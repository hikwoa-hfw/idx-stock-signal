import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from python.cloud.s3_sync import (
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


def lambda_daily_pipeline_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        s3_bucket = event.get("s3_bucket") or os.getenv("S3_BUCKET") or settings.s3_bucket
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

        # Step 2: Ingest market bars
        raw_tickers = event.get("tickers")
        tickers_list = (
            [t.strip().upper().removesuffix(".JK") for t in raw_tickers if t.strip()]
            if raw_tickers
            else None
        )

        ingested_count = 0
        try:
            ingested_count = run_ingest(
                provider_name=provider_name,
                tickers=tickers_list,
                db_url=db_url,
                mode=event.get("ingest_mode", "incremental"),
                end_date=target_date,
            )
        except Exception as ingest_err:
            logger.warning("Market ingestion encountered issue: %s", ingest_err)

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

        # Step 4: Generate daily signals
        model_reg = ModelRegistry(registry_dir=local_models_dir)
        sig_cfg = SignalConfig(top_n=top_n)
        sig_engine = SignalEngine(config=sig_cfg, bar_repo=bar_repo, model_registry=model_reg)


        universe = tickers_list or bar_repo.get_universe() or load_universe() or DEFAULT_UNIVERSE
        bars_by_ticker = {t: bar_repo.get_daily_bars(t) for t in universe}
        bars_by_ticker = {k: v for k, v in bars_by_ticker.items() if v}

        champ = model_reg.get_champion(task="classification")
        use_champ = champ is not None and not bool(event.get("no_champion", False))

        generated_signals = []
        if bars_by_ticker:
            try:
                generated_signals = sig_engine.generate_signals(
                    signal_date=target_date,
                    universe=universe,
                    use_champion=use_champ,
                    bars_by_ticker=bars_by_ticker,
                    config=sig_cfg,
                )
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
                        signals=generated_signals,
                        target_date=effective_date,
                    )
                    tg_client = TelegramClient(token=token, chat_id=chat_id)
                    resp = tg_client.send_message(text=formatted_msg)
                    msg_id = resp.get("result", {}).get("message_id")
                    telegram_status = f"SENT_{msg_id}" if msg_id else "SENT"
                except Exception as tg_err:
                    telegram_status = f"FAILED: {tg_err}"
            else:
                telegram_status = "NO_TOKEN"

        # Step 6: Upload updated SQLite DB to S3
        db_uploaded = False
        upload_meta = {}
        if not skip_s3_upload and s3_bucket:
            upload_meta = upload_database(
                s3_bucket=s3_bucket,
                local_path=local_db_path,
                create_backup=True,
                s3_client=s3_client,
            )
            db_uploaded = True

        summary = {
            "status": "SUCCESS",
            "date": str(effective_date),
            "bars_ingested": ingested_count,
            "outcomes_resolved": outcomes_count,
            "signals_generated": len(generated_signals),
            "telegram_status": telegram_status,
            "db_uploaded": db_uploaded,
            "s3_bucket": s3_bucket,
            "upload_meta": upload_meta,
        }
        return {"statusCode": 200, "body": summary}

    except Exception as exc:
        logger.exception("Daily pipeline execution failed")
        return {
            "statusCode": 500,
            "body": {
                "status": "FAILED",
                "error": str(exc),
            },
        }


def lambda_retraining_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        s3_bucket = event.get("s3_bucket") or os.getenv("S3_BUCKET") or settings.s3_bucket
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

        # Step 4: If model promoted, sync back to S3
        synced_models: list[str] = []
        if res.status == "PROMOTED" and not dry_run and s3_bucket:
            synced_models = sync_models_to_s3(s3_bucket, local_models_dir, s3_client=s3_client)
            upload_database(s3_bucket, local_db_path, create_backup=True, s3_client=s3_client)

        summary = {
            "status": res.status,
            "triggered": getattr(res, "triggered", False),
            "promoted": getattr(res, "promoted", False),
            "challenger_version": res.challenger_version,
            "champion_version": res.champion_version,
            "recommendation": res.gate_result.recommendation if res.gate_result else None,
            "models_synced_count": len(synced_models),
        }


        return {"statusCode": 200, "body": summary}

    except Exception as exc:
        logger.exception("Retraining pipeline execution failed")
        return {
            "statusCode": 500,
            "body": {
                "status": "FAILED",
                "error": str(exc),
            },
        }
