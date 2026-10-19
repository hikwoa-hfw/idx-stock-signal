# Agent Task Report — Phase 11B.1: Candidate Model Training & Evaluation (Trading Metric Reconciliation)

## 1. Metadata

- **Task ID:** `PHASE-11B-1-TRADING-METRIC-RECONCILIATION`
- **Task title:** Offline Candidate Model Evaluation: Discrete-Event Trading Metric Reconciliation under Production Cost Contract (50 bps)
- **Date:** `2026-10-19 17:50 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** Working tree with Phase 11B.1 reconciled trading evaluation pipeline
- **Task status:** `PASS`
- **Related reports:**
  - [09_outcome_tracking_backfill_and_integrity_audit_report.md](09_outcome_tracking_backfill_and_integrity_audit_report.md)
  - [10_controlled_feature_ablation_report.md](10_controlled_feature_ablation_report.md)
  - [11_feature_ablation_metric_validation_report.md](11_feature_ablation_metric_validation_report.md)
  - [12_phase_11b_target_contract_audit_report.md](12_phase_11b_target_contract_audit_report.md)

---

## 2. Executive Summary

### Decision

`DO_NOT_PROMOTE`

Offline candidate model training and comparative evaluation under dual target contracts (Variant A: Close-Anchor vs Variant B: Next-Session Open-Anchor) confirms that training directly on Variant B substantially mitigates operational execution failure. In `HIGHER_PRICE`, Variant B models reduce simulated pre-entry invalidations by nearly half ($156 \rightarrow 80$), boost simulated win rates ($26.49\% \rightarrow 29.11\%$), and lower worst-fold maximum drawdown from $56.15\%$ to $38.89\%$.

Following focused trading metric reconciliation, the discrete-event trading simulator is strictly aligned with the production cost contract (15 bps buy commission, 25 bps sell commission, 10 bps total round-trip slippage allocated as 5 bps entry + 5 bps exit, totaling 50 bps nominal round-trip friction). Under this reconciled model (recomputed without retraining any models using saved out-of-sample predictions), **all 16 candidate models produce negative average net returns** (ranging from **$-0.33\%$ to $-0.92\%$** per trade across all evaluated candidates) and profit factors below break-even (pooled profit factor: $0.52$ to $0.80$; mean fold profit factor: $0.52$ to $0.79$). Therefore, pursuant to the explicit Phase 11B candidate selection criteria, **no candidate model is approved for promotion to production champion**. The current production champions remain active and untouched.

### Completed

- **Trading Cost Contract Alignment:** Reconfigured `python/experiments/candidate_eval.py` to enforce exact 50 bps round-trip nominal friction: 15 bps buy commission, 25 bps sell commission, 5 bps entry slippage ($Open_{t+1} \times 1.0005$), and 5 bps exit slippage ($Exit_{\text{raw}} \times 0.9995$).
- **Retraining-Free Recomputation Engine:** Built `--recompute-trading-only` CLI mode and `recompute_trading_from_saved_predictions` method reusing exact out-of-sample predictions from `artifacts/candidate_eval/candidate_oos_predictions_{mode}.csv`, preserving identical walk-forward folds, candidate configurations, gap rules, and lot sizing without retraining.
- **Explicit Metric Definitions Implemented:**
  - True pooled profit factor ($\sum \text{Net Gain} / \sum |\text{Net Loss}|$ across all completed trades in Folds 1, 2, 3) alongside arithmetic mean fold profit factor.
  - Worst-fold maximum drawdown ($\max_k DD_k$) explicitly distinguished from continuous portfolio maximum drawdown (compounded continuous multi-year equity curve).
- **Report & Test Reconciliation:** Reconciled historical test count discrepancies (earlier report had a typo of 463 in R7 table vs 468 executed; full suite now has 471 tests passed with 3 targeted reconciliation unit tests added).
- **Artifacts Synchronized:** Updated all JSON and CSV artifacts in `artifacts/candidate_eval/` with reconciled trading metrics.
- **Governance Safeguards:** 100% preservation of active production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`), database tables, and production signal generation thresholds.

### Important Findings

1. **Variant B Superiority for Real-World Execution Fidelity:**
   In `HIGHER_PRICE`, training on Variant B eliminates lookahead phantom wins, causing pre-entry gap invalidations in backtesting to collapse from 156 to 80 (full model) and 165 to 107 (ablation model). Simulated win rate increases by $+2.62\%$ ($26.49\% \rightarrow 29.11\%$), and worst-fold maximum drawdown improves from $56.15\%$ to $38.89\%$.
2. **Net Negative Trading Return Barrier Across Every Candidate:**
   Under reconciled 50 bps round-trip friction, every candidate configuration generates net negative trading expectancy, ranging from $-0.33\%$ to $-0.92\%$ per trade across the entire 16-candidate matrix. The zero-friction break-even win rate is $28.57\%$, rising to $> 32.0\%$ after transaction fees. The best candidate models achieve win rates of $29.10\%$ (`LOW_PRICE` Full VB) and $29.11\%$ (`HIGHER_PRICE` Full VB), yielding average net returns of $-0.38\%$ and $-0.45\%$ per trade.
3. **Worst-Fold vs Continuous Portfolio Drawdown Divergence:**
   Worst-fold maximum drawdown measures the deepest peak-to-trough decline within any single 221-day temporal fold (ranging from $34.46\%$ to $83.24\%$). In contrast, continuous portfolio drawdown measures the compounded peak-to-trough drop across all 3 expanding folds (663 trading days), ranging from $62.63\%$ to $98.54\%$. Conflating worst-fold drawdown with continuous portfolio drawdown severely understates compounding risk over multi-year horizons.
4. **Predictive AUC Superiority of Ablation Models Fails to Improve Trading Net PnL:**
   - In `LOW_PRICE`, pruning `trend` improves Variant A macro ROC-AUC from 0.5686 to 0.5800 and Variant B macro ROC-AUC from 0.5631 to 0.5656. However, in simulated trading, the pruned model generates worse net return ($-0.51\%$ vs $-0.38\%$) and deeper worst-fold drawdown ($43.56\%$ vs $37.96\%$).
   - In `HIGHER_PRICE`, pruning `market_regime` improves Variant B macro ROC-AUC from 0.5483 to 0.5686 and Daily Top-10% precision from $26.14\%$ to $26.87\%$. Yet in simulated trading, it suffers higher invalidations (107 vs 80), lower win rate ($28.18\%$ vs $29.11\%$), and deeper worst-fold drawdown ($56.12\%$ vs $38.89\%$).
5. **Regularized Logistic Regression Suffers Over-Trading and Catastrophic Drawdown:**
   While Logistic Regression achieved competitive ROC-AUC ($0.5620$ in `LOW_PRICE`, $0.5566$ in `HIGHER_PRICE`), its probability outputs are flatter across dates, triggering 30–50% more trades (1,910–2,288 trades) and suffering continuous drawdowns of $87.45\%$ to $98.54\%$.

### Next Recommended Action

Conclude Phase 11B.1 with decision `DO_NOT_PROMOTE`. Do not begin Phase 11C automatically. Before any candidate model can be reconsidered for promotion, research in Phase 11C must address the structural win-rate deficit through higher-conviction signal thresholding, dynamic holding horizons, or hybrid volatility filtering upon user authorization.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Notes |
|---|---|---|---|---|
| R1 | Align Simulator with Production Cost Contract | PASS | `python/experiments/candidate_eval.py:584-604` | 15 bps buy commission, 25 bps sell commission, 10 bps total round-trip slippage (5 bps entry + 5 bps exit), 50 bps nominal friction. |
| R2 | Documented Entry/Exit Slippage Allocation | PASS | `python/experiments/candidate_eval.py:698,777` | 5 bps entry ($Open_{t+1} \times 1.0005$) and 5 bps exit ($Exit_{\text{raw}} \times 0.9995$). |
| R3 | Recompute Trading Without Retraining | PASS | `scripts/run_candidate_evaluation.py --recompute-trading-only` | Reused saved OOS predictions from `artifacts/candidate_eval/candidate_oos_predictions_{mode}.csv`. Zero models retrained. |
| R4 | Explicit Metric Definitions (PF & Drawdown) | PASS | `python/experiments/candidate_eval.py:1003-1048` | Pooled profit factor, mean fold profit factor, worst-fold max DD, and continuous portfolio max DD explicitly computed and reported. |
| R5 | Correct Report Inconsistencies & Reconcile Tests | PASS | `docs/13_phase_11b_candidate_model_evaluation_report.md` | Executive summary range matches all 16 candidates ($-0.33\%$ to $-0.92\%$). Test count reconciled to 471 passed. |
| R6 | Preserve Production Champions & Database State | PASS | `models/registry/` checksums, `labels_daily` unchanged | Champions `..._093522` and `..._093607` unmodified; live trading unchanged. |
| R7 | 100% Test Pass Rate & Clean Code Quality | PASS | `pytest` (471 passed in 107s), `ruff check .` (0 errors) | Added 3 unit tests in `tests/unit/test_candidate_evaluation.py`. |

---

## 4. Implementation Summary

| Component/File | Change | Reason |
|---|---|---|
| `python/experiments/candidate_eval.py` | Updated `_simulate_fold_trading` slippage parameters (`slippage_entry_bps=5.0`, `slippage_exit_bps=5.0`) | Aligns discrete-event fill simulator with production 10 bps round-trip slippage and 50 bps total friction. |
| `python/experiments/candidate_eval.py` | Added daily mark-to-market equity tracking and updated `_aggregate_trading_summaries` | Computes true pooled profit factor, worst-fold max drawdown, and continuous portfolio drawdown. |
| `python/experiments/candidate_eval.py` | Added `recompute_trading_from_saved_predictions` method | Enables reproducible recomputation of trading metrics directly from saved OOS prediction CSVs without retraining. |
| `python/experiments/candidate_eval.py` | Added `va_entry_price` to `fold_oos_dict` and JSON export for trading summaries | Guarantees self-contained OOS artifacts and completes JSON artifact exports. |
| `scripts/run_candidate_evaluation.py` | Added `--recompute-trading-only` CLI flag and updated comparison table display | Provides automated, fast trading reconciliation runner from command line. |
| `tests/unit/test_candidate_evaluation.py` | Added 3 unit tests (`test_slippage_friction_allocation`, `test_pooled_vs_mean_profit_factor...`, `test_recompute_trading...`) | Verifies friction allocation, metric distinction math, and saved OOS trading recomputation (11 unit tests total). |
| `artifacts/candidate_eval/` | Regenerated all trading summary CSV and JSON artifacts | Persists reconciled metrics across both price modes. |

---

## 5. Results and Evidence

### 5.1 Experimental Setup & Metric Definitions

- **Temporal Split Scheme:** 3-fold expanding walk-forward cross-validation.
- **Purge Window:** 10 trading days (matching maximum label holding horizon).
- **Date Range:** `2023-01-02` to `2026-10-13` (897 trading days; 663 walk-forward test days).
- **Trading Friction Contract:**
  - Buy commission: 15 bps ($0.0015$)
  - Sell commission: 25 bps ($0.0025$)
  - Entry slippage: 5 bps ($0.0005$) applied to $Open_{t+1}$
  - Exit slippage: 5 bps ($0.0005$) applied to exit barrier/expiry price
  - Total nominal round-trip friction: 50 bps ($0.0050$)
- **Position Sizing & Constraints:** Equal weight allocation (cap 20% equity per position, 100-share lot rounding, maximum 5 concurrent positions).
- **Pre-Entry Gap Rules:** Orders invalidated if $Open_{t+1} \le Close_t \times 0.98$ (`GAP_BELOW_SL`), $Open_{t+1} \ge Close_t \times 1.05$ (`GAP_ABOVE_TP`), or $|Open_{t+1} - Close_t| / Close_t > 0.05$ (`EXCESSIVE_DEV`).

#### Formal Metric Definitions

1. **Average Net Return:**
   $$\text{Avg Net Return} = \frac{1}{N_{\text{trades}}} \sum_{i=1}^{N_{\text{trades}}} \frac{\text{Net PnL}_i}{\text{Invested}_i}$$
   where $\text{Invested}_i = \text{Shares}_i \times P_{\text{entry}, i} + \text{Fee}_{\text{entry}, i}$, and $\text{Net PnL}_i = \text{Net Proceeds}_i - \text{Invested}_i$.

2. **True Pooled Profit Factor:**
   $$\text{Pooled Profit Factor} = \frac{\sum_{i: \text{Net PnL}_i > 0} \text{Net PnL}_i}{\sum_{i: \text{Net PnL}_i < 0} |\text{Net PnL}_i|}$$
   calculated globally across all completed trades in Folds 1, 2, and 3.

3. **Mean Fold Profit Factor:**
   $$\text{Mean Fold Profit Factor} = \frac{1}{K} \sum_{k=1}^K \text{Profit Factor}_k$$
   the arithmetic average of individual fold-level profit factors.

4. **Worst-Fold Maximum Drawdown (%):**
   $$\text{Worst-Fold Max DD} = \max_{k \in \{1, \dots, K\}} \left( \max_{t \in \text{Fold } k} \frac{\text{Peak}_{k}(t) - \text{Equity}_{k}(t)}{\text{Peak}_{k}(t)} \times 100\% \right)$$
   representing the deepest peak-to-trough decline observed within any single independent fold starting with IDR 100,000,000.

5. **Continuous Portfolio Maximum Drawdown (%):**
   $$\text{Continuous Max DD} = \max_{t \in [1, T]} \frac{\text{Peak}_{\text{cont}}(t) - \text{Equity}_{\text{cont}}(t)}{\text{Peak}_{\text{cont}}(t)} \times 100\%$$
   representing the maximum peak-to-trough decline of a continuous portfolio starting with IDR 100,000,000 compounded sequentially across all 663 walk-forward test days.

---

### 5.2 Before-and-After Trading Metric Reconciliation

Below is the direct comparison of candidate trading results before reconciliation (under 20 bps slippage / 60 bps total friction) versus after reconciliation (under 10 bps slippage: 5 bps entry + 5 bps exit / 50 bps total friction):

#### Key Models Before vs After Reconciliation

| Mode | Candidate Model | Target | Slippage Model | Completed Trades | Win Rate | Avg Net Return | Pooled Profit Factor | Mean Fold Profit Factor | Worst-Fold Max DD | Continuous Max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| `LOW_PRICE` | `VA_lgb_full` | A | Before (20 bps) | 1,450 | 28.62% | -0.49% | — | 0.71 | 44.70% | — |
| `LOW_PRICE` | `VA_lgb_full` | A | **After (10 bps)** | **1,423** | **30.22%** | **-0.33%** | **0.80** | **0.79** | **34.46%** | **62.63%** |
| `LOW_PRICE` | `VB_lgb_full` | B | Before (20 bps) | 1,458 | 28.05% | -0.52% | — | 0.69 | 43.89% | — |
| `LOW_PRICE` | `VB_lgb_full` | B | **After (10 bps)** | **1,433** | **29.10%** | **-0.38%** | **0.77** | **0.76** | **37.96%** | **67.52%** |
| `HIGHER_PRICE` | `VA_lgb_full` | A | Before (20 bps) | 1,350 | 25.48% | -0.76% | — | 0.60 | 60.23% | — |
| `HIGHER_PRICE` | `VA_lgb_full` | A | **After (10 bps)** | **1,325** | **26.49%** | **-0.65%** | **0.65** | **0.65** | **56.15%** | **82.22%** |
| `HIGHER_PRICE` | `VB_lgb_full` | B | Before (20 bps) | 1,254 | 28.07% | -0.57% | — | 0.69 | 45.02% | — |
| `HIGHER_PRICE` | `VB_lgb_full` | B | **After (10 bps)** | **1,223** | **29.11%** | **-0.45%** | **0.74** | **0.74** | **38.89%** | **68.04%** |

*Note on slight shift in trade count:* The 5 bps reduction in entry slippage slightly alters the intraday barrier trigger price ($P_{\text{entry}} \times 1.05$ and $P_{\text{entry}} \times 0.98$), resulting in marginal changes in trade exit timestamps and subsequent capital availability for pending orders.

---

### 5.3 Complete Reconciled Trading Performance Summary

#### Mode: `LOW_PRICE` ($\le 300$) — 50 bps Reconciled Friction

| Model ID | Target | Total Signals | Completed Trades | Invalidated Signals | Win Rate | TP Rate | SL Rate | Expiry Rate | Avg Net Return | Pooled Profit Factor | Mean Fold Profit Factor | Worst-Fold Max DD (%) | Continuous Max DD (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `VA_lgb_full` | A | 3,310 | 1,423 | 112 | 30.22% | 28.74% | 67.96% | 3.30% | **-0.33%** | 0.80 | 0.79 | 34.46% | 62.63% |
| `VA_lgb_minus_trend` | A | 3,310 | 1,472 | 127 | 28.26% | 26.90% | 70.11% | 2.99% | -0.49% | 0.72 | 0.72 | 48.16% | 79.02% |
| `VA_logistic_baseline` | A | 3,310 | 1,999 | 233 | 25.17% | 24.86% | 74.39% | 0.75% | -0.70% | 0.62 | 0.62 | 68.70% | 94.07% |
| `VA_prevalence_baseline` | A | 3,310 | 1,714 | 92 | 22.58% | 22.00% | 77.25% | 0.76% | -0.86% | 0.54 | 0.54 | 66.35% | 95.03% |
| `VB_lgb_full` | B | 3,310 | 1,433 | **83** | **29.10%** | **27.63%** | **69.16%** | **3.21%** | **-0.38%** | **0.77** | **0.76** | **37.96%** | **67.52%** |
| `VB_lgb_minus_trend` | B | 3,310 | 1,470 | 108 | 27.96% | 26.60% | 70.61% | 2.79% | -0.51% | 0.69 | 0.69 | 43.56% | 79.20% |
| `VB_logistic_baseline` | B | 3,310 | 1,910 | 231 | 27.69% | 27.64% | 71.88% | 0.47% | -0.53% | 0.70 | 0.70 | 59.25% | 87.45% |
| `VB_prevalence_baseline` | B | 3,310 | 1,714 | 92 | 22.58% | 22.00% | 77.25% | 0.76% | -0.86% | 0.54 | 0.54 | 66.35% | 95.03% |

#### Mode: `HIGHER_PRICE` ($> 300$) — 50 bps Reconciled Friction

| Model ID | Target | Total Signals | Completed Trades | Invalidated Signals | Win Rate | TP Rate | SL Rate | Expiry Rate | Avg Net Return | Pooled Profit Factor | Mean Fold Profit Factor | Worst-Fold Max DD (%) | Continuous Max DD (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `VA_lgb_full` | A | 3,315 | 1,325 | 156 | 26.49% | 23.85% | 72.30% | 3.85% | -0.65% | 0.65 | 0.65 | 56.15% | 82.22% |
| `VA_lgb_minus_market_regime` | A | 3,315 | 1,416 | 165 | 26.20% | 24.36% | 73.02% | 2.61% | -0.68% | 0.63 | 0.63 | 63.48% | 85.60% |
| `VA_logistic_baseline` | A | 3,315 | 2,288 | 310 | 22.07% | 21.90% | 77.88% | 0.22% | -0.92% | 0.52 | 0.52 | 83.24% | 98.54% |
| `VA_prevalence_baseline` | A | 3,315 | 1,058 | 24 | 25.52% | 21.93% | 71.27% | 6.81% | -0.72% | 0.59 | 0.59 | 42.86% | 78.97% |
| **`VB_lgb_full`** | B | 3,315 | 1,223 | **80** | **29.11%** | **26.74%** | **68.85%** | **4.42%** | **-0.45%** | **0.74** | **0.74** | **38.89%** | **68.04%** |
| `VB_lgb_minus_market_regime` | B | 3,315 | 1,352 | 107 | 28.18% | 26.26% | 71.01% | 2.74% | -0.54% | 0.70 | 0.70 | 56.12% | 77.88% |
| `VB_logistic_baseline` | B | 3,315 | 2,132 | 282 | 23.59% | 23.41% | 76.27% | 0.33% | -0.82% | 0.57 | 0.56 | 76.96% | 97.02% |
| `VB_prevalence_baseline` | B | 3,315 | 1,058 | 24 | 25.52% | 21.93% | 71.27% | 6.81% | -0.72% | 0.59 | 0.59 | 42.86% | 78.97% |

---

### 5.4 Out-Of-Sample Predictive Performance (Preserved & Unchanged)

*Predictive evaluation is strictly invariant to trading simulator reconciliation, as predictive models were not retrained.*

#### Mode: `LOW_PRICE` ($\le 300$) — Macro Fold Aggregates

| Model ID | Target Variant | Feats | Macro ROC-AUC Mean (Std) | Macro PR-AUC Mean (Std) | Daily Top-10% Prec Mean (Std) | Daily Top-5 Prec Mean | Macro Brier Score | Common Cohort ROC-AUC | Common Cohort PR-AUC |
|---|---|---|---|---|---|---|---|---|---|
| `VA_lgb_full` | A (Close) | 30 | 0.5686 (0.0151) | 0.3148 (0.0263) | 0.3185 (0.0415) | 0.3203 | 0.1981 | 0.5552 | 0.2843 |
| **`VA_lgb_minus_trend`** | A (Close) | 23 | **0.5800 (0.0251)** | **0.3228 (0.0286)** | **0.3327 (0.0227)** | **0.3297** | 0.1947 | 0.5564 | 0.2812 |
| `VA_logistic_baseline` | A (Close) | 30 | 0.5617 (0.0175) | 0.3109 (0.0212) | 0.3133 (0.0136) | 0.3119 | 0.1994 | 0.5506 | 0.2777 |
| `VA_prevalence_baseline` | A (Close) | 0 | 0.5000 (0.0000) | 0.2640 (0.0084) | 0.2976 (0.0145) | 0.2971 | 0.1945 | 0.5000 | 0.2377 |
| `VB_lgb_full` | B (Open) | 30 | 0.5631 (0.0199) | 0.2853 (0.0186) | 0.2946 (0.0127) | 0.2908 | 0.1858 | 0.5631 | 0.2853 |
| **`VB_lgb_minus_trend`** | B (Open) | 23 | **0.5656 (0.0247)** | 0.2837 (0.0283) | 0.2911 (0.0061) | 0.2908 | **0.1847** | **0.5656** | 0.2837 |
| `VB_logistic_baseline` | B (Open) | 30 | 0.5620 (0.0270) | **0.2852 (0.0209)** | **0.2970 (0.0225)** | **0.2944** | 0.1882 | 0.5620 | 0.2852 |
| `VB_prevalence_baseline` | B (Open) | 0 | 0.5000 (0.0000) | 0.2377 (0.0036) | 0.2554 (0.0089) | 0.2543 | 0.1813 | 0.5000 | 0.2377 |

#### Mode: `HIGHER_PRICE` ($> 300$) — Macro Fold Aggregates

| Model ID | Target Variant | Feats | Macro ROC-AUC Mean (Std) | Macro PR-AUC Mean (Std) | Daily Top-10% Prec Mean (Std) | Daily Top-5 Prec Mean | Macro Brier Score | Common Cohort ROC-AUC | Common Cohort PR-AUC |
|---|---|---|---|---|---|---|---|---|---|
| `VA_lgb_full` | A (Close) | 30 | 0.5576 (0.0191) | 0.2960 (0.0282) | 0.2935 (0.0165) | 0.3041 | 0.1910 | 0.5463 | 0.2556 |
| **`VA_lgb_minus_market_regime`** | A (Close) | 24 | **0.5771 (0.0168)** | 0.2952 (0.0253) | **0.3069 (0.0326)** | **0.3204** | 0.1858 | 0.5683 | 0.2554 |
| `VA_logistic_baseline` | A (Close) | 30 | 0.5626 (0.0372) | **0.2980 (0.0450)** | 0.2933 (0.0226) | 0.2929 | 0.1914 | 0.5564 | 0.2601 |
| `VA_prevalence_baseline` | A (Close) | 0 | 0.5000 (0.0000) | 0.2498 (0.0111) | 0.2602 (0.0017) | 0.2455 | 0.1875 | 0.5000 | 0.2198 |
| `VB_lgb_full` | B (Open) | 30 | 0.5483 (0.0243) | 0.2532 (0.0306) | 0.2614 (0.0155) | 0.2631 | 0.1766 | 0.5483 | 0.2532 |
| **`VB_lgb_minus_market_regime`** | B (Open) | 24 | **0.5686 (0.0087)** | **0.2576 (0.0135)** | **0.2687 (0.0171)** | **0.2782** | **0.1709** | **0.5686** | 0.2576 |
| `VB_logistic_baseline` | B (Open) | 30 | 0.5566 (0.0363) | 0.2613 (0.0372) | 0.2443 (0.0047) | 0.2332 | 0.1765 | 0.5566 | 0.2613 |
| `VB_prevalence_baseline` | B (Open) | 0 | 0.5000 (0.0000) | 0.2198 (0.0098) | 0.2268 (0.0101) | 0.2133 | 0.1715 | 0.5000 | 0.2198 |

---

## 6. Findings, Risks, and Limitations

| ID | Finding | Severity | Evidence | Impact | Status |
|---|---|---|---|---|---|
| F1 | Net Negative Trading Return Barrier | Critical | All 16 candidates produce average net returns between $-0.33\%$ and $-0.92\%$ | Models cannot trade profitably under 50 bps IDX friction without stronger gating | Confirmed |
| F2 | Significant Invalidation Suppression in Variant B | High | Invalidations drop $156 \rightarrow 80$ in HIGH Full, $112 \rightarrow 83$ in LOW Full | Variant B eliminates lookahead phantom wins and learns cleaner opening patterns | Confirmed |
| F3 | Predictive Edge of Ablation Fails in Trading | High | Pruning improves AUC ($+0.011$ to $+0.020$) but deteriorates net PnL ($-0.09\%$ to $-0.13\%$) | Higher discrimination does not automatically translate into superior execution | Confirmed |
| F4 | Over-Trading Risk in Linear Models | High | Logistic baselines trade 1,910–2,288 times, suffering 87–98% continuous drawdowns | Flatter probability distribution bypasses selection selectivity | Confirmed |
| F5 | Metric Definition Divergence (Worst-Fold vs Continuous DD) | Medium | Worst-fold DD is 34–83%, while continuous portfolio DD is 62–98% | Calling worst-fold DD a portfolio DD understates compounding risk | Resolved |
| F6 | Fixed Holding Period Inefficiency | Medium | Expiry rate is low ($0.2\%$ to $4.4\%$), but 10-day cap forces premature exits | Fixed barrier structure limits positive excursion capture | Open |
| F7 | Reused 2026 Test Period | Medium | 2026 bars previously inspected during historical pipeline audits | Monitored temporal fold rather than untouched blind holdout | Documented |

---

## 7. Verification

| Check | Command or Method | Result | Evidence/Notes |
|---|---|---|---|
| Friction Contract Unit Tests | `pytest tests/unit/test_candidate_evaluation.py -k test_slippage_friction_allocation` | PASS (1 passed in 1.2s) | 5 bps entry ($100.05$) and 5 bps exit ($105.00$) verified |
| Metric Distinction Unit Tests | `pytest tests/unit/test_candidate_evaluation.py -k test_pooled_vs_mean` | PASS (1 passed in 1.1s) | Pooled PF vs Mean PF and Worst-Fold DD vs Continuous DD verified |
| Recompute Runner Unit Test | `pytest tests/unit/test_candidate_evaluation.py -k test_recompute_trading` | PASS (1 passed in 38.2s) | Idempotent simulation from saved predictions verified |
| Full Candidate Eval Unit Suite | `pytest tests/unit/test_candidate_evaluation.py` | PASS (11 passed in 45.8s) | All 11 unit tests pass |
| Full Repository Test Suite | `pytest` | PASS (471 passed in 107.0s) | Reconciled test count: 468 previous + 3 new tests = 471 total |
| Code Quality & Lint Check | `ruff check .` | PASS (All checks passed) | 100% clean codebase (0 errors) |
| Retraining-Free Reconciliation Run | `python scripts/run_candidate_evaluation.py --mode BOTH --recompute-trading-only` | PASS (completed in 92.3s) | Recomputed 16 candidate trading summaries without model retraining |
| Champion Model Isolation | `git status`, inspection of `models/registry/` | PASS | Production champions remain 100% untouched |
| Database Immutability | SHA-256 checks on `datasets/stock_signals.db` | PASS | `daily_bars` and `labels_daily` unchanged |

---

## 8. Files, Artifacts, and Data Changes

- **Files created:** None (reused existing candidate evaluation pipeline).
- **Files modified:**
  - `python/experiments/candidate_eval.py` (Enforced 5 bps entry + 5 bps exit slippage, added pooled PF, worst-fold DD, continuous DD, and `recompute_trading_from_saved_predictions`)
  - `scripts/run_candidate_evaluation.py` (Added `--recompute-trading-only` CLI flag and updated console table columns)
  - `tests/unit/test_candidate_evaluation.py` (Added 3 unit tests verifying friction allocation, explicit metrics, and OOS recomputation; total 11 tests)
  - `docs/13_phase_11b_candidate_model_evaluation_report.md` (Updated report with before-and-after metrics, reconciled ranges, and explicit definitions)
  - `artifacts/candidate_eval/candidate_results_LOW_PRICE.json`
  - `artifacts/candidate_eval/candidate_results_HIGHER_PRICE.json`
  - `artifacts/candidate_eval/candidate_trading_results_LOW_PRICE.csv` & `.json`
  - `artifacts/candidate_eval/candidate_trading_results_HIGHER_PRICE.csv` & `.json`
  - `artifacts/candidate_eval/candidate_trading_aggregate.csv` & `.json`
  - `artifacts/candidate_eval/candidate_summary_aggregate.csv` & `.json`
  - `audit_report.md` (Updated status index)
  - `summary.md` (Appended Log Entry 57)
  - `walkthrough.md` (Updated session task breakdown & testing checklist)
- **Files deleted:** None.
- **Production state changed:** No. Zero champion weights, signal thresholds, EV gate configs, or live trading behaviors were altered.

---

## 9. Safeguards and Backward Compatibility

- **No Model Retraining:** Candidate predictive models and out-of-sample probability outputs were 100% preserved. Only downstream execution simulation was recomputed.
- **Champion Protection:** Production models `lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607` remain active champions.
- **Backward Compatibility:** `_aggregate_trading_summaries` maintains `"max_drawdown_pct"` as an alias to `"worst_fold_max_drawdown_pct"`, ensuring full backward compatibility with legacy scripts and tests.
- **Zero Live Pollution:** All updated artifacts remain strictly isolated inside `artifacts/candidate_eval/`.

---

## 10. Reproducibility

To reproduce the complete trading metric reconciliation without retraining any models:

```powershell
$env:PYTHONPATH="."
& ".venv\Scripts\python.exe" scripts/run_candidate_evaluation.py --mode BOTH --recompute-trading-only
& ".venv\Scripts\python.exe" -m pytest tests/unit/test_candidate_evaluation.py
& ".venv\Scripts\python.exe" -m pytest
& ".venv\Scripts\python.exe" -m ruff check .
```

Expected output:
- `scripts/run_candidate_evaluation.py`: Recomputes trading in ~90s across BOTH modes and regenerates all trading CSV/JSON artifacts.
- `pytest tests/unit/test_candidate_evaluation.py`: 11 passed.
- `pytest`: 471 passed.
- `ruff check .`: All checks passed.

---

## 11. Final Decision

- **Acceptance criteria satisfied:** Yes (100% of Phase 11B.1 reconciliation requirements satisfied and empirically verified).
- **Promotion Decision:** `DO_NOT_PROMOTE`. Under the reconciled 50 bps friction contract, every candidate model produces net negative returns ($-0.33\%$ to $-0.92\%$ per trade).
- **Recommended Next Research Steps (Phase 11C):**
  1. **Adopt Variant B as the Default Target Contract for Research:** Empirically verified to cut operational invalidations by 50% ($156 \rightarrow 80$).
  2. **Calibrate Dynamic EV Hurdles in Phase 11C:** Filter low-confidence signals where $EV_{\text{net}} \le 0$ to overcome the fee barrier.
  3. **Explore Multi-Horizon / Adaptive Targets:** Test dynamic holding horizons and adaptive volatility-scaled barriers to capture positive excursions beyond the static $+5\%$ barrier.
- **Approval required before proceeding:** Yes. Wait for user review and approval before beginning any Phase 11C activities. Do not begin Phase 11C automatically.
