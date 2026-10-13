import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from python.cloud.s3_sync import (
    _get_s3_client,
    bootstrap_database,
    download_database,
    sync_models_from_s3,
    sync_models_to_s3,
    upload_database,
)
from python.common.types import SignalConfig
from python.config.settings import settings
from python.data.provider import DEFAULT_UNIVERSE, load_universe
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.features.repository import FeatureRepository
from python.labels.repository import LabelRepository
from python.models.registry import ModelRegistry
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.retraining.dataset import RetrainingDatasetAssembler
from python.retraining.gate import PromotionGateManager
from python.retraining.pipeline import RetrainingPipeline, RetrainingPipelineConfig
from python.retraining.trigger import RetrainingTriggerConfig, RetrainingTriggerEvaluator
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository
from scripts.ingest_daily import run_ingest
from services.telegram.client import TelegramClient
from services.telegram.formatter import format_daily_signals

logger = logging.getLogger(__name__)


def mask_sensitive_error(text: str) -> str:
    """Mask Telegram bot tokens and AWS credential keys in error strings."""
    sanitized = str(text)
    sanitized = re.sub(r"bot\d{5,}:[A-Za-z0-9_-]{10,}", "bot***:***", sanitized)
    sanitized = re.sub(r"\d{8,}:[A-Za-z0-9_-]{20,}", "***:***", sanitized)
    sanitized = re.sub(r"(AKIA|ASIA)[A-Z0-9]{16}", "AKIA***", sanitized)
    sanitized = re.sub(
        r"(aws_secret_access_key\s*[:=]\s*)[A-Za-z0-9/+=]{16,}",
        r"\1***",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}",
        r"\1***",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def dispatch_failure_alert(
    error_msg: str,
    stage: str = "daily_pipeline",
    target_date: Optional[date] = None,
    event: Optional[dict[str, Any]] = None,
) -> bool:
    """Dispatch urgent failure alert to Telegram operator with masked error details."""
    evt = event or {}
    if evt.get("dry_run") or evt.get("skip_telegram"):
        logger.info("[DRY-RUN / SKIP] Failure alert suppressed: %s", error_msg)
        return False

    token = (
        evt.get("telegram_token")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or settings.telegram_bot_token
    )
    chat_id = (
        evt.get("telegram_chat_id")
        or os.getenv("TELEGRAM_CHAT_ID")
        or settings.telegram_chat_id
    )
    if not token or not chat_id:
        logger.warning("Cannot dispatch failure alert: Telegram token or chat_id missing")
        return False

    run_d = target_date or date.today()
    masked = mask_sensitive_error(error_msg)
    alert_msg = (
        f"🚨 *[ALERT] BEI Stock Signal Failure*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"• *Stage*: `{stage}`\n"
        f"• *Date*: `{run_d}`\n"
        f"• *Error*: `{masked[:400]}`\n"
        f"• *Timestamp*: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n"
        f"⚠️ Action required: Check CloudWatch logs."
    )
    try:
        client = TelegramClient(bot_token=token, chat_id=str(chat_id))
        client.send_message(text=alert_msg)
        logger.info("Failure alert dispatched to Telegram chat %s", chat_id)
        return True
    except Exception as alert_err:
        logger.error("Failed to dispatch failure alert via Telegram: %s", alert_err)
        return False


def lambda_daily_pipeline_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        s3_bucket = (
            event["s3_bucket"]
            if "s3_bucket" in event
            else (os.getenv("S3_BUCKET") or settings.s3_bucket)
        )
        tmp_dir = Path(event.get("tmp_dir") or os.getenv("TMP_DIR", "/tmp"))
        db_target = event.get("local_db_path") or tmp_dir / "stock_signals.db"
        local_db_path = Path(db_target).resolve()
        models_target = event.get("local_models_dir") or tmp_dir / "models"
        local_models_dir = Path(models_target).resolve()

        dry_run = bool(event.get("dry_run", False))
        skip_telegram = bool(event.get("skip_telegram", False))
        skip_s3_upload = bool(event.get("skip_s3_upload", False))
        top_n = int(event.get("top_n", 5))
        provider_name = (
            event.get("market_provider")
            or os.getenv("MARKET_DATA_PROVIDER")
            or "yfinance"
        )
        s3_client = event.get("_s3_client")


        target_date: Optional[date] = None
        if event.get("date"):
            raw_d = str(event["date"]).strip()
            target_date = datetime.strptime(raw_d, "%Y-%m-%d").date()

        # Step 1: Sync DB and models from S3
        if s3_bucket:
            download_database(s3_bucket, local_db_path, s3_client=s3_client)
            sync_models_from_s3(s3_bucket, local_models_dir, s3_client=s3_client)
        elif not local_db_path.is_file():
            bootstrap_database(local_db_path)

        db_url = f"sqlite:///{local_db_path.as_posix()}"
        bar_repo = DailyBarRepository(database_url=db_url)
        sig_repo = SignalRepository(database_url=db_url)
        out_repo = OutcomeRepository(database_url=db_url)
        feat_repo = FeatureRepository(database_url=db_url)

        # Duplicate-run protection: check DB & S3 logs unless force_rerun
        force_rerun = bool(event.get("force_rerun", False))
        check_date = target_date or date.today()
        if not force_rerun:
            existing_signals = sig_repo.get_signals_by_date(check_date)
            if existing_signals:
                logger.info(
                    "Pipeline already executed: %d signals exist in DB for %s. Skipping.",
                    len(existing_signals),
                    check_date,
                )
                return {
                    "statusCode": 200,
                    "body": {
                        "status": "SKIPPED_DUPLICATE",
                        "message": f"Pipeline already executed successfully for {check_date}",
                        "date": str(check_date),
                        "signals_count": len(existing_signals),
                    },
                }

            if s3_bucket:
                try:
                    s3_c = _get_s3_client(s3_client)
                    list_resp = s3_c.list_objects_v2(
                        Bucket=s3_bucket,
                        Prefix=f"logs/daily_pipeline_{check_date}_",
                    )
                    contents = list_resp.get("Contents", [])
                    if contents:
                        if event.get("strict_duplicate_check", False):
                            logger.info(
                                "Pipeline run log exists in S3 for %s (strict). Skipping.",
                                check_date,
                            )
                            return {
                                "statusCode": 200,
                                "body": {
                                    "status": "SKIPPED_DUPLICATE",
                                    "message": f"Pipeline run log exists in S3 for {check_date}",
                                    "date": str(check_date),
                                },
                            }

                        for obj in contents:
                            try:
                                get_resp = s3_c.get_object(Bucket=s3_bucket, Key=obj["Key"])
                                raw_b = get_resp.get("Body")
                                if raw_b is not None:
                                    raw_text = (
                                        raw_b.read().decode("utf-8")
                                        if hasattr(raw_b, "read")
                                        else str(raw_b)
                                    )
                                    payload = json.loads(raw_text)
                                    if payload.get("status") == "SUCCESS":
                                        logger.info(
                                            "Pipeline run log indicates prior SUCCESS in S3 "
                                            "for %s (%s). Skipping.",
                                            check_date,
                                            obj["Key"],
                                        )
                                        return {
                                            "statusCode": 200,
                                            "body": {
                                                "status": "SKIPPED_DUPLICATE",
                                                "message": (
                                                    "Pipeline run log exists in S3 for "
                                                    f"{check_date}"
                                                ),
                                                "date": str(check_date),
                                                "log_key": obj["Key"],
                                            },
                                        }
                            except Exception as parse_err:
                                logger.debug(
                                    "Could not inspect S3 log %s: %s",
                                    obj.get("Key"),
                                    parse_err,
                                )
                except Exception as s3_err:
                    logger.warning("Could not check duplicate runs in S3: %s", s3_err)

        # Step 2: Ingest market bars with bounded exponential backoff retry
        raw_tickers = event.get("tickers")
        tickers_list = (
            [t.strip().upper().removesuffix(".JK") for t in raw_tickers if t.strip()]
            if raw_tickers
            else None
        )

        start_date_val: Optional[date] = None
        if event.get("start_date"):
            start_date_val = datetime.strptime(str(event["start_date"]).strip(), "%Y-%m-%d").date()

        ingested_count = 0
        max_retries = int(event.get("max_retries", 3))
        backoff_base = float(event.get("backoff_base", 1.0))
        backoff_factor = float(event.get("backoff_factor", 2.0))
        max_backoff = float(event.get("max_backoff", 10.0))
        ingest_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                ingested_count = run_ingest(
                    provider_name=provider_name,
                    tickers=tickers_list,
                    db_url=db_url,
                    mode=event.get("ingest_mode", "incremental"),
                    start_date=start_date_val,
                    end_date=target_date,
                )
                ingest_error = None
                break
            except Exception as err:
                ingest_error = err
                logger.warning(
                    "Market ingestion attempt %d/%d failed: %s",
                    attempt,
                    max_retries,
                    err,
                )
                if attempt < max_retries:
                    sleep_s = min(backoff_base * (backoff_factor ** (attempt - 1)), max_backoff)
                    time.sleep(sleep_s)

        if ingest_error is not None:
            logger.error(
                "Market data provider failed after %d retries: %s",
                max_retries,
                ingest_error,
            )
            dispatch_failure_alert(
                error_msg=(
                    f"Market data ingestion failed after {max_retries} attempts: {ingest_error}"
                ),
                stage="market_ingestion",
                target_date=target_date,
                event=event,
            )
            raise ingest_error

        # Step 3: Resolve open outcomes
        ambiguity_policy = event.get("ambiguity_policy", "conservative")
        outcome_engine = OutcomeEngine(
            bar_repo=bar_repo,
            signal_repo=sig_repo,
            outcome_repo=out_repo,
            ambiguity_policy=ambiguity_policy,
        )
        resolved_results = outcome_engine.resolve_all_signals(
            as_of_date=target_date,
            save=True,
            ambiguity_policy=ambiguity_policy,
        )
        outcomes_count = len(resolved_results)

        # Step 4: Extract features and generate daily signals
        model_reg = ModelRegistry(registry_dir=local_models_dir)
        sig_cfg = SignalConfig(top_n=top_n)
        sig_engine = SignalEngine(config=sig_cfg, bar_repo=bar_repo, model_registry=model_reg)

        universe = tickers_list or bar_repo.get_universe() or load_universe() or DEFAULT_UNIVERSE
        bars_by_ticker = {t: bar_repo.get_daily_bars(t) for t in universe}
        bars_by_ticker = {k: v for k, v in bars_by_ticker.items() if v}

        feature_engine = FeatureEngine()
        computed_features = {}
        if bars_by_ticker:
            try:
                computed_features = feature_engine.compute_universe_features(bars_by_ticker)
                feat_records = [rec for f_list in computed_features.values() for rec in f_list]
                if feat_records:
                    feat_repo.save_features(feat_records)
            except Exception as feat_err:
                logger.warning("Feature extraction skipped or error: %s", feat_err)

        champ = model_reg.get_champion(task="classification")
        low_champ = model_reg.get_champion(task="classification", mode="LOW_PRICE")
        high_champ = model_reg.get_champion(task="classification", mode="HIGHER_PRICE")
        has_any_champ = bool(champ or low_champ or high_champ)
        use_champ = has_any_champ and not bool(event.get("no_champion", False))
        dual_mode = bool(event.get("dual_mode", True))

        generated_signals = []
        signals_payload = []
        if bars_by_ticker:
            try:
                if dual_mode:
                    dual_res = sig_engine.generate_dual_mode_signals(
                        signal_date=target_date,
                        universe=universe,
                        bars_by_ticker=bars_by_ticker,
                        config=sig_cfg,
                        use_champion=use_champ,
                    )
                    generated_signals = (
                        dual_res.get("LOW_PRICE", []) + dual_res.get("HIGHER_PRICE", [])
                    )
                    signals_payload = dual_res
                else:
                    generated_signals = sig_engine.generate_signals(
                        signal_date=target_date,
                        universe=universe,
                        use_champion=use_champ,
                        bars_by_ticker=bars_by_ticker,
                        features_by_ticker=computed_features or None,
                        config=sig_cfg,
                    )
                    signals_payload = generated_signals
                if generated_signals:
                    sig_repo.save_signals(generated_signals, ignore_existing=True)
            except Exception as sig_err:
                logger.warning("Signal generation skipped or error: %s", sig_err)

        effective_date = (
            generated_signals[0].signal_date
            if generated_signals
            else (target_date or date.today())
        )

        # Step 5: Format and broadcast report to Telegram
        telegram_status = "SKIPPED"
        if not dry_run and not skip_telegram:
            token = (
                event.get("telegram_token")
                or os.getenv("TELEGRAM_BOT_TOKEN")
                or settings.telegram_bot_token
            )
            chat_id = (
                event.get("telegram_chat_id")
                or os.getenv("TELEGRAM_CHAT_ID")
                or settings.telegram_chat_id
            )
            if token and chat_id:
                try:
                    formatted_msg = format_daily_signals(
                        signals=signals_payload if dual_mode else generated_signals,
                        target_date=effective_date,
                        dual_mode=dual_mode,
                    )
                    tg_client = TelegramClient(bot_token=token, chat_id=chat_id)
                    resp = tg_client.send_message(text=formatted_msg)
                    msg_id = resp.get("result", {}).get("message_id")
                    telegram_status = f"SENT_{msg_id}" if msg_id else "SENT"
                except Exception as tg_err:
                    telegram_status = f"FAILED: {tg_err}"
            else:
                telegram_status = "NO_TOKEN"

        # Step 6: Upload updated SQLite DB and execution log to S3
        db_uploaded = False
        upload_meta = {}
        log_uploaded = False
        if not skip_s3_upload and s3_bucket:
            upload_meta = upload_database(
                s3_bucket=s3_bucket,
                local_path=local_db_path,
                create_backup=True,
                s3_client=s3_client,
            )
            db_uploaded = True

            try:
                log_client = _get_s3_client(s3_client)
                ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                log_key = f"logs/daily_pipeline_{effective_date}_{ts_str}.json"
                log_data = json.dumps(
                    {
                        "status": "SUCCESS",
                        "date": str(effective_date),
                        "bars_ingested": ingested_count,
                        "outcomes_resolved": outcomes_count,
                        "signals_generated": len(generated_signals),
                        "telegram_status": telegram_status,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                )
                tmp_log_file = tmp_dir / f"daily_pipeline_{ts_str}.json"
                tmp_log_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_log_file.write_text(log_data, encoding="utf-8")
                log_client.upload_file(str(tmp_log_file), s3_bucket, log_key)
                log_uploaded = True
            except Exception as log_err:
                logger.warning("Could not upload execution log to S3: %s", log_err)

        summary = {
            "status": "SUCCESS",
            "date": str(effective_date),
            "bars_ingested": ingested_count,
            "outcomes_resolved": outcomes_count,
            "signals_generated": len(generated_signals),
            "telegram_status": telegram_status,
            "db_uploaded": db_uploaded,
            "log_uploaded": log_uploaded,
            "s3_bucket": s3_bucket,
            "upload_meta": upload_meta,
        }
        return {"statusCode": 200, "body": summary}

    except Exception as exc:
        logger.exception("Daily pipeline execution failed")
        dispatch_failure_alert(
            error_msg=str(exc),
            stage="daily_pipeline",
            target_date=target_date,
            event=event,
        )
        return {
            "statusCode": 500,
            "body": {
                "status": "FAILED",
                "error": str(exc),
            },
        }


def lambda_retraining_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        s3_bucket = (
            event["s3_bucket"]
            if "s3_bucket" in event
            else (os.getenv("S3_BUCKET") or settings.s3_bucket)
        )
        tmp_dir = Path(event.get("tmp_dir") or os.getenv("TMP_DIR", "/tmp"))
        local_db_path = Path(event.get("local_db_path") or tmp_dir / "stock_signals.db").resolve()
        local_models_dir = Path(event.get("local_models_dir") or tmp_dir / "models").resolve()

        force = bool(event.get("force", False))
        min_matured = int(event.get("min_matured", 200))
        auto_promote = bool(event.get("auto_promote", True))
        dry_run = bool(event.get("dry_run", False))
        algorithm = str(event.get("algorithm", "lightgbm"))
        task = str(event.get("task", "classification"))
        s3_client = event.get("_s3_client")

        # Step 1: Sync from S3
        if s3_bucket:
            download_database(s3_bucket, local_db_path, s3_client=s3_client)
            sync_models_from_s3(s3_bucket, local_models_dir, s3_client=s3_client)
        elif not local_db_path.is_file():
            bootstrap_database(local_db_path)

        db_url = f"sqlite:///{local_db_path.as_posix()}"
        bar_repo = DailyBarRepository(database_url=db_url)
        sig_repo = SignalRepository(database_url=db_url)
        out_repo = OutcomeRepository(database_url=db_url)
        feat_repo = FeatureRepository(database_url=db_url)
        lbl_repo = LabelRepository(database_url=db_url)
        reg = ModelRegistry(registry_dir=local_models_dir)

        # Step 2: Assemble retraining components
        trigger_cfg = RetrainingTriggerConfig(
            min_matured_samples=min_matured,
            force=force,
        )
        trigger_eval = RetrainingTriggerEvaluator(
            config=trigger_cfg,
            outcome_repo=out_repo,
            signal_repo=sig_repo,
        )
        assembler = RetrainingDatasetAssembler(
            outcome_repo=out_repo,
            signal_repo=sig_repo,
            feature_repo=feat_repo,
            label_repo=lbl_repo,
            bar_repo=bar_repo,
        )
        gate_mgr = PromotionGateManager(registry=reg)
        pipeline_cfg = RetrainingPipelineConfig(
            algorithm=algorithm,
            task=task,
            min_matured_samples=min_matured,
            auto_promote=auto_promote,
        )

        pipeline = RetrainingPipeline(
            config=pipeline_cfg,
            trigger_evaluator=trigger_eval,
            dataset_assembler=assembler,
            gate_manager=gate_mgr,
            registry=reg,
        )

        # Step 3: Run pipeline
        res = pipeline.run(
            since_date=event.get("since_date"),
            force=force,
            auto_promote=auto_promote,
            dry_run=dry_run,
        )

        # Step 4: If model promoted or challenger trained, sync back to S3
        synced_models: list[str] = []
        is_promoted = bool(getattr(res, "promoted", False))
        if is_promoted and not dry_run and s3_bucket:
            synced_models = sync_models_to_s3(s3_bucket, local_models_dir, s3_client=s3_client)
            upload_database(s3_bucket, local_db_path, create_backup=True, s3_client=s3_client)
        elif (
            res.status == "SUCCESS"
            and not dry_run
            and s3_bucket
            and getattr(res, "artifact_path", None)
        ):
            synced_models = sync_models_to_s3(s3_bucket, local_models_dir, s3_client=s3_client)

        summary = {
            "status": res.status,
            "triggered": getattr(res, "triggered", False),
            "promoted": is_promoted,
            "challenger_version": res.challenger_version,
            "champion_version": res.champion_version,
            "recommendation": res.gate_result.recommendation if res.gate_result else None,
            "models_synced_count": len(synced_models),
        }

        return {"statusCode": 200, "body": summary}

    except Exception as exc:
        logger.exception("Retraining pipeline execution failed")
        dispatch_failure_alert(
            error_msg=str(exc),
            stage="retraining_pipeline",
            event=event,
        )
        return {
            "statusCode": 500,
            "body": {
                "status": "FAILED",
                "error": str(exc),
            },
        }
