# Walkthrough — Phase 9: Outcome Engine & Skeptical Review Audit

Dokumen ini mencatat rincian implementasi **Phase 9 — Outcome Engine** beserta hasil **Skeptical Review & Audit Perbaikan** sesuai dokumen arsitektur `docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` (Sections 24, 25, 50, dan Phase 9 Section 65) serta `docs/03_plan_ai_stock_signal_BEI_daily.md`.

---

## 1. Task Breakdown & Implementasi

Outcome Engine bertugas merekonsiliasi rekomendasi sinyal harian (`signals_daily`) dengan data pergerakan harga pasar riil (`daily_bars`) untuk membuktikan edge model secara objektif melalui evaluasi triple barrier dan snapshot path harian.

### A. Domain Models (`python/common/types.py`)
- **`SignalOutcomeRecord` / `OutcomeRecord`**:
  - `outcome_id`: UUID string default.
  - `signal_id`: String ID referensi ke `signals_daily`.
  - `ticker`: Simbol saham ter-normalisasi uppercase (removesuffix `.JK`).
  - `signal_date`: Tanggal generasi sinyal (Hari $t$).
  - `entry_date`: Tanggal eksekusi entry (Hari $t+1$).
  - `entry_price`: Harga beli pada pembukaan (Open price Hari $t+1$).
  - `outcome_status`: Status trade (`OPEN`, `TP`, `SL`, `EXPIRY`, `AMBIGUOUS`).
  - `realized_return`: Net percentage return dari entry ke exit (`None` saat `OPEN`).
  - `holding_days`: Durasi hari bursa posisi dipegang.
  - `mfe`: Maximum Favorable Excursion (persentase gain tertinggi selama holding).
  - `mae`: Maximum Adverse Excursion (persentase loss terendah selama holding).
  - `exit_date`, `exit_price`, `exit_reason`, `resolved_at`, `notes`.
  - Lifecycle validator: menjamin status `OPEN` tidak memiliki harga/tanggal keluar, tidak memiliki `realized_return`, tidak memiliki `resolved_at`, serta menolak `entry_date < signal_date` untuk menjaga kausalitas waktu.
- **`SignalDailySnapshot`**:
  - `snapshot_id`: UUID string default.
  - `signal_id`: Referensi sinyal.
  - `snapshot_date`: Tanggal observasi bursa.
  - `holding_day`: Hari bursa ke-$k$ ($k \ge 1$).
  - `close_price`, `high_price`, `low_price`: Harga OHLC harian dengan validasi invariant `high_price >= low_price`.
  - `return_from_entry`: Return pada penutupan hari $k$.
  - `mfe_so_far`: Running peak gain hingga hari $k$.
  - `mae_so_far`: Running worst drawdown hingga hari $k$.

### B. Outcome Storage (`python/outcomes/repository.py`)
- Menggunakan SQLite dengan WAL mode dan synchronous normal:
  - Tabel `outcomes_daily`: Menyimpan record outcome aktif (`OPEN`) dan terselesaikan (`TP`, `SL`, `EXPIRY`, `AMBIGUOUS`). Diindeks pada `(signal_id)`, `(ticker)`, `(signal_date)`, `(outcome_status)` dengan constraint `UNIQUE(signal_id)`.
  - Tabel `signal_snapshots_daily`: Menyimpan progression path harian setiap sinyal. Diindeks pada `(signal_id, snapshot_date)` dengan constraint `UNIQUE(signal_id, snapshot_date)`.
- Method repository:
  - `save_outcome` / `save_outcomes`: Upsert idempotensial atomik dengan preservasi `notes` via `COALESCE(excluded.notes, outcomes_daily.notes)` dan `resolved_at` via `COALESCE(outcomes_daily.resolved_at, excluded.resolved_at)`.
  - `get_outcome_by_signal_id`: Mengambil outcome berdasarkan ID sinyal.
  - `get_outcome_statuses_map`: Batch lookup efisien memetakan `signal_id -> (outcome_id, outcome_status, notes)`.
  - `get_open_outcomes`: Mengambil semua sinyal berstatus `OPEN` (opsional filter `as_of_date` dan `ticker`).
  - `get_matured_outcomes`: Mengambil outcome yang sudah selesai/matur (`!= 'OPEN'`), mendukung filter rentang tanggal dan ticker.
  - `save_snapshots`: Upsert idempotensial snapshot harian (`ON CONFLICT(signal_id, snapshot_date) DO UPDATE`).
  - `get_snapshots_by_signal_id`: Mengambil seluruh urutan snapshot harian berdasarkan `holding_day ASC`.

### C. Triple Barrier Outcome Engine (`python/outcomes/engine.py`)
- Aturan evaluasi triple barrier:
  1. **Hari $t$**: Sinyal diterbitkan (`signal.signal_date`).
  2. **Hari $t+1$**: Eksekusi entry pada harga Open candle pertama setelah sinyal (`forward_bars[0].open`). Status menjadi `OPEN` aktif.
  3. **Hari-hari berikutnya ($k = 1 \dots \text{max\_holding\_days}$)**:
     - Setiap candle merekam `SignalDailySnapshot` dengan metrik `mfe_so_far` dan `mae_so_far`.
     - Barrier TP: `bar.high >= signal.tp_price`.
     - Barrier SL: `bar.low <= signal.sl_price`.
     - **Penanganan Ambiguitas Same-Candle** (Section 15):
       - Jika gap up pada open (`open >= TP`): TP dieksekusi pada open.
       - Jika gap down pada open (`open <= SL`): SL dieksekusi pada open.
       - Jika candle menyentuh TP dan SL di hari yang sama:
         * Policy `conservative` (default): Asumsi SL tersentuh lebih dahulu, exit pada `sl_price`.
         * Policy `optimistic`: Asumsi TP tersentuh lebih dahulu, exit pada `tp_price`.
         * Policy `ambiguous`: Tandai sebagai `AMBIGUOUS`, exit pada `close`.
     - **Expiry**: Jika mencapai `max_holding_days` (default 10 hari) tanpa menyentuh TP atau SL, posisi keluar pada `bar.close` hari ke-10 dengan status `EXPIRY`.
     - **In-flight**: Jika belum mencapai batas hari dan belum menyentuh barrier, status tetap `OPEN`.
- Method engine:
  - `evaluate_signal`: Evaluasi murni in-memory terhadap list candle forward, mendukung parameter `notes` untuk preservasi catatan analisis.
  - `resolve_signal_by_id`: Evaluasi sinyal tunggal dari database. Jika sinyal sudah berstatus matur, mengembalikan data tersimpan secara idempotensial tanpa re-evaluasi kecuali `force_recompute=True`.
  - `resolve_all_signals`: Rekonsiliasi sinyal aktif dan belum dievaluasi dengan batch status map dan commit batch atomik ke SQLite.

### D. Matured Dataset Builder (`python/outcomes/dataset.py`)
- Menggabungkan data hasil outcome yang sudah matur (`outcome_status != 'OPEN'`) dengan:
  - Metadata sinyal asli dari `signals_daily` (`predicted_probability`, `expected_return`, `score`, `model_version`, `entry_low/high`, `tp/sl_price`).
  - Fitur teknikal dan pasar dari `feature_snapshot` (`rsi14`, `atr14`, `return_5d`, dll).
  - Target biner ML: `binary_target = 1` jika TP, `0` jika lainnya.
  - Mendukung parameter `exclude_ambiguous` untuk memfilter data ambiguitas sebelum dipakai model training.
  - Menggunakan pre-fetch caching sinyal untuk eliminasi query N+1.
- Fungsi `export_matured_dataset` untuk ekspor bersih ke format CSV atau JSON sebagai input langsung untuk Phase 10 (Model Evaluation) dan Phase 11 (Retraining Pipeline).

### E. CLI Runner & Automation (`scripts/resolve_outcomes.py`, `Makefile`)
- CLI script dengan opsi:
  - `--as-of-date`: Evaluasi per tanggal tertentu (YYYY-MM-DD).
  - `--ambiguity-policy`: Pilihan `conservative`, `optimistic`, `ambiguous`.
  - `--save-db`: Menyimpan hasil evaluasi dan snapshot ke SQLite.
  - `--export-matured`: Format ekspor dataset (`csv` atau `json`).
  - `--export-path`: Lokasi file ekspor.
  - `--ticker`: Filter ticker tertentu.
  - `--exclude-ambiguous`: Memfilter record AMBIGUOUS saat ekspor dataset.
- Target `Makefile`:
  - `make outcomes` menjalankan `python -m scripts.resolve_outcomes --save-db`.

---

## 2. File & Line Changes Breakdown

1. [python/common/types.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py) (lines 874–1035)
   - Menambahkan `SignalOutcomeRecord`, alias `OutcomeRecord`, dan `SignalDailySnapshot`.
   - Menambahkan validasi lifecycle: `OPEN` dilarang memiliki `realized_return` dan `resolved_at`, `entry_date >= signal_date`.
   - Menambahkan validator invariant candle: `high_price >= low_price`.
2. [python/outcomes/repository.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py) (lines 1–425)
   - SQLite repository tabel `outcomes_daily` dan `signal_snapshots_daily`.
   - Menambahkan preservasi `notes` dan `resolved_at` via `COALESCE` pada upsert `save_outcome` dan `save_outcomes`.
   - Menambahkan `get_outcome_statuses_map` untuk optimasi batch lookup.
   - Menambahkan filter `ticker` pada `get_open_outcomes`.
3. [python/outcomes/engine.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py) (lines 1–350)
   - Triple barrier evaluation engine dengan snapshot path tracking.
   - Meneruskan `notes` pada `evaluate_signal`.
   - Idempotent return pada `resolve_signal_by_id` dengan opsi `force_recompute`.
   - Optimasi `resolve_all_signals` menggunakan batch status map dan commit simpanan atomik.
4. [python/outcomes/dataset.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/dataset.py) (lines 1–125)
   - `build_matured_outcomes_dataset` dengan pre-fetch caching metadata sinyal.
   - Penambahan opsi `exclude_ambiguous` untuk membersihkan dataset training ML.
   - `export_matured_dataset` untuk format CSV dan JSON.
5. [python/outcomes/__init__.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/__init__.py) (lines 1–12)
   - Export publik modul `OutcomeEngine`, `OutcomeRepository`, `build_matured_outcomes_dataset`, `export_matured_dataset`.
6. [scripts/resolve_outcomes.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/resolve_outcomes.py) (lines 1–195)
   - Menambahkan opsi `--exclude-ambiguous` pada parser CLI dan meneruskannya ke dataset exporter.
7. [Makefile](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/Makefile) (lines 1, 46–47)
   - Menambahkan target `outcomes` ke `.PHONY` dan mendefinisikan `make outcomes`.
8. [tests/unit/test_outcomes.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py) (lines 1–555)
   - 16 unit tests mencakup: TP hit, SL hit, max holding expiry, ambiguitas same-candle, gap up/down open, MFE/MAE multi-day progression, status OPEN in-flight, repository CRUD/snapshots, lifecycle `resolve_signal_by_id`, preservasi notes, filter open outcomes, dan exclude ambiguous dataset building.
9. [tests/integration/test_outcome_pipeline.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/integration/test_outcome_pipeline.py) (lines 1–246)
   - 2 integration tests menguji end-to-end signal lifecycle, outcome resolution, matured dataset CSV/JSON export, dan CLI execution.
10. [tests/unit/test_types.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_types.py) (lines 615–730)
    - Validasi Pydantic lengkap untuk lifecycle `SignalOutcomeRecord` dan invariant `SignalDailySnapshot`.
11. [tests/unit/test_smoke.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_smoke.py)
    - Verifikasi smoke test struktur file Phase 9.
12. [summary.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/summary.md) (lines 316–352)
    - Log entri 21 (Phase 9 Implementation) dan entri 22 (Skeptical Review & Audit Fixes).

---

## 3. Verification Record

- **Test Suite Pass Rate**:
  ```text
  250 passed in 29.03s (100% pass rate, 0 failed, 0 warnings)
  ```
- **Linter Status**:
  ```text
  ruff check . -> All checks passed!
  ```

---

## 4. Testing Checklist

Setelah deploy atau update branch, jalankan checklist verifikasi berikut:

- [ ] Jalankan test suite lengkap:
  ```bash
  pytest
  ```
- [ ] Jalankan linter:
  ```bash
  ruff check .
  ```
- [ ] Verifikasi CLI resolver help:
  ```bash
  python -m scripts.resolve_outcomes --help
  ```
- [ ] Uji coba eksekusi manual resolver ke memory DB:
  ```bash
  python -m scripts.resolve_outcomes --database-url :memory:
  ```
- [ ] Uji coba target Makefile:
  ```bash
  make outcomes
  ```
- [ ] Uji coba ekspor dataset matured ke file CSV dengan filter ambiguous:
  ```bash
  python -m scripts.resolve_outcomes --save-db --export-matured csv --exclude-ambiguous --export-path data/matured_outcomes.csv
  ```
- [ ] Periksa bahwa tabel `outcomes_daily` dan `signal_snapshots_daily` terbuat dengan indeks yang benar di SQLite database.
