# Walkthrough — Optimasi Pipeline Ingestion Harian dan Responsivitas Webhook Bot Telegram

## Sesi Kerja: 27 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini menyelesaikan investigasi mendalam, perbaikan bug kritis, dan optimasi performa pada pipeline harian AWS Lambda (`idx-daily-pipeline-staging`) dan webhook Bot Telegram (`idx-telegram-webhook-staging`):
1. **Pangkas Retry & Timeout Yahoo Finance:** Menurunkan default retry attempts dari 4 menjadi 2, backoff menjadi `[1.0, 2.0]`, timeout menjadi 15 detik, dan menghilangkan sleep yang tidak perlu pada kegagalan percobaan terakhir di `python/data/provider.py`.
2. **Paralelisasi Unduhan & Pembatasan Lookback Inkremental:** Mengaktifkan unduhan batch paralel via `ThreadPoolExecutor(max_workers=4)` di `scripts/ingest_daily.py`, membatasi lookback window mode incremental ke maksimal 7 hari, dan mengeliminasi bug unduhan fallback 10 tahun (2016-01-01) untuk ticker yang belum tercatat atau delisted.
3. **Perbaikan Bounding Tanggal & Ticker Stale di SQLite:** Mengikat `earliest_allowed` ke `effective_end = end_date or today` (bukan `today`) dan mengunci `chunk_start = max(min(dates_needed), earliest_allowed)` sehingga ticker non-aktif/tersuspensi dengan data bertahun-tahun lalu tidak lagi menarik window unduhan satu chunk ke masa lalu.
4. **Conditional S3 Database Download & Metadata Caching:** Menambahkan mekanisme conditional download berbasis ETag, size, dan LastModified di `python/cloud/s3_sync.py` dengan validasi SQLite magic header (`b"SQLite format 3\x00"`). File basis data 200+ MB tidak lagi diunduh ulang pada setiap interaksi webhook, memangkas latensi bot Telegram dari ~10.01 detik menjadi **0.21 - 0.23 detik**.
5. **Verifikasi & Deployment:** Seluruh 636 tests (100%) lolos, linting clean, dan ketiga fungsi Lambda berhasil dideploy ke staging dengan schedule EventBridge tetap `ENABLED`.

---

### Task Breakdown & Detail Perubahan Kode

#### 1. `python/data/provider.py`
- **Baris 578–591 (`YFinanceMarketDataProvider.__init__`):**
  - Mengubah default parameter `retry_attempts` dari `4` menjadi `2`.
  - Mengubah default parameter `retry_backoff_seconds` dari `[2.0, 5.0, 10.0, 20.0]` menjadi `[1.0, 2.0]`.
- **Baris 615 (`_fetch_yfinance`):**
  - Memperpendek batas `timeout` unduhan `yf.download` dari `20` detik menjadi `15` detik.
- **Baris 659–665 (`_process_chunk` di `get_daily_bars_batch`):**
  - Mengubah kondisi retry sleep menjadi `if attempt < self.retry_attempts - 1:`, sehingga jika percobaan terakhir gagal, fungsi langsung keluar tanpa sleep sia-sia.
- **Baris 667–676 (`_process_chunk`):**
  - Membungkus `normalize_yfinance_dataframe` dalam blok fail-closed `try...except Exception:` agar anomali skema respons yfinance menghasilkan daftar bar kosong yang aman, bukan exception yang menghentikan pool.

#### 2. `scripts/ingest_daily.py`
- **Baris 4:** Menambahkan impor `from concurrent.futures import ThreadPoolExecutor`.
- **Baris 29–31 (`run_ingest` signature):**
  - Menurunkan default `lookback_days` dari `30` menjadi `7`.
  - Menambahkan parameter `max_workers: int = 4`.
- **Baris 77–82:** Meneruskan `max_workers=max_workers` saat inisialisasi `YFinanceMarketDataProvider`.
- **Baris 118–147 (`isinstance(provider, YFinanceMarketDataProvider)`):**
  - Menetapkan batas lookback incremental `incremental_lookback = min(lookback_days, 7)`.
  - Menetapkan `effective_end = end_date or today` dan `earliest_allowed = effective_end - timedelta(days=incremental_lookback)`.
  - Mengikat `chunk_start = max(min(dates_needed), earliest_allowed)` sehingga ticker yang memiliki riwayat lama tidak dapat menarik batas awal satu chunk ke bertahun-tahun lalu.
  - Ticker unseen/belum ada di basis data menggunakan fallback `earliest_allowed`, bukan `date(2016, 1, 1)`.
  - Mengambil unduhan batch antar-chunk secara konkuren menggunakan `ThreadPoolExecutor(max_workers=concurrency)`.
  - Memproses validasi bar dan penulisan SQLite (`_process_ticker_bars`) secara sekuensial pada main thread untuk menjamin thread-safety database.
- **Baris 199–222 (non-YFinance branch):**
  - Mengikat lookback incremental pada `req_start = max(latest_in_db - timedelta(days=incremental_lookback), earliest_allowed)`.
- **Baris 407–435 (CLI parser):**
  - Menambahkan argumen `--max-workers` (default 4) dan meneruskannya ke pemanggilan `run_ingest`.

#### 3. `python/cloud/s3_sync.py`
- **Baris 2:** Menambahkan impor `json`.
- **Baris 73–140 (`download_database`):**
  - Menambahkan parameter `conditional: bool = False`.
  - Jika `conditional=True` dan file lokal sudah ada dengan ukuran >= 16 bytes:
    - Memverifikasi magic header SQLite (`f.read(16) == b"SQLite format 3\x00"`). Jika corrupt, file diunduh ulang dari S3.
    - Membaca metadata cache lokal (`stock_signals.db.meta.json`).
    - Jika ETag / SHA-256 / LastModified cocok dan ukuran file sesuai, fungsi langsung mengembalikan `True` tanpa memanggil `download_file` (menghemat transfer 200+ MB).
    - Menulis file `stock_signals.db.meta.json` secara otomatis jika `is_fresh` terverifikasi lewat SHA-256 tanpa cache file sebelumnya.
- **Baris 215–228 (`upload_database`):**
  - Memperbarui file metadata cache lokal (`stock_signals.db.meta.json`) pasca upload berhasil agar cache lokal langsung tersinkronisasi.
- **Baris 265–290 (`sync_models_from_s3`):**
  - Memeriksa ukuran file lokal sebelum mengunduh. Jika ukuran file `.joblib` sudah cocok dengan ukuran remote S3, proses unduh dilewati untuk efisiensi transfer.

#### 4. `python/cloud/handlers.py`
- **Baris 202–207 (`lambda_daily_pipeline_handler`):**
  - Memanggil `download_database(..., conditional=not bool(event.get("force_sync_db", False)))`.
- **Baris 334–339 (`lambda_daily_pipeline_handler`):**
  - Meneruskan `lookback_days=int(event.get("lookback_days", 7))`, `batch_size=int(event.get("batch_size", 25))`, dan `max_workers=int(event.get("max_workers", 4))` ke `run_ingest`.
- **Baris 945–950 (`lambda_telegram_webhook_handler`):**
  - Memanggil `download_database(..., conditional=not bool(event.get("force_sync_db", False)))` sehingga container warm webhook merespons dalam hitungan milidetik tanpa redownload basis data.

#### 5. `tests/unit/test_provider.py`
- **Baris 297–316:** Menambahkan test `test_yfinance_provider_defaults_and_sleep_on_failure` untuk memvalidasi default retry attempts = 2, backoff = [1.0, 2.0], max_workers = 4, dan memastikan `time.sleep` hanya dipanggil 1 kali pada 2 percobaan gagal.

#### 6. `tests/unit/test_aws.py`
- **Baris 1 & 50–57:** Menambahkan impor `hashlib` dan atribut `ETag` pada `FakeS3Client.head_object`.
- **Baris 169–215:** Menambahkan test `test_download_database_conditional` untuk memvalidasi:
  - Unduhan pertama berhasil saat file belum ada.
  - Unduhan kedua dengan `conditional=True` berhasil melakukan cache hit tanpa memanggil `download_file`.
  - Invalidation saat isi storage S3 berubah langsung memicu unduhan ulang.
  - Deteksi file lokal korup (invalid SQLite header) langsung memicu download ulang dari S3.
  - Rekreasi file metadata cache saat SHA-256 cocok tanpa metadata sidecar.

#### 7. `tests/unit/test_daily_pipeline.py`
- **Baris 895–955:** Menambahkan test `test_run_ingest_incremental_bounded_lookback` untuk memverifikasi bahwa mode incremental membatasi lookback window ke 7 hari dan tidak pernah meminta data ke masa lalu bahkan saat basis data telah memiliki bar lama dari tahun 2020.

---

### Hasil Verifikasi & Ringkasan Pengujian

| Pengujian / Operasi | Target / Perintah | Hasil | Status |
|---|---|---|---|
| Linter Kode | `ruff check .` | 0 errors across repo | PASS |
| Unit Test Provider | `pytest tests/unit/test_provider.py` | 19/19 passed (100%) | PASS |
| Unit Test AWS Cloud | `pytest tests/unit/test_aws.py` | 40/40 passed (100%) | PASS |
| Unit Test Pipeline | `pytest tests/unit/test_daily_pipeline.py` | 24/24 passed (100%) | PASS |
| Seluruh Test Suite | `pytest -q` | 636/636 passed (100%) | PASS |
| Deployment Lambda Staging | `deploy_aws.py --deploy-lambda --stage staging --schedule-state PRESERVE` | 3 Lambda Functions updated, zip 310.0 KB, Schedule ENABLED | PASS |
| Status Webhook Telegram | `deploy_aws.py --webhook-status` | `pending_update_count: 0`, webhook aktif | PASS |
| Benchmark Webhook Cold Start | `idx-telegram-webhook-staging` (first invoke) | HTTP 200, durasi ~10.01s (bootstrap DB) | PASS |
| Benchmark Webhook Warm Container | `idx-telegram-webhook-staging` (`/help`, `/daily`) | HTTP 200, durasi **0.21s - 0.23s** (cache hit) | PASS |

---

### Testing Checklist
Setelah deployment ke lingkungan AWS staging, verifikasi butir-butir berikut di bot Telegram dan CloudWatch:

- [ ] **1. Kecepatan Respons Bot (`/help`):** Ketik `/help` di Telegram, pastikan bot merespons seketika (< 1 detik).
- [ ] **2. Kueri Sinyal Terkini (`/daily`):** Ketik `/daily` di Telegram, pastikan sinyal harian tampil lengkap dengan header tanggal 22 Oct 2026.
- [ ] **3. Kueri Tanggal Historis (`/daily 9/10/26`):** Ketik `/daily 9/10/26`, pastikan sinyal 09 Okt 2026 muncul akurat.
- [ ] **4. Eksekusi Pipeline Otomatis (Senin - Jumat 16:30 WIB):** Periksa CloudWatch log `/aws/lambda/idx-daily-pipeline-staging` setelah sesi pasar harian berikutnya, pastikan ingestion 210 ticker selesai cepat (< 90 detik) tanpa timeout 600 detik dan memori stabil di bawah 1024 MB.
- [ ] **5. Notifikasi Telegram Sinyal Harian:** Pastikan pesan rangkuman sinyal harian otomatis masuk ke Telegram chat target tepat setelah pipeline selesai.
