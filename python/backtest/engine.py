import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import numpy as np

from python.backtest.metrics import compute_backtest_report
from python.common.types import (
    BacktestConfig,
    BacktestReport,
    DailyBar,
    EquityPoint,
    FeatureRecord,
    Signal,
    SignalAction,
    TradeRecord,
    classify_price_mode,
)
from python.features.engine import FeatureEngine
from python.models.dataset import DEFAULT_FEATURE_COLUMNS


@dataclass
class _ActivePosition:
    ticker: str
    signal_date: date
    entry_date: date
    shares: int
    entry_price: float
    raw_entry_price: float
    tp_price: float
    sl_price: float
    entry_fee: float
    entry_slippage: float
    highest_seen: float
    lowest_seen: float
    holding_days: int
    signal_prob: Optional[float] = None
    last_close: float = 0.0
    max_holding_days: int = 10
    mode: Optional[str] = None


@dataclass
class _PendingOrder:
    ticker: str
    signal_date: date
    signal_prob: float
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    max_holding_days: Optional[int] = None
    mode: Optional[str] = None


class BacktestEngine:
    """Discrete-event backtest simulator with realistic Indonesian equity market friction.

    Enforces strict causality (Day t signal executes on Day t+1 open), zero future lookahead,
    broker fees (buy 0.15%, sell 0.25%), slippage, lot-size rounding (100 shares),
    and risk-based/fractional position sizing constraints.
    """

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self.config = config or BacktestConfig()

    def _extract_feature_vector(
        self, record: FeatureRecord, feature_names: list[str]
    ) -> list[float]:
        vec: list[float] = []
        for col in feature_names:
            val = getattr(record, col, None)
            if val is not None and math.isfinite(val):
                vec.append(float(val))
            else:
                vec.append(0.0)
        return vec

    def _predict_probabilities(
        self,
        model: Any,
        records: list[FeatureRecord],
        feature_names: list[str],
    ) -> np.ndarray:
        if not records:
            return np.empty((0,), dtype=np.float64)

        X = np.array(
            [self._extract_feature_vector(r, feature_names) for r in records],
            dtype=np.float64,
        )

        if hasattr(model, "predict_probability"):
            probs = model.predict_probability(X)
        elif hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)
            if hasattr(model, "classes_"):
                classes = list(model.classes_)
                if 1 in classes:
                    idx = classes.index(1)
                    probs = proba[:, idx]
                elif len(classes) == 1 and classes[0] == 0:
                    probs = np.zeros(len(proba), dtype=np.float64)
                else:
                    probs = proba[:, -1]
            else:
                probs = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
        elif hasattr(model, "predict"):
            probs = model.predict(X).astype(np.float64)
        else:
            raise TypeError("Provided model does not have a supported predict method.")

        return np.clip(probs, 0.0, 1.0)

    def run(
        self,
        bars: list[DailyBar],
        signals: Optional[list[Signal]] = None,
        model: Optional[Any] = None,
        feature_names: Optional[list[str]] = None,
        universe_features: Optional[list[FeatureRecord]] = None,
        mode: Optional[str] = None,
    ) -> BacktestReport:
        """Executes discrete-event backtest simulation across all bars."""
        if not bars:
            today = date.today()
            return compute_backtest_report(
                config=self.config,
                trades=[],
                equity_curve=[],
                start_date=today,
                end_date=today,
            )

        # Normalize tickers and group bars by date and ticker
        bars_by_date: dict[date, dict[str, DailyBar]] = defaultdict(dict)
        bars_by_ticker: dict[str, list[DailyBar]] = defaultdict(list)

        for b in bars:
            clean_ticker = b.ticker.strip().upper().removesuffix(".JK")
            normalized_bar = DailyBar(
                ticker=clean_ticker,
                date=b.date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                value=b.value,
            )
            bars_by_date[b.date][clean_ticker] = normalized_bar
            bars_by_ticker[clean_ticker].append(normalized_bar)

        for t in bars_by_ticker:
            bars_by_ticker[t].sort(key=lambda x: x.date)

        sorted_dates = sorted(bars_by_date.keys())
        start_date = sorted_dates[0]
        end_date = sorted_dates[-1]

        # Prepare features if model prediction is requested
        model_feat_names = (
            feature_names or getattr(model, "feature_names_", None) or DEFAULT_FEATURE_COLUMNS
        )
        features_by_date_ticker: dict[date, dict[str, FeatureRecord]] = defaultdict(dict)

        if model is not None:
            if universe_features is not None:
                for f in universe_features:
                    features_by_date_ticker[f.date][f.ticker] = f
            else:
                engine = FeatureEngine()
                computed_features = engine.compute_universe_features(bars_by_ticker)
                for t_feats in computed_features.values():
                    for f in t_feats:
                        features_by_date_ticker[f.date][f.ticker] = f

        # Map pre-computed signals if provided
        signals_by_date: dict[date, list[Signal]] = defaultdict(list)
        if signals is not None:
            for s in signals:
                clean_s_tick = s.ticker.strip().upper().removesuffix(".JK")
                signals_by_date[s.signal_date].append(
                    Signal(
                        ticker=clean_s_tick,
                        signal_date=s.signal_date,
                        action=s.action,
                        entry_price=s.entry_price,
                        target_price=s.target_price,
                        stop_loss=s.stop_loss,
                        max_holding_days=s.max_holding_days,
                        probability=s.probability,
                        model_version=s.model_version,
                        score=s.score,
                    )
                )

        cash = float(self.config.initial_capital)
        peak_equity = cash
        open_positions: dict[str, _ActivePosition] = {}
        closed_trades: list[TradeRecord] = []
        equity_curve: list[EquityPoint] = []
        pending_orders: list[_PendingOrder] = []

        for d in sorted_dates:
            day_bars = bars_by_date[d]

            # -------------------------------------------------------------
            # STEP 1: Morning Execution of Pending Orders from Day d-1
            # -------------------------------------------------------------
            if pending_orders:
                # Rank candidates by model probability descending
                pending_orders.sort(key=lambda o: o.signal_prob, reverse=True)

                for order in pending_orders:
                    if len(open_positions) >= self.config.max_concurrent_positions:
                        break
                    if order.ticker in open_positions:
                        continue
                    if order.ticker not in day_bars:
                        continue

                    bar = day_bars[order.ticker]
                    if bar.volume <= 0:
                        continue
                    raw_entry = (
                        bar.open if self.config.entry_execution == "next_open" else bar.close
                    )
                    if raw_entry <= 0:
                        continue
                    entry_fill_price = raw_entry * (1.0 + self.config.slippage_bps / 10000.0)

                    # Mark-to-market equity for position sizing
                    open_pos_val = sum(
                        pos.shares
                        * (
                            day_bars[t].close
                            if (t in day_bars and day_bars[t].volume > 0)
                            else pos.last_close
                        )
                        for t, pos in open_positions.items()
                    )
                    current_equity = cash + open_pos_val
                    if current_equity <= 0:
                        break

                    # Position sizing calculation
                    if self.config.position_sizing_method == "risk_based":
                        risk_budget = current_equity * self.config.risk_per_trade_pct
                        risk_per_share = entry_fill_price * self.config.sl_pct
                        raw_shares = (risk_budget / risk_per_share) if risk_per_share > 0 else 0.0
                        max_cap_shares = (
                            current_equity * self.config.max_position_pct
                        ) / entry_fill_price
                        shares_f = min(raw_shares, max_cap_shares)
                    elif self.config.position_sizing_method == "fixed_fractional":
                        shares_f = (
                            current_equity * self.config.max_position_pct
                        ) / entry_fill_price
                    elif self.config.position_sizing_method == "equal_weight":
                        cap_per_pos = min(
                            current_equity / self.config.max_concurrent_positions,
                            current_equity * self.config.max_position_pct,
                        )
                        shares_f = cap_per_pos / entry_fill_price
                    else:
                        shares_f = (
                            current_equity * self.config.risk_per_trade_pct
                        ) / entry_fill_price

                    # Available cash constraint
                    max_cash_shares = cash / (entry_fill_price * (1.0 + self.config.commission_buy))
                    shares_f = min(shares_f, max_cash_shares)

                    # IDX Lot size rounding (1 lot = 100 shares)
                    shares = int(shares_f // self.config.lot_size) * self.config.lot_size
                    if shares < self.config.lot_size:
                        continue

                    # Total cash outlay
                    pos_gross = shares * entry_fill_price
                    entry_fee = pos_gross * self.config.commission_buy
                    entry_outlay = pos_gross + entry_fee

                    while entry_outlay > cash and shares >= self.config.lot_size:
                        shares -= self.config.lot_size
                        pos_gross = shares * entry_fill_price
                        entry_fee = pos_gross * self.config.commission_buy
                        entry_outlay = pos_gross + entry_fee

                    if shares < self.config.lot_size:
                        continue

                    cash -= entry_outlay
                    entry_slippage_cost = shares * (entry_fill_price - raw_entry)

                    tp_price = entry_fill_price * (1.0 + self.config.tp_pct)
                    sl_price = entry_fill_price * (1.0 - self.config.sl_pct)

                    open_positions[order.ticker] = _ActivePosition(
                        ticker=order.ticker,
                        signal_date=order.signal_date,
                        entry_date=d,
                        shares=shares,
                        entry_price=entry_fill_price,
                        raw_entry_price=raw_entry,
                        tp_price=tp_price,
                        sl_price=sl_price,
                        entry_fee=entry_fee,
                        entry_slippage=entry_slippage_cost,
                        highest_seen=bar.high,
                        lowest_seen=bar.low,
                        holding_days=1,
                        signal_prob=order.signal_prob,
                        last_close=bar.close,
                        max_holding_days=self.config.max_holding_days,
                        mode=order.mode,
                    )

                pending_orders.clear()

            # -------------------------------------------------------------
            # STEP 2: Intraday Evaluation & Barrier Hits on Day d
            # -------------------------------------------------------------
            active_tickers = list(open_positions.keys())
            for ticker in active_tickers:
                pos = open_positions[ticker]
                if ticker not in day_bars or day_bars[ticker].volume <= 0:
                    # Stock not traded on Day d, cannot exit intraday
                    pos.holding_days += 1
                    continue

                bar = day_bars[ticker]
                pos.last_close = bar.close
                pos.highest_seen = max(pos.highest_seen, bar.high)
                pos.lowest_seen = min(pos.lowest_seen, bar.low)

                tp_hit = bar.high >= pos.tp_price
                sl_hit = bar.low <= pos.sl_price

                exit_reason: Optional[str] = None
                raw_exit_price: Optional[float] = None

                if tp_hit and sl_hit:
                    # Intraday ambiguity
                    if bar.open >= pos.tp_price:
                        exit_reason = "TP"
                        raw_exit_price = float(bar.open)
                    elif bar.open <= pos.sl_price:
                        exit_reason = "SL"
                        raw_exit_price = float(bar.open)
                    else:
                        if self.config.ambiguity_policy == "conservative":
                            exit_reason = "SL"
                            raw_exit_price = pos.sl_price
                        elif self.config.ambiguity_policy == "optimistic":
                            exit_reason = "TP"
                            raw_exit_price = pos.tp_price
                        else:
                            exit_reason = "AMBIGUOUS"
                            raw_exit_price = float(bar.close)
                elif tp_hit:
                    exit_reason = "TP"
                    raw_exit_price = float(bar.open) if bar.open >= pos.tp_price else pos.tp_price
                elif sl_hit:
                    exit_reason = "SL"
                    raw_exit_price = float(bar.open) if bar.open <= pos.sl_price else pos.sl_price
                elif pos.holding_days >= pos.max_holding_days:
                    exit_reason = "EXPIRY"
                    raw_exit_price = float(bar.close)

                if exit_reason is not None and raw_exit_price is not None:
                    # Execute sell with slippage and commission
                    exit_fill_price = raw_exit_price * (1.0 - self.config.slippage_bps / 10000.0)
                    pos_gross_exit = pos.shares * exit_fill_price
                    exit_fee = pos_gross_exit * self.config.commission_sell
                    exit_slippage_cost = pos.shares * (raw_exit_price - exit_fill_price)
                    proceeds = pos_gross_exit - exit_fee
                    cash += proceeds

                    gross_pnl = pos.shares * (raw_exit_price - pos.raw_entry_price)
                    total_slippage = pos.entry_slippage + exit_slippage_cost
                    net_pnl = proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                    invested = pos.shares * pos.entry_price + pos.entry_fee
                    net_return = (net_pnl / invested) if invested > 0 else 0.0

                    mfe = (pos.highest_seen - pos.entry_price) / pos.entry_price
                    mae = (pos.lowest_seen - pos.entry_price) / pos.entry_price

                    trade = TradeRecord(
                        trade_id=f"T_{pos.ticker}_{pos.entry_date}_{d}",
                        ticker=pos.ticker,
                        signal_date=pos.signal_date,
                        entry_date=pos.entry_date,
                        exit_date=d,
                        shares=pos.shares,
                        entry_price=pos.entry_price,
                        exit_price=exit_fill_price,
                        position_value=pos.shares * pos.entry_price,
                        entry_fee=pos.entry_fee,
                        exit_fee=exit_fee,
                        slippage_cost=total_slippage,
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        net_return=net_return,
                        exit_reason=exit_reason,
                        holding_days=pos.holding_days,
                        mfe=mfe,
                        mae=mae,
                        signal_probability=pos.signal_prob,
                        mode=pos.mode,
                    )
                    closed_trades.append(trade)
                    del open_positions[ticker]
                else:
                    pos.holding_days += 1

            # -------------------------------------------------------------
            # STEP 3: Mark-To-Market Equity Curve at Close of Day d
            # -------------------------------------------------------------
            eod_positions_val = sum(
                pos.shares
                * (
                    day_bars[t].close
                    if (t in day_bars and day_bars[t].volume > 0)
                    else pos.last_close
                )
                for t, pos in open_positions.items()
            )

            total_equity = cash + eod_positions_val
            if total_equity > peak_equity:
                peak_equity = total_equity
            dd_pct = (
                max(0.0, (peak_equity - total_equity) / peak_equity) if peak_equity > 0 else 0.0
            )

            equity_curve.append(
                EquityPoint(
                    date=d,
                    cash=cash,
                    positions_value=eod_positions_val,
                    total_equity=total_equity,
                    drawdown_pct=dd_pct,
                    open_positions_count=len(open_positions),
                )
            )

            # -------------------------------------------------------------
            # STEP 4: Evening Signal Generation on Day d for Day d+1
            # -------------------------------------------------------------
            if d != end_date:
                # 4a. If explicit signals supplied
                if signals is not None:
                    if signals_by_date.get(d):
                        for sig in signals_by_date[d]:
                            if (
                                sig.action == SignalAction.BUY
                                and sig.probability >= self.config.probability_threshold
                            ):
                                sig_mode = (
                                    getattr(sig, "mode_id", None)
                                    or getattr(sig, "mode", None)
                                )
                                if sig_mode is None:
                                    has_bar = sig.ticker in day_bars
                                    ref_price = (
                                        day_bars[sig.ticker].close
                                        if (has_bar and day_bars[sig.ticker].close > 0)
                                        else sig.entry_price
                                    )
                                    sig_mode = classify_price_mode(ref_price)
                                if sig_mode in ("EXCLUDED_BELOW_50", "INVALID"):
                                    continue
                                if mode is not None and sig_mode != mode:
                                    continue
                                pending_orders.append(
                                    _PendingOrder(
                                        ticker=sig.ticker,
                                        signal_date=d,
                                        signal_prob=sig.probability,
                                        target_price=sig.target_price,
                                        stop_loss=sig.stop_loss,
                                        max_holding_days=sig.max_holding_days,
                                        mode=sig_mode,
                                    )
                                )

                # 4b. If model supplied, evaluate features available on Day d
                elif model is not None and features_by_date_ticker.get(d):
                    day_features = list(features_by_date_ticker[d].values())
                    if day_features:
                        probs = self._predict_probabilities(
                            model=model,
                            records=day_features,
                            feature_names=model_feat_names,
                        )
                        for r, prob in zip(day_features, probs, strict=True):
                            if prob >= self.config.probability_threshold:
                                ref_price = (
                                    day_bars[r.ticker].close
                                    if (r.ticker in day_bars and day_bars[r.ticker].close > 0)
                                    else None
                                )
                                cand_mode = classify_price_mode(ref_price)
                                if cand_mode in ("EXCLUDED_BELOW_50", "INVALID"):
                                    continue
                                if mode is not None and cand_mode != mode:
                                    continue
                                pending_orders.append(
                                    _PendingOrder(
                                        ticker=r.ticker,
                                        signal_date=d,
                                        signal_prob=float(prob),
                                        mode=cand_mode,
                                    )
                                )

        # -----------------------------------------------------------------
        # STEP 5: Final Liquidation of Remaining Open Positions at Last Close
        # -----------------------------------------------------------------
        if open_positions:
            last_date = sorted_dates[-1]
            last_day_bars = bars_by_date[last_date]

            for ticker in list(open_positions.keys()):
                pos = open_positions[ticker]
                last_bar = last_day_bars.get(ticker)
                raw_exit_price = (
                    float(last_bar.close)
                    if (last_bar is not None and last_bar.close > 0)
                    else pos.last_close
                )
                exit_fill_price = raw_exit_price * (1.0 - self.config.slippage_bps / 10000.0)
                pos_gross_exit = pos.shares * exit_fill_price
                exit_fee = pos_gross_exit * self.config.commission_sell
                exit_slippage_cost = pos.shares * (raw_exit_price - exit_fill_price)
                proceeds = pos_gross_exit - exit_fee
                cash += proceeds

                gross_pnl = pos.shares * (raw_exit_price - pos.raw_entry_price)
                total_slippage = pos.entry_slippage + exit_slippage_cost
                net_pnl = proceeds - (pos.shares * pos.entry_price + pos.entry_fee)
                invested = pos.shares * pos.entry_price + pos.entry_fee
                net_return = (net_pnl / invested) if invested > 0 else 0.0

                mfe = (pos.highest_seen - pos.entry_price) / pos.entry_price
                mae = (pos.lowest_seen - pos.entry_price) / pos.entry_price

                trade = TradeRecord(
                    trade_id=f"T_{pos.ticker}_{pos.entry_date}_{last_date}_FINAL",
                    ticker=pos.ticker,
                    signal_date=pos.signal_date,
                    entry_date=pos.entry_date,
                    exit_date=last_date,
                    shares=pos.shares,
                    entry_price=pos.entry_price,
                    exit_price=exit_fill_price,
                    position_value=pos.shares * pos.entry_price,
                    entry_fee=pos.entry_fee,
                    exit_fee=exit_fee,
                    slippage_cost=total_slippage,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    net_return=net_return,
                    exit_reason="EXPIRY",
                    holding_days=pos.holding_days,
                    mfe=mfe,
                    mae=mae,
                    signal_probability=pos.signal_prob,
                    mode=pos.mode,
                )
                closed_trades.append(trade)
                del open_positions[ticker]

            # Update final equity point after liquidating open positions
            if equity_curve:
                if cash > peak_equity:
                    peak_equity = cash
                dd_pct = max(0.0, (peak_equity - cash) / peak_equity) if peak_equity > 0 else 0.0
                equity_curve[-1] = EquityPoint(
                    date=last_date,
                    cash=cash,
                    positions_value=0.0,
                    total_equity=cash,
                    drawdown_pct=dd_pct,
                    open_positions_count=0,
                )

        return compute_backtest_report(
            config=self.config,
            trades=closed_trades,
            equity_curve=equity_curve,
            start_date=start_date,
            end_date=end_date,
        )
