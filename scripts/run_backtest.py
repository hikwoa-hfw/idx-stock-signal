import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import joblib

from python.backtest.engine import BacktestEngine
from python.common.types import BacktestConfig, BacktestReport
from python.config.settings import settings
from python.data.provider import DEFAULT_UNIVERSE, MockMarketDataProvider
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.labels.engine import LabelEngine
from python.models.baseline import LogisticRegressionBaseline
from python.models.dataset import DatasetBuilder
from python.models.registry import ModelRegistry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run discrete-event backtest simulation on BEI stock data."
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help="Path to saved .joblib model artifact.",
    )
    parser.add_argument(
        "--use-champion",
        action="store_true",
        help="Use current champion model from model registry.",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Filter start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Filter end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Tickers to include in universe (e.g. BBCA BBRI BMRI).",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100_000_000.0,
        help="Initial capital in IDR (default: 100,000,000).",
    )
    parser.add_argument(
        "--commission-rate",
        type=float,
        default=None,
        help="Uniform commission rate (overrides buy/sell commissions if set).",
    )
    parser.add_argument(
        "--commission-buy",
        type=float,
        default=0.0015,
        help="Broker buy commission fraction (default: 0.0015 / 0.15%%).",
    )
    parser.add_argument(
        "--commission-sell",
        type=float,
        default=0.0025,
        help="Broker sell commission fraction including levy/tax (default: 0.0025 / 0.25%%).",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=10.0,
        help="Execution slippage in basis points (default: 10.0 bps).",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="Maximum concurrent open positions (default: 5).",
    )
    parser.add_argument(
        "--risk-pct",
        type=float,
        default=0.005,
        help="Risk fraction per trade (default: 0.005 / 0.5%%).",
    )
    parser.add_argument(
        "--sizing",
        choices=["risk_based", "fixed_fractional", "equal_weight"],
        default="risk_based",
        help="Position sizing method (default: risk_based).",
    )
    parser.add_argument(
        "--tp-pct",
        type=float,
        default=0.05,
        help="Take profit barrier fraction (default: 0.05 / 5%%).",
    )
    parser.add_argument(
        "--sl-pct",
        type=float,
        default=0.02,
        help="Stop loss barrier fraction (default: 0.02 / 2%%).",
    )
    parser.add_argument(
        "--max-hold",
        type=int,
        default=10,
        help="Maximum holding trading days (default: 10).",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output presentation format: table or json.",
    )
    parser.add_argument(
        "--export-trades",
        default=None,
        help="Filepath to export trades (.csv or .json).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to settings.database_url.",
    )
    return parser.parse_args()


def load_model(
    model_path: Optional[str],
    use_champion: bool,
    registry_dir: Optional[str] = None,
) -> Optional[Any]:
    if model_path:
        p = Path(model_path)
        if not p.is_file():
            sys.stderr.write(f"[run_backtest] Error: Model file not found: {model_path}\n")
            sys.exit(1)
        return joblib.load(p)

    registry = ModelRegistry(registry_dir=registry_dir)
    if use_champion:
        res = registry.get_champion(task="classification")
        if res is not None:
            model, _ = res
            return model
        sys.stderr.write("[run_backtest] Error: No champion model found in registry.\n")
        sys.exit(1)

    # Try champion first as default fallback if neither flag given
    res = registry.get_champion(task="classification")
    if res is not None:
        model, _ = res
        return model

    return None


def print_table_report(report: BacktestReport, universe: list[str]) -> None:
    cagr_str = f"{report.cagr_pct * 100:+.2f}%" if report.cagr_pct is not None else "N/A"
    pf_str = f"{report.profit_factor:.2f}" if math.isfinite(report.profit_factor) else "Inf"
    wl_str = f"{report.win_loss_ratio:.2f}" if math.isfinite(report.win_loss_ratio) else "Inf"

    print("\n" + "=" * 80)
    print("                     BEI STOCK BACKTEST PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Period              : {report.start_date} to {report.end_date}")
    print(f"Universe            : {', '.join(universe)}")
    print(f"Initial Capital     : IDR {report.initial_capital:,.2f}")
    print(f"Final Equity        : IDR {report.final_equity:,.2f}")
    ret_str = f"{report.total_return_pct * 100:+.2f}%"
    print(f"Total Net PnL       : IDR {report.total_net_pnl:,.2f} ({ret_str})")
    print(f"CAGR                : {cagr_str}")
    print("-" * 80)
    n_trades = report.total_trades
    win_pct = (report.winning_trades / n_trades * 100.0) if n_trades > 0 else 0.0
    loss_pct = (report.losing_trades / n_trades * 100.0) if n_trades > 0 else 0.0

    print(f"Total Trades        : {report.total_trades}")
    print(f"Winning Trades      : {report.winning_trades} ({win_pct:.2f}%)")
    print(f"Losing Trades       : {report.losing_trades} ({loss_pct:.2f}%)")

    print(f"Average Win         : {report.average_win_pct * 100:+.2f}%")
    print(f"Average Loss        : {report.average_loss_pct * 100:+.2f}%")
    print(f"Win / Loss Ratio    : {wl_str}")
    print(f"Profit Factor       : {pf_str}")
    print(f"Expectancy / Trade  : {report.expectancy_pct * 100:+.2f}%")
    mdd_pct_str = f"{report.max_drawdown_pct * 100:.2f}%"
    print(f"Max Drawdown        : {mdd_pct_str} (IDR {report.max_drawdown_amount:,.2f})")
    print(f"Avg Holding Days    : {report.average_holding_days:.1f} days")

    print(
        f"Exit Breakdown      : TP: {report.tp_rate * 100:.1f}% | "
        f"SL: {report.sl_rate * 100:.1f}% | "
        f"Expiry: {report.expiry_rate * 100:.1f}%"
    )
    print("=" * 80 + "\n")


def export_trades(report: BacktestReport, export_path: str) -> None:
    p = Path(export_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.suffix.lower() == ".csv":
        fieldnames = [
            "trade_id",
            "ticker",
            "signal_date",
            "entry_date",
            "exit_date",
            "shares",
            "entry_price",
            "exit_price",
            "position_value",
            "entry_fee",
            "exit_fee",
            "slippage_cost",
            "gross_pnl",
            "net_pnl",
            "net_return",
            "exit_reason",
            "holding_days",
            "mfe",
            "mae",
            "signal_probability",
        ]
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in report.trades:
                writer.writerow(t.model_dump(mode="json"))
    else:
        trades_data = [t.model_dump(mode="json") for t in report.trades]
        p.write_text(json.dumps(trades_data, indent=2), encoding="utf-8")

    sys.stderr.write(
        f"[run_backtest] Exported {len(report.trades)} trade records to {export_path}\n"
    )


def main() -> None:
    args = parse_args()
    db = args.db_url or settings.database_url
    bar_repo = DailyBarRepository(db)

    raw_tickers = args.tickers or DEFAULT_UNIVERSE
    tickers_list: list[str] = []
    for item in raw_tickers:
        for t in item.split(","):
            clean = t.strip().upper().removesuffix(".JK")
            if clean:
                tickers_list.append(clean)
    target_universe = list(dict.fromkeys(tickers_list))

    # Load daily bars
    all_bars = []
    for t in target_universe:
        bars = bar_repo.get_daily_bars(t)
        if bars:
            all_bars.extend(bars)

    # Fallback to mock data if DB empty
    if not all_bars:
        mock = MockMarketDataProvider(universe=target_universe, days=120)
        for t in target_universe:
            bars = mock.get_daily_bars(t)
            if bars:
                all_bars.extend(bars)

    # Date filter
    if args.start_date:
        s_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        all_bars = [b for b in all_bars if b.date >= s_date]
    if args.end_date:
        e_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        all_bars = [b for b in all_bars if b.date <= e_date]

    if not all_bars:
        sys.stderr.write(
            "[run_backtest] Error: No market data available for the specified range.\n"
        )
        sys.exit(1)

    # Commission settings
    comm_buy = args.commission_rate if args.commission_rate is not None else args.commission_buy
    comm_sell = args.commission_rate if args.commission_rate is not None else args.commission_sell

    config = BacktestConfig(
        initial_capital=args.initial_capital,
        commission_buy=comm_buy,
        commission_sell=comm_sell,
        slippage_bps=args.slippage_bps,
        max_concurrent_positions=args.max_positions,
        risk_per_trade_pct=args.risk_pct,
        position_sizing_method=args.sizing,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        max_holding_days=args.max_hold,
    )

    # Load model
    model = load_model(args.model_path, args.use_champion)
    if model is None:
        # Train a fast fallback baseline on loaded bars
        sys.stderr.write(
            "[run_backtest] No pre-trained model found. Fitting baseline logistic classifier...\n"
        )
        feat_engine = FeatureEngine()
        bars_by_t: dict[str, list] = {}
        for b in all_bars:
            bars_by_t.setdefault(b.ticker, []).append(b)
        feats_dict = feat_engine.compute_universe_features(bars_by_t)
        feats = [f for f_list in feats_dict.values() for f in f_list]
        lbl_engine = LabelEngine(tp_pct=config.tp_pct, sl_pct=config.sl_pct)
        labels = lbl_engine.compute_labels(all_bars)
        dataset = DatasetBuilder().build_from_records(feats, labels)
        if len(dataset) > 0 and len(set(dataset.y)) > 1:
            baseline = LogisticRegressionBaseline().fit(dataset.X, dataset.y, dataset.feature_names)
            model = baseline
        else:
            model = None

    engine = BacktestEngine(config=config)
    report = engine.run(bars=all_bars, model=model)

    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print_table_report(report, target_universe)

    if args.export_trades:
        export_trades(report, args.export_trades)


if __name__ == "__main__":
    main()
