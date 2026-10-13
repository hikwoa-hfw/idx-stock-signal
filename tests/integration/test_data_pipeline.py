from pathlib import Path

from python.data.provider import CSVMarketDataProvider, MockMarketDataProvider
from python.data.repository import DailyBarRepository
from python.data.validation import validate_daily_bars
from scripts.ingest_daily import main as ingest_main
from scripts.validate_data import main as validate_main


def test_end_to_end_mock_pipeline(tmp_path: Path):
    db_file = tmp_path / "test_pipeline.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    provider = MockMarketDataProvider(universe=["BBCA", "BBRI"], days=15)
    repo = DailyBarRepository(database_url=db_url)

    for ticker in provider.get_universe():
        bars = provider.get_daily_bars(ticker)
        report = validate_daily_bars(bars, raise_on_error=True)
        assert report.is_valid
        saved = repo.save_bars(bars)
        assert saved == len(bars)

    assert repo.count_bars() > 0
    bbca_bars = repo.get_daily_bars("BBCA")
    assert len(bbca_bars) > 0
    assert bbca_bars[0].ticker == "BBCA"


def test_ingest_and_validate_cli(tmp_path: Path):
    db_file = tmp_path / "cli_pipeline.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # 1. Run ingestion CLI
    ingest_code = ingest_main(
        [
            "--provider",
            "mock",
            "--tickers",
            "BBCA,BMRI",
            "--days",
            "20",
            "--db-url",
            db_url,
        ]
    )
    assert ingest_code == 0

    repo = DailyBarRepository(database_url=db_url)
    assert repo.count_bars("BBCA") > 0
    assert repo.count_bars("BMRI") > 0

    # 2. Run validation CLI on newly created DB
    validate_code = validate_main(["--db-url", db_url])
    assert validate_code == 0

    # 3. Run validation CLI targeting ticker with .JK suffix
    validate_jk_code = validate_main(["--db-url", db_url, "--ticker", "BBCA.JK"])
    assert validate_jk_code == 0


def test_validate_cli_against_csv_datasets(tmp_path: Path):
    csv_dir = tmp_path / "csv_data"
    csv_dir.mkdir(parents=True, exist_ok=True)
    bbca_csv = csv_dir / "BBCA.csv"
    bbca_csv.write_text(
        "ticker,date,open,high,low,close,volume,value\n"
        "BBCA,2026-10-01,10000,10200,9900,10100,500000,5050000000\n"
        "BBCA,2026-10-02,10100,10300,10050,10250,600000,6150000000\n",
        encoding="utf-8",
    )

    provider = CSVMarketDataProvider(data_dir=csv_dir)
    universe = provider.get_universe()
    assert "BBCA" in universe

    code = validate_main(["--csv-dir", str(csv_dir)])
    assert code == 0

    # Verify ingestion CLI with CSV provider
    db_file = tmp_path / "from_csv.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    ingest_code = ingest_main(
        [
            "--provider",
            "csv",
            "--csv-dir",
            str(csv_dir),
            "--db-url",
            db_url,
        ]
    )
    assert ingest_code == 0
    repo = DailyBarRepository(database_url=db_url)
    assert repo.count_bars("BBCA") == 2
