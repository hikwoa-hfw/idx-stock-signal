# Walkthrough: Phase 11F.4 — Fail-Closed Readiness & Approval-Time Cutoff Patch

## Overview

In this patch, we enforced the prospective start-date contract and approval-time cutoff in `python/experiments/paper_trading.py` and `scripts/run_forward_paper_trading.py`. We recorded the approval timestamp and an explicit `effective_observation_cutoff` (`max(data_cutoff, approval_date)` in WIB), rejected pre-approval sessions even if bars are ingested later, dynamically resolved the first eligible prospective date, eliminated hardcoded past dates (`2026-10-19`), eliminated exception swallowing in `get_first_prospective_date()`, and added 5 new regression tests proving all target scenarios (28/28 tests passed).

---

## Task Breakdown & Changes

### 1. Approval-Time Cutoff & Dynamic Prospective Start
**Files:** `python/experiments/paper_trading.py`, `scripts/run_forward_paper_trading.py`
- Added `effective_observation_cutoff` to schema 1.1 state defaults, required fields, and type validation in `load_state()`.
- Enhanced `approve_observation()`:
  - Records `approval_timestamp` and computes `approval_date` in WIB (`Asia/Jakarta`).
  - Sets `effective_observation_cutoff = max(data_cutoff, approval_date)`.
  - Ensures decision sessions that occurred on or before approval cannot be accepted even if market bars are ingested later.
- Overhauled `get_first_prospective_date()`:
  - When unapproved (`not user_approved`), returns `None` (fails closed, no guessing).
  - When approved, dynamically returns `get_next_trading_date(effective_observation_cutoff)`.
  - Replaced silent `except Exception: pass` with direct propagation of `StateIntegrityError`.
- Updated `generate_operational_status()`:
  - Reports `effective_observation_cutoff` in `approval_metadata`.
  - Reports `first_allowed_prospective_date = "PENDING_USER_APPROVAL"` when unapproved.
  - Catches `StateIntegrityError` to set `first_allowed_prospective_date = "BLOCKED_ON_STATE_CORRUPTION"`.
- Enhanced `step_prospective_date()`:
  - Validates date against `approval_data_cutoff` and `effective_observation_cutoff`.
  - Raises `InvalidProspectiveDateError` if `eval_date <= cutoff`.
  - Checks missed sessions against `first_eligible` dynamically determined.
- Updated CLI in `scripts/run_forward_paper_trading.py`:
  - Displays `Effective Obs Cutoff` in `--status` and `--approve-observation`.
  - Enforces effective cutoff in `--date`: blocks pre-approval sessions with a descriptive error.

### 2. Comprehensive Fail-Closed Test Suite (28 Tests)
**File:** `tests/unit/test_fail_closed_readiness.py`
- Added 5 new targeted regression tests covering all target scenarios:
  1. `test_decision_session_before_approval_rejected_when_bars_ingested_later`: Proves session that occurred before approval cannot be accepted even if bars are ingested later.
  2. `test_first_session_eligible_after_approval_can_be_processed`: Proves first session strictly after approval can be processed successfully.
  3. `test_old_or_stale_date_cannot_be_accepted_through_user_approved`: Proves stale/backdated dates cannot be forced through via `--user-approved`.
  4. `test_corrupt_state_cannot_produce_misleading_first_prospective_date`: Proves corrupt state propagates `StateIntegrityError` and sets status to `BLOCKED_ON_STATE_CORRUPTION`.
  5. `test_unapproved_state_first_prospective_date_is_none_and_status_pending`: Proves unapproved state returns `first_allowed_prospective_date=None` and reports `PENDING_USER_APPROVAL`.
- Total tests in `test_fail_closed_readiness.py`: 28 passed (100%).

---

## Verification Record

| Verification Step | Command | Result |
|---|---|---|
| Fail-closed regression suite | `.venv\Scripts\python -m pytest tests/unit/test_fail_closed_readiness.py -v` | **PASS** (28/28 passed in 7.97s) |
| Combined paper trading suite | `.venv\Scripts\python -m pytest tests/unit/test_fail_closed_readiness.py tests/unit/test_research_scoring_integrity.py tests/unit/test_prospective_lifecycle.py tests/unit/test_forward_paper_trading.py` | **PASS** (88/88 passed in 10.70s) |
| Full repository test suite | `.venv\Scripts\python -m pytest` | **PASS** (591/591 passed in 101.90s) |
| Repository linter | `.venv\Scripts\ruff check .` | **PASS** (0 errors) |
| Unstarted state confirmation | `git status` | Clean; no production state file created |

---

## Testing Checklist

After pulling these changes, the operator should verify the following items:

- [ ] **1. Verify Operational Status Before Approval:**
  ```powershell
  python -m scripts.run_forward_paper_trading --status
  ```
  *Verify that operational status reports `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`, `user_approved: False`, and `First Allowed Prospective Date: PENDING_USER_APPROVAL`.*

- [ ] **2. Authorize Prospective Observation:**
  ```powershell
  python -m scripts.run_forward_paper_trading --approve-observation
  ```
  *Verify that operational status transitions to `APPROVED_PENDING_FIRST_OBSERVATION`, recording `approval_timestamp`, `approval_data_cutoff: "2026-10-16"`, and `effective_observation_cutoff: "<approval_date>"`, with `First Allowed Prospective Date` dynamically set to the next valid trading session.*

- [ ] **3. Verify Status Flag Does Not Activate Observation:**
  ```powershell
  python -m scripts.run_forward_paper_trading --status --user-approved
  ```
  *Verify that status remains `APPROVED_PENDING_FIRST_OBSERVATION` and `has_started` remains `False`.*

- [ ] **4. Verify Pre-Approval Session Rejection:**
  ```powershell
  python -m scripts.run_forward_paper_trading --date 2026-10-16 --user-approved
  ```
  *Verify that the command fails closed with an error indicating the date is at or before the market data or effective cutoff.*

- [ ] **5. Run Full Unit Test Suite:**
  ```powershell
  python -m pytest tests/unit/test_fail_closed_readiness.py -v
  ```
  *Verify all 28 fail-closed readiness tests pass.*

- [ ] **6. Ingest Next Trading Session Strictly After Approval & Step Observation:**
  ```powershell
  python -m scripts.ingest_daily --date <next_eligible_date>
  python -m scripts.run_forward_paper_trading --date <next_eligible_date> --user-approved
  ```
  *Verify that upon successful completion, operational status transitions to `OBSERVATION_ACTIVE` with 1 processed date.*
