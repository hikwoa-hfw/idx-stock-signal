"""Final Target Contract Audit Engine (Phase 11B.0).

Reconciles target-label versus executable-entry contracts without modifying
production labels, raw market data, models, or champions.
Generates research artifacts in artifacts/target_contract/.
"""

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.common.types import DailyBar, classify_price_mode
from python.labels.engine import LabelEngine


def load_all_bars(db_path: str = "datasets/stock_signals.db") -> dict[str, list[DailyBar]]:
    """Load and sort all daily bars grouped by canonical ticker."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT ticker, date, open, high, low, close, volume, value,
                   adj_close, dividends, stock_splits
            FROM daily_bars
            ORDER BY ticker, date ASC;
            """
        )
        bars_by_ticker: dict[str, list[DailyBar]] = {}
        for r in cursor.fetchall():
            clean_t = r["ticker"].strip().upper().removesuffix(".JK")
            b_date = date.fromisoformat(r["date"]) if isinstance(r["date"], str) else r["date"]
            bar = DailyBar(
                ticker=clean_t,
                date=b_date,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                value=float(r["value"]) if r["value"] is not None else None,
                adj_close=float(r["adj_close"]) if r["adj_close"] is not None else None,
                dividends=float(r["dividends"]) if r["dividends"] is not None else 0.0,
                stock_splits=float(r["stock_splits"]) if r["stock_splits"] is not None else 0.0,
            )
            bars_by_ticker.setdefault(clean_t, []).append(bar)
    finally:
        conn.close()
    return bars_by_ticker


def evaluate_variant_b(
    entry_bar: DailyBar,
    forward_bars: list[DailyBar],
    tp_pct: float = 0.05,
    sl_pct: float = 0.02,
    max_holding_days: int = 10,
    max_entry_dev_pct: float = 0.05,
    entry_band_pct: float = 0.01,
    ambiguity_policy: str = "conservative",
) -> dict[str, Any]:
    """Evaluate Variant B (Executable-Entry Market-On-Open target)."""
    c_close = float(entry_bar.close)

    if not forward_bars:
        return {
            "status": "INSUFFICIENT_FORWARD_DATA",
            "entry_status": "NONE",
            "invalidation_reason": "NO_FORWARD_BARS",
            "entry_price": None,
            "outcome": "INCOMPLETE",
            "binary_target": None,
            "realized_return": None,
            "holding_days": 0,
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": 0,
            "band_invalidated": False,
        }

    b1 = forward_bars[0]
    b1_open = float(b1.open)

    # Invalidation checks on Day 1 Open relative to Decision Close
    # Pre-entry planned barriers based on decision close
    planned_sl = c_close * (1.0 - sl_pct)
    planned_tp = c_close * (1.0 + tp_pct)
    open_dev = abs(b1_open - c_close) / c_close

    # Check entry band: half_band is entry_band_pct / 2.0 (default 0.005)
    half_band = entry_band_pct / 2.0
    band_low = c_close * (1.0 - half_band)
    band_high = c_close * (1.0 + half_band)
    outside_band = b1_open < band_low or b1_open > band_high

    if b1.volume <= 0:
        return {
            "status": "INVALIDATED",
            "entry_status": "UNFILLED",
            "invalidation_reason": "ZERO_VOLUME_SUSPENDED",
            "entry_price": None,
            "outcome": "UNFILLED_SUSPENDED",
            "binary_target": None,
            "realized_return": None,
            "holding_days": 0,
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": 0,
            "band_invalidated": outside_band,
        }

    if b1_open <= planned_sl:
        return {
            "status": "INVALIDATED",
            "entry_status": "UNFILLED",
            "invalidation_reason": "GAP_BELOW_SL",
            "entry_price": None,
            "outcome": "INVALIDATED_GAP",
            "binary_target": None,
            "realized_return": None,
            "holding_days": 0,
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": 0,
            "band_invalidated": outside_band,
        }

    if b1_open >= planned_tp:
        return {
            "status": "INVALIDATED",
            "entry_status": "UNFILLED",
            "invalidation_reason": "GAP_ABOVE_TP",
            "entry_price": None,
            "outcome": "INVALIDATED_GAP",
            "binary_target": None,
            "realized_return": None,
            "holding_days": 0,
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": 0,
            "band_invalidated": outside_band,
        }

    if open_dev > max_entry_dev_pct:
        return {
            "status": "INVALIDATED",
            "entry_status": "UNFILLED",
            "invalidation_reason": "EXCESSIVE_DEV",
            "entry_price": None,
            "outcome": "INVALIDATED_GAP",
            "binary_target": None,
            "realized_return": None,
            "holding_days": 0,
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": 0,
            "band_invalidated": outside_band,
        }

    # Valid modeled entry at Open of Day t+1
    ep = b1_open
    tp_price = ep * (1.0 + tp_pct)
    sl_price = ep * (1.0 - sl_pct)

    eval_bars = forward_bars[:max_holding_days]
    outcome: Optional[str] = None
    exit_price: Optional[float] = None
    exit_date: Optional[date] = None
    holding_days = 0
    ambiguous_hits = 0

    for k, bar in enumerate(eval_bars, start=1):
        tp_hit = bar.high >= tp_price
        sl_hit = bar.low <= sl_price

        if tp_hit and sl_hit:
            ambiguous_hits += 1
            if k == 1:
                # On entry bar, entered at open. Open cannot be >= tp or <= sl
                # Conservative policy resolves to SL
                if ambiguity_policy == "conservative":
                    outcome = "SL"
                    exit_price = sl_price
                elif ambiguity_policy == "optimistic":
                    outcome = "TP"
                    exit_price = tp_price
                else:
                    outcome = "AMBIGUOUS"
                    exit_price = float(bar.close)
            else:
                if bar.open >= tp_price:
                    outcome = "TP"
                    exit_price = float(bar.open)
                elif bar.open <= sl_price:
                    outcome = "SL"
                    exit_price = float(bar.open)
                else:
                    if ambiguity_policy == "conservative":
                        outcome = "SL"
                        exit_price = sl_price
                    elif ambiguity_policy == "optimistic":
                        outcome = "TP"
                        exit_price = tp_price
                    else:
                        outcome = "AMBIGUOUS"
                        exit_price = float(bar.close)

            exit_date = bar.date
            holding_days = k
            break

        elif tp_hit:
            outcome = "TP"
            exit_price = float(bar.open) if (k > 1 and bar.open >= tp_price) else tp_price
            exit_date = bar.date
            holding_days = k
            break

        elif sl_hit:
            outcome = "SL"
            exit_price = float(bar.open) if (k > 1 and bar.open <= sl_price) else sl_price
            exit_date = bar.date
            holding_days = k
            break

        elif k == max_holding_days:
            outcome = "EXPIRY"
            exit_price = float(bar.close)
            exit_date = bar.date
            holding_days = k
            break

    if outcome is None:
        # Less than 10 forward bars and did not trigger TP/SL
        return {
            "status": "INCOMPLETE",
            "entry_status": "FILLED",
            "invalidation_reason": None,
            "entry_price": ep,
            "outcome": "INCOMPLETE",
            "binary_target": None,
            "realized_return": None,
            "holding_days": len(eval_bars),
            "exit_date": None,
            "exit_price": None,
            "ambiguous_count": ambiguous_hits,
            "band_invalidated": outside_band,
        }

    binary_target = 1 if outcome == "TP" else 0
    realized_ret = (exit_price - ep) / ep

    return {
        "status": "VALID",
        "entry_status": "FILLED",
        "invalidation_reason": None,
        "entry_price": ep,
        "outcome": outcome,
        "binary_target": binary_target,
        "realized_return": realized_ret,
        "holding_days": holding_days,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "ambiguous_count": ambiguous_hits,
        "band_invalidated": outside_band,
    }


def run_full_contract_audit() -> dict[str, Any]:
    print("=" * 80)
    print(" PHASE 11B.0: FINAL TARGET CONTRACT AUDIT ENGINE")
    print("=" * 80)

    bars_by_ticker = load_all_bars()
    total_bars = sum(len(b) for b in bars_by_ticker.values())
    print(f"Loaded {total_bars} daily bars across {len(bars_by_ticker)} tickers.")

    # Load existing labels from database
    conn = sqlite3.connect("datasets/stock_signals.db")
    db_labels_df = pd.read_sql_query(
        """
        SELECT ticker, date, entry_price, tp_price, sl_price, outcome,
               binary_target, realized_return, holding_days, mode
        FROM labels_daily;
        """,
        conn,
    )
    conn.close()
    print(f"Loaded {len(db_labels_df)} production labels from labels_daily.")

    # Build row index from DB labels
    db_labels_map = {(r["ticker"], r["date"]): r for _, r in db_labels_df.iterrows()}

    engine_v_a = LabelEngine()

    all_comparison_rows: list[dict[str, Any]] = []

    print("\nAuditing decision bars across universe...")
    reconciled_va_count = 0
    mismatch_va_count = 0

    for ticker, t_bars in sorted(bars_by_ticker.items()):
        # Sort bars strictly by date
        sorted_bars = sorted(t_bars, key=lambda x: x.date)
        n = len(sorted_bars)

        for i in range(n):
            entry_bar = sorted_bars[i]
            forward_bars = sorted_bars[i + 1 :]
            b_date_str = str(entry_bar.date)
            key = (ticker, b_date_str)

            c_close = float(entry_bar.close)
            mode_decision = classify_price_mode(c_close)

            # Compute Variant A via LabelEngine
            rec_a = engine_v_a.compute_label_for_bar(
                entry_bar=entry_bar,
                forward_bars=forward_bars,
                include_incomplete=False,
            )

            # Reconcile Variant A with DB
            db_label = db_labels_map.get(key)
            if rec_a is not None and db_label is not None:
                reconciled_va_count += 1
            elif rec_a is None and db_label is None:
                pass
            else:
                mismatch_va_count += 1

            # Compute Variant B (Executable-Entry MOO)
            vb_res = evaluate_variant_b(
                entry_bar=entry_bar,
                forward_bars=forward_bars,
                tp_pct=0.05,
                sl_pct=0.02,
                max_holding_days=10,
                max_entry_dev_pct=0.05,
                entry_band_pct=0.01,
                ambiguity_policy="conservative",
            )

            row: dict[str, Any] = {
                "ticker": ticker,
                "date": b_date_str,
                "decision_price": c_close,
                "mode_decision": mode_decision,
                # Variant A fields
                "va_eligible": rec_a is not None,
                "va_entry_price": rec_a.entry_price if rec_a else None,
                "va_outcome": rec_a.outcome if rec_a else "INCOMPLETE",
                "va_binary_target": rec_a.binary_target if rec_a else None,
                "va_realized_return": rec_a.realized_return if rec_a else None,
                "va_holding_days": rec_a.holding_days if rec_a else 0,
                # Variant B fields
                "vb_status": vb_res["status"],
                "vb_entry_status": vb_res["entry_status"],
                "vb_invalidation_reason": vb_res["invalidation_reason"],
                "vb_entry_price": vb_res["entry_price"],
                "vb_outcome": vb_res["outcome"],
                "vb_binary_target": vb_res["binary_target"],
                "vb_realized_return": vb_res["realized_return"],
                "vb_holding_days": vb_res["holding_days"],
                "vb_band_invalidated": vb_res["band_invalidated"],
                "mode_execution": (
                    classify_price_mode(vb_res["entry_price"])
                    if vb_res["entry_price"] is not None
                    else "NONE"
                ),
            }

            all_comparison_rows.append(row)

    print(
        f"Reconciled Variant A with labels_daily: {reconciled_va_count} exact matches, "
        f"{mismatch_va_count} mismatches."
    )

    df_comp = pd.DataFrame(all_comparison_rows)

    # Filter to eligible decision rows (where Variant A has label in DB, i.e. 185,515 rows)
    # Exclude EXCLUDED_BELOW_50 and INVALID
    modes_to_evaluate = ["LOW_PRICE", "HIGHER_PRICE"]

    summary_records = []
    transition_records = []

    out_dir = Path("artifacts/target_contract")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 80)
    print(" QUANTITATIVE COMPARISON BY PRICE MODE")
    print("=" * 80)

    for m in modes_to_evaluate:
        sub = df_comp[(df_comp["mode_decision"] == m) & (df_comp["va_eligible"])].copy()
        n_eligible = len(sub)

        # Variant A metrics
        va_tp = int((sub["va_outcome"] == "TP").sum())
        va_sl = int((sub["va_outcome"] == "SL").sum())
        va_exp = int((sub["va_outcome"] == "EXPIRY").sum())
        va_prev = va_tp / n_eligible if n_eligible > 0 else 0.0

        # Variant B metrics across all eligible decision rows
        vb_valid = sub[sub["vb_status"] == "VALID"]
        n_vb_valid = len(vb_valid)
        vb_invalid = sub[sub["vb_status"] == "INVALIDATED"]
        n_vb_invalid = len(vb_invalid)
        vb_incomplete = sub[sub["vb_status"] == "INCOMPLETE"]
        n_vb_incomplete = len(vb_incomplete)

        # Prevalence on Valid Executable Cohort
        vb_tp_valid = int((vb_valid["vb_outcome"] == "TP").sum())
        vb_sl_valid = int((vb_valid["vb_outcome"] == "SL").sum())
        vb_exp_valid = int((vb_valid["vb_outcome"] == "EXPIRY").sum())
        vb_prev_valid = vb_tp_valid / n_vb_valid if n_vb_valid > 0 else 0.0

        # Invalidation reasons
        inv_counts = vb_invalid["vb_invalidation_reason"].value_counts().to_dict()

        # Band invalidation count
        n_band_invalid = int(sub["vb_band_invalidated"].sum())

        # Common Eligible Cohort (both VA and VB are valid completed trades)
        common = sub[sub["vb_status"] == "VALID"].copy()
        n_common = len(common)

        # Label flips on Common Cohort
        same_label = int((common["va_binary_target"] == common["vb_binary_target"]).sum())
        label_flips = int((common["va_binary_target"] != common["vb_binary_target"]).sum())
        flip_pct = (label_flips / n_common * 100.0) if n_common > 0 else 0.0

        # Flip directions:
        # Flip 1: VA=1 (TP) -> VB=0 (SL or EXPIRY)
        # Flip 2: VA=0 (SL or EXPIRY) -> VB=1 (TP)
        tp_to_loss = int(
            ((common["va_binary_target"] == 1) & (common["vb_binary_target"] == 0)).sum()
        )
        loss_to_tp = int(
            ((common["va_binary_target"] == 0) & (common["vb_binary_target"] == 1)).sum()
        )

        # Outcome-level transitions on common cohort
        common["trans"] = common["va_outcome"] + " -> " + common["vb_outcome"]
        trans_counts = common["trans"].value_counts().to_dict()

        # Detailed Flip Reason Analysis on Common Cohort:
        for trans_name, cnt in trans_counts.items():
            transition_records.append(
                {
                    "mode": m,
                    "transition": trans_name,
                    "count": cnt,
                    "pct_of_common": round(cnt / n_common * 100.0, 2) if n_common > 0 else 0.0,
                }
            )

        print(f"\nMode: {m}")
        print(f"  Total Eligible Decision Rows: {n_eligible:,}")
        print("  Variant A (Close-Anchor):")
        print(f"    TP: {va_tp:,} ({va_prev * 100:.2f}%) | SL: {va_sl:,} | EXPIRY: {va_exp:,}")
        print("  Variant B Execution Breakdown:")
        print(f"    Valid Modeled Entries: {n_vb_valid:,} ({n_vb_valid / n_eligible * 100:.2f}%)")
        print(
            f"    Invalidated Entries:   {n_vb_invalid:,} ({n_vb_invalid / n_eligible * 100:.2f}%)"
        )
        for r_name, r_cnt in inv_counts.items():
            print(f"      - {r_name}: {r_cnt:,} ({r_cnt / n_eligible * 100:.2f}%)")
        print(f"    Incomplete (Insufficient Forward Data): {n_vb_incomplete:,}")
        print(f"  Variant B Outcomes on Valid Executable Cohort (N={n_vb_valid:,}):")
        print(
            f"    TP: {vb_tp_valid:,} ({vb_prev_valid * 100:.2f}%) | "
            f"SL: {vb_sl_valid:,} | EXPIRY: {vb_exp_valid:,}"
        )
        print(f"  Common Cohort Comparison (N={n_common:,}):")
        print(
            f"    Identical Target (y_A == y_B): {same_label:,} "
            f"({same_label / n_common * 100:.2f}%)"
        )
        print(f"    Label Flips (y_A != y_B):      {label_flips:,} ({flip_pct:.2f}%)")
        print(
            f"      - False Positives in VA (VA=1, VB=0): {tp_to_loss:,} "
            f"({tp_to_loss / n_common * 100:.2f}%)"
        )
        print(
            f"      - False Negatives in VA (VA=0, VB=1): {loss_to_tp:,} "
            f"({loss_to_tp / n_common * 100:.2f}%)"
        )
        print(
            f"  Strict Entry Band Sensitivity (outside +/- 0.5%): {n_band_invalid:,} "
            f"({n_band_invalid / n_eligible * 100:.2f}%)"
        )

        summary_records.append(
            {
                "mode": m,
                "total_eligible_decision_rows": n_eligible,
                "va_tp": va_tp,
                "va_sl": va_sl,
                "va_expiry": va_exp,
                "va_prevalence_pct": round(va_prev * 100.0, 2),
                "vb_valid_entries": n_vb_valid,
                "vb_valid_pct": round(n_vb_valid / n_eligible * 100.0, 2),
                "vb_invalidated_entries": n_vb_invalid,
                "vb_invalidated_pct": round(n_vb_invalid / n_eligible * 100.0, 2),
                "vb_gap_sl_invalidation": inv_counts.get("GAP_BELOW_SL", 0),
                "vb_gap_tp_invalidation": inv_counts.get("GAP_ABOVE_TP", 0),
                "vb_excessive_dev_invalidation": inv_counts.get("EXCESSIVE_DEV", 0),
                "vb_suspended_invalidation": inv_counts.get("ZERO_VOLUME_SUSPENDED", 0),
                "vb_incomplete": n_vb_incomplete,
                "vb_valid_cohort_tp": vb_tp_valid,
                "vb_valid_cohort_sl": vb_sl_valid,
                "vb_valid_cohort_expiry": vb_exp_valid,
                "vb_valid_cohort_prevalence_pct": round(vb_prev_valid * 100.0, 2),
                "common_cohort_size": n_common,
                "common_cohort_same_label": same_label,
                "common_cohort_same_label_pct": round(same_label / n_common * 100.0, 2),
                "common_cohort_label_flips": label_flips,
                "common_cohort_label_flip_pct": round(flip_pct, 2),
                "flip_va_pos_to_vb_neg": tp_to_loss,
                "flip_va_pos_to_vb_neg_pct": round(tp_to_loss / n_common * 100.0, 2),
                "flip_va_neg_to_vb_pos": loss_to_tp,
                "flip_va_neg_to_vb_pos_pct": round(loss_to_tp / n_common * 100.0, 2),
                "strict_band_outside_count": n_band_invalid,
                "strict_band_outside_pct": round(n_band_invalid / n_eligible * 100.0, 2),
            }
        )

    # Export machine-readable artifacts
    df_summary = pd.DataFrame(summary_records)
    df_summary.to_csv(out_dir / "target_contract_summary.csv", index=False)
    with open(out_dir / "target_contract_summary.json", "w") as f:
        json.dump(summary_records, f, indent=2)

    df_trans = pd.DataFrame(transition_records)
    df_trans.to_csv(out_dir / "target_transitions_by_mode.csv", index=False)

    # Save representative sample showing each key case
    sample_criteria = [
        ("IDENTICAL_TP", (df_comp["va_outcome"] == "TP") & (df_comp["vb_outcome"] == "TP")),
        ("IDENTICAL_SL", (df_comp["va_outcome"] == "SL") & (df_comp["vb_outcome"] == "SL")),
        ("GAP_BELOW_SL_PROTECTION", df_comp["vb_invalidation_reason"] == "GAP_BELOW_SL"),
        ("GAP_ABOVE_TP_INVALIDATION", df_comp["vb_invalidation_reason"] == "GAP_ABOVE_TP"),
        (
            "PHANTOM_TP_FLIP",
            (df_comp["va_binary_target"] == 1) & (df_comp["vb_binary_target"] == 0),
        ),
        (
            "RECOVERED_TP_FLIP",
            (df_comp["va_binary_target"] == 0) & (df_comp["vb_binary_target"] == 1),
        ),
    ]

    sample_rows = []
    for case_name, mask in sample_criteria:
        matched = df_comp[mask].head(5)
        for _, r in matched.iterrows():
            d = dict(r)
            d["case_type"] = case_name
            sample_rows.append(d)

    df_samples = pd.DataFrame(sample_rows)
    df_samples.to_csv(out_dir / "target_contract_samples.csv", index=False)
    print(f"\nArtifacts successfully exported to {out_dir.resolve()}:")
    print("  - target_contract_summary.csv / .json")
    print("  - target_transitions_by_mode.csv")
    print(f"  - target_contract_samples.csv ({len(df_samples)} representative cases)")

    return {
        "summary": summary_records,
        "transitions": transition_records,
        "sample_count": len(df_comp),
    }


if __name__ == "__main__":
    run_full_contract_audit()
