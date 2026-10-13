import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from python.common.types import (
    ComparisonRecommendation,
    EvaluationReport,
    PredictionMetrics,
    SignalOutcomeRecord,
    TradingMetrics,
)
from python.models.comparator import (
    ModelComparator,
    PromotionGateConfig,
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
)
from python.models.evaluation import (
    EvaluationEngine,
    compute_calibration_bins,
    compute_trading_metrics,
)


def test_compute_calibration_bins_basics():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.2, 0.8, 0.9])
    ece, bins = compute_calibration_bins(y_true, y_prob, n_bins=10)

    assert isinstance(ece, float)
    assert ece >= 0.0
    assert len(bins) == 10
    total_samples = sum(b.sample_count for b in bins)
    assert total_samples == 4


def test_compute_calibration_bins_empty():
    ece, bins = compute_calibration_bins([], [], n_bins=10)
    assert ece == 0.0
    assert bins == []


def test_compute_calibration_perfect():
    y_true = np.array([1, 1, 0, 0])
    y_prob = np.array([1.0, 1.0, 0.0, 0.0])
    ece, bins = compute_calibration_bins(y_true, y_prob, n_bins=10)
    assert math.isclose(ece, 0.0, abs_tol=1e-6)


def test_compute_trading_metrics_basics():
    returns = [0.05, 0.02, -0.01, -0.02, 0.03]
    statuses = ["TP", "TP", "SL", "SL", "TP"]
    metrics = compute_trading_metrics(returns, outcome_statuses=statuses)

    assert metrics.total_trades == 5
    assert metrics.win_rate == 0.60
    assert metrics.tp_rate == 0.60
    assert metrics.sl_rate == 0.40
    assert metrics.expiry_rate == 0.0
    assert metrics.profit_factor == round((0.05 + 0.02 + 0.03) / (0.01 + 0.02), 4)
    assert metrics.expectancy == round((0.05 + 0.02 - 0.01 - 0.02 + 0.03) / 5, 4)
    assert metrics.max_drawdown >= 0.0


def test_compute_trading_metrics_empty():
    metrics = compute_trading_metrics([])
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.expectancy == 0.0
    assert metrics.max_drawdown == 0.0


def test_compute_trading_metrics_all_wins():
    returns = [0.05, 0.10, 0.02]
    metrics = compute_trading_metrics(returns)
    assert metrics.win_rate == 1.0
    assert metrics.profit_factor == float("inf")
    assert metrics.avg_loss == 0.0
    assert metrics.max_drawdown == 0.0


def test_compute_trading_metrics_all_losses():
    returns = [-0.02, -0.05, -0.01]
    metrics = compute_trading_metrics(returns)
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.avg_win == 0.0
    assert metrics.max_drawdown > 0.0


def test_evaluation_engine_evaluate_predictions():
    engine = EvaluationEngine(n_calibration_bins=5)
    y_true = [1, 0, 1, 0, 1]
    y_prob = [0.9, 0.1, 0.8, 0.2, 0.7]

    p_metrics, cal_bins = engine.evaluate_predictions(y_true, y_prob)
    assert p_metrics.accuracy == 1.0
    assert p_metrics.brier_score < 0.1
    assert p_metrics.roc_auc == 1.0
    assert len(cal_bins) == 5


def test_evaluation_engine_evaluate_dataset():
    engine = EvaluationEngine()
    df = pd.DataFrame(
        {
            "binary_target": [1, 0, 1, 0],
            "predicted_probability": [0.8, 0.2, 0.7, 0.3],
            "realized_return": [0.05, -0.02, 0.04, -0.01],
            "outcome_status": ["TP", "SL", "TP", "SL"],
        }
    )

    report = engine.evaluate_dataset(df, model_version="v1.0.0")
    assert report.model_version == "v1.0.0"
    assert report.sample_size == 4
    assert report.trading_metrics.win_rate == 0.50
    assert report.trading_metrics.profit_factor > 1.0
    assert report.prediction_metrics.roc_auc == 1.0


def test_evaluation_engine_evaluate_empty_dataset():
    engine = EvaluationEngine()
    report = engine.evaluate_dataset(pd.DataFrame(), model_version="empty_v1")
    assert report.sample_size == 0
    assert report.trading_metrics.total_trades == 0


def test_evaluation_engine_evaluate_model():
    engine = EvaluationEngine()

    class DummyClassifier:
        def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
            n = len(X)
            # return 2D array [prob_0, prob_1]
            return np.column_stack([np.full(n, 0.3), np.full(n, 0.7)])

    X = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "f2": [4.0, 5.0, 6.0]})
    y_true = np.array([1, 1, 0])
    returns = np.array([0.05, 0.04, -0.02])

    report = engine.evaluate_model(
        model=DummyClassifier(),
        X=X,
        y_true=y_true,
        returns=returns,
        model_version="dummy_v1",
    )
    assert report.sample_size == 3
    assert report.prediction_metrics.accuracy == pytest.approx(0.6667, abs=1e-3)
    assert report.trading_metrics.win_rate == pytest.approx(0.6667, abs=1e-3)


def test_evaluation_engine_evaluate_from_outcomes():
    engine = EvaluationEngine()
    outcomes = [
        SignalOutcomeRecord(
            signal_id="sig_1",
            ticker="BBCA",
            signal_date=date(2026, 10, 1),
            entry_date=date(2026, 10, 2),
            entry_price=10000.0,
            outcome_status="TP",
            exit_date=date(2026, 10, 5),
            exit_price=10500.0,
            exit_reason="TP",
            realized_return=0.05,
            holding_days=3,
        ),
        SignalOutcomeRecord(
            signal_id="sig_2",
            ticker="BBRI",
            signal_date=date(2026, 10, 1),
            entry_date=date(2026, 10, 2),
            entry_price=5000.0,
            outcome_status="SL",
            exit_date=date(2026, 10, 4),
            exit_price=4900.0,
            exit_reason="SL",
            realized_return=-0.02,
            holding_days=2,
        ),
    ]

    report = engine.evaluate_from_outcomes(outcomes, model_version="matured_v1")
    assert report.sample_size == 2
    assert report.trading_metrics.win_rate == 0.50
    assert report.trading_metrics.total_trades == 2


def test_model_comparator_promote_decision():
    config = PromotionGateConfig(min_sample_size=50, min_profit_factor_improvement=0.05)
    comparator = ModelComparator(config=config)

    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=100,
        trading_metrics=TradingMetrics(
            win_rate=0.55,
            profit_factor=1.50,
            expectancy=0.02,
            max_drawdown=0.10,
        ),
        prediction_metrics=PredictionMetrics(
            brier_score=0.20,
            roc_auc=0.62,
        ),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=100,
        trading_metrics=TradingMetrics(
            win_rate=0.60,
            profit_factor=1.75,  # +0.25 improvement
            expectancy=0.03,  # +0.01 improvement
            max_drawdown=0.09,  # less drawdown
        ),
        prediction_metrics=PredictionMetrics(
            brier_score=0.17,  # lower brier score (better)
            roc_auc=0.67,
        ),
    )

    comp = comparator.compare_reports(champ, chall, test_window="2026-H1")
    assert comp.recommendation == ComparisonRecommendation.PROMOTE.value
    assert comp.delta_metrics["profit_factor_delta"] == 0.25
    assert comp.delta_metrics["brier_score_delta"] == -0.03


def test_model_comparator_reject_insufficient_profit_factor():
    config = PromotionGateConfig(min_sample_size=50, min_profit_factor_improvement=0.05)
    comparator = ModelComparator(config=config)

    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=100,
        trading_metrics=TradingMetrics(profit_factor=1.50, max_drawdown=0.10),
        prediction_metrics=PredictionMetrics(brier_score=0.20),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=100,
        trading_metrics=TradingMetrics(profit_factor=1.40, max_drawdown=0.10),  # worse
        prediction_metrics=PredictionMetrics(brier_score=0.20),
    )

    comp = comparator.compare_reports(champ, chall)
    assert comp.recommendation == ComparisonRecommendation.REJECT.value


def test_model_comparator_reject_drawdown_blowout():
    config = PromotionGateConfig(
        min_sample_size=50,
        min_profit_factor_improvement=0.05,
        max_drawdown_increase=0.0,
    )
    comparator = ModelComparator(config=config)

    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=100,
        trading_metrics=TradingMetrics(profit_factor=1.50, max_drawdown=0.08),
        prediction_metrics=PredictionMetrics(brier_score=0.20),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=100,
        trading_metrics=TradingMetrics(profit_factor=1.80, max_drawdown=0.15),  # worse DD
        prediction_metrics=PredictionMetrics(brier_score=0.18),
    )

    comp = comparator.compare_reports(champ, chall)
    assert comp.recommendation == ComparisonRecommendation.REJECT.value


def test_model_comparator_inconclusive_sample_size():
    config = PromotionGateConfig(min_sample_size=100)
    comparator = ModelComparator(config=config)

    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=20,  # below 100
        trading_metrics=TradingMetrics(profit_factor=1.50),
        prediction_metrics=PredictionMetrics(brier_score=0.20),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=20,
        trading_metrics=TradingMetrics(profit_factor=2.00),
        prediction_metrics=PredictionMetrics(brier_score=0.15),
    )

    comp = comparator.compare_reports(champ, chall)
    assert comp.recommendation == ComparisonRecommendation.INCONCLUSIVE.value
    assert any("below minimum required" in r for r in comp.rationale)


def test_format_comparison_outputs():
    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=100,
        trading_metrics=TradingMetrics(win_rate=0.55, profit_factor=1.50, max_drawdown=0.10),
        prediction_metrics=PredictionMetrics(brier_score=0.20, roc_auc=0.62),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=100,
        trading_metrics=TradingMetrics(win_rate=0.60, profit_factor=1.80, max_drawdown=0.08),
        prediction_metrics=PredictionMetrics(brier_score=0.17, roc_auc=0.68),
    )
    comparator = ModelComparator(config=PromotionGateConfig(min_sample_size=50))
    report = comparator.compare_reports(champ, chall)

    tbl = format_comparison_table(report)
    assert "MODEL COMPARISON" in tbl
    assert "Profit Factor" in tbl
    assert "RECOMMENDATION: PROMOTE" in tbl

    md = format_comparison_markdown(report)
    assert "## Model Evaluation Comparison" in md
    assert "| **Profit Factor** |" in md

    js = format_comparison_json(report)
    assert '"recommendation": "PROMOTE"' in js
