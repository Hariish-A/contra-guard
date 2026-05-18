"""
ingestion/orchestrator.py
--------------------------
Week 1 orchestration: run the full ingestion pipeline for all 5 target companies.

Steps per company:
  1. Upsert company into DB
  2. Scrape BSE for transcript PDF links (8 target quarters)
  3. Download PDFs to data/transcripts/<bse_code>/<quarter>/
  4. Extract clean text from each PDF
  5. Insert transcript record into DB (raw_text, source_url, pdf_path)

Run:
    python -m ingestion.orchestrator
    python -m ingestion.orchestrator --company INFY --overwrite
"""

import argparse
import sys
from pathlib import Path
from loguru import logger

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import (
    COMPANIES, TARGET_QUARTERS,
    SCRAPE_FROM_DATE, SCRAPE_TO_DATE,
    LOG_FILE,
)
from storage.database import init_db, upsert_company, insert_transcript
from ingestion.bse_scraper import scrape_and_download
from ingestion.pdf_extractor import extract_transcript
from ingestion.screener_scraper import scrape_screener


# ── Logging setup ─────────────────────────────────────────────────
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add(str(LOG_FILE), level="DEBUG", rotation="10 MB", retention="30 days")


# ──────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────

def run_ingestion(
    companies: list = None,
    overwrite: bool = False,
    skip_screener: bool = False,
):
    """
    Full Week 1 ingestion pipeline.

    Args:
        companies:      List of BSE codes to process. None = all COMPANIES in config.
        overwrite:      Re-download PDFs even if they exist locally.
        skip_screener:  Skip Screener.in financial data fetch (faster for dev).
    """
    init_db()

    target = companies or [c["bse_code"] for c in COMPANIES]
    company_map = {c["bse_code"]: c for c in COMPANIES}

    overall_stats = {
        "companies_processed": 0,
        "transcripts_found":   0,
        "transcripts_saved":   0,
        "pdfs_downloaded":     0,
    }

    for bse_code in target:
        if bse_code not in company_map:
            logger.warning(f"BSE code {bse_code} not in config — skipping")
            continue

        info = company_map[bse_code]
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {info['name']} ({bse_code})")
        logger.info(f"{'='*60}")

        # 1. Upsert company
        company_id = upsert_company(
            name=info["name"],
            bse_code=bse_code,
            sector=info["sector"],
        )
        logger.info(f"  DB company_id = {company_id}")

        # 2-3. Scrape BSE + download PDFs
        downloaded = scrape_and_download(
            bse_code=bse_code,
            from_date=SCRAPE_FROM_DATE,
            to_date=SCRAPE_TO_DATE,
            overwrite=overwrite,
        )

        overall_stats["transcripts_found"] += len(downloaded)
        overall_stats["pdfs_downloaded"]   += sum(1 for d in downloaded if d.get("local_path"))

        if not downloaded:
            logger.warning(f"  No transcripts found for {bse_code} — skipping text extraction")
        else:
            # Filter to target quarters only
            target_q_set = set(TARGET_QUARTERS)
            in_scope = [d for d in downloaded if d["quarter"] in target_q_set]
            out_of_scope = len(downloaded) - len(in_scope)
            if out_of_scope:
                logger.debug(f"  Filtered out {out_of_scope} transcripts outside target quarters")

            # 4-5. Extract text + save to DB
            for item in in_scope:
                _process_transcript(item, company_id)
                overall_stats["transcripts_saved"] += 1

        # 6. Screener financial data (optional)
        if not skip_screener:
            _fetch_screener(info)

        overall_stats["companies_processed"] += 1

    # Summary
    logger.info("\n" + "="*60)
    logger.info("INGESTION COMPLETE — Summary")
    logger.info(f"  Companies processed : {overall_stats['companies_processed']}")
    logger.info(f"  Transcripts found   : {overall_stats['transcripts_found']}")
    logger.info(f"  PDFs downloaded     : {overall_stats['pdfs_downloaded']}")
    logger.info(f"  DB records saved    : {overall_stats['transcripts_saved']}")
    logger.info("="*60)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _process_transcript(item: dict, company_id: int) -> None:
    """Extract text from a downloaded PDF and save the transcript record to DB."""
    local_path = item.get("local_path")
    if not local_path or not Path(local_path).exists():
        logger.warning(f"  PDF missing: {item.get('filename', '?')} — skipping")
        return

    try:
        raw_text = extract_transcript(local_path)
    except Exception as exc:
        logger.error(f"  Text extraction failed for {local_path}: {exc}")
        raw_text = ""

    try:
        transcript_id = insert_transcript(
            company_id=company_id,
            quarter=item["quarter"],
            year=item["year"],
            source_url=item.get("url", ""),
            pdf_path=local_path,
            raw_text=raw_text,
        )
        logger.info(
            f"  Saved transcript → DB id={transcript_id} | "
            f"{item['quarter']} | {len(raw_text):,} chars"
        )
    except Exception as exc:
        logger.error(f"  DB insert failed: {exc}")


def _fetch_screener(info: dict) -> None:
    """Pull structured financials from Screener.in (best-effort)."""
    ticker = info["nse_ticker"]
    try:
        data = scrape_screener(ticker)
        qr   = data.get("quarterly_results")
        if qr is not None and not qr.empty:
            logger.info(
                f"  Screener [{ticker}]: {qr.shape[1]} quarters of financial data available"
            )
        else:
            logger.warning(f"  Screener [{ticker}]: no quarterly data returned")
    except Exception as exc:
        logger.warning(f"  Screener [{ticker}] failed (non-fatal): {exc}")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Week 1 Ingestion — scrape BSE transcripts for 5 companies"
    )
    parser.add_argument(
        "--company",
        nargs="+",
        metavar="BSE_CODE",
        help="One or more BSE codes to process (default: all 5 in config)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download PDFs even if they already exist",
    )
    parser.add_argument(
        "--skip-screener",
        action="store_true",
        help="Skip Screener.in fetch (saves time during dev)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_ingestion(
        companies=args.company,
        overwrite=args.overwrite,
        skip_screener=args.skip_screener,
    )
