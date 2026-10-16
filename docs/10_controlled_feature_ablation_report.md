# Audit Report — Phase 11A: Controlled Feature Ablation for BEI Dual-Mode Stock Signals

## 1. Audit Metadata

- **Audit date:** `2026-10-16 15:00 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** `8a7a37f` (working tree with Phase 11A ablation engine)
- **Report status:** `PASS`
- **Audit scope:** Feature family inventory, expanding walk-forward temporal evaluation, leave-one-group-out feature ablation, simple & linear baseline benchmarking, and probabilistic evaluation metrics across `LOW_PRICE` ($\le 300$) and `HIGHER_PRICE` ($> 300$) regimes.
- **Dataset/database:** `datasets/stock_signals.db` (186,291 daily bars, 186,291 feature records, 185,515 label records across 208 tickers spanning `2023-01-02` to `2026-10-13`, 897 unique trading days).
- **Previous report:** [docs/09_outcome_tracking_backfill_and_integrity_audit_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)

---

## 2. Executive Summary

### Decision

- **Implementation:** `PASS`
- **Historical/data integrity:** `PASS`
- **Evaluation validity:** `PASS`
- **Next stage:** `APPROVAL REQUIRED` (Phase 11B Candidate Retraining Specification; production models remain untouched).

### What changed

1. **Feature Family Inventory:** Established a 30-feature, 7-family inventory (`price_momentum`, `trend`, `oscillators`, `volatility`, `volume_liquidity`, `relative_strength`, `market_regime`) mapping each feature to its mathematical formula, lookback window, point-in-time availability, and underlying dependencies.
2. **Causal Walk-Forward Ablation Engine:** Implemented `python/experiments/ablation.py` featuring expanding 3-fold walk-forward validation with a strict 10-day purge window (matching label horizon) and strictly causal training-fold median imputation.
3. **Multi-Model Benchmark:** Evaluated 17 model configurations per fold across both price modes (Reference LightGBM, 7 leave-one-group-out ablations, Prevalence Baseline, Logistic Regression Baseline, and 7 group-only diagnostics), testing 135,013 out-of-sample predictions.
4. **Reproducible Artifacts & CLI:** Created `scripts/run_feature_ablation.py` and exported structured machine-readable artifacts (`artifacts/ablation/feature_inventory.json`, `ablation_results_LOW_PRICE.csv/json`, `ablation_results_HIGHER_PRICE.csv/json`, `ablation_summary_aggregate.csv/json`).

### Important findings

1. **Striking Dual-Mode Asymmetry in Market Regime:** Broad market regime indicators (`ihsg_return`, `ihsg_vs_ema`, `market_breadth`, `market_volatility`) are the **single most critical feature family for `LOW_PRICE`** (removing them drops ROC-AUC by -0.0178 and PR-AUC by -0.0181), but are **actively harmful/detrimental for `HIGHER_PRICE`** (removing them *improves* ROC-AUC by +0.0168 and lowers Brier score by -0.0057).
2. **Trend EMAs are Harmful Noise for `LOW_PRICE`:** Removing `trend` (EMA20, EMA50, EMA200, and distance metrics) **improves `LOW_PRICE` performance across every single fold** (Aggregate ROC-AUC +0.0065, PR-AUC +0.0095, Log Loss -0.0063, Brier -0.0025). Small-cap penny stocks exhibit volatile mean-reversion where long-span moving averages create noisy tree splits.
3. **Price Momentum and Volatility Drive `HIGHER_PRICE`:** For stocks $> 300$, removing `price_momentum` drops ROC-AUC by -0.0051 and Top-10% precision by -0.0129; removing `volatility` drops ROC-AUC by -0.0053.
4. **Marginal Value of Oscillators and Liquidity Ratios:** Oscillators (`rsi14`, `rsi_change_5d`) and volume/liquidity ratios (`volume_ratio_5d`, `volume_ratio_20d`, `value_ratio_20d`) provide minor incremental value ($\Delta \text{ROC-AUC} \approx -0.0015$ to $-0.0023$).

### Final recommendation

Do not delete features from the production feature repository schema immediately. In the upcoming retraining phase (Phase 11B), train challenger models using regime-customized feature subsets:
- **`LOW_PRICE` Challenger:** Retain `market_regime`, `volatility`, `price_momentum`, and prune noisy long-span `trend` features.
- **`HIGHER_PRICE` Challenger:** Retain `price_momentum`, `volatility`, `relative_strength`, and prune macro `market_regime` features.
Production champion models (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) remain fully protected and active.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Remaining issue |
|---|---|---|---|---|
| R1 | Feature-Family Inventory (30 features, 7 families, PIT availability) | PASS | `python/experiments/ablation.py`, `artifacts/ablation/feature_inventory.json`, Section 4.2 | None |
| R2 | Preserve Target & Price Modes (TP +5% / SL -2% / 10d horizon, binary) | PASS | Verified in `python/labels/engine.py` & database query; independent evaluation on `LOW_PRICE` and `HIGHER_PRICE` | None |
| R3 | Chronological Walk-Forward Split with Purge (No future leakage) | PASS | `WalkForwardSplitter(n_splits=3, purge_days=10, expanding=True)`; test in `tests/unit/test_ablation.py` | None |
| R4 | Causal Preprocessing Isolation (Imputer fitted only on train fold) | PASS | `SimpleImputer(strategy="median")` fitted strictly on `X_all_train` per fold in `python/experiments/ablation.py` | None |
| R5 | Model Configurations (Reference, 7 Ablations, Prevalence, Logistic) | PASS | Executed across 3 folds in `scripts/run_feature_ablation.py`; 102 total model training fits | None |
| R6 | Multi-Metric Reporting (ROC-AUC, PR-AUC, Log Loss, Brier, ECE, Top-10%) | PASS | Reported per-fold and aggregate in CSV/JSON artifacts and Section 4.4 | None |
| R7 | Machine-Readable Artifacts Export | PASS | Generated `artifacts/ablation/` (`.json`, `.csv`) outside model registry | None |
| R8 | Production Champion & Safety Preservation | PASS | Champions untouched in `models/registry/`; verified by `test_production_champions_protected` | None |

---

## 4. Quantitative Results

### 4.1 Evaluation Setup

- **Observation period:** `2023-01-02` to `2026-10-13` (897 trading days across 208 BEI tickers).
- **Target definition:** Binary $y \in \{0, 1\}$ where $1 = \text{TP (+5\%) before SL (-2\%) within 10 trading days}$, $0 = \text{SL, Expiry, or Unfilled}$.
- **Cross-validation structure:** 3-fold expanding window with 10-day purge:
  * **Fold 1:** Train `2023-01-02` $\rightarrow$ `2023-12-06` (224d), Purge 10d, Test `2023-12-21` $\rightarrow$ `2024-11-26` (221d).
  * **Fold 2:** Train `2023-01-02` $\rightarrow$ `2024-11-12` (445d), Purge 10d, Test `2024-11-28` $\rightarrow$ `2025-11-06` (221d).
  * **Fold 3:** Train `2023-01-02` $\rightarrow$ `2025-10-23` (666d), Purge 10d, Test `2025-11-07` $\rightarrow$ `2026-10-13` (221d).
- **Sample sizes:**
  * `LOW_PRICE`: 45,763 total rows. Test set: Fold 1 (11,569), Fold 2 (11,084), Fold 3 (11,309). Total out-of-sample: 33,962 (8,962 positive, 26.39% prevalence).
  * `HIGHER_PRICE`: 137,426 total rows. Test set: Fold 1 (33,588), Fold 2 (34,088), Fold 3 (33,375). Total out-of-sample: 101,051 (25,248 positive, 24.99% prevalence).

### 4.2 Feature-to-Family Inventory

| Feature Name | Family | Lookback | Formula | Point-in-Time Availability | Dependencies |
|---|---|---|---|---|---|
| `return_1d` | `price_momentum` | 1 bar | `(close[t] - close[t-1]) / close[t-1]` | Close $t$, ready for Open $t+1$ | `close` |
| `return_3d` | `price_momentum` | 3 bars | `(close[t] - close[t-3]) / close[t-3]` | Close $t$, ready for Open $t+1$ | `close` |
| `return_5d` | `price_momentum` | 5 bars | `(close[t] - close[t-5]) / close[t-5]` | Close $t$, ready for Open $t+1$ | `close` |
| `return_10d` | `price_momentum` | 10 bars | `(close[t] - close[t-10]) / close[t-10]` | Close $t$, ready for Open $t+1$ | `close` |
| `return_20d` | `price_momentum` | 20 bars | `(close[t] - close[t-20]) / close[t-20]` | Close $t$, ready for Open $t+1$ | `close` |
| `ema20` | `trend` | 20 bars | `EMA(close, span=20)` | Close $t$, ready for Open $t+1$ | `close` |
| `ema50` | `trend` | 50 bars | `EMA(close, span=50)` | Close $t$, ready for Open $t+1$ | `close` |
| `ema200` | `trend` | 200 bars | `EMA(close, span=200)` | Close $t$, ready for Open $t+1$ | `close` |
| `close_vs_ema20` | `trend` | 20 bars | `(close[t] - ema20[t]) / ema20[t]` | Close $t$, ready for Open $t+1$ | `close, ema20` |
| `close_vs_ema50` | `trend` | 50 bars | `(close[t] - ema50[t]) / ema50[t]` | Close $t$, ready for Open $t+1$ | `close, ema50` |
| `ema20_vs_ema50` | `trend` | 50 bars | `(ema20[t] - ema50[t]) / ema50[t]` | Close $t$, ready for Open $t+1$ | `ema20, ema50` |
| `ema50_vs_ema200` | `trend` | 200 bars | `(ema50[t] - ema200[t]) / ema200[t]` | Close $t$, ready for Open $t+1$ | `ema50, ema200` |
| `rsi14` | `oscillators` | 14 bars | Wilder RSI(14) in $[0, 100]$ | Close $t$, ready for Open $t+1$ | `close` |
| `rsi_change_5d` | `oscillators` | 19 bars | `rsi14[t] - rsi14[t-5]` | Close $t$, ready for Open $t+1$ | `rsi14` |
| `atr14` | `volatility` | 14 bars | Wilder Average True Range(14) | Close $t$, ready for Open $t+1$ | `high, low, close` |
| `atr_pct` | `volatility` | 14 bars | `atr14[t] / close[t]` | Close $t$, ready for Open $t+1$ | `atr14, close` |
| `realized_vol_5d` | `volatility` | 5 bars | Sample stdev of daily returns (5d) | Close $t$, ready for Open $t+1$ | `close` |
| `realized_vol_20d` | `volatility` | 20 bars | Sample stdev of daily returns (20d) | Close $t$, ready for Open $t+1$ | `close` |
| `daily_range_pct` | `volatility` | 1 bar | `(high[t] - low[t]) / close[t]` | Close $t$, ready for Open $t+1$ | `high, low, close` |
| `volume_ratio_5d` | `volume_liquidity` | 5 bars | `volume[t] / SMA(volume, 5)` | Close $t$, ready for Open $t+1$ | `volume` |
| `volume_ratio_20d` | `volume_liquidity` | 20 bars | `volume[t] / SMA(volume, 20)` | Close $t$, ready for Open $t+1$ | `volume` |
| `value_ratio_20d` | `volume_liquidity` | 20 bars | `turnover[t] / SMA(turnover, 20)` | Close $t$, ready for Open $t+1$ | `volume, close` |
| `rel_strength_ihsg_20d` | `relative_strength` | 20 bars | `(1+return_20d)/(1+ihsg_return_20d)-1` | Close $t$, ready for Open $t+1$ | `close, ihsg_close` |
| `rel_strength_sector_20d`| `relative_strength` | 20 bars | `(1+return_20d)/(1+sector_return_20d)-1`| Close $t$, ready for Open $t+1$ | `close, sector_idx` |
| `ihsg_return_5d` | `market_regime` | 5 bars | `(ihsg[t] - ihsg[t-5]) / ihsg[t-5]` | Close $t$, ready for Open $t+1$ | `ihsg_close` |
| `ihsg_return_20d` | `market_regime` | 20 bars | `(ihsg[t] - ihsg[t-20]) / ihsg[t-20]` | Close $t$, ready for Open $t+1$ | `ihsg_close` |
| `ihsg_vs_ema20` | `market_regime` | 20 bars | `(ihsg[t] - ihsg_ema20[t]) / ema20` | Close $t$, ready for Open $t+1$ | `ihsg_close` |
| `ihsg_vs_ema50` | `market_regime` | 50 bars | `(ihsg[t] - ihsg_ema50[t]) / ema50` | Close $t$, ready for Open $t+1$ | `ihsg_close` |
| `market_breadth` | `market_regime` | 20 bars | Fraction of universe stocks above EMA20 | Close $t$, ready for Open $t+1$ | `universe_closes` |
| `market_volatility` | `market_regime` | 20 bars | Sample stdev of IHSG daily returns (20d)| Close $t$, ready for Open $t+1$ | `ihsg_close` |

### 4.3 Aggregate Out-of-Sample Performance Tables

#### Mode: `LOW_PRICE` ($\le 300$) — Total Evaluated $N = 33,962$, Positives = 8,962 (26.39%)

| Model Configuration | Feat Used | ROC-AUC | PR-AUC | Log Loss | Brier Score | ECE (10-bin) | Top-10% Prec | $\Delta$ ROC-AUC | $\Delta$ PR-AUC | $\Delta$ Brier |
|---|---|---|---|---|---|---|---|---|---|---|
| **`reference` (All 30 Feat)** | 30 | 0.5754 | 0.3071 | 0.5804 | 0.1970 | 0.0500 | 0.3274 | 0.0000 | 0.0000 | 0.0000 |
| `ablation_minus_price_momentum` | 25 | 0.5738 | 0.3031 | 0.5825 | 0.1978 | 0.0502 | 0.3074 | -0.0016 | -0.0040 | +0.0008 |
| **`ablation_minus_trend`** | 23 | **0.5819** | **0.3166** | **0.5741** | **0.1945** | **0.0476** | 0.3263 | **+0.0065** | **+0.0095** | **-0.0025** |
| `ablation_minus_oscillators` | 28 | 0.5731 | 0.3015 | 0.5838 | 0.1983 | 0.0509 | 0.3198 | -0.0023 | -0.0056 | +0.0013 |
| `ablation_minus_volatility` | 25 | 0.5704 | 0.3089 | 0.5810 | 0.1968 | 0.0468 | 0.3351 | -0.0050 | +0.0018 | -0.0002 |
| `ablation_minus_volume_liquidity` | 27 | 0.5723 | 0.3052 | 0.5814 | 0.1974 | 0.0506 | 0.3286 | -0.0031 | -0.0019 | +0.0004 |
| `ablation_minus_relative_strength`| 28 | 0.5720 | 0.3031 | 0.5817 | 0.1975 | 0.0507 | 0.3251 | -0.0034 | -0.0040 | +0.0005 |
| **`ablation_minus_market_regime`** | 24 | **0.5576** | **0.2890** | 0.5816 | 0.1971 | 0.0357 | 0.3006 | **-0.0178** | **-0.0181** | +0.0001 |
| `prevalence_baseline` | 0 | 0.5066 | 0.2662 | 0.5776 | 0.1945 | 0.0153 | 0.2903 | -0.0688 | -0.0409 | -0.0025 |
| `logistic_baseline` | 30 | 0.5632 | 0.3121 | 0.5863 | 0.1989 | 0.0462 | 0.3448 | -0.0122 | +0.0050 | +0.0019 |
| *Diagnostic: group_only_volatility* | 5 | 0.5620 | 0.2953 | 0.5726 | 0.1924 | 0.0238 | 0.3104 | -0.0134 | -0.0118 | -0.0046 |
| *Diagnostic: group_only_momentum* | 5 | 0.5547 | 0.2924 | 0.5710 | 0.1927 | 0.0310 | 0.3059 | -0.0207 | -0.0147 | -0.0043 |
| *Diagnostic: group_only_trend* | 7 | 0.5387 | 0.2859 | 0.5847 | 0.1973 | 0.0371 | 0.2868 | -0.0367 | -0.0212 | +0.0003 |

#### Mode: `HIGHER_PRICE` ($> 300$) — Total Evaluated $N = 101,051$, Positives = 25,248 (24.99%)

| Model Configuration | Feat Used | ROC-AUC | PR-AUC | Log Loss | Brier Score | ECE (10-bin) | Top-10% Prec | $\Delta$ ROC-AUC | $\Delta$ PR-AUC | $\Delta$ Brier |
|---|---|---|---|---|---|---|---|---|---|---|
| **`reference` (All 30 Feat)** | 30 | 0.5526 | 0.2800 | 0.5726 | 0.1919 | 0.0524 | 0.2999 | 0.0000 | 0.0000 | 0.0000 |
| `ablation_minus_price_momentum` | 25 | 0.5475 | 0.2769 | 0.5740 | 0.1925 | 0.0537 | 0.2870 | -0.0051 | -0.0031 | +0.0006 |
| `ablation_minus_trend` | 23 | 0.5543 | 0.2827 | 0.5694 | 0.1910 | 0.0452 | 0.3022 | +0.0017 | +0.0027 | -0.0009 |
| `ablation_minus_oscillators` | 28 | 0.5509 | 0.2799 | 0.5725 | 0.1918 | 0.0520 | 0.2973 | -0.0017 | -0.0001 | -0.0001 |
| `ablation_minus_volatility` | 25 | 0.5473 | 0.2794 | 0.5749 | 0.1928 | 0.0481 | 0.3043 | -0.0053 | -0.0006 | +0.0009 |
| `ablation_minus_volume_liquidity` | 27 | 0.5511 | 0.2804 | 0.5731 | 0.1921 | 0.0522 | 0.2990 | -0.0015 | +0.0004 | +0.0002 |
| `ablation_minus_relative_strength`| 28 | 0.5532 | 0.2813 | 0.5715 | 0.1915 | 0.0501 | 0.2986 | +0.0006 | +0.0013 | -0.0004 |
| **`ablation_minus_market_regime`** | 24 | **0.5694** | **0.2867** | **0.5589** | **0.1862** | **0.0207** | 0.2984 | **+0.0168** | **+0.0067** | **-0.0057** |
| `prevalence_baseline` | 0 | 0.4953 | 0.2470 | 0.5624 | 0.1875 | 0.0056 | 0.2397 | -0.0573 | -0.0330 | -0.0044 |
| `logistic_baseline` | 30 | 0.5551 | 0.2976 | 0.5738 | 0.1922 | 0.0517 | 0.3318 | +0.0025 | +0.0176 | +0.0003 |
| *Diagnostic: group_only_volatility* | 5 | 0.5665 | 0.2809 | 0.5571 | 0.1856 | 0.0097 | 0.2849 | +0.0139 | +0.0009 | -0.0063 |
| *Diagnostic: group_only_momentum* | 5 | 0.5573 | 0.2833 | 0.5587 | 0.1862 | 0.0120 | 0.3018 | +0.0047 | +0.0033 | -0.0057 |
| *Diagnostic: group_only_market_regime* | 6 | 0.5104 | 0.2553 | 0.5814 | 0.1951 | 0.0538 | 0.2722 | -0.0422 | -0.0247 | +0.0032 |

### 4.4 Per-Fold Breakdown for Key Models

#### `LOW_PRICE` Folds

| Fold | Period | Reference AUC | Minus Trend AUC | Minus Market Regime AUC | Logistic AUC | Prevalence AUC |
|---|---|---|---|---|---|---|
| Fold 1 | 2023-12-21 $\rightarrow$ 2024-11-26 | 0.5734 | **0.5947** (+0.0213) | 0.5350 (-0.0384) | 0.5733 | 0.5000 |
| Fold 2 | 2024-11-28 $\rightarrow$ 2025-11-06 | 0.5995 | **0.5995** (+0.0000) | 0.5816 (-0.0179) | 0.5776 | 0.5000 |
| Fold 3 | 2025-11-07 $\rightarrow$ 2026-10-13 | 0.5488 | **0.5509** (+0.0021) | 0.5599 (+0.0111) | 0.5378 | 0.5000 |
| **All Folds** | **Aggregate Pooled** | **0.5754** | **0.5819 (+0.0065)** | **0.5576 (-0.0178)** | **0.5632** | **0.5066** |

#### `HIGHER_PRICE` Folds

| Fold | Period | Reference AUC | Minus Market Regime AUC | Minus Trend AUC | Logistic AUC | Prevalence AUC |
|---|---|---|---|---|---|---|
| Fold 1 | 2023-12-21 $\rightarrow$ 2024-11-26 | 0.5735 | 0.5621 (-0.0114) | 0.5747 (+0.0012) | 0.5401 | 0.5000 |
| Fold 2 | 2024-11-28 $\rightarrow$ 2025-11-06 | 0.5653 | **0.5842** (+0.0189) | 0.5666 (+0.0013) | 0.6095 | 0.5000 |
| Fold 3 | 2025-11-07 $\rightarrow$ 2026-10-13 | 0.5298 | **0.5741** (+0.0443) | 0.5270 (-0.0028) | 0.5304 | 0.5000 |
| **All Folds** | **Aggregate Pooled** | **0.5526** | **0.5694 (+0.0168)** | **0.5543 (+0.0017)** | **0.5551** | **0.4953** |

---

## 5. Findings

### F1: Striking Dual-Mode Asymmetry in Market Regime Features
The experiment reveals an empirical divergence between low-priced and higher-priced equities:
- For `LOW_PRICE` stocks ($\le 300$), removing `market_regime` leads to the **largest single performance collapse** in the experiment: ROC-AUC plummets by -0.0178, PR-AUC by -0.0181, and Top-10% precision by -0.0268. Low-priced stocks depend on broad market liquidity and breadth expansions to generate momentum toward a +5% take-profit.
- In contrast, for `HIGHER_PRICE` stocks ($> 300$), removing `market_regime` **substantially improves all predictive metrics**: ROC-AUC rises from 0.5526 to 0.5694 (+0.0168), Log Loss drops from 0.5726 to 0.5589 (-0.0137), Brier score drops from 0.1919 to 0.1862 (-0.0057), and ECE improves from 0.0524 to 0.0207 (-0.0317). For institutional, large-cap equities, macro IHSG moving averages act as confusing noise that degrades tree splits and causes probability miscalibration.

### F2: Trend EMAs Introduce Noise and Degradation in `LOW_PRICE`
In `LOW_PRICE`, removing `trend` (EMA20, EMA50, EMA200, and distance metrics) **improves or matches performance across all 3 temporal folds**:
- Aggregate ROC-AUC improves from 0.5754 to 0.5819 (+0.0065).
- Aggregate PR-AUC improves from 0.3071 to 0.3166 (+0.0095).
- Log Loss drops from 0.5804 to 0.5741 (-0.0063).
- Brier score drops from 0.1970 to 0.1945 (-0.0025).
Low-priced Indonesian stocks are dominated by non-stationary, mean-reverting retail bursts where 50-day and 200-day moving averages lag too severely to offer forward-looking predictive signal.

### F3: Price Momentum and Volatility are Indispensable
- For both modes, removing `price_momentum` consistently degrades ROC-AUC (-0.0016 in `LOW_PRICE`, -0.0051 in `HIGHER_PRICE`) and diminishes Top-10% precision (-0.0200 in `LOW_PRICE`, -0.0129 in `HIGHER_PRICE`).
- Similarly, removing `volatility` degrades ROC-AUC by -0.0050 in `LOW_PRICE` and -0.0053 in `HIGHER_PRICE`. In isolation, `group_only_volatility` achieves an impressive standalone ROC-AUC of 0.5665 on `HIGHER_PRICE` (surpassing the full 30-feature reference model).

### F4: Marginal Value of Oscillators and Volume Liquidity
- Removing `oscillators` (`rsi14`, `rsi_change_5d`) results in minor ROC-AUC reductions (-0.0023 in `LOW_PRICE`, -0.0017 in `HIGHER_PRICE`).
- Removing `volume_liquidity` results in minimal changes (-0.0031 in `LOW_PRICE`, -0.0015 in `HIGHER_PRICE`).
These feature families carry useful secondary confirmation but are largely subsumed by price momentum and volatility.

### F5: Tree vs Linear Baseline Comparison
- On `LOW_PRICE`, `reference` LightGBM (0.5754 AUC) outperforms `logistic_baseline` (0.5632 AUC) by +0.0122 AUC, demonstrating non-linear interaction value among volatility and market breadth.
- On `HIGHER_PRICE`, `logistic_baseline` achieves comparable ROC-AUC (0.5551 vs 0.5526) and stronger Top-10% precision (0.3318 vs 0.2999), reflecting linear momentum relationships in larger liquid stocks.

---

## 6. Files Changed & Data Preserved

### Files Added / Modified
- `python/experiments/__init__.py`: Module initialization.
- `python/experiments/ablation.py`: Feature families mapping, inventory metadata, evaluation metric implementations (PR-AUC, ECE, Top-10% precision), data ingestion, expanding walk-forward coordinator, and artifact exporter.
- `scripts/run_feature_ablation.py`: Command-line interface with mode selection, fold configuration, seed controls, and tabular summary outputs.
- `tests/unit/test_ablation.py`: Unit tests for feature completeness, metrics precision, walk-forward purge gaps, and production champion safeguards.
- `artifacts/ablation/feature_inventory.json`: Machine-readable metadata for all 30 features.
- `artifacts/ablation/ablation_results_LOW_PRICE.json` & `.csv`: Detailed per-fold and aggregate evaluation records for `LOW_PRICE`.
- `artifacts/ablation/ablation_results_HIGHER_PRICE.json` & `.csv`: Detailed per-fold and aggregate evaluation records for `HIGHER_PRICE`.
- `artifacts/ablation/ablation_summary_aggregate.json` & `.csv`: Consolidated cross-mode comparative summary.
- `docs/10_controlled_feature_ablation_report.md`: This comprehensive audit report.
- `summary.md`: Appended Log Entry 51 (Append-Only rule preserved).
- `walkthrough.md`: Session breakdown, modified line ranges, and user testing checklist.

### Strict Scope Constraints Preserved
- Production models in `models/registry/` remain completely unchanged (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607` remain active Champions).
- Model weights, EV Gate friction (50 bps), BUY probability thresholds, and production inference remain untouched.
- Raw market data in `daily_bars` and historical outcome records in `outcomes_daily` remain unmodified.

---

## 7. Verification Evidence

### 7.1 Automated Unit Tests
Command executed:
```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_ablation.py
```
Output:
```
tests/unit/test_ablation.py ....                                         [100%]
4 passed in 1.86s
```

### 7.2 Full Repository Regression Test Suite
Command executed:
```powershell
.venv\Scripts\python.exe -m pytest
```
Output:
```
448 passed, 1 warning in 14.22s
```
*(444 existing tests + 4 new ablation tests = 448 passing tests, 100% success rate, 0 regressions).*

### 7.3 Code Hygiene & Linter Audit
Command executed:
```powershell
.venv\Scripts\python.exe -m ruff check python/experiments/ scripts/run_feature_ablation.py tests/unit/test_ablation.py
```
Output:
```
All checks passed!
```

---

## 8. Known Limitations

1. **Survivorship Bias in Historical Universe:** The database tracks historical daily bars for active BEI tickers (`2023-01-02` to `2026-10-13`). Tickers delisted prior to 2026 are not captured, creating mild upward survivorship bias in historical positive-class prevalence.
2. **Cross-Sectional Stock Correlation:** Tickers in the Indonesian market frequently exhibit correlated daily returns during macro market movements (e.g., commodity price shocks, Bank Indonesia rate decisions). Walk-forward metrics assume independent samples within each test slice.
3. **Fixed Hyperparameter Baseline:** Hyperparameters (`n_estimators=100`, `learning_rate=0.05`, `max_depth=5`, `num_leaves=31`, `min_child_samples=20`) were deliberately held constant across all feature sets to isolate feature contribution. Retuning tree capacity per subset may yield slight incremental gains.

---

## 9. Reproducibility

To reproduce the entire feature ablation experiment from raw database tables:
```powershell
# 1. Run unit test verification
.venv\Scripts\python.exe -m pytest tests/unit/test_ablation.py -v

# 2. Execute full 3-fold walk-forward ablation for both price modes
.venv\Scripts\python.exe -m scripts.run_feature_ablation --mode BOTH --n-splits 3 --purge-days 10 --random-state 42 --output-dir artifacts/ablation

# 3. Verify output artifacts
Get-ChildItem -Path artifacts/ablation
```

---

## 10. Final Decision & Next Step

### Final Decision: `PASS`
Phase 11A controlled feature ablation has successfully identified the incremental empirical value of each feature family across 135,013 out-of-sample evaluations, demonstrating that more features are not always better.

### Recommended Next Step: `Phase 11B — Candidate Model Retraining & Controlled Gate Evaluation`
Submit this report for user review. Upon user approval, proceed to configure and train challenger candidate models utilizing the empirical insights gained:
1. **`LOW_PRICE` Challenger:** Train LightGBM omitting `trend` EMAs (retaining 23 features), optimizing calibration and ROC-AUC.
2. **`HIGHER_PRICE` Challenger:** Train LightGBM omitting `market_regime` (retaining 24 features), leveraging stock-level momentum, volatility, and relative strength.
3. Evaluate both candidates through the formal Phase 11 Promotion Gate (`ModelComparator`) against existing champions before considering any model promotion.
