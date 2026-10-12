# Project Summary Log

Log Perubahan Tambahan (12 Oktober 2026)
1. Inisialisasi Repository dan Struktur Project BEI Stock Signal (Phase 0)
   Masalah:
   1. Proyek AI daily signal generator untuk saham BEI belum memiliki struktur direktori, baseline virtual environment, konvensi monorepo (backend dan FE), serta aturan dokumentasi.
   2. Panduan arsitektur masih berada di folder download terpisah dan belum terintegrasi ke dalam repository.
   Solusi:
   1. Membuat struktur folder lengkap sesuai development guide: apps/api/node, apps/web/nextjs, services/telegram, python (data, features, labels, models, signals, risk, outcomes, backtest, evaluation, retraining, config, common), tests (unit, integration, backtest), datasets, models, docs, infra/aws.
   2. Menyalin execution guide "04_ai_agent_coding_development_guide_BEI_stock_signal.md" ke folder docs/.
   3. Menginisialisasi virtual environment Python 3.12 (.venv) dan menginstal dependencies dasar (pytest, pydantic, python-dotenv).
   4. Membuat file konfigurasi standar: .env.example, .gitignore, pyproject.toml, requirements.txt, requirements-dev.txt, Makefile, dan README.md.
   5. Menetapkan aturan lokal (PROJECT_RULES.md dan .agents/rules/project_rules.md) terkait kewajiban pencatatan summary.md (APPEND-ONLY), walkthrough.md, kaidah antislop-code, karpathy-guidelines, dan portabilitas cloud.
   6. Menulis baseline typed domain models (Signal, Position, Prediction, Outcome, ModelVersion) dan memverifikasi unit test (5 tests passed).
2. Skeptical Review & Audit Perbaikan Setup Phase 0
   Masalah:
   1. Dokumen arsitektur utama `03_plan_ai_stock_signal_BEI_daily.md` di Downloads belum tersalin ke docs/ (hanya file panduan 04 yang disalin).
   2. Model domain `Prediction` dan `Outcome` menggunakan `datetime.utcnow()` yang berstatus deprecated di Python 3.12+ dan memicu DeprecationWarning.
   3. Domain models `Prediction`, `Outcome`, dan `ModelVersion` belum diuji dalam unit tests (`tests/unit/test_types.py`).
   4. Modul `python/config/settings.py` tidak memanggil `load_dotenv()`, sehingga konfigurasi dari file `.env` tidak termuat ke runtime.
   5. Linter `ruff` dan `pytest-cov` belum terinstal di `.venv`, dan `ruff check .` memicu 4 lint error (E501 line length dan I001 import ordering).
   Solusi:
   1. Menyalin `03_plan_ai_stock_signal_BEI_daily.md` ke `docs/` dan menambahkan verifikasi smoke test.
   2. Memperbaiki `python/common/types.py` menggunakan `datetime.now(timezone.utc)` yang timezone-aware dan aman untuk Python 3.12+.
   3. Menambahkan unit test komprehensif di `tests/unit/test_types.py` untuk `Prediction`, `Outcome`, dan `ModelVersion` (total 8 unit tests passed).
   4. Mengintegrasikan `load_dotenv()` di `python/config/settings.py` dan menormalisasi URI SQLite dengan `.as_posix()`.
   5. Menginstal `ruff` dan `pytest-cov` di `.venv`, menyelesaikan seluruh isu linting (`ruff check .` lulus tanpa error), dan mengoptimalkan target `clean` di `Makefile`.
