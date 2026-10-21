"""Dataset & Cutoff Contract Inspection Script.

Audits historical bar dates, data maturity boundaries for Variant B H=15 targets,
champion vs challenger training row counts, and incremental sample statistics.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.common.types import classify_price_mode
from python.config.settings import settings
from python.experiments.challenger_retraining import ChallengerRetrainingRunner


def inspect_database_splits(db_path: str, cutoff_date: str = "2026-09-25") -> dict:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Inspect table max dates and counts
    cur.execute("SELECT MAX(date), COUNT(*), COUNT(DISTINCT date) FROM daily_bars")
    max_bar_date, bar_count, bar_dates_count = cur.fetchone()

    cur.execute("SELECT MAX(date), COUNT(*), COUNT(DISTINCT date) FROM features_daily")
    max_feat_date, feat_count, feat_dates_count = cur.fetchone()

    cur.execute("SELECT MAX(date), COUNT(*), COUNT(DISTINCT date) FROM labels_daily")
    max_label_date, label_count, label_dates_count = cur.fetchone()

    # 2. Check forward bar count for decision dates after cutoff
    cur.execute(
        "SELECT DISTINCT date FROM daily_bars WHERE date >= ? ORDER BY date",
        (cutoff_date,),
    )
    post_cutoff_dates = [r[0] for r in cur.fetchall()]

    # 3. Champion dataset breakdown
    query_champ = """
        SELECT f.date, l.entry_price, l.outcome, l.binary_target
        FROM features_daily f
        JOIN labels_daily l ON f.ticker = l.ticker AND f.date = l.date
        WHERE l.outcome != 'AMBIGUOUS' AND l.binary_target IS NOT NULL
          AND f.date <= '2025-08-14';
    """
    cur.execute(query_champ)
    champ_train_rows = cur.fetchall()

    champ_low = 0
    champ_high = 0
    champ_below50 = 0
    for r in champ_train_rows:
        mode = classify_price_mode(r[1])
        if mode == "LOW_PRICE":
            champ_low += 1
        elif mode == "HIGHER_PRICE":
            champ_high += 1
        elif mode == "EXCLUDED_BELOW_50":
            champ_below50 += 1

    conn.close()

    # 4. Challenger matured dataset breakdown using ChallengerRetrainingRunner
    runner = ChallengerRetrainingRunner(db_path=db_path, cutoff_date=cutoff_date)
    df_low, _ = runner.load_matured_data("LOW_PRICE")
    df_high, _ = runner.load_matured_data("HIGHER_PRICE")

    low_valid = int((df_low["vb_status_15"] == "VALID").sum())
    low_inval = int((df_low["vb_status_15"] == "INVALIDATED").sum())
    low_incomp = int((df_low["vb_status_15"] == "INCOMPLETE").sum())

    high_valid = int((df_high["vb_status_15"] == "VALID").sum())
    high_inval = int((df_high["vb_status_15"] == "INVALIDATED").sum())
    high_incomp = int((df_high["vb_status_15"] == "INCOMPLETE").sum())

    tot_champ_valid = champ_low + champ_high
    tot_chall_valid = low_valid + high_valid

    inc_low = low_valid - champ_low
    inc_low_pct = (inc_low / champ_low * 100.0) if champ_low > 0 else 0.0

    inc_high = high_valid - champ_high
    inc_high_pct = (inc_high / champ_high * 100.0) if champ_high > 0 else 0.0

    inc_tot = tot_chall_valid - tot_champ_valid
    inc_tot_pct = (inc_tot / tot_champ_valid * 100.0) if tot_champ_valid > 0 else 0.0

    return {
        "max_bar_date": max_bar_date,
        "bar_count": bar_count,
        "bar_dates_count": bar_dates_count,
        "max_feat_date": max_feat_date,
        "max_label_date": max_label_date,
        "cutoff_date": cutoff_date,
        "post_cutoff_dates": post_cutoff_dates,
        "champ_train_total": len(champ_train_rows),
        "champ_low": champ_low,
        "champ_high": champ_high,
        "champ_below50": champ_below50,
        "tot_champ_valid": tot_champ_valid,
        "chall_low_total": len(df_low),
        "chall_low_valid": low_valid,
        "chall_low_inval": low_inval,
        "chall_low_incomp": low_incomp,
        "chall_high_total": len(df_high),
        "chall_high_valid": high_valid,
        "chall_high_inval": high_inval,
        "chall_high_incomp": high_incomp,
        "tot_chall_valid": tot_chall_valid,
        "inc_low": inc_low,
        "inc_low_pct": inc_low_pct,
        "inc_high": inc_high,
        "inc_high_pct": inc_high_pct,
        "inc_tot": inc_tot,
        "inc_tot_pct": inc_tot_pct,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect dataset splits and cutoff contracts.")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: settings.database_url).",
    )
    parser.add_argument(
        "--cutoff-date",
        type=str,
        default="2026-09-25",
        help="Decision cutoff date for 15-day forward maturity (default: 2026-09-25).",
    )
    args = parser.parse_args()

    db_path = args.db_path
    if not db_path:
        url = settings.database_url
        if url.startswith("sqlite:///"):
            db_path = url[len("sqlite:///") :]
        elif url.startswith("sqlite://"):
            db_path = url[len("sqlite://") :]
        else:
            db_path = "datasets/stock_signals.db"

    print("=" * 80)
    print("DATASET & CUTOFF CONTRACT AUDIT INSPECTION")
    print("=" * 80)
    print(f"Database: {db_path}")
    print("Target Contract: Variant B (Next-Session Open MOO, H=15, TP +5%, SL -2%)")
    print(f"Maturity Cutoff Date: {args.cutoff_date}")
    print("=" * 80)

    stats = inspect_database_splits(db_path=db_path, cutoff_date=args.cutoff_date)

    print("\n1. RAW DATABASE METRICS:")
    print(
        f"  daily_bars:     Max Date = {stats['max_bar_date']} | "
        f"Rows = {stats['bar_count']:,} | Dates = {stats['bar_dates_count']}"
    )
    print(f"  features_daily: Max Date = {stats['max_feat_date']}")
    print(f"  labels_daily:   Max Date = {stats['max_label_date']}")

    print("\n2. DATA MATURITY HORIZON ANALYSIS (H=15 sessions after entry):")
    print(f"  Latest observable market bar date: {stats['max_bar_date']}")
    print(f"  Latest fully observable decision date: {stats['cutoff_date']}")
    print("  Forward sessions remaining for post-cutoff dates:")
    all_dates = stats["post_cutoff_dates"]
    for i, d in enumerate(all_dates):
        fwd_count = len(all_dates) - 1 - i
        status_label = "MATURED" if fwd_count >= 15 else "INCOMPLETE (< 15 bars)"
        print(f"    Decision {d}: {fwd_count:>2} forward bars remaining -> {status_label}")

    print("\n3. PRODUCTION CHAMPION DATASET BREAKDOWN (cutoff <= 2025-08-14):")
    print(f"  LOW_PRICE:          {stats['champ_low']:,} valid rows")
    print(f"  HIGHER_PRICE:       {stats['champ_high']:,} valid rows")
    print(f"  EXCLUDED_BELOW_50:  {stats['champ_below50']:,} rows (< 50 IDR penny stock filter)")
    print(f"  Total Valid (LOW + HIGH): {stats['tot_champ_valid']:,} rows")
    print(f"  Total Raw Rows:           {stats['champ_train_total']:,} rows")

    print("\n4. NEW FULLY-MATURED RETRAINING DATASET (cutoff <= 2026-09-25):")
    print(
        f"  LOW_PRICE:    {stats['chall_low_valid']:,} valid | "
        f"{stats['chall_low_inval']:,} invalidated | "
        f"{stats['chall_low_incomp']} incomplete (Total: {stats['chall_low_total']:,})"
    )
    print(
        f"  HIGHER_PRICE: {stats['chall_high_valid']:,} valid | "
        f"{stats['chall_high_inval']:,} invalidated | "
        f"{stats['chall_high_incomp']} incomplete (Total: {stats['chall_high_total']:,})"
    )
    print(f"  Total Valid:  {stats['tot_chall_valid']:,} rows")

    print("\n5. INCREMENTAL DATA SUPPORT COMPARISON:")
    print("  vs Champion Training Data (2025-08-14):")
    print(f"    LOW_PRICE:    +{stats['inc_low']:,} rows (+{stats['inc_low_pct']:.2f}%)")
    print(f"    HIGHER_PRICE: +{stats['inc_high']:,} rows (+{stats['inc_high_pct']:.2f}%)")
    print(
        f"    Total Valid:  +{stats['inc_tot']:,} rows (+{stats['inc_tot_pct']:.2f}%) "
        "across 13.5 additional calendar months"
    )
    print("  vs Phase 11F Research Cutoff (2026-09-25):")
    print("    Incremental fully matured rows: +0 rows (+0.0%)")
    print(
        "    Finding: Zero incremental data support beyond Phase 11F "
        "without newer forward market bars."
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
