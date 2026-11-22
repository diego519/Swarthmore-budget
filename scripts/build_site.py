#!/usr/bin/env python3
"""Build the budget explorer web page (docs/index.html).

The page is a single self-contained HTML file: the template in
scripts/templates/budget_explorer.html with the budget series embedded as
JSON. It needs no server or external libraries, so it can be opened locally
or hosted anywhere (e.g. GitHub Pages, serving the docs/ folder).

Inputs:
    data/processed/budget_series.csv   (from build_budget_series.py)
    data/mappings/budget_items.csv     labels, grouping and notes
    data/sources.csv                   document titles

Usage:
    uv run scripts/build_site.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from common import DATA_DIR, PROCESSED_DIR, REPO_ROOT, read_csv, rel, sources_by_id

TEMPLATE = Path(__file__).parent / "templates" / "budget_explorer.html"
OUTPUT = REPO_ROOT / "docs" / "index.html"
SERIES_CSV = PROCESSED_DIR / "budget_series.csv"
ITEMS_CSV = DATA_DIR / "mappings" / "budget_items.csv"

REPO_URL = "https://github.com/diego519/Swarthmore-budget"
DOC_URL = "https://www.swarthmorepa.org/DocumentCenter/View/{doc_id}"
DEFAULT_ITEM = "exp.total"

# Short keys keep the embedded JSON small: a = adopted budget, e = estimated
# actual, r = restated budget; d = document id, p = page, c = hand-corrected,
# s = source-error note.
MEASURE_KEYS = {"adopted_budget": "a", "estimated_actual": "e", "restated_budget": "r"}


def item_path(it: dict) -> str:
    parts = ["Revenue" if it["section"] == "revenue" else "Expenditures", it["group"], it["subgroup"]]
    return " › ".join(p for p in parts if p)


def main() -> int:
    items = read_csv(ITEMS_CSV)
    series = read_csv(SERIES_CSV)
    sources = sources_by_id()

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

    with_data = [it for it in items if it["item_id"] in values]
    years = sorted({int(r["year"]) for r in series})
    last_estimate_year = max(int(r["year"]) for r in series if r["measure"] == "estimated_actual")
    data = {
        "years": list(range(years[0], years[-1] + 1)),
        "default_item": DEFAULT_ITEM,
        "items": [
            {
                "id": it["item_id"],
                "label": it["label"],
                "type": it["row_type"],
                "path": item_path(it),
                "note": it["note"],
            }
            for it in with_data
        ],
        "values": values,
        "docs": docs,
    }

    # Embedding JSON in a <script> element: "</" must not appear literally.
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in {
        "__DATA__": payload,
        "__REPO_URL__": REPO_URL,
        "__LAST_ESTIMATE_YEAR__": str(last_estimate_year),
    }.items():
        if placeholder not in html:
            sys.exit(f"{rel(TEMPLATE)} has no {placeholder} placeholder")
        html = html.replace(placeholder, value)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(
        f"Wrote {rel(OUTPUT)} ({len(html) / 1024:.0f} KB, {len(with_data)} budget lines, {years[0]}-{years[-1]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
