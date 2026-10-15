from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from python.common.types import FeatureRecord, LabelRecord
from python.models.baseline import (
    LightGBMClassifierBaseline,
    LightGBMRegressorBaseline,
    LogisticRegressionBaseline,
    RidgeRegressionBaseline,
    create_baseline_model,
)
from python.models.dataset import DatasetBuilder
from python.models.metrics import (
    compute_accuracy,
    compute_brier_score,
    compute_calibration_curve,
    compute_expected_calibration_error,
    compute_log_loss,
    compute_mae,
    compute_mse,
    compute_r2,
    compute_rmse,
    compute_roc_auc,
    evaluate_classification,
    evaluate_regression,
)
from python.models.registry import ModelMetadata, ModelRegistry
from python.models.validation import (
    WalkForwardSplitter,
    split_by_dates,
    split_chronological,
)

# =========================================================================
# 1. Validation & Chronological Splitting Tests
# =========================================================================


def test_split_chronological_strict_ordering():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(100)]
    repeated_dates = [d for d in dates for _ in range(3)]  # 3 stocks per date

    train_idx, val_idx, test_idx = split_chronological(
        repeated_dates,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        purge_days=0,
    )

    assert len(train_idx) > 0
    assert len(val_idx) > 0
    assert len(test_idx) > 0
    assert len(train_idx) + len(val_idx) + len(test_idx) == len(repeated_dates)

    train_dates = [repeated_dates[i] for i in train_idx]
    val_dates = [repeated_dates[i] for i in val_idx]
    test_dates = [repeated_dates[i] for i in test_idx]

    assert max(train_dates) < min(val_dates)
    assert max(val_dates) < min(test_dates)


def test_split_chronological_with_purge_window():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(50)]
    purge_days = 5

    train_idx, val_idx, test_idx = split_chronological(
        dates,
        train_ratio=0.60,
        val_ratio=0.20,
        test_ratio=0.20,
        purge_days=purge_days,
    )

    train_dates = [dates[i] for i in train_idx]
    val_dates = [dates[i] for i in val_idx]
    test_dates = [dates[i] for i in test_idx]

    # Gap between train and val must be at least purge_days
    gap_train_val = (min(val_dates) - max(train_dates)).days
    assert gap_train_val >= purge_days

    # Gap between val and test
    gap_val_test = (min(test_dates) - max(val_dates)).days
    assert gap_val_test >= purge_days


def test_split_chronological_edge_cases():
    # Empty
    tr, va, te = split_chronological([])
    assert len(tr) == 0 and len(va) == 0 and len(te) == 0

    # Less than 2 distinct dates
    with pytest.raises(ValueError, match="Need at least 2 distinct dates"):
        split_chronological([date(2025, 1, 1), date(2025, 1, 1)])

    # Excessive purge
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(5)]
    with pytest.raises(ValueError, match="exceeds train date count"):
        split_chronological(dates, train_ratio=0.5, val_ratio=0.2, test_ratio=0.3, purge_days=10)


def test_split_by_dates():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(30)]
    train_idx, val_idx, test_idx = split_by_dates(
        dates,
        train_end=date(2025, 1, 15),
        val_end=date(2025, 1, 22),
        purge_days=2,
    )

    train_dates = [dates[i] for i in train_idx]
    val_dates = [dates[i] for i in val_idx]
    test_dates = [dates[i] for i in test_idx]

    assert max(train_dates) <= date(2025, 1, 13)
    assert min(val_dates) > date(2025, 1, 15)
    assert max(val_dates) <= date(2025, 1, 20)
    assert min(test_dates) > date(2025, 1, 22)


def test_walk_forward_splitter():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(60)]
    splitter = WalkForwardSplitter(n_splits=3, test_days=10, purge_days=5, expanding=False)

    folds = list(splitter.split(dates))
    assert len(folds) == 3

    for _fold_i, (train_idx, test_idx) in enumerate(folds):
        assert len(train_idx) > 0
        assert len(test_idx) == 10
        train_dates = [dates[i] for i in train_idx]
        test_dates = [dates[i] for i in test_idx]
        assert max(train_dates) < min(test_dates)
        gap = (min(test_dates) - max(train_dates)).days
        assert gap >= 5


# =========================================================================
# 2. DatasetBuilder & Dataset Tests
# =========================================================================


def _sample_feature_record(ticker: str, d: date, return_val: float = 0.01) -> FeatureRecord:
    return FeatureRecord(
        ticker=ticker,
        date=d,
        feature_version="v1.0.0",
        return_1d=return_val,
        return_3d=return_val * 2,
        return_5d=return_val * 3,
        return_10d=return_val * 4,
        return_20d=return_val * 5,
        ema20=1000.0,
        ema50=990.0,
        ema200=950.0,
        close_vs_ema20=0.01,
        close_vs_ema50=0.02,
        ema20_vs_ema50=0.01,
        ema50_vs_ema200=0.04,
        rsi14=55.0,
        rsi_change_5d=2.0,
        atr14=20.0,
        atr_pct=0.02,
        realized_vol_5d=0.015,
        realized_vol_20d=0.018,
        daily_range_pct=0.025,
        volume_ratio_5d=1.1,
        volume_ratio_20d=1.05,
        value_ratio_20d=1.08,
        rel_strength_ihsg_20d=0.03,
        rel_strength_sector_20d=0.02,
        ihsg_return_5d=0.01,
        ihsg_return_20d=0.02,
        ihsg_vs_ema20=0.005,
        ihsg_vs_ema50=0.012,
        market_breadth=0.6,
        market_volatility=0.012,
    )


def _sample_label_record(
    ticker: str,
    d: date,
    target: int = 1,
    outcome: str = "TP",
    ret: float = 0.05,
) -> LabelRecord:
    return LabelRecord(
        ticker=ticker,
        date=d,
        label_version="v1.0.0",
        entry_price=1000.0,
        tp_price=1050.0,
        sl_price=970.0,
        tp_pct=0.05,
        sl_pct=0.03,
        max_holding_days=10,
        outcome=outcome,
        binary_target=target,
        mfe=0.06,
        mae=0.01,
        holding_days=4,
        realized_return=ret,
    )


def test_dataset_builder_merging():
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 11)
    features = [
        _sample_feature_record("BBCA.JK", d1, 0.01),
        _sample_feature_record("BBCA", d2, 0.02),
        _sample_feature_record("BBRI.JK", d1, -0.01),
    ]
    labels = [
        _sample_label_record("BBCA", d1, target=1, ret=0.05),
        _sample_label_record("BBCA.JK", d2, target=0, outcome="SL", ret=-0.03),
        _sample_label_record("BBRI", d1, target=0, outcome="EXPIRY", ret=0.0),
    ]

    builder = DatasetBuilder()
    dataset = builder.build_from_records(features, labels)

    assert len(dataset) == 3
    assert dataset.X.shape == (3, len(builder.feature_cols))
    assert np.array_equal(dataset.y, np.array([1, 0, 0]))
    assert len(dataset.y_return) == 3

    # Ensure chronological order
    assert dataset.dates[0] <= dataset.dates[-1]


def test_dataset_builder_excludes_ambiguous():
    d = date(2025, 1, 10)
    features = [_sample_feature_record("BBCA", d)]
    labels = [_sample_label_record("BBCA", d, target=0, outcome="AMBIGUOUS")]

    builder = DatasetBuilder(exclude_ambiguous=True)
    dataset = builder.build_from_records(features, labels)
    assert len(dataset) == 0

    builder_keep = DatasetBuilder(exclude_ambiguous=False)
    dataset_keep = builder_keep.build_from_records(features, labels)
    assert len(dataset_keep) == 1


def test_dataset_filter_and_select():
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 11)
    d3 = date(2025, 1, 12)
    features = [
        _sample_feature_record("BBCA", d1),
        _sample_feature_record("BBCA", d2),
        _sample_feature_record("BBCA", d3),
    ]
    labels = [
        _sample_label_record("BBCA", d1),
        _sample_label_record("BBCA", d2),
        _sample_label_record("BBCA", d3),
    ]

    builder = DatasetBuilder()
    dataset = builder.build_from_records(features, labels)
    subset = dataset.select_indices([0, 2])
    assert len(subset) == 2
    assert subset.dates[0] == d1
    assert subset.dates[1] == d3

    date_subset = dataset.filter_by_date_range(start_date=d2, end_date=d3)
    assert len(date_subset) == 2


# =========================================================================
# 3. Baseline ML Models Tests
# =========================================================================


def _synthetic_dataset(n_samples: int = 100, n_features: int = 10):
    rng = np.random.default_rng(42)
    X = rng.standard_normal((n_samples, n_features))
    # Binary target with some true signal
    logits = X[:, 0] * 1.5 - X[:, 1] * 0.8
    probs = 1.0 / (1.0 + np.exp(-logits))
    y = (probs >= 0.5).astype(np.int64)
    y_return = logits * 0.02
    return X, y, y_return


def test_logistic_regression_baseline():
    X, y, _ = _synthetic_dataset(120, 10)
    model = LogisticRegressionBaseline(C=1.0)
    model.fit(X, y)

    prob = model.predict_probability(X)
    assert len(prob) == 120
    assert np.all(prob >= 0.0) and np.all(prob <= 1.0)

    preds = model.predict(X, threshold=0.5)
    assert np.all(np.isin(preds, [0, 1]))


def test_logistic_regression_calibrated():
    X, y, _ = _synthetic_dataset(120, 10)
    model = LogisticRegressionBaseline(C=1.0, calibrated=True)
    model.fit(X, y)

    prob = model.predict_probability(X)
    assert len(prob) == 120
    assert np.all(prob >= 0.0) and np.all(prob <= 1.0)


def test_lightgbm_classifier_baseline():
    X, y, _ = _synthetic_dataset(120, 10)
    model = LightGBMClassifierBaseline(n_estimators=30, max_depth=3)
    model.fit(X, y)

    prob = model.predict_probability(X)
    assert len(prob) == 120
    assert np.all(prob >= 0.0) and np.all(prob <= 1.0)

    preds = model.predict(X, threshold=0.5)
    assert np.all(np.isin(preds, [0, 1]))
    assert model.feature_importances_ is not None


def test_lightgbm_regressor_baseline():
    X, _, y_ret = _synthetic_dataset(120, 10)
    model = LightGBMRegressorBaseline(n_estimators=30, max_depth=3)
    model.fit(X, y_ret)

    preds = model.predict(X)
    assert len(preds) == 120
    assert np.all(np.isfinite(preds))
    assert model.feature_importances_ is not None


def test_ridge_regression_baseline():
    X, _, y_ret = _synthetic_dataset(120, 10)
    model = RidgeRegressionBaseline(alpha=1.0)
    model.fit(X, y_ret)

    preds = model.predict(X)
    assert len(preds) == 120
    assert np.all(np.isfinite(preds))


def test_create_baseline_model_factory():
    clf_lr = create_baseline_model("logistic", task="classification")
    assert isinstance(clf_lr, LogisticRegressionBaseline)

    clf_lgb = create_baseline_model("lightgbm", task="classification")
    assert isinstance(clf_lgb, LightGBMClassifierBaseline)

    reg_lgb = create_baseline_model("lightgbm", task="regression")
    assert isinstance(reg_lgb, LightGBMRegressorBaseline)

    reg_ridge = create_baseline_model("ridge", task="regression")
    assert isinstance(reg_ridge, RidgeRegressionBaseline)

    with pytest.raises(ValueError):
        create_baseline_model("unknown", task="classification")


# =========================================================================
# 4. Evaluation Metrics Tests
# =========================================================================


def test_classification_metrics():
    y_true = np.array([1, 0, 1, 0, 1])
    y_prob = np.array([0.9, 0.1, 0.8, 0.2, 0.7])

    brier = compute_brier_score(y_true, y_prob)
    assert 0.0 <= brier <= 0.1  # very good prediction

    log_loss = compute_log_loss(y_true, y_prob)
    assert log_loss >= 0.0

    auc = compute_roc_auc(y_true, y_prob)
    assert auc == 1.0

    acc = compute_accuracy(y_true, y_prob, threshold=0.5)
    assert acc == 1.0

    ece = compute_expected_calibration_error(y_true, y_prob)
    assert 0.0 <= ece <= 1.0

    conf, obs = compute_calibration_curve(y_true, y_prob, n_bins=5)
    assert len(conf) == len(obs)

    full = evaluate_classification(y_true, y_prob)
    assert "brier_score" in full
    assert "roc_auc" in full
    assert "calibration_error" in full


def test_roc_auc_single_class_fallback():
    # Only 1 class present
    y_single = np.array([1, 1, 1, 1])
    y_prob = np.array([0.5, 0.6, 0.7, 0.8])
    assert compute_roc_auc(y_single, y_prob) == 0.5


def test_regression_metrics():
    y_true = np.array([0.05, -0.02, 0.03, -0.01])
    y_pred = np.array([0.04, -0.01, 0.02, 0.00])

    mse = compute_mse(y_true, y_pred)
    rmse = compute_rmse(y_true, y_pred)
    mae = compute_mae(y_true, y_pred)
    r2 = compute_r2(y_true, y_pred)

    assert mse >= 0.0
    assert rmse >= 0.0
    assert mae >= 0.0
    assert r2 <= 1.0

    full = evaluate_regression(y_true, y_pred)
    assert full["mse"] == mse
    assert full["rmse"] == rmse


# =========================================================================
# 5. Model Registry Tests
# =========================================================================


def test_model_registry_save_load_champion_lifecycle(tmp_path: Path):
    registry = ModelRegistry(registry_dir=tmp_path)

    # 1. Train model 1
    X, y, _ = _synthetic_dataset(50, 5)
    m1 = LogisticRegressionBaseline(C=1.0).fit(X, y)

    meta1 = ModelMetadata(
        model_version="test_lr_v1",
        algorithm="logistic",
        task="classification",
        training_start="2025-01-01",
        training_end="2025-06-30",
        metrics={"brier_score": 0.20, "roc_auc": 0.65},
        status="champion",
    )

    art1_path = registry.save_model(m1, meta1)
    assert art1_path.is_file()

    loaded_m1, loaded_meta1 = registry.load_model("test_lr_v1")
    assert loaded_meta1.status == "champion"
    assert loaded_meta1.algorithm == "logistic"
    assert np.allclose(loaded_m1.predict_probability(X), m1.predict_probability(X))

    # 2. Register challenger model 2 as champion -> model 1 must be demoted
    m2 = LightGBMClassifierBaseline(n_estimators=10).fit(X, y)
    meta2 = ModelMetadata(
        model_version="test_lgb_v2",
        algorithm="lightgbm",
        task="classification",
        training_start="2025-01-01",
        training_end="2025-06-30",
        metrics={"brier_score": 0.15, "roc_auc": 0.72},
        status="champion",
    )
    registry.save_model(m2, meta2)

    # Verify model 2 is champion and model 1 was demoted
    _, meta1_updated = registry.load_model("test_lr_v1")
    assert meta1_updated.status == "challenger"

    champ_model, champ_meta = registry.get_champion("classification")
    assert champ_meta.model_version == "test_lgb_v2"
    assert champ_meta.status == "champion"

    # 3. Promote model 1 back to champion
    promoted_meta = registry.promote_to_champion("test_lr_v1")
    assert promoted_meta.status == "champion"

    _, meta2_demoted = registry.load_model("test_lgb_v2")
    assert meta2_demoted.status == "challenger"


def test_walk_forward_splitter_train_days_equal_purge_days():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(100)]
    splitter = WalkForwardSplitter(n_splits=3, train_days=10, test_days=10, purge_days=10)
    folds = list(splitter.split(dates))
    assert len(folds) == 3
    for train_idx, test_idx in folds:
        assert len(train_idx) == 10
        assert len(test_idx) == 10
        train_dates = [dates[i] for i in train_idx]
        test_dates = [dates[i] for i in test_idx]
        assert max(train_dates) < min(test_dates)
        gap = (min(test_dates) - max(train_dates)).days
        assert gap >= 10


def test_split_chronological_negative_ratios():
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(10)]
    with pytest.raises(ValueError, match="val_ratio must be non-negative"):
        split_chronological(dates, train_ratio=0.7, val_ratio=-0.1, test_ratio=0.2)
    with pytest.raises(ValueError, match="test_ratio must be non-negative"):
        split_chronological(dates, train_ratio=0.7, val_ratio=0.1, test_ratio=-0.2)


def test_unfitted_model_raises_not_fitted_error():
    from sklearn.exceptions import NotFittedError

    X = np.random.randn(5, 5)
    lr = LogisticRegressionBaseline()
    with pytest.raises(NotFittedError):
        lr.predict_probability(X)

    lgb_clf = LightGBMClassifierBaseline()
    with pytest.raises(NotFittedError):
        lgb_clf.predict_probability(X)


def test_model_metadata_status_validation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelMetadata(
            model_version="test_v1",
            algorithm="lightgbm",
            training_start="2025-01-01",
            training_end="2025-06-30",
            status="invalid_status",
        )


def test_calibration_metrics_out_of_bounds_clipping():
    y_true = np.array([1, 0, 1])
    y_prob = np.array([1.05, -0.05, 0.5])
    ece = compute_expected_calibration_error(y_true, y_prob, n_bins=5)
    assert 0.0 <= ece <= 1.0
    conf, obs = compute_calibration_curve(y_true, y_prob, n_bins=5)
    assert np.all(conf >= 0.0) and np.all(conf <= 1.0)


def test_models_with_extreme_imbalance():
    X = np.random.randn(100, 5)
    y = np.zeros(100, dtype=int)
    y[0] = 1

    lr = LogisticRegressionBaseline(calibrated=True).fit(X, y)
    probs_lr = lr.predict_probability(X)
    assert len(probs_lr) == 100
    assert np.all(probs_lr >= 0.0) and np.all(probs_lr <= 1.0)

    lgb = LightGBMClassifierBaseline(n_estimators=10, min_child_samples=5).fit(X, y)
    probs_lgb = lgb.predict_probability(X)
    assert len(probs_lgb) == 100
    assert np.all(probs_lgb >= 0.0) and np.all(probs_lgb <= 1.0)


def test_causal_calibration_with_validation_set():
    X_tr = np.random.randn(100, 5)
    y_tr = np.random.binomial(1, 0.3, 100)
    X_val = np.random.randn(40, 5)
    y_val = np.random.binomial(1, 0.3, 40)
    # Ensure at least 3 samples of each class in val
    y_val[:5] = 1
    y_val[5:10] = 0

    # 1. Logistic regression with validation set
    lr = LogisticRegressionBaseline(calibrated=True).fit(X_tr, y_tr, X_val=X_val, y_val=y_val)
    p_lr = lr.predict_probability(X_val)
    assert len(p_lr) == 40
    assert np.all((p_lr >= 0.0) & (p_lr <= 1.0))

    # 2. LightGBM with validation set and early stopping
    lgbm = LightGBMClassifierBaseline(n_estimators=50, calibrated=True).fit(
        X_tr, y_tr, X_val=X_val, y_val=y_val
    )
    p_lgbm = lgbm.predict_probability(X_val)
    assert len(p_lgbm) == 40
    assert np.all((p_lgbm >= 0.0) & (p_lgbm <= 1.0))
    assert lgbm.feature_importances_ is not None

    # 3. LightGBM regressor with validation set
    reg = LightGBMRegressorBaseline(n_estimators=50).fit(
        X_tr, y_tr.astype(float), X_val=X_val, y_val=y_val.astype(float)
    )
    preds = reg.predict(X_val)
    assert len(preds) == 40
    assert np.all(np.isfinite(preds))

