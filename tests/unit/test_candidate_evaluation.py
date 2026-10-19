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

