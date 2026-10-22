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
3. Implementasi Phase 1 — Data Layer & Market Data Provider Ingestion
   Masalah:
   1. Proyek belum memiliki data layer untuk mengonsumsi, memvalidasi, dan menyimpan bar harian saham BEI/IDX (BBCA, BBRI, BMRI, TLKM, ASII).
   2. Belum ada abstraksi provider (Protocol) sehingga sistem rentan terikat pada satu vendor market data.
   3. Belum ada aturan validasi otomatis untuk mencegah data anomali (harga open <= 0, high < close, low > open, volume negatif, duplikasi tanggal).
   4. Belum ada CLI ingestion dan validasi untuk operasional terjadwal lokal maupun cloud.
   Solusi:
   1. Menambahkan domain model `DailyBar` pada `python/common/types.py` dengan validasi tipe data Pydantic.
   2. Mendefinisikan interface `MarketDataProvider` (Protocol) serta implementasi `MockMarketDataProvider` (penghasil data sintetis deterministik) dan `CSVMarketDataProvider` pada `python/data/provider.py`.
   3. Membangun modul validasi komprehensif di `python/data/validation.py` untuk menegakkan aturan integritas data: open > 0, high >= max(open, close), low <= min(open, close), volume >= 0, deteksi duplikasi tanggal per ticker, dan null detection.
   4. Membangun `DailyBarRepository` di `python/data/repository.py` berbasis SQLite standar dengan skema tabel, indeks, serta mekanisme upsert (`ON CONFLICT DO UPDATE`) untuk mencegah duplikasi bar.
   5. Membuat CLI scripts `scripts/ingest_daily.py` dan `scripts/validate_data.py` yang siap dijalankan via command line (`python -m scripts.ingest_daily` dan `python -m scripts.validate_data`) atau `Makefile`.
   6. Menyiapkan dataset sampel CSV 5 saham utama BEI (BBCA, BBRI, BMRI, TLKM, ASII) di `datasets/raw/`.
   7. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_provider.py`, `tests/unit/test_validation.py`, `tests/unit/test_repository.py`, `tests/integration/test_data_pipeline.py`) dengan 100% lulus (36 tests passed, 91% code coverage).

4. Skeptical Review & Audit Perbaikan Phase 1 (Data Layer & Market Data Provider)
   Masalah:
   1. Nilai NaN dan Inf pada harga OHLCV lolos validasi tanpa error di `validate_bar` karena perbandingan IEEE-754 (`nan <= 0` bernilai `False` di Python).
   2. Validasi duplikasi tanggal (`validate_daily_bars`) tidak mendeteksi bentrok antara ticker polos (misal `BBCA`) dan ticker dengan suffix bursa (`BBCA.JK`).
   3. `DailyBarRepository.get_daily_bars`, `count_bars`, `get_latest_date`, dan `delete_bars` gagal menemukan data jika dipanggil dengan `BBCA.JK` karena query menambahkan suffix menjadi `BBCA.JK.JK`.
   4. `MockMarketDataProvider.get_daily_bars` mengembalikan 0 bar jika dipanggil dengan ticker huruf kecil (`bbca` atau `bbca.jk`).
   5. `CSVMarketDataProvider` gagal membaca file CSV yang memiliki UTF-8 BOM (`\ufeff`) dan gagal mem-parsing angka yang diformat dengan tanda koma ribuan.
   Solusi:
   1. Menambahkan pemeriksaan `_is_finite_number` dengan `math.isnan` dan `math.isinf` pada `validate_bar` serta memeriksa `high >= low`.
   2. Menormalisasi ticker secara kanonikal (`.strip().upper().removesuffix(".JK")`) pada `validate_daily_bars` sehingga duplikasi antar format tertangkap.
   3. Memperbaiki query parameter pada `DailyBarRepository` agar menormalisasi ticker kanonikal sebelum pencocokan `OR ticker = ?`, serta mengaktifkan SQLite WAL mode dan busy timeout 30 detik.
   4. Menormalisasi input ticker pada `MockMarketDataProvider` sehingga query huruf kecil dan suffix `.JK` menghasilkan data yang benar.
   5. Menambahkan `encoding="utf-8-sig"` pada `CSVMarketDataProvider` dan helper `_safe_float` untuk menangani BOM dan pemisah ribuan koma.
   6. Menjadikan `DailyBarRepository` memenuhi interface `MarketDataProvider` (Protocol) dengan menambahkan `get_sector_data()`.
   7. Menambahkan 7 unit & integrasi test baru (total 43 tests passed, zero warnings, ruff 100% clean).

5. Implementasi Phase 2 — Feature Engine & Data Leakage Prevention
   Masalah:
   1. Proyek belum memiliki mesin komputasi feature untuk menghitung indikator teknikal (momentum, trend EMA, RSI, volatilitas ATR/realized vol, dan volume/value ratios).
   2. Belum ada feature relative strength (saham vs IHSG dan saham vs sektor) serta indikator market regime numerik (ihsg return, ihsg vs EMA, market breadth, market volatility).
   3. Belum ada mekanisme pencegahan dan pengujian eksplisit data leakage (future lookahead bias) untuk memastikan komputasi masa lalu invariant terhadap data masa depan.
   4. Belum ada storage tabel `features_daily` bertipe data typed container dengan versioning (`feature_version`) serta CLI builder script.
   Solusi:
   1. Menambahkan domain model `FeatureRecord` pada `python/common/types.py` dengan skema fitur lengkap dan versi fitur (`feature_version`).
   2. Membangun modul fungsi matematika murni di `python/features/indicators.py` (returns, EMA multi-span, Wilder's RSI, ATR, realized volatility sample stdev, volume/value moving average ratios, daily range pct).
   3. Mengimplementasikan `FeatureEngine` pada `python/features/engine.py` untuk mengolah fitur per-saham, market benchmark proxy/IHSG, market breadth lintas universe, dan relative strength per-sektor secara strictly causal.
   4. Membangun `FeatureRepository` pada `python/features/repository.py` berbasis SQLite table `features_daily` dengan skema lengkap, indeks `(ticker, date)` dan `feature_version`, serta mekanisme upsert idempotent.
   5. Membuat CLI script `scripts/build_features.py` untuk menghitung fitur harian dari SQLite/Mock/CSV, persistensi ke database, dan visualisasi format tabel/JSON/CSV.
   6. Menambahkan target `features` pada `Makefile`.
   7. Menulis pengujian unit matematis dan integrasi (`tests/unit/test_features.py`, `tests/unit/test_leakage.py`, `tests/integration/test_feature_pipeline.py`) dengan 100% lulus (66 tests passed, ruff clean, zero data leakage).

6. Skeptical Review & Audit Perbaikan Phase 2 (Feature Engine & Data Leakage Prevention)
   Masalah:
   1. `scripts/build_features.py` memfilter universe sebelum pemanggilan `FeatureEngine` saat argumen `--ticker` diberikan, memusnahkan konteks pasar sehingga `rel_strength_ihsg_20d` dan `rel_strength_sector_20d` bernilai 0.0 konstan dan mendistorsi `market_breadth` jika disimpan ke database via `--save-db`.
   2. Harga awal benchmark `last_p` pada `FeatureEngine` di-hardcode ke `1000.0`, memicu lonjakan buatan +650% pada return dan volatilitas jika data bar `IHSG` baru tersedia beberapa hari setelah saham pertama.
   3. Ticker benchmark indeks (`IHSG`, `^JKSE`, `COMPOSITE`) ikut terhitung sebagai saham dalam rumus `market_breadth` dan proxy komposit equal-weighted.
   4. Perhitungan `market_breadth` menggunakan pemindaian list linear `next(...)` dalam loop tanggal-ticker ($O(N^2 M)$), memicu kelemahan latensi pada universe besar.
   5. Domain model `FeatureRecord` belum memiliki validasi/normalisasi ticker (whitespace dan suffix `.JK`), serta `FeatureRepository` belum memiliki method `get_universe()` dan `get_latest_date()`.
   6. Indikator `compute_returns`, `compute_relative_distance`, dan `compute_daily_range_pct` belum memvalidasi `math.isfinite`, berisiko memproduksi `NaN`/`Inf` jika data input terkontaminasi.
   7. Makefile target `features` belum tercantum pada `.PHONY`.
   Solusi:
   1. Memperbaiki `scripts/build_features.py` agar selalu memuat seluruh semesta saham yang tersedia untuk komputasi konteks pasar, lalu memfilter record hasil sesuai filter `--ticker` yang diminta.
   2. Menginisialisasi `last_p` benchmark ke harga bar pertama yang valid (`clean_universe[benchmark_key][0].close`), mengeliminasi lonjakan harga artifisial.
   3. Memfilter semesta saham dengan mengecualikan `BENCHMARK_TICKERS` dari denominator dan numerator `market_breadth`.
   4. Mengimplementasikan dictionary lookup $O(1)$ (`stock_close_map`) sehingga kompleksitas market breadth teroptimasi menjadi $O(NM)$.
   5. Menambahkan `@field_validator("ticker")` pada `FeatureRecord` dan menambahkan `get_universe()` serta `get_latest_date()` pada `FeatureRepository`.
   6. Menambahkan penjaga `math.isfinite` pada fungsi-fungsi indikator di `python/features/indicators.py`.
   7. Menambahkan `features` ke baris `.PHONY` di `Makefile`.
   8. Menambahkan 6 pengujian baru pada `test_types.py`, `test_smoke.py`, `test_features.py`, dan `test_leakage.py` (total 72 tests passed, 86% coverage, zero warnings, ruff clean).

7. Implementasi Phase 3 — Label Engine (Triple Barrier Labeling & Ambiguity Handling)
   Masalah:
   1. Proyek belum memiliki engine pelabelan berbasis triple barrier (upper barrier TP, lower barrier SL, dan vertical barrier max holding days) untuk menghasilkan supervised learning target bagi data harian BEI.
   2. Pada data harian OHLC, terdapat ambiguitas saat candle menyentuh TP dan SL di hari yang sama (`high >= tp_price` dan `low <= sl_price`) tanpa urutan intraday yang pasti, belum memiliki penanganan kebijakan configurable (conservative, optimistic, ambiguous) serta deteksi lonjakan harga gap up / gap down saat market open.
   3. Belum ada kalkulasi metrik jalur (path metrics) seperti MFE (Maximum Favorable Excursion), MAE (Maximum Adverse Excursion), holding days, dan realized return per-posisi.
   4. Belum ada domain model `LabelRecord`, SQLite storage `labels_daily` dengan indexing `(ticker, date)` dan upsert idempotent, serta CLI generator `scripts/build_labels.py` dan target `Makefile`.
   Solusi:
   1. Menambahkan domain model `LabelRecord`, enum `LabelOutcome` (TP, SL, EXPIRY, AMBIGUOUS), dan `AmbiguityPolicy` pada `python/common/types.py` dengan validasi dan normalisasi kanonikal ticker.
   2. Membangun `LabelEngine` pada `python/labels/engine.py` yang mengimplementasikan triple barrier labeling deterministik, deteksi gap up / gap down pada opening candle, resolusi ambiguitas intraday terkonfigurasi (conservative = SL first default, optimistic = TP first, ambiguous = mark AMBIGUOUS), serta kalkulasi MFE, MAE, holding days, dan realized return.
   3. Membangun `LabelRepository` pada `python/labels/repository.py` berbasis SQLite table `labels_daily` dengan indeks `(ticker, date)` dan `label_version`, serta upsert idempotent (`ON CONFLICT DO UPDATE`).
   4. Membuat CLI script `scripts/build_labels.py` dengan argumen lengkap (`--tp-pct`, `--sl-pct`, `--max-hold`, `--ambiguity-policy`, `--save-db`, `--format table/json/csv`, `--limit`) dan menambahkan target `labels` ke `Makefile`.
   5. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_labels.py`, `tests/integration/test_label_pipeline.py`, dan penambahan di `test_types.py`) yang mencakup semua skenario kritis Section 50 dan Section 25 dengan 100% lulus (92 tests passed, 91% code coverage, ruff clean).

8. Skeptical Review & Audit Perbaikan Phase 3 (Label Engine & Ambiguity Handling)
   Masalah:
   1. `LabelEngine.compute_labels` tidak memisahkan data bar berdasarkan ticker ketika list bar campuran diberikan, menyebabkan bar saham lain (misal BBRI harga 5000) masuk ke forward bars saham entry (misal BBCA harga 10000) dan memicu false stop-loss akibat kontaminasi lintas-ticker.
   2. Pada `scripts/build_labels.py`, pengecekan database kosong (`if not target_universe:`) membaca variabel `target_universe = tickers or bar_repo.get_universe()`, sehingga jika user menentukan argumen `--ticker BBCA.JK` pada database SQLite yang kosong, sistem tidak beralih ke mock provider dan menghasilkan 0 bar/0 label. Selain itu, ticker dari mock universe belum dinormalisasi ke format kanonikal.
   3. Pengecekan rentang tanggal `--end-date` pada `scripts/build_labels.py` memangkas query bar pasar tepat pada `end_date`, sehingga bar-bar entry menjelang akhir tanggal kehilangan jendela evaluasi masa depan (`forward_bars < max_holding_days`) dan terbuang (starvation) yang melenyapkan data label valid hingga 10 hari bursa.
   4. Bar forward yang memiliki nilai tidak valid (NaN/Inf atau high < low) tidak disaring pada `LabelEngine.compute_label_for_bar`, berisiko meracuni metrik `mfe` dan `mae` menjadi NaN pada dataset. Selain itu, domain model `LabelRecord` belum memiliki validasi Pydantic lengkap untuk nilai harga positif, persentase positif, binary target [0, 1], outcome valid, policy valid, dan metrik berhingga.
   5. `LabelRepository.count_labels` belum memiliki parameter filter `ticker`, dan `LabelRepository.get_all_labels` belum memiliki filter list `tickers` (tidak konsisten dengan `FeatureRepository`).
   6. `tests/unit/test_smoke.py` belum menyertakan pengujian keberadaan file implementasi Phase 3 (`python/labels/engine.py`, `python/labels/repository.py`, dan `scripts/build_labels.py`).
   Solusi:
   1. Mengelompokkan bar berdasarkan ticker kanonikal (`by_ticker`) di `LabelEngine.compute_labels`, menyaring ticker yang identik pada `valid_forward`, serta mendeduplikasi bar dengan tanggal yang sama.
   2. Memperbaiki pengecekan database kosong pada `scripts/build_labels.py` dengan memeriksa `db_universe = bar_repo.get_universe()`, menormalisasi seluruh key ticker mock provider, dan memastikan fallback berjalan mulus.
   3. Mengizinkan pemuatan jendela forward bar melampaui `end_date`, lalu memfilter hasil `LabelRecord` berdasarkan `start_date` dan `end_date` tanpa memangkas masa depan evaluasi holding.
   4. Menambahkan filter penjaga `math.isfinite` dan `high >= low` pada forward bars di `compute_label_for_bar`, serta menambahkan validasi `@field_validator` ketat pada `LabelRecord` di `python/common/types.py`.
   5. Menambahkan dukungan filter `ticker` pada `LabelRepository.count_labels` dan `tickers` pada `LabelRepository.get_all_labels`.
   6. Menambahkan verifikasi file Phase 3 pada `tests/unit/test_smoke.py`.
   7. Menambahkan 8 unit test baru mencakup isolasi lintas-ticker, deduplikasi bar, filtering corrupt bar, corporate action split 1:5, perbaikan CLI, dan CRUD repository (total 100 tests passed, 91% code coverage, ruff clean).
9. Implementasi Phase 4 — Baseline Models & Time-Series Validation
   Masalah:
   1. Proyek belum memiliki mekanisme validasi time-series strictly chronological tanpa random train/test split, serta rolling walk-forward generator dengan jendela purge window untuk mengeliminasi target overlap pada multi-day holding period.
   2. Belum ada DatasetBuilder untuk menggabungkan `features_daily` dan `labels_daily` berbasis `(ticker, date)`, mengekstrak matriks numerik X dan target y / continuous return, serta menangani missing feature values secara aman tanpa data leakage.
   3. Belum ada model ML baseline (Logistic Regression dan LightGBM untuk klasifikasi event probability P(TP before SL), LightGBM dan Ridge untuk regresi expected return), kalkulasi metrik evaluasi komprehensif (Brier score, Log loss, ROC-AUC, accuracy, MSE, MAE, dan ECE calibration curve), serta Model Registry dengan persistensi artifact joblib dan metadata JSON berstandar Section 54 (champion/challenger lifecycle).
   4. Belum ada training CLI `scripts/train_model.py` dan target `train` pada Makefile.
   Solusi:
   1. Membangun modul time-series validation di `python/models/validation.py` dengan fungsi `split_chronological`, `split_by_dates`, dan kelas `WalkForwardSplitter` yang menjamin train < val < test serta isolasi purge window.
   2. Mengimplementasikan `Dataset` container dan `DatasetBuilder` pada `python/models/dataset.py` dengan penyelarasan ticker kanonikal, sorting kronologis, deduplikasi, dan strategi imputasi nilai hilang yang aman tanpa leakage.
   3. Mengimplementasikan model baseline pada `python/models/baseline.py` (`LogisticRegressionBaseline`, `LightGBMClassifierBaseline`, `LightGBMRegressorBaseline`, `RidgeRegressionBaseline`) dengan penjaga fallback untuk dataset dengan satu kelas / sampel kecil, serta modul evaluasi pada `python/models/metrics.py` (Brier score, log loss, ROC-AUC dengan fallback, ECE, calibration curve, MSE, RMSE, MAE, R2).
   4. Mengimplementasikan `ModelRegistry` dan `ModelMetadata` pada `python/models/registry.py` yang mendukung penyimpanan joblib, registrasi metadata JSON Section 54, pencarian champion model, serta promosi/demosi champion-challenger otomatis.
   5. Membuat CLI script `scripts/train_model.py` dan target `train` di Makefile.
   6. Menginstal dependencies `scikit-learn`, `lightgbm`, dan `joblib` pada `.venv` dan memperbarui `requirements.txt` serta `pyproject.toml`.
   7. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_models.py`, `tests/integration/test_model_pipeline.py`, dan pembaruan `test_smoke.py`) dengan 100% lulus (120 tests passed, 89% code coverage, ruff clean).

10. Skeptical Review & Audit Perbaikan Phase 4 (Baseline Models & Time-Series Validation)
   Masalah:
   1. `WalkForwardSplitter` salah menghitung index awal training `train_start_idx = max(0, raw_train_end_idx - window_size)` dari `raw_train_end_idx` (`test_start_idx`) bukan dari `purged_train_end_idx`. Jika `window_size <= purge_days` (misal `train_days=10, purge_days=10`), maka `train_start_idx == purged_train_end_idx` sehingga fold training kosong dan memicu crash `ValueError: Purge window ... eliminated all training dates`, serta jika `window_size > purge_days`, durasi train berkurang sebanyak `purge_days` dari yang diminta user.
   2. Pada `scripts/train_model.py`, fallback mock data generator `MockMarketDataProvider(days=80)` mengabaikan ticker yang diminta user (`--ticker`) dan hanya menggunakan 5 default ticker (`DEFAULT_UNIVERSE`). Jika database kosong dan user menentukan `--ticker INCO`, sistem menghasilkan 0 bar dan gagal melatih model. Selain itu ticker belum dinormalisasi formatnya.
   3. Pemanggilan `predict`, `predict_proba`, atau `predict_probability` pada `LogisticRegressionBaseline` dan `LightGBMClassifierBaseline` sebelum `fit()` bocor sebagai exception internal `AttributeError: 'NoneType' object has no attribute 'predict_proba'` bukannya `sklearn.exceptions.NotFittedError` yang standar.
   4. `SimpleImputer` pada `LogisticRegressionBaseline` dan `RidgeRegressionBaseline` memunculkan `UserWarning: Skipping features without any observed values` ketika berhadapan dengan bar historis pendek di mana fitur indikator periode panjang (seperti `ema200`) bernilai NaN di seluruh fold training.
   5. `ModelMetadata.status` menerima string sembarang tanpa validasi terhadap standar Section 54 (`champion` / `challenger`), dan method `promote_to_champion` melakukan `joblib.load` (unpickle seluruh binary model) yang boros memori padahal hanya perlu memperbarui metadata JSON.
   6. Pada `compute_expected_calibration_error` dan `compute_calibration_curve`, probabilitas prediksi yang sedikit melebihi batas akibat presisi floating point tidak masuk ke bin manapun sehingga mendistorsi pembobotan ECE.
   7. `split_chronological` belum memvalidasi nilai negatif untuk `val_ratio` dan `test_ratio`.
   Solusi:
   1. Memperbaiki perhitungan `train_start_idx = max(0, purged_train_end_idx - window_size)` dan `min_required` pada `WalkForwardSplitter` sehingga ukuran training window akurat dan tidak crash ketika `train_days <= purge_days`.
   2. Menormalisasi ticker kanonikal pada `scripts/train_model.py` dan meneruskan `universe=target_tickers` ke `MockMarketDataProvider` sehingga fallback berjalan mulus untuk sembarang ticker yang diminta.
   3. Menambahkan pengecekan eksplisit `self.fitted_model_ is None` pada classifier baseline yang menaikkan `sklearn.exceptions.NotFittedError`.
   4. Mengonfigurasi `SimpleImputer(strategy="median", keep_empty_features=True, fill_value=0.0)` pada pipeline `LogisticRegressionBaseline` dan `RidgeRegressionBaseline`.
   5. Menambahkan `@field_validator("status")` pada `ModelMetadata` dan mengoptimalkan `promote_to_champion` menggunakan `get_metadata`.
   6. Melakukan `np.clip(yp, 0.0, 1.0)` pada fungsi kalkulasi kalibrasi.
   7. Menambahkan validasi `val_ratio < 0` dan `test_ratio < 0` pada `split_chronological`.
   8. Menambahkan 7 pengujian unit dan integrasi baru (total 127 tests passed, 90% code coverage, ruff clean).

11. Implementasi Phase 5 — Backtesting Engine, Friction Model & Financial Metrics
   Masalah:
   1. Proyek belum memiliki mesin simulasi perdagangan diskrit (discrete-event trade simulator) untuk merekonstruksi eksekusi sinyal model secara strictly causal tanpa data leakage / future lookahead bias (order dihasilkan EOD Day t dieksekusi di Open Day t+1).
   2. Belum ada model biaya dan friksi bursa Indonesia (IDX), seperti komisi broker beli (default 0.15%), komisi broker jual + pajak penjualan BEI (default 0.25%), estimasi slippage (5-15 bps), dan pembatasan kelipatan lot BEI (1 lot = 100 lembar).
   3. Belum ada kontrol risiko portofolio (max concurrent positions, e.g. 5, risk-based / fixed-fractional sizing, cash balance tracking) dan kalkulasi equity curve harian (mark-to-market).
   4. Belum ada metrik evaluasi finansial dan performa perdagangan standar industri (Win Rate, Profit Factor, Expectancy per trade, Maximum Drawdown nominal & persentase, CAGR, Average Holding Days, TP/SL/Expiry exit breakdown).
   5. Belum ada CLI runner `scripts/run_backtest.py` dan target `backtest` di Makefile.
   Solusi:
   1. Menambahkan domain models `BacktestConfig`, `TradeRecord`, `EquityPoint`, `BacktestReport`, dan `PositionSizingMethod` pada `python/common/types.py` dengan validasi parameter ketat.
   2. Membangun modul metrik murni di `python/backtest/metrics.py` (`calculate_win_rate`, `calculate_profit_factor`, `calculate_expectancy`, `calculate_max_drawdown`, `calculate_holding_period`, `calculate_barrier_rates`, `calculate_cagr`, `compute_backtest_report`) yang tahan pembagian nol dan class imbalance.
   3. Membangun `BacktestEngine` pada `python/backtest/engine.py` yang mereplikasi siklus perdagangan harian secara strictly causal: eksekusi pending order di open Day t+1, monitoring batas TP/SL/Expiry intraday sesuai policy ambiguitas, mark-to-market equity curve di close Day t+1, dan kalkulasi sinyal kandidat di EOD Day t+1 untuk eksekusi berikutnya.
   4. Memperbaiki kompatibilitas backward unpickling pada model baseline (`LogisticRegressionBaseline` dan `LightGBMClassifierBaseline`) agar aman memuat artifact registry lama via `getattr(self, "fitted_model_", None) or getattr(self, "model", None)`.
   5. Membuat CLI runner `scripts/run_backtest.py` dengan dukungan model champion registry, model kustom joblib, filter tanggal & ticker, format presentasi ASCII table atau JSON murni (dengan log ke stderr), serta ekspor trades ke format CSV/JSON.
   6. Menambahkan target `backtest` ke `Makefile`.
   7. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_backtest.py`, `tests/integration/test_backtest_pipeline.py`, pembaruan `tests/unit/test_smoke.py` dan `tests/unit/test_types.py`) dengan 100% kelulusan (141 tests passed, 90% total repository coverage, ruff clean).

12. Skeptical Review & Audit Perbaikan Phase 5 (Backtesting Engine, Friction Model & Financial Metrics)
   Masalah:
   1. `calculate_max_drawdown` menginisialisasi `peak` dari `equity_curve[0].total_equity` tanpa memperhitungkan `initial_capital`, sehingga jika portofolio mengalami kerugian sejak hari pertama di bawah modal awal, drawdown dari modal awal tidak terdeteksi (melaporkan 0.0% drawdown pada penurunan hari pertama).
   2. Pada `BacktestEngine`, posisi saham yang disuspensi (volume 0 atau tidak ada di `day_bars`) pada penutupan EOD mengalami mark-to-market shock karena nilainya dipaksa kembali ke `pos.entry_price`, bukan mempertahankan harga penutupan terakhir (`last_close`), serta pending order dapat terisi secara tidak realistis pada hari saham disuspensi (volume 0).
   3. Metode sizing `fixed_fractional` dan `equal_weight` diimplementasikan secara identik (keduanya membagi dengan `max_concurrent_positions`), mengabaikan alokasi fraksi tetap per trade (`max_position_pct`).
   4. CLI runner `scripts/run_backtest.py` mencetak log dan peringatan ke `sys.stdout` menggunakan `print()`, merusak output JSON murni ketika `--format json` dijalankan tanpa model pra-terlatih, serta belum mendukung format ticker yang dipisahkan koma (`--tickers BBCA,BBRI`).
   5. Domain models `BacktestConfig`, `TradeRecord`, dan `EquityPoint` belum memiliki validasi batas parameter ketat untuk `entry_execution`, `holding_days`, `signal_probability`, `open_positions_count`, dan `drawdown_pct`.
   6. Belum ada pengujian simulasi eksplisit untuk vertical barrier expiry pada batas `max_holding_days` (Section 50 acceptance test).
   Solusi:
   1. Memperbarui `calculate_max_drawdown` dengan parameter opsional `initial_capital`, menginisialisasi `peak = max(initial_capital, equity_curve[0].total_equity)`, dan meneruskannya dari `compute_backtest_report`.
   2. Melacak `last_close` pada `_ActivePosition` untuk mencegah penurunan semu nilai ekuitas saat saham disuspensi, menambahkan penjaga `volume <= 0` pada eksekusi order open dan barrier hit, serta menginkrementasi `holding_days` secara akurat pada hari bursa.
   3. Mengimplementasikan sizing `fixed_fractional` murni berbasis `current_equity * max_position_pct` dan `equal_weight` berbasis `current_equity / max_concurrent_positions`.
   4. Mengalihkan seluruh pesan log status, peringatan, dan error di `scripts/run_backtest.py` ke `sys.stderr.write(...)`, menambahkan penanganan `sys.exit(1)` yang aman, serta mendukung pemisahan ticker dengan koma maupun spasi.
   5. Menambahkan `@field_validator` ketat pada `python/common/types.py` untuk `BacktestConfig.entry_execution` (`next_open` / `next_close`), `TradeRecord.holding_days` (non-negatif), `TradeRecord.signal_probability` ([0.0, 1.0]), `EquityPoint.open_positions_count` (non-negatif), dan `EquityPoint.drawdown_pct` ([0.0, 1.0]).
   6. Menambahkan 8 unit dan integration tests baru di `test_backtest.py`, `test_types.py`, dan `test_backtest_pipeline.py` (total 149 tests passed, 90% code coverage, ruff 100% clean).

Log Perubahan Tambahan (12 Oktober 2026)
13. Implementasi Dataset Ingestion Layer, Seed Universe, YFinance Adapter & Integrasi Backtesting (Guide 05 DATA-001)
   Masalah:
   1. Repository belum memiliki adapter market data `yfinance` yang tangguh dengan penanganan corporate actions (dividen, stock split, adjusted close) dan pemisahan harga raw vs adjusted.
   2. Belum ada seed universe terstandarisasi untuk ~200 saham likuid BEI/IDX lintas sektor dengan skema pelacakan status aktif dan sumber seleksi (`configs/universe/seed_universe.csv`).
   3. Model domain `DailyBar` belum memfasilitasi kolom corporate actions (`adj_close`, `dividends`, `stock_splits`, `provider`, `provider_symbol`, `ingestion_run_id`, `interval`) serta alias canonical accessor (`open_raw`, `close_raw`, `trading_date`, `adj_close_provider`).
   4. Database repository `DailyBarRepository` masih menggunakan primary key sempit `(ticker, date)` tanpa kolom provider/interval, serta belum memiliki tabel audit ingestion (`ingestion_runs`, `ingestion_ticker_status`) dan pelacakan detail row counts (inserted/updated/unchanged).
   5. CLI runner `scripts/ingest_daily.py` belum mendukung mode terstruktur (`backfill`, `incremental`, `repair`) dengan jendela overlap 10 hari atau repair 30 hari, serta belum mencatat log audit run dan ticker status ke database.
   6. Validasi data (`python/data/validation.py`) belum memverifikasi batas kepatuhan field corporate actions (`adj_close > 0`, `dividends >= 0`, `stock_splits >= 0`).
   Solusi:
   1. Mengadopsi panduan `docs/05_dataset_and_market_data_agent_guide.md`, menginstal `yfinance>=0.2.38`, dan mengimplementasikan `YFinanceMarketDataProvider` lengkap dengan batching (default 25), bounded exponential retries, multithreaded concurrency, serta fungsi normalisasi `normalize_yfinance_dataframe` yang mendukung format single-ticker dan multi-ticker DataFrame.
   2. Membuat `configs/universe/seed_universe.csv` berisi 210 saham likuid BEI terverifikasi lintas 11 sektor IDX, disertai helper `load_universe` dan `load_sector_map` yang memiliki mekanisme graceful fallback.
   3. Memperbarui `DailyBar` pada `python/common/types.py` dengan backward compatibility penuh, validasi alias sebelum instansiasi, dan menambahkan audit domain models `IngestionRun` serta `IngestionTickerStatus`.
   4. Mengupgrade skema SQLite `DailyBarRepository` secara aman melalui auto-migration preserved data, memperluas primary key menjadi `(ticker, date, interval, provider)`, menambahkan method `save_bars_detailed`, serta menambahkan CRUD lengkap untuk audit tables `ingestion_runs` dan `ingestion_ticker_status`.
   5. Mengupgrade CLI runner `scripts/ingest_daily.py` dengan opsi `--mode [backfill|incremental|repair]`, parameter tanggal & batching, pencatatan otomatis audit log pada level run dan ticker, serta penanganan aman untuk ticker yang belum pernah di-ingest.
   6. Memperketat `validate_bar` di `python/data/validation.py` untuk memastikan kepatuhan corporate actions (`adj_close`, `dividends`, `stock_splits`).
   7. Menambahkan 16 unit dan integration tests baru di `test_provider.py`, `test_repository.py`, `test_validation.py`, `test_types.py`, dan `test_ingestion_and_backtest.py`, membuktikan integrasi end-to-end fitur, label, model baseline, dan backtest berjalan mulus tanpa regresi (total 165 tests passed, 100% ruff clean).

14. Skeptical Review & Audit Perbaikan Dataset Ingestion Layer (Guide 05 DATA-001)
   Masalah:
   1. `DailyBarRepository.save_bars_detailed` mengabaikan perubahan dividen, stock split, dan nilai transaksi pada pemeriksaan `is_same` (hanya memeriksa OHLCV dan adj_close), sehingga pembaruan corporate action pada bar yang sudah ada terdeteksi sebagai `unchanged` dan gagal ter-update di database.
   2. Field `row_hash` yang diwajibkan pada Guide 05 Section 7, 10, 11, dan 14 belum diimplementasikan pada `DailyBar` dan skema SQLite `daily_bars`, sehingga sistem belum memiliki hash kanonikal untuk deteksi mutasi bar secara instan.
   3. Pada `scripts/ingest_daily.py`, parameter `stat_counters` diinstansiasi ulang sebagai dictionary lokal baru pada setiap iterasi loop ticker (`stat_counters={"inserted": total_inserted, ...}`), melenyapkan akumulasi metrik baris `unchanged` dan `rejected`, sehingga audit log `ingestion_runs` dan output CLI selalu melaporkan `0 unchanged` dan `0 rejected`.
   4. Penentuan `final_status` pada `scripts/ingest_daily.py` salah menetapkan `SUCCESS` saat 0 ticker berhasil (`succeeded_cnt == 0`) selama `failed_cnt == 0` (seperti saat seluruh ticker menghasilkan `NO_DATA`), dan CLI selalu mengembalikan exit code 0 saat terjadi kegagalan total (`FAILED`).
   5. `normalize_yfinance_dataframe` memeriksa keberadaan ticker pada `df.columns.levels[0]` / `df.columns.levels[1]` yang menyimpan cache level lama saat MultiIndex dipotong (sliced), memicu unhandled `KeyError` jika ticker tidak terdapat pada kolom aktual DataFrame. Selain itu, ekstraksi tuple column dan zona waktu bursa (`Asia/Jakarta`) belum ditangani secara tangguh.
   6. Mode `incremental` pada adapter YFinance di `scripts/ingest_daily.py` meng-hardcode rentang tanggal ke `today - 10 days` tanpa memeriksa `latest_in_db` per ticker, menimbulkan kekosongan data (data gap) jika proses ingest terlewat beberapa hari.
   7. File `docs/05_dataset_and_market_data_agent_guide.md` dan `configs/universe/seed_universe.csv` belum diverifikasi pada smoke test `tests/unit/test_smoke.py`.
   Solusi:
   1. Memperbaiki logika deteksi perubahan pada `DailyBarRepository.save_bars_detailed` menggunakan `row_hash` dan fungsi pembanding `_is_close` yang mencakup seluruh field (`open`, `high`, `low`, `close`, `volume`, `value`, `adj_close`, `dividends`, `stock_splits`), sehingga perubahan dividen dan stock split memicu update dan tercatat pada counter `updated`.
   2. Menambahkan field `row_hash: Optional[str] = None` dan method `compute_row_hash()` pada `DailyBar`, menambahkan kolom `row_hash TEXT` pada tabel SQLite `daily_bars` dengan migrasi otomatis, serta memvalidasi kesamaan hash pada unit tests.
   3. Menggunakan dictionary referensi tunggal `stat_counters` lintas loop chunk/ticker di `scripts/ingest_daily.py`, sehingga jumlah baris `unchanged` dan `rejected` terakumulasi akurat ke tabel audit `ingestion_runs` dan log CLI.
   4. Memperbaiki penentuan status run: `SUCCESS` jika semua ticker berhasil tanpa error/no-data, `FAILED` jika `succeeded_cnt == 0`, dan `PARTIAL` untuk kondisi parsial. Menaikkan error saat `FAILED` sehingga CLI mengembalikan exit code 1.
   5. Memeriksa kolom aktual via `df.columns.get_level_values(...)` dengan proteksi `try...except KeyError`, mendukung tuple column unpacking, dan menormalisasi timezone timestamp ke `Asia/Jakarta` exchange calendar.
   6. Memperhitungkan `latest_in_db` per ticker pada mode incremental untuk menentukan tanggal awal fetch (`latest - 10 days`), mencegah gap historis.
   7. Menambahkan assertion `05_dataset_and_market_data_agent_guide.md` dan `seed_universe.csv` pada `test_smoke.py`.
   8. Menambahkan 6 unit dan integration tests baru di `test_types.py`, `test_provider.py`, `test_repository.py`, dan `test_ingestion_and_backtest.py` (total 171 tests passed, 83% coverage, ruff 100% clean).

15. Implementasi Phase 6 — Signal Engine & Daily Ranking Generator
   Masalah:
   1. Proyek belum memiliki mesin pembuat sinyal harian (Signal Engine) yang mengintegrasikan ekstraksi fitur kausal tanpa data leakage, inferensi probabilitas champion classifier dan regressor expected return, penyaringan risiko/likuiditas, dan pembobotan skor komposit terkonfigurasi.
   2. Belum ada model domain `SignalRecord` (mencakup signal_id, ticker, signal_date, entry band low-high, TP/SL price, holding days, predicted_probability, expected_return, composite score, versioning, dan feature snapshot) serta `SignalConfig` pada `python/common/types.py`.
   3. Belum ada layer persistensi `SignalRepository` berbasis SQLite tabel `signals_daily` dengan indexing `(signal_date, score DESC)` dan garansi mutlak IMMUTABILITY (tidak boleh ada penulisan ulang/mutasi terhadap sinyal historis).
   4. Belum ada CLI generator sinyal `scripts/generate_signals.py` dengan opsi `--date`, `--top-n`, `--model-version` / `--use-champion`, `--save-db`, `--min-prob`, format presentasi `table`/`json`/`csv`, serta target `signals` pada `Makefile`.
   Solusi:
   1. Menambahkan domain models `SignalRecord` dan `SignalConfig` pada `python/common/types.py` dengan validasi ketat batas harga, probabilitas, skor komposit [0, 100], batas barrier (entry_low <= entry_high, tp_price >= entry_high, sl_price <= entry_low), dan normalisasi kanonikal ticker.
   2. Membangun `SignalEngine` pada `python/signals/engine.py` dengan pipeline terstruktur: pengecekan kelengkapan data & tanggal bursa aktif, ekstraksi fitur strictly kausal sampai tanggal t (tanpa future bars), resolusi model champion dari `ModelRegistry`, inferensi probabilitas & return terekspektasi, filter probabilitas dan likuiditas 20 hari, kalkulasi skor komposit berbobot (probabilitas, return, likuiditas, regime pasar, risiko), pemeringkatan kandidat Top-N, kalkulasi entry band serta TP/SL, dan pencatatan feature snapshot lengkap per sinyal.
   3. Membangun `SignalRepository` pada `python/signals/repository.py` berbasis SQLite tabel `signals_daily` dengan indexing efisien dan penegakan prinsip immutability (menolak penulisan duplikasi via `UNIQUE constraint` dan exception `sqlite3.IntegrityError`, tanpa method update).
   4. Membuat CLI generator `scripts/generate_signals.py` dengan format tabel ASCII, JSON murni, dan CSV, disertai opsi `--save-db` dan `--ignore-existing`, serta menambahkan target `signals` pada `Makefile`.
   5. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_signals.py`, `tests/integration/test_signal_pipeline.py`, pembaruan `test_smoke.py` dan `test_types.py`) dengan 100% kelulusan (184 tests passed, ruff clean, zero regresi).

16. Skeptical Review & Audit Perbaikan Phase 6 (Signal Engine & Daily Ranking Generator)
   Masalah:
   1. Argument CLI `--use-champion` pada `scripts/generate_signals.py` dan target `Makefile` tidak pernah diteruskan ke `engine.generate_signals`, serta tidak memvalidasi mutual exclusion jika user memasukkan `--use-champion` dan `--model-version` sekaligus.
   2. Jika opsi `--use-champion` dipilih tetapi belum ada champion model terdaftar di `ModelRegistry`, `SignalEngine` diam-diam mengambil sembarang candidate model (`candidates[0]`) alih-alih melempar error eksplisit.
   3. `SignalEngine.generate_signals` tidak memvalidasi keberadaan bar pada tanggal yang diminta: jika `signal_date` jatuh pada akhir pekan/libur atau sebelum data harian di-ingest, engine mengembalikan `[]` secara diam-diam sehingga cron job harian mengira tidak ada sinyal beli padahal data belum tersedia. Selain itu, jika seluruh universe kekurangan riwayat bar (< `min_history_bars`), engine tidak melakukan abort/block.
   4. Sanitasi vektor inferensi `x_row` di `SignalEngine` menyisakan objek `None` untuk kolom fitur yang belum tersedia pada riwayat pendek, serta `feature_snapshot` hanya mencakup kolom bawaan `DEFAULT_FEATURE_COLUMNS` sehingga fitur kustom yang dipakai model tereksklusi dari audit.
   5. Garansi immutability pada `SignalRepository` tabel `signals_daily` belum memiliki SQLite trigger proteksi `BEFORE UPDATE`, dan query `get_signals` belum mendukung rentang tanggal `start_date` - `end_date` untuk evaluasi 500-1.000 sinyal historis.
   6. `SignalConfig` belum menyertakan bobot `risk` pada default weights dan menolak `entry_band_pct = 0.0`.
   Solusi:
   1. Menambahkan validasi argumen mutually exclusive di CLI `scripts/generate_signals.py` dan meneruskan flag `use_champion=args.use_champion` ke `SignalEngine.generate_signals`.
   2. Menambahkan parameter `use_champion: bool = False` pada `SignalEngine.generate_signals`, memuat champion classification model secara eksplisit, dan melempar `ValueError` informatif jika champion belum terdaftar.
   3. Memvalidasi `signal_date in all_dates` dan melempar `ValueError` jika tanggal yang diminta bukan tanggal bursa lengkap dalam database. Menambahkan pemeriksaan kelengkapan bar universe dengan melempar `ValueError` jika seluruh ticker memiliki riwayat bar kurang dari `min_history_bars`.
   4. Mengonversi seluruh nilai fitur pada `x_row` ke `float` terhingga atau `np.nan`, serta memperluas `feature_snapshot` agar mencakup gabungan seluruh `feature_names` model dan `DEFAULT_FEATURE_COLUMNS` dengan serialisasi JSON RFC-compliant.
   5. Menambahkan SQLite trigger `trg_signals_daily_prevent_update` pada `signals_daily` untuk memblokir seluruh operasi raw SQL `UPDATE`, serta menambahkan parameter `start_date`, `end_date`, dan `min_probability` pada `get_signals` dan `count_signals`.
   6. Menambahkan komponen `"risk": 0.10` pada default `weights` `SignalConfig` dan mengizinkan `entry_band_pct >= 0.0`.
   7. Menambahkan 5 pengujian unit dan integrasi baru di `test_signals.py` dan `test_signal_pipeline.py` (total 189 tests passed, ruff 100% clean).

17. Implementasi Phase 7 — Telegram Service & Command Dispatcher
   Masalah:
   1. Proyek belum memiliki antarmuka perpesanan Telegram untuk memformat dan menyiarkan sinyal harian saham BEI ke channel/grup pengguna secara otomatis dan deterministik.
   2. Format output sinyal harian belum mengikuti spesifikasi Section 42 (header tanggal, blok ringkasan pasar IHSG/breadth/volatilitas, kandidat Top-N berikon medali 🥇🥈🥉, score, probabilitas, expected return, band entri, TP/SL, durasi holding, dan poin alasan Why berbasis feature snapshot).
   3. Belum ada bot client ringan dengan proteksi keamanan token (Section 76: token tidak boleh bocor dalam log atau repr), mekanisme bounded retries, dan pemisahan lapisan domain dari network requests.
   4. Belum ada decoupled command dispatcher untuk Telegram bot (/start, /help, /daily, /signals, /model) yang mematuhi Rule 1 dan Rule 2 (zero kalkulasi ML/indikator di handler, murni mendelegasikan ke repository dan registry).
   5. Belum ada CLI runner `scripts/send_daily_telegram.py` (dengan dukungan `--dry-run`) serta target `telegram` dan `send-daily` pada `Makefile`.
   Solusi:
   1. Membangun modul pemformat murni `services/telegram/formatter.py` (`format_daily_signals` dan `derive_rationale`) yang menghasilkan pesan Markdown deterministik sesuai Section 42 tanpa ketergantungan jaringan.
   2. Membangun `TelegramClient` di `services/telegram/client.py` berbasis standard library `urllib.request` dengan masking token otomatis (`mask_token`, repr aman, sanitasi URL/error logs) dan bounded exponential retries.
   3. Membangun `TelegramBotDispatcher` di `services/telegram/bot.py` yang mematuhi Rule 1 & Rule 2 secara ketat, hanya membaca `SignalRepository` dan `ModelRegistry` tanpa rekalkulasi ML.
   4. Membuat CLI script `scripts/send_daily_telegram.py` dengan rekonfigurasi UTF-8 console output pada Windows, flag `--dry-run`, `--generate`, `--top-n`, dan `--chat-id`, serta menambahkan target `telegram` dan `send-daily` pada `Makefile`.
   5. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_telegram.py`, `tests/integration/test_telegram_pipeline.py`, dan pembaruan `test_smoke.py`) dengan 100% kelulusan (210 tests passed, ruff 100% clean, zero network leakage).

18. Skeptical Review & Audit Perbaikan Phase 7 (Telegram Service & Command Dispatcher)
   Masalah:
   1. `derive_rationale` dan `_derive_market_summary` pada `services/telegram/formatter.py` melempar unhandled `TypeError: '>' not supported between instances of 'NoneType' and 'float'` ketika feature snapshot dictionary memiliki nilai `None` (missing feature), serta lookup ringkasan pasar bersifat case-sensitive (`market_summary.get("ihsg")` gagal untuk key uppercase `{"IHSG": ...}`).
   2. `TelegramClient.send_message` tidak menangani respons rate limiting HTTP 429 Telegram secara adaptif: mengabaikan header `Retry-After` dan payload JSON `parameters.retry_after`, sehingga sleep eksponensial default terlalu cepat dan menghabiskan retry limit prematur.
   3. `TelegramClient.send_message` tidak memiliki mekanisme pemecahan pesan (message chunking) jika payload melebihi batas 4.096 karakter Telegram Bot API, menyebabkan broadcast Top-N besar (>15-20 sinyal) gagal total dengan HTTP 400 (`message is too long`).
   4. `TelegramClient` langsung melempar error unrecoverable jika Telegram mengembalikan HTTP 400 akibat kesalahan entity parsing Markdown (`can't parse entities`), tanpa fallback otomatis ke pengiriman teks biasa (plain text), sehingga sinyal kritis berisiko hilang.
   5. Command `/signals` pada `TelegramBotDispatcher` belum menampilkan signal ID sebagaimana diwajibkan deliverable spesifikasi Phase 7, dan perintah `/model` mencetak nama metrik dengan karakter underscore tanpa escaping (e.g. `• roc_auc: 0.6200`), memicu potensi syntax error italic pada parser Markdown Telegram. Selain itu, perintah `/compare`, `/positions`, dan `/performance` (Section 41) belum ditangani dengan pesan informatif.
   6. Script CLI `scripts/send_daily_telegram.py` tidak memvalidasi mutual exclusion antara argumen `--use-champion` dan `--model-version`, tidak memvalidasi batas `--top-n >= 1`, serta tidak memperbarui `target_date` dari sinyal yang baru digenerate saat `--date` tidak dispesifikasikan.
   Solusi:
   1. Menambahkan helper `_safe_float` pada `services/telegram/formatter.py` untuk seluruh ekstraksi indikator snapshot, serta menormalisasi key `market_summary` secara case-insensitive.
   2. Menambahkan `_parse_retry_after` pada `TelegramClient` untuk membaca header `Retry-After` maupun field `parameters.retry_after` JSON, serta menerapkan jeda adaptif pada HTTP 429.
   3. Menambahkan helper `split_message` dan chunking otomatis pada `TelegramClient.send_message` dengan pembagian rapi berbasis blok separator `━━━━━━━━━━━━━━━━` dan baris, menjamin seluruh pesan tetap berada di bawah 4.096 karakter.
   4. Menambahkan fallback otomatis pengiriman pesan sebagai teks polos (`parse_mode=None`) saat terjadi error `can't parse entities` dari Telegram API.
   5. Memperbarui `handle_signals` agar menyertakan ID sinyal (`ID: sig_...`), membungkus nama metrik pada `handle_model` dalam backticks (`` `roc_auc`: 0.6200 ``), serta menambahkan handler `/compare`, `/positions`, dan `/performance` pada `TelegramBotDispatcher`.
   7. Menambahkan 7 pengujian unit dan integrasi baru (total 217 tests passed, 100% kelulusan, ruff clean).

19. Implementasi Phase 8 — Manual Position Journal (Principle 2)
   Masalah:
   1. Proyek belum memiliki sistem pencatatan jurnal posisi manual untuk melacak eksekusi riil portofolio pengguna secara terpisah dari sinyal rekomendasi model (Section 22, 23, 41, 65).
   2. Berdasarkan Principle 2 ("Actual positions are separate from signals"), ketiadaan eksekusi terhadap sinyal beli tidak boleh dihitung sebagai posisi merugi dalam portofolio nyata, dan posisi manual harus dapat dibuka baik dengan referensi signal_id maupun tanpa sinyal (discretionary).
   3. Belum ada model domain `PositionRecord` dengan validasi ketat status ('OPEN', 'CLOSED', 'CANCELLED'), alasan keluar ('TP', 'SL', 'EXPIRY', 'MANUAL', 'OTHER'), perhitungan otomatis holding days, serta return terealisasi net of fees.
   4. Belum ada storage SQLite `positions_journal` berindeks, service layer `PositionJournalService`, integrasi command bot Telegram (`/enter`, `/exit`, `/positions`), CLI runner `scripts/manage_positions.py`, dan target `Makefile`.
   Solusi:
   1. Menambahkan domain model `PositionRecord` di `python/common/types.py` dengan UUID otomatis, field `signal_id` nullable (menegakkan Principle 2), normalisasi kanonikal ticker, validasi harga & kuantitas positif terhingga, validasi status dan exit reason, serta cross-field validator untuk siklus hidup posisi terbuka dan tertutup.
   2. Membangun `PositionJournalRepository` di `python/journal/repository.py` berbasis SQLite tabel `positions_journal` dengan indeks `(status)`, `(ticker)`, `(actual_entry_date)`, dan `(signal_id)`, serta method CRUD lengkap (create, get by id/prefix, get open FIFO, get closed, update, filter ticker, count, list).
   3. Membangun `PositionJournalService` di `python/journal/service.py` untuk mengelola pembukaan posisi (`open_position`), penutupan posisi (`close_position`) dengan resolusi FIFO, kalkulasi holding days dan return neto (dikurangi komisi/fee transaksi), pembatalan posisi (`cancel_position`), serta kalkulasi PnL belum terealisasi (`get_unrealized_pnl`).
   4. Mengintegrasikan command bot Telegram di `services/telegram/bot.py` (`/enter <TICKER> <PRICE> <QTY> [SIGNAL_ID]`, `/exit <TICKER_OR_ID> <PRICE> [REASON]`, `/cancel <TICKER_OR_ID> [REASON]`, `/positions`), tetap mempertahankan backward compatibility pengujian pesan Phase 8.
   5. Membuat CLI runner komprehensif `scripts/manage_positions.py` dengan subcommands `enter`, `exit`, `cancel`, dan `list` (format table, json, csv), serta menambahkan target `positions` pada `Makefile`.
   6. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_positions.py`, `tests/integration/test_position_journal_pipeline.py`, pembaruan `test_smoke.py` dan `test_types.py`) dengan 100% kelulusan (226 tests passed, ruff clean, zero regresi).

20. Skeptical Review & Audit Perbaikan Phase 8 (Manual Position Journal)
   Masalah:
   1. `close_position` dan `cancel_position` pada `PositionJournalService` memodifikasi atribut record posisi secara langsung di tempat (in-place mutation) tanpa re-validasi Pydantic, sehingga alasan penutupan ilegal (`INVALID_REASON`), harga non-finite (`NaN`/`Inf`), atau fee negatif dapat langsung tersimpan ke database SQLite `positions_journal`. Saat dibaca kembali oleh query berikutnya (`get_position_by_id`, `get_closed_positions`), aplikasi crash dengan unhandled `ValidationError`.
   2. Cross-field validator `validate_position_lifecycle` pada `PositionRecord` mengabaikan status `CANCELLED`, sehingga record yang dibatalkan dapat diinstansiasi dengan `actual_exit_price`, `actual_exit_date`, atau `realized_return` tanpa memicu error validasi.
   3. `PositionRecord` menerima nilai `realized_return` berupa `NaN`/`Inf` dan menyisakan string spasi kosong pada `signal_id` alih-alih menormalisasikannya menjadi `None`.
   4. `PositionJournalRepository.update_position` dan `create_position` tidak memvalidasi ulang record sebelum menulis ke SQLite via `model_dump()`, dan `get_position_by_id` mengembalikan `None` saat prefix ID cocok dengan lebih dari satu record alih-alih melempar error informatif.
   5. Integrasi Telegram `TelegramBotDispatcher.__init__` menginstansiasi `PositionJournalService` tanpa argumen `bar_repo`, sehingga perintah `/positions` tidak dapat menghitung estimasi unrealized PnL secara otomatis; perintah `/help` melupakan `/cancel`; handler `/positions` mengabaikan argumen filter ticker (`/positions BBCA`); serta angka dengan format koma (`10,000`) ditolak handler `/enter` dan `/exit`.
   6. Script CLI `scripts/manage_positions.py` tidak memiliki blok `try...except` pada subcommand `enter`, tidak memvalidasi fee negatif, dan melempar raw Python traceback unhandled `ValueError` saat pengguna memasukkan format tanggal salah (`--date 2026-99-99`).
   Solusi:
   1. Mengubah `close_position` dan `cancel_position` pada `PositionJournalService` agar memvalidasi harga terhingga positif, fee non-negatif, enum alasan keluar, serta merekonstruksi record `PositionRecord` secara atomik dengan validasi penuh sebelum diteruskan ke repository.
   2. Menambahkan cabang validasi status `CANCELLED` pada `validate_position_lifecycle` di `PositionRecord` yang menolak `actual_exit_price`, `actual_exit_date`, dan `realized_return`.
   3. Menambahkan `@field_validator("realized_return")` untuk menjamin nilai float terhingga dan `@field_validator("signal_id")` untuk normalisasi whitespace menjadi `None`.
   4. Menambahkan re-validasi eksplisit `PositionRecord.model_validate(record.model_dump())` pada `create_position` dan `update_position`, serta melempar `ValueError` informatif pada `get_position_by_id` jika prefix cocok dengan lebih dari satu posisi.
   5. Menginjeksi `DailyBarRepository` secara default pada `TelegramBotDispatcher`, menambahkan `/cancel` ke `/help`, mengimplementasikan filter ticker pada `/positions`, dan membersihkan pemisah koma pada input angka.
   6. Menambahkan sanitasi tanggal dan fee pada CLI `scripts/manage_positions.py` dengan penanganan error stderr yang bersih tanpa traceback dan exit code 1.
   7. Menambahkan 4 pengujian unit dan integrasi baru (termasuk verifikasi multi-threading concurrent writes SQLite WAL dengan 6 worker threads) dengan 100% kelulusan (230 tests passed, ruff clean, zero regresi).

Log Perubahan Tambahan (13 Oktober 2026)
21. Implementasi Phase 9 — Outcome Engine (Triple Barrier, Path Snapshots, & Matured Dataset)
   Masalah:
   1. Proyek belum memiliki sistem pelacakan outcome objektif untuk merekonsiliasi rekomendasi sinyal harian (`signals_daily`) terhadap data pergerakan harga pasar riil (`DailyBarRepository`) menggunakan aturan triple barrier (Sections 24, 25, 50, dan Phase 9 Section 65).
   2. Belum ada domain model `SignalOutcomeRecord` / `OutcomeRecord` dan `SignalDailySnapshot` di `python/common/types.py` untuk merekam status evaluasi sinyal ('OPEN', 'TP', 'SL', 'EXPIRY', 'AMBIGUOUS'), return terealisasi, holding days, metrik path MFE (Maximum Favorable Excursion), dan MAE (Maximum Adverse Excursion).
   3. Belum ada storage SQLite `outcomes_daily` dan `signal_snapshots_daily` berindeks di `python/outcomes/repository.py` untuk persistensi progres harian dan hasil evaluasi sinyal.
   4. Belum ada engine evaluasi triple barrier di `python/outcomes/engine.py` yang mengeksekusi entry pada Hari t+1 Open price, memantau barrier TP/SL pada hari-hari berikutnya, menangani ambiguitas same-candle (kebijakan conservative, optimistic, ambiguous), serta mengeksekusi expiry pada max holding days.
   5. Belum ada builder dataset hasil maturasi di `python/outcomes/dataset.py` yang menggabungkan outcome terselesaikan dengan metadata sinyal asli dan feature snapshot untuk pipeline evaluasi (Phase 10) dan retraining (Phase 11).
   6. Belum ada CLI runner `scripts/resolve_outcomes.py` dan target `outcomes` pada `Makefile`.
   Solusi:
   1. Menambahkan domain model `SignalOutcomeRecord` (alias `OutcomeRecord`) dan `SignalDailySnapshot` di `python/common/types.py` dengan validasi ketat status ('OPEN', 'TP', 'SL', 'EXPIRY', 'AMBIGUOUS'), normalisasi kanonikal ticker, cross-field lifecycle validation, kalkulasi otomatis return terealisasi, dan pelacakan metrik MFE/MAE.
   2. Membangun `OutcomeRepository` di `python/outcomes/repository.py` berbasis SQLite dengan tabel `outcomes_daily` (indeks pada `signal_id`, `ticker`, `signal_date`, `outcome_status`) dan `signal_snapshots_daily` (indeks `signal_id, snapshot_date`), mendukung operasi upsert atomik idempotensial dan query open/matured outcomes.
   3. Membangun `OutcomeEngine` di `python/outcomes/engine.py` yang mengimplementasikan evaluasi triple barrier: entry Hari t+1 pada Open, evaluasi High/Low terhadap TP/SL, resolusi ambiguitas same-candle sesuai kebijakan (conservative: SL first, optimistic: TP first, ambiguous: AMBIGUOUS status), auto-expiry pada Close hari ke-10, serta pelacakan snapshot progres harian dan metrik MFE/MAE.
   4. Membangun `python/outcomes/dataset.py` dengan method `build_matured_outcomes_dataset` dan `export_matured_dataset` untuk menggabungkan outcome matur dengan metadata sinyal dan fitur teknikal snapshot dari `signals_daily` ke format CSV/JSON dengan kolom target biner (`binary_target`).
   5. Membuat CLI runner komprehensif `scripts/resolve_outcomes.py` dengan opsi `--as-of-date`, `--ambiguity-policy`, `--save-db`, `--export-matured`, `--export-path`, `--ticker` dan menambahkan target `outcomes` pada `Makefile`.
   6. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_outcomes.py`, `tests/integration/test_outcome_pipeline.py`, pembaruan `test_smoke.py` dan `test_types.py`) dengan 100% kelulusan (246 tests passed, ruff clean, zero regresi).

22. Skeptical Review & Audit Perbaikan Phase 9 (Outcome Engine)
   Masalah:
   1. Validator lifecycle `validate_outcome_lifecycle` pada `SignalOutcomeRecord` tidak mengecek `realized_return` dan `resolved_at` untuk status `OPEN`, sehingga status terbuka dapat dibuat dengan return terealisasi fiktif atau timestamp penyelesaian sebelum sinyal selesai. Selain itu, validasi tidak menolak `entry_date` yang mendahului `signal_date` (pelanggaran kausalitas data).
   2. `SignalDailySnapshot` tidak memiliki validator konsistensi harga lilin (`high_price >= low_price`), sehingga candle dengan `high_price < low_price` lolos validasi.
   3. Operasi upsert SQLite `save_outcome` dan `save_outcomes` menimpa kolom `notes` dengan `NULL` dan mengubah timestamp `resolved_at` saat re-evaluasi sinyal, menyebabkan hilangnya catatan analisis pengguna dan hilangnya timestamp asli penyelesaian sinyal.
   4. `resolve_all_signals` pada `OutcomeEngine` melakukan N+1 query individual `SELECT * FROM outcomes_daily WHERE signal_id = ?` dan mengeksekusi commit transaksi terpisah di setiap iterasi loop, menimbulkan overhead performa drastis ketika jumlah sinyal mencapai ribuan.
   5. `resolve_signal_by_id` tidak memiliki proteksi idempotensi untuk sinyal yang sudah matur (selalu mengevaluasi ulang terhadap bars dan mengubah `resolved_at`) serta tidak memiliki flag `force_recompute`.
   6. `build_matured_outcomes_dataset` dan CLI runner `scripts/resolve_outcomes.py` belum mendukung opsi `--exclude-ambiguous` untuk memfilter outcome bertatus `AMBIGUOUS` sebelum diekspor ke dataset ML (Phase 10 & 11).
   7. Repository `OutcomeRepository.get_open_outcomes` belum mendukung filter parameter `ticker`.
   Solusi:
   1. Menambahkan validasi ketat pada `validate_outcome_lifecycle` di `python/common/types.py` yang menolak `realized_return` dan `resolved_at` pada status `OPEN`, serta memastikan `entry_date >= signal_date`.
   2. Menambahkan model validator `validate_candle_bounds` pada `SignalDailySnapshot` untuk menjamin `high_price >= low_price`.
   3. Memperbarui klausa `ON CONFLICT` pada `OutcomeRepository.save_outcome` dan `save_outcomes` dengan `COALESCE(excluded.notes, outcomes_daily.notes)` dan `COALESCE(outcomes_daily.resolved_at, excluded.resolved_at)` serta meneruskan parameter `notes` pada `evaluate_signal`.
   4. Menambahkan method batch `get_outcome_statuses_map` pada `OutcomeRepository`, mengoptimasi `resolve_all_signals` menjadi O(1) batch lookup di memori, dan mengelompokkan simpanan `save_outcomes` & `save_snapshots` dalam 1 transaksi atomik.
   5. Memperbarui `resolve_signal_by_id` agar mengembalikan record tersimpan secara langsung dan idempotensial jika sinyal sudah matur (kecuali jika `force_recompute=True`).
   6. Menambahkan parameter `exclude_ambiguous` pada `build_matured_outcomes_dataset` dan argumen `--exclude-ambiguous` pada CLI runner `scripts/resolve_outcomes.py`, sekaligus menambahkan cache pre-fetch sinyal untuk menghindari query N+1.
   7. Menambahkan dukungan filter `ticker` pada `OutcomeRepository.get_open_outcomes`.
   8. Menambahkan 4 pengujian unit baru di `tests/unit/test_outcomes.py` dan memperluas `tests/unit/test_types.py` (total 250 tests passed, 100% kelulusan, ruff clean, zero regresi).

23. Implementasi Phase 10 — Model Evaluation & Champion/Challenger Comparator
   Masalah:
   1. Proyek belum memiliki domain model `EvaluationReport` dan `ComparisonReport` untuk merekam metrik prediksi (Brier score, ECE, log loss, ROC-AUC) serta performa trading out-of-sample (win rate, profit factor, expectancy, max drawdown, Sharpe, avg win/loss).
   2. Belum ada modul komputasi `EvaluationEngine` yang menghitung reliability bins kalibrasi probabilitas secara seragam serta metrik performa trading secara terintegrasi dari dataset historis atau matured outcomes.
   3. Belum ada mekanisme pembanding Champion vs. Challenger (`ModelComparator`) dengan gerbang promosi otomatis (promotion gate) berdasarkan batas minimum sampel, perbaikan profit factor, stabilitas Brier score, toleransi drawdown, dan ekspektansi.
   4. Belum ada CLI runner `scripts/evaluate_models.py` dan target `evaluate` pada `Makefile` untuk mengevaluasi model tunggal maupun komparasi antar model dari registry atau outcomes database dengan format output table, json, dan markdown.
   Solusi:
   1. Menambahkan domain model `TradingMetrics`, `PredictionMetrics`, `CalibrationBin`, `EvaluationReport`, `ComparisonRecommendation`, dan `ComparisonReport` pada `python/common/types.py` dengan validasi Pydantic ketat.
   2. Membangun `EvaluationEngine` di `python/models/evaluation.py` (dan alias di `python/evaluation/engine.py` serta `python/evaluation/__init__.py`) untuk komputasi terpadu ECE, reliability bins, Brier score, ROC-AUC, win rate, profit factor, expectancy, compounded max drawdown, dan Sharpe ratio.
   3. Membangun `ModelComparator` di `python/models/comparator.py` dengan konfigurasi aturan gerbang keputusan otomatis (`PromotionGateConfig`) yang mengevaluasi apakah Challenger layak dipromosikan ke Champion (`PROMOTE`, `REJECT`, `INCONCLUSIVE`).
   4. Membangun formatters output komparasi (`format_comparison_table`, `format_comparison_markdown`, `format_comparison_json`).
   5. Membangun CLI tool `scripts/evaluate_models.py` dengan opsi `--champion-version`, `--challenger-version`, `--dataset-path`, `--from-outcomes`, `--output-format`, `--save-report`, `--min-sample-size`, `--promote-if-passed`, dan menambahkan target `evaluate` pada `Makefile`.
   6. Menulis pengujian unit dan integrasi komprehensif (`tests/unit/test_evaluation.py`, `tests/integration/test_evaluation_pipeline.py`, pembaruan `test_smoke.py` dan `test_types.py`).

24. Skeptical Review & Audit Perbaikan Phase 10 (Model Evaluation & Comparator)
   Masalah:
   1. Perhitungan Max Drawdown di `compute_trading_metrics` tidak menyertakan modal awal 1.0 pada kurva ekuitas (`np.cumprod(1.0 + clipped_returns)`), sehingga peak pertama diinisialisasi pada ekuitas pasca trade pertama (`0.95`). Akibatnya, trade rugi pertama dari modal awal menghasilkan drawdown 0.0% dan kerugian beruntun menghasilkan nilai drawdown yang jauh lebih rendah dari nilai sesungguhnya.
   2. Input return non-finite/null pada `compute_trading_metrics` dan panjang array tidak seimbang pada `compute_calibration_bins` / `evaluate_predictions` tidak divalidasi, memicu polusi `NaN` pada metrik atau error `IndexError` numpy yang tidak tertangani.
   3. `evaluate_dataset` pada `EvaluationEngine` dan CLI script `scripts/evaluate_models.py` tidak memfilter subset baris berdasarkan `model_version`, sehingga saat mengevaluasi dataset outcomes multi-model (Champion dan Challenger dalam 1 tabel), kedua model mengevaluasi data gabungan yang identik dan menghasilkan delta 0.
   4. `evaluate_model` dan `compare_from_registry` tidak mendukung penyaringan trade berdasarkan probabilitas sinyal (`filter_by_prediction`), sehingga metrik trading selalu mengevaluasi seluruh kandidat peluang tanpa memedulikan apakah model menghasilkan sinyal BUY (`prob >= threshold`) atau tidak.
   5. Perbandingan gerbang promosi di `ModelComparator` tidak memiliki toleransi floating-point epsilon (`1e-9`), berisiko memicu penolakan palsu (false reject) akibat ketidakakuratan representasi IEEE-754 pada drawdown dan Brier score yang identik.
   6. Parameter `test_window` berbentuk dictionary ditampilkan sebagai string representasi objek raw Python `{...}` pada tabel perbandingan dan markdown report.
   7. Metrik delta pada `ComparisonReport` belum menyertakan `avg_win_delta` dan `avg_loss_delta`.
   Solusi:
   1. Memperbaiki perhitungan max drawdown dengan menyisipkan modal awal `1.0` di indeks 0 (`np.insert(..., 0, 1.0)`) sehingga penarikan modal dari trade pertama hingga beruntun terhitung dengan akurat (single loss -5% menghasilkan 5.0% drawdown, two losses -5% menghasilkan 9.75% drawdown).
   2. Menambahkan sanitasi nilai non-finite/null menjadi `0.0` pada `compute_trading_metrics`, serta validasi eksplisit `len(y_true) != len(y_prob)` dengan `ValueError` pada `compute_calibration_bins` dan `evaluate_predictions`.
   3. Menambahkan opsi `filter_model_version` pada `evaluate_dataset` yang mengisolasi record sesuai `model_version` target jika kolom tersebut ada pada DataFrame, sehingga evaluasi outcome multi-model berjalan presisi.
   4. Menambahkan parameter `filter_by_prediction` dan `decision_threshold` pada `evaluate_model`, `compare_models`, `compare_from_registry`, serta argumen CLI `--filter-by-prediction` dan `--threshold` pada `scripts/evaluate_models.py`.
   5. Menambahkan proteksi toleransi floating-point `1e-9` pada aturan gerbang keputusan `ModelComparator` (Profit Factor, Brier Score, Max Drawdown, Expectancy).
   6. Menambahkan helper `_format_window_str` untuk memformat `test_window` dictionary menjadi format bersih `"start to end"`.
   7. Menambahkan `avg_win_delta` dan `avg_loss_delta` pada `delta_metrics` `ComparisonReport` serta kolom Avg Win & Avg Loss pada tabel ASCII, Markdown report, dan single model Markdown CLI.
   8. Menambahkan 9 pengujian baru di `tests/unit/test_evaluation.py` dan `tests/integration/test_evaluation_pipeline.py` (total 281 tests passed, 100% kelulusan, ruff clean, zero regresi).

25. Implementasi & Audit Phase 11 — Retraining Pipeline (Sections 29–33, 50, Phase 11)
   Masalah:
   1. Mesin pemicu retraining (`RetrainingTriggerEvaluator`) menggabungkan query `since_date` untuk perhitungan akumulasi volume baru dan evaluasi rolling window degradasi performa; akibatnya jika hanya ada sedikit trade baru sejak retraining terakhir, jendela rolling terpotong sehingga degradasi performa model terlewatkan secara fatal.
   2. `RetrainingPipeline` dan CLI `retrain_model.py` tidak menurunkan anchor `since_date` dari tanggal akhir pelatihan champion (`champ.training_end`), menyebabkan volume trigger terpicu ulang setiap kali dijalankan meski tidak ada outcome baru.
   3. Modul `RetrainingDatasetAssembler` melakukan deduplikasi dengan `drop_duplicates(keep="last")`, yang secara keliru menghapus record fitur historis lengkap dan menyisakan nilai `NaN` saat snapshot fitur outcome tidak lengkap.
   4. `ModelRegistry.rollback_champion` tidak memvalidasi kesesuaian jenis task (misal regresi vs klasifikasi), tidak memblokir rollback ke champion yang sedang aktif, dan tidak memiliki tie-breaker deterministik untuk timestamp identik.
   5. `PromotionGateManager.evaluate_candidate` tidak meneruskan `outcome_statuses` dari dataset uji ke comparator, menyebabkan metrik trading status (TP rate, SL rate, Expiry rate) bernilai 0.0.
   Solusi:
   1. Memperbaiki `RetrainingTriggerEvaluator` pada `python/retraining/trigger.py` dengan memisahkan evaluasi volume baru berbasis anchor `since_date` dari rolling window degradasi performa (tetap mengevaluasi riwayat pasar terkini secara utuh) serta menambahkan filter `exclude_ambiguous`.
   2. Menambahkan resolusi otomatis anchor date pada `RetrainingPipeline` (`champ.training_end + 1 hari`), menambahkan opsi `--since-date` dan `--registry-dir` pada CLI `retrain_model.py`, dan mengikat `db_url` secara konsisten ke seluruh repositori perakit dataset.
   3. Memperbaiki `RetrainingDatasetAssembler.assemble_from_dfs` menggunakan `combine_first` agar seluruh fitur non-null historis tetap terjaga saat label hasil eksekusi outcome diutamakan, serta menambahkan clamping aman pada `split_walk_forward` untuk mencegah error saat jumlah tanggal latih $\le$ `purge_days`.
   4. Menambahkan validasi kecocokan `task` dan proteksi no-op rollback ke active champion, serta tie-breaker `(created_at, model_version)` pada `list_models` di `python/models/registry.py`.
   5. Meneruskan `outcome_statuses` dari `test_dataset.metadata` ke `comparator.compare_from_registry` di `python/retraining/gate.py`.
   6. Menambahkan penanganan eksepsi terstruktur di `RetrainingPipeline.run()` agar kegagalan runtime mengembalikan status `FAILED` secara bersih tanpa crash unhandled.
   7. Menambahkan pengujian regresi komprehensif di `tests/unit/test_retraining.py` dan `tests/integration/test_retraining_pipeline.py` (total 304 tests passed, 100% kelulusan, ruff 100% clean).




26. Implementasi & Penguatan Phase 12 — Cloud Deployment, Serverless Architecture & AWS S3 Sync
   Masalah:
   1. Proyek belum memiliki mekanisme sinkronisasi penyimpanan cloud (S3) untuk file basis data SQLite (`stock_signals.db`) dan model champion joblib/json saat berjalan pada lingkungan ephemeral serverless AWS Lambda (/tmp).
   2. Belum ada handler pipeline AWS Lambda (`lambda_daily_pipeline_handler` dan `lambda_retraining_handler`) untuk mengorkestrasi seluruh tahapan (download DB & model, ingest bars harian, resolve outcome, generate Top-N sinyal, siarkan Telegram, upload DB dan log ke S3) secara otomatis.
   3. Terdapat bug fatal pada `lambda_retraining_handler` di mana evaluasi promosi memeriksa `res.status == "PROMOTED"` (padahal `RetrainingPipeline.run()` mengembalikan `status="SUCCESS"` dan `promoted=True`), menyebabkan model champion hasil promosi tidak pernah diunggah ke S3 dan hilang saat container Lambda berakhir.
   4. Pipeline harian `lambda_daily_pipeline_handler` tidak menyimpan fitur ke `FeatureRepository` dan tidak mengunggah log eksekusi ke S3, sehingga tabel `features_daily` kosong dan riwayat run cloud tidak terlacak.
   5. Berkas basis data SQLite dalam mode WAL berisiko kehilangan commit uncheckpointed saat diunggah langsung ke S3 tanpa checkpointing.
   6. Template AWS SAM `infra/aws/template.yaml` tidak mendefinisikan `CodeUri: ../..`, menyebabkan kegagalan build relatif terhadap direktori root proyek.
   Solusi:
   1. Membangun modul sinkronisasi S3 di `python/cloud/s3_sync.py` (`download_database`, `upload_database`, `sync_models_from_s3`, `sync_models_to_s3`, `bootstrap_database`) dengan pembersihan WAL otomatis (`PRAGMA wal_checkpoint(TRUNCATE)`), verifikasi integritas checksum SHA-256 dan MD5, pembuatan cadangan otomatis bertanda waktu (`database/backups/`), serta inisialisasi skema mandiri jika basis data belum ada di S3.
   2. Memperbaiki logika promosi pada `lambda_retraining_handler` menggunakan `res.promoted` sehingga model champion dan challenger hasil retrain selalu disinkronkan ke S3 `models/` beserta pembaruan basis data.
   3. Mengintegrasikan `FeatureEngine` dan `FeatureRepository` pada Step 4 `lambda_daily_pipeline_handler` untuk mengekstrak dan menyimpan fitur ke `features_daily`, serta menambahkan Step 6 log uploader ke `s3://{bucket}/logs/daily_pipeline_{date}_{ts}.json`.
   4. Memperbaiki template SAM `infra/aws/template.yaml` dengan `CodeUri: ../..`, menambahkan retry backoff untuk propagasi IAM role pada `scripts/deploy_aws.py`, serta menyelaraskan target `deploy` pada `Makefile`.
   5. Menambahkan pengujian regresi untuk retrain promoted (`test_lambda_retraining_handler_promoted`) dan WAL checkpointing (`test_upload_database_wal_checkpoint`), menghasilkan total 320 tests passed (100% kelulusan, ruff 100% clean, zero regresi).
Log Perubahan Tambahan (13 Oktober 2026)
27. Penyelesaian & Live Staging Deployment Phase 12 — Resilient Pipeline, Stage Isolation, Billing Alert & Test Reconciliation
   Masalah:
   1. Rekonsiliasi jumlah test repository: Phase 0–10 = 281 tests, Phase 11 = 23 tests, sedangkan repo melaporkan 320 tests; terdapat 16 preliminary tests Phase 12 (15 di test_aws.py dan 1 di test_cloud_pipeline.py) yang belum terdokumentasi formal dalam audit kelulusan.
   2. Handler AWS Lambda lambda_daily_pipeline_handler belum memiliki proteksi eksekusi ganda (duplicate-run protection) sehingga eksekusi berulang pada hari bursa yang sama berisiko menimpa log atau meregenerasi sinyal identik tanpa persetujuan eksplisit.
   3. Pipeline belum memiliki bounded exponential backoff retry pada saat kegagalan market data provider, dan belum memiliki failure alert otomatis via Telegram dengan penyensoran token/kredensial sensitif untuk notifikasi instan operator.
   4. Script provisioning scripts/deploy_aws.py belum mendukung isolasi stage deployment (--stage dev|staging|prod), memicu tabrakan nama resource dan variabel lingkungan antar stage.
   5. Infrastruktur SAM infra/aws/template.yaml belum memiliki CloudWatch Billing Metric Alarm untuk EstimatedCharges guna menjamin Free Tier AWS ($1.00 USD protection), dan script deploy_aws.py sebelumnya belum menyediakan otomasi pembuatan metric alarm langsung ke CloudWatch API.
   6. Script deploy_aws.py memasukkan reserved key AWS_REGION pada konfigurasi variabel lingkungan Lambda dan tidak memiliki waiter / retry penanganan ResourceConflictException saat pembaruan kode dan konfigurasi Lambda dilakukan berurutan.
   7. Pengecekan duplicate-run S3 sebelumnya hanya memeriksa ada/tidaknya objek log tanpa memeriksa status run (SUCCESS vs FAILED), memblokir pemulihan job jika ada run yang gagal, serta bergantung pada flag buatan strict_duplicate_check.
   8. Handler retraining lambda_retraining_handler belum terhubung ke dispatch_failure_alert() saat runtime pipeline retrain mengalami unhandled exception.
   9. Penyensoran token sensitif mask_sensitive_error belum mencakup secret access keys dan authorization Bearer tokens.
   Solusi:
   1. Melakukan rekonsiliasi dan verifikasi menyeluruh: 281 tests (Phase 0–10) + 23 tests (Phase 11) + 16 tests preliminary (Phase 12) = 320 tests baseline, diperluas menjadi 329 tests komprehensif tanpa mengurangi cakupan uji yang sudah ada.
   2. Mengimplementasikan duplicate-run protection di python/cloud/handlers.py: memeriksa ketersediaan sinyal di basis data (signals_daily) serta menginspeksi payload log S3 secara otomatis; melewatinya dengan status SKIPPED_DUPLICATE hanya jika status run adalah SUCCESS, sehingga run sebelumnya yang gagal (FAILED) tetap dapat dipulihkan secara otomatis (job recovery) kecuali jika force_rerun=True. Menambahkan method get_object pada FakeS3Client.
   3. Mengimplementasikan bounded exponential backoff retry pada konsumsi market data di lambda_daily_pipeline_handler (default 3 percobaan dengan interval eksponensial), serta mekanisme dispatch_failure_alert() dengan sanitasi token (mask_sensitive_error) yang menyiarkan alert kegagalan kritis langsung ke Telegram operator baik pada pipeline harian maupun lambda_retraining_handler.
   4. Menambahkan dukungan --stage [dev|staging|prod] (default staging) pada scripts/deploy_aws.py, mengisolasi nama fungsi (idx-daily-pipeline-staging, idx-retraining-pipeline-staging), IAM execution role (idx-stock-signal-lambda-role-staging), EventBridge schedule (idx-daily-pipeline-schedule-staging), dan tag environment APP_ENV.
   5. Menambahkan fungsi ensure_billing_alarm() dan opsi --deploy-alarm pada scripts/deploy_aws.py serta BillingAlertAlarm pada infra/aws/template.yaml; secara otomatis memverifikasi dan memasang CloudWatch Billing Metric Alarm EstimatedCharges ($1.00 USD, period 6 jam) di region us-east-1 (tempat metrik billing AWS dipublikasikan) dan ap-southeast-3.
   6. Menghapus reserved key AWS_REGION dari env_vars Lambda, menambahkan deteksi error FunctionError pada invoke_lambda_dry_run, dan mengintegrasikan Boto3 waiter function_updated serta backoff retry untuk mencegah ResourceConflictException.
   7. Melakukan deployment langsung (live deploy) ke akun AWS target (436095651956, ap-southeast-3): S3 bucket idx-stock-signal-436095651956-data terbuat dan terisi data seed, basis data, dan model champion; IAM role dan kedua fungsi Lambda staging terdeploy; EventBridge schedule aktif; alarm billing $1.00 USD terpasang aktif di CloudWatch; serta uji kirim notifikasi Telegram terverifikasi sukses (message_id: 14).
   8. Menambahkan 9 unit & integrasi test baru di tests/unit/test_aws.py, seluruh 329 test lulus 100% (zero failure, ruff 100% clean).

28. Upgrade Arsitektur Dual-Mode BEI Stock Signal (LOW_PRICE & HIGHER_PRICE)
   Masalah:
   1. Arsitektur sinyal sebelumnya menyatukan saham harga rendah (IDR 50-300) dan saham likuid harga tinggi (> IDR 300) ke dalam satu model champion tunggal, menyebabkan distorsi probabilitas, friksi fraksi harga IDX tick size yang berbeda, dan risiko slippage tajam pada saham harga kecil.
   2. Model champion dan challenger tidak memiliki pemisahan siklus hidup (lifecycle) berdasarkan mode harga: model yang unggul di saham berkapitalisasi besar otomatis diterapkan ke saham harga rendah tanpa isolasi metrik atau dataset.
   3. Penanganan saham di bawah batas minimum BEI (< IDR 50) dan harga invalid (<= 0, NaN, non-finite) belum memiliki batas fail-closed ketat, berisiko meloloskan sinyal BUY pada saham yang disuspen atau tidak likuid.
   4. Format laporan harian Telegram belum memisahkan bagian sinyal rekomendasi ke dalam MODE A: LOW_PRICE (Rp 50 - Rp 300) dan MODE B: HIGHER_PRICE (> Rp 300) sesuai panduan arsitektur Guide 06.
   5. Pelacakan posisi (journaling), evaluasi outcome triple barrier, dan engine backtest belum mencatat dan mempertahankan mode harga saat keputusan (decision-time price mode immutability) ketika harga saham melintasi batas IDR 300 pada tanggal berikutnya.
   Solusi:
   1. Mengimplementasikan `PriceMode` enum (`LOW_PRICE`, `HIGHER_PRICE`, `EXCLUDED_BELOW_50`, `INVALID`) dan fungsi klasifikasi kanonikal `classify_price_mode(price)` di `python/common/types.py`. Batas IDR 50-300 inklusif untuk LOW_PRICE, dan strictly > IDR 300 untuk HIGHER_PRICE.
   2. Menambahkan atribut `mode` dan properti `mode_id` pada seluruh record domain (`SignalRecord`, `PositionRecord`, `SignalOutcomeRecord`, `TradeRecord`, `LabelRecord`, `SignalConfig`, `Signal`, `Position`, `Prediction`).
   3. Memperbarui `ModelRegistry` di `python/models/registry.py` agar mengisolasi metadata model, promosi champion, resolusi champion aktif, dan riwayat rollback secara independen per mode (`LOW_PRICE` vs `HIGHER_PRICE`).
   4. Memperbarui `DatasetBuilder` dan `Dataset` di `python/models/dataset.py` dengan filter mode otomatis dan penghitungan sebaran data per mode (`mode_counts`).
   5. Memperbarui `SignalEngine` di `python/signals/engine.py` dengan penolakan fail-closed terhadap probabilitas non-positif/non-finite (`prob <= 0.0`), penolakan jika `expected_return` hilang saat diwajibkan, penolakan ketat saham < 50 IDR atau harga invalid, serta fungsi `generate_dual_mode_signals(...)` yang menghasilkan sinyal per mode secara terisolasi.
   6. Memperbarui `services/telegram/formatter.py` dengan `format_dual_mode_signals(...)` yang menyajikan ringkasan pasar terpadu, seksi [MODE A: LOW_PRICE] dan [MODE B: HIGHER_PRICE], serta mempertahankan kompatibilitas penuh dengan pemformat sinyal tunggal.
   7. Menambahkan kolom `mode TEXT` dan migrasi skema SQLite otomatis pada `signals_daily`, `positions_journal`, dan `outcomes_daily`, serta memastikan immutabilitas mode keputusan saat eksekusi posisi dan backtesting di `python/backtest/engine.py`.
   8. Memperbarui CLI scripts (`generate_signals.py`, `send_daily_telegram.py`, `train_model.py`, `run_telegram_bot.py`), command bot Telegram (`/daily`, `/model`), dan AWS Lambda handler `lambda_daily_pipeline_handler` untuk mendukung opsi dual-mode.
   9. Menambahkan 10 pengujian baru (`tests/unit/test_dual_mode.py` [9 unit tests] dan `tests/integration/test_dual_mode_pipeline.py` [1 integration test]) dengan 100% kelulusan (total 339 tests passed, ruff clean, zero regresi).

29. Penguatan & Perbaikan Audit Arsitektur Dual-Mode BEI Stock Signal (LOW_PRICE & HIGHER_PRICE)
   Masalah:
   1. Kebocoran champion lintas-mode (cross-mode champion contamination): Pada `SignalEngine`, ketika model champion untuk `LOW_PRICE` belum tersedia di registry, fallback `get_champion()` tanpa argumen mode secara tidak sengaja meminjam model champion `HIGHER_PRICE` (dan sebaliknya), melanggar aturan isolasi ketat Guide 06.
   2. Ketidaksesuaian tag mode pada inferensi: `SignalEngine` tidak memvalidasi kecocokan `meta.mode` terhadap `eff_mode` ketika `model_version` eksplisit diberikan, sehingga model berlabel `HIGHER_PRICE` dapat dieksekusi pada saham `LOW_PRICE`.
   3. Entitas Label belum mendukung mode: `LabelEngine.compute_label_for_bar()` tidak menyematkan atribut `mode` pada `LabelRecord`, dan tabel basis data `labels_daily` di `LabelRepository` belum memiliki kolom `mode`, migrasi skema, maupun filter kueri mode.
   4. Evaluasi outcome dan dataset comparison belum terisolasi per mode: `build_matured_outcomes_dataset()` di `python/outcomes/dataset.py` tidak memiliki parameter filter `mode` dan tidak menyertakan kolom `mode` di DataFrame hasil; `scripts/evaluate_models.py` belum menyediakan opsi CLI `--mode` untuk evaluasi champion vs challenger independen.
   5. Demosi champion model unsegmented: `ModelRegistry._demote_existing_champions()` mendemosi seluruh champion saat model unsegmented (mode=None) didaftarkan, mengorbankan status champion segmented.
   6. Argumen CLI scripts & format CSV: `scripts/send_daily_telegram.py` mengabaikan argumen `--model-version` saat mode dual berjalan; `scripts/generate_signals.py` melewatkan kolom `mode` pada output format CSV.
   Solusi:
   1. Memperbaiki resolusi model dan regressor pada `SignalEngine` di `python/signals/engine.py`: melarang peminjaman champion mode lain secara mutlak, hanya mengizinkan fallback ke champion legacy unsegmented (mode is None), dan menolak (fail-closed / ValueError) jika tidak ada model yang kompatibel.
   2. Menambahkan validasi kompatibilitas `meta.mode` pada `SignalEngine` saat `model_version` eksplisit dimuat, serta isolasi graceful per mode pada `generate_dual_mode_signals`.
   3. Mengintegrasikan `classify_price_mode(ep)` ke `LabelEngine.compute_label_for_bar()` dan menambahkan kolom `mode TEXT`, migrasi otomatis, indeks, serta filter mode pada `LabelRepository` (`save_labels`, `get_labels`, `get_all_labels`, `count_labels`, `_row_to_record`).
   4. Menambahkan parameter `mode: Optional[str] = None` dan kolom `mode` pada `build_matured_outcomes_dataset()`, serta menambahkan opsi CLI `--mode [LOW_PRICE|HIGHER_PRICE|ALL]` pada `scripts/evaluate_models.py` untuk perbandingan model dan promosi champion independen.
   5. Memperbaiki `_demote_existing_champions()` dan `rollback_champion()` pada `ModelRegistry` agar demosi model unsegmented tidak mendemosi model champion bertag mode.
   6. Meneruskan parameter `model_version` pada `scripts/send_daily_telegram.py` dan `scripts/generate_signals.py`, serta menambahkan kolom `mode` pada header dan baris CSV `scripts/generate_signals.py`.
   7. Memperbarui handler cloud `lambda_daily_pipeline_handler` di `python/cloud/handlers.py` untuk mendeteksi ketersediaan champion mode (`low_champ` atau `high_champ`).
   8. Menambahkan 4 unit test baru di `tests/unit/test_dual_mode.py` (total 13 unit tests dual-mode, 343 keseluruhan repo test suite lulus 100%, ruff 100% clean).

30. Implementasi, Otomasi & Live Deployment 24/7 Telegram Bot Webhook di AWS Lambda & API Gateway
   Masalah:
   1. Bot Telegram interaktif sebelumnya memerlukan proses runtime lokal yang berjalan terus menerus (`run_telegram_bot.py`), tidak serverless, dan mati jika mesin lokal dimatikan.
   2. Pada region AWS `ap-southeast-3` (Jakarta), Lambda Function URL dengan otentikasi publik `AuthType: NONE` mengembalikan respons `403 Forbidden` (`AccessDeniedException`) pada request masuk dari server publik Telegram akibat restriksi regional edge routing.
   3. Handler AWS Lambda memerlukan dukungan payload v2 / Function URL / API Gateway proxy, verifikasi keamanan (`chat_id` dan webhook secret header), persistensi mutasi state (`/enter`, `/exit`, `/cancel`) kembali ke basis data S3, serta fallback pustaka standar mandiri untuk runtime serverless yang ramping.
   4. Script provisioning `scripts/deploy_aws.py` belum mendukung pembuatan dan konfigurasi route AWS API Gateway v2 HTTP API (`apigatewayv2`) untuk mengarahkan request webhook ke Lambda secara otomatis.
   5. Pustaka Telegram client `services/telegram/client.py` belum memiliki method API `set_webhook`, `get_webhook_info`, dan `delete_webhook`.
   Solusi:
   1. Mengimplementasikan handler `lambda_telegram_webhook_handler` pada `python/cloud/handlers.py` yang mendukung ekstraksi pesan Telegram dari event API Gateway proxy / Function URL, verifikasi `allowed_chat_id` & `x-telegram-bot-api-secret-token`, sinkronisasi SQLite dari S3, perutean perintah ke `TelegramBotDispatcher`, pengiriman respons via `TelegramClient`, dan persistensi otomatis mutasi posisi ke S3.
   2. Mengintegrasikan provisioning AWS API Gateway v2 HTTP API (`setup_api_gateway_http_api`) pada `scripts/deploy_aws.py` dengan opsi `--webhook-type [apigw|function_url|both]` (default `apigw`), serta memperbarui template SAM `infra/aws/template.yaml` dengan event `TelegramWebhookApi` bertipe `HttpApi` dan output `TelegramWebhookApiEndpoint`.
   3. Menambahkan method `set_webhook`, `get_webhook_info`, dan `delete_webhook` pada `services/telegram/client.py` dengan penanganan error dan sanitasi token.
   4. Menambahkan fallback pustaka standar ringan tanpa dependensi berat (`numpy`, `pandas`, `pydantic`) pada runtime Lambda untuk modul validasi, tipe data, dan registri model.
   5. Melakukan live deployment ke AWS staging (`436095651956`, region `ap-southeast-3`): Lambda `idx-telegram-webhook-staging` terdeploy, API Gateway `157p0b1mtc` aktif di `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`, dan webhook Telegram terdaftar aktif (`pending_update_count: 0`, respons live HTTP 200 terverifikasi).
   6. Menambahkan pengujian komprehensif di `tests/unit/test_aws.py` (total 36 unit tests AWS lulus 100%, total 355 unit & integration tests repo lulus 100%, ruff 100% clean).

Log Perubahan Tambahan (13 Oktober 2026)
31. Sinkronisasi Deployment Dual-Mode AWS Staging dan Penanganan Sertifikat SSL Windows Corporate
   Masalah:
   1. Paket kode pada fungsi AWS Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, dan `idx-telegram-webhook-staging`) masih menggunakan zip lama sebelum pembaruan arsitektur dual-mode (commit 52ec11d).
   2. Pemanggilan API Telegram via pustaka standar `urllib.request` pada lingkungan Windows corporate mengalami kegagalan validasi sertifikat SSL (`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`) saat menjalankan script manajemen webhook `deploy_aws.py --webhook-status`.
   Solusi:
   1. Menambahkan helper `_urlopen` dengan graceful SSL context fallback pada `services/telegram/client.py` untuk mengatasi inspeksi sertifikat korporat pada mesin pengembang lokal tanpa mengorbankan keamanan runtime Linux serverless.
   2. Menjalankan deployment ulang (`scripts/deploy_aws.py --stage staging --deploy-lambda --set-webhook`) yang memaketkan seluruh kode pembaruan dual-mode ke ketiga fungsi Lambda staging AWS (`ap-southeast-3`).
   3. Memverifikasi status pendaftaran webhook Telegram secara live: endpoint aktif `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook` terhubung sukses dengan HTTP 200 OK dan 0 pending updates.
   4. Seluruh pengujian unit dan linting lulus 100% (63 unit tests AWS & Telegram passed, ruff clean).

Log Perubahan Tambahan (14 Oktober 2026)
32. Hardening Webhook Telegram AWS Lambda, Structured CloudWatch Logging, Otorisasi Group Chat, dan Resilient Delivery Fallback
   Masalah:
   1. Log eksekusi incoming webhook di CloudWatch tidak menampilkan detail update payload, sender chat ID, dan dispatch command karena level logging root Lambda belum diset ke INFO secara eksplisit.
   2. Verifikasi otorisasi hanya memeriksa `sender_chat_id`, sehingga pesan perintah dari user yang berhak (`allowed_chat_id`) yang dikirim di dalam grup chat tertolak karena ID grup berbeda dengan ID user.
   3. Jika pengiriman balasan sinkron via `TelegramClient.send_message` mengalami kegagalan jaringan atau upstream 503 dari Telegram API, pesan balasan berisiko hilang dan tidak terkirim kembali ke pengguna.
   4. Pustaka `services/telegram/client.py` perlu penanganan SSL fallback menyeluruh untuk menangkap variasi error sertifikasi di lingkungan Windows corporate dan Linux runtime Lambda.
   Solusi:
   1. Menambahkan inisialisasi level root logger `logging.getLogger().setLevel(logging.INFO)` dan structured `print()` logs (`[WEBHOOK_EVENT]`, `[WEBHOOK_AUTH]`, `[WEBHOOK_CMD]`, `[WEBHOOK_REPLY]`, `[WEBHOOK_SENT]`) pada `python/cloud/handlers.py` untuk pemantauan real-time yang jelas di AWS CloudWatch.
   2. Memperbarui logika otorisasi pada `lambda_telegram_webhook_handler` untuk mengekstrak dan memvalidasi baik `sender_chat_id` maupun `from_user_id` terhadap `allowed_chat_id`, mengizinkan interaksi dari private chat maupun grup.
   3. Mengimplementasikan dual delivery fallback: respons dikirim via `TelegramClient.send_message`; jika gagal atau token tidak tersedia, handler secara otomatis mengembalikan payload method webhook Telegram `{"method": "sendMessage", "chat_id": ..., "text": ...}` tanpa menduplikasi pesan jika pengiriman langsung berhasil.
   4. Memperluas penanganan SSL fallback pada `_urlopen` di `services/telegram/client.py` untuk menangkap variasi error sertifikat SSL pada Windows corporate.
   5. Menambahkan unit test baru di `tests/unit/test_aws.py` dan `tests/unit/test_telegram.py` (total 66 unit tests lulus 100%, ruff 100% clean).
   6. Menerapkan live deployment ulang ke AWS Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) dan memvalidasi webhook endpoint aktif serta bebas pending updates (`pending_update_count: 0`).
33. Penyempurnaan Webhook Telegram, Callback Query, Timeout Optimization, dan Perbaikan Regresi Integration Test
   Masalah:
   1. Handler `lambda_telegram_webhook_handler` belum mengekstrak data dari `callback_query` (tombol interaktif inline keyboard Telegram), sehingga interaksi tombol menghasilkan respons `no_text`.
   2. Pemanggilan langsung `TelegramClient` di dalam webhook handler belum membatasi timeout dan retry secara optimal (`timeout=5.0, max_retries=1`), berisiko memakan waktu hingga 33 detik saat Telegram API 503/timeout dan melewati batas timeout Lambda 30 detik sebelum fallback respons method webhook dapat dijalankan.
   3. Fallback method webhook `sendMessage` belum membatasi panjang teks `reply_text` ke batas maksimal Telegram (4096 karakter).
   4. Pengujian integrasi `test_end_to_end_cloud_pipeline_cycle` pada `tests/integration/test_cloud_pipeline.py` mengalami kegagalan pada tanggal 14 Oktober 2026 karena `event_run_1` tidak menyematkan tanggal eksplisit sehingga default ke `date.today()`, memicu deteksi duplikat run saat `event_run_2` berjalan pada tanggal yang sama.
   Solusi:
   1. Menambahkan ekstraksi payload `callback_query` data pada `python/cloud/handlers.py` agar interaksi tombol inline diteruskan ke dispatcher dengan sempurna.
   2. Mengonfigurasi `TelegramClient` di dalam webhook handler dengan `timeout=5.0, max_retries=1` dan pembatasan panjang teks fallback `reply_text[:4096]`, menjamin pengalihan instan ke method respons webhook tanpa risiko timeout Lambda.
   3. Memperbaiki `event_run_1` pada `tests/integration/test_cloud_pipeline.py` dengan tanggal eksplisit `"2026-10-13"` agar simulasi hari berikutnya (`"2026-10-14"`) berjalan deterministik kapanpun dijalankan.
   4. Menambahkan unit test `test_lambda_telegram_webhook_handler_callback_query` di `tests/unit/test_aws.py` (total 67 unit tests AWS & Telegram lulus 100%, 358 keseluruhan repo tests passed 100%, ruff 100% clean).
   5. Melakukan live deployment ulang ke AWS Lambda staging dan memvalidasi respons live API Gateway `/help`, `/model`, `/boost` serta CloudWatch logs.
34. Ingestion Data Historis BEI 3+ Tahun, Fitur & Triple-Barrier Labels, Pelatihan Model Champion Dual-Mode, Sinkronisasi Cloud S3, dan Verifikasi Live Webhook
   Masalah:
   1. Database lokal dan cloud sebelumnya hanya memiliki 5 ticker sampel (145 bar) tanpa data historis riil yang memadai untuk pelatihan model machine learning production.
   2. Belum ada model Champion dual-mode terkalibrasi untuk regime `LOW_PRICE` (Rp 50–300) dan `HIGHER_PRICE` (> Rp 300) yang dilatih menggunakan data pasar riil BEI.
   3. Unggahan database SQLite ukuran besar (178 MB) ke S3 rentan mengalami connection drops / timeout pada upload part multipart bawaan botocore di jaringan korporat.
   4. Model registry Lambda di lingkungan serverless berisiko membaca model lama jika folder bersarang (`models/registry`) tidak terdeteksi otomatis atau `sync_models` tidak aktif secara default.
   Solusi:
   1. Melakukan bulk backfill ingestion data harian riil via Yahoo Finance (`scripts/ingest_daily.py`) untuk 208 ticker aktif BEI dari `configs/universe/seed_universe.csv` sejak `2023-01-02` hingga `2026-10-14` (total 186.436 bar harian terverifikasi).
   2. Menghasilkan 186.291 baris fitur teknikal & rezim pasar (`scripts/build_features.py`) dan 185.515 label triple-barrier (`scripts/build_labels.py`) dengan target TP +5%, SL -2%, max holding 10 hari (45.763 sampel `LOW_PRICE` dan 137.426 sampel `HIGHER_PRICE`).
   3. Melatih dan mendaftarkan 2 model Champion LightGBM terkalibrasi (`scripts/train_model.py`):
      - `LOW_PRICE`: versi `lightgbm_classification_20261014_093522` (Brier: 0.1910, LogLoss: 0.5674, ROC-AUC: 0.5539, Accuracy: 0.7405, CalibError: 0.0334).
      - `HIGHER_PRICE`: versi `lightgbm_classification_20261014_093607` (Brier: 0.1884, LogLoss: 0.5643, ROC-AUC: 0.5135, Accuracy: 0.7515, CalibError: 0.0337).
   4. Mengoptimalkan `python/cloud/s3_sync.py` dengan adaptive retry policy dan `TransferConfig` yang stabil (single-stream / resilient non-threaded threshold), berhasil mengunggah database 178 MB (`datasets/stock_signals.db`) beserta backup timestamp ke S3 bucket `idx-stock-signal-436095651956-data`.
   5. Menyinkronkan seluruh artefak model ke S3 prefix `models/` dan `models/registry/`, serta memperbarui `ModelRegistry.__init__` dan handler Lambda agar mengenali folder `registry/` bersarang dan mengaktifkan auto-sync model dari S3.
   6. Melakukan deployment ulang kode ke AWS Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) dan memverifikasi balasan `/model` secara live pada endpoint API Gateway (`https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`) dengan respons HTTP 200 OK yang melaporkan metrik riil kedua Champion.
   7. Menghasilkan sinyal harian trading riil dual-mode menggunakan `scripts/generate_signals.py` dengan probabilitas terkalibrasi dan ranking score.

35. Hardening Kalibrasi Probabilitas Dual-Mode, Retensi Sinyal SQLite/S3, dan Pemulihan Validasi Webhook Callback Query
   Masalah:
   1. Default `min_probability=0.55` pada `SignalConfig` menyebabkan eksekusi CLI `scripts/generate_signals.py` dan handler Lambda `lambda_daily_pipeline_handler` menggugurkan seluruh kandidat sinyal saat menggunakan model Champion terkalibrasi (base win-rate historis bursa riil ~25%).
   2. Eksekusi inferensi sinyal harian `scripts/generate_signals.py` sebelumnya tidak menyertakan flag `--save-db`, sehingga tabel `signals_daily` di database SQLite lokal dan AWS S3 tidak menyimpan sinyal riil tanggal 14 Oktober 2026 dan webhook bot Telegram `/daily` masih merespons data usang 09 Oktober 2026 dengan probabilitas 0%.
   3. Assertion `assert body["status"] == "ok"` pada pengujian unit `test_lambda_telegram_webhook_handler_callback_query` sebelumnya dihapus alih-alih mempertahankan integritas kontrak pengujian.
   Solusi:
   1. Menambahkan fallback otomatis `config.min_probability = 0.25` pada `scripts/generate_signals.py` saat flag `--use-champion` atau `--dual-mode` aktif jika `--min-prob` tidak dispesifikasikan, serta memperbarui `lambda_daily_pipeline_handler` di `python/cloud/handlers.py` untuk mendukung konfigurasi `min_probability` (default 0.25 untuk model terkalibrasi) dengan opsi override via event atau env var `SIGNAL_MIN_PROBABILITY`.
   2. Menghasilkan dan mempersistensikan 10 sinyal riil 14 Oktober 2026 (5 `LOW_PRICE` dan 5 `HIGHER_PRICE`) ke tabel `signals_daily` pada SQLite, menyinkronkan ulang database berukuran 170 MB ke S3 bucket `idx-stock-signal-436095651956-data` (SHA-256: `909d312...`), dan memvalidasi respons `/daily` live pada API Gateway webhook.
   3. Mengembalikan assertion `assert body["status"] == "ok"` pada `test_lambda_telegram_webhook_handler_callback_query` di `tests/unit/test_aws.py`.
   4. Melakukan live deployment ulang paket kode ke AWS Lambda staging dan memvalidasi seluruh test suite (359 passed, 100% kelulusan, ruff clean).
36. Integritas Harga Sinyal (Price Integrity), Pencegahan Range Collapse, Pembulatan Fraksi Harga BEI, dan Klasifikasi WAIT_FOR_BREAKOUT
   Masalah:
   1. Diskrepansi harga kandidat sinyal beli di mana harga entri (IDR 56) jauh menyimpang di atas harga penutupan terakhir (IDR 44) tanpa pengamanan fail-closed.
   2. Range harga entri runtuh menjadi satu titik (single-point collapse, contoh: IDR 56–56, IDR 53–53) akibat ketiadaan pembulatan fraksi harga BEI dan pembulatan integer rupiah pada pemformat Telegram.
   3. Sinyal yang menembus di atas harga referensi dipancarkan sebagai sinyal BUY langsung alih-alih WAIT_FOR_BREAKOUT bersyarat.
   4. Field audit integritas harga belum tercatat pada SignalRecord dan skema basis data SQLite signals_daily.
   5. Transisi batas fraksi harga BEI (contoh: saham harga 500 dan 5000) menghasilkan harga fraksi ilegal di bursa (contoh: 495 pada fraksi 2 atau 4975 pada fraksi 10) akibat penggunaan fraksi harga acuan tunggal.
   6. Celah validasi barrier di mana status BUY dengan policy BREAKOUT dapat lolos tanpa evaluasi deviasi, serta hilangnya informasi Status dan Ref Close pada pemformat telegram single-mode.
   7. Ekspor CSV sinyal harian belum mencantumkan seluruh field audit timestamp dan tanggal bar.
   Solusi:
   1. Menambahkan fungsi pembulatan fraksi harga BEI (get_bei_tick_size, round_down_to_tick, round_up_to_tick, round_to_nearest_tick) pada python/common/types.py sesuai 5 fraksi harga resmi BEI (<200: 1, 200–500: 2, 500–2000: 5, 2000–5000: 10, >=5000: 25).
   2. Menambahkan field audit integritas harga pada SignalRecord: signal_generated_at, market_data_as_of, latest_completed_bar_date, reference_price, entry_low, entry_high, entry_policy, dan status.
   3. Mengimplementasikan validasi deviasi harga pada SignalEngine dan SignalRecord.validate_barriers: menolak deviasi > 5% untuk sinyal BUY langsung, menolak bar basi/mismatched ticker-date, serta menolak divergensi close raw vs adjusted > 5% tanpa aksi korporasi (fail-closed).
   4. Mengimplementasikan outward rounding dan minimum range width (min_range_ticks >= 1) pada SignalEngine serta pengamanan tampilan di services/telegram/formatter.py dan services/telegram/bot.py untuk mencegah keruntuhan rentang harga.
   5. Mengklasifikasikan pemicu breakout di atas batas deviasi menjadi entry_policy="BREAKOUT" dengan status WAIT_FOR_BREAKOUT.
   6. Memperbarui SignalRepository dengan migrasi otomatis skema signals_daily tanpa melanggar immutability trigger dan mempertahankan seluruh baris historis.
   7. Memperbarui pesan Telegram agar secara eksplisit membedakan data harian EOD Yahoo Finance (Daily Close / Not Real-Time Quote) dengan kuotasi real-time bursa.
   8. Menjamin fungsi pembulatan fraksi harga self-correcting terhadap transisi bracket bursa (menghasilkan 496 bukan 495, dan 4970 bukan 4975).
   9. Menutup celah validasi: melarang kombinasi policy BREAKOUT dengan status BUY, dan menolak pemicu breakout di bawah harga referensi.
   10. Melengkapi format Telegram single-mode dan antarmuka bot dengan tampilan Status dan Ref Close.
   11. Menambahkan seluruh kolom audit integritas harga pada keluaran CSV scripts/generate_signals.py.
   12. Menambahkan 23 pengujian unit dan regresi komprehensif pada tests/unit/test_price_integrity.py (382 repo tests passed 100%, ruff 100% clean).
37. Resolusi Alert Kegagalan Pipeline CloudWatch/Telegram (16:30 WIB) dan Pencegahan Kolisi Outcome/Snapshot ID di Lingkungan Serverless
   Masalah:
   1. EventBridge schedule `idx-daily-pipeline-schedule-staging` memicu fungsi Lambda `idx-daily-pipeline-staging` pada pukul 16:30 WIB (09:30:07 UTC) tanggal 14 Oktober 2026 dan memancarkan pesan Telegram failure alert: `'NoneType' object is not callable`.
   2. Pada `python/cloud/handlers.py`, kelas repositori murni SQLite (`OutcomeRepository`, `OutcomeEngine`, `FeatureRepository`, `LabelRepository`) sebelumnya dibungkus di dalam blok `try...except ImportError` bersama pustaka berat (`SignalEngine`, `FeatureEngine`, `run_ingest` / `pandas`, `lightgbm`). Di dalam environment serverless (paket zip 161 KB tanpa numpy/pandas), `ImportError` menyebabkan `OutcomeRepository` menjadi `None`, memicu TypeError sebelum pengecekan duplicate-run protection di baris berikutnya.
   3. Fallback `BaseModel` dan helper `Field` di `python/common/types.py` (yang aktif saat runtime Lambda tidak memiliki library `pydantic`) sebelumnya mengevaluasi `default_factory` hanya satu kali saat pemuatan modul (class attribute level). Akibatnya, setiap instansiasi `SignalOutcomeRecord` dan `SignalDailySnapshot` berbagi `outcome_id` dan `snapshot_id` statis yang sama persis, memicu `sqlite3.IntegrityError: UNIQUE constraint failed: outcomes_daily.outcome_id` saat evaluasi multi-sinyal.
   4. Pengujian unit `test_lambda_daily_pipeline_handler_error_handling` pada `tests/unit/test_aws.py` tidak menyertakan flag `force_rerun=True` sehingga diintersepsi oleh duplicate-run protection saat database lokal telah memiliki sinyal pada tanggal pengujian.
   Solusi:
   1. Memisahkan impor repositori murni SQLite (`DailyBarRepository`, `SignalRepository`, `OutcomeRepository`, `OutcomeEngine`, `FeatureRepository`, `LabelRepository`) keluar dari blok `try...except` agar selalu terdefinisi di modul root level tanpa dependensi ML eksternal.
   2. Menambahkan `_FieldInfo` class dan evaluasi instansiasi dinamis `default_factory` pada fallback `BaseModel.__init__` di `python/common/types.py`, serta menetapkan `outcome_id` dan `snapshot_id` secara eksplisit menggunakan `uuid.uuid4()` pada `python/outcomes/engine.py`.
   3. Memperbaiki `test_lambda_daily_pipeline_handler_error_handling` di `tests/unit/test_aws.py` dengan menambahkan `force_rerun=True, max_retries=1`.
   4. Melakukan live deployment ulang paket serverless ke AWS Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) dan memverifikasi eksekusi live via AWS Boto3:
      - Eksekusi normal: berhasil mengembalikan status HTTP 200 `SKIPPED_DUPLICATE` (sinyal 14 Oktober 2026 terlindungi tanpa duplikasi).
      - Eksekusi forced: berhasil menyelesaikan siklus pipeline HTTP 200 `SUCCESS` (`outcomes_resolved: 2`, `signals_generated: 10`, `db_uploaded: true`, `log_uploaded: true`).


38. Audit Empiris Model Pelatihan & Kualitas Champion Dual-Mode (LOW_PRICE & HIGHER_PRICE)
   Masalah:
   1. Diskrepansi status sinyal BUY dengan probabilitas rendah (~25–32%) dan Expected Return berstatus N/A di Telegram, menimbulkan pertanyaan apakah model champion saat ini valid secara statistik untuk bursa BEI.
   2. Perlunya pembuktian empiris berbasis data historis (out-of-sample) sebelum mengambil keputusan retraining atau tetap mempertahankan model champion.
   Solusi:
   1. Melakukan audit komprehensif terhadap basis data `datasets/stock_signals.db` (186.436 bar, 208 ticker) dan artefak model `models/registry/`.
   2. Mengukur metrik probabilistik out-of-sample (ROC-AUC, Brier score, Log loss) serta simulasi backtest walk-forward riil dengan friksi BEI (fee beli 0,15%, fee jual 0,25%, slippage 10 bps).
   3. Mengidentifikasi cacat kritis: model HIGHER_PRICE memiliki ROC-AUC 0,5135 (tanpa edge prediktif), Brier score 0,1884 lebih buruk dari baseline prevalensi (0,1867), backtest rugi -52,10%, serta kebocoran masa depan pada cross-validation kalibrasi (K-Fold non-kronologis).
   4. Menyusun seluruh temuan dan rekomendasi formal RETRAIN REQUIRED ke dalam berkas dokumentasi permanen `docs/07_audit_training_and_model_quality_report.md`.

39. Implementasi Rencana Remediasi Audit Pelatihan (Items 1–10): Pembersihan Duplikasi Bar, Kalibrasi Kausal & Early Stopping, Gerbang EV Hurdle Fail-Closed, Model Regresi Return Kontinu, dan Evaluasi Walk-Forward Dual-Mode
   Masalah:
   1. Ditemukan 145 bar duplikat pada tabel `daily_bars` basis data `datasets/stock_signals.db` yang berasal dari provider legacy (`provider='unknown'`), berisiko menimbulkan distorsi saat pemisahan dataset.
   2. Modul `python/models/baseline.py` menggunakan `CalibratedClassifierCV(cv=3)` yang menjalankan K-Fold non-kronologis standar sehingga membocorkan data masa depan ke kalibrasi masa lampau, serta tidak memanfaatkan `X_val, y_val` untuk early stopping LightGBM.
   3. DatasetBuilder pada `python/models/dataset.py` mengalami kolisi nama kolom `entry_price` antara feature set (bernilai `None`) dan label set, menyebabkan seluruh harga entri menjadi NaN dan mode harga kolaps menjadi `"INVALID"`.
   4. Engine sinyal memancarkan BUY pada probabilitas rendah (0.25) tanpa evaluasi nilai harapan matematis (EV) setelah memperhitungkan friksi riil BEI (fee beli 0,15%, fee jual 0,25%, slippage 10 bps), menghasilkan ekspektansi negatif (-0.46% s.d. -1.11% per trade).
   5. Sinyal harian tidak memiliki nilai Expected Return karena belum tersedianya model regresi companion terkalibrasi untuk memprediksi return kontinu.
   Solusi:
   1. Menghapus 145 bar duplikat legacy `unknown` pada `daily_bars` dengan tetap mempertahankan data resmi `yfinance`, lalu menjalankan `VACUUM` SQLite (terverifikasi 0 duplikat tersisa).
   2. Mengrombak pipeline validasi kronologis, early stopping, dan kalibrasi probabilitas kausal pada `python/models/baseline.py`: jika `X_val, y_val` tersedia, model dasar difit dengan early stopping pada validasi, kemudian dikalibrasi kausal menggunakan `CalibratedClassifierCV(estimator=FrozenEstimator(base_pipe))` langsung pada set validasi terisolasi tanpa kebocoran masa depan; jika fallback, menggunakan `TimeSeriesSplit(n_splits=3)`.
   3. Memperbaiki bug merging pada `python/models/dataset.py` dengan memprioritaskan `entry_price_label`, sehingga `LOW_PRICE` memuat 45.763 baris dan `HIGHER_PRICE` memuat 137.426 baris secara valid.
   4. Mengimplementasikan gerbang fail-closed Mathematical Expected Value (EV) hurdle check pada `python/signals/engine.py` dan `python/common/types.py`:
      - EV diskret memperhitungkan TP (+4,5% net), SL (-2,5% net), serta empirical outcome expiry (+0,69% net return pada 14,14% trade non-TP), menetapkan batas breakeven win rate matematis sebesar 32,1%.
      - Menolak seluruh kandidat yang memiliki net EV <= 0 atau return regresi <= friksi (0,50%), serta fail-closed jika data esensial tidak lengkap.
   5. Melatih 4 kandidat model baru (2 klasifikasi, 2 regresi companion) dan mendaftarkannya sebagai `challenger` di `models/registry/` (model champion lama tetap terlindungi tanpa mutasi):
      - `LOW_PRICE` Classifier: `lightgbm_classification_20261015_092538`
      - `HIGHER_PRICE` Classifier: `lightgbm_classification_20261015_092608`
      - `LOW_PRICE` Regressor: `lightgbm_regression_20261015_092635`
      - `HIGHER_PRICE` Regressor: `lightgbm_regression_20261015_092710`
   6. Menjalankan evaluasi walk-forward komprehensif pada test set terisolasi (`2026-03-26` s.d. `2026-10-13`) via `scripts/audit_evaluation_runner.py` dan menyimpan artefak JSON di `docs/audit_remediation_evaluation_results.json`:
      - Pada mode unhurdled (thresh=0.25), seluruh model champion dan kandidat mengalami kerugian besar (-26.32% s.d. -52.14%).
      - Pada mode EV Hurdle Gate, sistem fail-closed memblokir 100% taruhan bernilai harapan negatif, menghasilkan total trades = 0, Max Drawdown = 0,00%, dan menyelamatkan modal 100% (Rp 100.000.000 utuh).
   7. Memberikan rekomendasi formal: REJECT kandidat `HIGHER_PRICE` (ROC-AUC 0.4913, di bawah acak), dan CONTINUE TESTING / GATED CANDIDATE untuk `LOW_PRICE` di bawah perlindungan EV hurdle gate tanpa melakukan promosi champion otomatis.
   8. Memastikan isolasi S3 pada unit test `tests/unit/test_aws.py` dan memvalidasi 100% kelulusan seluruh test suite (386 passed, ruff clean).

40. Penguatan Fail-Closed EV Hurdle Gate terhadap Nilai Non-Finite (NaN/Inf) dan Restorasi Status Assertion Unit Test
   Masalah:
   1. Pada `python/signals/engine.py`, fungsi regressor yang memprediksi nilai `NaN` atau `+inf` tidak terdeteksi oleh evaluasi `exp_ret is None`, dan fungsi `min(ev_net_discrete, exp_ret - friction)` pada Python mengevaluasi `min(positive_float, nan)` menjadi `positive_float`. Akibatnya, sinyal BUY dengan nilai `expected_return = nan` tetap dipancarkan meski `require_expected_return=True` atau `enforce_positive_ev=True`.
   2. Pada `tests/unit/test_aws.py`, pengecekan assertion `assert body["status"] == "ok"` sebelumnya terhapus pada `test_lambda_telegram_webhook_handler_callback_query`.
   Solusi:
   1. Memperbarui `python/signals/engine.py` dengan validasi `math.isfinite()` yang ketat pada output regresi, evaluasi `effective_net_ev`, dan pembuatan `SignalRecord`. Menolak secara fail-closed jika nilai yang dibutuhkan tidak finite atau net EV <= min_hurdle.
   2. Menambahkan unit test `test_ev_hurdle_fails_closed_when_regressor_predicts_nan_or_inf` pada `tests/unit/test_signals.py` untuk memverifikasi penolakan mutlak (0 sinyal BUY) saat regressor menghasilkan NaN/Inf.
   3. Mengembalikan assertion `assert body["status"] == "ok"` pada `tests/unit/test_aws.py` dan memperbaiki formatting panjang baris agar 100% mematuhi linter `ruff check .`.


41. Penyusunan Laporan Resmi Remediasi Audit & Evaluasi Kandidat Model Dual-Mode
   - Seluruh hasil implementasi rencana remediasi audit pelatihan (Items 1–10), metrik out-of-sample klasifikasi/regresi, hasil backtest walk-forward riil BEI, serta rekomendasi formal kandidat telah disusun dan disimpan dalam format Markdown permanen pada `docs/08_audit_remediation_and_candidate_evaluation_report.md`.

Log Perubahan Tambahan (15 Oktober 2026)
42. Verifikasi Komprehensif EV Hurdle Gate dan Implementasi Outcome Tracking Terpisah
   Masalah:
   1. Perlunya verifikasi ketat fail-closed Mathematical Expected Value (EV) hurdle gate pada `python/signals/engine.py` terhadap seluruh kondisi batas (EV positif > 0, EV negatif <= 0, breakeven eksak p=32.1% / 32.02%, output non-finite NaN/Inf dari regressor maupun classifier, ekspektansi return hilang saat diwajibkan, deduksi friksi transaksi BEI 50 bps, dan perbandingan EV diskret vs return kontinu).
   2. Pada `python/signals/engine.py`, fungsi `_predict_prob` melakukan `np.clip(prob, 0.0, 1.0)` sebelum pemeriksaan `math.isfinite()`, sehingga nilai probabilitas `+inf` dari classifier secara keliru terpotong menjadi `1.0` (100% win rate) dan lolos memancarkan sinyal BUY.
   3. Residu pembulatan floating point IEEE 754 pada probabilitas breakeven eksak (menghasilkan residu +4.87e-19) meloloskan taruhan bernilai harapan netral jika evaluasi hurdle tidak memperhitungkan ambang batas numerik strictly positive epsilon.
   4. Evaluasi `OutcomeEngine` sebelumnya mengasumsikan entri langsung pada bar pertama (`first_bar.open`) tanpa membedakan kebijakan entri `BREAKOUT` (sinyal `WAIT_FOR_BREAKOUT`), sehingga tidak menanti terpenuhinya level penembusan `entry_low` dan mencatat snapshot sebelum posisi terpicu.
   5. Outcome tracking perlu dipastikan decoupled secara modular tanpa memuat dependensi berat `FeatureEngine`, `SignalEngine`, atau model pembelajaran mesin ML, serta mendukung pelacakan terisolasi untuk mode ganda (`LOW_PRICE` dan `HIGHER_PRICE`).
   6. Pada candle hari pertama pemicu penembusan breakout (`k=1`), jika bar dibuka di bawah harga pemicu (`open < trigger_level`) lalu menyentuh `sl_price`, `OutcomeEngine` sebelumnya mengevaluasi `sl_hit` secara prematur dan tanpa syarat menetapkan status `SL` di harga open (sebelum order sempat terbeli) bahkan saat `ambiguity_policy='ambiguous'` atau `optimistic`.
   Solusi:
   1. Memperbaiki urutan sanitasi fail-closed probabilitas pada `python/signals/engine.py`: validasi `math.isfinite(prob)` dan `prob <= 0.0` kini dieksekusi sebelum `np.clip`, mencegah probabilitas `inf` lolos.
   2. Menambahkan ambang batas toleransi numerik strictly positive (`effective_net_ev <= min_hurdle or abs(effective_net_ev - min_hurdle) < 1e-9`) pada langkah 7 dan langkah 11 `python/signals/engine.py`, menjamin kondisi breakeven eksak (EV = 0.0) gagal-tertutup (fail-closed) tanpa kompromi.
   3. Mengimplementasikan penanganan kebijakan entri `BREAKOUT` pada `python/outcomes/engine.py`: sinyal `WAIT_FOR_BREAKOUT` menanti hingga harga bar menembus `entry_low`, mencatat snapshot harian hanya sejak hari eksekusi entri, menahan status jika belum terpicu, dan menyelesaikan status menjadi `EXPIRY` dengan 0 holding days jika jendela waktu `max_holding_days` habis tanpa penembusan.
   4. Memperluas `OutcomeEngine.resolve_all_signals` dan CLI runner `scripts/resolve_outcomes.py` dengan parameter `--mode` (`LOW_PRICE`, `HIGHER_PRICE`, `ALL`), memungkinkan eksekusi standalone terisolasi per mode harga.
   5. Membuat test suite komprehensif `tests/unit/test_ev_gate.py` (9 pengujian unit yang memverifikasi seluruh skenario batas EV hurdle gate), memperluas `tests/unit/test_outcomes.py` dengan pengujian entri breakout dan mode ganda, serta memperluas `tests/integration/test_outcome_pipeline.py` untuk menguji pipeline CLI end-to-end dan verifikasi independensi/decoupling repositori outcome tanpa dependensi model ML.
   6. Memperbaiki resolusi barrier hari entri breakout pada `python/outcomes/engine.py`: mendeteksi secara presisi bar entri intraday breakout (`k=1` dan `open < trigger_level`), mencegah harga open dijadikan harga exit, serta menangani ambiguitas tubrukan level entri dan stop loss sesuai kebijakan `ambiguity_policy` (`conservative` -> `SL` pada `sl_price`, `ambiguous` -> `AMBIGUOUS` pada `close`, `optimistic` -> posisi bertahan jika candle ditutup di atas `sl_price`). Menambahkan 2 unit test baru di `tests/unit/test_outcomes.py`.

43. Historical Backfill Sinyal & Audit Integritas Outcome Tracking (UNFILLED_EXPIRED, MFE/MAE Clamping, Metrik Jalur, Net Return BEI)
   Masalah:
   1. Sinyal breakout yang kedaluwarsa tanpa pernah terpicu sebelumnya diselesaikan sebagai EXPIRY dengan realized_return = 0.0, terhitung sebagai perdagangan riil impas dan mendistorsi win rate serta ekspektansi model.
   2. Nilai MFE berisiko negatif jika harga tertinggi candle berada di bawah harga entri, dan MAE berisiko positif jika harga terendah di atas harga entri, melanggar invarian matematis MFE >= 0 dan MAE <= 0.
   3. Skema dan repositori outcome belum menyimpan metrik jalur penting (mfe_price, mae_price, time_to_peak, time_to_tp, time_to_sl) dan realized return setelah memperhitungkan friksi riil BEI (net_return).
   4. Evaluasi performa outcome (evaluate_from_outcomes) dan dataset training belum memisahkan sinyal yang tidak tereksekusi dari perdagangan riil.
   5. Perlu audit rekonsiliasi independen historis dan verifikasi idempotensi eksekusi outcome tracking terhadap data candle harian mentah.
   Solusi:
   1. Menambahkan status siklus hidup UNFILLED_EXPIRED pada SignalOutcomeRecord di python/common/types.py dengan holding_days = 0, realized_return = None, net_return = None, dan exit_reason = 'UNFILLED_EXPIRED'.
   2. Memperbarui OutcomeEngine di python/outcomes/engine.py: sinyal breakout kedaluwarsa tanpa penembusan diselesaikan sebagai UNFILLED_EXPIRED; MFE diklem max(0.0, ...) dan MAE diklem min(0.0, ...); menghitung mfe_price, mae_price, time_to_peak (indeks hari titik tertinggi), time_to_tp, time_to_sl, serta net_return menggunakan friksi BEI riil (fee beli 0,15%, fee jual 0,25%).
   3. Mengimplementasikan migrasi otomatis skema SQLite tabel outcomes_daily pada python/outcomes/repository.py untuk menambahkan kolom mfe_price, mae_price, time_to_peak, time_to_tp, time_to_sl, dan net_return secara backward-compatible.
   4. Memperbarui evaluate_from_outcomes di python/models/evaluation.py dan build_matured_outcomes_dataset di python/outcomes/dataset.py agar secara default memfilter status UNFILLED_EXPIRED dan OPEN sehingga tidak mendistorsi statistik perdagangan.
   5. Memperbarui scripts/resolve_outcomes.py dengan ringkasan status UNFILLED_EXPIRED dan opsi CLI --exclude-unfilled.
   6. Menjalankan replay historis pada datasets/stock_signals.db (terverifikasi 100% idempoten, 31 record matured, 0 duplikat), melakukan audit independen via scripts/audit_historical_outcomes.py dengan 0 inkonsistensi terhadap bar harian mentah, serta menyusun laporan lengkap di docs/09_outcome_tracking_backfill_and_integrity_audit_report.md.
   7. Memvalidasi 100% kelulusan test suite (409 passed, ruff clean).
44. Perbaikan Kritis Horison Validitas Breakout, Kolom entry_status, Penyelarasan MAE Snapshot, dan Penanganan UNFILLED_EXPIRED pada Evaluasi Metrik
   Masalah:
   1. Loop penelusuran pemicu breakout (`trigger_level`) pada `python/outcomes/engine.py` sebelumnya memeriksa seluruh bar yang ada tanpa membatasi pada `deduped_bars[: signal.max_holding_days]`. Akibatnya, sinyal breakout yang tidak terpicu dalam horison validitasnya berisiko hidup kembali dan tereksekusi jika harga menyentuh level pemicu di masa depan jauh setelah jendela holding habis (pelanggaran kausalitas dan idempotensi eksekusi).
   2. Metrik wajib `entry_status` belum disimpan sebagai kolom skema independen di `outcomes_daily` dan `SignalOutcomeRecord`, sehingga query DB tidak dapat membedakan langsung status eksekusi entri tanpa mengandalkan inferensi `outcome_status`.
   3. Perhitungan `mae_so_far` pada loop snapshot harian `SignalDailySnapshot` untuk entri intraday breakout hari ke-1 menggunakan harga low mentah candle (sebelum entri terbentuk), bertolak belakang dengan klem MAE `OutcomeEngine` yang mengecualikan low pra-entri.
   4. Fungsi `compute_trading_metrics` dan `evaluate_dataset` pada `python/models/evaluation.py` sebelumnya mengonversi return `NaN` menjadi `0.0` dan memperhitungkan `UNFILLED_EXPIRED` ke dalam pembagi `total_trades`, mendistorsi win rate dan ekspektansi perdagangan riil.
   5. Eksekusi langsung `python scripts/resolve_outcomes.py` gagal dengan `ModuleNotFoundError: No module named 'python'` di lingkungan shell tanpa PYTHONPATH yang disetel secara manual.
   Solusi:
   1. Membatasi pencarian pemicu breakout ketat pada jendela validitas `deduped_bars[: signal.max_holding_days]`, memastikan sinyal kadaluarsa tepat waktu sebagai `UNFILLED_EXPIRED` jika tidak tertembus dalam batas horison, serta mencatat harga tertinggi yang diobservasi (`max_observed_high`) pada field `notes`.
   2. Menambahkan kolom `entry_status` (`FILLED` vs `UNFILLED`) pada `SignalOutcomeRecord`, skema `outcomes_daily`, migrasi otomatis di `OutcomeRepository`, dan dataset export `build_matured_outcomes_dataset`.
   3. Menyelaraskan akumulasi `lowest_low` pada loop snapshot harian menggunakan `effective_lows` (`min(entry_price, close)` saat SL tidak tertembus di hari ke-1 entri intraday breakout), menjamin konsistensi matematis antara snapshot harian dan terminal outcome.
   4. Memperbarui `compute_trading_metrics` dan `evaluate_dataset` agar secara otomatis menyaring status `UNFILLED_EXPIRED` dan `OPEN` dari perhitungan metrik performa trading out-of-sample.
   5. Menambahkan konfigurasi root `sys.path` pada `scripts/resolve_outcomes.py` agar dapat dipanggil langsung dari terminal PowerShell/Bash.
   6. Menambahkan unit test baru di `tests/unit/test_outcomes.py` dan `tests/unit/test_evaluation.py`, menguji seluruh skenario batas horison breakout, konsistensi snapshot MAE, persistensi `entry_status`, dan eksklusi sinyal unfilled pada evaluasi.
45. Remediasi Semantik Metrik Outcome, Pemisahan Lingkup In-Trade vs Horison Penuh, Rekonsiliasi Friksi Eksekusi BEI, Konsistensi Ekskursi Tubrukan, dan Re-komputasi Historis
   Masalah:
   1. Terjadi kebocoran harga ekstrem pasca-keluar pada candle exit: saat posisi keluar via gap open (misal BYAN, ASII, BBCA) atau intraday barrier touch (misal GIAA, LPKR), pergerakan harga setelah barrier tersentuh bocor ke dalam metrik MFE/MAE perdagangan riil (seperti rally BYAN +26.87% tercatat pada posisi yang sudah stop out di open).
   2. Pada tubrukan TP dan SL di candle yang sama (same-bar collision), evaluasi ekskursi sebelumnya tidak konsisten dengan asumsi kebijakan: kebijakan `conservative` (asumsi SL hit lebih dulu) secara keliru menetapkan `bar_in_trade_high = tp_price` (+5% MFE pada posisi yang stop out), dan kebijakan `optimistic` (asumsi TP hit lebih dulu) menetapkan `bar_in_trade_low = sl_price` (-5% MAE pada posisi yang take profit).
   3. Pada hari entri breakout yang menyentuh TP intraday, penetapan `bar_in_trade_low = min(ep, bar.close)` membocorkan pelemahan penutupan pasar sore hari ke dalam in-trade MAE trade yang sudah ditutup profit.
   4. Belum ada pemisahan tegas antara kinerja in-trade aktual yang dibatasi saat exit (Scope A) dengan analisis peluang trajektori counterfactual pada horison observasi penuh (Scope B).
   5. Sinyal breakout yang kedaluwarsa tanpa penembusan (`UNFILLED_EXPIRED`) masih menyimpan harga rencana pada kolom `entry_price` dan `entry_date`, memicu kebingungan apakah order pernah tereksekusi.
   6. Friksi transaksi belum direkonsiliasi secara eksplisit antara Outcome Engine dan EV Hurdle Gate (komisi 0.15% beli, 0.25% jual, dan slippage 10 bps round-trip = 50 bps total friksi).
   Solusi:
   1. Mengimplementasikan pembatasan ekskursi candle exit pada `python/outcomes/engine.py`: gap open exit dibatasi pada harga `bar.open` (MFE BYAN, ASII, BBCA menjadi 0.00%); intraday TP touch dibatasi pada `tp_price`; intraday SL touch dibatasi pada `sl_price`.
   2. Menyelaraskan ekskursi tubrukan same-bar collision: pada `conservative`, ekskursi tertinggi in-trade dibatasi pada `bar.open` / `ep` (MFE 0.00%, karena reli TP terjadi pasca-SL); pada `optimistic`, ekskursi terendah in-trade dibatasi pada `bar.open` / `ep` (MAE 0.00%, karena penurunan SL terjadi pasca-TP); pada `ambiguous`, keluar di `close` dengan ekskursi dibatasi kedua barrier.
   3. Memperbaiki bar entri breakout TP: menetapkan `bar_in_trade_low = ep` (MAE 0.00%) mencegah kebocoran harga close sore hari pasca-exit.
   4. Menambahkan 14 field baru pada `SignalOutcomeRecord` (`python/common/types.py`) dan skema 38 kolom pada `outcomes_daily` (`python/outcomes/repository.py`): memisahkan Scope A (`gross_return`, `return_after_fees`, `return_after_fees_and_slippage` / `net_return`, in-trade bounded `mfe`/`mae`) dan Scope B (`trigger_price`, `observation_end_date`, `full_horizon_mfe`, `full_horizon_mae`, `full_horizon_time_to_peak`, `horizon_end_price`, `horizon_end_return`, `is_full_horizon_complete`).
   5. Menjadikan field entri/trade bernilai `NULL` untuk status `UNFILLED_EXPIRED` dengan `holding_days = 0`, serta menyimpan level pemicu pada `trigger_price` dan akhir observasi pada `observation_end_date`.
   6. Menyelaraskan friksi eksekusi BEI (0.15% beli, 0.25% jual, 10 bps slippage round-trip = 50 bps total friksi impas), menjamin keselarasan 100% dengan gerbang EV Hurdle.
   7. Menambahkan migrasi otomatis idempotensial skema SQLite pada `python/outcomes/repository.py` yang menangani kendala `NOT NULL` warisan dan mengupdate 38 kolom.
   8. Menjalankan re-komputasi historis pada seluruh 31 record matured di `datasets/stock_signals.db` via `scripts/resolve_outcomes.py --force-recompute --save-db`, memvalidasi 100% melalui `scripts/audit_historical_outcomes.py` (0 pelanggaran), memperbarui laporan audit `docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`, serta memvalidasi 100% kelulusan test suite (420 passed, ruff clean).

46. Remediasi Gap Pre-Entri (Status INVALIDATED_GAP), Klarifikasi Semantik Proksi Ekskursi Exit-Bar, dan Re-komputasi Integritas Historis
   Masalah:
   1. Sinyal yang mengalami gap pembukaan Hari ke-1 di luar barrier SL/TP sebelum posisi terbentuk (seperti BYAN pada 2026-08-18 yang gap down -14.9% di bawah SL, ASII pada 2026-10-09, dan BBCA pada 2026-10-09) sebelumnya dianggap sebagai trade terisi (FILLED) yang langsung stop out di harga pembukaan yang sama, memfabrikasi trade fiktif ber-return 0.00% gross dan merusak metrik performa trading dengan kerugian biaya transaksi semu (-0.50% net).
   2. Status siklus hidup outcome belum memiliki status eksplisit untuk membedakan pre-entry gap (order batal sebelum terisi) dengan post-entry gap exit (posisi terbuka yang ter-gap di hari berikutnya).
   3. Perlu klarifikasi semantik proksi konservatif daily-bar pada candle exit: pada TP intraday, MFE dibatasi pada TP sementara MAE secara konservatif merefleksikan harga low candle sebelum mencapai TP; sebaliknya pada SL intraday, MAE dibatasi pada SL sementara MFE merefleksikan harga high candle sebelum menyentuh SL.
   Solusi:
   1. Menambahkan status outcome baru `INVALIDATED_GAP` pada enum siklus hidup (`python/common/types.py`) dengan validasi ketat: `entry_status = 'UNFILLED'`, `holding_days = 0`, serta seluruh field perdagangan riil (`entry_price`, `entry_date`, `exit_price`, `exit_date`, `realized_return`, `net_return`, `mfe`, `mae`) wajib bernilai `NULL`.
   2. Mengimplementasikan deteksi pre-entry gap pada `python/outcomes/engine.py` untuk order immediate entry (`open <= sl_price` atau `open >= tp_price`) dan order breakout (`open >= tp_price` pada candle penembusan). Trajektori Scope B peluang tetap diobservasi relatif terhadap planned reference anchor.
   3. Memperbarui `python/models/evaluation.py` dan `python/outcomes/dataset.py` untuk secara ketat mengecualikan status `INVALIDATED_GAP` dari perhitungan sample size, win rate, dan expectancy perdagangan riil.
   4. Memperbarui `python/outcomes/repository.py` untuk mendukung `INVALIDATED_GAP` pada migrasi database dan secara otomatis membersihkan snapshot harian untuk sinyal unfilled (`UNFILLED_EXPIRED` dan `INVALIDATED_GAP`).
   5. Menjalankan re-komputasi historis penuh dengan `--force-recompute --save-db` pada `datasets/stock_signals.db`: mengoreksi status ASII, BBCA, dan BYAN menjadi `INVALIDATED_GAP`, menurunkan total trade terisi dari 30 menjadi 27, dan memperbarui win rate menjadi 37.04% (0 pelanggaran pada `scripts/audit_historical_outcomes.py`).
   6. Menambahkan suite pengujian komprehensif pada `tests/unit/test_outcomes.py` (termasuk gap pasca-entri Hari ke-2 dan proteksi note pre-entry gap) serta verifikasi jumlah snapshot (0 untuk unfilled, holding_days untuk filled) pada `scripts/audit_historical_outcomes.py`, memvalidasi seluruh test suite (431 passing tests, 100% success rate, ruff clean).



47. Resolusi Ambiguitas Ekskursi Exit-Day (Bounded Interval MFE/MAE), Paritas Snapshot-Outcome 100%, dan Validasi Deviasi Entri Sektoral/MOO
   Masalah:
   1. Ketidakpastian urutan pergerakan harga intraday pada candle exit (apakah MFE/MAE tercapai sebelum atau sesudah barrier touch) menimbulkan ambiguitas matematis yang tidak dapat diselesaikan hanya dengan titik tunggal (single-point proxy), sehingga diperlukan interval batas formal (`mfe_min`, `mfe_max`, `mae_min`, `mae_max`) yang mencerminkan rentang ekskursi yang tak tereduksi dari data daily OHLC.
   2. Snapshot harian (`SignalDailySnapshot`) belum mencatat interval ketidakpastian ekskursi (`mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far`) dan berisiko mengalami disparitas semantik terhadap terminal outcome record pada holding day terakhir.
   3. Validasi harga pembukaan entri immediate (Market-On-Open / MOO) belum memiliki batas deviasi maksimal (`max_entry_deviation_pct`) dan mekanisme penegakan rentang entri ketat (`enforce_entry_band`), sehingga pembukaan pasar yang melonjak atau anjlok jauh melampaui harga referensi sinyal berisiko terisi secara naif.
   4. Terdapat asimetri pada order breakout saat `first_bar.open >= trigger_level` di mana `enforce_entry_band` belum diperiksa secara konsisten terhadap `signal.entry_high`.
   Solusi:
   1. Menambahkan kolom interval bounded excursion pada `SignalOutcomeRecord` (`python/common/types.py`) dan skema tabel `outcomes_daily` (`python/outcomes/repository.py`): `mfe_min`, `mfe_max`, `mae_min`, `mae_max`, `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`, serta kolom `entry_deviation_pct`.
   2. Menambahkan `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, dan `mae_max_so_far` pada `SignalDailySnapshot` dan skema `signal_snapshots_daily`, serta menjamin 100% paritas matematis identik dengan record terminal outcome pada holding day terakhir.
   3. Mengimplementasikan validasi Market-On-Open (MOO) di `OutcomeEngine` (`python/outcomes/engine.py`): pembukaan dengan deviasi melebihi `max_entry_deviation_pct` (default 5.0%) atau berada di luar batas `[entry_low, entry_high]` saat `enforce_entry_band=True` secara otomatis membatalkan sinyal menjadi `INVALIDATED_GAP` dengan metrik Scope A bernilai `NULL`. Kolom `entry_deviation_pct` tercatat presisi pada seluruh trade yang terisi.
   4. Menyelaraskan kebijakan penegakan entry band (`enforce_entry_band`) secara konsisten pada order breakout jika pembukaan candle penembusan berada di atas `signal.entry_high`.
   5. Mengimplementasikan migrasi otomatis skema SQLite yang backward-compatible dan idempotensial pada `python/outcomes/repository.py` untuk 9 kolom baru di `outcomes_daily` dan 4 kolom baru di `signal_snapshots_daily`.
   6. Menambahkan opsi CLI `--enforce-entry-band` dan `--max-entry-deviation-pct` pada `scripts/resolve_outcomes.py`.
   7. Memperbarui `scripts/audit_historical_outcomes.py` dengan asersi invarian: `mfe_min <= mfe <= mfe_max`, `mae_min <= mae <= mae_max`, keberadaan `entry_deviation_pct` pada trade terisi, dan paritas snapshot harian vs terminal outcome pada hari penutupan.
   8. Menjalankan re-komputasi historis penuh pada `datasets/stock_signals.db` (`scripts/resolve_outcomes.py --force-recompute --save-db`) dan audit independen (`scripts/audit_historical_outcomes.py`), memverifikasi 31 rekor historis dengan 0 pelanggaran. Menganalisis dampak historis: 4 record terpengaruh jika `--enforce-entry-band` diaktifkan (`DEWA`, `BMTR`, `ADHI`, `BMTR`).
   9. Menambahkan suite pengujian komprehensif di `tests/unit/test_outcomes.py` (termasuk verifikasi ekskursi tak pasti saat SL tersentuh sebelum high hari ke-2 dan skenario gating pembukaan breakout), mencapai 439 passing tests (100% lulus, ruff clean).

48. Rekonsiliasi Statistik Performa Historis Unrounded, Penyelarasan Proksi MFE dan Semantik Time-to-Peak pada Exit Stop Loss, serta Klarifikasi Ekskursi Lilin Penuh pada Kebijakan Ambiguitas (Modeled Close Exit) (16 Oktober 2026)
   Masalah:
   1. Terjadi diskrepansi penulisan pada laporan audit sebelumnya untuk 27 trade terisi: rata-rata gross return dilaporkan -1.77% dan net return -2.26%, padahal akumulasi per-trade dari baris tabel mengindikasikan gross return ~ -0.17% dan net return ~ -0.67%. Selain itu, nilai Expectancy yang dicantumkan sebagai -0.0017 (-17 bps) sesungguhnya adalah rata-rata gross return, bukan rata-rata net return (yang bernilai -66.95 bps).
   2. Pada cabang Stop Loss (`sl_hit` ordinary dan breakout), penetapan proksi ekskursi `bar_high_proxy = bar.high` mengadopsi batas atas optimis (`mfe_max`), padahal lonjakan harga tersebut tidak dapat dipastikan terjadi sebelum atau sesudah stop loss intraday dari data daily OHLC. Hal ini mendistorsi nilai proksi `mfe` (misal 6 trade SL Hari ke-1 mencatat MFE fiktif +0.85% s/d +5.06%) dan menyebabkan `time_to_peak` menunjuk ke lonjakan harga pasca-stop.
   3. Pada kebijakan ambiguitas `ambiguity_policy="ambiguous"`, model mengeksekusi Modeled Close Exit pada harga penutupan bar (`bar.close`), namun evaluasi ekskursi in-trade sebelumnya masih membatasi pergerakan pada barrier ($\min(High, TP)$ dan $\max(Low, SL)$), yang kontradiktif dengan posisi yang tetap aktif hingga penutupan sesi.
   Solusi:
   1. Menghitung ulang dan merekonsiliasi statistik performa secara langsung dari data unrounded basis data `datasets/stock_signals.db`: Mean Gross Return riil adalah -0.00171376 (-0.1714% / -17.14 bps), Mean Net Return riil adalah -0.00669473 (-0.6695% / -66.95 bps), dan Expectancy terdefinisi secara baku sebagai unweighted Mean Net Return yaitu -0.00669473 (-66.95 bps per trade). Mengidentifikasi bahwa penulis sebelumnya membuat kesalahan pergeseran desimal (-0.001714 keliru ditulis -1.77%) dan tertukar antara gross return dengan expectancy. Mendokumentasikan tabel Before vs After serta skrip kueri SQL dan Python yang reproducible.
   2. Menyelaraskan seluruh cabang Stop Loss pada `python/outcomes/engine.py` untuk menetapkan proksi konservatif lower bound deterministik: `bar_high_proxy = bar_high_lower` (`float(bar.open)` untuk entri biasa, atau $P_{\text{entry}}$ untuk bar entri breakout Hari ke-1). Dengan ini, proksi MFE pada 6 trade SL Hari ke-1 bernilai tepat 0.00% (`mfe == mfe_min`), dan `time_to_peak` mencerminkan puncak in-trade terkonfirmasi sebelum exit bar.
   3. Memperbarui kalkulasi ekskursi pada kebijakan `ambiguous` di `python/outcomes/engine.py` agar merefleksikan rentang penuh lilin $[Low, High]$ (`bar_high_proxy = bar.high`, `bar_low_proxy = bar.low`), sepenuhnya konsisten dengan Modeled Close Exit dan dibedakan dari penafsiran Unresolved Barrier Execution.
   4. Menambahkan 5 targeted regression tests baru pada `tests/unit/test_outcomes.py`: `test_regression_sl_day_high_potentially_occurring_after_stop`, `test_regression_tp_day_low_potentially_occurring_after_target`, `test_regression_time_to_peak_when_exit_day_high_is_uncertain`, `test_regression_ambiguous_policy_candle_touching_both_barriers`, dan `test_regression_reconciliation_report_statistics_with_stored_trade_rows`. Total pengujian bertambah menjadi 61 passed di `test_outcomes.py` dan 444 passed pada seluruh repositori (100% pass rate, ruff clean).
   5. Menjalankan re-komputasi database penuh (`scripts/resolve_outcomes.py --force-recompute --save-db`) dan audit independen (`scripts/audit_historical_outcomes.py`), memverifikasi 31 rekor historis dengan 0 pelanggaran.
   6. Menyelaraskan seluruh dokumen pelaporan: `audit_report.md` (Bagian 1, 2, 3.3, 3.4, 3.7, 3.8, 3.9, 3.10) dan `docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`.
49. Rekonsiliasi Final Dokumentasi Outcome Tracking, Sinkronisasi Metrik Executive Summary, dan Koreksi Jumlah Kolom Skema SQLite outcomes_daily (47 Kolom) (16 Oktober 2026)
   Masalah:
   1. Executive Summary pada `audit_report.md` masih mencantumkan angka performa historis usang akibat kesalahan pergeseran desimal terdahulu (-1.77% gross, -2.26% net, Expectancy -17 bps, holding 4.19 / 3.85 hari), padahal hasil audit detail telah merekonsiliasi nilai unrounded riil (-0.1714% gross, -0.6695% net, Expectancy -66.95 bps, holding 4.48 hari).
   2. Terdapat diskrepansi pada jumlah kolom tabel `outcomes_daily` di mana subbagian dokumen melabelinya sebagai 38 kolom, sedangkan daftar kolom SQL yang didokumentasikan dan skema riil SQLite memuat tepat 47 kolom (akibat migrasi 9 kolom ekskursi batas dan deviasi MOO).
   3. Format dokumen audit belum mengadopsi template governance standar 10 bagian secara penuh (masih terdapat dangling section references, ketiadaan prompt pembagian tes di Section 7, ketiadaan prompt batasan di Section 6, serta hilangnya 4 poin pelaporan baku dan penjelasan unrounded vs display pada bagian Definitions and calculations).
   Solusi:
   1. Menyelaraskan seluruh angka pada Executive Summary dengan Section 4 dan basis data unrounded: Arithmetic Mean Gross Return -0.1714% (-17.14 bps), Arithmetic Mean Net Return -0.6695% (-66.95 bps), Expectancy -66.95 bps (unweighted arithmetic mean net return per trade terisi), Win Rate 37.04% (10 trade positif: 8 TP + 2 Expiry), dan Rata-rata Durasi 4.48 hari perdagangan (121 hari / 27 trade). Menegaskan perbedaan eksplisit antara gross return, net return setelah komisi & slippage, dan expectancy.
   2. Mengoreksi dokumentasi skema SQLite tabel `outcomes_daily` menjadi tepat 47 kolom dan `signal_snapshots_daily` menjadi 14 kolom, memverifikasi seluruh kolom via `PRAGMA table_info` dan DDL skema repository.
   3. Mengadopsi template pelaporan standar 10 bagian secara penuh pada `audit_report.md`: 1. Audit Metadata, 2. Executive Summary, 3. Scope & Acceptance Criteria (memperbaiki sitasi evidence ke Section 4 dan menyertakan catatan kriteria bukti), 4. Quantitative Results (menyusun urutan baku Setup -> Results -> Definitions and calculations dengan 4 poin format standar serta penjelasan unrounded floats vs display vs simulasi, diikuti DDL skema 47 kolom dan tabel 31 rekor matured), 5. Findings (F1–F6), 6. Files & Data Changed (menyertakan pernyataan penegasan batas task), 7. Verification Evidence (membedakan tes riil, tes di-skip, dan klaim tanpa eksekusi), 8. Known Limitations, 9. Reproducibility, 10. Final Decision & Next Step.
   4. Memverifikasi seluruh rangkaian pengujian (444 tests passed, ruff clean, 0 violations pada audit basis data historis).

50. Penyelarasan Kueri Filter Outcome Status dan Sinkronisasi Penamaan Roadmap Phase 11 (16 Oktober 2026)
   Masalah:
   1. Kueri SQL dan skrip Python reproduksi statistik pada `audit_report.md` sebelumnya hanya memfilter `WHERE entry_status = 'FILLED'`, berisiko mencampur posisi yang masih berstatus `OPEN` atau `AMBIGUOUS` ke dalam performa perdagangan jika di masa depan terdapat trade aktif saat evaluasi dijalankan.
   2. Penamaan tahap roadmap berikutnya pada `audit_report.md` menyebut "Phase 10 — Multi-Horizon Evaluation & Feature Ablation", yang bertentangan dengan `README.md` dan panduan teknis `docs/04_...` di mana Phase 10 adalah Model Evaluation (sudah terimplementasi) dan Phase 11 adalah Model Retraining Pipeline.
   Solusi:
   1. Memperbarui seluruh kueri SQL dan skrip Python pada `audit_report.md` dan suite pengujian `tests/unit/test_outcomes.py` agar secara ketat menggunakan klausa filter resmi: `WHERE entry_status = 'FILLED' AND outcome_status IN ('TP', 'SL', 'EXPIRY')`.
   2. Menyelaraskan seluruh referensi fase selanjutnya pada `audit_report.md` (bagian Final Recommendation, Limitations, dan Final Decision/Next Step) menjadi "Roadmap Phase 11 — Model Remediation & Retraining Pipeline (Feature Ablation & Candidate Training)", menghilangkan ambiguitas bagi coding agent.
   3. Memvalidasi seluruh test suite (444 tests passed, 100% success rate, ruff clean).

51. Phase 11A — Controlled Feature Ablation for BEI Dual-Mode Stock Signals (16 Oktober 2026)
   Masalah:
   1. Sebelum melatih dan mempromosikan model kandidat baru pada Phase 11 (Retraining Pipeline), sistem belum pernah menguji kontribusi empiris inkremental out-of-sample dari masing-masing kelompok fitur aktif (30 fitur) untuk mengidentifikasi fitur yang redundan atau merusak performa prediktif.
   2. Belum ada pipeline ablasi leave-one-group-out terkontrol dengan pemisahan temporal walk-forward dan jendela purge (10 hari) untuk mencegah kebocoran label masa depan (lookahead leakage) pada regim harga `LOW_PRICE` dan `HIGHER_PRICE`.
   3. Belum ada perbandingan terhadap baseline sederhana (prevalence baseline) dan baseline non-tree (`LogisticRegressionBaseline`) untuk memastikan kompleksitas pohon keputusan LightGBM memberikan nilai tambah probabilistik nyata.
   Solusi:
   1. Menginventarisasi 30 fitur aktif ke dalam 7 kelompok keluarga fitur terdisjoin (`price_momentum`, `trend`, `oscillators`, `volatility`, `volume_liquidity`, `relative_strength`, `market_regime`), lengkap dengan formula matematis, lookback window, ketersediaan point-in-time, dan dependensi indikator.
   2. Mengimplementasikan engine ablasi fitur `python/experiments/ablation.py` dengan validasi temporal expanding 3-fold walk-forward, jendela purge 10 hari, serta isolasi preprocessing kausal (imputasi median dipelajari strictly pada data training fold).
   3. Mengevaluasi 17 konfigurasi model per fold (model referensi 30 fitur, 7 model ablasi minus-satu-kelompok, prevalence baseline, logistic baseline, dan 7 model diagnostik group-only) pada 135,013 pengujian out-of-sample di `datasets/stock_signals.db`.
   4. Menemukan asimetri empiris fundamental: kelompok `market_regime` sangat krusial bagi `LOW_PRICE` ($\Delta \text{ROC-AUC} = -0.0178$ jika dihapus), namun justru bersifat destruktif/noise bagi `HIGHER_PRICE` ($\Delta \text{ROC-AUC} = +0.0168$ dan Brier Score membaik $-0.0057$ jika dihapus). Sebaliknya, indikator `trend` (EMA) memperburuk performa `LOW_PRICE` di seluruh 3 fold ($\Delta \text{ROC-AUC} = +0.0065$ jika dihapus).
   5. Membuat CLI runner `scripts/run_feature_ablation.py` dan mengekspor artefak machine-readable di `artifacts/ablation/` (`.json` dan `.csv`), menyusun laporan audit komprehensif 10 bagian pada `docs/10_controlled_feature_ablation_report.md`, serta menambahkan unit tests di `tests/unit/test_ablation.py`.
   6. Menjaga 100% integritas model produksi (champion tetap aktif dan tidak tersentuh) serta memvalidasi 448 unit/integration tests (100% passed, ruff clean).

52. Phase 11A.1 — Validasi Agregasi Fold dan Metrik Pemeringkatan Cross-Sectional Harian (16 Oktober 2026)
   Masalah:
   1. Implementasi Phase 11A sebelumnya menggabungkan (pool) seluruh prediksi out-of-sample dari 3 walk-forward folds sebelum menghitung metrik agregat, mendistorsi pemeringkatan cross-fold akibat pergeseran prevalensi positif antarfolds. Bukti paling nyata: prevalence baseline yang memiliki ROC-AUC 0.5000 di dalam tiap fold terdistorsi menjadi 0.5066 pada `LOW_PRICE` dan 0.4953 pada `HIGHER_PRICE` pada tabel pooled.
   2. Metrik `compute_top_k_precision` sebelumnya memeringkat seluruh baris evaluasi pooled multi-tahun, bukan menyeleksi kandidat saham terbaik pada setiap hari perdagangan keputusan (daily cross-sectional ranking).
   3. Belum ada persistensi prediksi out-of-sample per baris (row-level predictions) dan bendera seleksi harian untuk audit transparansi dan reproduktibilitas independen.
   4. Perlu verifikasi apakah kesimpulan kelompok fitur (pemangkasan `trend` pada `LOW_PRICE`, retensi `market_regime` pada `LOW_PRICE`, divergensi `market_regime` pada `HIGHER_PRICE`, dan daya saing regresi logistik) tetap konsisten di bawah metrik per-fold dan ranking harian.
   Solusi:
   1. Memperbaiki engine agregasi metrik pada `python/experiments/ablation.py`: menghitung metrik per-fold (ROC-AUC, PR-AUC, Daily Top-10% Precision, Daily Top-5 Precision, Brier Score, Log Loss, ECE, Accuracy) dan melaporkan agregasi macro (mean, std, min, max) lintas fold. Metrik pooled dipertahankan hanya sebagai diagnostik sekunder dengan disclaimer eksplisit. Memverifikasi bahwa prevalence baseline menghasilkan tepat 0.5000 ROC-AUC di dalam tiap fold dan 0.5000 macro mean (std 0.0000).
   2. Mengimplementasikan fungsi `compute_daily_cross_sectional_top_k_precision` dan `compute_daily_top_n_precision` dengan pengelompokan tanggal keputusan, aturan batas sampel minimum ($N_d \ge 10$), tie-breaking deterministik berurutan `(-prob, ticker ASC)`, seleksi top 10% ($K_d = \max(1, \text{round}(N_d \times 0.10))$), dan agregasi harian macro mean dan micro mean.
   3. Mengekspor seluruh prediksi out-of-sample ke `artifacts/ablation/oos_predictions_{mode}.csv` (33.962 baris untuk `LOW_PRICE`, 101.051 baris untuk `HIGHER_PRICE`) lengkap dengan probabilitas tiap model dan bendera seleksi harian `is_top10_{model}` untuk seluruh 17 konfigurasi model, menambahkan kolom `sample_size`, `positive_count`, dan `prevalence` pada `ablation_results_{mode}.csv`, menjamin `export_artifacts` tidak memutasi dictionary hasil pemanggil secara in-place, serta mengekspor detail per-fold ke `ablation_fold_details_{mode}.csv`.
   4. Mengonfirmasi ulang hipotesis ablasi fitur secara empiris:
      - `LOW_PRICE`: Pemangkasan `trend` terkonfirmasi secara kuat menguntungkan di setiap fold (+0.0078 Macro ROC-AUC, +0.0095 Macro PR-AUC, +2.04% Daily Top-10% Precision, dan perbaikan Brier score).
      - `LOW_PRICE`: Retensi `market_regime` terkonfirmasi esensial (penghapusan menurunkan Macro ROC-AUC sebesar -0.0151 dan menjatuhkan Fold 1 ROC-AUC ke 0.5350).
      - `HIGHER_PRICE`: Penghapusan `market_regime` menunjukkan divergensi fold nyata (merugikan di Fold 1 sebesar -0.0114 AUC dan -0.0233 PR-AUC, namun menguntungkan di Folds 2 dan 3; dampak presisi harian moderat +0.24%).
      - `logistic_baseline`: Terbukti sangat kompetitif (Macro ROC-AUC 0.5629 pada `LOW_PRICE` dengan 32.11% presisi harian, dan 0.5600 pada `HIGHER_PRICE` dengan 0.6095 di Fold 2).
   5. Mendokumentasikan distingsi anchor harga entri label (penutupan $t$) vs eksekusi operasional (Open $t+1$) sebagai bendera review sebelum Phase 11B, menyusun laporan audit komprehensif pada `docs/11_feature_ablation_metric_validation_report.md`, memformat `audit_report.md` menggunakan template standar governance 10 bagian resmi yang diisi dengan seluruh temuan dan metrik Phase 11A.1, serta menambahkan pengujian unit baru pada `tests/unit/test_ablation.py` (total 11 unit tests passed, 455 full test suite passed, ruff clean).

53. Pembuatan Template Laporan Tugas Agen Mandiri (agent_report_template.md) (16 Oktober 2026)
   - Menambahkan file template pelaporan tugas agen `agent_report_template.md` di root repositori dengan struktur 11 bagian (Metadata, Executive Summary, Scope & Acceptance Criteria, Implementation Summary, Results & Evidence, Findings/Risks/Limitations, Verification, Files/Artifacts/Data Changes, Safeguards & Backward Compatibility, Reproducibility, Final Decision) beserta 10 aturan pelaporan baku.
   - Template ini difungsikan sebagai wadah standar untuk pelaporan per-task yang dapat ditimpa/diperbarui pada setiap prompt kerja agen.

54. Phase 11B.0 — Final Target Contract Audit & Template Standard Governance (16 Oktober 2026)
   Masalah:
   1. Terjadi diskrepansi mendasar antara target label supervised learning saat ini (Variant A: Close-Anchor, $P_{\text{entry}} = Close_t$) dengan kebijakan eksekusi riil (Market-On-Open, $P_{\text{entry}} = Open_{t+1}$). Pada Variant A, lonjakan harga gap up semalam $\ge +5\%$ dicatat sebagai kemenangan instan (lookahead phantom profit), sedangkan gap down $\le -2\%$ dicatat sebagai kerugian perdagangan padahal kebijakan operasional membatalkan order sebelum terisi (`INVALIDATED_GAP`).
   2. Belum ada kuantifikasi empiris level basis data mengenai berapa persen sinyal yang terinvalidasi oleh gap pembukaan, berapa pergeseran prevalensi kelas positif, dan berapa banyak label yang berbalik (flip) antara Close-Anchor vs Executable-Entry pada semesta data historis BEI.
   3. File `agent_report_template.md` di root perlu disalin/dipindahkan ke `docs/AGENT_REPORT_TEMPLATE.md` (dan `docs/agent_report_template.md`), dan `audit_report.md` di root harus diselaraskan menjadi indeks ringkas status terkini yang menautkan laporan audit detail dengan format repositori-relatif.
   Solusi:
   1. Menyalin `agent_report_template.md` ke `docs/AGENT_REPORT_TEMPLATE.md` dan `docs/agent_report_template.md` sesuai tata kelola universal template repositori.
   2. Mengembangkan engine audit target contract `scripts/audit_target_contract_runner.py` untuk mengaudit seluruh 186.291 bar harian dan 185.515 label produksi di `datasets/stock_signals.db` tanpa memutasi data produksi:
      - Memvalidasi Variant A (Close-Anchor) dengan 185.510 kecocokan identik terhadap `labels_daily`.
      - Memodelkan Variant B (Executable-Entry Market-On-Open) dengan penegakan pembatalan pra-entri (`GAP_BELOW_SL`, `GAP_ABOVE_TP`, `EXCESSIVE_DEV`, `ZERO_VOLUME_SUSPENDED`) dan re-anchoring barrier TP/SL ke harga Open $t+1$.
   3. Menghasilkan temuan empiris kuantitatif pada 183.184 baris keputusan:
      - Valid Modeled Entries: 92,54% pada `LOW_PRICE` (42.351 baris) dan 96,30% pada `HIGHER_PRICE` (132.337 baris).
      - Invalidated Entries: 7,44% pada `LOW_PRICE` (1.532 gap down, 1.421 suspended, 451 gap up) dan 3,68% pada `HIGHER_PRICE` (3.116 gap down, 1.287 suspended, 648 gap up).
      - Prevalensi positif riil pada kohort tereksekusi turun sebesar $-2,45\%$ pada `LOW_PRICE` ($25,80\% \rightarrow 23,35\%$) dan $-2,66\%$ pada `HIGHER_PRICE` ($24,72\% \rightarrow 22,06\%$).
      - Pada Common Valid Cohort, 5,93% (`LOW_PRICE`) dan 4,89% (`HIGHER_PRICE`) label berbalik arah, didominasi oleh false positives Variant A (rasio asimetri $4:1$, 7.190 phantom wins vs 1.796 recovered wins).
      - Sensitivitas batas rentang ketat $\pm 0,5\%$ mendiskualifikasi 42,31% (`LOW_PRICE`) dan 34,08% (`HIGHER_PRICE`), mengonfirmasi desain `enforce_entry_band=False` pada `OutcomeEngine`.
   4. Mengekspor artefak terstruktur ke `artifacts/target_contract/` (`target_contract_summary.csv/.json`, `target_transitions_by_mode.csv`, dan `target_contract_samples.csv` 30 kasus representatif).
   5. Menyusun laporan audit komprehensif pada `docs/12_phase_11b_target_contract_audit_report.md` menggunakan universal template, memperbarui root `audit_report.md` sebagai indeks status ringkas, menambahkan unit test `tests/unit/test_target_contract.py` (5 passed), dan memvalidasi seluruh test suite (460 passed, ruff clean).

55. Sinkronisasi Data Harian 15–16 Oktober 2026, Penyelarasan Sinyal Dual-Mode Cloud, dan Hardening Logging Lambda Daily Pipeline (16 Oktober 2026)
   Masalah:
   1. Bot Telegram dan perintah `/daily` pada 16 Oktober 2026 masih memancarkan sinyal tanggal 14 Oktober 2026, karena basis data SQLite di S3 (`s3://idx-stock-signal-436095651956-data/database/stock_signals.db`) baru memuat data hingga penutupan 14 Oktober 2026.
   2. Pada eksekusi terjadwal harian di cloud AWS Lambda, paket serverless ringan (193 KB) tidak memuat dependensi berat ML/scikit/pandas/lightgbm (`FeatureEngine` dan `SignalEngine`), sehingga Lambda jatuh ke fallback pembacaan sinyal pre-computed di basis data S3 (`distinct_dates[-1]`).
   3. Level logging root pada `lambda_daily_pipeline_handler` dan `lambda_retraining_handler` sebelumnya belum disetel ke `logging.INFO`, sehingga catatan eksekusi rinci dan fallback diagnostik tidak tampil di CloudWatch.
   Solusi:
   1. Melakukan ingest bar harian pasar BEI untuk tanggal 15 dan 16 Oktober 2026 via `scripts.ingest_daily` (57.730 bar tersimpan, mencakup 201 ticker pada 15 Okt dan 194 ticker pada 16 Okt).
   2. Mengekstrak fitur teknikal pada `features_daily` via `scripts.build_features` untuk seluruh ticker semesta hingga 16 Oktober 2026.
   3. Membangun sinyal harian dual-mode resmi (`LOW_PRICE` dan `HIGHER_PRICE`) menggunakan model champion aktif untuk 15 Oktober (7 sinyal) dan 16 Oktober (10 sinyal: BNII, DILD, HAIS, GOOD, PNLF, DCII, ROTI, PNBN, CFIN, SIDO), serta menyelesaikan outcome via `scripts.resolve_outcomes`.
   4. Mengunggah basis data terbarui `datasets/stock_signals.db` (191,9 MB) ke S3 (`s3://idx-stock-signal-436095651956-data/database/stock_signals.db`) lengkap dengan verifikasi SHA-256 dan cadangan timestamped `stock_signals_20261016_110640.db`.
   5. Menambahkan `logging.getLogger().setLevel(logging.INFO)` pada `lambda_daily_pipeline_handler` dan `lambda_retraining_handler` di `python/cloud/handlers.py`, serta mendeploy ulang seluruh fungsi Lambda staging (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`).
   6. Menguji endpoint live API Gateway webhook (`https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`) dengan perintah `/daily` dan memverifikasi bot langsung merespons sinyal tanggal 16 Oktober 2026 ("16 Oct 2026 (Daily Close / Not Real-Time Quote)"), serta mengirimkan siaran langsung via Telegram bot (`message_id=83`).

56. Phase 11B.1 — Pelatihan & Evaluasi Model Kandidat Lintas Kontrak Target dan Simulasi Trading (19 Oktober 2026)
   Masalah:
   1. Perlu pembuktian empiris apakah temuan Phase 11A (pemangkasan fitur `trend` pada `LOW_PRICE` dan `market_regime` pada `HIGHER_PRICE`) serta re-anchoring target kontrak Phase 11B.0 (Variant B: Market-On-Open) menghasilkan perbaikan kinerja prediktif out-of-sample dan profitabilitas trading riil setelah memperhitungkan friksi transaksi BEI (50 bps).
   2. Model kandidat penantang tidak boleh memutasi atau menggantikan model champion produksi (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`) tanpa verifikasi out-of-sample yang ketat, dan seluruh artefak eksperimen harus diisolasi di luar registri produksi.
   3. Diperlukan simulasi trading discrete-event yang mencerminkan eksekusi pembukaan nyata (Next-Session Open), penanganan suspensi nol-volume, pembatalan gap pra-entri ($\le -2\%$ atau $\ge +5\%$), batasan lot (100 lembar), dan alokasi modal portofolio (maksimal 5 posisi konkuren).
   Solusi:
   1. Mengembangkan engine evaluasi model kandidat `python/experiments/candidate_eval.py` dan script runner `scripts/run_candidate_evaluation.py` dengan validasi expanding walk-forward 3-fold, jendela purge 10 hari, serta isolasi preprocessing kausal pada semesta data historis BEI.
   2. Melatih dan mengevaluasi 16 konfigurasi model kandidat (8 model pada `LOW_PRICE`, 8 model pada `HIGHER_PRICE`) yang mencakup LightGBM Full (30 fitur), model ablasi pilihan Phase 11A.1, baseline Regresi Logistik ter-regularisasi, dan baseline prevalensi konstan di bawah Target Variant A (Close-Anchor) dan Variant B (Next-Open Executable Anchor).
   3. Mengevaluasi metrik prediktif probabilistik (ROC-AUC, PR-AUC, Brier score, log loss, ECE) serta pemeringkatan cross-sectional harian (Daily Top-10% dan Daily Top-5 Precision), baik pada kohort native masing-masing target maupun pada kohort valid bersama (common valid cohort).
   4. Mengonfirmasi keunggulan operasional Variant B dalam menekan pembatalan gap: pada `HIGHER_PRICE`, model Variant B memangkas pembatalan gap pra-entri hingga separuh ($157 \rightarrow 79$ pada model full), meningkatkan win rate ($25,48\% \rightarrow 28,07\%$), dan menurunkan drawdown maksimum dari $60,23\%$ menjadi $45,02\%$.
   5. Melakukan simulasi trading discrete-event dengan friksi komisi beli 0,15%, komisi jual 0,25%, slippage 10 bps, dan batas 5 posisi: menemukan bahwa seluruh model kandidat menghasilkan net return negatif ($-0,49\%$ hingga $-0,79\%$ per trade) dan profit factor di bawah 1,0 ($0,59$ hingga $0,71$) karena ambang batas break-even setelah biaya membutuhkan win rate $> 32\%$.
   6. Menetapkan keputusan governance `DO_NOT_PROMOTE`: tidak ada model kandidat yang dipromosikan menggantikan champion produksi, champion tetap aktif dan utuh, mengekspor 13 artefak terstruktur ke `artifacts/candidate_eval/`, menyusun laporan komprehensif `docs/13_phase_11b_candidate_model_evaluation_report.md` menggunakan universal template, memperbarui `audit_report.md`, serta menambahkan pengujian unit pada `tests/unit/test_candidate_evaluation.py`.

57. Phase 11B.1 — Rekonsiliasi Metrik Simulasi Trading & Penyelarasan Kontrak Biaya Produksi (50 bps) (19 Oktober 2026)
   Masalah:
   1. Konfigurasi simulator trading pada `python/experiments/candidate_eval.py` menerapkan `slippage_bps=10.0` secara independen pada fill entri dan fill exit, menghasilkan total round-trip slippage 20 bps (nominal round-trip friction 60 bps: komisi beli 15 bps + komisi jual 25 bps + slippage entri 10 bps + slippage exit 10 bps), yang tidak selaras dengan kontrak biaya produksi baku sebesar 50 bps round-trip (komisi beli 15 bps, komisi jual 25 bps, dan total slippage round-trip 10 bps).
   2. Metrik profit factor pada laporan sebelumnya hanya merepresentasikan rata-rata aritmetika fold (`mean_profit_factor`), belum menyajikan true pooled profit factor dari total net gain dan total net loss lintas trade.
   3. Angka drawdown pada tabel pooled sebelumnya mencatat drawdown terburuk per-fold (`worst_fold_max_drawdown_pct`), namun dilabeli ambigu sehingga berisiko disalahartikan sebagai continuous portfolio drawdown dari kurva ekuitas portofolio berkesinambungan.
   4. Terdapat diskrepansi rentang return pada ringkasan eksekutif (tertulis -0.49% hingga -0.79% karena mengabaikan baseline yang mencapai -1.01%), serta inkonsistensi pencatatan jumlah pengujian (463 vs 468).
   Solusi:
   1. Memperbaiki simulator trading pada `python/experiments/candidate_eval.py` dengan parameter alokasi slippage eksplisit: `slippage_entry_bps=5.0` (5 bps pada harga Open $t+1$) dan `slippage_exit_bps=5.0` (5 bps pada harga exit barrier), menjamin total round-trip slippage tepat 10 bps dan total friksi nominal 50 bps.
   2. Menambahkan method `recompute_trading_from_saved_predictions` dan opsi CLI `--recompute-trading-only` pada `scripts/run_candidate_evaluation.py` untuk mengalkulasi ulang simulasi trading secara instan (~90 detik) langsung dari artefak prediksi out-of-sample yang telah tersimpan (`candidate_oos_predictions_{mode}.csv`) tanpa melatih ulang model (zero retraining).
   3. Mengimplementasikan komputasi metrik eksplisit:
      - Menghitung true pooled profit factor ($\sum \text{gain} / \sum |\text{loss}|$ across all completed trades: $0,52$ hingga $0,80$) di samping mean fold profit factor ($0,52$ hingga $0,79$).
      - Membedakan secara tegas worst-fold maximum drawdown ($34,46\%$ hingga $83,24\%$) dari continuous portfolio maximum drawdown ($62,63\%$ hingga $98,54\%$) yang memodelkan pemajemukan kurva ekuitas 663 hari bursa secara berkesinambungan.
      - Menghitung ulang seluruh net return dengan rentang konsisten mencakup seluruh 16 kandidat: $-0,33\%$ hingga $-0,92\%$ per trade.
   4. Memperbarui seluruh artefak JSON dan CSV pada `artifacts/candidate_eval/`, merekonsiliasi dokumen formal `docs/13_phase_11b_candidate_model_evaluation_report.md` (tabel sebelum vs sesudah rekonsiliasi, definisi metrik matematis, rentang konsisten), memperbarui `audit_report.md`, serta menambahkan 3 pengujian unit baru pada `tests/unit/test_candidate_evaluation.py` (total 11 unit tests passed, 471 full suite tests passed, ruff clean 0 error).

58. Phase 11C — Evaluasi Multi-Horizon, Regresi Return Kontinu, dan Diagnostik Expected Return (19 Oktober 2026)
   Masalah:
   1. Perlu pembuktian empiris apakah variasi horizon penahanan (holding horizon: 3, 5, 10, dan 15 hari perdagangan) serta pemodelan estimasi return langsung (regresi return kontinu vs baseline rata-rata dan nol) dapat memperbaiki kinerja prediktif out-of-sample dan profitabilitas trading bersih di bawah kontrak friksi 50 bps.
   2. Evaluasi multi-horizon hingga 15 hari membutuhkan pengendalian kebocoran temporal yang ketat melalui jendela purge/embargo 15 hari pada seluruh split walk-forward.
   3. Perlu perbandingan komparatif antara estimasi return kontinu via regresi LightGBM dengan ekspektasi diskret multi-outcome ($P(TP) \times +5\% + P(SL) \times -2\% + P(Exp) \times \bar{R}_{exp} - 50\text{ bps}$) serta uji diagnostik offline filtering EV.
   Solusi:
   1. Mengembangkan engine multi-horizon `python/experiments/multi_horizon_eval.py` dan runner CLI `scripts/run_multi_horizon_evaluation.py` dengan evaluasi simultan 4 horizon ($H \in \{3, 5, 10, 15\}$), target Variant B (Next-Open execution), barrier TP $+5\%$ dan SL $-2\%$, serta jendela purge 15 hari pada WalkForwardSplitter expanding 3-fold.
   2. Melatih dan mengevaluasi matriks model terkontrol per mode per horizon: Full LightGBM Classifier, Best Ablation LightGBM (`minus_trend` untuk LOW_PRICE, `minus_market_regime` untuk HIGHER_PRICE), Regularized Logistic Regression, Prevalence Baseline, LightGBM Regressor return bersih kontinu, Zero-Return Baseline, dan Training-Mean Baseline.
   3. Menemukan paradoks horizon: horizon pendek ($H=3$) menghasilkan ROC-AUC tertinggi (hingga 0.6566 pada HIGHER_PRICE dan 0.6093 pada LOW_PRICE) namun memicu churn trading berlebihan (2.000+ trade) dan drawdown terburuk (-92% s.d. -99%). Sebaliknya, perpanjangan ke $H=15$ memangkas trade hingga $>50\%$, menurunkan drawdown secara drastis (worst-fold 25,88% dan continuous 45,50% pada LOW_PRICE Regressor), namun seluruh konfigurasi tetap mencetak return bersih negatif ($-0,33\%$ hingga $-1,00\%$ per trade) dan profit factor di bawah 1,0 ($0,47$ hingga $0,80$).
   4. Menguji diagnostik Expected Return: regressor menghasilkan korelasi positif terhadap return realisasi ($r = +0,06$ s.d. $+0,10$), namun filtering berbasis EV positif terbukti sangat bergantung pada rezim pasar makro (menghasilkan return positif $+0,06\%$ pada bull market Fold 1, tetapi jatuh ke $-0,87\%$ pada bear market Fold 3).
   5. Menetapkan keputusan governance `DO_NOT_PROMOTE`: champion produksi tetap aktif dan tidak berubah. Memperbaiki bug double-prefix model_id (`lgb_minus_trend` dan `lgb_minus_market_regime`), mengisolasi kebocoran ambiguous count antar-horizon, menghilangkan lookahead pada valuasi sizing Market-On-Open, mengekspor 10 artefak lengkap ke `artifacts/phase_11c/` (termasuk `multi_horizon_regression_binned_diagnostics.csv` dan `multi_horizon_trading_by_fold.csv`), menyusun laporan formal `docs/14_phase_11c_multi_horizon_return_evaluation_report.md` berbasis universal template (dengan Tabel 5.5 kalibrasi binned), memperbarui `audit_report.md`, serta menambahkan 9 pengujian unit pada `tests/unit/test_multi_horizon_evaluation.py` (total 480 tests passed, ruff clean 0 error; mengoreksi diskrepansi dokumentasi awal yang mencatat 478).

59. Phase 11D — Riset Kebijakan Dynamic Exit, Selektivitas Cross-Sectional, dan Market Regime Conditioning (19 Oktober 2026)
   Masalah:
   1. Temuan Phase 11C menunjukkan bahwa seluruh model regresi dan klasifikasi multi-horizon tetap merugi setelah memperhitungkan friksi 50 bps (-0.33% s.d. -1.00% per trade). Diperlukan investigasi apakah intervensi kebijakan post-prediksi (selektivitas entri Top 10% s.d. 1%, pengkondisian rezim pasar point-in-time, durasi penahanan dinamis, dan barrier TP/SL dinamis) dapat membalikkan defisit transaksi tanpa melatih ulang model atau memutasi champion produksi.
   2. Simulasi kebijakan harus sepenuhnya kausal tanpa bias lookahead, mempertahankan kontrak eksekusi Market-On-Open (Variant B), pembatalan gap pra-entri, batasan lot 100 lembar, kapasitas maksimal 5 posisi (alokasi 20% ekuitas), dan evaluasi walk-forward expanding 3-fold.
   3. Terdapat risiko kebocoran data uji (test data leakage) pada kalkulasi median ATR dan pengali barrier TP/SL jika dihitung dari partisi data uji fold bersangkutan, ringkasan modular CSV sebelumnya belum menyertakan baris kontrol acuan baseline, serta metrik perputaran portofolio (turnover) dan eksposur waktu di pasar (time in market) belum dihitung secara eksplisit.
   Solusi:
   1. Mengembangkan engine evaluasi kebijakan modular pada `python/experiments/policy_eval.py` dan runner CLI `scripts/run_policy_evaluation.py` dengan optimasi pencarian bar lookup cache dan pengelompokan kandidat berbasis kamus (kecepatan eksekusi 156 simulasi dalam 72 detik).
   2. Mengeliminasi test data leakage pada `compute_fold_training_stats` dengan menghitung statistik median ATR, persentil 75 MFE, dan median MAE secara kausal dari database SQLite untuk tanggal-tanggal sebelum tanggal awal pengujian fold dikurangi jendela purge 15 hari bursa (`date <= train_cutoff_date`).
   3. Menambahkan baris kontrol eksplisit pada seluruh CSV ringkasan modular (`exp_a_control_top5`, `exp_b_none`, `exp_c_fixed_h15`, dan `exp_d_control`), serta menghitung metrik `eligible_candidates`, `portfolio_turnover`, `daily_turnover`, dan `time_in_market_pct`.
   4. Mereplikasi baseline acuan Phase 11C secara identik: LOW_PRICE H=15 regressor (856 trade, net return -0.33%, PF 0.80, worst-fold DD 26.43%, continuous DD 46.01%, turnover 154.3x) dan HIGHER_PRICE H=15 full classifier (980 trade, net return -0.49%, PF 0.72, turnover 166.1x).
   5. Mengeksekusi Eksperimen A (Selektivitas Cross-Sectional): menguji pemeringkatan harian Top 10%, Top 5%, Top 3%, dan Top 1%. Menemukan bahwa pada HIGHER_PRICE, Top 1% meningkatkan win rate dari 28.27% menjadi 30.29%, menekan net loss ke -0.36%, memangkas turnover ke 117.1x, dan memangkas continuous drawdown dari 62.67% ke 40.58%. Pada LOW_PRICE, Top 3% s.d. Top 5% terbukti paling stabil.
   6. Mengeksekusi Eksperimen B (Pengkondisian Rezim Pasar): menguji 5 filter predeclared berbasis indikator point-in-time. Menemukan bahwa filter tren IHSG (`ihsg_vs_ema20 > 0`) adalah tuas mitigasi risiko paling efektif: memangkas continuous drawdown sebesar >60% (dari 46.01% ke 16.65% pada LOW_PRICE dan 62.67% ke 23.43% pada HIGHER_PRICE) serta menekan rugi bersih hingga >70% (-0.10% dan -0.17%). Sebaliknya, entri pada rezim bear (`ihsg_vs_ema20 <= 0`) terbukti sangat destruktif (-0.65% s.d. -0.67% per trade, PF 0.63–0.64).
   7. Mengeksekusi Eksperimen C (Durasi Dinamis) dan Eksperimen D (TP/SL Dinamis): mengonfirmasi horizon H=15 tetap paling tangguh dibanding pemotongan durasi ke H=5 atau H=10. Membuktikan bahwa pengetatan stop-loss (-1.5%) kontra-produktif karena terkena derau pasar (win rate jatuh ke 18.36%), dan target cepat (+4%) menurunkan ekspektansi return bersih meski win rate naik ke 31.96%.
   8. Mengevaluasi Kebijakan Sintesis Terpilih:
      - `LOW_PRICE` Top 3% (`combined_policy_top3_trend_tp6`): mencetak return bersih positif secara pooled (+0.08% per trade, pooled PF 1.04, continuous drawdown 9.59%, turnover 34.0x). Namun didorong oleh Fold 1 (+0.34%), sementara Fold 2 (-0.10%) dan Fold 3 (-0.16%) negatif.
      - `HIGHER_PRICE` Top 1% (`combined_policy_top1_trend_tp6`): mencetak return bersih positif secara pooled (+0.13% per trade, pooled PF 1.07, continuous drawdown 9.77%, turnover 59.2x). Namun didorong oleh Fold 2 (+0.44%), sementara Fold 1 (-0.01%) dan Fold 3 (-0.11%) negatif.
   9. Menetapkan keputusan tata kelola `DO_NOT_PROMOTE`: champion produksi tetap aktif dan tidak berubah. Mengekspor 11 artefak lengkap ke `artifacts/phase_11d/`, menyusun laporan formal `docs/15_phase_11d_dynamic_exit_policy_evaluation_report.md` berbasis universal template, memperbarui `audit_report.md`, serta menambahkan 10 pengujian unit pada `tests/unit/test_policy_evaluation.py` (total 490 tests passed 100%, ruff check clean 0 error).

60. Phase 11E — Riset Dynamic Conviction Sizing dan Volatility Trailing Protection (19 Oktober 2026)
   Masalah:
   1. Temuan Phase 11D membuktikan bahwa pengkondisian rezim bull (`ihsg_vs_ema20 > 0`) dan selektivitas ketat (Top 3% / Top 1%) berhasil mencapai profitabilitas nominal pooled (+0.08% dan +0.13%), namun rentan terhadap defisit pada forward folds yang belum terselesaikan. Perlu diselidiki apakah dynamic position sizing berbasis conviction rezim point-in-time dan volatility-based trailing protection dapat memperbaiki kinerja risk-adjusted portofolio tanpa bergantung pada profitabilitas pooled yang rapuh.
   2. Aturan trailing stop harus strictly kausal tanpa bias lookahead (stop hanya boleh mengetat saat watermark naik, tidak boleh melonggar, dan tidak boleh mengasumsikan urutan kejadian intraday dari data OHLC harian).
   3. Perlu pembuktian empiris apakah sizing dinamis dan trailing protection bersifat komplementer atau justru memiliki dampak yang saling tumpang tindih.
   Solusi:
   1. Mengembangkan engine riset Phase 11E `python/experiments/sizing_trailing_eval.py` dan runner CLI `scripts/run_sizing_trailing_evaluation.py` yang memodelkan sizing dinamis (alokasi modal dan pembatasan kapasitas) serta trailing stop volatilitas di bawah kontrak friksi 50 bps round-trip dan eksekusi Variant B (Market-On-Open).
   2. Mengevaluasi Eksperimen A (Dynamic Position Sizing): menguji aturan Fixed Control (1.0x), Conservative Binary (1.0x Bull, 0.0x Bear), Three-Tier Regime Sizing (1.0x Favorable, 0.5x Mixed, 0.0x Unfavorable), dan Smooth Conviction Sizing. Menemukan bahwa Three-Tier Sizing memangkas continuous drawdown dari 46.01% ke 14.74% pada LOW_PRICE dan 62.67% ke 24.23% pada HIGHER_PRICE, namun tidak memperbaiki ekspektansi return per-trade (tetap -0.14% s.d. -0.26%). Sizing terbukti sebagai tuas preservasi modal murni, bukan generator alfa.
   3. Mengevaluasi Eksperimen B (Volatility-Based Trailing Protection): menguji Breakeven Ratchets (+2.5%, +3.0%), ATR Trailing Stops (1.0x, 1.5x ATR), dan Stepped Profit Lock. Menemukan "Paradoks Pemotongan Payoff": trailing stop meningkatkan win rate secara dramatis (hingga 44.5% pada HIGHER_PRICE), namun justru merusak ekspektansi return bersih dan profit factor (PF turun dari 1.07 ke 0.88–0.93) karena retracement harian memicu stop prematur dan menukar pemenang penuh +6.0% menjadi scratch trade +0.5%.
   4. Mengevaluasi Eksperimen C (Combined Policy Matrix): membuktikan bahwa sizing dan trailing tidak memiliki sinergi aditif; kombinasi sizing dinamis saja dengan target barrier tetap (`comb_selective_sizing_alone`) mencetak drawdown portofolio terendah sepanjang sejarah proyek (6.34% pada LOW_PRICE dan 8.83% pada HIGHER_PRICE) dengan return bersih trade positif (+0.08% dan +0.14%).
   5. Menemukan persistensi defisit lintas fold (Folds 2 & 3 tetap negatif pada LOW_PRICE; Folds 1 & 3 tetap negatif pada HIGHER_PRICE). Sesuai tata kelola, menetapkan keputusan `DO_NOT_PROMOTE`: tidak ada kebijakan atau model yang dipromosikan ke produksi, champion tetap aktif dan utuh.
   6. Mengekspor 10 artefak lengkap ke `artifacts/phase_11e/`, menyusun laporan komprehensif `docs/16_phase_11e_sizing_trailing_protection_report.md` berbasis universal template (termasuk rekonsiliasi tabel Eksperimen B dan pelacakan posisi terbuka tersisa/remaining open positions), memperbarui `audit_report.md`, serta menambahkan 13 pengujian unit pada `tests/unit/test_sizing_trailing_evaluation.py` (total 503 tests passed 100%, ruff clean 0 error).
61. Phase 11F — Forward Paper Trading & Frozen Policy Validation (19 Oktober 2026)
   Masalah:
   1. Hasil riset historis Phase 11D dan 11E telah selesai membuktikan efektivitas dynamic position sizing tiga-tingkat dalam menekan drawdown portofolio (6.34% pada LOW_PRICE dan 8.83% pada HIGHER_PRICE), namun defisit lintas fold forward masih belum konsisten dan varian trailing stop terbukti memotong payoff kemenangan (+6.0% target terpangkas menjadi +0.5%). Diperlukan validasi prospektif forward paper-trading atas data pasar baru tanpa mempromosikan model atau mengubah champion produksi aktif.
   2. Kebijakan riset terpilih harus dibekukan (frozen) secara deterministik sebelum pengumpulan data baru, dan seluruh parameter kebijakan harus di-hash (SHA-256) agar tidak dapat dimodifikasi di tengah jalan.
   3. Model H=15 Variant B pada Phase 11C dievaluasi secara in-memory dalam loop walk-forward tanpa menyimpan file biner `.joblib` mandiri ke `models/registry/`. Diperlukan guard fail-closed yang ketat agar sistem tidak secara diam-diam beralih (fallback) menggunakan model champion produksi Variant A ($H=5$).
   Solusi:
   1. Mengembangkan engine forward paper-trading `python/experiments/paper_trading.py` dan runner CLI `scripts/run_forward_paper_trading.py` yang membekukan kebijakan riset primer:
      - `LOW_PRICE`: Top 3% harian (`pred_return_lgb` H=15 Regressor), filter tren IHSG (`ihsg_vs_ema20 > 0`), TP $+6.0\%$, SL $-2.0\%$, horizon 15 hari bursa, three-tier sizing ($1.0\times$ Favorable, $0.5\times$ Mixed, $0.0\times$ Unfavorable), maksimal 5 posisi, cap ekuitas 20%, tanpa trailing stop.
      - `HIGHER_PRICE`: Top 1% harian (`prob_lgb_full` H=15 Full Classifier), filter tren IHSG (`ihsg_vs_ema20 > 0`), TP $+6.0\%$, SL $-2.0\%$, horizon 15 hari bursa, three-tier sizing ($1.0\times / 0.5\times / 0.0\times$), maksimal 5 posisi, cap ekuitas 20%, tanpa trailing stop.
      - Menghasilkan hash konfigurasi kanonikal SHA-256: `2fa07ad5d2e10ad5c6b873338e648a5194b61bfbe84f02048cd6305e6c355bbd`.
   2. Mengimplementasikan scoring artifact audit dan guard fail-closed: mendeteksi ketidakhadiran file `.joblib` H=15 Variant B di `models/registry/`, melaporkan status `MISSING_SCORING_ARTIFACT`, dan secara tegas melarang fallback ke champion produksi (`lightgbm_classification_20261014_093522` atau `lightgbm_classification_20261014_093607`). Jika perintah penskoran prospektif `--date` dijalankan, sistem membunyikan `MissingScoringArtifactError` dan memblokir eksekusi.
   3. Memvalidasi engine melalui simulasi replay historis pada prediksi OOS Phase 11C (134.382 baris kandidat): mereplikasi secara presisi pembatalan gap pra-entri (gap down $\le -2\%$, gap up $\ge +6\%$, deviasi $> 5\%$, suspensi volume), friksi transaksi nominal 50 bps (15 bps komisi beli, 25 bps komisi jual, 5 bps slippage entri, 5 bps exit), lot size 100 lembar, pembatasan modal kas, precedensi konservatif SL sebelum TP pada bar ambigu, serta pelacakan MFE/MAE sepanjang umur posisi. Hasil replay mengonfirmasi penekanan drawdown portofolio kontinu hingga rekor terendah: **6.33%** pada `LOW_PRICE` (172 trade, net return $+0.08\%$) dan **8.59%** pada `HIGHER_PRICE` (309 trade, net return $+0.10\%$).
   4. Menetapkan keputusan tata kelola `READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)`: tidak ada kebijakan yang dideploy ke produksi, champion produksi tetap terlindungi dan utuh.
   5. Mengekspor 7 artefak terstruktur ke `artifacts/phase_11f/` (`frozen_policy_config.json`, `frozen_reference_benchmarks.csv`, `paper_trading_candidates.csv`, `paper_trading_decisions.csv`, `paper_trading_trades.csv`, `paper_trading_daily_equity.csv`, dan `paper_trading_operational_status.json`).
   6. Menyusun laporan formal universal `docs/17_phase_11f_forward_paper_trading_report.md`, merekonsiliasi angka acuan benchmark Phase 11D pada `frozen_reference_benchmarks.csv`, mengimplementasikan penskoran model prospektif saat artefak tersedia, memperbarui `audit_report.md` ke Phase 11F dan indeks entri 9, serta menambahkan 21 pengujian unit mendalam pada `tests/unit/test_forward_paper_trading.py` (total 524 tests passed 100%, ruff clean 0 error).
62. Phase 11F.1 — Finalisasi Artefak Research Scoring dan Kesiapan Observasi Forward Paper-Trading (19 Oktober 2026)
   Masalah:
   1. Binary model H=15 Variant B yang dibutuhkan untuk penskoran prospektif forward paper-trading belum pernah diserialisasi ke disk selama evaluasi walk-forward Phase 11C, sehingga status audit operasional berstatus `BLOCKED_ON_SCORING_ARTIFACT`.
   2. Dibutuhkan wrapper penskoran inferensi yang secara ketat menegakkan urutan skema 30 fitur kanonikal (`FEATURE_SCHEMA_30`), menolak input yang memiliki kolom hilang/ekstra/tertukar, dan menerapkan imputasi median kausal dari data historis sebelum batas cutoff.
   3. Terdapat diskrepansi jumlah trade pada ringkasan replay historis Phase 11F (309 trade pada `HIGHER_PRICE`) dibandingkan angka acuan Phase 11E/11D (298–301 trade) yang perlu direkonsiliasi secara matematis.
   Solusi:
   1. Mengembangkan script pelatihan mandiri `scripts/train_phase11f_research_models.py` yang merekonstruksi dan melatih ulang estimator H=15 Variant B (100 estimators, learning rate 0.05, max depth 5, num leaves 31, min child samples 20, seed 42) dengan cutoff eksplisit `2026-09-25` (menjamin seluruh horizon 15 hari bursa hingga `2026-10-16` telah teramati penuh) pada data valid:
      - `LOW_PRICE`: Regressor return bersih kontinu (41.848 baris valid dari 45.232 baris, mean return -0.63%, SHA-256: `84170b518a658e75dc481b8b445f0925e9811aa857dd0c94ebaa1ac65ed127f8`).
      - `HIGHER_PRICE`: Classifier probabilitas penuh (131.110 baris valid dari 136.118 baris, 31.400 positif / prevalensi 23.95%, SHA-256: `3192aa5c68d00052707dd31a271e639f9d30e28cda7407bbc9bdd45e054953bc`).
      - Menyimpan biner model ke folder riset terisolasi `artifacts/phase_11f/research_models/` (bukan di `models/registry/`) beserta metadata `research_model_metadata.json`.
   2. Mengimplementasikan wrapper model `ResearchRegressorModel` dan `ResearchClassifierModel` pada `python/models/research_scoring.py` yang memvalidasi kolom DataFrame secara ketat terhadap `FEATURE_SCHEMA_30`, menolak kolom yang hilang/berlebih/tertukar via `ValueError`, serta menerapkan imputasi median kausal berbasis data latih.
   3. Memperbarui `RESEARCH_SCORING_ARTIFACTS` pada `python/experiments/paper_trading.py`, menambahkan deduplikasi data kandidat dan keputusan, mengunci hash konfigurasi kebijakan kanonikal baru SHA-256 (`8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`) pada `artifacts/phase_11f/frozen_policy_config.json`, dan mentransisikan status audit operasional menjadi `READY_FOR_OBSERVATION`.
   4. Merekonsiliasi diskrepansi jumlah trade historis: simulasi Phase 11E mempartisi pengujian ke dalam 3 fold terpisah yang melikuidasi posisi di batas fold (menyisakan 5 posisi terbuka di akhir Fold 3), sedangkan Phase 11F menjalankan replay timeline kontinu tanpa pembersihan artifisial, memungkinkan 11 posisi perbatasan (5 posisi terbuka batas fold + 6 carryover lintas fold) selesai hingga batas terminal (298 + 11 = 309 trade).
   5. Menyusun jadwal operasional 3 bulan (scoring harian pukul 16:15 WIB dan audit mingguan), mengekspor laporan formal `docs/18_phase_11f_research_scoring_and_observation_readiness_report.md` berbasis universal template, memperbarui `audit_report.md` (entri 10), serta menambahkan 17 unit test integritas pada `tests/unit/test_research_scoring_integrity.py` (total 541 tests passed 100%: 509 unit, 32 integration; ruff clean 0 error).

63. Phase 11F.2 — Rekonsiliasi Jalur Artefak Riset, Hash Kebijakan, dan Kesiapan Operasional (19 Oktober 2026)
   Masalah:
   1. Terdapat inkonsistensi semantik status operasional: status `READY_FOR_OBSERVATION` belum membedakan antara kesiapan artefak biner model dengan otorisasi aktif pengguna untuk memulai observasi prospektif 3 bulan, sehingga memicu risiko eksekusi scoring sebelum persetujuan resmi.
   2. Perlu verifikasi ketat jalur artefak riset (`artifacts/phase_11f/research_models/`), perhitungan ulang hash runtime bundle terhadap file konfigurasi kanonikal (`8c102c4423f442099cf6a9b5471323ac22906ad68e1199c5587874028a862d71`), serta pengujian smoke prediktif untuk memastikan nilai skor selalu berhingga.
   3. Metadata batas cutoff (cutoff metadata) belum secara eksplisit memisahkan tanggal cutoff keputusan pelatihan (`2026-09-25`), tanggal bar harga terakhir untuk penetapan label forward (`2026-10-16`), dan tanggal awal observasi prospektif (`2026-10-19`) dengan pembuktian matematis ketiadaan kebocoran data (zero data leakage).
   Solusi:
   1. Memisahkan 4 status daur hidup secara eksplisit pada `python/experiments/paper_trading.py`: `BLOCKED_ON_SCORING_ARTIFACT`, `SCORING_ARTIFACTS_READY`, `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`, dan `OBSERVATION_ACTIVE`.
   2. Mengimplementasikan eksepsi `UserApprovalRequiredError` dan flag CLI `--user-approved` pada `scripts/run_forward_paper_trading.py`. Eksekusi penskoran prospektif `--date` tanpa flag `--user-approved` secara ketat diblokir (exit code 1 dengan pesan panduan yang jelas).
   3. Mengembangkan metode `load(cls, path)` pada `python/models/research_scoring.py` untuk deserialisasi bertipe ketat, serta memperkaya `audit_scoring_artifacts()` untuk memverifikasi SHA-256 terhadap `research_model_metadata.json`, memuat via `.load()`, dan menjalankan uji inferensi 1 sampel fitur `FEATURE_SCHEMA_30` (memvalidasi nilai finite tanpa NaN/Inf).
   4. Mengklarifikasi metadata cutoff dan pembuktian finalitas data pada `artifacts/phase_11f/paper_trading_operational_status.json`: membuktikan seluruh horizon 15 hari bursa untuk sampel pelatihan <= 2026-09-25 telah jatuh tempo per 2026-10-16, menjamin nol kebocoran prospektif.
   5. Menambahkan 7 unit test pada `tests/unit/test_research_scoring_integrity.py` (memvalidasi kesesuaian hash bundle runtime vs JSON, blokir saat artefak hilang, blokir saat hash tidak cocok, status pending approval, status active observation, penolakan saat tanpa approval, dan keberhasilan eksekusi saat approved). Total test suite mencapai 548 passed (516 unit, 32 integration; ruff clean 0 error).
   6. Memperbarui laporan formal universal `docs/18_phase_11f_research_scoring_and_observation_readiness_report.md`, `audit_report.md` (entri 10 dan status operasional), dan `walkthrough.md`.

64. Phase 11F.3 — Penyelesaian Daur Hidup Eksekusi Paper Trading Prospektif & State Persistence (20 Oktober 2026)
   Masalah:
   1. Pada implementasi Phase 11F.1/11F.2 sebelumnya, `PaperDecision.execution_date` disetel ke tanggal keputusan yang sama ($t$) dan alur `step_prospective_date()` hanya melakukan penskoran kandidat serta penulisan file CSV keputusan tanpa memproses eksekusi order tertunda, manajemen posisi terbuka, evaluasi exit TP/SL/expiry, kalkulasi PnL terealisasi, maupun valuasi ekuitas mark-to-market.
   2. Status portofolio dan posisi perdagangan bersifat mutable dan tidak boleh hanya mengandalkan file CSV sebagai satu-satunya penyimpan data; order tertunda, posisi terbuka, riwayat order, dan time series ekuitas harus persisten secara aman dan atomik di antara pemanggilan proses CLI yang terpisah.
   3. Pemanggilan ulang (rerun) pada sesi tanggal yang sama berisiko menduplikasi order, posisi, trade, atau merusak saldo kas portofolio (perlu jaminan idempotensi mutlak).
   4. Perintah status operasional (`--status`) sebelumnya hanya melaporkan kesiapan artefak biner dan belum menampilkan metrik daur hidup observasi prospektif secara nyata.
   Solusi:
   1. Memperbaiki penetapan tanggal eksekusi: mengimplementasikan metode `get_next_trading_date()` yang mencari tanggal bursa aktif berikutnya ($t+1$) dari bar database (atau fallback hari kerja Senin–Jumat), sehingga `PaperDecision.execution_date` selalu terjadwal di masa depan dan tidak pernah sama dengan tanggal keputusan $t$.
   2. Menyelesaikan daur hidup harian prospektif lengkap pada `PaperTradingEngine.step_prospective_date()`:
      - Memproses order tertunda dari sesi sebelumnya pada Open sesi $t+1$ dengan validasi gap pre-entry (gap down $\le -2\%$, gap up $\ge +6\%$, deviasi $> 5\%$, volume $\le 0$).
      - Menerapkan batasan kapasitas portofolio (maksimal 5 posisi terbuka konkuren, penolakan ticker duplikat), pembatasan modal 20% ekuitas, convicton sizing tiga-tingkat (1.0x, 0.5x, 0.0x), dan pembulatan round-lot 100 lembar (aturan IDX).
      - Menghitung friksi transaksi nominal 50 bps round-trip secara konsisten (15 bps komisi beli, 25 bps komisi jual, 5 bps slippage masuk, 5 bps slippage keluar).
      - Memperbarui posisi terbuka terhadap OHLC sesi harian: evaluasi TP $+6\%$, SL $-2\%$, preseden konservatif pada candle ambigu (SL mendahului TP), dan batas kadaluarsa 15 hari bursa (exit pada Close).
      - Melakukan kalkulasi valuasi ekuitas mark-to-market (MTM), ekuitas puncak (peak equity), dan continuous drawdown portofolio pada akhir hari (EOD).
   3. Mengembangkan manajemen state persisten aman `paper_trading_state.json` via metode `load_state()`, `save_state()`, dan `reset_state()` dengan mekanisme penulisan atomik (temporary file replace). Menjamin idempotensi: jika tanggal sesi telah diproses (`processed_dates`), sistem langsung mengembalikan status `ALREADY_PROCESSED` tanpa mutasi saldo kas maupun duplikasi rekaman.
   4. Memperbarui pelaporan status operasional `generate_operational_status()` dan CLI `scripts/run_forward_paper_trading.py --status`: menyajikan rincian lengkap order tertunda, posisi terbuka aktif, trade selesai, saldo kas, MTM equity, PnL terealisasi/belum terealisasi, drawdown, dan ringkasan order yang tidak terisi/terinvaliasi.
   5. Mempertahankan gerbang otorisasi pengguna (`UserApprovalRequiredError`): status operasional hanya bertransisi menjadi `OBSERVATION_ACTIVE` setelah adanya observasi prospektif yang disetujui (`user_approved=True`) dan berhasil dieksekusi. Tidak ada observasi prospektif yang dimulai selama pengujian ini.
   6. Menambahkan 14 unit dan regression test komprehensif pada `tests/unit/test_prospective_lifecycle.py`. Total test suite meningkat menjadi 562 passed (530 unit, 32 integration, 0 failure; ruff clean 0 error).
   7. Menyusun laporan penyelesaian formal `docs/19_phase_11f_prospective_lifecycle_completion_report.md` berbasis universal template, memperbarui `audit_report.md` (entri 11), dan memperbarui `walkthrough.md`.

65. Phase 11F.4 — Koreksi Kesiapan Fail-Closed Daur Hidup Paper Trading Prospektif (20 Oktober 2026)
   Masalah:
   1. Otorisasi pengguna sebelumnya belum didecoupling secara persisten dari aktivasi observasi; eksekusi `--status --user-approved` sebelumnya dapat memicu status aktif semu tanpa adanya run penskoran prospektif yang benar-benar berhasil dan tercatat.
   2. Belum ada proteksi terhadap eksekusi observasi historis atau tanggal lampau (backdated) di bawah atau sama dengan batas data pelatihan (`approval_data_cutoff`), lompatan sesi bursa yang terlewat (missed sessions), maupun eksekusi order tertunda yang basi (stale orders) pada sesi open berikutnya. Tanggal prospektif pertama juga masih di-hardcode ke string 2026-10-19.
   3. Pengecekan kualitas data belum fail-closed secara independen untuk ketiadaan bar harga harian saat fitur ada, ketiadaan baris fitur saat bar harga ada, diskrepansi tanggal, kolom fitur hilang, ticker coverage bernilai 0, atau nilai fitur infinite (Inf).
   4. Status persisten (`paper_trading_state.json`) jika mengalami korupsi atau ketidaksesuaian hash kebijakan sebelumnya berisiko tertimpa secara diam-diam oleh state default; field otorisasi belum divalidasi ketat saat loading state skema lama.
   Solusi:
   1. Mendekopel otorisasi pengguna ke dalam state persisten (`user_approved`, `approval_timestamp`, `approval_data_cutoff`), membuat perintah CLI baru `--approve-observation`, menambahkan status eksplisit `STATUS_APPROVED_PENDING_FIRST_OBSERVATION`, dan memastikan status `OBSERVATION_ACTIVE` hanya aktif setelah run prospektif pertama yang sah berhasil dan tersimpan secara permanen di disk dengan otorisasi persisten.
   2. Menegakkan dynamic data cutoff berbasis `MAX(date)` dari `daily_bars` (menolak tanggal <= cutoff dengan `InvalidProspectiveDateError`), menegakkan monotonic progression (menolak tanggal lebih awal dari `last_d`), mendeteksi gap sesi bursa pertama maupun lanjutan yang terlewat serta order basi yang terlewat dengan `MissedSessionError`, serta menghitung tanggal prospektif pertama secara dinamis via `get_first_prospective_date()`.
   3. Mengimplementasikan data quality guards ketat pada `step_prospective_date()` yang memicu `DataQualityError` saat bar harga hilang, fitur hilang, tanggal tidak cocok, kolom skema hilang, zero joined tickers, atau terdeteksi nilai infinite (Inf).
   4. Memperketat `load_state()` untuk memvalidasi versi skema 1.1, seluruh field wajib termasuk approval metadata, saldo kas non-negatif, dan integritas hash kebijakan kanonikal (`StateIntegrityError`), mencegah penimpaan diam-diam, menambahkan status `STATUS_BLOCKED_ON_STATE_CORRUPTION`, serta menyediakan mekanisme migrasi aman CLI `--migrate-state` / `migrate_state(backup=True)` dengan salinan backup `.bak` bertimestamp.
   5. Menambahkan 23 unit dan regression test komprehensif pada `tests/unit/test_fail_closed_readiness.py` (total 83 paper trading tests passed; 586 total suite tests passed 100%; ruff clean 0 error). Menyusun laporan universal `docs/20_phase_11f_final_readiness_report.md` dan memperbarui `audit_report.md` (entri 12).


66. Phase 11F.4 — Patch Batas Efektif Waktu Otorisasi untuk Observasi Prospektif (21 Oktober 2026)
   Masalah:
   1. Tanggal mulai observasi prospektif sebelumnya berisiko menerima sesi keputusan lampau (misal 2026-10-19) jika bar baru di-ingest setelah tanggal otorisasi (2026-10-20), karena sistem hanya melacak `approval_data_cutoff` (2026-10-16) dan belum menegakkan batas efektif waktu persetujuan manusia (`effective_observation_cutoff`).
   2. Rekomendasi tanggal prospektif pertama sebelumnya sempat merekomendasikan tanggal lampau (2026-10-19) secara statis saat sistem belum disetujui, alih-alih menghitungnya secara dinamis dan gagal tertutup (`PENDING_USER_APPROVAL`).
   3. Metode `get_first_prospective_date()` menelan eksepsi secara diam-diam (`except Exception: pass`), sehingga korupsi state berisiko tidak terdeteksi pada resolusi tanggal prospektif.
   Solusi:
   1. Menambahkan field `effective_observation_cutoff` pada skema state 1.1 di `python/experiments/paper_trading.py`. Pada `approve_observation()`, batas efektif dihitung secara otomatis sebagai `max(data_cutoff, approval_date)` dalam zona waktu WIB (`Asia/Jakarta`).
   2. Menegakkan aturan konsisten pada engine dan CLI `scripts/run_forward_paper_trading.py`: tanggal sesi prospektif harus > `approval_data_cutoff` DAN > `effective_observation_cutoff`. Sesi yang terjadi sebelum atau pada hari otorisasi secara ketat ditolak (`InvalidProspectiveDateError`).
   3. Memperbarui `get_first_prospective_date()`: mengembalikan `None` saat belum disetujui (`user_approved=False`), sehingga status operasional menampilkan `PENDING_USER_APPROVAL` tanpa menebak tanggal historis. Saat telah disetujui, tanggal dihitung secara dinamis via `get_next_trading_date(effective_cutoff)`.
   4. Mengeliminasi penekanan eksepsi pada `get_first_prospective_date()`, mempropagasi `StateIntegrityError` secara langsung sehingga status operasional secara benar bertransisi ke `BLOCKED_ON_STATE_CORRUPTION`.
   5. Menambahkan 5 regression test khusus pada `tests/unit/test_fail_closed_readiness.py` untuk menguji kelima skenario target (penolakan sesi pra-otorisasi saat bar di-ingest belakangan, penerimaan sesi sah pasca-otorisasi, penolakan tanggal basi via flag approved, propagasi error pada state korup, dan nilai None/pending pada unapproved state). Total 28 fail-closed tests lulus (100%), total suite paper trading 88 passed, total repository suite 591 passed (100%), dan linter 100% clean (0 error).
   6. Menyusun ulang laporan universal `docs/20_phase_11f_final_readiness_report.md`, memperbarui `audit_report.md` (entri 12 dan status operasional), dan memperbarui `walkthrough.md`.
67. Offline Challenger Retraining — Fresh Historical Data & Controlled Evaluation (21 Oktober 2026)
   Masalah / Konteks:
   1. Perlunya mengevaluasi apakah pelatihan ulang model classifier challenger riset menggunakan data historis terbaru yang telah sepenuhnya matang (cutoff keputusan 2026-09-25, bar hingga 2026-10-16) serta konfigurasi ablasi fitur yang telah diidentifikasi sebelumnya mampu memberikan prediksi out-of-sample yang lebih reliabel dibandingkan konfigurasi champion produksi saat ini.
   2. Perlunya audit ketat terhadap batas kedewasaan data target Variant B H=15: tanggal keputusan setelah 2026-09-25 memiliki forward bar < 15 sehingga belum matang dan tidak boleh dimasukkan agar tidak menimbulkan bias survivorship/right-censoring.
   3. Perlunya isolasi mutlak dari artefak frozen Phase 11F dan model champion produksi di `models/registry/`.
   Solusi / Hasil:
   1. Mengembangkan engine pelatihan ulang dan evaluasi terkontrol `python/experiments/challenger_retraining.py`, CLI runner `scripts/run_offline_challenger_retraining.py`, dan audit inspeksi dataset `scripts/inspect_dataset_splits.py`.
   2. Menjalankan evaluasi walk-forward 3-split expanding dengan purge window ketat 15 hari bursa untuk Candidate A (Full LightGBM 30 fitur), Candidate B (Ablasi fitur: minus trend untuk LOW_PRICE, minus market_regime untuk HIGHER_PRICE), Candidate C (Regularized Logistic Regression), Reference Baseline 1 (Prevalence Baseline), dan Reference Baseline 2 (Production Champion).
   3. Menjalankan simulasi perdagangan discrete-event terkontrol di bawah friksi transaksi nominal IDX 50 bps round-trip (15 bps komisi beli, 25 bps komisi jual, 5 bps slippage masuk, 5 bps slippage keluar), batas modal 20%, ukuran lot 100 lembar, dan penolakan gap pra-entry.
   4. Menemukan hasil empiris: seluruh konfigurasi kandidat yang dilatih ulang menghasilkan net return negatif (-0.35% s.d. -0.68% per trade) dan pooled profit factor < 1.0 (0.63 s.d. 0.79) di bawah friksi 50 bps. Tidak ada kandidat yang menembus batas profitabilitas atau mengungguli champion produksi secara out-of-sample.
   5. Melatih dan mem-persistensi 6 artefak biner riset (.joblib) beserta hash SHA-256 dan metadata lengkap pada `artifacts/offline_challengers/run_20261021_retraining/` tanpa mengubah model champion atau Phase 11F.
   6. Menambahkan 6 unit test komprehensif pada `tests/unit/test_challenger_retraining.py`. Total test suite meningkat menjadi 597 passed (565 unit, 32 integration, 0 failure; ruff clean 0 error).
   7. Menyusun laporan formal `docs/21_offline_challenger_retraining_report.md` berbasis universal template, memperbarui `audit_report.md` (entri 13), dan memperbarui `walkthrough.md`. Keputusan final: `DO_NOT_PROMOTE`.

68. Phase 11F — Otorisasi Resmi Pengguna untuk Observasi Paper Trading Prospektif (21 Oktober 2026)
   Masalah / Konteks:
   1. Observasi paper trading forward Phase 11F sebelumnya berada dalam status `READY_FOR_OBSERVATION_PENDING_USER_APPROVAL`, menunggu persetujuan eksplisit dari operator sebelum sesi bursa forward dapat diproses.
   Solusi / Hasil:
   1. Menjalankan perintah otorisasi operator resmi: `python -m scripts.run_forward_paper_trading --approve-observation`.
   2. Status persisten `artifacts/phase_11f/paper_trading_state.json` berhasil diperbarui: `user_approved: True`, `approval_timestamp: '2026-10-21T07:19:05.601655+00:00'`, `approval_data_cutoff: '2026-10-16'`, dan `effective_observation_cutoff: '2026-10-21'`.
   3. Status operasional bertransisi menjadi `APPROVED_PENDING_FIRST_OBSERVATION`. Belum ada transaksi yang dieksekusi (0 trades, 0 open positions, saldo kas utuh 100jt IDR). Observasi akan aktif saat sesi data bursa setelah 2026-10-21 di-ingest dan diproses.

69. Phase 11G — Otomasi & Orkestrasi Pipeline Harian Market Data ke Paper Trading (21 Oktober 2026)
   Masalah:
   1. Script harian sebelumnya terfragmentasi (`scripts/ingest_daily.py`, `scripts/build_features.py`, `scripts/run_forward_paper_trading.py`) tanpa satu titik orkestrasi terpusat (single entry point) yang mengelola transisi data end-to-end dari Stage A s.d. Stage F.
   2. Script ingest dan build features memiliki fallback sintetik/mock secara default jika provider gagal atau data kosong, berisiko mengontaminasi database operasional dengan data tiruan.
   3. Perhitungan fitur sebelumnya default `save_db=False`, sehingga fitur baru berisiko hanya berada di memori tanpa tersimpan ke tabel `features_daily`.
   4. Evaluasi `np.isinf` pada `PaperTradingEngine` memicu `TypeError` jika matriks fitur mengandung kolom bertipe `object` dengan nilai `None`.
   5. Belum adanya penjadwalan otomatis di tingkat sistem operasi (Windows Task Scheduler) untuk memicu pipeline pada akhir jam bursa (Senin–Jumat 16:30 WIB).
   Solusi:
   1. Mengembangkan pipeline orchestrator `python/pipeline/daily_pipeline.py` (`DailyPipeline` & `PipelineRunReport`) dan CLI `scripts/run_daily_pipeline.py` yang mengoordinasikan 6 stage operasional secara ketat dan fail-closed:
      - Stage A: Ingest market data harian.
      - Stage B: Ingestion Validation Gate (cakupan ticker >= ambang batas).
      - Stage C: Feature Generation & DB Persistence (menyimpan ke `features_daily` dan memvalidasi hitungan baris DB).
      - Stage D: Feature Readiness Gate (verifikasi skema 30 fitur, kecocokan tanggal, dan ketiadaan NaN/Inf).
      - Stage E: Paper Trading Lifecycle (eksekusi order tertunda, evaluasi barrier, penskoran prospektif).
      - Stage F: Pelaporan operasional komprehensif ke file JSON di `reports/daily_runs/`.
   2. Menambahkan parameter `allow_mock_fallback: bool` pada `scripts/ingest_daily.py` dan `scripts/build_features.py`. Pada pipeline operasional, nilai disetel secara eksplisit ke `False`, sehingga kegagalan provider memicu error dan menghentikan pipeline tanpa fallback tiruan.
   3. Memperbaiki sanitasi tipe numerik pada `python/experiments/paper_trading.py` sebelum pemanggilan `np.isinf` menggunakan `apply(pd.to_numeric, errors="coerce")`.
   4. Mengembangkan otomasi Windows Task Scheduler via skrip PowerShell:
      - `scripts/run_scheduled_pipeline.ps1`: wrapper operasional dengan penanganan concurrency lockfile (`.pipeline.lock`), deteksi virtualenv otomatis, logging permanen UTF-8 di `logs/`, dan propagasi exit code.
      - `scripts/register_daily_scheduler.ps1`: mendaftarkan task `\IDX_Stock_Signal_Daily_Pipeline` untuk berjalan setiap hari kerja (Senin–Jumat) pukul 16:30 WIB. Berhasil didaftarkan dan berstatus `Ready`.
      - `scripts/unregister_daily_scheduler.ps1`: skrip pelepasan task secara bersih.
   5. Menambahkan target `daily-pipeline` pada `Makefile`.
   6. Menambahkan 13 unit dan integration test pada `tests/unit/test_daily_pipeline.py` yang memvalidasi ke-8 skenario kegagalan dan keberhasilan operasional (provider failure fail-closed, mock rejection, partial coverage, DB persistence verification, DB reuse, idempotensi tanpa duplikasi, deteksi data basi, dan immutabilitas hash artefak).
   7. Menyusun laporan audit universal `docs/22_daily_pipeline_automation_validation_report.md` dan memperbarui `audit_report.md` (entri 14).

70. Phase 11G — Review Kritis, Perbaikan Bug Pipeline Harian, & Rekonsiliasi Metrik Operasional (21 Oktober 2026)
   Masalah:
   1. `DailyBarRepository` tidak memiliki method `get_ingestion_runs(limit)`, memicu `AttributeError` di Stage A saat penarikan data nyata dijalankan.
   2. Skrip wrapper `scripts/run_scheduled_pipeline.ps1` memicu `NativeCommandError` PowerShell saat yfinance mencetak pesan ke stderr, memutus pipeline di batch tengah dan meninggalkan data parsial.
   3. Skrip pendaftaran Task Scheduler `register_daily_scheduler.ps1` belum menyertakan pengaturan `-StartWhenAvailable`, sehingga eksekusi berisiko terlewat jika komputer mati pada pukul 16:30.
   4. Tipe data string vs objek `datetime.date` pada `processed_dates` di Stage B menyebabkan perbandingan selalu bernilai False, sehingga skip sesi yang sudah diproses gagal terpicu.
   5. Urutan pengecekan ambang batas cakupan ticker dan proxy benchmark di Stage B terbalik, menyebabkan error benchmark muncul mendahului error cakupan ticker.
   6. Laporan operasional `PipelineRunReport` belum memuat metrik audit lengkap (14 metrik: schema hash, model hashes, policy bundle hash, candidate/decision count, fill/exit count, position count, pnl, drawdown, equity).
   7. Stage D belum memverifikasi kecocokan ticker fitur terhadap `daily_bars`, belum memvalidasi non-null kolom benchmark, dan meloloskan kondisi ketika kandidat dengan histori lengkap berjumlah 0.
   Solusi:
   1. Mengimplementasikan `get_ingestion_runs(limit)` pada `DailyBarRepository` di `python/data/repository.py`.
   2. Menyetel `$ErrorActionPreference = "Continue"` secara lokal selama pemanggilan `python.exe` pada `scripts/run_scheduled_pipeline.ps1` dan meneruskan argumen CLI `@args`.
   3. Menambahkan `-StartWhenAvailable` pada `scripts/register_daily_scheduler.ps1` dan mendaftarkan ulang task `\IDX_Stock_Signal_Daily_Pipeline` (status: `Ready`, `StartWhenAvailable: True`).
   4. Menormalisasi perbandingan `str(session_d_check) in processed_dates` pada Stage B sehingga aman dari perbedaan tipe.
   5. Mengevaluasi ambang batas cakupan ticker terlebih dahulu sebelum evaluasi ketersediaan proxy benchmark di Stage B.
   6. Melengkapi seluruh 14 metrik operasional pada `PipelineRunReport` dan ringkasan eksekusi CLI `scripts/run_daily_pipeline.py`.
   7. Menambahkan validasi silang ticker fitur terhadap bar harga di `daily_bars`, validasi kelengkapan kolom benchmark, dan verifikasi `complete_history_candidates > 0` di Stage D.
   8. Menambahkan 6 unit test baru pada `tests/unit/test_daily_pipeline.py` (total 19 unit test). Total test suite repositori menjadi 616 passed (100%), ruff clean 0 error.

71. Phase 11G — Final Repository and Runtime Reconciliation (21 Oktober 2026)
   Masalah:
   1. Target `daily-pipeline` pada Makefile diklaim telah ditambahkan dan diuji pada laporan validasi, namun lingkungan host Windows belum memiliki binary `make.exe` dalam sistem PATH, sehingga eksekusi langsung via `make` memicu error CommandNotFoundException.
   2. Terdapat inkonsistensi ambang batas cakupan ticker minimum (minimum ticker coverage threshold) antara laporan yang menyebut 80% (0.80) dengan default parameter pada kode pipeline dan CLI yang sebelumnya masih 70% (0.70).
   3. Terdapat diskrepansi hitungan test di laporan validasi (tabel Ringkasan Implementasi masih mencatat 13 unit test, sementara realisasi adalah 19 unit test dan belum ada unit test untuk mengunci ambang batas 80%).
   4. Status operasional pada header `audit_report.md` masih mendeskripsikan Phase 11F.4 dan belum ditautkan secara langsung ke laporan rinci Phase 11G.
   5. Registrasi task scheduler Windows `\IDX_Stock_Signal_Daily_Pipeline` dan riwayat eksekusinya memerlukan verifikasi runtime nyata pada mesin target.
   6. Database lokal terbaru (194MB dengan data bar hingga 21 Oktober 2026) dan kode aplikasi perlu disinkronkan ke AWS S3 dan AWS Lambda.
   Solusi:
   1. Merekonsiliasi klaim Makefile: memastikan target `daily-pipeline` terdefinisi bersih pada `Makefile` (`$(VENV_PYTHON) -m scripts.run_daily_pipeline`) dan memvalidasi sintaks serta resep eksekusi via Python (`.venv\Scripts\python.exe -m scripts.run_daily_pipeline --help`), serta mendokumentasikan bahwa pada Windows native eksekusi dilakukan langsung via PowerShell/Python.
   2. Menyelaraskan ambang batas cakupan ticker minimum menjadi 80% (0.80) secara konsisten di `python/pipeline/daily_pipeline.py` (`min_ticker_coverage: float = 0.80`), `scripts/run_daily_pipeline.py` (`default=0.80`), dan menambahkan unit test pengunci ambang batas pada `tests/unit/test_daily_pipeline.py`.
   3. Mengoreksi dan merekonsiliasi seluruh hitungan unit test pada `docs/22_daily_pipeline_automation_validation_report.md` berdasarkan output aktual pytest: 20 passed pada modul daily pipeline, 585 unit tests, 32 integration tests, dengan total 617/617 passed (100% pass rate).
   4. Memperbarui `audit_report.md` pada bagian "Current Operational State" ke Phase 11G, menambahkan link ke `docs/22_daily_pipeline_automation_validation_report.md`, dan merangkum hasil operasional terkini.
   5. Memverifikasi status runtime nyata Windows Task Scheduler `\IDX_Stock_Signal_Daily_Pipeline` via PowerShell: State `Ready`, Enabled `True`, StartWhenAvailable `True`, NextRunTime `10/22/2026 4:30:00 PM`, LastRunTime `10/21/2026 4:30:00 PM`, LastTaskResult `0` (Success).
   6. Melakukan sinkronisasi ke AWS: mengunggah database SQLite `datasets/stock_signals.db` (194,031,616 bytes, SHA256 terverifikasi) ke bucket S3 `idx-stock-signal-436095651956-data/database/stock_signals.db` dengan backup otomatis (`database/backups/stock_signals_20261021_110909.db`), serta memperbarui kode fungsi AWS Lambda (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) via `scripts/deploy_aws.py` di region `ap-southeast-3`.

Log Perubahan Tambahan (22 Oktober 2026)
72. Phase 11G — Penguncian Ambang Batas 80% Coverage Pipeline, Verifikasi Provider Market Data, dan Fitur Interactive Command Menu Telegram
   Masalah:
   1. Perlunya penguncian permanen dan pengujian regresi untuk ambang batas cakupan ticker minimum 80% (0.80) di Stage B pipeline harian, membuktikan bahwa cakupan <80% secara fail-closed memblokir downstream scoring (Stage C, D, E) sedangkan cakupan >= 80% meloloskan gate, serta mendukung CLI override.
   2. Perlunya verifikasi empiris penyedia data pasar (market data provider) di lingkungan runtime lokal dan log eksekusi terbaru (`yfinance`), penegasan larangan penggunaan mock/sintetik pada mode operasional, serta koreksi terhadap klaim di laporan sebelumnya mengenai dukungan GoAPI (yang tidak didukung oleh implementasi ingestion publik `python/data/provider.py`).
   3. Bot Telegram belum memiliki fitur menu interaktif popup saat pengguna mengetik karakter `/` di kolom input pesan Telegram, sehingga pengguna harus mengingat atau mengetik manual seluruh perintah (`/start`, `/help`, `/daily`, `/signals`, `/status`, `/portfolio`, `/pipeline`, dll).
   4. Perlunya rekonsiliasi riwayat hitungan pengujian (616 vs 617 vs 625 test) antara `audit_report.md`, `summary.md`, dan `docs/22_daily_pipeline_automation_validation_report.md`.
   Solusi:
   1. Menambahkan 3 unit regression tests pada `tests/unit/test_daily_pipeline.py`:
      - `test_ticker_coverage_below_80_percent_blocks_downstream_scoring`: membuktikan cakupan 70% menggugurkan Stage B dan memblokir Stage C/D/E.
      - `test_ticker_coverage_meeting_80_percent_passes_gate`: membuktikan cakupan 80% meloloskan Stage B.
      - `test_ticker_coverage_cli_override`: memvalidasi override CLI `--min-coverage 0.70` (lulus) dan `--min-coverage 0.90` (gagal).
      Total test modul daily pipeline meningkat dari 20 menjadi 23 test (23/23 passed).
   2. Memverifikasi `.env` (`MARKET_DATA_PROVIDER=yfinance`), `python/config/settings.py`, serta log riil terbaru `logs/daily_pipeline_20261021_163002.log` dan `artifacts/pipeline_runs/latest_pipeline_run.json` (terkonfirmasi 192/210 ticker, cakupan 91.4% via `yfinance`). Mengoreksi `python/data/provider.py` bahwa provider yang didukung hanya `yfinance`, `local_csv`, dan mock (`goapi` memicu `ValueError: Unsupported market data provider: goapi`). Menghapus seluruh klaim dukungan GoAPI dari `docs/22_daily_pipeline_automation_validation_report.md` dan menegaskan larangan mock (`allow_mock_fallback=False`).
   3. Mengembangkan fitur interaktif Telegram Bot Commands via Bot API `setMyCommands`:
      - Membuat `services/telegram/commands.py` yang mendefinisikan 14 perintah bawaan (`DEFAULT_BOT_COMMANDS`), fungsi validasi batas Bot API (`validate_bot_commands`), dan generator format BotFather (`format_commands_for_botfather`).
      - Menambahkan method `set_my_commands()`, `get_my_commands()`, dan `delete_my_commands()` pada `TelegramClient` di `services/telegram/client.py`.
      - Mengintegrasikan handler perintah `/status`, `/pipeline`, dan `/portfolio` pada `TelegramBotDispatcher` di `services/telegram/bot.py`.
      - Membuat CLI tool `scripts/set_telegram_commands.py` untuk pendaftaran otomatis maupun ekspor BotFather.
      - Mengintegrasikan registrasi otomatis perintah bot pada skrip deployment AWS `scripts/deploy_aws.py`.
      - Menambahkan 5 unit tests komprehensif pada `tests/unit/test_telegram.py` (total 33 unit tests telegram passed).
   4. Merekonsiliasi hitungan test: 616 (state pada entri 70), 617 (setelah penambahan test pengunci threshold pada entri 71), dan 625 (setelah penambahan 3 regression tests pipeline dan 5 bot command tests: 593 unit tests, 32 integration tests, 100% kelulusan, ruff 0 error).
73. Phase 11G — Perbaikan Direct Execution CLI set_telegram_commands, Penyelarasan Default Threshold pada Test Suite, dan Penambahan Routing '/' & '/menu'
   Masalah:
   1. Script `scripts/set_telegram_commands.py` mengalami `ModuleNotFoundError: No module named 'python'` ketika dieksekusi secara langsung (`python scripts/set_telegram_commands.py`) karena belum menyisipkan project root ke `sys.path`.
   2. Unit test `test_partial_ticker_coverage_blocks_scoring` pada `tests/unit/test_daily_pipeline.py` masih secara manual menggunakan parameter `min_ticker_coverage=0.50` alih-alih menguji default locked threshold `0.80`.
   3. Dispatcher bot Telegram (`TelegramBotDispatcher.dispatch`) merespons dengan pesan `Unknown command /` jika pengguna mengirimkan karakter `/` atau `/menu` langsung dalam pesan obrolan.
   Solusi:
   1. Menambahkan `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` pada `scripts/set_telegram_commands.py` sehingga dapat dieksekusi langsung tanpa error import (terverifikasi dengan `--dry-run` dan `--botfather`).
   2. Menghapus hardcode `0.50` pada `test_partial_ticker_coverage_blocks_scoring` dan meng-assert bahwa default threshold adalah `0.80` secara konsisten di seluruh pipeline dan test suite.
   3. Menambahkan routing `/` dan `/menu` ke `handle_help()` pada `TelegramBotDispatcher.dispatch`, menambahkan perintah `menu` ke `DEFAULT_BOT_COMMANDS`, serta menambahkan unit test pendukung pada `tests/unit/test_telegram.py`. Seluruh 625 test passed (100%), ruff clean 0 error.
74. AWS Runtime Verification — Daily Ingestion dan Telegram Signal Pipeline (22 Oktober 2026)
   Masalah:
   1. Perlunya verifikasi empiris apakah lingkungan AWS nyata saat ini menjalankan pipeline ingestion data harian dan pembuatan sinyal Telegram secara otomatis atau tidak, mengingat template SAM `infra/aws/template.yaml` dan handler `python/cloud/handlers.py` ada di repositori namun belum tentu aktif secara operasional.
   2. Perlunya pembuktian apakah eksekusi terjadwal Lambda di AWS benar-benar mengunduh DB, melakukan ingestion bar segar, menghitung fitur, menghasilkan sinyal baru, mengirim Telegram, dan mengunggah kembali DB ke S3.
   3. Perlunya audit mendalam terhadap perilaku fail-closed vs fail-open pada kode Lambda handler `python/cloud/handlers.py`.
   4. Perlunya penegasan perbedaan antara workflow pipeline harian AWS dengan forward paper trading lokal Phase 11F/11G.
   Solusi:
   1. Melakukan inspeksi read-only komprehensif pada AWS region `ap-southeast-3` (Account `436095651956` via `deployer`):
      - CloudFormation Stacks: 0 stack terdaftar (`describe_stacks()` = `[]`); infrastruktur dideploy secara imperatif via `scripts/deploy_aws.py`.
      - Lambda Functions: 3 fungsi staging terdaftar (`idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`) dengan ukuran paket zip 321 KB dan tanpa Lambda Layer (`Layers: []`).
      - EventBridge Rules: Rule `idx-daily-pipeline-schedule-staging` berstatus `ENABLED` dengan target `idx-daily-pipeline-staging` dan jadwal `cron(30 9 ? * MON-FRI *)` (16:30 WIB).
      - CloudWatch Logs: Fungsi terpicu otomatis setiap hari bursa pukul 09:30 UTC (16:30 WIB) dengan durasi ~18 detik dan memory 543 MB.
   2. Menelusuri alur eksekusi riil Lambda harian dari log CloudWatch dan artefak S3:
      - Lambda berhasil mengunduh DB SQLite dari S3 ke `/tmp/stock_signals.db`.
      - **Kegagalan Ingestion & ML:** Paket zip Lambda (321 KB) hanya berisi kode sumber dan tidak memuat third-party dependencies (`yfinance`, `pandas`, `numpy`, `scikit-learn`, `lightgbm`). Akibatnya, `run_ingest` dan `SignalEngine` memicu `ImportError` saat diimpor, sehingga `run_ingest` bernilai `None` dan `SignalEngine` bernilai `None`.
      - Handler secara fail-open melewati tahap ingestion (`Market data ingestion skipped: run_ingest not loaded in serverless package`) dan tahap signal generation (`SignalEngine skipped: ML dependencies not present in serverless package`).
      - **Critical Fail-Open Stale Replay:** Karena sinyal baru tidak terbentuk, handler mengeksekusi fallback query ke tabel `signals_daily` di SQLite, mengambil tanggal sinyal historis terakhir (`2026-10-16`, 10 sinyal), dan mengirimkan ulang sinyal usang tersebut ke Telegram setiap hari bursa (`SENT_85`, `SENT_86`, `SENT_87`), lalu mengunggah log eksekusi ke S3 dengan label `status: "SUCCESS"` dan `bars_ingested: 0`.
   3. Mengidentifikasi temuan fail-open kritis pada `python/cloud/handlers.py`:
      - Baris 306-309: kegagalan load `run_ingest` tidak menghentikan pipeline melainkan di-skip secara diam-diam.
      - Baris 360-361: kegagalan ekstraksi fitur hanya di-log sebagai warning dan eksekusi tetap berlanjut.
      - Baris 400-418: ketiadaan sinyal baru memicu fallback pengambilan sinyal usang dari database untuk disiarkan ke Telegram sebagai sinyal harian dengan status `SUCCESS`.
   4. Membedakan kedua workflow secara tegas:
      - Pipeline AWS Lambda (`idx-daily-pipeline-staging`) tidak menggunakan `DailyPipeline`, tidak menyentuh `artifacts/phase_11f/paper_trading_state.json`, tidak mengevaluasi model riset frozen Phase 11F, dan tidak menjalankan lifecycle paper trading.
      - Paper trading operasional Phase 11F/11G berjalan secara independen dan strictly fail-closed di lingkungan lokal melalui Windows Task Scheduler (`\IDX_Stock_Signal_Daily_Pipeline`).
   5. Mendokumentasikan seluruh bukti teknis pada `docs/23_aws_runtime_daily_pipeline_verification_report.md` dengan kesimpulan `AWS_AUTOMATION_FAILED`, memperbarui `audit_report.md` (Indeks Entri 15), dan merekomendasikan penonaktifan sementara EventBridge rule untuk mencegah spam siaran sinyal usang 2026-10-16.
