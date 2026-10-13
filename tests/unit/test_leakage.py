from datetime import date, timedelta

from python.common.types import DailyBar, FeatureRecord
from python.features.engine import FeatureEngine


def _generate_synthetic_bars(
    ticker: str, count: int, base_date: date, base_price: float = 10000.0
) -> list[DailyBar]:
    bars: list[DailyBar] = []
    p = base_price
    for i in range(count):
        d = base_date + timedelta(days=i)
        drift = ((i % 5) - 2) * 50.0
        c = max(100.0, p + drift)
        h = c + 50.0
        low_val = max(50.0, c - 50.0)
        v = 1_000_000.0 + (i % 3) * 100_000.0
        bars.append(
            DailyBar(
                ticker=ticker,
                date=d,
                open=p,
                high=h,
                low=low_val,
                close=c,
                volume=v,
                value=c * v,
            )
        )
        p = c
    return bars


def _records_equal(r1: FeatureRecord, r2: FeatureRecord) -> bool:
    d1 = r1.model_dump()
    d2 = r2.model_dump()
    if d1.keys() != d2.keys():
        return False
    for k in d1:
        v1 = d1[k]
        v2 = d2[k]
        if v1 is None and v2 is None:
            continue
        if isinstance(v1, float) and isinstance(v2, float):
            if abs(v1 - v2) > 1e-12:
                return False
        elif v1 != v2:
            return False
    return True


def test_stock_features_causality_future_data_tampering():
    base_date = date(2026, 7, 1)
    bars = _generate_synthetic_bars("BBCA", 60, base_date)
    cutoff_idx = 35
    cutoff_date = bars[cutoff_idx].date

    engine = FeatureEngine()

    # 1. Baseline: compute strictly on bars up to cutoff
    past_bars = bars[: cutoff_idx + 1]
    baseline_records = engine.compute_stock_features(past_bars)
    baseline_snapshot = baseline_records[-1]
    assert baseline_snapshot.date == cutoff_date

    # 2. Tampered dataset: mutate future bars (> cutoff) with extreme anomalies
    tampered_bars = [b.model_copy() for b in past_bars]
    for b in bars[cutoff_idx + 1 :]:
        tampered_bars.append(
            DailyBar(
                ticker=b.ticker,
                date=b.date,
                open=b.open * 15.0,
                high=b.high * 20.0,
                low=b.low * 10.0,
                close=b.close * 15.0,
                volume=b.volume * 100.0,
                value=b.value * 1500.0 if b.value else None,
            )
        )

    # 3. Compute on full tampered dataset
    tampered_records = engine.compute_stock_features(tampered_bars)
    tampered_snapshot = next(r for r in tampered_records if r.date == cutoff_date)

    # 4. Assert past snapshot is bit-for-bit identical
    assert _records_equal(baseline_snapshot, tampered_snapshot), (
        f"Feature leakage detected! Snapshot at {cutoff_date} changed "
        "when future bars were tampered."
    )

    # Verify all past dates match exactly
    for i in range(cutoff_idx + 1):
        assert _records_equal(baseline_records[i], tampered_records[i]), (
            f"Feature leakage at index {i} (date {baseline_records[i].date})"
        )


def test_stock_features_truncation_invariance():
    base_date = date(2026, 7, 1)
    bars = _generate_synthetic_bars("BBRI", 50, base_date)

    engine = FeatureEngine()
    recs_30 = engine.compute_stock_features(bars[:30])
    recs_50 = engine.compute_stock_features(bars)

    # The first 30 records must be exactly identical
    for i in range(30):
        assert _records_equal(recs_30[i], recs_50[i])


def test_universe_features_causality():
    base_date = date(2026, 7, 1)
    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    universe = {tk: _generate_synthetic_bars(tk, 50, base_date) for tk in tickers}

    cutoff_idx = 30
    cutoff_date = universe["BBCA"][cutoff_idx].date

    engine = FeatureEngine()

    # Baseline up to cutoff
    past_universe = {tk: bars[: cutoff_idx + 1] for tk, bars in universe.items()}
    baseline_result = engine.compute_universe_features(past_universe)
    baseline_bbca_snapshot = baseline_result["BBCA"][-1]

    # Tampered: wildly mutate future bars in other tickers and BBCA
    tampered_universe: dict[str, list[DailyBar]] = {}
    for tk, bars in universe.items():
        t_bars = [b.model_copy() for b in bars[: cutoff_idx + 1]]
        for b in bars[cutoff_idx + 1 :]:
            t_bars.append(
                DailyBar(
                    ticker=tk,
                    date=b.date,
                    open=b.open * 8.0,
                    high=b.high * 10.0,
                    low=b.low * 5.0,
                    close=b.close * 8.0,
                    volume=b.volume * 50.0,
                )
            )
        tampered_universe[tk] = t_bars

    tampered_result = engine.compute_universe_features(tampered_universe)
    tampered_bbca_snapshot = next(r for r in tampered_result["BBCA"] if r.date == cutoff_date)

    # Verify market regime and relative strength at cutoff_date remain identical
    assert _records_equal(baseline_bbca_snapshot, tampered_bbca_snapshot), (
        "Universe market regime or relative strength leaked future data!"
    )


def test_no_target_or_forward_leakage_fields():
    # Verify no feature record field has future/lookahead semantics
    forbidden_tokens = ["future", "next", "forward", "lead", "target", "label", "outcome"]
    for field_name in FeatureRecord.model_fields:
        for token in forbidden_tokens:
            assert token not in field_name.lower(), (
                f"Feature field '{field_name}' suggests future target leakage!"
            )


def test_universe_features_causality_with_explicit_benchmark():
    base_date = date(2026, 7, 1)
    tickers = ["BBCA", "BMRI", "IHSG"]
    universe = {tk: _generate_synthetic_bars(tk, 50, base_date) for tk in tickers}

    cutoff_idx = 30
    cutoff_date = universe["BBCA"][cutoff_idx].date

    engine = FeatureEngine()

    # Baseline up to cutoff
    past_universe = {tk: bars[: cutoff_idx + 1] for tk, bars in universe.items()}
    baseline_result = engine.compute_universe_features(past_universe)
    baseline_bbca_snapshot = baseline_result["BBCA"][-1]

    # Tampered: mutate future bars in IHSG and stocks
    tampered_universe: dict[str, list[DailyBar]] = {}
    for tk, bars in universe.items():
        t_bars = [b.model_copy() for b in bars[: cutoff_idx + 1]]
        for b in bars[cutoff_idx + 1 :]:
            t_bars.append(
                DailyBar(
                    ticker=tk,
                    date=b.date,
                    open=b.open * 20.0,
                    high=b.high * 25.0,
                    low=b.low * 15.0,
                    close=b.close * 20.0,
                    volume=b.volume * 10.0,
                )
            )
        tampered_universe[tk] = t_bars

    tampered_result = engine.compute_universe_features(tampered_universe)
    tampered_bbca_snapshot = next(r for r in tampered_result["BBCA"] if r.date == cutoff_date)

    assert _records_equal(baseline_bbca_snapshot, tampered_bbca_snapshot), (
        "Universe market regime leaked future benchmark data!"
    )
