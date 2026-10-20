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
    DataQualityError,
    InvalidProspectiveDateError,
    MissedSessionError,
    MissingScoringArtifactError,
    PaperTradingEngine,
    StateIntegrityError,
    UserApprovalRequiredError,
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
        "--approve-observation",
        action="store_true",
        help="Record explicit human authorization and cutoff for prospective paper trading",
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
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset paper trading persistent state and artifacts (testing only)",
    )
    return parser.parse_args()


def print_status_summary(status: dict) -> None:
    print("=" * 80)
    print("PHASE 11F — FORWARD PAPER TRADING OPERATIONAL STATUS")
    print("=" * 80)
    print(f"Status Code:            {status['operational_status']}")
    print(f"Scoring Artifacts:      {status.get('scoring_artifacts_status', 'UNKNOWN')}")
    print(f"User Approved:          {status.get('user_approved', False)}")
    app_meta = status.get("approval_metadata", {})
    print(f"Approval Timestamp:     {app_meta.get('approval_timestamp', 'NONE')}")
    print(f"Approval Data Cutoff:   {app_meta.get('approval_data_cutoff', 'NONE')}")
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

    pl = status.get("prospective_lifecycle")
    if pl:
        print("-" * 80)
        print("PROSPECTIVE OBSERVATION LIFECYCLE (PHASE 11F.3)")
        print("-" * 80)
        print(f"Observation Started:    {pl.get('has_started', False)}")
        print(f"First Observation Date: {pl.get('first_observation_date', 'NONE')}")
        print(f"Last Decision Date:     {pl.get('last_decision_date', 'NONE')}")
        print(f"Last Execution Session: {pl.get('last_execution_date', 'NONE')}")
        print(f"Sessions Processed:     {pl.get('processed_dates_count', 0)}")
        print(f"Pending Orders:         {pl.get('pending_orders_count', 0)}")
        for o in pl.get("pending_orders", [])[:5]:
            print(
                f"  * {o.get('ticker')} ({o.get('mode')}) "
                f"sched: {o.get('scheduled_execution_date')} score: {o.get('score', 0):.4f}"
            )
        print(f"Active Open Positions:  {pl.get('open_positions_count', 0)}")
        for p in pl.get("open_positions", [])[:5]:
            print(
                f"  * {p.get('ticker')} ({p.get('mode')}) entry: {p.get('entry_price', 0):.1f} "
                f"shares: {p.get('shares')} age: {p.get('holding_days')}d "
                f"MTM PnL: {p.get('unrealized_pnl_idr', 0):,.0f} IDR"
            )
        print(f"Completed Trades:       {pl.get('completed_trades_count', 0)}")
        print(f"Realized Net PnL (IDR): {pl.get('realized_net_pnl_idr', 0):,.0f}")
        print(f"Unrealized PnL (IDR):   {pl.get('unrealized_pnl_idr', 0):,.0f}")
        print(f"Cash Balance (IDR):     {pl.get('cash_balance_idr', 0):,.0f}")
        print(f"Current Total Equity:   {pl.get('current_equity_idr', 0):,.0f}")
        print(f"Peak Equity (IDR):      {pl.get('peak_equity_idr', 0):,.0f}")
        dd_amt = pl.get("max_drawdown_amount_idr", 0)
        dd_pct = pl.get("max_drawdown_pct", 0) * 100.0
        print(f"Max Drawdown:           {dd_amt:,.0f} ({dd_pct:.2f}%)")
        print(f"Unfilled / Inval Counts:{pl.get('unfilled_counts', {})}")
    print("=" * 80)


def main() -> None:
    args = parse_args()
    engine = PaperTradingEngine(
        db_path=args.db_path,
        artifacts_dir=args.artifacts_dir,
    )

    no_cmd = not (
        args.status
        or args.approve_observation
        or args.export_benchmarks
        or args.run_replay
        or args.date
        or args.reset_state
    )

    if args.reset_state:
        logger.info(
            "Resetting prospective paper trading state in %s...",
            engine.artifacts_dir,
        )
        engine.reset_state()
        logger.info("State reset complete.")
        return

    if args.approve_observation:
        logger.info("Recording explicit user approval for prospective observation...")
        approval_info = engine.approve_observation()
        logger.info("Approval recorded: %s", approval_info)
        print("=" * 80)
        print("PHASE 11F — PROSPECTIVE OBSERVATION APPROVAL RECORDED")
        print("=" * 80)
        print(f"User Approved:          {approval_info['user_approved']}")
        print(f"Approval Timestamp:     {approval_info['approval_timestamp']}")
        print(f"Market Data Cutoff:     {approval_info['approval_data_cutoff']}")
        print(f"Operational Status:     {approval_info['operational_status']}")
        print("=" * 80)
        return

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
        state = engine.load_state()
        if not state.get("user_approved") and not args.user_approved:
            logger.error(
                "Prospective observation date scoring on %s requires explicit user approval.",
                args.date,
            )
            print(
                "Error: Prospective observation date scoring requires explicit user approval. "
                "Pass --approve-observation first or provide --user-approved."
            )
            sys.exit(1)

        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        cutoff = state.get("approval_data_cutoff")
        if cutoff is None:
            cutoff = engine.get_latest_market_data_date()
        if cutoff and d <= datetime.strptime(cutoff, "%Y-%m-%d").date():
            logger.error(
                "Requested prospective date %s is at or before cutoff %s. "
                "Historical observation is prohibited.",
                d,
                cutoff,
            )
            print(
                f"Error: Requested prospective date {d} is at or before market data cutoff "
                f"{cutoff}. Historical prospective observation is prohibited."
            )
            sys.exit(1)

        logger.info("Evaluating prospective date %s...", d)
        try:
            res = engine.step_prospective_date(d, user_approved=True)
            logger.info("Prospective scoring result: %s", res)
        except (
            MissingScoringArtifactError,
            DataQualityError,
            InvalidProspectiveDateError,
            MissedSessionError,
            StateIntegrityError,
            UserApprovalRequiredError,
        ) as e:
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
