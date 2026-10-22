# Walkthrough — Phase 11G Coverage Threshold Lock, Provider Verification & Telegram Interactive Menu

## Sesi Kerja: 22 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini menuntaskan 4 area krusial pada Phase 11G:
1. **Penguncian Ambang Batas 80% & Regression Tests:** Mengunci ambang batas cakupan ticker minimum 80% (`0.80`) di `python/pipeline/daily_pipeline.py` dan CLI `scripts/run_daily_pipeline.py`, serta menambahkan 3 regression tests komprehensif di `tests/unit/test_daily_pipeline.py` membuktikan coverage <80% secara fail-closed memblokir scoring Stage C/D/E sedangkan >= 80% lolos gate.
2. **Verifikasi Market-Data Provider:** Memverifikasi provider operasional aktif adalah `yfinance` melalui konfigurasi `.env`, `settings.py`, serta file log eksekusi nyata terbaru `logs/daily_pipeline_20261021_163002.log` (192/210 ticker, 91.4% coverage). Menegaskan larangan penggunaan data sintetik/mock dalam mode operasional, dan menghapus seluruh klaim usang terkait GoAPI pada laporan validasi (karena `python/data/provider.py` hanya mendukung `yfinance`, `local_csv`, dan `mock`).
3. **Fitur Telegram Interactive `/` Command Menu:** Mengimplementasikan pendaftaran perintah bot via Bot API `setMyCommands` (`services/telegram/commands.py`, `scripts/set_telegram_commands.py`) dan routing command baru `/status`, `/pipeline`, `/portfolio` pada `services/telegram/bot.py`. Ketika pengguna mengetik `/` di Telegram, menu daftar perintah akan muncul secara interaktif.
4. **Rekonsiliasi Test & Dokumentasi:** Merekonsiliasi hitungan pengujian (616 -> 617 -> 625 passed, 100% kelulusan, ruff 0 error), memperbarui `audit_report.md` (Current Operational State & Indeks Entri 14), merekonsiliasi `docs/22_daily_pipeline_automation_validation_report.md`, serta mencatat Log 72 pada `summary.md`.

---

### Task Breakdown & Perubahan File

#### 1. Penguncian Ambang Batas 80% & Regression Tests Pipeline
- **File:** `tests/unit/test_daily_pipeline.py` (Baris 781–847)
  - Menambahkan test `test_ticker_coverage_below_80_percent_blocks_downstream_scoring`: menyimulasikan 7 dari 10 ticker (70%), memverifikasi Stage B gagal (`status == "FAILED"`), dan memverifikasi Stage C, D, E tidak pernah dieksekusi.
  - Menambahkan test `test_ticker_coverage_meeting_80_percent_passes_gate`: menyimulasikan 8 dari 10 ticker (80%), memverifikasi Stage B berhasil lolos.
  - Menambahkan test `test_ticker_coverage_cli_override`: memverifikasi CLI override `--min-coverage 0.70` meloloskan coverage 70%, dan `--min-coverage 0.90` menggugurkan coverage 80%.
  - Total test pada modul `test_daily_pipeline.py` bertambah dari 20 menjadi 23 test (23/23 passed).

#### 2. Fitur Telegram Interactive `/` Command Menu & Endpoint Integrasi
- **File Baru:** `services/telegram/commands.py`
  - Mendefinisikan daftar 14 command bawaan `DEFAULT_BOT_COMMANDS` (`start`, `help`, `daily`, `signals`, `status`, `pipeline`, `portfolio`, `positions`, `enter`, `exit`, `cancel`, `model`, `compare`, `performance`).
  - Fungsi `validate_bot_commands()`: memvalidasi format nama perintah (huruf kecil, angka, underscore, 1–32 karakter) dan panjang deskripsi (1–256 karakter) sesuai batas resmi Telegram Bot API.
  - Fungsi `format_commands_for_botfather()`: memformat daftar perintah untuk disalin langsung ke BotFather.
- **File:** `services/telegram/client.py` (Baris 242–289)
  - Menambahkan method `set_my_commands(commands, scope, language_code)`: memanggil endpoint Telegram Bot API `setMyCommands`.
  - Menambahkan method `get_my_commands(scope, language_code)`: memanggil endpoint `getMyCommands`.
  - Menambahkan method `delete_my_commands(scope, language_code)`: memanggil endpoint `deleteMyCommands`.
- **File:** `services/telegram/bot.py` (Baris 21–24, 73–84, 185–230)
  - Menambahkan dispatching untuk `/status` (melaporkan operational state, cutoff tanggal, approval status, saldo kas, open positions), `/pipeline` (melaporkan ringkasan eksekusi pipeline terakhir dari `artifacts/pipeline_runs/latest_pipeline_run.json`), dan `/portfolio` (melaporkan ringkasan portofolio paper trading).
  - Memperbarui handler `/help` agar menampilkan seluruh perintah interaktif baru.
- **File:** `services/telegram/__init__.py`
  - Mengekspor `DEFAULT_BOT_COMMANDS`, `format_commands_for_botfather`, dan `validate_bot_commands`.
- **File Baru:** `scripts/set_telegram_commands.py`
  - Skrip CLI mandiri untuk mendaftarkan command ke bot token Telegram (`--token`, `--botfather`, `--delete`, `--dry-run`).
- **File:** `scripts/deploy_aws.py` (Baris 248–265)
  - Menghubungkan pemanggilan `set_my_commands()` otomatis saat deployment webhook Telegram di AWS.
- **File:** `tests/unit/test_telegram.py` (Baris 540–600)
  - Menambahkan 5 unit test baru: `test_default_bot_commands_validation`, `test_format_commands_for_botfather`, `test_telegram_client_set_my_commands`, `test_telegram_client_get_my_commands`, `test_telegram_bot_dispatcher_new_commands`.
  - Total test modul telegram bertambah dari 28 menjadi 33 test (33/33 passed).

#### 3. Verifikasi Provider Market Data & Koreksi Dokumentasi
- **File:** `docs/22_daily_pipeline_automation_validation_report.md`
  - Mengoreksi catatan provider pada Metadata, Completed Items (item 13), Scope table R13, Section 5.1 Q8, Verification table, dan Section 10.
  - Menegaskan bahwa `yfinance` adalah provider operasional terverifikasi di runtime lokal (`.env`, `settings.py`), dan `python/data/provider.py` hanya mendukung `yfinance`, `local_csv`, dan mock.
  - Menghapus klaim dukungan GoAPI dan menegaskan larangan mutlak terhadap fallback mock di mode operasional (`allow_mock_fallback=False`).

#### 4. Rekonsiliasi Audit Report & Cumulative Summary
- **File:** `audit_report.md`
  - Memperbarui header "Current Operational State": commit SHA, 625 test suite passed 100%, 80% coverage threshold lock, yfinance verification, dan Telegram `/` command menu.
  - Memperbarui Indeks Entri 14: 23 unit tests pipeline, 33 tests telegram, 625 total tests.
- **File:** `summary.md` (Baris 1076–1110)
  - Menambahkan Log 72 (22 Oktober 2026) secara strictly append-only mencatat Masalah & Solusi 4 area kerja.

---

### Testing Checklist

Item yang harus diverifikasi oleh operator/reviewer:
- [x] **Linter:** `.venv\Scripts\ruff.exe check .` menghasilkan 0 error (All checks passed).
- [x] **Unit & Regression Pipeline Tests:** `.venv\Scripts\pytest.exe -q tests/unit/test_daily_pipeline.py` meloloskan seluruh 23 test (termasuk 3 regression tests ambang batas 80%).
- [x] **Telegram Unit Tests:** `.venv\Scripts\pytest.exe -q tests/unit/test_telegram.py` meloloskan seluruh 33 test (termasuk 5 tests bot commands & API client).
- [x] **Full Repository Test Suite:** `.venv\Scripts\pytest.exe` meloloskan seluruh 625 test (593 unit, 32 integration, 0 failure, 100% pass rate dalam 333 detik).
- [x] **Ambang Batas Cakupan Ticker Default:** Terkunci di 0.80 (80%) di `DailyPipeline` dan CLI `scripts.run_daily_pipeline`, fail-closed jika <80%.
- [x] **Provider Market Data Terverifikasi:** `MARKET_DATA_PROVIDER=yfinance` terkonfigurasi di `.env`, didukung di `provider.py`, dan log eksekusi nyata `logs/daily_pipeline_20261021_163002.log` mencatat 91.4% coverage via `yfinance`.
- [x] **Telegram Interactive Command Menu:** Script CLI `scripts/set_telegram_commands.py --dry-run` memvalidasi 14 command, dan `--botfather` menghasilkan teks siap pakai untuk @BotFather.
- [x] **Windows Task Scheduler Terdaftar:** Task `\IDX_Stock_Signal_Daily_Pipeline` terdaftar dalam status `Ready` (`Enabled: True`, `StartWhenAvailable: True`).
- [x] **Integritas Model Produksi & Riset:** Model champion produksi (`lightgbm_classification_20261014_093522` dan `093607`) serta bundel kebijakan riset Phase 11F (`8c102c44...`) tetap identik dan tidak tersentuh.
