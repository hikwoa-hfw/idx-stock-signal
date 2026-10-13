# Walkthrough — Phase 10: Model Evaluation & Champion/Challenger Comparator (Audit & Hardening)

Dokumen ini mencatat rincian implementasi dan audit perbaikan **Phase 10 — Model Evaluation** sesuai panduan arsitektur `docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` (Sections 26, 27, 28, 30, 31, 32, 50, dan Phase 10 pada Section 65) serta `docs/03_plan_ai_stock_signal_BEI_daily.md`.

---

## 1. Task Breakdown & Komponen yang Dibangun & Diaudit

Phase 10 berfokus pada pembuktian edge model secara ilmiah dan objektif:
- Mengukur kualitas probabilitas prediksi (Brier score, calibration curve, ECE, log loss, ROC-AUC).
- Mengukur kinerja trading out-of-sample (win rate, profit factor, expectancy, max drawdown, Sharpe ratio, avg win, avg loss).
- Menyediakan automated promotion gate untuk membandingkan model Champion dan Challenger pada dataset out-of-sample yang identik secara kronologis atau dari matured outcomes.

### A. Domain Models (`python/common/types.py`)
- **`TradingMetrics`**:
  - `win_rate`: Rasio trade profit terhadap total trade.
  - `profit_factor`: Gross gains dibagi gross losses (mengembalikan `inf` jika tanpa kerugian).
  - `expectancy`: Rata-rata persentase return per trade.
  - `max_drawdown`: Penurunan ekuitas puncak-ke-lembah maksimum dari modal awal ($1.0$).
  - `sharpe`: Annualized Sharpe ratio (frekuensi 252 hari).
  - `avg_win`, `avg_loss`, `total_trades`, `tp_rate`, `sl_rate`, `expiry_rate`.
- **`PredictionMetrics`**:
  - `brier_score`: MSE probabilitas vs target biner.
  - `log_loss`: Binary cross-entropy dengan probability clipping ($10^{-15}$).
  - `roc_auc`: Area under the ROC curve.
  - `ece`: Expected Calibration Error.
  - `accuracy`: Akurasi klasifikasi pada threshold keputusan.
- **`CalibrationBin`**:
  - `bin_index`, `lower_bound`, `upper_bound`, `sample_count`, `mean_predicted`, `observed_frequency`, `gap`.
- **`EvaluationReport`**:
  - Metadata model (`model_version`, `evaluation_date`, `dataset_version`, `sample_size`, `status`).
  - Kontainer bertipe `trading_metrics`, `prediction_metrics`, dan list `calibration_bins`.
  - Serialisasi JSON via `.to_dict()`.
- **`ComparisonRecommendation` & `ComparisonReport`**:
  - `champion_version`, `challenger_version`, `test_window`.
  - Kontainer `champion_metrics` dan `challenger_metrics` bertipe `EvaluationReport`.
  - `delta_metrics`: Selisih kuantitatif antar metrik (`challenger - champion`), termasuk `avg_win_delta` dan `avg_loss_delta`.
  - `recommendation`: Status keputusan promosi (`PROMOTE`, `REJECT`, `INCONCLUSIVE`).
  - `rationale`: Log argumentasi eksplisit setiap aturan evaluasi.

### B. Evaluation Engine (`python/models/evaluation.py` & `python/evaluation/`)
- `compute_calibration_bins(y_true, y_prob, n_bins=10)`:
  - Memvalidasi kesamaan panjang array input `y_true` dan `y_prob` (`ValueError` jika berbeda).
  - Menyaring nilai non-finite secara aman.
  - Membagi probabilitas ke dalam $n$ bin seragam ($0.0 \dots 1.0$).
  - Menghitung deviasi kalibrasi berbobot (ECE) dan detail setiap reliability bin.
- `compute_trading_metrics(returns, outcome_statuses=None)`:
  - Menyaring dan menormalisasi input non-finite/null menjadi `0.0`.
  - **Perbaikan Max Drawdown**: Menyisipkan modal awal `1.0` di indeks 0 kurva ekuitas (`np.insert(..., 0, 1.0)`). Menghilangkan bug di mana trade loss pertama menghasilkan drawdown 0.0%.
- `EvaluationEngine`:
  - `evaluate_predictions(y_true, y_prob)`: Menghasilkan `PredictionMetrics` dan bin kalibrasi dengan validasi dimensi.
  - `evaluate_dataset(df, ...)`: Mengevaluasi dataset Pandas/matured outcomes DataFrame dengan opsi `filter_model_version` otomatis mengisolasi baris milik model terkait.
  - `evaluate_model(model, X, y_true, returns, ...)`: Menjalankan inferensi model dengan dukungan `filter_by_prediction` dan `decision_threshold` (hanya menghitung trade yang disinyalkan oleh model).
  - `evaluate_from_outcomes(outcomes, ...)`: Mengevaluasi langsung dari list record `SignalOutcomeRecord`.

### C. Champion vs. Challenger Comparator (`python/models/comparator.py`)
- `PromotionGateConfig`:
  - `min_sample_size`: Default 30 (mencegah promosi pada sampel kecil/tidak signifikan).
  - `min_profit_factor_improvement`: Default +0.05.
  - `max_brier_worsening`: Default 0.0 (Brier score Challenger harus $\le$ Champion).
  - `max_drawdown_increase`: Default 0.0 (Max Drawdown tidak boleh memburuk).
  - `min_expectancy_improvement`: Default 0.0%.
- `ModelComparator`:
  - Mengaplikasikan toleransi floating-point epsilon ($10^{-9}$) pada evaluasi batas numerik untuk mencegah penolakan palsu (false reject) akibat pembulatan IEEE-754.
  - `compare_reports(champion_report, challenger_report)`: Menerapkan gerbang keputusan dan memproduksi `ComparisonReport`.
  - `compare_models(...)` & `compare_from_registry(...)`: Mendukung penerusan `filter_by_prediction` dan `decision_threshold`.
- Formatters presentasi laporan:
  - `format_comparison_table`: Tabel perbandingan ASCII terminal rapi dengan formatting window bersih (`_format_window_str`).
  - `format_comparison_markdown`: Tabel laporan format GitHub Markdown dengan metrik lengkap.
  - `format_comparison_json`: Ekspor JSON terstruktur.

### D. CLI Tool & Integrasi Workflow (`scripts/evaluate_models.py` & `Makefile`)
- CLI Runner `scripts/evaluate_models.py`:
  - Opsi: `--champion-version`, `--challenger-version`, `--dataset-path`, `--from-outcomes`, `--output-format [table|json|markdown]`, `--save-report`, `--min-sample-size`, `--promote-if-passed`, `--filter-by-prediction`, `--threshold`.
  - Format output Markdown didukung penuh untuk evaluasi single-model dan perbandingan multi-model.
- Target `Makefile`:
  - `make evaluate`: Menjalankan evaluasi dari matured outcomes database dengan format tabel.

---

## 2. File & Line Changes Detail (Audit Session)

1. **`python/models/evaluation.py`**:
   - `compute_calibration_bins`: Menambahkan validasi `len(yt) != len(yp)` (`ValueError`) dan penyaringan `np.isfinite`.
   - `compute_trading_metrics`: Menormalisasi input null/non-finite; menyisipkan modal awal `1.0` pada `equity_curve` (`np.insert(..., 0, 1.0)`) sehingga penarikan modal trade pertama dan beruntun terhitung presisi.
   - `EvaluationEngine.evaluate_predictions`: Menambahkan validasi dimensi eksplisit.
   - `EvaluationEngine.evaluate_dataset`: Menambahkan parameter `filter_model_version=True` untuk mengisolasi baris DataFrame berdasarkan kolom `model_version`.
   - `EvaluationEngine.evaluate_model`: Menambahkan parameter `filter_by_prediction` dan `decision_threshold` untuk menyaring kandidat trade berdasarkan sinyal probabilitas.

2. **`python/models/comparator.py`**:
   - `ModelComparator.compare_reports`: Menambahkan `avg_win_delta` dan `avg_loss_delta` ke `delta_metrics`; mengaplikasikan toleransi float epsilon $10^{-9}$ pada semua aturan gerbang keputusan.
   - `ModelComparator.compare_models` & `compare_from_registry`: Meneruskan parameter `filter_by_prediction` dan `decision_threshold`.
   - `format_comparison_table` & `format_comparison_markdown`: Menggunakan helper `_format_window_str` untuk memformat `test_window` dictionary menjadi `"start to end"`.

3. **`scripts/evaluate_models.py`**:
   - Menambahkan argumen CLI `--filter-by-prediction` dan `--threshold`.
   - Meneruskan filter prediksi ke `compare_from_registry`.
   - Menambahkan dukungan format Markdown untuk evaluasi model tunggal (`--output-format markdown`).

4. **`README.md`**:
   - Memperbarui jumlah total automated test menjadi 281 tests.

5. **`summary.md`**:
   - Menambahkan entri ke-24 (Skeptical Review & Audit Perbaikan Phase 10) secara append-only.

6. **`tests/unit/test_evaluation.py`**:
   - Menambahkan 7 unit test baru: pengujian single-loss max drawdown (5.0%), two-loss drawdown (9.75%), input non-finite/null, validasi ketidakcocokan panjang array, isolasi model_version pada DataFrame, penyaringan trade berdasarkan probabilitas, dan toleransi floating-point comparator.

7. **`tests/integration/test_evaluation_pipeline.py`**:
   - Menambahkan 2 integration test baru: pengujian CLI multi-model outcomes CSV dataset (memverifikasi isolasi model dan promosi Challenger), dan pengujian single-model dengan format Markdown.

---

## 3. Testing Checklist (Post-Deployment Verification)

Setelah proses deployment atau clone, verifikasi checklist berikut:

- [ ] **Linting & Code Style**:
  ```bash
  .venv/Scripts/ruff check .
  ```
  *Harus menghasilkan `All checks passed!` tanpa error.*

- [ ] **Full Test Suite Execution**:
  ```bash
  .venv/Scripts/pytest
  ```
  *Seluruh 281 pengujian unit dan integrasi harus 100% passed.*

- [ ] **Single Model Evaluation CLI**:
  ```bash
  .venv/Scripts/python -m scripts.evaluate_models --champion-version baseline_v1 --output-format table
  ```
  *Memverifikasi CLI menampilkan metrik evaluasi model tunggal.*

- [ ] **Champion vs. Challenger Comparator**:
  ```bash
  .venv/Scripts/python -m scripts.evaluate_models --champion-version champ_v1 --challenger-version chall_v2 --dataset-path datasets/processed/sample.csv --output-format markdown
  ```
  *Memverifikasi kalkulasi delta metrik dan logika gate rekomendasi (PROMOTE/REJECT/INCONCLUSIVE).*

- [ ] **Makefile Target Check**:
  ```bash
  make evaluate
  ```
  *Memverifikasi Makefile recipe terhubung dengan environment Python venv secara benar.*

- [ ] **Git Remote & Authentication**:
  *Remote origin terkonfigurasi ke `https://github.com/hikwoa-hfw/idx-stock-signal.git`. Jalankan push dengan PAT/SSH user:*
  ```bash
  git push -u origin main
  ```
