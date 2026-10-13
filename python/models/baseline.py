from typing import Any, Optional, Union

import lightgbm as lgb
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.exceptions import NotFittedError
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class LogisticRegressionBaseline:
    """Logistic Regression baseline classifier for event probability P(TP before SL)."""

    def __init__(
        self,
        C: float = 1.0,
        max_iter: int = 1000,
        random_state: int = 42,
        calibrated: bool = False,
        calibration_method: str = "sigmoid",
    ) -> None:
        self.C = C
        self.max_iter = max_iter
        self.random_state = random_state
        self.calibrated = calibrated
        self.calibration_method = calibration_method
        self.feature_names_: list[str] = []
        self.constant_class_: Optional[int] = None
        self.fitted_model_: Any = None

    def _build_base_pipeline(self) -> Pipeline:
        return Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0),
                ),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        C=self.C,
                        max_iter=self.max_iter,
                        random_state=self.random_state,
                        solver="lbfgs",
                    ),
                ),
            ]
        )

    def fit(
        self,
        X: Union[np.ndarray, list],
        y: Union[np.ndarray, list],
        feature_names: Optional[list[str]] = None,
    ) -> "LogisticRegressionBaseline":
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.int64)
        if len(X_arr) == 0:
            raise ValueError("Cannot fit on empty dataset")
        self.feature_names_ = feature_names or [f"feature_{i}" for i in range(X_arr.shape[1])]

        unique_classes = np.unique(y_arr)
        if len(unique_classes) < 2:
            self.constant_class_ = int(unique_classes[0])
            self.fitted_model_ = None
            return self

        self.constant_class_ = None
        base_pipe = self._build_base_pipeline()
        counts = np.bincount(y_arr)
        min_count = int(np.min(counts)) if len(counts) > 1 else 0

        if self.calibrated and min_count >= 3:
            self.fitted_model_ = CalibratedClassifierCV(
                estimator=base_pipe,
                method=self.calibration_method,
                cv=3,
            )
        else:
            self.fitted_model_ = base_pipe

        self.fitted_model_.fit(X_arr, y_arr)
        return self

    def predict_proba(self, X: Union[np.ndarray, list]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if len(X_arr) == 0:
            return np.empty((0, 2), dtype=np.float64)
        constant_cls = getattr(self, "constant_class_", None)
        if constant_cls is not None:
            p = np.zeros((len(X_arr), 2), dtype=np.float64)
            p[:, min(constant_cls, 1)] = 1.0
            return p

        if self.fitted_model_ is None:
            raise NotFittedError(
                "LogisticRegressionBaseline is not fitted yet. Call 'fit' before predicting."
            )
        return self.fitted_model_.predict_proba(X_arr)

    def predict_probability(self, X: Union[np.ndarray, list]) -> np.ndarray:
        """Returns 1D array of positive class probability P(y=1) bounded in [0, 1]."""
        proba = self.predict_proba(X)
        if len(proba) == 0:
            return np.empty((0,), dtype=np.float64)
        p = proba[:, 1]
        return np.clip(p, 0.0, 1.0)

    def predict(self, X: Union[np.ndarray, list], threshold: float = 0.5) -> np.ndarray:
        probs = self.predict_probability(X)
        return (probs >= threshold).astype(np.int64)


class LightGBMClassifierBaseline:
    """LightGBM Classifier baseline for event probability P(TP before SL)."""

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        random_state: int = 42,
        calibrated: bool = False,
        calibration_method: str = "sigmoid",
    ) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.min_child_samples = min_child_samples
        self.random_state = random_state
        self.calibrated = calibrated
        self.calibration_method = calibration_method
        self.feature_names_: list[str] = []
        self.constant_class_: Optional[int] = None
        self.fitted_model_: Any = None

    def _build_base_model(self) -> lgb.LGBMClassifier:
        return lgb.LGBMClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            num_leaves=self.num_leaves,
            min_child_samples=self.min_child_samples,
            random_state=self.random_state,
            objective="binary",
            verbose=-1,
        )

    def fit(
        self,
        X: Union[np.ndarray, list],
        y: Union[np.ndarray, list],
        feature_names: Optional[list[str]] = None,
    ) -> "LightGBMClassifierBaseline":
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.int64)
        if len(X_arr) == 0:
            raise ValueError("Cannot fit on empty dataset")
        self.feature_names_ = feature_names or [f"feature_{i}" for i in range(X_arr.shape[1])]

        unique_classes = np.unique(y_arr)
        if len(unique_classes) < 2:
            self.constant_class_ = int(unique_classes[0])
            self.fitted_model_ = None
            return self

        self.constant_class_ = None
        base_lgbm = self._build_base_model()
        counts = np.bincount(y_arr)
        min_count = int(np.min(counts)) if len(counts) > 1 else 0

        if self.calibrated and min_count >= 3:
            self.fitted_model_ = CalibratedClassifierCV(
                estimator=base_lgbm,
                method=self.calibration_method,
                cv=3,
            )
        else:
            self.fitted_model_ = base_lgbm

        self.fitted_model_.fit(X_arr, y_arr)
        return self

    def predict_proba(self, X: Union[np.ndarray, list]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if len(X_arr) == 0:
            return np.empty((0, 2), dtype=np.float64)
        constant_cls = getattr(self, "constant_class_", None)
        if constant_cls is not None:
            p = np.zeros((len(X_arr), 2), dtype=np.float64)
            p[:, min(constant_cls, 1)] = 1.0
            return p

        fitted = getattr(self, "fitted_model_", None) or getattr(self, "model", None)
        if fitted is None:
            raise NotFittedError(
                "LightGBMClassifierBaseline is not fitted yet. Call 'fit' before predicting."
            )
        return fitted.predict_proba(X_arr)

    def predict_probability(self, X: Union[np.ndarray, list]) -> np.ndarray:
        """Returns 1D array of positive class probability P(y=1) bounded in [0, 1]."""
        proba = self.predict_proba(X)
        if len(proba) == 0:
            return np.empty((0,), dtype=np.float64)
        p = proba[:, 1]
        return np.clip(p, 0.0, 1.0)

    def predict(self, X: Union[np.ndarray, list], threshold: float = 0.5) -> np.ndarray:
        probs = self.predict_probability(X)
        return (probs >= threshold).astype(np.int64)

    @property
    def feature_importances_(self) -> Optional[np.ndarray]:
        fitted = getattr(self, "fitted_model_", None) or getattr(self, "model", None)
        if (
            not getattr(self, "calibrated", False)
            and fitted is not None
            and hasattr(fitted, "feature_importances_")
        ):
            return fitted.feature_importances_
        return None


class LightGBMRegressorBaseline:
    """LightGBM Regressor baseline predicting expected return."""

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        num_leaves: int = 31,
        min_child_samples: int = 20,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.min_child_samples = min_child_samples
        self.random_state = random_state

        self.model = lgb.LGBMRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            num_leaves=self.num_leaves,
            min_child_samples=self.min_child_samples,
            random_state=self.random_state,
            objective="regression",
            verbose=-1,
        )
        self.feature_names_: list[str] = []

    def fit(
        self,
        X: Union[np.ndarray, list],
        y: Union[np.ndarray, list],
        feature_names: Optional[list[str]] = None,
    ) -> "LightGBMRegressorBaseline":
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        if len(X_arr) == 0:
            raise ValueError("Cannot fit on empty dataset")
        self.feature_names_ = feature_names or [f"feature_{i}" for i in range(X_arr.shape[1])]
        self.model.fit(X_arr, y_arr)
        return self

    def predict(self, X: Union[np.ndarray, list]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if len(X_arr) == 0:
            return np.empty((0,), dtype=np.float64)
        return self.model.predict(X_arr)

    @property
    def feature_importances_(self) -> Optional[np.ndarray]:
        if hasattr(self.model, "feature_importances_"):
            return self.model.feature_importances_
        return None


class RidgeRegressionBaseline:
    """Ridge Regression baseline predicting expected return."""

    def __init__(self, alpha: float = 1.0, random_state: int = 42) -> None:
        self.alpha = alpha
        self.random_state = random_state
        self.model = Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0),
                ),
                ("scaler", StandardScaler()),
                ("reg", Ridge(alpha=self.alpha, random_state=self.random_state)),
            ]
        )
        self.feature_names_: list[str] = []

    def fit(
        self,
        X: Union[np.ndarray, list],
        y: Union[np.ndarray, list],
        feature_names: Optional[list[str]] = None,
    ) -> "RidgeRegressionBaseline":
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        if len(X_arr) == 0:
            raise ValueError("Cannot fit on empty dataset")
        self.feature_names_ = feature_names or [f"feature_{i}" for i in range(X_arr.shape[1])]
        self.model.fit(X_arr, y_arr)
        return self

    def predict(self, X: Union[np.ndarray, list]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if len(X_arr) == 0:
            return np.empty((0,), dtype=np.float64)
        return self.model.predict(X_arr)


def create_baseline_model(
    model_type: str,
    task: str = "classification",
    **kwargs: Any,
) -> Any:
    """Factory creating configured baseline model."""
    m_type = model_type.strip().lower()
    t_type = task.strip().lower()

    if t_type == "classification":
        if m_type in ("logistic", "logistic_regression", "lr"):
            return LogisticRegressionBaseline(**kwargs)
        elif m_type in ("lightgbm", "lgbm"):
            return LightGBMClassifierBaseline(**kwargs)
        else:
            raise ValueError(f"Unknown classification model type: {model_type}")
    elif t_type == "regression":
        if m_type in ("lightgbm", "lgbm"):
            return LightGBMRegressorBaseline(**kwargs)
        elif m_type in ("ridge", "ridge_regression"):
            return RidgeRegressionBaseline(**kwargs)
        else:
            raise ValueError(f"Unknown regression model type: {model_type}")
    else:
        raise ValueError(f"Invalid task: {task}. Must be 'classification' or 'regression'.")
