import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from python.common.types import PositionRecord
from python.config.settings import settings


class PositionJournalRepository:
    """SQLite repository for manual position journal records.

    Manages persistent execution state of manual positions in accordance with
    Principle 2 (Actual positions are separate from signals).
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or settings.database_url
        self._is_memory = ":memory:" in self.database_url
        self.db_path = self._resolve_db_path(self.database_url)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _resolve_db_path(self, url: str) -> str:
        if ":memory:" in url or url.strip() in ("sqlite://", ":memory:"):
            return ":memory:"
        if url.startswith("sqlite:///"):
            raw_path = url[len("sqlite:///") :]
            p = Path(raw_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            return str(p)
        if url.startswith("sqlite://"):
            raw_path = url[len("sqlite://") :]
            p = Path(raw_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            return str(p)
        p = Path(url)
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._conn is None:
                self._conn = sqlite3.connect(":memory:")
                self._conn.row_factory = sqlite3.Row
            return self._conn

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                if not self._is_memory:
                    conn.execute("PRAGMA journal_mode = WAL;")
                    conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS positions_journal (
                        position_id TEXT PRIMARY KEY,
                        signal_id TEXT,
                        ticker TEXT NOT NULL,
                        actual_entry_date TEXT NOT NULL,
                        actual_entry_price REAL NOT NULL,
                        quantity INTEGER NOT NULL,
                        actual_exit_date TEXT,
                        actual_exit_price REAL,
                        status TEXT NOT NULL,
                        exit_reason TEXT,
                        realized_return REAL,
                        fees REAL NOT NULL DEFAULT 0.0,
                        holding_days INTEGER,
                        notes TEXT,
                        mode TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                cols = [
                    row[1]
                    for row in conn.execute("PRAGMA table_info(positions_journal);").fetchall()
                ]
                if "mode" not in cols:
                    conn.execute("ALTER TABLE positions_journal ADD COLUMN mode TEXT;")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_positions_journal_mode "
                    "ON positions_journal(mode);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_positions_journal_status "
                    "ON positions_journal(status);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_positions_journal_ticker "
                    "ON positions_journal(ticker);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_positions_journal_entry_date "
                    "ON positions_journal(actual_entry_date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_positions_journal_signal_id "
                    "ON positions_journal(signal_id);"
                )
        finally:
            if not self._is_memory:
                conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> PositionRecord:
        mode_val = row["mode"] if "mode" in row.keys() else None
        return PositionRecord(
            position_id=row["position_id"],
            signal_id=row["signal_id"],
            ticker=row["ticker"],
            actual_entry_date=date.fromisoformat(row["actual_entry_date"]),
            actual_entry_price=float(row["actual_entry_price"]),
            quantity=int(row["quantity"]),
            actual_exit_date=(
                date.fromisoformat(row["actual_exit_date"]) if row["actual_exit_date"] else None
            ),
            actual_exit_price=(
                float(row["actual_exit_price"]) if row["actual_exit_price"] is not None else None
            ),
            status=row["status"],
            exit_reason=row["exit_reason"],
            realized_return=(
                float(row["realized_return"]) if row["realized_return"] is not None else None
            ),
            fees=float(row["fees"]) if row["fees"] is not None else 0.0,
            holding_days=(int(row["holding_days"]) if row["holding_days"] is not None else None),
            notes=row["notes"],
            mode=mode_val,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create_position(self, record: PositionRecord) -> PositionRecord:
        """Insert a new position record into the database."""
        validated = PositionRecord.model_validate(record.model_dump())
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO positions_journal (
                        position_id, signal_id, ticker, actual_entry_date,
                        actual_entry_price, quantity, actual_exit_date,
                        actual_exit_price, status, exit_reason,
                        realized_return, fees, holding_days, notes,
                        mode, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        validated.position_id,
                        validated.signal_id,
                        validated.ticker,
                        str(validated.actual_entry_date),
                        validated.actual_entry_price,
                        validated.quantity,
                        str(validated.actual_exit_date) if validated.actual_exit_date else None,
                        validated.actual_exit_price,
                        validated.status,
                        validated.exit_reason,
                        validated.realized_return,
                        validated.fees,
                        validated.holding_days,
                        validated.notes,
                        validated.mode_id,
                        validated.created_at.isoformat(),
                        validated.updated_at.isoformat(),
                    ),
                )
            return validated
        finally:
            if not self._is_memory:
                conn.close()

    def get_position_by_id(self, position_id: str) -> Optional[PositionRecord]:
        """Fetch a position by position_id (exact match or unique prefix)."""
        clean_id = (position_id or "").strip()
        if not clean_id:
            return None

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM positions_journal WHERE position_id = ?;",
                (clean_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                return self._row_to_record(row)

            # Prefix fallback for short IDs (e.g. first 8 chars)
            if len(clean_id) >= 6:
                cursor = conn.execute(
                    "SELECT * FROM positions_journal WHERE position_id LIKE ?;",
                    (f"{clean_id}%",),
                )
                rows = cursor.fetchall()
                if len(rows) == 1:
                    return self._row_to_record(rows[0])
                if len(rows) > 1:
                    raise ValueError(
                        f"Ambiguous position ID prefix '{clean_id}' matches {len(rows)} positions"
                    )
            return None
        finally:
            if not self._is_memory:
                conn.close()

    def get_open_positions(self, ticker: Optional[str] = None) -> list[PositionRecord]:
        """Fetch currently open positions ordered by entry date (FIFO)."""
        conn = self._get_connection()
        try:
            if ticker:
                clean_ticker = ticker.strip().upper().removesuffix(".JK")
                cursor = conn.execute(
                    """
                    SELECT * FROM positions_journal
                    WHERE status = 'OPEN' AND ticker = ?
                    ORDER BY actual_entry_date ASC, created_at ASC;
                    """,
                    (clean_ticker,),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM positions_journal
                    WHERE status = 'OPEN'
                    ORDER BY actual_entry_date ASC, created_at ASC;
                    """
                )
            return [self._row_to_record(r) for r in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def get_closed_positions(
        self,
        ticker: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[PositionRecord]:
        """Fetch closed positions ordered by exit date descending."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM positions_journal WHERE status = 'CLOSED'"
            params: list[Any] = []
            if ticker:
                clean_ticker = ticker.strip().upper().removesuffix(".JK")
                query += " AND ticker = ?"
                params.append(clean_ticker)
            query += " ORDER BY actual_exit_date DESC, updated_at DESC"
            if limit is not None and limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            return [self._row_to_record(r) for r in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def update_position(self, record: PositionRecord) -> PositionRecord:
        """Update an existing position record by position_id."""
        validated = PositionRecord.model_validate(record.model_dump())
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE positions_journal
                    SET signal_id = ?,
                        ticker = ?,
                        actual_entry_date = ?,
                        actual_entry_price = ?,
                        quantity = ?,
                        actual_exit_date = ?,
                        actual_exit_price = ?,
                        status = ?,
                        exit_reason = ?,
                        realized_return = ?,
                        fees = ?,
                        holding_days = ?,
                        notes = ?,
                        updated_at = ?
                    WHERE position_id = ?;
                    """,
                    (
                        validated.signal_id,
                        validated.ticker,
                        str(validated.actual_entry_date),
                        validated.actual_entry_price,
                        validated.quantity,
                        str(validated.actual_exit_date) if validated.actual_exit_date else None,
                        validated.actual_exit_price,
                        validated.status,
                        validated.exit_reason,
                        validated.realized_return,
                        validated.fees,
                        validated.holding_days,
                        validated.notes,
                        validated.updated_at.isoformat(),
                        validated.position_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"Position '{validated.position_id}' not found for update")
            return validated
        finally:
            if not self._is_memory:
                conn.close()

    def get_positions_by_ticker(
        self,
        ticker: str,
        status: Optional[str] = None,
    ) -> list[PositionRecord]:
        """Fetch all positions for a specific ticker, optionally filtered by status."""
        clean_ticker = (ticker or "").strip().upper().removesuffix(".JK")
        conn = self._get_connection()
        try:
            if status:
                cursor = conn.execute(
                    """
                    SELECT * FROM positions_journal
                    WHERE ticker = ? AND status = ?
                    ORDER BY actual_entry_date ASC, created_at ASC;
                    """,
                    (clean_ticker, status.strip().upper()),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM positions_journal
                    WHERE ticker = ?
                    ORDER BY actual_entry_date ASC, created_at ASC;
                    """,
                    (clean_ticker,),
                )
            return [self._row_to_record(r) for r in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def list_positions(
        self,
        status: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[PositionRecord]:
        """List positions with optional status, ticker filter, and limit."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM positions_journal WHERE 1=1"
            params: list[Any] = []
            if status and status.upper() != "ALL":
                query += " AND status = ?"
                params.append(status.strip().upper())
            if ticker:
                clean_ticker = ticker.strip().upper().removesuffix(".JK")
                query += " AND ticker = ?"
                params.append(clean_ticker)
            query += " ORDER BY actual_entry_date DESC, created_at DESC"
            if limit is not None and limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            return [self._row_to_record(r) for r in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def count_positions(self, status: Optional[str] = None) -> int:
        """Count positions, optionally filtered by status."""
        conn = self._get_connection()
        try:
            if status and status.upper() != "ALL":
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM positions_journal WHERE status = ?;",
                    (status.strip().upper(),),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM positions_journal;")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            if not self._is_memory:
                conn.close()

    def clear_positions(self) -> None:
        """Remove all records from positions_journal (for testing)."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM positions_journal;")
        finally:
            if not self._is_memory:
                conn.close()
