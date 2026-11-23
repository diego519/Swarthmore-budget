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

### Added

- **Visitor analytics.** The website reports visits, and which of its
  controls, charts and tables people use, to Google Analytics (see
  [Analytics](README.md#analytics) in the README).

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

[Unreleased]: https://github.com/diego519/Swarthmore-budget/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/diego519/Swarthmore-budget/releases/tag/v1.0.0
