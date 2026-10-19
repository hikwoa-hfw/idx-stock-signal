# Phase 11C — Multi-Horizon Evaluation & Return Estimation Walkthrough

## Overview & Scope

Phase 11C evaluates whether multi-day holding horizons ($H \in \{3, 5, 10, 15\}$ trading days) and continuous return-regression models improve out-of-sample prediction and simulated net trading performance under the production cost contract (50 bps nominal round-trip friction).

The research contract enforces:
- Target Contract: Next-Session Open-Anchor (Variant B) with $+5\%$ TP and $-2\%$ SL barriers, expiring at observation-end Close.
- Temporal Embargo: Chronological expanding walk-forward splits with a strict **15 trading days purge window** to eliminate forward target overlap across all horizons.
- Controlled Model Matrix: 7 models per mode per horizon (Full LightGBM Classifier, Best Ablation LightGBM, Regularized Logistic Regression, Constant Prevalence, LightGBM Regressor, Zero-Return Baseline, Training-Mean Baseline).
- Governance Safeguards: Production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) and live configurations remain strictly immutable.

---

## Detailed Task Breakdown & Changes

### 1. Multi-Horizon Target & Evaluation Engine
- **File:** `python/experiments/multi_horizon_eval.py`
  - `calculate_net_return(entry_price, exit_price, ...)`: Calculates exact compound net return under 50 bps round-trip friction ($Open_{t+1} \times 1.0005 \times 1.0015$ invested vs $Exit \times 0.9995 \times 0.9975$ net proceeds).
  - `evaluate_variant_b_multi_horizon(entry_bar, forward_bars, horizons=...)`: Efficiently scans forward bars in a single pass, simultaneously evaluating exit conditions, holding days, and net returns across all 4 horizons ($H \in \{3, 5, 10, 15\}$).
  - `MultiHorizonEvaluationRunner`:
    - `load_multi_horizon_data`: Loads features, bars, and precomputes multi-horizon target outcomes for `LOW_PRICE` and `HIGHER_PRICE`.
    - `get_model_specs`: Configures controlled classifiers and regressors (including pruned ablation feature subsets).
    - `run_multi_horizon_evaluation`: Executes walk-forward cross-validation with `purge_days=15`, causal median imputers, daily cross-sectional ranking ($N_d \ge 10$, deterministic tie-breaking), and discrete EV comparison.
    - `_simulate_horizon_trading`: Simulates discrete-event trading with parameterized horizon expiry, 100-share lots, max 5 positions, fail-closed gap checks, and causal morning sizing valuation (using strictly previous day close without today's close lookahead).
    - `export_artifacts`: Exports structured JSON, CSV summaries, fold-level trading CSV, binned calibration CSV, and row-level out-of-sample predictions.
  - **Review Fixes Applied:**
    - Corrected model_id double-prefix bug (`lgb_minus_trend` and `lgb_minus_market_regime`).
    - Isolated ambiguous hit leakage in `evaluate_variant_b_multi_horizon` so hits beyond horizon $h$ do not pollute horizon $h$'s count.
    - Preserved `binned_diagnostics` in JSON and exported `multi_horizon_regression_binned_diagnostics.csv`.
    - Exported `multi_horizon_trading_by_fold.csv` for detailed fold-by-fold simulated trading inspection.
    - Eliminated lookahead to today's close during morning Market-On-Open position valuation.

### 2. Multi-Horizon CLI Runner
- **File:** `scripts/run_multi_horizon_evaluation.py`
  - CLI runner supporting `--mode`, `--horizons`, `--n-splits`, `--purge-days`, `--random-state`, and `--output-dir`.
  - Prints structured multi-horizon summary tables covering classification, return regression, trading metrics, and discrete EV diagnostics.

### 3. Unit Test Suite
- **File:** `tests/unit/test_multi_horizon_evaluation.py`
  - `test_calculate_net_return_contract`: Validates exact net returns for flat ($-49.9$ bps), TP ($+4.48\%$), and SL ($-2.49\%$) trades.
  - `test_multi_horizon_target_barrier_detection`: Tests differential barrier hits and expiries across $H \in \{3, 5, 10, 15\}$.
  - `test_multi_horizon_invalidation_consistency`: Verifies fail-closed gap-down and gap-up invalidations across all horizons.
  - `test_multi_horizon_incomplete_data`: Verifies handling of insufficient forward bars.
  - `test_regression_metrics_evaluation`: Validates MAE, RMSE, $R^2$, and Pearson $r$ calculations.
  - `test_regression_binned_diagnostics`: Validates predicted return range calibration binning.
  - `test_multi_horizon_model_specs`: Asserts completeness and correct feature exclusion for `LOW_PRICE` and `HIGHER_PRICE` ablations.
  - `test_multi_horizon_ambiguous_hit_isolation`: Verifies that ambiguous barrier hits on day $k > h$ do not leak into horizon $h$.
  - `test_multi_horizon_export_artifacts_structure`: Verifies that all 10 JSON and CSV artifacts are generated with proper schema.

### 4. Repository Audit & Status Index
- **File:** `audit_report.md`
  - Updated current phase to `Phase 11C — Multi-Horizon Evaluation & Return Estimation`.
  - Reconciled Phase 11B.1 Executive Summary return range ($-0.33\%$ to $-0.92\%$).
  - Added entry for `docs/14_phase_11c_multi_horizon_return_evaluation_report.md` with status `PASS (DO_NOT_PROMOTE)`.

### 5. Formal Agent Task Report
- **File:** `docs/14_phase_11c_multi_horizon_return_evaluation_report.md`
  - Full universal report following `docs/AGENT_REPORT_TEMPLATE.md` with 11 standardized sections, complete tables (including Table 5.5 for binned calibration diagnostics), and reproduction commands.

---

## Key Empirical Findings

1. **Horizon Discrimination vs Execution Viability Paradox:**
   - Classification ROC-AUC peaks at $H=3$ (up to **0.6566** in `HIGHER_PRICE` and **0.6093** in `LOW_PRICE`) due to short-term momentum predictability.
   - However, $H=3$ suffers from severe over-trading (2,000+ trades) and catastrophic continuous drawdowns ($-92\%$ to $-99\%$).
2. **Drawdown Dampening via Horizon Extension:**
   - Increasing horizon to $H=15$ cuts total trades by $>50\%$ and drastically lowers continuous drawdown from $\sim 95\%$ to **$45.50\%$** (`LOW_PRICE` Regressor) and **$62.09\%$** (`HIGHER_PRICE` Regressor).
   - In `LOW_PRICE`, worst-fold drawdown falls from $63.87\%$ ($H=3$) to **$25.88\%$** ($H=15$).
3. **Net Negative Trading Return Barrier:**
   - Under 50 bps round-trip friction, every evaluated configuration produces negative net returns ($-0.33\%$ to $-1.00\%$ per trade) and profit factors below 1.0 ($0.47$ to $0.80$).
   - Extending holding horizon improves capital preservation, but by itself does not achieve positive net expectancy without higher-conviction gating.
4. **LightGBM Regressor Superiority:**
   - Continuous return regressors achieve positive correlation with realized returns ($r \approx +0.06$ to $+0.10$ in `LOW_PRICE`), filtering out low-conviction signals and achieving the lowest drawdowns.
5. **Expected Return Regime Dependency:**
   - Filtering by positive expected return produces positive net returns in bull regimes (Fold 1: $+0.064\%$), but deteriorates in bear regimes (Fold 3: $-0.87\%$).

---

## Testing Checklist

After pulling these changes or running reproductions, verify the following:

- [x] **Unit Tests:** `pytest tests/unit/test_multi_horizon_evaluation.py` passes all 9 tests.
- [x] **Full Test Suite:** `pytest` passes all 480 tests without error.
- [x] **Code Hygiene:** `ruff check` reports zero linting or formatting errors across the entire codebase.
- [x] **Artifact Verification:** Check that `artifacts/phase_11c/` contains all 10 generated files:
  - `multi_horizon_metrics_LOW_PRICE.json`
  - `multi_horizon_metrics_HIGHER_PRICE.json`
  - `multi_horizon_classification_summary.csv`
  - `multi_horizon_regression_summary.csv`
  - `multi_horizon_trading_summary.csv`
  - `multi_horizon_trading_by_fold.csv`
  - `multi_horizon_regression_binned_diagnostics.csv`
  - `multi_horizon_ev_diagnostic_summary.csv`
  - `multi_horizon_oos_predictions_LOW_PRICE.csv`
  - `multi_horizon_oos_predictions_HIGHER_PRICE.csv`
- [x] **Production Integrity:** Confirm production champions in `models/` and live configs in `configs/` remain untouched.
- [x] **Governance Decision:** Confirm decision `DO_NOT_PROMOTE` is maintained across all documentation.
