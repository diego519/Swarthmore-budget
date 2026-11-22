#!/usr/bin/env python3
"""Discover, download, and verify Swarthmore Borough financial documents.

The borough publishes its budgets, audits, and monthly financial reports as
PDFs in the "Document Center" of https://www.swarthmorepa.org. Every document
has a stable numeric id and lives at /DocumentCenter/View/<id>.

This script has three subcommands:

  discover   Scrape the borough's finance pages and write every document link
             found to data/site_links.csv (a snapshot of what the website
             shows). Reports any link that is not yet in data/sources.csv so a
             human can review and catalogue it.

  download   Download every document listed in data/sources.csv (include=yes)
             into data/raw/, and record a SHA-256 checksum, size, and retrieval
             time for each file in data/downloads.csv.

  verify     Re-hash the files in data/raw/ and compare them with
             data/downloads.csv. Use this to confirm that your copy of the
             source documents is byte-for-byte identical to ours.

data/sources.csv is the hand-curated catalogue and the single source of truth
for what each document *is* (type, year, period). The link text on the
website is sometimes wrong, so it is recorded in site_links.csv for reference
but never used to label documents automatically.

Usage:
    uv run scripts/fetch_documents.py discover
    uv run scripts/fetch_documents.py download [--category monthly_report] [--force]
    uv run scripts/fetch_documents.py verify
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.swarthmorepa.org"

# Pages on the borough website that link to financial documents.
SOURCE_PAGES = [
    "/403/Taxes-Finance",  # adopted budgets, audits, pension reports
    "/407/Borough-Budget",  # current budget cycle: drafts, presentations
    "/2272/Financial-Reports",  # monthly financial reports
]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SOURCES_CSV = DATA_DIR / "sources.csv"
SITE_LINKS_CSV = DATA_DIR / "site_links.csv"
DOWNLOADS_CSV = DATA_DIR / "downloads.csv"

SITE_LINKS_FIELDS = ["doc_id", "source_page", "section_heading", "link_text"]
DOWNLOADS_FIELDS = [
    "doc_id",
    "path",
    "sha256",
    "bytes",
    "content_type",
    "original_filename",
    "retrieved_at_utc",
]

# The site's host returns 404 to user agents that don't follow the usual
# "Mozilla/5.0 (compatible; ...)" convention (e.g. the python-requests
# default), so we use that form while still identifying ourselves honestly.
USER_AGENT = "Mozilla/5.0 (compatible; swarthmore-budget/0.1; open-data research script)"
REQUEST_DELAY_SECONDS = 1.0  # be polite to the borough's web server
DOC_LINK_RE = re.compile(r"/DocumentCenter/View/(\d+)")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def doc_url(doc_id: str) -> str:
    return f"{BASE_URL}/DocumentCenter/View/{doc_id}"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def clean_text(text: str) -> str:
    return " ".join(text.split())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_stem(row: dict[str, str]) -> Path:
    """Where a catalogued document is stored, minus the file extension, e.g.
    data/raw/monthly_report/2081_monthly-financial-report-2022-05
    (the extension comes from the server: almost always .pdf)."""
    return RAW_DIR / row["category"] / f"{row['doc_id']}_{slugify(row['title'])}"


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def filename_from_headers(headers: requests.structures.CaseInsensitiveDict) -> str:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?(?:\"([^\"]+)\"|([^;]+))", disposition)
    return unquote(match.group(1) or match.group(2)).strip() if match else ""


# --------------------------------------------------------------------------
# discover
# --------------------------------------------------------------------------


def scrape_page(session: requests.Session, page: str) -> list[dict[str, str]]:
    resp = session.get(BASE_URL + page, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Only look at the page body; the site header/footer repeat on every page.
    content = soup.select_one("#moduleContent")
    if content is None:
        raise RuntimeError(f"{page}: page layout changed (no #moduleContent)")

    links: list[dict[str, str]] = []
    for a in content.find_all("a", href=True):
        match = DOC_LINK_RE.search(a["href"])
        if not match:
            continue
        heading = a.find_previous(["h1", "h2", "h3", "h4"])
        links.append(
            {
                "doc_id": match.group(1),
                "source_page": page,
                "section_heading": clean_text(heading.get_text(" ")) if heading else "",
                "link_text": clean_text(a.get_text(" ")),
            }
        )

    # The same document is sometimes linked more than once on a page: an icon
    # plus a text link, a link split across formatting tags, or -- worth
    # keeping -- two links with *different* labels. Drop exact repeats and
    # blank-text links when a labelled link to the same document exists.
    labelled = {r["doc_id"] for r in links if r["link_text"]}
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for r in links:
        if not r["link_text"] and r["doc_id"] in labelled:
            continue
        unique.setdefault((r["doc_id"], r["link_text"]), r)
    return list(unique.values())


def cmd_discover(args: argparse.Namespace) -> int:
    session = make_session()
    found: list[dict[str, str]] = []
    for page in SOURCE_PAGES:
        page_links = scrape_page(session, page)
        print(f"{page}: {len(page_links)} document links")
        found.extend(page_links)
        time.sleep(REQUEST_DELAY_SECONDS)

    found.sort(key=lambda r: (r["source_page"], int(r["doc_id"]), r["link_text"]))
    write_csv(SITE_LINKS_CSV, SITE_LINKS_FIELDS, found)
    print(f"Wrote {SITE_LINKS_CSV.relative_to(REPO_ROOT)}")

    catalogued = {r["doc_id"] for r in read_csv(SOURCES_CSV)}
    on_site = {r["doc_id"] for r in found}

    new: dict[str, dict[str, str]] = {}
    for r in found:
        if r["doc_id"] not in catalogued:
            new.setdefault(r["doc_id"], r)
    if new:
        print(f"\n{len(new)} document(s) not yet in {SOURCES_CSV.name} -- please review and add them:")
        for doc_id, r in sorted(new.items(), key=lambda kv: int(kv[0])):
            print(f"  {doc_id:>5}  {r['source_page']:<26} {r['link_text'] or r['section_heading']}")
            print(f"         {doc_url(doc_id)}")

    gone = sorted(catalogued - on_site, key=int)
    if gone:
        print(f"\n{len(gone)} catalogued document(s) no longer linked from the source pages:")
        print("  " + ", ".join(gone))
        print("  (They may still be downloadable; this is informational.)")

    if not new and not gone:
        print("\nCatalogue is in sync with the website.")
    return 1 if new and args.strict else 0


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------


def download_one(session: requests.Session, row: dict[str, str], stem: Path) -> dict[str, str]:
    """Stream a document to a temp file, validate it, then move it into place."""
    url = doc_url(row["doc_id"])
    stem.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("text/html"):
            # The site serves an HTML error page for missing documents.
            raise RuntimeError(f"{url} returned a web page, not a document")
        h = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(dir=stem.parent, delete=False, suffix=".part") as tmp:
            tmp_path = Path(tmp.name)
            for chunk in resp.iter_content(chunk_size=1 << 16):
                tmp.write(chunk)
                h.update(chunk)
                size += len(chunk)
        headers = resp.headers

    original_filename = filename_from_headers(headers)
    suffix = Path(original_filename).suffix.lower() or ".pdf"
    if suffix == ".pdf":
        with tmp_path.open("rb") as f:
            if f.read(5) != b"%PDF-":
                tmp_path.unlink()
                raise RuntimeError(f"{url} claims to be a PDF but is not one")

    dest = stem.with_name(stem.name + suffix)
    tmp_path.replace(dest)
    return {
        "doc_id": row["doc_id"],
        "path": rel(dest),
        "sha256": h.hexdigest(),
        "bytes": str(size),
        "content_type": content_type,
        "original_filename": original_filename,
        "retrieved_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save_records(records: dict[str, dict[str, str]]) -> None:
    write_csv(DOWNLOADS_CSV, DOWNLOADS_FIELDS, sorted(records.values(), key=lambda r: int(r["doc_id"])))


def cmd_download(args: argparse.Namespace) -> int:
    sources = [r for r in read_csv(SOURCES_CSV) if r["include"] == "yes"]
    filtered = bool(args.category or args.doc_id)
    if args.category:
        sources = [r for r in sources if r["category"] in args.category]
    if args.doc_id:
        sources = [r for r in sources if r["doc_id"] in args.doc_id]
    if not sources:
        print("Nothing to download (check --category / --doc-id filters).")
        return 1

    records = {r["doc_id"]: r for r in read_csv(DOWNLOADS_CSV)}

    # On a full run, forget documents that are no longer catalogued with
    # include=yes (e.g. ones later found to be duplicates).
    if not filtered:
        wanted = {r["doc_id"] for r in sources}
        for doc_id in sorted(set(records) - wanted, key=int):
            path = REPO_ROOT / records[doc_id]["path"]
            print(
                f"{'Would remove' if args.dry_run else 'Removing'} {doc_id}: no longer included ({rel(path)})"
            )
            if not args.dry_run:
                path.unlink(missing_ok=True)
                del records[doc_id]
        if not args.dry_run:
            save_records(records)

    session = make_session()
    downloaded = skipped = changed = failed = 0

    for i, row in enumerate(sources, 1):
        stem = local_stem(row)
        prev = records.get(row["doc_id"])
        prev_path = REPO_ROOT / prev["path"] if prev else None
        label = f"[{i}/{len(sources)}] {row['doc_id']:>5} {row['title']}"

        have_valid_copy = (
            prev_path is not None and prev_path.exists() and sha256_of(prev_path) == prev["sha256"]
        )
        if have_valid_copy and not args.force:
            new_path = stem.with_name(stem.name + prev_path.suffix)
            if new_path != prev_path:
                # Catalogue entry was re-titled or re-categorised: just move the file.
                if not args.dry_run:
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    prev_path.replace(new_path)
                    prev["path"] = rel(new_path)
                    save_records(records)
                verb = "would rename" if args.dry_run else "renamed"
                print(f"{label}  {verb} {rel(prev_path)} -> {rel(new_path)}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"{label}  -> would download to {rel(stem)}.*")
            continue

        try:
            record = download_one(session, row, stem)
        except (requests.RequestException, RuntimeError, OSError) as exc:  # keep going; report at end
            print(f"{label}  FAILED: {exc}", file=sys.stderr)
            failed += 1
            continue

        if prev_path and rel(prev_path) != record["path"]:
            prev_path.unlink(missing_ok=True)  # stale copy under an old name
        if prev and prev["sha256"] != record["sha256"]:
            print(f"{label}  WARNING: content changed since {prev['retrieved_at_utc']}")
            changed += 1

        records[row["doc_id"]] = record
        downloaded += 1
        print(f"{label}  ({int(record['bytes']) / 1e6:.1f} MB)")
        save_records(records)  # after every file, so an interrupted run loses nothing
        time.sleep(REQUEST_DELAY_SECONDS)

    print(
        f"\nDownloaded {downloaded}, already up to date {skipped}, "
        f"changed upstream {changed}, failed {failed}."
    )
    return 1 if failed else 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    records = read_csv(DOWNLOADS_CSV)
    if not records:
        print(f"No records in {DOWNLOADS_CSV.relative_to(REPO_ROOT)}.")
        return 1
    ok = missing = mismatched = 0
    for r in records:
        path = REPO_ROOT / r["path"]
        if not path.exists():
            print(f"MISSING   {r['path']}")
            missing += 1
        elif sha256_of(path) != r["sha256"]:
            print(f"MISMATCH  {r['path']}")
            mismatched += 1
        else:
            ok += 1
    print(f"\n{ok} OK, {missing} missing, {mismatched} mismatched (of {len(records)}).")
    return 0 if missing == mismatched == 0 else 1


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="scrape the website for document links")
    p.add_argument("--strict", action="store_true", help="exit non-zero if uncatalogued links are found")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("download", help="download catalogued documents")
    p.add_argument("--category", action="append", help="only this category (repeatable)")
    p.add_argument("--doc-id", action="append", help="only this document id (repeatable)")
    p.add_argument("--force", action="store_true", help="re-download even if the local copy is current")
    p.add_argument("--dry-run", action="store_true", help="show what would be downloaded")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("verify", help="check local files against recorded checksums")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
