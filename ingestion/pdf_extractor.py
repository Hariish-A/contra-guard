"""
ingestion/pdf_extractor.py
--------------------------
Converts a downloaded transcript PDF → clean plain text using PyMuPDF (fitz).

Pipeline:
  1. Open PDF with fitz
  2. Extract text page-by-page
  3. Remove common PDF noise (page numbers, headers/footers, repeated boilerplate)
  4. Normalise whitespace / line-breaks
  5. Return clean string + per-page list for debug

Also handles:
  - Rotated / scanned pages (basic OCR fallback note)
  - Multi-column layouts (fitz sort parameter)
"""

import re
import fitz                   # PyMuPDF
from pathlib import Path
from typing import List, Tuple, Optional
from loguru import logger


# ──────────────────────────────────────────────────────────────────
# Noise patterns to strip from extracted text
# ──────────────────────────────────────────────────────────────────
NOISE_PATTERNS = [
    re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),             # lone page numbers
    re.compile(r"Strictly\s+Confidential", re.IGNORECASE),
    re.compile(r"For\s+internal\s+use\s+only", re.IGNORECASE),
    re.compile(r"Motilal\s+Oswal\s+Financial\s+Services", re.IGNORECASE),
    re.compile(r"Edelweiss\s+Securities", re.IGNORECASE),
    re.compile(r"Safe\s+Harbour\s+Statement", re.IGNORECASE),
    # Repeated blank lines → single blank line
    re.compile(r"\n{3,}"),
]


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def extract_transcript(pdf_path: str | Path) -> str:
    """
    Main entry point.
    Returns a single clean string ready for downstream diarization.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info(f"[PDF] Extracting: {pdf_path.name}")

    pages_text, page_count = _extract_pages(pdf_path)
    full_text = "\n".join(pages_text)
    clean     = _clean_text(full_text)

    logger.info(
        f"[PDF] {pdf_path.name}: {page_count} pages → "
        f"{len(clean):,} chars after cleaning"
    )
    return clean


def extract_transcript_pages(pdf_path: str | Path) -> List[str]:
    """
    Same as extract_transcript but returns a per-page list (useful for debugging).
    """
    pdf_path = Path(pdf_path)
    pages_text, _ = _extract_pages(pdf_path)
    return [_clean_text(p) for p in pages_text]


def get_pdf_metadata(pdf_path: str | Path) -> dict:
    """Return PDF metadata (author, title, creation date, page count)."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    meta = doc.metadata or {}
    meta["page_count"] = doc.page_count
    doc.close()
    return meta


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

def _extract_pages(pdf_path: Path) -> Tuple[List[str], int]:
    """
    Open PDF with fitz and extract text from every page.
    Uses sort=True to handle multi-column layouts correctly.
    Returns (list_of_page_texts, total_page_count).
    """
    doc = fitz.open(str(pdf_path))
    pages_text = []

    for page_num, page in enumerate(doc, start=1):
        try:
            # sort=True → reading-order left→right, top→bottom
            text = page.get_text("text", sort=True)
            if not text.strip():
                # Possibly a scanned/image page — log and skip for now
                logger.debug(
                    f"  Page {page_num}: no extractable text "
                    f"(may be scanned image — OCR not yet implemented)"
                )
                continue
            pages_text.append(text)
        except Exception as exc:
            logger.warning(f"  Page {page_num}: extraction failed — {exc}")

    page_count = doc.page_count
    doc.close()
    return pages_text, page_count


def _clean_text(text: str) -> str:
    """
    Apply all noise-removal patterns and normalise whitespace.
    """
    for pattern in NOISE_PATTERNS:
        if pattern.pattern == r"\n{3,}":
            text = pattern.sub("\n\n", text)
        else:
            text = pattern.sub("", text)

    # Normalise Windows/Mac line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove trailing spaces on each line
    lines = [line.rstrip() for line in text.split("\n")]
    text  = "\n".join(lines)

    # Collapse runs of spaces (but not newlines)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


# ──────────────────────────────────────────────────────────────────
# Batch helper (used by orchestrator)
# ──────────────────────────────────────────────────────────────────

def batch_extract(pdf_paths: List[str | Path]) -> dict:
    """
    Extract text from a list of PDFs.
    Returns dict: { pdf_path_str → clean_text }
    Failures are logged but don't abort the batch.
    """
    results = {}
    for p in pdf_paths:
        try:
            results[str(p)] = extract_transcript(p)
        except Exception as exc:
            logger.error(f"[PDF] Failed: {p} — {exc}")
            results[str(p)] = ""
    return results


# ──────────────────────────────────────────────────────────────────
# Quick test
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py <path_to_pdf>")
        sys.exit(1)

    text = extract_transcript(sys.argv[1])
    print(text[:3000])
    print(f"\n--- Total characters: {len(text):,} ---")
