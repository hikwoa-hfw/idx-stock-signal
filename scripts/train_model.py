import argparse
from datetime import datetime
from typing import Optional

from python.config.settings import settings
from python.data.provider import DEFAULT_UNIVERSE, MockMarketDataProvider
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.features.repository import FeatureRepository
from python.labels.engine import LabelEngine
from python.labels.repository import LabelRepository
from python.models.baseline import create_baseline_model
from python.models.dataset import Dataset, DatasetBuilder
from python.models.metrics import evaluate_classification, evaluate_regression
from python.models.registry import ModelMetadata, ModelRegistry
from python.models.validation import split_chronological


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train baseline classification or regression models on BEI stock data."
    )
    parser.add_argument(
        "--model-type",
        choices=["logistic", "lightgbm", "ridge"],
        default="lightgbm",
        help="Algorithm: logistic, lightgbm, or ridge",
    )
    parser.add_argument(
        "--task",
        choices=["classification", "regression"],
        default="classification",
        help="Task: classification (P(TP before SL)) or regression (expected return)",
    )
    parser.add_argument(
        "--model-version",
        default=None,
        help="Model version string (e.g. baseline_lgbm_v1). Defaults to auto-generated.",
    )
    parser.add_argument(
        "--dataset-version",
        default="v1.0.0",
        help="Dataset version tag for registry metadata.",
    )
    parser.add_argument(
        "--feature-version",
        default="v1.0.0",
        help="Feature version tag for registry metadata.",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
        help="Fraction of dates for training (default: 0.70).",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Fraction of dates for validation (default: 0.15).",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Fraction of dates for testing (default: 0.15).",
    )
    parser.add_argument(
        "--purge-days",
        type=int,
        default=10,
        help="Purge window in trading days to eliminate target overlap (default: 10).",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Calibrate classifier probabilities using Platt scaling / sigmoid.",
    )
    parser.add_argument(
        "--save-registry",
        action="store_true",
        help="Persist trained model artifact and metadata into model registry.",
    )
    parser.add_argument(
        "--set-champion",
        action="store_true",
        help="Register model with status=champion (demotes existing champions).",
    )
    parser.add_argument(
        "--ticker",
        nargs="+",
        help="Tickers to train on (e.g. BBCA BBRI BMRI).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLite database URL. Defaults to settings.database_url.",
    )
    return parser.parse_args()


def load_or_generate_dataset(
    db_url: Optional[str] = None,
    tickers: Optional[list[str]] = None,
) -> Dataset:
    db = db_url or settings.database_url
    feat_repo = FeatureRepository(db)
    lbl_repo = LabelRepository(db)
    bar_repo = DailyBarRepository(db)

    feat_count = feat_repo.count_features()
    lbl_count = lbl_repo.count_labels()

    builder = DatasetBuilder()

    if feat_count > 0 and lbl_count > 0:
        dataset = builder.build_from_db(
            feature_repo=feat_repo,
            label_repo=lbl_repo,
            tickers=tickers,
        )
        if len(dataset) > 0:
            return dataset

    # Fallback to generating features and labels on the fly
    target_tickers = [t.strip().upper().removesuffix(".JK") for t in (tickers or DEFAULT_UNIVERSE)]
    universe_bars: dict[str, list] = {}
    all_bars = []
    for t in target_tickers:
        bars = bar_repo.get_daily_bars(t)
        if bars:
            universe_bars[t] = bars
            all_bars.extend(bars)

    if not universe_bars:
        mock = MockMarketDataProvider(universe=target_tickers, days=80)
        for t in target_tickers:
            bars = mock.get_daily_bars(t)
            if bars:
                universe_bars[t] = bars
                all_bars.extend(bars)

    feat_engine = FeatureEngine()
    features_by_ticker = feat_engine.compute_universe_features(universe_bars)
    features = []
    for t_recs in features_by_ticker.values():
        features.extend(t_recs)

    lbl_engine = LabelEngine()
    labels = lbl_engine.compute_labels(all_bars)

    return builder.build_from_records(features, labels)


def main() -> None:
    args = parse_args()

    # Model type validation against task
    if args.task == "regression" and args.model_type == "logistic":
        print("[train_model] Error: Logistic regression does not support regression task.")
        return
    if args.task == "classification" and args.model_type == "ridge":
        print("[train_model] Error: Ridge regression does not support classification task.")
        return

    print("=" * 65)
    print(" AI BEI Stock Signal — Model Training Pipeline (Phase 4)")
    print("=" * 65)
    print(f"Task:              {args.task}")
    print(f"Algorithm:         {args.model_type}")
    print(f"Calibrated:        {args.calibrate}")
    print(f"Purge Days:        {args.purge_days}")
    ratios_str = (
        f"Train={args.train_ratio:.2f}, Val={args.val_ratio:.2f}, Test={args.test_ratio:.2f}"
    )
    print(f"Split Ratios:      {ratios_str}")

    dataset = load_or_generate_dataset(db_url=args.db_url, tickers=args.ticker)
    if len(dataset) == 0:
        print("[train_model] Error: No valid samples found to train model.")
        return

    print(f"Total Samples:     {len(dataset)} across {len(set(dataset.tickers))} tickers")
    print(f"Date Span:         {min(dataset.dates)} -> {max(dataset.dates)}")
    print(f"Feature Dimensions:{dataset.X.shape[1]}")

    # Chronological Split
    train_idx, val_idx, test_idx = split_chronological(
        dates=dataset.dates,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        purge_days=args.purge_days,
    )

    if len(train_idx) == 0 or len(test_idx) == 0:
        print("[train_model] Error: Chronological split resulted in empty train or test set.")
        return

    train_ds = dataset.select_indices(train_idx)
    val_ds = dataset.select_indices(val_idx) if len(val_idx) > 0 else None
    test_ds = dataset.select_indices(test_idx)

    train_span = f"{min(train_ds.dates)} to {max(train_ds.dates)}"
    print(f"\nTrain Set:         {len(train_ds)} rows ({train_span})")
    if val_ds and len(val_ds) > 0:
        val_span = f"{min(val_ds.dates)} to {max(val_ds.dates)}"
        print(f"Validation Set:    {len(val_ds)} rows ({val_span})")
    test_span = f"{min(test_ds.dates)} to {max(test_ds.dates)}"
    print(f"Test Set:          {len(test_ds)} rows ({test_span})")

    # Initialize model
    kwargs = {}
    if args.task == "classification" and args.calibrate:
        kwargs["calibrated"] = True

    model = create_baseline_model(
        model_type=args.model_type,
        task=args.task,
        **kwargs,
    )

    # Train
    y_train = train_ds.y if args.task == "classification" else train_ds.y_return
    y_test = test_ds.y if args.task == "classification" else test_ds.y_return

    model.fit(train_ds.X, y_train, feature_names=dataset.feature_names)

    # Evaluate on Unseen Test Set
    print("\n--- Evaluation on Unseen Test Data ---")
    if args.task == "classification":
        y_prob = model.predict_probability(test_ds.X)
        metrics = evaluate_classification(y_test, y_prob)
        print(f"  Brier Score:       {metrics['brier_score']:.4f}")
        print(f"  Log Loss:          {metrics['log_loss']:.4f}")
        print(f"  ROC-AUC:           {metrics['roc_auc']:.4f}")
        print(f"  Accuracy:          {metrics['accuracy']:.4f}")
        print(f"  Calibration Error: {metrics['calibration_error']:.4f}")
    else:
        y_pred = model.predict(test_ds.X)
        metrics = evaluate_regression(y_test, y_pred)
        print(f"  MSE:               {metrics['mse']:.6f}")
        print(f"  RMSE:              {metrics['rmse']:.6f}")
        print(f"  MAE:               {metrics['mae']:.6f}")
        print(f"  R2 Score:          {metrics['r2']:.4f}")

    # Register Model
    if args.save_registry:
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = args.model_version or f"{args.model_type}_{args.task}_{now_str}"
        status = "champion" if args.set_champion else "challenger"

        metadata = ModelMetadata(
            model_version=version,
            algorithm=args.model_type,
            task=args.task,
            dataset_version=args.dataset_version,
            feature_version=args.feature_version,
            training_start=str(min(train_ds.dates)),
            training_end=str(max(train_ds.dates)),
            validation_start=str(min(val_ds.dates)) if val_ds and len(val_ds) > 0 else None,
            validation_end=str(max(val_ds.dates)) if val_ds and len(val_ds) > 0 else None,
            metrics=metrics,
            status=status,
            feature_names=dataset.feature_names,
        )

        registry = ModelRegistry()
        saved_path = registry.save_model(model, metadata)
        print("\n[Registry] Model registered successfully!")
        print(f"  Version:  {metadata.model_version}")
        print(f"  Status:   {metadata.status}")
        print(f"  Artifact: {saved_path}")


if __name__ == "__main__":
    main()
