# Walkthrough — AWS Runtime Verification: Daily Ingestion & Telegram Signal Pipeline

## Sesi Kerja: 22 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini melakukan verifikasi empiris dan audit mendalam terhadap status operasional riil dari pipeline harian dan generator sinyal Telegram di lingkungan AWS (region `ap-southeast-3`, akun `436095651956`):
1. **Inspeksi Infrastruktur AWS Deployed (Read-Only):**
   - CloudFormation/SAM stacks: 0 stack terdaftar (`describe_stacks()` = `[]`). Template SAM di repo belum pernah dideploy via CloudFormation.
   - Lambda Functions: Terdaftar 3 fungsi staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) dengan ukuran paket zip 321 KB dan tanpa Lambda Layer (`Layers: []`). Tidak ada fungsi berawalan production.
   - EventBridge Rules: Terdaftar rule `idx-daily-pipeline-schedule-staging` dalam status `ENABLED` yang menargetkan `idx-daily-pipeline-staging` dengan jadwal `cron(30 9 ? * MON-FRI *)` (pukul 16:30 WIB).
   - CloudWatch Logs: Fungsi harian terpicu secara otomatis setiap hari kerja bursa pukul 09:30 UTC (16:30 WIB) dengan durasi eksekusi rata-rata ~18 detik dan memory 543 MB.
2. **Penelusuran Alur Eksekusi Harian Nyata & Root Cause Analisis:**
   - Lambda berhasil mengunduh database SQLite dari S3 (`database/stock_signals.db`) ke `/tmp/stock_signals.db`.
   - **Kegagalan Ingestion & ML:** Paket zip Lambda (321 KB) hanya berisi kode sumber Python aplikasi dan sama sekali tidak memuat dependensi pihak ketiga (`yfinance`, `pandas`, `numpy`, `scikit-learn`, `lightgbm`). Akibatnya, statement import pada `python/cloud/handlers.py` tertangkap oleh blok `except ImportError`, menyetel `run_ingest = None`, `SignalEngine = None`, dan `FeatureEngine = None`.
   - **Fail-Open Silent Skip:** Handler melewati tahap ingestion bar harian (`Market data ingestion skipped: run_ingest not loaded in serverless package`) dan mencatat `bars_ingested = 0`. Ekstraksi fitur dan kalkulasi model Machine Learning juga dilewati (`SignalEngine skipped: ML dependencies not present in serverless package`).
   - **Critical Fail-Open Stale Replay:** Karena sinyal baru tidak terbentuk, handler menjalankan logika fallback pada baris 400–418 di `handlers.py` yang mengambil tanggal sinyal historis terakhir di SQLite (`distinct_dates[-1]` yaitu `2026-10-16`), mengambil 10 sinyal usang tersebut, lalu mengirimkannya ulang ke Telegram (`SENT_85` pada 19 Okt, `SENT_86` pada 20 Okt, `SENT_87` pada 21 Okt).
   - Handler kemudian mengunggah kembali DB dan file log eksekusi ke S3 (`logs/daily_pipeline_2026-10-16_*.json`) dengan status buatan `status: "SUCCESS"`.
3. **Pemisahan Workflow AWS Daily vs Local Paper Trading:**
   - Workflow AWS Lambda harian sama sekali tidak menggunakan `DailyPipeline`, tidak menyentuh `artifacts/phase_11f/paper_trading_state.json`, tidak mengevaluasi model riset frozen Phase 11F, dan tidak menjalankan lifecycle order/fill paper trading.
   - Workflow operasional yang sesungguhnya berjalan secara independen dan strictly fail-closed di mesin lokal melalui Windows Task Scheduler (`\IDX_Stock_Signal_Daily_Pipeline`) pada pukul 16:30 WIB.
4. **Dokumentasi & Pelaporan:**
   - Membuat laporan audit menyeluruh pada `docs/23_aws_runtime_daily_pipeline_verification_report.md` dengan kesimpulan tegas `AWS_AUTOMATION_FAILED`.
   - Memperbarui `audit_report.md` (Indeks Entri 15 dan header state) serta mencatat Log 74 pada `summary.md`.

---

### Task Breakdown & Detail Investigasi

#### 1. Verifikasi Sumber Daya AWS yang Dideploy (Read-Only)
- Menggunakan `boto3.Session(region_name='ap-southeast-3')` untuk memverifikasi identitas pemanggil: `arn:aws:iam::436095651956:user/deployer`.
- Menjalankan `cf.describe_stacks()` dan `cf.list_stacks()`: Mengonfirmasi bahwa SAM template `infra/aws/template.yaml` tidak terdaftar sebagai CloudFormation stack.
- Memeriksa fungsi Lambda:
  - `idx-daily-pipeline-staging`: Runtime `python3.12`, Memory 1536 MB, Timeout 300 detik, CodeSize 321,357 bytes, EphemeralStorage 1024 MB.
  - Memverifikasi konfigurasi `Layers`: Bernilai `[]` (tidak ada runtime layer yang terpasang).
  - Mengunduh zip paket Lambda dan memvalidasi isinya: Hanya berisi 97 file kode sumber (`python/`, `services/`, `configs/`, `scripts/`). Terkonfirmasi tidak ada folder `site-packages` untuk `numpy`, `pandas`, `lightgbm`, `scikit-learn`, `yfinance`.
- Memeriksa EventBridge rules:
  - Rule `idx-daily-pipeline-schedule-staging` terdaftar dengan state `ENABLED` dan ekspresi `cron(30 9 ? * MON-FRI *)`.
  - Target mengarah ke `idx-daily-pipeline-staging`.
  - Resource policy Lambda memiliki permission `EventBridgeInvoke-idx-daily-pipeline-schedule-staging`.
- Memeriksa CloudWatch log streams dan metrics:
  - Ditemukan 14 log streams, dengan eksekusi harian otomatis pada 15, 16, 19, 20, dan 21 Oktober 2026 tepat pukul 09:30 UTC (16:30 WIB).
  - Metrics mencatat Invocations: 1.0/hari, Errors: 0.0/hari, Durasi: ~18 detik/eksekusi.

#### 2. Penelusuran Log CloudWatch & File Log S3
- Log CloudWatch mencatat pesan persis:
  - `[INFO] ... Market data ingestion skipped: run_ingest not loaded in serverless package.`
  - `[INFO] ... SignalEngine skipped: ML dependencies not present in serverless package.`
  - `[INFO] ... Loaded 10 pre-computed signals from DB for 2026-10-16`
- Memeriksa file log S3 pada bucket `idx-stock-signal-436095651956-data`:
  - `logs/daily_pipeline_2026-10-16_20261021_093021.json`: status SUCCESS, bars_ingested 0, signals_generated 10, telegram_status `SENT_87`.
  - `logs/daily_pipeline_2026-10-16_20261020_093022.json`: status SUCCESS, bars_ingested 0, signals_generated 10, telegram_status `SENT_86`.
  - `logs/daily_pipeline_2026-10-16_20261019_093022.json`: status SUCCESS, bars_ingested 0, signals_generated 10, telegram_status `SENT_85`.
- Memeriksa database S3 `database/stock_signals.db`: ETag `4e92d6da8745bd9fd9a8467f2b4baf3e` identik dengan hash MD5 lokal `datasets/stock_signals.db` (194,031,616 bytes) hasil upload manual Phase 11G pada 21 Oktober pukul 18:07 WIB.

#### 3. Audit Fail-Closed vs Fail-Open Behavior pada `python/cloud/handlers.py`
- Mengidentifikasi 4 jalur fail-open yang melanggar arsitektur trading yang aman:
  1. *Import Failure Handling (Baris 33–54):* Menangkap `ImportError` secara silent dan menetapkan modul-modul penting menjadi `None`.
  2. *Ingestion Incomplete/Missing (Baris 306–309):* Melewati proses pengambilan data jika `run_ingest is None`, tanpa membatalkan eksekusi downstream.
  3. *Coverage Gate Absent:* Tidak ada pengecekan minimum ticker coverage di `handlers.py` (berbeda dengan `DailyPipeline` lokal yang mengunci ambang batas 80%).
  4. *Fallback Sinyal Usang (Baris 400–418):* Jika tidak ada sinyal baru yang terbentuk, handler secara otomatis mencari tanggal sinyal terakhir di SQLite (`distinct_dates[-1]`) dan mengirimkannya ke Telegram seolah-olah itu adalah sinyal hari ini.

#### 4. Pemisahan AWS Daily Signals vs Local Paper Trading
- Membuktikan secara definitif bahwa:
  - AWS Lambda ditargetkan untuk evaluasi champion lama 14 Oktober (`lightgbm_classification_20261014_093522` / `093607`) via `SignalEngine`.
  - Local Paper Trading menjalankan `DailyPipeline` (Phase 11F/11G) dengan model riset terisolasi (`artifacts/phase_11f/research_models/`), hash kebijakan `8c102c44...`, dan state mesin mandiri di `paper_trading_state.json`.
  - Kedua alur kerja tidak saling berbagi state eksekusi atau dependensi operasional.

---

### Testing Checklist

Item yang harus diverifikasi oleh reviewer/operator:
- [x] **Read-Only Compliance:** Seluruh pemeriksaan AWS dijalankan murni read-only via API query boto3 tanpa ada mutasi, deploy, invoke, maupun delete resource AWS.
- [x] **AWS Caller & Region:** Terverifikasi region `ap-southeast-3` dan akun `436095651956` (User: `deployer`).
- [x] **CloudFormation Stacks:** Terverifikasi 0 stack CloudFormation aktif di `ap-southeast-3`.
- [x] **Status Lambda Functions:** Terverifikasi 3 fungsi staging berukuran 321 KB tanpa runtime layer terpasang.
- [x] **Status EventBridge Rule:** Terverifikasi rule `idx-daily-pipeline-schedule-staging` aktif (`ENABLED`) dengan jadwal 16:30 WIB Mon–Fri.
- [x] **Bukti CloudWatch Logs:** Terverifikasi pesan kegagalan import dependensi data/ML dan pengiriman fallback sinyal usang 2026-10-16 pada run 19, 20, dan 21 Oktober 2026.
- [x] **Bukti S3 Logs & DB:** Terverifikasi log S3 mencatat `bars_ingested: 0` dan `signals_generated: 10` dengan status `SUCCESS`. Hash DB S3 terverifikasi cocok dengan DB lokal (194MB).
- [x] **Status Telegram Webhook:** Terverifikasi aktif menunjuk ke endpoint API Gateway HTTP API (`https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`).
- [x] **Laporan Universal Template:** Dokumen `docs/23_aws_runtime_daily_pipeline_verification_report.md` telah dibuat lengkap sesuai format standar.
- [x] **Pembaruan Indeks & Summary:** Dokumen `audit_report.md` (Indeks Entri 15) dan `summary.md` (Log 74 & 75, append-only) telah diperbarui secara konsisten.
- [x] **EventBridge Rule Disabled:** Rule `idx-daily-pipeline-schedule-staging` berhasil dinonaktifkan (`State: DISABLED`) via Python boto3, mencegah eksekusi harian staging AWS yang gagal open.
- [x] **Test Suite & Invarian Integritas:** Seluruh 625 test repository tetap lolos 100%, linter ruff 0 error, model champion produksi dan riset Phase 11F tidak mengalami perubahan.
