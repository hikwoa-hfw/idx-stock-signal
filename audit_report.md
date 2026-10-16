# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11B.0 — Final Target Contract Audit`
- **Audit Date:** `2026-10-16 17:20 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** `ff84511823d8f73ea073939b54e0d0010a88964d`
- **Overall Status:** `NEEDS_DESIGN_DECISION`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Technical Blocker / Required Decision:**
  - Selection of target contract for candidate model retraining in Phase 11B:
    - **Design Option A (Recommended):** Retrain candidate challenger models on **Variant B (Executable-Entry Market-On-Open Target)**, excluding pre-entry invalidated rows ($\le -2\%$ gap-down or $\ge +5\%$ gap-up). Eliminates pre-entry lookahead bias and aligns training directly with execution.
    - **Design Option B:** Dual-target parallel training (train separate candidate models on Variant A and Variant B for comparative backtesting).
- **Next Permitted Action:** Proceed to Phase 11B.1 (Candidate Model Retraining) upon receipt of user/coordinator approval.

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
   - **Status:** `NEEDS_DESIGN_DECISION` (Full reconciliation complete, ready for retraining decision).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
