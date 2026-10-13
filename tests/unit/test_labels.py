import math
from datetime import date, timedelta

import pytest

from python.common.types import DailyBar, LabelOutcome, LabelRecord
from python.labels.engine import LabelEngine
from python.labels.repository import LabelRepository
from scripts.build_labels import run_build_labels


def _make_bar(
    d: date,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
    ticker: str = "BBCA",
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


# --- Section 50 Critical Unit Tests ---


def test_tp_hit_basic():
    # Section 50: entry = 100, TP = 105, high = 106 -> TP
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    forward_bar = _make_bar(date(2026, 1, 2), 101.0, 106.0, 99.5, 104.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry_bar, [forward_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.binary_target == 1
    assert label.exit_price == pytest.approx(105.0)
    assert label.realized_return == pytest.approx(0.05)
    assert label.holding_days == 1
    assert label.exit_date == date(2026, 1, 2)
    assert label.mfe == pytest.approx(0.06)
    assert label.mae == pytest.approx(-0.005)


def test_sl_hit_basic():
    # Section 50: entry = 100, SL = 98, low = 97 -> SL
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    forward_bar = _make_bar(date(2026, 1, 2), 99.0, 101.0, 97.0, 97.5)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry_bar, [forward_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.SL.value
    assert label.binary_target == 0
    assert label.exit_price == pytest.approx(98.0)
    assert label.realized_return == pytest.approx(-0.02)
    assert label.holding_days == 1
    assert label.exit_date == date(2026, 1, 2)
    assert label.mfe == pytest.approx(0.01)
    assert label.mae == pytest.approx(-0.03)


def test_expiry_reached():
    # Section 50: 10 days, TP not hit, SL not hit -> EXPIRY
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.5, 100.0)
    forward_bars = [
        _make_bar(
            date(2026, 1, 2) + timedelta(days=i),
            open_=100.0,
            high=102.0,
            low=99.0,
            close=101.0 if i < 9 else 102.5,
        )
        for i in range(10)
    ]

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry_bar, forward_bars)

    assert label is not None
    assert label.outcome == LabelOutcome.EXPIRY.value
    assert label.binary_target == 0
    assert label.holding_days == 10
    assert label.exit_date == forward_bars[9].date
    assert label.exit_price == pytest.approx(102.5)
    assert label.realized_return == pytest.approx(0.025)


# --- Section 15 Ambiguity Handling Tests ---


def test_both_touched_conservative():
    # high >= TP and low <= SL on same daily candle, conservative -> SL first
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    ambiguous_bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=96.0, close=101.0)

    engine = LabelEngine(
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        ambiguity_policy="conservative",
    )
    label = engine.compute_label_for_bar(entry_bar, [ambiguous_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.SL.value
    assert label.binary_target == 0
    assert label.exit_price == pytest.approx(98.0)
    assert label.realized_return == pytest.approx(-0.02)
    assert label.holding_days == 1


def test_both_touched_optimistic():
    # high >= TP and low <= SL on same daily candle, optimistic -> TP first
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    ambiguous_bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=96.0, close=101.0)

    engine = LabelEngine(
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        ambiguity_policy="optimistic",
    )
    label = engine.compute_label_for_bar(entry_bar, [ambiguous_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.binary_target == 1
    assert label.exit_price == pytest.approx(105.0)
    assert label.realized_return == pytest.approx(0.05)
    assert label.holding_days == 1


def test_both_touched_ambiguous():
    # high >= TP and low <= SL on same daily candle, ambiguous -> mark AMBIGUOUS
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    ambiguous_bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=96.0, close=101.0)

    engine = LabelEngine(
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        ambiguity_policy="ambiguous",
    )
    label = engine.compute_label_for_bar(entry_bar, [ambiguous_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.AMBIGUOUS.value
    assert label.binary_target == 0
    assert label.exit_price == pytest.approx(101.0)
    assert label.realized_return == pytest.approx(0.01)
    assert label.holding_days == 1


# --- Gap Up / Gap Down Edge Cases ---


def test_gap_up_above_tp():
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    gap_bar = _make_bar(date(2026, 1, 2), open_=108.0, high=110.0, low=107.0, close=109.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02)
    label = engine.compute_label_for_bar(entry_bar, [gap_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.binary_target == 1
    assert label.exit_price == pytest.approx(108.0)
    assert label.realized_return == pytest.approx(0.08)
    assert label.mfe == pytest.approx(0.10)
    assert label.mae == pytest.approx(0.07)


def test_gap_down_below_sl():
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    gap_bar = _make_bar(date(2026, 1, 2), open_=95.0, high=96.0, low=94.0, close=95.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02)
    label = engine.compute_label_for_bar(entry_bar, [gap_bar])

    assert label is not None
    assert label.outcome == LabelOutcome.SL.value
    assert label.binary_target == 0
    assert label.exit_price == pytest.approx(95.0)
    assert label.realized_return == pytest.approx(-0.05)
    assert label.mfe == pytest.approx(-0.04)
    assert label.mae == pytest.approx(-0.06)


def test_gap_up_with_wide_range_both_touched():
    # Opened at 106 (>= TP 105), intraday dropped to 95 (<= SL 98)
    # Trade exited on open before the intraday plunge
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    bar = _make_bar(date(2026, 1, 2), open_=106.0, high=108.0, low=95.0, close=96.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, ambiguity_policy="conservative")
    label = engine.compute_label_for_bar(entry_bar, [bar])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.exit_price == pytest.approx(106.0)
    assert label.binary_target == 1


def test_gap_down_with_wide_range_both_touched():
    # Opened at 96 (<= SL 98), intraday rallied to 108 (>= TP 105)
    # Trade exited on open before the intraday rally
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    bar = _make_bar(date(2026, 1, 2), open_=96.0, high=108.0, low=95.0, close=107.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, ambiguity_policy="optimistic")
    label = engine.compute_label_for_bar(entry_bar, [bar])

    assert label is not None
    assert label.outcome == LabelOutcome.SL.value
    assert label.exit_price == pytest.approx(96.0)
    assert label.binary_target == 0


# --- Section 25 MFE and MAE Calculations ---


def test_section_25_mfe_and_mae():
    # Section 25 example: entry = 8,500, MFE = +4.5%, MAE = -1.6%
    entry_bar = _make_bar(date(2026, 1, 1), 8500.0, 8550.0, 8450.0, 8500.0)
    forward_bars = [
        _make_bar(date(2026, 1, 2), 8500.0, 8500.0 * 1.005, 8500.0 * 0.998, 8500.0 * 1.001),
        _make_bar(date(2026, 1, 3), 8500.0, 8500.0 * 1.017, 8500.0 * 0.992, 8500.0 * 1.010),
        # Day 4 low is -1.6%
        _make_bar(date(2026, 1, 4), 8500.0, 8500.0 * 1.039, 8500.0 * 0.984, 8500.0 * 1.030),
        # Day 5 high is +4.5%
        _make_bar(date(2026, 1, 5), 8500.0, 8500.0 * 1.045, 8500.0 * 1.020, 8500.0 * 1.040),
        _make_bar(date(2026, 1, 6), 8500.0, 8500.0 * 1.025, 8500.0 * 1.015, 8500.0 * 1.020),
    ]

    # With high barriers so it doesn't trigger TP (+10%) or SL (-5%)
    engine = LabelEngine(tp_pct=0.10, sl_pct=0.05, max_holding_days=5)
    label = engine.compute_label_for_bar(entry_bar, forward_bars)

    assert label is not None
    assert label.outcome == LabelOutcome.EXPIRY.value
    assert label.mfe == pytest.approx(0.045)
    assert label.mae == pytest.approx(-0.016)
    assert label.holding_days == 5


# --- Multi-day Exit and Incomplete Edge Cases ---


def test_tp_hit_on_day_3():
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    bars = [
        _make_bar(date(2026, 1, 2), 100.0, 102.0, 99.5, 101.0),
        _make_bar(date(2026, 1, 3), 101.0, 103.0, 100.0, 102.5),
        _make_bar(date(2026, 1, 4), 103.0, 106.0, 101.0, 104.0),  # Hits TP 105
        _make_bar(date(2026, 1, 5), 104.0, 107.0, 90.0, 92.0),  # After exit
    ]

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry_bar, bars)

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.holding_days == 3
    assert label.exit_date == date(2026, 1, 4)
    # Path was only bars 1..3, so day 5 low=90 is NOT included in MAE
    assert label.mae == pytest.approx(-0.005)


def test_immature_bars_handling():
    entry_bar = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    # Only 3 bars available, neither hits TP (105) nor SL (98)
    short_bars = [
        _make_bar(date(2026, 1, 2), 100.0, 101.0, 99.5, 100.5),
        _make_bar(date(2026, 1, 3), 100.5, 102.0, 100.0, 101.0),
        _make_bar(date(2026, 1, 4), 101.0, 101.5, 100.5, 101.0),
    ]

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    # Default: skip immature signals
    assert engine.compute_label_for_bar(entry_bar, short_bars, include_incomplete=False) is None

    # Option to include incomplete
    partial = engine.compute_label_for_bar(entry_bar, short_bars, include_incomplete=True)
    assert partial is not None
    assert partial.outcome == LabelOutcome.EXPIRY.value
    assert partial.holding_days == 3


def test_compute_labels_sequence():
    bars = [
        _make_bar(date(2026, 1, 1) + timedelta(days=i), 100.0 + i, 102.0 + i, 99.0 + i, 101.0 + i)
        for i in range(25)
    ]
    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    labels = engine.compute_labels(bars)

    assert len(labels) > 0
    for rec in labels:
        assert isinstance(rec, LabelRecord)
        assert rec.ticker == "BBCA"


# --- LabelEngine Parameter Validation ---


def test_engine_validation():
    # Percentage conversion if >= 1
    eng1 = LabelEngine(tp_pct=5.0, sl_pct=2.0)
    assert eng1.tp_pct == pytest.approx(0.05)
    assert eng1.sl_pct == pytest.approx(0.02)

    with pytest.raises(ValueError):
        LabelEngine(tp_pct=0)
    with pytest.raises(ValueError):
        LabelEngine(sl_pct=0)
    with pytest.raises(ValueError):
        LabelEngine(max_holding_days=0)
    with pytest.raises(ValueError):
        LabelEngine(ambiguity_policy="invalid_policy")


# --- Repository CRUD & Idempotency ---


def test_label_repository_crud():
    repo = LabelRepository("sqlite:///:memory:")

    rec1 = LabelRecord(
        ticker="BBCA.JK",
        date=date(2026, 1, 1),
        label_version="v1.0.0",
        entry_price=10000.0,
        tp_price=10500.0,
        sl_price=9800.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        outcome=LabelOutcome.TP.value,
        binary_target=1,
        mfe=0.06,
        mae=-0.01,
        holding_days=2,
        realized_return=0.05,
        exit_date=date(2026, 1, 3),
        exit_price=10500.0,
        ambiguity_policy="conservative",
    )

    rec2 = LabelRecord(
        ticker="BBRI",
        date=date(2026, 1, 2),
        label_version="v1.0.0",
        entry_price=5000.0,
        tp_price=5250.0,
        sl_price=4900.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        outcome=LabelOutcome.SL.value,
        binary_target=0,
        mfe=0.01,
        mae=-0.025,
        holding_days=1,
        realized_return=-0.02,
        exit_date=date(2026, 1, 3),
        exit_price=4900.0,
        ambiguity_policy="conservative",
    )

    saved = repo.save_labels([rec1, rec2])
    assert saved == 2
    assert repo.count_labels() == 2

    # Query BBCA with .JK suffix query
    bbca_rows = repo.get_labels("bbca.jk")
    assert len(bbca_rows) == 1
    assert bbca_rows[0].ticker == "BBCA"
    assert bbca_rows[0].outcome == "TP"

    # Universe and latest date
    universe = repo.get_universe()
    assert universe == ["BBCA", "BBRI"]
    latest_d = repo.get_latest_date("BBCA")
    assert latest_d == date(2026, 1, 1)

    # Idempotent upsert: update rec1 outcome to SL
    rec1_updated = rec1.model_copy(update={"outcome": "SL", "binary_target": 0})
    saved2 = repo.save_labels([rec1_updated])
    assert saved2 == 1
    assert repo.count_labels() == 2  # No duplicate row inserted!

    updated_rows = repo.get_labels("BBCA")
    assert len(updated_rows) == 1
    assert updated_rows[0].outcome == "SL"
    assert updated_rows[0].binary_target == 0

    # Delete
    deleted = repo.delete_labels("BBCA")
    assert deleted == 1
    assert repo.count_labels() == 1


def test_label_repository_disk_and_queries(tmp_path):
    db_file = tmp_path / "labels_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    repo = LabelRepository(db_url)

    rec1 = LabelRecord(
        ticker="BBCA",
        date=date(2026, 1, 1),
        label_version="v1.0.0",
        entry_price=100.0,
        tp_price=105.0,
        sl_price=98.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        outcome=LabelOutcome.TP.value,
        binary_target=1,
        mfe=0.06,
        mae=-0.01,
        holding_days=2,
        realized_return=0.05,
        exit_date=date(2026, 1, 3),
        exit_price=105.0,
        ambiguity_policy="conservative",
    )
    rec2 = LabelRecord(
        ticker="BBCA",
        date=date(2026, 1, 5),
        label_version="v1.0.0",
        entry_price=102.0,
        tp_price=107.1,
        sl_price=99.96,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        outcome=LabelOutcome.EXPIRY.value,
        binary_target=0,
        mfe=0.02,
        mae=-0.01,
        holding_days=10,
        realized_return=0.01,
        exit_date=date(2026, 1, 15),
        exit_price=103.0,
        ambiguity_policy="conservative",
    )
    repo.save_labels([rec1, rec2])

    # Date filter queries
    filtered = repo.get_labels(
        "BBCA",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 6),
        label_version="v1.0.0",
    )
    assert len(filtered) == 1
    assert filtered[0].date == date(2026, 1, 5)

    # get_all_labels
    all_recs = repo.get_all_labels(label_version="v1.0.0")
    assert len(all_recs) == 2

    # count_labels with version
    assert repo.count_labels(label_version="v1.0.0") == 2
    assert repo.count_labels(label_version="v2.0.0") == 0

    # delete with version
    del_count = repo.delete_labels(label_version="v1.0.0")
    assert del_count == 2
    assert repo.count_labels() == 0


# --- CLI Smoke Tests ---


def test_cli_build_labels_smoke(tmp_path):
    labels_dict = run_build_labels(
        tickers=["BBCA", "BBRI"],
        provider_name="mock",
        save_db=False,
        out_format="json",
        max_holding_days=5,
    )
    assert "BBCA" in labels_dict
    assert "BBRI" in labels_dict
    assert len(labels_dict["BBCA"]) > 0

    # Test table and csv formats
    run_build_labels(
        tickers=["BBCA"],
        provider_name="mock",
        save_db=False,
        out_format="table",
        max_holding_days=5,
        limit=5,
    )
    run_build_labels(
        tickers=["BBCA"],
        provider_name="mock",
        save_db=False,
        out_format="csv",
        max_holding_days=5,
    )

    # Test save-db with temp db
    db_file = tmp_path / "cli_labels.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    run_build_labels(
        tickers=["BBCA"],
        provider_name="mock",
        save_db=True,
        db_url=db_url,
        out_format="table",
        max_holding_days=5,
    )
    repo = LabelRepository(db_url)
    assert repo.count_labels() > 0


def test_mixed_tickers_no_cross_contamination():
    # Verify bars from different tickers are isolated and never cross-contaminate
    b_bbca_entry = _make_bar(date(2026, 1, 1), 10000.0, 10100.0, 9900.0, 10000.0, ticker="BBCA")
    b_bbri_forward = _make_bar(date(2026, 1, 2), 5000.0, 5000.0, 5000.0, 5000.0, ticker="BBRI")
    b_bbca_forward = _make_bar(date(2026, 1, 2), 10100.0, 10600.0, 10050.0, 10550.0, ticker="BBCA")

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    # Pass mixed bars
    labels = engine.compute_labels([b_bbca_entry, b_bbri_forward, b_bbca_forward])

    # BBCA should hit TP based on BBCA forward bar, NOT be stopped out by BBRI
    assert len(labels) == 1
    rec = labels[0]
    assert rec.ticker == "BBCA"
    assert rec.outcome == LabelOutcome.TP.value
    assert rec.binary_target == 1
    assert rec.exit_price == pytest.approx(10500.0)


def test_forward_bars_deduplication():
    # If duplicate bars on the same date exist, holding days shouldn't count duplicates twice
    entry = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    dup1 = _make_bar(date(2026, 1, 2), 100.0, 102.0, 99.5, 101.0)
    dup2 = _make_bar(date(2026, 1, 2), 100.0, 102.0, 99.5, 101.0)
    fwd2 = _make_bar(date(2026, 1, 3), 101.0, 106.0, 100.0, 105.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry, [dup1, dup2, fwd2])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.holding_days == 2  # Only 2 distinct dates: Jan 2 and Jan 3


def test_corrupt_forward_bar_skipped():
    # Forward bar with NaN high/low should be skipped and not poison metrics
    entry = _make_bar(date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0)
    corrupt = _make_bar(date(2026, 1, 2), 100.0, float("nan"), 99.0, 100.0)
    valid_tp = _make_bar(date(2026, 1, 3), 101.0, 106.0, 100.0, 105.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label = engine.compute_label_for_bar(entry, [corrupt, valid_tp])

    assert label is not None
    assert label.outcome == LabelOutcome.TP.value
    assert label.mfe == pytest.approx(0.06)
    assert not math.isnan(label.mfe)


def test_build_labels_empty_db_fallback_normalized(tmp_path):
    # Calling run_build_labels on empty DB with .JK suffix ticker falls back cleanly to mock
    db_file = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    labels = run_build_labels(
        tickers=["BBCA.JK"],
        provider_name="sqlite",
        db_url=db_url,
        max_holding_days=5,
    )
    assert "BBCA" in labels
    assert len(labels["BBCA"]) > 0


def test_build_labels_end_date_does_not_starve_forward_window():
    # Passing end_date filters labels at record date without starving forward horizon
    res_full = run_build_labels(provider_name="mock", max_holding_days=10)
    dates_full = [r.date for r in res_full["BBCA"]]
    target_end = dates_full[15]

    res_filtered = run_build_labels(
        provider_name="mock",
        max_holding_days=10,
        end_date=target_end,
    )
    dates_filtered = [r.date for r in res_filtered["BBCA"]]
    assert len(dates_filtered) > 0
    assert max(dates_filtered) == target_end


def test_corporate_action_unadjusted_stock_split():
    # Documents Section 37 behavior: unadjusted 1:5 stock split triggers false SL
    entry_bar = _make_bar(date(2026, 1, 1), 10000.0, 10100.0, 9900.0, 10000.0)
    split_bar_unadjusted = _make_bar(date(2026, 1, 2), 2000.0, 2050.0, 1980.0, 2000.0)

    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    label_unadj = engine.compute_label_for_bar(entry_bar, [split_bar_unadjusted])
    assert label_unadj is not None
    assert label_unadj.outcome == LabelOutcome.SL.value
    # False stop loss caused by lack of adjustment
    assert label_unadj.realized_return == pytest.approx(-0.80)

    # In contrast, split-adjusted data retains true price relative movement (+2.5%)
    split_bar_adjusted = _make_bar(date(2026, 1, 2), 10000.0, 10250.0, 9950.0, 10100.0)
    label_adj = engine.compute_label_for_bar(
        entry_bar, [split_bar_adjusted], include_incomplete=True
    )
    assert label_adj is not None
    assert label_adj.outcome != LabelOutcome.SL.value


def test_label_repository_ticker_queries():
    repo = LabelRepository("sqlite:///:memory:")
    rec_bbca = LabelRecord(
        ticker="BBCA",
        date=date(2026, 1, 1),
        entry_price=100.0,
        tp_price=105.0,
        sl_price=98.0,
        tp_pct=0.05,
        sl_pct=0.02,
        outcome="TP",
        binary_target=1,
    )
    rec_bbri = LabelRecord(
        ticker="BBRI",
        date=date(2026, 1, 1),
        entry_price=50.0,
        tp_price=52.5,
        sl_price=49.0,
        tp_pct=0.05,
        sl_pct=0.02,
        outcome="SL",
        binary_target=0,
    )
    repo.save_labels([rec_bbca, rec_bbri])

    # Count by ticker
    assert repo.count_labels(ticker="BBCA") == 1
    assert repo.count_labels(ticker="bbca.jk") == 1
    assert repo.count_labels(ticker="BBRI") == 1
    assert repo.count_labels(ticker="BMRI") == 0

    # Get all labels by tickers filter
    bbca_all = repo.get_all_labels(tickers=["BBCA.JK"])
    assert len(bbca_all) == 1
    assert bbca_all[0].ticker == "BBCA"
