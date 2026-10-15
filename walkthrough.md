# Walkthrough: Outcome Tracking Historical Backfill & Integrity Audit

Sesi kerja ini menyelesaikan audit integritas menyeluruh dan backfill historis untuk Outcome Tracking pipeline. Perubahan mencakup penambahan status siklus hidup sinyal `UNFILLED_EXPIRED` (memisahkan sinyal breakout yang tidak pernah terpicu dari perdagangan riil), penambahan kolom eksplisit `entry_status` (`FILLED` vs `UNFILLED`), pembatasan matematis MFE $\ge 0.0$ dan MAE $\le 0.0$, penegakan horison validitas pemicu breakout (mencegah kebangkitan order kedaluwarsa di masa depan), penyelarasan snapshot harian MAE pada entri intraday breakout, kalkulasi metrik jalur (`mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl`), perhitungan net return transaksi BEI (`net_return`), pengecualian konsisten `UNFILLED_EXPIRED` pada seluruh jalur evaluasi trading (`compute_trading_metrics`, `evaluate_dataset`, `evaluate_from_outcomes`), perbaikan portabilitas pemanggilan langsung CLI runner, migrasi otomatis skema SQLite `outcomes_daily`, verifikasi idempotensi replay, dan audit rekonsiliasi data mentah independen.

---

## 1. Rincian Perubahan Kode & File

### A. [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py)
- **Field & Validator Baru**:
  - `entry_status: str = "FILLED"` ditambahkan pada `SignalOutcomeRecord` dengan validasi nilai `{"FILLED", "UNFILLED", "PENDING"}`.
  - Menambahkan field metrik jalur baru pada `SignalOutcomeRecord`: `mfe_price: Optional[float]`, `mae_price: Optional[float]`, `time_to_peak: Optional[int]`, `time_to_tp: Optional[int]`, `time_to_sl: Optional[int]`, `net_return: Optional[float]`.
  - Menambahkan status `"UNFILLED_EXPIRED"` ke dalam himpunan status valid outcome (`{"OPEN", "TP", "SL", "EXPIRY", "AMBIGUOUS", "UNFILLED_EXPIRED"}`).
  - Mendaftarkan `mfe_price`, `mae_price`, dan `net_return` ke dalam validator finite return metrics.
  - Menambahkan validator `validate_time_to_metrics` untuk memastikan `time_to_peak`, `time_to_tp`, dan `time_to_sl` bernilai non-negatif (`v >= 0`).
- **Aturan Siklus Hidup (`validate_outcome_lifecycle`)**:
  - Untuk `UNFILLED_EXPIRED`: `self.entry_status = "UNFILLED"`, `realized_return is None`, `holding_days == 0`, `net_return is None`, `exit_reason = "UNFILLED_EXPIRED"`, `resolved_at` terisi timestamp UTC.
  - Untuk status selain `UNFILLED_EXPIRED`: memastikan `entry_status != "UNFILLED"`.

### B. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py)
- **Horison Validitas Pemicu Breakout**:
  - Pencarian pemicu breakout `trigger_level` dibatasi secara ketat pada bar validitas `deduped_bars[: signal.max_holding_days]`.
  - Jika `trigger_level` tidak tertembus dalam batas `max_holding_days`, sinyal diselesaikan sebagai `UNFILLED_EXPIRED` (`entry_status="UNFILLED"`) dan tidak akan terpicu oleh bar-bar di masa depan setelah horison kedaluwarsa.
  - Mencatat harga tertinggi yang diobservasi (`max_observed_high`) pada field `notes` untuk analisis peluang breakout tanpa eksekusi.
  - Jika breakout tertembus pada candle batas terakhir (`k == max_holding_days`), order berhasil masuk dan holding period dimulai dari bar tersebut.
- **Penyelarasan MAE Snapshot Intraday Breakout**:
  - Pada entri intraday breakout (`k=1` dan `open < trigger_level`), low pra-entri disaring menggunakan `min(entry_price, close)` saat SL tidak tersentuh, sehingga `SignalDailySnapshot.mae_so_far` identik dengan `SignalOutcomeRecord.mae`.
- **Penjagaan MFE/MAE Matematis**:
  - `mfe = max(0.0, (highest_high - ep) / ep)` (tidak pernah negatif).
  - `mae = min(0.0, (lowest_low - ep) / ep)` (tidak pernah positif).
  - `mfe_price = max(0.0, highest_high - ep)`.
  - `mae_price = min(0.0, lowest_low - ep)`.
- **Metrik Time-to-Event**:
  - `time_to_peak`: indeks 1-based holding day saat `highest_high` tercapai.
  - `time_to_tp`: indeks holding day saat barrier TP tersentuh (`None` jika bukan TP).
  - `time_to_sl`: indeks holding day saat barrier SL tersentuh (`None` jika bukan SL).
- **Net Return Transaksi BEI (`net_return`)**:
  - Fee beli $c_{\text{buy}} = 0.0015$ (0.15%), fee jual $c_{\text{sell}} = 0.0025$ (0.25%).
  - Rumus: $R_{\text{net}} = \frac{P_{\text{exit}} \cdot (1 - 0.0025)}{P_{\text{entry}} \cdot (1 + 0.0015)} - 1.0$.

### C. [`python/outcomes/repository.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py)
- **Skema & Migrasi**:
  - Menambahkan kolom `entry_status TEXT NOT NULL DEFAULT 'FILLED'` pada DDL tabel `outcomes_daily`.
  - Migrasi otomatis menambahkan `entry_status`, `mode`, `mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl`, `net_return`.
  - Migrasi data otomatis: `UPDATE outcomes_daily SET entry_status = 'UNFILLED' WHERE outcome_status = 'UNFILLED_EXPIRED'`.
- **Query & Mapping**:
  - Memperbarui `_row_to_outcome` untuk mengekstrak dan memetakan `entry_status`.
  - Memperbarui `save_outcome` dan `save_outcomes` untuk memasukkan `entry_status` pada klausa `INSERT` dan `ON CONFLICT DO UPDATE SET`.

### D. [`python/models/evaluation.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/models/evaluation.py)
- **Eksklusi Menyeluruh `UNFILLED_EXPIRED` dari Metrik Trading**:
  - Pada `compute_trading_metrics`: jika `outcome_statuses` diberikan, pasangan elemen berstatus `UNFILLED_EXPIRED` dan `OPEN` otomatis dikeluarkan dari `raw_list` dan `clean_statuses`, mencegah return `NaN` diubah menjadi `0.0` dan mendistorsi `total_trades`, `win_rate`, serta `expectancy`.
  - Pada `evaluate_dataset`: menyaring baris `UNFILLED_EXPIRED` dan `OPEN` sebelum menghitung metrik performa perdagangan.
  - Pada `evaluate_from_outcomes`: mengecualikan `UNFILLED_EXPIRED` dan `OPEN` dari perhitungan `sample_size` dan `trading_metrics`.

### E. [`python/outcomes/dataset.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/dataset.py)
- Menambahkan kolom `entry_status` ke dalam DataFrame ekspor dataset outcome.
- Mendukung opsi `exclude_unfilled: bool = False` untuk menyaring record tanpa entri.

### F. [`scripts/resolve_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/resolve_outcomes.py)
- Menambahkan konfigurasi root `sys.path.insert(0, ...)` sehingga skrip dapat dipanggil langsung dari terminal PowerShell/Bash tanpa ketergantungan variabel environment.
- Format tabel ASCII dan ringkasan distribusi menampilkan status `UNFILLED_EXPIRED`.
- Opsi CLI `--exclude-unfilled` untuk ekspor dataset.

### G. [`scripts/audit_historical_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/audit_historical_outcomes.py)
- Skrip rekonsiliasi independen yang memverifikasi:
  1. Batas MFE $\ge 0.0$ dan MAE $\le 0.0$ pada seluruh outcome.
  2. Invarian siklus hidup `UNFILLED_EXPIRED` (holding_days=0, returns=None, entry_status='UNFILLED').
  3. Validasi `entry_status == 'FILLED'` untuk semua trade yang tereksekusi.
  4. Perhitungan net return transaksi BEI terhadap gross realized return.
  5. Rekonsiliasi independen MFE/MAE dan holding days terhadap bar historis mentah pada `daily_bars`.

### H. [`tests/unit/test_outcomes.py`] & [`tests/unit/test_evaluation.py`]
- Menambahkan pengujian menyeluruh:
  - `test_breakout_policy_trigger_beyond_max_holding_days_expires_unfilled`: Verifikasi order tidak bangkit setelah jendela kedaluwarsa.
  - `test_breakout_policy_trigger_on_exact_final_candle`: Verifikasi penembusan tepat pada candle akhir horison berhasil masuk.
  - `test_intraday_breakout_snapshot_mae_consistency`: Verifikasi snapshot MAE tidak tercemar low pra-breakout.
  - `test_entry_status_lifecycle_and_persistence`: Verifikasi persistensi dan validasi kolom `entry_status`.
  - `test_unfilled_expired_excluded_from_compute_trading_metrics_and_dataset`: Verifikasi `compute_trading_metrics` dan `evaluate_dataset` tidak mendistorsi metrik trading.

---

## 2. Testing Checklist

Setelah perubahan ini diterapkan dan dijalankan di lingkungan produksi/staging, lakukan verifikasi berikut:

- [ ] **Breakout Unfilled Lifecycle Invariants**:
  - [ ] Sinyal `WAIT_FOR_BREAKOUT` yang tidak pernah mencapai `entry_low` hingga `max_holding_days` diselesaikan dengan status `UNFILLED_EXPIRED`.
  - [ ] Record `UNFILLED_EXPIRED` memiliki `entry_status == 'UNFILLED'`.
  - [ ] Record `UNFILLED_EXPIRED` memiliki `holding_days == 0`.
  - [ ] Record `UNFILLED_EXPIRED` memiliki `realized_return IS NULL` dan `net_return IS NULL`.
  - [ ] Record `UNFILLED_EXPIRED` memiliki `exit_price IS NULL`.
  - [ ] Sinyal breakout yang menyentuh pemicu setelah `max_holding_days` tidak hidup kembali menjadi trade.
- [ ] **MFE / MAE Clamping & Price Trajectory**:
  - [ ] Nilai `mfe >= 0.0` dan `mfe_price >= 0.0` di semua record outcome.
  - [ ] Nilai `mae <= 0.0` dan `mae_price <= 0.0` di semua record outcome.
  - [ ] `SignalDailySnapshot.mae_so_far` selaras dengan `SignalOutcomeRecord.mae` pada entri intraday breakout.
  - [ ] `time_to_peak` bernilai antara 1 s.d. `holding_days` untuk semua trade yang terisi.
  - [ ] `time_to_tp` terisi jika dan hanya jika `outcome_status == "TP"`.
  - [ ] `time_to_sl` terisi jika dan hanya jika `outcome_status == "SL"`.
- [ ] **BEI Transaction Costs & Net Return**:
  - [ ] Nilai `net_return` dihitung dengan formula $((P_{\text{exit}} \times (1 - 0.0025)) / (P_{\text{entry}} \times (1 + 0.0015))) - 1.0$.
  - [ ] Pada trade impas gross ($P_{\text{exit}} == P_{\text{entry}}$), `net_return` mencerminkan friksi transaksi (sekitar -0.40%).
- [ ] **Evaluation Metric Isolation**:
  - [ ] `compute_trading_metrics` mengecualikan record `UNFILLED_EXPIRED` dan `OPEN` dari perhitungan `total_trades`, `win_rate`, dan `expectancy`.
  - [ ] `EvaluationEngine.evaluate_dataset` mengecualikan record tanpa entri dari metrik trading.
  - [ ] `EvaluationEngine.evaluate_from_outcomes` mengecualikan record `UNFILLED_EXPIRED` dan `OPEN`.
  - [ ] CLI runner `python scripts/resolve_outcomes.py --exclude-unfilled` mengekspor dataset yang bebas dari record sinyal tanpa entri.
- [ ] **Database Schema & Replay Idempotency**:
  - [ ] Skema tabel `outcomes_daily` termigrasi secara otomatis dengan kolom `entry_status` tanpa kehilangan data historis.
  - [ ] Menjalankan `python scripts/resolve_outcomes.py --save-db` berulang kali bersifat 100% idempoten (0 duplikasi record baru).
  - [ ] Eksekusi `python scripts/audit_historical_outcomes.py` menghasilkan 0 pelanggaran terhadap bar pasar mentah (31/31 record terverifikasi).
