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
                        entry_date TEXT,
                        entry_price REAL,
                        entry_status TEXT NOT NULL DEFAULT 'FILLED',
                        outcome_status TEXT NOT NULL,
                        realized_return REAL,
                        holding_days INTEGER NOT NULL DEFAULT 0,
                        mfe REAL,
                        mae REAL,
                        mfe_price REAL,
                        mae_price REAL,
                        time_to_peak INTEGER,
                        time_to_tp INTEGER,
                        time_to_sl INTEGER,
                        net_return REAL,
                        gross_return REAL,
                        return_after_fees REAL,
                        return_after_fees_and_slippage REAL,
                        exit_date TEXT,
                        exit_price REAL,
                        exit_reason TEXT,
                        resolved_at TEXT,
                        notes TEXT,
                        mode TEXT,
                        trigger_price REAL,
                        observation_end_date TEXT,
                        full_horizon_mfe REAL,
                        full_horizon_mae REAL,
                        full_horizon_mfe_price REAL,
                        full_horizon_mae_price REAL,
                        full_horizon_time_to_peak INTEGER,
                        horizon_end_date TEXT,
                        horizon_end_price REAL,
                        horizon_end_return REAL,
                        is_full_horizon_complete INTEGER DEFAULT 0,
                        UNIQUE (signal_id)
                    );
                    """
                )
                cols_info = {
                    row[1]: row
                    for row in conn.execute("PRAGMA table_info(outcomes_daily);").fetchall()
                }
                # Check if legacy table has NOT NULL on entry_price, entry_date, mfe, or mae
                needs_migration = any(
                    col in cols_info and cols_info[col][3] == 1
                    for col in ("entry_date", "entry_price", "mfe", "mae")
                )
                if needs_migration:
                    conn.execute(
                        """
                        CREATE TABLE outcomes_daily_migration (
                            outcome_id TEXT PRIMARY KEY,
                            signal_id TEXT NOT NULL,
                            ticker TEXT NOT NULL,
                            signal_date TEXT NOT NULL,
                            entry_date TEXT,
                            entry_price REAL,
                            entry_status TEXT NOT NULL DEFAULT 'FILLED',
                            outcome_status TEXT NOT NULL,
                            realized_return REAL,
                            holding_days INTEGER NOT NULL DEFAULT 0,
                            mfe REAL,
                            mae REAL,
                            mfe_price REAL,
                            mae_price REAL,
                            time_to_peak INTEGER,
                            time_to_tp INTEGER,
                            time_to_sl INTEGER,
                            net_return REAL,
                            gross_return REAL,
                            return_after_fees REAL,
                            return_after_fees_and_slippage REAL,
                            exit_date TEXT,
                            exit_price REAL,
                            exit_reason TEXT,
                            resolved_at TEXT,
                            notes TEXT,
                            mode TEXT,
                            trigger_price REAL,
                            observation_end_date TEXT,
                            full_horizon_mfe REAL,
                            full_horizon_mae REAL,
                            full_horizon_mfe_price REAL,
                            full_horizon_mae_price REAL,
                            full_horizon_time_to_peak INTEGER,
                            horizon_end_date TEXT,
                            horizon_end_price REAL,
                            horizon_end_return REAL,
                            is_full_horizon_complete INTEGER DEFAULT 0,
                            UNIQUE (signal_id)
                        );
                        """
                    )
                    common_cols = [
                        c
                        for c in cols_info.keys()
                        if c
                        in {
                            "outcome_id",
                            "signal_id",
                            "ticker",
                            "signal_date",
                            "entry_date",
                            "entry_price",
                            "entry_status",
                            "outcome_status",
                            "realized_return",
                            "holding_days",
                            "mfe",
                            "mae",
                            "mfe_price",
                            "mae_price",
                            "time_to_peak",
                            "time_to_tp",
                            "time_to_sl",
                            "net_return",
                            "exit_date",
                            "exit_price",
                            "exit_reason",
                            "resolved_at",
                            "notes",
                            "mode",
                        }
                    ]
                    cols_str = ", ".join(common_cols)
                    conn.execute(
                        f"INSERT INTO outcomes_daily_migration ({cols_str}) "
                        f"SELECT {cols_str} FROM outcomes_daily;"
                    )
                    conn.execute("DROP TABLE outcomes_daily;")
                    conn.execute("ALTER TABLE outcomes_daily_migration RENAME TO outcomes_daily;")
                    cols_info = {
                        row[1]: row
                        for row in conn.execute("PRAGMA table_info(outcomes_daily);").fetchall()
                    }

                new_cols = [
                    ("mode", "TEXT"),
                    ("mfe_price", "REAL DEFAULT 0.0"),
                    ("mae_price", "REAL DEFAULT 0.0"),
                    ("time_to_peak", "INTEGER"),
                    ("time_to_tp", "INTEGER"),
                    ("time_to_sl", "INTEGER"),
                    ("net_return", "REAL"),
                    ("gross_return", "REAL"),
                    ("return_after_fees", "REAL"),
                    ("return_after_fees_and_slippage", "REAL"),
                    ("entry_status", "TEXT DEFAULT 'FILLED'"),
                    ("trigger_price", "REAL"),
                    ("observation_end_date", "TEXT"),
                    ("full_horizon_mfe", "REAL"),
                    ("full_horizon_mae", "REAL"),
                    ("full_horizon_mfe_price", "REAL"),
                    ("full_horizon_mae_price", "REAL"),
                    ("full_horizon_time_to_peak", "INTEGER"),
                    ("horizon_end_date", "TEXT"),
                    ("horizon_end_price", "REAL"),
                    ("horizon_end_return", "REAL"),
                    ("is_full_horizon_complete", "INTEGER DEFAULT 0"),
                ]
                for c_name, c_type in new_cols:
                    if c_name not in cols_info:
                        conn.execute(f"ALTER TABLE outcomes_daily ADD COLUMN {c_name} {c_type};")

                conn.execute(
                    "UPDATE outcomes_daily SET entry_status = 'UNFILLED' "
                    "WHERE outcome_status IN ('UNFILLED_EXPIRED', 'INVALIDATED_GAP') "
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
        keys = set(row.keys())
        mode_val = row["mode"] if "mode" in keys else None

        def _get_float(k: str) -> Optional[float]:
            return float(row[k]) if k in keys and row[k] is not None else None

        def _get_int(k: str) -> Optional[int]:
            return int(row[k]) if k in keys and row[k] is not None else None

        def _get_date(k: str) -> Optional[date]:
            return date.fromisoformat(row[k]) if k in keys and row[k] else None

        entry_date_val = _get_date("entry_date")
        entry_price_val = _get_float("entry_price")
        obs_end_date_val = _get_date("observation_end_date")
        horiz_end_date_val = _get_date("horizon_end_date")
        is_fhc = (
            bool(row["is_full_horizon_complete"])
            if "is_full_horizon_complete" in keys and row["is_full_horizon_complete"] is not None
            else False
        )

        entry_status_val = (
            row["entry_status"]
            if "entry_status" in keys and row["entry_status"] is not None
            else (
                "UNFILLED"
                if row["outcome_status"] in ("UNFILLED_EXPIRED", "INVALIDATED_GAP")
                else "FILLED"
            )
        )

        return SignalOutcomeRecord(
            outcome_id=row["outcome_id"],
            signal_id=row["signal_id"],
            ticker=row["ticker"],
            signal_date=date.fromisoformat(row["signal_date"]),
            entry_date=entry_date_val,
            entry_price=entry_price_val,
            entry_status=entry_status_val,
            outcome_status=row["outcome_status"],
            realized_return=_get_float("realized_return"),
            holding_days=int(row["holding_days"]),
            mfe=_get_float("mfe"),
            mae=_get_float("mae"),
            mfe_price=_get_float("mfe_price"),
            mae_price=_get_float("mae_price"),
            time_to_peak=_get_int("time_to_peak"),
            time_to_tp=_get_int("time_to_tp"),
            time_to_sl=_get_int("time_to_sl"),
            net_return=_get_float("net_return"),
            gross_return=_get_float("gross_return"),
            return_after_fees=_get_float("return_after_fees"),
            return_after_fees_and_slippage=_get_float("return_after_fees_and_slippage"),
            exit_date=exit_date_val,
            exit_price=_get_float("exit_price"),
            exit_reason=row["exit_reason"],
            resolved_at=resolved_at_val,
            notes=row["notes"],
            mode=mode_val,
            trigger_price=_get_float("trigger_price"),
            observation_end_date=obs_end_date_val,
            full_horizon_mfe=_get_float("full_horizon_mfe"),
            full_horizon_mae=_get_float("full_horizon_mae"),
            full_horizon_mfe_price=_get_float("full_horizon_mfe_price"),
            full_horizon_mae_price=_get_float("full_horizon_mae_price"),
            full_horizon_time_to_peak=_get_int("full_horizon_time_to_peak"),
            horizon_end_date=horiz_end_date_val,
            horizon_end_price=_get_float("horizon_end_price"),
            horizon_end_return=_get_float("horizon_end_return"),
            is_full_horizon_complete=is_fhc,
        )

    @staticmethod
    def _outcome_to_db_params(rec: SignalOutcomeRecord) -> tuple:
        return (
            rec.outcome_id,
            rec.signal_id,
            rec.ticker,
            rec.signal_date.isoformat(),
            rec.entry_date.isoformat() if rec.entry_date else None,
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
            rec.gross_return,
            rec.return_after_fees,
            rec.return_after_fees_and_slippage,
            rec.exit_date.isoformat() if rec.exit_date else None,
            rec.exit_price,
            rec.exit_reason,
            rec.resolved_at.isoformat() if rec.resolved_at else None,
            rec.notes,
            rec.mode_id,
            rec.trigger_price,
            rec.observation_end_date.isoformat() if rec.observation_end_date else None,
            rec.full_horizon_mfe,
            rec.full_horizon_mae,
            rec.full_horizon_mfe_price,
            rec.full_horizon_mae_price,
            rec.full_horizon_time_to_peak,
            rec.horizon_end_date.isoformat() if rec.horizon_end_date else None,
            rec.horizon_end_price,
            rec.horizon_end_return,
            1 if rec.is_full_horizon_complete else 0,
        )

    _UPSERT_OUTCOME_SQL = """
        INSERT INTO outcomes_daily (
            outcome_id, signal_id, ticker, signal_date, entry_date,
            entry_price, entry_status, outcome_status, realized_return,
            holding_days, mfe, mae, mfe_price, mae_price, time_to_peak,
            time_to_tp, time_to_sl, net_return, gross_return, return_after_fees,
            return_after_fees_and_slippage, exit_date, exit_price,
            exit_reason, resolved_at, notes, mode, trigger_price,
            observation_end_date, full_horizon_mfe, full_horizon_mae,
            full_horizon_mfe_price, full_horizon_mae_price, full_horizon_time_to_peak,
            horizon_end_date, horizon_end_price, horizon_end_return,
            is_full_horizon_complete
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?
        )
        ON CONFLICT(signal_id) DO UPDATE SET
            entry_date = excluded.entry_date,
            entry_price = excluded.entry_price,
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
            gross_return = excluded.gross_return,
            return_after_fees = excluded.return_after_fees,
            return_after_fees_and_slippage = excluded.return_after_fees_and_slippage,
            exit_date = excluded.exit_date,
            exit_price = excluded.exit_price,
            exit_reason = excluded.exit_reason,
            resolved_at = COALESCE(outcomes_daily.resolved_at, excluded.resolved_at),
            notes = COALESCE(excluded.notes, outcomes_daily.notes),
            mode = COALESCE(outcomes_daily.mode, excluded.mode),
            trigger_price = excluded.trigger_price,
            observation_end_date = excluded.observation_end_date,
            full_horizon_mfe = excluded.full_horizon_mfe,
            full_horizon_mae = excluded.full_horizon_mae,
            full_horizon_mfe_price = excluded.full_horizon_mfe_price,
            full_horizon_mae_price = excluded.full_horizon_mae_price,
            full_horizon_time_to_peak = excluded.full_horizon_time_to_peak,
            horizon_end_date = excluded.horizon_end_date,
            horizon_end_price = excluded.horizon_end_price,
            horizon_end_return = excluded.horizon_end_return,
            is_full_horizon_complete = excluded.is_full_horizon_complete;
    """

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

    def delete_snapshots_by_signal_id(self, signal_id: str) -> None:
        """Delete all daily snapshots associated with a signal ID."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM signal_snapshots_daily WHERE signal_id = ?;",
                    (signal_id.strip(),),
                )
        finally:
            if not self._is_memory:
                conn.close()

    def save_outcome(self, outcome: Union[SignalOutcomeRecord, dict]) -> None:
        rec = (
            outcome
            if isinstance(outcome, SignalOutcomeRecord)
            else SignalOutcomeRecord.model_validate(outcome)
        )
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(self._UPSERT_OUTCOME_SQL, self._outcome_to_db_params(rec))
                if (
                    rec.outcome_status in ("UNFILLED_EXPIRED", "INVALIDATED_GAP")
                    or rec.entry_status == "UNFILLED"
                ):
                    conn.execute(
                        "DELETE FROM signal_snapshots_daily WHERE signal_id = ?;",
                        (rec.signal_id,),
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
                    conn.execute(self._UPSERT_OUTCOME_SQL, self._outcome_to_db_params(rec))
                    if (
                        rec.outcome_status in ("UNFILLED_EXPIRED", "INVALIDATED_GAP")
                        or rec.entry_status == "UNFILLED"
                    ):
                        conn.execute(
                            "DELETE FROM signal_snapshots_daily WHERE signal_id = ?;",
                            (rec.signal_id,),
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
