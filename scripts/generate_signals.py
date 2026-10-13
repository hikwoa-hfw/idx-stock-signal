import argparse
import csv
import json
import sys
from datetime import datetime
from typing import Optional

from python.common.types import SignalConfig, SignalRecord
from python.config.settings import settings
from python.data.provider import DEFAULT_UNIVERSE, MockMarketDataProvider, load_universe
from python.data.repository import DailyBarRepository
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ranked daily trading signals for BEI stocks."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Signal date in YYYY-MM-DD format (defaults to latest available trading date).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Number of top ranked candidate signals to output (default: 5).",
    )
    parser.add_argument(
        "--model-version",
        default=None,
        help="Specific model version string from model registry.",
    )
    parser.add_argument(
        "--use-champion",
        action="store_true",
        help="Explicitly use current champion model from registry.",
    )
    parser.add_argument(
        "--save-db",
        action="store_true",
        help="Persist generated signals into SQLite signals_daily table.",
    )
    parser.add_argument(
        "--min-prob",
        type=float,
        default=None,
        help="Minimum predicted probability threshold (overrides config).",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output presentation format: table, json, or csv (default: table).",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Tickers to include in universe (e.g. BBCA BBRI BMRI).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLite database URL. Defaults to settings.database_url.",
    )
    parser.add_argument(
        "--ignore-existing",
        action="store_true",
        help="Ignore duplicate signals when persisting to database instead of raising error.",
    )
    parser.add_argument(
        "--mode",
        choices=["LOW_PRICE", "HIGHER_PRICE", "ALL"],
        default="ALL",
        help="Price regime filter: LOW_PRICE (50-300), HIGHER_PRICE (>300), or ALL (default: ALL).",
    )
    parser.add_argument(
        "--dual-mode",
        action="store_true",
        help="Generate signals for both LOW_PRICE and HIGHER_PRICE concurrently.",
    )
    return parser.parse_args()


def print_table_signals(signals: list[SignalRecord], target_date: Optional[str]) -> None:
    if not signals:
        print(f"\n[signals] No BUY signals qualified for date {target_date or 'latest'}.")
        return

    print("\n" + "=" * 96)
    print("                      INDONESIAN STOCK AI -- DAILY BUY SIGNALS")
    print("=" * 96)
    print(f"Signal Date    : {signals[0].signal_date}")
    print(f"Model Version  : {signals[0].model_version}")
    print(f"Total Ranked   : {len(signals)}")
    print("-" * 96)
    print(
        f"{'Rank':<5} {'Ticker':<8} {'Mode':<13} {'Signal':<6} "
        f"{'Entry Low':<11} {'Entry High':<11} "
        f"{'TP Price':<11} {'SL Price':<11} {'P(Win)':<8} {'Exp Ret':<9} {'Score':<6}"
    )
    print("-" * 110)

    for rank, sig in enumerate(signals, 1):
        ret_str = f"{sig.expected_return * 100:+.2f}%" if sig.expected_return is not None else "N/A"
        prob_str = f"{sig.predicted_probability * 100:.1f}%"
        mode_str = sig.mode_id or "-"
        print(
            f"{rank:<5} {sig.ticker:<8} {mode_str:<13} {sig.signal:<6} {sig.entry_low:<11,.2f} "
            f"{sig.entry_high:<11,.2f} {sig.tp_price:<11,.2f} {sig.sl_price:<11,.2f} "
            f"{prob_str:<8} {ret_str:<9} {sig.score:<6.1f}"
        )

    print("=" * 96 + "\n")


def print_csv_signals(signals: list[SignalRecord]) -> None:
    if not signals:
        return
    writer = csv.writer(sys.stdout)
    writer.writerow(
        [
            "rank",
            "signal_id",
            "ticker",
            "signal_date",
            "mode",
            "signal",
            "entry_low",
            "entry_high",
            "tp_price",
            "sl_price",
            "max_holding_days",
            "predicted_probability",
            "expected_return",
            "score",
            "model_version",
            "feature_version",
            "signal_config_version",
        ]
    )
    for rank, s in enumerate(signals, 1):
        writer.writerow(
            [
                rank,
                s.signal_id,
                s.ticker,
                str(s.signal_date),
                s.mode_id or "",
                s.signal,
                s.entry_low,
                s.entry_high,
                s.tp_price,
                s.sl_price,
                s.max_holding_days,
                s.predicted_probability,
                s.expected_return if s.expected_return is not None else "",
                s.score,
                s.model_version,
                s.feature_version,
                s.signal_config_version,
            ]
        )


def main() -> None:
    args = parse_args()
    db_url = args.db_url or settings.database_url
    bar_repo = DailyBarRepository(db_url)

    # Resolve target universe
    if args.tickers:
        raw_list = []
        for item in args.tickers:
            for t in item.split(","):
                c = t.strip().upper().removesuffix(".JK")
                if c:
                    raw_list.append(c)
        target_universe = list(dict.fromkeys(raw_list))
    else:
        target_universe = bar_repo.get_universe()
        if not target_universe:
            target_universe = load_universe()
        if not target_universe:
            target_universe = DEFAULT_UNIVERSE

    # Load daily bars from DB
    bars_by_ticker: dict[str, list] = {}
    for t in target_universe:
        bars = bar_repo.get_daily_bars(t)
        if bars:
            bars_by_ticker[t] = bars

    # Fallback to deterministic mock market data if DB empty
    if not bars_by_ticker:
        sys.stderr.write(
            "[generate_signals] Warning: No bars in DB. Generating deterministic mock data...\n"
        )
        mock = MockMarketDataProvider(universe=target_universe, days=120)
        for t in target_universe:
            bars = mock.get_daily_bars(t)
            if bars:
                bars_by_ticker[t] = bars

    # Signal configuration
    config = SignalConfig(top_n=args.top_n)
    if args.min_prob is not None:
        config.min_probability = args.min_prob

    # Parse target date if specified
    s_date = None
    if args.date:
        try:
            s_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            sys.stderr.write(
                f"[generate_signals] Invalid date format '{args.date}'. Expected YYYY-MM-DD.\n"
            )
            sys.exit(1)

    if args.use_champion and args.model_version:
        sys.stderr.write(
            "[generate_signals] Cannot specify both --use-champion and --model-version.\n"
        )
        sys.exit(1)

    engine = SignalEngine(config=config, bar_repo=bar_repo)

    try:
        if args.dual_mode or args.mode == "ALL":
            dual_res = engine.generate_dual_mode_signals(
                signal_date=s_date,
                universe=target_universe,
                bars_by_ticker=bars_by_ticker,
                config=config,
                use_champion=args.use_champion,
                model_version=args.model_version,
            )
            signals = dual_res.get("LOW_PRICE", []) + dual_res.get("HIGHER_PRICE", [])
        else:
            signals = engine.generate_signals(
                signal_date=s_date,
                universe=target_universe,
                model_version=args.model_version,
                use_champion=args.use_champion,
                bars_by_ticker=bars_by_ticker,
                config=config,
                mode=args.mode,
            )
    except Exception as e:
        sys.stderr.write(f"[generate_signals] Error during signal generation: {e}\n")
        sys.exit(1)

    # Persist to DB if requested
    if args.save_db and signals:
        sig_repo = SignalRepository(db_url)
        try:
            saved_cnt = sig_repo.save_signals(signals, ignore_existing=args.ignore_existing)
            sys.stderr.write(
                f"[generate_signals] Persisted {saved_cnt} signals into 'signals_daily'.\n"
            )
        except Exception as e:
            sys.stderr.write(f"[generate_signals] Database error while saving signals: {e}\n")
            sys.exit(1)

    # Output presentation
    if args.format == "json":
        data = [s.model_dump(mode="json") for s in signals]
        print(json.dumps(data, indent=2))
    elif args.format == "csv":
        print_csv_signals(signals)
    else:
        print_table_signals(signals, args.date)


if __name__ == "__main__":
    main()
