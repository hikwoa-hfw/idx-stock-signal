from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from python.cloud.handlers import lambda_daily_pipeline_handler
from python.cloud.s3_sync import bootstrap_database
from python.common.types import SignalRecord
from python.signals.repository import SignalRepository
from tests.unit.test_aws import FakeS3Client


def _assert_no_daily_signals_broadcast(mock_tg: MagicMock) -> None:
    """Ensure no daily stock signal recommendations were broadcast to Telegram."""
    for call_item in mock_tg.send_message.call_args_list:
        text = call_item.kwargs.get("text", "")
        # Only failure alerts are allowed, never signal broadcasts
        assert "DAILY STOCK SIGNALS" not in text
        assert "BUY" not in text or "ALERT" in text


def test_fail_closed_missing_ingest_dependency(tmp_path: Path):
    with patch("python.cloud.handlers.run_ingest", None):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": None,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(tmp_path / "fail_dep.db"),
                "date": "2026-10-21",
                "force_rerun": True,
                "market_provider": "mock",
                "dry_run": False,
                "skip_telegram": False,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
            }
            resp = lambda_daily_pipeline_handler(event, None)
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert "Missing required serverless dependencies" in resp["body"]["error"]
            _assert_no_daily_signals_broadcast(mock_tg)


def test_fail_closed_provider_failure(tmp_path: Path):
    def mock_fail_ingest(*args, **kwargs):
        raise ConnectionError("Provider upstream 503")

    with patch("python.cloud.handlers.run_ingest", side_effect=mock_fail_ingest):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": None,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(tmp_path / "fail_prov.db"),
                "date": "2026-10-21",
                "market_provider": "mock",
                "force_rerun": True,
                "dry_run": False,
                "skip_telegram": False,
                "max_retries": 1,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
            }
            resp = lambda_daily_pipeline_handler(event, None)
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert "Market data ingestion failed" in resp["body"]["error"]
            _assert_no_daily_signals_broadcast(mock_tg)


def test_fail_closed_zero_bars_and_low_coverage(tmp_path: Path):
    with patch("python.cloud.handlers.run_ingest", return_value=0):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": None,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(tmp_path / "fail_zero.db"),
                "date": "2026-10-21",
                "market_provider": "mock",
                "force_rerun": True,
                "dry_run": False,
                "skip_telegram": False,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
            }
            resp = lambda_daily_pipeline_handler(event, None)
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert "Market data ingestion produced 0 bars" in resp["body"]["error"]
            _assert_no_daily_signals_broadcast(mock_tg)


def test_fail_closed_feature_generation_error(tmp_path: Path):
    with patch(
        "python.cloud.handlers.FeatureEngine.compute_universe_features",
        side_effect=ValueError("Feature NaN corruption"),
    ):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": None,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(tmp_path / "fail_feat.db"),
                "date": "2026-10-13",
                "force_rerun": True,
                "market_provider": "mock",
                "dry_run": False,
                "skip_telegram": False,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
            }
            resp = lambda_daily_pipeline_handler(event, None)
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert "Feature generation error" in resp["body"]["error"]
            _assert_no_daily_signals_broadcast(mock_tg)


def test_fail_closed_scoring_error(tmp_path: Path):
    with patch(
        "python.cloud.handlers.SignalEngine.generate_dual_mode_signals",
        side_effect=RuntimeError("Model prediction error"),
    ):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": None,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(tmp_path / "fail_score.db"),
                "date": "2026-10-13",
                "force_rerun": True,
                "market_provider": "mock",
                "dry_run": False,
                "skip_telegram": False,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
            }
            resp = lambda_daily_pipeline_handler(event, None)
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert "Signal scoring error" in resp["body"]["error"]
            _assert_no_daily_signals_broadcast(mock_tg)


def test_stale_signals_never_broadcast_on_upstream_failure(tmp_path: Path):
    db_path = tmp_path / "stale_test.db"
    bootstrap_database(db_path)
    db_url = f"sqlite:///{db_path.as_posix()}"
    sig_repo = SignalRepository(database_url=db_url)

    # Seed historical signals from 2026-10-16 in the database (replicating staging bug)
    stale_date = date(2026, 10, 16)
    sample_tickers = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
    stale_records = [
        SignalRecord(
            signal_id=f"stale_{t}",
            ticker=t,
            signal_date=stale_date,
            signal="BUY",
            entry_low=9900.0,
            entry_high=10100.0,
            tp_price=10500.0,
            sl_price=9700.0,
            max_holding_days=10,
            predicted_probability=0.85,
            expected_return=0.06,
            score=0.85,
            model_version="champ_v1",
        )
        for t in sample_tickers
    ]
    sig_repo.save_signals(stale_records)

    s3_mock = FakeS3Client()
    bucket = "idx-stale-test-bucket"

    # Simulate run on 2026-10-21 where market ingestion fails
    def mock_fail_ingest(*args, **kwargs):
        raise ConnectionError("Network down")

    with patch("python.cloud.handlers.run_ingest", side_effect=mock_fail_ingest):
        with patch("python.cloud.handlers.TelegramClient") as MockTG:
            mock_tg = MagicMock()
            MockTG.return_value = mock_tg

            event = {
                "s3_bucket": bucket,
                "tmp_dir": str(tmp_path),
                "local_db_path": str(db_path),
                "date": "2026-10-21",
                "market_provider": "yfinance",
                "dry_run": False,
                "skip_telegram": False,
                "max_retries": 1,
                "telegram_token": "tok123",
                "telegram_chat_id": "12345",
                "_s3_client": s3_mock,
            }
            resp = lambda_daily_pipeline_handler(event, None)

            # Must fail closed
            assert resp["statusCode"] == 500
            assert resp["body"]["status"] == "FAILED"
            assert resp["body"]["scoring_success"] is False
            assert resp["body"]["telegram_delivery"] is False

            # Telegram MUST NOT be sent with the stale 2026-10-16 signals!
            _assert_no_daily_signals_broadcast(mock_tg)

            # S3 log uploaded MUST be marked FAILED, NEVER SUCCESS
            uploaded_logs = [
                k for (b, k) in s3_mock.storage if b == bucket and k.startswith("logs/")
            ]
            assert len(uploaded_logs) > 0
            for k in uploaded_logs:
                log_body = s3_mock.storage[(bucket, k)].decode("utf-8")
                assert '"status": "FAILED"' in log_body
                assert '"status": "SUCCESS"' not in log_body


def test_fail_closed_s3_failure_log_with_env_var_bucket(tmp_path: Path, monkeypatch):
    """Verify S3 failure log is written when s3_bucket is configured via env var, not event dict."""
    s3_mock = FakeS3Client()
    bucket = "idx-env-bucket-test"
    monkeypatch.setenv("S3_BUCKET", bucket)

    def mock_fail_ingest(*args, **kwargs):
        raise ConnectionError("Upstream timeout")

    with patch("python.cloud.handlers.run_ingest", side_effect=mock_fail_ingest):
        event = {
            "tmp_dir": str(tmp_path),
            "local_db_path": str(tmp_path / "env_fail.db"),
            "date": "2026-10-21",
            "market_provider": "yfinance",
            "dry_run": False,
            "skip_telegram": True,
            "skip_s3_upload": False,
            "max_retries": 1,
            "_s3_client": s3_mock,
        }
        resp = lambda_daily_pipeline_handler(event, None)
        assert resp["statusCode"] == 500
        assert resp["body"]["status"] == "FAILED"

        uploaded_logs = [
            k for (b, k) in s3_mock.storage if b == bucket and k.startswith("logs/")
        ]
        assert len(uploaded_logs) > 0, (
            "Failure log must be uploaded to S3 even when bucket is in env var"
        )
        log_body = s3_mock.storage[(bucket, uploaded_logs[0])].decode("utf-8")
        assert '"status": "FAILED"' in log_body

