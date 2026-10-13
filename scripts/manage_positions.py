import argparse
import csv
import json
import sys
from datetime import date, datetime
from typing import Optional

from python.common.types import PositionRecord
from python.config.settings import settings
from python.data.repository import DailyBarRepository
from python.journal.repository import PositionJournalRepository
from python.journal.service import PositionJournalService

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _print_table(
    positions: list[PositionRecord], service: PositionJournalService, status_filter: str
) -> None:
    if not positions:
        print(f"\n[INFO] No positions found matching filter (Status: {status_filter}).\n")
        return

    print("\n" + "=" * 105)
    print("                        INDONESIAN STOCK AI -- POSITION JOURNAL")
    print("=" * 105)
    print(f"Filter Status   : {status_filter}")
    print(f"Total Positions : {len(positions)}")
    print("-" * 105)

    if status_filter.upper() == "OPEN":
        print(
            f"{'ID':<10} {'Ticker':<8} {'Entry Date':<12} {'Entry Price':<13} "
            f"{'Qty':<8} {'Unrealized PnL':<16} {'Signal ID':<12} {'Notes'}"
        )
        print("-" * 105)
        for p in positions:
            short_id = p.position_id[:8]
            _, ret_pct = service.get_unrealized_pnl(p)
            pnl_str = f"{ret_pct * 100:+.2f}%" if ret_pct is not None else "N/A"
            sig_str = p.signal_id[:10] if p.signal_id else "-"
            notes_str = p.notes or "-"
            print(
                f"{short_id:<10} {p.ticker:<8} {str(p.actual_entry_date):<12} "
                f"{p.actual_entry_price:<13,.2f} {p.quantity:<8,} {pnl_str:<16} "
                f"{sig_str:<12} {notes_str}"
            )
    elif status_filter.upper() == "CLOSED":
        print(
            f"{'ID':<10} {'Ticker':<8} {'Entry Date':<12} {'Exit Date':<12} "
            f"{'Entry Price':<13} {'Exit Price':<13} {'Qty':<8} {'Return':<10} "
            f"{'Hold':<6} {'Reason'}"
        )
        print("-" * 105)
        for p in positions:
            short_id = p.position_id[:8]
            exit_d = str(p.actual_exit_date) if p.actual_exit_date else "-"
            exit_p = f"{p.actual_exit_price:,.2f}" if p.actual_exit_price is not None else "-"
            ret_str = f"{p.realized_return * 100:+.2f}%" if p.realized_return is not None else "N/A"
            hold_str = f"{p.holding_days}D" if p.holding_days is not None else "-"
            reason_str = p.exit_reason or "-"
            print(
                f"{short_id:<10} {p.ticker:<8} {str(p.actual_entry_date):<12} {exit_d:<12} "
                f"{p.actual_entry_price:<13,.2f} {exit_p:<13} {p.quantity:<8,} "
                f"{ret_str:<10} {hold_str:<6} {reason_str}"
            )
    else:
        print(
            f"{'ID':<10} {'Ticker':<8} {'Status':<10} {'Entry Date':<12} "
            f"{'Entry Price':<13} {'Exit Price':<13} {'Qty':<8} {'Return':<10} {'Reason'}"
        )
        print("-" * 105)
        for p in positions:
            short_id = p.position_id[:8]
            exit_p = f"{p.actual_exit_price:,.2f}" if p.actual_exit_price is not None else "-"
            ret_str = f"{p.realized_return * 100:+.2f}%" if p.realized_return is not None else "-"
            reason_str = p.exit_reason or "-"
            print(
                f"{short_id:<10} {p.ticker:<8} {p.status:<10} {str(p.actual_entry_date):<12} "
                f"{p.actual_entry_price:<13,.2f} {exit_p:<13} {p.quantity:<8,} "
                f"{ret_str:<10} {reason_str}"
            )

    print("=" * 105 + "\n")


def _print_csv(positions: list[PositionRecord]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        [
            "position_id",
            "signal_id",
            "ticker",
            "actual_entry_date",
            "actual_entry_price",
            "quantity",
            "actual_exit_date",
            "actual_exit_price",
            "status",
            "exit_reason",
            "realized_return",
            "fees",
            "holding_days",
            "notes",
            "created_at",
            "updated_at",
        ]
    )
    for p in positions:
        writer.writerow(
            [
                p.position_id,
                p.signal_id or "",
                p.ticker,
                str(p.actual_entry_date),
                p.actual_entry_price,
                p.quantity,
                str(p.actual_exit_date) if p.actual_exit_date else "",
                p.actual_exit_price if p.actual_exit_price is not None else "",
                p.status,
                p.exit_reason or "",
                p.realized_return if p.realized_return is not None else "",
                p.fees,
                p.holding_days if p.holding_days is not None else "",
                p.notes or "",
                p.created_at.isoformat(),
                p.updated_at.isoformat(),
            ]
        )


def _print_json(positions: list[PositionRecord]) -> None:
    data = [p.model_dump(mode="json") for p in positions]
    print(json.dumps(data, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Indonesian Stock AI — Position Journal Management CLI",
    )
    parser.add_argument("--db-url", type=str, default=None, help="Database URL")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. enter
    p_enter = subparsers.add_parser("enter", help="Open a manual position")
    p_enter.add_argument("pos_ticker", nargs="?", default=None, help="Ticker symbol (e.g. BBCA)")
    p_enter.add_argument("pos_price", nargs="?", type=float, default=None, help="Entry price")
    p_enter.add_argument("pos_qty", nargs="?", type=int, default=None, help="Quantity")
    p_enter.add_argument("--ticker", dest="opt_ticker", default=None, help="Ticker symbol")
    p_enter.add_argument("--price", dest="opt_price", type=float, default=None, help="Entry price")
    p_enter.add_argument("--qty", dest="opt_qty", type=int, default=None, help="Quantity")
    p_enter.add_argument("--date", type=str, default=None, help="Entry date (YYYY-MM-DD)")
    p_enter.add_argument("--signal-id", type=str, default=None, help="Optional reference signal ID")
    p_enter.add_argument("--fees", type=float, default=0.0, help="Entry transaction fees")
    p_enter.add_argument("--notes", type=str, default=None, help="Optional notes")

    # 2. exit
    p_exit = subparsers.add_parser("exit", help="Close an open position")
    p_exit.add_argument("pos_target", nargs="?", default=None, help="Position ID or ticker symbol")
    p_exit.add_argument("pos_price", nargs="?", type=float, default=None, help="Exit price")
    p_exit.add_argument("pos_reason", nargs="?", default=None, help="Exit reason (TP/SL/MANUAL)")
    p_exit.add_argument("--target", dest="opt_target", default=None, help="Position ID or ticker")
    p_exit.add_argument("--price", dest="opt_price", type=float, default=None, help="Exit price")
    p_exit.add_argument("--reason", dest="opt_reason", default=None, help="Exit reason")
    p_exit.add_argument("--date", type=str, default=None, help="Exit date (YYYY-MM-DD)")
    p_exit.add_argument("--fees", type=float, default=0.0, help="Exit transaction fees")

    # 3. cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel an open position")
    p_cancel.add_argument("pos_target", nargs="?", default=None, help="Position ID or ticker")
    p_cancel.add_argument("pos_reason", nargs="?", default=None, help="Cancellation reason")
    p_cancel.add_argument("--target", dest="opt_target", default=None, help="Position ID or ticker")
    p_cancel.add_argument("--reason", dest="opt_reason", default=None, help="Cancellation reason")

    # 4. list
    p_list = subparsers.add_parser("list", help="List positions")
    p_list.add_argument(
        "--status",
        type=str,
        default="OPEN",
        choices=["OPEN", "CLOSED", "CANCELLED", "ALL"],
        help="Filter status (default: OPEN)",
    )
    p_list.add_argument("--ticker", type=str, default=None, help="Filter by ticker")
    p_list.add_argument("--limit", type=int, default=None, help="Max results")
    p_list.add_argument(
        "--format",
        type=str,
        default="table",
        choices=["table", "json", "csv"],
        help="Output format (table, json, csv)",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    db_url = args.db_url or settings.database_url
    repo = PositionJournalRepository(database_url=db_url)
    bar_repo = DailyBarRepository(database_url=db_url)
    service = PositionJournalService(repo=repo, bar_repo=bar_repo)

    if args.command == "enter":
        ticker = args.opt_ticker or args.pos_ticker
        price = args.opt_price if args.opt_price is not None else args.pos_price
        qty = args.opt_qty if args.opt_qty is not None else args.pos_qty

        if not ticker:
            parser.error("Ticker must be provided (e.g. enter BBCA 10000 100)")
        if price is None or price <= 0:
            parser.error("Price must be a positive number")
        if qty is None or qty <= 0:
            parser.error("Quantity must be a positive integer")
        if args.fees < 0:
            parser.error("Fees must be non-negative")

        if args.date:
            try:
                entry_d = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(
                    f"[ERROR] Invalid date format '{args.date}', expected YYYY-MM-DD",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            entry_d = date.today()

        try:
            record = service.open_position(
                ticker=ticker,
                entry_price=price,
                quantity=qty,
                entry_date=entry_d,
                signal_id=args.signal_id,
                fees=args.fees,
                notes=args.notes,
            )
            print(
                f"[OK] Position opened: ID={record.position_id[:8]} Ticker={record.ticker} "
                f"Price={record.actual_entry_price:,.2f} Qty={record.quantity:,}"
            )
        except Exception as err:
            print(f"[ERROR] Failed to open position: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "exit":
        target = args.opt_target or args.pos_target
        price = args.opt_price if args.opt_price is not None else args.pos_price
        reason = args.opt_reason or args.pos_reason or "MANUAL"

        if not target:
            parser.error("Target position ID or ticker must be provided")
        if price is None or price <= 0:
            parser.error("Exit price must be a positive number")
        if args.fees < 0:
            parser.error("Fees must be non-negative")

        if args.date:
            try:
                exit_d = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(
                    f"[ERROR] Invalid date format '{args.date}', expected YYYY-MM-DD",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            exit_d = date.today()

        try:
            record = service.close_position(
                position_id_or_ticker=target,
                exit_price=price,
                exit_date=exit_d,
                exit_reason=reason,
                fees=args.fees,
            )
            ret_pct = (
                f"{record.realized_return * 100:+.2f}%"
                if record.realized_return is not None
                else "0.00%"
            )
            print(
                f"[OK] Position closed: ID={record.position_id[:8]} Ticker={record.ticker} "
                f"ExitPrice={record.actual_exit_price:,.2f} Return={ret_pct} "
                f"HoldingDays={record.holding_days}D Reason={record.exit_reason}"
            )
        except Exception as err:
            print(f"[ERROR] Failed to close position: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "cancel":
        target = args.opt_target or args.pos_target
        reason = args.opt_reason or args.pos_reason or "CANCELLED"

        if not target:
            parser.error("Target position ID or ticker must be provided")

        try:
            record = service.cancel_position(
                position_id_or_ticker=target,
                reason=reason,
            )
            print(
                f"[OK] Position cancelled: ID={record.position_id[:8]} Ticker={record.ticker} "
                f"Reason={reason}"
            )
        except Exception as err:
            print(f"[ERROR] Failed to cancel position: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        positions = repo.list_positions(
            status=args.status,
            ticker=args.ticker,
            limit=args.limit,
        )
        if args.format == "json":
            _print_json(positions)
        elif args.format == "csv":
            _print_csv(positions)
        else:
            _print_table(positions, service, status_filter=args.status)


if __name__ == "__main__":
    main()
