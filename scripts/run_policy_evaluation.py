"""CLI Runner for Phase 11D Dynamic Exit & Policy Selection Research.

Executes:
- Frozen reference baselines (Phase 11C replication)
- Experiment A: Cross-sectional entry selectivity (Top 10%, 5%, 3%, 1%)
- Experiment B: Market-regime-conditioned selection
- Experiment C: Dynamic holding period duration
- Experiment D: Dynamic TP/SL barrier adaptation
- Walk-forward confirmation & Combined Policy

Outputs formatted console tables and machine-readable artifacts in artifacts/phase_11d/.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.policy_eval import PolicyEvaluationEngine, run_all_phase11d_experiments


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
    parser = argparse.ArgumentParser(description="Run Phase 11D Policy Evaluation Research")
    parser.add_argument(
        "--output-dir", type=str, default="artifacts/phase_11d", help="Artifact output directory"
    )
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 80)
    print("PHASE 11D — DYNAMIC EXIT & POLICY SELECTION RESEARCH")
    print(f"Output directory: {args.output_dir}")
    print("Friction: 50 bps (15 buy, 25 sell, 5 entry slip, 5 exit slip)")
    print("Execution: Next-Session Open (Variant B)")
    print("Portfolio: Max 5 concurrent positions, 20% equity cap, 100-share lots")
    print("=" * 80)

    engine = PolicyEvaluationEngine()
    results = run_all_phase11d_experiments(engine=engine, output_dir=args.output_dir)

    pooled_df = results["pooled_df"]

    headers = [
        "Mode",
        "Experiment",
        "Policy ID",
        "Eligible",
        "Trades",
        "WinRate",
        "TP Rate",
        "SL Rate",
        "Exp Rate",
        "Net Return",
        "Pooled PF",
        "Worst Fold DD",
        "Continuous DD",
        "Turnover",
        "TimeInMkt",
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
                    int(r.get("eligible_candidates", 0)),
                    int(r["completed_trades"]),
                    f"{r['win_rate'] * 100:.2f}%",
                    f"{r['tp_rate'] * 100:.2f}%",
                    f"{r['sl_rate'] * 100:.2f}%",
                    f"{r['expiry_rate'] * 100:.2f}%",
                    f"{r['avg_net_return'] * 100:.2f}%",
                    f"{r['pooled_profit_factor']:.2f}",
                    f"{r['worst_fold_max_drawdown_pct']:.2f}%",
                    f"{r['continuous_max_drawdown_pct']:.2f}%",
                    f"{r.get('portfolio_turnover', 0.0):.1f}x",
                    f"{r.get('time_in_market_pct', 0.0):.1f}%",
                ]
            )
        print_table(f"Policy Evaluation Summary — {mode}", headers, rows)

    elapsed = time.time() - t0
    print(f"\nPhase 11D research pipeline completed in {elapsed:.1f} seconds.")
    print("Exported artifacts:")
    for path in results["exported_files"]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
