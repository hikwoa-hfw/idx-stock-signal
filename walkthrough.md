# Walkthrough: Bootstrap & Setup Indonesian Stock AI Project (Phase 0)

Sesi ini menyelesaikan inisialisasi awal repository dan arsitektur dasar untuk proyek **AI Indonesian Stock Daily Signal Generator (BEI)** di lokasi `C:\Users\DROSE250122\Documents\Personal\indonesian-stock-ai`.

---

## Task Breakdown

### 1. Pembuatan Struktur Folder Monorepo
Membuat struktur direktori yang memisahkan backend Python, API service, Web frontend, infrastruktur cloud, dan model registry:
- `apps/api/node/`: Service API backend Node.js (untuk V1/V2).
- `apps/web/nextjs/`: Frontend Next.js dashboard (untuk V2).
- `services/telegram/`: Layanan bot pengiriman notifikasi sinyal Telegram.
- `python/`: Pipeline inti ML dan sinyal (data, features, labels, models, signals, risk, outcomes, backtest, evaluation, retraining, config, common).
- `datasets/`: Penyimpanan data lokal (raw, processed, features).
- `models/`: Penyimpanan model ML (registry, champion, challengers).
- `tests/`: Pengujian otomatis (unit, integration, backtest).
- `infra/aws/`: Konfigurasi serverless & cloud deployment AWS.
- `docs/`: Dokumentasi arsitektur dan panduan pengembangan.
- `.agents/rules/`: Aturan lokal agent AI.

### 2. Integrasi Dokumen Panduan & Rule Lokal
- Menyalin dokumen panduan arsitektur lengkap `04_ai_agent_coding_development_guide_BEI_stock_signal.md` dari folder download ke `docs/`.
- Membuat aturan lokal `PROJECT_RULES.md` dan `.agents/rules/project_rules.md`:
  - **`summary.md`**: Bersifat **APPEND-ONLY** (dilarang menghapus/reset log sebelumnya).
  - **`walkthrough.md`**: Dapat di-overwrite setiap sesi kerja baru untuk melacak detail teknis sesi tersebut, wajib ada testing checklist di akhir.
  - **Antislop-code**: Standar kebersihan komentar kode (tanpa separator dekoratif, tanpa narasi alur step-by-step, tanpa restating obvious code, maks 1-2 baris kontekstual alasan WHY).
  - **Karpathy guidelines**: Simplicity first, surgical changes, think before coding, goal-driven execution.
  - **Cloud portability**: Nol hardcoded path komputer lokal, konfigurasi 12-factor via `.env`, siap migrasi ke laptop rumah / cloud.

### 3. Konfigurasi Environment & Tooling
- `.env.example`: Template variabel lingkungan (database URL, market data provider, Telegram token, S3 bucket, AWS region, model registry path).
- `.gitignore`: Menjaga repository bersih dari `.venv`, file data (`.parquet`, `.csv`), binary weight model (`.pkl`, `.joblib`), file cache Python/Node, dan credentials `.env`.
- `pyproject.toml`: Konfigurasi metadata proyek Python 3.12+, ruff linter, dan pytest options.
- `requirements.txt` & `requirements-dev.txt`: Daftar dependensi runtime dan development.
- `Makefile`: Perintah praktis untuk running test, linting, dan format.
- `README.md`: Ringkasan dokumentasi arsitektur, panduan instalasi lokal, dan panduan testing.

### 4. Setup Python Virtual Environment (.venv) & Baseline Implementation
- Membuat virtual environment `.venv` menggunakan interpreter `C:\Users\DROSE250122\AppData\Local\Programs\Python\Python312\python.exe`.
- Menginstal dependensi awal: `pytest`, `pydantic`, `python-dotenv`.
- Mengimplementasikan typed domain models (`python/common/types.py`) menggunakan Pydantic:
  - `Signal` (ticker, signal_date, action, entry_price, target_price, stop_loss, max_holding_days, probability, model_version, score).
  - `Position` (position_id, ticker, entry_date, entry_price, quantity, target_price, stop_loss, is_open, close_date, close_price).
  - `Prediction` (ticker, prediction_date, model_version, probability, expected_return).
  - `Outcome` (ticker, signal_date, status, realized_return, holding_days).
  - `ModelVersion` (version, model_type, trained_at, metrics, is_champion).
- Mengimplementasikan loader konfigurasi terpusat (`python/config/settings.py`) berbasis `pydantic.BaseModel` yang membaca environment variable tanpa hardcoded path absolut mesin.
- Membuat file `__init__.py` pada seluruh modul Python.

### 5. Unit Testing
- Membuat `tests/unit/test_smoke.py`: Memverifikasi kecocokan versi Python (>= 3.12) dan keberadaan path direktori proyek.
- Membuat `tests/unit/test_types.py`: Memverifikasi validasi data schema `Signal`, `Position`, dan default settings.
- Menjalankan `pytest` dengan hasil 5 passed.

### 6. Git Inisialisasi
- Menjalankan `git init` di root folder project `C:\Users\DROSE250122\Documents\Personal\indonesian-stock-ai`.
- Menambahkan file `.gitkeep` pada setiap folder kosong agar struktur direktori dapat dilacak oleh git.

---

## Daftar File yang Dibuat

1. `docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md` (3206 baris) — Salinan lengkap development guide.
2. `PROJECT_RULES.md` (72 baris) — Aturan lokal: summary.md APPEND-ONLY, walkthrough.md, antislop, karpathy, cloud portability.
3. `.agents/rules/project_rules.md` (72 baris) — Aturan lokal untuk AI agent framework.
4. `.env.example` (10 baris) — Template environment variables.
5. `.gitignore` (63 baris) — Aturan ignore git untuk virtual environment, data files, model binaries, dan cache.
6. `pyproject.toml` (39 baris) — Konfigurasi build, ruff, dan pytest.
7. `requirements.txt` (11 baris) — Dependensi runtime (pydantic, python-dotenv, pandas, scikit-learn, pyarrow).
8. `requirements-dev.txt` (5 baris) — Dependensi pengujian dan linting.
9. `Makefile` (18 baris) — Shortcut command untuk test, lint, format.
10. `README.md` (66 baris) — Dokumentasi overview proyek dan petunjuk quickstart.
11. `summary.md` (17 baris) — Log kumulatif append-only sesi pengerjaan.
12. `python/config/settings.py` (23 baris) — Pydantic settings loader.
13. `python/common/types.py` (57 baris) — Typed domain models (Signal, Position, Prediction, Outcome, ModelVersion).
14. `tests/unit/test_smoke.py` (13 baris) — Smoke test environment dan struktur folder.
15. `tests/unit/test_types.py` (37 baris) — Unit test domain models dan konfigurasi default.
16. `.gitkeep` di folder `apps/api/node`, `apps/web/nextjs`, `services/telegram`, `datasets/raw`, `datasets/processed`, `datasets/features`, `models/registry`, `models/champion`, `models/challengers`, `notebooks`, `infra/aws`, `migrations`.
17. `__init__.py` di 17 modul python dan folder tests.

---

## Testing Checklist

Berikut checklist yang perlu diverifikasi:
- [x] Folder proyek telah terbuat di `C:\Users\DROSE250122\Documents\Personal\indonesian-stock-ai`.
- [x] Struktur folder lengkap (apps/api, apps/web, services, python, datasets, models, tests, infra, docs).
- [x] Dokumen panduan `04_ai_agent_coding_development_guide_BEI_stock_signal.md` tersalin di `docs/`.
- [x] Virtual environment `.venv` aktif dan berjalan dengan Python 3.12.
- [x] `pytest` berhasil dijalankan dan semua unit tests lulus (5/5 passed).
- [x] File `.env.example`, `.gitignore`, `pyproject.toml`, dan `README.md` tersedia dan valid.
- [x] Aturan lokal `PROJECT_RULES.md` telah memuat mandat `summary.md` APPEND-ONLY dan `walkthrough.md`.
- [x] Git repository telah diinisialisasi (`git init`).
- [ ] Pengujian manual aktivasi virtual environment oleh pengguna: `.\.venv\Scripts\Activate.ps1`.
- [ ] Pengujian git commit pertama jika pengguna ingin melakukan commit awal.
