from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np

from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository


@dataclass
class RetrainingTriggerConfig:
    min_matured_samples: int = 200
    rolling_window_size: int = 50
    brier_safety_floor: float = 0.25
    win_rate_safety_floor: float = 0.45
    force: bool = False


@dataclass
class RetrainingTriggerResult:
    should_retrain: bool
    reasons: list[str] = field(default_factory=list)
    matured_count: int = 0
    rolling_brier: Optional[float] = None
    rolling_win_rate: Optional[float] = None
    evaluated_at: str = ""

    def summary(self) -> str:
        status_str = "TRIGGERED" if self.should_retrain else "IDLE"
        wr_str = f"{self.rolling_win_rate:.2%}" if self.rolling_win_rate is not None else "N/A"
        brier_str = f"{self.rolling_brier:.4f}" if self.rolling_brier is not None else "N/A"
        reasons_str = "; ".join(self.reasons) if self.reasons else "None"
        return (
            f"[{status_str}] Matured: {self.matured_count} | Rolling Win Rate: {wr_str} | "
            f"Rolling Brier: {brier_str} | Reasons: {reasons_str}"
        )


class RetrainingTriggerEvaluator:
    """Evaluates volume, performance degradation, and manual triggers for retraining."""

    def __init__(
        self,
        config: Optional[RetrainingTriggerConfig] = None,
        outcome_repo: Optional[OutcomeRepository] = None,
        signal_repo: Optional[SignalRepository] = None,
    ) -> None:
        self.config = config or RetrainingTriggerConfig()
        self.outcome_repo = outcome_repo or OutcomeRepository()
        self.signal_repo = signal_repo or SignalRepository()

    def evaluate(
        self,
        force: bool = False,
        since_date: Optional[date] = None,
        min_matured_samples: Optional[int] = None,
    ) -> RetrainingTriggerResult:
        reasons: list[str] = []
        is_forced = force or self.config.force

        if is_forced:
            reasons.append("Manual / forced trigger requested by operator.")

        outcomes = self.outcome_repo.get_matured_outcomes(start_date=since_date)
        matured_count = len(outcomes)
        threshold = (
            min_matured_samples
            if min_matured_samples is not None
            else self.config.min_matured_samples
        )

        if matured_count >= threshold:
            reasons.append(
                f"Volume trigger: Accumulated matured outcomes ({matured_count}) "
                f">= threshold ({threshold})."
            )

        rolling_win_rate: Optional[float] = None
        rolling_brier: Optional[float] = None

        if matured_count > 0:
            k = min(matured_count, self.config.rolling_window_size)
            window = outcomes[-k:]

            wins = sum(
                1
                for o in window
                if o.outcome_status.upper() == "TP"
                or (o.realized_return is not None and o.realized_return > 0)
            )
            rolling_win_rate = float(wins / len(window))

            min_check_size = min(10, self.config.rolling_window_size)
            if len(window) >= min_check_size:
                if rolling_win_rate < self.config.win_rate_safety_floor:
                    reasons.append(
                        f"Performance degradation: Rolling win rate ({rolling_win_rate:.2%}) "
                        f"below safety floor ({self.config.win_rate_safety_floor:.2%})."
                    )

                y_true: list[float] = []
                y_prob: list[float] = []
                for o in window:
                    sig = self.signal_repo.get_signal_by_id(o.signal_id)
                    if sig is not None and sig.predicted_probability is not None:
                        y_true.append(1.0 if o.outcome_status.upper() == "TP" else 0.0)
                        y_prob.append(float(sig.predicted_probability))

                if len(y_true) >= min_check_size:
                    rolling_brier = float(np.mean((np.array(y_prob) - np.array(y_true)) ** 2))
                    if rolling_brier > self.config.brier_safety_floor:
                        reasons.append(
                            f"Performance degradation: Rolling Brier score ({rolling_brier:.4f}) "
                            f"exceeded safety floor ({self.config.brier_safety_floor:.4f})."
                        )

        should_retrain = len(reasons) > 0
        if not should_retrain:
            reasons.append(
                f"Threshold not met: {matured_count}/{threshold} matured outcomes; "
                f"performance within normal bounds."
            )

        return RetrainingTriggerResult(
            should_retrain=should_retrain,
            reasons=reasons,
            matured_count=matured_count,
            rolling_brier=rolling_brier,
            rolling_win_rate=rolling_win_rate,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
