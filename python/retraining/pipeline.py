from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, Union

from python.models.baseline import create_baseline_model
from python.models.dataset import Dataset
from python.models.metrics import evaluate_classification
from python.models.registry import ModelMetadata, ModelRegistry
from python.retraining.dataset import RetrainingDatasetAssembler
from python.retraining.gate import PromotionGateManager, PromotionGateResult
from python.retraining.trigger import (
    RetrainingTriggerConfig,
    RetrainingTriggerEvaluator,
    RetrainingTriggerResult,
)


@dataclass
class RetrainingPipelineConfig:
    algorithm: str = "lightgbm"  # "lightgbm" or "logistic"
    task: str = "classification"
    calibrate: bool = True
    min_matured_samples: int = 200
    rolling_window_size: int = 50
    brier_safety_floor: float = 0.25
    win_rate_safety_floor: float = 0.45
    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    purge_days: int = 10
    auto_promote: bool = False
    force: bool = False
    dry_run: bool = False
    dataset_version: str = "v1.0.0"
    feature_version: str = "v1.0.0"
    model_version: Optional[str] = None
    since_date: Optional[Union[date, str]] = None


@dataclass
class RetrainingPipelineResult:
    status: str  # "SUCCESS", "SKIPPED", "FAILED"
    triggered: bool
    trigger_result: Optional[RetrainingTriggerResult] = None
    challenger_version: Optional[str] = None
    champion_version: Optional[str] = None
    gate_result: Optional[PromotionGateResult] = None
    promoted: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    train_sample_count: int = 0
    test_sample_count: int = 0
    artifact_path: Optional[str] = None
    error_message: Optional[str] = None


class RetrainingPipeline:
    """Automated retraining pipeline: trains challengers, evaluates gates, and promotes."""

    def __init__(
        self,
        config: Optional[RetrainingPipelineConfig] = None,
        trigger_evaluator: Optional[RetrainingTriggerEvaluator] = None,
        dataset_assembler: Optional[RetrainingDatasetAssembler] = None,
        gate_manager: Optional[PromotionGateManager] = None,
        registry: Optional[ModelRegistry] = None,
    ) -> None:
        self.config = config or RetrainingPipelineConfig()
        self.registry = registry or ModelRegistry()

        trigger_cfg = RetrainingTriggerConfig(
            min_matured_samples=self.config.min_matured_samples,
            rolling_window_size=self.config.rolling_window_size,
            brier_safety_floor=self.config.brier_safety_floor,
            win_rate_safety_floor=self.config.win_rate_safety_floor,
            force=self.config.force,
        )
        self.trigger_evaluator = trigger_evaluator or RetrainingTriggerEvaluator(
            config=trigger_cfg
        )
        self.dataset_assembler = dataset_assembler or RetrainingDatasetAssembler(
            purge_days=self.config.purge_days
        )
        self.gate_manager = gate_manager or PromotionGateManager(
            registry=self.registry
        )

    def run(
        self,
        base_dataset: Optional[Dataset] = None,
        since_date: Optional[Union[date, str]] = None,
        force: Optional[bool] = None,
        auto_promote: Optional[bool] = None,
        dry_run: Optional[bool] = None,
        check_trigger_only: bool = False,
    ) -> RetrainingPipelineResult:
        is_force = force if force is not None else self.config.force
        is_auto_promote = (
            auto_promote if auto_promote is not None else self.config.auto_promote
        )
        is_dry_run = dry_run if dry_run is not None else self.config.dry_run

        current_champ = self.registry.get_champion(task=self.config.task)
        champ_ver = current_champ[1].model_version if current_champ else None

        # Resolve anchor date for counting new accumulated outcomes:
        # Default to champion's training_end + 1 day to measure strictly new outcomes
        anchor_since: Optional[date] = None
        s_date = since_date or self.config.since_date
        if s_date is not None:
            anchor_since = (
                date.fromisoformat(s_date.strip())
                if isinstance(s_date, str)
                else s_date
            )
        elif current_champ is not None and current_champ[1].training_end:
            try:
                t_end = current_champ[1].training_end.strip()
                anchor_since = date.fromisoformat(t_end) + timedelta(days=1)
            except Exception:
                anchor_since = None

        # 1. Trigger Evaluation
        trigger_res = self.trigger_evaluator.evaluate(
            force=is_force,
            since_date=anchor_since,
            min_matured_samples=self.config.min_matured_samples,
        )

        if check_trigger_only:
            return RetrainingPipelineResult(
                status="TRIGGER_CHECKED",
                triggered=trigger_res.should_retrain,
                trigger_result=trigger_res,
                champion_version=champ_ver,
            )

        if not trigger_res.should_retrain:
            return RetrainingPipelineResult(
                status="SKIPPED",
                triggered=False,
                trigger_result=trigger_res,
                champion_version=champ_ver,
            )

        try:
            # 2. Dataset Assembly
            dataset = self.dataset_assembler.assemble_dataset(base_dataset=base_dataset)
            if len(dataset) < 10:
                return RetrainingPipelineResult(
                    status="FAILED",
                    triggered=True,
                    trigger_result=trigger_res,
                    champion_version=champ_ver,
                    error_message=(
                        f"Insufficient samples in assembled dataset ({len(dataset)}). "
                        f"Need at least 10 samples to train."
                    ),
                )

            # 3. Walk-Forward Split with Purge Window
            train_ds, val_ds, test_ds = self.dataset_assembler.split_walk_forward(
                dataset=dataset,
                train_ratio=self.config.train_ratio,
                val_ratio=self.config.val_ratio,
                test_ratio=self.config.test_ratio,
                purge_days=self.config.purge_days,
            )

            if len(train_ds) == 0 or len(test_ds) == 0:
                return RetrainingPipelineResult(
                    status="FAILED",
                    triggered=True,
                    trigger_result=trigger_res,
                    champion_version=champ_ver,
                    error_message="Chronological split produced empty train or test set.",
                )

            # 4. Train Candidate Challenger Model
            kwargs = {}
            if self.config.task == "classification" and self.config.calibrate:
                kwargs["calibrated"] = True

            model = create_baseline_model(
                model_type=self.config.algorithm,
                task=self.config.task,
                **kwargs,
            )

            y_train = train_ds.y if self.config.task == "classification" else train_ds.y_return
            y_test = test_ds.y if self.config.task == "classification" else test_ds.y_return

            model.fit(train_ds.X, y_train, feature_names=dataset.feature_names)

            # Compute test metrics
            y_prob = model.predict_probability(test_ds.X)
            metrics = evaluate_classification(y_test, y_prob)

            # 5. Save Challenger Artifact into ModelRegistry
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            challenger_version = (
                self.config.model_version
                or f"challenger_{self.config.algorithm}_{now_str}"
            )

            val_start = str(min(val_ds.dates)) if val_ds and len(val_ds) > 0 else None
            val_end = str(max(val_ds.dates)) if val_ds and len(val_ds) > 0 else None

            metadata = ModelMetadata(
                model_version=challenger_version,
                algorithm=self.config.algorithm,
                task=self.config.task,
                dataset_version=self.config.dataset_version,
                feature_version=self.config.feature_version,
                training_start=str(min(train_ds.dates)),
                training_end=str(max(train_ds.dates)),
                validation_start=val_start,
                validation_end=val_end,
                metrics=metrics,
                status="challenger",
                feature_names=dataset.feature_names,
            )

            art_path: Optional[str] = None
            if not is_dry_run:
                saved_p = self.registry.save_model(model, metadata)
                art_path = str(saved_p)

            # 6. Promotion Gate Evaluation
            gate_res: Optional[PromotionGateResult] = None
            promoted = False

            if not is_dry_run:
                gate_res = self.gate_manager.evaluate_candidate(
                    challenger_version=challenger_version,
                    test_dataset=test_ds,
                    champion_version=champ_ver,
                    task=self.config.task,
                )

                if gate_res.passed and is_auto_promote:
                    self.gate_manager.promote_challenger(
                        challenger_version=challenger_version,
                        archive_status="archived_champion",
                    )
                    promoted = True

            return RetrainingPipelineResult(
                status="SUCCESS",
                triggered=True,
                trigger_result=trigger_res,
                challenger_version=challenger_version,
                champion_version=champ_ver,
                gate_result=gate_res,
                promoted=promoted,
                metrics=metrics,
                train_sample_count=len(train_ds),
                test_sample_count=len(test_ds),
                artifact_path=art_path,
            )
        except Exception as e:
            return RetrainingPipelineResult(
                status="FAILED",
                triggered=True,
                trigger_result=trigger_res,
                champion_version=champ_ver,
                error_message=f"Pipeline execution failed: {e}",
            )
