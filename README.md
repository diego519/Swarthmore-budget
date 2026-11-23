# Swarthmore Borough Budget

An independent, open, and reproducible look at the finances of
[Swarthmore Borough](https://www.swarthmorepa.org) (Delaware County,
Pennsylvania), built entirely from documents the borough publishes on its
website.

**Website: <https://diego519.github.io/Swarthmore-budget/>**

> **Not affiliated with Swarthmore Borough.** This project only collects and
> reorganizes public records. The borough's own documents are the
> authoritative source; if anything here disagrees with them, they win. Please
> [open an issue](../../issues) if you find a mistake.

## Goals

1. **Collect** every publicly posted budget, audit, and monthly financial
   report. *(done)*
2. **Parse** them into clean, machine-readable tables. *(adopted budgets: in
   progress; see [status](#status))*
3. **Summarize** the top-level picture: revenue, spending, fund balances, and
   how they change over time. *(adopted budgets: done)*
4. **Visualize** it on a public, interactive website. *(see
   [Website](#website))*

Each step is a plain script that reads the previous step's output, so anyone
can re-run the whole analysis and check every number back to its page in a
source PDF.

## Status

| Table | Years | State |
| --- | --- | --- |
| [`budget_summary.csv`](data/processed/budget_summary.csv) | 2017–2026 adopted budgets | **Complete.** Every printed subtotal and total reconciles with its rows, except six errors in the borough's own documents, which are documented. |
| [`budget_line_items.csv`](data/processed/budget_line_items.csv) | 2023–2025 adopted budgets (the only years with line items) | **Partly reconciled.** Each row's `table_check` column says whether its table's printed total has been reconciled. Rows marked `FAIL` are not yet verified. |
| [`budget_series.csv`](data/processed/budget_series.csv) | 2016–2026, one series per summary line | **Complete.** The summary lines linked across years (renamed lines combined), with adopted budget, estimated actual, and each figure's source page. |
| [`proposed_budget_lines.csv`](data/processed/proposed_budget_lines.csv) | 2027 proposed (advertised) budget | **Complete.** Every line of every fund, with the 2026 budget, 2026 year-to-date and 2025 actual columns; every fund subtotal reconciles. |
| [`proposed_budget_summary.csv`](data/processed/proposed_budget_summary.csv) | 2027 proposed budget | The proposal totalled into the categories of the 2016–2026 summaries, for comparison (see [Comparing a proposed budget](#5-comparing-a-proposed-budget)). |

## Reproducing the analysis

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which
installs the right Python version and the exact library versions pinned in
`uv.lock`.

```sh
git clone https://github.com/diego519/Swarthmore-budget.git
cd Swarthmore-budget

# 1. Download every catalogued document from the borough website (~400 MB)
uv run scripts/fetch_documents.py download
uv run scripts/fetch_documents.py verify      # confirm identical copies

# 2. Parse the adopted budgets into data/processed/
uv run scripts/parse_budgets.py

# 3. Parse the latest proposed budget and total it into comparable categories
uv run scripts/parse_proposed_budget.py
uv run scripts/build_proposed_summary.py

# 4. Link each budget line across years, and build the website
uv run scripts/build_budget_series.py
uv run scripts/build_site.py                  # writes docs/index.html and docs/explorer.html
```

The inflation adjustment uses consumer price data saved in
`data/external/cpi_u.csv`. To refresh it (e.g. when a new month is published),
run `uv run scripts/fetch_cpi.py` before `build_site.py`.

Step 2 reads the OCR output committed in `data/ocr/`, so it does not need any
OCR software. To redo the OCR as well, install
[Tesseract](https://tesseract-ocr.github.io/) (`brew install tesseract` or
`apt install tesseract-ocr`) and run:

```sh
uv run scripts/ocr_documents.py --category budget_adopted --force
```

With Tesseract 5.5.4 (the version recorded in `data/ocr/manifest.csv`) this
reproduces `data/ocr/` byte for byte. Other versions may differ slightly; `git
diff` shows exactly how.

If `verify` reports a mismatch, the borough has replaced that document since
we downloaded it. The checksum in `data/downloads.csv` identifies the version
we used.

## How it works

### 1. Collecting documents

Every file on the borough website has a permanent numeric id and lives at
`https://www.swarthmorepa.org/DocumentCenter/View/<id>`.

| Step | Command | What it does |
| --- | --- | --- |
| Discover | `fetch_documents.py discover` | Reads the borough's finance pages and saves every document link, with its on-page label, to `data/site_links.csv`. Lists any link not yet catalogued. |
| Catalogue | *(by hand)* | A person reviews each new document and adds a row to `data/sources.csv` saying what it actually is: type, year, period. |
| Download | `fetch_documents.py download` | Downloads everything in `data/sources.csv` to `data/raw/` and records each file's SHA-256 checksum in `data/downloads.csv`. |

The catalogue step is done by hand on purpose: the website's link labels are
sometimes wrong (see [data/README.md](data/README.md#known-issues-with-the-source-documents)),
and a reviewed catalogue is easier to audit than code that guesses.

The pages scanned are
[Taxes & Finance](https://www.swarthmorepa.org/403/Taxes-Finance),
[Borough Budget](https://www.swarthmorepa.org/407/Borough-Budget) and
[Financial Reports](https://www.swarthmorepa.org/2272/Financial-Reports).

### 2. Reading scanned pages (OCR)

Many documents are scanned images with no text. `ocr_documents.py` renders
each such page, turns it upright (several are scanned sideways or upside
down), erases table borders, and runs Tesseract. Numbers are then re-read with
Tesseract restricted to digits, which fixes its habit of misreading this
typeface's "1". Every word is saved with its position and confidence to
`data/ocr/<doc_id>.csv`.

OCR still makes mistakes. Each one found is fixed by hand in
[`data/corrections/ocr_corrections.csv`](data/corrections/ocr_corrections.csv):
one row per word, saying what OCR read, what the page shows, and how that was
checked. Every corrected value is flagged in the output tables.

### 3. Parsing and checking

`parse_budgets.py` reads words with their positions, from the PDF text layer
where there is one and from the OCR output otherwise, and rebuilds the
budgets' tables. It then checks the arithmetic: every printed subtotal and
total is compared with the sum of the rows it covers. All results go to
[`data/processed/budget_checks.csv`](data/processed/budget_checks.csv).
Differences caused by the borough's own documents, not by our reading of them,
are explained in
[`data/corrections/budget_source_errors.csv`](data/corrections/budget_source_errors.csv).

### 4. Linking lines across years

Each year's budget is a separate document, and the same line can be labelled
differently from year to year: renamed ("Swarthmore Borough Authority" became
"Swarthmore College"), or misspelt by OCR. The hand-curated
[`data/mappings/budget_items.csv`](data/mappings/budget_items.csv) lists each
budget line once, with every label it has appeared under and a note wherever
two labels were judged to be the same line. `build_budget_series.py` uses it to
build [`budget_series.csv`](data/processed/budget_series.csv), and stops if any
row in any budget is not accounted for.

As a check on those judgments, it compares each year's adopted budget with the
figure the following year's budget gives for it
([`budget_series_checks.csv`](data/processed/budget_series_checks.csv)). Of 701
comparisons, 661 are identical; the rest are rounding, revisions by the borough
(e.g. reallocating shared costs), or the known source errors.

### 5. Comparing a proposed budget

From 2027 the borough lays out its budget by fund (General, Sewer & Solid
Waste, Liquid Fuels, and a new Capital Fund) and by type of expense, not by the
department groups of its 2016–2026 summaries. `parse_proposed_budget.py`
reads every line of the proposal and checks each fund's lines against its
printed subtotals. To set the proposal beside earlier years, each line is
assigned by hand to one of the overview's categories in
[`data/mappings/proposed_budget_categories.csv`](data/mappings/proposed_budget_categories.csv),
with a note wherever the choice needed judgment. `build_proposed_summary.py`
then totals the categories, making four adjustments so the comparison is like
for like:

- **Money moving between the borough's own funds is left out.** The Sewer &
  Solid Waste Fund pays the General Fund for its share of staff and overhead
  ($188,001 of charges; the General Fund books $180,301 as received, a $7,700
  difference the document does not explain). The General Fund already budgets
  those costs in full.
- **Planned surpluses** carried into 2028 ("balance forward" expense lines,
  $154,828) are not spending.
- **The new Capital Fund is left out.** The General Fund's payments into it are
  counted under general government, as contributions to capital were before.
- **Employee benefits** ($1.02M), now budgeted centrally, are shared among
  general government, police and public works in proportion to each one's
  2027 salaries, since earlier budgets included benefits in each department's
  personnel costs. Category figures that include a share are **estimates**;
  the totals are exact.

Comparisons are firmest for the totals and the department groups. Within
public works, for example, crew wages are now budgeted together (and counted
under streets), which moves money between public works categories.

## Website

Two interactive pages, built from the summary series:

- **Overview** ([`docs/index.html`](docs/index.html)): where the budget is
  headed. Total adopted spending or revenue each year, plus the latest
  proposed budget, stacked by department group (spending) or source
  (revenue), and a ranked breakdown of what drove the change between any two
  years, by category or (for adopted years) by individual budget line.
- **Explore a budget line** ([`docs/explorer.html`](docs/explorer.html)): any
  single line, from total spending down to, say, police personnel, with its
  adopted budget and estimated actual each year and its change from year to
  year or since the first year. Every figure in its table links to the page of
  the borough's budget it comes from.

Both pages can show figures **as budgeted** or **adjusted for inflation**, in
the latest year's dollars. The adjustment uses the Consumer Price Index for
All Urban Consumers (CPI-U, U.S. city average, not seasonally adjusted; BLS
series `CUUR0000SA0`), averaged over each calendar year: a year's figure is
multiplied by the latest year's average price level divided by that year's.
The latest year's average uses the months published so far; months the BLS
did not publish (October 2025, during the federal government shutdown) are
left out of their year's average.

Each page is one self-contained HTML file that needs nothing else to work:
open it in a browser, or host it anywhere. The site is published with GitHub
Pages from the `main` branch's `/docs` folder at
<https://diego519.github.io/Swarthmore-budget/>; pushing rebuilt pages to
`main` updates it.

### Analytics

With `GA_MEASUREMENT_ID` set in `scripts/build_site.py`, the published pages
report visits to Google Analytics (GA4). Pages opened from a file or a local
server report nothing. If you publish your own copy of the site, set
`GA_MEASUREMENT_ID` to your own ID or to `""`. Besides GA's standard measures (page views, visitors,
engagement time, and clicks on links to other sites, such as the borough's
documents), the pages send these events:

| Event | Parameters | Sent when someone... |
| --- | --- | --- |
| `change_setting` | `setting`, `choice` | changes a control. `setting` is `view` (spending or revenue), `years` (e.g. `2016-2027`), `detail` (break down by category or budget line), `dollars` (`nominal` or `real`), `budget_line` (the explorer's line, e.g. `exp.ps.police.subtotal`), `base` (change compared with the previous year, `yoy`, or the first, `since`) or `unit` (`pct` or `usd`). |
| `chart_tooltip` | `chart` | first reads a chart's figures by hovering or with the keyboard (once per chart per page view): `stack-chart` and `drivers-chart` on the overview, `amount-chart` and `change-chart` in the explorer. |
| `open_table` | `table` | opens a "Table of values" on the overview: `stack-table` or `drivers-table`. |

To set it up:

1. In [Google Analytics](https://analytics.google.com), create a property with
   a **Web** data stream for `https://diego519.github.io`, and copy its
   measurement ID (`G-...`) into `GA_MEASUREMENT_ID`.
2. In that data stream's **Enhanced measurement** settings, open **Page
   views**' advanced settings and turn off **Page changes based on browser
   history events**. The pages keep their settings in the URL, so with it on
   every click on a control counts as a page view.
3. Under **Admin > Custom definitions**, create an event-scoped custom
   dimension for each parameter (`setting`, `choice`, `chart`, `table`), so
   they appear in reports. GA only records them from then on.
4. Rebuild the site and push it to `main`.

### Updating when the borough posts something new

```sh
uv run scripts/fetch_documents.py discover   # lists new documents
# ...add a row to data/sources.csv for each one...
uv run scripts/fetch_documents.py download   # fetches only what's new
git add data/ && git commit
```

## Releases

Changes are recorded in [CHANGELOG.md](CHANGELOG.md), and each release is
tagged in git (`v1.0.0`, ...) and listed on the
[releases page](../../releases). The version in `pyproject.toml` is printed
at the bottom of every page of the website, so a figure quoted from the site
can be traced to the release it came from, and that release's code and data
can be checked out with `git checkout v1.0.0`.

Version numbers follow [Semantic Versioning](https://semver.org), read for a
data project:

- **Major**: a change that breaks reuse. A column or file in
  `data/processed/` is renamed, removed, or changes meaning, or links into the
  website stop working.
- **Minor**: new data or features. A newly posted budget or other document is
  added, a new page or chart appears, or a change of method revises published
  figures.
- **Patch**: corrections. A misread or mismapped figure is fixed, or wording
  and display are corrected.

When figures change, the changelog lists which ones.

To make a release:

```sh
# 1. Move the changelog's [Unreleased] notes under a new version heading,
#    and set the same version in pyproject.toml.
uv lock                          # records the new version in uv.lock
uv run scripts/build_site.py     # prints the new version on the pages
git commit -am "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main vX.Y.Z
# 2. Publish the release, with that version's changelog section as its notes:
gh release create vX.Y.Z --title vX.Y.Z --notes-file <notes.md>
```

## What's here

```
CHANGELOG.md         What changed in each release
data/
  sources.csv        Catalogue of documents (hand-curated, the source of truth)
  site_links.csv     Snapshot of document links on the borough website
  downloads.csv      SHA-256 checksum, size, and retrieval time of each file
  raw/               Downloaded documents (not committed; ~400 MB)
  ocr/               OCR output: every word on every scanned page, with position
  corrections/       Hand corrections to OCR, and known errors in the source documents
  mappings/          Which rows in different years' budgets are the same budget line
  external/          Consumer Price Index (for the inflation adjustment)
  processed/         Parsed tables, linked series, and the arithmetic checks
  README.md          Column definitions and known data issues
docs/                (generated by build_site.py; do not edit by hand)
  index.html         Overview page
  explorer.html      Explore a budget line
scripts/
  fetch_documents.py      discover / download / verify source documents
  ocr_documents.py        OCR scanned pages
  parse_budgets.py        parse adopted budgets and check their arithmetic
  build_budget_series.py  link budget lines across years
  parse_proposed_budget.py   parse proposed budgets (fund-by-fund layout, from 2027)
  build_proposed_summary.py  total a proposed budget into comparable categories
  fetch_cpi.py            download the Consumer Price Index
  build_site.py           build the website from templates/
  common.py               shared helpers
```

See [data/README.md](data/README.md) for what's covered, the column
definitions, and known problems with the source documents.

## License

Code is released under the [MIT License](LICENSE). The source documents are
public records published by Swarthmore Borough.
