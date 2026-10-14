# Walkthrough: Price Integrity, Range Collapse Prevention, BEI Tick Size Compliance, and Breakout Classification

## Ringkasan Sesi
Sesi ini menginvestigasi dan menyelesaikan akar penyebab integritas harga sinyal trading sebelum retraining atau promosi model:
1. **Diskrepansi Harga Entri vs Close Terakhir (IDR 56 vs IDR 44):** Menambahkan fail-closed validation terhadap deviasi harga entri dari harga penutupan harian terakhir (`reference_price`), penolakan bar basi (`stale bar`), pengecekan kecocokan ticker/tanggal, verifikasi divergensi harga raw vs adjusted close (>5% tanpa aksi korporasi ditolak fail-closed), dan reklasifikasi sinyal di atas deviasi batas sebagai `WAIT_FOR_BREAKOUT` alih-alih `BUY` langsung.
2. **Pencegahan Range Collapse (IDR 56–56 / IDR 53–53):** Mengimplementasikan pembulatan fraksi harga resmi BEI (*Fraksi Harga*) dengan *outward rounding* (`floor_to_tick` untuk batas bawah, `ceil_to_tick` untuk batas atas) dan penjaminan lebar rentang minimum (`min_range_ticks >= 1`), baik di tingkat `SignalEngine` maupun pada pemformat tampilan pesan Telegram (`services/telegram/formatter.py` dan `services/telegram/bot.py`).
3. **Koreksi Transisi Bracket Fraksi Harga BEI:** Mengatasi kelemahan pada batas transisi bracket (contoh: harga 500 dan 5000) di mana outward rounding yang menggunakan tick acuan tunggal menghasilkan fraksi harga bursa yang tidak valid (contoh: 495 pada fraksi Rp 2 atau 4975 pada fraksi Rp 10). Fungsi pembulatan disempurnakan menjadi *self-correcting* sesuai fraksi bracket hasil pembulatan (`cand % cand_tick != 0`).
4. **Penutupan Celah Validasi Barrier:** Menegakkan aturan ketat bahwa sinyal dengan `entry_policy="BREAKOUT"` tidak boleh memiliki status `BUY` (harus `WAIT_FOR_BREAKOUT`), dan pemicu breakout `entry_low` tidak boleh berada di bawah `reference_price`.
5. **Pencatatan Audit Field Integritas Harga:** Menambahkan field audit pada `SignalRecord` dan tabel SQLite `signals_daily` (`signal_generated_at`, `market_data_as_of`, `latest_completed_bar_date`, `reference_price`, `entry_low`, `entry_high`, `entry_policy`, `status`) dengan migrasi skema yang aman dan backward-compatible terhadap data historis yang ada.
6. **Keterbukaan Data Harian vs Real-Time:** Memperbarui format pesan Telegram untuk menegaskan bahwa data bersumber dari penutupan harian Yahoo Finance EOD (`Daily Close / Not Real-Time Quote`).
7. **Verifikasi Komprehensif:** Menambahkan 23 unit & regression test (`tests/unit/test_price_integrity.py`). Seluruh test suite repositori lulus 100% (382 tests passed, 0 failed, ruff 100% clean). Tidak ada model yang di-retrain atau dipromosikan selama investigasi ini.

---

## Root Cause Analysis

### 1. Masalah Diskrepansi IDR 44 Close vs IDR 56 Entry
- **Penyebab Utama:**
  - Sebelumnya, `SignalEngine` tidak melakukan validasi batas deviasi antara entry zone yang dihasilkan dengan harga penutupan terakhir saham (`reference_price = last_bar.close`).
  - Bila ada pemicu breakout atau harga referensi yang tidak sinkron/stale (misal candle saham lain atau data lama yang belum ter-update EOD), sistem tetap memancarkan rekomendasi `BUY` langsung.
  - Tidak ada pengecekan divergensi antara harga raw close dan adjusted close provider data tanpa adanya catatan dividen atau stock split.
- **Solusi:**
  - Menetapkan batas toleransi deviasi ketat (`max_entry_deviation_pct = 0.05`). Sinyal yang melebihi batas ini diklasifikasikan sebagai `entry_policy="BREAKOUT"` dengan status `WAIT_FOR_BREAKOUT` (atau digugurkan/fail-closed jika breakout dinonaktifkan).
  - Menolak data bar yang tanggalnya tidak cocok dengan `signal_date` (deteksi bar basi / missing bar).
  - Memverifikasi konsistensi raw close vs adjusted close (>5% tanpa aksi korporasi digugurkan fail-closed).

### 2. Masalah Collapsed Entry Range (56–56 / 53–53)
- **Penyebab Utama:**
  - Untuk saham bernilai kecil (< Rp 200, contoh BKSL dengan close Rp 53), kalkulasi default setengah band 0.5% menghasilkan rentang `[52.73, 53.26]`.
  - `SignalEngine` sebelumnya hanya membulatkan ke 2 desimal standar (`round(x, 2)`) tanpa pembulatan fraksi harga BEI.
  - Pada antarmuka Telegram (`services/telegram/formatter.py` dan `services/telegram/bot.py`), angka tersebut diformat dengan pemformat integer rupiah `:,.0f`, sehingga kedua batas atas dan bawah membulat ke angka yang sama persis (`53–53` atau `56–56`).
- **Solusi:**
  - Menerapkan pembulatan fraksi harga resmi bursa BEI secara outward: batas bawah dibulatkan ke bawah ke kelipatan fraksi (`round_down_to_tick`), dan batas atas dibulatkan ke atas ke kelipatan fraksi (`round_up_to_tick`).
  - Menegakkan `min_range_ticks >= 1`: jika batas bawah dan atas bernilai sama pada fraksi harga yang berlaku, batas atas dinaikkan minimal 1 fraksi harga BEI (contoh: untuk saham Rp 53 fraksi 1, rentang minimum menjadi Rp 53–54).
  - Melengkapi pemformat tampilan Telegram dengan proteksi outward rounding serupa sebagai jaring pengaman UI.

### 3. Masalah Transisi Fraksi Harga Bursa (Bracket Transitions)
- **Penyebab Utama:**
  - Bila harga saham berada persis di batas ambang fraksi harga (misal Rp 500 dengan fraksi Rp 5, atau Rp 5.000 dengan fraksi Rp 25), pengurangan setengah band membawa batas bawah ke bracket lebih rendah (<500 dengan fraksi Rp 2, <5000 dengan fraksi Rp 10).
  - Jika rounding function menggunakan fraksi tick acuan awal (5 atau 25), harga batas bawah yang dihasilkan (seperti 495 atau 4975) merupakan harga fraksi ilegal di BEI karena 495 ganjil pada fraksi Rp 2 dan 4975 bukan kelipatan 10 pada fraksi Rp 10.
- **Solusi:**
  - Menjadikan fungsi pembulatan fraksi harga self-correcting: jika hasil pembulatan jatuh ke bracket dengan fraksi harga berbeda, lakukan pembulatan ulang berbasis fraksi bracket baru (`cand % cand_tick != 0`), sehingga menghasilkan harga sah (496 dan 4970).

---

## Task Breakdown & Detail Perubahan

### 1. `python/common/types.py`
- **Fraksi Harga BEI (Baris 195–236):**
  - Implementasi fungsi kepatuhan Fraksi Harga SK Direksi BEI Kep-00023/BEI/03-2020:
    - `< 200`: fraksi Rp 1
    - `200 – < 500`: fraksi Rp 2
    - `500 – < 2000`: fraksi Rp 5
    - `2000 – < 5000`: fraksi Rp 10
    - `>= 5000`: fraksi Rp 25
  - Fungsi: `get_bei_tick_size`, `round_down_to_tick`, `round_up_to_tick`, `round_to_nearest_tick` dengan rekonsiliasi otomatis batas bracket.
- **Ekstensi `FeatureRecord` (Baris 335–336):**
  - Menambahkan field opsional `breakout_price` dan `entry_price`.
- **Ekstensi `SignalConfig` (Baris 770–774):**
  - Menambahkan:
    - `max_entry_deviation_pct: float = 0.05` (toleransi deviasi maksimal 5%)
    - `min_range_ticks: int = 1` (lebar rentang minimum 1 fraksi)
    - `enforce_bei_ticks: bool = False` (opsi pembulatan ketat fraksi BEI)
    - `allow_breakout: bool = True` (opsi izin klasifikasi breakout bersyarat)
    - `raw_adjusted_tolerance_pct: float = 0.05` (toleransi divergensi raw vs adjusted)
- **Ekstensi & Hardening `SignalRecord` (Baris 835, 850–855, 866–876, 941–978):**
  - Menambahkan field integritas: `status`, `signal_generated_at`, `market_data_as_of`, `latest_completed_bar_date`, `reference_price`, `entry_policy`, `max_entry_deviation_pct`.
  - Menambahkan root-validator backward-compatible untuk dictionary historis.
  - Memperbarui `validate_barriers()`:
    - Melarang status `BUY` dengan policy `BREAKOUT`.
    - Melarang pemicu `WAIT_FOR_BREAKOUT` di bawah harga referensi.
    - Menolak deviasi `BUY` melebihi `max_entry_deviation_pct` terhadap `reference_price`.

### 2. `python/signals/engine.py`
- **Validasi Bar dan Data Pasar (Baris 341–360):**
  - Memeriksa kesesuaian bar terakhir terhadap `signal_date` (gugurkan jika bar basi / stale).
  - Memeriksa divergensi antara `last_bar.close` (raw) dan `last_bar.adj_close` (>5% tanpa dividen/split ditolak fail-closed).
- **Outward Rounding & Range Collapse Prevention (Baris 465–530):**
  - Menghitung rentang entri dengan target breakout / close.
  - Outward rounding ke kelipatan tick BEI yang valid sesuai bracket masing-masing batas.
  - Memeriksa bila `(entry_high - entry_low) < min_ticks * tick`, menaikkan batas atas secara proporsional.
- **Klasifikasi Status Sinyal & Fail-Closed (Baris 532–560):**
  - Bila deviasi entry melampaui `max_entry_deviation_pct`:
    - Jika `allow_breakout=True`: menetapkan `entry_policy="BREAKOUT"` dan `status="WAIT_FOR_BREAKOUT"`.
    - Jika `allow_breakout=False`: menolak sinyal (fail-closed).
  - Bila deviasi ke bawah > max_dev: menolak sinyal (fail-closed).
  - Mengisi `signal_generated_at`, `market_data_as_of`, `latest_completed_bar_date`, dan `reference_price` secara lengkap.

### 3. `python/signals/repository.py`
- **Auto-Migration Skema SQLite (Baris 80–108):**
  - Mengecek keberadaan kolom-kolom baru (`mode`, `signal_generated_at`, `market_data_as_of`, `latest_completed_bar_date`, `reference_price`, `entry_policy`, `status`) pada tabel `signals_daily`.
  - Menjalankan `ALTER TABLE signals_daily ADD COLUMN ...` bila belum ada, tanpa merusak data historis atau memicu trigger immutability.
- **Persistensi & Deserialisasi (Baris 176–180, 210–216, 233–293):**
  - Memperbarui `INSERT INTO signals_daily` untuk menyimpan kolom-kolom audit baru.
  - Memperbarui `_row_to_record` dengan fallback default untuk baris historis yang dibuat sebelum penambahan kolom.

### 4. `services/telegram/formatter.py` & `services/telegram/bot.py`
- **Pemberitahuan Data EOD vs Real-Time:**
  - Header pesan Telegram diperbarui dengan label jelas: `(Daily Close / Not Real-Time Quote)`.
- **Pencegahan Collapse pada Tampilan:**
  - Memastikan batas bawah dan batas atas yang dibulatkan integer rupiah tidak pernah tampil sama (`entry_str = f"{low_d:,.0f}–{high_d:,.0f}"`).
  - Menampilkan status (`BUY` vs `WAIT_FOR_BREAKOUT`) dan harga penutupan referensi (`Ref Close`).

### 5. `scripts/generate_signals.py`
- Menampilkan kolom `Status` dan `Ref Close` pada tabel terminal.
- Menambahkan kolom `reference_price`, `entry_policy`, `status`, `latest_completed_bar_date`, `market_data_as_of`, dan `signal_generated_at` ke keluaran CSV sinyal harian.

### 6. `tests/unit/test_price_integrity.py`
- Menulis 23 pengujian unit dan regresi:
  1. `test_entry_deviation_fail_closed`: Penolakan deviasi ekstrem (44 vs 56).
  2. `test_entry_range_collapse_prevention`: Pencegahan keruntuhan rentang harga 53, 56, 76.
  3. `test_min_range_width_enforced_zero_band`: Rentang tetap memiliki lebar minimal saat band = 0.
  4. `test_telegram_formatter_collapse_prevention`: Pemformat Telegram tidak pernah menampilkan rentang collapsed.
  5. `test_bei_tick_size_brackets`: Kepatuhan kelima fraksi harga resmi BEI.
  6. `test_round_down_and_up_to_tick`: Akurasi fungsi rounding tick.
  7. `test_stale_data_rejection`: Penolakan bar basi / tanggal tidak cocok.
  8. `test_mismatched_ticker_bar_rejection`: Penolakan bar dari ticker lain.
  9. `test_raw_vs_adjusted_close_divergence_rejected`: Penolakan divergensi data raw vs adjusted >5%.
  10. `test_legitimate_corporate_action_tolerance`: Toleransi divergensi sah jika ada dividen/split.
  11. `test_breakout_trigger_status`: Penetapan status `WAIT_FOR_BREAKOUT` untuk pemicu di atas referensi.
  12. `test_price_integrity_fields_recorded`: Kelengkapan audit metadata sinyal.
  13. `test_repository_roundtrip_with_integrity_fields`: Persistensi dan query basis data SQLite.
  14. `test_validate_barriers_enforces_price_integrity`: Validasi integritas harga pada model domain.
  15. `test_eod_vs_realtime_distinction_in_telegram`: Keterbukaan data EOD pada Telegram broadcast.
  16. `test_bei_tick_boundary_transitions_round_down`: Validasi round-down pada batas fraksi (497.5 -> 496, 4975 -> 4970).
  17. `test_bei_tick_boundary_transitions_round_up`: Validasi round-up pada batas fraksi (199.5 -> 200, 499.5 -> 500).
  18. `test_bei_tick_boundary_transitions_round_nearest`: Validasi round-nearest pada batas fraksi.
  19. `test_breakout_policy_with_buy_status_rejected_in_validate_barriers`: Larangan kombinasi BREAKOUT dan BUY.
  20. `test_breakout_trigger_entry_low_below_reference_rejected`: Larangan breakout trigger di bawah close.
  21. `test_signal_engine_breakout_from_feature_record`: Ekstraksi breakout target dari FeatureRecord.
  22. `test_signal_engine_downward_discrepancy_fail_closed`: Penolakan anomali deviasi ke bawah > 5%.
  23. `test_telegram_formatter_single_mode_shows_status_and_ref_close`: Format single-mode menampilkan Status dan Ref Close.

---

## Verification Record

- **Unit & Regression Testing (Price Integrity):**
  - Perintah: `pytest tests/unit/test_price_integrity.py`
  - Hasil: `23 passed in 1.82s` (100% kelulusan)
- **AWS & Telegram Webhook Unit Testing:**
  - Perintah: `pytest tests/unit/test_aws.py`
  - Hasil: `39 passed in 272.65s` (100% kelulusan)
- **Other Repository Unit Tests:**
  - Perintah: `pytest tests/unit/ -k "not test_aws"`
  - Hasil: `313 passed, 39 deselected in 5.36s` (100% kelulusan)
- **Code Hygiene & Linting:**
  - Perintah: `ruff check .`
  - Hasil: `All checks passed!` (0 lint errors)
- **Database Schema & Data Integrity:**
  - Tabel `signals_daily` di `datasets/stock_signals.db`: Seluruh 12 baris sinyal historis utuh tanpa mutasi nilai.

---

## Testing Checklist

Item verifikasi yang perlu dicek oleh pengguna setelah pembaruan:
- [ ] **Verifikasi Eksekusi Sinyal Harian:** Jalankan `python -m scripts.generate_signals --dual-mode --use-champion` dan pastikan tidak ada saham dengan rentang harga entri collapsed (misal `53–53` atau `56–56`).
- [ ] **Verifikasi Status Breakout:** Pastikan kandidat yang memiliki harga entri di atas toleransi deviasi penutupan berstatus `WAIT_FOR_BREAKOUT` dengan policy `BREAKOUT`, bukan `BUY` langsung.
- [ ] **Verifikasi Tampilan Telegram:** Uji pengiriman broadcast `/daily` atau simulasikan via `python -m scripts.send_daily_telegram --dry-run` dan pastikan teks mencantumkan header `(Daily Close / Not Real-Time Quote)` serta menampilkan rentang fraksi harga yang valid beserta `Status` dan `Ref Close`.
- [ ] **Verifikasi Integritas SQLite:** Periksa tabel `signals_daily` pada `datasets/stock_signals.db` untuk memastikan kolom `reference_price`, `entry_policy`, `status`, dan `market_data_as_of` terisi dengan benar pada sinyal baru tanpa merusak 12 baris historis terdahulu.
