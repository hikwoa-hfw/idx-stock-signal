"""Controlled Feature Ablation Engine for BEI Dual-Mode Stock Signals (Phase 11A).

Evaluates the out-of-sample incremental predictive value of existing feature
families using expanding-window walk-forward validation with a 10-day purge.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score

from python.common.types import classify_price_mode
from python.config.settings import settings
from python.models.baseline import LightGBMClassifierBaseline, LogisticRegressionBaseline
from python.models.metrics import (
    compute_accuracy,
    compute_brier_score,
    compute_expected_calibration_error,
    compute_log_loss,
    compute_roc_auc,
)
from python.models.validation import WalkForwardSplitter

FEATURE_FAMILIES: dict[str, list[str]] = {
    "price_momentum": [
        "return_1d",
        "return_3d",
        "return_5d",
        "return_10d",
        "return_20d",
    ],
    "trend": [
        "ema20",
        "ema50",
        "ema200",
        "close_vs_ema20",
        "close_vs_ema50",
        "ema20_vs_ema50",
        "ema50_vs_ema200",
    ],
    "oscillators": [
        "rsi14",
        "rsi_change_5d",
    ],
    "volatility": [
        "atr14",
        "atr_pct",
        "realized_vol_5d",
        "realized_vol_20d",
        "daily_range_pct",
    ],
    "volume_liquidity": [
        "volume_ratio_5d",
        "volume_ratio_20d",
        "value_ratio_20d",
    ],
    "relative_strength": [
        "rel_strength_ihsg_20d",
        "rel_strength_sector_20d",
    ],
    "market_regime": [
        "ihsg_return_5d",
        "ihsg_return_20d",
        "ihsg_vs_ema20",
        "ihsg_vs_ema50",
        "market_breadth",
        "market_volatility",
    ],
}

ALL_FEATURE_COLUMNS: list[str] = [
    f for family_features in FEATURE_FAMILIES.values() for f in family_features
]

FEATURE_INVENTORY: list[dict[str, Any]] = [
    {
        "name": "return_1d",
        "family": "price_momentum",
        "lookback": "1 bar",
        "formula": "(close[t] - close[t-1]) / close[t-1]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "return_3d",
        "family": "price_momentum",
        "lookback": "3 bars",
        "formula": "(close[t] - close[t-3]) / close[t-3]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "return_5d",
        "family": "price_momentum",
        "lookback": "5 bars",
        "formula": "(close[t] - close[t-5]) / close[t-5]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "return_10d",
        "family": "price_momentum",
        "lookback": "10 bars",
        "formula": "(close[t] - close[t-10]) / close[t-10]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "return_20d",
        "family": "price_momentum",
        "lookback": "20 bars",
        "formula": "(close[t] - close[t-20]) / close[t-20]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "ema20",
        "family": "trend",
        "lookback": "20 bars",
        "formula": "EMA(close, span=20)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "ema50",
        "family": "trend",
        "lookback": "50 bars",
        "formula": "EMA(close, span=50)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "ema200",
        "family": "trend",
        "lookback": "200 bars",
        "formula": "EMA(close, span=200)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "close_vs_ema20",
        "family": "trend",
        "lookback": "20 bars",
        "formula": "(close[t] - ema20[t]) / ema20[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close, ema20",
    },
    {
        "name": "close_vs_ema50",
        "family": "trend",
        "lookback": "50 bars",
        "formula": "(close[t] - ema50[t]) / ema50[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close, ema50",
    },
    {
        "name": "ema20_vs_ema50",
        "family": "trend",
        "lookback": "50 bars",
        "formula": "(ema20[t] - ema50[t]) / ema50[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ema20, ema50",
    },
    {
        "name": "ema50_vs_ema200",
        "family": "trend",
        "lookback": "200 bars",
        "formula": "(ema50[t] - ema200[t]) / ema200[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ema50, ema200",
    },
    {
        "name": "rsi14",
        "family": "oscillators",
        "lookback": "14 bars",
        "formula": "Wilder RSI(14) in [0, 100]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "rsi_change_5d",
        "family": "oscillators",
        "lookback": "19 bars",
        "formula": "rsi14[t] - rsi14[t-5]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "rsi14",
    },
    {
        "name": "atr14",
        "family": "volatility",
        "lookback": "14 bars",
        "formula": "Wilder Average True Range(14)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "high, low, close",
    },
    {
        "name": "atr_pct",
        "family": "volatility",
        "lookback": "14 bars",
        "formula": "atr14[t] / close[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "atr14, close",
    },
    {
        "name": "realized_vol_5d",
        "family": "volatility",
        "lookback": "5 bars",
        "formula": "Sample standard deviation of daily returns over 5 bars",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "realized_vol_20d",
        "family": "volatility",
        "lookback": "20 bars",
        "formula": "Sample standard deviation of daily returns over 20 bars",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close",
    },
    {
        "name": "daily_range_pct",
        "family": "volatility",
        "lookback": "1 bar",
        "formula": "(high[t] - low[t]) / close[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "high, low, close",
    },
    {
        "name": "volume_ratio_5d",
        "family": "volume_liquidity",
        "lookback": "5 bars",
        "formula": "volume[t] / SMA(volume, 5)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "volume",
    },
    {
        "name": "volume_ratio_20d",
        "family": "volume_liquidity",
        "lookback": "20 bars",
        "formula": "volume[t] / SMA(volume, 20)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "volume",
    },
    {
        "name": "value_ratio_20d",
        "family": "volume_liquidity",
        "lookback": "20 bars",
        "formula": "turnover[t] / SMA(turnover, 20)",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "volume, close",
    },
    {
        "name": "rel_strength_ihsg_20d",
        "family": "relative_strength",
        "lookback": "20 bars",
        "formula": "(1 + return_20d[t]) / (1 + ihsg_return_20d[t]) - 1",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close, ihsg_close",
    },
    {
        "name": "rel_strength_sector_20d",
        "family": "relative_strength",
        "lookback": "20 bars",
        "formula": "(1 + return_20d[t]) / (1 + sector_return_20d[t]) - 1",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "close, sector_indices",
    },
    {
        "name": "ihsg_return_5d",
        "family": "market_regime",
        "lookback": "5 bars",
        "formula": "(ihsg_close[t] - ihsg_close[t-5]) / ihsg_close[t-5]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ihsg_close",
    },
    {
        "name": "ihsg_return_20d",
        "family": "market_regime",
        "lookback": "20 bars",
        "formula": "(ihsg_close[t] - ihsg_close[t-20]) / ihsg_close[t-20]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ihsg_close",
    },
    {
        "name": "ihsg_vs_ema20",
        "family": "market_regime",
        "lookback": "20 bars",
        "formula": "(ihsg_close[t] - ihsg_ema20[t]) / ihsg_ema20[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ihsg_close",
    },
    {
        "name": "ihsg_vs_ema50",
        "family": "market_regime",
        "lookback": "50 bars",
        "formula": "(ihsg_close[t] - ihsg_ema50[t]) / ihsg_ema50[t]",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ihsg_close",
    },
    {
        "name": "market_breadth",
        "family": "market_regime",
        "lookback": "20 bars",
        "formula": "Fraction of universe stocks trading above EMA20 on date t",
        "pit_availability": "Computed at Close t across universe, available for Open t+1",
        "dependencies": "universe_closes, universe_ema20",
    },
    {
        "name": "market_volatility",
        "family": "market_regime",
        "lookback": "20 bars",
        "formula": "Sample standard deviation of daily IHSG returns over 20 bars",
        "pit_availability": "Computed at Close t, available for entry at Open t+1",
        "dependencies": "ihsg_close",
    },
]


def compute_pr_auc(y_true: Union[np.ndarray, list], y_prob: Union[np.ndarray, list]) -> float:
    """Area Under the Precision-Recall Curve (Average Precision)."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    if len(np.unique(yt)) < 2:
        return float(np.mean(yt))
    try:
        return float(average_precision_score(yt, yp))
    except Exception:
        return float(np.mean(yt))


def compute_top_k_precision(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    k_pct: float = 0.10,
) -> float:
    """Global/pooled precision within the top k-percent highest predicted probabilities."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    n = len(yt)
    if n == 0:
        return 0.0
    k = max(1, int(round(n * k_pct)))
    # Deterministic stable sort descending
    order = np.argsort(-yp, kind="stable")
    top_indices = order[:k]
    return float(np.mean(yt[top_indices]))


def compute_daily_cross_sectional_top_k_precision(
    df: pd.DataFrame,
    k_pct: float = 0.10,
    min_candidates: int = 10,
    date_col: str = "date",
    ticker_col: str = "ticker",
    target_col: str = "binary_target",
    prob_col: str = "y_prob",
) -> dict[str, Any]:
    """Computes daily cross-sectional Top-K precision with deterministic tie-breaking.

    Rules:
    - Stocks are ranked separately per completed trading decision date.
    - Deterministic tie-handling: probability DESC, then ticker ASC.
    - Select top k_pct: k_d = max(1, int(round(n_candidates * k_pct))).
    - Dates with fewer than min_candidates are excluded from precision aggregation
      and tracked under insufficient_dates.
    """
    if df.empty:
        return {
            "daily_precision_macro": 0.0,
            "daily_precision_std": 0.0,
            "daily_precision_micro": 0.0,
            "total_dates": 0,
            "evaluated_dates": 0,
            "insufficient_dates": 0,
            "candidates_per_date_min": 0,
            "candidates_per_date_max": 0,
            "candidates_per_date_mean": 0.0,
            "candidates_per_date_median": 0.0,
            "min_candidates_threshold": min_candidates,
            "k_pct": k_pct,
            "selection_rule": (
                f"Top {int(round(k_pct * 100))}% of candidates per date "
                f"(min {min_candidates} required)"
            ),
            "tie_breaker_rule": "Deterministic stable sort: -prob descending, ticker ascending",
            "selection_mask": np.zeros(0, dtype=np.int64),
        }

    counts = df.groupby(date_col).size()
    total_dates = int(len(counts))
    valid_dates = set(counts[counts >= min_candidates].index)
    insufficient_dates = int(total_dates - len(valid_dates))

    c_min = int(counts.min()) if not counts.empty else 0
    c_max = int(counts.max()) if not counts.empty else 0
    c_mean = round(float(counts.mean()), 2) if not counts.empty else 0.0
    c_median = round(float(counts.median()), 2) if not counts.empty else 0.0

    if not valid_dates:
        return {
            "daily_precision_macro": 0.0,
            "daily_precision_std": 0.0,
            "daily_precision_micro": 0.0,
            "total_dates": total_dates,
            "evaluated_dates": 0,
            "insufficient_dates": insufficient_dates,
            "candidates_per_date_min": c_min,
            "candidates_per_date_max": c_max,
            "candidates_per_date_mean": c_mean,
            "candidates_per_date_median": c_median,
            "min_candidates_threshold": min_candidates,
            "k_pct": k_pct,
            "selection_rule": (
                f"Top {int(round(k_pct * 100))}% of candidates per date "
                f"(min {min_candidates} required)"
            ),
            "tie_breaker_rule": "Deterministic stable sort: -prob descending, ticker ascending",
            "selection_mask": np.zeros(len(df), dtype=np.int64),
        }

    valid_df = df[df[date_col].isin(valid_dates)]
    sorted_df = valid_df.sort_values(
        by=[date_col, prob_col, ticker_col],
        ascending=[True, False, True],
        kind="stable",
    )

    daily_precisions: list[float] = []
    total_picks = 0
    total_positives = 0
    selection_mask = np.zeros(len(df), dtype=np.int64)

    for _, group in sorted_df.groupby(date_col, sort=False):
        n_d = len(group)
        k_d = min(n_d, max(1, int(round(n_d * k_pct))))
        top_group = group.iloc[:k_d]
        selection_mask[top_group.index] = 1
        pos = int(top_group[target_col].sum())
        prec = float(pos / k_d) if k_d > 0 else 0.0
        daily_precisions.append(prec)
        total_picks += k_d
        total_positives += pos

    macro_mean = float(np.mean(daily_precisions)) if daily_precisions else 0.0
    macro_std = float(np.std(daily_precisions, ddof=1)) if len(daily_precisions) > 1 else 0.0
    micro_mean = float(total_positives / total_picks) if total_picks > 0 else 0.0

    return {
        "daily_precision_macro": round(macro_mean, 4),
        "daily_precision_std": round(macro_std, 4),
        "daily_precision_micro": round(micro_mean, 4),
        "total_dates": total_dates,
        "evaluated_dates": len(daily_precisions),
        "insufficient_dates": insufficient_dates,
        "candidates_per_date_min": c_min,
        "candidates_per_date_max": c_max,
        "candidates_per_date_mean": c_mean,
        "candidates_per_date_median": c_median,
        "min_candidates_threshold": min_candidates,
        "k_pct": k_pct,
        "selection_rule": (
            f"Top {int(round(k_pct * 100))}% of candidates per date (min {min_candidates} required)"
        ),
        "tie_breaker_rule": "Deterministic stable sort: -prob descending, ticker ascending",
        "selection_mask": selection_mask,
    }


def compute_daily_top_n_precision(
    df: pd.DataFrame,
    top_n: int = 5,
    min_candidates: int = 5,
    date_col: str = "date",
    ticker_col: str = "ticker",
    target_col: str = "binary_target",
    prob_col: str = "y_prob",
) -> dict[str, Any]:
    """Computes daily Top-N fixed-count precision matching production signal engine policy.

    Ranks candidates by probability DESC, ticker ASC, selecting top_n candidates per date.
    Dates with fewer than min_candidates are excluded.
    """
    if df.empty or top_n <= 0:
        return {
            "daily_precision_macro": 0.0,
            "daily_precision_std": 0.0,
            "daily_precision_micro": 0.0,
            "evaluated_dates": 0,
            "insufficient_dates": 0,
            "top_n": top_n,
        }

    counts = df.groupby(date_col).size()
    valid_dates = set(counts[counts >= min_candidates].index)
    insufficient_dates = int(len(counts) - len(valid_dates))

    if not valid_dates:
        return {
            "daily_precision_macro": 0.0,
            "daily_precision_std": 0.0,
            "daily_precision_micro": 0.0,
            "evaluated_dates": 0,
            "insufficient_dates": insufficient_dates,
            "top_n": top_n,
        }

    valid_df = df[df[date_col].isin(valid_dates)]
    sorted_df = valid_df.sort_values(
        by=[date_col, prob_col, ticker_col],
        ascending=[True, False, True],
        kind="stable",
    )

    daily_precisions: list[float] = []
    total_picks = 0
    total_positives = 0

    for _, group in sorted_df.groupby(date_col, sort=False):
        n_d = len(group)
        k_d = min(top_n, n_d)
        top_group = group.iloc[:k_d]
        pos = int(top_group[target_col].sum())
        prec = float(pos / k_d) if k_d > 0 else 0.0
        daily_precisions.append(prec)
        total_picks += k_d
        total_positives += pos

    macro_mean = float(np.mean(daily_precisions)) if daily_precisions else 0.0
    macro_std = float(np.std(daily_precisions, ddof=1)) if len(daily_precisions) > 1 else 0.0
    micro_mean = float(total_positives / total_picks) if total_picks > 0 else 0.0

    return {
        "daily_precision_macro": round(macro_mean, 4),
        "daily_precision_std": round(macro_std, 4),
        "daily_precision_micro": round(micro_mean, 4),
        "evaluated_dates": len(daily_precisions),
        "insufficient_dates": insufficient_dates,
        "top_n": top_n,
    }


def evaluate_predictions(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute primary probabilistic metrics and secondary ranking diagnostics."""
    n_samples = len(y_true)
    pos_count = int(np.sum(y_true == 1))
    prevalence = float(pos_count / n_samples) if n_samples > 0 else 0.0

    return {
        "sample_size": n_samples,
        "positive_count": pos_count,
        "prevalence": round(prevalence, 4),
        "roc_auc": round(compute_roc_auc(y_true, y_prob), 4),
        "pr_auc": round(compute_pr_auc(y_true, y_prob), 4),
        "log_loss": round(compute_log_loss(y_true, y_prob), 4),
        "brier_score": round(compute_brier_score(y_true, y_prob), 4),
        "ece": round(compute_expected_calibration_error(y_true, y_prob, n_bins=n_bins), 4),
        "accuracy": round(compute_accuracy(y_true, y_prob, threshold=threshold), 4),
        "top_10pct_precision": round(compute_top_k_precision(y_true, y_prob, k_pct=0.10), 4),
    }


@dataclass
class FoldEvaluation:
    fold: int
    train_start: str
    train_end: str
    train_samples: int
    train_pos_rate: float
    test_start: str
    test_end: str
    test_samples: int
    test_pos_rate: float
    model_name: str
    feature_group_excluded: Optional[str]
    features_used: int
    metrics: dict[str, Any]


class FeatureAblationRunner:
    """Coordinates walk-forward feature ablation experiments across price regimes."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        n_splits: int = 3,
        purge_days: int = 10,
        random_state: int = 42,
    ) -> None:
        self.db_path = db_path or self._resolve_db_path()
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.random_state = random_state

    def _resolve_db_path(self) -> str:
        url = settings.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        if url.startswith("sqlite://"):
            return url[len("sqlite://") :]
        return "datasets/stock_signals.db"

    def load_clean_data(self, mode: str) -> pd.DataFrame:
        """Loads features and labels joined on ticker/date, filtered to target price mode."""
        conn = sqlite3.connect(self.db_path)
        try:
            cols_sql = ", ".join([f"f.{col}" for col in ALL_FEATURE_COLUMNS])
            query = f"""
                SELECT f.ticker, f.date, l.binary_target, l.entry_price, {cols_sql}
                FROM features_daily f
                JOIN labels_daily l ON f.ticker = l.ticker AND f.date = l.date
                WHERE l.outcome != 'AMBIGUOUS' AND l.binary_target IS NOT NULL
            """
            df = pd.read_sql_query(query, conn)
        finally:
            conn.close()

        if df.empty:
            return df

        df["mode"] = df["entry_price"].apply(classify_price_mode)
        target_mode = mode.strip().upper()
        df = df[df["mode"] == target_mode].reset_index(drop=True)

        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values(by=["date", "ticker"]).reset_index(drop=True)
        return df

    def run_experiment(
        self,
        mode: str,
        include_group_only: bool = True,
    ) -> dict[str, Any]:
        """Executes reference model, 7 leave-one-group-out ablations, and baselines."""
        df = self.load_clean_data(mode)
        if df.empty:
            raise ValueError(f"No valid data found for mode: {mode}")

        dates = df["date"].to_numpy()
        y_all = df["binary_target"].to_numpy(dtype=np.int64)

        splitter = WalkForwardSplitter(
            n_splits=self.n_splits,
            purge_days=self.purge_days,
            expanding=True,
        )

        model_specs: list[dict[str, Any]] = [
            {
                "name": "reference",
                "type": "lightgbm",
                "excluded_group": None,
                "included_group": None,
                "features": list(ALL_FEATURE_COLUMNS),
            }
        ]

        # 7 Leave-one-group-out ablations
        for family, features in FEATURE_FAMILIES.items():
            remaining = [f for f in ALL_FEATURE_COLUMNS if f not in features]
            model_specs.append(
                {
                    "name": f"ablation_minus_{family}",
                    "type": "lightgbm",
                    "excluded_group": family,
                    "included_group": None,
                    "features": remaining,
                }
            )

        # Baseline: Prevalence
        model_specs.append(
            {
                "name": "prevalence_baseline",
                "type": "prevalence",
                "excluded_group": None,
                "included_group": None,
                "features": [],
            }
        )

        # Baseline: Logistic Regression
        model_specs.append(
            {
                "name": "logistic_baseline",
                "type": "logistic",
                "excluded_group": None,
                "included_group": None,
                "features": list(ALL_FEATURE_COLUMNS),
            }
        )

        # Optional: 7 Group-only models as secondary diagnostics
        if include_group_only:
            for family, features in FEATURE_FAMILIES.items():
                model_specs.append(
                    {
                        "name": f"group_only_{family}",
                        "type": "lightgbm",
                        "excluded_group": None,
                        "included_group": family,
                        "features": list(features),
                    }
                )

        fold_evaluations: list[FoldEvaluation] = []
        # Store pooled out-of-sample predictions across folds for aggregate metrics
        pooled_predictions: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {
            spec["name"]: [] for spec in model_specs
        }

        fold_metadata: list[dict[str, Any]] = []
        all_oos_dfs: list[pd.DataFrame] = []

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(dates), start=1):
            d_tr_min, d_tr_max = str(dates[train_idx].min()), str(dates[train_idx].max())
            d_te_min, d_te_max = str(dates[test_idx].min()), str(dates[test_idx].max())

            y_tr = y_all[train_idx]
            y_te = y_all[test_idx]

            fold_info = {
                "fold": fold_idx,
                "train_dates": f"{d_tr_min} -> {d_tr_max}",
                "train_days": len(np.unique(dates[train_idx])),
                "train_samples": len(train_idx),
                "train_pos_rate": round(float(y_tr.mean()), 4),
                "purge_days": self.purge_days,
                "test_dates": f"{d_te_min} -> {d_te_max}",
                "test_days": len(np.unique(dates[test_idx])),
                "test_samples": len(test_idx),
                "test_pos_rate": round(float(y_te.mean()), 4),
            }
            fold_metadata.append(fold_info)

            # Fit strictly causal median imputer on training fold
            X_all_train = df.iloc[train_idx][ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)
            X_all_test = df.iloc[test_idx][ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)

            imputer = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
            X_all_train_imp = imputer.fit_transform(X_all_train)
            X_all_test_imp = imputer.transform(X_all_test)

            test_tickers = df.iloc[test_idx]["ticker"].to_numpy()
            test_dates = df.iloc[test_idx]["date"].to_numpy()

            fold_preds_dict: dict[str, Any] = {
                "fold": [fold_idx] * len(test_idx),
                "date": [str(d) for d in test_dates],
                "ticker": list(test_tickers),
                "mode": [mode] * len(test_idx),
                "binary_target": list(y_te),
            }

            col_index_map = {col: i for i, col in enumerate(ALL_FEATURE_COLUMNS)}

            for spec in model_specs:
                m_name = spec["name"]
                m_type = spec["type"]
                feat_cols = spec["features"]

                if m_type == "prevalence":
                    # Constant positive-class prevalence prediction within fold
                    prev_val = float(y_tr.mean())
                    y_prob = np.full(len(test_idx), prev_val, dtype=np.float64)
                elif m_type == "logistic":
                    indices = [col_index_map[c] for c in feat_cols]
                    X_tr_sub = X_all_train_imp[:, indices]
                    X_te_sub = X_all_test_imp[:, indices]
                    clf = LogisticRegressionBaseline(
                        C=1.0,
                        max_iter=1000,
                        random_state=self.random_state,
                        calibrated=False,
                    )
                    clf.fit(X_tr_sub, y_tr, feature_names=feat_cols)
                    y_prob = clf.predict_probability(X_te_sub)
                else:  # lightgbm
                    indices = [col_index_map[c] for c in feat_cols]
                    X_tr_sub = X_all_train_imp[:, indices]
                    X_te_sub = X_all_test_imp[:, indices]
                    clf = LightGBMClassifierBaseline(
                        n_estimators=100,
                        learning_rate=0.05,
                        max_depth=5,
                        num_leaves=31,
                        min_child_samples=20,
                        random_state=self.random_state,
                        calibrated=False,
                    )
                    clf.fit(X_tr_sub, y_tr, feature_names=feat_cols)
                    y_prob = clf.predict_probability(X_te_sub)

                metrics = evaluate_predictions(y_te, y_prob)

                # Compute fold-level daily cross-sectional ranking metrics
                fold_df = pd.DataFrame(
                    {
                        "ticker": test_tickers,
                        "date": test_dates,
                        "binary_target": y_te,
                        "y_prob": y_prob,
                    }
                )
                daily_top10 = compute_daily_cross_sectional_top_k_precision(
                    fold_df, k_pct=0.10, min_candidates=10
                )
                daily_top5 = compute_daily_top_n_precision(fold_df, top_n=5, min_candidates=5)

                metrics["daily_top_10pct_precision"] = daily_top10["daily_precision_macro"]
                metrics["daily_top_10pct_precision_std"] = daily_top10["daily_precision_std"]
                metrics["daily_top_10pct_micro_precision"] = daily_top10["daily_precision_micro"]
                metrics["daily_top_5_precision"] = daily_top5["daily_precision_macro"]
                metrics["daily_evaluated_dates"] = daily_top10["evaluated_dates"]
                metrics["daily_insufficient_dates"] = daily_top10["insufficient_dates"]
                metrics["candidates_per_date_median"] = daily_top10["candidates_per_date_median"]
                metrics["candidates_per_date_mean"] = daily_top10["candidates_per_date_mean"]
                metrics["candidates_per_date_min"] = daily_top10["candidates_per_date_min"]
                metrics["candidates_per_date_max"] = daily_top10["candidates_per_date_max"]
                metrics["global_top_10pct_precision"] = metrics["top_10pct_precision"]

                fold_eval = FoldEvaluation(
                    fold=fold_idx,
                    train_start=d_tr_min,
                    train_end=d_tr_max,
                    train_samples=len(train_idx),
                    train_pos_rate=round(float(y_tr.mean()), 4),
                    test_start=d_te_min,
                    test_end=d_te_max,
                    test_samples=len(test_idx),
                    test_pos_rate=round(float(y_te.mean()), 4),
                    model_name=m_name,
                    feature_group_excluded=spec["excluded_group"],
                    features_used=len(feat_cols),
                    metrics=metrics,
                )
                fold_evaluations.append(fold_eval)
                pooled_predictions[m_name].append((y_te, y_prob))

                # Store predictions and daily top 10% flag in out-of-sample prediction table
                fold_preds_dict[f"prob_{m_name}"] = [round(float(p), 6) for p in y_prob]
                fold_preds_dict[f"is_top10_{m_name}"] = list(daily_top10["selection_mask"])

            oos_fold_df = pd.DataFrame(fold_preds_dict)
            all_oos_dfs.append(oos_fold_df)

        # Macro fold aggregation (Mean, Std, Min, Max across folds)
        macro_aggregate_results: list[dict[str, Any]] = []
        metrics_to_aggregate = [
            "roc_auc",
            "pr_auc",
            "daily_top_10pct_precision",
            "daily_top_5_precision",
            "brier_score",
            "log_loss",
            "ece",
            "accuracy",
            "global_top_10pct_precision",
        ]

        for spec in model_specs:
            m_name = spec["name"]
            fe_list = [fe for fe in fold_evaluations if fe.model_name == m_name]

            macro_stats: dict[str, dict[str, float]] = {}
            for met in metrics_to_aggregate:
                vals = [fe.metrics[met] for fe in fe_list]
                macro_stats[met] = {
                    "mean": round(float(np.mean(vals)), 4),
                    "std": round(float(np.std(vals, ddof=1)), 4) if len(vals) > 1 else 0.0,
                    "min": round(float(np.min(vals)), 4),
                    "max": round(float(np.max(vals)), 4),
                }

            # Pooled diagnostics across concatenated out-of-sample predictions
            y_te_all = np.concatenate([p[0] for p in pooled_predictions[m_name]])
            y_prob_all = np.concatenate([p[1] for p in pooled_predictions[m_name]])
            pooled_eval = evaluate_predictions(y_te_all, y_prob_all)

            pooled_diagnostics = {
                "pooled_roc_auc": pooled_eval["roc_auc"],
                "pooled_pr_auc": pooled_eval["pr_auc"],
                "pooled_brier_score": pooled_eval["brier_score"],
                "pooled_log_loss": pooled_eval["log_loss"],
                "pooled_ece": pooled_eval["ece"],
                "pooled_top_10pct_precision": pooled_eval["top_10pct_precision"],
                "disclaimer": (
                    "Pooled ranking metrics concatenate out-of-sample predictions across "
                    "folds with shifting prevalence and different calibration baselines. "
                    "They are secondary diagnostics and must NOT be used as the sole criteria "
                    "for model/feature selection."
                ),
            }

            agg_entry = {
                "model_name": m_name,
                "model_type": spec["type"],
                "excluded_group": spec["excluded_group"],
                "included_group": spec["included_group"],
                "features_used": len(spec["features"]),
                "macro_metrics": macro_stats,
                "pooled_diagnostics": pooled_diagnostics,
                "roc_auc_mean": macro_stats["roc_auc"]["mean"],
                "roc_auc_std": macro_stats["roc_auc"]["std"],
                "roc_auc_min": macro_stats["roc_auc"]["min"],
                "roc_auc_max": macro_stats["roc_auc"]["max"],
                "pr_auc_mean": macro_stats["pr_auc"]["mean"],
                "pr_auc_std": macro_stats["pr_auc"]["std"],
                "pr_auc_min": macro_stats["pr_auc"]["min"],
                "pr_auc_max": macro_stats["pr_auc"]["max"],
                "daily_top_10pct_precision_mean": macro_stats["daily_top_10pct_precision"]["mean"],
                "daily_top_10pct_precision_std": macro_stats["daily_top_10pct_precision"]["std"],
                "daily_top_10pct_precision_min": macro_stats["daily_top_10pct_precision"]["min"],
                "daily_top_10pct_precision_max": macro_stats["daily_top_10pct_precision"]["max"],
                "daily_top_5_precision_mean": macro_stats["daily_top_5_precision"]["mean"],
                "brier_score_mean": macro_stats["brier_score"]["mean"],
                "log_loss_mean": macro_stats["log_loss"]["mean"],
                "ece_mean": macro_stats["ece"]["mean"],
                "metrics": {
                    "roc_auc": macro_stats["roc_auc"]["mean"],
                    "pr_auc": macro_stats["pr_auc"]["mean"],
                    "daily_top_10pct_precision": macro_stats["daily_top_10pct_precision"]["mean"],
                    "daily_top_5_precision": macro_stats["daily_top_5_precision"]["mean"],
                    "brier_score": macro_stats["brier_score"]["mean"],
                    "log_loss": macro_stats["log_loss"]["mean"],
                    "ece": macro_stats["ece"]["mean"],
                    "accuracy": macro_stats["accuracy"]["mean"],
                    "sample_size": sum(fe.test_samples for fe in fe_list),
                    "positive_count": sum(fe.metrics["positive_count"] for fe in fe_list),
                    "prevalence": round(
                        float(sum(fe.metrics["positive_count"] for fe in fe_list))
                        / sum(fe.test_samples for fe in fe_list),
                        4,
                    ),
                    "pooled_roc_auc": pooled_eval["roc_auc"],
                    "pooled_pr_auc": pooled_eval["pr_auc"],
                    "top_10pct_precision": macro_stats["daily_top_10pct_precision"]["mean"],
                },
            }
            macro_aggregate_results.append(agg_entry)

        # Compute deltas relative to reference model on macro means
        ref_entry = next(e for e in macro_aggregate_results if e["model_name"] == "reference")
        ref_m = ref_entry["macro_metrics"]

        for entry in macro_aggregate_results:
            m = entry["macro_metrics"]
            entry["deltas_vs_reference"] = {
                "delta_macro_roc_auc": round(m["roc_auc"]["mean"] - ref_m["roc_auc"]["mean"], 4),
                "delta_macro_pr_auc": round(m["pr_auc"]["mean"] - ref_m["pr_auc"]["mean"], 4),
                "delta_macro_daily_top_10pct_precision": round(
                    m["daily_top_10pct_precision"]["mean"]
                    - ref_m["daily_top_10pct_precision"]["mean"],
                    4,
                ),
                "delta_macro_daily_top_5_precision": round(
                    m["daily_top_5_precision"]["mean"] - ref_m["daily_top_5_precision"]["mean"], 4
                ),
                "delta_macro_brier_score": round(
                    m["brier_score"]["mean"] - ref_m["brier_score"]["mean"], 4
                ),
                "delta_macro_log_loss": round(m["log_loss"]["mean"] - ref_m["log_loss"]["mean"], 4),
                "delta_roc_auc": round(m["roc_auc"]["mean"] - ref_m["roc_auc"]["mean"], 4),
                "delta_pr_auc": round(m["pr_auc"]["mean"] - ref_m["pr_auc"]["mean"], 4),
                "delta_log_loss": round(m["log_loss"]["mean"] - ref_m["log_loss"]["mean"], 4),
                "delta_brier_score": round(
                    m["brier_score"]["mean"] - ref_m["brier_score"]["mean"], 4
                ),
                "delta_ece": round(m["ece"]["mean"] - ref_m["ece"]["mean"], 4),
                "delta_top_10pct_precision": round(
                    m["daily_top_10pct_precision"]["mean"]
                    - ref_m["daily_top_10pct_precision"]["mean"],
                    4,
                ),
            }

        oos_predictions_df = (
            pd.concat(all_oos_dfs, ignore_index=True) if all_oos_dfs else pd.DataFrame()
        )

        return {
            "mode": mode,
            "sample_count": len(df),
            "date_range": f"{dates.min()} -> {dates.max()}",
            "n_splits": self.n_splits,
            "purge_days": self.purge_days,
            "random_state": self.random_state,
            "fold_metadata": fold_metadata,
            "aggregate_results": macro_aggregate_results,
            "macro_aggregate_results": macro_aggregate_results,
            "fold_evaluations": [asdict(fe) for fe in fold_evaluations],
            "oos_predictions_df": oos_predictions_df,
        }

    def export_artifacts(
        self,
        results: dict[str, Any],
        output_dir: Union[str, Path] = "artifacts/ablation",
    ) -> tuple[Path, Path]:
        """Saves machine-readable JSON and CSV summaries outside the model registry."""
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        mode = results["mode"]
        json_path = out_p / f"ablation_results_{mode}.json"
        csv_path = out_p / f"ablation_results_{mode}.csv"
        fold_details_csv = out_p / f"ablation_fold_details_{mode}.csv"
        oos_preds_csv = out_p / f"oos_predictions_{mode}.csv"

        # Extract oos_predictions DataFrame without mutating results dict
        oos_df = results.get("oos_predictions_df", None)
        json_results = {k: v for k, v in results.items() if k != "oos_predictions_df"}

        # Export full JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2)

        # Flatten macro aggregate results into CSV
        rows = []
        for res in results["macro_aggregate_results"]:
            row = {
                "mode": mode,
                "model_name": res["model_name"],
                "model_type": res["model_type"],
                "excluded_group": res["excluded_group"] or "NONE",
                "features_used": res["features_used"],
                "sample_size": res["metrics"]["sample_size"],
                "positive_count": res["metrics"]["positive_count"],
                "prevalence": res["metrics"]["prevalence"],
                "roc_auc_mean": res["roc_auc_mean"],
                "roc_auc_std": res["roc_auc_std"],
                "roc_auc_min": res["roc_auc_min"],
                "roc_auc_max": res["roc_auc_max"],
                "pr_auc_mean": res["pr_auc_mean"],
                "pr_auc_std": res["pr_auc_std"],
                "pr_auc_min": res["pr_auc_min"],
                "pr_auc_max": res["pr_auc_max"],
                "daily_top_10pct_prec_mean": res["daily_top_10pct_precision_mean"],
                "daily_top_10pct_prec_std": res["daily_top_10pct_precision_std"],
                "daily_top_10pct_prec_min": res["daily_top_10pct_precision_min"],
                "daily_top_10pct_prec_max": res["daily_top_10pct_precision_max"],
                "daily_top_5_prec_mean": res["daily_top_5_precision_mean"],
                "brier_score_mean": res["brier_score_mean"],
                "log_loss_mean": res["log_loss_mean"],
                "ece_mean": res["ece_mean"],
                "delta_macro_roc_auc": res["deltas_vs_reference"]["delta_macro_roc_auc"],
                "delta_macro_pr_auc": res["deltas_vs_reference"]["delta_macro_pr_auc"],
                "delta_macro_daily_top_10pct_prec": res["deltas_vs_reference"][
                    "delta_macro_daily_top_10pct_precision"
                ],
                "delta_macro_daily_top_5_prec": res["deltas_vs_reference"][
                    "delta_macro_daily_top_5_precision"
                ],
                "delta_macro_brier_score": res["deltas_vs_reference"]["delta_macro_brier_score"],
                "delta_macro_log_loss": res["deltas_vs_reference"]["delta_macro_log_loss"],
                "pooled_roc_auc": res["pooled_diagnostics"]["pooled_roc_auc"],
                "pooled_pr_auc": res["pooled_diagnostics"]["pooled_pr_auc"],
                "pooled_brier_score": res["pooled_diagnostics"]["pooled_brier_score"],
                "pooled_log_loss": res["pooled_diagnostics"]["pooled_log_loss"],
                "pooled_top_10pct_precision": res["pooled_diagnostics"][
                    "pooled_top_10pct_precision"
                ],
            }
            rows.append(row)

        pd.DataFrame(rows).to_csv(csv_path, index=False)

        # Export fold details CSV
        fold_rows = []
        for fe in results["fold_evaluations"]:
            m = fe["metrics"]
            f_row = {
                "mode": mode,
                "fold": fe["fold"],
                "model_name": fe["model_name"],
                "feature_group_excluded": fe["feature_group_excluded"] or "NONE",
                "features_used": fe["features_used"],
                "train_samples": fe["train_samples"],
                "train_pos_rate": fe["train_pos_rate"],
                "test_samples": fe["test_samples"],
                "test_pos_rate": fe["test_pos_rate"],
                "roc_auc": m["roc_auc"],
                "pr_auc": m["pr_auc"],
                "daily_top_10pct_precision": m.get("daily_top_10pct_precision", 0.0),
                "daily_top_10pct_precision_std": m.get("daily_top_10pct_precision_std", 0.0),
                "daily_top_10pct_micro_precision": m.get("daily_top_10pct_micro_precision", 0.0),
                "daily_top_5_precision": m.get("daily_top_5_precision", 0.0),
                "daily_evaluated_dates": m.get("daily_evaluated_dates", 0),
                "daily_insufficient_dates": m.get("daily_insufficient_dates", 0),
                "candidates_per_date_median": m.get("candidates_per_date_median", 0.0),
                "candidates_per_date_mean": m.get("candidates_per_date_mean", 0.0),
                "candidates_per_date_min": m.get("candidates_per_date_min", 0),
                "candidates_per_date_max": m.get("candidates_per_date_max", 0),
                "brier_score": m["brier_score"],
                "log_loss": m["log_loss"],
                "ece": m["ece"],
                "accuracy": m["accuracy"],
                "global_top_10pct_precision": m.get("global_top_10pct_precision", 0.0),
            }
            fold_rows.append(f_row)

        pd.DataFrame(fold_rows).to_csv(fold_details_csv, index=False)

        # Export out-of-sample predictions if present
        if oos_df is not None and not oos_df.empty:
            oos_df.to_csv(oos_preds_csv, index=False)

        # Also write feature inventory JSON
        inv_path = out_p / "feature_inventory.json"
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(FEATURE_INVENTORY, f, indent=2)

        return json_path, csv_path
