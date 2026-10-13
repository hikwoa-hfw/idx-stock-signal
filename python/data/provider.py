import csv
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from python.common.types import DailyBar
from python.config.settings import PROJECT_ROOT, settings

DEFAULT_UNIVERSE: list[str] = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
DEFAULT_SECTOR_MAP: dict[str, str] = {
    "BBCA": "Financials",
    "BBRI": "Financials",
    "BMRI": "Financials",
    "TLKM": "Infrastructure",
    "ASII": "Industrials",
    "BBCA.JK": "Financials",
    "BBRI.JK": "Financials",
    "BMRI.JK": "Financials",
    "TLKM.JK": "Infrastructure",
    "ASII.JK": "Industrials",
}


def load_universe(universe_path: Optional[Path | str] = None) -> list[str]:
    path = (
        Path(universe_path)
        if universe_path
        else PROJECT_ROOT / "configs" / "universe" / "seed_universe.csv"
    )
    if not path.is_file():
        return list(DEFAULT_UNIVERSE)

    tickers: list[str] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            t = normalized.get("ticker")
            active = normalized.get("active", "1")
            if t and active in ("1", "true", "yes"):
                clean = t.strip().upper().removesuffix(".JK")
                if clean not in tickers:
                    tickers.append(clean)
    return sorted(tickers) if tickers else list(DEFAULT_UNIVERSE)


def load_sector_map(universe_path: Optional[Path | str] = None) -> dict[str, str]:
    path = (
        Path(universe_path)
        if universe_path
        else PROJECT_ROOT / "configs" / "universe" / "seed_universe.csv"
    )
    if not path.is_file():
        return dict(DEFAULT_SECTOR_MAP)

    sectors: dict[str, str] = {}
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            t = normalized.get("ticker")
            s = normalized.get("sector")
            if t and s:
                clean = t.strip().upper().removesuffix(".JK")
                sectors[clean] = s
                sectors[f"{clean}.JK"] = s
    return sectors if sectors else dict(DEFAULT_SECTOR_MAP)


@runtime_checkable
class MarketDataProvider(Protocol):
    def get_daily_bars(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[DailyBar]: ...

    def get_universe(self) -> list[str]: ...

    def get_sector_data(self) -> dict[str, str]: ...


class MockMarketDataProvider:
    def __init__(
        self,
        universe: Optional[list[str]] = None,
        sector_map: Optional[dict[str, str]] = None,
        days: int = 60,
        base_date: Optional[date] = None,
    ) -> None:
        self._universe = universe or list(DEFAULT_UNIVERSE)
        self._sector_map = sector_map or dict(DEFAULT_SECTOR_MAP)
        self._days = days
        self._base_date = base_date or date(2026, 10, 10)
        self._bars: dict[str, list[DailyBar]] = {}
        self._generate_synthetic_bars()

    def _generate_synthetic_bars(self) -> None:
        base_prices: dict[str, float] = {
            "BBCA": 10250.0,
            "BBRI": 5100.0,
            "BMRI": 6700.0,
            "TLKM": 3150.0,
            "ASII": 5200.0,
        }

        for ticker in self._universe:
            clean_ticker = ticker.strip().upper().removesuffix(".JK")
            price = base_prices.get(clean_ticker, 5000.0)
            bars: list[DailyBar] = []

            for i in range(self._days):
                bar_date = self._base_date - timedelta(days=(self._days - 1 - i))
                if bar_date.weekday() >= 5:
                    continue

                drift = ((i % 5) - 2) * 25.0
                open_p = max(50.0, price)
                close_p = max(50.0, round(open_p + drift, 2))
                high_p = round(max(open_p, close_p) + 50.0, 2)
                low_p = round(max(25.0, min(open_p, close_p) - 50.0), 2)
                if low_p >= min(open_p, close_p):
                    low_p = round(min(open_p, close_p) * 0.99, 2)
                volume = 1_000_000.0 + (i % 7) * 100_000.0
                value = round(close_p * volume, 2)

                bars.append(
                    DailyBar(
                        ticker=clean_ticker,
                        date=bar_date,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=volume,
                        value=value,
                        provider="mock",
                        provider_symbol=f"{clean_ticker}.JK",
                        interval="1d",
                    )
                )
                price = close_p

            self._bars[clean_ticker] = bars

    def get_daily_bars(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[DailyBar]:
        clean_ticker = ticker.strip().upper().removesuffix(".JK")
        bars = self._bars.get(clean_ticker, [])
        if not bars:
            bars = self._bars.get(ticker, [])

        return [
            b
            for b in bars
            if (start_date is None or b.date >= start_date)
            and (end_date is None or b.date <= end_date)
        ]

    def get_universe(self) -> list[str]:
        return list(self._universe)

    def get_sector_data(self) -> dict[str, str]:
        return dict(self._sector_map)


def _safe_float(val: Optional[str], default: float = float("nan")) -> float:
    if val is None:
        return default
    cleaned = str(val).strip().replace(",", "")
    if not cleaned or cleaned.lower() in ("null", "none", "nan", "n/a", "-"):
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


class CSVMarketDataProvider:
    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        sector_map: Optional[dict[str, str]] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else PROJECT_ROOT / "datasets" / "raw"
        self._sector_map = sector_map or dict(DEFAULT_SECTOR_MAP)

    def _find_csv_file(self, ticker: str) -> Optional[Path]:
        if not self.data_dir.is_dir():
            return None

        clean = ticker.strip().upper().removesuffix(".JK")
        candidates = [
            self.data_dir / f"{clean}.csv",
            self.data_dir / f"{clean}.JK.csv",
            self.data_dir / f"{clean.lower()}.csv",
            self.data_dir / f"{clean.lower()}.jk.csv",
            self.data_dir / f"{ticker.strip()}.csv",
            self.data_dir / f"{ticker.strip().upper()}.csv",
            self.data_dir / f"{ticker.strip().lower()}.csv",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        for p in self.data_dir.glob("*.csv"):
            if p.stem.upper().removesuffix(".JK") == clean:
                return p
        return None

    def _parse_row(self, row: dict[str, str], default_ticker: str) -> Optional[DailyBar]:
        normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}
        raw_ticker = normalized.get("ticker")
        clean_default = default_ticker.strip().upper().removesuffix(".JK")
        ticker = raw_ticker.strip().upper().removesuffix(".JK") if raw_ticker else clean_default

        raw_date = normalized.get("date")
        if not raw_date:
            return None

        try:
            cleaned_date = raw_date.strip()[:10].replace("/", "-")
            bar_date = datetime.strptime(cleaned_date, "%Y-%m-%d").date()
        except ValueError:
            return None

        open_p = _safe_float(normalized.get("open"))
        high_p = _safe_float(normalized.get("high"))
        low_p = _safe_float(normalized.get("low"))
        close_p = _safe_float(normalized.get("close"))
        volume = _safe_float(normalized.get("volume"), default=0.0)
        value_raw = normalized.get("value")
        value = _safe_float(value_raw) if value_raw else round(close_p * volume, 2)
        adj_close = _safe_float(normalized.get("adj_close"))
        if np.isnan(adj_close):
            adj_close = None
        divs = _safe_float(normalized.get("dividends"), default=0.0)
        splits = _safe_float(normalized.get("stock_splits"), default=0.0)

        return DailyBar(
            ticker=ticker,
            date=bar_date,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=volume,
            value=value,
            adj_close=adj_close,
            dividends=divs if not np.isnan(divs) else 0.0,
            stock_splits=splits if not np.isnan(splits) else 0.0,
            provider="local_csv",
            provider_symbol=f"{ticker}.JK",
            interval="1d",
        )

    def get_daily_bars(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[DailyBar]:
        file_path = self._find_csv_file(ticker)
        if not file_path:
            return []

        bars: list[DailyBar] = []
        with open(file_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bar = self._parse_row(row, default_ticker=ticker)
                if not bar:
                    continue
                if start_date and bar.date < start_date:
                    continue
                if end_date and bar.date > end_date:
                    continue
                bars.append(bar)

        bars.sort(key=lambda b: b.date)
        return bars

    def get_universe(self) -> list[str]:
        if not self.data_dir.is_dir():
            return []

        tickers: set[str] = set()
        for p in self.data_dir.glob("*.csv"):
            stem_clean = p.stem.upper().removesuffix(".JK")
            if stem_clean.lower() in ("sectors", "universe"):
                continue
            tickers.add(stem_clean)
        return sorted(tickers)

    def get_sector_data(self) -> dict[str, str]:
        sector_file = self.data_dir / "sectors.csv"
        if not sector_file.is_file():
            for p in self.data_dir.glob("*.csv"):
                if p.stem.lower() == "sectors":
                    sector_file = p
                    break

        if sector_file.is_file():
            sectors: dict[str, str] = {}
            with open(sector_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}
                    t = normalized.get("ticker")
                    s = normalized.get("sector")
                    if t and s:
                        clean_t = t.strip().upper().removesuffix(".JK")
                        sectors[clean_t] = s
                        sectors[f"{clean_t}.JK"] = s
            return sectors
        return dict(self._sector_map)


def _extract_bars_from_single_ticker_df(
    sub_df: pd.DataFrame,
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[DailyBar]:
    bars: list[DailyBar] = []
    clean_ticker = ticker.strip().upper().removesuffix(".JK")

    col_map: dict[str, Any] = {}
    for col in sub_df.columns:
        if isinstance(col, tuple):
            cand_names = [
                str(x).strip().lower().replace("_", "").replace(" ", "") for x in col if x
            ]
            for cname in cand_names:
                if cname in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "adjclose",
                    "dividends",
                    "dividend",
                    "stocksplits",
                    "stocksplit",
                    "splits",
                    "value",
                ):
                    col_map[cname] = col
                    break
            else:
                first_name = str(col[0]).strip().lower().replace("_", "").replace(" ", "")
                col_map[first_name] = col
        else:
            norm_col = str(col).strip().lower().replace("_", "").replace(" ", "")
            col_map[norm_col] = col

    open_col = col_map.get("open")
    high_col = col_map.get("high")
    low_col = col_map.get("low")
    close_col = col_map.get("close")
    vol_col = col_map.get("volume")
    adj_col = col_map.get("adjclose")
    div_col = col_map.get("dividends") or col_map.get("dividend")
    split_col = col_map.get("stocksplits") or col_map.get("stocksplit") or col_map.get("splits")
    val_col = col_map.get("value")

    if not all([open_col, high_col, low_col, close_col]):
        return bars

    for idx, row in sub_df.iterrows():
        if isinstance(idx, pd.Timestamp):
            if idx.tz is not None:
                bar_date = idx.tz_convert("Asia/Jakarta").date()
            else:
                bar_date = idx.date()
        elif hasattr(idx, "date"):
            bar_date = idx.date()
        else:
            try:
                ts = pd.to_datetime(idx)
                if getattr(ts, "tz", None) is not None:
                    bar_date = ts.tz_convert("Asia/Jakarta").date()
                else:
                    bar_date = ts.date()
            except Exception:
                continue

        if start_date and bar_date < start_date:
            continue
        if end_date and bar_date > end_date:
            continue

        try:
            open_p = float(row[open_col])
            high_p = float(row[high_col])
            low_p = float(row[low_col])
            close_p = float(row[close_col])
        except (TypeError, ValueError):
            continue

        if any(
            np.isnan([open_p, high_p, low_p, close_p]) | np.isinf([open_p, high_p, low_p, close_p])
        ):
            continue
        if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
            continue

        volume = 0.0
        if vol_col and not pd.isna(row.get(vol_col)):
            try:
                volume = max(0.0, float(row[vol_col]))
            except (TypeError, ValueError):
                volume = 0.0

        if val_col and not pd.isna(row.get(val_col)):
            try:
                value = max(0.0, float(row[val_col]))
            except (TypeError, ValueError):
                value = round(close_p * volume, 2)
        else:
            value = round(close_p * volume, 2)

        adj_close = None
        if adj_col and not pd.isna(row.get(adj_col)):
            try:
                v = float(row[adj_col])
                if not (np.isnan(v) or np.isinf(v)) and v > 0:
                    adj_close = v
            except (TypeError, ValueError):
                pass

        divs = 0.0
        if div_col and not pd.isna(row.get(div_col)):
            try:
                v = float(row[div_col])
                if not (np.isnan(v) or np.isinf(v)) and v >= 0:
                    divs = v
            except (TypeError, ValueError):
                pass

        splits = 0.0
        if split_col and not pd.isna(row.get(split_col)):
            try:
                v = float(row[split_col])
                if not (np.isnan(v) or np.isinf(v)) and v >= 0:
                    splits = v
            except (TypeError, ValueError):
                pass

        bars.append(
            DailyBar(
                ticker=clean_ticker,
                date=bar_date,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=volume,
                value=value,
                adj_close=adj_close,
                dividends=divs,
                stock_splits=splits,
                provider="yfinance",
                provider_symbol=f"{clean_ticker}.JK",
                interval="1d",
            )
        )

    bars.sort(key=lambda b: b.date)
    return bars


def normalize_yfinance_dataframe(
    df: Optional[pd.DataFrame],
    requested_tickers: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, list[DailyBar]]:
    results: dict[str, list[DailyBar]] = {
        t.strip().upper().removesuffix(".JK"): [] for t in requested_tickers
    }
    if df is None or df.empty:
        return results

    canonical_map: dict[str, str] = {}
    for t in requested_tickers:
        clean = t.strip().upper().removesuffix(".JK")
        canonical_map[clean] = clean
        canonical_map[f"{clean}.JK"] = clean
        canonical_map[clean.lower()] = clean
        canonical_map[f"{clean.lower()}.jk"] = clean

    if isinstance(df.columns, pd.MultiIndex):
        col_l0 = {str(x).strip().upper() for x in df.columns.get_level_values(0)}
        col_l1 = {str(x).strip().upper() for x in df.columns.get_level_values(1)}

        level_0_is_ticker = any(x in col_l0 for x in canonical_map)
        level_1_is_ticker = any(x in col_l1 for x in canonical_map)

        for req in requested_tickers:
            clean = req.strip().upper().removesuffix(".JK")
            sym = f"{clean}.JK"

            sub_df = None
            if level_0_is_ticker:
                for actual in df.columns.get_level_values(0).unique():
                    if str(actual).strip().upper() in (clean, sym):
                        try:
                            sub = df[actual]
                            if isinstance(sub, pd.Series):
                                sub = sub.to_frame()
                            sub_df = sub
                            break
                        except (KeyError, TypeError, ValueError):
                            pass
            elif level_1_is_ticker:
                for actual in df.columns.get_level_values(1).unique():
                    if str(actual).strip().upper() in (clean, sym):
                        try:
                            sub = df.xs(actual, level=1, axis=1)
                            if isinstance(sub, pd.Series):
                                sub = sub.to_frame()
                            sub_df = sub
                            break
                        except (KeyError, TypeError, ValueError):
                            pass

            if sub_df is not None and not sub_df.empty:
                results[clean] = _extract_bars_from_single_ticker_df(
                    sub_df, clean, start_date=start_date, end_date=end_date
                )
    else:
        flat_cols = {str(c).strip().lower(): c for c in df.columns}
        ticker_col_name = flat_cols.get("ticker") or flat_cols.get("symbol")
        if ticker_col_name:
            for clean_t in results.keys():
                ticker_mask = (
                    df[ticker_col_name].astype(str).str.strip().str.upper().str.removesuffix(".JK")
                    == clean_t
                )
                ticker_df = df[ticker_mask]
                if not ticker_df.empty:
                    results[clean_t] = _extract_bars_from_single_ticker_df(
                        ticker_df, clean_t, start_date=start_date, end_date=end_date
                    )
        elif len(requested_tickers) == 1:
            clean = requested_tickers[0].strip().upper().removesuffix(".JK")
            results[clean] = _extract_bars_from_single_ticker_df(
                df, clean, start_date=start_date, end_date=end_date
            )
        else:
            first_clean = requested_tickers[0].strip().upper().removesuffix(".JK")
            results[first_clean] = _extract_bars_from_single_ticker_df(
                df, first_clean, start_date=start_date, end_date=end_date
            )

    return results


class YFinanceMarketDataProvider:
    def __init__(
        self,
        universe: Optional[list[str]] = None,
        sector_map: Optional[dict[str, str]] = None,
        universe_path: Optional[Path | str] = None,
        batch_size: int = 25,
        max_workers: int = 4,
        retry_attempts: int = 4,
        retry_backoff_seconds: Optional[list[float]] = None,
    ) -> None:
        self._universe = universe or load_universe(universe_path)
        self._sector_map = sector_map or load_sector_map(universe_path)
        self.batch_size = max(1, batch_size)
        self.max_workers = max(1, max_workers)
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = (
            retry_backoff_seconds if retry_backoff_seconds is not None else [2.0, 5.0, 10.0, 20.0]
        )

    def get_universe(self) -> list[str]:
        return list(self._universe)

    def get_sector_data(self) -> dict[str, str]:
        return dict(self._sector_map)

    def _fetch_yfinance(
        self,
        symbols: list[str],
        start_str: Optional[str] = None,
        end_str: Optional[str] = None,
    ) -> Any:
        import yfinance as yf

        ticker_arg = symbols if len(symbols) > 1 else symbols[0]
        return yf.download(
            tickers=ticker_arg,
            start=start_str,
            end=end_str,
            interval="1d",
            auto_adjust=False,
            actions=True,
            group_by="ticker",
            threads=False,
            progress=False,
            timeout=20,
        )

    def get_daily_bars(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[DailyBar]:
        clean = ticker.strip().upper().removesuffix(".JK")
        batch_res = self.get_daily_bars_batch([clean], start_date=start_date, end_date=end_date)
        return batch_res.get(clean, [])

    def get_daily_bars_batch(
        self,
        tickers: list[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, list[DailyBar]]:
        if not tickers:
            return {}

        start_str = str(start_date) if start_date else None
        end_str = (end_date + timedelta(days=1)).isoformat()[:10] if end_date else None

        results: dict[str, list[DailyBar]] = {}
        chunks = [tickers[i : i + self.batch_size] for i in range(0, len(tickers), self.batch_size)]

        def _process_chunk(chunk: list[str]) -> dict[str, list[DailyBar]]:
            provider_symbols = [f"{t.strip().upper().removesuffix('.JK')}.JK" for t in chunk]
            batch_df = None
            for attempt in range(self.retry_attempts):
                try:
                    batch_df = self._fetch_yfinance(
                        provider_symbols, start_str=start_str, end_str=end_str
                    )
                    break
                except Exception:
                    if attempt < len(self.retry_backoff_seconds):
                        time.sleep(self.retry_backoff_seconds[attempt])
                    elif attempt < self.retry_attempts - 1:
                        time.sleep(1.0)

            if batch_df is not None:
                return normalize_yfinance_dataframe(
                    batch_df, chunk, start_date=start_date, end_date=end_date
                )
            return {t.strip().upper().removesuffix(".JK"): [] for t in chunk}

        if len(chunks) > 1 and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(chunks))) as executor:
                for chunk_res in executor.map(_process_chunk, chunks):
                    results.update(chunk_res)
        else:
            for chunk in chunks:
                results.update(_process_chunk(chunk))

        return results


def get_market_data_provider(
    provider_name: Optional[str] = None,
    **kwargs,
) -> MarketDataProvider:
    name = (provider_name or settings.market_data_provider).lower()
    if name in ("mock", "synthetic"):
        return MockMarketDataProvider(**kwargs)
    if name in ("local_csv", "csv"):
        return CSVMarketDataProvider(**kwargs)
    if name in ("yfinance", "yf"):
        return YFinanceMarketDataProvider(**kwargs)
    raise ValueError(f"Unsupported market data provider: {name}")
