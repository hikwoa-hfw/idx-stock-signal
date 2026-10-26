# Walkthrough — Bot Telegram: Fitur `/daily <tanggal>` & Optimasi Deployment Lambda

## Sesi Kerja: 26 Oktober 2026

### Ringkasan Eksekutif
Sesi kerja ini menambahkan fitur kueri sinyal harian per tanggal spesifik (`/daily <tanggal>`) pada Bot Telegram (misal `/daily 9/10/26`), mengoptimasi paket zip aplikasi Lambda agar tetap aman di bawah limit uncompressed 250 MB saat dipadukan dengan ML layer, mendaftarkan menu interaktif baru ke BotFather via API Telegram `setMyCommands`, serta mendeploy pembaruan ke AWS Lambda staging (`ap-southeast-3`).

---

### Task Breakdown & Detail Perubahan Kode

#### 1. `services/telegram/bot.py`
- **Baris 3:** Menambahkan impor `re`.
- **Baris 17–55:** Mengimplementasikan fungsi parser tanggal fleksibel `_parse_date_input(raw: str) -> Optional[date]`:
  - Mendukung format 3 segmen dengan pemisah `-`, `/`, `.`:
    - `DD/MM/YY` (misal `9/10/26` -> 2026-10-09, auto-expand tahun 2 digit jika `< 100`).
    - `DD/MM/YYYY` (misal `09/10/2026`).
    - `YYYY-MM-DD` (standar ISO, misal `2026-10-09`).
  - Mendukung format 2 segmen (`DD/MM`), dengan default tahun berjalan (`date.today().year`).
  - Penolakan aman (mengembalikan `None`) untuk input non-numerik atau tanggal kalender yang tidak valid.
- **Baris 122:** Memperbarui deskripsi perintah di `handle_help()`: `• /daily [DD/MM/YY] — Ranked buy signals (e.g. /daily 9/10/26)`.
- **Baris 144–172:** Memperbarui method `handle_daily(args)`:
  - Jika argumen diberikan: parsing input via `_parse_date_input`.
  - Jika format salah: kembalikan petunjuk format `Gunakan format: DD/MM/YY atau YYYY-MM-DD`.
  - Jika tanggal valid namun tidak ada di `distinct_dates`: kembalikan pesan informatif beserta daftar 5 tanggal sinyal terbaru yang tersedia di database.
  - Jika tanpa argumen: pertahankan default tanggal terbaru (`distinct_dates[-1]`).
  - Ambil sinyal dan kembalikan pesan terformat dual-mode via `format_daily_signals`.

#### 2. `services/telegram/commands.py`
- **Baris 30:** Memperbarui deskripsi `daily` pada `DEFAULT_BOT_COMMANDS` menjadi `"Daily BUY signals [optional: DD/MM/YY]"`.

#### 3. `tests/unit/test_telegram.py`
- **Baris 322–358:** Menambahkan unit test baru `test_bot_dispatcher_daily_specific_date_formats`:
  1. Kasus `9/10/26` (`DD/MM/YY`): mengembalikan sinyal untuk tanggal `09 Oct 2026`.
  2. Kasus `09/10/2026` (`DD/MM/YYYY`): mengembalikan sinyal untuk tanggal `09 Oct 2026`.
  3. Kasus `2026-10-09` (`YYYY-MM-DD`): mengembalikan sinyal untuk tanggal `09 Oct 2026`.
  4. Kasus `9-10-26` (`DD-MM-YY` pemisah strip): mengembalikan sinyal untuk tanggal `09 Oct 2026`.
  5. Kasus format tidak valid (`/daily bukan_tanggal`): memverifikasi pesan petunjuk format.
  6. Kasus tanggal tanpa sinyal (`/daily 01/01/26`): memverifikasi pesan ketiadaan sinyal dan daftar tanggal alternatif.

#### 4. `scripts/deploy_aws.py`
- **Baris 39–55:** Mengoptimasi `build_lambda_zip()`:
  - Menambahkan ekstensi non-runtime `.ps1` dan `.vbs` ke `skip_exts`.
  - Menambahkan script deployment lokal (`deploy_aws.py`, `build_lambda_layer.py`) ke `skip_files`.
  - Menghemat ~53.5 KB uncompressed, memastikan kombinasi Function Code + ML Layer v6 (248.6 MB) tetap aman di bawah batas uncompressed AWS 250 MB (`262,091,765 bytes < 262,144,000 bytes`).

---

### Hasil Verifikasi & Ringkasan Pengujian

| Pengujian / Operasi | Perintah / Target | Hasil | Status |
|---|---|---|---|
| Linter Kode | `ruff check .` | 0 errors across repo | PASS |
| Unit Test Telegram | `pytest tests/unit/test_telegram.py` | 34/34 passed (100%) | PASS |
| Test Suite Repositori | `pytest -q` | 633/633 passed (100%) | PASS |
| Pendaftaran Menu BotFather | `TelegramClient.set_my_commands()` | `{"ok": true, "result": true}` | PASS |
| Deployment Lambda Staging | `deploy_aws.py --deploy-lambda --stage staging` | `idx-telegram-webhook-staging`, `idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging` terdeploy | PASS |
| Integrasi Webhook API Gateway | `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook` | Webhook terdaftar, 0 pending updates | PASS |
| Dispatcher Command Test | `/daily`, `/daily 9/10/26`, `/daily 01/01/25`, `/daily invalid` | Output terverifikasi akurat dan ramah pengguna | PASS |

---

### Testing Checklist
Setelah deployment ke lingkungan AWS staging, verifikasi butir-butir berikut di aplikasi Telegram:

- [ ] **1. Kueri Tanggal Spesifik:** Ketik `/daily 9/10/26` pada bot Telegram, verifikasi bot merespons dengan sinyal 09 Okt 2026 (Mode A: No Signal, Mode B: BNII & ANTM).
- [ ] **2. Kueri Tanggal Terbaru (Default):** Ketik `/daily` tanpa argumen, verifikasi bot merespons dengan sinyal tanggal terbaru yang tersedia di database.
- [ ] **3. Kueri Format Alternatif:** Ketik `/daily 2026-10-09` atau `/daily 09/10/2026`, verifikasi respons identik dengan `/daily 9/10/26`.
- [ ] **4. Kueri Tanggal Tanpa Sinyal:** Ketik `/daily 01/01/25`, verifikasi bot menampilkan pesan ramah bahwa sinyal tidak ditemukan beserta daftar 5 tanggal sinyal terbaru yang tersedia.
- [ ] **5. Penanganan Format Salah:** Ketik `/daily salah`, verifikasi bot menampilkan panduan format (`Gunakan format: DD/MM/YY atau YYYY-MM-DD`).
- [ ] **6. Menu Perintah Interaktif:** Ketik `/` di kolom input Telegram, pastikan deskripsi perintah `daily` muncul sebagai `Daily BUY signals [optional: DD/MM/YY]`.
- [ ] **7. Perintah `/help`:** Ketik `/help`, pastikan baris bantuan memuat `/daily [DD/MM/YY]`.
