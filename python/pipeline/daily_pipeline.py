"""Daily End-to-End Orchestration Pipeline for BEI Stock Signals.

Orchestrates the operational workflow:
Stage A: Market data ingestion (incremental, fail-closed, real provider).
Stage B: Data validation & freshness gate (persisted DB checks, coverage, calendar).
Stage C: Feature generation & persistence (sufficient lookback, idempotent save).
Stage D: Feature readiness gate (30-feature schema, NaN/Inf check, point-in-time).
Stage E: Research paper-trading lifecycle (approval check, dynamic date, execution).
Stage F: Post-run verification & operational report (JSON run report, status log).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from python.common.types import DailyBar, FeatureRecord
from python.config.settings import PROJECT_ROOT, settings
from python.data.provider import load_universe
from python.data.repository import DailyBarRepository
from python.data.validation import validate_daily_bars
from python.experiments.paper_trading import (
    FEATURE_SCHEMA_30,
    PaperTradingEngine,
)
from python.features.engine import FEATURE_VERSION, FeatureEngine
from python.features.repository import FeatureRepository
from scripts.ingest_daily import run_ingest

logger = logging.getLogger("daily_pipeline")


def _get_git_commit_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


@dataclass
class StageResult:
    stage_name: str
    status: str  # SUCCESS, SKIPPED, FAILED
    duration_seconds: float
    details: dict[str, Any]
    error: Optional[str] = None


@dataclass
class PipelineRunReport:
    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    git_commit_sha: str
    configured_provider: str
    overall_status: str  # SUCCESS, SKIPPED_NO_NEW_SESSION, SKIPPED_PRE_APPROVAL_SESSION, FAILED
    stages: dict[str, dict[str, Any]]
    errors: list[str]
    ingestion_summary: dict[str, Any]
    validation_summary: dict[str, Any]
    feature_summary: dict[str, Any]
    feature_readiness_summary: dict[str, Any]
    paper_trading_summary: dict[str, Any]
    feature_schema_hash: str = ""
    feature_version: str = ""
    model_hashes: dict[str, str] = field(default_factory=dict)
    policy_bundle_hash: str = ""
    decision_date: Optional[str] = None
    candidates_count: int = 0
    decisions_count: int = 0
    pending_orders_count: int = 0
    new_fills_count: int = 0
    exits_count: int = 0
    open_positions_count: int = 0
    cash_balance_idr: float = 0.0
    realized_net_pnl_idr: float = 0.0
    unrealized_pnl_idr: float = 0.0
    current_equity_idr: float = 0.0
    max_drawdown_pct: float = 0.0


class DailyPipeline:
    def __init__(
        self,
        db_url: Optional[str] = None,
        artifacts_dir: Optional[Path | str] = None,
        reports_dir: Optional[Path | str] = None,
        provider_name: Optional[str] = None,
        min_ticker_coverage: float = 0.80,
        allow_mock_fallback: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.db_url = db_url or settings.database_url
        self.artifacts_dir = Path(artifacts_dir or (PROJECT_ROOT / "artifacts" / "phase_11f"))
        self.reports_dir = Path(reports_dir or (PROJECT_ROOT / "artifacts" / "pipeline_runs"))
        self.provider_name = (provider_name or settings.market_data_provider or "yfinance").lower()
        self.min_ticker_coverage = min_ticker_coverage
        self.allow_mock_fallback = allow_mock_fallback
        self.dry_run = dry_run

        self.bar_repo = DailyBarRepository(database_url=self.db_url)
        self.feature_repo = FeatureRepository(database_url=self.db_url)

    def _resolve_raw_db_path(self) -> str:
        return self.bar_repo.db_path

    def run(
        self,
        target_date: Optional[date] = None,
        skip_ingest: bool = False,
        ingest_mode: str = "incremental",
        lookback_days: int = 30,
        batch_size: int = 25,
    ) -> PipelineRunReport:
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"pipeline_{ts_str}_{uuid.uuid4().hex[:6]}"
        started_at = datetime.now(timezone.utc)
        git_sha = _get_git_commit_sha()
        stages: dict[str, StageResult] = {}
        errors: list[str] = []

        overall_status = "SUCCESS"

        # Stage A: Ingestion
        t0 = datetime.now(timezone.utc)
        if not skip_ingest:
            try:
                stage_a = self._execute_stage_a(
                    mode=ingest_mode,
                    lookback_days=lookback_days,
                    batch_size=batch_size,
                    target_date=target_date,
                )
                stages["stage_a_ingestion"] = stage_a
                if stage_a.status == "FAILED":
                    errors.append(f"Stage A failed: {stage_a.error}")
                    overall_status = "FAILED"
            except Exception as e:
                err_msg = f"Stage A unhandled exception: {e}"
                errors.append(err_msg)
                stages["stage_a_ingestion"] = StageResult(
                    stage_name="Stage A: Ingestion",
                    status="FAILED",
                    duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                    details={},
                    error=str(e),
                )
                overall_status = "FAILED"
        else:
            stages["stage_a_ingestion"] = StageResult(
                stage_name="Stage A: Ingestion",
                status="SKIPPED",
                duration_seconds=0.0,
                details={"reason": "User requested --skip-ingest"},
            )

        # Halt if Stage A failed
        if overall_status == "FAILED":
            return self._finalize_report(
                run_id=run_id,
                started_at=started_at,
                overall_status=overall_status,
                stages=stages,
                errors=errors,
                git_sha=git_sha,
            )

        # Stage B: Data Validation & Freshness Gate
        t0 = datetime.now(timezone.utc)
        ingest_det = stages.get("stage_a_ingestion", StageResult("", "SKIPPED", 0, {})).details
        try:
            stage_b = self._execute_stage_b(
                target_date=target_date, latest_ingest_details=ingest_det
            )
            stages["stage_b_data_validation"] = stage_b
            if stage_b.status == "FAILED":
                errors.append(f"Stage B failed: {stage_b.error}")
                overall_status = "FAILED"
            elif stage_b.status == "SKIPPED_NO_NEW_SESSION":
                overall_status = "SKIPPED_NO_NEW_SESSION"
        except Exception as e:
            err_msg = f"Stage B unhandled exception: {e}"
            errors.append(err_msg)
            stages["stage_b_data_validation"] = StageResult(
                stage_name="Stage B: Data Validation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=str(e),
            )
            overall_status = "FAILED"

        # Halt if Stage B failed or skipped due to no new session
        if overall_status in ("FAILED", "SKIPPED_NO_NEW_SESSION"):
            return self._finalize_report(
                run_id=run_id,
                started_at=started_at,
                overall_status=overall_status,
                stages=stages,
                errors=errors,
                git_sha=git_sha,
            )

        resolved_session = stages["stage_b_data_validation"].details["latest_completed_session"]
        session_d = pd.to_datetime(resolved_session).date()

        # Stage C: Feature Generation & Persistence
        t0 = datetime.now(timezone.utc)
        try:
            stage_c = self._execute_stage_c(session_date=session_d)
            stages["stage_c_feature_generation"] = stage_c
            if stage_c.status == "FAILED":
                errors.append(f"Stage C failed: {stage_c.error}")
                overall_status = "FAILED"
        except Exception as e:
            err_msg = f"Stage C unhandled exception: {e}"
            errors.append(err_msg)
            stages["stage_c_feature_generation"] = StageResult(
                stage_name="Stage C: Feature Generation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=str(e),
            )
            overall_status = "FAILED"

        if overall_status == "FAILED":
            return self._finalize_report(
                run_id=run_id,
                started_at=started_at,
                overall_status=overall_status,
                stages=stages,
                errors=errors,
                git_sha=git_sha,
            )

        # Stage D: Feature Readiness Gate
        t0 = datetime.now(timezone.utc)
        try:
            stage_d = self._execute_stage_d(session_date=session_d)
            stages["stage_d_feature_readiness"] = stage_d
            if stage_d.status == "FAILED":
                errors.append(f"Stage D failed: {stage_d.error}")
                overall_status = "FAILED"
        except Exception as e:
            err_msg = f"Stage D unhandled exception: {e}"
            errors.append(err_msg)
            stages["stage_d_feature_readiness"] = StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=str(e),
            )
            overall_status = "FAILED"

        if overall_status == "FAILED":
            return self._finalize_report(
                run_id=run_id,
                started_at=started_at,
                overall_status=overall_status,
                stages=stages,
                errors=errors,
                git_sha=git_sha,
            )

        # Stage E: Paper-Trading Lifecycle
        t0 = datetime.now(timezone.utc)
        try:
            stage_e = self._execute_stage_e(session_date=session_d)
            stages["stage_e_paper_trading"] = stage_e
            if stage_e.status == "FAILED":
                errors.append(f"Stage E failed: {stage_e.error}")
                overall_status = "FAILED"
            elif stage_e.status == "SKIPPED_PRE_APPROVAL_SESSION":
                if overall_status == "SUCCESS":
                    overall_status = "SKIPPED_PRE_APPROVAL_SESSION"
        except Exception as e:
            err_msg = f"Stage E unhandled exception: {e}"
            errors.append(err_msg)
            stages["stage_e_paper_trading"] = StageResult(
                stage_name="Stage E: Paper Trading",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=str(e),
            )
            overall_status = "FAILED"

        return self._finalize_report(
            run_id=run_id,
            started_at=started_at,
            overall_status=overall_status,
            stages=stages,
            errors=errors,
            git_sha=git_sha,
        )

    def _execute_stage_a(
        self,
        mode: str,
        lookback_days: int,
        batch_size: int,
        target_date: Optional[date] = None,
    ) -> StageResult:
        t0 = datetime.now(timezone.utc)
        universe = load_universe()

        # Operational rule: fail-closed if mock requested in production path without permission
        if self.provider_name in ("mock", "synthetic") and not self.allow_mock_fallback:
            return StageResult(
                stage_name="Stage A: Ingestion",
                status="FAILED",
                duration_seconds=0.0,
                details={"provider": self.provider_name},
                error="Mock/synthetic market data provider forbidden in operational mode.",
            )

        # Run ingestion
        total_saved = run_ingest(
            provider_name=self.provider_name,
            tickers=universe,
            db_url=self.db_url,
            mode=mode,
            end_date=target_date,
            lookback_days=lookback_days,
            batch_size=batch_size,
            allow_mock_fallback=self.allow_mock_fallback,
        )

        # Ingestion run summary from audit table
        runs = self.bar_repo.get_ingestion_runs(limit=1)
        latest_run = runs[0] if runs else None

        details: dict[str, Any] = {
            "provider": self.provider_name,
            "mode": mode,
            "requested_tickers_count": len(universe),
            "rows_saved": total_saved,
            "run_id": latest_run.id if latest_run else None,
            "run_status": latest_run.status if latest_run else "UNKNOWN",
            "tickers_succeeded": latest_run.tickers_succeeded if latest_run else 0,
            "tickers_partial": latest_run.tickers_partial if latest_run else 0,
            "tickers_failed": latest_run.tickers_failed if latest_run else 0,
            "rows_inserted": latest_run.rows_inserted if latest_run else 0,
            "rows_updated": latest_run.rows_updated if latest_run else 0,
            "rows_unchanged": latest_run.rows_unchanged if latest_run else 0,
            "rows_rejected": latest_run.rows_rejected if latest_run else 0,
        }

        # Check latest bar date in DB
        db_path = self._resolve_raw_db_path()
        conn = sqlite3.connect(db_path)
        try:
            max_d_row = conn.execute("SELECT MAX(date) FROM daily_bars;").fetchone()
            latest_bar_date = max_d_row[0] if max_d_row and max_d_row[0] else None
        finally:
            conn.close()

        details["latest_bar_date"] = latest_bar_date

        # Check market candle completeness
        wib_now = datetime.now(timezone(timedelta(hours=7)))
        if latest_bar_date == str(wib_now.date()):
            # If date is today, check if closing auction is complete (16:15 WIB)
            is_closed = wib_now.hour > 16 or (wib_now.hour == 16 and wib_now.minute >= 15)
            if not is_closed:
                details["session_complete_warning"] = (
                    f"Today's candle ({latest_bar_date}) is ingested before 16:15 WIB closing. "
                    "Session may be incomplete."
                )

        status = "SUCCESS" if (latest_run and latest_run.status != "FAILED") else "FAILED"
        err = latest_run.error_summary if (latest_run and latest_run.status == "FAILED") else None

        return StageResult(
            stage_name="Stage A: Ingestion",
            status=status,
            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
            details=details,
            error=err,
        )

    def _execute_stage_b(
        self,
        target_date: Optional[date] = None,
        latest_ingest_details: Optional[dict[str, Any]] = None,
    ) -> StageResult:
        t0 = datetime.now(timezone.utc)
        db_path = self._resolve_raw_db_path()
        universe = load_universe()
        active_universe_count = len(universe)

        conn = sqlite3.connect(db_path)
        try:
            # Reconcile ingestion run with stored database rows
            if latest_ingest_details and latest_ingest_details.get("run_id"):
                ingest_run_id = latest_ingest_details["run_id"]
                rows_inserted = latest_ingest_details.get("rows_inserted", 0)
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM daily_bars WHERE ingestion_run_id = ?;",
                    (ingest_run_id,),
                )
                db_run_count = cur.fetchone()[0]
                if rows_inserted > 0 and db_run_count == 0:
                    return StageResult(
                        stage_name="Stage B: Data Validation",
                        status="FAILED",
                        duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                        details={
                            "ingestion_run_id": ingest_run_id,
                            "rows_inserted": rows_inserted,
                        },
                        error=(
                            f"Database reconciliation failed: run {ingest_run_id} reported "
                            f"{rows_inserted} rows inserted, but 0 found in daily_bars."
                        ),
                    )

            if target_date is not None:
                latest_session = str(target_date)
            else:
                max_row = conn.execute("SELECT MAX(date) FROM daily_bars;").fetchone()
                if not max_row or not max_row[0]:
                    return StageResult(
                        stage_name="Stage B: Data Validation",
                        status="FAILED",
                        duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                        details={},
                        error="No price bars exist in daily_bars database table.",
                    )
                latest_session = str(max_row[0])

                # Automated daily run check:
                # Check if this latest session has ALREADY been processed by paper trading
                # and no new rows were inserted by Stage A for a newer date
                try:
                    engine = PaperTradingEngine(
                        db_path=self._resolve_raw_db_path(),
                        artifacts_dir=str(self.artifacts_dir),
                    )
                    pt_state = engine.load_state()
                    processed_dates = {str(d) for d in pt_state.get("processed_dates", [])}
                    session_d_check = pd.to_datetime(latest_session).date()
                    rows_ins = (latest_ingest_details or {}).get("rows_inserted", 0)

                    if str(session_d_check) in processed_dates and rows_ins == 0:
                        details = {
                            "latest_completed_session": latest_session,
                            "session_weekday": session_d_check.strftime("%A"),
                            "action": "SKIPPED_NO_NEW_SESSION",
                            "reason": (
                                f"Latest session {latest_session} is already fully processed in "
                                "paper trading state, and 0 new bars were inserted today. "
                                "Safely skipping downstream feature generation and paper trading."
                            ),
                        }
                        return StageResult(
                            stage_name="Stage B: Data Validation",
                            status="SKIPPED_NO_NEW_SESSION",
                            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                            details=details,
                        )
                except Exception:
                    pass

            # Check session weekday
            session_d = pd.to_datetime(latest_session).date()
            if session_d.weekday() >= 5:
                return StageResult(
                    stage_name="Stage B: Data Validation",
                    status="FAILED",
                    duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                    details={"latest_completed_session": latest_session},
                    error=(
                        f"Session date {latest_session} falls on weekend "
                        f"(weekday={session_d.weekday()})."
                    ),
                )

            # Query bars for session
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ticker, date, open, high, low, close, volume, value,
                       adj_close, dividends, stock_splits, provider, provider_symbol,
                       ingestion_run_id
                FROM daily_bars
                WHERE date = ?;
                """,
                (latest_session,),
            )
            raw_rows = cur.fetchall()
        finally:
            conn.close()

        if not raw_rows:
            return StageResult(
                stage_name="Stage B: Data Validation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"latest_completed_session": latest_session},
                error=f"Zero price bars found for target session {latest_session}.",
            )

        bars = [
            DailyBar(
                ticker=r[0],
                date=pd.to_datetime(r[1]).date(),
                open=float(r[2]),
                high=float(r[3]),
                low=float(r[4]),
                close=float(r[5]),
                volume=float(r[6]),
                value=float(r[7]) if r[7] is not None else None,
                adj_close=float(r[8]) if r[8] is not None else None,
                dividends=float(r[9]) if r[9] is not None else 0.0,
                stock_splits=float(r[10]) if r[10] is not None else 0.0,
                provider=r[11] or "unknown",
                provider_symbol=r[12],
                ingestion_run_id=r[13],
            )
            for r in raw_rows
        ]

        # Individual bar integrity check
        validation_report = validate_daily_bars(bars, raise_on_error=False)
        if not validation_report.is_valid:
            err_summary = "; ".join(validation_report.errors[:5])
            return StageResult(
                stage_name="Stage B: Data Validation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={
                    "latest_completed_session": latest_session,
                    "bars_count": len(bars),
                    "error_count": validation_report.error_count,
                },
                error=f"Data integrity errors detected on {latest_session}: {err_summary}",
            )

        # Coverage check
        distinct_tickers = {
            b.ticker.strip().upper().removesuffix(".JK") for b in bars if b.close > 0
        }
        coverage_pct = len(distinct_tickers) / float(max(1, active_universe_count))

        has_bench_ticker = any(t in {"IHSG", "^JKSE", "COMPOSITE"} for t in distinct_tickers)
        has_composite = len(distinct_tickers) >= 5

        details = {
            "latest_completed_session": latest_session,
            "session_weekday": session_d.strftime("%A"),
            "active_universe_count": active_universe_count,
            "distinct_tickers_count": len(distinct_tickers),
            "coverage_pct": round(coverage_pct, 4),
            "bars_validated": len(bars),
            "has_benchmark_ticker": has_bench_ticker,
            "has_composite_proxy": has_composite,
            "has_benchmark_or_composite": has_bench_ticker or has_composite,
        }

        if coverage_pct < self.min_ticker_coverage:
            return StageResult(
                stage_name="Stage B: Data Validation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details=details,
                error=(
                    f"Ticker coverage on {latest_session} is {coverage_pct:.1%} "
                    f"({len(distinct_tickers)}/{active_universe_count}), below threshold "
                    f"{self.min_ticker_coverage:.1%}. Fail-closed before feature generation."
                ),
            )

        if not (has_bench_ticker or has_composite):
            return StageResult(
                stage_name="Stage B: Data Validation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details=details,
                error=(
                    f"Benchmark gate failed on {latest_session}: neither explicit index "
                    f"nor >=5 universe tickers available for composite proxy calculation."
                ),
            )

        return StageResult(
            stage_name="Stage B: Data Validation",
            status="SUCCESS",
            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
            details=details,
        )

    def _execute_stage_c(self, session_date: date) -> StageResult:
        t0 = datetime.now(timezone.utc)
        # Lookback: at least 250 calendar days to warm up EMA200
        lookback_start = session_date - timedelta(days=400)

        db_path = self._resolve_raw_db_path()
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ticker, date, open, high, low, close, volume, value
                FROM daily_bars
                WHERE date >= ? AND date <= ?
                ORDER BY ticker, date ASC;
                """,
                (str(lookback_start), str(session_date)),
            )
            raw_bars = cur.fetchall()
        finally:
            conn.close()

        if not raw_bars:
            return StageResult(
                stage_name="Stage C: Feature Generation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=(
                    f"No historical bars loaded for lookback window "
                    f"{lookback_start} to {session_date}."
                ),
            )

        universe_bars: dict[str, list[DailyBar]] = {}
        for r in raw_bars:
            t = str(r[0]).strip().upper().removesuffix(".JK")
            b = DailyBar(
                ticker=t,
                date=pd.to_datetime(r[1]).date(),
                open=float(r[2]),
                high=float(r[3]),
                low=float(r[4]),
                close=float(r[5]),
                volume=float(r[6]),
                value=float(r[7]) if r[7] is not None else float(r[5]) * float(r[6]),
            )
            if t not in universe_bars:
                universe_bars[t] = []
            universe_bars[t].append(b)

        # Compute features
        engine = FeatureEngine(feature_version=FEATURE_VERSION)
        features_by_ticker = engine.compute_universe_features(universe_bars)

        # Filter records for session_date
        records_to_save: list[FeatureRecord] = []
        for _t, recs in features_by_ticker.items():
            for r in recs:
                if r.date == session_date:
                    records_to_save.append(r)

        if not records_to_save:
            return StageResult(
                stage_name="Stage C: Feature Generation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"universe_tickers_loaded": len(universe_bars)},
                error=f"Engine generated 0 feature records for target session {session_date}.",
            )

        # Persist explicitly to DB
        saved_count = self.feature_repo.save_features(records_to_save)

        # Verify directly from DB
        conn = sqlite3.connect(db_path)
        try:
            db_count_row = conn.execute(
                "SELECT COUNT(*) FROM features_daily WHERE date = ? AND feature_version = ?;",
                (str(session_date), FEATURE_VERSION),
            ).fetchone()
            db_verified_count = db_count_row[0] if db_count_row else 0
        finally:
            conn.close()

        details = {
            "session_date": str(session_date),
            "features_generated_count": len(records_to_save),
            "features_persisted_count": saved_count,
            "db_verified_count": db_verified_count,
            "feature_version": FEATURE_VERSION,
        }

        if db_verified_count == 0:
            return StageResult(
                stage_name="Stage C: Feature Generation",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details=details,
                error=(
                    f"Feature persistence verification failed: 0 rows in features_daily "
                    f"for {session_date}."
                ),
            )

        return StageResult(
            stage_name="Stage C: Feature Generation",
            status="SUCCESS",
            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
            details=details,
        )

    def _execute_stage_d(self, session_date: date) -> StageResult:
        t0 = datetime.now(timezone.utc)
        db_path = self._resolve_raw_db_path()

        conn = sqlite3.connect(db_path)
        try:
            df_feat = pd.read_sql_query(
                "SELECT * FROM features_daily WHERE date = ? AND feature_version = ?;",
                conn,
                params=[str(session_date), FEATURE_VERSION],
            )
            bar_rows = conn.execute(
                "SELECT DISTINCT ticker FROM daily_bars WHERE date = ?;",
                (str(session_date),),
            ).fetchall()
            stored_bar_tickers = {
                r[0].strip().upper().removesuffix(".JK") for r in bar_rows
            }
        finally:
            conn.close()

        if df_feat.empty:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"session_date": str(session_date)},
                error=(
                    f"Feature readiness check failed: zero feature rows in features_daily "
                    f"for {session_date}."
                ),
            )

        # Check ordered schema columns
        missing_cols = [c for c in FEATURE_SCHEMA_30 if c not in df_feat.columns]
        if missing_cols:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"missing_cols": missing_cols},
                error=f"Feature readiness schema violation: missing columns {missing_cols}.",
            )

        # Point-in-time check: all rows must match session_date
        if any(str(r["date"]) != str(session_date) for _, r in df_feat.iterrows()):
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={},
                error=(
                    f"Point-in-time check failed: feature date mismatch in features_daily "
                    f"for {session_date}."
                ),
            )

        # Cross-table price bar match check
        feat_tickers = {
            str(t).strip().upper().removesuffix(".JK") for t in df_feat["ticker"]
        }
        unmatched_features = feat_tickers - stored_bar_tickers
        if unmatched_features:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"unmatched_feature_tickers": list(unmatched_features)},
                error=(
                    f"Feature records do not match stored price bars on {session_date}: "
                    f"{len(unmatched_features)} feature tickers have no bar in daily_bars."
                ),
            )

        # Benchmark features completeness check
        bench_cols = [
            "ihsg_return_5d",
            "ihsg_return_20d",
            "ihsg_vs_ema20",
            "ihsg_vs_ema50",
            "market_breadth",
            "market_volatility",
        ]
        all_null_bench = [
            c for c in bench_cols if c in df_feat.columns and df_feat[c].isna().all()
        ]
        if all_null_bench:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"all_null_benchmark_columns": all_null_bench},
                error=(
                    f"Feature readiness check failed on {session_date}: benchmark columns "
                    f"{all_null_bench} are entirely NULL. Composite/IHSG benchmark failed to build."
                ),
            )

        # Complete candidates history check
        complete_candidates = df_feat.dropna(subset=FEATURE_SCHEMA_30)
        if len(complete_candidates) == 0:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"total_feature_rows": len(df_feat), "complete_history_candidates": 0},
                error=(
                    f"Feature readiness check failed on {session_date}: 0 candidates have complete "
                    "30-feature history. Feature build incomplete or lookback insufficient."
                ),
            )

        # Strict NaN / Inf check on complete candidates
        cand_values = (
            complete_candidates[FEATURE_SCHEMA_30]
            .apply(pd.to_numeric, errors="coerce")
            .values
        )
        has_nan = np.isnan(cand_values).any()
        has_inf = np.isinf(cand_values).any()
        if has_nan or has_inf:
            return StageResult(
                stage_name="Stage D: Feature Readiness",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"has_nan": bool(has_nan), "has_inf": bool(has_inf)},
                error=(
                    f"Feature readiness check failed on {session_date}: NaN ({has_nan}) or "
                    f"Inf ({has_inf}) detected in complete candidates feature matrix."
                ),
            )

        details = {
            "session_date": str(session_date),
            "total_feature_rows": len(df_feat),
            "complete_history_candidates": len(complete_candidates),
            "schema_columns_count": len(FEATURE_SCHEMA_30),
            "matched_bar_tickers_count": len(feat_tickers & stored_bar_tickers),
            "has_infinite_values": False,
        }

        return StageResult(
            stage_name="Stage D: Feature Readiness",
            status="SUCCESS",
            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
            details=details,
        )

    def _execute_stage_e(self, session_date: date) -> StageResult:
        t0 = datetime.now(timezone.utc)
        engine = PaperTradingEngine(
            db_path=self._resolve_raw_db_path(),
            artifacts_dir=str(self.artifacts_dir),
        )

        # Artifact audit
        audit = engine.audit_scoring_artifacts()
        if audit["status"] != "PASS":
            err_log = audit["error_logs"][0] if audit["error_logs"] else "Unknown error"
            return StageResult(
                stage_name="Stage E: Paper Trading",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"audit": audit},
                error=f"Scoring artifacts audit failed: {err_log}",
            )

        model_hashes = {
            k: v.get("sha256", "") for k, v in audit.get("artifacts", {}).items()
        }
        policy_bundle_hash = engine.frozen_bundle.config_sha256
        feature_schema_hash = hashlib.sha256(json.dumps(FEATURE_SCHEMA_30).encode()).hexdigest()

        # State check
        state = engine.load_state()
        if not state.get("user_approved"):
            return StageResult(
                stage_name="Stage E: Paper Trading",
                status="FAILED",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={"user_approved": False},
                error="Human operator approval not recorded. Run --approve-observation first.",
            )

        eff_cutoff_str = state.get("effective_observation_cutoff") or state.get(
            "approval_data_cutoff"
        )
        eff_cutoff_d = pd.to_datetime(eff_cutoff_str).date() if eff_cutoff_str else None

        # Check if session is prospective or pre-approval
        if eff_cutoff_d and session_date <= eff_cutoff_d:
            op_status = engine.generate_operational_status()
            lifecycle = op_status.get("prospective_lifecycle", {})
            details = {
                "decision_date": str(session_date),
                "effective_observation_cutoff": str(eff_cutoff_d),
                "operational_status": op_status["operational_status"],
                "action": "SKIPPED_PRE_APPROVAL_SESSION",
                "reason": (
                    f"Session {session_date} is at or before effective observation cutoff "
                    f"{eff_cutoff_d}. System remains APPROVED_PENDING_FIRST_OBSERVATION awaiting "
                    "the first completed session strictly after cutoff."
                ),
                "model_hashes": model_hashes,
                "policy_bundle_hash": policy_bundle_hash,
                "feature_schema_hash": feature_schema_hash,
                "cash": lifecycle.get("cash_balance_idr", 100000000.0),
                "total_equity": lifecycle.get("current_equity_idr", 100000000.0),
                "open_positions_count": lifecycle.get("open_positions_count", 0),
                "pending_orders_count": lifecycle.get("pending_orders_count", 0),
                "max_drawdown_pct": lifecycle.get("max_drawdown_pct", 0.0),
                "realized_net_pnl_idr": lifecycle.get("realized_net_pnl_idr", 0.0),
                "unrealized_pnl_idr": lifecycle.get("unrealized_pnl_idr", 0.0),
                "candidates_count": 0,
                "decisions_count": 0,
                "new_fills_count": 0,
                "exits_count": 0,
            }
            return StageResult(
                stage_name="Stage E: Paper Trading",
                status="SKIPPED_PRE_APPROVAL_SESSION",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details=details,
            )

        # If dry run, do not mutate state
        if self.dry_run:
            op_status = engine.generate_operational_status()
            lifecycle = op_status.get("prospective_lifecycle", {})
            return StageResult(
                stage_name="Stage E: Paper Trading",
                status="SUCCESS",
                duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
                details={
                    "decision_date": str(session_date),
                    "dry_run": True,
                    "action": "DRY_RUN_CHECK_PASSED",
                    "model_hashes": model_hashes,
                    "policy_bundle_hash": policy_bundle_hash,
                    "feature_schema_hash": feature_schema_hash,
                    "cash": lifecycle.get("cash_balance_idr", 100000000.0),
                    "total_equity": lifecycle.get("current_equity_idr", 100000000.0),
                    "open_positions_count": lifecycle.get("open_positions_count", 0),
                    "pending_orders_count": lifecycle.get("pending_orders_count", 0),
                    "max_drawdown_pct": lifecycle.get("max_drawdown_pct", 0.0),
                    "realized_net_pnl_idr": lifecycle.get("realized_net_pnl_idr", 0.0),
                    "unrealized_pnl_idr": lifecycle.get("unrealized_pnl_idr", 0.0),
                    "candidates_count": 0,
                    "decisions_count": 0,
                    "new_fills_count": 0,
                    "exits_count": 0,
                },
            )

        # Execute prospective step
        step_result = engine.step_prospective_date(session_date, user_approved=True)

        # Refresh operational status
        op_status = engine.generate_operational_status()
        lifecycle = op_status.get("prospective_lifecycle", {})

        details = {
            "decision_date": str(session_date),
            "step_result": step_result,
            "operational_status": op_status["operational_status"],
            "model_hashes": model_hashes,
            "policy_bundle_hash": policy_bundle_hash,
            "feature_schema_hash": feature_schema_hash,
            "cash": lifecycle.get("cash_balance_idr", 100000000.0),
            "total_equity": lifecycle.get("current_equity_idr", 100000000.0),
            "open_positions_count": lifecycle.get("open_positions_count", 0),
            "pending_orders_count": lifecycle.get("pending_orders_count", 0),
            "max_drawdown_pct": lifecycle.get("max_drawdown_pct", 0.0),
            "realized_net_pnl_idr": lifecycle.get("realized_net_pnl_idr", 0.0),
            "unrealized_pnl_idr": lifecycle.get("unrealized_pnl_idr", 0.0),
            "candidates_count": step_result.get("candidates_count", 0),
            "decisions_count": step_result.get("decisions_count", 0),
            "new_fills_count": step_result.get("fills_count", 0),
            "exits_count": step_result.get("exits_count", 0),
        }

        return StageResult(
            stage_name="Stage E: Paper Trading",
            status="SUCCESS",
            duration_seconds=(datetime.now(timezone.utc) - t0).total_seconds(),
            details=details,
        )

    def _finalize_report(
        self,
        run_id: str,
        started_at: datetime,
        overall_status: str,
        stages: dict[str, StageResult],
        errors: list[str],
        git_sha: str,
    ) -> PipelineRunReport:
        finished_at = datetime.now(timezone.utc)
        duration_s = (finished_at - started_at).total_seconds()

        stages_dict: dict[str, dict[str, Any]] = {
            name: {
                "stage_name": res.stage_name,
                "status": res.status,
                "duration_seconds": round(res.duration_seconds, 3),
                "details": res.details,
                "error": res.error,
            }
            for name, res in stages.items()
        }

        ing_det = stages.get("stage_a_ingestion", StageResult("", "SKIPPED", 0, {})).details
        val_det = stages.get("stage_b_data_validation", StageResult("", "SKIPPED", 0, {})).details
        feat_det = stages.get(
            "stage_c_feature_generation", StageResult("", "SKIPPED", 0, {})
        ).details
        read_det = stages.get(
            "stage_d_feature_readiness", StageResult("", "SKIPPED", 0, {})
        ).details
        pt_det = stages.get("stage_e_paper_trading", StageResult("", "SKIPPED", 0, {})).details

        feature_version = feat_det.get("feature_version", FEATURE_VERSION)
        feature_schema_hash = pt_det.get(
            "feature_schema_hash",
            hashlib.sha256(json.dumps(FEATURE_SCHEMA_30).encode()).hexdigest(),
        )
        model_hashes = pt_det.get("model_hashes", {})
        try:
            default_bundle_hash = PaperTradingEngine(
                db_path=self._resolve_raw_db_path(),
                artifacts_dir=str(self.artifacts_dir),
            ).frozen_bundle.config_sha256
        except Exception:
            default_bundle_hash = ""
        policy_bundle_hash = pt_det.get("policy_bundle_hash") or default_bundle_hash
        decision_date = pt_det.get("decision_date") or val_det.get("latest_completed_session")

        step_res = pt_det.get("step_result", {})
        candidates_cnt = step_res.get("candidates_count", pt_det.get("candidates_count", 0))
        decisions_cnt = step_res.get("decisions_count", pt_det.get("decisions_count", 0))
        new_fills_cnt = step_res.get("fills_count", pt_det.get("new_fills_count", 0))
        exits_cnt = step_res.get("exits_count", pt_det.get("exits_count", 0))

        pending_orders_cnt = pt_det.get("pending_orders_count", 0)
        open_positions_cnt = pt_det.get("open_positions_count", 0)
        cash_balance = pt_det.get("cash", 100000000.0)
        total_equity = pt_det.get("total_equity", 100000000.0)
        realized_pnl = pt_det.get("realized_net_pnl_idr", 0.0)
        unrealized_pnl = pt_det.get("unrealized_pnl_idr", 0.0)
        max_drawdown = pt_det.get("max_drawdown_pct", 0.0)

        report = PipelineRunReport(
            run_id=run_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=round(duration_s, 3),
            git_commit_sha=git_sha,
            configured_provider=self.provider_name,
            overall_status=overall_status,
            stages=stages_dict,
            errors=errors,
            ingestion_summary=ing_det,
            validation_summary=val_det,
            feature_summary=feat_det,
            feature_readiness_summary=read_det,
            paper_trading_summary=pt_det,
            feature_schema_hash=feature_schema_hash,
            feature_version=feature_version,
            model_hashes=model_hashes,
            policy_bundle_hash=policy_bundle_hash,
            decision_date=decision_date,
            candidates_count=candidates_cnt,
            decisions_count=decisions_cnt,
            pending_orders_count=pending_orders_cnt,
            new_fills_count=new_fills_cnt,
            exits_count=exits_cnt,
            open_positions_count=open_positions_cnt,
            cash_balance_idr=cash_balance,
            realized_net_pnl_idr=realized_pnl,
            unrealized_pnl_idr=unrealized_pnl,
            current_equity_idr=total_equity,
            max_drawdown_pct=max_drawdown,
        )

        # Persist report JSON
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = self.reports_dir / f"pipeline_run_{run_id}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2, default=str)

        latest_file = self.reports_dir / "latest_pipeline_run.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2, default=str)

        return report
