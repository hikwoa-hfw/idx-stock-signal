# Walkthrough — Phase 11A: Controlled Feature Ablation for BEI Dual-Mode Stock Signals

Sesi kerja ini mengimplementasikan **Phase 11A — Controlled Feature Ablation** untuk mengevaluasi nilai prediktif inkremental out-of-sample dari 7 keluarga fitur teknikal pada klasifikasi sinyal saham BEI (`LOW_PRICE` $\le 300$ dan `HIGHER_PRICE` $> 300$).

---

## 1. Perubahan Teknis dan File yang Dibuat / Dimodifikasi

### 1.1 Inisialisasi Modul Eksperimen
- **File:** `python/experiments/__init__.py`
  - Menginisialisasi paket modul `python.experiments`.

### 1.2 Implementasi Engine Ablasi Fitur
- **File:** `python/experiments/ablation.py`
  - Baris 31–84: Mendefinisikan pemetaan baku 7 keluarga fitur (`FEATURE_FAMILIES`) untuk 30 fitur aktif (`price_momentum`, `trend`, `oscillators`, `volatility`, `volume_liquidity`, `relative_strength`, `market_regime`).
  - Baris 88–331: Mendefinisikan metadata inventaris fitur komprehensif (`FEATURE_INVENTORY`) dengan formula matematis, lookback window, ketersediaan point-in-time, dan dependensi indikator.
  - Baris 334–382: Mengimplementasikan fungsi evaluasi performa probabilistik: `compute_pr_auc` (Average Precision), `compute_top_k_precision` (presisi deterministik pada top 10% probabilitas tertinggi), dan `evaluate_predictions` (sample size, prevalence, ROC-AUC, PR-AUC, Log Loss, Brier score, 10-bin ECE, Accuracy, Top-10% precision).
  - Baris 406–623: Mengimplementasikan `FeatureAblationRunner`:
    * Pemuatan data bersih langsung via SQL join `features_daily` dan `labels_daily` dengan filter regim harga kanonikal `classify_price_mode` dalam < 3 detik.
    * Pemisahan temporal expanding 3-fold walk-forward dengan jendela purge 10 hari (`WalkForwardSplitter`).
    * Isolasi preprocessing kausal: `SimpleImputer(strategy="median")` dipelajari strictly pada slice training per fold tanpa lookahead leakage.
    * Pelatihan dan evaluasi 17 model per fold (Reference LightGBM 30 fitur, 7 model ablasi leave-one-group-out, Prevalence Baseline, Logistic Regression Baseline, dan 7 model diagnostik group-only).
    * Agregasi metrik out-of-sample pooled dan perhitungan delta relatif terhadap model referensi ($\Delta = M_{\text{ablation}} - M_{\text{reference}}$).
    * Ekspor artefak JSON dan CSV di `artifacts/ablation/`.

### 1.3 Command Line Interface (CLI) Runner
- **File:** `scripts/run_feature_ablation.py`
  - Menyediakan runner eksekusi eksperimen dengan argumen CLI: `--mode [LOW_PRICE|HIGHER_PRICE|BOTH]`, `--n-splits` (default 3), `--purge-days` (default 10), `--random-state` (default 42), `--output-dir` (default `artifacts/ablation`), dan `--include-group-only`.
  - Mencetak ringkasan tabular rapi per regim harga dan mengekspor `ablation_summary_aggregate.csv/json`.

### 1.4 Suite Pengujian Otomatis
- **File:** `tests/unit/test_ablation.py`
  - `test_feature_family_inventory_completeness`: Memverifikasi 30 fitur default terpetakan secara lengkap dan mutually disjoint ke dalam 7 keluarga fitur.
  - `test_metrics_calculation_correctness`: Menguji presisi matematis Top-k precision, PR-AUC, Brier score, dan 10-bin ECE.
  - `test_walk_forward_purge_guarantees`: Memverifikasi ketiadaan tumpang tindih tanggal antar-fold dan penegakan celah purge 10 hari.
  - `test_production_champions_protected`: Memverifikasi model champion produksi (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`) tetap aktif dan tidak termodifikasi.

### 1.5 Artefak Eksperimen
- **File:**
  - `artifacts/ablation/feature_inventory.json`: Metadata 30 fitur.
  - `artifacts/ablation/ablation_results_LOW_PRICE.csv` & `.json`: Hasil evaluasi 33,962 sampel OOS `LOW_PRICE`.
  - `artifacts/ablation/ablation_results_HIGHER_PRICE.csv` & `.json`: Hasil evaluasi 101,051 sampel OOS `HIGHER_PRICE`.
  - `artifacts/ablation/ablation_summary_aggregate.csv` & `.json`: Ringkasan lintas regim harga.

### 1.6 Dokumentasi dan Pelaporan
- **File:** `docs/10_controlled_feature_ablation_report.md`
  - Laporan audit komprehensif mengikuti template standar 10 bagian.
- **File:** `summary.md`
  - Menambahkan Log Entry 51 (Append-Only preserved).

---

## 2. Temuan Kunci Eksperimen

1. **`LOW_PRICE` ($\le 300$, $N = 33,962$ OOS):**
   - **`market_regime` sangat krusial:** Menghapus kelompok ini memicu penurunan terbesar ($\Delta \text{ROC-AUC} = -0.0178$, $\Delta \text{PR-AUC} = -0.0181$).
   - **`trend` (EMA) adalah noise berbahaya:** Menghapus kelompok ini **meningkatkan performa di seluruh 3 fold** ($\Delta \text{ROC-AUC} = +0.0065$, $\Delta \text{PR-AUC} = +0.0095$, Brier score membaik $-0.0025$).
   - **`price_momentum` dan `volatility` esensial:** Menghapus salah satunya menurunkan ROC-AUC dan presisi top-10%.
2. **`HIGHER_PRICE` ($> 300$, $N = 101,051$ OOS):**
   - **`market_regime` merusak performa:** Menghapus kelompok ini **meningkatkan performa secara substansial** ($\Delta \text{ROC-AUC} = +0.0168$, Log Loss $-0.0137$, Brier $-0.0057$, ECE membaik dari $0.0524$ menjadi $0.0207$).
   - **`price_momentum` dan `volatility` adalah pendorong utama:** Menghapus momentum menurunkan ROC-AUC ($-0.0051$) dan presisi top-10% ($-0.0129$); menghapus volatilitas menurunkan ROC-AUC ($-0.0053$).
3. **Tree vs Linear:**
   - LightGBM reference unggul di `LOW_PRICE` (AUC 0.5754 vs Logistic 0.5632).
   - Logistic regression kompetitif di `HIGHER_PRICE` (AUC 0.5551 vs Tree 0.5526, Top-10% Precision 0.3318 vs 0.2999).

---

## 3. Testing Checklist

- [x] Jalankan pengujian unit ablasi:
  ```powershell
  .venv\Scripts\python.exe -m pytest tests/unit/test_ablation.py -v
  ```
  *Hasil:* 4 passed in 1.86s.
- [x] Jalankan pengujian regresi menyeluruh seluruh repositori:
  ```powershell
  .venv\Scripts\python.exe -m pytest
  ```
  *Hasil:* 448 passed, 0 failures, 1 warning (444 existing + 4 new).
- [x] Jalankan linter dan code hygiene:
  ```powershell
  .venv\Scripts\python.exe -m ruff check python/experiments/ scripts/run_feature_ablation.py tests/unit/test_ablation.py
  ```
  *Hasil:* All checks passed!
- [x] Jalankan eksekusi eksperimen ablasi CLI:
  ```powershell
  .venv\Scripts\python.exe -m scripts.run_feature_ablation --mode BOTH
  ```
  *Hasil:* Berhasil mengeksekusi 102 model fit dan menghasilkan artefak di `artifacts/ablation/`.
- [x] Verifikasi integritas model produksi di `models/registry/`:
  * `lightgbm_classification_20261014_093522` (status: champion)
  * `lightgbm_classification_20261014_093607` (status: champion)
  * Tidak ada model yang dipromosikan atau ditimpa secara prematur.
