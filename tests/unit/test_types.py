from datetime import date
from python.common.types import Signal, SignalAction, Position, Outcome, OutcomeStatus, ModelVersion
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
