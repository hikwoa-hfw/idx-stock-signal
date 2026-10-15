import math
import sqlite3
from datetime import date, timedelta
from typing import Any

import pytest

from python.common.types import DailyBar, FeatureRecord, SignalConfig, SignalRecord
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository


class DummyClassifier:
    """Mock classifier returning preset probabilities based on ticker."""

    def __init__(self, prob_map: dict[str, float]) -> None:
        self.prob_map = prob_map
        self.model_version = "dummy_clf_v1"
        self.feature_names_ = ["return_1d", "volume_ratio_20d"]

    def predict_probability(self, X: Any) -> list[float]:
        # X contains rows of feature values
        return [0.70] * len(X)


class DummyRegressor:
    """Mock regressor returning preset returns."""

    def __init__(self, ret_map: dict[str, float]) -> None:
        self.ret_map = ret_map
        self.model_version = "dummy_reg_v1"

    def predict_expected_return(self, X: Any) -> list[float]:
        return [0.05] * len(X)


def create_bars_sequence(
    ticker: str, start_date: date, count: int, base_price: float = 1000.0
) -> list[DailyBar]:
    bars = []
    current_date = start_date
    for i in range(count):
        price = base_price + i * 2.0
        bars.append(
            DailyBar(
                ticker=ticker,
                date=current_date,
                open=price,
                high=price + 10.0,
                low=price - 10.0,
                close=price,
                volume=1_000_000.0,
                value=price * 1_000_000.0,
            )
        )
        current_date += timedelta(days=1)
    return bars


def test_ranking_order_and_top_n():
    engine = SignalEngine()

    config = SignalConfig(top_n=2)
    # Ticker A: score 90, B: score 80, C: score 85
    r_a = FeatureRecord(
        ticker="BBCA",
        date=date(2026, 10, 1),
        volume_ratio_20d=2.0,
        market_breadth=0.8,
        atr_pct=0.02,
    )
    r_b = FeatureRecord(
        ticker="BBRI",
        date=date(2026, 10, 1),
        volume_ratio_20d=0.5,
        market_breadth=0.3,
        atr_pct=0.08,
    )
    r_c = FeatureRecord(
        ticker="BMRI",
        date=date(2026, 10, 1),
        volume_ratio_20d=1.5,
        market_breadth=0.6,
        atr_pct=0.03,
    )

    score_a = engine.calculate_composite_score(0.80, 0.08, r_a, config)
    score_b = engine.calculate_composite_score(0.60, 0.01, r_b, config)
    score_c = engine.calculate_composite_score(0.75, 0.05, r_c, config)

    assert score_a > score_c > score_b

    # Verify ranking logic via generate_signals
    start = date(2026, 1, 1)
    bars_a = create_bars_sequence("BBCA", start, 25, 10000.0)
    bars_b = create_bars_sequence("BBRI", start, 25, 5000.0)
    bars_c = create_bars_sequence("BMRI", start, 25, 7000.0)

    class CustomProbClassifier:
        model_version = "custom_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            # Returns prob based on number of rows
            return [0.80, 0.60, 0.75][: len(X)]

    # Generate signals
    signals = engine.generate_signals(
        signal_date=bars_a[-1].date,
        classifier=CustomProbClassifier(),
        bars_by_ticker={"BBCA": bars_a, "BBRI": bars_b, "BMRI": bars_c},
        config=config,
    )

    # top_n is 2 -> should return only 2 signals
    assert len(signals) == 2
    # Winner should have highest score
    assert signals[0].score >= signals[1].score


def test_threshold_filtering():
    engine = SignalEngine()

    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)
    target_date = bars[-1].date

    # Probability below min_probability (0.50 vs min 0.65)
    class LowProbClassifier:
        model_version = "low_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.50] * len(X)

    cfg = SignalConfig(min_probability=0.65)
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=LowProbClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 0

    # Minimum volume filter
    cfg_vol = SignalConfig(min_probability=0.40, min_volume_20d=5_000_000.0)
    # Our bars have 1,000,000 volume -> should be filtered out
    signals_vol = engine.generate_signals(
        signal_date=target_date,
        classifier=LowProbClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg_vol,
    )
    assert len(signals_vol) == 0


def test_score_weighting():
    engine = SignalEngine()
    feat = FeatureRecord(
        ticker="BBCA",
        date=date(2026, 10, 1),
        volume_ratio_20d=1.0,  # liquidity score = 50.0
        market_breadth=0.5,  # regime score = 50.0
        atr_pct=0.05,  # risk score = 50.0
    )

    # Only probability weighted
    cfg_prob_only = SignalConfig(weights={"probability": 1.0, "return": 0.0, "liquidity": 0.0})
    score1 = engine.calculate_composite_score(0.80, 0.05, feat, cfg_prob_only)
    assert score1 == 80.0

    # 50% probability (80.0), 50% liquidity (50.0) -> composite = 65.0
    cfg_half = SignalConfig(weights={"probability": 0.50, "liquidity": 0.50})
    score2 = engine.calculate_composite_score(0.80, None, feat, cfg_half)
    assert score2 == 65.0


def test_entry_tp_sl_price_math():
    engine = SignalEngine()
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)
    target_date = bars[-1].date
    last_close = bars[-1].close

    cfg = SignalConfig(
        tp_pct=0.06,
        sl_pct=0.03,
        entry_band_pct=0.02,
        min_probability=0.50,
    )

    class HighProbClassifier:
        model_version = "high_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.75] * len(X)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=HighProbClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )

    assert len(signals) == 1
    sig = signals[0]

    # Verify math
    expected_low = round(last_close * (1.0 - 0.01), 2)
    expected_high = round(last_close * (1.0 + 0.01), 2)
    expected_tp = round(expected_high * (1.0 + 0.06), 2)
    expected_sl = round(expected_low * (1.0 - 0.03), 2)

    assert sig.entry_low == expected_low
    assert sig.entry_high == expected_high
    assert sig.tp_price == expected_tp
    assert sig.sl_price == expected_sl
    assert sig.tp_price > sig.entry_high
    assert sig.sl_price < sig.entry_low


def test_data_quality_checks_insufficient_bars_and_suspension():
    engine = SignalEngine()
    start = date(2026, 1, 1)

    # Ticker A has only 10 bars (< min_history_bars=20)
    short_bars = create_bars_sequence("BBCA", start, 10, 10000.0)
    # Ticker B has 25 bars, but its last bar is 5 days ago (suspended / no bar on target_date)
    long_bars = create_bars_sequence("BBRI", start, 25, 5000.0)
    # Ticker C has 25 bars up to target_date
    valid_bars = create_bars_sequence("BMRI", start, 30, 7000.0)

    target_date = valid_bars[-1].date  # Target is Day 30

    class DummyClf:
        model_version = "dummy"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.80] * len(X)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClf(),
        bars_by_ticker={"BBCA": short_bars, "BBRI": long_bars, "BMRI": valid_bars},
    )

    # Only BMRI should be eligible
    assert len(signals) == 1
    assert signals[0].ticker == "BMRI"


def test_feature_snapshot_attached_and_deterministic_uuid():
    engine = SignalEngine()
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class DummyClf:
        model_version = "clf_v1"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.72] * len(X)

    signals1 = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=DummyClf(),
        bars_by_ticker={"BBCA": bars},
    )
    signals2 = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=DummyClf(),
        bars_by_ticker={"BBCA": bars},
    )

    assert len(signals1) == 1
    # Deterministic signal_id reproducibility
    assert signals1[0].signal_id == signals2[0].signal_id
    # Feature snapshot attached
    snapshot = signals1[0].feature_snapshot
    assert isinstance(snapshot, dict)
    assert len(snapshot) > 0


def test_signal_repository_immutability():
    repo = SignalRepository(":memory:")

    sig = SignalRecord(
        signal_id="sig-immut-001",
        ticker="BBCA",
        signal_date=date(2026, 10, 12),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10600.0,
        sl_price=9800.0,
        max_holding_days=10,
        predicted_probability=0.72,
        expected_return=0.04,
        score=80.0,
        model_version="v1.0",
        feature_snapshot={"rsi14": 55.0},
    )

    # Initial save succeeds
    saved = repo.save_signals([sig])
    assert saved == 1

    # Check exists
    assert repo.exists("BBCA", date(2026, 10, 12), "v1.0") is True

    # Mutated copy trying to overwrite historical signal
    mutated_sig = SignalRecord(
        signal_id="sig-immut-001",
        ticker="BBCA",
        signal_date=date(2026, 10, 12),
        signal="BUY",
        entry_low=9500.0,  # changed!
        entry_high=9600.0,
        tp_price=10100.0,
        sl_price=9300.0,
        max_holding_days=10,
        predicted_probability=0.99,  # changed!
        score=99.0,  # changed!
        model_version="v1.0",
        feature_snapshot={"rsi14": 99.0},
    )

    # Non-negotiable: duplicate insert MUST raise sqlite3.IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_signals([mutated_sig], ignore_existing=False)

    # Verify original record remained strictly IMMUTABLE
    fetched = repo.get_signal_by_id("sig-immut-001")
    assert fetched is not None
    assert fetched.predicted_probability == 0.72
    assert fetched.score == 80.0
    assert fetched.entry_low == 10000.0

    # With ignore_existing=True, duplicate is safely skipped
    saved_skipped = repo.save_signals([mutated_sig], ignore_existing=True)
    assert saved_skipped == 0
    # Still original values
    fetched_again = repo.get_signal_by_id("sig-immut-001")
    assert fetched_again.score == 80.0


def test_signal_repository_queries():
    repo = SignalRepository(":memory:")

    sig1 = SignalRecord(
        signal_id="sig-1",
        ticker="BBCA",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10600.0,
        sl_price=9800.0,
        predicted_probability=0.80,
        score=85.0,
        model_version="v1",
    )
    sig2 = SignalRecord(
        signal_id="sig-2",
        ticker="BBRI",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        entry_low=5000.0,
        entry_high=5050.0,
        tp_price=5300.0,
        sl_price=4900.0,
        predicted_probability=0.70,
        score=75.0,
        model_version="v1",
    )
    sig3 = SignalRecord(
        signal_id="sig-3",
        ticker="BMRI",
        signal_date=date(2026, 10, 2),
        signal="BUY",
        entry_low=7000.0,
        entry_high=7070.0,
        tp_price=7420.0,
        sl_price=6860.0,
        predicted_probability=0.75,
        score=80.0,
        model_version="v2",
    )

    repo.save_signals([sig1, sig2, sig3])

    assert repo.count_signals() == 3
    assert repo.count_signals(ticker="BBCA") == 1
    assert repo.count_signals(signal_date=date(2026, 10, 1)) == 2
    assert repo.count_signals(model_version="v2") == 1

    # Query by date and ordering
    day1_sigs = repo.get_signals_by_date(date(2026, 10, 1))
    assert len(day1_sigs) == 2
    assert day1_sigs[0].ticker == "BBCA"  # score 85 > score 75

    # Distinct dates
    dates = repo.get_distinct_dates()
    assert dates == [date(2026, 10, 1), date(2026, 10, 2)]

    # Query with min_score filter
    high_score_sigs = repo.get_signals(min_score=80.0)
    assert len(high_score_sigs) == 2


def test_non_trading_date_aborts():
    engine = SignalEngine()
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class DummyClf:
        model_version = "clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.70] * len(X)

    # Date not in bars (e.g. holiday or weekend)
    with pytest.raises(ValueError, match="not a completed trading date"):
        engine.generate_signals(
            signal_date=date(2026, 12, 31),
            classifier=DummyClf(),
            bars_by_ticker={"BBCA": bars},
        )


def test_insufficient_bars_across_universe_aborts():
    engine = SignalEngine()
    start = date(2026, 1, 1)
    # Only 5 bars, but min_history_bars=20
    bars = create_bars_sequence("BBCA", start, 5, 10000.0)

    class DummyClf:
        model_version = "clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.70] * len(X)

    with pytest.raises(ValueError, match="Insufficient historical bars"):
        engine.generate_signals(
            signal_date=bars[-1].date,
            classifier=DummyClf(),
            bars_by_ticker={"BBCA": bars},
            min_history_bars=20,
        )


def test_use_champion_without_champion_aborts(tmp_path):
    from python.models.registry import ModelRegistry

    empty_registry = ModelRegistry(registry_dir=tmp_path / "empty_reg")
    engine = SignalEngine(model_registry=empty_registry)
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    with pytest.raises(ValueError, match="No champion classification model registered"):
        engine.generate_signals(
            signal_date=bars[-1].date,
            use_champion=True,
            bars_by_ticker={"BBCA": bars},
        )


def test_sqlite_trigger_prevents_raw_update():
    repo = SignalRepository(":memory:")
    sig = SignalRecord(
        signal_id="sig-trigger-01",
        ticker="BBCA",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10600.0,
        sl_price=9800.0,
        predicted_probability=0.80,
        score=85.0,
        model_version="v1",
    )
    repo.save_signals([sig])

    conn = repo._get_connection()
    # Executing raw SQL UPDATE directly must be blocked by the trigger
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("UPDATE signals_daily SET score = 99.0 WHERE signal_id = 'sig-trigger-01';")


def test_repository_date_range_and_min_probability_query():
    repo = SignalRepository(":memory:")
    sig1 = SignalRecord(
        signal_id="sig-d1",
        ticker="BBCA",
        signal_date=date(2026, 10, 1),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10600.0,
        sl_price=9800.0,
        predicted_probability=0.60,
        score=65.0,
        model_version="v1",
    )
    sig2 = SignalRecord(
        signal_id="sig-d2",
        ticker="BBRI",
        signal_date=date(2026, 10, 5),
        signal="BUY",
        entry_low=5000.0,
        entry_high=5050.0,
        tp_price=5300.0,
        sl_price=4900.0,
        predicted_probability=0.75,
        score=80.0,
        model_version="v1",
    )
    sig3 = SignalRecord(
        signal_id="sig-d3",
        ticker="BMRI",
        signal_date=date(2026, 10, 10),
        signal="BUY",
        entry_low=7000.0,
        entry_high=7070.0,
        tp_price=7420.0,
        sl_price=6860.0,
        predicted_probability=0.85,
        score=90.0,
        model_version="v1",
    )
    repo.save_signals([sig1, sig2, sig3])

    # Range query: between Oct 2 and Oct 6
    range_sigs = repo.get_signals(
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 6),
    )
    assert len(range_sigs) == 1
    assert range_sigs[0].ticker == "BBRI"

    # min_probability query
    prob_sigs = repo.get_signals(min_probability=0.70)
    assert len(prob_sigs) == 2
    assert {s.ticker for s in prob_sigs} == {"BBRI", "BMRI"}


def test_ev_hurdle_blocks_negative_ev_bets():
    """Verify that a candidate passing min_probability=0.25 is BLOCKED when net EV <= 0."""
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class LowEdgeClassifier:
        model_version = "low_edge_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.26] * len(X)

    # 1. With EV hurdle enforced (default), 26% prob has negative EV -> 0 signals
    cfg = SignalConfig(min_probability=0.25, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)
    signals = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=LowEdgeClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 0

    # 2. When EV hurdle is disabled, 26% passes min_probability 0.25
    cfg_no_ev = SignalConfig(min_probability=0.25, enforce_positive_ev=False)
    engine_no_ev = SignalEngine(config=cfg_no_ev)
    signals_no_ev = engine_no_ev.generate_signals(
        signal_date=bars[-1].date,
        classifier=LowEdgeClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg_no_ev,
    )
    assert len(signals_no_ev) == 1
    assert signals_no_ev[0].predicted_probability == 0.26


def test_ev_hurdle_passes_positive_ev_bets():
    """Verify that candidate with positive net EV (>32.1% with empirical expiry) is emitted."""
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class PositiveEdgeClassifier:
        model_version = "pos_edge_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.35] * len(X)

    cfg = SignalConfig(min_probability=0.25, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)
    signals = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=PositiveEdgeClassifier(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 1
    assert signals[0].signal == "BUY"
    assert signals[0].expected_return is not None
    assert signals[0].expected_return > 0.0
    assert signals[0].net_ev is not None
    assert signals[0].net_ev > 0.0


def test_ev_hurdle_fails_closed_when_regressor_predicts_negative_return():
    """Verify that even with high win prob, negative predicted return rejects candidate."""
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class HighProbClassifier:
        model_version = "high_p_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.80] * len(X)

    class NegativeReturnRegressor:
        model_version = "neg_reg"

        def predict_expected_return(self, X: Any) -> list[float]:
            return [-0.02] * len(X)

    cfg = SignalConfig(min_probability=0.25, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)
    signals = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=HighProbClassifier(),
        regressor=NegativeReturnRegressor(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 0


def test_ev_hurdle_fails_closed_when_regressor_predicts_nan_or_inf():
    """Verify that NaN or Inf from regressor fails closed and does not emit BUY signals."""
    start = date(2026, 1, 1)
    bars = create_bars_sequence("BBCA", start, 25, 10000.0)

    class HighProbClassifier:
        model_version = "high_p_clf"
        feature_names_ = ["return_1d"]

        def predict_probability(self, X: Any) -> list[float]:
            return [0.80] * len(X)

    class NanRegressor:
        model_version = "nan_reg"

        def predict_expected_return(self, X: Any) -> list[float]:
            return [float("nan")] * len(X)

    class InfRegressor:
        model_version = "inf_reg"

        def predict_expected_return(self, X: Any) -> list[float]:
            return [float("inf")] * len(X)

    # 1. require_expected_return=True with NaN regressor -> Fail closed (0 signals)
    cfg_req = SignalConfig(
        min_probability=0.25,
        enforce_positive_ev=True,
        require_expected_return=True,
    )
    engine = SignalEngine(config=cfg_req)
    sigs_nan = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=HighProbClassifier(),
        regressor=NanRegressor(),
        bars_by_ticker={"BBCA": bars},
        config=cfg_req,
    )
    assert len(sigs_nan) == 0

    # 2. require_expected_return=True with Inf regressor -> Fail closed (0 signals)
    sigs_inf = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=HighProbClassifier(),
        regressor=InfRegressor(),
        bars_by_ticker={"BBCA": bars},
        config=cfg_req,
    )
    assert len(sigs_inf) == 0

    # 3. require_expected_return=False with NaN regressor -> Fallback to discrete EV
    cfg_opt = SignalConfig(
        min_probability=0.25,
        enforce_positive_ev=True,
        require_expected_return=False,
    )
    sigs_opt = engine.generate_signals(
        signal_date=bars[-1].date,
        classifier=HighProbClassifier(),
        regressor=NanRegressor(),
        bars_by_ticker={"BBCA": bars},
        config=cfg_opt,
    )
    assert len(sigs_opt) == 1
    assert math.isfinite(sigs_opt[0].expected_return)
    assert math.isfinite(sigs_opt[0].net_ev)


