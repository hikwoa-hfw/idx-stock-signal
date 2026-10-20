"""CLI runner for Phase 11F Forward Paper Trading & Frozen Policy Validation.

Commands:
    python scripts/run_forward_paper_trading.py --status
    python scripts/run_forward_paper_trading.py --export-benchmarks
    python scripts/run_forward_paper_trading.py --run-replay
    python scripts/run_forward_paper_trading.py --date 2026-10-19
    python scripts/run_forward_paper_trading.py (default: audit, export, replay, status)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.paper_trading import (
    MissingScoringArtifactError,
    PaperTradingEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("run_forward_paper_trading")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 11F Forward Paper Trading Runner & Protocol Auditor"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display operational status, fail-closed audit, and policy hash",
    )
    parser.add_argument(
        "--export-benchmarks",
        action="store_true",
        help="Export frozen policy configuration and reference benchmark tables",
    )
    parser.add_argument(
        "--run-replay",
        action="store_true",
        help="Execute historical replay using Phase 11C out-of-sample predictions",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Simulate prospective candidate scoring on specific trading date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--user-approved",
        action="store_true",
        help="Explicitly authorize prospective observation scoring or active observation status",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default="artifacts/phase_11f",
        help="Directory to write Phase 11F artifacts",
    )
    return parser.parse_args()


def print_status_summary(status: dict) -> None:
    print("=" * 80)
    print("PHASE 11F — FORWARD PAPER TRADING OPERATIONAL STATUS")
    print("=" * 80)
    print(f"Status Code:            {status['operational_status']}")
    print(f"Scoring Artifacts:      {status.get('scoring_artifacts_status', 'UNKNOWN')}")
    print(f"User Approved:          {status.get('user_approved', False)}")
    print(f"Timestamp:              {status['timestamp']}")
    print(f"Policy Bundle Hash:     {status['policy_bundle_hash']}")
    fc_active = status["scoring_artifacts_audit"]["fail_closed_guard_active"]
    fb_perm = status["scoring_artifacts_audit"]["champion_fallback_permitted"]
    print(f"Fail-Closed Active:     {fc_active}")
    print(f"Fallback Allowed:       {fb_perm}")
    print(f"Missing Artifacts:      {len(status['scoring_artifacts_audit']['missing_artifacts'])}")
    for a in status["scoring_artifacts_audit"]["missing_artifacts"]:
        print(f"  - {a}")
    print(f"Data Quality DB Bars:   {status['data_quality']['total_daily_bars']}")
    print(f"Last Historical Date:   {status['data_quality']['last_historical_bar_date']}")
    print("=" * 80)


def main() -> None:
    args = parse_args()
    engine = PaperTradingEngine(
        db_path=args.db_path,
        artifacts_dir=args.artifacts_dir,
    )

    no_cmd = not (args.status or args.export_benchmarks or args.run_replay or args.date)

    if args.status:
        status = engine.generate_operational_status(user_approved=args.user_approved)
        print_status_summary(status)
        return

    if args.export_benchmarks:
        logger.info("Exporting frozen policy config and benchmark tables...")
        cfg = engine.export_frozen_policy_config()
        bm = engine.export_frozen_reference_benchmarks()
        logger.info(
            "Exported config (SHA256: %s) and %d benchmark rows to %s",
            cfg["config_sha256"],
            len(bm),
            engine.artifacts_dir,
        )
        return

    if args.date:
        if not args.user_approved:
            logger.error(
                "Prospective observation date scoring on %s requires explicit user approval.",
                args.date,
            )
            print(
                "Error: Prospective observation date scoring requires explicit user approval. "
                "Pass --user-approved to confirm execution."
            )
            sys.exit(1)

        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        logger.info("Evaluating prospective date %s...", d)
        try:
            res = engine.step_prospective_date(d, user_approved=True)
            logger.info("Prospective scoring result: %s", res)
        except MissingScoringArtifactError as e:
            logger.error("Scoring aborted due to fail-closed guard: %s", e)
            print(f"FAIL_CLOSED: {e}")
            sys.exit(1)
        return

    if args.run_replay:
        logger.info("Running historical replay across LOW_PRICE and HIGHER_PRICE...")
        engine.export_frozen_policy_config()
        engine.export_frozen_reference_benchmarks()
        res = engine.run_replay()
        logger.info("Historical replay completed successfully:")
        for mode, summ in res["summaries"].items():
            logger.info(
                "[%s] Trades: %d | Win: %.2f%% | Net: %.4f | PF: %.2f | DD: %.2f%%",
                mode,
                summ["completed_trades"],
                summ["win_rate"] * 100.0,
                summ["avg_net_return"],
                summ["pooled_profit_factor"],
                summ["continuous_max_drawdown_pct"],
            )
        status = engine.generate_operational_status(
            replay_summaries=res["summaries"],
            total_candidates=res["candidates_count"],
            total_decisions=res["decisions_count"],
            total_trades=res["trades_count"],
            user_approved=args.user_approved,
        )
        print_status_summary(status)
        return

    if no_cmd:
        logger.info("Running default full protocol: export, replay, and status check...")
        engine.export_frozen_policy_config()
        engine.export_frozen_reference_benchmarks()
        res = engine.run_replay()
        status = engine.generate_operational_status(
            replay_summaries=res["summaries"],
            total_candidates=res["candidates_count"],
            total_decisions=res["decisions_count"],
            total_trades=res["trades_count"],
            user_approved=args.user_approved,
        )
        print_status_summary(status)


if __name__ == "__main__":
    main()
