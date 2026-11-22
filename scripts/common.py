"""Paths and helpers shared by the scripts in this directory."""

from __future__ import annotations

import csv
import hashlib
import statistics
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OCR_DIR = DATA_DIR / "ocr"
PROCESSED_DIR = DATA_DIR / "processed"
CORRECTIONS_DIR = DATA_DIR / "corrections"

SOURCES_CSV = DATA_DIR / "sources.csv"
SITE_LINKS_CSV = DATA_DIR / "site_links.csv"
DOWNLOADS_CSV = DATA_DIR / "downloads.csv"
OCR_MANIFEST_CSV = OCR_DIR / "manifest.csv"

# Words in the OCR files and from PDF text layers share one coordinate
# system: PDF points (1/72 inch) on the upright page, origin top-left.
POINTS_PER_INCH = 72


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sources_by_id() -> dict[str, dict[str, str]]:
    return {r["doc_id"]: r for r in read_csv(SOURCES_CSV)}


def downloaded_path(doc_id: str) -> Path:
    """Local path of a downloaded document (see fetch_documents.py)."""
    for r in read_csv(DOWNLOADS_CSV):
        if r["doc_id"] == doc_id:
            path = REPO_ROOT / r["path"]
            if not path.exists():
                raise FileNotFoundError(f"{rel(path)} is missing; run fetch_documents.py download")
            return path
    raise KeyError(f"document {doc_id} has not been downloaded; run fetch_documents.py download")


# --------------------------------------------------------------------------
# Words and lines
# --------------------------------------------------------------------------


@dataclass
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    conf: float = 100.0  # OCR confidence 0-100; 100 for text-layer words
    corrected: bool = False  # set by a hand correction (data/corrections/ocr_corrections.csv)

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Line:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)


def group_into_lines(words: list[Word]) -> list[Line]:
    """Group words into text lines by vertical position (for PDF text layers;
    OCR output already comes grouped into lines by Tesseract)."""
    if not words:
        return []
    height = statistics.median(w.bottom - w.top for w in words)
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.yc):
        if lines and abs(w.yc - statistics.mean(x.yc for x in lines[-1])) < 0.5 * height:
            lines[-1].append(w)
        else:
            lines.append([w])
    return merge_overlapping([Line(sorted(ws, key=lambda w: w.x0)) for ws in lines])


def merge_overlapping(lines: list[Line]) -> list[Line]:
    """Merge consecutive lines that overlap vertically by more than half the
    shorter line's height. In table rows, a label is sometimes vertically
    centred against a multi-line note and so sits a few points lower than the
    row's amounts; it still belongs on the same row. Separate rows don't overlap."""
    merged: list[Line] = []
    for line in lines:
        if merged:
            prev = merged[-1]
            overlap = min(prev.bottom, line.bottom) - max(prev.top, line.top)
            shorter = min(prev.bottom - prev.top, line.bottom - line.top)
            if shorter > 0 and overlap > 0.5 * shorter:
                merged[-1] = Line(sorted(prev.words + line.words, key=lambda w: w.x0))
                continue
        merged.append(line)
    return merged


def text_layer_lines(pdf_page) -> list[Line]:
    """Lines of text from a pdfplumber page's embedded text layer."""
    words = [
        Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"])
        for w in pdf_page.extract_words(x_tolerance=1.5, y_tolerance=2)
    ]
    return group_into_lines(words)


def ocr_lines(doc_id: str) -> dict[int, list[Line]]:
    """Lines of OCR'd text for each page of a document, from data/ocr/<doc_id>.csv,
    with the hand corrections in data/corrections/ocr_corrections.csv applied."""
    path = OCR_DIR / f"{doc_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{rel(path)} not found; run ocr_documents.py --doc-id {doc_id}")
    pages: dict[int, dict[int, list[Word]]] = {}
    for r in read_csv(path):
        word = Word(
            r["text"], float(r["x0"]), float(r["top"]), float(r["x1"]), float(r["bottom"]), float(r["conf"])
        )
        pages.setdefault(int(r["page"]), {}).setdefault(int(r["line"]), []).append(word)
    result = {
        page: merge_overlapping(
            sorted((Line(sorted(ws, key=lambda w: w.x0)) for ws in lines.values()), key=lambda ln: ln.top)
        )
        for page, lines in pages.items()
    }
    apply_ocr_corrections(doc_id, result)
    return result


OCR_CORRECTIONS_CSV = CORRECTIONS_DIR / "ocr_corrections.csv"


class CorrectionError(Exception):
    pass


def apply_ocr_corrections(doc_id: str, pages: dict[int, list[Line]]) -> None:
    """Apply hand corrections to OCR'd words.

    Each row of data/corrections/ocr_corrections.csv fixes one word that OCR
    misread, as checked by eye against the page image:

      doc_id, page   where the word is
      line_contains  text (as OCR'd) that picks out the word's line
      ocr_text       the word as OCR read it; empty to insert a missing word
      corrected_text what the page actually shows
      x              for an inserted word, or one OCR misplaced: its left
                     edge, in points
      note           why, and how it was verified

    A correction must match exactly one word (or, for an insertion, one
    line). If re-running OCR changes what it matches, the correction is
    reported as stale rather than silently applied to the wrong word.
    """
    for c in read_csv(OCR_CORRECTIONS_CSV):
        if c["doc_id"] != doc_id:
            continue
        lines = [ln for ln in pages.get(int(c["page"]), []) if c["line_contains"] in ln.text]
        where = f"doc {doc_id} p{c['page']} line containing {c['line_contains']!r}"
        if len(lines) != 1:
            raise CorrectionError(f"{where}: matched {len(lines)} lines, expected 1")
        line = lines[0]
        if not c["ocr_text"]:  # insert a word OCR missed
            x0 = float(c["x"])
            word = Word(c["corrected_text"], x0, line.top, x0 + 5 * len(c["corrected_text"]), line.bottom)
            word.corrected = True  # (conf defaults to 100: checked by eye)
            line.words = sorted([*line.words, word], key=lambda w: w.x0)
            continue
        words = [w for w in line.words if w.text == c["ocr_text"]]
        if len(words) != 1:
            raise CorrectionError(
                f"{where}: OCR text {c['ocr_text']!r} matched {len(words)} words, expected 1"
            )
        word = words[0]
        word.text = c["corrected_text"]
        word.corrected = True
        word.conf = 100.0  # checked by eye
        if c["x"]:  # OCR misplaced the word: move it, keeping its width
            word.x0, word.x1 = float(c["x"]), float(c["x"]) + (word.x1 - word.x0)
