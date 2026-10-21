"""Unit tests for Phase 11B.1 Candidate Model Training & Evaluation Engine."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from python.common.types import DailyBar
from python.experiments.candidate_eval import CandidateEvaluationRunner


def make_bar(
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


def test_candidate_specs_completeness():
    """Verify that candidate model specs match Phase 11A.1 ablation findings."""
    runner = CandidateEvaluationRunner()

    specs_low = runner.get_candidate_specs("LOW_PRICE")
    ids_low = [s.model_id for s in specs_low]
    assert "VA_lgb_full" in ids_low
    assert "VA_lgb_minus_trend" in ids_low
    assert "VA_logistic_baseline" in ids_low
    assert "VA_prevalence_baseline" in ids_low
    assert "VB_lgb_full" in ids_low
    assert "VB_lgb_minus_trend" in ids_low
    assert "VB_logistic_baseline" in ids_low
    assert "VB_prevalence_baseline" in ids_low

    # LOW_PRICE ablation must exclude trend family (23 features remaining)
    ablation_low = next(s for s in specs_low if s.model_id == "VB_lgb_minus_trend")
    assert len(ablation_low.features) == 23
    assert ablation_low.feature_group_excluded == "trend"
    assert "ema20" not in ablation_low.features

    specs_high = runner.get_candidate_specs("HIGHER_PRICE")
    ids_high = [s.model_id for s in specs_high]
    assert "VA_lgb_full" in ids_high
    assert "VA_lgb_minus_market_regime" in ids_high
    assert "VB_lgb_full" in ids_high
    assert "VB_lgb_minus_market_regime" in ids_high

    # HIGHER_PRICE ablation must exclude market_regime family (24 features remaining)
    ablation_high = next(s for s in specs_high if s.model_id == "VB_lgb_minus_market_regime")
    assert len(ablation_high.features) == 24
    assert ablation_high.feature_group_excluded == "market_regime"
    assert "market_breadth" not in ablation_high.features


def test_simulated_trade_gap_invalidation_handling():
    """Verify that simulated trading rejects gap-downs and gap-ups."""
    runner = CandidateEvaluationRunner()

    df_test = pd.DataFrame(
        {
            "ticker": ["GAPDOWN", "GAPUP", "NORMAL"],
            "date": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)],
            "va_entry_price": [100.0, 100.0, 100.0],
        }
    )
    y_prob = np.array([0.9, 0.85, 0.8])

    # Construct bars for Day 1 and Day 2
    bars = {
        "GAPDOWN": [
            make_bar("GAPDOWN", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("GAPDOWN", date(2026, 1, 2), 97.0, 98.0, 96.0, 97.5),  # -3.0% gap down
        ],
        "GAPUP": [
            make_bar("GAPUP", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("GAPUP", date(2026, 1, 2), 106.0, 107.0, 105.0, 106.5),  # +6.0% gap up
        ],
        "NORMAL": [
            make_bar("NORMAL", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("NORMAL", date(2026, 1, 2), 100.5, 106.0, 100.0, 105.5),  # hits TP
        ],
    }

    # Add dummy tickers for Day 1 and Day 2 to allow min_candidates rule and multi-day loop
    day1_dummies = [
        pd.DataFrame(
            {
                "ticker": [f"DUMMY_{i}"],
                "date": [date(2026, 1, 1)],
                "va_entry_price": [100.0],
            }
        )
        for i in range(10)
    ]
    day2_dummies = [
        pd.DataFrame(
            {
                "ticker": [f"DUMMY_{i}"],
                "date": [date(2026, 1, 2)],
                "va_entry_price": [100.0],
            }
        )
        for i in range(10)
    ]
    df_test_full = pd.concat([df_test] + day1_dummies + day2_dummies, ignore_index=True)
    y_prob_full = np.concatenate([y_prob, np.full(10, 0.1), np.full(10, 0.1)])

    for i in range(10):
        t_name = f"DUMMY_{i}"
        bars[t_name] = [
            make_bar(t_name, date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar(t_name, date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ]

    res = runner._simulate_fold_trading(
        df_test=df_test_full,
        y_prob=y_prob_full,
        bars_by_ticker=bars,
        top_n_per_day=5,
    )

    # GAPDOWN and GAPUP must be invalidated, only NORMAL fills and trades
    assert res["invalidated_gap_down"] >= 1
    assert res["invalidated_gap_up"] >= 1
    assert res["completed_trades"] == 1
    assert res["trades"][0].ticker == "NORMAL"
    assert res["trades"][0].exit_reason == "TP"


def test_macro_summaries_calculation():
    """Verify macro aggregation math across folds."""
    runner = CandidateEvaluationRunner()
    specs = runner.get_candidate_specs("LOW_PRICE")

    dummy_fold_res = [
        {
            "fold": 1,
            "model_id": "VB_lgb_full",
            "native_roc_auc": 0.60,
            "native_pr_auc": 0.35,
            "native_brier": 0.19,
            "native_log_loss": 0.55,
            "native_ece": 0.03,
            "native_daily_top10_prec": 0.34,
            "native_daily_top5_prec": 0.33,
            "common_roc_auc": 0.59,
            "common_pr_auc": 0.34,
            "common_brier": 0.19,
            "common_log_loss": 0.56,
        },
        {
            "fold": 2,
            "model_id": "VB_lgb_full",
            "native_roc_auc": 0.58,
            "native_pr_auc": 0.33,
            "native_brier": 0.20,
            "native_log_loss": 0.57,
            "native_ece": 0.04,
            "native_daily_top10_prec": 0.32,
            "native_daily_top5_prec": 0.31,
            "common_roc_auc": 0.57,
            "common_pr_auc": 0.32,
            "common_brier": 0.20,
            "common_log_loss": 0.58,
        },
    ]

    summaries = runner._compute_macro_summaries(dummy_fold_res, specs)
    vb_summary = next(s for s in summaries if s["model_id"] == "VB_lgb_full")

    assert vb_summary["macro_roc_auc_mean"] == 0.59
    assert vb_summary["macro_pr_auc_mean"] == 0.34
    assert vb_summary["macro_brier_mean"] == 0.195
    assert vb_summary["macro_daily_top10_mean"] == 0.33


def test_simulated_trade_excessive_dev_and_suspension():
    """Verify handling of excessive deviation and zero-volume suspension."""
    runner = CandidateEvaluationRunner()

    df_test = pd.DataFrame(
        {
            "ticker": ["DEV_FAIL", "SUSP_FAIL", "NORMAL"],
            "date": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)],
            "va_entry_price": [100.0, 100.0, 100.0],
        }
    )
    y_prob = np.array([0.95, 0.90, 0.85])

    bars = {
        "DEV_FAIL": [
            make_bar("DEV_FAIL", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("DEV_FAIL", date(2026, 1, 2), 105.5, 106.0, 105.0, 105.5),  # 5.5% dev (> 5%)
        ],
        "SUSP_FAIL": [
            make_bar("SUSP_FAIL", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("SUSP_FAIL", date(2026, 1, 2), 100.0, 100.0, 100.0, 100.0, volume=0.0),
        ],
        "NORMAL": [
            make_bar("NORMAL", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("NORMAL", date(2026, 1, 2), 100.5, 106.0, 100.0, 105.5),  # hits TP
        ],
    }

    day1_dummies = [
        pd.DataFrame({"ticker": [f"D_{i}"], "date": [date(2026, 1, 1)], "va_entry_price": [100.0]})
        for i in range(10)
    ]
    day2_dummies = [
        pd.DataFrame({"ticker": [f"D_{i}"], "date": [date(2026, 1, 2)], "va_entry_price": [100.0]})
        for i in range(10)
    ]
    df_test_full = pd.concat([df_test] + day1_dummies + day2_dummies, ignore_index=True)
    y_prob_full = np.concatenate([y_prob, np.full(10, 0.1), np.full(10, 0.1)])

    for i in range(10):
        t_name = f"D_{i}"
        bars[t_name] = [
            make_bar(t_name, date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar(t_name, date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ]

    res = runner._simulate_fold_trading(
        df_test=df_test_full,
        y_prob=y_prob_full,
        bars_by_ticker=bars,
        top_n_per_day=5,
    )

    assert res["invalidated_gap_up"] >= 1
    assert res["invalidated_total"] >= 1
    assert res["unfilled_suspended"] >= 1
    assert res["completed_trades"] == 1
    assert res["trades"][0].ticker == "NORMAL"


def test_simulated_trade_capacity_limit():
    """Verify max_positions limit prevents over-allocation."""
    runner = CandidateEvaluationRunner()

    df_test = pd.DataFrame(
        {
            "ticker": ["STOCK_A", "STOCK_B"],
            "date": [date(2026, 1, 1), date(2026, 1, 1)],
            "va_entry_price": [100.0, 100.0],
        }
    )
    y_prob = np.array([0.95, 0.90])

    bars = {
        "STOCK_A": [
            make_bar("STOCK_A", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("STOCK_A", date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ],
        "STOCK_B": [
            make_bar("STOCK_B", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("STOCK_B", date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ],
    }

    day1_dummies = [
        pd.DataFrame({"ticker": [f"D_{i}"], "date": [date(2026, 1, 1)], "va_entry_price": [100.0]})
        for i in range(10)
    ]
    day2_dummies = [
        pd.DataFrame({"ticker": [f"D_{i}"], "date": [date(2026, 1, 2)], "va_entry_price": [100.0]})
        for i in range(10)
    ]
    df_test_full = pd.concat([df_test] + day1_dummies + day2_dummies, ignore_index=True)
    y_prob_full = np.concatenate([y_prob, np.full(10, 0.1), np.full(10, 0.1)])

    for i in range(10):
        t_name = f"D_{i}"
        bars[t_name] = [
            make_bar(t_name, date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar(t_name, date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ]

    res = runner._simulate_fold_trading(
        df_test=df_test_full,
        y_prob=y_prob_full,
        bars_by_ticker=bars,
        max_positions=1,
        top_n_per_day=5,
    )

    assert res["unfilled_capacity"] >= 1


def test_simulated_trade_empty_dataframe():
    """Verify that empty test set returns clean zeros without error."""
    runner = CandidateEvaluationRunner()
    df_empty = pd.DataFrame(columns=["ticker", "date", "va_entry_price"])
    y_prob_empty = np.array([])

    res = runner._simulate_fold_trading(
        df_test=df_empty,
        y_prob=y_prob_empty,
        bars_by_ticker={},
    )
    assert res["completed_trades"] == 0
    assert res["final_equity"] == 100_000_000.0
    assert res["total_signals"] == 0


def test_aggregate_trading_summaries_calculation():
    """Verify trading summary aggregation across multiple folds."""
    runner = CandidateEvaluationRunner()
    specs = runner.get_candidate_specs("LOW_PRICE")

    trade_stats = {
        "VB_lgb_full": [
            {
                "fold": 1,
                "total_signals": 100,
                "completed_trades": 50,
                "invalidated_total": 10,
                "unfilled_total": 40,
                "win_rate": 0.30,
                "tp_count": 15,
                "sl_count": 33,
                "expiry_count": 2,
                "avg_net_return": -0.005,
                "profit_factor": 0.70,
                "max_drawdown_pct": 20.0,
            },
            {
                "fold": 2,
                "total_signals": 100,
                "completed_trades": 50,
                "invalidated_total": 10,
                "unfilled_total": 40,
                "win_rate": 0.26,
                "tp_count": 13,
                "sl_count": 35,
                "expiry_count": 2,
                "avg_net_return": -0.007,
                "profit_factor": 0.60,
                "max_drawdown_pct": 25.0,
            },
        ]
    }

    summaries = runner._aggregate_trading_summaries(trade_stats, specs)
    vb_trade = next(s for s in summaries if s["model_id"] == "VB_lgb_full")

    assert vb_trade["completed_trades"] == 100
    assert vb_trade["win_rate"] == 0.28
    assert vb_trade["tp_count"] == 28
    assert vb_trade["sl_count"] == 68
    assert vb_trade["avg_net_return"] == -0.006
    assert vb_trade["mean_profit_factor"] == 0.65
    assert vb_trade["max_drawdown_pct"] == 25.0


def test_export_artifacts_completeness(tmp_path):
    """Verify that export_artifacts generates expected files."""
    runner = CandidateEvaluationRunner()
    mock_results = {
        "LOW_PRICE": {
            "mode": "LOW_PRICE",
            "macro_summaries": [{"model_id": "M1", "macro_roc_auc_mean": 0.55}],
            "fold_results": [{"fold": 1, "model_id": "M1", "native_roc_auc": 0.55}],
            "trading_summaries": [{"model_id": "M1", "win_rate": 0.25}],
            "oos_predictions": pd.DataFrame(
                {"fold": [1], "date": ["2026-01-01"], "ticker": ["TLKM"]}
            ),
        }
    }

    exported = runner.export_artifacts(mock_results, output_dir=tmp_path)
    assert len(exported) >= 7
    for f_path in exported.values():
        assert Path(f_path).exists()


def test_slippage_friction_allocation():
    """Verify that 5 bps entry + 5 bps exit slippage is accurately applied."""
    runner = CandidateEvaluationRunner()

    df_test = pd.DataFrame(
        {
            "ticker": ["SLIP_TEST"],
            "date": [date(2026, 1, 1)],
            "va_entry_price": [100.0],
        }
    )
    y_prob = np.array([0.9])

    bars = {
        "SLIP_TEST": [
            make_bar("SLIP_TEST", date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar("SLIP_TEST", date(2026, 1, 2), 100.0, 106.0, 100.0, 105.5),
        ]
    }

    # Add 10 dummy candidates to meet min_candidates=10 requirement on Day 1 and Day 2
    day1_dummies = [
        pd.DataFrame(
            {
                "ticker": [f"D_{i}"],
                "date": [date(2026, 1, 1)],
                "va_entry_price": [100.0],
            }
        )
        for i in range(10)
    ]
    day2_dummies = [
        pd.DataFrame(
            {
                "ticker": [f"D_{i}"],
                "date": [date(2026, 1, 2)],
                "va_entry_price": [100.0],
            }
        )
        for i in range(10)
    ]
    for i in range(10):
        t_name = f"D_{i}"
        bars[t_name] = [
            make_bar(t_name, date(2026, 1, 1), 100.0, 101.0, 99.0, 100.0),
            make_bar(t_name, date(2026, 1, 2), 100.0, 101.0, 99.0, 100.0),
        ]

    df_full = pd.concat([df_test] + day1_dummies + day2_dummies, ignore_index=True)
    y_prob_full = np.concatenate([y_prob, np.full(10, 0.1), np.full(10, 0.1)])

    res = runner._simulate_fold_trading(
        df_test=df_full,
        y_prob=y_prob_full,
        bars_by_ticker=bars,
        commission_buy=0.0015,
        commission_sell=0.0025,
        slippage_entry_bps=5.0,
        slippage_exit_bps=5.0,
    )

    assert res["completed_trades"] == 1
    trade = res["trades"][0]
    assert trade.ticker == "SLIP_TEST"
    # Entry raw is 100.0; fill_price with 5 bps slippage is 100.0 * 1.0005 = 100.05
    assert trade.entry_price == 100.05
    # TP barrier is 100.05 * 1.05 = 105.0525; exit fill with 5 bps slippage:
    # 105.0525 * (1 - 0.0005)
    expected_exit = 105.0525 * (1.0 - 0.0005)
    assert abs(trade.exit_price - expected_exit) < 1e-4


def test_pooled_vs_mean_profit_factor_and_drawdown_distinction():
    """Verify distinct computation of pooled PF vs mean PF and worst-fold vs continuous drawdown."""
    from python.experiments.candidate_eval import SimulatedTrade

    runner = CandidateEvaluationRunner()
    specs = runner.get_candidate_specs("LOW_PRICE")

    # Trade 1 in Fold 1: gain = 200, loss = 0
    t1 = SimulatedTrade(
        ticker="AAA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        exit_date=date(2026, 1, 3),
        entry_price=100.0,
        exit_price=105.0,
        shares=1000,
        gross_pnl=5000.0,
        net_pnl=2000.0,
        net_return=0.02,
        exit_reason="TP",
        holding_days=1,
        signal_prob=0.8,
    )
    # Trade 2 in Fold 2: gain = 0, loss = 1000
    t2 = SimulatedTrade(
        ticker="BBB",
        signal_date=date(2026, 2, 1),
        entry_date=date(2026, 2, 2),
        exit_date=date(2026, 2, 3),
        entry_price=100.0,
        exit_price=98.0,
        shares=1000,
        gross_pnl=-2000.0,
        net_pnl=-1000.0,
        net_return=-0.01,
        exit_reason="SL",
        holding_days=1,
        signal_prob=0.8,
    )

    trade_stats = {
        "VB_lgb_full": [
            {
                "fold": 1,
                "total_signals": 10,
                "completed_trades": 1,
                "invalidated_total": 0,
                "unfilled_total": 9,
                "win_rate": 1.0,
                "tp_count": 1,
                "sl_count": 0,
                "expiry_count": 0,
                "avg_net_return": 0.02,
                "profit_factor": 2.0,
                "max_drawdown_pct": 10.0,
                "initial_capital": 100_000_000.0,
                "final_equity": 102_000_000.0,
                "daily_equity": [
                    (date(2026, 1, 2), 100_000_000.0),
                    (date(2026, 1, 3), 102_000_000.0),
                ],
            },
            {
                "fold": 2,
                "total_signals": 10,
                "completed_trades": 1,
                "invalidated_total": 0,
                "unfilled_total": 9,
                "win_rate": 0.0,
                "tp_count": 0,
                "sl_count": 1,
                "expiry_count": 0,
                "avg_net_return": -0.01,
                "profit_factor": 0.5,
                "max_drawdown_pct": 20.0,
                "initial_capital": 100_000_000.0,
                "final_equity": 99_000_000.0,
                "daily_equity": [
                    (date(2026, 2, 2), 100_000_000.0),
                    (date(2026, 2, 3), 99_000_000.0),
                ],
            },
        ]
    }
    all_trades = {"VB_lgb_full": [t1, t2]}

    summaries = runner._aggregate_trading_summaries(
        all_model_trade_stats=trade_stats,
        specs=specs,
        all_model_trades=all_trades,
    )
    s = next(entry for entry in summaries if entry["model_id"] == "VB_lgb_full")

    # Pooled profit factor = 2000 / 1000 = 2.0
    assert s["pooled_profit_factor"] == 2.0
    # Mean profit factor = (2.0 + 0.5) / 2 = 1.25
    assert s["mean_profit_factor"] == 1.25
    # Worst fold max drawdown = max(10.0, 20.0) = 20.0
    assert s["worst_fold_max_drawdown_pct"] == 20.0
    # Continuous max drawdown:
    # Fold 1 peaks at 102M.
    # Fold 2 starts at 102M, drops to 102M * 0.99 = 100.98M. Drawdown = (102 - 100.98) / 102 = 1.0%
    assert s["continuous_max_drawdown_pct"] >= 1.0


def test_recompute_trading_from_saved_predictions():
    """Verify that recompute_trading_from_saved_predictions simulates trading."""
    runner = CandidateEvaluationRunner()
    res = runner.recompute_trading_from_saved_predictions(
        mode="LOW_PRICE",
        artifacts_dir="artifacts/candidate_eval",
    )
    assert res["mode"] == "LOW_PRICE"
    assert "trading_summaries" in res
    assert len(res["trading_summaries"]) == 8
    vb = next(s for s in res["trading_summaries"] if s["model_id"] == "VB_lgb_full")
    assert vb["completed_trades"] > 0
    assert vb["pooled_profit_factor"] > 0.0
    assert vb["mean_profit_factor"] > 0.0
    assert vb["worst_fold_max_drawdown_pct"] > 0.0
    assert vb["continuous_max_drawdown_pct"] > 0.0
