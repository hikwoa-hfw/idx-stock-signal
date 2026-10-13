import argparse
import sys
from pathlib import Path
from typing import Optional

from python.config.settings import PROJECT_ROOT, settings
from python.data.provider import CSVMarketDataProvider
from python.data.repository import DailyBarRepository
from python.data.validation import validate_daily_bars


def run_validation(
    db_url: Optional[str] = None,
    csv_dir: Optional[str] = None,
    ticker: Optional[str] = None,
    strict: bool = True,
) -> int:
    all_errors: list[str] = []
    total_bars = 0
    checked_tickers: list[str] = []

    clean_ticker = ticker.strip().upper().removesuffix(".JK") if ticker else None

    if csv_dir:
        raw_path = Path(csv_dir)
        provider = CSVMarketDataProvider(data_dir=raw_path)
        tickers = [clean_ticker] if clean_ticker else provider.get_universe()
        for t in tickers:
            bars = provider.get_daily_bars(t)
            checked_tickers.append(t)
            total_bars += len(bars)
            if not bars and clean_ticker:
                all_errors.append(f"No bars found for ticker '{t}' in CSV directory.")
                print(f"[validate_data] {t}: 0 bars retrieved (missing file or empty data).")
                continue
            report = validate_daily_bars(bars)
            if not report.is_valid:
                all_errors.extend(report.errors)
                print(f"[validate_data] {t}: {report.error_count} error(s) found.")
            else:
                print(f"[validate_data] {t}: {len(bars)} bars valid.")
    else:
        resolved_db = db_url or settings.database_url
        repo = DailyBarRepository(database_url=resolved_db)
        tickers = [clean_ticker] if clean_ticker else repo.get_universe()
        for t in tickers:
            bars = repo.get_daily_bars(t)
            checked_tickers.append(t)
            total_bars += len(bars)
            if not bars and clean_ticker:
                all_errors.append(f"No bars found for ticker '{t}' in database.")
                print(f"[validate_data] {t}: 0 bars retrieved from database.")
                continue
            report = validate_daily_bars(bars)
            if not report.is_valid:
                all_errors.extend(report.errors)
                print(f"[validate_data] {t}: {report.error_count} error(s) found.")
            else:
                print(f"[validate_data] {t}: {len(bars)} bars valid.")

    print(
        f"[validate_data] Summary: {total_bars} bars checked across "
        f"{len(checked_tickers)} tickers. {len(all_errors)} error(s) found."
    )

    if all_errors:
        for err in all_errors[:10]:
            print(f"  - Error: {err}", file=sys.stderr)
        if len(all_errors) > 10:
            print(f"  ... and {len(all_errors) - 10} more.", file=sys.stderr)
        if strict:
            return 1

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate stock daily bars for schema integrity.")
    parser.add_argument("--db-url", help="Database URL to validate.")
    parser.add_argument(
        "--csv-dir",
        default=None,
        help="Optional CSV directory path to validate instead of database.",
    )
    parser.add_argument("--ticker", help="Specific ticker to validate.")
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Do not exit with non-zero code when errors are detected.",
    )

    args = parser.parse_args(argv)

    default_csv = PROJECT_ROOT / "datasets" / "raw"
    csv_dir = args.csv_dir
    db_url = args.db_url

    if not csv_dir and not db_url:
        repo = DailyBarRepository(database_url=settings.database_url)
        if repo.count_bars() == 0 and default_csv.is_dir() and any(default_csv.glob("*.csv")):
            csv_dir = str(default_csv)

    return run_validation(
        db_url=db_url,
        csv_dir=csv_dir,
        ticker=args.ticker,
        strict=not args.no_strict,
    )


if __name__ == "__main__":
    sys.exit(main())
