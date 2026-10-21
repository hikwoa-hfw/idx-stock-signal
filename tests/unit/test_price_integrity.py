from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from python.common.types import (
    DailyBar,
    FeatureRecord,
    SignalConfig,
    SignalRecord,
    get_bei_tick_size,
    round_down_to_tick,
    round_to_nearest_tick,
    round_up_to_tick,
)
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository
from services.telegram.formatter import format_daily_signals, format_dual_mode_signals


class DummyClassifier:
    """Mock classifier returning fixed high probability."""

    def __init__(self, prob: float = 0.80) -> None:
        self.prob = prob
        self.model_version = "dummy_clf_v1"
        self.feature_names_ = ["return_1d", "volume_ratio_20d"]

    def predict_probability(self, X: Any) -> list[float]:
        return [self.prob] * len(X)


def create_bars_with_prices(
    ticker: str,
    end_date: date,
    count: int,
    close_price: float,
    adj_close: float | None = None,
    dividends: float = 0.0,
    stock_splits: float = 0.0,
) -> list[DailyBar]:
    bars = []
    start_date = end_date - timedelta(days=count - 1)
    for i in range(count):
        d = start_date + timedelta(days=i)
        p = close_price if i == count - 1 else max(50.0, close_price - (count - 1 - i))
        ac = adj_close if (i == count - 1 and adj_close is not None) else p
        bars.append(
            DailyBar(
                ticker=ticker,
                date=d,
                open=p,
                high=p + 2.0,
                low=max(1.0, p - 2.0),
                close=p,
                volume=1_000_000.0,
                value=p * 1_000_000.0,
                adj_close=ac,
                dividends=dividends if i == count - 1 else 0.0,
                stock_splits=stock_splits if i == count - 1 else 0.0,
                provider="test",
                provider_symbol=f"{ticker}.JK",
            )
        )
    return bars


# ==============================================================================
# 1. IDR 44 Close vs IDR 56 Entry Discrepancy Fails Closed
# ==============================================================================


def test_idr_44_close_idr_56_entry_discrepancy_fails_closed():
    """Verify that a candidate with close IDR 44 and entry IDR 56 (+27.3% deviation)
    cannot be created or emitted as an immediate BUY signal (fails closed).
    """
    # 1. At SignalRecord type level: immediate BUY cannot deviate by +27.3% from reference price
    with pytest.raises(ValueError, match="deviates excessively from reference price"):
        SignalRecord(
            signal_id="sig-disc-001",
            ticker="MDLN",
            signal_date=date(2026, 10, 14),
            signal="BUY",
            status="BUY",
            entry_low=56.0,
            entry_high=57.0,
            tp_price=60.0,
            sl_price=54.0,
            reference_price=44.0,
            entry_policy="IMMEDIATE",
            predicted_probability=0.75,
            score=80.0,
            model_version="test_v1",
        )

    # 2. At SignalEngine level: candidate price 44 cannot produce entry 56 without breakout policy
    target_date = date(2026, 10, 14)
    # Price is 44, but sub-50 is excluded or if price is 44:
    # If a stock close is 44, it is EXCLUDED_BELOW_50 from normal signals
    bars_44 = create_bars_with_prices("MDLN", target_date, 25, close_price=44.0)

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"MDLN": bars_44},
    )
    # Ticker trading at 44 is below 50, so must be excluded and never emit BUY
    assert len(signals) == 0


def test_discrepancy_beyond_max_deviation_fails_closed_in_engine():
    """Verify that if an entry price deviates beyond max_entry_deviation_pct without
    breakout policy enabled, the engine rejects the candidate (fail-closed).
    """
    target_date = date(2026, 10, 14)
    # Stock at 100 IDR
    bars = create_bars_with_prices("TEST", target_date, 25, close_price=100.0)

    # Allow breakout disabled, max deviation 5%
    cfg = SignalConfig(
        min_probability=0.25,
        max_entry_deviation_pct=0.02,
        allow_breakout=False,
        entry_band_pct=0.10,  # 10% band -> entry_low 95, entry_high 105 (>2% deviation)
    )
    engine = SignalEngine(config=cfg)
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"TEST": bars},
    )
    # Discrepancy beyond max_entry_deviation_pct with allow_breakout=False must fail closed
    assert len(signals) == 0


# ==============================================================================
# 2. Entry Range Collapse Prevention & Outward Rounding
# ==============================================================================


def test_entry_range_no_collapse_with_outward_rounding():
    """Verify that entry range for low-priced stocks (e.g. BKSL at 53 or 56, BMTR at 76)
    does not collapse to a single point (e.g. 53-53 or 56-56).
    """
    target_date = date(2026, 10, 14)

    # 1. BKSL at IDR 53 (tick = 1)
    bars_53 = create_bars_with_prices("BKSL", target_date, 25, close_price=53.0)
    cfg = SignalConfig(min_probability=0.25, entry_band_pct=0.01)  # 1% band around 53
    engine = SignalEngine(config=cfg)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BKSL": bars_53},
    )
    assert len(signals) == 1
    sig = signals[0]
    # Outward rounding ensures entry_low < entry_high
    assert sig.entry_low < sig.entry_high
    assert sig.entry_low == 52.0
    assert sig.entry_high == 54.0

    # 2. Stock at IDR 56 (tick = 1)
    bars_56 = create_bars_with_prices("BKSL56", target_date, 25, close_price=56.0)
    signals_56 = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BKSL56": bars_56},
    )
    assert len(signals_56) == 1
    sig_56 = signals_56[0]
    assert sig_56.entry_low < sig_56.entry_high
    assert sig_56.entry_low == 55.0
    assert sig_56.entry_high == 57.0

    # 3. Stock at IDR 76 (tick = 1)
    bars_76 = create_bars_with_prices("BMTR", target_date, 25, close_price=76.0)
    signals_76 = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BMTR": bars_76},
    )
    assert len(signals_76) == 1
    sig_76 = signals_76[0]
    assert sig_76.entry_low < sig_76.entry_high
    assert sig_76.entry_low == 75.0
    assert sig_76.entry_high == 77.0


def test_entry_range_zero_band_expands_to_minimum_tick_width():
    """Verify that even when entry_band_pct is 0, outward rounding ensures
    a minimum range width of at least min_range_ticks ticks.
    """
    target_date = date(2026, 10, 14)
    bars = create_bars_with_prices("BKSL", target_date, 25, close_price=53.0)

    cfg = SignalConfig(min_probability=0.25, entry_band_pct=0.0, min_range_ticks=1)
    engine = SignalEngine(config=cfg)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BKSL": bars},
    )
    assert len(signals) == 1
    sig = signals[0]
    # Symmetrically expanded by 1 tick below and 1 tick above
    assert sig.entry_high > sig.entry_low
    assert sig.entry_high - sig.entry_low >= 1.0


def test_telegram_formatter_prevents_single_value_display_collapse():
    """Verify that format_dual_mode_signals never renders a collapsed single value
    like '53–53' or '56–56' in Telegram output.
    """
    # Create record where raw floats round to the same integer
    sig = SignalRecord(
        signal_id="sig-collapse-test",
        ticker="BKSL",
        signal_date=date(2026, 10, 14),
        signal="BUY",
        status="BUY",
        entry_low=52.73,
        entry_high=53.26,
        tp_price=56.0,
        sl_price=51.0,
        reference_price=53.0,
        predicted_probability=0.32,
        score=27.7,
        model_version="test_v1",
        mode="LOW_PRICE",
    )

    formatted = format_dual_mode_signals([sig], target_date=date(2026, 10, 14))
    # Must NOT contain "53–53"
    assert "53–53" not in formatted
    assert "56–56" not in formatted
    # Must display distinct tick boundaries
    assert "52–54" in formatted or "52–53" in formatted


# ==============================================================================
# 3. BEI Tick Size Compliance Across All Brackets
# ==============================================================================


def test_bei_tick_size_rules_all_brackets():
    """Verify official BEI tick size (fraksi harga) calculation across all 5 price brackets."""
    # Bracket 1: < 200 -> tick 1
    assert get_bei_tick_size(50.0) == 1
    assert get_bei_tick_size(100.0) == 1
    assert get_bei_tick_size(199.0) == 1

    # Bracket 2: 200 - < 500 -> tick 2
    assert get_bei_tick_size(200.0) == 2
    assert get_bei_tick_size(350.0) == 2
    assert get_bei_tick_size(498.0) == 2

    # Bracket 3: 500 - < 2000 -> tick 5
    assert get_bei_tick_size(500.0) == 5
    assert get_bei_tick_size(1250.0) == 5
    assert get_bei_tick_size(1995.0) == 5

    # Bracket 4: 2000 - < 5000 -> tick 10
    assert get_bei_tick_size(2000.0) == 10
    assert get_bei_tick_size(3100.0) == 10
    assert get_bei_tick_size(4990.0) == 10

    # Bracket 5: >= 5000 -> tick 25
    assert get_bei_tick_size(5000.0) == 25
    assert get_bei_tick_size(8500.0) == 25
    assert get_bei_tick_size(192000.0) == 25


def test_bei_rounding_helpers():
    """Verify round_down_to_tick, round_up_to_tick, and round_to_nearest_tick."""
    # Price in bracket 2 (tick 2): 251.3
    assert round_down_to_tick(251.3) == 250.0
    assert round_up_to_tick(251.3) == 252.0
    assert round_to_nearest_tick(251.3) == 252.0

    # Price in bracket 5 (tick 25): 8530.0
    assert round_down_to_tick(8530.0) == 8525.0
    assert round_up_to_tick(8530.0) == 8550.0
    assert round_to_nearest_tick(8530.0) == 8525.0


def test_enforce_bei_ticks_produces_exact_multiples():
    """Verify that when enforce_bei_ticks=True, all prices (entry, TP, SL)
    are exact integer multiples of their respective BEI tick sizes.
    """
    target_date = date(2026, 10, 14)
    # DCII at 192,000 IDR (tick 25)
    bars_dcii = create_bars_with_prices("DCII", target_date, 25, close_price=192000.0)
    # BBRI at 3,120 IDR (tick 10)
    bars_bbri = create_bars_with_prices("BBRI", target_date, 25, close_price=3120.0)

    cfg = SignalConfig(min_probability=0.25, enforce_bei_ticks=True)
    engine = SignalEngine(config=cfg)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"DCII": bars_dcii, "BBRI": bars_bbri},
    )

    assert len(signals) == 2
    for s in signals:
        tick_low = get_bei_tick_size(s.entry_low)
        tick_high = get_bei_tick_size(s.entry_high)
        tick_tp = get_bei_tick_size(s.tp_price)
        tick_sl = get_bei_tick_size(s.sl_price)

        assert s.entry_low % tick_low == 0
        assert s.entry_high % tick_high == 0
        assert s.tp_price % tick_tp == 0
        assert s.sl_price % tick_sl == 0


# ==============================================================================
# 4. Stale Data Rejection Fails Closed
# ==============================================================================


def test_stale_data_fails_closed():
    """Verify that a ticker whose latest bar is older than the target trading date
    is rejected and fails closed.
    """
    target_date = date(2026, 10, 14)
    # Ticker A has bars up to 2026-10-14 (current)
    bars_current = create_bars_with_prices("BBCA", target_date, 25, close_price=10000.0)
    # Ticker B has bars up to 2026-10-09 (stale by 5 days)
    stale_date = date(2026, 10, 9)
    bars_stale = create_bars_with_prices("STALE", stale_date, 25, close_price=5000.0)

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BBCA": bars_current, "STALE": bars_stale},
    )

    # Only BBCA should qualify; STALE must be completely excluded
    assert len(signals) == 1
    assert signals[0].ticker == "BBCA"


# ==============================================================================
# 5. Mismatched Ticker / Date Fails Closed
# ==============================================================================


def test_mismatched_ticker_or_date_fails_closed():
    """Verify that if feature record date/ticker does not match the bar,
    the candidate fails closed.
    """
    target_date = date(2026, 10, 14)
    bars = create_bars_with_prices("BBCA", target_date, 25, close_price=10000.0)

    # Mismatched date in feature record
    mismatched_feat = [
        FeatureRecord(
            ticker="BBCA",
            date=date(2026, 10, 9),  # Wrong date!
            volume_ratio_20d=1.5,
        )
    ]

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BBCA": bars},
        features_by_ticker={"BBCA": mismatched_feat},
    )
    assert len(signals) == 0


# ==============================================================================
# 6. Raw vs Adjusted Price Inconsistency Fails Closed
# ==============================================================================


def test_raw_versus_adjusted_price_inconsistency_fails_closed():
    """Verify that when raw close and adjusted close diverge significantly
    without corporate actions (e.g. raw 56, adj 44), candidate fails closed.
    """
    target_date = date(2026, 10, 14)
    # Raw close = 56.0, adj_close = 44.0, no dividends or splits (21.4% unexplained diff)
    corrupted_bars = create_bars_with_prices(
        ticker="INCON",
        end_date=target_date,
        count=25,
        close_price=56.0,
        adj_close=44.0,
        dividends=0.0,
        stock_splits=0.0,
    )

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"INCON": corrupted_bars},
    )
    # Corrupted / inconsistent raw vs adj prices must be excluded
    assert len(signals) == 0


def test_legitimate_split_dividend_passes():
    """Verify that when dividends or stock splits are present, legitimate
    difference between close and adj_close is permitted.
    """
    target_date = date(2026, 10, 14)
    # Close 1000, adj_close 800 with stock_splits 1.25
    legit_bars = create_bars_with_prices(
        ticker="SPLIT",
        end_date=target_date,
        count=25,
        close_price=1000.0,
        adj_close=800.0,
        stock_splits=1.25,
    )

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"SPLIT": legit_bars},
    )
    assert len(signals) == 1
    assert signals[0].ticker == "SPLIT"


# ==============================================================================
# 7. Breakout Trigger Status WAIT_FOR_BREAKOUT
# ==============================================================================


def test_breakout_trigger_status_wait_for_breakout():
    """Verify that if an entry represents a breakout trigger above reference price,
    it receives status WAIT_FOR_BREAKOUT, not an immediate BUY.
    """
    # 1. Direct SignalRecord validation
    sig = SignalRecord(
        signal_id="sig-breakout-001",
        ticker="BRMS",
        signal_date=date(2026, 10, 14),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_low=56.0,
        entry_high=58.0,
        tp_price=64.0,
        sl_price=52.0,
        reference_price=44.0,
        entry_policy="BREAKOUT",
        predicted_probability=0.70,
        score=78.0,
        model_version="test_v1",
    )
    assert sig.status == "WAIT_FOR_BREAKOUT"
    assert sig.signal == "WAIT_FOR_BREAKOUT"
    assert sig.entry_policy == "BREAKOUT"

    # 2. Formatter presentation
    formatted = format_dual_mode_signals([sig], target_date=date(2026, 10, 14))
    assert "Status: WAIT_FOR_BREAKOUT" in formatted
    assert "Status: BUY" not in formatted


# ==============================================================================
# 8. Price Integrity Metadata Recording & Repository Persistence
# ==============================================================================


def test_price_integrity_fields_recorded_and_persisted():
    """Verify that signal_generated_at, market_data_as_of, latest_completed_bar_date,
    reference_price, entry_policy, and status are recorded and persisted to SQLite.
    """
    target_date = date(2026, 10, 14)
    bars = create_bars_with_prices("BBCA", target_date, 25, close_price=10000.0)

    engine = SignalEngine(config=SignalConfig(min_probability=0.25))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BBCA": bars},
    )

    assert len(signals) == 1
    s = signals[0]

    # Verify fields populated on generated SignalRecord
    assert s.reference_price == 10000.0
    assert s.latest_completed_bar_date == target_date
    assert s.entry_policy == "IMMEDIATE"
    assert s.status == "BUY"
    assert isinstance(s.signal_generated_at, datetime)
    assert isinstance(s.market_data_as_of, datetime)

    # Verify SQLite persistence and retrieval
    repo = SignalRepository(":memory:")
    saved = repo.save_signals([s])
    assert saved == 1

    loaded = repo.get_signal_by_id(s.signal_id)
    assert loaded is not None
    assert loaded.ticker == "BBCA"
    assert loaded.reference_price == 10000.0
    assert loaded.latest_completed_bar_date == target_date
    assert loaded.entry_policy == "IMMEDIATE"
    assert loaded.status == "BUY"
    assert loaded.signal_generated_at is not None
    assert loaded.market_data_as_of is not None


# ==============================================================================
# 9. Daily Yahoo Finance Data Not Presented as Real-Time Quote
# ==============================================================================


def test_daily_data_not_presented_as_realtime_quote():
    """Verify that Telegram formatting clearly distinguishes market data as-of
    completed daily close rather than a real-time quote.
    """
    sig = SignalRecord(
        signal_id="sig-eod-001",
        ticker="ASII",
        signal_date=date(2026, 10, 14),
        signal="BUY",
        status="BUY",
        entry_low=5000.0,
        entry_high=5050.0,
        tp_price=5300.0,
        sl_price=4900.0,
        reference_price=5025.0,
        entry_policy="IMMEDIATE",
        predicted_probability=0.75,
        score=82.0,
        model_version="test_v1",
        mode="HIGHER_PRICE",
    )

    dual_text = format_dual_mode_signals([sig], target_date=date(2026, 10, 14))
    single_text = format_daily_signals([sig], target_date=date(2026, 10, 14))

    # Dual mode header mentions Daily Close / Not Real-Time
    assert "Daily Close" in dual_text or "Not Real-Time" in dual_text
    # Single mode header also clarifies Daily Close
    assert "Daily Close" in single_text
    # Ref close is clearly labeled
    assert "Ref Close: 5,025" in dual_text


# ==============================================================================
# 10. Comprehensive Regression Tests for Bracket Transitions & Breakout Gaps
# ==============================================================================


def test_illegal_tick_boundary_transitions_500_and_5000():
    """Verify that bracket boundary prices (e.g. 500 IDR and 5000 IDR)
    never produce illegal exchange ticks (e.g. 495 in tick-2 bracket or 4975 in tick-10 bracket).
    """
    target_date = date(2026, 10, 14)

    # 1. Stock at 500 IDR (bracket 2/3 transition)
    bars_500 = create_bars_with_prices("T500", target_date, 25, close_price=500.0)
    cfg = SignalConfig(min_probability=0.25, entry_band_pct=0.01, enforce_bei_ticks=True)
    engine = SignalEngine(config=cfg)

    signals_500 = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"T500": bars_500},
    )
    assert len(signals_500) == 1
    s500 = signals_500[0]
    # entry_low must be a valid tick in its bracket (< 500 -> tick 2, so even number)
    tick_low = get_bei_tick_size(s500.entry_low)
    assert s500.entry_low % tick_low == 0
    assert s500.entry_low != 495.0, (
        "495 is an illegal BEI tick in bracket 2 (< 500 requires tick 2)"
    )
    # entry_high must be a valid tick in its bracket (>= 500 -> tick 5)
    tick_high = get_bei_tick_size(s500.entry_high)
    assert s500.entry_high % tick_high == 0

    # 2. Stock at 5000 IDR (bracket 4/5 transition)
    bars_5000 = create_bars_with_prices("T5000", target_date, 25, close_price=5000.0)
    signals_5000 = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"T5000": bars_5000},
    )
    assert len(signals_5000) == 1
    s5000 = signals_5000[0]
    tick_low_5000 = get_bei_tick_size(s5000.entry_low)
    assert s5000.entry_low % tick_low_5000 == 0
    assert s5000.entry_low != 4975.0, (
        "4975 is an illegal BEI tick in bracket 4 (< 5000 requires tick 10)"
    )
    tick_high_5000 = get_bei_tick_size(s5000.entry_high)
    assert s5000.entry_high % tick_high_5000 == 0


def test_signal_record_rejects_breakout_policy_with_buy_status():
    """Verify that a SignalRecord with BREAKOUT entry policy cannot be assigned BUY status."""
    with pytest.raises(ValueError, match="Signal with BREAKOUT policy cannot have BUY status"):
        SignalRecord(
            signal_id="sig-breakout-invalid",
            ticker="BKSL",
            signal_date=date(2026, 10, 14),
            signal="BUY",
            status="BUY",
            entry_low=56.0,
            entry_high=58.0,
            tp_price=62.0,
            sl_price=52.0,
            reference_price=44.0,
            entry_policy="BREAKOUT",
            predicted_probability=0.70,
            score=75.0,
            model_version="test_v1",
        )


def test_signal_record_rejects_breakout_trigger_below_reference_price():
    """Verify that a breakout trigger entry cannot be below reference price."""
    with pytest.raises(ValueError, match="cannot be below reference price"):
        SignalRecord(
            signal_id="sig-breakout-below",
            ticker="BKSL",
            signal_date=date(2026, 10, 14),
            signal="WAIT_FOR_BREAKOUT",
            status="WAIT_FOR_BREAKOUT",
            entry_low=40.0,
            entry_high=42.0,
            tp_price=48.0,
            sl_price=38.0,
            reference_price=44.0,
            entry_policy="BREAKOUT",
            predicted_probability=0.70,
            score=75.0,
            model_version="test_v1",
        )


def test_signal_engine_downward_discrepancy_fails_closed():
    """Verify that an unexplained downward discrepancy beyond max deviation fails closed."""
    target_date = date(2026, 10, 14)
    # Reference price 100
    bars = create_bars_with_prices("DOWN", target_date, 25, close_price=100.0)

    # Feature record with downward entry_price = 80.0 (-20% below reference price)
    feat_down = FeatureRecord(
        ticker="DOWN",
        date=target_date,
        volume_ratio_20d=1.5,
        entry_price=80.0,
    )

    engine = SignalEngine(config=SignalConfig(min_probability=0.25, max_entry_deviation_pct=0.05))
    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"DOWN": bars},
        features_by_ticker={"DOWN": [feat_down]},
    )
    # Downward discrepancy must fail closed (candidate excluded)
    assert len(signals) == 0


def test_signal_engine_breakout_target_classification_and_fail_closed():
    """Verify that an upside target above reference price receives WAIT_FOR_BREAKOUT
    when allow_breakout=True, and fails closed when allow_breakout=False.
    """
    target_date = date(2026, 10, 14)
    # Reference price 60 (eligible LOW_PRICE stock)
    bars_60 = create_bars_with_prices("BKSL", target_date, 25, close_price=60.0)
    # Target entry 75 (+25% above reference price)
    feat_breakout = FeatureRecord(
        ticker="BKSL",
        date=target_date,
        volume_ratio_20d=1.5,
        breakout_price=75.0,
    )

    # 1. When allow_breakout=True, mode classified as BREAKOUT with WAIT_FOR_BREAKOUT status
    cfg_allow = SignalConfig(
        min_probability=0.25,
        max_entry_deviation_pct=0.05,
        allow_breakout=True,
    )
    engine_allow = SignalEngine(config=cfg_allow)
    signals_allow = engine_allow.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BKSL": bars_60},
        features_by_ticker={"BKSL": [feat_breakout]},
    )
    assert len(signals_allow) == 1
    sig = signals_allow[0]
    assert sig.ticker == "BKSL"
    assert sig.status == "WAIT_FOR_BREAKOUT"
    assert sig.signal == "WAIT_FOR_BREAKOUT"
    assert sig.entry_policy == "BREAKOUT"
    assert sig.reference_price == 60.0
    assert sig.entry_low >= 74.0

    # 2. When allow_breakout=False, candidate fails closed
    cfg_disallow = SignalConfig(
        min_probability=0.25,
        max_entry_deviation_pct=0.05,
        allow_breakout=False,
    )
    engine_disallow = SignalEngine(config=cfg_disallow)
    signals_disallow = engine_disallow.generate_signals(
        signal_date=target_date,
        classifier=DummyClassifier(0.80),
        bars_by_ticker={"BKSL": bars_60},
        features_by_ticker={"BKSL": [feat_breakout]},
    )
    assert len(signals_disallow) == 0


def test_single_mode_telegram_formatter_includes_status_and_ref_close():
    """Verify format_daily_signals displays Status, Ref Close, and prevents collapse."""
    sig_breakout = SignalRecord(
        signal_id="sig-single-001",
        ticker="BRMS",
        signal_date=date(2026, 10, 14),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_low=56.0,
        entry_high=58.0,
        tp_price=64.0,
        sl_price=52.0,
        reference_price=44.0,
        entry_policy="BREAKOUT",
        predicted_probability=0.75,
        score=85.0,
        model_version="test_v1",
    )

    formatted = format_daily_signals(
        [sig_breakout], target_date=date(2026, 10, 14), dual_mode=False
    )
    assert "Status          : WAIT_FOR_BREAKOUT" in formatted
    assert "Ref Close       : 44" in formatted
    assert "Entry           : 56–58" in formatted
    assert "Daily Close / Not Real-Time Quote" in formatted


def test_telegram_bot_handle_signals_shows_status_and_ref(monkeypatch, tmp_path):
    """Verify TelegramBotDispatcher.handle_signals formats status and reference close."""
    from python.data.repository import DailyBarRepository
    from python.journal.service import PositionJournalService
    from python.models.registry import ModelRegistry
    from services.telegram.bot import TelegramBotDispatcher

    db_file = tmp_path / "test_bot.db"
    sig_repo = SignalRepository(str(db_file))
    sig = SignalRecord(
        signal_id="sig-bot-001",
        ticker="WIRG",
        signal_date=date(2026, 10, 14),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_low=56.0,
        entry_high=58.0,
        tp_price=64.0,
        sl_price=52.0,
        reference_price=44.0,
        entry_policy="BREAKOUT",
        predicted_probability=0.75,
        score=85.0,
        model_version="test_v1",
    )
    sig_repo.save_signals([sig])

    dispatcher = TelegramBotDispatcher(
        signal_repo=sig_repo,
        bar_repo=DailyBarRepository(str(db_file)),
        journal_service=PositionJournalService(str(db_file)),
        model_registry=ModelRegistry(str(tmp_path / "reg")),
    )

    output = dispatcher.handle_signals()
    assert "[WAIT_FOR_BREAKOUT]" in output
    assert "Ref: 44" in output
    assert "56–58" in output


def test_csv_export_includes_all_audit_fields(capsys):
    """Verify print_csv_signals includes all required price-integrity audit columns."""
    from scripts.generate_signals import print_csv_signals

    sig = SignalRecord(
        signal_id="sig-csv-001",
        ticker="ASII",
        signal_date=date(2026, 10, 14),
        signal="BUY",
        status="BUY",
        entry_low=5000.0,
        entry_high=5050.0,
        tp_price=5300.0,
        sl_price=4900.0,
        reference_price=5025.0,
        entry_policy="IMMEDIATE",
        predicted_probability=0.75,
        score=82.0,
        model_version="test_v1",
        latest_completed_bar_date=date(2026, 10, 14),
        market_data_as_of=datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc),
        signal_generated_at=datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc),
    )

    print_csv_signals([sig])
    captured = capsys.readouterr().out
    header = captured.splitlines()[0]

    # Required audit columns from Requirement 6
    assert "signal_generated_at" in header
    assert "market_data_as_of" in header
    assert "latest_completed_bar_date" in header
    assert "reference_price" in header
    assert "entry_low" in header
    assert "entry_high" in header
    assert "entry_policy" in header
    assert "status" in header
