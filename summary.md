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
