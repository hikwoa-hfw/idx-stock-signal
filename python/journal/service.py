import math
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from python.common.types import PositionRecord
from python.data.repository import DailyBarRepository
from python.journal.repository import PositionJournalRepository


class PositionJournalService:
    """Application service for manual position management.

    Encapsulates position entry, exit calculations, lifecycle transitions,
    and portfolio tracking. In strict accordance with Principle 2, position
    operations never modify signal records or confuse actual fills with signals.
    """

    def __init__(
        self,
        repo: Optional[PositionJournalRepository] = None,
        bar_repo: Optional[DailyBarRepository] = None,
    ) -> None:
        self.repo = repo or PositionJournalRepository()
        self.bar_repo = bar_repo

    def open_position(
        self,
        ticker: str,
        entry_price: float,
        quantity: int,
        entry_date: Optional[date] = None,
        signal_id: Optional[str] = None,
        fees: float = 0.0,
        notes: Optional[str] = None,
    ) -> PositionRecord:
        """Open a new actual manual trading position.

        Parameters
        ----------
        ticker : str
            Stock ticker (e.g. 'BBCA' or 'BBCA.JK').
        entry_price : float
            Actual fill price (> 0).
        quantity : int
            Quantity in shares or lots (> 0).
        entry_date : date, optional
            Actual entry date (defaults to today).
        signal_id : str, optional
            Reference signal ID if position was inspired by a signal (Principle 2).
        fees : float, optional
            Entry transaction fee / brokerage commission (default 0.0).
        notes : str, optional
            Optional freeform commentary.
        """
        resolved_date = entry_date or date.today()
        record = PositionRecord(
            position_id=str(uuid.uuid4()),
            signal_id=signal_id.strip() if signal_id else None,
            ticker=ticker,
            actual_entry_date=resolved_date,
            actual_entry_price=float(entry_price),
            quantity=int(quantity),
            status="OPEN",
            fees=float(fees or 0.0),
            notes=notes.strip() if notes else None,
        )
        return self.repo.create_position(record)

    def _resolve_open_position(self, position_id_or_ticker: str) -> PositionRecord:
        """Resolve an open position by ID or ticker (FIFO)."""
        clean_target = (position_id_or_ticker or "").strip()
        if not clean_target:
            raise ValueError("Position ID or ticker must be provided")

        # 1. Try finding by ID
        pos = self.repo.get_position_by_id(clean_target)
        if pos is not None:
            if pos.status != "OPEN":
                raise ValueError(
                    f"Position '{pos.position_id}' ({pos.ticker}) is already {pos.status}"
                )
            return pos

        # 2. Try finding by ticker
        candidates = self.repo.get_open_positions(ticker=clean_target)
        if candidates:
            return candidates[0]  # FIFO: oldest open position

        raise ValueError(f"No open position found for '{clean_target}'")

    def close_position(
        self,
        position_id_or_ticker: str,
        exit_price: float,
        exit_date: Optional[date] = None,
        exit_reason: str = "MANUAL",
        fees: float = 0.0,
    ) -> PositionRecord:
        """Close an existing open position and compute realized return net of fees.

        Parameters
        ----------
        position_id_or_ticker : str
            Unique position UUID or ticker symbol to close (FIFO).
        exit_price : float
            Actual fill exit price (> 0).
        exit_date : date, optional
            Exit execution date (defaults to today).
        exit_reason : str, optional
            Reason for exit ('TP', 'SL', 'EXPIRY', 'MANUAL', 'OTHER').
        fees : float, optional
            Exit transaction fees to be added to position total fees.
        """
        pos = self._resolve_open_position(position_id_or_ticker)
        resolved_exit_date = exit_date or date.today()

        p_exit = float(exit_price)
        if not math.isfinite(p_exit) or p_exit <= 0:
            raise ValueError(f"exit_price must be positive and finite, got {exit_price}")

        f_exit = float(fees or 0.0)
        if not math.isfinite(f_exit) or f_exit < 0:
            raise ValueError(f"fees must be non-negative and finite, got {fees}")

        if resolved_exit_date < pos.actual_entry_date:
            raise ValueError(
                f"exit_date ({resolved_exit_date}) cannot precede "
                f"entry_date ({pos.actual_entry_date})"
            )

        clean_reason = (exit_reason or "MANUAL").strip().upper()
        if clean_reason not in {"TP", "SL", "EXPIRY", "MANUAL", "OTHER"}:
            raise ValueError(
                f"exit_reason must be one of 'TP', 'SL', 'EXPIRY', 'MANUAL', 'OTHER', "
                f"got '{exit_reason}'"
            )

        holding_days = (resolved_exit_date - pos.actual_entry_date).days
        total_fees = pos.fees + f_exit

        cost_basis = pos.actual_entry_price * pos.quantity
        net_pnl = (p_exit - pos.actual_entry_price) * pos.quantity - total_fees
        realized_return = net_pnl / cost_basis

        closed_pos = PositionRecord(
            position_id=pos.position_id,
            signal_id=pos.signal_id,
            ticker=pos.ticker,
            actual_entry_date=pos.actual_entry_date,
            actual_entry_price=pos.actual_entry_price,
            quantity=pos.quantity,
            actual_exit_date=resolved_exit_date,
            actual_exit_price=p_exit,
            status="CLOSED",
            exit_reason=clean_reason,
            fees=total_fees,
            holding_days=holding_days,
            realized_return=realized_return,
            notes=pos.notes,
            created_at=pos.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        return self.repo.update_position(closed_pos)

    def cancel_position(
        self,
        position_id_or_ticker: str,
        reason: str = "CANCELLED",
    ) -> PositionRecord:
        """Cancel an open position before execution or in error.

        Parameters
        ----------
        position_id_or_ticker : str
            Unique position UUID or ticker symbol to cancel.
        reason : str, optional
            Explanation for cancellation.
        """
        pos = self._resolve_open_position(position_id_or_ticker)
        note_entry = f"Cancelled: {reason.strip() if reason else 'CANCELLED'}"
        notes_str = f"{pos.notes}; {note_entry}" if pos.notes else note_entry

        cancelled_pos = PositionRecord(
            position_id=pos.position_id,
            signal_id=pos.signal_id,
            ticker=pos.ticker,
            actual_entry_date=pos.actual_entry_date,
            actual_entry_price=pos.actual_entry_price,
            quantity=pos.quantity,
            status="CANCELLED",
            fees=pos.fees,
            notes=notes_str,
            created_at=pos.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        return self.repo.update_position(cancelled_pos)

    def get_open_positions(self, ticker: Optional[str] = None) -> list[PositionRecord]:
        """Fetch all currently open positions."""
        return self.repo.get_open_positions(ticker=ticker)

    def get_closed_positions(
        self,
        ticker: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[PositionRecord]:
        """Fetch all closed positions."""
        return self.repo.get_closed_positions(ticker=ticker, limit=limit)

    def get_position(self, position_id: str) -> Optional[PositionRecord]:
        """Fetch a position by ID."""
        return self.repo.get_position_by_id(position_id)

    def get_unrealized_pnl(
        self,
        position: PositionRecord,
        current_price: Optional[float] = None,
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate unrealized PnL (amount, pct) if market price is available."""
        resolved_price = current_price
        if resolved_price is None and self.bar_repo is not None:
            bars = self.bar_repo.get_daily_bars(position.ticker)
            if bars:
                resolved_price = bars[-1].close

        if resolved_price is not None and resolved_price > 0:
            pnl_amount = (resolved_price - position.actual_entry_price) * position.quantity
            pnl_pct = (resolved_price - position.actual_entry_price) / position.actual_entry_price
            return pnl_amount, pnl_pct

        return None, None
