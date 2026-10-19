"""CLI runner to execute Phase 11B.1 Candidate Model Training & Evaluation."""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.candidate_eval import CandidateEvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 11B.1 Candidate Model Training & Evaluation for BEI Signals."
    )
    parser.add_argument(
        "--mode",
        choices=["LOW_PRICE", "HIGHER_PRICE", "BOTH"],
        default="BOTH",
        help="Price mode to evaluate (default: BOTH).",
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
        default=10,
        help="Purge window in trading days to eliminate target overlap (default: 10).",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/candidate_eval",
        help="Directory to save JSON and CSV artifacts (default: artifacts/candidate_eval).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: from settings).",
    )
    return parser.parse_args()


def print_comparison_table(mode: str, macro_df: pd.DataFrame, trading_df: pd.DataFrame) -> None:
    print("\n" + "=" * 95)
    print(f" CANDIDATE MODEL EVALUATION SUMMARY — MODE: {mode}")
    print("=" * 95)

    print("\n[A] Out-Of-Sample Predictive Performance (Macro Mean across 3 Expanding Folds):")
    pred_cols = [
        "model_id",
        "target_variant",
        "features_used",
        "macro_roc_auc_mean",
        "macro_pr_auc_mean",
        "macro_daily_top10_mean",
        "macro_brier_mean",
        "common_roc_auc_mean",
        "common_pr_auc_mean",
    ]
    avail_pred_cols = [c for c in pred_cols if c in macro_df.columns]
    print(macro_df[avail_pred_cols].to_string(index=False))

    print("\n[B] Simulated Trading Performance (50 bps Friction, Next-Open Execution):")
    trade_cols = [
        "model_id",
        "target_variant",
        "completed_trades",
        "invalidated_signals",
        "win_rate",
        "tp_rate",
        "sl_rate",
        "expiry_rate",
        "avg_net_return",
        "mean_profit_factor",
        "max_drawdown_pct",
    ]
    avail_trade_cols = [c for c in trade_cols if c in trading_df.columns]
    print(trading_df[avail_trade_cols].to_string(index=False))
    print("=" * 95 + "\n")


def main() -> None:
    args = parse_args()
    modes = ["LOW_PRICE", "HIGHER_PRICE"] if args.mode == "BOTH" else [args.mode]

    runner = CandidateEvaluationRunner(
        db_path=args.db_path,
        n_splits=args.n_splits,
        purge_days=args.purge_days,
        random_state=args.random_state,
    )

    out_p = Path(args.output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print(" Phase 11B.1: Candidate Model Training & Evaluation Engine")
    print(
        f" Modes: {modes} | Splits: {args.n_splits} | Purge: {args.purge_days}d | "
        f"Seed: {args.random_state}"
    )
    print(f" Artifacts target: {out_p.resolve()}")
    print(" Production champions remain strictly unchanged.")
    print("================================================================================\n")

    results_by_mode = {}

    for mode in modes:
        t0 = time.time()
        print(f"[*] Training and evaluating candidate models for mode: {mode} ...")
        res = runner.run_candidate_evaluation(mode=mode, simulate_trading=True)
        elapsed = time.time() - t0
        n_samp = res["total_universe_samples"]
        print(f"[+] Completed {mode} in {elapsed:.2f}s across {n_samp} samples.")
        results_by_mode[mode] = res

        df_macro = pd.DataFrame(res["macro_summaries"])
        df_trading = pd.DataFrame(res["trading_summaries"])
        print_comparison_table(mode, df_macro, df_trading)

    # Export all artifacts
    print("[*] Exporting structured artifacts to", out_p.resolve())
    exported = runner.export_artifacts(results_by_mode, output_dir=out_p)
    for k, v in exported.items():
        print(f"    - {k}: {v}")

    print("\n[+] Phase 11B.1 candidate evaluation execution finished successfully.")


if __name__ == "__main__":
    main()
