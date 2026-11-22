#!/usr/bin/env python3
"""Parse the borough's adopted budgets into tables.

The adopted budgets come in two layouts:

* **Summary** -- every year, 2017-2026. One row per spending or revenue
  program ("Police Services - Personnel"), with the prior year's budget, the
  prior year's estimated actual (not in 2026), and the new year's budget.
  Rows are grouped under headings and followed by subtotals and totals.

* **Line items** -- only the 2023, 2024 and 2025 budgets. Small tables of
  individual ledger accounts: Fund | Account | Account # | prior-year budget |
  new budget, each ending in a printed Total.

2017-2022 and 2026 have a PDF text layer. 2023-2025 are scans and are read
from the OCR output in data/ocr/ (see ocr_documents.py). Both kinds of input
are turned into words with page coordinates, and from there the same code
parses them.

OCR makes mistakes. They are fixed by hand, word by word, in
data/corrections/ocr_corrections.csv (applied when the OCR output is loaded;
see common.apply_ocr_corrections). Each fix names the word as OCR read it, so
if OCR output changes, a stale fix fails loudly instead of silently editing
the wrong number. Every corrected value is flagged in the output's
`corrected` column.

To catch errors, every subtotal and total printed in the documents is
checked against the sum of the rows it covers. Results go to
data/processed/budget_checks.csv; differences that are mistakes in the
borough's own document (not OCR errors) are explained in
data/corrections/budget_source_errors.csv.

Outputs (in data/processed/):
    budget_summary.csv      one row per summary line, all years
    budget_line_items.csv   one row per ledger account line, 2023-2025
    budget_checks.csv       every arithmetic check and its result

Usage:
    uv run scripts/parse_budgets.py [--strict]

Failed checks are listed when the script finishes; with --strict it also
exits with an error status, for use in automated checks.
"""

from __future__ import annotations

import argparse
import difflib
import re
import statistics
import sys
from dataclasses import dataclass, field

import pdfplumber
from common import (
    CORRECTIONS_DIR,
    OCR_DIR,
    OCR_MANIFEST_CSV,
    PROCESSED_DIR,
    Line,
    Word,
    downloaded_path,
    ocr_lines,
    read_csv,
    rel,
    sha256_of,
    sources_by_id,
    text_layer_lines,
    write_csv,
)

SOURCE_ERRORS_CSV = CORRECTIONS_DIR / "budget_source_errors.csv"
SUMMARY_CSV = PROCESSED_DIR / "budget_summary.csv"
LINE_ITEMS_CSV = PROCESSED_DIR / "budget_line_items.csv"
CHECKS_CSV = PROCESSED_DIR / "budget_checks.csv"

SUMMARY_FIELDS = [
    "doc_id", "fiscal_year", "page", "extraction", "section", "group", "subgroup", "item", "row_type",
    "prior_year_budget", "prior_year_estimated_actual", "budget", "corrected",
]  # fmt: skip
LINE_ITEM_FIELDS = [
    "doc_id", "fiscal_year", "page", "extraction", "section", "group", "table", "fund", "account",
    "account_number", "prior_year_budget", "budget", "corrected", "table_check",
]  # fmt: skip
CHECK_FIELDS = [
    "doc_id",
    "page",
    "check",
    "printed_row",
    "column",
    "printed",
    "computed",
    "difference",
    "status",
    "note",
]
AMOUNT_COLUMNS = ["prior_year_budget", "prior_year_estimated_actual", "budget"]
# The borough's spreadsheets show each figure rounded to the dollar, so a
# printed total of n rows can differ from the sum of the printed rows by up to
# n/2 dollars. Such differences are reported as "rounding", not failures.

# Expenditure groups, as headed in the documents.
GROUPS = ["GENERAL GOVERNMENT", "PUBLIC SAFETY", "PUBLIC WORKS", "COMMUNITY SERVICES"]


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

# Stray marks that OCR produces from table borders, plus "$" look-alikes.
JUNK = "_|—–~\"'‘’“”«»=:;!¦[]{}§•*^`°"
YEAR_RE = re.compile(r"^20[12]\d$")
ACCOUNT_NUMBER_RE = re.compile(r"^\d{3}\.\d{3,4}$")


def clean(text: str) -> str:
    return text.strip(JUNK + " ")


def has_letters(text: str) -> bool:
    return sum(c.isalpha() for c in text) >= 2


def parse_amount(text: str) -> int | None:
    """Parse a dollar amount such as "$1,234", "(1,234)", "1234." or "$0".
    Returns None if the text is not an amount. Budgets are in whole dollars."""
    t = clean(text).replace("$", "").replace("§", "").strip(JUNK + " ").rstrip(".,")
    # The budgets show negative amounts in parentheses. A leading dash is OCR
    # noise from a table border, not a minus sign.
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()-").rstrip(".,")
    if not re.fullmatch(r"\d[\d,.]*", t):
        # OCR noise around a well-formed number, e.g. "—s-8,391/": take the number.
        m = re.search(r"\d{1,3}(?:,\d{3})+", text)
        return int(m.group().replace(",", "")) if m else None
    if re.search(r"\.\d{2}$", t) and not re.search(r"[.,]\d{3}$", t):
        t = t[:-3]  # drop cents
    value = int(re.sub(r"\D", "", t))
    return -value if negative else value


def is_year(text: str) -> bool:
    return bool(YEAR_RE.match(re.sub(r"\D", "", text))) and len(clean(text)) <= 6


def is_column_year(text: str) -> bool:
    """A year in a column header. Only its position matters, so accept any
    three to five digits: OCR sometimes misreads or splits a header year
    ("3923", "20230", "s 023")."""
    return bool(re.fullmatch(r"\d{3,5}", re.sub(r"\D", "", clean(text)))) and len(clean(text)) <= 7


def fuzzy_is(text: str, target: str, cutoff: float = 0.75) -> bool:
    t = re.sub(r"[^a-z#]", "", text.lower())
    return difflib.SequenceMatcher(None, t, target).ratio() >= cutoff


def pick_amount(words: list[Word]) -> tuple[int | None, bool]:
    """The amount in one table cell, and whether it was hand-corrected. OCR
    sometimes adds stray marks or a lone "0" from a border, so prefer the
    candidate with a "$" and the most digits."""
    candidates = [(w, parse_amount(w.text)) for w in words]
    # A lone digit other than 0 is a misread "$", a page number or a stray
    # mark, never a budget figure.
    candidates = [(w, v) for w, v in candidates if v is not None and (abs(v) >= 10 or v == 0)]
    if not candidates:
        # A zero is printed as "$ -" (accounting format).
        texts = [w.text.strip() for w in words]
        has_dollar = any(t.rstrip("-—–") in ("$", "S", "§") for t in texts)
        has_dash = any(t and t[-1] in "-—–" for t in texts)
        return (0 if has_dollar and has_dash else None), any(w.corrected for w in words)
    best = max(candidates, key=lambda wv: ("$" in wv[0].text, len(re.sub(r"\D", "", wv[0].text))))
    return best[1], best[0].corrected


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


@dataclass
class Page:
    doc_id: str
    number: int
    extraction: str  # "text" (PDF text layer) or "ocr"
    lines: list[Line]


def load_pages(doc_id: str) -> list[Page]:
    """Every page of a document as lines of words, from the PDF's text layer
    where there is one and from the OCR output otherwise."""
    path = downloaded_path(doc_id)
    ocr = None
    pages = []
    with pdfplumber.open(path) as pdf:
        for number, pdf_page in enumerate(pdf.pages, 1):
            if len(pdf_page.chars) >= 20:
                pages.append(Page(doc_id, number, "text", text_layer_lines(pdf_page)))
                continue
            if ocr is None:
                check_ocr_is_current(doc_id, path)
                ocr = ocr_lines(doc_id)
            pages.append(Page(doc_id, number, "ocr", ocr.get(number, [])))
    return pages


def check_ocr_is_current(doc_id: str, path) -> None:
    for r in read_csv(OCR_MANIFEST_CSV):
        if r["doc_id"] == doc_id:
            if r["source_sha256"] != sha256_of(path):
                sys.exit(
                    f"{rel(OCR_DIR / (doc_id + '.csv'))} was made from a different version of the PDF; re-run OCR"
                )
            return
    sys.exit(f"no OCR output for document {doc_id}; run: uv run scripts/ocr_documents.py --doc-id {doc_id}")


def page_kind(page: Page) -> str:
    """'summary', 'line_items' or 'other', judged from the column headers."""
    if summary_layout(page):
        return "summary"
    if any(find_line_item_header(line) for line in page.lines):
        return "line_items"
    return "other"


# --------------------------------------------------------------------------
# Summary pages
# --------------------------------------------------------------------------


@dataclass
class Heading:
    label: str
    items: list[dict] = field(default_factory=list)
    child_x: float | None = None  # indentation of the rows under this heading


HEADER_WORDS = {"budget", "estimated", "actual", "change", "from", "explanatory", "notes", "%"}
# OCR words below this confidence are noise (e.g. a sideways column header
# read as "zuze wuaget"); real words, even misspelt, score higher.
MIN_LABEL_CONFIDENCE = 40


@dataclass
class SummaryLayout:
    right_edges: list[float]  # where the amounts in each column end (they are right-aligned)
    columns: list[str]  # which amount each column holds
    label_end: float  # row labels lie left of this
    change_x: float  # left edge of "% Change"; the % and notes columns lie beyond it
    first_row: int  # index of the first line after the column header block

    def column_of(self, w: Word) -> str | None:
        """The amount column a word falls in, judged by its right edge."""
        distances = [abs(w.x1 - edge) for edge in self.right_edges]
        i = distances.index(min(distances))
        return self.columns[i] if distances[i] <= COLUMN_TOLERANCE else None

    def is_zero(self, words: list[Word], col: str, text_layer: bool) -> bool:
        """Whether a column cell shows a zero, printed in accounting format as
        "$" at the left of the cell and "-" at the right. On a scan, a dash
        alone may be a stray mark, so the "$" must be there too."""
        i = self.columns.index(col)
        left = self.right_edges[i - 1] + 2 if i else self.label_end
        right = self.right_edges[i] + COLUMN_TOLERANCE
        cell = [w.text.strip() for w in words if w.x0 >= left - 5 and w.x1 <= right]
        dash = any(t and t[-1] in "-—–" and not any(c.isdigit() for c in t) for t in cell)
        dollar = any(t.rstrip("-—–") and set(t.rstrip("-—–")) <= set("$S§") for t in cell)  # "$", "S$", "§"
        return dash and (dollar or text_layer)


COLUMN_TOLERANCE = 20  # points


def summary_layout(page: Page) -> SummaryLayout | None:
    """Work out a summary page's columns.

    The header ("2021  2021  2022  % Change  Explanatory Notes") marks where
    the rows begin and where the % change column starts. The amount columns
    themselves are found from the data, because OCR of the small header text
    is unreliable: amounts are right-aligned, so their right edges cluster
    tightly, one cluster per column. 2017-2025 have three columns (prior-year
    budget, prior-year estimated actual, budget); 2026 has two.
    """
    for i, line in enumerate(page.lines):
        change = [w for w in line.words if fuzzy_is(w.text, "change", 0.85)]
        if not change or not any(is_column_year(w.text) for w in line.words):
            continue
        change_x = change[0].x0
        # Skip the rest of the header block: lines made only of header words.
        j = i + 1
        while j < len(page.lines) and all(
            is_column_year(w.text) or clean(w.text).lower() in HEADER_WORDS or not clean(w.text)
            for w in page.lines[j].words
        ):
            j += 1
        # Amounts with a thousands separator are unambiguous; cluster their right edges.
        amounts = sorted(
            (
                w
                for ln in page.lines[j:]
                for w in ln.words
                if w.x1 < change_x and re.search(r"\d,\d{3}", w.text)
            ),
            key=lambda w: w.x1,
        )
        clusters: list[list[Word]] = []
        for w in amounts:
            if clusters and w.x1 - clusters[-1][-1].x1 < COLUMN_TOLERANCE:
                clusters[-1].append(w)
            else:
                clusters.append([w])
        clusters = [c for c in clusters if len(c) >= 3]
        if len(clusters) not in (2, 3):
            raise ValueError(
                f"doc {page.doc_id} p{page.number}: found {len(clusters)} amount columns, expected 2 or 3"
            )
        columns = AMOUNT_COLUMNS if len(clusters) == 3 else ["prior_year_budget", "budget"]
        return SummaryLayout(
            right_edges=[statistics.median(w.x1 for w in c) for c in clusters],
            columns=columns,
            label_end=min(w.x0 for w in clusters[0]) - 5,
            change_x=change_x,
            first_row=j,
        )
    return None


def parse_summary(doc_id: str, fiscal_year: str, pages: list[Page]) -> tuple[list[dict], list[dict]]:
    """Returns the summary rows and, for each printed subtotal or total, the
    rows it should equal the sum of: {"row": total_row, "check": ..., "items": [...]}."""
    rows: list[dict] = []
    sums: list[dict] = []
    section = group = ""
    stack: list[Heading] = []  # open sub-headings, outermost first
    group_items: list[dict] = []
    section_items: list[dict] = []
    # A label-only line: either a heading or a label wrapped above its amounts.
    # Kept across pages, since a heading can fall at the foot of a page.
    pending: dict | None = None
    last_bottom = 0.0  # bottom edge of the last row's line
    since_total: list[dict] = []  # item rows since the last subtotal or total

    layouts = {page.number: summary_layout(page) for page in pages}
    if len({len(lay.columns) for lay in layouts.values() if lay}) > 1:
        raise ValueError(f"doc {doc_id}: summary pages disagree on the number of amount columns")

    for page in pages:
        layout = layouts[page.number]
        if not layout:
            continue
        label_end = layout.label_end
        # Printed row numbers sit left of the labels; find where labels start.
        label_start = min(
            w.x0
            for ln in page.lines
            for w in ln.words
            if w.x0 < label_end and len(clean(w.text)) >= 4 and clean(w.text).replace("-", "").isalpha()
        )

        for line in page.lines[layout.first_row :]:
            # Ignore printed row numbers (left) and the % change and notes columns (right).
            words = [w for w in line.words if w.x1 > label_start + 1 and w.x0 < layout.change_x - 2]
            # Repeated column headers ("Police Services  2024 Budget  2024 Estimated...")
            # carry a heading on the left but no amounts.
            in_columns = [w for w in words if w.x0 >= label_end]
            is_header = any(clean(w.text).lower() in HEADER_WORDS for w in in_columns)
            amounts: dict[str, int | None] = {}
            corrected = []
            if not is_header:
                for col in layout.columns:
                    amounts[col], fixed = pick_amount([w for w in in_columns if layout.column_of(w) == col])
                    if amounts[col] is None and layout.is_zero(in_columns, col, page.extraction == "text"):
                        amounts[col] = 0
                    if fixed:
                        corrected.append(col)
            has_amounts = any(v is not None for v in amounts.values())

            # Section and group headings are bold, which lowers OCR confidence,
            # so recognise them before filtering out low-confidence words.
            heading_text = " ".join(
                clean(w.text)
                for w in words
                if w.x0 < label_end and has_letters(w.text) and clean(w.text).lower() not in HEADER_WORDS
            ).upper()
            label_words = [
                w
                for w in words
                if w.x0 < label_end
                and (has_letters(w.text) or clean(w.text) == "&")
                # One- or two-letter OCR fragments ("Oo", "TO") are noise unless confident.
                and (len(clean(w.text)) > 2 or w.conf >= 70 or clean(w.text) == "&")
                and clean(w.text).lower() not in HEADER_WORDS
                # Lines without amounts may be OCR noise; keep only confident words.
                # (Not applied to rows with amounts: bold labels get low confidence.)
                and (has_amounts or w.conf >= MIN_LABEL_CONFIDENCE)
            ]
            # A mangled row number ("lhe" for 11, "4l") can precede the label.
            while len(label_words) > 1 and is_mangled_number(label_words[0].text):
                label_words = label_words[1:]
            label = " ".join(p for p in (clean(w.text).rstrip(",") for w in label_words) if p)
            label_x = label_words[0].x0 if label_words else None

            if not has_amounts:
                if re.match(
                    r"^(REVENUES?|EXPENDITURES?)\b.*\bALL\b", heading_text
                ):  # "... - ALL OPERATING FUNDS"
                    section = "revenue" if heading_text.startswith("REVENUE") else "expenditure"
                    group, stack, section_items, pending = "", [], [], None
                elif match_group(heading_text):
                    group, stack, group_items, pending = match_group(heading_text), [], [], None
                elif not label or heading_text == "FUNDS":  # "FUNDS" ends the wrapped section heading
                    pass
                elif (
                    rows
                    and rows[-1]["item"] == ""
                    and rows[-1]["page"] == page.number
                    and line.top - last_bottom < 6
                ):
                    # The label of the row just above, printed a little below its amounts.
                    rows[-1]["item"] = label
                else:
                    if pending:  # two label-only lines in a row: the first was a heading
                        stack.append(Heading(pending["label"]))
                    pending = {"label": label, "x": label_x}
                continue

            if pending and (not label or (pending["label"].isupper() and label.isupper())):
                # A label wrapped above its amounts, e.g. "Vehicle Operation &
                # Maintenance" or "TOTAL REVENUES LESS TOTAL / EXPENDITURES".
                label, label_x = f"{pending['label']} {label}".strip(), pending["x"]
            elif pending:  # the pending line was a sub-heading
                stack.append(Heading(pending["label"]))
            pending = None
            if not label and sum(v is not None for v in amounts.values()) < 2:
                continue  # a page number, not a row
            # (A row with amounts but no label is kept: OCR lost its label, and a
            # correction supplies it. Dropping it would throw off the totals.)
            # A row indented less than a heading's other rows has left that heading.
            # (Nested rows are indented ~16 points; OCR positions wobble by a few.)
            while (
                stack
                and stack[-1].child_x is not None
                and label_x is not None
                and label_x < stack[-1].child_x - 8
            ):
                stack.pop()

            upper = label.upper()
            row_type = (
                "subtotal" if upper.startswith("SUBTOT") else "total" if upper.startswith("TOTAL") else "item"
            )
            if "LESS" in upper:  # "TOTAL REVENUES LESS TOTAL EXPENDITURES": a difference, not a sum
                row_type = "net"
            row = {
                "doc_id": doc_id,
                "fiscal_year": fiscal_year,
                "page": page.number,
                "extraction": page.extraction,
                "section": section,
                "group": group,
                "subgroup": stack[-1].label if stack else "",
                "item": label,
                "row_type": row_type,
                "prior_year_budget": amounts.get("prior_year_budget"),
                "prior_year_estimated_actual": amounts.get("prior_year_estimated_actual"),
                "budget": amounts.get("budget"),
                "corrected": ";".join(
                    (["item"] if any(w.corrected for w in label_words) else []) + corrected
                ),
            }
            rows.append(row)
            last_bottom = line.bottom

            if row_type == "item":
                if stack and stack[-1].child_x is None:
                    stack[-1].child_x = label_x
                for heading in stack:
                    heading.items.append(row)
                group_items.append(row)
                section_items.append(row)
                since_total.append(row)
            elif row_type == "subtotal" and stack:
                heading = stack.pop()
                row["subgroup"] = heading.label
                sums.append({"row": row, "check": f"subtotal: {heading.label}", "items": list(heading.items)})
            elif row_type == "subtotal":
                # The heading was lost (e.g. to OCR); check against the rows since the last total.
                sums.append({"row": row, "check": f"subtotal: {label}", "items": list(since_total)})
            elif row_type == "total" and group and match_group(re.sub(r"^\W*TOTAL\W*", "", upper)) == group:
                sums.append({"row": row, "check": f"group total: {group}", "items": list(group_items)})
                group, stack, group_items = "", [], []
            elif row_type == "total":
                sums.append({"row": row, "check": f"section total: {section}", "items": list(section_items)})
                stack = []
            if row_type != "item":
                since_total = []
    return rows, sums


def is_mangled_number(text: str) -> bool:
    t = clean(text)
    return len(t) <= 3 and (any(c.isdigit() for c in t) or not t[:1].isupper())


# Groups as printed, including the abbreviation "GENERAL GOV'T".
GROUP_SPELLINGS = {g: g for g in GROUPS} | {"GENERAL GOVT": "GENERAL GOVERNMENT"}


def match_group(text: str) -> str:
    """The expenditure group a heading names, allowing for OCR misspellings."""
    t = re.sub(r"[^A-Z ]", "", text.upper()).strip()
    for spelling, group in GROUP_SPELLINGS.items():
        if difflib.SequenceMatcher(None, t, spelling).ratio() >= 0.85:
            return group
    return ""


# --------------------------------------------------------------------------
# Line-item pages
# --------------------------------------------------------------------------


@dataclass
class TableColumns:
    """Left boundaries of the line-item table columns, from the header line
    'Fund | Account | Account # | 2022 Budget | 2023 Budget'."""

    account: float
    account_number: float
    prior_year_budget: float
    budget: float

    def column_of(self, w: Word) -> str:
        x = w.xc
        if x < self.account:
            return "fund"
        if x < self.account_number:
            return "account"
        if x < self.prior_year_budget:
            return "account_number"
        if x < self.budget:
            return "prior_year_budget"
        return "budget"


def find_line_item_header(line: Line) -> TableColumns | None:
    years = [w for w in line.words if is_column_year(w.text)]
    accounts = [w for w in line.words if fuzzy_is(w.text, "account") or fuzzy_is(w.text, "account#")]
    if len(years) != 2 or not accounts or not any(fuzzy_is(w.text, "budget") for w in line.words):
        return None
    if not any(fuzzy_is(w.text, "fund") for w in line.words):
        return None
    name, number = accounts[0], accounts[-1]
    if name is number:
        return None
    y1, y2 = years
    return TableColumns(
        account=name.x0 - 4,
        account_number=number.x0 - 8,
        prior_year_budget=(number.x0 + y1.x0) / 2 + 10,
        budget=(y1.x0 + y2.x0) / 2 + 10,
    )


def table_title(lines: list[str]) -> str:
    """Title of a table from the text above it, e.g. 'Professional Services-
    where there is an allocated expense...' -> 'Professional Services'.
    With a heading and a title ("Police Services" / "Personnel"), the title
    is the last line; a long description's wrapped second line is skipped."""
    titles = []
    for i, t in enumerate(lines):
        wrapped = i > 0 and len(lines[i - 1]) > 50
        if t and not wrapped and not t[0].islower() and not t.startswith(("(", "•", "e ")):
            titles.append(t)
    if not titles:
        return ""
    return re.split(r"(?<=\S)- ", titles[-1])[0].strip()


def parse_line_items(
    doc_id: str, fiscal_year: str, pages: list[Page]
) -> tuple[list[dict], list[dict], list[dict]]:
    rows: list[dict] = []
    totals: list[dict] = []  # printed table totals, kept for checking
    statements: list[dict] = []  # lines like "Total Budgeted Revenue 2023 $6,301,151"
    section = group = ""
    above: list[str] = []  # text lines since the last table
    cols: TableColumns | None = None
    table = ""
    current: dict | None = None
    table_rows: list[dict] = []

    for page in pages:
        if page_kind(page) != "line_items" and cols is None:
            continue
        for line in page.lines:
            header = find_line_item_header(line)
            if header:
                cols, current, table_rows = header, None, []
                table = table_title(above)
                above = []
                continue

            text = " ".join(c for c in (clean(w.text) for w in line.words) if c)
            if cols is None:  # between tables
                lower = text.lower()
                if "revenue by category" in lower:
                    section, group = "revenue", ""
                elif "expenditures by category" in lower:
                    section, group = "expenditure", ""
                elif match_group(text) and len(text) < 30:
                    group = match_group(text)
                elif "total" in lower or "expenses" in lower or "budget" in lower:
                    amounts = [parse_amount(w.text) for w in line.words if "$" in w.text]
                    years = [re.sub(r"\D", "", w.text) for w in line.words if is_year(w.text)]
                    if amounts and amounts[-1] is not None and years:
                        statements.append(
                            {"page": page.number, "text": text, "year": years[0], "amount": amounts[-1]}
                        )
                    else:
                        above.append(text)
                elif text:
                    above.append(text)
                continue

            cells: dict[str, list[Word]] = {}
            for w in line.words:
                if clean(w.text):
                    cells.setdefault(cols.column_of(w), []).append(w)
            number_words = [w for w in cells.get("account_number", []) if re.search(r"\d", w.text)]
            # An account number has five or more digits ("400.020"); a stray digit is noise.
            has_account_number = sum(c.isdigit() for w in number_words for c in w.text) >= 5
            prior, prior_fixed = pick_amount(cells.get("prior_year_budget", []))
            budget, budget_fixed = pick_amount(cells.get("budget", []))
            fixed = [name for name, f in (("prior_year_budget", prior_fixed), ("budget", budget_fixed)) if f]
            for name in ("fund", "account", "account_number"):
                if any(w.corrected for w in cells.get(name, [])):
                    fixed.append(name)
            fund = " ".join(
                clean(w.text) for w in cells.get("fund", []) if has_letters(w.text) or "(" in w.text
            )
            account = " ".join(clean(w.text) for w in cells.get("account", []) if has_letters(w.text))
            has_amounts = prior is not None or budget is not None

            # The Total line: "Total" plus amounts. If OCR garbles the word
            # "Total", it is still the only line with amounts but no fund,
            # account name or account number.
            leading = [clean(w.text) for w in line.words if clean(w.text)][:2]
            labelled_total = any(fuzzy_is(t, "total", 0.8) for t in leading) and not fund
            if labelled_total or (has_amounts and not (fund or account or has_account_number)):
                totals.append(
                    {
                        "doc_id": doc_id,
                        "page": page.number,
                        "table": table,
                        "section": section,
                        "group": group,
                        "prior_year_budget": prior,
                        "budget": budget,
                        "rows": table_rows,
                    }
                )
                cols, current, table_rows = None, None, []
                continue

            if has_account_number or has_amounts:
                current = {
                    "doc_id": doc_id,
                    "fiscal_year": fiscal_year,
                    "page": page.number,
                    "extraction": page.extraction,
                    "section": section,
                    "group": group,
                    "table": table,
                    "fund": fund,
                    "account": account,
                    "account_number": normalize_account_number(" ".join(clean(w.text) for w in number_words)),
                    "prior_year_budget": prior,
                    "budget": budget,
                    "corrected": ";".join(fixed),
                }
                rows.append(current)
                table_rows.append(current)
            elif current is not None and (fund or account):  # wrapped text, e.g. "Allocated" / "(GF)"
                current["fund"] = f"{current['fund']} {fund}".strip()
                current["account"] = f"{current['account']} {account}".strip()
    return rows, totals, statements


def normalize_account_number(text: str) -> str:
    t = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    return t


# --------------------------------------------------------------------------
# Corrections and checks
# --------------------------------------------------------------------------


def make_check(doc_id, page, check, column, printed, computed, note="", n_rows=1, printed_row="") -> dict:
    diff = (computed or 0) - (printed or 0)
    rounding = abs(diff) <= max(1, n_rows / 2)
    return {
        "doc_id": doc_id,
        "page": page,
        "check": check,
        "printed_row": printed_row,
        "column": column,
        "printed": printed,
        "computed": computed,
        "difference": diff,
        "status": "ok" if diff == 0 else "rounding" if rounding else "FAIL",
        "note": note,
    }


def summary_checks(sums: list[dict]) -> list[dict]:
    checks = []
    for s in sums:
        row = s["row"]
        for col in AMOUNT_COLUMNS:
            if row[col] is not None:
                computed = sum(r[col] or 0 for r in s["items"])
                checks.append(
                    make_check(
                        row["doc_id"],
                        row["page"],
                        s["check"],
                        col,
                        row[col],
                        computed,
                        n_rows=len(s["items"]),
                        printed_row=row["item"],
                    )
                )
    return checks


def line_item_checks(doc_id, fiscal_year, rows, totals, statements) -> list[dict]:
    checks = []
    for t in totals:
        t["checks"] = []
        for col in ("prior_year_budget", "budget"):
            computed = sum(r[col] or 0 for r in t["rows"])
            check = make_check(
                doc_id, t["page"], f"table total: {t['table']}", col, t[col], computed, n_rows=len(t["rows"])
            )
            checks.append(check)
            t["checks"].append(check)
    for s in statements:
        text = s["text"].lower()
        col = "budget" if s["year"] == fiscal_year else "prior_year_budget"
        if "revenue" in text:
            subset = [r for r in rows if r["section"] == "revenue"]
            label = "total revenue"
        elif "expenditure" in text:
            subset = [r for r in rows if r["section"] == "expenditure"]
            label = "total expenditures"
        elif match_group_in(text):
            subset = [r for r in rows if r["group"] == match_group_in(text)]
            label = f"group total: {match_group_in(text)}"
            if " gf " in f" {text} ":  # "General Government GF Expenses": General Fund share only
                subset = [r for r in subset if "SSW" not in r["fund"].upper()]
                label += " (General Fund)"
        else:
            continue
        computed = sum(r[col] or 0 for r in subset)
        checks.append(
            make_check(
                doc_id, s["page"], f"stated {label}", col, s["amount"], computed, s["text"], len(subset)
            )
        )
    for r in rows:
        # Some rows (e.g. "Benefits") have no account number in the source.
        if r["account_number"] and not ACCOUNT_NUMBER_RE.match(r["account_number"]):
            checks.append(
                {
                    "doc_id": doc_id,
                    "page": r["page"],
                    "check": f"account number format: {r['account']}",
                    "printed_row": "",
                    "column": "account_number",
                    "printed": r["account_number"],
                    "computed": "",
                    "difference": "",
                    "status": "FAIL",
                    "note": "",
                }
            )
    return checks


def match_group_in(text: str) -> str:
    for g in GROUPS:
        if g.lower() in text.lower():
            return g
    return ""


def explain_source_errors(checks: list[dict]) -> None:
    known = {
        (r["doc_id"], r["page"], r["check"], r["column"]): r["note"] for r in read_csv(SOURCE_ERRORS_CSV)
    }
    for c in checks:
        note = known.get((c["doc_id"], str(c["page"]), c["check"], c["column"]))
        if note is not None and c["status"] == "FAIL":
            c["status"] = "source error"
            c["note"] = note


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--strict", action="store_true", help="exit with an error if any check fails")
    args = parser.parse_args()

    budgets = [
        r for r in sources_by_id().values() if r["category"] == "budget_adopted" and r["include"] == "yes"
    ]
    summary: list[dict] = []
    line_items: list[dict] = []
    totals: list[dict] = []
    statements: dict[str, list[dict]] = {}
    sums: list[dict] = []

    for doc in budgets:
        doc_id, year = doc["doc_id"], doc["fiscal_year"]
        pages = load_pages(doc_id)
        rows, doc_sums = parse_summary(doc_id, year, [p for p in pages if page_kind(p) == "summary"])
        summary += rows
        sums += doc_sums
        items, doc_totals, doc_statements = parse_line_items(doc_id, year, pages)
        line_items += items
        totals += doc_totals
        statements[doc_id] = doc_statements
        print(f"{doc_id} {doc['title']}: {len(rows)} summary rows, {len(items)} line items")

    checks = summary_checks(sums)
    for doc in budgets:
        doc_id, year = doc["doc_id"], doc["fiscal_year"]
        checks += line_item_checks(
            doc_id,
            year,
            [r for r in line_items if r["doc_id"] == doc_id],
            [t for t in totals if t["doc_id"] == doc_id],
            statements[doc_id],
        )
    explain_source_errors(checks)

    # Mark each line item with the outcome of its table's printed-total check,
    # so a reader can tell reconciled rows from unreconciled ones.
    for r in line_items:
        r["table_check"] = "no total"
    for t in totals:
        statuses = {c["status"] for c in t["checks"]}
        status = next((s for s in ("FAIL", "source error", "rounding") if s in statuses), "ok")
        for r in t["rows"]:
            r["table_check"] = status

    write_csv(SUMMARY_CSV, SUMMARY_FIELDS, summary)
    write_csv(LINE_ITEMS_CSV, LINE_ITEM_FIELDS, line_items)
    write_csv(CHECKS_CSV, CHECK_FIELDS, checks)
    for path in (SUMMARY_CSV, LINE_ITEMS_CSV, CHECKS_CSV):
        print(f"Wrote {rel(path)}")

    failed = [c for c in checks if c["status"] == "FAIL"]
    explained = [c for c in checks if c["status"] == "source error"]
    print(
        f"\nChecks: {len(checks) - len(failed) - len(explained)} ok, {len(explained)} source errors, {len(failed)} FAILED"
    )
    for c in failed:
        print(f"  FAIL doc {c['doc_id']} p{c['page']} {c['check']} [{c['column']}]: "
              f"printed {c['printed']}, computed {c['computed']}")  # fmt: skip
    return 1 if failed and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
