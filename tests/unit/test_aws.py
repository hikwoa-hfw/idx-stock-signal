import io
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from python.cloud.handlers import (
    lambda_daily_pipeline_handler,
    lambda_retraining_handler,
    lambda_telegram_webhook_handler,
)
from python.cloud.s3_sync import (
    bootstrap_database,
    compute_file_md5,
    compute_file_sha256,
    download_database,
    sync_models_from_s3,
    sync_models_to_s3,
    upload_database,
)
from scripts.deploy_aws import (
    build_lambda_zip,
    deploy_lambda_function,
    ensure_billing_alarm,
    ensure_iam_role,
    ensure_s3_bucket,
    get_telegram_webhook_status,
    invoke_lambda_dry_run,
    register_telegram_webhook,
    seed_s3_data,
    setup_api_gateway_http_api,
    setup_eventbridge_schedule,
    setup_function_url,
)
from scripts.deploy_aws import (
    main as deploy_main,
)


class FakeS3Client:
    def __init__(self):
        self.storage: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict] = {}

    def head_object(self, Bucket: str, Key: str):
        if (Bucket, Key) not in self.storage:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        return {
            "Metadata": self.metadata.get((Bucket, Key), {}),
            "ContentLength": len(self.storage[(Bucket, Key)]),
        }

    def download_file(self, Bucket: str, Key: str, Filename: str):
        if (Bucket, Key) not in self.storage:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}},
                "DownloadFile",
            )
        Path(Filename).write_bytes(self.storage[(Bucket, Key)])

    def get_object(self, Bucket: str, Key: str):
        if (Bucket, Key) not in self.storage:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.storage[(Bucket, Key)])}

    def upload_file(self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict = None):
        content = Path(Filename).read_bytes()
        self.storage[(Bucket, Key)] = content
        if ExtraArgs and "Metadata" in ExtraArgs:
            self.metadata[(Bucket, Key)] = ExtraArgs["Metadata"]

    def put_object(self, Bucket: str, Key: str, Body: bytes = b"", ContentType: str = "", **kwargs):
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.storage[(Bucket, Key)] = Body

    def copy_object(
        self,
        Bucket: str,
        CopySource: dict,
        Key: str,
        Metadata: dict = None,
        MetadataDirective: str = None,
    ):

        src_bucket = CopySource["Bucket"]
        src_key = CopySource["Key"]
        if (src_bucket, src_key) not in self.storage:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Source key not found"}},
                "CopyObject",
            )
        self.storage[(Bucket, Key)] = self.storage[(src_bucket, src_key)]
        if Metadata:
            self.metadata[(Bucket, Key)] = Metadata

    def list_objects_v2(self, Bucket: str, Prefix: str = ""):
        contents = []
        for (b, k) in self.storage:
            if b == Bucket and k.startswith(Prefix):
                contents.append({"Key": k, "Size": len(self.storage[(b, k)])})
        return {"Contents": contents}


def test_compute_hashes(tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Indonesian Stock Signal AI")

    sha256_val = compute_file_sha256(test_file)
    md5_val = compute_file_md5(test_file)

    assert isinstance(sha256_val, str)
    assert len(sha256_val) == 64
    assert isinstance(md5_val, str)
    assert len(md5_val) == 32


def test_bootstrap_database(tmp_path: Path):
    db_file = tmp_path / "bootstrapped.db"
    res = bootstrap_database(db_file)

    assert Path(res).is_file()
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "daily_bars" in tables
    assert "signals_daily" in tables
    assert "outcomes_daily" in tables
    assert "positions_journal" in tables


def test_download_database_exists(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    key = "database/stock_signals.db"

    # Pre-populate s3 with fake db bytes
    s3.storage[(bucket, key)] = b"SQLite format 3\x00 fake db content"

    dest = tmp_path / "downloaded.db"
    downloaded = download_database(bucket, dest, s3_key=key, s3_client=s3)

    assert downloaded is True
    assert dest.is_file()
    assert dest.read_bytes() == b"SQLite format 3\x00 fake db content"


def test_download_database_missing_triggers_bootstrap(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    key = "database/stock_signals.db"

    dest = tmp_path / "bootstrapped_from_s3.db"
    downloaded = download_database(bucket, dest, s3_key=key, s3_client=s3)

    assert downloaded is False
    assert dest.is_file()

    conn = sqlite3.connect(dest)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "daily_bars" in tables


def test_upload_database_success_and_backup(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    key = "database/stock_signals.db"

    local_db = tmp_path / "local.db"
    bootstrap_database(local_db)

    meta = upload_database(bucket, local_db, s3_key=key, create_backup=True, s3_client=s3)

    assert meta["s3_bucket"] == bucket
    assert meta["s3_key"] == key
    assert len(meta["sha256"]) == 64
    assert meta["backup_key"] is not None
    assert meta["backup_key"].startswith("database/backups/stock_signals_")

    assert (bucket, key) in s3.storage
    assert (bucket, meta["backup_key"]) in s3.storage
    assert s3.storage[(bucket, key)] == local_db.read_bytes()


def test_upload_database_nonexistent_file(tmp_path: Path):
    s3 = FakeS3Client()
    with pytest.raises(FileNotFoundError):
        upload_database("bucket", tmp_path / "nonexistent.db", s3_client=s3)


def test_upload_database_wal_checkpoint(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    key = "database/stock_signals.db"

    local_db = tmp_path / "wal_test.db"
    conn = sqlite3.connect(local_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE sample (id INT)")
    conn.execute("INSERT INTO sample VALUES (123)")
    conn.commit()

    meta = upload_database(bucket, local_db, s3_key=key, create_backup=False, s3_client=s3)
    conn.close()

    assert meta["s3_bucket"] == bucket
    assert (bucket, key) in s3.storage
    dest_verify = tmp_path / "restored.db"
    dest_verify.write_bytes(s3.storage[(bucket, key)])
    c2 = sqlite3.connect(dest_verify)
    row = c2.execute("SELECT id FROM sample").fetchone()
    c2.close()
    assert row[0] == 123


def test_sync_models_from_and_to_s3(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"

    # 1. Create local model artifacts and sync TO s3
    local_source = tmp_path / "models_source"
    local_source.mkdir()
    (local_source / "champ.joblib").write_bytes(b"champion model binary")
    (local_source / "meta.json").write_text('{"version": "v1"}')

    sub_dir = local_source / "sub"
    sub_dir.mkdir()
    (sub_dir / "challenger.joblib").write_bytes(b"challenger model binary")

    uploaded_keys = sync_models_to_s3(bucket, local_source, s3_prefix="models/", s3_client=s3)
    assert len(uploaded_keys) == 3
    assert "models/champ.joblib" in uploaded_keys
    assert "models/sub/challenger.joblib" in uploaded_keys

    # 2. Sync FROM s3 to fresh target directory
    local_target = tmp_path / "models_dest"
    downloaded_keys = sync_models_from_s3(bucket, local_target, s3_prefix="models/", s3_client=s3)

    assert len(downloaded_keys) == 3
    assert (local_target / "champ.joblib").read_bytes() == b"champion model binary"
    assert (local_target / "sub" / "challenger.joblib").read_bytes() == b"challenger model binary"


def test_lambda_daily_pipeline_handler_success(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"

    event = {
        "s3_bucket": bucket,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "daily_test.db"),
        "local_models_dir": str(tmp_path / "models"),
        "market_provider": "mock",
        "dry_run": True,
        "skip_telegram": True,
        "skip_s3_upload": False,
        "top_n": 3,
        "_s3_client": s3,
    }

    resp = lambda_daily_pipeline_handler(event, None)

    assert resp["statusCode"] == 200
    body = resp["body"]
    assert body["status"] == "SUCCESS"
    assert body["bars_ingested"] > 0
    assert body["db_uploaded"] is True
    assert body["log_uploaded"] is True
    assert (bucket, "database/stock_signals.db") in s3.storage
    assert any(k.startswith("logs/daily_pipeline_") for (b, k) in s3.storage if b == bucket)

    conn = sqlite3.connect(tmp_path / "daily_test.db")
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM features_daily")
    feat_count = cur.fetchone()[0]
    conn.close()
    assert feat_count > 0


def test_lambda_daily_pipeline_handler_error_handling():
    # Pass invalid path or trigger exception
    event = {
        "local_db_path": "",
        "s3_bucket": None,
        "market_provider": "invalid_unknown_provider_xyz",
        "skip_telegram": True,
    }
    resp = lambda_daily_pipeline_handler(event, None)
    assert resp["statusCode"] == 500
    assert resp["body"]["status"] == "FAILED"
    assert "error" in resp["body"]


def test_lambda_retraining_handler_skipped(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"

    event = {
        "s3_bucket": bucket,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "retrain_test.db"),
        "local_models_dir": str(tmp_path / "models"),
        "force": False,
        "min_matured": 500,
        "_s3_client": s3,
    }

    resp = lambda_retraining_handler(event, None)
    assert resp["statusCode"] == 200
    assert resp["body"]["status"] == "SKIPPED"
    assert resp["body"]["triggered"] is False


def test_lambda_retraining_handler_promoted(tmp_path: Path):
    from python.retraining.pipeline import RetrainingPipelineResult

    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "challenger.joblib").write_bytes(b"dummy challenger model")

    mock_result = RetrainingPipelineResult(
        status="SUCCESS",
        triggered=True,
        promoted=True,
        challenger_version="challenger_lgb_20261013",
        champion_version="champion_lgb_20261001",
        artifact_path=str(models_dir / "challenger.joblib"),
    )

    with patch("python.cloud.handlers.RetrainingPipeline.run", return_value=mock_result):
        event = {
            "s3_bucket": bucket,
            "tmp_dir": str(tmp_path),
            "local_db_path": str(tmp_path / "retrain_promoted.db"),
            "local_models_dir": str(models_dir),
            "force": True,
            "auto_promote": True,
            "_s3_client": s3,
        }
        resp = lambda_retraining_handler(event, None)

    assert resp["statusCode"] == 200
    body = resp["body"]
    assert body["status"] == "SUCCESS"
    assert body["promoted"] is True
    assert body["challenger_version"] == "challenger_lgb_20261013"
    assert body["models_synced_count"] > 0
    assert (bucket, "database/stock_signals.db") in s3.storage
    assert (bucket, "models/challenger.joblib") in s3.storage


def test_build_lambda_zip():
    zip_bytes = build_lambda_zip()
    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert any("python/cloud/handlers.py" in n for n in names)
        assert any("python/cloud/s3_sync.py" in n for n in names)
        assert any("configs/universe/seed_universe.csv" in n for n in names)
        assert not any("__pycache__" in n for n in names)


def test_deploy_aws_dry_run():
    # Test deploy_aws.py CLI with --dry-run
    ret = deploy_main(["--dry-run", "--bucket", "test-bucket", "--region", "ap-southeast-3"])
    assert ret == 0


def test_deploy_aws_helpers():
    mock_s3 = MagicMock()
    mock_iam = MagicMock()
    mock_lambda = MagicMock()
    mock_events = MagicMock()

    # S3 helper
    mock_s3.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
    res = ensure_s3_bucket(mock_s3, "test-bucket", "ap-southeast-3", dry_run=False)
    assert res is True
    mock_s3.create_bucket.assert_called_once()
    seed_res = seed_s3_data(mock_s3, "test-bucket", dry_run=True)
    assert isinstance(seed_res, list)

    # IAM helper
    mock_iam.get_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/test-role"}}
    arn = ensure_iam_role(mock_iam, "test-role", "test-bucket", dry_run=False)
    assert arn == "arn:aws:iam::123:role/test-role"

    # Lambda deploy helper
    mock_lambda.get_function.return_value = {
        "Configuration": {"FunctionArn": "arn:aws:lambda:123:func"}
    }
    mock_lambda.update_function_configuration.return_value = {
        "FunctionArn": "arn:aws:lambda:123:func"
    }
    func_arn = deploy_lambda_function(
        lambda_client=mock_lambda,
        function_name="idx-daily-pipeline",
        handler="python.cloud.handlers.lambda_daily_pipeline_handler",
        role_arn="arn:aws:iam::123:role/test-role",
        zip_bytes=b"PK\x05\x06fake",
        env_vars={"ENV": "test"},
        dry_run=False,
    )
    assert func_arn == "arn:aws:lambda:123:func"


    # EventBridge helper
    mock_events.put_rule.return_value = {"RuleArn": "arn:aws:events:123:rule/test"}
    setup_eventbridge_schedule(
        events_client=mock_events,
        lambda_client=mock_lambda,
        rule_name="rule1",
        schedule_cron="cron(30 9 ? * MON-FRI *)",
        lambda_arn=func_arn,
        function_name="idx-daily-pipeline",
        dry_run=False,
    )
    mock_events.put_targets.assert_called_once()

    # Invoke test helper
    mock_lambda.invoke.return_value = {"Payload": io.BytesIO(b'{"status": "SUCCESS"}')}
    inv_res = invoke_lambda_dry_run(mock_lambda, "idx-daily-pipeline")
    assert inv_res == {"status": "SUCCESS"}


def test_mask_sensitive_error():
    from python.cloud.handlers import mask_sensitive_error

    err_text = (
        "Error in bot8774288238:AAEXsM9ivOv6AeTCzoNgsVRSoEFkS0QRJwQ with "
        "AKIAIOSFODNN7EXAMPLE credentials"
    )
    masked = mask_sensitive_error(err_text)
    assert "8774288238:AAEXsM9ivOv6AeTCzoNgsVRSoEFkS0QRJwQ" not in masked
    assert "bot***:***" in masked or "***:***" in masked
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "AKIA***" in masked


def test_dispatch_failure_alert():
    from python.cloud.handlers import dispatch_failure_alert

    # Suppressed on dry_run / skip_telegram
    res_dry = dispatch_failure_alert("Error 1", event={"dry_run": True})
    assert res_dry is False

    # Dispatched when tokens present
    with patch("python.cloud.handlers.TelegramClient") as MockTG:
        mock_instance = MagicMock()
        MockTG.return_value = mock_instance
        res = dispatch_failure_alert(
            error_msg="Database connection timeout",
            stage="test_stage",
            event={
                "dry_run": False,
                "skip_telegram": False,
                "telegram_token": "mock_token",
                "telegram_chat_id": "12345",
            },
        )
        assert res is True
        mock_instance.send_message.assert_called_once()
        args, kwargs = mock_instance.send_message.call_args
        sent_text = kwargs.get("text", "")
        assert "BEI Stock Signal Failure" in sent_text
        assert "Database connection timeout" in sent_text


def test_duplicate_run_protection_db(tmp_path: Path):
    from datetime import date

    from python.common.types import SignalRecord
    from python.signals.repository import SignalRepository

    db_path = tmp_path / "dup_test.db"
    bootstrap_database(db_path)
    db_url = f"sqlite:///{db_path.as_posix()}"
    sig_repo = SignalRepository(database_url=db_url)

    target_d = date(2026, 10, 13)
    sig_record = SignalRecord(
        signal_id="sig_test_1",
        ticker="BBCA",
        signal_date=target_d,
        signal="BUY",
        entry_low=9900.0,
        entry_high=10100.0,
        tp_price=10500.0,
        sl_price=9700.0,
        max_holding_days=10,
        predicted_probability=0.8,
        expected_return=0.05,
        score=0.8,
        model_version="champ_v1",
    )
    sig_repo.save_signals([sig_record])

    event = {
        "s3_bucket": None,
        "local_db_path": str(db_path),
        "tmp_dir": str(tmp_path),
        "date": "2026-10-13",
        "force_rerun": False,
        "dry_run": True,
        "skip_telegram": True,
        "skip_s3_upload": True,
    }

    # 1. Without force_rerun: must skip
    resp = lambda_daily_pipeline_handler(event, None)
    assert resp["statusCode"] == 200
    assert resp["body"]["status"] == "SKIPPED_DUPLICATE"
    assert resp["body"]["signals_count"] == 1

    # 2. With force_rerun: must proceed
    event_force = dict(event)
    event_force["force_rerun"] = True
    event_force["market_provider"] = "mock"
    resp_force = lambda_daily_pipeline_handler(event_force, None)
    assert resp_force["statusCode"] == 200
    assert resp_force["body"]["status"] == "SUCCESS"


def test_duplicate_run_protection_s3_log(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-bucket"
    s3.storage[(bucket, "logs/daily_pipeline_2026-10-13_120000.json")] = (
        b'{"status": "SUCCESS"}'
    )

    event = {
        "s3_bucket": bucket,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "s3_dup.db"),
        "date": "2026-10-13",
        "force_rerun": False,
        "strict_duplicate_check": True,
        "_s3_client": s3,
    }

    resp = lambda_daily_pipeline_handler(event, None)
    assert resp["statusCode"] == 200
    assert resp["body"]["status"] == "SKIPPED_DUPLICATE"


def test_market_provider_failure_retry_and_alert(tmp_path: Path):
    call_count = 0

    def mock_failing_ingest(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Provider API rate limited")

    with patch("python.cloud.handlers.run_ingest", side_effect=mock_failing_ingest), \
         patch("python.cloud.handlers.dispatch_failure_alert") as mock_alert:

        event = {
            "s3_bucket": None,
            "tmp_dir": str(tmp_path),
            "local_db_path": str(tmp_path / "retry_test.db"),
            "max_retries": 3,
            "backoff_base": 0.01,
            "backoff_factor": 2.0,
            "dry_run": True,
            "skip_telegram": True,
            "skip_s3_upload": True,
        }
        resp = lambda_daily_pipeline_handler(event, None)

        assert call_count == 3
        mock_alert.assert_called()
        assert resp["statusCode"] == 500
        assert resp["body"]["status"] == "FAILED"


def test_deploy_aws_stage_support():
    mock_s3 = MagicMock()
    mock_iam = MagicMock()
    mock_lambda = MagicMock()
    mock_events = MagicMock()

    mock_lambda.get_function.return_value = {"Configuration": {"FunctionArn": "arn:func"}}
    mock_lambda.update_function_configuration.return_value = {"FunctionArn": "arn:func"}
    mock_lambda.create_function_url_config.return_value = {"FunctionUrl": "https://func.url"}
    mock_iam.get_role.return_value = {"Role": {"Arn": "arn:role"}}
    mock_events.put_rule.return_value = {"RuleArn": "arn:rule"}

    mock_cw = MagicMock()
    mock_apigw = MagicMock()
    mock_apigw.get_apis.return_value = {"Items": []}
    mock_apigw.create_api.return_value = {
        "ApiId": "api-staging",
        "ApiEndpoint": "https://api-staging.execute-api.ap-southeast-3.amazonaws.com",
    }
    mock_apigw.get_integrations.return_value = {"Items": []}
    mock_apigw.create_integration.return_value = {"IntegrationId": "int-staging"}
    mock_apigw.get_routes.return_value = {"Items": []}
    mock_apigw.get_stages.return_value = {"Items": []}

    with patch("boto3.Session") as MockSession, patch(
        "scripts.deploy_aws.register_telegram_webhook", return_value={"ok": True}
    ):
        mock_sess = MagicMock()
        mock_sess.client.side_effect = lambda svc, **kwargs: {
            "s3": mock_s3,
            "iam": mock_iam,
            "lambda": mock_lambda,
            "events": mock_events,
            "cloudwatch": mock_cw,
            "apigatewayv2": mock_apigw,
        }[svc]
        MockSession.return_value = mock_sess

        ret = deploy_main([
            "--stage", "staging",
            "--deploy-lambda",
            "--bucket", "test-b",
            "--region", "ap-southeast-3",
        ])
        assert ret == 0
        call_names = [
            call.kwargs.get("FunctionName")
            for call in mock_lambda.update_function_code.call_args_list
        ]
        assert "idx-daily-pipeline-staging" in call_names
        assert "idx-retraining-pipeline-staging" in call_names
        assert "idx-telegram-webhook-staging" in call_names


def test_ensure_billing_alarm():
    mock_cw = MagicMock()
    # Dry run
    res_dry = ensure_billing_alarm(mock_cw, "alarm-dry", threshold=1.0, dry_run=True)
    assert res_dry is True
    mock_cw.put_metric_alarm.assert_not_called()

    # Live call
    res_live = ensure_billing_alarm(mock_cw, "alarm-staging", threshold=1.0, dry_run=False)
    assert res_live is True
    mock_cw.put_metric_alarm.assert_called_once()
    _, kwargs = mock_cw.put_metric_alarm.call_args
    assert kwargs["AlarmName"] == "alarm-staging"
    assert kwargs["MetricName"] == "EstimatedCharges"
    assert kwargs["Namespace"] == "AWS/Billing"
    assert kwargs["Threshold"] == 1.0


def test_duplicate_run_protection_job_recovery_vs_duplicate(tmp_path: Path):
    s3 = FakeS3Client()
    bucket = "idx-test-recovery"

    # 1. Previous run was FAILED -> job recovery should proceed (NOT skipped)
    s3.storage[(bucket, "logs/daily_pipeline_2026-10-13_110000.json")] = (
        b'{"status": "FAILED", "error": "Timeout"}'
    )
    event = {
        "s3_bucket": bucket,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "recovery.db"),
        "date": "2026-10-13",
        "force_rerun": False,
        "market_provider": "mock",
        "dry_run": True,
        "skip_telegram": True,
        "skip_s3_upload": True,
        "_s3_client": s3,
    }
    resp_recovery = lambda_daily_pipeline_handler(event, None)
    assert resp_recovery["statusCode"] == 200
    assert resp_recovery["body"]["status"] == "SUCCESS"

    # 2. Previous run was SUCCESS -> must skip as duplicate
    s3.storage[(bucket, "logs/daily_pipeline_2026-10-13_120000.json")] = (
        b'{"status": "SUCCESS"}'
    )
    resp_dup = lambda_daily_pipeline_handler(event, None)
    assert resp_dup["statusCode"] == 200
    assert resp_dup["body"]["status"] == "SKIPPED_DUPLICATE"

    # 3. With force_rerun=True -> must execute despite SUCCESS
    event_force = dict(event)
    event_force["force_rerun"] = True
    resp_forced = lambda_daily_pipeline_handler(event_force, None)
    assert resp_forced["statusCode"] == 200
    assert resp_forced["body"]["status"] == "SUCCESS"


def test_lambda_retraining_handler_failure_alert(tmp_path: Path):
    with patch("python.cloud.handlers.RetrainingPipeline") as MockPipe, \
         patch("python.cloud.handlers.dispatch_failure_alert") as mock_alert:
        mock_instance = MagicMock()
        mock_instance.run.side_effect = RuntimeError("GPU out of memory")
        MockPipe.return_value = mock_instance

        event = {
            "s3_bucket": None,
            "tmp_dir": str(tmp_path),
            "local_db_path": str(tmp_path / "retrain_fail.db"),
            "local_models_dir": str(tmp_path / "models"),
            "dry_run": False,
            "skip_telegram": False,
        }
        resp = lambda_retraining_handler(event, None)
        assert resp["statusCode"] == 500
        assert resp["body"]["status"] == "FAILED"
        mock_alert.assert_called_once()
        _, kwargs = mock_alert.call_args
        assert kwargs["stage"] == "retraining_pipeline"
        assert "GPU out of memory" in kwargs["error_msg"]


def test_lambda_telegram_webhook_handler_help_command(tmp_path: Path):
    import json

    event = {
        "body": json.dumps({
            "update_id": 100,
            "message": {
                "chat": {"id": 12345},
                "text": "/help",
            },
        }),
        "allowed_chat_id": "12345",
        "skip_telegram": True,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    resp = lambda_telegram_webhook_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert "BEI Daily Stock Signal Bot" in body["reply"]


def test_lambda_telegram_webhook_handler_unauthorized(tmp_path: Path):
    import json

    event = {
        "body": json.dumps({
            "update_id": 101,
            "message": {
                "chat": {"id": 99999},
                "text": "/daily",
            },
        }),
        "allowed_chat_id": "12345",
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    resp = lambda_telegram_webhook_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ignored"
    assert body["reason"] == "unauthorized"


def test_lambda_telegram_webhook_handler_secret_token(tmp_path: Path, monkeypatch):
    import json

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "supersecret123")

    # 1. Invalid secret token
    event_invalid = {
        "headers": {"x-telegram-bot-api-secret-token": "wrongtoken"},
        "body": json.dumps({"message": {"chat": {"id": 12345}, "text": "/help"}}),
        "allowed_chat_id": "12345",
    }
    resp_inv = lambda_telegram_webhook_handler(event_invalid, None)
    assert resp_inv["statusCode"] == 200
    assert json.loads(resp_inv["body"])["status"] == "ignored"
    assert json.loads(resp_inv["body"])["reason"] == "invalid_secret"

    # 2. Valid secret token
    event_valid = {
        "headers": {"x-telegram-bot-api-secret-token": "supersecret123"},
        "body": json.dumps({"message": {"chat": {"id": 12345}, "text": "/help"}}),
        "allowed_chat_id": "12345",
        "skip_telegram": True,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    resp_val = lambda_telegram_webhook_handler(event_valid, None)
    assert resp_val["statusCode"] == 200
    assert json.loads(resp_val["body"])["status"] == "ok"


def test_lambda_telegram_webhook_handler_empty_text(tmp_path: Path):
    import json

    event = {
        "body": json.dumps({
            "update_id": 102,
            "message": {"chat": {"id": 12345}},
        }),
        "allowed_chat_id": "12345",
    }
    resp = lambda_telegram_webhook_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["message"] == "no_text"


def test_lambda_telegram_webhook_handler_dispatches_telegram_send(tmp_path: Path):
    event = {
        "body": {
            "update_id": 103,
            "message": {"chat": {"id": 12345}, "text": "/model"},
        },
        "allowed_chat_id": "12345",
        "telegram_token": "mock_token_123",
        "skip_telegram": False,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    with patch("python.cloud.handlers.TelegramClient") as MockTG:
        mock_instance = MagicMock()
        MockTG.return_value = mock_instance
        resp = lambda_telegram_webhook_handler(event, None)
        assert resp["statusCode"] == 200
        mock_instance.send_message.assert_called_once()
        _, kwargs = mock_instance.send_message.call_args
        assert "Model" in kwargs["text"] or "model" in kwargs["text"].lower()


def test_lambda_telegram_webhook_handler_position_mutation_uploads_db(tmp_path: Path):
    import json

    s3 = FakeS3Client()
    bucket = "idx-test-webhook-db"
    db_file = tmp_path / "journal_test.db"
    bootstrap_database(db_file)

    event = {
        "body": json.dumps({
            "message": {"chat": {"id": 12345}, "text": "/enter BBCA 10000 100"}
        }),
        "allowed_chat_id": "12345",
        "s3_bucket": bucket,
        "local_db_path": str(db_file),
        "tmp_dir": str(tmp_path),
        "skip_telegram": True,
        "_s3_client": s3,
    }
    resp = lambda_telegram_webhook_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert "Position Opened" in body["reply"]
    assert (bucket, "database/stock_signals.db") in s3.storage


def test_lambda_telegram_webhook_handler_group_user_authorization(tmp_path: Path):
    import json

    event = {
        "body": json.dumps({
            "update_id": 104,
            "message": {
                "chat": {"id": -100987654321, "type": "group"},
                "from": {"id": 12345, "first_name": "Admin"},
                "text": "/help",
            },
        }),
        "allowed_chat_id": "12345",
        "skip_telegram": True,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    resp = lambda_telegram_webhook_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert "BEI Daily Stock Signal Bot" in body["reply"]


def test_lambda_telegram_webhook_handler_fallback_to_webhook_response(tmp_path: Path):
    import json

    event = {
        "body": {
            "update_id": 105,
            "message": {"chat": {"id": 12345}, "text": "/help"},
        },
        "allowed_chat_id": "12345",
        "telegram_token": "mock_token_123",
        "skip_telegram": False,
        "tmp_dir": str(tmp_path),
        "local_db_path": str(tmp_path / "webhook_test.db"),
    }
    with patch("python.cloud.handlers.TelegramClient") as MockTG:
        mock_instance = MagicMock()
        mock_instance.send_message.side_effect = RuntimeError("Upstream 503 Service Unavailable")
        MockTG.return_value = mock_instance

        resp = lambda_telegram_webhook_handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["method"] == "sendMessage"
        assert body["chat_id"] == 12345
        assert "BEI Daily Stock Signal Bot" in body["text"]


def test_setup_function_url_and_telegram_webhook_helpers():
    mock_lambda = MagicMock()
    mock_lambda.create_function_url_config.return_value = {
        "FunctionUrl": "https://test-func-url.lambda-url.ap-southeast-3.on.aws/"
    }

    url = setup_function_url(mock_lambda, "idx-telegram-webhook", dry_run=False)
    assert url == "https://test-func-url.lambda-url.ap-southeast-3.on.aws/"
    mock_lambda.create_function_url_config.assert_called_once()
    mock_lambda.add_permission.assert_called_once()

    dry_url = setup_function_url(mock_lambda, "idx-telegram-webhook", dry_run=True)
    assert "lambda-url" in dry_url

    with patch("scripts.deploy_aws.TelegramClient") as MockTG:
        mock_client = MagicMock()
        mock_client.set_webhook.return_value = {"ok": True, "result": True}
        mock_client.get_webhook_info.return_value = {"ok": True, "result": {"url": url}}
        MockTG.return_value = mock_client

        reg_res = register_telegram_webhook("token123", url, dry_run=False)
        assert reg_res["ok"] is True
        mock_client.set_webhook.assert_called_once_with(url=url, secret_token=None)

        info_res = get_telegram_webhook_status("token123", dry_run=False)
        assert info_res["result"]["url"] == url
        mock_client.get_webhook_info.assert_called_once()


def test_telegram_client_webhook_methods():
    from services.telegram.client import TelegramClient

    client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

    mock_resp = MagicMock()
    mock_resp.read.return_value = (
        b'{"ok": true, "result": true, "description": "Webhook was set"}'
    )
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_set = client.set_webhook(url="https://sample.url")
        assert res_set["ok"] is True

        res_info = client.get_webhook_info()
        assert res_info["ok"] is True

        res_del = client.delete_webhook()
        assert res_del["ok"] is True


def test_setup_api_gateway_http_api_dry_run():
    mock_apigw = MagicMock()
    mock_lambda = MagicMock()
    url = setup_api_gateway_http_api(
        apigw_client=mock_apigw,
        lambda_client=mock_lambda,
        function_name="idx-telegram-webhook",
        function_arn="arn:aws:lambda:ap-southeast-3:123456789012:function:idx-telegram-webhook",
        region="ap-southeast-3",
        dry_run=True,
    )
    assert "execute-api.ap-southeast-3.amazonaws.com/webhook" in url
    mock_apigw.create_api.assert_not_called()
    mock_lambda.add_permission.assert_not_called()


def test_setup_api_gateway_http_api_create_flow():
    mock_apigw = MagicMock()
    mock_apigw.get_apis.return_value = {"Items": []}
    mock_apigw.create_api.return_value = {
        "ApiId": "api123",
        "ApiEndpoint": "https://api123.execute-api.ap-southeast-3.amazonaws.com",
    }
    mock_apigw.get_integrations.return_value = {"Items": []}
    mock_apigw.create_integration.return_value = {"IntegrationId": "integ456"}
    mock_apigw.get_routes.return_value = {"Items": []}
    mock_apigw.get_stages.return_value = {"Items": []}

    mock_lambda = MagicMock()

    fn_arn = "arn:aws:lambda:ap-southeast-3:123456789012:function:idx-telegram-webhook"
    url = setup_api_gateway_http_api(
        apigw_client=mock_apigw,
        lambda_client=mock_lambda,
        function_name="idx-telegram-webhook",
        function_arn=fn_arn,
        region="ap-southeast-3",
        dry_run=False,
    )

    assert url == "https://api123.execute-api.ap-southeast-3.amazonaws.com/webhook"
    mock_apigw.create_api.assert_called_once_with(
        Name="idx-telegram-webhook-api",
        ProtocolType="HTTP",
        Description="Telegram Webhook API for idx-telegram-webhook",
    )
    mock_apigw.create_integration.assert_called_once()
    mock_apigw.create_route.assert_called_once()
    mock_apigw.create_stage.assert_called_once()
    mock_lambda.add_permission.assert_called_once()


def test_setup_api_gateway_http_api_existing_flow():
    mock_apigw = MagicMock()
    mock_apigw.get_apis.return_value = {
        "Items": [
            {
                "Name": "idx-telegram-webhook-api",
                "ApiId": "exist123",
                "ApiEndpoint": "https://exist123.execute-api.ap-southeast-3.amazonaws.com",
            }
        ]
    }
    fn_arn = "arn:aws:lambda:ap-southeast-3:123456789012:function:idx-telegram-webhook"
    mock_apigw.get_integrations.return_value = {
        "Items": [
            {"IntegrationId": "int999", "IntegrationUri": fn_arn}
        ]
    }
    mock_apigw.get_routes.return_value = {
        "Items": [{"RouteKey": "POST /webhook"}]
    }
    mock_apigw.get_stages.return_value = {
        "Items": [{"StageName": "$default"}]
    }

    mock_lambda = MagicMock()
    mock_lambda.add_permission.side_effect = ClientError(
        {"Error": {"Code": "ResourceConflictException", "Message": "Conflict"}},
        "AddPermission",
    )

    url = setup_api_gateway_http_api(
        apigw_client=mock_apigw,
        lambda_client=mock_lambda,
        function_name="idx-telegram-webhook",
        function_arn=fn_arn,
        region="ap-southeast-3",
        dry_run=False,
    )

    assert url == "https://exist123.execute-api.ap-southeast-3.amazonaws.com/webhook"
    mock_apigw.create_api.assert_not_called()
    mock_apigw.create_integration.assert_not_called()
    mock_apigw.create_route.assert_not_called()
    mock_apigw.create_stage.assert_not_called()


def test_deploy_main_webhook_options_dry_run():
    ret = deploy_main([
        "--dry-run",
        "--set-webhook",
        "--webhook-type", "apigw",
        "--stage", "staging",
    ])
    assert ret == 0

    ret_both = deploy_main([
        "--dry-run",
        "--set-webhook",
        "--webhook-type", "both",
        "--stage", "staging",
    ])
    assert ret_both == 0



