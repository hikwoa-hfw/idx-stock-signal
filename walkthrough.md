# Walkthrough — Phase 11: Retraining Pipeline

## Ringkasan Pekerjaan
Mengimplementasikan **Phase 11 — Retraining Pipeline** sesuai spesifikasi Sections 29, 30, 31, 32, 33, 50, dan Section 65 pada panduan pengembangan (`docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` dan `docs/03_plan_ai_stock_signal_BEI_daily.md`).

Pipeline ini mengotomatiskan siklus hidup model:
1. Pengecekan trigger retraining (volume outcomes, degradasi performa Brier/Win Rate, atau forced manual).
2. Perakitan dataset terpadu (menggabungkan data historis dan matured outcomes dengan purges window kausal).
3. Pelatihan kandidat challenger model (LightGBM/Logistic terkalibrasi).
4. Evaluasi gerbang promosi otomatis berbasis `ModelComparator` Phase 10.
5. Promosi champion atomik dan kapabilitas rollback deterministik ke model sebelumnya.
6. CLI orchestrator terpadu dan target Makefile.

---

## Perubahan Kode & File

### 1. `python/models/registry.py`
- **Validasi Status (`ModelMetadata.validate_status`):**
  - Memperluas status yang diizinkan: `"champion"`, `"challenger"`, `"archived_champion"`, dan `"retired"`.
- **Dukungan Demote Otomatis (`ModelRegistry.promote_to_champion`):**
  - Menambahkan parameter `demote_to: str = "challenger"` (default tetap menjaga kompatibilitas pengujian sebelumnya) dan mendukung demosi ke `"archived_champion"`.
- **Method Rollback Champion (`ModelRegistry.rollback_champion`):**
  - Mengembalikan status champion ke target versi yang ditentukan atau otomatis mencari archived champion terakhir. Champion saat ini didemosikan menjadi `"retired"`.

### 2. `python/retraining/trigger.py` (File Baru)
- **`RetrainingTriggerConfig`:**
  - Konfigurasi ambang volume (`min_matured_samples = 200`), ukuran rolling window (`rolling_window_size = 50`), batas keselamatan Brier (`brier_safety_floor = 0.25`), dan batas keselamatan Win Rate (`win_rate_safety_floor = 0.45`).
- **`RetrainingTriggerResult`:**
  - Data class hasil evaluasi trigger: `should_retrain`, `reasons`, `matured_count`, `rolling_brier`, `rolling_win_rate`, dan `evaluated_at`.
- **`RetrainingTriggerEvaluator`:**
  - Mengevaluasi apakah retraining harus dijalankan berdasarkan:
    1. Operator forced manual trigger (`force=True`).
    2. Volume trigger: akumulasi matured outcomes $\ge$ threshold.
    3. Degradasi performa: rolling win rate $<$ floor atau rolling Brier score $>$ floor pada $k$ trade terbaru.

### 3. `python/retraining/dataset.py` (File Baru)
- **`RetrainingDatasetAssembler`:**
  - Menggabungkan data frame historis dengan matured outcomes (`outcomes_daily` + `signals_daily`).
  - Menangani deduplikasi record `(ticker, date)` di mana hasil outcome riil diprioritaskan.
  - Imputasi nilai fitur yang hilang secara median/0.0 deterministik.
  - Menegakkan `split_walk_forward` dengan `purge_days = 10` untuk mencegah lookahead data leakage antara train set dan validation/test set.

### 4. `python/retraining/gate.py` (File Baru)
- **`PromotionGateResult`:**
  - Domain class hasil evaluasi gerbang promosi: `recommendation` (`PROMOTE`, `REJECT`, `INCONCLUSIVE`), `passed`, `challenger_version`, `champion_version`, `report`, dan `rationale`.
- **`PromotionGateManager`:**
  - `evaluate_candidate`: Membandingkan challenger terhadap champion di test dataset menggunakan `ModelComparator` Phase 10. Menangani kasus bootstrap awal (langsung `PROMOTE` jika belum ada champion).
  - `promote_challenger`: Promosi atomik yang mengubah status challenger menjadi `"champion"` dan champion lama menjadi `"archived_champion"`.
  - `rollback`: Revert model champion ke versi sebelumnya secara deterministik.

### 5. `python/retraining/pipeline.py` (File Baru)
- **`RetrainingPipelineConfig` & `RetrainingPipelineResult`:**
  - Konfigurasi terpusat dan penampung hasil eksekusi pipeline.
- **`RetrainingPipeline`:**
  - Mengorkestrasi tahapan end-to-end:
    1. Evaluasi trigger -> skip jika tidak memenuhi syarat.
    2. Perakitan dataset terpadu.
    3. Split train/val/test dengan purge window 10 hari.
    4. Training model kandidat challenger (LightGBM/Logistic terkalibrasi).
    5. Penyimpanan model artifact & metadata ke `models/registry/` berstatus `"challenger"`.
    6. Evaluasi promotion gate terhadap champion saat ini.
    7. Promosi otomatis jika `--auto-promote` aktif dan gerbang terpenuhi.

### 6. `python/retraining/__init__.py`
- Mengekspor seluruh modul publik: `RetrainingTriggerConfig`, `RetrainingTriggerEvaluator`, `RetrainingTriggerResult`, `RetrainingDatasetAssembler`, `PromotionGateManager`, `PromotionGateResult`, `RetrainingPipelineConfig`, `RetrainingPipelineResult`, `RetrainingPipeline`.

### 7. `scripts/retrain_model.py` (File Baru)
- CLI Orchestrator dengan argumen:
  - `--check-trigger-only`: Cek status trigger tanpa melakukan training.
  - `--force`: Paksa retraining mengabaikan trigger.
  - `--min-matured <N>`: Ubah batas minimum sampel volume trigger.
  - `--auto-promote`: Promosikan challenger otomatis jika gerbang lolos.
  - `--dry-run`: Jalankan training dan evaluasi tanpa menyimpan artifact atau mengubah registry.
  - `--rollback-to <version>` / `--rollback`: Kembalikan model champion ke versi target atau versi sebelumnya.
  - `--algorithm`: lightgbm atau logistic.
  - `--output-format`: table, json, markdown.

### 8. `Makefile`
- Menambahkan target `retrain` dan deklarasi `.PHONY`:
  ```makefile
  retrain:
  	$(VENV_PYTHON) -m scripts.retrain_model --auto-promote
  ```

### 9. Pengujian Komprehensif
- **`tests/unit/test_retraining.py` (16 unit tests):**
  - Volume trigger reached / not reached.
  - Forced manual trigger.
  - Rolling win rate & Brier score degradation trigger.
  - Dataset assembly merging, deduplication, imputation, dan purge window enforcement.
  - Promotion gate evaluation (bootstrap, promote, reject, sample size inconclusive).
  - Atomic promotion dan rollback verification.
- **`tests/integration/test_retraining_pipeline.py` (2 integration tests):**
  - Full end-to-end retraining pipeline dari database SQLite nyata -> trigger -> assemble -> train -> gate -> promote -> rollback.
  - CLI invocation tests (`--check-trigger-only` dan `--dry-run --force`).
- **`tests/unit/test_smoke.py`:**
  - Verifikasi eksistensi seluruh file Phase 11.

---

## Testing Checklist

Berikut checklist pengujian pasca deployment yang dapat diverifikasi:

- [ ] **Pengecekan Trigger:**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --check-trigger-only --output-format table
  ```
  *Verifikasi:* Menampilkan tabel status volume matured outcomes dan rolling metrics tanpa error.

- [ ] **Dry-Run Retraining:**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --force --dry-run
  ```
  *Verifikasi:* Melatih model kandidat dan menghitung metrik evaluasi tanpa memodifikasi isi registry.

- [ ] **Full Retrain & Auto-Promotion:**
  ```powershell
  make retrain
  ```
  *Verifikasi:* Model challenger dilatih, dievaluasi terhadap champion, dan dipromosikan jika memenuhi seluruh kriteria Profit Factor, Brier, dan Drawdown.

- [ ] **Rollback Champion:**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --rollback
  ```
  *Verifikasi:* Model champion dikembalikan ke versi sebelum promosi terakhir, dan model yang didemosikan berstatus `"retired"`.

- [ ] **Lint & Test Suite:**
  ```powershell
  make lint
  make test
  ```
  *Verifikasi:* 299 tests lulus 100% dan linting ruff bersih tanpa peringatan.
