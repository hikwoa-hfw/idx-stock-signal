"""Dynamic Conviction Sizing & Volatility Trailing Protection Research Engine (Phase 11E).

Evaluates whether point-in-time regime conviction sizing and volatility-based
trailing protection can improve portfolio risk-adjusted performance without
relying on fragile pooled profitability.

Strict offline research contract:
- Production champion models and registry remain strictly immutable.
- Frozen reference baselines reused from Phase 11D without retraining.
- 50 bps round-trip nominal friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip).
- 100-share lot sizes, maximum 5 concurrent positions, 20% equity cap per position.
- Strict point-in-time causality: all inputs known at decision Close t, entry at Open t+1.
- Trailing stops strictly tighten as the watermark rises; they never loosen.
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
from scripts.audit_target_contract_runner import load_all_bars


@dataclass
class SimulatedTrade11E:
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
    exit_reason: str  # "TP", "SL", "TRAILING_SL", "EXPIRY"
    holding_days: int
    signal_prob: float
    size_multiplier: float
    regime_category: str  # "FAVORABLE", "MIXED", "UNFAVORABLE"
    highest_watermark: float
    final_sl_price: float


@dataclass
class PolicySummary11E:
    policy_id: str
    experiment: str  # "BASELINE", "EXP_A_SIZING", "EXP_B_TRAILING", "COMBINED"
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
    trailing_stop_count: int
    trailing_stop_rate: float
    expiry_count: int
    expiry_rate: float
    avg_net_return: float  # Trade-level expectancy
    net_portfolio_return_pct: float  # Portfolio net return percentage
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
    skipped_regime_sizing: int
    signals_removed_regime: int
    dates_too_few_candidates: int
    avg_daily_candidates: float
    avg_holding_days: float
    eligible_candidates: int = 0
    portfolio_turnover: float = 0.0
    daily_turnover: float = 0.0
    time_in_market_pct: float = 0.0
    avg_portfolio_allocation_pct: float = 0.0
    max_portfolio_allocation_pct: float = 0.0
    avg_cash_exposure_pct: float = 100.0
    avg_allocation_favorable: float = 0.0
    avg_allocation_mixed: float = 0.0
    avg_allocation_unfavorable: float = 0.0
    remaining_open_positions: int = 0


class SizingTrailingEvaluationEngine:
    """Core simulation engine for Phase 11E sizing and trailing stop research."""

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
                        else 0.5,
                        "ihsg_return_20d": float(r["ihsg_return_20d"])
                        if pd.notnull(r["ihsg_return_20d"])
                        else 0.0,
                        "market_volatility": float(r["market_volatility"])
                        if pd.notnull(r["market_volatility"])
                        else 0.0075,
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
            atr_map.get((t, d), 0.035) for t, d in zip(df["ticker"], df["date"], strict=False)
        ]

        return df

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
        finally:
            conn.close()

        for f in [1, 2, 3]:
            f_test_dates = sorted(df_mode[df_mode["fold"] == f]["date"].unique())
            if not f_test_dates:
                stats[f] = {"median_atr_pct": 0.035, "p75_atr_pct": 0.045}
                continue

            test_start = f_test_dates[0]
            if test_start in all_dates:
                test_start_idx = all_dates.index(test_start)
                train_cutoff_idx = max(0, test_start_idx - purge_days)
                train_cutoff_date = all_dates[train_cutoff_idx]
            else:
                train_cutoff_date = test_start

            f_feat_tr = df_feat[df_feat["date"] <= train_cutoff_date]
            med_atr = float(f_feat_tr["atr_pct"].median()) if not f_feat_tr.empty else 0.035
            p75_atr = float(f_feat_tr["atr_pct"].quantile(0.75)) if not f_feat_tr.empty else 0.045

            stats[f] = {
                "median_atr_pct": med_atr,
                "p75_atr_pct": p75_atr,
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
        sizing_rule: Optional[Callable[[dict[str, float]], tuple[float, str]]] = None,
        trailing_rule: Optional[Callable[[dict[str, Any]], Optional[float]]] = None,
        horizon_days: int = 15,
        tp_pct: float = 0.05,
        sl_pct: float = 0.02,
        max_entry_dev_pct: float = 0.05,
    ) -> dict[str, Any]:
        """Simulates trading with dynamic sizing and volatility trailing protection."""
        regime_lookup = self.regime_lookup
        bar_lookup = self.bar_lookup

        eval_df = df_test.copy()
        eval_df["score"] = eval_df[score_col]
        dates_sorted = sorted(eval_df["date"].unique())

        cash = float(self.initial_capital)
        peak_equity = float(self.initial_capital)
        total_eq = float(self.initial_capital)
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        daily_equity: list[tuple[date, float]] = []
        daily_allocations: list[float] = []

        open_positions: dict[str, dict[str, Any]] = {}
        completed_trades: list[SimulatedTrade11E] = []

        total_signals_generated = 0
        signals_removed_regime = 0
        dates_too_few_candidates = 0
        invalidated_gap_down = 0
        invalidated_gap_up = 0
        invalidated_excessive_dev = 0
        unfilled_suspended = 0
        unfilled_capacity = 0
        unfilled_cash = 0
        skipped_regime_sizing = 0

        pending_orders: list[dict[str, Any]] = []
        last_known_close: dict[str, float] = {}

        candidate_counts_on_eval_dates: list[int] = []
        days_with_open = 0

        regime_alloc_multipliers: dict[str, list[float]] = {
            "FAVORABLE": [],
            "MIXED": [],
            "UNFAVORABLE": [],
        }

        candidates_by_date = {d: sub for d, sub in eval_df.groupby("date", sort=False)}
        empty_day_cands = eval_df.iloc[:0]

        for curr_d in dates_sorted:
            # 1. Execute pending orders from previous trading date at Open curr_d
            if pending_orders:
                # Rank pending orders: score desc, ticker asc (deterministic capital competition)
                pending_orders.sort(key=lambda o: (-o["score"], o["ticker"]))

                for ord_info in pending_orders:
                    t = ord_info["ticker"]
                    c_close = ord_info["close_t"]
                    ord_tp = ord_info["tp_pct"]
                    ord_sl = ord_info["sl_pct"]
                    ord_h = ord_info["max_holding_days"]
                    ord_mult = ord_info["size_multiplier"]
                    ord_reg_cat = ord_info["regime_category"]
                    ord_atr = ord_info["atr_pct"]

                    # Check regime zero allocation rule
                    if ord_mult <= 0.0:
                        skipped_regime_sizing += 1
                        continue

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

                    # Pre-entry gap and deviation checks (fail-closed Variant B contract)
                    if b_open <= c_close * (1.0 - ord_sl):
                        invalidated_gap_down += 1
                        continue
                    if b_open >= c_close * (1.0 + ord_tp):
                        invalidated_gap_up += 1
                        continue
                    if abs(b_open - c_close) / c_close > max_entry_dev_pct:
                        invalidated_excessive_dev += 1
                        continue

                    # Dynamic sizing: base cap per pos = min(equity / max_pos, equity * 0.20)
                    open_val = sum(
                        pos["shares"] * last_known_close.get(pos["ticker"], pos["entry_price"])
                        for pos in open_positions.values()
                    )
                    current_equity = cash + open_val

                    base_cap_per_pos = min(
                        current_equity / self.max_positions,
                        current_equity * 0.20,
                    )
                    sized_cap_per_pos = base_cap_per_pos * ord_mult

                    fill_price = b_open * (1.0 + self.slippage_entry_bps / 10000.0)
                    raw_shares = sized_cap_per_pos / fill_price
                    max_cash_shares = cash / (fill_price * (1.0 + self.commission_buy))
                    shares_f = min(raw_shares, max_cash_shares)

                    # Lot size rounding (100 shares per IDX lot)
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
                        "initial_sl_price": fill_price * (1.0 - ord_sl),
                        "current_sl_price": fill_price * (1.0 - ord_sl),
                        "highest_watermark": fill_price,
                        "atr_pct": ord_atr,
                        "max_holding_days": ord_h,
                        "holding_days": 1,
                        "score": ord_info["score"],
                        "size_multiplier": ord_mult,
                        "regime_category": ord_reg_cat,
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
                sl_hit = bar_curr.low <= pos["current_sl_price"]
                expiry_hit = pos["holding_days"] >= pos["max_holding_days"]

                exit_reason = None
                exit_raw = None

                if tp_hit and sl_hit:
                    # Conservative contract: SL takes precedence on ambiguous same-day bar
                    is_trailing = pos["current_sl_price"] > pos["initial_sl_price"]
                    exit_reason = "TRAILING_SL" if is_trailing else "SL"
                    exit_raw = (
                        pos["current_sl_price"]
                        if pos["holding_days"] == 1
                        else (
                            bar_curr.open
                            if bar_curr.open <= pos["current_sl_price"]
                            else pos["current_sl_price"]
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
                    is_trailing = pos["current_sl_price"] > pos["initial_sl_price"]
                    exit_reason = "TRAILING_SL" if is_trailing else "SL"
                    exit_raw = (
                        float(bar_curr.open)
                        if (pos["holding_days"] > 1 and bar_curr.open <= pos["current_sl_price"])
                        else pos["current_sl_price"]
                    )
                elif expiry_hit:
                    exit_reason = "EXPIRY"
                    exit_raw = float(bar_curr.close)

                if exit_reason is not None and exit_raw is not None:
                    exit_fill = exit_raw * (1.0 - self.slippage_exit_bps / 10000.0)
                    gross_proceeds = pos["shares"] * exit_fill
                    exit_fee = gross_proceeds * self.commission_sell
                    net_proceeds = gross_proceeds - exit_fee
                    cash += net_proceeds

                    invested = pos["shares"] * pos["entry_price"] + pos["entry_fee"]
                    net_pnl = net_proceeds - invested
                    net_ret = net_pnl / invested if invested > 0 else 0.0

                    trade = SimulatedTrade11E(
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
                        size_multiplier=pos["size_multiplier"],
                        regime_category=pos["regime_category"],
                        highest_watermark=pos["highest_watermark"],
                        final_sl_price=pos["current_sl_price"],
                    )
                    completed_trades.append(trade)
                    del open_positions[t]
                else:
                    # Update watermark and causal trailing stop for NEXT day's execution
                    pos["highest_watermark"] = max(pos["highest_watermark"], float(bar_curr.high))
                    if trailing_rule is not None:
                        proposed_sl = trailing_rule(pos)
                        # Stop may tighten, but must NEVER loosen
                        if proposed_sl is not None and proposed_sl > pos["current_sl_price"]:
                            pos["current_sl_price"] = proposed_sl

                    pos["holding_days"] += 1

            # 3. Mark to market equity & continuous drawdown calculation at EOD curr_d
            for t_open in open_positions.keys():
                bar_c = bar_lookup.get((t_open, curr_d))
                if bar_c is not None and bar_c.close > 0:
                    last_known_close[t_open] = float(bar_c.close)

            eod_open_val = sum(
                pos["shares"]
                * (
                    bar_lookup[(pos["ticker"], curr_d)].close
                    if (pos["ticker"], curr_d) in bar_lookup
                    and bar_lookup[(pos["ticker"], curr_d)].close > 0
                    else pos["entry_price"]
                )
                for pos in open_positions.values()
            )
            total_eq = cash + eod_open_val
            daily_equity.append((curr_d, total_eq))

            alloc_pct = (eod_open_val / total_eq * 100.0) if total_eq > 0 else 0.0
            daily_allocations.append(alloc_pct)

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
            reg_info = regime_lookup.get(curr_d, {})

            # Apply regime filter if specified
            if regime_filter is not None and not regime_filter(reg_info):
                signals_removed_regime += n_cands
                continue

            # Determine point-in-time sizing multiplier and regime category
            if sizing_rule is not None:
                mult, reg_cat = sizing_rule(reg_info)
            else:
                mult, reg_cat = 1.0, "FAVORABLE"

            if reg_cat in regime_alloc_multipliers:
                regime_alloc_multipliers[reg_cat].append(mult)

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
                pending_orders.append(
                    {
                        "ticker": r["ticker"],
                        "signal_date": curr_d,
                        "close_t": float(r["va_entry_price"]),
                        "score": float(r["score"]),
                        "max_holding_days": horizon_days,
                        "tp_pct": tp_pct,
                        "sl_pct": sl_pct,
                        "atr_pct": float(r.get("atr_pct", 0.035)),
                        "size_multiplier": mult,
                        "regime_category": reg_cat,
                    }
                )

        # Final summary metrics for fold
        n_trades = len(completed_trades)
        wins = sum(1 for t in completed_trades if t.net_pnl > 0)
        win_rate = (wins / n_trades) if n_trades > 0 else 0.0

        tp_count = sum(1 for t in completed_trades if t.exit_reason == "TP")
        sl_count = sum(1 for t in completed_trades if t.exit_reason == "SL")
        trail_count = sum(1 for t in completed_trades if t.exit_reason == "TRAILING_SL")
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

        fold_net_port_ret_pct = ((total_eq - self.initial_capital) / self.initial_capital) * 100.0

        total_invalidated = invalidated_gap_down + invalidated_gap_up + invalidated_excessive_dev
        total_unfilled = unfilled_suspended + unfilled_capacity + unfilled_cash
        avg_candidates = (
            float(np.mean(candidate_counts_on_eval_dates))
            if candidate_counts_on_eval_dates
            else 0.0
        )
        total_gross_outlay = sum(t.shares * t.entry_price for t in completed_trades)
        port_turnover = (
            round(total_gross_outlay / self.initial_capital, 2) if self.initial_capital > 0 else 0.0
        )
        daily_turn = round(n_trades / len(dates_sorted), 4) if dates_sorted else 0.0
        time_in_mkt = round(days_with_open / len(dates_sorted) * 100.0, 2) if dates_sorted else 0.0
        eligible_cands = sum(candidate_counts_on_eval_dates)

        avg_port_alloc = float(np.mean(daily_allocations)) if daily_allocations else 0.0
        max_port_alloc = float(np.max(daily_allocations)) if daily_allocations else 0.0
        avg_cash_exp = 100.0 - avg_port_alloc

        avg_alloc_fav = (
            float(np.mean(regime_alloc_multipliers["FAVORABLE"]))
            if regime_alloc_multipliers["FAVORABLE"]
            else 0.0
        )
        avg_alloc_mix = (
            float(np.mean(regime_alloc_multipliers["MIXED"]))
            if regime_alloc_multipliers["MIXED"]
            else 0.0
        )
        avg_alloc_unf = (
            float(np.mean(regime_alloc_multipliers["UNFAVORABLE"]))
            if regime_alloc_multipliers["UNFAVORABLE"]
            else 0.0
        )

        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(total_eq, 2),
            "net_portfolio_return_pct": round(fold_net_port_ret_pct, 2),
            "total_signals": total_signals_generated,
            "completed_trades": n_trades,
            "win_rate": round(win_rate, 4),
            "tp_count": tp_count,
            "tp_rate": round(tp_count / n_trades, 4) if n_trades > 0 else 0.0,
            "sl_count": sl_count,
            "sl_rate": round(sl_count / n_trades, 4) if n_trades > 0 else 0.0,
            "trailing_stop_count": trail_count,
            "trailing_stop_rate": round(trail_count / n_trades, 4) if n_trades > 0 else 0.0,
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
            "skipped_regime_sizing": skipped_regime_sizing,
            "signals_removed_regime": signals_removed_regime,
            "dates_too_few_candidates": dates_too_few_candidates,
            "avg_daily_candidates": round(avg_candidates, 1),
            "eligible_candidates": eligible_cands,
            "portfolio_turnover": port_turnover,
            "daily_turnover": daily_turn,
            "time_in_market_pct": time_in_mkt,
            "avg_portfolio_allocation_pct": round(avg_port_alloc, 2),
            "max_portfolio_allocation_pct": round(max_port_alloc, 2),
            "avg_cash_exposure_pct": round(avg_cash_exp, 2),
            "avg_allocation_favorable": round(avg_alloc_fav, 2),
            "avg_allocation_mixed": round(avg_alloc_mix, 2),
            "avg_allocation_unfavorable": round(avg_alloc_unf, 2),
            "remaining_open_positions": len(open_positions),
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
    ) -> tuple[PolicySummary11E, list[PolicySummary11E]]:
        """Aggregates per-fold simulation runs into pooled and per-fold PolicySummary11E records."""
        per_fold_summaries: list[PolicySummary11E] = []

        all_trades: list[SimulatedTrade11E] = []
        for fold_idx, res in enumerate(fold_results, start=1):
            trades = res["trades"]
            all_trades.extend(trades)
            pf = res["profit_factor"]
            f_summary = PolicySummary11E(
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
                trailing_stop_count=res["trailing_stop_count"],
                trailing_stop_rate=res["trailing_stop_rate"],
                expiry_count=res["expiry_count"],
                expiry_rate=res["expiry_rate"],
                avg_net_return=res["avg_net_return"],
                net_portfolio_return_pct=res["net_portfolio_return_pct"],
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
                skipped_regime_sizing=res["skipped_regime_sizing"],
                signals_removed_regime=res["signals_removed_regime"],
                dates_too_few_candidates=res["dates_too_few_candidates"],
                avg_daily_candidates=res["avg_daily_candidates"],
                avg_holding_days=res["avg_holding_days"],
                eligible_candidates=res.get("eligible_candidates", 0),
                portfolio_turnover=res.get("portfolio_turnover", 0.0),
                daily_turnover=res.get("daily_turnover", 0.0),
                time_in_market_pct=res.get("time_in_market_pct", 0.0),
                avg_portfolio_allocation_pct=res.get("avg_portfolio_allocation_pct", 0.0),
                max_portfolio_allocation_pct=res.get("max_portfolio_allocation_pct", 0.0),
                avg_cash_exposure_pct=res.get("avg_cash_exposure_pct", 100.0),
                avg_allocation_favorable=res.get("avg_allocation_favorable", 0.0),
                avg_allocation_mixed=res.get("avg_allocation_mixed", 0.0),
                avg_allocation_unfavorable=res.get("avg_allocation_unfavorable", 0.0),
                remaining_open_positions=res.get("remaining_open_positions", 0),
            )
            per_fold_summaries.append(f_summary)

        # Pooled stats across all folds
        tot_trades = len(all_trades)
        wins = sum(1 for t in all_trades if t.net_pnl > 0)
        win_rate = (wins / tot_trades) if tot_trades > 0 else 0.0
        tp_tot = sum(1 for t in all_trades if t.exit_reason == "TP")
        sl_tot = sum(1 for t in all_trades if t.exit_reason == "SL")
        trail_tot = sum(1 for t in all_trades if t.exit_reason == "TRAILING_SL")
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

        # Continuous compounding equity curve across chained test folds
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
            continuous_net_port_ret_pct = round((scale - 1.0) * 100.0, 2)
        else:
            continuous_dd = worst_dd
            continuous_net_port_ret_pct = 0.0

        pooled_summary = PolicySummary11E(
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
            trailing_stop_count=trail_tot,
            trailing_stop_rate=round(trail_tot / tot_trades, 4) if tot_trades > 0 else 0.0,
            expiry_count=exp_tot,
            expiry_rate=round(exp_tot / tot_trades, 4) if tot_trades > 0 else 0.0,
            avg_net_return=round(avg_ret, 4),
            net_portfolio_return_pct=continuous_net_port_ret_pct,
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
            skipped_regime_sizing=sum(r["skipped_regime_sizing"] for r in fold_results),
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
            avg_portfolio_allocation_pct=round(
                float(np.mean([r.get("avg_portfolio_allocation_pct", 0.0) for r in fold_results])),
                2,
            )
            if fold_results
            else 0.0,
            max_portfolio_allocation_pct=round(
                float(np.max([r.get("max_portfolio_allocation_pct", 0.0) for r in fold_results])), 2
            )
            if fold_results
            else 0.0,
            avg_cash_exposure_pct=round(
                float(np.mean([r.get("avg_cash_exposure_pct", 100.0) for r in fold_results])), 2
            )
            if fold_results
            else 100.0,
            avg_allocation_favorable=round(
                float(np.mean([r.get("avg_allocation_favorable", 0.0) for r in fold_results])), 2
            )
            if fold_results
            else 0.0,
            avg_allocation_mixed=round(
                float(np.mean([r.get("avg_allocation_mixed", 0.0) for r in fold_results])), 2
            )
            if fold_results
            else 0.0,
            avg_allocation_unfavorable=round(
                float(np.mean([r.get("avg_allocation_unfavorable", 0.0) for r in fold_results])), 2
            )
            if fold_results
            else 0.0,
            remaining_open_positions=sum(
                r.get("remaining_open_positions", 0) for r in fold_results
            ),
        )

        return pooled_summary, per_fold_summaries


# =============================================================================
# PREDECLARED SIZING RULES (EXPERIMENT A)
# =============================================================================


def sizing_fixed_control(reg: dict[str, float]) -> tuple[float, str]:
    """Control: Fixed equal allocation (1.0x / 20% equity cap) across all regimes."""
    return 1.0, "FAVORABLE"


def sizing_conservative_binary(reg: dict[str, float]) -> tuple[float, str]:
    """Conservative binary: 1.0x in bull trend (ihsg_vs_ema20 > 0), 0.0x in bear trend."""
    ema = reg.get("ihsg_vs_ema20", 0.0)
    if ema > 0.0:
        return 1.0, "FAVORABLE"
    return 0.0, "UNFAVORABLE"


def sizing_three_tier_regime(reg: dict[str, float]) -> tuple[float, str]:
    """Three-tier sizing: Favorable=1.0x, Mixed=0.5x, Unfavorable=0.0x.

    - Favorable: Trend > 0 and Breadth >= 0.50
    - Mixed: (Trend > 0 and Breadth < 0.50) or (Trend <= 0 and Breadth >= 0.50)
    - Unfavorable: Trend <= 0 and Breadth < 0.50
    """
    ema = reg.get("ihsg_vs_ema20", 0.0)
    brd = reg.get("market_breadth", 0.50)
    if ema > 0.0 and brd >= 0.50:
        return 1.0, "FAVORABLE"
    elif (ema > 0.0 and brd < 0.50) or (ema <= 0.0 and brd >= 0.50):
        return 0.5, "MIXED"
    else:
        return 0.0, "UNFAVORABLE"


def sizing_smooth_conviction(reg: dict[str, float]) -> tuple[float, str]:
    """Smooth bounded sizing: linear ramp from -2% (0.0x) to +2% (1.0x) on ihsg_vs_ema20."""
    ema = reg.get("ihsg_vs_ema20", 0.0)
    w = float(np.clip((ema + 0.02) / 0.04, 0.0, 1.0))
    w = round(w, 2)
    if w >= 0.75:
        cat = "FAVORABLE"
    elif w >= 0.25:
        cat = "MIXED"
    else:
        cat = "UNFAVORABLE"
    return w, cat


# =============================================================================
# PREDECLARED TRAILING STOP RULES (EXPERIMENT B)
# =============================================================================


def make_breakeven_ratchet_rule(activation_pct: float = 0.025, friction_pct: float = 0.0050):
    """Ratchet stop to breakeven + friction once price reaches activation_pct."""

    def rule(pos: dict[str, Any]) -> Optional[float]:
        if pos["highest_watermark"] >= pos["entry_price"] * (1.0 + activation_pct):
            return pos["entry_price"] * (1.0 + friction_pct)
        return None

    return rule


def make_atr_trailing_rule(atr_multiple: float = 1.5, activation_pct: float = 0.025):
    """Trailing stop based on causal ATR multiple, activated after favorable move."""

    def rule(pos: dict[str, Any]) -> Optional[float]:
        if pos["highest_watermark"] >= pos["entry_price"] * (1.0 + activation_pct):
            atr_pct = pos.get("atr_pct", 0.035)
            bounded_atr = float(np.clip(atr_pct, 0.015, 0.06))
            trail_distance = atr_multiple * bounded_atr
            return pos["highest_watermark"] * (1.0 - trail_distance)
        return None

    return rule


def make_stepped_profit_lock_rule():
    """Stepped profit protection: +2.5% move locks breakeven (+0.5%), +4.0% move locks +2.0%."""

    def rule(pos: dict[str, Any]) -> Optional[float]:
        if pos["highest_watermark"] >= pos["entry_price"] * 1.040:
            return pos["entry_price"] * 1.020
        elif pos["highest_watermark"] >= pos["entry_price"] * 1.025:
            return pos["entry_price"] * 1.005
        return None

    return rule


# =============================================================================
# COORDINATION OF ALL PHASE 11E EXPERIMENTS
# =============================================================================


def run_all_phase11e_experiments(
    engine: Optional[SizingTrailingEvaluationEngine] = None,
    output_dir: Union[str, Path] = "artifacts/phase_11e",
) -> dict[str, Any]:
    """Coordinates and executes all Phase 11E experiments across both price modes."""
    if engine is None:
        engine = SizingTrailingEvaluationEngine()

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    all_pooled_summaries: list[dict[str, Any]] = []
    all_fold_summaries: list[dict[str, Any]] = []
    sample_trades_list: list[dict[str, Any]] = []

    results_by_mode: dict[str, Any] = {}

    for mode in ["LOW_PRICE", "HIGHER_PRICE"]:
        df_mode = engine.load_mode_dataset(mode)
        _ = engine.compute_fold_training_stats(df_mode)

        # Baseline Primary Reference Model ID:
        # LOW_PRICE: lgb_regressor (primary Phase 11C winner)
        # HIGHER_PRICE: lgb_full (primary Phase 11C winner)
        primary_score_col = "pred_return_lgb" if mode == "LOW_PRICE" else "prob_lgb_full"
        primary_model_name = "lgb_regressor" if mode == "LOW_PRICE" else "lgb_full"

        mode_pooled: list[PolicySummary11E] = []
        mode_folds: list[PolicySummary11E] = []

        # =====================================================================
        # 1. FROZEN REFERENCE BASELINES (Phase 11D Replication)
        # =====================================================================
        ref_configs = [
            (
                "ref_h15_fixed_control",
                "BASELINE",
                "Phase 11D Frozen Baseline: H=15 Fixed Size (Top 5 fixed, TP +5%, SL -2%)",
                None,
                None,
                None,
                15,
                0.05,
                0.02,
                5,
            ),
            (
                "ref_bull_filter_alone",
                "BASELINE",
                "Phase 11D Comparator: Bull Filter (IHSG > EMA20, Fixed Size, TP +5%, SL -2%)",
                None,
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                None,
                15,
                0.05,
                0.02,
                5,
            ),
        ]
        if mode == "LOW_PRICE":
            ref_configs.append(
                (
                    "ref_combined_phase11d",
                    "BASELINE",
                    "Phase 11D Combined Policy: Top 3%, Bull Filter, H=15, TP +6%, SL -2%",
                    0.03,
                    lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                    None,
                    15,
                    0.06,
                    0.02,
                    5,
                )
            )
        else:
            ref_configs.append(
                (
                    "ref_combined_phase11d_top1",
                    "BASELINE",
                    "Phase 11D Combined Policy: Top 1%, Bull Filter, H=15, TP +6%, SL -2%",
                    0.01,
                    lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                    None,
                    15,
                    0.06,
                    0.02,
                    5,
                )
            )
            ref_configs.append(
                (
                    "ref_combined_phase11d_top3",
                    "BASELINE",
                    "Phase 11D Combined Policy: Top 3%, Bull Filter, H=15, TP +6%, SL -2%",
                    0.03,
                    lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                    None,
                    15,
                    0.06,
                    0.02,
                    5,
                )
            )

        for p_id, exp_tag, desc, top_k, r_filt, t_rule, h_days, tp_v, sl_v, top_n in ref_configs:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=top_k,
                    top_n_per_day=top_n,
                    min_candidates=10,
                    regime_filter=r_filt,
                    sizing_rule=sizing_fixed_control,
                    trailing_rule=t_rule,
                    horizon_days=h_days,
                    tp_pct=tp_v,
                    sl_pct=sl_v,
                )
                f_runs.append(res)
                if p_id == "ref_h15_fixed_control":
                    for t in res["trades"][:5]:
                        sample_trades_list.append(
                            {"mode": mode, "policy_id": p_id, "fold": f, **asdict(t)}
                        )

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment=exp_tag,
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 2. EXPERIMENT A: DYNAMIC CONVICTION SIZING
        # =====================================================================
        # Evaluated on baseline model (Top 5 fixed, H=15, TP +5%, SL -2%)
        sizing_policies = [
            (
                "exp_a_size_fixed_control",
                sizing_fixed_control,
                "Experiment A Control: Fixed Sizing (1.0x / 20% equity cap)",
            ),
            (
                "exp_a_size_conservative",
                sizing_conservative_binary,
                "Experiment A: Conservative Binary (1.0x Bull Trend, 0.0x Bear Trend)",
            ),
            (
                "exp_a_size_three_tier",
                sizing_three_tier_regime,
                "Experiment A: Three-Tier Regime Sizing (1.0x Fav, 0.5x Mix, 0.0x Unfav)",
            ),
            (
                "exp_a_size_smooth",
                sizing_smooth_conviction,
                "Experiment A: Smooth Conviction Sizing (Linear ramp on IHSG vs EMA20)",
            ),
        ]

        for p_id, s_rule, desc in sizing_policies:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=None,
                    sizing_rule=s_rule,
                    trailing_rule=None,
                    horizon_days=15,
                    tp_pct=0.05,
                    sl_pct=0.02,
                )
                f_runs.append(res)
                if p_id in ("exp_a_size_three_tier", "exp_a_size_smooth"):
                    for t in res["trades"][:5]:
                        sample_trades_list.append(
                            {"mode": mode, "policy_id": p_id, "fold": f, **asdict(t)}
                        )

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="EXP_A_SIZING",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 3. EXPERIMENT B: VOLATILITY-BASED TRAILING PROTECTION
        # =====================================================================
        # Evaluated on baseline model (Fixed Sizing 1.0x, Top 5 fixed, H=15, TP +5%, SL -2%)
        trailing_policies = [
            (
                "exp_b_trail_control",
                None,
                "Experiment B Control: Fixed Exit Without Trailing Protection",
            ),
            (
                "exp_b_trail_breakeven_25",
                make_breakeven_ratchet_rule(0.025, 0.0050),
                "Experiment B: Breakeven Ratchet After +2.5% Move (Locks +0.50% Net)",
            ),
            (
                "exp_b_trail_breakeven_30",
                make_breakeven_ratchet_rule(0.030, 0.0050),
                "Experiment B: Breakeven Ratchet After +3.0% Move (Locks +0.50% Net)",
            ),
            (
                "exp_b_trail_atr_1_0x",
                make_atr_trailing_rule(1.0, 0.025),
                "Experiment B: Causal ATR Trailing Stop (1.0x ATR distance, activated at +2.5%)",
            ),
            (
                "exp_b_trail_atr_1_5x",
                make_atr_trailing_rule(1.5, 0.025),
                "Experiment B: Causal ATR Trailing Stop (1.5x ATR distance, activated at +2.5%)",
            ),
            (
                "exp_b_trail_stepped_lock",
                make_stepped_profit_lock_rule(),
                "Experiment B: Stepped Profit Lock (+2.5% -> +0.5% BE, +4.0% -> +2.0% lock)",
            ),
        ]

        for p_id, t_rule, desc in trailing_policies:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=None,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=None,
                    sizing_rule=sizing_fixed_control,
                    trailing_rule=t_rule,
                    horizon_days=15,
                    tp_pct=0.05,
                    sl_pct=0.02,
                )
                f_runs.append(res)
                if p_id in ("exp_b_trail_breakeven_25", "exp_b_trail_atr_1_0x"):
                    for t in res["trades"][:5]:
                        sample_trades_list.append(
                            {"mode": mode, "policy_id": p_id, "fold": f, **asdict(t)}
                        )

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="EXP_B_TRAILING",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # Also evaluate Trailing Stops on Phase 11D Combined Policy Comparator
        comb_top_k = 0.03 if mode == "LOW_PRICE" else 0.01
        for p_sub_id, t_rule, t_desc in [
            (
                "comb_trail_control",
                None,
                "Combined Policy Control: Fixed Exits (TP +6%, SL -2%, no trailing)",
            ),
            (
                "comb_trail_breakeven_25",
                make_breakeven_ratchet_rule(0.025, 0.0050),
                "Combined Policy + Breakeven Ratchet (+2.5% move -> +0.50% net)",
            ),
            (
                "comb_trail_atr_1_0x",
                make_atr_trailing_rule(1.0, 0.025),
                "Combined Policy + ATR 1.0x Trailing Stop",
            ),
            (
                "comb_trail_stepped_lock",
                make_stepped_profit_lock_rule(),
                "Combined Policy + Stepped Profit Lock",
            ),
        ]:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=comb_top_k,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                    sizing_rule=sizing_fixed_control,
                    trailing_rule=t_rule,
                    horizon_days=15,
                    tp_pct=0.06,
                    sl_pct=0.02,
                )
                f_runs.append(res)

            pooled, per_f = engine.aggregate_folds(
                policy_id=f"exp_b_on_{p_sub_id}",
                experiment="EXP_B_TRAILING",
                description=t_desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

        # =====================================================================
        # 4. EXPERIMENT C: COMBINED SIZING & TRAILING PROTECTION
        # =====================================================================
        # Compare Sizing Alone vs Trailing Alone vs Sizing + Trailing Combined
        # on both Baseline and Phase 11D Combined configurations.
        comb_eval_matrix = [
            # Baseline setting (All regimes eligible, Top 5 fixed, TP +5%, SL -2%)
            (
                "comb_baseline_sizing_alone",
                "Baseline + Three-Tier Sizing Alone (Fixed Exit)",
                None,
                None,
                sizing_three_tier_regime,
                None,
                15,
                0.05,
                0.02,
            ),
            (
                "comb_baseline_trailing_alone",
                "Baseline + Breakeven Ratchet Alone (Fixed Size)",
                None,
                None,
                sizing_fixed_control,
                make_breakeven_ratchet_rule(0.025, 0.0050),
                15,
                0.05,
                0.02,
            ),
            (
                "comb_baseline_size_and_be_ratchet",
                "Baseline + Three-Tier Sizing + Breakeven Ratchet",
                None,
                None,
                sizing_three_tier_regime,
                make_breakeven_ratchet_rule(0.025, 0.0050),
                15,
                0.05,
                0.02,
            ),
            (
                "comb_baseline_size_and_stepped_lock",
                "Baseline + Three-Tier Sizing + Stepped Profit Lock",
                None,
                None,
                sizing_three_tier_regime,
                make_stepped_profit_lock_rule(),
                15,
                0.05,
                0.02,
            ),
            # Phase 11D Combined Policy setting (Bull Trend filter, Top 3% / Top 1%, TP +6%, SL -2%)
            (
                "comb_selective_sizing_alone",
                "Phase 11D Selective + Three-Tier Sizing (Fixed Exit)",
                comb_top_k,
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                sizing_three_tier_regime,
                None,
                15,
                0.06,
                0.02,
            ),
            (
                "comb_selective_trailing_alone",
                "Phase 11D Selective + Breakeven Ratchet Alone (Fixed Size)",
                comb_top_k,
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                sizing_fixed_control,
                make_breakeven_ratchet_rule(0.025, 0.0050),
                15,
                0.06,
                0.02,
            ),
            (
                "comb_selective_size_and_be_ratchet",
                "Phase 11D Selective + Three-Tier Sizing + Breakeven Ratchet",
                comb_top_k,
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                sizing_three_tier_regime,
                make_breakeven_ratchet_rule(0.025, 0.0050),
                15,
                0.06,
                0.02,
            ),
            (
                "comb_selective_size_and_stepped_lock",
                "Phase 11D Selective + Three-Tier Sizing + Stepped Profit Lock",
                comb_top_k,
                lambda r: r.get("ihsg_vs_ema20", 0.0) > 0.0,
                sizing_three_tier_regime,
                make_stepped_profit_lock_rule(),
                15,
                0.06,
                0.02,
            ),
        ]

        for p_id, desc, top_k, r_filt, s_rule, t_rule, h_days, tp_v, sl_v in comb_eval_matrix:
            f_runs = []
            for f in [1, 2, 3]:
                sub = df_mode[(df_mode["fold"] == f) & (df_mode["horizon"] == 15)]
                res = engine.simulate_policy(
                    df_test=sub,
                    score_col=primary_score_col,
                    top_k_pct=top_k,
                    top_n_per_day=5,
                    min_candidates=10,
                    regime_filter=r_filt,
                    sizing_rule=s_rule,
                    trailing_rule=t_rule,
                    horizon_days=h_days,
                    tp_pct=tp_v,
                    sl_pct=sl_v,
                )
                f_runs.append(res)
                if "size_and" in p_id:
                    for t in res["trades"][:5]:
                        sample_trades_list.append(
                            {"mode": mode, "policy_id": p_id, "fold": f, **asdict(t)}
                        )

            pooled, per_f = engine.aggregate_folds(
                policy_id=p_id,
                experiment="COMBINED",
                description=desc,
                mode=mode,
                model_id=primary_model_name,
                fold_results=f_runs,
            )
            mode_pooled.append(pooled)
            mode_folds.extend(per_f)

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
        ("EXP_A_SIZING", "experiment_a_sizing_summary.csv"),
        ("EXP_B_TRAILING", "experiment_b_trailing_summary.csv"),
        ("COMBINED", "experiment_c_combined_summary.csv"),
    ]:
        sub_df = df_all_pooled[df_all_pooled["experiment"] == exp_id]
        sub_df.to_csv(out_p / filename, index=False)

    # 3. Regime allocation breakdown CSV
    regime_cols = [
        "mode",
        "experiment",
        "policy_id",
        "completed_trades",
        "skipped_regime_sizing",
        "avg_portfolio_allocation_pct",
        "max_portfolio_allocation_pct",
        "avg_cash_exposure_pct",
        "avg_allocation_favorable",
        "avg_allocation_mixed",
        "avg_allocation_unfavorable",
    ]
    df_all_pooled[regime_cols].to_csv(out_p / "regime_allocation_breakdown.csv", index=False)

    # 4. Sample trades CSV
    pd.DataFrame(sample_trades_list).to_csv(
        out_p / "phase_11e_selected_trades_sample.csv", index=False
    )

    exported_files = [
        str(out_p / "policy_summary_all.csv"),
        str(out_p / "policy_summary_by_fold.csv"),
        str(out_p / "baseline_reference_summary.csv"),
        str(out_p / "experiment_a_sizing_summary.csv"),
        str(out_p / "experiment_b_trailing_summary.csv"),
        str(out_p / "experiment_c_combined_summary.csv"),
        str(out_p / "regime_allocation_breakdown.csv"),
        str(out_p / "phase_11e_selected_trades_sample.csv"),
        str(out_p / "policy_metrics_LOW_PRICE.json"),
        str(out_p / "policy_metrics_HIGHER_PRICE.json"),
    ]

    return {
        "results_by_mode": results_by_mode,
        "pooled_df": df_all_pooled,
        "folds_df": df_all_folds,
        "exported_files": exported_files,
    }
