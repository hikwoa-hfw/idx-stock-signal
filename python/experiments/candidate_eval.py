"""Candidate Model Training and Evaluation Engine (Phase 11B.1).

Coordinates walk-forward candidate model training, predictive evaluation,
and discrete-event simulated trading across dual target definitions
(Variant A: Legacy Close-Anchor vs Variant B: Next-Session Open-Anchor)
and dual price modes (LOW_PRICE vs HIGHER_PRICE).

Production champion models and live configs remain strictly untouched.
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
    FEATURE_FAMILIES,
    compute_daily_cross_sectional_top_k_precision,
    compute_daily_top_n_precision,
    evaluate_predictions,
)
from python.models.baseline import LightGBMClassifierBaseline, LogisticRegressionBaseline
from python.models.validation import WalkForwardSplitter
from scripts.audit_target_contract_runner import evaluate_variant_b, load_all_bars

BEST_ABLATIONS: dict[str, dict[str, Any]] = {
    "LOW_PRICE": {
        "name": "lgb_minus_trend",
        "description": "LightGBM without trend features (EMA20, EMA50, EMA200, distances)",
        "excluded_group": "trend",
        "features": [f for f in ALL_FEATURE_COLUMNS if f not in FEATURE_FAMILIES["trend"]],
    },
    "HIGHER_PRICE": {
        "name": "lgb_minus_market_regime",
        "description": "LightGBM without market_regime (IHSG returns, breadth, vol)",
        "excluded_group": "market_regime",
        "features": [f for f in ALL_FEATURE_COLUMNS if f not in FEATURE_FAMILIES["market_regime"]],
    },
}


@dataclass
class CandidateModelSpec:
    model_id: str
    display_name: str
    target_variant: str  # "A" or "B"
    model_family: str  # "lightgbm", "logistic", "prevalence"
    feature_group_excluded: Optional[str]
    features: list[str]


@dataclass
class SimulatedTrade:
    ticker: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    gross_pnl: float
    net_pnl: float
    net_return: float
    exit_reason: str
    holding_days: int
    signal_prob: float


class CandidateEvaluationRunner:
    """Coordinates Phase 11B.1 candidate model training, validation, and trading simulation."""

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

    def load_universe_and_target_data(
        self,
        mode: str,
    ) -> tuple[pd.DataFrame, dict[str, list[DailyBar]]]:
        """Loads features, bars, Variant A labels, and computes Variant B outcomes.

        Filters strictly to decision bars matching the requested price mode.
        """
        bars_by_ticker = load_all_bars(self.db_path)

        # Pre-compute Variant B outcomes across all bars
        vb_map: dict[tuple[str, str], dict[str, Any]] = {}
        for ticker, t_bars in bars_by_ticker.items():
            s_bars = sorted(t_bars, key=lambda x: x.date)
            n_b = len(s_bars)
            for i in range(n_b):
                entry_b = s_bars[i]
                fwd_b = s_bars[i + 1 :]
                b_date_str = str(entry_b.date)
                vb_res = evaluate_variant_b(
                    entry_bar=entry_b,
                    forward_bars=fwd_b,
                    tp_pct=0.05,
                    sl_pct=0.02,
                    max_holding_days=10,
                    max_entry_dev_pct=0.05,
                    entry_band_pct=0.01,
                    ambiguity_policy="conservative",
                )
                vb_map[(ticker, b_date_str)] = vb_res

        # Query features and Variant A labels from SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cols_sql = ", ".join([f"f.{col}" for col in ALL_FEATURE_COLUMNS])
            query = f"""
                SELECT f.ticker, f.date, l.entry_price AS va_entry_price,
                       l.outcome AS va_outcome, l.binary_target AS va_binary_target,
                       l.realized_return AS va_realized_return,
                       l.holding_days AS va_holding_days,
                       {cols_sql}
                FROM features_daily f
                JOIN labels_daily l ON f.ticker = l.ticker AND f.date = l.date
                WHERE l.outcome != 'AMBIGUOUS' AND l.binary_target IS NOT NULL;
            """
            df_main = pd.read_sql_query(query, conn)
        finally:
            conn.close()

        if df_main.empty:
            raise ValueError(f"No feature/label rows found in database for mode {mode}")

        # Classify price mode at decision timestamp (Close t)
        df_main["mode_decision"] = df_main["va_entry_price"].apply(classify_price_mode)
        target_mode = mode.strip().upper()
        df_filtered = df_main[df_main["mode_decision"] == target_mode].copy()

        if df_filtered.empty:
            raise ValueError(f"No records matching mode {target_mode}")

        # Attach Variant B fields
        vb_status_list = []
        vb_entry_status_list = []
        vb_invalidation_list = []
        vb_entry_price_list = []
        vb_outcome_list = []
        vb_binary_target_list = []
        vb_realized_ret_list = []
        vb_holding_days_list = []
        vb_band_invalid_list = []

        for _, row in df_filtered.iterrows():
            key = (row["ticker"].strip().upper().removesuffix(".JK"), str(row["date"]))
            vb = vb_map.get(key)
            if vb is not None:
                vb_status_list.append(vb["status"])
                vb_entry_status_list.append(vb["entry_status"])
                vb_invalidation_list.append(vb["invalidation_reason"])
                vb_entry_price_list.append(vb["entry_price"])
                vb_outcome_list.append(vb["outcome"])
                vb_binary_target_list.append(vb["binary_target"])
                vb_realized_ret_list.append(vb["realized_return"])
                vb_holding_days_list.append(vb["holding_days"])
                vb_band_invalid_list.append(vb["band_invalidated"])
            else:
                vb_status_list.append("UNKNOWN")
                vb_entry_status_list.append("NONE")
                vb_invalidation_list.append("NO_DATA")
                vb_entry_price_list.append(None)
                vb_outcome_list.append("INCOMPLETE")
                vb_binary_target_list.append(None)
                vb_realized_ret_list.append(None)
                vb_holding_days_list.append(0)
                vb_band_invalid_list.append(False)

        df_filtered["vb_status"] = vb_status_list
        df_filtered["vb_entry_status"] = vb_entry_status_list
        df_filtered["vb_invalidation_reason"] = vb_invalidation_list
        df_filtered["vb_entry_price"] = vb_entry_price_list
        df_filtered["vb_outcome"] = vb_outcome_list
        df_filtered["vb_binary_target"] = vb_binary_target_list
        df_filtered["vb_realized_return"] = vb_realized_ret_list
        df_filtered["vb_holding_days"] = vb_holding_days_list
        df_filtered["vb_band_invalidated"] = vb_band_invalid_list

        df_filtered["date"] = pd.to_datetime(df_filtered["date"]).dt.date
        df_filtered = df_filtered.sort_values(by=["date", "ticker"]).reset_index(drop=True)

        return df_filtered, bars_by_ticker

    def get_candidate_specs(self, mode: str) -> list[CandidateModelSpec]:
        """Returns the controlled candidate model specifications for a given price mode."""
        ablation_cfg = BEST_ABLATIONS[mode]
        specs: list[CandidateModelSpec] = [
            # Variant A candidates (trained on Close-Anchor target)
            CandidateModelSpec(
                model_id="VA_lgb_full",
                display_name="Variant A: Full LightGBM (30 feats)",
                target_variant="A",
                model_family="lightgbm",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            CandidateModelSpec(
                model_id=f"VA_{ablation_cfg['name']}",
                display_name=f"Variant A: {ablation_cfg['description']}",
                target_variant="A",
                model_family="lightgbm",
                feature_group_excluded=ablation_cfg["excluded_group"],
                features=list(ablation_cfg["features"]),
            ),
            CandidateModelSpec(
                model_id="VA_logistic_baseline",
                display_name="Variant A: Regularized Logistic Regression (30 feats)",
                target_variant="A",
                model_family="logistic",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            CandidateModelSpec(
                model_id="VA_prevalence_baseline",
                display_name="Variant A: Prevalence Baseline (Reference)",
                target_variant="A",
                model_family="prevalence",
                feature_group_excluded=None,
                features=[],
            ),
            # Variant B candidates (trained on Next-Open Executable target)
            CandidateModelSpec(
                model_id="VB_lgb_full",
                display_name="Variant B: Full LightGBM (30 feats)",
                target_variant="B",
                model_family="lightgbm",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            CandidateModelSpec(
                model_id=f"VB_{ablation_cfg['name']}",
                display_name=f"Variant B: {ablation_cfg['description']}",
                target_variant="B",
                model_family="lightgbm",
                feature_group_excluded=ablation_cfg["excluded_group"],
                features=list(ablation_cfg["features"]),
            ),
            CandidateModelSpec(
                model_id="VB_logistic_baseline",
                display_name="Variant B: Regularized Logistic Regression (30 feats)",
                target_variant="B",
                model_family="logistic",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            CandidateModelSpec(
                model_id="VB_prevalence_baseline",
                display_name="Variant B: Prevalence Baseline (Reference)",
                target_variant="B",
                model_family="prevalence",
                feature_group_excluded=None,
                features=[],
            ),
        ]
        return specs

    def run_candidate_evaluation(
        self,
        mode: str,
        simulate_trading: bool = True,
    ) -> dict[str, Any]:
        """Executes walk-forward candidate model training, predictive & trading evaluation."""
        df, bars_by_ticker = self.load_universe_and_target_data(mode)
        dates = df["date"].to_numpy()
        specs = self.get_candidate_specs(mode)

        splitter = WalkForwardSplitter(
            n_splits=self.n_splits,
            purge_days=self.purge_days,
            expanding=True,
        )

        fold_metadata: list[dict[str, Any]] = []
        fold_results: list[dict[str, Any]] = []
        all_oos_dfs: list[pd.DataFrame] = []

        # Maps model_id -> list of simulated trades across folds
        all_model_trades: dict[str, list[SimulatedTrade]] = {s.model_id: [] for s in specs}
        all_model_trade_stats: dict[str, list[dict[str, Any]]] = {s.model_id: [] for s in specs}

        col_index_map = {col: i for i, col in enumerate(ALL_FEATURE_COLUMNS)}

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(dates), start=1):
            d_tr_min, d_tr_max = str(dates[train_idx].min()), str(dates[train_idx].max())
            d_te_min, d_te_max = str(dates[test_idx].min()), str(dates[test_idx].max())

            df_train = df.iloc[train_idx]
            df_test = df.iloc[test_idx]

            # Common cohort mask on test fold: both VA and VB valid
            common_mask_test = (df_test["vb_status"] == "VALID") & (
                df_test["va_binary_target"].notnull()
            )
            n_common_test = int(common_mask_test.sum())

            # Label flips on common cohort in test fold
            flips_test = int(
                (
                    df_test.loc[common_mask_test, "va_binary_target"]
                    != df_test.loc[common_mask_test, "vb_binary_target"]
                ).sum()
            )
            flip_pct_test = (flips_test / n_common_test * 100.0) if n_common_test > 0 else 0.0

            fold_info = {
                "fold": fold_idx,
                "train_dates": f"{d_tr_min} -> {d_tr_max}",
                "train_days": len(np.unique(dates[train_idx])),
                "train_samples_va": len(df_train),
                "train_samples_vb": int((df_train["vb_status"] == "VALID").sum()),
                "test_dates": f"{d_te_min} -> {d_te_max}",
                "test_days": len(np.unique(dates[test_idx])),
                "test_samples_va": len(df_test),
                "test_samples_vb": int((df_test["vb_status"] == "VALID").sum()),
                "test_common_cohort": n_common_test,
                "test_common_flips": flips_test,
                "test_common_flip_pct": round(flip_pct_test, 2),
                "test_vb_invalidated": int((df_test["vb_status"] == "INVALIDATED").sum()),
            }
            fold_metadata.append(fold_info)

            # Fit strictly causal median imputer on all training features
            X_all_train = df_train[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)
            X_all_test = df_test[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)

            imputer = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
            X_all_train_imp = imputer.fit_transform(X_all_train)
            X_all_test_imp = imputer.transform(X_all_test)

            # Ground truth targets
            y_va_train = df_train["va_binary_target"].to_numpy(dtype=np.int64)
            y_va_test = df_test["va_binary_target"].to_numpy(dtype=np.int64)

            # Variant B valid training mask (exclude pre-entry invalidations and unfilled)
            vb_train_valid = (df_train["vb_status"] == "VALID").to_numpy()
            y_vb_train = df_train.loc[vb_train_valid, "vb_binary_target"].to_numpy(dtype=np.int64)
            X_vb_train_imp = X_all_train_imp[vb_train_valid]

            # Variant B valid test mask
            vb_test_valid = (df_test["vb_status"] == "VALID").to_numpy()
            y_vb_test = df_test.loc[vb_test_valid, "vb_binary_target"].to_numpy(dtype=np.int64)

            test_tickers = df_test["ticker"].to_numpy()
            test_dates = df_test["date"].to_numpy()

            fold_oos_dict: dict[str, Any] = {
                "fold": [fold_idx] * len(test_idx),
                "date": [str(d) for d in test_dates],
                "ticker": list(test_tickers),
                "mode": [mode] * len(test_idx),
                "va_entry_price": list(df_test["va_entry_price"]),
                "va_binary_target": list(y_va_test),
                "vb_status": list(df_test["vb_status"]),
                "vb_binary_target": list(df_test["vb_binary_target"]),
                "is_common_cohort": list(common_mask_test.astype(int)),
            }

            fitted_models: dict[str, Any] = {}
            predictions_map: dict[str, np.ndarray] = {}

            for spec in specs:
                m_id = spec.model_id
                target_v = spec.target_variant
                m_family = spec.model_family
                feat_cols = spec.features

                # Select training data according to target variant
                if target_v == "A":
                    y_tr = y_va_train
                    X_tr_sub = (
                        X_all_train_imp[:, [col_index_map[c] for c in feat_cols]]
                        if feat_cols
                        else np.empty((len(y_tr), 0))
                    )
                else:  # Target Variant B
                    y_tr = y_vb_train
                    X_tr_sub = (
                        X_vb_train_imp[:, [col_index_map[c] for c in feat_cols]]
                        if feat_cols
                        else np.empty((len(y_tr), 0))
                    )

                # Test features for all test rows
                X_te_sub = (
                    X_all_test_imp[:, [col_index_map[c] for c in feat_cols]]
                    if feat_cols
                    else np.empty((len(test_idx), 0))
                )

                # Fit model
                if m_family == "prevalence":
                    prev_val = float(y_tr.mean()) if len(y_tr) > 0 else 0.0
                    y_prob = np.full(len(test_idx), prev_val, dtype=np.float64)
                    clf = None
                elif m_family == "logistic":
                    clf = LogisticRegressionBaseline(
                        C=1.0,
                        max_iter=1000,
                        random_state=self.random_state,
                        calibrated=False,
                    )
                    clf.fit(X_tr_sub, y_tr, feature_names=feat_cols)
                    y_prob = clf.predict_probability(X_te_sub)
                else:  # lightgbm
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

                fitted_models[m_id] = clf
                predictions_map[m_id] = y_prob
                fold_oos_dict[f"prob_{m_id}"] = [round(float(p), 6) for p in y_prob]

                # Evaluate native target performance
                if target_v == "A":
                    native_y_true = y_va_test
                    native_y_prob = y_prob
                else:
                    native_y_true = y_vb_test
                    native_y_prob = y_prob[vb_test_valid]

                native_metrics = evaluate_predictions(native_y_true, native_y_prob)

                # Daily ranking on native test set
                fold_df_native = pd.DataFrame(
                    {
                        "ticker": test_tickers[vb_test_valid] if target_v == "B" else test_tickers,
                        "date": test_dates[vb_test_valid] if target_v == "B" else test_dates,
                        "binary_target": native_y_true,
                        "y_prob": native_y_prob,
                    }
                )
                daily_top10 = compute_daily_cross_sectional_top_k_precision(
                    fold_df_native, k_pct=0.10, min_candidates=10
                )
                daily_top5 = compute_daily_top_n_precision(
                    fold_df_native, top_n=5, min_candidates=5
                )

                # Common-cohort evaluation (ground truth = y_vb on common cohort)
                common_indices = np.where(common_mask_test)[0]
                y_common_vb = df_test.iloc[common_indices]["vb_binary_target"].to_numpy(
                    dtype=np.int64
                )
                y_prob_common = y_prob[common_indices]
                common_metrics = evaluate_predictions(y_common_vb, y_prob_common)

                fold_res_entry = {
                    "fold": fold_idx,
                    "model_id": m_id,
                    "target_variant": target_v,
                    "model_family": m_family,
                    "features_used": len(feat_cols),
                    # Native test metrics
                    "native_samples": native_metrics["sample_size"],
                    "native_positives": native_metrics["positive_count"],
                    "native_prevalence": native_metrics["prevalence"],
                    "native_roc_auc": native_metrics["roc_auc"],
                    "native_pr_auc": native_metrics["pr_auc"],
                    "native_brier": native_metrics["brier_score"],
                    "native_log_loss": native_metrics["log_loss"],
                    "native_ece": native_metrics["ece"],
                    "native_accuracy": native_metrics["accuracy"],
                    "native_daily_top10_prec": daily_top10["daily_precision_macro"],
                    "native_daily_top10_std": daily_top10["daily_precision_std"],
                    "native_daily_top5_prec": daily_top5["daily_precision_macro"],
                    "native_daily_eval_dates": daily_top10["evaluated_dates"],
                    "native_daily_insufficient_dates": daily_top10["insufficient_dates"],
                    "native_candidates_per_date_median": daily_top10["candidates_per_date_median"],
                    "native_candidates_per_date_mean": daily_top10["candidates_per_date_mean"],
                    # Common-cohort metrics
                    "common_samples": common_metrics["sample_size"],
                    "common_positives": common_metrics["positive_count"],
                    "common_prevalence": common_metrics["prevalence"],
                    "common_roc_auc": common_metrics["roc_auc"],
                    "common_pr_auc": common_metrics["pr_auc"],
                    "common_brier": common_metrics["brier_score"],
                    "common_log_loss": common_metrics["log_loss"],
                    "common_ece": common_metrics["ece"],
                }
                fold_results.append(fold_res_entry)

            # Run trading simulation on test fold for all candidate models
            if simulate_trading:
                for spec in specs:
                    m_id = spec.model_id
                    t_res = self._simulate_fold_trading(
                        df_test=df_test,
                        y_prob=predictions_map[m_id],
                        bars_by_ticker=bars_by_ticker,
                        initial_capital=100_000_000.0,
                        max_positions=5,
                        top_n_per_day=5,
                        commission_buy=0.0015,
                        commission_sell=0.0025,
                        slippage_entry_bps=5.0,
                        slippage_exit_bps=5.0,
                    )
                    all_model_trades[m_id].extend(t_res["trades"])
                    t_stat = {
                        "fold": fold_idx,
                        "model_id": m_id,
                        **{k: v for k, v in t_res.items() if k != "trades"},
                    }
                    all_model_trade_stats[m_id].append(t_stat)

            oos_fold_df = pd.DataFrame(fold_oos_dict)
            all_oos_dfs.append(oos_fold_df)

        full_oos_df = pd.concat(all_oos_dfs, ignore_index=True)

        # Aggregate macro metrics across folds
        macro_summaries = self._compute_macro_summaries(fold_results, specs)

        # Aggregate trading statistics across folds
        trading_summaries = self._aggregate_trading_summaries(
            all_model_trade_stats=all_model_trade_stats,
            specs=specs,
            all_model_trades=all_model_trades,
        )

        return {
            "mode": mode,
            "n_splits": self.n_splits,
            "purge_days": self.purge_days,
            "random_state": self.random_state,
            "total_universe_samples": len(df),
            "fold_metadata": fold_metadata,
            "fold_results": fold_results,
            "macro_summaries": macro_summaries,
            "trading_summaries": trading_summaries,
            "trading_fold_stats": all_model_trade_stats,
            "oos_predictions": full_oos_df,
        }

    def _simulate_fold_trading(
        self,
        df_test: pd.DataFrame,
        y_prob: np.ndarray,
        bars_by_ticker: dict[str, list[DailyBar]],
        initial_capital: float = 100_000_000.0,
        max_positions: int = 5,
        top_n_per_day: int = 5,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
        slippage_bps: Optional[float] = None,
    ) -> dict[str, Any]:
        """Simulates discrete-event trading with realistic Next-Open execution and gap protection.

        Friction Contract:
        - Buy commission: 15 bps (0.0015)
        - Sell commission: 25 bps (0.0025)
        - Entry slippage: 5 bps (0.0005)
        - Exit slippage: 5 bps (0.0005)
        - Total nominal round-trip friction: 50 bps (0.0050)
        - Lot size: 100 shares
        - Equal weight allocation (cap 20% equity per position)
        """
        if slippage_bps is not None:
            # Backward-compatibility: split total round-trip slippage equally
            slippage_entry_bps = float(slippage_bps) / 2.0
            slippage_exit_bps = float(slippage_bps) / 2.0

        # Map test bars with predictions
        eval_df = df_test[["ticker", "date", "va_entry_price"]].copy()
        eval_df["y_prob"] = y_prob

        # Group by decision date
        dates_sorted = sorted(eval_df["date"].unique())

        cash = float(initial_capital)
        peak_equity = float(initial_capital)
        total_eq = float(initial_capital)
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        daily_equity: list[tuple[date, float]] = []

        # Active position: ticker -> dict
        open_positions: dict[str, dict[str, Any]] = {}
        completed_trades: list[SimulatedTrade] = []

        total_signals_generated = 0
        invalidated_gap_down = 0
        invalidated_gap_up = 0
        invalidated_excessive_dev = 0
        unfilled_suspended = 0
        unfilled_capacity = 0
        unfilled_cash = 0

        # Quick lookup for bars by (ticker, date)
        bar_lookup: dict[tuple[str, date], DailyBar] = {}
        for t, b_list in bars_by_ticker.items():
            for b in b_list:
                bar_lookup[(t, b.date)] = b

        # Chronological day-by-day simulation
        # Pending orders generated on Day d execute on Day d+1 morning
        pending_orders: list[dict[str, Any]] = []

        for curr_d in dates_sorted:
            # 1. Execute pending orders from previous trading date
            if pending_orders:
                # Sort pending orders by probability descending, ticker ascending
                pending_orders.sort(key=lambda o: (-o["prob"], o["ticker"]))

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
                    open_val = sum(
                        pos["shares"]
                        * (
                            bar_lookup[(pos["ticker"], curr_d)].close
                            if (pos["ticker"], curr_d) in bar_lookup
                            and bar_lookup[(pos["ticker"], curr_d)].close > 0
                            else pos["entry_price"]
                        )
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
                        "signal_prob": ord_info["prob"],
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
                elif pos["holding_days"] >= 10:
                    exit_reason = "EXPIRY"
                    exit_raw = float(bar_curr.close)

                if exit_reason is not None and exit_raw is not None:
                    exit_fill = exit_raw * (1.0 - slippage_exit_bps / 10000.0)
                    gross_proceeds = pos["shares"] * exit_fill
                    exit_fee = gross_proceeds * commission_sell
                    net_proceeds = gross_proceeds - exit_fee
                    cash += net_proceeds

                    net_pnl = net_proceeds - (pos["shares"] * pos["entry_price"] + pos["entry_fee"])
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
                        signal_prob=pos["signal_prob"],
                    )
                    completed_trades.append(trade)
                    del open_positions[t]
                else:
                    pos["holding_days"] += 1

            # 3. Mark to market equity & drawdown calculation
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
                # Rank candidates by probability descending, ticker ascending
                sorted_cands = day_candidates.sort_values(
                    by=["y_prob", "ticker"], ascending=[False, True], kind="stable"
                )
                top_picks = sorted_cands.iloc[:top_n_per_day]
                for _, r in top_picks.iterrows():
                    total_signals_generated += 1
                    pending_orders.append(
                        {
                            "ticker": r["ticker"],
                            "signal_date": curr_d,
                            "close_t": float(r["va_entry_price"]),
                            "prob": float(r["y_prob"]),
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

        total_invalidated = invalidated_gap_down + invalidated_gap_up + invalidated_excessive_dev
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

    def _compute_macro_summaries(
        self,
        fold_results: list[dict[str, Any]],
        specs: list[CandidateModelSpec],
    ) -> list[dict[str, Any]]:
        """Computes macro fold-aggregated predictive metrics across walk-forward splits."""
        summaries: list[dict[str, Any]] = []
        df_folds = pd.DataFrame(fold_results)

        for spec in specs:
            m_id = spec.model_id
            m_df = df_folds[df_folds["model_id"] == m_id]
            if m_df.empty:
                continue

            roc_mean = float(m_df["native_roc_auc"].mean())
            roc_std = float(m_df["native_roc_auc"].std(ddof=1)) if len(m_df) > 1 else 0.0
            pr_mean = float(m_df["native_pr_auc"].mean())
            pr_std = float(m_df["native_pr_auc"].std(ddof=1)) if len(m_df) > 1 else 0.0
            brier_mean = float(m_df["native_brier"].mean())
            log_loss_mean = float(m_df["native_log_loss"].mean())
            ece_mean = float(m_df["native_ece"].mean())
            daily_top10_mean = float(m_df["native_daily_top10_prec"].mean())
            daily_top10_std = (
                float(m_df["native_daily_top10_prec"].std(ddof=1)) if len(m_df) > 1 else 0.0
            )
            daily_top5_mean = float(m_df["native_daily_top5_prec"].mean())

            # Common cohort macro
            c_roc_mean = float(m_df["common_roc_auc"].mean())
            c_pr_mean = float(m_df["common_pr_auc"].mean())
            c_brier_mean = float(m_df["common_brier"].mean())
            c_log_loss_mean = float(m_df["common_log_loss"].mean())

            summary = {
                "model_id": m_id,
                "display_name": spec.display_name,
                "target_variant": spec.target_variant,
                "model_family": spec.model_family,
                "features_used": len(spec.features),
                "excluded_group": spec.feature_group_excluded,
                # Native macro metrics
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
                # Common cohort macro metrics
                "common_roc_auc_mean": round(c_roc_mean, 4),
                "common_pr_auc_mean": round(c_pr_mean, 4),
                "common_brier_mean": round(c_brier_mean, 4),
                "common_log_loss_mean": round(c_log_loss_mean, 4),
            }
            summaries.append(summary)

        return summaries

    def _aggregate_trading_summaries(
        self,
        all_model_trade_stats: dict[str, list[dict[str, Any]]],
        specs: list[CandidateModelSpec],
        all_model_trades: Optional[dict[str, list[SimulatedTrade]]] = None,
    ) -> list[dict[str, Any]]:
        """Aggregates simulated trading results across folds with explicit metric definitions."""
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

            # Worst-fold maximum drawdown (highest peak-to-trough drop within any single fold)
            worst_fold_dd = max(s["max_drawdown_pct"] for s in stats) if stats else 0.0

            # Continuous portfolio maximum drawdown across chained walk-forward test folds
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
                "model_id": m_id,
                "display_name": spec.display_name,
                "target_variant": spec.target_variant,
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
                "pooled_profit_factor": round(pooled_pf, 2) if math.isfinite(pooled_pf) else 999.0,
                "mean_profit_factor": round(mean_pf, 2),
                "worst_fold_max_drawdown_pct": round(worst_fold_dd, 2),
                "continuous_max_drawdown_pct": round(continuous_max_dd, 2),
                # Backward-compatibility alias
                "max_drawdown_pct": round(worst_fold_dd, 2),
            }
            summaries.append(entry)

        return summaries

    def export_artifacts(
        self,
        results_by_mode: dict[str, dict[str, Any]],
        output_dir: Union[str, Path] = "artifacts/candidate_eval",
    ) -> dict[str, str]:
        """Saves machine-readable JSON and CSV artifacts into output directory."""
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        exported_files: dict[str, str] = {}

        all_macro_rows: list[dict[str, Any]] = []
        all_fold_rows: list[dict[str, Any]] = []
        all_trading_rows: list[dict[str, Any]] = []

        for mode, data in results_by_mode.items():
            # Mode-specific JSON
            mode_json_path = out_p / f"candidate_results_{mode}.json"
            clean_mode_dict = {
                k: v for k, v in data.items() if k not in ("oos_predictions", "trading_fold_stats")
            }
            with open(mode_json_path, "w", encoding="utf-8") as f:
                json.dump(clean_mode_dict, f, indent=2, default=str)
            exported_files[f"{mode}_json"] = str(mode_json_path)

            # Macro summary CSV
            mode_macro_df = pd.DataFrame(data["macro_summaries"])
            mode_macro_df["mode"] = mode
            mode_macro_csv_path = out_p / f"candidate_results_{mode}.csv"
            mode_macro_df.to_csv(mode_macro_csv_path, index=False)
            exported_files[f"{mode}_macro_csv"] = str(mode_macro_csv_path)
            all_macro_rows.extend(mode_macro_df.to_dict(orient="records"))

            # Fold details CSV
            mode_fold_df = pd.DataFrame(data["fold_results"])
            mode_fold_df["mode"] = mode
            mode_fold_csv_path = out_p / f"candidate_fold_details_{mode}.csv"
            mode_fold_df.to_csv(mode_fold_csv_path, index=False)
            exported_files[f"{mode}_fold_csv"] = str(mode_fold_csv_path)
            all_fold_rows.extend(mode_fold_df.to_dict(orient="records"))

            # Trading summary CSV & JSON
            mode_trading_df = pd.DataFrame(data["trading_summaries"])
            mode_trading_df["mode"] = mode
            mode_trading_csv_path = out_p / f"candidate_trading_results_{mode}.csv"
            mode_trading_df.to_csv(mode_trading_csv_path, index=False)
            exported_files[f"{mode}_trading_csv"] = str(mode_trading_csv_path)

            mode_trading_json_path = out_p / f"candidate_trading_results_{mode}.json"
            with open(mode_trading_json_path, "w", encoding="utf-8") as f:
                json.dump(data["trading_summaries"], f, indent=2, default=str)
            exported_files[f"{mode}_trading_json"] = str(mode_trading_json_path)

            all_trading_rows.extend(mode_trading_df.to_dict(orient="records"))

            # Out of sample predictions CSV
            oos_df = data["oos_predictions"]
            oos_path = out_p / f"candidate_oos_predictions_{mode}.csv"
            oos_df.to_csv(oos_path, index=False)
            exported_files[f"{mode}_oos_csv"] = str(oos_path)

        # Aggregate combined tables
        agg_macro_df = pd.DataFrame(all_macro_rows)
        agg_macro_csv = out_p / "candidate_summary_aggregate.csv"
        agg_macro_df.to_csv(agg_macro_csv, index=False)
        exported_files["agg_macro_csv"] = str(agg_macro_csv)

        agg_macro_json = out_p / "candidate_summary_aggregate.json"
        with open(agg_macro_json, "w", encoding="utf-8") as f:
            json.dump(all_macro_rows, f, indent=2, default=str)
        exported_files["agg_macro_json"] = str(agg_macro_json)

        agg_trading_df = pd.DataFrame(all_trading_rows)
        agg_trading_csv = out_p / "candidate_trading_aggregate.csv"
        agg_trading_df.to_csv(agg_trading_csv, index=False)
        exported_files["agg_trading_csv"] = str(agg_trading_csv)

        agg_trading_json = out_p / "candidate_trading_aggregate.json"
        with open(agg_trading_json, "w", encoding="utf-8") as f:
            json.dump(all_trading_rows, f, indent=2, default=str)
        exported_files["agg_trading_json"] = str(agg_trading_json)

        return exported_files

    def recompute_trading_from_saved_predictions(
        self,
        mode: str,
        artifacts_dir: Union[str, Path] = "artifacts/candidate_eval",
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
    ) -> dict[str, Any]:
        """Recomputes discrete-event trading evaluation from saved predictions without retraining.

        Enforces 50 bps round-trip nominal friction:
        - 15 bps buy commission
        - 25 bps sell commission
        - 5 bps entry slippage + 5 bps exit slippage (10 bps round-trip slippage)
        """
        out_p = Path(artifacts_dir)
        oos_file = out_p / f"candidate_oos_predictions_{mode}.csv"
        if not oos_file.exists():
            raise FileNotFoundError(f"Saved OOS predictions file not found: {oos_file}")

        df_universe, bars_by_ticker = self.load_universe_and_target_data(mode)
        oos_df = pd.read_csv(oos_file)
        oos_df["date"] = pd.to_datetime(oos_df["date"]).dt.date

        if "va_entry_price" not in oos_df.columns:
            lookup_df = df_universe[["ticker", "date", "va_entry_price"]].drop_duplicates(
                subset=["ticker", "date"]
            )
            oos_df = oos_df.merge(lookup_df, on=["ticker", "date"], how="left")

        specs = self.get_candidate_specs(mode)
        folds = sorted(oos_df["fold"].unique())

        all_model_trades: dict[str, list[SimulatedTrade]] = {s.model_id: [] for s in specs}
        all_model_trade_stats: dict[str, list[dict[str, Any]]] = {s.model_id: [] for s in specs}

        for fold_idx in folds:
            fold_df = oos_df[oos_df["fold"] == fold_idx].copy()
            for spec in specs:
                m_id = spec.model_id
                prob_col = f"prob_{m_id}"
                if prob_col not in fold_df.columns:
                    raise KeyError(f"Column {prob_col} not found in {oos_file}")

                y_prob = fold_df[prob_col].to_numpy(dtype=np.float64)
                t_res = self._simulate_fold_trading(
                    df_test=fold_df,
                    y_prob=y_prob,
                    bars_by_ticker=bars_by_ticker,
                    initial_capital=100_000_000.0,
                    max_positions=5,
                    top_n_per_day=5,
                    commission_buy=commission_buy,
                    commission_sell=commission_sell,
                    slippage_entry_bps=slippage_entry_bps,
                    slippage_exit_bps=slippage_exit_bps,
                )
                all_model_trades[m_id].extend(t_res["trades"])
                t_stat = {
                    "fold": int(fold_idx),
                    "model_id": m_id,
                    **{k: v for k, v in t_res.items() if k != "trades"},
                }
                all_model_trade_stats[m_id].append(t_stat)

        trading_summaries = self._aggregate_trading_summaries(
            all_model_trade_stats=all_model_trade_stats,
            specs=specs,
            all_model_trades=all_model_trades,
        )

        # Load existing JSON artifact to preserve predictive metrics (macro_summaries, etc.)
        json_path = out_p / f"candidate_results_{mode}.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                base_data = json.load(f)
        else:
            base_data = {
                "mode": mode,
                "n_splits": self.n_splits,
                "purge_days": self.purge_days,
                "random_state": self.random_state,
                "total_universe_samples": len(df_universe),
                "macro_summaries": [],
                "fold_results": [],
            }

        base_data["trading_summaries"] = trading_summaries
        base_data["trading_fold_stats"] = all_model_trade_stats
        base_data["oos_predictions"] = oos_df

        return base_data
