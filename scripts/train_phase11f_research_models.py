"""Training script for Phase 11F H=15 Variant B Research Scoring Models.

Reconstructs, fits, and serializes the two primary research estimators:
1. LOW_PRICE: H=15 Variant B LightGBM Return Regressor (score metric: pred_return_lgb)
2. HIGHER_PRICE: H=15 Variant B Full-Feature LightGBM Classifier (score metric: prob_lgb_full)

Contract:
- Training period: 2023-01-02 to 2026-09-25 (all 15-day forward horizons fully observable).
- Features: Exact FEATURE_SCHEMA_30 ordering.
- Imputation: Strictly causal median imputation from training dataset up to cutoff.
- Output directory: artifacts/phase_11f/research_models/
- Production isolation: Never writes to models/registry/ or alters production champions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import joblib
import numpy as np
from sklearn.impute import SimpleImputer

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.experiments.multi_horizon_eval import MultiHorizonEvaluationRunner
from python.experiments.paper_trading import FEATURE_SCHEMA_30
from python.models.baseline import (
    LightGBMClassifierBaseline,
    LightGBMRegressorBaseline,
)
from python.models.research_scoring import (
    ResearchClassifierModel,
    ResearchRegressorModel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("train_phase11f_research_models")


def get_git_commit() -> str:
    """Retrieves current git commit hash, with fallback."""
    try:
        res = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return res
    except Exception:
        return "UNKNOWN_COMMIT"


def compute_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a binary file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def train_research_models(
    db_path: Optional[str] = None,
    output_dir: Union[str, Path] = "artifacts/phase_11f/research_models",
    cutoff_date: str = "2026-09-25",
    start_date: str = "2023-01-02",
    random_state: int = 42,
) -> dict[str, Any]:
    """Trains and serializes H=15 Variant B research scoring models."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
    d_cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d").date()

    logger.info("Initializing MultiHorizonEvaluationRunner (db: %s)...", db_path or "default")
    runner = MultiHorizonEvaluationRunner(
        db_path=db_path,
        random_state=random_state,
    )

    metadata: dict[str, Any] = {
        "title": "Phase 11F H=15 Variant B Frozen Research Scoring Models",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "training_start_date": str(d_start),
        "training_cutoff_date": str(d_cutoff),
        "target_contract": "Variant B (Next-Session Open Market-On-Open, H=15, TP +5%, SL -2%)",
        "feature_schema": FEATURE_SCHEMA_30,
        "feature_count": len(FEATURE_SCHEMA_30),
        "imputation_strategy": "median (strictly derived from training dataset <= cutoff)",
        "random_state": random_state,
        "models": {},
    }

    # -------------------------------------------------------------------------
    # 1. LOW_PRICE: LightGBM Regressor H=15 (score: pred_return_lgb)
    # -------------------------------------------------------------------------
    logger.info("Loading multi-horizon dataset for LOW_PRICE...")
    df_low, _ = runner.load_multi_horizon_data("LOW_PRICE", horizons=[15])

    mask_tr_low = (df_low["date"] >= d_start) & (df_low["date"] <= d_cutoff)
    df_tr_low = df_low[mask_tr_low].copy()
    mask_valid_low = df_tr_low["vb_status_15"] == "VALID"
    df_tr_low_valid = df_tr_low[mask_valid_low].copy()

    total_low = len(df_tr_low)
    valid_low = len(df_tr_low_valid)
    logger.info(
        "LOW_PRICE: %d total rows in training range, %d valid executable Variant B rows",
        total_low,
        valid_low,
    )

    # Imputer fit strictly on training feature matrix
    X_tr_low_raw = df_tr_low[FEATURE_SCHEMA_30].to_numpy(dtype=np.float64)
    imputer_low = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
    imputer_low.fit(X_tr_low_raw)

    X_tr_low_valid_imp = imputer_low.transform(
        df_tr_low_valid[FEATURE_SCHEMA_30].to_numpy(dtype=np.float64)
    )
    y_tr_low_valid = df_tr_low_valid["vb_realized_net_15"].to_numpy(dtype=np.float64)

    logger.info(
        "Fitting LightGBM Regressor Baseline (100 est, lr=0.05, depth=5)..."
    )
    reg_estimator = LightGBMRegressorBaseline(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        num_leaves=31,
        min_child_samples=20,
        random_state=random_state,
    )
    reg_estimator.fit(X_tr_low_valid_imp, y_tr_low_valid, feature_names=FEATURE_SCHEMA_30)

    reg_wrapper = ResearchRegressorModel(
        feature_schema=FEATURE_SCHEMA_30,
        imputer=imputer_low,
        estimator=reg_estimator,
        training_cutoff=str(d_cutoff),
        metadata={
            "train_samples_total": total_low,
            "train_samples_valid": valid_low,
            "mean_net_return": float(np.mean(y_tr_low_valid)),
            "std_net_return": float(np.std(y_tr_low_valid)),
        },
    )

    reg_artifact_path = out_path / "lgb_regressor_h15_variant_b.joblib"
    joblib.dump(reg_wrapper, reg_artifact_path)
    reg_sha256 = compute_file_sha256(reg_artifact_path)
    logger.info("Saved LOW_PRICE regressor to %s (SHA256: %s)", reg_artifact_path, reg_sha256)

    repo_root = Path(__file__).resolve().parent.parent
    reg_rel_path = reg_artifact_path.resolve().relative_to(repo_root.resolve()).as_posix()

    metadata["models"]["LOW_PRICE"] = {
        "artifact_path": reg_rel_path,
        "sha256": reg_sha256,
        "task_type": "regression",
        "score_metric": "pred_return_lgb",
        "train_samples_total": total_low,
        "train_samples_valid": valid_low,
        "mean_net_return": float(np.mean(y_tr_low_valid)),
        "std_net_return": float(np.std(y_tr_low_valid)),
        "min_net_return": float(np.min(y_tr_low_valid)),
        "max_net_return": float(np.max(y_tr_low_valid)),
        "hyperparameters": {
            "n_estimators": 100,
            "learning_rate": 0.05,
            "max_depth": 5,
            "num_leaves": 31,
            "min_child_samples": 20,
            "random_state": random_state,
        },
    }

    # -------------------------------------------------------------------------
    # 2. HIGHER_PRICE: Full-Feature LightGBM Classifier H=15 (score: prob_lgb_full)
    # -------------------------------------------------------------------------
    logger.info("Loading multi-horizon dataset for HIGHER_PRICE...")
    df_high, _ = runner.load_multi_horizon_data("HIGHER_PRICE", horizons=[15])

    mask_tr_high = (df_high["date"] >= d_start) & (df_high["date"] <= d_cutoff)
    df_tr_high = df_high[mask_tr_high].copy()
    mask_valid_high = df_tr_high["vb_status_15"] == "VALID"
    df_tr_high_valid = df_tr_high[mask_valid_high].copy()

    total_high = len(df_tr_high)
    valid_high = len(df_tr_high_valid)
    logger.info(
        "HIGHER_PRICE: %d total rows in training range, %d valid executable Variant B rows",
        total_high,
        valid_high,
    )

    X_tr_high_raw = df_tr_high[FEATURE_SCHEMA_30].to_numpy(dtype=np.float64)
    imputer_high = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
    imputer_high.fit(X_tr_high_raw)

    X_tr_high_valid_imp = imputer_high.transform(
        df_tr_high_valid[FEATURE_SCHEMA_30].to_numpy(dtype=np.float64)
    )
    y_tr_high_valid = df_tr_high_valid["vb_binary_target_15"].to_numpy(dtype=np.int64)

    pos_high = int(np.sum(y_tr_high_valid))
    prev_high = float(np.mean(y_tr_high_valid))
    logger.info(
        "HIGHER_PRICE positives: %d / %d (prevalence: %.4f)",
        pos_high,
        valid_high,
        prev_high,
    )

    logger.info(
        "Fitting LightGBM Classifier Baseline (100 est, lr=0.05, depth=5)..."
    )
    clf_estimator = LightGBMClassifierBaseline(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        num_leaves=31,
        min_child_samples=20,
        random_state=random_state,
        calibrated=False,
    )
    clf_estimator.fit(X_tr_high_valid_imp, y_tr_high_valid, feature_names=FEATURE_SCHEMA_30)

    clf_wrapper = ResearchClassifierModel(
        feature_schema=FEATURE_SCHEMA_30,
        imputer=imputer_high,
        estimator=clf_estimator,
        training_cutoff=str(d_cutoff),
        metadata={
            "train_samples_total": total_high,
            "train_samples_valid": valid_high,
            "positive_samples": pos_high,
            "prevalence": prev_high,
        },
    )

    clf_artifact_path = out_path / "lgb_full_classifier_h15_variant_b.joblib"
    joblib.dump(clf_wrapper, clf_artifact_path)
    clf_sha256 = compute_file_sha256(clf_artifact_path)
    clf_rel_path = clf_artifact_path.resolve().relative_to(repo_root.resolve()).as_posix()

    metadata["models"]["HIGHER_PRICE"] = {
        "artifact_path": clf_rel_path,
        "sha256": clf_sha256,
        "task_type": "classification",
        "score_metric": "prob_lgb_full",
        "train_samples_total": total_high,
        "train_samples_valid": valid_high,
        "positive_samples": pos_high,
        "prevalence": prev_high,
        "hyperparameters": {
            "n_estimators": 100,
            "learning_rate": 0.05,
            "max_depth": 5,
            "num_leaves": 31,
            "min_child_samples": 20,
            "random_state": random_state,
            "calibrated": False,
        },
    }

    # -------------------------------------------------------------------------
    # 3. Export Metadata JSON
    # -------------------------------------------------------------------------
    meta_path = out_path / "research_model_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
    logger.info("Saved metadata JSON to %s", meta_path)

    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit and serialize Phase 11F frozen research scoring models"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: resolves from settings)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/phase_11f/research_models",
        help="Directory to save research model artifacts",
    )
    parser.add_argument(
        "--cutoff-date",
        type=str,
        default="2026-09-25",
        help="Fixed training cutoff date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2023-01-02",
        help="Training start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_research_models(
        db_path=args.db_path,
        output_dir=args.output_dir,
        cutoff_date=args.cutoff_date,
        start_date=args.start_date,
        random_state=args.seed,
    )


if __name__ == "__main__":
    main()
