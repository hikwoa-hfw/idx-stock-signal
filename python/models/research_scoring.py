"""Frozen Research Scoring Estimators for Phase 11F.

Encapsulates feature schema validation (strict 30-feature ordering),
causal median imputation (derived strictly from training data up to cutoff),
and model prediction for LOW_PRICE and HIGHER_PRICE research policies.
"""

from __future__ import annotations

from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer


class BaseResearchScoringModel:
    """Base estimator enforcing strict schema ordering and median imputation."""

    def __init__(
        self,
        mode: str,
        task_type: str,
        score_metric: str,
        feature_schema: list[str],
        imputer: SimpleImputer,
        estimator: Any,
        training_cutoff: str = "2026-09-25",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.mode = mode
        self.task_type = task_type
        self.score_metric = score_metric
        self.feature_schema = list(feature_schema)
        self.feature_names_ = list(feature_schema)
        self.imputer_ = imputer
        self.estimator_ = estimator
        self.training_cutoff = training_cutoff
        self.metadata = metadata or {}

    def _validate_and_transform_X(self, X: Union[pd.DataFrame, np.ndarray, list]) -> np.ndarray:
        """Validates feature columns against feature_schema and applies median imputation."""
        if isinstance(X, pd.DataFrame):
            col_list = list(X.columns)
            missing = [c for c in self.feature_schema if c not in col_list]
            if missing:
                raise ValueError(
                    f"Missing required feature columns for {self.mode}: {missing}"
                )
            unexpected = [c for c in col_list if c not in self.feature_schema]
            if unexpected:
                raise ValueError(
                    f"Unexpected feature columns for {self.mode}: {unexpected}"
                )
            if col_list != self.feature_schema:
                raise ValueError(
                    f"Feature columns reordered for {self.mode}. "
                    f"Must match exact ordered schema ({len(self.feature_schema)} features)."
                )
            X_arr = X[self.feature_schema].to_numpy(dtype=np.float64)
        else:
            X_arr = np.asarray(X, dtype=np.float64)
            if X_arr.ndim == 1:
                X_arr = X_arr.reshape(1, -1)
            if X_arr.shape[1] != len(self.feature_schema):
                raise ValueError(
                    f"Expected {len(self.feature_schema)} features, got {X_arr.shape[1]}"
                )

        if len(X_arr) == 0:
            return np.empty((0, len(self.feature_schema)), dtype=np.float64)

        # Apply strictly causal median imputation from training dataset
        return self.imputer_.transform(X_arr)


class ResearchRegressorModel(BaseResearchScoringModel):
    """LOW_PRICE H=15 Variant B Return Regressor model wrapper."""

    def __init__(
        self,
        feature_schema: list[str],
        imputer: SimpleImputer,
        estimator: Any,
        training_cutoff: str = "2026-09-25",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            mode="LOW_PRICE",
            task_type="regression",
            score_metric="pred_return_lgb",
            feature_schema=feature_schema,
            imputer=imputer,
            estimator=estimator,
            training_cutoff=training_cutoff,
            metadata=metadata,
        )

    def predict(self, X: Union[pd.DataFrame, np.ndarray, list]) -> np.ndarray:
        """Predicts expected return (pred_return_lgb)."""
        X_imp = self._validate_and_transform_X(X)
        if len(X_imp) == 0:
            return np.empty((0,), dtype=np.float64)
        preds = self.estimator_.predict(X_imp)
        return np.asarray(preds, dtype=np.float64)


class ResearchClassifierModel(BaseResearchScoringModel):
    """HIGHER_PRICE H=15 Variant B Full-Feature Classifier model wrapper."""

    def __init__(
        self,
        feature_schema: list[str],
        imputer: SimpleImputer,
        estimator: Any,
        training_cutoff: str = "2026-09-25",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            mode="HIGHER_PRICE",
            task_type="classification",
            score_metric="prob_lgb_full",
            feature_schema=feature_schema,
            imputer=imputer,
            estimator=estimator,
            training_cutoff=training_cutoff,
            metadata=metadata,
        )
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X: Union[pd.DataFrame, np.ndarray, list]) -> np.ndarray:
        """Returns 2D class probabilities [P(y=0), P(y=1)]."""
        X_imp = self._validate_and_transform_X(X)
        if len(X_imp) == 0:
            return np.empty((0, 2), dtype=np.float64)
        if hasattr(self.estimator_, "predict_proba"):
            return self.estimator_.predict_proba(X_imp)
        # Fallback if estimator only has predict_probability
        p1 = self.estimator_.predict_probability(X_imp)
        return np.column_stack([1.0 - p1, p1])

    def predict_probability(self, X: Union[pd.DataFrame, np.ndarray, list]) -> np.ndarray:
        """Returns 1D positive event probabilities (prob_lgb_full)."""
        proba = self.predict_proba(X)
        return np.clip(proba[:, 1], 0.0, 1.0)

    def predict(
        self, X: Union[pd.DataFrame, np.ndarray, list], threshold: float = 0.5
    ) -> np.ndarray:
        """Returns binary predictions using threshold."""
        probs = self.predict_probability(X)
        return (probs >= threshold).astype(np.int64)
