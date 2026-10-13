from pathlib import Path

from python.config.settings import PROJECT_ROOT
from python.data.provider import CSVMarketDataProvider
from python.data.repository import DailyBarRepository
from python.labels.engine import LABEL_VERSION, LabelEngine
from python.labels.repository import LabelRepository
from scripts.build_labels import run_build_labels


def test_end_to_end_label_pipeline_with_csv(tmp_path: Path):
    db_file = tmp_path / "test_label_pipeline.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # 1. Ingest sample CSVs into test DB
    raw_dir = PROJECT_ROOT / "datasets" / "raw"
    csv_provider = CSVMarketDataProvider(data_dir=raw_dir)
    bar_repo = DailyBarRepository(database_url=db_url)

    total_bars = 0
    for tk in csv_provider.get_universe():
        bars = csv_provider.get_daily_bars(tk)
        total_bars += bar_repo.save_bars(bars)

    assert total_bars > 0
    assert bar_repo.count_bars() == total_bars

    # 2. Run label engine directly on DB bars
    universe_bars = {tk: bar_repo.get_daily_bars(tk) for tk in bar_repo.get_universe()}
    engine = LabelEngine(tp_pct=0.05, sl_pct=0.02, max_holding_days=10)
    labels = engine.compute_universe_labels(universe_bars)

    assert len(labels) == 5
    for tk, recs in labels.items():
        assert len(recs) > 0
        for r in recs:
            assert r.ticker == tk
            assert r.label_version == LABEL_VERSION
            assert r.outcome in ("TP", "SL", "EXPIRY", "AMBIGUOUS")
            if r.outcome == "TP":
                assert r.binary_target == 1
            else:
                assert r.binary_target == 0
            assert r.mfe >= r.mae
            assert 1 <= r.holding_days <= 10

    # 3. Test saving labels via LabelRepository
    label_repo = LabelRepository(database_url=db_url)
    all_recs = [r for recs in labels.values() for r in recs]
    saved_count = label_repo.save_labels(all_recs)
    assert saved_count == len(all_recs)
    assert label_repo.count_labels() == len(all_recs)

    # 4. Test run_build_labels CLI function on sqlite provider
    cli_labels = run_build_labels(
        tickers=["BBCA", "BMRI"],
        provider_name="sqlite",
        db_url=db_url,
        save_db=True,
        out_format="json",
        max_holding_days=10,
    )
    assert "BBCA" in cli_labels
    assert "BMRI" in cli_labels
