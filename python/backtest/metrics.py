import math
from datetime import date
from typing import Optional

from python.common.types import BacktestConfig, BacktestReport, EquityPoint, TradeRecord


def calculate_win_rate(trades: list[TradeRecord]) -> float:
    """Calculates fraction of trades with positive net PnL."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.net_pnl > 0)
    return float(wins / len(trades))


def calculate_profit_factor(trades: list[TradeRecord]) -> float:
    """Calculates Profit Factor = gross net profit / abs(gross net loss).

    Returns float('inf') if all trades win, 0.0 if no trades or all lose.
    """
    if not trades:
        return 0.0
    total_gain = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    total_loss = sum(abs(t.net_pnl) for t in trades if t.net_pnl < 0)

    if total_loss == 0.0:
        return float("inf") if total_gain > 0 else 0.0
    return float(total_gain / total_loss)


def calculate_expectancy(trades: list[TradeRecord]) -> float:
    """Calculates average net return per trade."""
    if not trades:
        return 0.0
    return float(sum(t.net_return for t in trades) / len(trades))


def calculate_max_drawdown(
    equity_curve: list[EquityPoint],
    initial_capital: Optional[float] = None,
) -> tuple[float, float]:
    """Calculates maximum drawdown in percentage and currency amount.

    Returns (max_drawdown_pct, max_drawdown_amount).
    """
    if not equity_curve:
        return 0.0, 0.0

    peak = (
        float(initial_capital)
        if initial_capital is not None and initial_capital > 0
        else equity_curve[0].total_equity
    )
    max_dd_amount = 0.0
    max_dd_pct = 0.0

    for pt in equity_curve:
        if pt.total_equity > peak:
            peak = pt.total_equity
        dd_amt = peak - pt.total_equity
        dd_pct = (dd_amt / peak) if peak > 0 else 0.0

        if dd_amt > max_dd_amount:
            max_dd_amount = dd_amt
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return float(max_dd_pct), float(max_dd_amount)


def calculate_holding_period(trades: list[TradeRecord]) -> float:
    """Calculates mean holding days across all completed trades."""
    if not trades:
        return 0.0
    return float(sum(t.holding_days for t in trades) / len(trades))


def calculate_barrier_rates(trades: list[TradeRecord]) -> tuple[float, float, float]:
    """Calculates (tp_rate, sl_rate, expiry_rate) fractions."""
    if not trades:
        return 0.0, 0.0, 0.0
    n = len(trades)
    tp_count = sum(1 for t in trades if t.exit_reason.upper() == "TP")
    sl_count = sum(1 for t in trades if t.exit_reason.upper() == "SL")
    exp_count = sum(1 for t in trades if t.exit_reason.upper() == "EXPIRY")
    return float(tp_count / n), float(sl_count / n), float(exp_count / n)


def calculate_cagr(
    initial_capital: float, final_equity: float, start_date: date, end_date: date
) -> Optional[float]:
    """Calculates Compound Annual Growth Rate (CAGR)."""
    days = (end_date - start_date).days
    if days < 1 or initial_capital <= 0 or final_equity <= 0:
        return None
    years = days / 365.25
    cagr = (final_equity / initial_capital) ** (1.0 / years) - 1.0
    if not math.isfinite(cagr):
        return None
    return float(cagr)


def compute_backtest_report(
    config: BacktestConfig,
    trades: list[TradeRecord],
    equity_curve: list[EquityPoint],
    start_date: date,
    end_date: date,
) -> BacktestReport:
    """Compiles complete BacktestReport aggregating all financial and performance metrics."""
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.net_pnl > 0)
    losing_trades = sum(1 for t in trades if t.net_pnl < 0)

    win_rate = calculate_win_rate(trades)
    profit_factor = calculate_profit_factor(trades)
    expectancy_pct = calculate_expectancy(trades)

    wins = [t.net_return for t in trades if t.net_pnl > 0]
    losses = [t.net_return for t in trades if t.net_pnl < 0]

    avg_win_pct = float(sum(wins) / len(wins)) if wins else 0.0
    avg_loss_pct = float(sum(losses) / len(losses)) if losses else 0.0

    if avg_loss_pct != 0.0:
        win_loss_ratio = float(abs(avg_win_pct / avg_loss_pct))
    else:
        win_loss_ratio = float("inf") if avg_win_pct > 0 else 0.0

    mdd_pct, mdd_amount = calculate_max_drawdown(
        equity_curve, initial_capital=config.initial_capital
    )
    avg_hold = calculate_holding_period(trades)
    tp_rate, sl_rate, expiry_rate = calculate_barrier_rates(trades)

    total_net_pnl = float(sum(t.net_pnl for t in trades))
    final_equity = (
        float(equity_curve[-1].total_equity)
        if equity_curve
        else float(config.initial_capital + total_net_pnl)
    )
    total_return_pct = float((final_equity - config.initial_capital) / config.initial_capital)
    cagr_pct = calculate_cagr(config.initial_capital, final_equity, start_date, end_date)

    return BacktestReport(
        config=config,
        start_date=start_date,
        end_date=end_date,
        initial_capital=config.initial_capital,
        final_equity=final_equity,
        total_net_pnl=total_net_pnl,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        average_win_pct=avg_win_pct,
        average_loss_pct=avg_loss_pct,
        win_loss_ratio=win_loss_ratio,
        profit_factor=profit_factor,
        expectancy_pct=expectancy_pct,
        max_drawdown_pct=mdd_pct,
        max_drawdown_amount=mdd_amount,
        average_holding_days=avg_hold,
        tp_rate=tp_rate,
        sl_rate=sl_rate,
        expiry_rate=expiry_rate,
        trades=trades,
        equity_curve=equity_curve,
    )
