# Training & Model Quality Audit Report: BEI Dual-Mode Stock Signals

> **Audit Date:** 2026-10-15  
> **Status:** COMPLETED  
> **Target Models:** `LOW_PRICE` & `HIGHER_PRICE` Champion Classifiers  
> **Target Database:** `datasets/stock_signals.db`  
> **Decision Verdict:** **RETRAIN REQUIRED**

---

## 1. Audit Champion Models

Audit performed on saved artifacts in `models/registry/` and database `datasets/stock_signals.db`. No model artifacts or champion status modified during audit.

| Metric / Dimension | `LOW_PRICE` Champion | `HIGHER_PRICE` Champion |
| :--- | :--- | :--- |
| **Model Version** | `lightgbm_classification_20261014_093522` | `lightgbm_classification_20261014_093607` |
| **Training Timestamp** | `2026-10-14 02:35:22 UTC` | `2026-10-14 02:36:07 UTC` |
| **Algorithm** | LightGBM Classifier (`CalibratedClassifierCV`, sigmoid) | LightGBM Classifier (`CalibratedClassifierCV`, sigmoid) |
| **Price Regime Filter** | `entry_price <= IDR 300` | `entry_price > IDR 300` |
| **Total Observations** | 45,763 | 137,426 |
| **Train Samples (70%)** | 31,794 (`2023-01-02` to `2025-08-14`) | 94,821 (`2023-01-02` to `2025-08-14`) |
| **Purge Window 1** | 10 trading days (`2025-08-15` to `2025-08-29`) | 10 trading days (`2025-08-15` to `2025-08-29`) |
| **Validation Samples (15%)** | 5,576 (`2025-09-01` to `2026-03-04`) | 20,049 (`2025-09-01` to `2026-03-04`) |
| **Purge Window 2** | 10 trading days (`2026-03-05` to `2026-03-25`) | 10 trading days (`2026-03-05` to `2026-03-25`) |
| **Test Samples (15%)** | 7,410 (`2026-03-26` to `2026-10-13`) | 19,439 (`2026-03-26` to `2026-10-13`) |
| **Unique Tickers** | 87 | 182 |
| **Features Count** | 30 numerical features | 30 numerical features |
| **Target Definition** | Binary `1` if TP (+5%) hit before SL (-2%) within 10d; else `0` | Binary `1` if TP (+5%) hit before SL (-2%) within 10d; else `0` |
| **Positive Class Count** | 11,809 (25.80%) | 33,973 (24.72%) |
| **Negative Class Count** | 33,954 (74.20%) | 103,453 (75.28%) |
| **Class Index in Output** | Index `1` via `predict_proba()[:, 1]` | Index `1` via `predict_proba()[:, 1]` |
| **Mode Assignment Timing** | `entry_bar.close` on day $t$ (historical decision time, no lookahead) | `entry_bar.close` on day $t$ (historical decision time, no lookahead) |

---

## 2. Historical Coverage & Dataset Quality

1. **Volume & Date Span**:
   - Total daily bars in database: **186,436** across **208 tickers** from `2023-01-02` to `2026-10-14` (~3.75 years).
   - Median bars per ticker: **898**. Min bars: 717 (`BREN`, IPO Oct 2023). Max bars: 927.
   - Zero invalid OHLC bars ($P \le 0$ or High < Low). Zero negative volume bars.
   - Zero-volume bars: **3,160 (1.69%)** caused by trading suspensions or holiday illiquidity.
2. **Defects in Raw Ingestion**:
   - **Duplicate Bars**: **145 duplicate (ticker, date) records** found in `daily_bars` for `ASII`, `BBCA`, `BBRI`, `BMRI`, `TLKM` (Sept 2026). Caused by early mock ingestion (`provider='unknown'`) coexisting with `yfinance` ingestion due to composite key `(ticker, date, interval, provider)`. Handled by deduplication in `DatasetBuilder`, but raw table dirty.
   - **Survivorship Bias**: `configs/universe/seed_universe.csv` created in Oct 2026 with currently active liquid stocks. Stocks delisted or bankrupt between 2023 and 2026 excluded. Moderate survivorship bias present.

---

## 3. Labels & Training Methodology

1. **Target Formulation**:
   - Total labels in database: **185,515**.
   - **TP (+5%) hit first**: 46,537 (25.09%) $\rightarrow$ `binary_target = 1`. Average realized return: **+5.26%**, avg hold: 3.2 days.
   - **SL (-2%) hit first**: 119,329 (64.32%) $\rightarrow$ `binary_target = 0`. Average realized return: **-2.22%**, avg hold: 2.5 days.
   - **Expiry (10 days without TP or SL)**: 19,649 (10.59%) $\rightarrow$ `binary_target = 0`. Average realized return: **+0.69%**, avg hold: 10.0 days.
   - **Same-Candle Ambiguity**: **3,800 bars (2.05%)** touched both +5% High and -2% Low on same daily candle. Resolved under `conservative` policy as SL (loss).
2. **Methodological Defects**:
   - **Validation Set Bypassed**: `scripts/train_model.py` partitioned chronological `val_ds` (5,576 and 20,049 rows), but `model.fit(train_ds.X, y_train)` never passed validation data for early stopping or calibration. `val_ds` completely unutilized.
   - **Causality Leak in Calibration**: `LightGBMClassifierBaseline` wrapped LightGBM in `CalibratedClassifierCV(estimator=base_lgbm, method="sigmoid", cv=3)`. Standard K-Fold CV splits time series non-chronologically. Fold 1 calibrated using models trained on Folds 2 & 3 (future data).

---

## 4. Out-of-Sample Model Quality

Models evaluated on untouched chronological test set (`2026-03-26` to `2026-10-13`, 7,410 `LOW_PRICE` rows and 19,439 `HIGHER_PRICE` rows).

### A. Probabilistic & Classification Metrics

| Mode | Dataset Split | Sample Size | Positive Rate | Brier Score | Log Loss | ROC-AUC | Accuracy | Calibration Error |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`LOW_PRICE`** | In-Sample Train | 31,794 | 25.30% | 0.1741 | 0.5248 | 0.7580 | 74.72% | 0.0688 |
| | Validation Set | 5,576 | 29.04% | 0.2024 | 0.5911 | 0.5612 | 70.96% | 0.0234 |
| | **Out-of-Sample Test** | **7,410** | **25.95%** | **0.1910** | **0.5674** | **0.5539** | **74.05%** | **0.0334** |
| | *Prevalence Baseline* | *7,410* | *25.95%* | *0.1922* | *0.5727* | *0.5000* | *74.05%* | *0.0065* |
| **`HIGHER_PRICE`**| In-Sample Train | 94,821 | 24.94% | 0.1795 | 0.5413 | 0.7052 | 75.06% | 0.0275 |
| | Validation Set | 20,049 | 24.64% | 0.1832 | 0.5516 | 0.5836 | 75.36% | 0.0158 |
| | **Out-of-Sample Test** | **19,439** | **24.85%** | **0.1884** | **0.5643** | **0.5135** | **75.15%** | **0.0337** |
| | *Prevalence Baseline* | *19,439* | *24.85%* | ***0.1867*** | ***0.5607*** | *0.5000* | *75.15%* | *0.0010* |

#### Key Findings from Metrics:
1. **HIGHER_PRICE Model Has Zero Predictive Power**:
   - Out-of-sample ROC-AUC is **0.5135** (indistinguishable from 0.50 random coin toss).
   - Both Brier Score (0.1884) and Log Loss (0.5643) are **worse than naive constant baseline** (0.1867 and 0.5607).
2. **74–75% Accuracy is an Artifact of Class Imbalance**:
   - Base negative class prevalence is ~75%.
   - At threshold 0.50, model predicts positive class **zero times** ($N=0$).
   - Accuracy equals 75% purely by predicting constant zero.
3. **Probability Ceiling**:
   - Maximum predicted probability across entire test set is **~42%**. Model never outputs $> 50\%$.

### B. Out-of-Sample Walk-Forward Backtest Results

Simulated via `BacktestEngine` over test period (`2026-03-26` to `2026-10-14`) with real IDX friction (Buy fee 0.15%, Sell fee 0.25%, Slippage 10 bps, max 5 positions, risk 2% per trade):

| Backtest Metric | `LOW_PRICE` (thresh=0.25) | `HIGHER_PRICE` (thresh=0.25) | Breakeven Hurdle Required |
| :--- | :--- | :--- | :--- |
| **Total Trades** | 348 | 336 | — |
| **Win Rate** | **30.17%** | **20.54%** | **$\ge 35.71\%$** |
| **Profit Factor** | **0.76** | **0.44** | **$> 1.00$** |
| **Total Net Return** | **-26.05%** | **-52.10%** | **$> 0.00\%$** |
| **Max Drawdown** | **30.50%** | **52.10%** | **$< 20.00\%$** |
| **Expectancy / Trade** | **-0.42%** | **-1.10%** | **$> +0.30\%$** |
| **Stop Loss Rate** | 66.67% | 78.57% | — |
| **Take Profit Rate** | 29.02% | 18.45% | — |
| **Avg Win / Avg Loss** | +4.41% / -2.51% | +4.25% / -2.48% | — |

---

## 5. Probability Semantics & Decision Logic

1. **Why Probabilities Cluster Around 25–32%**:
   - Training target is binary: $P(\text{TP hit before SL within 10d})$.
   - Market base rate for this event across 185k historical bars is **25.09%**.
   - A calibrated classifier maps predictions to empirical event frequency, naturally centering outputs near ~25–30%.
2. **Why BUY Status Was Issued with 25–32% Probability**:
   - In `SignalConfig`, default `min_probability` was 0.55.
   - Because calibrated probabilities never reach 0.50, original engine generated zero signals.
   - In Session Entry 35, `min_probability` was lowered to `0.25`.
   - Any stock with $P \ge 25\%$ entered candidate ranking, Top-N selected and assigned `status="BUY"`.
3. **Why Expected Return is `N/A`**:
   - `SignalEngine` checks: `self.model_registry.has_champion(task="regression", mode=mode)`.
   - No regression champion was trained or registered for dual mode. Variable left as `None`, formatted as `N/A`.
4. **Mathematical Defect in Current Decision Logic**:
   - Breakeven win rate for +5% TP and -2% SL after 0.50% round-trip friction is **35.71%**:
     $$\text{Win Rate}_{\text{BE}} = \frac{2\% + 0.50\%}{5\% + 2\%} = 35.71\%$$
   - Issuing `BUY` at $P(\text{TP}) = 26\%$ guarantees **negative mathematical expectancy** (-0.75% per trade).
   - System lacked Expected Value (EV) hurdle check before issuing `BUY`.

---

## 6. Defect Inventory

| # | Component | Defect Description | Severity |
| :--- | :--- | :--- | :--- |
| **D1** | `python/models/baseline.py` | `CalibratedClassifierCV(cv=3)` uses standard K-Fold CV, leaking future fold data into past fold calibration. | **HIGH** |
| **D2** | `scripts/train_model.py` | Chronological `val_ds` split created but never passed to model fitting, calibration, or early stopping. | **MEDIUM** |
| **D3** | `models/registry/` (HIGHER_PRICE) | Out-of-sample ROC-AUC is 0.5135. Brier score worse than naive baseline. Model has zero predictive edge. | **CRITICAL** |
| **D4** | `python/signals/engine.py` | Threshold lowered to 0.25 without EV check. Issues BUY recommendations on mathematically negative expectancy bets. | **CRITICAL** |
| **D5** | `python/signals/engine.py` | No trained regression model registered. Expected return displays `N/A` instead of failing closed. | **HIGH** |
| **D6** | `datasets/stock_signals.db` | 145 duplicate rows in `daily_bars` from legacy mock ingestion. | **LOW** |

---

## 7. Final Recommendation

# **RETRAIN REQUIRED**

**Justification**:
1. `HIGHER_PRICE` champion has zero statistical edge (ROC-AUC 0.5135, Brier score worse than baseline, backtest return -52.1%).
2. `LOW_PRICE` champion loses -26.0% with profit factor 0.76.
3. Calibration methodology leaked future data across standard K-folds.
4. Current signal engine emits BUY signals with negative expectancy because threshold was lowered to 0.25 without EV validation.

---

## Next Implementation Steps (Priority Order)

1. **Step 1 (Data Hygiene)**:
   - Purge 145 legacy `provider='unknown'` duplicate bars from `daily_bars`.
   - Re-index and vacuum SQLite database.
2. **Step 2 (Causal Calibration & Split Overhaul)**:
   - Replace standard K-Fold CV in `python/models/baseline.py` with causal walk-forward calibration (`cv="prefit"` using untouched `val_ds`, or `TimeSeriesSplit`).
   - Use `val_ds` strictly for LightGBM early stopping and probability calibration.
3. **Step 3 (Dual-Task Model Training: Classification + Regression)**:
   - Train `LOW_PRICE` and `HIGHER_PRICE` classification models with causal calibration.
   - Train companion regression models (`lightgbm_regression` or `ridge_regression`) predicting continuous expected return.
   - Register both classifiers and regressors in `ModelRegistry`.
4. **Step 4 (Decision Engine Mathematical Gate)**:
   - In `SignalEngine`: Require positive expected value net of transaction costs before issuing `BUY`:
     $$\text{EV} = P(\text{TP}) \times \text{TP}_{\text{net}} + P(\text{SL}) \times \text{SL}_{\text{net}} + P(\text{Expiry}) \times \text{Expiry}_{\text{net}} > 0$$
   - Fail closed (no signal) if Expected Value $\le 0$ or Expected Return is unavailable.
5. **Step 5 (Walk-Forward Backtest Verification)**:
   - Run walk-forward simulation on test period. Verify Profit Factor $> 1.15$ and positive net return before promoting models to champion.
