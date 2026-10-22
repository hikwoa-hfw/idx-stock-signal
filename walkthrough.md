# Walkthrough — AWS Daily Signal Pipeline: Critical Fail-Open Remediation & Staging ML Layer Deployment

## Sesi Kerja: 22 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini menyelesaikan secara tuntas remediasi kerentanan fail-open pada AWS Daily Signal Pipeline (`idx-daily-pipeline-staging`), membangun paket dependensi Machine Learning mandiri berbasis Lambda Layer dengan optimasi batas 250 MB dan OpenMP runtime, melakukan deployment ke staging Lambda di AWS Jakarta (`ap-southeast-3`), serta memverifikasi eksekusi runtime nyata secara terkontrol:
1. **Priority 1 (Containment):**
   - Memverifikasi EventBridge rule `idx-daily-pipeline-schedule-staging` tetap berstatus `DISABLED` di region `ap-southeast-3`.
   - Memverifikasi Windows Task Scheduler lokal `\IDX_Stock_Signal_Daily_Pipeline` tetap utuh dalam status `Ready` dan terjadwal pukul 16:30 WIB tanpa gangguan.
2. **Priority 2 (Fail-Closed Correction):**
   - Menghapus secara permanen logika fallback query sinyal historis (`lookup_date = distinct_dates[-1]`) pada `python/cloud/handlers.py`.
   - Mengimplementasikan gerbang dependensi wajib (`run_ingest`, `FeatureEngine`, `SignalEngine`) yang langsung menggagalkan eksekusi jika tidak termuat.
   - Mengimplementasikan gerbang minimum cakupan ticker 80% (`min_ticker_coverage`) dan validasi bar segar (0 bars memicu fail-closed).
   - Memisahkan pelaporan status sub-tahapan (`ingestion_success`, `feature_success`, `scoring_success`, `telegram_delivery`, `database_upload`, dan peta detail `stages`).
   - Membuat 6 regression tests pada `tests/unit/test_fail_closed_pipeline.py` yang membuktikan sinyal usang mustahil disiarkan jika terjadi kegagalan upstream.
3. **Priority 3 (Deployment Packaging & Lambda Layer):**
   - Membangun tool reproduksibel `scripts/build_lambda_layer.py` untuk mengunduh wheel manylinux cp312 (`pandas`, `numpy`, `scipy`, `scikit-learn`, `lightgbm`, `joblib`, `yfinance<1.0.0`, `pydantic`).
   - Menerapkan pemangkasan selektif (test suites, caches, Cython sources `.h`/`.pyx`/`.c`, dan file dokumentasi `.md`/`.rst`), dengan tetap melindungi modul runtime wajib `numpy.testing`.
   - Membundel pustaka OpenMP `libgomp.so.1` (dari `scikit_learn.libs`) ke `/opt/lib` untuk mendukung dynamic linking LightGBM pada Amazon Linux 2023.
   - Metrik Layer: Ukuran uncompressed 246.6 MB (di bawah batas absolut AWS 250 MB / 262,144,000 bytes); ukuran arsip zip 79.5 MB.
   - Mempublikasikan versi layer ke AWS: `arn:aws:lambda:ap-southeast-3:436095651956:layer:idx-ml-dependencies-staging:3`.
   - Memperbarui `infra/aws/template.yaml` dan `scripts/deploy_aws.py` untuk mengintegrasikan layer, mengonfigurasi `PYTHONPATH` dan `LD_LIBRARY_PATH`, serta mengunci `schedule-state` agar tidak mengaktifkan kembali rule yang sedang dinonaktifkan.
4. **Priority 4 (Controlled Runtime Verification on Staging):**
   - Melakukan deployment kode dan layer ke `idx-daily-pipeline-staging` dan `idx-retraining-pipeline-staging`.
   - *Negative Test:* Menjalankan payload uji dengan cakupan parsial 5/208 ticker (2.4% < 80.0%). Lambda secara fail-closed mengembalikan HTTP 500 `FAILED` dengan pesan `Insufficient ticker coverage for 2026-10-22: 2.4% < 80.0% (5/208 tickers). Fail-closed.`, tanpa memicu scoring dan tanpa menyiarkan sinyal usang ke Telegram.
   - *Positive Test:* Menjalankan payload uji terkontrol dengan 5 ticker universe (cakupan 100%). Seluruh pipeline berjalan tuntas hingga menghasilkan HTTP 200 `SUCCESS`:
     - Ingestion: 50 bar segar untuk 22 Oktober 2026 (`ingestion_success: true`).
     - Features: 4,520 fitur dihitung (`feature_success: true`).
     - Scoring: 5 sinyal baru dihitung oleh model LightGBM (`scoring_success: true`).
     - Durasi eksekusi: 4.43 detik; Memory terpakai: 1031 MB (dari alokasi 1536 MB).
   - Memverifikasi bahwa model champion produksi dan model riset Phase 11F serta `paper_trading_state.json` tetap utuh.
   - EventBridge schedule tetap `DISABLED` hingga disetujui untuk diaktifkan kembali.

---

### Task Breakdown & Detail Perubahan Kode

#### 1. `python/cloud/handlers.py`
- **Baris 6–7:** Menambahkan import `sys` dan konfigurasi path `/opt/lib:/var/task`.
- **Baris 35–38:** Menambahkan penyisipan jalur `/opt/python`, `/opt/python/lib/python3.12/site-packages`, dan `/var/task` ke `sys.path`.
- **Baris 44–55:** Menambahkan logging diagnostik detail pada blok `except ImportError` untuk menangkap error impor dependensi secara transparan.
- **Baris 150–165:** Menambahkan gerbang dependensi fail-closed di awal `lambda_daily_pipeline_handler`: jika `run_ingest`, `FeatureEngine`, atau `SignalEngine` bernilai `None`, langsung melempar `RuntimeError`.
- **Baris 340–370:** Memperbaiki penanganan provider gagal, validasi 0 bars, dan penegakan batas cakupan ticker minimum 80% (`min_ticker_coverage`).
- **Baris 375–410:** Memastikan eksepsi pada tahap kalkulasi fitur langsung dilempar (fail-closed) alih-alih diabaikan.
- **Baris 415–435:** Memastikan ketiadaan sinyal tanggal target langsung memicu error fail-closed; **menghapus secara total query fallback sinyal usang (`distinct_dates[-1]`)**.
- **Baris 460–585:** Memperinci pelaporan status per tahap (`stages_record`), memperbaiki akuntansi boolean (`telegram_delivery = False` dan `database_upload = False` saat diskip), menambahkan info log sukses di CloudWatch, dan mengunggah log `FAILED` ke S3 menggunakan `s3_bucket` yang diangkat ke luar `try` agar aman untuk pemanggilan EventBridge.
- **Baris 680–695:** Menambahkan gerbang dependensi fail-closed pada `lambda_retraining_handler`.

#### 2. `scripts/ingest_daily.py`
- **Baris 44–46, 56–73:** Menambahkan parameter `base_date` pada instansiasi `MockMarketDataProvider` (`base_date = end_date or today`) agar data sintetik uji selalu relevan dengan tanggal target pengujian.

#### 3. `scripts/build_lambda_layer.py` (File Baru)
- **Baris 16–25:** Mendefinisikan paket dependensi layer: `pandas>=2.2.0`, `numpy>=1.26.0`, `scipy>=1.13.0`, `scikit-learn>=1.4.0`, `lightgbm>=4.0.0`, `joblib>=1.3.0`, `yfinance>=0.2.38,<1.0.0`, `pydantic>=2.7.0`.
- **Baris 28–56:** Fungsi `prune_layer_directory`: memangkas test, cache, header Cython, dan file dokumentasi, dengan tetap mempertahankan modul wajib `numpy/testing`.
- **Baris 108–117:** Membundel pustaka OpenMP `libgomp.so.1` dari wheel `scikit_learn.libs` ke dalam direktori layer `lib/libgomp.so.1`.
- **Baris 120–135:** Memvalidasi batas uncompressed 250 MB dan membuat zip kompresi DEFLATED.
- **Baris 140–185:** Fungsi `publish_ml_dependencies_layer`: mengunggah arsip ke S3 (`layers/`) dan memanggil `publish_layer_version` di `ap-southeast-3`.

#### 4. `scripts/deploy_aws.py`
- **Baris 268–360:** Memperbarui `deploy_lambda_function` untuk menerima parameter `layers: Optional[list[str]] = None`, meneruskannya ke `create_function` dan `update_function_configuration`.
- **Baris 365–385:** Memperbarui `setup_eventbridge_schedule` untuk menerima parameter `state` dan secara default mempertahankan status aturan yang ada (`PRESERVE`), sehingga rule `DISABLED` tidak sengaja menjadi `ENABLED`.
- **Baris 479–490:** Memperbarui `invoke_lambda_dry_run` agar menerima custom payload dictionary.
- **Baris 791–802:** Menambahkan argumen CLI `--layer-arn` dan `--schedule-state` (choices: `ENABLED`, `DISABLED`, `PRESERVE`).
- **Baris 870–895:** Menambahkan logika resolusi otomatis layer ARN versi terbaru untuk stage target (`idx-ml-dependencies-{stage}`).
- **Baris 900–915:** Menambahkan `LD_LIBRARY_PATH` (`/opt/lib:/var/task`) dan memperluas `PYTHONPATH` pada variabel environment Lambda.

#### 5. `infra/aws/template.yaml`
- **Baris 32–37:** Menambahkan parameter `ScheduleEnabled` (default `'false'`).
- **Baris 145–155:** Mendefinisikan resource `MlDependenciesLayer` (`AWS::Serverless::LayerVersion`) dengan konten `artifacts/layers/ml_dependencies_layer.zip`.
- **Baris 160–180:** Menyematkan `Layers: [!Ref MlDependenciesLayer]` pada `DailyPipelineFunction` dan `RetrainingPipelineFunction`, serta menyetel properti `Enabled: !Ref ScheduleEnabled` pada jadwal EventBridge.
- **Baris 268–272:** Menambahkan output `MlDependenciesLayerArn`.

#### 6. `tests/unit/test_fail_closed_pipeline.py` (File Baru)
- Menambahkan 7 unit test regresi:
  1. `test_fail_closed_missing_ingest_dependency`: membuktikan ketiadaan dependensi memicu HTTP 500 `FAILED`.
  2. `test_fail_closed_provider_failure`: membuktikan kegagalan koneksi provider memicu HTTP 500 `FAILED`.
  3. `test_fail_closed_zero_bars_and_low_coverage`: membuktikan 0 bars / cakupan rendah memicu HTTP 500 `FAILED`.
  4. `test_fail_closed_feature_generation_error`: membuktikan error pada ekstraksi fitur memicu HTTP 500 `FAILED`.
  5. `test_fail_closed_scoring_error`: membuktikan error pada scoring model memicu HTTP 500 `FAILED`.
  6. `test_stale_signals_never_broadcast_on_upstream_failure`: membuktikan database yang berisi sinyal usang 2026-10-16 tidak akan pernah disiarkan ke Telegram jika terjadi kegagalan upstream, dan log S3 bertuliskan `FAILED`.
  7. `test_fail_closed_s3_failure_log_with_env_var_bucket`: membuktikan log kegagalan S3 tetap terunggah saat bucket dikonfigurasi melalui environment variable (`S3_BUCKET`).

---

### Hasil Verifikasi & Ringkasan Pengujian

| Komponen | Perintah / Uji | Hasil | Status |
|---|---|---|---|
| Priority 1: EventBridge Schedule | `events.describe_rule(Name='idx-daily-pipeline-schedule-staging')` | `State: DISABLED` | PASS |
| Priority 1: Windows Task Scheduler | `Get-ScheduledTask -TaskName 'IDX_Stock_Signal_Daily_Pipeline'` | `State: Ready`, Next: 16:30 WIB | PASS |
| Priority 2: Fail-Closed Pipeline Tests | `.venv\Scripts\pytest tests/unit/test_fail_closed_pipeline.py` | 7/7 passed (100%) | PASS |
| Priority 2: Cloud & Pipeline Test Suite | `.venv\Scripts\pytest tests/unit/test_aws.py tests/integration/test_cloud_pipeline.py` | 40/40 passed (100%) | PASS |
| Priority 3: Lambda Layer Build | `scripts/build_lambda_layer.py --publish` | Layer v3 diterbitkan (246.6 MB uncompressed, libgomp bundled) | PASS |
| Priority 4: Staging Lambda Deployment | `scripts/deploy_aws.py --deploy-lambda --stage staging` | Berhasil dideploy dengan layer v3 terpasang, rule tetap `DISABLED` | PASS |
| Priority 4: Controlled Negative Test | Invoke Lambda dengan coverage < 80% | HTTP 500 `FAILED` (`Insufficient ticker coverage`), log S3 terunggah | PASS |
| Priority 4: Controlled Positive Test | Invoke Lambda dengan coverage 100% | HTTP 200 `SUCCESS` (50 bars, 4520 features, 5 signals LightGBM) | PASS |
| Linter Kebersihan Kode | `.venv\Scripts\ruff check .` | All checks passed (0 error) | PASS |
| Total Test Suite Repositori | `.venv\Scripts\pytest -q` | 632/632 passed (100% pass rate) | PASS |
| Invarian Model & State | `git status` model/research/paper trading state | Untouched / Bersih | PASS |

---

### Testing Checklist

Item yang harus diverifikasi oleh reviewer/operator:
- [x] **EventBridge Rule State:** Memastikan rule `idx-daily-pipeline-schedule-staging` di AWS `ap-southeast-3` tetap berstatus `DISABLED` (tidak terpicu otomatis sebelum persetujuan).
- [x] **Local Task Scheduler Invariant:** Memastikan task `\IDX_Stock_Signal_Daily_Pipeline` pada host lokal berstatus `Ready` dan menjadi satu-satunya pipeline aktif harian.
- [x] **Fail-Closed Code Review:** Memeriksa `python/cloud/handlers.py` bahwa query sinyal historis `lookup_date = distinct_dates[-1]` telah dihapus total.
- [x] **Coverage & Dependency Gates:** Memeriksa bahwa ketiadaan dependensi ML atau cakupan ticker $< 80\%$ langsung menggagalkan eksekusi dengan status `FAILED`.
- [x] **Lambda Layer Status:** Memverifikasi layer `arn:aws:lambda:ap-southeast-3:436095651956:layer:idx-ml-dependencies-staging:3` terpasang pada `idx-daily-pipeline-staging`.
- [x] **OpenMP Runtime Compatibility:** Memverifikasi file `libgomp.so.1` ada di dalam direktori `lib/` layer dan LightGBM berhasil diimpor tanpa error `libgomp.so.1: cannot open shared object file`.
- [x] **CloudWatch Logs Verification:** Memverifikasi log CloudWatch staging mencatat eksekusi sukses ingestion 50 bars, 4,520 fitur, dan 5 sinyal baru tanggal `2026-10-22` tanpa error import.
- [x] **Dokumentasi Terbarui:** Memeriksa bahwa `docs/23_aws_runtime_daily_pipeline_verification_report.md` (Bagian 12), `audit_report.md` (Indeks Entri 15), dan `summary.md` (Log 76) telah memuat dokumentasi lengkap.
- [x] **Test Suite & Linter:** Seluruh 632 test di repositori passed (100%) dan `ruff check .` bersih 0 error.
