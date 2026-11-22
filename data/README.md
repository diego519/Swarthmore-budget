# Data

| File | Made by | Purpose |
| --- | --- | --- |
| `sources.csv` | hand | Catalogue of every known document and what it actually is. **Source of truth.** |
| `site_links.csv` | `fetch_documents.py discover` | Snapshot of the document links on the borough's finance pages, labels and all. |
| `downloads.csv` | `fetch_documents.py download` | Checksum, size, original filename and retrieval time of each downloaded file. |
| `raw/` | `fetch_documents.py download` | The documents themselves, as `raw/<category>/<doc_id>_<title>.<ext>`. Not committed to git. |
| `ocr/<doc_id>.csv` | `ocr_documents.py` | Every word OCR found on a document's scanned pages, with its position and confidence. |
| `ocr/manifest.csv` | `ocr_documents.py` | Which source file (by checksum) and Tesseract version produced each OCR file. |
| `corrections/ocr_corrections.csv` | hand | Words OCR misread, and what the page actually shows. |
| `corrections/budget_source_errors.csv` | hand | Arithmetic errors in the borough's own budget documents. |
| `processed/budget_summary.csv` | `parse_budgets.py` | Adopted budgets, summary level, 2017-2026. |
| `processed/budget_line_items.csv` | `parse_budgets.py` | Adopted budgets, ledger-account level, 2023-2025. |
| `processed/budget_checks.csv` | `parse_budgets.py` | Every printed subtotal and total, checked against the rows it covers. |

## Coverage

As of November 2026: 118 documents (about 385 MB).

| Category | Entity | Years | Count |
| --- | --- | --- | ---: |
| Adopted budget | Borough | 2017–2026 | 11 |
| Proposed budget, drafts, presentations, ordinances | Borough | 2027 cycle | 16 |
| Monthly financial report | Borough | Jun 2021 – Oct 2026 | 63 |
| Audited financial statements | Borough | 2018–2023 | 6 |
| DCED Municipal Annual Audit and Financial Report | Borough | 2022, 2024 | 2 |
| Audited financial statements | Police pension plan | 2018–2020, 2022–2023 | 5 |
| Audited financial statements | Non-uniformed pension plan | 2017–2020, 2022–2023 | 6 |
| Act 205 actuarial valuation | Both pension plans | 2017, 2019 | 3 |
| Act 44 disclosure, MMO resolution | Pension plans | various | 4 |
| Audited / summary financial statements | Borough Authority | 2024 | 2 |

### Gaps

These are not posted on the borough website (as of the date above):

- Monthly reports for **March 2024, November 2024, October 2025**, and anything before June 2021.
- Monthly reports for **May 2025, July 2025, January 2026** contain only the bills list
  (wire transactions, open invoices), not the revenue and expenditure summary.
- Borough audited financial statements for **2024** (only the state DCED form is posted) and before 2018.
- Police and non-uniformed pension audits for **2021** and **2024**.
- The **9/15/2026 Capital Fund draft** (its link points to the General Fund draft).

## Known issues with the source documents

The borough website's link labels are sometimes wrong. Each document was opened
and checked; corrections are recorded in the `notes` column of `sources.csv`.
The main ones:

| doc_id | Website says | Actually is |
| ---: | --- | --- |
| 808 | 2017 Act 205 Pension Valuation – Non-Uniformed | 2017 non-uniformed pension plan **audit** |
| 1456 | 2021 Police Pension Audited Financial Statement | Resolution 2020-19, the police pension **Minimum Municipal Obligation** for 2021 |
| 2877 | 2021 Non-Uniformed Audited Financial Statement *(one of two links)* | The **2023** non-uniformed pension audit |
| 3207 | 2024 Audit and Financial Report | The state **DCED-CLGS-30** form, not the auditor's financial statements |
| 3741 | 2027 Capital Fund Draft 9.15.26 | Byte-identical copy of the **General Fund** draft (3736) |
| 3822, 3823 | 2026 Approved Budget | Byte-identical copies of 3467 and 3466 (marked `include=no`) |

**Monthly reports are named for the meeting, not the month.** A report covering July is
typically presented at the August council meeting, so files are often named after the
later month (e.g. `aug expenditures.pdf`). The `period` column in `sources.csv` is the
month the report covers, taken from each report's cover page ("Through the Month of …").
Every monthly report's period was checked this way.

**Many documents are scanned images.** Every monthly report, the 2023–2025 adopted
budgets, and a handful of others (noted in `sources.csv`) have no text layer and will
need OCR to extract numbers. The borough audits, most pension audits, the 2017–2022 and
2026 budgets, and the 2027 drafts have selectable text. Some PDFs are encrypted with an
owner password (no password is needed to open them).

**Some budgets' arithmetic does not add up.** Checking every printed subtotal and
total found six places where a budget's own figures disagree with its rows (all
listed in `corrections/budget_source_errors.csv`). For example, the 2024 budget
prints 2023's total expenditures as $5,628,873, which is the 2022 figure; its rows
add to $6,218,188.

## Column definitions

### `sources.csv`

| Column | Description |
| --- | --- |
| `doc_id` | The borough's Document Center id. The file is at `https://www.swarthmorepa.org/DocumentCenter/View/<doc_id>`. |
| `include` | `yes` to download; `no` for documents deliberately skipped (with the reason in `notes`). |
| `category` | Document type; see below. |
| `entity` | Whose finances: `borough`, `police_pension`, `nonuniformed_pension`, or `borough_authority`. |
| `fiscal_year` | The fiscal (calendar) year the document is about. Blank if unknown. |
| `period` | For monthly reports, the month covered (`YYYY-MM`). For drafts and presentations, the date presented (`YYYY-MM-DD`). |
| `title` | Our descriptive title. Also used for the local filename. |
| `notes` | Anything a reader should know, especially where the website label is wrong. |

Categories:

| `category` | Meaning |
| --- | --- |
| `budget_adopted` | Annual budget as adopted by Borough Council |
| `budget_proposed` | Budget as advertised for public comment before adoption |
| `budget_draft` | Working drafts of individual funds during the budget process |
| `presentation` | Slides presented at budget sessions |
| `ordinance` | Tax and fee ordinances |
| `monthly_report` | Monthly financial report to council: revenue and expenditure summary vs. budget, budget-to-actual detail by fund, and the bills list |
| `audit` | Independent auditor's financial statements |
| `audit_summary` | Summary financial statement |
| `dced_report` | Pennsylvania DCED Municipal Annual Audit and Financial Report (form DCED-CLGS-30) |
| `pension_valuation` | Act 205 actuarial valuation of a pension plan |
| `pension_disclosure` | Act 44 disclosure by a pension service provider |
| `pension_mmo` | Minimum Municipal Obligation (required annual pension contribution) |

### `site_links.csv`

One row per distinct link on each page scanned: `doc_id`, `source_page`,
`section_heading` (the nearest heading above the link), and `link_text`
(verbatim). Comparing versions of this file in git history shows what the
borough added, removed or relabelled over time.

### `downloads.csv`

| Column | Description |
| --- | --- |
| `doc_id` | Matches `sources.csv` |
| `path` | Local path, relative to the repository root |
| `sha256` | SHA-256 of the file. `fetch_documents.py verify` checks your copy against this. |
| `bytes` | File size |
| `content_type` | As reported by the server |
| `original_filename` | The filename the borough uploaded, from the `Content-Disposition` header |
| `retrieved_at_utc` | When this exact version (this checksum) was first downloaded. Re-downloading identical bytes leaves it unchanged. |

### `processed/budget_summary.csv`

One row per line of each adopted budget's summary ("REVENUE - ALL OPERATING
FUNDS" and "EXPENDITURES - ALL OPERATING FUNDS"). Each budget shows the prior
year's budget and estimated actual alongside the new budget, so most figures
appear in two documents; they usually agree, but the borough sometimes
revises a prior year's figures.

| Column | Description |
| --- | --- |
| `doc_id`, `page` | Where the row is printed. |
| `fiscal_year` | The year the budget is for. |
| `extraction` | `text` (read from the PDF's text layer: exact) or `ocr` (read from a scan). |
| `section` | `revenue` or `expenditure`. |
| `group` | Expenditure group: `GENERAL GOVERNMENT`, `PUBLIC SAFETY`, `PUBLIC WORKS` or `COMMUNITY SERVICES`. |
| `subgroup` | The heading the row sits under, e.g. `Police Services`, `Other Revenue`. |
| `item` | The row's label, as printed (OCR spelling slips are not normalised). |
| `row_type` | `item`, `subtotal`, `total`, or `net` (revenue less expenditure). Sum only `item` rows. |
| `prior_year_budget` | Budget for `fiscal_year - 1`, in dollars. |
| `prior_year_estimated_actual` | Estimated actual for `fiscal_year - 1` (not shown in the 2026 budget). |
| `budget` | Adopted budget for `fiscal_year`. |
| `corrected` | Columns whose value comes from a hand correction (see `corrections/ocr_corrections.csv`). |

### `processed/budget_line_items.csv`

One row per ledger account in the "Revenue by Category" and "Expenditures by
Category" tables, which only the 2023, 2024 and 2025 budgets include.

| Column | Description |
| --- | --- |
| `doc_id`, `page`, `fiscal_year`, `extraction`, `section`, `group` | As above. |
| `table` | The table's title, e.g. `Property Taxes`, `Police General Expenditures`. |
| `fund` | As printed: `General`, `SSW` (Sewer & Solid Waste), `Highway` (Liquid Fuels), `Pension`, or `Allocated (GF)` / `Allocated (SSW)` for costs split between funds. |
| `account`, `account_number` | Ledger account name and number (e.g. `400.020`). Some rows, such as benefits, have no number. |
| `prior_year_budget`, `budget` | As above. |
| `corrected` | As above. |
| `table_check` | Whether the table's rows add up to its printed total: `ok`, `rounding`, `source error` (explained in `corrections/budget_source_errors.csv`), `FAIL` (not yet reconciled; treat these rows with caution), or `no total`. |

### `processed/budget_checks.csv`

| Column | Description |
| --- | --- |
| `doc_id`, `page` | Where the printed total is. |
| `check` | What was checked, e.g. `subtotal: Police Services`, `table total: Fines`, `stated total revenue`. |
| `column` | Which amount column. |
| `printed`, `computed`, `difference` | The printed figure, the sum of the rows it covers, and `computed - printed`. |
| `status` | `ok`; `rounding` (off by no more than half a dollar per row, from the borough's spreadsheets rounding each figure); `source error` (a mistake in the document itself, explained in `note`); or `FAIL`. |

### `ocr/<doc_id>.csv`

| Column | Description |
| --- | --- |
| `page`, `rotation` | Page number, and how far it was rotated to be upright. |
| `line` | Text line number on the page, as Tesseract grouped them. |
| `x0`, `top`, `x1`, `bottom` | The word's box, in points (1/72 inch) from the upright page's top-left corner. |
| `conf` | Tesseract's confidence, 0-100. |
| `text` | The word. |
| `first_pass_text` | If the word is a number that was re-read with digits-only OCR, what the first pass read. |

### `corrections/ocr_corrections.csv`

Applied when OCR output is loaded. Each correction must match exactly one word,
so if OCR is re-run and its output changes, a stale correction stops the
parse instead of being misapplied.

| Column | Description |
| --- | --- |
| `doc_id`, `page` | The page. |
| `line_contains` | Text (as OCR'd) that picks out the line. |
| `ocr_text` | The word as OCR read it. Empty to insert a word OCR missed. |
| `corrected_text` | What the page shows. |
| `x` | For an inserted word, its left edge in points. |
| `note` | What was wrong and how the correct value was confirmed (by eye against the page image, and where possible against the printed totals or the same figure in another year's budget). |
