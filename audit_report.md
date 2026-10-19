# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11F.1 — Research Scoring Artifact Finalization & Forward Observation Readiness`
- **Audit Date:** `2026-10-19 23:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** Working tree with Phase 11F.1 research scoring models, schema-enforcing wrappers, locked policy hash, and full test suite
- **Overall Status:** `PASS (READY_FOR_OBSERVATION / OBSERVATION_SCHEDULE_ACTIVE)`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - Frozen forward paper-trading protocol and research scoring artifacts finalized for prospective market evaluation without modifying active production champions:
    1. **Research Scoring Estimators Serialized:** Fitted and serialized exact H=15 Variant B estimators up to cutoff `2026-09-25`: `lgb_regressor_h15_variant_b.joblib` (SHA-256: `84170b51...`) and `lgb_full_classifier_h15_variant_b.joblib` (SHA-256: `3192aa5c...`) in `artifacts/phase_11f/research_models/` with full metadata documentation.
    2. **Strict Schema & Causal Imputation:** Codified `ResearchRegressorModel` and `ResearchClassifierModel` enforcing strict 30-feature schema ordering and training-derived median imputation.
    3. **Canonical Policy Hash Locked:** Updated artifact references and locked canonical configuration SHA-256: `8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`. Fail-closed audit transitioned from `BLOCKED` to `PASS`.
    4. **Historical Replay & Test Count Reconciled:** Reconciled 309 continuous replay trades vs 298 fold-partitioned trades (+11 unpurged boundary trades). Verified 541 total passed tests (509 unit, 32 integration).
    5. **Decision:** Candidate policies are NOT promoted to production champion status. Current champions remain active and untouched. The forward paper-trading system is set to `READY_FOR_OBSERVATION (OBSERVATION_SCHEDULE_ACTIVE)`.
- **Next Permitted Action:** Execute daily prospective paper-trading scoring on new market bars at 16:15 WIB under the 3-month observation window.

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
    - **Phase 11F.1:** Research Scoring Artifact Finalization & Forward Observation Readiness
    - **Scope:** Reconstructed H=15 Variant B research scoring estimators (`artifacts/phase_11f/research_models/`), strict schema ordering and causal median imputation wrappers, canonical policy hash locking (`8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`), fail-closed guard transition to PASS, continuous replay trade reconciliation (309 vs 298–301), test count reconciliation (541 passed: 509 unit, 32 integration), and 3-month operational observation schedule.
    - **Status:** `PASS (READY_FOR_OBSERVATION)` (17 new unit tests added, 541 total suite tests passed; champions preserved).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
