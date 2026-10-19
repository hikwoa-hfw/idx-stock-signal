"""CLI runner to execute Phase 11C Multi-Horizon Evaluation & Return Estimation."""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.multi_horizon_eval import MultiHorizonEvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 11C Multi-Horizon Evaluation & Return Estimation for BEI Signals."
    )
    parser.add_argument(
        "--mode",
        choices=["LOW_PRICE", "HIGHER_PRICE", "BOTH"],
        default="BOTH",
        help="Price mode to evaluate (default: BOTH).",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="3,5,10,15",
        help="Comma-separated holding horizons in trading days (default: 3,5,10,15).",
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
        help="Purge window in trading days to eliminate target overlap (default: 15).",
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
        default="artifacts/phase_11c",
        help="Directory to save JSON and CSV artifacts (default: artifacts/phase_11c).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: from settings).",
    )
    return parser.parse_args()


def print_horizon_summary_tables(mode: str, res: dict[str, Any]) -> None:
    print("\n" + "=" * 105)
    print(f" PHASE 11C MULTI-HORIZON EVALUATION SUMMARY — MODE: {mode}")
    print("=" * 105)

    all_clf: list[dict[str, Any]] = []
    all_reg: list[dict[str, Any]] = []
    all_trade: list[dict[str, Any]] = []
    all_ev: list[dict[str, Any]] = []

    for h, h_data in res["horizon_results"].items():
        for item in h_data["classification_summaries"]:
            all_clf.append({"horizon": h, **item})
        for item in h_data["regression_summaries"]:
            all_reg.append({"horizon": h, **item})
        for item in h_data["trading_summaries"]:
            all_trade.append(item)
        for item in h_data["ev_diagnostic_results"]:
            all_ev.append(item)

    df_clf = pd.DataFrame(all_clf)
    df_reg = pd.DataFrame(all_reg)
    df_trade = pd.DataFrame(all_trade)
    df_ev = pd.DataFrame(all_ev)

    print("\n[A] Out-Of-Sample Classification Performance across Horizons:")
    clf_cols = [
        "horizon",
        "model_id",
        "macro_roc_auc_mean",
        "macro_pr_auc_mean",
        "macro_daily_top10_mean",
        "macro_brier_mean",
        "macro_ece_mean",
    ]
    avail_clf_cols = [c for c in clf_cols if c in df_clf.columns]
    print(df_clf[avail_clf_cols].to_string(index=False))

    print("\n[B] Return Regression Performance across Horizons (vs Zero & Mean Baselines):")
    reg_cols = [
        "horizon",
        "model_id",
        "macro_mae_mean",
        "macro_mae_zero_mean",
        "macro_mae_mean_baseline_mean",
        "macro_rmse_mean",
        "macro_r2_mean",
        "macro_pearson_r_mean",
    ]
    avail_reg_cols = [c for c in reg_cols if c in df_reg.columns]
    print(df_reg[avail_reg_cols].to_string(index=False))

    print("\n[C] Simulated Trading Performance (50 bps Friction, Next-Open Execution):")
    trade_cols = [
        "horizon",
        "model_id",
        "completed_trades",
        "invalidated_signals",
        "win_rate",
        "tp_rate",
        "sl_rate",
        "expiry_rate",
        "avg_net_return",
        "pooled_profit_factor",
        "worst_fold_max_drawdown_pct",
        "continuous_max_drawdown_pct",
    ]
    avail_trade_cols = [c for c in trade_cols if c in df_trade.columns]
    print(df_trade[avail_trade_cols].to_string(index=False))

    print("\n[D] Discrete EV vs Regressor Return Correlation & Filtering Diagnostics:")
    ev_cols = [
        "horizon",
        "fold",
        "pearson_r_classifier_prob",
        "pearson_r_discrete_ev",
        "pearson_r_regressor",
        "positive_ev_count",
        "positive_ev_win_rate",
        "positive_ev_avg_net_return",
        "positive_reg_count",
        "positive_reg_win_rate",
        "positive_reg_avg_net_return",
    ]
    avail_ev_cols = [c for c in ev_cols if c in df_ev.columns]
    print(df_ev[avail_ev_cols].to_string(index=False))
    print("=" * 105 + "\n")


def main() -> None:
    args = parse_args()
    modes = ["LOW_PRICE", "HIGHER_PRICE"] if args.mode == "BOTH" else [args.mode]
    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]

    print("================================================================================")
    print(" Phase 11C: Multi-Horizon Evaluation & Return Estimation Engine")
    print(
        f" Modes: {modes} | Horizons: {horizons} | Splits: {args.n_splits} | "
        f"Purge: {args.purge_days}d"
    )
    print(" Execution Proxy: Variant B (Next-Open) | Friction Contract: 50 bps round-trip")
    print(" STRICT IMMUTABILITY: Production models and live configs remain untouched.")
    print("================================================================================\n")

    runner = MultiHorizonEvaluationRunner(
        db_path=args.db_path,
        n_splits=args.n_splits,
        purge_days=args.purge_days,
        random_state=args.random_state,
    )

    out_p = Path(args.output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    results_by_mode: dict[str, Any] = {}
    for mode in modes:
        t0 = time.time()
        print(f"[*] Starting multi-horizon evaluation for mode: {mode} ...")
        res = runner.run_multi_horizon_evaluation(
            mode=mode,
            horizons=horizons,
            simulate_trading=True,
        )
        elapsed = time.time() - t0
        print(f"[+] Finished {mode} multi-horizon evaluation in {elapsed:.2f}s.")
        results_by_mode[mode] = res
        print_horizon_summary_tables(mode, res)

    print("[*] Exporting structured artifacts to", out_p.resolve())
    exported = runner.export_artifacts(results_by_mode, output_dir=out_p)
    for k, v in exported.items():
        print(f"    - {k}: {v}")

    print("\n[+] Phase 11C Multi-Horizon evaluation completed successfully.")


if __name__ == "__main__":
    main()
