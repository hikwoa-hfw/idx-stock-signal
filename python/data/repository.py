import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from python.common.types import DailyBar, IngestionRun, IngestionTickerStatus
from python.config.settings import settings


def _is_close(a: Any, b: Any, eps: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) < eps
    except (TypeError, ValueError):
        return str(a) == str(b)


class DailyBarRepository:
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

                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_bars';"
                )
                if cur.fetchone():
                    table_info = conn.execute("PRAGMA table_info(daily_bars);").fetchall()
                    col_names = {row["name"] for row in table_info}
                    pk_cols = [
                        row["name"]
                        for row in sorted(
                            [r for r in table_info if r["pk"] > 0], key=lambda r: r["pk"]
                        )
                    ]
                    needs_migration = (
                        "interval" not in col_names
                        or "provider" not in col_names
                        or set(pk_cols) != {"ticker", "date", "interval", "provider"}
                    )
                    if needs_migration:
                        conn.execute(
                            """
                            CREATE TABLE daily_bars_migrated (
                                ticker TEXT NOT NULL,
                                date TEXT NOT NULL,
                                interval TEXT NOT NULL DEFAULT '1d',
                                open REAL NOT NULL,
                                high REAL NOT NULL,
                                low REAL NOT NULL,
                                close REAL NOT NULL,
                                volume REAL NOT NULL,
                                value REAL,
                                adj_close REAL,
                                dividends REAL DEFAULT 0.0,
                                stock_splits REAL DEFAULT 0.0,
                                provider TEXT NOT NULL DEFAULT 'unknown',
                                provider_symbol TEXT,
                                ingestion_run_id TEXT,
                                row_hash TEXT,
                                created_at TEXT NOT NULL,
                                updated_at TEXT,
                                PRIMARY KEY (ticker, date, interval, provider)
                            );
                            """
                        )
                        sel_interval = "interval" if "interval" in col_names else "'1d'"
                        sel_provider = "provider" if "provider" in col_names else "'unknown'"
                        sel_adj = "adj_close" if "adj_close" in col_names else "NULL"
                        sel_div = "dividends" if "dividends" in col_names else "0.0"
                        sel_split = "stock_splits" if "stock_splits" in col_names else "0.0"
                        sel_sym = "provider_symbol" if "provider_symbol" in col_names else "NULL"
                        sel_run = "ingestion_run_id" if "ingestion_run_id" in col_names else "NULL"
                        sel_hash = "row_hash" if "row_hash" in col_names else "NULL"
                        sel_upd = "updated_at" if "updated_at" in col_names else "NULL"
                        conn.execute(
                            f"""
                            INSERT OR IGNORE INTO daily_bars_migrated (
                                ticker, date, interval, open, high, low, close, volume, value,
                                adj_close, dividends, stock_splits, provider, provider_symbol,
                                ingestion_run_id, row_hash, created_at, updated_at
                            )
                            SELECT
                                ticker, date, {sel_interval}, open, high, low, close, volume, value,
                                {sel_adj}, {sel_div}, {sel_split}, {sel_provider}, {sel_sym},
                                {sel_run}, {sel_hash}, created_at, {sel_upd}
                            FROM daily_bars;
                            """
                        )
                        conn.execute("DROP TABLE daily_bars;")
                        conn.execute("ALTER TABLE daily_bars_migrated RENAME TO daily_bars;")
                    elif "row_hash" not in col_names:
                        conn.execute("ALTER TABLE daily_bars ADD COLUMN row_hash TEXT;")
                else:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS daily_bars (
                            ticker TEXT NOT NULL,
                            date TEXT NOT NULL,
                            interval TEXT NOT NULL DEFAULT '1d',
                            open REAL NOT NULL,
                            high REAL NOT NULL,
                            low REAL NOT NULL,
                            close REAL NOT NULL,
                            volume REAL NOT NULL,
                            value REAL,
                            adj_close REAL,
                            dividends REAL DEFAULT 0.0,
                            stock_splits REAL DEFAULT 0.0,
                            provider TEXT NOT NULL DEFAULT 'unknown',
                            provider_symbol TEXT,
                            ingestion_run_id TEXT,
                            row_hash TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT,
                            PRIMARY KEY (ticker, date, interval, provider)
                        );
                        """
                    )

                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_daily_bars_ticker ON daily_bars(ticker);"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(date);")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_daily_bars_lookup "
                    "ON daily_bars(ticker, date, interval, provider);"
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_runs (
                        id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        job_type TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        status TEXT NOT NULL,
                        tickers_requested INTEGER NOT NULL DEFAULT 0,
                        tickers_succeeded INTEGER NOT NULL DEFAULT 0,
                        tickers_partial INTEGER NOT NULL DEFAULT 0,
                        tickers_failed INTEGER NOT NULL DEFAULT 0,
                        rows_inserted INTEGER NOT NULL DEFAULT 0,
                        rows_updated INTEGER NOT NULL DEFAULT 0,
                        rows_unchanged INTEGER NOT NULL DEFAULT 0,
                        rows_rejected INTEGER NOT NULL DEFAULT 0,
                        error_summary TEXT,
                        config_version TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_ticker_status (
                        id TEXT PRIMARY KEY,
                        ingestion_run_id TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        status TEXT NOT NULL,
                        rows_received INTEGER NOT NULL DEFAULT 0,
                        rows_inserted INTEGER NOT NULL DEFAULT 0,
                        rows_updated INTEGER NOT NULL DEFAULT 0,
                        first_date_received TEXT,
                        last_date_received TEXT,
                        error_code TEXT,
                        error_message TEXT,
                        attempt_count INTEGER NOT NULL DEFAULT 1,
                        FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(id)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ticker_status_run "
                    "ON ingestion_ticker_status(ingestion_run_id);"
                )
        finally:
            if not self._is_memory:
                conn.close()

    def save_bars_detailed(
        self,
        bars: list[DailyBar],
        default_provider: str = "unknown",
        ingestion_run_id: Optional[str] = None,
    ) -> dict[str, int]:
        if not bars:
            return {"inserted": 0, "updated": 0, "unchanged": 0}

        now_iso = datetime.now(timezone.utc).isoformat()
        inserted = 0
        updated = 0
        unchanged = 0

        conn = self._get_connection()
        try:
            with conn:
                for bar in bars:
                    clean_ticker = bar.ticker.strip().upper().removesuffix(".JK")
                    bar_interval = getattr(bar, "interval", "1d") or "1d"
                    bar_provider = getattr(bar, "provider", None) or default_provider
                    bar_prov_sym = getattr(bar, "provider_symbol", None) or f"{clean_ticker}.JK"
                    bar_run_id = getattr(bar, "ingestion_run_id", None) or ingestion_run_id
                    adj_close = getattr(bar, "adj_close", None)
                    divs = float(getattr(bar, "dividends", 0.0) or 0.0)
                    splits = float(getattr(bar, "stock_splits", 0.0) or 0.0)
                    val = float(bar.value) if bar.value is not None else None

                    bar_hash = getattr(bar, "row_hash", None) or bar.compute_row_hash()

                    cur = conn.execute(
                        """
                        SELECT open, high, low, close, volume, value,
                               adj_close, dividends, stock_splits, row_hash
                        FROM daily_bars
                        WHERE ticker = ? AND date = ? AND interval = ? AND provider = ?
                        """,
                        (clean_ticker, str(bar.date), bar_interval, bar_provider),
                    )
                    existing = cur.fetchone()
                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO daily_bars (
                                ticker, date, interval, open, high, low, close, volume, value,
                                adj_close, dividends, stock_splits, provider, provider_symbol,
                                ingestion_run_id, row_hash, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                clean_ticker,
                                str(bar.date),
                                bar_interval,
                                float(bar.open),
                                float(bar.high),
                                float(bar.low),
                                float(bar.close),
                                float(bar.volume),
                                val,
                                adj_close,
                                divs,
                                splits,
                                bar_provider,
                                bar_prov_sym,
                                bar_run_id,
                                bar_hash,
                                now_iso,
                                None,
                            ),
                        )
                        inserted += 1
                    else:
                        existing_cols = existing.keys()
                        has_db_hash = (
                            "row_hash" in existing_cols and existing["row_hash"] is not None
                        )
                        if has_db_hash and bar_hash:
                            is_same = existing["row_hash"] == bar_hash
                        else:
                            is_same = (
                                _is_close(existing["open"], bar.open)
                                and _is_close(existing["high"], bar.high)
                                and _is_close(existing["low"], bar.low)
                                and _is_close(existing["close"], bar.close)
                                and _is_close(existing["volume"], bar.volume)
                                and _is_close(existing["value"], val)
                                and _is_close(existing["adj_close"], adj_close)
                                and _is_close(existing["dividends"], divs)
                                and _is_close(existing["stock_splits"], splits)
                            )
                        if is_same:
                            unchanged += 1
                        else:
                            conn.execute(
                                """
                                UPDATE daily_bars SET
                                    open = ?, high = ?, low = ?, close = ?, volume = ?, value = ?,
                                    adj_close = ?, dividends = ?, stock_splits = ?,
                                    provider_symbol = ?, ingestion_run_id = ?,
                                    row_hash = ?, updated_at = ?
                                WHERE ticker = ? AND date = ? AND interval = ? AND provider = ?
                                """,
                                (
                                    float(bar.open),
                                    float(bar.high),
                                    float(bar.low),
                                    float(bar.close),
                                    float(bar.volume),
                                    val,
                                    adj_close,
                                    divs,
                                    splits,
                                    bar_prov_sym,
                                    bar_run_id,
                                    bar_hash,
                                    now_iso,
                                    clean_ticker,
                                    str(bar.date),
                                    bar_interval,
                                    bar_provider,
                                ),
                            )
                            updated += 1
            return {"inserted": inserted, "updated": updated, "unchanged": unchanged}
        finally:
            if not self._is_memory:
                conn.close()

    def save_bars(
        self,
        bars: list[DailyBar],
        provider: Optional[str] = None,
        ingestion_run_id: Optional[str] = None,
    ) -> int:
        if not bars:
            return 0
        self.save_bars_detailed(
            bars,
            default_provider=provider or "unknown",
            ingestion_run_id=ingestion_run_id,
        )
        return len(bars)

    def get_daily_bars(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        provider: Optional[str] = None,
    ) -> list[DailyBar]:
        clean = ticker.strip().upper().removesuffix(".JK")
        query = (
            "SELECT ticker, date, interval, open, high, low, close, volume, value, "
            "adj_close, dividends, stock_splits, provider, provider_symbol, "
            "ingestion_run_id, row_hash "
            "FROM daily_bars WHERE (ticker = ? OR ticker = ?)"
        )
        params: list[Any] = [clean, f"{clean}.JK"]

        if provider is not None:
            query += " AND provider = ?"
            params.append(provider)
        if start_date is not None:
            query += " AND date >= ?"
            params.append(str(start_date))
        if end_date is not None:
            query += " AND date <= ?"
            params.append(str(end_date))

        query += " ORDER BY date ASC"

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            bars: list[DailyBar] = []
            for r in rows:
                col_keys = r.keys()
                bars.append(
                    DailyBar(
                        ticker=r["ticker"],
                        date=datetime.strptime(r["date"][:10], "%Y-%m-%d").date(),
                        open=float(r["open"]),
                        high=float(r["high"]),
                        low=float(r["low"]),
                        close=float(r["close"]),
                        volume=float(r["volume"]),
                        value=float(r["value"]) if r["value"] is not None else None,
                        adj_close=float(r["adj_close"]) if r["adj_close"] is not None else None,
                        dividends=float(r["dividends"]) if r["dividends"] is not None else 0.0,
                        stock_splits=float(r["stock_splits"])
                        if r["stock_splits"] is not None
                        else 0.0,
                        provider=r["provider"] if "provider" in col_keys else None,
                        provider_symbol=r["provider_symbol"]
                        if "provider_symbol" in col_keys
                        else None,
                        ingestion_run_id=r["ingestion_run_id"]
                        if "ingestion_run_id" in col_keys
                        else None,
                        interval=r["interval"] if "interval" in col_keys else "1d",
                        row_hash=r["row_hash"] if "row_hash" in col_keys else None,
                    )
                )
            return bars
        finally:
            if not self._is_memory:
                conn.close()

    def get_latest_date(self, ticker: str, provider: Optional[str] = None) -> Optional[date]:
        clean = ticker.strip().upper().removesuffix(".JK")
        query = "SELECT MAX(date) as latest FROM daily_bars WHERE (ticker = ? OR ticker = ?)"
        params: list[Any] = [clean, f"{clean}.JK"]
        if provider is not None:
            query += " AND provider = ?"
            params.append(provider)

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

    def get_universe(self) -> list[str]:
        query = "SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker ASC"
        conn = self._get_connection()
        try:
            cursor = conn.execute(query)
            rows = cursor.fetchall()
            tickers: set[str] = set()
            for r in rows:
                tickers.add(r["ticker"].strip().upper().removesuffix(".JK"))
            return sorted(tickers)
        finally:
            if not self._is_memory:
                conn.close()

    def get_sector_data(self) -> dict[str, str]:
        from python.data.provider import DEFAULT_SECTOR_MAP

        return dict(DEFAULT_SECTOR_MAP)

    def count_bars(self, ticker: Optional[str] = None, provider: Optional[str] = None) -> int:
        if ticker:
            clean = ticker.strip().upper().removesuffix(".JK")
            query = "SELECT COUNT(*) as cnt FROM daily_bars WHERE (ticker = ? OR ticker = ?)"
            params: list[Any] = [clean, f"{clean}.JK"]
        else:
            query = "SELECT COUNT(*) as cnt FROM daily_bars"
            params = []

        if provider is not None:
            query += " AND provider = ?" if ("WHERE" in query) else " WHERE provider = ?"
            params.append(provider)

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            if not self._is_memory:
                conn.close()

    def delete_bars(self, ticker: Optional[str] = None, provider: Optional[str] = None) -> int:
        if ticker:
            clean = ticker.strip().upper().removesuffix(".JK")
            query = "DELETE FROM daily_bars WHERE (ticker = ? OR ticker = ?)"
            params: list[Any] = [clean, f"{clean}.JK"]
        else:
            query = "DELETE FROM daily_bars"
            params = []

        if provider is not None:
            query += " AND provider = ?" if ("WHERE" in query) else " WHERE provider = ?"
            params.append(provider)

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(query, params)
                return cursor.rowcount
        finally:
            if not self._is_memory:
                conn.close()

    def create_ingestion_run(self, run: IngestionRun) -> str:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ingestion_runs (
                        id, provider, job_type, started_at, finished_at, status,
                        tickers_requested, tickers_succeeded, tickers_partial, tickers_failed,
                        rows_inserted, rows_updated, rows_unchanged, rows_rejected,
                        error_summary, config_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        run.provider,
                        run.job_type,
                        run.started_at.isoformat(),
                        run.finished_at.isoformat() if run.finished_at else None,
                        run.status,
                        run.tickers_requested,
                        run.tickers_succeeded,
                        run.tickers_partial,
                        run.tickers_failed,
                        run.rows_inserted,
                        run.rows_updated,
                        run.rows_unchanged,
                        run.rows_rejected,
                        run.error_summary,
                        run.config_version,
                    ),
                )
            return run.id
        finally:
            if not self._is_memory:
                conn.close()

    def update_ingestion_run(
        self,
        run_id: str,
        finished_at: Optional[datetime] = None,
        status: Optional[str] = None,
        tickers_succeeded: Optional[int] = None,
        tickers_partial: Optional[int] = None,
        tickers_failed: Optional[int] = None,
        rows_inserted: Optional[int] = None,
        rows_updated: Optional[int] = None,
        rows_unchanged: Optional[int] = None,
        rows_rejected: Optional[int] = None,
        error_summary: Optional[str] = None,
    ) -> None:
        updates = []
        params = []
        if finished_at is not None:
            updates.append("finished_at = ?")
            params.append(finished_at.isoformat())
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if tickers_succeeded is not None:
            updates.append("tickers_succeeded = ?")
            params.append(tickers_succeeded)
        if tickers_partial is not None:
            updates.append("tickers_partial = ?")
            params.append(tickers_partial)
        if tickers_failed is not None:
            updates.append("tickers_failed = ?")
            params.append(tickers_failed)
        if rows_inserted is not None:
            updates.append("rows_inserted = ?")
            params.append(rows_inserted)
        if rows_updated is not None:
            updates.append("rows_updated = ?")
            params.append(rows_updated)
        if rows_unchanged is not None:
            updates.append("rows_unchanged = ?")
            params.append(rows_unchanged)
        if rows_rejected is not None:
            updates.append("rows_rejected = ?")
            params.append(rows_rejected)
        if error_summary is not None:
            updates.append("error_summary = ?")
            params.append(error_summary)

        if not updates:
            return

        params.append(run_id)
        query = f"UPDATE ingestion_runs SET {', '.join(updates)} WHERE id = ?"
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
        finally:
            if not self._is_memory:
                conn.close()

    def record_ticker_status(self, status: IngestionTickerStatus) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ingestion_ticker_status (
                        id, ingestion_run_id, ticker, status, rows_received,
                        rows_inserted, rows_updated, first_date_received,
                        last_date_received, error_code, error_message, attempt_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status = excluded.status,
                        rows_received = excluded.rows_received,
                        rows_inserted = excluded.rows_inserted,
                        rows_updated = excluded.rows_updated,
                        first_date_received = excluded.first_date_received,
                        last_date_received = excluded.last_date_received,
                        error_code = excluded.error_code,
                        error_message = excluded.error_message,
                        attempt_count = excluded.attempt_count;
                    """,
                    (
                        status.id,
                        status.ingestion_run_id,
                        status.ticker,
                        status.status,
                        status.rows_received,
                        status.rows_inserted,
                        status.rows_updated,
                        str(status.first_date_received) if status.first_date_received else None,
                        str(status.last_date_received) if status.last_date_received else None,
                        status.error_code,
                        status.error_message,
                        status.attempt_count,
                    ),
                )
        finally:
            if not self._is_memory:
                conn.close()

    def get_ingestion_run(self, run_id: str) -> Optional[IngestionRun]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM ingestion_runs WHERE id = ?", [run_id])
            row = cur.fetchone()
            if not row:
                return None
            return IngestionRun(
                id=row["id"],
                provider=row["provider"],
                job_type=row["job_type"],
                started_at=datetime.fromisoformat(row["started_at"]),
                finished_at=datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None,
                status=row["status"],
                tickers_requested=row["tickers_requested"],
                tickers_succeeded=row["tickers_succeeded"],
                tickers_partial=row["tickers_partial"],
                tickers_failed=row["tickers_failed"],
                rows_inserted=row["rows_inserted"],
                rows_updated=row["rows_updated"],
                rows_unchanged=row["rows_unchanged"],
                rows_rejected=row["rows_rejected"],
                error_summary=row["error_summary"],
                config_version=row["config_version"],
            )
        finally:
            if not self._is_memory:
                conn.close()

    def get_ticker_statuses(self, run_id: str) -> list[IngestionTickerStatus]:
        conn = self._get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM ingestion_ticker_status WHERE ingestion_run_id = ? "
                "ORDER BY ticker ASC",
                [run_id],
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                result.append(
                    IngestionTickerStatus(
                        id=r["id"],
                        ingestion_run_id=r["ingestion_run_id"],
                        ticker=r["ticker"],
                        status=r["status"],
                        rows_received=r["rows_received"],
                        rows_inserted=r["rows_inserted"],
                        rows_updated=r["rows_updated"],
                        first_date_received=datetime.strptime(
                            r["first_date_received"], "%Y-%m-%d"
                        ).date()
                        if r["first_date_received"]
                        else None,
                        last_date_received=datetime.strptime(
                            r["last_date_received"], "%Y-%m-%d"
                        ).date()
                        if r["last_date_received"]
                        else None,
                        error_code=r["error_code"],
                        error_message=r["error_message"],
                        attempt_count=r["attempt_count"],
                    )
                )
            return result
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
