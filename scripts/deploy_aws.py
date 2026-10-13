import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
from botocore.exceptions import ClientError

from python.config.settings import PROJECT_ROOT, settings

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_BUCKET = "idx-stock-signal-436095651956-data"
DEFAULT_REGION = "ap-southeast-3"
DEFAULT_ROLE_NAME = "idx-stock-signal-lambda-role"
DAILY_FUNCTION_NAME = "idx-daily-pipeline"
RETRAIN_FUNCTION_NAME = "idx-retraining-pipeline"
SCHEDULE_RULE_NAME = "idx-daily-pipeline-schedule"
SCHEDULE_CRON = "cron(30 9 ? * MON-FRI *)"


def build_lambda_zip() -> bytes:
    buffer = io.BytesIO()
    dirs_to_pack = ["python", "services", "configs", "scripts"]
    skip_exts = {".pyc", ".pyo", ".pyd"}
    skip_dirs = {"__pycache__", ".pytest_cache", ".ruff_cache", ".git", ".venv"}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in dirs_to_pack:
            src_dir = PROJECT_ROOT / folder
            if not src_dir.is_dir():
                continue
            for file_path in src_dir.rglob("*"):
                if file_path.is_file():
                    if any(part in skip_dirs for part in file_path.parts):
                        continue
                    if file_path.suffix in skip_exts:
                        continue
                    arcname = file_path.relative_to(PROJECT_ROOT).as_posix()
                    zf.write(file_path, arcname)

    buffer.seek(0)
    return buffer.getvalue()


def ensure_s3_bucket(
    s3_client: Any,
    bucket_name: str,
    region: str,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        sys.stdout.write(f"[DRY-RUN] Check / create S3 bucket: {bucket_name} in {region}\n")
        return True

    exists = False
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        exists = True
        sys.stdout.write(f"[deploy_aws] S3 bucket already exists: {bucket_name}\n")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchBucket"):
            exists = False
        else:
            raise

    if not exists:
        sys.stdout.write(f"[deploy_aws] Creating S3 bucket: {bucket_name} in {region}...\n")
        params: dict[str, Any] = {"Bucket": bucket_name}
        if region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3_client.create_bucket(**params)
        sys.stdout.write(f"[deploy_aws] Bucket created: {bucket_name}\n")

    # Enable versioning
    try:
        s3_client.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={"Status": "Enabled"},
        )
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Warning: could not enable bucket versioning: {exc}\n")

    # Server-side encryption
    try:
        s3_client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    }
                ]
            },
        )
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Warning: could not enable bucket encryption: {exc}\n")

    # Block public access
    try:
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Warning: could not set public access block: {exc}\n")

    return True


def seed_s3_data(
    s3_client: Any,
    bucket_name: str,
    dry_run: bool = False,
) -> list[str]:
    uploaded = []
    # Seed universe
    universe_path = PROJECT_ROOT / "configs" / "universe" / "seed_universe.csv"
    if universe_path.is_file():
        key = "configs/universe/seed_universe.csv"
        if dry_run:
            sys.stdout.write(f"[DRY-RUN] Upload {universe_path} -> s3://{bucket_name}/{key}\n")
            uploaded.append(key)
        else:
            s3_client.upload_file(str(universe_path), bucket_name, key)
            sys.stdout.write(f"[deploy_aws] Seed universe uploaded to s3://{bucket_name}/{key}\n")
            uploaded.append(key)

    # Database seed if exists locally
    local_db = PROJECT_ROOT / "datasets" / "stock_signals.db"
    if local_db.is_file() and local_db.stat().st_size > 0:
        db_key = "database/stock_signals.db"
        if dry_run:
            sys.stdout.write(f"[DRY-RUN] Upload {local_db} -> s3://{bucket_name}/{db_key}\n")
            uploaded.append(db_key)
        else:
            try:
                s3_client.head_object(Bucket=bucket_name, Key=db_key)
                sys.stdout.write(f"[deploy_aws] Remote DB already exists at s3://{bucket_name}/{db_key}\n")
            except ClientError:
                s3_client.upload_file(str(local_db), bucket_name, db_key)
                sys.stdout.write(f"[deploy_aws] Initial DB uploaded to s3://{bucket_name}/{db_key}\n")
                uploaded.append(db_key)

    # Model registry artifacts if exist locally
    models_dir = PROJECT_ROOT / "models" / "registry"
    if models_dir.is_dir():
        for f in models_dir.rglob("*"):
            if f.is_file():
                rel_k = f.relative_to(models_dir).as_posix()
                model_k = f"models/{rel_k}"
                if dry_run:
                    sys.stdout.write(f"[DRY-RUN] Upload model {f.name} -> s3://{bucket_name}/{model_k}\n")
                    uploaded.append(model_k)
                else:
                    s3_client.upload_file(str(f), bucket_name, model_k)
                    uploaded.append(model_k)

    return uploaded


def ensure_iam_role(
    iam_client: Any,
    role_name: str,
    bucket_name: str,
    dry_run: bool = False,
) -> str:
    if dry_run:
        sys.stdout.write(f"[DRY-RUN] Ensure IAM Role: {role_name}\n")
        return f"arn:aws:iam::436095651956:role/{role_name}"

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    try:
        resp = iam_client.get_role(RoleName=role_name)
        role_arn = resp["Role"]["Arn"]
        sys.stdout.write(f"[deploy_aws] Existing IAM Role found: {role_arn}\n")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "NoSuchEntity":
            sys.stdout.write(f"[deploy_aws] Creating IAM Role: {role_name}...\n")
            create_resp = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Execution role for BEI Stock Signal Lambda functions",
            )
            role_arn = create_resp["Role"]["Arn"]
            sys.stdout.write(f"[deploy_aws] Created IAM Role: {role_arn}\n")
        else:
            raise

    # Attach basic execution managed policy
    try:
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
    except Exception:
        pass

    # Attach least-privilege inline S3 policy
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                    "s3:DeleteObject",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*",
                ],
            }
        ],
    }
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="S3DataBucketAccess",
        PolicyDocument=json.dumps(s3_policy),
    )

    return role_arn


def deploy_lambda_function(
    lambda_client: Any,
    function_name: str,
    handler: str,
    role_arn: str,
    zip_bytes: bytes,
    env_vars: dict[str, str],
    timeout: int = 300,
    memory_size: int = 1536,
    dry_run: bool = False,
) -> str:
    if dry_run:
        sys.stdout.write(
            f"[DRY-RUN] Deploy Lambda '{function_name}' ({handler}, {memory_size}MB, {timeout}s)\n"
        )
        return f"arn:aws:lambda:ap-southeast-3:436095651956:function:{function_name}"

    exists = False
    try:
        lambda_client.get_function(FunctionName=function_name)
        exists = True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "ResourceNotFoundException":
            exists = False
        else:
            raise

    if exists:
        sys.stdout.write(f"[deploy_aws] Updating existing Lambda code for {function_name}...\n")
        lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_bytes,
        )
        sys.stdout.write(f"[deploy_aws] Updating configuration for {function_name}...\n")
        resp = lambda_client.update_function_configuration(
            FunctionName=function_name,
            Handler=handler,
            Role=role_arn,
            Timeout=timeout,
            MemorySize=memory_size,
            Environment={"Variables": env_vars},
        )
        func_arn = resp["FunctionArn"]
    else:
        sys.stdout.write(f"[deploy_aws] Creating new Lambda function: {function_name}...\n")
        func_arn = None
        max_retries = 6
        for attempt in range(max_retries):
            try:
                resp = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler=handler,
                    Code={"ZipFile": zip_bytes},
                    Timeout=timeout,
                    MemorySize=memory_size,
                    Environment={"Variables": env_vars},
                    EphemeralStorage={"Size": 1024},
                    Description="Serverless pipeline function for BEI Stock Signal AI",
                )
                func_arn = resp["FunctionArn"]
                break
            except ClientError as exc:
                err_code = str(exc.response.get("Error", {}).get("Code", ""))
                err_msg = str(exc)
                if (
                    err_code == "InvalidParameterValueException" or "cannot be assumed" in err_msg
                ) and attempt < max_retries - 1:
                    sys.stdout.write(
                        f"[deploy_aws] Waiting IAM role (retry {attempt + 1}/{max_retries})...\n"
                    )
                    time.sleep(3)
                    continue
                raise

    sys.stdout.write(f"[deploy_aws] Deployed Lambda {function_name}: {func_arn}\n")
    return func_arn


def setup_eventbridge_schedule(
    events_client: Any,
    lambda_client: Any,
    rule_name: str,
    schedule_cron: str,
    lambda_arn: str,
    function_name: str,
    dry_run: bool = False,
) -> None:
    if dry_run:
        sys.stdout.write(
            f"[DRY-RUN] Setup EventBridge rule '{rule_name}' -> "
            f"'{schedule_cron}' target {lambda_arn}\n"
        )
        return


    sys.stdout.write(f"[deploy_aws] Configuring EventBridge schedule: {rule_name}...\n")
    rule_resp = events_client.put_rule(
        Name=rule_name,
        ScheduleExpression=schedule_cron,
        State="ENABLED",
        Description="Trigger daily stock signal pipeline Mon-Fri at 16:30 WIB",
    )
    rule_arn = rule_resp["RuleArn"]

    events_client.put_targets(
        Rule=rule_name,
        Targets=[{"Id": "DailyPipelineTarget", "Arn": lambda_arn}],
    )

    try:
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId=f"EventBridgeInvoke-{rule_name}",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
        sys.stdout.write(f"[deploy_aws] Lambda invoke permission granted to rule {rule_name}\n")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "ResourceConflictException":
            pass
        else:
            raise


def invoke_lambda_dry_run(
    lambda_client: Any,
    function_name: str,
) -> dict[str, Any]:
    sys.stdout.write(f"[deploy_aws] Invoking Lambda '{function_name}' in test dry-run mode...\n")
    payload = json.dumps({"dry_run": True, "skip_telegram": True, "skip_s3_upload": True})
    resp = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=payload.encode("utf-8"),
    )
    raw_resp = resp["Payload"].read().decode("utf-8")
    parsed = json.loads(raw_resp)
    sys.stdout.write(f"[deploy_aws] Invocation response: {json.dumps(parsed, indent=2)}\n")
    return parsed



def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy and provision AWS Serverless pipeline for BEI Stock Signal AI."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deployment actions without modifying AWS resources.",
    )
    parser.add_argument(
        "--create-bucket",
        action="store_true",
        help="Create and verify S3 storage bucket.",
    )
    parser.add_argument(
        "--deploy-lambda",
        action="store_true",
        help="Package and deploy Lambda functions and EventBridge schedules.",
    )
    parser.add_argument(
        "--test-invoke",
        action="store_true",
        help="Test invoke daily pipeline Lambda in dry-run mode.",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help=f"Target S3 bucket name (default: {DEFAULT_BUCKET}).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help=f"AWS region (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--role-name",
        default=DEFAULT_ROLE_NAME,
        help="IAM role name for Lambda functions.",
    )

    args = parser.parse_args(argv)

    region = args.region or os.getenv("AWS_REGION") or settings.aws_region or DEFAULT_REGION
    bucket = args.bucket or os.getenv("S3_BUCKET") or settings.s3_bucket or DEFAULT_BUCKET

    if not args.create_bucket and not args.deploy_lambda and not args.test_invoke:
        # Default behavior: run full deploy sequence
        args.create_bucket = True
        args.deploy_lambda = True

    try:
        session = boto3.Session(region_name=region)
        s3_client = session.client("s3")
        iam_client = session.client("iam")
        lambda_client = session.client("lambda")
        events_client = session.client("events")

        sys.stdout.write(
            f"[deploy_aws] Initializing deployment to AWS (Region: {region}, Bucket: {bucket})\n"
        )

        # 1. Bucket and seeds
        if args.create_bucket:
            ensure_s3_bucket(s3_client, bucket, region, dry_run=args.dry_run)
            seed_s3_data(s3_client, bucket, dry_run=args.dry_run)

        # 2. Deploy Lambda and Schedules
        if args.deploy_lambda:
            role_arn = ensure_iam_role(iam_client, args.role_name, bucket, dry_run=args.dry_run)
            sys.stdout.write("[deploy_aws] Packaging application zip...\n")
            zip_bytes = build_lambda_zip()
            sys.stdout.write(f"[deploy_aws] Zip package built: {len(zip_bytes) / 1024:.1f} KB\n")

            tg_tok = (
                os.getenv("TELEGRAM_BOT_TOKEN")
                or settings.telegram_bot_token
                or ""
            )
            tg_chat = (
                os.getenv("TELEGRAM_CHAT_ID")
                or settings.telegram_chat_id
                or ""
            )
            env_vars = {
                "APP_ENV": "production",
                "S3_BUCKET": bucket,
                "AWS_REGION": region,
                "TELEGRAM_BOT_TOKEN": tg_tok,
                "TELEGRAM_CHAT_ID": tg_chat,
                "MARKET_DATA_PROVIDER": "yfinance",
                "DATABASE_URL": "sqlite:////tmp/stock_signals.db",
                "MODEL_REGISTRY_PATH": "/tmp/models",
                "PYTHONPATH": ".",
            }


            daily_arn = deploy_lambda_function(
                lambda_client=lambda_client,
                function_name=DAILY_FUNCTION_NAME,
                handler="python.cloud.handlers.lambda_daily_pipeline_handler",
                role_arn=role_arn,
                zip_bytes=zip_bytes,
                env_vars=env_vars,
                timeout=300,
                memory_size=1536,
                dry_run=args.dry_run,
            )

            deploy_lambda_function(
                lambda_client=lambda_client,
                function_name=RETRAIN_FUNCTION_NAME,
                handler="python.cloud.handlers.lambda_retraining_handler",
                role_arn=role_arn,
                zip_bytes=zip_bytes,
                env_vars=env_vars,
                timeout=600,
                memory_size=2048,
                dry_run=args.dry_run,
            )

            setup_eventbridge_schedule(
                events_client=events_client,
                lambda_client=lambda_client,
                rule_name=SCHEDULE_RULE_NAME,
                schedule_cron=SCHEDULE_CRON,
                lambda_arn=daily_arn,
                function_name=DAILY_FUNCTION_NAME,
                dry_run=args.dry_run,
            )

        # 3. Test invocation
        if args.test_invoke:
            invoke_lambda_dry_run(lambda_client, DAILY_FUNCTION_NAME)


        sys.stdout.write("[deploy_aws] Deployment completed successfully.\n")
        return 0

    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Deployment failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
