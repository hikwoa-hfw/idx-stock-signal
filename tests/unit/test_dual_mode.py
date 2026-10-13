from datetime import date, datetime, timezone
from pathlib import Path

from python.common.types import (
    DailyBar,
    PositionRecord,
    PriceMode,
    SignalConfig,
    SignalOutcomeRecord,
    SignalRecord,
    TradeRecord,
    classify_price_mode,
)
from python.models.baseline import LogisticRegressionBaseline
from python.models.dataset import Dataset
from python.models.registry import ModelMetadata, ModelRegistry
from python.signals.engine import SignalEngine
from services.telegram.formatter import format_dual_mode_signals

# ==============================================================================
# 1. Price Mode Classification & Boundary Tests
# ==============================================================================

def test_classify_price_mode_boundaries():
    # Invalid / Non-positive
    assert classify_price_mode(None) == PriceMode.INVALID.value
    assert classify_price_mode(0.0) == PriceMode.INVALID.value
    assert classify_price_mode(-10.0) == PriceMode.INVALID.value
    assert classify_price_mode(float("nan")) == PriceMode.INVALID.value
    assert classify_price_mode(float("inf")) == PriceMode.INVALID.value

    # Sub-50 excluded
    assert classify_price_mode(1.0) == PriceMode.EXCLUDED_BELOW_50.value
    assert classify_price_mode(49.0) == PriceMode.EXCLUDED_BELOW_50.value
    assert classify_price_mode(49.99) == PriceMode.EXCLUDED_BELOW_50.value

    # Low Price: 50 <= price <= 300
    assert classify_price_mode(50.0) == PriceMode.LOW_PRICE.value
    assert classify_price_mode(50.01) == PriceMode.LOW_PRICE.value
    assert classify_price_mode(150.0) == PriceMode.LOW_PRICE.value
    assert classify_price_mode(299.99) == PriceMode.LOW_PRICE.value
    assert classify_price_mode(300.0) == PriceMode.LOW_PRICE.value

    # Higher Price: price > 300
    assert classify_price_mode(300.01) == PriceMode.HIGHER_PRICE.value
    assert classify_price_mode(301.0) == PriceMode.HIGHER_PRICE.value
    assert classify_price_mode(9500.0) == PriceMode.HIGHER_PRICE.value


# ==============================================================================
# 2. Decision-Time Mode Immutability Across Lifecycle
# ==============================================================================

def test_mode_immutability_on_price_crossing():
    # Position entered at 280 (LOW_PRICE), exits at 350 (would be HIGHER_PRICE if re-classified)
    pos = PositionRecord(
        position_id="pos-001",
        ticker="GOTO",
        actual_entry_date=date(2026, 8, 1),
        actual_entry_price=280.0,
        quantity=1000,
        mode="LOW_PRICE",
    )
    assert pos.mode_id == "LOW_PRICE"

    # Close position at 350
    pos.actual_exit_date = date(2026, 8, 10)
    pos.actual_exit_price = 350.0
    pos.status = "CLOSED"
    pos.realized_return = (350.0 - 280.0) / 280.0

    # Mode remains LOW_PRICE
    assert pos.mode_id == "LOW_PRICE"

    # TradeRecord reflects decision-time mode
    trade = TradeRecord(
        trade_id="T_GOTO_1",
        ticker="GOTO",
        signal_date=date(2026, 7, 31),
        entry_date=date(2026, 8, 1),
        exit_date=date(2026, 8, 10),
        shares=1000,
        entry_price=280.0,
        exit_price=350.0,
        position_value=280000.0,
        entry_fee=420.0,
        exit_fee=875.0,
        slippage_cost=50.0,
        gross_pnl=70000.0,
        net_pnl=68655.0,
        net_return=0.245,
        exit_reason="TP",
        holding_days=9,
        mode=pos.mode_id,
    )
    assert trade.mode_id == "LOW_PRICE"


def test_outcome_record_mode_immutability():
    # Signal generated at 290 (LOW_PRICE), resolves at 310 (TP)
    outcome = SignalOutcomeRecord(
        outcome_id="out-001",
        signal_id="sig-001",
        ticker="BUKA",
        signal_date=date(2026, 8, 1),
        entry_date=date(2026, 8, 2),
        entry_price=290.0,
        outcome_status="TP",
        realized_return=0.069,
        holding_days=3,
        exit_date=date(2026, 8, 5),
        exit_price=310.0,
        exit_reason="TP",
        resolved_at=datetime.now(timezone.utc),
        mode="LOW_PRICE",
    )
    assert outcome.mode_id == "LOW_PRICE"


# ==============================================================================
# 3. Fail-Closed BUY Guards in SignalEngine
# ==============================================================================

def test_signal_engine_fail_closed_on_zero_or_invalid_prob(tmp_path: Path):
    registry = ModelRegistry(registry_dir=tmp_path / "reg")

    # Fit dummy classifier
    clf = LogisticRegressionBaseline()
    clf.fit([[0.01], [-0.01]], [1, 0], feature_names=["return_1d"])

    meta = ModelMetadata(
        model_version="champ_low",
        algorithm="logistic",
        task="classification",
        mode="LOW_PRICE",
        status="champion",
        training_start="2026-08-01",
        training_end="2026-08-10",
        feature_names=["return_1d"],
    )
    registry.save_model(clf, meta)

    engine = SignalEngine(
        model_registry=registry,
        config=SignalConfig(min_probability=0.50, mode="LOW_PRICE"),
    )

    # Candidate with price 100 (LOW_PRICE)
    bars = {
        "TEST": [
            DailyBar(
                ticker="TEST",
                date=date(2026, 8, i + 1),
                open=100.0,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=500_000.0,
                provider="test",
            )
            for i in range(25)
        ]
    }

    # If classifier is mocked to predict 0.0 probability -> fail closed
    class ZeroProbModel:
        feature_names_ = ["return_1d"]
        model_version = "zero_prob"
        def predict_probability(self, X):
            import numpy as np
            return np.zeros(len(X))

    signals = engine.generate_signals(
        signal_date=date(2026, 8, 25),
        universe=["TEST"],
        classifier=ZeroProbModel(),
        bars_by_ticker=bars,
        mode="LOW_PRICE",
    )
    assert len(signals) == 0, "Candidate with 0.0 probability must be rejected"


def test_signal_engine_strictly_excludes_sub_50(tmp_path: Path):
    registry = ModelRegistry(registry_dir=tmp_path / "reg")
    engine = SignalEngine(model_registry=registry)

    # Ticker trading at 45 IDR
    bars = {
        "PENNY": [
            DailyBar(
                ticker="PENNY",
                date=date(2026, 8, i + 1),
                open=45.0,
                high=46.0,
                low=44.0,
                close=45.0,
                volume=1_000_000.0,
                provider="test",
            )
            for i in range(25)
        ]
    }

    class HighProbModel:
        feature_names_ = ["return_1d"]
        model_version = "high_prob"
        def predict_probability(self, X):
            import numpy as np
            return np.ones(len(X)) * 0.95

    signals = engine.generate_signals(
        signal_date=date(2026, 8, 25),
        universe=["PENNY"],
        classifier=HighProbModel(),
        bars_by_ticker=bars,
    )
    assert len(signals) == 0, "Sub-50 IDR tickers must be strictly excluded from BUY signals"


def test_signal_engine_fail_closed_on_missing_required_expected_return():
    engine = SignalEngine(
        config=SignalConfig(
            min_probability=0.50,
            require_expected_return=True,
            mode="LOW_PRICE",
        )
    )

    bars = {
        "TEST": [
            DailyBar(
                ticker="TEST",
                date=date(2026, 8, i + 1),
                open=100.0,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=500_000.0,
                provider="test",
            )
            for i in range(25)
        ]
    }

    class HighProbModel:
        feature_names_ = ["return_1d"]
        model_version = "high_prob"
        def predict_probability(self, X):
            import numpy as np
            return np.ones(len(X)) * 0.85

    # regressor is None, require_expected_return is True -> must fail closed
    signals = engine.generate_signals(
        signal_date=date(2026, 8, 25),
        universe=["TEST"],
        classifier=HighProbModel(),
        regressor=None,
        bars_by_ticker=bars,
        mode="LOW_PRICE",
    )
    assert len(signals) == 0, "Missing required expected return must block BUY signal"


# ==============================================================================
# 4. Independent Champion Lifecycle per PriceMode
# ==============================================================================

def test_independent_champion_lifecycle(tmp_path: Path):
    reg = ModelRegistry(registry_dir=tmp_path / "registry")
    clf_low = LogisticRegressionBaseline()
    clf_low.fit([[0.01], [-0.01]], [1, 0], feature_names=["f1"])

    clf_high = LogisticRegressionBaseline()
    clf_high.fit([[0.02], [-0.02]], [1, 0], feature_names=["f1"])

    # 1. Register LOW_PRICE champion
    meta_low1 = ModelMetadata(
        model_version="low_v1",
        algorithm="logistic",
        task="classification",
        mode="LOW_PRICE",
        status="champion",
        training_start="2026-08-01",
        training_end="2026-08-10",
        feature_names=["f1"],
    )
    reg.save_model(clf_low, meta_low1)

    # 2. Register HIGHER_PRICE champion
    meta_high1 = ModelMetadata(
        model_version="high_v1",
        algorithm="logistic",
        task="classification",
        mode="HIGHER_PRICE",
        status="champion",
        training_start="2026-08-01",
        training_end="2026-08-10",
        feature_names=["f1"],
    )
    reg.save_model(clf_high, meta_high1)

    # Both champions coexist
    champ_low = reg.get_champion(task="classification", mode="LOW_PRICE")
    champ_high = reg.get_champion(task="classification", mode="HIGHER_PRICE")
    assert champ_low is not None and champ_low[1].model_version == "low_v1"
    assert champ_high is not None and champ_high[1].model_version == "high_v1"

    # 3. Promote a new LOW_PRICE champion (low_v2)
    meta_low2 = ModelMetadata(
        model_version="low_v2",
        algorithm="logistic",
        task="classification",
        mode="LOW_PRICE",
        status="challenger",
        training_start="2026-08-01",
        training_end="2026-08-15",
        feature_names=["f1"],
    )
    reg.save_model(clf_low, meta_low2)
    reg.promote_to_champion("low_v2")

    # Verify low_v2 is now champion for LOW_PRICE, while high_v1 is UNTOUCHED
    champ_low_new = reg.get_champion(task="classification", mode="LOW_PRICE")
    champ_high_still = reg.get_champion(task="classification", mode="HIGHER_PRICE")
    assert champ_low_new[1].model_version == "low_v2"
    assert champ_high_still[1].model_version == "high_v1"

    # 4. Rollback LOW_PRICE to low_v1
    reg.rollback_champion("low_v1")
    champ_low_rolled = reg.get_champion(task="classification", mode="LOW_PRICE")
    assert champ_low_rolled is not None and champ_low_rolled[1].model_version == "low_v1"
    champ_high_check = reg.get_champion(task="classification", mode="HIGHER_PRICE")
    assert champ_high_check is not None and champ_high_check[1].model_version == "high_v1"


# ==============================================================================
# 5. DatasetBuilder Dual-Mode Filtering & Summary
# ==============================================================================

def test_dataset_dual_mode_filter_and_summary():
    import numpy as np
    import pandas as pd

    dates = np.array([date(2026, 8, 1)] * 4)
    tickers = np.array(["P1", "P2", "P3", "P4"])
    X = np.ones((4, 2))
    y = np.array([1, 0, 1, 0])
    y_return = np.array([0.05, -0.02, 0.04, -0.01])
    feature_names = ["f1", "f2"]
    modes = ["LOW_PRICE", "HIGHER_PRICE", "LOW_PRICE", "EXCLUDED_BELOW_50"]
    meta_df = pd.DataFrame({"mode": modes, "ticker": tickers})

    ds = Dataset(
        X=X,
        y=y,
        y_return=y_return,
        dates=dates,
        tickers=tickers,
        feature_names=feature_names,
        metadata=meta_df,
    )

    summary = ds.get_summary()
    assert summary["mode_counts"]["LOW_PRICE"] == 2
    assert summary["mode_counts"]["HIGHER_PRICE"] == 1
    assert summary["mode_counts"]["EXCLUDED_BELOW_50"] == 1

    ds_low = ds.filter_by_mode("LOW_PRICE")
    assert len(ds_low) == 2
    assert all(m == "LOW_PRICE" for m in ds_low.metadata["mode"])

    ds_high = ds.filter_by_mode("HIGHER_PRICE")
    assert len(ds_high) == 1
    assert ds_high.tickers[0] == "P2"


# ==============================================================================
# 6. Telegram Dual-Mode Formatter Layout (Guide 06 Section 11)
# ==============================================================================

def test_telegram_dual_mode_formatter():
    low_sig = SignalRecord(
        signal_id="sig-low-1",
        ticker="GOTO",
        signal_date=date(2026, 8, 20),
        signal="BUY",
        entry_low=60.0,
        entry_high=62.0,
        tp_price=66.0,
        sl_price=58.0,
        max_holding_days=10,
        predicted_probability=0.72,
        expected_return=0.065,
        score=78.5,
        model_version="lgbm_low_v1",
        mode="LOW_PRICE",
    )

    high_sig = SignalRecord(
        signal_id="sig-high-1",
        ticker="BBCA",
        signal_date=date(2026, 8, 20),
        signal="BUY",
        entry_low=10200.0,
        entry_high=10300.0,
        tp_price=10800.0,
        sl_price=10000.0,
        max_holding_days=10,
        predicted_probability=0.81,
        expected_return=0.048,
        score=84.2,
        model_version="lgbm_high_v1",
        mode="HIGHER_PRICE",
    )

    dual_dict = {
        "LOW_PRICE": [low_sig],
        "HIGHER_PRICE": [high_sig],
    }

    text = format_dual_mode_signals(dual_dict, target_date=date(2026, 8, 20))

    assert "DAILY STOCK SIGNAL" in text
    assert "MODE A" in text and "LOW_PRICE" in text
    assert "GOTO" in text
    assert "MODE B" in text and "HIGHER_PRICE" in text
    assert "BBCA" in text
    assert "Probability: 72%" in text
    assert "Probability: 81%" in text

    # Test empty mode section messaging
    empty_dict = {"LOW_PRICE": [], "HIGHER_PRICE": [high_sig]}
    empty_text = format_dual_mode_signals(empty_dict, target_date=date(2026, 8, 20))
    assert "NO SIGNAL" in empty_text
