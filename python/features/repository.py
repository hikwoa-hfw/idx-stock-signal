import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from python.common.types import FeatureRecord
from python.config.settings import settings


class FeatureRepository:
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
                    CREATE TABLE IF NOT EXISTS features_daily (
                        ticker TEXT NOT NULL,
                        date TEXT NOT NULL,
                        feature_version TEXT NOT NULL,
                        return_1d REAL,
                        return_3d REAL,
                        return_5d REAL,
                        return_10d REAL,
                        return_20d REAL,
                        ema20 REAL,
                        ema50 REAL,
                        ema200 REAL,
                        close_vs_ema20 REAL,
                        close_vs_ema50 REAL,
                        ema20_vs_ema50 REAL,
                        ema50_vs_ema200 REAL,
                        rsi14 REAL,
                        rsi_change_5d REAL,
                        atr14 REAL,
                        atr_pct REAL,
                        realized_vol_5d REAL,
                        realized_vol_20d REAL,
                        daily_range_pct REAL,
                        volume_ratio_5d REAL,
                        volume_ratio_20d REAL,
                        value_ratio_20d REAL,
                        rel_strength_ihsg_20d REAL,
                        rel_strength_sector_20d REAL,
                        ihsg_return_5d REAL,
                        ihsg_return_20d REAL,
                        ihsg_vs_ema20 REAL,
                        ihsg_vs_ema50 REAL,
                        market_breadth REAL,
                        market_volatility REAL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (ticker, date, feature_version)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_features_ticker_date "
                    "ON features_daily(ticker, date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_features_version "
                    "ON features_daily(feature_version);"
                )
        finally:
            if not self._is_memory:
                conn.close()

    def save_features(self, records: list[FeatureRecord]) -> int:
        if not records:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                r.ticker.strip().upper().removesuffix(".JK"),
                str(r.date),
                r.feature_version,
                r.return_1d,
                r.return_3d,
                r.return_5d,
                r.return_10d,
                r.return_20d,
                r.ema20,
                r.ema50,
                r.ema200,
                r.close_vs_ema20,
                r.close_vs_ema50,
                r.ema20_vs_ema50,
                r.ema50_vs_ema200,
                r.rsi14,
                r.rsi_change_5d,
                r.atr14,
                r.atr_pct,
                r.realized_vol_5d,
                r.realized_vol_20d,
                r.daily_range_pct,
                r.volume_ratio_5d,
                r.volume_ratio_20d,
                r.value_ratio_20d,
                r.rel_strength_ihsg_20d,
                r.rel_strength_sector_20d,
                r.ihsg_return_5d,
                r.ihsg_return_20d,
                r.ihsg_vs_ema20,
                r.ihsg_vs_ema50,
                r.market_breadth,
                r.market_volatility,
                now_iso,
            )
            for r in records
        ]

        query = """
            INSERT INTO features_daily (
                ticker, date, feature_version,
                return_1d, return_3d, return_5d, return_10d, return_20d,
                ema20, ema50, ema200,
                close_vs_ema20, close_vs_ema50, ema20_vs_ema50, ema50_vs_ema200,
                rsi14, rsi_change_5d,
                atr14, atr_pct, realized_vol_5d, realized_vol_20d, daily_range_pct,
                volume_ratio_5d, volume_ratio_20d, value_ratio_20d,
                rel_strength_ihsg_20d, rel_strength_sector_20d,
                ihsg_return_5d, ihsg_return_20d, ihsg_vs_ema20, ihsg_vs_ema50,
                market_breadth, market_volatility,
                created_at
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?
            )
            ON CONFLICT(ticker, date, feature_version) DO UPDATE SET
                return_1d = excluded.return_1d,
                return_3d = excluded.return_3d,
                return_5d = excluded.return_5d,
                return_10d = excluded.return_10d,
                return_20d = excluded.return_20d,
                ema20 = excluded.ema20,
                ema50 = excluded.ema50,
                ema200 = excluded.ema200,
                close_vs_ema20 = excluded.close_vs_ema20,
                close_vs_ema50 = excluded.close_vs_ema50,
                ema20_vs_ema50 = excluded.ema20_vs_ema50,
                ema50_vs_ema200 = excluded.ema50_vs_ema200,
                rsi14 = excluded.rsi14,
                rsi_change_5d = excluded.rsi_change_5d,
                atr14 = excluded.atr14,
                atr_pct = excluded.atr_pct,
                realized_vol_5d = excluded.realized_vol_5d,
                realized_vol_20d = excluded.realized_vol_20d,
                daily_range_pct = excluded.daily_range_pct,
                volume_ratio_5d = excluded.volume_ratio_5d,
                volume_ratio_20d = excluded.volume_ratio_20d,
                value_ratio_20d = excluded.value_ratio_20d,
                rel_strength_ihsg_20d = excluded.rel_strength_ihsg_20d,
                rel_strength_sector_20d = excluded.rel_strength_sector_20d,
                ihsg_return_5d = excluded.ihsg_return_5d,
                ihsg_return_20d = excluded.ihsg_return_20d,
                ihsg_vs_ema20 = excluded.ihsg_vs_ema20,
                ihsg_vs_ema50 = excluded.ihsg_vs_ema50,
                market_breadth = excluded.market_breadth,
                market_volatility = excluded.market_volatility,
                created_at = excluded.created_at;
        """

        conn = self._get_connection()
        try:
            with conn:
                conn.executemany(query, rows)
            return len(rows)
        finally:
            if not self._is_memory:
                conn.close()

    def _row_to_record(self, r: sqlite3.Row) -> FeatureRecord:
        return FeatureRecord(
            ticker=r["ticker"],
            date=datetime.strptime(r["date"], "%Y-%m-%d").date(),
            feature_version=r["feature_version"],
            return_1d=r["return_1d"],
            return_3d=r["return_3d"],
            return_5d=r["return_5d"],
            return_10d=r["return_10d"],
            return_20d=r["return_20d"],
            ema20=r["ema20"],
            ema50=r["ema50"],
            ema200=r["ema200"],
            close_vs_ema20=r["close_vs_ema20"],
            close_vs_ema50=r["close_vs_ema50"],
            ema20_vs_ema50=r["ema20_vs_ema50"],
            ema50_vs_ema200=r["ema50_vs_ema200"],
            rsi14=r["rsi14"],
            rsi_change_5d=r["rsi_change_5d"],
            atr14=r["atr14"],
            atr_pct=r["atr_pct"],
            realized_vol_5d=r["realized_vol_5d"],
            realized_vol_20d=r["realized_vol_20d"],
            daily_range_pct=r["daily_range_pct"],
            volume_ratio_5d=r["volume_ratio_5d"],
            volume_ratio_20d=r["volume_ratio_20d"],
            value_ratio_20d=r["value_ratio_20d"],
            rel_strength_ihsg_20d=r["rel_strength_ihsg_20d"],
            rel_strength_sector_20d=r["rel_strength_sector_20d"],
            ihsg_return_5d=r["ihsg_return_5d"],
            ihsg_return_20d=r["ihsg_return_20d"],
            ihsg_vs_ema20=r["ihsg_vs_ema20"],
            ihsg_vs_ema50=r["ihsg_vs_ema50"],
            market_breadth=r["market_breadth"],
            market_volatility=r["market_volatility"],
        )

    def get_features(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        feature_version: Optional[str] = None,
    ) -> list[FeatureRecord]:
        clean = ticker.strip().upper().removesuffix(".JK")
        query = "SELECT * FROM features_daily WHERE (ticker = ? OR ticker = ?)"
        params: list[str] = [clean, f"{clean}.JK"]

        if start_date is not None:
            query += " AND date >= ?"
            params.append(str(start_date))
        if end_date is not None:
            query += " AND date <= ?"
            params.append(str(end_date))
        if feature_version is not None:
            query += " AND feature_version = ?"
            params.append(feature_version)

        query += " ORDER BY date ASC"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def get_feature_matrix(
        self,
        tickers: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        feature_version: Optional[str] = None,
    ) -> list[FeatureRecord]:
        query = "SELECT * FROM features_daily WHERE 1=1"
        params: list[str] = []

        if tickers:
            placeholders = []
            for t in tickers:
                c = t.strip().upper().removesuffix(".JK")
                placeholders.extend(["?", "?"])
                params.extend([c, f"{c}.JK"])
            query += f" AND ticker IN ({','.join(placeholders)})"

        if start_date is not None:
            query += " AND date >= ?"
            params.append(str(start_date))
        if end_date is not None:
            query += " AND date <= ?"
            params.append(str(end_date))
        if feature_version is not None:
            query += " AND feature_version = ?"
            params.append(feature_version)

        query += " ORDER BY ticker ASC, date ASC"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def count_features(
        self,
        ticker: Optional[str] = None,
        feature_version: Optional[str] = None,
    ) -> int:
        query = "SELECT COUNT(*) as cnt FROM features_daily WHERE 1=1"
        params: list[str] = []
        if ticker:
            clean = ticker.strip().upper().removesuffix(".JK")
            query += " AND (ticker = ? OR ticker = ?)"
            params.extend([clean, f"{clean}.JK"])
        if feature_version:
            query += " AND feature_version = ?"
            params.append(feature_version)

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            if not self._is_memory:
                conn.close()

    def delete_features(
        self,
        ticker: Optional[str] = None,
        feature_version: Optional[str] = None,
    ) -> int:
        query = "DELETE FROM features_daily WHERE 1=1"
        params: list[str] = []
        if ticker:
            clean = ticker.strip().upper().removesuffix(".JK")
            query += " AND (ticker = ? OR ticker = ?)"
            params.extend([clean, f"{clean}.JK"])
        if feature_version:
            query += " AND feature_version = ?"
            params.append(feature_version)

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(query, params)
                return cursor.rowcount
        finally:
            if not self._is_memory:
                conn.close()

    def get_latest_date(self, ticker: str, feature_version: Optional[str] = None) -> Optional[date]:
        clean = ticker.strip().upper().removesuffix(".JK")
        query = "SELECT MAX(date) as latest FROM features_daily WHERE (ticker = ? OR ticker = ?)"
        params: list[str] = [clean, f"{clean}.JK"]
        if feature_version:
            query += " AND feature_version = ?"
            params.append(feature_version)

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            if row and row["latest"]:
                return datetime.strptime(row["latest"], "%Y-%m-%d").date()
            return None
        finally:
            if not self._is_memory:
                conn.close()

    def get_universe(self, feature_version: Optional[str] = None) -> list[str]:
        query = "SELECT DISTINCT ticker FROM features_daily"
        params: list[str] = []
        if feature_version:
            query += " WHERE feature_version = ?"
            params.append(feature_version)
        query += " ORDER BY ticker ASC"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [r["ticker"] for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
