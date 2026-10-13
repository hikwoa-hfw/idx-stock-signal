from datetime import date

import pytest

from python.common.types import DailyBar
from python.data.validation import (
    DataValidationError,
    validate_bar,
    validate_daily_bars,
)


def _make_bar(**overrides) -> DailyBar:
    data = {
        "ticker": "BBCA",
        "date": date(2026, 10, 1),
        "open": 10000.0,
        "high": 10200.0,
        "low": 9900.0,
        "close": 10100.0,
        "volume": 500000.0,
        "value": 5050000000.0,
    }
    data.update(overrides)
    return DailyBar(**data)


def test_valid_bar_passes():
    bar = _make_bar()
    errors = validate_bar(bar)
    assert errors == []


def test_invalid_open_fails():
    bar = _make_bar(open=0.0)
    errors = validate_bar(bar)
    assert any("open must be > 0" in err for err in errors)


def test_invalid_high_fails():
    bar = _make_bar(open=10000.0, close=10200.0, high=10100.0)
    errors = validate_bar(bar)
    assert any("high must be >= max" in err for err in errors)


def test_invalid_low_fails():
    bar = _make_bar(open=10000.0, close=10200.0, low=10100.0)
    errors = validate_bar(bar)
    assert any("low must be <= min" in err for err in errors)


def test_negative_volume_fails():
    bar = _make_bar(volume=-100.0)
    errors = validate_bar(bar)
    assert any("volume must be >= 0" in err for err in errors)


def test_duplicate_date_detected():
    bar1 = _make_bar(date=date(2026, 10, 1))
    bar2 = _make_bar(date=date(2026, 10, 1))

    report = validate_daily_bars([bar1, bar2])
    assert not report.is_valid
    assert any("duplicate date" in err for err in report.errors)


def test_different_tickers_same_date_valid():
    bar1 = _make_bar(ticker="BBCA", date=date(2026, 10, 1))
    bar2 = _make_bar(ticker="BBRI", date=date(2026, 10, 1))

    report = validate_daily_bars([bar1, bar2])
    assert report.is_valid
    assert report.error_count == 0


def test_raise_on_error_behaviour():
    bad_bar = _make_bar(open=-50.0)
    with pytest.raises(DataValidationError, match="Data validation failed"):
        validate_daily_bars([bad_bar], raise_on_error=True)


def test_invalid_close_fails():
    bar = _make_bar(close=-10.0)
    errors = validate_bar(bar)
    assert any("close must be > 0" in err for err in errors)


def test_negative_value_fails():
    bar = _make_bar(value=-500.0)
    errors = validate_bar(bar)
    assert any("value must be >= 0" in err for err in errors)


def test_empty_ticker_fails():
    bar = _make_bar(ticker="")
    errors = validate_bar(bar)
    assert any("ticker must not be empty" in err for err in errors)


def test_null_bar_in_list():
    report = validate_daily_bars([None])
    assert not report.is_valid
    assert any("null bar encountered" in err for err in report.errors)


def test_nan_and_inf_values_fail():
    nan_open_bar = _make_bar(open=float("nan"))
    errors = validate_bar(nan_open_bar)
    assert any("open must be > 0" in err for err in errors)

    nan_close_bar = _make_bar(close=float("nan"))
    errors = validate_bar(nan_close_bar)
    assert any("close must be > 0" in err for err in errors)

    inf_high_bar = _make_bar(high=float("inf"))
    errors = validate_bar(inf_high_bar)
    assert any("high must be > 0" in err for err in errors)

    nan_vol_bar = _make_bar(volume=float("nan"))
    errors = validate_bar(nan_vol_bar)
    assert any("volume must be >= 0" in err for err in errors)


def test_high_less_than_low_fails():
    bar = _make_bar(open=100.0, close=100.0, high=90.0, low=110.0)
    errors = validate_bar(bar)
    assert any("high must be >= low" in err for err in errors)


def test_duplicate_date_with_jk_suffix():
    bar1 = _make_bar(ticker="BBCA", date=date(2026, 10, 1))
    bar2 = _make_bar(ticker="BBCA.JK", date=date(2026, 10, 1))
    report = validate_daily_bars([bar1, bar2])
    assert not report.is_valid
    assert any("duplicate date" in err for err in report.errors)


def test_corporate_actions_validation():
    # Valid corporate action bar
    valid_bar = _make_bar(adj_close=10050.0, dividends=120.0, stock_splits=2.0)
    assert validate_bar(valid_bar) == []

    # Invalid negative / zero adj_close
    bad_adj = _make_bar(adj_close=-10.0)
    assert any("adj_close must be > 0" in e for e in validate_bar(bad_adj))

    # Invalid negative dividends
    bad_div = _make_bar(dividends=-5.0)
    assert any("dividends must be >= 0" in e for e in validate_bar(bad_div))

    # Invalid negative stock_splits
    bad_split = _make_bar(stock_splits=-1.0)
    assert any("stock_splits must be >= 0" in e for e in validate_bar(bad_split))
