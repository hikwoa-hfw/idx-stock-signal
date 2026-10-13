from datetime import date
from typing import Optional

from python.common.types import DailyBar, FeatureRecord
from python.data.provider import DEFAULT_SECTOR_MAP
from python.features.indicators import (
    compute_atr,
    compute_daily_range_pct,
    compute_ema,
    compute_realized_vol,
    compute_relative_distance,
    compute_returns,
    compute_rolling_mean_ratio,
    compute_rsi,
    compute_rsi_change,
)

FEATURE_VERSION = "v1.0.0"
BENCHMARK_TICKERS = {"IHSG", "^JKSE", "COMPOSITE"}


class FeatureEngine:
    def __init__(
        self,
        feature_version: str = FEATURE_VERSION,
        sector_map: Optional[dict[str, str]] = None,
    ) -> None:
        self.feature_version = feature_version
        self.sector_map = {
            k.strip().upper().removesuffix(".JK"): v
            for k, v in (sector_map or DEFAULT_SECTOR_MAP).items()
        }

    def compute_stock_features(self, bars: list[DailyBar]) -> list[FeatureRecord]:
        if not bars:
            return []

        # Deduplicate bars by date and sort
        seen_dates: set[date] = set()
        sorted_bars: list[DailyBar] = []
        for b in sorted(bars, key=lambda x: x.date):
            if b.date not in seen_dates:
                seen_dates.add(b.date)
                sorted_bars.append(b)

        if not sorted_bars:
            return []

        ticker = sorted_bars[0].ticker.strip().upper().removesuffix(".JK")
        n = len(sorted_bars)

        closes = [float(b.close) for b in sorted_bars]
        highs = [float(b.high) for b in sorted_bars]
        lows = [float(b.low) for b in sorted_bars]
        volumes = [float(b.volume) for b in sorted_bars]
        values = [
            float(b.value) if b.value is not None else float(b.close * b.volume)
            for b in sorted_bars
        ]

        # Momentum
        ret_1d = compute_returns(closes, 1)
        ret_3d = compute_returns(closes, 3)
        ret_5d = compute_returns(closes, 5)
        ret_10d = compute_returns(closes, 10)
        ret_20d = compute_returns(closes, 20)

        # Trend
        ema20 = compute_ema(closes, 20)
        ema50 = compute_ema(closes, 50)
        ema200 = compute_ema(closes, 200)

        # RSI
        rsi14 = compute_rsi(closes, 14)
        rsi_chg_5d = compute_rsi_change(rsi14, 5)

        # Volatility
        atr14 = compute_atr(highs, lows, closes, 14)
        realized_vol_5d = compute_realized_vol(ret_1d, 5)
        realized_vol_20d = compute_realized_vol(ret_1d, 20)
        daily_range_pct = compute_daily_range_pct(highs, lows, closes)

        # Volume
        vol_ratio_5d = compute_rolling_mean_ratio(volumes, 5)
        vol_ratio_20d = compute_rolling_mean_ratio(volumes, 20)
        val_ratio_20d = compute_rolling_mean_ratio(values, 20)

        records: list[FeatureRecord] = []
        for i in range(n):
            c = closes[i]
            e20 = ema20[i]
            e50 = ema50[i]
            e200 = ema200[i]
            atr = atr14[i]

            atr_pct = (atr / c) if (atr is not None and c > 0) else None

            rec = FeatureRecord(
                ticker=ticker,
                date=sorted_bars[i].date,
                feature_version=self.feature_version,
                return_1d=ret_1d[i],
                return_3d=ret_3d[i],
                return_5d=ret_5d[i],
                return_10d=ret_10d[i],
                return_20d=ret_20d[i],
                ema20=e20,
                ema50=e50,
                ema200=e200,
                close_vs_ema20=compute_relative_distance(c, e20),
                close_vs_ema50=compute_relative_distance(c, e50),
                ema20_vs_ema50=compute_relative_distance(e20, e50),
                ema50_vs_ema200=compute_relative_distance(e50, e200),
                rsi14=rsi14[i],
                rsi_change_5d=rsi_chg_5d[i],
                atr14=atr,
                atr_pct=atr_pct,
                realized_vol_5d=realized_vol_5d[i],
                realized_vol_20d=realized_vol_20d[i],
                daily_range_pct=daily_range_pct[i],
                volume_ratio_5d=vol_ratio_5d[i],
                volume_ratio_20d=vol_ratio_20d[i],
                value_ratio_20d=val_ratio_20d[i],
            )
            records.append(rec)

        return records

    def compute_universe_features(
        self, universe_bars: dict[str, list[DailyBar]]
    ) -> dict[str, list[FeatureRecord]]:
        if not universe_bars:
            return {}

        clean_universe: dict[str, list[DailyBar]] = {}
        for raw_tk, bars in universe_bars.items():
            if not bars:
                continue
            clean_tk = raw_tk.strip().upper().removesuffix(".JK")
            if clean_tk in clean_universe:
                clean_universe[clean_tk].extend(bars)
            else:
                clean_universe[clean_tk] = list(bars)

        for tk, bars in list(clean_universe.items()):
            seen_dates: set[date] = set()
            deduped: list[DailyBar] = []
            for b in sorted(bars, key=lambda x: x.date):
                if b.date not in seen_dates:
                    seen_dates.add(b.date)
                    deduped.append(b)
            if deduped:
                clean_universe[tk] = deduped
            else:
                del clean_universe[tk]

        if not clean_universe:
            return {}

        # 1. Compute individual stock features
        stock_records: dict[str, list[FeatureRecord]] = {
            tk: self.compute_stock_features(bars) for tk, bars in clean_universe.items()
        }

        # Index records by (ticker, date)
        stock_date_map: dict[str, dict[date, FeatureRecord]] = {
            tk: {r.date: r for r in recs} for tk, recs in stock_records.items()
        }

        # Collect sorted union of all trading dates
        all_dates = sorted({b.date for bars in clean_universe.values() for b in bars})

        # 2. Extract or build benchmark series
        benchmark_key = None
        for tk in clean_universe:
            if tk in BENCHMARK_TICKERS:
                benchmark_key = tk
                break

        stock_tickers = [tk for tk in clean_universe if tk not in BENCHMARK_TICKERS]
        stock_close_map = {
            tk: {b.date: float(b.close) for b in bars} for tk, bars in clean_universe.items()
        }

        benchmark_closes: list[float] = []
        if benchmark_key:
            bench_bars = {b.date: float(b.close) for b in clean_universe[benchmark_key]}
            first_bench_close = float(clean_universe[benchmark_key][0].close)
            last_p = first_bench_close
            for d in all_dates:
                if d in bench_bars:
                    last_p = bench_bars[d]
                benchmark_closes.append(last_p)
        else:
            # Build equal-weighted composite proxy from non-benchmark universe
            proxy_price = 1000.0
            for d in all_dates:
                day_rets = [
                    stock_date_map[tk][d].return_1d
                    for tk in stock_tickers
                    if d in stock_date_map[tk] and stock_date_map[tk][d].return_1d is not None
                ]
                mean_ret = sum(day_rets) / len(day_rets) if day_rets else 0.0
                proxy_price = proxy_price * (1.0 + mean_ret)
                benchmark_closes.append(proxy_price)

        bench_ret_1d = compute_returns(benchmark_closes, 1)
        bench_ret_5d = compute_returns(benchmark_closes, 5)
        bench_ret_20d = compute_returns(benchmark_closes, 20)
        bench_ema20 = compute_ema(benchmark_closes, 20)
        bench_ema50 = compute_ema(benchmark_closes, 50)
        bench_vol_20d = compute_realized_vol(bench_ret_1d, 20)

        date_regime: dict[date, dict[str, Optional[float]]] = {}
        for idx, d in enumerate(all_dates):
            bc = benchmark_closes[idx]
            be20 = bench_ema20[idx]
            be50 = bench_ema50[idx]

            # Market breadth: count of stocks above EMA20 on date d
            valid_e20_count = 0
            above_e20_count = 0
            for tk in stock_tickers:
                if d in stock_date_map[tk]:
                    rec = stock_date_map[tk][d]
                    if rec.ema20 is not None:
                        valid_e20_count += 1
                        c = stock_close_map[tk].get(d)
                        if c is not None and c > rec.ema20:
                            above_e20_count += 1

            breadth = (above_e20_count / float(valid_e20_count)) if valid_e20_count > 0 else None

            date_regime[d] = {
                "ihsg_return_5d": bench_ret_5d[idx],
                "ihsg_return_20d": bench_ret_20d[idx],
                "ihsg_vs_ema20": compute_relative_distance(bc, be20),
                "ihsg_vs_ema50": compute_relative_distance(bc, be50),
                "market_breadth": breadth,
                "market_volatility": bench_vol_20d[idx],
            }

        # 3. Compute sector 20d return per date
        sector_date_ret20: dict[str, dict[date, Optional[float]]] = {}
        all_sectors = set(self.sector_map.values())
        for sec in all_sectors:
            sec_tickers = [
                tk for tk, s in self.sector_map.items() if s == sec and tk in stock_date_map
            ]
            sector_date_ret20[sec] = {}
            for d in all_dates:
                rets = [
                    stock_date_map[tk][d].return_20d
                    for tk in sec_tickers
                    if d in stock_date_map[tk] and stock_date_map[tk][d].return_20d is not None
                ]
                sector_date_ret20[sec][d] = (sum(rets) / len(rets)) if rets else None

        # 4. Enrich stock records with relative strength & market regime
        for tk, recs in stock_records.items():
            sec = self.sector_map.get(tk)
            for rec in recs:
                regime = date_regime.get(rec.date, {})
                rec.ihsg_return_5d = regime.get("ihsg_return_5d")
                rec.ihsg_return_20d = regime.get("ihsg_return_20d")
                rec.ihsg_vs_ema20 = regime.get("ihsg_vs_ema20")
                rec.ihsg_vs_ema50 = regime.get("ihsg_vs_ema50")
                rec.market_breadth = regime.get("market_breadth")
                rec.market_volatility = regime.get("market_volatility")

                # Relative Strength vs IHSG
                if rec.return_20d is not None and rec.ihsg_return_20d is not None:
                    rec.rel_strength_ihsg_20d = rec.return_20d - rec.ihsg_return_20d
                else:
                    rec.rel_strength_ihsg_20d = None

                # Relative Strength vs Sector
                sec_ret20 = sector_date_ret20.get(sec, {}).get(rec.date) if sec else None
                if rec.return_20d is not None and sec_ret20 is not None:
                    rec.rel_strength_sector_20d = rec.return_20d - sec_ret20
                else:
                    rec.rel_strength_sector_20d = None

        return stock_records
