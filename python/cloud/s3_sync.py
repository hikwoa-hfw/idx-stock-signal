import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import boto3
from botocore.exceptions import ClientError

from python.config.settings import settings
from python.data.repository import DailyBarRepository
from python.features.repository import FeatureRepository
from python.journal.repository import PositionJournalRepository
from python.labels.repository import LabelRepository
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    path = Path(file_path)
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_file_md5(file_path: Union[str, Path]) -> str:
    path = Path(file_path)
    hasher = hashlib.md5()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_s3_client(client: Optional[Any] = None) -> Any:
    if client is not None:
        return client
    region = os.getenv("AWS_REGION") or settings.aws_region or "ap-southeast-3"
    try:
        from botocore.config import Config

        cfg = Config(
            retries={"max_attempts": 10, "mode": "adaptive"},
            connect_timeout=60,
            read_timeout=120,
        )
        return boto3.client("s3", region_name=region, config=cfg)
    except Exception:
        return boto3.client("s3", region_name=region)


def bootstrap_database(local_path: Union[str, Path]) -> str:
    path = Path(local_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{path.as_posix()}"

    DailyBarRepository(database_url=db_url)
    FeatureRepository(database_url=db_url)
    LabelRepository(database_url=db_url)
    SignalRepository(database_url=db_url)
    OutcomeRepository(database_url=db_url)
    PositionJournalRepository(database_url=db_url)
    return str(path)


def download_database(
    s3_bucket: str,
    local_path: Union[str, Path],
    s3_key: str = "database/stock_signals.db",
    s3_client: Optional[Any] = None,
    conditional: bool = False,
) -> bool:
    target_path = Path(local_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    client = _get_s3_client(s3_client)

    try:
        head_resp = client.head_object(Bucket=s3_bucket, Key=s3_key)
        remote_size = head_resp.get("ContentLength")
        remote_etag = head_resp.get("ETag")
        remote_mtime = head_resp.get("LastModified")
        remote_sha = head_resp.get("Metadata", {}).get("sha256")

        meta_path = target_path.with_name(f"{target_path.name}.meta.json")

        if conditional and target_path.is_file() and target_path.stat().st_size >= 16:
            is_valid_sqlite = False
            try:
                with open(target_path, "rb") as f:
                    is_valid_sqlite = f.read(16) == b"SQLite format 3\x00"
            except Exception:
                is_valid_sqlite = False

            if is_valid_sqlite:
                local_size = target_path.stat().st_size
                if remote_size is None or local_size == remote_size:
                    is_fresh = False
                    cached_meta = None
                    if meta_path.is_file():
                        try:
                            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        except Exception:
                            cached_meta = None

                    if cached_meta:
                        if remote_etag and cached_meta.get("etag") == remote_etag:
                            is_fresh = True
                        elif remote_sha and cached_meta.get("sha256") == remote_sha:
                            is_fresh = True
                        elif remote_mtime and cached_meta.get("last_modified") == str(remote_mtime):
                            is_fresh = True

                    if not is_fresh and remote_sha:
                        if compute_file_sha256(target_path) == remote_sha:
                            is_fresh = True

                    if is_fresh:
                        if not meta_path.is_file():
                            try:
                                meta_data = {
                                    "etag": remote_etag,
                                    "last_modified": str(remote_mtime) if remote_mtime else None,
                                    "size_bytes": local_size,
                                    "sha256": remote_sha or (
                                        cached_meta.get("sha256") if cached_meta else None
                                    ),
                                }
                                meta_path.write_text(json.dumps(meta_data), encoding="utf-8")
                            except Exception:
                                pass
                        return True

        client.download_file(s3_bucket, s3_key, str(target_path))
        if not target_path.exists() or target_path.stat().st_size == 0:
            bootstrap_database(target_path)
            return False
        local_sha = None
        if remote_sha:
            local_sha = compute_file_sha256(target_path)
            if local_sha != remote_sha:
                bootstrap_database(target_path)
                return False

        try:
            meta_data = {
                "etag": remote_etag,
                "last_modified": str(remote_mtime) if remote_mtime else None,
                "size_bytes": target_path.stat().st_size,
                "sha256": remote_sha or local_sha,
            }
            meta_path.write_text(json.dumps(meta_data), encoding="utf-8")
        except Exception:
            pass

        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("404", "NoSuchKey", "NotFound") or status == 404:
            bootstrap_database(target_path)
            return False
        raise


def upload_database(
    s3_bucket: str,
    local_path: Union[str, Path],
    s3_key: str = "database/stock_signals.db",
    create_backup: bool = True,
    s3_client: Optional[Any] = None,
) -> dict[str, Any]:
    source_path = Path(local_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Local database file not found: {source_path}")

    try:
        conn = sqlite3.connect(str(source_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()
    except Exception:
        pass

    sha256_hash = compute_file_sha256(source_path)
    md5_hash = compute_file_md5(source_path)
    size_bytes = source_path.stat().st_size
    client = _get_s3_client(s3_client)

    metadata = {
        "sha256": sha256_hash,
        "md5": md5_hash,
        "size_bytes": str(size_bytes),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    extra_upload_args: dict[str, Any] = {}
    try:
        import inspect

        from boto3.s3.transfer import TransferConfig

        sig = inspect.signature(client.upload_file)
        if "Config" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            extra_upload_args["Config"] = TransferConfig(
                multipart_threshold=250 * 1024 * 1024,
                max_concurrency=2,
                use_threads=False,
            )
    except Exception:
        pass

    client.upload_file(
        str(source_path),
        s3_bucket,
        s3_key,
        ExtraArgs={"Metadata": metadata},
        **extra_upload_args,
    )

    try:
        head_resp = client.head_object(Bucket=s3_bucket, Key=s3_key)
        remote_meta = head_resp.get("Metadata", {})
        if remote_meta.get("sha256") and remote_meta.get("sha256") != sha256_hash:
            raise ValueError(
                f"S3 upload verification failed: SHA-256 mismatch for s3://{s3_bucket}/{s3_key}"
            )
        if "ContentLength" in head_resp and head_resp["ContentLength"] != size_bytes:
            raise ValueError(
                f"S3 upload verification failed: size mismatch for s3://{s3_bucket}/{s3_key}"
            )
        meta_path = source_path.with_name(f"{source_path.name}.meta.json")
        try:
            meta_data = {
                "etag": head_resp.get("ETag"),
                "last_modified": (
                    str(head_resp.get("LastModified")) if head_resp.get("LastModified") else None
                ),
                "size_bytes": size_bytes,
                "sha256": sha256_hash,
            }
            meta_path.write_text(json.dumps(meta_data), encoding="utf-8")
        except Exception:
            pass
    except ClientError:
        pass

    backup_key = None
    if create_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_key = f"database/backups/stock_signals_{ts}.db"
        client.copy_object(
            Bucket=s3_bucket,
            CopySource={"Bucket": s3_bucket, "Key": s3_key},
            Key=backup_key,
            Metadata=metadata,
            MetadataDirective="REPLACE",
        )

    return {
        "s3_bucket": s3_bucket,
        "s3_key": s3_key,
        "sha256": sha256_hash,
        "md5": md5_hash,
        "size_bytes": size_bytes,
        "backup_key": backup_key,
    }


def sync_models_from_s3(
    s3_bucket: str,
    local_dir: Union[str, Path],
    s3_prefix: str = "models/",
    s3_client: Optional[Any] = None,
) -> list[str]:
    target_dir = Path(local_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    client = _get_s3_client(s3_client)

    normalized_prefix = s3_prefix.lstrip("/")
    downloaded: list[str] = []

    has_paginator = hasattr(client, "get_paginator")
    paginator = client.get_paginator("list_objects_v2") if has_paginator else None

    if paginator:
        page_iterator = paginator.paginate(Bucket=s3_bucket, Prefix=normalized_prefix)
        for page in page_iterator:
            for item in page.get("Contents", []):
                key = item["Key"]
                if key.endswith("/"):
                    continue
                rel_path = key[len(normalized_prefix) :].lstrip("/")
                dest_file = target_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                remote_size = item.get("Size")
                if (
                    dest_file.is_file()
                    and remote_size is not None
                    and dest_file.stat().st_size == remote_size
                ):
                    downloaded.append(key)
                    continue
                client.download_file(s3_bucket, key, str(dest_file))
                downloaded.append(key)
    else:
        resp = client.list_objects_v2(Bucket=s3_bucket, Prefix=normalized_prefix)
        for item in resp.get("Contents", []):
            key = item["Key"]
            if key.endswith("/"):
                continue
            rel_path = key[len(normalized_prefix) :].lstrip("/")
            dest_file = target_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            remote_size = item.get("Size")
            if (
                dest_file.is_file()
                and remote_size is not None
                and dest_file.stat().st_size == remote_size
            ):
                downloaded.append(key)
                continue
            client.download_file(s3_bucket, key, str(dest_file))
            downloaded.append(key)

    return downloaded


def sync_models_to_s3(
    s3_bucket: str,
    local_dir: Union[str, Path],
    s3_prefix: str = "models/",
    s3_client: Optional[Any] = None,
) -> list[str]:
    source_dir = Path(local_dir).resolve()
    if not source_dir.is_dir():
        return []

    client = _get_s3_client(s3_client)
    clean_prefix = s3_prefix.strip("/")
    prefix = f"{clean_prefix}/" if clean_prefix else ""
    uploaded: list[str] = []

    for item in sorted(source_dir.rglob("*")):
        if item.is_file():
            rel_str = item.relative_to(source_dir).as_posix()
            key = f"{prefix}{rel_str}"
            client.upload_file(str(item), s3_bucket, key)
            uploaded.append(key)

    return uploaded
