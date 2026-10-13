import argparse
import sys
from datetime import datetime

from python.common.types import SignalConfig
from python.config.settings import settings
from python.data.provider import DEFAULT_UNIVERSE, load_universe
from python.data.repository import DailyBarRepository
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository
from services.telegram.client import TelegramClient, TelegramError
from services.telegram.formatter import format_daily_signals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Broadcast daily stock signals to Telegram channel."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Signal date in YYYY-MM-DD format (defaults to latest available date).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Max number of top signals to broadcast (default: 5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Format and print message to stdout without making network calls.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate signals using SignalEngine before broadcasting.",
    )
    parser.add_argument(
        "--use-champion",
        action="store_true",
        help="Use current champion model when --generate is set.",
    )
    parser.add_argument(
        "--model-version",
        default=None,
        help="Specific model version when --generate is set.",
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help="Override recipient Telegram chat ID.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLite database URL. Defaults to settings.database_url.",
    )
    parser.add_argument(
        "--single-mode",
        action="store_true",
        help="Format single mode instead of default dual-mode sections.",
    )
    return parser.parse_args()


def main() -> None:
    # ponytail: CLI broadcast runner; add AWS Lambda / EventBridge wrapper when deployed.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()
    if args.top_n < 1:
        sys.stderr.write("[send_daily_telegram] --top-n must be at least 1.\n")
        sys.exit(1)

    if args.use_champion and args.model_version:
        sys.stderr.write(
            "[send_daily_telegram] Cannot specify both --use-champion and --model-version.\n"
        )
        sys.exit(1)

    db_url = args.db_url or settings.database_url
    sig_repo = SignalRepository(db_url)
    bar_repo = DailyBarRepository(db_url)

    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date.strip(), "%Y-%m-%d").date()
        except ValueError:
            sys.stderr.write(
                f"[send_daily_telegram] Invalid date format '{args.date}'. Expected YYYY-MM-DD.\n"
            )
            sys.exit(1)

    if args.generate:
        universe = bar_repo.get_universe() or load_universe() or DEFAULT_UNIVERSE
        bars_by_ticker = {t: bar_repo.get_daily_bars(t) for t in universe}
        bars_by_ticker = {k: v for k, v in bars_by_ticker.items() if v}

        cfg = SignalConfig(top_n=args.top_n)
        engine = SignalEngine(config=cfg, bar_repo=bar_repo)
        try:
            if not args.single_mode:
                dual_results = engine.generate_dual_mode_signals(
                    signal_date=target_date,
                    universe=universe,
                    bars_by_ticker=bars_by_ticker,
                    config=cfg,
                    use_champion=args.use_champion,
                    model_version=args.model_version,
                )
                low_sigs = dual_results.get("LOW_PRICE", [])
                high_sigs = dual_results.get("HIGHER_PRICE", [])
                all_signals = low_sigs + high_sigs
                if all_signals:
                    sig_repo.save_signals(all_signals, ignore_existing=True)
                    target_date = all_signals[0].signal_date
                signals = dual_results
            else:
                signals = engine.generate_signals(
                    signal_date=target_date,
                    universe=universe,
                    model_version=args.model_version,
                    use_champion=args.use_champion,
                    bars_by_ticker=bars_by_ticker,
                    config=cfg,
                )
                if signals:
                    sig_repo.save_signals(signals, ignore_existing=True)
                    target_date = signals[0].signal_date
        except Exception as e:
            sys.stderr.write(f"[send_daily_telegram] Error during signal generation: {e}\n")
            sys.exit(1)
    else:
        if target_date is None:
            distinct_dates = sig_repo.get_distinct_dates()
            if distinct_dates:
                target_date = distinct_dates[-1]

        signals = (
            sig_repo.get_signals(signal_date=target_date)
            if target_date is not None
            else []
        )

    message = format_daily_signals(
        signals=signals,
        target_date=target_date,
        dual_mode=not args.single_mode,
    )

    if args.dry_run:
        print(message)
        sys.exit(0)

    try:
        client = TelegramClient(chat_id=args.chat_id)
        resp = client.send_message(text=message)
        msg_id = resp.get("result", {}).get("message_id")
        sys.stdout.write(f"[send_daily_telegram] Broadcast successful: message_id={msg_id}\n")
    except TelegramError as e:
        sys.stderr.write(f"[send_daily_telegram] Telegram dispatch failed: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
