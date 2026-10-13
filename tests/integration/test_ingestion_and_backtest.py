from pathlib import Path

from python.backtest.engine import BacktestEngine
from python.common.types import BacktestConfig
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.labels.engine import LabelEngine
from python.models.baseline import LogisticRegressionBaseline
from python.models.dataset import DatasetBuilder
from scripts.ingest_daily import main as ingest_main


def test_cli_ingestion_modes_and_audit(tmp_path: Path):
    db_file = tmp_path / "modes_audit.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # 1. Backfill mode
    code_backfill = ingest_main(
        [
            "--mode",
            "backfill",
            "--provider",
            "mock",
            "--tickers",
            "BBCA,BBRI",
            "--days",
            "30",
            "--db-url",
            db_url,
        ]
    )
    assert code_backfill == 0

    repo = DailyBarRepository(database_url=db_url)
    assert repo.count_bars("BBCA") > 0
    assert repo.count_bars("BBRI") > 0

    conn = repo._get_connection()
    try:
        runs = conn.execute("SELECT * FROM ingestion_runs ORDER BY started_at ASC").fetchall()
        assert len(runs) >= 1
        assert runs[0]["job_type"] == "backfill"
        assert runs[0]["status"] == "SUCCESS"
        assert runs[0]["tickers_succeeded"] == 2

        ticker_statuses = conn.execute("SELECT * FROM ingestion_ticker_status").fetchall()
        assert len(ticker_statuses) >= 2
    finally:
        conn.close()

    # 2. Incremental mode (should report unchanged or small overlap update)
    code_incr = ingest_main(
        [
            "--mode",
            "incremental",
            "--provider",
            "mock",
            "--tickers",
            "BBCA,BBRI",
            "--days",
            "30",
            "--db-url",
            db_url,
        ]
    )
    assert code_incr == 0

    conn = repo._get_connection()
    try:
        runs = conn.execute("SELECT * FROM ingestion_runs ORDER BY started_at ASC").fetchall()
        assert len(runs) >= 2
        # Run 2 (incremental) should accurately report unchanged rows
        assert runs[1]["rows_unchanged"] > 0
    finally:
        conn.close()

    # 3. Repair mode
    code_repair = ingest_main(
        [
            "--mode",
            "repair",
            "--provider",
            "mock",
            "--tickers",
            "BBCA",
            "--lookback-days",
            "15",
            "--days",
            "30",
            "--db-url",
            db_url,
        ]
    )
    assert code_repair == 0


def test_cli_ingestion_failure_exit_code(tmp_path: Path):
    db_file = tmp_path / "fail_audit.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # Invalid ticker with 0 days produces NO_DATA for all tickers -> status FAILED -> exit code 1
    code = ingest_main(
        [
            "--mode",
            "incremental",
            "--provider",
            "mock",
            "--tickers",
            "INVALID_TICKER",
            "--days",
            "0",
            "--db-url",
            db_url,
        ]
    )
    assert code == 1


def test_end_to_end_backtest_with_ingested_dataset(tmp_path: Path):
    db_file = tmp_path / "backtest_ingested.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    tickers = ["BBCA", "BBRI", "BMRI"]
    # Ingest 90 days of mock history into SQLite repository
    ingest_code = ingest_main(
        [
            "--mode",
            "backfill",
            "--provider",
            "mock",
            "--tickers",
            ",".join(tickers),
            "--days",
            "90",
            "--db-url",
            db_url,
        ]
    )
    assert ingest_code == 0

    repo = DailyBarRepository(database_url=db_url)
    all_bars = []
    bars_by_t = {}
    for t in tickers:
        b_list = repo.get_daily_bars(t)
        assert len(b_list) >= 50
        all_bars.extend(b_list)
        bars_by_t[t] = b_list

    # 1. Feature engine consuming data from repository
    feat_engine = FeatureEngine()
    feats_dict = feat_engine.compute_universe_features(bars_by_t)
    feats = [f for f_list in feats_dict.values() for f in f_list]
    assert len(feats) > 0

    # 2. Label engine
    lbl_engine = LabelEngine(tp_pct=0.04, sl_pct=0.02, max_holding_days=8)
    labels = lbl_engine.compute_labels(all_bars)
    assert len(labels) > 0

    # 3. DatasetBuilder & baseline model training
    dataset = DatasetBuilder().build_from_records(feats, labels)
    assert len(dataset) > 0

    model = LogisticRegressionBaseline().fit(dataset.X, dataset.y, dataset.feature_names)

    # 4. Run BacktestEngine over the ingested repository data
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
    assert 0.0 <= report.win_rate <= 1.0
