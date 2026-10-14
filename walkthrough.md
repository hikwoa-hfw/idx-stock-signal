# Walkthrough: Ingestion Data Historis BEI 3+ Tahun, Fitur & Labeling, Pelatihan Champion Dual-Mode, Sinkronisasi S3, dan Verifikasi Live

## Ringkasan Sesi
Sesi ini merealisasikan pipeline machine learning produksi ujung-ke-ujung (end-to-end) menggunakan data riil bursa saham Indonesia (BEI/IDX):
1. Mengingest **186.436 bar harian riil** (rentang 2023-01-02 hingga 2026-10-14, ~3.8 tahun) untuk 208 saham likuid BEI via Yahoo Finance.
2. Mengekstrak **186.291 baris fitur teknikal dan rezim pasar**.
3. Menghitung **185.515 label triple-barrier** (TP +5%, SL -2%, max 10 hari trading) terpisah ke dalam rezim `LOW_PRICE` (45.763 sampel) dan `HIGHER_PRICE` (137.426 sampel).
4. Melatih dan meregistrasi dua classifier Champion LightGBM terkalibrasi independen untuk masing-masing mode.
5. Mengunggah basis data SQLite (178 MB) dan artefak model ke AWS S3 bucket staging (`idx-stock-signal-436095651956-data`) dengan verifikasi integritas hash SHA-256 dan auto-backup.
6. Memperbarui dan mendeploy kode ke AWS Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`).
7. Memverifikasi respons perintah `/model` secara lokal dan langsung terhadap live API Gateway endpoint (`https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`) yang mengembalikan status dual-mode Champion dan metrik evaluasi riil.

---

## Task Breakdown & Detail Perubahan

### 1. Ingestion Data Historis Pasar Riil BEI (3+ Tahun)
- **Eksekusi:**
  - Perintah: `python -m scripts.ingest_daily --mode backfill --provider yfinance --start-date 2023-01-01 --universe-file configs/universe/seed_universe.csv --batch-size 25`
  - Hasil: Mengunduh dan memvalidasi 186.436 bar harian dari 208 ticker aktif IDX (termasuk saham liquid cap besar seperti BBCA, BBRI, BMRI, TLKM, ASII dan saham rentang rendah seperti GOTO, BUMI, DOID, BRMS, ENRG, PWON, AGRO, BKSL, dll.).
  - Integritas data tersimpan dalam tabel `daily_bars` pada `datasets/stock_signals.db`.

### 2. Pembangunan Fitur Teknikal & Label Triple-Barrier
- **Eksekusi Fitur:**
  - Perintah: `python -m scripts.build_features --save-db --limit 1`
  - Hasil: Menghasilkan 186.291 record fitur teknikal (retur 1d–20d, EMA20/50/200, RSI14, ATR14, volatilitas 20d, rasio volume, kekuatan relatif terhadap IHSG/sektor, market breadth) pada tabel `features_daily`.
- **Eksekusi Label Triple-Barrier:**
  - Perintah: `python -m scripts.build_labels --tp-pct 0.05 --sl-pct 0.02 --max-hold 10 --save-db --limit 1`
  - Hasil: 185.515 record label pada tabel `labels_daily` dengan rincian:
    - `LOW_PRICE` (Rp 50–300): 45.763 sampel.
    - `HIGHER_PRICE` (> Rp 300): 137.426 sampel.
    - `EXCLUDED_BELOW_50` (< Rp 50): 2.326 sampel.
    - Distribusi outcome: 46.537 TP, 119.329 SL, 19.649 EXPIRY.

### 3. Pelatihan Model Machine Learning Dual-Mode Champions
- **Champion `LOW_PRICE`:**
  - Perintah: `python -m scripts.train_model --mode LOW_PRICE --model-type lightgbm --task classification --set-champion --save-registry --calibrate`
  - Data: 45.763 baris pada 87 ticker (Train: 31.794 baris, Val: 5.576 baris, Test: 7.410 baris).
  - Metrik Uji (Unseen Test Data):
    - Brier Score: `0.1910`
    - Log Loss: `0.5674`
    - ROC-AUC: `0.5539`
    - Accuracy: `0.7405`
    - Calibration Error: `0.0334`
  - Versi Terdaftar: `lightgbm_classification_20261014_093522` (status: `champion`, mode: `LOW_PRICE`).
- **Champion `HIGHER_PRICE`:**
  - Perintah: `python -m scripts.train_model --mode HIGHER_PRICE --model-type lightgbm --task classification --set-champion --save-registry --calibrate`
  - Data: 137.426 baris pada 182 ticker (Train: 94.821 baris, Val: 20.049 baris, Test: 19.439 baris).
  - Metrik Uji (Unseen Test Data):
    - Brier Score: `0.1884`
    - Log Loss: `0.5643`
    - ROC-AUC: `0.5135`
    - Accuracy: `0.7515`
    - Calibration Error: `0.0337`
  - Versi Terdaftar: `lightgbm_classification_20261014_093607` (status: `champion`, mode: `HIGHER_PRICE`).

### 4. Perbaikan dan Optimasi Kode
- **File:** `python/cloud/s3_sync.py`
  - **Baris 42–52:** Menambahkan adaptive retry config (`max_attempts=10`, `connect_timeout=60`, `read_timeout=120`) pada helper `_get_s3_client` untuk mencegah drop koneksi pada upload berukuran besar di jaringan korporat.
  - **Baris 131–147:** Menambahkan konfigurasi `TransferConfig` yang stabil (`multipart_threshold=250MB`, `use_threads=False`) dengan fallback introspeksi signature untuk mock client pada unit test.
- **File:** `python/models/registry.py`
  - **Baris 93–101:** Memperbarui `ModelRegistry.__init__` agar otomatis mendeteksi subdirektori `registry/` jika diinisialisasi dengan direktori induk `models/`.
- **File:** `python/cloud/handlers.py`
  - **Baris 757:** Mengubah default `event.get("sync_models", False)` menjadi `event.get("sync_models", True)` pada `lambda_telegram_webhook_handler` agar kontainer Lambda yang hangat (warm) selalu menyinkronkan model champion terbaru dari S3.
- **File:** `tests/unit/test_aws.py`
  - **Baris 943:** Memperbarui assertion respons balasan `/model` pada callback query agar fleksibel menerima format output model Dual-Mode maupun Single-Mode.

### 5. Sinkronisasi Cloud Storage S3 & AWS Staging Deployment
- **Unggah Database SQLite:**
  - Database berukuran 178 MB (`datasets/stock_signals.db`) berhasil diunggah ke `s3://idx-stock-signal-436095651956-data/database/stock_signals.db` (SHA-256: `9e332b3d237097e09e64dc41e9d32e0b7a27f62d67effdd9a47eb65f26ca09cf`).
  - Dibuatkan salinan snapshot otomatis: `database/backups/stock_signals_20261014_024731.db`.
- **Unggah Artefak Model:**
  - 15 file model (termasuk artefak `.joblib` dan metadata `.json` untuk kedua champion baru) disinkronkan ke prefix `models/` dan `models/registry/`.
- **AWS Lambda Deployment:**
  - Perintah: `python -m scripts.deploy_aws --stage staging --deploy-lambda --set-webhook`
  - Hasil: Paket zip 157.1 KB diperbarui ke seluruh fungsi Lambda staging:
    - `idx-daily-pipeline-staging`
    - `idx-retraining-pipeline-staging`
    - `idx-telegram-webhook-staging`
  - Status webhook Telegram terhubung ke `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`.

---

## Verifikasi Pengujian

1. **Uji Inferensi Sinyal Trading Harian (`scripts/generate_signals.py`):**
   - Perintah: `python -m scripts.generate_signals --dual-mode --use-champion --min-prob 0.25 --top-n 5`
   - Hasil: 10 sinyal teratas berhasil dihasilkan untuk tanggal 14 Oktober 2026:
     - **LOW_PRICE:** BKSL (P: 31.9%, Score: 27.7), SMRA (P: 25.1%, Score: 26.9), AGRO (P: 25.0%, Score: 26.1), WOOD (P: 25.6%, Score: 25.7), BMTR (P: 28.7%, Score: 25.7).
     - **HIGHER_PRICE:** BBRI (P: 28.2%, Score: 38.7), BBCA (P: 28.2%, Score: 37.7), ASII (P: 27.2%, Score: 32.6), DCII (P: 28.1%, Score: 31.8), BMRI (P: 28.5%, Score: 31.1).
2. **Uji Dispatch Lokal Perintah `/model`:**
   - Hasil: Menampilkan Champion `LOW_PRICE` dan `HIGHER_PRICE` beserta metrik evaluasinya.
3. **Uji Live API Gateway Webhook Endpoint:**
   - Request: Payload Telegram `/model` dikirim ke `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`.
   - Response: `HTTP 200 OK`
     ```text
     🧠 *Model Registry (Dual-Mode)*

     🏆 *Champion [LOW_PRICE]*: `lightgbm_classification_20261014_093522` (lightgbm)
       Metrics: `accuracy`: 0.7405, `brier_score`: 0.1910, `calibration_error`: 0.0334

     🏆 *Champion [HIGHER_PRICE]*: `lightgbm_classification_20261014_093607` (lightgbm)
       Metrics: `accuracy`: 0.7515, `brier_score`: 0.1884, `calibration_error`: 0.0337
     ```
4. **Linter & Code Hygiene:**
   - Perintah: `ruff check .`
   - Hasil: `All checks passed!` (0 lint errors).
5. **Unit Tests:**
   - Perintah: `pytest tests/unit/test_aws.py`
   - Hasil: `39 passed in 270.50s` (100% pass).

---

## Testing Checklist

- [x] Ingestion real historical data BEI (186.436 bar, 208 ticker) tersimpan dan terverifikasi di SQLite `daily_bars`.
- [x] Fitur teknikal & regime IHSG/sektor (186.291 record) tersimpan di `features_daily`.
- [x] Triple-barrier labeling (185.515 record) terklasifikasi ke mode `LOW_PRICE` (45.763) dan `HIGHER_PRICE` (137.426).
- [x] Pelatihan Champion `LOW_PRICE` (LightGBM calibrated) sukses dan terdaftar di `models/registry/`.
- [x] Pelatihan Champion `HIGHER_PRICE` (LightGBM calibrated) sukses dan terdaftar di `models/registry/`.
- [x] Sinkronisasi basis data SQLite (178 MB) ke S3 bucket `idx-stock-signal-436095651956-data` terverifikasi hash SHA-256.
- [x] Sinkronisasi artefak model ke S3 prefix `models/` dan `models/registry/` berhasil.
- [x] Deployment paket zip terbaru ke 3 Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) selesai.
- [x] Endpoint live API Gateway HTTP API merespons `/model` dengan HTTP 200 OK dan menyajikan metrik dual-mode riil.
- [x] Pembuatan sinyal harian (`generate_signals.py`) menghasilkan sinyal real-market pada kedua rezim harga.
- [x] Ruff check bebas error (clean).
- [x] Unit test suite AWS lulus 100%.
- [ ] **Verifikasi Pengguna di Telegram Mobile (@vergellen_bot):**
  - [ ] Kirim `/model` di Telegram: pastikan bot membalas dengan status 🏆 Champion [LOW_PRICE] dan 🏆 Champion [HIGHER_PRICE] beserta metrik akurasinya.
  - [ ] Kirim `/signals` di Telegram: pastikan bot menampilkan kandidat saham dengan harga dan level TP/SL riil.
