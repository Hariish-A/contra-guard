"""
run_extraction.py
-----------------
Top-level CLI entry point for Week 2 extraction.

Usage:
  # Process all unprocessed transcripts in the database
  python run_extraction.py

  # Process only the first N transcripts (useful for testing)
  python run_extraction.py --limit 2
"""

import argparse
from loguru import logger
from extraction.orchestrator import run_extraction

def main():
    parser = argparse.ArgumentParser(
        description="Financial Contradiction Tracker — Week 2 Extraction Layer"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of transcripts to process (default: all unprocessed)",
    )
    args = parser.parse_args()

    run_extraction(limit=args.limit)

if __name__ == "__main__":
    main()
