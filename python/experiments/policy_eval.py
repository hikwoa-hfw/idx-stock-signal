"""Dynamic Exit & Policy Selection Research Engine (Phase 11D).

Evaluates whether selective entry policies, market-regime conditioning,
dynamic holding periods, and dynamic TP/SL can improve simulated out-of-sample
net trading performance for the BEI dual-mode stock-signal system.

Strict offline research contract:
- Production champion models and registry remain strictly immutable.
- Reference baselines frozen from Phase 11C without retraining.
- 50 bps round-trip nominal friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip).
- 100-share lot sizes, maximum 5 concurrent positions, 20% equity cap per position.
- Strict point-in-time causality: all inputs known at decision Close t, entry at Open t+1.
"""

import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np
import pandas as pd

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from python.common.types import DailyBar
from python.config.settings import settings
from python.experiments.candidate_eval import SimulatedTrade
from scripts.audit_target_contract_runner import load_all_bars


@dataclass
class PolicySummary:
    policy_id: str
    experiment: str  # "BASELINE", "EXP_A_SELECTIVITY", "EXP_B_REGIME", etc.
    description: str
    mode: str
    model_id: str
    fold: int  # 0 for pooled / all folds
    total_signals: int
    completed_trades: int
    win_rate: float
    tp_count: int
    tp_rate: float
    sl_count: int
    sl_rate: float
    expiry_count: int
    expiry_rate: float
    avg_net_return: float
    pooled_profit_factor: float
    mean_profit_factor: float
    worst_fold_max_drawdown_pct: float
    continuous_max_drawdown_pct: float
    invalidated_total: int
    invalidated_gap_down: int
    invalidated_gap_up: int
    invalidated_excessive_dev: int
    unfilled_total: int
    unfilled_suspended: int
    unfilled_capacity: int
    unfilled_cash: int
    signals_removed_regime: int
    dates_too_few_candidates: int
    avg_daily_candidates: float
    avg_holding_days: float
    eligible_candidates: int = 0
    portfolio_turnover: float = 0.0
    daily_turnover: float = 0.0
    time_in_market_pct: float = 0.0


class PolicyEvaluationEngine:
    """Core simulation and policy evaluation engine for Phase 11D."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        phase11c_dir: Union[str, Path] = "artifacts/phase_11c",
        initial_capital: float = 100_000_000.0,
        max_positions: int = 5,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
    ) -> None:
        self.db_path = db_path or self._resolve_db_path()
        self.phase11c_dir = Path(phase11c_dir)
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.commission_buy = commission_buy
        self.commission_sell = commission_sell
        self.slippage_entry_bps = slippage_entry_bps
        self.slippage_exit_bps = slippage_exit_bps

        # Lazily loaded caches
        self._bars_by_ticker: Optional[dict[str, list[DailyBar]]] = None
        self._bar_lookup: Optional[dict[tuple[str, date], DailyBar]] = None
        self._regime_lookup: Optional[dict[date, dict[str, float]]] = None
        self._atr_lookup: Optional[dict[tuple[str, date], float]] = None
        self._all_trading_dates: Optional[list[date]] = None

    def _resolve_db_path(self) -> str:
        url = settings.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        if url.startswith("sqlite://"):
            return url[len("sqlite://") :]
        return "datasets/stock_signals.db"

    @property
    def bars_by_ticker(self) -> dict[str, list[DailyBar]]:
        if self._bars_by_ticker is None:
            self._bars_by_ticker = load_all_bars(self.db_path)
        return self._bars_by_ticker

    @property
    def bar_lookup(self) -> dict[tuple[str, date], DailyBar]:
        if self._bar_lookup is None:
            self._bar_lookup = {
                (t, b.date): b for t, b_list in self.bars_by_ticker.items() for b in b_list
            }
        return self._bar_lookup

    @property
    def regime_lookup(self) -> dict[date, dict[str, float]]:
        if self._regime_lookup is None:
            conn = sqlite3.connect(self.db_path)
            try:
                query = """
                    SELECT date,
                           AVG(ihsg_vs_ema20) as ihsg_vs_ema20,
                           AVG(market_breadth) as market_breadth,
                           AVG(ihsg_return_20d) as ihsg_return_20d,
                           AVG(market_volatility) as market_volatility
                    FROM features_daily
                    GROUP BY date;
                """
                df_reg = pd.read_sql_query(query, conn)
                df_reg["date"] = pd.to_datetime(df_reg["date"]).dt.date
                self._regime_lookup = {
                    r["date"]: {
                        "ihsg_vs_ema20": float(r["ihsg_vs_ema20"])
                        if pd.notnull(r["ihsg_vs_ema20"])
                        else 0.0,
                        "market_breadth": float(r["market_breadth"])
                        if pd.notnull(r["market_breadth"])
                        else 0.0,
                        "ihsg_return_20d": float(r["ihsg_return_20d"])
                        if pd.notnull(r["ihsg_return_20d"])
                        else 0.0,
                        "market_volatility": float(r["market_volatility"])
                        if pd.notnull(r["market_volatility"])
                        else 0.0,
                    }
                    for _, r in df_reg.iterrows()
                }
            finally:
                conn.close()
        return self._regime_lookup

    @property
    def atr_lookup(self) -> dict[tuple[str, date], float]:
        if self._atr_lookup is None:
            conn = sqlite3.connect(self.db_path)
            try:
                query = """
                    SELECT date, ticker, atr_pct
                    FROM features_daily
                    WHERE atr_pct IS NOT NULL;
                """
                df_atr = pd.read_sql_query(query, conn)
                df_atr["date"] = pd.to_datetime(df_atr["date"]).dt.date
                self._atr_lookup = {
                    (r["ticker"].strip().upper().removesuffix(".JK"), r["date"]): float(
                        r["atr_pct"]
                    )
                    for _, r in df_atr.iterrows()
                }
            finally:
                conn.close()
        return self._atr_lookup

    def load_mode_dataset(self, mode: str) -> pd.DataFrame:
        """Loads and formats Phase 11C out-of-sample predictions merged with features."""
        csv_path = self.phase11c_dir / f"multi_horizon_oos_predictions_{mode}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing Phase 11C predictions at {csv_path}")

        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["ticker"] = df["ticker"].str.strip().str.upper().str.removesuffix(".JK")
        df["va_entry_price"] = df["decision_price"]

        # Attach ATR percentage
        atr_map = self.atr_lookup
        df["atr_pct"] = [
            atr_map.get((t, d), 0.03) for t, d in zip(df["ticker"], df["date"], strict=False)
        ]

        # Attach multi-horizon pivoted predictions for dynamic horizon selection
        df_pvt_ret = df.pivot_table(
            index=["fold", "date", "ticker"], columns="horizon", values="pred_return_lgb"
        )
        df_pvt_ret.columns = [f"pred_ret_h{h}" for h in df_pvt_ret.columns]

        df_pvt_prob = df.pivot_table(
            index=["fold", "date", "ticker"], columns="horizon", values="prob_lgb_full"
        )
        df_pvt_prob.columns = [f"prob_full_h{h}" for h in df_pvt_prob.columns]

        pvt_all = df_pvt_ret.join(df_pvt_prob, how="left").reset_index()

        df_merged = df.merge(pvt_all, on=["fold", "date", "ticker"], how="left")

        return df_merged

    @property
    def all_trading_dates(self) -> list[date]:
        if self._all_trading_dates is None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT DISTINCT date FROM features_daily ORDER BY date;"
                ).fetchall()
                self._all_trading_dates = [pd.to_datetime(r[0]).date() for r in rows]
            finally:
                conn.close()
        return self._all_trading_dates

    def compute_fold_training_stats(
        self, df_mode: pd.DataFrame, purge_days: int = 15
    ) -> dict[int, dict[str, float]]:
        """Calculates causal training-fold stats strictly without test data leakage."""
        stats: dict[int, dict[str, float]] = {}
        all_dates = self.all_trading_dates

        conn = sqlite3.connect(self.db_path)
        try:
            df_feat = pd.read_sql_query(
                "SELECT date, atr_pct FROM features_daily WHERE atr_pct IS NOT NULL;", conn
            )
            df_feat["date"] = pd.to_datetime(df_feat["date"]).dt.date

            df_lbl = pd.read_sql_query(
                "SELECT date, mfe, mae FROM labels_daily "
                "WHERE mfe IS NOT NULL AND mae IS NOT NULL;",
                conn,
            )
            df_lbl["date"] = pd.to_datetime(df_lbl["date"]).dt.date
        finally:
            conn.close()

        for f in [1, 2, 3]:
            f_test_dates = sorted(df_mode[df_mode["fold"] == f]["date"].unique())
            if not f_test_dates:
                stats[f] = {
                    "median_atr_pct": 0.03,
                    "p75_atr_pct": 0.04,
                    "p25_atr_pct": 0.02,
                    "tp_multiplier": 1.5,
                    "sl_multiplier": 0.75,
                }
                continue

            test_start = f_test_dates[0]
            if test_start in all_dates:
                test_start_idx = all_dates.index(test_start)
                train_cutoff_idx = max(0, test_start_idx - purge_days)
                train_cutoff_date = all_dates[train_cutoff_idx]
            else:
                train_cutoff_date = test_start

            f_feat_tr = df_feat[df_feat["date"] <= train_cutoff_date]
            f_lbl_tr = df_lbl[df_lbl["date"] <= train_cutoff_date]

            med_atr = float(f_feat_tr["atr_pct"].median()) if not f_feat_tr.empty else 0.03
            p75_atr = float(f_feat_tr["atr_pct"].quantile(0.75)) if not f_feat_tr.empty else 0.04
            p25_atr = float(f_feat_tr["atr_pct"].quantile(0.25)) if not f_feat_tr.empty else 0.02

            # Derive TP/SL multipliers causally from training fold MFE p75 and median MAE
            if not f_lbl_tr.empty and med_atr > 0:
                mfe_75 = float(f_lbl_tr["mfe"].quantile(0.75))
                mae_med = float(abs(f_lbl_tr["mae"].median()))
                tp_mult = round(float(np.clip(mfe_75 / med_atr, 1.2, 2.5)), 2)
                sl_mult = round(float(np.clip(mae_med / med_atr, 0.5, 1.5)), 2)
            else:
                tp_mult = 1.5
                sl_mult = 0.75

            stats[f] = {
                "median_atr_pct": med_atr,
                "p75_atr_pct": p75_atr,
                "p25_atr_pct": p25_atr,
                "tp_multiplier": tp_mult,
                "sl_multiplier": sl_mult,
                "train_cutoff_date": str(train_cutoff_date),
            }
        return stats

    def simulate_policy(
        self,
        df_test: pd.DataFrame,
        score_col: str,
        top_k_pct: Optional[float] = None,
        top_n_per_day: int = 5,
        min_candidates: int = 10,
        regime_filter: Optional[Callable[[dict[str, float]], bool]] = None,
        horizon_policy: Union[int, Callable[[pd.Series], int]] = 15,
        tp_sl_policy: Union[tuple[float, float], Callable[[pd.Series], tuple[float, float]]] = (
            0.05,
            0.02,
        ),
        max_entry_dev_pct: float = 0.05,
    ) -> dict[str, Any]:
        """Simulates discrete-event trading for an arbitrary dynamic policy."""
        regime_lookup = self.regime_lookup

        eval_df = df_test.copy()
        eval_df["score"] = eval_df[score_col]
        dates_sorted = sorted(eval_df["date"].unique())

        cash = float(self.initial_capital)
        peak_equity = float(self.initial_capital)
        total_eq = float(self.initial_capital)
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        daily_equity: list[tuple[date, float]] = []

        open_positions: dict[str, dict[str, Any]] = {}
        completed_trades: list[SimulatedTrade] = []

        total_signals_generated = 0
        signals_removed_regime = 0
        dates_too_few_candidates = 0
        invalidated_gap_down = 0
        invalidated_gap_up = 0
        invalidated_excessive_dev = 0
        unfilled_suspended = 0
        unfilled_capacity = 0
        unfilled_cash = 0

        bar_lookup = self.bar_lookup
        candidates_by_date = {d: sub for d, sub in eval_df.groupby("date", sort=False)}
        empty_day_cands = eval_df.iloc[:0]

        pending_orders: list[dict[str, Any]] = []
        last_known_close: dict[str, float] = {}

        candidate_counts_on_eval_dates: list[int] = []
        days_with_open = 0

        for curr_d in dates_sorted:
            # 1. Execute pending orders from previous trading date
            if pending_orders:
                # Rank pending orders: score desc, ticker asc
                pending_orders.sort(key=lambda o: (-o["score"], o["ticker"]))

                for ord_info in pending_orders:
                    t = ord_info["ticker"]
                    c_close = ord_info["close_t"]
                    ord_tp = ord_info["tp_pct"]
                    ord_sl = ord_info["sl_pct"]
                    ord_h = ord_info["max_holding_days"]

                    if len(open_positions) >= self.max_positions:
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
                    if b_open <= c_close * (1.0 - ord_sl):
                        invalidated_gap_down += 1
                        continue
                    if b_open >= c_close * (1.0 + ord_tp):
                        invalidated_gap_up += 1
                        continue
                    if abs(b_open - c_close) / c_close > max_entry_dev_pct:
                        invalidated_excessive_dev += 1
                        continue

                    # Sizing: Equal weight allocation capped at 20% equity
                    open_val = sum(
                        pos["shares"] * last_known_close.get(pos["ticker"], pos["entry_price"])
                        for pos in open_positions.values()
                    )
                    current_equity = cash + open_val

                    cap_per_pos = min(
                        current_equity / self.max_positions,
                        current_equity * 0.20,
                    )
                    fill_price = b_open * (1.0 + self.slippage_entry_bps / 10000.0)
                    raw_shares = cap_per_pos / fill_price
                    max_cash_shares = cash / (fill_price * (1.0 + self.commission_buy))
                    shares_f = min(raw_shares, max_cash_shares)

                    # Lot size rounding (100 shares per lot)
                    shares = int(shares_f // 100) * 100
                    if shares < 100:
                        unfilled_cash += 1
                        continue

                    gross_outlay = shares * fill_price
                    entry_fee = gross_outlay * self.commission_buy
                    total_outlay = gross_outlay + entry_fee

                    if total_outlay > cash:
                        shares = (
                            int((cash / (fill_price * (1.0 + self.commission_buy))) // 100) * 100
                        )
                        if shares < 100:
                            unfilled_cash += 1
                            continue
                        gross_outlay = shares * fill_price
                        entry_fee = gross_outlay * self.commission_buy
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
                        "tp_pct": ord_tp,
                        "sl_pct": ord_sl,
                        "tp_price": fill_price * (1.0 + ord_tp),
                        "sl_price": fill_price * (1.0 - ord_sl),
                        "max_holding_days": ord_h,
                        "holding_days": 1,
                        "score": ord_info["score"],
                    }

                pending_orders.clear()

            # 2. Intraday barrier checks on Day curr_d for active positions
            active_tickers = list(open_positions.keys())
            if active_tickers:
                days_with_open += 1
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
                    exit_raw = (
                        pos["sl_price"]
                        if pos["holding_days"] == 1
                        else (
                            bar_curr.open if bar_curr.open <= pos["sl_price"] else pos["sl_price"]
                        )
                    )
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
                elif pos["holding_days"] >= pos["max_holding_days"]:
                    exit_reason = "EXPIRY"
                    exit_raw = float(bar_curr.close)

                if exit_reason is not None and exit_raw is not None:
                    exit_fill = exit_raw * (1.0 - self.slippage_exit_bps / 10000.0)
                    gross_proceeds = pos["shares"] * exit_fill
                    exit_fee = gross_proceeds * self.commission_sell
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
            day_candidates = candidates_by_date.get(curr_d, empty_day_cands)
            n_cands = len(day_candidates)

            if n_cands < min_candidates:
                dates_too_few_candidates += 1
                continue

            candidate_counts_on_eval_dates.append(n_cands)

            # Apply regime filter if specified
            if regime_filter is not None:
                reg_info = regime_lookup.get(curr_d, {})
                if not regime_filter(reg_info):
                    signals_removed_regime += n_cands
                    continue

            sorted_cands = day_candidates.sort_values(
                by=["score", "ticker"], ascending=[False, True], kind="stable"
            )

            if top_k_pct is not None:
                n_select = max(1, math.ceil(n_cands * top_k_pct))
                top_picks = sorted_cands.iloc[:n_select]
            else:
                top_picks = sorted_cands.iloc[:top_n_per_day]

            for _, r in top_picks.iterrows():
                total_signals_generated += 1

                # Dynamic holding duration
                if callable(horizon_policy):
                    h_val = horizon_policy(r)
                else:
                    h_val = int(horizon_policy)

                # Dynamic TP/SL
                if callable(tp_sl_policy):
                    tp_val, sl_val = tp_sl_policy(r)
                else:
                    tp_val, sl_val = tp_sl_policy

                pending_orders.append(
                    {
                        "ticker": r["ticker"],
                        "signal_date": curr_d,
                        "close_t": float(r["va_entry_price"]),
                        "score": float(r["score"]),
                        "max_holding_days": h_val,
                        "tp_pct": tp_val,
                        "sl_pct": sl_val,
                    }
                )

        # Final summary metrics for fold
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
        avg_candidates = (
            float(np.mean(candidate_counts_on_eval_dates))
            if candidate_counts_on_eval_dates
            else 0.0
        )
        total_gross_outlay = sum(t.shares * t.entry_price for t in completed_trades)
        port_turnover = (
            round(total_gross_outlay / self.initial_capital, 2)
            if self.initial_capital > 0
            else 0.0
        )
        daily_turn = round(n_trades / len(dates_sorted), 4) if dates_sorted else 0.0
        time_in_mkt = (
            round(days_with_open / len(dates_sorted) * 100.0, 2) if dates_sorted else 0.0
        )
        eligible_cands = sum(candidate_counts_on_eval_dates)

        return {
            "initial_capital": self.initial_capital,
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
            "gain": total_gain,
            "loss": total_loss,
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
            "signals_removed_regime": signals_removed_regime,
            "dates_too_few_candidates": dates_too_few_candidates,
            "avg_daily_candidates": round(avg_candidates, 1),
            "eligible_candidates": eligible_cands,
            "portfolio_turnover": port_turnover,
            "daily_turnover": daily_turn,
            "time_in_market_pct": time_in_mkt,
            "daily_equity": daily_equity,
            "trades": completed_trades,
        }

    def aggregate_folds(
        self,
        policy_id: str,
        experiment: str,
        description: str,
        mode: str,
        model_id: str,
        fold_results: list[dict[str, Any]],
    ) -> tuple[PolicySummary, list[PolicySummary]]:
        """Aggregates per-fold simulation runs into pooled and per-fold PolicySummary records."""
        per_fold_summaries: list[PolicySummary] = []

        all_trades: list[SimulatedTrade] = []
        for fold_idx, res in enumerate(fold_results, start=1):
            trades = res["trades"]
            all_trades.extend(trades)
            pf = res["profit_factor"]
            f_summary = PolicySummary(
                policy_id=policy_id,
                experiment=experiment,
                description=description,
                mode=mode,
                model_id=model_id,
                fold=fold_idx,
                total_signals=res["total_signals"],
                completed_trades=res["completed_trades"],
                win_rate=res["win_rate"],
                tp_count=res["tp_count"],
                tp_rate=res["tp_rate"],
                sl_count=res["sl_count"],
                sl_rate=res["sl_rate"],
                expiry_count=res["expiry_count"],
                expiry_rate=res["expiry_rate"],
                avg_net_return=res["avg_net_return"],
                pooled_profit_factor=pf,
                mean_profit_factor=pf,
                worst_fold_max_drawdown_pct=res["max_drawdown_pct"],
                continuous_max_drawdown_pct=res["max_drawdown_pct"],
                invalidated_total=res["invalidated_total"],
                invalidated_gap_down=res["invalidated_gap_down"],
                invalidated_gap_up=res["invalidated_gap_up"],
                invalidated_excessive_dev=res["invalidated_excessive_dev"],
                unfilled_total=res["unfilled_total"],
                unfilled_suspended=res["unfilled_suspended"],
                unfilled_capacity=res["unfilled_capacity"],
                unfilled_cash=res["unfilled_cash"],
                signals_removed_regime=res["signals_removed_regime"],
                dates_too_few_candidates=res["dates_too_few_candidates"],
                avg_daily_candidates=res["avg_daily_candidates"],
                avg_holding_days=res["avg_holding_days"],
                eligible_candidates=res.get("eligible_candidates", 0),
                portfolio_turnover=res.get("portfolio_turnover", 0.0),
                daily_turnover=res.get("daily_turnover", 0.0),
                time_in_market_pct=res.get("time_in_market_pct", 0.0),
            )
            per_fold_summaries.append(f_summary)

        # Pooled stats across all folds
        tot_trades = len(all_trades)
        wins = sum(1 for t in all_trades if t.net_pnl > 0)
        win_rate = (wins / tot_trades) if tot_trades > 0 else 0.0
        tp_tot = sum(1 for t in all_trades if t.exit_reason == "TP")
        sl_tot = sum(1 for t in all_trades if t.exit_reason == "SL")
        exp_tot = sum(1 for t in all_trades if t.exit_reason == "EXPIRY")

        gain_tot = sum(t.net_pnl for t in all_trades if t.net_pnl > 0)
        loss_tot = sum(abs(t.net_pnl) for t in all_trades if t.net_pnl < 0)
        pooled_pf = (
            (gain_tot / loss_tot) if loss_tot > 0 else (float("inf") if gain_tot > 0 else 0.0)
        )

        avg_ret = sum(t.net_return for t in all_trades) / tot_trades if tot_trades > 0 else 0.0
        avg_holding = (
            sum(t.holding_days for t in all_trades) / tot_trades if tot_trades > 0 else 0.0
        )

        pf_vals = [r["profit_factor"] for r in fold_results if math.isfinite(r["profit_factor"])]
        mean_pf = float(np.mean(pf_vals)) if pf_vals else 0.0
        worst_dd = max(r["max_drawdown_pct"] for r in fold_results) if fold_results else 0.0

        # Continuous portfolio drawdown across chained test folds
        has_daily = all(r.get("daily_equity") for r in fold_results)
        if has_daily:
            cont_series: list[float] = []
            scale = 1.0
            for r in fold_results:
                init_cap = float(r.get("initial_capital", self.initial_capital))
                for _, eq in r["daily_equity"]:
                    cont_series.append(scale * eq)
                fin_eq = float(r.get("final_equity", init_cap))
                scale *= (fin_eq / init_cap) if init_cap > 0 else 1.0

            peak = cont_series[0] if cont_series else self.initial_capital
            max_cont_dd = 0.0
            for eq_val in cont_series:
                if eq_val > peak:
                    peak = eq_val
                dd = (peak - eq_val) / peak if peak > 0 else 0.0
                if dd > max_cont_dd:
                    max_cont_dd = dd
            continuous_dd = round(max_cont_dd * 100.0, 2)
        else:
            continuous_dd = worst_dd

        pooled_summary = PolicySummary(
            policy_id=policy_id,
            experiment=experiment,
            description=description,
            mode=mode,
            model_id=model_id,
            fold=0,
            total_signals=sum(r["total_signals"] for r in fold_results),
            completed_trades=tot_trades,
            win_rate=round(win_rate, 4),
            tp_count=tp_tot,
            tp_rate=round(tp_tot / tot_trades, 4) if tot_trades > 0 else 0.0,
            sl_count=sl_tot,
            sl_rate=round(sl_tot / tot_trades, 4) if tot_trades > 0 else 0.0,
            expiry_count=exp_tot,
            expiry_rate=round(exp_tot / tot_trades, 4) if tot_trades > 0 else 0.0,
            avg_net_return=round(avg_ret, 4),
            pooled_profit_factor=round(pooled_pf, 2) if math.isfinite(pooled_pf) else 999.0,
            mean_profit_factor=round(mean_pf, 2) if math.isfinite(mean_pf) else 999.0,
            worst_fold_max_drawdown_pct=round(worst_dd, 2),
            continuous_max_drawdown_pct=continuous_dd,
            invalidated_total=sum(r["invalidated_total"] for r in fold_results),
            invalidated_gap_down=sum(r["invalidated_gap_down"] for r in fold_results),
            invalidated_gap_up=sum(r["invalidated_gap_up"] for r in fold_results),
            invalidated_excessive_dev=sum(r["invalidated_excessive_dev"] for r in fold_results),
            unfilled_total=sum(r["unfilled_total"] for r in fold_results),
            unfilled_suspended=sum(r["unfilled_suspended"] for r in fold_results),
            unfilled_capacity=sum(r["unfilled_capacity"] for r in fold_results),
            unfilled_cash=sum(r["unfilled_cash"] for r in fold_results),
            signals_removed_regime=sum(r["signals_removed_regime"] for r in fold_results),
            dates_too_few_candidates=sum(r["dates_too_few_candidates"] for r in fold_results),
            avg_daily_candidates=round(
                float(np.mean([r["avg_daily_candidates"] for r in fold_results])), 1
            ),
            avg_holding_days=round(avg_holding, 1),
            eligible_candidates=sum(r.get("eligible_candidates", 0) for r in fold_results),
            portfolio_turnover=round(
                sum(r.get("portfolio_turnover", 0.0) for r in fold_results), 2
            ),
            daily_turnover=round(
                float(np.mean([r.get("daily_turnover", 0.0) for r in fold_results])), 4
            )
            if fold_results
            else 0.0,
            time_in_market_pct=round(
                float(np.mean([r.get("time_in_market_pct", 0.0) for r in fold_results])), 2
            )
            if fold_results
            else 0.0,
        )

        return pooled_summary, per_fold_summaries


def run_all_phase11d_experiments(
    engine: Optional[PolicyEvaluationEngine] = None,
    output_dir: Union[str, Path] = "artifacts/phase_11d",
) -> dict[str, Any]:
    """Coordinates and executes all Phase 11D experiments across both price modes."""
    if engine is None:
        engine = PolicyEvaluationEngine()

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    all_pooled_summaries: list[dict[str, Any]] = []
    all_fold_summaries: list[dict[str, Any]] = []
    sample_trades_list: list[dict[str, Any]] = []

    results_by_mode: dict[str, Any] = {}

    for mode in ["LOW_PRICE", "HIGHER_PRICE"]:
        df_mode = engine.load_mode_dataset(mode)
        training_stats = engine.compute_fold_training_stats(df_mode)

        # Baseline Primary Reference Model ID:
        # LOW_PRICE: lgb_regressor (primary Phase 11C winner) + lgb_full
        # HIGHER_PRICE: lgb_full (primary Phase 11C winner) + lgb_regressor
        primary_score_col = "pred_return_lgb" if mode == "LOW_PRICE" else "prob_lgb_full"
        primary_model_name = "lgb_regressor" if mode == "LOW_PRICE" else "lgb_full"

        mode_pooled: list[PolicySummary] = []
        mode_folds: list[PolicySummary] = []

        # =====================================================================
        # 1. FROZEN REFERENCE BASELINES (Phase 11C Replication)
        # =====================================================================
        ref_configs = [
            (
                "ref_h15_regressor",
                "pred_return_lgb",
                15,
                "Phase 11C H=15 LightGBM Regressor (Top 5 fixed)",
            ),
            (
                "ref_h15_full",
                "prob_lgb_full",
                15,
                "Phase 11C H=15 Full LightGBM Classifier (Top 5 fixed)",
            ),
            (
                "ref_h10_comparator",
                "prob_lgb_ablation",
                10,
                "Phase 11C H=10 Ablation Classifier Comparator (Top 5 fixed)",
            ),
        ]

        for p_id, s_col, h_val, desc in ref_configs:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == h_val)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=s_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=None,
                    horizon_policy=h_val,
                    tp_sl_policy=(0.05, 0.02),
                )
                f_runs.append(res)
                if p_id == f"ref_h15_{primary_model_name.replace('lgb_', '')}":
                    for t in res["trades"][:10]:
                        sample_trades_list.append(
                            {"mode": mode, "policy_id": p_id, "fold": f, **asdict(t)}
                        )

            m_name = (
                "lgb_regressor"
                if "regressor" in p_id
                else ("lgb_full" if "full" in p_id else "lgb_ablation")
            )
            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="BASELINE",
                description=desc,
                mode=mode,
                model_id=m_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 2. EXPERIMENT A: CROSS-SECTIONAL ENTRY SELECTIVITY
        # =====================================================================
        # Evaluate Top 10%, Top 5%, Top 3%, Top 1% on primary model (plus Top 5 fixed control)
        selectivity_levels = [
            ("exp_a_control_top5", None, "Experiment A Control: Top 5 Fixed Daily Selection"),
            ("exp_a_top10pct", 0.10, "Experiment A: Top 10% Cross-Sectional Selectivity"),
            ("exp_a_top5pct", 0.05, "Experiment A: Top 5% Cross-Sectional Selectivity"),
            ("exp_a_top3pct", 0.03, "Experiment A: Top 3% Cross-Sectional Selectivity"),
            ("exp_a_top1pct", 0.01, "Experiment A: Top 1% Cross-Sectional Selectivity"),
        ]

        # Also evaluate on secondary model for robustness
        secondary_score_col = "prob_lgb_full" if mode == "LOW_PRICE" else "pred_return_lgb"
        secondary_model_name = "lgb_full" if mode == "LOW_PRICE" else "lgb_regressor"

        for s_col, m_name in [
            (primary_score_col, primary_model_name),
            (secondary_score_col, secondary_model_name),
        ]:
            for p_tag, k_pct, desc in selectivity_levels:
                p_id = f"{p_tag}_{m_name}"
                f_runs = []
                for f in [1, 2, 3]:
                    sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                    res = engine.simulate_policy(
                        df_test=sub,
                        score_col=s_col,
                        top_k_pct=k_pct,
                        min_candidates=10,
                        regime_filter=None,
                        horizon_policy=15,
                        tp_sl_policy=(0.05, 0.02),
                    )
                    f_runs.append(res)

                pooled, per_f = engine.aggregate_folds(
                    policy_id=p_id,
                    experiment="EXP_A_SELECTIVITY",
                    description=f"{desc} ({m_name})",
                    mode=mode,
                    model_id=m_name,
                    fold_results=f_runs,
                )
                mode_pooled.append(pooled)
                mode_folds.extend(per_f)

        # =====================================================================
        # 3. EXPERIMENT B: MARKET-REGIME-CONDITIONED SELECTION
        # =====================================================================
        regime_policies = [
            (
                "exp_b_none",
                None,
                "Experiment B Control: No Regime Filter (All Regimes)",
            ),
            (
                "exp_b_ihsg_trend",
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                "Experiment B: IHSG Bull Trend Only (IHSG > EMA20)",
            ),
            (
                "exp_b_breadth",
                lambda r: r.get("market_breadth", 0.0) > 0.0,
                "Experiment B: Positive Market Breadth Only (Breadth > 0)",
            ),
            (
                "exp_b_trend_and_breadth",
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0 and r.get("market_breadth", 0.0) > 0.0,
                "Experiment B: Combined Trend & Breadth Bull Filter",
            ),
            (
                "exp_b_bear_only",
                lambda r: r.get("ihsg_vs_ema20", 0.0) <= 0.0,
                "Experiment B: Bear Regime Only (IHSG <= EMA20)",
            ),
            (
                "exp_b_low_vol",
                lambda r: r.get("market_volatility", 0.0) <= 0.0075,
                "Experiment B: Low Market Volatility Only (<= median)",
            ),
        ]

        for p_id, r_filt, desc in regime_policies:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=r_filt,
                    horizon_policy=15,
                    tp_sl_policy=(0.05, 0.02),
                )
                f_runs.append(res)

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="EXP_B_REGIME",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 4. EXPERIMENT C: DYNAMIC HOLDING PERIOD
        # =====================================================================
        def make_c4_max_pred_ret_rule():
            def rule(row: pd.Series) -> int:
                # Compare predicted returns across H=3, 5, 10, 15
                r3 = row.get("pred_ret_h3", -999.0)
                r5 = row.get("pred_ret_h5", -999.0)
                r10 = row.get("pred_ret_h10", -999.0)
                r15 = row.get("pred_ret_h15", -999.0)
                h_candidates = [(r15, 15), (r10, 10), (r5, 5), (r3, 3)]
                h_candidates.sort(key=lambda x: -x[0])
                return h_candidates[0][1]

            return rule

        def make_c5_volatility_rule(median_atr: float):
            def rule(row: pd.Series) -> int:
                # If high volatility, shorter holding H=5; if low, H=15
                atr_val = row.get("atr_pct", 0.03)
                return 5 if atr_val > median_atr else 15

            return rule

        def make_c6_regime_duration_rule(reg_lookup: dict[date, dict[str, float]]):
            def rule(row: pd.Series) -> int:
                d_val = row.get("date")
                reg = reg_lookup.get(d_val, {})
                return 15 if reg.get("ihsg_vs_ema20", 0.0) > 0.0 else 5

            return rule

        duration_policies = [
            ("exp_c_fixed_h15", 15, "Experiment C Control: Fixed H=15 Holding Period Control"),
            ("exp_c_fixed_h10", 10, "Experiment C: Fixed H=10 Holding Period Control"),
            ("exp_c_fixed_h5", 5, "Experiment C: Fixed H=5 Holding Period Control"),
            (
                "exp_c_max_pred_ret",
                make_c4_max_pred_ret_rule(),
                "Experiment C: Dynamic Max Predicted Return Horizon (H in {3,5,10,15})",
            ),
            (
                "exp_c_vol_adaptive",
                "VOL_ADAPTIVE",
                "Experiment C: Volatility-Adaptive Duration (H=5 High Vol, H=15 Low Vol)",
            ),
            (
                "exp_c_regime_adaptive",
                make_c6_regime_duration_rule(engine.regime_lookup),
                "Experiment C: Regime-Adaptive Duration (H=15 Bull, H=5 Bear)",
            ),
        ]

        for p_id, h_pol, desc in duration_policies:
            f_runs = []
            for f in [1, 2, 3]:
                # If fixed horizon policy, use exact horizon test rows
                h_filter = h_pol if isinstance(h_pol, int) else 15
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == h_filter)]

                active_h_pol: Any
                if h_pol == "VOL_ADAPTIVE":
                    med_atr = training_stats[f]["median_atr_pct"]
                    active_h_pol = make_c5_volatility_rule(med_atr)
                else:
                    active_h_pol = h_pol

                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=None,
                    horizon_policy=active_h_pol,
                    tp_sl_policy=(0.05, 0.02),
                )
                f_runs.append(res)

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="EXP_C_DURATION",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 5. EXPERIMENT D: DYNAMIC TP/SL
        # =====================================================================
        def make_d4_atr_barrier_rule(
            tp_multiplier: float = 1.5, sl_multiplier: float = 0.75
        ):
            def rule(row: pd.Series) -> tuple[float, float]:
                atr_val = row.get("atr_pct", 0.03)
                tp = float(np.clip(tp_multiplier * atr_val, 0.03, 0.08))
                sl = float(np.clip(sl_multiplier * atr_val, 0.015, 0.04))
                return tp, sl

            return rule

        tpsl_policies = [
            (
                "exp_d_control",
                (0.05, 0.02),
                "Experiment D Control: Fixed Target TP +5%, SL -2% (2.5:1 R:R)",
            ),
            (
                "exp_d_expanded_tp_6_2",
                (0.06, 0.02),
                "Experiment D: Expanded Target TP +6%, SL -2% (3.0:1 R:R)",
            ),
            (
                "exp_d_quick_tp_4_2",
                (0.04, 0.02),
                "Experiment D: Quick Target TP +4%, SL -2% (2.0:1 R:R)",
            ),
            (
                "exp_d_tight_sl_5_15",
                (0.05, 0.015),
                "Experiment D: Tight Stop TP +5%, SL -1.5% (3.3:1 R:R)",
            ),
            (
                "exp_d_atr_scaled_barriers",
                "ATR_SCALED",
                "Experiment D: Causal Volatility-Scaled Barriers (Derived from Training Folds)",
            ),
        ]

        for p_id, tp_pol, desc in tpsl_policies:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                if tp_pol == "ATR_SCALED":
                    active_tp_mult = training_stats[f].get("tp_multiplier", 1.5)
                    active_sl_mult = training_stats[f].get("sl_multiplier", 0.75)
                    active_tp_pol = make_d4_atr_barrier_rule(active_tp_mult, active_sl_mult)
                else:
                    active_tp_pol = tp_pol

                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=None,
                    horizon_policy=15,
                    tp_sl_policy=active_tp_pol,
                )
                f_runs.append(res)

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="EXP_D_TPSL",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 6. COMBINED / WALK-FORWARD SELECTED POLICY
        # =====================================================================
        # Synthesizes Selective Entry + Bull Trend Conditioning + H=15 + Expanded TP (+6%/-2%)
        comb_configs = [
            (
                "combined_policy_top3_trend_tp6",
                0.03,
                "Combined Policy: Top 3% Selectivity + Bull Filter + H=15 + TP +6%/-2%",
            ),
        ]
        if mode == "HIGHER_PRICE":
            comb_configs.append(
                (
                    "combined_policy_top1_trend_tp6",
                    0.01,
                    "Combined Policy: Top 1% Selectivity + Bull Filter + H=15 + TP +6%/-2%",
                )
            )

        for p_id_comb, top_k_comb, desc_comb in comb_configs:
            f_runs_comb = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=top_k_comb,
                    min_candidates=10,
                    regime_filter=lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                    horizon_policy=15,
                    tp_sl_policy=(0.06, 0.02),
                )
                f_runs_comb.append(res)

            pooled_comb, per_f_comb = engine.aggregate_folds(
                policy_id=p_id_comb,
                experiment="COMBINED",
                description=desc_comb,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs_comb,
            )
            mode_pooled.append(pooled_comb)
            mode_folds.extend(per_f_comb)

        results_by_mode[mode] = {
            "pooled": mode_pooled,
            "per_fold": mode_folds,
        }

        for p in mode_pooled:
            all_pooled_summaries.append(asdict(p))
        for f_s in mode_folds:
            all_fold_summaries.append(asdict(f_s))

    # =====================================================================
    # EXPORT MACHINE-READABLE ARTIFACTS
    # =====================================================================
    # 1. JSON dumps by mode
    for mode in ["LOW_PRICE", "HIGHER_PRICE"]:
        mode_json = {
            "mode": mode,
            "pooled_summaries": [asdict(p) for p in results_by_mode[mode]["pooled"]],
            "fold_summaries": [asdict(f) for f in results_by_mode[mode]["per_fold"]],
        }
        json_file = out_p / f"policy_metrics_{mode}.json"
        with open(json_file, "w", encoding="utf-8") as fp:
            json.dump(mode_json, fp, indent=2)

    # 2. CSV summaries
    df_all_pooled = pd.DataFrame(all_pooled_summaries)
    df_all_pooled.to_csv(out_p / "policy_summary_all.csv", index=False)

    df_all_folds = pd.DataFrame(all_fold_summaries)
    df_all_folds.to_csv(out_p / "policy_summary_by_fold.csv", index=False)

    # Split into per-experiment summary CSVs for modular reporting
    for exp_id, filename in [
        ("BASELINE", "baseline_reference_summary.csv"),
        ("EXP_A_SELECTIVITY", "experiment_a_selectivity_summary.csv"),
        ("EXP_B_REGIME", "experiment_b_regime_summary.csv"),
        ("EXP_C_DURATION", "experiment_c_duration_summary.csv"),
        ("EXP_D_TPSL", "experiment_d_tpsl_summary.csv"),
        ("COMBINED", "combined_policy_summary.csv"),
    ]:
        sub_df = df_all_pooled[df_all_pooled["experiment"] == exp_id]
        sub_df.to_csv(out_p / filename, index=False)

    # 3. Sample trades CSV
    pd.DataFrame(sample_trades_list).to_csv(
        out_p / "phase_11d_selected_trades_sample.csv", index=False
    )

    return {
        "results_by_mode": results_by_mode,
        "pooled_df": df_all_pooled,
        "folds_df": df_all_folds,
        "exported_files": [
            str(out_p / "policy_summary_all.csv"),
            str(out_p / "policy_summary_by_fold.csv"),
            str(out_p / "experiment_a_selectivity_summary.csv"),
            str(out_p / "experiment_b_regime_summary.csv"),
            str(out_p / "experiment_c_duration_summary.csv"),
            str(out_p / "experiment_d_tpsl_summary.csv"),
            str(out_p / "combined_policy_summary.csv"),
            str(out_p / "policy_metrics_LOW_PRICE.json"),
            str(out_p / "policy_metrics_HIGHER_PRICE.json"),
            str(out_p / "phase_11d_selected_trades_sample.csv"),
        ],
    }
