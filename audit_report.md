# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11F — Forward Paper Trading & Frozen Policy Validation`
- **Audit Date:** `2026-10-19 23:00 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** Working tree with Phase 11F forward paper trading engine, CLI runner, empirical artifacts, and comprehensive test suite
- **Overall Status:** `PASS (READY_FOR_OBSERVATION / BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - Frozen forward paper-trading protocol and research policies codified for prospective market evaluation without modifying active production champions:
    1. **Policy Freezing & Deterministic Hashing:** Formally froze primary research policies: `LOW_PRICE` (Top 3%, H=15 LightGBM Regressor, TP $+6.0\%$ / SL $-2.0\%$, Three-tier sizing $1.0\times / 0.5\times / 0.0\times$) and `HIGHER_PRICE` (Top 1%, H=15 Full LightGBM Classifier, TP $+6.0\%$ / SL $-2.0\%$, Three-tier sizing $1.0\times / 0.5\times / 0.0\times$). Trailing stops strictly excluded to prevent winning payoff truncation. Policy configuration hashed to canonical SHA-256: `2fa07ad5d2e10ad5c6b873338e648a5194b61bfbe84f02048cd6305e6c355bbd`.
    2. **Scoring Artifact Audit & Fail-Closed Guard:** The audit confirmed that while walk-forward out-of-sample predictions exist from Phase 11C, exact persistent `.joblib` model binaries (`models/registry/lgb_regressor_h15_variant_b.joblib` and `models/registry/lgb_full_classifier_h15_variant_b.joblib`) were evaluated in-memory during Phase 11C and not serialized to disk. The fail-closed guard correctly flags `MISSING_SCORING_ARTIFACT`. In compliance with core governance, fallback to production champions is strictly forbidden.
    3. **Forward Execution Simulation Validation (Historical Replay):** End-to-end replay on Phase 11C OOS predictions confirmed full execution fidelity under 50 bps round-trip nominal friction, lot sizing (100 shares), max 5 positions, 20% equity cap, pre-entry gap invalidations, and conservative SL precedence on ambiguous bars. Continuous portfolio drawdown was suppressed to a record low of **$6.33\%$** in `LOW_PRICE` (172 trades, $+0.08\%$ net return) and **$8.59\%$** in `HIGHER_PRICE` (309 trades, $+0.10\%$ net return).
    4. **Decision:** Candidate policies are NOT promoted to production champion status. Current champions remain active and untouched. The forward paper-trading system is set to `READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)`.
- **Next Permitted Action:** Await user authorization before serializing persistent H=15 research scoring model estimators or ingesting prospective daily bars.

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

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
