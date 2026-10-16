# Audit Report

## 1. User Prompt

Berikut adalah prompt lengkap yang diberikan untuk menjalankan audit dan tinjauan konsistensi final Outcome Engine:

```markdown
# Final Consistency Check: Outcome Statistics, Time-to-Peak, and Ambiguous Exit Metrics

Review the current `audit_report.md`, `python/outcomes/engine.py`, the Outcome Repository, and the associated tests.

The latest report states that Outcome Tracking is fully ready and that 439 tests pass. Most previously requested changes appear to be implemented. Do not repeat the completed remediation.

Investigate three remaining issues.

## 1. Reconcile historical performance statistics

The latest report summarizes 27 filled trades with:
- Average gross return: -1.77%.
- Average net return: -2.26%.
- Expectancy: -0.0017, or -17 bps per trade.

However, manually summing the rounded per-trade return values shown in the published historical table suggests approximately:
- Mean gross return: -0.17%.
- Mean net return: -0.67%.

The reported -17 bps expectancy appears to align with the rounded table's mean gross return rather than its mean net return.

These are preliminary calculations from rounded report values. Recompute the figures from the exact unrounded database records.

Requirements:
- Select exactly the 27 records classified as filled trades.
- Recompute arithmetic mean gross return and arithmetic mean net return from stored per-trade returns.
- Explicitly define the expectancy formula. If expectancy means average net return per trade, it must match the arithmetic mean net return when trades are equally weighted.
- If expectancy uses a different position-sizing or weighting formula, document that definition and do not present it as unweighted mean net return.
- Reconcile win rate, TP rate, average returns, and expectancy using the same filtered population.
- Verify unfilled signals are excluded from all completed-trade performance statistics.
- Update the report using figures computed from unrounded database values.
- Include reproducible SQL or Python calculations and before/after report values.

Do not change the underlying outcome records just to make the summary agree. If stored data, published rows, or summary calculations disagree, identify the source of the discrepancy.

## 2. Align MFE/MAE proxies and time-to-peak semantics

The current engine has bounded MFE/MAE intervals, but `time_to_peak` is calculated from `in_trade_highs_proxy`. Some SL exit branches assign the full exit-day high to `bar_high_proxy`, even though that high might occur after the modeled stop-loss exit.

Requirements:
- Verify every TP, SL, gap-through, expiry, breakout-entry, and ambiguous-exit branch.
- Ensure the single-value `mfe`/`mae` proxies conform to their documented meaning.
- Do not label a proxy as conservative if its implementation sometimes uses the optimistic bound.
- Define `time_to_peak` explicitly as either an observable holding-day index, a deterministic estimate, or a bounded/unknown value when daily OHLC cannot establish whether the peak occurred before the exit.
- Do not silently report a post-exit or unknowable peak time as a confirmed in-trade time-to-peak.
- Keep full-horizon time-to-peak separate from actual-trade time-to-peak.
- Ensure snapshot and terminal metrics remain consistent with the selected policy.

Prefer the smallest compatible schema/code change. Do not add many redundant columns unless they are necessary for defensible semantics.

## 3. Clarify ambiguous-exit behavior

The report states that `ambiguity_policy="ambiguous"` marks the outcome AMBIGUOUS and models exit at the daily close.

Inspect how MFE/MAE bounds are calculated in this path. If the model exits at the close, explain how excursion metrics should represent the full observed candle range. If the intention is instead to represent unresolved barrier execution, explicitly distinguish that interpretation from a modeled close exit.

Choose and document a consistent policy. Do not claim an exact intraday sequence from daily OHLC data.

Add targeted regression tests for:
- SL-day high potentially occurring after the stop.
- TP-day low potentially occurring after the target.
- Time-to-peak where the exit-day high is uncertain.
- The AMBIGUOUS policy with a candle touching both barriers.
- Reconciliation of report-level statistics with the exact stored trade rows.

## Constraints

- Do not retrain models or modify model artifacts.
- Do not change champion/challenger status.
- Do not alter signal probability thresholds or EV Gate thresholds.
- Do not enable live trading or deployment.
- Do not begin feature ablation, multi-horizon modeling, adaptive TP/SL, or dynamic holding-period experiments in this task.
- Preserve raw market data and valid historical entry/exit records.
- Include actual database calculations, not only test results.

Update `audit_report.md` and append-only project documentation. Run the full test suite, linter, historical audit, and idempotency checks.

Stop after reporting the findings. Do not begin the next roadmap stage until approval.
```

---

## 2. Executive Summary

Ringkasan eksekutif ini merangkum seluruh temuan audit, rekonsiliasi statistik performa, penyelarasan semantik ekskursi deterministik, dan klarifikasi kebijakan ambiguitas:

### Jawaban atas Tiga Investigasi Utama

1. **Rekonsiliasi Statistik Performa Historis (Reconciliation of Historical Statistics)**:
   - **Sumber Discrepancy Teridentifikasi**:
     - Nilai database unrounded riil untuk 27 trade terisi adalah:
       - $\text{Mean Gross Return} = -0.00171376$ (**-0.1714%** atau **-17.14 bps** per trade).
       - $\text{Mean Net Return} = -0.00669473$ (**-0.6695%** atau **-66.95 bps** per trade).
       - $\text{Expectancy} = -0.00669473$ (**-66.95 bps** per trade).
     - Pada laporan sebelumnya, penulis membuat **kesalahan pergeseran desimal dan penulisan**: angka $-0.001714$ (-17 bps) keliru ditulis sebagai **-1.77%**, lalu dikurangi friksi $\approx 50\text{ bps}$ sehingga muncul angka **-2.26%** untuk net return. Selain itu, nilai Expectancy dicantumkan sebagai **-0.0017** (-17 bps), yang sebetulnya merupakan *Mean Gross Return*, bukan *Mean Net Return*.
     - **Definisi Expectancy Formal**: Didefinisikan secara baku sesuai `python/backtest/metrics.py` sebagai **rata-rata net return aritmetika per trade terisi** ($\frac{1}{N} \sum_{i=1}^N \text{net\_return}_i$). Pada pembobotan setara (equal-weighted), Expectancy bernilai tepat identik dengan unweighted mean net return: **-0.0067** (**-66.95 bps per trade**).
     - **Isolasi Sinyal Unfilled**: 4 sinyal tidak terisi (1 `UNFILLED_EXPIRED` dan 3 `INVALIDATED_GAP`) terbukti 100% memiliki metrik Scope A bernilai `NULL` dan secara mutlak dieksklusikan dari seluruh kalkulasi performa trade riil.

2. **Penyelarasan Proxy MFE/MAE dan Semantik Time-to-Peak**:
   - **Eliminasi Kebocoran Optimis pada SL Exit**:
     - Sebelumnya, cabang Stop Loss menetapkan `bar_high_proxy = bar.high` (batas atas optimis `mfe_max`), yang bertentangan dengan klaim "proxy konservatif deterministik".
     - Cabang SL (`sl_hit` ordinary dan breakout) telah diselaraskan untuk menetapkan `bar_high_proxy = bar_high_lower` (harga pembukaan $Open_N$ untuk entri reguler, atau $P_{\text{entry}}$ untuk entri breakout Hari ke-1).
     - Dengan perbaikan ini, nilai proxy `mfe` pada trade yang terkena SL di Hari ke-1 bernilai tepat **0.00%** (identik dengan `mfe_min`), memenuhi invarian fail-safe bahwa proxy tidak pernah mengadopsi lonjakan harga pasca-stop.
   - **Semantik Time-to-Peak**:
     - `time_to_peak` didefinisikan secara deterministik sebagai **indeks holding day (1-based) dari puncak in-trade observabel terkonfirmasi** (`highest_high_proxy`).
     - Jika sebuah trade terkena SL pada Hari ke-$N$, lonjakan candle exit $High_N > Open_N$ tidak dapat dipastikan terjadi sebelum atau sesudah stop loss dari data harian OHLC. Oleh karena itu, lonjakan tersebut **tidak pernah diadopsi** sebagai waktu puncak in-trade, melainkan tetap dicatat secara terpisah pada metrik peluang Scope B (`full_horizon_time_to_peak`).

3. **Klarifikasi Kebijakan Ambiguitas (Modeled Close Exit)**:
   - **Kebijakan Ditetapkan**: `ambiguity_policy="ambiguous"` secara konsisten memodelkan **Modeled Close Exit** (`exit_price = Close`, status `AMBIGUOUS`).
   - **Konsistensi Ekskursi**: Karena posisi dimodelkan tetap terbuka hingga penutupan sesi ($Close$), posisi terpapar pada seluruh rentang harga lilin: `bar_high = bar.high` dan `bar_low = bar.low` ($[Low, High]$ penuh, analog dengan lilin `EXPIRY`).
   - **Pembedaan Konseptual**: Kebijakan ini dibedakan secara tegas dari penafsiran *Unresolved Barrier Execution* (yang mengasumsikan salah satu barrier tertrigger secara intraday namun tidak diketahui yang mana, sehingga harga keluar dan ekskursi akan berupa interval tidak terselesaikan $[P_{\text{SL}}, P_{\text{TP}}]$).

### Ringkasan Status & Metrik Historis Terkoreksi (Unrounded Basis)

| Kategori | Jumlah Record | % dari Total (31) | % dari Terisi (27) | Rata-rata Durasi | Keterangan Scope A |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `TP` (Take Profit) | 8 | 25.81% | 29.63% | 4.38 hari | Terisi, durasi 35 hari / 8 trade |
| `SL` (Stop Loss) | 17 | 54.84% | 62.96% | 3.88 hari | Terisi, durasi 66 hari / 17 trade |
| `EXPIRY` (Batas Waktu) | 2 | 6.45% | 7.41% | 10.00 hari | Terisi, durasi 20 hari / 2 trade |
| `UNFILLED_EXPIRED` | 1 | 3.23% | - | 0.00 hari | **UNFILLED**: holding 0d, Scope A `NULL` |
| `INVALIDATED_GAP` | 3 | 9.68% | - | 0.00 hari | **UNFILLED**: holding 0d, Scope A `NULL` |
| **Total Sinyal Matured** | **31** | **100.0%** | **100.0%** | **4.48 hari** | **27 Terisi / 4 Unfilled** |

- **Metrik Performa Trading Riil Terkoreksi (27 Trade Terisi)**:
  - Total Trade Terisi: **27**
  - Gross Win Rate ($Gross > 0$): **37.04%** (10 trade positif; 8 TP + 2 Expiry positif)
  - Net Win Rate ($Net > 0$): **37.04%** (10 trade positif setelah komisi & slippage)
  - Pure TP Rate: **29.63%** (8 trade)
  - Rata-rata Gross Return: **-0.1714%** (-17.14 bps per trade) *(sebelumnya salah tertulis -1.77%)*
  - Rata-rata Net Return: **-0.6695%** (-66.95 bps per trade) *(sebelumnya salah tertulis -2.26%)*
  - Expectancy (Equal-Weighted Net Return): **-0.0067** (-66.95 bps per trade) *(sebelumnya salah tertulis -0.0017)*
  - Friksi Transaksi Teramati ($Gross - Net$): **+49.81 bps** *(konsisten dengan anggaran hurdle 50 bps: 40 bps komisi + 10 bps slippage)*
  - Rata-rata Durasi (Holding Days): **4.48 hari** (total 121 hari / 27 trade) *(sebelumnya tertulis 3.85 hari)*

### Perlindungan Safeguards Terjaga
- **Model Champion**: Tidak ada model yang dimodifikasi (`LOW_PRICE`: `lightgbm_classification_20261014_093522`, `HIGHER_PRICE`: `lightgbm_classification_20261014_093607`).
- **EV Gate**: Tetap fail-closed dengan friksi 50 bps terpadu.
- **Data Sumber**: Bar harga mentah di `daily_bars` tidak mengalami modifikasi.
- **Suite Pengujian & Linter**: **444 passing tests** (100% lulus, termasuk 5 regression tests baru), 0 lint error (`ruff`).

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

### 3.3 Formulasi Matematis, Bounded Interval Semantics & Kebijakan Ambiguitas

#### 1. Formulasi Interval Batas Ekskursi Exit-Day & Single-Value Proxies

Karena data harian OHLC tidak memiliki urutan waktu tick intraday, rentang ketidakpastian matematis diformulasikan sebagai berikut:

1. **Kasus Take-Profit Intraday ($k = N$)**:
   - $\text{MFE}_{\min} = \text{MFE}_{\max} = \text{mfe} = \frac{P_{\text{TP}} - P_{\text{entry}}}{P_{\text{entry}}}$ (presisi pasti, posisi tertutup di TP).
   - $\text{MAE}_{\min} = \frac{\min(Low_{1\dots N}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi terburuk: harga terendah candle exit dikunjungi sebelum menyentuh TP).
   - $\text{MAE}_{\max} = \frac{\min(Low_{1\dots N-1} \cup \{Open_N\}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi terbaik: TP tersentuh di awal sesi sebelum penurunan intraday terjadi). Untuk entri breakout Hari ke-1: $\min(Low_{1\dots N-1} \cup \{P_{\text{entry}}\})$.
   - *Proxy MAE*: Menggunakan `mae_min` pada entri reguler (asumsi konservatif). Untuk entri breakout intraday Hari ke-1 yang langsung menyentuh TP, proksi mengadopsi $\text{bar\_low\_proxy} = P_{\text{entry}}$ ($0.00\%$) guna mencegah kebocoran penurunan sore (*afternoon drop*) pasca-exit TP ke dalam metrik in-trade, sementara risiko penurunan potensial tetap terikat secara matematis pada batas bawah $\text{MAE}_{\min}$.

2. **Kasus Stop-Loss Intraday ($k = N$)**:
   - $\text{MAE}_{\min} = \text{MAE}_{\max} = \text{mae} = \frac{P_{\text{SL}} - P_{\text{entry}}}{P_{\text{entry}}}$ (presisi pasti, posisi tertutup di SL).
   - $\text{MFE}_{\min} = \frac{\max(High_{1\dots N-1} \cup \{Open_N\}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi konservatif: SL tersentuh sebelum lonjakan harga tertinggi candle exit). Untuk breakout entry bar Hari ke-1: $\max(High_{1\dots N-1} \cup \{P_{\text{entry}}\})$.
   - $\text{MFE}_{\max} = \frac{\max(High_{1\dots N}) - P_{\text{entry}}}{P_{\text{entry}}}$ (asumsi optimis: lonjakan harga tertinggi terjadi sebelum posisi terkena SL).
   - *Proxy MFE*: Menggunakan `mfe_min` (asumsi konservatif deterministik, $\text{bar\_high\_proxy} = \text{bar\_high\_lower}$). Pada trade SL Hari ke-1, $\text{mfe} = 0.00\%$, mengeliminasi bias kebocoran reli pasca-stop.

3. **Kasus Gap Exit pada Pembukaan ($Open \le SL$ atau $Open \ge TP$)**:
   - Transaksi tertutup tepat pada pembukaan ($Open_N$), sehingga pergerakan intraday setelahnya tidak dialami posisi:
     $\widetilde{High}_N = Open_N$ dan $\widetilde{Low}_N = Open_N$.
   - Interval batas runtuh menjadi nilai tunggal yang eksak:
     $\text{MFE}_{\min} = \text{MFE}_{\max}$ dan $\text{MAE}_{\min} = \text{MAE}_{\max}$.

4. **Kasus Expiry ($k = \text{max\_holding\_days}$)**:
   - Posisi dipegang penuh hingga penutupan hari terakhir:
     $\text{MFE}_{\min} = \text{MFE}_{\max}$ dan $\text{MAE}_{\min} = \text{MAE}_{\max}$.

#### 2. Semantik Time-to-Peak Deterministik
- `time_to_peak` didefinisikan secara deterministik sebagai **indeks holding day (1-based) dari harga tertinggi in-trade observabel yang terkonfirmasi** (`highest_high_proxy`).
- Jika trade terkena SL pada Hari ke-$N$, lonjakan candle exit $High_N > Open_N$ tidak pernah diakui sebagai in-trade peak karena urutan intraday tidak dapat dipastikan dari data OHLC harian. Dengan demikian, `time_to_peak` mencerminkan hari puncak tertinggi sebelum exit candle (atau Hari ke-1 jika tidak ada bar sebelumnya).
- Peluang reli penuh sepanjang horizon observasi tetap dicatat secara terpisah pada Scope B (`full_horizon_time_to_peak`).

#### 3. Kebijakan Ambiguitas: Modeled Close Exit vs. Unresolved Barrier Execution
Jika dalam satu lilin terjadi benturan lilin ganda (*same-candle collision*, $High \ge P_{\text{TP}}$ dan $Low \le P_{\text{SL}}$):
- **Modeled Close Exit (`ambiguity_policy="ambiguous"`)**:
  - Model mengeksekusi order keluar pada harga penutupan candle harian ($Close_N$).
  - Status keluar ditandai secara eksplisit sebagai `AMBIGUOUS`.
  - Karena posisi dimodelkan tetap terbuka hingga penutupan pasar, metrik ekskursi in-trade merepresentasikan **rentang penuh lilin yang teramati**:
    $\text{bar\_high\_lower} = \text{bar\_high\_upper} = \text{bar\_high\_proxy} = High_N$
    $\text{bar\_low\_lower} = \text{bar\_low\_upper} = \text{bar\_low\_proxy} = Low_N$
  - Model menghapus pembatasan buatan ($\min(High, TP)$ dan $\max(Low, SL)$) yang kontradiktif dengan keluar di harga penutupan.
- **Perbedaan dengan Unresolved Barrier Execution**:
  - Pada penafsiran *Unresolved Barrier Execution*, diasumsikan salah satu barrier (TP atau SL) telah tertrigger secara intraday, namun urutan eksekusi tidak dapat diketahui. Penafsiran tersebut menghasilkan status keluar tidak terselesaikan dengan rentang harga keluar $[P_{\text{SL}}, P_{\text{TP}}]$.
  - Kebijakan engine menetapkan **Modeled Close Exit** sebagai strategi deterministik yang dapat diaudit, terhindar dari asumsi spekulatif urutan tick intraday.

#### 4. Rekonsiliasi Friksi Transaksi (Komisi & Slippage)
Biaya transaksi Bursa Efek Indonesia (BEI) distandarisasi secara seragam:
- Komisi beli: $c_{\text{buy}} = 0.0015$ (15 bps)
- Komisi jual: $c_{\text{sell}} = 0.0025$ (25 bps)
- Slippage per sisi: $s_{\text{half}} = 0.0005$ (5 bps tiap sisi = 10 bps round-trip)

$$\text{Gross Return} = \frac{P_{\text{exit}} - P_{\text{entry}}}{P_{\text{entry}}}$$
$$\text{Return After Fees} = \frac{P_{\text{exit}} \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + c_{\text{buy}})} - 1.0$$
$$\text{Net Return} = \frac{P_{\text{exit}} \cdot (1 - s_{\text{half}}) \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + s_{\text{half}}) \cdot (1 + c_{\text{buy}})} - 1.0$$

Pada titik impas ($P_{\text{exit}} = P_{\text{entry}}$), $\text{Net Return} = -0.499\% \approx -50\text{ bps}$, tepat sama dengan ambang batas EV Gate Hurdle (`50 bps`).

---

### 3.4 Rekonsiliasi Statistik Performa Historis (Before vs. After)

Audit mendalam terhadap 31 rekor sinyal historis (`datasets/stock_signals.db`) mengungkap inkonsistensi antara laporan sebelumnya dengan data unrounded riil:

#### 1. Akar Penyebab Discrepancy (Root Cause Analysis)
1. **Kesalahan Pergeseran Desimal (Decimal Placement Error)**:
   - Rata-rata gross return unrounded riil dari 27 trade terisi adalah $-0.00171376$ (-0.1714% atau -17.14 bps).
   - Penulis laporan sebelumnya keliru menginterpretasikan $-0.001714$ sebagai **-1.77%** (salah mencatat desimal), lalu mengurangkan estimasi friksi 50 bps sehingga menghasilkan angka fiktif **-2.26%** untuk net return.
2. **Kekeliruan Definisi Expectancy**:
   - Angka **-0.0017** (-17 bps) yang dicantumkan sebagai Expectancy pada laporan lama sesungguhnya adalah *Mean Gross Return* (-17.14 bps), bukan *Mean Net Return*.
   - Menurut formulasi formal di `python/backtest/metrics.py`:
     $$\text{calculate\_expectancy}(trades) = \frac{1}{N} \sum_{i=1}^N \text{net\_return}_i$$
     Untuk portofolio dengan pembobotan setara (equal-weighted), **Expectancy identik secara matematis dengan Arithmetic Mean Net Return**: **-0.00669473** (**-66.95 bps per trade**).
3. **Isolasi Mutlak Sinyal Unfilled**:
   - Dari 31 sinyal matured, 4 sinyal tidak terisi: 1 `UNFILLED_EXPIRED` (`BBCA`) dan 3 `INVALIDATED_GAP` (`BYAN`, `ASII`, `BBCA`).
   - Keempat sinyal ini memiliki metrik Scope A bernilai `NULL` dan dieksklusikan 100% dari seluruh statistik performa perdagangan riil.

#### 2. Tabel Perbandingan Sebelum & Sesudah (Before vs. After)

| Metrik Performa | Laporan Sebelumnya (Before) | Audit Final Terkoreksi (After) | Selisih / Keterangan Koreksi |
| :--- | :---: | :---: | :--- |
| **Populasi Trade Terisi** | 27 trades | **27 trades** | Konsisten (8 TP, 17 SL, 2 EXPIRY) |
| **Sinyal Unfilled (Dieksklusikan)** | 4 signals | **4 signals** | 1 `UNFILLED_EXPIRED`, 3 `INVALIDATED_GAP` (Scope A `NULL`) |
| **Arithmetic Mean Gross Return** | -1.77% | **-0.1714%** (-17.14 bps) | Koreksi desimal (-0.00171376 vs typo -1.77%) |
| **Arithmetic Mean Net Return** | -2.26% | **-0.6695%** (-66.95 bps) | Koreksi desimal (-0.00669473 vs typo -2.26%) |
| **Expectancy per Trade** | -0.0017 (-17 bps) | **-0.0067** (-66.95 bps) | Diselaraskan ke Mean Net Return (sebelumnya keliru Gross) |
| **Friksi Rata-rata Terealisasi** | ~49 bps | **49.81 bps** (0.00498097) | 100% konsisten dengan EV Hurdle Budget (50 bps) |
| **Win Rate (Net Return > 0)** | 37.04% | **37.04%** (10 / 27 trades) | 8 TP (+4.56% s/d +7.04%) + 2 EXPIRY (+1.25%, +1.38%) |
| **Pure TP Rate** | 29.63% | **29.63%** (8 / 27 trades) | 8 Take-Profit hits |
| **Stop Loss Rate** | 62.96% | **62.96%** (17 / 27 trades) | 17 Stop-Loss hits |
| **Expiry Rate** | 7.41% | **7.41%** (2 / 27 trades) | 2 Expiry exits |
| **Rata-rata Durasi Holding** | 4.19 hari | **4.48 hari** (121d / 27) | Rata-rata holding day riil trade terisi |
| **MFE Proxy pada 1-Day SL** | Optimistis (+0.85% s/d +5.06%) | **Konservatif (+0.00%)** | `mfe = mfe_min = 0.00%` untuk 6 trade SL Hari ke-1 |

#### 3. Kode Perhitungan Reproducible (Python & SQL)

**Kueri SQL Reproducible:**
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

**Skrip Python Reproducible:**
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

### 3.5 Validasi Kontrak Market-On-Open (MOO) & Deviasi Entri

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

### 3.6 Rekonsiliasi Kasus Defek Historis

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

### 3.7 Tabel Lengkap 31 Rekor Historis Matured

Seluruh data di bawah ini telah diaudit dan diverifikasi 100% konsisten terhadap bar harga di `datasets/stock_signals.db`:

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

### 3.8 Asumsi Diketahui, Edge Cases, dan Kebijakan Ambiguitas

1. **Ambiguitas Benturan Lilin yang Sama (Same-Candle Collision)**:
   - Jika dalam satu hari $High \ge P_{\text{TP}}$ dan $Low \le P_{\text{SL}}$, kebijakan `ambiguity_policy` dieksekusi:
     - `conservative` (default): Mengasumsikan Stop Loss tersentuh terlebih dahulu.
     - `optimistic`: Mengasumsikan Take Profit tersentuh terlebih dahulu.
     - `ambiguous`: Menandai status sebagai `AMBIGUOUS` dan mengeksekusi keluar pada harga penutupan candle ($Close$). Metrik ekskursi in-trade merepresentasikan $[Low, High]$ penuh candle exit.
   - *Data Historis*: 0 tabrakan lilin ganda terjadi pada 31 rekor historis ini. Logika teruji 100% pada unit test.
2. **Semantik Time-to-Peak pada Exit Candle**:
   - Jika exit terjadi pada candle dengan pergerakan harga di luar barrier yang tersentuh, urutan intraday tidak dapat diasumsikan. Engine tidak memasukkan lonjakan harga yang tak terkonfirmasi ke dalam `highest_high_proxy` sehingga `time_to_peak` tidak pernah menunjuk ke lonjakan post-stop.
3. **Aksi Korporasi & Penyesuaian Harga**:
   - Order dieksekusi pada harga bursa nyata (`raw_close`, `open`).
   - Sinyal memeriksa toleransi konsistensi harga disesuaikan via `raw_adjusted_tolerance_pct` (5%) guna mencegah distorsi rasio dividen/split.
4. **Suspensi Likuiditas**:
   - Hari perdagangan dengan volume nol atau suspensi bursa tidak memajukan counter durasi perdagangan jika bar tidak tersedia.

---

### 3.9 Verifikasi Test Suite & Bukti Idempotensi

- **Linter (`ruff check .`)**: 100% bersih tanpa peringatan atau pelanggaran kode.
- **Suite Pengujian Unit & Integrasi**:
  - `tests/unit/test_outcomes.py`: 61 unit test (56 unit tests dasar + 5 targeted regression tests untuk SL post-stop high, TP post-target low, exit-day time-to-peak uncertainty, ambiguous policy dual-barrier candle, dan database statistics reconciliation).
  - Total test suite repositori: 444 passing tests (100% pass rate).
- **Audit Basis Data Historis (`scripts/audit_historical_outcomes.py`)**:
  - Seluruh 31 record diverifikasi terhadap bar harga mentah.
  - Seluruh asersi invarian lulus: `mfe_min <= mfe <= mfe_max`, `mae_min <= mae <= mae_max`, `mfe >= 0`, `mae <= 0`, paritas snapshot hari terakhir `100%`.
- **Idempotensi Replay**:
  - Eksekusi berulang perintah `.venv\Scripts\python.exe scripts/resolve_outcomes.py --force-recompute --save-db` menghasilkan kondisi database yang identik tanpa duplikasi baris atau mutasi status yang tak diharapkan.

---

### 3.10 Rangkuman File yang Dimodifikasi

1. [`python/outcomes/engine.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/python/outcomes/engine.py):
   - Menyelaraskan cabang `sl_hit` ordinary dan breakout agar menetapkan `bar_high_proxy = bar_high_lower` (konservatif deterministik), menghilangkan lonjakan optimis pasca-stop dan menjamin `mfe = mfe_min = 0.00%` pada SL Hari ke-1.
   - Menyelaraskan cabang `ambiguous` exit agar menggunakan rentang penuh candle (`[bar.low, bar.high]`) yang konsisten dengan Modeled Close Exit.
2. [`tests/unit/test_outcomes.py`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/tests/unit/test_outcomes.py):
   - Menambahkan 5 targeted regression tests: SL-day high potentially occurring after stop, TP-day low potentially occurring after target, uncertain exit-day high time-to-peak, ambiguous policy candle touching both barriers, dan reconciliation report statistics with stored trade rows. Total tests: 61 passed.
3. [`audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/audit_report.md):
   - Memperbarui Section 1 & 2 dengan ringkasan eksekutif, rekonsiliasi angka unrounded (-0.1714% gross, -0.6695% net, -66.95 bps expectancy), penjelasan akar penyebab discrepancy, dan sebelum/sesudah tabel perbandingan.
   - Memperbarui Section 3.3, 3.4, 3.7, 3.8, 3.9, 3.10 dengan formulasi lengkap, script reproducible Python/SQL, dan tabel 31 record matured yang telah diselaraskan.
4. [`docs/09_outcome_tracking_backfill_and_integrity_audit_report.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md):
   - Memperbarui ringkasan statistik performa dan tabel rekor historis agar seragam dengan audit_report.md dan database riil.
5. [`walkthrough.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/walkthrough.md) & [`summary.md`](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/summary.md):
   - Dokumentasi sesi kerja dan penambahan log entry 48 (append-only).

