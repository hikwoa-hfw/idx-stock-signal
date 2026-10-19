# Walkthrough — Phase 11F.1: Research Scoring Artifact Finalization & Forward Observation Readiness

## Session Overview

Completed **Phase 11F.1 — Research Scoring Artifact Finalization & Forward Observation Readiness** for the Indonesian Stock AI dual-mode signals. This phase serializes the required H=15 Variant B research scoring estimators, enforces strict 30-feature schema ordering and training-derived median imputation, transitions the fail-closed audit status to `READY_FOR_OBSERVATION`, re-locks the canonical policy configuration hash, reconciles historical replay trade evidence (309 continuous replay trades vs 298 fold-partitioned trades), reconciles test execution counts (541 total passed tests: 509 unit, 32 integration), and prepares the system for the 3-month prospective paper-trading observation window.

During this session:
1. Reconstructed and serialized the two intended H=15 Variant B research scoring estimators up to cutoff `2026-09-25` (all 15 forward trading days up to `2026-10-16` fully observable):
   - `artifacts/phase_11f/research_models/lgb_regressor_h15_variant_b.joblib` (SHA-256: `84170b51...`)
   - `artifacts/phase_11f/research_models/lgb_full_classifier_h15_variant_b.joblib` (SHA-256: `3192aa5c...`)
   - `artifacts/phase_11f/research_models/research_model_metadata.json` documenting cutoffs, row counts, label prevalence, and hyperparameters.
2. Built schema-enforcing estimator wrappers in `python/models/research_scoring.py` (`ResearchRegressorModel` and `ResearchClassifierModel`) requiring strict `FEATURE_SCHEMA_30` column ordering, rejecting missing/extra/reordered columns via `ValueError`, and applying causal median imputation.
3. Updated `python/experiments/paper_trading.py` to point `RESEARCH_SCORING_ARTIFACTS` to the research directory, incorporated schema validation and deduplication in `step_prospective_date`, locked the canonical configuration hash to `8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`, and updated `frozen_policy_config.json`.
4. Transitioned `PaperTradingEngine` operational audit status to `PASS` / `READY_FOR_OBSERVATION`.
5. Added 17 comprehensive unit tests in `tests/unit/test_research_scoring_integrity.py` and updated `test_forward_paper_trading.py` and `test_smoke.py`, achieving 100% pass rate across the full 541-test workspace suite with 0 linter errors.
6. Reconciled historical replay trade counts (309 vs 298–301) and test suite counts, creating the formal report in `docs/18_phase_11f_research_scoring_and_observation_readiness_report.md` and updating `audit_report.md` and `summary.md`.

---

## 1. Task Breakdown & Code Modifications

### 1.1 Research Scoring Model Wrappers: `python/models/research_scoring.py` (New File, Lines 1–117)
- **`BaseResearchScoringModel` (Lines 15–64):**
  - Encapsulates `feature_schema` (`FEATURE_SCHEMA_30`), `imputer_` (`SimpleImputer`), `estimator_`, and `training_cutoff`.
  - `_validate_and_transform_X`:
    * If DataFrame: checks missing columns (`ValueError: Missing required feature columns`), unexpected extra columns (`ValueError: Unexpected feature columns`), and exact ordering (`ValueError: Feature columns reordered`).
    * If ndarray: validates shape `(N, 30)` (`ValueError: Expected 30 features, got ...`).
    * Applies training-derived median imputation via `self.imputer_.transform(X_arr)`.
- **`ResearchRegressorModel` (Lines 67–88):**
  - Wraps LOW_PRICE return regressor (`task_type="regression"`, `score_metric="pred_return_lgb"`).
  - Implements `predict(X)` returning continuous float expected return array.
  - Lacks `predict_proba` to enforce regression semantics.
- **`ResearchClassifierModel` (Lines 91–117):**
  - Wraps HIGHER_PRICE full classifier (`task_type="classification"`, `score_metric="prob_lgb_full"`).
  - Implements `predict_proba(X)` returning `(N, 2)` probabilities.
  - Implements `predict_probability(X)` returning `(N,)` positive class probability $P(y=1) \in [0, 1]$.
  - Implements `predict(X, threshold=0.5)` returning integer class predictions.

### 1.2 Training Script: `scripts/train_phase11f_research_models.py` (New File, Lines 1–285)
- Reconstructs and fits both estimators using `MultiHorizonEvaluationRunner` and SQLite database:
  - Fixed training start: `2023-01-02`.
  - Fixed training cutoff: `2026-09-25` (where all 15 forward trading days up to latest bar `2026-10-16` are observable).
  - `LOW_PRICE`: LightGBM Regressor Baseline (`n_estimators=100, learning_rate=0.05, max_depth=5, num_leaves=31, min_child_samples=20, random_state=42`) on 41,848 valid executable Variant B rows.
  - `HIGHER_PRICE`: LightGBM Classifier Baseline (`n_estimators=100, learning_rate=0.05, max_depth=5, num_leaves=31, min_child_samples=20, random_state=42, calibrated=False`) on 131,110 valid executable Variant B rows (31,400 positive samples, 23.95% prevalence).
  - Serializes binaries to `artifacts/phase_11f/research_models/` (isolated from `models/registry/`).
  - Computes SHA-256 binary hashes and exports `research_model_metadata.json`.

### 1.3 Core Forward Paper Trading Engine: `python/experiments/paper_trading.py`
- **Scoring Artifact Paths (Lines 46–55):**
  - Updated `RESEARCH_SCORING_ARTIFACTS` from `models/registry/...` to `artifacts/phase_11f/research_models/...`.
- **Re-exports in `__all__` (Lines 42–60):**
  - Added `ResearchRegressorModel` and `ResearchClassifierModel` to module exports.
- **Operational Status Code (Lines 1155–1165):**
  - Updated `generate_operational_status`: status transitions to `READY_FOR_OBSERVATION` when scoring artifacts audit passes (`audit['status'] == 'PASS'`).
- **Prospective Scoring Execution (`step_prospective_date`, Lines 1270–1360):**
  - Passed `X_df` directly to `model.predict(X_df)` and `model.predict_proba(X_df)` to activate schema ordering validation and training-derived median imputation.
  - Added candidate and decision deduplication: checks existing records in `paper_trading_candidates.csv` and `paper_trading_decisions.csv` by `(date, ticker, mode)` before appending, preventing duplicate entries on repeated runs.

### 1.4 Frozen Policy Configuration: `artifacts/phase_11f/frozen_policy_config.json`
- Recomputed canonical SHA-256 hash incorporating updated artifact paths:
  `8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`.

### 1.5 Unit Tests: `tests/unit/test_research_scoring_integrity.py` (New File, Lines 1–370)
- Added 17 unit tests:
  1. `test_artifacts_load_successfully`: verifies joblib loading and wrapper class instances.
  2. `test_feature_input_schema_success`: verifies exact ordered schema succeeds.
  3. `test_missing_feature_column_fails`: verifies missing columns raise `ValueError`.
  4. `test_reordered_feature_columns_fail`: verifies swapped columns raise `ValueError`.
  5. `test_unexpected_feature_column_fails`: verifies unapproved extra columns raise `ValueError`.
  6. `test_array_dimension_mismatch_fails`: verifies wrong 2D array dimension raises `ValueError`.
  7. `test_all_produced_scores_are_finite`: verifies no NaN/Inf in predictions.
  8. `test_low_price_uses_regression_score`: verifies continuous float output and absence of `predict_proba`.
  9. `test_higher_price_uses_classifier_score`: verifies probability output bounded in $[0, 1]$.
  10. `test_no_production_champion_fallback`: verifies isolation from `models/registry/` and active champions.
  11. `test_frozen_configuration_hash_is_deterministic`: verifies canonical SHA-256 hash match.
  12. `test_prospective_empty_or_incomplete_data_no_fabricated_signals`: verifies zero signals on empty dates.
  13. `test_fixed_sample_prediction_and_temporal_causality`: verifies deterministic outputs and exact numerical reference predictions on fixed DB records.
  14. `test_prospective_deduplication_across_consecutive_runs`: verifies no duplicate rows on re-runs.
  15. `test_empty_feature_input_returns_empty_array`: verifies models handle 0-row DataFrames gracefully without invoking SimpleImputer errors.
  16. `test_single_sample_1d_input`: verifies single 1D array input of 30 features works for inference.
  17. `test_full_column_nan_handled_by_imputer`: verifies training median imputation when an entire feature column in a batch is NaN.

### 1.6 Existing Tests Hardening: `tests/unit/test_forward_paper_trading.py` and `tests/unit/test_smoke.py`
- `tests/unit/test_forward_paper_trading.py`: Updated mock model paths to `RESEARCH_SCORING_ARTIFACTS`, added `empty_models` dir to verify fail-closed behavior when artifacts are absent, and updated operational status assertions.
- `tests/unit/test_smoke.py`: Restored `infra/aws/Dockerfile` existence assertion and added assertions for Phase 11F/11F.1 files, training script, and research model binaries.

---

## 2. Replay Evidence & Test Count Reconciliation

### Historical Replay Trade Count Reconciliation (309 vs 298–301)
- **Phase 11E/11D Backtest:** Partitioned across 3 disjoint walk-forward test folds. Each fold began fresh with empty positions. Positions open at fold boundaries were artificially liquidated, leaving 5 open positions at the end of Fold 3. Total completed trades reported: 298.
- **Phase 11F Replay Simulation:** Spans a continuous timeline from 2023-12-28 to 2026-10-13 without artificial fold boundary liquidations.
- **Reconciliation Proof:**
  $$\text{Replay Trades} = \text{Fold Completed} (298) + \text{Fold Boundary Open} (5) + \text{Cross-Fold Carryovers} (6) = 309 \text{ trades}.$$
  Continuous simulation accurately allows positions to mature to terminal TP/SL/expiry barriers.

### Test Suite Reconciliation
- **Total Tests Passed:** 541 (100% pass rate).
- **Unit Tests:** 509 across 28 test modules.
- **Integration Tests:** 32 across 14 pipeline modules.
- **Linter Status:** `ruff check .` clean (0 errors, 0 warnings).

---

## 3. Testing Checklist for User After Deployment

After deployment or when preparing for daily paper-trading operations, verify the following items:

- [ ] **Scoring Artifact Presence:** Confirm `lgb_regressor_h15_variant_b.joblib` and `lgb_full_classifier_h15_variant_b.joblib` exist in `artifacts/phase_11f/research_models/` and match recorded SHA-256 hashes.
- [ ] **Operational Status Check:** Run `python scripts/run_forward_paper_trading.py --status`. Verify `Status Code: READY_FOR_OBSERVATION`, `Missing Artifacts: 0`, and `Policy Bundle Hash: 8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`.
- [ ] **Champion Model Protection:** Confirm `models/registry/` contains only production champions and no research binaries were written there.
- [ ] **Prospective Scoring Execution:** Run `python scripts/run_forward_paper_trading.py --date 2026-10-16`. Verify candidates are scored and appended to `artifacts/phase_11f/paper_trading_candidates.csv` without duplicate rows.
- [ ] **Daily Cron Readiness:** Verify daily scheduled ingestion (`scripts/ingest_daily.py`), feature generation (`scripts/build_features.py`), and prospective paper-trading (`scripts/run_forward_paper_trading.py`) are queued for 16:15 WIB.
- [ ] **Full Test Suite & Linter Execution:** Run `pytest` (541 passed) and `ruff check .` (0 errors).
