# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11C — Multi-Horizon Evaluation & Return Estimation`
- **Audit Date:** `2026-10-19 18:55 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** Working tree with Phase 11C multi-horizon evaluation pipeline and empirical findings
- **Overall Status:** `PASS (DO_NOT_PROMOTE)`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - Walk-forward multi-horizon evaluation across holding horizons ($H \in \{3, 5, 10, 15\}$ trading days) and continuous return estimation under Variant B execution with a 15-day purge window confirms that extending holding horizons substantially cushions portfolio drawdown (continuous multi-year drawdown falls from $\sim 95\%$ to $45.50\%$ in `LOW_PRICE` and $62.09\%$ in `HIGHER_PRICE`) and cuts trading churn by $>50\%$.
  - However, under the production 50 bps round-trip friction model (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip), **all evaluated configurations generate net negative returns** ($-0.33\%$ to $-1.00\%$ per trade) and profit factors below 1.0 ($0.47$ to $0.80$).
  - LightGBM Regressors demonstrate positive correlation with realized returns ($r = +0.06$ to $+0.10$ in `LOW_PRICE`; $+0.03$ to $+0.05$ in `HIGHER_PRICE`), selecting more disciplined trades than raw binary classifiers.
  - Expected return filtering exhibits severe macro-regime dependency (profitable in Fold 1 bull market; negative in Fold 3 bear market).
  - **Decision:** Candidates are NOT promoted to production champion status. Current champions remain active and untouched.
- **Next Permitted Action:** Proceed to Phase 11D research design upon user authorization. Do not begin Phase 11D automatically.

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
   - **Scope:** Holding horizons ($H \in \{3, 5, 10, 15\}$ trading days), strict 15-day purge window walk-forward splits, LightGBM Regressor continuous return estimation vs zero & mean baselines, discrete-event simulated trading under 50 bps friction, and Expected Return vs discrete EV diagnostics.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Horizon extension dampens drawdown but fails to cross net profitability threshold; champions preserved).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
