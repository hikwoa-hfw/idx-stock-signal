# Walkthrough — Dual-Mode BEI Stock Signal Architecture Upgrade

## Ringkasan Eksekusi
Mengupgrade sistem sinyal saham BEI/IDX menjadi arsitektur Dual-Mode berbasis panduan resmi `docs/06_dual_mode_BEI_stock_signal_agent_guide.md`. Arsitektur ini memisahkan secara ketat dua rezim harga saham dengan dinamika mikrostruktur dan fraksi harga (tick size) yang berbeda:
- **MODE A: LOW_PRICE**: Rentang harga Rp 50 – Rp 300 (inklusif: `50 <= close <= 300`).
- **MODE B: HIGHER_PRICE**: Di atas Rp 300 (strictly `close > 300`).
- **EXCLUDED_BELOW_50**: Di bawah Rp 50 (`close < 50`) dilarang menghasilkan sinyal BUY.
- **INVALID**: Harga `<= 0`, `NaN`, atau `Inf` ditolak secara fail-closed.

Seluruh siklus hidup model champion/challenger, dataset, aturan fail-closed BUY guards, penyimpanan basis data SQLite, format siaran Telegram, command dispatcher, engine backtest, dan pipeline serverless AWS Lambda telah diperbarui dan diuji secara menyeluruh.

---

## 1. Rincian Perubahan Kode & File

### A. Domain Types & Boundary Rules (`python/common/types.py`)
- **Lines 10–25**: Menambahkan `PriceMode(str, Enum)` dengan nilai `LOW_PRICE`, `HIGHER_PRICE`, `EXCLUDED_BELOW_50`, dan `INVALID`.
- **Lines 28–46**: Menambahkan fungsi kanonikal `classify_price_mode(price: Optional[float]) -> str` dengan batas presisi:
  * `price is None` atau `np.isnan(price)` atau `price <= 0` $\rightarrow$ `INVALID`
  * `price < 50.0` $\rightarrow$ `EXCLUDED_BELOW_50`
  * `50.0 <= price <= 300.0` $\rightarrow$ `LOW_PRICE`
  * `price > 300.0` $\rightarrow$ `HIGHER_PRICE`
- **Lines 50–65**: Menambahkan helper `_normalize_mode_field(v)` untuk serialisasi dan deserialisasi Pydantic.
- **Lines 110–650**: Menambahkan field `mode: Optional[str] = None` dan `@property def mode_id` pada seluruh record domain:
  * `SignalRecord`, `PositionRecord`, `SignalOutcomeRecord`, `TradeRecord`, `LabelRecord`
  * `SignalConfig`, `Signal`, `Position`, `Prediction`

### B. Model Registry & Champion Lifecycle (`python/models/registry.py`)
- **Lines 45–60**: Menambahkan `mode: Optional[str] = None` dan properti `mode_id` pada `ModelMetadata`.
- **Lines 115–140**: Memperbarui `save_model` untuk merekam `mode` pada metadata JSON.
- **Lines 150–185**: Memperbarui `list_models(mode=...)` untuk mendukung penyaringan model berdasarkan mode.
- **Lines 200–245**: Mengisolasi champion resolution pada `get_champion(task, mode=...)`:
  * Jika `mode` diisi, mencari champion khusus untuk mode tersebut.
  * Tetap kompatibel dengan pencarian legacy unsegmented jika mode tidak diisi.
- **Lines 260–310**: Memperbarui `promote_to_champion` dan `rollback_champion` agar demosi dan promosi hanya memengaruhi model dengan `mode` yang identik (menjamin champion `LOW_PRICE` dan `HIGHER_PRICE` independen).

### C. Dataset & Feature Filtering (`python/models/dataset.py`)
- **Lines 70–95**: Menambahkan `Dataset.mode_id`, `Dataset.filter_by_mode(mode: str)`, dan penghitungan sebaran `mode_counts` pada `get_summary()`.
- **Lines 140–210**: Memperbarui `DatasetBuilder` (`__init__`, `build_from_records`, `build_from_dfs`, `build_from_db`) untuk mengklasifikasikan kolom `merged["mode"]` secara otomatis menggunakan `classify_price_mode` dan memfilter data latih/uji jika parameter `mode` diberikan.

### D. Signal Engine & Fail-Closed BUY Guards (`python/signals/engine.py`)
- **Lines 85–120**: Memperbarui `generate_signals` dengan parameter `mode: Optional[str] = None`. Mengambil champion spesifik mode saat `use_champion=True`.
- **Lines 130–175**: Menambahkan fail-closed guards ketat:
  * Ticker dengan `close < 50.0` atau invalid dilewati total dari sinyal BUY.
  * Kandidat dengan `probability <= 0.0` atau non-finite ditolak dari rekomendasi BUY.
  * Kandidat dengan `expected_return is None` ditolak jika `require_expected_return=True`.
  * Menetapkan `mode` kanonikal pada setiap `SignalRecord` yang diterbitkan.
- **Lines 240–295**: Mengimplementasikan `generate_dual_mode_signals(...)` yang mengeksekusi generasi sinyal terisolasi untuk `LOW_PRICE` dan `HIGHER_PRICE` serta mengembalikan struktur dictionary `{"LOW_PRICE": [...], "HIGHER_PRICE": [...]}`.

### E. Telegram Formatter & Bot Dispatcher (`services/telegram/formatter.py` & `services/telegram/bot.py`)
- **`services/telegram/formatter.py` Lines 140–265**:
  * Mengimplementasikan `format_dual_mode_signals(...)` sesuai Guide 06 Section 11 (Header tanggal, ringkasan pasar IHSG, [MODE A: LOW_PRICE (Rp 50 - Rp 300)], [MODE B: HIGHER_PRICE (> Rp 300)], dan catatan kepatuhan).
  * Mempertahankan kompatibilitas penuh pada `format_daily_signals(...)` untuk single-mode list maupun dual-mode dictionary.
- **`services/telegram/bot.py` Lines 70–120**:
  * Memperbarui handler `/daily` untuk menghasilkan dan memformat sinyal dual-mode.
  * Memperbarui handler `/model` untuk menampilkan champion aktif per mode (`LOW_PRICE` dan `HIGHER_PRICE`).
- **`scripts/run_telegram_bot.py` Line 78**:
  * Menghapus unused variable `offset` yang memicu peringatan ruff.

### F. Repository & Storage Immutability (`python/signals/repository.py`, `python/journal/repository.py`, `python/outcomes/repository.py`)
- **`python/signals/repository.py` Lines 35–85**:
  * Menambahkan kolom `mode TEXT` pada DDL `signals_daily`.
  * Menambahkan auto-migration DDL `ALTER TABLE signals_daily ADD COLUMN mode TEXT` jika kolom belum ada.
  * Menambahkan index `idx_signals_daily_mode`, persistensi field `mode`, dan filter `mode` pada query `get_signals` & `count_signals`.
- **`python/journal/repository.py` Lines 30–80**:
  * Menambahkan kolom `mode TEXT`, migrasi skema otomatis, index `idx_positions_mode`, dan pemetaan atribut record.
- **`python/journal/service.py` Lines 55–85**:
  * Menambahkan resolusi mode otomatis di `open_position` menggunakan `classify_price_mode(entry_price)`.
- **`python/outcomes/repository.py` Lines 35–85**:
  * Menambahkan kolom `mode TEXT`, migrasi skema otomatis, index `idx_outcomes_mode`, dan resolusi conflict `COALESCE(outcomes_daily.mode, excluded.mode)`.
- **`python/outcomes/engine.py` Lines 70–85**:
  * Meneruskan `signal.mode` ke `SignalOutcomeRecord`.

### G. Backtest Engine & Decision-Time Mode Immutability (`python/backtest/engine.py`)
- **Lines 45–95**: Menambahkan `mode` pada `_PendingOrder` dan `_ActivePosition`.
- **Lines 135–220**: Menambahkan parameter `mode: Optional[str] = None` pada `BacktestEngine.run`. Memfilter order masuk berdasarkan mode harga saat keputusan, dan mengikat mode keputusan tersebut ke `TradeRecord` saat posisi ditutup (menjamin immutabilitas mode keputusan).

### H. CLI Tools & Cloud Handlers (`scripts/*.py` & `python/cloud/handlers.py`)
- **`scripts/generate_signals.py`**: Menambahkan opsi `--mode [LOW_PRICE|HIGHER_PRICE|ALL]` dan `--dual-mode`, serta kolom `Mode` pada output tabel.
- **`scripts/send_daily_telegram.py`**: Menambahkan siaran dual-mode terpadu dan opsi `--single-mode` fallback.
- **`scripts/train_model.py`**: Menambahkan argumen `--mode` untuk melatih model terfokus pada sub-dataset tertentu.
- **`python/cloud/handlers.py`**: Memperbarui `lambda_daily_pipeline_handler` untuk menjalankan `generate_dual_mode_signals` dan menyiarkan notifikasi Telegram berformat dual-mode.

---

## 2. Pengujian Baru (Test Suite Verification)

### A. Unit Tests (`tests/unit/test_dual_mode.py`)
1. `test_classify_price_mode_boundaries`: Verifikasi batas harga kanonikal (49.99 $\rightarrow$ EXCLUDED, 50.0 $\rightarrow$ LOW_PRICE, 300.0 $\rightarrow$ LOW_PRICE, 300.01 $\rightarrow$ HIGHER_PRICE, 0/NaN/None $\rightarrow$ INVALID).
2. `test_decision_time_mode_immutability`: Menjamin posisi yang dibuka pada Rp 250 tetap bertag `LOW_PRICE` meskipun harga naik menjadi Rp 350.
3. `test_signal_engine_fail_closed_sub_50_exclusion`: Menolak saham harga < Rp 50 dari rekomendasi BUY.
4. `test_signal_engine_fail_closed_zero_probability`: Menolak kandidat BUY dengan probabilitas non-positif.
5. `test_signal_engine_fail_closed_missing_expected_return`: Menolak sinyal BUY jika model regresi tidak tersedia saat `require_expected_return=True`.
6. `test_model_registry_isolated_champion_per_mode`: Menguji isolasi champion independen untuk `LOW_PRICE` dan `HIGHER_PRICE`.
7. `test_model_registry_rollback_isolated_per_mode`: Memastikan rollback pada `LOW_PRICE` tidak memengaruhi champion `HIGHER_PRICE`.
8. `test_dataset_filter_and_summary_by_mode`: Memverifikasi pemfilteran dataset dan perhitungan `mode_counts`.
9. `test_telegram_dual_mode_formatting`: Memverifikasi struktur tampilan Telegram [MODE A: LOW_PRICE] dan [MODE B: HIGHER_PRICE].

### B. Integration Tests (`tests/integration/test_dual_mode_pipeline.py`)
1. `test_dual_mode_end_to_end_pipeline`: Menjalankan siklus end-to-end:
   - Generasi sinyal dual-mode simultan.
   - Penyimpanan ke basis data SQLite `signals_daily` dengan kolom `mode`.
   - Evaluasi outcome harian dengan propagasi `mode` ke `outcomes_daily`.
   - Pembukaan dan penutupan posisi di `positions_journal` dengan mempertahankan `mode`.
   - Simulasi backtesting dengan filter mode `LOW_PRICE`.

---

## 3. Rekonsiliasi Hasil Pengujian

- **Baseline Sebelum Perubahan**: 329 tests passed.
- **Pengujian Dual-Mode Baru**: +10 tests passed (9 unit tests + 1 integration test).
- **Total Pengujian Saat Ini**: **339 tests passed (100% kelulusan)**.
- **Linter Status**: `All checks passed!` (Ruff 100% clean).

---

## Testing Checklist
Item yang perlu diverifikasi oleh operator/pengguna:

- [ ] **CLI Signal Generator**: Jalankan `python scripts/generate_signals.py --dual-mode` dan pastikan output menampilkan section `LOW_PRICE` dan `HIGHER_PRICE`.
- [ ] **CLI Model Training**: Latih model spesifik mode dengan `python scripts/train_model.py --mode LOW_PRICE` dan pastikan metadata tersimpan dengan tag `mode: "LOW_PRICE"`.
- [ ] **Telegram Broadcast**: Jalankan `python scripts/send_daily_telegram.py --dry-run` dan periksa apakah format pesan memuat `[MODE A: LOW_PRICE]` dan `[MODE B: HIGHER_PRICE]`.
- [ ] **Telegram Bot Command**: Uji command `/daily` dan `/model` pada bot Telegram untuk melihat sinyal dan champion per mode.
- [ ] **SQLite Database Schema**: Buka `database/stock_signals.db` dan pastikan kolom `mode` telah tersedia di tabel `signals_daily`, `positions_journal`, dan `outcomes_daily`.
- [ ] **AWS Lambda Staging**: Uji invoke `idx-daily-pipeline-staging` dan pastikan sinyal dual-mode tersimpan ke basis data S3.
