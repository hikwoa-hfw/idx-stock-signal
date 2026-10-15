# Walkthrough: Outcome Metric Semantics, Collision Excursion Consistency, and Execution Cost Remediation

Sesi kerja ini menyelesaikan investigasi skeptis dan perbaikan terhadap implementasi outcome tracking, pemisahan dua lingkup metrik independen (Scope A: Kinerja Perdagangan Riil vs Scope B: Analisis Peluang Horison Penuh), perbaikan kebocoran harga ekstrem pasca-keluar pada candle exit dan tubrukan TP/SL di candle yang sama (same-bar collision), koreksi semantik sinyal breakout tanpa entri (`UNFILLED_EXPIRED`), penyelarasan friksi komisi dan slippage dengan gerbang EV Hurdle, re-komputasi historis pada basis data `datasets/stock_signals.db`, dan verifikasi audit independen.

---

## 1. Rincian Temuan & Perbaikan Kode

### A. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py)
- **Konsistensi Metrik Ekskursi pada Tubrukan Barrier di Candle yang Sama (Same-Bar Collision)**:
  - *Masalah*: Saat candle menyentuh TP dan SL di hari yang sama (`tp_hit and sl_hit`), implementasi sebelumnya menetapkan `bar_in_trade_high = min(bar.high, tp_price)` pada kebijakan `conservative` (memberikan kredit kenaikan TP penuh +5% pada trade yang dihentikan rugi di SL!), dan menetapkan `bar_in_trade_low = max(bar.low, sl_price)` pada kebijakan `optimistic` (membebankan kerugian penuh SL -5% pada trade yang keluar untung di TP!). Hal ini melanggar asumsi dasar kebijakan collision: jika konservatif mengasumsikan SL tercapai duluan dan menutup trade, maka reli lanjutan ke TP terjadi pasca-exit dan tidak dialami oleh posisi.
  - *Solusi (Baris 270–288 & 367–385)*:
    - `conservative`: Posisi keluar di `sl_price`. Ekskursi tertinggi in-trade dibatasi pada `bar.open` (atau `ep` jika entri hari ke-1 breakout), dan ekskursi terendah adalah `sl_price`. Trade tidak pernah mencapai TP saat masih aktif (MFE = 0.00%).
    - `optimistic`: Posisi keluar di `tp_price`. Ekskursi tertinggi in-trade adalah `tp_price`, dan ekskursi terendah dibatasi pada `bar.open` (atau `ep` jika entri hari ke-1 breakout). Trade tidak pernah mencapai SL saat masih aktif (MAE = 0.00%).
    - `ambiguous`: Posisi keluar di `bar.close` (close exit policy). Ekskursi in-trade mencakup pergerakan menuju kedua barrier: `bar_in_trade_high = min(bar.high, tp_price)` dan `bar_in_trade_low = max(bar.low, sl_price)`.
- **Pencegahan Kebocoran MAE Pasca-Exit pada Hari Entri Breakout (Baris 291–300)**:
  - *Masalah*: Saat sinyal breakout terpicu dan menyentuh TP di hari pertama, implementasi sebelumnya menetapkan `bar_in_trade_low = min(ep, bar.close)`. Jika di sesi sore setelah TP tersentuh harga pasar berbalik turun tajam di bawah harga entri (`close < ep`), penurunan pasca-exit tersebut bocor ke dalam in-trade MAE trade yang sudah ditutup untung.
  - *Solusi*: Karena posisi telah ditutup saat menyentuh `tp_price` dan SL tidak tersentuh, harga penutupan sore hari adalah pasca-exit, sehingga `bar_in_trade_low = ep` (in-trade MAE = 0.00%).
- **Scope A vs Scope B Trajectory**:
  - Scope A (in-trade bounded) membatasi seluruh ekskursi pada titik keluar aktual.
  - Scope B (`full_horizon_mfe`, `full_horizon_mae`, `full_horizon_time_to_peak`, `horizon_end_price`, `horizon_end_return`) menangkap seluruh dinamika harga selama `max_holding_days` tanpa mencemari metrik Scope A.
- **Penyelarasan Biaya Eksekusi BEI**:
  - Komisi beli 0.15%, komisi jual 0.25%, slippage 10 bps round-trip (5 bps per leg). Total friksi pada trade impas adalah -0.499% (~ 50 bps), selaras 100% dengan EV Hurdle Gate.

### B. [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py)
- **Struktur Domain Model 38 Kolom**:
  - Kolom entri/trade bersifat nullable (`entry_date`, `entry_price`, `mfe`, `mae`, `mfe_price`, `mae_price`, `time_to_peak`, `realized_return`, `net_return`).
  - Kolom Scope A baru: `gross_return`, `return_after_fees`, `return_after_fees_and_slippage`.
  - Kolom Scope B baru: `trigger_price`, `observation_end_date`, `full_horizon_mfe`, `full_horizon_mae`, `full_horizon_mfe_price`, `full_horizon_mae_price`, `full_horizon_time_to_peak`, `horizon_end_date`, `horizon_end_price`, `horizon_end_return`, `is_full_horizon_complete`.
- **Validasi Siklus Hidup (`validate_outcome_lifecycle`)**:
  - Memvalidasi bahwa sinyal `UNFILLED_EXPIRED` wajib memiliki metrik trade bernilai `None` dan `holding_days == 0`.

### C. [`python/outcomes/repository.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py)
- Migrasi otomatis tabel SQLite `outcomes_daily` ke 38 kolom tanpa kendala `NOT NULL` warisan pada field entri/trade.
- Helper terpusat `_outcome_to_db_params` dan pemetaan konsisten `_row_to_outcome`.

### D. [`docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)
- Diperbarui dengan dokumentasi lengkap formula matematika untuk Scope A (bounded gap open, intraday touch, dan collision policy) dan Scope B (counterfactual opportunity).
- Penjelasan perlakuan ambiguitas intraday dan rekapitulasi audit 31 rekor historis.

### E. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py)
- Memperluas `test_same_candle_collision_ambiguity_policies` dengan memverifikasi secara ketat MFE dan MAE pada ketiga kebijakan (`conservative`: MFE 0.0%, MAE -5.0%; `optimistic`: MFE +5.0%, MAE 0.0%; `ambiguous`: MFE +5.0%, MAE -5.0%).
- Menambahkan `test_breakout_entry_bar_tp_no_post_exit_mae_leakage` untuk memverifikasi bahwa pelemahan harga saat close tidak bocor ke dalam in-trade MAE saat TP telah tersentuh pada bar entri breakout.

---

## 2. Testing Checklist

Setelah perubahan ini diterapkan dan dijalankan di lingkungan produksi/staging, lakukan verifikasi berikut:

- [ ] **Scope A — In-Trade Excursion Bounding**:
  - [ ] Gap open exit (misal `BYAN` 2026-08-18): trade berhenti di open dan MFE/MAE candle exit dibatasi pada harga open (MFE = 0.00%, bukan +26.87%).
  - [ ] Intraday TP exit (misal `GIAA` 2026-08-03): MFE in-trade dibatasi pada `tp_price` (MFE = +7.41%, bukan +33.33%).
  - [ ] Intraday SL exit (misal `LPKR` 2026-09-15): MAE in-trade dibatasi pada `sl_price` (MAE = -6.67%, bukan -11.67%).
  - [ ] Same-candle collision under conservative policy: MFE dibatasi pada open/entry (0.0%), MAE pada `sl_price`.
  - [ ] Same-candle collision under optimistic policy: MAE dibatasi pada open/entry (0.0%), MFE pada `tp_price`.
- [ ] **Scope B — Counterfactual Full Horizon Opportunity**:
  - [ ] `full_horizon_mfe` dan `full_horizon_mae` mencatat seluruh pergerakan harga hingga `signal.max_holding_days`.
  - [ ] Pada trade yang keluar lebih awal, `full_horizon_mfe` berhasil menangkap lonjakan reli lanjutan (misal GIAA: +55.56%, BYAN: +26.87%).
  - [ ] Pada sinyal `UNFILLED_EXPIRED`, `full_horizon_mfe` dan `full_horizon_mae` dihitung relatif terhadap `trigger_price`.
- [ ] **Unfilled Breakout Signal Semantics**:
  - [ ] Sinyal breakout yang kedaluwarsa tanpa penembusan memiliki status `UNFILLED_EXPIRED`.
  - [ ] Kolom `entry_date`, `entry_price`, `exit_date`, `exit_price`, `mfe`, `mae`, `realized_return`, dan `net_return` bernilai strictly `NULL`.
  - [ ] `holding_days` bernilai 0.
  - [ ] `trigger_price` dan `observation_end_date` terisi nilai pemicu rencana dan tanggal akhir jendela observasi.
- [ ] **Execution Cost & Slippage Reconciliation**:
  - [ ] `return_after_fees` mencerminkan deduksi komisi bursa 0.15% beli dan 0.25% jual.
  - [ ] `return_after_fees_and_slippage` / `net_return` mencerminkan deduksi komisi ditambah 10 bps slippage round-trip.
  - [ ] Pada trade impas gross ($P_{\text{exit}} == P_{\text{entry}}$), net return bernilai -0.499% (~ 50 bps), selaras 100% dengan friksi EV Hurdle Gate.
- [ ] **Database Integrity & Idempotency**:
  - [ ] Skema tabel `outcomes_daily` termigrasi 38 kolom tanpa error dan kolom entry_date/entry_price/mfe/mae bersifat nullable.
  - [ ] Eksekusi `scripts/resolve_outcomes.py --force-recompute --save-db` memproses dan mengupdate seluruh 31 record matured secara konsisten.
  - [ ] Eksekusi `scripts/audit_historical_outcomes.py` menghasilkan 0 pelanggaran dari 31 record terverifikasi.
  - [ ] Seluruh unit dan integrasi test lulus 100% (`pytest` 420 passed) dan linter 100% bersih (`ruff check .` clean).
