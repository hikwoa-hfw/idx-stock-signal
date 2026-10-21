# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11G — Final Repository & Runtime Reconciliation`
- **Audit Date:** `2026-10-21 18:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** `53c04dd41e096904abdeb79a83bce260ff0ca38d` (Phase 11G Final Reconciliation: 617 tests passed 100%, 80% coverage threshold locked, Windows Task Scheduler verified in Ready state, S3 & Lambda cloud synchronization verified)
- **Overall Status:** `PASS (OPERATIONAL_AUTOMATED_PIPELINE / APPROVED_PENDING_FIRST_OBSERVATION)`
- **Detailed Validation Report:** [docs/22_daily_pipeline_automation_validation_report.md](docs/22_daily_pipeline_automation_validation_report.md)
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - **Completed Phase 11G Daily Market-Data-to-Paper-Trading Automation and Reconciliation:**
    1. **6-Stage Operational Orchestrator:** Implemented `DailyPipeline` and `PipelineRunReport` in `python/pipeline/daily_pipeline.py` and CLI `scripts/run_daily_pipeline.py` coordinating Stages A through F with strict fail-closed progression and JSON reporting.
    2. **Fail-Closed Provider Gate & Threshold Reconciliation:** Enforced `allow_mock_fallback=False` in operational paths to reject synthetic fallback. Reconciled and locked minimum ticker coverage threshold to 80% (0.80) across code, CLI defaults, unit tests, and documentation.
    3. **Task Scheduler Verification:** Registered and verified task `\IDX_Stock_Signal_Daily_Pipeline` in `Ready` state (StartWhenAvailable: `True`, weekday trigger 16:30 WIB, last result `0`, next run `2026-10-22 16:30:00`). Silent execution verified via VBS wrapper `scripts/run_scheduled_pipeline.vbs`.
    4. **Makefile Target Reconciled:** Reconciled `Makefile` target `daily-pipeline`. In Windows host environments lacking `make.exe`, equivalent canonical execution is `.venv\Scripts\python.exe -m scripts.run_daily_pipeline`.
    5. **AWS Cloud Synchronization:** Uploaded 194MB SQLite database to S3 `idx-stock-signal-436095651956-data` with SHA-256 validation and automated backup (`database/backups/`). Updated AWS Lambda functions (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) in region `ap-southeast-3`.
    6. **Comprehensive Test Suite & Linter:** All 617 tests passed (585 unit, 32 integration, 0 failures, 100% pass rate; 20 unit tests in pipeline suite). Codebase clean under `ruff check .` (0 errors). Production champions and frozen Phase 11F research models remain strictly intact.
- **Next Permitted Action:** Unattended execution via Windows Task Scheduler at 16:30 WIB on the next active market session (`2026-10-22`). Monitor `logs/pipeline_*.log` and `reports/daily_runs/` for execution reports.

---

## Detailed Audit Reports Index

The repository maintains dedicated, detailed reports for each major governance and development phase:

1. [docs/09_outcome_tracking_backfill_and_integrity_audit_report.md](docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
   - **Phase 9:** Outcome Tracking Historical Backfill & Integrity Audit
   - **Scope:** In-trade bounded excursions (Scope A) vs full-horizon opportunity analysis (Scope B), IDX commission & slippage reconciliation, fail-closed pre-entry gap invalidations.
   - **Status:** `PASS` (31 matured outcomes verified with 0 violations).

2. [docs/10_controlled_feature_ablation_report.md](docs/10_controlled_feature_ablation_report.md)
   - **Phase 11A:** Controlled Feature Ablation for BEI Dual-Mode Stock Signals
   - **Scope:** 7 feature family leave-one-group-out ablations across 3-fold expanding walk-forward splits with 10-day purge window.
   - **Status:** `PASS` (Identified empirical necessity of `market_regime` for `LOW_PRICE` and noise property of `trend` moving averages).

3. [docs/11_feature_ablation_metric_validation_report.md](docs/11_feature_ablation_metric_validation_report.md)
   - **Phase 11A.1:** Metric Validation & Daily Cross-Sectional Ranking
   - **Scope:** Elimination of pooled cross-fold ranking bias, implementation of intra-fold macro aggregation and daily cross-sectional Top-10% precision ($N_d \ge 10$, deterministic tie-breaking), row-level out-of-sample predictions export for 17 models.
   - **Status:** `PASS` (Empirical confirmation of feature pruning hypotheses).

4. [docs/12_phase_11b_target_contract_audit_report.md](docs/12_phase_11b_target_contract_audit_report.md)
   - **Phase 11B.0:** Final Target Contract Audit
   - **Scope:** Discrepancy reconciliation between Close-anchor labels (Variant A) and executable Market-On-Open entries (Variant B). Universal report template compliance, pre-entry gap invalidation quantification, and common-cohort label flip analysis.
   - **Status:** `PASS` (Design decision resolved via empirical candidate evaluation).

5. [docs/13_phase_11b_candidate_model_evaluation_report.md](docs/13_phase_11b_candidate_model_evaluation_report.md)
   - **Phase 11B.1:** Candidate Model Training & Evaluation (Trading Metric Reconciliation)
   - **Scope:** Walk-forward candidate model training across dual target contracts (Variant A vs Variant B), common-cohort evaluation, discrete-event simulated trading with reconciled 50 bps friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip), true pooled profit factor vs mean fold profit factor, and worst-fold max drawdown vs continuous portfolio max drawdown. Executive summary reconciled to $-0.33\%$ to $-0.92\%$ net return range.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Variant B validated for operational fidelity; champions preserved).

6. [docs/14_phase_11c_multi_horizon_return_evaluation_report.md](docs/14_phase_11c_multi_horizon_return_evaluation_report.md)
   - **Phase 11C:** Multi-Horizon Evaluation & Return Estimation
   - **Scope:** Holding horizons ($H \in \{3, 5, 10, 15\}$ trading days), strict 15-day purge window walk-forward splits, LightGBM Regressor continuous return estimation vs zero & mean baselines, discrete-event simulated trading under 50 bps friction, and Expected Return vs discrete EV diagnostics. Corrected test count documentation to 480 passed unit/regression tests.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Horizon extension dampens drawdown but fails to cross net profitability threshold; champions preserved).

7. [docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md](docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md)
   - **Phase 11D:** Dynamic Exit & Policy Selection Research
   - **Scope:** Cross-sectional entry selectivity (Top 10%, 5%, 3%, 1%), point-in-time market regime conditioning (IHSG trend, breadth, volatility), dynamic holding periods ($H \in \{5, 10, 15\}$, max predicted return $H^*$, volatility-adaptive, regime-adaptive), dynamic TP/SL barriers (+6%/-2%, +4%/-2%, +5%/-1.5%, ATR-scaled), and combined walk-forward policy under 50 bps round-trip friction.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Regime conditioning cuts drawdowns by >60%, combined policy achieves +0.08% pooled net return in LOW_PRICE and +0.13% in HIGHER_PRICE Top 1%, but lack of uniform cross-fold robustness prevents deployment; 490 unit/regression tests passed; champions preserved).

8. [docs/16_phase_11e_sizing_trailing_protection_report.md](docs/16_phase_11e_sizing_trailing_protection_report.md)
   - **Phase 11E:** Dynamic Conviction Sizing & Volatility Trailing Protection Research
   - **Scope:** Point-in-time regime conviction sizing (Fixed control, Conservative binary, Three-tier regime, Smooth conviction), volatility-based trailing protection (Breakeven ratchets, causal ATR trailing stops, Stepped profit locks), and combined sizing & trailing protection under 50 bps round-trip friction.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Three-tier sizing cuts continuous portfolio drawdown to record low 6.34% in LOW_PRICE and 8.83% in HIGHER_PRICE; trailing stops increase win rate up to 44.5% but truncate winning payoffs and degrade net expectancy; persistent forward-fold deficit prevents promotion; 13 unit tests added, 503 total suite tests passed; champions preserved).

9. [docs/17_phase_11f_forward_paper_trading_report.md](docs/17_phase_11f_forward_paper_trading_report.md)
   - **Phase 11F:** Forward Paper Trading & Frozen Policy Validation
   - **Scope:** Protocol and policy freezing, configuration hashing (SHA-256: `2fa07ad5d2e10ad5c6b873338e648a5194b61bfbe84f02048cd6305e6c355bbd`), scoring artifact audit and fail-closed guard, forward execution simulation, discrete-event gap invalidations, 50 bps round-trip transaction friction, MFE/MAE tracking, and automated weekly reporting.
   - **Status:** `PASS (READY_FOR_OBSERVATION / BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)` (524 total suite tests passed; 21 unit tests added; champions preserved).

10. [docs/18_phase_11f_research_scoring_and_observation_readiness_report.md](docs/18_phase_11f_research_scoring_and_observation_readiness_report.md)
    - **Phase 11F.2:** Reconcile Research Artifact Paths, Policy Hash, and Operational Readiness
    - **Scope:** Reconciled research artifact paths (`artifacts/phase_11f/research_models/`), verified runtime canonical policy hash (`8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`), decoupled 4 lifecycle statuses, implemented `UserApprovalRequiredError` and `--user-approved` CLI guard, enhanced `audit_scoring_artifacts()` with SHA-256 and smoke tests, documented cutoff metadata with data finality proof, and verified test suite.
    - **Status:** `PASS (READY_FOR_OBSERVATION_PENDING_USER_APPROVAL)` (24 unit tests in scoring module, 548 total suite tests passed: 516 unit, 32 integration; champions preserved).

11. [docs/19_phase_11f_prospective_lifecycle_completion_report.md](docs/19_phase_11f_prospective_lifecycle_completion_report.md)
    - **Phase 11F.3:** Complete Prospective Paper-Trading Lifecycle & State Persistence Engine
    - **Scope:** Fixed `PaperDecision.execution_date` from decision date $t$ to next eligible trading session $t+1$ (`get_next_trading_date()`), implemented multi-session daily lifecycle (Market-on-Open fills, pre-entry gap invalidations, barrier monitoring with conservative ambiguity precedence, 15-day expiry, 50 bps friction), atomic state persistence (`paper_trading_state.json`), strict idempotency (`processed_dates`), live operational reporting with prospective observation metrics, and human authorization guard.
    - **Status:** `PASS (READY_FOR_OBSERVATION_PENDING_USER_APPROVAL)` (14 unit tests in lifecycle module, 562 total suite tests passed: 530 unit, 32 integration; champions preserved).

12. [docs/20_phase_11f_final_readiness_report.md](docs/20_phase_11f_final_readiness_report.md)
    - **Phase 11F.4:** Final Fail-Closed Readiness & Approval-Time Cutoff Patch
    - **Scope:** Decoupled persistent human approval state and cutoff tracking (`--approve-observation`), explicit `effective_observation_cutoff` (`max(data_cutoff, approval_date)`), rejection of pre-approval sessions even if bars are ingested later, dynamic prospective date resolution (`first_allowed_prospective_date`), exception propagation for corrupt state in date resolution, fail-closed historical date rejection ($\le$ cutoff), monotonicity enforcement, missed session and stale order execution guards (`MissedSessionError`), comprehensive data quality validation (`DataQualityError` for missing bars, missing features, schema/coverage, Inf values), state corruption detection (`StateIntegrityError` and `BLOCKED_ON_STATE_CORRUPTION`), and safe migration with timestamped backups.
    - **Status:** `PASS (APPROVED_PENDING_FIRST_OBSERVATION / READY_FOR_OBSERVATION_PENDING_USER_APPROVAL)` (28 unit tests in fail-closed module, 88 total paper trading tests passed, 591 total repository tests passed 100%; ruff clean 0 error; champions preserved).

13. [docs/21_offline_challenger_retraining_report.md](docs/21_offline_challenger_retraining_report.md)
    - **Offline Challenger Retraining:** Fresh Historical Data & Controlled Evaluation
    - **Scope:** 3-fold expanding walk-forward controlled evaluation of candidate classifiers (Full LightGBM, feature ablation, regularized logistic regression, constant prevalence) against production champions under Variant B H=15 MOO target contract and 50 bps round-trip friction. Audited data cutoffs (`scripts/inspect_dataset_splits.py`; latest bar: `2026-10-16`; latest fully observable decision: `2026-09-25`; +36.60% valid rows over champions [+46,343 rows], +0.0% over Phase 11F). Serialized research models in `artifacts/offline_challengers/run_20261021_retraining/`.
    - **Status:** `PASS (DO_NOT_PROMOTE)` (Candidates produce negative net returns between -0.35% and -0.68%; production champions preserved; 6 unit tests added, 597 total repository tests passed 100%; ruff clean 0 error).

14. [docs/22_daily_pipeline_automation_validation_report.md](docs/22_daily_pipeline_automation_validation_report.md)
    - **Phase 11G:** Daily Market-Data-to-Paper-Trading Pipeline Automation & Operational Validation
    - **Scope:** 6-stage operational pipeline orchestrator (`Stage A: Ingestion -> Stage B: Validation Gate -> Stage C: Feature Generation -> Stage D: Feature Readiness -> Stage E: Paper Trading -> Stage F: Reporting`), single CLI entry point (`scripts/run_daily_pipeline.py`), Windows Task Scheduler automation (`IDX_Stock_Signal_Daily_Pipeline` scheduled Mon-Fri 16:30 WIB with `StartWhenAvailable: True`), fail-closed provider rejection (`allow_mock_fallback=False`), point-in-time readiness check, idempotent re-runs, and full prospective lifecycle integration.
    - **Status:** `PASS (AUTOMATED_PIPELINE_OPERATIONAL)` (20 unit/integration tests added, 617 total repository tests passed 100%; ruff clean 0 error; champions and frozen Phase 11F research models preserved).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
