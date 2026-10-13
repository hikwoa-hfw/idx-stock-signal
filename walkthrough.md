# Walkthrough — Dual-Mode BEI Stock Signal Architecture Upgrade & Audit Remediation

## Ringkasan Eksekusi
Mengupgrade sistem sinyal saham BEI/IDX menjadi arsitektur Dual-Mode berbasis panduan resmi `docs/06_dual_mode_BEI_stock_signal_agent_guide.md`, diikuti audit skeptis dan perbaikan mendalam terhadap isolasi champion, penanganan label engine, segmentasi dataset outcome, dan sinkronisasi cloud:
- **MODE A: LOW_PRICE**: Rentang harga Rp 50 – Rp 300 (inklusif: `50 <= close <= 300`).
- **MODE B: HIGHER_PRICE**: Di atas Rp 300 (strictly `close > 300`).
- **EXCLUDED_BELOW_50**: Di bawah Rp 50 (`close < 50`) dilarang menghasilkan sinyal BUY.
- **INVALID**: Harga `<= 0`, `NaN`, atau `Inf` ditolak secara fail-closed.

Seluruh siklus hidup model champion/challenger, dataset, aturan fail-closed BUY guards, penyimpanan basis data SQLite, format siaran Telegram, command dispatcher, engine backtest, dan pipeline serverless AWS Lambda telah diperbarui dan diuji secara menyeluruh (343 passed tests, 100% pass rate, ruff clean).

---

## 1. Rincian Perubahan Kode & File

### A. Domain Types & Boundary Rules (`python/common/types.py`)
- **Lines 136–162**: Menambahkan `PriceMode(str, Enum)` (`LOW_PRICE`, `HIGHER_PRICE`, `EXCLUDED_BELOW_50`, `INVALID`) dan fungsi kanonikal `classify_price_mode(price: Optional[float]) -> str`.
- **Lines 185–1005**: Menambahkan field `mode: Optional[str] = None` dan `@property def mode_id` pada seluruh record domain:
  * `SignalRecord`, `PositionRecord`, `SignalOutcomeRecord`, `TradeRecord`, `LabelRecord`
  * `SignalConfig`, `Signal`, `Position`, `Prediction`

### B. Signal Engine & Strict Mode Isolation (`python/signals/engine.py`)
- **Lines 230–315**: Memperbaiki resolusi model classifier dan regressor:
  * Menolak keras cross-mode champion borrowing: jika mode `LOW_PRICE` tidak memiliki champion, dilarang meminjam champion `HIGHER_PRICE` (dan sebaliknya).
  * Menolak eksekusi `model_version` jika `meta.mode` tidak kompatibel dengan mode yang diminta (`eff_mode`).
  * Mencegah peminjaman model regressor lintas-mode.
- **Lines 320–350**: Memperketat fail-closed BUY policy:
  * Ticker dengan `close < 50.0` atau invalid dieksklusi mutlak dari sinyal BUY.
  * Kandidat dengan `probability <= 0.0` atau non-finite ditolak dari rekomendasi BUY.
  * Kandidat dengan `expected_return is None` ditolak jika `require_expected_return=True`.
- **Lines 500–550**: Memperbarui `generate_dual_mode_signals(...)` agar mengisolasi kegagalan model per mode (fail-closed jika suatu mode belum memiliki champion tanpa membatalkan mode lainnya).

### C. Label Engine & Storage Mode Support (`python/labels/engine.py` & `python/labels/repository.py`)
- **`python/labels/engine.py` Lines 170–200**:
  * Mengintegrasikan `classify_price_mode(ep)` saat pembuatan `LabelRecord` di `compute_label_for_bar`.
- **`python/labels/repository.py` Lines 50–390**:
  * Menambahkan kolom `mode TEXT` pada tabel `labels_daily` dan auto-migration DDL `ALTER TABLE labels_daily ADD COLUMN mode TEXT`.
  * Menambahkan indeks `idx_labels_mode` pada tabel `labels_daily`.
  * Memperbarui `save_labels` untuk menyimpan `mode`.
  * Memperbarui `get_labels`, `get_all_labels`, dan `count_labels` dengan parameter filter `mode: Optional[str] = None`.
  * Memperbarui `_row_to_record` untuk memetakan kolom `mode` ke `LabelRecord`.

### D. Outcomes Dataset & Model Evaluation Mode Support (`python/outcomes/dataset.py` & `scripts/evaluate_models.py`)
- **`python/outcomes/dataset.py` Lines 10–65**:
  * Menambahkan parameter `mode: Optional[str] = None` pada `build_matured_outcomes_dataset`.
  * Menyertakan kolom `mode` pada DataFrame hasil untuk pelacakan evaluasi independen.
- **`scripts/evaluate_models.py` Lines 30–270**:
  * Menambahkan opsi CLI `--mode [LOW_PRICE|HIGHER_PRICE|ALL]`.
  * Mengisolasi pencarian champion dan pemfilteran dataset evaluasi berdasarkan mode.
  * Meneruskan `mode` saat mempromosikan model ke champion (`registry.promote_to_champion(chall_ver, mode=args.mode)`).

### E. Model Registry & Champion Lifecycle Isolation (`python/models/registry.py`)
- **Lines 45–60**: Menambahkan `mode: Optional[str] = None` dan properti `mode_id` pada `ModelMetadata`.
- **Lines 150–235**: Memperbaiki `_demote_existing_champions` agar pendaftaran model unsegmented (mode=None) tidak mendemosi model champion yang telah memiliki tag mode (`LOW_PRICE` atau `HIGHER_PRICE`).
- Memperbaiki `rollback_champion` agar mendeteksi dan mempertahankan mode target model saat rollback.

### F. Dataset Builder & Filtering (`python/models/dataset.py`)
- **Lines 105–150**: Menambahkan `Dataset.mode_id`, `Dataset.filter_by_mode(mode: str)`, dan penghitungan sebaran `mode_counts` pada `get_summary()`.
- **Lines 230–335**: Memperbarui `DatasetBuilder` untuk mengklasifikasikan `merged["mode"]` secara otomatis dan menyediakan `build_dataset(mode=...)`.

### G. Telegram Formatter, Bot & CLI Scripts
- **`services/telegram/formatter.py` Lines 125–260**:
  * Mengimplementasikan `format_dual_mode_signals(...)` sesuai Guide 06 Section 11 (Header tanggal, ringkasan pasar IHSG, [MODE A: LOW_PRICE (Rp 50 - Rp 300)], [MODE B: HIGHER_PRICE (> Rp 300)]).
- **`services/telegram/bot.py` Lines 110–150**:
  * Memperbarui handler `/model` untuk menampilkan champion aktif per mode (`LOW_PRICE` dan `HIGHER_PRICE`).
- **`scripts/generate_signals.py`**:
  * Menambahkan opsi `--mode` dan `--dual-mode`, menyertakan kolom `mode` pada export CSV (`print_csv_signals`), dan meneruskan `model_version` pada eksekusi dual-mode.
- **`scripts/send_daily_telegram.py`**:
  * Meneruskan `model_version` ke `generate_dual_mode_signals`.
- **`python/cloud/handlers.py`**:
  * Memperbarui `lambda_daily_pipeline_handler` untuk mendeteksi ketersediaan champion mode (`low_champ` atau `high_champ`).

---

## 2. Pengujian (Test Suite Verification)

### A. Unit Tests (`tests/unit/test_dual_mode.py`) — 13 Tests Passed
1. `test_classify_price_mode_boundaries`: Verifikasi batas harga kanonikal (49.99 $\rightarrow$ EXCLUDED, 50.0 $\rightarrow$ LOW_PRICE, 300.0 $\rightarrow$ LOW_PRICE, 300.01 $\rightarrow$ HIGHER_PRICE, 0/NaN/None $\rightarrow$ INVALID).
2. `test_mode_immutability_on_price_crossing`: Menjamin posisi yang dibuka pada Rp 280 tetap bertag `LOW_PRICE` meskipun harga naik menjadi Rp 350.
3. `test_outcome_record_mode_immutability`: Menjamin outcome sinyal mempertahankan mode saat pembukaan.
4. `test_signal_engine_fail_closed_on_zero_or_invalid_prob`: Menolak kandidat BUY dengan probabilitas non-positif.
5. `test_signal_engine_strictly_excludes_sub_50`: Menolak saham harga < Rp 50 dari rekomendasi BUY.
6. `test_signal_engine_fail_closed_on_missing_required_expected_return`: Menolak sinyal BUY jika model regresi tidak tersedia saat `require_expected_return=True`.
7. `test_independent_champion_lifecycle`: Menguji isolasi champion independen untuk `LOW_PRICE` dan `HIGHER_PRICE`.
8. `test_dataset_dual_mode_filter_and_summary`: Memverifikasi pemfilteran dataset dan perhitungan `mode_counts`.
9. `test_telegram_dual_mode_formatter`: Memverifikasi struktur tampilan Telegram [MODE A: LOW_PRICE] dan [MODE B: HIGHER_PRICE].
10. `test_signal_engine_mode_isolation_and_no_cross_champion_borrowing`: Verifikasi kegagalan fail-closed jika mode tidak memiliki champion dan larangan menggunakan champion mode lain.
11. `test_label_engine_and_repository_mode_support`: Verifikasi pembuatan label bertag mode dan penyimpanan/kueri tabel `labels_daily` dengan kolom `mode`.
12. `test_outcomes_dataset_mode_segmentation`: Verifikasi pemfilteran dataset outcome matang berdasarkan mode.
13. `test_registry_unsegmented_champion_does_not_demote_segmented`: Verifikasi bahwa pendaftaran model unsegmented tidak mendemosi model champion bertag mode.

### B. Integration Tests (`tests/integration/test_dual_mode_pipeline.py`) — 1 Test Passed
1. `test_dual_mode_end_to_end_pipeline`: Siklus end-to-end generasi sinyal dual-mode simultan, persistensi `signals_daily`, evaluasi outcome, journaling posisi, dan backtest mode terisolasi.

---

## 3. Rekonsiliasi Hasil Pengujian

- **Baseline Sebelum Perubahan**: 329 tests passed.
- **Pengujian Dual-Mode**: +14 tests passed (13 unit tests + 1 integration test).
- **Total Pengujian Saat Ini**: **343 tests passed (100% kelulusan dalam 48.35s)**.
- **Linter Status**: `All checks passed!` (Ruff 100% clean).

---

## Testing Checklist
Item yang perlu diverifikasi oleh operator/pengguna setelah deployment:

- [ ] **CLI Signal Generator**: Jalankan `python scripts/generate_signals.py --dual-mode` dan pastikan output tabel menampilkan kolom `Mode` serta kandidat terpisah.
- [ ] **CLI CSV Export**: Jalankan `python scripts/generate_signals.py --dual-mode --format csv` dan periksa header memuat kolom `mode`.
- [ ] **CLI Model Training per Mode**: Latih model spesifik mode dengan `python scripts/train_model.py --mode LOW_PRICE` dan `python scripts/train_model.py --mode HIGHER_PRICE`.
- [ ] **CLI Model Evaluation per Mode**: Evaluasi model dengan `python scripts/evaluate_models.py --from-outcomes --mode LOW_PRICE`.
- [ ] **Telegram Broadcast**: Jalankan `python scripts/send_daily_telegram.py --dry-run` dan periksa apakah format pesan memuat `[MODE A: LOW_PRICE]` dan `[MODE B: HIGHER_PRICE]`.
- [ ] **Telegram Bot Command**: Uji command `/daily` dan `/model` pada bot Telegram untuk melihat sinyal dan champion terisolasi per mode.
- [ ] **SQLite Database Schema**: Buka basis data dan pastikan kolom `mode` telah tersedia pada tabel `signals_daily`, `positions_journal`, `outcomes_daily`, dan `labels_daily`.
- [ ] **AWS Lambda Staging**: Uji invoke `idx-daily-pipeline-staging` dan pastikan sinyal dual-mode tersimpan ke basis data S3.
