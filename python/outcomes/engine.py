import math
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


class OutcomeEngine:
    """Triple-barrier outcome engine reconciling daily signals with price data."""

    def __init__(
        self,
        bar_repo: Optional[DailyBarRepository] = None,
        signal_repo: Optional[SignalRepository] = None,
        outcome_repo: Optional[OutcomeRepository] = None,
        ambiguity_policy: Union[str, AmbiguityPolicy] = DEFAULT_AMBIGUITY_POLICY,
    ) -> None:
        self.bar_repo = bar_repo
        self.signal_repo = signal_repo
        self.outcome_repo = outcome_repo
        self.ambiguity_policy = _normalize_policy(ambiguity_policy)

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
    ) -> tuple[Optional[SignalOutcomeRecord], list[SignalDailySnapshot]]:
        """Evaluate a signal across forward trading bars using triple barrier rules."""
        policy = (
            _normalize_policy(ambiguity_policy)
            if ambiguity_policy is not None
            else self.ambiguity_policy
        )
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

        eval_bars = deduped_bars[: signal.max_holding_days]
        first_bar = eval_bars[0]
        entry_date = first_bar.date

        ep = float(entry_price if entry_price is not None else first_bar.open)
        if not math.isfinite(ep) or ep <= 0:
            return None, []

        tp_price = float(signal.tp_price)
        sl_price = float(signal.sl_price)

        snapshots: list[SignalDailySnapshot] = []
        path_bars: list[DailyBar] = []
        outcome_status: Optional[str] = None
        exit_price_val: Optional[float] = None
        exit_date_val: Optional[date] = None
        exit_reason_val: Optional[str] = None
        resolved_holding_days: int = 0

        for k, bar in enumerate(eval_bars, start=1):
            path_bars.append(bar)
            highest_high = max(b.high for b in path_bars)
            lowest_low = min(b.low for b in path_bars)
            mfe_so_far = (highest_high - ep) / ep
            mae_so_far = (lowest_low - ep) / ep
            return_from_entry = (bar.close - ep) / ep

            snapshots.append(
                SignalDailySnapshot(
                    signal_id=signal.signal_id,
                    snapshot_date=bar.date,
                    holding_day=k,
                    close_price=float(bar.close),
                    return_from_entry=float(return_from_entry),
                    high_price=float(bar.high),
                    low_price=float(bar.low),
                    mfe_so_far=float(mfe_so_far),
                    mae_so_far=float(mae_so_far),
                )
            )

            tp_hit = bar.high >= tp_price
            sl_hit = bar.low <= sl_price

            if tp_hit and sl_hit:
                if bar.open >= tp_price:
                    outcome_status = "TP"
                    exit_price_val = float(bar.open)
                    exit_reason_val = "TP"
                elif bar.open <= sl_price:
                    outcome_status = "SL"
                    exit_price_val = float(bar.open)
                    exit_reason_val = "SL"
                else:
                    if policy == "conservative":
                        outcome_status = "SL"
                        exit_price_val = sl_price
                        exit_reason_val = "SL"
                    elif policy == "optimistic":
                        outcome_status = "TP"
                        exit_price_val = tp_price
                        exit_reason_val = "TP"
                    else:
                        outcome_status = "AMBIGUOUS"
                        exit_price_val = float(bar.close)
                        exit_reason_val = "AMBIGUOUS"

                exit_date_val = bar.date
                resolved_holding_days = k
                break

            elif tp_hit:
                outcome_status = "TP"
                exit_price_val = float(bar.open) if bar.open >= tp_price else tp_price
                exit_reason_val = "TP"
                exit_date_val = bar.date
                resolved_holding_days = k
                break

            elif sl_hit:
                outcome_status = "SL"
                exit_price_val = float(bar.open) if bar.open <= sl_price else sl_price
                exit_reason_val = "SL"
                exit_date_val = bar.date
                resolved_holding_days = k
                break

            elif k == signal.max_holding_days:
                outcome_status = "EXPIRY"
                exit_price_val = float(bar.close)
                exit_reason_val = "EXPIRY"
                exit_date_val = bar.date
                resolved_holding_days = k
                break

        highest_high = max(b.high for b in path_bars)
        lowest_low = min(b.low for b in path_bars)
        mfe = (highest_high - ep) / ep
        mae = (lowest_low - ep) / ep

        signal_mode = getattr(signal, "mode_id", None) or getattr(signal, "mode", None)
        mode_val = signal_mode or classify_price_mode(ep)

        kwargs: dict = {
            "signal_id": signal.signal_id,
            "ticker": clean_ticker,
            "signal_date": signal.signal_date,
            "entry_date": entry_date,
            "entry_price": ep,
            "mfe": mfe,
            "mae": mae,
            "mode": mode_val,
        }
        if outcome_id:
            kwargs["outcome_id"] = outcome_id
        if notes is not None:
            kwargs["notes"] = notes

        if outcome_status is not None and exit_price_val is not None and exit_date_val is not None:
            realized_return = (exit_price_val - ep) / ep
            kwargs.update(
                {
                    "outcome_status": outcome_status,
                    "realized_return": realized_return,
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
        existing_notes = existing_outcome.notes if existing_outcome else None

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
        )

        if outcome is not None and save:
            out_repo.save_outcome(outcome)
            out_repo.save_snapshots(snapshots)

        return outcome, snapshots

    def resolve_all_signals(
        self,
        as_of_date: Optional[date] = None,
        ticker: Optional[str] = None,
        save: bool = True,
        ambiguity_policy: Optional[Union[str, AmbiguityPolicy]] = None,
    ) -> list[tuple[SignalOutcomeRecord, list[SignalDailySnapshot]]]:
        """Resolve all active and un-evaluated signals against market bars."""
        sig_repo = self._get_signal_repo()
        bar_repo = self._get_bar_repo()
        out_repo = self._get_outcome_repo()

        # 1. Fetch all signals up to as_of_date
        signals = sig_repo.get_signals(
            end_date=as_of_date,
            ticker=ticker,
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
            if entry is not None and entry[1] != "OPEN":
                # Already matured outcome, skip re-evaluating
                continue

            outcome_id = entry[0] if entry else None
            existing_notes = entry[2] if entry else None

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
