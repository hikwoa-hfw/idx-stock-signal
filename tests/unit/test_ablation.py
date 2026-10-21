"""Unit tests for Phase 11A controlled feature ablation engine."""

from pathlib import Path

import numpy as np
import pandas as pd

from python.experiments.ablation import (
    ALL_FEATURE_COLUMNS,
    FEATURE_FAMILIES,
    FEATURE_INVENTORY,
    FeatureAblationRunner,
    compute_daily_cross_sectional_top_k_precision,
    compute_daily_top_n_precision,
    compute_pr_auc,
    compute_top_k_precision,
    evaluate_predictions,
)
from python.models.dataset import DEFAULT_FEATURE_COLUMNS
from python.models.registry import ModelRegistry
from python.models.validation import WalkForwardSplitter


def test_feature_family_inventory_completeness() -> None:
    """Verifies that all 30 default features are mapped to exactly one family."""
    all_mapped = []
    for family, features in FEATURE_FAMILIES.items():
        assert len(features) > 0, f"Family {family} has no features"
        all_mapped.extend(features)

    assert len(all_mapped) == 30, f"Expected 30 features, got {len(all_mapped)}"
    assert len(set(all_mapped)) == 30, "Feature families must be mutually disjoint"
    assert set(all_mapped) == set(DEFAULT_FEATURE_COLUMNS), (
        "Mapped features must match DEFAULT_FEATURE_COLUMNS"
    )
    assert set(ALL_FEATURE_COLUMNS) == set(DEFAULT_FEATURE_COLUMNS)
    assert len(FEATURE_INVENTORY) == 30, "FEATURE_INVENTORY must have 30 entries"


def test_metrics_calculation_correctness() -> None:
    """Tests PR-AUC, ECE, top-k precision, and evaluate_predictions calculations."""
    y_true = np.array([1, 0, 1, 1, 0, 0, 1, 0, 0, 0], dtype=np.int64)  # 4 pos, 6 neg
    y_prob = np.array([0.9, 0.1, 0.8, 0.7, 0.3, 0.2, 0.6, 0.4, 0.2, 0.1], dtype=np.float64)

    # Top-10% (k=1) of 10 samples -> highest probability is index 0 (y=1) -> precision 1.0
    prec_top10 = compute_top_k_precision(y_true, y_prob, k_pct=0.10)
    assert prec_top10 == 1.0

    # Top-40% (k=4) -> indices [0, 2, 3, 6], all y=1 -> precision 1.0
    prec_top40 = compute_top_k_precision(y_true, y_prob, k_pct=0.40)
    assert prec_top40 == 1.0

    pr_auc = compute_pr_auc(y_true, y_prob)
    assert 0.8 <= pr_auc <= 1.0

    res = evaluate_predictions(y_true, y_prob)
    assert res["sample_size"] == 10
    assert res["positive_count"] == 4
    assert res["prevalence"] == 0.40
    assert res["roc_auc"] == 1.0  # Perfect separation
    assert res["brier_score"] >= 0.0
    assert 0.0 <= res["ece"] <= 1.0


def test_walk_forward_purge_guarantees() -> None:
    """Verifies that WalkForwardSplitter strictly enforces purge window and order."""
    dates = [f"2024-01-{i:02d}" for i in range(1, 31)]  # 30 unique dates
    splitter = WalkForwardSplitter(n_splits=3, purge_days=4, expanding=True)

    splits = list(splitter.split(dates))
    assert len(splits) == 3

    for fold_idx, (tr_idx, te_idx) in enumerate(splits, start=1):
        tr_dates = [dates[i] for i in tr_idx]
        te_dates = [dates[i] for i in te_idx]

        assert max(tr_dates) < min(te_dates), f"Leakage detected in fold {fold_idx}"

        # Check purge gap: difference in date index between max train and min test
        max_tr_pos = dates.index(max(tr_dates))
        min_te_pos = dates.index(min(te_dates))
        gap = min_te_pos - max_tr_pos - 1
        assert gap == 4, f"Expected purge gap of 4 dates, got {gap}"


def test_production_champions_protected() -> None:
    """Verifies that production champions remain untouched and unmodified."""
    registry = ModelRegistry()
    res_low = registry.get_champion(task="classification", mode="LOW_PRICE")
    res_high = registry.get_champion(task="classification", mode="HIGHER_PRICE")

    assert res_low is not None, "LOW_PRICE champion must exist"
    assert res_high is not None, "HIGHER_PRICE champion must exist"

    _, meta_low = res_low
    _, meta_high = res_high

    assert meta_low.model_version == "lightgbm_classification_20261014_093522"
    assert meta_high.model_version == "lightgbm_classification_20261014_093607"
    assert meta_low.status == "champion"
    assert meta_high.status == "champion"


def test_daily_cross_sectional_top_k_precision() -> None:
    """Verifies daily cross-sectional ranking, selection, and aggregation."""
    # 2 dates, each with 10 candidates
    dates = ["2024-01-01"] * 10 + ["2024-01-02"] * 10
    tickers = [f"TICK{i:02d}" for i in range(10)] + [f"TICK{i:02d}" for i in range(10)]
    # Date 1: top 10% (1 pick) will be TICK00 (prob 0.95), target 1 -> precision 1.0
    # Date 2: top 10% (1 pick) will be TICK00 (prob 0.90), target 0 -> precision 0.0
    targets = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0] + [0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    probs = [0.95, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05] + [
        0.90,
        0.85,
        0.7,
        0.6,
        0.5,
        0.4,
        0.3,
        0.2,
        0.1,
        0.05,
    ]
    df = pd.DataFrame({"date": dates, "ticker": tickers, "binary_target": targets, "y_prob": probs})

    res = compute_daily_cross_sectional_top_k_precision(df, k_pct=0.10, min_candidates=10)
    assert res["total_dates"] == 2
    assert res["evaluated_dates"] == 2
    assert res["insufficient_dates"] == 0
    # Mean of 1.0 and 0.0 is 0.5
    assert res["daily_precision_macro"] == 0.5000
    assert res["daily_precision_micro"] == 0.5000

    # Test minimum candidates threshold exclusion
    df_small = pd.DataFrame(
        {
            "date": ["2024-01-01"] * 10 + ["2024-01-02"] * 4,
            "ticker": [f"T{i:02d}" for i in range(10)] + [f"T{i:02d}" for i in range(4)],
            "binary_target": [1] * 10 + [0] * 4,
            "y_prob": [0.8] * 10 + [0.8] * 4,
        }
    )
    res_thresh = compute_daily_cross_sectional_top_k_precision(
        df_small, k_pct=0.10, min_candidates=5
    )
    assert res_thresh["total_dates"] == 2
    assert res_thresh["evaluated_dates"] == 1
    assert res_thresh["insufficient_dates"] == 1
    assert res_thresh["daily_precision_macro"] == 1.0


def test_deterministic_tie_breaking_by_ticker() -> None:
    """Verifies that tied probabilities break ties deterministically by ticker ascending."""
    # 5 stocks with identical predicted probability 0.70
    df = pd.DataFrame(
        {
            "date": ["2024-01-01"] * 5,
            "ticker": ["TLKM", "BBCA", "ASII", "UNVR", "BMRI"],
            "binary_target": [0, 1, 0, 0, 0],  # Only BBCA is positive
            "y_prob": [0.70, 0.70, 0.70, 0.70, 0.70],
        }
    )
    # Alphabetical order: ASII, BBCA, BMRI, TLKM, UNVR
    # Top 2 picks (top 40%) will be ASII (target 0) and BBCA (target 1) -> precision 0.5
    res = compute_daily_cross_sectional_top_k_precision(df, k_pct=0.40, min_candidates=5)
    assert res["evaluated_dates"] == 1
    assert res["daily_precision_macro"] == 0.5000


def test_prevalence_baseline_fold_auc_and_pooled_effect() -> None:
    """Verifies constant prediction produces 0.5000 AUC within fold but distorts when pooled."""
    from python.models.metrics import compute_roc_auc

    # Fold 1: prevalence 0.20 (20 pos / 100), prediction is constant 0.20
    y_true_f1 = np.array([1] * 20 + [0] * 80)
    y_prob_f1 = np.full(100, 0.20)
    auc_f1 = compute_roc_auc(y_true_f1, y_prob_f1)
    assert auc_f1 == 0.5000, f"Fold 1 ROC-AUC must be 0.5000, got {auc_f1}"

    # Fold 2: prevalence 0.35 (35 pos / 100), prediction is constant 0.35
    y_true_f2 = np.array([1] * 35 + [0] * 65)
    y_prob_f2 = np.full(100, 0.35)
    auc_f2 = compute_roc_auc(y_true_f2, y_prob_f2)
    assert auc_f2 == 0.5000, f"Fold 2 ROC-AUC must be 0.5000, got {auc_f2}"

    # Macro average across folds is strictly 0.5000
    macro_auc = float(np.mean([auc_f1, auc_f2]))
    assert macro_auc == 0.5000

    # Pooled cross-fold vector: probabilities differ between folds (0.20 vs 0.35)
    y_true_pooled = np.concatenate([y_true_f1, y_true_f2])
    y_prob_pooled = np.concatenate([y_prob_f1, y_prob_f2])
    pooled_auc = compute_roc_auc(y_true_pooled, y_prob_pooled)
    # The pooled AUC deviates from 0.5000 due to cross-fold prevalence shift
    assert pooled_auc != 0.5000, f"Pooled AUC was expected to deviate from 0.5, got {pooled_auc}"


def test_daily_top_n_precision() -> None:
    """Verifies daily Top-N fixed-count precision diagnostic."""
    df = pd.DataFrame(
        {
            "date": ["2024-01-01"] * 6,
            "ticker": [f"T{i}" for i in range(6)],
            "binary_target": [1, 1, 0, 0, 0, 0],
            "y_prob": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
        }
    )
    # Top-2 of 6 candidates: T0 (prob 0.9, target 1) and T1 (prob 0.8, target 1) -> 2/2 = 1.0
    res = compute_daily_top_n_precision(df, top_n=2, min_candidates=5)
    assert res["evaluated_dates"] == 1
    assert res["daily_precision_macro"] == 1.0


def test_daily_top_k_selection_mask() -> None:
    """Verifies that selection_mask precisely tags selected candidates across dates."""
    dates = ["2024-01-01"] * 10 + ["2024-01-02"] * 10
    tickers = [f"T{i:02d}" for i in range(10)] + [f"T{i:02d}" for i in range(10)]
    targets = [0] * 20
    # On date 1, T00 has highest prob; on date 2, T09 has highest prob
    probs = [0.9] + [0.1] * 9 + [0.1] * 9 + [0.9]
    df = pd.DataFrame({"date": dates, "ticker": tickers, "binary_target": targets, "y_prob": probs})
    res = compute_daily_cross_sectional_top_k_precision(df, k_pct=0.10, min_candidates=10)
    mask = res["selection_mask"]
    assert len(mask) == 20
    # Date 1 top pick is index 0; Date 2 top pick is index 19
    assert mask[0] == 1
    assert mask[19] == 1
    assert sum(mask) == 2


def test_daily_top_n_precision_edge_cases() -> None:
    """Verifies safe handling of empty data, zero, or negative top_n without ZeroDivisionError."""
    df = pd.DataFrame(
        {
            "date": ["2024-01-01"] * 5,
            "ticker": [f"T{i}" for i in range(5)],
            "binary_target": [1] * 5,
            "y_prob": [0.8] * 5,
        }
    )
    res_zero = compute_daily_top_n_precision(df, top_n=0)
    assert res_zero["daily_precision_macro"] == 0.0
    assert res_zero["evaluated_dates"] == 0

    res_neg = compute_daily_top_n_precision(df, top_n=-3)
    assert res_neg["daily_precision_macro"] == 0.0
    assert res_neg["evaluated_dates"] == 0


def test_export_artifacts_preserves_results_dict(tmp_path: object) -> None:
    """Verifies export_artifacts does not mutate the caller's results dictionary in-place."""
    out_dir = Path(str(tmp_path))
    dummy_oos = pd.DataFrame({"fold": [1], "ticker": ["TEST"], "binary_target": [1]})
    results: dict[str, object] = {
        "mode": "TEST_MODE",
        "macro_aggregate_results": [],
        "fold_evaluations": [],
        "oos_predictions_df": dummy_oos,
    }

    runner = FeatureAblationRunner()
    runner.export_artifacts(results, output_dir=out_dir)

    # Must NOT have popped oos_predictions_df
    assert "oos_predictions_df" in results
    assert results["oos_predictions_df"] is dummy_oos
    assert (out_dir / "oos_predictions_TEST_MODE.csv").exists()
