import math
from typing import Union

import numpy as np


def compute_brier_score(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
) -> float:
    """Mean squared error between predicted probability and actual binary outcome."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_prob, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    return float(np.mean((yp - yt) ** 2))


def compute_log_loss(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    eps: float = 1e-15,
) -> float:
    """Binary cross-entropy / log loss with probability clipping."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_prob, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    yp = np.clip(yp, eps, 1.0 - eps)
    loss = -(yt * np.log(yp) + (1.0 - yt) * np.log(1.0 - yp))
    return float(np.mean(loss))


def compute_roc_auc(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
) -> float:
    """Area Under the ROC Curve. Returns 0.5 if only one class exists."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    if len(yt) == 0:
        return 0.5
    unique = np.unique(yt)
    if len(unique) < 2:
        return 0.5

    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(yt, yp))
    except Exception:
        # Fallback rank-based calculation
        n_pos = int(np.sum(yt == 1))
        n_neg = int(np.sum(yt == 0))
        if n_pos == 0 or n_neg == 0:
            return 0.5
        order = np.argsort(yp)
        ranks = np.empty_like(order, dtype=np.float64)
        ranks[order] = np.arange(len(yp)) + 1
        pos_ranks = np.sum(ranks[yt == 1])
        u_stat = pos_ranks - (n_pos * (n_pos + 1)) / 2.0
        return float(u_stat / (n_pos * n_neg))


def compute_accuracy(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    threshold: float = 0.5,
) -> float:
    """Classification accuracy at chosen decision threshold."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_prob, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    y_pred = (yp >= threshold).astype(np.int64)
    return float(np.mean(y_pred == yt))


def compute_expected_calibration_error(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error (ECE) across uniform confidence bins."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)
    if len(yt) == 0:
        return 0.0

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(yt)

    for i in range(n_bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (yp >= low) & (yp <= high)
        else:
            in_bin = (yp >= low) & (yp < high)

        count = int(np.sum(in_bin))
        if count > 0:
            bin_acc = float(np.mean(yt[in_bin]))
            bin_conf = float(np.mean(yp[in_bin]))
            ece += (count / n) * abs(bin_acc - bin_conf)

    return float(ece)


def compute_calibration_curve(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    n_bins: int = 10,
) -> tuple[np.ndarray, np.ndarray]:
    """Reliability curve: returns (mean_predicted_prob, observed_fraction_positive)."""
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)
    if len(yt) == 0:
        return np.array([]), np.array([])

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    conf_list = []
    acc_list = []

    for i in range(n_bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (yp >= low) & (yp <= high)
        else:
            in_bin = (yp >= low) & (yp < high)

        if np.any(in_bin):
            acc_list.append(float(np.mean(yt[in_bin])))
            conf_list.append(float(np.mean(yp[in_bin])))

    return np.array(conf_list), np.array(acc_list)


def evaluate_classification(
    y_true: Union[np.ndarray, list],
    y_prob: Union[np.ndarray, list],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Compute complete Section 17 & 31 prediction classification metrics."""
    return {
        "brier_score": compute_brier_score(y_true, y_prob),
        "log_loss": compute_log_loss(y_true, y_prob),
        "roc_auc": compute_roc_auc(y_true, y_prob),
        "accuracy": compute_accuracy(y_true, y_prob, threshold=threshold),
        "calibration_error": compute_expected_calibration_error(y_true, y_prob),
    }


def compute_mse(
    y_true: Union[np.ndarray, list],
    y_pred: Union[np.ndarray, list],
) -> float:
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    return float(np.mean((yt - yp) ** 2))


def compute_rmse(
    y_true: Union[np.ndarray, list],
    y_pred: Union[np.ndarray, list],
) -> float:
    return math.sqrt(compute_mse(y_true, y_pred))


def compute_mae(
    y_true: Union[np.ndarray, list],
    y_pred: Union[np.ndarray, list],
) -> float:
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    if len(yt) == 0:
        return 0.0
    return float(np.mean(np.abs(yt - yp)))


def compute_r2(
    y_true: Union[np.ndarray, list],
    y_pred: Union[np.ndarray, list],
) -> float:
    yt = np.asarray(y_true, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.float64)
    if len(yt) < 2:
        return 0.0
    ss_tot = np.sum((yt - np.mean(yt)) ** 2)
    if ss_tot == 0:
        return 0.0
    ss_res = np.sum((yt - yp) ** 2)
    return float(1.0 - (ss_res / ss_tot))


def evaluate_regression(
    y_true: Union[np.ndarray, list],
    y_pred: Union[np.ndarray, list],
) -> dict[str, float]:
    """Compute regression metrics (MSE, RMSE, MAE, R2)."""
    return {
        "mse": compute_mse(y_true, y_pred),
        "rmse": compute_rmse(y_true, y_pred),
        "mae": compute_mae(y_true, y_pred),
        "r2": compute_r2(y_true, y_pred),
    }
