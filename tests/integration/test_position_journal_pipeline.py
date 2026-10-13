import json
import subprocess
import sys
from unittest.mock import MagicMock

from python.journal.repository import PositionJournalRepository
from python.journal.service import PositionJournalService
from services.telegram.bot import TelegramBotDispatcher


def test_telegram_dispatcher_position_journal_pipeline():
    journal_repo = PositionJournalRepository(database_url=":memory:")
    journal_service = PositionJournalService(repo=journal_repo)
    dispatcher = TelegramBotDispatcher(
        signal_repo=MagicMock(),
        model_registry=MagicMock(),
        journal_service=journal_service,
    )

    # 1. Initial state: no positions
    res = dispatcher.dispatch("/positions")
    assert "No open positions" in res

    # 2. Invalid /enter usage
    res_err1 = dispatcher.dispatch("/enter")
    assert "Usage" in res_err1
    res_err2 = dispatcher.dispatch("/enter BBCA invalid 100")
    assert "Error" in res_err2
    res_err3 = dispatcher.dispatch("/enter BBCA 10000 invalid")
    assert "Error" in res_err3

    # 3. Valid /enter without signal_id
    res_open = dispatcher.dispatch("/enter BBCA 10000 100")
    assert "Position Opened" in res_open
    assert "BBCA" in res_open
    assert "10,000.00" in res_open
    assert "100" in res_open

    # 4. Check /positions
    res_list = dispatcher.dispatch("/positions")
    assert "Open Positions (1)" in res_list
    assert "BBCA" in res_list
    assert "10,000.00" in res_list

    # 5. Enter another position with signal_id
    res_open2 = dispatcher.dispatch("/enter BBRI 5000 200 sig_top1_bbri")
    assert "Position Opened" in res_open2
    assert "BBRI" in res_open2
    assert "sig_top1_bbri" in res_open2

    res_list2 = dispatcher.dispatch("/positions")
    assert "Open Positions (2)" in res_list2

    # 6. Invalid /exit usage
    res_exit_err = dispatcher.dispatch("/exit")
    assert "Usage" in res_exit_err
    res_exit_err2 = dispatcher.dispatch("/exit BBCA not_a_number")
    assert "Error" in res_exit_err2
    res_exit_unknown = dispatcher.dispatch("/exit UNKNOWN 10000")
    assert "Failed to close position" in res_exit_unknown

    # 7. Valid /exit BBCA
    res_exit = dispatcher.dispatch("/exit BBCA 10500 TP")
    assert "Position Closed" in res_exit
    assert "BBCA" in res_exit
    assert "10,500.00" in res_exit
    assert "+5.00%" in res_exit
    assert "TP" in res_exit

    # 8. Check /positions: only BBRI remains
    res_list3 = dispatcher.dispatch("/positions")
    assert "Open Positions (1)" in res_list3
    assert "BBRI" in res_list3
    assert "BBCA" not in res_list3

    # Check ticker-filtered /positions
    res_filtered = dispatcher.dispatch("/positions BBRI")
    assert "Open Positions for BBRI (1)" in res_filtered
    assert "BBRI" in res_filtered

    res_none = dispatcher.dispatch("/positions TLKM")
    assert "No open positions found for 'TLKM'" in res_none

    # 9. Cancel BBRI
    res_cancel = dispatcher.dispatch("/cancel BBRI User changed mind")
    assert "Position Cancelled" in res_cancel
    assert "BBRI" in res_cancel

    # 10. Check /positions: empty again
    res_list4 = dispatcher.dispatch("/positions")
    assert "No open positions" in res_list4

    # 11. Enter and exit with formatted commas
    res_open_commas = dispatcher.dispatch("/enter BBCA 10,000 1,000")
    assert "Position Opened" in res_open_commas
    assert "1,000" in res_open_commas
    res_exit_commas = dispatcher.dispatch("/exit BBCA 10,500 TP")
    assert "Position Closed" in res_exit_commas
    assert "10,500.00" in res_exit_commas

    # 12. Verify /help lists /cancel
    help_out = dispatcher.dispatch("/help")
    assert "/cancel" in help_out


def test_cli_manage_positions_integration(tmp_path):
    db_file = tmp_path / "test_positions.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    def run_cli(*cli_args: str) -> subprocess.CompletedProcess:
        cmd = [
            sys.executable,
            "-m",
            "scripts.manage_positions",
            "--db-url",
            db_url,
            *cli_args,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, check=True)

    # 1. Open position via CLI
    p_enter = run_cli(
        "enter", "BBCA", "9500", "100", "--signal-id", "sig_cli_01", "--notes", "CLI test"
    )
    assert "[OK] Position opened" in p_enter.stdout
    assert "BBCA" in p_enter.stdout

    # 2. List in JSON format
    p_list_json = run_cli("list", "--status", "OPEN", "--format", "json")
    records = json.loads(p_list_json.stdout)
    assert len(records) == 1
    assert records[0]["ticker"] == "BBCA"
    assert records[0]["actual_entry_price"] == 9500.0
    assert records[0]["quantity"] == 100
    pos_id = records[0]["position_id"]

    # 3. List in Table format
    p_list_table = run_cli("list", "--status", "OPEN", "--format", "table")
    assert "INDONESIAN STOCK AI -- POSITION JOURNAL" in p_list_table.stdout
    assert "BBCA" in p_list_table.stdout
    assert "9,500.00" in p_list_table.stdout

    # 4. List in CSV format
    p_list_csv = run_cli("list", "--status", "OPEN", "--format", "csv")
    assert "position_id,signal_id,ticker" in p_list_csv.stdout
    assert "BBCA" in p_list_csv.stdout

    # 5. Close position via CLI
    p_exit = run_cli("exit", pos_id, "10000", "TP", "--fees", "2500")
    assert "[OK] Position closed" in p_exit.stdout
    assert "BBCA" in p_exit.stdout
    assert "10,000.00" in p_exit.stdout

    # 6. List CLOSED positions
    p_list_closed = run_cli("list", "--status", "CLOSED", "--format", "json")
    closed_records = json.loads(p_list_closed.stdout)
    assert len(closed_records) == 1
    assert closed_records[0]["status"] == "CLOSED"
    assert closed_records[0]["exit_reason"] == "TP"
    assert closed_records[0]["realized_return"] is not None

    # 7. Open another position and cancel
    run_cli("enter", "BMRI", "6000", "50")
    p_cancel = run_cli("cancel", "BMRI", "--reason", "Market volatility spiked")
    assert "[OK] Position cancelled" in p_cancel.stdout

    p_list_cancelled = run_cli("list", "--status", "CANCELLED", "--format", "json")
    cancelled_records = json.loads(p_list_cancelled.stdout)
    assert len(cancelled_records) == 1
    assert cancelled_records[0]["ticker"] == "BMRI"
    assert "Market volatility" in cancelled_records[0]["notes"]

    # 8. Error handling: invalid date format in enter
    cmd_bad_date = [
        sys.executable,
        "-m",
        "scripts.manage_positions",
        "--db-url",
        db_url,
        "enter",
        "ASII",
        "5000",
        "100",
        "--date",
        "2026-99-99",
    ]
    p_err_date = subprocess.run(cmd_bad_date, capture_output=True, text=True)
    assert p_err_date.returncode != 0
    assert "Invalid date format" in p_err_date.stderr
    assert "Traceback" not in p_err_date.stderr

    # 9. Error handling: negative fees in enter
    cmd_bad_fees = [
        sys.executable,
        "-m",
        "scripts.manage_positions",
        "--db-url",
        db_url,
        "enter",
        "ASII",
        "5000",
        "100",
        "--fees",
        "-50",
    ]
    p_err_fees = subprocess.run(cmd_bad_fees, capture_output=True, text=True)
    assert p_err_fees.returncode != 0
    assert "Fees must be non-negative" in p_err_fees.stderr
