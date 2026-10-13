from datetime import date, timedelta

import pytest

from python.common.types import (
    DailyBar,
    SignalDailySnapshot,
    SignalOutcomeRecord,
    SignalRecord,
)
from python.data.repository import DailyBarRepository
from python.outcomes.dataset import build_matured_outcomes_dataset
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository


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


def _make_signal(
    signal_id: str = "sig-001",
    ticker: str = "BBCA",
    signal_date: date = date(2026, 1, 1),
    entry_low: float = 99.0,
    entry_high: float = 101.0,
    tp_price: float = 105.0,
    sl_price: float = 95.0,
    max_holding_days: int = 10,
) -> SignalRecord:
    return SignalRecord(
        signal_id=signal_id,
        ticker=ticker,
        signal_date=signal_date,
        signal="BUY",
        entry_low=entry_low,
        entry_high=entry_high,
        tp_price=tp_price,
        sl_price=sl_price,
        max_holding_days=max_holding_days,
        predicted_probability=0.75,
        score=85.0,
        model_version="v1.0.0",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
    )


# -------------------------------------------------------------------------
# Unit Tests: Triple Barrier Logic
# -------------------------------------------------------------------------


def test_tp_hit_before_sl():
    # Day t = Jan 1, Day t+1 = Jan 2
    # Entry at Open = 100.0, TP = 105.0, SL = 95.0
    # Day t+1 High reaches 106.0 -> TP hit
    signal = _make_signal(tp_price=105.0, sl_price=95.0)
    forward_bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=106.0, low=99.0, close=104.0),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, forward_bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.holding_days == 1
    assert outcome.entry_date == date(2026, 1, 2)
    assert outcome.entry_price == 100.0
    assert outcome.exit_date == date(2026, 1, 2)
    assert outcome.exit_price == pytest.approx(105.0)
    assert outcome.realized_return == pytest.approx(0.05)
    assert outcome.exit_reason == "TP"
    assert outcome.mfe == pytest.approx(0.06)
    assert outcome.mae == pytest.approx(-0.01)

    assert len(snapshots) == 1
    assert snapshots[0].holding_day == 1
    assert snapshots[0].close_price == 104.0
    assert snapshots[0].mfe_so_far == pytest.approx(0.06)
    assert snapshots[0].mae_so_far == pytest.approx(-0.01)


def test_sl_hit_before_tp():
    signal = _make_signal(tp_price=105.0, sl_price=95.0)
    forward_bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=94.0, close=94.5),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, forward_bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.holding_days == 1
    assert outcome.entry_date == date(2026, 1, 2)
    assert outcome.entry_price == 100.0
    assert outcome.exit_date == date(2026, 1, 2)
    assert outcome.exit_price == pytest.approx(95.0)
    assert outcome.realized_return == pytest.approx(-0.05)
    assert outcome.exit_reason == "SL"
    assert outcome.mfe == pytest.approx(0.02)
    assert outcome.mae == pytest.approx(-0.06)


def test_max_holding_days_expiry():
    signal = _make_signal(tp_price=105.0, sl_price=95.0, max_holding_days=10)
    forward_bars = [
        _make_bar(
            date(2026, 1, 2) + timedelta(days=i),
            open_=100.0,
            high=102.0,
            low=98.0,
            close=101.0 if i < 9 else 103.0,
        )
        for i in range(10)
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, forward_bars)

    assert outcome is not None
    assert outcome.outcome_status == "EXPIRY"
    assert outcome.holding_days == 10
    assert outcome.entry_date == forward_bars[0].date
    assert outcome.exit_date == forward_bars[-1].date
    assert outcome.exit_price == pytest.approx(103.0)
    assert outcome.realized_return == pytest.approx(0.03)
    assert outcome.exit_reason == "EXPIRY"
    assert len(snapshots) == 10


def test_same_candle_ambiguity_conservative():
    # Both TP and SL touched on same candle
    signal = _make_signal(tp_price=105.0, sl_price=95.0)
    bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=93.0, close=101.0)

    engine = OutcomeEngine(ambiguity_policy="conservative")
    outcome, _ = engine.evaluate_signal(signal, [bar])

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.exit_price == pytest.approx(95.0)
    assert outcome.realized_return == pytest.approx(-0.05)


def test_same_candle_ambiguity_optimistic():
    signal = _make_signal(tp_price=105.0, sl_price=95.0)
    bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=93.0, close=101.0)

    engine = OutcomeEngine(ambiguity_policy="optimistic")
    outcome, _ = engine.evaluate_signal(signal, [bar])

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.exit_price == pytest.approx(105.0)
    assert outcome.realized_return == pytest.approx(0.05)


def test_same_candle_ambiguity_ambiguous():
    signal = _make_signal(tp_price=105.0, sl_price=95.0)
    bar = _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=93.0, close=102.0)

    engine = OutcomeEngine(ambiguity_policy="ambiguous")
    outcome, _ = engine.evaluate_signal(signal, [bar])

    assert outcome is not None
    assert outcome.outcome_status == "AMBIGUOUS"
    assert outcome.exit_price == pytest.approx(102.0)
    assert outcome.realized_return == pytest.approx(0.02)


def test_gap_up_and_down_on_open():
    signal = _make_signal(tp_price=105.0, sl_price=95.0)

    # Gap up open >= TP
    gap_up_bar = _make_bar(date(2026, 1, 2), open_=107.0, high=108.0, low=94.0, close=106.0)
    engine = OutcomeEngine(ambiguity_policy="conservative")
    outcome_up, _ = engine.evaluate_signal(signal, [gap_up_bar])
    assert outcome_up is not None
    assert outcome_up.outcome_status == "TP"
    assert outcome_up.exit_price == 107.0

    # Gap down open <= SL
    gap_down_bar = _make_bar(date(2026, 1, 2), open_=93.0, high=106.0, low=92.0, close=94.0)
    outcome_down, _ = engine.evaluate_signal(signal, [gap_down_bar])
    assert outcome_down is not None
    assert outcome_down.outcome_status == "SL"
    assert outcome_down.exit_price == 93.0


def test_mfe_and_mae_calculation_multi_day():
    signal = _make_signal(tp_price=110.0, sl_price=90.0, max_holding_days=10)
    bars = [
        # Day 1: Open 100, High 104 (+4%), Low 98 (-2%), Close 101
        _make_bar(date(2026, 1, 2), open_=100.0, high=104.0, low=98.0, close=101.0),
        # Day 2: Open 101, High 107 (+7%), Low 97 (-3%), Close 103
        _make_bar(date(2026, 1, 3), open_=101.0, high=107.0, low=97.0, close=103.0),
        # Day 3: Open 103, High 111 (>= 110 TP hit), Low 99, Close 110.5
        _make_bar(date(2026, 1, 4), open_=103.0, high=111.0, low=99.0, close=110.5),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.holding_days == 3
    assert outcome.exit_date == date(2026, 1, 4)
    assert outcome.exit_price == pytest.approx(110.0)
    assert outcome.realized_return == pytest.approx(0.10)
    # Highest high across days 1..3 was 111.0 -> MFE = +11%
    assert outcome.mfe == pytest.approx(0.11)
    # Lowest low across days 1..3 was 97.0 -> MAE = -3%
    assert outcome.mae == pytest.approx(-0.03)

    assert len(snapshots) == 3
    # Check progressive snapshot tracking
    assert snapshots[0].holding_day == 1
    assert snapshots[0].mfe_so_far == pytest.approx(0.04)
    assert snapshots[0].mae_so_far == pytest.approx(-0.02)

    assert snapshots[1].holding_day == 2
    assert snapshots[1].mfe_so_far == pytest.approx(0.07)
    assert snapshots[1].mae_so_far == pytest.approx(-0.03)

    assert snapshots[2].holding_day == 3
    assert snapshots[2].mfe_so_far == pytest.approx(0.11)
    assert snapshots[2].mae_so_far == pytest.approx(-0.03)


def test_open_in_flight_signal():
    signal = _make_signal(tp_price=110.0, sl_price=90.0, max_holding_days=10)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=98.0, close=101.0),
        _make_bar(date(2026, 1, 3), open_=101.0, high=104.0, low=99.0, close=102.0),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "OPEN"
    assert outcome.holding_days == 2
    assert outcome.exit_date is None
    assert outcome.exit_price is None
    assert outcome.realized_return is None
    assert outcome.mfe == pytest.approx(0.04)
    assert outcome.mae == pytest.approx(-0.02)
    assert len(snapshots) == 2


def test_empty_forward_bars_returns_none():
    signal = _make_signal()
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, [])
    assert outcome is None
    assert snapshots == []


# -------------------------------------------------------------------------
# Unit Tests: OutcomeRepository
# -------------------------------------------------------------------------


def test_outcome_repository_crud():
    repo = OutcomeRepository(":memory:")

    # 1. Save and retrieve OPEN outcome
    open_outcome = SignalOutcomeRecord(
        signal_id="sig-101",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="OPEN",
        holding_days=1,
        mfe=0.02,
        mae=-0.01,
    )
    repo.save_outcome(open_outcome)

    fetched = repo.get_outcome_by_signal_id("sig-101")
    assert fetched is not None
    assert fetched.outcome_status == "OPEN"
    assert fetched.ticker == "BBCA"
    assert fetched.holding_days == 1

    # 2. Open outcomes query
    open_list = repo.get_open_outcomes()
    assert len(open_list) == 1
    assert open_list[0].signal_id == "sig-101"

    # 3. Transition to resolved TP (upsert)
    resolved_outcome = SignalOutcomeRecord(
        outcome_id=open_outcome.outcome_id,
        signal_id="sig-101",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="TP",
        exit_date=date(2026, 1, 5),
        exit_price=105.0,
        holding_days=3,
        mfe=0.06,
        mae=-0.01,
        exit_reason="TP",
    )
    repo.save_outcome(resolved_outcome)

    updated = repo.get_outcome_by_signal_id("sig-101")
    assert updated is not None
    assert updated.outcome_status == "TP"
    assert updated.exit_price == 105.0
    assert updated.holding_days == 3

    # Now open_outcomes is empty
    assert len(repo.get_open_outcomes()) == 0

    # Matured outcomes has 1
    matured = repo.get_matured_outcomes(ticker="BBCA")
    assert len(matured) == 1
    assert matured[0].signal_id == "sig-101"


def test_outcome_repository_snapshots():
    repo = OutcomeRepository(":memory:")

    snaps = [
        SignalDailySnapshot(
            signal_id="sig-201",
            snapshot_date=date(2026, 1, 2),
            holding_day=1,
            close_price=101.0,
            return_from_entry=0.01,
            high_price=103.0,
            low_price=99.0,
            mfe_so_far=0.03,
            mae_so_far=-0.01,
        ),
        SignalDailySnapshot(
            signal_id="sig-201",
            snapshot_date=date(2026, 1, 3),
            holding_day=2,
            close_price=104.0,
            return_from_entry=0.04,
            high_price=105.0,
            low_price=100.0,
            mfe_so_far=0.05,
            mae_so_far=-0.01,
        ),
    ]

    repo.save_snapshots(snaps)
    fetched = repo.get_snapshots_by_signal_id("sig-201")

    assert len(fetched) == 2
    assert fetched[0].holding_day == 1
    assert fetched[0].close_price == 101.0
    assert fetched[1].holding_day == 2
    assert fetched[1].close_price == 104.0


def test_resolve_signal_by_id_lifecycle():
    bar_repo = DailyBarRepository(":memory:")
    sig_repo = SignalRepository(":memory:")
    out_repo = OutcomeRepository(":memory:")

    engine = OutcomeEngine(
        bar_repo=bar_repo,
        signal_repo=sig_repo,
        outcome_repo=out_repo,
    )

    signal = _make_signal(
        signal_id="sig-live-001",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        tp_price=105.0,
        sl_price=95.0,
    )
    sig_repo.save_signals([signal])

    # 1. Day t+1 bar: enters, no TP or SL hit
    bar1 = _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=99.0, close=101.0)
    bar_repo.save_bars([bar1])
    outcome_open, snaps_open = engine.resolve_signal_by_id("sig-live-001", save=True)

    assert outcome_open is not None
    assert outcome_open.outcome_status == "OPEN"
    assert outcome_open.holding_days == 1
    assert len(snaps_open) == 1

    # 2. Day t+2 bar: hits TP
    bar2 = _make_bar(date(2026, 1, 3), open_=101.0, high=106.0, low=100.0, close=104.0)
    bar_repo.save_bars([bar2])
    outcome_tp, snaps_tp = engine.resolve_signal_by_id("sig-live-001", save=True)

    assert outcome_tp is not None
    assert outcome_tp.outcome_status == "TP"
    assert outcome_tp.holding_days == 2
    assert outcome_tp.exit_date == date(2026, 1, 3)
    assert outcome_tp.exit_price == pytest.approx(105.0)
    resolved_time = outcome_tp.resolved_at

    # 3. Third call without force_recompute returns existing matured record without re-evaluating
    outcome_cached, snaps_cached = engine.resolve_signal_by_id("sig-live-001", save=True)
    assert outcome_cached is not None
    assert outcome_cached.outcome_status == "TP"
    assert outcome_cached.resolved_at == resolved_time
    assert len(snaps_cached) == 2

    # 4. Force recompute runs evaluation
    outcome_forced, snaps_forced = engine.resolve_signal_by_id(
        "sig-live-001", save=True, force_recompute=True
    )
    assert outcome_forced is not None
    assert outcome_forced.outcome_status == "TP"


def test_notes_preservation_on_outcome_update():
    repo = OutcomeRepository(":memory:")

    open_outcome = SignalOutcomeRecord(
        signal_id="sig-note-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="OPEN",
        holding_days=1,
        notes="Risk assessment reviewed",
    )
    repo.save_outcome(open_outcome)

    # Update without notes (notes=None)
    updated_outcome = SignalOutcomeRecord(
        outcome_id=open_outcome.outcome_id,
        signal_id="sig-note-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="TP",
        exit_date=date(2026, 1, 3),
        exit_price=105.0,
        holding_days=2,
        notes=None,
    )
    repo.save_outcome(updated_outcome)

    fetched = repo.get_outcome_by_signal_id("sig-note-01")
    assert fetched is not None
    assert fetched.outcome_status == "TP"
    assert fetched.notes == "Risk assessment reviewed"


def test_outcome_repository_get_open_outcomes_ticker_filter():
    repo = OutcomeRepository(":memory:")

    repo.save_outcome(
        SignalOutcomeRecord(
            signal_id="sig-f1",
            ticker="BBCA",
            signal_date=date(2026, 1, 1),
            entry_date=date(2026, 1, 2),
            entry_price=100.0,
            outcome_status="OPEN",
        )
    )
    repo.save_outcome(
        SignalOutcomeRecord(
            signal_id="sig-f2",
            ticker="BBRI",
            signal_date=date(2026, 1, 1),
            entry_date=date(2026, 1, 2),
            entry_price=50.0,
            outcome_status="OPEN",
        )
    )

    all_open = repo.get_open_outcomes()
    assert len(all_open) == 2

    bbca_only = repo.get_open_outcomes(ticker="BBCA")
    assert len(bbca_only) == 1
    assert bbca_only[0].ticker == "BBCA"


def test_build_matured_dataset_exclude_ambiguous():
    sig_repo = SignalRepository(":memory:")
    out_repo = OutcomeRepository(":memory:")

    # Signals
    s1 = _make_signal(signal_id="s1", ticker="BBCA")
    s2 = _make_signal(signal_id="s2", ticker="BBRI")
    sig_repo.save_signals([s1, s2])

    # Outcomes: 1 TP and 1 AMBIGUOUS
    out_repo.save_outcome(
        SignalOutcomeRecord(
            signal_id="s1",
            ticker="BBCA",
            signal_date=date(2026, 1, 1),
            entry_date=date(2026, 1, 2),
            entry_price=100.0,
            outcome_status="TP",
            exit_date=date(2026, 1, 3),
            exit_price=105.0,
            holding_days=2,
        )
    )
    out_repo.save_outcome(
        SignalOutcomeRecord(
            signal_id="s2",
            ticker="BBRI",
            signal_date=date(2026, 1, 1),
            entry_date=date(2026, 1, 2),
            entry_price=50.0,
            outcome_status="AMBIGUOUS",
            exit_date=date(2026, 1, 3),
            exit_price=50.0,
            holding_days=2,
        )
    )

    # With exclude_ambiguous=False -> both are included
    df_all = build_matured_outcomes_dataset(out_repo, sig_repo, exclude_ambiguous=False)
    assert len(df_all) == 2
    assert set(df_all["outcome_status"]) == {"TP", "AMBIGUOUS"}

    # With exclude_ambiguous=True -> AMBIGUOUS is dropped
    df_clean = build_matured_outcomes_dataset(out_repo, sig_repo, exclude_ambiguous=True)
    assert len(df_clean) == 1
    assert df_clean.iloc[0]["outcome_status"] == "TP"
    assert df_clean.iloc[0]["binary_target"] == 1

