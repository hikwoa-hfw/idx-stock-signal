from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
import pandas as pd

from python.common.types import ComparisonRecommendation, ComparisonReport
from python.models.comparator import ModelComparator, PromotionGateConfig
from python.models.dataset import Dataset
from python.models.registry import ModelMetadata, ModelRegistry


@dataclass
class PromotionGateResult:
    recommendation: str
    passed: bool
    challenger_version: str
    champion_version: Optional[str] = None
    report: Optional[ComparisonReport] = None
    rationale: list[str] = field(default_factory=list)


class PromotionGateManager:
    """Manages model promotion gating evaluations, atomic champion promotions, and rollback."""

    def __init__(
        self,
        comparator: Optional[ModelComparator] = None,
        registry: Optional[ModelRegistry] = None,
        gate_config: Optional[PromotionGateConfig] = None,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.comparator = comparator or ModelComparator(config=gate_config)

    def evaluate_candidate(
        self,
        challenger_version: str,
        test_dataset: Optional[Dataset] = None,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[np.ndarray] = None,
        returns_test: Optional[np.ndarray] = None,
        champion_version: Optional[str] = None,
        task: str = "classification",
        test_window: Union[str, dict[str, Optional[str]]] = "",
    ) -> PromotionGateResult:
        """Evaluates whether a challenger model satisfies promotion criteria against champion."""
        # Extract evaluation arrays from test_dataset if provided
        outcome_statuses: Optional[list[str]] = None
        if test_dataset is not None:
            feat_df = pd.DataFrame(test_dataset.X, columns=test_dataset.feature_names)
            y_arr = test_dataset.y
            ret_arr = test_dataset.y_return
            if (
                test_dataset.metadata is not None
                and not test_dataset.metadata.empty
                and "outcome_status" in test_dataset.metadata.columns
            ):
                outcome_statuses = test_dataset.metadata["outcome_status"].tolist()
            if not test_window and len(test_dataset.dates) > 0:
                test_window = f"{min(test_dataset.dates)} to {max(test_dataset.dates)}"
        else:
            if X_test is None or y_test is None or returns_test is None:
                raise ValueError(
                    "Either test_dataset or (X_test, y_test, returns_test) must be supplied."
                )
            feat_df = X_test if isinstance(X_test, pd.DataFrame) else pd.DataFrame(X_test)
            y_arr = np.asarray(y_test, dtype=np.int64)
            ret_arr = np.asarray(returns_test, dtype=np.float64)

        # Resolve champion
        champ_ver = champion_version
        if not champ_ver:
            champ_res = self.registry.get_champion(task=task)
            if champ_res is not None:
                champ_ver = champ_res[1].model_version

        # Handle initial bootstrap where no champion exists
        if not champ_ver:
            rationale = [
                "Initial bootstrap: No existing champion found in registry. "
                "Challenger passes promotion gate automatically."
            ]
            return PromotionGateResult(
                recommendation=ComparisonRecommendation.PROMOTE.value,
                passed=True,
                challenger_version=challenger_version,
                champion_version=None,
                report=None,
                rationale=rationale,
            )

        # Run Phase 10 ModelComparator evaluation
        report = self.comparator.compare_from_registry(
            registry=self.registry,
            champion_version=champ_ver,
            challenger_version=challenger_version,
            X_test=feat_df,
            y_test=y_arr,
            returns_test=ret_arr,
            outcome_statuses=outcome_statuses,
            test_window=test_window,
        )

        passed = report.recommendation == ComparisonRecommendation.PROMOTE.value
        return PromotionGateResult(
            recommendation=report.recommendation,
            passed=passed,
            challenger_version=challenger_version,
            champion_version=champ_ver,
            report=report,
            rationale=report.rationale,
        )

    def promote_challenger(
        self,
        challenger_version: str,
        archive_status: str = "archived_champion",
    ) -> ModelMetadata:
        """Atomically promotes challenger to champion and demotes existing champion."""
        return self.registry.promote_to_champion(
            model_version=challenger_version,
            demote_to=archive_status,
        )

    def rollback(
        self,
        target_version: Optional[str] = None,
        task: str = "classification",
        demote_current_to: str = "retired",
    ) -> ModelMetadata:
        """Reverts champion to a specific prior version or last known good champion."""
        return self.registry.rollback_champion(
            target_version=target_version,
            task=task,
            demote_current_to=demote_current_to,
        )
