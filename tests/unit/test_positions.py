from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from python.common.types import DailyBar, PositionRecord, SignalRecord
from python.journal.repository import PositionJournalRepository
from python.journal.service import PositionJournalService
from python.signals.repository import SignalRepository


def test_position_record_pydantic_validation():
    # Valid OPEN record
    pos = PositionRecord(
        ticker="bbca.jk",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=10000.0,
        quantity=100,
        signal_id="sig_001",
    )
    assert pos.ticker == "BBCA"
    assert pos.status == "OPEN"
    assert pos.signal_id == "sig_001"
    assert pos.position_id is not None
    assert pos.fees == 0.0

    # Invalid entry price <= 0
    with pytest.raises(ValueError, match="actual_entry_price must be positive"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=-100.0,
            quantity=10,
        )

    # Invalid quantity <= 0
    with pytest.raises(ValueError, match="quantity must be > 0"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=0,
        )

    # Invalid status
    with pytest.raises(ValueError, match="status must be one of"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=10,
            status="INVALID",
        )

    # Invalid exit reason
    with pytest.raises(ValueError, match="exit_reason must be one of"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=10,
            status="CLOSED",
            actual_exit_date=date(2026, 10, 5),
            actual_exit_price=10500.0,
            exit_reason="MAGIC",
        )

    # Negative fees
    with pytest.raises(ValueError, match="fees must be non-negative"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=10,
            fees=-50.0,
        )

    # Exit date before entry date
    with pytest.raises(ValueError, match="cannot precede actual_entry_date"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 5),
            actual_entry_price=10000.0,
            quantity=10,
            status="CLOSED",
            actual_exit_date=date(2026, 10, 1),
            actual_exit_price=10500.0,
        )

    # OPEN with exit price rejected
    with pytest.raises(ValueError, match="Open position cannot have actual_exit_price"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=10,
            status="OPEN",
            actual_exit_price=10500.0,
        )

    # CLOSED without exit price rejected
    with pytest.raises(ValueError, match="Closed position must specify actual_exit_price"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=10,
            status="CLOSED",
            actual_exit_date=date(2026, 10, 5),
        )

    # Valid CLOSED auto-calculates holding days & realized return
    closed_pos = PositionRecord(
        ticker="BBCA",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=10000.0,
        quantity=100,
        status="CLOSED",
        actual_exit_date=date(2026, 10, 6),
        actual_exit_price=10500.0,
        fees=10000.0,
    )
    assert closed_pos.holding_days == 5
    # cost basis = 1,000,000; net pnl = 50,000 - 10,000 = 40,000; ret = 0.04
    assert closed_pos.realized_return == pytest.approx(0.04)
    assert closed_pos.exit_reason == "MANUAL"


def test_position_repository_crud():
    repo = PositionJournalRepository(database_url=":memory:")
    assert repo.count_positions() == 0

    record = PositionRecord(
        position_id="test-pos-uuid-123456",
        ticker="BBRI",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=5000.0,
        quantity=200,
    )
    created = repo.create_position(record)
    assert created.position_id == "test-pos-uuid-123456"
    assert repo.count_positions() == 1
    assert repo.count_positions(status="OPEN") == 1
    assert repo.count_positions(status="CLOSED") == 0

    # Fetch by exact ID and prefix
    by_id = repo.get_position_by_id("test-pos-uuid-123456")
    assert by_id is not None
    assert by_id.ticker == "BBRI"

    by_prefix = repo.get_position_by_id("test-pos")
    assert by_prefix is not None
    assert by_prefix.position_id == "test-pos-uuid-123456"

    # Nonexistent ID
    assert repo.get_position_by_id("nonexistent") is None
    assert repo.get_position_by_id("") is None

    # Get open positions
    open_list = repo.get_open_positions()
    assert len(open_list) == 1
    assert open_list[0].ticker == "BBRI"

    # Filter open positions by ticker
    assert len(repo.get_open_positions(ticker="BBRI.JK")) == 1
    assert len(repo.get_open_positions(ticker="BMRI")) == 0

    # Update position to CLOSED
    created.status = "CLOSED"
    created.actual_exit_date = date(2026, 10, 5)
    created.actual_exit_price = 5200.0
    created.exit_reason = "TP"
    created.holding_days = 4
    created.realized_return = 0.04
    repo.update_position(created)

    assert repo.count_positions(status="OPEN") == 0
    assert repo.count_positions(status="CLOSED") == 1

    closed_list = repo.get_closed_positions()
    assert len(closed_list) == 1
    assert closed_list[0].exit_reason == "TP"

    # Positions by ticker
    by_ticker = repo.get_positions_by_ticker("BBRI")
    assert len(by_ticker) == 1
    assert repo.get_positions_by_ticker("BBRI", status="OPEN") == []
    assert len(repo.get_positions_by_ticker("BBRI", status="CLOSED")) == 1

    # List positions with filters
    assert len(repo.list_positions(status="CLOSED", ticker="BBRI", limit=5)) == 1
    assert len(repo.list_positions(status="OPEN")) == 0

    # Clear positions
    repo.clear_positions()
    assert repo.count_positions() == 0


def test_journal_service_open_close_cancel_lifecycle():
    repo = PositionJournalRepository(database_url=":memory:")
    service = PositionJournalService(repo=repo)

    # 1. Open Position
    pos = service.open_position(
        ticker="BBCA",
        entry_price=10000.0,
        quantity=100,
        entry_date=date(2026, 10, 1),
        signal_id="sig_test_bbca",
        fees=1500.0,
        notes="Testing lifecycle",
    )
    assert pos.status == "OPEN"
    assert pos.actual_entry_price == 10000.0
    assert pos.quantity == 100
    assert pos.fees == 1500.0
    assert pos.signal_id == "sig_test_bbca"

    # 2. Close Position with profit and additional exit fee
    # cost basis = 10,000 * 100 = 1,000,000
    # exit gross = 10,500 * 100 = 1,050,000 (+50,000)
    # total fees = 1,500 (entry) + 2,500 (exit) = 4,000
    # net pnl = 50,000 - 4,000 = 46,000 (+4.60%)
    closed = service.close_position(
        position_id_or_ticker=pos.position_id,
        exit_price=10500.0,
        exit_date=date(2026, 10, 8),
        exit_reason="TP",
        fees=2500.0,
    )
    assert closed.status == "CLOSED"
    assert closed.holding_days == 7
    assert closed.fees == 4000.0
    assert closed.realized_return == pytest.approx(0.046)
    assert closed.exit_reason == "TP"

    # Cannot close already closed position
    with pytest.raises(ValueError, match="is already CLOSED"):
        service.close_position(
            position_id_or_ticker=pos.position_id,
            exit_price=10600.0,
        )

    # Cannot close with negative price
    service.open_position(ticker="TLKM", entry_price=3000.0, quantity=500)
    with pytest.raises(ValueError, match="exit_price must be positive"):
        service.close_position(position_id_or_ticker="TLKM", exit_price=-3100.0)

    # Cannot close with exit date before entry date
    with pytest.raises(ValueError, match="cannot precede entry_date"):
        service.close_position(
            position_id_or_ticker="TLKM",
            exit_price=3100.0,
            exit_date=date.today() - timedelta(days=2),
        )

    # Cancel position
    cancelled = service.cancel_position(
        position_id_or_ticker="TLKM",
        reason="Order retracted by user",
    )
    assert cancelled.status == "CANCELLED"
    assert "Order retracted" in (cancelled.notes or "")

    # Cannot cancel already cancelled position by ID
    with pytest.raises(ValueError, match="is already CANCELLED"):
        service.cancel_position(cancelled.position_id)

    # Calling by ticker when no open position remains raises not found
    with pytest.raises(ValueError, match="No open position found for 'TLKM'"):
        service.cancel_position("TLKM")


def test_fifo_position_resolution():
    repo = PositionJournalRepository(database_url=":memory:")
    service = PositionJournalService(repo=repo)

    # Open position 1 on Day 1
    p1 = service.open_position(
        ticker="BMRI",
        entry_price=6000.0,
        quantity=100,
        entry_date=date(2026, 10, 1),
    )
    # Open position 2 on Day 3
    p2 = service.open_position(
        ticker="BMRI",
        entry_price=6200.0,
        quantity=100,
        entry_date=date(2026, 10, 3),
    )

    # First close targeting ticker 'BMRI' should close p1 (FIFO)
    closed1 = service.close_position(
        position_id_or_ticker="BMRI",
        exit_price=6400.0,
        exit_date=date(2026, 10, 10),
    )
    assert closed1.position_id == p1.position_id
    assert closed1.actual_entry_price == 6000.0

    # Second close targeting 'BMRI' should close p2
    closed2 = service.close_position(
        position_id_or_ticker="BMRI",
        exit_price=6300.0,
        exit_date=date(2026, 10, 10),
    )
    assert closed2.position_id == p2.position_id
    assert closed2.actual_entry_price == 6200.0

    # Third close should fail as no open positions remain
    with pytest.raises(ValueError, match="No open position found for 'BMRI'"):
        service.close_position(position_id_or_ticker="BMRI", exit_price=6500.0)


def test_principle_2_signals_independent_of_positions():
    """Principle 2: Actual positions are separate from signals.

    A signal generated or recorded MUST NOT create an open position or affect
    portfolio loss if the user did not execute it.
    """
    sig_repo = SignalRepository(database_url=":memory:")
    journal_repo = PositionJournalRepository(database_url=":memory:")
    journal_service = PositionJournalService(repo=journal_repo)

    # Record 3 signals into the signal repository
    for i, t in enumerate(["BBCA", "BBRI", "BMRI"]):
        sig = SignalRecord(
            signal_id=f"sig_p2_{i}",
            ticker=t,
            signal_date=date(2026, 10, 12),
            signal="BUY",
            entry_low=9900.0,
            entry_high=10000.0,
            tp_price=10500.0,
            sl_price=9700.0,
            max_holding_days=10,
            predicted_probability=0.75,
            expected_return=0.04,
            score=90.0,
            model_version="v1.0.0",
        )
        sig_repo.save_signals([sig])

    assert sig_repo.count_signals() == 3

    # Verify positions journal remains 100% untouched
    assert journal_repo.count_positions() == 0
    assert len(journal_service.get_open_positions()) == 0

    # User explicitly enters only BBCA
    entered = journal_service.open_position(
        ticker="BBCA",
        entry_price=9950.0,
        quantity=100,
        signal_id="sig_p2_0",
    )
    assert journal_repo.count_positions() == 1
    assert entered.signal_id == "sig_p2_0"

    # User did NOT buy BBRI or BMRI: no positions exist for them
    assert len(journal_service.get_open_positions(ticker="BBRI")) == 0
    assert len(journal_service.get_open_positions(ticker="BMRI")) == 0

    # User also manually opens an un-signaled position (discretionary)
    manual_pos = journal_service.open_position(
        ticker="ASII",
        entry_price=4500.0,
        quantity=50,
        signal_id=None,  # No signal backing
        notes="Discretionary trade",
    )
    assert manual_pos.signal_id is None
    assert journal_repo.count_positions() == 2


def test_unrealized_pnl_calculation():
    journal_repo = PositionJournalRepository(database_url=":memory:")
    mock_bar_repo = MagicMock()

    service = PositionJournalService(repo=journal_repo, bar_repo=mock_bar_repo)

    pos = service.open_position(
        ticker="BBCA",
        entry_price=10000.0,
        quantity=100,
    )

    # 1. Price passed explicitly
    amt, pct = service.get_unrealized_pnl(pos, current_price=10500.0)
    assert amt == 50000.0
    assert pct == pytest.approx(0.05)

    # 2. Price retrieved from mock bar repo
    mock_bar = DailyBar(
        ticker="BBCA",
        date=date(2026, 10, 12),
        open=10200.0,
        high=10400.0,
        low=10100.0,
        close=10300.0,
        volume=100000.0,
    )
    mock_bar_repo.get_daily_bars.return_value = [mock_bar]

    amt_repo, pct_repo = service.get_unrealized_pnl(pos)
    assert amt_repo == 30000.0
    assert pct_repo == pytest.approx(0.03)

    # 3. No market data available
    mock_bar_repo.get_daily_bars.return_value = []
    amt_none, pct_none = service.get_unrealized_pnl(pos)
    assert amt_none is None
    assert pct_none is None


def test_position_record_extended_validation_and_assignment():
    pos = PositionRecord(
        ticker="BBCA",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=10000.0,
        quantity=100,
        signal_id="   ",
    )
    # Empty/whitespace signal_id normalized to None
    assert pos.signal_id is None

    # invalid status on creation raises ValidationError
    with pytest.raises(ValueError, match="status must be one of"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="BOGUS_STATUS",
        )

    # invalid exit reason on creation raises ValidationError
    with pytest.raises(ValueError, match="exit_reason must be one of"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            exit_reason="MAGIC_REASON",
        )

    # negative fees on creation raises ValidationError
    with pytest.raises(ValueError, match="fees must be non-negative"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            fees=-10.0,
        )

    # CANCELLED position cannot have exit price
    with pytest.raises(ValueError, match="Cancelled position cannot have actual_exit_price"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="CANCELLED",
            actual_exit_price=10500.0,
        )

    # CANCELLED position cannot have exit date
    with pytest.raises(ValueError, match="Cancelled position cannot have actual_exit_date"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="CANCELLED",
            actual_exit_date=date(2026, 10, 5),
        )

    # CANCELLED position cannot have realized return
    with pytest.raises(ValueError, match="Cancelled position cannot have realized_return"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="CANCELLED",
            realized_return=0.05,
        )

    # Non-finite realized_return rejected
    with pytest.raises(ValueError, match="realized_return must be a finite float"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="CLOSED",
            actual_exit_date=date(2026, 10, 5),
            actual_exit_price=10500.0,
            realized_return=float("nan"),
        )


def test_position_service_strict_error_paths():
    repo = PositionJournalRepository(database_url=":memory:")
    service = PositionJournalService(repo=repo)

    pos = service.open_position("BBCA", 10000.0, 100)

    # Invalid exit reason rejected without corrupting DB
    with pytest.raises(ValueError, match="exit_reason must be one of"):
        service.close_position(pos.position_id, 10500.0, exit_reason="UNKNOWN_REASON")

    # DB remains cleanly OPEN
    stored = repo.get_position_by_id(pos.position_id)
    assert stored is not None
    assert stored.status == "OPEN"

    # NaN exit price rejected
    with pytest.raises(ValueError, match="exit_price must be positive and finite"):
        service.close_position(pos.position_id, float("nan"))

    # Negative exit fee rejected
    with pytest.raises(ValueError, match="fees must be non-negative and finite"):
        service.close_position(pos.position_id, 10500.0, fees=-200.0)

    # Repo update_position revalidates
    invalid_pos = pos.model_copy()
    object.__setattr__(invalid_pos, "actual_entry_price", -500.0)
    with pytest.raises(ValidationError):
        repo.update_position(invalid_pos)


def test_repository_ambiguous_prefix():
    repo = PositionJournalRepository(database_url=":memory:")
    # Create two positions with identical first 8 characters
    p1 = PositionRecord(
        position_id="prefix1234-aaaa-bbbb",
        ticker="BBCA",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=10000.0,
        quantity=100,
    )
    p2 = PositionRecord(
        position_id="prefix1234-cccc-dddd",
        ticker="BBRI",
        actual_entry_date=date(2026, 10, 2),
        actual_entry_price=5000.0,
        quantity=200,
    )
    repo.create_position(p1)
    repo.create_position(p2)

    # Exact ID works
    assert repo.get_position_by_id("prefix1234-aaaa-bbbb") is not None

    # Ambiguous prefix raises informative ValueError
    with pytest.raises(ValueError, match="Ambiguous position ID prefix 'prefix1234' matches 2"):
        repo.get_position_by_id("prefix1234")


def test_journal_repository_concurrent_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "concurrent_journal.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    repo = PositionJournalRepository(database_url=db_url)
    service = PositionJournalService(repo=repo)

    def worker_trade(idx: int) -> str:
        # Open position
        pos = service.open_position(
            ticker=f"TK{idx:02d}",
            entry_price=1000.0 + idx,
            quantity=100,
            entry_date=date(2026, 10, 1),
        )
        # Close position
        closed = service.close_position(
            position_id_or_ticker=pos.position_id,
            exit_price=1100.0 + idx,
            exit_date=date(2026, 10, 5),
            exit_reason="TP",
        )
        return closed.position_id

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(worker_trade, range(12)))

    assert len(results) == 12
    assert repo.count_positions(status="CLOSED") == 12
    assert repo.count_positions(status="OPEN") == 0
