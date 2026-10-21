# Walkthrough — Daily Market-Data-to-Paper-Trading Pipeline Automation & Validation Review

## Sesi Kerja: 21 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini meninjau secara kritis dan memverifikasi implementasi Phase 11G (Daily Market-Data-to-Paper-Trading Pipeline Automation & Operational Validation). Ditemukan dan diperbaiki sejumlah kelemahan dan bug pada upaya sebelumnya:
1. `DailyBarRepository` mengalami crash runtime (`AttributeError`) saat Stage A memanggil `get_ingestion_runs(limit=1)` karena method belum diimplementasikan.
2. Skrip wrapper PowerShell `scripts/run_scheduled_pipeline.ps1` berhenti mendadak dengan `NativeCommandError` ketika native `python.exe` mencetak pesan log rutin ke stderr di bawah `$ErrorActionPreference = "Stop"`.
3. Pendaftaran Windows Task Scheduler sebelumnya belum menyertakan flag catch-up `-StartWhenAvailable`.
4. Laporan operasional `PipelineRunReport` belum memuat seluruh 14 metrik audit wajib.
5. Stage B dan Stage D belum dilengkapi rekonsiliasi database fisik, verifikasi ketersediaan proxy benchmark, cross-check ticker fitur terhadap bar harga di `daily_bars`, dan penolakan fail-closed saat kandidat berhistori lengkap berjumlah 0.
6. Perbandingan tanggal pada `processed_dates` di Stage B mengalami type mismatch (`datetime.date` vs `str`).

Seluruh isu tersebut telah diperbaiki secara tuntas. Pengujian unit pada `tests/unit/test_daily_pipeline.py` telah diperluas dari 13 menjadi 19 test case. Seluruh 616 test dalam repositori (584 unit, 32 integration) lulus 100%, linter ruff bersih tanpa error (0 errors), dan task scheduler terverifikasi berstatus `Ready` dengan `StartWhenAvailable: True`.

---

### Task Breakdown & Perubahan File

#### 1. Repository Ingestion Run Audit Query
- **File:** `python/data/repository.py` (Baris 388–425)
  - Mengimplementasikan method `DailyBarRepository.get_ingestion_runs(limit: int = 10) -> list[IngestionRun]`.
  - Mengambil rekaman log ingestion audit dari tabel `ingestion_runs` yang diurutkan secara descending (`ORDER BY started_at DESC`).
  - Mencegah `AttributeError: 'DailyBarRepository' object has no attribute 'get_ingestion_runs'` saat Stage A merekonsiliasi statistik eksekusi ingestion.

#### 2. Robustness PowerShell Scheduled Wrapper
- **File:** `scripts/run_scheduled_pipeline.ps1` (Baris 80–92)
  - Mengisolasi pemanggilan executable Python native dengan scoping lokal `$ErrorActionPreference = "Continue"`.
  - Meneruskan seluruh argumen CLI `@args` ke skrip Python.
  - Memastikan output stderr rutin (seperti logging peringatan yfinance pada ticker delisting) tidak memicu terminasi prematur PowerShell `NativeCommandError`.

#### 3. Task Scheduler Catch-Up Settings
- **File:** `scripts/register_daily_scheduler.ps1` (Baris 48–56)
  - Menambahkan parameter `-StartWhenAvailable` pada pemanggilan `New-ScheduledTaskSettingsSet`.
  - Menjadwalkan ulang task `\IDX_Stock_Signal_Daily_Pipeline` menggunakan flag `-Force`.
  - Terverifikasi via `Get-ScheduledTask` dengan konfigurasi `State: Ready`, trigger Senin–Jumat 16:30 WIB, dan `StartWhenAvailable: True`.

#### 4. Penguatan Gerbang Fail-Closed & Rekonsiliasi Database (Stage B & Stage D)
- **File:** `python/pipeline/daily_pipeline.py` (Baris 415–615, 780–860, 1010–1110)
  - **Stage B Rekonsiliasi:** Memverifikasi baris yang dilaporkan oleh ingestion run terhadap tabel fisik `daily_bars` (`SELECT COUNT(*) FROM daily_bars WHERE ingestion_run_id = ?`). Jika ingestion melaporkan baris berhasil diinsert tetapi tidak ditemukan di database fisik, Stage B gagal seketika (`FAILED`).
  - **Stage B Normalisasi Tipe & Safe Skip:** Memperbaiki bug komparasi tipe data tanggal (`str(session_d_check) in processed_dates`). Jika sesi terbaru sudah selesai diproses pada paper trading state dan tidak ada bar baru yang di-ingest, pipeline melakukan skip aman dengan status `SKIPPED_NO_NEW_SESSION`.
  - **Stage B Urutan Evaluasi:** Mengevaluasi ambang batas cakupan ticker (`coverage_pct < self.min_ticker_coverage`) mendahului pengecekan ketersediaan proxy benchmark composite.
  - **Stage D Validasi Silang Ticker & Benchmark:**
    * Memvalidasi bahwa seluruh ticker yang memiliki fitur pada `features_daily` memiliki bar harga yang cocok di `daily_bars` pada sesi yang sama.
    * Memvalidasi bahwa kolom benchmark (`ihsg_return_5d`, `ihsg_return_20d`, `ihsg_vs_ema20`, `ihsg_vs_ema50`, `market_breadth`, `market_volatility`) tidak bernilai seluruhnya NULL.
    * Menegakkan aturan fail-closed jika kandidat dengan riwayat 30-fitur lengkap berjumlah 0 (`complete_history_candidates == 0`).
    * Memvalidasi ketiadaan nilai `NaN` atau `Inf` pada matriks kandidat berhistori lengkap.
  - **Stage E & Pelaporan Audit (14 Metrik):** Melengkapi dataclass `PipelineRunReport` dan method `_finalize_report` dengan 14 metrik operasional: `feature_schema_hash`, `feature_version`, `model_hashes`, `policy_bundle_hash`, `decision_date`, `candidates_count`, `decisions_count`, `pending_orders_count`, `new_fills_count`, `exits_count`, `open_positions_count`, `cash_balance_idr`, `realized_net_pnl_idr`, `unrealized_pnl_idr`, `current_equity_idr`, `max_drawdown_pct`. Menyediakan fallback otomatis ke canonical policy hash bundle (`8c102c44...`).

#### 5. CLI Formatting & Summary Updates
- **File:** `scripts/run_daily_pipeline.py` (Baris 150–175)
  - Memperbarui fungsi `print_report_summary` untuk menampilkan metrik audit baru: hash kebijakan, hash model per mode harga, hitungan kandidat/keputusan, fill/exit, posisi terbuka, kas, dan ekuitas.
  - Membungkus output teks di bawah 100 karakter untuk kepatuhan linter ruff.

#### 6. Penambahan & Perbaikan Test Suite
- **File:** `tests/unit/test_daily_pipeline.py` (Baris 1–765)
  - Menambahkan 6 unit test baru (total 19 unit test):
    1. `test_stage_b_reconciliation_fails_on_missing_db_rows`
    2. `test_stage_b_skips_when_session_already_processed_in_daily_mode`
    3. `test_feature_readiness_fails_if_zero_candidates_have_complete_history`
    4. `test_feature_readiness_fails_if_features_mismatch_price_bars`
    5. `test_report_contains_all_required_operational_metrics`
    6. `test_get_ingestion_runs_repository_method`
  - Memperbaiki test fixtures (`test_unapproved_or_invalid_prospective_dates_rejected`, `test_cli_runner_execution`, `test_report_contains_all_required_operational_metrics`) agar menyediakan histori 380 hari bursa sehingga perhitungan benchmark composite berjalan valid.
- **File:** `tests/unit/test_challenger_retraining.py` (Baris 80–85)
  - Menyesuaikan asersi `max_bar_date >= '2026-10-16'` untuk mengakomodasi bar harian baru yang di-ingest ke `datasets/stock_signals.db`.

---

### Testing Checklist

Setelah perubahan sesi ini, lakukan verifikasi berikut:

- [ ] **Verifikasi Status Scheduled Task Windows:**
  ```powershell
  Get-ScheduledTask -TaskName "IDX_Stock_Signal_Daily_Pipeline" | Format-List TaskName, State, @{Name="Triggers";Expression={$_.Triggers.StartBoundary}}, @{Name="Settings";Expression={$_.Settings.StartWhenAvailable}}
  ```
  *Ekspektasi: TaskName: `IDX_Stock_Signal_Daily_Pipeline`, State: `Ready`, Triggers: `16:30:00+07:00`, Settings (StartWhenAvailable): `True`.*

- [ ] **Verifikasi Linter Repositori (Ruff):**
  ```powershell
  .venv\Scripts\ruff.exe check .
  ```
  *Ekspektasi: `All checks passed!` (0 errors).*

- [ ] **Verifikasi Unit Test Daily Pipeline:**
  ```powershell
  .venv\Scripts\python.exe -m pytest tests/unit/test_daily_pipeline.py -v
  ```
  *Ekspektasi: 19 passed in ~7s (100%).*

- [ ] **Verifikasi Paper Trading Integrity Suite:**
  ```powershell
  .venv\Scripts\python.exe -m pytest tests/unit/test_fail_closed_readiness.py tests/unit/test_research_scoring_integrity.py -q
  ```
  *Ekspektasi: 53 passed (100%).*

- [ ] **Verifikasi Seluruh Test Suite Repositori:**
  ```powershell
  .venv\Scripts\python.exe -m pytest -q
  ```
  *Ekspektasi: 616 passed (100%).*

- [ ] **Verifikasi Dry-Run Eksekusi Pipeline CLI:**
  ```powershell
  .venv\Scripts\python.exe -m scripts.run_daily_pipeline --date 2026-10-16 --skip-ingest --dry-run
  ```
  *Ekspektasi: Exit code 0, status `COMPLETED_DRY_RUN` / `SKIPPED_PRE_APPROVAL_SESSION`, seluruh metrik audit tercetak lengkap.*
