import json
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from python.common.types import (
    ComparisonRecommendation,
    ComparisonReport,
    EvaluationReport,
)
from python.models.evaluation import EvaluationEngine
from python.models.registry import ModelRegistry


@dataclass
class PromotionGateConfig:
    min_sample_size: int = 30
    min_profit_factor_improvement: float = 0.05
    max_brier_worsening: float = 0.0
    max_drawdown_increase: float = 0.0
    min_expectancy_improvement: float = 0.0


class ModelComparator:
    """Compares champion and challenger model evaluations under identical test conditions."""

    def __init__(
        self,
        config: Optional[PromotionGateConfig] = None,
        evaluation_engine: Optional[EvaluationEngine] = None,
    ) -> None:
        self.config = config or PromotionGateConfig()
        self.engine = evaluation_engine or EvaluationEngine()

    def compare_reports(
        self,
        champion_report: EvaluationReport,
        challenger_report: EvaluationReport,
        test_window: Union[str, dict[str, Optional[str]]] = "",
    ) -> ComparisonReport:
        """Compares two pre-computed EvaluationReport instances and decides promotion."""
        champ_t = champion_report.trading_metrics
        champ_p = champion_report.prediction_metrics
        chall_t = challenger_report.trading_metrics
        chall_p = challenger_report.prediction_metrics

        pf_champ = champ_t.profit_factor if np.isfinite(champ_t.profit_factor) else 999.0
        pf_chall = chall_t.profit_factor if np.isfinite(chall_t.profit_factor) else 999.0

        delta: dict[str, float] = {
            "win_rate_delta": round(chall_t.win_rate - champ_t.win_rate, 4),
            "profit_factor_delta": round(pf_chall - pf_champ, 4),
            "expectancy_delta": round(chall_t.expectancy - champ_t.expectancy, 4),
            "max_drawdown_delta": round(chall_t.max_drawdown - champ_t.max_drawdown, 4),
            "sharpe_delta": round(chall_t.sharpe - champ_t.sharpe, 4),
            "brier_score_delta": round(chall_p.brier_score - champ_p.brier_score, 4),
            "log_loss_delta": round(chall_p.log_loss - champ_p.log_loss, 4),
            "roc_auc_delta": round(chall_p.roc_auc - champ_p.roc_auc, 4),
            "ece_delta": round(chall_p.ece - champ_p.ece, 4),
        }

        sample_size = min(champion_report.sample_size, challenger_report.sample_size)
        rationale: list[str] = []

        if sample_size < self.config.min_sample_size:
            rationale.append(
                f"Sample size ({sample_size}) below minimum required "
                f"({self.config.min_sample_size})."
            )
            return ComparisonReport(
                champion_version=champion_report.model_version,
                challenger_version=challenger_report.model_version,
                test_window=test_window,
                champion_metrics=champion_report,
                challenger_metrics=challenger_report,
                delta_metrics=delta,
                recommendation=ComparisonRecommendation.INCONCLUSIVE.value,
                rationale=rationale,
            )

        # Rule 1: Profit factor improvement
        pf_pass = (pf_chall - pf_champ) >= self.config.min_profit_factor_improvement
        if pf_pass:
            rationale.append(
                f"Profit Factor improved: {pf_chall:.2f} vs {pf_champ:.2f} "
                f"(delta: {delta['profit_factor_delta']:+.2f} "
                f">= +{self.config.min_profit_factor_improvement:.2f})."
            )
        else:
            rationale.append(
                f"Profit Factor insufficient: {pf_chall:.2f} vs {pf_champ:.2f} "
                f"(delta: {delta['profit_factor_delta']:+.2f} "
                f"< +{self.config.min_profit_factor_improvement:.2f})."
            )

        # Rule 2: Brier score must not worsen (lower or equal is better)
        brier_pass = (chall_p.brier_score - champ_p.brier_score) <= self.config.max_brier_worsening
        if brier_pass:
            rationale.append(
                f"Brier Score acceptable: {chall_p.brier_score:.4f} vs {champ_p.brier_score:.4f} "
                f"(delta: {delta['brier_score_delta']:+.4f} "
                f"<= +{self.config.max_brier_worsening:.4f})."
            )
        else:
            rationale.append(
                f"Brier Score worsened: {chall_p.brier_score:.4f} vs {champ_p.brier_score:.4f} "
                f"(delta: {delta['brier_score_delta']:+.4f} "
                f"> +{self.config.max_brier_worsening:.4f})."
            )

        # Rule 3: Max drawdown must not worsen beyond tolerance
        dd_pass = (
            chall_t.max_drawdown - champ_t.max_drawdown
        ) <= self.config.max_drawdown_increase
        if dd_pass:
            rationale.append(
                f"Drawdown within tolerance: {chall_t.max_drawdown:.2%} vs "
                f"{champ_t.max_drawdown:.2%} (delta: {delta['max_drawdown_delta']:+.2%})."
            )
        else:
            rationale.append(
                f"Drawdown worsened: {chall_t.max_drawdown:.2%} vs "
                f"{champ_t.max_drawdown:.2%} (delta: {delta['max_drawdown_delta']:+.2%} "
                f"> +{self.config.max_drawdown_increase:.2%})."
            )

        # Rule 4: Expectancy must not decrease
        exp_pass = (
            chall_t.expectancy - champ_t.expectancy
        ) >= self.config.min_expectancy_improvement
        if exp_pass:
            rationale.append(
                f"Expectancy acceptable: {chall_t.expectancy:.2%} vs {champ_t.expectancy:.2%} "
                f"(delta: {delta['expectancy_delta']:+.2%})."
            )
        else:
            rationale.append(
                f"Expectancy decreased: {chall_t.expectancy:.2%} vs {champ_t.expectancy:.2%} "
                f"(delta: {delta['expectancy_delta']:+.2%})."
            )

        all_rules_passed = pf_pass and brier_pass and dd_pass and exp_pass

        if all_rules_passed:
            recommendation = ComparisonRecommendation.PROMOTE.value
            rationale.append("Promotion gate passed: Challenger satisfies all criteria.")
        elif not pf_pass and not brier_pass and not dd_pass:
            recommendation = ComparisonRecommendation.REJECT.value
            rationale.append(
                "Promotion rejected: Challenger underperforms on core metrics."
            )
        elif not pf_pass or not dd_pass:
            recommendation = ComparisonRecommendation.REJECT.value
            rationale.append(
                "Promotion rejected: Profit factor failed to improve or drawdown deteriorated."
            )
        else:
            recommendation = ComparisonRecommendation.INCONCLUSIVE.value
            rationale.append(
                "Promotion inconclusive: Mixed indicators across trading and calibration."
            )

        return ComparisonReport(
            champion_version=champion_report.model_version,
            challenger_version=challenger_report.model_version,
            test_window=test_window,
            champion_metrics=champion_report,
            challenger_metrics=challenger_report,
            delta_metrics=delta,
            recommendation=recommendation,
            rationale=rationale,
        )

    def compare_models(
        self,
        champion_model: Any,
        challenger_model: Any,
        X_test: pd.DataFrame,
        y_test: np.ndarray,
        returns_test: np.ndarray,
        champion_version: str = "champion",
        challenger_version: str = "challenger",
        dataset_version: str = "v1.0.0",
        outcome_statuses: Optional[list[str]] = None,
        feature_names: Optional[list[str]] = None,
        test_window: Union[str, dict[str, Optional[str]]] = "",
    ) -> ComparisonReport:
        """Evaluates two model objects synchronously on test data and compares outcomes."""
        champ_report = self.engine.evaluate_model(
            model=champion_model,
            X=X_test,
            y_true=y_test,
            returns=returns_test,
            model_version=champion_version,
            dataset_version=dataset_version,
            outcome_statuses=outcome_statuses,
            feature_names=feature_names,
        )
        chall_report = self.engine.evaluate_model(
            model=challenger_model,
            X=X_test,
            y_true=y_test,
            returns=returns_test,
            model_version=challenger_version,
            dataset_version=dataset_version,
            outcome_statuses=outcome_statuses,
            feature_names=feature_names,
        )

        return self.compare_reports(
            champion_report=champ_report,
            challenger_report=chall_report,
            test_window=test_window,
        )

    def compare_from_registry(
        self,
        registry: ModelRegistry,
        champion_version: str,
        challenger_version: str,
        X_test: pd.DataFrame,
        y_test: np.ndarray,
        returns_test: np.ndarray,
        outcome_statuses: Optional[list[str]] = None,
        dataset_version: str = "v1.0.0",
        test_window: Union[str, dict[str, Optional[str]]] = "",
    ) -> ComparisonReport:
        """Loads models from ModelRegistry and runs identical evaluation & comparison."""
        champ_obj, champ_meta = registry.load_model(champion_version)
        chall_obj, chall_meta = registry.load_model(challenger_version)

        champ_features = champ_meta.feature_names if champ_meta.feature_names else None
        chall_features = chall_meta.feature_names if chall_meta.feature_names else None

        champ_report = self.engine.evaluate_model(
            model=champ_obj,
            X=X_test,
            y_true=y_test,
            returns=returns_test,
            model_version=champion_version,
            dataset_version=dataset_version,
            outcome_statuses=outcome_statuses,
            feature_names=champ_features,
        )
        chall_report = self.engine.evaluate_model(
            model=chall_obj,
            X=X_test,
            y_true=y_test,
            returns=returns_test,
            model_version=challenger_version,
            dataset_version=dataset_version,
            outcome_statuses=outcome_statuses,
            feature_names=chall_features,
        )

        return self.compare_reports(
            champion_report=champ_report,
            challenger_report=chall_report,
            test_window=test_window,
        )


def format_comparison_table(report: ComparisonReport) -> str:
    """Formats comparison report into clean ASCII comparison table."""
    c_t = report.champion_metrics.trading_metrics
    c_p = report.champion_metrics.prediction_metrics
    ch_t = report.challenger_metrics.trading_metrics
    ch_p = report.challenger_metrics.prediction_metrics
    d = report.delta_metrics

    s_champ = report.champion_metrics.sample_size
    s_chall = report.challenger_metrics.sample_size

    lines = [
        "=" * 78,
        f"MODEL COMPARISON: {report.champion_version} (Champ) vs "
        f"{report.challenger_version} (Challenger)",
        "=" * 78,
        f"Test Window: {report.test_window or 'Full Test Dataset'}",
        f"Sample Size: Champion={s_champ}, Challenger={s_chall}",
        "-" * 78,
        f"{'Metric':<26} | {'Champion':<14} | {'Challenger':<14} | {'Delta':<14}",
        "-" * 78,
        (
            f"{'Win Rate':<26} | {c_t.win_rate:<14.2%} | "
            f"{ch_t.win_rate:<14.2%} | {d.get('win_rate_delta', 0.0):<+14.2%}"
        ),
        (
            f"{'Profit Factor':<26} | {c_t.profit_factor:<14.2f} | "
            f"{ch_t.profit_factor:<14.2f} | {d.get('profit_factor_delta', 0.0):<+14.2f}"
        ),
        (
            f"{'Expectancy':<26} | {c_t.expectancy:<14.2%} | "
            f"{ch_t.expectancy:<14.2%} | {d.get('expectancy_delta', 0.0):<+14.2%}"
        ),
        (
            f"{'Max Drawdown':<26} | {c_t.max_drawdown:<14.2%} | "
            f"{ch_t.max_drawdown:<14.2%} | {d.get('max_drawdown_delta', 0.0):<+14.2%}"
        ),
        (
            f"{'Sharpe Ratio':<26} | {c_t.sharpe:<14.2f} | "
            f"{ch_t.sharpe:<14.2f} | {d.get('sharpe_delta', 0.0):<+14.2f}"
        ),
        (
            f"{'Brier Score (lower)':<26} | {c_p.brier_score:<14.4f} | "
            f"{ch_p.brier_score:<14.4f} | {d.get('brier_score_delta', 0.0):<+14.4f}"
        ),
        (
            f"{'ROC-AUC':<26} | {c_p.roc_auc:<14.4f} | "
            f"{ch_p.roc_auc:<14.4f} | {d.get('roc_auc_delta', 0.0):<+14.4f}"
        ),
        (
            f"{'Log Loss (lower)':<26} | {c_p.log_loss:<14.4f} | "
            f"{ch_p.log_loss:<14.4f} | {d.get('log_loss_delta', 0.0):<+14.4f}"
        ),
        (
            f"{'ECE (lower)':<26} | {c_p.ece:<14.4f} | "
            f"{ch_p.ece:<14.4f} | {d.get('ece_delta', 0.0):<+14.4f}"
        ),
        "-" * 78,
        f"RECOMMENDATION: {report.recommendation}",
        "-" * 78,
        "Rationale:",
    ]
    for r in report.rationale:
        lines.append(f" - {r}")
    lines.append("=" * 78)
    return "\n".join(lines)


def format_comparison_markdown(report: ComparisonReport) -> str:
    """Formats comparison report as GitHub Markdown."""
    c_t = report.champion_metrics.trading_metrics
    c_p = report.champion_metrics.prediction_metrics
    ch_t = report.challenger_metrics.trading_metrics
    ch_p = report.challenger_metrics.prediction_metrics
    d = report.delta_metrics

    md = [
        f"## Model Evaluation Comparison: `{report.champion_version}` vs "
        f"`{report.challenger_version}`",
        "",
        f"- **Test Window**: {report.test_window or 'Full Test Dataset'}",
        (
            f"- **Sample Size**: Champion={report.champion_metrics.sample_size}, "
            f"Challenger={report.challenger_metrics.sample_size}"
        ),
        f"- **Decision**: **{report.recommendation}**",
        "",
        "| Metric | Champion | Challenger | Delta |",
        "|---|---|---|---|",
        f"| **Win Rate** | {c_t.win_rate:.2%} | {ch_t.win_rate:.2%} | "
        f"{d.get('win_rate_delta', 0.0):+.2%} |",
        f"| **Profit Factor** | {c_t.profit_factor:.2f} | {ch_t.profit_factor:.2f} | "
        f"{d.get('profit_factor_delta', 0.0):+.2f} |",
        f"| **Expectancy** | {c_t.expectancy:.2%} | {ch_t.expectancy:.2%} | "
        f"{d.get('expectancy_delta', 0.0):+.2%} |",
        f"| **Max Drawdown** | {c_t.max_drawdown:.2%} | {ch_t.max_drawdown:.2%} | "
        f"{d.get('max_drawdown_delta', 0.0):+.2%} |",
        f"| **Sharpe Ratio** | {c_t.sharpe:.2f} | {ch_t.sharpe:.2f} | "
        f"{d.get('sharpe_delta', 0.0):+.2f} |",
        f"| **Brier Score** | {c_p.brier_score:.4f} | {ch_p.brier_score:.4f} | "
        f"{d.get('brier_score_delta', 0.0):+.4f} |",
        f"| **ROC-AUC** | {c_p.roc_auc:.4f} | {ch_p.roc_auc:.4f} | "
        f"{d.get('roc_auc_delta', 0.0):+.4f} |",
        f"| **Log Loss** | {c_p.log_loss:.4f} | {ch_p.log_loss:.4f} | "
        f"{d.get('log_loss_delta', 0.0):+.4f} |",
        f"| **ECE** | {c_p.ece:.4f} | {ch_p.ece:.4f} | "
        f"{d.get('ece_delta', 0.0):+.4f} |",
        "",
        "### Rationale",
    ]
    for r in report.rationale:
        md.append(f"- {r}")
    return "\n".join(md)


def format_comparison_json(report: ComparisonReport) -> str:
    """Formats comparison report as formatted JSON."""
    return json.dumps(report.to_dict(), indent=2)
