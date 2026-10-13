# Walkthrough — Phase 12: AWS Deployment & Resilient Serverless Architecture

## Ringkasan Eksekusi
Tahap 12 (Phase 12) menyelesaikan seluruh kebutuhan deployment cloud serverless berbasis AWS untuk sistem AI Indonesian Stock Daily Signal Generator (BEI/IDX). Seluruh komponen telah disiapkan, diaudit, diperkuat dengan proteksi ketahanan (resilience: duplicate-run protection, bounded exponential backoff retry, masked failure alert via Telegram, CloudWatch billing alarm), dideploy ke lingkungan staging pada akun AWS target (`436095651956`, region `ap-southeast-3`), dan diuji secara komprehensif.

---

## 1. Rekonsiliasi Jumlah Test Repository
Sebelum dan selama deployment Phase 12, dilakukan audit rekonsiliasi jumlah pengujian unit dan integrasi:
- **Phase 0–10**: 281 tests (Domain types, data provider & validation, feature engine & leakage, triple barrier labeling, model training, risk & TP/SL, position journal, outcome engine, Telegram client/formatters, model evaluation & comparator).
- **Phase 11**: 23 tests (`tests/unit/test_retraining.py` [21 tests] + `tests/integration/test_retraining_pipeline.py` [2 tests]).
- **Phase 12 Preliminary**: 16 tests (`tests/unit/test_aws.py` [15 tests baseline] + `tests/integration/test_cloud_pipeline.py` [1 test]).
  * 15 unit tests di `test_aws.py` mencakup: kalkulasi hash SHA-256/MD5, inisialisasi basis data mandiri (bootstrapping), download database ketika ada/tidak ada di S3, upload database dengan backup bertanda waktu, WAL checkpointing sebelum sinkronisasi, sinkronisasi model dua arah dari/ke S3, handler Lambda harian dan retraining, pengemasan zip, CLI deployment dry-run, dan helper IAM/S3/Lambda/EventBridge.
  * 1 integration test di `test_cloud_pipeline.py` mencakup: siklus pipeline cloud end-to-end (download S3 -> ingest bar -> compute feature -> persistensi DB -> upload S3) dan verifikasi pemuatan ulang warm-start.
- **Phase 12 Resiliency Additions**: 9 tests baru di `tests/unit/test_aws.py`:
  * `test_mask_sensitive_error`: penyensoran Telegram bot token, AWS access keys, AWS secret access keys, dan Bearer tokens.
  * `test_dispatch_failure_alert`: verifikasi pemanggilan TelegramClient saat terjadi error pipeline.
  * `test_duplicate_run_protection_db`: pencegahan duplikasi eksekusi jika sinyal sudah ada di DB.
  * `test_duplicate_run_protection_s3_log`: pencegahan duplikasi eksekusi berbasis S3 run log.
  * `test_duplicate_run_protection_job_recovery_vs_duplicate`: pemulihan job saat run log S3 berstatus FAILED, pencegahan duplicate saat SUCCESS, dan override via force_rerun.
  * `test_market_provider_failure_retry_and_alert`: bounded exponential backoff retry (3x) dan alert dispatch saat provider gagal.
  * `test_deploy_aws_stage_support`: isolasi resource per stage pada script CLI deploy.
  * `test_ensure_billing_alarm`: otomasi konfigurasi CloudWatch metric alarm EstimatedCharges ($1.00 USD).
  * `test_lambda_retraining_handler_failure_alert`: dispatch alert Telegram darurat saat retraining pipeline gagal di cloud.
- **Total Repository Saat Ini**: **329 tests passed (100% kelulusan)**.

---

## 2. Rincian Perubahan Kode & File

### A. `python/cloud/handlers.py`
1. **Pencegahan Eksekusi Ganda & Pemulihan Job (Lines 140–225)**:
   - Memeriksa sinyal di basis data (`signals_daily`) untuk tanggal target; melewatinya (`SKIPPED_DUPLICATE`) kecuali `force_rerun=True`.
   - Menginspeksi log eksekusi S3 (`logs/daily_pipeline_{check_date}_*.json`) secara otomatis: jika menemukan log bertanda `status: SUCCESS`, eksekusi dilewati. Jika log berstatus `FAILED`, sistem tidak melewatinya, sehingga pemulihan job (job recovery) dapat berjalan otomatis.
2. **Penanganan Kegagalan Provider Data Pasar (Lines 226–285)**:
   - Mengimplementasikan perulangan retry (default 3 percobaan) dengan bounded exponential backoff (`backoff_base=1.0s`, `backoff_factor=2.0`, `max_backoff=10.0s`) saat memanggil `run_ingest()`.
   - Menangkap error fatal dan menyiarkan notifikasi alert via `dispatch_failure_alert()`.
3. **Mekanisme Peringatan Kegagalan (Failure Alert Notification, Lines 41–95, 545–555)**:
   - `mask_sensitive_error()`: menyensor Telegram token (`bot***:***`), AWS access keys (`AKIA***`), secret keys (`aws_secret_access_key=***`), dan `Bearer ***`.
   - `dispatch_failure_alert()`: menyiarkan notifikasi kegagalan terformat ke Telegram operator. Terhubung ke `lambda_daily_pipeline_handler` dan `lambda_retraining_handler`.

### B. `scripts/deploy_aws.py`
1. **CloudWatch Billing Metric Alarm Provisioning (Lines 404–442, 635–655)**:
   - Menambahkan fungsi `ensure_billing_alarm()` dan opsi CLI `--deploy-alarm`.
   - Mengkonfigurasi metric alarm `EstimatedCharges` ($1.00 USD, period 21600s / 6 jam) pada region `us-east-1` (pusat metrik billing AWS) dan region deployment `ap-southeast-3`.
2. **Dukungan Isolasi Lingkungan (Stage Support, Lines 499–555)**:
   - Menambahkan opsi CLI `--stage [dev|staging|prod]` (default: `staging`).
   - Mengisolasi penamaan fungsi Lambda (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`), IAM execution role (`idx-stock-signal-lambda-role-staging`), EventBridge schedule (`idx-daily-pipeline-schedule-staging`), dan CloudWatch alarm (`idx-stock-signal-billing-alert-staging`).
3. **Resilience Deployment & Error Detection (Lines 285–320, 444–465)**:
   - Menambahkan waiter Boto3 `function_updated` dan retry backoff mencegah `ResourceConflictException`.
   - Memperbaiki `invoke_lambda_dry_run()` agar mendeteksi `FunctionError` dari respon Lambda.

### C. `infra/aws/template.yaml`
- Menambahkan resource SAM `BillingAlertAlarm` (`AWS/Billing`, `EstimatedCharges`, Period 21600s / 6 jam, Threshold $1.00 USD, Currency USD) dan dokumentasi batas Free Tier AWS ($0.00/bulan).

### D. `tests/unit/test_aws.py` & `tests/integration/test_cloud_pipeline.py`
- Menambahkan method `get_object` pada `FakeS3Client`.
- Menambahkan 9 pengujian unit baru mencakup proteksi duplikasi, recovery, masking, alert retraining, dan provisioning alarm billing.
- Memperjelas simulasi hari berikutnya pada `test_cloud_pipeline.py` dengan parameter eksplisit `date: "2026-10-14"`.

---

## 3. Hasil Live Deployment ke AWS (Staging Environment)

Eksekusi aktual pada akun AWS target `436095651956` (region `ap-southeast-3`):
1. **S3 Bucket Creation & Data Seeding**:
   - Bucket: `idx-stock-signal-436095651956-data` (Region: `ap-southeast-3`, Versioning: Enabled, AES-256 SSE).
   - Artifacts di S3: `configs/universe/seed_universe.csv`, `database/stock_signals.db`, `models/` (LightGBM classifier champion & regression).
2. **IAM Execution Role**:
   - Role ARN: `arn:aws:iam::436095651956:role/idx-stock-signal-lambda-role-staging`.
3. **AWS Lambda Functions**:
   - Daily Pipeline: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-daily-pipeline-staging` (Python 3.12, 1536MB, timeout 300s).
   - Retraining Pipeline: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-retraining-pipeline-staging` (Python 3.12, 2048MB, timeout 600s).
4. **AWS EventBridge Schedule**:
   - Rule Name: `idx-daily-pipeline-schedule-staging` (`cron(30 9 ? * MON-FRI *)` / 16:30 WIB).
   - Target: `idx-daily-pipeline-staging`.
5. **CloudWatch Billing Alarms**:
   - `idx-stock-signal-billing-alert-staging` terpasang aktif di `us-east-1` (pusat data metrik billing AWS) dan `ap-southeast-3`. Threshold: $1.00 USD.
6. **Live Telegram Broadcast**:
   - Uji pesan terkirim ke chat `514541354` via bot `8774288238:AAEXsM9ivOv6AeTCzoNgsVRSoEFkS0QRJwQ` (Message ID: `14`).

---

## 4. Evaluasi Acceptance Criteria Phase 12

| No | Acceptance Criteria | Status | Bukti / Catatan Pengujian |
|---|---|---|---|
| 1 | **Scheduled job works** | **PASS** | EventBridge Rule `idx-daily-pipeline-schedule-staging` aktif (`cron(30 9 ? * MON-FRI *)`) dengan target `idx-daily-pipeline-staging`. |
| 2 | **Data validation works** | **PASS** | Modul `python.data.validation` memvalidasi integritas bar (OHLC consistency, finite, volume non-negatif, deduplikasi). Diverifikasi lewat `test_validation.py`. |
| 3 | **Daily Telegram arrives** | **PASS** | Uji siaran langsung berhasil terkirim ke operator chat `514541354` (message_id: 14). Format pesan diverifikasi di `test_telegram.py`. |
| 4 | **Outcome update works** | **PASS** | `OutcomeEngine` menyelesaikan sinyal aktif, mencatat TP/SL/EXPIRY, dan menyimpan snapshot harga harian. Diverifikasi di `test_outcomes.py`. |
| 5 | **Logs accessible** | **PASS** | Log diekspor ke format JSON di S3 (`s3://{bucket}/logs/daily_pipeline_{date}_{ts}.json`) dan CloudWatch Log Group `/aws/lambda/idx-daily-pipeline-staging`. |
| 6 | **Failure alert works** | **PASS** | `dispatch_failure_alert()` menyiarkan notifikasi darurat dengan masking kredensial (`mask_sensitive_error`) saat daily pipeline, retraining, atau provider gagal. Diverifikasi lewat `test_dispatch_failure_alert` dan `test_lambda_retraining_handler_failure_alert`. |
| 7 | **Duplicate-run protection works** | **PASS** | Pipeline mendeteksi sinyal di DB atau log S3 bertanda SUCCESS untuk tanggal yang sama dan mengembalikan `SKIPPED_DUPLICATE` kecuali `force_rerun=True`. Diverifikasi di `test_duplicate_run_protection_db` dan `test_duplicate_run_protection_job_recovery_vs_duplicate`. |
| 8 | **Provider failure handling works** | **PASS** | Ingestion mengimplementasikan retry backoff eksponensial (3 percobaan), menangkap error, dan memicu alert darurat. Diverifikasi di `test_market_provider_failure_retry_and_alert`. |
| 9 | **Job recovery works** | **PASS** | Kegagalan run log sebelumnya (status FAILED) tidak memblokir eksekusi berikutnya, memungkinkan retry otomatis hingga sukses. Diverifikasi di `test_duplicate_run_protection_job_recovery_vs_duplicate`. |
| 10 | **Billing alert active** | **PASS** | CloudWatch alarm `idx-stock-signal-billing-alert-staging` terkonfigurasi pada ambang batas $1.00 USD di `us-east-1` dan `ap-southeast-3`. Diverifikasi lewat Boto3 describe_alarms dan `test_ensure_billing_alarm`. |

---

## Testing Checklist
Item yang perlu diverifikasi oleh operator/pengguna pasca deployment:

- [ ] **S3 Data Bucket**: Buka AWS Console S3, pastikan bucket `idx-stock-signal-436095651956-data` ada di region `ap-southeast-3` dan berisi `database/stock_signals.db` serta `models/`.
- [ ] **Lambda Functions**: Buka AWS Console Lambda, verifikasi fungsi `idx-daily-pipeline-staging` dan `idx-retraining-pipeline-staging` berstatus `Active`.
- [ ] **EventBridge Schedule**: Pastikan rule `idx-daily-pipeline-schedule-staging` aktif pada jadwal `cron(30 9 ? * MON-FRI *)`.
- [ ] **Telegram Bot**: Pastikan notifikasi uji coba `🔔 Phase 12 Staging Test: Berhasil.` telah diterima di aplikasi Telegram (chat id: `514541354`).
- [ ] **CloudWatch Billing Alarm**: Pastikan metric alarm `idx-stock-signal-billing-alert-staging` terdaftar pada CloudWatch Alarms (region `us-east-1` dan `ap-southeast-3`) dengan threshold $1.00 USD.
- [ ] **Container Packaging (Jika Diperlukan untuk Production Managed Dependencies)**: Untuk deployment kontainer penuh tanpa mock dependencies, deploy image ECR berbasis `infra/aws/Dockerfile`.
