import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from python.common.types import LabelRecord, classify_price_mode
from python.config.settings import settings


class LabelRepository:
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
                    CREATE TABLE IF NOT EXISTS labels_daily (
                        ticker TEXT NOT NULL,
                        date TEXT NOT NULL,
                        label_version TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        tp_price REAL NOT NULL,
                        sl_price REAL NOT NULL,
                        tp_pct REAL NOT NULL,
                        sl_pct REAL NOT NULL,
                        max_holding_days INTEGER NOT NULL,
                        outcome TEXT NOT NULL,
                        binary_target INTEGER NOT NULL,
                        mfe REAL NOT NULL,
                        mae REAL NOT NULL,
                        holding_days INTEGER NOT NULL,
                        realized_return REAL NOT NULL,
                        exit_date TEXT,
                        exit_price REAL,
                        ambiguity_policy TEXT NOT NULL,
                        mode TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (ticker, date, label_version)
                    );
                    """
                )
                cols = [
                    row[1] for row in conn.execute("PRAGMA table_info(labels_daily);").fetchall()
                ]
                if "mode" not in cols:
                    conn.execute("ALTER TABLE labels_daily ADD COLUMN mode TEXT;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_labels_mode ON labels_daily(mode);")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_labels_ticker_date "
                    "ON labels_daily(ticker, date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_labels_version ON labels_daily(label_version);"
                )
        finally:
            if not self._is_memory:
                conn.close()

    def save_labels(self, records: list[LabelRecord]) -> int:
        if not records:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                r.ticker.strip().upper().removesuffix(".JK"),
                str(r.date),
                r.label_version,
                r.entry_price,
                r.tp_price,
                r.sl_price,
                r.tp_pct,
                r.sl_pct,
                r.max_holding_days,
                r.outcome,
                r.binary_target,
                r.mfe,
                r.mae,
                r.holding_days,
                r.realized_return,
                str(r.exit_date) if r.exit_date else None,
                r.exit_price,
                r.ambiguity_policy,
                r.mode_id or classify_price_mode(r.entry_price),
                now_iso,
            )
            for r in records
        ]

        query = """
            INSERT INTO labels_daily (
                ticker, date, label_version,
                entry_price, tp_price, sl_price,
                tp_pct, sl_pct, max_holding_days,
                outcome, binary_target, mfe, mae,
                holding_days, realized_return,
                exit_date, exit_price,
                ambiguity_policy, mode, created_at
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?
            )
            ON CONFLICT(ticker, date, label_version) DO UPDATE SET
                entry_price = excluded.entry_price,
                tp_price = excluded.tp_price,
                sl_price = excluded.sl_price,
                tp_pct = excluded.tp_pct,
                sl_pct = excluded.sl_pct,
                max_holding_days = excluded.max_holding_days,
                outcome = excluded.outcome,
                binary_target = excluded.binary_target,
                mfe = excluded.mfe,
                mae = excluded.mae,
                holding_days = excluded.holding_days,
                realized_return = excluded.realized_return,
                exit_date = excluded.exit_date,
                exit_price = excluded.exit_price,
                ambiguity_policy = excluded.ambiguity_policy,
                mode = COALESCE(excluded.mode, labels_daily.mode),
                created_at = excluded.created_at;
        """

        conn = self._get_connection()
        try:
            with conn:
                conn.executemany(query, rows)
            return len(records)
        finally:
            if not self._is_memory:
                conn.close()

    def get_labels(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        label_version: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> list[LabelRecord]:
        clean_ticker = ticker.strip().upper().removesuffix(".JK")
        clauses = ["(ticker = ? OR ticker = ? || '.JK')"]
        params: list[object] = [clean_ticker, clean_ticker]

        if start_date is not None:
            clauses.append("date >= ?")
            params.append(str(start_date))
        if end_date is not None:
            clauses.append("date <= ?")
            params.append(str(end_date))
        if label_version is not None:
            clauses.append("label_version = ?")
            params.append(label_version)
        if mode is not None:
            clauses.append("mode = ?")
            params.append(mode.strip().upper())

        query = f"""
            SELECT * FROM labels_daily
            WHERE {" AND ".join(clauses)}
            ORDER BY date ASC;
        """

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def get_all_labels(
        self,
        tickers: Optional[list[str]] = None,
        label_version: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        mode: Optional[str] = None,
    ) -> list[LabelRecord]:
        clauses: list[str] = []
        params: list[object] = []

        if tickers:
            placeholders = []
            for t in tickers:
                c = t.strip().upper().removesuffix(".JK")
                placeholders.extend(["?", "?"])
                params.extend([c, f"{c}.JK"])
            clauses.append(f"ticker IN ({','.join(placeholders)})")
        if label_version is not None:
            clauses.append("label_version = ?")
            params.append(label_version)
        if start_date is not None:
            clauses.append("date >= ?")
            params.append(str(start_date))
        if end_date is not None:
            clauses.append("date <= ?")
            params.append(str(end_date))
        if mode is not None:
            clauses.append("mode = ?")
            params.append(mode.strip().upper())

        where_str = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM labels_daily
            {where_str}
            ORDER BY ticker ASC, date ASC;
        """

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def count_labels(
        self,
        ticker: Optional[str] = None,
        label_version: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if ticker:
            clean_ticker = ticker.strip().upper().removesuffix(".JK")
            clauses.append("(ticker = ? OR ticker = ? || '.JK')")
            params.extend([clean_ticker, clean_ticker])
        if label_version:
            clauses.append("label_version = ?")
            params.append(label_version)
        if mode:
            clauses.append("mode = ?")
            params.append(mode.strip().upper())

        where_str = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT COUNT(*) FROM labels_daily {where_str};"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            if not self._is_memory:
                conn.close()

    def delete_labels(
        self,
        ticker: Optional[str] = None,
        label_version: Optional[str] = None,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if ticker:
            clean_ticker = ticker.strip().upper().removesuffix(".JK")
            clauses.append("(ticker = ? OR ticker = ? || '.JK')")
            params.extend([clean_ticker, clean_ticker])
        if label_version:
            clauses.append("label_version = ?")
            params.append(label_version)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"DELETE FROM labels_daily {where_clause};"

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(query, params)
                return cursor.rowcount
        finally:
            if not self._is_memory:
                conn.close()

    def get_universe(self, label_version: Optional[str] = None) -> list[str]:
        query = "SELECT DISTINCT ticker FROM labels_daily"
        params: list[object] = []
        if label_version:
            query += " WHERE label_version = ?"
            params.append(label_version)
        query += " ORDER BY ticker ASC;"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            return [row["ticker"] for row in cursor.fetchall()]
        finally:
            if not self._is_memory:
                conn.close()

    def get_latest_date(
        self,
        ticker: Optional[str] = None,
        label_version: Optional[str] = None,
    ) -> Optional[date]:
        clauses: list[str] = []
        params: list[object] = []
        if ticker:
            clean_ticker = ticker.strip().upper().removesuffix(".JK")
            clauses.append("(ticker = ? OR ticker = ? || '.JK')")
            params.extend([clean_ticker, clean_ticker])
        if label_version:
            clauses.append("label_version = ?")
            params.append(label_version)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT MAX(date) FROM labels_daily {where_clause};"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            if row and row[0]:
                return date.fromisoformat(row[0])
            return None
        finally:
            if not self._is_memory:
                conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> LabelRecord:
        exit_d = date.fromisoformat(row["exit_date"]) if row["exit_date"] else None
        mode_val = (
            row["mode"]
            if "mode" in row.keys() and row["mode"]
            else classify_price_mode(float(row["entry_price"]))
        )
        return LabelRecord(
            ticker=row["ticker"],
            date=date.fromisoformat(row["date"]),
            label_version=row["label_version"],
            entry_price=float(row["entry_price"]),
            tp_price=float(row["tp_price"]),
            sl_price=float(row["sl_price"]),
            tp_pct=float(row["tp_pct"]),
            sl_pct=float(row["sl_pct"]),
            max_holding_days=int(row["max_holding_days"]),
            outcome=row["outcome"],
            binary_target=int(row["binary_target"]),
            mfe=float(row["mfe"]),
            mae=float(row["mae"]),
            holding_days=int(row["holding_days"]),
            realized_return=float(row["realized_return"]),
            exit_date=exit_d,
            exit_price=float(row["exit_price"]) if row["exit_price"] is not None else None,
            ambiguity_policy=row["ambiguity_policy"],
            mode=mode_val,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
