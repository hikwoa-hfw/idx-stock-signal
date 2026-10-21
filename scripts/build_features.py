import argparse
import json
import sys
from datetime import date, datetime
from typing import Optional

from python.common.types import DailyBar, FeatureRecord
from python.config.settings import PROJECT_ROOT, settings
from python.data.provider import (
    DEFAULT_UNIVERSE,
    CSVMarketDataProvider,
    MockMarketDataProvider,
)
from python.data.repository import DailyBarRepository
from python.features.engine import FEATURE_VERSION, FeatureEngine
from python.features.repository import FeatureRepository


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _format_cell(val: Optional[float], decimals: int = 4) -> str:
    if val is None:
        return "None"
    return f"{val:.{decimals}f}"


def print_feature_table(records: list[FeatureRecord], limit: int = 15) -> None:
    if not records:
        print("[build_features] No feature records to display.")
        return

    display_records = records[-limit:] if len(records) > limit else records
    headers = [
        "Ticker",
        "Date",
        "Ret1d",
        "Ret5d",
        "Ret20d",
        "EMA20",
        "vsEMA20",
        "RSI14",
        "ATR14",
        "Vol20d",
        "VRat20",
        "RelIHSG",
        "RelSec",
        "Breadth",
    ]

    col_widths = [len(h) for h in headers]
    rows: list[list[str]] = []
    for r in display_records:
        row = [
            r.ticker,
            str(r.date),
            _format_cell(r.return_1d),
            _format_cell(r.return_5d),
            _format_cell(r.return_20d),
            _format_cell(r.ema20, 2),
            _format_cell(r.close_vs_ema20),
            _format_cell(r.rsi14, 2),
            _format_cell(r.atr14, 2),
            _format_cell(r.realized_vol_20d),
            _format_cell(r.volume_ratio_20d, 2),
            _format_cell(r.rel_strength_ihsg_20d),
            _format_cell(r.rel_strength_sector_20d),
            _format_cell(r.market_breadth, 2),
        ]
        rows.append(row)
        for i, val in enumerate(row):
            if len(val) > col_widths[i]:
                col_widths[i] = len(val)

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print(" | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)))
    if len(records) > limit:
        print(f"... Showing last {limit} of {len(records)} total records.")


def run_build_features(
    tickers: Optional[list[str]] = None,
    provider_name: Optional[str] = None,
    db_url: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    save_db: bool = False,
    feature_version: str = FEATURE_VERSION,
    out_format: str = "table",
    limit: int = 15,
    allow_mock_fallback: bool = True,
) -> dict[str, list[FeatureRecord]]:
    resolved_db = db_url or settings.database_url
    selected_provider = (provider_name or "sqlite").lower()

    universe_bars: dict[str, list[DailyBar]] = {}

    if selected_provider == "sqlite":
        bar_repo = DailyBarRepository(database_url=resolved_db)
        all_universe = bar_repo.get_universe()
        if not all_universe:
            if not allow_mock_fallback:
                raise RuntimeError(
                    "[build_features] Database empty and mock fallback is disabled. "
                    "Fail-closed in operational mode."
                )
            print(
                "[build_features] Database empty, falling back to mock provider.",
                file=sys.stderr,
            )
            mock = MockMarketDataProvider(days=60)
            for t in mock.get_universe():
                universe_bars[t] = mock.get_daily_bars(t, start_date=start_date, end_date=end_date)
        else:
            for t in all_universe:
                bars = bar_repo.get_daily_bars(t, start_date=start_date, end_date=end_date)
                if bars:
                    universe_bars[t] = bars
    elif selected_provider in ("mock", "synthetic"):
        if not allow_mock_fallback:
            raise ValueError(
                "[build_features] Mock provider forbidden when mock fallback disabled. "
                "Fail-closed in operational mode."
            )
        mock_universe = list(dict.fromkeys(DEFAULT_UNIVERSE + (tickers or [])))
        mock = MockMarketDataProvider(days=60, universe=mock_universe)
        for t in mock.get_universe():
            universe_bars[t] = mock.get_daily_bars(t, start_date=start_date, end_date=end_date)
    elif selected_provider in ("local_csv", "csv"):
        raw_dir = PROJECT_ROOT / "datasets" / "raw"
        csv_p = CSVMarketDataProvider(data_dir=raw_dir)
        for t in csv_p.get_universe():
            bars = csv_p.get_daily_bars(t, start_date=start_date, end_date=end_date)
            if bars:
                universe_bars[t] = bars
    else:
        raise ValueError(f"Unknown provider: {selected_provider}")

    if not universe_bars:
        print("[build_features] No bars loaded for specified tickers.", file=sys.stderr)
        return {}

    engine = FeatureEngine(feature_version=feature_version)
    features_by_ticker = engine.compute_universe_features(universe_bars)

    # Filter to requested tickers if specified
    if tickers:
        clean_target = {t.strip().upper().removesuffix(".JK") for t in tickers}
        features_by_ticker = {
            t: recs for t, recs in features_by_ticker.items() if t in clean_target
        }

    all_records: list[FeatureRecord] = []
    for t in sorted(features_by_ticker.keys()):
        all_records.extend(features_by_ticker[t])

    if save_db:
        feat_repo = FeatureRepository(database_url=resolved_db)
        saved = feat_repo.save_features(all_records)
        print(f"[build_features] Saved {saved} feature records to {resolved_db}")

    if out_format == "json":
        json_data = [r.model_dump(mode="json") for r in all_records]
        print(json.dumps(json_data, indent=2, default=str))
    elif out_format == "csv":
        import csv
        import io

        if all_records:
            fields = list(all_records[0].model_dump().keys())
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            for r in all_records:
                writer.writerow(r.model_dump(mode="json"))
            print(buf.getvalue().strip())
    else:
        # Table format
        for t, recs in features_by_ticker.items():
            print(f"\n--- Features for {t} ({len(recs)} bars, v={feature_version}) ---")
            print_feature_table(recs, limit=limit)

    return features_by_ticker


def main() -> None:
    parser = argparse.ArgumentParser(description="BEI Stock Signal Feature Engine Builder")
    parser.add_argument("--ticker", "-t", type=str, help="Ticker or comma-separated tickers")
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        default="sqlite",
        choices=["sqlite", "mock", "local_csv", "csv"],
        help="Data provider source",
    )
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--db-url", type=str, help="SQLite Database URL")
    parser.add_argument("--save-db", action="store_true", help="Persist features into database")
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        default="table",
        choices=["table", "json", "csv"],
        help="Output display format",
    )
    parser.add_argument("--limit", type=int, default=15, help="Number of rows to display in table")
    parser.add_argument("--version", type=str, default=FEATURE_VERSION, help="Feature version tag")

    args = parser.parse_args()
    tickers = (
        [x.strip().upper() for x in args.ticker.split(",") if x.strip()] if args.ticker else None
    )

    run_build_features(
        tickers=tickers,
        provider_name=args.provider,
        db_url=args.db_url,
        start_date=_parse_date(args.start_date),
        end_date=_parse_date(args.end_date),
        save_db=args.save_db,
        feature_version=args.version,
        out_format=args.format,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
