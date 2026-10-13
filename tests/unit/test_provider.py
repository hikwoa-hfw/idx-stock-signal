from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from python.data.provider import (
    CSVMarketDataProvider,
    MockMarketDataProvider,
    YFinanceMarketDataProvider,
    get_market_data_provider,
    load_sector_map,
    load_universe,
    normalize_yfinance_dataframe,
)


def test_mock_provider_defaults():
    provider = MockMarketDataProvider(days=30)
    universe = provider.get_universe()
    assert "BBCA" in universe
    assert len(universe) == 5

    bars = provider.get_daily_bars("BBCA")
    assert len(bars) > 0
    assert all(b.ticker == "BBCA" for b in bars)
    assert all(b.open > 0 and b.high >= b.low for b in bars)


def test_mock_provider_date_filters():
    provider = MockMarketDataProvider(
        days=30,
        base_date=date(2026, 10, 10),
    )
    start = date(2026, 10, 1)
    end = date(2026, 10, 8)
    bars = provider.get_daily_bars("BBCA", start_date=start, end_date=end)

    assert len(bars) > 0
    for b in bars:
        assert start <= b.date <= end


def test_mock_provider_ticker_normalization():
    provider = MockMarketDataProvider(days=10)
    bars_plain = provider.get_daily_bars("BBRI")
    bars_jk = provider.get_daily_bars("BBRI.JK")

    assert len(bars_plain) > 0
    assert len(bars_plain) == len(bars_jk)


def test_mock_provider_sector_data():
    provider = MockMarketDataProvider()
    sectors = provider.get_sector_data()
    assert sectors.get("BBCA") == "Financials"
    assert sectors.get("TLKM") == "Infrastructure"
    assert sectors.get("ASII") == "Industrials"


def test_csv_provider_reads_raw_directory(tmp_path: Path):
    csv_file = tmp_path / "TEST.csv"
    csv_file.write_text(
        "Date,Open,High,Low,Close,Volume,Value\n"
        "2026-10-01,1000,1050,990,1020,100000,102000000\n"
        "2026-10-02,1020,1060,1010,1050,150000,157500000\n",
        encoding="utf-8",
    )

    provider = CSVMarketDataProvider(data_dir=tmp_path)
    universe = provider.get_universe()
    assert "TEST" in universe

    bars = provider.get_daily_bars("TEST")
    assert len(bars) == 2
    assert bars[0].date == date(2026, 10, 1)
    assert bars[0].open == 1000.0
    assert bars[1].close == 1050.0

    filtered = provider.get_daily_bars("TEST", start_date=date(2026, 10, 2))
    assert len(filtered) == 1
    assert filtered[0].date == date(2026, 10, 2)


def test_csv_provider_empty_for_missing_ticker(tmp_path: Path):
    provider = CSVMarketDataProvider(data_dir=tmp_path)
    bars = provider.get_daily_bars("NONEXISTENT")
    assert bars == []


def test_get_market_data_provider_factory():
    mock_p = get_market_data_provider("mock")
    assert isinstance(mock_p, MockMarketDataProvider)

    csv_p = get_market_data_provider("local_csv")
    assert isinstance(csv_p, CSVMarketDataProvider)

    with pytest.raises(ValueError, match="Unsupported market data provider"):
        get_market_data_provider("invalid_provider_name")


def test_csv_provider_utf8_bom_and_commas(tmp_path: Path):
    csv_file = tmp_path / "BBCA.JK.csv"
    csv_content = (
        "\ufeffDate,Open,High,Low,Close,Volume,Value\n"
        '2026-10-01,"10,000.0","10,200.0","9,900.0","10,100.0","1,500,000","15,150,000,000"\n'
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    provider = CSVMarketDataProvider(data_dir=tmp_path)
    universe = provider.get_universe()
    assert "BBCA" in universe

    # Test querying with plain, .JK, lowercase, and lowercase.jk
    bars_plain = provider.get_daily_bars("BBCA")
    assert len(bars_plain) == 1
    assert bars_plain[0].open == 10000.0
    assert bars_plain[0].volume == 1500000.0

    bars_lower = provider.get_daily_bars("bbca")
    assert len(bars_lower) == 1

    bars_lower_jk = provider.get_daily_bars("bbca.jk")
    assert len(bars_lower_jk) == 1


def test_mock_provider_lowercase_query():
    provider = MockMarketDataProvider(days=10)
    bars_lower = provider.get_daily_bars("bbca")
    bars_lower_jk = provider.get_daily_bars("bbca.jk")
    assert len(bars_lower) > 0
    assert len(bars_lower) == len(bars_lower_jk)


def test_yfinance_provider_factory():
    yf_p = get_market_data_provider("yfinance")
    assert isinstance(yf_p, YFinanceMarketDataProvider)
    assert len(yf_p.get_universe()) >= 5


def test_load_universe_and_sector_map_from_seed_file():
    universe = load_universe()
    assert len(universe) >= 200
    assert "BBCA" in universe
    assert "BBRI" in universe

    sectors = load_sector_map()
    assert sectors.get("BBCA") == "Financials"
    assert sectors.get("TLKM") == "Infrastructure"

    # Fallback when non-existent path
    fallback_u = load_universe("non_existent_file.csv")
    assert fallback_u == ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]


def test_normalize_yfinance_single_ticker_flat_columns():
    dates = pd.date_range("2026-10-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            "Open": [10000.0, 10100.0],
            "High": [10200.0, 10300.0],
            "Low": [9900.0, 10050.0],
            "Close": [10100.0, 10250.0],
            "Adj Close": [9800.0, 9950.0],
            "Volume": [1000000.0, 1500000.0],
            "Dividends": [0.0, 150.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=dates,
    )

    res = normalize_yfinance_dataframe(df, ["BBCA"])
    assert "BBCA" in res
    bars = res["BBCA"]
    assert len(bars) == 2
    assert bars[0].date == date(2026, 10, 1)
    assert bars[0].open == 10000.0
    assert bars[0].close == 10100.0
    assert bars[0].adj_close == 9800.0
    assert bars[1].dividends == 150.0
    assert bars[0].provider == "yfinance"
    assert bars[0].provider_symbol == "BBCA.JK"


def test_normalize_yfinance_multi_ticker_group_by_ticker():
    dates = pd.date_range("2026-10-01", periods=2, freq="D")
    tuples = [
        ("BBCA.JK", "Open"),
        ("BBCA.JK", "High"),
        ("BBCA.JK", "Low"),
        ("BBCA.JK", "Close"),
        ("BBCA.JK", "Adj Close"),
        ("BBCA.JK", "Volume"),
        ("BBRI.JK", "Open"),
        ("BBRI.JK", "High"),
        ("BBRI.JK", "Low"),
        ("BBRI.JK", "Close"),
        ("BBRI.JK", "Adj Close"),
        ("BBRI.JK", "Volume"),
    ]
    columns = pd.MultiIndex.from_tuples(tuples)
    data = [
        [10000, 10200, 9900, 10100, 9800, 1000000, 5000, 5100, 4950, 5050, 4900, 2000000],
        [10100, 10300, 10050, 10250, 9950, 1200000, 5050, 5150, 5000, 5100, 4950, 2200000],
    ]
    df = pd.DataFrame(data, index=dates, columns=columns)

    res = normalize_yfinance_dataframe(df, ["BBCA", "BBRI"])
    assert len(res["BBCA"]) == 2
    assert len(res["BBRI"]) == 2
    assert res["BBCA"][0].close == 10100.0
    assert res["BBRI"][0].close == 5050.0


def test_normalize_yfinance_multi_ticker_group_by_column():
    dates = pd.date_range("2026-10-01", periods=2, freq="D")
    tuples = [
        ("Open", "BBCA.JK"),
        ("High", "BBCA.JK"),
        ("Low", "BBCA.JK"),
        ("Close", "BBCA.JK"),
        ("Volume", "BBCA.JK"),
        ("Open", "BMRI.JK"),
        ("High", "BMRI.JK"),
        ("Low", "BMRI.JK"),
        ("Close", "BMRI.JK"),
        ("Volume", "BMRI.JK"),
    ]
    columns = pd.MultiIndex.from_tuples(tuples)
    data = [
        [10000, 10200, 9900, 10100, 1000000, 6800, 6900, 6750, 6850, 1500000],
        [10100, 10300, 10050, 10250, 1200000, 6850, 6950, 6800, 6900, 1600000],
    ]
    df = pd.DataFrame(data, index=dates, columns=columns)

    res = normalize_yfinance_dataframe(df, ["BBCA", "BMRI"])
    assert len(res["BBCA"]) == 2
    assert len(res["BMRI"]) == 2
    assert res["BMRI"][1].close == 6900.0


def test_normalize_yfinance_handles_empty_or_nans():
    res_empty = normalize_yfinance_dataframe(None, ["BBCA"])
    assert res_empty == {"BBCA": []}

    res_df_empty = normalize_yfinance_dataframe(pd.DataFrame(), ["BBCA"])
    assert res_df_empty == {"BBCA": []}

    dates = pd.date_range("2026-10-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            "Open": [10000.0, float("nan")],
            "High": [10200.0, 10300.0],
            "Low": [9900.0, 10000.0],
            "Close": [10100.0, 10200.0],
            "Volume": [1000000.0, 1000000.0],
        },
        index=dates,
    )
    res = normalize_yfinance_dataframe(df, ["BBCA"])
    # Second bar with NaN Open skipped
    assert len(res["BBCA"]) == 1
    assert res["BBCA"][0].date == date(2026, 10, 1)


def test_yfinance_provider_mocked_batch_and_retries():
    provider = YFinanceMarketDataProvider(
        universe=["BBCA", "BBRI"],
        batch_size=25,
        retry_attempts=3,
        retry_backoff_seconds=[0.01, 0.02],
    )

    dates = pd.date_range("2026-10-01", periods=1, freq="D")
    mock_df = pd.DataFrame(
        {
            "Open": [10000.0],
            "High": [10200.0],
            "Low": [9900.0],
            "Close": [10100.0],
            "Volume": [1000000.0],
        },
        index=dates,
    )

    # Mock _fetch_yfinance: fail once with exception, then succeed
    mock_fetch = MagicMock(side_effect=[RuntimeError("Yahoo 503 error"), mock_df])
    provider._fetch_yfinance = mock_fetch

    bars = provider.get_daily_bars("BBCA")
    assert len(bars) == 1
    assert bars[0].close == 10100.0
    assert mock_fetch.call_count == 2


def test_normalize_yfinance_handles_sliced_multiindex_levels_without_keyerror():
    # MultiIndex where BBCA.JK is present in index levels cache but dropped in actual df columns
    dates = pd.date_range("2026-10-01", periods=1, freq="D")
    full_mi = pd.MultiIndex.from_tuples(
        [
            ("BBCA.JK", "Open"),
            ("BBCA.JK", "Close"),
            ("BBRI.JK", "Open"),
            ("BBRI.JK", "Close"),
        ]
    )
    df_full = pd.DataFrame([[10000.0, 10100.0, 5000.0, 5100.0]], index=dates, columns=full_mi)
    # Slicing keeps BBCA in levels, but drops it from columns
    df_sliced = df_full[[("BBRI.JK", "Open"), ("BBRI.JK", "Close")]]

    res = normalize_yfinance_dataframe(df_sliced, ["BBCA", "BBRI"])
    assert res["BBCA"] == []
    # BBRI has Open and Close only (no High/Low), so _extract_bars safely skips or extracts
    assert isinstance(res["BBRI"], list)


def test_normalize_yfinance_tuple_columns():
    dates = pd.date_range("2026-10-01", periods=1, freq="D")
    mi = pd.MultiIndex.from_tuples(
        [
            ("BBCA.JK", "Open"),
            ("BBCA.JK", "High"),
            ("BBCA.JK", "Low"),
            ("BBCA.JK", "Close"),
            ("BBCA.JK", "Volume"),
            ("BBCA.JK", "Adj Close"),
            ("BBCA.JK", "Dividends"),
        ]
    )
    data = [[10000.0, 10200.0, 9900.0, 10100.0, 1000000.0, 9950.0, 50.0]]
    df = pd.DataFrame(data, index=dates, columns=mi)
    res = normalize_yfinance_dataframe(df, ["BBCA"])
    assert len(res["BBCA"]) == 1
    b = res["BBCA"][0]
    assert b.open == 10000.0
    assert b.high == 10200.0
    assert b.low == 9900.0
    assert b.close == 10100.0
    assert b.volume == 1000000.0
    assert b.adj_close == 9950.0
    assert b.dividends == 50.0
