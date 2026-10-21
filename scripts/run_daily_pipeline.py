"""CLI entry point for daily end-to-end pipeline automation.

Workflow:
1. Stage A: Market data ingestion
2. Stage B: Data validation and freshness gate
3. Stage C: Feature generation and persistence
4. Stage D: Feature readiness gate
5. Stage E: Research paper-trading lifecycle
6. Stage F: Post-run verification and operational reporting

Usage:
    python -m scripts.run_daily_pipeline
    python -m scripts.run_daily_pipeline --skip-ingest
    python -m scripts.run_daily_pipeline --date 2026-10-16 --skip-ingest
    python -m scripts.run_daily_pipeline --mode incremental
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.pipeline.daily_pipeline import DailyPipeline, PipelineRunReport


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run daily market-data-to-paper-trading pipeline for IDX Stock Signal."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target session date to process (YYYY-MM-DD). Defaults to latest completed session.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Market data provider ('yfinance', 'local_csv', etc.). Defaults to settings.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="incremental",
        choices=["incremental", "repair", "backfill"],
        help="Ingestion mode (default: incremental).",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip Stage A ingestion and validate existing database records.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="Ingestion lookback window in days (default: 30).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Provider batch size (default: 25).",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.70,
        help="Minimum required ticker coverage fraction on session (default: 0.70).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Database URL override.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default=None,
        help="Artifacts directory override (default: artifacts/phase_11f).",
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default=None,
        help="Reports output directory override (default: artifacts/pipeline_runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline in dry-run mode without modifying paper-trading persistent state.",
    )
    parser.add_argument(
        "--allow-synthetic-fixture",
        action="store_true",
        help="Allow mock/synthetic market data provider (TEST FIXTURES ONLY).",
    )
    return parser.parse_args(argv)


def print_report_summary(report: PipelineRunReport) -> None:
    print("=" * 80)
    print("IDX STOCK SIGNAL  DAILY PIPELINE EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Pipeline Run ID:      {report.run_id}")
    print(f"Git Commit SHA:       {report.git_commit_sha}")
    print(f"Configured Provider:  {report.configured_provider}")
    print(f"Started At:           {report.started_at}")
    print(f"Finished At:          {report.finished_at}")
    print(f"Total Duration:       {report.duration_seconds:.2f}s")
    print(f"Overall Status:       {report.overall_status}")
    print("-" * 80)
    print("STAGE EXECUTION BREAKDOWN:")
    print("-" * 80)
    for stage_key, s in report.stages.items():
        status_str = s.get("status", "UNKNOWN")
        dur = s.get("duration_seconds", 0.0)
        name = s.get("stage_name", stage_key)
        print(f"  [{status_str:^7}] {name:<32} ({dur:>6.2f}s)")
        if s.get("error"):
            print(f"            Error: {s['error']}")

    print("-" * 80)
    print("PIPELINE OPERATIONAL STATE:")
    print("-" * 80)

    val = report.validation_summary
    if val:
        sess = val.get("latest_completed_session", "NONE")
        cov = val.get("coverage_pct", 0.0)
        dist = val.get("distinct_tickers_count", 0)
        tot = val.get("active_universe_count", 0)
        print(
            f"  Latest Completed Session: {sess} ({dist}/{tot} tickers, {cov * 100:.1f}% coverage)"
        )

    feat = report.feature_summary
    if feat:
        gen = feat.get("features_generated_count", 0)
        ver = feat.get("db_verified_count", 0)
        ver_tag = report.feature_version or feat.get("feature_version", "v1.0.0")
        print(f"  Feature Persistence:      {gen} generated, {ver} verified in DB (ver={ver_tag})")
        if report.feature_schema_hash:
            print(f"  Feature Schema Hash:      {report.feature_schema_hash}")

    pt = report.paper_trading_summary
    if pt:
        act = pt.get("action", pt.get("operational_status", "UNKNOWN"))
        print(f"  Paper-Trading Action:     {act}")
        if pt.get("reason"):
            print(f"  Reason:                   {pt['reason']}")
        if report.policy_bundle_hash:
            print(f"  Policy Bundle Hash:       {report.policy_bundle_hash}")
        if report.model_hashes:
            print(f"  Model Hashes:             {report.model_hashes}")
        print(
            f"  Candidates / Decisions:   {report.candidates_count} candidates, "
            f"{report.decisions_count} decisions"
        )
        print(
            f"  New Fills / Exits:        {report.new_fills_count} fills, "
            f"{report.exits_count} exits"
        )
        print(f"  Active Positions:         {report.open_positions_count}")
        print(f"  Pending Orders:           {report.pending_orders_count}")
        print(f"  Cash Balance:             IDR {report.cash_balance_idr:,.2f}")
        print(f"  Current Total Equity:     IDR {report.current_equity_idr:,.2f}")
        print(f"  Realized Net PnL:         IDR {report.realized_net_pnl_idr:,.2f}")
        print(f"  Unrealized PnL:           IDR {report.unrealized_pnl_idr:,.2f}")
        print(f"  Max Drawdown:             {report.max_drawdown_pct * 100:.2f}%")

    if report.errors:
        print("-" * 80)
        print(f"ERRORS ENCOUNTERED ({len(report.errors)}):")
        for err in report.errors:
            print(f"  ! {err}")

    print("=" * 80)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    target_d = None
    if args.date:
        try:
            target_d = datetime.strptime(args.date.strip(), "%Y-%m-%d").date()
        except ValueError:
            sys.stderr.write(f"Invalid --date format '{args.date}', expected YYYY-MM-DD\n")
            return 1

    pipeline = DailyPipeline(
        db_url=args.db_url,
        artifacts_dir=args.artifacts_dir,
        reports_dir=args.reports_dir,
        provider_name=args.provider,
        min_ticker_coverage=args.min_coverage,
        allow_mock_fallback=args.allow_synthetic_fixture,
        dry_run=args.dry_run,
    )

    try:
        report = pipeline.run(
            target_date=target_d,
            skip_ingest=args.skip_ingest,
            ingest_mode=args.mode,
            lookback_days=args.lookback_days,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        sys.stderr.write(f"Pipeline execution fatal error: {exc}\n")
        return 1

    print_report_summary(report)

    if report.overall_status == "FAILED":
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
