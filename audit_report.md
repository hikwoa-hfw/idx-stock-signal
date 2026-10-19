# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11D — Dynamic Exit & Policy Selection Research`
- **Audit Date:** `2026-10-19 20:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** Working tree with Phase 11D dynamic policy engine, CLI evaluation runner, and empirical artifacts
- **Overall Status:** `PASS (DO_NOT_PROMOTE)`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - Walk-forward dynamic policy evaluation across entry selectivity (Top 10% to 1%), point-in-time market regime conditioning, dynamic holding periods ($H \in \{3, 5, 10, 15\}$), and alternative TP/SL barriers under the 50 bps round-trip friction model demonstrates that:
    1. **Bull Regime Filtering (`ihsg_vs_ema20 > 0`) is the single most powerful tail-risk reducer:** It cuts continuous drawdown from $45.50\% \rightarrow 16.65\%$ in `LOW_PRICE` and $62.67\% \rightarrow 23.43\%$ in `HIGHER_PRICE`, while cutting net losses by $>70\%$. Conversely, trading in bear regimes (`ihsg_vs_ema20 <= 0`) yields severe losses ($-0.65\%$ to $-0.67\%$ net return, PF $0.63$–$0.64$).
    2. **Combined Policy achieves nominal pooled profitability:** Combining Top 3% entry selectivity, bull trend conditioning, 15-day holding horizon, and $+6\% / -2\%$ barriers yields $+0.08\%$ net return (PF $1.04$) with continuous drawdown suppressed to $9.59\%$ in `LOW_PRICE`. In `HIGHER_PRICE`, Top 1% selectivity with bull trend and $+6\% / -2\%$ yields $+0.13\%$ net return (PF $1.07$, continuous DD $9.77\%$).
    3. **However, forward fold performance lacks uniform robustness:** In `LOW_PRICE`, Fold 1 ($+0.34\%$) drives the gain, while Folds 2 and 3 remain negative ($-0.10\%$ and $-0.16\%$). In `HIGHER_PRICE` Top 1%, Fold 2 is positive ($+0.44\%$), but Fold 1 ($-0.01\%$) and Fold 3 ($-0.11\%$) remain negative. Neither policy achieves uniform cross-fold profitability.
  - **Decision:** Candidates and policies are NOT promoted to production champion status. Current champions remain active and untouched.
- **Next Permitted Action:** Proceed to Phase 11E research design (Dynamic Conviction Sizing and Volatility Trailing Protection) upon user authorization. Do not begin Phase 11E automatically.

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
   - **Scope:** Holding horizons ($H \in \{3, 5, 10, 15\}$ trading days), strict 15-day purge window walk-forward splits, LightGBM Regressor continuous return estimation vs zero & mean baselines, discrete-event simulated trading under 50 bps friction, and Expected Return vs discrete EV diagnostics. Corrected test count documentation to 480 passed unit/regression tests (previously noted as 478 in preliminary text).
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Horizon extension dampens drawdown but fails to cross net profitability threshold; champions preserved).

7. [docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md](docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md)
   - **Phase 11D:** Dynamic Exit & Policy Selection Research
   - **Scope:** Cross-sectional entry selectivity (Top 10%, 5%, 3%, 1%), point-in-time market regime conditioning (IHSG trend, breadth, volatility), dynamic holding periods ($H \in \{5, 10, 15\}$, max predicted return $H^*$, volatility-adaptive, regime-adaptive), dynamic TP/SL barriers (+6%/-2%, +4%/-2%, +5%/-1.5%, ATR-scaled), and combined walk-forward policy under 50 bps round-trip friction.
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Regime conditioning cuts drawdowns by >60%, combined policy achieves +0.08% pooled net return in LOW_PRICE and +0.13% in HIGHER_PRICE Top 1%, but lack of uniform cross-fold robustness prevents deployment; 490 unit/regression tests passed; champions preserved).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
