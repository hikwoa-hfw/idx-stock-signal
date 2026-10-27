"""Unit and integration tests for daily market-data-to-paper-trading pipeline.

Verifies:
1. Real-provider failure fails closed.
2. Empty provider results do not invoke a mock fallback.
3. Partial ticker coverage blocks scoring.
4. Data ingestion followed by feature generation saves the expected rows.
5. Next daily run can reuse the persisted database.
6. Reprocessing the same session does not duplicate features, decisions, fills, exits,
   or equity entries.
7. Missing or stale data prevents scoring.
8. Scoring artifacts and policy hashes are unchanged.
9. Unapproved or invalid prospective dates are rejected.
10. Paper-trading state and cash remain intact on failure.
11. A complete synthetic fixture can traverse every pipeline stage successfully.
12. Failure in any stage is recorded and prevents downstream stages from executing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from python.common.types import DailyBar
from python.data.repository import DailyBarRepository
from python.experiments.paper_trading import (
    PaperTradingEngine,
)
from python.pipeline.daily_pipeline import DailyPipeline
from scripts.run_daily_pipeline import main as cli_main


class DummyEstimator:
    def predict(self, X: Any) -> np.ndarray:
        return np.full(len(X), 0.05)

    def predict_proba(self, X: Any) -> np.ndarray:
        n = len(X)
        return np.column_stack([np.full(n, 0.4), np.full(n, 0.6)])


def _populate_test_artifacts(artifacts_dir: Path) -> None:
    models_dir = artifacts_dir / "research_models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for model_file in (
        "lgb_regressor_h15_variant_b.joblib",
        "lgb_full_classifier_h15_variant_b.joblib",
    ):
        joblib.dump(DummyEstimator(), models_dir / model_file)


def _init_test_database(db_path: Path, session_dates: list[date], tickers: list[str]) -> None:
    repo = DailyBarRepository(database_url=f"sqlite:///{db_path.as_posix()}")
    bars: list[DailyBar] = []
    base_price = 1000.0

    # Create historical sequence
    for d in session_dates:
        for i, t in enumerate(tickers):
            p = base_price + (i * 100) + (d.day % 10)
            bars.append(
                DailyBar(
                    ticker=t,
                    date=d,
                    open=p,
                    high=p + 20.0,
                    low=p - 10.0,
                    close=p + 10.0,
                    volume=100000.0,
                    value=p * 100000.0,
                    provider="test",
                    interval="1d",
                )
            )
    repo.save_bars_detailed(bars, default_provider="test")


def test_real_provider_failure_fails_closed(tmp_path: Path) -> None:
    """Stage A fails closed when an invalid or failing provider is requested."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        provider_name="non_existent_provider_xyz",
        allow_mock_fallback=False,
    )

    report = pipeline.run(skip_ingest=False)
    assert report.overall_status == "FAILED"
    assert "stage_a_ingestion" in report.stages
    assert report.stages["stage_a_ingestion"]["status"] == "FAILED"
    assert "stage_b_data_validation" not in report.stages
    assert len(report.errors) > 0


def test_empty_provider_results_fails_closed_no_mock_fallback(tmp_path: Path) -> None:
    """Mock fallback is strictly prohibited in operational mode."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    # With allow_mock_fallback=False, selecting mock or empty csv must fail closed
    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        provider_name="mock",
        allow_mock_fallback=False,
    )

    report = pipeline.run(skip_ingest=False)
    assert report.overall_status == "FAILED"
    assert report.stages["stage_a_ingestion"]["status"] == "FAILED"
    assert "forbidden" in report.stages["stage_a_ingestion"]["error"].lower()


def test_partial_ticker_coverage_blocks_scoring(tmp_path: Path) -> None:
    """If session has insufficient ticker coverage, Stage B halts pipeline."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    # Insert only 1 ticker for a session
    sess_date = date(2026, 10, 16)
    _init_test_database(db_path, [sess_date], ["BBCA"])

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )
    assert pipeline.min_ticker_coverage == 0.80

    report = pipeline.run(skip_ingest=True, target_date=sess_date)
    assert report.overall_status == "FAILED"
    assert report.stages["stage_b_data_validation"]["status"] == "FAILED"
    assert "below threshold" in report.stages["stage_b_data_validation"]["error"].lower()
    # Downstream stages must not execute
    assert "stage_c_feature_generation" not in report.stages
    assert "stage_e_paper_trading" not in report.stages


def test_data_ingestion_and_feature_generation_saves_expected_rows(tmp_path: Path) -> None:
    """Feature generation persists rows to database with direct verification."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    # Create sequence of 30 trading dates for 5 tickers
    start = date(2026, 9, 1)
    dates = [
        start + timedelta(days=i) for i in range(35) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    target_sess = dates[-1]

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    report = pipeline.run(skip_ingest=True, target_date=target_sess)
    assert report.stages["stage_c_feature_generation"]["status"] == "SUCCESS"
    feat_summary = report.stages["stage_c_feature_generation"]["details"]
    assert feat_summary["features_persisted_count"] == len(tickers)
    assert feat_summary["db_verified_count"] == len(tickers)

    # Directly inspect database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cnt = cur.execute(
        "SELECT COUNT(*) FROM features_daily WHERE date = ?;",
        (str(target_sess),),
    ).fetchone()[0]
    conn.close()
    assert cnt == len(tickers)


def test_next_daily_run_reuses_persisted_database(tmp_path: Path) -> None:
    """Subsequent daily runs safely reuse existing persisted database records."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    start = date(2026, 9, 1)
    dates = [
        start + timedelta(days=i) for i in range(35) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    # Run 1: process session
    rep1 = pipeline.run(skip_ingest=True, target_date=dates[-1])
    assert rep1.stages["stage_c_feature_generation"]["status"] == "SUCCESS"

    # Run 2: re-run on same database
    rep2 = pipeline.run(skip_ingest=True, target_date=dates[-1])
    assert rep2.stages["stage_b_data_validation"]["status"] == "SUCCESS"
    assert rep2.stages["stage_c_feature_generation"]["status"] == "SUCCESS"
    assert rep2.stages["stage_c_feature_generation"]["details"]["db_verified_count"] == len(tickers)


def test_reprocessing_same_session_is_idempotent(tmp_path: Path) -> None:
    """Reprocessing the same session produces zero duplicate features, decisions,
    or equity entries."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    start = date(2025, 10, 1)
    dates = [
        start + timedelta(days=i) for i in range(380) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    target_sess = dates[-1]

    # Set up approved state with cutoff before target_sess
    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    engine.approve_observation(
        cutoff_date=dates[-2],
        effective_cutoff=dates[-2],
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    # First run on target_sess
    r1 = pipeline.run(skip_ingest=True, target_date=target_sess)
    assert r1.stages["stage_e_paper_trading"]["status"] == "SUCCESS"

    state1 = engine.load_state()
    cash1 = state1["cash"]
    processed1 = list(state1["processed_dates"])

    # Second run on same target_sess
    r2 = pipeline.run(skip_ingest=True, target_date=target_sess)
    assert r2.stages["stage_e_paper_trading"]["status"] == "SUCCESS"

    state2 = engine.load_state()
    assert state2["cash"] == cash1
    assert state2["processed_dates"] == processed1
    assert (
        r2.stages["stage_e_paper_trading"]["details"]["step_result"]["status"]
        == "ALREADY_PROCESSED"
    )

    # Verify features table has no duplicate rows
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    total_feat = cur.execute(
        "SELECT COUNT(*) FROM features_daily WHERE date = ?;", (str(target_sess),)
    ).fetchone()[0]
    conn.close()
    assert total_feat == len(tickers)


def test_missing_or_stale_data_prevents_scoring(tmp_path: Path) -> None:
    """Invalid OHLC relationships or empty data halt pipeline at Stage B."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    sess = date(2026, 10, 16)
    repo = DailyBarRepository(database_url=f"sqlite:///{db_path.as_posix()}")
    # Corrupt bar: high < low
    corrupt_bar = DailyBar(
        ticker="BBCA",
        date=sess,
        open=1000.0,
        high=800.0,  # Invalid: high < open and high < low
        low=900.0,
        close=950.0,
        volume=100.0,
    )
    repo.save_bars([corrupt_bar])

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    report = pipeline.run(skip_ingest=True, target_date=sess)
    assert report.overall_status == "FAILED"
    assert report.stages["stage_b_data_validation"]["status"] == "FAILED"
    assert "stage_c_feature_generation" not in report.stages
    assert "stage_e_paper_trading" not in report.stages


def test_scoring_artifacts_and_policy_hashes_unchanged(tmp_path: Path) -> None:
    """Pipeline execution preserves policy bundle hash and artifact integrity."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    expected_hash = engine.frozen_bundle.config_sha256
    assert expected_hash == "8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71"

    sess = date(2026, 10, 16)
    _init_test_database(db_path, [sess], ["BBCA", "BBRI"])

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )
    pipeline.run(skip_ingest=True, target_date=sess)

    # Verify hash remains identical
    state = engine.load_state()
    assert state["policy_bundle_hash"] == expected_hash


def test_unapproved_or_invalid_prospective_dates_rejected(tmp_path: Path) -> None:
    """Pre-approval or historical sessions are safely skipped and cannot run prospective scoring."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    start = date(2025, 10, 1)
    dates = [
        start + timedelta(days=i) for i in range(380) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    sess = dates[-1]

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    # Approval recorded with cutoff in future (after session dates[-1])
    engine.approve_observation(
        cutoff_date=sess + timedelta(days=5),
        effective_cutoff=sess + timedelta(days=5),
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    report = pipeline.run(skip_ingest=True, target_date=sess)
    assert report.stages["stage_e_paper_trading"]["status"] == "SKIPPED_PRE_APPROVAL_SESSION"
    assert report.overall_status == "SKIPPED_PRE_APPROVAL_SESSION"
    assert (
        "awaiting the first completed session strictly after cutoff"
        in report.stages["stage_e_paper_trading"]["details"]["reason"]
    )


def test_paper_trading_state_and_cash_intact_on_failure(tmp_path: Path) -> None:
    """Upstream pipeline failure leaves paper-trading capital and positions intact."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    initial_cash = engine.load_state()["cash"]

    # Run on empty DB -> fails at Stage B
    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )

    report = pipeline.run(skip_ingest=True, target_date=date(2026, 10, 16))
    assert report.overall_status == "FAILED"

    # State and cash must be pristine
    after_cash = engine.load_state()["cash"]
    assert after_cash == initial_cash
    assert len(engine.load_state()["processed_dates"]) == 0


def test_complete_synthetic_fixture_traverses_every_pipeline_stage(tmp_path: Path) -> None:
    """A complete synthetic fixture traverses Stage A through Stage F successfully."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    # Setup history up to 2026-10-21, and target session on 2026-10-22
    start = date(2025, 10, 1)
    dates = [
        start + timedelta(days=i) for i in range(380) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    cutoff_d = dates[-2]
    target_d = dates[-1]

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    engine.approve_observation(
        cutoff_date=cutoff_d,
        effective_cutoff=cutoff_d,
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
        dry_run=False,
    )

    report = pipeline.run(skip_ingest=True, target_date=target_d)
    assert report.overall_status == "SUCCESS"
    assert report.stages["stage_b_data_validation"]["status"] == "SUCCESS"
    assert report.stages["stage_c_feature_generation"]["status"] == "SUCCESS"
    assert report.stages["stage_d_feature_readiness"]["status"] == "SUCCESS"
    assert report.stages["stage_e_paper_trading"]["status"] == "SUCCESS"

    # Check report files written
    latest_rep = reports_dir / "latest_pipeline_run.json"
    assert latest_rep.is_file()
    with open(latest_rep, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["overall_status"] == "SUCCESS"
    assert data["run_id"] == report.run_id


def test_failure_in_any_stage_recorded_in_report_and_blocks_downstream(tmp_path: Path) -> None:
    """Stage failure is preserved in run report JSON and halts execution."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )

    # Empty DB triggers failure in Stage B
    report = pipeline.run(skip_ingest=True, target_date=date(2026, 10, 16))
    assert report.overall_status == "FAILED"
    assert len(report.errors) > 0

    latest_rep = reports_dir / "latest_pipeline_run.json"
    assert latest_rep.is_file()
    with open(latest_rep, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["overall_status"] == "FAILED"
    assert "stage_c_feature_generation" not in saved_data["stages"]


def test_cli_runner_execution(tmp_path: Path) -> None:
    """CLI entry point executes cleanly and returns exit code 0."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    start = date(2025, 10, 1)
    dates = [
        start + timedelta(days=i) for i in range(380) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)
    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    engine.approve_observation(
        cutoff_date=dates[-2],
        effective_cutoff=dates[-2],
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )

    ret = cli_main(
        [
            "--skip-ingest",
            "--date",
            str(dates[-1]),
            "--db-url",
            f"sqlite:///{db_path.as_posix()}",
            "--artifacts-dir",
            str(artifacts_dir),
            "--reports-dir",
            str(reports_dir),
            "--min-coverage",
            "0.01",
            "--dry-run",
        ]
    )
    assert ret == 0


def test_stage_b_reconciliation_fails_on_missing_db_rows(tmp_path: Path) -> None:
    """Stage B fails closed if ingestion reported inserted rows that are missing in daily_bars."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    sess = date(2026, 10, 16)
    _init_test_database(db_path, [sess], ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"])

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    fake_ingest = {
        "run_id": "run_phantom_uncommitted",
        "rows_inserted": 50,
    }
    stage_b = pipeline._execute_stage_b(target_date=sess, latest_ingest_details=fake_ingest)
    assert stage_b.status == "FAILED"
    assert "Database reconciliation failed" in stage_b.error


def test_stage_b_skips_when_session_already_processed_in_daily_mode(tmp_path: Path) -> None:
    """In daily mode (target_date=None), if latest session is already processed and 0 rows
    inserted, skip safely.
    """
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    sess = date(2026, 10, 22)
    _init_test_database(db_path, [sess], ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"])

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    engine.approve_observation(
        cutoff_date=date(2026, 10, 21),
        effective_cutoff=date(2026, 10, 21),
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )
    # Mark session as already processed
    state = engine.load_state()
    state["processed_dates"] = [str(sess)]
    state_file = artifacts_dir / "paper_trading_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f)

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
    )

    stage_b = pipeline._execute_stage_b(
        target_date=None,
        latest_ingest_details={"rows_inserted": 0},
    )
    assert stage_b.status == "SKIPPED_NO_NEW_SESSION"
    assert "already fully processed" in stage_b.details["reason"]


def test_feature_readiness_fails_if_zero_candidates_have_complete_history(tmp_path: Path) -> None:
    """Stage D fails closed if 0 candidates have complete 30-feature history."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    sess = date(2026, 10, 16)
    _init_test_database(db_path, [sess], ["BBCA"])

    # Insert feature row with NaNs across indicators
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS features_daily (
            ticker TEXT, date TEXT, feature_version TEXT,
            return_1d REAL, return_3d REAL, return_5d REAL, return_10d REAL, return_20d REAL,
            ema20 REAL, ema50 REAL, ema200 REAL,
            close_vs_ema20 REAL, close_vs_ema50 REAL, ema20_vs_ema50 REAL, ema50_vs_ema200 REAL,
            rsi14 REAL, rsi_change_5d REAL,
            atr14 REAL, atr_pct REAL, realized_vol_5d REAL,
            realized_vol_20d REAL, daily_range_pct REAL,
            volume_ratio_5d REAL, volume_ratio_20d REAL, value_ratio_20d REAL,
            rel_strength_ihsg_20d REAL, rel_strength_sector_20d REAL,
            ihsg_return_5d REAL, ihsg_return_20d REAL, ihsg_vs_ema20 REAL, ihsg_vs_ema50 REAL,
            market_breadth REAL, market_volatility REAL,
            created_at TEXT
        );
        """
    )
    cur.execute(
        """
        INSERT INTO features_daily (
            ticker, date, feature_version,
            ihsg_return_5d, ihsg_return_20d, ihsg_vs_ema20, ihsg_vs_ema50,
            market_breadth, market_volatility,
            ema200, return_1d
        )
        VALUES ('BBCA', '2026-10-16', 'v1.0.0', 0.01, 0.02, 0.01, 0.01, 0.6, 0.02, NULL, 0.01);
        """
    )
    conn.commit()
    conn.close()

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )

    stage_d = pipeline._execute_stage_d(session_date=sess)
    assert stage_d.status == "FAILED"
    assert "0 candidates have complete" in stage_d.error


def test_feature_readiness_fails_if_features_mismatch_price_bars(tmp_path: Path) -> None:
    """Stage D fails closed if a feature ticker has no corresponding price bar in daily_bars."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    sess = date(2026, 10, 16)
    _init_test_database(db_path, [sess], ["BBCA"])

    # Insert feature for UNKNOWN_TICKER which has no bar
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS features_daily (
            ticker TEXT, date TEXT, feature_version TEXT,
            return_1d REAL, return_3d REAL, return_5d REAL, return_10d REAL, return_20d REAL,
            ema20 REAL, ema50 REAL, ema200 REAL,
            close_vs_ema20 REAL, close_vs_ema50 REAL, ema20_vs_ema50 REAL, ema50_vs_ema200 REAL,
            rsi14 REAL, rsi_change_5d REAL,
            atr14 REAL, atr_pct REAL, realized_vol_5d REAL,
            realized_vol_20d REAL, daily_range_pct REAL,
            volume_ratio_5d REAL, volume_ratio_20d REAL, value_ratio_20d REAL,
            rel_strength_ihsg_20d REAL, rel_strength_sector_20d REAL,
            ihsg_return_5d REAL, ihsg_return_20d REAL, ihsg_vs_ema20 REAL, ihsg_vs_ema50 REAL,
            market_breadth REAL, market_volatility REAL,
            created_at TEXT
        );
        """
    )
    cur.execute(
        """
        INSERT INTO features_daily (ticker, date, feature_version, return_1d)
        VALUES ('UNKNOWN_TICKER', '2026-10-16', 'v1.0.0', 0.01);
        """
    )
    conn.commit()
    conn.close()

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )

    stage_d = pipeline._execute_stage_d(session_date=sess)
    assert stage_d.status == "FAILED"
    assert "Feature records do not match stored price bars" in stage_d.error


def test_report_contains_all_required_operational_metrics(tmp_path: Path) -> None:
    """Run summary report JSON includes all required operational metrics and hashes."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    start = date(2025, 10, 1)
    dates = [
        start + timedelta(days=i) for i in range(380) if (start + timedelta(days=i)).weekday() < 5
    ]
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    _init_test_database(db_path, dates, tickers)

    sess = dates[-1]

    engine = PaperTradingEngine(db_path=str(db_path), artifacts_dir=str(artifacts_dir))
    engine.approve_observation(
        cutoff_date=dates[-2],
        effective_cutoff=dates[-2],
        approval_timestamp=datetime.now(timezone.utc).isoformat(),
        base_dir=artifacts_dir.parent,
    )

    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=0.01,
        dry_run=True,
    )

    report = pipeline.run(skip_ingest=True, target_date=sess)
    assert report.policy_bundle_hash != ""
    assert report.feature_schema_hash != ""
    assert "LOW_PRICE" in report.model_hashes
    assert "HIGHER_PRICE" in report.model_hashes
    assert report.cash_balance_idr == 100000000.0
    assert report.current_equity_idr == 100000000.0

    # Verify JSON file has keys
    latest_file = reports_dir / "latest_pipeline_run.json"
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "policy_bundle_hash" in data
    assert "feature_schema_hash" in data
    assert "model_hashes" in data
    assert "cash_balance_idr" in data
    assert "current_equity_idr" in data


def test_get_ingestion_runs_repository_method(tmp_path: Path) -> None:
    """DailyBarRepository.get_ingestion_runs retrieves runs in descending order."""
    repo = DailyBarRepository(database_url=f"sqlite:///{tmp_path.as_posix()}/test.db")
    runs = repo.get_ingestion_runs(limit=5)
    assert isinstance(runs, list)
    assert len(runs) == 0


def test_default_ticker_coverage_threshold_and_cli_default() -> None:
    """Default minimum ticker coverage threshold is 0.80 in both pipeline and CLI."""
    from scripts.run_daily_pipeline import parse_args

    pipeline = DailyPipeline()
    assert pipeline.min_ticker_coverage == 0.80

    args = parse_args([])
    assert args.min_coverage == 0.80


def test_ticker_coverage_below_80_percent_blocks_downstream_scoring(
    tmp_path: Path, monkeypatch
) -> None:
    """Coverage below 80% default threshold blocks downstream scoring."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    mock_universe = [f"TCK{i:02d}" for i in range(10)]
    monkeypatch.setattr("python.pipeline.daily_pipeline.load_universe", lambda: mock_universe)

    # Ingest 7 out of 10 tickers (70% coverage < 80% threshold)
    sess_date = date(2026, 10, 16)
    _init_test_database(db_path, [sess_date], mock_universe[:7])

    # Run pipeline with DEFAULT min_ticker_coverage (0.80)
    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )
    assert pipeline.min_ticker_coverage == 0.80

    report = pipeline.run(skip_ingest=True, target_date=sess_date)
    assert report.overall_status == "FAILED"
    stage_b = report.stages.get("stage_b_data_validation")
    assert stage_b is not None
    assert stage_b["status"] == "FAILED"
    assert "below threshold 80.0%" in stage_b["error"]
    assert stage_b["details"]["coverage_pct"] == 0.70

    # Downstream scoring stages must NOT execute
    assert "stage_c_feature_generation" not in report.stages
    assert "stage_d_feature_readiness" not in report.stages
    assert "stage_e_paper_trading" not in report.stages


def test_ticker_coverage_meeting_80_percent_passes_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """Coverage meeting or exceeding 80% threshold passes Stage B validation gate."""
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _populate_test_artifacts(artifacts_dir)

    mock_universe = [f"TCK{i:02d}" for i in range(10)]
    monkeypatch.setattr("python.pipeline.daily_pipeline.load_universe", lambda: mock_universe)

    # Ingest 8 out of 10 tickers (80% coverage == 80% threshold)
    sess_date = date(2026, 10, 16)
    _init_test_database(db_path, [sess_date], mock_universe[:8])

    # Run pipeline with DEFAULT min_ticker_coverage (0.80)
    pipeline = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
    )
    assert pipeline.min_ticker_coverage == 0.80

    stage_b = pipeline._execute_stage_b(target_date=sess_date)
    assert stage_b.status == "SUCCESS"
    assert stage_b.details["coverage_pct"] == 0.80
    assert stage_b.details["distinct_tickers_count"] == 8
    assert stage_b.details["active_universe_count"] == 10


def test_ticker_coverage_cli_override(tmp_path: Path, monkeypatch) -> None:
    """Explicit CLI override of --min-coverage modifies gate threshold as intended."""
    from scripts.run_daily_pipeline import parse_args

    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = tmp_path / "reports"

    mock_universe = [f"TCK{i:02d}" for i in range(10)]
    monkeypatch.setattr("python.pipeline.daily_pipeline.load_universe", lambda: mock_universe)

    sess_date = date(2026, 10, 16)
    _init_test_database(db_path, [sess_date], mock_universe[:7])

    # 1. Override to 0.70 allows 70% coverage to pass Stage B
    args_70 = parse_args(["--min-coverage", "0.70"])
    assert args_70.min_coverage == 0.70

    pipeline_70 = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=args_70.min_coverage,
    )
    stage_b_70 = pipeline_70._execute_stage_b(target_date=sess_date)
    assert stage_b_70.status == "SUCCESS"
    assert stage_b_70.details["coverage_pct"] == 0.70

    # 2. Override to 0.90 causes 80% coverage to fail Stage B
    _init_test_database(db_path, [sess_date], mock_universe[:8])
    args_90 = parse_args(["--min-coverage", "0.90"])
    assert args_90.min_coverage == 0.90

    pipeline_90 = DailyPipeline(
        db_url=f"sqlite:///{db_path.as_posix()}",
        artifacts_dir=artifacts_dir,
        reports_dir=reports_dir,
        min_ticker_coverage=args_90.min_coverage,
    )
    stage_b_90 = pipeline_90._execute_stage_b(target_date=sess_date)
    assert stage_b_90.status == "FAILED"
    assert "below threshold 90.0%" in stage_b_90.error


def test_run_ingest_incremental_bounded_lookback(tmp_path: Path, monkeypatch) -> None:
    from scripts.ingest_daily import run_ingest

    db_path = tmp_path / "ingest_test.db"
    captured_calls = []

    class MockYFProvider:
        max_workers = 4

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def get_universe(self):
            return ["BBCA", "UNSEEN"]

        def get_daily_bars_batch(self, chunk, start_date=None, end_date=None):
            captured_calls.append((chunk, start_date, end_date))
            return {
                t: [
                    DailyBar(
                        ticker=t,
                        date=date(2026, 10, 26),
                        open=1000.0,
                        high=1050.0,
                        low=990.0,
                        close=1020.0,
                        volume=100000.0,
                        value=102000000.0,
                        provider="yfinance",
                        provider_symbol=f"{t}.JK",
                        interval="1d",
                    )
                ]
                for t in chunk
            }

    monkeypatch.setattr("scripts.ingest_daily.YFinanceMarketDataProvider", MockYFProvider)

    repo = DailyBarRepository(database_url=f"sqlite:///{db_path.as_posix()}")
    repo.save_bars(
        [
            DailyBar(
                ticker="BBCA",
                date=date(2020, 1, 1),
                open=800.0,
                high=810.0,
                low=790.0,
                close=805.0,
                volume=50000.0,
                value=40250000.0,
                provider="yfinance",
                provider_symbol="BBCA.JK",
                interval="1d",
            )
        ]
    )

    total = run_ingest(
        provider_name="yfinance",
        tickers=["BBCA", "UNSEEN"],
        db_url=f"sqlite:///{db_path.as_posix()}",
        mode="incremental",
        lookback_days=30,
        batch_size=25,
        max_workers=2,
    )
    assert total == 2
    assert len(captured_calls) == 1
    chunk, start_d, end_d = captured_calls[0]
    assert start_d >= date.today() - timedelta(days=7)
    assert start_d > date(2020, 1, 1)


