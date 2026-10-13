from datetime import date, timedelta
from pathlib import Path

import pytest

from python.data.provider import MockMarketDataProvider
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.features.repository import FeatureRepository
from python.labels.engine import LabelEngine
from python.labels.repository import LabelRepository
from python.models.registry import ModelRegistry
from python.outcomes.repository import OutcomeRepository
from python.retraining.dataset import RetrainingDatasetAssembler
from python.retraining.gate import PromotionGateManager
from python.retraining.pipeline import (
    RetrainingPipeline,
    RetrainingPipelineConfig,
)
from python.retraining.trigger import (
    RetrainingTriggerConfig,
    RetrainingTriggerEvaluator,
)
from python.signals.repository import SignalRepository


@pytest.fixture
def populated_env(tmp_path: Path):
    db_file = tmp_path / "test_retrain.db"
    db_url = f"sqlite:///{db_file}"
    reg_dir = tmp_path / "models_registry"

    bar_repo = DailyBarRepository(db_url)
    feat_repo = FeatureRepository(db_url)
    lbl_repo = LabelRepository(db_url)
    outcome_repo = OutcomeRepository(db_url)
    signal_repo = SignalRepository(db_url)
    registry = ModelRegistry(registry_dir=reg_dir)

    # 1. Populate mock bars
    tickers = ["BBCA", "BBRI"]
    mock = MockMarketDataProvider(universe=tickers, days=70)
    universe_bars = {}
    all_bars = []
    for t in tickers:
        bars = mock.get_daily_bars(t)
        bar_repo.save_bars(bars)
        universe_bars[t] = bars
        all_bars.extend(bars)

    # 2. Compute & save features and labels
    feat_engine = FeatureEngine()
    feats_by_ticker = feat_engine.compute_universe_features(universe_bars)
    all_feats = []
    for _t, frecs in feats_by_ticker.items():
        feat_repo.save_features(frecs)
        all_feats.extend(frecs)

    lbl_engine = LabelEngine()
    labels = lbl_engine.compute_labels(all_bars)
    lbl_repo.save_labels(labels)

    # 3. Populate synthetic matured outcomes & signals (e.g. 20 signals & outcomes)
    base_d = date(2025, 1, 1)
    for i in range(25):
        d = base_d + timedelta(days=i)
        sig_id = f"sig_test_{i}"
        from python.common.types import SignalOutcomeRecord, SignalRecord

        status = "TP" if i % 2 == 0 else "SL"
        ret = 0.04 if status == "TP" else -0.02
        prob = 0.75 if status == "TP" else 0.25
        sig = SignalRecord(
            signal_id=sig_id,
            ticker="BBCA",
            signal_date=d,
            signal="BUY",
            entry_low=9900.0,
            entry_high=10100.0,
            tp_price=10500.0,
            sl_price=9700.0,
            max_holding_days=10,
            predicted_probability=prob,
            expected_return=0.03,
            score=70.0,
            model_version="v0",
            feature_version="v1.0.0",
            signal_config_version="v1.0.0",
            feature_snapshot={"return_1d": 0.01, "rsi14": 52.0},
        )
        signal_repo.save_signals([sig])
        out = SignalOutcomeRecord(
            outcome_id=f"out_test_{i}",
            signal_id=sig_id,
            ticker="BBCA",
            signal_date=d,
            entry_date=d + timedelta(days=1),
            entry_price=10000.0,
            outcome_status=status,
            realized_return=ret,
            holding_days=3,
            mfe=0.04,
            mae=-0.01,
            exit_date=d + timedelta(days=4),
            exit_price=10000.0 * (1.0 + ret),
            exit_reason="TP_HIT" if status == "TP" else "SL_HIT",
        )
        outcome_repo.save_outcome(out)

    return {
        "db_url": db_url,
        "reg_dir": reg_dir,
        "bar_repo": bar_repo,
        "feat_repo": feat_repo,
        "lbl_repo": lbl_repo,
        "outcome_repo": outcome_repo,
        "signal_repo": signal_repo,
        "registry": registry,
    }


def test_retraining_pipeline_end_to_end(populated_env):
    reg = populated_env["registry"]
    outcome_repo = populated_env["outcome_repo"]
    signal_repo = populated_env["signal_repo"]
    feat_repo = populated_env["feat_repo"]
    lbl_repo = populated_env["lbl_repo"]

    # 1. Trigger Check Only
    trigger_cfg = RetrainingTriggerConfig(min_matured_samples=100)
    trigger_eval = RetrainingTriggerEvaluator(
        config=trigger_cfg,
        outcome_repo=outcome_repo,
        signal_repo=signal_repo,
    )
    assembler = RetrainingDatasetAssembler(
        outcome_repo=outcome_repo,
        signal_repo=signal_repo,
        feature_repo=feat_repo,
        label_repo=lbl_repo,
    )
    gate_mgr = PromotionGateManager(registry=reg)

    config = RetrainingPipelineConfig(
        min_matured_samples=100,
        algorithm="lightgbm",
        auto_promote=True,
    )

    pipeline = RetrainingPipeline(
        config=config,
        trigger_evaluator=trigger_eval,
        dataset_assembler=assembler,
        gate_manager=gate_mgr,
        registry=reg,
    )

    # Without force and 25 matured outcomes < 100 threshold -> SKIPPED
    res_skipped = pipeline.run(force=False)
    assert res_skipped.status == "SKIPPED"
    assert res_skipped.triggered is False

    # Check trigger only
    res_trig = pipeline.run(check_trigger_only=True)
    assert res_trig.status == "TRIGGER_CHECKED"

    # Dry run with force=True
    res_dry = pipeline.run(force=True, dry_run=True)
    assert res_dry.status == "SUCCESS"
    assert res_dry.triggered is True
    assert res_dry.train_sample_count > 0
    assert res_dry.test_sample_count > 0
    assert len(reg.list_models()) == 0  # No model persisted in dry-run

    # Full execution with force=True and auto_promote=True (Initial Bootstrap)
    res_full = pipeline.run(force=True, dry_run=False, auto_promote=True)
    assert res_full.status == "SUCCESS"
    assert res_full.promoted is True  # Bootstrap model promoted to champion
    assert res_full.challenger_version is not None
    assert Path(res_full.artifact_path).is_file()

    # Verify model is champion in registry
    champ_obj, champ_meta = reg.get_champion()
    assert champ_meta.model_version == res_full.challenger_version
    assert champ_meta.status == "champion"

    # Now train second model as challenger
    res_challenger2 = pipeline.run(
        force=True,
        dry_run=False,
        auto_promote=False,
    )
    assert res_challenger2.status == "SUCCESS"
    assert res_challenger2.champion_version == champ_meta.model_version
    assert res_challenger2.gate_result is not None

    # Rollback test
    # Promote challenger2 first
    gate_mgr.promote_challenger(
        res_challenger2.challenger_version, archive_status="archived_champion"
    )
    _, new_champ_meta = reg.get_champion()
    assert new_champ_meta.model_version == res_challenger2.challenger_version

    # Now rollback back to previous champion
    restored_meta = gate_mgr.rollback(demote_current_to="retired")
    assert restored_meta.model_version == champ_meta.model_version
    _, current_champ = reg.get_champion()
    assert current_champ.model_version == champ_meta.model_version


def test_retrain_cli_options(populated_env):
    import subprocess
    import sys

    db_url = populated_env["db_url"]

    # 1. Test --check-trigger-only with JSON format
    cmd_check = [
        sys.executable,
        "-m",
        "scripts.retrain_model",
        "--db-url",
        db_url,
        "--check-trigger-only",
        "--output-format",
        "json",
    ]
    res_check = subprocess.run(cmd_check, capture_output=True, text=True, check=False)
    assert res_check.returncode == 0
    assert "should_retrain" in res_check.stdout

    # 2. Test --dry-run and --force with table format
    cmd_dry = [
        sys.executable,
        "-m",
        "scripts.retrain_model",
        "--db-url",
        db_url,
        "--force",
        "--dry-run",
        "--algorithm",
        "lightgbm",
        "--output-format",
        "table",
    ]
    res_dry = subprocess.run(cmd_dry, capture_output=True, text=True, check=False)
    assert res_dry.returncode == 0
    assert "Retraining Pipeline (Phase 11)" in res_dry.stdout

