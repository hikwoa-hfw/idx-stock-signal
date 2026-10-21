from datetime import date

import numpy as np
import pandas as pd
import pytest

from python.common.types import DailyBar
from python.experiments.multi_horizon_eval import (
    HORIZONS,
    MultiHorizonEvaluationRunner,
    calculate_net_return,
    compute_regression_binned_diagnostics,
    evaluate_regression_predictions,
    evaluate_variant_b_multi_horizon,
)


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


def test_calculate_net_return_contract():
    """Verify exact net return under 50 bps round-trip friction."""
    # Flat trade: entry 100, exit 100
    r_flat = calculate_net_return(100.0, 100.0)
    # Expected friction: entry_fill=100.05, invested=100.200075, exit_fill=99.95, proceeds=99.700125
    # net_return = (99.700125 - 100.200075) / 100.200075 = -0.0049895...
    assert pytest.approx(r_flat, abs=1e-5) == -0.00499

    # TP at +5%: entry 100, exit 105
    r_tp = calculate_net_return(100.0, 105.0)
    assert pytest.approx(r_tp, abs=1e-5) == 0.04476

    # SL at -2%: entry 100, exit 98
    r_sl = calculate_net_return(100.0, 98.0)
    assert pytest.approx(r_sl, abs=1e-5) == -0.02489

    # Edge cases
    assert calculate_net_return(0.0, 100.0) == 0.0
    assert calculate_net_return(-10.0, 100.0) == 0.0


def test_multi_horizon_target_barrier_detection():
    """Verify that multi-horizon outcomes correctly handle barrier hits across horizons."""
    entry_b = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)

    # Bars: Day 1 open 100.0, Day 2 flat, Day 3 flat, Day 4 hits TP (+5%), Day 5-15 flat
    forward_bars = [
        make_bar("TEST", date(2026, 1, 2), 100.0, 101.0, 99.5, 100.2),  # Day 1
        make_bar("TEST", date(2026, 1, 3), 100.2, 101.5, 99.5, 100.5),  # Day 2
        make_bar("TEST", date(2026, 1, 4), 100.5, 101.8, 99.8, 101.0),  # Day 3 (Close 101.0)
        make_bar("TEST", date(2026, 1, 5), 101.0, 105.5, 100.8, 105.2),  # Day 4 (Hits TP 105.0)
    ]
    # Add dummy flat bars up to 15
    for k in range(5, 16):
        forward_bars.append(make_bar("TEST", date(2026, 1, k), 105.0, 106.0, 104.0, 105.0))

    outcomes = evaluate_variant_b_multi_horizon(entry_b, forward_bars, horizons=[3, 5, 10, 15])

    # Horizon 3: TP hit on Day 4, so at Day 3 it expires!
    assert outcomes[3]["status"] == "VALID"
    assert outcomes[3]["outcome"] == "EXPIRY"
    assert outcomes[3]["binary_target"] == 0
    assert outcomes[3]["holding_days"] == 3
    assert outcomes[3]["exit_price"] == 101.0

    # Horizon 5: TP hit on Day 4!
    assert outcomes[5]["status"] == "VALID"
    assert outcomes[5]["outcome"] == "TP"
    assert outcomes[5]["binary_target"] == 1
    assert outcomes[5]["holding_days"] == 4
    assert outcomes[5]["exit_price"] == 105.0

    # Horizon 10 and 15: also TP at Day 4!
    assert outcomes[10]["outcome"] == "TP"
    assert outcomes[10]["holding_days"] == 4
    assert outcomes[15]["outcome"] == "TP"
    assert outcomes[15]["holding_days"] == 4


def test_multi_horizon_invalidation_consistency():
    """Verify that pre-entry gap invalidations fail-closed across all horizons."""
    entry_b = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)

    # Gap down > 2% on Day 1 Open (open 97.5 <= 98.0)
    fwd_gap_down = [
        make_bar("TEST", date(2026, 1, 2), 97.0, 98.0, 96.0, 97.5),
    ] + [make_bar("TEST", date(2026, 1, k), 100.0, 101.0, 99.0, 100.0) for k in range(3, 17)]

    outcomes_down = evaluate_variant_b_multi_horizon(entry_b, fwd_gap_down)
    for h in HORIZONS:
        assert outcomes_down[h]["status"] == "INVALIDATED"
        assert outcomes_down[h]["outcome"] == "INVALIDATED_GAP"
        assert outcomes_down[h]["invalidation_reason"] == "GAP_BELOW_SL"
        assert outcomes_down[h]["binary_target"] is None

    # Gap up > 5% on Day 1 Open (open 106.0 >= 105.0)
    fwd_gap_up = [
        make_bar("TEST", date(2026, 1, 2), 106.0, 107.0, 105.0, 106.0),
    ] + [make_bar("TEST", date(2026, 1, k), 100.0, 101.0, 99.0, 100.0) for k in range(3, 17)]

    outcomes_up = evaluate_variant_b_multi_horizon(entry_b, fwd_gap_up)
    for h in HORIZONS:
        assert outcomes_up[h]["status"] == "INVALIDATED"
        assert outcomes_up[h]["outcome"] == "INVALIDATED_GAP"
        assert outcomes_up[h]["invalidation_reason"] == "GAP_ABOVE_TP"


def test_multi_horizon_incomplete_data():
    """Verify incomplete forward data handling across horizons."""
    entry_b = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)

    # Only 4 forward flat bars (no TP, no SL)
    fwd_short = [make_bar("TEST", date(2026, 1, k), 100.0, 101.0, 99.5, 100.0) for k in range(2, 6)]

    outcomes = evaluate_variant_b_multi_horizon(entry_b, fwd_short, horizons=[3, 5, 10, 15])
    # Horizon 3 has enough bars (4 >= 3) -> EXPIRY
    assert outcomes[3]["status"] == "VALID"
    assert outcomes[3]["outcome"] == "EXPIRY"

    # Horizon 5, 10, 15 do not have enough forward bars -> INCOMPLETE
    assert outcomes[5]["status"] == "INCOMPLETE"
    assert outcomes[5]["outcome"] == "INCOMPLETE"
    assert outcomes[5]["binary_target"] is None

    assert outcomes[10]["status"] == "INCOMPLETE"
    assert outcomes[15]["status"] == "INCOMPLETE"


def test_regression_metrics_evaluation():
    """Verify regression metrics and baselines computation."""
    y_true = np.array([0.04, -0.02, 0.01, -0.01, 0.03])
    y_pred = np.array([0.03, -0.01, 0.02, 0.00, 0.02])
    y_train = np.array([0.02, 0.01, -0.01, 0.00])

    metrics = evaluate_regression_predictions(y_true, y_pred, y_train=y_train)
    assert metrics["sample_size"] == 5
    assert metrics["mae"] > 0.0
    assert metrics["rmse"] > 0.0
    assert metrics["mae_zero_baseline"] > 0.0
    assert metrics["mae_mean_baseline"] > 0.0
    assert "r2" in metrics
    assert "pearson_r" in metrics

    # Empty inputs check
    empty_res = evaluate_regression_predictions(np.array([]), np.array([]))
    assert empty_res["sample_size"] == 0
    assert empty_res["mae"] == 0.0


def test_regression_binned_diagnostics():
    """Verify calibration diagnostics across predicted return ranges."""
    y_true = np.array([-0.02, -0.01, 0.005, 0.015, 0.04])
    y_pred = np.array([-0.015, -0.005, 0.008, 0.012, 0.025])

    diag = compute_regression_binned_diagnostics(y_true, y_pred)
    assert len(diag) == 5
    # Total count matches
    total_cnt = sum(b["count"] for b in diag)
    assert total_cnt == len(y_true)


def test_multi_horizon_model_specs():
    """Verify controlled model specifications for Phase 11C."""
    runner = MultiHorizonEvaluationRunner()

    specs_low = runner.get_model_specs("LOW_PRICE")
    ids_low = [s.model_id for s in specs_low]
    assert "lgb_full" in ids_low
    assert "lgb_minus_trend" in ids_low
    assert "logistic_baseline" in ids_low
    assert "prevalence_baseline" in ids_low
    assert "lgb_regressor" in ids_low
    assert "zero_return_baseline" in ids_low
    assert "mean_regressor_baseline" in ids_low

    # Pruned feature checks
    ablation_low = next(s for s in specs_low if s.model_id == "lgb_minus_trend")
    assert len(ablation_low.features) == 23
    assert "ema20" not in ablation_low.features

    specs_high = runner.get_model_specs("HIGHER_PRICE")
    ids_high = [s.model_id for s in specs_high]
    assert "lgb_full" in ids_high
    assert "lgb_minus_market_regime" in ids_high
    ablation_high = next(s for s in specs_high if s.model_id == "lgb_minus_market_regime")
    assert len(ablation_high.features) == 24
    assert "market_breadth" not in ablation_high.features


def test_multi_horizon_ambiguous_hit_isolation():
    """Verify that an ambiguous barrier hit beyond horizon h does not leak into horizon h."""
    entry_b = make_bar("TEST", date(2026, 1, 1), 100.0, 102.0, 99.0, 100.0)

    # Days 1 to 3: flat bars (no TP, no SL)
    # Day 4: hits both TP (106.0 >= 105.0) and SL (97.0 <= 98.0) -> Ambiguous hit on Day 4
    forward_bars = [
        make_bar("TEST", date(2026, 1, 2), 100.0, 101.0, 99.5, 100.0),  # Day 1
        make_bar("TEST", date(2026, 1, 3), 100.0, 101.0, 99.5, 100.0),  # Day 2
        make_bar("TEST", date(2026, 1, 4), 100.0, 101.0, 99.5, 100.0),  # Day 3
        make_bar("TEST", date(2026, 1, 5), 100.0, 106.0, 97.0, 100.0),  # Day 4 (ambiguous!)
    ]
    for k in range(6, 18):
        forward_bars.append(make_bar("TEST", date(2026, 1, k), 100.0, 101.0, 99.0, 100.0))

    outcomes = evaluate_variant_b_multi_horizon(entry_b, forward_bars, horizons=[3, 5, 10, 15])

    # Horizon 3 expired on Day 3 without any hit, ambiguous count MUST be 0!
    assert outcomes[3]["outcome"] == "EXPIRY"
    assert outcomes[3]["ambiguous_count"] == 0

    # Horizon 5 hit ambiguous on Day 4, so outcome is SL (conservative) and ambiguous_count is 1
    assert outcomes[5]["outcome"] == "SL"
    assert outcomes[5]["ambiguous_count"] == 1
    assert outcomes[5]["holding_days"] == 4


def test_multi_horizon_export_artifacts_structure(tmp_path):
    """Verify that artifact export generates all required JSON and CSV artifacts."""
    runner = MultiHorizonEvaluationRunner()
    mock_results = {
        "LOW_PRICE": {
            "mode": "LOW_PRICE",
            "n_splits": 3,
            "purge_days": 15,
            "random_state": 42,
            "total_universe_samples": 100,
            "horizons": [3],
            "horizon_results": {
                3: {
                    "horizon": 3,
                    "fold_metadata": [],
                    "classification_fold_results": [],
                    "classification_summaries": [
                        {
                            "model_id": "lgb_full",
                            "display_name": "Full LightGBM",
                            "macro_roc_auc_mean": 0.60,
                        }
                    ],
                    "regression_fold_results": [
                        {
                            "fold": 1,
                            "model_id": "lgb_regressor",
                            "mae": 0.02,
                            "binned_diagnostics": [
                                {
                                    "bin_label": "[0%, 1%)",
                                    "count": 50,
                                    "pct_of_total": 50.0,
                                    "mean_predicted_ret": 0.005,
                                    "mean_realized_ret": 0.004,
                                    "error": 0.001,
                                    "mae": 0.008,
                                    "win_rate": 0.55,
                                }
                            ],
                        }
                    ],
                    "regression_summaries": [
                        {
                            "model_id": "lgb_regressor",
                            "display_name": "LGBM Regressor",
                            "macro_mae_mean": 0.02,
                        }
                    ],
                    "trading_summaries": [
                        {
                            "horizon": 3,
                            "model_id": "lgb_full",
                            "display_name": "Full LightGBM",
                            "completed_trades": 10,
                            "win_rate": 0.30,
                        }
                    ],
                    "trading_fold_stats": {
                        "lgb_full": [
                            {
                                "horizon": 3,
                                "fold": 1,
                                "model_id": "lgb_full",
                                "completed_trades": 10,
                                "win_rate": 0.30,
                            }
                        ]
                    },
                    "ev_diagnostic_results": [],
                }
            },
            "oos_predictions": pd.DataFrame({"ticker": ["BBCA"], "prob_lgb_full": [0.6]}),
        }
    }

    exported = runner.export_artifacts(mock_results, output_dir=tmp_path)
    assert "classification_summary_csv" in exported
    assert "regression_summary_csv" in exported
    assert "trading_summary_csv" in exported
    assert "trading_by_fold_csv" in exported
    assert "regression_binned_diagnostics_csv" in exported
    assert "ev_diagnostic_summary_csv" in exported
    assert (tmp_path / "multi_horizon_trading_by_fold.csv").exists()
    assert (tmp_path / "multi_horizon_regression_binned_diagnostics.csv").exists()
