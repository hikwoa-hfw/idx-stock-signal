# Walkthrough — Phase 11B.0: Final Target Contract Audit

## 1. Work Session Summary

In this work session, we resolved the target-label versus executable-entry contract discrepancy prior to candidate model retraining in Phase 11B. We migrated the task report template to `docs/AGENT_REPORT_TEMPLATE.md`, developed a comprehensive target audit engine (`scripts/audit_target_contract_runner.py`), quantified differences across 186,291 daily bars and 185,515 production labels in `datasets/stock_signals.db`, exported structured research artifacts to `artifacts/target_contract/`, added targeted unit tests in `tests/unit/test_target_contract.py`, authored the audit report `docs/12_phase_11b_target_contract_audit_report.md`, updated the root `audit_report.md` into a concise status index, and updated `summary.md`.

---

## 2. Detailed Task Breakdown & Code Modifications

### A. Template Governance Setup
- **File:** `docs/AGENT_REPORT_TEMPLATE.md` (and `docs/agent_report_template.md` for case insensitivity).
- **Description:** Copied from root `agent_report_template.md` as the mandatory repository standard for all future agent tasks.

### B. Target Contract Audit Engine
- **File:** `scripts/audit_target_contract_runner.py`
- **Lines 28–66 (`load_all_bars`):**
  * Loads all 186,291 daily price bars from SQLite `daily_bars`, grouped by canonical ticker and sorted chronologically.
- **Lines 69–238 (`evaluate_variant_b`):**
  * Implements the operational next-session execution contract:
    - Pre-entry gap-down invalidation: $Open_{t+1} \le Close_t \times (1 - 0.02) \rightarrow$ `INVALIDATED_GAP` (`GAP_BELOW_SL`).
    - Pre-entry gap-up invalidation: $Open_{t+1} \ge Close_t \times (1 + 0.05) \rightarrow$ `INVALIDATED_GAP` (`GAP_ABOVE_TP`).
    - Excessive open deviation check: $|Open_{t+1} - Close_t| / Close_t > 0.05 \rightarrow$ `INVALIDATED_GAP` (`EXCESSIVE_DEV`).
    - Zero volume / suspended trading check: $Volume_{t+1} \le 0 \rightarrow$ `UNFILLED_SUSPENDED`.
    - Barrier re-anchoring to actual fill price: $TP = Open_{t+1} \times 1.05$, $SL = Open_{t+1} \times 0.98$.
    - Holding horizon: Exactly 10 trading bars starting from the entry day $t+1$ to $t+10$.
    - Ambiguity resolution on entry bar: Day 1 open cannot trigger barriers, but if candle touches both TP and SL, conservative policy resolves to SL.
- **Lines 241–567 (`run_full_contract_audit`):**
  * Reconciles Variant A against `labels_daily` (185,510 exact matches).
  * Computes Variant B for all 186,291 bars.
  * Quantifies valid entries, invalidations, and common-cohort transitions for `LOW_PRICE` and `HIGHER_PRICE`.
  * Exports machine-readable artifacts to `artifacts/target_contract/`.

### C. Targeted Unit Tests
- **File:** `tests/unit/test_target_contract.py`
- **Lines 29–43 (`test_variant_b_gap_below_sl_invalidation`):** Tests pre-entry gap down below SL barrier ($Open_{t+1} = 97.5$ vs decision 100.0).
- **Lines 45–58 (`test_variant_b_gap_above_tp_invalidation`):** Tests pre-entry gap up at or above TP barrier ($Open_{t+1} = 105.5$ vs decision 100.0).
- **Lines 60–79 (`test_variant_b_valid_entry_and_tp_hit`):** Tests valid entry at $Open_{t+1} = 101.0$, re-anchoring TP to $106.05$, hitting TP on Day 2.
- **Lines 81–96 (`test_variant_b_valid_entry_and_sl_hit`):** Tests valid entry at $Open_{t+1} = 99.5$, re-anchoring SL to $97.51$, hitting SL on Day 2.
- **Lines 98–112 (`test_variant_b_expiry_after_10_days`):** Tests 10-day holding horizon expiry without barrier hits.

### D. Governance & Reporting Documentation
- **File:** `docs/12_phase_11b_target_contract_audit_report.md`
  * Complete 11-section report using universal template, detailing empirical numbers, comparison tables, flip analysis, and design decision tradeoffs.
- **File:** `audit_report.md`
  * Refactored as a concise status index linking to reports 09, 10, 11, and 12 using repository-relative Markdown links.
- **File:** `summary.md`
  * Cumulative append-only log entry 54 added.

---

## 3. Key Quantitative Results

1. **Eligible Decision Rows ($N = 183,184$):**
   - `LOW_PRICE` ($\le 300$): 45,763 rows.
   - `HIGHER_PRICE` ($> 300$): 137,421 rows.

2. **Pre-Entry Invalidations in Variant B:**
   - `LOW_PRICE`: 3,404 rows ($7.44\%$) invalidated before entry (1,532 gap-downs, 1,421 zero-volume/suspended, 451 gap-ups).
   - `HIGHER_PRICE`: 5,051 rows ($3.68\%$) invalidated before entry (3,116 gap-downs, 1,287 zero-volume/suspended, 648 gap-ups).

3. **Prevalence Shift on Valid Modeled Entries:**
   - `LOW_PRICE`: Drops from **25.80%** (Variant A) down to **23.35%** (Variant B) ($\Delta = -2.45\%$).
   - `HIGHER_PRICE`: Drops from **24.72%** (Variant A) down to **22.06%** (Variant B) ($\Delta = -2.66\%$).

4. **Common Cohort Label Flips ($N = 174,688$):**
   - Agreement: 94.07% in `LOW_PRICE` (39,840 rows) and 95.11% in `HIGHER_PRICE` (125,862 rows).
   - Label Flips: 5.93% in `LOW_PRICE` (2,511 rows) and 4.89% in `HIGHER_PRICE` (6,475 rows).
   - False Positives in Variant A ($y_A = 1, y_B = 0$): 1,977 in `LOW_PRICE`, 5,213 in `HIGHER_PRICE` ($4:1$ asymmetry ratio vs false negatives).

5. **Entry Band Sensitivity ($\pm 0.5\%$):**
   - 42.31% of `LOW_PRICE` and 34.08% of `HIGHER_PRICE` open prices exceed $\pm 0.5\%$, confirming that strict bands on daily bars would drop over a third of trading opportunities.

---

## 4. Testing Checklist

Before deploying or proceeding to Phase 11B.1, verify the following items:

- [ ] **Universal Report Template:** Confirm `docs/AGENT_REPORT_TEMPLATE.md` exists and is formatted correctly.
- [ ] **Phase 12 Report Integrity:** Inspect `docs/12_phase_11b_target_contract_audit_report.md` for section completeness and repository-relative links.
- [ ] **Audit Index Integrity:** Verify root `audit_report.md` is a concise index linking to reports 09, 10, 11, and 12 with valid repository-relative links.
- [ ] **Target Contract Audit Runner:** Run `& ".venv\Scripts\python.exe" scripts/audit_target_contract_runner.py` and ensure it runs to completion with 0 errors.
- [ ] **Artifact Verification:** Check `artifacts/target_contract/` contains:
  - [ ] `target_contract_summary.csv`
  - [ ] `target_contract_summary.json`
  - [ ] `target_transitions_by_mode.csv`
  - [ ] `target_contract_samples.csv`
- [ ] **Target Contract Unit Tests:** Run `& ".venv\Scripts\python.exe" -m pytest tests/unit/test_target_contract.py` (5 tests must pass).
- [ ] **Full Repository Test Suite:** Run `& ".venv\Scripts\python.exe" -m pytest` (all 460 tests must pass).
- [ ] **Code Formatting & Linter:** Run `& ".venv\Scripts\python.exe" -m ruff check .` (0 errors reported).
- [ ] **Production Model Safeguards:** Verify `models/registry/` was untouched and champion models remain unchanged.
- [ ] **Cumulative Log:** Confirm `summary.md` preserved all previous entries and appended entry 54.
