from pathlib import Path

import numpy as np

from python.data.provider import DEFAULT_UNIVERSE, MockMarketDataProvider
from python.features.engine import FeatureEngine
from python.labels.engine import LabelEngine
from python.models.baseline import (
    LightGBMClassifierBaseline,
    LightGBMRegressorBaseline,
    LogisticRegressionBaseline,
)
from python.models.dataset import DatasetBuilder
from python.models.metrics import evaluate_classification, evaluate_regression
from python.models.registry import ModelMetadata, ModelRegistry
from python.models.validation import split_chronological


def test_end_to_end_model_pipeline(tmp_path: Path):
    # 1. Ingest mock bars
    provider = MockMarketDataProvider(days=80)
    universe_bars = {}
    all_bars = []
    for ticker in DEFAULT_UNIVERSE:
        bars = provider.get_daily_bars(ticker)
        universe_bars[ticker] = bars
        all_bars.extend(bars)

    assert len(all_bars) > 0

    # 2. Features & Labels
    feat_engine = FeatureEngine()
    features_by_ticker = feat_engine.compute_universe_features(universe_bars)
    features = []
    for recs in features_by_ticker.values():
        features.extend(recs)

    lbl_engine = LabelEngine()
    labels = lbl_engine.compute_labels(all_bars)

    assert len(features) > 0
    assert len(labels) > 0

    # 3. Dataset Builder
    builder = DatasetBuilder()
    dataset = builder.build_from_records(features, labels)

    assert len(dataset) > 50
    assert dataset.X.shape[1] == len(builder.feature_cols)

    # 4. Strictly Chronological Split with Purge Window
    train_idx, val_idx, test_idx = split_chronological(
        dates=dataset.dates,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        purge_days=5,
    )

    assert len(train_idx) > 0
    assert len(val_idx) > 0
    assert len(test_idx) > 0

    train_ds = dataset.select_indices(train_idx)
    val_ds = dataset.select_indices(val_idx)
    test_ds = dataset.select_indices(test_idx)

    # Assert no lookahead overlap
    assert max(train_ds.dates) < min(val_ds.dates)
    assert max(val_ds.dates) < min(test_ds.dates)
    assert (min(val_ds.dates) - max(train_ds.dates)).days >= 5
    assert (min(test_ds.dates) - max(val_ds.dates)).days >= 5

    # 5. Train Classification Baseline (Logistic Regression)
    lr_clf = LogisticRegressionBaseline(C=1.0)
    lr_clf.fit(train_ds.X, train_ds.y, feature_names=dataset.feature_names)
    lr_probs = lr_clf.predict_probability(test_ds.X)
    assert np.all(lr_probs >= 0.0) and np.all(lr_probs <= 1.0)

    lr_metrics = evaluate_classification(test_ds.y, lr_probs)
    assert 0.0 <= lr_metrics["brier_score"] <= 1.0
    assert 0.0 <= lr_metrics["calibration_error"] <= 1.0

    # 6. Train Classification Baseline (LightGBM)
    lgb_clf = LightGBMClassifierBaseline(n_estimators=30, max_depth=3)
    lgb_clf.fit(train_ds.X, train_ds.y, feature_names=dataset.feature_names)
    lgb_probs = lgb_clf.predict_probability(test_ds.X)
    assert np.all(lgb_probs >= 0.0) and np.all(lgb_probs <= 1.0)

    lgb_metrics = evaluate_classification(test_ds.y, lgb_probs)
    assert 0.0 <= lgb_metrics["brier_score"] <= 1.0

    # 7. Train Regression Baseline (LightGBM)
    lgb_reg = LightGBMRegressorBaseline(n_estimators=30, max_depth=3)
    lgb_reg.fit(train_ds.X, train_ds.y_return, feature_names=dataset.feature_names)
    reg_preds = lgb_reg.predict(test_ds.X)
    reg_metrics = evaluate_regression(test_ds.y_return, reg_preds)
    assert reg_metrics["mse"] >= 0.0
    assert reg_metrics["mae"] >= 0.0

    # 8. Model Registry persistence & loading
    registry = ModelRegistry(registry_dir=tmp_path)
    metadata = ModelMetadata(
        model_version="lgb_champion_v1",
        algorithm="lightgbm",
        task="classification",
        training_start=str(min(train_ds.dates)),
        training_end=str(max(train_ds.dates)),
        validation_start=str(min(val_ds.dates)),
        validation_end=str(max(val_ds.dates)),
        metrics=lgb_metrics,
        status="champion",
        feature_names=dataset.feature_names,
    )

    art_path = registry.save_model(lgb_clf, metadata)
    assert art_path.is_file()

    loaded_model, loaded_meta = registry.load_model("lgb_champion_v1")
    assert loaded_meta.status == "champion"
    assert loaded_meta.algorithm == "lightgbm"

    # Verify predictions on unseen test dataset match exact in-memory outputs
    loaded_probs = loaded_model.predict_probability(test_ds.X)
    assert np.allclose(loaded_probs, lgb_probs)


def test_cli_train_model_execution(monkeypatch, tmp_path: Path):
    from scripts.train_model import main

    test_args = [
        "train_model.py",
        "--model-type",
        "lightgbm",
        "--task",
        "classification",
        "--model-version",
        "cli_test_model",
        "--train-ratio",
        "0.70",
        "--val-ratio",
        "0.15",
        "--test-ratio",
        "0.15",
        "--purge-days",
        "3",
        "--save-registry",
        "--set-champion",
        "--ticker",
        "BBCA",
        "BBRI",
    ]
    monkeypatch.setattr("sys.argv", test_args)
    monkeypatch.setattr("python.config.settings.settings.model_registry_path", tmp_path)

    # Run main CLI
    main()

    # Check registered artifacts
    registry = ModelRegistry(registry_dir=tmp_path)
    loaded_model, loaded_meta = registry.load_model("cli_test_model")
    assert loaded_meta.status == "champion"
    assert loaded_meta.algorithm == "lightgbm"
    assert "brier_score" in loaded_meta.metrics


def test_cli_train_model_with_custom_tickers(monkeypatch, tmp_path: Path):
    from scripts.train_model import main

    test_args = [
        "train_model.py",
        "--model-type",
        "logistic",
        "--task",
        "classification",
        "--model-version",
        "cli_custom_tickers_model",
        "--save-registry",
        "--ticker",
        "INCO.JK",
        "ANTM",
    ]
    monkeypatch.setattr("sys.argv", test_args)
    monkeypatch.setattr("python.config.settings.settings.model_registry_path", tmp_path)
    monkeypatch.setattr(
        "python.config.settings.settings.database_url", f"sqlite:///{tmp_path}/empty.db"
    )

    main()

    registry = ModelRegistry(registry_dir=tmp_path)
    loaded_model, loaded_meta = registry.load_model("cli_custom_tickers_model")
    assert loaded_meta.model_version == "cli_custom_tickers_model"
    assert loaded_meta.algorithm == "logistic"
