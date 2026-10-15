# Audit Remediation & Candidate Model Evaluation Report: BEI Dual-Mode Stock Signals

> **Tanggal Laporan:** 2026-10-15  
> **Status Remediasi:** COMPLETED (Items 1–10)  
> **Status Promosi Produksi:** HALTED / AWAITING APPROVAL  
> **Basis Data:** `datasets/stock_signals.db` (186.291 bar bersih, 208 ticker)  
> **Artefak Hasil Evaluasi:** [`docs/audit_remediation_evaluation_results.json`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/audit_remediation_evaluation_results.json)  
> **Dokumen Audit Sebelumnya:** [`docs/07_audit_training_and_model_quality_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/07_audit_training_and_model_quality_report.md)

---

## 1. Ringkasan Eksekutif & Status Remediasi

Seluruh 10 butir tindakan perbaikan dari rencana remediasi audit pelatihan telah diimplementasikan secara empiris dan diverifikasi menggunakan pengujian unit, linter, serta evaluasi walk-forward out-of-sample:

1. **Pembersihan Data**: 145 bar duplikat legacy `unknown` pada tabel `daily_bars` basis data `datasets/stock_signals.db` telah dihapus. Data resmi `yfinance` dipertahankan utuh. Keterbatasan *survivorship bias* dicatat secara transparan (saham delisted 2023–2026 tidak difabrikasi).
2. **Eliminasi Kebocoran Kalibrasi**: Standard K-Fold CV acak pada `python/models/baseline.py` digantikan dengan kalibrasi kausal murni (`FrozenEstimator` pada validation set terisolasi atau `TimeSeriesSplit` fallback). Early stopping LightGBM dihubungkan ke data validasi kronologis.
3. **Perbaikan Merge Dataset**: Memperbaiki tabrakan nama kolom `entry_price` pada `python/models/dataset.py` sehingga mode harga `LOW_PRICE` (45.763 baris) dan `HIGHER_PRICE` (137.426 baris) terbagi secara valid tanpa baris `INVALID`.
4. **Gerbang Fail-Closed Mathematical EV Hurdle Gate**: Mengimplementasikan perhitungan nilai harapan matematis net friksi riil BEI (fee beli 0,15%, fee jual 0,25%, slippage 10 bps) dan memvalidasi sanitasi nilai non-finite (`math.isfinite()`). Sinyal dengan net EV $\le 0$ atau input esensial invalid ditolak secara fail-closed (0 sinyal BUY dipancarkan).
5. **Evaluasi Eksplisit Outcome Expiry**: Memperhitungkan outcome expiry (+0,69% return realized pada 14,14% dari taruhan non-TP) dalam formulasi nilai harapan diskret.
6. **Pelatihan Regresi Return Companion**: Melatih model regresi LightGBM untuk continuous return pada kedua mode dan membandingkannya secara kuantitatif terhadap baseline statistik.
7. **Simulasi Walk-Forward Backtest Riil**: Menjalankan pengujian walk-forward menyeluruh pada out-of-sample test set (`2026-03-26` s.d. `2026-10-13`).
8. **Proteksi Model Champion**: Model Champion eksisting tetap dipertahankan tanpa perubahan. Empat model baru didaftarkan dengan status `challenger`.
9. **Kepatuhan Batasan**: Tidak mengimplementasikan adaptive TP/SL, target prediksi baru MFE/MAE, maupun dashboard visual.

---

## 2. Rincian Implementasi Remediasi (Items 1–10)

### Item 1: Pembersihan Data Duplikat & Catatan Survivorship Bias
- **Aksi**: Menghapus baris dari tabel `daily_bars` di mana `provider = 'unknown'` bertabrakan dengan data resmi `provider = 'yfinance'` pada kunci unik `(ticker, date, interval)`.
- **Hasil**: 145 bar terhapus. Total bar bersih adalah **186.291 bar**. Basis data di-`VACUUM`.
- **Keterbatasan Data**: Universe saham BEI dibangun menggunakan saham aktif likuid Oktober 2026 (`seed_universe.csv`). Terdapat *survivorship bias* moderat karena saham yang delisted atau pailit antara Januari 2023 hingga Oktober 2026 tidak dimasukkan, dan data delisted tidak difabrikasi demi menjaga integritas data riil.

### Item 2: Kalibrasi Kausal & Early Stopping
- **Komponen**: [`python/models/baseline.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/models/baseline.py) & [`scripts/train_model.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/train_model.py).
- **Akar Masalah Sebelumnya**: Penggunaan `CalibratedClassifierCV(cv=3)` menjalankan K-Fold acak standar di mana baris masa depan pada fold 2 dan 3 digunakan untuk mengalibrasi model fold 1 (future-data leakage). Dataset validasi kronologis (`val_ds`) juga dibuat namun diabaikan saat fitting.
- **Perbaikan**:
  - Jika validation set tersedia (`X_val, y_val`): Model dasar difit dengan early stopping (50 ronde) terhadap loss validasi. Kalibrator kausal dibungkus menggunakan `CalibratedClassifierCV(estimator=FrozenEstimator(base_pipe), method="sigmoid")` dan difit langsung pada set validasi terisolasi tanpa menyentuh data train.
  - Jika fallback tanpa validation set: Menggunakan `TimeSeriesSplit(n_splits=3)` murni kausal.

### Item 3 & 6: Pelatihan Model Dual-Mode (Klasifikasi & Regresi)
Model kandidat dilatih dan didaftarkan ke `models/registry/` sebagai `status="challenger"`:
1. `LOW_PRICE` Classifier: [`lightgbm_classification_20261015_092538`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/models/registry/lightgbm_classification_20261015_092538.json)
2. `HIGHER_PRICE` Classifier: [`lightgbm_classification_20261015_092608`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/models/registry/lightgbm_classification_20261015_092608.json)
3. `LOW_PRICE` Regressor: [`lightgbm_regression_20261015_092635`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/models/registry/lightgbm_regression_20261015_092635.json)
4. `HIGHER_PRICE` Regressor: [`lightgbm_regression_20261015_092710`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/models/registry/lightgbm_regression_20261015_092710.json)

### Item 4 & 5: Gerbang Fail-Closed Mathematical EV Hurdle Gate
- **Komponen**: [`python/signals/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/signals/engine.py) & [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py).
- **Formulasi Nilai Harapan Matematis**:
  $$\text{Friction} = \text{Fee}_{\text{buy}} (0.15\%) + \text{Fee}_{\text{sell}} (0.25\%) + \text{Slippage} (0.10\%) = 0.50\%$$
  $$\text{TP}_{\text{net}} = +5.00\% - 0.50\% = +4.50\%$$
  $$\text{SL}_{\text{net}} = -2.00\% - 0.50\% = -2.50\%$$
  $$\text{Exp}_{\text{net}} = +0.69\% - 0.50\% = +0.19\%$$
  $$\text{EV}_{\text{discrete}} = p \cdot (+0.045) + (1-p) \cdot [0.8586 \cdot (-0.025) + 0.1414 \cdot (+0.0019)]$$
- **Batas Breakeven Hurdle**:
  $$\text{Win Rate}_{\text{BE}} = \frac{0.8586 \times 0.025 - 0.1414 \times 0.0019}{0.045 + 0.8586 \times 0.025 - 0.1414 \times 0.0019} = \mathbf{32.1\%}$$
- **Kombinasi Regresi**: $\text{Effective Net EV} = \min(\text{EV}_{\text{discrete}}, \text{Pred Return} - \text{Friction})$.
- **Sanitasi Fail-Closed**: Nilai return dan EV divalidasi dengan `math.isfinite()`. Jika regressor menghasilkan `NaN` atau `Inf`, atau net EV $\le 0$, sinyal BUY langsung digugurkan secara absolut.

---

## 3. Hasil Pengujian & Evaluasi Out-of-Sample

Evaluasi dilakukan secara ketat pada periode out-of-sample murni (`2026-03-26` s.d. `2026-10-13`):
- `LOW_PRICE`: 7.410 baris pengujian.
- `HIGHER_PRICE`: 19.439 baris pengujian.

### A. Metrik Klasifikasi Probabilistik
| Mode Harga | Model Evaluasi | Brier Score | Log Loss | ROC-AUC | Akurasi | Calibration Error |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`LOW_PRICE`** | *Baseline Prevalensi Konstan* | 0.1922 | 0.5727 | 0.5000 | 74.05% | **0.0065** |
| | Champion (`20261014_093522`) | **0.1910** | **0.5674** | **0.5539** | 74.05% | 0.0334 |
| | Kandidat Kausal (`20261015_092538`) | 0.1981 | 0.5810 | 0.5390 | 72.83% | 0.0728 |
| **`HIGHER_PRICE`** | *Baseline Prevalensi Konstan* | **0.1867** | **0.5607** | 0.5000 | 75.15% | **0.0010** |
| | Champion (`20261014_093607`) | 0.1884 | 0.5643 | 0.5135 | 75.15% | 0.0337 |
| | Kandidat Kausal (`20261015_092608`) | 0.1989 | 0.5878 | **0.4913** | 73.20% | 0.0808 |

### B. Metrik Regresi Return Kontinu
| Mode Harga | Model Evaluasi | MSE | RMSE | MAE | $R^2$ Score |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`LOW_PRICE`** | *Baseline Prediksi Nol ($y=0$)* | 0.001292 | 0.035945 | 0.028324 | -0.0002 |
| | *Baseline Rata-rata Historis ($\bar{y}$)* | **0.001293** | **0.035956** | **0.028170** | **-0.0008** |
| | Baseline Ridge Regression | 0.001302 | 0.036082 | 0.029273 | -0.0079 |
| | Kandidat LightGBM (`20261015_092635`) | 0.001312 | 0.036218 | 0.029074 | -0.0155 |
| **`HIGHER_PRICE`** | *Baseline Prediksi Nol ($y=0$)* | 0.001806 | 0.042496 | 0.029916 | -0.0003 |
| | *Baseline Rata-rata Historis ($\bar{y}$)* | **0.001806** | **0.042493** | **0.029811** | **-0.0001** |
| | Baseline Ridge Regression | 0.001832 | 0.042800 | 0.031456 | -0.0146 |
| | Kandidat LightGBM (`20261015_092710`) | 0.001851 | 0.043021 | 0.030729 | -0.0251 |

### C. Simulasi Walk-Forward Backtest (Modal Awal Rp 100 Juta, Friksi Penuh BEI)
| Mode Harga | Parameter Simulasi | Champion (`p>=0.25`) | Kandidat Tanpa Gate (`p>=0.25`) | **Kandidat + EV Hurdle Gate** |
| :--- | :--- | :--- | :--- | :--- |
| **`LOW_PRICE`** | Total Eksekusi Trades | 346 | 316 | **0** |
| | Win Rate | 30.06% | 25.32% | **0.00%** |
| | Profit Factor | 0.75 | 0.66 | **0.00** |
| | Total Net Return | -26.32% (-Rp 26.31M) | -34.64% (-Rp 34.64M) | **+0.00% (Rp 0)** |
| | Max Drawdown | 30.65% | 38.88% | **0.00%** |
| | Net Expectancy / Trade | -0.43% | -0.67% | **+0.00%** |
| | Modal Akhir Portofolio | Rp 73.683.842 | Rp 65.363.770 | **Rp 100.000.000 (100% Utuh)** |
| **`HIGHER_PRICE`** | Total Eksekusi Trades | 333 | 320 | **0** |
| | Win Rate | 20.42% | 23.75% | **0.00%** |
| | Profit Factor | 0.44 | 0.51 | **0.00** |
| | Total Net Return | -52.14% (-Rp 52.14M) | -43.66% (-Rp 43.66M) | **+0.00% (Rp 0)** |
| | Max Drawdown | 52.14% | 43.66% | **0.00%** |
| | Net Expectancy / Trade | -1.11% | -0.89% | **+0.00%** |
| | Modal Akhir Portofolio | Rp 47.856.486 | Rp 56.344.617 | **Rp 100.000.000 (100% Utuh)** |

---

## 4. Rekomendasi Formal Kandidat

1. **Kandidat `HIGHER_PRICE` Classifier (`lightgbm_classification_20261015_092608`)**:
   - **Keputusan**: **REJECT (DITOLAK SECARA MUTLAK)**.
   - **Rasional**: Out-of-sample ROC-AUC adalah **0.4913** (lebih buruk dari tebakan acak 50%). Brier score (0.1989) kalah terhadap baseline prevalensi historis (0.1867). Fitur teknikal standar saat ini tidak memiliki daya prediksi memadai untuk saham di atas IDR 300.
2. **Kandidat `HIGHER_PRICE` Regressor (`lightgbm_regression_20261015_092710`)**:
   - **Keputusan**: **REJECT**.
   - **Rasional**: Nilai $R^2 = -0.0251$ menunjukkan error prediksi lebih tinggi daripada menebak rata-rata historis secara konstan.
3. **Kandidat `LOW_PRICE` Classifier (`lightgbm_classification_20261015_092538`)**:
   - **Keputusan**: **CONTINUE TESTING (JANGAN DIPROMOSIKAN KE CHAMPION)**.
   - **Rasional**: ROC-AUC berada di angka **0.5390** (memiliki sinyal prediktif positif, namun belum mengungguli Champion lama 0.5539). Brier score (0.1981) masih di bawah baseline prevalensi (0.1922).
4. **Gerbang Mathematical EV Hurdle Gate**:
   - **Keputusan**: **MANDATORY IN PRODUCTION (WAJIB AKTIF)**.
   - **Rasional**: Mencegah kerugian modal sistematis. Jika sinyal dipaksa trading pada threshold 0.25 tanpa hurdle, portofolio mengalami kehancuran hingga -43.66%. Di bawah EV Hurdle Gate, 100% sinyal bernilai harapan negatif diblokir, menyelamatkan modal 100% (Rp 100.000.000 utuh).
5. **Status Model Champion Produksi**:
   - Model Champion eksisting tetap dipertahankan (`lightgbm_classification_20261014_093522` dan `lightgbm_classification_20261014_093607`).
   - Tidak ada model yang dipromosikan ke status champion pada sesi ini.

---

## 5. Ringkasan Verifikasi & Kepatuhan Proyek

- **Unit & Integration Tests**: **387 test lulus 100%** tanpa kegagalan (`pytest` exit code 0).
- **Linter**: **0 lint errors** (`ruff check .` clean).
- **Integritas Dokumentasi**:
  - `summary.md`: Entri 39 & 40 ditambahkan secara Append-Only.
  - `walkthrough.md`: Rincian baris kode dan Checklist Pengujian diperbarui lengkap.
- **Status Deployment**: Berhenti sebelum promosi model atau deployment AWS produksi, menunggu keputusan pengguna.
