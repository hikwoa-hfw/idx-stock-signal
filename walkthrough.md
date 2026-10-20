# Walkthrough: Phase 11F.4 — Final Fail-Closed Readiness Corrections

## Overview

In Phase 11F.4, we completed all final fail-closed readiness corrections for forward paper trading. We decoupled user approval from observation activation, enforced dynamic market data cutoffs to prevent backdated observations, added strict multi-point data quality guards in prospective scoring, secured persistent state integrity against corruption or tampering, and verified all behaviors with an exhaustive 16-test unit and regression suite.

---

## Task Breakdown & Changes

### 1. Decoupled Persistent Human Approval & Cutoff Tracking
**Files:** `python/experiments/paper_trading.py`, `scripts/run_forward_paper_trading.py`
- Added custom exception classes to `python/experiments/paper_trading.py` (lines 137–152):
  - `InvalidProspectiveDateError`: Raised on historical, out-of-order, or non-monotonic dates.
  - `MissedSessionError`: Raised on skipped trading sessions or stale pending orders.
  - `DataQualityError`: Raised on missing bars/features, schema errors, or infinite values.
  - `StateIntegrityError`: Raised on malformed, incomplete, or hash-mismatched state files.
- Added status constants (lines 47–48):
  - `STATUS_APPROVED_PENDING_FIRST_OBSERVATION`
  - `STATUS_BLOCKED_ON_STATE_CORRUPTION`
- Updated `_default_state()` (lines 1275–1285):
  - Upgraded schema to `version: "1.1"`.
  - Added persistent approval fields: `user_approved: False`, `approval_timestamp: None`, `approval_data_cutoff: None`.
- Implemented `approve_observation()` and `get_latest_market_data_date()` (lines 1420–1455):
  - Queries `MAX(date)` from `daily_bars` to establish market data cutoff.
  - Records human authorization and cutoff in `paper_trading_state.json` without running scoring or modifying balances/trades.
- Updated `generate_operational_status()` (lines 1490–1525):
  - If state is corrupt, reports `STATUS_BLOCKED_ON_STATE_CORRUPTION`.
  - If approved but no run has occurred, reports `STATUS_APPROVED_PENDING_FIRST_OBSERVATION`.
  - Reports `STATUS_OBSERVATION_ACTIVE` **only** when `has_started` is True (`first_observation_date`, `first_prospective_run_timestamp`, and `processed_dates > 0`).
- Updated CLI in `scripts/run_forward_paper_trading.py`:
  - Added `--approve-observation` CLI argument (lines 48–53).
  - Updated `--status` action to display persistent approval metadata and data cutoff (lines 185–215).
  - Prohibited `--status --user-approved` from activating observation (status remains `APPROVED_PENDING_FIRST_OBSERVATION`).

### 2. Prevent Backdated or Stale Observations & Missed Session Guards
**Files:** `python/experiments/paper_trading.py`, `scripts/run_forward_paper_trading.py`
- Enforced dynamic data cutoff in `step_prospective_date()` (lines 1715–1725):
  - If `eval_date <= approval_data_cutoff`, raises `InvalidProspectiveDateError` and halts.
- Enforced sequential monotonicity (lines 1745–1765):
  - If `eval_date < last_processed_date`, raises `InvalidProspectiveDateError`.
  - If `eval_date > expected_next_trading_date`, raises `MissedSessionError` requiring sequential catch-up.
- Prevented silent execution of stale orders (lines 1890–1905):
  - Pending orders scheduled for an earlier session than `eval_date` raise `MissedSessionError` under approved observation instead of silently filling at a later open.
- Added cutoff verification guard in CLI `--date` execution (lines 222–236).

### 3. Strict Data Quality Guards in `step_prospective_date()`
**File:** `python/experiments/paper_trading.py`
- Added comprehensive data quality validation prior to processing orders and candidates (lines 1823–1885):
  - Check 1: Daily bars missing when features exist -> raises `DataQualityError`.
  - Check 2: Features missing when bars exist -> raises `DataQualityError`.
  - Check 3: Date mismatch between `eval_date` and database rows -> raises `DataQualityError`.
  - Check 4: Missing required feature schema columns -> raises `DataQualityError`.
  - Check 5: Zero joined common tickers between features and positive-close bars -> raises `DataQualityError`.
  - Check 6: Infinite values (`np.isinf()`) or entirely null columns in candidate feature matrix -> raises `DataQualityError`.
- Clean handling of holidays/weekends: returns `status: "NO_DATA"` without mutating state when both bars and features are absent.

### 4. Fail-Closed Persistent State Integrity & Migration
**File:** `python/experiments/paper_trading.py`
- Hardened `load_state()` (lines 1300–1365):
  - Validates JSON parseability, dictionary root type, all required state keys, non-negative cash balance, and validates `policy_bundle_hash` against `frozen_bundle.config_sha256`.
  - Raises `StateIntegrityError` on any violation; never falls back to silently overwriting the corrupted state with default values.
- Implemented `migrate_state(backup=True)` (lines 1390–1418):
  - Creates a timestamped backup copy (`paper_trading_state_backup_YYYYMMDD_HHMMSS.json`) before migrating schema.
  - Preserves custom cash balances, open positions, and completed trade history.

### 5. Exhaustive Regression Testing Suite
**Files:** `tests/unit/test_fail_closed_readiness.py`, `tests/unit/test_research_scoring_integrity.py`
- Created `tests/unit/test_fail_closed_readiness.py` with 16 comprehensive tests:
  1. `test_approval_recorded_without_scoring_does_not_activate_observation`
  2. `test_status_user_approved_flag_does_not_activate_observation`
  3. `test_historical_date_at_or_before_data_cutoff_rejected`
  4. `test_new_valid_date_after_approval_can_be_processed`
  5. `test_missing_bars_fails_closed_independently`
  6. `test_missing_features_fails_closed_independently`
  7. `test_infinite_feature_values_fails_closed`
  8. `test_failed_scoring_or_persistence_does_not_create_false_start_record`
  9. `test_missing_state_file_initializes_default`
  10. `test_malformed_json_state_raises_state_integrity_error`
  11. `test_missing_required_fields_in_state_raises_state_integrity_error`
  12. `test_incompatible_policy_hash_in_state_raises_state_integrity_error`
  13. `test_state_migration_preserves_backup_and_upgrades_schema`
  14. `test_duplicate_and_out_of_order_dates_cannot_alter_portfolio`
  15. `test_missed_session_in_prospective_observation_fails_closed`
  16. `test_production_champion_fallback_remains_strictly_prohibited`
- Updated operational status tests in `tests/unit/test_research_scoring_integrity.py`:
  - Adjusted `test_operational_status_observation_active` to verify `STATUS_APPROVED_PENDING_FIRST_OBSERVATION`.
  - Added `test_operational_status_active_only_after_persisted_first_run`.

---

## Verification Record

| Verification Step | Command | Result |
|---|---|---|
| Fail-closed regression suite | `.venv\Scripts\python -m pytest tests/unit/test_fail_closed_readiness.py -v` | **PASS** (16/16 passed in 2.28s) |
| Combined paper trading suite | `.venv\Scripts\python -m pytest tests/unit/test_fail_closed_readiness.py tests/unit/test_research_scoring_integrity.py tests/unit/test_prospective_lifecycle.py tests/unit/test_forward_paper_trading.py` | **PASS** (76/76 passed in 11.05s) |
| Repository linter | `.venv\Scripts\ruff check .` | **PASS** (0 errors) |
| Unstarted state confirmation | `git status` | Clean; no production state file created |

---

## Testing Checklist

After pulling these changes, the operator should verify the following items:

- [ ] **1. Verify Operational Status Before Approval:**
  ```powershell
  python -m scripts.run_forward_paper_trading --status
  ```
  *Verify that operational status reports `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`, `user_approved: False`, and `has_started: False`.*

- [ ] **2. Authorize Prospective Observation:**
  ```powershell
  python -m scripts.run_forward_paper_trading --approve-observation
  ```
  *Verify that operational status transitions to `APPROVED_PENDING_FIRST_OBSERVATION`, recording `approval_timestamp` and `approval_data_cutoff: "2026-10-16"`.*

- [ ] **3. Verify Status Flag Does Not Activate Observation:**
  ```powershell
  python -m scripts.run_forward_paper_trading --status --user-approved
  ```
  *Verify that status remains `APPROVED_PENDING_FIRST_OBSERVATION` and `has_started` remains `False`.*

- [ ] **4. Verify Historical Rejection:**
  ```powershell
  python -m scripts.run_forward_paper_trading --date 2026-10-16 --user-approved
  ```
  *Verify that the command fails closed with an error indicating the date is at or before the market data cutoff.*

- [ ] **5. Run Full Unit Test Suite:**
  ```powershell
  python -m pytest tests/unit/test_fail_closed_readiness.py -v
  ```
  *Verify all 16 fail-closed readiness tests pass.*

- [ ] **6. Ingest Next Trading Session & Step Observation:**
  ```powershell
  python -m scripts.ingest_daily --date 2026-10-19
  python -m scripts.run_forward_paper_trading --date 2026-10-19 --user-approved
  ```
  *Verify that upon successful completion, operational status transitions to `OBSERVATION_ACTIVE` with 1 processed date.*
