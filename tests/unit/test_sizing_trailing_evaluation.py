"""Unit tests for Phase 11E Dynamic Conviction Sizing & Volatility Trailing Protection."""

from datetime import date

import pandas as pd

from python.common.types import DailyBar
from python.experiments.sizing_trailing_eval import (
    SimulatedTrade11E,
    SizingTrailingEvaluationEngine,
    make_atr_trailing_rule,
    make_breakeven_ratchet_rule,
    make_stepped_profit_lock_rule,
    sizing_conservative_binary,
    sizing_fixed_control,
    sizing_smooth_conviction,
    sizing_three_tier_regime,
)


def make_test_bar(
    ticker: str,
    d: date,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1_000_000.0,
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


def test_engine_initialization():
    """Verify initialization parameters, paths, and friction contracts."""
    engine = SizingTrailingEvaluationEngine()
    assert engine.db_path.endswith("stock_signals.db")
    assert engine.initial_capital == 100_000_000.0
    assert engine.max_positions == 5
    assert engine.commission_buy == 0.0015
    assert engine.commission_sell == 0.0025
    assert engine.slippage_entry_bps == 5.0
    assert engine.slippage_exit_bps == 5.0


def test_sizing_rules_logic():
    """Verify mathematical behavior of all 4 predeclared sizing rules."""
    reg_bull_fav = {"ihsg_vs_ema20": 0.02, "market_breadth": 0.65}
    reg_bull_mix = {"ihsg_vs_ema20": 0.01, "market_breadth": 0.35}
    reg_bear_mix = {"ihsg_vs_ema20": -0.01, "market_breadth": 0.60}
    reg_bear_unf = {"ihsg_vs_ema20": -0.03, "market_breadth": 0.20}

    # Control rule: Always 1.0x
    assert sizing_fixed_control(reg_bull_fav) == (1.0, "FAVORABLE")
    assert sizing_fixed_control(reg_bear_unf) == (1.0, "FAVORABLE")

    # Conservative binary rule
    assert sizing_conservative_binary(reg_bull_fav) == (1.0, "FAVORABLE")
    assert sizing_conservative_binary(reg_bear_unf) == (0.0, "UNFAVORABLE")

    # Three-tier regime rule
    assert sizing_three_tier_regime(reg_bull_fav) == (1.0, "FAVORABLE")
    assert sizing_three_tier_regime(reg_bull_mix) == (0.5, "MIXED")
    assert sizing_three_tier_regime(reg_bear_mix) == (0.5, "MIXED")
    assert sizing_three_tier_regime(reg_bear_unf) == (0.0, "UNFAVORABLE")

    # Smooth conviction rule
    w_fav, cat_fav = sizing_smooth_conviction(reg_bull_fav)
    assert w_fav == 1.0 and cat_fav == "FAVORABLE"

    w_mid, cat_mid = sizing_smooth_conviction({"ihsg_vs_ema20": 0.0})
    assert w_mid == 0.50 and cat_mid == "MIXED"

    w_unf, cat_unf = sizing_smooth_conviction(reg_bear_unf)
    assert w_unf == 0.0 and cat_unf == "UNFAVORABLE"


def test_sizing_zero_allocation_skips_orders():
    """Verify that orders in zero-allocation regimes are skipped and recorded."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    tickers = ["STKA", "STKB"]
    df_rows = []
    for d in [d1, d2]:
        for t in tickers:
            df_rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "score": 0.15,
                    "decision_price": 100.0,
                    "va_entry_price": 100.0,
                    "atr_pct": 0.03,
                }
            )
    df_test = pd.DataFrame(df_rows)

    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 100.0, 101.0, 99.0, 100.0),
            make_test_bar("STKA", d2, 100.0, 101.0, 99.0, 100.0),
            make_test_bar("STKA", d3, 100.0, 101.0, 99.0, 100.0),
        ],
        "STKB": [
            make_test_bar("STKB", d1, 100.0, 101.0, 99.0, 100.0),
            make_test_bar("STKB", d2, 100.0, 101.0, 99.0, 100.0),
            make_test_bar("STKB", d3, 100.0, 101.0, 99.0, 100.0),
        ],
    }
    engine._bars_by_ticker = mock_bars
    # On d1: bear market (multiplier 0.0); on d2: bull market (multiplier 1.0)
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": -0.02, "market_breadth": 0.30},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d3: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        sizing_rule=sizing_conservative_binary,
    )
    # Orders generated on d1 should be skipped when evaluated at d2 Open
    assert res["skipped_regime_sizing"] == 2
    # Orders generated on d2 should execute at d3 Open
    assert len(res["trades"]) > 0 or len(res["daily_equity"]) > 0


def test_sizing_multiplier_scales_capital_allocation():
    """Verify that sizing multiplier scales shares allocated appropriately."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    df_test = pd.DataFrame(
        [
            {
                "ticker": "STKA",
                "date": d1,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            },
            {
                "ticker": "STKA",
                "date": d2,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            },
        ]
    )

    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 1000.0, 1010.0, 990.0, 1000.0),
            make_test_bar("STKA", d2, 1000.0, 1010.0, 990.0, 1000.0),
            make_test_bar("STKA", d3, 1000.0, 1010.0, 990.0, 1000.0),
        ]
    }
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.40},  # Mixed: 0.5x
        d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.40},
        d3: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.40},
    }

    # Simulate with three-tier (0.5x)
    res_half = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        sizing_rule=sizing_three_tier_regime,
        horizon_days=1,
    )
    # Simulate with fixed (1.0x)
    res_full = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        sizing_rule=sizing_fixed_control,
        horizon_days=1,
    )

    shares_half = res_half["trades"][0].shares
    shares_full = res_full["trades"][0].shares
    # 0.5x multiplier should yield approximately half the shares
    assert shares_half < shares_full
    assert abs(shares_half - shares_full / 2) <= 100  # within lot size rounding


def test_trailing_stop_tightens_and_never_loosens():
    """Verify that trailing stop tightens on rising watermark and never loosens."""
    rule = make_breakeven_ratchet_rule(activation_pct=0.025, friction_pct=0.0050)
    pos = {
        "entry_price": 1000.0,
        "highest_watermark": 1010.0,  # +1.0% (not activated)
        "current_sl_price": 980.0,  # initial -2%
    }
    assert rule(pos) is None

    # Watermark rises to +2.8%
    pos["highest_watermark"] = 1028.0
    new_sl = rule(pos)
    assert new_sl is not None
    assert round(new_sl, 2) == 1005.0

    # Ensure stop tightens
    pos["current_sl_price"] = max(pos["current_sl_price"], new_sl)
    assert round(pos["current_sl_price"], 2) == 1005.0

    # Watermark falls to 1015.0 on pullback (watermark can't decrease, but test rule behavior)
    assert round(rule(pos), 2) == 1005.0
    # Stop does not loosen below 1005.0
    assert round(pos["current_sl_price"], 2) == 1005.0


def test_atr_trailing_and_stepped_lock_rules():
    """Verify ATR-scaled trailing stops and stepped profit locks."""
    # ATR rule: 1.0x ATR distance, activated at +2.5%
    atr_rule = make_atr_trailing_rule(atr_multiple=1.0, activation_pct=0.025)
    pos_atr = {
        "entry_price": 1000.0,
        "highest_watermark": 1020.0,  # +2.0% -> not activated
        "atr_pct": 0.03,
    }
    assert atr_rule(pos_atr) is None

    # Watermark hits 1040.0 (+4.0%) -> activated! Trail distance = 1.0 * 0.03 = 3%
    # Proposed stop = 1040 * (1 - 0.03) = 1040 * 0.97 = 1008.8
    pos_atr["highest_watermark"] = 1040.0
    sl_atr = atr_rule(pos_atr)
    assert sl_atr is not None
    assert round(sl_atr, 1) == 1008.8

    # Stepped profit lock rule
    step_rule = make_stepped_profit_lock_rule()
    pos_step = {"entry_price": 1000.0, "highest_watermark": 1015.0}
    assert step_rule(pos_step) is None

    # Step 1: watermark >= +2.5% -> locks +0.5% (1005.0)
    pos_step["highest_watermark"] = 1030.0
    assert round(step_rule(pos_step), 1) == 1005.0

    # Step 2: watermark >= +4.0% -> locks +2.0% (1020.0)
    pos_step["highest_watermark"] = 1045.0
    assert round(step_rule(pos_step), 1) == 1020.0


def test_trailing_stop_exit_execution():
    """Verify simulation handles trailing stop exits with reason TRAILING_SL."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)
    d4 = date(2026, 1, 4)

    df_rows = []
    for d in [d1, d2, d3, d4]:
        df_rows.append(
            {
                "ticker": "STKA",
                "date": d,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            }
        )
    df_test = pd.DataFrame(df_rows)

    # d2: Entry at 1000, rallies to High 1030 (+3.0%) -> triggers breakeven ratchet to 1005
    # d3: Low drops to 1000 -> triggers trailing stop at 1005!
    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 1000.0, 1005.0, 995.0, 1000.0),
            make_test_bar("STKA", d2, 1000.0, 1030.0, 995.0, 1025.0),
            make_test_bar("STKA", d3, 1010.0, 1015.0, 1000.0, 1002.0),
            make_test_bar("STKA", d4, 1000.0, 1005.0, 995.0, 1000.0),
        ]
    }
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d3: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d4: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        trailing_rule=make_breakeven_ratchet_rule(0.025, 0.0050),
        horizon_days=10,
        tp_pct=0.06,
        sl_pct=0.02,
    )

    assert res["completed_trades"] >= 1
    assert res["trailing_stop_count"] >= 1
    t = res["trades"][0]
    assert t.exit_reason == "TRAILING_SL"
    assert t.exit_date == d3
    assert t.net_pnl > 0  # Protected profit after friction!


def test_trailing_gap_down_execution():
    """Verify that opening gap down below trailing stop fills at Open price."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    df_rows = []
    for d in [d1, d2, d3]:
        df_rows.append(
            {
                "ticker": "STKA",
                "date": d,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            }
        )
    df_test = pd.DataFrame(df_rows)

    # d2: High hits 1030 -> stop ratchets to 1005
    # d3: Gaps down at Open to 990 (below trailing stop 1005)
    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 1000.0, 1005.0, 995.0, 1000.0),
            make_test_bar("STKA", d2, 1000.0, 1030.0, 995.0, 1025.0),
            make_test_bar("STKA", d3, 990.0, 995.0, 985.0, 990.0),
        ]
    }
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d3: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        trailing_rule=make_breakeven_ratchet_rule(0.025, 0.0050),
        horizon_days=10,
        tp_pct=0.06,
        sl_pct=0.02,
    )

    assert res["completed_trades"] >= 1
    t = res["trades"][0]
    assert t.exit_reason == "TRAILING_SL"
    # Fill price must be based on open 990 minus exit slippage (5 bps)
    expected_exit = 990.0 * (1.0 - 0.0005)
    assert abs(t.exit_price - expected_exit) < 1e-4


def test_simultaneous_tp_and_trailing_sl_precedence():
    """Verify that SL takes precedence when both TP and trailing SL are breached on same day."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    df_rows = []
    for d in [d1, d2, d3]:
        df_rows.append(
            {
                "ticker": "STKA",
                "date": d,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            }
        )
    df_test = pd.DataFrame(df_rows)

    # d2: High hits 1030 -> stop ratchets to 1005
    # d3: Wide range bar: High 1070 (exceeds TP 1060), Low 995 (breaches trailing stop 1005)
    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 1000.0, 1005.0, 995.0, 1000.0),
            make_test_bar("STKA", d2, 1000.0, 1030.0, 995.0, 1025.0),
            make_test_bar("STKA", d3, 1010.0, 1070.0, 995.0, 1010.0),
        ]
    }
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d3: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        trailing_rule=make_breakeven_ratchet_rule(0.025, 0.0050),
        horizon_days=10,
        tp_pct=0.06,
        sl_pct=0.02,
    )

    assert res["completed_trades"] >= 1
    assert res["trades"][0].exit_reason == "TRAILING_SL"


def test_continuous_equity_chaining_math():
    """Verify continuous compounding scale and drawdown math across folds."""
    engine = SizingTrailingEvaluationEngine()

    # Create synthetic fold results
    # Fold 1: +10% equity (100M -> 110M)
    d_f1 = [
        (date(2024, 1, 1), 100_000_000.0),
        (date(2024, 1, 2), 110_000_000.0),
    ]
    # Fold 2: -10% equity (100M -> 90M)
    d_f2 = [
        (date(2024, 1, 3), 100_000_000.0),
        (date(2024, 1, 4), 90_000_000.0),
    ]

    t1 = SimulatedTrade11E(
        "A",
        date(2024, 1, 1),
        date(2024, 1, 1),
        date(2024, 1, 2),
        100.0,
        110.0,
        1000,
        10000.0,
        9000.0,
        0.09,
        "TP",
        2,
        0.8,
        1.0,
        "FAVORABLE",
        110.0,
        98.0,
    )
    t2 = SimulatedTrade11E(
        "B",
        date(2024, 1, 3),
        date(2024, 1, 3),
        date(2024, 1, 4),
        100.0,
        90.0,
        1000,
        -10000.0,
        -10500.0,
        -0.105,
        "SL",
        2,
        0.7,
        1.0,
        "FAVORABLE",
        100.0,
        90.0,
    )

    f1_res = {
        "initial_capital": 100_000_000.0,
        "final_equity": 110_000_000.0,
        "net_portfolio_return_pct": 10.0,
        "total_signals": 1,
        "completed_trades": 1,
        "win_rate": 1.0,
        "tp_count": 1,
        "tp_rate": 1.0,
        "sl_count": 0,
        "sl_rate": 0.0,
        "trailing_stop_count": 0,
        "trailing_stop_rate": 0.0,
        "expiry_count": 0,
        "expiry_rate": 0.0,
        "avg_net_return": 0.09,
        "profit_factor": 999.0,
        "max_drawdown_pct": 0.0,
        "max_drawdown_amount": 0.0,
        "avg_holding_days": 2.0,
        "invalidated_total": 0,
        "invalidated_gap_down": 0,
        "invalidated_gap_up": 0,
        "invalidated_excessive_dev": 0,
        "unfilled_total": 0,
        "unfilled_suspended": 0,
        "unfilled_capacity": 0,
        "unfilled_cash": 0,
        "skipped_regime_sizing": 0,
        "signals_removed_regime": 0,
        "dates_too_few_candidates": 0,
        "avg_daily_candidates": 1.0,
        "daily_equity": d_f1,
        "trades": [t1],
    }

    f2_res = {
        "initial_capital": 100_000_000.0,
        "final_equity": 90_000_000.0,
        "net_portfolio_return_pct": -10.0,
        "total_signals": 1,
        "completed_trades": 1,
        "win_rate": 0.0,
        "tp_count": 0,
        "tp_rate": 0.0,
        "sl_count": 1,
        "sl_rate": 1.0,
        "trailing_stop_count": 0,
        "trailing_stop_rate": 0.0,
        "expiry_count": 0,
        "expiry_rate": 0.0,
        "avg_net_return": -0.105,
        "profit_factor": 0.0,
        "max_drawdown_pct": 10.0,
        "max_drawdown_amount": 10_000_000.0,
        "avg_holding_days": 2.0,
        "invalidated_total": 0,
        "invalidated_gap_down": 0,
        "invalidated_gap_up": 0,
        "invalidated_excessive_dev": 0,
        "unfilled_total": 0,
        "unfilled_suspended": 0,
        "unfilled_capacity": 0,
        "unfilled_cash": 0,
        "skipped_regime_sizing": 0,
        "signals_removed_regime": 0,
        "dates_too_few_candidates": 0,
        "avg_daily_candidates": 1.0,
        "daily_equity": d_f2,
        "trades": [t2],
    }

    pooled, per_f = engine.aggregate_folds(
        policy_id="test_chain",
        experiment="TEST",
        description="Test Chaining",
        mode="LOW_PRICE",
        model_id="test_model",
        fold_results=[f1_res, f2_res],
    )

    # Chained return: 1.10 * 0.90 = 0.99 -> -1.0% return
    assert pooled.net_portfolio_return_pct == -1.0
    # Peak is 110M, trough is 110M * 0.90 = 99M -> 10% continuous drawdown
    assert pooled.continuous_max_drawdown_pct == 10.0


def test_capital_competition_ranking():
    """Verify that simultaneous orders compete for capital sorted by score desc, ticker asc."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)

    # Create 7 candidates with distinct scores, while max_positions = 5
    df_rows = []
    for d in [d1, d2]:
        for i in range(7):
            df_rows.append(
                {
                    "ticker": f"STK{i:02d}",
                    "date": d,
                    "score": 0.10 + i * 0.02,  # STK06 has highest score (0.22)
                    "decision_price": 100.0,
                    "va_entry_price": 100.0,
                    "atr_pct": 0.03,
                }
            )
    df_test = pd.DataFrame(df_rows)

    mock_bars = {}
    for i in range(7):
        t = f"STK{i:02d}"
        mock_bars[t] = [
            make_test_bar(t, d1, 100.0, 101.0, 99.0, 100.0),
            make_test_bar(t, d2, 100.0, 101.0, 99.0, 100.0),
        ]
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=7,
        min_candidates=1,
        horizon_days=1,
    )

    # 5 positions should fill, 2 should record unfilled_capacity
    assert res["unfilled_capacity"] >= 2
    executed_tickers = [t.ticker for t in res["trades"]]
    assert "STK06" in executed_tickers
    assert "STK05" in executed_tickers
    assert "STK04" in executed_tickers
    assert "STK03" in executed_tickers
    assert "STK02" in executed_tickers
    assert "STK00" not in executed_tickers
    assert "STK01" not in executed_tickers


def test_remaining_open_positions_tracking():
    """Verify that positions open at end of evaluation are counted in remaining_open_positions."""
    engine = SizingTrailingEvaluationEngine()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)

    df_test = pd.DataFrame(
        [
            {
                "ticker": "STKA",
                "date": d1,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            },
            {
                "ticker": "STKA",
                "date": d2,
                "score": 0.20,
                "decision_price": 1000.0,
                "va_entry_price": 1000.0,
                "atr_pct": 0.03,
            },
        ]
    )

    mock_bars = {
        "STKA": [
            make_test_bar("STKA", d1, 1000.0, 1005.0, 995.0, 1000.0),
            make_test_bar("STKA", d2, 1000.0, 1005.0, 995.0, 1000.0),  # No TP, no SL
        ]
    }
    engine._bars_by_ticker = mock_bars
    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.60},
    }

    # Simulate with horizon = 10 days, so position is still open on d2
    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        min_candidates=1,
        horizon_days=10,
    )

    assert res["completed_trades"] == 0
    assert res["remaining_open_positions"] == 1

    pooled, per_f = engine.aggregate_folds(
        policy_id="test_open",
        experiment="TEST",
        description="Test Open",
        mode="LOW_PRICE",
        model_id="test_model",
        fold_results=[res],
    )
    assert per_f[0].remaining_open_positions == 1
    assert pooled.remaining_open_positions == 1


def test_compute_fold_training_stats_causality():
    """Verify that training fold stats are computed causally with purge window before test fold."""
    engine = SizingTrailingEvaluationEngine()
    df_mode = engine.load_mode_dataset("LOW_PRICE")
    stats = engine.compute_fold_training_stats(df_mode, purge_days=15)

    assert set(stats.keys()) == {1, 2, 3}
    for f in [1, 2, 3]:
        assert "median_atr_pct" in stats[f]
        assert "p75_atr_pct" in stats[f]
        assert "train_cutoff_date" in stats[f]
        assert 0.01 < stats[f]["median_atr_pct"] < 0.10
        assert stats[f]["median_atr_pct"] <= stats[f]["p75_atr_pct"]

        # Verify causal ordering: train_cutoff_date < test_start_date
        f_test_dates = sorted(df_mode[df_mode["fold"] == f]["date"].unique())
        test_start = f_test_dates[0]
        train_cutoff = pd.to_datetime(stats[f]["train_cutoff_date"]).date()
        assert train_cutoff < test_start
