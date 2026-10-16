# Walkthrough: Final Consistency Check for Outcome Engine, Time-to-Peak Semantics, Ambiguous Exit Metrics, and Historical Statistics Reconciliation

Dokumen ini mendokumentasikan hasil pekerjaan audit final, perbaikan semantik mesin evaluasi outcome (`python/outcomes/engine.py`), penambahan regression tests (`tests/unit/test_outcomes.py`), penyelarasan dokumentasi audit, dan rekonsiliasi statistik performa historis unrounded pada basis data `datasets/stock_signals.db`.

---

## 1. Task Breakdown & Root Cause Analysis

### A. Rekonsiliasi Statistik Performa Historis (Historical Performance Statistics Reconciliation)
- **Masalah**:
  - Laporan sebelumnya merangkum 27 trade terisi dengan: Rata-rata gross return: -1.77%, Rata-rata net return: -2.26%, Expectancy: -0.0017 (-17 bps).
  - Penjumlahan manual pada tabel publikasi mengindikasikan gross return ~ -0.17% dan net return ~ -0.67%.
  - Nilai expectancy -17 bps sejajar dengan rata-rata gross return, bukan rata-rata net return.
- **Investigasi & Akar Masalah**:
  - Dihitung langsung dari data unrounded riil di `datasets/stock_signals.db` untuk 27 trade terisi (`entry_status = 'FILLED'`):
    - $\sum \text{gross\_return} = -0.04627161956972274 \rightarrow \text{Mean Gross Return} = -0.00171376$ (**-0.1714%** atau **-17.14 bps** per trade).
    - $\sum \text{net\_return} = -0.18075771155913367 \rightarrow \text{Mean Net Return} = -0.00669473$ (**-0.6695%** atau **-66.95 bps** per trade).
  - **Akar Kesalahan**: Penulis laporan sebelumnya melakukan **kesalahan penulisan desimal** (angka $-0.001714$ keliru dicatat sebagai -1.77%, lalu dikurangi friksi ~50 bps menjadi -2.26%). Selain itu, nilai -0.0017 yang dipublikasikan sebagai Expectancy sebetulnya adalah *Mean Gross Return*, bukan *Mean Net Return*.
  - **Formulasi Expectancy**: Mengikuti `python/backtest/metrics.py`, untuk equal-weighted trades:
    $$\text{calculate\_expectancy}(trades) = \frac{1}{N} \sum_{i=1}^N \text{net\_return}_i = \text{Mean Net Return} = -0.00669473\text{ (-66.95 bps)}$$
  - **Friksi Terealisasi**: $\text{Gross} - \text{Net} = 0.00498097 \approx 49.81\text{ bps}$, 100% konsisten dengan anggaran friksi EV Gate (50 bps).
  - **Isolasi Sinyal Unfilled**: 4 sinyal tidak terisi (1 `UNFILLED_EXPIRED` dan 3 `INVALIDATED_GAP`) terbukti 100% memiliki metrik Scope A `NULL` dan dieksklusikan dari seluruh kalkulasi performa trade riil.

### B. Penyelarasan Proxy MFE/MAE dan Semantik Time-to-Peak
- **Masalah**:
  - Pada cabang exit Stop Loss, kode sebelumnya menetapkan `bar_high_proxy = bar.high` (batas atas optimis `mfe_max`), padahal lonjakan harga tersebut bisa saja terjadi *setelah* posisi terkena stop loss intraday. Hal ini mendistorsi `mfe` proxy dan `time_to_peak`.
- **Solusi Rekayasa**:
  - Menetapkan `bar_high_proxy = bar_high_lower` pada seluruh cabang SL (`float(bar.open)` untuk entri reguler, atau harga entri $P_{\text{entry}}$ untuk bar entri breakout Hari ke-1).
  - Pada 6 trade SL yang keluar di Hari ke-1 (`ADHI`, `BMTR` 09-15, `DEWA`, `GIAA` 08-18, `KRAS`, `WIRG` 09-15), nilai `mfe` proxy kini tepat bernilai **0.00%** (`mfe_min`), konsisten dengan definisi proksi konservatif deterministik.
  - `time_to_peak` mencerminkan indeks holding day dari puncak in-trade observabel terkonfirmasi (`highest_high_proxy`), mengabaikan lonjakan candle exit yang tak dapat dipastikan mendahului stop.

### C. Klarifikasi Kebijakan Ambiguitas (Modeled Close Exit)
- **Masalah**:
  - Pada `ambiguity_policy="ambiguous"`, model keluar pada penutupan sesi ($Close$), namun sebelumnya ekskursi dibatasi oleh $\min(High, TP)$ dan $\max(Low, SL)$, yang kontradiktif dengan keluar di penutupan.
- **Solusi Rekayasa**:
  - Karena posisi dimodelkan tetap aktif hingga penutupan pasar, ekskursi in-trade merepresentasikan rentang lilin penuh yang dialami posisi:
    $\text{bar\_high\_lower} = \text{bar\_high\_upper} = \text{bar\_high\_proxy} = bar.high$
    $\text{bar\_low\_lower} = \text{bar\_low\_upper} = \text{bar\_low\_proxy} = bar.low$
  - Dibedakan secara eksplisit dari penafsiran *Unresolved Barrier Execution* (yang mengasumsikan barrier tersentuh intraday namun tidak terselesaikan sehingga harga keluar berupa interval $[P_{\text{SL}}, P_{\text{TP}}]$).

---

## 2. Rincian Modifikasi File & Baris Kode

### A. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py)
1. **Baris 601–606**: Breakout entry bar collision di bawah kebijakan `ambiguous` menetapkan `bar_high_proxy = bar.high` dan `bar_low_proxy = bar.low` (full observed candle range).
2. **Baris 634 & 648**: Breakout SL exit menetapkan `bar_high_proxy = bar_high_lower = ep` (conservative lower bound).
3. **Baris 659–664**: Breakout intraday SL collision di bawah kebijakan `ambiguous` menetapkan `bar_high_proxy = bar.high` dan `bar_low_proxy = bar.low`.
4. **Baris 746–751**: Ordinary entry bar collision di bawah kebijakan `ambiguous` menetapkan `bar_high_proxy = bar.high` dan `bar_low_proxy = bar.low`.
5. **Baris 800**: Ordinary `sl_hit` menetapkan `bar_high_proxy = bar_high_lower = float(bar.open)` (conservative lower bound).

### B. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py)
1. **Baris 1735, 1756, 1779**: Memperbarui unit test ekskursi SL (`test_sl_hit_before_tp`, `test_sl_day_high_conservative_proxy_semantics`, `test_sl_touched_before_days_high_uncertain_excursion`) untuk memvalidasi proksi konservatif lower bound (`mfe == mfe_min`).
2. **Baris 1855, 1902**: Memperbarui unit test breakout dan ambiguous collision (`test_breakout_entry_bar_gap_down_then_surge`, `test_same_candle_collision_ambiguity_policies`, `test_same_candle_collision_excursion_bounds_policies`) untuk memvalidasi ekskursi full range pada close exit.
3. **Baris 2267–2461**: Menambahkan 5 targeted regression tests baru:
   - `test_regression_sl_day_high_potentially_occurring_after_stop`: Verifikasi SL-day high tidak bocor ke proxy/time_to_peak.
   - `test_regression_tp_day_low_potentially_occurring_after_target`: Verifikasi TP-day low pasca-target tidak mendistorsi proksi.
   - `test_regression_time_to_peak_when_exit_day_high_is_uncertain`: Verifikasi time_to_peak menunjuk ke puncak terkonfirmasi sebelum exit bar.
   - `test_regression_ambiguous_policy_candle_touching_both_barriers`: Verifikasi kebijakan ambiguous mengeksekusi close exit dengan ekskursi full candle range.
   - `test_regression_reconciliation_report_statistics_with_stored_trade_rows`: Verifikasi rekonsiliasi statistik laporan terhadap nilai database riil.

### C. [`audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/audit_report.md)
1. **Section 1**: Memperbarui User Prompt lengkap.
2. **Section 2**: Menambahkan Executive Summary dengan rekonsiliasi statistik unrounded, penjelasan akar penyebab discrepancy, dan ringkasan populasi sinyal.
3. **Section 3.3**: Memperbarui formulasi bounded excursion proxies, semantik time-to-peak deterministik, dan klarifikasi Modeled Close Exit.
4. **Section 3.4**: Menambahkan rekonsiliasi statistik performa historis (Before vs After table, formulasi expectancy, skrip reproducible Python dan kueri SQL).
5. **Section 3.7**: Memperbarui Tabel 31 Rekor Historis Matured (menyelaraskan MFE proxy untuk 6 trade SL Hari ke-1 menjadi `+0.00% [+0.00%, +X.XX%]`, MAE proxy bounds, dan enum `mode`).
6. **Section 3.8**: Memperbarui penjelasan asumsi ambiguitas dan edge cases.
7. **Section 3.9**: Memperbarui verifikasi test suite (61 unit tests di `test_outcomes.py`, 444 passing tests full repository).
8. **Section 3.10**: Rangkuman lengkap seluruh file yang dimodifikasi.

### D. [`docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
1. **Section 3**: Memperbarui formulasi MFE/MAE proxy pada SL dan ambiguous exit.
2. **Section 4 Defect 4**: Memperbarui ringkasan statistik performa (Mean Gross: -17.14 bps, Mean Net: -66.95 bps, Expectancy: -66.95 bps).
3. **Section 5 Table**: Menyelaraskan nilai MFE 6 trade SL Hari ke-1 ke `+0.0%` dan memperbarui rangkuman performa.
4. **Section 7 & 9**: Memperbarui jumlah test yang lulus menjadi 444 tests dan memperbarui kesimpulan evaluasi.

---

## 3. Hasil Re-komputasi Basis Data & Verifikasi Idempotensi

Perintah yang dieksekusi:
```powershell
.venv\Scripts\python.exe scripts/resolve_outcomes.py --force-recompute --save-db
.venv\Scripts\python.exe scripts/audit_historical_outcomes.py
```

### Hasil Audit Historis:
- **Total Rekor Matured**: 31 (27 FILLED, 1 UNFILLED_EXPIRED, 3 INVALIDATED_GAP)
- **Pelanggaran Invarian / Ambiguitas / Paritas Snapshot**: **0 (Nol)**
- **Hasil**: `ALL INVARIANTS, BOUNDED EXCURSIONS, AND FEES/SLIPPAGE PASSED 100%!`
- **Verifikasi Angka Unrounded (27 Trade Terisi)**:
  - $\text{Arithmetic Mean Gross Return} = -0.00171376$ (-0.1714% / -17.14 bps)
  - $\text{Arithmetic Mean Net Return} = -0.00669473$ (-0.6695% / -66.95 bps)
  - $\text{Expectancy} = -0.00669473$ (-66.95 bps per trade)
  - $\text{Win Rate (Net Return > 0)} = 37.04\%$ (10 / 27 trades)
  - $\text{Pure TP Rate} = 29.63\%$ (8 / 27 trades)
  - $\text{Stop Loss Rate} = 62.96\%$ (17 / 27 trades)
  - $\text{Expiry Rate} = 7.41\%$ (2 / 27 trades)
  - $\text{Average Holding Time} = 4.48\text{ hari}$

---

## Testing Checklist

Berikut adalah item pengujian yang telah diverifikasi dan siap ditinjau:

- [x] **Unit & Regression Testing**:
  - [x] Jalankan `tests/unit/test_outcomes.py`: 61/61 passing tests (100% pass rate).
  - [x] Jalankan seluruh test suite repositori: 444/444 passing tests (100% pass rate).
- [x] **Code Quality & Linting**:
  - [x] Jalankan `ruff check .`: 100% bersih tanpa error atau peringatan.
- [x] **Integritas Basis Data & Audit Invarian**:
  - [x] Jalankan `scripts/audit_historical_outcomes.py`: 31 rekor diverifikasi, 0 pelanggaran.
  - [x] Invarian ekskursi `mfe_min <= mfe <= mfe_max` dan `mae_min <= mae <= mae_max` terpenuhi 100%.
  - [x] Invarian non-negativitas `mfe >= 0` dan non-positivitas `mae <= 0` terpenuhi 100%.
  - [x] Paritas snapshot holding day terakhir terhadap record outcome terminal terpenuhi 100%.
- [x] **Konsistensi Semantik Ekskursi & Ambiguitas**:
  - [x] Trade SL Hari ke-1 memiliki proksi MFE `+0.00%` (`mfe_min`).
  - [x] `time_to_peak` tidak menunjuk ke lonjakan harga exit-day yang tidak terkonfirmasi.
  - [x] Kebijakan `ambiguous` merefleksikan ekskursi rentang lilin penuh $[Low, High]$ pada Modeled Close Exit.
- [x] **Konsistensi Dokumentasi**:
  - [x] `audit_report.md` memuat prompt lengkap, executive summary, sebelum/sesudah tabel perbandingan, skrip kalkulasi reproducible, dan tabel 31 rekor matured.
  - [x] `docs/09_outcome_tracking_backfill_and_integrity_audit_report.md` diselaraskan.
  - [x] `summary.md` diperbarui secara append-only.
