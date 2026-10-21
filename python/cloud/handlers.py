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
from python.data.repository import DailyBarRepository
from python.features.repository import FeatureRepository
from python.journal.repository import PositionJournalRepository
from python.journal.service import PositionJournalService
from python.labels.repository import LabelRepository
from python.models.registry import ModelRegistry
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository
from services.telegram.bot import TelegramBotDispatcher
from services.telegram.client import TelegramClient
from services.telegram.formatter import format_daily_signals

try:
    from python.data.provider import DEFAULT_UNIVERSE, load_universe
    from python.features.engine import FeatureEngine
    from python.retraining.dataset import RetrainingDatasetAssembler
    from python.retraining.gate import PromotionGateManager
    from python.retraining.pipeline import RetrainingPipeline, RetrainingPipelineConfig
    from python.retraining.trigger import RetrainingTriggerConfig, RetrainingTriggerEvaluator
    from python.signals.engine import SignalEngine
    from scripts.ingest_daily import run_ingest
except ImportError as _import_err:
    DEFAULT_UNIVERSE = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]  # type: ignore[assignment]
    load_universe = None  # type: ignore[assignment]
    FeatureEngine = None  # type: ignore[assignment]
    RetrainingDatasetAssembler = None  # type: ignore[assignment]
    PromotionGateManager = None  # type: ignore[assignment]
    RetrainingPipeline = None  # type: ignore[assignment]
    RetrainingPipelineConfig = None  # type: ignore[assignment]
    RetrainingTriggerConfig = None  # type: ignore[assignment]
    RetrainingTriggerEvaluator = None  # type: ignore[assignment]
    SignalEngine = None  # type: ignore[assignment]
    run_ingest = None  # type: ignore[assignment]


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
        evt.get("telegram_token") or os.getenv("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token
    )
    chat_id = (
        evt.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID") or settings.telegram_chat_id
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
    logging.getLogger().setLevel(logging.INFO)
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
            event.get("market_provider") or os.getenv("MARKET_DATA_PROVIDER") or "yfinance"
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

        if run_ingest is not None:
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
        else:
            logger.info(
                "Market data ingestion skipped: run_ingest not loaded in serverless package."
            )

        # Step 3: Resolve open outcomes
        ambiguity_policy = event.get("ambiguity_policy", "conservative")
        outcomes_count = 0
        if OutcomeEngine is not None and out_repo is not None:
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
        min_prob_val = event.get("min_probability", event.get("min_prob"))
        if min_prob_val is None and "SIGNAL_MIN_PROBABILITY" in os.environ:
            try:
                min_prob_val = float(os.environ["SIGNAL_MIN_PROBABILITY"])
            except ValueError:
                pass
        sig_cfg = SignalConfig(
            top_n=top_n,
            min_probability=float(min_prob_val) if min_prob_val is not None else 0.25,
        )

        sig_engine = None
        if SignalEngine is not None:
            sig_engine = SignalEngine(config=sig_cfg, bar_repo=bar_repo, model_registry=model_reg)
        else:
            logger.info("SignalEngine skipped: ML dependencies not present in serverless package.")

        fallback_univ = load_universe() if load_universe else []
        universe = tickers_list or bar_repo.get_universe() or fallback_univ or DEFAULT_UNIVERSE
        bars_by_ticker = {t: bar_repo.get_daily_bars(t) for t in universe}
        bars_by_ticker = {k: v for k, v in bars_by_ticker.items() if v}

        computed_features = {}
        if bars_by_ticker and FeatureEngine is not None:
            feature_engine = FeatureEngine()
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
        if bars_by_ticker and sig_engine is not None:
            try:
                if dual_mode:
                    dual_res = sig_engine.generate_dual_mode_signals(
                        signal_date=target_date,
                        universe=universe,
                        bars_by_ticker=bars_by_ticker,
                        config=sig_cfg,
                        use_champion=use_champ,
                    )
                    generated_signals = dual_res.get("LOW_PRICE", []) + dual_res.get(
                        "HIGHER_PRICE", []
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
        elif not generated_signals:
            # Fallback to pre-computed signals in SQLite database for target/today's date
            lookup_date = target_date or check_date
            latest_db_signals = sig_repo.get_signals_by_date(lookup_date)
            if not latest_db_signals:
                # If no signals on exact date, fetch latest available signals
                distinct_dates = sig_repo.get_distinct_dates()
                if distinct_dates:
                    lookup_date = distinct_dates[-1]
                    latest_db_signals = sig_repo.get_signals_by_date(lookup_date)
            if latest_db_signals:
                generated_signals = latest_db_signals
                signals_payload = latest_db_signals
                logger.info(
                    "Loaded %d pre-computed signals from DB for %s",
                    len(generated_signals),
                    lookup_date,
                )

        effective_date = (
            generated_signals[0].signal_date if generated_signals else (target_date or date.today())
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
    logging.getLogger().setLevel(logging.INFO)
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


def lambda_telegram_webhook_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda handler for incoming Telegram Bot webhook updates.

    Processes Telegram updates via Function URL or API Gateway proxy,
    dispatches commands to TelegramBotDispatcher, responds via TelegramClient,
    and maintains database sync with S3.
    """
    # ponytail: synchronous webhook handler; offload to SQS worker if query latency exceeds 10s.
    logging.getLogger().setLevel(logging.INFO)
    try:
        # Step 1: Parse payload from event (direct payload or API Gateway proxy body)
        payload: dict[str, Any] = {}
        if isinstance(event, dict):
            raw_body = event.get("body")
            if raw_body is not None:
                if isinstance(raw_body, str):
                    if event.get("isBase64Encoded"):
                        import base64

                        raw_body = base64.b64decode(raw_body).decode("utf-8")
                    try:
                        payload = json.loads(raw_body)
                    except Exception:
                        payload = {}
                elif isinstance(raw_body, dict):
                    payload = raw_body
            else:
                payload = event

        print(f"[WEBHOOK_EVENT] Received payload: {json.dumps(payload)[:1000]}")

        # Step 2: Extract message details
        msg = (
            payload.get("message")
            or payload.get("edited_message")
            or payload.get("channel_post")
            or payload.get("callback_query", {}).get("message")
            or payload
        )
        chat = msg.get("chat") if isinstance(msg, dict) else {}
        chat_id = (
            chat.get("id")
            if isinstance(chat, dict)
            else (msg.get("chat_id") if isinstance(msg, dict) else None)
        )
        cb_from = (
            payload.get("callback_query", {}).get("from") if isinstance(payload, dict) else None
        )
        from_user = (msg.get("from") if isinstance(msg, dict) else None) or cb_from or {}
        from_user_id = (
            str(from_user.get("id"))
            if isinstance(from_user, dict) and from_user.get("id") is not None
            else str(msg.get("from_user_id") or "").strip()
        )
        sender_chat_id = str(chat_id or "").strip()
        if not sender_chat_id and from_user_id:
            sender_chat_id = from_user_id

        text = str(msg.get("text", "")).strip() if isinstance(msg, dict) else ""
        if not text and isinstance(payload.get("callback_query"), dict):
            text = str(payload["callback_query"].get("data") or "").strip()

        # Step 3: Security verification (chat_id, user_id, and secret header)
        allowed_chat_id = str(
            event.get("allowed_chat_id")
            or os.getenv("TELEGRAM_CHAT_ID")
            or settings.telegram_chat_id
            or ""
        ).strip()
        allowed_ids = {i.strip() for i in allowed_chat_id.split(",") if i.strip()}

        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
        if webhook_secret:
            headers = event.get("headers") or {}
            token_header = headers.get("x-telegram-bot-api-secret-token") or headers.get(
                "X-Telegram-Bot-Api-Secret-Token"
            )
            if token_header != webhook_secret:
                logger.warning("Telegram webhook secret mismatch")
                print("[WEBHOOK_REJECTED] Secret token mismatch")
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"status": "ignored", "reason": "invalid_secret"}),
                }

        is_authorized = True
        if allowed_ids:
            is_authorized = (sender_chat_id in allowed_ids) or (from_user_id in allowed_ids)

        print(
            f"[WEBHOOK_AUTH] sender_chat_id='{sender_chat_id}', from_user_id='{from_user_id}', "
            f"allowed='{allowed_chat_id}', authorized={is_authorized}"
        )

        if not is_authorized:
            logger.warning(
                "Unauthorized Telegram webhook: sender_chat_id=%s, from_user_id=%s (allowed: %s)",
                sender_chat_id,
                from_user_id,
                allowed_chat_id,
            )
            print(
                f"[WEBHOOK_REJECTED] Unauthorized: chat_id={sender_chat_id}, "
                f"from_user_id={from_user_id}"
            )
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "ignored", "reason": "unauthorized"}),
            }

        if not text:
            print(f"[WEBHOOK_NO_TEXT] Message contains no command/text for chat {sender_chat_id}")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "ok", "message": "no_text"}),
            }

        print(f"[WEBHOOK_CMD] Dispatching command: '{text}' from chat {sender_chat_id}")

        # Step 4: Sync DB and models from S3
        s3_bucket = (
            event.get("s3_bucket")
            if "s3_bucket" in event
            else (os.getenv("S3_BUCKET") or settings.s3_bucket)
        )
        tmp_dir = Path(event.get("tmp_dir") or os.getenv("TMP_DIR", "/tmp"))
        local_db_path = Path(event.get("local_db_path") or tmp_dir / "stock_signals.db").resolve()
        local_models_dir = Path(event.get("local_models_dir") or tmp_dir / "models").resolve()
        s3_client = event.get("_s3_client")

        if s3_bucket:
            if not local_db_path.is_file() or event.get("sync_db", True):
                try:
                    download_database(s3_bucket, local_db_path, s3_client=s3_client)
                except Exception as s3_err:
                    logger.warning("Could not sync DB from S3: %s", s3_err)
            if not local_models_dir.is_dir() or event.get("sync_models", True):
                try:
                    sync_models_from_s3(s3_bucket, local_models_dir, s3_client=s3_client)
                except Exception as s3_err:
                    logger.warning("Could not sync models from S3: %s", s3_err)
        elif not local_db_path.is_file():
            bootstrap_database(local_db_path)

        # Step 5: Route command through TelegramBotDispatcher
        db_url = f"sqlite:///{local_db_path.as_posix()}"
        bar_repo = DailyBarRepository(database_url=db_url)
        sig_repo = SignalRepository(database_url=db_url)
        reg = ModelRegistry(registry_dir=local_models_dir)
        j_repo = PositionJournalRepository(database_url=db_url)
        j_svc = PositionJournalService(repo=j_repo, bar_repo=bar_repo)

        dispatcher = TelegramBotDispatcher(
            signal_repo=sig_repo,
            model_registry=reg,
            journal_service=j_svc,
            bar_repo=bar_repo,
        )
        reply_text = dispatcher.dispatch(text)
        preview_rep = reply_text[:60].replace("\n", " ")
        print(f"[WEBHOOK_REPLY] Reply for {sender_chat_id} ({len(reply_text)}c): {preview_rep}...")

        # Step 6: Persist modified DB to S3 if state mutated
        if s3_bucket and text.lower().startswith(("/enter", "/exit", "/cancel")):
            try:
                upload_database(
                    s3_bucket=s3_bucket,
                    local_path=local_db_path,
                    create_backup=False,
                    s3_client=s3_client,
                )
            except Exception as up_err:
                logger.warning("Could not persist modified DB to S3: %s", up_err)

        # Step 7: Reply to user via TelegramClient or webhook fallback
        token = (
            event.get("telegram_token")
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or settings.telegram_bot_token
        )
        skip_tg = bool(event.get("skip_telegram", False))

        sent_via_client = False
        if not skip_tg and token and sender_chat_id:
            try:
                client = TelegramClient(
                    bot_token=token,
                    chat_id=sender_chat_id,
                    timeout=5.0,
                    max_retries=1,
                )
                client.send_message(text=reply_text)
                sent_via_client = True
                print(f"[WEBHOOK_SENT] Sent reply via TelegramClient to chat {sender_chat_id}")
            except Exception as send_err:
                logger.warning("Failed to deliver Telegram reply via client: %s", send_err)
                print(f"[WEBHOOK_FALLBACK] Client failed ({send_err}); using webhook response")

        if not skip_tg and not sent_via_client and sender_chat_id:
            target_chat_val: Any = (
                int(sender_chat_id) if sender_chat_id.lstrip("-").isdigit() else sender_chat_id
            )
            print(f"[WEBHOOK_METHOD_REPLY] Returning sendMessage for chat {target_chat_val}")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "method": "sendMessage",
                        "chat_id": target_chat_val,
                        "text": reply_text[:4096],
                        "disable_web_page_preview": True,
                    }
                ),
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "ok", "reply": reply_text}),
        }

    except Exception as exc:
        logger.exception("Error in lambda_telegram_webhook_handler: %s", exc)
        print(f"[WEBHOOK_ERROR] Exception in lambda_telegram_webhook_handler: {exc}")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "error", "error": str(exc)}),
        }
