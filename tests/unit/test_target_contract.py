"""Unit tests for Phase 11B.0 Target Contract Audit logic."""

from datetime import date

from python.common.types import DailyBar
from scripts.audit_target_contract_runner import evaluate_variant_b


def make_bar(
    ticker: str,
    d: date,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1_000_000.0,
) -> DailyBar:
    return DailyBar(
        ticker=ticker,
        date=d,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_variant_b_gap_below_sl_invalidation():
    """Stock gapping down below SL barrier on Day 1 is invalidated."""
    entry_bar = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)
    # Day 1 opens at 97.5 (<= 100 * 0.98 = 98.0)
    b1 = make_bar("TEST", date(2026, 1, 2), 97.5, 99.0, 96.0, 98.0)
    forward = [b1] + [
        make_bar("TEST", date(2026, 1, 3 + i), 98.0, 99.0, 97.0, 98.0)
        for i in range(9)
    ]

    res = evaluate_variant_b(entry_bar, forward)
    assert res["status"] == "INVALIDATED"
    assert res["entry_status"] == "UNFILLED"
    assert res["invalidation_reason"] == "GAP_BELOW_SL"
    assert res["outcome"] == "INVALIDATED_GAP"
    assert res["binary_target"] is None
    assert res["realized_return"] is None


def test_variant_b_gap_above_tp_invalidation():
    """Stock gapping up at or above TP barrier on Day 1 is invalidated."""
    entry_bar = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)
    # Day 1 opens at 105.5 (>= 100 * 1.05 = 105.0)
    b1 = make_bar("TEST", date(2026, 1, 2), 105.5, 108.0, 105.0, 107.0)
    forward = [b1] + [
        make_bar("TEST", date(2026, 1, 3 + i), 107.0, 108.0, 106.0, 107.0)
        for i in range(9)
    ]

    res = evaluate_variant_b(entry_bar, forward)
    assert res["status"] == "INVALIDATED"
    assert res["entry_status"] == "UNFILLED"
    assert res["invalidation_reason"] == "GAP_ABOVE_TP"
    assert res["outcome"] == "INVALIDATED_GAP"
    assert res["binary_target"] is None


def test_variant_b_valid_entry_and_tp_hit():
    """Stock opens within valid range, entry anchors to open, hits +5% TP."""
    entry_bar = make_bar("TEST", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    # Day 1 opens at 101.0 (valid, +1.0% from close)
    # TP barrier is 101.0 * 1.05 = 106.05
    # SL barrier is 101.0 * 0.98 = 98.98
    b1 = make_bar("TEST", date(2026, 1, 2), 101.0, 103.0, 100.0, 102.0)
    # Day 2 reaches 107.0 (>= 106.05)
    b2 = make_bar("TEST", date(2026, 1, 3), 102.0, 107.0, 101.5, 106.5)
    forward = [b1, b2] + [
        make_bar("TEST", date(2026, 1, 4 + i), 106.0, 107.0, 105.0, 106.0)
        for i in range(8)
    ]

    res = evaluate_variant_b(entry_bar, forward)
    assert res["status"] == "VALID"
    assert res["entry_status"] == "FILLED"
    assert res["entry_price"] == 101.0
    assert res["outcome"] == "TP"
    assert res["binary_target"] == 1
    assert res["holding_days"] == 2
    assert abs(res["realized_return"] - 0.05) < 1e-4


def test_variant_b_valid_entry_and_sl_hit():
    """Stock opens within valid range, drops and hits -2% SL."""
    entry_bar = make_bar("TEST", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    # Day 1 opens at 99.5. SL is 99.5 * 0.98 = 97.51
    b1 = make_bar("TEST", date(2026, 1, 2), 99.5, 100.0, 99.0, 99.2)
    # Day 2 drops to 97.0 (<= 97.51)
    b2 = make_bar("TEST", date(2026, 1, 3), 99.0, 99.5, 97.0, 97.5)
    forward = [b1, b2] + [
        make_bar("TEST", date(2026, 1, 4 + i), 97.0, 98.0, 96.0, 97.0)
        for i in range(8)
    ]

    res = evaluate_variant_b(entry_bar, forward)
    assert res["status"] == "VALID"
    assert res["outcome"] == "SL"
    assert res["binary_target"] == 0
    assert res["holding_days"] == 2
    assert abs(res["realized_return"] - (-0.02)) < 1e-4


def test_variant_b_expiry_after_10_days():
    """Stock never hits TP or SL, exits at close on day 10."""
    entry_bar = make_bar("TEST", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    # All forward days trade in [99.0, 102.0], entry at 100.0
    forward = [
        make_bar("TEST", date(2026, 1, 2 + i), 100.0, 102.0, 99.0, 101.0)
        for i in range(10)
    ]

    res = evaluate_variant_b(entry_bar, forward)
    assert res["status"] == "VALID"
    assert res["outcome"] == "EXPIRY"
    assert res["binary_target"] == 0
    assert res["holding_days"] == 10
    assert abs(res["realized_return"] - 0.01) < 1e-4
