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
    # In-trade MFE bounded by TP barrier (105.0)
    assert outcome.mfe == pytest.approx(0.05)
    assert outcome.mae == pytest.approx(-0.01)
    # Full horizon opportunity captures full candle high (106.0)
    assert outcome.full_horizon_mfe == pytest.approx(0.06)

    assert len(snapshots) == 1
    assert snapshots[0].holding_day == 1
    assert snapshots[0].close_price == 104.0
    assert snapshots[0].mfe_so_far == pytest.approx(0.05)
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
    # In-trade MAE bounded by SL barrier (95.0)
    assert outcome.mae == pytest.approx(-0.05)
    # Full horizon opportunity captures full candle low (94.0)
    assert outcome.full_horizon_mae == pytest.approx(-0.06)


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
    """Pre-entry gap-through on Day 1 open invalidates entry before execution."""
    signal = _make_signal(tp_price=105.0, sl_price=95.0)

    # Gap up open >= TP on Day 1 (pre-entry gap)
    gap_up_bar = _make_bar(date(2026, 1, 2), open_=107.0, high=108.0, low=94.0, close=106.0)
    engine = OutcomeEngine(ambiguity_policy="conservative")
    outcome_up, _ = engine.evaluate_signal(signal, [gap_up_bar])
    assert outcome_up is not None
    assert outcome_up.outcome_status == "INVALIDATED_GAP"
    assert outcome_up.entry_status == "UNFILLED"
    assert outcome_up.entry_price is None

    # Gap down open <= SL on Day 1 (pre-entry gap)
    gap_down_bar = _make_bar(date(2026, 1, 2), open_=93.0, high=106.0, low=92.0, close=94.0)
    outcome_down, _ = engine.evaluate_signal(signal, [gap_down_bar])
    assert outcome_down is not None
    assert outcome_down.outcome_status == "INVALIDATED_GAP"
    assert outcome_down.entry_status == "UNFILLED"
    assert outcome_down.entry_price is None


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
    # In-trade MFE bounded by TP barrier (110.0) -> +10%
    assert outcome.mfe == pytest.approx(0.10)
    # Full horizon MFE across all 3 days reaches 111.0 (+11%)
    assert outcome.full_horizon_mfe == pytest.approx(0.11)
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
    assert snapshots[2].mfe_so_far == pytest.approx(0.10)
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


# -------------------------------------------------------------------------
# Unit Tests: Breakout Entry Policy & Dual-Mode Outcome Tracking
# -------------------------------------------------------------------------


def test_breakout_policy_delayed_entry_and_snapshots():
    """Verify that BREAKOUT policy waits for price >= entry_low before entering."""
    signal = SignalRecord(
        signal_id="sig-bo-001",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,  # Breakout trigger level
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )

    bars = [
        # Day 1: High reaches 104 (< 106) -> breakout not triggered yet
        _make_bar(date(2026, 1, 2), open_=101.0, high=104.0, low=100.0, close=103.0),
        # Day 2: Open 103, High 107 (>= 106) -> triggers breakout at 106, Close 106.5
        _make_bar(date(2026, 1, 3), open_=103.0, high=107.0, low=102.5, close=106.5),
        # Day 3: Open 107, High 113 (>= 112 TP hit), Low 105, Close 112.0
        _make_bar(date(2026, 1, 4), open_=107.0, high=113.0, low=105.0, close=112.0),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.entry_date == date(2026, 1, 3)  # Entered on Day 2 when breakout triggered
    assert outcome.entry_price == 106.0  # Trigger level fill
    assert outcome.exit_date == date(2026, 1, 4)
    assert outcome.exit_price == pytest.approx(112.0)
    assert outcome.holding_days == 2  # Day 2 (entry) and Day 3 (TP hit)

    # Snapshots start only from entry date (Day 2)
    assert len(snapshots) == 2
    assert snapshots[0].holding_day == 1
    assert snapshots[0].snapshot_date == date(2026, 1, 3)
    assert snapshots[1].holding_day == 2
    assert snapshots[1].snapshot_date == date(2026, 1, 4)


def test_breakout_policy_untriggered_within_max_holding_days_returns_none():
    """Verify untriggered breakout signal returns None while within max holding window."""
    signal = SignalRecord(
        signal_id="sig-bo-002",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )

    # 2 bars elapsed, both below 106.0 (< max_holding_days 5)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=99.0, close=101.0),
        _make_bar(date(2026, 1, 3), open_=101.0, high=104.0, low=100.0, close=102.0),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)
    assert outcome is None
    assert snapshots == []


def test_breakout_policy_expired_without_triggering():
    """Verify breakout signal expires with UNFILLED_EXPIRED if trigger level never reached."""
    signal = SignalRecord(
        signal_id="sig-bo-003",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=3,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )

    # 3 bars elapsed (== max_holding_days), none reached 106.0
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=99.0, close=101.0),
        _make_bar(date(2026, 1, 3), open_=101.0, high=104.0, low=100.0, close=102.0),
        _make_bar(date(2026, 1, 4), open_=102.0, high=105.0, low=101.0, close=103.0),
    ]

    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "UNFILLED_EXPIRED"
    assert outcome.exit_reason == "UNFILLED_EXPIRED"
    assert outcome.holding_days == 0
    assert outcome.realized_return is None
    assert outcome.exit_price is None
    assert outcome.net_return is None
    assert snapshots == []


def test_dual_mode_outcome_tracking_and_filtering():
    """Verify dual mode (LOW_PRICE vs HIGHER_PRICE) isolation in repository and engine."""
    sig_repo = SignalRepository(":memory:")
    out_repo = OutcomeRepository(":memory:")
    bar_repo = DailyBarRepository(":memory:")

    engine = OutcomeEngine(bar_repo=bar_repo, signal_repo=sig_repo, outcome_repo=out_repo)

    sig_low = SignalRecord(
        signal_id="sig-low-01",
        ticker="GOTO",
        signal_date=date(2026, 1, 1),
        signal="BUY",
        entry_low=80.0,
        entry_high=82.0,
        tp_price=86.0,
        sl_price=78.0,
        max_holding_days=5,
        predicted_probability=0.75,
        score=85.0,
        model_version="v1",
        mode="LOW_PRICE",
    )
    sig_high = SignalRecord(
        signal_id="sig-high-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10600.0,
        sl_price=9800.0,
        max_holding_days=5,
        predicted_probability=0.72,
        score=82.0,
        model_version="v1",
        mode="HIGHER_PRICE",
    )
    sig_repo.save_signals([sig_low, sig_high])

    # Save forward bars
    bar_repo.save_bars(
        [
            DailyBar(
                ticker="GOTO",
                date=date(2026, 1, 2),
                open=81.0,
                high=87.0,
                low=80.0,
                close=86.0,
                volume=1000,
            ),
            DailyBar(
                ticker="BBCA",
                date=date(2026, 1, 2),
                open=10050.0,
                high=10700.0,
                low=10000.0,
                close=10650.0,
                volume=1000,
            ),
        ]
    )

    # 1. Resolve LOW_PRICE mode only
    results_low = engine.resolve_all_signals(mode="LOW_PRICE", save=True)
    assert len(results_low) == 1
    assert results_low[0][0].ticker == "GOTO"
    assert results_low[0][0].mode == "LOW_PRICE"

    # Repository query for matured outcomes in LOW_PRICE
    matured_low = out_repo.get_matured_outcomes(mode="LOW_PRICE")
    assert len(matured_low) == 1
    assert matured_low[0].ticker == "GOTO"

    matured_high_empty = out_repo.get_matured_outcomes(mode="HIGHER_PRICE")
    assert len(matured_high_empty) == 0

    # 2. Resolve HIGHER_PRICE mode
    results_high = engine.resolve_all_signals(mode="HIGHER_PRICE", save=True)
    assert len(results_high) == 1
    assert results_high[0][0].ticker == "BBCA"
    assert results_high[0][0].mode == "HIGHER_PRICE"

    matured_high = out_repo.get_matured_outcomes(mode="HIGHER_PRICE")
    assert len(matured_high) == 1
    assert matured_high[0].ticker == "BBCA"


def test_breakout_entry_bar_ambiguity_policies():
    """Verify breakout entry bar collision between morning dip and trigger level."""
    signal = SignalRecord(
        signal_id="sig-bo-ambig",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=115.0,
        sl_price=102.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )

    # Day 1 (Jan 2): Opens at 103 (below entry 106), dips to 101 (<= SL 102),
    # then rallies to 107 (>= trigger 106), closes at 106.5 (> SL 102).
    bar1 = _make_bar(date(2026, 1, 2), open_=103.0, high=107.0, low=101.0, close=106.5)
    # Day 2 (Jan 3): Reaches TP
    bar2 = _make_bar(date(2026, 1, 3), open_=107.0, high=116.0, low=106.0, close=115.0)

    # 1. Conservative policy: assumes worst-case -> stopped out on Day 1 at sl_price
    engine_cons = OutcomeEngine(ambiguity_policy="conservative")
    out_cons, snaps_cons = engine_cons.evaluate_signal(signal, [bar1, bar2])
    assert out_cons is not None
    assert out_cons.outcome_status == "SL"
    assert out_cons.exit_price == 102.0
    assert out_cons.exit_reason == "SL"
    assert out_cons.holding_days == 1
    assert out_cons.exit_date == date(2026, 1, 2)

    # 2. Ambiguous policy: collision cannot be resolved -> AMBIGUOUS at close on Day 1
    engine_ambig = OutcomeEngine(ambiguity_policy="ambiguous")
    out_ambig, snaps_ambig = engine_ambig.evaluate_signal(signal, [bar1, bar2])
    assert out_ambig is not None
    assert out_ambig.outcome_status == "AMBIGUOUS"
    assert out_ambig.exit_price == pytest.approx(106.5)
    assert out_ambig.exit_reason == "AMBIGUOUS"
    assert out_ambig.holding_days == 1

    # 3. Optimistic policy: assumes dip occurred before breakout -> trade survives Day 1
    engine_opt = OutcomeEngine(ambiguity_policy="optimistic")
    out_opt, snaps_opt = engine_opt.evaluate_signal(signal, [bar1, bar2])
    assert out_opt is not None
    assert out_opt.outcome_status == "TP"
    assert out_opt.exit_price == pytest.approx(115.0)
    assert out_opt.exit_reason == "TP"
    assert out_opt.holding_days == 2
    assert out_opt.exit_date == date(2026, 1, 3)
    assert len(snaps_opt) == 2


def test_breakout_entry_bar_gap_down_then_surge():
    """Verify breakout entry bar where open is below SL, then rallies past TP."""
    signal = SignalRecord(
        signal_id="sig-bo-gapdown",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )

    # Open is 101 (< SL 102), low 100, high 115 (>= TP 112), close 114
    bar = _make_bar(date(2026, 1, 2), open_=101.0, high=115.0, low=100.0, close=114.0)

    # Conservative exits at sl_price (102.0), NOT at open (101.0); MFE bounded by entry (106.0)
    engine_cons = OutcomeEngine(ambiguity_policy="conservative")
    out_cons, _ = engine_cons.evaluate_signal(signal, [bar])
    assert out_cons is not None
    assert out_cons.outcome_status == "SL"
    assert out_cons.exit_price == 102.0
    assert out_cons.mfe == pytest.approx(0.0)
    assert out_cons.mae == pytest.approx((102.0 - 106.0) / 106.0)

    # Optimistic resolves to TP (112.0); MAE bounded by entry (106.0)
    engine_opt = OutcomeEngine(ambiguity_policy="optimistic")
    out_opt, _ = engine_opt.evaluate_signal(signal, [bar])
    assert out_opt is not None
    assert out_opt.outcome_status == "TP"
    assert out_opt.exit_price == pytest.approx(112.0)
    assert out_opt.mfe == pytest.approx((112.0 - 106.0) / 106.0)
    assert out_opt.mae == pytest.approx(0.0)

    # Ambiguous resolves to AMBIGUOUS at close (114.0)
    engine_ambig = OutcomeEngine(ambiguity_policy="ambiguous")
    out_ambig, _ = engine_ambig.evaluate_signal(signal, [bar])
    assert out_ambig is not None
    assert out_ambig.outcome_status == "AMBIGUOUS"
    assert out_ambig.exit_price == pytest.approx(114.0)
    assert out_ambig.mfe == pytest.approx((112.0 - 106.0) / 106.0)
    assert out_ambig.mae == pytest.approx((102.0 - 106.0) / 106.0)


def test_breakout_entry_bar_tp_no_post_exit_mae_leakage():
    """Verify that when a breakout hits TP, afternoon sell-off does not leak into MAE."""
    signal = SignalRecord(
        signal_id="sig-bo-tp-leakage",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=100.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    # Day 1: Open 104, surges past trigger 106 to TP 112 (high 113).
    # Then in afternoon closes down at 103 (below entry 106, but > SL 100).
    bar = _make_bar(date(2026, 1, 2), open_=104.0, high=113.0, low=102.0, close=103.0)
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, [bar])

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.exit_price == pytest.approx(112.0)
    assert outcome.holding_days == 1
    # In-trade MFE is bounded by TP (112.0 vs entry 106.0)
    assert outcome.mfe == pytest.approx((112.0 - 106.0) / 106.0)
    # In-trade MAE is 0.0 because the afternoon drop to close 103 happened AFTER exit at TP
    assert outcome.mae == pytest.approx(0.0)
    # Full horizon opportunity captures the afternoon drop
    assert outcome.full_horizon_mae == pytest.approx((102.0 - 106.0) / 106.0)


def test_extended_metrics_mfe_mae_price_and_time_to_events():
    """Verify calculation of mfe_price, mae_price, time_to_peak, time_to_tp, net_return."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0, max_holding_days=5)
    bars = [
        # Day 1: Open 100, High 103, Low 98, Close 101
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=98.0, close=101.0),
        # Day 2: Open 101, High 108 (peak), Low 97, Close 104
        _make_bar(date(2026, 1, 3), open_=101.0, high=108.0, low=97.0, close=104.0),
        # Day 3: Open 104, High 111 (>= 110 TP hit), Low 102, Close 110.0
        _make_bar(date(2026, 1, 4), open_=104.0, high=111.0, low=102.0, close=110.0),
    ]

    engine = OutcomeEngine()
    outcome, _ = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.entry_price == 100.0
    assert outcome.exit_price == pytest.approx(110.0)
    assert outcome.holding_days == 3

    # In-trade MFE / MAE bounded by exit barrier TP (110.0)
    assert outcome.mfe == pytest.approx(0.10)
    assert outcome.mae == pytest.approx(-0.03)
    assert outcome.mfe_price == pytest.approx(10.0)
    assert outcome.mae_price == pytest.approx(-3.0)

    # Full-horizon opportunity metrics capture high 111.0
    assert outcome.full_horizon_mfe == pytest.approx(0.11)
    assert outcome.full_horizon_mfe_price == pytest.approx(11.0)
    assert outcome.full_horizon_time_to_peak == 3

    # Time to events
    assert outcome.time_to_peak == 3  # In-trade peak reached on Day 3
    assert outcome.time_to_tp == 3
    assert outcome.time_to_sl is None

    # Return after brokerage commissions only (buy 0.15%, sell 0.25%)
    expected_fees = ((110.0 * (1.0 - 0.0025)) / (100.0 * (1.0 + 0.0015))) - 1.0
    assert outcome.return_after_fees == pytest.approx(expected_fees)

    # Net return after all modeled costs (fees + 10 bps slippage)
    expected_all = (
        (110.0 * (1.0 - 0.0005) * (1.0 - 0.0025))
        / (100.0 * (1.0 + 0.0005) * (1.0 + 0.0015))
    ) - 1.0
    assert outcome.net_return == pytest.approx(expected_all)
    assert outcome.return_after_fees_and_slippage == pytest.approx(expected_all)


def test_mfe_never_negative_and_mae_never_positive():
    """Verify that MFE is never negative and MAE is never positive when clamped."""
    signal = _make_signal(tp_price=120.0, sl_price=80.0, max_holding_days=1)
    # Candle where high == entry_price and low == entry_price (flat bar)
    bar_flat = _make_bar(date(2026, 1, 2), open_=100.0, high=100.0, low=100.0, close=100.0)

    engine = OutcomeEngine()
    outcome, _ = engine.evaluate_signal(signal, [bar_flat])

    assert outcome is not None
    assert outcome.mfe >= 0.0
    assert outcome.mfe_price >= 0.0
    assert outcome.mae <= 0.0
    assert outcome.mae_price <= 0.0


def test_unfilled_breakout_excluded_from_evaluation_metrics():
    """Verify that UNFILLED_EXPIRED outcomes are excluded from trade performance metrics."""
    from python.models.evaluation import EvaluationEngine

    out_tp = SignalOutcomeRecord(
        signal_id="sig-tp",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="TP",
        realized_return=0.10,
        holding_days=2,
        exit_date=date(2026, 1, 3),
        exit_price=110.0,
    )
    out_sl = SignalOutcomeRecord(
        signal_id="sig-sl",
        ticker="BBRI",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="SL",
        realized_return=-0.05,
        holding_days=1,
        exit_date=date(2026, 1, 2),
        exit_price=95.0,
    )
    out_unfilled = SignalOutcomeRecord(
        signal_id="sig-unfilled",
        ticker="TLKM",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=105.0,
        outcome_status="UNFILLED_EXPIRED",
        realized_return=None,
        holding_days=0,
        exit_date=date(2026, 1, 6),
        exit_price=None,
    )

    eval_engine = EvaluationEngine()
    report = eval_engine.evaluate_from_outcomes(
        outcomes=[out_tp, out_sl, out_unfilled],
        model_version="test_v1",
    )

    # Sample size should only be the 2 filled trades, NOT 3!
    assert report.sample_size == 2
    assert report.trading_metrics.total_trades == 2
    # 1 win out of 2 trades -> win_rate = 50% (NOT 33.3% from counting unfilled as loss)
    assert report.trading_metrics.win_rate == pytest.approx(0.50)
    assert report.trading_metrics.tp_rate == pytest.approx(0.50)
    assert report.trading_metrics.sl_rate == pytest.approx(0.50)


def test_repository_extended_metrics_persistence():
    """Verify persistence and retrieval of extended outcome fields in OutcomeRepository."""
    repo = OutcomeRepository(":memory:")

    rec = SignalOutcomeRecord(
        signal_id="sig-ext-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="TP",
        realized_return=0.08,
        net_return=0.0756,
        holding_days=3,
        mfe=0.10,
        mae=-0.02,
        mfe_price=10.0,
        mae_price=-2.0,
        time_to_peak=2,
        time_to_tp=3,
        exit_date=date(2026, 1, 5),
        exit_price=108.0,
    )
    repo.save_outcome(rec)

    fetched = repo.get_outcome_by_signal_id("sig-ext-01")
    assert fetched is not None
    assert fetched.mfe_price == pytest.approx(10.0)
    assert fetched.mae_price == pytest.approx(-2.0)
    assert fetched.time_to_peak == 2
    assert fetched.time_to_tp == 3
    assert fetched.time_to_sl is None
    assert fetched.net_return == pytest.approx(0.0756)


def test_build_matured_dataset_exclude_unfilled():
    """Verify build_matured_outcomes_dataset with exclude_unfilled option."""
    sig_repo = SignalRepository(":memory:")
    out_repo = OutcomeRepository(":memory:")

    s1 = _make_signal(signal_id="s-fill", ticker="BBCA")
    s2 = _make_signal(signal_id="s-unfill", ticker="TLKM")
    sig_repo.save_signals([s1, s2])

    out_repo.save_outcome(
        SignalOutcomeRecord(
            signal_id="s-fill",
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
            signal_id="s-unfill",
            ticker="TLKM",
            signal_date=date(2026, 1, 1),
            entry_date=date(2026, 1, 2),
            entry_price=105.0,
            outcome_status="UNFILLED_EXPIRED",
            holding_days=0,
            exit_date=date(2026, 1, 6),
        )
    )

    df_all = build_matured_outcomes_dataset(out_repo, sig_repo, exclude_unfilled=False)
    assert len(df_all) == 2

    df_no_unfilled = build_matured_outcomes_dataset(out_repo, sig_repo, exclude_unfilled=True)
    assert len(df_no_unfilled) == 1
    assert df_no_unfilled.iloc[0]["signal_id"] == "s-fill"
    assert "mfe_price" in df_no_unfilled.columns
    assert "net_return" in df_no_unfilled.columns


def test_breakout_policy_trigger_beyond_max_holding_days_expires_unfilled():
    """Verify that if trigger level is touched after max_holding_days, it expires as UNFILLED."""
    signal = SignalRecord(
        signal_id="sig-bo-late",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=3,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    # Day 1-3 stay below 106.0; Day 4 reaches 107.0 (> 106.0)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=99.0, close=101.0),
        _make_bar(date(2026, 1, 3), open_=101.0, high=104.0, low=100.0, close=102.0),
        _make_bar(date(2026, 1, 4), open_=102.0, high=105.0, low=101.0, close=103.0),
        _make_bar(date(2026, 1, 5), open_=103.0, high=107.0, low=102.0, close=106.5),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "UNFILLED_EXPIRED"
    assert outcome.entry_status == "UNFILLED"
    assert outcome.holding_days == 0
    assert outcome.entry_date is None
    assert outcome.entry_price is None
    assert outcome.exit_date is None
    assert outcome.exit_price is None
    assert outcome.realized_return is None
    assert outcome.gross_return is None
    assert outcome.return_after_fees is None
    assert outcome.return_after_fees_and_slippage is None
    assert outcome.net_return is None
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.trigger_price == 106.0
    assert outcome.observation_end_date == date(2026, 1, 4)
    assert outcome.notes is not None
    assert "105.0" in outcome.notes


def test_breakout_policy_trigger_on_exact_final_candle():
    """Verify breakout trigger touched on exact final candle of max_holding_days enters."""
    signal = SignalRecord(
        signal_id="sig-bo-boundary",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=112.0,
        sl_price=102.0,
        max_holding_days=3,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    # Day 1-2 below 106.0; Day 3 reaches 107.0 -> enters!
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=99.0, close=101.0),
        _make_bar(date(2026, 1, 3), open_=101.0, high=104.0, low=100.0, close=102.0),
        _make_bar(date(2026, 1, 4), open_=103.0, high=107.0, low=102.5, close=106.5),
        _make_bar(date(2026, 1, 5), open_=107.0, high=113.0, low=105.0, close=112.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.entry_status == "FILLED"
    assert outcome.entry_date == date(2026, 1, 4)
    assert outcome.entry_price == 106.0
    assert outcome.exit_date == date(2026, 1, 5)
    assert outcome.holding_days == 2


def test_intraday_breakout_snapshot_mae_consistency():
    """Verify snapshot mae_so_far does not get polluted by pre-breakout morning low."""
    signal = SignalRecord(
        signal_id="sig-bo-mae",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=115.0,
        sl_price=95.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    bars = [
        _make_bar(date(2026, 1, 2), open_=102.0, high=108.0, low=101.0, close=107.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert len(snapshots) == 1
    assert outcome.mae == pytest.approx(0.0)
    assert snapshots[0].mae_so_far == pytest.approx(0.0)


def test_entry_status_lifecycle_and_persistence():
    """Verify entry_status validation and persistence in SQLite repository."""
    repo = OutcomeRepository(":memory:")
    out_fill = SignalOutcomeRecord(
        signal_id="sig-stat-fill",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        entry_status="FILLED",
        outcome_status="TP",
        exit_date=date(2026, 1, 3),
        exit_price=105.0,
        holding_days=2,
    )
    out_unfill = SignalOutcomeRecord(
        signal_id="sig-stat-unfill",
        ticker="TLKM",
        signal_date=date(2026, 1, 1),
        entry_date=None,
        entry_price=None,
        entry_status="UNFILLED",
        outcome_status="UNFILLED_EXPIRED",
        holding_days=0,
        trigger_price=105.0,
        observation_end_date=date(2026, 1, 6),
    )
    repo.save_outcomes([out_fill, out_unfill])

    f1 = repo.get_outcome_by_signal_id("sig-stat-fill")
    assert f1 is not None
    assert f1.entry_status == "FILLED"
    assert f1.entry_price == 100.0

    f2 = repo.get_outcome_by_signal_id("sig-stat-unfill")
    assert f2 is not None
    assert f2.entry_status == "UNFILLED"
    assert f2.entry_price is None
    assert f2.entry_date is None
    assert f2.exit_price is None
    assert f2.exit_date is None
    assert f2.trigger_price == 105.0


def test_gap_through_tp_at_open():
    """Verify gap-through TP at open bounds excursions to open price."""
    signal = _make_signal(tp_price=105.0, sl_price=95.0, max_holding_days=5)
    bars = [
        # Day 1: normal bar
        _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=99.0, close=101.0),
        # Day 2: gaps open above TP at 108.0, intraday high 115.0, low 107.0, close 112.0
        _make_bar(date(2026, 1, 3), open_=108.0, high=115.0, low=107.0, close=112.0),
        # Day 3: future bar (should not be in trade)
        _make_bar(date(2026, 1, 4), open_=112.0, high=120.0, low=110.0, close=118.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.exit_price == pytest.approx(108.0)
    assert outcome.holding_days == 2
    # In-trade MFE bounded by gap exit at 108.0 (+8%), NOT 115.0 (+15%)
    assert outcome.mfe == pytest.approx(0.08)
    assert outcome.mfe_price == pytest.approx(8.0)
    # Full horizon opportunity captures high 120.0 (+20%)
    assert outcome.full_horizon_mfe == pytest.approx(0.20)
    assert outcome.full_horizon_mfe_price == pytest.approx(20.0)
    # Day 2 snapshot MFE so far is bounded by 108.0
    assert snapshots[1].mfe_so_far == pytest.approx(0.08)


def test_gap_through_sl_at_open():
    """Verify gap-through SL at open bounds excursions to open price."""
    signal = _make_signal(tp_price=110.0, sl_price=95.0, max_holding_days=5)
    bars = [
        # Day 1: normal bar
        _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=98.0, close=99.0),
        # Day 2: gaps open below SL at 92.0, then rallies intraday to 99.0, low 90.0, close 98.0
        _make_bar(date(2026, 1, 3), open_=92.0, high=99.0, low=90.0, close=98.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.exit_price == pytest.approx(92.0)
    assert outcome.holding_days == 2
    # In-trade MAE bounded by gap open at 92.0 (-8%), NOT 90.0 (-10%)
    assert outcome.mae == pytest.approx(-0.08)
    # In-trade MFE does not include intraday rally to 99.0 occurring after exit
    assert outcome.mfe == pytest.approx(0.02)  # from Day 1 high 102.0
    # Full horizon opportunity captures full candle extremes
    assert outcome.full_horizon_mae == pytest.approx(-0.10)


def test_same_candle_collision_ambiguity_policies():
    """Verify collision behavior under conservative, optimistic, and ambiguous policies."""
    signal = _make_signal(tp_price=105.0, sl_price=95.0, max_holding_days=5)
    # Candle touching both TP (105) and SL (95): Open 100, High 106, Low 94, Close 99
    collision_bar = _make_bar(date(2026, 1, 2), open_=100.0, high=106.0, low=94.0, close=99.0)

    # 1. Conservative (SL first): exits at SL 95 (-5%), MFE bounded by open 100 (0%), MAE -5%
    eng_cons = OutcomeEngine(ambiguity_policy="conservative")
    out_cons, _ = eng_cons.evaluate_signal(signal, [collision_bar])
    assert out_cons is not None
    assert out_cons.outcome_status == "SL"
    assert out_cons.exit_price == pytest.approx(95.0)
    assert out_cons.exit_reason == "SL"
    assert out_cons.mfe == pytest.approx(0.0)
    assert out_cons.mae == pytest.approx(-0.05)
    assert out_cons.full_horizon_mfe == pytest.approx(0.06)
    assert out_cons.full_horizon_mae == pytest.approx(-0.06)

    # 2. Optimistic (TP first): exits at TP 105 (+5%), MFE +5%, MAE bounded by open 100 (0%)
    eng_opt = OutcomeEngine(ambiguity_policy="optimistic")
    out_opt, _ = eng_opt.evaluate_signal(signal, [collision_bar])
    assert out_opt is not None
    assert out_opt.outcome_status == "TP"
    assert out_opt.exit_price == pytest.approx(105.0)
    assert out_opt.exit_reason == "TP"
    assert out_opt.mfe == pytest.approx(0.05)
    assert out_opt.mae == pytest.approx(0.0)
    assert out_opt.full_horizon_mfe == pytest.approx(0.06)
    assert out_opt.full_horizon_mae == pytest.approx(-0.06)

    # 3. Ambiguous (closes at market close 99): MFE bounded by TP 105 (+5%), MAE by SL 95 (-5%)
    eng_amb = OutcomeEngine(ambiguity_policy="ambiguous")
    out_amb, _ = eng_amb.evaluate_signal(signal, [collision_bar])
    assert out_amb is not None
    assert out_amb.outcome_status == "AMBIGUOUS"
    assert out_amb.exit_price == pytest.approx(99.0)  # Close
    assert out_amb.exit_reason == "AMBIGUOUS"
    assert out_amb.mfe == pytest.approx(0.05)
    assert out_amb.mae == pytest.approx(-0.05)
    assert out_amb.full_horizon_mfe == pytest.approx(0.06)
    assert out_amb.full_horizon_mae == pytest.approx(-0.06)


def test_fees_and_slippage_accounting_consistency():
    """Verify separate fee and slippage metrics and alignment with EV Gate friction."""
    signal = _make_signal(tp_price=105.0, sl_price=95.0, max_holding_days=5)
    # Trade exiting at break-even (exit_price == entry_price == 100.0)
    flat_bar = _make_bar(date(2026, 1, 2), open_=100.0, high=100.0, low=100.0, close=100.0)
    engine = OutcomeEngine(commission_buy=0.0015, commission_sell=0.0025, slippage_bps=10.0)

    # Immediate exit at horizon end with max_holding_days=1
    signal.max_holding_days = 1
    outcome, _ = engine.evaluate_signal(signal, [flat_bar])

    assert outcome is not None
    assert outcome.outcome_status == "EXPIRY"
    assert outcome.exit_price == pytest.approx(100.0)
    assert outcome.realized_return == pytest.approx(0.0)
    assert outcome.gross_return == pytest.approx(0.0)

    # Commissions-only return: ((100 * 0.9975) / (100 * 1.0015)) - 1.0 ~ -0.3994%
    expected_fees = (0.9975 / 1.0015) - 1.0
    assert outcome.return_after_fees == pytest.approx(expected_fees, abs=1e-6)

    # Commissions + Slippage return (5 bps each side = 10 bps total round trip):
    # ((100 * 0.9995 * 0.9975) / (100 * 1.0005 * 1.0015)) - 1.0 ~ -0.49895% (~ 50 bps friction)
    expected_all = ((0.9995 * 0.9975) / (1.0005 * 1.0015)) - 1.0
    assert outcome.net_return == pytest.approx(expected_all, abs=1e-6)
    assert outcome.return_after_fees_and_slippage == pytest.approx(expected_all, abs=1e-6)
    assert abs(outcome.net_return - (-0.0050)) < 1.5e-5  # Matches EV Gate 50 bps friction


def test_unfilled_breakout_expiry_null_metrics_and_repository_persistence():
    """Verify UNFILLED_EXPIRED stores NULL trade metrics and persists cleanly in repository."""
    repo = OutcomeRepository(":memory:")
    signal = SignalRecord(
        signal_id="sig-unfilled-repo",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=110.0,
        entry_high=112.0,
        tp_price=118.0,
        sl_price=105.0,
        max_holding_days=3,
        predicted_probability=0.65,
        score=75.0,
        model_version="v1",
    )
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=104.0, low=98.0, close=102.0),
        _make_bar(date(2026, 1, 3), open_=102.0, high=106.0, low=100.0, close=104.0),
        _make_bar(date(2026, 1, 4), open_=104.0, high=107.0, low=101.0, close=105.0),
    ]
    engine = OutcomeEngine(outcome_repo=repo)
    outcome, _ = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "UNFILLED_EXPIRED"
    assert outcome.entry_status == "UNFILLED"
    assert outcome.entry_date is None
    assert outcome.entry_price is None
    assert outcome.exit_date is None
    assert outcome.exit_price is None
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.realized_return is None
    assert outcome.net_return is None
    assert outcome.trigger_price == 110.0
    assert outcome.observation_end_date == date(2026, 1, 4)
    assert outcome.full_horizon_mfe is not None
    assert outcome.is_full_horizon_complete is True

    # Persist and re-fetch from SQLite
    repo.save_outcome(outcome)
    fetched = repo.get_outcome_by_signal_id("sig-unfilled-repo")
    assert fetched is not None
    assert fetched.entry_status == "UNFILLED"
    assert fetched.entry_price is None
    assert fetched.entry_date is None
    assert fetched.exit_price is None
    assert fetched.exit_date is None
    assert fetched.mfe is None
    assert fetched.mae is None
    assert fetched.realized_return is None
    assert fetched.net_return is None
    assert fetched.trigger_price == 110.0
    assert fetched.observation_end_date == date(2026, 1, 4)
    assert fetched.is_full_horizon_complete is True


def test_immediate_entry_open_below_sl_invalidated_gap():
    """Verify Day 1 open below SL resolves to INVALIDATED_GAP with NULL trade metrics."""
    signal = _make_signal(
        entry_low=99.0, entry_high=101.0, tp_price=105.0, sl_price=95.0, max_holding_days=5
    )
    bars = [
        _make_bar(date(2026, 1, 2), open_=93.0, high=98.0, low=92.0, close=96.0),
        _make_bar(date(2026, 1, 3), open_=96.0, high=102.0, low=95.0, close=101.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "INVALIDATED_GAP"
    assert outcome.entry_status == "UNFILLED"
    assert outcome.entry_price is None
    assert outcome.entry_date is None
    assert outcome.exit_price is None
    assert outcome.exit_date is None
    assert outcome.realized_return is None
    assert outcome.gross_return is None
    assert outcome.return_after_fees is None
    assert outcome.return_after_fees_and_slippage is None
    assert outcome.net_return is None
    assert outcome.holding_days == 0
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.mfe_price is None
    assert outcome.mae_price is None
    assert outcome.time_to_peak is None
    assert outcome.time_to_tp is None
    assert outcome.time_to_sl is None
    assert outcome.exit_reason == "INVALIDATED_GAP"
    assert len(snapshots) == 0

    # Scope B opportunity metrics capture counterfactual trajectory relative to anchor (100.0)
    assert outcome.trigger_price == pytest.approx(100.0)
    assert outcome.full_horizon_mfe == pytest.approx((102.0 - 100.0) / 100.0)
    assert outcome.full_horizon_mae == pytest.approx((92.0 - 100.0) / 100.0)
    assert outcome.observation_end_date == date(2026, 1, 3)


def test_immediate_entry_open_above_tp_invalidated_gap():
    """Verify immediate entry with Day 1 open above TP resolves to INVALIDATED_GAP."""
    signal = _make_signal(
        entry_low=99.0, entry_high=101.0, tp_price=105.0, sl_price=95.0, max_holding_days=5
    )
    bars = [
        _make_bar(date(2026, 1, 2), open_=108.0, high=112.0, low=106.0, close=110.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "INVALIDATED_GAP"
    assert outcome.entry_status == "UNFILLED"
    assert outcome.entry_price is None
    assert outcome.realized_return is None
    assert outcome.net_return is None
    assert outcome.holding_days == 0
    assert outcome.mfe is None
    assert outcome.mae is None
    assert len(snapshots) == 0


def test_valid_immediate_entry_open_between_barriers():
    """Verify normal immediate entry between barriers fills cleanly at open."""
    signal = _make_signal(entry_low=99.0, entry_high=101.0, tp_price=105.0, sl_price=95.0)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=98.0, close=102.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.entry_status == "FILLED"
    assert outcome.entry_price == 100.0
    assert outcome.outcome_status == "OPEN"
    assert len(snapshots) == 1


def test_breakout_open_above_trigger_below_tp_fills_at_open():
    """Verify breakout order opening above trigger but below TP fills at open (gap up fill)."""
    signal = SignalRecord(
        signal_id="sig-bo-gap-fill",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=115.0,
        sl_price=95.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    bars = [
        # Gaps open at 108.0 (above trigger 106.0, below TP 115.0), high reaches 112.0
        _make_bar(date(2026, 1, 2), open_=108.0, high=112.0, low=107.0, close=110.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.entry_status == "FILLED"
    assert outcome.entry_price == 108.0  # filled at open price above trigger
    assert outcome.outcome_status == "OPEN"
    assert len(snapshots) == 1


def test_breakout_open_exceeds_tp_invalidated_gap():
    """Verify breakout order opening above TP barrier resolves to INVALIDATED_GAP."""
    signal = SignalRecord(
        signal_id="sig-bo-gap-tp",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        reference_price=100.0,
        entry_low=106.0,
        entry_high=108.0,
        tp_price=115.0,
        sl_price=95.0,
        max_holding_days=5,
        predicted_probability=0.70,
        score=80.0,
        model_version="v1",
    )
    bars = [
        # Gaps open at 118.0 (above TP 115.0)
        _make_bar(date(2026, 1, 2), open_=118.0, high=120.0, low=116.0, close=117.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "INVALIDATED_GAP"
    assert outcome.entry_status == "UNFILLED"
    assert outcome.entry_price is None
    assert outcome.realized_return is None
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.holding_days == 0
    assert len(snapshots) == 0


def test_post_entry_gap_down_on_day_2_remains_sl_fill_at_open():
    """Verify that an already-open position (Day 1 filled) that gaps down on Day 2
    below SL exits at open as an executed SL trade, preserving trade metrics."""
    signal = _make_signal(tp_price=110.0, sl_price=95.0, max_holding_days=5)
    bars = [
        # Day 1: normal fill at open 100.0, trades between 98.0 and 102.0
        _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=98.0, close=100.0),
        # Day 2: gaps down to 91.0 (below SL 95.0), low 90.0, high 93.0, close 92.0
        _make_bar(date(2026, 1, 3), open_=91.0, high=93.0, low=90.0, close=92.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.entry_status == "FILLED"
    assert outcome.outcome_status == "SL"
    assert outcome.entry_date == date(2026, 1, 2)
    assert outcome.entry_price == pytest.approx(100.0)
    assert outcome.exit_date == date(2026, 1, 3)
    assert outcome.exit_price == pytest.approx(91.0)  # filled at open on Day 2
    assert outcome.realized_return == pytest.approx(-0.09)
    assert outcome.holding_days == 2
    # In-trade MAE bounded by gap open at 91.0 (-9%), NOT low of 90.0 (-10%)
    assert outcome.mae == pytest.approx(-0.09)
    assert len(snapshots) == 2


def test_invalidated_gap_exclusion_from_evaluation_metrics():
    """Verify INVALIDATED_GAP is excluded from trading metrics, win rate, and expectancy."""
    from python.models.evaluation import EvaluationEngine

    o_tp = SignalOutcomeRecord(
        signal_id="s1",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="TP",
        exit_date=date(2026, 1, 3),
        exit_price=105.0,
        realized_return=0.05,
        holding_days=2,
    )
    o_sl = SignalOutcomeRecord(
        signal_id="s2",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        entry_price=100.0,
        outcome_status="SL",
        exit_date=date(2026, 1, 3),
        exit_price=95.0,
        realized_return=-0.05,
        holding_days=2,
    )
    o_gap = SignalOutcomeRecord(
        signal_id="s3",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_status="UNFILLED",
        outcome_status="INVALIDATED_GAP",
        holding_days=0,
    )

    eval_eng = EvaluationEngine()
    report = eval_eng.evaluate_from_outcomes(
        outcomes=[o_tp, o_sl, o_gap],
        model_version="test_model",
    )

    # Sample size should only count filled trades (2), excluding INVALIDATED_GAP
    assert report.sample_size == 2
    assert report.trading_metrics.total_trades == 2
    assert report.trading_metrics.win_rate == pytest.approx(0.50)


def test_invalidated_gap_lifecycle_validation_and_persistence():
    """Verify lifecycle constraints and SQLite persistence roundtrip for INVALIDATED_GAP."""
    repo = OutcomeRepository(":memory:")

    # Attempting to assign entry_price to INVALIDATED_GAP should raise ValueError
    with pytest.raises(ValueError, match="cannot have entry_price"):
        SignalOutcomeRecord(
            signal_id="sig-inv-fail",
            ticker="BBCA",
            signal_date=date(2026, 1, 1),
            entry_price=100.0,
            outcome_status="INVALIDATED_GAP",
            holding_days=0,
        )

    # Valid INVALIDATED_GAP record persists and reloads cleanly
    out_valid = SignalOutcomeRecord(
        signal_id="sig-inv-pass",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        outcome_status="INVALIDATED_GAP",
        trigger_price=100.0,
        observation_end_date=date(2026, 1, 5),
        full_horizon_mfe=0.10,
        full_horizon_mae=-0.05,
        holding_days=0,
    )
    repo.save_outcome(out_valid)
    fetched = repo.get_outcome_by_signal_id("sig-inv-pass")
    assert fetched is not None
    assert fetched.outcome_status == "INVALIDATED_GAP"
    assert fetched.entry_status == "UNFILLED"
    assert fetched.entry_price is None
    assert fetched.entry_date is None
    assert fetched.exit_price is None
    assert fetched.realized_return is None
    assert fetched.holding_days == 0
    assert fetched.trigger_price == 100.0


def test_tp_day_low_conservative_proxy_semantics():
    """Verify exit proxy: TP exit bounds MFE at TP, while MAE reflects candle low."""
    signal = _make_signal(tp_price=105.0, sl_price=95.0, max_holding_days=5)
    # Day 1: entries at open 100.0, rallies to 107.0 (hitting TP 105), but also has low 98.0
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=107.0, low=98.0, close=104.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.exit_price == pytest.approx(105.0)
    assert outcome.realized_return == pytest.approx(0.05)
    # In-trade MFE bounded at TP barrier (105.0 = +5%)
    assert outcome.mfe == pytest.approx(0.05)
    # Conservative daily-bar proxy: MAE includes low of 98.0 (-2%) as potential pre-TP excursion
    assert outcome.mae == pytest.approx(-0.02)
    # Full horizon opportunity captures full candle high of 107.0 (+7%)
    assert outcome.full_horizon_mfe == pytest.approx(0.07)
    # Daily snapshot matches terminal metrics
    assert snapshots[0].mfe_so_far == pytest.approx(0.05)
    assert snapshots[0].mae_so_far == pytest.approx(-0.02)


def test_sl_day_high_conservative_proxy_semantics():
    """Verify exit proxy: SL exit bounds MAE at SL, while MFE reflects candle high."""
    signal = _make_signal(tp_price=110.0, sl_price=95.0, max_holding_days=5)
    # Day 1: entries at open 100.0, high 103.0, drops to low 93.0 (hitting SL 95)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=93.0, close=94.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.exit_price == pytest.approx(95.0)
    assert outcome.realized_return == pytest.approx(-0.05)
    # In-trade MAE bounded at SL barrier (95.0 = -5%)
    assert outcome.mae == pytest.approx(-0.05)
    # In-trade MFE reflects candle high of 103.0 (+3%) prior to stop-out
    assert outcome.mfe == pytest.approx(0.03)
    # Full horizon opportunity captures full candle low of 93.0 (-7%)
    assert outcome.full_horizon_mae == pytest.approx(-0.07)


def test_asii_bbca_byan_historical_recomputation():
    """Verify exact recomputations for historical signals ASII, BBCA, and BYAN."""
    engine = OutcomeEngine()

    # 1. BYAN (2026-08-18): Ref=17275, entry=[17188.62, 17361.37], TP=18229.44, SL=16844.85
    # Next day 2026-08-19: Open 14700.0 (gapped below SL 16844.85)
    sig_byan = SignalRecord(
        signal_id="2b7159d5-7987-5494-94ee-5898e6c20c27",
        ticker="BYAN",
        signal_date=date(2026, 8, 18),
        signal="BUY",
        reference_price=17275.0,
        entry_low=17188.62,
        entry_high=17361.37,
        tp_price=18229.44,
        sl_price=16844.85,
        max_holding_days=10,
        predicted_probability=0.3238,
        score=50.23,
        model_version="champion",
        entry_policy="IMMEDIATE",
    )
    byan_bars = [
        _make_bar(
            date(2026, 8, 19),
            open_=14700.0,
            high=18650.0,
            low=14700.0,
            close=15650.0,
            ticker="BYAN",
        ),
    ]
    out_byan, snap_byan = engine.evaluate_signal(sig_byan, byan_bars)
    assert out_byan is not None
    assert out_byan.outcome_status == "INVALIDATED_GAP"
    assert out_byan.entry_status == "UNFILLED"
    assert out_byan.entry_price is None
    assert out_byan.realized_return is None
    assert out_byan.holding_days == 0
    assert len(snap_byan) == 0
    assert out_byan.trigger_price == 17275.0
    assert out_byan.full_horizon_mfe == pytest.approx((18650.0 - 17275.0) / 17275.0)

    # 2. ASII (2026-10-09): entry_low=5124.25, entry_high=5175.75, TP=5434.54, SL=5021.77
    # Next day 2026-10-12: Open 4850.0 (gapped below SL 5021.77)
    sig_asii = SignalRecord(
        signal_id="d6825f71-84b2-511d-9dc1-b9b5082ba4dd",
        ticker="ASII",
        signal_date=date(2026, 10, 9),
        signal="BUY",
        entry_low=5124.25,
        entry_high=5175.75,
        tp_price=5434.54,
        sl_price=5021.77,
        max_holding_days=10,
        predicted_probability=0.0,
        score=7.86,
        model_version="v1",
    )
    asii_bars = [
        _make_bar(
            date(2026, 10, 12),
            open_=4850.0,
            high=4920.0,
            low=4810.0,
            close=4810.0,
            ticker="ASII",
        ),
    ]
    out_asii, snap_asii = engine.evaluate_signal(sig_asii, asii_bars)
    assert out_asii is not None
    assert out_asii.outcome_status == "INVALIDATED_GAP"
    assert out_asii.entry_status == "UNFILLED"
    assert out_asii.entry_price is None
    assert out_asii.realized_return is None
    assert out_asii.holding_days == 0
    assert len(snap_asii) == 0
    assert out_asii.trigger_price == pytest.approx(5150.0)

    # 3. BBCA (2026-10-09): entry_low=10149.0, entry_high=10251.0, TP=10763.55, SL=9946.02
    # Next day 2026-10-12: Open 6050.0 (gapped below SL 9946.02)
    sig_bbca = SignalRecord(
        signal_id="29cb7d6c-802f-5a07-8853-06efbc7d62a8",
        ticker="BBCA",
        signal_date=date(2026, 10, 9),
        signal="BUY",
        entry_low=10149.0,
        entry_high=10251.0,
        tp_price=10763.55,
        sl_price=9946.02,
        max_holding_days=10,
        predicted_probability=0.0,
        score=7.86,
        model_version="v1",
    )
    bbca_bars = [
        _make_bar(
            date(2026, 10, 12),
            open_=6050.0,
            high=6100.0,
            low=5950.0,
            close=5950.0,
            ticker="BBCA",
        ),
    ]
    out_bbca, snap_bbca = engine.evaluate_signal(sig_bbca, bbca_bars)
    assert out_bbca is not None
    assert out_bbca.outcome_status == "INVALIDATED_GAP"
    assert out_bbca.entry_status == "UNFILLED"
    assert out_bbca.entry_price is None
    assert out_bbca.realized_return is None
    assert out_bbca.holding_days == 0
    assert len(snap_bbca) == 0
    assert out_bbca.trigger_price == pytest.approx(10200.0)


# -------------------------------------------------------------------------
# Unit Tests: Excursion Bounds, Entry Deviation, and Barrier Exits
# -------------------------------------------------------------------------


def test_tp_touched_excursion_bounds_and_snapshot_parity():
    """Verify single TP exit bounds and snapshot parity."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=105.0, low=98.0, close=103.0),
        _make_bar(date(2026, 1, 5), open_=102.0, high=112.0, low=97.0, close=109.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "TP"
    assert outcome.holding_days == 2
    assert outcome.entry_price == 100.0
    assert outcome.exit_price == pytest.approx(110.0)

    # In-trade MFE is bounded by TP barrier on exit day
    assert outcome.mfe == pytest.approx(0.10)
    assert outcome.mfe_min == pytest.approx(0.10)
    assert outcome.mfe_max == pytest.approx(0.10)

    # MAE bounds: Day 1 reached 98.0 (-2%), Day 2 reached 97.0 (-3%)
    # If TP hit before day 2 low, low was 102.0 (open), so adverse excursion was -2% (from Day 1)
    # If low hit before TP, adverse excursion was -3% (Day 2 low)
    assert outcome.mae_min == pytest.approx(-0.03)
    assert outcome.mae_max == pytest.approx(-0.02)
    assert outcome.mae == pytest.approx(-0.03)

    # Snapshots check
    assert len(snapshots) == 2
    last_snap = snapshots[-1]
    assert last_snap.holding_day == 2
    assert last_snap.mfe_so_far == pytest.approx(outcome.mfe)
    assert last_snap.mae_so_far == pytest.approx(outcome.mae)
    assert last_snap.mfe_min_so_far == pytest.approx(outcome.mfe_min)
    assert last_snap.mfe_max_so_far == pytest.approx(outcome.mfe_max)
    assert last_snap.mae_min_so_far == pytest.approx(outcome.mae_min)
    assert last_snap.mae_max_so_far == pytest.approx(outcome.mae_max)


def test_sl_touched_excursion_bounds_and_snapshot_parity():
    """Verify single SL exit bounds and snapshot parity."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0)
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=104.0, low=95.0, close=96.0),
        _make_bar(date(2026, 1, 5), open_=94.0, high=98.0, low=88.0, close=89.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.holding_days == 2
    assert outcome.entry_price == 100.0
    assert outcome.exit_price == pytest.approx(90.0)

    # In-trade MAE is bounded by SL barrier on exit day
    assert outcome.mae == pytest.approx(-0.10)
    assert outcome.mae_min == pytest.approx(-0.10)
    assert outcome.mae_max == pytest.approx(-0.10)

    # MFE bounds: Day 1 reached 104.0 (+4%).
    # Day 2 reached 98.0 (< 104.0).
    # Regardless of whether 98.0 was before or after SL, Day 1 peak was 104.0
    assert outcome.mfe_min == pytest.approx(0.04)
    assert outcome.mfe_max == pytest.approx(0.04)
    assert outcome.mfe == pytest.approx(0.04)

    # Snapshots check
    assert len(snapshots) == 2
    last_snap = snapshots[-1]
    assert last_snap.mfe_so_far == pytest.approx(outcome.mfe)
    assert last_snap.mae_so_far == pytest.approx(outcome.mae)
    assert last_snap.mfe_min_so_far == pytest.approx(outcome.mfe_min)
    assert last_snap.mfe_max_so_far == pytest.approx(outcome.mfe_max)
    assert last_snap.mae_min_so_far == pytest.approx(outcome.mae_min)
    assert last_snap.mae_max_so_far == pytest.approx(outcome.mae_max)


def test_gap_through_exit_at_open_bounds():
    """Verify gap-through at open bounds are exact and equal."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0)
    # Day 1 regular, Day 2 gaps below SL at open 85.0
    bars = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=103.0, low=97.0, close=98.0),
        _make_bar(date(2026, 1, 5), open_=85.0, high=88.0, low=82.0, close=86.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.holding_days == 2
    assert outcome.exit_price == pytest.approx(85.0)

    # Exit at open: Day 2 in-trade extreme is 85.0
    assert outcome.mae == pytest.approx(-0.15)
    assert outcome.mae_min == pytest.approx(-0.15)
    assert outcome.mae_max == pytest.approx(-0.15)
    assert outcome.mfe == pytest.approx(0.03)
    assert outcome.mfe_min == pytest.approx(0.03)
    assert outcome.mfe_max == pytest.approx(0.03)


def test_breakout_entry_intraday_and_open_exceeding_dev():
    """Verify breakout intraday entry vs excessive gap at trigger day open."""
    # Breakout signal: entry_low is trigger level (105.0)
    sig_breakout = SignalRecord(
        signal_id="sig-breakout-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        entry_low=105.0,
        entry_high=107.0,
        tp_price=115.0,
        sl_price=95.0,
        max_holding_days=5,
        predicted_probability=0.8,
        score=90.0,
        model_version="v1",
        max_entry_deviation_pct=0.05,
    )

    # 1. Intraday trigger: Day 1 open=100.0 (< 105.0), high=108.0 (triggers at 105.0)
    bars_trigger_intraday = [
        _make_bar(date(2026, 1, 2), open_=100.0, high=108.0, low=99.0, close=106.0),
    ]
    engine = OutcomeEngine()
    out1, snaps1 = engine.evaluate_signal(sig_breakout, bars_trigger_intraday)
    assert out1 is not None
    assert out1.outcome_status == "OPEN"
    assert out1.entry_status == "FILLED"
    assert out1.entry_price == pytest.approx(105.0)
    assert out1.entry_deviation_pct == pytest.approx(0.0)

    # 2. Open exceeds max deviation: trigger=105.0, open=112.0 (dev = 6.67% > 5%)
    bars_trigger_gap = [
        _make_bar(date(2026, 1, 2), open_=112.0, high=114.0, low=110.0, close=113.0),
    ]
    out2, snaps2 = engine.evaluate_signal(sig_breakout, bars_trigger_gap)
    assert out2 is not None
    assert out2.outcome_status == "INVALIDATED_GAP"
    assert out2.entry_status == "UNFILLED"
    assert out2.entry_price is None
    assert len(snaps2) == 0


def test_same_candle_collision_excursion_bounds_policies():
    """Verify excursion bounds for same-candle collisions under all 3 policies."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0)
    bar = _make_bar(date(2026, 1, 2), open_=100.0, high=115.0, low=85.0, close=102.0)

    # 1. Conservative (SL first)
    eng_cons = OutcomeEngine(ambiguity_policy="conservative")
    out_cons, _ = eng_cons.evaluate_signal(signal, [bar])
    assert out_cons is not None
    assert out_cons.outcome_status == "SL"
    assert out_cons.exit_price == pytest.approx(90.0)
    assert out_cons.mae == pytest.approx(-0.10)
    assert out_cons.mae_min == pytest.approx(-0.10)
    assert out_cons.mae_max == pytest.approx(-0.10)
    assert out_cons.mfe == pytest.approx(0.0)  # bounded at open (100.0)
    assert out_cons.mfe_min == pytest.approx(0.0)
    assert out_cons.mfe_max == pytest.approx(0.15)  # upper bound had high touched first

    # 2. Optimistic (TP first)
    eng_opt = OutcomeEngine(ambiguity_policy="optimistic")
    out_opt, _ = eng_opt.evaluate_signal(signal, [bar])
    assert out_opt is not None
    assert out_opt.outcome_status == "TP"
    assert out_opt.exit_price == pytest.approx(110.0)
    assert out_opt.mfe == pytest.approx(0.10)
    assert out_opt.mfe_min == pytest.approx(0.10)
    assert out_opt.mfe_max == pytest.approx(0.10)
    assert out_opt.mae == pytest.approx(0.0)  # bounded at open (100.0)
    assert out_opt.mae_min == pytest.approx(-0.15)  # lower bound had low touched first
    assert out_opt.mae_max == pytest.approx(0.0)

    # 3. Ambiguous (Close exit)
    eng_amb = OutcomeEngine(ambiguity_policy="ambiguous")
    out_amb, _ = eng_amb.evaluate_signal(signal, [bar])
    assert out_amb is not None
    assert out_amb.outcome_status == "AMBIGUOUS"
    assert out_amb.exit_price == pytest.approx(102.0)
    assert out_amb.mfe == pytest.approx(0.10)
    assert out_amb.mfe_min == pytest.approx(0.10)
    assert out_amb.mfe_max == pytest.approx(0.10)
    assert out_amb.mae == pytest.approx(-0.10)
    assert out_amb.mae_min == pytest.approx(-0.10)
    assert out_amb.mae_max == pytest.approx(-0.10)


def test_immediate_entry_band_and_deviation_scenarios():
    """Verify immediate entry band enforcement and max deviation gating."""
    # Signal: entry range [99.0, 101.0], ref=100.0, max_dev=0.05 (range 95.0 to 105.0)
    signal = _make_signal(entry_low=99.0, entry_high=101.0, tp_price=110.0, sl_price=90.0)

    # Scenario A: Open inside band (100.0) -> fills under both modes
    bar_inside = [_make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=99.5, close=101.0)]
    eng_lax = OutcomeEngine(enforce_entry_band=False)
    out_a1, _ = eng_lax.evaluate_signal(signal, bar_inside)
    assert out_a1 is not None and out_a1.outcome_status == "OPEN"
    assert out_a1.entry_price == 100.0
    assert out_a1.entry_deviation_pct == pytest.approx(0.0)

    eng_strict = OutcomeEngine(enforce_entry_band=True)
    out_a2, _ = eng_strict.evaluate_signal(signal, bar_inside)
    assert out_a2 is not None and out_a2.outcome_status == "OPEN"
    assert out_a2.entry_price == 100.0

    # Scenario B: Open outside band (102.0) but <= 5% deviation (dev = 2%)
    bar_outside_mild = [
        _make_bar(date(2026, 1, 2), open_=102.0, high=103.0, low=101.5, close=102.5)
    ]
    out_b1, _ = eng_lax.evaluate_signal(signal, bar_outside_mild)
    assert out_b1 is not None and out_b1.outcome_status == "OPEN"
    assert out_b1.entry_price == 102.0
    assert out_b1.entry_deviation_pct == pytest.approx(0.02)

    out_b2, snaps_b2 = eng_strict.evaluate_signal(signal, bar_outside_mild)
    assert out_b2 is not None
    assert out_b2.outcome_status == "INVALIDATED_GAP"
    assert out_b2.entry_status == "UNFILLED"
    assert out_b2.entry_price is None
    assert len(snaps_b2) == 0

    # Scenario C: Open outside max deviation (106.0, dev = 6% > 5%)
    bar_outside_extreme = [
        _make_bar(date(2026, 1, 2), open_=106.0, high=107.0, low=105.0, close=106.5)
    ]
    out_c1, snaps_c1 = eng_lax.evaluate_signal(signal, bar_outside_extreme)
    assert out_c1 is not None
    assert out_c1.outcome_status == "INVALIDATED_GAP"
    assert out_c1.entry_status == "UNFILLED"
    assert out_c1.entry_price is None
    assert len(snaps_c1) == 0


def test_sl_touched_before_days_high_uncertain_excursion():
    """Verify SL touched on Day 2 where Day 2 high exceeds prior peak produces distinct bounds."""
    signal = _make_signal(tp_price=110.0, sl_price=90.0, max_holding_days=5)
    bars = [
        # Day 1: normal entry at 100.0, peak reaches 102.0 (+2%)
        _make_bar(date(2026, 1, 2), open_=100.0, high=102.0, low=98.0, close=101.0),
        # Day 2: opens at 94.0, touches high 108.0 (+8%), drops to low 88.0 (hitting SL 90.0)
        _make_bar(date(2026, 1, 5), open_=94.0, high=108.0, low=88.0, close=89.0),
    ]
    engine = OutcomeEngine()
    outcome, snapshots = engine.evaluate_signal(signal, bars)

    assert outcome is not None
    assert outcome.outcome_status == "SL"
    assert outcome.holding_days == 2
    assert outcome.entry_price == 100.0
    assert outcome.exit_price == pytest.approx(90.0)

    # In-trade MAE is strictly bounded at SL barrier
    assert outcome.mae == pytest.approx(-0.10)
    assert outcome.mae_min == pytest.approx(-0.10)
    assert outcome.mae_max == pytest.approx(-0.10)

    # In-trade MFE bounds:
    # Lower bound (SL visited before candle high): Day 2 high in-trade is bounded by open 94.0,
    # so overall in-trade peak is Day 1 high 102.0 (+2%).
    assert outcome.mfe_min == pytest.approx(0.02)
    # Upper bound (candle high visited before SL): Day 2 high 108.0 reached in-trade (+8%).
    assert outcome.mfe_max == pytest.approx(0.08)
    # Proxy tracks upper bound estimate
    assert outcome.mfe == pytest.approx(0.08)

    # Snapshots parity on terminal day
    assert len(snapshots) == 2
    last_snap = snapshots[-1]
    assert last_snap.holding_day == 2
    assert last_snap.mfe_so_far == pytest.approx(outcome.mfe)
    assert last_snap.mae_so_far == pytest.approx(outcome.mae)
    assert last_snap.mfe_min_so_far == pytest.approx(outcome.mfe_min)
    assert last_snap.mfe_max_so_far == pytest.approx(outcome.mfe_max)
    assert last_snap.mae_min_so_far == pytest.approx(outcome.mae_min)
    assert last_snap.mae_max_so_far == pytest.approx(outcome.mae_max)


def test_breakout_open_gating_scenarios():
    """Verify breakout order open gating: below SL, outside band, and inside band."""
    sig_bo = SignalRecord(
        signal_id="sig-bo-gating-01",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        signal="WAIT_FOR_BREAKOUT",
        status="WAIT_FOR_BREAKOUT",
        entry_policy="BREAKOUT",
        entry_low=105.0,
        entry_high=107.0,
        tp_price=115.0,
        sl_price=95.0,
        max_holding_days=5,
        predicted_probability=0.8,
        score=90.0,
        model_version="v1",
        max_entry_deviation_pct=0.05,
    )

    # 1. Trigger day open above TP (116.0 >= 115.0) -> INVALIDATED_GAP
    bars_open_above_tp = [
        _make_bar(date(2026, 1, 2), open_=116.0, high=118.0, low=114.0, close=117.0),
    ]
    eng = OutcomeEngine()
    out1, snaps1 = eng.evaluate_signal(sig_bo, bars_open_above_tp)
    assert out1 is not None
    assert out1.outcome_status == "INVALIDATED_GAP"
    assert out1.entry_status == "UNFILLED"
    assert out1.entry_price is None
    assert len(snaps1) == 0

    # 2. Trigger day open outside band (108.0 > entry_high 107.0) but dev = 2.86% <= 5%
    bars_open_above_band = [
        _make_bar(date(2026, 1, 2), open_=108.0, high=110.0, low=107.5, close=109.0),
    ]
    # Under enforce_entry_band=True -> INVALIDATED_GAP
    eng_strict = OutcomeEngine(enforce_entry_band=True)
    out2_strict, snaps2_strict = eng_strict.evaluate_signal(sig_bo, bars_open_above_band)
    assert out2_strict is not None
    assert out2_strict.outcome_status == "INVALIDATED_GAP"
    assert out2_strict.entry_status == "UNFILLED"
    assert out2_strict.entry_price is None
    assert len(snaps2_strict) == 0

    # Under enforce_entry_band=False (default MOO) -> fills at open 108.0
    eng_lax = OutcomeEngine(enforce_entry_band=False)
    out2_lax, snaps2_lax = eng_lax.evaluate_signal(sig_bo, bars_open_above_band)
    assert out2_lax is not None
    assert out2_lax.entry_status == "FILLED"
    assert out2_lax.entry_price == pytest.approx(108.0)
    assert out2_lax.entry_deviation_pct == pytest.approx((108.0 - 105.0) / 105.0)
    assert len(snaps2_lax) == 1

    # 3. Trigger day open inside band (106.0 in [105.0, 107.0]) -> fills under both
    bars_open_inside_band = [
        _make_bar(date(2026, 1, 2), open_=106.0, high=109.0, low=105.5, close=108.0),
    ]
    out3_strict, snaps3_strict = eng_strict.evaluate_signal(sig_bo, bars_open_inside_band)
    assert out3_strict is not None
    assert out3_strict.entry_status == "FILLED"
    assert out3_strict.entry_price == pytest.approx(106.0)
    assert len(snaps3_strict) == 1
