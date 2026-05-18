"""
ingestion/bse_scraper.py
------------------------
Scrapes BSE India for earnings-call transcript links for a given company,
then downloads the PDFs into data/transcripts/<bse_code>/<quarter>/.

Strategy:
  1. Hit the BSE announcements search page filtered by sub-category
     "Investor Presentation" + "Earnings Call".
  2. Parse the result table for PDF links whose title contains
     'transcript', 'earnings call', or 'concall'.
  3. Download each PDF; skip if already present on disk.

BSE's public endpoints (no auth required):
  Announcement list : https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
  Document download : https://www.bseindia.com/xml-data/corpfiling/AttachLive/<filename>
"""

import re
import time
import requests
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger
from tqdm import tqdm

# ── Paths ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────
BSE_ANN_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_DOC_URL  = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{filename}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/",
}

# Keywords that identify a document as an earnings-call transcript
TRANSCRIPT_KEYWORDS = [
    "transcript", "concall", "earnings call",
    "conference call", "investor call", "analyst call",
]

# Sub-category codes on BSE for announcements
# 57 = Investor Presentation / Concall transcript
ANN_SUBCATEGORY = "57"


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def fetch_transcript_links(
    bse_code: str,
    from_date: str = "20220401",   # YYYYMMDD
    to_date:   str = "20250331",
) -> List[Dict]:
    """
    Returns a list of dicts:
      { 'quarter': 'Q1FY24', 'year': 2023, 'url': '...', 'filename': '...' }

    Makes paginated calls to the BSE announcement API.
    """
    logger.info(f"[BSE] Fetching transcript links for {bse_code} ({from_date}→{to_date})")

    params = {
        "pageno":      "1",
        "strCat":      "-1",
        "strPrevDate": from_date,
        "strScrip":    bse_code,
        "strSearch":   "P",
        "strToDate":   to_date,
        "strType":     "C",
        "subcategory": ANN_SUBCATEGORY,
    }

    results = []
    page = 1

    while True:
        params["pageno"] = str(page)
        try:
            resp = requests.get(BSE_ANN_API, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"[BSE] API call failed (page {page}): {exc}")
            break

        announcements = data.get("Table", [])
        if not announcements:
            break

        for ann in announcements:
            headline = (ann.get("HEADLINE") or "").lower()
            filename  = ann.get("ATTACHMENTNAME") or ""
            news_date = ann.get("NEWS_DT") or ""           # e.g. "2023-07-15T00:00:00"

            if not _is_transcript(headline, filename):
                continue

            quarter, year = _parse_quarter(news_date, headline)
            url = BSE_DOC_URL.format(filename=filename)

            results.append({
                "quarter":  quarter,
                "year":     year,
                "url":      url,
                "filename": filename,
                "headline": ann.get("HEADLINE", ""),
                "date":     news_date,
            })
            logger.debug(f"  Found: {quarter} → {filename}")

        # BSE API returns ≤50 rows per page
        if len(announcements) < 50:
            break
        page += 1
        time.sleep(0.5)          # polite delay

    logger.info(f"[BSE] Found {len(results)} transcript links for {bse_code}")
    return results


def download_transcripts(
    bse_code: str,
    links: List[Dict],
    overwrite: bool = False,
) -> List[Dict]:
    """
    Downloads each PDF in *links* to data/transcripts/<bse_code>/<quarter>/.
    Returns the same list augmented with a 'local_path' key.
    """
    company_dir = TRANSCRIPT_DIR / bse_code
    company_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for item in tqdm(links, desc=f"Downloading {bse_code}", unit="pdf"):
        quarter_dir = company_dir / item["quarter"]
        quarter_dir.mkdir(parents=True, exist_ok=True)

        local_path = quarter_dir / item["filename"]

        if local_path.exists() and not overwrite:
            logger.debug(f"  Skip (exists): {local_path.name}")
            item["local_path"] = str(local_path)
            downloaded.append(item)
            continue

        try:
            resp = requests.get(item["url"], headers=HEADERS, timeout=60, stream=True)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"  Downloaded: {local_path.name} ({local_path.stat().st_size // 1024} KB)")
            item["local_path"] = str(local_path)
            downloaded.append(item)
        except Exception as exc:
            logger.warning(f"  Failed to download {item['url']}: {exc}")
            item["local_path"] = None

        time.sleep(0.3)

    return downloaded


def scrape_and_download(
    bse_code: str,
    from_date: str = "20220401",
    to_date:   str = "20250331",
    overwrite: bool = False,
) -> List[Dict]:
    """Convenience wrapper: fetch links then download all PDFs."""
    links = fetch_transcript_links(bse_code, from_date, to_date)
    if not links:
        logger.warning(f"[BSE] No transcripts found for {bse_code}")
        return []
    return download_transcripts(bse_code, links, overwrite=overwrite)


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

def _is_transcript(headline: str, filename: str) -> bool:
    """Return True if the announcement looks like an earnings-call transcript."""
    combined = (headline + " " + filename).lower()
    return any(kw in combined for kw in TRANSCRIPT_KEYWORDS)


def _parse_quarter(date_str: str, headline: str) -> tuple[str, int]:
    """
    Best-effort quarter detection.
    First tries to extract from headline (e.g. 'Q2 FY2024', 'Q3FY23').
    Falls back to deriving from the filing date.
    """
    # Try headline patterns
    m = re.search(
        r"Q([1-4])\s*FY\s*(\d{2,4})",
        headline,
        re.IGNORECASE,
    )
    if m:
        q_num = m.group(1)
        fy    = m.group(2)
        fy    = "20" + fy if len(fy) == 2 else fy
        return f"Q{q_num}FY{fy[2:]}", int(fy)

    # Fall back to date
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str.split("T")[0])
        year  = dt.year
        month = dt.month
        # Indian FY: Apr-Jun=Q1, Jul-Sep=Q2, Oct-Dec=Q3, Jan-Mar=Q4
        q_map = {4:1,5:1,6:1, 7:2,8:2,9:2, 10:3,11:3,12:3, 1:4,2:4,3:4}
        q_num = q_map.get(month, 1)
        fy_year = year if month >= 4 else year - 1
        return f"Q{q_num}FY{str(fy_year)[2:]}", fy_year
    except Exception:
        return "Q0FY00", 0


# ──────────────────────────────────────────────────────────────────
# Quick test
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Quick smoke-test with Infosys (BSE code 500209)
    links = fetch_transcript_links("500209", from_date="20230101", to_date="20241231")
    print(f"\nFound {len(links)} transcript links")
    for lnk in links[:5]:
        print(f"  {lnk['quarter']} | {lnk['headline'][:60]}")
