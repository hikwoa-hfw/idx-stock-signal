import math
from datetime import date
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from python.common.types import (
    CalibrationBin,
    EvaluationReport,
    PredictionMetrics,
    SignalOutcomeRecord,
    TradingMetrics,
)
from python.models.metrics import (
    compute_accuracy,
    compute_brier_score,
    compute_log_loss,
    compute_roc_auc,
)


def compute_calibration_bins(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    n_bins: int = 10,
) -> tuple[float, list[CalibrationBin]]:
    """Calculates ECE and returns uniform reliability bin details."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)
    if len(yt) != len(yp):
        raise ValueError(f"y_true ({len(yt)}) and y_prob ({len(yp)}) must have identical lengths")
    if len(yt) == 0:
        return 0.0, []

    valid = np.isfinite(yt) & np.isfinite(yp)
    yt = yt[valid]
    yp = yp[valid]
    if len(yt) == 0:
        return 0.0, []

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(yt)
    bins_list: list[CalibrationBin] = []

    for i in range(n_bins):
        low, high = float(bin_edges[i]), float(bin_edges[i + 1])
        if i == n_bins - 1:
            in_bin = (yp >= low) & (yp <= high)
        else:
            in_bin = (yp >= low) & (yp < high)

        count = int(np.sum(in_bin))
        if count > 0:
            bin_acc = float(np.mean(yt[in_bin]))
            bin_conf = float(np.mean(yp[in_bin]))
            gap = float(abs(bin_acc - bin_conf))
            ece += (count / n) * gap
        else:
            bin_acc = 0.0
            bin_conf = float((low + high) / 2.0)
            gap = 0.0

        bins_list.append(
            CalibrationBin(
                bin_index=i + 1,
                lower_bound=round(low, 4),
                upper_bound=round(high, 4),
                sample_count=count,
                mean_predicted=round(bin_conf, 4),
                observed_frequency=round(bin_acc, 4),
                gap=round(gap, 4),
            )
        )

    return float(ece), bins_list


def compute_trading_metrics(
    returns: Union[np.ndarray, list[float]],
    outcome_statuses: Optional[list[str]] = None,
) -> TradingMetrics:
    """Computes trading performance metrics from out-of-sample trade returns."""
    clean_statuses: Optional[list[str]] = None
    if outcome_statuses is not None:
        raw_ret_list = list(returns)
        if len(raw_ret_list) == len(outcome_statuses):
            pairs = [
                (r, str(s).strip().upper())
                for r, s in zip(raw_ret_list, outcome_statuses, strict=False)
                if (
                    s is not None
                    and str(s).strip().upper()
                    not in ("OPEN", "UNFILLED_EXPIRED", "INVALIDATED_GAP")
                )
            ]
            raw_list = [r if r is not None and math.isfinite(r) else 0.0 for r, _ in pairs]
            clean_statuses = [s for _, s in pairs]
        else:
            raw_list = [r if r is not None and math.isfinite(r) else 0.0 for r in raw_ret_list]
    else:
        raw_list = [r if r is not None and math.isfinite(r) else 0.0 for r in returns]

    r_arr = np.asarray(raw_list, dtype=np.float64)
    n = len(r_arr)
    if n == 0:
        return TradingMetrics()

    wins = r_arr[r_arr > 0]
    losses = r_arr[r_arr < 0]

    win_rate = float(len(wins) / n)
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0

    gross_gain = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(np.sum(np.abs(losses))) if len(losses) > 0 else 0.0

    if gross_loss == 0.0:
        profit_factor = float("inf") if gross_gain > 0 else 0.0
    else:
        profit_factor = float(gross_gain / gross_loss)

    expectancy = float(np.mean(r_arr))

    # Compounded equity path starting at 1.0 capital for accurate max drawdown
    clipped_returns = np.maximum(r_arr, -0.9999)
    equity_curve = np.insert(np.cumprod(1.0 + clipped_returns), 0, 1.0)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = (peak - equity_curve) / peak
    max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Sharpe ratio (annualized, assuming ~252 trade frequency base)
    if n >= 2:
        r_std = float(np.std(r_arr, ddof=1))
        sharpe = (
            float((np.mean(r_arr) / r_std) * math.sqrt(252))
            if r_std > 0 and math.isfinite(r_std)
            else 0.0
        )
    else:
        sharpe = 0.0

    tp_rate = 0.0
    sl_rate = 0.0
    expiry_rate = 0.0
    if clean_statuses and len(clean_statuses) == n:
        tp_rate = float(sum(1 for s in clean_statuses if s == "TP") / n)
        sl_rate = float(sum(1 for s in clean_statuses if s == "SL") / n)
        expiry_rate = float(sum(1 for s in clean_statuses if s == "EXPIRY") / n)

    return TradingMetrics(
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4) if math.isfinite(profit_factor) else float("inf"),
        expectancy=round(expectancy, 4),
        max_drawdown=round(max_drawdown, 4),
        sharpe=round(sharpe, 4),
        avg_win=round(avg_win, 4),
        avg_loss=round(avg_loss, 4),
        total_trades=n,
        tp_rate=round(tp_rate, 4),
        sl_rate=round(sl_rate, 4),
        expiry_rate=round(expiry_rate, 4),
    )


class EvaluationEngine:
    """Computes probabilistic and trading metrics on out-of-sample models and datasets."""

    def __init__(self, n_calibration_bins: int = 10, decision_threshold: float = 0.5) -> None:
        self.n_bins = n_calibration_bins
        self.threshold = decision_threshold

    def evaluate_predictions(
        self,
        y_true: Union[np.ndarray, list],
        y_prob: Union[np.ndarray, list],
    ) -> tuple[PredictionMetrics, list[CalibrationBin]]:
        """Calculates prediction classification and calibration metrics."""
        yt = np.asarray(y_true, dtype=np.float64)
        yp = np.asarray(y_prob, dtype=np.float64)

        if len(yt) != len(yp):
            raise ValueError(
                f"y_true ({len(yt)}) and y_prob ({len(yp)}) must have identical lengths"
            )

        if len(yt) == 0:
            return PredictionMetrics(), []

        brier = compute_brier_score(yt, yp)
        log_loss = compute_log_loss(yt, yp)
        roc_auc = compute_roc_auc(yt, yp)
        acc = compute_accuracy(yt, yp, threshold=self.threshold)
        ece, bins = compute_calibration_bins(yt, yp, n_bins=self.n_bins)

        metrics = PredictionMetrics(
            brier_score=round(brier, 4),
            log_loss=round(log_loss, 4),
            roc_auc=round(roc_auc, 4),
            ece=round(ece, 4),
            accuracy=round(acc, 4),
        )
        return metrics, bins

    def evaluate_dataset(
        self,
        df: pd.DataFrame,
        model_version: str = "unknown",
        dataset_version: str = "v1.0.0",
        prob_col: str = "predicted_probability",
        return_col: str = "realized_return",
        target_col: str = "binary_target",
        status_col: str = "outcome_status",
        evaluation_date: Optional[date] = None,
        filter_model_version: bool = True,
    ) -> EvaluationReport:
        """Evaluates an outcome or validation DataFrame."""
        if df.empty:
            return EvaluationReport(
                model_version=model_version,
                evaluation_date=evaluation_date or date.today(),
                dataset_version=dataset_version,
                sample_size=0,
            )

        data = df
        if filter_model_version and "model_version" in df.columns:
            matched = df[df["model_version"] == model_version]
            if not matched.empty:
                data = matched

        y_true = (
            data[target_col].to_numpy(dtype=np.float64)
            if target_col in data.columns
            else np.array([])
        )
        y_prob = (
            data[prob_col].to_numpy(dtype=np.float64) if prob_col in data.columns else np.array([])
        )
        returns = (
            data[return_col].to_numpy(dtype=np.float64)
            if return_col in data.columns
            else np.array([])
        )
        statuses = data[status_col].tolist() if status_col in data.columns else None

        pred_metrics, cal_bins = (
            self.evaluate_predictions(y_true, y_prob)
            if len(y_true) > 0 and len(y_prob) > 0
            else (PredictionMetrics(), [])
        )
        trade_metrics = compute_trading_metrics(returns, outcome_statuses=statuses)

        return EvaluationReport(
            model_version=model_version,
            evaluation_date=evaluation_date or date.today(),
            dataset_version=dataset_version,
            sample_size=len(data),
            trading_metrics=trade_metrics,
            prediction_metrics=pred_metrics,
            calibration_bins=cal_bins,
            status="evaluated",
        )

    def evaluate_model(
        self,
        model: Any,
        X: pd.DataFrame,
        y_true: np.ndarray,
        returns: np.ndarray,
        model_version: str,
        dataset_version: str = "v1.0.0",
        outcome_statuses: Optional[list[str]] = None,
        feature_names: Optional[list[str]] = None,
        evaluation_date: Optional[date] = None,
        filter_by_prediction: bool = False,
        decision_threshold: Optional[float] = None,
    ) -> EvaluationReport:
        """Runs model inference on feature matrix X and evaluates metrics."""
        if len(X) == 0:
            return EvaluationReport(
                model_version=model_version,
                evaluation_date=evaluation_date or date.today(),
                dataset_version=dataset_version,
                sample_size=0,
            )

        features = X[feature_names] if feature_names is not None else X

        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(features)
            y_prob = probs[:, 1] if probs.ndim == 2 and probs.shape[1] > 1 else probs.ravel()
        elif hasattr(model, "predict"):
            y_prob = model.predict(features)
        else:
            raise TypeError(
                f"Model object {type(model)} has neither predict_proba nor predict method."
            )

        pred_metrics, cal_bins = self.evaluate_predictions(y_true, y_prob)

        if filter_by_prediction:
            thresh = decision_threshold if decision_threshold is not None else self.threshold
            mask = y_prob >= thresh
            trade_returns = returns[mask] if len(returns) == len(mask) else returns
            trade_statuses = (
                [s for s, m in zip(outcome_statuses, mask, strict=False) if m]
                if outcome_statuses is not None and len(outcome_statuses) == len(mask)
                else outcome_statuses
            )
            trade_metrics = compute_trading_metrics(trade_returns, outcome_statuses=trade_statuses)
        else:
            trade_metrics = compute_trading_metrics(returns, outcome_statuses=outcome_statuses)

        return EvaluationReport(
            model_version=model_version,
            evaluation_date=evaluation_date or date.today(),
            dataset_version=dataset_version,
            sample_size=len(X),
            trading_metrics=trade_metrics,
            prediction_metrics=pred_metrics,
            calibration_bins=cal_bins,
            status="evaluated",
        )

    def evaluate_from_outcomes(
        self,
        outcomes: list[SignalOutcomeRecord],
        model_version: str,
        dataset_version: str = "v1.0.0",
        evaluation_date: Optional[date] = None,
    ) -> EvaluationReport:
        """Evaluates performance directly from a list of SignalOutcomeRecord objects."""
        if not outcomes:
            return EvaluationReport(
                model_version=model_version,
                evaluation_date=evaluation_date or date.today(),
                dataset_version=dataset_version,
                sample_size=0,
            )

        filled_trades = [
            out
            for out in outcomes
            if out.outcome_status not in ("OPEN", "UNFILLED_EXPIRED", "INVALIDATED_GAP")
        ]
        returns = [out.realized_return for out in filled_trades if out.realized_return is not None]
        statuses = [out.outcome_status for out in filled_trades]
        trade_metrics = compute_trading_metrics(returns, outcome_statuses=statuses)

        return EvaluationReport(
            model_version=model_version,
            evaluation_date=evaluation_date or date.today(),
            dataset_version=dataset_version,
            sample_size=len(filled_trades),
            trading_metrics=trade_metrics,
            prediction_metrics=PredictionMetrics(
                accuracy=trade_metrics.win_rate,
            ),
            calibration_bins=[],
            status="evaluated",
        )
