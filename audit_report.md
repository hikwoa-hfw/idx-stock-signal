# Repository Status & Audit Index — BEI Dual-Mode Stock Signals

## Current Operational State

- **Current Phase:** `Phase 11E — Dynamic Conviction Sizing & Volatility Trailing Protection Research`
- **Audit Date:** `2026-10-19 22:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Latest Commit SHA:** Working tree with Phase 11E sizing & trailing engine, CLI runner, empirical artifacts, and comprehensive test suite
- **Overall Status:** `PASS (DO_NOT_PROMOTE)`
- **Active Production Champions:**
  - `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active)
- **Primary Empirical Finding & Decision:**
  - Out-of-sample investigation of dynamic conviction sizing (Conservative binary, Three-tier regime, Smooth conviction) and volatility trailing protection (Breakeven ratchets, ATR trailing stops, Stepped profit locks) under the 50 bps round-trip friction model demonstrates that:
    1. **Dynamic Position Sizing suppresses portfolio drawdown to record lows:** Three-tier regime sizing ($1.0\times$ Favorable, $0.5\times$ Mixed, $0.0\times$ Unfavorable) cuts continuous drawdown on the baseline from $46.01\% \rightarrow 14.74\%$ in `LOW_PRICE` and $62.67\% \rightarrow 24.23\%$ in `HIGHER_PRICE`. When applied on top of the Phase 11D selective policy (`comb_selective_sizing_alone`), continuous drawdown is suppressed to a record low of **$6.34\%$** in `LOW_PRICE` and **$8.83\%$** in `HIGHER_PRICE`, while maintaining cash reserves ($70.0\%$ to $81.3\%$ average cash exposure).
    2. **Position sizing preserves, but does not create, net expectancy:** Baseline net return per trade remains negative ($-0.14\%$ in `LOW_PRICE`, $-0.26\%$ in `HIGHER_PRICE`). De-allocating capital in adverse or mixed regimes is strictly a capital preservation lever, not an expectancy generator.
    3. **The Trailing Stop Payoff Truncation Paradox:** Trailing stops dramatically increase win rates (surging up to $43.67\%$–$44.48\%$ in `HIGHER_PRICE` and $36.41\%$ in `LOW_PRICE`). However, net trade expectancy and profit factor severely deteriorate (e.g. `HIGHER_PRICE` selective expectancy drops from $+0.13\% \rightarrow -0.06\%$ to $-0.14\%$, PF falls from $1.07 \rightarrow 0.88$–$0.93$). Premature trailing stop hits truncate full $+6.0\%$ target winners on routine daily retracements while preserving full initial stop-loss exposure ($-2.0\%$), asymmetrically shrinking the right tail of the return distribution.
    4. **Persistent forward-fold deficit prevents production promotion:** While the combined selective sizing policy (`comb_selective_sizing_alone`) achieves positive pooled net return ($+0.08\%$ in `LOW_PRICE`, $+0.14\%$ in `HIGHER_PRICE`), forward test folds remain underwater (Fold 2: $-0.10\%$ and Fold 3: $-0.16\%$ in `LOW_PRICE`; Fold 1: $-0.01\%$ and Fold 3: $-0.11\%$ in `HIGHER_PRICE`).
  - **Decision:** Candidates and policies are NOT promoted to production champion status. Current champions remain active and untouched.
- **Next Permitted Action:** Proceed to forward paper-trading design on newly observed market data upon user authorization. Do not begin paper trading or production changes automatically.

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
   - **Status:** `PASS (DO_NOT_PROMOTE)` (Three-tier sizing cuts continuous portfolio drawdown to record low 6.34% in LOW_PRICE and 8.83% in HIGHER_PRICE; trailing stops increase win rate up to 44.5% but truncate winning payoffs and degrade net expectancy; persistent forward-fold deficit prevents promotion; 503 unit/regression tests passed; champions preserved).

---

## Core Operational Invariants & Safeguards

- **Champion Protection:** Production models cannot be modified, re-weighted, or replaced without passing the full Retraining Gate and explicit human authorization.
- **Fail-Closed Gate:** Sizing and BUY signals are blocked if mathematical Expected Value net of fees (40 bps IDX commission + 10 bps slippage = 50 bps friction) is non-positive or non-finite.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable during audit and evaluation phases.
- **Point-in-Time Causality:** All predictive features use data strictly up to Close $t$; execution is modeled strictly at Open $t+1$ or later.
