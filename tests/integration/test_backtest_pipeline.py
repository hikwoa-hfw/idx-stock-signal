import json
import subprocess
import sys
from pathlib import Path

import pytest

from python.backtest.engine import BacktestEngine
from python.common.types import BacktestConfig
from python.data.provider import MockMarketDataProvider
from python.features.engine import FeatureEngine
from python.labels.engine import LabelEngine
from python.models.baseline import LogisticRegressionBaseline
from python.models.dataset import DatasetBuilder


def test_end_to_end_backtest_with_mock_market_data(tmp_path: Path):
    """End-to-end test: synthetic market data -> feature engine -> baseline model -> backtest."""
    tickers = ["BBCA", "BBRI", "BMRI"]
    provider = MockMarketDataProvider(universe=tickers, days=90)
    all_bars = []
    bars_by_t = {}
    for t in tickers:
        b_list = provider.get_daily_bars(t)
        all_bars.extend(b_list)
        bars_by_t[t] = b_list

    # 1. Feature engine
    feat_engine = FeatureEngine()
    feats_dict = feat_engine.compute_universe_features(bars_by_t)
    feats = [f for f_list in feats_dict.values() for f in f_list]

    # 2. Label engine
    lbl_engine = LabelEngine(tp_pct=0.04, sl_pct=0.02, max_holding_days=8)
    labels = lbl_engine.compute_labels(all_bars)

    # 3. Build dataset & train baseline classifier
    dataset = DatasetBuilder().build_from_records(feats, labels)
    assert len(dataset) > 0

    model = LogisticRegressionBaseline().fit(dataset.X, dataset.y, dataset.feature_names)

    # 4. Run Backtest
    cfg = BacktestConfig(
        initial_capital=50_000_000.0,
        commission_buy=0.0015,
        commission_sell=0.0025,
        slippage_bps=10.0,
        max_concurrent_positions=3,
        risk_per_trade_pct=0.01,
        probability_threshold=0.45,
        tp_pct=0.04,
        sl_pct=0.02,
        max_holding_days=8,
    )
    engine = BacktestEngine(config=cfg)
    report = engine.run(bars=all_bars, model=model)

    assert report.initial_capital == 50_000_000.0
    assert report.total_trades >= 0
    assert len(report.equity_curve) > 0

    # Invariant: final equity equals initial capital plus sum of net PnL
    expected_final = cfg.initial_capital + sum(t.net_pnl for t in report.trades)
    assert pytest.approx(report.final_equity, abs=1e-3) == expected_final


def test_cli_run_backtest_table_and_json(tmp_path: Path):
    """Integration test for CLI execution with --format table and --format json."""
    python_exe = sys.executable

    # Test table output
    res_table = subprocess.run(
        [
            python_exe,
            "-m",
            "scripts.run_backtest",
            "--tickers",
            "BBCA",
            "BBRI",
            "--format",
            "table",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BEI STOCK BACKTEST PERFORMANCE REPORT" in res_table.stdout
    assert "Initial Capital" in res_table.stdout

    # Test JSON output and trade export
    export_csv = tmp_path / "trades.csv"
    res_json = subprocess.run(
        [
            python_exe,
            "-m",
            "scripts.run_backtest",
            "--tickers",
            "BBCA",
            "--format",
            "json",
            "--export-trades",
            str(export_csv),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    # Parse output as JSON BacktestReport
    report_dict = json.loads(res_json.stdout)
    assert "initial_capital" in report_dict
    assert "final_equity" in report_dict
    assert "total_trades" in report_dict

    # Check exported CSV exists
    assert export_csv.is_file()


def test_cli_runner_comma_tickers_and_json(tmp_path: Path):
    """Test CLI runner with comma-separated tickers and pure JSON output parsing."""
    python_exe = sys.executable
    res = subprocess.run(
        [
            python_exe,
            "-m",
            "scripts.run_backtest",
            "--tickers",
            "BBCA,BBRI",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    # Output must be pure parseable JSON with no stdout logging contamination
    data = json.loads(res.stdout)
    assert data["initial_capital"] == 100_000_000.0
    assert "trades" in data
