# Walkthrough — Phase 11D: Dynamic Exit & Policy Selection Research

## Overview

In Phase 11D, we conducted a rigorous out-of-sample investigation of post-prediction policy interventions:
1. **Cross-Sectional Selectivity (Experiment A):** Restricting entries to the top percentile (Top 10%, 5%, 3%, 1%) of daily candidates per price mode ($N_d \ge 10$, deterministic tie-breaking).
2. **Market-Regime Conditioning (Experiment B):** Gating new entries using causal point-in-time IHSG trend, market breadth, and volatility indicators.
3. **Dynamic Holding Periods (Experiment C):** Adapting trade duration ($H \in \{3, 5, 10, 15\}$) based on multi-horizon model return predictions or stock volatility.
4. **Dynamic TP/SL (Experiment D):** Evaluating alternative reward-to-risk targets (+6%/-2%, +4%/-2%, +5%/-1.5%, and causal ATR-scaled barriers).
5. **Combined Policy Synthesis:** Combining the highest-conviction mechanisms evaluated under expanding walk-forward splits.

All experiments were conducted offline without retraining models, modifying production champion artifacts, or relaxing the 50 bps round-trip friction contract.

---

## Detailed Task Breakdown & Code Modifications

### 1. Research Engine: `python/experiments/policy_eval.py`
- **Causal Training Statistics (`compute_fold_training_stats`, lines 235–302):**
  - Eliminated test data leakage by querying `features_daily` and `labels_daily` strictly for `date <= train_cutoff_date` (test start date minus 15 trading days purge window).
  - Derived median ATR and causal dynamic TP/SL multipliers from training fold MFE (p75) and median MAE.
- **Turnover and Market Exposure Metrics (`simulate_policy`, lines 312–540):**
  - Added tracking for `eligible_candidates` (total unique test candidates meeting universe criteria).
  - Added `portfolio_turnover` ($\sum \text{entry\_shares} \times \text{entry\_price} / \text{initial\_capital}$) and `daily_turnover`.
  - Added `time_in_market_pct` based on active positions at the beginning of each trading day / entry.
- **Modular Summaries with Baseline Controls (`run_all_phase11d_experiments`, lines 840–1180):**
  - Added baseline control rows across all modular CSV exports:
    - `EXP_A_SELECTIVITY`: `exp_a_control_top5` (both `lgb_regressor` and `lgb_full`).
    - `EXP_B_REGIME`: `exp_b_none` (all regimes control).
    - `EXP_C_DURATION`: `exp_c_fixed_h15` (fixed 15-day control).
    - `EXP_D_TPSL`: `exp_d_control` (fixed +5%/-2% control).
- **Mode-Specific Combined Policies (lines 1115–1150):**
  - Added `combined_policy_top1_trend_tp6` for `HIGHER_PRICE` alongside `combined_policy_top3_trend_tp6` for direct comparison.

### 2. CLI Evaluation Runner: `scripts/run_policy_evaluation.py`
- Formatted summary tables with new columns: `Turnover` and `TimeInMkt`.
- Clean ASCII tabular output for `LOW_PRICE` and `HIGHER_PRICE`.
- Completed 156 policy simulations in 72 seconds.

### 3. Unit Test Suite: `tests/unit/test_policy_evaluation.py`
- Expanded test suite from 6 to 10 comprehensive unit tests:
  - `test_policy_engine_init`: Parameter and path resolution.
  - `test_policy_selectivity_filtering`: Percentile selection and deterministic tie-breaking.
  - `test_policy_regime_filtering`: Blocking new orders on adverse dates while aging open trades.
  - `test_policy_dynamic_duration`: Discrete trade horizon expirations.
  - `test_policy_dynamic_tpsl_barriers`: Target barrier execution precedence.
  - `test_policy_fold_aggregation_math`: Pooled profit factor and drawdown chaining.
  - `test_policy_training_stats_causality`: Strict training partition boundaries and purge enforcement.
  - `test_policy_turnover_and_market_exposure`: Turnover and active-day market exposure metrics.
  - `test_policy_date_with_too_few_candidates`: Minimum universe threshold ($N_d < 10$) skipping.
  - `test_policy_modular_summaries_contain_controls`: Presence of control policies in modular outputs.

### 4. Documentation & Governance
- `docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md`:
  - Created complete audit report matching `docs/AGENT_REPORT_TEMPLATE.md`.
  - Executive decision: `DO_NOT_PROMOTE`.
  - Detailed empirical tables with turnover, time in market, signals removed, and fold dispersions.
- `audit_report.md`:
  - Updated Phase 11D audit status with 490 passed tests.
  - Documented empirical findings and preserved production invariants.
- `summary.md`:
  - Appended entry 59 with complete log of fixes, metrics, and governance rationale.

---

## Key Empirical Findings

1. **Replication of Phase 11C Baselines:**
   - `LOW_PRICE` H=15 Regressor: 856 trades, $-0.33\%$ net return, PF $0.80$, continuous DD $46.01\%$, turnover $154.3\text{x}$, time in market $99.5\%$.
   - `HIGHER_PRICE` H=15 Full Classifier: 980 trades, $-0.49\%$ net return, PF $0.72$, continuous DD $62.67\%$, turnover $166.1\text{x}$, time in market $99.5\%$.
2. **Experiment A (Selectivity):**
   - In `HIGHER_PRICE`, Top 1% selectivity improved win rate to $30.29\%$, net return to $-0.36\%$, continuous DD to $40.58\%$, and reduced turnover to $117.1\text{x}$.
   - In `LOW_PRICE`, Top 5% on `lgb_full` delivered best standalone return ($-0.34\%$, PF $0.79$).
3. **Experiment B (Market-Regime Conditioning):**
   - `ihsg_vs_ema20 > 0` proved to be the single most impactful filter:
     - `LOW_PRICE`: Continuous DD fell from $46.01\% \rightarrow 16.65\%$, net return improved from $-0.33\% \rightarrow -0.10\%$, PF jumped from $0.80 \rightarrow 0.93$.
     - `HIGHER_PRICE`: Continuous DD fell from $62.67\% \rightarrow 23.43\%$, net return improved from $-0.49\% \rightarrow -0.17\%$, PF jumped from $0.72 \rightarrow 0.89$.
   - Conversely, trading in bear regimes (`ihsg_vs_ema20 <= 0`) resulted in catastrophic losses ($-0.65\%$ to $-0.67\%$ net return, PF $0.63$–$0.64$).
4. **Experiment C (Duration):**
   - Fixed $H=15$ remained superior to $H=5$ and $H=10$. Truncating duration increased churn and amplified continuous drawdown.
5. **Experiment D (TP/SL):**
   - Tight stop losses ($-1.5\%$) failed severely due to market noise (SL hit rate $78.5\%$, win rate $18.4\%$, DD $81.3\%$).
   - Quick targets ($+4\%$) improved win rate to $31.96\%$, but compressed payoff reduced net return to $-0.54\%$.
6. **Combined Policy:**
   - `LOW_PRICE` Top 3% (`combined_policy_top3_trend_tp6`): pooled $+0.08\%$ net return, PF $1.04$, continuous DD $9.59\%$. Fold 1 was $+0.34\%$, while Folds 2 and 3 remained negative ($-0.10\%$ and $-0.16\%$).
   - `HIGHER_PRICE` Top 1% (`combined_policy_top1_trend_tp6`): pooled $+0.13\%$ net return, PF $1.07$, continuous DD $9.77\%$. Fold 2 was $+0.44\%$, while Fold 1 ($-0.01\%$) and Fold 3 ($-0.11\%$) remained negative.
   - Governance Decision: `DO_NOT_PROMOTE`. Production champions remain unchanged.

---

## Testing Checklist

After checking out the working tree or reviewing Phase 11D artifacts, verify the following:

- [ ] **Unit Tests:** Run `pytest tests/unit/test_policy_evaluation.py` and verify all 10 tests pass.
- [ ] **Full Regression Suite:** Run `pytest` and verify all 490 tests pass with 0 failures.
- [ ] **Code Linter:** Run `ruff check .` and confirm 0 errors.
- [ ] **CLI Execution:** Run `python scripts/run_policy_evaluation.py` and verify execution completes in under 90 seconds.
- [ ] **Artifact Presence:** Verify that 11 files exist in `artifacts/phase_11d/`:
  - [ ] `artifacts/phase_11d/policy_metrics_LOW_PRICE.json`
  - [ ] `artifacts/phase_11d/policy_metrics_HIGHER_PRICE.json`
  - [ ] `artifacts/phase_11d/policy_summary_all.csv`
  - [ ] `artifacts/phase_11d/policy_summary_by_fold.csv`
  - [ ] `artifacts/phase_11d/baseline_reference_summary.csv`
  - [ ] `artifacts/phase_11d/experiment_a_selectivity_summary.csv`
  - [ ] `artifacts/phase_11d/experiment_b_regime_summary.csv`
  - [ ] `artifacts/phase_11d/experiment_c_duration_summary.csv`
  - [ ] `artifacts/phase_11d/experiment_d_tpsl_summary.csv`
  - [ ] `artifacts/phase_11d/combined_policy_summary.csv`
  - [ ] `artifacts/phase_11d/phase_11d_selected_trades_sample.csv`
- [ ] **Production Champion Invariance:** Verify that production champion models in `models/` and production database tables remain untouched.
- [ ] **Audit Index:** Inspect `audit_report.md` and confirm it links to report `docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md` with status `PASS (DO_NOT_PROMOTE)`.
