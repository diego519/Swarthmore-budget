#!/usr/bin/env python3
"""Total a proposed budget's lines into the categories of earlier budgets.

From 2027 the borough lays its budget out by fund and by type of expense,
not by the department groups its 2016-2026 budget summaries used. To compare
a proposal with those years, each line is assigned by hand to one of the
overview's categories in data/mappings/proposed_budget_categories.csv, which
also handles three things that would otherwise distort the comparison:

  interfund         Money moving between the borough's own funds (the Sewer &
                    Solid Waste Fund's share of staff and overhead, paid to
                    the General Fund) is left out on both sides, so each cost
                    is counted once.
  surplus           "Balance forward" expense lines are planned surpluses
                    carried to the next year, not spending.
  capital_fund      The new Capital Fund is outside the operating funds that
                    earlier summaries covered. The General Fund's payment into
                    it is counted (as general government) instead.
  payroll_benefits  Employee benefits are budgeted centrally, but earlier
                    budgets included them in each department's personnel
                    costs. They are shared out in proportion to each
                    category's salaries (lines marked payroll=yes). The
                    resulting category figures are estimates.

A category can also be split across categories with explicit amounts, e.g.
"police:499375;fire:53000".

Every parsed line must be mapped exactly once; the script stops otherwise.
Totals are checked: categories must add up to the funds' totals less
transfers, surpluses and the Capital Fund.

Output:
    data/processed/proposed_budget_summary.csv   one row per category ("spending"
        or "revenue"), plus the amounts left out ("excluded_revenue",
        "excluded_expense") and the benefits shared out ("allocated")

Usage:
    uv run scripts/build_proposed_summary.py
"""

from __future__ import annotations

import sys
from collections import defaultdict

from common import DATA_DIR, PROCESSED_DIR, read_csv, rel, write_csv

LINES_CSV = PROCESSED_DIR / "proposed_budget_lines.csv"
MAPPING_CSV = DATA_DIR / "mappings" / "proposed_budget_categories.csv"
SUMMARY_CSV = PROCESSED_DIR / "proposed_budget_summary.csv"

SPENDING = [
    "police",
    "fire",
    "gg",
    "streets",
    "sewer",
    "solid_waste",
    "parks",
    "pw_vehicles",
    "pw_other",
    "community",
]
REVENUE = [
    "property_taxes", "eit", "sewer_fees", "trash_fees", "other_taxes",
    "intergovernmental", "misc_revenue", "prior_year_funds",
]  # fmt: skip
EXCLUDED = {"interfund", "surplus", "capital_fund"}
FIELDS = ["fiscal_year", "doc_id", "side", "category", "amount", "estimated", "lines"]


def main() -> int:
    lines = read_csv(LINES_CSV)
    mapping = {
        (m["fiscal_year"], m["fund"], m["section"], m["page"], m["account"]): m for m in read_csv(MAPPING_CSV)
    }
    problems, out = [], []

    for year in sorted({r["fiscal_year"] for r in lines}):
        rows = [r for r in lines if r["fiscal_year"] == year]
        totals: dict[str, dict[str, int]] = {"revenue": defaultdict(int), "expense": defaultdict(int)}
        count: dict[str, int] = defaultdict(int)
        payroll: dict[str, int] = defaultdict(int)
        benefits = 0
        used = set()
        for r in rows:
            key = (r["fiscal_year"], r["fund"], r["section"], r["page"], r["account"])
            m = mapping.get(key)
            if m is None:
                problems.append(
                    f"{year} {r['fund']} p{r['page']} {r['account']!r}: not in {rel(MAPPING_CSV)}"
                )
                continue
            used.add(key)
            amount = int(r["budget"] or 0)
            side = totals[r["section"]]
            valid = SPENDING if r["section"] == "expense" else REVENUE
            if m["category"] == "payroll_benefits":
                benefits += amount
                count["payroll_benefits"] += 1
                continue
            parts = (
                [(c, int(a)) for c, a in (p.split(":") for p in m["category"].split(";"))]
                if ":" in m["category"]
                else [(m["category"], amount)]
            )
            if sum(a for _, a in parts) != amount:
                problems.append(f"{r['account']!r}: split {m['category']} does not add up to {amount}")
            for c, a in parts:
                if c not in valid and c not in EXCLUDED:
                    problems.append(f"{r['account']!r} ({r['section']}): unknown category {c!r}")
                side[c] += a
                count[c] += 1
                if m["payroll"] == "yes":
                    payroll[c] += a
        stale = [k for k in mapping if k[0] == year and k not in used]
        problems += [f"mapping entry matches no line: {k}" for k in stale]
        if problems:
            break

        # Share centrally budgeted benefits by salaries.
        total_payroll = sum(payroll.values())
        shares = {c: round(benefits * p / total_payroll) for c, p in payroll.items()}
        shares[max(shares, key=shares.get)] += benefits - sum(shares.values())  # rounding remainder
        for c, a in shares.items():
            totals["expense"][c] += a

        doc_id = rows[0]["doc_id"]
        for side_name, cats, section in (("spending", SPENDING, "expense"), ("revenue", REVENUE, "revenue")):
            for c in cats:
                out.append(
                    {
                        "fiscal_year": year,
                        "doc_id": doc_id,
                        "side": side_name,
                        "category": c,
                        "amount": totals[section][c],
                        "estimated": "yes" if section == "expense" and c in shares else "",
                        "lines": count[c],
                    }
                )
        # What was left out of the comparison, and the benefits shared out.
        for section in ("revenue", "expense"):
            for c in sorted(EXCLUDED):
                out.append(
                    {
                        "fiscal_year": year,
                        "doc_id": doc_id,
                        "side": f"excluded_{section}",
                        "category": c,
                        "amount": totals[section][c],
                        "estimated": "",
                        "lines": "",
                    }
                )
        out.append(
            {
                "fiscal_year": year,
                "doc_id": doc_id,
                "side": "allocated",
                "category": "payroll_benefits",
                "amount": benefits,
                "estimated": "yes",
                "lines": count["payroll_benefits"],
            }
        )

        # Reconcile: categories = fund totals less the excluded lines.
        for section in ("revenue", "expense"):
            fund_total = sum(int(r["budget"] or 0) for r in rows if r["section"] == section)
            excluded = sum(totals[section][c] for c in EXCLUDED)
            cats = SPENDING if section == "expense" else REVENUE
            counted = sum(totals[section][c] for c in cats)
            if counted != fund_total - excluded:
                problems.append(
                    f"{year} {section}: categories {counted} != funds {fund_total} - excluded {excluded}"
                )
            print(
                f"{year} {section}: funds ${fund_total:,}, less transfers ${totals[section]['interfund']:,}, "
                f"surplus ${totals[section]['surplus']:,}, Capital Fund ${totals[section]['capital_fund']:,} "
                f"= ${counted:,}"
            )
        print(
            f"{year} benefits shared by payroll: ${benefits:,} -> "
            + ", ".join(f"{c} ${a:,}" for c, a in shares.items())
        )

    if problems:
        print("Cannot build the summary; fix these first:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    write_csv(SUMMARY_CSV, FIELDS, out)
    print(f"Wrote {rel(SUMMARY_CSV)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
