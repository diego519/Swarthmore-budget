#!/usr/bin/env python3
"""Download the Consumer Price Index used to adjust budgets for inflation.

The series is the CPI for All Urban Consumers (CPI-U), U.S. city average,
all items, not seasonally adjusted -- BLS series CUUR0000SA0, the standard
measure of consumer price inflation. Not-seasonally-adjusted figures are not
revised after publication, so a download is reproducible.

It is fetched from the Bureau of Labor Statistics' public API (no key
needed) for every year from the first budget year to the current year, and
saved month by month to data/external/cpi_u.csv. build_site.py averages the
months of each year; the current year's average uses the months published
so far. Months BLS did not publish have an empty value and BLS's note.

Usage:
    uv run scripts/fetch_cpi.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import requests
from common import DATA_DIR, PROCESSED_DIR, read_csv, rel, write_csv

SERIES_ID = "CUUR0000SA0"
API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/{series}?startyear={start}&endyear={end}"
YEARS_PER_REQUEST = 10  # the API's limit without a registration key
CPI_CSV = DATA_DIR / "external" / "cpi_u.csv"
USER_AGENT = "Mozilla/5.0 (compatible; swarthmore-budget/0.1; open-data research script)"


def fetch(start: int, end: int) -> list[dict]:
    url = API_URL.format(series=SERIES_ID, start=start, end=end)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {body.get('status')} {body.get('message')}")
    rows = []
    for d in body["Results"]["series"][0]["data"]:
        if d["period"].startswith("M") and d["period"] != "M13":  # months only, not annual averages
            rows.append(
                {
                    "series_id": SERIES_ID,
                    "year": int(d["year"]),
                    "month": int(d["period"][1:]),
                    # BLS marks months it did not publish with "-" and a footnote
                    # (e.g. October 2025, lost to the federal government shutdown).
                    "value": "" if d["value"] == "-" else d["value"],
                    "note": "; ".join(f["text"] for f in d.get("footnotes", []) if f.get("text")),
                }
            )
    return rows


def main() -> int:
    first = min(int(r["year"]) for r in read_csv(PROCESSED_DIR / "budget_series.csv"))
    last = datetime.now(UTC).year
    rows: list[dict] = []
    for start in range(first, last + 1, YEARS_PER_REQUEST):
        rows += fetch(start, min(start + YEARS_PER_REQUEST - 1, last))
    rows.sort(key=lambda r: (r["year"], r["month"]))
    write_csv(CPI_CSV, ["series_id", "year", "month", "value", "note"], rows)
    latest = rows[-1]
    print(
        f"Wrote {rel(CPI_CSV)}: {len(rows)} months, {rows[0]['year']}-{latest['year']}/{latest['month']:02d}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
