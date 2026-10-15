import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from python.common.types import DailyBar, SignalRecord
from python.data.repository import DailyBarRepository
from python.outcomes.dataset import build_matured_outcomes_dataset, export_matured_dataset
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository
from scripts.resolve_outcomes import run_resolve_outcomes


def test_full_outcome_pipeline_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_lifecycle.db"
    db_url = f"sqlite:///{db_file}"

    bar_repo = DailyBarRepository(db_url)
    sig_repo = SignalRepository(db_url)
    out_repo = OutcomeRepository(db_url)

    # 1. Create and save Signals
    signal_date = date(2026, 10, 1)
    sig1 = SignalRecord(
        signal_id="sig-bbca-001",
        ticker="BBCA",
        signal_date=signal_date,
        signal="BUY",
        entry_low=9900.0,
        entry_high=10100.0,
        tp_price=10500.0,
        sl_price=9500.0,
        max_holding_days=10,
        predicted_probability=0.78,
        expected_return=0.06,
        score=88.5,
        model_version="lgbm_champion_v1",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot={"rsi14": 55.4, "atr14": 150.0, "return_5d": 0.025},
    )
    sig2 = SignalRecord(
        signal_id="sig-bbri-002",
        ticker="BBRI",
        signal_date=signal_date,
        signal="BUY",
        entry_low=4900.0,
        entry_high=5100.0,
        tp_price=5300.0,
        sl_price=4700.0,
        max_holding_days=10,
        predicted_probability=0.68,
        expected_return=0.04,
        score=75.0,
        model_version="lgbm_champion_v1",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot={"rsi14": 48.2, "atr14": 75.0, "return_5d": -0.01},
    )
    sig_repo.save_signals([sig1, sig2])

    # 2. Ingest forward price bars
    # BBCA: Day 1 (Oct 2) entry at 10000, Day 2 (Oct 3) hits TP at 10600
    bbca_bars = [
        DailyBar(
            ticker="BBCA",
            date=date(2026, 10, 2),
            open=10000.0,
            high=10200.0,
            low=9900.0,
            close=10150.0,
            volume=50000.0,
        ),
        DailyBar(
            ticker="BBCA",
            date=date(2026, 10, 3),
            open=10200.0,
            high=10600.0,
            low=10100.0,
            close=10550.0,
            volume=60000.0,
        ),
    ]

    # BBRI: Day 1 (Oct 2) entry at 5000, Day 2 (Oct 3) hits SL at 4650
    bbri_bars = [
        DailyBar(
            ticker="BBRI",
            date=date(2026, 10, 2),
            open=5000.0,
            high=5050.0,
            low=4950.0,
            close=5000.0,
            volume=30000.0,
        ),
        DailyBar(
            ticker="BBRI",
            date=date(2026, 10, 3),
            open=4900.0,
            high=4950.0,
            low=4650.0,
            close=4680.0,
            volume=40000.0,
        ),
    ]

    bar_repo.save_bars(bbca_bars)
    bar_repo.save_bars(bbri_bars)

    # 3. Run OutcomeEngine to resolve signals
    engine = OutcomeEngine(
        bar_repo=bar_repo,
        signal_repo=sig_repo,
        outcome_repo=out_repo,
    )

    results = engine.resolve_all_signals(save=True)
    assert len(results) == 2

    # Check BBCA resolution
    bbca_outcome = out_repo.get_outcome_by_signal_id("sig-bbca-001")
    assert bbca_outcome is not None
    assert bbca_outcome.outcome_status == "TP"
    assert bbca_outcome.holding_days == 2
    assert bbca_outcome.entry_price == 10000.0
    assert bbca_outcome.exit_price == pytest.approx(10500.0)
    assert bbca_outcome.realized_return == pytest.approx(0.05)
    assert bbca_outcome.mfe == pytest.approx(0.06)

    bbca_snaps = out_repo.get_snapshots_by_signal_id("sig-bbca-001")
    assert len(bbca_snaps) == 2
    assert bbca_snaps[0].holding_day == 1
    assert bbca_snaps[1].holding_day == 2

    # Check BBRI resolution
    bbri_outcome = out_repo.get_outcome_by_signal_id("sig-bbri-002")
    assert bbri_outcome is not None
    assert bbri_outcome.outcome_status == "SL"
    assert bbri_outcome.holding_days == 2
    assert bbri_outcome.entry_price == 5000.0
    assert bbri_outcome.exit_price == pytest.approx(4700.0)
    assert bbri_outcome.realized_return == pytest.approx(-0.06)

    # 4. Extract Matured Dataset
    df = build_matured_outcomes_dataset(out_repo, sig_repo)
    assert len(df) == 2
    assert set(df["ticker"]) == {"BBCA", "BBRI"}

    # Verify column presence
    assert "binary_target" in df.columns
    assert "predicted_probability" in df.columns
    assert "model_version" in df.columns
    assert "rsi14" in df.columns
    assert "atr14" in df.columns

    # Verify binary target logic
    bbca_row = df[df["ticker"] == "BBCA"].iloc[0]
    bbri_row = df[df["ticker"] == "BBRI"].iloc[0]
    assert bbca_row["binary_target"] == 1
    assert bbri_row["binary_target"] == 0
    assert bbca_row["rsi14"] == pytest.approx(55.4)

    # 5. Export to CSV and JSON
    csv_path = tmp_path / "matured.csv"
    json_path = tmp_path / "matured.json"

    export_matured_dataset(df, csv_path, format="csv")
    export_matured_dataset(df, json_path, format="json")

    assert csv_path.is_file()
    assert json_path.is_file()

    # Read back CSV
    read_csv = pd.read_csv(csv_path)
    assert len(read_csv) == 2
    assert "binary_target" in read_csv.columns

    # Read back JSON
    with open(json_path, encoding="utf-8") as f:
        read_json = json.load(f)
    assert len(read_json) == 2
    assert read_json[0]["ticker"] in ["BBCA", "BBRI"]


def test_cli_resolve_outcomes_pipeline(tmp_path: Path):
    db_file = tmp_path / "cli_test.db"
    db_url = f"sqlite:///{db_file}"

    bar_repo = DailyBarRepository(db_url)
    sig_repo = SignalRepository(db_url)

    # Save signal
    sig = SignalRecord(
        signal_id="sig-tlkm-001",
        ticker="TLKM",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        entry_low=3000.0,
        entry_high=3100.0,
        tp_price=3200.0,
        sl_price=2900.0,
        max_holding_days=5,
        predicted_probability=0.80,
        score=90.0,
        model_version="champion",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot={"return_1d": 0.01},
    )
    sig_repo.save_signals([sig])

    # Save bars
    bar_repo.save_bars(
        [
            DailyBar(
                ticker="TLKM",
                date=date(2026, 10, 2),
                open=3050.0,
                high=3250.0,
                low=3000.0,
                close=3210.0,
                volume=100000.0,
            )
        ]
    )

    export_file = tmp_path / "cli_export.csv"

    # Invoke CLI runner function directly
    exit_code = run_resolve_outcomes(
        save_db=True,
        export_matured="csv",
        export_path=str(export_file),
        database_url=db_url,
    )
    assert exit_code == 0
    assert export_file.is_file()

    df_exported = pd.read_csv(export_file)
    assert len(df_exported) == 1
    assert df_exported.iloc[0]["ticker"] == "TLKM"
    assert df_exported.iloc[0]["outcome_status"] == "TP"


def test_outcome_pipeline_dual_mode_and_breakout_integration(tmp_path: Path):
    """Integration test verifying dual-mode filtering and breakout progression through CLI."""
    db_file = tmp_path / "dual_mode_cli.db"
    db_url = f"sqlite:///{db_file}"

    bar_repo = DailyBarRepository(db_url)
    sig_repo = SignalRepository(db_url)
    out_repo = OutcomeRepository(db_url)

    # 1. Create one LOW_PRICE IMMEDIATE signal and one HIGHER_PRICE BREAKOUT signal
    sig_low = SignalRecord(
        signal_id="sig-goto-low",
        ticker="GOTO",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        status="BUY",
        entry_policy="IMMEDIATE",
        reference_price=80.0,
        entry_low=79.0,
        entry_high=81.0,
        tp_price=85.0,
        sl_price=77.0,
        max_holding_days=5,
        predicted_probability=0.75,
        expected_return=0.05,
        score=85.0,
        model_version="lgbm_low_v1",
        mode="LOW_PRICE",
        feature_snapshot={"rsi14": 45.0},
    )
    sig_high = SignalRecord(
        signal_id="sig-bbca-high",
        ticker="BBCA",
        signal_date=date(2026, 10, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=10000.0,
        entry_low=10600.0,
        entry_high=10800.0,
        tp_price=11200.0,
        sl_price=10200.0,
        max_holding_days=5,
        predicted_probability=0.70,
        expected_return=0.04,
        score=80.0,
        model_version="lgbm_high_v1",
        mode="HIGHER_PRICE",
        feature_snapshot={"rsi14": 60.0},
    )
    sig_repo.save_signals([sig_low, sig_high])

    # 2. Ingest forward price bars
    # GOTO: Day 1 (Oct 2) opens at 80.0, hits TP at 86.0
    goto_bars = [
        DailyBar(
            ticker="GOTO",
            date=date(2026, 10, 2),
            open=80.0,
            high=86.0,
            low=79.5,
            close=85.5,
            volume=500_000.0,
        ),
    ]

    # BBCA: Day 1 (Oct 2) stays below breakout (High 10400 < 10600)
    #       Day 2 (Oct 3) breaks out (High 10700 >= 10600)
    #       Day 3 (Oct 4) hits TP (High 11300 >= 11200)
    bbca_bars = [
        DailyBar(
            ticker="BBCA",
            date=date(2026, 10, 2),
            open=10100.0,
            high=10400.0,
            low=10000.0,
            close=10300.0,
            volume=50_000.0,
        ),
        DailyBar(
            ticker="BBCA",
            date=date(2026, 10, 3),
            open=10300.0,
            high=10700.0,
            low=10250.0,
            close=10650.0,
            volume=60_000.0,
        ),
        DailyBar(
            ticker="BBCA",
            date=date(2026, 10, 4),
            open=10700.0,
            high=11300.0,
            low=10600.0,
            close=11250.0,
            volume=70_000.0,
        ),
    ]
    bar_repo.save_bars(goto_bars)
    bar_repo.save_bars(bbca_bars)

    # 3. Test CLI runner with --mode LOW_PRICE
    csv_low = tmp_path / "low_outcomes.csv"
    code_low = run_resolve_outcomes(
        mode="LOW_PRICE",
        save_db=True,
        export_matured="csv",
        export_path=str(csv_low),
        database_url=db_url,
    )
    assert code_low == 0
    df_low = pd.read_csv(csv_low)
    assert len(df_low) == 1
    assert df_low.iloc[0]["ticker"] == "GOTO"
    assert df_low.iloc[0]["mode"] == "LOW_PRICE"
    assert df_low.iloc[0]["outcome_status"] == "TP"

    # 4. Test CLI runner with --mode HIGHER_PRICE
    csv_high = tmp_path / "high_outcomes.csv"
    code_high = run_resolve_outcomes(
        mode="HIGHER_PRICE",
        save_db=True,
        export_matured="csv",
        export_path=str(csv_high),
        database_url=db_url,
    )
    assert code_high == 0
    df_high = pd.read_csv(csv_high)
    assert len(df_high) == 1
    assert df_high.iloc[0]["ticker"] == "BBCA"
    assert df_high.iloc[0]["mode"] == "HIGHER_PRICE"
    assert df_high.iloc[0]["outcome_status"] == "TP"
    assert df_high.iloc[0]["entry_price"] == pytest.approx(10600.0)
    assert df_high.iloc[0]["entry_date"] == "2026-10-03"

    # Check snapshots in DB for BBCA
    snaps = out_repo.get_snapshots_by_signal_id("sig-bbca-high")
    assert len(snaps) == 2
    assert snaps[0].holding_day == 1
    assert snaps[0].snapshot_date == date(2026, 10, 3)
    assert snaps[1].holding_day == 2
    assert snaps[1].snapshot_date == date(2026, 10, 4)


def test_outcome_engine_standalone_decoupling():
    """Verify OutcomeEngine runs as standalone service without ML or FeatureEngine imports."""
    import sys

    # Confirm OutcomeEngine and repository modules do not import ML or feature modules
    outcome_engine_mod = sys.modules.get("python.outcomes.engine")
    assert outcome_engine_mod is not None

    # Check imported symbols / module dictionary: no feature engine or ML model registry
    engine_globals = vars(outcome_engine_mod)
    assert "FeatureEngine" not in engine_globals
    assert "SignalEngine" not in engine_globals
    assert "ModelRegistry" not in engine_globals
    assert "LightGBM" not in engine_globals

