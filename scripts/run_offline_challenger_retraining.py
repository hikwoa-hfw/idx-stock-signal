"""CLI runner for Offline Challenger Retraining and Controlled Evaluation.

Executes expanding walk-forward evaluation, simulated trading, and candidate serialization
for LOW_PRICE and HIGHER_PRICE stock universes up to fully matured cutoff date.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.challenger_retraining import ChallengerRetrainingRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("run_offline_challenger_retraining")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run offline challenger retraining and controlled evaluation."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (defaults to settings.database_url).",
    )
    parser.add_argument(
        "--cutoff-date",
        type=str,
        default="2026-09-25",
        help="Latest decision date whose 15 forward sessions are fully observable.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="run_20261021_retraining",
        help="Unique run identifier for artifacts/offline_challengers/<run_id>/.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default=None,
        help="Custom output directory for artifacts.",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=3,
        help="Number of expanding walk-forward splits (default: 3).",
    )
    parser.add_argument(
        "--purge-days",
        type=int,
        default=15,
        help="Purge / embargo window in trading days (default: 15).",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for model training (default: 42).",
    )

    args = parser.parse_args()

    logger.info("Initializing ChallengerRetrainingRunner with run_id=%s...", args.run_id)
    runner = ChallengerRetrainingRunner(
        db_path=args.db_path,
        n_splits=args.n_splits,
        purge_days=args.purge_days,
        random_state=args.random_state,
        cutoff_date=args.cutoff_date,
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
    )

    logger.info("Starting full pipeline for LOW_PRICE and HIGHER_PRICE...")
    results = runner.run_full_pipeline()

    print("\n" + "=" * 80)
    print("OFFLINE CHALLENGER RETRAINING & EVALUATION COMPLETED")
    print("=" * 80)
    print(f"Run ID: {results['run_id']}")
    print(f"Cutoff Date: {results['training_decision_cutoff_date']}")
    print(f"Label Maturity Bar Date: {results['forward_label_maturity_bar_date']}")
    print(f"Artifacts Directory: {runner.artifacts_dir}")
    print("=" * 80)

    for mode, m_data in results["modes"].items():
        print(f"\n--- MODE: {mode} (Total Samples: {m_data['total_samples']}) ---")
        print("Classification Summaries (Macro Mean across Folds):")
        for s in m_data["classification_summaries"]:
            print(
                f"  [{s['model_id']:<25}] ROC-AUC: {s['roc_auc_mean']:.4f} "
                f"(std {s['roc_auc_std']:.4f}) | "
                f"PR-AUC: {s['pr_auc_mean']:.4f} | Brier: {s['brier_score_mean']:.4f} | "
                f"Top-10% Prec: {s['daily_top10_prec_mean']:.4f}"
            )

        print("\nTrading Simulation Summaries (Pooled across Folds, 50 bps friction):")
        for t in m_data["trading_summaries"]:
            print(
                f"  [{t['model_id']:<25}] Trades: {t['completed_trades']:>4} | "
                f"WinRate: {t['win_rate']:.2%} | Avg Net Ret: {t['avg_net_return']:+.4f} | "
                f"Pooled PF: {t['pooled_profit_factor']:.2f} | "
                f"Cont MaxDD: {t['continuous_max_drawdown_pct']:.2f}%"
            )


if __name__ == "__main__":
    main()
