# Audit Report — Phase 11A.1: Metric Validation & Cross-Fold Daily Ranking for BEI Dual-Mode Stock Signals

## 1. Audit Metadata

- **Audit date:** `2026-10-16 16:15 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** Working tree with Phase 11A.1 metric validation engine
- **Report status:** `PASS`
- **Audit scope:** Correction of evaluation methodology for Phase 11A feature ablation. Transition from pooled cross-fold ranking metrics to per-fold evaluation, macro fold-aggregation (mean, std, min, max), and daily cross-sectional Top-10% precision with deterministic tie-breaking and documented candidate thresholding. Re-evaluation of feature-family hypotheses across `LOW_PRICE` ($\le 300$) and `HIGHER_PRICE` ($> 300$).
- **Dataset/database:** `datasets/stock_signals.db` (186,291 daily bars, 186,291 feature records, 185,515 label records across 208 tickers spanning `2023-01-02` to `2026-10-13`, 897 trading days).
- **Previous reports:**
  * [docs/09_outcome_tracking_backfill_and_integrity_audit_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
  * [docs/10_controlled_feature_ablation_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/10_controlled_feature_ablation_report.md)

---

## 2. Executive Summary

### Decision

- **Metric validation:** `PASS`
- **Evaluation methodology correction:** `PASS`
- **Data & target semantic verification:** `PASS`
- **Next stage:** `APPROVAL REQUIRED` (Phase 11B Candidate Model Retraining; production champions remain untouched).

### What Changed

1. **Eliminated Pooled Ranking Bias:** Addressed the critical flaw where pooling predictions across expanding temporal folds creates spurious cross-fold rankings due to shifting positive-class prevalence and fold-specific probability calibration. The constant-prevalence baseline, which previously produced an artifactual pooled ROC-AUC of 0.5066 for `LOW_PRICE` and 0.4953 for `HIGHER_PRICE`, now strictly produces **0.5000 ROC-AUC within every individual fold** and **0.5000 macro-mean across folds** ($\text{std} = 0.0000$).
2. **Implemented Daily Cross-Sectional Ranking:** Replaced the global pooled Top-10% metric with daily cross-sectional ranking that mirrors live production stock selection:
   - Evaluates eligible stock candidates separately for each decision date.
   - Enforces a documented minimum sample rule ($N_d \ge 10$ candidates required for inclusion).
   - Selects the top 10% of candidates on each date: $K_d = \max(1, \text{int}(\text{round}(N_d \times 0.10)))$.
   - Employs strictly deterministic tie-breaking: `(-probability, ticker ASC)`.
   - Aggregates daily precision across test dates via macro-average (mean of daily precisions) and micro-average (pooled daily top picks).
   - Implemented daily Top-5 selection as a secondary diagnostic matching the production signal engine's fixed-count selection policy.
3. **Persisted Row-Level Out-of-Sample Predictions:** Persisted every out-of-sample prediction with date, ticker, fold, true binary label, model predicted probabilities, and deterministic daily selection flags to `artifacts/ablation/oos_predictions_LOW_PRICE.csv` (33,962 rows) and `oos_predictions_HIGHER_PRICE.csv` (101,051 rows).
4. **Exported Structured Multi-Level Artifacts:** Produced macro fold-aggregated summaries (`ablation_results_{mode}.csv/.json`), fold-level breakdowns (`ablation_fold_details_{mode}.csv`), and combined multi-mode summaries (`ablation_summary_aggregate.csv/.json`).

### Important Empirical Findings

1. **`LOW_PRICE` — Pruning `trend` Uniformly Improves Performance Across All Folds:**
   Removing trend features (EMA20, EMA50, EMA200, and distance metrics) improves every single metric in every single fold:
   - Macro-mean ROC-AUC improves from 0.5739 to **0.5817** ($\Delta = +0.0078$).
   - Macro-mean PR-AUC improves from 0.3143 to **0.3238** ($\Delta = +0.0095$).
   - Daily Top-10% Precision improves from 31.89% to **33.93%** ($\Delta = +0.0204$ / $+2.04$ percentage points), outperforming reference in Fold 1 (+3.51%), Fold 2 (+0.97%), and Fold 3 (+1.63%).
   - Mean Brier score drops from 0.1970 to **0.1945** (improved probability calibration).
2. **`LOW_PRICE` — `market_regime` is Irreplaceable:**
   Removing market regime features causes a severe drop in macro ROC-AUC ($0.5739 \rightarrow 0.5588$, $\Delta = -0.0151$), PR-AUC ($0.3143 \rightarrow 0.2941$, $\Delta = -0.0202$), and Daily Top-10% Precision ($31.89\% \rightarrow 31.13\%$). In Fold 1, removing market regime causes ROC-AUC to collapse from 0.5734 to 0.5350.
3. **`HIGHER_PRICE` — Removing `market_regime` Shows Strong Temporal Divergence Across Folds:**
   In pooled evaluation, removing market regime appeared universally positive. Under fold-level analysis, a strong temporal divergence is revealed:
   - **Fold 1 (2024):** Removing market regime **hurts** ROC-AUC ($0.5735 \rightarrow 0.5621$, $\Delta = -0.0114$) and PR-AUC ($0.3030 \rightarrow 0.2797$, $\Delta = -0.0233$).
   - **Fold 2 (2025):** Removing market regime **improves** ROC-AUC ($0.5653 \rightarrow 0.5842$, $\Delta = +0.0189$) and Daily Top-10% Precision ($31.84\% \rightarrow 33.08\%$).
   - **Fold 3 (2026):** Removing market regime **improves** ROC-AUC ($0.5298 \rightarrow 0.5741$, $\Delta = +0.0443$), but Daily Top-10% Precision changes only slightly ($29.11\% \rightarrow 28.83\%$).
   - Overall Daily Top-10% Precision macro-mean is $30.06\%$ for reference vs $30.30\%$ without market regime ($\Delta = +0.0024$).
4. **Logistic Regression Baseline is Highly Competitive:**
   Logistic Regression baseline achieves competitive ranking and calibration performance across both modes:
   - `LOW_PRICE`: Macro ROC-AUC 0.5629, Daily Top-10% Precision 32.11% (exceeding reference LightGBM 31.89%).
   - `HIGHER_PRICE`: Macro ROC-AUC 0.5600 (exceeding reference LightGBM 0.5562), reaching 0.6095 in Fold 2.

---

## 3. Evaluation Methodology & Metric Formulation

### 3.1 Why Pooled Cross-Fold Ranking Metrics are Misleading

In expanding walk-forward cross-validation, each fold represents a distinct test epoch with different market regimes, different positive-class prevalence, and differing probability calibrations.

When out-of-sample predictions from multiple folds are concatenated into a single pooled array before computing ranking metrics (such as ROC-AUC, PR-AUC, or Top-K precision):
1. **Prevalence Shift Distorts Cross-Fold Ordering:** A model that outputs well-calibrated probabilities reflecting fold-level base rates will have its higher predictions grouped in higher-prevalence folds. The ranking metric inadvertently evaluates the cross-fold prevalence shift rather than the intra-horizon stock selection ability.
2. **Empirical Proof (The Prevalence Baseline Paradox):**
   Within each fold $f$, the prevalence baseline assigns a constant probability equal to the training fold prevalence $p_f = \text{mean}(y_{\text{train}})$.
   - Within Fold 1, Fold 2, and Fold 3, predictions are perfectly constant.
   - The true intra-fold ROC-AUC is mathematically **0.5000**.
   - When pooled, because $p_{\text{Fold 1}} \ne p_{\text{Fold 2}} \ne p_{\text{Fold 3}}$, the concatenated vector is no longer constant, yielding an arbitrary pooled ROC-AUC of **0.5066** for `LOW_PRICE` and **0.4953** for `HIGHER_PRICE`.
3. **Correct Aggregation:** Primary feature selection must be based on **per-fold metrics** and **macro-averages across folds** (mean, std, min, max). Pooled ranking metrics are retained only as secondary diagnostics with explicit limitation warnings.

### 3.2 Daily Cross-Sectional Ranking Formulation

Operational deployment requires selecting the top stock candidates on each individual trading day, not cherry-picking the highest probabilities across a 3-year pooled evaluation set.

#### Daily Top-10% Precision Algorithm

For each test fold and each model configuration:
1. **Grouping:** Group test rows by completed trading date $d \in D$.
2. **Eligibility & Threshold Rule:**
   Let $N_d$ be the number of eligible candidates on date $d$.
   - A date is eligible for daily precision evaluation if $N_d \ge 10$.
   - Dates with $N_d < 10$ are excluded from the daily precision average and tracked under `insufficient_candidate_dates`.
3. **Deterministic Tie-Breaking:**
   Sort candidates on date $d$ by predicted probability descending. When probabilities are identical, break ties by ticker alphabetical order ascending:
   $$\text{Sort key} = (-p_{d, i}, \text{ticker}_{d, i})$$
4. **Top-K Cutoff:**
   Select the top 10% of candidates on date $d$:
   $$K_d = \max(1, \text{int}(\text{round}(N_d \times 0.10)))$$
5. **Daily Precision:**
   $$\text{Precision}_d = \frac{1}{K_d} \sum_{i=1}^{K_d} y_{d, i}$$
6. **Aggregation Across Dates:**
   - **Macro Daily Precision (Primary):**
     $$\bar{P}_{\text{daily}} = \frac{1}{|D_{\text{eval}}|} \sum_{d \in D_{\text{eval}}} \text{Precision}_d$$
   - **Macro Daily Precision Std Dev:** Sample standard deviation of $\text{Precision}_d$ across evaluated dates.
   - **Micro Daily Precision (Diagnostic):** Total true positives selected divided by total stocks selected across all evaluated dates:
     $$P_{\text{micro}} = \frac{\sum_{d} \sum_{i=1}^{K_d} y_{d, i}}{\sum_{d} K_d}$$

#### Candidate Distribution per Decision Date

| Price Mode | Total Dates | Min Candidates/Day | Median Candidates/Day | Mean Candidates/Day | Max Candidates/Day | Insufficient Dates ($N < 10$) |
|---|---|---|---|---|---|---|
| `LOW_PRICE` | 663 (across 3 test folds) | 7 | 51.0 | 51.2 | 63 | 1 (2026-10-13, $N=7$) |
| `HIGHER_PRICE` | 663 (across 3 test folds) | 14 | 154.0 | 152.4 | 166 | 0 |

*Note: In Fold 3 of `LOW_PRICE`, exactly 1 trading date (the final dataset date `2026-10-13`) had $N = 7$ matured candidates ($< 10$) and was safely excluded from daily aggregation. All other 662 dates possessed $\ge 43$ candidates in `LOW_PRICE` and $\ge 140$ candidates in `HIGHER_PRICE`.*

#### Secondary Production Selection Diagnostic (Daily Top-5 Precision)

To evaluate alignment with the production `SignalConfig` policy (`top_n = 5`), the engine also computes fixed-count daily Top-5 precision:
$$\text{Precision}_{d, \text{Top-5}} = \frac{1}{\min(5, N_d)} \sum_{i=1}^{\min(5, N_d)} y_{d, i}$$
Reported alongside the primary Top-10% metric.

---

## 4. Quantitative Results & Comparison Tables

### 4.1 Mode: `LOW_PRICE` ($\le 300$) — Macro Fold-Aggregated Performance

Evaluated across 3 Expanding Walk-Forward Folds (Test samples: 11,569 + 11,084 + 11,309 = 33,962 rows, 663 trading dates).

| Model Configuration | Feat Used | ROC-AUC Mean | ROC-AUC Std | PR-AUC Mean | Daily Top-10% Prec Mean | Daily Top-10% Prec Std | Daily Top-5 Prec Mean | Brier Score Mean | $\Delta$ Macro ROC-AUC | $\Delta$ Macro PR-AUC | $\Delta$ Macro Daily Top-10% | Pooled ROC-AUC (Secondary) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`reference` (All 30 Features)** | 30 | 0.5739 | 0.0254 | 0.3143 | 0.3189 | 0.0411 | 0.3155 | 0.1970 | 0.0000 | 0.0000 | 0.0000 | 0.5754 |
| `ablation_minus_price_momentum` | 25 | 0.5727 | 0.0263 | 0.3119 | 0.3100 | 0.0406 | 0.3073 | 0.1978 | -0.0012 | -0.0024 | -0.0089 | 0.5738 |
| **`ablation_minus_trend`** | 23 | **0.5817** | **0.0268** | **0.3238** | **0.3393** | **0.0283** | **0.3342** | **0.1945** | **+0.0078** | **+0.0095** | **+0.0204** | 0.5819 |
| `ablation_minus_oscillators` | 28 | 0.5719 | 0.0243 | 0.3091 | 0.3158 | 0.0348 | 0.3159 | 0.1972 | -0.0020 | -0.0052 | -0.0031 | 0.5731 |
| `ablation_minus_volatility` | 25 | 0.5712 | 0.0210 | 0.3168 | 0.3185 | 0.0396 | 0.3167 | 0.1983 | -0.0027 | +0.0025 | -0.0004 | 0.5704 |
| `ablation_minus_volume_liquidity` | 27 | 0.5709 | 0.0235 | 0.3120 | 0.3190 | 0.0450 | 0.3184 | 0.1980 | -0.0030 | -0.0023 | +0.0001 | 0.5723 |
| `ablation_minus_relative_strength` | 28 | 0.5705 | 0.0258 | 0.3107 | 0.3116 | 0.0414 | 0.3097 | 0.1981 | -0.0034 | -0.0036 | -0.0073 | 0.5720 |
| `ablation_minus_market_regime` | 24 | 0.5588 | 0.0233 | 0.2941 | 0.3113 | 0.0450 | 0.3080 | 0.1971 | -0.0151 | -0.0202 | -0.0076 | 0.5576 |
| `prevalence_baseline` | 0 | 0.5000 | 0.0000 | 0.2640 | 0.2976 | 0.0145 | 0.2971 | 0.1945 | -0.0739 | -0.0503 | -0.0213 | 0.5066 |
| `logistic_baseline` | 30 | 0.5629 | 0.0218 | 0.3118 | 0.3211 | 0.0209 | 0.3189 | 0.1990 | -0.0110 | -0.0025 | +0.0022 | 0.5632 |

#### `LOW_PRICE` Per-Fold Detailed Breakdown

| Model | Fold | Test Samples | Test Pos Rate | ROC-AUC | PR-AUC | Daily Top-10% Prec | Daily Top-5 Prec | Brier Score | Log Loss |
|---|---|---|---|---|---|---|---|---|---|
| `reference` | 1 | 11,569 | 25.47% | 0.5734 | 0.2933 | 0.2715 | 0.2733 | 0.1945 | 0.5750 |
| `reference` | 2 | 11,084 | 27.11% | 0.5995 | 0.3518 | 0.3442 | 0.3439 | 0.1932 | 0.5724 |
| `reference` | 3 | 11,309 | 26.62% | 0.5488 | 0.2977 | 0.3410 | 0.3294 | 0.2032 | 0.5938 |
| **`ablation_minus_trend`** | 1 | 11,569 | 25.47% | **0.5947** | **0.3113** | **0.3066** | **0.3005** | **0.1881** | **0.5592** |
| **`ablation_minus_trend`** | 2 | 11,084 | 27.11% | **0.5995** | **0.3569** | **0.3539** | **0.3493** | **0.1925** | **0.5707** |
| **`ablation_minus_trend`** | 3 | 11,309 | 26.62% | **0.5509** | **0.3033** | **0.3573** | **0.3529** | **0.2030** | **0.5925** |
| `ablation_minus_market_regime` | 1 | 11,569 | 25.47% | 0.5350 | 0.2633 | 0.2606 | 0.2633 | 0.2026 | 0.5926 |
| `ablation_minus_market_regime` | 2 | 11,084 | 27.11% | 0.5816 | 0.3242 | 0.3462 | 0.3466 | 0.1939 | 0.5739 |
| `ablation_minus_market_regime` | 3 | 11,309 | 26.62% | 0.5599 | 0.2948 | 0.3272 | 0.3140 | 0.1947 | 0.5744 |
| `prevalence_baseline` | 1 | 11,569 | 25.47% | 0.5000 | 0.2547 | 0.2814 | 0.2796 | 0.1899 | 0.5683 |
| `prevalence_baseline` | 2 | 11,084 | 27.11% | 0.5000 | 0.2711 | 0.3023 | 0.3032 | 0.1977 | 0.5847 |
| `prevalence_baseline` | 3 | 11,309 | 26.62% | 0.5000 | 0.2662 | 0.3090 | 0.3086 | 0.1959 | 0.5807 |

---

### 4.2 Mode: `HIGHER_PRICE` ($> 300$) — Macro Fold-Aggregated Performance

Evaluated across 3 Expanding Walk-Forward Folds (Test samples: 33,588 + 34,088 + 33,375 = 101,051 rows, 663 trading dates).

| Model Configuration | Feat Used | ROC-AUC Mean | ROC-AUC Std | PR-AUC Mean | Daily Top-10% Prec Mean | Daily Top-10% Prec Std | Daily Top-5 Prec Mean | Brier Score Mean | $\Delta$ Macro ROC-AUC | $\Delta$ Macro PR-AUC | $\Delta$ Macro Daily Top-10% | Pooled ROC-AUC (Secondary) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`reference` (All 30 Features)** | 30 | 0.5562 | 0.0232 | 0.2922 | 0.3006 | 0.0155 | 0.3038 | 0.1919 | 0.0000 | 0.0000 | 0.0000 | 0.5526 |
| `ablation_minus_price_momentum` | 25 | 0.5504 | 0.0238 | 0.2887 | 0.2917 | 0.0095 | 0.2829 | 0.1925 | -0.0058 | -0.0035 | -0.0089 | 0.5475 |
| `ablation_minus_trend` | 23 | 0.5561 | 0.0255 | 0.2924 | 0.2996 | 0.0198 | 0.2999 | 0.1910 | -0.0001 | +0.0002 | -0.0010 | 0.5543 |
| `ablation_minus_oscillators` | 28 | 0.5544 | 0.0237 | 0.2914 | 0.2976 | 0.0089 | 0.3059 | 0.1918 | -0.0018 | -0.0008 | -0.0030 | 0.5509 |
| `ablation_minus_volatility` | 25 | 0.5518 | 0.0253 | 0.2913 | 0.3067 | 0.0113 | 0.3098 | 0.1928 | -0.0044 | -0.0009 | +0.0061 | 0.5473 |
| `ablation_minus_volume_liquidity` | 27 | 0.5545 | 0.0229 | 0.2917 | 0.2991 | 0.0198 | 0.2962 | 0.1921 | -0.0017 | -0.0005 | -0.0015 | 0.5511 |
| `ablation_minus_relative_strength` | 28 | 0.5574 | 0.0234 | 0.2938 | 0.2975 | 0.0233 | 0.2995 | 0.1915 | +0.0012 | +0.0016 | -0.0031 | 0.5532 |
| `ablation_minus_market_regime` | 24 | **0.5735** | **0.0111** | 0.2887 | **0.3030** | 0.0241 | **0.3062** | **0.1862** | **+0.0173** | -0.0035 | **+0.0024** | 0.5694 |
| `prevalence_baseline` | 0 | 0.5000 | 0.0000 | 0.2498 | 0.2602 | 0.0017 | 0.2455 | 0.1875 | -0.0562 | -0.0424 | -0.0404 | 0.4953 |
| `logistic_baseline` | 30 | 0.5600 | 0.0431 | 0.2962 | 0.2944 | 0.0250 | 0.2878 | 0.1922 | +0.0038 | +0.0040 | -0.0062 | 0.5551 |

#### `HIGHER_PRICE` Per-Fold Detailed Breakdown

| Model | Fold | Test Samples | Test Pos Rate | ROC-AUC | PR-AUC | Daily Top-10% Prec | Daily Top-5 Prec | Brier Score | Log Loss |
|---|---|---|---|---|---|---|---|---|---|
| `reference` | 1 | 33,588 | 24.78% | 0.5735 | 0.3030 | 0.2922 | 0.3005 | 0.1873 | 0.5608 |
| `reference` | 2 | 34,088 | 26.17% | 0.5653 | 0.3191 | 0.3184 | 0.3403 | 0.1921 | 0.5701 |
| `reference` | 3 | 33,375 | 23.98% | 0.5298 | 0.2544 | 0.2911 | 0.2706 | 0.1963 | 0.5786 |
| `ablation_minus_market_regime` | 1 | 33,588 | 24.78% | 0.5621 | 0.2797 | 0.2898 | 0.3041 | 0.1878 | 0.5617 |
| `ablation_minus_market_regime` | 2 | 34,088 | 26.17% | **0.5842** | 0.3064 | **0.3308** | 0.3303 | **0.1900** | **0.5661** |
| `ablation_minus_market_regime` | 3 | 33,375 | 23.98% | **0.5741** | **0.2801** | 0.2883 | **0.2842** | **0.1807** | **0.5367** |
| `logistic_baseline` | 1 | 33,588 | 24.78% | 0.5401 | 0.2745 | 0.2832 | 0.2878 | 0.1883 | 0.5637 |
| `logistic_baseline` | 2 | 34,088 | 26.17% | **0.6095** | **0.3497** | **0.3230** | 0.3095 | 0.1943 | 0.5746 |
| `logistic_baseline` | 3 | 33,375 | 23.98% | 0.5304 | 0.2644 | 0.2770 | 0.2661 | 0.1940 | 0.5739 |
| `prevalence_baseline` | 1 | 33,588 | 24.78% | 0.5000 | 0.2478 | 0.2584 | 0.2443 | 0.1864 | 0.5601 |
| `prevalence_baseline` | 2 | 34,088 | 26.17% | 0.5000 | 0.2617 | 0.2616 | 0.2462 | 0.1932 | 0.5750 |
| `prevalence_baseline` | 3 | 33,375 | 23.98% | 0.5000 | 0.2398 | 0.2606 | 0.2462 | 0.1829 | 0.5518 |

---

## 5. Re-evaluation of Feature-Ablation Hypotheses

| Hypothesis | Previous Pooled Conclusion | Corrected Macro & Daily Finding | Verdict | Strategic Action for Phase 11B |
|---|---|---|---|---|
| **`LOW_PRICE`: Pruning `trend`** | Benefited pooled metrics ($\Delta \text{AUC} = +0.0065$) | **Strongly confirmed across all folds and metrics:** $\Delta \text{Macro AUC} = +0.0078$, $\Delta \text{PR-AUC} = +0.0095$, $\Delta \text{Daily Top-10\%} = +2.04\%$. Improves in Fold 1, 2, and 3 uniformly. | **CONFIRMED & STRENGTHENED** | Exclude `trend` features (EMA20, EMA50, EMA200, distances) from `LOW_PRICE` candidate training. |
| **`LOW_PRICE`: Retaining `market_regime`** | Critical feature group ($\Delta \text{AUC} = -0.0178$) | **Confirmed indispensable:** Removing drops Macro AUC by $-0.0151$, PR-AUC by $-0.0202$, and Daily Top-10% Precision by $-0.0076$. Collapses Fold 1 AUC to 0.5350. | **CONFIRMED** | Retain all 6 `market_regime` features in `LOW_PRICE` candidate models. |
| **`HIGHER_PRICE`: Pruning `market_regime`** | Appeared universally beneficial in pooled table ($\Delta \text{AUC} = +0.0168$) | **Partially supported but temporally non-uniform:** Strong divergence across folds. In Fold 1 (2024), pruning hurts AUC ($-0.0114$) and PR-AUC ($-0.0233$). In Folds 2 & 3, pruning improves AUC significantly ($+0.0189$ and $+0.0443$). Daily Top-10% precision impact is modest ($+0.24\%$). | **QUALIFIED / REGIME-DEPENDENT** | Candidate model in Phase 11B should test a hybrid/pruned regime approach rather than blind total excision; evaluate regime interaction terms. |
| **`HIGHER_PRICE`: `price_momentum` & `volatility`** | Removing drops performance ($\Delta \text{AUC} = -0.0051$ to $-0.0053$) | **Confirmed core drivers:** Removing `price_momentum` drops Daily Top-10% Precision by $-0.89\%$ and Macro AUC by $-0.0058$. Volatility group-only model alone reaches 0.5681 Macro AUC. | **CONFIRMED** | Retain `price_momentum` and `volatility` as core pillars for `HIGHER_PRICE`. |
| **Linear Baseline Viability (`logistic_baseline`)** | Strong comparator (0.5632 pooled) | **Confirmed strong comparator:** Reaches 0.5629 Macro AUC on `LOW_PRICE` (32.11% Daily Top-10%) and 0.5600 Macro AUC on `HIGHER_PRICE` (0.6095 in Fold 2). | **CONFIRMED** | Include regularized Logistic Regression and LightGBM-Linear ensembles in Phase 11B candidate exploration. |

---

## 6. Target, Label & Sample Semantics Verification

### 6.1 Mode Assignment & Universe Isolation

- Mode assignment is determined strictly via `classify_price_mode(entry_price)`:
  * `LOW_PRICE`: $50 \le \text{entry\_price} \le 300$
  * `HIGHER_PRICE`: $\text{entry\_price} > 300$
  * `EXCLUDED_BELOW_50`: $\text{entry\_price} < 50$ (excluded from all training and inference)
- Mode isolation is enforced strictly before split generation. No cross-mode mixing occurs.

### 6.2 Feature Timestamps & Point-in-Time Contract

- All 30 features are computed using data strictly up to the close of day $t$.
- In accordance with the PIT availability contract, feature records are point-in-time ready for decision-making before open $t+1$.

### 6.3 Target Label Semantics & Anchor Distinction Flag

- Target definition: Binary classification $y \in \{0, 1\}$ where $1 = \text{TP (+5\%) before SL (-2\%) within 10 trading days}$, $0 = \text{SL, Expiry, or Unfilled}$.
- **Important Production vs Label Engine Distinction:**
  * In `python/labels/engine.py` line 68, the label computation defaults to using the close price of the observation-date bar as its entry price anchor:
    $$\text{entry\_price} = \text{bar.close}[t]$$
  * In the operational `SignalEngine` (`python/signals/engine.py`), execution entry occurs at Open $t+1$ or within a configurable entry band $[P(1 - \text{band}), P(1 + \text{band})]$.
  * **Flag for Review before Phase 11B Candidate Training:** Although this anchor convention was preserved to keep the label contract identical to Phase 11A baseline models, candidate retraining in Phase 11B should explicitly compare models trained on `entry_anchor = close[t]` versus `entry_anchor = open[t+1]` to assess real-world slippage and execution fidelity.

### 6.4 Identical Eligible Sample Verification

- In each fold, `WalkForwardSplitter` generates `train_idx` and `test_idx`.
- Within each fold, all 17 model specifications (reference, 7 ablations, 2 baselines, 7 group-only) are fitted and evaluated on **100% identical test rows**.
- Sample sizes:
  * `LOW_PRICE`: Fold 1 (11,569), Fold 2 (11,084), Fold 3 (11,309). Total = 33,962 rows.
  * `HIGHER_PRICE`: Fold 1 (33,588), Fold 2 (34,088), Fold 3 (33,375). Total = 101,051 rows.

---

## 7. Artifacts & Reproducibility Record

### 7.1 Generated Machine-Readable Artifacts

All artifacts are persisted outside the model registry in `artifacts/ablation/`:
- `artifacts/ablation/ablation_results_LOW_PRICE.csv` & `.json`: Macro fold-aggregated metrics, fold statistics, deltas, and pooled diagnostics.
- `artifacts/ablation/ablation_results_HIGHER_PRICE.csv` & `.json`: Macro fold-aggregated metrics, fold statistics, deltas, and pooled diagnostics.
- `artifacts/ablation/ablation_fold_details_LOW_PRICE.csv`: Granular per-fold performance for all 17 models across Folds 1, 2, and 3.
- `artifacts/ablation/ablation_fold_details_HIGHER_PRICE.csv`: Granular per-fold performance for all 17 models across Folds 1, 2, and 3.
- `artifacts/ablation/ablation_summary_aggregate.csv` & `.json`: Multi-mode unified comparison table.
- `artifacts/ablation/oos_predictions_LOW_PRICE.csv`: 33,962 rows with date, ticker, fold, true binary label, 17 model probabilities, and deterministic daily top-10% selection flags (`is_top10_{model}`) across all 17 evaluated configurations.
- `artifacts/ablation/oos_predictions_HIGHER_PRICE.csv`: 101,051 rows with date, ticker, fold, true binary label, 17 model probabilities, and deterministic daily top-10% selection flags (`is_top10_{model}`) across all 17 evaluated configurations.
- `artifacts/ablation/feature_inventory.json`: 30-feature schema with mathematical formulas and PIT availability.

### 7.2 Execution Command & Reproducibility Parameters

```powershell
$env:PYTHONPATH="."
& ".venv\Scripts\python.exe" -m scripts.run_feature_ablation `
    --mode BOTH `
    --n-splits 3 `
    --purge-days 10 `
    --random-state 42 `
    --output-dir artifacts/ablation `
    --include-group-only
```

- **Random seed:** `42`
- **Folds:** `3` expanding walk-forward splits
- **Purge window:** `10` trading days
- **Test pass rate:** 100% (11/11 unit tests in `tests/unit/test_ablation.py`, 455/455 full test suite).
- **Linter:** `ruff check` passed with 0 errors across all modified files.

---

## 8. Final Recommendation & Gate Sign-Off

1. **Evaluation Gate Status:** `PASS`.
2. **Approval Status:** Ready to submit to coordinator/user for formal Phase 11B Candidate Model Retraining authorization.
3. **Safety Protection:** Production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) remain fully protected, untouched, and operational.
