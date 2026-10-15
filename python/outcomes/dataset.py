from datetime import date
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository


def build_matured_outcomes_dataset(
    outcome_repo: OutcomeRepository,
    signal_repo: SignalRepository,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    ticker: Optional[str] = None,
    mode: Optional[str] = None,
    exclude_ambiguous: bool = False,
    exclude_unfilled: bool = False,
) -> pd.DataFrame:
    """Merge matured outcomes with original signal metadata and feature snapshots."""
    eff_mode = mode.strip().upper() if mode and mode != "ALL" else None
    matured_outcomes = outcome_repo.get_matured_outcomes(
        start_date=start_date,
        end_date=end_date,
        ticker=ticker,
        mode=eff_mode,
    )
    if not matured_outcomes:
        return pd.DataFrame()

    # Pre-fetch candidate signals for fast batch lookup
    signals = signal_repo.get_signals(
        start_date=start_date,
        end_date=end_date,
        ticker=ticker,
        mode=eff_mode,
    )
    sig_map = {s.signal_id: s for s in signals}

    rows: list[dict] = []
    for out in matured_outcomes:
        if exclude_ambiguous and out.outcome_status == "AMBIGUOUS":
            continue
        if exclude_unfilled and out.outcome_status == "UNFILLED_EXPIRED":
            continue

        row: dict = {
            "outcome_id": out.outcome_id,
            "signal_id": out.signal_id,
            "ticker": out.ticker,
            "signal_date": out.signal_date.isoformat(),
            "entry_date": out.entry_date.isoformat() if out.entry_date else None,
            "entry_price": out.entry_price,
            "entry_status": out.entry_status,
            "outcome_status": out.outcome_status,
            "binary_target": 1 if out.outcome_status == "TP" else 0,
            "realized_return": out.realized_return,
            "gross_return": out.gross_return,
            "return_after_fees": out.return_after_fees,
            "return_after_fees_and_slippage": out.return_after_fees_and_slippage,
            "holding_days": out.holding_days,
            "mfe": out.mfe,
            "mae": out.mae,
            "mfe_price": out.mfe_price,
            "mae_price": out.mae_price,
            "time_to_peak": out.time_to_peak,
            "time_to_tp": out.time_to_tp,
            "time_to_sl": out.time_to_sl,
            "net_return": out.net_return,
            "exit_date": out.exit_date.isoformat() if out.exit_date else None,
            "exit_price": out.exit_price,
            "exit_reason": out.exit_reason,
            "resolved_at": out.resolved_at.isoformat() if out.resolved_at else None,
            "notes": out.notes,
            "mode": out.mode_id,
            "trigger_price": out.trigger_price,
            "observation_end_date": (
                out.observation_end_date.isoformat() if out.observation_end_date else None
            ),
            "full_horizon_mfe": out.full_horizon_mfe,
            "full_horizon_mae": out.full_horizon_mae,
            "full_horizon_mfe_price": out.full_horizon_mfe_price,
            "full_horizon_mae_price": out.full_horizon_mae_price,
            "full_horizon_time_to_peak": out.full_horizon_time_to_peak,
            "horizon_end_date": (
                out.horizon_end_date.isoformat() if out.horizon_end_date else None
            ),
            "horizon_end_price": out.horizon_end_price,
            "horizon_end_return": out.horizon_end_return,
            "is_full_horizon_complete": out.is_full_horizon_complete,
        }

        signal = sig_map.get(out.signal_id) or signal_repo.get_signal_by_id(out.signal_id)
        if signal is not None:
            row.update(
                {
                    "signal_action": signal.signal,
                    "signal_entry_low": signal.entry_low,
                    "signal_entry_high": signal.entry_high,
                    "signal_tp_price": signal.tp_price,
                    "signal_sl_price": signal.sl_price,
                    "signal_max_holding_days": signal.max_holding_days,
                    "predicted_probability": signal.predicted_probability,
                    "expected_return": signal.expected_return,
                    "signal_score": signal.score,
                    "model_version": signal.model_version,
                    "feature_version": signal.feature_version,
                    "signal_config_version": signal.signal_config_version,
                    "signal_created_at": signal.created_at.isoformat(),
                }
            )
            if signal.feature_snapshot:
                for feat_k, feat_v in signal.feature_snapshot.items():
                    # Prefix only if key collides with core outcome/signal column
                    col_name = feat_k if feat_k not in row else f"feat_{feat_k}"
                    row[col_name] = feat_v
        else:
            row.update(
                {
                    "signal_action": None,
                    "signal_entry_low": None,
                    "signal_entry_high": None,
                    "signal_tp_price": None,
                    "signal_sl_price": None,
                    "signal_max_holding_days": None,
                    "predicted_probability": None,
                    "expected_return": None,
                    "signal_score": None,
                    "model_version": None,
                    "feature_version": None,
                    "signal_config_version": None,
                    "signal_created_at": None,
                }
            )

        rows.append(row)

    return pd.DataFrame(rows)


def export_matured_dataset(
    df: pd.DataFrame,
    output_path: Union[str, Path],
    format: str = "csv",
) -> Path:
    """Export the matured dataset to CSV or JSON format."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fmt = format.strip().lower()
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", indent=2, date_format="iso")
    else:
        raise ValueError(f"Unsupported export format '{format}'. Expected 'csv' or 'json'.")

    return path
