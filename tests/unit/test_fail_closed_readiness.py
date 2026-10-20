"""Targeted unit and regression tests for Phase 11F.4 Fail-Closed Readiness Corrections.

Verifies:
1. Approval recorded without scoring does not activate observation.
2. `--status --user-approved` does not independently activate observation.
3. Historical date at or before approval-time data cutoff is strictly rejected.
4. A new valid date strictly after approval can be processed.
5. Missing bars and missing features each fail closed independently.
6. Failed scoring or persistence does not create a false start record.
7. Corrupt existing state never silently resets capital or positions:
   - Missing state
   - Malformed JSON
   - Missing required fields
   - Incompatible policy hash
   - Valid migrated state with backup copy
8. Duplicate and out-of-order dates cannot alter the portfolio.
9. Missed sessions fail closed without silently filling at a later open.
10. Successful initial scoring activates lifecycle only after records are persisted.
11. Production champion fallback remains strictly prohibited.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest

from python.experiments.paper_trading import (
    CHAMPION_MODELS,
    FEATURE_SCHEMA_30,
    RESEARCH_SCORING_ARTIFACTS,
    STATUS_APPROVED_PENDING_FIRST_OBSERVATION,
    STATUS_BLOCKED_ON_SCORING_ARTIFACT,
    STATUS_BLOCKED_ON_STATE_CORRUPTION,
    STATUS_OBSERVATION_ACTIVE,
    STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL,
    DataQualityError,
    InvalidProspectiveDateError,
    MissedSessionError,
    MissingScoringArtifactError,
    PaperTradingEngine,
    StateIntegrityError,
)


class DummyEstimator:
    """Mock LightGBM model for testing."""

    def predict(self, X: Any) -> np.ndarray:
        return np.full(len(X), 0.05)

    def predict_proba(self, X: Any) -> np.ndarray:
        n = len(X)
        return np.column_stack([np.full(n, 0.4), np.full(n, 0.6)])


class BrokenModel:
    """Mock model that passes all-zero smoke test but crashes during actual feature scoring."""

    def predict(self, X: Any) -> np.ndarray:
        arr = np.asarray(X)
        if (arr == 0.0).all():
            return np.array([0.05])
        raise RuntimeError("Scoring calculation crashed unexpectedly")

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X)
        if (arr == 0.0).all():
            return np.array([[0.4, 0.6]])
        raise RuntimeError("Scoring calculation crashed unexpectedly")


def populate_mock_models(base_dir: Path) -> None:
    for rel_path in RESEARCH_SCORING_ARTIFACTS.values():
        full_path = base_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(DummyEstimator(), full_path)


def create_isolated_test_db(db_path: Path) -> None:
    """Creates a minimal SQLite database containing daily_bars and features_daily."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE daily_bars (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (date, ticker)
        );
    """)
    cols = ", ".join(f"{col} REAL" for col in FEATURE_SCHEMA_30)
    cur.execute(f"""
        CREATE TABLE features_daily (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            {cols},
            PRIMARY KEY (date, ticker)
        );
    """)
    # Add historical baseline bars up to 2026-10-16
    cur.execute("""
        INSERT INTO daily_bars VALUES
        ('2026-10-16', 'BBCA', 10000.0, 10200.0, 9950.0, 10150.0, 500000.0),
        ('2026-10-16', 'BBRI', 5000.0, 5100.0, 4980.0, 5050.0, 800000.0);
    """)
    feat_vals = ", ".join("0.05" for _ in FEATURE_SCHEMA_30)
    cur.execute(f"""
        INSERT INTO features_daily VALUES
        ('2026-10-16', 'BBCA', {feat_vals}),
        ('2026-10-16', 'BBRI', {feat_vals});
    """)
    conn.commit()
    conn.close()


def add_session_to_test_db(
    db_path: Path, session_date: str, ticker: str = "BBCA", price: float = 10000.0
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (session_date, ticker, price, price * 1.02, price * 0.98, price, 1000000.0))
    feat_vals = [0.05] * len(FEATURE_SCHEMA_30)
    # Set ihsg_vs_ema20 positive for bull regime
    feat_vals[FEATURE_SCHEMA_30.index("ihsg_vs_ema20")] = 0.02
    placeholders = ", ".join("?" for _ in feat_vals)
    cur.execute(f"""
        INSERT OR REPLACE INTO features_daily VALUES (?, ?, {placeholders});
    """, [session_date, ticker] + feat_vals)
    conn.commit()
    conn.close()


# ==============================================================================
# Requirement 1: Separate Approval from Actual Observation Activation
# ==============================================================================


def test_approval_recorded_without_scoring_does_not_activate_observation(tmp_path: Path):
    """Verifies that recording approval creates approval records but does not
    score stocks, generate decisions, or activate observation.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    art_dir = tmp_path / "artifacts"
    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=art_dir)

    # Status before approval
    s0 = engine.generate_operational_status(base_dir=tmp_path)
    assert s0["operational_status"] == STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL
    assert s0["user_approved"] is False

    # Execute approval command
    info = engine.approve_observation(base_dir=tmp_path)
    assert info["user_approved"] is True
    assert info["approval_timestamp"] is not None
    assert info["approval_data_cutoff"] == "2026-10-16"
    assert info["operational_status"] == STATUS_APPROVED_PENDING_FIRST_OBSERVATION

    # State file check
    state = engine.load_state()
    assert state["user_approved"] is True
    assert state["approval_timestamp"] == info["approval_timestamp"]
    assert state["approval_data_cutoff"] == "2026-10-16"
    assert state["first_observation_date"] is None
    assert state["first_prospective_run_timestamp"] is None
    assert len(state["processed_dates"]) == 0
    assert len(state["pending_orders"]) == 0
    assert len(state["completed_trades"]) == 0

    # Operational status check: must be distinct APPROVED_PENDING_FIRST_OBSERVATION
    s1 = engine.generate_operational_status(base_dir=tmp_path)
    assert s1["operational_status"] == STATUS_APPROVED_PENDING_FIRST_OBSERVATION
    assert s1["prospective_lifecycle"]["has_started"] is False
    assert s1["prospective_lifecycle"]["first_observation_date"] is None


def test_status_user_approved_flag_does_not_activate_observation(tmp_path: Path):
    """Verifies that --status --user-approved does not activate observation
    when no prospective run has succeeded.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")

    # Call generate_operational_status with user_approved=True
    status = engine.generate_operational_status(user_approved=True, base_dir=tmp_path)

    # Must NOT be OBSERVATION_ACTIVE
    assert status["operational_status"] == STATUS_APPROVED_PENDING_FIRST_OBSERVATION
    assert status["operational_status"] != STATUS_OBSERVATION_ACTIVE
    assert status["prospective_lifecycle"]["has_started"] is False


# ==============================================================================
# Requirement 2: Prevent Backdated or Stale Prospective Observations
# ==============================================================================


def test_historical_date_at_or_before_data_cutoff_rejected(tmp_path: Path):
    """Verifies that dates at or before the approval-time data cutoff are rejected,
    even when user_approved=True is supplied.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    # 1. Exact cutoff date 2026-10-16 must be rejected
    with pytest.raises(
        InvalidProspectiveDateError, match="at or before the approval market data cutoff"
    ):
        engine.step_prospective_date(date(2026, 10, 16), user_approved=True, base_dir=tmp_path)

    # 2. Earlier historical date 2026-09-18 must be rejected
    with pytest.raises(
        InvalidProspectiveDateError, match="at or before the approval market data cutoff"
    ):
        engine.step_prospective_date(date(2026, 9, 18), user_approved=True, base_dir=tmp_path)

    # State must not be mutated
    state = engine.load_state()
    assert len(state["processed_dates"]) == 0
    assert state["first_observation_date"] is None


def test_new_valid_date_after_approval_can_be_processed(tmp_path: Path):
    """Verifies that a valid newly ingested trading session strictly after
    the approval cutoff is scored successfully and activates observation.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    # Ingest new session for 2026-10-19
    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10500.0)

    # Step prospective date 2026-10-19
    res = engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)
    assert res["status"] == "SCORED"
    assert res["candidates_count"] > 0

    state = engine.load_state()
    assert state["first_observation_date"] == "2026-10-19"
    assert state["first_prospective_run_timestamp"] is not None
    assert "2026-10-19" in state["processed_dates"]

    # Operational status must now be active
    status = engine.generate_operational_status(base_dir=tmp_path)
    assert status["operational_status"] == STATUS_OBSERVATION_ACTIVE
    assert status["prospective_lifecycle"]["has_started"] is True


# ==============================================================================
# Requirement 3: Require Valid, Complete Decision-Date Data
# ==============================================================================


def test_missing_bars_fails_closed_independently(tmp_path: Path):
    """Verifies missing daily bars while features exist fails closed with DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    # Insert features for 2026-10-19 without daily_bars
    conn = sqlite3.connect(db_file)
    feat_vals = ", ".join("0.05" for _ in FEATURE_SCHEMA_30)
    conn.execute(f"INSERT INTO features_daily VALUES ('2026-10-19', 'BBCA', {feat_vals});")
    conn.commit()
    conn.close()

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="daily price bars are missing"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)

    # Verify no state was modified
    state = engine.load_state()
    assert len(state["processed_dates"]) == 0
    assert state["first_observation_date"] is None


def test_missing_features_fails_closed_independently(tmp_path: Path):
    """Verifies that missing features while bars exist fails closed with DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    # Insert daily bars for 2026-10-19 without features
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO daily_bars VALUES "
        "('2026-10-19', 'BBCA', 10000.0, 10200.0, 9900.0, 10100.0, 100000.0);"
    )
    conn.commit()
    conn.close()

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="feature rows in features_daily are missing"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)

    state = engine.load_state()
    assert len(state["processed_dates"]) == 0
    assert state["first_observation_date"] is None


def test_infinite_feature_values_fails_closed(tmp_path: Path):
    """Verifies that non-finite (Inf) values in feature rows fail closed with DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)

    # Corrupt one feature with infinity in features_daily
    conn = sqlite3.connect(db_file)
    conn.execute("UPDATE features_daily SET return_1d = 1e300 * 1e300 WHERE date = '2026-10-19';")
    conn.commit()
    conn.close()

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="invalid infinite values"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)


def test_failed_scoring_or_persistence_does_not_create_false_start_record(tmp_path: Path):
    """Verifies that an exception during scoring halts execution and does not create
    a start record or record the date as processed.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)

    for rel_path in RESEARCH_SCORING_ARTIFACTS.values():
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(BrokenModel(), p)

    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(RuntimeError, match="Scoring calculation crashed"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)

    state = engine.load_state()
    assert state["first_observation_date"] is None
    assert state["first_prospective_run_timestamp"] is None
    assert len(state["processed_dates"]) == 0

    status = engine.generate_operational_status(base_dir=tmp_path)
    assert status["operational_status"] == STATUS_APPROVED_PENDING_FIRST_OBSERVATION
    assert status["prospective_lifecycle"]["has_started"] is False


# ==============================================================================
# Requirement 4: Fail Closed on Corrupted Persistent State
# ==============================================================================


def test_missing_state_file_initializes_default(tmp_path: Path):
    """Verifies that if state file does not exist, default state is cleanly initialized."""
    engine = PaperTradingEngine(
        db_path="datasets/stock_signals.db",
        artifacts_dir=tmp_path / "non_existent_artifacts",
    )
    state = engine.load_state()
    assert state["version"] == "1.1"
    assert state["cash"] == 100_000_000.0
    assert state["processed_dates"] == []
    assert state["user_approved"] is False


def test_malformed_json_state_raises_state_integrity_error(tmp_path: Path):
    """Verifies that malformed JSON in paper_trading_state.json raises StateIntegrityError
    and is not overwritten with default state.
    """
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    state_file = art_dir / "paper_trading_state.json"
    corrupt_content = "{ this is invalid json !!! "
    state_file.write_text(corrupt_content, encoding="utf-8")

    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)

    with pytest.raises(StateIntegrityError, match="invalid JSON"):
        engine.load_state()

    # File on disk must NOT have been overwritten
    assert state_file.read_text(encoding="utf-8") == corrupt_content

    # Operational status must report BLOCKED_ON_STATE_CORRUPTION
    status = engine.generate_operational_status(base_dir=tmp_path)
    assert status["operational_status"] == STATUS_BLOCKED_ON_STATE_CORRUPTION
    assert len(status["error_logs"]) > 0


def test_missing_required_fields_in_state_raises_state_integrity_error(tmp_path: Path):
    """Verifies that missing essential fields in state raises StateIntegrityError."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    state_file = art_dir / "paper_trading_state.json"

    # Incomplete state dict
    incomplete_state = {
        "version": "1.1",
        "cash": 100_000_000.0,
        # missing policy_bundle_hash, open_positions, processed_dates, etc.
    }
    state_file.write_text(json.dumps(incomplete_state), encoding="utf-8")

    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)

    with pytest.raises(StateIntegrityError, match="missing required fields"):
        engine.load_state()


def test_incompatible_policy_hash_in_state_raises_state_integrity_error(tmp_path: Path):
    """Verifies that a state with a mismatched policy bundle hash raises StateIntegrityError."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    state_file = art_dir / "paper_trading_state.json"

    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
    valid_state = engine._default_state()
    valid_state["policy_bundle_hash"] = "tampered_policy_hash_0000000000000000000000000000"
    state_file.write_text(json.dumps(valid_state), encoding="utf-8")

    with pytest.raises(StateIntegrityError, match="Incompatible policy bundle hash"):
        engine.load_state()


def test_state_migration_preserves_backup_and_upgrades_schema(tmp_path: Path):
    """Verifies migrate_state creates a timestamped backup and updates schema fields."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    state_file = art_dir / "paper_trading_state.json"

    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
    legacy_state = engine._default_state()
    legacy_state["version"] = "1.0"
    del legacy_state["user_approved"]
    del legacy_state["approval_timestamp"]
    del legacy_state["approval_data_cutoff"]
    legacy_state["cash"] = 85_000_000.0  # custom capital to preserve

    state_file.write_text(json.dumps(legacy_state), encoding="utf-8")

    # Before migration, load_state must fail closed on incompatible schema
    with pytest.raises(StateIntegrityError, match="Incompatible state schema version"):
        engine.load_state()

    # Run authorized migration
    migrated = engine.migrate_state(backup=True)
    assert migrated["version"] == "1.1"
    assert migrated["cash"] == 85_000_000.0
    assert "user_approved" in migrated

    # Verify backup copy was created on disk
    bak_files = list(art_dir.glob("paper_trading_state_backup_*.json"))
    assert len(bak_files) == 1
    bak_data = json.loads(bak_files[0].read_text(encoding="utf-8"))
    assert bak_data["version"] == "1.0"
    assert bak_data["cash"] == 85_000_000.0

    # load_state must now succeed
    loaded = engine.load_state()
    assert loaded["version"] == "1.1"
    assert loaded["cash"] == 85_000_000.0


# ==============================================================================
# Monotonicity, Missed Sessions, and Idempotency
# ==============================================================================


def test_duplicate_and_out_of_order_dates_cannot_alter_portfolio(tmp_path: Path):
    """Verifies that re-running the same date is idempotent, and out-of-order dates are rejected."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    # Ingest session 1: 2026-10-19
    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)

    # Process 2026-10-19
    res1 = engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)
    assert res1["status"] == "SCORED"
    state1 = engine.load_state()
    cash1 = state1["cash"]
    orders1 = len(state1["pending_orders"])

    # Re-run identical date 2026-10-19 -> must return ALREADY_PROCESSED
    res1_dup = engine.step_prospective_date(
        date(2026, 10, 19), user_approved=True, base_dir=tmp_path
    )
    assert res1_dup["status"] == "ALREADY_PROCESSED"
    state1_dup = engine.load_state()
    assert state1_dup["cash"] == cash1
    assert len(state1_dup["pending_orders"]) == orders1

    # Attempt earlier/out-of-order date 2026-10-18 -> must raise InvalidProspectiveDateError
    with pytest.raises(InvalidProspectiveDateError, match="earlier than last processed date"):
        engine.step_prospective_date(date(2026, 10, 18), user_approved=True, base_dir=tmp_path)

    # State remains unmodified
    state_after = engine.load_state()
    assert state_after["cash"] == cash1


def test_missed_session_in_prospective_observation_fails_closed(tmp_path: Path):
    """Verifies skipping a trading session after approval fails closed with MissedSessionError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    # Ingest sessions for 2026-10-19, 2026-10-20, and 2026-10-21
    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)
    add_session_to_test_db(db_file, "2026-10-20", ticker="BBCA", price=10100.0)
    add_session_to_test_db(db_file, "2026-10-21", ticker="BBCA", price=10200.0)

    # Process 2026-10-19
    engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)

    # Skip 2026-10-20 and attempt to jump straight to 2026-10-21
    with pytest.raises(MissedSessionError, match="Missed trading session detected"):
        engine.step_prospective_date(date(2026, 10, 21), user_approved=True, base_dir=tmp_path)

    # Verify state did not record 2026-10-21
    state = engine.load_state()
    assert state["processed_dates"] == ["2026-10-19"]


# ==============================================================================
# Production Champion Fallback Prohibited
# ==============================================================================


def test_production_champion_fallback_remains_strictly_prohibited(tmp_path: Path):
    """Verifies that missing research models fail closed with MissingScoringArtifactError
    and NEVER fall back to production champion models.
    """
    empty_dir = tmp_path / "empty_models"
    empty_dir.mkdir(parents=True, exist_ok=True)

    engine = PaperTradingEngine(
        db_path="datasets/stock_signals.db",
        artifacts_dir=tmp_path / "artifacts",
    )

    with pytest.raises(MissingScoringArtifactError):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=empty_dir)

    status = engine.generate_operational_status(base_dir=empty_dir)
    assert status["operational_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
    assert status["scoring_artifacts_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
    assert status["champion_protection"]["fallback_permitted"] is False
    assert status["champion_protection"]["LOW_PRICE_champion"] == CHAMPION_MODELS["LOW_PRICE"]
    assert status["champion_protection"]["HIGHER_PRICE_champion"] == CHAMPION_MODELS["HIGHER_PRICE"]


def test_first_prospective_session_missed_fails_closed(tmp_path: Path):
    """Verifies that skipping the initial trading session strictly after cutoff
    fails closed with MissedSessionError.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    # Ingest 2026-10-19 and 2026-10-20
    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)
    add_session_to_test_db(db_file, "2026-10-20", ticker="BBCA", price=10100.0)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    # Attempt to skip 2026-10-19 and start directly on 2026-10-20
    with pytest.raises(MissedSessionError, match="Missed initial trading session detected"):
        engine.step_prospective_date(date(2026, 10, 20), user_approved=True, base_dir=tmp_path)

    # State must not record any dates
    state = engine.load_state()
    assert state["processed_dates"] == []
    assert state["first_observation_date"] is None


def test_observation_active_requires_persisted_approval(tmp_path: Path):
    """Verifies OBSERVATION_ACTIVE cannot be reported if user_approved is False,
    even if first_observation_date or processed_dates are present.
    """
    art_dir = tmp_path / "artifacts"
    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
    state = engine._default_state()
    state["user_approved"] = False  # unapproved
    state["first_observation_date"] = "2026-10-19"
    state["first_prospective_run_timestamp"] = "2026-10-19T09:00:00Z"
    state["processed_dates"] = ["2026-10-19"]
    engine.save_state(state)

    status = engine.generate_operational_status()
    # Must NOT report OBSERVATION_ACTIVE
    assert status["operational_status"] != STATUS_OBSERVATION_ACTIVE
    assert status["operational_status"] == STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL
    assert status["prospective_lifecycle"]["has_started"] is False


def test_step_prospective_date_persists_approval_fields(tmp_path: Path):
    """Verifies that running step_prospective_date with user_approved=True
    persists user_approved=True and approval_timestamp into state.
    """
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)
    add_session_to_test_db(db_file, "2026-10-19", ticker="BBCA", price=10000.0)

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    # State has user_approved=False initially
    s0 = engine.load_state()
    assert s0["user_approved"] is False

    res = engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)
    assert res["status"] == "SCORED"

    s1 = engine.load_state()
    assert s1["user_approved"] is True
    assert s1["approval_timestamp"] is not None
    assert s1["first_observation_date"] == "2026-10-19"

    status = engine.generate_operational_status(base_dir=tmp_path)
    assert status["operational_status"] == STATUS_OBSERVATION_ACTIVE


def test_missing_required_feature_columns_fails_closed(tmp_path: Path):
    """Verifies that missing required columns in features_daily raises DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE daily_bars (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (date, ticker)
        );
    """)
    # Omit the last column from FEATURE_SCHEMA_30
    partial_schema = FEATURE_SCHEMA_30[:-1]
    cols = ", ".join(f"{col} REAL" for col in partial_schema)
    cur.execute(
        f"CREATE TABLE features_daily ("
        f"date TEXT NOT NULL, ticker TEXT NOT NULL, {cols}, PRIMARY KEY (date, ticker));"
    )
    cur.execute(
        "INSERT INTO daily_bars VALUES "
        "('2026-10-19', 'BBCA', 10000.0, 10200.0, 9900.0, 10100.0, 100000.0);"
    )
    feat_vals = ", ".join("0.05" for _ in partial_schema)
    cur.execute(f"INSERT INTO features_daily VALUES ('2026-10-19', 'BBCA', {feat_vals});")
    conn.commit()
    conn.close()

    populate_mock_models(tmp_path)
    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="missing required feature columns"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)


def test_date_mismatch_in_bars_fails_closed(tmp_path: Path):
    """Verifies that mismatched dates in daily_bars raises DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    conn = sqlite3.connect(db_file)
    feat_vals = ", ".join("0.05" for _ in FEATURE_SCHEMA_30)
    conn.execute(f"INSERT INTO features_daily VALUES ('2026-10-19', 'BBCA', {feat_vals});")
    conn.commit()
    conn.close()

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="daily price bars are missing"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)


def test_zero_joined_tickers_fails_closed(tmp_path: Path):
    """Verifies that disjoint tickers between features and bars raises DataQualityError."""
    db_file = tmp_path / "test_stock.db"
    create_isolated_test_db(db_file)
    populate_mock_models(tmp_path)

    conn = sqlite3.connect(db_file)
    feat_vals = ", ".join("0.05" for _ in FEATURE_SCHEMA_30)
    conn.execute(f"INSERT INTO features_daily VALUES ('2026-10-19', 'BBCA', {feat_vals});")
    conn.execute(
        "INSERT INTO daily_bars VALUES "
        "('2026-10-19', 'TLKM', 3000.0, 3100.0, 2950.0, 3050.0, 100000.0);"
    )
    conn.commit()
    conn.close()

    engine = PaperTradingEngine(db_path=str(db_file), artifacts_dir=tmp_path / "artifacts")
    engine.approve_observation(cutoff_date="2026-10-16", base_dir=tmp_path)

    with pytest.raises(DataQualityError, match="zero valid joined tickers"):
        engine.step_prospective_date(date(2026, 10, 19), user_approved=True, base_dir=tmp_path)


def test_cli_migrate_state_action(tmp_path: Path):
    """Verifies that running CLI with --migrate-state upgrades legacy state."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    state_file = art_dir / "paper_trading_state.json"

    engine = PaperTradingEngine(db_path="datasets/stock_signals.db", artifacts_dir=art_dir)
    legacy = engine._default_state()
    legacy["version"] = "1.0"
    del legacy["user_approved"]
    del legacy["approval_timestamp"]
    del legacy["approval_data_cutoff"]
    legacy["cash"] = 75_000_000.0
    state_file.write_text(json.dumps(legacy), encoding="utf-8")

    cmd = [
        sys.executable,
        "scripts/run_forward_paper_trading.py",
        "--migrate-state",
        "--artifacts-dir",
        str(art_dir),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0
    assert "STATE MIGRATION COMPLETE" in p.stdout

    migrated = engine.load_state()
    assert migrated["version"] == "1.1"
    assert migrated["cash"] == 75_000_000.0
    assert migrated["user_approved"] is False
