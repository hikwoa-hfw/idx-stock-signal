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
        # 1. Check MFE / MAE bounds
        if out.mfe < -1e-9:
            violations.append(f"{out.signal_id}: Negative MFE {out.mfe}")
        if out.mae > 1e-9:
            violations.append(f"{out.signal_id}: Positive MAE {out.mae}")
        if out.mfe_price is not None and out.mfe_price < -1e-9:
            violations.append(f"{out.signal_id}: Negative mfe_price {out.mfe_price}")
        if out.mae_price is not None and out.mae_price > 1e-9:
            violations.append(f"{out.signal_id}: Positive mae_price {out.mae_price}")

        # 2. Check unfilled breakout invariants
        if out.outcome_status == "UNFILLED_EXPIRED":
            if out.entry_status != "UNFILLED":
                violations.append(
                    f"{out.signal_id}: UNFILLED_EXPIRED entry_status != 'UNFILLED' "
                    f"({out.entry_status})"
                )
            if out.realized_return is not None:
                violations.append(f"{out.signal_id}: UNFILLED_EXPIRED has realized_return")
            if out.holding_days != 0:
                violations.append(f"{out.signal_id}: UNFILLED_EXPIRED holding_days != 0")
            if out.net_return is not None:
                violations.append(f"{out.signal_id}: UNFILLED_EXPIRED net_return is not None")
        else:
            # Filled trades
            if out.entry_status != "FILLED":
                violations.append(
                    f"{out.signal_id}: Filled trade entry_status != 'FILLED' ({out.entry_status})"
                )
            if out.holding_days <= 0:
                violations.append(f"{out.signal_id}: Filled trade holding_days <= 0")
            if out.exit_price is None:
                violations.append(f"{out.signal_id}: Filled trade exit_price is None")
            if out.realized_return is None:
                violations.append(f"{out.signal_id}: Filled trade realized_return is None")
            # Check net return
            if out.net_return is not None and out.realized_return is not None:
                c_b = 0.0015
                c_s = 0.0025
                gross_proceeds = out.exit_price * (1.0 - c_s)
                gross_cost = out.entry_price * (1.0 + c_b)
                expected_net = (gross_proceeds / gross_cost) - 1.0
                if abs(out.net_return - expected_net) > 1e-5:
                    violations.append(
                        f"{out.signal_id}: Net return mismatch {out.net_return} vs {expected_net}"
                    )

        # 3. Independent bar verification
        if out.outcome_status != "UNFILLED_EXPIRED":
            bars = conn.execute(
                "SELECT * FROM daily_bars WHERE ticker=? AND date >= ? AND date <= ? "
                "ORDER BY date ASC",
                (out.ticker, out.entry_date.isoformat(), out.exit_date.isoformat()),
            ).fetchall()
            if len(bars) != out.holding_days:
                violations.append(
                    f"{out.signal_id}: Bar count {len(bars)} != holding_days {out.holding_days}"
                )
            if bars:
                highs = [float(b["high"]) for b in bars]
                lows = [float(b["low"]) for b in bars]
                indep_mfe = max(0.0, (max(highs) - out.entry_price) / out.entry_price)
                indep_mae = min(0.0, (min(lows) - out.entry_price) / out.entry_price)
                if abs(out.mfe - indep_mfe) > 1e-4:
                    violations.append(
                        f"{out.signal_id}: MFE mismatch {out.mfe} vs indep {indep_mfe}"
                    )
                if abs(out.mae - indep_mae) > 1e-4:
                    violations.append(
                        f"{out.signal_id}: MAE mismatch {out.mae} vs indep {indep_mae}"
                    )

        verified_count += 1
        sample_for_report.append(
            {
                "ticker": out.ticker,
                "signal_date": str(out.signal_date),
                "entry_date": str(out.entry_date),
                "entry_price": out.entry_price,
                "status": out.outcome_status,
                "exit_date": str(out.exit_date) if out.exit_date else "-",
                "exit_price": out.exit_price,
                "realized_return": out.realized_return,
                "net_return": out.net_return,
                "holding_days": out.holding_days,
                "mfe": out.mfe,
                "mae": out.mae,
                "time_to_peak": out.time_to_peak,
                "time_to_tp": out.time_to_tp,
                "time_to_sl": out.time_to_sl,
                "mode": out.mode,
            }
        )

    print(f"Verification finished. Verified {verified_count} records.")
    print(f"Violations found: {len(violations)}")
    if violations:
        for v in violations[:10]:
            print("  VIOLATION:", v)
    else:
        print("ALL INVARIANTS AND INDEPENDENT RE-CALCULATIONS PASSED 100%!")


if __name__ == "__main__":
    run_audit()
