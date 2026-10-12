# Walkthrough: Skeptical Review & Audit Fixes for Indonesian Stock AI (Phase 0)

Sesi ini melakukan audit mendalam terhadap hasil setup Phase 0 pada proyek **AI Indonesian Stock Daily Signal Generator (BEI)** di `C:\Users\DROSE250122\Documents\Personal\indonesian-stock-ai`, memperbaiki celah teknis, menambahkan dokumen spesifikasi yang tertinggal, melengkapi pengujian domain models, mengintegrasikan loader `.env`, serta mengonfigurasi dan memvalidasi linter `ruff`.

---

## Task Breakdown & Findings

### 1. Salinan Dokumen Spesifikasi yang Tertinggal
- **Temuan**: Folder `Downloads` berisi dua dokumen spesifikasi: `03_plan_ai_stock_signal_BEI_daily.md` (38KB, rencana arsitektur sistem) dan `04_ai_agent_coding_development_guide_BEI_stock_signal.md` (46KB, execution guide). Pekerja sebelumnya hanya menyalin file 04 dan melewatkan file 03.
- **Tindakan**:
  - Menyalin `C:\Users\DROSE250122\Downloads\03_plan_ai_stock_signal_BEI_daily.md` ke [docs/03_plan_ai_stock_signal_BEI_daily.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/03_plan_ai_stock_signal_BEI_daily.md).
  - Memperbarui [README.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/README.md#L74-L79) dan smoke test untuk mereferensikan kedua dokumen secara eksplisit.

### 2. Penanganan Deprecated `datetime.utcnow()` pada Domain Models
- **Temuan**: Pada [python/common/types.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py), model `Prediction` dan `Outcome` menggunakan `Field(default_factory=datetime.utcnow)`. Di Python 3.12+, `datetime.utcnow()` memicu `DeprecationWarning` dan dijadwalkan untuk dihapus.
- **Tindakan**:
  - Mengubah import: `from datetime import date, datetime, timezone`.
  - Mengubah default factory pada baris 49 dan 57 menjadi lambda timezone-aware: `default_factory=lambda: datetime.now(timezone.utc)`.

### 3. Pengujian Unit untuk Seluruh Domain Models
- **Temuan**: Sebelumnya [tests/unit/test_types.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_types.py) mengimpor `Outcome` dan `ModelVersion` namun tidak pernah mengujinya sama sekali, sehingga `datetime.utcnow()` tidak pernah terpanggil saat test run. Model `Prediction` bahkan sama sekali tidak diuji.
- **Tindakan**:
  - Menambahkan test `test_prediction_model_validation` (verifikasi model, probabilitas, dan tzinfo pada created_at).
  - Menambahkan test `test_outcome_model_validation` (verifikasi status outcome TP_HIT, realized return, holding days, dan tzinfo).
  - Menambahkan test `test_model_version_validation` (verifikasi versioning, model type, metrics dictionary, dan status champion).
  - Memperbarui [tests/unit/test_smoke.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_smoke.py) untuk memastikan integritas file dokumen spesifikasi, rules, summary, dan walkthrough.
  - Total test suite meningkat dari 5 test menjadi 8 test lulus (8/8 passed).

### 4. Integrasi Otomatis `.env` Loader pada Settings
- **Temuan**: Paket `python-dotenv` tercantum di `requirements.txt`, namun `python/config/settings.py` tidak pernah memanggil `load_dotenv()`. Akibatnya konfigurasi lokal `.env` tidak pernah termuat ke dalam runtime aplikasi. Selain itu default SQLite URI menggunakan path dengan backslash yang tidak standar.
- **Tindakan**:
  - Menambahkan `from dotenv import load_dotenv` dan memanggil `load_dotenv(PROJECT_ROOT / ".env")` sebelum inisialisasi class `Settings` di [python/config/settings.py](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/config/settings.py#L9).
  - Menormalisasi URL SQLite default dengan `PROJECT_ROOT.as_posix()`.

### 5. Setup & Verifikasi Linter `ruff` (Phase 0 Acceptance Criteria)
- **Temuan**: Kriteria penerimaan Phase 0 di development guide mencakup `pytest passes`, `lint passes`, `project starts locally`. Linter `ruff` belum terinstal di `.venv`, dan saat dieksekusi memicu 4 error linting (E501 line too long pada `settings.py` dan I001 unsorted imports).
- **Tindakan**:
  - Menginstal `ruff` dan `pytest-cov` ke `.venv`.
  - Merapikan pemformatan dan panjang baris di `python/config/settings.py` dan `tests/unit/test_types.py`.
  - Menjalankan `ruff check .` dan memverifikasi seluruh file 100% clean tanpa warning/error.
  - Memperbarui target `clean` di [Makefile](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/Makefile#L16-L18) agar menggunakan script Python cross-platform dan tidak gagal di lingkungan Windows.

---

## Changes by File and Line Number

1. **`docs/03_plan_ai_stock_signal_BEI_daily.md`** (Lines 1–2787):
   - Dokumen rencana arsitektur sistem disalin dari `C:\Users\DROSE250122\Downloads\03_plan_ai_stock_signal_BEI_daily.md`.
2. **`python/common/types.py`**:
   - Line 1: Menambahkan `timezone` ke import `datetime`.
   - Line 49: `Prediction.created_at` diganti menjadi `default_factory=lambda: datetime.now(timezone.utc)`.
   - Line 57: `Outcome.evaluated_at` diganti menjadi `default_factory=lambda: datetime.now(timezone.utc)`.
3. **`python/config/settings.py`**:
   - Line 4: Import `from dotenv import load_dotenv`.
   - Line 9: Eksekusi `load_dotenv(PROJECT_ROOT / ".env")`.
   - Lines 14–18: Menormalisasi `PROJECT_ROOT.as_posix()` pada SQLite URI default.
   - Lines 27–31: Memecah `model_registry_path` ke multi-baris agar sesuai standar panjang baris (`ruff` E501 <= 100 chars).
4. **`tests/unit/test_smoke.py`**:
   - Lines 12–17: Memverifikasi keberadaan `docs/03_plan_ai_stock_signal_BEI_daily.md`, `docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md`, `PROJECT_RULES.md`, `summary.md`, dan `walkthrough.md`.
5. **`tests/unit/test_types.py`**:
   - Lines 1–11: Mengatur import sorting ruff.
   - Line 24: Menambahkan assertion `max_holding_days == 10`.
   - Lines 39–77: Menambahkan pengujian untuk `test_prediction_model_validation`, `test_outcome_model_validation`, dan `test_model_version_validation`.
6. **`Makefile`**:
   - Lines 16–18: Mengganti perintah Unix `find ... rm -rf` menjadi script Python built-in `pathlib`/`shutil` yang bekerja di Windows maupun Linux.
7. **`README.md`**:
   - Lines 76–78: Menambahkan link referensi ke `docs/03_plan_ai_stock_signal_BEI_daily.md`.
8. **`summary.md`**:
   - Lines 15–28: Menambahkan entri nomor 2 (Skeptical Review & Audit Perbaikan Setup Phase 0) secara append-only.

---

## Verification Results

1. **Unit Testing:**
   - Command: `.\.venv\Scripts\python.exe -m pytest -v`
   - Result: `8 passed in 0.41s`
   - Strict warning check: `.\.venv\Scripts\python.exe -W error -m pytest` lulus tanpa runtime/deprecation warning.
2. **Linting Check:**
   - Command: `.\.venv\Scripts\ruff.exe check .`
   - Result: `All checks passed!`
3. **Formatting Check:**
   - Command: `.\.venv\Scripts\ruff.exe format --check .`
   - Result: `28 files already formatted.`
4. **Git Workspace Cleanliness:**
   - Command: `git status`
   - Verifikasi trackable changes siap di-commit.

---

## Testing Checklist

Berikut checklist yang perlu diverifikasi setelah audit perbaikan:
- [x] Dokumen arsitektur lengkap `03_plan_ai_stock_signal_BEI_daily.md` dan `04_ai_agent_coding_development_guide_BEI_stock_signal.md` tersedia di `docs/`.
- [x] Python virtual environment `.venv` memiliki dependensi runtime dan development lengkap (`pytest`, `pydantic`, `python-dotenv`, `ruff`, `pytest-cov`).
- [x] Linter `ruff check .` berjalan dan melaporkan `All checks passed!`.
- [x] Seluruh unit test (`test_smoke.py`, `test_types.py`) lulus 100% (8/8 passed) tanpa `DeprecationWarning`.
- [x] File `.env` secara otomatis dibaca oleh `python/config/settings.py` via `python-dotenv`.
- [x] Aturan lokal `PROJECT_RULES.md` dan `.agents/rules/project_rules.md` tetap utuh dan mendokumentasikan kewajiban `summary.md` APPEND-ONLY.
- [x] `summary.md` telah diperbarui secara APPEND-ONLY (riwayat sebelumnya tidak hilang).
- [ ] Pengguna memverifikasi eksekusi linter secara mandiri: `.\.venv\Scripts\ruff.exe check .`.
- [ ] Pengguna memverifikasi eksekusi test secara mandiri: `.\.venv\Scripts\python.exe -m pytest`.
