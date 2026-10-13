# Walkthrough — Phase 10: Model Evaluation & Champion/Challenger Comparator

Dokumen ini mencatat rincian implementasi **Phase 10 — Model Evaluation** sesuai panduan arsitektur `docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` (Sections 26, 27, 28, 30, 31, 32, 50, dan Phase 10 pada Section 65) serta `docs/03_plan_ai_stock_signal_BEI_daily.md`.

---

## 1. Task Breakdown & Komponen yang Dibangun

Phase 10 berfokus pada pembuktian edge model secara ilmiah dan objektif:
- Mengukur kualitas probabilitas prediksi (Brier score, calibration curve, ECE, log loss, ROC-AUC).
- Mengukur kinerja trading out-of-sample (win rate, profit factor, expectancy, max drawdown, Sharpe ratio).
- Menyediakan automated promotion gate untuk membandingkan model Champion dan Challenger pada dataset out-of-sample yang identik secara kronologis.

### A. Domain Models (`python/common/types.py`)
- **`TradingMetrics`**:
  - `win_rate`: Rasio trade profit terhadap total trade.
  - `profit_factor`: Gross gains dibagi gross losses (mengembalikan `inf` jika tanpa kerugian).
  - `expectancy`: Rata-rata persentase return per trade.
  - `max_drawdown`: Penurunan ekuitas puncak-ke-lembah maksimum (compounded path).
  - `sharpe`: Annualized Sharpe ratio (frekuensi 252 hari).
  - `avg_win`, `avg_loss`, `total_trades`, `tp_rate`, `sl_rate`, `expiry_rate`.
- **`PredictionMetrics`**:
  - `brier_score`: MSE probabilitas vs target biner.
  - `log_loss`: Binary cross-entropy dengan probability clipping ($10^{-15}$).
  - `roc_auc`: Area under the ROC curve (fallback rank-based jika sklearn tidak tersedia).
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
  - `delta_metrics`: Selisih kuantitatif antar metrik (`challenger - champion`).
  - `recommendation`: Status keputusan promosi (`PROMOTE`, `REJECT`, `INCONCLUSIVE`).
  - `rationale`: Log argumentasi eksplisit setiap aturan evaluasi.

### B. Evaluation Engine (`python/models/evaluation.py` & `python/evaluation/`)
- `compute_calibration_bins(y_true, y_prob, n_bins=10)`:
  - Membagi probabilitas ke dalam $n$ bin seragam ($0.0 \dots 1.0$).
  - Menghitung deviasi kalibrasi berbobot (ECE) dan detail setiap reliability bin.
- `compute_trading_metrics(returns, outcome_statuses=None)`:
  - Mengkalkulasi metrik trade out-of-sample dari array return dan status outcome.
- `EvaluationEngine`:
  - `evaluate_predictions(y_true, y_prob)`: Menghasilkan `PredictionMetrics` dan bin kalibrasi.
  - `evaluate_dataset(df, ...)`: Mengevaluasi dataset Pandas/matured outcomes DataFrame.
  - `evaluate_model(model, X, y_true, returns, ...)`: Menjalankan inferensi model dan komputasi metrik lengkap.
  - `evaluate_from_outcomes(outcomes, ...)`: Mengevaluasi langsung dari list record `SignalOutcomeRecord`.

### C. Champion vs. Challenger Comparator (`python/models/comparator.py`)
- `PromotionGateConfig`:
  - `min_sample_size`: Default 30 (mencegah promosi pada sampel kecil/tidak signifikan).
  - `min_profit_factor_improvement`: Default +0.05.
  - `max_brier_worsening`: Default 0.0 (Brier score Challenger harus $\le$ Champion).
  - `max_drawdown_increase`: Default 0.0 (Max Drawdown tidak boleh memburuk).
  - `min_expectancy_improvement`: Default 0.0%.
- `ModelComparator`:
  - `compare_reports(champion_report, challenger_report)`: Menerapkan gerbang keputusan dan memproduksi `ComparisonReport`.
  - `compare_models(champion_model, challenger_model, X_test, ...)`: Evaluasi sinkron dua objek model pada data uji yang sama.
  - `compare_from_registry(registry, champ_ver, chall_ver, X_test, ...)`: Pemuatan otomatis model dari `ModelRegistry`.
- Formatters presentasi laporan:
  - `format_comparison_table`: Tabel perbandingan ASCII terminal yang rapi.
  - `format_comparison_markdown`: Tabel laporan format GitHub Markdown.
  - `format_comparison_json`: Ekspor JSON terstruktur.

### D. CLI Tool & Integrasi Workflow (`scripts/evaluate_models.py` & `Makefile`)
- CLI Runner `scripts/evaluate_models.py`:
  - Opsi: `--champion-version`, `--challenger-version`, `--dataset-path`, `--from-outcomes`, `--output-format [table|json|markdown]`, `--save-report`, `--min-sample-size`, `--promote-if-passed`.
  - Mendukung evaluasi model tunggal maupun komparasi Champion vs. Challenger.
- Target `Makefile`:
  - `make evaluate`: Menjalankan evaluasi dari matured outcomes database dengan format tabel.

### E. README & Repository Remote
- Penambahan **AI Authorship Disclosure** di `README.md` sesuai `/antislop-copywriting` (jujur, tidak ada klaim pemasaran berlebihan, menerangkan ~98% kode di-generate oleh AI coding agents di bawah supervisi spesifikasi dan pengujian ketat).
- Penambahan baris `Model Evaluation` di tabel CLI Pipelines `README.md`.
- Konfigurasi git remote origin diarahkan ke `https://github.com/hikwoa-hfw/idx-stock-signal.git`.
- Commit git fungsional Phase 0-9 telah direkam ke branch `main`.

---

## 2. File & Line Changes Detail

1. **`python/common/types.py`**:
   - Baris 6: Menambahkan import `Union` pada typing module.
   - Baris 1048–1123: Menambahkan class `TradingMetrics`, `PredictionMetrics`, `CalibrationBin`, `EvaluationReport`, `ComparisonRecommendation`, dan `ComparisonReport` dengan validasi enum dan lifecycle.

2. **`python/models/evaluation.py`**:
   - File baru: Implementasi fungsi matematis `compute_calibration_bins`, `compute_trading_metrics`, dan kelas `EvaluationEngine`.

3. **`python/models/comparator.py`**:
   - File baru: Implementasi `PromotionGateConfig`, `ModelComparator`, serta helper formatters (`format_comparison_table`, `format_comparison_markdown`, `format_comparison_json`).

4. **`python/models/__init__.py`**:
   - Re-ekspor `EvaluationEngine`, `compute_calibration_bins`, `compute_trading_metrics`, `ModelComparator`, `PromotionGateConfig`, dan formatters.

5. **`python/evaluation/__init__.py` & `python/evaluation/engine.py`**:
   - Re-ekspor modul evaluasi pada package namespace `python.evaluation`.

6. **`scripts/evaluate_models.py`**:
   - Script CLI runner untuk evaluasi model dan ekspor laporan komparasi.

7. **`Makefile`**:
   - Menambahkan target `evaluate` ke `.PHONY` dan mendefinisikan recipe `$(VENV_PYTHON) -m scripts.evaluate_models --from-outcomes --output-format table`.

8. **`README.md`**:
   - Menambahkan section `AI Authorship Disclosure`.
   - Menambahkan pipeline `Model Evaluation` pada tabel CLI.
   - Memperbarui `Project Status` menjadi Phases 0–10 Complete.

9. **`summary.md`**:
   - Append-only: Menambahkan entri ke-23 untuk Phase 10 tanpa menghapus rekaman riwayat sebelumnya.

10. **`tests/unit/test_types.py`**:
    - Menambahkan pengujian `test_evaluation_report_validation` dan `test_comparison_report_validation`.

11. **`tests/unit/test_evaluation.py`**:
    - File baru: 16 unit tests untuk komputasi metrik probabilistik, bin kalibrasi ECE, metrik trading, skenario tepi (empty, all wins, all losses), dan gerbang keputusan comparator (`PROMOTE`, `REJECT`, `INCONCLUSIVE`).

12. **`tests/integration/test_evaluation_pipeline.py`**:
    - File baru: 3 integration tests mencakup end-to-end evaluation dari `ModelRegistry`, CLI runner via subprocess, dan evaluasi single-model JSON.

13. **`tests/unit/test_smoke.py`**:
    - Memverifikasi keberadaan file artefak Phase 10 (`python/models/evaluation.py`, `python/models/comparator.py`, `scripts/evaluate_models.py`).

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
  *Seluruh 272 pengujian unit dan integrasi harus 100% passed.*

- [ ] **CLI Model Evaluation (Sample/Test Dataset)**:
  ```bash
  .venv/Scripts/python -m scripts.evaluate_models --champion-version baseline_v1 --output-format table
  ```
  *Memverifikasi CLI dapat menampilkan ringkasan metrik evaluasi ke stdout.*

- [ ] **Champion vs. Challenger Comparator**:
  ```bash
  .venv/Scripts/python -m scripts.evaluate_models --champion-version champ_v1 --challenger-version chall_v2 --dataset-path datasets/processed/sample.csv --output-format markdown
  ```
  *Memverifikasi kalkulasi delta metrik dan logika gate rekomendasi (PROMOTE/REJECT).*

- [ ] **Makefile Target Check**:
  ```bash
  make evaluate
  ```
  *Memverifikasi Makefile recipe terhubung dengan environment Python venv secara benar.*

- [ ] **Git Authentication & Push**:
  *Konfigurasi token personal GitHub (PAT) atau SSH key jika ingin melakukan push ke remote origin:*
  ```bash
  git push -u origin main
  ```
