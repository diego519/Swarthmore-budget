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

# 3. Link each budget line across years, and build the website
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

## Website

Two interactive pages, built from the summary series:

- **Overview** ([`docs/index.html`](docs/index.html)): where the budget is
  headed. Total adopted spending or revenue each year, stacked by department
  group (spending) or source (revenue), and a ranked breakdown of what drove
  the change between any two years, by category or by individual budget line.
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

Each page is one self-contained HTML file with no external dependencies: open
it in a browser, or host it anywhere. The site is published with GitHub Pages
from the `main` branch's `/docs` folder at
<https://diego519.github.io/Swarthmore-budget/>; pushing rebuilt pages to
`main` updates it.

### Updating when the borough posts something new

```sh
uv run scripts/fetch_documents.py discover   # lists new documents
# ...add a row to data/sources.csv for each one...
uv run scripts/fetch_documents.py download   # fetches only what's new
git add data/ && git commit
```

## What's here

```
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
  fetch_cpi.py            download the Consumer Price Index
  build_site.py           build the website from templates/
  common.py               shared helpers
```

See [data/README.md](data/README.md) for what's covered, the column
definitions, and known problems with the source documents.

## License

Code is released under the [MIT License](LICENSE). The source documents are
public records published by Swarthmore Borough.
