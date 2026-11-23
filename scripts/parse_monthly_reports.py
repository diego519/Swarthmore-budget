#!/usr/bin/env python3
"""Parse the borough's monthly financial reports into tables.

Each monthly report to council (one per month since June 2021, with gaps; see
data/README.md) is a scan, read from the OCR output in data/ocr/. Two parts
are parsed:

* **Cover page** -- "Consolidated Revenues and Expenditures through the month
  of ...": year-to-date revenue and expenditure against the year's total
  budget, for this year and last, and the cash balance.

* **Current/Prior Year Comparison Report** -- the accounting system's
  budget-to-actual report, one section per fund (General, Sewer & Solid
  Waste, Highway Aid, Pension, Sinking) for revenue and then for expenses.
  Every ledger account is listed under its department with this year's
  budget, month-to-date (from August 2023) and year-to-date totals and the same
  figures for the prior year, followed by a subtotal per department, a
  subtotal per fund and a total.

The rest of each report (bank balances, wire transfers, open invoices, and from
2024 a department-level summary) is not parsed yet.

OCR misreads some figures (most often "$1" as "$7" or "$71"), so every
figure is checked against the others printed with it, and each line records
which of its figures a check confirmed:

* each line's printed percentage against year-to-date / budget, which
  confirms the budget and year-to-date figures to within the percentage's
  rounding;
* each department's lines against its printed subtotal, column by column,
  which confirms every figure in the column exactly;
* each fund's department subtotals against the fund subtotal, and the fund
  subtotal against the closing total.

Ledger ids are misread too, so each line's id is settled across all the
reports, which list the same accounts month after month: the fund and
department come from the section the line is printed in, and the account
number from the reading that the account's description is most often printed
with.

Outputs (in data/processed/):
    monthly_report_lines.csv     one row per ledger line, subtotal and total
    monthly_report_checks.csv    every arithmetic check and its result
    monthly_report_summary.csv   the cover pages' figures

Usage:
    uv run scripts/parse_monthly_reports.py [--doc-id ID ...]
"""

from __future__ import annotations

import argparse
import difflib
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from common import (
    CORRECTIONS_DIR,
    PROCESSED_DIR,
    Line,
    Word,
    check_ocr_is_current,
    downloaded_path,
    ocr_lines,
    read_csv,
    rel,
    sources_by_id,
    write_csv,
)

LINES_CSV = PROCESSED_DIR / "monthly_report_lines.csv"
CHECKS_CSV = PROCESSED_DIR / "monthly_report_checks.csv"
SUMMARY_CSV = PROCESSED_DIR / "monthly_report_summary.csv"
SOURCE_ERRORS_CSV = CORRECTIONS_DIR / "monthly_report_source_errors.csv"

AMOUNTS = ["budget", "mtd", "ytd", "prior_year_budget", "prior_year_mtd", "prior_year_ytd"]
LINE_FIELDS = [
    "doc_id", "period", "page", "statement", "fund_code", "fund", "department_code", "department",
    "ledger_id", "description", "row_type", *AMOUNTS, "percent", "prior_year_percent", "verified", "corrected",
    "ledger_id_as_read", "description_as_read",
]  # fmt: skip
CHECK_FIELDS = [
    "doc_id", "period", "page", "check", "statement", "fund_code", "department_code", "ledger_id",
    "column", "printed", "computed", "difference", "status",
]  # fmt: skip
SUMMARY_FIELDS = [
    "doc_id", "period", "page", "year", "measure", "amount", "total_budget", "printed_percent", "check", "note",
]  # fmt: skip

# Column layouts of the comparison report, left to right. "%" is the printed
# percentage of budget. Reports from 2021 have no month-to-date columns.
LAYOUT_8 = ["budget", "mtd", "ytd", "%", "prior_year_budget", "prior_year_mtd", "prior_year_ytd", "prior_%"]
LAYOUT_6 = ["budget", "ytd", "%", "prior_year_budget", "prior_year_ytd", "prior_%"]
COLUMN_GAP = 15  # points between the right edges of neighbouring columns' figures, at least
COLUMN_TOLERANCE = 12  # a figure's right edge lies within this of its column's

# Characters OCR substitutes for digits in these reports' figures.
DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "C": "0", "¢": "0", "€": "0", "G": "0", "l": "1", "I": "1",
                                  "|": "1", "]": "1", "!": "1", "B": "8", "S": "5", "s": "5"})  # fmt: skip
JUNK = " .,:;'\"‘’`°~=—–-_*^"


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


@dataclass
class Figure:
    """A dollar amount (in cents) or a percentage (in hundredths of a percent)
    as printed in one cell, and whether it had to be tidied to parse."""

    value: int
    text: str
    clean: bool
    corrected: bool = False  # read from a hand correction (data/corrections/ocr_corrections.csv)


def parse_money(text: str) -> Figure | None:
    """'$2,707,997.00', '($358.64)', '$0.0C' (cents clipped by the printer).
    Every amount in these reports is printed with a '$' and with cents."""
    t = text.strip(JUNK)
    if not re.search(r"\d", t) or "%" in t:
        return None
    negative = t.startswith("(") or t.endswith((")", "}"))
    t = t.strip("(){}[]" + JUNK)
    clean = bool(re.fullmatch(r"\$\d{1,3}(,\d{3})*\.\d\d", t))
    if not clean:
        dollar = t.startswith(("$", "S", "§"))
        t = t.lstrip("$S§")
        t = re.sub(r"[.,](\S)$", r".\g<1>0", t) if re.search(r"[.,]\S$", t) else t  # "$0.0" -> cents "00"
        t = t.translate(DIGIT_LOOKALIKES).replace(" ", "")
        m = re.fullmatch(r"(\d[\d,.]*?)[.,](\d\d)", t)
        if not m:
            return None
        dollars = m.group(1).replace(",", "").replace(".", "")
        if not dollar and len(m.group(1).split(",")[0]) == 4 and "," in m.group(1):
            dollars = dollars[1:]  # "3190,000.00": the "$" was read as a digit
        t = f"{dollars}.{m.group(2)}"
    value = round(float(t.replace("$", "").replace(",", "")) * 100)
    return Figure(-value if negative else value, text, clean)


def parse_percent(text: str) -> Figure | None:
    """'94.95%', '(12.50%)', '1,049.00%'."""
    t = text.strip(JUNK.replace("-", ""))
    if "%" not in t or not re.search(r"\d", t):
        return None
    negative = t.startswith(("(", "-"))  # "-15.62%" (a negative year-to-date)
    t = t.strip("(){}[]" + JUNK).rstrip("%").strip(JUNK)
    t = re.sub(r"[.,]{2,}", ".", t)  # "7,.54"
    clean = bool(re.fullmatch(r"\d{1,3}(,\d{3})*\.\d\d", t))
    if re.fullmatch(r"\d+,\d\d", t):
        t = t.replace(",", ".")  # "76,38%": a comma read for the decimal point
    t = t.translate(DIGIT_LOOKALIKES).replace(",", "")
    if not re.fullmatch(r"\d+\.\d\d", t):
        return None
    value = round(float(t) * 100)
    return Figure(-value if negative else value, text, clean)


def is_figure_like(text: str) -> bool:
    t = text.strip(JUNK)
    return bool(re.search(r"\d", t)) and bool(re.search(r"[$%]|\d[.,]\d", t))


def looks_complete(text: str) -> bool:
    """Whether a figure's text ends as a whole figure does (cents or %)."""
    return bool(re.search(r"[.,]\S\S\)?\W?$|%\)?\W?$", text))


def merge_fragments(words: list[Word]) -> list[Word]:
    """Rejoin figures OCR split in two, e.g. '$29' + '838.93' or '847' + '50%'."""
    out: list[Word] = []
    for w in sorted(words, key=lambda w: w.x0):
        if out and not looks_complete(out[-1].text) and w.x0 - out[-1].x1 < 8:
            p = out[-1]
            # "$62,996" + "80": the decimal point was lost between dollars and cents.
            sep = "." if re.fullmatch(r"\d\d", w.text) and re.fullmatch(r"\(?\$[\d,]+", p.text) else ""
            out[-1] = Word(
                p.text + sep + w.text, p.x0, p.top, w.x1, p.bottom, min(p.conf, w.conf), p.corrected
            )
        else:
            out.append(w)
    return out


# --------------------------------------------------------------------------
# Comparison report pages
# --------------------------------------------------------------------------

LEDGER_ID = re.compile(r"^\W?(\d{1,4})\s*-\s*(\d{3})\s*-\s*(\d{3,4})\W?$")
# Shaped like a ledger id but with characters misread ("C4-427-375", "04-430-*72", "04-427-38%").
GARBLED_LEDGER_ID = re.compile(r"^\W?\S{1,4}-\S{3}-\S{3,4}$")
CODE_AND_NAME = re.compile(r"^\W*[\(\{\[]?\s*([0-9OoIl]{2,3})\s*[\)\}\]!|]?\W*\s+(.*?)[:;.,]*$")
YEAR_PERIOD = re.compile(r"Year\W*(\d{4})\W*Period\W*(\d{1,2})", re.IGNORECASE)


@dataclass
class Row:
    page: int
    # "item", "department_subtotal", "fund_subtotal", "total", or a heading
    # (no figures): "fund_heading", "department_heading"
    kind: str
    code: str  # ledger id as read (items) or the "(NNN)" code printed in a subtotal or heading
    label: str  # description (items) or name (subtotals, headings)
    cells: dict[str, Figure | None]
    statement: str = ""  # "revenue" or "expense"
    fund_block: int = 0  # rows of one fund's revenue or expenses share a fund block
    dept_block: int = 0  # rows of one department within it share a department block
    fund_code: str = ""
    fund: str = ""
    department_code: str = ""
    department: str = ""
    ledger_id: str = ""
    description: str = ""
    verified: set[str] = field(default_factory=set)


def page_title(lines: list[Line]) -> str:
    """'revenue', 'expense' or '' from the report title ('... Comparison
    Report - Revenue') or the line under it ('PriorYrRev: Year (2026) ...').
    Either can be lost to OCR."""
    for line in lines[:4]:
        t = re.sub(r"\s+", "", line.text.lower())
        if "comparison" in t or "prior" in t:
            if re.search(r"revenue|yrrev", t):
                return "revenue"
            if re.search(r"expen|yrexp", t):
                return "expense"
    return ""


def find_header(lines: list[Line]) -> tuple[int, list[str]] | None:
    """Index of the column header line ('Ledger ID  Ledger Description  Budget
    MTD Total  YTD Total  %  ...') and the page's column layout."""
    for i, line in enumerate(lines):
        t = [re.sub(r"[^a-z0-9]", "", w.text.lower()) for w in line.words]  # "_Budget_", "Tota!"
        # Words of "YTD Total" ("YTD", "YTO", "YTOTotaa", "Tota!") and of the other headings.
        totals = sum(bool(re.search(r"t[o0]ta|^yt[a-z]?$", x)) for x in t)
        if any(re.search(r"ledger|descr|^.?udget", x) for x in t) and totals >= 2:
            totals = sum(bool(re.search(r"t[o0]ta", x)) for x in t)
            return i, (LAYOUT_8 if totals >= 3 or "mtd" in t else LAYOUT_6)
    return None


def column_edges(rows: list[list[Word]], layout: list[str]) -> list[float] | None:
    """Right edges of the figure columns. Figures are right-aligned, so their
    right edges cluster tightly, one cluster per column."""
    x1s = sorted(w.x1 for words in rows for w in words)
    clusters: list[list[float]] = []
    for x in x1s:
        if clusters and x - clusters[-1][-1] < COLUMN_GAP:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    if len(clusters) > len(layout):  # stray marks: keep the best-populated clusters, in order
        keep = sorted(sorted(clusters, key=len, reverse=True)[: len(layout)], key=lambda c: c[0])
        clusters = keep
    if len(clusters) != len(layout):
        return None
    return [statistics.median(c) for c in clusters]


def parse_comparison_page(page_number: int, lines: list[Line]) -> tuple[list[Row], dict]:
    """Rows (including headings) of one comparison-report page, in printed order."""
    info: dict = {"statement": page_title(lines)}
    for line in lines[:4]:
        m = YEAR_PERIOD.search(line.text.replace(" ", ""))
        if m:
            info["year"], info["period"] = int(m.group(1)), int(m.group(2))
    header = find_header(lines)
    if not header:
        return [], info
    start, layout = header
    info["layout"] = len(layout)

    body = []
    for line in lines[start + 1 :]:
        if re.match(r"^\W*Page\W", line.text):
            break
        figures = merge_fragments([w for w in line.words if is_figure_like(w.text)])
        body.append((line, figures))

    edges = column_edges([f for _, f in body if len(f) == len(layout)] or [f for _, f in body], layout)
    if not edges:
        raise ValueError(f"p{page_number}: could not find the {len(layout)} figure columns")
    # Only words in a figure column are figures ("04-427-38%", a misread ledger id, is not).
    body = [
        (line, [w for w in f if min(abs(w.x1 - e) for e in edges) <= COLUMN_TOLERANCE]) for line, f in body
    ]
    left_of_figures = min(
        (w.x0 for _, f in body for w in f if abs(w.x1 - edges[0]) <= COLUMN_TOLERANCE), default=1e9
    )

    rows: list[Row] = []

    def heading(text: str) -> Row | None:
        m = CODE_AND_NAME.match(text)
        if not (m and re.search(r"[A-Za-z]{3}", m.group(2))):
            return None
        code, name = m.group(1).translate(DIGIT_LOOKALIKES), m.group(2)
        is_fund = len(code) == 2 or (len(code) != 3 and bool(match_fund(name, "")))
        return Row(page_number, "fund_heading" if is_fund else "department_heading", code, name, {})

    for line, figures in body:
        words = [w for w in line.words if w not in figures]
        if figures:
            # OCR sometimes merges a heading into the row printed just below it; the
            # heading's words sit higher than the row's figures.
            height = statistics.median(w.bottom - w.top for w in figures)
            row_yc = statistics.median(w.yc for w in figures)
            above = [w for w in words if w.yc < row_yc - 0.5 * height]
            above_heading = heading(" ".join(w.text for w in above)) if above else None
            if above_heading:
                rows.append(above_heading)
                words = [w for w in words if w not in above]
        text = " ".join(w.text for w in words if w.x1 <= left_of_figures + 5).strip()
        if not figures:
            if h := heading(text):
                rows.append(h)
            continue
        cells: dict[str, Figure | None] = dict.fromkeys(layout)
        for w in figures:
            distances = [abs(w.x1 - e) for e in edges]
            i = distances.index(min(distances))
            if distances[i] > COLUMN_TOLERANCE:
                continue
            col = layout[i]
            parsed = parse_percent(w.text) if col.endswith("%") else parse_money(w.text)
            if parsed and cells[col] is None:
                parsed.corrected = w.corrected
                cells[col] = parsed
        if sum(v is not None for v in cells.values()) < 2:
            continue  # a stray mark, not a row

        low = text.lower()
        first_word = re.sub(r"[^a-z]", "", low.split()[0]) if low.split() else ""
        # "Subtotal", "Subfotal", "Subtetal" (but not "Total")
        is_subtotal = (
            first_word.startswith("s")
            and difflib.SequenceMatcher(None, first_word, "subtotal").ratio() >= 0.75
        )
        if is_subtotal or "subtot" in low:
            rest = re.sub(r"^\W*\S+\s*", "", text)  # drop the word "Subtotal"
            m = CODE_AND_NAME.match(rest)
            code, name = (m.group(1).translate(DIGIT_LOOKALIKES), m.group(2)) if m else ("", rest)
            # "(392) Interfund Operating Transfers" is a department; "(04) SEWER & SOLID WASTE FUND" a fund.
            is_fund = len(code) == 2 or (len(code) != 3 and bool(match_fund(name, "")))
            kind = "fund_subtotal" if is_fund else "department_subtotal"
            rows.append(Row(page_number, kind, code, name.strip(" :;"), cells))
        elif re.match(r"^\W*t[o0]ta", low):
            rows.append(Row(page_number, "total", "", "Total", cells))
        else:
            left = [w for w in words if w.x1 <= left_of_figures + 5]
            first = left[0].text if left else ""
            if LEDGER_ID.match(first) or GARBLED_LEDGER_ID.match(first):
                ledger, desc_words = first, [w.text for w in left[1:]]
            else:  # the id is not first (a heading OCR merged in, unseparated): take it from where it is
                found = next((w for w in left if LEDGER_ID.match(w.text)), None)
                ledger = found.text if found else ""
                desc_words = [w.text for w in left if w is not found and (not found or w.x0 > found.x1)]
            description = " ".join(t for t in desc_words if re.search(r"[A-Za-z0-9&/]", t)).strip(" :;.,")
            rows.append(Row(page_number, "item", ledger, description, cells))
    return rows, info


# --------------------------------------------------------------------------
# Sections: which fund and department each row belongs to
# --------------------------------------------------------------------------

FUND_NAMES = {
    "01": "GENERAL FUND",
    "04": "SEWER & SOLID WASTE FUND",
    "05": "HIGHWAY AID FUND",
    "09": "PENSION FUND",
    "10": "SINKING FUND",
}


def match_fund(name: str, code: str) -> str:
    """A fund's code from its printed name (more reliable than the printed code)."""
    t = re.sub(r"[^A-Z& ]", "", name.upper()).strip()
    best = max(FUND_NAMES, key=lambda c: difflib.SequenceMatcher(None, t, FUND_NAMES[c]).ratio())
    if difflib.SequenceMatcher(None, t, FUND_NAMES[best]).ratio() >= 0.75:
        return best
    return code if code in FUND_NAMES else ""


HEADINGS = ("fund_heading", "department_heading")


def assign_sections(rows: list[Row]) -> None:
    """Give each row its fund and department.

    The rows are first cut into blocks. A fund's revenue or expenses form one
    fund block, which starts at the fund's heading (or where the statement
    changes from revenue to expenses) and ends with the fund's subtotal. A
    department's rows form a department block, which starts at its heading
    and ends with its subtotal. Since OCR sometimes loses a heading or a
    subtotal, either one is enough to separate two blocks.

    Codes are read in several places, and each is sometimes misread, so a
    block's code is decided by vote: a department's among its heading, its
    subtotal and the middle part of its lines' ledger ids; a fund's among its
    heading's and subtotal's names and its lines' ledger id prefixes.
    """
    fund_block = dept_block = 0
    fund_used = dept_used = False  # whether the current block has rows yet
    statement = None
    last = None  # the previous row that is not a heading
    for r in rows:
        if r.kind == "item" and not r.code and last and last.kind == "fund_subtotal":
            # A total whose label ("Totals=====") OCR lost or garbled ("Sassessess"): it
            # repeats the fund subtotal above it.
            same = sum(f is not None and f.value == value(last, c) for c, f in r.cells.items())
            if same >= 2:
                r.kind = "total"
        new_fund = r.kind == "fund_heading" or r.statement != statement
        if new_fund and fund_used:
            fund_block, fund_used = fund_block + 1, False
        if (new_fund or r.kind == "department_heading") and dept_used:
            dept_block, dept_used = dept_block + 1, False
        statement = r.statement
        if r.kind == "total" and last is not None and last.kind == "fund_subtotal":
            r.fund_block, r.dept_block = last.fund_block, last.dept_block  # repeats the fund subtotal
            continue
        r.fund_block, r.dept_block = fund_block, dept_block
        if r.kind not in HEADINGS:
            fund_used = dept_used = True
            last = r
        if r.kind == "department_subtotal":
            dept_block, dept_used = dept_block + 1, False
        elif r.kind in ("fund_subtotal", "total"):
            fund_block, dept_block, fund_used, dept_used = fund_block + 1, dept_block + 1, False, False

    by_fund: dict[int, list[Row]] = defaultdict(list)
    by_dept: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        by_fund[r.fund_block].append(r)
        by_dept[r.dept_block].append(r)

    for block in by_fund.values():
        votes: Counter = Counter()
        for r in block:
            if r.kind in ("fund_heading", "fund_subtotal"):
                code = match_fund(r.label, r.code)
                if code:
                    votes[code] += 3
            elif r.kind == "item":
                m = re.fullmatch(r"(\d\d)-\d{3}-\d{3}", r.code)
                if m and m.group(1) in FUND_NAMES:
                    votes[m.group(1)] += 1
        code = votes.most_common(1)[0][0] if votes else ""
        for r in block:
            r.fund_code, r.fund = code, FUND_NAMES.get(code, "")

    for block in by_dept.values():
        votes = Counter()
        names = []
        for r in block:
            if r.kind in ("department_heading", "department_subtotal"):
                if re.fullmatch(r"\d{3}", r.code):
                    votes[r.code] += 2
                names.append(r.label)
            elif r.kind == "item":
                m = LEDGER_ID.match(r.code)
                if m:
                    votes[m.group(2)] += 1
        if not any(r.kind in ("item", "department_heading", "department_subtotal") for r in block):
            continue  # fund subtotals and totals belong to no department
        code = votes.most_common(1)[0][0] if votes else ""
        name = names[-1] if names else ""  # the subtotal's spelling, else the heading's
        for r in block:
            if r.kind in ("item", "department_heading", "department_subtotal"):
                r.department_code, r.department = code, name


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def value(row: Row, col: str) -> int | None:
    f = row.cells.get(col)
    return f.value if f else None


def check_row_percent(row: Row, years: list[tuple[str, str, str]]) -> list[dict]:
    """The printed percentage against year-to-date / budget. A match confirms
    the budget (if the year-to-date is not zero) and the year-to-date (if the
    budget is not zero), to within the percentage's rounding."""
    out = []
    for budget_col, ytd_col, pct_col in years:
        b, y, p = value(row, budget_col), value(row, ytd_col), value(row, pct_col)
        if b is None or y is None or p is None:
            status = "unreadable"
        elif b == 0:
            status = "ok" if p == 0 else "FAIL"  # the system prints 0.00% when there is no budget
        else:
            status = "ok" if abs(y / b * 10000 - p) <= 1 else "FAIL"
        if status == "ok" and b:
            row.verified.add(ytd_col)
            if y:
                row.verified.add(budget_col)
        out.append(
            {"check": "line percent", "column": pct_col, "printed": p,
             "computed": round(y / b * 10000) if b and y is not None else None, "status": status}
        )  # fmt: skip
    return out


def check_sum(printed: Row, parts: list[Row], columns: list[str], check: str) -> list[dict]:
    """A printed subtotal or total against the sum of the rows it covers. A
    match confirms every figure in that column, exactly."""
    out = []
    for col in columns:
        p = value(printed, col)
        vals = [value(r, col) for r in parts]
        if p is None or any(v is None for v in vals):
            status, computed = "unreadable", None
        else:
            computed = sum(vals)
            status = "ok" if computed == p else "FAIL"
        if status == "ok":
            for r in [printed, *parts]:
                r.verified.add(col)
        out.append({"check": check, "column": col, "printed": p, "computed": computed, "status": status})
    return out


def run_checks(rows: list[Row], layout: list[str]) -> list[dict]:
    amount_cols = [c for c in layout if not c.endswith("%")]
    years = [("budget", "ytd", "%"), ("prior_year_budget", "prior_year_ytd", "prior_%")]
    rows = [r for r in rows if r.kind not in HEADINGS]
    checks = []

    def add(results: list[dict], row: Row) -> None:
        for c in results:
            checks.append(
                {"page": row.page, "statement": row.statement, "fund_code": row.fund_code,
                 "department_code": row.department_code, "ledger_id": row.ledger_id or row.code, **c}
            )  # fmt: skip

    for r in rows:
        add(check_row_percent(r, years), r)

    with_subtotal = set()
    for block in group_by(rows, "dept_block"):
        subtotals = [r for r in block if r.kind == "department_subtotal"]
        if subtotals:
            with_subtotal.add(block[0].dept_block)
            items = [r for r in block if r.kind == "item"]
            add(check_sum(subtotals[0], items, amount_cols, "department subtotal"), subtotals[0])

    for block in group_by(rows, "fund_block"):
        closing = [r for r in block if r.kind == "fund_subtotal"]
        totals = [r for r in block if r.kind == "total"]
        if not closing and totals:  # the fund subtotal was lost; the total stands in for it
            closing, totals = totals, []
        if not closing:
            continue
        # Departments' subtotals, plus the lines of any department whose subtotal was lost.
        parts = [
            r
            for r in block
            if r.kind == "department_subtotal" or (r.kind == "item" and r.dept_block not in with_subtotal)
        ]
        add(check_sum(closing[0], parts, amount_cols, "fund subtotal"), closing[0])
        if totals:
            add(check_sum(totals[0], [closing[0]], amount_cols, "total"), totals[0])
    return checks


def group_by(rows: list[Row], attr: str) -> list[list[Row]]:
    groups: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        groups[getattr(r, attr)].append(r)
    return list(groups.values())


# --------------------------------------------------------------------------
# Cover page
# --------------------------------------------------------------------------


def parse_cover(lines: list[Line], report_year: int) -> list[dict]:
    """The cover page's figures: for this year and last, revenue and
    expenditure to date, the total budget and the percentage; then the cash
    balance at the start of the year and at the report date.

    The page has a block of figures under a heading for each year, this year
    first. The headings are sometimes misread, so each block's year is taken
    from its position."""
    out = []
    year = None
    blocks = 0
    cash = False
    for line in lines:
        t = line.text
        compact = re.sub(r"\W", "", t.upper())
        if "CASHBALANCE" in compact or "BEGINNINGBALANCE" in compact:  # (either can be lost to OCR)
            cash, year = True, report_year
            continue
        if re.fullmatch(r"\W*(20\d\d|2\d{3})\W*", t) and not cash:
            year, blocks = report_year - blocks, blocks + 1
            continue
        figures = cover_amounts(t)
        pm = re.search(r"(\d+(?:[.,]\d+)?)\s?%", t)  # "96.9%", "110.11%"
        percent = pm.group(1).replace(",", ".") if pm else None
        # OCR sometimes puts a stray mark before the label ("lo REVENUES").
        label = re.search(r"REVENUE|EXPEND", compact[:12])
        if not cash and year and len(figures) >= 2 and label:
            measure = "revenue" if label.group() == "REVENUE" else "expenditure"
            amount, budget = figures[0], figures[1]
            check = ""
            if percent is not None and budget:
                # Within half a unit of the percentage's last printed decimal place.
                places = len(percent.split(".")[1]) if "." in percent else 0
                check = (
                    "ok" if abs(amount / budget * 100 - float(percent)) <= 0.5 / 10**places + 1e-9 else "FAIL"
                )
            out.append(
                {"year": year, "measure": measure, "amount": amount, "total_budget": budget,
                 "printed_percent": percent or "", "check": check}
            )  # fmt: skip
        elif cash and len(figures) == 2:
            for measure, amount in zip(("cash_beginning_balance", "cash_balance"), figures, strict=True):
                out.append({"year": year, "measure": measure, "amount": amount, "total_budget": "",
                            "printed_percent": "", "check": ""})  # fmt: skip
            cash = False
    return out


def cover_amounts(text: str) -> list[int]:
    """Whole-dollar amounts on a cover-page line: '$8,296,328', '$6,.361,864', '$ 972,687'."""
    return [int(re.sub(r"\D", "", m)) for m in re.findall(r"[$S§]\s?(\d[\d,.]*\d)", text)]


# --------------------------------------------------------------------------
# Ledger ids across reports
# --------------------------------------------------------------------------


def letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def settle_department_codes(docs_rows: list[tuple[dict, Row]]) -> list[str]:
    """Correct department codes that the section vote got wrong.

    Within one report a department's code is decided by vote among its
    heading, subtotal and lines (assign_sections), so two misread codes can
    outvote a correct one: in January 2025, "(439) Construction & Rebuilding"
    was printed with a subtotal and a line both misread as 438. A
    department's name is read more reliably than its code, and each name is
    printed with the same code in report after report. So where a
    department's name is one that the other reports print, at least nine
    times in ten, with a different code, that code is used. Returns a
    description of each change."""
    votes: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for _, r in docs_rows:
        if r.kind == "department_subtotal" and r.department_code and letters(r.label):
            votes[(r.statement, letters(r.label))][r.department_code] += 1
    popular = {k: c for k, c in votes.items() if sum(c.values()) >= 10}
    blocks: dict[tuple[str, int], list[Row]] = defaultdict(list)
    for doc, r in docs_rows:
        if r.kind in ("item", "department_subtotal", "department_heading"):
            blocks[(doc["doc_id"], r.dept_block)].append(r)
    changes = []
    for (doc_id, _), block in blocks.items():
        name = next((r.department for r in block if r.department), "")
        statement = block[0].statement
        key = (statement, letters(name))
        if key not in popular:
            close = difflib.get_close_matches(
                key[1], [k[1] for k in popular if k[0] == statement], n=1, cutoff=0.85
            )
            key = (statement, close[0]) if close else key
        if key not in popular:
            continue
        code, n = popular[key].most_common(1)[0]
        current = block[0].department_code
        if code != current and n >= 0.9 * sum(popular[key].values()):
            for r in block:
                r.department_code = code
            changes.append(f"{doc_id}: {name!r} {current} -> {code}")
    return changes


def settle_ledger_ids(rows: list[Row]) -> None:
    """Give each line a ledger id and description that are consistent across
    reports.

    Within a fund and department, the account number (the id's last part)
    printed with each description is counted over every report; a line's
    account number is the one its description is most often printed with,
    and a description's spelling is the one most often printed with that id.
    """
    by_dept: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        if r.kind == "item":
            by_dept[(r.fund_code, r.department_code)].append(r)
    for (fund, dept), items in by_dept.items():
        # Votes for each description's account number.
        votes: dict[str, Counter] = defaultdict(Counter)
        for r in items:
            m = LEDGER_ID.match(r.code)
            if m and letters(r.label):
                votes[letters(r.label)][m.group(3)[-3:]] += 1
        # A spelling seen once or twice that is close to one seen far more often is a
        # misreading of it ("FRIOR YEAR FOREIGN CASUALTY"), and so is its account number.
        popular = [k for k in votes if sum(votes[k].values()) >= 5]
        for key in [k for k in votes if sum(votes[k].values()) <= 2]:
            close = difflib.get_close_matches(key, popular, n=1, cutoff=0.85)
            if close:
                votes[key] = votes[close[0]]
        descriptions = list(votes)
        for r in items:
            key = letters(r.label)
            if key not in votes:  # description unread or garbled: the closest one read elsewhere
                close = difflib.get_close_matches(key, descriptions, n=1, cutoff=0.8)
                key = close[0] if close else key
            if key in votes:
                account = votes[key].most_common(1)[0][0]
            else:
                m = LEDGER_ID.match(r.code)
                account = m.group(3)[-3:] if m else "???"
            r.ledger_id = f"{fund or '??'}-{dept or '???'}-{account}"
        # Each id's description: its most common spelling.
        spellings: dict[str, Counter] = defaultdict(Counter)
        for r in items:
            spellings[r.ledger_id][r.label] += 1
        for r in items:
            r.description = spellings[r.ledger_id].most_common(1)[0][0]


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


def parse_report(doc: dict) -> tuple[list[Row], list[dict], list[dict], list[str]]:
    """Rows, checks and cover-page figures of one report, plus warnings."""
    doc_id = doc["doc_id"]
    check_ocr_is_current(doc_id, downloaded_path(doc_id))
    pages = ocr_lines(doc_id)
    warnings = []
    rows: list[Row] = []
    infos = []
    cover = parse_cover(pages.get(1, []), int(doc["period"][:4]))
    statement = ""
    for number in sorted(pages):
        page_rows, info = parse_comparison_page(number, pages[number])
        if not any(r.kind not in HEADINGS for r in page_rows):
            continue
        # Without a legible title, judge by the lines' departments: 3xx are revenue, 4xx expenses.
        kinds = Counter(
            "revenue" if m.group(2)[0] == "3" else "expense"
            for r in page_rows
            if (m := LEDGER_ID.match(r.code)) and m.group(2)[0] in "34"
        )
        statement = info["statement"] or (kinds.most_common(1)[0][0] if kinds else statement)
        for r in page_rows:
            r.statement = statement
        rows += page_rows
        infos.append(info)
    if not rows:
        return [], [], cover, ["no comparison report found"]

    layouts = Counter(i["layout"] for i in infos)
    layout = LAYOUT_8 if layouts.most_common(1)[0][0] == 8 else LAYOUT_6
    periods = Counter((i["year"], i["period"]) for i in infos if "year" in i)
    if periods:
        (year, month), _ = periods.most_common(1)[0]
        if f"{year}-{month:02d}" != doc["period"]:
            warnings.append(f"report says year {year} period {month}; catalogued as {doc['period']}")
    assign_sections(rows)
    checks = run_checks(rows, layout)
    return rows, checks, cover, warnings


def mark_source_errors(summary: list[dict]) -> None:
    """Mark cover-page checks that fail because of a mistake in the document
    itself, as recorded (and checked by eye) in
    data/corrections/monthly_report_source_errors.csv."""
    known = {
        (r["doc_id"], r["year"], r["measure"]): r["note"]
        for r in read_csv(SOURCE_ERRORS_CSV)
        if r["check"] == "cover percent"
    }
    used = set()
    for c in summary:
        key = (c["doc_id"], str(c["year"]), c["measure"])
        if c.get("check") == "FAIL" and key in known:
            c["check"], c["note"] = "source error", known[key]
            used.add(key)
    for key in sorted(set(known) - used):
        print(
            f"warning: {rel(SOURCE_ERRORS_CSV)} lists {key}, but that cover check does not fail",
            file=sys.stderr,
        )


def fmt(cents: int | None) -> str:
    return "" if cents is None else f"{cents / 100:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--doc-id", action="append", help="parse only this report (repeatable)")
    args = parser.parse_args()

    reports = sorted(
        (
            r
            for r in sources_by_id().values()
            if r["category"] == "monthly_report" and r["include"] == "yes"
            and (not args.doc_id or r["doc_id"] in args.doc_id)
        ),
        key=lambda r: (r["period"], r["doc_id"]),
    )  # fmt: skip
    all_rows: list[tuple[dict, Row]] = []
    all_checks: list[dict] = []
    summary: list[dict] = []
    for doc in reports:
        rows, checks, cover, warnings = parse_report(doc)
        base = {"doc_id": doc["doc_id"], "period": doc["period"]}
        all_rows += [(doc, r) for r in rows if r.kind not in HEADINGS]
        all_checks += [base | c for c in checks]
        summary += [base | {"page": 1} | c for c in cover]
        ok = sum(c["status"] == "ok" for c in checks)
        print(
            f"{doc['doc_id']} {doc['period']}: {sum(r.kind == 'item' for r in rows)} lines, "
            f"checks {ok}/{len(checks)} ok" + "".join(f"\n  warning: {w}" for w in warnings)
        )

    for change in settle_department_codes(all_rows):
        print(f"department code settled by name: {change}")
    settle_ledger_ids([r for _, r in all_rows])
    out_rows = []
    for doc, r in all_rows:
        out_rows.append(
            {
                "doc_id": doc["doc_id"],
                "period": doc["period"],
                "page": r.page,
                "statement": r.statement,
                "fund_code": r.fund_code,
                "fund": r.fund,
                "department_code": r.department_code,
                "department": r.department,
                "ledger_id": r.ledger_id if r.kind == "item" else "",
                "description": r.description if r.kind == "item" else r.label,
                "row_type": r.kind,
                **{c: fmt(value(r, c)) for c in AMOUNTS},
                "percent": fmt(value(r, "%")),
                "prior_year_percent": fmt(value(r, "prior_%")),
                "verified": ";".join(c for c in AMOUNTS if c in r.verified),
                "corrected": ";".join(c for c in AMOUNTS if r.cells.get(c) and r.cells[c].corrected),
                "ledger_id_as_read": r.code if r.kind == "item" else "",
                "description_as_read": r.label if r.kind == "item" else "",
            }
        )
    for c in all_checks:
        c["difference"] = (
            fmt(c["computed"] - c["printed"]) if None not in (c["computed"], c["printed"]) else ""
        )
        pct = c["column"].endswith("%")
        for k in ("printed", "computed"):
            c[k] = "" if c[k] is None else (f"{c[k] / 100:.2f}" if pct else fmt(c[k]))
    write_csv(LINES_CSV, LINE_FIELDS, out_rows)
    write_csv(CHECKS_CSV, CHECK_FIELDS, all_checks)
    mark_source_errors(summary)
    write_csv(SUMMARY_CSV, SUMMARY_FIELDS, summary)

    statuses = Counter(c["status"] for c in all_checks)
    figures = [(r, c) for _, r in all_rows for c in AMOUNTS if value(r, c) is not None]
    verified = sum(c in r.verified for r, c in figures)
    print(f"Wrote {rel(LINES_CSV)}, {rel(CHECKS_CSV)} and {rel(SUMMARY_CSV)}")
    print(f"Checks: {dict(statuses)}")
    print(
        f"Figures confirmed by a check: {verified}/{len(figures)} ({100 * verified / max(len(figures), 1):.1f}%)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
