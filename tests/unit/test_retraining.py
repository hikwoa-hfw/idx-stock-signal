from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from python.common.types import (
    ComparisonRecommendation,
    EvaluationReport,
    PredictionMetrics,
    SignalOutcomeRecord,
    SignalRecord,
    TradingMetrics,
)
from python.models.comparator import ModelComparator, PromotionGateConfig
from python.models.dataset import DEFAULT_FEATURE_COLUMNS
from python.models.registry import ModelMetadata, ModelRegistry
from python.retraining.dataset import RetrainingDatasetAssembler
from python.retraining.gate import PromotionGateManager
from python.retraining.trigger import (
    RetrainingTriggerConfig,
    RetrainingTriggerEvaluator,
)


class MockOutcomeRepo:
    def __init__(self, outcomes: Optional[list[SignalOutcomeRecord]] = None) -> None:
        self.outcomes = outcomes or []

    def get_matured_outcomes(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        ticker: Optional[str] = None,
    ) -> list[SignalOutcomeRecord]:
        res = self.outcomes
        if start_date:
            res = [o for o in res if o.signal_date >= start_date]
        if end_date:
            res = [o for o in res if o.signal_date <= end_date]
        if ticker:
            clean = ticker.strip().upper().removesuffix(".JK")
            res = [o for o in res if o.ticker == clean]
        return res


class MockSignalRepo:
    def __init__(self, signals: Optional[list[SignalRecord]] = None) -> None:
        self.signals = {s.signal_id: s for s in (signals or [])}

    def get_signal_by_id(self, signal_id: str) -> Optional[SignalRecord]:
        return self.signals.get(signal_id)


def _make_dummy_outcome(
    idx: int,
    status: str = "TP",
    ret: float = 0.04,
    d: Optional[date] = None,
) -> SignalOutcomeRecord:
    sig_d = d or (date(2025, 1, 1) + timedelta(days=idx))
    return SignalOutcomeRecord(
        outcome_id=f"out_{idx}",
        signal_id=f"sig_{idx}",
        ticker="BBCA",
        signal_date=sig_d,
        entry_date=sig_d + timedelta(days=1),
        entry_price=10000.0,
        outcome_status=status,
        realized_return=ret,
        holding_days=3,
        mfe=0.05,
        mae=-0.01,
        exit_date=sig_d + timedelta(days=4),
        exit_price=10000.0 * (1.0 + ret),
        exit_reason="TP_HIT" if status == "TP" else "SL_HIT",
    )


def _make_dummy_signal(
    idx: int,
    prob: float = 0.70,
    d: Optional[date] = None,
) -> SignalRecord:
    sig_d = d or (date(2025, 1, 1) + timedelta(days=idx))
    return SignalRecord(
        signal_id=f"sig_{idx}",
        ticker="BBCA",
        signal_date=sig_d,
        signal="BUY",
        entry_low=9900.0,
        entry_high=10100.0,
        tp_price=10500.0,
        sl_price=9700.0,
        max_holding_days=10,
        predicted_probability=prob,
        expected_return=0.03,
        score=75.0,
        model_version="champ_v1",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot={"return_1d": 0.01, "rsi14": 55.0},
    )


# ==============================================================================
# 1. TRIGGER TESTS
# ==============================================================================


def test_trigger_volume_threshold_reached():
    outcomes = [_make_dummy_outcome(i) for i in range(250)]
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(min_matured_samples=200),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(),
    )
    result = evaluator.evaluate()
    assert result.should_retrain is True
    assert result.matured_count == 250
    assert any("Volume trigger" in r for r in result.reasons)


def test_trigger_volume_threshold_not_reached():
    outcomes = [_make_dummy_outcome(i) for i in range(50)]
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(min_matured_samples=200),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(),
    )
    result = evaluator.evaluate()
    assert result.should_retrain is False
    assert result.matured_count == 50
    assert "Threshold not met" in result.reasons[0]


def test_trigger_forced_manual():
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(min_matured_samples=200),
        outcome_repo=MockOutcomeRepo([]),
        signal_repo=MockSignalRepo(),
    )
    result = evaluator.evaluate(force=True)
    assert result.should_retrain is True
    assert result.matured_count == 0
    assert any("Manual / forced trigger" in r for r in result.reasons)


def test_trigger_performance_degradation_win_rate():
    # 20 consecutive losses -> win rate 0.0%, below floor 0.45
    outcomes = [_make_dummy_outcome(i, status="SL", ret=-0.03) for i in range(20)]
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(
            min_matured_samples=200,
            rolling_window_size=20,
            win_rate_safety_floor=0.45,
        ),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(),
    )
    result = evaluator.evaluate()
    assert result.should_retrain is True
    assert result.rolling_win_rate == 0.0
    assert any("Rolling win rate" in r for r in result.reasons)


def test_trigger_performance_degradation_brier_score():
    # High confidence BUY (prob=0.90) but all signals hit SL (y=0) -> Brier = (0.9-0)^2 = 0.81
    outcomes = [_make_dummy_outcome(i, status="SL", ret=-0.03) for i in range(20)]
    signals = [_make_dummy_signal(i, prob=0.90) for i in range(20)]
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(
            min_matured_samples=200,
            rolling_window_size=20,
            brier_safety_floor=0.25,
            win_rate_safety_floor=0.0,  # disable win rate check to isolate brier check
        ),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(signals),
    )
    result = evaluator.evaluate()
    assert result.should_retrain is True
    assert result.rolling_brier is not None
    assert result.rolling_brier > 0.25
    assert any("Rolling Brier score" in r for r in result.reasons)


def test_trigger_healthy_metrics_no_trigger():
    # 20 trades: 14 TP (70% win rate), prob=0.75 for TP and prob=0.25 for SL -> low Brier
    outcomes = []
    signals = []
    for i in range(20):
        if i < 14:
            outcomes.append(_make_dummy_outcome(i, status="TP", ret=0.04))
            signals.append(_make_dummy_signal(i, prob=0.80))
        else:
            outcomes.append(_make_dummy_outcome(i, status="SL", ret=-0.02))
            signals.append(_make_dummy_signal(i, prob=0.20))

    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(
            min_matured_samples=200,
            rolling_window_size=20,
            brier_safety_floor=0.25,
            win_rate_safety_floor=0.45,
        ),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(signals),
    )
    result = evaluator.evaluate()
    assert result.should_retrain is False
    assert result.rolling_win_rate == 0.70
    assert result.rolling_brier < 0.25
    assert "summary" in dir(result)
    assert "[IDLE]" in result.summary()


# ==============================================================================
# 2. DATASET ASSEMBLY TESTS
# ==============================================================================


def test_dataset_assembler_merge_historical_and_outcomes():
    assembler = RetrainingDatasetAssembler(
        feature_cols=["return_1d", "rsi14"],
        exclude_ambiguous=True,
    )
    hist_df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "date": "2025-01-01",
                "binary_target": 0,
                "realized_return": -0.01,
                "return_1d": 0.005,
                "rsi14": 45.0,
            },
            {
                "ticker": "BBRI",
                "date": "2025-01-01",
                "binary_target": 1,
                "realized_return": 0.03,
                "return_1d": 0.02,
                "rsi14": 55.0,
            },
        ]
    )
    # Outcome updates BBCA with real matured result and adds BMRI
    outcomes_df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "signal_date": "2025-01-01",
                "binary_target": 1,
                "realized_return": 0.04,
                "outcome_status": "TP",
                "return_1d": 0.005,
                "rsi14": 45.0,
            },
            {
                "ticker": "BMRI",
                "signal_date": "2025-01-02",
                "binary_target": 1,
                "realized_return": 0.02,
                "outcome_status": "TP",
                "return_1d": 0.015,
                "rsi14": 60.0,
            },
        ]
    )

    dataset = assembler.assemble_from_dfs(hist_df, outcomes_df)
    assert len(dataset) == 3
    # Check deduplication: BBCA updated to outcome realized_return 0.04
    bbca_mask = (dataset.tickers == "BBCA") & (dataset.dates == date(2025, 1, 1))
    assert dataset.y_return[bbca_mask][0] == 0.04
    assert dataset.y[bbca_mask][0] == 1


def test_dataset_assembler_handles_empty_dfs():
    assembler = RetrainingDatasetAssembler()
    dataset = assembler.assemble_from_dfs(pd.DataFrame(), pd.DataFrame())
    assert len(dataset) == 0
    assert dataset.X.shape == (0, len(DEFAULT_FEATURE_COLUMNS))
    assert dataset.feature_names == DEFAULT_FEATURE_COLUMNS


def test_dataset_assembler_imputes_missing_features():
    assembler = RetrainingDatasetAssembler(feature_cols=["return_1d", "rsi14"])
    df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "date": "2025-01-01",
                "binary_target": 1,
                "realized_return": 0.02,
                "return_1d": None,  # Missing
                "rsi14": 50.0,
            },
            {
                "ticker": "BBCA",
                "date": "2025-01-02",
                "binary_target": 0,
                "realized_return": -0.01,
                "return_1d": 0.02,
                "rsi14": 60.0,
            },
        ]
    )
    dataset = assembler.assemble_from_dfs(df, pd.DataFrame())
    assert len(dataset) == 2
    # Verify no NaN remains in X
    assert not np.isnan(dataset.X).any()


def test_dataset_assembler_walk_forward_purge_window():
    assembler = RetrainingDatasetAssembler(feature_cols=["return_1d", "rsi14"], purge_days=10)
    # Generate 60 days of sequential records
    rows = []
    base_d = date(2025, 1, 1)
    for i in range(60):
        d = base_d + timedelta(days=i)
        rows.append(
            {
                "ticker": "BBCA",
                "date": d,
                "binary_target": 1 if i % 2 == 0 else 0,
                "realized_return": 0.02 if i % 2 == 0 else -0.01,
                "return_1d": 0.01,
                "rsi14": 50.0,
            }
        )
    dataset = assembler.assemble_from_dfs(pd.DataFrame(rows), pd.DataFrame())
    train_ds, val_ds, test_ds = assembler.split_walk_forward(
        dataset, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, purge_days=10
    )

    assert len(train_ds) > 0
    assert len(test_ds) > 0
    max_train_date = max(train_ds.dates)
    if val_ds and len(val_ds) > 0:
        min_val_date = min(val_ds.dates)
        assert (min_val_date - max_train_date).days >= 10
        max_val_date = max(val_ds.dates)
        min_test_date = min(test_ds.dates)
        assert (min_test_date - max_val_date).days >= 10
    else:
        min_test_date = min(test_ds.dates)
        assert (min_test_date - max_train_date).days >= 10


# ==============================================================================
# 3. PROMOTION GATE & ROLLBACK TESTS
# ==============================================================================


def _create_mock_report(
    ver: str,
    pf: float = 1.5,
    wr: float = 0.55,
    brier: float = 0.18,
    dd: float = 0.08,
    sample_size: int = 50,
) -> EvaluationReport:
    return EvaluationReport(
        model_version=ver,
        sample_size=sample_size,
        trading_metrics=TradingMetrics(
            profit_factor=pf,
            win_rate=wr,
            max_drawdown=dd,
            expectancy=0.01,
            total_trades=sample_size,
        ),
        prediction_metrics=PredictionMetrics(
            brier_score=brier,
            log_loss=0.45,
            roc_auc=0.70,
            ece=0.03,
            accuracy=0.60,
        ),
    )


def test_gate_initial_bootstrap_no_champion(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    gate_mgr = PromotionGateManager(registry=registry)

    result = gate_mgr.evaluate_candidate(
        challenger_version="challenger_init_v1",
        X_test=pd.DataFrame({"f1": [1.0, 2.0]}),
        y_test=np.array([1, 0]),
        returns_test=np.array([0.02, -0.01]),
    )
    assert result.passed is True
    assert result.recommendation == ComparisonRecommendation.PROMOTE.value
    assert result.champion_version is None


def test_gate_promotes_when_criteria_met():
    comparator = ModelComparator(
        config=PromotionGateConfig(
            min_sample_size=30,
            min_profit_factor_improvement=0.05,
            max_brier_worsening=0.0,
            max_drawdown_increase=0.0,
        )
    )
    champ_rep = _create_mock_report("champ", pf=1.50, brier=0.20, dd=0.10, sample_size=50)
    chall_rep = _create_mock_report("chall", pf=1.65, brier=0.18, dd=0.08, sample_size=50)

    report = comparator.compare_reports(champ_rep, chall_rep)
    assert report.recommendation == ComparisonRecommendation.PROMOTE.value
    assert any("Promotion gate passed" in r for r in report.rationale)


def test_gate_rejects_when_profit_factor_or_drawdown_worse():
    comparator = ModelComparator(config=PromotionGateConfig(min_sample_size=30))
    # Challenger has worse profit factor (1.40 vs 1.50) and worse drawdown (0.15 vs 0.10)
    champ_rep = _create_mock_report("champ", pf=1.50, brier=0.20, dd=0.10, sample_size=50)
    chall_rep = _create_mock_report("chall", pf=1.40, brier=0.20, dd=0.15, sample_size=50)

    report = comparator.compare_reports(champ_rep, chall_rep)
    assert report.recommendation == ComparisonRecommendation.REJECT.value
    assert any("Promotion rejected" in r for r in report.rationale)


def test_gate_insufficient_sample_size_inconclusive():
    comparator = ModelComparator(config=PromotionGateConfig(min_sample_size=50))
    champ_rep = _create_mock_report("champ", pf=1.50, sample_size=20)
    chall_rep = _create_mock_report("chall", pf=1.70, sample_size=20)

    report = comparator.compare_reports(champ_rep, chall_rep)
    assert report.recommendation == ComparisonRecommendation.INCONCLUSIVE.value
    assert any("below minimum required" in r for r in report.rationale)


def test_atomic_promotion_and_rollback(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    gate_mgr = PromotionGateManager(registry=registry)

    # 1. Register Champion v1
    meta1 = ModelMetadata(
        model_version="model_v1",
        algorithm="lightgbm",
        status="champion",
        training_start="2025-01-01",
        training_end="2025-03-31",
    )
    registry.save_model("dummy_model_v1", meta1)

    # 2. Register Challenger v2
    meta2 = ModelMetadata(
        model_version="model_v2",
        algorithm="lightgbm",
        status="challenger",
        training_start="2025-01-01",
        training_end="2025-04-30",
    )
    registry.save_model("dummy_model_v2", meta2)

    # Verify initial status
    _, cur_champ_meta = registry.get_champion()
    assert cur_champ_meta.model_version == "model_v1"

    # 3. Atomically promote Challenger v2
    promoted_meta = gate_mgr.promote_challenger("model_v2", archive_status="archived_champion")
    assert promoted_meta.model_version == "model_v2"
    assert promoted_meta.status == "champion"

    # Verify old champion v1 is demoted to archived_champion
    old_meta = registry.get_metadata("model_v1")
    assert old_meta.status == "archived_champion"

    # 4. Rollback to last known champion (model_v1)
    restored_meta = gate_mgr.rollback(demote_current_to="retired")
    assert restored_meta.model_version == "model_v1"
    assert restored_meta.status == "champion"

    # Verify demoted model_v2 is retired
    demoted_v2 = registry.get_metadata("model_v2")
    assert demoted_v2.status == "retired"

    # 5. Rollback to specific target version
    restored_v2 = gate_mgr.rollback(
        target_version="model_v2", demote_current_to="archived_champion"
    )
    assert restored_v2.model_version == "model_v2"
    assert restored_v2.status == "champion"


def test_rollback_raises_when_no_prior_models(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    gate_mgr = PromotionGateManager(registry=registry)
    with pytest.raises(ValueError, match="No prior models found"):
        gate_mgr.rollback()


def test_trigger_performance_degradation_with_recent_anchor():
    # 50 total outcomes in DB, all losing (0% win rate).
    # since_date is 5 days ago, so only 5 new outcomes (volume 5 < 200).
    # But rolling window over recent 20 trades should detect degradation and trigger.
    base_d = date(2025, 1, 1)
    outcomes = [
        _make_dummy_outcome(i, status="SL", ret=-0.02, d=base_d + timedelta(days=i))
        for i in range(50)
    ]
    evaluator = RetrainingTriggerEvaluator(
        config=RetrainingTriggerConfig(
            min_matured_samples=200,
            rolling_window_size=20,
            win_rate_safety_floor=0.45,
        ),
        outcome_repo=MockOutcomeRepo(outcomes),
        signal_repo=MockSignalRepo(),
    )
    result = evaluator.evaluate(since_date=base_d + timedelta(days=45))
    assert result.should_retrain is True
    assert result.matured_count == 5  # 5 new outcomes since anchor
    assert result.rolling_win_rate == 0.0
    assert any("Rolling win rate" in r for r in result.reasons)


def test_dataset_assembly_feature_preservation_combine_first():
    # Historical DataFrame has full computed features (return_1d, rsi14, macd).
    # Outcomes DataFrame for same (ticker, date) only has partial snapshot (return_1d).
    # Assembler must preserve rsi14 and macd from historical data.
    assembler = RetrainingDatasetAssembler(
        feature_cols=["return_1d", "rsi14", "macd"],
        exclude_ambiguous=True,
    )
    h_df = pd.DataFrame([
        {
            "ticker": "BBCA",
            "date": "2025-01-01",
            "return_1d": 0.01,
            "rsi14": 55.0,
            "macd": 0.5,
            "binary_target": 0,
            "realized_return": -0.01,
        }
    ])
    o_df = pd.DataFrame([
        {
            "ticker": "BBCA",
            "date": "2025-01-01",
            "return_1d": 0.02,
            "binary_target": 1,
            "realized_return": 0.04,
            "outcome_status": "TP",
        }
    ])
    ds = assembler.assemble_from_dfs(h_df, o_df)
    assert len(ds) == 1
    assert ds.y[0] == 1  # Outcome target takes precedence
    assert ds.y_return[0] == 0.04
    # Features preserved from historical data rather than imputed median/0
    assert ds.X[0][0] == 0.02  # return_1d from outcome
    assert ds.X[0][1] == 55.0  # rsi14 preserved from historical
    assert ds.X[0][2] == 0.5   # macd preserved from historical


def test_rollback_task_mismatch_raises(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    gate_mgr = PromotionGateManager(registry=registry)

    meta_reg = ModelMetadata(
        model_version="reg_model_1",
        algorithm="lightgbm",
        task="regression",
        status="archived_champion",
        training_start="2025-01-01",
        training_end="2025-03-31",
    )
    registry.save_model("dummy_reg", meta_reg)

    with pytest.raises(ValueError, match="does not match requested task"):
        gate_mgr.rollback(target_version="reg_model_1", task="classification")


def test_rollback_same_active_champion_raises(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path)
    gate_mgr = PromotionGateManager(registry=registry)

    meta = ModelMetadata(
        model_version="champ_v1",
        algorithm="lightgbm",
        task="classification",
        status="champion",
        training_start="2025-01-01",
        training_end="2025-03-31",
    )
    registry.save_model("dummy_champ", meta)

    with pytest.raises(ValueError, match="already the active champion"):
        gate_mgr.rollback(target_version="champ_v1", task="classification")


def test_walk_forward_split_small_dataset_clamping():
    assembler = RetrainingDatasetAssembler(
        feature_cols=["return_1d", "rsi14"],
        purge_days=10,
    )
    # Small dataset spanning only 5 dates
    dates = [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 4),
        date(2025, 1, 5),
    ]
    df = pd.DataFrame({
        "ticker": ["BBCA"] * 5,
        "date": dates,
        "return_1d": [0.01] * 5,
        "rsi14": [50.0] * 5,
        "binary_target": [1, 0, 1, 0, 1],
        "realized_return": [0.02, -0.01, 0.03, -0.02, 0.01],
    })
    ds = assembler.assemble_from_dfs(df, pd.DataFrame())
    # Should not raise ValueError even though 5 dates < purge_days (10)
    train_ds, val_ds, test_ds = assembler.split_walk_forward(ds, purge_days=10)
    assert len(train_ds) > 0
    assert len(test_ds) > 0
