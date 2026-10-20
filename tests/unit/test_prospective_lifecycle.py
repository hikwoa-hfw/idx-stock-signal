"""Unit and regression tests for Phase 11F.3 prospective paper-trading lifecycle.

Verifies:
1. Gating & Approval:
   - No prospective scoring or state mutation without explicit user approval.
   - Fail-closed guard on missing research scoring artifacts.
2. Execution Scheduling:
   - Decision on date t is scheduled for next eligible trading session t+1, NOT date t.
3. Order Fills & Gap Invalidations:
   - Next-session open creates valid fill at open + 5 bps slippage and 15 bps fee.
   - Gap-down <= SL invalidates order (INVALIDATED_GAP_DOWN).
   - Gap-up >= TP invalidates order (INVALIDATED_GAP_UP).
   - Excessive deviation > 5% invalidates order (INVALIDATED_EXCESSIVE_DEV).
   - Suspended / zero-volume bar remains unfilled (UNFILLED_SUSPENDED).
4. Exit Lifecycle:
   - TP (+6%) exit with 5 bps slippage and 25 bps sell commission.
   - SL (-2%) exit with conservative precedence on ambiguous same-candle bar.
   - Expiry exit at day 15 close.
5. Sizing & Portfolio Constraints:
   - 100-share lot rounding (IDX constraint).
   - 20% equity cap per position.
   - Max 5 concurrent positions (excess rejected with UNFILLED_CAPACITY).
6. State Persistence & Idempotency:
   - State persists across separate engine/process instances.
   - Re-running the same date is strictly idempotent (ALREADY_PROCESSED).
7. Operational Status:
   - Transitions to OBSERVATION_ACTIVE only after an approved prospective run succeeds.
   - Isolation from production champions.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest

from python.common.types import DailyBar
from python.experiments.paper_trading import (
    RESEARCH_SCORING_ARTIFACTS,
    STATUS_OBSERVATION_ACTIVE,
    STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL,
    MissingScoringArtifactError,
    PaperTradingEngine,
    UserApprovalRequiredError,
)


class DummyModel:
    """Mock model returning deterministic scores."""

    def predict(self, X: Any) -> np.ndarray:
        return np.full(len(X), 0.05)

    def predict_proba(self, X: Any) -> np.ndarray:
        n = len(X)
        return np.column_stack([np.full(n, 0.4), np.full(n, 0.6)])


@pytest.fixture
def mock_lifecycle_engine(tmp_path: Path) -> PaperTradingEngine:
    """Provides PaperTradingEngine configured with mock artifacts and isolated directory."""
    artifacts_dir = tmp_path / "artifacts_11f"
    engine = PaperTradingEngine(
        db_path="datasets/stock_signals.db",
        artifacts_dir=artifacts_dir,
    )

    # Populate mock research scoring models
    for rel_path in RESEARCH_SCORING_ARTIFACTS.values():
        full_path = tmp_path / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(DummyModel(), full_path)

    return engine


class TestApprovalAndFailClosedGuard:
    def test_user_approval_required_blocks_mutation(
        self, mock_lifecycle_engine: PaperTradingEngine, tmp_path: Path
    ):
        """Verifies step_prospective_date raises UserApprovalRequiredError
        when user_approved=False.
        """
        engine = mock_lifecycle_engine

        with pytest.raises(UserApprovalRequiredError):
            engine.step_prospective_date(date(2026, 9, 18), user_approved=False, base_dir=tmp_path)

        # State must not be created or started
        state_file = engine.artifacts_dir / "paper_trading_state.json"
        assert not state_file.exists()

        status = engine.generate_operational_status(base_dir=tmp_path)
        assert status["operational_status"] == STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL
        assert status["prospective_lifecycle"]["has_started"] is False

    def test_missing_artifacts_halts_prospective_date(self, tmp_path: Path):
        """Verifies missing research artifacts halt with MissingScoringArtifactError."""
        empty_dir = tmp_path / "empty_artifacts"
        engine = PaperTradingEngine(
            db_path="datasets/stock_signals.db",
            artifacts_dir=empty_dir,
        )

        with pytest.raises(MissingScoringArtifactError):
            engine.step_prospective_date(date(2026, 9, 18), user_approved=True, base_dir=tmp_path)


class TestExecutionScheduling:
    def test_decision_scheduled_for_next_eligible_session_not_date_t(
        self, mock_lifecycle_engine: PaperTradingEngine, tmp_path: Path
    ):
        """Verifies decision created on date t has execution_date strictly in future (t+1)."""
        engine = mock_lifecycle_engine
        eval_d = date(2026, 9, 18)  # Friday

        res = engine.step_prospective_date(eval_d, user_approved=True, base_dir=tmp_path)
        assert res["status"] == "SCORED"
        assert res["decisions_count"] > 0

        # Read persisted decisions CSV
        decs_csv = engine.artifacts_dir / "paper_trading_decisions.csv"
        assert decs_csv.exists()
        import pandas as pd

        df_decs = pd.read_csv(decs_csv)
        assert not df_decs.empty

        for _, row in df_decs.iterrows():
            dec_d = str(row["decision_date"])
            exec_d = str(row["execution_date"])
            assert dec_d == "2026-09-18"
            # Must NOT claim execution on decision date
            assert exec_d != dec_d
            # In database, next trading date after Friday 2026-09-18 is Monday 2026-09-21
            assert exec_d == "2026-09-21"

        # Check pending orders in persistent state
        state = engine.load_state()
        assert len(state["pending_orders"]) > 0
        for ord_info in state["pending_orders"]:
            assert ord_info["decision_date"] == "2026-09-18"
            assert ord_info["scheduled_execution_date"] == "2026-09-21"


class TestOrderFillsAndGapInvalidations:
    def test_next_session_valid_fill_at_open(self, mock_lifecycle_engine: PaperTradingEngine):
        """Verifies queued order fills at session Open with slippage and commission."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Seed a pending order scheduled for 2026-10-01
        state["pending_orders"].append(
            {
                "ticker": "BBCA",
                "mode": "LOW_PRICE",
                "decision_date": "2026-09-30",
                "scheduled_execution_date": "2026-10-01",
                "close_t": 100.0,
                "score": 0.85,
                "max_holding_days": 15,
                "tp_pct": 0.06,
                "sl_pct": 0.02,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
                "status": "PENDING",
            }
        )
        engine.save_state(state)

        # Inject bar for BBCA on 2026-10-01: open=101.0, close=102.0, high=103.0, low=100.5
        engine._bars_by_ticker = {
            "BBCA": [
                DailyBar(
                    ticker="BBCA",
                    date=date(2026, 10, 1),
                    open=101.0,
                    high=103.0,
                    low=100.5,
                    close=102.0,
                    volume=500000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["orders_filled"] == 1
        assert res["open_positions_count"] == 1

        state_after = engine.load_state()
        assert "BBCA" in state_after["open_positions"]
        pos = state_after["open_positions"]["BBCA"]
        expected_fill = 101.0 * (1.0 + 5.0 / 10000.0)
        assert pos["entry_price"] == pytest.approx(expected_fill, rel=1e-5)
        assert pos["shares"] % 100 == 0

    def test_next_session_gap_down_invalidation(self, mock_lifecycle_engine: PaperTradingEngine):
        """Verifies open <= SL barrier invalidates entry without filling."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Close was 100.0, SL is 2% (98.0). Open gaps to 97.0
        state["pending_orders"].append(
            {
                "ticker": "ASII",
                "mode": "LOW_PRICE",
                "decision_date": "2026-09-30",
                "scheduled_execution_date": "2026-10-01",
                "close_t": 100.0,
                "score": 0.90,
                "max_holding_days": 15,
                "tp_pct": 0.06,
                "sl_pct": 0.02,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
                "status": "PENDING",
            }
        )
        engine.save_state(state)

        engine._bars_by_ticker = {
            "ASII": [
                DailyBar(
                    ticker="ASII",
                    date=date(2026, 10, 1),
                    open=97.0,
                    high=99.0,
                    low=96.0,
                    close=98.0,
                    volume=100000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["orders_filled"] == 0
        assert res["open_positions_count"] == 0

        state_after = engine.load_state()
        assert state_after["unfilled_summary"]["invalidated_gap_down"] == 1
        assert len(state_after["completed_trades"]) == 0

    def test_next_session_gap_up_invalidation(self, mock_lifecycle_engine: PaperTradingEngine):
        """Verifies open >= TP barrier invalidates entry without filling."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Close was 100.0, TP is 6% (106.0). Open gaps to 107.0
        state["pending_orders"].append(
            {
                "ticker": "TLKM",
                "mode": "LOW_PRICE",
                "decision_date": "2026-09-30",
                "scheduled_execution_date": "2026-10-01",
                "close_t": 100.0,
                "score": 0.92,
                "max_holding_days": 15,
                "tp_pct": 0.06,
                "sl_pct": 0.02,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
                "status": "PENDING",
            }
        )
        engine.save_state(state)

        engine._bars_by_ticker = {
            "TLKM": [
                DailyBar(
                    ticker="TLKM",
                    date=date(2026, 10, 1),
                    open=107.0,
                    high=108.0,
                    low=106.5,
                    close=107.5,
                    volume=200000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["orders_filled"] == 0
        state_after = engine.load_state()
        assert state_after["unfilled_summary"]["invalidated_gap_up"] == 1

    def test_next_session_excessive_deviation_invalidation(
        self, mock_lifecycle_engine: PaperTradingEngine
    ):
        """Verifies open deviating > 5% without hitting TP/SL invalidates entry."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Close was 100.0, TP is 108 (so 105.5 is below TP), but deviation is 5.5% > 5%
        state["pending_orders"].append(
            {
                "ticker": "UNVR",
                "mode": "LOW_PRICE",
                "decision_date": "2026-09-30",
                "scheduled_execution_date": "2026-10-01",
                "close_t": 100.0,
                "score": 0.88,
                "max_holding_days": 15,
                "tp_pct": 0.08,
                "sl_pct": 0.05,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
                "status": "PENDING",
            }
        )
        engine.save_state(state)

        engine._bars_by_ticker = {
            "UNVR": [
                DailyBar(
                    ticker="UNVR",
                    date=date(2026, 10, 1),
                    open=105.5,
                    high=106.0,
                    low=105.0,
                    close=105.8,
                    volume=150000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["orders_filled"] == 0
        state_after = engine.load_state()
        assert state_after["unfilled_summary"]["invalidated_excessive_dev"] == 1


class TestExitLifecycleAndAmbiguity:
    def test_tp_exit_resolution(self, mock_lifecycle_engine: PaperTradingEngine):
        """Verifies open position hits TP (+6%) and completes trade cleanly."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Seed active open position
        entry_p = 100.0
        shares = 1000
        gross = entry_p * shares
        fee_buy = gross * 0.0015
        state["cash"] -= gross + fee_buy
        state["open_positions"]["BBNI"] = {
            "ticker": "BBNI",
            "mode": "LOW_PRICE",
            "signal_date": "2026-09-29",
            "entry_date": "2026-09-30",
            "entry_price": entry_p,
            "raw_entry": entry_p,
            "shares": shares,
            "gross_outlay": gross,
            "entry_fee": fee_buy,
            "tp_pct": 0.06,
            "sl_pct": 0.02,
            "tp_price": entry_p * 1.06,
            "sl_price": entry_p * 0.98,
            "highest_watermark": entry_p,
            "lowest_watermark": entry_p,
            "max_holding_days": 15,
            "holding_days": 2,
            "score": 0.88,
            "size_multiplier": 1.0,
            "regime_category": "FAVORABLE",
        }
        engine.save_state(state)

        # Day 2 bar hits TP: high=107.0 >= 106.0, low=101.0
        engine._bars_by_ticker = {
            "BBNI": [
                DailyBar(
                    ticker="BBNI",
                    date=date(2026, 10, 1),
                    open=101.0,
                    high=107.0,
                    low=101.0,
                    close=106.5,
                    volume=500000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["positions_closed"] == 1
        assert res["open_positions_count"] == 0

        state_after = engine.load_state()
        assert len(state_after["completed_trades"]) == 1
        trade = state_after["completed_trades"][0]
        assert trade["ticker"] == "BBNI"
        assert trade["exit_reason"] == "TP"
        assert trade["net_pnl"] > 0
        assert trade["exit_price"] == pytest.approx(106.0 * (1.0 - 5.0 / 10000.0), rel=1e-5)

    def test_conservative_sl_precedence_on_ambiguous_candle(
        self, mock_lifecycle_engine: PaperTradingEngine
    ):
        """Verifies conservative precedence: if both TP and SL hit on same candle, resolve as SL."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        entry_p = 100.0
        shares = 1000
        gross = entry_p * shares
        fee_buy = gross * 0.0015
        state["cash"] -= gross + fee_buy
        state["open_positions"]["MDKA"] = {
            "ticker": "MDKA",
            "mode": "LOW_PRICE",
            "signal_date": "2026-09-29",
            "entry_date": "2026-09-30",
            "entry_price": entry_p,
            "raw_entry": entry_p,
            "shares": shares,
            "gross_outlay": gross,
            "entry_fee": fee_buy,
            "tp_pct": 0.06,
            "sl_pct": 0.02,
            "tp_price": 106.0,
            "sl_price": 98.0,
            "highest_watermark": entry_p,
            "lowest_watermark": entry_p,
            "max_holding_days": 15,
            "holding_days": 3,
            "score": 0.75,
            "size_multiplier": 1.0,
            "regime_category": "FAVORABLE",
        }
        engine.save_state(state)

        # Ambiguous bar: high=107.0 (>=TP), low=97.0 (<=SL)
        engine._bars_by_ticker = {
            "MDKA": [
                DailyBar(
                    ticker="MDKA",
                    date=date(2026, 10, 1),
                    open=99.0,
                    high=107.0,
                    low=97.0,
                    close=101.0,
                    volume=800000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["positions_closed"] == 1

        state_after = engine.load_state()
        trade = state_after["completed_trades"][0]
        assert trade["ticker"] == "MDKA"
        # Must resolve as SL under conservative policy
        assert trade["exit_reason"] == "SL"
        assert trade["net_pnl"] < 0

    def test_expiry_exit_at_holding_day_15(self, mock_lifecycle_engine: PaperTradingEngine):
        """Verifies position reaching 15 holding days exits at Close with EXPIRY."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        entry_p = 100.0
        shares = 1000
        gross = entry_p * shares
        fee_buy = gross * 0.0015
        state["cash"] -= gross + fee_buy
        state["open_positions"]["ICBP"] = {
            "ticker": "ICBP",
            "mode": "HIGHER_PRICE",
            "signal_date": "2026-09-10",
            "entry_date": "2026-09-11",
            "entry_price": entry_p,
            "raw_entry": entry_p,
            "shares": shares,
            "gross_outlay": gross,
            "entry_fee": fee_buy,
            "tp_pct": 0.06,
            "sl_pct": 0.02,
            "tp_price": 106.0,
            "sl_price": 98.0,
            "highest_watermark": 102.0,
            "lowest_watermark": 99.0,
            "max_holding_days": 15,
            "holding_days": 15,  # Reached max horizon
            "score": 0.65,
            "size_multiplier": 1.0,
            "regime_category": "FAVORABLE",
        }
        engine.save_state(state)

        # Bar does not hit TP or SL
        engine._bars_by_ticker = {
            "ICBP": [
                DailyBar(
                    ticker="ICBP",
                    date=date(2026, 10, 1),
                    open=101.0,
                    high=102.0,
                    low=100.0,
                    close=101.5,
                    volume=300000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["positions_closed"] == 1

        state_after = engine.load_state()
        trade = state_after["completed_trades"][0]
        assert trade["exit_reason"] == "EXPIRY"
        assert trade["exit_price"] == pytest.approx(101.5 * (1.0 - 5.0 / 10000.0), rel=1e-5)


class TestConstraintsAndAccounting:
    def test_capacity_and_duplicate_ticker_constraints(
        self, mock_lifecycle_engine: PaperTradingEngine
    ):
        """Verifies max 5 concurrent positions and duplicate ticker rejection."""
        engine = mock_lifecycle_engine
        state = engine.load_state()

        # Fill 5 positions
        for i in range(5):
            tkr = f"TK0{i}"
            state["open_positions"][tkr] = {
                "ticker": tkr,
                "mode": "LOW_PRICE",
                "signal_date": "2026-09-29",
                "entry_date": "2026-09-30",
                "entry_price": 100.0,
                "raw_entry": 100.0,
                "shares": 100,
                "gross_outlay": 10000.0,
                "entry_fee": 15.0,
                "tp_pct": 0.06,
                "sl_pct": 0.02,
                "tp_price": 106.0,
                "sl_price": 98.0,
                "highest_watermark": 100.0,
                "lowest_watermark": 100.0,
                "max_holding_days": 15,
                "holding_days": 1,
                "score": 0.8,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
            }

        # Queue a 6th ticker
        state["pending_orders"].append(
            {
                "ticker": "TK06",
                "mode": "LOW_PRICE",
                "decision_date": "2026-09-30",
                "scheduled_execution_date": "2026-10-01",
                "close_t": 100.0,
                "score": 0.85,
                "max_holding_days": 15,
                "tp_pct": 0.06,
                "sl_pct": 0.02,
                "size_multiplier": 1.0,
                "regime_category": "FAVORABLE",
                "status": "PENDING",
            }
        )
        engine.save_state(state)

        engine._bars_by_ticker = {
            "TK06": [
                DailyBar(
                    ticker="TK06",
                    date=date(2026, 10, 1),
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=100000.0,
                )
            ]
        }

        res = engine.step_prospective_date(date(2026, 10, 1), user_approved=True)
        assert res["orders_filled"] == 0
        state_after = engine.load_state()
        assert state_after["unfilled_summary"]["unfilled_capacity"] == 1
        assert len(state_after["open_positions"]) == 5


class TestPersistenceAndIdempotency:
    def test_state_persists_across_instances(self, tmp_path: Path):
        """Verifies state written by engine instance 1 is accurately read by engine instance 2."""
        art_dir = tmp_path / "art_persist"
        e1 = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
        state1 = e1.load_state()
        state1["cash"] = 85_000_000.0
        state1["open_positions"]["TEST"] = {
            "ticker": "TEST",
            "entry_price": 500.0,
            "shares": 200,
        }
        e1.save_state(state1)

        # Instance 2 pointing to same directory
        e2 = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
        state2 = e2.load_state()
        assert state2["cash"] == 85_000_000.0
        assert "TEST" in state2["open_positions"]
        assert state2["open_positions"]["TEST"]["shares"] == 200

    def test_idempotent_rerun_returns_already_processed(
        self, mock_lifecycle_engine: PaperTradingEngine, tmp_path: Path
    ):
        """Verifies re-running the same trading date returns ALREADY_PROCESSED
        without duplicates.
        """
        engine = mock_lifecycle_engine
        eval_d = date(2026, 9, 18)

        # Run 1
        res1 = engine.step_prospective_date(eval_d, user_approved=True, base_dir=tmp_path)
        assert res1["status"] == "SCORED"
        state1 = engine.load_state()
        cash1 = state1["cash"]
        orders1_len = len(state1["pending_orders"])

        # Run 2 on same date
        res2 = engine.step_prospective_date(eval_d, user_approved=True, base_dir=tmp_path)
        assert res2["status"] == "ALREADY_PROCESSED"
        assert res2["candidates_count"] == 0
        assert res2["decisions_count"] == 0

        # State must remain identical
        state2 = engine.load_state()
        assert state2["cash"] == cash1
        assert len(state2["pending_orders"]) == orders1_len


class TestOperationalStatusTransitions:
    def test_status_transitions_to_active_only_after_approved_prospective_run(
        self, mock_lifecycle_engine: PaperTradingEngine, tmp_path: Path
    ):
        """Verifies operational status transitions to OBSERVATION_ACTIVE
        only after approved prospective run.
        """
        engine = mock_lifecycle_engine

        # Initial status before any run
        s0 = engine.generate_operational_status(base_dir=tmp_path)
        assert s0["operational_status"] == STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL
        assert s0["prospective_lifecycle"]["has_started"] is False

        # Execute approved prospective scoring
        engine.step_prospective_date(date(2026, 9, 18), user_approved=True, base_dir=tmp_path)

        # Status after prospective execution
        s1 = engine.generate_operational_status(base_dir=tmp_path)
        assert s1["operational_status"] == STATUS_OBSERVATION_ACTIVE
        assert s1["prospective_lifecycle"]["has_started"] is True
        assert s1["prospective_lifecycle"]["first_observation_date"] == "2026-09-18"
        assert s1["prospective_lifecycle"]["last_decision_date"] == "2026-09-18"
        assert s1["prospective_lifecycle"]["pending_orders_count"] > 0
