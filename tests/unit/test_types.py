from datetime import date, datetime, timezone

from python.common.types import (
    ModelVersion,
    Outcome,
    OutcomeStatus,
    Position,
    Prediction,
    Signal,
    SignalAction,
)
from python.config.settings import settings


def test_settings_load_defaults():
    assert settings.app_env in ["development", "production", "test"]
    assert settings.market_data_provider != ""


def test_signal_model_validation():
    signal = Signal(
        ticker="BBCA.JK",
        signal_date=date(2026, 10, 12),
        action=SignalAction.BUY,
        entry_price=10000.0,
        target_price=10500.0,
        stop_loss=9800.0,
        probability=0.72,
        model_version="v1.0.0",
    )
    assert signal.ticker == "BBCA.JK"
    assert signal.action == SignalAction.BUY
    assert signal.target_price > signal.entry_price
    assert signal.max_holding_days == 10


def test_position_model_validation():
    pos = Position(
        position_id="pos-001",
        ticker="BBRI.JK",
        entry_date=date(2026, 10, 12),
        entry_price=5000.0,
        quantity=10,
        target_price=5300.0,
        stop_loss=4850.0,
        is_open=True,
    )
    assert pos.is_open is True
    assert pos.quantity == 10


def test_prediction_model_validation():
    pred = Prediction(
        ticker="TLKM.JK",
        prediction_date=date(2026, 10, 12),
        model_version="lgbm_v1.0",
        probability=0.68,
        expected_return=0.045,
    )
    assert pred.ticker == "TLKM.JK"
    assert pred.probability == 0.68
    assert pred.created_at is not None
    assert pred.created_at.tzinfo is not None


def test_outcome_model_validation():
    outcome = Outcome(
        ticker="BBCA.JK",
        signal_date=date(2026, 10, 1),
        status=OutcomeStatus.TP_HIT,
        realized_return=0.052,
        holding_days=4,
    )
    assert outcome.status == OutcomeStatus.TP_HIT
    assert outcome.realized_return == 0.052
    assert outcome.holding_days == 4
    assert outcome.evaluated_at.tzinfo is not None


def test_model_version_validation():
    mv = ModelVersion(
        version="v1.0.0",
        model_type="lightgbm_classifier",
        trained_at=datetime.now(timezone.utc),
        metrics={"roc_auc": 0.65, "precision_at_k": 0.70},
        is_champion=True,
    )
    assert mv.is_champion is True
    assert mv.metrics["roc_auc"] == 0.65
