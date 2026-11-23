#!/usr/bin/env python3
"""Give budget lines their actual totals from the monthly reports, where they match.

The adopted budgets' summary lines (budget_series.csv) say what was planned;
the monthly reports say what was spent or collected, account by account.
data/mappings/budget_line_accounts.csv lists, by hand, the ledger accounts
that make up each budget line that can be traced to them: specific accounts
("01-456-000"), whole departments ("01-450-*"), a category of the monthly
summary ("category:community"), or a whole side ("all:expense").

A line is given an actual for a year only if it demonstrably covers the same
thing as its accounts that year: the accounts' budget in the year's first
monthly report must equal the line's adopted budget (to within rounding).
Where it doesn't (the line includes a share of employee benefits that the
accounts don't, say, or the borough split it differently that year), the
line gets no actual for that year. The actual is the accounts' total for the
year in the December report, as first reported; the same total as the next
December's report restates it is given too.

Lines given by category or side take their figures from monthly_summary.csv,
so they agree with the website's actuals page (including any amount not
matched to a line); the rest sum their accounts in monthly_series.csv.

Output:
    data/processed/budget_line_actuals.csv   one row per line and year with a
                                             December report: the two budgets,
                                             whether they match, and the actual

Usage:
    uv run scripts/build_line_actuals.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from decimal import Decimal

from common import DATA_DIR, PROCESSED_DIR, read_csv, rel, write_csv

MAPPING_CSV = DATA_DIR / "mappings" / "budget_line_accounts.csv"
CATEGORIES_CSV = DATA_DIR / "mappings" / "monthly_account_categories.csv"
ITEMS_CSV = DATA_DIR / "mappings" / "budget_items.csv"
BUDGET_SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
MONTHLY_SERIES_CSV = PROCESSED_DIR / "monthly_series.csv"
MONTHLY_SUMMARY_CSV = PROCESSED_DIR / "monthly_summary.csv"
OUT_CSV = PROCESSED_DIR / "budget_line_actuals.csv"

TOLERANCE = 500  # cents: the adopted budgets are rounded to the dollar, line by line
FIELDS = [
    "item_id", "year", "accounts", "ledger_budget", "adopted_budget", "difference", "match", "actual",
    "restated_actual", "unconfirmed", "doc_id", "page",
]  # fmt: skip


def cents(text: str) -> int | None:
    return int(Decimal(text) * 100) if text else None


def dollars(c: int | None) -> str:
    return "" if c is None else f"{Decimal(c) / 100:.2f}"


def resolve(spec: str, accounts: dict[str, dict], category: dict[str, str]) -> tuple[str, list[str]]:
    """("summary", [category keys]) for a category or side, else ("accounts", [ledger ids])."""
    kind, _, rest = spec.partition(":")
    if kind == "all":
        return "summary", [f"side:{rest}"]
    if kind == "category":
        return "summary", [rest]
    ids = []
    for part in spec.split():
        if part.endswith("*"):
            found = [a for a in accounts if a.startswith(part[:-1])]
            if not found:
                sys.exit(f"{rel(MAPPING_CSV)}: {part} matches no account")
            ids += found
        elif part in accounts:
            ids.append(part)
        else:
            sys.exit(f"{rel(MAPPING_CSV)}: unknown account {part}")
    return "accounts", sorted(set(ids))


def main() -> int:
    items = {r["item_id"] for r in read_csv(ITEMS_CSV)}
    mapping = read_csv(MAPPING_CSV)
    unknown = [m["item_id"] for m in mapping if m["item_id"] not in items]
    if unknown:
        print(f"{rel(MAPPING_CSV)}: unknown budget lines {unknown}", file=sys.stderr)
        return 1
    category = {m["ledger_id"]: m["category"] for m in read_csv(CATEGORIES_CSV)}
    adopted = {
        (r["item_id"], int(r["year"])): cents(r["amount"])
        for r in read_csv(BUDGET_SERIES_CSV)
        if r["measure"] == "adopted_budget"
    }

    # Account figures by (ledger id, year, month); category figures likewise.
    series = [r for r in read_csv(MONTHLY_SERIES_CSV) if r["row_type"] == "item"]
    accounts = {r["ledger_id"]: r["statement"] for r in series}
    by_account = {(r["ledger_id"], int(r["year"]), int(r["month"])): r for r in series}
    by_category: dict[tuple[str, int, int], dict[str, int | None]] = defaultdict(dict)
    for r in read_csv(MONTHLY_SUMMARY_CSV):
        key = (int(r["year"]), int(r["month"]))
        side = "side:expense" if r["side"] in ("spending", "excluded_expense") else "side:revenue"
        for name in (r["category"], side):
            cell = by_category[(name, *key)]
            for col in ("budget", "ytd", "restated_ytd"):
                if r[col] != "":
                    cell[col] = (cell.get(col) or 0) + cents(r[col])
            cell["unconfirmed"] = (cell.get("unconfirmed") or 0) + int(r["unconfirmed"] or 0)
            cell.setdefault("doc_id", r["reported_doc_id"])

    reported = defaultdict(set)  # year -> months with that month's own report
    for r in series:
        if r["reported_doc_id"]:
            reported[int(r["year"])].add(int(r["month"]))
    years = sorted(y for y, months in reported.items() if 12 in months)

    out = []
    for m in mapping:
        kind, parts = resolve(m["accounts"], accounts, category)
        for year in years:
            first = min(reported[year])
            if kind == "summary":
                start = [by_category.get((p, year, first), {}) for p in parts]
                end = [by_category.get((p, year, 12), {}) for p in parts]
                n = sum(1 for a, c in category.items() if any(c == p or (p.startswith("side:")
                        and accounts.get(a) == p[5:]) for p in parts))  # fmt: skip
                budget = sum(c.get("budget") or 0 for c in start) if any(start) else None
                actual = sum(c.get("ytd") or 0 for c in end) if any("ytd" in c for c in end) else None
                restated = (
                    sum(c["restated_ytd"] for c in end)
                    if end and all("restated_ytd" in c for c in end)
                    else None
                )
                unconfirmed = sum(c.get("unconfirmed") or 0 for c in end)
                doc_id, page = next((c["doc_id"] for c in end if c.get("doc_id")), ""), ""
            else:
                start = [by_account.get((a, year, first)) for a in parts]
                end = [by_account.get((a, year, 12)) for a in parts]
                n = len(parts)
                budget = sum(cents(r["budget"]) or 0 for r in start if r) if any(start) else None
                present = [r for r in end if r and r["reported_doc_id"]]
                actual = sum(cents(r["ytd"]) or 0 for r in present) if present else None
                restated = sum(cents(r["restated_ytd"]) or 0 for r in present) if present and all(
                    r["restated_ytd"] != "" for r in present) else None  # fmt: skip
                unconfirmed = sum(1 for r in present if r["ytd"] == "" or r["ytd_check"] in ("", "corrected"))
                doc_id = present[0]["reported_doc_id"] if present else ""
                page = min((int(r["reported_page"]) for r in present), default="")
            a = adopted.get((m["item_id"], year))
            match = budget is not None and a is not None and abs(budget - a) <= TOLERANCE
            out.append({
                "item_id": m["item_id"], "year": year, "accounts": n,
                "ledger_budget": dollars(budget), "adopted_budget": dollars(a),
                "difference": dollars(budget - a) if budget is not None and a is not None else "",
                "match": "yes" if match else "no", "actual": dollars(actual), "restated_actual": dollars(restated),
                "unconfirmed": unconfirmed, "doc_id": doc_id, "page": page,
            })  # fmt: skip

    write_csv(OUT_CSV, FIELDS, out)
    matched = [r for r in out if r["match"] == "yes"]
    lines = {r["item_id"] for r in matched}
    print(
        f"Wrote {rel(OUT_CSV)}: {len(matched)} of {len(out)} line-years match, on {len(lines)} of {len(mapping)} lines"
    )
    for item in [m["item_id"] for m in mapping]:
        rows = [r for r in out if r["item_id"] == item]
        marks = " ".join(f"{r['year']}{'+' if r['match'] == 'yes' else '-'}" for r in rows)
        print(f"  {item:32} {marks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
