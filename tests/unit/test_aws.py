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
    ensure_iam_role,
    ensure_s3_bucket,
    invoke_lambda_dry_run,
    seed_s3_data,
    setup_eventbridge_schedule,
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

