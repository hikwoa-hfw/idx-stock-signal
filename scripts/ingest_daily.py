import argparse
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from python.common.types import DailyBar, IngestionRun, IngestionTickerStatus
from python.config.settings import PROJECT_ROOT, settings
from python.data.provider import (
    CSVMarketDataProvider,
    MockMarketDataProvider,
    YFinanceMarketDataProvider,
)
from python.data.repository import DailyBarRepository
from python.data.validation import validate_daily_bars


def run_ingest(
    provider_name: Optional[str] = None,
    csv_dir: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    db_url: Optional[str] = None,
    days: int = 60,
    validate: bool = True,
    mode: str = "incremental",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    lookback_days: int = 30,
    batch_size: int = 25,
    universe_file: Optional[str] = None,
) -> int:
    resolved_db = db_url or settings.database_url
    repo = DailyBarRepository(database_url=resolved_db)

    selected_provider = (provider_name or settings.market_data_provider or "yfinance").lower()
    raw_dir = Path(csv_dir) if csv_dir else PROJECT_ROOT / "datasets" / "raw"

    cleaned_tickers = (
        [t.strip().upper().removesuffix(".JK") for t in tickers if t.strip()] if tickers else None
    )

    # Provider instantiation
    if selected_provider in ("local_csv", "csv"):
        has_csv = raw_dir.is_dir() and any(raw_dir.glob("*.csv"))
        if not has_csv:
            sys.stderr.write(
                f"[ingest_daily] No CSV files found in {raw_dir}. Falling back to mock provider.\n"
            )
            provider = MockMarketDataProvider(days=days, universe=cleaned_tickers)
            selected_provider = "mock"
        else:
            provider = CSVMarketDataProvider(data_dir=raw_dir)
    elif selected_provider in ("mock", "synthetic"):
        provider = MockMarketDataProvider(days=days, universe=cleaned_tickers)
    elif selected_provider in ("yfinance", "yf"):
        provider = YFinanceMarketDataProvider(
            universe=cleaned_tickers,
            universe_path=universe_file,
            batch_size=batch_size,
        )
    else:
        raise ValueError(f"Unknown provider: {selected_provider}")

    target_tickers = cleaned_tickers or provider.get_universe()
    if not target_tickers:
        sys.stderr.write("[ingest_daily] No tickers found to ingest.\n")
        return 0

    today = date.today()

    # Prepare ingestion run record
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    ingestion_run = IngestionRun(
        id=run_id,
        provider=selected_provider,
        job_type=mode,
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
        tickers_requested=len(target_tickers),
        config_version="v1.0.0",
    )
    repo.create_ingestion_run(ingestion_run)

    stat_counters = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0,
        "succeeded": 0,
        "partial": 0,
        "failed": 0,
    }
    errors: list[str] = []

    # Process tickers
    if isinstance(provider, YFinanceMarketDataProvider):
        effective_end = end_date or today
        chunks = [
            target_tickers[i : i + batch_size] for i in range(0, len(target_tickers), batch_size)
        ]
        for chunk in chunks:
            if mode == "backfill":
                chunk_start = start_date or date(2016, 1, 1)
            elif mode == "repair":
                chunk_start = today - timedelta(days=lookback_days)
            else:  # incremental
                if start_date is not None:
                    chunk_start = start_date
                else:
                    dates_needed = []
                    for t in chunk:
                        latest = repo.get_latest_date(t)
                        if latest:
                            dates_needed.append(latest - timedelta(days=10))
                        else:
                            dates_needed.append(date(2016, 1, 1))
                    chunk_start = (
                        min(dates_needed) if dates_needed else (today - timedelta(days=10))
                    )

            try:
                batch_bars = provider.get_daily_bars_batch(
                    chunk, start_date=chunk_start, end_date=effective_end
                )
            except Exception as exc:
                sys.stderr.write(f"[ingest_daily] Batch fetch error for {chunk}: {exc}\n")
                errors.append(f"Batch {chunk}: {exc}")
                batch_bars = {t: [] for t in chunk}

            for ticker in chunk:
                bars = batch_bars.get(ticker, [])
                _process_ticker_bars(
                    ticker=ticker,
                    bars=bars,
                    repo=repo,
                    run_id=run_id,
                    provider_name=selected_provider,
                    validate=validate,
                    errors=errors,
                    stat_counters=stat_counters,
                )
    else:
        for ticker in target_tickers:
            if mode == "backfill":
                req_start = start_date or date(2016, 1, 1)
                effective_end = end_date or today
            elif mode == "repair":
                req_start = today - timedelta(days=lookback_days)
                effective_end = end_date or today
            elif mode == "incremental":
                latest_in_db = repo.get_latest_date(ticker)
                if latest_in_db:
                    req_start = latest_in_db - timedelta(days=10)
                    effective_end = end_date or today
                elif selected_provider in ("local_csv", "csv", "mock", "synthetic"):
                    req_start = start_date
                    effective_end = end_date
                else:
                    req_start = start_date or (today - timedelta(days=10))
                    effective_end = end_date or today
            else:
                req_start = start_date
                effective_end = end_date

            try:
                bars = provider.get_daily_bars(ticker, start_date=req_start, end_date=effective_end)
            except Exception as exc:
                sys.stderr.write(f"[ingest_daily] Fetch error for {ticker}: {exc}\n")
                errors.append(f"{ticker}: {exc}")
                bars = []

            _process_ticker_bars(
                ticker=ticker,
                bars=bars,
                repo=repo,
                run_id=run_id,
                provider_name=selected_provider,
                validate=validate,
                errors=errors,
                stat_counters=stat_counters,
            )

    # Read updated totals from ticker statuses in repository for precision
    ticker_statuses = repo.get_ticker_statuses(run_id)
    succeeded_cnt = sum(1 for s in ticker_statuses if s.status == "SUCCESS")
    partial_cnt = sum(1 for s in ticker_statuses if s.status == "NO_DATA")
    failed_cnt = sum(1 for s in ticker_statuses if s.status == "ERROR")
    inserted_cnt = sum(s.rows_inserted for s in ticker_statuses)
    updated_cnt = sum(s.rows_updated for s in ticker_statuses)
    unchanged_cnt = stat_counters["unchanged"]
    rejected_cnt = stat_counters["rejected"]

    if succeeded_cnt == len(target_tickers) and failed_cnt == 0 and partial_cnt == 0:
        final_status = "SUCCESS"
    elif succeeded_cnt == 0:
        final_status = "FAILED"
    else:
        final_status = "PARTIAL"

    error_summary = "; ".join(errors[:5]) if errors else None
    if errors and len(errors) > 5:
        error_summary += f" ... ({len(errors) - 5} more)"

    repo.update_ingestion_run(
        run_id,
        finished_at=datetime.now(timezone.utc),
        status=final_status,
        tickers_succeeded=succeeded_cnt,
        tickers_partial=partial_cnt,
        tickers_failed=failed_cnt,
        rows_inserted=inserted_cnt,
        rows_updated=updated_cnt,
        rows_unchanged=unchanged_cnt,
        rows_rejected=rejected_cnt,
        error_summary=error_summary,
    )

    total_saved = inserted_cnt + updated_cnt
    print(
        f"[ingest_daily] [{final_status}] Run {run_id} ({mode}): "
        f"{inserted_cnt} inserted, {updated_cnt} updated, {unchanged_cnt} unchanged across "
        f"{len(target_tickers)} tickers "
        f"(succeeded={succeeded_cnt}, partial={partial_cnt}, failed={failed_cnt})."
    )

    if final_status == "FAILED":
        raise RuntimeError(
            f"Ingestion run {run_id} failed: 0 of {len(target_tickers)} tickers succeeded."
        )

    return total_saved


def _process_ticker_bars(
    ticker: str,
    bars: list[DailyBar],
    repo: DailyBarRepository,
    run_id: str,
    provider_name: str,
    validate: bool,
    errors: list[str],
    stat_counters: dict[str, int],
) -> None:
    ticker_status_id = f"{run_id}_{ticker}"
    if not bars:
        sys.stderr.write(f"[ingest_daily] Skipping {ticker}: 0 bars retrieved.\n")
        repo.record_ticker_status(
            IngestionTickerStatus(
                id=ticker_status_id,
                ingestion_run_id=run_id,
                ticker=ticker,
                status="NO_DATA",
                rows_received=0,
                rows_inserted=0,
                rows_updated=0,
            )
        )
        stat_counters["partial"] += 1
        return

    if validate:
        report = validate_daily_bars(bars, raise_on_error=False)
        if not report.is_valid:
            err_msg = "; ".join(report.errors[:3])
            sys.stderr.write(f"[ingest_daily] Validation failed for {ticker}: {err_msg}\n")
            errors.append(f"{ticker}: {err_msg}")
            repo.record_ticker_status(
                IngestionTickerStatus(
                    id=ticker_status_id,
                    ingestion_run_id=run_id,
                    ticker=ticker,
                    status="ERROR",
                    rows_received=len(bars),
                    rows_inserted=0,
                    rows_updated=0,
                    error_code="VALIDATION_FAILED",
                    error_message=err_msg,
                )
            )
            stat_counters["rejected"] += len(bars)
            stat_counters["failed"] += 1
            return

    res = repo.save_bars_detailed(bars, default_provider=provider_name, ingestion_run_id=run_id)
    stat_counters["inserted"] += res["inserted"]
    stat_counters["updated"] += res["updated"]
    stat_counters["unchanged"] += res["unchanged"]
    stat_counters["succeeded"] += 1

    repo.record_ticker_status(
        IngestionTickerStatus(
            id=ticker_status_id,
            ingestion_run_id=run_id,
            ticker=ticker,
            status="SUCCESS",
            rows_received=len(bars),
            rows_inserted=res["inserted"],
            rows_updated=res["updated"],
            first_date_received=min(b.date for b in bars),
            last_date_received=max(b.date for b in bars),
        )
    )
    print(
        f"[ingest_daily] Ingested {len(bars)} bars for {ticker} "
        f"({res['inserted']} inserted, {res['updated']} updated, {res['unchanged']} unchanged)."
    )


def _parse_date(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    cleaned = val.strip()[:10].replace("/", "-")
    return datetime.strptime(cleaned, "%Y-%m-%d").date()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest daily stock bars into database.")
    parser.add_argument(
        "--mode",
        choices=["backfill", "incremental", "repair"],
        default="incremental",
        help=(
            "Ingestion mode: backfill (bulk), incremental (daily overlap), repair (recent window)."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=["yfinance", "yf", "mock", "synthetic", "local_csv", "csv"],
        help="Market data provider to use.",
    )
    parser.add_argument("--csv-dir", help="Path to raw CSV directory.")
    parser.add_argument("--tickers", help="Comma-separated or space-separated list of tickers.")
    parser.add_argument("--universe-file", help="Path to seed universe CSV file.")
    parser.add_argument("--db-url", help="Database URL for persistence.")
    parser.add_argument("--days", type=int, default=60, help="Days of mock history to generate.")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD).")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="Lookback days for repair or incremental mode (default 30).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Batch size for bulk provider requests (default 25).",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip pre-ingestion validation.",
    )

    args = parser.parse_args(argv)

    ticker_list = None
    if args.tickers:
        raw = args.tickers.replace(",", " ").split()
        ticker_list = [t.strip().upper() for t in raw if t.strip()]

    start_d = _parse_date(args.start_date)
    end_d = _parse_date(args.end_date)

    try:
        run_ingest(
            provider_name=args.provider,
            csv_dir=args.csv_dir,
            tickers=ticker_list,
            db_url=args.db_url,
            days=args.days,
            validate=not args.no_validate,
            mode=args.mode,
            start_date=start_d,
            end_date=end_d,
            lookback_days=args.lookback_days,
            batch_size=args.batch_size,
            universe_file=args.universe_file,
        )
        return 0
    except Exception as exc:
        sys.stderr.write(f"[ingest_daily] Ingestion failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
