import sqlite3
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.outcomes.repository import OutcomeRepository


def run_audit() -> None:
    out_repo = OutcomeRepository("datasets/stock_signals.db")
    conn = sqlite3.connect("datasets/stock_signals.db")
    conn.row_factory = sqlite3.Row

    outcomes = out_repo.get_matured_outcomes()
    print(f"Total matured outcomes retrieved: {len(outcomes)}")

    verified_count = 0
    violations: list[str] = []
    sample_for_report: list[dict] = []

    for _idx, out in enumerate(outcomes):
        # 1. Check unfilled breakout and invalidated gap invariants
        if out.outcome_status in ("UNFILLED_EXPIRED", "INVALIDATED_GAP"):
            if out.entry_status != "UNFILLED":
                violations.append(
                    f"{out.signal_id}: {out.outcome_status} entry_status != 'UNFILLED' "
                    f"({out.entry_status})"
                )
            if out.entry_date is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} entry_date is not None")
            if out.entry_price is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} entry_price is not None")
            if out.exit_date is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} exit_date is not None")
            if out.exit_price is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} exit_price is not None")
            if out.realized_return is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} has realized_return")
            if out.gross_return is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} has gross_return")
            if out.return_after_fees is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} has return_after_fees")
            if out.return_after_fees_and_slippage is not None:
                violations.append(
                    f"{out.signal_id}: {out.outcome_status} has return_after_fees_and_slippage"
                )
            if out.holding_days != 0:
                violations.append(f"{out.signal_id}: {out.outcome_status} holding_days != 0")
            if out.net_return is not None:
                violations.append(f"{out.signal_id}: {out.outcome_status} net_return is not None")
            if out.mfe is not None or out.mae is not None:
                violations.append(
                    f"{out.signal_id}: {out.outcome_status} trade MFE/MAE is not None"
                )
            if out.trigger_price is None:
                violations.append(f"{out.signal_id}: {out.outcome_status} trigger_price is None")
            if out.observation_end_date is None:
                violations.append(
                    f"{out.signal_id}: {out.outcome_status} observation_end_date is None"
                )
            # Verify 0 snapshots for unfilled/invalidated outcomes
            snap_count = conn.execute(
                "SELECT COUNT(*) FROM signal_snapshots_daily WHERE signal_id=?",
                (out.signal_id,),
            ).fetchone()[0]
            if snap_count != 0:
                violations.append(
                    f"{out.signal_id}: {out.outcome_status} has {snap_count} snapshots (expected 0)"
                )
        else:
            # Filled trades
            if out.entry_status != "FILLED":
                violations.append(
                    f"{out.signal_id}: Filled trade entry_status != 'FILLED' ({out.entry_status})"
                )
            if out.entry_date is None or out.entry_price is None:
                violations.append(
                    f"{out.signal_id}: Filled trade entry_date or entry_price is None"
                )
            if out.holding_days <= 0:
                violations.append(f"{out.signal_id}: Filled trade holding_days <= 0")
            # Verify snapshot count matches holding_days for filled trades
            snap_count = conn.execute(
                "SELECT COUNT(*) FROM signal_snapshots_daily WHERE signal_id=?",
                (out.signal_id,),
            ).fetchone()[0]
            if snap_count != out.holding_days:
                violations.append(
                    f"{out.signal_id}: Filled trade snap_count {snap_count} != "
                    f"holding_days {out.holding_days}"
                )
            if out.exit_price is None:
                violations.append(f"{out.signal_id}: Filled trade exit_price is None")
            if out.exit_date is None:
                violations.append(f"{out.signal_id}: Filled trade exit_date is None")
            if out.realized_return is None:
                violations.append(f"{out.signal_id}: Filled trade realized_return is None")

            # Check MFE / MAE bounds for filled trades
            if out.mfe is not None and out.mfe < -1e-9:
                violations.append(f"{out.signal_id}: Negative MFE {out.mfe}")
            if out.mae is not None and out.mae > 1e-9:
                violations.append(f"{out.signal_id}: Positive MAE {out.mae}")
            if out.mfe_price is not None and out.mfe_price < -1e-9:
                violations.append(f"{out.signal_id}: Negative mfe_price {out.mfe_price}")
            if out.mae_price is not None and out.mae_price > 1e-9:
                violations.append(f"{out.signal_id}: Positive mae_price {out.mae_price}")

            # Check explicit excursion bounds and entry deviation
            if (
                out.mfe_min is None
                or out.mfe_max is None
                or out.mae_min is None
                or out.mae_max is None
            ):
                violations.append(f"{out.signal_id}: Filled trade missing excursion bounds")
            else:
                if out.mfe_min > (out.mfe or 0.0) + 1e-9:
                    violations.append(
                        f"{out.signal_id}: mfe_min {out.mfe_min} > mfe {out.mfe}"
                    )
                if (out.mfe or 0.0) > out.mfe_max + 1e-9:
                    violations.append(
                        f"{out.signal_id}: mfe {out.mfe} > mfe_max {out.mfe_max}"
                    )
                if out.mae_min > (out.mae or 0.0) + 1e-9:
                    violations.append(
                        f"{out.signal_id}: mae_min {out.mae_min} > mae {out.mae}"
                    )
                if (out.mae or 0.0) > out.mae_max + 1e-9:
                    violations.append(
                        f"{out.signal_id}: mae {out.mae} > mae_max {out.mae_max}"
                    )

            if out.entry_deviation_pct is None:
                violations.append(f"{out.signal_id}: Filled trade missing entry_deviation_pct")

            # Final snapshot parity check
            last_snap = conn.execute(
                "SELECT * FROM signal_snapshots_daily "
                "WHERE signal_id=? ORDER BY holding_day DESC LIMIT 1",
                (out.signal_id,),
            ).fetchone()
            if last_snap:
                if out.mfe is not None and abs(last_snap["mfe_so_far"] - out.mfe) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: Final snapshot mfe_so_far {last_snap['mfe_so_far']} "
                        f"!= outcome mfe {out.mfe}"
                    )
                if out.mae is not None and abs(last_snap["mae_so_far"] - out.mae) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: Final snapshot mae_so_far {last_snap['mae_so_far']} "
                        f"!= outcome mae {out.mae}"
                    )
                if out.mfe_min is not None and last_snap["mfe_min_so_far"] is not None:
                    if abs(last_snap["mfe_min_so_far"] - out.mfe_min) > 1e-5:
                        violations.append(
                            f"{out.signal_id}: Final snapshot mfe_min_so_far "
                            f"{last_snap['mfe_min_so_far']} != outcome {out.mfe_min}"
                        )
                if out.mfe_max is not None and last_snap["mfe_max_so_far"] is not None:
                    if abs(last_snap["mfe_max_so_far"] - out.mfe_max) > 1e-5:
                        violations.append(
                            f"{out.signal_id}: Final snapshot mfe_max_so_far "
                            f"{last_snap['mfe_max_so_far']} != outcome {out.mfe_max}"
                        )
                if out.mae_min is not None and last_snap["mae_min_so_far"] is not None:
                    if abs(last_snap["mae_min_so_far"] - out.mae_min) > 1e-5:
                        violations.append(
                            f"{out.signal_id}: Final snapshot mae_min_so_far "
                            f"{last_snap['mae_min_so_far']} != outcome {out.mae_min}"
                        )
                if out.mae_max is not None and last_snap["mae_max_so_far"] is not None:
                    if abs(last_snap["mae_max_so_far"] - out.mae_max) > 1e-5:
                        violations.append(
                            f"{out.signal_id}: Final snapshot mae_max_so_far "
                            f"{last_snap['mae_max_so_far']} != outcome {out.mae_max}"
                        )

            # Check fee and slippage math
            if (
                out.return_after_fees is not None
                and out.exit_price is not None
                and out.entry_price is not None
            ):
                c_b = 0.0015
                c_s = 0.0025
                expected_fees = (
                    (out.exit_price * (1.0 - c_s)) / (out.entry_price * (1.0 + c_b))
                ) - 1.0
                if abs(out.return_after_fees - expected_fees) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: return_after_fees mismatch {out.return_after_fees} "
                        f"vs {expected_fees}"
                    )

            if (
                out.return_after_fees_and_slippage is not None
                and out.exit_price is not None
                and out.entry_price is not None
            ):
                c_b = 0.0015
                c_s = 0.0025
                s_half = 0.0005
                expected_all = (
                    (out.exit_price * (1.0 - s_half) * (1.0 - c_s))
                    / (out.entry_price * (1.0 + s_half) * (1.0 + c_b))
                ) - 1.0
                if abs(out.return_after_fees_and_slippage - expected_all) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: return_after_fees_and_slippage mismatch "
                        f"{out.return_after_fees_and_slippage} vs {expected_all}"
                    )
                if out.net_return is not None and abs(out.net_return - expected_all) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: net_return mismatch {out.net_return} vs {expected_all}"
                    )

            # Check exit bar bounded excursions
            # Fetch exit bar
            exit_bar = conn.execute(
                "SELECT * FROM daily_bars WHERE ticker=? AND date=?",
                (out.ticker, out.exit_date.isoformat()),
            ).fetchone()
            if exit_bar and out.entry_price is not None:
                # If gap exit at open
                is_open_exit = abs(exit_bar["open"] - out.exit_price) < 1e-4
                if is_open_exit:
                    if out.holding_days == 1:
                        # Should have 0 MFE/MAE if open was entry
                        if abs(exit_bar["open"] - out.entry_price) < 1e-4:
                            if abs(out.mfe or 0.0) > 1e-4 or abs(out.mae or 0.0) > 1e-4:
                                violations.append(
                                    f"{out.signal_id}: Gap exit on day 1 should have 0 MFE/MAE, "
                                    f"got {out.mfe}/{out.mae}"
                                )
                elif out.outcome_status == "TP":
                    # In-trade MFE should be bounded by exit_price
                    max_allowed_mfe = max(
                        0.0, (out.exit_price - out.entry_price) / out.entry_price
                    )
                    if out.mfe is not None and out.mfe > max_allowed_mfe + 1e-4:
                        violations.append(
                            f"{out.signal_id}: TP trade MFE {out.mfe} exceeds exit bound "
                            f"{max_allowed_mfe}"
                        )
                elif out.outcome_status == "SL":
                    # In-trade low on exit day is bounded by exit_price
                    # If stopped out intraday on day 1:
                    if out.holding_days == 1:
                        min_allowed_mae = min(
                            0.0, (out.exit_price - out.entry_price) / out.entry_price
                        )
                        if out.mae is not None and out.mae < min_allowed_mae - 1e-4:
                            violations.append(
                                f"{out.signal_id}: Day 1 SL trade MAE {out.mae} exceeded "
                                f"stop bound {min_allowed_mae}"
                            )

        # 3. Full-horizon opportunity check
        if out.full_horizon_mfe is not None and out.full_horizon_mfe < -1e-9:
            violations.append(f"{out.signal_id}: Negative full_horizon_mfe {out.full_horizon_mfe}")
        if out.full_horizon_mae is not None and out.full_horizon_mae > 1e-9:
            violations.append(f"{out.signal_id}: Positive full_horizon_mae {out.full_horizon_mae}")

        verified_count += 1
        sample_for_report.append(
            {
                "ticker": out.ticker,
                "signal_date": str(out.signal_date),
                "entry_date": str(out.entry_date) if out.entry_date else "-",
                "entry_price": out.entry_price,
                "status": out.outcome_status,
                "exit_date": str(out.exit_date) if out.exit_date else "-",
                "exit_price": out.exit_price,
                "realized_return": out.realized_return,
                "return_after_fees": out.return_after_fees,
                "net_return": out.net_return,
                "holding_days": out.holding_days,
                "mfe": out.mfe,
                "mae": out.mae,
                "full_horizon_mfe": out.full_horizon_mfe,
                "full_horizon_mae": out.full_horizon_mae,
                "time_to_peak": out.time_to_peak,
                "full_horizon_time_to_peak": out.full_horizon_time_to_peak,
                "mode": out.mode,
            }
        )

    print(f"Verification finished. Verified {verified_count} records.")
    print(f"Violations found: {len(violations)}")
    if violations:
        for v in violations[:10]:
            print("  VIOLATION:", v)
    else:
        print("ALL INVARIANTS, BOUNDED EXCURSIONS, AND FEES/SLIPPAGE PASSED 100%!")


if __name__ == "__main__":
    run_audit()
