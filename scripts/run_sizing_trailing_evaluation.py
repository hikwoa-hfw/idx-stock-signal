"""CLI Runner for Phase 11E Dynamic Conviction Sizing & Volatility Trailing Protection Research.

Executes:
- Frozen reference baselines (Phase 11D replication)
- Experiment A: Dynamic position sizing (Conservative binary, Three-tier, Smooth conviction)
- Experiment B: Volatility trailing protection (Breakeven ratchets, ATR trailing, Stepped lock)
- Experiment C: Combined sizing & trailing protection
- Walk-forward confirmation and regime allocation diagnostics

Outputs formatted console tables and machine-readable artifacts in artifacts/phase_11e/.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.sizing_trailing_eval import (
    SizingTrailingEvaluationEngine,
    run_all_phase11e_experiments,
)


def print_table(title: str, headers: list[str], rows: list[list[Any]]) -> None:
    """Prints clean, aligned text table."""
    print(f"\n=== {title} ===")
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print(" | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 11E Dynamic Sizing & Trailing Protection Research"
    )
    parser.add_argument(
        "--output-dir", type=str, default="artifacts/phase_11e", help="Artifact output directory"
    )
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 85)
    print("PHASE 11E — DYNAMIC CONVICTION SIZING & VOLATILITY TRAILING PROTECTION RESEARCH")
    print(f"Output directory: {args.output_dir}")
    print("Friction: 50 bps round-trip (15 buy, 25 sell, 5 entry slip, 5 exit slip)")
    print("Execution: Next-Session Open (Variant B)")
    print("Portfolio: Max 5 concurrent positions, 20% equity cap, 100-share IDX lots")
    print("=" * 85)

    engine = SizingTrailingEvaluationEngine()
    results = run_all_phase11e_experiments(engine=engine, output_dir=args.output_dir)

    pooled_df = results["pooled_df"]

    headers = [
        "Mode",
        "Experiment",
        "Policy ID",
        "Trades",
        "Rem Open",
        "WinRate",
        "TP Rate",
        "SL Rate",
        "Trail Rate",
        "Exp Rate",
        "Net Exp",
        "Port Ret %",
        "Pooled PF",
        "Worst Fold DD",
        "Cont DD",
        "Turnover",
        "Avg Alloc %",
        "Cash Exp %",
    ]

    for mode in ["LOW_PRICE", "HIGHER_PRICE"]:
        mode_df = pooled_df[pooled_df["mode"] == mode]
        rows = []
        for _, r in mode_df.iterrows():
            rows.append(
                [
                    r["mode"],
                    r["experiment"],
                    r["policy_id"],
                    int(r["completed_trades"]),
                    int(r.get("remaining_open_positions", 0)),
                    f"{r['win_rate'] * 100:.2f}%",
                    f"{r['tp_rate'] * 100:.2f}%",
                    f"{r['sl_rate'] * 100:.2f}%",
                    f"{r.get('trailing_stop_rate', 0.0) * 100:.2f}%",
                    f"{r['expiry_rate'] * 100:.2f}%",
                    f"{r['avg_net_return'] * 100:.2f}%",
                    f"{r.get('net_portfolio_return_pct', 0.0):.2f}%",
                    f"{r['pooled_profit_factor']:.2f}",
                    f"{r['worst_fold_max_drawdown_pct']:.2f}%",
                    f"{r['continuous_max_drawdown_pct']:.2f}%",
                    f"{r.get('portfolio_turnover', 0.0):.1f}x",
                    f"{r.get('avg_portfolio_allocation_pct', 0.0):.1f}%",
                    f"{r.get('avg_cash_exposure_pct', 100.0):.1f}%",
                ]
            )
        print_table(f"Policy Evaluation Summary — {mode}", headers, rows)

    # Regime allocation table
    regime_headers = [
        "Mode",
        "Policy ID",
        "Trades",
        "Skipped Regime",
        "Avg Alloc %",
        "Max Alloc %",
        "Cash Exp %",
        "Alloc Fav",
        "Alloc Mix",
        "Alloc Unfav",
    ]
    regime_rows = []
    for _, r in pooled_df[pooled_df["experiment"].isin(["EXP_A_SIZING", "COMBINED"])].iterrows():
        regime_rows.append(
            [
                r["mode"],
                r["policy_id"],
                int(r["completed_trades"]),
                int(r.get("skipped_regime_sizing", 0)),
                f"{r.get('avg_portfolio_allocation_pct', 0.0):.1f}%",
                f"{r.get('max_portfolio_allocation_pct', 0.0):.1f}%",
                f"{r.get('avg_cash_exposure_pct', 100.0):.1f}%",
                f"{r.get('avg_allocation_favorable', 0.0):.2f}x",
                f"{r.get('avg_allocation_mixed', 0.0):.2f}x",
                f"{r.get('avg_allocation_unfavorable', 0.0):.2f}x",
            ]
        )
    print_table("Regime Sizing & Capital Allocation Breakdown", regime_headers, regime_rows)

    elapsed = time.time() - t0
    print(f"\nPhase 11E research pipeline completed in {elapsed:.1f} seconds.")
    print("Exported artifacts:")
    for path in results["exported_files"]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
