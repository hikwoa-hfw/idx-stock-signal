import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

from python.common.types import SignalDailySnapshot, SignalOutcomeRecord
from python.config.settings import settings


class OutcomeRepository:
    """SQLite repository for signal outcome tracking and daily snapshots."""

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
                    CREATE TABLE IF NOT EXISTS outcomes_daily (
                        outcome_id TEXT PRIMARY KEY,
                        signal_id TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        signal_date TEXT NOT NULL,
                        entry_date TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        entry_status TEXT NOT NULL DEFAULT 'FILLED',
                        outcome_status TEXT NOT NULL,
                        realized_return REAL,
                        holding_days INTEGER NOT NULL DEFAULT 0,
                        mfe REAL NOT NULL DEFAULT 0.0,
                        mae REAL NOT NULL DEFAULT 0.0,
                        mfe_price REAL DEFAULT 0.0,
                        mae_price REAL DEFAULT 0.0,
                        time_to_peak INTEGER,
                        time_to_tp INTEGER,
                        time_to_sl INTEGER,
                        net_return REAL,
                        exit_date TEXT,
                        exit_price REAL,
                        exit_reason TEXT,
                        resolved_at TEXT,
                        notes TEXT,
                        mode TEXT,
                        UNIQUE (signal_id)
                    );
                    """
                )
                cols = [
                    row[1]
                    for row in conn.execute("PRAGMA table_info(outcomes_daily);").fetchall()
                ]
                new_cols = [
                    ("mode", "TEXT"),
                    ("mfe_price", "REAL DEFAULT 0.0"),
                    ("mae_price", "REAL DEFAULT 0.0"),
                    ("time_to_peak", "INTEGER"),
                    ("time_to_tp", "INTEGER"),
                    ("time_to_sl", "INTEGER"),
                    ("net_return", "REAL"),
                    ("entry_status", "TEXT DEFAULT 'FILLED'"),
                ]
                for c_name, c_type in new_cols:
                    if c_name not in cols:
                        conn.execute(f"ALTER TABLE outcomes_daily ADD COLUMN {c_name} {c_type};")
                conn.execute(
                    "UPDATE outcomes_daily SET entry_status = 'UNFILLED' "
                    "WHERE outcome_status = 'UNFILLED_EXPIRED' "
                    "AND (entry_status IS NULL OR entry_status != 'UNFILLED');"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outcomes_mode "
                    "ON outcomes_daily(mode);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outcomes_signal_id "
                    "ON outcomes_daily(signal_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outcomes_ticker "
                    "ON outcomes_daily(ticker);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outcomes_signal_date "
                    "ON outcomes_daily(signal_date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outcomes_status "
                    "ON outcomes_daily(outcome_status);"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS signal_snapshots_daily (
                        snapshot_id TEXT PRIMARY KEY,
                        signal_id TEXT NOT NULL,
                        snapshot_date TEXT NOT NULL,
                        holding_day INTEGER NOT NULL,
                        close_price REAL NOT NULL,
                        return_from_entry REAL NOT NULL,
                        high_price REAL NOT NULL,
                        low_price REAL NOT NULL,
                        mfe_so_far REAL NOT NULL,
                        mae_so_far REAL NOT NULL,
                        UNIQUE (signal_id, snapshot_date)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_snapshots_signal_date "
                    "ON signal_snapshots_daily(signal_id, snapshot_date);"
                )
        finally:
            if not self._is_memory:
                conn.close()

    def _row_to_outcome(self, row: sqlite3.Row) -> SignalOutcomeRecord:
        exit_date_val = date.fromisoformat(row["exit_date"]) if row["exit_date"] else None
        resolved_at_val = (
            datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
        )
        keys = row.keys()
        mode_val = row["mode"] if "mode" in keys else None

        def _get_float(k: str) -> Optional[float]:
            return float(row[k]) if k in keys and row[k] is not None else None

        def _get_int(k: str) -> Optional[int]:
            return int(row[k]) if k in keys and row[k] is not None else None

        mfe_p = _get_float("mfe_price")
        mae_p = _get_float("mae_price")
        ttp = _get_int("time_to_peak")
        tt_tp = _get_int("time_to_tp")
        tt_sl = _get_int("time_to_sl")
        net_ret = _get_float("net_return")
        entry_status_val = (
            row["entry_status"]
            if "entry_status" in keys and row["entry_status"] is not None
            else ("UNFILLED" if row["outcome_status"] == "UNFILLED_EXPIRED" else "FILLED")
        )

        return SignalOutcomeRecord(
            outcome_id=row["outcome_id"],
            signal_id=row["signal_id"],
            ticker=row["ticker"],
            signal_date=date.fromisoformat(row["signal_date"]),
            entry_date=date.fromisoformat(row["entry_date"]),
            entry_price=float(row["entry_price"]),
            entry_status=entry_status_val,
            outcome_status=row["outcome_status"],
            realized_return=(
                float(row["realized_return"]) if row["realized_return"] is not None else None
            ),
            holding_days=int(row["holding_days"]),
            mfe=float(row["mfe"]),
            mae=float(row["mae"]),
            mfe_price=mfe_p,
            mae_price=mae_p,
            time_to_peak=ttp,
            time_to_tp=tt_tp,
            time_to_sl=tt_sl,
            net_return=net_ret,
            exit_date=exit_date_val,
            exit_price=float(row["exit_price"]) if row["exit_price"] is not None else None,
            exit_reason=row["exit_reason"],
            resolved_at=resolved_at_val,
            notes=row["notes"],
            mode=mode_val,
        )

    def _row_to_snapshot(self, row: sqlite3.Row) -> SignalDailySnapshot:
        return SignalDailySnapshot(
            snapshot_id=row["snapshot_id"],
            signal_id=row["signal_id"],
            snapshot_date=date.fromisoformat(row["snapshot_date"]),
            holding_day=int(row["holding_day"]),
            close_price=float(row["close_price"]),
            return_from_entry=float(row["return_from_entry"]),
            high_price=float(row["high_price"]),
            low_price=float(row["low_price"]),
            mfe_so_far=float(row["mfe_so_far"]),
            mae_so_far=float(row["mae_so_far"]),
        )

    def save_outcome(self, outcome: Union[SignalOutcomeRecord, dict]) -> None:
        rec = (
            outcome
            if isinstance(outcome, SignalOutcomeRecord)
            else SignalOutcomeRecord.model_validate(outcome)
        )
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO outcomes_daily (
                        outcome_id, signal_id, ticker, signal_date, entry_date,
                        entry_price, entry_status, outcome_status, realized_return,
                        holding_days, mfe, mae, mfe_price, mae_price, time_to_peak,
                        time_to_tp, time_to_sl, net_return, exit_date, exit_price,
                        exit_reason, resolved_at, notes, mode
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(signal_id) DO UPDATE SET
                        entry_status = excluded.entry_status,
                        outcome_status = excluded.outcome_status,
                        realized_return = excluded.realized_return,
                        holding_days = excluded.holding_days,
                        mfe = excluded.mfe,
                        mae = excluded.mae,
                        mfe_price = excluded.mfe_price,
                        mae_price = excluded.mae_price,
                        time_to_peak = excluded.time_to_peak,
                        time_to_tp = excluded.time_to_tp,
                        time_to_sl = excluded.time_to_sl,
                        net_return = excluded.net_return,
                        exit_date = excluded.exit_date,
                        exit_price = excluded.exit_price,
                        exit_reason = excluded.exit_reason,
                        resolved_at = COALESCE(outcomes_daily.resolved_at, excluded.resolved_at),
                        notes = COALESCE(excluded.notes, outcomes_daily.notes),
                        mode = COALESCE(outcomes_daily.mode, excluded.mode);
                    """,
                    (
                        rec.outcome_id,
                        rec.signal_id,
                        rec.ticker,
                        rec.signal_date.isoformat(),
                        rec.entry_date.isoformat(),
                        rec.entry_price,
                        rec.entry_status,
                        rec.outcome_status,
                        rec.realized_return,
                        rec.holding_days,
                        rec.mfe,
                        rec.mae,
                        rec.mfe_price,
                        rec.mae_price,
                        rec.time_to_peak,
                        rec.time_to_tp,
                        rec.time_to_sl,
                        rec.net_return,
                        rec.exit_date.isoformat() if rec.exit_date else None,
                        rec.exit_price,
                        rec.exit_reason,
                        rec.resolved_at.isoformat() if rec.resolved_at else None,
                        rec.notes,
                        rec.mode_id,
                    ),
                )
        finally:
            if not self._is_memory:
                conn.close()

    def save_outcomes(self, outcomes: list[Union[SignalOutcomeRecord, dict]]) -> None:
        if not outcomes:
            return
        records = [
            o if isinstance(o, SignalOutcomeRecord) else SignalOutcomeRecord.model_validate(o)
            for o in outcomes
        ]
        conn = self._get_connection()
        try:
            with conn:
                for rec in records:
                    conn.execute(
                        """
                        INSERT INTO outcomes_daily (
                            outcome_id, signal_id, ticker, signal_date, entry_date,
                            entry_price, entry_status, outcome_status, realized_return,
                            holding_days, mfe, mae, mfe_price, mae_price, time_to_peak,
                            time_to_tp, time_to_sl, net_return, exit_date, exit_price,
                            exit_reason, resolved_at, notes, mode
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        ON CONFLICT(signal_id) DO UPDATE SET
                            entry_status = excluded.entry_status,
                            outcome_status = excluded.outcome_status,
                            realized_return = excluded.realized_return,
                            holding_days = excluded.holding_days,
                            mfe = excluded.mfe,
                            mae = excluded.mae,
                            mfe_price = excluded.mfe_price,
                            mae_price = excluded.mae_price,
                            time_to_peak = excluded.time_to_peak,
                            time_to_tp = excluded.time_to_tp,
                            time_to_sl = excluded.time_to_sl,
                            net_return = excluded.net_return,
                            exit_date = excluded.exit_date,
                            exit_price = excluded.exit_price,
                            exit_reason = excluded.exit_reason,
                            resolved_at = COALESCE(
                                outcomes_daily.resolved_at, excluded.resolved_at
                            ),
                            notes = COALESCE(excluded.notes, outcomes_daily.notes),
                            mode = COALESCE(outcomes_daily.mode, excluded.mode);
                        """,
                        (
                            rec.outcome_id,
                            rec.signal_id,
                            rec.ticker,
                            rec.signal_date.isoformat(),
                            rec.entry_date.isoformat(),
                            rec.entry_price,
                            rec.entry_status,
                            rec.outcome_status,
                            rec.realized_return,
                            rec.holding_days,
                            rec.mfe,
                            rec.mae,
                            rec.mfe_price,
                            rec.mae_price,
                            rec.time_to_peak,
                            rec.time_to_tp,
                            rec.time_to_sl,
                            rec.net_return,
                            rec.exit_date.isoformat() if rec.exit_date else None,
                            rec.exit_price,
                            rec.exit_reason,
                            rec.resolved_at.isoformat() if rec.resolved_at else None,
                            rec.notes,
                            rec.mode_id,
                        ),
                    )
        finally:
            if not self._is_memory:
                conn.close()

    def get_outcome_by_signal_id(self, signal_id: str) -> Optional[SignalOutcomeRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM outcomes_daily WHERE signal_id = ? LIMIT 1;",
                (signal_id.strip(),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_outcome(row)
        finally:
            if not self._is_memory:
                conn.close()

    def get_outcome_by_id(self, outcome_id: str) -> Optional[SignalOutcomeRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM outcomes_daily WHERE outcome_id = ? LIMIT 1;",
                (outcome_id.strip(),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_outcome(row)
        finally:
            if not self._is_memory:
                conn.close()

    def get_outcome_statuses_map(self) -> dict[str, tuple[str, str, Optional[str]]]:
        """Return mapping of signal_id -> (outcome_id, outcome_status, notes)."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT signal_id, outcome_id, outcome_status, notes FROM outcomes_daily;"
            )
            return {
                row["signal_id"]: (
                    row["outcome_id"],
                    row["outcome_status"],
                    row["notes"],
                )
                for row in cursor.fetchall()
            }
        finally:
            if not self._is_memory:
                conn.close()

    def get_open_outcomes(
        self,
        as_of_date: Optional[date] = None,
        ticker: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> list[SignalOutcomeRecord]:
        conn = self._get_connection()
        try:
            query = "SELECT * FROM outcomes_daily WHERE outcome_status = 'OPEN'"
            params: list[str] = []
            if as_of_date is not None:
                query += " AND entry_date <= ?"
                params.append(as_of_date.isoformat())
            if ticker is not None:
                clean_t = ticker.strip().upper().removesuffix(".JK")
                query += " AND ticker = ?"
                params.append(clean_t)
            if mode is not None:
                query += " AND mode = ?"
                params.append(mode)
            query += " ORDER BY entry_date ASC, signal_date ASC;"
            cursor = conn.execute(query, params)
            return [self._row_to_outcome(row) for row in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def get_matured_outcomes(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        ticker: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> list[SignalOutcomeRecord]:
        conn = self._get_connection()
        try:
            query = "SELECT * FROM outcomes_daily WHERE outcome_status != 'OPEN'"
            params: list[str] = []
            if start_date is not None:
                query += " AND signal_date >= ?"
                params.append(start_date.isoformat())
            if end_date is not None:
                query += " AND signal_date <= ?"
                params.append(end_date.isoformat())
            if ticker is not None:
                clean_t = ticker.strip().upper().removesuffix(".JK")
                query += " AND ticker = ?"
                params.append(clean_t)
            if mode is not None:
                query += " AND mode = ?"
                params.append(mode)
            query += " ORDER BY signal_date ASC, ticker ASC;"
            cursor = conn.execute(query, params)
            return [self._row_to_outcome(row) for row in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def save_snapshots(self, snapshots: list[SignalDailySnapshot]) -> None:
        if not snapshots:
            return
        records = [
            s if isinstance(s, SignalDailySnapshot) else SignalDailySnapshot.model_validate(s)
            for s in snapshots
        ]
        conn = self._get_connection()
        try:
            with conn:
                for s in records:
                    conn.execute(
                        """
                        INSERT INTO signal_snapshots_daily (
                            snapshot_id, signal_id, snapshot_date, holding_day,
                            close_price, return_from_entry, high_price, low_price,
                            mfe_so_far, mae_so_far
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(signal_id, snapshot_date) DO UPDATE SET
                            holding_day = excluded.holding_day,
                            close_price = excluded.close_price,
                            return_from_entry = excluded.return_from_entry,
                            high_price = excluded.high_price,
                            low_price = excluded.low_price,
                            mfe_so_far = excluded.mfe_so_far,
                            mae_so_far = excluded.mae_so_far;
                        """,
                        (
                            s.snapshot_id,
                            s.signal_id,
                            s.snapshot_date.isoformat(),
                            s.holding_day,
                            s.close_price,
                            s.return_from_entry,
                            s.high_price,
                            s.low_price,
                            s.mfe_so_far,
                            s.mae_so_far,
                        ),
                    )
        finally:
            if not self._is_memory:
                conn.close()

    def get_snapshots_by_signal_id(self, signal_id: str) -> list[SignalDailySnapshot]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM signal_snapshots_daily
                WHERE signal_id = ?
                ORDER BY holding_day ASC, snapshot_date ASC;
                """,
                (signal_id.strip(),),
            )
            return [self._row_to_snapshot(row) for row in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()
