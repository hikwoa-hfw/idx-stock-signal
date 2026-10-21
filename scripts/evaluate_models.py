import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from python.common.types import ComparisonRecommendation
from python.config.settings import settings
from python.models.comparator import (
    ModelComparator,
    PromotionGateConfig,
    format_comparison_json,
    format_comparison_markdown,
    format_comparison_table,
)
from python.models.evaluation import EvaluationEngine
from python.models.registry import ModelRegistry
from python.outcomes.dataset import build_matured_outcomes_dataset
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _load_dataset(
    dataset_path: Optional[str] = None,
    from_outcomes: bool = False,
    mode: Optional[str] = None,
) -> pd.DataFrame:
    """Loads evaluation dataset from CSV/Parquet file or database matured outcomes."""
    eff_mode = mode.strip().upper() if mode and mode != "ALL" else None
    if from_outcomes:
        outcome_repo = OutcomeRepository()
        signal_repo = SignalRepository()
        df = build_matured_outcomes_dataset(
            outcome_repo=outcome_repo,
            signal_repo=signal_repo,
            mode=eff_mode,
            exclude_ambiguous=True,
        )
        if df.empty:
            print("[WARN] No matured outcomes found in outcomes repository.", file=sys.stderr)
        return df

    if dataset_path:
        p = Path(dataset_path)
        if not p.is_file():
            print(f"[ERROR] Dataset file not found: {dataset_path}", file=sys.stderr)
            sys.exit(1)
        if p.suffix.lower() == ".parquet":
            df = pd.read_parquet(p)
        else:
            df = pd.read_csv(p)
        if eff_mode and "mode" in df.columns:
            df = df[df["mode"].astype(str).str.upper() == eff_mode].reset_index(drop=True)
        return df

    # Fallback to matured outcomes if available, else empty DataFrame
    outcome_repo = OutcomeRepository()
    signal_repo = SignalRepository()
    df = build_matured_outcomes_dataset(
        outcome_repo=outcome_repo,
        signal_repo=signal_repo,
        mode=eff_mode,
        exclude_ambiguous=True,
    )
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate model metrics and perform Champion vs. Challenger comparison."
    )
    parser.add_argument(
        "--champion-version",
        type=str,
        default=None,
        help="Champion model version string (default: current champion in registry).",
    )
    parser.add_argument(
        "--challenger-version",
        type=str,
        default=None,
        help="Challenger model version string to compare against champion.",
    )
    parser.add_argument(
        "--dataset-path",
        type=str,
        default=None,
        help="Path to CSV or Parquet test dataset.",
    )
    parser.add_argument(
        "--from-outcomes",
        action="store_true",
        help="Build evaluation dataset directly from matured outcomes database.",
    )
    parser.add_argument(
        "--output-format",
        choices=["table", "json", "markdown"],
        default="table",
        help="Output presentation format.",
    )
    parser.add_argument(
        "--filter-by-prediction",
        action="store_true",
        help="Only evaluate trades where predicted probability >= threshold.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Probability decision threshold for trade filtering (default: 0.5).",
    )
    parser.add_argument(
        "--save-report",
        type=str,
        default=None,
        help="File path to save the generated comparison or evaluation report.",
    )
    parser.add_argument(
        "--min-sample-size",
        type=int,
        default=30,
        help="Minimum required sample size for promotion readiness.",
    )
    parser.add_argument(
        "--promote-if-passed",
        action="store_true",
        help="Automatically promote challenger to champion if recommendation is PROMOTE.",
    )
    parser.add_argument(
        "--mode",
        choices=["LOW_PRICE", "HIGHER_PRICE", "ALL"],
        default=None,
        help="Price regime filter: LOW_PRICE, HIGHER_PRICE, or ALL (default: evaluate all).",
    )

    args = parser.parse_args()

    registry = ModelRegistry()
    engine = EvaluationEngine()
    config = PromotionGateConfig(min_sample_size=args.min_sample_size)
    comparator = ModelComparator(config=config, evaluation_engine=engine)

    # Determine champion version
    champ_ver = args.champion_version
    if not champ_ver:
        champ_meta = registry.get_champion(mode=args.mode)
        if champ_meta:
            champ_ver = champ_meta[1].model_version
        else:
            champ_ver = "champion_default"

    chall_ver = args.challenger_version

    df = _load_dataset(
        dataset_path=args.dataset_path,
        from_outcomes=args.from_outcomes,
        mode=args.mode,
    )

    if df.empty:
        print("[INFO] Evaluation dataset is empty. Nothing to evaluate.")
        return

    # If both models provided, run comparison
    if chall_ver:
        # Check if models are in registry
        has_champ_artifact = (settings.model_registry_path / f"{champ_ver}.joblib").is_file()
        has_chall_artifact = (settings.model_registry_path / f"{chall_ver}.joblib").is_file()

        if has_champ_artifact and has_chall_artifact:
            # Extract features and target
            y_test = (
                df["binary_target"].to_numpy(dtype=float)
                if "binary_target" in df.columns
                else np.array([])
            )
            ret_test = (
                df["realized_return"].to_numpy(dtype=float)
                if "realized_return" in df.columns
                else np.array([])
            )
            statuses = df["outcome_status"].tolist() if "outcome_status" in df.columns else None

            # Drop non-feature columns
            drop_cols = [
                "outcome_id",
                "signal_id",
                "ticker",
                "signal_date",
                "entry_date",
                "entry_price",
                "outcome_status",
                "binary_target",
                "realized_return",
                "holding_days",
                "mfe",
                "mae",
                "exit_date",
                "exit_price",
                "exit_reason",
                "resolved_at",
                "notes",
                "predicted_probability",
                "expected_return",
                "signal_score",
                "model_version",
                "feature_version",
                "signal_config_version",
                "signal_created_at",
            ]
            feature_cols = [c for c in df.columns if c not in drop_cols]
            X_test = df[feature_cols]

            report = comparator.compare_from_registry(
                registry=registry,
                champion_version=champ_ver,
                challenger_version=chall_ver,
                X_test=X_test,
                y_test=y_test,
                returns_test=ret_test,
                outcome_statuses=statuses,
                filter_by_prediction=args.filter_by_prediction,
                decision_threshold=args.threshold,
            )
        else:
            # Evaluate using dataframe predictions if models are not registry artifacts
            champ_report = engine.evaluate_dataset(df, model_version=champ_ver)
            chall_report = engine.evaluate_dataset(df, model_version=chall_ver)
            report = comparator.compare_reports(
                champion_report=champ_report,
                challenger_report=chall_report,
            )

        # Output format
        if args.output_format == "json":
            out_str = format_comparison_json(report)
        elif args.output_format == "markdown":
            out_str = format_comparison_markdown(report)
        else:
            out_str = format_comparison_table(report)

        print(out_str)

        if args.save_report:
            save_p = Path(args.save_report)
            save_p.parent.mkdir(parents=True, exist_ok=True)
            save_p.write_text(out_str, encoding="utf-8")
            print(f"[INFO] Report saved to {save_p}")

        should_promote = (
            args.promote_if_passed
            and report.recommendation == ComparisonRecommendation.PROMOTE.value
        )
        if should_promote:
            if has_chall_artifact:
                registry.promote_to_champion(chall_ver, mode=args.mode)
                print(
                    f"[SUCCESS] Model '{chall_ver}' successfully promoted to champion in registry."
                )
            else:
                print(f"[WARN] Cannot promote '{chall_ver}': artifact not found in registry.")

    else:
        # Single model evaluation
        rep = engine.evaluate_dataset(df, model_version=champ_ver)
        if args.output_format == "json":
            import json

            out_str = json.dumps(rep.to_dict(), indent=2)
        elif args.output_format == "markdown":
            t = rep.trading_metrics
            p = rep.prediction_metrics
            md_lines = [
                f"## Model Evaluation Report: `{rep.model_version}`",
                "",
                f"- **Sample Size**: {rep.sample_size}",
                "",
                "| Metric | Value |",
                "|---|---|",
                f"| **Win Rate** | {t.win_rate:.2%} |",
                f"| **Profit Factor** | {t.profit_factor:.2f} |",
                f"| **Expectancy** | {t.expectancy:.2%} |",
                f"| **Max Drawdown** | {t.max_drawdown:.2%} |",
                f"| **Sharpe Ratio** | {t.sharpe:.2f} |",
                f"| **Avg Win** | {t.avg_win:.2%} |",
                f"| **Avg Loss** | {t.avg_loss:.2%} |",
                f"| **Brier Score** | {p.brier_score:.4f} |",
                f"| **ROC-AUC** | {p.roc_auc:.4f} |",
                f"| **Log Loss** | {p.log_loss:.4f} |",
                f"| **ECE** | {p.ece:.4f} |",
            ]
            out_str = "\n".join(md_lines)
        else:
            t = rep.trading_metrics
            p = rep.prediction_metrics
            lines = [
                "=" * 70,
                f"MODEL EVALUATION REPORT: {rep.model_version}",
                "=" * 70,
                f"Sample Size:  {rep.sample_size}",
                f"Win Rate:     {t.win_rate:.2%}",
                f"Profit Factor:{t.profit_factor:.2f}",
                f"Expectancy:   {t.expectancy:.2%}",
                f"Max Drawdown: {t.max_drawdown:.2%}",
                f"Sharpe Ratio: {t.sharpe:.2f}",
                f"Avg Win:      {t.avg_win:.2%}",
                f"Avg Loss:     {t.avg_loss:.2%}",
                f"Brier Score:  {p.brier_score:.4f}",
                f"ROC-AUC:      {p.roc_auc:.4f}",
                f"Log Loss:     {p.log_loss:.4f}",
                f"ECE:          {p.ece:.4f}",
                "=" * 70,
            ]
            out_str = "\n".join(lines)
        print(out_str)

        if args.save_report:
            save_p = Path(args.save_report)
            save_p.parent.mkdir(parents=True, exist_ok=True)
            save_p.write_text(out_str, encoding="utf-8")
            print(f"[INFO] Report saved to {save_p}")


if __name__ == "__main__":
    main()
