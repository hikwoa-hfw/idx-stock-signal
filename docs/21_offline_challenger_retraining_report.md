# Agent Task Report: Offline Challenger Retraining & Controlled Evaluation

## 1. Metadata

- **Task ID:** `OFFLINE-CHALLENGER-RETRAINING-20261021`
- **Task title:** Offline Challenger Retraining — Fresh Historical Data & Controlled Evaluation
- **Date:** 2026-10-21 13:30 WIB
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** `ede8154a34e69a4954495558b90e70c4449155ba`
- **Task status:** `PASS_WITH_FINDINGS (DO_NOT_PROMOTE)`
- **Related reports:**
  - [docs/10_controlled_feature_ablation_report.md](10_controlled_feature_ablation_report.md)
  - [docs/11_feature_ablation_metric_validation_report.md](11_feature_ablation_metric_validation_report.md)
  - [docs/13_phase_11b_candidate_model_evaluation_report.md](13_phase_11b_candidate_model_evaluation_report.md)
  - [docs/14_phase_11c_multi_horizon_return_evaluation_report.md](14_phase_11c_multi_horizon_return_evaluation_report.md)
  - [docs/18_phase_11f_research_scoring_and_observation_readiness_report.md](18_phase_11f_research_scoring_and_observation_readiness_report.md)
  - [docs/20_phase_11f_final_readiness_report.md](20_phase_11f_final_readiness_report.md)

---

## 2. Executive Summary

### Decision

`DO_NOT_PROMOTE`

Offline retraining and walk-forward controlled evaluation of candidate classifiers across fully matured historical market data confirm that **no retrained candidate classifier crosses the economic profitability threshold under the mandatory 50 bps round-trip transaction friction contract**. Every newly fitted candidate configuration produces negative net returns ($-0.35\%$ to $-0.68\%$ per trade) and pooled profit factors below 1.0 ($0.63$ to $0.79$).

Furthermore, dataset inspection demonstrates that while the fully matured historical dataset expanded by **+36.60% valid rows** (+46,343 rows, 13.5 additional calendar months) relative to the original production champion training cutoff (`2025-08-14`), it contains **0 genuinely incremental fully-matured training rows** relative to the Phase 11F research models (`2026-09-25` cutoff). Decision dates occurring after `2026-09-25` lack the requisite 15 forward sessions in the existing market bars (`2026-10-16` latest bar) and cannot reach maturity without severe right-censoring survivorship bias.

Consequently, pursuant to repository invariants and model governance rules:
1. **Production champions remain strictly immutable and active** (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`).
2. **Phase 11F frozen paper-trading systems and states remain strictly untouched**.
3. **All six newly fitted models are serialized exclusively as research artifacts** in `artifacts/offline_challengers/run_20261021_retraining/`.

### Completed

1. **Dataset Contract and Cutoff Verification:** Inspected SQLite tables (`daily_bars`, `features_daily`, `labels_daily`) via `scripts/inspect_dataset_splits.py` and proved that the latest observable bar date is `2026-10-16`, establishing `2026-09-25` as the exact latest decision date whose next-session entry ($t+1$) and complete 15-trading-day outcome are fully observable without survivorship truncation.
2. **Controlled Walk-Forward Splitting:** Enforced 3 expanding chronological walk-forward splits with a strict **15-trading-day purge/embargo window** between training and evaluation folds, completely eliminating forward label lookahead.
3. **Predeclared Candidate Matrix:** Evaluated five model configurations per mode:
   - Candidate A: Full-feature LightGBM Classifier (30 features).
   - Candidate B: Feature-Ablation LightGBM Classifier (minus `trend` for `LOW_PRICE`, minus `market_regime` for `HIGHER_PRICE`).
   - Candidate C: Regularized Logistic Regression Baseline ($C=1.0$, leakage-free pipeline).
   - Reference Baseline 1: Constant Training-Prevalence Classifier.
   - Reference Baseline 2: Existing Production Champion Model (evaluated on identical decision rows).
4. **Primary Classification Evaluation:** Evaluated ROC-AUC, Average Precision (PR-AUC), Brier score, Log loss, Expected Calibration Error (ECE, 10 bins), Daily cross-sectional Top-10% and Top-5% precision ($N_d \ge 10$, deterministic tie-breaking), and Top-5 fixed count precision.
5. **Discrete-Event Trading Simulation:** Modeled portfolio execution under exact production conditions: 50 bps round-trip friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip), 100-share lot sizes, maximum 5 positions (20% equity cap), fail-closed gap invalidations, and 15-day expiry.
6. **Artifact Persistence & Hash Verification:** Fit final research models on all eligible historical data up to `2026-09-25` and persisted six `.joblib` binaries, full `metadata.json`, fold-level predictions CSVs, and machine-readable metrics in `artifacts/offline_challengers/run_20261021_retraining/`.
7. **Test Suite & Linter Cleanliness:** Added 6 unit tests in `tests/unit/test_challenger_retraining.py` (597 total repository unit/integration tests passed 100%, ruff check clean 0 errors).

### Important Findings

1. **Zero New-Data Increment Beyond Phase 11F:**
   - The latest market bar in the repository is `2026-10-16`. For a 15-trading-day horizon starting at Open $t+1$, the final decision date with complete 15 forward bars is `2026-09-25`.
   - Decisions between `2026-09-28` and `2026-10-13` (531 rows in LOW_PRICE, 1,308 rows in HIGHER_PRICE) have only 1 to 14 forward bars and cannot reach expiry. Truncating or including only premature barrier hits would inject survivorship bias.
   - Retraining relative to Phase 11F does not possess substantial new-data support (+0.0% fully matured samples).
2. **Ablation Hypotheses Yield Mixed Predictive Value:**
   - In `LOW_PRICE`: Candidate B (minus `trend`) achieved marginal AUC improvement (+0.0028: 0.5643 vs 0.5615 for Full LGBM), but suffered lower Daily Top-10% Precision (30.40% vs 31.03%), lower average net return ($-0.478\%$ vs $-0.351\%$), and higher continuous drawdown ($73.51\%$ vs $60.54\%$).
   - In `HIGHER_PRICE`: Candidate B (minus `market_regime`) demonstrated notable predictive stabilization: ROC-AUC rose to 0.5488 (std 0.0054 vs 0.0233 for Full LGBM), ECE fell from 0.0582 to 0.0271, and Daily Top-10% Precision rose from 25.67% to 26.95%. However, in unconditioned simulated trading, Full LGBM still lost less ($-0.432\%$ vs $-0.675\%$).
3. **Structural Transaction Friction Deficit Persists Across All Retrained Models:**
   - Break-even win rate under 50 bps friction is $\approx 32.0\%$. Across all walk-forward folds, retrained candidate win rates peaked at $29.39\%$ (LOW_PRICE Full LGBM) and $29.09\%$ (HIGHER_PRICE Full LGBM).
   - In unconditioned top-5 trade selection, every retrained model loses capital systematically over time (continuous drawdowns between 59.88% and 77.69%).
4. **Production Champion Context & Target Mismatch:**
   - Production champions achieved positive net return in simulated trading (+0.205% in LOW_PRICE, +0.183% in HIGHER_PRICE) primarily due to outsized performance in Fold 1 (2023–2024 bull market).
   - However, champion performance deteriorated in Fold 3 (2025–2026 bear regime), suffering negative net return ($-0.425\%$ in LOW_PRICE, $-0.706\%$ in HIGHER_PRICE). Furthermore, champions were trained on Variant A H=10, meaning their probability outputs represent Close-anchor 10-day targets, not Variant B H=15 MOO execution.

### Next Recommended Action

Conclude offline retraining with status `PASS_WITH_FINDINGS (DO_NOT_PROMOTE)`. Do not modify production champions or paper-trading systems. Maintain all models as research artifacts. Await forward prospective data ingestion past `2026-10-16` before any subsequent model retraining is conducted.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Notes |
|---|---|---|---|---|
| R1 | Dataset & Cutoff Contract Audit | PASS | `scripts/inspect_dataset_splits.py` | Latest bar: `2026-10-16`; latest fully observable decision: `2026-09-25`. |
| R2 | Variant B Research Target Preservation | PASS | `python/experiments/challenger_retraining.py` | MOO entry $t+1$, TP +5%, SL -2%, H=15 expiry, gap invalidations. |
| R3 | Controlled 3-Fold Expanding Walk-Forward | PASS | `ChallengerRetrainingRunner.run_walk_forward_evaluation` | 15-day purge window enforced across all folds; no lookahead. |
| R4 | Predeclared Candidate Model Matrix | PASS | `ChallengerRetrainingRunner.get_candidate_specs` | Full LGBM, Ablation LGBM, Logistic Baseline, Prevalence, Champion. |
| R5 | Primary Classification Evaluation | PASS | `metrics/classification_macro_summaries.csv` | ROC-AUC, PR-AUC, Brier, Log Loss, ECE, Daily Top-10% & Top-5% Prec. |
| R6 | Consistent Discrete-Event Economic Simulation | PASS | `metrics/trading_macro_summaries.csv` | 50 bps friction, 100-share lots, 20% cap, pooled PF, continuous max DD. |
| R7 | Research Artifact Persistence & Hashing | PASS | `artifacts/offline_challengers/run_20261021_retraining/` | 6 `.joblib` binaries, SHA-256 hashes, metadata.json, OOS CSVs. |
| R8 | Strict Isolation from Champions & Phase 11F | PASS | Verification inspection | `models/registry/` and `artifacts/phase_11f/` 100% untouched. |
| R9 | Repository Test Suite Cleanliness | PASS | `pytest` (597 passed), `ruff check` (0 errors) | 6 unit tests added; 100% pass rate. |

---

## 4. Implementation Summary

| Component/File | Change | Reason |
|---|---|---|
| `scripts/inspect_dataset_splits.py` | Built data maturity cutoff and row count audit tool verifying bar limits, forward sessions, and champion vs challenger splits. | Pre-training contract audit and verifiable data maturity verification. |
| `python/experiments/challenger_retraining.py` | Implemented `ChallengerRetrainingRunner`, walk-forward candidate evaluator, discrete-event simulated trader, and artifact serializer. | Core engine for offline challenger retraining and controlled evaluation. |
| `scripts/run_offline_challenger_retraining.py` | Built CLI execution wrapper with structured console tables and summary metrics export. | Reproducible CLI execution tool for offline research. |
| `tests/unit/test_challenger_retraining.py` | Created 6 dedicated unit tests covering candidate specs, cutoff enforcement across modes, dataset inspection, purge gaps, SHA-256 hashing, and champion immutability. | Enforces mathematical and operational correctness of retraining pipeline. |
| `artifacts/offline_challengers/run_20261021_retraining/` | Saved 6 model binaries (`.joblib`), `metadata.json`, 2 OOS predictions CSVs, and 4 metrics CSVs. | Delivers durable, machine-readable audit artifacts. |
| `audit_report.md` | Updated audit index with offline challenger evaluation status and links. | Repository documentation compliance. |
| `summary.md` | Appended Log Entry 67 preserving historical records. | Repository documentation compliance. |
| `walkthrough.md` | Rewritten with task breakdown, line changes, and Testing Checklist. | Repository documentation compliance. |

---

## 5. Results and Evidence

### 5.1 Dataset Eligibility and Incremental Training Samples

| Metric | Production Champion Dataset (2025-08-14 Train / 2026-03-04 Val) | Phase 11F Research Dataset (2026-09-25 Cutoff) | New Fully-Matured Retraining Dataset (2026-09-25 Cutoff) | Incremental vs Champion | Incremental vs Phase 11F |
|---|---|---|---|---|---|
| **Latest Market Bar** | `2026-03-04` | `2026-10-16` | `2026-10-16` | +7.4 months | 0 days |
| **Latest Matured Decision** | `2025-08-14` (Train) / `2026-02-18` (Val) | `2026-09-25` | `2026-09-25` | +13.5 months (Train) | 0 days |
| **LOW_PRICE Valid Rows** | 31,794 (Train) / 37,848 (Total)* | 41,848 | 41,848 | +10,054 (+31.62%) | +0 (+0.0%) |
| **HIGHER_PRICE Valid Rows** | 94,821 (Train) / 116,442 (Total) | 131,110 | 131,110 | +36,289 (+38.27%) | +0 (+0.0%) |
| **Total Valid Rows** | 126,615 (Train) / 154,290 (Total) | 172,958 | 172,958 | **+46,343 (+36.60%)** | **+0 (+0.0%)** |
| **Decision Dates > 2026-09-25** | N/A | Excluded (< 15 forward bars) | Excluded (< 15 forward bars) | N/A | 0 usable rows |

*\*Note on Penny Stocks & Missing Bars:* In the champion training set (`<= 2025-08-14`), 1,452 raw rows have `entry_price < 50` IDR and are categorized as `EXCLUDED_BELOW_50` under BEI market microstructure rules, leaving 31,794 valid `LOW_PRICE` rows (total 128,067 raw rows). In the new dataset (`<= 2026-09-25`), `LOW_PRICE` has 0 incomplete rows (41,848 valid, 3,384 invalidated). In `HIGHER_PRICE`, exactly 2 decision rows (ticker `MPMX` on `2026-09-24` and `2026-09-25`) have incomplete outcomes due to absent market bars on `2026-10-15` and `2026-10-16` (14 and 13 forward bars), and are strictly excluded from the 131,110 valid sample count by the `vb_status_15 == "VALID"` training filter.

*Finding on Data Finality:* Retraining incorporates substantial historical data not seen by the production champions (+36.60% valid rows spanning Sep 2025 to Sep 2026). However, compared to the Phase 11F research model cutoff (`2026-09-25`), **0 genuinely incremental fully-matured training rows exist** because no new market bars beyond `2026-10-16` have been ingested.

---

### 5.2 Walk-Forward Temporal Boundaries

Expanding chronological walk-forward cross-validation using 3 splits and a strict 15-trading-day purge window:

| Fold | Training Range (Dates & Days) | Training Rows (LOW / HIGH) | Purge Window (Dates & Days) | Test Range (Dates & Days) | Test Rows (LOW / HIGH) |
|---|---|---|---|---|---|
| **Fold 1** | `2023-01-02` to `2023-11-29` (219 days) | 10,980 / 34,076 | `2023-11-30` to `2023-12-20` (15 days) | `2023-12-21` to `2024-11-20` (217 days) | 10,651 valid / 31,941 valid |
| **Fold 2** | `2023-01-02` to `2024-10-30` (436 days) | 22,455 / 67,008 | `2024-10-31` to `2024-11-20` (15 days) | `2024-11-21` to `2025-10-27` (217 days) | 9,964 valid / 32,219 valid |
| **Fold 3** | `2023-01-02` to `2025-10-06` (653 days) | 33,428 / 100,362 | `2025-10-07` to `2025-10-27` (15 days) | `2025-10-28` to `2026-09-25` (217 days) | 10,192 valid / 31,836 valid |

*Exploratory Nature:* All dates between `2023-01-02` and `2026-09-25` were previously examined in Phase 11A–11F research and must not be characterized as untouched blind holdout data.

---

### 5.3 Classification Predictive Performance

#### LOW_PRICE Universe ($\le 300$ IDR)

| Model Configuration | Feats | ROC-AUC (Mean $\pm$ Std) | PR-AUC (Mean $\pm$ Std) | Brier Score | Log Loss | ECE (10 bins) | Daily Top-10% Prec | Daily Top-5% Prec |
|---|---|---|---|---|---|---|---|---|
| **Candidate A: Full LightGBM** | 30 | 0.5615 $\pm$ 0.0094 | **0.3025 $\pm$ 0.0156** | 0.1924 | 0.5733 | 0.0616 | **31.03%** $\pm$ 3.00% | **32.31%** $\pm$ 2.90% |
| **Candidate B: Ablation (minus trend)** | 23 | **0.5643 $\pm$ 0.0205** | 0.3000 $\pm$ 0.0259 | 0.1914 | 0.5720 | **0.0565** | 30.40% $\pm$ 2.64% | 31.75% $\pm$ 4.95% |
| **Candidate C: Logistic Baseline** | 30 | 0.5613 $\pm$ 0.0202 | 0.2979 $\pm$ 0.0185 | 0.1960 | 0.5811 | 0.0616 | 30.54% $\pm$ 3.19% | 32.33% $\pm$ 2.24% |
| **Reference: Prevalence Baseline** | 0 | 0.5000 $\pm$ 0.0000 | 0.2512 $\pm$ 0.0011 | 0.1882 | 0.5639 | 0.0077 | 26.33% $\pm$ 1.61% | 27.08% $\pm$ 1.70% |
| **Reference: Production Champion** | 30 | 0.6527 $\pm$ 0.1188 | 0.4202 $\pm$ 0.1360 | 0.1816 | 0.5466 | 0.0665 | 43.41% $\pm$ 12.30% | 49.05% $\pm$ 12.84% |

#### HIGHER_PRICE Universe ($> 300$ IDR)

| Model Configuration | Feats | ROC-AUC (Mean $\pm$ Std) | PR-AUC (Mean $\pm$ Std) | Brier Score | Log Loss | ECE (10 bins) | Daily Top-10% Prec | Daily Top-5% Prec |
|---|---|---|---|---|---|---|---|---|
| **Candidate A: Full LightGBM** | 30 | 0.5337 $\pm$ 0.0233 | **0.2635 $\pm$ 0.0305** | 0.1867 | 0.5617 | 0.0582 | 25.67% $\pm$ 1.28% | 25.59% $\pm$ 1.94% |
| **Candidate B: Ablation (minus market_regime)** | 24 | **0.5488 $\pm$ 0.0054** | 0.2623 $\pm$ 0.0087 | **0.1817** | **0.5500** | **0.0271** | **26.95%** $\pm$ 1.06% | **26.54%** $\pm$ 0.93% |
| **Candidate C: Logistic Baseline** | 30 | 0.5512 $\pm$ 0.0352 | 0.2792 $\pm$ 0.0335 | 0.1874 | 0.5633 | 0.0657 | 24.69% $\pm$ 1.66% | 23.20% $\pm$ 1.24% |
| **Reference: Prevalence Baseline** | 0 | 0.5000 $\pm$ 0.0000 | 0.2375 $\pm$ 0.0110 | 0.1812 | 0.5483 | 0.0102 | 24.32% $\pm$ 1.89% | 24.34% $\pm$ 3.67% |
| **Reference: Production Champion** | 30 | 0.6226 $\pm$ 0.0994 | 0.3559 $\pm$ 0.1169 | 0.1779 | 0.5394 | 0.0376 | 35.74% $\pm$ 11.55% | 38.52% $\pm$ 15.78% |

---

### 5.4 Discrete-Event Economic Evaluation (Simulated Trading Under 50 bps Friction)

Simulation parameters: 100,000,000 IDR initial capital per fold, 5 positions max (20% equity cap), 100-share lots, 50 bps round-trip transaction friction, 15-day maximum holding period.

#### LOW_PRICE Universe

| Model Configuration | Completed Trades | Win Rate | TP / SL / Expiry Counts | Avg Net Return | Pooled Profit Factor | Worst Fold Max DD | Continuous Portfolio Max DD |
|---|---|---|---|---|---|---|---|
| **Candidate A: Full LightGBM** | 1,242 | **29.39%** | 355 / 857 / 30 | **-0.351%** | **0.79** | **41.07%** | **60.54%** |
| **Candidate B: Ablation (minus trend)** | 1,270 | 28.19% | 349 / 893 / 28 | -0.478% | 0.71 | 44.80% | 73.51% |
| **Candidate C: Logistic Baseline** | 1,652 | 29.06% | 476 / 1165 / 11 | -0.422% | 0.75 | 49.60% | 77.69% |
| **Reference: Prevalence Baseline** | 1,665 | 22.52% | 373 / 1288 / 4 | -0.852% | 0.54 | 62.76% | 94.30% |
| **Reference: Production Champion** | 1,414 | 37.34% | 525 / 873 / 16 | +0.205% | 1.20 | 38.54% | 42.69% |

#### HIGHER_PRICE Universe

| Model Configuration | Completed Trades | Win Rate | TP / SL / Expiry Counts | Avg Net Return | Pooled Profit Factor | Worst Fold Max DD | Continuous Portfolio Max DD |
|---|---|---|---|---|---|---|---|
| **Candidate A: Full LightGBM** | 959 | **29.09%** | 266 / 666 / 27 | **-0.432%** | **0.74** | **33.84%** | **59.88%** |
| **Candidate B: Ablation (minus market_regime)** | 1,007 | 25.72% | 244 / 735 / 28 | -0.675% | 0.63 | 43.81% | 74.90% |
| **Candidate C: Logistic Baseline** | 1,644 | 23.24% | 377 / 1253 / 14 | -0.852% | 0.55 | 64.85% | 93.79% |
| **Reference: Prevalence Baseline** | 984 | 25.10% | 230 / 726 / 28 | -0.717% | 0.59 | 43.04% | 77.98% |
| **Reference: Production Champion** | 1,448 | 37.84% | 544 / 897 / 7 | +0.183% | 1.33 | 58.48% | 58.48% |

---

### 5.5 Research Challenger Model Artifacts

Six candidate models were fit on all eligible, fully matured historical data up to `2026-09-25`:
- `LOW_PRICE`: 41,848 valid samples (10,339 positives, prevalence 24.71%).
- `HIGHER_PRICE`: 131,110 valid samples (31,400 positives, prevalence 23.95%).

Persisted artifacts in `artifacts/offline_challengers/run_20261021_retraining/`:

| Universe | Model ID | Artifact Path | SHA-256 Hash | Features Used |
|---|---|---|---|---|
| `LOW_PRICE` | `lgb_full` | `low_price/low_price_lgb_full.joblib` | `9bac146545ad1ddc7fa1874e540f55d05064303602d8c74f2c3e2232af835a85` | 30 |
| `LOW_PRICE` | `lgb_minus_trend` | `low_price/low_price_lgb_minus_trend.joblib` | `21ecbdeb9b5034de657ef413988a44d531ce5080dda87de9771b45f75e92ecc9` | 23 |
| `LOW_PRICE` | `logistic_baseline` | `low_price/low_price_logistic_baseline.joblib` | `0dfad387a41da9cea80cd75e9609acd1d9bbe906f50ce3739f32899cd4e091f1` | 30 |
| `HIGHER_PRICE` | `lgb_full` | `higher_price/higher_price_lgb_full.joblib` | `2c42f9639fe488d1af92dbe5c9ca8a5fd974b0182701735f236dd332747337a4` | 30 |
| `HIGHER_PRICE` | `lgb_minus_market_regime` | `higher_price/higher_price_lgb_minus_market_regime.joblib` | `d1befb3783a38f32e83ec7f34b02357da0b40266d1064f608cc0f0cd2c293311` | 24 |
| `HIGHER_PRICE` | `logistic_baseline` | `higher_price/higher_price_logistic_baseline.joblib` | `f79ef47fe7413374d1d572645d6c68c36bf33db288e7564e6c5a149c549b8f7c` | 30 |

---

## 6. Findings, Risks, and Limitations

| ID | Finding | Severity | Evidence | Impact | Status |
|---|---|---|---|---|---|
| F1 | Zero incremental data beyond Phase 11F | High | `daily_bars` max date is `2026-10-16`; decision cutoff `2026-09-25` | Retraining does not yet have substantial new-data support. | Accepted |
| F2 | Structural transaction friction barrier | Critical | All candidates net negative ($-0.35\%$ to $-0.68\%$) under 50 bps friction | Models cannot be promoted to production or live trading. | Open |
| F3 | Cross-fold degradation in Fold 3 | High | Realized win rates fall across all models in Fold 3 (2025–2026) | Market regime shifts degrade raw model edge. | Open |
| F4 | Target mismatch in champion baseline | Info | Champion trained on Variant A H=10, evaluated on Variant B H=15 | Comparison provides context, but is not direct apples-to-apples. | Accepted |

---

## 7. Verification

| Check | Command or Method | Result | Evidence/Notes |
|---|---|---|---|
| Cutoff audit | `.venv\Scripts\python.exe scripts/inspect_dataset_splits.py` | PASS | Bar max `2026-10-16`, decision cutoff `2026-09-25`, +46,343 valid rows (+36.60%). |
| Unit tests | `.venv\Scripts\python.exe -m pytest tests/unit/test_challenger_retraining.py` | PASS (6 passed) | Specs, cutoff, MPMX filter, dataset audit, purge window, SHA-256, and champion immutability verified. |
| Full test suite | `.venv\Scripts\python.exe -m pytest` | PASS (597 passed) | 100% pass rate across entire repository test suite (565 unit, 32 integration). |
| Linter checks | `.venv\Scripts\python.exe -m ruff check .` | PASS (0 errors) | Zero formatting or code hygiene violations. |
| Production isolation | `git status`, registry inspection | PASS | Production champions in `models/registry/` and Phase 11F artifacts strictly untouched. |

---

## 8. Files, Artifacts, and Data Changes

- **Files created:**
  - `python/experiments/challenger_retraining.py`
  - `scripts/run_offline_challenger_retraining.py`
  - `scripts/inspect_dataset_splits.py`
  - `tests/unit/test_challenger_retraining.py`
  - `docs/21_offline_challenger_retraining_report.md`
- **Files modified:**
  - `audit_report.md` (updated current-status index)
  - `summary.md` (appended log entry 67)
  - `walkthrough.md` (rewritten with current work session breakdown)
- **Files deleted:** None.
- **Generated artifacts:**
  - `artifacts/offline_challengers/run_20261021_retraining/low_price/*.joblib` (3 binaries)
  - `artifacts/offline_challengers/run_20261021_retraining/higher_price/*.joblib` (3 binaries)
  - `artifacts/offline_challengers/run_20261021_retraining/metadata.json`
  - `artifacts/offline_challengers/run_20261021_retraining/challenger_retraining_summary.json`
  - `artifacts/offline_challengers/run_20261021_retraining/metrics/*.csv` (4 CSVs)
  - `artifacts/offline_challengers/run_20261021_retraining/oos_predictions_*.csv` (2 CSVs)
- **Production state changed:** No. Zero changes to production models, registries, or databases.

---

## 9. Safeguards and Backward Compatibility

- **Champion Protection:** Production models `lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607` were verified immutable before, during, and after execution.
- **Phase 11F Isolation:** No files in `artifacts/phase_11f/` were altered. `--approve-observation` was not executed. Prospective observation was not started.
- **Database Immutability:** No rows in `daily_bars`, `features_daily`, `labels_daily`, or `outcomes_daily` were created, deleted, or modified.

---

## 10. Reproducibility

- **Environment:** Windows, Python 3.12.10 (`.venv\Scripts\python.exe`).
- **Database:** `datasets/stock_signals.db` (SQLite, SHA-verified).
- **Reproduction Command:**
  ```powershell
  .venv\Scripts\python.exe scripts/run_offline_challenger_retraining.py --cutoff-date 2026-09-25 --run-id run_20261021_retraining
  ```
- **Test Command:**
  ```powershell
  .venv\Scripts\python.exe -m pytest tests/unit/test_challenger_retraining.py -v
  ```

---

## 11. Final Decision

- **Acceptance criteria satisfied:** Yes. All requested model configurations evaluated, walk-forward splits verified, simulated trading completed, and artifacts serialized.
- **Remaining blockers:** None for this offline task.
- **Known limitations:** Genuinely incremental training data beyond `2026-09-25` is currently unavailable in the database.
- **Next action:** Maintain current champions and wait for forward prospective market bar ingestion past `2026-10-16` before initiating any prospective scoring or subsequent retraining.
- **Approval required before proceeding:** Yes. Any future champion replacement or prospective activation requires human operator authorization.
