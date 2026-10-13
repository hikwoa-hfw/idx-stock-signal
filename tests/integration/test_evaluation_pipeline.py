import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from python.models.baseline import LogisticRegressionBaseline
from python.models.comparator import (
    ModelComparator,
    PromotionGateConfig,
    format_comparison_markdown,
    format_comparison_table,
)
from python.models.evaluation import EvaluationEngine
from python.models.registry import ModelMetadata, ModelRegistry


def test_end_to_end_evaluation_pipeline(tmp_path: Path):
    registry_dir = tmp_path / "models_registry"
    registry = ModelRegistry(registry_dir=registry_dir)
    engine = EvaluationEngine()
    comparator = ModelComparator(
        config=PromotionGateConfig(min_sample_size=20),
        evaluation_engine=engine,
    )

    # 1. Train champion and challenger models on synthetic dataset
    np.random.seed(42)
    n_train = 120
    X_train = pd.DataFrame(
        {
            "f1": np.random.randn(n_train),
            "f2": np.random.randn(n_train),
        }
    )
    y_train = (X_train["f1"] + X_train["f2"] > 0).astype(int).to_numpy()

    champ_model = LogisticRegressionBaseline(C=0.1)
    champ_model.fit(X_train, y_train)
    champ_meta = ModelMetadata(
        model_version="champ_v1",
        algorithm="LogisticRegression",
        training_start="2026-01-01",
        training_end="2026-06-30",
        status="champion",
        feature_names=["f1", "f2"],
    )
    registry.save_model(champ_model, champ_meta)

    chall_model = LogisticRegressionBaseline(C=1.0)
    chall_model.fit(X_train, y_train)
    chall_meta = ModelMetadata(
        model_version="chall_v2",
        algorithm="LogisticRegression",
        training_start="2026-01-01",
        training_end="2026-06-30",
        status="challenger",
        feature_names=["f1", "f2"],
    )
    registry.save_model(chall_model, chall_meta)

    # 2. Prepare out-of-sample test dataset
    n_test = 50
    X_test = pd.DataFrame(
        {
            "f1": np.random.randn(n_test),
            "f2": np.random.randn(n_test),
        }
    )
    y_test = (X_test["f1"] + X_test["f2"] > 0).astype(int).to_numpy()
    returns_test = np.where(y_test == 1, 0.05, -0.02)
    statuses_test = ["TP" if y == 1 else "SL" for y in y_test]

    # 3. Compare from registry
    report = comparator.compare_from_registry(
        registry=registry,
        champion_version="champ_v1",
        challenger_version="chall_v2",
        X_test=X_test,
        y_test=y_test,
        returns_test=returns_test,
        outcome_statuses=statuses_test,
        test_window="2026-07-01 to 2026-09-30",
    )

    assert report.champion_version == "champ_v1"
    assert report.challenger_version == "chall_v2"
    assert report.champion_metrics.sample_size == n_test
    assert report.challenger_metrics.sample_size == n_test
    assert report.recommendation in ["PROMOTE", "REJECT", "INCONCLUSIVE"]
    assert len(report.rationale) > 0

    table_str = format_comparison_table(report)
    assert "MODEL COMPARISON" in table_str
    md_str = format_comparison_markdown(report)
    assert "## Model Evaluation Comparison" in md_str


def test_evaluate_models_cli_invocation(tmp_path: Path):
    # Create test CSV dataset
    dataset_path = tmp_path / "test_outcomes.csv"
    report_path = tmp_path / "comparison_report.md"

    np.random.seed(42)
    n = 40
    df = pd.DataFrame(
        {
            "ticker": ["BBCA"] * n,
            "signal_date": ["2026-10-01"] * n,
            "entry_date": ["2026-10-02"] * n,
            "entry_price": [10000.0] * n,
            "outcome_status": ["TP" if i % 2 == 0 else "SL" for i in range(n)],
            "binary_target": [1 if i % 2 == 0 else 0 for i in range(n)],
            "realized_return": [0.05 if i % 2 == 0 else -0.02 for i in range(n)],
            "predicted_probability": [0.75 if i % 2 == 0 else 0.25 for i in range(n)],
            "holding_days": [3] * n,
        }
    )
    df.to_csv(dataset_path, index=False)

    # Invoke evaluate_models.py via CLI
    cmd = [
        sys.executable,
        "-m",
        "scripts.evaluate_models",
        "--champion-version",
        "baseline_v1",
        "--challenger-version",
        "candidate_v2",
        "--dataset-path",
        str(dataset_path),
        "--output-format",
        "markdown",
        "--save-report",
        str(report_path),
        "--min-sample-size",
        "20",
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"CLI error: {res.stderr}"
    assert "Model Evaluation Comparison" in res.stdout
    assert report_path.is_file()
    assert "## Model Evaluation Comparison" in report_path.read_text(encoding="utf-8")


def test_evaluate_models_cli_single_model(tmp_path: Path):
    dataset_path = tmp_path / "test_outcomes.csv"
    df = pd.DataFrame(
        {
            "binary_target": [1, 0, 1, 0, 1],
            "realized_return": [0.05, -0.02, 0.04, -0.01, 0.03],
            "predicted_probability": [0.8, 0.2, 0.7, 0.3, 0.6],
            "outcome_status": ["TP", "SL", "TP", "SL", "TP"],
        }
    )
    df.to_csv(dataset_path, index=False)

    cmd = [
        sys.executable,
        "-m",
        "scripts.evaluate_models",
        "--champion-version",
        "test_champ",
        "--dataset-path",
        str(dataset_path),
        "--output-format",
        "json",
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"CLI error: {res.stderr}"
    parsed = json.loads(res.stdout)
    assert parsed["model_version"] == "test_champ"
    assert parsed["sample_size"] == 5
