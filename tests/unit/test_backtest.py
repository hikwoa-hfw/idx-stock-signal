from datetime import date

import pytest

from python.backtest.engine import BacktestEngine
from python.backtest.metrics import (
    calculate_barrier_rates,
    calculate_cagr,
    calculate_expectancy,
    calculate_holding_period,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_win_rate,
)
from python.common.types import (
    BacktestConfig,
    DailyBar,
    EquityPoint,
    Signal,
    SignalAction,
    TradeRecord,
)


def _make_bar(ticker: str, d: date, o: float, h: float, low_val: float, c: float) -> DailyBar:
    return DailyBar(
        ticker=ticker,
        date=d,
        open=o,
        high=h,
        low=low_val,
        close=c,
        volume=1_000_000.0,
    )


def test_backtest_config_validation():
    # Valid default config
    cfg = BacktestConfig()
    assert cfg.initial_capital == 100_000_000.0
    assert cfg.max_concurrent_positions == 5
    assert cfg.lot_size == 100

    # Invalid initial capital
    with pytest.raises(ValueError, match="initial_capital"):
        BacktestConfig(initial_capital=-1000)

    # Invalid commissions
    with pytest.raises(ValueError, match="Commission"):
        BacktestConfig(commission_buy=-0.01)

    # Invalid slippage
    with pytest.raises(ValueError, match="slippage_bps"):
        BacktestConfig(slippage_bps=-5.0)

    # Invalid max concurrent positions
    with pytest.raises(ValueError, match="max_concurrent_positions"):
        BacktestConfig(max_concurrent_positions=0)

    # Invalid lot size
    with pytest.raises(ValueError, match="lot_size"):
        BacktestConfig(lot_size=0)

    # Invalid probability threshold
    with pytest.raises(ValueError, match="probability_threshold"):
        BacktestConfig(probability_threshold=1.5)

    # Invalid sizing method
    with pytest.raises(ValueError, match="Invalid position_sizing_method"):
        BacktestConfig(position_sizing_method="unsupported_method")

    # Invalid ambiguity policy
    with pytest.raises(ValueError, match="Invalid ambiguity_policy"):
        BacktestConfig(ambiguity_policy="yolo")


def test_metrics_win_rate_and_profit_factor():
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 5)

    # Empty trades
    assert calculate_win_rate([]) == 0.0
    assert calculate_profit_factor([]) == 0.0
    assert calculate_expectancy([]) == 0.0

    t1 = TradeRecord(
        trade_id="1",
        ticker="BBCA",
        signal_date=d1,
        entry_date=d1,
        exit_date=d2,
        shares=1000,
        entry_price=1000.0,
        exit_price=1050.0,
        position_value=1_000_000.0,
        entry_fee=1500.0,
        exit_fee=2625.0,
        slippage_cost=1000.0,
        gross_pnl=50_000.0,
        net_pnl=44_875.0,
        net_return=0.0448,
        exit_reason="TP",
        holding_days=4,
    )
    t2 = TradeRecord(
        trade_id="2",
        ticker="BBRI",
        signal_date=d1,
        entry_date=d1,
        exit_date=d2,
        shares=1000,
        entry_price=1000.0,
        exit_price=980.0,
        position_value=1_000_000.0,
        entry_fee=1500.0,
        exit_fee=2450.0,
        slippage_cost=1000.0,
        gross_pnl=-20_000.0,
        net_pnl=-24_950.0,
        net_return=-0.0249,
        exit_reason="SL",
        holding_days=2,
    )

    trades = [t1, t2]
    assert pytest.approx(calculate_win_rate(trades)) == 0.5
    assert pytest.approx(calculate_profit_factor(trades)) == 44875.0 / 24950.0
    assert pytest.approx(calculate_expectancy(trades)) == (0.0448 - 0.0249) / 2.0
    assert calculate_holding_period(trades) == 3.0

    tp_r, sl_r, exp_r = calculate_barrier_rates(trades)
    assert tp_r == 0.5
    assert sl_r == 0.5
    assert exp_r == 0.0

    # All wins -> profit factor inf
    assert calculate_profit_factor([t1]) == float("inf")

    # All losses -> profit factor 0.0
    assert calculate_profit_factor([t2]) == 0.0


def test_metrics_max_drawdown():
    assert calculate_max_drawdown([]) == (0.0, 0.0)

    # Single point
    p1 = EquityPoint(
        date=date(2026, 1, 1),
        cash=100_000.0,
        positions_value=0.0,
        total_equity=100_000.0,
    )
    assert calculate_max_drawdown([p1]) == (0.0, 0.0)

    curve = [
        EquityPoint(date=date(2026, 1, 1), cash=100.0, positions_value=0.0, total_equity=100.0),
        EquityPoint(date=date(2026, 1, 2), cash=120.0, positions_value=0.0, total_equity=120.0),
        EquityPoint(date=date(2026, 1, 3), cash=90.0, positions_value=0.0, total_equity=90.0),
        EquityPoint(date=date(2026, 1, 4), cash=110.0, positions_value=0.0, total_equity=110.0),
        EquityPoint(date=date(2026, 1, 5), cash=130.0, positions_value=0.0, total_equity=130.0),
        EquityPoint(date=date(2026, 1, 6), cash=104.0, positions_value=0.0, total_equity=104.0),
    ]

    mdd_pct, mdd_amt = calculate_max_drawdown(curve)
    assert pytest.approx(mdd_pct) == 30.0 / 120.0
    assert pytest.approx(mdd_amt) == 30.0


def test_metrics_cagr():
    s_date = date(2025, 1, 1)
    e_date = date(2026, 1, 1)
    # 1 year doubling = 100% CAGR
    cagr = calculate_cagr(100.0, 200.0, s_date, e_date)
    assert cagr is not None
    assert pytest.approx(cagr, rel=0.01) == 1.0

    # Same date or negative period
    assert calculate_cagr(100.0, 200.0, s_date, s_date) is None
    assert calculate_cagr(0.0, 200.0, s_date, e_date) is None


def test_simulation_strict_causality_and_no_lookahead():
    """Verifies Day t signal generates order filled on Day t+1 open, never on Day t."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1020.0, 990.0, 1010.0),
        _make_bar("BBCA", d1, 1050.0, 1060.0, 1040.0, 1055.0),
        _make_bar("BBCA", d2, 1060.0, 1070.0, 1050.0, 1065.0),
    ]

    # Signal produced on Day d0 (close of Day d0)
    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1010.0,
        target_price=1100.0,
        stop_loss=950.0,
        probability=0.85,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        tp_pct=0.20,
        sl_pct=0.20,
        max_holding_days=5,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=bars, signals=[sig])

    assert len(report.trades) == 1
    trade = report.trades[0]
    # Trade must have entered on d1, NOT on d0!
    assert trade.signal_date == d0
    assert trade.entry_date == d1
    # Entry price must be d1 open (1050.0), NOT d0 close (1010.0)!
    assert trade.entry_price == 1050.0


def test_take_profit_hit():
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        # Day 1: Entry at 1000.0. TP = 5% = 1050.0. High is 1020 (no hit)
        _make_bar("BBCA", d1, 1000.0, 1020.0, 990.0, 1010.0),
        # Day 2: High reaches 1060.0 >= 1050.0 -> TP HIT!
        _make_bar("BBCA", d2, 1010.0, 1060.0, 1005.0, 1055.0),
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.75,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=5,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=bars, signals=[sig])

    assert report.total_trades == 1
    trade = report.trades[0]
    assert trade.exit_reason == "TP"
    assert trade.exit_date == d2
    assert trade.exit_price == 1050.0
    assert trade.net_pnl > 0


def test_stop_loss_hit():
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        # Day 1: Entry at 1000.0. SL = 2% = 980.0. Low is 990 (no hit)
        _make_bar("BBCA", d1, 1000.0, 1010.0, 990.0, 995.0),
        # Day 2: Low reaches 970.0 <= 980.0 -> SL HIT!
        _make_bar("BBCA", d2, 995.0, 1000.0, 970.0, 975.0),
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.75,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=5,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=bars, signals=[sig])

    assert report.total_trades == 1
    trade = report.trades[0]
    assert trade.exit_reason == "SL"
    assert trade.exit_date == d2
    assert trade.exit_price == 980.0
    assert trade.net_pnl < 0


def test_ambiguous_candle_policy():
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    # Day 2 touches both TP (1050) and SL (980): High=1060, Low=970
    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1020.0, 990.0, 1000.0),
        _make_bar("BBCA", d2, 1000.0, 1060.0, 970.0, 1010.0),
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.75,
        model_version="v1",
    )

    # Conservative -> SL hit
    cfg_cons = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        ambiguity_policy="conservative",
    )
    report_cons = BacktestEngine(config=cfg_cons).run(bars=bars, signals=[sig])
    assert report_cons.trades[0].exit_reason == "SL"

    # Optimistic -> TP hit
    cfg_opt = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        ambiguity_policy="optimistic",
    )
    report_opt = BacktestEngine(config=cfg_opt).run(bars=bars, signals=[sig])
    assert report_opt.trades[0].exit_reason == "TP"

    # Ambiguous -> AMBIGUOUS hit
    cfg_amb = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
        ambiguity_policy="ambiguous",
    )
    report_amb = BacktestEngine(config=cfg_amb).run(bars=bars, signals=[sig])
    assert report_amb.trades[0].exit_reason == "AMBIGUOUS"


def test_max_concurrent_positions_constraint():
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    bars = []
    for t in tickers:
        bars.append(_make_bar(t, d0, 1000.0, 1020.0, 990.0, 1000.0))
        bars.append(_make_bar(t, d1, 1000.0, 1020.0, 990.0, 1000.0))
        bars.append(_make_bar(t, d2, 1000.0, 1020.0, 990.0, 1000.0))

    signals = [
        Signal(
            ticker=t,
            signal_date=d0,
            action=SignalAction.BUY,
            entry_price=1000.0,
            target_price=1050.0,
            stop_loss=980.0,
            probability=0.70 + i * 0.05,
            model_version="v1",
        )
        for i, t in enumerate(tickers)
    ]

    # Limit to max 2 concurrent positions
    cfg = BacktestConfig(
        initial_capital=100_000_000.0,
        max_concurrent_positions=2,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=bars, signals=signals)

    # Only top 2 signals should have been opened
    assert len(report.trades) == 2
    # Highest probability signals were ASII (0.90) and TLKM (0.85)
    executed_tickers = {t.ticker for t in report.trades}
    assert executed_tickers == {"ASII", "TLKM"}


def test_fees_slippage_and_cash_accounting_invariant():
    """Mathematical invariant: final_equity == initial_capital + total_net_pnl."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1020.0, 990.0, 1000.0),
        _make_bar("BBCA", d2, 1020.0, 1060.0, 1010.0, 1050.0),  # TP hit at 1050
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.80,
        model_version="v1",
    )

    init_cap = 50_000_000.0
    cfg = BacktestConfig(
        initial_capital=init_cap,
        commission_buy=0.0015,
        commission_sell=0.0025,
        slippage_bps=10.0,
        tp_pct=0.05,
        sl_pct=0.02,
        lot_size=100,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=bars, signals=[sig])

    assert len(report.trades) == 1
    trade = report.trades[0]

    # Verify lot size compliance
    assert trade.shares % 100 == 0
    assert trade.shares > 0

    # Verify net_pnl formula
    expected_net_pnl = trade.gross_pnl - (trade.entry_fee + trade.exit_fee) - trade.slippage_cost
    assert pytest.approx(trade.net_pnl) == expected_net_pnl

    # Invariant: final equity equals initial capital plus sum of all net pnl
    assert pytest.approx(report.final_equity) == init_cap + trade.net_pnl
    assert pytest.approx(report.total_net_pnl) == trade.net_pnl


def test_lot_size_enforcement_and_insufficient_funds():
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)

    # Stock costs 100,000 per share, so 1 lot (100 shares) costs 10,000,000 IDR
    bars = [
        _make_bar("HIGH_P", d0, 100_000.0, 101_000.0, 99_000.0, 100_000.0),
        _make_bar("HIGH_P", d1, 100_000.0, 101_000.0, 99_000.0, 100_000.0),
    ]

    sig = Signal(
        ticker="HIGH_P",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=100_000.0,
        target_price=105_000.0,
        stop_loss=98_000.0,
        probability=0.80,
        model_version="v1",
    )

    # Initial capital is only 1,000,000 IDR -> Cannot afford 1 lot (10,000,000)
    cfg = BacktestConfig(
        initial_capital=1_000_000.0,
        lot_size=100,
    )
    report = BacktestEngine(config=cfg).run(bars=bars, signals=[sig])

    # No trade can be taken due to lot size constraint
    assert report.total_trades == 0
    assert report.final_equity == 1_000_000.0


def test_expiry_barrier_hit():
    """Section 50 acceptance test: max_holding_days reached with neither TP nor SL hit -> EXPIRY."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)

    # TP = 1050, SL = 980. High never reaches 1050, Low never drops below 980.
    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1010.0, 990.0, 1005.0),  # Day 1: enter at 1000
        _make_bar("BBCA", d2, 1005.0, 1015.0, 995.0, 1010.0),  # Day 2: held
        _make_bar("BBCA", d3, 1010.0, 1020.0, 995.0, 1015.0),  # Day 3: max holding reached (3 days)
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.80,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        max_holding_days=3,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    report = BacktestEngine(config=cfg).run(bars=bars, signals=[sig])

    assert report.total_trades == 1
    trade = report.trades[0]
    assert trade.exit_reason == "EXPIRY"
    assert trade.exit_date == d3
    assert trade.holding_days == 3
    assert trade.exit_price == 1015.0


def test_custom_config_barrier_percentages():
    """Custom tp_pct and sl_pct provided in BacktestConfig are respected by engine."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1010.0, 990.0, 1000.0),
        # Day 2 High reaches 1025. Standard default tp_pct is 0.05 (1050),
        # but configured tp_pct is 0.02 (1020).
        _make_bar("BBCA", d2, 1000.0, 1025.0, 990.0, 1020.0),
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1020.0,
        stop_loss=950.0,
        probability=0.85,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        tp_pct=0.02,  # Configured TP at +2% instead of default +5%
        sl_pct=0.05,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    report = BacktestEngine(config=cfg).run(bars=bars, signals=[sig])

    assert report.total_trades == 1
    trade = report.trades[0]
    assert trade.exit_reason == "TP"
    assert trade.exit_price == 1020.0


def test_zero_volume_suspension_prevents_entry():
    """An order must not fill on a day where stock has zero volume / is suspended."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)

    bar_d0 = _make_bar("SUSP", d0, 1000.0, 1010.0, 990.0, 1000.0)
    bar_d1_suspended = DailyBar(
        ticker="SUSP",
        date=d1,
        open=1000.0,
        high=1000.0,
        low=1000.0,
        close=1000.0,
        volume=0.0,  # Zero volume -> trading suspended
    )

    sig = Signal(
        ticker="SUSP",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.90,
        model_version="v1",
    )

    report = BacktestEngine().run(bars=[bar_d0, bar_d1_suspended], signals=[sig])
    assert report.total_trades == 0


def test_zero_volume_suspension_mtm_no_reversion():
    """When a stock is suspended on Day 3, EOD MTM must maintain last close,
    not revert to entry price.
    """
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)

    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1020.0, 990.0, 1000.0),  # Enters at 1000
        _make_bar("BBCA", d2, 1010.0, 1040.0, 1005.0, 1030.0),  # Rises to 1030
        DailyBar(
            ticker="BBCA",
            date=d3,
            open=1030.0,
            high=1030.0,
            low=1030.0,
            close=1030.0,
            volume=0.0,  # Suspended on Day 3
        ),
    ]

    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1100.0,
        stop_loss=950.0,
        probability=0.85,
        model_version="v1",
    )

    cfg = BacktestConfig(
        initial_capital=10_000_000.0,
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    report = BacktestEngine(config=cfg).run(bars=bars, signals=[sig])

    # Day 2 total equity should be greater than initial capital
    eq_d2 = report.equity_curve[2]
    # Day 3 (suspended) total equity should match Day 2, NOT artificially drop back to entry price
    eq_d3 = report.equity_curve[3]
    assert pytest.approx(eq_d2.total_equity) == eq_d3.total_equity


def test_drawdown_calculation_with_day_one_loss():
    """Drawdown must accurately capture an initial drop below initial capital on Day 1."""
    curve = [
        EquityPoint(
            date=date(2026, 1, 1),
            cash=90_000_000.0,
            positions_value=0.0,
            total_equity=90_000_000.0,
        ),
        EquityPoint(
            date=date(2026, 1, 2),
            cash=85_000_000.0,
            positions_value=0.0,
            total_equity=85_000_000.0,
        ),
    ]
    # Starting from initial capital 100M, dropping to 85M is 15M / 15% drawdown
    mdd_pct, mdd_amt = calculate_max_drawdown(curve, initial_capital=100_000_000.0)
    assert pytest.approx(mdd_pct) == 0.15
    assert pytest.approx(mdd_amt) == 15_000_000.0


def test_fixed_fractional_and_equal_weight_sizing():
    """Verify position sizing calculations for fixed_fractional and equal_weight."""
    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    bars = [
        _make_bar("BBCA", d0, 1000.0, 1010.0, 990.0, 1000.0),
        _make_bar("BBCA", d1, 1000.0, 1010.0, 990.0, 1000.0),
    ]
    sig = Signal(
        ticker="BBCA",
        signal_date=d0,
        action=SignalAction.BUY,
        entry_price=1000.0,
        target_price=1050.0,
        stop_loss=980.0,
        probability=0.85,
        model_version="v1",
    )

    # fixed_fractional with 20% of 100M = 20M / 1000 = 20,000 shares
    cfg_ff = BacktestConfig(
        initial_capital=100_000_000.0,
        max_position_pct=0.20,
        position_sizing_method="fixed_fractional",
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    rep_ff = BacktestEngine(config=cfg_ff).run(bars=bars, signals=[sig])
    assert rep_ff.trades[0].shares == 20_000

    # equal_weight with max_concurrent_positions=10 -> 10% of 100M = 10M / 1000 = 10,000 shares
    cfg_ew = BacktestConfig(
        initial_capital=100_000_000.0,
        max_concurrent_positions=10,
        max_position_pct=0.50,
        position_sizing_method="equal_weight",
        commission_buy=0.0,
        commission_sell=0.0,
        slippage_bps=0.0,
    )
    rep_ew = BacktestEngine(config=cfg_ew).run(bars=bars, signals=[sig])
    assert rep_ew.trades[0].shares == 10_000
