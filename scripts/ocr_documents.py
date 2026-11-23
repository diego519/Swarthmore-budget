#!/usr/bin/env python3
"""OCR the scanned pages of catalogued documents.

Many of the borough's PDFs are scanned images with no text layer. For each
such page this script:

  1. renders the page at 300 DPI (but see "Profiles" below),
  2. detects whether it was scanned sideways or upside down (Tesseract's
     orientation detection) and rotates it upright,
  3. erases table ruling lines, which otherwise make Tesseract drop the text
     inside table cells,
  4. runs Tesseract OCR on the whole page, and
  5. re-reads malformed numbers. Tesseract often misreads the thin "1" in
     these documents' typeface as "]", "|" or a space ("2] 8,395" for
     218,395). Each run of number-like text that is not a well-formed number
     is cropped and OCR'd again with Tesseract restricted to the characters
     0-9 , . $ ( ) -, which fixes nearly all such errors. (Well-formed
     numbers are left alone: the restricted pass sometimes reads "$" as "5".)
     The first-pass reading is kept alongside.

Profiles. Most documents use the "standard" settings above. Monthly reports
use the "monthly" profile, which adds two steps:

  * From 2023 most of their pages are 1-bit (black and white) scans at 200
    DPI, on which Tesseract often reads "$1" as "$7" or "$71". Those pages
    are rendered at 400 DPI and smoothed with a slight Gaussian blur before
    OCR, which took the share of rows whose printed percentage agrees with
    their amounts from 65-72% to 81-95% in trials on three reports. Their
    grayscale pages (most 2021-2022 reports) are read at 300 DPI, unsmoothed,
    which did slightly better on them.
  * A page scanned a degree or more askew (July 2026's are 2-3 degrees) is
    straightened after being turned upright; otherwise Tesseract reads down
    the table's columns instead of along its rows. The angle is the one
    that makes the rows of ink most sharply horizontal.

The profile is recorded in the manifest.

Every recognised word is saved, with its position and confidence, to
data/ocr/<doc_id>.csv. Positions are in PDF points (1/72 inch) on the upright
page, the same units as words read from a PDF text layer, so the parsing
scripts can treat both alike. data/ocr/manifest.csv records which exact source
file (by SHA-256) and which Tesseract version produced each OCR file.

The OCR output is committed to the repository, so the parsing step does not
need Tesseract, and anyone can re-run OCR and diff the result against ours.
Pages that already have a text layer are skipped.

Requires Tesseract (https://tesseract-ocr.github.io/): `brew install
tesseract` on macOS, `apt install tesseract-ocr` on Debian/Ubuntu.

Usage:
    uv run scripts/ocr_documents.py --category budget_adopted
    uv run scripts/ocr_documents.py --doc-id 2408 --doc-id 2676 [--force]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

# Tesseract is deterministic for a given version and input when run
# single-threaded (set before pytesseract starts any Tesseract process).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import cv2
import numpy as np
import pdfplumber
import pytesseract
from common import (
    OCR_DIR,
    OCR_MANIFEST_CSV,
    POINTS_PER_INCH,
    downloaded_path,
    read_csv,
    rel,
    sha256_of,
    sources_by_id,
    write_csv,
)
from PIL import Image

DPI = 300
# The "monthly" profile (see the module docstring): 1-bit pages are rendered at
# this resolution and blurred with this standard deviation (in pixels) before
# OCR, and pages skewed by at least MIN_SKEW_DEGREES are straightened.
FAX_DPI = 400
FAX_BLUR_SIGMA_PX = 1.6
MIN_SKEW_DEGREES = 1.0
MAX_SKEW_DEGREES = 4.0
PROFILES = {"monthly_report": "monthly"}  # by category; anything else is "standard"
# "Single column of text of variable sizes": keeps each table row on one line
# without dropping bold or differently sized rows, as the uniform-block mode (6) does.
PAGE_CONFIG = "--psm 4"
NUMBER_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789,.$()-"  # one line, number characters only
# A page with at least this many characters in its text layer is not OCR'd.
MIN_TEXT_LAYER_CHARS = 20
# Characters that make up numbers, plus those the first pass confuses with
# digits or "$" ("]" and "l" for 1, "&" and "B" for 8, "S" for 5 or $, "O" for 0).
NUMBER_LIKE = re.compile(r"^[\d,.$()\-\]\[|!JIl§&SsBOo]+$")
# First-pass readings that are already well-formed and are kept as read:
# amounts ("$1,234", "(1,234)", "1,234.56"), account numbers ("400.020",
# and the monthly reports' ledger ids, "01-300-010"), years.
WELL_FORMED_NUMBER = re.compile(
    r"^\$?\(?\d{1,3}(,\d{3})*(\.\d{2})?\)?$|^\d{3}\.\d{3,4}$|^\d{2}-\d{3}-\d{3}$|^20[12]\d$"
)
EDGE_JUNK = "|!][ "
CROP_MARGIN_PX = 6

WORD_FIELDS = ["page", "rotation", "line", "x0", "top", "x1", "bottom", "conf", "text", "first_pass_text"]
MANIFEST_FIELDS = [
    "doc_id", "source_sha256", "pages_ocred", "tesseract_version", "dpi", "profile", "created_utc",
]  # fmt: skip


def min_rule_length_px(dpi: int) -> int:
    """Ruling lines are runs of dark pixels at least this long (0.2 inch); text strokes are shorter."""
    return dpi // 5


def number_gap_px(dpi: int) -> int:
    """Pieces of one number are closer together than this (about 4 points)."""
    return dpi // 18


def detect_rotation(image: Image.Image) -> int:
    """Degrees clockwise the page must be rotated to be upright (0/90/180/270)."""
    try:
        osd = pytesseract.image_to_osd(image, config="--psm 0")
    except pytesseract.TesseractError:
        return 0  # too little text to tell (e.g. a blank page)
    return int(osd.split("Rotate:")[1].split()[0])


def erase_rules(gray: np.ndarray, dpi: int) -> np.ndarray:
    """Return a black-on-white binary image with long horizontal and vertical
    lines (table borders, underlines) removed."""
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    length = min_rule_length_px(dpi)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    rules = cv2.dilate(horizontal | vertical, np.ones((3, 3), np.uint8))
    ink[rules > 0] = 0
    return 255 - ink


def first_pass(image: Image.Image) -> list[dict]:
    """OCR the whole page. Returns words in pixel coordinates."""
    data = pytesseract.image_to_data(image, config=PAGE_CONFIG, output_type=pytesseract.Output.DICT)
    line_ids: dict[tuple[int, int, int], int] = {}
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = data["left"][i], data["top"][i]
        words.append(
            {
                "line": line_ids.setdefault(key, len(line_ids) + 1),
                "x0": left,
                "top": top,
                "x1": left + data["width"][i],
                "bottom": top + data["height"][i],
                "conf": float(data["conf"][i]),
                "text": text,
                "first_pass_text": "",
            }
        )
    return words


def number_runs(words: list[dict], dpi: int) -> list[list[dict]]:
    """Runs of adjacent number-like words on the same line, e.g. ["2]", "8,395"]."""
    gap = number_gap_px(dpi)
    runs: list[list[dict]] = []
    by_line: dict[int, list[dict]] = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    for line_words in by_line.values():
        current: list[dict] = []
        for w in sorted(line_words, key=lambda w: w["x0"]):
            joins = current and w["x0"] - current[-1]["x1"] < gap
            if NUMBER_LIKE.match(w["text"]) and w["text"] not in ("$", "§"):
                if not joins and current:
                    runs.append(current)
                    current = []
                current.append(w)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
    # Re-read only runs that look like numbers (at least three digits) but are malformed.
    return [
        r
        for r in runs
        if sum(c.isdigit() for c in "".join(w["text"] for w in r)) >= 3
        and not WELL_FORMED_NUMBER.match(" ".join(w["text"] for w in r).strip(EDGE_JUNK))
    ]


def second_pass(image: Image.Image, words: list[dict], dpi: int) -> list[dict]:
    """Re-read each number with Tesseract restricted to number characters,
    replacing the run of first-pass words with a single word."""
    replaced: set[int] = set()
    refined = []
    for run in number_runs(words, dpi):
        box = (
            max(0, min(w["x0"] for w in run) - CROP_MARGIN_PX),
            max(0, min(w["top"] for w in run) - CROP_MARGIN_PX),
            max(w["x1"] for w in run) + CROP_MARGIN_PX,
            max(w["bottom"] for w in run) + CROP_MARGIN_PX,
        )
        data = pytesseract.image_to_data(
            image.crop(box), config=NUMBER_CONFIG, output_type=pytesseract.Output.DICT
        )
        found = [(t.strip(), float(c)) for t, c in zip(data["text"], data["conf"], strict=True) if t.strip()]
        if not found:
            continue  # keep the first-pass reading
        replaced.update(id(w) for w in run)
        refined.append(
            {
                "line": run[0]["line"],
                "x0": min(w["x0"] for w in run),
                "top": min(w["top"] for w in run),
                "x1": max(w["x1"] for w in run),
                "bottom": max(w["bottom"] for w in run),
                "conf": min(c for _, c in found),
                "text": "".join(t for t, _ in found),
                "first_pass_text": " ".join(w["text"] for w in run),
            }
        )
    kept = [w for w in words if id(w) not in replaced]
    return sorted(kept + refined, key=lambda w: (w["line"], w["x0"]))


def skew_degrees(gray: np.ndarray) -> float:
    """How far a page's text lines are tilted, in degrees counter-clockwise,
    to the nearest 0.1 degree: the rotation (within MAX_SKEW_DEGREES) under
    which the page's rows of ink are most sharply separated, i.e. the
    row-by-row ink totals vary the most. Measured on a quarter-size copy."""
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    h, w = ink.shape
    best_score, best_angle = -1.0, 0.0
    for tenths in range(-round(MAX_SKEW_DEGREES * 10), round(MAX_SKEW_DEGREES * 10) + 1):
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), tenths / 10, 1)
        rows = cv2.warpAffine(ink, matrix, (w, h), flags=cv2.INTER_NEAREST).sum(axis=1, dtype=np.float64)
        score = float(np.var(rows))
        if score > best_score:
            best_score, best_angle = score, tenths / 10
    return best_angle


def straighten(image: Image.Image) -> Image.Image:
    """Rotate a page so its text lines are horizontal, if it is noticeably askew."""
    gray = np.array(image)
    angle = skew_degrees(gray)
    if abs(angle) < MIN_SKEW_DEGREES:
        return image
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
    return Image.fromarray(cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderValue=255))


def is_bilevel(pdf_page) -> bool:
    """Whether a scanned page is a 1-bit (black and white) image."""
    return bool(pdf_page.images) and all(im.get("bits") == 1 for im in pdf_page.images)


def ocr_page(pdf_path: Path, page_number: int, profile: str) -> tuple[list[dict], int]:
    """OCR one page. Returns its words and the DPI it was read at."""
    with pdfplumber.open(pdf_path) as pdf:
        pdf_page = pdf.pages[page_number - 1]
        fax = profile == "monthly" and is_bilevel(pdf_page)
        dpi = FAX_DPI if fax else DPI
        image = pdf_page.to_image(resolution=dpi).original.convert("L")
    if fax:
        image = Image.fromarray(cv2.GaussianBlur(np.array(image), (0, 0), FAX_BLUR_SIGMA_PX))
    rotation = detect_rotation(image)
    if rotation:
        image = image.rotate(-rotation, expand=True)  # PIL rotates counter-clockwise
    if profile == "monthly":
        image = straighten(image)
    cleaned = Image.fromarray(erase_rules(np.array(image), dpi))
    words = second_pass(cleaned, first_pass(cleaned), dpi)

    scale = POINTS_PER_INCH / dpi
    for w in words:
        for k in ("x0", "top", "x1", "bottom"):
            w[k] = round(w[k] * scale, 1)
        w["conf"] = round(w["conf"], 1)
        w["page"] = page_number
        w["rotation"] = rotation
    return words, dpi


def ocr_document(doc_id: str, profile: str, workers: int) -> tuple[list[dict], list[int], list[int]]:
    """OCR every page without a text layer. Returns the words, the pages
    OCR'd, and the DPIs they were read at."""
    path = downloaded_path(doc_id)
    with pdfplumber.open(path) as pdf:
        pages = [n for n, page in enumerate(pdf.pages, 1) if len(page.chars) < MIN_TEXT_LAYER_CHARS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(ocr_page, [path] * len(pages), pages, [profile] * len(pages)))
    for number, (page_words, dpi) in zip(pages, results, strict=True):
        rotation = page_words[0]["rotation"] if page_words else 0
        print(f"  page {number}: {dpi} DPI, rotated {rotation}°, {len(page_words)} words")
    words = [w for page_words, _ in results for w in page_words]
    return words, pages, sorted({dpi for _, dpi in results})


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--category", action="append", help="OCR documents in this category (repeatable)")
    parser.add_argument("--doc-id", action="append", help="OCR this document (repeatable)")
    parser.add_argument("--force", action="store_true", help="re-run OCR even if the output is current")
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="pages to OCR in parallel")
    args = parser.parse_args()
    if not (args.category or args.doc_id):
        parser.error("give --category and/or --doc-id")

    sources = [
        r
        for r in sources_by_id().values()
        if r["include"] == "yes"
        and (
            (args.category and r["category"] in args.category) or (args.doc_id and r["doc_id"] in args.doc_id)
        )
    ]
    version = str(pytesseract.get_tesseract_version())
    manifest = {r["doc_id"]: {"profile": "standard"} | r for r in read_csv(OCR_MANIFEST_CSV)}

    for row in sources:
        doc_id = row["doc_id"]
        source_sha = sha256_of(downloaded_path(doc_id))
        profile = PROFILES.get(row["category"], "standard")
        prev = manifest.get(doc_id)
        if (
            not args.force
            and prev
            and prev["source_sha256"] == source_sha
            and prev["tesseract_version"] == version
            and prev["profile"] == profile
            and (OCR_DIR / f"{doc_id}.csv").exists()
        ):
            print(f"{doc_id} {row['title']}: up to date")
            continue

        print(f"{doc_id} {row['title']}")
        words, pages, dpis = ocr_document(doc_id, profile, args.workers)
        if not pages:
            print("  every page has a text layer; nothing to OCR")
            continue
        out = OCR_DIR / f"{doc_id}.csv"
        write_csv(out, WORD_FIELDS, words)
        manifest[doc_id] = {
            "doc_id": doc_id,
            "source_sha256": source_sha,
            "pages_ocred": " ".join(map(str, pages)),
            "tesseract_version": version,
            "dpi": " ".join(map(str, dpis)),
            "profile": profile,
            "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        write_csv(
            OCR_MANIFEST_CSV, MANIFEST_FIELDS, sorted(manifest.values(), key=lambda r: int(r["doc_id"]))
        )
        print(f"  wrote {rel(out)} ({len(words)} words from {len(pages)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
