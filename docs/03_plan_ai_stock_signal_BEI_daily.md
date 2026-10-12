# AI Indonesian Stock Daily Signal Generator — BEI
## Python + Node.js + Next.js + Telegram + AWS

> Konsep utama: **bukan auto-trading**, tetapi sistem yang setiap hari melakukan screening saham BEI, menghasilkan sinyal BUY/WATCH/AVOID lengkap dengan entry, TP, SL, confidence, dan horizon, lalu hasilnya dikirim ke Telegram untuk dieksekusi manual.
>
> Prinsip terpenting: **setiap prediction harus dicatat, setiap position harus dilacak, dan setiap outcome harus masuk kembali ke dataset sehingga kita bisa menguji apakah model benar-benar membaik setelah 500–1.000+ signal.**

---

# 1. Executive Summary

Project ini adalah **AI Stock Signal Generator untuk saham Indonesia** dengan fokus pada timeframe daily dan swing trading sekitar 3–10 trading days.

Sistem tidak mencoba menebak:

> "Besok candle BBCA hijau atau merah?"

Tetapi mencoba menjawab pertanyaan yang lebih berguna:

> "Dari universe saham BEI yang likuid, saham mana yang saat ini memiliki probabilitas risk-adjusted return terbaik untuk beberapa hari ke depan?"

Contoh output:

```text
BBCA
Signal              : BUY
Entry               : 8,500–8,600
TP                  : +5%
SL                  : -2%
Max Holding         : 10 trading days

P(TP tercapai)      : 71%
Expected Return     : +3.8%
Confidence          : High
Model Version       : v17

Alasan:
- momentum bullish
- volume meningkat
- relative strength mengungguli sektor
- market regime mendukung
```

Kemudian sistem mencatat signal tersebut.

Misalnya ternyata dalam 10 trading days:

```text
TP tidak pernah tercapai
SL tidak tercapai
Hari ke-10 return = -2%
```

Maka outcome menjadi:

```text
RESULT = LOSS / EXPIRED
REALIZED RETURN = -2%
HOLDING = 10 days
```

Data tersebut masuk ke **historical outcome dataset**.

Secara berkala model dievaluasi dan diretrain.

Tujuan akhirnya bukan:

> "Model ini terlihat pintar."

Tetapi:

> **"Apakah model v18 benar-benar lebih baik dari v17 setelah 500–1.000 signal out-of-sample?"**

---

# 2. Kenapa Use Case Daily + Manual Execution Cocok

Untuk project pertama, daily signal memiliki beberapa kelebihan dibanding auto-trading intraday:

1. Tidak membutuhkan broker API untuk eksekusi otomatis.
2. Tidak perlu server hidup 24/7.
3. Frekuensi data lebih rendah sehingga biaya lebih kecil.
4. Noise market lebih kecil daripada 1m/5m.
5. Ada waktu untuk melakukan sanity check manual sebelum entry.
6. Bisa fokus mengembangkan model dan evaluasi, bukan masalah execution engineering.

Catatan penting:

> Saham BEI tidak seluruhnya slow-moving. Ada saham yang sangat volatil. Yang dimaksud di sini adalah **time horizon daily lebih cocok untuk signal engine dibanding mencoba mengejar gerakan per-menit**.

---

# 3. Tujuan Project

## Tujuan utama

Membangun sistem yang:

- melakukan scan universe saham BEI;
- menghitung technical, market, sector, dan liquidity features;
- menghasilkan probability prediction;
- menghitung expected return;
- menentukan TP, SL, dan max holding;
- memberikan ranking saham;
- mengirim hasil ke Telegram;
- mencatat signal;
- mencatat position manual;
- memonitor outcome;
- mengukur performa model;
- melakukan retraining terkontrol;
- membandingkan model lama vs model baru.

## Bukan tujuan awal

- auto order ke broker;
- high-frequency trading;
- memprediksi setiap candle;
- menggunakan LLM sebagai decision-maker utama;
- mengejar akurasi 90%.

---

# 4. Arsitektur Sistem

## V1 — Recommended Starting Architecture

```text
                   ┌───────────────────────────┐
                   │     BEI Market Data       │
                   │ Historical + Daily/EOD    │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │     Python Data Layer     │
                   │ cleaning / validation     │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │   Feature Engineering     │
                   │ momentum / volume / trend │
                   │ volatility / sector       │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │       ML Prediction       │
                   │ LightGBM / XGBoost        │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │   Signal + Risk Engine    │
                   │ Entry / TP / SL / Horizon │
                   └─────────────┬─────────────┘
                                 │
                 ┌───────────────┴────────────────┐
                 ▼                                ▼
      ┌─────────────────────┐         ┌─────────────────────┐
      │ PostgreSQL / DB      │         │ Telegram Bot        │
      │ signal + positions   │         │ daily report        │
      │ outcomes + models    │         └──────────┬──────────┘
      └──────────┬──────────┘                    │
                 │                               ▼
                 │                         Manual Execution
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                   ┌───────────────────────────┐
                   │   Outcome / Evaluation    │
                   │ TP/SL/expiry / return     │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │ Training Dataset Update   │
                   │ matured historical trades │
                   └─────────────┬─────────────┘
                                 │
                                 ▼
                   ┌───────────────────────────┐
                   │   Retraining + Validation │
                   │ Model v18, v19, ...       │
                   └───────────────────────────┘
```

---

# 5. Stack yang Direkomendasikan

## Core ML / Data

**Python**

Recommended:

- Python 3.x
- pandas
- NumPy
- scikit-learn
- LightGBM
- XGBoost
- scipy
- pyarrow
- joblib
- matplotlib

Kenapa Python?

Karena research, feature engineering, backtesting, model training, dan evaluasi jauh lebih nyaman.

---

## Backend / Integration

**Node.js + TypeScript**

Node.js tidak wajib untuk V1, tetapi disiapkan untuk V2/V3.

Kegunaan:

- REST API
- Telegram service
- webhook
- auth
- dashboard backend
- model/service orchestration
- notification management

Alternative:

V1 boleh sepenuhnya Python.

---

## Frontend

**Next.js + TypeScript**

Belum wajib di awal.

Dipakai setelah signal engine sudah stabil untuk:

- dashboard market
- signal history
- position tracking
- model performance
- backtest result
- model version comparison
- portfolio
- analytics

---

## Database

Recommended:

**PostgreSQL**

Karena nanti query analytics akan cukup kompleks.

Alternatif awal yang lebih murah/sederhana:

- SQLite untuk local research
- PostgreSQL ketika masuk production
- object storage untuk dataset besar

---

## Notification

**Telegram Bot**

Telegram menjadi interface utama pada V1.

Contoh command:

```text
/daily
/signals
/position
/positions
/performance
/model
/backtest
```

---

## Cloud

Recommended AWS:

```text
EventBridge Scheduler
        ↓
AWS Lambda
        ↓
Python signal engine
        ↓
PostgreSQL / object storage
        ↓
Telegram Bot
```

Untuk daily workload, server tidak perlu hidup 24/7.

---

# 6. Data Pipeline

Data minimum:

```text
ticker
date
open
high
low
close
volume
value
```

Data yang lebih bagus:

```text
bid
offer
trade count
foreign buy
foreign sell
foreign net
sector
market cap
shares outstanding
```

Data fundamental yang bisa ditambahkan nanti:

```text
PER
PBV
ROE
ROA
DER
Revenue growth
Net income growth
EPS growth
Dividend yield
```

Data macro / market:

```text
IHSG
sector index
USD/IDR
market breadth
market volatility
```

---

# 7. Universe Filtering

Jangan langsung memberi model seluruh saham tanpa filter.

Contoh preliminary filter:

```text
- minimum average daily value
- minimum trading days
- minimum average volume
- price above minimum threshold
- tidak terlalu illiquid
- tidak suspend
- data cukup lengkap
```

Tujuannya:

- mengurangi noise;
- menghindari saham yang sulit dieksekusi manual;
- mengurangi distorted backtest;
- mengurangi spread/slippage problem.

---

# 8. Feature Engineering

## A. Momentum

Contoh:

```text
return_1d
return_3d
return_5d
return_10d
return_20d
```

Relative momentum:

```text
stock_return_20d - sector_return_20d
stock_return_20d - IHSG_return_20d
```

---

## B. Trend

Contoh:

```text
distance_to_ema20
distance_to_ema50
distance_to_ema200
ema20_vs_ema50
ema50_vs_ema200
```

---

## C. RSI

Bisa dipakai tetapi bukan sebagai decision rule tunggal.

Contoh feature:

```text
RSI14
RSI_change_5d
RSI_zone
```

---

## D. Volatility

Contoh:

```text
ATR
ATR_pct
realized_vol_5d
realized_vol_20d
high_low_range
```

Ini penting untuk menentukan TP dan SL yang realistis.

---

## E. Volume

Sangat penting untuk saham.

Contoh:

```text
volume_ratio_5d
volume_ratio_20d
value_ratio_20d
volume_trend
breakout_volume
```

Contoh:

```text
volume_today / average_volume_20d = 2.3x
```

bisa menjadi feature penting.

---

## F. Market Regime

Jangan hanya melihat saham individu.

Kita ingin mengetahui:

```text
IHSG:
BULLISH
BEARISH
SIDEWAYS
HIGH VOLATILITY
LOW VOLATILITY
```

Contoh features:

```text
IHSG_return_1d
IHSG_return_5d
IHSG_return_20d
IHSG_above_ema20
IHSG_above_ema50
market_breadth
```

---

## G. Sector Strength

Sangat berguna.

Misalnya:

```text
BANKING     +4.2%
ENERGY      +7.8%
PROPERTY    -2.1%
TECH        +1.4%
```

Kemudian:

```text
ANTM
Stock strength  : +8.2%
Sector strength : +7.1%
```

Sinyal menjadi lebih kontekstual.

---

# 9. Target ML

Jangan hanya memakai satu target.

## Target A — Probability Target

Contoh:

> Apakah harga mencapai +5% sebelum -2% dalam maksimal 10 trading days?

Target:

```text
1 = TP hit first
0 = SL hit first / expiry under defined rule
```

Ini sangat cocok karena langsung berhubungan dengan trading setup.

---

## Target B — Expected Return

Contoh:

```text
return_5d
return_10d
```

Regression model dapat memprediksi expected return.

---

## Target C — Time to Event

Nanti dapat dikembangkan:

```text
hari ke berapa TP tercapai?
hari ke berapa SL tercapai?
```

Ini berguna untuk mengoptimalkan holding period.

---

# 10. Contoh Signal

Misalnya:

```text
Ticker               : BBCA
Signal Date          : 2026-10-06

Entry Range          : 8,500 – 8,600
TP                   : 9,025
SL                   : 8,330
Max Holding          : 10 trading days

P(TP before SL)      : 71%
Expected Return      : +3.8%
Confidence           : High
Score                : 88/100

Model Version        : v17
```

---

# 11. TP dan SL

V1 dapat menggunakan kombinasi:

### Fixed threshold

```text
TP = +5%
SL = -2%
```

### ATR-based

Contoh:

```text
TP = +2.0 ATR
SL = -1.0 ATR
```

### Dynamic

Nanti:

```text
Market regime
+
volatility
+
model confidence
+
historical behavior
        ↓
dynamic TP/SL
```

Jadi TP/SL tidak harus angka mati selamanya.

---

# 12. Position Tracking

Ini wajib.

Signal dan actual position harus dipisahkan.

## SIGNAL

Mencatat:

> "Model menyarankan apa?"

## POSITION

Mencatat:

> "Apa yang benar-benar saya beli?"

Contoh:

Signal:

```text
BUY BBCA
```

Tapi user bisa:

```text
tidak beli
```

Maka signal tetap tercatat, tetapi tidak boleh dianggap sebagai realized loss.

---

# 13. Database Schema

## `stocks`

```text
id
ticker
company_name
sector
is_active
```

## `market_daily`

```text
id
ticker
date
open
high
low
close
volume
value
```

## `features_daily`

```text
id
ticker
date

rsi14
ema20
ema50
atr
return_1d
return_5d
return_20d
volume_ratio_20d
sector_strength
market_regime
...
```

## `signals`

```text
id
ticker
signal_date

signal
entry_low
entry_high

tp_price
sl_price
max_holding_days

predicted_probability
expected_return
confidence
score

model_version
feature_snapshot
```

## `positions`

```text
id
signal_id
ticker

actual_entry_date
actual_entry_price

actual_exit_date
actual_exit_price

exit_reason
realized_return
holding_days

status
```

Status:

```text
OPEN
CLOSED
CANCELLED
EXPIRED
```

## `position_daily_snapshots`

```text
id
position_id
date

open
high
low
close

return_from_entry

max_favorable_excursion
max_adverse_excursion

tp_reached
sl_reached
days_held
```

## `model_versions`

```text
id
model_name
version

training_start
training_end

feature_version
dataset_version

metrics_json
created_at
is_production
```

## `model_predictions`

Opsional tetapi sangat berguna untuk audit:

```text
id
signal_id
model_version
prediction_probability
prediction_timestamp
```

---

# 14. Outcome Engine

Setiap hari sistem mengecek semua signal/position yang masih aktif.

Contoh:

```text
Day 1
price = 8,620

Day 2
price = 8,710

Day 3
price = 8,910

Day 4
high = 9,050

TP = 9,025
```

Jika TP tercapai:

```text
EXIT_REASON = TP
RESULT = WIN
```

---

## Contoh loss karena SL

```text
Entry = 8,500
SL    = 8,330

Day 4 low = 8,300
```

Maka:

```text
EXIT_REASON = SL
RESULT = LOSS
```

---

## Contoh expiry

```text
Max holding = 10 days

TP tidak hit
SL tidak hit

Day 10 close = 8,330
```

Maka:

```text
EXIT_REASON = EXPIRY
RESULT = EXPIRED
RETURN = -2%
```

---

# 15. Penting: Daily OHLC Memiliki Ambiguity

Misalnya satu candle daily:

```text
Open  = 8,400
High  = 8,950
Low   = 8,250
Close = 8,500
```

Dengan:

```text
TP = 8,925
SL = 8,330
```

keduanya tersentuh pada hari yang sama.

Tetapi OHLC harian tidak memberi tahu:

```text
TP dulu?
atau
SL dulu?
```

Karena itu untuk backtesting yang serius:

- gunakan intraday 5m/15m bila tersedia; atau
- gunakan rule konservatif untuk ambiguity.

Contoh conservative rule:

```text
TP dan SL keduanya tersentuh
→ anggap SL terjadi lebih dahulu
```

Tujuannya mencegah backtest terlalu optimistis.

---

# 16. Feedback Loop — Bagian Terpenting

Pipeline:

```text
Signal
   ↓
Actual Price Path
   ↓
TP / SL / Expiry
   ↓
Outcome
   ↓
Historical Dataset
   ↓
Model Evaluation
   ↓
Retraining
   ↓
New Model Version
```

Setiap prediction harus immutable dan menyimpan `model_version`.

Contoh:

```text
Signal #000123
Model v17
Prediction = 0.71
Outcome = LOSS
```

Jangan mengganti historical prediction tersebut ketika model baru dilatih.

---

# 17. Kenapa Tidak Langsung "Belajar" Setiap Satu Trade?

Secara teknis bisa, tetapi tidak disarankan.

Masalah:

- sample terlalu sedikit;
- model mudah overreact;
- noise tinggi;
- regime belum tentu berubah;
- satu trade buruk tidak berarti model rusak.

Lebih sehat:

```text
Daily
→ collect data

Weekly
→ evaluate

Every N matured outcomes
→ candidate retraining

Monthly
→ formal model review
```

Contoh:

```text
minimum 200–500 new matured observations
→ candidate model
```

Batas N harus diuji, bukan dianggap angka sakral.

---

# 18. Apakah Model Benar-Benar Makin Baik?

Ini **KPI utama project**.

Bukan:

> "Model v18 accuracy 75%."

Tetapi:

> "Apakah model v18 menghasilkan performa out-of-sample lebih baik daripada v17?"

---

# 19. Model Comparison Framework

Misalnya:

## Model v17

```text
Signals       = 1,000
Win rate      = 58%
Avg win       = +4.1%
Avg loss      = -2.0%
Profit Factor = 1.54
Expectancy    = +0.67%
Max DD        = 11%
```

## Model v18

```text
Signals       = 1,000
Win rate      = 61%
Avg win       = +4.0%
Avg loss      = -1.8%
Profit Factor = 1.74
Expectancy    = +0.93%
Max DD        = 8%
```

Model v18 terlihat lebih baik.

Tetapi **harus diuji di periode data yang belum digunakan untuk training**.

---

# 20. Metrics yang Harus Dipantau

## Prediction Metrics

Untuk classification:

```text
AUC
Log Loss
Brier Score
Precision
Recall
Calibration
```

Untuk regression:

```text
MAE
RMSE
Correlation
Rank IC
```

---

## Trading Metrics

Lebih penting lagi:

```text
Win Rate
Average Win
Average Loss
Profit Factor
Expectancy
Maximum Drawdown
Sharpe-like metric
Sortino-like metric
Average Holding Period
```

Tambahkan:

```text
TP hit rate
SL hit rate
Expiry rate
```

---

# 21. Expected Value

Misalnya:

```text
P(win)  = 0.70
avg win = +5%
P(loss) = 0.30
avg loss = -2%
```

Expected return sederhana:

```text
EV = (0.70 × 5%) - (0.30 × 2%)
   = 3.5% - 0.6%
   = +2.9%
```

Tetapi production evaluation harus memasukkan:

- fee;
- slippage;
- spread;
- realistic entry;
- realistic exit;
- posisi yang tidak selalu terisi.

---

# 22. Risk-Adjusted Ranking

Jangan ranking berdasarkan probability saja.

Misalnya:

```text
Stock A
P(win) = 80%
Expected = +1.0%

Stock B
P(win) = 68%
Expected = +5.0%
```

Stock B bisa menjadi trade yang lebih menarik tergantung risk.

Gunakan score yang menggabungkan:

```text
probability
expected return
volatility
liquidity
drawdown risk
market regime
```

---

# 23. Model Calibration

Prediction:

```text
P(TP) = 70%
```

berarti idealnya dari banyak prediction yang model beri:

```text
70%
```

sekitar 70% benar-benar mencapai target.

Kalau kenyataannya:

```text
70% predicted probability
→ cuma 52% win
```

maka model overconfident.

Karena itu calibration sangat penting.

Metode yang bisa digunakan:

- Platt scaling
- isotonic regression
- reliability curve
- Brier score

---

# 24. Walk-Forward Validation

Jangan random split seperti dataset biasa.

Karena ini time series.

Gunakan:

```text
Train
2018 ───────── 2023

Validation
2024

Test
2025
```

Lalu rolling:

```text
Train 2018–2023
Test 2024

Train 2019–2024
Test 2025

Train 2020–2025
Test 2026
```

Ini lebih dekat dengan kondisi real.

---

# 25. Hindari Data Leakage

Ini salah satu risiko terbesar.

Feature pada tanggal T hanya boleh menggunakan informasi yang memang tersedia pada atau sebelum T.

Tidak boleh:

```text
Signal Date = 6 Oct

Feature menggunakan
earnings/result yang baru diumumkan 7 Oct
```

Atau:

```text
menggunakan future close
untuk menghitung feature signal hari ini
```

Semua harus mengikuti chronological availability.

---

# 26. Delisted / Survivorship Bias

Jangan hanya menggunakan saham yang masih hidup hari ini.

Kalau training dataset hanya berisi:

```text
saham yang masih listed / aktif sekarang
```

hasil bisa terlalu optimistis.

Idealnya dataset historis juga mempertimbangkan:

- saham suspended;
- delisted;
- perubahan ticker;
- perubahan corporate action.

Ini merupakan improvement penting saat project mulai serius.

---

# 27. Corporate Action Handling

Perlu penyesuaian untuk:

- stock split
- reverse split
- rights issue
- dividen
- bonus shares

Harga historis perlu diperlakukan secara konsisten.

Tanpa penanganan corporate action, signal dan return bisa salah.

---

# 28. Position Tracking vs Signal Tracking

Ini konsep penting.

### Signal

> "Model menyarankan BBCA BUY."

### Position

> "Saya benar-benar membeli BBCA."

Contoh:

```text
Signal #123
BBCA BUY

User:
did not execute
```

Maka:

```text
Signal outcome:
WIN

Actual portfolio:
NO POSITION
```

Ini memungkinkan kita mengukur:

1. **Model performance**
2. **Actual trading performance**

secara terpisah.

---

# 29. Manual Execution Workflow

Telegram:

```text
DAILY SIGNAL

1. BBCA
BUY
Entry 8,500–8,600
TP 9,025
SL 8,330
Max hold 10D
Confidence 71%
```

User:

```text
/enter BBCA 8550 100
```

Bot menyimpan:

```text
actual_entry_price = 8550
quantity = 100
```

Ketika keluar:

```text
/exit BBCA 8950
```

Bot mencatat:

```text
realized_return
fees
exit_reason = MANUAL
```

Opsional: user tetap bisa input posisi langsung lewat dashboard.

---

# 30. Telegram Commands

Recommended V1:

```text
/start

/daily
```

Menampilkan daily top signals.

```text
/signals
```

Menampilkan signal history.

```text
/positions
```

Posisi aktif.

```text
/enter BBCA 8550 100
```

Mencatat manual position.

```text
/exit BBCA 8950
```

Mencatat manual exit.

```text
/performance
```

Performance portfolio.

```text
/model
```

Model version + latest metrics.

```text
/compare
```

Compare model versions.

---

# 31. Telegram Daily Report

Contoh:

```text
🤖 DAILY STOCK SIGNAL
06 Oct 2026

MARKET
IHSG       : Bullish
Breadth    : Positive
Volatility : Normal

━━━━━━━━━━━━━━━━━━

🥇 ANTM
Score            : 91/100
P(TP before SL)  : 74%
Expected Return  : +3.8%

Entry            : 3,950–4,000
TP               : +5%
SL               : -2%
Max Hold         : 10D

Why:
• strong momentum
• volume expansion
• sector outperforming
• market regime supportive

━━━━━━━━━━━━━━━━━━

🥈 BMRI
Score            : 87/100
P(TP before SL)  : 69%
Expected Return  : +2.9%

━━━━━━━━━━━━━━━━━━

🥉 BBCA
Score            : 84/100
P(TP before SL)  : 67%
Expected Return  : +2.4%
```

---

# 32. LLM: Perlu atau Tidak?

## Jawaban

**Tidak perlu untuk core ML loop.**

Core system:

```text
market data
→ features
→ ML
→ TP/SL
→ signal
→ outcome
→ retraining
```

Tidak membutuhkan LLM.

---

# 33. Fungsi LLM yang Masuk Akal

LLM dapat menjadi **analyst / explanation layer**.

Contoh model:

```text
BBCA
P(TP) = 71%
Expected = +3.8%
Volume = 2.1x
RSI = 64
Sector strength = +3.4%
Market regime = bullish
```

LLM mengubahnya menjadi:

> "Signal BBCA didukung momentum dan volume expansion dengan sektor perbankan yang sedang kuat. Risiko utama adalah reversal IHSG dan penurunan volume."

LLM juga bisa digunakan untuk:

- membuat ringkasan berita;
- menjelaskan signal;
- membuat natural language report;
- membantu debugging strategy;
- membantu research ide.

---

# 34. Yang Jangan Dilakukan dengan LLM

Jangan membuat:

```text
LLM:
"Menurut saya BBCA akan naik.
BUY!"
```

sebagai sumber kebenaran trading.

LLM tidak boleh menjadi:

- source price truth;
- outcome calculator;
- position ledger;
- final risk engine;
- pengganti deterministic rules.

Core trading logic harus tetap reproducible.

---

# 35. Feedback Loop Tanpa LLM

Ini sangat mungkin:

```text
Prediction
   ↓
Actual price
   ↓
Deterministic outcome
   ↓
Dataset
   ↓
Retraining
   ↓
Model v2
```

Tidak ada AI generatif di sini.

Ini sebenarnya lebih baik untuk auditability.

---

# 36. Improvement Roadmap

## Phase 1 — Baseline

Buat baseline sederhana:

```text
EMA
RSI
Volume
ATR
IHSG regime
```

Model:

```text
Logistic Regression
Random Forest
LightGBM
```

Tujuan:

> punya benchmark.

---

## Phase 2 — Better Feature Set

Tambah:

```text
sector strength
relative strength
market breadth
liquidity
volatility regime
```

---

## Phase 3 — Better Labels

Dari:

```text
return_5d
```

menjadi:

```text
TP before SL
```

Contoh:

```text
+5% TP
-2% SL
10D max hold
```

---

## Phase 4 — Dynamic TP/SL

Pelajari:

```text
TP = fixed
vs
TP = ATR-based
vs
TP = volatility-based
```

---

## Phase 5 — Ranking Model

Pisahkan:

```text
Probability model
+
Expected return model
+
Risk score
```

kemudian ranking seluruh universe.

---

## Phase 6 — Regime-specific Models

Contoh:

```text
Bull Model
Sideways Model
Bear Model
```

atau satu model dengan regime features.

Bandingkan mana yang lebih baik.

---

## Phase 7 — Meta Model

Gabungkan beberapa model:

```text
LightGBM
XGBoost
Logistic Regression

        ↓

Ensemble
        ↓

Final probability
```

---

# 37. Improvement Penting: MFE / MAE

Jangan cuma mencatat final return.

Tambahkan:

### MFE — Maximum Favorable Excursion

Contoh:

```text
Entry = 8,500

selama holding:
+0.8%
+2.1%
+3.7%
+4.4%
-1.2%
```

MFE:

```text
+4.4%
```

### MAE — Maximum Adverse Excursion

Misalnya:

```text
-0.3%
-1.1%
-1.7%
+2.0%
```

MAE:

```text
-1.7%
```

Ini membantu menjawab:

> "Apakah SL -2% terlalu longgar?"

> "Apakah TP +5% terlalu tinggi?"

---

# 38. Improvement: Dynamic Holding Period

Awalnya:

```text
Max hold = 10D
```

Setelah data cukup:

```text
High confidence:
optimal holding = 3–7D

Medium confidence:
optimal holding = 2–5D
```

Atau:

```text
Jika momentum kehilangan strength
→ exit sebelum max hold.
```

---

# 39. Improvement: Signal Quality by Regime

Sistem harus bisa menjawab:

```text
Model works best when:

Bull regime        68% win
Sideways            55%
Bear                 42%
High volatility      39%
```

Kemudian risk engine dapat mengurangi exposure:

```text
Bull
→ normal size

Sideways
→ half size

Bear
→ only highest score
```

Atau bahkan:

```text
Bear
→ no new position
```

---

# 40. Improvement: Portfolio-Level Risk

Jangan menganggap setiap signal independen.

Misalnya:

```text
BBCA
BMRI
BBNI
BBRI
```

semuanya banking.

Walaupun 4 signal berbeda, sebenarnya exposure sektornya besar.

Tambahkan:

```text
max positions
max sector exposure
max correlated exposure
cash reserve
```

Contoh:

```text
Max total positions = 5
Max banking         = 2
Max high-volatility = 1
```

---

# 41. Improvement: Model Drift

Performa model bisa berubah.

Contoh:

```text
2024:
Win rate = 64%

2025:
Win rate = 60%

2026:
Win rate = 51%
```

Ini bisa berarti:

- market regime berubah;
- feature relationship berubah;
- liquidity berubah;
- model drift terjadi.

Sistem perlu memberi alert:

```text
⚠ MODEL DRIFT DETECTED
Recent 200 signals:
Win rate = 49%

Historical:
Win rate = 61%
```

---

# 42. Improvement: Champion / Challenger Model

Jangan langsung mengganti model production.

Contoh:

```text
Champion
Model v17
```

vs

```text
Challenger
Model v18
```

Keduanya diberi prediction pada data baru.

Tetapi hanya v17 yang dipakai sebagai production signal.

Setelah cukup sample:

```text
v18 statistically better?
YES → promote
NO  → reject
```

Ini salah satu cara terbaik untuk menghindari model baru yang hanya terlihat bagus pada backtest.

---

# 43. Improvement: Model Versioning

Setiap signal harus tahu:

```text
model_version = v17
```

Setiap model harus punya:

```text
training period
feature version
dataset version
hyperparameters
evaluation metrics
```

Contoh:

```text
v17

Training:
2018-01-01 → 2026-03-31

Validation:
2026-04-01 → 2026-06-30

Features:
feature_set_05

Algorithm:
LightGBM
```

---

# 44. Improvement: Reproducibility

Kalau suatu hari:

> "Kenapa tanggal 12 Juni model bilang BUY?"

kita harus bisa menjawab.

Simpan:

```text
ticker
signal_date
all feature values
model version
probability
threshold
TP
SL
decision
```

Signal lama tidak boleh berubah ketika model baru dilatih.

---

# 45. Backtesting Framework

Backtest harus mensimulasikan:

```text
signal generation
→ entry
→ position management
→ TP / SL / expiry
→ fees
→ slippage
→ position sizing
```

Jangan hanya:

```text
buy if prediction > 70%
```

lalu melihat equity curve.

Harus lebih realistis.

---

# 46. Paper Trading

Sebelum memakai uang:

```text
Live market data
+
real signal
+
paper position
```

Tidak ada uang nyata.

Tujuan:

- memastikan data benar;
- memastikan Telegram benar;
- memastikan TP/SL logic benar;
- memastikan position tracking benar;
- membandingkan backtest vs live-paper.

---

# 47. Live Manual Execution

Setelah paper cukup panjang:

```text
bot signal
→ Telegram
→ user checks chart
→ user decides
→ manual buy
```

Ukuran posisi awal kecil.

Fokus:

> validate system, bukan mengejar profit maksimum.

---

# 48. Success Criteria

Project dianggap mulai valid bukan ketika:

```text
"Accuracy 70%"
```

tetapi ketika:

1. signal dapat direproduksi;
2. historical backtest masuk akal;
3. live-paper mendekati backtest;
4. calibration cukup baik;
5. expectancy positif setelah cost;
6. drawdown dapat diterima;
7. model baru dapat dibandingkan secara fair;
8. setelah 500–1.000 signal ada bukti model punya edge yang konsisten.

---

# 49. Target Evaluasi 500–1.000 Signal

Buat dashboard khusus:

```text
TOTAL MATURED SIGNALS
1,000

MODEL v17
Win Rate       58.4%
Avg Win         4.2%
Avg Loss       -2.0%
Expectancy      0.66%
Profit Factor   1.61
Max Drawdown    10.4%
Brier Score     0.18
```

Kemudian:

```text
MODEL v18
Win Rate       61.1%
Avg Win         4.0%
Avg Loss       -1.8%
Expectancy      0.87%
Profit Factor   1.78
Max Drawdown     8.2%
Brier Score     0.16
```

Dashboard harus menunjukkan:

```text
v18 vs v17

Expectancy      ↑
Profit Factor   ↑
Max Drawdown    ↓
Calibration     ↑
```

Tetapi tetap harus memakai out-of-sample evaluation.

---

# 50. Yang Sebenarnya Kita Cari

Bukan:

```text
akurasi tertinggi
```

Melainkan:

```text
positive expectancy
+
stable performance
+
good calibration
+
controlled drawdown
+
reproducibility
```

Model dengan:

```text
55% win rate
```

bisa lebih bagus daripada model:

```text
70% win rate
```

jika model 55%:

```text
average win jauh lebih besar
average loss terkendali
```

---

# 51. Suggested Project Structure

```text
indonesian-stock-ai/
│
├── apps/
│   ├── api/
│   │   └── node/
│   │
│   └── web/
│       └── nextjs/
│
├── python/
│   ├── data/
│   ├── features/
│   ├── models/
│   ├── signals/
│   ├── risk/
│   ├── backtest/
│   ├── evaluation/
│   ├── retraining/
│   └── telegram/
│
├── datasets/
│
├── notebooks/
│
├── migrations/
│
├── configs/
│
├── tests/
│
├── docker/
│
└── docs/
```

---

# 52. Suggested Python Modules

```text
python/
├── data/
│   ├── downloader.py
│   ├── cleaner.py
│   └── validator.py
│
├── features/
│   ├── momentum.py
│   ├── trend.py
│   ├── volume.py
│   ├── volatility.py
│   ├── market.py
│   └── sector.py
│
├── models/
│   ├── classifier.py
│   ├── regressor.py
│   ├── calibration.py
│   └── registry.py
│
├── signals/
│   ├── scorer.py
│   ├── ranking.py
│   └── generator.py
│
├── risk/
│   ├── position_size.py
│   ├── tp_sl.py
│   └── portfolio.py
│
├── outcomes/
│   ├── tracker.py
│   └── evaluator.py
│
├── backtest/
│   ├── engine.py
│   └── metrics.py
│
└── retraining/
    ├── trainer.py
    └── challenger.py
```

---

# 53. AWS Deployment Concept

Daily:

```text
EventBridge
    ↓
Lambda
    ↓
Python job
    ↓
download/read latest market data
    ↓
build features
    ↓
load production model
    ↓
generate signals
    ↓
save to DB
    ↓
send Telegram
```

Nightly / scheduled outcome job:

```text
EventBridge
    ↓
Lambda / scheduled worker
    ↓
update position snapshots
    ↓
evaluate TP / SL / expiry
    ↓
store matured outcomes
```

Periodic retraining:

```text
Scheduled job
    ↓
load matured dataset
    ↓
train challenger model
    ↓
run validation
    ↓
compare champion vs challenger
    ↓
promote only if criteria pass
```

---

# 54. AWS Cost Philosophy

Untuk workload daily, jangan mulai dari:

```text
24/7 EC2
RDS besar
Kubernetes
```

Mulai dari serverless / low-idle architecture.

Prioritas:

```text
Lambda
Scheduler
Object Storage
small database
CloudWatch
Telegram
```

Tetap pasang billing alert karena "free tier" selalu mempunyai batas, eligibility, dan perubahan kebijakan.

---

# 55. Security

Wajib:

- Telegram bot token disimpan di secret/env;
- database credentials disimpan di secrets;
- tidak menyimpan credentials di GitHub;
- least privilege IAM;
- backup database;
- audit log;
- jangan menyimpan secret di notebook.

Karena sistem hanya memberi signal, attack surface lebih kecil dibanding bot auto-trading.

---

# 56. Development Roadmap

## Phase 0 — Data

Target:

```text
historical OHLCV
```

Output:

```text
clean dataset
```

---

## Phase 1 — Baseline Screener

Tanpa ML.

```text
EMA
RSI
Volume
ATR
```

Tujuan:

> baseline strategy.

---

## Phase 2 — First ML Model

```text
features
→ LightGBM
→ probability
```

Buat model v1.

---

## Phase 3 — Historical Backtest

Tambahkan:

```text
TP
SL
max hold
fee
slippage
```

---

## Phase 4 — Telegram

Setiap hari:

```text
Top 5–10
```

---

## Phase 5 — Position Journal

Manual:

```text
/enter
/exit
```

---

## Phase 6 — Outcome Engine

Tracking:

```text
TP
SL
Expiry
Manual exit
```

---

## Phase 7 — 500+ Matured Signals

Mulai melakukan analisis:

```text
market regime
sector
confidence bucket
score bucket
TP/SL
```

---

## Phase 8 — Challenger Models

```text
v1 champion
v2 challenger
```

Bandingkan.

---

## Phase 9 — Dashboard

Next.js:

```text
signals
positions
performance
model history
```

---

# 57. Potential Future Features

## A. Fundamental model

Tambah:

```text
earnings
valuation
growth
ROE
debt
cashflow
```

Bisa dibuat:

```text
technical score
+
fundamental score
```

---

## B. News sentiment

LLM / NLP membaca:

- corporate announcements;
- earnings;
- major news;
- sector news.

Tetapi news harus memiliki timestamp yang jelas untuk menghindari leakage.

---

## C. Event-aware model

Misalnya:

```text
earnings soon
dividend date
corporate action
```

Model dapat memiliki event features.

---

## D. Multi-horizon prediction

Secara simultan:

```text
P(TP 3D)
P(TP 5D)
P(TP 10D)
```

---

## E. Meta-labeling

Base model:

```text
BUY candidate
```

Meta model:

```text
Should we actually take this trade?
YES / NO
```

Ini bisa meningkatkan precision.

---

## F. Portfolio Optimizer

Dari top 10 signal:

```text
pilih 3–5 saham
```

berdasarkan:

- score;
- correlation;
- volatility;
- sector exposure;
- expected return.

---

# 58. Long-Term Architecture

```text
                MARKET DATA
                     │
                     ▼
             DATA ENGINEERING
                     │
                     ▼
            FEATURE STORE
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
   CLASSIFICATION          REGRESSION
   P(TP before SL)          Expected Return
          │                     │
          └──────────┬──────────┘
                     ▼
              RISK ENGINE
                     │
              TP / SL / Size
                     │
                     ▼
             SIGNAL RANKING
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      TELEGRAM               DASHBOARD
          │                     │
          └──────────┬──────────┘
                     ▼
              MANUAL TRADE
                     │
                     ▼
              POSITION TRACK
                     │
                     ▼
               OUTCOME DATA
                     │
                     ▼
             MODEL EVALUATION
                     │
            ┌────────┴────────┐
            ▼                 ▼
       CHAMPION           CHALLENGER
            │                 │
            └────────┬────────┘
                     ▼
                 PROMOTION
```

---

# 59. Final Recommendation

Untuk project ini, rekomendasi architecture adalah:

### V1

```text
Python
+ PostgreSQL/SQLite
+ Telegram
+ AWS scheduled execution
```

Fokus pada:

```text
data
→ features
→ ML
→ signal
→ TP/SL
→ tracking
→ outcome
```

### V2

Tambahkan:

```text
Node.js/TypeScript
+ Next.js
```

untuk dashboard dan API.

### V3

Tambahkan:

```text
LLM
```

sebagai:

- explanation layer;
- news analysis;
- research assistant;
- natural language reporting.

Bukan sebagai source utama trading decision.

---

# 60. Prinsip Besar Project

Ada 5 prinsip yang sebaiknya tidak berubah:

### 1. Signal harus reproducible

Signal lama tidak berubah hanya karena model baru dibuat.

### 2. Outcome harus deterministic

TP/SL/expiry dihitung berdasarkan market data, bukan opini LLM.

### 3. Model version wajib dicatat

Setiap prediction harus tahu:

```text
model version
feature version
dataset version
```

### 4. Model baru tidak otomatis menjadi production

Selalu:

```text
Champion vs Challenger
```

### 5. Keberhasilan diukur dari 500–1.000+ signal

Pertanyaan final bukan:

> "Seberapa akurat model?"

Tetapi:

> **"Apakah model menghasilkan positive expectancy secara konsisten, terkalibrasi, dan dengan drawdown yang dapat diterima?"**

Dan pertanyaan lanjutan yang lebih penting:

> **"Apakah model v18 benar-benar lebih baik daripada v17 berdasarkan data out-of-sample yang cukup besar?"**

Itulah feedback loop yang akan membuat project ini menjadi **sistem machine-learning trading yang bisa dievaluasi dan berkembang**, bukan sekadar screener dengan indikator teknikal.

---
