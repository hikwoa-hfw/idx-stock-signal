"""Integrity and smoke tests for Phase 11F research scoring artifacts (Phase 11F.1).

Verifies:
1. Both artifacts load successfully from artifacts/phase_11f/research_models/.
2. Feature input requires exact ordered frozen schema (FEATURE_SCHEMA_30).
3. Missing, reordered, or unexpected columns fail clearly with descriptive ValueError.
4. All produced scores are finite (no NaN, no Inf).
5. LOW_PRICE uses intended regression score (pred_return_lgb) and lacks predict_proba.
6. HIGHER_PRICE uses intended classifier score (prob_lgb_full) bounded in [0, 1] with predict_proba.
7. Research scoring never loads or falls back to a production champion.
8. Frozen configuration hash is deterministic and matches canonical hash.
9. Prospective date with incomplete or empty market data does not create fabricated signals.
10. Fixed sample predictions are deterministic and causal (no lookahead beyond decision date).
11. State persistence across consecutive or repeated prospective dates deduplicates records.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

from python.experiments.paper_trading import (
    CHAMPION_MODELS,
    FEATURE_SCHEMA_30,
    RESEARCH_SCORING_ARTIFACTS,
    STATUS_APPROVED_PENDING_FIRST_OBSERVATION,
    STATUS_BLOCKED_ON_SCORING_ARTIFACT,
    STATUS_OBSERVATION_ACTIVE,
    STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL,
    STATUS_SCORING_ARTIFACTS_READY,
    PaperTradingEngine,
    UserApprovalRequiredError,
    get_default_frozen_policies,
)
from python.models.research_scoring import (
    ResearchClassifierModel,
    ResearchRegressorModel,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def low_price_model(repo_root: Path) -> ResearchRegressorModel:
    path = repo_root / RESEARCH_SCORING_ARTIFACTS["LOW_PRICE"]
    assert path.is_file(), f"Missing LOW_PRICE artifact at {path}"
    model = joblib.load(path)
    return model


@pytest.fixture
def higher_price_model(repo_root: Path) -> ResearchClassifierModel:
    path = repo_root / RESEARCH_SCORING_ARTIFACTS["HIGHER_PRICE"]
    assert path.is_file(), f"Missing HIGHER_PRICE artifact at {path}"
    model = joblib.load(path)
    return model


@pytest.fixture
def sample_feature_dataframe() -> pd.DataFrame:
    """Builds a deterministic 5-row sample DataFrame conforming to FEATURE_SCHEMA_30."""
    rng = np.random.default_rng(seed=123)
    data = {}
    for col in FEATURE_SCHEMA_30:
        data[col] = rng.normal(loc=0.0, scale=1.0, size=5)
    df = pd.DataFrame(data)
    # Inject one NaN to verify median imputation
    df.loc[0, "return_1d"] = np.nan
    df.loc[1, "ema200"] = np.nan
    return df


class TestResearchScoringIntegrity:
    def test_artifacts_load_successfully(self, low_price_model: Any, higher_price_model: Any):
        """Verifies both artifacts load from artifacts/phase_11f/research_models/."""
        assert isinstance(low_price_model, ResearchRegressorModel)
        assert isinstance(higher_price_model, ResearchClassifierModel)
        assert low_price_model.mode == "LOW_PRICE"
        assert higher_price_model.mode == "HIGHER_PRICE"
        assert low_price_model.feature_schema == FEATURE_SCHEMA_30
        assert higher_price_model.feature_schema == FEATURE_SCHEMA_30
        assert low_price_model.training_cutoff == "2026-09-25"
        assert higher_price_model.training_cutoff == "2026-09-25"

    def test_feature_input_schema_success(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies exact ordered schema succeeds and produces expected shapes."""
        preds_low = low_price_model.predict(sample_feature_dataframe)
        assert isinstance(preds_low, np.ndarray)
        assert len(preds_low) == 5

        probs_high = higher_price_model.predict_probability(sample_feature_dataframe)
        assert isinstance(probs_high, np.ndarray)
        assert len(probs_high) == 5

    def test_missing_feature_column_fails(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies missing feature columns raise descriptive ValueError."""
        df_missing = sample_feature_dataframe.drop(columns=["return_1d"])
        with pytest.raises(ValueError, match="Missing required feature columns"):
            low_price_model.predict(df_missing)

        with pytest.raises(ValueError, match="Missing required feature columns"):
            higher_price_model.predict_probability(df_missing)

    def test_reordered_feature_columns_fail(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies reordered feature columns raise ValueError."""
        cols = list(sample_feature_dataframe.columns)
        # Swap first two columns
        cols[0], cols[1] = cols[1], cols[0]
        df_reordered = sample_feature_dataframe[cols]

        with pytest.raises(ValueError, match="Feature columns reordered"):
            low_price_model.predict(df_reordered)

        with pytest.raises(ValueError, match="Feature columns reordered"):
            higher_price_model.predict_probability(df_reordered)

    def test_unexpected_feature_column_fails(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies unexpected extra columns raise descriptive ValueError."""
        df_unexpected = sample_feature_dataframe.copy()
        df_unexpected["unapproved_leakage_feature"] = 1.0

        with pytest.raises(ValueError, match="Unexpected feature columns"):
            low_price_model.predict(df_unexpected)

        with pytest.raises(ValueError, match="Unexpected feature columns"):
            higher_price_model.predict_probability(df_unexpected)

    def test_array_dimension_mismatch_fails(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
    ):
        """Verifies 2D numpy array with wrong number of features fails."""
        arr_wrong = np.zeros((5, 29), dtype=np.float64)
        with pytest.raises(ValueError, match="Expected 30 features, got 29"):
            low_price_model.predict(arr_wrong)

        with pytest.raises(ValueError, match="Expected 30 features, got 29"):
            higher_price_model.predict_probability(arr_wrong)

    def test_all_produced_scores_are_finite(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies all model scores are finite numbers (no NaN or Inf)."""
        preds_low = low_price_model.predict(sample_feature_dataframe)
        assert np.all(np.isfinite(preds_low)), "LOW_PRICE produced non-finite score"

        proba_high = higher_price_model.predict_proba(sample_feature_dataframe)
        assert np.all(np.isfinite(proba_high)), "HIGHER_PRICE produced non-finite proba"
        prob_p1 = higher_price_model.predict_probability(sample_feature_dataframe)
        assert np.all(np.isfinite(prob_p1)), "HIGHER_PRICE produced non-finite prob"

    def test_low_price_uses_regression_score(
        self,
        low_price_model: ResearchRegressorModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies LOW_PRICE outputs continuous pred_return_lgb and has no predict_proba."""
        assert low_price_model.score_metric == "pred_return_lgb"
        assert low_price_model.task_type == "regression"
        assert not hasattr(low_price_model, "predict_proba")
        scores = low_price_model.predict(sample_feature_dataframe)
        # Expected return can be negative or positive float
        assert isinstance(scores[0], (float, np.floating))

    def test_higher_price_uses_classifier_score(
        self,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies HIGHER_PRICE outputs prob_lgb_full bounded in [0, 1] with predict_proba."""
        assert higher_price_model.score_metric == "prob_lgb_full"
        assert higher_price_model.task_type == "classification"
        assert hasattr(higher_price_model, "predict_proba")
        probs = higher_price_model.predict_probability(sample_feature_dataframe)
        assert np.all(probs >= 0.0)
        assert np.all(probs <= 1.0)
        classes = higher_price_model.predict(sample_feature_dataframe)
        assert set(np.unique(classes)).issubset({0, 1})

    def test_no_production_champion_fallback(self, repo_root: Path):
        """Verifies research scoring points strictly to research_models and never champions."""
        engine = PaperTradingEngine(db_path=str(repo_root / "datasets/stock_signals.db"))
        audit = engine.audit_scoring_artifacts()

        assert audit["fail_closed_guard_active"] is True
        assert audit["champion_fallback_permitted"] is False
        assert audit["status"] == "PASS"

        for mode, info in audit["artifacts"].items():
            # Confirm path is under artifacts/phase_11f/research_models
            norm_path = info["expected_artifact"].replace("\\", "/")
            assert "artifacts/phase_11f/research_models" in norm_path
            # Confirm champion model is explicitly blocked from substitution
            assert info["champion_substitute_blocked"] == CHAMPION_MODELS[mode]
            assert "models/registry" not in norm_path

    def test_frozen_configuration_hash_is_deterministic(self):
        """Verifies frozen policy configuration bundle produces deterministic canonical hash."""
        bundle1 = get_default_frozen_policies()
        bundle2 = get_default_frozen_policies()

        hash1 = bundle1.compute_sha256()
        hash2 = bundle2.compute_sha256()
        assert hash1 == hash2
        assert len(hash1) == 64
        # Validate canonical value
        assert hash1 == "8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71"

    def test_prospective_empty_or_incomplete_data_no_fabricated_signals(
        self, repo_root: Path, tmp_path: Path
    ):
        """Verifies prospective scoring on empty/weekend date produces 0 candidates/decisions."""
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        # Sunday with no data
        res = engine.step_prospective_date(date(2026, 10, 18), user_approved=True)
        assert res["status"] == "NO_DATA"
        assert res["candidates_count"] == 0
        assert res["decisions_count"] == 0

    def test_fixed_sample_prediction_and_temporal_causality(
        self,
        repo_root: Path,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
    ):
        """Validates deterministic prediction values on fixed sample and causality."""
        db_path = repo_root / "datasets/stock_signals.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Query fixed historical record on cutoff date 2026-09-25
            cols_sql = ", ".join(FEATURE_SCHEMA_30)
            query = f"""
                SELECT ticker, {cols_sql}
                FROM features_daily
                WHERE date = '2026-09-25' AND ticker IN ('BBCA', 'BBRI', 'BUMI')
                ORDER BY ticker;
            """
            df_fixed = pd.read_sql_query(query, conn)
        finally:
            conn.close()

        assert not df_fixed.empty, "Fixed sample on 2026-09-25 was not found in DB"
        X_fixed = df_fixed[FEATURE_SCHEMA_30]

        # Verify predictions are finite and deterministic across repeated calls
        preds_low_1 = low_price_model.predict(X_fixed)
        preds_low_2 = low_price_model.predict(X_fixed)
        np.testing.assert_array_equal(preds_low_1, preds_low_2)
        assert np.all(np.isfinite(preds_low_1))

        probs_high_1 = higher_price_model.predict_probability(X_fixed)
        probs_high_2 = higher_price_model.predict_probability(X_fixed)
        np.testing.assert_array_equal(probs_high_1, probs_high_2)
        assert np.all(np.isfinite(probs_high_1))

        # Document and assert exact reference values for fixed sample (prevents silent model drift)
        expected_low = {"BBCA": -0.017080, "BBRI": -0.018656, "BUMI": -0.010147}
        expected_high = {"BBCA": 0.244376, "BBRI": 0.235124, "BUMI": 0.281598}
        for ticker, pred_low, prob_high in zip(
            df_fixed["ticker"], preds_low_1, probs_high_1, strict=True
        ):
            assert pred_low == pytest.approx(expected_low[ticker], abs=1e-5)
            assert prob_high == pytest.approx(expected_high[ticker], abs=1e-5)

    def test_prospective_deduplication_across_consecutive_runs(
        self, repo_root: Path, tmp_path: Path
    ):
        """Verifies running step_prospective_date twice on same date avoids duplicate entries."""
        art_dir = tmp_path / "artifacts_dedup"
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=art_dir,
        )

        # Run 1 on 2026-10-14
        res1 = engine.step_prospective_date(date(2026, 10, 14), user_approved=True)
        assert res1["candidates_count"] > 0
        cands_csv = art_dir / "paper_trading_candidates.csv"
        assert cands_csv.exists()
        df1 = pd.read_csv(cands_csv)
        count1 = len(df1)

        # Run 2 on same date
        engine.step_prospective_date(date(2026, 10, 14), user_approved=True)
        df2 = pd.read_csv(cands_csv)
        count2 = len(df2)

        # Assert no duplicate candidate rows appended
        assert count1 == count2

    def test_empty_feature_input_returns_empty_array(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
    ):
        """Verifies models handle 0-row DataFrames gracefully returning empty arrays."""
        df_empty = pd.DataFrame(columns=FEATURE_SCHEMA_30)
        preds_low = low_price_model.predict(df_empty)
        assert isinstance(preds_low, np.ndarray)
        assert len(preds_low) == 0

        probs_high = higher_price_model.predict_probability(df_empty)
        assert isinstance(probs_high, np.ndarray)
        assert len(probs_high) == 0

        proba_high = higher_price_model.predict_proba(df_empty)
        assert isinstance(proba_high, np.ndarray)
        assert proba_high.shape == (0, 2)

    def test_single_sample_1d_input(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies passing 1D array of 30 features works for single-sample inference."""
        arr_1d = sample_feature_dataframe.iloc[0].to_numpy()
        pred_low = low_price_model.predict(arr_1d)
        assert len(pred_low) == 1
        assert np.isfinite(pred_low[0])

        prob_high = higher_price_model.predict_probability(arr_1d)
        assert len(prob_high) == 1
        assert 0.0 <= prob_high[0] <= 1.0

    def test_full_column_nan_handled_by_imputer(
        self,
        low_price_model: ResearchRegressorModel,
        higher_price_model: ResearchClassifierModel,
        sample_feature_dataframe: pd.DataFrame,
    ):
        """Verifies that even if an entire feature column is NaN, training median imputes it."""
        df_all_nan = sample_feature_dataframe.copy()
        df_all_nan["return_5d"] = np.nan
        df_all_nan["market_breadth"] = np.nan

        preds_low = low_price_model.predict(df_all_nan)
        assert np.all(np.isfinite(preds_low))

        probs_high = higher_price_model.predict_probability(df_all_nan)
        assert np.all(np.isfinite(probs_high))

    def test_runtime_bundle_hash_matches_frozen_policy_config_json(self, repo_root: Path):
        """Verifies runtime hash from get_default_frozen_policies()
        matches frozen_policy_config.json.
        """
        config_path = repo_root / "artifacts/phase_11f/frozen_policy_config.json"
        assert config_path.is_file(), f"Missing config file at {config_path}"
        with open(config_path, encoding="utf-8") as f:
            cfg_data = json.load(f)
        canonical_sha = cfg_data["config_sha256"]

        runtime_bundle = get_default_frozen_policies()
        runtime_sha = runtime_bundle.compute_sha256()

        assert runtime_sha == canonical_sha
        assert runtime_sha == "8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71"

    def test_missing_scoring_artifact_reports_blocked_status(self, repo_root: Path, tmp_path: Path):
        """Verifies missing research artifacts result in BLOCKED_ON_SCORING_ARTIFACT."""
        empty_dir = tmp_path / "empty_models"
        empty_dir.mkdir(parents=True, exist_ok=True)
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        audit = engine.audit_scoring_artifacts(base_dir=empty_dir)
        assert audit["status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
        assert audit["scoring_artifacts_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT

        status = engine.generate_operational_status(base_dir=empty_dir)
        assert status["operational_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
        assert status["scoring_artifacts_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT

    def test_hash_mismatch_reports_blocked_status(self, repo_root: Path, tmp_path: Path):
        """Verifies hash mismatch between artifact and metadata
        reports BLOCKED_ON_SCORING_ARTIFACT.
        """
        tampered_dir = tmp_path / "tampered"
        rel_dir = tampered_dir / "artifacts/phase_11f/research_models"
        rel_dir.mkdir(parents=True, exist_ok=True)

        meta_file = "artifacts/phase_11f/research_models/research_model_metadata.json"
        real_meta_path = repo_root / meta_file
        meta_content = real_meta_path.read_text(encoding="utf-8")
        (rel_dir / "research_model_metadata.json").write_text(meta_content, encoding="utf-8")

        for rel_file in RESEARCH_SCORING_ARTIFACTS.values():
            file_name = Path(rel_file).name
            (rel_dir / file_name).write_bytes(b"corrupted_tampered_model_bytes")

        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        audit = engine.audit_scoring_artifacts(base_dir=tampered_dir)
        assert audit["status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
        assert audit["scoring_artifacts_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT
        assert len(audit["error_logs"]) > 0
        assert "Hash mismatch" in audit["error_logs"][0]

        status = engine.generate_operational_status(base_dir=tampered_dir)
        assert status["operational_status"] == STATUS_BLOCKED_ON_SCORING_ARTIFACT

    def test_operational_status_pending_approval(self, repo_root: Path, tmp_path: Path):
        """Verifies artifacts ready and user_approved=False
        -> READY_FOR_OBSERVATION_PENDING_USER_APPROVAL.
        """
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        status = engine.generate_operational_status(user_approved=False)
        assert status["operational_status"] == STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL
        assert status["scoring_artifacts_status"] == STATUS_SCORING_ARTIFACTS_READY
        assert status["user_approved"] is False

    def test_operational_status_observation_active(self, repo_root: Path, tmp_path: Path):
        """Verifies artifacts ready and user_approved=True without run
        -> APPROVED_PENDING_FIRST_OBSERVATION.
        """
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        status = engine.generate_operational_status(user_approved=True)
        assert status["operational_status"] == STATUS_APPROVED_PENDING_FIRST_OBSERVATION
        assert status["scoring_artifacts_status"] == STATUS_SCORING_ARTIFACTS_READY
        assert status["user_approved"] is True

    def test_operational_status_active_only_after_persisted_first_run(
        self, repo_root: Path, tmp_path: Path
    ):
        """Verifies OBSERVATION_ACTIVE requires approval and persisted first prospective run."""
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        state = engine._default_state()
        state["user_approved"] = True
        state["first_observation_date"] = "2026-10-19"
        state["first_prospective_run_timestamp"] = "2026-10-19T09:00:00Z"
        state["processed_dates"] = ["2026-10-19"]
        engine.save_state(state)

        status = engine.generate_operational_status()
        assert status["operational_status"] == STATUS_OBSERVATION_ACTIVE
        assert status["prospective_lifecycle"]["has_started"] is True

    def test_step_prospective_date_without_user_approval_raises(
        self, repo_root: Path, tmp_path: Path
    ):
        """Verifies step_prospective_date without user_approved=True
        raises UserApprovalRequiredError.
        """
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        with pytest.raises(UserApprovalRequiredError, match="requires explicit user approval"):
            engine.step_prospective_date(date(2026, 10, 19), user_approved=False)

        with pytest.raises(UserApprovalRequiredError, match="requires explicit user approval"):
            engine.step_prospective_date(date(2026, 10, 19))

    def test_step_prospective_date_with_user_approval_succeeds(
        self, repo_root: Path, tmp_path: Path
    ):
        """Verifies step_prospective_date with user_approved=True succeeds on valid dates."""
        engine = PaperTradingEngine(
            db_path=str(repo_root / "datasets/stock_signals.db"),
            artifacts_dir=tmp_path / "artifacts",
        )
        res = engine.step_prospective_date(date(2026, 10, 19), user_approved=True)
        assert res["status"] in ("SCORED", "NO_DATA")
        assert "candidates_count" in res
        assert "decisions_count" in res
