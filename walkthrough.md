# Walkthrough: Pre-Entry Gap Invalidation (`INVALIDATED_GAP`) and Exit-Bar Excursion Semantics Remediation

Sesi kerja ini menyelesaikan tindak lanjut audit integritas outcome tracking: membedakan gap pra-entri (Hari ke-1 pembukaan pasar sudah melampaui Stop Loss atau Take Profit sebelum order terbentuk) dengan gap pasca-entri (posisi yang sudah aktif terbuka mengalami gap di hari berikutnya), memperkenalkan status resmi `INVALIDATED_GAP`, memperjelas semantik proksi konservatif candle exit, melakukan re-komputasi historis pada database `datasets/stock_signals.db`, dan memverifikasi integritas metrik dengan 430 unit test serta verifikasi audit independen 0 pelanggaran.

---

## 1. Rincian Masalah & Investigasi Akar Masalah

### A. Pre-Entry Gap vs Post-Entry Gap
1. **BYAN (Signal Date: 2026-08-18)**:
   - Sinyal dihitung dengan referensi harga 17.275, target TP 18.229,44, dan SL 16.844,85.
   - Pada pembukaan hari berikutnya (2026-08-19), harga pasar melompat anjlok -14,9% dan dibuka di 14.700 (jauh di bawah SL 16.844,85).
   - Logika mesin sebelumnya secara keliru mensimulasikan entri pada 14.700 dan langsung menghentikan posisi di tick yang sama pada 14.700, memfabrikasi trade terisi (*FILLED*) dengan gross return 0.00% dan membebankan rugi biaya komisi bursa semu (-0.50% net).
2. **ASII (Signal Date: 2026-10-09)**:
   - Ketidaksesuaian penetapan harga retroaktif menghasilkan SL 5.021,77, sedangkan bar mentah tanggal 2026-10-12 dibuka di 4.850. Pasar dibuka langsung di bawah SL sebelum order dapat terisi.
3. **BBCA (Signal Date: 2026-10-09)**:
   - Kalkulasi sebelum pemecahan saham (*stock split*) menghasilkan SL 9.946,02, sedangkan harga bar pembukaan telah disesuaikan menjadi 6.050. Pasar dibuka langsung di bawah SL sebelum order dapat terisi.

### B. Keputusan Desain Rekayasa
- **Order tidak boleh dieksekusi bila pasar sudah menembus barrier sebelum posisi dibuka**: Jika pada Hari ke-1 harga pembukaan pasar telah menyentuh atau melampaui batas Stop Loss (`open <= sl_price`) atau Take Profit (`open >= tp_price`), order perdagangan riil dibatalkan (`INVALIDATED_GAP`).
- **Pembersihan Metrik Perdagangan Riil (Scope A)**: Posisi berstatus `INVALIDATED_GAP` memiliki `entry_status = 'UNFILLED'`, `holding_days = 0`, dan seluruh field perdagangan riil (`entry_price`, `entry_date`, `exit_price`, `exit_date`, `realized_return`, `net_return`, `mfe`, `mae`) bernilai strictly `NULL`.
- **Eksklusi Metrik Evaluasi**: Status `INVALIDATED_GAP` dan `UNFILLED_EXPIRED` secara ketat dikeluarkan dari sample size evaluasi, perhitungan win rate, dan expectancy perdagangan riil.
- **Penyimpanan Snapshot Harian**: Sinyal yang berstatus `INVALIDATED_GAP` dan `UNFILLED_EXPIRED` tidak memiliki snapshot posisi harian (seluruh snapshot lama dibersihkan secara otomatis).
- **Preservasi Peluang Horison Penuh (Scope B)**: Trajektori counterfactual Scope B (`full_horizon_mfe`, `full_horizon_mae`, `full_horizon_time_to_peak`, `horizon_end_price`, `horizon_end_return`) tetap dicatat dan dihitung relatif terhadap harga jangkar referensi (`reference_price` atau midpoint pita entri).
- **Proksi Konservatif Ekskursi Candle Exit**: Daily OHLC tidak memiliki urutan waktu tick intraday. Proksi deterministik konservatif diterapkan:
  - Pada exit Take Profit: MFE dibatasi pada `tp_price`, sedangkan MAE secara konservatif merefleksikan harga `low` candle sebagai ekskursi merugikan sebelum mencapai TP. Return terealisasi terisolasi dari pergerakan harga pasca-barrier.
  - Pada exit Stop Loss: MAE dibatasi pada `sl_price`, sedangkan MFE merefleksikan harga `high` candle sebagai ekskursi menguntungkan sebelum terkena SL. Return terealisasi terisolasi dari pergerakan harga pasca-barrier.

---

## 2. Rincian Perubahan File & Baris Kode

### A. [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py)
- **Baris 24–33**: Menambahkan `INVALIDATED_GAP` ke dalam tipe literal `outcome_status`.
- **Baris 260–295 (`validate_outcome_lifecycle`)**:
  - Menegakkan bahwa jika `outcome_status == "INVALIDATED_GAP"`, maka `entry_status` wajib `"UNFILLED"`, `holding_days` wajib `0`, dan kolom `entry_date`, `entry_price`, `exit_date`, `exit_price`, `realized_return`, `gross_return`, `net_return`, `return_after_fees`, `return_after_fees_and_slippage`, `mfe`, `mae`, `mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl` wajib `None`.
  - Mengizinkan kolom `trigger_price`, `observation_end_date`, dan metrik Scope B tetap terisi.

### B. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py)
- **Baris 140–185**: Menambahkan fungsi helper `_create_invalidated_gap_outcome` untuk menghasilkan record `INVALIDATED_GAP` dengan metadata lengkap, pembersihan snapshot, dan evaluasi trajektori Scope B relatif terhadap `anchor_price`.
- **Baris 215–235**: Menambahkan deteksi pre-entry gap pada order *immediate entry* (Hari ke-1 pembukaan pasar):
  - Jika `first_bar.open <= sl_price` atau `first_bar.open >= tp_price`: langsung delegasikan ke `_create_invalidated_gap_outcome`.
- **Baris 250–275**: Menambahkan penanganan gap pada order *breakout*:
  - Jika pada candle penembusan harga pembukaan telah melampaui pemicu (`open >= trigger`), periksa apakah `open >= tp_price`. Jika ya, delegasikan ke `_create_invalidated_gap_outcome`. Jika `open < tp_price`, order terisi di harga pembukaan (`open`).
- **Baris 380–420 (`resolve_signal_by_id` & `resolve_all_signals`)**:
  - Menghindari pembuatan note ganda saat `force_recompute=True`.
  - Memanggil `delete_snapshots_by_signal_id` ketika sinyal berakhir sebagai unfilled (`UNFILLED_EXPIRED` atau `INVALIDATED_GAP`).

### C. [`python/outcomes/repository.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py)
- **Baris 54–62 (`_init_db`)**: Memperbarui migrasi tabel `outcomes_daily` agar klausul `CHECK (outcome_status IN (...))` menyertakan `'INVALIDATED_GAP'`.
- **Baris 195–205 (`_row_to_outcome`)**: Menyertakan `INVALIDATED_GAP` dalam pengecekan status unfilled fallback.
- **Baris 270–290 (`save_outcome` & `save_outcomes`)**: Secara otomatis menghapus snapshot harian dari `signal_snapshots_daily` jika status outcome adalah `UNFILLED_EXPIRED` atau `INVALIDATED_GAP`.
- **Baris 315–330**: Mengekspos fungsi `delete_snapshots_by_signal_id(signal_id)`.

### D. [`python/models/evaluation.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/models/evaluation.py)
- **Baris 94 & Baris 345**: Memperbarui filter pengumpulan trade riil agar mengecualikan `INVALIDATED_GAP`:
  - `[o for o in outcomes if o.entry_status == "FILLED" and o.outcome_status in ("TP", "SL", "EXPIRY")]`.
  - Mencegah trade batal mempengaruhi win rate, total trade count, dan expectancy.

### E. [`python/outcomes/dataset.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/dataset.py)
- **Baris 48**: Menyaring `INVALIDATED_GAP` bersama `UNFILLED_EXPIRED` saat parameter `exclude_unfilled=True`.

### F. [`scripts/resolve_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/resolve_outcomes.py)
- **Baris 113–116**: Menambahkan `INVALIDATED_GAP` ke dalam ringkasan distribusi status outcome di terminal.

### G. [`scripts/audit_historical_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/audit_historical_outcomes.py)
- **Baris 63–85**: Menyelaraskan verifikasi invarian integritas: untuk status `INVALIDATED_GAP` maupun `UNFILLED_EXPIRED`, memastikan bahwa `entry_status == 'UNFILLED'`, `holding_days == 0`, seluruh metrik perdagangan bernilai `None`, dan jumlah snapshot di database tepat `0` (`SELECT COUNT(*) FROM signal_snapshots_daily WHERE signal_id = ?`). Untuk filled trades, memverifikasi `snap_count == holding_days`.

### H. [`docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
- Memperbarui Bagian 1, 2, 4, 5, 7, 8, dan 9 dengan definisi `INVALIDATED_GAP`, tabel re-komputasi historis komprehensif ASII/BBCA/BYAN, penjelasan kausalitas non-supresi sinyal pada Day 0, penjelasan rinci proksi konservatif candle exit, tabel lengkap 31 rekor historis terverifikasi, ringkasan performa trading sample riil (27 trade terisi), dan 3 keputusan kesimpulan evaluasi.

### I. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py)
- **Baris 1475–1850**: Menambahkan 11 unit test komprehensif baru:
  1. `test_immediate_entry_open_below_sl_invalidated_gap`
  2. `test_immediate_entry_open_above_tp_invalidated_gap`
  3. `test_valid_immediate_entry_open_between_barriers`
  4. `test_breakout_open_above_trigger_below_tp_fills_at_open`
  5. `test_breakout_open_exceeds_tp_invalidated_gap`
  6. `test_post_entry_gap_down_on_day_2_remains_sl_fill_at_open`
  7. `test_invalidated_gap_exclusion_from_evaluation_metrics`
  8. `test_invalidated_gap_lifecycle_validation_and_persistence`
  9. `test_tp_day_low_conservative_proxy_semantics`
  10. `test_sl_day_high_conservative_proxy_semantics`
  11. `test_asii_bbca_byan_historical_recomputation`

---

## 3. Hasil Re-komputasi Basis Data Historis (`datasets/stock_signals.db`)

Perintah yang dijalankan:
```powershell
.venv\Scripts\python.exe scripts/resolve_outcomes.py --force-recompute --save-db
.venv\Scripts\python.exe scripts/audit_historical_outcomes.py
```

### Distribusi Status Akhir:
- **Total Rekor Matured**: 31
  - `TP`: 8 (25.8%)
  - `SL`: 17 (54.8%)
  - `EXPIRY`: 2 (6.5%)
  - `UNFILLED_EXPIRED`: 1 (3.2%)
  - `INVALIDATED_GAP`: 3 (9.7%) — *ASII, BBCA, BYAN*
- **Kinerja Perdagangan Terisi (Scope A Filled Trades)**:
  - Total Filled Trades: 27
  - Win Rate: 37.04% (10 trade positif net dari 27 trade; pure TP rate: 29.63%)
  - Expectancy: -0.0017 (-17 bps)
  - Snapshot count untuk sinyal unfilled: **0 record**.
  - Audit Invariants: **0 pelanggaran** (Lulus 100%).

---

## 4. Testing Checklist

Setelah perubahan ini dideploy atau diintegrasikan, lakukan verifikasi berikut:

- [ ] **Validasi Gap Pra-Entri (`INVALIDATED_GAP`)**:
  - [ ] Sinyal immediate entry dengan Day 1 open di bawah SL menghasilkan status `INVALIDATED_GAP` (misal `BYAN` 2026-08-18).
  - [ ] Sinyal immediate entry dengan Day 1 open di atas TP menghasilkan status `INVALIDATED_GAP`.
  - [ ] Sinyal breakout dengan pembukaan candle penembusan di atas TP menghasilkan status `INVALIDATED_GAP`.
  - [ ] Sinyal breakout dengan pembukaan candle penembusan di antara trigger dan TP terisi di harga open.
  - [ ] Seluruh trade berstatus `INVALIDATED_GAP` memiliki `entry_status == 'UNFILLED'`, `holding_days == 0`, dan seluruh field perdagangan riil bernilai `NULL`.
- [ ] **Perlindungan Gap Pasca-Entri (Post-Entry Gap)**:
  - [ ] Posisi yang sudah aktif terbuka pada Hari ke-1 dan mengalami gap down di bawah SL pada Hari ke-2 tetap diproses sebagai exit `SL` terisi di harga pembukaan (`open`), dengan MFE/MAE dibatasi pada harga pembukaan.
- [ ] **Semantik Proksi Konservatif Candle Exit**:
  - [ ] Exit TP intraday: in-trade MFE dibatasi pada `tp_price`, sedangkan MAE merefleksikan harga `low` candle exit sebagai potensi ekskursi adverse sebelum menyentuh TP.
  - [ ] Exit SL intraday: in-trade MAE dibatasi pada `sl_price`, sedangkan MFE merefleksikan harga `high` candle exit sebagai potensi ekskursi favorable sebelum menyentuh SL.
  - [ ] Realized return murni dihitung dari harga barrier, tanpa terdistorsi oleh fluktuasi harga pasca-barrier.
- [ ] **Pembersihan Snapshot & Isolasi Metrik**:
  - [ ] Tabel `signal_snapshots_daily` tidak menyimpan rekor snapshot untuk sinyal `INVALIDATED_GAP` maupun `UNFILLED_EXPIRED`.
  - [ ] `EvaluationEngine` mengecualikan sinyal `INVALIDATED_GAP` dari total trade count, win rate, dan expectancy.
- [ ] **Kualitas Kode & Test Suite**:
  - [ ] Linter `ruff check .` lulus 100% tanpa error maupun pelanggaran panjang baris.
  - [ ] Seluruh unit dan integrasi test `pytest` lulus 100% (431 passed).
  - [ ] Skrip audit `scripts/audit_historical_outcomes.py` menghasilkan 0 pelanggaran.
