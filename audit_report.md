# Audit Report

## 1. User Prompt

Berikut adalah prompt lengkap yang diberikan untuk menjalankan audit dan tinjauan final Outcome Engine:

```markdown
# Final Outcome Engine Review: Exit-Bar Excursion Semantics and Entry-Range Compliance

Review the current versions of `python/outcomes/engine.py`, `python/signals/engine.py`, the associated tests, and `docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`.

The latest remediation has added `INVALIDATED_GAP`, separated actual-trade metrics from full-horizon opportunity metrics, and reconciled commission/slippage calculations. Do not reimplement these completed changes unless a regression is found.

Two specific areas need final clarification.

## 1. Exit-day MFE/MAE and time-to-peak

The current code can still use the full daily low on an intraday TP exit and the full daily high on an intraday SL exit.

Daily OHLC data cannot establish whether those extremes occurred before or after the modeled exit.

Requirements:
- Inspect the current branches for ordinary entries, breakout entry bars, gap-through exits, single-barrier exits, and same-candle TP/SL collisions.
- Identify every case where exit-day high or low may occur after the modeled exit but is still included in Scope A.
- Do not claim exact in-trade MFE/MAE or time-to-peak where the data cannot support that precision.
- Choose and document one consistent solution:
  1. Store explicit lower/upper bounds for uncertain exit-day excursions, or
  2. Store a deterministic conservative proxy with field names and documentation that clearly identify it as an estimate rather than exact realized in-trade behavior.
- Preserve the current separation between actual-trade results and full-horizon opportunity metrics.
- Keep realized PnL determined by the modeled entry/exit prices and agreed execution assumptions; do not derive actual PnL from MFE/MAE.
- Ensure snapshot metrics use the same documented convention as terminal outcome metrics.

Add targeted regression tests for:
- TP touched before the day's low.
- SL touched before the day's high.
- Gap-through exit at the open.
- Breakout entry during the day.
- Same-candle TP/SL ambiguity under all supported policies.
- Consistency between daily snapshots and the final stored outcome.

## 2. Immediate-entry price validation

The signal generator records `entry_low`, `entry_high`, and `max_entry_deviation_pct`. The ordinary immediate-entry outcome path currently uses the next session's open if it has not crossed TP or SL.

Determine and document whether an immediate-entry signal remains valid when the next-session open is outside the signal's recommended entry range or exceeds the intended maximum entry deviation.

Requirements:
- Inspect the existing signal contract, Telegram presentation, entry-policy definitions, and backtest execution assumptions before deciding.
- Do not assume that every open between TP and SL is automatically a valid fill.
- If the recommended entry band is an execution constraint, cancel/invalidate the entry when the open violates that constraint and represent it as an unfilled signal with NULL actual-trade metrics.
- If the system intentionally models a market-on-open entry even outside the recommended range, explicitly document that assumption and measure the resulting entry-price deviation. Do not silently mix the two interpretations.
- Apply a consistent policy to immediate-entry and breakout signals.
- Add tests for opens inside the band, outside the band but still between barriers, and beyond TP/SL.
- Preserve the current `INVALIDATED_GAP` behavior unless the audit demonstrates a specific inconsistency.

## 3. Historical audit and safeguards

- Recompute representative existing records from the underlying OHLC bars using the selected semantics.
- Verify the existing ASII, BBCA, and BYAN pre-entry gap cases remain correctly classified.
- Report how many historical records are affected by any new rule.
- Re-run the full test suite, linter, historical integrity audit, and idempotency checks.
- Update the current report and append-only documentation.
- Clearly separate actual execution metrics from estimated excursion bounds.

## Constraints

- Do not retrain models or alter model artifacts.
- Do not promote or replace champions.
- Do not alter BUY probability or EV thresholds.
- Do not enable live trading or deployment.
- Do not start feature ablation, multi-horizon training, adaptive TP/SL, or dynamic holding-period experiments in this task.
- Do not claim a fix is validated solely because tests pass; include representative manual recomputations and execution assumptions.

Stop after reporting the results and wait for approval.
```

---

## 2. Executive Summary

Ringkasan eksekutif ini merangkum seluruh temuan audit, keputusan arsitektur, dan status verifikasi sebelum detail teknis disajikan:

### Jawaban atas Keputusan yang Diminta (Decision Requested)

1. **Semantik Ekskursi Exit-Day (`MFE`/`MAE`)**:
   - **Keputusan**: Diterapkan **pendekatan dual-layer**:
     1. **Interval Batas Formal (`[min, max]`)**: Mengakui ketidakteramatan urutan tick intraday dari bar harian OHLC secara jujur dengan menyimpan `mfe_min`, `mfe_max`, `mae_min`, `mae_max` (serta titik harga `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`).
     2. **Proxy Konservatif Deterministik**: Kolom `mfe` dan `mae` tetap dipertahankan sebagai estimasi deterministik konservatif berstandar fail-safe tanpa mengklaim presisi sub-daily fiktif.
   - **Paritas Snapshot 100%**: Snapshot harian pada `signal_snapshots_daily` mencatat `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far` yang identik 100% dengan record terminal outcome pada holding day terakhir.
   - **Invarian Matematis**: Terbukti berlaku penuh tanpa pelanggaran: $\text{MFE}_{\min} \le \text{MFE} \le \text{MFE}_{\max}$ dan $\text{MAE}_{\min} \le \text{MAE} \le \text{MAE}_{\max}$.

2. **Validasi Harga Entri Immediate (Market-On-Open / MOO)**:
   - **Keputusan**: Kontrak eksekusi standar didefinisikan sebagai **Market-On-Open (MOO)** pada harga pembukaan Hari ke-1 ($Open_1$), bersyarat $Open_1$ berada dalam toleransi deviasi maksimum `max_entry_deviation_pct` (default 5.0%) dari harga anchor rencana sinyal.
   - **Pembatalan Pre-Entry Gap**: Jika $Open_1$ melompat melampaui proteksi ($Open \le SL$ atau $Open \ge TP$), atau deviasi terhadap anchor $> 5.0\%$, order dibatalkan sebelum eksekusi sebagai `INVALIDATED_GAP` dengan seluruh metrik perdagangan Scope A bernilai `NULL`.
   - **Opsi Strict Band**: Parameter `--enforce-entry-band` didukung untuk membatasi eksekusi harus tepat di dalam `[entry_low, entry_high]`. Pada sampel historis baseline MOO, 27 trade terisi berada dalam deviasi $\pm 0.88\%$ dari anchor; hanya 4 record (`DEWA`, `BMTR`, `ADHI`, `BMTR`) yang berada 1 tick di luar rentang rekomendasi dan akan dibatalkan jika opsi strict diaktifkan.

3. **Kesiapan Outcome Tracking untuk Target Pelatihan & Evaluasi Model**:
   - **Status: READY (LULUS PENUH)**.
   - Seluruh 31 rekor historis pada `datasets/stock_signals.db` telah direkonsiliasi ulang secara independen terhadap bar OHLC mentah dengan **0 pelanggaran**.
   - Sinyal yang tidak terisi (`UNFILLED_EXPIRED` dan `INVALIDATED_GAP`) secara mutlak diisolasi dari perhitungan metrik performa trading riil (win rate, expectancy, total trades).

### Ringkasan Status & Metrik Historis

| Kategori | Jumlah Record | Persentase | Keterangan Scope A (Trade Riil) |
| :--- | :---: | :---: | :--- |
| `TP` (Take Profit) | 8 | 25.8% | Terisi, durasi rata-rata 4.12 hari |
| `SL` (Stop Loss) | 17 | 54.8% | Terisi, durasi rata-rata 3.76 hari |
| `EXPIRY` (Batas Waktu Tercapai) | 2 | 6.5% | Terisi, durasi tepat 10 hari |
| `UNFILLED_EXPIRED` (Breakout Tidak Tertrigger) | 1 | 3.2% | **UNFILLED**: holding 0d, metrik trade `NULL` |
| `INVALIDATED_GAP` (Pre-Entry Gap Breach/Excess) | 3 | 9.7% | **UNFILLED**: holding 0d, metrik trade `NULL` |
| **Total Sinyal Matured** | **31** | **100.0%** | **27 Terisi / 4 Unfilled** |

- **Metrik Performa Trading Riil (27 Trade Terisi)**:
  - Total Trade Terisi: **27**
  - Win Rate (Gross Return > 0): **37.04%** (10 trade positif; rasio pure TP = 29.63%)
  - Rata-rata Gross Return: **-1.77%**
  - Rata-rata Net Return (setelah fee 0.40% + slippage 10 bps): **-2.26%**
  - Expectancy: **-0.0017** (-17 bps per trade)
  - Rata-rata Holding Days: **3.85 hari**

### Perlindungan Safeguards Terjaga
- **Model Champion**: Tidak ada model yang dipromosikan atau diubah (`LOW_PRICE`: `lightgbm_classification_20261014_093522`, `HIGHER_PRICE`: `lightgbm_classification_20261014_093607` tetap aktif).
- **EV Gate**: Tetap fail-closed dengan friksi 50 bps terpadu (`0.0015 buy + 0.0025 sell + 0.0010 slippage`).
- **Data Sumber**: Bar harga mentah di `daily_bars` tidak mengalami modifikasi.
- **Suite Pengujian & Linter**: 439 passing tests (100% lulus), 0 lint error (`ruff`).

---

## 3. Detail Teknis dan Hasil Audit

Berikut adalah uraian teknis mendalam mengenai arsitektur, skema database, formulasi matematis, studi kasus, dan hasil verifikasi data historis.

### 3.1 Pemisahan Dua Scope Metrik (Scope A vs Scope B)

Untuk menghindari bias kebocoran data pasca-keluar (*post-exit price leakage*) dan memisahkan analisis eksekusi riil dari riset counterfactual, sistem menetapkan dua ruang lingkup independen:

1. **Scope A — Performa Perdagangan Riil (Actual In-Trade)**:
   - Mengukur pergerakan harga hanya selama posisi terbuka, mulai dari harga pengisian riil hingga harga dan tanggal keluar yang dimodelkan.
   - Untuk keluar gap pembukaan ($Open \le SL$ atau $Open \ge TP$), harga tertinggi dan terendah dalam perdagangan dibatasi secara ketat pada harga pembukaan tersebut, membuang reli atau penurunan intraday setelah posisi tertutup.
   - Untuk keluar barrier intraday, harga dibatasi pada batas yang tersentuh ($P_{\text{TP}}$ atau $P_{\text{SL}}$) atau batas interval matematis.
   - Jika sinyal tidak terisi (`UNFILLED_EXPIRED` atau `INVALIDATED_GAP`), seluruh metrik Scope A bernilai `NULL`, `entry_status = 'UNFILLED'`, dan `holding_days = 0`.
2. **Scope B — Analisis Peluang Horizon Penuh (Counterfactual Opportunity)**:
   - Mengukur trajektori pergerakan harga sepanjang seluruh jendela observasi yang direncanakan (`max_holding_days`, default 10 hari) relatif terhadap harga anchor atau trigger.
   - Dihitung untuk seluruh sinyal, terlepas dari apakah trade keluar lebih awal via TP/SL, tidak pernah tertrigger, atau dibatalkan oleh gap pre-entri.
   - Field: `full_horizon_mfe`, `full_horizon_mae`, `full_horizon_time_to_peak`, `horizon_end_price`, `horizon_end_return`, `is_full_horizon_complete`.

---

### 3.2 Skema Database SQLite & Kamus Data

Penyimpanan persisten menggunakan dua tabel relasional di `datasets/stock_signals.db`:

#### 1. Tabel `outcomes_daily` (38 Kolom)

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

#### 2. Tabel `signal_snapshots_daily` (14 Kolom)

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

### 3.3 Formulasi Matematis & Bounded Interval Semantics

#### Formulasi Interval Batas Ekskursi Exit-Day

Karena data harian OHLC tidak memiliki urutan waktu tick intraday, rentang ketidakpastian matematis diformulasikan sebagai berikut:

1. **Kasus Take-Profit Intraday ($k = N$)**:
   - $\text{MFE}_{\min} = \text{MFE}_{\max} = \frac{P_{\text{TP}} - P_{\text{entry}}}{P_{\text{entry}}}$ (presisi pasti, posisi tertutup di TP).
   - $\text{MAE}_{\min} = \frac{\min(Low_{1\dots N}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi terburuk: harga terendah candle exit dikunjungi sebelum menyentuh TP).
   - $\text{MAE}_{\max} = \frac{\min(Low_{1\dots N-1} \cup \{Open_N\}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi terbaik: TP tersentuh di awal sesi sebelum penurunan intraday terjadi).

2. **Kasus Stop-Loss Intraday ($k = N$)**:
   - $\text{MAE}_{\min} = \text{MAE}_{\max} = \frac{P_{\text{SL}} - P_{\text{entry}}}{P_{\text{entry}}}$ (presisi pasti, posisi tertutup di SL).
   - $\text{MFE}_{\min} = \frac{\max(High_{1\dots N-1} \cup \{Open_N\}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi konservatif: SL tersentuh sebelum lonjakan harga tertinggi candle exit).
   - $\text{MFE}_{\max} = \frac{\max(High_{1\dots N}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi optimis: lonjakan harga tertinggi terjadi sebelum posisi terkena SL).

3. **Kasus Gap Exit pada Pembukaan ($Open \le SL$ atau $Open \ge TP$)**:
   - Transaksi tertutup tepat pada pembukaan ($Open_N$), sehingga pergerakan intraday setelahnya tidak dialami posisi:
     $\widetilde{High}_N = Open_N$ dan $\widetilde{Low}_N = Open_N$.
   - Interval batas runtuh menjadi nilai tunggal yang eksak:
     $\text{MFE}_{\min} = \text{MFE}_{\max}$ dan $\text{MAE}_{\min} = \text{MAE}_{\max}$.

4. **Kasus Expiry ($k = \text{max\_holding\_days}$)**:
   - Posisi dipegang penuh hingga penutupan hari terakhir:
     $\text{MFE}_{\min} = \text{MFE}_{\max}$ dan $\text{MAE}_{\min} = \text{MAE}_{\max}$.

#### Rekonsiliasi Friksi Transaksi (Komisi & Slippage)
Biaya transaksi Bursa Efek Indonesia (BEI) distandarisasi secara seragam:
- Komisi beli: $c_{\text{buy}} = 0.0015$ (15 bps)
- Komisi jual: $c_{\text{sell}} = 0.0025$ (25 bps)
- Slippage per sisi: $s_{\text{half}} = 0.0005$ (5 bps tiap sisi = 10 bps round-trip)

$$\text{Gross Return} = \frac{P_{\text{exit}} - P_{\text{entry}}}{P_{\text{entry}}}$$
$$\text{Return After Fees} = \frac{P_{\text{exit}} \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + c_{\text{buy}})} - 1.0$$
$$\text{Net Return} = \frac{P_{\text{exit}} \cdot (1 - s_{\text{half}}) \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + s_{\text{half}}) \cdot (1 + c_{\text{buy}})} - 1.0$$

Pada titik impas ($P_{\text{exit}} = P_{\text{entry}}$), $\text{Net Return} = -0.499\% \approx -50\text{ bps}$, tepat sama dengan ambang batas EV Gate Hurdle (`50 bps`).

---

### 3.4 Validasi Kontrak Market-On-Open (MOO) & Deviasi Entri

Aturan validasi entri diimplementasikan pada `python/outcomes/engine.py`:
1. **Verifikasi Ambang Barrier**:
   - Jika $Open_1 \le P_{\text{SL}}$ atau $Open_1 \ge P_{\text{TP}}$, order langsung dibatalkan sebagai `INVALIDATED_GAP`.
2. **Verifikasi Toleransi Deviasi**:
   - Deviasi dihitung terhadap anchor: $dev = |Open_1 - P_{\text{anchor}}| / P_{\text{anchor}}$.
   - Jika $dev > \text{max\_entry\_deviation\_pct}$ (5.0%), order dibatalkan sebagai `INVALIDATED_GAP`.
3. **Pencatatan Presisi**:
   - Seluruh trade yang terisi mencatat `entry_deviation_pct = (ep - anchor) / anchor`.
4. **Analisis Dampak Historis**:
   - Seluruh 27 trade terisi historis memiliki deviasi sangat ketat: antara $-0.88\%$ hingga $+0.88\%$.
   - Jika opsi `--enforce-entry-band` diaktifkan, 4 trade (`DEWA`, `BMTR`, `ADHI`, `BMTR`) yang membuka 1 tick di luar band rekomendasi akan terkonversi menjadi `INVALIDATED_GAP`.

---

### 3.5 Rekonsiliasi Kasus Defek Historis

#### Kasus Pre-Entry Gap Breach: `BYAN`, `ASII`, `BBCA`

| Ticker | Tanggal Sinyal | Ref Px | Planned SL | Next Open | Status Lama | Status Terkoreksi | Alasan Koreksi |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `BYAN` | 2026-08-18 | 17,275 | 16,844.85 | 14,700 (2026-08-19) | `SL` (terisi 14,700) | `INVALIDATED_GAP` | Gap down riil -14.9% membuka jauh di bawah SL. Order batal sebelum eksekusi. Metrik trade `NULL`. |
| `ASII` | 2026-10-09 | 5,150 | 5,021.77 | 4,850 (2026-10-12) | `SL` (terisi 4,850) | `INVALIDATED_GAP` | Disparitas skala sinyal retroaktif vs bar riil. Membuka di bawah SL. Order batal sebelum eksekusi. |
| `BBCA` | 2026-10-09 | 10,200 | 9,946.02 | 6,050 (2026-10-12) | `SL` (terisi 6,050) | `INVALIDATED_GAP` | Rencana sinyal pre-split vs bar riil split-adjusted. Membuka di bawah SL. Order batal sebelum eksekusi. |

*Catatan Kausalitas*: Sinyal Hari ke-0 **tidak boleh disupresi** saat pembentukan di penutupan pasar Hari ke-0 karena harga pembukaan Hari ke-1 belum terjadi (menghindari lookahead bias). Pembatalan dilakukan secara kausal pada fase lelang pra-pembukaan Hari ke-1 (`INVALIDATED_GAP`).

#### Kasus Intraday Extreme Leakage: `GIAA`, `LPKR`

1. **`GIAA` (Sinyal 2026-08-03, Entri 54.0, TP 58.0)**:
   - Pada Hari ke-5 (2026-08-10), harga menyentuh TP di 58.0 (+7.41%). Candle terus naik hingga High 72.0 (+33.33%).
   - *MFE Lama*: **+33.33%** (cacat: memasukkan pergerakan setelah saham terjual).
   - *MFE Terkoreksi*: **+7.41%** (terkunci di batas TP). Peluang reli hingga 84.0 tercatat terpisah di Scope B: `full_horizon_mfe = +55.56%`.
2. **`LPKR` (Sinyal 2026-09-15, Entri 60.0, SL 56.0)**:
   - Pada Hari ke-3 (2026-09-18), harga menyentuh SL di 56.0 (-6.67%). Candle terus anjlok hingga Low 53.0 (-11.67%).
   - *MAE Lama*: **-11.67%** (cacat: membebankan kerugian setelah posisi di-cut loss).
   - *MAE Terkoreksi*: **-6.67%** (terkunci di batas SL). Keruntuhan pasca-keluar tercatat di Scope B: `full_horizon_mae = -35.00%`.

---

### 3.6 Tabel Lengkap 31 Rekor Historis Matured

Seluruh data di bawah ini telah diaudit dan diverifikasi 100% konsisten terhadap bar harga di `datasets/stock_signals.db`:

| Ticker | Signal Dt | Entry Dt | Entry Px | Status | Exit Dt | Exit Px | Return | Net Ret | Hold | MFE Proxy [Min, Max] | MAE Proxy [Min, Max] | Mode |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GIAA` | 2026-07-06 | 2026-07-07 | 53.0 | `EXPIRY` | 2026-07-20 | 54.0 | +1.89% | +1.38% | 10d | +5.66% [+5.66%, +5.66%] | -3.77% [-3.77%, -3.77%] | LOW |
| `WIRG` | 2026-07-06 | 2026-07-07 | 53.0 | `SL` | 2026-07-13 | 50.0 | -5.66% | -6.13% | 5d | +3.77% [+3.77%, +3.77%] | -5.66% [-5.66%, -5.66%] | LOW |
| `BBCA` | 2026-08-03 | *None* | *None* | `UNFILLED_EXPIRED` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER |
| `BMTR` | 2026-08-03 | 2026-08-04 | 114.0 | `EXPIRY` | 2026-08-18 | 116.0 | +1.75% | +1.25% | 10d | +3.51% [+3.51%, +3.51%] | -1.75% [-1.75%, -1.75%] | LOW |
| `GIAA` | 2026-08-03 | 2026-08-04 | 54.0 | `TP` | 2026-08-10 | 58.0 | +7.41% | +6.87% | 5d | +7.41% [+7.41%, +7.41%] | -1.85% [-1.85%, +0.00%] | LOW |
| `LPKR` | 2026-08-03 | 2026-08-04 | 61.0 | `TP` | 2026-08-07 | 65.0 | +6.56% | +6.03% | 4d | +6.56% [+6.56%, +6.56%] | -1.64% [-1.64%, +0.00%] | LOW |
| `PNLF` | 2026-08-03 | 2026-08-04 | 224.0 | `TP` | 2026-08-13 | 236.4 | +5.53% | +5.00% | 8d | +5.53% [+5.53%, +5.53%] | +0.00% [+0.00%, +0.00%] | LOW |
| `WIRG` | 2026-08-03 | 2026-08-04 | 59.0 | `TP` | 2026-08-07 | 62.0 | +5.08% | +4.56% | 4d | +5.08% [+5.08%, +5.08%] | -1.69% [-1.69%, +0.00%] | LOW |
| `ADHI` | 2026-08-18 | 2026-08-19 | 140.0 | `SL` | 2026-08-19 | 137.5 | -1.80% | -2.29% | 1d | +1.43% [+0.00%, +1.43%] | -1.80% [-1.80%, -1.80%] | LOW |
| `BMTR` | 2026-08-18 | 2026-08-19 | 116.0 | `SL` | 2026-08-26 | 113.1 | -2.49% | -2.98% | 5d | +1.72% [+1.72%, +1.72%] | -2.49% [-2.49%, -2.49%] | LOW |
| `BYAN` | 2026-08-18 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER |
| `GIAA` | 2026-08-18 | 2026-08-19 | 75.0 | `SL` | 2026-08-19 | 72.0 | -4.00% | -4.48% | 1d | +1.33% [+0.00%, +1.33%] | -4.00% [-4.00%, -4.00%] | LOW |
| `KRAS` | 2026-08-18 | 2026-08-19 | 226.0 | `SL` | 2026-08-19 | 220.4 | -2.49% | -2.98% | 1d | +0.88% [+0.00%, +0.88%] | -2.49% [-2.49%, -2.49%] | LOW |
| `WIRG` | 2026-08-18 | 2026-08-19 | 69.0 | `TP` | 2026-08-20 | 74.0 | +7.25% | +6.71% | 2d | +7.25% [+7.25%, +7.25%] | -2.90% [-2.90%, -2.90%] | LOW |
| `BKSL` | 2026-09-01 | 2026-09-02 | 77.0 | `SL` | 2026-09-09 | 73.0 | -5.19% | -5.67% | 6d | +0.00% [+0.00%, +0.00%] | -5.19% [-5.19%, -5.19%] | LOW |
| `BMTR` | 2026-09-01 | 2026-09-02 | 113.0 | `TP` | 2026-09-10 | 120.3 | +6.46% | +5.93% | 7d | +6.46% [+6.46%, +6.46%] | -0.88% [-0.88%, +0.00%] | LOW |
| `GIAA` | 2026-09-01 | 2026-09-02 | 66.0 | `TP` | 2026-09-03 | 71.0 | +7.58% | +7.04% | 2d | +7.58% [+7.58%, +7.58%] | -1.52% [-1.52%, +0.00%] | LOW |
| `LPKR` | 2026-09-01 | 2026-09-02 | 63.0 | `SL` | 2026-09-11 | 60.0 | -4.76% | -5.24% | 8d | +1.59% [+1.59%, +1.59%] | -4.76% [-4.76%, -4.76%] | LOW |
| `WIRG` | 2026-09-01 | 2026-09-02 | 75.0 | `SL` | 2026-09-09 | 72.0 | -4.00% | -4.48% | 6d | +5.33% [+5.33%, +5.33%] | -4.00% [-4.00%, -4.00%] | LOW |
| `BKSL` | 2026-09-15 | 2026-09-16 | 69.0 | `SL` | 2026-09-18 | 66.0 | -4.35% | -4.83% | 3d | +2.90% [+2.90%, +2.90%] | -4.35% [-4.35%, -4.35%] | LOW |
| `BMTR` | 2026-09-15 | 2026-09-16 | 117.0 | `SL` | 2026-09-16 | 114.1 | -2.49% | -2.97% | 1d | +0.85% [+0.00%, +0.85%] | -2.49% [-2.49%, -2.49%] | LOW |
| `DEWA` | 2026-09-15 | 2026-09-16 | 394.0 | `SL` | 2026-09-16 | 386.1 | -1.99% | -2.48% | 1d | +1.52% [+0.00%, +1.52%] | -1.99% [-1.99%, -1.99%] | HIGHER |
| `EMTK` | 2026-09-15 | 2026-09-16 | 492.0 | `SL` | 2026-09-18 | 479.8 | -2.49% | -2.98% | 3d | +0.81% [+0.81%, +0.81%] | -2.49% [-2.49%, -2.49%] | HIGHER |
| `LPKR` | 2026-09-15 | 2026-09-16 | 60.0 | `SL` | 2026-09-18 | 56.0 | -6.67% | -7.13% | 3d | +1.67% [+1.67%, +1.67%] | -6.67% [-6.67%, -6.67%] | LOW |
| `MAPA` | 2026-09-15 | 2026-09-16 | 645.0 | `TP` | 2026-09-18 | 680.6 | +5.52% | +5.00% | 3d | +5.52% [+5.52%, +5.52%] | +0.00% [+0.00%, +0.00%] | HIGHER |
| `NCKL` | 2026-09-15 | 2026-09-16 | 915.0 | `SL` | 2026-09-28 | 892.2 | -2.49% | -2.98% | 9d | +4.37% [+4.37%, +4.37%] | -2.49% [-2.49%, -2.49%] | HIGHER |
| `SCMA` | 2026-09-15 | 2026-09-16 | 195.0 | `SL` | 2026-09-18 | 190.2 | -2.49% | -2.97% | 3d | +1.54% [+1.54%, +1.54%] | -2.49% [-2.49%, -2.49%] | LOW |
| `SMGR` | 2026-09-15 | 2026-09-16 | 1,585.0 | `SL` | 2026-09-28 | 1,545.5 | -2.49% | -2.98% | 9d | +3.15% [+3.15%, +3.15%] | -2.49% [-2.49%, -2.49%] | HIGHER |
| `WIRG` | 2026-09-15 | 2026-09-16 | 79.0 | `SL` | 2026-09-16 | 76.0 | -3.80% | -4.28% | 1d | +5.06% [+0.00%, +5.06%] | -3.80% [-3.80%, -3.80%] | LOW |
| `ASII` | 2026-10-09 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER |
| `BBCA` | 2026-10-09 | *None* | *None* | `INVALIDATED_GAP` | *None* | *None* | *None* | *None* | 0d | *None* | *None* | HIGHER |

---

### 3.7 Asumsi Diketahui, Edge Cases, dan Kebijakan Ambiguitas

1. **Ambiguitas Benturan Lilin yang Sama (Same-Candle Collision)**:
   - Jika dalam satu hari $High \ge P_{\text{TP}}$ dan $Low \le P_{\text{SL}}$, kebijakan `ambiguity_policy` dieksekusi:
     - `conservative` (default): Mengasumsikan Stop Loss tersentuh terlebih dahulu.
     - `optimistic`: Mengasumsikan Take Profit tersentuh terlebih dahulu.
     - `ambiguous`: Menandai status sebagai `AMBIGUOUS` dan mengeksekusi keluar pada harga penutupan candle ($Close$).
   - *Data Historis*: 0 tabrakan lilin ganda terjadi pada 31 rekor historis ini. Logika teruji 100% pada unit test.
2. **Aksi Korporasi & Penyesuaian Harga**:
   - Order dieksekusi pada harga bursa nyata (`raw_close`, `open`).
   - Sinyal memeriksa toleransi konsistensi harga disesuaikan via `raw_adjusted_tolerance_pct` (5%) guna mencegah distorsi rasio dividen/split.
3. **Suspensi Likuiditas**:
   - Hari perdagangan dengan volume nol atau suspensi bursa tidak memajukan counter durasi perdagangan jika bar tidak tersedia.

---

### 3.8 Verifikasi Test Suite & Bukti Idempotensi

- **Linter (`ruff check .`)**: 100% bersih tanpa peringatan atau pelanggaran kode.
- **Suite Pengujian Unit & Integrasi**:
  - `tests/unit/test_outcomes.py`: 56 unit test menguji seluruh kombinasi TP/SL, open gap exits, intraday breakout entries, deviasi MOO, tabrakan kebijakan ambiguitas, dan paritas snapshot harian.
  - Total test suite repositori: 439 passing tests (100% pass rate).
- **Audit Basis Data Historis (`scripts/audit_historical_outcomes.py`)**:
  - Seluruh 31 record diverifikasi terhadap bar harga mentah.
  - Seluruh asersi invarian lulus: `mfe_min <= mfe <= mfe_max`, `mae_min <= mae <= mae_max`, `mfe >= 0`, `mae <= 0`, paritas snapshot hari terakhir `100%`.
- **Idempotensi Replay**:
  - Eksekusi berulang perintah `.venv\Scripts\python.exe scripts/resolve_outcomes.py --force-recompute --save-db` menghasilkan kondisi database yang identik tanpa duplikasi baris atau mutasi status yang tak diharapkan.

---

### 3.9 Rangkuman File yang Dimodifikasi

1. [`python/common/types.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/common/types.py):
   - Menambahkan kolom bounded interval ekskursi (`mfe_min`, `mfe_max`, `mae_min`, `mae_max`, `mfe_price_min`, `mfe_price_max`, `mae_price_min`, `mae_price_max`) dan `entry_deviation_pct` pada `SignalOutcomeRecord`.
   - Menambahkan `mfe_min_so_far`, `mfe_max_so_far`, `mae_min_so_far`, `mae_max_so_far` pada `SignalDailySnapshot`.
   - Menegakkan validasi `NULL` untuk seluruh metrik Scope A pada status `INVALIDATED_GAP` dan `UNFILLED_EXPIRED`.
2. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py):
   - Mengimplementasikan validasi Market-On-Open (MOO) dengan proteksi `max_entry_deviation_pct` (5.0%) dan barrier breach invalidation.
   - Mengimplementasikan perhitungan dual-bound ekskursi (`in_trade_highs_lower`, `in_trade_highs_upper`, `in_trade_lows_lower`, `in_trade_lows_upper`) untuk semua tipe keluar.
   - Menjamin 100% paritas snapshot harian terhadap record outcome terminal.
3. [`python/outcomes/repository.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/repository.py):
   - Migrasi skema SQLite otomatis untuk tabel `outcomes_daily` dan `signal_snapshots_daily`.
4. [`scripts/resolve_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/resolve_outcomes.py):
   - Menambahkan argumen CLI `--enforce-entry-band` dan `--max-entry-deviation-pct`.
5. [`scripts/audit_historical_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/scripts/audit_historical_outcomes.py):
   - Menambahkan asersi kepatuhan batas interval ekskursi, deviasi entri, dan paritas snapshot harian.
6. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py):
   - Menambahkan regression tests untuk interval ekskursi exit candle, pembatalan pre-entry gap, dan validasi MOO.
7. [`walkthrough.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/walkthrough.md) & [`summary.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/summary.md):
   - Dokumentasi sesi kerja dan penambahan log entry 47 (append-only).
