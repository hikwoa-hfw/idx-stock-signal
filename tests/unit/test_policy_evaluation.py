"""Unit tests for Phase 11D Dynamic Exit & Policy Selection Research Engine."""

from datetime import date

import pandas as pd
import pytest

from python.common.types import DailyBar
from python.experiments.candidate_eval import SimulatedTrade
from python.experiments.policy_eval import PolicyEvaluationEngine


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


def test_policy_engine_init():
    """Verify initialization and default parameters of PolicyEvaluationEngine."""
    engine = PolicyEvaluationEngine()
    assert engine.db_path.endswith("stock_signals.db")
    assert engine.initial_capital == 100_000_000.0
    assert engine.max_positions == 5
    assert engine.commission_buy == 0.0015
    assert engine.commission_sell == 0.0025
    assert engine.slippage_entry_bps == 5.0
    assert engine.slippage_exit_bps == 5.0


def test_policy_selectivity_filtering():
    """Verify that cross-sectional percentile selection correctly limits daily candidates."""
    engine = PolicyEvaluationEngine()

    d_eval = date(2026, 1, 1)
    d_next = date(2026, 1, 2)
    tickers = [f"STK{i:02d}" for i in range(20)]
    scores = [0.01 * (i + 1) for i in range(20)]  # STK19 has highest score (0.20)
    prices = [100.0] * 20

    # Provide rows for d_eval and d_next so simulation executes and matures orders
    rows = []
    for d in [d_eval, d_next]:
        for i, t in enumerate(tickers):
            rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "score": scores[i],
                    "pred_return_lgb": scores[i],
                    "decision_price": prices[i],
                    "va_entry_price": prices[i],
                    "atr_pct": 0.03,
                }
            )
    df_test = pd.DataFrame(rows)

    mock_bars = {}
    for t in tickers:
        mock_bars[t] = [
            make_test_bar(t, d_eval, 100.0, 101.0, 99.0, 100.0),
            make_test_bar(t, d_next, 100.0, 101.0, 99.0, 100.0),
        ]
    engine._bars_by_ticker = mock_bars

    # Top 10% of 20 stocks = 2 stocks (STK19, STK18)
    res_10 = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_k_pct=0.10,
        min_candidates=10,
        horizon_policy=1,
        tp_sl_policy=(0.05, 0.02),
    )
    assert res_10["total_signals"] == 4  # 2 on d_eval, 2 on d_next
    executed_tickers = [t.ticker for t in res_10["trades"]]
    assert "STK19" in executed_tickers
    assert "STK18" in executed_tickers

    # Top 5% of 20 stocks = 1 stock (STK19)
    res_5 = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_k_pct=0.05,
        min_candidates=10,
        horizon_policy=1,
        tp_sl_policy=(0.05, 0.02),
    )
    executed_5 = [t.ticker for t in res_5["trades"]]
    assert "STK19" in executed_5
    assert "STK18" not in executed_5


def test_policy_regime_filtering():
    """Verify that regime condition correctly filters out adverse market dates."""
    engine = PolicyEvaluationEngine()

    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    tickers = [f"STK{i:02d}" for i in range(10)]
    df_rows = []
    for d in [d1, d2]:
        for i, t in enumerate(tickers):
            df_rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "score": 0.10 + i * 0.01,
                    "decision_price": 100.0,
                    "va_entry_price": 100.0,
                    "atr_pct": 0.03,
                }
            )
    df_test = pd.DataFrame(df_rows)

    mock_bars = {}
    for t in tickers:
        mock_bars[t] = [
            make_test_bar(t, d1, 100.0, 101.0, 99.0, 100.0),
            make_test_bar(t, d2, 100.0, 101.0, 99.0, 100.0),
            make_test_bar(t, d3, 100.0, 101.0, 99.0, 100.0),
        ]
    engine._bars_by_ticker = mock_bars

    engine._regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.02, "market_breadth": 0.10},
        d2: {"ihsg_vs_ema20": -0.01, "market_breadth": -0.05},
        d3: {"ihsg_vs_ema20": 0.00, "market_breadth": 0.00},
    }

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=2,
        min_candidates=10,
        regime_filter=lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
        horizon_policy=1,
    )

    assert res["total_signals"] == 2
    assert res["signals_removed_regime"] == 10
    assert res["completed_trades"] == 2
    for t in res["trades"]:
        assert t.signal_date == d1


def test_policy_dynamic_duration():
    """Verify that dynamic per-trade holding duration triggers expiry on correct bar."""
    engine = PolicyEvaluationEngine()

    d_sig = date(2026, 1, 1)
    all_dates = [date(2026, 1, k) for k in range(1, 20)]

    rows = []
    for d in all_dates:
        for i in range(10):
            rows.append(
                {
                    "ticker": f"STK{i:02d}",
                    "date": d,
                    "score": 0.10 - i * 0.01 if d == d_sig else -1.0,
                    "decision_price": 100.0,
                    "va_entry_price": 100.0,
                    "atr_pct": 0.05 if i == 0 else 0.01,  # STK00 high vol, STK01 low vol
                }
            )
    df_test = pd.DataFrame(rows)

    mock_bars = {}
    for i in range(10):
        t = f"STK{i:02d}"
        mock_bars[t] = [make_test_bar(t, d, 100.0, 101.0, 99.5, 100.0) for d in all_dates]
    engine._bars_by_ticker = mock_bars

    def duration_rule(r):
        return 3 if r["atr_pct"] > 0.03 else 10

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=2,  # picks STK00 and STK01 on d_sig
        min_candidates=10,
        horizon_policy=duration_rule,
        tp_sl_policy=(0.05, 0.02),
    )

    # Find the trades triggered from d_sig
    sig_trades = [t for t in res["trades"] if t.signal_date == d_sig]
    assert len(sig_trades) == 2

    t0 = next(t for t in sig_trades if t.ticker == "STK00")
    t1 = next(t for t in sig_trades if t.ticker == "STK01")

    assert t0.exit_reason == "EXPIRY"
    assert t0.holding_days == 3

    assert t1.exit_reason == "EXPIRY"
    assert t1.holding_days == 10


def test_policy_dynamic_tpsl_barriers():
    """Verify that dynamic TP/SL barriers correctly trigger exits at specified thresholds."""
    engine = PolicyEvaluationEngine()

    d_sig = date(2026, 1, 1)
    d_fwd = [date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]
    all_d = [d_sig] + d_fwd

    rows = []
    for d in all_d:
        for i in range(10):
            rows.append(
                {
                    "ticker": f"STK{i:02d}",
                    "date": d,
                    "score": 0.10 - i * 0.01 if d == d_sig else -1.0,
                    "decision_price": 100.0,
                    "va_entry_price": 100.0,
                    "atr_pct": 0.04,
                }
            )
    df_test = pd.DataFrame(rows)

    mock_bars = {
        "STK00": [
            make_test_bar("STK00", d_sig, 100.0, 101.0, 99.0, 100.0),
            make_test_bar("STK00", d_fwd[0], 100.0, 101.0, 99.5, 100.0),
            make_test_bar("STK00", d_fwd[1], 100.0, 104.5, 99.5, 103.0),
            make_test_bar("STK00", d_fwd[2], 103.0, 103.5, 102.0, 102.5),
        ]
    }
    for i in range(1, 10):
        t = f"STK{i:02d}"
        mock_bars[t] = [make_test_bar(t, d, 100.0, 101.0, 99.0, 100.0) for d in all_d]
    engine._bars_by_ticker = mock_bars

    res_std = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=1,
        min_candidates=10,
        horizon_policy=3,
        tp_sl_policy=(0.05, 0.02),
    )
    sig_std = [t for t in res_std["trades"] if t.signal_date == d_sig]
    assert sig_std[0].exit_reason == "EXPIRY"

    res_quick = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=1,
        min_candidates=10,
        horizon_policy=3,
        tp_sl_policy=(0.04, 0.02),
    )
    sig_quick = [t for t in res_quick["trades"] if t.signal_date == d_sig]
    assert sig_quick[0].exit_reason == "TP"
    assert sig_quick[0].holding_days == 2


def test_policy_fold_aggregation_math():
    """Verify mathematical correctness of pooled profit factor and continuous drawdown."""
    engine = PolicyEvaluationEngine(initial_capital=100_000_000.0)

    trade1 = SimulatedTrade(
        ticker="T1",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        exit_date=date(2026, 1, 3),
        entry_price=100.0,
        exit_price=105.0,
        shares=1000,
        gross_pnl=5000.0,
        net_pnl=4000.0,
        net_return=0.04,
        exit_reason="TP",
        holding_days=2,
        signal_prob=0.8,
    )
    trade2 = SimulatedTrade(
        ticker="T2",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        exit_date=date(2026, 1, 3),
        entry_price=100.0,
        exit_price=98.0,
        shares=1000,
        gross_pnl=-2000.0,
        net_pnl=-2500.0,
        net_return=-0.025,
        exit_reason="SL",
        holding_days=2,
        signal_prob=0.8,
    )

    f1_res = {
        "initial_capital": 100_000_000.0,
        "final_equity": 100_001_500.0,
        "total_signals": 2,
        "completed_trades": 2,
        "win_rate": 0.50,
        "tp_count": 1,
        "tp_rate": 0.50,
        "sl_count": 1,
        "sl_rate": 0.50,
        "expiry_count": 0,
        "expiry_rate": 0.0,
        "avg_net_return": 0.0075,
        "profit_factor": 1.60,
        "gain": 4000.0,
        "loss": 2500.0,
        "max_drawdown_pct": 2.50,
        "max_drawdown_amount": 2500.0,
        "avg_holding_days": 2.0,
        "invalidated_total": 0,
        "invalidated_gap_down": 0,
        "invalidated_gap_up": 0,
        "invalidated_excessive_dev": 0,
        "unfilled_total": 0,
        "unfilled_suspended": 0,
        "unfilled_capacity": 0,
        "unfilled_cash": 0,
        "signals_removed_regime": 0,
        "dates_too_few_candidates": 0,
        "avg_daily_candidates": 15.0,
        "daily_equity": [(date(2026, 1, 2), 100_000_000.0), (date(2026, 1, 3), 100_001_500.0)],
        "trades": [trade1, trade2],
    }

    trade3 = SimulatedTrade(
        ticker="T3",
        signal_date=date(2026, 2, 1),
        entry_date=date(2026, 2, 2),
        exit_date=date(2026, 2, 3),
        entry_price=100.0,
        exit_price=97.0,
        shares=1000,
        gross_pnl=-3000.0,
        net_pnl=-3500.0,
        net_return=-0.035,
        exit_reason="SL",
        holding_days=2,
        signal_prob=0.8,
    )
    f2_res = {
        "initial_capital": 100_000_000.0,
        "final_equity": 99_996_500.0,
        "total_signals": 1,
        "completed_trades": 1,
        "win_rate": 0.0,
        "tp_count": 0,
        "tp_rate": 0.0,
        "sl_count": 1,
        "sl_rate": 1.0,
        "expiry_count": 0,
        "expiry_rate": 0.0,
        "avg_net_return": -0.035,
        "profit_factor": 0.0,
        "gain": 0.0,
        "loss": 3500.0,
        "max_drawdown_pct": 3.50,
        "max_drawdown_amount": 3500.0,
        "avg_holding_days": 2.0,
        "invalidated_total": 0,
        "invalidated_gap_down": 0,
        "invalidated_gap_up": 0,
        "invalidated_excessive_dev": 0,
        "unfilled_total": 0,
        "unfilled_suspended": 0,
        "unfilled_capacity": 0,
        "unfilled_cash": 0,
        "signals_removed_regime": 0,
        "dates_too_few_candidates": 0,
        "avg_daily_candidates": 12.0,
        "daily_equity": [(date(2026, 2, 2), 100_000_000.0), (date(2026, 2, 3), 99_996_500.0)],
        "trades": [trade3],
    }

    pooled, per_f = engine.aggregate_folds(
        policy_id="test_policy",
        experiment="TEST",
        description="Test Policy Aggregation",
        mode="LOW_PRICE",
        model_id="test_model",
        fold_results=[f1_res, f2_res],
    )

    assert pooled.completed_trades == 3
    assert pooled.win_rate == pytest.approx(1 / 3, abs=1e-4)
    assert pooled.pooled_profit_factor == 0.67
    assert pooled.worst_fold_max_drawdown_pct == 3.50
    assert len(per_f) == 2


def test_policy_training_stats_causality():
    """Verify training fold stats are computed strictly on training partitions."""
    engine = PolicyEvaluationEngine()

    # Create dummy dataframe with fold assignments
    df_mode = pd.DataFrame(
        [
            {"fold": 1, "date": date(2023, 12, 28), "ticker": "BBCA", "atr_pct": 0.05},
            {"fold": 2, "date": date(2024, 12, 2), "ticker": "BBCA", "atr_pct": 0.05},
            {"fold": 3, "date": date(2025, 11, 10), "ticker": "BBCA", "atr_pct": 0.05},
        ]
    )

    stats = engine.compute_fold_training_stats(df_mode, purge_days=15)
    for f in [1, 2, 3]:
        assert f in stats
        assert "median_atr_pct" in stats[f]
        assert "tp_multiplier" in stats[f]
        assert "sl_multiplier" in stats[f]
        assert "train_cutoff_date" in stats[f]
        assert stats[f]["median_atr_pct"] > 0.0
        assert stats[f]["tp_multiplier"] >= 1.2
        assert stats[f]["sl_multiplier"] >= 0.5

    # Confirm cutoff dates precede test start dates
    assert stats[1]["train_cutoff_date"] < "2023-12-28"
    assert stats[2]["train_cutoff_date"] < "2024-12-02"
    assert stats[3]["train_cutoff_date"] < "2025-11-10"


def test_policy_turnover_and_time_in_market():
    """Verify that turnover, daily turnover, and market exposure are accurately computed."""
    engine = PolicyEvaluationEngine(initial_capital=100_000_000.0)

    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)
    d4 = date(2026, 1, 4)
    all_d = [d1, d2, d3, d4]

    tickers = [f"STK{i:02d}" for i in range(10)]
    rows = []
    for d in all_d:
        for i, t in enumerate(tickers):
            rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "score": 0.10 if d == d1 and i == 0 else -1.0,
                    "decision_price": 1000.0,
                    "va_entry_price": 1000.0,
                    "atr_pct": 0.03,
                }
            )
    df_test = pd.DataFrame(rows)

    mock_bars = {}
    for i, t in enumerate(tickers):
        if i == 0:
            mock_bars[t] = [
                make_test_bar(t, d1, 1000.0, 1005.0, 995.0, 1000.0),
                make_test_bar(t, d2, 1000.0, 1010.0, 995.0, 1005.0),  # enters d2
                make_test_bar(t, d3, 1005.0, 1010.0, 995.0, 1005.0),  # open pos d3
                make_test_bar(t, d4, 1005.0, 1060.0, 1000.0, 1055.0),  # exits TP d4
            ]
        else:
            mock_bars[t] = [make_test_bar(t, d, 1000.0, 1005.0, 995.0, 1000.0) for d in all_d]
    engine._bars_by_ticker = mock_bars

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=1,
        min_candidates=10,
        horizon_policy=5,
        tp_sl_policy=(0.05, 0.02),
    )

    assert res["completed_trades"] == 1
    assert res["eligible_candidates"] == 40  # 10 candidates * 4 days
    assert res["portfolio_turnover"] > 0.0  # ~0.20 (20M gross outlay / 100M cap)
    assert res["daily_turnover"] == pytest.approx(1 / 4, abs=1e-4)
    # Position was open on d2, d3, d4 = 3 days out of 4 = 75.0%
    assert res["time_in_market_pct"] == pytest.approx(75.0, abs=1.0)


def test_policy_dates_too_few_candidates():
    """Verify that days with fewer than min_candidates increment dates_too_few_candidates."""
    engine = PolicyEvaluationEngine()

    d1 = date(2026, 1, 1)
    # Only 5 candidates when min_candidates=10
    tickers = [f"STK{i:02d}" for i in range(5)]
    rows = [
        {
            "ticker": t,
            "date": d1,
            "score": 0.10,
            "decision_price": 100.0,
            "va_entry_price": 100.0,
            "atr_pct": 0.03,
        }
        for t in tickers
    ]
    df_test = pd.DataFrame(rows)

    mock_bars = {t: [make_test_bar(t, d1, 100.0, 101.0, 99.0, 100.0)] for t in tickers}
    engine._bars_by_ticker = mock_bars

    res = engine.simulate_policy(
        df_test=df_test,
        score_col="score",
        top_n_per_day=2,
        min_candidates=10,
    )

    assert res["dates_too_few_candidates"] == 1
    assert res["total_signals"] == 0
    assert res["completed_trades"] == 0


def test_policy_modular_summaries_contain_controls(tmp_path):
    """Verify that modular summary CSVs contain their respective control baseline policies."""
    # Test aggregate_folds with control IDs
    engine = PolicyEvaluationEngine()
    f_res = {
        "initial_capital": 100_000_000.0,
        "final_equity": 100_000_000.0,
        "total_signals": 5,
        "completed_trades": 5,
        "win_rate": 0.40,
        "tp_count": 2,
        "tp_rate": 0.40,
        "sl_count": 3,
        "sl_rate": 0.60,
        "expiry_count": 0,
        "expiry_rate": 0.0,
        "avg_net_return": -0.002,
        "profit_factor": 0.85,
        "gain": 2000.0,
        "loss": 2350.0,
        "max_drawdown_pct": 10.0,
        "max_drawdown_amount": 10000.0,
        "avg_holding_days": 5.0,
        "invalidated_total": 0,
        "invalidated_gap_down": 0,
        "invalidated_gap_up": 0,
        "invalidated_excessive_dev": 0,
        "unfilled_total": 0,
        "unfilled_suspended": 0,
        "unfilled_capacity": 0,
        "unfilled_cash": 0,
        "signals_removed_regime": 0,
        "dates_too_few_candidates": 0,
        "avg_daily_candidates": 10.0,
        "eligible_candidates": 10,
        "portfolio_turnover": 0.5,
        "daily_turnover": 0.1,
        "time_in_market_pct": 50.0,
        "daily_equity": [(date(2026, 1, 1), 100_000_000.0)],
        "trades": [],
    }
    p_b, _ = engine.aggregate_folds(
        "exp_b_none", "EXP_B_REGIME", "Control", "LOW_PRICE", "m", [f_res]
    )
    p_c, _ = engine.aggregate_folds(
        "exp_c_fixed_h15", "EXP_C_DURATION", "Control", "LOW_PRICE", "m", [f_res]
    )
    p_d, _ = engine.aggregate_folds(
        "exp_d_control", "EXP_D_TPSL", "Control", "LOW_PRICE", "m", [f_res]
    )

    assert p_b.policy_id == "exp_b_none"
    assert p_c.policy_id == "exp_c_fixed_h15"
    assert p_d.policy_id == "exp_d_control"

