# Changelog

All notable changes to this project's data, method, and website are recorded
here, newest first. Each release is tagged in git and listed on the
[releases page](https://github.com/diego519/Swarthmore-budget/releases); the
version on the website's pages says which release you are looking at.

Version numbers follow [Semantic Versioning](https://semver.org), read for a
data project (see [Releases](README.md#releases) in the README):

- **Major** (2.0.0): a change that breaks reuse. A column or file in
  `data/processed/` is renamed, removed, or changes meaning, or links into
  the website stop working.
- **Minor** (1.1.0): new data or features. A newly posted budget or other
  document is added, a new page or chart appears, or a change of method
  revises published figures. Revised figures are listed.
- **Patch** (1.0.1): corrections. A misread or mismapped figure is fixed, or
  wording and display are corrected. Corrected figures are listed.

## [Unreleased]

## [1.2.0] - 2026-11-23

### Added

- **Actual vs. budget**, a new page of the website
  ([`docs/actuals.html`](docs/actuals.html)): what the borough actually spent
  and collected in each year (or so far this year) against its budget, by the
  overview's categories; any category month by month beside the year before;
  and the ledger accounts behind it, each figure linked to its page of the
  monthly report. The overview and the explorer link to it.
- **Actuals in the explorer.** Where the monthly reports' ledger accounts
  demonstrably cover the same things as a budget line (their budget equals the
  line's adopted budget that year), the explorer shows what was actually spent
  or collected, from the December report: 40 lines, 2021–2025
  ([`budget_line_actuals.csv`](data/processed/budget_line_actuals.csv)). Each
  figure links to the accounts behind it on the new page, and every line links
  to its category there.
- **Monthly financial reports, June 2021 – October 2026.** The 59 monthly
  reports that include the accounting system's budget-to-actual report are
  read from their scans: every ledger account of every fund, with this
  year's budget, month-to-date and year-to-date totals and the same for the
  year before.
  - [`monthly_series.csv`](data/processed/monthly_series.csv) brings the
    reports together into one series per account (297 accounts, plus
    department and fund subtotals), by month from June 2020, as each figure
    was first reported and as restated a year later. 1,032 OCR misreadings
    are corrected, each only where the reports' own arithmetic or another
    report's printing of the same figure shows it was misread (listed in
    [`monthly_series_corrections.csv`](data/processed/monthly_series_corrections.csv)),
    and 64 more on the worst-scanned pages were read off the page by eye and
    corrected by hand. 99.6% of the figures are confirmed, and each says how.
    Every month's totals agree with the report's cover to within $10, except
    where the cover itself is wrong.
  - [`monthly_report_lines.csv`](data/processed/monthly_report_lines.csv)
    has each report's lines as printed, with the checks of each report's own
    arithmetic.
  - The cover pages' consolidated totals and cash balances are in
    [`monthly_report_summary.csv`](data/processed/monthly_report_summary.csv).
    The totals match the funds' detail to the dollar in 190 cases
    ([`monthly_series_checks.csv`](data/processed/monthly_series_checks.csv)).
    Six cover totals that do not, and eight cover percentages that disagree
    with the cover's own figures, are mistakes in the borough's documents,
    explained in
    [`monthly_report_source_errors.csv`](data/corrections/monthly_report_source_errors.csv).

  - Every ledger account is assigned to one of the overview's categories
    ([`monthly_account_categories.csv`](data/mappings/monthly_account_categories.csv)),
    and [`monthly_summary.csv`](data/processed/monthly_summary.csv) totals
    each month's budget and actuals to date by category, so actual spending
    can be compared with the budget. Employee benefits and the Sewer & Solid
    Waste Fund's administration are shared out, as estimates. As a check,
    the ledger's total spending budget matches the adopted budget exactly in
    2021, 2022, 2024 and 2025, and its revenue categories match in 2021–2025
    except for $750 in 2023;
    [`monthly_summary_checks.csv`](data/processed/monthly_summary_checks.csv)
    explains each difference.

  No published figures change.

### Changed

- **Colors.** In the explorer, the borough's estimated actual is now drawn in
  green, so that orange can mean actual spending (from the monthly reports) on
  every page.

- **OCR of monthly reports.** `ocr_documents.py` has a second set of settings
  for the monthly reports, whose scans are mostly black-and-white fax-quality
  images: those pages are read at a higher resolution and smoothed, and pages
  scanned askew are straightened. The budgets' OCR is unchanged, byte for
  byte.

## [1.1.0] - 2026-11-22

### Added

- **Visitor analytics.** The website reports visits, and which of its
  controls, charts and tables people use, to Google Analytics (see
  [Analytics](README.md#analytics) in the README). A note at the foot of each
  page says so, and that no data is collected for commercial purposes. No
  figures change.

## [1.0.0] - 2026-11-22

First public release.

### Added

- **Document catalogue and downloader.** 118 documents from the borough's
  website are catalogued: adopted, draft and proposed budgets, audits, monthly
  financial reports, pension reports, and budget presentations. Each download
  is recorded with its SHA-256 checksum, so anyone can confirm they have the
  same files.
- **Adopted budgets, 2017–2026.** The budget summaries were read from the
  scanned PDFs with OCR and checked against their own arithmetic. Every
  printed subtotal and total reconciles with its rows, except six errors in
  the borough's own documents, which are documented. All 34 hand corrections
  to the OCR are recorded with the page they apply to.
- **Line items, 2023–2025.** The detailed line items of the three budgets
  that include them. These are only partly reconciled. Each row says whether
  its table's printed total has been checked.
- **Budget lines linked across years, 2016–2026.** 85 summary lines are
  followed from year to year, combining lines that were renamed. Each line has
  the adopted budget and estimated actual for each year, plus the source page
  of every figure. The 2016 figures come from the 2017 budget's prior-year
  columns.
- **The 2027 proposed budget.** The advertised budget of November 2026 is
  parsed line by line, and all of its fund subtotals reconcile. The 2027 budget
  is laid out by fund rather than by department. To compare it with earlier
  years, each line was assigned by hand to the earlier budgets' categories.
  Transfers between the borough's own funds, planned surpluses and the new
  Capital Fund are left out of that comparison. Centrally budgeted employee
  benefits are shared among departments by salary, so 2027 department figures
  are estimates. The totals are exact.
- **Inflation adjustment.** The Consumer Price Index for All Urban Consumers
  (CPI-U) comes from the Bureau of Labor Statistics. It is used to show any
  figure in the latest year's dollars.
- **Website** at <https://diego519.github.io/Swarthmore-budget/>:
  - **Overview:** total spending and revenue for each year from 2016 to the
    2027 proposal, broken down by department group or revenue source. A
    ranked chart shows what drove the change between any two years, with
    average annual growth rates.
  - **Explore a budget line:** any single line, from total spending down to
    police personnel. It shows the adopted budget and estimated actual for
    each year and the change from year to year. Every figure links to its
    page in the borough's PDF.
  - Both pages can show figures as budgeted or adjusted for inflation. Both
    work in light and dark mode, can be used with a keyboard, and offer a
    table view of every chart.

### Known limitations

- The 2023–2025 line items are only partly reconciled: 203 of 591 rows belong
  to tables whose printed totals match.
- 2027 department figures are estimates because of the benefits split. Crew
  wages for public works are budgeted on a single line in 2027 and counted
  under streets, which moves money between public works subcategories.
- In the inflation-adjusted view, the 2027 proposal is left in 2026 dollars,
  since 2027 inflation is not yet known.
- Audits, monthly financial reports and pension reports are downloaded but
  not yet parsed.

[Unreleased]: https://github.com/diego519/Swarthmore-budget/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/diego519/Swarthmore-budget/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/diego519/Swarthmore-budget/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/diego519/Swarthmore-budget/releases/tag/v1.0.0
