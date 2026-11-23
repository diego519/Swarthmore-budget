#!/usr/bin/env python3
"""Reconcile the monthly reports with each other into one series per account.

parse_monthly_reports.py reads each report on its own, and checks each figure
against the report's own arithmetic. This script brings the reports together.

Every figure is printed twice. A month's budget, month-to-date and
year-to-date totals are printed in that month's report ("reported"), and
again in the prior-year columns of the same month's report a year later
("restated"); budgets are printed in every report of the year. The two
printings usually agree, but not always, and not only because of OCR: in
about 3% of year-to-date figures and 10% of month-to-date figures that both
reports confirm, the borough's books changed in between (late postings to a
past month). So the two are kept apart, and another report's figure is used
to correct a reading only with proof that the reading is an OCR error.

Each figure as printed in each report (a "reading") is settled in rounds:

1. Correct by arithmetic. Where a column of a department or fund does not
   add up to its printed subtotal, the misread figure is looked for among the
   readings not already confirmed (by sum or repeat, below). Changed to the
   value that makes the column add up, a reading qualifies if the line's
   printed percentage does not contradict the new value and it has one of:
     - the same figure printed with that value in another report;
     - the line's printed percentage agreeing with the new value but not
       with the reading, the change being to at most two digits, none of
       them finer than the percentage can tell apart (the arithmetic may
       have absorbed a second misread there);
     - weakest: a change to a single digit.
   A month-to-date or year-to-date reading is not changed to a value that
   contradicts a confirmed printing of the same figure in another report.
   If exactly one reading qualifies, or exactly one has support of the first
   two kinds, it is corrected. A correction of the weakest kind confirms
   nothing else: a sum that adds up only because of it does not count in
   round 2.

2. Confirm. A reading is confirmed by any of:
     sum         its column adds up to the printed subtotal (exact);
     repeat      the same figure is printed identically in another report
                 (two independent scans read alike; exact);
     difference  a month-to-date total equals the difference between this
                 month's and last month's confirmed year-to-date totals
                 (exact);
     percent     the line's printed percentage equals year-to-date / budget
                 (to within the percentage's rounding).

3. Correct from another report. A reading still unconfirmed takes the
   value of the same figure in another report if that one is confirmed by
   sum or repeat and differs from the reading by at most two digits, and
   either the line's printed percentage agrees with it but not with the
   reading (budgets and year-to-date totals) or the month's year-to-date
   difference equals it (month-to-date totals).

Rounds 1-3 repeat until nothing changes.

Finally, each report's cover page is checked against the detail. The
cover's consolidated revenue and expenditure for the year to date are the
sums of every fund's year-to-date total, rounded to the dollar; the
prior-year figures on the cover are those of the same month's report a year
before (as first reported, not as restated).

Outputs (in data/processed/):
    monthly_series.csv              one row per account (and per department and
                                    fund subtotal) per month: reported and
                                    restated budget, month-to-date and
                                    year-to-date, with how each is confirmed
    monthly_series_corrections.csv  every reading corrected, with the evidence
    monthly_series_checks.csv       each cover-page total against the sum of the
                                    funds' year-to-date totals

Usage:
    uv run scripts/build_monthly_series.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from common import CORRECTIONS_DIR, PROCESSED_DIR, read_csv, rel, write_csv

LINES_CSV = PROCESSED_DIR / "monthly_report_lines.csv"
SUMMARY_CSV = PROCESSED_DIR / "monthly_report_summary.csv"
SERIES_CSV = PROCESSED_DIR / "monthly_series.csv"
CORRECTIONS_CSV = PROCESSED_DIR / "monthly_series_corrections.csv"
CHECKS_CSV = PROCESSED_DIR / "monthly_series_checks.csv"
SOURCE_ERRORS_CSV = CORRECTIONS_DIR / "monthly_report_source_errors.csv"

COLUMNS = ["budget", "mtd", "ytd", "prior_year_budget", "prior_year_mtd", "prior_year_ytd"]
# Each year's budget, year-to-date and printed percentage of budget.
YEARS = [("budget", "ytd", "percent"), ("prior_year_budget", "prior_year_ytd", "prior_year_percent")]
# A plausible misreading differs from the printed figure by at most this many
# digits (inserted, dropped or changed). Most OCR slips here change one digit.
MAX_DIGIT_EDITS = 2

KEY_FIELDS = ["statement", "fund_code", "fund", "department_code", "department", "row_type", "ledger_id",
              "description"]  # fmt: skip
MEASURES = ["budget", "mtd", "ytd"]
SERIES_FIELDS = [
    *KEY_FIELDS, "year", "month",
    "reported_doc_id", "reported_page", *MEASURES, *(f"{m}_check" for m in MEASURES),
    "restated_doc_id", "restated_page", *(f"restated_{m}" for m in MEASURES),
    *(f"restated_{m}_check" for m in MEASURES),
]  # fmt: skip
CHECK_FIELDS = [
    "doc_id", "period", "year", "measure", "cover", "detail", "detail_doc_id", "funds", "difference", "status",
    "note",
]  # fmt: skip
CORRECTION_FIELDS = [
    "doc_id", "period", "page", "statement", "fund_code", "department_code", "row_type", "ledger_id",
    "column", "printed", "corrected", "method", "evidence",
]  # fmt: skip


@dataclass
class Reading:
    """One figure as printed in one report."""

    row: dict
    column: str
    printed: int | None  # cents, as parsed from the OCR
    value: int | None = None  # cents, after any correction
    checks: set[str] = field(default_factory=set)
    corrected: str = ""  # method, if corrected
    weak: bool = False  # corrected on arithmetic and a one-digit slip alone, with no independent support

    @property
    def doc(self) -> str:
        return self.row["doc_id"]

    @property
    def prior(self) -> bool:
        return self.column.startswith("prior_year_")

    @property
    def measure(self) -> str:
        return self.column.removeprefix("prior_year_")

    @property
    def year(self) -> int:
        return int(self.row["period"][:4]) - (1 if self.prior else 0)

    @property
    def month(self) -> int:
        return int(self.row["period"][5:])


def cents(text: str) -> int | None:
    return int(Decimal(text) * 100) if text else None


def fmt(c: int | None) -> str:
    return "" if c is None else f"{Decimal(c) / 100:.2f}"


def row_key(r: dict) -> tuple:
    return (r["row_type"], r["statement"], r["fund_code"], r["department_code"], r["ledger_id"])


def digit_edits(a: int, b: int) -> int:
    """Edit distance between two figures' digits as printed (sign included):
    "9.00" and "0.00" (900 and 0 cents) differ by one digit."""
    s, t = (("-" if v < 0 else "") + f"{abs(v):03d}" for v in (a, b))
    prev = list(range(len(t) + 1))
    for i, cs in enumerate(s, 1):
        cur = [i]
        for j, ct in enumerate(t, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cs != ct)))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------------
# The reports' own arithmetic
# --------------------------------------------------------------------------


@dataclass
class Sum:
    """A printed subtotal or total and the readings it should equal the sum of."""

    total: Reading
    parts: list[Reading]
    check: str

    def difference(self) -> int | None:
        values = [p.value for p in self.parts]
        if self.total.value is None or any(v is None for v in values):
            return None
        return sum(values) - self.total.value


def build_sums(rows: list[dict], readings: dict[tuple[int, str], Reading]) -> list[Sum]:
    """The subtotal and total checks of one report, as parse_monthly_reports.py makes them."""
    by_kind: dict[str, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(rows):
        by_kind[r["row_type"]][(r["statement"], r["fund_code"], r["department_code"])].append(i)
    dept_subtotals = by_kind["department_subtotal"]
    sums = []
    for col in COLUMNS:
        if not any((i, col) in readings for i in range(len(rows))):
            continue

        def get(i: int, col: str = col) -> Reading | None:
            return readings.get((i, col))

        for key, [i] in ((k, v) for k, v in dept_subtotals.items() if len(v) == 1):
            parts = [get(j) for j in by_kind["item"].get(key, [])]
            if get(i) and parts and all(parts):
                sums.append(Sum(get(i), parts, "department subtotal"))
        for (statement, fund, _), [i] in ((k, v) for k, v in by_kind["fund_subtotal"].items() if len(v) == 1):
            idx = [j for k, js in dept_subtotals.items() if k[:2] == (statement, fund) for j in js]
            idx += [
                j
                for k, js in by_kind["item"].items()
                if k[:2] == (statement, fund) and k not in dept_subtotals
                for j in js
            ]
            parts = [get(j) for j in idx]
            if get(i) and parts and all(parts):
                sums.append(Sum(get(i), parts, "fund subtotal"))
            for t in by_kind["total"].get((statement, fund, ""), []):
                if get(t):
                    sums.append(Sum(get(t), [get(i)], "total"))
    return sums


def percent_agrees(row: dict, readings: dict[str, Reading], column: str, value: int | None) -> bool | None:
    """Whether the row's printed percentage of budget agrees with its budget
    and year-to-date, taking `value` for `column`. None if it says nothing."""
    for budget_col, ytd_col, pct_col in YEARS:
        if column not in (budget_col, ytd_col):
            continue
        pct = cents(row[pct_col])  # hundredths of a percent
        b = (
            value
            if column == budget_col
            else (readings[budget_col].value if budget_col in readings else None)
        )
        y = value if column == ytd_col else (readings[ytd_col].value if ytd_col in readings else None)
        if pct is None or b is None or y is None or b == 0:
            return None  # (with no budget the system prints 0.00% whatever the year-to-date)
        if column == budget_col and y == 0:
            return None  # 0.00% of any budget
        return abs(y / b * 10000 - pct) <= 1
    return None


def percent_shows_change(
    row: dict, readings: dict[str, Reading], column: str, printed: int, x: int, deduced: bool
) -> bool:
    """Whether the printed percentage can vouch for changing `printed` to `x`:
    the percentage (rounded to 0.01%) agrees with x and not with the printed
    figure. If x was deduced by arithmetic (rather than printed elsewhere),
    the change must also leave alone every digit finer than the percentage
    can tell apart, since the arithmetic may have absorbed a second misread
    there."""
    if not percent_agrees(row, readings, column, x) or percent_agrees(row, readings, column, printed) is True:
        return False
    if not deduced:
        return True
    for budget_col, ytd_col, pct_col in YEARS:
        if column in (budget_col, ytd_col):
            pct = abs(cents(row[pct_col]) or 1)
            budget = abs(x if column == budget_col else readings[budget_col].value)
            # How far the figure can move before the percentage changes, in cents.
            spread = budget / 10000 if column == ytd_col else budget / pct
            unit = 1
            while unit < spread:
                unit *= 10
            return abs(x) % unit == abs(printed) % unit
    return False


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


class Reconciler:
    def __init__(self, rows: list[dict]):
        self.docs: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            self.docs[r["doc_id"]].append(r)
        self.readings: dict[str, dict[tuple[int, str], Reading]] = {}
        self.by_row: dict[int, dict[str, Reading]] = defaultdict(dict)  # id(row) -> column -> reading
        self.same_figure: dict[tuple, list[Reading]] = defaultdict(list)
        self.same_budget: dict[tuple, list[Reading]] = defaultdict(list)
        for doc, doc_rows in self.docs.items():
            self.readings[doc] = {}
            # Reports up to July 2023 have no month-to-date columns.
            columns = [c for c in COLUMNS if not c.endswith("mtd") or any(x[c] for x in doc_rows)]
            for i, r in enumerate(doc_rows):
                for col in columns:
                    rd = Reading(r, col, cents(r[col]))
                    rd.value = rd.printed
                    self.readings[doc][(i, col)] = rd
                    self.by_row[id(r)][col] = rd
                    self.same_figure[self.figure(rd)].append(rd)
                    if rd.measure == "budget":
                        self.same_budget[(row_key(r), rd.year)].append(rd)
        self.sums = {doc: build_sums(self.docs[doc], self.readings[doc]) for doc in self.docs}
        self.corrections: list[dict] = []

    @staticmethod
    def figure(rd: Reading) -> tuple:
        return (row_key(rd.row), rd.year, rd.month, rd.measure)

    def others(self, rd: Reading) -> list[Reading]:
        """Readings of the same figure in other reports. A budget is the same
        figure in every report of its year."""
        pool = (
            self.same_budget[(row_key(rd.row), rd.year)]
            if rd.measure == "budget"
            else self.same_figure[self.figure(rd)]
        )
        return [o for o in pool if o.doc != rd.doc]

    def percent(self, rd: Reading, value: int | None) -> bool | None:
        return percent_agrees(rd.row, self.by_row[id(rd.row)], rd.column, value)

    def ytd_difference(self, rd: Reading) -> int | None:
        """This month's year-to-date minus last month's, both confirmed, from the
        same vintage (reported or restated), for a month-to-date reading."""
        ytd = self.by_row[id(rd.row)].get(rd.column.replace("mtd", "ytd"))
        if ytd is None or ytd.value is None or not ytd.checks & {"sum", "repeat"}:
            return None
        if rd.month == 1:
            return ytd.value
        earlier = [
            o
            for o in self.same_figure[(row_key(rd.row), rd.year, rd.month - 1, "ytd")]
            if o.prior == rd.prior and o.value is not None and o.checks & {"sum", "repeat"}
        ]
        return ytd.value - earlier[0].value if len(earlier) == 1 else None

    def correct(self, rd: Reading, value: int, method: str, evidence: str) -> None:
        self.corrections.append(
            {**{k: rd.row[k] for k in ("doc_id", "period", "page", "statement", "fund_code", "department_code",
                                       "row_type", "ledger_id")},
             "column": rd.column, "printed": fmt(rd.printed), "corrected": fmt(value), "method": method,
             "evidence": evidence}
        )  # fmt: skip
        rd.value, rd.corrected = value, method

    # Round 1 ------------------------------------------------------------

    def correct_by_arithmetic(self) -> int:
        changed = 0
        for sums in self.sums.values():
            for s in sums:
                diff = s.difference()
                cells = [*s.parts, s.total]
                if diff == 0:
                    continue
                unread = [c for c in cells if c.value is None]
                if diff is None and len(unread) != 1:
                    continue
                candidates = []  # (reading, value, supporting evidence)
                for c in unread or cells:
                    if c.corrected or c.checks & {"sum", "repeat"}:
                        continue  # confirmed elsewhere, so not the misreading
                    if c.value is None:  # the one unreadable figure: what makes the column add up
                        known = sum(p.value for p in s.parts if p is not c)
                        x = s.total.value - known if c is not s.total else known
                    else:
                        x = c.value - diff if c is not s.total else c.value + diff
                    pct = self.percent(c, x)
                    if pct is False:
                        continue
                    edits = digit_edits(c.printed, x) if c.printed is not None else None
                    others = self.others(c)
                    support = []
                    if any(o.printed == x for o in others):
                        support.append("same figure printed in another report")
                    else:
                        if c.measure != "budget" and any(
                            o.checks & {"sum", "repeat"} and o.value != x for o in others
                        ):
                            continue  # another report confirms a different figure
                        if c.printed is None and pct:
                            support.append("the line's printed percentage agrees")
                        elif (
                            c.printed is not None
                            and edits <= MAX_DIGIT_EDITS
                            and percent_shows_change(
                                c.row, self.by_row[id(c.row)], c.column, c.printed, x, deduced=True
                            )
                        ):
                            support.append(
                                "the line's printed percentage agrees, as it did not with the reading"
                            )
                    if support or edits == 1:
                        candidates.append((c, x, support))
                if len(candidates) > 1 and sum(bool(sup) for _, _, sup in candidates) == 1:
                    candidates = [cand for cand in candidates if cand[2]]  # the one with independent support
                if len(candidates) != 1:
                    continue
                c, x, support = candidates[0]
                evidence = "; ".join([f"{s.check} adds up", *support] if support else
                                     [f"{s.check} adds up", "one digit misread"])  # fmt: skip
                self.correct(c, x, "arithmetic", evidence)
                c.weak = not support
                changed += 1
        return changed

    # Round 2 ------------------------------------------------------------

    def confirm(self) -> None:
        for doc_readings in self.readings.values():
            for rd in doc_readings.values():
                rd.checks = set()
        for sums in self.sums.values():
            for s in sums:
                # A sum that adds up only thanks to a weak correction confirms nothing else.
                if s.difference() == 0 and not any(c.weak for c in [*s.parts, s.total]):
                    for c in [*s.parts, s.total]:
                        c.checks.add("sum")
        for doc_readings in self.readings.values():
            for rd in doc_readings.values():
                if rd.value is None:
                    continue
                if any(o.printed == rd.value for o in self.others(rd)):
                    rd.checks.add("repeat")
                if self.percent(rd, rd.value):
                    rd.checks.add("percent")
        for doc_readings in self.readings.values():  # after sum and repeat, which it depends on
            for rd in doc_readings.values():
                if rd.measure == "mtd" and rd.value is not None and self.ytd_difference(rd) == rd.value:
                    rd.checks.add("difference")

    # Round 3 ------------------------------------------------------------

    def correct_from_other_reports(self) -> int:
        changed = 0
        for doc_readings in self.readings.values():
            for rd in doc_readings.values():
                if rd.checks or rd.corrected:
                    continue
                options = {
                    o.printed
                    for o in self.others(rd)
                    if o.printed is not None
                    and o.printed == o.value
                    and o.checks & {"sum", "repeat"}
                    and (rd.printed is None or digit_edits(rd.printed, o.printed) <= MAX_DIGIT_EDITS)
                }
                agreed = []
                for x in options:
                    if rd.measure == "mtd":
                        if self.ytd_difference(rd) == x:
                            agreed.append((x, "the month's year-to-date difference agrees"))
                    elif (
                        rd.printed is None
                        and self.percent(rd, x)
                        or (
                            rd.printed is not None
                            and percent_shows_change(
                                rd.row, self.by_row[id(rd.row)], rd.column, rd.printed, x, deduced=False
                            )
                        )
                    ):
                        agreed.append(
                            (x, "the line's printed percentage agrees, as it did not with the reading")
                        )
                if len(agreed) == 1:
                    x, why = agreed[0]
                    self.correct(rd, x, "other report", f"same figure confirmed in another report; {why}")
                    changed += 1
        return changed

    def run(self) -> None:
        for _ in range(10):
            changed = self.correct_by_arithmetic()
            self.confirm()
            changed += self.correct_from_other_reports()
            self.confirm()
            if not changed:
                return


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def check_text(rd: Reading | None) -> str:
    if rd is None:
        return ""
    order = ["sum", "repeat", "difference", "percent"]
    return ";".join((["corrected"] if rd.corrected else []) + [c for c in order if c in rd.checks])


def build_series(rec: Reconciler) -> list[dict]:
    names: dict[tuple, Counter] = defaultdict(Counter)
    for doc_rows in rec.docs.values():
        for r in doc_rows:
            names[row_key(r)][(r["fund"], r["department"], r["description"])] += 1
    series: dict[tuple, dict] = {}
    for doc_rows in rec.docs.values():
        for r in doc_rows:
            if r["row_type"] == "total":
                continue  # repeats the fund subtotal
            for rd in rec.by_row[id(r)].values():
                key = (row_key(r), rd.year, rd.month)
                if key not in series:
                    fund, dept, desc = names[row_key(r)].most_common(1)[0][0]
                    series[key] = {
                        **{k: r[k] for k in KEY_FIELDS},
                        "fund": fund, "department": dept, "description": desc,
                        "year": rd.year, "month": rd.month,
                    }  # fmt: skip
                out = series[key]
                prefix = "restated_" if rd.prior else ""
                out[f"{prefix}doc_id"] = rd.doc
                out[f"{prefix}page"] = r["page"]
                out[f"{prefix}{rd.measure}"] = fmt(rd.value)
                out[f"{prefix}{rd.measure}_check"] = check_text(rd)
    rows = []
    for out in series.values():
        out["reported_doc_id"] = out.pop("doc_id", "")
        out["reported_page"] = out.pop("page", "")
        rows.append(out)
    order = {"item": 0, "department_subtotal": 1, "fund_subtotal": 2}
    rows.sort(key=lambda o: (o["statement"], o["fund_code"], o["department_code"], order[o["row_type"]],
                             o["ledger_id"], o["year"], o["month"]))  # fmt: skip
    return rows


def cover_checks(rec: Reconciler, cover: list[dict]) -> list[dict]:
    """Each cover-page revenue and expenditure figure against the sum of the
    funds' year-to-date totals in the report it comes from: this report for
    this year's, the same month's report a year before for last year's."""
    totals: dict[tuple[str, str], int] = defaultdict(int)  # (doc, statement) -> cents
    funds: dict[tuple[str, str], int] = defaultdict(int)
    unread: set[tuple[str, str]] = set()
    period_doc = {}
    for doc, doc_rows in rec.docs.items():
        period_doc[doc_rows[0]["period"]] = doc
        for r in doc_rows:
            rd = rec.by_row[id(r)].get("ytd")
            if r["row_type"] == "fund_subtotal" and rd is not None:
                funds[(doc, r["statement"])] += 1
                if rd.value is None:
                    unread.add((doc, r["statement"]))
                else:
                    totals[(doc, r["statement"])] += rd.value
    out = []
    for c in cover:
        if c["measure"] not in ("revenue", "expenditure"):
            continue
        statement = "revenue" if c["measure"] == "revenue" else "expense"
        period = f"{c['year']}-{c['period'][5:]}"
        doc = period_doc.get(period)
        key = (doc, statement)
        amount = int(c["amount"])
        if doc is None or key in unread or not funds[key]:
            detail, status = None, "no detail" if doc is None else "unreadable"
        else:
            detail = round(totals[key] / 100)
            status = "ok" if abs(detail - amount) <= 1 else "differs"
        out.append(
            {"doc_id": c["doc_id"], "period": c["period"], "year": c["year"], "measure": c["measure"],
             "cover": amount, "detail": "" if detail is None else detail, "detail_doc_id": doc or "",
             "funds": funds[key] if doc else "", "difference": "" if detail is None else detail - amount,
             "status": status, "note": ""}
        )  # fmt: skip
    # Differences that are the borough's own, checked by eye.
    known = {
        (r["doc_id"], r["year"], r["measure"]): r["note"]
        for r in read_csv(SOURCE_ERRORS_CSV)
        if r["check"] == "cover vs detail"
    }
    for c in out:
        key = (c["doc_id"], str(c["year"]), c["measure"])
        if c["status"] == "differs" and key in known:
            c["status"], c["note"] = "source error", known.pop(key)
    for key in sorted(known):
        print(
            f"warning: {rel(SOURCE_ERRORS_CSV)} lists {key}, but that cover does not differ", file=sys.stderr
        )
    return out


def main() -> int:
    rows = read_csv(LINES_CSV)
    if not rows:
        print(f"{rel(LINES_CSV)} not found; run parse_monthly_reports.py first", file=sys.stderr)
        return 1
    rec = Reconciler(rows)
    rec.confirm()
    before = Counter(
        bool(rd.checks) for d in rec.readings.values() for rd in d.values() if rd.value is not None
    )
    rec.run()
    after = Counter(
        bool(rd.checks) for d in rec.readings.values() for rd in d.values() if rd.value is not None
    )
    unread = sum(rd.value is None for d in rec.readings.values() for rd in d.values())

    series = build_series(rec)
    checks = cover_checks(rec, read_csv(SUMMARY_CSV))
    write_csv(SERIES_CSV, SERIES_FIELDS, series)
    write_csv(CORRECTIONS_CSV, CORRECTION_FIELDS, rec.corrections)
    write_csv(CHECKS_CSV, CHECK_FIELDS, checks)
    methods = Counter(c["method"] for c in rec.corrections)
    print(f"Wrote {rel(SERIES_CSV)} ({len(series)} rows), {rel(CORRECTIONS_CSV)} and {rel(CHECKS_CSV)}")
    print(f"Readings confirmed: {before[True]} of {sum(before.values())} before any correction;")
    print(
        f"  {after[True]} of {sum(after.values())} ({100 * after[True] / sum(after.values()):.1f}%) after reconciling"
    )
    print(f"Corrected: {dict(methods)}; unreadable: {unread}")
    print(f"Cover pages against the detail: {dict(Counter(c['status'] for c in checks))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
