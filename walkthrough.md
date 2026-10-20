# Walkthrough: Phase 11F.3 — Complete Prospective Paper-Trading Lifecycle

## Overview

In Phase 11F.3, we completed the missing execution and position-management lifecycle for the prospective paper-trading pipeline. We resolved the decision-scheduling defect (`PaperDecision.execution_date`), implemented a transactionally safe state persistence engine (`paper_trading_state.json`), enforced pre-entry gap invalidations and barrier exits (TP +6%, SL -2%, conservative same-candle precedence, 15-day expiry), and updated operational reporting to present real-time prospective observation metrics.

---

## Task Breakdown & Changes

### 1. Decision Scheduling & Next-Trading-Date Resolution
**File:** `python/experiments/paper_trading.py`
- Added `get_next_trading_date(current_date: date) -> date` (lines 1300–1318):
  - Queries `daily_bars` for `MIN(date) > current_date`.
  - Falls back to next business weekday (Monday–Friday) if at the frontier of available bars.
- Fixed `PaperDecision.execution_date` in `step_prospective_date()` (line 2045):
  - Evaluates `next_exec_d = self.get_next_trading_date(eval_date)`.
  - Sets `PaperDecision.execution_date = next_exec_d` (strictly $t+1$), eliminating same-day execution claims under Variant B Market-On-Open policy.

### 2. Persistent State Management & Idempotency
**File:** `python/experiments/paper_trading.py`
- Added `_default_state() -> dict[str, Any]` (lines 1240–1274):
  - Initializes structured state: `cash`, `peak_equity`, `max_drawdown`, `processed_dates`, `pending_orders`, `order_history`, `open_positions`, `completed_trades`, `daily_equity_history`, `unfilled_summary`.
- Added `load_state() -> dict[str, Any]` (lines 1276–1288):
  - Safely loads `artifacts/phase_11f/paper_trading_state.json` with fallback to default state.
- Added `save_state(state: dict[str, Any]) -> None` (lines 1290–1296):
  - Writes atomically via `.tmp` temporary file and replacement to prevent corruption.
- Added `reset_state() -> None` (lines 1298–1310):
  - Unlinks `paper_trading_state.json` and associated paper trading CSV files for clean test resets.
- Added Idempotency Guard in `step_prospective_date()` (lines 1470–1495):
  - If `str(eval_date) in state["processed_dates"]`, returns `status="ALREADY_PROCESSED"` immediately without mutating balances or appending duplicate trades.

### 3. Multi-Session Daily Lifecycle Execution
**File:** `python/experiments/paper_trading.py`
- Overhauled `step_prospective_date()` (lines 1440–2180):
  - **Step A: Session Open Fills:**
    * Processes orders in `state["pending_orders"]` scheduled for $\le eval\_date$.
    * Sorts deterministically by `(-score, ticker)`.
    * Checks zero-regime multiplier (`SKIPPED_REGIME_ZERO`), portfolio capacity / duplicates (`UNFILLED_CAPACITY`), and market bar availability / volume (`UNFILLED_SUSPENDED`).
    * Evaluates pre-entry gap invalidations: gap down $\le -2\%$ (`INVALIDATED_GAP_DOWN`), gap up $\ge +6\%$ (`INVALIDATED_GAP_UP`), open deviation $> 5\%$ (`INVALIDATED_EXCESSIVE_DEV`).
    * Applies three-tier sizing, 20% equity cap, and IDX 100-share lot rounding.
    * Deducts cash outlay + 15 bps buy commission + 5 bps entry slippage, adding filled positions to `open_positions`.
  - **Step B: Intraday Barrier Exits:**
    * Evaluates open positions against daily OHLC: TP $+6\%$, SL $-2\%$, expiry at day 15 close.
    * Conservative precedence: on ambiguous bars touching both TP and SL, resolves strictly as SL.
    * Credits cash proceeds net of 25 bps sell commission and 5 bps exit slippage.
    * Records closed positions into `state["completed_trades"]` with full MFE/MAE excursion metrics.
  - **Step C: Mark-to-Market Equity Valuation:**
    * Updates `last_known_close` and open position valuations.
    * Computes total equity, peak equity, and continuous drawdown.
    * Appends snapshot to `state["daily_equity_history"]`.
  - **Step D: Evening Candidate Scoring:**
    * Scores candidates at Close $t$ with frozen research models (`LOW_PRICE` regressor, `HIGHER_PRICE` classifier).
    * Ranks deterministically (`-score, ticker`) and selects top 3% / top 1% under bull regime (`ihsg_vs_ema20 > 0`).
    * Queues decisions into `pending_orders` scheduled for next session $t+1$.
  - **Step E: CSV Export Synchronization:**
    * Synchronizes `paper_trading_candidates.csv`, `paper_trading_decisions.csv`, `paper_trading_trades.csv`, and `paper_trading_daily_equity.csv`.

### 4. Live Prospective Operational Status
**File:** `python/experiments/paper_trading.py` & `scripts/run_forward_paper_trading.py`
- Updated `generate_operational_status()` (lines 1320–1430):
  - Adds `prospective_lifecycle` block reporting `has_started`, `first_observation_date`, `last_decision_date`, `last_execution_date`, `pending_orders_count`, `open_positions_count`, `completed_trades_count`, `realized_net_pnl_idr`, `unrealized_pnl_idr`, `cash_balance_idr`, `current_equity_idr`, `peak_equity_idr`, and `unfilled_counts`.
  - Sets `operational_status = STATUS_OBSERVATION_ACTIVE` if `user_approved or has_started`, otherwise `STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`.
- Updated `scripts/run_forward_paper_trading.py`:
  - Added `--reset-state` flag (lines 76–80, 155–163).
  - Enhanced `print_status_summary()` to print prospective observation metrics (lines 100–145).

### 5. Unit & Regression Tests
**File:** `tests/unit/test_prospective_lifecycle.py`
- Created 14 comprehensive tests covering:
  1. `test_user_approval_required_blocks_mutation`
  2. `test_missing_artifacts_halts_prospective_date`
  3. `test_decision_scheduled_for_next_eligible_session_not_date_t`
  4. `test_next_session_valid_fill_at_open`
  5. `test_next_session_gap_down_invalidation`
  6. `test_next_session_gap_up_invalidation`
  7. `test_next_session_excessive_deviation_invalidation`
  8. `test_tp_exit_resolution`
  9. `test_conservative_sl_precedence_on_ambiguous_candle`
  10. `test_expiry_exit_at_holding_day_15`
  11. `test_capacity_and_duplicate_ticker_constraints`
  12. `test_state_persists_across_instances`
  13. `test_idempotent_rerun_returns_already_processed`
  14. `test_status_transitions_to_active_only_after_approved_prospective_run`

---

## Verification Results

- `pytest tests/unit/test_prospective_lifecycle.py`: **14 passed** in 7.33s.
- `pytest tests/unit/test_forward_paper_trading.py`: **21 passed** in 2.81s.
- `pytest tests/unit/test_research_scoring_integrity.py`: **24 passed** in 4.73s.
- `pytest` (full test suite): **562 passed** (530 unit, 32 integration, 0 failures) in 130s.
- `ruff check .`: **All checks passed** (0 errors).
- `python scripts/run_forward_paper_trading.py --status`: Output verified clean and uncorrupted.

---

## Testing Checklist

After pulling these changes, verify the following:

- [ ] Run unit tests for prospective lifecycle:
  ```bash
  pytest tests/unit/test_prospective_lifecycle.py -v
  ```
- [ ] Run full test suite to confirm zero regressions:
  ```bash
  pytest
  ```
- [ ] Verify linter clean status:
  ```bash
  ruff check .
  ```
- [ ] Check operational status output:
  ```bash
  python scripts/run_forward_paper_trading.py --status
  ```
  Confirm:
  - `Status Code`: `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`
  - `Scoring Artifacts`: `SCORING_ARTIFACTS_READY`
  - `Observation Started`: `False`
  - `Cash Balance`: `100,000,000 IDR`
- [ ] Verify user approval guard without `--user-approved`:
  ```bash
  python scripts/run_forward_paper_trading.py --date 2026-10-19
  ```
  Confirm it exits with error requiring `--user-approved`.
- [ ] Verify git working directory status:
  ```bash
  git status
  ```
