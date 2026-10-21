"""Offline Challenger Retraining and Controlled Evaluation Engine.

Evaluates research-only challenger classifiers using fully matured historical data
under Variant B H=15 target contract and expanding walk-forward validation.
Production champions and Phase 11F paper trading systems remain strictly untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from python.common.types import DailyBar
from python.config.settings import settings
from python.experiments.ablation import (
    ALL_FEATURE_COLUMNS,
    compute_daily_cross_sectional_top_k_precision,
    compute_daily_top_n_precision,
    evaluate_predictions,
)
from python.experiments.candidate_eval import BEST_ABLATIONS, SimulatedTrade
from python.experiments.multi_horizon_eval import MultiHorizonEvaluationRunner
from python.models.baseline import (
    LightGBMClassifierBaseline,
    LogisticRegressionBaseline,
)
from python.models.registry import ModelRegistry
from python.models.validation import WalkForwardSplitter

logger = logging.getLogger("challenger_retraining")


def compute_file_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ChallengerModelSpec:
    model_id: str
    display_name: str
    model_family: str  # "lightgbm", "logistic", "prevalence", "champion"
    feature_group_excluded: Optional[str]
    features: list[str]


class ChallengerRetrainingRunner:
    """Coordinates walk-forward evaluation and artifact training for offline challengers."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        n_splits: int = 3,
        purge_days: int = 15,
        random_state: int = 42,
        cutoff_date: str = "2026-09-25",
        run_id: Optional[str] = None,
        artifacts_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.db_path = db_path or self._resolve_db_path()
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.random_state = random_state
        self.cutoff_date = cutoff_date
        self.d_cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d").date()
        self.run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        repo_root = Path(__file__).resolve().parent.parent.parent
        if artifacts_dir:
            self.artifacts_dir = Path(artifacts_dir)
        else:
            self.artifacts_dir = repo_root / "artifacts" / "offline_challengers" / self.run_id

    def _resolve_db_path(self) -> str:
        url = settings.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        if url.startswith("sqlite://"):
            return url[len("sqlite://") :]
        return "datasets/stock_signals.db"

    def load_matured_data(
        self,
        mode: str,
    ) -> tuple[pd.DataFrame, dict[str, list[DailyBar]]]:
        """Loads features and bars with fully matured 15-day outcomes."""
        eval_runner = MultiHorizonEvaluationRunner(
            db_path=self.db_path,
            purge_days=self.purge_days,
            random_state=self.random_state,
        )
        df_all, bars = eval_runner.load_multi_horizon_data(mode=mode, horizons=[15])

        # Filter strictly on or before cutoff date for complete 15-session observation
        mask = df_all["date"] <= self.d_cutoff
        df_matured = df_all[mask].copy().reset_index(drop=True)
        return df_matured, bars

    def get_candidate_specs(self, mode: str) -> list[ChallengerModelSpec]:
        """Returns candidate specs: Full, Ablation, Logistic, Prevalence, Champion."""
        ablation_cfg = BEST_ABLATIONS[mode]
        abl_grp = ablation_cfg["excluded_group"]
        return [
            # Candidate A: Full LightGBM Classifier
            ChallengerModelSpec(
                model_id="lgb_full",
                display_name="Candidate A — Full-Feature LightGBM (30 feats)",
                model_family="lightgbm",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            # Candidate B: Feature-Ablation LightGBM
            ChallengerModelSpec(
                model_id=ablation_cfg["name"],
                display_name=f"Candidate B — Ablation LightGBM (minus {abl_grp})",
                model_family="lightgbm",
                feature_group_excluded=ablation_cfg["excluded_group"],
                features=list(ablation_cfg["features"]),
            ),
            # Candidate C: Regularized Logistic Regression
            ChallengerModelSpec(
                model_id="logistic_baseline",
                display_name="Candidate C — Regularized Logistic Regression",
                model_family="logistic",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
            # Reference Baseline 1: Constant Training-Prevalence Baseline
            ChallengerModelSpec(
                model_id="prevalence_baseline",
                display_name="Reference Baseline — Constant Prevalence",
                model_family="prevalence",
                feature_group_excluded=None,
                features=[],
            ),
            # Reference Baseline 2: Existing Production Champion
            ChallengerModelSpec(
                model_id="production_champion",
                display_name="Reference Baseline — Existing Production Champion",
                model_family="champion",
                feature_group_excluded=None,
                features=list(ALL_FEATURE_COLUMNS),
            ),
        ]

    def run_walk_forward_evaluation(
        self,
        mode: str,
        simulate_trading: bool = True,
    ) -> dict[str, Any]:
        """Executes chronological expanding walk-forward evaluation across all candidates."""
        df, bars_by_ticker = self.load_matured_data(mode)
        dates = df["date"].to_numpy()
        specs = self.get_candidate_specs(mode)

        # Load production champion
        reg = ModelRegistry()
        champ_res = reg.get_champion(mode=mode)
        champ_model = champ_res[0] if champ_res else None
        champ_meta = champ_res[1] if champ_res else None

        splitter = WalkForwardSplitter(
            n_splits=self.n_splits,
            purge_days=self.purge_days,
            expanding=True,
        )

        col_index_map = {col: i for i, col in enumerate(ALL_FEATURE_COLUMNS)}

        fold_clf_results: list[dict[str, Any]] = []
        fold_trading_stats: dict[str, list[dict[str, Any]]] = {s.model_id: [] for s in specs}
        fold_trades: dict[str, list[SimulatedTrade]] = {s.model_id: [] for s in specs}
        fold_metadata: list[dict[str, Any]] = []
        all_oos_records: list[pd.DataFrame] = []

        status_col = "vb_status_15"
        bin_target_col = "vb_binary_target_15"
        net_ret_col = "vb_realized_net_15"
        outcome_col = "vb_outcome_15"

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(dates), start=1):
            d_tr_min, d_tr_max = str(dates[train_idx].min()), str(dates[train_idx].max())
            d_te_min, d_te_max = str(dates[test_idx].min()), str(dates[test_idx].max())

            df_train = df.iloc[train_idx]
            df_test = df.iloc[test_idx]

            tr_valid_mask = (df_train[status_col] == "VALID").to_numpy()
            te_valid_mask = (df_test[status_col] == "VALID").to_numpy()

            n_tr_valid = int(tr_valid_mask.sum())
            n_te_valid = int(te_valid_mask.sum())

            # Median imputer fit strictly on training fold features
            X_all_train = df_train[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)
            X_all_test = df_test[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)

            imputer = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
            X_all_train_imp = imputer.fit_transform(X_all_train)
            X_all_test_imp = imputer.transform(X_all_test)

            X_tr_imp_valid = X_all_train_imp[tr_valid_mask]
            y_tr_bin = (
                df_train.loc[tr_valid_mask, bin_target_col].to_numpy(dtype=np.int64)
                if n_tr_valid > 0
                else np.empty(0, dtype=np.int64)
            )
            y_te_bin = (
                df_test.loc[te_valid_mask, bin_target_col].to_numpy(dtype=np.int64)
                if n_te_valid > 0
                else np.empty(0, dtype=np.int64)
            )

            fold_meta = {
                "mode": mode,
                "fold": fold_idx,
                "train_dates": f"{d_tr_min} -> {d_tr_max}",
                "train_days": len(np.unique(dates[train_idx])),
                "train_samples_total": len(df_train),
                "train_samples_valid": n_tr_valid,
                "train_positives": int(y_tr_bin.sum()),
                "train_prevalence": round(float(y_tr_bin.mean()), 4) if n_tr_valid > 0 else 0.0,
                "test_dates": f"{d_te_min} -> {d_te_max}",
                "test_days": len(np.unique(dates[test_idx])),
                "test_samples_total": len(df_test),
                "test_samples_valid": n_te_valid,
                "test_positives": int(y_te_bin.sum()),
                "test_prevalence": round(float(y_te_bin.mean()), 4) if n_te_valid > 0 else 0.0,
                "test_invalidated": int((df_test[status_col] == "INVALIDATED").sum()),
                "test_incomplete": int((df_test[status_col] == "INCOMPLETE").sum()),
            }
            fold_metadata.append(fold_meta)

            predictions_map: dict[str, np.ndarray] = {}

            for spec in specs:
                m_id = spec.model_id
                feat_cols = spec.features
                m_fam = spec.model_family

                if feat_cols:
                    feat_indices = [col_index_map[c] for c in feat_cols]
                    X_tr = X_tr_imp_valid[:, feat_indices]
                    X_te_full = X_all_test_imp[:, feat_indices]
                else:
                    X_tr = np.empty((n_tr_valid, 0))
                    X_te_full = np.empty((len(test_idx), 0))

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
                elif m_fam == "champion":
                    if champ_model is not None:
                        y_prob_full = champ_model.predict_probability(X_te_full)
                        y_prob_valid = y_prob_full[te_valid_mask]
                    else:
                        y_prob_full = np.zeros(len(test_idx), dtype=np.float64)
                        y_prob_valid = np.zeros(n_te_valid, dtype=np.float64)
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

                # Predictive metrics on valid test samples
                clf_metrics = evaluate_predictions(y_te_bin, y_prob_valid, n_bins=10)

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
                daily_top5 = compute_daily_cross_sectional_top_k_precision(
                    fold_df_native, k_pct=0.05, min_candidates=10
                )
                daily_top5_fixed = compute_daily_top_n_precision(
                    fold_df_native, top_n=5, min_candidates=5
                )

                fold_clf_results.append(
                    {
                        "mode": mode,
                        "fold": fold_idx,
                        "model_id": m_id,
                        "display_name": spec.display_name,
                        "features_count": len(feat_cols),
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
                        "daily_top5_std": daily_top5["daily_precision_std"],
                        "daily_top5_fixed": daily_top5_fixed["daily_precision_macro"],
                        "daily_eval_dates": daily_top10["evaluated_dates"],
                    }
                )

            # Simulated trading for this fold
            if simulate_trading:
                for spec in specs:
                    m_id = spec.model_id
                    t_res = self._simulate_trading(
                        df_test=df_test,
                        predictions=predictions_map[m_id],
                        bars_by_ticker=bars_by_ticker,
                        max_holding_days=15,
                    )
                    fold_trades[m_id].extend(t_res["trades"])
                    t_stat = {
                        "mode": mode,
                        "fold": fold_idx,
                        "model_id": m_id,
                        **{k: v for k, v in t_res.items() if k != "trades"},
                    }
                    fold_trading_stats[m_id].append(t_stat)

            # Store OOS predictions
            oos_data = {
                "fold": [fold_idx] * len(test_idx),
                "date": [str(d) for d in df_test["date"]],
                "ticker": list(df_test["ticker"]),
                "mode": [mode] * len(test_idx),
                "decision_price": list(df_test["va_entry_price"]),
                "vb_status": list(df_test[status_col]),
                "vb_binary_target": list(df_test[bin_target_col]),
                "vb_realized_net": list(df_test[net_ret_col]),
                "vb_outcome": list(df_test[outcome_col]),
            }
            for spec in specs:
                oos_data[f"prob_{spec.model_id}"] = list(predictions_map[spec.model_id])

            all_oos_records.append(pd.DataFrame(oos_data))

        # Summaries across folds
        clf_summaries = self._compute_macro_classification_summaries(fold_clf_results, specs)
        trade_summaries = (
            self._aggregate_trading_summaries(fold_trading_stats, specs, fold_trades)
            if simulate_trading
            else []
        )
        full_oos_df = pd.concat(all_oos_records, ignore_index=True)

        return {
            "mode": mode,
            "cutoff_date": self.cutoff_date,
            "n_splits": self.n_splits,
            "purge_days": self.purge_days,
            "random_state": self.random_state,
            "total_samples": len(df),
            "champion_version": champ_meta.model_version if champ_meta else "NONE",
            "fold_metadata": fold_metadata,
            "classification_fold_results": fold_clf_results,
            "classification_summaries": clf_summaries,
            "trading_fold_stats": fold_trading_stats,
            "trading_summaries": trade_summaries,
            "oos_predictions": full_oos_df,
        }

    def _simulate_trading(
        self,
        df_test: pd.DataFrame,
        predictions: np.ndarray,
        bars_by_ticker: dict[str, list[DailyBar]],
        max_holding_days: int = 15,
        initial_capital: float = 100_000_000.0,
        max_positions: int = 5,
        top_n_per_day: int = 5,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
    ) -> dict[str, Any]:
        """Simulates discrete-event execution matching Variant B H=15 trading contract."""
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
            # 1. Fill pending orders from previous session
            if pending_orders:
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

                    # Pre-entry gap and excessive deviation checks
                    if b_open <= c_close * 0.98:
                        invalidated_gap_down += 1
                        continue
                    if b_open >= c_close * 1.05:
                        invalidated_gap_up += 1
                        continue
                    if abs(b_open - c_close) / c_close > 0.05:
                        invalidated_excessive_dev += 1
                        continue

                    # Position sizing: max 20% equity cap, 100-share lots
                    open_val = sum(
                        pos["shares"] * last_known_close.get(pos["ticker"], pos["entry_price"])
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

            # 2. Intraday barrier monitoring for open positions
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
                    # Conservative: SL takes precedence
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
            "avg_net_return": round(avg_net_ret, 5),
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
        specs: list[ChallengerModelSpec],
    ) -> list[dict[str, Any]]:
        """Aggregates macro mean, std, min, max across walk-forward folds."""
        summaries: list[dict[str, Any]] = []
        df_folds = pd.DataFrame(fold_results)

        for spec in specs:
            m_id = spec.model_id
            m_df = df_folds[df_folds["model_id"] == m_id]
            if m_df.empty:
                continue

            summaries.append(
                {
                    "model_id": m_id,
                    "display_name": spec.display_name,
                    "features_count": len(spec.features),
                    "roc_auc_mean": round(float(m_df["roc_auc"].mean()), 4),
                    "roc_auc_std": round(float(m_df["roc_auc"].std(ddof=1)), 4)
                    if len(m_df) > 1
                    else 0.0,
                    "roc_auc_min": round(float(m_df["roc_auc"].min()), 4),
                    "roc_auc_max": round(float(m_df["roc_auc"].max()), 4),
                    "pr_auc_mean": round(float(m_df["pr_auc"].mean()), 4),
                    "pr_auc_std": round(float(m_df["pr_auc"].std(ddof=1)), 4)
                    if len(m_df) > 1
                    else 0.0,
                    "pr_auc_min": round(float(m_df["pr_auc"].min()), 4),
                    "pr_auc_max": round(float(m_df["pr_auc"].max()), 4),
                    "brier_score_mean": round(float(m_df["brier_score"].mean()), 4),
                    "log_loss_mean": round(float(m_df["log_loss"].mean()), 4),
                    "ece_mean": round(float(m_df["ece"].mean()), 4),
                    "daily_top10_prec_mean": round(float(m_df["daily_top10_prec"].mean()), 4),
                    "daily_top10_prec_std": round(float(m_df["daily_top10_prec"].std(ddof=1)), 4)
                    if len(m_df) > 1
                    else 0.0,
                    "daily_top5_prec_mean": round(float(m_df["daily_top5_prec"].mean()), 4),
                    "daily_top5_prec_std": round(float(m_df["daily_top5_prec"].std(ddof=1)), 4)
                    if len(m_df) > 1
                    else 0.0,
                    "daily_top5_fixed_mean": round(float(m_df["daily_top5_fixed"].mean()), 4),
                }
            )
        return summaries

    def _aggregate_trading_summaries(
        self,
        all_model_trade_stats: dict[str, list[dict[str, Any]]],
        specs: list[ChallengerModelSpec],
        all_model_trades: Optional[dict[str, list[SimulatedTrade]]] = None,
    ) -> list[dict[str, Any]]:
        """Aggregates trading metrics across folds including continuous drawdown and pooled PF."""
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

            # Pooled profit factor
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
                pf_vals = [s["profit_factor"] for s in stats if math.isfinite(s["profit_factor"])]
                pooled_pf = float(np.mean(pf_vals)) if pf_vals else 0.0

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

            summaries.append(
                {
                    "model_id": m_id,
                    "display_name": spec.display_name,
                    "completed_trades": total_trades,
                    "win_rate": round(win_rate, 4),
                    "tp_count": tp_tot,
                    "tp_rate": round(tp_tot / total_trades, 4) if total_trades > 0 else 0.0,
                    "sl_count": sl_tot,
                    "sl_rate": round(sl_tot / total_trades, 4) if total_trades > 0 else 0.0,
                    "expiry_count": exp_tot,
                    "expiry_rate": round(exp_tot / total_trades, 4) if total_trades > 0 else 0.0,
                    "avg_net_return": round(avg_net_ret, 5),
                    "pooled_profit_factor": (
                        round(pooled_pf, 2) if math.isfinite(pooled_pf) else 999.0
                    ),
                    "continuous_max_drawdown_pct": round(continuous_max_dd, 2),
                    "worst_fold_max_drawdown_pct": round(worst_fold_dd, 2),
                    "avg_holding_days": round(avg_holding, 1),
                    "total_signals": total_signals,
                    "total_invalidated": total_invalid,
                    "total_unfilled": total_unfilled,
                }
            )

        return summaries

    def fit_and_serialize_challengers(
        self,
        mode: str,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Fits candidate models up to cutoff date and serializes artifacts."""
        out_dir = self.artifacts_dir / mode.lower()
        out_dir.mkdir(parents=True, exist_ok=True)

        status_col = "vb_status_15"
        bin_target_col = "vb_binary_target_15"

        mask_valid = (df[status_col] == "VALID") & (df["date"] <= self.d_cutoff)
        df_valid = df[mask_valid].copy()

        n_total = len(df[df["date"] <= self.d_cutoff])
        n_valid = len(df_valid)
        y_valid = df_valid[bin_target_col].to_numpy(dtype=np.int64)
        pos_count = int(np.sum(y_valid))
        prevalence = float(pos_count / n_valid) if n_valid > 0 else 0.0

        # Causal imputer fit on full historical training slice up to cutoff
        imputer = SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)
        X_all_raw = df[df["date"] <= self.d_cutoff][ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64)
        imputer.fit(X_all_raw)

        X_valid_imp = imputer.transform(df_valid[ALL_FEATURE_COLUMNS].to_numpy(dtype=np.float64))
        col_index_map = {col: i for i, col in enumerate(ALL_FEATURE_COLUMNS)}

        specs = [
            s for s in self.get_candidate_specs(mode) if s.model_family in ("lightgbm", "logistic")
        ]

        mode_metadata: dict[str, Any] = {
            "mode": mode,
            "training_start_date": str(df["date"].min()),
            "training_cutoff_date": self.cutoff_date,
            "label_maturity_cutoff": "2026-10-16",
            "samples_total": n_total,
            "samples_valid": n_valid,
            "positives": pos_count,
            "prevalence": round(prevalence, 4),
            "random_state": self.random_state,
            "models": {},
        }

        for spec in specs:
            m_id = spec.model_id
            feat_cols = spec.features
            feat_indices = [col_index_map[c] for c in feat_cols]
            X_sub = X_valid_imp[:, feat_indices]

            if spec.model_family == "logistic":
                clf = LogisticRegressionBaseline(
                    C=1.0,
                    max_iter=1000,
                    random_state=self.random_state,
                    calibrated=False,
                )
                clf.fit(X_sub, y_valid, feature_names=feat_cols)
            else:
                clf = LightGBMClassifierBaseline(
                    n_estimators=100,
                    learning_rate=0.05,
                    max_depth=5,
                    num_leaves=31,
                    min_child_samples=20,
                    random_state=self.random_state,
                    calibrated=False,
                )
                clf.fit(X_sub, y_valid, feature_names=feat_cols)

            # Serialize model artifact bundle
            bundle = {
                "model_id": m_id,
                "display_name": spec.display_name,
                "mode": mode,
                "features": feat_cols,
                "excluded_family": spec.feature_group_excluded,
                "imputer": imputer,
                "estimator": clf,
                "cutoff_date": self.cutoff_date,
                "fitted_at": datetime.now(timezone.utc).isoformat(),
            }

            model_filename = f"{mode.lower()}_{m_id}.joblib"
            artifact_path = out_dir / model_filename
            joblib.dump(bundle, artifact_path)
            sha256_hash = compute_file_sha256(artifact_path)

            rel_path = artifact_path.relative_to(self.artifacts_dir.parent.parent.parent).as_posix()
            mode_metadata["models"][m_id] = {
                "model_id": m_id,
                "display_name": spec.display_name,
                "artifact_path": rel_path,
                "sha256": sha256_hash,
                "feature_count": len(feat_cols),
                "features": feat_cols,
                "excluded_family": spec.feature_group_excluded,
            }

        return mode_metadata

    def run_full_pipeline(self) -> dict[str, Any]:
        """Executes walk-forward evaluation, simulated trading, and model serialization."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        modes = ["LOW_PRICE", "HIGHER_PRICE"]

        master_results: dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_contract": "Variant B (Next-Session Open MOO, H=15, TP +5%, SL -2%)",
            "training_decision_cutoff_date": self.cutoff_date,
            "forward_label_maturity_bar_date": "2026-10-16",
            "n_splits": self.n_splits,
            "purge_days": self.purge_days,
            "random_state": self.random_state,
            "modes": {},
        }

        all_clf_fold_rows: list[dict[str, Any]] = []
        all_clf_summary_rows: list[dict[str, Any]] = []
        all_trade_summary_rows: list[dict[str, Any]] = []
        all_trade_fold_rows: list[dict[str, Any]] = []

        for mode in modes:
            logger.info("Executing walk-forward evaluation for %s...", mode)
            mode_eval = self.run_walk_forward_evaluation(mode=mode, simulate_trading=True)

            # Fit and serialize final challenger binaries
            df_matured, _ = self.load_matured_data(mode)
            fit_meta = self.fit_and_serialize_challengers(mode=mode, df=df_matured)

            mode_eval["final_artifacts"] = fit_meta
            master_results["modes"][mode] = mode_eval

            # Collect tabular rows
            all_clf_fold_rows.extend(mode_eval["classification_fold_results"])
            all_clf_summary_rows.extend(mode_eval["classification_summaries"])
            all_trade_summary_rows.extend(mode_eval["trading_summaries"])
            for _m_id, stats in mode_eval["trading_fold_stats"].items():
                for s in stats:
                    # Exclude daily equity curve from CSV summary
                    clean_s = {k: v for k, v in s.items() if k != "daily_equity"}
                    all_trade_fold_rows.append(clean_s)

            # Save OOS predictions CSV
            oos_path = self.artifacts_dir / f"oos_predictions_{mode.lower()}.csv"
            mode_eval["oos_predictions"].to_csv(oos_path, index=False)

        # Export metrics files
        metrics_dir = self.artifacts_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(all_clf_fold_rows).to_csv(
            metrics_dir / "classification_fold_metrics.csv", index=False
        )
        pd.DataFrame(all_clf_summary_rows).to_csv(
            metrics_dir / "classification_macro_summaries.csv", index=False
        )
        pd.DataFrame(all_trade_fold_rows).to_csv(
            metrics_dir / "trading_fold_metrics.csv", index=False
        )
        pd.DataFrame(all_trade_summary_rows).to_csv(
            metrics_dir / "trading_macro_summaries.csv", index=False
        )

        # Clean JSON for persistence (remove DataFrame objects and dates)
        def _json_serialize(obj: Any) -> Any:
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                return None
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (np.int64, np.int32)):
                return int(obj)
            if isinstance(obj, (np.float64, np.float32)):
                return float(obj)
            return obj

        clean_results = json.loads(json.dumps(master_results, default=_json_serialize))
        # Drop raw oos predictions from master JSON
        for m in modes:
            if "oos_predictions" in clean_results["modes"][m]:
                del clean_results["modes"][m]["oos_predictions"]

        json_path = self.artifacts_dir / "challenger_retraining_summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(clean_results, f, indent=2)

        metadata_path = self.artifacts_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "run_id": self.run_id,
                    "created_at": clean_results["created_at"],
                    "cutoff_date": self.cutoff_date,
                    "target_contract": clean_results["target_contract"],
                    "artifacts_dir": str(self.artifacts_dir),
                    "modes": {m: clean_results["modes"][m]["final_artifacts"] for m in modes},
                },
                f,
                indent=2,
            )

        logger.info("Retraining and evaluation complete. Artifacts saved to %s", self.artifacts_dir)
        return clean_results
