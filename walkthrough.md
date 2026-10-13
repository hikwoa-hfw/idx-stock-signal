# Walkthrough — Phase 12: Cloud Deployment, Serverless Architecture & AWS S3 Sync

## Ringkasan Pekerjaan
Mengimplementasikan arsitektur serverless cloud deployment ($0/month Free Tier) untuk sistem AI Indonesian Stock Daily Signal Generator (BEI/IDX). 

Sistem mengadopsi model **AWS Lambda + S3 Database Two-Way Sync + EventBridge Scheduler**:
1. **S3 Cloud Storage Sync Layer (`python/cloud/s3_sync.py`)**:
   - Sinkronisasi dua arah file basis data SQLite (`stock_signals.db`) dan model ML artifact antara S3 bucket (`idx-stock-signal-436095651956-data`) dan storage ephemeral Lambda (`/tmp`).
   - Integritas data diverifikasi menggunakan checksum SHA-256 dan MD5.
   - Pembuatan cadangan otomatis bertanda waktu ke `database/backups/stock_signals_{timestamp}.db` setiap kali database diunggah.
   - Inisialisasi otomatis (bootstrapping) skema tabel SQLite (`daily_bars`, `signals_daily`, `outcomes_daily`, `positions_journal`) secara mandiri jika file basis data belum ada di S3.
2. **AWS Lambda Pipeline Handlers (`python/cloud/handlers.py`)**:
   - `lambda_daily_pipeline_handler`: mengeksekusi 7 langkah siklus harian secara kausal:
     * Langkah 1: Unduh SQLite DB dan model champion dari S3 ke `/tmp`.
     * Langkah 2: Ingest bar pasar hari ini via `YFinanceMarketDataProvider`.
     * Langkah 3: Evaluasi dan selesaikan open outcomes serta update snapshots via `OutcomeEngine`.
     * Langkah 4: Ekstraksi fitur dan generate sinyal Top-N harian via `SignalEngine`.
     * Langkah 5: Format dan siarkan laporan sinyal ke Telegram via `TelegramClient`.
     * Langkah 6: Unggah basis data SQLite yang diperbarui beserta cadangannya kembali ke S3.
     * Langkah 7: Kembalikan ringkasan eksekusi terstruktur dalam format JSON.
   - `lambda_retraining_handler`: mengevaluasi trigger retraining otomatis, melatih model challenger, mengevaluasi gerbang promosi champion-challenger, dan menyinkronkan artifact model yang dipromosikan ke S3.
3. **Infrastructure as Code (IaC) AWS SAM (`infra/aws/template.yaml`)**:
   - S3 Bucket: `idx-stock-signal-436095651956-data` (enkripsi AES-256, versioning aktif, blokir akses publik, lifecycle rule kadaluarsa cadangan 90 hari).
   - IAM Execution Role: Least-privilege policy untuk S3, CloudWatch Logs, dan SSM.
   - Lambda Function `DailyPipelineFunction`: Python 3.12, 1536 MB, timeout 300s, ephemeral storage 1024 MB.
   - EventBridge Scheduler Rule: `cron(30 9 ? * MON-FRI *)` (Senin-Jumat 16:30 WIB / 09:30 UTC).
   - Lambda Function `RetrainingPipelineFunction`: Python 3.12, 2048 MB, timeout 600s.
   - CloudWatch Log Groups dengan retensi 30 hari dan CloudWatch Alarm untuk error Lambda.
4. **Boto3 Provisioning & Deployment Script (`scripts/deploy_aws.py`)**:
   - Script mandiri tanpa dependensi eksternal selain `boto3`.
   - Mengemas kode aplikasi (`python/`, `services/`, `configs/`, `scripts/`) ke dalam memory zip (~140 KB).
   - Mendukung opsi `--dry-run`, `--create-bucket`, `--deploy-lambda`, `--test-invoke`.
   - Idempotent: memverifikasi atau membuat bucket, IAM role, fungsi Lambda, dan aturan EventBridge.
5. **Container Support (`infra/aws/Dockerfile`) & Makefile**:
   - Dockerfile berbasis `public.ecr.aws/lambda/python:3.12` untuk opsi deployment berbasis container image.
   - Target `deploy` ditambahkan pada `Makefile`.

---

## Perubahan Kode & File

### 1. `python/cloud/s3_sync.py`
- `compute_file_sha256(file_path)` & `compute_file_md5(file_path)`: kalkulasi checksum integritas data chunk 64KB.
- `bootstrap_database(local_path)`: menginisialisasi skema SQLite lengkap (`DailyBarRepository`, `FeatureRepository`, `LabelRepository`, `SignalRepository`, `OutcomeRepository`, `PositionJournalRepository`) secara lokal jika belum ada di S3.
- `download_database(s3_bucket, local_path, s3_key, s3_client)`: mengunduh DB dari S3 jika ada, atau memicu bootstrapping jika objek belum ditemukan (404/NoSuchKey).
- `upload_database(s3_bucket, local_path, s3_key, create_backup, s3_client)`: mengunggah DB dengan metadata SHA-256 dan membuat backup bertanda waktu di `database/backups/`.
- `sync_models_from_s3(s3_bucket, local_dir, s3_prefix, s3_client)` & `sync_models_to_s3(s3_bucket, local_dir, s3_prefix, s3_client)`: menyinkronkan artifact model machine learning secara rekursif.

### 2. `python/cloud/handlers.py`
- `lambda_daily_pipeline_handler(event, context)`:
  - Mengorkestrasi pipeline harian: S3 Sync -> Ingestion -> Outcome Resolution -> Signal Generation -> Telegram Broadcast -> S3 Upload.
  - Membaca konfigurasi dari `event` dengan fallback ke variabel lingkungan dan `python.config.settings`.
  - Penanganan eksepsi terstruktur dengan respons status code 200 (sukses) atau 500 (gagal).
- `lambda_retraining_handler(event, context)`:
  - Mengorkestrasi retraining model, trigger evaluation, dan promosi champion-challenger di Lambda.
  - Menyinkronkan artifact champion baru ke S3 saat promosi disetujui.

### 3. `python/cloud/__init__.py`
- Mengekspor modul-modul sinkronisasi S3 dan AWS Lambda handlers.

### 4. `infra/aws/template.yaml`
- AWS SAM / CloudFormation template lengkap:
  - S3 Data Bucket dengan enkripsi AES-256, versioning, dan aturan lifecycle.
  - Least-privilege IAM Execution Role.
  - Daily Pipeline Lambda Function dengan EventBridge trigger `cron(30 9 ? * MON-FRI *)`.
  - Retraining Pipeline Lambda Function.
  - CloudWatch Log Groups & Error Alarm.

### 5. `scripts/deploy_aws.py`
- Script deployment otomatis menggunakan Boto3:
  - `build_lambda_zip()`: mengemas kode aplikasi ke zip dalam memori.
  - `ensure_s3_bucket()`: memastikan keberadaan S3 bucket di region target (`ap-southeast-3`).
  - `seed_s3_data()`: mengunggah seed universe CSV, initial DB, dan model ke S3.
  - `ensure_iam_role()`: memastikan keberadaan IAM execution role dan inline policy.
  - `deploy_lambda_function()`: membuat atau memperbarui fungsi Lambda.
  - `setup_eventbridge_schedule()`: mengonfigurasi schedule rule dan izin invokasi Lambda.
  - `invoke_lambda_dry_run()`: menguji invokasi fungsi Lambda dalam mode dry-run.

### 6. `infra/aws/Dockerfile`
- Container packaging untuk AWS Lambda Python 3.12 runtime.

### 7. `Makefile`
- Menambahkan target `deploy` ke deklarasi `.PHONY` dan aturan pembuatan:
  ```makefile
  deploy:
  	$(VENV_PYTHON) -m scripts.deploy_aws --deploy-lambda
  ```

### 8. `requirements.txt` & `pyproject.toml`
- Menambahkan dependensi `boto3>=1.34.0`.

### 9. Pengujian
- `tests/unit/test_aws.py` (10 unit tests):
  - Uji hash SHA-256 dan MD5.
  - Uji bootstrap basis data SQLite.
  - Uji download DB saat ada di S3.
  - Uji download DB saat tidak ada di S3 (pemicu bootstrap).
  - Uji upload DB dan pembuatan backup bertanda waktu.
  - Uji error handling saat file lokal tidak ditemukan.
  - Uji dua arah `sync_models_from_s3` dan `sync_models_to_s3`.
  - Uji keberhasilan `lambda_daily_pipeline_handler`.
  - Uji penanganan error `lambda_daily_pipeline_handler` (respons status 500).
  - Uji `lambda_retraining_handler` dalam mode skipped.
  - Uji pembentukan zip packaging Lambda.
  - Uji CLI `deploy_aws.py --dry-run`.
  - Uji helper provisioning IAM, S3, Lambda, dan EventBridge.
- `tests/integration/test_cloud_pipeline.py`:
  - Siklus end-to-end simulasi eksekusi Lambda: download/bootstrap DB, ingest bar mock, resolve outcome, generate sinyal, siarkan Telegram mock, upload DB ke mock S3, dan verifikasi konsistensi DB pada invokasi berikutnya (warm start).
- `tests/unit/test_smoke.py`:
  - Menambahkan verifikasi keberadaan file-file deliverables Phase 12.

---

## Testing Checklist

Setelah melakukan deployment ke akun AWS target (`436095651956`), pengguna disarankan untuk memverifikasi item-item berikut:

- [ ] **1. Verifikasi Kredensial & Identitas AWS**:
  - Jalankan `aws sts get-caller-identity` atau verifikasi profil `deployer` di region `ap-southeast-3`.
- [ ] **2. Verifikasi Dry-Run Deployment**:
  - Jalankan `python -m scripts.deploy_aws --dry-run` dan pastikan seluruh resource yang akan dibuat/diupdate terdaftar dengan benar tanpa error.
- [ ] **3. Pembuatan S3 Bucket & Seeding Data**:
  - Jalankan `python -m scripts.deploy_aws --create-bucket`.
  - Verifikasi di AWS Console / CLI bahwa bucket `idx-stock-signal-436095651956-data` telah terbuat dengan enkripsi AES256 dan versioning aktif.
  - Verifikasi file `configs/universe/seed_universe.csv` telah terunggah ke S3.
- [ ] **4. Deployment Lambda Functions & EventBridge Schedule**:
  - Jalankan `make deploy` atau `python -m scripts.deploy_aws --deploy-lambda`.
  - Verifikasi fungsi `idx-daily-pipeline` dan `idx-retraining-pipeline` telah terdaftar di AWS Lambda Console.
  - Verifikasi role `idx-stock-signal-lambda-role` terpasang dengan kebijakan least-privilege ke bucket data.
  - Verifikasi aturan EventBridge `idx-daily-pipeline-schedule` aktif dengan jadwal `cron(30 9 ? * MON-FRI *)` (pukul 16:30 WIB).
- [ ] **5. Uji Invokasi Test (Dry-Run Invoke)**:
  - Jalankan `python -m scripts.deploy_aws --test-invoke`.
  - Periksa log CloudWatch `/aws/lambda/idx-daily-pipeline` dan pastikan status respons bernilai `200` dengan `"status": "SUCCESS"`.
- [ ] **6. Verifikasi Notifikasi Siaran Telegram**:
  - Jalankan pengujian invokasi dengan `dry_run=False` (atau tunggu jadwal EventBridge pukul 16:30 WIB) dan pastikan pesan sinyal harian terkirim ke chat ID `514541354`.
- [ ] **7. Verifikasi Backup S3**:
  - Periksa bucket S3 pada prefix `database/backups/` dan pastikan file backup SQLite bertanda waktu tersimpan setelah eksekusi pipeline harian.
- [ ] **8. Verifikasi Keseluruhan Test Suite Lokal**:
  - Jalankan `make test` dan pastikan 100% test lulus (318 passed).
  - Jalankan `make lint` dan pastikan linter bersih tanpa error (`All checks passed!`).
