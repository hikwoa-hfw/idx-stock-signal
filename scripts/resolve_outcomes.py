import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.common.types import SignalOutcomeRecord
from python.config.settings import settings
from python.data.repository import DailyBarRepository
from python.outcomes.dataset import build_matured_outcomes_dataset, export_matured_dataset
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"[ERROR] Invalid date format: '{s}'. Expected YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)


def _print_outcomes_table(outcomes: list[SignalOutcomeRecord], limit: int = 20) -> None:
    if not outcomes:
        print("\n[INFO] No outcomes resolved.\n")
        return

    print("\n" + "=" * 112)
    print("                    INDONESIAN STOCK AI -- OUTCOME ENGINE RESULTS")
    print("=" * 112)
    print(
        f"{'Ticker':<8} {'Signal Dt':<11} {'Entry Dt':<11} {'Entry Px':<10} "
        f"{'Status':<16} {'Exit Dt':<11} {'Exit Px':<10} "
        f"{'Return':<9} {'Hold':<5} {'MFE':<8} {'MAE':<8}"
    )
    print("-" * 112)

    display = outcomes[:limit]
    for o in display:
        ret_str = f"{o.realized_return * 100:+.2f}%" if o.realized_return is not None else "-"
        exit_dt_str = str(o.exit_date) if o.exit_date else "-"
        exit_px_str = f"{o.exit_price:,.1f}" if o.exit_price is not None else "-"
        mfe_str = f"{o.mfe * 100:+.2f}%"
        mae_str = f"{o.mae * 100:+.2f}%"

        print(
            f"{o.ticker:<8} {str(o.signal_date):<11} {str(o.entry_date):<11} "
            f"{o.entry_price:<10,.1f} {o.outcome_status:<16} {exit_dt_str:<11} "
            f"{exit_px_str:<10} {ret_str:<9} {o.holding_days:<5} {mfe_str:<8} {mae_str:<8}"
        )

    if len(outcomes) > limit:
        print(f"... and {len(outcomes) - limit} more outcomes.")
    print("=" * 112 + "\n")


def run_resolve_outcomes(
    as_of_date: Optional[date] = None,
    ambiguity_policy: str = "conservative",
    save_db: bool = False,
    export_matured: Optional[str] = None,
    export_path: Optional[str] = None,
    ticker: Optional[str] = None,
    mode: Optional[str] = None,
    database_url: Optional[str] = None,
    exclude_ambiguous: bool = False,
    exclude_unfilled: bool = False,
) -> int:
    db_url = database_url or settings.database_url
    bar_repo = DailyBarRepository(db_url)
    sig_repo = SignalRepository(db_url)
    out_repo = OutcomeRepository(db_url)

    engine = OutcomeEngine(
        bar_repo=bar_repo,
        signal_repo=sig_repo,
        outcome_repo=out_repo,
        ambiguity_policy=ambiguity_policy,
    )

    results = engine.resolve_all_signals(
        as_of_date=as_of_date,
        ticker=ticker,
        mode=mode,
        save=save_db,
        ambiguity_policy=ambiguity_policy,
    )

    outcomes = [r[0] for r in results]
    _print_outcomes_table(outcomes)

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.outcome_status] = counts.get(o.outcome_status, 0) + 1

    print("[SUMMARY] Resolved Outcomes Distribution:")
    for status in ("TP", "SL", "EXPIRY", "UNFILLED_EXPIRED", "AMBIGUOUS", "OPEN"):
        if status in counts:
            print(f"  {status:<18}: {counts[status]}")
    print(f"  TOTAL             : {len(outcomes)}")
    if save_db:
        print("  Database          : Persisted to SQLite successfully.")

    if export_matured:
        df = build_matured_outcomes_dataset(
            outcome_repo=out_repo,
            signal_repo=sig_repo,
            end_date=as_of_date,
            ticker=ticker,
            mode=mode,
            exclude_ambiguous=exclude_ambiguous,
            exclude_unfilled=exclude_unfilled,
        )
        if df.empty:
            print("\n[WARNING] No matured outcomes found to export.")
        else:
            default_ext = export_matured.lower()
            out_file = export_path or f"data/matured_outcomes.{default_ext}"
            saved_p = export_matured_dataset(df, out_file, format=export_matured)
            print(f"\n[EXPORT] Exported {len(df)} matured outcome rows to '{saved_p}'.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 9 — Outcome Engine: Reconcile daily signals against price data."
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Evaluate outcomes as of date (YYYY-MM-DD). Default: latest available.",
    )
    parser.add_argument(
        "--ambiguity-policy",
        type=str,
        choices=["conservative", "optimistic", "ambiguous"],
        default="conservative",
        help="Policy for same-candle TP and SL collision. Default: conservative.",
    )
    parser.add_argument(
        "--save-db",
        action="store_true",
        help="Persist resolved outcomes and snapshots to database.",
    )
    parser.add_argument(
        "--export-matured",
        type=str,
        choices=["csv", "json"],
        default=None,
        help="Export matured dataset into CSV or JSON.",
    )
    parser.add_argument(
        "--export-path",
        type=str,
        default=None,
        help="File path for exported matured dataset.",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="Filter signals by specific ticker symbol (e.g. BBCA).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["LOW_PRICE", "HIGHER_PRICE", "ALL"],
        default=None,
        help="Filter signals by dual price mode (LOW_PRICE, HIGHER_PRICE, ALL).",
    )
    parser.add_argument(
        "--exclude-ambiguous",
        action="store_true",
        help="Exclude AMBIGUOUS outcomes when exporting matured dataset.",
    )
    parser.add_argument(
        "--exclude-unfilled",
        action="store_true",
        help="Exclude UNFILLED_EXPIRED breakout outcomes when exporting matured dataset.",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Database URL (default: from settings).",
    )

    args = parser.parse_args()
    parsed_date = _parse_date(args.as_of_date)

    sys.exit(
        run_resolve_outcomes(
            as_of_date=parsed_date,
            ambiguity_policy=args.ambiguity_policy,
            save_db=args.save_db,
            export_matured=args.export_matured,
            export_path=args.export_path,
            ticker=args.ticker,
            mode=args.mode,
            database_url=args.database_url,
            exclude_ambiguous=args.exclude_ambiguous,
            exclude_unfilled=args.exclude_unfilled,
        )
    )


if __name__ == "__main__":
    main()
