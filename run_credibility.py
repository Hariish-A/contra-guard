"""
run_credibility.py
------------------
CLI entry point for Milestone 5 — Executive Credibility Scorer.

Modes
-----

1. Extract numeric predictions from guidance statements and store in DB:
   python run_credibility.py --extract-predictions

2. Extract predictions for a single executive only:
   python run_credibility.py --extract-predictions --exec-id 1

3. Score all executives and print the full report:
   python run_credibility.py --score

4. Score a single executive:
   python run_credibility.py --score --exec-id 1

5. Verify a prediction manually (fill in the actual value):
   python run_credibility.py --verify --pred-id 3 --actual 14.5

6. List all stored predictions (optionally for one executive):
   python run_credibility.py --list-predictions
   python run_credibility.py --list-predictions --exec-id 1

7. Export the credibility report as JSON:
   python run_credibility.py --score --json

"""

import sys
import json
import argparse
from pathlib import Path
from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from storage.database import (
    get_connection,
    get_all_executives,
    get_predictions_for_executive,
    update_prediction_actual,
)
from credibility.scorer import (
    PredictionExtractor,
    CredibilityScorer,
    format_credibility_report,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sub-command handlers
# ─────────────────────────────────────────────────────────────────────────────

def cmd_extract_predictions(exec_id: int = None) -> None:
    """Extract numeric predictions from guidance statements into DB."""
    logger.info("=" * 70)
    logger.info("MILESTONE 5 — STEP 1: PREDICTION EXTRACTION")
    logger.info("=" * 70)

    extractor = PredictionExtractor()
    total     = extractor.run(executive_id=exec_id)

    if total == 0:
        logger.warning(
            "No new predictions extracted. Possible reasons:\n"
            "  • Extraction (Week 2) has not been run yet — run `python run_extraction.py` first.\n"
            "  • All eligible statements have already been processed.\n"
            "  • The statements lack numeric guidance (check statement types in DB)."
        )
    else:
        logger.info(f"Done — {total} prediction(s) inserted into the `predictions` table.")


def cmd_score(exec_id: int = None, as_json: bool = False) -> None:
    """Compute and display credibility scores."""
    logger.info("=" * 70)
    logger.info("MILESTONE 5 — STEP 2: CREDIBILITY SCORING")
    logger.info("=" * 70)

    scorer = CredibilityScorer()

    if exec_id is not None:
        result = scorer.score_executive(exec_id)
        if not result:
            logger.error(f"No result for executive ID {exec_id}.")
            return
        results = [result]
    else:
        results = scorer.score_all()
        if not results:
            logger.warning(
                "No executives found in DB. Run ingestion + extraction + contradiction pipeline first."
            )
            return

    if as_json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(format_credibility_report(results))


def cmd_verify(pred_id: int, actual_value: float) -> None:
    """Manually fill in the actual outcome for a prediction."""
    update_prediction_actual(pred_id, actual_value, verified=1)
    logger.info(
        f"Prediction ID {pred_id} updated: actual_value={actual_value}, verified=1"
    )


def cmd_list_predictions(exec_id: int = None) -> None:
    """Print all stored predictions (optionally for one executive)."""
    if exec_id is not None:
        executives_to_show = [exec_id]
    else:
        executives_to_show = [e["id"] for e in get_all_executives()]

    if not executives_to_show:
        logger.warning("No executives in database.")
        return

    conn = get_connection()
    print("\n" + "=" * 90)
    print("STORED PREDICTIONS")
    print("=" * 90)
    print(
        f"{'ID':<5} {'Exec ID':<8} {'Quarter':<10} {'Metric':<22} "
        f"{'Predicted':>10} {'Direction':<10} {'Actual':>10} {'Verified':<10}"
    )
    print("-" * 90)

    for eid in executives_to_show:
        exec_row = conn.execute(
            "SELECT name, role FROM executives WHERE id=?", (eid,)
        ).fetchone()
        if exec_row:
            print(f"\n  ► {exec_row['name']} ({exec_row['role']})")

        preds = get_predictions_for_executive(eid)
        if not preds:
            print("    (no predictions)")
            continue

        for p in preds:
            actual_str   = f"{p['actual_value']:.2f}" if p["actual_value"] is not None else "—"
            verified_str = "✓" if p["verified"] else "pending"
            pred_str     = f"{p['predicted_value']:.2f}" if p["predicted_value"] is not None else "—"
            print(
                f"  {p['id']:<5} {p['executive_id']:<8} {p['quarter']:<10} "
                f"{p['metric']:<22} {pred_str:>10} {p['direction']:<10} "
                f"{actual_str:>10} {verified_str:<10}"
            )

    conn.close()
    print("=" * 90 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Financial Contradiction Tracker — Credibility Scorer (Milestone 5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_credibility.py --extract-predictions
  python run_credibility.py --extract-predictions --exec-id 1
  python run_credibility.py --score
  python run_credibility.py --score --exec-id 2
  python run_credibility.py --score --json
  python run_credibility.py --verify --pred-id 7 --actual 15.3
  python run_credibility.py --list-predictions
  python run_credibility.py --list-predictions --exec-id 1
        """,
    )

    # Mutually exclusive primary modes
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--extract-predictions",
        action="store_true",
        help="Extract numeric predictions from guidance statements into the predictions table",
    )
    mode_group.add_argument(
        "--score",
        action="store_true",
        help="Compute credibility scores for all executives (or one with --exec-id)",
    )
    mode_group.add_argument(
        "--verify",
        action="store_true",
        help="Record the actual outcome for a prediction (requires --pred-id and --actual)",
    )
    mode_group.add_argument(
        "--list-predictions",
        action="store_true",
        help="List all stored predictions (optionally filtered by --exec-id)",
    )

    # Shared optional arguments
    parser.add_argument(
        "--exec-id",
        type=int,
        metavar="ID",
        help="Limit to a single executive by their database ID",
    )
    parser.add_argument(
        "--pred-id",
        type=int,
        metavar="ID",
        help="Prediction row ID to update (used with --verify)",
    )
    parser.add_argument(
        "--actual",
        type=float,
        metavar="VALUE",
        help="Actual outcome value to record (used with --verify)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output the score report as JSON (used with --score)",
    )

    args = parser.parse_args()

    # ── Validate argument combinations ────────────────────────────────────
    if args.verify:
        if args.pred_id is None or args.actual is None:
            parser.error("--verify requires both --pred-id <ID> and --actual <VALUE>")

    # ── Dispatch ──────────────────────────────────────────────────────────
    if args.extract_predictions:
        cmd_extract_predictions(exec_id=args.exec_id)

    elif args.score:
        cmd_score(exec_id=args.exec_id, as_json=args.as_json)

    elif args.verify:
        cmd_verify(pred_id=args.pred_id, actual_value=args.actual)

    elif args.list_predictions:
        cmd_list_predictions(exec_id=args.exec_id)


if __name__ == "__main__":
    main()
