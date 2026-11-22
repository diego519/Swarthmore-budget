#!/usr/bin/env python3
"""Parse proposed (advertised) budgets into a table of budget lines.

From 2027 the borough's budget is laid out by fund -- General, Sewer & Solid
Waste, Liquid Fuels, Capital -- each with its revenue and expense accounts and
four columns: the proposed budget, the current year's budget, the current
year to date, and the previous year's actual total, plus explanatory notes.
That is a different layout from the adopted budgets of 2016-2026 (see
parse_budgets.py), so it has its own parser.

The proposed budgets have a PDF text layer, so the figures are read exactly.
Each fund's revenue and expense lines are checked against the subtotal
printed under them.

Outputs (in data/processed/):
    proposed_budget_lines.csv    one row per account line
    proposed_budget_checks.csv   each printed subtotal vs. the sum of its lines

Usage:
    uv run scripts/parse_proposed_budget.py
"""

from __future__ import annotations

import re
import sys

import pdfplumber
from common import (
    CORRECTIONS_DIR,
    PROCESSED_DIR,
    downloaded_path,
    read_csv,
    rel,
    sources_by_id,
    text_layer_lines,
    write_csv,
)

LINES_CSV = PROCESSED_DIR / "proposed_budget_lines.csv"
CHECKS_CSV = PROCESSED_DIR / "proposed_budget_checks.csv"
SOURCE_ERRORS_CSV = CORRECTIONS_DIR / "proposed_budget_source_errors.csv"

# The four amount columns, left to right.
COLUMNS = ["budget", "prior_year_budget", "prior_year_to_date", "two_years_prior_actual"]
LINE_FIELDS = ["doc_id", "fiscal_year", "page", "fund", "section", "account", *COLUMNS, "note"]
CHECK_FIELDS = ["doc_id", "fund", "section", "column", "printed", "computed", "difference", "status", "note"]
FUNDS = ["GENERAL FUND", "SEWER & SOLID WASTE FUND", "LIQUID FUELS FUND", "CAPITAL FUND"]
AMOUNT = re.compile(r"^\$?\(?-?\$?[\d,]+\)?\$?$")


def amount(text: str) -> int | None:
    """A dollar amount from the text layer: "2,590,492", "$5,400", "5,400$",
    "-2,991" (text layers have real minus signs), "(1,031)"."""
    t = text.strip()
    if not AMOUNT.match(t) or not re.search(r"\d", t):
        return None
    negative = t.replace("$", "").startswith(("-", "("))
    value = int(re.sub(r"\D", "", t))
    return -value if negative else value


def column_bounds(line) -> list[float] | None:
    """Left edges of the amount and notes columns, from the header line
    'Account  2027 BUD  2026 BUD  2026 YTD  2025 TOT  EXPLANATORY NOTES'."""
    words = line.words
    if not words or words[0].text != "Account":
        return None
    years = [w.x0 for w in words if re.fullmatch(r"20\d\d", w.text)]
    notes = [w.x0 for w in words if w.text.upper().startswith("EXPLANATORY")]
    if len(years) != 4 or not notes:
        raise ValueError(f"unexpected column header: {line.text}")
    # Amounts in the first column are right-aligned and may start left of
    # its header; the label column ends well before.
    return [years[0] - 60, years[1], years[2], years[3], notes[0]]


def parse(doc_id: str, fiscal_year: str) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    subtotals: list[dict] = []
    fund = section = ""
    bounds: list[float] | None = None
    with pdfplumber.open(downloaded_path(doc_id)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for line in text_layer_lines(page):
                header = column_bounds(line)
                if header:
                    bounds = header
                    continue
                text = line.text.strip()
                upper = text.upper()
                if upper in FUNDS:
                    fund, section = upper.title().replace("&", "&"), ""
                    continue
                if upper in ("REVENUES", "EXPENSES"):
                    section = "revenue" if upper == "REVENUES" else "expense"
                    continue
                if not fund or not bounds:
                    continue  # title and notes before the first fund

                # The account name is everything left of the amounts, plus any
                # word with letters that runs on into the first amount column.
                label_words = []
                values = {c: None for c in COLUMNS}
                notes_x = bounds[4] - 10  # notes can start a little left of their heading
                for w in line.words:
                    if w.x0 < bounds[0]:
                        label_words.append(w.text)
                    elif w.x0 < notes_x:
                        v = amount(w.text)
                        if v is not None:
                            values[COLUMNS[max(i for i in range(4) if w.x0 >= bounds[i] - 1)]] = v
                        elif re.search(r"[A-Za-z]", w.text) and w.x0 < bounds[1]:
                            label_words.append(w.text)
                label = " ".join(label_words)
                note = " ".join(w.text for w in line.words if w.x0 >= notes_x)

                if label.lower().startswith("subtotal"):
                    subtotals.append({"fund": fund, "section": section, **values})
                    continue
                if not label and not any(v is not None for v in values.values()):
                    if note and rows:  # a wrapped explanatory note
                        rows[-1]["note"] = f"{rows[-1]['note']} {note}".strip()
                    continue
                if not section:
                    raise ValueError(f"doc {doc_id} p{page_number}: line before REVENUES/EXPENSES: {text}")
                rows.append(
                    {
                        "doc_id": doc_id,
                        "fiscal_year": fiscal_year,
                        "page": page_number,
                        "fund": fund,
                        "section": section,
                        "account": label,
                        **values,
                        "note": note,
                    }
                )
    return rows, subtotals


def checks(doc_id: str, rows: list[dict], subtotals: list[dict]) -> list[dict]:
    """Each printed subtotal vs. the sum of its lines. Differences that are the
    source document's own (data/corrections/proposed_budget_source_errors.csv)
    are marked "source error" with the explanation."""
    known = {
        (r["doc_id"], r["fund"], r["section"], r["column"]): r["note"] for r in read_csv(SOURCE_ERRORS_CSV)
    }
    out = []
    for s in subtotals:
        lines = [r for r in rows if r["fund"] == s["fund"] and r["section"] == s["section"]]
        for col in COLUMNS:
            printed = s[col] or 0
            computed = sum(r[col] or 0 for r in lines)
            diff = computed - printed
            out.append(
                {
                    "doc_id": doc_id,
                    "fund": s["fund"],
                    "section": s["section"],
                    "column": col,
                    "printed": printed,
                    "computed": computed,
                    "difference": diff,
                    "status": "ok"
                    if diff == 0
                    else "rounding"
                    if abs(diff) <= max(1, len(lines) / 2)
                    else "FAIL",
                    "note": "",
                }
            )
            note = known.get((doc_id, s["fund"], s["section"], col))
            if note and out[-1]["status"] == "FAIL":
                out[-1].update(status="source error", note=note)
    return out


def main() -> int:
    proposed = [
        r for r in sources_by_id().values() if r["category"] == "budget_proposed" and r["include"] == "yes"
    ]
    all_rows, all_checks = [], []
    for doc in proposed:
        rows, subtotals = parse(doc["doc_id"], doc["fiscal_year"])
        all_rows += rows
        all_checks += checks(doc["doc_id"], rows, subtotals)
        expected = {(f.title(), s) for f in FUNDS for s in ("revenue", "expense")}
        found = {(s["fund"], s["section"]) for s in subtotals}
        if found != expected:
            print(f"doc {doc['doc_id']}: subtotals found for {sorted(found)}", file=sys.stderr)
            return 1
        print(f"{doc['doc_id']} {doc['title']}: {len(rows)} lines in {len({r['fund'] for r in rows})} funds")
    write_csv(LINES_CSV, LINE_FIELDS, all_rows)
    write_csv(CHECKS_CSV, CHECK_FIELDS, all_checks)
    failed = [c for c in all_checks if c["status"] == "FAIL"]
    explained = [c for c in all_checks if c["status"] == "source error"]
    print(f"Wrote {rel(LINES_CSV)} and {rel(CHECKS_CSV)}")
    print(
        f"Checks: {len(all_checks) - len(failed) - len(explained)} ok, {len(explained)} source errors, {len(failed)} FAILED"
    )
    for c in failed:
        print(
            f"  FAIL {c['fund']} {c['section']} [{c['column']}]: printed {c['printed']}, computed {c['computed']}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
