"""
run_ingestion.py
----------------
Top-level CLI entry point for Week 1 ingestion.

Usage:
  # Ingest all 5 companies (8 quarters each)
  python run_ingestion.py

  # Single company only
  python run_ingestion.py --company 500209

  # Multiple companies, force re-download
  python run_ingestion.py --company 500209 532540 --overwrite

  # Fast dev run (skip Screener.in)
  python run_ingestion.py --skip-screener

  # Only initialise the database schema (no scraping)
  python run_ingestion.py --init-only
"""

import argparse
import sys
from loguru import logger
from storage.database import init_db
from ingestion.orchestrator import run_ingestion


def main():
    parser = argparse.ArgumentParser(
        description="Financial Contradiction Tracker — Week 1 Ingestion"
    )
    parser.add_argument(
        "--company",
        nargs="+",
        metavar="BSE_CODE",
        help="Specific BSE codes to process (default: all 5 in config.py)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download PDFs even if they already exist on disk",
    )
    parser.add_argument(
        "--skip-screener",
        action="store_true",
        help="Skip Screener.in financial data fetch",
    )
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Only initialise the SQLite database schema and exit",
    )
    args = parser.parse_args()

    if args.init_only:
        init_db()
        logger.info("Database initialised. Exiting.")
        sys.exit(0)

    run_ingestion(
        companies=args.company,
        overwrite=args.overwrite,
        skip_screener=args.skip_screener,
    )


if __name__ == "__main__":
    main()
