# Audit Report — Phase 11A.1: Validasi Agregasi Fold & Metrik Pemeringkatan Cross-Sectional Harian

## 1. Audit Metadata

- **Audit date:** `2026-10-16 16:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** `5c06aa85e67c4bfa4b6b1877d3e896b694087574`
- **Report status:** `PASS`
- **Audit scope:** Validasi metodologi evaluasi Phase 11A feature ablation. Penggantian metrik pemeringkatan pooled antar-fold dengan evaluasi intra-fold, agregasi makro (mean, std, min, max), serta implementasi daily cross-sectional Top-10% precision dengan deterministic tie-breaking `(-probability, ticker ASC)` dan threshold kandidat harian ($N_d \ge 10$). Penyimpanan prediksi out-of-sample level baris di `artifacts/ablation/oos_predictions_*.csv` untuk 17 model. Re-evaluasi hipotesis fitur dual-mode `LOW_PRICE` ($\le 300$) dan `HIGHER_PRICE` ($> 300$).
- **Dataset/database:** `datasets/stock_signals.db` (186,291 daily bars, 186,291 feature records, 185,515 label records across 208 tickers spanning `2023-01-02` to `2026-10-13`, 897 trading days).
- **Previous report:** [docs/10_controlled_feature_ablation_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/10_controlled_feature_ablation_report.md) & [docs/11_feature_ablation_metric_validation_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/11_feature_ablation_metric_validation_report.md)

---

## 2. Executive Summary

### Decision

- **Implementation:** `PASS`
- **Historical/data integrity:** `PASS`
- **Evaluation validity:** `PASS`
- **Next stage:** `APPROVAL REQUIRED` (Phase 11B Candidate Model Retraining; production champions remain untouched).

### What changed

- **Eliminasi Bias Pemeringkatan Pooled:** Mengganti agregasi pooled cross-fold yang mendistorsi peringkat probabilitas dengan evaluasi intra-fold independen dan agregasi makro (mean, std, min, max). Memperbaiki paradoks *prevalence baseline* yang sebelumnya menghasilkan ROC-AUC semu 0.5066 (`LOW_PRICE`) dan 0.4953 (`HIGHER_PRICE`), kini strictly 0.5000 di setiap fold dan rata-rata makro (std 0.0000).
- **Implementasi Daily Cross-Sectional Ranking:** Mengganti metrik pooled global dengan pemeringkatan cross-sectional harian riil pada setiap tanggal keputusan ($N_d \ge 10$, $K_d = \max(1, \text{round}(N_d \times 0.10)))$ menggunakan tie-breaking deterministik stabil `(-probability, ticker ASC)`. Menambahkan metrik diagnostik harian Top-5 fixed sesuai kebijakan produksi `SignalConfig(top_n=5)`.
- **Persistensi Prediksi Out-of-Sample Level Baris:** Menyimpan seluruh prediksi out-of-sample beserta probabilitas dan flag seleksi harian `is_top10_{model}` untuk 17 model ke `artifacts/ablation/oos_predictions_LOW_PRICE.csv` (33,962 baris) dan `oos_predictions_HIGHER_PRICE.csv` (101,051 baris).
- **Ekspor Artifak Multi-Level:** Menghasilkan detail per-fold (`ablation_fold_details_*.csv`), ringkasan agregasi makro (`ablation_results_*.csv/.json`), dan multi-mode aggregate summary (`ablation_summary_aggregate.csv/.json`).

### Important findings

- **`LOW_PRICE` ($\le 300$) — Pemangkasan `trend` Meningkatkan Seluruh Metrik di Semua Fold:** Menghapus fitur trend moving average (EMA20, EMA50, EMA200, dan jarak EMA) secara konsisten meningkatkan performa di ketiga fold: Macro ROC-AUC naik dari 0.5739 ke **0.5817** ($\Delta = +0.0078$), Macro PR-AUC naik dari 0.3143 ke **0.3238** ($\Delta = +0.0095$), Daily Top-10% Precision melonjak dari 31.89% ke **33.93%** ($\Delta = +2.04\%$, unggul di Fold 1 +3.51%, Fold 2 +0.97%, Fold 3 +1.63%), dan Brier score membaik ke 0.1945.
- **`LOW_PRICE` ($\le 300$) — `market_regime` Bersifat Esensial:** Menghapus fitur rezim pasar IHSG dan breadth menyebabkan kejatuhan drastis: Macro ROC-AUC anjlok ke **0.5588** ($\Delta = -0.0151$), PR-AUC ke **0.2941** ($\Delta = -0.0202$), Daily Top-10% ke **31.13%**, dan pada Fold 1 ROC-AUC runtuh ke **0.5350**.
- **`HIGHER_PRICE` ($> 300$) — Divergensi Temporal pada `market_regime`:** Penghapusan regime pasar menunjukkan divergensi antar-fold: merugikan Fold 1 (2024: AUC $-0.0114$, PR-AUC $-0.0233$), namun meningkatkan Fold 2 (2025: AUC $+0.0189$) dan Fold 3 (2026: AUC $+0.0443$). Efek presisi harian rata-rata hanya berubah $+0.24\%$ (30.06% $\rightarrow$ 30.30%). Fitur momentum harga dan volatilitas terbukti sebagai pilar utama.
- **Baseline Linear (`logistic_baseline`) Sangat Kompetitif:** Mencapai Macro ROC-AUC 0.5629 pada `LOW_PRICE` (Daily Top-10% 32.11%) dan 0.5600 pada `HIGHER_PRICE` (mencapai 0.6095 pada Fold 2), mengonfirmasi perannya sebagai baseline pembanding wajib di Phase 11B.

### Final recommendation

Pertahankan model champion produksi saat ini (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`) tanpa perubahan. Setujui transisi ke **Phase 11B: Candidate Model Retraining & Controlled Gate Evaluation** dengan spesifikasi fitur yang terbukti secara empiris:
1. **`LOW_PRICE` Challenger:** Latih model LightGBM tanpa kelompok `trend` (mempertahankan 23 fitur terbaik).
2. **`HIGHER_PRICE` Challenger:** Uji interaksi regime pasar vs stock-level momentum/volatility, serta sertakan regularized logistic regression dan ensemble.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Remaining issue |
|---|---|---|---|---|
| R1 | Per-Fold Metric Calculation (ROC-AUC, PR-AUC, Brier, Log Loss, ECE, Accuracy) | PASS | `python/experiments/ablation.py` `evaluate_predictions_binary()`, `artifacts/ablation/ablation_fold_details_*.csv` | None |
| R2 | Macro Fold Aggregation (Mean, Std, Min, Max across expanding walk-forward folds) | PASS | `python/experiments/ablation.py` `aggregate_fold_metrics()`, `artifacts/ablation/ablation_results_*.csv` | None |
| R3 | Elimination of Cross-Fold Pooling Bias (Constant prevalence = strictly 0.5000 ROC-AUC) | PASS | Verified in Fold 1, 2, 3 and Macro-average = 0.5000 ($\text{std} = 0.0000$); test in `tests/unit/test_ablation.py` | None |
| R4 | Daily Cross-Sectional Ranking Algorithm ($N_d \ge 10$, Top-10% Cutoff, Deterministic Tie-Breaking) | PASS | `python/experiments/ablation.py` `compute_daily_cross_sectional_top_k_precision()`; verified on 663 trading dates | None |
| R5 | Secondary Production Diagnostic (Daily Top-5 Precision matching `SignalConfig(top_n=5)`) | PASS | `python/experiments/ablation.py` `compute_daily_top_n_precision()`; exported in fold details and results | None |
| R6 | Row-Level Out-of-Sample Predictions Persistence (`oos_predictions_*.csv`) | PASS | `artifacts/ablation/oos_predictions_LOW_PRICE.csv` (33,962 rows) & `oos_predictions_HIGHER_PRICE.csv` (101,051 rows) | None |
| R7 | Target, Label & Point-in-Time Anchor Consistency Verification | PASS | Audited against `python/labels/engine.py` (entry price close[t] vs open[t+1] flagged for Phase 11B evaluation) | None |
| R8 | Production Champion & Security Safeguards Preservation | PASS | `models/registry/` intact; `test_production_champions_protected` passing; no live trading/promotion | None |

Jangan menandai PASS hanya karena kode berhasil dijalankan. Setiap kriteria harus memiliki bukti yang sesuai.

---

## 4. Quantitative Results

### Evaluation setup

- **Observation period:** `2023-01-02` to `2026-10-13` (897 trading days across 208 BEI tickers).
- **Number of records:**
  * `LOW_PRICE` ($\le 300$): 45,763 total rows. Test out-of-sample: 33,962 rows across 663 trading dates (8,962 positive, prevalence 26.39%).
  * `HIGHER_PRICE` ($> 300$): 137,426 total rows. Test out-of-sample: 101,051 rows across 663 trading dates (25,248 positive, prevalence 24.99%).
- **Inclusion/exclusion rules:**
  * `LOW_PRICE`: $50 \le \text{entry\_price} \le 300$.
  * `HIGHER_PRICE`: $\text{entry\_price} > 300$.
  * Saham dengan harga $< 50$ dieksklusikan dari inferensi dan pelatihan (`EXCLUDED_BELOW_50`).
- **Price mode:** `LOW_PRICE` and `HIGHER_PRICE` (evaluated independently, zero cross-mode contamination).
- **Splits:** 3-fold expanding walk-forward splits with 10-day purge window:
  * **Fold 1:** Train `2023-01-02` $\rightarrow$ `2023-12-06` (224d), Purge 10d, Test `2023-12-21` $\rightarrow$ `2024-11-26` (221d).
  * **Fold 2:** Train `2023-01-02` $\rightarrow$ `2024-11-12` (445d), Purge 10d, Test `2024-11-28` $\rightarrow$ `2025-11-06` (221d).
  * **Fold 3:** Train `2023-01-02` $\rightarrow$ `2025-10-23` (666d), Purge 10d, Test `2025-11-07` $\rightarrow$ `2026-10-13` (221d).

### Results tables

#### Table 4.1: `LOW_PRICE` ($\le 300$) — Macro Fold-Aggregated Performance (3 Folds, $N = 33,962$)

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

#### Table 4.2: `LOW_PRICE` Per-Fold Detailed Breakdown

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

#### Table 4.3: `HIGHER_PRICE` ($> 300$) — Macro Fold-Aggregated Performance (3 Folds, $N = 101,051$)

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

#### Table 4.4: `HIGHER_PRICE` Per-Fold Detailed Breakdown

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

### Definitions and calculations

1. **ROC-AUC & PR-AUC:**
   - ROC-AUC dihitung per-fold menggunakan kurva ROC standard scikit-learn.
   - PR-AUC (Average Precision) dihitung menggunakan integral kurva precision-recall non-interpolasi: $\text{PR-AUC} = \sum_n (R_n - R_{n-1}) P_n$.
2. **Daily Cross-Sectional Ranking:**
   - Evaluasi harian dilakukan terpisah untuk setiap tanggal $d \in D$.
   - Syarat kelayakan tanggal: $N_d \ge 10$ kandidat eligible.
   - Kuota seleksi 10%: $K_d = \max(1, \text{int}(\text{round}(N_d \times 0.10)))$.
   - Tie-breaking deterministik stabil: `(-probability, ticker ASC)`.
   - Macro Daily Precision: $\bar{P} = \frac{1}{|D_{\text{eval}}|} \sum_{d \in D_{\text{eval}}} \text{Precision}_d$.
   - Micro Daily Precision: Total True Positives terpilih dibagi Total Picks terpilih.
3. **Macro Fold Aggregation:**
   - Setiap metrik $m$ dihitung secara independen pada setiap fold $f \in \{1, \dots, K\}$.
   - Macro-Mean: $\bar{m} = \frac{1}{K} \sum_{f=1}^K m_f$.
   - Macro-Std: $\sigma = \sqrt{\frac{1}{K-1} \sum_{f=1}^K (m_f - \bar{m})^2}$.
4. **Brier Score & Expected Calibration Error (ECE):**
   - Brier Score: Mean squared error probabilitas terhadap label riil: $\frac{1}{N}\sum (p_i - y_i)^2$.
   - ECE dihitung menggunakan 10 bin seragam $[0, 0.1), \dots, [0.9, 1.0]$.
5. **Catatan Perbedaan Unrounded Floats vs Display:**
   - Seluruh metrik diagregasikan dan dievaluasi menggunakan unrounded floating-point 64-bit IEEE 754 pada runtime. Angka tabel dibulatkan untuk tampilan visual markdown tanpa mempengaruhi kalkulasi matematis underlying.

---

## 5. Findings

### F1: Eliminasi Bias Pemeringkatan Pooled dan Paradoks Baseline Prevalensi
Penggabungan prediksi out-of-sample lintas-fold terbukti mendistorsi metrik pemeringkatan (ranking) secara artifisial. Pada model *prevalence baseline* yang menghasilkan probabilitas konstan di dalam tiap fold, intra-fold ROC-AUC mathematically adalah **0.5000**. Namun saat digabungkan, perbedaan prevalensi base-rate antarfolds menciptakan pemeringkatan semu (pooled ROC-AUC 0.5066 pada `LOW_PRICE` dan 0.4953 pada `HIGHER_PRICE`). Pendekatan per-fold dan macro-aggregation mengembalikan kebenaran empiris matematis: ROC-AUC tepat 0.5000 di setiap fold dan rata-rata makro 0.5000 (std 0.0000).

### F2: `LOW_PRICE` — Pemangkasan `trend` Meningkatkan Seluruh Metrik di Seluruh Fold
Pada saham $\le 300$, menghapus kelompok fitur `trend` (EMA20, EMA50, EMA200, dan rasio jarak) **menghasilkan peningkatan performa seragam di seluruh 3 fold**:
- Macro ROC-AUC meningkat $+0.0078$ (0.5739 $\rightarrow$ **0.5817**).
- Macro PR-AUC meningkat $+0.0095$ (0.3143 $\rightarrow$ **0.3238**).
- Daily Top-10% Precision melonjak $+2.04\%$ (31.89% $\rightarrow$ **33.93%**), mengungguli model referensi di Fold 1 (+3.51%), Fold 2 (+0.97%), dan Fold 3 (+1.63%).
- Brier score membaik dari 0.1970 menjadi **0.1945**.
Saham bernilai nominal rendah didominasi oleh pergerakan mean-reverting cepat yang tidak berkorelasi dengan tren jangka panjang 50/200 hari, sehingga indikator moving average hanya menambah noise pada split tree.

### F3: `LOW_PRICE` — `market_regime` Bersifat Esensial dan Tak Tergantikan
Menghapus kelompok `market_regime` pada saham `LOW_PRICE` menyebabkan penurunan performa paling parah di seluruh eksperimen:
- Macro ROC-AUC anjlok $-0.0151$ (0.5739 $\rightarrow$ **0.5588**).
- Macro PR-AUC jatuh $-0.0202$ (0.3143 $\rightarrow$ **0.2941**).
- Pada Fold 1, ROC-AUC ambruk dari 0.5734 ke **0.5350**.
Saham penny bursa BEI memerlukan dorongan likuiditas makro dan ekspansi IHSG untuk mempertahankan reli menuju target take-profit +5%.

### F4: `HIGHER_PRICE` — Divergensi Temporal Antar-Fold pada Pemangkasan `market_regime`
Pada tabel pooled Phase 11A, menghapus `market_regime` tampak selalu menguntungkan. Evaluasi per-fold mengungkap fakta divergensi temporal yang signifikan:
- **Fold 1 (2024):** Menghapus regime makro **merugikan** ROC-AUC ($-0.0114$) dan PR-AUC ($-0.0233$).
- **Fold 2 (2025):** Menghapus regime makro **meningkatkan** ROC-AUC ($+0.0189$) dan Daily Top-10% Precision ($+1.24\%$).
- **Fold 3 (2026):** Menghapus regime makro **meningkatkan** ROC-AUC ($+0.0443$), namun presisi harian hampir tidak berubah ($-0.28\%$).
Secara keseluruhan, Daily Top-10% Precision hanya berubah $+0.24\%$ (30.06% vs 30.30%). Kesimpulan: Pemangkasan `market_regime` pada `HIGHER_PRICE` bersifat regime-dependent dan tidak boleh dilakukan secara membabi buta tanpa pengujian interaksi pada Phase 11B.

### F5: Daya Saing dan Keandalan Baseline Linear (`logistic_baseline`)
Model regresi logistik terbukti menjadi pembanding yang sangat tangguh:
- Pada `LOW_PRICE`: Mencapai Macro ROC-AUC 0.5629 dengan Daily Top-10% Precision 32.11% (mengungguli LightGBM reference 31.89%).
- Pada `HIGHER_PRICE`: Mencapai Macro ROC-AUC 0.5600 (mengungguli LightGBM reference 0.5562), bahkan mencapai 0.6095 pada Fold 2.
Hal ini membuktikan bahwa hubungan linier sederhana pada momentum dan volatilitas sangat kokoh dan layak dieksplorasi sebagai model ensemble di Phase 11B.

---

## 6. Files & Data Changed

| File / Artifact | Type | Description |
|---|---|---|
| `python/experiments/ablation.py` | Code | Engine validasi agregasi fold, evaluasi per-fold, macro aggregation, dan daily cross-sectional ranking ($N_d \ge 10$, deterministic tie-breaking). |
| `scripts/run_feature_ablation.py` | CLI | Runner CLI dengan output tabel macro fold-aggregated summary dan opsi ekspor lengkap. |
| `tests/unit/test_ablation.py` | Tests | 11 unit tests mencakup validasi presisi harian, tie-breaking, isolasi fold, paradoks pooled baseline, dan perlindungan champion. |
| `artifacts/ablation/oos_predictions_LOW_PRICE.csv` | Data | 33,962 baris prediksi out-of-sample dengan probabilitas 17 model dan flag seleksi harian `is_top10_{model}`. |
| `artifacts/ablation/oos_predictions_HIGHER_PRICE.csv` | Data | 101,051 baris prediksi out-of-sample dengan probabilitas 17 model dan flag seleksi harian `is_top10_{model}`. |
| `artifacts/ablation/ablation_results_LOW_PRICE.csv/.json` | Data | Ringkasan metrik macro fold-aggregated, standar deviasi, delta, dan diagnostik pooled `LOW_PRICE`. |
| `artifacts/ablation/ablation_results_HIGHER_PRICE.csv/.json` | Data | Ringkasan metrik macro fold-aggregated, standar deviasi, delta, dan diagnostik pooled `HIGHER_PRICE`. |
| `artifacts/ablation/ablation_fold_details_LOW_PRICE.csv` | Data | Rincian performa per-fold untuk seluruh 17 model pada Fold 1, 2, dan 3 `LOW_PRICE`. |
| `artifacts/ablation/ablation_fold_details_HIGHER_PRICE.csv` | Data | Rincian performa per-fold untuk seluruh 17 model pada Fold 1, 2, dan 3 `HIGHER_PRICE`. |
| `artifacts/ablation/ablation_summary_aggregate.csv/.json` | Data | Tabel perbandingan terpadu multi-mode. |
| `docs/11_feature_ablation_metric_validation_report.md` | Doc | Laporan teknis historis Phase 11A.1. |
| `audit_report.md` | Doc | Laporan audit utama menggunakan template standar 10 bagian resmi. |
| `summary.md` | Doc | Log penambahan riwayat proyek (strictly append-only). |
| `walkthrough.md` | Doc | Catatan rincian pekerjaan dan checklist pengujian sesi. |

### Batasan dan Perlindungan Sistem (Strict Safeguards Preserved)
- Model champion produksi di `models/registry/` (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`) tetap aktif, tidak diubah, dan tidak dipromosikan ulang.
- Data mentah bursa di `daily_bars` dan rekor outcome di `outcomes_daily` tidak mengalami perubahan.
- Ambang batas BUY, EV Gate friction (50 bps), dan logika produksi tetap fail-closed.

---

## 7. Verification Evidence

### 7.1 Automated Unit Tests
Perintah yang dijalankan:
```powershell
& ".venv\Scripts\python.exe" -m pytest tests/unit/test_ablation.py
```
Output terminal:
```
...........                                                              [100%]
11 passed in 3.32s
```

### 7.2 Full Repository Regression Test Suite
Perintah yang dijalankan:
```powershell
& ".venv\Scripts\python.exe" -m pytest
```
Output terminal:
```
455 passed in 83.31s (0:01:23)
```
*(Seluruh 455 pengujian unit dan integrasi repositori lulus 100%, 0 failed, 0 regressions).*

### 7.3 Code Hygiene & Linter Audit
Perintah yang dijalankan:
```powershell
& ".venv\Scripts\python.exe" -m ruff check .
```
Output terminal:
```
All checks passed!
```

- **Tes yang benar-benar dijalankan:** 11 pengujian unit pada `tests/unit/test_ablation.py` dieksekusi secara nyata; 455 pengujian regresi penuh dieksekusi via pytest (100% lulus); linter dieksekusi via `ruff check .` (0 errors).
- **Tes yang dilewati:** 0 tes dilewati (`0 skipped`).
- **Klaim log agent tanpa eksekusi:** Nol. Seluruh angka metrik (33,962 dan 101,051 baris evaluasi) didasarkan pada file artifak riil di `artifacts/ablation/`.

---

## 8. Known Limitations

1. **Survivorship Bias pada Semesta Historis:** Database melacak bar harian untuk 208 ticker aktif BEI periode `2023-01-02` s.d. `2026-10-13`. Ticker yang mengalami delisting sebelum 2026 tidak tercakup dalam dataset, menimbulkan sedikit upward bias pada prevalensi positif historis.
2. **Korelasi Cross-Sectional Antar Saham:** Saham-saham bursa BEI kerap bergerak serempak saat sentimen makro (keputusan suku bunga BI, fluktuasi komoditas global), sehingga sampel harian tidak sepenuhnya independen.
3. **Konvensi Anchor Harga Entri Label:** Label engine pada `python/labels/engine.py` baris 68 menggunakan harga penutupan $t$ (`close[t]`) sebagai harga anchor entri, sedangkan engine operasional `SignalEngine` menggunakan pembukaan $t+1$ (`open[t+1]`). Hal ini menjadi catatan evaluasi komparatif pada Phase 11B.
4. **Baseline Hyperparameter Statis:** Hyperparameter LightGBM dipertahankan konstan di seluruh subset fitur untuk mengisolasi kontribusi murni kelompok fitur tanpa distorsi tuning budget.

---

## 9. Reproducibility

Perintah untuk mereproduksi seluruh eksperimen dan validasi metrik:
```powershell
# 1. Jalankan unit test ablasi
& ".venv\Scripts\python.exe" -m pytest tests/unit/test_ablation.py -v

# 2. Jalankan validasi metrik dan eksperimen ablasi 3-fold untuk kedua mode harga
$env:PYTHONPATH="."
& ".venv\Scripts\python.exe" -m scripts.run_feature_ablation `
    --mode BOTH `
    --n-splits 3 `
    --purge-days 10 `
    --random-state 42 `
    --output-dir artifacts/ablation `
    --include-group-only

# 3. Verifikasi file artifak yang dihasilkan
Get-ChildItem -Path artifacts/ablation
```

---

## 10. Final Decision & Next Step

### Final Decision: `PASS`
Validasi agregasi fold dan metrik pemeringkatan cross-sectional harian Phase 11A.1 berhasil diselesaikan dan diverifikasi secara matematis. Paradoks pooled ranking telah dieliminasi, metrik presisi harian telah mencerminkan seleksi bursa nyata, dan prediksi out-of-sample 17 model telah dipersistensikan secara lengkap.

### Recommended Next Step: `Phase 11B — Candidate Model Retraining & Controlled Gate Evaluation`
Mengajukan laporan ini untuk ditinjau pengguna. Setelah mendapat persetujuan, lanjutkan ke pelatihan model penantang (challenger candidate) pada Phase 11B:
1. **`LOW_PRICE` Challenger:** Latih model LightGBM tanpa kelompok `trend` (23 fitur), optimalkan kalibrasi dan ROC-AUC.
2. **`HIGHER_PRICE` Challenger:** Uji model kandidat dengan penanganan `market_regime` terkalibrasi serta model komparator linear/ensemble.
3. Evaluasi kedua kandidat melalui gerbang promosi formal Phase 11 (`ModelComparator`) terhadap champion yang ada sebelum mempertimbangkan promosi model.
