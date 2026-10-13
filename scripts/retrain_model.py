import argparse
import json
import sys
from typing import Optional

from python.config.settings import settings
from python.models.registry import ModelRegistry
from python.retraining.gate import PromotionGateManager
from python.retraining.pipeline import RetrainingPipeline, RetrainingPipelineConfig

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retraining Pipeline CLI Orchestrator (Phase 11)."
    )
    parser.add_argument(
        "--check-trigger-only",
        action="store_true",
        help="Evaluate trigger conditions only without running training.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force retraining regardless of trigger threshold or degradation.",
    )
    parser.add_argument(
        "--min-matured",
        type=int,
        default=200,
        help="Minimum matured outcomes count to trigger retraining (default: 200).",
    )
    parser.add_argument(
        "--auto-promote",
        action="store_true",
        help="Automatically promote challenger to champion if promotion gate passes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run retraining and evaluation without saving artifact or altering registry.",
    )
    parser.add_argument(
        "--rollback-to",
        type=str,
        default=None,
        help="Revert champion to specified version or 'last' for previous champion.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Revert champion to last known good champion.",
    )
    parser.add_argument(
        "--algorithm",
        choices=["lightgbm", "logistic"],
        default="lightgbm",
        help="Algorithm for challenger model: lightgbm or logistic (default: lightgbm).",
    )
    parser.add_argument(
        "--task",
        choices=["classification"],
        default="classification",
        help="Task type (default: classification).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLite database URL. Defaults to settings.database_url.",
    )
    parser.add_argument(
        "--output-format",
        choices=["table", "json", "markdown"],
        default="table",
        help="Output presentation format (default: table).",
    )
    return parser.parse_args()


def format_trigger_output(res: object, fmt: str) -> str:
    from python.retraining.trigger import RetrainingTriggerResult

    if not isinstance(res, RetrainingTriggerResult):
        return str(res)

    if fmt == "json":
        return json.dumps(
            {
                "should_retrain": res.should_retrain,
                "matured_count": res.matured_count,
                "rolling_win_rate": res.rolling_win_rate,
                "rolling_brier": res.rolling_brier,
                "reasons": res.reasons,
                "evaluated_at": res.evaluated_at,
            },
            indent=2,
        )

    if fmt == "markdown":
        status_badge = "**TRIGGERED**" if res.should_retrain else "**IDLE**"
        reasons_md = "\n".join(f"- {r}" for r in res.reasons)
        wr_str = f"{res.rolling_win_rate:.2%}" if res.rolling_win_rate is not None else "N/A"
        brier_str = f"{res.rolling_brier:.4f}" if res.rolling_brier is not None else "N/A"
        return (
            f"### Retraining Trigger Evaluation\n\n"
            f"- **Status:** {status_badge}\n"
            f"- **Matured Outcomes:** {res.matured_count}\n"
            f"- **Rolling Win Rate:** {wr_str}\n"
            f"- **Rolling Brier Score:** {brier_str}\n\n"
            f"#### Trigger Reasons:\n{reasons_md}"
        )

    # Table / Plain format
    status_str = "TRIGGERED" if res.should_retrain else "IDLE"
    wr_str = f"{res.rolling_win_rate:.2%}" if res.rolling_win_rate is not None else "N/A"
    brier_str = f"{res.rolling_brier:.4f}" if res.rolling_brier is not None else "N/A"
    lines = [
        "=" * 65,
        " AI BEI Stock Signal — Retraining Trigger Status",
        "=" * 65,
        f"Status:             [{status_str}]",
        f"Matured Outcomes:   {res.matured_count}",
        f"Rolling Win Rate:   {wr_str}",
        f"Rolling Brier:      {brier_str}",
        "Reasons:",
    ]
    for r in res.reasons:
        lines.append(f"  * {r}")
    lines.append("=" * 65)
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    db_url = args.db_url or settings.database_url
    registry = ModelRegistry()
    gate_mgr = PromotionGateManager(registry=registry)

    # 1. Handle Rollback Command
    if args.rollback or args.rollback_to:
        target_version: Optional[str] = args.rollback_to
        if target_version and target_version.strip().lower() in ("last", "prev", "previous"):
            target_version = None

        try:
            restored_meta = gate_mgr.rollback(
                target_version=target_version,
                task=args.task,
                demote_current_to="retired",
            )
            print("=" * 65)
            print(" AI BEI Stock Signal — Champion Rollback")
            print("=" * 65)
            print("Action:             RESTORED TO CHAMPION")
            print(f"Model Version:      {restored_meta.model_version}")
            print(f"Algorithm:          {restored_meta.algorithm}")
            print(f"Status:             {restored_meta.status}")
            print(f"Dataset Version:    {restored_meta.dataset_version}")
            print("=" * 65)
            return
        except Exception as e:
            print(f"[Rollback Error] {e}", file=sys.stderr)
            sys.exit(1)

    # 2. Configure Retraining Pipeline
    config = RetrainingPipelineConfig(
        algorithm=args.algorithm,
        task=args.task,
        min_matured_samples=args.min_matured,
        auto_promote=args.auto_promote,
        force=args.force,
        dry_run=args.dry_run,
    )

    from python.outcomes.repository import OutcomeRepository
    from python.signals.repository import SignalRepository

    outcome_repo = OutcomeRepository(db_url)
    signal_repo = SignalRepository(db_url)

    from python.retraining.trigger import (
        RetrainingTriggerConfig,
        RetrainingTriggerEvaluator,
    )

    trigger_cfg = RetrainingTriggerConfig(
        min_matured_samples=args.min_matured,
        force=args.force,
    )
    trigger_eval = RetrainingTriggerEvaluator(
        config=trigger_cfg,
        outcome_repo=outcome_repo,
        signal_repo=signal_repo,
    )

    from python.retraining.dataset import RetrainingDatasetAssembler

    assembler = RetrainingDatasetAssembler(
        outcome_repo=outcome_repo,
        signal_repo=signal_repo,
    )

    pipeline = RetrainingPipeline(
        config=config,
        trigger_evaluator=trigger_eval,
        dataset_assembler=assembler,
        gate_manager=gate_mgr,
        registry=registry,
    )

    # 3. Check trigger only
    if args.check_trigger_only:
        trig_res = trigger_eval.evaluate(
            force=args.force,
            min_matured_samples=args.min_matured,
        )
        print(format_trigger_output(trig_res, args.output_format))
        return

    # 4. Run Retraining Pipeline
    res = pipeline.run(
        force=args.force,
        auto_promote=args.auto_promote,
        dry_run=args.dry_run,
    )

    if res.status == "SKIPPED":
        if args.output_format == "json":
            print(
                json.dumps(
                    {
                        "status": "SKIPPED",
                        "triggered": False,
                        "reasons": res.trigger_result.reasons if res.trigger_result else [],
                    },
                    indent=2,
                )
            )
        else:
            matured_n = res.trigger_result.matured_count if res.trigger_result else 0
            print(f"[Retrain Skipped] Triggers not met ({matured_n} matured).")
            if res.trigger_result:
                for r in res.trigger_result.reasons:
                    print(f"  * {r}")
        return

    if res.status == "FAILED":
        print(f"[Retrain Failed] {res.error_message}", file=sys.stderr)
        sys.exit(1)

    # 5. Output Results
    if args.output_format == "json":
        data = {
            "status": res.status,
            "challenger_version": res.challenger_version,
            "champion_version": res.champion_version,
            "promoted": res.promoted,
            "train_sample_count": res.train_sample_count,
            "test_sample_count": res.test_sample_count,
            "metrics": res.metrics,
            "gate_recommendation": res.gate_result.recommendation if res.gate_result else None,
            "gate_rationale": res.gate_result.rationale if res.gate_result else [],
        }
        print(json.dumps(data, indent=2))
        return

    if args.output_format == "markdown":
        rec_str = res.gate_result.recommendation if res.gate_result else "N/A"
        print("### Retraining Pipeline Execution Summary\n")
        print(f"- **Challenger Version:** `{res.challenger_version}`")
        print(f"- **Champion Version:** `{res.champion_version}`")
        print(f"- **Gate Recommendation:** **{rec_str}**")
        print(f"- **Promoted:** **{res.promoted}**")
        print(
            f"- **Train Samples:** {res.train_sample_count} | "
            f"**Test Samples:** {res.test_sample_count}"
        )
        print("\n#### Test Metrics:")
        for k, v in res.metrics.items():
            print(f"- **{k}:** {v:.4f}")
        if res.gate_result and res.gate_result.rationale:
            print("\n#### Gate Rationale:")
            for rat in res.gate_result.rationale:
                print(f"- {rat}")
        return

    # Table format
    print("=" * 65)
    print(" AI BEI Stock Signal — Retraining Pipeline (Phase 11)")
    print("=" * 65)
    print(f"Challenger Version:  {res.challenger_version}")
    print(f"Current Champion:    {res.champion_version or 'None (Bootstrap)'}")
    print(f"Train Samples:       {res.train_sample_count}")
    print(f"Test Samples:        {res.test_sample_count}")
    if res.artifact_path:
        print(f"Artifact Saved:      {res.artifact_path}")
    print("\n--- Challenger Test Metrics ---")
    for k, v in res.metrics.items():
        print(f"  {k:18s}: {v:.4f}")

    if res.gate_result:
        print("\n--- Promotion Gate Evaluation ---")
        print(f"Recommendation:      {res.gate_result.recommendation}")
        print(f"Passed:              {res.gate_result.passed}")
        print(f"Promoted to Champ:   {res.promoted}")
        print("Rationale:")
        for rat in res.gate_result.rationale:
            print(f"  * {rat}")
    print("=" * 65)


if __name__ == "__main__":
    main()
