import argparse
import csv
import io
import json
import sys
from datetime import date, datetime
from typing import Optional

from python.common.types import DailyBar, LabelRecord
from python.config.settings import PROJECT_ROOT, settings
from python.data.provider import (
    DEFAULT_UNIVERSE,
    CSVMarketDataProvider,
    MockMarketDataProvider,
)
from python.data.repository import DailyBarRepository
from python.labels.engine import (
    DEFAULT_AMBIGUITY_POLICY,
    DEFAULT_MAX_HOLDING_DAYS,
    DEFAULT_SL_PCT,
    DEFAULT_TP_PCT,
    LABEL_VERSION,
    LabelEngine,
)
from python.labels.repository import LabelRepository


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _format_pct(val: Optional[float], decimals: int = 2) -> str:
    if val is None:
        return "None"
    return f"{val * 100:.{decimals}f}%"


def _format_price(val: Optional[float], decimals: int = 2) -> str:
    if val is None:
        return "None"
    return f"{val:.{decimals}f}"


def print_label_table(records: list[LabelRecord], limit: int = 15) -> None:
    if not records:
        print("[build_labels] No label records to display.")
        return

    display_records = records[-limit:] if len(records) > limit else records
    headers = [
        "Ticker",
        "Date",
        "Entry",
        "TP",
        "SL",
        "Outcome",
        "Target",
        "Hold",
        "ExitDate",
        "ExitPrice",
        "Return%",
        "MFE%",
        "MAE%",
    ]

    col_widths = [len(h) for h in headers]
    rows: list[list[str]] = []
    for r in display_records:
        row = [
            r.ticker,
            str(r.date),
            _format_price(r.entry_price),
            _format_price(r.tp_price),
            _format_price(r.sl_price),
            r.outcome,
            str(r.binary_target),
            f"{r.holding_days}d",
            str(r.exit_date) if r.exit_date else "None",
            _format_price(r.exit_price),
            _format_pct(r.realized_return),
            _format_pct(r.mfe),
            _format_pct(r.mae),
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


def run_build_labels(
    tickers: Optional[list[str]] = None,
    provider_name: Optional[str] = None,
    db_url: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    tp_pct: float = DEFAULT_TP_PCT,
    sl_pct: float = DEFAULT_SL_PCT,
    max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
    ambiguity_policy: str = DEFAULT_AMBIGUITY_POLICY,
    save_db: bool = False,
    label_version: str = LABEL_VERSION,
    out_format: str = "table",
    limit: int = 15,
    include_incomplete: bool = False,
) -> dict[str, list[LabelRecord]]:
    resolved_db = db_url or settings.database_url
    selected_provider = (provider_name or "sqlite").lower()

    universe_bars: dict[str, list[DailyBar]] = {}

    if selected_provider == "sqlite":
        bar_repo = DailyBarRepository(database_url=resolved_db)
        db_universe = bar_repo.get_universe()
        if not db_universe:
            print(
                "[build_labels] Database empty, falling back to mock provider.",
                file=sys.stderr,
            )
            mock_universe = list(dict.fromkeys(DEFAULT_UNIVERSE + (tickers or [])))
            mock = MockMarketDataProvider(days=60, universe=mock_universe)
            for t in mock.get_universe():
                clean_t = t.strip().upper().removesuffix(".JK")
                universe_bars[clean_t] = mock.get_daily_bars(t, start_date=start_date)
        else:
            target_universe = tickers or db_universe
            for t in target_universe:
                bars = bar_repo.get_daily_bars(t, start_date=start_date)
                if bars:
                    clean_t = t.strip().upper().removesuffix(".JK")
                    universe_bars[clean_t] = bars
    elif selected_provider in ("mock", "synthetic"):
        mock_universe = list(dict.fromkeys(DEFAULT_UNIVERSE + (tickers or [])))
        mock = MockMarketDataProvider(days=60, universe=mock_universe)
        for t in mock.get_universe():
            clean_t = t.strip().upper().removesuffix(".JK")
            bars = mock.get_daily_bars(t, start_date=start_date)
            universe_bars[clean_t] = bars
    elif selected_provider in ("local_csv", "csv"):
        raw_dir = PROJECT_ROOT / "datasets" / "raw"
        csv_p = CSVMarketDataProvider(data_dir=raw_dir)
        target_universe = tickers or csv_p.get_universe()
        for t in target_universe:
            bars = csv_p.get_daily_bars(t, start_date=start_date)
            if bars:
                clean_t = t.strip().upper().removesuffix(".JK")
                universe_bars[clean_t] = bars
    else:
        raise ValueError(f"Unknown provider: {selected_provider}")

    if not universe_bars:
        print("[build_labels] No bars loaded for specified tickers.", file=sys.stderr)
        return {}

    # Filter tickers if specified
    if tickers:
        clean_target = {t.strip().upper().removesuffix(".JK") for t in tickers}
        universe_bars = {t: bars for t, bars in universe_bars.items() if t in clean_target}

    engine = LabelEngine(
        tp_pct=tp_pct,
        sl_pct=sl_pct,
        max_holding_days=max_holding_days,
        ambiguity_policy=ambiguity_policy,
        label_version=label_version,
    )
    labels_by_ticker = engine.compute_universe_labels(
        universe_bars=universe_bars,
        include_incomplete=include_incomplete,
    )

    # Filter generated labels by requested date range
    if start_date is not None or end_date is not None:
        filtered_labels: dict[str, list[LabelRecord]] = {}
        for t, recs in labels_by_ticker.items():
            filtered_labels[t] = [
                r
                for r in recs
                if (start_date is None or r.date >= start_date)
                and (end_date is None or r.date <= end_date)
            ]
        labels_by_ticker = filtered_labels

    all_records: list[LabelRecord] = []
    for t in sorted(labels_by_ticker.keys()):
        all_records.extend(labels_by_ticker[t])

    if save_db:
        label_repo = LabelRepository(database_url=resolved_db)
        saved = label_repo.save_labels(all_records)
        print(f"[build_labels] Saved {saved} label records to {resolved_db}")

    if out_format == "json":
        json_data = [r.model_dump(mode="json") for r in all_records]
        print(json.dumps(json_data, indent=2, default=str))
    elif out_format == "csv":
        if all_records:
            fields = list(all_records[0].model_dump().keys())
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            for r in all_records:
                writer.writerow(r.model_dump(mode="json"))
            print(buf.getvalue().strip())
    else:
        for t, recs in labels_by_ticker.items():
            print(
                f"\n--- Labels for {t} ({len(recs)} labeled bars, "
                f"TP={engine.tp_pct * 100:.1f}%, SL={engine.sl_pct * 100:.1f}%, "
                f"Hold={engine.max_holding_days}d, Policy={engine.ambiguity_policy}) ---"
            )
            print_label_table(recs, limit=limit)

    return labels_by_ticker


def main() -> None:
    parser = argparse.ArgumentParser(description="BEI Stock Signal Label Engine Builder")
    parser.add_argument("--ticker", "-t", type=str, help="Ticker or comma-separated tickers")
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        default="sqlite",
        choices=["sqlite", "mock", "local_csv", "csv"],
        help="Data provider source",
    )
    parser.add_argument(
        "--tp-pct",
        type=float,
        default=DEFAULT_TP_PCT,
        help="Take profit percentage (e.g. 0.05 or 5)",
    )
    parser.add_argument(
        "--sl-pct",
        type=float,
        default=DEFAULT_SL_PCT,
        help="Stop loss percentage (e.g. 0.02 or 2)",
    )
    parser.add_argument(
        "--max-hold",
        type=int,
        default=DEFAULT_MAX_HOLDING_DAYS,
        help="Max holding trading days",
    )
    parser.add_argument(
        "--ambiguity-policy",
        type=str,
        default=DEFAULT_AMBIGUITY_POLICY,
        choices=["conservative", "optimistic", "ambiguous"],
        help="Ambiguity handling policy when both barriers touched on same day",
    )
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--db-url", type=str, help="SQLite Database URL")
    parser.add_argument("--save-db", action="store_true", help="Persist labels into database")
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        default="table",
        choices=["table", "json", "csv"],
        help="Output display format",
    )
    parser.add_argument("--limit", type=int, default=15, help="Number of rows to display in table")
    parser.add_argument("--version", type=str, default=LABEL_VERSION, help="Label version tag")
    parser.add_argument("--include-incomplete", action="store_true", help="Include immature trades")

    args = parser.parse_args()
    tickers = (
        [x.strip().upper() for x in args.ticker.split(",") if x.strip()] if args.ticker else None
    )

    run_build_labels(
        tickers=tickers,
        provider_name=args.provider,
        db_url=args.db_url,
        start_date=_parse_date(args.start_date),
        end_date=_parse_date(args.end_date),
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        max_holding_days=args.max_hold,
        ambiguity_policy=args.ambiguity_policy,
        save_db=args.save_db,
        label_version=args.version,
        out_format=args.format,
        limit=args.limit,
        include_incomplete=args.include_incomplete,
    )


if __name__ == "__main__":
    main()
