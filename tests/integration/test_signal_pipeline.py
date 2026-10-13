import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from python.common.types import DailyBar, SignalConfig
from python.data.repository import DailyBarRepository
from python.models.baseline import LogisticRegressionBaseline
from python.models.registry import ModelMetadata, ModelRegistry
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository


def test_end_to_end_signal_pipeline(tmp_path: Path):
    db_file = tmp_path / "test_signals_pipeline.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # 1. Setup mock bar data in SQLite
    bar_repo = DailyBarRepository(db_url)
    start_d = date(2026, 8, 1)

    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    all_bars = []
    for t_idx, ticker in enumerate(tickers):
        base_p = 5000.0 + t_idx * 1500.0
        for i in range(40):
            d = start_d + timedelta(days=i)
            p = base_p + (i * 10.0)
            all_bars.append(
                DailyBar(
                    ticker=ticker,
                    date=d,
                    open=p,
                    high=p + 20.0,
                    low=p - 15.0,
                    close=p + 5.0,
                    volume=2_000_000.0,
                    value=p * 2_000_000.0,
                    provider="test",
                )
            )

    bar_repo.save_bars(all_bars)
    target_date = all_bars[-1].date

    # 2. Setup trained model in registry
    registry_dir = tmp_path / "models_registry"
    registry = ModelRegistry(registry_dir=registry_dir)

    clf = LogisticRegressionBaseline()
    # Dummy fit with 2 samples
    clf.fit(
        X=[[0.01, 1.0], [-0.01, 0.5]],
        y=[1, 0],
        feature_names=["return_1d", "volume_ratio_20d"],
    )

    meta = ModelMetadata(
        model_version="champ_clf_pipeline_v1",
        algorithm="logistic",
        task="classification",
        training_start="2026-08-01",
        training_end="2026-08-20",
        status="champion",
        feature_names=["return_1d", "volume_ratio_20d"],
    )
    registry.save_model(clf, meta)

    # 3. Run SignalEngine
    config = SignalConfig(top_n=3, min_probability=0.30)
    engine = SignalEngine(
        config=config,
        model_registry=registry,
        bar_repo=bar_repo,
    )

    signals = engine.generate_signals(
        signal_date=target_date,
        universe=tickers,
        config=config,
    )

    assert len(signals) == 3
    assert signals[0].signal_date == target_date
    assert signals[0].model_version == "champ_clf_pipeline_v1"
    assert signals[0].entry_low <= signals[0].entry_high
    assert signals[0].tp_price > signals[0].entry_high
    assert signals[0].sl_price < signals[0].entry_low

    # 4. Save to SignalRepository
    sig_repo = SignalRepository(db_url)
    saved = sig_repo.save_signals(signals)
    assert saved == 3

    # Query from DB
    persisted = sig_repo.get_signals_by_date(target_date)
    assert len(persisted) == 3
    assert persisted[0].signal_id == signals[0].signal_id
    assert persisted[0].score == signals[0].score


def test_cli_generate_signals_execution(tmp_path: Path):
    db_file = tmp_path / "cli_signals.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # Setup 30 bars in DB for BBCA
    bar_repo = DailyBarRepository(db_url)
    start_d = date(2026, 8, 1)
    bars = []
    for i in range(30):
        d = start_d + timedelta(days=i)
        p = 10000.0 + i * 50.0
        bars.append(
            DailyBar(
                ticker="BBCA",
                date=d,
                open=p,
                high=p + 100.0,
                low=p - 50.0,
                close=p + 20.0,
                volume=1_500_000.0,
                provider="test",
            )
        )
    bar_repo.save_bars(bars)
    target_date_str = str(bars[-1].date)

    # Setup dummy champion model in temporary registry
    registry_dir = tmp_path / "cli_registry"
    registry = ModelRegistry(registry_dir=registry_dir)
    clf = LogisticRegressionBaseline()
    clf.fit(X=[[0.01], [-0.01]], y=[1, 0], feature_names=["return_1d"])
    meta = ModelMetadata(
        model_version="cli_test_champ",
        algorithm="logistic",
        task="classification",
        training_start="2026-08-01",
        training_end="2026-08-20",
        status="champion",
        feature_names=["return_1d"],
    )
    registry.save_model(clf, meta)

    python_exe = sys.executable

    # Run CLI with --format json
    cmd = [
        python_exe,
        "-m",
        "scripts.generate_signals",
        "--db-url",
        db_url,
        "--date",
        target_date_str,
        "--tickers",
        "BBCA",
        "--min-prob",
        "0.10",
        "--format",
        "json",
        "--save-db",
    ]

    env_vars = {
        "MODEL_REGISTRY_PATH": str(registry_dir),
        "PYTHONPATH": ".",
    }
    import os

    merged_env = {**os.environ, **env_vars}

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )

    assert result.returncode == 0, f"CLI stderr: {result.stderr}"

    # Parse JSON output from stdout
    output_json = json.loads(result.stdout)
    assert isinstance(output_json, list)
    assert len(output_json) == 1
    sig_dict = output_json[0]
    assert sig_dict["ticker"] == "BBCA"
    assert sig_dict["signal"] == "BUY"
    assert sig_dict["signal_date"] == target_date_str

    # Verify DB persistence
    sig_repo = SignalRepository(db_url)
    assert sig_repo.count_signals() == 1

    # Test CLI with --use-champion
    cmd_champ = [
        python_exe,
        "-m",
        "scripts.generate_signals",
        "--db-url",
        db_url,
        "--date",
        target_date_str,
        "--tickers",
        "BBCA",
        "--use-champion",
        "--min-prob",
        "0.10",
        "--format",
        "json",
    ]
    res_champ = subprocess.run(
        cmd_champ,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )
    assert res_champ.returncode == 0
    champ_json = json.loads(res_champ.stdout)
    assert len(champ_json) == 1
    assert champ_json[0]["model_version"] == "cli_test_champ"

    # Test mutually exclusive flags error
    cmd_conflict = [
        python_exe,
        "-m",
        "scripts.generate_signals",
        "--db-url",
        db_url,
        "--use-champion",
        "--model-version",
        "cli_test_champ",
    ]
    res_conflict = subprocess.run(
        cmd_conflict,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )
    assert res_conflict.returncode != 0
    assert "Cannot specify both --use-champion and --model-version" in res_conflict.stderr
