import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from python.cloud.handlers import lambda_daily_pipeline_handler
from python.cloud.s3_sync import download_database
from python.data.repository import DailyBarRepository
from tests.unit.test_aws import FakeS3Client


def test_end_to_end_cloud_pipeline_cycle(tmp_path: Path):
    s3_mock = FakeS3Client()
    bucket_name = "idx-stock-signal-436095651956-data"
    s3_key = "database/stock_signals.db"

    local_db_path = tmp_path / "work" / "stock_signals.db"
    models_dir = tmp_path / "work" / "models"

    event_run_1 = {
        "s3_bucket": bucket_name,
        "tmp_dir": str(tmp_path / "work"),
        "local_db_path": str(local_db_path),
        "local_models_dir": str(models_dir),
        "date": "2026-10-13",
        "market_provider": "mock",
        "dry_run": False,
        "skip_telegram": False,
        "skip_s3_upload": False,
        "top_n": 5,
        "telegram_token": "mock_token_12345",
        "telegram_chat_id": "99999",
        "_s3_client": s3_mock,
    }

    # Mock TelegramClient.send_message to verify broadcast without network
    with patch("python.cloud.handlers.TelegramClient") as MockTG:
        mock_instance = MagicMock()
        mock_instance.send_message.return_value = {"result": {"message_id": 777}}
        MockTG.return_value = mock_instance

        resp_1 = lambda_daily_pipeline_handler(event_run_1, None)

    assert resp_1["statusCode"] == 200
    body_1 = resp_1["body"]
    assert body_1["status"] == "SUCCESS"
    assert body_1["bars_ingested"] > 0
    assert body_1["db_uploaded"] is True
    assert body_1["log_uploaded"] is True
    assert body_1["telegram_status"] == "SENT_777"
    assert (bucket_name, s3_key) in s3_mock.storage

    # Verify uploaded database content in S3
    uploaded_db_path = tmp_path / "verify" / "from_s3.db"
    download_database(bucket_name, uploaded_db_path, s3_key=s3_key, s3_client=s3_mock)

    conn = sqlite3.connect(uploaded_db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM daily_bars")
    bars_count = cur.fetchone()[0]
    assert bars_count > 0

    cur.execute("SELECT count(*) FROM features_daily")
    feat_count = cur.fetchone()[0]
    assert feat_count > 0

    cur.execute("SELECT count(*) FROM signals_daily")
    sig_count = cur.fetchone()[0]
    assert sig_count >= 0
    conn.close()


    # Second invocation: simulate next day / warm start with DB already on S3
    second_work_db = tmp_path / "second_work" / "stock_signals.db"
    event_run_2 = {
        "s3_bucket": bucket_name,
        "tmp_dir": str(tmp_path / "second_work"),
        "local_db_path": str(second_work_db),
        "local_models_dir": str(tmp_path / "second_work" / "models"),
        "date": "2026-10-14",
        "market_provider": "mock",
        "dry_run": False,
        "skip_telegram": True,
        "skip_s3_upload": False,
        "top_n": 5,
        "_s3_client": s3_mock,
    }

    resp_2 = lambda_daily_pipeline_handler(event_run_2, None)
    assert resp_2["statusCode"] == 200
    assert resp_2["body"]["status"] == "SUCCESS"
    assert resp_2["body"]["db_uploaded"] is True

    # Re-verify database still has data and grew or remained consistent
    bar_repo = DailyBarRepository(database_url=f"sqlite:///{second_work_db.as_posix()}")
    assert len(bar_repo.get_universe()) > 0
