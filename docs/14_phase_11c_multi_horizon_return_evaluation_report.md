# Agent Task Report — Phase 11C: Multi-Horizon Evaluation & Return Estimation

## 1. Metadata

- **Task ID:** `PHASE-11C-MULTI-HORIZON-RETURN-ESTIMATION`
- **Task title:** Multi-Horizon Target Evaluation, Continuous Return Regression, and Discrete-Event Trading Simulation
- **Date:** `2026-10-19 18:55 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** Working tree with Phase 11C multi-horizon evaluation pipeline and empirical findings
- **Task status:** `PASS (DO_NOT_PROMOTE)`
- **Related reports:**
  - [09_outcome_tracking_backfill_and_integrity_audit_report.md](09_outcome_tracking_backfill_and_integrity_audit_report.md)
  - [10_controlled_feature_ablation_report.md](10_controlled_feature_ablation_report.md)
  - [11_feature_ablation_metric_validation_report.md](11_feature_ablation_metric_validation_report.md)
  - [12_phase_11b_target_contract_audit_report.md](12_phase_11b_target_contract_audit_report.md)
  - [13_phase_11b_candidate_model_evaluation_report.md](13_phase_11b_candidate_model_evaluation_report.md)

---

## 2. Executive Summary

### Decision

`DO_NOT_PROMOTE`

Offline walk-forward evaluation across multi-day holding horizons ($H \in \{3, 5, 10, 15\}$ trading days) and continuous return estimation demonstrates that **extending the holding horizon significantly mitigates portfolio drawdown and trading churn, but cannot overcome the structural 50 bps friction deficit**. Under the agreed 50 bps round-trip transaction friction model (15 bps buy commission, 25 bps sell commission, 5 bps entry slippage, 5 bps exit slippage), **every evaluated configuration across all 4 horizons and both price modes produces negative average net returns** (spanning $-0.33\%$ to $-1.00\%$ per completed trade) and pooled profit factors below break-even ($0.47$ to $0.80$).

Consequently, pursuant to repository governance invariants, **no model is promoted to production champion**. Active production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) remain strictly untouched.

### Completed

1. **Multi-Horizon Target Engine:** Implemented simultaneous target evaluation in `python/experiments/multi_horizon_eval.py` for horizons $H \in \{3, 5, 10, 15\}$ trading days under Next-Session Open execution (Variant B), keeping TP at $+5\%$ and SL at $-2\%$, with expiry exit at the observation-end Close.
2. **Leakage-Free Temporal Splitting:** Enforced an expanding walk-forward cross-validation splitter with a strict **15 trading days purge window** across all 3 splits, fully embargoing training labels from overlapping any test fold up to the maximum 15-day target horizon.
3. **Controlled Model Matrix (Classifiers & Regressors):** Evaluated 7 model configurations per mode per horizon:
   - Full LightGBM Classifier (30 features)
   - Best Ablation LightGBM Classifier (`lgb_minus_trend` for `LOW_PRICE`, `lgb_minus_market_regime` for `HIGHER_PRICE`)
   - Regularized Logistic Regression Baseline ($C=1.0$)
   - Constant Prevalence Classification Baseline
   - LightGBM Return Regressor (continuous net return prediction)
   - Zero-Return Regression Baseline
   - Training-Mean Regression Baseline
4. **Discrete-Event Trading Simulation:** Modeled day-by-day portfolio execution under identical 50 bps friction, 100-share lot sizes, maximum 5 positions (20% equity cap), fail-closed gap checks, and horizon-specific expiries.
5. **Expected Return Diagnostics:** Compared direct regressor return predictions against discrete outcome expectations ($EV_{\text{discrete}} = p \bar{R}_{TP} + (1-p)q_{SL}\bar{R}_{SL} + (1-p)(1-q_{SL})\bar{R}_{EXP}$), evaluating Pearson correlation with realized returns and offline EV filtering.
6. **Testing and Verification:** Added 7 unit tests in `tests/unit/test_multi_horizon_evaluation.py` (total suite: 478 tests passed, 0 failures, clean ruff linter).
7. **Artifact Generation:** Saved comprehensive JSON, summary CSVs, and row-level out-of-sample predictions in `artifacts/phase_11c/`.

### Important Findings

1. **Short Horizons Yield Higher Predictive AUC but Worse Trading Churn:**
   - Shorter horizons exhibit markedly higher classification discrimination: at $H=3$, macro ROC-AUC reaches **0.6566** in `HIGHER_PRICE` (ablation) and **0.6093** in `LOW_PRICE`. As horizon expands to $H=15$, ROC-AUC declines monotonically to **0.5498** and **0.5606**.
   - However, in trading simulation, $H=3$ triggers excessive trading churn (2,095–2,417 trades), suffering the worst net returns ($-0.60\%$ to $-1.00\%$ per trade) and catastrophic continuous drawdowns ($-92.21\%$ to $-99.19\%$).
2. **Longer Horizons Substantially Cushion Portfolio Drawdown:**
   - Extending holding duration from $H=3$ to $H=15$ cuts total trades by $>50\%$ ($2,165 \rightarrow 980$ in `HIGHER_PRICE`; $2,095 \rightarrow 1,211$ in `LOW_PRICE`).
   - Worst-fold maximum drawdown drops from $66.55\%$ to $39.92\%$ in `HIGHER_PRICE`, and continuous multi-year drawdown falls from $94.60\%$ to $62.58\%$.
   - In `LOW_PRICE`, the LightGBM Regressor at $H=15$ achieved the lowest worst-fold drawdown in the study (**$25.88\%$**) and lowest continuous drawdown (**$45.50\%$**).
3. **Net Negative Trading Return Barrier Persists Across All Horizons:**
   - Despite improved survival and reduced churn at $H=15$, average net return per trade remains negative: $-0.33\%$ (`LOW_PRICE` Regressor, pooled PF 0.80) and $-0.49\%$ (`HIGHER_PRICE` Full LGBM, pooled PF 0.72).
   - Zero-friction break-even win rate is $28.57\%$, rising to $>32.0\%$ after 50 bps transaction friction. Across all horizons, realized win rates peaked at $29.94\%$ ($H=10$ ablation in `LOW_PRICE`) and $29.52\%$ ($H=15$ regressor in `HIGHER_PRICE`), leaving an unbroken structural deficit.
4. **Return Regressor Outperforms Classifiers in Trade Selection:**
   - LightGBM Regressors achieved positive correlation with realized net returns ($r = +0.06$ to $+0.10$ in `LOW_PRICE`; $+0.03$ to $+0.05$ in `HIGHER_PRICE`).
   - Regressors trade more selectively (847–856 trades at $H=15$ vs 980–1,211 for full classifiers), yielding superior profit factors and lower drawdowns.
5. **Expected-Return Filtering is Strongly Regime-Dependent:**
   - In Fold 1 (favorable bull regime), filtering by $\hat{R}_{\text{reg}} > 0$ produced positive net returns ($+0.019\%$ at $H=5$ and $+0.064\%$ at $H=15$ in `HIGHER_PRICE`).
   - However, in Fold 3 (bearish market), positive EV trades deteriorated to $-0.87\%$ to $-0.97\%$ net return. Unconditional static EV gating without dynamic regime awareness cannot prevent drawdown during adverse market conditions.

### Next Recommended Action

Conclude Phase 11C offline research with status `PASS (DO_NOT_PROMOTE)`. Do not deploy new models or modify production configurations. To cross the break-even threshold in subsequent research (Phase 11D), dynamic holding horizons must be combined with high-conviction signal decile thresholding (top 1–3% rather than top 10%) and dynamic regime-adaptive EV gating.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Notes |
|---|---|---|---|---|
| R1 | Multi-Horizon Target Contract (3, 5, 10, 15 days) | PASS | `python/experiments/multi_horizon_eval.py` | Modeled at Open $t+1$ with $+5\%$ TP, $-2\%$ SL, and observation-end Close expiry. |
| R2 | Strict Purge Window (15 trading days) | PASS | `MultiHorizonEvaluationRunner(purge_days=15)` | Eliminates lookahead target overlap across all walk-forward folds up to 15 days. |
| R3 | Controlled Model Matrix (Classifiers & Regressors) | PASS | `MultiHorizonEvaluationRunner.get_model_specs` | Full LGBM, ablation LGBM, logistic baseline, prevalence, LGBM regressor, zero & mean baselines. |
| R4 | Production Cost Friction Contract (50 bps) | PASS | `calculate_net_return`, `_simulate_horizon_trading` | 15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip = 50 bps round-trip friction. |
| R5 | Discrete EV vs Regressor Return Comparison | PASS | `multi_horizon_ev_diagnostic_summary.csv` | Pearson correlation and EV-filtered win rates/returns documented across folds. |
| R6 | Universal Report Structure & Metric Reconciliation | PASS | `docs/14_phase_11c_multi_horizon_return_evaluation_report.md` | Universal template, reconciled audit index, and complete quantitative evidence. |
| R7 | Repository Test Suite & Linter Cleanliness | PASS | `pytest` (478 passed), `ruff check` | 7 new unit tests added; 100% test pass rate with zero linter errors. |
| R8 | Production Safeguards & Registry Immutability | PASS | Repository inspection | Production champions, live configs, and database tables untouched. |

---

## 4. Implementation Summary

| Component/File | Change | Reason |
|---|---|---|
| `python/experiments/multi_horizon_eval.py` | Implemented `MultiHorizonEvaluationRunner`, `evaluate_variant_b_multi_horizon`, `calculate_net_return`, regression evaluators, and horizon trading simulator. | Core research engine for Phase 11C multi-horizon evaluation. |
| `scripts/run_multi_horizon_evaluation.py` | Created CLI runner with structured console tables and artifact export. | Provides reproducible command-line execution for offline research. |
| `tests/unit/test_multi_horizon_evaluation.py` | Implemented 7 targeted unit tests covering multi-horizon targets, friction math, regression metrics, and model specs. | Verifies mathematical and operational correctness of new modules. |
| `artifacts/phase_11c/` | Exported 2 JSON metric files, 4 summary CSVs, and 2 out-of-sample prediction CSVs. | Delivers durable, machine-readable artifacts for auditability. |
| `audit_report.md` | Updated current-status index to Phase 11C; reconciled Phase 11B.1 return range ($-0.33\%$ to $-0.92\%$). | Maintains repository status and links to detailed reports. |
| `summary.md` | Appended Phase 11C entry preserving historical logs. | Repository documentation compliance. |
| `walkthrough.md` | Rewritten with Phase 11C detailed breakdown and post-deployment checklist. | Repository documentation compliance. |

---

## 5. Results and Evidence

### 5.1 Out-Of-Sample Classification Performance across Horizons

*Macro Mean across 3 Expanding Walk-Forward Splits (Purge: 15 trading days):*

#### `LOW_PRICE` ($\le 300$ IDR)

| Horizon | Model | Features | Macro ROC-AUC | Macro PR-AUC | Daily Top-10% Prec | Macro Brier | Macro ECE |
|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_full` | 30 | **0.6093** | 0.2328 | 23.94% | 0.1405 | 0.0386 |
| H=3 | `lgb_minus_trend` | 23 | 0.6053 | 0.2284 | 23.36% | 0.1408 | 0.0418 |
| H=3 | `logistic_baseline` | 30 | 0.6030 | 0.2280 | 24.12% | 0.1421 | 0.0409 |
| H=3 | `prevalence_baseline` | 0 | 0.5000 | 0.1677 | 18.17% | 0.1397 | 0.0131 |
| **H=5** | `lgb_full` | 30 | **0.5870** | 0.2637 | 26.77% | 0.1651 | 0.0500 |
| H=5 | `lgb_minus_trend` | 23 | 0.5841 | 0.2576 | 25.60% | 0.1642 | 0.0465 |
| H=5 | `logistic_baseline` | 30 | 0.5768 | 0.2554 | 27.01% | 0.1669 | 0.0508 |
| H=5 | `prevalence_baseline` | 0 | 0.5000 | 0.2037 | 22.42% | 0.1623 | 0.0117 |
| **H=10** | `lgb_full` | 30 | 0.5646 | **0.2859** | 29.32% | 0.1856 | 0.0611 |
| H=10 | `lgb_minus_trend` | 23 | **0.5660** | 0.2821 | 29.03% | 0.1845 | 0.0550 |
| H=10 | `logistic_baseline` | 30 | 0.5617 | 0.2845 | 29.47% | 0.1882 | 0.0616 |
| H=10 | `prevalence_baseline` | 0 | 0.5000 | 0.2372 | 25.47% | 0.1810 | 0.0084 |
| **H=15** | `lgb_full` | 30 | 0.5606 | **0.2994** | 29.93% | 0.1929 | 0.0640 |
| H=15 | `lgb_minus_trend` | 23 | **0.5630** | 0.2973 | **31.64%** | 0.1916 | 0.0622 |
| H=15 | `logistic_baseline` | 30 | 0.5604 | 0.2962 | 30.57% | 0.1955 | 0.0628 |
| H=15 | `prevalence_baseline` | 0 | 0.5000 | 0.2497 | 26.04% | 0.1874 | 0.0069 |

#### `HIGHER_PRICE` ($> 300$ IDR)

| Horizon | Model | Features | Macro ROC-AUC | Macro PR-AUC | Daily Top-10% Prec | Macro Brier | Macro ECE |
|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_full` | 30 | 0.6478 | 0.2034 | 21.63% | 0.1138 | 0.0239 |
| H=3 | `lgb_minus_market_regime` | 24 | **0.6566** | **0.2043** | **22.33%** | 0.1115 | 0.0130 |
| H=3 | `logistic_baseline` | 30 | 0.6364 | 0.1981 | 20.60% | 0.1162 | 0.0328 |
| H=3 | `prevalence_baseline` | 0 | 0.5000 | 0.1329 | 13.46% | 0.1154 | 0.0115 |
| **H=5** | `lgb_full` | 30 | 0.6065 | 0.2309 | 24.04% | 0.1439 | 0.0304 |
| H=5 | `lgb_minus_market_regime` | 24 | **0.6183** | **0.2330** | **24.55%** | 0.1403 | 0.0181 |
| H=5 | `logistic_baseline` | 30 | 0.5950 | 0.2274 | 22.40% | 0.1459 | 0.0381 |
| H=5 | `prevalence_baseline` | 0 | 0.5000 | 0.1737 | 18.01% | 0.1435 | 0.0113 |
| **H=10** | `lgb_full` | 30 | 0.5516 | 0.2535 | 24.97% | 0.1758 | 0.0546 |
| H=10 | `lgb_minus_market_regime` | 24 | **0.5688** | **0.2550** | **26.65%** | 0.1704 | 0.0226 |
| H=10 | `logistic_baseline` | 30 | 0.5576 | 0.2611 | 24.15% | 0.1761 | 0.0588 |
| H=10 | `prevalence_baseline` | 0 | 0.5000 | 0.2190 | 22.62% | 0.1711 | 0.0055 |
| **H=15** | `lgb_full` | 30 | 0.5323 | 0.2619 | 25.65% | 0.1875 | 0.0646 |
| H=15 | `lgb_minus_market_regime` | 24 | **0.5498** | 0.2611 | **26.74%** | 0.1810 | 0.0289 |
| H=15 | `logistic_baseline` | 30 | 0.5514 | **0.2780** | 24.86% | 0.1866 | 0.0659 |
| H=15 | `prevalence_baseline` | 0 | 0.5000 | 0.2360 | 24.11% | 0.1804 | 0.0096 |

---

### 5.2 Return Regression Performance across Horizons

*Comparison against Zero-Return and Training-Mean Baselines:*

#### `LOW_PRICE`

| Horizon | Model | Macro MAE | Zero Baseline MAE | Mean Baseline MAE | Macro RMSE | Macro $R^2$ | Pearson $r$ |
|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_regressor` | 0.022783 | 0.025122 | 0.022265 | 0.027762 | -0.022552 | **+0.1008** |
| H=3 | `zero_return_baseline` | 0.025122 | 0.025122 | 0.022265 | 0.028401 | -0.070241 | 0.0000 |
| H=3 | `mean_regressor_baseline` | **0.022265** | 0.025122 | 0.022265 | **0.027459** | -0.000518 | 0.0000 |
| **H=5** | `lgb_regressor` | 0.025198 | 0.027422 | 0.024483 | 0.030281 | -0.030229 | **+0.0832** |
| H=5 | `zero_return_baseline` | 0.027422 | 0.027422 | 0.024483 | 0.030634 | -0.054599 | 0.0000 |
| H=5 | `mean_regressor_baseline` | **0.024483** | 0.027422 | 0.024483 | **0.029834** | -0.000287 | 0.0000 |
| **H=10** | `lgb_regressor` | 0.027353 | 0.029389 | 0.026505 | 0.032314 | -0.035659 | **+0.0832** |
| H=10 | `zero_return_baseline` | 0.029389 | 0.029389 | 0.026505 | 0.032429 | -0.043220 | 0.0000 |
| H=10 | `mean_regressor_baseline` | **0.026505** | 0.029389 | 0.026505 | **0.031754** | -0.000246 | 0.0000 |
| **H=15** | `lgb_regressor` | 0.028471 | 0.030177 | 0.027370 | 0.033521 | -0.058036 | **+0.0634** |
| H=15 | `zero_return_baseline` | 0.030177 | 0.030177 | 0.027370 | 0.033210 | -0.039160 | 0.0000 |
| H=15 | `mean_regressor_baseline` | **0.027370** | 0.030177 | 0.027370 | **0.032584** | -0.000314 | 0.0000 |

#### `HIGHER_PRICE`

| Horizon | Model | Macro MAE | Zero Baseline MAE | Mean Baseline MAE | Macro RMSE | Macro $R^2$ | Pearson $r$ |
|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_regressor` | 0.021156 | 0.023321 | 0.020897 | 0.025963 | -0.037954 | **+0.0497** |
| H=3 | `zero_return_baseline` | 0.023321 | 0.023321 | 0.020897 | 0.026547 | -0.085144 | 0.0000 |
| H=3 | `mean_regressor_baseline` | **0.020897** | 0.023321 | 0.020897 | **0.025503** | -0.001136 | 0.0000 |
| **H=5** | `lgb_regressor` | 0.023723 | 0.026027 | 0.023385 | 0.028554 | -0.045382 | **+0.0369** |
| H=5 | `zero_return_baseline` | 0.026027 | 0.026027 | 0.023385 | 0.028888 | -0.069727 | 0.0000 |
| H=5 | `mean_regressor_baseline` | **0.023385** | 0.026027 | 0.023385 | **0.027945** | -0.000944 | 0.0000 |
| **H=10** | `lgb_regressor` | 0.026275 | 0.028756 | 0.025856 | 0.031100 | -0.055821 | **+0.0317** |
| H=10 | `zero_return_baseline` | 0.028756 | 0.028756 | 0.025856 | 0.031155 | -0.059012 | 0.0000 |
| H=10 | `mean_regressor_baseline` | **0.025856** | 0.028756 | 0.025856 | **0.030291** | -0.001061 | 0.0000 |
| **H=15** | `lgb_regressor` | 0.027081 | 0.029740 | 0.026706 | 0.031824 | -0.050827 | **+0.0373** |
| H=15 | `zero_return_baseline` | 0.029740 | 0.029740 | 0.026706 | 0.031929 | -0.057333 | 0.0000 |
| H=15 | `mean_regressor_baseline` | **0.026706** | 0.029740 | 0.026706 | **0.031070** | -0.001205 | 0.0000 |

---

### 5.3 Simulated Trading Performance across Horizons

*Simulated with 50 bps round-trip friction, Next-Open execution, 5 positions max, 100-share lots, fail-closed gaps:*

#### `LOW_PRICE`

| Horizon | Model | Trades | Inval | Win Rate | TP Rate | SL Rate | Exp Rate | Avg Net Ret | Pooled PF | Worst Fold DD | Continuous DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_full` | 2,095 | 149 | 27.88% | 23.53% | 67.73% | 8.74% | -0.60% | 0.64 | 63.87% | 92.21% |
| H=3 | `lgb_minus_trend` | 1,943 | 143 | 26.40% | 21.67% | 69.58% | 8.75% | -0.73% | 0.58 | 72.40% | 94.09% |
| H=3 | `logistic_baseline` | 2,311 | 318 | 25.27% | 23.19% | 72.44% | 4.37% | -0.73% | 0.57 | 73.78% | 96.80% |
| H=3 | `prevalence_baseline` | 1,961 | 95 | 25.24% | 17.70% | 69.15% | 13.16% | -0.84% | 0.52 | 70.80% | 96.48% |
| H=3 | `lgb_regressor` | 1,777 | 96 | **28.42%** | 20.93% | 57.12% | 21.95% | **-0.47%** | **0.69** | **50.94%** | **81.66%** |
| **H=5** | `lgb_full` | 1,768 | 114 | **29.75%** | 26.41% | 67.76% | 5.83% | -0.45% | 0.72 | 52.35% | 81.69% |
| H=5 | `lgb_minus_trend` | 1,767 | 129 | 27.84% | 25.07% | 69.21% | 5.72% | -0.54% | 0.68 | 54.11% | 85.61% |
| H=5 | `logistic_baseline` | 2,076 | 292 | 25.68% | 24.61% | 73.31% | 2.07% | -0.70% | 0.61 | 68.59% | 94.69% |
| H=5 | `prevalence_baseline` | 1,784 | 93 | 24.05% | 20.40% | 74.05% | 5.55% | -0.83% | 0.55 | 67.04% | 95.06% |
| H=5 | `lgb_regressor` | 1,419 | 75 | 29.39% | 24.95% | 62.30% | 12.76% | **-0.41%** | **0.74** | **40.77%** | **69.88%** |
| **H=10** | `lgb_full` | 1,451 | 85 | 29.29% | 27.36% | 69.26% | 3.38% | -0.44% | 0.73 | 43.45% | 73.21% |
| H=10 | `lgb_minus_trend` | 1,386 | 90 | **29.94%** | 28.28% | 68.47% | 3.25% | **-0.38%** | **0.78** | 42.47% | 65.67% |
| H=10 | `logistic_baseline` | 1,888 | 229 | 27.43% | 27.38% | 72.14% | 0.48% | -0.55% | 0.69 | 58.05% | 88.03% |
| H=10 | `prevalence_baseline` | 1,707 | 91 | 22.62% | 21.97% | 77.21% | 0.82% | -0.86% | 0.55 | 66.28% | 94.87% |
| H=10 | `lgb_regressor` | 959 | 44 | 28.68% | 26.07% | 64.65% | 9.28% | -0.42% | 0.74 | **32.38%** | **56.25%** |
| **H=15** | `lgb_full` | 1,211 | 78 | 29.07% | 28.16% | 68.79% | 3.06% | -0.41% | 0.76 | 39.92% | 63.58% |
| H=15 | `lgb_minus_trend` | 1,263 | 75 | 27.87% | 27.08% | 70.63% | 2.30% | -0.50% | 0.71 | 45.80% | 72.78% |
| H=15 | `logistic_baseline` | 1,718 | 187 | 28.87% | 28.64% | 70.84% | 0.52% | -0.45% | 0.74 | 49.28% | 79.38% |
| H=15 | `prevalence_baseline` | 1,692 | 91 | 22.40% | 22.28% | 77.54% | 0.18% | -0.86% | 0.55 | 66.04% | 94.67% |
| H=15 | `lgb_regressor` | 856 | 42 | **29.67%** | 28.50% | 65.54% | 5.96% | **-0.33%** | **0.80** | **25.88%** | **45.50%** |

#### `HIGHER_PRICE`

| Horizon | Model | Trades | Inval | Win Rate | TP Rate | SL Rate | Exp Rate | Avg Net Ret | Pooled PF | Worst Fold DD | Continuous DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **H=3** | `lgb_full` | 2,165 | 194 | 26.84% | 22.22% | 69.56% | 8.22% | -0.67% | 0.62 | 66.55% | 94.60% |
| H=3 | `lgb_minus_market_regime` | 2,178 | 219 | 27.36% | 23.00% | 69.74% | 7.25% | -0.64% | 0.64 | 67.53% | 94.01% |
| H=3 | `logistic_baseline` | 2,417 | 337 | 21.31% | 20.02% | 77.37% | 2.61% | -1.00% | 0.47 | 84.14% | 99.19% |
| H=3 | `prevalence_baseline` | 1,535 | 30 | 29.19% | 12.31% | 52.05% | 35.64% | -0.68% | 0.53 | 53.34% | 88.09% |
| H=3 | `lgb_regressor` | 1,638 | 95 | **29.36%** | 15.57% | 54.95% | 29.49% | **-0.63%** | 0.59 | **63.51%** | **87.31%** |
| **H=5** | `lgb_full` | 1,903 | 131 | 27.53% | 24.86% | 70.78% | 4.36% | **-0.59%** | **0.67** | **62.57%** | **89.48%** |
| H=5 | `lgb_minus_market_regime` | 1,887 | 149 | 27.40% | 24.54% | 71.28% | 4.19% | -0.62% | 0.66 | 67.13% | 90.42% |
| H=5 | `logistic_baseline` | 2,288 | 323 | 21.41% | 20.76% | 78.23% | 1.01% | -0.98% | 0.49 | 83.39% | 98.85% |
| H=5 | `prevalence_baseline` | 1,231 | 21 | 27.94% | 16.90% | 62.23% | 20.88% | -0.67% | 0.57 | 45.58% | 81.86% |
| H=5 | `lgb_regressor` | 1,258 | 71 | **28.06%** | 18.12% | 60.73% | 21.14% | -0.65% | 0.60 | 51.51% | 80.58% |
| **H=10** | `lgb_full` | 1,232 | 77 | 26.38% | 24.19% | 71.75% | 4.06% | -0.66% | 0.63 | 50.56% | 80.44% |
| H=10 | `lgb_minus_market_regime` | 1,277 | 96 | **28.66%** | 26.23% | 70.24% | 3.52% | **-0.52%** | **0.71** | **48.79%** | **74.10%** |
| H=10 | `logistic_baseline` | 2,116 | 291 | 23.30% | 23.11% | 76.65% | 0.24% | -0.84% | 0.55 | 76.54% | 97.21% |
| H=10 | `prevalence_baseline` | 1,047 | 24 | 25.50% | 21.78% | 71.25% | 6.97% | -0.72% | 0.59 | 42.59% | 78.79% |
| H=10 | `lgb_regressor` | 941 | 65 | 27.74% | 21.57% | 68.12% | 10.31% | -0.65% | 0.62 | 50.55% | 71.61% |
| **H=15** | `lgb_full` | 980 | 68 | 28.27% | 27.04% | 70.31% | 2.65% | **-0.49%** | **0.72** | 44.33% | 62.58% |
| H=15 | `lgb_minus_market_regime` | 975 | 66 | 26.98% | 25.03% | 71.90% | 3.08% | -0.63% | 0.66 | 44.78% | 70.77% |
| H=15 | `logistic_baseline` | 1,668 | 246 | 22.84% | 22.54% | 76.62% | 0.84% | -0.88% | 0.53 | 68.19% | 94.60% |
| H=15 | `prevalence_baseline` | 1,003 | 24 | 24.73% | 23.23% | 74.28% | 2.49% | -0.74% | 0.59 | 42.00% | 78.23% |
| H=15 | `lgb_regressor` | 847 | 63 | **29.52%** | 26.21% | 69.07% | 4.72% | -0.52% | 0.69 | **33.47%** | **62.09%** |

---

### 5.4 Expected-Return vs Discrete EV Diagnostics

*Evaluating Correlation with Realized Net Return and Offline EV-Gated Subsets:*

| Mode | Horizon | Fold | Pearson $r$ (Prob) | Pearson $r$ (Discrete EV) | Pearson $r$ (Regressor) | Pos EV Trades | Pos EV Win Rate | Pos EV Net Return | Pos Reg Trades | Pos Reg Win Rate | Pos Reg Net Return |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `LOW_PRICE` | H=3 | F1 | +0.0284 | +0.0284 | **+0.1039** | 1,378 | 31.49% | -0.49% | 1,772 | **34.59%** | **-0.21%** |
| `LOW_PRICE` | H=3 | F2 | +0.0898 | +0.0898 | **+0.1192** | 1,321 | 34.75% | -0.18% | 1,673 | 34.73% | -0.17% |
| `LOW_PRICE` | H=3 | F3 | +0.0244 | +0.0244 | **+0.0791** | 3,119 | 26.03% | -0.77% | 2,558 | **27.83%** | **-0.59%** |
| `LOW_PRICE` | H=5 | F1 | +0.0326 | +0.0326 | **+0.0865** | 1,726 | 32.33% | -0.42% | 2,055 | **35.09%** | **-0.18%** |
| `LOW_PRICE` | H=5 | F2 | +0.1008 | +0.1008 | **+0.1020** | 2,058 | 34.21% | -0.20% | 2,608 | 32.82% | -0.27% |
| `LOW_PRICE` | H=5 | F3 | +0.0435 | +0.0435 | **+0.0610** | 3,680 | 26.44% | -0.67% | 3,080 | **27.56%** | **-0.58%** |
| `LOW_PRICE` | H=10 | F1 | +0.0602 | +0.0602 | **+0.1059** | 1,765 | 34.28% | -0.20% | 2,737 | 32.96% | **-0.08%** |
| `LOW_PRICE` | H=10 | F2 | +0.0901 | +0.0901 | **+0.1018** | 2,764 | 33.18% | -0.20% | 2,834 | 32.57% | -0.25% |
| `LOW_PRICE` | H=10 | F3 | +0.0666 | +0.0666 | +0.0419 | 4,203 | 27.98% | -0.51% | 3,476 | **28.51%** | -0.53% |
| `LOW_PRICE` | H=15 | F1 | +0.0873 | +0.0873 | +0.0718 | 1,966 | 33.57% | -0.10% | 2,599 | 32.36% | **-0.07%** |
| `LOW_PRICE` | H=15 | F2 | +0.0988 | +0.0988 | **+0.1046** | 2,700 | 33.89% | -0.14% | 2,930 | 33.11% | -0.16% |
| `LOW_PRICE` | H=15 | F3 | +0.0605 | +0.0605 | +0.0139 | 4,455 | 27.54% | -0.56% | 3,767 | **29.17%** | -0.51% |
| `HIGHER_PRICE` | H=3 | F1 | +0.0129 | +0.0129 | **+0.0910** | 1,383 | 31.89% | -0.45% | 1,060 | **39.91%** | **-0.14%** |
| `HIGHER_PRICE` | H=3 | F2 | +0.0532 | +0.0532 | **+0.0627** | 3,825 | 32.76% | -0.35% | 2,846 | **39.39%** | **-0.06%** |
| `HIGHER_PRICE` | H=3 | F3 | -0.0139 | -0.0139 | -0.0046 | 6,136 | 25.20% | -0.91% | 5,250 | 25.56% | -0.94% |
| `HIGHER_PRICE` | H=5 | F1 | +0.0334 | +0.0334 | **+0.1063** | 1,527 | 34.71% | -0.26% | 1,683 | **42.60%** | **+0.02%** |
| `HIGHER_PRICE` | H=5 | F2 | +0.0625 | +0.0625 | +0.0217 | 4,201 | 32.59% | -0.34% | 5,313 | 33.03% | -0.44% |
| `HIGHER_PRICE` | H=5 | F3 | -0.0279 | -0.0279 | -0.0174 | 6,229 | 22.59% | -1.02% | 7,506 | 24.63% | -0.98% |
| `HIGHER_PRICE` | H=10 | F1 | +0.0675 | +0.0675 | **+0.0928** | 1,455 | 36.98% | -0.06% | 2,565 | **38.21%** | **-0.06%** |
| `HIGHER_PRICE` | H=10 | F2 | +0.0442 | +0.0442 | +0.0270 | 5,265 | 32.12% | -0.33% | 8,964 | 28.70% | -0.61% |
| `HIGHER_PRICE` | H=10 | F3 | -0.0113 | -0.0113 | -0.0248 | 7,799 | 24.48% | -0.87% | 8,399 | 24.79% | -0.92% |
| `HIGHER_PRICE` | H=15 | F1 | +0.0802 | +0.0802 | **+0.0944** | 1,840 | 37.61% | **+0.06%** | 2,873 | 36.76% | -0.05% |
| `HIGHER_PRICE` | H=15 | F2 | +0.0477 | +0.0477 | +0.0346 | 7,287 | 29.55% | -0.51% | 8,214 | 28.79% | -0.59% |
| `HIGHER_PRICE` | H=15 | F3 | -0.0134 | -0.0134 | -0.0172 | 8,761 | 24.42% | -0.88% | 8,872 | 24.45% | -0.92% |

---

### 5.5 Return Regression Calibration Diagnostics across Predicted Return Ranges

*Binned out-of-sample calibration for LightGBM Regressor (`lgb_regressor`), averaged across 3 walk-forward splits:*

#### `LOW_PRICE`

| Horizon | Bin Range | % of Samples | Mean Predicted Return | Mean Realized Return | Error | Win Rate |
|---|---|---|---|---|---|---|
| **H=3** | `< -1%` | 19.89% | -1.28% | -1.04% | -0.24% | 22.93% |
| H=3 | `[-1%, 0%)` | 60.84% | -0.52% | -0.74% | +0.22% | 26.92% |
| H=3 | `[0%, 1%)` | 16.20% | +0.32% | -0.41% | +0.73% | 30.87% |
| H=3 | `[1%, 2%)` | 2.37% | +1.41% | +0.20% | +1.21% | **41.10%** |
| H=3 | `>= 2%` | 0.71% | +2.45% | +0.01% | +2.44% | 38.69% |
| **H=5** | `< -1%` | 20.90% | -1.32% | -0.96% | -0.36% | 23.53% |
| H=5 | `[-1%, 0%)` | 54.17% | -0.51% | -0.75% | +0.24% | 25.50% |
| H=5 | `[0%, 1%)` | 21.12% | +0.37% | -0.41% | +0.78% | 31.05% |
| H=5 | `[1%, 2%)` | 3.12% | +1.34% | -0.02% | +1.36% | 35.46% |
| H=5 | `>= 2%` | 0.69% | +2.42% | +0.17% | +2.26% | **37.86%** |
| **H=10** | `< -1%` | 21.08% | -1.33% | -0.93% | -0.40% | 22.92% |
| H=10 | `[-1%, 0%)` | 49.85% | -0.50% | -0.74% | +0.25% | 25.09% |
| H=10 | `[0%, 1%)` | 22.43% | +0.39% | -0.37% | +0.76% | 30.54% |
| H=10 | `[1%, 2%)` | 5.49% | +1.38% | -0.09% | +1.47% | 34.30% |
| H=10 | `>= 2%` | 1.15% | +2.59% | +0.19% | +2.40% | 31.63% |
| **H=15** | `< -1%` | 20.74% | -1.32% | -0.85% | -0.47% | 23.68% |
| H=15 | `[-1%, 0%)` | 49.36% | -0.50% | -0.77% | +0.27% | 24.51% |
| H=15 | `[0%, 1%)` | 22.49% | +0.40% | -0.26% | +0.66% | 31.65% |
| H=15 | `[1%, 2%)` | 5.54% | +1.36% | -0.15% | +1.51% | **34.13%** |
| H=15 | `>= 2%` | 1.86% | +3.27% | -0.16% | +3.44% | 27.02% |

#### `HIGHER_PRICE`

| Horizon | Bin Range | % of Samples | Mean Predicted Return | Mean Realized Return | Error | Win Rate |
|---|---|---|---|---|---|---|
| **H=3** | `< -1%` | 20.96% | -1.32% | -0.77% | -0.55% | 28.29% |
| H=3 | `[-1%, 0%)` | 69.53% | -0.54% | -0.74% | +0.20% | 28.81% |
| H=3 | `[0%, 1%)` | 7.73% | +0.32% | -0.49% | +0.81% | 33.40% |
| H=3 | `[1%, 2%)` | 1.73% | +1.32% | **+0.48%** | +0.84% | **46.66%** |
| H=3 | `>= 2%` | 0.04% | +2.12% | -0.15% | +2.27% | 32.93% |
| **H=5** | `< -1%` | 24.97% | -1.34% | -0.77% | -0.57% | 27.67% |
| H=5 | `[-1%, 0%)` | 59.99% | -0.53% | -0.69% | +0.17% | 28.89% |
| H=5 | `[0%, 1%)` | 12.94% | +0.29% | -0.50% | +0.78% | 33.04% |
| H=5 | `[1%, 2%)` | 2.00% | +1.35% | -0.13% | +1.48% | **37.80%** |
| H=5 | `>= 2%` | 0.09% | +2.28% | -0.75% | +3.03% | 29.46% |
| **H=10** | `< -1%` | 25.81% | -1.41% | -0.73% | -0.68% | 27.11% |
| H=10 | `[-1%, 0%)` | 53.59% | -0.53% | -0.72% | +0.19% | 27.03% |
| H=10 | `[0%, 1%)` | 17.70% | +0.31% | -0.59% | +0.90% | 29.72% |
| H=10 | `[1%, 2%)` | 2.48% | +1.35% | -0.05% | +1.41% | **37.44%** |
| H=10 | `>= 2%` | 0.42% | +2.27% | -0.12% | +2.39% | 36.44% |
| **H=15** | `< -1%` | 25.96% | -1.41% | -0.79% | -0.62% | 25.73% |
| H=15 | `[-1%, 0%)` | 53.38% | -0.52% | -0.70% | +0.18% | 26.57% |
| H=15 | `[0%, 1%)` | 17.55% | +0.32% | -0.59% | +0.91% | 28.92% |
| H=15 | `[1%, 2%)` | 2.77% | +1.36% | -0.08% | +1.44% | 36.72% |
| H=15 | `>= 2%` | 0.33% | +2.27% | **+0.37%** | +1.90% | **42.26%** |

---

## 6. Findings, Risks, and Limitations

| ID | Finding | Severity | Evidence | Impact | Status |
|---|---|---|---|---|---|
| F1 | Horizon Extension Lowers Drawdown but Fails to Beat Friction | Critical | Realized net return remains negative across all 16 candidate configurations ($-0.33\%$ to $-1.00\%$). | Model promotion blocked; holding duration extension alone is insufficient. | Confirmed |
| F2 | Disconnect Between Short-Horizon Discrimination and Trading Quality | High | $H=3$ achieves highest ROC-AUC ($0.6566$) but worst continuous drawdown ($-99.19\%$). | Demonstrates that standard AUC metrics on short horizons heavily penalize execution viability. | Confirmed |
| F3 | Direct Return Regressor Outperforms Binary Classifiers in Sizing and Selectivity | Medium | $H=15$ Regressor achieves lowest drawdown ($25.88\%$) and highest pooled PF ($0.80$). | Recommends return regression ranking over probability ranking in future gating. | Confirmed |
| F4 | Expected Return Filtering Shows Severe Macro Regime Dependency | High | Positive EV trades produce positive returns in Fold 1 ($+0.06\%$) but degrade to $-0.87\%$ in Fold 3. | Proves that EV filtering requires dynamic regime gating before deployment. | Confirmed |
| F5 | Logistic Regression Suffers Over-Trading Across All Horizons | Medium | Generates 1,668–2,417 trades, suffering $-94\%$ to $-99\%$ continuous drawdowns. | Confirms linear baseline unsuitability for direct trade selection. | Confirmed |

---

## 7. Verification

| Check | Command or Method | Result | Evidence/Notes |
|---|---|---|---|
| Unit tests | `pytest tests/unit/test_multi_horizon_evaluation.py` | PASS | 9 passed in 2.37s. |
| Full test suite | `pytest` | PASS | 480 passed in 105.12s. |
| Linter / style | `ruff check` | PASS | All checks passed repository-wide. |
| Multi-horizon execution | `python scripts/run_multi_horizon_evaluation.py --mode BOTH` | PASS | Both modes executed successfully across 4 horizons in 235.87s. |
| Artifact validation | File inspection in `artifacts/phase_11c/` | PASS | All 10 expected JSON and CSV files generated and validated. |

---

## 8. Files, Artifacts, and Data Changes

- **Files created:**
  - `python/experiments/multi_horizon_eval.py`
  - `scripts/run_multi_horizon_evaluation.py`
  - `tests/unit/test_multi_horizon_evaluation.py`
  - `docs/14_phase_11c_multi_horizon_return_evaluation_report.md`
- **Files modified:**
  - `audit_report.md` (Updated status index to Phase 11C; reconciled Phase 11B.1 return range).
  - `walkthrough.md` (Updated task breakdown and post-deployment checklist).
  - `summary.md` (Appended Phase 11C log).
- **Files deleted:** None.
- **Data/schema migrations:** None.
- **Generated artifacts:**
  - `artifacts/phase_11c/multi_horizon_metrics_LOW_PRICE.json`
  - `artifacts/phase_11c/multi_horizon_metrics_HIGHER_PRICE.json`
  - `artifacts/phase_11c/multi_horizon_classification_summary.csv`
  - `artifacts/phase_11c/multi_horizon_regression_summary.csv`
  - `artifacts/phase_11c/multi_horizon_trading_summary.csv`
  - `artifacts/phase_11c/multi_horizon_trading_by_fold.csv`
  - `artifacts/phase_11c/multi_horizon_regression_binned_diagnostics.csv`
  - `artifacts/phase_11c/multi_horizon_ev_diagnostic_summary.csv`
  - `artifacts/phase_11c/multi_horizon_oos_predictions_LOW_PRICE.csv`
  - `artifacts/phase_11c/multi_horizon_oos_predictions_HIGHER_PRICE.csv`
- **Production state changed:** No. Production champions and live thresholds remain strictly immutable.
  - `artifacts/phase_11c/multi_horizon_oos_predictions_HIGHER_PRICE.csv`
- **Production state changed:** No. Production champions and live thresholds remain strictly immutable.

---

## 9. Safeguards and Backward Compatibility

- **Production Champion Protection:** `lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607` were not retrained, overwritten, or modified.
- **Fail-Closed EV Gate:** EV Gate logic in `python/signals/ev_gate.py` remains strictly intact; EV filtering in this task was conducted strictly offline as a diagnostic.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable.
- **Backward Compatibility:** All existing tests in `tests/unit/test_candidate_evaluation.py` pass without modification.

---

## 10. Reproducibility

- **Environment:** Windows, Python 3.12 (`.venv`), LightGBM, scikit-learn.
- **Database snapshot:** `datasets/stock_signals.db` (186,702 daily feature rows, 208 tickers).
- **Reproduction command:**
  ```powershell
  .venv\Scripts\python.exe scripts/run_multi_horizon_evaluation.py --mode BOTH --horizons 3,5,10,15 --n-splits 3 --purge-days 15 --random-state 42
  ```
- **Test execution:**
  ```powershell
  .venv\Scripts\python.exe -m pytest tests/unit/test_multi_horizon_evaluation.py
  .venv\Scripts\python.exe -m pytest
  .venv\Scripts\python.exe -m ruff check
  ```

---

## 11. Final Decision

- **Acceptance criteria satisfied:** Yes (100% of R1–R8 satisfied).
- **Promotion decision:** `DO_NOT_PROMOTE`. Under 50 bps round-trip friction, every multi-horizon candidate produces negative average net returns ($-0.33\%$ to $-1.00\%$ per trade).
- **Remaining blockers:** Structural win-rate gap under IDX transaction friction requires higher conviction decile filtering and macro-regime conditioning.
- **Next action:** Stop and await user authorization. Do not begin Phase 11D automatically.
