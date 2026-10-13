import math
from typing import Optional, Union

from python.common.types import (
    AmbiguityPolicy,
    DailyBar,
    LabelOutcome,
    LabelRecord,
    classify_price_mode,
)

DEFAULT_TP_PCT: float = 0.05
DEFAULT_SL_PCT: float = 0.02
DEFAULT_MAX_HOLDING_DAYS: int = 10
DEFAULT_AMBIGUITY_POLICY: str = "conservative"
LABEL_VERSION: str = "v1.0.0"


def _normalize_pct(val: float) -> float:
    if not math.isfinite(val) or val == 0:
        raise ValueError(f"Percentage barrier must be a non-zero finite number, got {val}")
    raw = abs(val)
    if raw >= 1.0:
        return raw / 100.0
    return raw


def _normalize_policy(policy: Union[str, AmbiguityPolicy]) -> str:
    raw = policy.value if isinstance(policy, AmbiguityPolicy) else str(policy)
    clean = raw.strip().lower()
    if clean in ("conservative", "optimistic", "ambiguous"):
        return clean
    raise ValueError(
        f"Invalid ambiguity_policy: '{policy}'. "
        "Expected 'conservative', 'optimistic', or 'ambiguous'."
    )


class LabelEngine:
    def __init__(
        self,
        tp_pct: float = DEFAULT_TP_PCT,
        sl_pct: float = DEFAULT_SL_PCT,
        max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
        ambiguity_policy: Union[str, AmbiguityPolicy] = DEFAULT_AMBIGUITY_POLICY,
        label_version: str = LABEL_VERSION,
    ) -> None:
        self.tp_pct = _normalize_pct(tp_pct)
        self.sl_pct = _normalize_pct(sl_pct)
        if self.tp_pct <= 0:
            raise ValueError("tp_pct must be greater than 0")
        if self.sl_pct <= 0:
            raise ValueError("sl_pct must be greater than 0")
        if max_holding_days < 1:
            raise ValueError("max_holding_days must be >= 1")

        self.max_holding_days = int(max_holding_days)
        self.ambiguity_policy = _normalize_policy(ambiguity_policy)
        self.label_version = label_version.strip() or LABEL_VERSION

    def compute_label_for_bar(
        self,
        entry_bar: DailyBar,
        forward_bars: list[DailyBar],
        entry_price: Optional[float] = None,
        include_incomplete: bool = False,
    ) -> Optional[LabelRecord]:
        ep = float(entry_price if entry_price is not None else entry_bar.close)
        if not math.isfinite(ep) or ep <= 0:
            return None

        tp_price = ep * (1.0 + self.tp_pct)
        sl_price = ep * (1.0 - self.sl_pct)

        clean_ticker = entry_bar.ticker.strip().upper().removesuffix(".JK")
        valid_forward: list[DailyBar] = []
        for b in forward_bars:
            if b.date <= entry_bar.date:
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
            if b.high < b.low or b.open <= 0 or b.close <= 0 or b.low <= 0:
                continue
            valid_forward.append(b)

        seen_dates = set()
        deduped_forward: list[DailyBar] = []
        for b in sorted(valid_forward, key=lambda x: x.date):
            if b.date not in seen_dates:
                seen_dates.add(b.date)
                deduped_forward.append(b)

        eval_bars = deduped_forward[: self.max_holding_days]

        if not eval_bars:
            return None

        path_bars: list[DailyBar] = []
        outcome: Optional[str] = None
        exit_price: Optional[float] = None
        exit_date = None
        holding_days: int = 0

        for k, bar in enumerate(eval_bars, start=1):
            path_bars.append(bar)
            tp_hit = bar.high >= tp_price
            sl_hit = bar.low <= sl_price

            if tp_hit and sl_hit:
                # Ambiguous intraday candle
                if bar.open >= tp_price:
                    outcome = LabelOutcome.TP.value
                    exit_price = float(bar.open)
                elif bar.open <= sl_price:
                    outcome = LabelOutcome.SL.value
                    exit_price = float(bar.open)
                else:
                    if self.ambiguity_policy == "conservative":
                        outcome = LabelOutcome.SL.value
                        exit_price = sl_price
                    elif self.ambiguity_policy == "optimistic":
                        outcome = LabelOutcome.TP.value
                        exit_price = tp_price
                    else:
                        outcome = LabelOutcome.AMBIGUOUS.value
                        exit_price = float(bar.close)

                exit_date = bar.date
                holding_days = k
                break

            elif tp_hit:
                outcome = LabelOutcome.TP.value
                exit_price = float(bar.open) if bar.open >= tp_price else tp_price
                exit_date = bar.date
                holding_days = k
                break

            elif sl_hit:
                outcome = LabelOutcome.SL.value
                exit_price = float(bar.open) if bar.open <= sl_price else sl_price
                exit_date = bar.date
                holding_days = k
                break

            elif k == self.max_holding_days:
                outcome = LabelOutcome.EXPIRY.value
                exit_price = float(bar.close)
                exit_date = bar.date
                holding_days = k
                break

        if outcome is None:
            if not include_incomplete:
                return None
            outcome = LabelOutcome.EXPIRY.value
            exit_price = float(path_bars[-1].close)
            exit_date = path_bars[-1].date
            holding_days = len(path_bars)

        if exit_price is None or exit_date is None:
            return None

        highest_high = max(b.high for b in path_bars)
        lowest_low = min(b.low for b in path_bars)
        mfe = (highest_high - ep) / ep
        mae = (lowest_low - ep) / ep
        realized_return = (exit_price - ep) / ep
        binary_target = 1 if outcome == LabelOutcome.TP.value else 0

        return LabelRecord(
            ticker=clean_ticker,
            date=entry_bar.date,
            label_version=self.label_version,
            entry_price=ep,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_pct=self.tp_pct,
            sl_pct=self.sl_pct,
            max_holding_days=self.max_holding_days,
            outcome=outcome,
            binary_target=binary_target,
            mfe=mfe,
            mae=mae,
            holding_days=holding_days,
            realized_return=realized_return,
            exit_date=exit_date,
            exit_price=exit_price,
            ambiguity_policy=self.ambiguity_policy,
            mode=classify_price_mode(ep),
        )

    def compute_labels(
        self,
        bars: list[DailyBar],
        include_incomplete: bool = False,
    ) -> list[LabelRecord]:
        if not bars:
            return []

        # Group by canonical ticker to avoid cross-ticker contamination
        by_ticker: dict[str, list[DailyBar]] = {}
        for b in bars:
            clean_t = b.ticker.strip().upper().removesuffix(".JK")
            by_ticker.setdefault(clean_t, []).append(b)

        records: list[LabelRecord] = []
        for _ticker, t_bars in sorted(by_ticker.items()):
            seen_dates = set()
            sorted_bars: list[DailyBar] = []
            for b in sorted(t_bars, key=lambda x: x.date):
                if b.date not in seen_dates:
                    seen_dates.add(b.date)
                    sorted_bars.append(b)

            n = len(sorted_bars)
            for i in range(n):
                entry_bar = sorted_bars[i]
                forward_bars = sorted_bars[i + 1 :]
                rec = self.compute_label_for_bar(
                    entry_bar=entry_bar,
                    forward_bars=forward_bars,
                    include_incomplete=include_incomplete,
                )
                if rec is not None:
                    records.append(rec)
        return records

    def compute_universe_labels(
        self,
        universe_bars: dict[str, list[DailyBar]],
        include_incomplete: bool = False,
    ) -> dict[str, list[LabelRecord]]:
        results: dict[str, list[LabelRecord]] = {}
        for ticker, bars in universe_bars.items():
            clean_t = ticker.strip().upper().removesuffix(".JK")
            results[clean_t] = self.compute_labels(
                bars=bars,
                include_incomplete=include_incomplete,
            )
        return results
