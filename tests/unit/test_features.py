import statistics
from datetime import date, timedelta

import pytest

from python.common.types import DailyBar, FeatureRecord
from python.features.engine import FEATURE_VERSION, FeatureEngine
from python.features.indicators import (
    compute_atr,
    compute_daily_range_pct,
    compute_ema,
    compute_realized_vol,
    compute_relative_distance,
    compute_returns,
    compute_rolling_mean_ratio,
    compute_rsi,
    compute_rsi_change,
)
from python.features.repository import FeatureRepository


# ---------------------------------------------------------
# Mathematical Accuracy Tests: Returns / Momentum
# ---------------------------------------------------------
def test_compute_returns_known_values():
    closes = [100.0, 105.0, 110.25, 121.275]
    ret_1d = compute_returns(closes, 1)
    assert ret_1d[0] is None
    assert ret_1d[1] == pytest.approx(0.05, rel=1e-5)
    assert ret_1d[2] == pytest.approx(0.05, rel=1e-5)
    assert ret_1d[3] == pytest.approx(0.10, rel=1e-5)

    ret_2d = compute_returns(closes, 2)
    assert ret_2d[0] is None
    assert ret_2d[1] is None
    assert ret_2d[2] == pytest.approx(0.1025, rel=1e-5)
    assert ret_2d[3] == pytest.approx(0.155, rel=1e-4)


def test_compute_returns_edge_cases():
    with pytest.raises(ValueError):
        compute_returns([10.0, 20.0], 0)

    # Zero previous close
    ret = compute_returns([0.0, 10.0], 1)
    assert ret[0] is None
    assert ret[1] is None


# ---------------------------------------------------------
# Mathematical Accuracy Tests: EMA
# ---------------------------------------------------------
def test_compute_ema_known_math():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    span = 3
    # alpha = 2 / (3 + 1) = 0.5
    # SMA seed at index 2: (10 + 20 + 30) / 3 = 20.0
    # idx 3: 0.5 * 40.0 + 0.5 * 20.0 = 30.0
    # idx 4: 0.5 * 50.0 + 0.5 * 30.0 = 40.0
    ema = compute_ema(values, span=span)
    assert ema[0] is None
    assert ema[1] is None
    assert ema[2] == pytest.approx(20.0)
    assert ema[3] == pytest.approx(30.0)
    assert ema[4] == pytest.approx(40.0)


def test_compute_ema_constant_series():
    values = [5000.0] * 30
    ema20 = compute_ema(values, span=20)
    assert ema20[18] is None
    for val in ema20[19:]:
        assert val == pytest.approx(5000.0)


def test_compute_ema_insufficient_data():
    values = [10.0, 20.0]
    ema5 = compute_ema(values, span=5)
    assert ema5 == [None, None]

    with pytest.raises(ValueError):
        compute_ema(values, 0)


def test_compute_relative_distance():
    assert compute_relative_distance(110.0, 100.0) == pytest.approx(0.10)
    assert compute_relative_distance(90.0, 100.0) == pytest.approx(-0.10)
    assert compute_relative_distance(None, 100.0) is None
    assert compute_relative_distance(100.0, None) is None
    assert compute_relative_distance(100.0, 0.0) is None


# ---------------------------------------------------------
# Mathematical Accuracy Tests: RSI
# ---------------------------------------------------------
def test_compute_rsi_all_gains():
    # Strictly ascending prices -> RS = infinity -> RSI = 100.0
    closes = [float(100 + i * 5) for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    assert rsi[13] is None
    assert rsi[14] == pytest.approx(100.0)
    assert rsi[19] == pytest.approx(100.0)


def test_compute_rsi_all_losses():
    # Strictly descending prices -> RS = 0 -> RSI = 0.0
    closes = [float(200 - i * 5) for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    assert rsi[13] is None
    assert rsi[14] == pytest.approx(0.0)
    assert rsi[19] == pytest.approx(0.0)


def test_compute_rsi_alternating():
    # Equal gains and losses -> RS = 1.0 -> RSI = 50.0
    closes = [100.0, 110.0] * 10
    rsi = compute_rsi(closes, period=14)
    assert rsi[14] == pytest.approx(50.0, abs=1e-2)


def test_compute_rsi_change_5d():
    rsi_vals: list[float | None] = [None] * 14 + [50.0, 52.0, 54.0, 56.0, 58.0, 65.0]
    chg = compute_rsi_change(rsi_vals, period=5)
    assert chg[18] is None
    # idx 19 (65.0) - idx 14 (50.0) = 15.0
    assert chg[19] == pytest.approx(15.0)


# ---------------------------------------------------------
# Mathematical Accuracy Tests: ATR & Volatility
# ---------------------------------------------------------
def test_compute_atr_constant_range():
    # High=110, Low=90, Close=100 every day -> TR is always 20
    highs = [110.0] * 20
    lows = [90.0] * 20
    closes = [100.0] * 20
    atr = compute_atr(highs, lows, closes, period=14)
    assert atr[12] is None
    assert atr[13] == pytest.approx(20.0)
    assert atr[19] == pytest.approx(20.0)


def test_compute_atr_gap_day():
    # Day 0: C=100, H=105, L=95
    # Day 1: Gap up: H=130, L=120, C=125 -> TR = max(10, |130-100|, |120-100|) = 30
    highs = [105.0, 130.0]
    lows = [95.0, 120.0]
    closes = [100.0, 125.0]
    # Insufficient for period=14 but testing length checks
    atr = compute_atr(highs, lows, closes, period=14)
    assert atr == [None, None]


def test_compute_realized_vol():
    returns: list[float | None] = [0.01, 0.02, -0.01, 0.03, -0.02, 0.015]
    vol5 = compute_realized_vol(returns, period=5)
    assert vol5[0] is None
    assert vol5[3] is None
    # Index 4 uses slice returns[0:5]
    expected_stdev = statistics.stdev([0.01, 0.02, -0.01, 0.03, -0.02])
    assert vol5[4] == pytest.approx(expected_stdev)


def test_daily_range_pct():
    highs = [110.0, 105.0]
    lows = [90.0, 95.0]
    closes = [100.0, 100.0]
    ranges = compute_daily_range_pct(highs, lows, closes)
    assert ranges[0] == pytest.approx(0.20)
    assert ranges[1] == pytest.approx(0.10)


# ---------------------------------------------------------
# Mathematical Accuracy Tests: Volume & Value Ratios
# ---------------------------------------------------------
def test_compute_volume_ratios():
    vols = [100.0, 100.0, 100.0, 100.0, 200.0]
    ratio5 = compute_rolling_mean_ratio(vols, period=5)
    assert ratio5[0] is None
    assert ratio5[3] is None
    # Mean of 5 is (100*4 + 200) / 5 = 120. Ratio is 200 / 120 = 1.66667
    assert ratio5[4] == pytest.approx(200.0 / 120.0)


# ---------------------------------------------------------
# FeatureEngine Integration Tests
# ---------------------------------------------------------
def test_feature_engine_synthetic_bars():
    base = date(2026, 8, 1)
    bars: list[DailyBar] = []
    price = 10000.0
    for i in range(60):
        d = base + timedelta(days=i)
        drift = ((i % 5) - 2) * 50.0
        c = price + drift
        h = c + 100.0
        low_p = c - 100.0
        bars.append(
            DailyBar(
                ticker="BBCA",
                date=d,
                open=price,
                high=h,
                low=low_p,
                close=c,
                volume=1_000_000.0,
                value=c * 1_000_000.0,
            )
        )
        price = c

    engine = FeatureEngine()
    records = engine.compute_stock_features(bars)

    assert len(records) == 60
    assert records[0].ticker == "BBCA"
    assert records[0].feature_version == FEATURE_VERSION

    # Check momentum
    assert records[0].return_1d is None
    assert records[1].return_1d is not None
    assert records[20].return_20d is not None

    # Check trend
    assert records[19].ema20 is not None
    assert records[19].close_vs_ema20 is not None
    assert records[49].ema50 is not None

    # Check RSI & Volatility
    assert records[14].rsi14 is not None
    assert records[13].atr14 is not None
    assert records[13].atr_pct is not None
    assert records[5].realized_vol_5d is not None
    assert records[20].realized_vol_20d is not None

    # Check volume ratios
    assert records[4].volume_ratio_5d is not None
    assert records[19].volume_ratio_20d is not None


def test_feature_engine_universe_market_regime():
    base = date(2026, 8, 1)
    universe_bars: dict[str, list[DailyBar]] = {}

    for tk in ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]:
        tk_bars: list[DailyBar] = []
        p = 5000.0
        for i in range(40):
            d = base + timedelta(days=i)
            c = p + (i % 3) * 50.0
            tk_bars.append(
                DailyBar(
                    ticker=tk,
                    date=d,
                    open=p,
                    high=c + 50.0,
                    low=c - 50.0,
                    close=c,
                    volume=500_000.0,
                )
            )
            p = c
        universe_bars[tk] = tk_bars

    engine = FeatureEngine()
    result = engine.compute_universe_features(universe_bars)

    assert "BBCA" in result
    bbca_recs = result["BBCA"]
    last_rec = bbca_recs[-1]

    # Market regime populated
    assert last_rec.ihsg_return_5d is not None
    assert last_rec.ihsg_return_20d is not None
    assert last_rec.ihsg_vs_ema20 is not None
    assert last_rec.market_breadth is not None
    assert 0.0 <= last_rec.market_breadth <= 1.0

    # Relative strength populated
    assert last_rec.rel_strength_ihsg_20d is not None
    assert last_rec.rel_strength_sector_20d is not None


# ---------------------------------------------------------
# FeatureRepository Tests
# ---------------------------------------------------------
def test_feature_repository_crud():
    repo = FeatureRepository(database_url=":memory:")
    try:
        rec1 = FeatureRecord(
            ticker="BBCA",
            date=date(2026, 10, 1),
            feature_version="v1.0.0",
            return_1d=0.015,
            ema20=10200.0,
            rsi14=58.5,
            market_breadth=0.8,
        )
        rec2 = FeatureRecord(
            ticker="BBCA",
            date=date(2026, 10, 2),
            feature_version="v1.0.0",
            return_1d=-0.005,
            ema20=10220.0,
            rsi14=56.0,
            market_breadth=0.6,
        )

        saved = repo.save_features([rec1, rec2])
        assert saved == 2
        assert repo.count_features("BBCA") == 2

        # Query
        fetched = repo.get_features("BBCA")
        assert len(fetched) == 2
        assert fetched[0].ticker == "BBCA"
        assert fetched[0].return_1d == pytest.approx(0.015)
        assert fetched[0].market_breadth == pytest.approx(0.8)

        # Upsert test
        rec1_updated = FeatureRecord(
            ticker="BBCA",
            date=date(2026, 10, 1),
            feature_version="v1.0.0",
            return_1d=0.020,  # updated
            ema20=10200.0,
            rsi14=60.0,
        )
        repo.save_features([rec1_updated])
        assert repo.count_features("BBCA") == 2
        refetched = repo.get_features(
            "BBCA", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)
        )
        assert len(refetched) == 1
        assert refetched[0].return_1d == pytest.approx(0.020)

        # Delete
        deleted = repo.delete_features("BBCA")
        assert deleted == 2
        assert repo.count_features("BBCA") == 0
    finally:
        repo.close()


def test_feature_repository_universe_and_latest_date():
    repo = FeatureRepository(database_url=":memory:")
    try:
        rec1 = FeatureRecord(
            ticker="BBCA.JK",
            date=date(2026, 10, 1),
            feature_version="v1.0.0",
        )
        rec2 = FeatureRecord(
            ticker="TLKM",
            date=date(2026, 10, 5),
            feature_version="v1.0.0",
        )
        repo.save_features([rec1, rec2])

        universe = repo.get_universe()
        assert universe == ["BBCA", "TLKM"]

        latest_bbca = repo.get_latest_date("BBCA")
        assert latest_bbca == date(2026, 10, 1)

        latest_tlkm = repo.get_latest_date("TLKM.JK")
        assert latest_tlkm == date(2026, 10, 5)

        assert repo.get_latest_date("NONEXIST") is None
    finally:
        repo.close()


def test_feature_engine_explicit_benchmark_ihsg():
    base = date(2026, 8, 1)
    universe_bars: dict[str, list[DailyBar]] = {}

    for tk, base_p in [("BBCA", 10000.0), ("BMRI", 7000.0), ("IHSG", 7500.0)]:
        bars: list[DailyBar] = []
        p = base_p
        for i in range(35):
            d = base + timedelta(days=i)
            c = p + (10.0 if tk == "IHSG" else 20.0)
            bars.append(
                DailyBar(
                    ticker=tk,
                    date=d,
                    open=p,
                    high=c + 10.0,
                    low=c - 10.0,
                    close=c,
                    volume=1_000_000.0,
                )
            )
            p = c
        universe_bars[tk] = bars

    engine = FeatureEngine()
    result = engine.compute_universe_features(universe_bars)

    assert "BBCA" in result
    bbca_last = result["BBCA"][-1]

    # IHSG benchmark return computed
    assert bbca_last.ihsg_return_5d is not None
    assert bbca_last.ihsg_return_20d is not None

    # Market breadth excludes IHSG from stock denominator
    assert bbca_last.market_breadth is not None
    assert 0.0 <= bbca_last.market_breadth <= 1.0

    # Relative strength vs IHSG is difference of 20d returns
    assert bbca_last.rel_strength_ihsg_20d is not None
    assert bbca_last.rel_strength_ihsg_20d == pytest.approx(
        bbca_last.return_20d - bbca_last.ihsg_return_20d
    )


def test_feature_engine_deduplication_and_merging():
    base = date(2026, 9, 1)
    # Provide duplicate bars on the same date
    bars = [
        DailyBar(
            ticker="BBCA",
            date=base,
            open=10000.0,
            high=10100.0,
            low=9900.0,
            close=10050.0,
            volume=500_000.0,
        ),
        DailyBar(
            ticker="BBCA",
            date=base,  # duplicate date
            open=10000.0,
            high=10100.0,
            low=9900.0,
            close=10050.0,
            volume=500_000.0,
        ),
        DailyBar(
            ticker="BBCA",
            date=base + timedelta(days=1),
            open=10050.0,
            high=10200.0,
            low=10000.0,
            close=10150.0,
            volume=600_000.0,
        ),
    ]

    engine = FeatureEngine()
    recs = engine.compute_stock_features(bars)
    assert len(recs) == 2
    assert recs[0].date == base
    assert recs[1].date == base + timedelta(days=1)


def test_build_features_single_ticker_preserves_universe_context():
    from scripts.build_features import run_build_features

    # Run for single ticker from mock provider
    features = run_build_features(
        tickers=["BBCA"],
        provider_name="mock",
        save_db=False,
        out_format="table",
    )

    assert "BBCA" in features
    assert len(features) == 1
    bbca_recs = features["BBCA"]
    last_rec = bbca_recs[-1]

    # Market breadth is calculated across full mock universe, not single stock
    assert last_rec.market_breadth is not None
    assert 0.0 <= last_rec.market_breadth <= 1.0
