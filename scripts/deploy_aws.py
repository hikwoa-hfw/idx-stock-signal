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
from services.telegram.client import TelegramClient

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
WEBHOOK_FUNCTION_NAME = "idx-telegram-webhook"
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
                sys.stdout.write(
                    f"[deploy_aws] Remote DB already exists at s3://{bucket_name}/{db_key}\n"
                )
            except ClientError:
                s3_client.upload_file(str(local_db), bucket_name, db_key)
                sys.stdout.write(
                    f"[deploy_aws] Initial DB uploaded to s3://{bucket_name}/{db_key}\n"
                )
                uploaded.append(db_key)

    # Model registry artifacts if exist locally
    models_dir = PROJECT_ROOT / "models" / "registry"
    if models_dir.is_dir():
        for f in models_dir.rglob("*"):
            if f.is_file():
                rel_k = f.relative_to(models_dir).as_posix()
                model_k = f"models/{rel_k}"
                if dry_run:
                    sys.stdout.write(
                        f"[DRY-RUN] Upload model {f.name} -> s3://{bucket_name}/{model_k}\n"
                    )
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
        try:
            waiter = lambda_client.get_waiter("function_updated")
            waiter.wait(
                FunctionName=function_name,
                WaiterConfig={"Delay": 2, "MaxAttempts": 30},
            )
        except Exception:
            pass

        sys.stdout.write(f"[deploy_aws] Updating configuration for {function_name}...\n")
        resp = None
        for attempt in range(6):
            try:
                resp = lambda_client.update_function_configuration(
                    FunctionName=function_name,
                    Handler=handler,
                    Role=role_arn,
                    Timeout=timeout,
                    MemorySize=memory_size,
                    Environment={"Variables": env_vars},
                )
                break
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code == "ResourceConflictException" and attempt < 5:
                    time.sleep(2)
                    continue
                raise
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


def ensure_billing_alarm(
    cw_client: Any,
    alarm_name: str,
    threshold: float = 1.0,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        sys.stdout.write(
            f"[DRY-RUN] Ensure CloudWatch Billing Alarm: {alarm_name} "
            f"(Threshold: ${threshold:.2f} USD)\n"
        )
        return True

    sys.stdout.write(
        f"[deploy_aws] Configuring CloudWatch Billing Alarm: {alarm_name} "
        f"(Threshold: ${threshold:.2f} USD)...\n"
    )
    try:
        desc = (
            f"Alarm triggered when estimated AWS monthly charges exceed "
            f"${threshold:.2f} USD (Free Tier Protection)"
        )
        cw_client.put_metric_alarm(
            AlarmName=alarm_name,
            AlarmDescription=desc,
            ActionsEnabled=True,
            MetricName="EstimatedCharges",
            Namespace="AWS/Billing",
            Statistic="Maximum",
            Dimensions=[{"Name": "Currency", "Value": "USD"}],
            Period=21600,
            EvaluationPeriods=1,
            Threshold=threshold,
            ComparisonOperator="GreaterThanOrEqualToThreshold",
        )
        sys.stdout.write(f"[deploy_aws] Billing alarm configured: {alarm_name}\n")
        return True
    except Exception as exc:
        sys.stderr.write(
            f"[deploy_aws] Warning: could not configure billing alarm '{alarm_name}': {exc}\n"
        )
        return False


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
    if "FunctionError" in resp:
        sys.stderr.write(
            f"[deploy_aws] Warning: Lambda invocation returned FunctionError: "
            f"{resp.get('FunctionError')}\n"
        )
    return parsed


def setup_function_url(
    lambda_client: Any,
    function_name: str,
    dry_run: bool = False,
) -> str:
    """Create or retrieve Lambda Function URL with public AuthType: NONE and permissions."""
    if dry_run:
        sys.stdout.write(
            f"[DRY-RUN] Configure public Function URL for '{function_name}' (AuthType: NONE)\n"
        )
        return "https://mock-dryrun.lambda-url.ap-southeast-3.on.aws/"

    sys.stdout.write(f"[deploy_aws] Configuring Function URL for {function_name}...\n")
    url = ""
    try:
        resp = lambda_client.create_function_url_config(
            FunctionName=function_name,
            AuthType="NONE",
            Cors={
                "AllowOrigins": ["*"],
                "AllowMethods": ["POST", "GET"],
                "AllowHeaders": ["content-type", "x-telegram-bot-api-secret-token"],
            },
        )
        url = str(resp.get("FunctionUrl", ""))
        sys.stdout.write(f"[deploy_aws] Created Function URL: {url}\n")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "ResourceConflictException":
            resp = lambda_client.get_function_url_config(FunctionName=function_name)
            url = str(resp.get("FunctionUrl", ""))
            sys.stdout.write(f"[deploy_aws] Existing Function URL found: {url}\n")
        else:
            raise

    try:
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId="FunctionURLAllowPublicAccess",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
        sys.stdout.write(
            f"[deploy_aws] Granted public InvokeFunctionUrl permission on {function_name}\n"
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code != "ResourceConflictException":
            raise

    return url


def setup_api_gateway_http_api(
    apigw_client: Any,
    lambda_client: Any,
    function_name: str,
    function_arn: str,
    region: str = DEFAULT_REGION,
    dry_run: bool = False,
) -> str:
    """Create or retrieve API Gateway HTTP API (v2) route pointing to Webhook Lambda function."""
    api_name = f"{function_name}-api"
    if dry_run:
        sys.stdout.write(
            f"[DRY-RUN] Provision API Gateway HTTP API '{api_name}' -> {function_name}\n"
        )
        return f"https://mock-dryrun.execute-api.{region}.amazonaws.com/webhook"

    sys.stdout.write(f"[deploy_aws] Configuring API Gateway HTTP API for {function_name}...\n")
    api_id = None
    api_endpoint = ""
    try:
        apis = apigw_client.get_apis()
        for item in apis.get("Items", []):
            if item.get("Name") == api_name:
                api_id = item.get("ApiId")
                api_endpoint = item.get("ApiEndpoint", "")
                sys.stdout.write(
                    f"[deploy_aws] Existing HTTP API found: {api_id} ({api_endpoint})\n"
                )
                break
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Note checking existing APIs: {exc}\n")

    if not api_id:
        resp = apigw_client.create_api(
            Name=api_name,
            ProtocolType="HTTP",
            Description=f"Telegram Webhook API for {function_name}",
        )
        api_id = resp["ApiId"]
        api_endpoint = resp.get("ApiEndpoint", "")
        sys.stdout.write(f"[deploy_aws] Created HTTP API: {api_id} ({api_endpoint})\n")

    if not api_endpoint:
        api_endpoint = f"https://{api_id}.execute-api.{region}.amazonaws.com"

    # Ensure Integration exists
    integration_id = None
    try:
        integrations = apigw_client.get_integrations(ApiId=api_id).get("Items", [])
        for integ in integrations:
            uri = integ.get("IntegrationUri", "")
            if uri == function_arn or uri.endswith(f":function:{function_name}"):
                integration_id = integ.get("IntegrationId")
                break
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Note checking integrations: {exc}\n")

    if not integration_id:
        integ_resp = apigw_client.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationMethod="POST",
            IntegrationUri=function_arn,
            PayloadFormatVersion="2.0",
            TimeoutInMillis=30000,
        )
        integration_id = integ_resp["IntegrationId"]
        sys.stdout.write(f"[deploy_aws] Created API Gateway integration: {integration_id}\n")

    # Ensure Route exists
    has_webhook_route = False
    try:
        routes = apigw_client.get_routes(ApiId=api_id).get("Items", [])
        for r in routes:
            if r.get("RouteKey") == "POST /webhook":
                has_webhook_route = True
                break
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Note checking routes: {exc}\n")

    if not has_webhook_route:
        apigw_client.create_route(
            ApiId=api_id,
            RouteKey="POST /webhook",
            Target=f"integrations/{integration_id}",
        )
        sys.stdout.write(
            f"[deploy_aws] Created route POST /webhook -> integrations/{integration_id}\n"
        )

    # Ensure $default stage exists and auto-deploys
    try:
        stages = apigw_client.get_stages(ApiId=api_id).get("Items", [])
        stage_exists = any(s.get("StageName") == "$default" for s in stages)
        if not stage_exists:
            apigw_client.create_stage(
                ApiId=api_id,
                StageName="$default",
                AutoDeploy=True,
            )
            sys.stdout.write("[deploy_aws] Created $default stage with AutoDeploy\n")
    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Note checking stages: {exc}\n")

    # Ensure Lambda permission for API Gateway
    try:
        account_id = function_arn.split(":")[4] if len(function_arn.split(":")) > 4 else "*"
        source_arn = f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/*/webhook"
        stmt_id = f"APIGatewayInvokePermission-{api_id}"
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId=stmt_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn,
        )
        sys.stdout.write(f"[deploy_aws] Granted API Gateway invoke permission on {function_name}\n")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code != "ResourceConflictException":
            pass

    webhook_url = f"{api_endpoint.rstrip('/')}/webhook"
    sys.stdout.write(f"[deploy_aws] HTTP API Webhook URL: {webhook_url}\n")
    return webhook_url


def register_telegram_webhook(
    bot_token: str,
    webhook_url: str,
    secret_token: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register Lambda Function URL with Telegram Bot API setWebhook."""
    clean_url = str(webhook_url)
    if dry_run:
        sys.stdout.write(f"[DRY-RUN] Telegram setWebhook -> url: {clean_url}\n")
        return {"ok": True, "result": True, "description": "Webhook set (dry-run)"}

    sys.stdout.write(f"[deploy_aws] Registering Telegram webhook: {clean_url}...\n")
    client = TelegramClient(bot_token=bot_token)
    resp = client.set_webhook(url=clean_url, secret_token=secret_token)
    sys.stdout.write(f"[deploy_aws] Telegram setWebhook response: {json.dumps(resp)}\n")
    try:
        cmd_resp = client.set_my_commands()
        sys.stdout.write(f"[deploy_aws] Telegram setMyCommands response: {json.dumps(cmd_resp)}\n")
    except Exception as cmd_err:
        sys.stdout.write(f"[deploy_aws] Warning: Could not register Telegram commands: {cmd_err}\n")
    return resp


def get_telegram_webhook_status(
    bot_token: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Retrieve current Telegram webhook status via getWebhookInfo."""
    if dry_run:
        return {"ok": True, "result": {"url": "https://dryrun.lambda-url.ap-southeast-3.on.aws"}}
    client = TelegramClient(bot_token=bot_token)
    return client.get_webhook_info()


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
        "--deploy-alarm",
        action="store_true",
        help="Deploy or update CloudWatch billing alert alarm.",
    )
    parser.add_argument(
        "--set-webhook",
        action="store_true",
        help="Register Lambda Function URL with Telegram setWebhook API.",
    )
    parser.add_argument(
        "--skip-set-webhook",
        action="store_true",
        help="Skip automatic registration of Telegram webhook during deploy.",
    )
    parser.add_argument(
        "--webhook-status",
        action="store_true",
        help="Query Telegram getWebhookInfo status.",
    )
    parser.add_argument(
        "--webhook-type",
        choices=["apigw", "function_url", "both"],
        default="apigw",
        help="Webhook endpoint type: 'apigw' (API Gateway, default), 'function_url', or 'both'.",
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
        "--stage",
        choices=["dev", "development", "staging", "prod", "production"],
        default="staging",
        help="Deployment stage environment (default: staging).",
    )
    parser.add_argument(
        "--role-name",
        default=DEFAULT_ROLE_NAME,
        help="IAM role name for Lambda functions.",
    )

    args = parser.parse_args(argv)

    region = args.region or os.getenv("AWS_REGION") or settings.aws_region or DEFAULT_REGION
    bucket = args.bucket or os.getenv("S3_BUCKET") or settings.s3_bucket or DEFAULT_BUCKET

    stage_raw = (args.stage or "staging").strip().lower()
    if stage_raw in ("dev", "development"):
        stage_name = "development"
        stage_suffix = "-dev"
    elif stage_raw in ("staging",):
        stage_name = "staging"
        stage_suffix = "-staging"
    else:
        stage_name = "production"
        stage_suffix = ""

    daily_func = f"{DAILY_FUNCTION_NAME}{stage_suffix}"
    retrain_func = f"{RETRAIN_FUNCTION_NAME}{stage_suffix}"
    webhook_func = f"{WEBHOOK_FUNCTION_NAME}{stage_suffix}"
    schedule_rule = f"{SCHEDULE_RULE_NAME}{stage_suffix}"
    effective_role_name = (
        args.role_name
        if args.role_name != DEFAULT_ROLE_NAME
        else f"{DEFAULT_ROLE_NAME}{stage_suffix}"
    )

    if (
        not args.create_bucket
        and not args.deploy_lambda
        and not args.test_invoke
        and not args.deploy_alarm
        and not args.set_webhook
        and not args.webhook_status
    ):
        # Default behavior: run full deploy sequence
        args.create_bucket = True
        args.deploy_lambda = True
        args.deploy_alarm = True

    try:
        session = boto3.Session(region_name=region)
        s3_client = session.client("s3")
        iam_client = session.client("iam")
        lambda_client = session.client("lambda")
        events_client = session.client("events")
        apigw_client = session.client("apigatewayv2")

        sys.stdout.write(
            f"[deploy_aws] Initializing deployment to AWS (Stage: {stage_name}, "
            f"Region: {region}, Bucket: {bucket})\n"
        )

        # 1. Bucket and seeds
        if args.create_bucket:
            ensure_s3_bucket(s3_client, bucket, region, dry_run=args.dry_run)
            seed_s3_data(s3_client, bucket, dry_run=args.dry_run)

        # 2. Deploy Lambda and Schedules
        if args.deploy_lambda:
            role_arn = ensure_iam_role(
                iam_client, effective_role_name, bucket, dry_run=args.dry_run
            )
            sys.stdout.write("[deploy_aws] Packaging application zip...\n")
            zip_bytes = build_lambda_zip()
            sys.stdout.write(f"[deploy_aws] Zip package built: {len(zip_bytes) / 1024:.1f} KB\n")

            tg_tok = os.getenv("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token or ""
            tg_chat = os.getenv("TELEGRAM_CHAT_ID") or settings.telegram_chat_id or ""
            env_vars = {
                "APP_ENV": stage_name,
                "S3_BUCKET": bucket,
                "TELEGRAM_BOT_TOKEN": tg_tok,
                "TELEGRAM_CHAT_ID": tg_chat,
                "MARKET_DATA_PROVIDER": "yfinance",
                "DATABASE_URL": "sqlite:////tmp/stock_signals.db",
                "MODEL_REGISTRY_PATH": "/tmp/models",
                "PYTHONPATH": ".",
            }

            daily_arn = deploy_lambda_function(
                lambda_client=lambda_client,
                function_name=daily_func,
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
                function_name=retrain_func,
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
                rule_name=schedule_rule,
                schedule_cron=SCHEDULE_CRON,
                lambda_arn=daily_arn,
                function_name=daily_func,
                dry_run=args.dry_run,
            )

            # Deploy Webhook Lambda and Function URL / API Gateway
            webhook_arn = deploy_lambda_function(
                lambda_client=lambda_client,
                function_name=webhook_func,
                handler="python.cloud.handlers.lambda_telegram_webhook_handler",
                role_arn=role_arn,
                zip_bytes=zip_bytes,
                env_vars=env_vars,
                timeout=30,
                memory_size=512,
                dry_run=args.dry_run,
            )

            webhook_url = ""
            if args.webhook_type in ("apigw", "both"):
                webhook_url = setup_api_gateway_http_api(
                    apigw_client=apigw_client,
                    lambda_client=lambda_client,
                    function_name=webhook_func,
                    function_arn=webhook_arn,
                    region=region,
                    dry_run=args.dry_run,
                )

            if args.webhook_type in ("function_url", "both"):
                fn_url = setup_function_url(
                    lambda_client=lambda_client,
                    function_name=webhook_func,
                    dry_run=args.dry_run,
                )
                if not webhook_url:
                    webhook_url = fn_url

            if tg_tok and webhook_url and not args.skip_set_webhook:
                register_telegram_webhook(
                    bot_token=tg_tok,
                    webhook_url=webhook_url,
                    dry_run=args.dry_run,
                )

        # 3. CloudWatch Billing Metric Alarm
        if args.deploy_alarm:
            billing_alarm_name = f"idx-stock-signal-billing-alert-{stage_name}"
            # AWS Billing metrics only live in us-east-1
            try:
                cw_us = session.client("cloudwatch", region_name="us-east-1")
                ensure_billing_alarm(cw_us, billing_alarm_name, threshold=1.0, dry_run=args.dry_run)
            except Exception as cw_err:
                sys.stderr.write(f"[deploy_aws] Note: CloudWatch us-east-1 unavailable: {cw_err}\n")

            if region != "us-east-1":
                try:
                    cw_reg = session.client("cloudwatch", region_name=region)
                    ensure_billing_alarm(
                        cw_reg, billing_alarm_name, threshold=1.0, dry_run=args.dry_run
                    )
                except Exception as cw_err:
                    sys.stderr.write(
                        f"[deploy_aws] Note: CloudWatch {region} unavailable: {cw_err}\n"
                    )

        # 4. Standalone set-webhook or webhook-status
        if args.set_webhook and not args.deploy_lambda:
            tg_tok = os.getenv("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token or ""
            webhook_url = ""
            if args.webhook_type in ("apigw", "both"):
                if args.dry_run:
                    webhook_arn = f"arn:aws:lambda:{region}:436095651956:function:{webhook_func}"
                else:
                    fn_info = lambda_client.get_function(FunctionName=webhook_func)
                    webhook_arn = fn_info["Configuration"]["FunctionArn"]
                webhook_url = setup_api_gateway_http_api(
                    apigw_client=apigw_client,
                    lambda_client=lambda_client,
                    function_name=webhook_func,
                    function_arn=webhook_arn,
                    region=region,
                    dry_run=args.dry_run,
                )

            if args.webhook_type in ("function_url", "both"):
                fn_url = setup_function_url(
                    lambda_client=lambda_client,
                    function_name=webhook_func,
                    dry_run=args.dry_run,
                )
                if not webhook_url:
                    webhook_url = fn_url

            if tg_tok and webhook_url:
                register_telegram_webhook(
                    bot_token=tg_tok,
                    webhook_url=webhook_url,
                    dry_run=args.dry_run,
                )

        if args.webhook_status:
            tg_tok = os.getenv("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token or ""
            if tg_tok:
                info = get_telegram_webhook_status(tg_tok, dry_run=args.dry_run)
                formatted_info = json.dumps(info, indent=2)
                sys.stdout.write(f"[deploy_aws] Telegram Webhook Info:\n{formatted_info}\n")
            else:
                sys.stderr.write("[deploy_aws] Error: TELEGRAM_BOT_TOKEN not configured.\n")

        # 5. Test invocation
        if args.test_invoke:
            invoke_lambda_dry_run(lambda_client, daily_func)

        sys.stdout.write("[deploy_aws] Deployment completed successfully.\n")
        return 0

    except Exception as exc:
        sys.stderr.write(f"[deploy_aws] Deployment failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
