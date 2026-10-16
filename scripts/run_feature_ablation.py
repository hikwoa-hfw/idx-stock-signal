"""CLI script to execute Phase 11A controlled feature ablation experiments."""

import argparse
import time
from pathlib import Path

import pandas as pd

from python.experiments.ablation import FeatureAblationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 11A Controlled Feature Ablation for BEI Dual-Mode Stock Signals."
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
        default="artifacts/ablation",
        help="Directory to save JSON and CSV artifacts (default: artifacts/ablation).",
    )
    parser.add_argument(
        "--include-group-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include secondary group-only diagnostic models (default: True).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: from settings).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    modes = ["LOW_PRICE", "HIGHER_PRICE"] if args.mode == "BOTH" else [args.mode]

    runner = FeatureAblationRunner(
        db_path=args.db_path,
        n_splits=args.n_splits,
        purge_days=args.purge_days,
        random_state=args.random_state,
    )

    out_p = Path(args.output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print(" Phase 11A: Controlled Feature Ablation for BEI Dual-Mode Stock Signals")
    print(
        f" Modes: {modes} | Splits: {args.n_splits} | Purge: {args.purge_days}d | "
        f"Seed: {args.random_state}"
    )
    print(f" Artifacts target: {out_p.resolve()}")
    print("================================================================================\n")

    all_summaries = []

    for mode in modes:
        t0 = time.time()
        print(f"[*] Running ablation experiment for mode: {mode} ...")
        res = runner.run_experiment(mode=mode, include_group_only=args.include_group_only)
        elapsed = time.time() - t0
        print(f"[+] Completed {mode} in {elapsed:.2f}s across {res['sample_count']} samples.")

        json_path, csv_path = runner.export_artifacts(res, output_dir=out_p)
        print(f"    - JSON: {json_path}")
        print(f"    - CSV:  {csv_path}")

        # Print clean aggregate summary table
        df_summary = pd.read_csv(csv_path)
        all_summaries.append(df_summary)

        print(f"\n--- Macro Fold-Aggregated Results Summary ({mode}) ---")
        cols_to_show = [
            "model_name",
            "features_used",
            "roc_auc_mean",
            "roc_auc_std",
            "pr_auc_mean",
            "daily_top_10pct_prec_mean",
            "daily_top_10pct_prec_std",
            "daily_top_5_prec_mean",
            "brier_score_mean",
            "delta_macro_roc_auc",
            "delta_macro_pr_auc",
            "delta_macro_daily_top_10pct_prec",
            "pooled_roc_auc",
        ]
        # Only select columns that exist in the dataframe
        available_cols = [c for c in cols_to_show if c in df_summary.columns]
        print(df_summary[available_cols].to_string(index=False))
        print("\n")

    if len(all_summaries) > 1:
        combined_df = pd.concat(all_summaries, ignore_index=True)
        comb_csv = out_p / "ablation_summary_aggregate.csv"
        comb_json = out_p / "ablation_summary_aggregate.json"
        combined_df.to_csv(comb_csv, index=False)
        combined_df.to_json(comb_json, orient="records", indent=2)
        print(f"[+] Combined aggregate summary written to {comb_csv}")


if __name__ == "__main__":
    main()
