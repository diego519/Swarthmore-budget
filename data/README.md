# Data

All files here are produced by [`scripts/fetch_documents.py`](../scripts/fetch_documents.py),
except `sources.csv`, which is curated by hand.

| File | Edited by | Purpose |
| --- | --- | --- |
| `sources.csv` | hand | Catalogue of every known document and what it actually is. **Source of truth.** |
| `site_links.csv` | `discover` | Snapshot of the document links on the borough's finance pages, labels and all. |
| `downloads.csv` | `download` | Checksum, size, original filename and retrieval time of each downloaded file. |
| `raw/` | `download` | The documents themselves, as `raw/<category>/<doc_id>_<title>.<ext>`. Not committed to git. |

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
