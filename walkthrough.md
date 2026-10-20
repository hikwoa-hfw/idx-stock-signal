# Walkthrough: Phase 11F.2 — Reconcile Research Artifact Paths, Policy Hash, and Operational Readiness

## Overview

In Phase 11F.2, we reconciled all reported inconsistencies across research scoring artifact paths, canonical configuration hashing, operational lifecycle semantics, and cutoff metadata. We enforced a strict human-in-the-loop authorization barrier (`UserApprovalRequiredError` and `--user-approved` CLI flag) ensuring prospective observation remains in `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL` until the user explicitly grants permission to begin the three-month prospective observation window.

---

## Task Breakdown & Changes

### 1. Research Model Wrapper & Deserialization
**File:** `python/models/research_scoring.py`
- Added `@classmethod def load(cls, path: Union[str, Path]) -> Self` to `BaseResearchScoringModel` (lines 40–48) to enforce explicit type-checked deserialization for `ResearchRegressorModel` and `ResearchClassifierModel`.
- Imported `joblib`, `Path`, and `Self` from `typing`.

### 2. Operational Status Lifecycle Decoupling & User Approval Guard
**File:** `python/experiments/paper_trading.py`
- Exported and defined lifecycle status constants (lines 45–66):
  - `STATUS_BLOCKED_ON_SCORING_ARTIFACT = "BLOCKED_ON_SCORING_ARTIFACT"`
  - `STATUS_SCORING_ARTIFACTS_READY = "SCORING_ARTIFACTS_READY"`
  - `STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL = "READY_FOR_OBSERVATION_PENDING_USER_APPROVAL"`
  - `STATUS_OBSERVATION_ACTIVE = "OBSERVATION_ACTIVE"`
  - `FIRST_PROSPECTIVE_DATE = date(2026, 10, 19)`
- Defined `UserApprovalRequiredError(Exception)` (lines 114–116).
- Enhanced `audit_scoring_artifacts(base_dir=None)` (lines 474–586):
  - Checks binary file existence in `artifacts/phase_11f/research_models/`.
  - Computes SHA-256 for both models.
  - Verifies hashes against `research_model_metadata.json` (or canonical fallback).
  - Loads models via `ResearchRegressorModel.load` / `ResearchClassifierModel.load` when metadata exists.
  - Executes smoke prediction on 1 sample of `FEATURE_SCHEMA_30` to verify scores are finite.
  - Returns `status` (`PASS` or `BLOCKED_ON_SCORING_ARTIFACT`) and `scoring_artifacts_status`.
- Updated `generate_operational_status()` (lines 1270–1334):
  - Added `user_approved: bool = False` and `base_dir: Optional[Path] = None` arguments.
  - Evaluates operational status: `BLOCKED_ON_SCORING_ARTIFACT`, `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`, or `OBSERVATION_ACTIVE`.
  - Added `cutoff_metadata`:
    * `training_decision_cutoff_date`: `2026-09-25`
    * `forward_label_final_bar_date`: `2026-10-16`
    * `training_build_timestamp`: `2026-10-19T09:22:28.960379+00:00`
    * `first_allowed_prospective_date`: `2026-10-19`
    * `data_finality_proof`: Confirms all 15-day forward horizons matured on or before market close 2026-10-16.
- Updated `step_prospective_date()` (lines 1336–1360):
  - Added `user_approved: bool = False` parameter.
  - Checks `audit_scoring_artifacts()` first; fails closed with `MissingScoringArtifactError` if not pass.
  - If `not user_approved`: raises `UserApprovalRequiredError("Prospective observation date scoring requires explicit user approval.")`.

### 3. Forward Paper Trading CLI Runner
**File:** `scripts/run_forward_paper_trading.py`
- Added `--user-approved` CLI argument (lines 60–64).
- Updated `print_status_summary()` (lines 73–90) to display `Status Code`, `Scoring Artifacts`, and `User Approved`.
- Updated `--status` action to pass `args.user_approved` (line 101).
- Updated `--date` action (lines 116–135) to require `--user-approved`. Exits with code 1 and descriptive prompt if omitted.

### 4. Operational Status JSON Artifact
**File:** `artifacts/phase_11f/paper_trading_operational_status.json`
- Regenerated with canonical hash `8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`.
- `operational_status`: `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`.
- `scoring_artifacts_status`: `SCORING_ARTIFACTS_READY`.
- `user_approved`: `false`.
- Contains `cutoff_metadata` with zero data leakage finality proof.

### 5. Unit & Regression Tests
**File:** `tests/unit/test_research_scoring_integrity.py`
- Added `json` and new status/exception imports.
- Updated prospective calls on historical test dates with `user_approved=True`.
- Added 7 dedicated unit tests (lines 382–493):
  1. `test_runtime_bundle_hash_matches_frozen_policy_config_json`: Asserts runtime `compute_sha256()` matches `frozen_policy_config.json`.
  2. `test_missing_scoring_artifact_reports_blocked_status`: Verifies missing artifacts report `BLOCKED_ON_SCORING_ARTIFACT`.
  3. `test_hash_mismatch_reports_blocked_status`: Verifies tampered models report `BLOCKED_ON_SCORING_ARTIFACT`.
  4. `test_operational_status_pending_approval`: Verifies `user_approved=False` yields `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`.
  5. `test_operational_status_observation_active`: Verifies `user_approved=True` yields `OBSERVATION_ACTIVE`.
  6. `test_step_prospective_date_without_user_approval_raises`: Verifies unapproved execution raises `UserApprovalRequiredError`.
  7. `test_step_prospective_date_with_user_approval_succeeds`: Verifies approved execution succeeds.
- Module tests passed: 24 of 24.

**File:** `tests/unit/test_forward_paper_trading.py`
- Updated lines 587 and 595 in `test_prospective_scoring_executes_with_mock_artifacts` with `user_approved=True`.
- Updated lines 645–651 in `test_operational_status_generation` to allow `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`.
- Module tests passed: 21 of 21.

### 6. Documentation & Audit Index
- `docs/18_phase_11f_research_scoring_and_observation_readiness_report.md`: Updated to Phase 11F.2 specification.
- `audit_report.md`: Updated current operational state to Phase 11F.2 and index entry 10 (548 passed tests).
- `summary.md`: Appended Log Entry 63 (strictly append-only).

---

## Verification Results

1. **Scoring Integrity Tests:**
   ```powershell
   .venv\Scripts\pytest tests/unit/test_research_scoring_integrity.py
   # Output: 24 passed in 3.17s
   ```
2. **Forward Paper Trading Tests:**
   ```powershell
   .venv\Scripts\pytest tests/unit/test_forward_paper_trading.py
   # Output: 21 passed in 2.43s
   ```
3. **Full Repository Test Suite:**
   ```powershell
   .venv\Scripts\pytest -q
   # Output: 548 passed in 44.5s (516 unit, 32 integration)
   ```
4. **Code Quality / Linter:**
   ```powershell
   .venv\Scripts\ruff check .
   # Output: All checks passed!
   ```
5. **CLI Status Verification:**
   - Pending: `.venv\Scripts\python scripts/run_forward_paper_trading.py --status` -> `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`
   - Active: `.venv\Scripts\python scripts/run_forward_paper_trading.py --status --user-approved` -> `OBSERVATION_ACTIVE`
   - Unapproved Date Scoring: `.venv\Scripts\python scripts/run_forward_paper_trading.py --date 2026-10-19` -> Exit code 1 with prompt.

---

## Testing Checklist

After reviewing or deploying this change, verify the following items:

- [ ] Run `.venv\Scripts\python scripts/run_forward_paper_trading.py --status` and confirm:
  - Status Code is `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`.
  - Scoring Artifacts is `SCORING_ARTIFACTS_READY`.
  - User Approved is `False`.
  - Policy Bundle Hash is `8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`.
- [ ] Run `.venv\Scripts\python scripts/run_forward_paper_trading.py --status --user-approved` and confirm Status Code switches to `OBSERVATION_ACTIVE`.
- [ ] Run `.venv\Scripts\python scripts/run_forward_paper_trading.py --date 2026-10-19` without `--user-approved` and confirm:
  - Process exits with code 1.
  - Clear error message displayed: `Error: Prospective observation date scoring requires explicit user approval. Pass --user-approved to confirm execution.`
- [ ] Run `.venv\Scripts\pytest tests/unit/test_research_scoring_integrity.py` and confirm all 24 unit tests pass.
- [ ] Run `.venv\Scripts\pytest tests/unit/test_forward_paper_trading.py` and confirm all 21 unit tests pass.
- [ ] Run `.venv\Scripts\pytest -q` and confirm all 548 unit and integration tests pass.
- [ ] Run `.venv\Scripts\ruff check .` and confirm 0 lint errors.
- [ ] Confirm `artifacts/phase_11f/paper_trading_operational_status.json` contains `cutoff_metadata` with decision cutoff `2026-09-25` and final bar date `2026-10-16`.
