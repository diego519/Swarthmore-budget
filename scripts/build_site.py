#!/usr/bin/env python3
"""Build the website (docs/): the budget overview and the line explorer.

Each page is a single self-contained HTML file -- a template from
scripts/templates/ with the shared stylesheet and script (common.css,
common.js) and the budget data (as JSON) written into it. The pages need no
server or external libraries: open them locally or host them anywhere
(e.g. GitHub Pages, serving the docs/ folder).

    docs/index.html      overview: totals over time by broad category, and
                         what drove the change between two years
    docs/explorer.html   any single budget line, year by year

Inputs:
    data/processed/budget_series.csv   (from build_budget_series.py)
    data/mappings/budget_items.csv     labels, grouping and notes
    data/sources.csv                   document titles
    data/external/cpi_u.csv            consumer prices, for the inflation
                                       adjustment (from fetch_cpi.py; optional)

Usage:
    uv run scripts/build_site.py
"""

from __future__ import annotations

import calendar
import json
import sys
from collections import defaultdict
from pathlib import Path

from common import DATA_DIR, PROCESSED_DIR, REPO_ROOT, read_csv, rel, sources_by_id

TEMPLATES = Path(__file__).parent / "templates"
PAGES = {"overview.html": "index.html", "explorer.html": "explorer.html"}
OUTPUT_DIR = REPO_ROOT / "docs"
SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
ITEMS_CSV = DATA_DIR / "mappings" / "budget_items.csv"
CPI_CSV = DATA_DIR / "external" / "cpi_u.csv"

REPO_URL = "https://github.com/diego519/Swarthmore-budget"
DOC_URL = "https://www.swarthmorepa.org/DocumentCenter/View/{doc_id}"
DEFAULT_ITEM = "exp.total"

# Short keys keep the embedded JSON small: a = adopted budget, e = estimated
# actual, r = restated budget; d = document id, p = page, c = hand-corrected,
# s = source-error note.
MEASURE_KEYS = {"adopted_budget": "a", "estimated_actual": "e", "restated_budget": "r"}


def cat(label: str, items: list[str], link: str | None = None) -> dict:
    """A category on the overview page: the sum of one or more budget lines.
    `link` is the line the explorer opens for it (only for single lines)."""
    return {"label": label, "items": items, "link": link or (items[0] if len(items) == 1 else None)}


# The overview page's categories. "groups" stack up to the total each year,
# bottom to top (they must add up to it: checked below). "broad" is the finer
# split used for "what changed"; it must add up to the total too.
OVERVIEW = {
    "spending": {
        "total": "exp.total",
        "groups": [
            cat("Public safety", ["exp.ps.total"]),
            cat("Public works", ["exp.pw.total"]),
            cat("General government", ["exp.gg.total"]),
            cat("Community services", ["exp.cs.total"]),
        ],
        "broad": [
            cat("Police", ["exp.ps.police.subtotal"]),
            cat("Fire protection", ["exp.ps.fire.subtotal"]),
            cat("General government", ["exp.gg.total"]),
            cat("Streets", ["exp.pw.streets.subtotal"]),
            cat("Sanitary sewer", ["exp.pw.sewer.subtotal"]),
            cat("Solid waste (trash & recycling)", ["exp.pw.solid_waste.subtotal"]),
            cat("Parks & street trees", ["exp.pw.parks.subtotal"]),
            cat("Public works vehicles", ["exp.pw.vehicles.subtotal"]),
            cat("Public works, other", ["exp.pw.misc.subtotal"]),
            cat("Community services", ["exp.cs.total"]),
        ],
    },
    "revenue": {
        "total": "rev.total",
        "groups": [
            cat("Property taxes", ["rev.property_taxes"]),
            cat("Sewer & trash fees", ["rev.sewer_fees", "rev.trash_fees"]),
            cat("Other taxes & state aid", ["rev.other_taxes", "rev.intergovernmental"]),
            cat("Miscellaneous revenue", ["rev.misc.subtotal"]),
            cat("Prior-year funds", ["rev.prior_year_revenue", "rev.prior_year_pension_revenue"]),
        ],
        "broad": [
            cat("Property taxes", ["rev.property_taxes"]),
            cat("Sewer fees", ["rev.sewer_fees"]),
            cat("Trash fees", ["rev.trash_fees"]),
            cat("Other taxes", ["rev.other_taxes"]),
            cat("Intergovernmental (state aid)", ["rev.intergovernmental"]),
            cat("Miscellaneous revenue", ["rev.misc.subtotal"]),
            cat("Prior-year funds", ["rev.prior_year_revenue", "rev.prior_year_pension_revenue"]),
        ],
    },
    "net": "exp.net",
}

CATEGORY_NOTE = (
    "Spending groups are the budgets' own: <strong>public safety</strong> (police and fire), <strong>public "
    "works</strong> (streets, sewer, trash &amp; recycling, parks, vehicles), <strong>general government</strong> "
    "(administration, buildings, debt, grants, reserves) and <strong>community services</strong> (library, "
    "recreation, Town Center, seniors, PAC Center). Revenue sources group the budgets' revenue lines: "
    "<strong>other taxes</strong> are the real estate transfer and local services taxes; <strong>state "
    "aid</strong> is intergovernmental revenue; <strong>miscellaneous revenue</strong> includes police service "
    "contracts, permits, fines, contributions from Swarthmore College, interest and grants; "
    "<strong>prior-year funds</strong> are fund balances carried over from earlier years."
)
TOLERANCE = 5  # dollars: categories may differ from printed totals by rounding


def load_cpi() -> dict | None:
    """Annual averages of the monthly CPI-U; the latest year may be partial."""
    if not CPI_CSV.exists():
        return None
    rows = read_csv(CPI_CSV)
    months: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r["value"]:  # empty: not published by BLS
            months[int(r["year"])].append(float(r["value"]))
    index = {y: round(sum(v) / len(v), 3) for y, v in months.items()}
    ref = max(index)
    latest = max((int(r["year"]), int(r["month"])) for r in rows if r["value"])
    return {
        "index": index,
        "ref_year": ref,
        "partial": {y: len(v) for y, v in months.items() if len(v) < 12},
        "latest_month": latest[1],
        "unpublished": [
            {"year": int(r["year"]), "month": int(r["month"]), "note": r["note"]}
            for r in rows
            if not r["value"]
        ],
        "series": rows[0]["series_id"],
    }


def main() -> int:
    items = read_csv(ITEMS_CSV)
    series = read_csv(SERIES_CSV)
    sources = sources_by_id()
    item_ids = {it["item_id"] for it in items}

    values: dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(dict))
    docs = {}
    for r in series:
        k = MEASURE_KEYS[r["measure"]]
        v = values[r["item_id"]][int(r["year"])]
        v[k] = int(r["amount"])
        v[k + "d"] = r["doc_id"]
        v[k + "p"] = int(r["page"])
        if r["corrected"]:
            v[k + "c"] = 1
        if r["source_error"]:
            v[k + "s"] = r["source_error"]
        docs[r["doc_id"]] = {
            "title": sources[r["doc_id"]]["title"],
            "url": DOC_URL.format(doc_id=r["doc_id"]),
        }

    years = list(range(min(int(r["year"]) for r in series), max(int(r["year"]) for r in series) + 1))

    # The overview's categories must cover their totals exactly (to rounding).
    for view_name in ("spending", "revenue"):
        view = OVERVIEW[view_name]
        for kind in ("groups", "broad"):
            for c in view[kind]:
                for item_id in c["items"]:
                    if item_id not in item_ids:
                        sys.exit(f"overview {view_name}/{kind}: unknown budget line {item_id}")
            for y in years:
                total = values[view["total"]].get(y, {}).get("a")
                parts = sum(values[i].get(y, {}).get("a", 0) for c in view[kind] for i in c["items"])
                if total is not None and abs(total - parts) > TOLERANCE:
                    sys.exit(f"overview {view_name}/{kind}: {y} categories add to {parts}, total is {total}")

    cpi = load_cpi()
    if cpi and not all(y in cpi["index"] for y in years):
        sys.exit(f"{rel(CPI_CSV)} lacks some years in {years[0]}-{years[-1]}; run fetch_cpi.py")
    if cpi:
        ref = cpi["ref_year"]
        month_name = calendar.month_name
        so_far = (
            f" {ref}'s price level is the average of January to {month_name[cpi['latest_month']]} {ref}, the "
            "months published so far."
            if ref in cpi["partial"]
            else ""
        )
        gaps = "".join(
            f" {month_name[u['month']]} {u['year']} was not published"
            + (f" ({u['note'].rstrip('.')})" if u["note"] else "")
            + f", so {u['year']}'s average uses the other months."
            for u in cpi["unpublished"]
        )
        dollars_note = (
            "Figures are shown <strong>as budgeted</strong> (nominal dollars). Choose <strong>“In "
            f"{ref} dollars”</strong> to adjust them for inflation with the Consumer Price Index for All Urban "
            "Consumers (CPI-U, U.S. city average, from the Bureau of Labor Statistics): each year's figure is "
            f"multiplied by {ref}'s average price level divided by that year's.{so_far}{gaps}"
        )
    else:
        dollars_note = "Figures are in <strong>nominal dollars</strong>: they are not adjusted for inflation."

    data = {
        "years": years,
        "default_item": DEFAULT_ITEM,
        "items": [
            {
                "id": it["item_id"],
                "label": it["label"],
                "type": it["row_type"],
                "path": " › ".join(
                    p
                    for p in [
                        "Revenue" if it["section"] == "revenue" else "Expenditures",
                        it["group"],
                        it["subgroup"],
                    ]
                    if p
                ),
                "note": it["note"],
            }
            for it in items
            if it["item_id"] in values
        ],
        "values": values,
        "docs": docs,
        "overview": OVERVIEW,
        "cpi": cpi,
    }

    # Embedding JSON in a <script> element: "</" must not appear literally.
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    replacements = {
        "/*__COMMON_CSS__*/": (TEMPLATES / "common.css").read_text(encoding="utf-8"),
        "/*__COMMON_JS__*/": (TEMPLATES / "common.js").read_text(encoding="utf-8"),
        "__DATA__": payload,
        "__REPO_URL__": REPO_URL,
        "__LAST_ESTIMATE_YEAR__": str(
            max(int(r["year"]) for r in series if r["measure"] == "estimated_actual")
        ),
        "__DOLLARS_NOTE__": dollars_note,
        "__CATEGORY_NOTE__": CATEGORY_NOTE,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for template, output in PAGES.items():
        html = (TEMPLATES / template).read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            html = html.replace(placeholder, value)
        leftover = [p for p in replacements if p in html]
        if leftover:
            sys.exit(f"{template}: unreplaced placeholders {leftover}")
        out = OUTPUT_DIR / output
        out.write_text(html, encoding="utf-8")
        print(f"Wrote {rel(out)} ({len(html) / 1024:.0f} KB)")
    print(
        f"{len(data['items'])} budget lines, {years[0]}-{years[-1]}"
        + (f"; CPI to {cpi['ref_year']}" if cpi else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
