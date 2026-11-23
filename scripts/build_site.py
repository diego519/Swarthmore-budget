#!/usr/bin/env python3
"""Build the website (docs/): the budget overview and the line explorer.

Each page is a single self-contained HTML file -- a template from
scripts/templates/ with the shared stylesheet and script (common.css,
common.js) and the budget data (as JSON) written into it. The pages need no
server or external libraries: open them locally or host them anywhere
(e.g. GitHub Pages, serving the docs/ folder). With GA_MEASUREMENT_ID set,
the published pages also report visits to Google Analytics.

    docs/index.html      overview: totals over time by broad category, and
                         what drove the change between two years
    docs/explorer.html   any single budget line, year by year
    docs/actuals.html    actual spending and revenue against the budget, from
                         the monthly financial reports

Inputs:
    data/processed/budget_series.csv   (from build_budget_series.py)
    data/mappings/budget_items.csv     labels, grouping and notes
    data/sources.csv                   document titles
    data/external/cpi_u.csv            consumer prices, for the inflation
                                       adjustment (from fetch_cpi.py; optional)
    data/processed/proposed_budget_summary.csv
                                       the latest proposed budget, by category
                                       (from build_proposed_summary.py; optional)
    data/processed/monthly_summary.csv the monthly reports' budget and actuals by
                                       category (from build_monthly_summary.py)
    data/processed/monthly_series.csv  their accounts (from build_monthly_series.py)
    data/processed/budget_line_actuals.csv
                                       budget lines' actuals from the monthly reports,
                                       where they match (from build_line_actuals.py)
    pyproject.toml                     the release version, shown on each page

Usage:
    uv run scripts/build_site.py
"""

from __future__ import annotations

import calendar
import datetime
import json
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

from common import DATA_DIR, PROCESSED_DIR, REPO_ROOT, read_csv, rel, sources_by_id

TEMPLATES = Path(__file__).parent / "templates"
PAGES = {"overview.html": "index.html", "explorer.html": "explorer.html", "actuals.html": "actuals.html"}
OUTPUT_DIR = REPO_ROOT / "docs"
SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
ITEMS_CSV = DATA_DIR / "mappings" / "budget_items.csv"
CPI_CSV = DATA_DIR / "external" / "cpi_u.csv"
PROPOSED_CSV = PROCESSED_DIR / "proposed_budget_summary.csv"
MONTHLY_SUMMARY_CSV = PROCESSED_DIR / "monthly_summary.csv"
MONTHLY_SERIES_CSV = PROCESSED_DIR / "monthly_series.csv"
MONTHLY_MAPPING_CSV = DATA_DIR / "mappings" / "monthly_account_categories.csv"
LINE_ACTUALS_CSV = PROCESSED_DIR / "budget_line_actuals.csv"

REPO_URL = "https://github.com/diego519/Swarthmore-budget"
DOC_URL = "https://www.swarthmorepa.org/DocumentCenter/View/{doc_id}"
# Google Analytics (GA4) measurement ID, "G-..." (Admin > Data streams in the
# GA property). Empty: the pages include no analytics. See the README.
GA_MEASUREMENT_ID = "G-597GBN3XND"
DEFAULT_ITEM = "exp.total"
VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def money(v: int) -> str:
    return f"${v:,}"


# Short keys keep the embedded JSON small: a = adopted budget, e = estimated
# actual, r = restated budget; d = document id, p = page, c = hand-corrected,
# s = source-error note.
MEASURE_KEYS = {"adopted_budget": "a", "estimated_actual": "e", "restated_budget": "r"}


def cat(key: str, label: str, items: list[str], link: str | None = None) -> dict:
    """A "broad" category on the overview page: the sum of one or more budget
    lines. `key` names it in proposed budgets (proposed_budget_summary.csv);
    `link` is the line the explorer opens for it (only for single lines)."""
    return {
        "key": key,
        "label": label,
        "items": items,
        "link": link or (items[0] if len(items) == 1 else None),
    }


def group(label: str, items: list[str], keys: list[str]) -> dict:
    """A group of broad categories, stacked on the overview's column chart.
    `items` give its adopted figures; `keys` its proposed ones."""
    return {"label": label, "items": items, "keys": keys, "link": items[0] if len(items) == 1 else None}


# The overview page's categories. "broad" is the split used for "what
# changed"; "groups" stack up to the total each year, bottom to top. Both must
# add up to the total (checked below), and each group's keys must cover the
# same budget lines as its items.
OVERVIEW = {
    "spending": {
        "total": "exp.total",
        "broad": [
            cat("police", "Police", ["exp.ps.police.subtotal"]),
            cat("fire", "Fire protection", ["exp.ps.fire.subtotal"]),
            cat("gg", "General government", ["exp.gg.total"]),
            cat("streets", "Streets", ["exp.pw.streets.subtotal"]),
            cat("sewer", "Sanitary sewer", ["exp.pw.sewer.subtotal"]),
            cat("solid_waste", "Solid waste (trash & recycling)", ["exp.pw.solid_waste.subtotal"]),
            cat("parks", "Parks & street trees", ["exp.pw.parks.subtotal"]),
            cat("pw_vehicles", "Public works vehicles", ["exp.pw.vehicles.subtotal"]),
            cat("pw_other", "Public works, other", ["exp.pw.misc.subtotal"]),
            cat("community", "Community services", ["exp.cs.total"]),
        ],
        "groups": [
            group("Public safety", ["exp.ps.total"], ["police", "fire"]),
            group(
                "Public works",
                ["exp.pw.total"],
                ["streets", "sewer", "solid_waste", "parks", "pw_vehicles", "pw_other"],
            ),
            group("General government", ["exp.gg.total"], ["gg"]),
            group("Community services", ["exp.cs.total"], ["community"]),
        ],
    },
    "revenue": {
        "total": "rev.total",
        "broad": [
            cat("property_taxes", "Property taxes", ["rev.property_taxes"]),
            cat("eit", "Earned income tax", []),
            cat("sewer_fees", "Sewer fees", ["rev.sewer_fees"]),
            cat("trash_fees", "Trash fees", ["rev.trash_fees"]),
            cat("other_taxes", "Other taxes", ["rev.other_taxes"]),
            cat("intergovernmental", "Intergovernmental (state aid)", ["rev.intergovernmental"]),
            cat("misc_revenue", "Miscellaneous revenue", ["rev.misc.subtotal"]),
            cat(
                "prior_year_funds",
                "Prior-year funds",
                ["rev.prior_year_revenue", "rev.prior_year_pension_revenue"],
            ),
        ],
        "groups": [
            group("Property taxes", ["rev.property_taxes"], ["property_taxes"]),
            group("Sewer & trash fees", ["rev.sewer_fees", "rev.trash_fees"], ["sewer_fees", "trash_fees"]),
            group(
                "Other taxes & state aid",
                ["rev.other_taxes", "rev.intergovernmental"],
                ["other_taxes", "intergovernmental"],
            ),
            group("Miscellaneous revenue", ["rev.misc.subtotal"], ["misc_revenue"]),
            group(
                "Prior-year funds",
                ["rev.prior_year_revenue", "rev.prior_year_pension_revenue"],
                ["prior_year_funds"],
            ),
            group("Earned income tax", [], ["eit"]),
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


def load_proposed(sources: dict) -> dict | None:
    """The latest proposed budget, totalled into the overview's categories
    (from build_proposed_summary.py), and the explorer lines it can be
    compared with: single-line categories, groups and totals."""
    rows = read_csv(PROPOSED_CSV)
    if not rows:
        return None
    year = max(int(r["fiscal_year"]) for r in rows)
    rows = [r for r in rows if int(r["fiscal_year"]) == year]
    other = {
        (r["side"], r["category"]): int(r["amount"]) for r in rows if r["side"] not in ("spending", "revenue")
    }
    rows = [r for r in rows if r["side"] in ("spending", "revenue")]
    amounts = {r["category"]: int(r["amount"]) for r in rows}
    estimated = {r["category"] for r in rows if r["estimated"]}
    keys_for: dict[str, list[str]] = {}
    for view in ("spending", "revenue"):
        for c in OVERVIEW[view]["broad"]:
            if c["link"]:
                keys_for[c["link"]] = [c["key"]]
        for g in OVERVIEW[view]["groups"]:
            if g["link"]:
                keys_for[g["link"]] = g["keys"]
        keys_for[OVERVIEW[view]["total"]] = [c["key"] for c in OVERVIEW[view]["broad"]]
    spending = sum(int(r["amount"]) for r in rows if r["side"] == "spending")
    revenue = sum(int(r["amount"]) for r in rows if r["side"] == "revenue")
    items = {i: sum(amounts[k] for k in ks) for i, ks in keys_for.items()}
    items[OVERVIEW["net"]] = revenue - spending
    doc_id = rows[0]["doc_id"]
    return {
        "excluded": {
            f"{side.split('_')[1]}_{cat}": amount
            for (side, cat), amount in other.items()
            if side != "allocated"
        },
        "benefits": other.get(("allocated", "payroll_benefits"), 0),
        "advertised": sources[doc_id]["period"],
        "year": year,
        "doc_id": doc_id,
        "title": sources[doc_id]["title"],
        "url": DOC_URL.format(doc_id=doc_id),
        "categories": amounts,
        "estimated": sorted(estimated),
        "spending": spending,
        "revenue": revenue,
        "items": items,
        # The split between departments is estimated; the totals are exact.
        "items_estimated": sorted(
            i
            for i, ks in keys_for.items()
            if estimated & set(ks) and i not in (OVERVIEW["spending"]["total"], OVERVIEW["revenue"]["total"])
        ),
    }


def overview_category(item_id: str) -> tuple[str, str] | None:
    """The overview view and category a budget line belongs to ("all" for a
    side's total or group), for linking to the actuals page."""
    for view in ("spending", "revenue"):
        if item_id == OVERVIEW[view]["total"]:
            return view, "all"
        for c in OVERVIEW[view]["broad"]:
            for i in c["items"]:
                parent = i.rsplit(".", 1)[0] + "." if i.endswith((".subtotal", ".total")) else None
                if item_id == i or (parent and item_id.startswith(parent)):
                    return view, c["key"]
        for g in OVERVIEW[view]["groups"]:
            if item_id in g["items"]:
                return view, g["keys"][0] if len(g["keys"]) == 1 else "all"
    return None


def add_line_actuals(values: dict, docs: dict, sources: dict) -> None:
    """Add each budget line's actual from the monthly reports (measure "m"),
    for the years in which its accounts' budget matches its adopted budget."""
    for r in read_csv(LINE_ACTUALS_CSV):
        if r["match"] != "yes" or r["actual"] == "":
            continue
        v = values[r["item_id"]][int(r["year"])]
        v["m"] = round(float(r["actual"]))
        v["md"] = r["doc_id"]
        if r["restated_actual"] and abs(float(r["restated_actual"]) - float(r["actual"])) > TOLERANCE:
            v["mr"] = round(float(r["restated_actual"]))
        if int(r["unconfirmed"] or 0):
            v["mu"] = int(r["unconfirmed"])
        docs[r["doc_id"]] = {
            "title": sources[r["doc_id"]]["title"],
            "url": DOC_URL.format(doc_id=r["doc_id"]),
        }


def amount(text: str) -> float | None:
    return round(float(text), 2) if text else None


def load_monthly(sources: dict) -> dict:
    """The monthly reports' budget and actuals by category, month by month,
    and each year's accounts as of its latest report (for the actuals page).
    Compact rows keep the page small:

      cells:    [year, month, side, category, budget, ytd, restated_ytd,
                 estimated (0/1), unmatched, unconfirmed]
      accounts: {year: [ledger id, description, side, category, budget, ytd,
                 flags ("c" corrected, "u" unconfirmed), doc id, page]}
    """
    rows = read_csv(MONTHLY_SUMMARY_CSV)
    if not rows:
        sys.exit(f"{rel(MONTHLY_SUMMARY_CSV)} not found; run build_monthly_summary.py")
    cells, month_docs, docs = [], {}, {}
    for r in rows:
        if r["side"] not in ("spending", "revenue"):
            continue
        year, month = int(r["year"]), int(r["month"])
        cells.append([
            year, month, r["side"], r["category"], amount(r["budget"]), amount(r["ytd"]), amount(r["restated_ytd"]),
            1 if r["estimated"] else 0, amount(r["unmatched"]),
            int(r["unconfirmed"]) if r["unconfirmed"] != "" else None,
        ])  # fmt: skip
        for key in ("reported_doc_id", "restated_doc_id"):
            if r[key]:
                docs[r[key]] = {"title": sources[r[key]]["title"], "url": DOC_URL.format(doc_id=r[key])}
        if r["reported_doc_id"]:
            month_docs[f"{year}-{month}"] = r["reported_doc_id"]
    reported = defaultdict(list)
    for c in cells:
        if c[5] is not None and f"{c[0]}-{c[1]}" in month_docs:
            reported[c[0]].append(c[1])
    years = sorted(reported)
    latest_month = {y: max(reported[y]) for y in years}

    category = {m["ledger_id"]: m["category"] for m in read_csv(MONTHLY_MAPPING_CSV)}
    accounts: dict[int, list] = defaultdict(list)
    for r in read_csv(MONTHLY_SERIES_CSV):
        if r["row_type"] != "item" or not r["reported_doc_id"]:
            continue
        year = int(r["year"])
        if year not in latest_month or int(r["month"]) != latest_month[year]:
            continue
        checks = set(r["ytd_check"].split(";")) - {""}
        flags = ("c" if "corrected" in checks else "") + ("" if checks - {"corrected"} else "u")
        accounts[year].append([
            r["ledger_id"], r["description"], "spending" if r["statement"] == "expense" else "revenue",
            category[r["ledger_id"]], amount(r["budget"]), amount(r["ytd"]), flags, r["reported_doc_id"],
            int(r["reported_page"]),
        ])  # fmt: skip
    return {
        "years": years,
        "latest_month": latest_month,
        "categories": {
            view: [{"key": c["key"], "label": c["label"]} for c in OVERVIEW[view]["broad"]]
            for view in ("spending", "revenue")
        },
        "cells": cells,
        "month_docs": month_docs,
        "accounts": accounts,
        "docs": docs,
    }


def analytics(measurement_id: str) -> str:
    """The Google Analytics tag for each page's <head>, or nothing without an
    ID. It loads only on the published site (https), not when a page is opened
    from a file or a local server. Usage events are sent by track() in
    common.js."""
    if not measurement_id:
        return ""
    if not re.fullmatch(r"G-[A-Z0-9]+", measurement_id):
        sys.exit(f"GA_MEASUREMENT_ID should look like G-XXXXXXXXXX, not {measurement_id!r}")
    return f"""<script>
if (location.protocol === "https:") {{
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () {{ dataLayer.push(arguments); }};
  gtag("js", new Date());
  gtag("config", "{measurement_id}");
  const tag = document.createElement("script");
  tag.async = true;
  tag.src = "https://www.googletagmanager.com/gtag/js?id={measurement_id}";
  document.head.appendChild(tag);
}}
</script>
"""


def analytics_note(measurement_id: str) -> str:
    """The notice on each page that it uses Google Analytics, if it does."""
    if not measurement_id:
        return ""
    return (
        '<p class="small">This site uses Google Analytics to follow usage trends: how many people visit, and which '
        "of its features they use. No data is collected for commercial purposes.</p>"
    )


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
    add_line_actuals(values, docs, sources)

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

        # Each broad category belongs to exactly one group, and a group's
        # keys must cover the same lines as its items.
        broad = {c["key"]: c for c in view["broad"]}
        grouped = [k for g in view["groups"] for k in g["keys"]]
        if sorted(grouped) != sorted(broad):
            sys.exit(f"overview {view_name}: groups' keys {sorted(grouped)} != broad keys {sorted(broad)}")
        for g in view["groups"]:
            for y in years:
                a = sum(values[i].get(y, {}).get("a", 0) for i in g["items"])
                b = sum(values[i].get(y, {}).get("a", 0) for k in g["keys"] for i in broad[k]["items"])
                if abs(a - b) > TOLERANCE:
                    sys.exit(f"overview {view_name}: group {g['label']} {y}: items {a} != keys {b}")

    proposed = load_proposed(sources)
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

    if proposed:
        x = proposed["excluded"]
        advertised = datetime.date.fromisoformat(proposed["advertised"]).strftime("%B %-d, %Y")
        proposed_note = (
            f"<strong>{proposed['year']} is the proposed budget</strong>, advertised on {advertised} and not yet "
            "adopted. It is laid out by fund and type of expense rather than by department, so each of its lines was "
            "matched by hand to these categories (<code>data/mappings/proposed_budget_categories.csv</code>). To "
            "compare like with like: money moving between the borough's own funds is left out "
            f"({money(x['revenue_interfund'])} of revenue and {money(x['expense_interfund'])} of matching sewer-fund "
            "charges, which the document does not quite reconcile); planned surpluses carried to the next year "
            f"({money(x['expense_surplus'])}) are not counted as spending; the new Capital Fund is left out, and the "
            "General Fund's payments into it are counted under general government, as in earlier budgets. Employee "
            f"benefits ({money(proposed['benefits'])}), now budgeted centrally, are shared among general government, "
            "police and public works in proportion to salaries, so those category figures (marked *) are estimates. "
            "Totals are exact."
            + (
                f" Adjusted for inflation, {proposed['year']} figures are left in {cpi['ref_year']} prices."
                if cpi
                else ""
            )
        )
    else:
        proposed_note = ""

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
                "actuals": overview_category(it["item_id"]),
            }
            for it in items
            if it["item_id"] in values
        ],
        "values": values,
        "docs": docs,
        "overview": OVERVIEW,
        "cpi": cpi,
        "proposed": proposed,
    }

    monthly = load_monthly(sources)
    months = sorted(tuple(map(int, k.split("-"))) for k in monthly["month_docs"])
    month_name = calendar.month_name
    span = [
        (y, m)
        for y in range(months[0][0], months[-1][0] + 1)
        for m in range(1, 13)
        if months[0] <= (y, m) <= months[-1]
    ]
    gaps = [f"{month_name[m]} {y}" for y, m in span if f"{y}-{m}" not in monthly["month_docs"]]
    monthly_range = (
        f"{len(set(monthly['month_docs'].values()))} reports, {month_name[months[0][1]]} {months[0][0]} to "
        f"{month_name[months[-1][1]]} {months[-1][0]}"
    )
    monthly_gaps = (
        (
            f"No usable report is posted for {', '.join(gaps[:-1])} and {gaps[-1]} (some months' reports contain only "
            "the bills list). "
            if len(gaps) > 1
            else f"No usable report is posted for {gaps[0]}. "
            if gaps
            else ""
        )
        + "Where a month's own report is missing, its year-to-date figures are taken from the same month's report a "
        "year later, which repeats them as the previous year's."
    )
    # The actuals page has its own data; it shares the CPI only to carry the
    # dollars setting between pages.
    actuals_data = {"years": [], "items": [], "docs": monthly.pop("docs"), "cpi": cpi, "proposed": None,
                    "monthly": monthly}  # fmt: skip

    def embed(d: dict) -> str:
        # Embedding JSON in a <script> element: "</" must not appear literally.
        return json.dumps(d, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")

    payloads = {
        "overview.html": embed(data),
        "explorer.html": embed(data),
        "actuals.html": embed(actuals_data),
    }
    replacements = {
        "<!--__ANALYTICS__-->\n": analytics(GA_MEASUREMENT_ID),
        "<!--__ANALYTICS_NOTE__-->": analytics_note(GA_MEASUREMENT_ID),
        "/*__COMMON_CSS__*/": (TEMPLATES / "common.css").read_text(encoding="utf-8"),
        "/*__COMMON_JS__*/": (TEMPLATES / "common.js").read_text(encoding="utf-8"),
        "__REPO_URL__": REPO_URL,
        "__VERSION__": VERSION,
        "__LAST_ESTIMATE_YEAR__": str(
            max(int(r["year"]) for r in series if r["measure"] == "estimated_actual")
        ),
        "__DOLLARS_NOTE__": dollars_note,
        "__CATEGORY_NOTE__": CATEGORY_NOTE,
        "__PROPOSED_NOTE__": proposed_note,
        "__MONTHLY_RANGE__": monthly_range,
        "__MONTHLY_GAPS__": monthly_gaps,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for template, output in PAGES.items():
        html = (TEMPLATES / template).read_text(encoding="utf-8")
        for placeholder, value in {**replacements, "__DATA__": payloads[template]}.items():
            html = html.replace(placeholder, value)
        leftover = [p for p in [*replacements, "__DATA__"] if p in html]
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
