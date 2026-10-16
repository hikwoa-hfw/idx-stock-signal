# Walkthrough — Phase 11A.1: Validasi Agregasi Fold & Metrik Pemeringkatan Cross-Sectional Harian

## 1. Ringkasan Sesi Pekerjaan

Pada sesi pekerjaan ini, kami mengoreksi dan memvalidasi metodologi evaluasi metrik untuk eksperimen ablasi fitur Phase 11A pada sistem sinyal saham BEI dual-mode.

### Masalah Utama yang Diselesaikan:
1. **Bias Agregasi Cross-Fold (Pooled Metric Artifact):** Penggabungan prediksi out-of-sample lintas walk-forward folds mendistorsi metrik ranking karena adanya pergeseran prevalensi dan kalibrasi probabilitas antar-epoch. Kasus nyata: *prevalence baseline* yang memiliki ROC-AUC 0.5000 di dalam tiap fold terdistorsi menjadi 0.5066 pada `LOW_PRICE` dan 0.4953 pada `HIGHER_PRICE`.
2. **Ketiadaan Evaluasi Cross-Sectional Harian:** Metrik `compute_top_k_precision` sebelumnya memeringkat seluruh baris evaluasi pooled multi-tahun, bukan menyeleksi 10% kandidat saham terbaik pada setiap tanggal keputusan perdagangan bursa.
3. **Persistensi Prediksi Out-of-Sample Lengkap:** Belum tersimpannya probabilitas per baris dan penanda seleksi harian (`is_top10_{model}`) secara menyeluruh untuk seluruh 17 model yang dievaluasi.
4. **Proteksi Integritas Objek Hasil Eksperimen:** Metode `export_artifacts` sebelumnya menghapus kunci `oos_predictions_df` dari kamus hasil pemanggil menggunakan `pop()`, yang memutasi status data runtime secara in-place.

---

## 2. Rincian Perubahan File dan Kode

### A. `python/experiments/ablation.py`
- **Baris 357–471 (`compute_daily_cross_sectional_top_k_precision`):**
  * Mengimplementasikan ranking terisolasi per tanggal perdagangan (`date`).
  * Menerapkan aturan batas sampel minimum ($N_d \ge 10$). Tanggal dengan kandidat $< 10$ dieksklusikan dari agregasi presisi dan dicatat pada `insufficient_dates`.
  * Menerapkan tie-breaking deterministik stabil: `-probability` descending, kemudian `ticker` ascending.
  * Menghitung kuota seleksi harian $K_d = \min(N_d, \max(1, \text{int}(\text{round}(N_d \times 0.10))))$.
  * Menghasilkan array `selection_mask` berukuran $N$ yang menandai indeks baris saham terpilih (1) dan tidak terpilih (0).
  * Menghitung macro-average daily precision (rata-rata nilai presisi harian), standar deviasi presisi harian, dan micro-average (total true positives terpilih / total picks terpilih).
- **Baris 473–544 (`compute_daily_top_n_precision`):**
  * Mengimplementasikan diagnostik sekunder seleksi Top-N tetap ($N=5$) untuk mencocokkan kebijakan produksi `SignalConfig(top_n=5)`.
  * Menambahkan proteksi fail-closed terhadap `top_n <= 0` untuk mencegah `ZeroDivisionError`.
- **Baris 750–860 (`FeatureAblationRunner.run_experiment`):**
  * Menghitung metrik per-fold: ROC-AUC, PR-AUC, Daily Top-10% Precision, Daily Top-5 Precision, Brier Score, Log Loss, ECE, dan Accuracy.
  * Mengumpulkan prediksi out-of-sample per baris (`date`, `ticker`, `mode`, `binary_target`, probabilitas 17 model, dan penanda seleksi `is_top10_{model}` untuk seluruh model tanpa duplikasi kode seleksi).
- **Baris 862–990 (`FeatureAblationRunner.run_experiment` - Macro Aggregation):**
  * Mengimplementasikan agregasi macro lintas 3 folds: menghitung `mean`, `std`, `min`, `max` untuk setiap metrik.
  * Menghitung delta performa terhadap model referensi berbasis macro-mean.
  * Menyertakan metrik pooled sebagai diagnostik sekunder disertai label disclaimer limitasi.
- **Baris 992–1085 (`FeatureAblationRunner.export_artifacts`):**
  * Mengambil `oos_predictions_df` secara non-destruktif (`get()` alih-alih `pop()`), mencegah mutasi dictionary caller.
  * Menambahkan kolom `sample_size`, `positive_count`, dan `prevalence` pada `ablation_results_{mode}.csv`.
  * Mengekspor `ablation_fold_details_{mode}.csv` (rincian performa per-fold).
  * Mengekspor `oos_predictions_{mode}.csv` (prediksi out-of-sample per baris dengan bendera seleksi lengkap).
  * Mengekspor `feature_inventory.json`.

### B. `scripts/run_feature_ablation.py`
- **Baris 101–120:**
  * Memperbarui tabel output terminal untuk menampilkan kolom metrik macro fold-aggregated (`roc_auc_mean`, `roc_auc_std`, `pr_auc_mean`, `daily_top_10pct_prec_mean`, `daily_top_10pct_prec_std`, `daily_top_5_prec_mean`, `brier_score_mean`, `delta_macro_roc_auc`, `delta_macro_pr_auc`, `delta_macro_daily_top_10pct_prec`, `pooled_roc_auc`).

### C. `tests/unit/test_ablation.py`
- **`test_daily_cross_sectional_top_k_precision`:**
  * Menguji seleksi harian top 10% pada beberapa tanggal perdagangan serta aturan batas ambang minimum kandidat ($N < 5$ atau $N < 10$).
- **`test_deterministic_tie_breaking_by_ticker`:**
  * Menguji stabilitas tie-breaking deterministik berdasarkan abjad ticker saat probabilitas identik.
- **`test_prevalence_baseline_fold_auc_and_pooled_effect`:**
  * Membuktikan secara matematis bahwa prediksi konstan menghasilkan ROC-AUC tepat 0.5000 di dalam tiap fold, namun menyimpang dari 0.5000 saat dipooling antar-fold dengan prevalensi berbeda.
- **`test_daily_top_n_precision`:**
  * Menguji kalkulasi diagnostik Top-N tetap harian.
- **`test_daily_top_k_selection_mask`:**
  * Menguji akurasi array `selection_mask` harian terhadap baris data kandidat terpilih.
- **`test_daily_top_n_precision_edge_cases`:**
  * Menguji ketahanan fungsi saat menerima input `top_n <= 0` atau DataFrame kosong.
- **`test_export_artifacts_preserves_results_dict`:**
  * Menguji bahwa `export_artifacts` tidak menghapus kunci `oos_predictions_df` dari kamus input.

### D. Dokumentasi & Laporan Audit
- **`docs/11_feature_ablation_metric_validation_report.md`:**
  * Laporan audit lengkap 8 bagian mencakup metadata, executive summary, metodologi metrik harian & macro, tabel hasil komparasi, validasi hipotesis fitur, verifikasi semantik label & target, dan artefak reproduktibilitas.
- **`audit_report.md`:**
  * Diformat menggunakan template standar governance 10 bagian resmi yang diisi dengan seluruh temuan, hasil kuantitatif agregasi makro & presisi harian, serta verifikasi Phase 11A.1.
- **`summary.md`:**
  * Menambahkan Log Entry 52 (strictly append-only).

---

## 3. Hasil Validasi Empiris Utama

### Mode `LOW_PRICE` ($\le 300$)
- **Model Referensi (30 Fitur):** Macro ROC-AUC = 0.5739 ($\pm 0.0254$), Daily Top-10% Precision = 31.89% ($\pm 4.11\%$).
- **Tanpa Kelompok `trend` (`ablation_minus_trend`, 23 Fitur):**
  * Macro ROC-AUC meningkat menjadi **0.5817** ($\Delta = +0.0078$).
  * Macro PR-AUC meningkat menjadi **0.3238** ($\Delta = +0.0095$).
  * Daily Top-10% Precision meningkat menjadi **33.93%** ($\Delta = +0.0204$ / $+2.04\%$), unggul di Fold 1 (+3.51%), Fold 2 (+0.97%), dan Fold 3 (+1.63%).
  * Brier score membaik dari 0.1970 menjadi **0.1945**.
  * **Kesimpulan:** Mengonfirmasi secara konsisten bahwa fitur trend moving average jangka panjang bersifat noise untuk saham penny/small-cap BEI.
- **Tanpa Kelompok `market_regime` (`ablation_minus_market_regime`, 24 Fitur):**
  * Macro ROC-AUC jatuh ke **0.5588** ($\Delta = -0.0151$).
  * Fold 1 ROC-AUC anjlok ke 0.5350.
  * **Kesimpulan:** Fitur makro IHSG dan market breadth sangat esensial untuk `LOW_PRICE`.
- **Prevalence Baseline:**
  * Macro ROC-AUC = tepat **0.5000** (std 0.0000). Terbukti bebas dari bias agregasi pooled (sebelumnya 0.5066).

### Mode `HIGHER_PRICE` ($> 300$)
- **Model Referensi (30 Fitur):** Macro ROC-AUC = 0.5562 ($\pm 0.0232$), Daily Top-10% Precision = 30.06% ($\pm 1.55\%$).
- **Tanpa Kelompok `market_regime` (`ablation_minus_market_regime`, 24 Fitur):**
  * Menunjukkan divergensi temporal antarfolds: di Fold 1 (2024), menghapus regime makro merugikan performa ($\Delta \text{AUC} = -0.0114$, $\Delta \text{PR-AUC} = -0.0233$). Namun di Fold 2 (2025) dan Fold 3 (2026), menghapus regime makro meningkatkan ROC-AUC secara signifikan ($+0.0189$ dan $+0.0443$).
  * Macro Daily Top-10% Precision hanya meningkat tipis $+0.24\%$ ($30.06\% \rightarrow 30.30\%$).
- **Kelompok Inti `price_momentum` dan `volatility`:**
  * Menghapus `price_momentum` menurunkan Daily Top-10% Precision sebesar $-0.89\%$. Model group-only `volatility` sendiri mencapai Macro ROC-AUC 0.5681.
- **Prevalence Baseline:**
  * Macro ROC-AUC = tepat **0.5000** (std 0.0000). Terbukti bebas dari bias agregasi pooled (sebelumnya 0.4953).

---

## 4. Testing Checklist

Setelah perubahan di-deploy, verifikasi hal-hal berikut:

- [ ] **Integritas Model Produksi:**
  * Pastikan model champion produksi (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`) di `models/registry/` tidak mengalami mutasi file, timestamp, maupun status.
- [ ] **Kelulusan Pengujian Unit & Integrasi:**
  * Jalankan `pytest tests/unit/test_ablation.py` dan pastikan seluruh 11 tests lulus 100%.
  * Jalankan suite tes penuh `pytest` dan pastikan seluruh 455 tests lulus 100%.
- [ ] **Kepatuhan Linter:**
  * Jalankan `ruff check python/ experiments/ scripts/ tests/` dan pastikan 0 error/warning.
- [ ] **Kelengkapan Artefak Hasil Eksperimen:**
  * Verifikasi keberadaan file ringkasan agregat:
    - `artifacts/ablation/ablation_results_LOW_PRICE.csv` & `.json` (termasuk kolom sample_size & prevalence)
    - `artifacts/ablation/ablation_results_HIGHER_PRICE.csv` & `.json` (termasuk kolom sample_size & prevalence)
    - `artifacts/ablation/ablation_summary_aggregate.csv` & `.json`
  * Verifikasi keberadaan file detail per-fold:
    - `artifacts/ablation/ablation_fold_details_LOW_PRICE.csv`
    - `artifacts/ablation/ablation_fold_details_HIGHER_PRICE.csv`
  * Verifikasi keberadaan file prediksi out-of-sample baris-per-baris:
    - `artifacts/ablation/oos_predictions_LOW_PRICE.csv` (33.962 baris, 17 pasang prob & is_top10)
    - `artifacts/ablation/oos_predictions_HIGHER_PRICE.csv` (101.051 baris, 17 pasang prob & is_top10)
- [ ] **Verifikasi Prevalence Baseline 0.5000:**
  * Periksa kolom `roc_auc_mean` dan `roc_auc_std` untuk baris `prevalence_baseline` pada CSV hasil; pastikan nilainya tepat `0.5000` dan `0.0000`.
- [ ] **Flag Review Anchor Harga Entri Sebelum Phase 11B:**
  * Sebelum memulai pelatihan model kandidat challenger pada Phase 11B, pastikan tim/koordinator telah mereview implikasi anchor harga entri label (Close $t$ pada `labels_daily`) versus eksekusi operasional (Open $t+1$ pada `SignalEngine`).
