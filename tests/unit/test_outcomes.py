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

    # Conservative exits at sl_price (102.0), NOT at open (101.0)
    engine_cons = OutcomeEngine(ambiguity_policy="conservative")
    out_cons, _ = engine_cons.evaluate_signal(signal, [bar])
    assert out_cons is not None
    assert out_cons.outcome_status == "SL"
    assert out_cons.exit_price == 102.0

    # Optimistic resolves to TP (112.0)
    engine_opt = OutcomeEngine(ambiguity_policy="optimistic")
    out_opt, _ = engine_opt.evaluate_signal(signal, [bar])
    assert out_opt is not None
    assert out_opt.outcome_status == "TP"
    assert out_opt.exit_price == pytest.approx(112.0)

    # Ambiguous resolves to AMBIGUOUS at close (114.0)
    engine_ambig = OutcomeEngine(ambiguity_policy="ambiguous")
    out_ambig, _ = engine_ambig.evaluate_signal(signal, [bar])
    assert out_ambig is not None
    assert out_ambig.outcome_status == "AMBIGUOUS"
    assert out_ambig.exit_price == pytest.approx(114.0)


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

    # MFE / MAE in price and percentage
    assert outcome.mfe == pytest.approx(0.11)  # (111 - 100) / 100
    assert outcome.mae == pytest.approx(-0.03)  # (97 - 100) / 100
    assert outcome.mfe_price == pytest.approx(11.0)
    assert outcome.mae_price == pytest.approx(-3.0)

    # Time to events
    assert outcome.time_to_peak == 3  # High 111 occurred on Day 3
    assert outcome.time_to_tp == 3
    assert outcome.time_to_sl is None

    # Net return after transaction costs (buy 0.15%, sell 0.25%)
    expected_net = ((110.0 * (1.0 - 0.0025)) / (100.0 * (1.0 + 0.0015))) - 1.0
    assert outcome.net_return == pytest.approx(expected_net)


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
    assert outcome.realized_return is None
    assert outcome.exit_date == date(2026, 1, 4)
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
        entry_date=date(2026, 1, 2),
        entry_price=105.0,
        entry_status="UNFILLED",
        outcome_status="UNFILLED_EXPIRED",
        holding_days=0,
        exit_date=date(2026, 1, 6),
    )
    repo.save_outcomes([out_fill, out_unfill])

    f1 = repo.get_outcome_by_signal_id("sig-stat-fill")
    assert f1 is not None
    assert f1.entry_status == "FILLED"

    f2 = repo.get_outcome_by_signal_id("sig-stat-unfill")
    assert f2 is not None
    assert f2.entry_status == "UNFILLED"





