# Walkthrough — Offline Challenger Retraining & Controlled Evaluation

## Sesi Kerja: 21 Oktober 2026

### Ringkasan Eksekutif
Telah diselesaikan evaluasi dan pelatihan ulang offline challenger classifier untuk BEI Dual-Mode Stock Signals menggunakan data historis yang sepenuhnya matang (`2026-09-25` cutoff, bar hingga `2026-10-16`) di bawah kontrak target riset Variant B H=15 (Next-Session Open MOO, TP +5%, SL -2%, friksi 50 bps). Hasil empiris menunjukkan bahwa meskipun model kandidat menunjukkan diferensiasi prediktif, seluruh konfigurasi menghasilkan return neto negatif (-0.35% s.d. -0.68%) di bawah friksi 50 bps, sehingga **tidak ada model yang dipromosikan (DO_NOT_PROMOTE)**. Champion produksi dan sistem Phase 11F tetap diisolasi dan tidak berubah.

---

### Task Breakdown & Perubahan File

#### 1. Audit Dataset & Data Maturity Cutoff
- **File:** `scripts/inspect_dataset_splits.py` (Baru, 185 baris)
- **Rincian Perubahan:**
  - Menginspeksi tabel SQLite `daily_bars` (244,021 bar, 2,654 tanggal, max `2026-10-16`), `features_daily` (186,702 baris, 900 tanggal, max `2026-10-16`), dan `labels_daily` (185,515 baris, max `2026-10-13`).
  - Menetapkan batas matematis kedewasaan data: untuk target Variant B H=15 dengan entry Open $t+1$, tanggal keputusan terakhir dengan 15 bar forward lengkap hingga `2026-10-16` adalah `2026-09-25`.
  - Menganalisis kenaikan baris data:
    - Terhadap Champion Produksi (cutoff train 2025-08-14): penambahan **+46,343 baris valid (+36.60%)** melintasi 13.5 bulan kalender tambahan (LOW_PRICE valid 31,794 baris, HIGHER_PRICE valid 94,821 baris, terpisah dari 1,452 baris penny stock `EXCLUDED_BELOW_50`).
    - Terhadap Phase 11F (cutoff 2026-09-25): **0 baris inkremental (0.0%)**, karena tidak ada bar pasar baru setelah 2026-10-16.

#### 2. Engine Evaluasi Walk-Forward & Retraining Challenger
- **File:** `python/experiments/challenger_retraining.py` (Baru, 1,074 baris)
- **Rincian Perubahan:**
  - `ChallengerModelSpec`: Mendefinisikan spesifikasi kandidat (Full LightGBM, Ablasi Fitur, Regularized Logistic Regression, Prevalence Baseline, Production Champion).
  - `ChallengerRetrainingRunner.load_matured_data()`: Memuat bar dan fitur, memotong secara ketat pada `date <= 2026-09-25` untuk mencegah kebocoran atau bias survivorship right-censoring.
  - `run_walk_forward_evaluation()`: Menjalankan 3-fold expanding walk-forward validation dengan purge window 15 hari bursa antar fold. Menghitung metrik klasifikasi (ROC-AUC, PR-AUC, Brier score, Log loss, ECE 10 bin, Daily Top-10% & Top-5% precision, Top-5 fixed precision).
  - `_simulate_trading()`: Mensimulasikan eksekusi portofolio harian di bawah friksi 50 bps (15 bps komisi beli, 25 bps komisi jual, 5 bps entry slip, 5 bps exit slip), modal 100jt IDR, max 5 posisi (cap 20%), lot 100 lembar, filter gap pre-entry, preseden konservatif candle ambigu, dan expiry bar 15.
  - `fit_and_serialize_challengers()`: Melatih ulang model kandidat pada seluruh data historis valid hingga `2026-09-25` dan menyimpan 6 biner `.joblib` beserta hash SHA-256 pada `artifacts/offline_challengers/<run_id>/`.

#### 3. CLI Runner Script
- **File:** `scripts/run_offline_challenger_retraining.py` (Baru, 121 baris)
- **Rincian Perubahan:**
  - Menyediakan antarmuka CLI yang dapat dikonfigurasi (`--db-path`, `--cutoff-date`, `--run-id`, `--n-splits`, `--purge-days`, `--random-state`).
  - Menampilkan ringkasan metrik klasifikasi dan simulasi trading secara terstruktur pada konsol.

#### 4. Pengujian Otomatis
- **File:** `tests/unit/test_challenger_retraining.py` (Baru, 142 baris)
- **Rincian Perubahan:**
  - `test_challenger_model_specs`: Menguji kebenaran jumlah fitur dan exclusion group (Full 30, minus trend 23, minus market_regime 24).
  - `test_matured_data_cutoff_enforcement`: Menguji bahwa tanggal keputusan $\le$ `2026-09-25`, LOW_PRICE memiliki 0 incomplete, dan 2 incomplete pada HIGHER_PRICE (MPMX) terfilter keluar dari sampel valid.
  - `test_inspect_dataset_splits`: Menguji keakuratan inspeksi split dataset dan metrik row counts.
  - `test_walk_forward_fold_purge_window`: Menguji penegakan purge window $\ge 15$ hari bursa di seluruh fold.
  - `test_compute_file_sha256`: Menguji integritas perhitungan hash SHA-256.
  - `test_champion_immutability`: Menguji bahwa model champion produksi di registry tetap utuh dan aktif.

#### 5. Dokumentasi dan Laporan Formal
- **File:** `docs/21_offline_challenger_retraining_report.md` (Baru, 281 baris)
  - Menyusun laporan komprehensif mengikuti `docs/AGENT_REPORT_TEMPLATE.md`.
- **File:** `audit_report.md` (Diperbarui baris 91–95)
  - Menambahkan entri indeks 13 untuk laporan retraining challenger.
- **File:** `summary.md` (Diperbarui baris 994–1015)
  - Menambahkan Log Entry 67 (strictly append-only).

---

### Ringkasan Temuan Empiris

#### Metrik Klasifikasi (Macro Mean antar Fold)
- **LOW_PRICE:**
  - Candidate A (Full LGBM): ROC-AUC **0.5615** | PR-AUC **0.3025** | Top-10% Prec **31.03%**
  - Candidate B (Ablation minus trend): ROC-AUC **0.5643** | PR-AUC **0.3000** | Top-10% Prec **30.40%**
  - Candidate C (Logistic Baseline): ROC-AUC **0.5613** | PR-AUC **0.2979** | Top-10% Prec **30.54%**
  - Prevalence Baseline: ROC-AUC **0.5000** | PR-AUC **0.2512** | Top-10% Prec **26.33%**
  - Production Champion (Ref): ROC-AUC **0.6527** | PR-AUC **0.4202** | Top-10% Prec **43.41%**
- **HIGHER_PRICE:**
  - Candidate A (Full LGBM): ROC-AUC **0.5337** | PR-AUC **0.2635** | Top-10% Prec **25.67%**
  - Candidate B (Ablation minus market_regime): ROC-AUC **0.5488** (std 0.0054) | PR-AUC **0.2623** | Top-10% Prec **26.95%**
  - Candidate C (Logistic Baseline): ROC-AUC **0.5512** | PR-AUC **0.2792** | Top-10% Prec **24.69%**
  - Prevalence Baseline: ROC-AUC **0.5000** | PR-AUC **0.2375** | Top-10% Prec **24.32%**
  - Production Champion (Ref): ROC-AUC **0.6226** | PR-AUC **0.3559** | Top-10% Prec **35.74%**

#### Metrik Trading Simulasi (Pooled antar Fold, Friksi 50 bps)
- **LOW_PRICE:**
  - Candidate A (Full LGBM): 1,242 trade | WinRate **29.39%** | Avg Net Ret **-0.351%** | Pooled PF **0.79** | Cont MaxDD **60.54%**
  - Candidate B (Ablation): 1,270 trade | WinRate **28.19%** | Avg Net Ret **-0.478%** | Pooled PF **0.71** | Cont MaxDD **73.51%**
  - Candidate C (Logistic): 1,652 trade | WinRate **29.06%** | Avg Net Ret **-0.422%** | Pooled PF **0.75** | Cont MaxDD **77.69%**
  - Production Champion (Ref): 1,414 trade | WinRate **37.34%** | Avg Net Ret **+0.205%** | Pooled PF **1.20** | Cont MaxDD **42.69%**
- **HIGHER_PRICE:**
  - Candidate A (Full LGBM): 959 trade | WinRate **29.09%** | Avg Net Ret **-0.432%** | Pooled PF **0.74** | Cont MaxDD **59.88%**
  - Candidate B (Ablation): 1,007 trade | WinRate **25.72%** | Avg Net Ret **-0.675%** | Pooled PF **0.63** | Cont MaxDD **74.90%**
  - Candidate C (Logistic): 1,644 trade | WinRate **23.24%** | Avg Net Ret **-0.852%** | Pooled PF **0.55** | Cont MaxDD **93.79%**
  - Production Champion (Ref): 1,448 trade | WinRate **37.84%** | Avg Net Ret **+0.183%** | Pooled PF **1.33** | Cont MaxDD **58.48%**

---

### Testing Checklist

Setelah sesi kerja ini, verifikasi hal-hal berikut:

- [x] **Audit Kontrak & Dataset:** Jalankan `.venv\Scripts\python.exe scripts/inspect_dataset_splits.py` (Verifikasi bar max `2026-10-16`, cutoff `2026-09-25`, +46,343 baris valid [+36.60%], 0 baris incremental vs Phase 11F).
- [x] **Unit Testing Pipeline:** Jalankan `.venv\Scripts\python.exe -m pytest tests/unit/test_challenger_retraining.py -v` (Semua 6 pengujian lulus 100%).
- [x] **Full Repository Test Suite:** Jalankan `.venv\Scripts\python.exe -m pytest -q` (597 tests passed, 0 failures).
- [x] **Linter Cleanliness:** Jalankan `.venv\Scripts\python.exe -m ruff check .` (All checks passed, 0 errors).
- [x] **Integritas Champion Produksi:** Pastikan file `models/registry/lightgbm_classification_20261014_093522.*` dan `093607.*` tidak berubah status atau bobotnya.
- [x] **Isolasi Phase 11F:** Pastikan artefak `artifacts/phase_11f/` tidak dimodifikasi dan flag `--approve-observation` tidak dijalankan.
- [x] **Kelengkapan Artefak Challenger:** Verifikasi 6 model `.joblib`, `metadata.json`, `challenger_retraining_summary.json`, dan file CSV pada `artifacts/offline_challengers/run_20261021_retraining/`.
- [x] **Keputusan Governance:** Verifikasi keputusan eksplisit `DO_NOT_PROMOTE` terdokumentasi jelas pada `docs/21_offline_challenger_retraining_report.md` dan `audit_report.md`.
