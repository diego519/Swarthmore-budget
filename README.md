# Swarthmore Borough Budget

An independent, open, and reproducible look at the finances of
[Swarthmore Borough](https://www.swarthmorepa.org) (Delaware County,
Pennsylvania), built entirely from documents the borough publishes on its
website.

> **Not affiliated with Swarthmore Borough.** This project only collects and
> reorganizes public records. The borough's own documents are the
> authoritative source; if anything here disagrees with them, they win. Please
> [open an issue](../../issues) if you find a mistake.

## Goals

1. **Collect** every publicly posted budget, audit, and monthly financial
   report. *(done: see below)*
2. **Parse** them into clean, machine-readable tables. *(next)*
3. **Summarize** the top-level picture: revenue, spending, fund balances, and
   how they change over time.
4. **Visualize** it on a public, interactive website.

Each step is a plain script that reads the previous step's output, so anyone
can re-run the whole analysis and check every number back to its page in a
source PDF.

## Reproducing the analysis

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which
installs the right Python version and the exact library versions pinned in
`uv.lock`.

```sh
git clone https://github.com/diego519/Swarthmore-budget.git
cd Swarthmore-budget

# Download every catalogued document from the borough website (~400 MB)
uv run scripts/fetch_documents.py download

# Confirm your copies are byte-for-byte identical to the ones we used
uv run scripts/fetch_documents.py verify
```

If `verify` reports a mismatch, the borough has replaced that document since
we downloaded it. The checksum in `data/downloads.csv` identifies the version
we used.

## How the documents are collected

Every file on the borough website has a permanent numeric id and lives at
`https://www.swarthmorepa.org/DocumentCenter/View/<id>`. Collection works in
three steps:

| Step | Command | What it does |
| --- | --- | --- |
| Discover | `fetch_documents.py discover` | Reads the borough's finance pages and saves every document link, with its on-page label, to `data/site_links.csv`. Lists any link not yet catalogued. |
| Catalogue | *(by hand)* | A person reviews each new document and adds a row to `data/sources.csv` saying what it actually is: type, year, period. |
| Download | `fetch_documents.py download` | Downloads everything in `data/sources.csv` to `data/raw/` and records each file's SHA-256 checksum in `data/downloads.csv`. |

The catalogue step is done by hand on purpose: the website's link labels are
sometimes wrong (see [data/README.md](data/README.md#known-issues-with-the-source-documents)),
and a reviewed catalogue is easier to audit than code that guesses.

The pages scanned are:

- [Taxes & Finance](https://www.swarthmorepa.org/403/Taxes-Finance): adopted budgets, audits, pension reports
- [Borough Budget](https://www.swarthmorepa.org/407/Borough-Budget): the current budget cycle's drafts and presentations
- [Financial Reports](https://www.swarthmorepa.org/2272/Financial-Reports): monthly financial reports

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
  sources.csv       Catalogue of documents (hand-curated, the source of truth)
  site_links.csv    Snapshot of document links on the borough website
  downloads.csv     SHA-256 checksum, size, and retrieval time of each file
  raw/              Downloaded documents (not committed; see below)
  README.md         Column definitions and known data issues
scripts/
  fetch_documents.py
```

The downloaded documents are **not** stored in git: together they are about
400 MB, mostly because the 2021–22 monthly reports are large scans. The
checksums in `data/downloads.csv` let anyone confirm they are working from the
same files.

See [data/README.md](data/README.md) for what's covered, the column
definitions, and known problems with the source documents.

## License

Code is released under the [MIT License](LICENSE). The source documents are
public records published by Swarthmore Borough.
