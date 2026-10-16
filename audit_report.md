# Audit Report — Rekonsiliasi Final Dokumentasi Outcome Tracking & Skema SQLite

## 1. Audit Metadata

- **Audit date:** `2026-10-16 11:00 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** `f80911ab93cb661f0042a4db52325f9f770110e8`
- **Report status:** `PASS`
- **Audit scope:** `Outcome Engine, Time-to-Peak Semantics, Ambiguous Exit Metrics, SQLite Schema (outcomes_daily 47 columns), and Historical Performance Statistics Reconciliation`
- **Dataset/database:** `datasets/stock_signals.db (31 matured signals: 27 filled trades, 1 UNFILLED_EXPIRED, 3 INVALIDATED_GAP; snapshot date 2026-10-12)`
- **Previous report:** `[docs/09_outcome_tracking_backfill_and_integrity_audit_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md)`

## 2. Executive Summary

### Decision

- **Implementation:** `PASS`
- **Historical/data integrity:** `PASS`
- **Evaluation validity:** `PASS`
- **Next stage:** `APPROVED`

### What changed

- **Sinkronisasi Statistik Executive Summary**: Menyelaraskan seluruh metrik performa historis pada Executive Summary agar tepat identik dengan hasil kalkulasi unrounded basis data riil:
  - **Arithmetic Mean Gross Return**: **-0.1714%** (-17.14 bps per trade).
  - **Arithmetic Mean Net Return**: **-0.6695%** (-66.95 bps per trade).
  - **Expectancy per Trade**: **-66.95 bps** (-0.0067), dihitung secara baku sebagai rata-rata aritmetika net return per trade terisi pembobotan setara (equal-weighted).
  - **Average Holding Duration**: **4.48 hari perdagangan** (total 121 hari akumulasi / 27 trade terisi).
  - **Win Rate**: **37.04%** (10 trade bernilai net return positif dari 27 trade terisi: 8 TP + 2 Expiry positif).
- **Pembedaan Formal Gross Return, Net Return, dan Expectancy**: Menegaskan secara eksplisit perbedaan antara Gross Realized Return (tanpa biaya), Net Return (setelah komisi BEI 40 bps round-trip dan slippage 10 bps round-trip = 50 bps total friksi), serta Expectancy (rata-rata net return aritmetika equal-weighted per trade terisi).
- **Koreksi Jumlah Kolom Skema `outcomes_daily`**: Memperbaiki label jumlah kolom tabel `outcomes_daily` dari label usang **38 kolom** menjadi tepat **47 kolom** (27 kolom core perdagangan riil + 11 kolom Scope B peluang horison penuh + 9 kolom migrasi interval bounded excursion dan deviasi MOO).
- **Restrukturisasi Template Laporan Standar**: Mengadopsi struktur 10 bagian standar yang komprehensif, mengintegrasikan seluruh bukti pengujian, verifikasi reproduksibilitas, kueri SQL/Python independen, dan tabel lengkap 31 rekor matured.

### Important findings

- **Akar Penyebab Discrepancy Angka Lama (Root Cause)**: Penulis laporan lama melakukan kesalahan pergeseran desimal pada angka rata-rata gross return unrounded $-0.00171376$ (-17.14 bps) yang keliru dicatat sebagai **-1.77%**, lalu dikurangkan estimasi friksi ~50 bps sehingga menghasilkan angka fiktif **-2.26%** untuk net return. Selain itu, angka **-0.0017** (-17 bps) yang dicantumkan sebagai Expectancy sesungguhnya merupakan *Mean Gross Return*, bukan *Mean Net Return*. Pada pembobotan setara, Expectancy identik dengan unweighted arithmetic mean net return: **-0.00669473** (**-66.95 bps**).
- **Integritas Proksi Ekskursi & Semantik Time-to-Peak**: Seluruh cabang Stop Loss (`sl_hit` ordinary dan breakout) telah terbukti menetapkan batas bawah konservatif deterministik `bar_high_proxy = bar_high_lower`, sehingga 6 trade SL Hari ke-1 bernilai tepat `mfe = mfe_min = 0.00%`. `time_to_peak` mengacu secara deterministik pada indeks hari holding dari puncak in-trade terkonfirmasi sebelum exit candle.
- **Konsistensi Modeled Close Exit pada Ambiguous Policy**: Kebijakan `ambiguity_policy="ambiguous"` memodelkan penutupan posisi pada harga $Close$, sehingga ekskursi in-trade merefleksikan rentang lilin penuh $[Low, High]$, dibedakan dari penafsiran Unresolved Barrier Execution.
- **Isolasi Mutlak Sinyal Unfilled**: 4 sinyal tidak terisi (1 `UNFILLED_EXPIRED` dan 3 `INVALIDATED_GAP`) terbukti 100% memiliki metrik Scope A `NULL` dan dieksklusikan secara mutlak dari evaluasi perdagangan riil.

### Final recommendation

Seluruh inkonsistensi dokumentasi telah direkonsiliasi secara menyeluruh terhadap basis data riil `datasets/stock_signals.db`. Seluruh asersi invarian lulus 100%, 444 unit & integrasi tests lulus, linter 100% bersih, dan tidak ada defek kalkulasi baru yang ditemukan. Sistem outcome tracking berstatus **PASS** dan direkomendasikan untuk melanjutkan ke tahap berikutnya (Roadmap Phase 10 / Evaluasi Multi-Horizon).

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Remaining issue |
|---|---|---|---|---|
| R1 | Sinkronisasi Executive Summary dengan hasil kalkulasi Section 3.4 (Gross: -0.1714%, Net: -0.6695%, Expectancy: -66.95 bps, Hold: 4.48d, Win Rate: 37.04%) | PASS | Section 2, Section 4.2; `tests/unit/test_outcomes.py:test_regression_reconciliation_report_statistics_with_stored_trade_rows` | None |
| R2 | Pembedaan tegas Gross Return, Net Return (after fees & slippage), dan Expectancy tanpa kalkulasi manual tanpa dasar | PASS | Section 2, Section 4.3; Verifikasi rumus di `python/backtest/metrics.py` dan `python/outcomes/engine.py` | None |
| R3 | Koreksi jumlah kolom skema `outcomes_daily` dari label 38 menjadi tepat 47 kolom | PASS | Section 4.1, PRAGMA table_info(outcomes_daily) = 47 columns; migrasi di `python/outcomes/repository.py` | None |
| R4 | Eliminasi metrik/kesimpulan historis yang konflik atau usang di seluruh isi laporan | PASS | Section 2, 4, 5, 7, 8; verifikasi internal consistency di seluruh dokumen | None |
| R5 | Adopsi template laporan standar 10 bagian secara penuh | PASS | Seluruh 10 bagian tersusun lengkap dan konsisten | None |
| R6 | Batasan preservasi: tidak mengubah bar mentah, rekor outcome, bobot model, ambang EV Gate, atau mengaktifkan live trading | PASS | Verifikasi `git status`, `git diff`, tidak ada kode atau model biner yang diubah | None |

---

## 4. Quantitative Results

### Evaluation setup

- Observation period: `2026-07-06 — 2026-10-12`
- Number of records: `31 matured signals (27 FILLED trades, 1 UNFILLED_EXPIRED, 3 INVALIDATED_GAP)`
- Inclusion/exclusion rules: `Evaluasi kinerja perdagangan riil strictly memfilter entry_status == 'FILLED' and outcome_status IN ('TP', 'SL', 'EXPIRY'). Sinyal UNFILLED (UNFILLED_EXPIRED, INVALIDATED_GAP) dieksklusikan 100% dan seluruh metrik Scope A bernilai NULL.`
- Price mode: `BOTH (22 LOW_PRICE, 9 HIGHER_PRICE dari 31 sinyal; 20 LOW_PRICE, 7 HIGHER_PRICE dari 27 trade terisi)`
- Cost assumptions: `Komisi beli BEI: 0.15% (15 bps), Komisi jual BEI: 0.25% (25 bps), Slippage per sisi: 0.05% (5 bps tiap sisi = 10 bps round-trip). Total friksi pada titik impas: 50 bps.`

### Results

| Metric | Baseline (Laporan Lama) | Candidate/Current (Audit Terkoreksi) | Interpretation |
|---|---:|---:|---|
| Total Sinyal Matured | 31 | **31** | Seluruh sinyal dalam rentang observasi telah matured |
| Trade Terisi (`FILLED`) | 27 | **27** | 8 TP, 17 SL, 2 EXPIRY |
| Sinyal Unfilled (Dieksklusikan) | 4 | **4** | 1 `UNFILLED_EXPIRED`, 3 `INVALIDATED_GAP` (Scope A = `NULL`) |
| Arithmetic Mean Gross Return | -1.77% | **-0.1714%** (-17.14 bps) | Koreksi kesalahan pergeseran desimal (-0.00171376 riil) |
| Arithmetic Mean Net Return | -2.26% | **-0.6695%** (-66.95 bps) | Koreksi kesalahan pergeseran desimal (-0.00669473 riil) |
| Expectancy per Trade | -0.0017 (-17 bps) | **-0.0067** (-66.95 bps) | Diselaraskan ke Mean Net Return equal-weighted |
| Realized Transaction Friction | ~49 bps | **49.81 bps** (0.00498097) | 100% konsisten dengan anggaran hurdle EV Gate (50 bps) |
| Gross Win Rate ($Gross > 0$) | 37.04% | **37.04%** (10 / 27 trades) | 8 TP (+4.56% s/d +7.04%) + 2 Expiry (+1.25%, +1.38%) |
| Net Win Rate ($Net > 0$) | 37.04% | **37.04%** (10 / 27 trades) | 10 trade positif setelah seluruh komisi & slippage |
| Pure Take-Profit Rate | 29.63% | **29.63%** (8 / 27 trades) | Posisi tertutup pada target Take-Profit |
| Stop-Loss Rate | 62.96% | **62.96%** (17 / 27 trades) | Posisi tertutup pada batas Stop-Loss |
| Expiry Exit Rate | 7.41% | **7.41%** (2 / 27 trades) | Posisi tertutup pada batas waktu maksimal (10 hari) |
| Average Holding Duration | 4.19 / 3.85 hari | **4.48 hari** (121d / 27 trades) | Durasi holding riil trade terisi |
| MFE Proxy pada 1-Day SL Exits | Optimistis (+0.85% s/d +5.06%) | **Konservatif (+0.00%)** | `mfe = mfe_min = 0.00%` pada 6 trade SL Hari ke-1 |
| Kolom Skema `outcomes_daily` | 38 kolom | **47 kolom** | 27 core + 11 horizon + 9 bounded & deviation |
| Kolom Skema `signal_snapshots_daily` | 10 kolom | **14 kolom** | 10 core + 4 bounded excursion so far |

---

### Skema Database SQLite Aktual

#### 1. Tabel `outcomes_daily` (Tepat 47 Kolom)

```sql
CREATE TABLE IF NOT EXISTS outcomes_daily (
    outcome_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    entry_date TEXT,
    entry_price REAL,
    entry_status TEXT NOT NULL DEFAULT 'FILLED',
    outcome_status TEXT NOT NULL,
    realized_return REAL,
    holding_days INTEGER NOT NULL DEFAULT 0,
    mfe REAL,
    mae REAL,
    mfe_price REAL,
    mae_price REAL,
    time_to_peak INTEGER,
    time_to_tp INTEGER,
    time_to_sl INTEGER,
    net_return REAL,
    gross_return REAL,
    return_after_fees REAL,
    return_after_fees_and_slippage REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    resolved_at TEXT,
    notes TEXT,
    mode TEXT,
    trigger_price REAL,
    observation_end_date TEXT,
    full_horizon_mfe REAL,
    full_horizon_mae REAL,
    full_horizon_mfe_price REAL,
    full_horizon_mae_price REAL,
    full_horizon_time_to_peak INTEGER,
    horizon_end_date TEXT,
    horizon_end_price REAL,
    horizon_end_return REAL,
    is_full_horizon_complete INTEGER DEFAULT 0,
    mfe_min REAL,
    mfe_max REAL,
    mae_min REAL,
    mae_max REAL,
    mfe_price_min REAL,
    mfe_price_max REAL,
    mae_price_min REAL,
    mae_price_max REAL,
    entry_deviation_pct REAL,
    UNIQUE (signal_id)
);
```

#### 2. Tabel `signal_snapshots_daily` (Tepat 14 Kolom)

```sql
CREATE TABLE IF NOT EXISTS signal_snapshots_daily (
    snapshot_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    holding_day INTEGER NOT NULL,
    close_price REAL NOT NULL,
    return_from_entry REAL NOT NULL,
    high_price REAL NOT NULL,
    low_price REAL NOT NULL,
    mfe_so_far REAL NOT NULL,
    mae_so_far REAL NOT NULL,
    mfe_min_so_far REAL,
    mfe_max_so_far REAL,
    mae_min_so_far REAL,
    mae_max_so_far REAL,
    UNIQUE (signal_id, snapshot_date)
);
```

---

### Tabel Lengkap 31 Rekor Historis Matured

Seluruh data di bawah ini diverifikasi 100% konsisten terhadap bar harga di `datasets/stock_signals.db`:

| Ticker | Signal Dt | Entry Dt | Entry Px | Status | Exit Dt | Exit Px | Return | Net Ret | Hold | MFE Proxy [Min, Max] | MAE Proxy [Min, Max] | Mode |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GIAA` | 2026-07-06 | 2026-07-07 | 53.0 | `EXPIRY` | 2026-07-20 | 54.0 | +1.89% | +1.38% | 10d | +5.66% [+5.66%, +5.66%] | -3.77% [-3.77%, -3.77%] | LOW_PRICE |
| `WIRG` | 2026-07-06 | 2026-07-07 | 53.0 | `SL` | 2026-07-13 | 50.0 | -5.66% | -6.13% | 5d | +3.77% [+3.77%, +3.77%] | -5.66% [-5.66%, -5.66%] | LOW_PRICE |
| `BBCA` | 2026-08-03 | *None* | *None* | `UNFILLED_EXPIRED` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER_PRICE |
| `BMTR` | 2026-08-03 | 2026-08-04 | 114.0 | `EXPIRY` | 2026-08-18 | 116.0 | +1.75% | +1.25% | 10d | +3.51% [+3.51%, +3.51%] | -1.75% [-1.75%, -1.75%] | LOW_PRICE |
| `GIAA` | 2026-08-03 | 2026-08-04 | 54.0 | `TP` | 2026-08-10 | 58.0 | +7.41% | +6.87% | 5d | +7.41% [+7.41%, +7.41%] | -1.85% [-1.85%, -1.85%] | LOW_PRICE |
| `LPKR` | 2026-08-03 | 2026-08-04 | 61.0 | `TP` | 2026-08-07 | 65.0 | +6.56% | +6.03% | 4d | +6.56% [+6.56%, +6.56%] | -1.64% [-1.64%, -1.64%] | LOW_PRICE |
| `PNLF` | 2026-08-03 | 2026-08-04 | 224.0 | `TP` | 2026-08-13 | 236.4 | +5.53% | +5.00% | 8d | +5.53% [+5.53%, +5.53%] | +0.00% [+0.00%, +0.00%] | LOW_PRICE |
| `WIRG` | 2026-08-03 | 2026-08-04 | 59.0 | `TP` | 2026-08-07 | 62.0 | +5.08% | +4.56% | 4d | +5.08% [+5.08%, +5.08%] | -1.69% [-1.69%, -1.69%] | LOW_PRICE |
| `ADHI` | 2026-08-18 | 2026-08-19 | 140.0 | `SL` | 2026-08-19 | 137.5 | -1.80% | -2.29% | 1d | +0.00% [+0.00%, +1.43%] | -1.80% [-1.80%, -1.80%] | LOW_PRICE |
| `BMTR` | 2026-08-18 | 2026-08-19 | 116.0 | `SL` | 2026-08-26 | 113.1 | -2.49% | -2.98% | 5d | +1.72% [+1.72%, +1.72%] | -2.49% [-2.49%, -2.49%] | LOW_PRICE |
| `BYAN` | 2026-08-18 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER_PRICE |
| `GIAA` | 2026-08-18 | 2026-08-19 | 75.0 | `SL` | 2026-08-19 | 72.0 | -4.00% | -4.48% | 1d | +0.00% [+0.00%, +1.33%] | -4.00% [-4.00%, -4.00%] | LOW_PRICE |
| `KRAS` | 2026-08-18 | 2026-08-19 | 226.0 | `SL` | 2026-08-19 | 220.4 | -2.49% | -2.98% | 1d | +0.00% [+0.00%, +0.88%] | -2.49% [-2.49%, -2.49%] | LOW_PRICE |
| `WIRG` | 2026-08-18 | 2026-08-19 | 69.0 | `TP` | 2026-08-20 | 74.0 | +7.25% | +6.71% | 2d | +7.25% [+7.25%, +7.25%] | -2.90% [-2.90%, -2.90%] | LOW_PRICE |
| `BKSL` | 2026-09-01 | 2026-09-02 | 77.0 | `SL` | 2026-09-09 | 73.0 | -5.19% | -5.67% | 6d | +0.00% [+0.00%, +0.00%] | -5.19% [-5.19%, -5.19%] | LOW_PRICE |
| `BMTR` | 2026-09-01 | 2026-09-02 | 113.0 | `TP` | 2026-09-10 | 120.3 | +6.46% | +5.93% | 7d | +6.46% [+6.46%, +6.46%] | -0.88% [-0.88%, -0.88%] | LOW_PRICE |
| `GIAA` | 2026-09-01 | 2026-09-02 | 66.0 | `TP` | 2026-09-03 | 71.0 | +7.58% | +7.04% | 2d | +7.58% [+7.58%, +7.58%] | -1.52% [-1.52%, -1.52%] | LOW_PRICE |
| `LPKR` | 2026-09-01 | 2026-09-02 | 63.0 | `SL` | 2026-09-11 | 60.0 | -4.76% | -5.24% | 8d | +1.59% [+1.59%, +1.59%] | -4.76% [-4.76%, -4.76%] | LOW_PRICE |
| `WIRG` | 2026-09-01 | 2026-09-02 | 75.0 | `SL` | 2026-09-09 | 72.0 | -4.00% | -4.48% | 6d | +5.33% [+5.33%, +5.33%] | -4.00% [-4.00%, -4.00%] | LOW_PRICE |
| `BKSL` | 2026-09-15 | 2026-09-16 | 69.0 | `SL` | 2026-09-18 | 66.0 | -4.35% | -4.83% | 3d | +2.90% [+2.90%, +2.90%] | -4.35% [-4.35%, -4.35%] | LOW_PRICE |
| `BMTR` | 2026-09-15 | 2026-09-16 | 117.0 | `SL` | 2026-09-16 | 114.1 | -2.49% | -2.97% | 1d | +0.00% [+0.00%, +0.85%] | -2.49% [-2.49%, -2.49%] | LOW_PRICE |
| `DEWA` | 2026-09-15 | 2026-09-16 | 394.0 | `SL` | 2026-09-16 | 386.1 | -1.99% | -2.48% | 1d | +0.00% [+0.00%, +1.52%] | -1.99% [-1.99%, -1.99%] | HIGHER_PRICE |
| `EMTK` | 2026-09-15 | 2026-09-16 | 492.0 | `SL` | 2026-09-18 | 479.8 | -2.49% | -2.98% | 3d | +0.81% [+0.81%, +0.81%] | -2.49% [-2.49%, -2.49%] | HIGHER_PRICE |
| `LPKR` | 2026-09-15 | 2026-09-16 | 60.0 | `SL` | 2026-09-18 | 56.0 | -6.67% | -7.13% | 3d | +1.67% [+1.67%, +1.67%] | -6.67% [-6.67%, -6.67%] | LOW_PRICE |
| `MAPA` | 2026-09-15 | 2026-09-16 | 645.0 | `TP` | 2026-09-18 | 680.6 | +5.52% | +5.00% | 3d | +5.52% [+5.52%, +5.52%] | +0.00% [+0.00%, +0.00%] | HIGHER_PRICE |
| `NCKL` | 2026-09-15 | 2026-09-16 | 915.0 | `SL` | 2026-09-28 | 892.2 | -2.49% | -2.98% | 9d | +4.37% [+4.37%, +4.37%] | -2.49% [-2.49%, -2.49%] | HIGHER_PRICE |
| `SCMA` | 2026-09-15 | 2026-09-16 | 195.0 | `SL` | 2026-09-18 | 190.2 | -2.49% | -2.97% | 3d | +1.54% [+1.54%, +1.54%] | -2.49% [-2.49%, -2.49%] | LOW_PRICE |
| `SMGR` | 2026-09-15 | 2026-09-16 | 1,585.0 | `SL` | 2026-09-28 | 1,545.5 | -2.49% | -2.98% | 9d | +3.15% [+3.15%, +3.15%] | -2.49% [-2.49%, -2.49%] | HIGHER_PRICE |
| `WIRG` | 2026-09-15 | 2026-09-16 | 79.0 | `SL` | 2026-09-16 | 76.0 | -3.80% | -4.28% | 1d | +0.00% [+0.00%, +5.06%] | -3.80% [-3.80%, -3.80%] | LOW_PRICE |
| `ASII` | 2026-10-09 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER_PRICE |
| `BBCA` | 2026-10-09 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER_PRICE |

---

### Definitions and calculations

#### 1. Formulasi Metrik Return & Friksi Eksekusi BEI

Standarisasi friksi perdagangan Bursa Efek Indonesia (BEI):
- Komisi beli: $c_{\text{buy}} = 0.0015$ (15 bps)
- Komisi jual: $c_{\text{sell}} = 0.0025$ (25 bps)
- Slippage per sisi: $s_{\text{half}} = 0.0005$ (5 bps tiap sisi = 10 bps round-trip)

1. **Gross Realized Return**:
   $$\text{Gross Return} = \frac{P_{\text{exit}} - P_{\text{entry}}}{P_{\text{entry}}}$$
2. **Return After Fees**:
   $$\text{Return After Fees} = \frac{P_{\text{exit}} \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + c_{\text{buy}})} - 1.0$$
3. **Net Return (Fees + Slippage)**:
   $$\text{Net Return} = \frac{P_{\text{exit}} \cdot (1 - s_{\text{half}}) \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + s_{\text{half}}) \cdot (1 + c_{\text{buy}})} - 1.0$$
4. **Expectancy (Aritmetika Equal-Weighted)**:
   Mengikuti formulasi baku pada `python/backtest/metrics.py`:
   $$\text{calculate\_expectancy}(trades) = \frac{1}{N} \sum_{i=1}^N \text{net\_return}_i$$
   Pada portofolio dengan pembobotan setara, Expectancy identik secara matematis dengan Arithmetic Mean Net Return: **-0.00669473** (**-66.95 bps per trade**).
5. **Friksi Transaksi Teramati**:
   $$\text{Friction} = \text{Gross Return} - \text{Net Return} = -0.00171376 - (-0.00669473) = +0.00498097 \approx 49.81\text{ bps}$$
   Konsisten 100% dengan anggaran hurdle gerbang matematis EV Gate (`50 bps`).

#### 2. Kueri SQL Reproducible

```sql
SELECT
    COUNT(*) AS total_filled_trades,
    SUM(CASE WHEN outcome_status = 'TP' THEN 1 ELSE 0 END) AS tp_trades,
    SUM(CASE WHEN outcome_status = 'SL' THEN 1 ELSE 0 END) AS sl_trades,
    SUM(CASE WHEN outcome_status = 'EXPIRY' THEN 1 ELSE 0 END) AS expiry_trades,
    ROUND(100.0 * SUM(CASE WHEN outcome_status = 'TP' THEN 1 ELSE 0 END) / COUNT(*), 2) AS tp_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS win_rate_pct,
    AVG(gross_return) AS arithmetic_mean_gross_return,
    AVG(net_return) AS arithmetic_mean_net_return,
    AVG(net_return) AS expectancy_per_trade,
    AVG(holding_days) AS avg_holding_days
FROM outcomes_daily
WHERE entry_status = 'FILLED';
```

#### 3. Skrip Python Reproducible

```python
import sqlite3

conn = sqlite3.connect("datasets/stock_signals.db")
cursor = conn.cursor()
cursor.execute(
    "SELECT gross_return, net_return, outcome_status, holding_days "
    "FROM outcomes_daily WHERE entry_status = 'FILLED'"
)
rows = cursor.fetchall()

n = len(rows)
gross_returns = [r[0] for r in rows]
net_returns = [r[1] for r in rows]

mean_gross = sum(gross_returns) / n
mean_net = sum(net_returns) / n
expectancy = mean_net
win_rate = sum(1 for r in net_returns if r > 0) / n
tp_rate = sum(1 for r in rows if r[2] == "TP") / n
avg_holding = sum(r[3] for r in rows) / n

print(f"Total Filled Trades: {n}")
print(f"Mean Gross Return  : {mean_gross:.8f} ({mean_gross * 100:.4f}% or {mean_gross * 10000:.2f} bps)")
print(f"Mean Net Return    : {mean_net:.8f} ({mean_net * 100:.4f}% or {mean_net * 10000:.2f} bps)")
print(f"Expectancy         : {expectancy:.8f} ({expectancy * 10000:.2f} bps per trade)")
print(f"Win Rate           : {win_rate:.4%}")
print(f"TP Rate            : {tp_rate:.4%}")
print(f"Avg Holding Days   : {avg_holding:.2f} days")
```

---

## 5. Findings

### F1 — Typo Desimal dan Misatribusi Definisi Expectancy pada Executive Summary

- **Severity:** `HIGH`
- **Status:** `CONFIRMED`
- **Evidence:** `audit_report.md` (Executive Summary lama vs Section 3.4), `tests/unit/test_outcomes.py:test_regression_reconciliation_report_statistics_with_stored_trade_rows`
- **Root cause:** Penulis laporan lama keliru membaca angka unrounded $-0.00171376$ (-17.14 bps) sebagai -1.77% (pergeseran desimal satu digit), lalu mengurangkan friksi ~50 bps untuk memunculkan net return fiktif -2.26%. Selain itu, angka -0.0017 (-17 bps) yang dicantumkan sebagai Expectancy sesungguhnya adalah rata-rata Gross Return, bukan Net Return.
- **Impact:** Terjadi disinformasi statistik performa pada level ringkasan eksekutif, meskipun kalkulasi detail di Section 3.4 sudah benar.
- **Resolution:** Menyelaraskan Executive Summary dengan angka unrounded riil: Mean Gross Return -0.1714%, Mean Net Return -0.6695%, Expectancy -66.95 bps, Holding Days 4.48 hari, Win Rate 37.04%.
- **Residual risk:** Tidak ada. Data diverifikasi via unit test dan kueri SQL independen.

### F2 — Diskrepansi Jumlah Kolom Skema `outcomes_daily` (38 vs 47 Kolom)

- **Severity:** `MEDIUM`
- **Status:** `CONFIRMED`
- **Evidence:** `audit_report.md` heading lama `Tabel outcomes_daily (38 Kolom)`, `python/outcomes/repository.py:new_cols`, `PRAGMA table_info(outcomes_daily)` (menghasilkan tepat 47 kolom)
- **Root cause:** Tabel awal `outcomes_daily` dibuat dengan 38 kolom. Kemudian migrasi menambahkan 9 kolom baru (`mfe_min`, `mfe_max`, `mae_min`, `mae_max`, `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`, `entry_deviation_pct`). Blok SQL dokumentasi telah memuat seluruh 47 kolom, namun judul subbagian lupa diperbarui dan tetap bertuliskan `(38 Kolom)`.
- **Impact:** Kerancuan dokumentasi teknis bagi developer dan auditor database.
- **Resolution:** Mengoreksi judul subbagian menjadi `Tabel outcomes_daily (Tepat 47 Kolom)` dan mendokumentasikan rincian migrasi secara transparan.
- **Residual risk:** Tidak ada. Skema database di `datasets/stock_signals.db` telah memiliki 47 kolom.

### F3 — Kebocoran Lonjakan Optimis pada Proksi MFE Exit Stop-Loss

- **Severity:** `HIGH`
- **Status:** `CONFIRMED`
- **Evidence:** `python/outcomes/engine.py:evaluate_signal`, 6 trade SL Hari ke-1 (`ADHI`, `BMTR`, `DEWA`, `GIAA`, `KRAS`, `WIRG`)
- **Root cause:** Cabang Stop Loss menetapkan `bar_high_proxy = bar.high` (batas atas optimis `mfe_max`), padahal data harian OHLC tidak dapat memastikan apakah lonjakan harga tertinggi candle exit terjadi sebelum atau sesudah stop loss tertrigger.
- **Impact:** Nilai proksi `mfe` terdistorsi positif (+0.85% s/d +5.06%) pada posisi yang langsung stop out di Hari ke-1.
- **Resolution:** Menetapkan `bar_high_proxy = bar_high_lower` (harga pembukaan $Open$ untuk entri reguler, atau harga entri $P_{\text{entry}}$ untuk entri breakout). Proksi MFE pada 6 trade SL Hari ke-1 bernilai tepat 0.00% (`mfe == mfe_min`).
- **Residual risk:** Tidak ada. Diuji pada 5 unit tests dan diverifikasi pada `scripts/audit_historical_outcomes.py`.

### F4 — Semantik Time-to-Peak Deterministik vs Urutan Intraday Tak Pasti

- **Severity:** `MEDIUM`
- **Status:** `CONFIRMED`
- **Evidence:** `python/outcomes/engine.py:time_to_peak`, `tests/unit/test_outcomes.py:test_regression_time_to_peak_when_exit_day_high_is_uncertain`
- **Root cause:** Candle exit yang mengalami pergerakan harga di atas open sebelum stop loss tidak dapat diverifikasi secara kausal tanpa data tick intraday.
- **Impact:** `time_to_peak` berisiko menunjuk ke lilin keluar pasca-stop.
- **Resolution:** `time_to_peak` didefinisikan secara deterministik sebagai indeks holding day dari harga tertinggi in-trade observabel terkonfirmasi (`highest_high_proxy`). Lonjakan exit candle yang tak terkonfirmasi diabaikan dan disimpan terpisah pada Scope B (`full_horizon_time_to_peak`).
- **Residual risk:** Tidak ada.

### F5 — Ekskursi Rentang Penuh Candle pada Modeled Close Exit (Ambiguous Policy)

- **Severity:** `MEDIUM`
- **Status:** `CONFIRMED`
- **Evidence:** `python/outcomes/engine.py`, `tests/unit/test_outcomes.py:test_regression_ambiguous_policy_candle_touching_both_barriers`
- **Root cause:** Model keluar di harga penutupan ($Close$) pada lilin tabrakan barrier ganda, namun sebelumnya ekskursi dibatasi pada barrier.
- **Impact:** Inkonsistensi semantik antara status keluar di close dengan rentang harga yang dialami posisi.
- **Resolution:** Menyelaraskan ekskursi in-trade merepresentasikan $[Low, High]$ penuh candle exit (`bar_high_proxy = bar.high`, `bar_low_proxy = bar.low`).
- **Residual risk:** Tidak ada.

### F6 — Pre-Entry Gap Invalidation (`INVALIDATED_GAP` Case Studies: `BYAN`, `ASII`, `BBCA`)

- **Severity:** `HIGH`
- **Status:** `CONFIRMED`
- **Evidence:** `BYAN` (2026-08-18), `ASII` (2026-10-09), `BBCA` (2026-10-09)
- **Root cause:** Sinyal yang membuka di bawah SL atau di atas TP pada Hari ke-1 sebelumnya dianggap trade terisi yang langsung keluar di pembukaan yang sama (memproduksi trade fiktif return 0.00% gross dan -50 bps net).
- **Impact:** Mendistorsi win rate dan expectancy dengan kerugian transaksi buatan.
- **Resolution:** Menetapkan status `INVALIDATED_GAP` (`entry_status = 'UNFILLED'`, `holding_days = 0`, metrik Scope A bernilai `NULL`). Mengeliminasi lookahead bias dengan tetap membentuk sinyal di Hari ke-0 close dan membatalkannya di pra-pembukaan Hari ke-1.
- **Residual risk:** Tidak ada.

---

## 6. Files and Data Changed

| Path | Change | Reason | Migration/backfill |
|---|---|---|---|
| `audit_report.md` | Restrukturisasi ke template 10 bagian, sinkronisasi metrik Executive Summary dengan Section 3.4, koreksi kolom `outcomes_daily` menjadi 47 kolom | Final documentation reconciliation | No |
| `summary.md` | Penambahan log entry 49 (append-only) | Kepatuhan aturan pencatatan histori proyek | No |
| `walkthrough.md` | Pembaharuan rincian tugas dan testing checklist | Dokumentasi sesi kerja terkini | No |

- Raw market data modified: **NO**
- Model artifacts modified: **NO**
- Champion/challenger status changed: **NO**
- Production thresholds changed: **NO**
- Live trading/deployment enabled: **NO**

---

## 7. Verification Evidence

| Check | Command/method | Result | Evidence |
|---|---|---|---|
| Unit/integration tests | `.venv\Scripts\python.exe -m pytest` | **PASSED** (444 passed in 110s) | Seluruh 444 tests lulus 100%, termasuk 61 tests di `test_outcomes.py` |
| Linter | `.venv\Scripts\ruff.exe check .` | **PASSED** | 100% clean, `All checks passed!` |
| Database integrity | `.venv\Scripts\python.exe scripts/audit_historical_outcomes.py` | **PASSED** | 31 rekor diverifikasi, 0 pelanggaran invarian/bounds |
| Historical spot checks | Kueri SQL mandiri pada 27 trade terisi | **PASSED** | Mean Gross: -0.1714%, Mean Net: -0.6695%, Expectancy: -66.95 bps, Hold: 4.48d |
| Idempotency | `scripts/resolve_outcomes.py --force-recompute --save-db` | **PASSED** | Rekomputasi berulang mempertahankan 31 rekor identik tanpa mutasi |

---

## 8. Known Limitations

| Limitation | Why it matters | Impact | Follow-up |
|---|---|---|---|
| Resolusi Bar Harian OHLC (Tick Sequence Absence) | Data harian tidak memiliki cap waktu sub-menit untuk menentukan urutan intraday | Ekstrem exit candle (High vs Low) tidak dapat diurutkan dengan kepastian 100% | Bounded interval $[MFE_{\min}, MFE_{\max}]$ dan proksi konservatif lower-bound mengeliminasi bias optimis |
| Ukuran Sampel Matured Historis Terbatas ($N=27$ filled) | Sampel sinyal historis awal masih terbatas pada 31 sinyal matured (27 trade terisi) | Nilai expectancy -66.95 bps mencerminkan sampel awal sebelum ekspansi multi-horizon | Evaluasi semesta yang lebih besar pada Phase 10 (Multi-Horizon & Walk-Forward Testing) |
| Model Friksi Transaksi Statis (50 bps) | Asumsi komisi tetap 40 bps round-trip dan slippage 10 bps round-trip | Saham dengan likuiditas sangat tinggi vs sangat rendah mungkin memiliki slippage riil yang sedikit berbeda | Model slippage dinamis berbasis likuiditas dapat dipertimbangkan pada modul eksekusi live mendatang |

---

## 9. Reproducibility

- **Commands to reproduce:**
  ```powershell
  .venv\Scripts\python.exe -m pytest
  .venv\Scripts\ruff.exe check .
  .venv\Scripts\python.exe scripts/audit_historical_outcomes.py
  .venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect('datasets/stock_signals.db'); c = conn.cursor(); c.execute('SELECT COUNT(*), AVG(gross_return), AVG(net_return), AVG(holding_days) FROM outcomes_daily WHERE entry_status=\'FILLED\''); print(c.fetchone())"
  ```
- **Required configuration:** Python 3.12 venv, SQLite database di `datasets/stock_signals.db`.
- **Data snapshot/version:** 31 matured historical records (snapshot per 2026-10-12).
- **Expected results:**
  - Pytest: 444 passed in ~110s.
  - Ruff: `All checks passed!`.
  - Historical audit: 31 records verified, 0 violations.
  - Database calculation: Mean Gross -0.00171376 (-0.1714%), Mean Net -0.00669473 (-0.6695%), Expectancy -66.95 bps, Hold 4.48 days.
- **Evidence files:**
  - [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py)
  - [`scripts/audit_historical_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/audit_historical_outcomes.py)
  - [`datasets/stock_signals.db`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/datasets/stock_signals.db)

---

## 10. Final Decision and Next Step

- **Current stage completed:** `YES`
- **Can the next stage begin?** `YES`
- **Required blockers:** `None`
- **Next approved task:** `Roadmap Phase 10: Multi-Horizon Evaluation & Feature Ablation Experiments`
- **Explicitly prohibited changes:**
  - Dilarang mengaktifkan live trading / deployment riil ke bursa.
  - Dilarang mempromosikan atau mengganti model champion tanpa tinjauan komite tata kelola.
  - Dilarang melonggarkan ambang batas probabilitas BUY atau batas friksi EV Gate (50 bps).
  - Dilarang memodifikasi harga mentah pada tabel `daily_bars`.
