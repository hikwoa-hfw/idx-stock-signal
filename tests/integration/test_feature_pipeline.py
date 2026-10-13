from datetime import date
from pathlib import Path

from python.config.settings import PROJECT_ROOT
from python.data.provider import CSVMarketDataProvider
from python.data.repository import DailyBarRepository
from python.features.engine import FEATURE_VERSION, FeatureEngine
from python.features.repository import FeatureRepository
from scripts.build_features import run_build_features


def test_end_to_end_feature_pipeline_with_csv(tmp_path: Path):
    db_file = tmp_path / "test_pipeline.db"
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

    # 2. Run feature engine directly on DB bars
    universe_bars = {tk: bar_repo.get_daily_bars(tk) for tk in bar_repo.get_universe()}
    engine = FeatureEngine()
    features = engine.compute_universe_features(universe_bars)

    assert len(features) == 5
    for tk, recs in features.items():
        assert len(recs) == 29
        # Check that latest bar has all required rolling features
        latest = recs[-1]
        assert latest.ticker == tk
        assert latest.feature_version == FEATURE_VERSION
        assert latest.return_1d is not None
        assert latest.return_5d is not None
        assert latest.return_20d is not None
        assert latest.ema20 is not None
        assert latest.rsi14 is not None
        assert latest.atr14 is not None
        assert latest.volume_ratio_20d is not None
        assert latest.rel_strength_ihsg_20d is not None
        assert latest.market_breadth is not None

    # 3. Test saving features via FeatureRepository
    feat_repo = FeatureRepository(database_url=db_url)
    all_recs = [r for recs in features.values() for r in recs]
    saved_count = feat_repo.save_features(all_recs)
    assert saved_count == len(all_recs)
    assert feat_repo.count_features() == len(all_recs)

    # 4. Query feature matrix
    matrix = feat_repo.get_feature_matrix(
        tickers=["BBCA", "TLKM"],
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 10),
    )
    assert len(matrix) > 0
    for m in matrix:
        assert m.ticker in ("BBCA", "TLKM")
        assert m.date >= date(2026, 10, 1)

    # 5. CLI runner helper test
    cli_result = run_build_features(
        tickers=["BBCA"],
        provider_name="sqlite",
        db_url=db_url,
        save_db=False,
        out_format="table",
        limit=5,
    )
    assert "BBCA" in cli_result
