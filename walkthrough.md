# Walkthrough — Phase 12: AWS Deployment & Resilient Serverless Architecture

## Ringkasan Eksekusi
Tahap 12 (Phase 12) menyelesaikan seluruh kebutuhan deployment cloud serverless berbasis AWS untuk sistem AI Indonesian Stock Daily Signal Generator (BEI/IDX). Seluruh komponen telah disiapkan, diaudit, diperkuat dengan proteksi ketahanan (resilience), dideploy ke lingkungan staging pada akun AWS target (`436095651956`, region `ap-southeast-3`), dan diuji secara komprehensif.

---

## 1. Rekonsiliasi Jumlah Test Repository
Sebelum deployment Phase 12, dilakukan audit rekonsiliasi jumlah pengujian unit dan integrasi:
- **Phase 0–10**: 281 tests (Domain types, data provider & validation, feature engine & leakage, triple barrier labeling, model training, risk & TP/SL, position journal, outcome engine, Telegram client/formatters, model evaluation & comparator).
- **Phase 11**: 23 tests (`tests/unit/test_retraining.py` [21 tests] + `tests/integration/test_retraining_pipeline.py` [2 tests]).
- **Phase 12 Preliminary**: 16 tests (`tests/unit/test_aws.py` [15 tests baseline] + `tests/integration/test_cloud_pipeline.py` [1 test]).
  * 15 unit tests di `test_aws.py` mencakup: kalkulasi hash SHA-256/MD5, inisialisasi basis data mandiri (bootstrapping), download database ketika ada/tidak ada di S3, upload database dengan backup bertanda waktu, WAL checkpointing sebelum sinkronisasi, sinkronisasi model dua arah dari/ke S3, handler Lambda harian dan retraining, pengemasan zip, CLI deployment dry-run, dan helper IAM/S3/Lambda/EventBridge.
  * 1 integration test di `test_cloud_pipeline.py` mencakup: siklus pipeline cloud end-to-end (download S3 -> ingest bar -> compute feature -> persistensi DB -> upload S3) dan verifikasi pemuatan ulang warm-start.
- **Phase 12 Resiliency Additions**: 6 tests baru (`test_mask_sensitive_error`, `test_dispatch_failure_alert`, `test_duplicate_run_protection_db`, `test_duplicate_run_protection_s3_log`, `test_market_provider_failure_retry_and_alert`, `test_deploy_aws_stage_support`).
- **Total Repository Saat Ini**: **326 tests passed (100% kelulusan)**.

---

## 2. Perubahan Kode & File

### A. `python/cloud/handlers.py`
1. **Pencegahan Eksekusi Ganda (Duplicate-Run Protection)**:
   - Memeriksa apakah sinyal untuk tanggal target sudah pernah tersimpan di basis data (`signals_daily`) atau log sukses S3 (`logs/daily_pipeline_{date}_...`).
   - Melewati eksekusi jika sudah ada dengan mengembalikan status `SKIPPED_DUPLICATE` kecuali flag `force_rerun=True` diberikan.
2. **Penanganan Kegagalan Provider Data Pasar (Bounded Exponential Backoff Retry)**:
   - Mengimplementasikan perulangan retry (default 3 percobaan) dengan interval eksponensial (`backoff_base=1.0s`, `backoff_factor=2.0`, `max_backoff=10.0s`) saat memanggil `run_ingest()`.
   - Menangkap kegagalan fatal provider dan menyiarkan notifikasi alert via `dispatch_failure_alert()`.
3. **Mekanisme Peringatan Kegagalan (Failure Alert Notification)**:
   - Fungsi `mask_sensitive_error(text)`: menyensor bot token Telegram (`bot***:***`) dan kredensial AWS (`AKIA***`) untuk mencegah kebocoran informasi rahasia ke kanal komunikasi.
   - Fungsi `dispatch_failure_alert()`: menyiarkan pesan darurat dengan status alert langsung ke Telegram operator saat pipeline atau proses konsumsi data mengalami kegagalan.
4. **Perbaikan Resolusi S3 Bucket**:
   - Menghormati nilai eksplisit `event["s3_bucket"] = None` agar pengujian lokal tidak tersandung pada konfigurasi default bucket jarak jauh.

### B. `infra/aws/template.yaml`
1. **CloudWatch Billing Metric Alarm**:
   - Menambahkan resource `BillingAlertAlarm` (`AWS/Billing`, `EstimatedCharges`, Period 21600s / 6 jam, Threshold $1.00 USD, Currency USD) untuk proteksi Free Tier AWS.
2. **Dokumentasi Batas Free Tier**:
   - Lambda: 1.000.000 request/bulan gratis, 3.200.000 detik komputasi gratis.
   - S3: 5 GB Standard Storage gratis, 20.000 GET dan 2.000 PUT gratis.
   - EventBridge: 14.000.000 scheduled invocation gratis.
   - Estimasi biaya bulanan: **$0.00 / bulan**.

### C. `scripts/deploy_aws.py`
1. **Dukungan Isolasi Lingkungan (Stage Support)**:
   - Menambahkan opsi CLI `--stage [dev|staging|prod]` (default: `staging`).
   - Mengisolasi penamaan fungsi Lambda (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`), IAM execution role (`idx-stock-signal-lambda-role-staging`), dan EventBridge schedule (`idx-daily-pipeline-schedule-staging`).
   - Mengatur environment variable `APP_ENV` sesuai stage yang dipilih.
2. **Pembersihan Reserved Environment Variables**:
   - Menghapus key reserved `AWS_REGION` dari deklarasi environment variable Lambda untuk mematuhi aturan AWS Lambda API.
3. **Resilience Deployment**:
   - Menambahkan Boto3 waiter `function_updated` dan retry backoff saat pembaruan kode dan konfigurasi Lambda dijalankan secara berurutan guna mengeliminasi error `ResourceConflictException`.

### D. `services/telegram/client.py`
1. **Kompatibilitas Parameter Token**:
   - Mengizinkan `token` sebagai alias kata kunci untuk `bot_token` pada `__init__`, mencegah `TypeError` saat dipanggil dari berbagai modul.

### E. `tests/unit/test_aws.py`
- Menambahkan 6 unit test baru untuk memverifikasi fitur penyensoran error, dispatch alert, proteksi duplikasi di DB dan S3, retry backoff provider, serta resolusi stage pada script deploy.

---

## 3. Hasil Live Deployment ke AWS (Staging Environment)

Eksekusi nyata pada akun AWS target `436095651956` (region `ap-southeast-3`):
1. **S3 Bucket Creation & Data Seeding**:
   - Bucket: `idx-stock-signal-436095651956-data` (Region: `ap-southeast-3`, Versioning: Enabled, AES-256 SSE).
   - Artifacts di S3:
     * `configs/universe/seed_universe.csv`
     * `database/stock_signals.db`
     * `models/lightgbm_classification_20261012_120916.joblib` (Champion Classifier)
     * `models/lightgbm_classification_20261012_120916.json`
     * Model regresi dan baseline logistik/ridge.
2. **IAM Execution Role**:
   - Role ARN: `arn:aws:iam::436095651956:role/idx-stock-signal-lambda-role-staging`
   - Policy: `AWSLambdaBasicExecutionRole` + Inline Policy `S3DataBucketAccess` ke `idx-stock-signal-436095651956-data`.
3. **AWS Lambda Functions**:
   - Daily Pipeline: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-daily-pipeline-staging` (Runtime: Python 3.12, 1536MB, timeout 300s).
   - Retraining Pipeline: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-retraining-pipeline-staging` (Runtime: Python 3.12, 2048MB, timeout 600s).
4. **AWS EventBridge Schedule**:
   - Rule Name: `idx-daily-pipeline-schedule-staging`
   - Schedule Expression: `cron(30 9 ? * MON-FRI *)` (Senin-Jumat 16:30 WIB / 09:30 UTC).
   - Target: `idx-daily-pipeline-staging`.
   - Lambda Permission: `EventBridgeInvoke-idx-daily-pipeline-schedule-staging` terpasang.
5. **Live Telegram Broadcast**:
   - Pesan verifikasi berhasil dikirimkan ke Telegram chat `514541354` via bot `8774288238:AAEXsM9ivOv6AeTCzoNgsVRSoEFkS0QRJwQ` (Message ID: `14`).

---

## 4. Evaluasi Acceptance Criteria Phase 12

| No | Acceptance Criteria | Status | Bukti / Catatan Pengujian |
|---|---|---|---|
| 1 | **Scheduled job works** | **PASS** | EventBridge Rule `idx-daily-pipeline-schedule-staging` aktif (`cron(30 9 ? * MON-FRI *)`) dengan target `idx-daily-pipeline-staging`. |
| 2 | **Data validation works** | **PASS** | Modul `python.data.validation` memvalidasi integritas bar (OHLC consistency, finite, volume non-negatif, deduplikasi). Diverifikasi lewat `test_validation.py`. |
| 3 | **Daily Telegram arrives** | **PASS** | Uji siaran langsung berhasil terkirim ke operator chat `514541354` dengan return `message_id: 14`. Format pesan diverifikasi di `test_telegram.py`. |
| 4 | **Outcome update works** | **PASS** | `OutcomeEngine` menyelesaikan sinyal aktif, mencatat TP/SL/EXPIRY, dan menyimpan snapshot harga harian. Diverifikasi di `test_outcomes.py`. |
| 5 | **Logs accessible** | **PASS** | Log diekspor ke format JSON di S3 (`s3://{bucket}/logs/daily_pipeline_{date}_{ts}.json`) dan CloudWatch Log Group `/aws/lambda/idx-daily-pipeline`. |
| 6 | **Failure alert works** | **PASS** | `dispatch_failure_alert()` menyiarkan notifikasi darurat dengan masking kredensial (`mask_sensitive_error`) saat pipeline atau provider gagal. Diverifikasi lewat `test_dispatch_failure_alert`. |
| 7 | **Duplicate-run protection works** | **PASS** | Pipeline mendeteksi keberadaan sinyal di DB atau S3 untuk tanggal yang sama dan mengembalikan `SKIPPED_DUPLICATE` kecuali `force_rerun=True`. Diverifikasi di `test_duplicate_run_protection_db`. |
| 8 | **Provider failure handling works** | **PASS** | Ingestion mengimplementasikan retry backoff eksponensial (3 percobaan), menangkap error, dan memicu alert darurat. Diverifikasi di `test_market_provider_failure_retry_and_alert`. |

---

## Testing Checklist
Item yang perlu diverifikasi oleh operator/pengguna pasca deployment:

- [ ] **S3 Data Bucket**: Buka AWS Console S3, pastikan bucket `idx-stock-signal-436095651956-data` ada di region `ap-southeast-3` dan berisi `database/stock_signals.db` serta `models/`.
- [ ] **Lambda Functions**: Buka AWS Console Lambda, verifikasi fungsi `idx-daily-pipeline-staging` dan `idx-retraining-pipeline-staging` berstatus `Active`.
- [ ] **EventBridge Schedule**: Pastikan rule `idx-daily-pipeline-schedule-staging` aktif pada jadwal `cron(30 9 ? * MON-FRI *)`.
- [ ] **Telegram Bot**: Pastikan notifikasi uji coba `🔔 Phase 12 Staging Test: Berhasil.` telah diterima di aplikasi Telegram (chat id: `514541354`).
- [ ] **CloudWatch Billing Alarm**: Pastikan metric alarm `idx-stock-signal-billing-alert-staging` terdaftar pada CloudWatch Alarms dengan threshold $1.00 USD.
- [ ] **Container Packaging (Jika Diperlukan untuk Prod)**: Untuk deployment berbasis kontainer penuh dengan semua native C dependencies, jalankan build image via `infra/aws/Dockerfile`.
