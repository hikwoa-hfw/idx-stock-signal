"""Multi-Horizon Evaluation and Return Estimation Engine (Phase 11C).

Evaluates whether different holding horizons (3, 5, 10, 15 trading days)
and return-estimation models improve out-of-sample prediction and simulated
net trading performance for the BEI dual-mode stock-signal system.

Strict offline research contract:
- Production champion models and registry remain strictly immutable.
- Variant B (Next-Session Open-Anchor Target) is the primary executable entry proxy.
- 50 bps round-trip nominal friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip).
- 15 trading days purge window for walk-forward splits to prevent leakage across all horizons.
"""

import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from python.common.types import DailyBar, classify_price_mode
from python.config.settings import settings
from python.experiments.ablation import (
    ALL_FEATURE_COLUMNS,
    compute_daily_cross_sectional_top_k_precision,
    compute_daily_top_n_precision,
    evaluate_predictions,
)
from python.experiments.candidate_eval import BEST_ABLATIONS, SimulatedTrade
from python.models.baseline import (
    LightGBMClassifierBaseline,
    LightGBMRegressorBaseline,
    LogisticRegressionBaseline,
)
from python.models.validation import WalkForwardSplitter
from scripts.audit_target_contract_runner import load_all_bars

HORIZONS: list[int] = [3, 5, 10, 15]


def calculate_net_return(
    entry_price: float,
    exit_price: float,
    commission_buy: float = 0.0015,
    commission_sell: float = 0.0025,
    slippage_entry_bps: float = 5.0,
    slippage_exit_bps: float = 5.0,
) -> float:
    """Calculates exact net return under production friction contract (50 bps nominal)."""
    if entry_price <= 0:
        return 0.0
    entry_fill = entry_price * (1.0 + slippage_entry_bps / 10000.0)
    exit_fill = exit_price * (1.0 - slippage_exit_bps / 10000.0)
    invested = entry_fill * (1.0 + commission_buy)
    net_proceeds = exit_fill * (1.0 - commission_sell)
    return float((net_proceeds - invested) / invested)


def evaluate_variant_b_multi_horizon(
    entry_bar: DailyBar,
    forward_bars: list[DailyBar],
    horizons: list[int] = HORIZONS,
    tp_pct: float = 0.05,
    sl_pct: float = 0.02,
    max_entry_dev_pct: float = 0.05,
    entry_band_pct: float = 0.01,
    ambiguity_policy: str = "conservative",
) -> dict[int, dict[str, Any]]:
    """Evaluates Variant B target outcomes simultaneously across multiple holding horizons."""
    c_close = float(entry_bar.close)

    results: dict[int, dict[str, Any]] = {}

    if not forward_bars:
        for h in horizons:
            results[h] = {
                "status": "INSUFFICIENT_FORWARD_DATA",
                "entry_status": "NONE",
                "invalidation_reason": "NO_FORWARD_BARS",
                "entry_price": None,
                "outcome": "INCOMPLETE",
                "binary_target": None,
                "realized_gross": None,
                "realized_net": None,
                "holding_days": 0,
                "exit_date": None,
                "exit_price": None,
                "ambiguous_count": 0,
            }
        return results

    b1 = forward_bars[0]
    b1_open = float(b1.open)

    # Invalidation checks on Day 1 Open relative to Decision Close
    planned_sl = c_close * (1.0 - sl_pct)
    planned_tp = c_close * (1.0 + tp_pct)
    open_dev = abs(b1_open - c_close) / c_close

    if b1.volume <= 0:
        for h in horizons:
            results[h] = {
                "status": "INVALIDATED",
                "entry_status": "UNFILLED",
                "invalidation_reason": "ZERO_VOLUME_SUSPENDED",
                "entry_price": None,
                "outcome": "UNFILLED_SUSPENDED",
                "binary_target": None,
                "realized_gross": None,
                "realized_net": None,
                "holding_days": 0,
                "exit_date": None,
                "exit_price": None,
                "ambiguous_count": 0,
            }
        return results

    if b1_open <= planned_sl:
        for h in horizons:
            results[h] = {
                "status": "INVALIDATED",
                "entry_status": "UNFILLED",
                "invalidation_reason": "GAP_BELOW_SL",
                "entry_price": None,
                "outcome": "INVALIDATED_GAP",
                "binary_target": None,
                "realized_gross": None,
                "realized_net": None,
                "holding_days": 0,
                "exit_date": None,
                "exit_price": None,
                "ambiguous_count": 0,
            }
        return results

    if b1_open >= planned_tp:
        for h in horizons:
            results[h] = {
                "status": "INVALIDATED",
                "entry_status": "UNFILLED",
                "invalidation_reason": "GAP_ABOVE_TP",
                "entry_price": None,
                "outcome": "INVALIDATED_GAP",
                "binary_target": None,
                "realized_gross": None,
                "realized_net": None,
                "holding_days": 0,
                "exit_date": None,
                "exit_price": None,
                "ambiguous_count": 0,
            }
        return results

    if open_dev > max_entry_dev_pct:
        for h in horizons:
            results[h] = {
                "status": "INVALIDATED",
                "entry_status": "UNFILLED",
                "invalidation_reason": "EXCESSIVE_DEV",
                "entry_price": None,
                "outcome": "INVALIDATED_GAP",
                "binary_target": None,
                "realized_gross": None,
                "realized_net": None,
                "holding_days": 0,
                "exit_date": None,
                "exit_price": None,
                "ambiguous_count": 0,
            }
        return results

    # Valid entry at Day 1 Open
    ep = b1_open
    tp_price = ep * (1.0 + tp_pct)
    sl_price = ep * (1.0 - sl_pct)

    max_h = max(horizons)
    eval_bars = forward_bars[:max_h]

    # Pre-scan forward bars to detect first barrier hit
    first_hit_day: Optional[int] = None
    first_hit_outcome: Optional[str] = None
    first_hit_exit_price: Optional[float] = None
    first_hit_exit_date: Optional[date] = None
    ambiguous_hits = 0

    for k, bar in enumerate(eval_bars, start=1):
        tp_hit = bar.high >= tp_price
        sl_hit = bar.low <= sl_price

        if tp_hit and sl_hit:
            ambiguous_hits += 1
            first_hit_day = k
            first_hit_exit_date = bar.date
            if k == 1:
                first_hit_outcome = "SL" if ambiguity_policy == "conservative" else "TP"
                first_hit_exit_price = sl_price if ambiguity_policy == "conservative" else tp_price
            else:
                if bar.open >= tp_price:
                    first_hit_outcome = "TP"
                    first_hit_exit_price = float(bar.open)
                elif bar.open <= sl_price:
                    first_hit_outcome = "SL"
                    first_hit_exit_price = float(bar.open)
                else:
                    first_hit_outcome = "SL" if ambiguity_policy == "conservative" else "TP"
                    first_hit_exit_price = (
                        sl_price if ambiguity_policy == "conservative" else tp_price
                    )
            break
        elif tp_hit:
            first_hit_day = k
            first_hit_outcome = "TP"
            first_hit_exit_price = (
                float(bar.open) if (k > 1 and bar.open >= tp_price) else tp_price
            )
            first_hit_exit_date = bar.date
            break
        elif sl_hit:
            first_hit_day = k
            first_hit_outcome = "SL"
            first_hit_exit_price = (
                float(bar.open) if (k > 1 and bar.open <= sl_price) else sl_price
            )
            first_hit_exit_date = bar.date
            break

    # Construct outcomes for each requested horizon
    for h in horizons:
        if first_hit_day is not None and first_hit_day <= h:
            # Barrier hit within horizon h
            outcome = first_hit_outcome
            exit_price = first_hit_exit_price
            exit_date = first_hit_exit_date
            h_days = first_hit_day
            bin_target = 1 if outcome == "TP" else 0
            gross_ret = (exit_price - ep) / ep if exit_price is not None else 0.0
            net_ret = calculate_net_return(ep, exit_price) if exit_price is not None else 0.0
            results[h] = {
                "status": "VALID",
                "entry_status": "FILLED",
                "invalidation_reason": None,
                "entry_price": ep,
                "outcome": outcome,
                "binary_target": bin_target,
                "realized_gross": gross_ret,
                "realized_net": net_ret,
                "holding_days": h_days,
                "exit_date": exit_date,
                "exit_price": exit_price,
                "ambiguous_count": ambiguous_hits,
            }
        else:
            # Neither barrier hit within horizon h
            if len(forward_bars) >= h:
                # Reached expiry at bar h
                exp_bar = forward_bars[h - 1]
                exp_price = float(exp_bar.close)
                gross_ret = (exp_price - ep) / ep
                net_ret = calculate_net_return(ep, exp_price)
                results[h] = {
                    "status": "VALID",
                    "entry_status": "FILLED",
                    "invalidation_reason": None,
                    "entry_price": ep,
                    "outcome": "EXPIRY",
                    "binary_target": 0,
                    "realized_gross": gross_ret,
                    "realized_net": net_ret,
                    "holding_days": h,
                    "exit_date": exp_bar.date,
                    "exit_price": exp_price,
                    "ambiguous_count": 0,
                }
            else:
                # Incomplete observation: not enough forward bars to reach expiry
                results[h] = {
                    "status": "INCOMPLETE",
                    "entry_status": "FILLED",
                    "invalidation_reason": None,
                    "entry_price": ep,
                    "outcome": "INCOMPLETE",
                    "binary_target": None,
                    "realized_gross": None,
                    "realized_net": None,
                    "holding_days": len(forward_bars),
                    "exit_date": None,
                    "exit_price": None,
                    "ambiguous_count": 0,
                }

    return results


def evaluate_regression_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_train: Optional[np.ndarray] = None,
) -> dict[str, float]:
    """Computes MAE, RMSE, R2, and correlation against zero and mean baselines."""
    if len(y_true) == 0:
        return {
            "sample_size": 0,
            "mae": 0.0,
            "rmse": 0.0,
            "mae_zero_baseline": 0.0,
            "rmse_zero_baseline": 0.0,
            "mae_mean_baseline": 0.0,
            "rmse_mean_baseline": 0.0,
            "r2": 0.0,
            "pearson_r": 0.0,
        }
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    n = len(y_true)

    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))

    # Zero baseline
    mae_zero = float(np.mean(np.abs(y_true)))
    rmse_zero = float(np.sqrt(np.mean(y_true**2)))

    # Mean baseline
    mean_val = (
        float(np.mean(y_train))
        if (y_train is not None and len(y_train) > 0)
        else float(np.mean(y_true))
    )
    err_mean = mean_val - y_true
    mae_mean = float(np.mean(np.abs(err_mean)))
    rmse_mean = float(np.sqrt(np.mean(err_mean**2)))

    # R-squared
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    ss_res = float(np.sum(err**2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

    # Pearson correlation
    std_true = float(np.std(y_true))
    std_pred = float(np.std(y_pred))
    if std_true > 1e-12 and std_pred > 1e-12:
        cov = float(np.mean((y_true - np.mean(y_true)) * (y_pred - np.mean(y_pred))))
        pearson_r = cov / (std_true * std_pred)
    else:
        pearson_r = 0.0

    return {
        "sample_size": n,
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "mae_zero_baseline": round(mae_zero, 6),
        "rmse_zero_baseline": round(rmse_zero, 6),
        "mae_mean_baseline": round(mae_mean, 6),
        "rmse_mean_baseline": round(rmse_mean, 6),
        "r2": round(r2, 6),
        "pearson_r": round(pearson_r, 6),
    }


def compute_regression_binned_diagnostics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    bins: Optional[list[float]] = None,
) -> list[dict[str, Any]]:
    """Evaluates calibration and realized return across predicted return ranges."""
    if bins is None:
        bins = [-np.inf, -0.01, 0.0, 0.01, 0.02, np.inf]
    labels = ["< -1%", "[-1%, 0%)", "[0%, 1%)", "[1%, 2%)", ">= 2%"]

    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)

    results = []
    for i in range(len(bins) - 1):
        low, high = bins[i], bins[i + 1]
        lbl = labels[i]
        mask = (
            (y_pred >= low) & (y_pred < high)
            if i < len(bins) - 2
            else (y_pred >= low) & (y_pred <= high)
        )
        n_bin = int(mask.sum())
        if n_bin > 0:
            pred_sub = y_pred[mask]
            true_sub = y_true[mask]
            mean_pred = float(np.mean(pred_sub))
            mean_realized = float(np.mean(true_sub))
            error = mean_pred - mean_realized
            win_rate = float(np.mean(true_sub > 0))
            mae = float(np.mean(np.abs(pred_sub - true_sub)))
        else:
            mean_pred = 0.0
            mean_realized = 0.0
            error = 0.0
            win_rate = 0.0
            mae = 0.0

        results.append(
            {
                "bin_label": lbl,
                "count": n_bin,
                "pct_of_total": (
                    round(n_bin / len(y_true) * 100.0, 2) if len(y_true) > 0 else 0.0
                ),
                "mean_predicted_ret": round(mean_pred, 5),
                "mean_realized_ret": round(mean_realized, 5),
                "error": round(error, 5),
                "mae": round(mae, 5),
                "win_rate": round(win_rate, 4),
            }
        )
    return results


@dataclass
class HorizonModelSpec:
    model_id: str
    display_name: str
    model_family: str  # "lightgbm", "logistic", "prevalence", "regressor", etc.
    task_type: str  # "classification" or "regression"
    feature_group_excluded: Optional[str]
    features: list[str]


class MultiHorizonEvaluationRunner:
    """Coordinates Phase 11C Multi-Horizon evaluation and trading simulation."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        n_splits: int = 3,
        purge_days: int = 15,
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

    def load_multi_horizon_data(
        self,
        mode: str,
        horizons: list[int] = HORIZONS,
    ) -> tuple[pd.DataFrame, dict[str, list[DailyBar]]]:
        """Loads features, bars, and precomputes multi-horizon Variant B outcomes."""
        bars_by_ticker = load_all_bars(self.db_path)

        # Precompute multi-horizon outcomes across all bars
        mh_map: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        for ticker, t_bars in bars_by_ticker.items():
            s_bars = sorted(t_bars, key=lambda x: x.date)
            n_b = len(s_bars)
            for i in range(n_b):
                entry_b = s_bars[i]
                fwd_b = s_bars[i + 1 :]
                b_date_str = str(entry_b.date)
                mh_res = evaluate_variant_b_multi_horizon(
                    entry_bar=entry_b,
                    forward_bars=fwd_b,
                    horizons=horizons,
                    tp_pct=0.05,
                    sl_pct=0.02,
                    max_entry_dev_pct=0.05,
                    entry_band_pct=0.01,
                    ambiguity_policy="conservative",
                )
                mh_map[(ticker, b_date_str)] = mh_res

        # Query features and labels from SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cols_sql = ", ".join([f"f.{col}" for col in ALL_FEATURE_COLUMNS])
            query = f"""
                SELECT f.ticker, f.date, l.entry_price AS va_entry_price,
                       l.outcome AS va_outcome, l.binary_target AS va_binary_target,
                       {cols_sql}
                FROM features_daily f
                JOIN labels_daily l ON f.ticker = l.ticker AND f.date = l.date
                WHERE l.outcome != 'AMBIGUOUS' AND l.binary_target IS NOT NULL;
            """
            df_main = pd.read_sql_query(query, conn)
        finally:
            conn.close()

        if df_main.empty:
            raise ValueError(f"No records found in database for mode {mode}")

        # Classify decision price mode
        df_main["mode_decision"] = df_main["va_entry_price"].apply(classify_price_mode)
        target_mode = mode.strip().upper()
        df_filtered = df_main[df_main["mode_decision"] == target_mode].copy()

        if df_filtered.empty:
            raise ValueError(f"No records matching mode {target_mode}")

        # Attach multi-horizon target fields
        for h in horizons:
            status_list = []
            outcome_list = []
            binary_list = []
            gross_list = []
            net_list = []
            holding_list = []
            exit_price_list = []
            entry_price_list = []
            inval_list = []

            for _, row in df_filtered.iterrows():
                key = (row["ticker"].strip().upper().removesuffix(".JK"), str(row["date"]))
                bar_h = mh_map.get(key)
                if bar_h is not None and h in bar_h:
                    info = bar_h[h]
                    status_list.append(info["status"])
                    outcome_list.append(info["outcome"])
                    binary_list.append(info["binary_target"])
                    gross_list.append(info["realized_gross"])
                    net_list.append(info["realized_net"])
                    holding_list.append(info["holding_days"])
                    exit_price_list.append(info["exit_price"])
                    entry_price_list.append(info["entry_price"])
                    inval_list.append(info["invalidation_reason"])
                else:
                    status_list.append("UNKNOWN")
                    outcome_list.append("INCOMPLETE")
                    binary_list.append(None)
                    gross_list.append(None)
                    net_list.append(None)
                    holding_list.append(0)
                    exit_price_list.append(None)
                    entry_price_list.append(None)
                    inval_list.append("NO_DATA")

            df_filtered[f"vb_status_{h}"] = status_list
            df_filtered[f"vb_outcome_{h}"] = outcome_list
            df_filtered[f"vb_binary_target_{h}"] = binary_list
            df_filtered[f"vb_realized_gross_{h}"] = gross_list
            df_filtered[f"vb_realized_net_{h}"] = net_list
            df_filtered[f"vb_holding_days_{h}"] = holding_list
            df_filtered[f"vb_exit_price_{h}"] = exit_price_list
            df_filtered[f"vb_entry_price_{h}"] = entry_price_list
            df_filtered[f"vb_invalidation_reason_{h}"] = inval_list

        df_filtered["date"] = pd.to_datetime(df_filtered["date"]).dt.date
        df_filtered = df_filtered.sort_values(by=["date", "ticker"]).reset_index(drop=True)

        return df_filtered, bars_by_ticker

    def get_model_specs(self, mode: str) -> list[HorizonModelSpec]:
        """Returns controlled model specifications for classifiers and regressors."""
        ablation_cfg = BEST_ABLATIONS[mode]
        specs: list[HorizonModelSpec] = [
            # 1. Full LightGBM Classifier
            HorizonModelSpec(
                model_id="lgb_full",
                display_name="Full LightGBM Classifier (30 feats)",
                model_family="lightgbm",
                task_type="classification",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            # 2. Strongest Ablation LightGBM Classifier
            HorizonModelSpec(
                model_id=ablation_cfg["name"],
                display_name=f"Ablation LightGBM ({ablation_cfg['description']})",
                model_family="lightgbm",
                task_type="classification",
                feature_group_excluded=ablation_cfg["excluded_group"],
                features=list(ablation_cfg["features"]),
            ),
            # 3. Regularized Logistic Regression Baseline
            HorizonModelSpec(
                model_id="logistic_baseline",
                display_name="Regularized Logistic Regression Baseline",
                model_family="logistic",
                task_type="classification",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            # 4. Constant-prevalence classification baseline
            HorizonModelSpec(
                model_id="prevalence_baseline",
                display_name="Constant Prevalence Classification Baseline",
                model_family="prevalence",
                task_type="classification",
                feature_group_excluded=None,
                features=[],
            ),
            # 5. Return-Regression Model (Full LightGBM Regressor)
            HorizonModelSpec(
                model_id="lgb_regressor",
                display_name="LightGBM Return Regressor (30 feats)",
                model_family="lightgbm_regressor",
                task_type="regression",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            # 6. Zero-return baseline
            HorizonModelSpec(
                model_id="zero_return_baseline",
                display_name="Zero Return Regression Baseline",
                model_family="zero_return",
                task_type="regression",
                feature_group_excluded=None,
                features=[],
            ),
            # 7. Training-mean regression baseline
            HorizonModelSpec(
                model_id="mean_regressor_baseline",
                display_name="Training Mean Regression Baseline",
                model_family="mean_regressor",
                task_type="regression",
                feature_group_excluded=None,
                features=[],
            ),
        ]
        return specs

    def run_multi_horizon_evaluation(
        self,
        mode: str,
        horizons: list[int] = HORIZONS,
        simulate_trading: bool = True,
    ) -> dict[str, Any]:
        """Executes walk-forward multi-horizon classification, regression, and simulated trading."""
        df, bars_by_ticker = self.load_multi_horizon_data(mode, horizons=horizons)
        dates = df["date"].to_numpy()
        specs = self.get_model_specs(mode)

        splitter = WalkForwardSplitter(
            n_splits=self.n_splits,
            purge_days=self.purge_days,
            expanding=True,
        )

        col_index_map = {col: i for i, col in enumerate(ALL_FEATURE_COLUMNS)}

        # Master structure across horizons
        horizon_results: dict[int, dict[str, Any]] = {}
        all_oos_records: list[pd.DataFrame] = []

        for h in horizons:
            status_col = f"vb_status_{h}"
            bin_target_col = f"vb_binary_target_{h}"
            net_ret_col = f"vb_realized_net_{h}"
            outcome_col = f"vb_outcome_{h}"

            fold_clf_results: list[dict[str, Any]] = []
            fold_reg_results: list[dict[str, Any]] = []
            fold_trading_stats: dict[str, list[dict[str, Any]]] = {s.model_id: [] for s in specs}
            fold_trades: dict[str, list[SimulatedTrade]] = {s.model_id: [] for s in specs}
            fold_metadata: list[dict[str, Any]] = []
            ev_diagnostic_results: list[dict[str, Any]] = []

            for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(dates), start=1):
                d_tr_min, d_tr_max = str(dates[train_idx].min()), str(dates[train_idx].max())
                d_te_min, d_te_max = str(dates[test_idx].min()), str(dates[test_idx].max())

                df_train = df.iloc[train_idx]
                df_test = df.iloc[test_idx]

                # Filter valid executable samples
                tr_valid_mask = (df_train[status_col] == "VALID").to_numpy()
                te_valid_mask = (df_test[status_col] == "VALID").to_numpy()

                n_tr_valid = int(tr_valid_mask.sum())
                n_te_valid = int(te_valid_mask.sum())

                # Fit strictly causal median imputer on training fold
                X_all_train = df_train[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)
                X_all_test = df_test[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)

                imputer = SimpleImputer(
                    strategy="median", keep_empty_features=True, fill_value=0.0
                )
                X_all_train_imp = imputer.fit_transform(X_all_train)
                X_all_test_imp = imputer.transform(X_all_test)

                # Training subsets for valid samples
                X_tr_imp_valid = X_all_train_imp[tr_valid_mask]
                y_tr_bin = (
                    df_train.loc[tr_valid_mask, bin_target_col].to_numpy(dtype=np.int64)
                    if n_tr_valid > 0
                    else np.empty(0, dtype=np.int64)
                )
                y_tr_net = (
                    df_train.loc[tr_valid_mask, net_ret_col].to_numpy(dtype=np.float64)
                    if n_tr_valid > 0
                    else np.empty(0, dtype=np.float64)
                )

                # Test subsets for valid samples
                y_te_bin = (
                    df_test.loc[te_valid_mask, bin_target_col].to_numpy(dtype=np.int64)
                    if n_te_valid > 0
                    else np.empty(0, dtype=np.int64)
                )
                y_te_net = (
                    df_test.loc[te_valid_mask, net_ret_col].to_numpy(dtype=np.float64)
                    if n_te_valid > 0
                    else np.empty(0, dtype=np.float64)
                )

                # Training fold outcome distribution (for discrete EV estimation)
                tr_outcomes = df_train.loc[tr_valid_mask, outcome_col].to_numpy()
                n_tp_tr = int((tr_outcomes == "TP").sum())
                n_sl_tr = int((tr_outcomes == "SL").sum())
                n_exp_tr = int((tr_outcomes == "EXPIRY").sum())

                r_tp_mean = float(y_tr_net[tr_outcomes == "TP"].mean()) if n_tp_tr > 0 else 0.0448
                r_sl_mean = float(y_tr_net[tr_outcomes == "SL"].mean()) if n_sl_tr > 0 else -0.0249
                r_exp_mean = (
                    float(y_tr_net[tr_outcomes == "EXPIRY"].mean()) if n_exp_tr > 0 else -0.0050
                )
                q_sl_ratio = (
                    float(n_sl_tr / (n_sl_tr + n_exp_tr)) if (n_sl_tr + n_exp_tr) > 0 else 0.5
                )

                fold_meta = {
                    "horizon": h,
                    "fold": fold_idx,
                    "train_dates": f"{d_tr_min} -> {d_tr_max}",
                    "train_days": len(np.unique(dates[train_idx])),
                    "train_samples_total": len(df_train),
                    "train_samples_valid": n_tr_valid,
                    "train_positives": int(y_tr_bin.sum()),
                    "train_prevalence": round(float(y_tr_bin.mean()), 4) if n_tr_valid > 0 else 0.0,
                    "train_mean_net_return": (
                        round(float(y_tr_net.mean()), 6) if n_tr_valid > 0 else 0.0
                    ),
                    "test_dates": f"{d_te_min} -> {d_te_max}",
                    "test_days": len(np.unique(dates[test_idx])),
                    "test_samples_total": len(df_test),
                    "test_samples_valid": n_te_valid,
                    "test_positives": int(y_te_bin.sum()),
                    "test_prevalence": round(float(y_te_bin.mean()), 4) if n_te_valid > 0 else 0.0,
                    "test_mean_net_return": (
                        round(float(y_te_net.mean()), 6) if n_te_valid > 0 else 0.0
                    ),
                    "test_invalidated": int((df_test[status_col] == "INVALIDATED").sum()),
                    "test_incomplete": int((df_test[status_col] == "INCOMPLETE").sum()),
                }
                fold_metadata.append(fold_meta)

                # Predictions map on test fold (full test rows)
                predictions_map: dict[str, np.ndarray] = {}

                for spec in specs:
                    m_id = spec.model_id
                    feat_cols = spec.features
                    m_fam = spec.model_family
                    t_type = spec.task_type

                    # Extract training features
                    if feat_cols:
                        feat_indices = [col_index_map[c] for c in feat_cols]
                        X_tr = X_tr_imp_valid[:, feat_indices]
                        X_te_full = X_all_test_imp[:, feat_indices]
                    else:
                        X_tr = np.empty((n_tr_valid, 0))
                        X_te_full = np.empty((len(test_idx), 0))

                    if t_type == "classification":
                        if m_fam == "prevalence":
                            prev_val = float(y_tr_bin.mean()) if len(y_tr_bin) > 0 else 0.0
                            y_prob_full = np.full(len(test_idx), prev_val, dtype=np.float64)
                            y_prob_valid = np.full(n_te_valid, prev_val, dtype=np.float64)
                        elif m_fam == "logistic":
                            clf = LogisticRegressionBaseline(
                                C=1.0,
                                max_iter=1000,
                                random_state=self.random_state,
                                calibrated=False,
                            )
                            clf.fit(X_tr, y_tr_bin, feature_names=feat_cols)
                            y_prob_full = clf.predict_probability(X_te_full)
                            y_prob_valid = y_prob_full[te_valid_mask]
                        else:  # lightgbm classifier
                            clf = LightGBMClassifierBaseline(
                                n_estimators=100,
                                learning_rate=0.05,
                                max_depth=5,
                                num_leaves=31,
                                min_child_samples=20,
                                random_state=self.random_state,
                                calibrated=False,
                            )
                            clf.fit(X_tr, y_tr_bin, feature_names=feat_cols)
                            y_prob_full = clf.predict_probability(X_te_full)
                            y_prob_valid = y_prob_full[te_valid_mask]

                        predictions_map[m_id] = y_prob_full

                        # Compute classification metrics on valid test samples
                        clf_metrics = evaluate_predictions(y_te_bin, y_prob_valid)

                        # Daily cross-sectional Top-10% and Top-5 precision
                        test_dates_valid = df_test.loc[te_valid_mask, "date"].to_numpy()
                        test_tickers_valid = df_test.loc[te_valid_mask, "ticker"].to_numpy()
                        fold_df_native = pd.DataFrame(
                            {
                                "ticker": test_tickers_valid,
                                "date": test_dates_valid,
                                "binary_target": y_te_bin,
                                "y_prob": y_prob_valid,
                            }
                        )
                        daily_top10 = compute_daily_cross_sectional_top_k_precision(
                            fold_df_native, k_pct=0.10, min_candidates=10
                        )
                        daily_top5 = compute_daily_top_n_precision(
                            fold_df_native, top_n=5, min_candidates=5
                        )

                        fold_clf_results.append(
                            {
                                "horizon": h,
                                "fold": fold_idx,
                                "model_id": m_id,
                                "samples": clf_metrics["sample_size"],
                                "positives": clf_metrics["positive_count"],
                                "prevalence": clf_metrics["prevalence"],
                                "roc_auc": clf_metrics["roc_auc"],
                                "pr_auc": clf_metrics["pr_auc"],
                                "brier_score": clf_metrics["brier_score"],
                                "log_loss": clf_metrics["log_loss"],
                                "ece": clf_metrics["ece"],
                                "accuracy": clf_metrics["accuracy"],
                                "daily_top10_prec": daily_top10["daily_precision_macro"],
                                "daily_top10_std": daily_top10["daily_precision_std"],
                                "daily_top5_prec": daily_top5["daily_precision_macro"],
                                "daily_eval_dates": daily_top10["evaluated_dates"],
                                "daily_candidates_per_date_median": daily_top10[
                                    "candidates_per_date_median"
                                ],
                            }
                        )

                    else:  # regression task
                        if m_fam == "zero_return":
                            y_pred_full = np.zeros(len(test_idx), dtype=np.float64)
                            y_pred_valid = np.zeros(n_te_valid, dtype=np.float64)
                        elif m_fam == "mean_regressor":
                            mean_ret = float(y_tr_net.mean()) if len(y_tr_net) > 0 else 0.0
                            y_pred_full = np.full(len(test_idx), mean_ret, dtype=np.float64)
                            y_pred_valid = np.full(n_te_valid, mean_ret, dtype=np.float64)
                        else:  # lightgbm regressor
                            reg = LightGBMRegressorBaseline(
                                n_estimators=100,
                                learning_rate=0.05,
                                max_depth=5,
                                num_leaves=31,
                                min_child_samples=20,
                                random_state=self.random_state,
                            )
                            reg.fit(X_tr, y_tr_net, feature_names=feat_cols)
                            y_pred_full = reg.predict(X_te_full)
                            y_pred_valid = y_pred_full[te_valid_mask]

                        predictions_map[m_id] = y_pred_full

                        # Compute regression metrics
                        reg_metrics = evaluate_regression_predictions(
                            y_true=y_te_net,
                            y_pred=y_pred_valid,
                            y_train=y_tr_net,
                        )
                        binned_diag = compute_regression_binned_diagnostics(
                            y_true=y_te_net,
                            y_pred=y_pred_valid,
                        )

                        fold_reg_results.append(
                            {
                                "horizon": h,
                                "fold": fold_idx,
                                "model_id": m_id,
                                **reg_metrics,
                                "binned_diagnostics": binned_diag,
                            }
                        )

                # Expected Return Diagnostic: Classifier Discrete EV vs Continuous Regressor
                p_lgb = predictions_map["lgb_full"][te_valid_mask]
                r_pred_lgb = predictions_map["lgb_regressor"][te_valid_mask]

                # Discrete EV formulation: p * R_tp + (1-p)*q_sl*R_sl + (1-p)*(1-q_sl)*R_exp
                ev_discrete = (
                    p_lgb * r_tp_mean
                    + (1.0 - p_lgb) * q_sl_ratio * r_sl_mean
                    + (1.0 - p_lgb) * (1.0 - q_sl_ratio) * r_exp_mean
                )

                corr_reg = (
                    float(np.corrcoef(r_pred_lgb, y_te_net)[0, 1])
                    if len(y_te_net) > 1 and np.std(r_pred_lgb) > 1e-12
                    else 0.0
                )
                corr_ev = (
                    float(np.corrcoef(ev_discrete, y_te_net)[0, 1])
                    if len(y_te_net) > 1 and np.std(ev_discrete) > 1e-12
                    else 0.0
                )
                corr_p = (
                    float(np.corrcoef(p_lgb, y_te_net)[0, 1])
                    if len(y_te_net) > 1 and np.std(p_lgb) > 1e-12
                    else 0.0
                )

                # Positive EV / predicted return trade subsets
                pos_ev_mask = ev_discrete > 0.0
                pos_reg_mask = r_pred_lgb > 0.0

                ev_diagnostic_results.append(
                    {
                        "horizon": h,
                        "fold": fold_idx,
                        "r_tp_training_mean": round(r_tp_mean, 5),
                        "r_sl_training_mean": round(r_sl_mean, 5),
                        "r_exp_training_mean": round(r_exp_mean, 5),
                        "q_sl_training_ratio": round(q_sl_ratio, 4),
                        "pearson_r_regressor": round(corr_reg, 4),
                        "pearson_r_discrete_ev": round(corr_ev, 4),
                        "pearson_r_classifier_prob": round(corr_p, 4),
                        "total_valid_test_samples": n_te_valid,
                        "positive_ev_count": int(pos_ev_mask.sum()),
                        "positive_ev_win_rate": (
                            round(float(np.mean(y_te_net[pos_ev_mask] > 0)), 4)
                            if pos_ev_mask.sum() > 0
                            else 0.0
                        ),
                        "positive_ev_avg_net_return": (
                            round(float(np.mean(y_te_net[pos_ev_mask])), 5)
                            if pos_ev_mask.sum() > 0
                            else 0.0
                        ),
                        "positive_reg_count": int(pos_reg_mask.sum()),
                        "positive_reg_win_rate": (
                            round(float(np.mean(y_te_net[pos_reg_mask] > 0)), 4)
                            if pos_reg_mask.sum() > 0
                            else 0.0
                        ),
                        "positive_reg_avg_net_return": (
                            round(float(np.mean(y_te_net[pos_reg_mask])), 5)
                            if pos_reg_mask.sum() > 0
                            else 0.0
                        ),
                    }
                )

                # Simulated Trading for this fold and horizon
                if simulate_trading:
                    # Simulated models: lgb_full, ablation, logistic, prevalence, regressor
                    trading_models = [
                        s.model_id
                        for s in specs
                        if s.model_id
                        in [
                            "lgb_full",
                            BEST_ABLATIONS[mode]["name"],
                            "logistic_baseline",
                            "prevalence_baseline",
                            "lgb_regressor",
                        ]
                    ]
                    for m_id in trading_models:
                        t_res = self._simulate_horizon_trading(
                            df_test=df_test,
                            predictions=predictions_map[m_id],
                            bars_by_ticker=bars_by_ticker,
                            max_holding_days=h,
                            initial_capital=100_000_000.0,
                            max_positions=5,
                            top_n_per_day=5,
                            commission_buy=0.0015,
                            commission_sell=0.0025,
                            slippage_entry_bps=5.0,
                            slippage_exit_bps=5.0,
                        )
                        fold_trades[m_id].extend(t_res["trades"])
                        t_stat = {
                            "horizon": h,
                            "fold": fold_idx,
                            "model_id": m_id,
                            **{k: v for k, v in t_res.items() if k != "trades"},
                        }
                        fold_trading_stats[m_id].append(t_stat)

                # Store out-of-sample prediction rows for this fold
                oos_df = pd.DataFrame(
                    {
                        "horizon": [h] * len(test_idx),
                        "fold": [fold_idx] * len(test_idx),
                        "date": [str(d) for d in df_test["date"]],
                        "ticker": list(df_test["ticker"]),
                        "mode": [mode] * len(test_idx),
                        "decision_price": list(df_test["va_entry_price"]),
                        "vb_status": list(df_test[status_col]),
                        "vb_binary_target": list(df_test[bin_target_col]),
                        "vb_realized_net": list(df_test[net_ret_col]),
                        "vb_outcome": list(df_test[outcome_col]),
                        "prob_lgb_full": list(predictions_map["lgb_full"]),
                        "prob_lgb_ablation": list(
                            predictions_map[BEST_ABLATIONS[mode]["name"]]
                        ),
                        "prob_logistic": list(predictions_map["logistic_baseline"]),
                        "prob_prevalence": list(predictions_map["prevalence_baseline"]),
                        "pred_return_lgb": list(predictions_map["lgb_regressor"]),
                    }
                )
                all_oos_records.append(oos_df)

            # Summaries across folds for horizon h
            clf_summaries = self._compute_macro_classification_summaries(fold_clf_results, specs)
            reg_summaries = self._compute_macro_regression_summaries(fold_reg_results, specs)
            trade_summaries = self._aggregate_trading_summaries(
                all_model_trade_stats=fold_trading_stats,
                specs=specs,
                all_model_trades=fold_trades,
                horizon=h,
            )

            horizon_results[h] = {
                "horizon": h,
                "fold_metadata": fold_metadata,
                "classification_fold_results": fold_clf_results,
                "classification_summaries": clf_summaries,
                "regression_fold_results": fold_reg_results,
                "regression_summaries": reg_summaries,
                "trading_fold_stats": fold_trading_stats,
                "trading_summaries": trade_summaries,
                "ev_diagnostic_results": ev_diagnostic_results,
            }

        full_oos_df = pd.concat(all_oos_records, ignore_index=True)

        return {
            "mode": mode,
            "n_splits": self.n_splits,
            "purge_days": self.purge_days,
            "random_state": self.random_state,
            "total_universe_samples": len(df),
            "horizons": horizons,
            "horizon_results": horizon_results,
            "oos_predictions": full_oos_df,
        }

    def _simulate_horizon_trading(
        self,
        df_test: pd.DataFrame,
        predictions: np.ndarray,
        bars_by_ticker: dict[str, list[DailyBar]],
        max_holding_days: int,
        initial_capital: float = 100_000_000.0,
        max_positions: int = 5,
        top_n_per_day: int = 5,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
    ) -> dict[str, Any]:
        """Simulates discrete-event trading for a specific maximum holding horizon."""
        eval_df = df_test[["ticker", "date", "va_entry_price"]].copy()
        eval_df["score"] = predictions

        dates_sorted = sorted(eval_df["date"].unique())

        cash = float(initial_capital)
        peak_equity = float(initial_capital)
        total_eq = float(initial_capital)
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        daily_equity: list[tuple[date, float]] = []

        open_positions: dict[str, dict[str, Any]] = {}
        completed_trades: list[SimulatedTrade] = []

        total_signals_generated = 0
        invalidated_gap_down = 0
        invalidated_gap_up = 0
        invalidated_excessive_dev = 0
        unfilled_suspended = 0
        unfilled_capacity = 0
        unfilled_cash = 0

        bar_lookup: dict[tuple[str, date], DailyBar] = {}
        for t, b_list in bars_by_ticker.items():
            for b in b_list:
                bar_lookup[(t, b.date)] = b

        pending_orders: list[dict[str, Any]] = []
        last_known_close: dict[str, float] = {}

        for curr_d in dates_sorted:
            # 1. Execute pending orders from previous trading date
            if pending_orders:
                # Rank pending orders: score desc, ticker asc
                pending_orders.sort(key=lambda o: (-o["score"], o["ticker"]))

                for ord_info in pending_orders:
                    t = ord_info["ticker"]
                    c_close = ord_info["close_t"]

                    if len(open_positions) >= max_positions:
                        unfilled_capacity += 1
                        continue
                    if t in open_positions:
                        unfilled_capacity += 1
                        continue

                    bar_next = bar_lookup.get((t, curr_d))
                    if bar_next is None or bar_next.volume <= 0:
                        unfilled_suspended += 1
                        continue

                    b_open = float(bar_next.open)
                    if b_open <= 0:
                        unfilled_suspended += 1
                        continue

                    # Pre-entry gap and deviation checks (fail-closed)
                    if b_open <= c_close * 0.98:
                        invalidated_gap_down += 1
                        continue
                    if b_open >= c_close * 1.05:
                        invalidated_gap_up += 1
                        continue
                    if abs(b_open - c_close) / c_close > 0.05:
                        invalidated_excessive_dev += 1
                        continue

                    # Sizing: Equal weight allocation capped at 20% equity
                    # Causal: Use strictly previous day's close or entry price (no lookahead)
                    open_val = sum(
                        pos["shares"]
                        * last_known_close.get(pos["ticker"], pos["entry_price"])
                        for pos in open_positions.values()
                    )
                    current_equity = cash + open_val

                    cap_per_pos = min(
                        current_equity / max_positions,
                        current_equity * 0.20,
                    )
                    fill_price = b_open * (1.0 + slippage_entry_bps / 10000.0)
                    raw_shares = cap_per_pos / fill_price
                    max_cash_shares = cash / (fill_price * (1.0 + commission_buy))
                    shares_f = min(raw_shares, max_cash_shares)

                    # Lot size rounding (100 shares per lot)
                    shares = int(shares_f // 100) * 100
                    if shares < 100:
                        unfilled_cash += 1
                        continue

                    gross_outlay = shares * fill_price
                    entry_fee = gross_outlay * commission_buy
                    total_outlay = gross_outlay + entry_fee

                    if total_outlay > cash:
                        shares = int((cash / (fill_price * (1.0 + commission_buy))) // 100) * 100
                        if shares < 100:
                            unfilled_cash += 1
                            continue
                        gross_outlay = shares * fill_price
                        entry_fee = gross_outlay * commission_buy
                        total_outlay = gross_outlay + entry_fee

                    cash -= total_outlay
                    open_positions[t] = {
                        "ticker": t,
                        "signal_date": ord_info["signal_date"],
                        "entry_date": curr_d,
                        "entry_price": fill_price,
                        "raw_entry": b_open,
                        "shares": shares,
                        "entry_fee": entry_fee,
                        "tp_price": fill_price * 1.05,
                        "sl_price": fill_price * 0.98,
                        "holding_days": 1,
                        "score": ord_info["score"],
                    }

                pending_orders.clear()

            # 2. Intraday barrier checks on Day curr_d for active positions
            active_tickers = list(open_positions.keys())
            for t in active_tickers:
                pos = open_positions[t]
                bar_curr = bar_lookup.get((t, curr_d))

                if bar_curr is None or bar_curr.volume <= 0:
                    pos["holding_days"] += 1
                    continue

                tp_hit = bar_curr.high >= pos["tp_price"]
                sl_hit = bar_curr.low <= pos["sl_price"]
                exit_reason = None
                exit_raw = None

                if tp_hit and sl_hit:
                    # Conservative policy: SL takes precedence
                    exit_reason = "SL"
                    exit_raw = pos["sl_price"]
                elif tp_hit:
                    exit_reason = "TP"
                    exit_raw = (
                        float(bar_curr.open)
                        if (pos["holding_days"] > 1 and bar_curr.open >= pos["tp_price"])
                        else pos["tp_price"]
                    )
                elif sl_hit:
                    exit_reason = "SL"
                    exit_raw = (
                        float(bar_curr.open)
                        if (pos["holding_days"] > 1 and bar_curr.open <= pos["sl_price"])
                        else pos["sl_price"]
                    )
                elif pos["holding_days"] >= max_holding_days:
                    exit_reason = "EXPIRY"
                    exit_raw = float(bar_curr.close)

                if exit_reason is not None and exit_raw is not None:
                    exit_fill = exit_raw * (1.0 - slippage_exit_bps / 10000.0)
                    gross_proceeds = pos["shares"] * exit_fill
                    exit_fee = gross_proceeds * commission_sell
                    net_proceeds = gross_proceeds - exit_fee
                    cash += net_proceeds

                    net_pnl = net_proceeds - (
                        pos["shares"] * pos["entry_price"] + pos["entry_fee"]
                    )
                    invested = pos["shares"] * pos["entry_price"] + pos["entry_fee"]
                    net_ret = net_pnl / invested if invested > 0 else 0.0

                    trade = SimulatedTrade(
                        ticker=pos["ticker"],
                        signal_date=pos["signal_date"],
                        entry_date=pos["entry_date"],
                        exit_date=curr_d,
                        entry_price=pos["entry_price"],
                        exit_price=exit_fill,
                        shares=pos["shares"],
                        gross_pnl=gross_proceeds - pos["shares"] * pos["entry_price"],
                        net_pnl=net_pnl,
                        net_return=net_ret,
                        exit_reason=exit_reason,
                        holding_days=pos["holding_days"],
                        signal_prob=pos["score"],
                    )
                    completed_trades.append(trade)
                    del open_positions[t]
                else:
                    pos["holding_days"] += 1

            # 3. Mark to market equity & drawdown calculation
            for t_open in open_positions.keys():
                bar_c = bar_lookup.get((t_open, curr_d))
                if bar_c is not None and bar_c.close > 0:
                    last_known_close[t_open] = float(bar_c.close)

            eod_val = sum(
                pos["shares"]
                * (
                    bar_lookup[(pos["ticker"], curr_d)].close
                    if (pos["ticker"], curr_d) in bar_lookup
                    and bar_lookup[(pos["ticker"], curr_d)].close > 0
                    else pos["entry_price"]
                )
                for pos in open_positions.values()
            )
            total_eq = cash + eod_val
            daily_equity.append((curr_d, total_eq))
            if total_eq > peak_equity:
                peak_equity = total_eq
            dd_amt = peak_equity - total_eq
            dd_pct = dd_amt / peak_equity if peak_equity > 0 else 0.0
            if dd_amt > max_dd_amount:
                max_dd_amount = dd_amt
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # 4. Evening signal generation on Day curr_d
            day_candidates = eval_df[eval_df["date"] == curr_d]
            if len(day_candidates) >= 10:
                sorted_cands = day_candidates.sort_values(
                    by=["score", "ticker"], ascending=[False, True], kind="stable"
                )
                top_picks = sorted_cands.iloc[:top_n_per_day]
                for _, r in top_picks.iterrows():
                    total_signals_generated += 1
                    pending_orders.append(
                        {
                            "ticker": r["ticker"],
                            "signal_date": curr_d,
                            "close_t": float(r["va_entry_price"]),
                            "score": float(r["score"]),
                        }
                    )

        # Final summary statistics for fold
        n_trades = len(completed_trades)
        wins = sum(1 for t in completed_trades if t.net_pnl > 0)
        win_rate = (wins / n_trades) if n_trades > 0 else 0.0

        tp_count = sum(1 for t in completed_trades if t.exit_reason == "TP")
        sl_count = sum(1 for t in completed_trades if t.exit_reason == "SL")
        exp_count = sum(1 for t in completed_trades if t.exit_reason == "EXPIRY")

        total_gain = sum(t.net_pnl for t in completed_trades if t.net_pnl > 0)
        total_loss = sum(abs(t.net_pnl) for t in completed_trades if t.net_pnl < 0)
        profit_factor = (
            (total_gain / total_loss)
            if total_loss > 0
            else (float("inf") if total_gain > 0 else 0.0)
        )

        avg_net_ret = (
            sum(t.net_return for t in completed_trades) / n_trades if n_trades > 0 else 0.0
        )
        avg_holding = (
            sum(t.holding_days for t in completed_trades) / n_trades if n_trades > 0 else 0.0
        )

        total_invalidated = (
            invalidated_gap_down + invalidated_gap_up + invalidated_excessive_dev
        )
        total_unfilled = unfilled_suspended + unfilled_capacity + unfilled_cash

        return {
            "initial_capital": initial_capital,
            "final_equity": round(total_eq, 2),
            "total_signals": total_signals_generated,
            "completed_trades": n_trades,
            "win_rate": round(win_rate, 4),
            "tp_count": tp_count,
            "tp_rate": round(tp_count / n_trades, 4) if n_trades > 0 else 0.0,
            "sl_count": sl_count,
            "sl_rate": round(sl_count / n_trades, 4) if n_trades > 0 else 0.0,
            "expiry_count": exp_count,
            "expiry_rate": round(exp_count / n_trades, 4) if n_trades > 0 else 0.0,
            "avg_net_return": round(avg_net_ret, 4),
            "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else 999.0,
            "max_drawdown_pct": round(max_dd_pct * 100.0, 2),
            "max_drawdown_amount": round(max_dd_amount, 2),
            "avg_holding_days": round(avg_holding, 1),
            "invalidated_total": total_invalidated,
            "invalidated_gap_down": invalidated_gap_down,
            "invalidated_gap_up": invalidated_gap_up,
            "invalidated_excessive_dev": invalidated_excessive_dev,
            "unfilled_total": total_unfilled,
            "unfilled_suspended": unfilled_suspended,
            "unfilled_capacity": unfilled_capacity,
            "unfilled_cash": unfilled_cash,
            "daily_equity": daily_equity,
            "trades": completed_trades,
        }

    def _compute_macro_classification_summaries(
        self,
        fold_results: list[dict[str, Any]],
        specs: list[HorizonModelSpec],
    ) -> list[dict[str, Any]]:
        """Computes macro fold-aggregated predictive metrics across walk-forward splits."""
        summaries: list[dict[str, Any]] = []
        df_folds = pd.DataFrame(fold_results)

        for spec in specs:
            if spec.task_type != "classification":
                continue
            m_id = spec.model_id
            m_df = df_folds[df_folds["model_id"] == m_id]
            if m_df.empty:
                continue

            roc_mean = float(m_df["roc_auc"].mean())
            roc_std = float(m_df["roc_auc"].std(ddof=1)) if len(m_df) > 1 else 0.0
            pr_mean = float(m_df["pr_auc"].mean())
            pr_std = float(m_df["pr_auc"].std(ddof=1)) if len(m_df) > 1 else 0.0
            brier_mean = float(m_df["brier_score"].mean())
            log_loss_mean = float(m_df["log_loss"].mean())
            ece_mean = float(m_df["ece"].mean())
            daily_top10_mean = float(m_df["daily_top10_prec"].mean())
            daily_top10_std = (
                float(m_df["daily_top10_prec"].std(ddof=1)) if len(m_df) > 1 else 0.0
            )
            daily_top5_mean = float(m_df["daily_top5_prec"].mean())

            summaries.append(
                {
                    "model_id": m_id,
                    "display_name": spec.display_name,
                    "task_type": "classification",
                    "features_used": len(spec.features),
                    "macro_roc_auc_mean": round(roc_mean, 4),
                    "macro_roc_auc_std": round(roc_std, 4),
                    "macro_pr_auc_mean": round(pr_mean, 4),
                    "macro_pr_auc_std": round(pr_std, 4),
                    "macro_brier_mean": round(brier_mean, 4),
                    "macro_log_loss_mean": round(log_loss_mean, 4),
                    "macro_ece_mean": round(ece_mean, 4),
                    "macro_daily_top10_mean": round(daily_top10_mean, 4),
                    "macro_daily_top10_std": round(daily_top10_std, 4),
                    "macro_daily_top5_mean": round(daily_top5_mean, 4),
                }
            )

        return summaries

    def _compute_macro_regression_summaries(
        self,
        fold_results: list[dict[str, Any]],
        specs: list[HorizonModelSpec],
    ) -> list[dict[str, Any]]:
        """Computes macro fold-aggregated regression metrics across walk-forward splits."""
        summaries: list[dict[str, Any]] = []
        df_folds = pd.DataFrame(fold_results)

        for spec in specs:
            if spec.task_type != "regression":
                continue
            m_id = spec.model_id
            m_df = df_folds[df_folds["model_id"] == m_id]
            if m_df.empty:
                continue

            mae_mean = float(m_df["mae"].mean())
            rmse_mean = float(m_df["rmse"].mean())
            mae_zero_mean = float(m_df["mae_zero_baseline"].mean())
            rmse_zero_mean = float(m_df["rmse_zero_baseline"].mean())
            mae_mean_mean = float(m_df["mae_mean_baseline"].mean())
            rmse_mean_mean = float(m_df["rmse_mean_baseline"].mean())
            r2_mean = float(m_df["r2"].mean())
            r_mean = float(m_df["pearson_r"].mean())

            summaries.append(
                {
                    "model_id": m_id,
                    "display_name": spec.display_name,
                    "task_type": "regression",
                    "features_used": len(spec.features),
                    "macro_mae_mean": round(mae_mean, 6),
                    "macro_rmse_mean": round(rmse_mean, 6),
                    "macro_mae_zero_mean": round(mae_zero_mean, 6),
                    "macro_rmse_zero_mean": round(rmse_zero_mean, 6),
                    "macro_mae_mean_baseline_mean": round(mae_mean_mean, 6),
                    "macro_rmse_mean_baseline_mean": round(rmse_mean_mean, 6),
                    "macro_r2_mean": round(r2_mean, 6),
                    "macro_pearson_r_mean": round(r_mean, 6),
                }
            )

        return summaries

    def _aggregate_trading_summaries(
        self,
        all_model_trade_stats: dict[str, list[dict[str, Any]]],
        specs: list[HorizonModelSpec],
        all_model_trades: Optional[dict[str, list[SimulatedTrade]]] = None,
        horizon: int = 10,
    ) -> list[dict[str, Any]]:
        """Aggregates simulated trading results across folds for a specific horizon."""
        summaries: list[dict[str, Any]] = []

        for spec in specs:
            m_id = spec.model_id
            stats = all_model_trade_stats.get(m_id, [])
            if not stats:
                continue

            total_trades = sum(s["completed_trades"] for s in stats)
            total_signals = sum(s["total_signals"] for s in stats)
            total_invalid = sum(s["invalidated_total"] for s in stats)
            total_unfilled = sum(s["unfilled_total"] for s in stats)

            tp_tot = sum(s["tp_count"] for s in stats)
            sl_tot = sum(s["sl_count"] for s in stats)
            exp_tot = sum(s["expiry_count"] for s in stats)

            win_rate = (
                sum(s["win_rate"] * s["completed_trades"] for s in stats) / total_trades
                if total_trades > 0
                else 0.0
            )
            avg_net_ret = (
                sum(s["avg_net_return"] * s["completed_trades"] for s in stats) / total_trades
                if total_trades > 0
                else 0.0
            )
            avg_holding = (
                sum(s["avg_holding_days"] * s["completed_trades"] for s in stats) / total_trades
                if total_trades > 0
                else 0.0
            )

            # Fold-level profit factors and mean fold profit factor
            pf_vals = [s["profit_factor"] for s in stats if math.isfinite(s["profit_factor"])]
            mean_pf = float(np.mean(pf_vals)) if pf_vals else 0.0

            # True pooled profit factor across all completed trades (sum gains / sum losses)
            if all_model_trades and m_id in all_model_trades and all_model_trades[m_id]:
                trades = all_model_trades[m_id]
                pooled_gain = sum(t.net_pnl for t in trades if t.net_pnl > 0)
                pooled_loss = sum(abs(t.net_pnl) for t in trades if t.net_pnl < 0)
                pooled_pf = (
                    (pooled_gain / pooled_loss)
                    if pooled_loss > 0
                    else (float("inf") if pooled_gain > 0 else 0.0)
                )
            else:
                pooled_pf = mean_pf

            # Worst-fold maximum drawdown
            worst_fold_dd = max(s["max_drawdown_pct"] for s in stats) if stats else 0.0

            # Continuous portfolio maximum drawdown across chained test folds
            has_daily_equity = all(s.get("daily_equity") for s in stats)
            if has_daily_equity:
                continuous_equity_series: list[float] = []
                cum_scale = 1.0
                for s in stats:
                    fold_daily = s["daily_equity"]
                    init_cap = float(s.get("initial_capital", 100_000_000.0))
                    for _, eq in fold_daily:
                        continuous_equity_series.append(cum_scale * eq)
                    final_eq = float(s.get("final_equity", init_cap))
                    cum_scale *= (final_eq / init_cap) if init_cap > 0 else 1.0

                peak = continuous_equity_series[0] if continuous_equity_series else 100_000_000.0
                max_cont_dd = 0.0
                for eq_val in continuous_equity_series:
                    if eq_val > peak:
                        peak = eq_val
                    dd = (peak - eq_val) / peak if peak > 0 else 0.0
                    if dd > max_cont_dd:
                        max_cont_dd = dd
                continuous_max_dd = max_cont_dd * 100.0
            else:
                continuous_max_dd = worst_fold_dd

            entry = {
                "horizon": horizon,
                "model_id": m_id,
                "display_name": spec.display_name,
                "total_signals": total_signals,
                "completed_trades": total_trades,
                "invalidated_signals": total_invalid,
                "unfilled_signals": total_unfilled,
                "win_rate": round(win_rate, 4),
                "tp_count": tp_tot,
                "tp_rate": round(tp_tot / total_trades, 4) if total_trades > 0 else 0.0,
                "sl_count": sl_tot,
                "sl_rate": round(sl_tot / total_trades, 4) if total_trades > 0 else 0.0,
                "expiry_count": exp_tot,
                "expiry_rate": round(exp_tot / total_trades, 4) if total_trades > 0 else 0.0,
                "avg_net_return": round(avg_net_ret, 4),
                "avg_holding_days": round(avg_holding, 1),
                "pooled_profit_factor": (
                    round(pooled_pf, 2) if math.isfinite(pooled_pf) else 999.0
                ),
                "mean_profit_factor": round(mean_pf, 2) if math.isfinite(mean_pf) else 999.0,
                "worst_fold_max_drawdown_pct": round(worst_fold_dd, 2),
                "continuous_max_drawdown_pct": round(continuous_max_dd, 2),
            }
            summaries.append(entry)

        return summaries

    def export_artifacts(
        self,
        results_by_mode: dict[str, Any],
        output_dir: Union[str, Path] = "artifacts/phase_11c",
    ) -> dict[str, str]:
        """Exports JSON and CSV artifacts for Phase 11C."""
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        exported: dict[str, str] = {}

        all_clf_summaries: list[dict[str, Any]] = []
        all_reg_summaries: list[dict[str, Any]] = []
        all_trade_summaries: list[dict[str, Any]] = []
        all_trade_by_fold: list[dict[str, Any]] = []
        all_binned_diagnostics: list[dict[str, Any]] = []
        all_ev_diagnostics: list[dict[str, Any]] = []

        for mode, res in results_by_mode.items():
            # Export JSON (exclude raw oos_predictions df)
            json_dict: dict[str, Any] = {
                "mode": mode,
                "n_splits": res["n_splits"],
                "purge_days": res["purge_days"],
                "random_state": res["random_state"],
                "total_universe_samples": res["total_universe_samples"],
                "horizons": res["horizons"],
                "horizon_results": {},
            }

            for h, h_data in res["horizon_results"].items():
                # Clean daily_equity and trades objects before dumping to json
                clean_h_data = {
                    "horizon": h,
                    "fold_metadata": h_data["fold_metadata"],
                    "classification_fold_results": h_data["classification_fold_results"],
                    "classification_summaries": h_data["classification_summaries"],
                    "regression_fold_results": h_data["regression_fold_results"],
                    "regression_summaries": h_data["regression_summaries"],
                    "trading_summaries": h_data["trading_summaries"],
                    "trading_fold_stats": {
                        m: [{k: v for k, v in f.items() if k != "daily_equity"} for f in f_list]
                        for m, f_list in h_data["trading_fold_stats"].items()
                    },
                    "ev_diagnostic_results": h_data["ev_diagnostic_results"],
                }
                json_dict["horizon_results"][h] = clean_h_data

                for s in h_data["classification_summaries"]:
                    all_clf_summaries.append({"mode": mode, "horizon": h, **s})
                for s in h_data["regression_summaries"]:
                    all_reg_summaries.append({"mode": mode, "horizon": h, **s})
                for s in h_data["trading_summaries"]:
                    all_trade_summaries.append({"mode": mode, **s})
                for f_list in h_data["trading_fold_stats"].values():
                    for f_stat in f_list:
                        all_trade_by_fold.append(
                            {
                                "mode": mode,
                                **{k: v for k, v in f_stat.items() if k != "daily_equity"},
                            }
                        )
                for reg_res in h_data["regression_fold_results"]:
                    for b_diag in reg_res.get("binned_diagnostics", []):
                        all_binned_diagnostics.append(
                            {
                                "mode": mode,
                                "horizon": h,
                                "fold": reg_res["fold"],
                                "model_id": reg_res["model_id"],
                                **b_diag,
                            }
                        )
                for ev in h_data["ev_diagnostic_results"]:
                    all_ev_diagnostics.append({"mode": mode, **ev})

            json_path = out_p / f"multi_horizon_metrics_{mode}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_dict, f, indent=2)
            exported[f"json_{mode}"] = str(json_path)

            # Export OOS Predictions CSV
            oos_df: pd.DataFrame = res["oos_predictions"]
            oos_path = out_p / f"multi_horizon_oos_predictions_{mode}.csv"
            oos_df.to_csv(oos_path, index=False)
            exported[f"oos_csv_{mode}"] = str(oos_path)

        # Export aggregate CSV summaries
        clf_csv_path = out_p / "multi_horizon_classification_summary.csv"
        pd.DataFrame(all_clf_summaries).to_csv(clf_csv_path, index=False)
        exported["classification_summary_csv"] = str(clf_csv_path)

        reg_csv_path = out_p / "multi_horizon_regression_summary.csv"
        pd.DataFrame(all_reg_summaries).to_csv(reg_csv_path, index=False)
        exported["regression_summary_csv"] = str(reg_csv_path)

        trade_csv_path = out_p / "multi_horizon_trading_summary.csv"
        pd.DataFrame(all_trade_summaries).to_csv(trade_csv_path, index=False)
        exported["trading_summary_csv"] = str(trade_csv_path)

        trade_fold_csv_path = out_p / "multi_horizon_trading_by_fold.csv"
        pd.DataFrame(all_trade_by_fold).to_csv(trade_fold_csv_path, index=False)
        exported["trading_by_fold_csv"] = str(trade_fold_csv_path)

        binned_csv_path = out_p / "multi_horizon_regression_binned_diagnostics.csv"
        pd.DataFrame(all_binned_diagnostics).to_csv(binned_csv_path, index=False)
        exported["regression_binned_diagnostics_csv"] = str(binned_csv_path)

        ev_csv_path = out_p / "multi_horizon_ev_diagnostic_summary.csv"
        pd.DataFrame(all_ev_diagnostics).to_csv(ev_csv_path, index=False)
        exported["ev_diagnostic_summary_csv"] = str(ev_csv_path)

        return exported
