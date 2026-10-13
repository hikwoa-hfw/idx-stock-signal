# Walkthrough — Phase 11: Retraining Pipeline

## Ringkasan Pekerjaan
Mengimplementasikan & mengaudit secara komprehensif **Phase 11 — Retraining Pipeline** sesuai spesifikasi Sections 29, 30, 31, 32, 33, 50, dan Section 65 pada panduan pengembangan (`docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` dan `docs/03_plan_ai_stock_signal_BEI_daily.md`).

Pipeline ini mengotomatiskan siklus hidup model:
1. Pengecekan trigger retraining (volume outcomes baru terakumulasi, degradasi performa Brier/Win Rate pada rolling window pasar, atau forced manual trigger).
2. Perakitan dataset terpadu (`RetrainingDatasetAssembler`) dengan pemeliharaan fitur historis via `combine_first` dan penegakan walk-forward purge window 10 hari yang adaptif.
3. Pelatihan kandidat challenger model (LightGBM/Logistic terkalibrasi) dengan penanganan eksepsi terstruktur.
4. Evaluasi gerbang promosi otomatis berbasis `ModelComparator` Phase 10 dengan penerusan `outcome_statuses` lengkap.
5. Promosi champion atomik dan kapabilitas rollback deterministik dengan validasi kesesuaian tipe task dan proteksi status.
6. CLI orchestrator terpadu (`scripts/retrain_model.py`) dengan dukungan `--check-trigger-only`, `--force`, `--min-matured`, `--auto-promote`, `--dry-run`, `--rollback-to`, `--since-date`, `--registry-dir`, dan target Makefile.

---

## Perubahan Kode & File

### 1. `python/models/registry.py`
- **Validasi Status (`ModelMetadata.validate_status`):**
  - Mendukung status: `"champion"`, `"challenger"`, `"archived_champion"`, dan `"retired"`.
- **Dukungan Demote Otomatis (`ModelRegistry.promote_to_champion`):**
  - Menambahkan parameter `demote_to: str = "challenger"` (default menjaga kompatibilitas pengujian lama) dan mendukung demosi ke `"archived_champion"`.
- **Method Rollback Champion (`ModelRegistry.rollback_champion`):**
  - Mengembalikan status champion ke target versi yang ditentukan atau otomatis mencari archived champion terakhir.
  - Memvalidasi bahwa tipe task target model cocok dengan task yang diminta (`target_meta.task.lower() == task.lower()`), mencegah kesalahan fatal lintas-task (misal model regresi dipromosikan ke klasifikasi).
  - Memvalidasi bahwa target model belum menjadi champion aktif untuk task tersebut.
  - Champion saat ini didemosikan menjadi `"retired"`.
- **Sorting Deterministik (`ModelRegistry.list_models`):**
  - Menggunakan tie-breaker tuple `(m.created_at, m.model_version)` untuk menjamin determinisme urutan saat model memiliki timestamp identik.

### 2. `python/retraining/trigger.py`
- **`RetrainingTriggerConfig`:**
  - Konfigurasi ambang volume (`min_matured_samples = 200`), ukuran rolling window (`rolling_window_size = 50`), batas keselamatan Brier (`brier_safety_floor = 0.25`), batas keselamatan Win Rate (`win_rate_safety_floor = 0.45`), `exclude_ambiguous = True`, dan `force = False`.
- **`RetrainingTriggerResult`:**
  - Data class hasil evaluasi trigger: `should_retrain`, `reasons`, `matured_count`, `rolling_brier`, `rolling_win_rate`, dan `evaluated_at`.
- **`RetrainingTriggerEvaluator`:**
  - Memisahkan evaluasi volume baru berbasis anchor `since_date` dari rolling window degradasi performa:
    1. Operator forced manual trigger (`force=True`).
    2. Volume trigger: akumulasi matured outcomes sejak `since_date` $\ge$ threshold.
    3. Degradasi performa: rolling win rate $<$ safety floor atau rolling Brier score $>$ safety floor dievaluasi pada riwayat outcome pasar terkini secara penuh (sehingga anchor tanggal tidak memotong jendela rolling).

### 3. `python/retraining/dataset.py`
- **`RetrainingDatasetAssembler.assemble_from_dfs`:**
  - Menggabungkan data frame historis dengan matured outcomes (`outcomes_daily` + `signals_daily`).
  - Menggunakan `combine_first` berbasis index `(ticker, date)`: label dan target dari outcome riil diutamakan, namun seluruh kolom fitur non-null dari data historis tetap terjaga (mencegah fitur terhapus menjadi NaN saat snapshot outcome parsial).
  - Imputasi nilai fitur yang hilang secara median/0.0 deterministik.
- **`split_walk_forward`:**
  - Menegakkan `split_chronological` dengan `purge_days = 10` untuk mencegah kebocoran lookahead.
  - Menambahkan clamping proteksi adaptif pada `p_days` agar tidak melebihi jumlah tanggal latih yang tersedia saat dataset kecil.

### 4. `python/retraining/gate.py`
- **`PromotionGateResult`:**
  - Domain class hasil evaluasi gerbang promosi: `recommendation` (`PROMOTE`, `REJECT`, `INCONCLUSIVE`), `passed`, `challenger_version`, `champion_version`, `report`, dan `rationale`.
- **`PromotionGateManager`:**
  - `evaluate_candidate`: Membandingkan challenger terhadap champion di test dataset menggunakan `ModelComparator` Phase 10. Meneruskan `outcome_statuses` dari metadata dataset uji agar metrik status perdagangan (TP/SL/Expiry rate) terisi lengkap.
  - Menangani bootstrap awal secara otomatis (`PROMOTE` jika belum ada champion).
  - `promote_challenger`: Promosi atomik yang mengubah challenger menjadi `"champion"` dan champion lama menjadi `"archived_champion"`.
  - `rollback`: Revert model champion ke versi sebelumnya secara deterministik.

### 5. `python/retraining/pipeline.py`
- **`RetrainingPipelineConfig` & `RetrainingPipelineResult`:**
  - Konfigurasi terpusat mencakup parameter model, trigger, dan opsi `since_date`.
- **`RetrainingPipeline`:**
  - Mengorkestrasi tahapan end-to-end:
    1. Menurunkan anchor date otomatis dari champion saat ini (`champ.training_end + 1 hari`) jika `since_date` tidak disuplai secara eksplisit.
    2. Evaluasi trigger -> skip secara aman jika tidak memenuhi syarat volume/degradasi.
    3. Perakitan dataset terpadu dari DB & matured outcomes.
    4. Split train/val/test dengan purge window adaptif.
    5. Training model kandidat challenger (LightGBM/Logistic terkalibrasi).
    6. Penyimpanan model artifact & metadata ke `models/registry/` berstatus `"challenger"`.
    7. Evaluasi promotion gate terhadap champion saat ini.
    8. Promosi otomatis jika `--auto-promote` aktif dan gerbang terpenuhi.
  - Membungkus eksekusi pelatihan dan gating dalam blok `try...except` terstruktur sehingga error tak terduga dilaporkan rapi sebagai `status="FAILED"` dengan `error_message`.

### 6. `python/retraining/__init__.py`
- Mengekspor seluruh modul publik: `RetrainingTriggerConfig`, `RetrainingTriggerEvaluator`, `RetrainingTriggerResult`, `RetrainingDatasetAssembler`, `PromotionGateManager`, `PromotionGateResult`, `RetrainingPipelineConfig`, `RetrainingPipelineResult`, `RetrainingPipeline`.

### 7. `scripts/retrain_model.py`
- CLI Orchestrator dengan argumen:
  - `--check-trigger-only`: Cek status trigger tanpa melakukan training (mendukung deteksi anchor champion otomatis).
  - `--force`: Paksa retraining mengabaikan trigger.
  - `--min-matured <N>`: Ubah batas minimum sampel volume trigger.
  - `--auto-promote`: Promosikan challenger otomatis jika gerbang lolos.
  - `--dry-run`: Jalankan training dan evaluasi tanpa menyimpan artifact atau mengubah registry.
  - `--rollback-to <version>` / `--rollback`: Kembalikan model champion ke versi target atau versi sebelumnya.
  - `--since-date <YYYY-MM-DD>`: Tentukan anchor tanggal khusus untuk perhitungan volume baru.
  - `--registry-dir <path>`: Direktori registry custom untuk isolasi pengujian/multi-lingkungan.
  - `--db-url <url>`: URL database SQLite terikat ke seluruh repositori perakit data.
  - `--algorithm`: lightgbm atau logistic.
  - `--output-format`: table, json, markdown.

### 8. `Makefile`
- Menambahkan target `retrain` dan deklarasi `.PHONY`:
  ```makefile
  retrain:
  	$(VENV_PYTHON) -m scripts.retrain_model --auto-promote
  ```

### 9. Pengujian Komprehensif
- **`tests/unit/test_retraining.py` (21 unit tests):**
  - Volume trigger reached / not reached.
  - Forced manual trigger.
  - Rolling win rate & Brier score degradation trigger.
  - Degradasi performa dengan anchor `since_date` (regresi bug fixed).
  - Dataset assembly merging, deduplication, imputation, dan purge window enforcement.
  - Preservasi fitur via `combine_first` (regresi bug fixed).
  - Promotion gate evaluation (bootstrap, promote, reject, sample size inconclusive).
  - Atomic promotion dan rollback verification.
  - Rollback task mismatch validation dan active champion protection.
  - Clamping purge days pada dataset kecil.
- **`tests/integration/test_retraining_pipeline.py` (2 integration tests):**
  - Full end-to-end retraining pipeline dari database SQLite nyata -> trigger -> assemble -> train -> gate -> promote -> skip tanpa force -> rollback.
  - CLI invocation tests (`--check-trigger-only` dengan `--registry-dir` dan `--since-date`, serta `--dry-run --force`).
- **`tests/unit/test_smoke.py`:**
  - Verifikasi eksistensi seluruh file Phase 11.

---

## Testing Checklist

Berikut checklist pengujian pasca deployment yang dapat diverifikasi:

- [ ] **Pengecekan Trigger (Idle / Triggered):**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --check-trigger-only --output-format table
  ```
  *Verifikasi:* Menampilkan tabel status volume matured outcomes dan rolling metrics tanpa error runtime.

- [ ] **Pengecekan Trigger dengan Format JSON:**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --check-trigger-only --output-format json
  ```
  *Verifikasi:* Menghasilkan output JSON terstruktur yang valid dengan field `should_retrain`, `matured_count`, dan `reasons`.

- [ ] **Dry-Run Retraining:**
  ```powershell
  .venv/Scripts/python -m scripts.retrain_model --force --dry-run
  ```
  *Verifikasi:* Melatih model kandidat dan menghitung metrik evaluasi tanpa memodifikasi registry atau menyimpan artefak.

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
  *Verifikasi:* 304 tests lulus 100% dan linting ruff bersih tanpa peringatan.
