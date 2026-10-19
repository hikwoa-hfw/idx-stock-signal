# Walkthrough — Phase 11F: Forward Paper Trading & Frozen Policy Validation

## Session Overview

Completed **Phase 11F — Forward Paper Trading & Frozen Policy Validation** review and hardening for the Indonesian Stock AI dual-mode signals. This phase builds the prospective evaluation engine, deterministically freezes the primary research policies, validates scoring artifacts with fail-closed guards, executes historical replay validation under 50 bps round-trip transaction friction, maintains frozen reference benchmarks, and provides comprehensive operational reporting.

During this review session:
1. Reconciled historical benchmark metrics in `frozen_reference_benchmarks.csv`: corrected Phase 11D `net_portfolio_return_pct` (from `0.0%` to actual backtest returns: `+2.12%` for `LOW_PRICE` and `+8.57%` for `HIGHER_PRICE`) and cash exposure (from `time_in_market_pct` to actual `avg_cash_exposure_pct`: `77.35%` and `62.92%`).
2. Implemented end-to-end prospective scoring in `step_prospective_date`: when model artifacts exist, the engine loads `.joblib` estimators via `joblib.load`, extracts `FEATURE_SCHEMA_30` features, computes model inference, ranks candidates, enforces regime filters and sizing multipliers, and records prospective candidates and decisions.
3. Overhauled unit tests in `tests/unit/test_forward_paper_trading.py`: replaced shallow tautological assertions with deep simulation execution tests (testing gap invalidation counters, order rejections, zero cash spent, capacity limits, conservative SL precedence on ambiguous bars, MFE/MAE excursions, and mock artifact prospective scoring).
4. Expanded test coverage to 21 unit tests, achieving a 100% pass rate across the full workspace suite (524 tests passed, 0 failures, 100% ruff clean).

---

## 1. Task Breakdown & Code Modifications

### 1.1 Core Engine: `python/experiments/paper_trading.py`
- **Imports (Lines 20–35):**
  - Added `import joblib` to third-party dependencies block.
- **Reference Benchmarks (Lines 490–525):**
  - Reconciled Phase 11D benchmark records to match empirical findings from Phase 11D/11E:
    * `LOW_PRICE`: `net_portfolio_return_pct: 2.12`, `avg_cash_exposure_pct: 77.35`
    * `HIGHER_PRICE`: `net_portfolio_return_pct: 8.57`, `avg_cash_exposure_pct: 62.92`
- **Prospective Date Scoring (`step_prospective_date`, Lines 1198–1347):**
  - Added `base_dir` parameter for dependency injection during tests and custom deployments.
  - Fail-closed guard: checks `audit_scoring_artifacts(base_dir=base_dir)`. If research scoring artifacts are missing, raises `MissingScoringArtifactError`. Fallback to production champions is strictly forbidden.
  - Prospective inference: when artifacts exist, queries `features_daily` and `daily_bars` for `eval_date`, filters price modes (50–300 for `LOW_PRICE`, >300 for `HIGHER_PRICE`), runs model prediction, applies deterministic sorting (`score desc, ticker asc`), enforces `ihsg_vs_ema20 > 0`, scales allocation via three-tier regime conviction, and saves records to `paper_trading_candidates.csv` and `paper_trading_decisions.csv`.

### 1.2 Unit Tests: `tests/unit/test_forward_paper_trading.py` (Lines 1–640)
- Overhauled test suite to 21 unit tests covering real simulation behavior:
  - `TestPolicyConfigurationAndHashing`: Deterministic SHA-256 computation (`2fa07ad5d2e10ad5c6b873338e648a5194b61bfbe84f02048cd6305e6c355bbd`), parameter sensitivity, 30-feature schema verification.
  - `TestRegimeSizingTiers`: Point-in-time three-tier sizing classification (1.0x, 0.5x, 0.0x).
  - `TestDeterministicTieBreaking`: Sorting candidates by `score desc, ticker asc` in both list sorting and engine simulation ranking.
  - `TestExecutionFidelityAndGapInvalidations`:
    * `test_gap_down_invalidation_in_simulation`: verifies simulated Day 1 Open $\le$ SL increments `invalidated_gap_down`, produces 0 trades, and leaves cash untouched (100,000,000 IDR).
    * `test_gap_up_invalidation_in_simulation`: verifies simulated Day 1 Open $\ge$ TP increments `invalidated_gap_up`, produces 0 trades, and consumes 0 cash.
    * `test_excessive_deviation_invalidation_in_simulation`: verifies simulated Day 1 Open deviation $> 5\%$ increments `invalidated_excessive_dev`, produces 0 trades, and consumes 0 cash.
    * `test_suspended_or_zero_volume_unfilled_in_simulation`: verifies simulated Day 1 Volume $\le 0$ increments `unfilled_suspended` and consumes 0 cash.
    * `test_lot_size_and_cash_accounting`: verifies 100-share lot rounding and capital protection.
    * `test_fee_accounting_50bps_nominal`: verifies 50 bps round-trip nominal transaction friction.
    * `test_ambiguous_bar_conservative_sl_precedence_in_simulation`: executes trade where High $\ge$ TP and Low $\le$ SL on the same bar, verifying exit reason resolves to `"SL"`.
    * `test_mfe_mae_tracking`: executes multi-day trade and verifies `highest_watermark`, `lowest_watermark`, `mfe_pct`, and `mae_pct`.
  - `TestFailClosedScoringArtifactGuard`:
    * `test_scoring_artifacts_audit_missing_fails_closed`: verifies missing H=15 Variant B artifacts flag `BLOCKED_ON_SCORING_ARTIFACT`.
    * `test_prospective_scoring_halts_on_missing_artifact`: verifies `step_prospective_date` raises `MissingScoringArtifactError`.
    * `test_champion_fallback_strictly_forbidden`: verifies champions are blocked from substitution.
    * `test_prospective_scoring_executes_with_mock_artifacts`: creates mock `.joblib` estimators and validates prospective scoring on bull date (`2026-09-18`, generating decisions) and bear date (`2026-10-14`, filtering decisions to 0).
  - `TestOperationalStatusAndBenchmarks`:
    * `test_export_frozen_policy_config`: verifies config JSON structure and hash.
    * `test_export_frozen_reference_benchmarks`: verifies 6 benchmark rows, checking Phase 11D and 11E reconciled metrics.
    * `test_operational_status_generation`: verifies status JSON structure and content.

### 1.3 Machine-Readable Artifacts: `artifacts/phase_11f/`
- `frozen_policy_config.json`: Canonical policy parameters, feature schema, sizing tiers, and SHA-256 hash.
- `frozen_reference_benchmarks.csv`: Reconciled benchmark comparator records for Phase 11D, Phase 11E, and production champions.
- `paper_trading_candidates.csv`: 134,382 decision candidate records with rank, score, and eligibility.
- `paper_trading_decisions.csv`: 1,528 selected decision orders with sizing multiplier and planned barriers.
- `paper_trading_trades.csv`: 481 completed simulated trades with fills, PnL, net return, MFE, and MAE.
- `paper_trading_daily_equity.csv`: Daily cash, equity, and continuous drawdown records.
- `paper_trading_operational_status.json`: Operational status, audit flags, data quality metrics, and error logs.

### 1.4 Governance & Audit Documentation
- `docs/17_phase_11f_forward_paper_trading_report.md`: Universal template report with executive decision `READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)`, reconciled Table 5.2 benchmarks.
- `audit_report.md`: Updated Current Operational State to Phase 11F, Entry 9 test count updated to 524 total suite tests and 21 unit tests.
- `summary.md`: Appended and updated Entry 61 with benchmark reconciliation, prospective scoring implementation, and 21 unit tests.

---

## 2. Verification Record

1. **Unit Tests:**
   ```bash
   .venv\Scripts\python.exe -m pytest tests/unit/test_forward_paper_trading.py -v
   # Result: 21 passed in 2.03s
   ```
2. **Full Workspace Regression Suite:**
   ```bash
   .venv\Scripts\python.exe -m pytest -q
   # Result: 524 passed in 100% full suite
   ```
3. **Linter & Code Hygiene:**
   ```bash
   .venv\Scripts\python.exe -m ruff check .
   # Result: All checks passed! (0 errors)
   ```
4. **Operational Status & Fail-Closed Guard:**
   ```bash
   .venv\Scripts\python.exe scripts/run_forward_paper_trading.py --status
   # Result: READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)
   # Missing Artifacts: 2 (H=15 Variant B models)
   # Fallback Allowed: False

   .venv\Scripts\python.exe scripts/run_forward_paper_trading.py --date 2026-10-19
   # Result: FAIL_CLOSED: MissingScoringArtifactError
   ```
5. **Historical Replay Simulation:**
   ```bash
   .venv\Scripts\python.exe scripts/run_forward_paper_trading.py --run-replay
   # Result:
   # [LOW_PRICE] Trades: 172 | Win: 30.81% | Net: +0.0008 | PF: 1.02 | Max DD: 6.33%
   # [HIGHER_PRICE] Trades: 309 | Win: 33.33% | Net: +0.0010 | PF: 1.04 | Max DD: 8.59%
   ```

---

## Testing Checklist

After pulling these changes, verify:

- [ ] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_forward_paper_trading.py -v` and confirm all 21 unit tests pass.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q` and confirm all 524 tests in the workspace pass with 0 failures.
- [ ] Run `.venv\Scripts\python.exe -m ruff check .` and confirm 0 lint errors across the workspace.
- [ ] Run `.venv\Scripts\python.exe scripts/run_forward_paper_trading.py --status` and verify status code `READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)`.
- [ ] Run `.venv\Scripts\python.exe scripts/run_forward_paper_trading.py --export-benchmarks` and verify config hash `2fa07ad5d2e10ad5c6b873338e648a5194b61bfbe84f02048cd6305e6c355bbd`.
- [ ] Verify that `artifacts/phase_11f/` contains all 7 required files:
  - `frozen_policy_config.json`
  - `frozen_reference_benchmarks.csv`
  - `paper_trading_candidates.csv`
  - `paper_trading_decisions.csv`
  - `paper_trading_trades.csv`
  - `paper_trading_daily_equity.csv`
  - `paper_trading_operational_status.json`
- [ ] Run `.venv\Scripts\python.exe scripts/run_forward_paper_trading.py --date 2026-10-19` and confirm fail-closed exit with code 1.
- [ ] Run `.venv\Scripts\python.exe scripts/run_forward_paper_trading.py --run-replay` and confirm replay logs 172 trades on `LOW_PRICE` and 309 trades on `HIGHER_PRICE`.
- [ ] Inspect `audit_report.md` to confirm Phase 11F status and Entry 9 in the index (524 tests).
- [ ] Inspect `summary.md` to confirm strictly append-only Entry 61.
- [ ] Confirm active production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) remain untouched.
