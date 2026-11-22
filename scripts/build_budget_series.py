#!/usr/bin/env python3
"""Turn the adopted-budget summaries into one time series per budget line.

Each year's budget is a separate document, and the same line can be labelled
differently from year to year (renamed, or misspelt by OCR), while some labels
("Debt Service", "Insurance") appear in several places. The hand-curated
mapping in data/mappings/budget_items.csv says which rows are the same line:

  * a row is identified by its section, its own label, and -- for ordinary
    rows -- the subtotal or total that closes it in the document (so "Debt
    Service" under "Subtotal - Fire Protection" is fire debt service);
  * `raw_labels` lists every spelling of the label seen in the documents,
    letters only, lower case ("Snow & Ice Removal" -> "snowiceremoval").

Every summary row must match exactly one mapping entry; anything else stops
the script, so new or changed labels are always reviewed by a person.

For each line and year the output has three measures:

  adopted_budget     the year's adopted budget, from that year's document
                     (2016's comes from the 2017 budget's prior-year column)
  estimated_actual   the year's estimated actual, from the NEXT year's
                     budget (so 2016-2024 only)
  restated_budget    the year's budget as the NEXT year's budget reports it

Comparing adopted_budget with restated_budget is a check on the mapping: if
two documents' rows were wrongly linked, the figures disagree. They can also
disagree for real (the borough revised a budget, e.g. reallocating shared
costs); every disagreement is listed in data/processed/budget_series_checks.csv.

Values printed in a total that is known to be wrong in the borough's own
document (see data/corrections/budget_source_errors.csv) carry an explanation
in the `source_error` column.

Outputs:
    data/processed/budget_series.csv          one row per line, year and measure
    data/processed/budget_series_checks.csv   adopted vs. restated comparisons

Usage:
    uv run scripts/build_budget_series.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict

from common import DATA_DIR, PROCESSED_DIR, read_csv, rel, write_csv

ITEMS_CSV = DATA_DIR / "mappings" / "budget_items.csv"
SUMMARY_CSV = PROCESSED_DIR / "budget_summary.csv"
SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
SERIES_CHECKS_CSV = PROCESSED_DIR / "budget_series_checks.csv"
BUDGET_CHECKS_CSV = PROCESSED_DIR / "budget_checks.csv"
# Which measure, and which year relative to the document's, each column feeds.
COLUMN_MEASURES = {
    "budget": ("adopted_budget", 0),
    "prior_year_budget": ("restated_budget", -1),
    "prior_year_estimated_actual": ("estimated_actual", -1),
}

SERIES_FIELDS = [
    "item_id",
    "year",
    "measure",
    "amount",
    "doc_id",
    "page",
    "extraction",
    "corrected",
    "source_error",
]
CHECK_FIELDS = [
    "item_id",
    "year",
    "adopted_budget",
    "restated_budget",
    "difference",
    "adopted_doc",
    "restated_doc",
]


def label_key(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def row_keys(rows: list[dict]) -> list[tuple[str, str, str, str]]:
    """(section, closing, label, row_type) for each row of one document, where
    `closing` is the label of the next subtotal/total row in the same section
    (for ordinary rows) or empty (for subtotal, total and net rows)."""
    keys = []
    for i, r in enumerate(rows):
        closing = ""
        if r["row_type"] == "item":
            closing = next(
                (
                    label_key(x["item"])
                    for x in rows[i + 1 :]
                    if x["section"] == r["section"] and x["row_type"] in ("subtotal", "total")
                ),
                "",
            )
        keys.append((r["section"], closing, label_key(r["item"]), r["row_type"]))
    return keys


def match_item(key: tuple[str, str, str, str], items: list[dict]) -> list[dict]:
    section, closing, label, row_type = key
    return [
        it
        for it in items
        if it["section"] == section
        and it["row_type"] == row_type
        and label in it["raw_labels"].split(";")
        and (closing in it["closing"].split(";") if it["closing"] else True)
    ]


def amount(value: str) -> int | None:
    return int(value) if value not in ("", None) else None


def main() -> int:
    items = read_csv(ITEMS_CSV)
    summary = read_csv(SUMMARY_CSV)

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in summary:
        by_doc[r["doc_id"]].append(r)

    # series[item_id][year][measure] = (amount, source row)
    series: dict[str, dict[int, dict[str, tuple[int, dict]]]] = defaultdict(lambda: defaultdict(dict))
    problems = []

    def put(item_id: str, year: int, measure: str, value: int | None, row: dict, column: str) -> None:
        if value is None:
            return
        if measure in series[item_id][year]:
            problems.append(f"{item_id} {year} {measure}: two values (doc {row['doc_id']} p{row['page']})")
            return
        series[item_id][year][measure] = (value, row, column)

    # Printed totals known to be wrong in the source document
    # (data/corrections/budget_source_errors.csv, via the parse checks).
    source_errors = {
        (c["doc_id"], c["page"], c["printed_row"], c["column"]): c["note"]
        for c in read_csv(BUDGET_CHECKS_CSV)
        if c["status"] == "source error"
    }
    notes: dict[tuple[str, int, str], str] = {}

    for doc_id, rows in by_doc.items():
        for row, key in zip(rows, row_keys(rows), strict=True):
            matches = match_item(key, items)
            if len(matches) != 1:
                problems.append(
                    f"doc {doc_id} p{row['page']} {row['item']!r} {key}: "
                    f"matched {len(matches)} entries in {rel(ITEMS_CSV)} (expected 1)"
                )
                continue
            item_id = matches[0]["item_id"]
            year = int(row["fiscal_year"])
            for column, (measure, offset) in COLUMN_MEASURES.items():
                note = source_errors.get((doc_id, row["page"], row["item"], column))
                if note:
                    notes[(item_id, year + offset, measure)] = note
            put(item_id, year, "adopted_budget", amount(row["budget"]), row, "budget")
            put(
                item_id,
                year - 1,
                "restated_budget",
                amount(row["prior_year_budget"]),
                row,
                "prior_year_budget",
            )
            put(
                item_id,
                year - 1,
                "estimated_actual",
                amount(row["prior_year_estimated_actual"]),
                row,
                "prior_year_estimated_actual",
            )

    if problems:
        print("Cannot build the series; fix these first:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1

    first_year = min(int(r["fiscal_year"]) for r in summary) - 1
    out, checks = [], []
    order = {it["item_id"]: i for i, it in enumerate(items)}
    for item_id in sorted(series, key=order.__getitem__):
        for year in sorted(series[item_id]):
            m = series[item_id][year]
            # The earliest year has no budget document of its own: use the
            # next year's prior-year column as its adopted budget.
            if year == first_year and "restated_budget" in m and "adopted_budget" not in m:
                m["adopted_budget"] = m["restated_budget"]
                if (item_id, year, "restated_budget") in notes:
                    notes[(item_id, year, "adopted_budget")] = notes[(item_id, year, "restated_budget")]
            for measure in ("adopted_budget", "estimated_actual", "restated_budget"):
                if measure not in m:
                    continue
                value, row, column = m[measure]
                out.append(
                    {
                        "item_id": item_id,
                        "year": year,
                        "measure": measure,
                        "amount": value,
                        "doc_id": row["doc_id"],
                        "page": row["page"],
                        "extraction": row["extraction"],
                        "corrected": "yes" if column in row["corrected"].split(";") else "",
                        "source_error": notes.get((item_id, year, measure), ""),
                    }
                )
            if year > first_year and "adopted_budget" in m and "restated_budget" in m:
                adopted, restated = m["adopted_budget"][0], m["restated_budget"][0]
                checks.append(
                    {
                        "item_id": item_id,
                        "year": year,
                        "adopted_budget": adopted,
                        "restated_budget": restated,
                        "difference": restated - adopted,
                        "adopted_doc": m["adopted_budget"][1]["doc_id"],
                        "restated_doc": m["restated_budget"][1]["doc_id"],
                    }
                )

    write_csv(SERIES_CSV, SERIES_FIELDS, out)
    write_csv(SERIES_CHECKS_CSV, CHECK_FIELDS, checks)
    differ = [c for c in checks if c["difference"] != 0]
    print(f"Wrote {rel(SERIES_CSV)}: {len(series)} budget lines, {len(out)} values")
    print(
        f"Wrote {rel(SERIES_CHECKS_CSV)}: {len(checks)} adopted vs. restated comparisons, "
        f"{len(checks) - len(differ)} identical, {len(differ)} different"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
