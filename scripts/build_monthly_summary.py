#!/usr/bin/env python3
"""Total the monthly reports' accounts into the overview's categories.

Every ledger account in the monthly reports is assigned by hand to one of the
website overview's categories (police, streets, property taxes, ...) in
data/mappings/monthly_account_categories.csv, with a note wherever the choice
needed judgment. This script totals each month's budget and year-to-date
actual spending and revenue by category, so actuals can be set beside
budgets on the categories the overview already uses.

The ledger is not laid out quite like the budget summaries the overview is
built from, so a few amounts are shared out, and the categories that receive
a share are marked as estimates:

  payroll_benefits  Employee benefits (health insurance, social security,
                    workers' compensation, retirement contributions) are
                    budgeted and paid centrally, but the budget summaries
                    include them in each department's personnel costs. They
                    are shared out in proportion to each category's salaries
                    (accounts marked payroll=yes), as for the 2027 proposal.
  ssw_overhead      The Sewer & Solid Waste Fund's share of administration,
                    tax collection, public works staff leave and insurance.
                    The budget summaries show it as "allocated expenses"
                    under sewer and under solid waste; it is split between
                    the two in the proportion those lines have in that year's
                    adopted budget.

Accounts for transfers between the borough's own funds ("interfund") and
proceeds of borrowing ("financing") are left out. (Almost no transfers were
made in 2020-2026: $196,000 was booked as a General Fund transfer in May
2026 and reversed by June, so May's totals are that much less than the
report's cover.)

Where OCR misread more than one line of a department, so that its lines do
not add up to the department's printed subtotal and no single misreading
could be corrected, the subtotal (if it is confirmed exactly: it adds up
with the fund's other departments, or another report prints the same
figure) is taken as the
department's total: the difference is counted in the category of the
department's unconfirmed lines, and reported in the "unmatched" columns.

Every account in data/processed/monthly_series.csv must be mapped exactly
once; the script stops otherwise. As a check on the mapping, each year's
budget, totalled by category from the year's first report, is compared with
that year's adopted budget summary.

Outputs (in data/processed/):
    monthly_summary.csv          by year, month and category: the budget and
                                 year-to-date total as reported that month,
                                 and the year-to-date total as restated a year
                                 later
    monthly_summary_checks.csv   each year's budget by category, from the
                                 ledger and from the adopted budget summary

Usage:
    uv run scripts/build_monthly_summary.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from decimal import Decimal

from build_site import OVERVIEW
from common import DATA_DIR, PROCESSED_DIR, read_csv, rel, write_csv

SERIES_CSV = PROCESSED_DIR / "monthly_series.csv"
BUDGET_SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
MAPPING_CSV = DATA_DIR / "mappings" / "monthly_account_categories.csv"
SUMMARY_CSV = PROCESSED_DIR / "monthly_summary.csv"
CHECKS_CSV = PROCESSED_DIR / "monthly_summary_checks.csv"

SPENDING = [c["key"] for c in OVERVIEW["spending"]["broad"]]
REVENUE = [c["key"] for c in OVERVIEW["revenue"]["broad"]]
POOLED = {"payroll_benefits", "ssw_overhead"}
EXCLUDED = {"interfund", "financing"}
MEASURES = {"budget": "budget", "ytd": "ytd", "restated_ytd": "restated_ytd"}

SUMMARY_FIELDS = [
    "year", "month", "side", "category", "budget", "ytd", "restated_ytd", "estimated", "accounts",
    "unconfirmed", "restated_unconfirmed", "unmatched", "restated_unmatched", "reported_doc_id",
    "restated_doc_id",
]  # fmt: skip
CHECK_FIELDS = [
    "year", "side", "category", "ledger_budget", "adopted_budget", "difference", "estimated", "doc_id", "note",
]  # fmt: skip
# Why a year's ledger budget differs from its adopted budget summary, other
# than by the sharing out of benefits and overhead (checked by hand).
CAPITAL_2023 = (
    "The adopted budget includes a $100,000 contribution to capital; the ledger budgets that account "
    "(01-492-300) at $0 all year, although $100,000 was paid in October."
)
CHECK_NOTES = {
    ("revenue", "prior_year_funds"): "Fund balances carried over from earlier years are budgeted in the "
    "summaries but are not a ledger account.",
    ("revenue", "total"): "The summaries' total includes prior-year funds, which are not a ledger account.",
    (2023, "spending", "gg"): CAPITAL_2023,
    (2023, "spending", "total"): CAPITAL_2023,
    ("spending", "fire"): "The summaries include a fire insurance line; the ledger budgets the borough's "
    "insurance centrally, and it is counted under general government here.",
    (2023, "revenue", "property_taxes"): "Interim real estate taxes: $1,500 in the adopted budget, $750 in "
    "the ledger.",
    (
        2026,
        "*",
        "*",
    ): "The 2026 adopted budget is laid out differently: its summary leaves out the Highway Aid "
    "(liquid fuels) Fund, and the ledger budgets several lines differently (the emergency services tax, for "
    "example, was first budgeted under the ALS revenue account).",
}


def cents(text: str) -> int | None:
    return int(Decimal(text) * 100) if text else None


def dollars(c: float | None) -> str:
    return "" if c is None else f"{Decimal(round(c)) / 100:.2f}"


def ssw_sewer_share(adopted: dict) -> dict[int, float]:
    """For each year, the sewer's share of the Sewer & Solid Waste Fund's
    allocated expenses in the adopted budget summary."""
    out = {}
    for year in {y for (_, y) in adopted}:
        sewer = adopted.get(("exp.pw.sewer.allocated", year))
        waste = adopted.get(("exp.pw.solid_waste.allocated", year))
        if sewer is not None and waste is not None and sewer + waste:
            out[year] = sewer / (sewer + waste)
    return out


def categorize(values: dict[str, int], mapping: dict[str, dict], sewer_share: float) -> tuple[dict, set]:
    """Category totals (cents, possibly fractional) of one set of account
    values, and the categories that received a shared-out amount."""
    totals: dict[str, float] = defaultdict(float)
    payroll: dict[str, float] = defaultdict(float)
    for lid, v in values.items():
        m = mapping[lid]
        totals[m["category"]] += v
        if m["payroll"] == "yes":
            payroll[m["category"]] += v
    estimated = set()
    benefits = totals.pop("payroll_benefits", 0)
    total_payroll = sum(payroll.values())
    if benefits and total_payroll:
        for cat, p in payroll.items():
            totals[cat] += benefits * p / total_payroll
            estimated.add(cat)
    elif benefits:
        totals["payroll_benefits"] = benefits  # no salaries to share it by
    overhead = totals.pop("ssw_overhead", 0)
    if overhead:
        totals["sewer"] += overhead * sewer_share
        totals["solid_waste"] += overhead * (1 - sewer_share)
        estimated |= {"sewer", "solid_waste"}
    return totals, estimated


def unmatched(
    rows: list[dict], subtotals: list[dict], column: str, mapping: dict
) -> dict[str, tuple[int, str, str]]:
    """For each department whose lines do not add up to its printed, confirmed
    subtotal, the difference (cents) and the category it belongs to: that of
    the department's unconfirmed lines, or failing a single one, of most of
    its lines, and the statement. Keyed by a pseudo-account id."""
    out = {}
    check = f"{column}_check"
    for sub in subtotals:
        if sub[column] == "" or not {"sum", "repeat", "difference"} & set(sub[check].split(";")):
            continue  # no exactly confirmed subtotal to go by (a percentage can't vouch for it to the dollar)
        key = (sub["statement"], sub["fund_code"], sub["department_code"])
        lines = [r for r in rows if (r["statement"], r["fund_code"], r["department_code"]) == key]
        if not lines:
            continue
        diff = cents(sub[column]) - sum(cents(r[column]) or 0 for r in lines)
        if abs(diff) < 100:  # within a dollar: cents misread, not worth a line
            continue
        doubtful = {
            mapping[r["ledger_id"]]["category"]
            for r in lines
            if r[column] == "" or r[check] in ("", "corrected")
        }
        cats = Counter(mapping[r["ledger_id"]]["category"] for r in lines)
        category = next(iter(doubtful)) if len(doubtful) == 1 else cats.most_common(1)[0][0]
        key = f"unmatched:{sub['statement']}:{sub['fund_code']}-{sub['department_code']}"
        out[key] = (diff, category, sub["statement"])
    return out


def side_of(category: str, statement: str) -> str:
    if category in SPENDING:
        return "spending"
    if category in REVENUE:
        return "revenue"
    return f"excluded_{statement}"


def main() -> int:
    everything = read_csv(SERIES_CSV)
    series = [r for r in everything if r["row_type"] == "item"]
    dept_subtotals: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in everything:
        if r["row_type"] == "department_subtotal":
            dept_subtotals[(int(r["year"]), int(r["month"]))].append(r)
    mapping = {m["ledger_id"]: m for m in read_csv(MAPPING_CSV)}
    problems = sorted({r["ledger_id"] for r in series} - set(mapping))
    extra = sorted(set(mapping) - {r["ledger_id"] for r in series})
    known = set(SPENDING) | set(REVENUE) | POOLED | EXCLUDED
    bad = sorted({m["category"] for m in mapping.values()} - known)
    if problems or extra or bad:
        print(f"{rel(MAPPING_CSV)}: unmapped accounts {problems}; unknown accounts {extra}; "
              f"unknown categories {bad}", file=sys.stderr)  # fmt: skip
        return 1
    wrong_side = [
        lid for lid, m in mapping.items()
        if (m["category"] in SPENDING and m["statement"] != "expense")
        or (m["category"] in REVENUE and m["statement"] != "revenue")
    ]  # fmt: skip
    if wrong_side:
        print(
            f"{rel(MAPPING_CSV)}: revenue/expense category on the wrong side: {wrong_side}", file=sys.stderr
        )
        return 1

    adopted = {
        (r["item_id"], int(r["year"])): cents(r["amount"])
        for r in read_csv(BUDGET_SERIES_CSV)
        if r["measure"] == "adopted_budget"
    }
    shares = ssw_sewer_share(adopted)

    # Account values by (year, month), per measure, split by statement.
    months: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in series:
        months[(int(r["year"]), int(r["month"]))].append(r)

    out = []
    for (year, month), rows in sorted(months.items()):
        if year not in shares:
            print(
                f"no adopted budget for {year} to split the Sewer & Solid Waste overhead by", file=sys.stderr
            )
            return 1
        per_measure = {}
        residuals = {}
        for measure, column in MEASURES.items():
            extra = unmatched(rows, dept_subtotals[(year, month)], column, mapping)
            for statement in ("expense", "revenue"):
                values = {
                    r["ledger_id"]: cents(r[column])
                    for r in rows
                    if r["statement"] == statement and r[column] != ""
                }
                found = {k: (diff, cat) for k, (diff, cat, st) in extra.items() if st == statement}
                ext = dict(mapping) | {k: {"category": cat, "payroll": ""} for k, (_, cat) in found.items()}
                values |= {k: diff for k, (diff, _) in found.items()}
                residuals[(measure, statement)] = found
                per_measure[(measure, statement)] = (
                    categorize(values, ext, shares[year]),
                    values,
                )
        docs = {
            "reported_doc_id": next((r["reported_doc_id"] for r in rows if r["reported_doc_id"]), ""),
            "restated_doc_id": next((r["restated_doc_id"] for r in rows if r["restated_doc_id"]), ""),
        }
        for statement in ("expense", "revenue"):
            categories = set()
            for measure in MEASURES:
                (totals, _), _ = per_measure[(measure, statement)]
                categories |= set(totals)
            order = SPENDING + REVENUE + sorted(POOLED | EXCLUDED)
            for cat in sorted(categories, key=order.index):
                row = {"year": year, "month": month, "side": side_of(cat, statement), "category": cat, **docs}
                estimated = False
                for measure in MEASURES:
                    (totals, est), values = per_measure[(measure, statement)]
                    row[measure] = dollars(totals.get(cat)) if values else ""
                    estimated |= cat in est and bool(values)
                accounts = [
                    r for r in rows
                    if r["statement"] == statement and mapping[r["ledger_id"]]["category"] == cat
                ]  # fmt: skip
                row["accounts"] = len(accounts)
                for measure, col in (("ytd", "unmatched"), ("restated_ytd", "restated_unmatched")):
                    amount = sum(d for d, c in residuals[(measure, statement)].values() if c == cat)
                    row[col] = dollars(amount) if amount else ""
                # Year-to-date figures that no check confirms, or that could not be read.
                for col, doc in (("ytd", "reported_doc_id"), ("restated_ytd", "restated_doc_id")):
                    row[col.replace("ytd", "unconfirmed")] = (
                        sum(
                            1
                            for r in accounts
                            if r[doc] and (r[col] == "" or r[f"{col}_check"] in ("", "corrected"))
                        )
                        if any(r[doc] for r in accounts)
                        else ""
                    )
                row["estimated"] = "yes" if estimated else ""
                out.append(row)

    checks = mapping_checks(out, adopted)
    write_csv(SUMMARY_CSV, SUMMARY_FIELDS, out)
    write_csv(CHECKS_CSV, CHECK_FIELDS, checks)
    print(f"Wrote {rel(SUMMARY_CSV)} ({len(out)} rows) and {rel(CHECKS_CSV)}")
    report_checks(checks)
    return 0


def mapping_checks(summary: list[dict], adopted: dict) -> list[dict]:
    """Each year's budget by category, from the year's first monthly report,
    beside the adopted budget summary's figure for that category."""
    first: dict[int, int] = {}
    for r in summary:
        if r["budget"] != "" and r["reported_doc_id"]:
            first[r["year"]] = min(first.get(r["year"], 13), r["month"])
    out = []
    for kind, side in (("spending", "spending"), ("revenue", "revenue")):
        cats = {c["key"]: c["items"] for c in OVERVIEW[kind]["broad"]}
        cats["total"] = [OVERVIEW[kind]["total"]]
        for year, month in sorted(first.items()):
            rows = [r for r in summary if r["year"] == year and r["month"] == month and r["side"] == side]
            ledger = {r["category"]: cents(r["budget"]) or 0 for r in rows}
            ledger["total"] = sum(ledger.values())
            estimated = {r["category"] for r in rows if r["estimated"]}
            for cat, items in cats.items():
                values = [adopted.get((i, year)) for i in items]
                adopted_value = (
                    sum(v for v in values if v is not None) if any(v is not None for v in values) else None
                )
                led = ledger.get(cat, 0)
                out.append(
                    {"year": year, "side": side, "category": cat, "ledger_budget": dollars(led),
                     "adopted_budget": dollars(adopted_value),
                     "difference": dollars(led - adopted_value) if adopted_value is not None else "",
                     "estimated": "yes" if cat in estimated else "",
                     "doc_id": next((r["reported_doc_id"] for r in rows), ""),
                     "note": check_note(year, side, cat, led, adopted_value, cat in estimated)}
                )  # fmt: skip
    return out


def check_note(year: int, side: str, cat: str, ledger: int, adopted: int | None, estimated: bool) -> str:
    """Why the ledger and the adopted summary differ, if they do (by more than $1 of rounding)."""
    if adopted is None or abs(ledger - adopted) <= 100:
        return ""
    for key in ((year, side, cat), (year, "*", "*"), (side, cat)):
        if key in CHECK_NOTES:
            return CHECK_NOTES[key]
    if estimated:
        return (
            "Includes shared-out employee benefits or Sewer & Solid Waste overhead, which the summaries "
            "share out differently."
        )
    return ""


def report_checks(checks: list[dict]) -> None:
    compared = [c for c in checks if c["difference"]]
    exact = [c for c in compared if abs(Decimal(c["difference"])) <= 1]
    unexplained = [c for c in compared if abs(Decimal(c["difference"])) > 1 and not c["note"]]
    print(f"Mapping check: {len(exact)} of {len(compared)} year-category budgets match the adopted budget "
          f"summary to the dollar; {len(compared) - len(exact) - len(unexplained)} differ for known reasons, "
          f"{len(unexplained)} unexplained")  # fmt: skip
    for c in unexplained:
        print(f"  UNEXPLAINED {c['year']} {c['side']} {c['category']}: {c['difference']}")
    for c in checks:
        if c["category"] == "total":
            print(f"  {c['year']} {c['side']:8} total: ledger {c['ledger_budget']:>13}, adopted "
                  f"{c['adopted_budget']:>13}, difference {c['difference']}")  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
