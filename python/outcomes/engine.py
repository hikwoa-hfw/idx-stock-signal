import math
import uuid
from datetime import date, datetime, timezone
from typing import Optional, Union

from python.common.types import (
    AmbiguityPolicy,
    DailyBar,
    SignalDailySnapshot,
    SignalOutcomeRecord,
    SignalRecord,
    classify_price_mode,
)
from python.config.settings import settings
from python.data.repository import DailyBarRepository
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository

DEFAULT_AMBIGUITY_POLICY: str = "conservative"


def _normalize_policy(policy: Union[str, AmbiguityPolicy]) -> str:
    raw = policy.value if isinstance(policy, AmbiguityPolicy) else str(policy)
    clean = raw.strip().lower()
    if clean in ("conservative", "optimistic", "ambiguous"):
        return clean
    raise ValueError(
        f"Invalid ambiguity_policy: '{policy}'. "
        "Expected 'conservative', 'optimistic', or 'ambiguous'."
    )


def _create_invalidated_gap_outcome(
    signal: SignalRecord,
    clean_ticker: str,
    deduped_bars: list[DailyBar],
    gap_reason: str,
    outcome_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> tuple[SignalOutcomeRecord, list[SignalDailySnapshot]]:
    """Construct an INVALIDATED_GAP outcome record for pre-entry barrier violations.

    Actual trade metrics (Scope A) are NULL with holding_days=0.
    Full horizon opportunity metrics (Scope B) are evaluated relative to the planned
    anchor price (reference_price or entry range midpoint).
    """
    ref_p = getattr(signal, "reference_price", None)
    if ref_p is not None and math.isfinite(ref_p) and ref_p > 0:
        anchor_px = float(ref_p)
    elif (
        signal.entry_low is not None
        and signal.entry_high is not None
        and math.isfinite(signal.entry_low)
        and math.isfinite(signal.entry_high)
    ):
        anchor_px = float((signal.entry_low + signal.entry_high) / 2.0)
    elif signal.entry_low is not None and math.isfinite(signal.entry_low):
        anchor_px = float(signal.entry_low)
    else:
        anchor_px = float(deduped_bars[0].open)

    validity_bars = deduped_bars[: signal.max_holding_days]
    last_bar = validity_bars[-1]
    max_observed_high = max(b.high for b in validity_bars)
    min_observed_low = min(b.low for b in validity_bars)
    full_h_mfe = max(0.0, (max_observed_high - anchor_px) / anchor_px)
    full_h_mae = min(0.0, (min_observed_low - anchor_px) / anchor_px)
    full_h_mfe_p = max(0.0, max_observed_high - anchor_px)
    full_h_mae_p = min(0.0, min_observed_low - anchor_px)
    full_h_ttp = next(
        i for i, b in enumerate(validity_bars, start=1) if b.high == max_observed_high
    )
    end_px = float(last_bar.close)
    end_ret = (end_px - anchor_px) / anchor_px
    is_fhc = len(validity_bars) >= signal.max_holding_days

    signal_mode = getattr(signal, "mode_id", None) or getattr(signal, "mode", None)
    mode_val = signal_mode or classify_price_mode(anchor_px)

    return (
        SignalOutcomeRecord(
            outcome_id=outcome_id or str(uuid.uuid4()),
            signal_id=signal.signal_id,
            ticker=clean_ticker,
            signal_date=signal.signal_date,
            entry_date=None,
            entry_price=None,
            entry_status="UNFILLED",
            outcome_status="INVALIDATED_GAP",
            realized_return=None,
            gross_return=None,
            return_after_fees=None,
            return_after_fees_and_slippage=None,
            net_return=None,
            holding_days=0,
            mfe=None,
            mae=None,
            mfe_price=None,
            mae_price=None,
            time_to_peak=None,
            time_to_tp=None,
            time_to_sl=None,
            exit_date=None,
            exit_price=None,
            exit_reason="INVALIDATED_GAP",
            resolved_at=datetime.now(timezone.utc),
            notes=(
                f"{gap_reason} | {notes}"
                if notes and notes != gap_reason
                else (notes or gap_reason)
            ),
            mode=mode_val,
            trigger_price=anchor_px,
            observation_end_date=last_bar.date,
            full_horizon_mfe=full_h_mfe,
            full_horizon_mae=full_h_mae,
            full_horizon_mfe_price=full_h_mfe_p,
            full_horizon_mae_price=full_h_mae_p,
            full_horizon_time_to_peak=full_h_ttp,
            horizon_end_date=last_bar.date,
            horizon_end_price=end_px,
            horizon_end_return=end_ret,
            is_full_horizon_complete=is_fhc,
        ),
        [],
    )


class OutcomeEngine:
    """Triple-barrier outcome engine reconciling daily signals with price data."""

    def __init__(
        self,
        bar_repo: Optional[DailyBarRepository] = None,
        signal_repo: Optional[SignalRepository] = None,
        outcome_repo: Optional[OutcomeRepository] = None,
        ambiguity_policy: Union[str, AmbiguityPolicy] = DEFAULT_AMBIGUITY_POLICY,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_bps: float = 10.0,
        enforce_entry_band: bool = False,
        max_entry_deviation_pct: Optional[float] = None,
    ) -> None:
        self.bar_repo = bar_repo
        self.signal_repo = signal_repo
        self.outcome_repo = outcome_repo
        self.ambiguity_policy = _normalize_policy(ambiguity_policy)
        self.commission_buy = commission_buy
        self.commission_sell = commission_sell
        self.slippage_bps = slippage_bps
        self.enforce_entry_band = enforce_entry_band
        self.max_entry_deviation_pct = max_entry_deviation_pct

    def _get_bar_repo(self) -> DailyBarRepository:
        if self.bar_repo is None:
            self.bar_repo = DailyBarRepository(settings.database_url)
        return self.bar_repo

    def _get_signal_repo(self) -> SignalRepository:
        if self.signal_repo is None:
            self.signal_repo = SignalRepository(settings.database_url)
        return self.signal_repo

    def _get_outcome_repo(self) -> OutcomeRepository:
        if self.outcome_repo is None:
            self.outcome_repo = OutcomeRepository(settings.database_url)
        return self.outcome_repo

    def evaluate_signal(
        self,
        signal: SignalRecord,
        forward_bars: list[DailyBar],
        ambiguity_policy: Optional[Union[str, AmbiguityPolicy]] = None,
        entry_price: Optional[float] = None,
        outcome_id: Optional[str] = None,
        notes: Optional[str] = None,
        commission_buy: Optional[float] = None,
        commission_sell: Optional[float] = None,
        slippage_bps: Optional[float] = None,
        enforce_entry_band: Optional[bool] = None,
        max_entry_deviation_pct: Optional[float] = None,
    ) -> tuple[Optional[SignalOutcomeRecord], list[SignalDailySnapshot]]:
        """Evaluate a signal across forward trading bars using triple barrier rules."""
        policy = (
            _normalize_policy(ambiguity_policy)
            if ambiguity_policy is not None
            else self.ambiguity_policy
        )
        c_buy = self.commission_buy if commission_buy is None else commission_buy
        c_sell = self.commission_sell if commission_sell is None else commission_sell
        s_bps = self.slippage_bps if slippage_bps is None else slippage_bps
        s_half = (s_bps / 10000.0) / 2.0

        clean_ticker = signal.ticker.strip().upper().removesuffix(".JK")

        valid_bars: list[DailyBar] = []
        for b in forward_bars:
            if b.date <= signal.signal_date:
                continue
            b_tick = b.ticker.strip().upper().removesuffix(".JK")
            if b_tick != clean_ticker:
                continue
            if not (
                math.isfinite(b.open)
                and math.isfinite(b.high)
                and math.isfinite(b.low)
                and math.isfinite(b.close)
            ):
                continue
            if b.high < b.low or b.open <= 0 or b.close <= 0 or b.low <= 0 or b.high <= 0:
                continue
            valid_bars.append(b)

        seen_dates = set()
        deduped_bars: list[DailyBar] = []
        for b in sorted(valid_bars, key=lambda x: x.date):
            if b.date not in seen_dates:
                seen_dates.add(b.date)
                deduped_bars.append(b)

        if not deduped_bars:
            return None, []

        policy_str = (
            getattr(signal, "entry_policy", None) or "IMMEDIATE"
        ).strip().upper()
        signal_status = (
            getattr(signal, "status", None) or getattr(signal, "signal", None) or "BUY"
        ).strip().upper()
        is_breakout = policy_str == "BREAKOUT" or signal_status == "WAIT_FOR_BREAKOUT"

        eff_enforce_band = (
            self.enforce_entry_band
            if enforce_entry_band is None
            else enforce_entry_band
        )
        eff_max_dev = (
            max_entry_deviation_pct
            if max_entry_deviation_pct is not None
            else (
                self.max_entry_deviation_pct
                if self.max_entry_deviation_pct is not None
                else (getattr(signal, "max_entry_deviation_pct", 0.05) or 0.05)
            )
        )

        ref_p = getattr(signal, "reference_price", None)
        if ref_p is not None and math.isfinite(ref_p) and ref_p > 0:
            anchor_px = float(ref_p)
        elif (
            signal.entry_low is not None
            and signal.entry_high is not None
            and math.isfinite(signal.entry_low)
            and math.isfinite(signal.entry_high)
        ):
            anchor_px = float((signal.entry_low + signal.entry_high) / 2.0)
        elif signal.entry_low is not None and math.isfinite(signal.entry_low):
            anchor_px = float(signal.entry_low)
        else:
            anchor_px = float(deduped_bars[0].open)

        if is_breakout and entry_price is None:
            trigger_level = float(signal.entry_low)
            trigger_idx = None
            validity_bars = deduped_bars[: signal.max_holding_days]
            for idx, bar in enumerate(validity_bars):
                if bar.high >= trigger_level:
                    trigger_idx = idx
                    break

            if trigger_idx is None:
                if len(deduped_bars) >= signal.max_holding_days:
                    # Breakout order expired without triggering
                    last_bar = validity_bars[-1]
                    max_observed_high = max(b.high for b in validity_bars)
                    min_observed_low = min(b.low for b in validity_bars)
                    full_h_mfe = max(0.0, (max_observed_high - trigger_level) / trigger_level)
                    full_h_mae = min(0.0, (min_observed_low - trigger_level) / trigger_level)
                    full_h_mfe_p = max(0.0, max_observed_high - trigger_level)
                    full_h_mae_p = min(0.0, min_observed_low - trigger_level)
                    full_h_ttp = next(
                        i
                        for i, b in enumerate(validity_bars, start=1)
                        if b.high == max_observed_high
                    )
                    end_px = float(last_bar.close)
                    end_ret = (end_px - trigger_level) / trigger_level

                    signal_mode = getattr(signal, "mode_id", None) or getattr(signal, "mode", None)
                    mode_val = signal_mode or classify_price_mode(trigger_level)
                    return (
                        SignalOutcomeRecord(
                            outcome_id=outcome_id or str(uuid.uuid4()),
                            signal_id=signal.signal_id,
                            ticker=clean_ticker,
                            signal_date=signal.signal_date,
                            entry_date=None,
                            entry_price=None,
                            entry_status="UNFILLED",
                            outcome_status="UNFILLED_EXPIRED",
                            realized_return=None,
                            gross_return=None,
                            return_after_fees=None,
                            return_after_fees_and_slippage=None,
                            net_return=None,
                            holding_days=0,
                            mfe=None,
                            mae=None,
                            mfe_price=None,
                            mae_price=None,
                            time_to_peak=None,
                            time_to_tp=None,
                            time_to_sl=None,
                            exit_date=None,
                            exit_price=None,
                            exit_reason="UNFILLED_EXPIRED",
                            resolved_at=datetime.now(timezone.utc),
                            notes=notes or (
                                f"Breakout trigger price {trigger_level:,.1f} never reached "
                                f"before expiry. Max high observed: {max_observed_high:,.1f}."
                            ),
                            mode=mode_val,
                            trigger_price=trigger_level,
                            observation_end_date=last_bar.date,
                            full_horizon_mfe=full_h_mfe,
                            full_horizon_mae=full_h_mae,
                            full_horizon_mfe_price=full_h_mfe_p,
                            full_horizon_mae_price=full_h_mae_p,
                            full_horizon_time_to_peak=full_h_ttp,
                            horizon_end_date=last_bar.date,
                            horizon_end_price=end_px,
                            horizon_end_return=end_ret,
                            is_full_horizon_complete=True,
                        ),
                        [],
                    )
                else:
                    # Still waiting for breakout trigger
                    return None, []

            eval_bars = deduped_bars[trigger_idx : trigger_idx + signal.max_holding_days]
            first_bar = eval_bars[0]
            entry_date = first_bar.date
            tp_price = float(signal.tp_price)
            sl_price = float(signal.sl_price)
            if first_bar.open >= tp_price:
                gap_note = (
                    f"Pre-entry gap-through above TP barrier on trigger day: "
                    f"open {first_bar.open:,.1f} >= tp_price {tp_price:,.1f}. "
                    f"Order invalidated before execution."
                )
                return _create_invalidated_gap_outcome(
                    signal=signal,
                    clean_ticker=clean_ticker,
                    deduped_bars=deduped_bars,
                    gap_reason=gap_note,
                    outcome_id=outcome_id,
                    notes=notes,
                )

            if first_bar.open >= trigger_level:
                dev = (first_bar.open - trigger_level) / trigger_level
                if dev > eff_max_dev:
                    gap_note = (
                        f"Pre-entry breakout gap-through above max deviation: "
                        f"open {first_bar.open:,.1f} exceeds trigger {trigger_level:,.1f} by "
                        f"{dev * 100:.2f}% (> {eff_max_dev * 100:.1f}%). "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                if eff_enforce_band and (
                    first_bar.open < signal.entry_low or first_bar.open > signal.entry_high
                ):
                    gap_note = (
                        f"Pre-entry breakout open outside band "
                        f"[{signal.entry_low:,.1f}, {signal.entry_high:,.1f}]: "
                        f"trigger day open {first_bar.open:,.1f}. "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                ep = float(first_bar.open)
                entry_deviation_pct = dev
            else:
                ep = trigger_level
                entry_deviation_pct = 0.0
        else:
            eval_bars = deduped_bars[: signal.max_holding_days]
            first_bar = eval_bars[0]
            entry_date = first_bar.date
            tp_price = float(signal.tp_price)
            sl_price = float(signal.sl_price)
            if entry_price is None:
                cand_px = float(first_bar.open)
                if cand_px <= sl_price:
                    gap_note = (
                        f"Pre-entry gap-through below SL barrier: "
                        f"Day 1 open {cand_px:,.1f} <= sl_price {sl_price:,.1f}. "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                elif cand_px >= tp_price:
                    gap_note = (
                        f"Pre-entry gap-through above TP barrier: "
                        f"Day 1 open {cand_px:,.1f} >= tp_price {tp_price:,.1f}. "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                dev = abs(cand_px - anchor_px) / anchor_px
                if dev > eff_max_dev:
                    gap_note = (
                        f"Pre-entry open deviation excessive: "
                        f"Day 1 open {cand_px:,.1f} deviates {dev * 100:.2f}% from reference "
                        f"{anchor_px:,.1f} (> {eff_max_dev * 100:.1f}%). "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                if eff_enforce_band and (
                    cand_px < signal.entry_low or cand_px > signal.entry_high
                ):
                    gap_note = (
                        f"Pre-entry open outside band "
                        f"[{signal.entry_low:,.1f}, {signal.entry_high:,.1f}]: "
                        f"Day 1 open {cand_px:,.1f}. Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                ep = cand_px
                entry_deviation_pct = (ep - anchor_px) / anchor_px
            else:
                ep = float(entry_price)
                if ep <= sl_price or ep >= tp_price:
                    gap_note = (
                        f"Pre-entry price beyond barrier: "
                        f"entry_price {ep:,.1f} outside [{sl_price:,.1f}, {tp_price:,.1f}]. "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                dev = abs(ep - anchor_px) / anchor_px
                if dev > eff_max_dev:
                    gap_note = (
                        f"Pre-entry price deviation excessive: "
                        f"entry_price {ep:,.1f} deviates {dev * 100:.2f}% from reference "
                        f"{anchor_px:,.1f} (> {eff_max_dev * 100:.1f}%). "
                        f"Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                if eff_enforce_band and (ep < signal.entry_low or ep > signal.entry_high):
                    gap_note = (
                        f"Pre-entry price outside band "
                        f"[{signal.entry_low:,.1f}, {signal.entry_high:,.1f}]: "
                        f"entry_price {ep:,.1f}. Order invalidated before execution."
                    )
                    return _create_invalidated_gap_outcome(
                        signal=signal,
                        clean_ticker=clean_ticker,
                        deduped_bars=deduped_bars,
                        gap_reason=gap_note,
                        outcome_id=outcome_id,
                        notes=notes,
                    )
                entry_deviation_pct = (ep - anchor_px) / anchor_px

        if not math.isfinite(ep) or ep <= 0:
            return None, []

        tp_price = float(signal.tp_price)
        sl_price = float(signal.sl_price)
        trigger_level_val = float(signal.entry_low)
        is_intraday_breakout_entry = (
            is_breakout and entry_price is None and first_bar.open < trigger_level_val
        )

        # Full-horizon opportunity metrics calculated over configured horizon (<= max_holding_days)
        horizon_bars = eval_bars[: signal.max_holding_days]
        is_fhc = len(horizon_bars) >= signal.max_holding_days
        last_h_bar = horizon_bars[-1]
        h_max_high = max(b.high for b in horizon_bars)
        h_min_low = min(b.low for b in horizon_bars)
        full_h_mfe = max(0.0, (h_max_high - ep) / ep)
        full_h_mae = min(0.0, (h_min_low - ep) / ep)
        full_h_mfe_p = max(0.0, h_max_high - ep)
        full_h_mae_p = min(0.0, h_min_low - ep)
        full_h_ttp = next(
            i for i, b in enumerate(horizon_bars, start=1) if b.high == h_max_high
        )
        h_end_price = float(last_h_bar.close)
        h_end_ret = (h_end_price - ep) / ep
        h_end_date = last_h_bar.date

        snapshots: list[SignalDailySnapshot] = []
        path_bars: list[DailyBar] = []
        in_trade_highs_lower: list[float] = []
        in_trade_highs_upper: list[float] = []
        in_trade_highs_proxy: list[float] = []
        in_trade_lows_lower: list[float] = []
        in_trade_lows_upper: list[float] = []
        in_trade_lows_proxy: list[float] = []

        outcome_status: Optional[str] = None
        exit_price_val: Optional[float] = None
        exit_date_val: Optional[date] = None
        exit_reason_val: Optional[str] = None
        resolved_holding_days: int = 0

        for k, bar in enumerate(eval_bars, start=1):
            path_bars.append(bar)
            tp_hit = bar.high >= tp_price
            sl_hit = bar.low <= sl_price
            is_entry_bar_breakout = k == 1 and is_intraday_breakout_entry

            is_exit = False
            bar_high_lower = bar.high
            bar_high_upper = bar.high
            bar_high_proxy = bar.high
            bar_low_lower = bar.low
            bar_low_upper = bar.low
            bar_low_proxy = bar.low

            if is_entry_bar_breakout:
                if tp_hit and sl_hit:
                    is_exit = True
                    if policy == "conservative":
                        outcome_status = "SL"
                        exit_price_val = sl_price
                        exit_reason_val = "SL"
                        bar_high_lower = ep
                        bar_high_upper = bar.high
                        bar_high_proxy = ep
                        bar_low_lower = sl_price
                        bar_low_upper = sl_price
                        bar_low_proxy = sl_price
                    elif policy == "optimistic":
                        outcome_status = "TP"
                        exit_price_val = tp_price
                        exit_reason_val = "TP"
                        bar_high_lower = tp_price
                        bar_high_upper = tp_price
                        bar_high_proxy = tp_price
                        bar_low_lower = bar.low
                        bar_low_upper = ep
                        bar_low_proxy = ep
                    else:
                        outcome_status = "AMBIGUOUS"
                        exit_price_val = float(bar.close)
                        exit_reason_val = "AMBIGUOUS"
                        bar_high_lower = bar.high
                        bar_high_upper = bar.high
                        bar_high_proxy = bar.high
                        bar_low_lower = bar.low
                        bar_low_upper = bar.low
                        bar_low_proxy = bar.low
                    exit_date_val = bar.date
                    resolved_holding_days = k

                elif tp_hit:
                    is_exit = True
                    outcome_status = "TP"
                    exit_price_val = tp_price
                    exit_reason_val = "TP"
                    exit_date_val = bar.date
                    resolved_holding_days = k
                    bar_high_lower = tp_price
                    bar_high_upper = tp_price
                    bar_high_proxy = tp_price
                    bar_low_lower = bar.low
                    bar_low_upper = ep
                    bar_low_proxy = ep

                elif sl_hit:
                    if bar.close <= sl_price:
                        is_exit = True
                        outcome_status = "SL"
                        exit_price_val = sl_price
                        exit_reason_val = "SL"
                        exit_date_val = bar.date
                        resolved_holding_days = k
                        bar_high_lower = ep
                        bar_high_upper = bar.high
                        bar_high_proxy = ep
                        bar_low_lower = sl_price
                        bar_low_upper = sl_price
                        bar_low_proxy = sl_price
                    else:
                        if policy == "conservative":
                            is_exit = True
                            outcome_status = "SL"
                            exit_price_val = sl_price
                            exit_reason_val = "SL"
                            exit_date_val = bar.date
                            resolved_holding_days = k
                            bar_high_lower = ep
                            bar_high_upper = bar.high
                            bar_high_proxy = ep
                            bar_low_lower = sl_price
                            bar_low_upper = sl_price
                            bar_low_proxy = sl_price
                        elif policy == "ambiguous":
                            is_exit = True
                            outcome_status = "AMBIGUOUS"
                            exit_price_val = float(bar.close)
                            exit_reason_val = "AMBIGUOUS"
                            exit_date_val = bar.date
                            resolved_holding_days = k
                            bar_high_lower = bar.high
                            bar_high_upper = bar.high
                            bar_high_proxy = bar.high
                            bar_low_lower = bar.low
                            bar_low_upper = bar.low
                            bar_low_proxy = bar.low
                        elif policy == "optimistic":
                            is_exit = False
                            bar_high_lower = max(ep, bar.close)
                            bar_high_upper = bar.high
                            bar_high_proxy = bar.high
                            bar_low_lower = bar.low
                            bar_low_upper = min(ep, bar.close)
                            bar_low_proxy = min(ep, bar.close)

                elif k == signal.max_holding_days:
                    is_exit = True
                    outcome_status = "EXPIRY"
                    exit_price_val = float(bar.close)
                    exit_reason_val = "EXPIRY"
                    exit_date_val = bar.date
                    resolved_holding_days = k
                    bar_high_lower = max(ep, bar.close)
                    bar_high_upper = bar.high
                    bar_high_proxy = bar.high
                    bar_low_lower = bar.low
                    bar_low_upper = min(ep, bar.close)
                    bar_low_proxy = min(ep, bar.close)
                else:
                    is_exit = False
                    bar_high_lower = max(ep, bar.close)
                    bar_high_upper = bar.high
                    bar_high_proxy = bar.high
                    bar_low_lower = bar.low
                    bar_low_upper = min(ep, bar.close)
                    bar_low_proxy = min(ep, bar.close)

            else:
                if tp_hit and sl_hit:
                    is_exit = True
                    if bar.open >= tp_price:
                        # Gap-through TP at open
                        outcome_status = "TP"
                        exit_price_val = float(bar.open)
                        exit_reason_val = "TP"
                        bar_high_lower = float(bar.open)
                        bar_high_upper = float(bar.open)
                        bar_high_proxy = float(bar.open)
                        bar_low_lower = float(bar.open)
                        bar_low_upper = float(bar.open)
                        bar_low_proxy = float(bar.open)
                    elif bar.open <= sl_price:
                        # Gap-through SL at open
                        outcome_status = "SL"
                        exit_price_val = float(bar.open)
                        exit_reason_val = "SL"
                        bar_high_lower = float(bar.open)
                        bar_high_upper = float(bar.open)
                        bar_high_proxy = float(bar.open)
                        bar_low_lower = float(bar.open)
                        bar_low_upper = float(bar.open)
                        bar_low_proxy = float(bar.open)
                    else:
                        if policy == "conservative":
                            outcome_status = "SL"
                            exit_price_val = sl_price
                            exit_reason_val = "SL"
                            bar_high_lower = float(bar.open)
                            bar_high_upper = bar.high
                            bar_high_proxy = float(bar.open)
                            bar_low_lower = sl_price
                            bar_low_upper = sl_price
                            bar_low_proxy = sl_price
                        elif policy == "optimistic":
                            outcome_status = "TP"
                            exit_price_val = tp_price
                            exit_reason_val = "TP"
                            bar_high_lower = tp_price
                            bar_high_upper = tp_price
                            bar_high_proxy = tp_price
                            bar_low_lower = bar.low
                            bar_low_upper = float(bar.open)
                            bar_low_proxy = float(bar.open)
                        else:
                            outcome_status = "AMBIGUOUS"
                            exit_price_val = float(bar.close)
                            exit_reason_val = "AMBIGUOUS"
                            bar_high_lower = bar.high
                            bar_high_upper = bar.high
                            bar_high_proxy = bar.high
                            bar_low_lower = bar.low
                            bar_low_upper = bar.low
                            bar_low_proxy = bar.low
                    exit_date_val = bar.date
                    resolved_holding_days = k

                elif tp_hit:
                    is_exit = True
                    if bar.open >= tp_price:
                        # Gap-through TP at open
                        outcome_status = "TP"
                        exit_price_val = float(bar.open)
                        exit_reason_val = "TP"
                        bar_high_lower = float(bar.open)
                        bar_high_upper = float(bar.open)
                        bar_high_proxy = float(bar.open)
                        bar_low_lower = float(bar.open)
                        bar_low_upper = float(bar.open)
                        bar_low_proxy = float(bar.open)
                    else:
                        outcome_status = "TP"
                        exit_price_val = tp_price
                        exit_reason_val = "TP"
                        bar_high_lower = tp_price
                        bar_high_upper = tp_price
                        bar_high_proxy = tp_price
                        bar_low_lower = bar.low
                        bar_low_upper = float(bar.open)
                        bar_low_proxy = bar.low
                    exit_date_val = bar.date
                    resolved_holding_days = k

                elif sl_hit:
                    is_exit = True
                    if bar.open <= sl_price:
                        # Gap-through SL at open
                        outcome_status = "SL"
                        exit_price_val = float(bar.open)
                        exit_reason_val = "SL"
                        bar_high_lower = float(bar.open)
                        bar_high_upper = float(bar.open)
                        bar_high_proxy = float(bar.open)
                        bar_low_lower = float(bar.open)
                        bar_low_upper = float(bar.open)
                        bar_low_proxy = float(bar.open)
                    else:
                        outcome_status = "SL"
                        exit_price_val = sl_price
                        exit_reason_val = "SL"
                        bar_high_lower = float(bar.open)
                        bar_high_upper = bar.high
                        bar_high_proxy = float(bar.open)
                        bar_low_lower = sl_price
                        bar_low_upper = sl_price
                        bar_low_proxy = sl_price
                    exit_date_val = bar.date
                    resolved_holding_days = k

                elif k == signal.max_holding_days:
                    is_exit = True
                    outcome_status = "EXPIRY"
                    exit_price_val = float(bar.close)
                    exit_reason_val = "EXPIRY"
                    exit_date_val = bar.date
                    resolved_holding_days = k
                    bar_high_lower = bar.high
                    bar_high_upper = bar.high
                    bar_high_proxy = bar.high
                    bar_low_lower = bar.low
                    bar_low_upper = bar.low
                    bar_low_proxy = bar.low
                else:
                    is_exit = False
                    bar_high_lower = bar.high
                    bar_high_upper = bar.high
                    bar_high_proxy = bar.high
                    bar_low_lower = bar.low
                    bar_low_upper = bar.low
                    bar_low_proxy = bar.low

            in_trade_highs_lower.append(bar_high_lower)
            in_trade_highs_upper.append(bar_high_upper)
            in_trade_highs_proxy.append(bar_high_proxy)
            in_trade_lows_lower.append(bar_low_lower)
            in_trade_lows_upper.append(bar_low_upper)
            in_trade_lows_proxy.append(bar_low_proxy)

            highest_in_trade_proxy = max(in_trade_highs_proxy)
            lowest_in_trade_proxy = min(in_trade_lows_proxy)
            mfe_so_far = max(0.0, (highest_in_trade_proxy - ep) / ep)
            mae_so_far = min(0.0, (lowest_in_trade_proxy - ep) / ep)

            highest_in_trade_lower = max(in_trade_highs_lower)
            highest_in_trade_upper = max(in_trade_highs_upper)
            lowest_in_trade_lower = min(in_trade_lows_lower)
            lowest_in_trade_upper = min(in_trade_lows_upper)
            mfe_min_so_far = max(0.0, (highest_in_trade_lower - ep) / ep)
            mfe_max_so_far = max(0.0, (highest_in_trade_upper - ep) / ep)
            mae_min_so_far = min(0.0, (lowest_in_trade_lower - ep) / ep)
            mae_max_so_far = min(0.0, (lowest_in_trade_upper - ep) / ep)

            return_from_entry = (
                (exit_price_val - ep) / ep
                if is_exit and exit_price_val is not None
                else (bar.close - ep) / ep
            )

            snapshots.append(
                SignalDailySnapshot(
                    snapshot_id=str(uuid.uuid4()),
                    signal_id=signal.signal_id,
                    snapshot_date=bar.date,
                    holding_day=k,
                    close_price=float(bar.close),
                    return_from_entry=float(return_from_entry),
                    high_price=float(bar.high),
                    low_price=float(bar.low),
                    mfe_so_far=float(mfe_so_far),
                    mae_so_far=float(mae_so_far),
                    mfe_min_so_far=float(mfe_min_so_far),
                    mfe_max_so_far=float(mfe_max_so_far),
                    mae_min_so_far=float(mae_min_so_far),
                    mae_max_so_far=float(mae_max_so_far),
                )
            )

            if is_exit:
                break

        highest_high_proxy = max(in_trade_highs_proxy)
        lowest_low_proxy = min(in_trade_lows_proxy)
        mfe = max(0.0, (highest_high_proxy - ep) / ep)
        mae = min(0.0, (lowest_low_proxy - ep) / ep)
        mfe_price = max(0.0, highest_high_proxy - ep)
        mae_price = min(0.0, lowest_low_proxy - ep)

        highest_high_lower = max(in_trade_highs_lower)
        highest_high_upper = max(in_trade_highs_upper)
        lowest_low_lower = min(in_trade_lows_lower)
        lowest_low_upper = min(in_trade_lows_upper)

        mfe_min = max(0.0, (highest_high_lower - ep) / ep)
        mfe_max = max(0.0, (highest_high_upper - ep) / ep)
        mae_min = min(0.0, (lowest_low_lower - ep) / ep)
        mae_max = min(0.0, (lowest_low_upper - ep) / ep)

        mfe_price_min = max(0.0, highest_high_lower - ep)
        mfe_price_max = max(0.0, highest_high_upper - ep)
        mae_price_min = min(0.0, lowest_low_lower - ep)
        mae_price_max = min(0.0, lowest_low_upper - ep)

        # Time-to-peak: 1-based holding day index when in-trade peak occurred
        time_to_peak = next(
            i for i, h in enumerate(in_trade_highs_proxy, start=1) if h == highest_high_proxy
        )
        time_to_tp = resolved_holding_days if outcome_status == "TP" else None
        time_to_sl = resolved_holding_days if outcome_status == "SL" else None

        signal_mode = getattr(signal, "mode_id", None) or getattr(signal, "mode", None)
        mode_val = signal_mode or classify_price_mode(ep)

        kwargs: dict = {
            "signal_id": signal.signal_id,
            "ticker": clean_ticker,
            "signal_date": signal.signal_date,
            "entry_date": entry_date,
            "entry_price": ep,
            "entry_status": "FILLED",
            "mfe": mfe,
            "mae": mae,
            "mfe_price": mfe_price,
            "mae_price": mae_price,
            "mfe_min": mfe_min,
            "mfe_max": mfe_max,
            "mae_min": mae_min,
            "mae_max": mae_max,
            "mfe_price_min": mfe_price_min,
            "mfe_price_max": mfe_price_max,
            "mae_price_min": mae_price_min,
            "mae_price_max": mae_price_max,
            "entry_deviation_pct": entry_deviation_pct,
            "time_to_peak": time_to_peak,
            "time_to_tp": time_to_tp,
            "time_to_sl": time_to_sl,
            "mode": mode_val,
            "outcome_id": outcome_id or str(uuid.uuid4()),
            "trigger_price": trigger_level_val,
            "observation_end_date": h_end_date,
            "full_horizon_mfe": full_h_mfe,
            "full_horizon_mae": full_h_mae,
            "full_horizon_mfe_price": full_h_mfe_p,
            "full_horizon_mae_price": full_h_mae_p,
            "full_horizon_time_to_peak": full_h_ttp,
            "horizon_end_date": h_end_date,
            "horizon_end_price": h_end_price,
            "horizon_end_return": h_end_ret,
            "is_full_horizon_complete": is_fhc,
        }
        if notes is not None:
            kwargs["notes"] = notes

        if outcome_status is not None and exit_price_val is not None and exit_date_val is not None:
            realized_return = (exit_price_val - ep) / ep
            gross_return = realized_return
            # Indonesian stock exchange broker commission: buy 0.15%, sell 0.25%
            return_after_fees = ((exit_price_val * (1.0 - c_sell)) / (ep * (1.0 + c_buy))) - 1.0
            # Slippage assumption: 10 bps total round-trip (5 bps per leg)
            # Aligned with EV Gate friction = comm_buy + comm_sell + slippage
            return_after_fees_and_slippage = (
                (exit_price_val * (1.0 - s_half) * (1.0 - c_sell))
                / (ep * (1.0 + s_half) * (1.0 + c_buy))
            ) - 1.0
            net_return = return_after_fees_and_slippage
            kwargs.update(
                {
                    "outcome_status": outcome_status,
                    "realized_return": realized_return,
                    "gross_return": gross_return,
                    "return_after_fees": return_after_fees,
                    "return_after_fees_and_slippage": return_after_fees_and_slippage,
                    "net_return": net_return,
                    "holding_days": resolved_holding_days,
                    "exit_date": exit_date_val,
                    "exit_price": exit_price_val,
                    "exit_reason": exit_reason_val,
                    "resolved_at": datetime.now(timezone.utc),
                }
            )
        else:
            kwargs.update(
                {
                    "outcome_status": "OPEN",
                    "realized_return": None,
                    "gross_return": None,
                    "return_after_fees": None,
                    "return_after_fees_and_slippage": None,
                    "net_return": None,
                    "holding_days": len(path_bars),
                    "exit_date": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "resolved_at": None,
                }
            )

        outcome_rec = SignalOutcomeRecord(**kwargs)
        return outcome_rec, snapshots

    def resolve_signal_by_id(
        self,
        signal_id: str,
        as_of_date: Optional[date] = None,
        save: bool = False,
        ambiguity_policy: Optional[Union[str, AmbiguityPolicy]] = None,
        force_recompute: bool = False,
        enforce_entry_band: Optional[bool] = None,
        max_entry_deviation_pct: Optional[float] = None,
    ) -> tuple[Optional[SignalOutcomeRecord], list[SignalDailySnapshot]]:
        """Resolve a specific signal from database repositories."""
        sig_repo = self._get_signal_repo()
        bar_repo = self._get_bar_repo()
        out_repo = self._get_outcome_repo()

        signal = sig_repo.get_signal_by_id(signal_id)
        if signal is None:
            return None, []

        existing_outcome = out_repo.get_outcome_by_signal_id(signal_id)
        if (
            not force_recompute
            and existing_outcome is not None
            and existing_outcome.outcome_status != "OPEN"
        ):
            snapshots = out_repo.get_snapshots_by_signal_id(signal_id)
            return existing_outcome, snapshots

        outcome_id = existing_outcome.outcome_id if existing_outcome else None
        existing_notes = (
            None if force_recompute
            else (existing_outcome.notes if existing_outcome else None)
        )

        bars = bar_repo.get_daily_bars(
            ticker=signal.ticker,
            start_date=signal.signal_date,
            end_date=as_of_date,
        )

        outcome, snapshots = self.evaluate_signal(
            signal=signal,
            forward_bars=bars,
            ambiguity_policy=ambiguity_policy,
            outcome_id=outcome_id,
            notes=existing_notes,
            enforce_entry_band=enforce_entry_band,
            max_entry_deviation_pct=max_entry_deviation_pct,
        )

        if outcome is not None and save:
            out_repo.save_outcome(outcome)
            if snapshots:
                out_repo.save_snapshots(snapshots)
            elif outcome.outcome_status in ("UNFILLED_EXPIRED", "INVALIDATED_GAP"):
                out_repo.delete_snapshots_by_signal_id(outcome.signal_id)

        return outcome, snapshots

    def resolve_all_signals(
        self,
        as_of_date: Optional[date] = None,
        ticker: Optional[str] = None,
        mode: Optional[str] = None,
        save: bool = True,
        ambiguity_policy: Optional[Union[str, AmbiguityPolicy]] = None,
        force_recompute: bool = False,
        enforce_entry_band: Optional[bool] = None,
        max_entry_deviation_pct: Optional[float] = None,
    ) -> list[tuple[SignalOutcomeRecord, list[SignalDailySnapshot]]]:
        """Resolve all active and un-evaluated signals against market bars."""
        sig_repo = self._get_signal_repo()
        bar_repo = self._get_bar_repo()
        out_repo = self._get_outcome_repo()

        eff_mode = mode.strip().upper() if mode and mode != "ALL" else None

        # 1. Fetch all signals up to as_of_date
        signals = sig_repo.get_signals(
            end_date=as_of_date,
            ticker=ticker,
            mode=eff_mode,
        )
        if not signals:
            return []

        # 2. Check existing outcomes via fast batch map lookup
        status_map = out_repo.get_outcome_statuses_map()
        results: list[tuple[SignalOutcomeRecord, list[SignalDailySnapshot]]] = []
        outcomes_to_save: list[SignalOutcomeRecord] = []
        snapshots_to_save: list[SignalDailySnapshot] = []

        for sig in signals:
            entry = status_map.get(sig.signal_id)
            if not force_recompute and entry is not None and entry[1] != "OPEN":
                # Already matured outcome, skip re-evaluating
                continue

            outcome_id = entry[0] if entry else None
            existing_notes = None if force_recompute else (entry[2] if entry else None)

            bars = bar_repo.get_daily_bars(
                ticker=sig.ticker,
                start_date=sig.signal_date,
                end_date=as_of_date,
            )

            outcome, snapshots = self.evaluate_signal(
                signal=sig,
                forward_bars=bars,
                ambiguity_policy=ambiguity_policy,
                outcome_id=outcome_id,
                notes=existing_notes,
                enforce_entry_band=enforce_entry_band,
                max_entry_deviation_pct=max_entry_deviation_pct,
            )

            if outcome is not None:
                if save:
                    outcomes_to_save.append(outcome)
                    snapshots_to_save.extend(snapshots)
                results.append((outcome, snapshots))

        if save and outcomes_to_save:
            out_repo.save_outcomes(outcomes_to_save)
            out_repo.save_snapshots(snapshots_to_save)

        return results
