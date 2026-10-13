import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from python.common.types import SignalRecord
from python.config.settings import settings


class SignalRepository:
    """SQLite repository for immutable daily signal records.

    Once written, signal records are immutable and must never be updated.
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
                    CREATE TABLE IF NOT EXISTS signals_daily (
                        signal_id TEXT PRIMARY KEY,
                        ticker TEXT NOT NULL,
                        signal_date TEXT NOT NULL,
                        signal TEXT NOT NULL,
                        entry_low REAL NOT NULL,
                        entry_high REAL NOT NULL,
                        tp_price REAL NOT NULL,
                        sl_price REAL NOT NULL,
                        max_holding_days INTEGER NOT NULL,
                        predicted_probability REAL NOT NULL,
                        expected_return REAL,
                        score REAL NOT NULL,
                        model_version TEXT NOT NULL,
                        feature_version TEXT NOT NULL,
                        signal_config_version TEXT NOT NULL,
                        feature_snapshot TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE (ticker, signal_date, model_version)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_signals_date_score "
                    "ON signals_daily(signal_date, score DESC);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_signals_ticker_date "
                    "ON signals_daily(ticker, signal_date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_signals_model_version "
                    "ON signals_daily(model_version);"
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_signals_daily_prevent_update
                    BEFORE UPDATE ON signals_daily
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Historical signal records in signals_daily are immutable.'
                        );
                    END;
                    """
                )
        finally:
            if not self._is_memory:
                conn.close()

    def exists(self, ticker: str, signal_date: date, model_version: str) -> bool:
        clean = ticker.strip().upper().removesuffix(".JK")
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT 1 FROM signals_daily
                WHERE (ticker = ? OR ticker = ?)
                  AND signal_date = ?
                  AND model_version = ?
                LIMIT 1;
                """,
                (clean, f"{clean}.JK", str(signal_date), model_version),
            )
            return cursor.fetchone() is not None
        finally:
            if not self._is_memory:
                conn.close()

    def save_signals(self, records: list[SignalRecord], ignore_existing: bool = False) -> int:
        """Persist signals to SQLite.

        Signals are strictly immutable. If ignore_existing is False and a duplicate exists,
        sqlite3.IntegrityError will be raised. If ignore_existing is True, duplicates are
        skipped without updating existing records.
        """
        if not records:
            return 0

        verb = "INSERT OR IGNORE INTO" if ignore_existing else "INSERT INTO"
        query = f"""
            {verb} signals_daily (
                signal_id, ticker, signal_date, signal,
                entry_low, entry_high, tp_price, sl_price,
                max_holding_days, predicted_probability, expected_return,
                score, model_version, feature_version, signal_config_version,
                feature_snapshot, created_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?
            );
        """

        rows = [
            (
                r.signal_id,
                r.ticker,
                str(r.signal_date),
                r.signal,
                r.entry_low,
                r.entry_high,
                r.tp_price,
                r.sl_price,
                r.max_holding_days,
                r.predicted_probability,
                r.expected_return,
                r.score,
                r.model_version,
                r.feature_version,
                r.signal_config_version,
                json.dumps(r.feature_snapshot),
                r.created_at.isoformat(),
            )
            for r in records
        ]

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.executemany(query, rows)
                return cursor.rowcount
        finally:
            if not self._is_memory:
                conn.close()

    def _row_to_record(self, r: sqlite3.Row) -> SignalRecord:
        snapshot_raw = r["feature_snapshot"]
        snapshot = json.loads(snapshot_raw) if snapshot_raw else {}
        return SignalRecord(
            signal_id=r["signal_id"],
            ticker=r["ticker"],
            signal_date=datetime.strptime(r["signal_date"], "%Y-%m-%d").date(),
            signal=r["signal"],
            entry_low=float(r["entry_low"]),
            entry_high=float(r["entry_high"]),
            tp_price=float(r["tp_price"]),
            sl_price=float(r["sl_price"]),
            max_holding_days=int(r["max_holding_days"]),
            predicted_probability=float(r["predicted_probability"]),
            expected_return=float(r["expected_return"])
            if r["expected_return"] is not None
            else None,
            score=float(r["score"]),
            model_version=r["model_version"],
            feature_version=r["feature_version"],
            signal_config_version=r["signal_config_version"],
            feature_snapshot=snapshot,
            created_at=datetime.fromisoformat(r["created_at"]),
        )

    def get_signal_by_id(self, signal_id: str) -> Optional[SignalRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM signals_daily WHERE signal_id = ? LIMIT 1;",
                (signal_id,),
            )
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            if not self._is_memory:
                conn.close()

    def get_signals_by_date(
        self, signal_date: date, limit: Optional[int] = None
    ) -> list[SignalRecord]:
        return self.get_signals(signal_date=signal_date, limit=limit)

    def get_signals(
        self,
        signal_date: Optional[date] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        ticker: Optional[str] = None,
        model_version: Optional[str] = None,
        min_score: Optional[float] = None,
        min_probability: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[SignalRecord]:
        query = "SELECT * FROM signals_daily WHERE 1=1"
        params: list[str] = []

        if signal_date is not None:
            query += " AND signal_date = ?"
            params.append(str(signal_date))
        else:
            if start_date is not None:
                query += " AND signal_date >= ?"
                params.append(str(start_date))
            if end_date is not None:
                query += " AND signal_date <= ?"
                params.append(str(end_date))

        if ticker is not None:
            clean = ticker.strip().upper().removesuffix(".JK")
            query += " AND (ticker = ? OR ticker = ?)"
            params.extend([clean, f"{clean}.JK"])

        if model_version is not None:
            query += " AND model_version = ?"
            params.append(model_version)

        if min_score is not None:
            query += " AND score >= ?"
            params.append(str(min_score))

        if min_probability is not None:
            query += " AND predicted_probability >= ?"
            params.append(str(min_probability))

        query += " ORDER BY signal_date DESC, score DESC, ticker ASC"

        if limit is not None and limit > 0:
            query += f" LIMIT {limit}"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def count_signals(
        self,
        signal_date: Optional[date] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        ticker: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> int:
        query = "SELECT COUNT(*) as cnt FROM signals_daily WHERE 1=1"
        params: list[str] = []

        if signal_date is not None:
            query += " AND signal_date = ?"
            params.append(str(signal_date))
        else:
            if start_date is not None:
                query += " AND signal_date >= ?"
                params.append(str(start_date))
            if end_date is not None:
                query += " AND signal_date <= ?"
                params.append(str(end_date))

        if ticker is not None:
            clean = ticker.strip().upper().removesuffix(".JK")
            query += " AND (ticker = ? OR ticker = ?)"
            params.extend([clean, f"{clean}.JK"])

        if model_version is not None:
            query += " AND model_version = ?"
            params.append(model_version)

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            if not self._is_memory:
                conn.close()

    def get_distinct_dates(self) -> list[date]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT signal_date FROM signals_daily ORDER BY signal_date ASC;"
            )
            rows = cursor.fetchall()
            return [datetime.strptime(r["signal_date"], "%Y-%m-%d").date() for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def delete_signals(
        self,
        signal_date: Optional[date] = None,
        ticker: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> int:
        """Utility for test isolation and data management."""
        query = "DELETE FROM signals_daily WHERE 1=1"
        params: list[str] = []

        if signal_date is not None:
            query += " AND signal_date = ?"
            params.append(str(signal_date))

        if ticker is not None:
            clean = ticker.strip().upper().removesuffix(".JK")
            query += " AND (ticker = ? OR ticker = ?)"
            params.extend([clean, f"{clean}.JK"])

        if model_version is not None:
            query += " AND model_version = ?"
            params.append(model_version)

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(query, params)
                return cursor.rowcount
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
