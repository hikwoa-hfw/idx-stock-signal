"""Unit tests for Phase 11A controlled feature ablation engine."""

import numpy as np

from python.experiments.ablation import (
    ALL_FEATURE_COLUMNS,
    FEATURE_FAMILIES,
    FEATURE_INVENTORY,
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
