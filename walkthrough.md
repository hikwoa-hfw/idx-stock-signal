# Walkthrough: Formal Resolution of Outcome Ambiguities, Bounded Excursion Intervals, Snapshot Parity, and MOO Entry Gating

Dokumen ini mencatat penyelesaian formal terhadap dua area utama pada mesin *outcome tracking*:
1. **Exit-day MFE/MAE dan Time-to-Peak**: Menggantikan ketergantungan semata pada estimasi titik tunggal (*single-point heuristic*) dengan interval batas matematis formal (`mfe_min`, `mfe_max`, `mae_min`, `mae_max`, `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`) yang mencerminkan ambiguitas urutan sentuhan barrier pada data bar harian (daily OHLC), sembari mempertahankan proksi konservatif deterministik (`mfe`, `mae`). Menjamin 100% paritas matematis antara snapshot harian (`SignalDailySnapshot`) dan *terminal outcome record* pada *holding day* terakhir.
2. **Validasi Harga Entri Langsung (Market-On-Open / MOO) & Breakout**: Mengimplementasikan kontrak eksekusi pembukaan pasar dengan validasi deviasi batas maksimal (`max_entry_deviation_pct`, default 5.0%) dan penegakan rentang entri opsional (`enforce_entry_band`, default `False`). Deviasi yang melampaui toleransi atau menembus barrier sebelum posisi terbentuk diklasifikasikan sebagai `INVALIDATED_GAP` dengan metrik perdagangan riil (Scope A) bernilai `NULL`. Menyelaraskan kebijakan penegakan entry band secara konsisten pada order breakout (`first_bar.open >= trigger_level`). Kolom `entry_deviation_pct` dicatat pada seluruh perdagangan yang terisi (*FILLED*).

---

## 1. Rincian Masalah & Investigasi Akar Masalah

### A. Ambiguitas Ekskursi Exit-Day (MFE/MAE & Time-to-Peak)
- Pada data candle harian (daily OHLC), urutan harga intraday tidak diketahui tanpa data tick/menit:
  - **Single Take Profit Exit**: Diketahui harga menyentuh TP pada hari tersebut. Namun apakah harga terendah hari itu (`low`) terjadi *sebelum* TP tersentuh (posisi menanggung MAE penuh) atau *setelah* TP tersentuh (posisi sudah ditutup di TP sehingga MAE candle exit hanya terbatas pada `open`) tidak dapat dipastikan secara pasti.
  - **Single Stop Loss Exit**: Diketahui harga menyentuh SL pada hari tersebut. Namun apakah reli harga tertinggi hari itu (`high`) terjadi *sebelum* SL tersentuh (posisi sempat menikmati kenaikan sebelum berbalik stop out) atau *setelah* SL tersentuh tidak dapat dipastikan.
  - **Same-Bar Collision**: Pada candle yang menyentuh TP dan SL secara bersamaan, asumsi kebijakan (`conservative`, `optimistic`, `ambiguous`) menghasilkan rentang ekskursi ekstrem yang berbeda.
- **Solusi Rekayasa**:
  - Menyediakan **bounded interval** eksplisit:
    - TP Exit: `mfe_min = mfe_max = (tp_price - ep) / ep`. Rentang MAE: `mae_min = (min(lows) - ep) / ep` (kasus terburuk), `mae_max = (min(prior_lows + [open]) - ep) / ep` (kasus terbaik).
    - SL Exit: `mae_min = mae_max = (sl_price - ep) / ep`. Rentang MFE: `mfe_min = (max(prior_highs + [open]) - ep) / ep` (kasus terburuk / konservatif), `mfe_max = (max(highs) - ep) / ep` (kasus terbaik).
    - Expiry Exit: Karena posisi ditahan hingga penutupan bar terakhir, seluruh harga OHLC berada dalam periode trade (`lower = upper = proxy`).
    - Invarian matematis: Selalu berlaku `mfe_min <= mfe <= mfe_max` dan `mae_min <= mae <= mae_max`.
  - Menghubungkan metrik snapshot harian (`mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far`) agar pada holding day terakhir tepat identik dengan nilai terminal outcome record.

### B. Kontrak Validasi Entri Langsung (Market-On-Open / MOO) & Breakout
- Order `BUY` langsung dieksekusi pada pembukaan hari perdagangan berikutnya (`first_bar.open`).
- Sebelumnya, pembukaan gap ekstrim (misal gap +10% atau -15%) yang tidak menembus SL/TP dapat terisi secara naif meskipun harga menyimpang sangat jauh dari rencana sinyal.
- **Solusi Rekayasa**:
  - Gating deviasi maksimal pembukaan: `abs(open - target_entry_price) / target_entry_price > max_entry_deviation_pct` membatalkan order menjadi `INVALIDATED_GAP`.
  - Penegakan rentang entri (`enforce_entry_band=True`): Memastikan `open` berada dalam `[entry_low, entry_high]`.
  - Breakout entry gating: Jika bar pembukaan breakout melonjak melampaui `trigger_level` lebih dari `max_entry_deviation_pct` atau berada di luar band entri saat `enforce_entry_band=True`, order dibatalkan menjadi `INVALIDATED_GAP`.
  - Persistensi metrik: Menambahkan `entry_deviation_pct = (open - target_entry_price) / target_entry_price` pada seluruh trade yang terisi.

---

## 2. Rincian Perubahan File & Baris Kode

### A. [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py)
- **Baris 1216–1226 (`SignalOutcomeRecord`)**:
  - Menambahkan kolom `mfe_min: Optional[float]`, `mfe_max: Optional[float]`, `mae_min: Optional[float]`, `mae_max: Optional[float]`.
  - Menambahkan kolom harga `mfe_price_min: Optional[float]`, `mfe_price_max: Optional[float]`, `mae_price_min: Optional[float]`, `mae_price_max: Optional[float]`.
  - Menambahkan kolom `entry_deviation_pct: Optional[float]`.
- **Baris 1317–1327 & 1385–1405 (`validate_outcome_lifecycle`)**:
  - Menegaskan bahwa untuk trade unfilled (`UNFILLED_EXPIRED`, `INVALIDATED_GAP`), seluruh field bounded excursion dan `entry_deviation_pct` wajib `None`.
  - Menegaskan asersi konsistensi matematis pada trade terisi: `mfe_min <= mfe_max`, `mae_min <= mae_max`, `mfe_min <= mfe <= mfe_max`, dan `mae_min <= mae <= mae_max`.
- **Baris 1475–1485 (`SignalDailySnapshot`)**:
  - Menambahkan field `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far`.
- **Baris 1505–1520 (`validate_snapshot_bounds`)**:
  - Menegaskan validasi bound pada setiap snapshot harian: `mfe_min_so_far <= mfe_max_so_far` dan `mae_min_so_far <= mae_max_so_far`.

### B. [`python/outcomes/repository.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py)
- **Baris 215–235 (`_init_db` migrasi `outcomes_daily`)**:
  - Menambahkan migrasi otomatis idempotensial untuk 9 kolom baru: `mfe_min REAL`, `mfe_max REAL`, `mae_min REAL`, `mae_max REAL`, `mfe_price_min REAL`, `mfe_price_max REAL`, `mae_price_min REAL`, `mae_price_max REAL`, `entry_deviation_pct REAL`.
- **Baris 275–295 (`_init_db` migrasi `signal_snapshots_daily`)**:
  - Menambahkan migrasi otomatis idempotensial untuk 4 kolom baru: `mfe_min_so_far REAL`, `mfe_max_so_far REAL`, `mae_min_so_far REAL`, `mae_max_so_far REAL`.
- **Baris 380–395 (`_row_to_outcome`)**:
  - Memetakan 9 kolom baru dari baris SQLite ke atribut `SignalOutcomeRecord`.
- **Baris 430–445 (`_outcome_to_db_params`)**:
  - Menyusun tuple parameter SQLite untuk seluruh 47 kolom `SignalOutcomeRecord`.
- **Baris 450–510 (`_UPSERT_OUTCOME_SQL`)**:
  - Memperbarui query upsert `INSERT INTO outcomes_daily (...) ON CONFLICT(signal_id) DO UPDATE SET ...` dengan 47 kolom lengkap.
- **Baris 520–540 (`_row_to_snapshot`)**:
  - Memetakan 4 kolom bound snapshot baru ke `SignalDailySnapshot`.
- **Baris 725–765 (`save_snapshots`)**:
  - Memperbarui query upsert snapshot `signal_snapshots_daily` dengan 4 kolom bound baru.

### C. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py)
- **Baris 140–155 (`OutcomeEngine.__init__`)**:
  - Menambahkan atribut konfigurasi `enforce_entry_band: bool = False` dan `max_entry_deviation_pct: Optional[float] = None`.
- **Baris 180–190 (`evaluate_signal` & helper wrappers)**:
  - Menerima parameter `enforce_entry_band` dan `max_entry_deviation_pct`.
- **Baris 415–455 (Validasi Immediate Entry MOO)**:
  - Menghitung deviasi `dev = abs(cand_px - anchor_px) / anchor_px`.
  - Jika `dev > eff_max_dev`: membatalkan sinyal menjadi `INVALIDATED_GAP` dengan deskripsi deviasi di `notes`.
  - Jika `eff_enforce_band and (cand_px < signal.entry_low or cand_px > signal.entry_high)`: membatalkan sinyal menjadi `INVALIDATED_GAP`.
  - Jika entri valid: mencatat `entry_deviation_pct = (ep - anchor_px) / anchor_px`.
- **Baris 361–396 (Validasi Breakout Entry Gating & Band Enforcement)**:
  - Jika `first_bar.open >= tp_price`: membatalkan sinyal menjadi `INVALIDATED_GAP`.
  - Jika `first_bar.open >= trigger_level`:
    - Jika deviasi melampaui `eff_max_dev`: membatalkan sinyal menjadi `INVALIDATED_GAP`.
    - Jika `eff_enforce_band and (first_bar.open < signal.entry_low or first_bar.open > signal.entry_high)`: membatalkan sinyal menjadi `INVALIDATED_GAP`.
    - Jika entri valid: mengisi di `first_bar.open` dengan `entry_deviation_pct = dev`.
- **Baris 550–820 (Bounded Excursion Tracking across Exit Policies)**:
  - Mengakumulasikan pergerakan bar perdagangan ke dalam 6 deret harga:
    - Lower, Upper, dan Proxy untuk Highs (`in_trade_highs_lower`, `in_trade_highs_upper`, `in_trade_highs_proxy`)
    - Lower, Upper, dan Proxy untuk Lows (`in_trade_lows_lower`, `in_trade_lows_upper`, `in_trade_lows_proxy`)
  - Logika khusus exit candle:
    - **TP Exit**: `mfe_min = mfe_max = tp_price`. Low candle exit disertakan pada rentang `lower` (worst case), namun dibatasi pada `open` untuk `upper` (best case saat TP langsung tersentuh di awal sesi).
    - **SL Exit**: `mae_min = mae_max = sl_price`. High candle exit dibatasi pada `open` untuk `lower` (worst case jika SL langsung kena di open), dan menyertakan `high` untuk `upper` (best case jika reli terjadi sebelum stop out).
    - **EXPIRY Exit**: Seluruh rentang `lower = upper = proxy`.
    - **Same-Candle Collision**: Penyesuaian rentang sesuai kebijakan `conservative`, `optimistic`, atau `ambiguous`.
- **Baris 820–865 (Perhitungan Snapshot Harian)**:
  - Menghitung `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far` pada setiap holding day.
  - Memastikan nilai snapshot pada hari penutupan tepat sama dengan nilai terminal outcome.
- **Baris 870–930 (Perhitungan Terminal Outcome)**:
  - Menghitung persentase return bound: `mfe_min`, `mfe_max`, `mae_min`, `mae_max`, serta level harga `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`.
  - Memvalidasi asersi `mfe_min <= mfe <= mfe_max` dan `mae_min <= mae <= mae_max`.

### D. [`scripts/resolve_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/resolve_outcomes.py)
- **Baris 45–55**: Menambahkan argumen CLI `--enforce-entry-band` (boolean flag) dan `--max-entry-deviation-pct` (float, default 0.05).
- **Baris 110–125**: Meneruskan opsi CLI ke pemanggilan `OutcomeEngine.resolve_all_signals`.

### E. [`scripts/audit_historical_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/audit_historical_outcomes.py)
- **Baris 112–140**: Menambahkan pemeriksaan asersi matematis komprehensif:
  - Invarian rentang: `mfe_min <= mfe <= mfe_max` dan `mae_min <= mae <= mae_max`.
  - Kepatuhan trade terisi: `entry_deviation_pct is not None` pada seluruh trade `FILLED`.
  - Paritas snapshot 100%: snapshot pada holding day terakhir memiliki nilai `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far` yang persis identik dengan `mfe_min`, `mfe_max`, `mae_min`, `mae_max` pada terminal outcome.

### F. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py)
- **Baris 1914–2260**: Menambahkan dan menyempurnakan suite pengujian komprehensif:
  1. `test_tp_touched_excursion_bounds_and_snapshot_parity`: Memverifikasi bounded excursion pada exit TP, konsistensi invarian, dan paritas snapshot harian.
  2. `test_sl_touched_excursion_bounds_and_snapshot_parity`: Memverifikasi bounded excursion pada exit SL dan paritas snapshot.
  3. `test_gap_through_exit_at_open_bounds`: Memverifikasi bounded excursion saat terjadi gap exit di pembukaan hari berikutnya.
  4. `test_breakout_entry_intraday_and_open_exceeding_dev`: Memverifikasi entri breakout intraday vs pembatalan gap pembukaan ekstrem.
  5. `test_same_candle_collision_excursion_bounds_policies`: Memverifikasi bounded excursion saat TP dan SL disentuh pada candle yang sama di bawah ketiga kebijakan ambiguitas.
  6. `test_immediate_entry_band_and_deviation_scenarios`: Memverifikasi pembatalan order di bawah deviasi ekstrim serta penegakan band opsi strict.
  7. `test_sl_touched_before_days_high_uncertain_excursion`: Memverifikasi ekskursi tak pasti saat SL disentuh sebelum reli puncak hari ke-2 (`mfe_min = 0.02 != mfe_max = 0.08`).
  8. `test_breakout_open_gating_scenarios`: Memverifikasi gating pembukaan breakout: gap open di atas TP, pembukaan di luar band saat `enforce_entry_band=True`, dan pembukaan valid di bawah default MOO.

### G. [`docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
- Memperbarui dokumentasi audit resmi Bagian 1, 4, 7, 8, dan 9:
  - Formulasi matematis *bounded excursion intervals*, resolusi ketidakpastian daily OHLC, jaminan paritas snapshot-outcome 100%, kontrak eksekusi MOO, dan analisis dampak historis (4 record terpengaruh jika `--enforce-entry-band` diaktifkan: `DEWA`, `BMTR`, `ADHI`, `BMTR`).

---

## 3. Hasil Re-komputasi Basis Data Historis (`datasets/stock_signals.db`)

Perintah yang dijalankan:
```powershell
.venv\Scripts\python.exe scripts/resolve_outcomes.py --force-recompute --save-db
.venv\Scripts\python.exe scripts/audit_historical_outcomes.py
```

### Ringkasan Audit Independen:
- **Total Rekor Matured**: 31
- **Pelanggaran Invarian / Ambiguitas / Paritas Snapshot**: **0 (Nol)**
- **Hasil**: `ALL INVARIANTS, BOUNDED EXCURSIONS, AND FEES/SLIPPAGE PASSED 100%!`
- **Distribusi Status Akhir**:
  - `TP`: 8 (25.8%)
  - `SL`: 17 (54.8%)
  - `EXPIRY`: 2 (6.5%)
  - `UNFILLED_EXPIRED`: 1 (3.2%)
  - `INVALIDATED_GAP`: 3 (9.7%)
- **Statistik Scope A (Trade Terisi - 27 Trade)**:
  - Win Rate: 29.63% (8 TP / 27 Trades)
  - Gross Return Rata-rata: -1.77%
  - Net Return Rata-rata: -2.26%
  - Rata-rata Holding Days: 3.85 hari

---

## Testing Checklist

Berikut adalah daftar item pengujian yang wajib diverifikasi:

- [x] **Invarian Ekskursi Matematis**:
  - [x] Memastikan `mfe_min <= mfe <= mfe_max` untuk setiap trade terisi.
  - [x] Memastikan `mae_min <= mae <= mae_max` untuk setiap trade terisi.
  - [x] Memastikan `mfe >= 0.0` dan `mae <= 0.0` terpasang tanpa pelanggaran.
- [x] **Paritas Snapshot-to-Outcome 100%**:
  - [x] Memastikan snapshot harian pada `holding_days` terakhir memiliki nilai `mfe_min_so_far == mfe_min`, `mfe_max_so_far == mfe_max`, `mae_min_so_far == mae_min`, dan `mae_max_so_far == mae_max`.
  - [x] Memastikan jumlah snapshot untuk trade `UNFILLED_EXPIRED` dan `INVALIDATED_GAP` tepat `0`.
- [x] **Validasi Kontrak MOO & Breakout**:
  - [x] Order dengan deviasi pembukaan melebihi `max_entry_deviation_pct` (5.0%) dibatalkan sebagai `INVALIDATED_GAP`.
  - [x] Order dengan pembukaan menembus SL (`open <= sl_price`) atau TP (`open >= tp_price`) dibatalkan sebagai `INVALIDATED_GAP`.
  - [x] Parameter `--enforce-entry-band` menolak entri di luar `[entry_low, entry_high]`.
  - [x] Order breakout yang membuka di luar band saat `enforce_entry_band=True` dibatalkan sebagai `INVALIDATED_GAP`.
  - [x] Kolom `entry_deviation_pct` terisi presisi pada seluruh trade terisi.
- [x] **Suite Pengujian Otomatis**:
  - [x] Menjalankan `.venv\Scripts\python.exe -m pytest tests/unit/test_outcomes.py`: Seluruh 56 tests lulus (100% pass rate).
  - [x] Menjalankan `.venv\Scripts\python.exe -m ruff check .`: 100% bersih tanpa peringatan/pelanggaran linter.
- [x] **Audit Integritas Basis Data**:
  - [x] Menjalankan `.venv\Scripts\python.exe scripts/audit_historical_outcomes.py`: Memverifikasi 31 rekor historis dengan 0 pelanggaran.
