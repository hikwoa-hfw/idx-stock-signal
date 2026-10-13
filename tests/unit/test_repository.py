import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from python.common.types import DailyBar, IngestionRun, IngestionTickerStatus
from python.data.repository import DailyBarRepository


def _sample_bar(ticker: str, bar_date: date, close: float = 1000.0) -> DailyBar:
    return DailyBar(
        ticker=ticker,
        date=bar_date,
        open=close - 10,
        high=close + 20,
        low=close - 20,
        close=close,
        volume=50000.0,
        value=close * 50000.0,
    )


def test_repository_save_and_query_memory():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    bars = [
        _sample_bar("BBCA", date(2026, 10, 1), 10000.0),
        _sample_bar("BBCA", date(2026, 10, 2), 10100.0),
        _sample_bar("BBRI", date(2026, 10, 1), 5000.0),
    ]

    saved = repo.save_bars(bars)
    assert saved == 3
    assert repo.count_bars() == 3
    assert repo.count_bars("BBCA") == 2
    assert repo.count_bars("BBRI") == 1

    queried_bbca = repo.get_daily_bars("BBCA")
    assert len(queried_bbca) == 2
    assert queried_bbca[0].date == date(2026, 10, 1)
    assert queried_bbca[1].date == date(2026, 10, 2)
    assert queried_bbca[0].close == 10000.0


def test_repository_upsert_prevents_duplicate():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    bar1 = _sample_bar("BBCA", date(2026, 10, 1), 10000.0)
    repo.save_bars([bar1])
    assert repo.count_bars("BBCA") == 1

    bar1_updated = _sample_bar("BBCA", date(2026, 10, 1), 10500.0)
    repo.save_bars([bar1_updated])
    assert repo.count_bars("BBCA") == 1

    queried = repo.get_daily_bars("BBCA")
    assert len(queried) == 1
    assert queried[0].close == 10500.0


def test_repository_date_range_filter():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    bars = [
        _sample_bar("TLKM", date(2026, 10, 1)),
        _sample_bar("TLKM", date(2026, 10, 2)),
        _sample_bar("TLKM", date(2026, 10, 3)),
        _sample_bar("TLKM", date(2026, 10, 4)),
    ]
    repo.save_bars(bars)

    filtered = repo.get_daily_bars(
        "TLKM",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 3),
    )
    assert len(filtered) == 2
    assert [b.date for b in filtered] == [date(2026, 10, 2), date(2026, 10, 3)]


def test_repository_file_based_persistence(tmp_path: Path):
    db_file = tmp_path / "test_stock.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    repo1 = DailyBarRepository(database_url=db_url)
    repo1.save_bars([_sample_bar("ASII", date(2026, 10, 1), 5200.0)])
    assert repo1.count_bars() == 1

    # Open separate repository connection on same file
    repo2 = DailyBarRepository(database_url=db_url)
    assert repo2.count_bars() == 1
    assert repo2.get_latest_date("ASII") == date(2026, 10, 1)
    assert repo2.get_universe() == ["ASII"]

    deleted = repo2.delete_bars("ASII")
    assert deleted == 1
    assert repo2.count_bars() == 0


def test_repository_edge_cases():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    assert repo.save_bars([]) == 0
    assert repo.get_latest_date("NONEXISTENT") is None
    assert repo.get_universe() == []
    assert repo.count_bars() == 0

    repo.save_bars([_sample_bar("BMRI", date(2026, 10, 5))])
    # inverted date range
    assert (
        repo.get_daily_bars(
            "BMRI",
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 1),
        )
        == []
    )


def test_repository_jk_suffix_equivalence():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    bar = _sample_bar("BBCA", date(2026, 10, 1), 10000.0)
    repo.save_bars([bar])

    # Query with .JK
    bars_jk = repo.get_daily_bars("BBCA.JK")
    assert len(bars_jk) == 1
    assert bars_jk[0].date == date(2026, 10, 1)

    # Count with .JK
    assert repo.count_bars("BBCA.JK") == 1
    assert repo.get_latest_date("BBCA.JK") == date(2026, 10, 1)

    # Delete with .JK
    assert repo.delete_bars("BBCA.JK") == 1
    assert repo.count_bars() == 0


def test_repository_implements_market_data_provider_protocol():
    from python.data.provider import MarketDataProvider

    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    assert isinstance(repo, MarketDataProvider)
    assert "BBCA" in repo.get_sector_data()


def test_repository_schema_migration_v1_to_v2(tmp_path: Path):
    db_file = tmp_path / "v1_legacy.db"
    # Create legacy table manually
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE daily_bars (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            value REAL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (ticker, date)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO daily_bars (
            ticker, date, open, high, low, close, volume, value, created_at
        ) VALUES (
            'BBCA', '2026-10-01', 10000, 10200, 9900, 10100, 500000, 5050000000,
            '2026-10-01T00:00:00'
        )
        """
    )
    conn.commit()
    conn.close()

    # Open with DailyBarRepository -> migration runs
    repo = DailyBarRepository(database_url=f"sqlite:///{db_file.as_posix()}")
    assert repo.count_bars("BBCA") == 1
    bars = repo.get_daily_bars("BBCA")
    assert len(bars) == 1
    assert bars[0].close == 10100.0
    assert bars[0].interval == "1d"
    assert bars[0].provider == "unknown"


def test_repository_multi_provider_unique_keys():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    bar_mock = _sample_bar("BBCA", date(2026, 10, 1), 10000.0)
    bar_yf = _sample_bar("BBCA", date(2026, 10, 1), 10050.0)

    repo.save_bars([bar_mock], provider="mock")
    repo.save_bars([bar_yf], provider="yfinance")

    assert repo.count_bars("BBCA") == 2
    assert repo.count_bars("BBCA", provider="mock") == 1
    assert repo.count_bars("BBCA", provider="yfinance") == 1

    mock_bars = repo.get_daily_bars("BBCA", provider="mock")
    yf_bars = repo.get_daily_bars("BBCA", provider="yfinance")
    assert len(mock_bars) == 1 and mock_bars[0].close == 10000.0
    assert len(yf_bars) == 1 and yf_bars[0].close == 10050.0


def test_repository_save_bars_detailed_tracking():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    b1 = _sample_bar("BBCA", date(2026, 10, 1), 10000.0)
    b2 = _sample_bar("BBCA", date(2026, 10, 2), 10100.0)

    # First insert: 2 inserted
    res1 = repo.save_bars_detailed([b1, b2], default_provider="yfinance")
    assert res1 == {"inserted": 2, "updated": 0, "unchanged": 0}

    # Second insert with same data: 2 unchanged
    res2 = repo.save_bars_detailed([b1, b2], default_provider="yfinance")
    assert res2 == {"inserted": 0, "updated": 0, "unchanged": 2}

    # Third insert with 1 updated
    b2_mod = _sample_bar("BBCA", date(2026, 10, 2), 10200.0)
    res3 = repo.save_bars_detailed([b2_mod], default_provider="yfinance")
    assert res3 == {"inserted": 0, "updated": 1, "unchanged": 0}


def test_repository_audit_ingestion_runs_and_ticker_statuses():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    run = IngestionRun(
        id="run_test_001",
        provider="yfinance",
        job_type="incremental",
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
        tickers_requested=2,
    )
    repo.create_ingestion_run(run)

    queried_run = repo.get_ingestion_run("run_test_001")
    assert queried_run is not None
    assert queried_run.status == "RUNNING"
    assert queried_run.tickers_requested == 2

    # Record ticker status
    t_status = IngestionTickerStatus(
        id="run_test_001_BBCA",
        ingestion_run_id="run_test_001",
        ticker="BBCA",
        status="SUCCESS",
        rows_received=10,
        rows_inserted=8,
        rows_updated=2,
        first_date_received=date(2026, 10, 1),
        last_date_received=date(2026, 10, 10),
    )
    repo.record_ticker_status(t_status)

    statuses = repo.get_ticker_statuses("run_test_001")
    assert len(statuses) == 1
    assert statuses[0].ticker == "BBCA"
    assert statuses[0].rows_inserted == 8

    # Update run
    repo.update_ingestion_run(
        "run_test_001",
        finished_at=datetime.now(timezone.utc),
        status="SUCCESS",
        tickers_succeeded=1,
        rows_inserted=8,
        rows_updated=2,
    )
    updated_run = repo.get_ingestion_run("run_test_001")
    assert updated_run.status == "SUCCESS"
    assert updated_run.rows_inserted == 8


def test_repository_corporate_actions_change_detected_and_updated():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    b1 = DailyBar(
        ticker="BBCA",
        date=date(2026, 10, 1),
        open=10000.0,
        high=10200.0,
        low=9900.0,
        close=10100.0,
        volume=500000.0,
        dividends=0.0,
        stock_splits=0.0,
        provider="yfinance",
    )
    res1 = repo.save_bars_detailed([b1], default_provider="yfinance")
    assert res1 == {"inserted": 1, "updated": 0, "unchanged": 0}

    # Second save with dividend updated to 150.0
    b1_div = DailyBar(
        ticker="BBCA",
        date=date(2026, 10, 1),
        open=10000.0,
        high=10200.0,
        low=9900.0,
        close=10100.0,
        volume=500000.0,
        dividends=150.0,
        stock_splits=0.0,
        provider="yfinance",
    )
    res2 = repo.save_bars_detailed([b1_div], default_provider="yfinance")
    assert res2 == {"inserted": 0, "updated": 1, "unchanged": 0}

    queried = repo.get_daily_bars("BBCA")
    assert len(queried) == 1
    assert queried[0].dividends == 150.0


def test_repository_row_hash_persisted_and_queried():
    repo = DailyBarRepository(database_url="sqlite:///:memory:")
    b = DailyBar(
        ticker="BMRI",
        date=date(2026, 10, 1),
        open=6500.0,
        high=6600.0,
        low=6450.0,
        close=6550.0,
        volume=300000.0,
        provider="yfinance",
    )
    repo.save_bars([b])
    queried = repo.get_daily_bars("BMRI")
    assert len(queried) == 1
    assert queried[0].row_hash is not None
    assert queried[0].row_hash == b.row_hash
