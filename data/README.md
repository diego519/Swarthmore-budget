# Data

| File | Made by | Purpose |
| --- | --- | --- |
| `sources.csv` | hand | Catalogue of every known document and what it actually is. **Source of truth.** |
| `site_links.csv` | `fetch_documents.py discover` | Snapshot of the document links on the borough's finance pages, labels and all. |
| `downloads.csv` | `fetch_documents.py download` | Checksum, size, original filename and retrieval time of each downloaded file. |
| `raw/` | `fetch_documents.py download` | The documents themselves, as `raw/<category>/<doc_id>_<title>.<ext>`. Not committed to git. |
| `ocr/<doc_id>.csv` | `ocr_documents.py` | Every word OCR found on a document's scanned pages, with its position and confidence. |
| `ocr/manifest.csv` | `ocr_documents.py` | Which source file (by checksum), Tesseract version and settings produced each OCR file. |
| `corrections/ocr_corrections.csv` | hand | Words OCR misread, and what the page actually shows. |
| `corrections/budget_source_errors.csv` | hand | Arithmetic errors in the borough's own budget documents. |
| `processed/budget_summary.csv` | `parse_budgets.py` | Adopted budgets, summary level, 2017-2026. |
| `processed/budget_line_items.csv` | `parse_budgets.py` | Adopted budgets, ledger-account level, 2023-2025. |
| `processed/budget_checks.csv` | `parse_budgets.py` | Every printed subtotal and total, checked against the rows it covers. |
| `mappings/budget_items.csv` | hand | Each summary budget line, with every label it has appeared under. |
| `processed/budget_series.csv` | `build_budget_series.py` | Each summary line's figures by year, linked across documents. |
| `processed/budget_series_checks.csv` | `build_budget_series.py` | Each year's adopted budget compared with the figure the next year's budget gives. |
| `external/cpi_u.csv` | `fetch_cpi.py` | Consumer Price Index (CPI-U), monthly, for the inflation adjustment. |
| `processed/proposed_budget_lines.csv` | `parse_proposed_budget.py` | Every line of the proposed budget(s), by fund. |
| `processed/proposed_budget_checks.csv` | `parse_proposed_budget.py` | Each fund's printed subtotals vs. the sum of its lines. |
| `mappings/proposed_budget_categories.csv` | hand | Which overview category each proposed-budget line belongs to. |
| `processed/proposed_budget_summary.csv` | `build_proposed_summary.py` | The proposal totalled into the overview's categories. |
| `corrections/proposed_budget_source_errors.csv` | hand | Arithmetic errors in proposed budgets (none so far). |
| `processed/monthly_report_lines.csv` | `parse_monthly_reports.py` | Monthly reports: every ledger account's budget and actuals to date, this year and last. |
| `processed/monthly_report_checks.csv` | `parse_monthly_reports.py` | Every arithmetic check of the monthly reports and its result. |
| `processed/monthly_report_summary.csv` | `parse_monthly_reports.py` | Monthly reports' cover pages: consolidated totals and cash balance. |
| `corrections/monthly_report_source_errors.csv` | hand | Mistakes in the monthly reports' cover pages. |
| `processed/monthly_series.csv` | `build_monthly_series.py` | The monthly reports reconciled: each account's figures by month, OCR misreadings corrected. |
| `processed/monthly_series_corrections.csv` | `build_monthly_series.py` | Every OCR misreading corrected in reconciling, with the evidence. |
| `processed/monthly_series_checks.csv` | `build_monthly_series.py` | Each cover page's totals against the sum of the funds in the detail. |
| `mappings/monthly_account_categories.csv` | hand | Which overview category each ledger account in the monthly reports belongs to. |
| `processed/monthly_summary.csv` | `build_monthly_summary.py` | Monthly budget and actuals to date, by overview category. |
| `processed/monthly_summary_checks.csv` | `build_monthly_summary.py` | Each year's ledger budget by category against the adopted budget summary. |

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
budgets, and a handful of others (noted in `sources.csv`) have no text layer. The
budgets and monthly reports among them have been OCR'd (see `ocr/`); the others have
not yet. Most monthly reports from 2023 on are black-and-white scans of fax quality,
so their OCR needs the most checking (see `processed/monthly_report_lines.csv`). The
borough audits, most pension audits, the 2017–2022 and
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
| `printed_row` | For summary checks, the label of the row that prints the total. |
| `column` | Which amount column. |
| `printed`, `computed`, `difference` | The printed figure, the sum of the rows it covers, and `computed - printed`. |
| `status` | `ok`; `rounding` (off by no more than half a dollar per row, from the borough's spreadsheets rounding each figure); `source error` (a mistake in the document itself, explained in `note`); or `FAIL`. |

### `mappings/budget_items.csv`

One row per budget line in the summary tables. A row in a budget document
belongs to the line whose `section` and `row_type` match, whose `raw_labels`
include the row's label (letters only, lower case: "Snow & Ice Removal" is
`snowiceremoval`), and, for ordinary rows, whose `closing` includes the label
of the subtotal or total that follows the row in the document. That is how,
say, the three "Debt Service" rows (general government, fire, sewer) are told
apart.

| Column | Description |
| --- | --- |
| `item_id` | Stable id, e.g. `exp.ps.police.personnel`. |
| `section`, `group`, `subgroup` | Where the line sits. |
| `label` | Display name. |
| `row_type` | `item`, `subtotal`, `total` or `net`. |
| `closing` | For `item` rows: the subtotal/total label(s) that close it. |
| `raw_labels` | Every label the line has been printed under. |
| `note` | Renames, garbled labels, and what the line covers. |

### `processed/budget_series.csv`

| Column | Description |
| --- | --- |
| `item_id` | See `mappings/budget_items.csv`. |
| `year` | Fiscal (calendar) year the figure is for. |
| `measure` | `adopted_budget` (from that year's budget; 2016's from the 2017 budget), `estimated_actual` (from the next year's budget), or `restated_budget` (the year's budget as the next year's budget gives it). |
| `amount` | Dollars. |
| `doc_id`, `page`, `extraction` | Where the figure is printed, and whether it was read from text or OCR. |
| `corrected` | `yes` if the figure comes from a hand correction of OCR. |
| `source_error` | If the figure is a printed total that does not add up, the explanation. |

### `processed/budget_series_checks.csv`

Each year's `adopted_budget` beside its `restated_budget`, with the
`difference` and the two documents. A difference is not necessarily an error:
it can be rounding, or the borough revising the earlier year's figure.

### `processed/proposed_budget_lines.csv`

| Column | Description |
| --- | --- |
| `doc_id`, `fiscal_year`, `page` | The proposed budget, the year it is for, and the page. |
| `fund` | `General Fund`, `Sewer & Solid Waste Fund`, `Liquid Fuels Fund` or `Capital Fund`. |
| `section` | `revenue` or `expense`. |
| `account` | The line's name, as printed. |
| `budget` | The proposed amount for `fiscal_year`. |
| `prior_year_budget`, `prior_year_to_date`, `two_years_prior_actual` | The document's other columns (for 2027: 2026 budget, 2026 to date, 2025 actual). Blank where the document leaves them blank, which it often does for reorganized lines, so the 2026 column is not a full restatement of the 2026 budget. |
| `note` | The document's explanatory note. |

### `mappings/proposed_budget_categories.csv`

One row per proposed-budget line, identified by `fiscal_year`, `fund`,
`section`, `page` and `account`. `category` is an overview category key
(`police`, `fire`, `gg`, `streets`, `sewer`, `solid_waste`, `parks`,
`pw_vehicles`, `pw_other`, `community`; `property_taxes`, `eit`,
`sewer_fees`, `trash_fees`, `other_taxes`, `intergovernmental`,
`misc_revenue`, `prior_year_funds`), a split such as
`police:499375;fire:53000`, or one of `interfund`, `surplus`, `capital_fund`
(left out of the comparison) and `payroll_benefits` (shared out by salaries).
`payroll` marks salary lines; `note` explains judgment calls.

### `processed/proposed_budget_summary.csv`

| Column | Description |
| --- | --- |
| `fiscal_year`, `doc_id` | The proposal. |
| `side` | `spending` or `revenue` for the categories; `excluded_revenue` / `excluded_expense` for amounts left out; `allocated` for the benefits shared out. |
| `category`, `amount` | The category and its total. |
| `estimated` | `yes` where the amount includes a share of centrally budgeted benefits. |
| `lines` | How many proposed-budget lines it combines. |

### `external/cpi_u.csv`

The Consumer Price Index for All Urban Consumers (CPI-U), U.S. city average,
all items, not seasonally adjusted (1982-84 = 100), from the Bureau of Labor
Statistics' public API. One row per month: `series_id` (`CUUR0000SA0`),
`year`, `month`, `value`, and BLS's `note` for months it did not publish
(their `value` is empty).

### `ocr/<doc_id>.csv`

| Column | Description |
| --- | --- |
| `page`, `rotation` | Page number, and how far it was rotated to be upright. (Monthly report pages scanned a degree or more askew were also straightened; see `ocr_documents.py`.) |
| `line` | Text line number on the page, as Tesseract grouped them. |
| `x0`, `top`, `x1`, `bottom` | The word's box, in points (1/72 inch) from the upright page's top-left corner. |
| `conf` | Tesseract's confidence, 0-100. |
| `text` | The word. |
| `first_pass_text` | If the word is a number that was re-read with digits-only OCR, what the first pass read. |

### `ocr/manifest.csv`

| Column | Description |
| --- | --- |
| `doc_id`, `source_sha256` | The document, and the checksum of the file that was OCR'd. |
| `pages_ocred` | Pages without a text layer, which were OCR'd. |
| `tesseract_version` | The Tesseract version used. |
| `dpi` | The resolution(s) the pages were rendered at. |
| `profile` | `standard`, or `monthly` for monthly reports: 1-bit pages rendered at 400 DPI and smoothed, and askew pages straightened (see `ocr_documents.py`). |
| `created_utc` | When the OCR was run. |

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
| `x` | For an inserted word, or one OCR placed in the wrong spot, its left edge in points. |
| `note` | What was wrong and how the correct value was confirmed (by eye against the page image, and where possible against the printed totals or the same figure in another year's budget). |

### `processed/monthly_report_lines.csv`

One row per line of each monthly report's *Current/Prior Year Comparison
Report*: every ledger account, department subtotal, fund subtotal and total,
for revenue and for expenses. Amounts are in dollars and cents, as printed
(OCR misreads included: see `verified`).

| Column | Description |
| --- | --- |
| `doc_id`, `period`, `page` | The report, the month it covers (`YYYY-MM`), and the page. |
| `statement` | `revenue` or `expense`. |
| `fund_code`, `fund` | `01` General, `04` Sewer & Solid Waste, `05` Highway Aid (Liquid Fuels), `09` Pension, `10` Sinking. |
| `department_code`, `department` | The department heading the line is under, e.g. `410` Police (blank for fund subtotals and totals). Revenue departments are numbered 3xx, expense departments 4xx. |
| `ledger_id`, `description` | The account (`01-410-040`, `PATROL OFFICER`), consistent across reports (see below). |
| `row_type` | `item` (a ledger account), `department_subtotal`, `fund_subtotal` or `total`. Sum only `item` rows. |
| `budget`, `mtd`, `ytd` | This year's budget, the month's total, and the total for the year to date. Reports up to July 2023 have no month-to-date columns. |
| `prior_year_budget`, `prior_year_mtd`, `prior_year_ytd` | The same for the year before, to the same month. |
| `percent`, `prior_year_percent` | The printed percentage of budget (year-to-date / budget), this year and last. |
| `verified` | The amount columns the report's own arithmetic confirms: the row's printed percentage matches its year-to-date / budget (confirming both, to within the percentage's rounding), or its column adds up in a department or fund subtotal (confirming it exactly). Amounts not listed may be misread; `monthly_series.csv` has them reconciled. |
| `ledger_id_as_read`, `description_as_read` | The id and description as OCR read them. |

Each line's ledger id is put together from its fund and department, which
come from the section it is printed in (decided by vote between the
section's heading, its subtotal and its lines' ids, since any of them may be
misread), and its account number, which is the number its description is
most often printed with across all the reports. Its `description` is the
spelling most often printed with that id.

### `processed/monthly_report_checks.csv`

| Column | Description |
| --- | --- |
| `doc_id`, `period`, `page` | Where the checked figure is printed. |
| `check` | `line percent` (the printed percentage vs. year-to-date / budget), `department subtotal`, `fund subtotal` (the department subtotals, plus any lines whose department subtotal was not read), or `total` (vs. the fund subtotal). |
| `statement`, `fund_code`, `department_code`, `ledger_id` | The row checked. |
| `column` | The amount (or `%`, `prior_%`) column. |
| `printed`, `computed`, `difference` | The printed figure, what the other figures make it, and `computed - printed`. |
| `status` | `ok`, `FAIL`, or `unreadable` (a figure needed for the check could not be read). |

### `processed/monthly_report_summary.csv`

The figures on each monthly report's cover page ("Consolidated Revenues and
Expenditures"), in whole dollars.

| Column | Description |
| --- | --- |
| `doc_id`, `period`, `page` | The report and the month it covers. |
| `year` | The year the figure is for: the report's year, or the year before. |
| `measure` | `revenue` or `expenditure` (to date), `cash_beginning_balance` (at the start of the year) or `cash_balance` (at the end of the month). |
| `amount`, `total_budget` | The figure, and for revenue and expenditure the year's total budget. |
| `printed_percent`, `check` | The printed percentage of budget, and whether `amount / total_budget` matches it: `ok`, `FAIL`, or `source error` (a mistake on the cover itself, explained in `note`). |
| `note` | For a source error, the explanation from `corrections/monthly_report_source_errors.csv`. |

### `processed/monthly_series.csv`

The monthly reports brought together: one row per account, department
subtotal or fund subtotal per month, June 2020 – October 2026. Each month's
figures are printed in two reports: that month's (*reported*) and the same
month's a year later, in its prior-year columns (*restated*). Both are given,
since the borough's books sometimes change in between. OCR misreadings are
corrected (see `build_monthly_series.py` for the rules, and
`monthly_series_corrections.csv`).

| Column | Description |
| --- | --- |
| `statement`, `fund_code`, `fund`, `department_code`, `department` | As in `monthly_report_lines.csv`; names are each one's most common spelling. |
| `row_type` | `item` (a ledger account), `department_subtotal` or `fund_subtotal`. Sum only `item` rows. |
| `ledger_id`, `description` | The account (blank for subtotals). |
| `year`, `month` | The month the figures are for. |
| `reported_doc_id`, `reported_page` | The month's own report, and the page. Blank if it is not posted. |
| `budget`, `mtd`, `ytd` | The year's budget as of the report, the month's total, and the total for the year to date, as reported. Month-to-date totals are printed only from August 2023, so `mtd` starts then and `restated_mtd` in August 2022. |
| `budget_check`, `mtd_check`, `ytd_check` | What confirms each figure (see below). |
| `restated_doc_id`, `restated_page`, `restated_budget`, `restated_mtd`, `restated_ytd`, `restated_*_check` | The same, from the report a year later. Blank if it is not posted (yet). |

The `_check` columns list, separated by `;`:

| Value | Meaning |
| --- | --- |
| `sum` | The figure adds up with the others in its department's or fund's subtotal (exact). |
| `repeat` | The same figure is printed identically in another report (exact). |
| `difference` | A month-to-date total equals the difference between this month's and last month's year-to-date totals, both confirmed (exact). |
| `percent` | The line's printed percentage equals year-to-date / budget (to within its rounding to 0.01%). |
| `corrected` | The figure was misread and has been corrected (see `monthly_series_corrections.csv`). |

A figure with no check (0.5% of them, mostly month-to-date totals) may be
misread.

### `processed/monthly_series_corrections.csv`

| Column | Description |
| --- | --- |
| `doc_id`, `period`, `page` | Where the figure is printed. |
| `statement`, `fund_code`, `department_code`, `row_type`, `ledger_id` | The row. |
| `column` | Which figure, as in `monthly_report_lines.csv`. |
| `printed`, `corrected` | The figure as OCR read it (blank if unreadable) and the corrected figure. |
| `method` | `arithmetic` (the one figure that makes its department or fund add up) or `other report` (the same figure as printed, and confirmed, in another report). |
| `evidence` | What supports the correction. "One digit misread" alone is the weakest: the column adds up, and the figure differs from what OCR read by one digit, but nothing independent confirms it. |

### `processed/monthly_series_checks.csv`

Each cover page's consolidated revenue and expenditure for the year to date,
against the sum of all funds' year-to-date totals in the detail. The cover's
prior-year figures are compared with the same month's report a year before
(as first reported), from which the borough copies them.

| Column | Description |
| --- | --- |
| `doc_id`, `period` | The report whose cover it is. |
| `year`, `measure` | Which cover figure: `revenue` or `expenditure`, for the report's year or the year before. |
| `cover`, `detail` | The cover's figure and the sum of the funds' year-to-date totals, in whole dollars. |
| `detail_doc_id`, `funds` | The report the detail comes from, and how many funds it has. |
| `difference`, `status` | `detail - cover`; `ok` (within $1), `differs`, `source error` (the cover's figure is wrong, explained in `note`), `no detail` (that report is not posted) or `unreadable`. |
| `note` | For a source error, the explanation from `corrections/monthly_report_source_errors.csv`. |

### `corrections/monthly_report_source_errors.csv`

Mistakes in the monthly reports' cover pages, each checked by eye against
the scan. A listed mistake that no longer makes its check fail is reported
when the scripts run.

| Column | Description |
| --- | --- |
| `doc_id` | The report. |
| `check` | `cover percent` (the cover's percentage of budget disagrees with its own figures) or `cover vs detail` (the cover's total differs from the sum of the funds in the report). |
| `year`, `measure` | Which cover figure: the year, and `revenue` or `expenditure`. |
| `note` | What is printed, what it should be, and how that was checked. |

### `mappings/monthly_account_categories.csv`

One row per ledger account in the monthly reports.

| Column | Description |
| --- | --- |
| `ledger_id`, `statement`, `description` | The account, as in `monthly_series.csv`. |
| `category` | An overview category key (as in `proposed_budget_categories.csv`), or `payroll_benefits` (employee benefits, shared out by salaries), `ssw_overhead` (the Sewer & Solid Waste Fund's administration, split between `sewer` and `solid_waste` in the proportion of the adopted budget's "allocated expenses" lines that year), `interfund` (transfers between the borough's funds, left out) or `financing` (proceeds of borrowing, left out). |
| `payroll` | `yes` for salary and wage accounts, by which benefits are shared out. |
| `note` | Why, where the choice needed judgment. |

### `processed/monthly_summary.csv`

| Column | Description |
| --- | --- |
| `year`, `month` | The month. |
| `side` | `spending` or `revenue`, or `excluded_expense` / `excluded_revenue` for accounts left out. |
| `category` | The overview category. |
| `budget`, `ytd` | The year's budget as of the month's report, and the year-to-date total as reported that month. |
| `restated_ytd` | The year-to-date total as restated in the same month's report a year later (blank until that report is posted). |
| `estimated` | `yes` if the category includes a share of employee benefits or Sewer & Solid Waste overhead. |
| `accounts`, `unconfirmed` | How many ledger accounts the category combines, and how many of their year-to-date figures are unconfirmed (see `monthly_series.csv`). |
| `reported_doc_id`, `restated_doc_id` | The two reports. |

### `processed/monthly_summary_checks.csv`

Each year's budget by category, from the year's first monthly report (the
ledger), beside the adopted budget summary's figure for the same category
(from `budget_series.csv`, using the overview's definition of each
category).

| Column | Description |
| --- | --- |
| `year`, `side`, `category` | The year and category (`total` for the whole side). |
| `ledger_budget`, `adopted_budget`, `difference` | The two budgets and `ledger - adopted`. |
| `estimated` | `yes` if the ledger figure includes shared-out amounts. |
| `doc_id` | The monthly report the ledger budget is from. |
| `note` | Why the two differ, where they do by more than $1. |
