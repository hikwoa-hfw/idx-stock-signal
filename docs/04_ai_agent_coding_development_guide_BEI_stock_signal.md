# AI Agent Coding Development Guide
## AI Indonesian Stock Daily Signal Generator — BEI

> **Dokumen ini adalah execution guide untuk AI coding agent.**
>
> Berikan file ini kepada coding agent seperti Claude Code, Cursor Agent, Gemini CLI, Antigravity, atau agent serupa. Agent harus mengikuti arsitektur, aturan data, ML, testing, dan acceptance criteria di dokumen ini.
>
> Project ini **signal generator + portfolio journal**, bukan auto-trading.
>
> Prinsip utama:
>
> **Data → Features → ML → Signal → TP/SL → Telegram → Manual Execution → Position Tracking → Outcome → Evaluation → Retraining → Champion/Challenger**
>
> Tujuan akhirnya bukan sekadar membuat model yang terlihat pintar, tetapi membangun sistem yang dapat membuktikan:
>
> **"Setelah 500–1.000+ matured signals, apakah model benar-benar memiliki edge dan apakah model baru benar-benar lebih baik daripada model sebelumnya?"**

---

# 1. Role dan Mandate AI Coding Agent

Agent bertindak sebagai **senior software engineer + ML engineer**, bukan sebagai trader.

Agent wajib:

1. membangun sistem secara modular;
2. menjaga reproducibility;
3. mencegah data leakage;
4. memisahkan signal, position, dan outcome;
5. membuat tests sebelum menganggap fitur selesai;
6. mencatat model version;
7. menjaga historical predictions immutable;
8. tidak mengganti production model tanpa evaluation;
9. tidak menggunakan LLM sebagai decision-maker trading utama;
10. tidak membuat auto-trading/broker execution pada V1.

Agent dilarang:

- menghapus historical data hanya karena format berubah;
- melakukan random train/test split untuk time-series;
- menggunakan future data dalam feature;
- menganggap semua BUY signal sebagai actual position;
- mengubah prediction historis ketika model baru dibuat;
- mengklaim model profitable hanya dari in-sample backtest;
- menaruh secret/API key di source code;
- menambahkan dependency besar tanpa alasan;
- memperkenalkan microservice complexity tanpa kebutuhan.

---

# 2. Project Objective

Build a production-minded application that:

- scans an Indonesian stock universe;
- prepares clean historical/daily data;
- computes technical, market, sector, and liquidity features;
- predicts probability of a predefined event;
- predicts expected return;
- ranks candidate stocks;
- calculates entry/TP/SL/max holding;
- sends daily signals through Telegram;
- records manual positions;
- tracks daily price path;
- determines TP/SL/expiry outcomes;
- evaluates model performance;
- retrains challenger models;
- promotes a challenger only when objective criteria are met.

---

# 3. Scope V1

## Included

- daily/EOD data;
- swing horizon approximately 3–10 trading days;
- classification model;
- optional regression model;
- technical + market + sector features;
- TP/SL;
- position journal;
- Telegram;
- historical backtesting;
- walk-forward evaluation;
- model versioning;
- outcome tracking;
- champion/challenger evaluation;
- AWS scheduled deployment.

## Not Included

- real broker order execution;
- intraday HFT;
- 1m/5m scalping;
- leveraged trading;
- autonomous portfolio rebalancing;
- autonomous LLM BUY/SELL decisions.

---

# 4. Recommended Technical Stack

## Python

Primary ML/data language.

Recommended baseline:

```text
Python 3.13
```

Python 3.13 is available as an AWS Lambda managed runtime and is suitable for a stable production baseline. Verify runtime availability before deployment because AWS runtime support changes over time.

Core libraries:

```text
pandas
numpy
scikit-learn
lightgbm
xgboost
scipy
pyarrow
joblib
pydantic
pytest
```

Optional:

```text
optuna
mlflow
matplotlib
```

Do not install all optional libraries immediately.

---

## Node.js / TypeScript

Recommended:

```text
Node.js 24 LTS
TypeScript
```

Pin the exact version with `.nvmrc` / Volta / mise and use the lockfile. Do not depend on an unpinned floating runtime.

Node.js is primarily for:

- API;
- Telegram integration if separated from Python;
- dashboard backend;
- webhook;
- orchestration.

V1 may keep Telegram entirely inside Python.

---

## Frontend

```text
Next.js
TypeScript
```

Use the latest stable Next.js version that is compatible with the selected Node LTS, and pin the package version in the lockfile.

Frontend is V2.

---

## Database

Preferred:

```text
PostgreSQL
```

Local development can use:

```text
SQLite
```

provided that persistence logic is abstracted and production PostgreSQL compatibility is maintained.

---

## Cloud

Recommended AWS:

```text
AWS EventBridge Scheduler
AWS Lambda
AWS S3
PostgreSQL
AWS Secrets Manager or SSM Parameter Store
CloudWatch
```

Use serverless scheduling for daily jobs.

AWS Lambda currently supports managed Python 3.13 and newer runtimes on Amazon Linux 2023. Prefer AL2023-based runtimes over legacy Amazon Linux 2 runtimes. Verify current supported runtimes during deployment.

---

## Messaging

```text
Telegram Bot API
```

---

# 5. High-Level Architecture

```text
                       ┌─────────────────────┐
                       │  MARKET DATA SOURCE │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │   DATA INGESTION    │
                       │ clean / validate    │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ FEATURE ENGINEERING │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │    ML PREDICTOR     │
                       │ classifier/regress. │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │   SIGNAL ENGINE     │
                       │ rank + TP + SL      │
                       └──────────┬──────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
           ┌─────────────────┐          ┌─────────────────┐
           │    PostgreSQL   │          │    Telegram     │
           └────────┬────────┘          └────────┬────────┘
                    │                            │
                    │                       manual trade
                    │                            │
                    └─────────────┬──────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │  POSITION TRACKER   │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │   OUTCOME ENGINE    │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ MODEL EVALUATION    │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ CHALLENGER TRAINING │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ CHAMPION PROMOTION  │
                       └─────────────────────┘
```

---

# 6. Repository Structure

Create:

```text
indonesian-stock-ai/
│
├── apps/
│   ├── api/
│   │   └── node/
│   └── web/
│       └── nextjs/
│
├── services/
│   └── telegram/
│
├── python/
│   ├── data/
│   ├── features/
│   ├── labels/
│   ├── models/
│   ├── signals/
│   ├── risk/
│   ├── outcomes/
│   ├── backtest/
│   ├── evaluation/
│   ├── retraining/
│   ├── config/
│   └── common/
│
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── backtest/
├── migrations/
├── datasets/
│   ├── raw/
│   ├── processed/
│   └── features/
├── models/
│   ├── registry/
│   ├── champion/
│   └── challengers/
├── notebooks/
├── infra/
│   └── aws/
├── docs/
├── .env.example
├── .gitignore
├── README.md
└── Makefile
```

---

# 7. Architecture Rules

## Rule 1 — Keep ML independent from API

Bad:

```text
Telegram handler calculates RSI and runs LightGBM directly.
```

Good:

```text
Telegram
  ↓
service
  ↓
signal repository
```

ML should be callable independently.

## Rule 2 — Domain logic must not depend on UI

The same signal engine must work from:

```text
CLI
Python script
Lambda
API
Telegram
```

without rewriting trading logic.

## Rule 3 — Use typed domain models

Use Pydantic/dataclasses in Python and TypeScript interfaces/types in Node.

Examples:

```python
Signal
Position
Prediction
Outcome
ModelVersion
```

## Rule 4 — Deterministic logic

Given the same:

```text
same data
same config
same model version
```

the result should be reproducible.

---

# 8. Environment Variables

Create `.env.example`:

```text
APP_ENV=development
DATABASE_URL=
MARKET_DATA_PROVIDER=
MARKET_DATA_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
AWS_REGION=
S3_BUCKET=
MODEL_REGISTRY_PATH=
LOG_LEVEL=INFO
```

Never commit `.env`.

Never place credentials in notebooks.

---

# 9. Data Provider Abstraction

Do NOT hardcode one provider throughout the application.

Create interface:

```python
class MarketDataProvider(Protocol):
    def get_daily_bars(...)
    def get_universe(...)
    def get_sector_data(...)
```

Implement:

```text
ProviderA
ProviderB
LocalCSVProvider
```

Development can use a free/temporary source where legally and technically appropriate.

Production must use a source whose data access and usage rights are suitable for the project.

---

# 10. Data Model — Market Data

Minimum:

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

Validation rules:

```text
open > 0
high >= max(open, close)
low <= min(open, close)
volume >= 0
date unique per ticker
```

Handle:

- missing dates;
- duplicates;
- null values;
- ticker changes;
- corporate actions;
- suspended periods.

Do not blindly forward-fill prices across trading suspensions.

---

# 11. Universe Definition

Create a configurable universe:

```yaml
min_avg_value_20d:
min_avg_volume_20d:
min_price:
allowed_sectors:
excluded_tickers:
```

Do not hardcode the universe inside feature code.

---

# 12. Feature Engineering

Implement independently.

## Momentum

```text
return_1d
return_3d
return_5d
return_10d
return_20d
```

## Trend

```text
ema20
ema50
ema200
close_vs_ema20
close_vs_ema50
ema20_vs_ema50
ema50_vs_ema200
```

## RSI

```text
rsi14
rsi_change_5d
```

## Volatility

```text
atr14
atr_pct
realized_vol_5d
realized_vol_20d
daily_range_pct
```

## Volume

```text
volume_ratio_5d
volume_ratio_20d
value_ratio_20d
```

## Relative Strength

```text
stock_return_20d - ihsg_return_20d
stock_return_20d - sector_return_20d
```

## Market Regime

Create or derive:

```text
bullish
sideways
bearish
high_vol
low_vol
```

Prefer numerical features over categorical labels when possible:

```text
ihsg_return_5d
ihsg_return_20d
ihsg_vs_ema20
ihsg_vs_ema50
market_breadth
market_volatility
```

---

# 13. Feature Availability Rule

Every feature must be calculated using information available **at signal time**.

Example:

Signal date:

```text
2026-10-06
```

A feature may use:

```text
prices through 2026-10-05
```

or same-day information only if the signal is explicitly generated after that information became available.

Do NOT use:

```text
2026-10-07 close
```

inside a 2026-10-06 signal feature.

All feature functions must document their information timestamp assumptions.

---

# 14. Labeling Strategy

V1 primary label:

> Did TP happen before SL within maximum holding period?

Example:

```text
Entry = 8,500
TP    = +5%
SL    = -2%
Max hold = 10 trading days
```

Label:

```text
1 = TP first
0 = SL first / expiry under configured classification policy
```

However, preserve separate outcome states in the database:

```text
TP
SL
EXPIRY
AMBIGUOUS
```

The ML label mapping may be configurable.

---

# 15. TP / SL Ambiguity

Daily OHLC can produce this case:

```text
high >= TP
low <= SL
```

in the same day.

Daily OHLC alone cannot tell which happened first.

V1 default:

```text
if both TP and SL touched on same daily candle:
    mark AMBIGUOUS
```

Backtest mode may support:

```text
conservative:
    assume SL first

optimistic:
    assume TP first

intraday:
    use 5m/15m data to determine order
```

The production benchmark should use the conservative rule until reliable intraday data is available.

---

# 16. ML Architecture

Start simple.

## Model A — Classification

Predict:

```text
P(TP before SL)
```

Preferred baseline:

```text
Logistic Regression
LightGBM
XGBoost
```

Start with Logistic Regression + LightGBM.

Do not immediately build neural networks.

## Model B — Expected Return

Optional regression:

```text
return_5d
return_10d
```

Use:

```text
LightGBM Regressor
```

or equivalent.

---

# 17. Calibration

Probability is only useful if it is calibrated.

Example:

```text
Predicted 70%
```

should roughly mean:

```text
~70% success
```

over a sufficiently large set.

Evaluate:

```text
Brier Score
Log Loss
Reliability Curve
Calibration Error
```

Candidate calibration:

```text
Platt scaling
Isotonic regression
```

---

# 18. Signal Engine

Signal generation pipeline:

```text
Universe filter
    ↓
Feature calculation
    ↓
Classifier probability
    ↓
Expected return
    ↓
Risk filters
    ↓
Ranking
    ↓
Top N candidates
```

Example:

```python
if probability >= 0.65 and expected_return > min_expected_return:
    candidate = True
```

Thresholds must live in config, not hardcoded source.

---

# 19. Signal Score

Example:

```text
probability_score
expected_return_score
risk_score
liquidity_score
market_regime_score
```

Combine into:

```text
final_score = weighted score
```

Weights must be configurable and versioned.

Do not arbitrarily tune weights on the test period.

---

# 20. TP / SL Engine

V1 supports:

```text
fixed percentage
ATR based
```

Example:

```text
TP = +5%
SL = -2%
```

Later:

```text
dynamic TP
dynamic SL
trailing TP
regime-aware exit
```

Each signal must persist the **actual chosen TP/SL**, not only the rule name.

---

# 21. Signal Record

Every generated signal must capture:

```text
signal_id
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
score
model_version
feature_version
signal_config_version
feature_snapshot
created_at
```

Signal records are immutable.

If a calculation bug is fixed, generate a new signal/version. Do not rewrite old production signals.

---

# 22. Position Record

Separate from signal.

Required:

```text
position_id
signal_id
ticker
actual_entry_date
actual_entry_price
quantity
actual_exit_date
actual_exit_price
status
exit_reason
realized_return
fees
holding_days
```

Possible status:

```text
OPEN
CLOSED
CANCELLED
```

Possible exit reason:

```text
TP
SL
EXPIRY
MANUAL
OTHER
```

---

# 23. Position Journal

User may choose not to execute a signal.

Example:

```text
Signal:
BBCA BUY
```

User:

```text
did not buy
```

This must NOT create a losing position.

Therefore:

```text
signal_outcome
```

and

```text
actual_portfolio_result
```

must be evaluated separately.

---

# 24. Position Daily Snapshot

For each open position:

```text
position_id
date
open
high
low
close
return_from_entry
mfe
mae
tp_reached
sl_reached
days_held
```

This enables post-trade analysis.

---

# 25. MFE and MAE

### MFE

Maximum favorable excursion.

Example:

```text
entry = 8,500

price path:
+0.5%
+1.7%
+3.9%
+4.5%
+2.0%

MFE = +4.5%
```

### MAE

Maximum adverse excursion.

Example:

```text
price path:
-0.2%
-0.8%
-1.6%
+2.0%

MAE = -1.6%
```

Use MFE/MAE data later to optimize TP/SL.

---

# 26. Outcome Engine

Run daily after market data is finalized.

Pseudo-flow:

```python
for open_position in positions:
    update_daily_snapshot(open_position)

    if sl_triggered(open_position):
        close_as_sl(open_position)

    elif tp_triggered(open_position):
        close_as_tp(open_position)

    elif holding_days >= max_holding_days(open_position):
        close_as_expiry(open_position)
```

For ambiguous daily candles, use configured ambiguity policy.

---

# 27. Outcome Dataset

After a signal becomes mature:

```text
prediction
+
feature snapshot
+
market context
+
actual price path
+
TP/SL result
+
return
+
holding period
+
MFE
+
MAE
```

becomes training/evaluation data.

Do not train on immature signals.

---

# 28. Why Not Retrain After Every Trade?

Do not retrain after one outcome.

Bad:

```text
Trade loss
→ immediately retrain
→ deploy model
```

This creates instability and overreaction.

Recommended:

```text
daily:
    collect outcomes

weekly:
    monitor

after sufficient matured samples:
    train challenger

periodically:
    review champion vs challenger
```

Example threshold:

```text
minimum_new_matured_samples = 200–500
```

This is configurable and must be tested.

---

# 29. Retraining Pipeline

```text
Matured Outcomes
      ↓
Dataset Builder
      ↓
Train Candidate
      ↓
Time-series Validation
      ↓
Calibration
      ↓
Backtest
      ↓
Compare to Champion
      ↓
Promotion Gate
```

Never:

```text
new model trains
→ automatically becomes production
```

---

# 30. Champion / Challenger

Production:

```text
Champion v17
```

Research:

```text
Challenger v18
```

Both should be evaluated on the same unseen period.

Promotion criteria must be explicit.

Example:

```yaml
promotion:
  minimum_sample_size: 300
  min_expectancy_improvement: 0.10%
  min_profit_factor_improvement: 0.05
  max_drawdown_increase: 0
  calibration_must_not_worsen: true
```

These are initial examples, not proven optimal thresholds.

---

# 31. Measuring Whether the Model Gets Better

This is the central research objective.

Do not use accuracy alone.

## Prediction

```text
AUC
Log Loss
Brier Score
Calibration Error
```

## Trading

```text
Win Rate
Average Win
Average Loss
Profit Factor
Expectancy
Maximum Drawdown
Average Holding Period
TP Rate
SL Rate
Expiry Rate
```

## Ranking

```text
Top-K hit rate
Top-K average return
Rank IC
```

---

# 32. 500–1,000 Signal Evaluation

When enough observations accumulate, generate a comparison report.

Example:

```text
MODEL v17

Signals          1,000
Win Rate          58.4%
Avg Win            4.2%
Avg Loss          -2.0%
Profit Factor      1.61
Expectancy         0.66%
Max Drawdown      10.4%
Brier Score        0.18
```

vs:

```text
MODEL v18

Signals          1,000
Win Rate          61.1%
Avg Win            4.0%
Avg Loss          -1.8%
Profit Factor      1.78
Expectancy         0.87%
Max Drawdown       8.2%
Brier Score        0.16
```

Question:

```text
Is v18 genuinely better?
```

Answer must come from:

- out-of-sample results;
- confidence intervals where appropriate;
- consistent results across market regimes;
- no suspicious data leakage;
- realistic trading costs.

---

# 33. 500–1,000 Is Not a Magic Number

500 or 1,000 signals is a **research milestone**, not a guarantee of statistical proof.

Also analyze:

```text
by year
by sector
by market regime
by score bucket
by probability bucket
by volatility bucket
```

A model that works only in one bull market is not considered robust.

---

# 34. Time-Series Validation

Never use ordinary random split.

Required:

```text
Train → earlier
Validation → later
Test → later still
```

Example:

```text
Train:      2018–2023
Validation: 2024
Test:       2025
```

Rolling walk-forward:

```text
Train 2018–2023 → Test 2024
Train 2019–2024 → Test 2025
Train 2020–2025 → Test 2026
```

Exact dates depend on available clean data.

---

# 35. Leakage Tests

Create explicit tests for:

### Future price leakage

Ensure no feature references future rows.

### Corporate announcement leakage

Ensure fundamental/news features use publication/availability timestamp rather than event date alone.

### Normalization leakage

Scaler/transformer must fit only on training data.

### Target leakage

Do not include:

```text
future return
future high
future low
```

in features.

---

# 36. Survivorship Bias

Do not build a historical dataset only from today's surviving stocks.

Where data permits, handle:

- delisted names;
- ticker changes;
- suspended periods;
- universe changes.

Document limitations when historical survivorship-free data is unavailable.

---

# 37. Corporate Action Handling

Need explicit treatment for:

```text
stock split
reverse split
rights issue
bonus shares
dividend
```

Use provider-adjusted data only when the adjustment semantics are understood.

Document whether each series is:

```text
raw
split-adjusted
total-return adjusted
```

Do not mix adjusted and unadjusted series.

---

# 38. Backtesting

Backtest engine must simulate:

```text
signal
→ entry
→ TP/SL
→ expiry
→ fees
→ slippage
→ position sizing
```

Do not assume:

```text
signal price = exact fill price
```

unless explicitly justified.

Initial configurable cost model:

```yaml
commission_rate:
slippage_bps:
tax_rate:
```

Actual rates must be supplied by the user/provider and should not be invented by the agent.

---

# 39. Position Sizing

V1 can use simple risk-based sizing.

Example concept:

```text
Risk per trade = 0.5% of portfolio

Entry = 8,500
SL    = 8,330

Risk/share = 170

Position size = portfolio risk budget / 170
```

Position sizing must be separate from:

```text
signal probability
```

Do not increase leverage simply because confidence is high.

---

# 40. Portfolio Risk

Avoid concentration.

Track:

```text
max_positions
max_sector_exposure
max_single_position
cash_reserve
correlation_exposure
```

Example:

```text
max positions = 5
max banking positions = 2
```

Values are configurable.

---

# 41. Telegram Interface

V1 commands:

```text
/start
/daily
/signals
/positions
/performance
/model
/compare
```

Manual journal:

```text
/enter BBCA 8550 100
```

Exit:

```text
/exit BBCA 8950
```

The Telegram layer should only call application services.

Do not put ML calculations directly inside Telegram handlers.

---

# 42. Daily Telegram Output

Example:

```text
🤖 DAILY STOCK SIGNAL
06 Oct 2026

MARKET
IHSG       : Bullish
Breadth    : Positive
Volatility : Normal

━━━━━━━━━━━━━━━━

🥇 ANTM
Score           : 91/100
P(TP before SL) : 74%
Expected Return : +3.8%

Entry           : 3,950–4,000
TP              : +5%
SL              : -2%
Max Hold        : 10D

Why:
• strong momentum
• volume expansion
• sector outperforming
• market regime supportive
```

Keep the report deterministic.

LLM is optional for rewriting the explanation.

---

# 43. LLM Integration

LLM is NOT required for the core system.

Core:

```text
Data
→ Features
→ ML
→ Signal
→ Outcome
→ Retraining
```

Optional LLM layer:

```text
structured ML output
        ↓
LLM
        ↓
human-friendly explanation
```

Useful use cases:

- explain a signal;
- summarize relevant news;
- produce a natural-language morning report;
- explain why a model changed;
- help investigate anomalies.

Do not use LLM as:

```text
price truth
TP/SL calculator
outcome calculator
final risk engine
historical ledger
```

---

# 44. API Boundary

Future Node API can expose:

```text
GET /signals/today
GET /signals/:id
GET /positions
GET /performance
GET /models
GET /models/:version
GET /models/compare
POST /positions
POST /positions/:id/exit
```

Python remains responsible for ML logic.

---

# 45. Frontend V2

Dashboard pages:

```text
/
  market summary

/signals
  current + historical signals

/positions
  open/closed positions

/performance
  PnL + risk metrics

/models
  champion/challenger comparison

/backtests
  backtest runs

/research
  MFE/MAE + regime analysis
```

Frontend must never calculate financial truth differently from backend.

---

# 46. AWS Job Design

## Daily Signal Job

```text
EventBridge Scheduler
        ↓
AWS Lambda
        ↓
load latest data
        ↓
build features
        ↓
load champion model
        ↓
generate signals
        ↓
save DB
        ↓
send Telegram
```

## Outcome Job

```text
EventBridge Scheduler
        ↓
Lambda / worker
        ↓
update snapshots
        ↓
resolve matured outcomes
        ↓
save results
```

## Retraining Job

```text
scheduled/manual
        ↓
build matured dataset
        ↓
train challenger
        ↓
validate
        ↓
backtest
        ↓
promotion gate
```

---

# 47. Deployment Strategy

Do not deploy everything at once.

Recommended:

```text
Local
 ↓
Docker
 ↓
AWS development
 ↓
paper/live-signal validation
 ↓
production
```

Use separate config for:

```text
development
staging
production
```

---

# 48. CI/CD

Recommended GitHub Actions:

```text
lint
unit tests
integration tests
type checking
build
```

Do not deploy production when tests fail.

Suggested Python:

```text
ruff
pytest
mypy (optional)
```

Suggested Node:

```text
eslint
prettier
tsc --noEmit
vitest/jest
```

---

# 49. Testing Requirements

## Unit Tests

Required for:

- indicators;
- returns;
- ATR;
- RSI;
- volume ratio;
- label generation;
- TP/SL engine;
- ambiguity policy;
- position calculations;
- metrics.

## Integration Tests

Required for:

```text
data provider → pipeline
pipeline → database
signal → Telegram
position → outcome
model registry → signal engine
```

Use mocks for external services.

---

# 50. Critical Unit Test Cases

### TP hit

```text
entry = 100
TP = 105
high = 106
```

Expected:

```text
TP
```

### SL hit

```text
entry = 100
SL = 98
low = 97
```

Expected:

```text
SL
```

### Expiry

```text
10 days
TP not hit
SL not hit
```

Expected:

```text
EXPIRY
```

### Both touched

```text
high >= TP
low <= SL
```

Expected:

```text
AMBIGUOUS
```

or configured conservative behavior.

### No actual position

Signal exists but user did not enter.

Expected:

```text
signal_outcome exists
position does not
```

---

# 51. Logging

Use structured logs:

```json
{
  "event": "signal_generated",
  "ticker": "BBCA",
  "signal_id": "123",
  "model_version": "v17"
}
```

Include:

```text
job_id
model_version
data_version
ticker
timestamp
```

Never log:

```text
API secrets
tokens
passwords
```

---

# 52. Error Handling

External data failures must be explicit.

Example:

```text
Data source unavailable
→ do not generate incomplete signals
→ alert
→ preserve previous valid data
```

Do not silently fill missing market data with fake values.

---

# 53. Data Quality Checks

Before model execution:

```text
ticker count reasonable
date reasonable
missing data threshold
duplicate rows = 0
price sanity
volume sanity
```

If critical validation fails:

```text
STOP SIGNAL GENERATION
```

Sending no signal is better than sending a signal based on corrupted data.

---

# 54. Model Registry

Every model artifact must store metadata:

```yaml
model_version: v17
algorithm: lightgbm
dataset_version: dataset_2026_09
feature_version: features_05
training_start: 2018-01-01
training_end: 2026-06-30
validation_start: 2026-07-01
validation_end: 2026-08-31
metrics:
  brier_score:
  profit_factor:
  expectancy:
  max_drawdown:
status: champion
```

---

# 55. Model Promotion Rules

Only promote if:

1. test period is strictly unseen;
2. minimum sample size is reached;
3. trading expectancy does not deteriorate materially;
4. max drawdown does not worsen beyond allowed tolerance;
5. calibration is acceptable;
6. no new leakage is found;
7. results are not dependent on one tiny subset;
8. code/tests pass.

Agent must produce a promotion report before changing:

```text
is_production = true
```

---

# 56. Rollback

If the current production model degrades:

```text
v18
```

must be able to rollback to:

```text
v17
```

without retraining.

Store immutable model artifacts.

---

# 57. Daily/Weekly/Monthly Operations

## Daily

```text
ingest data
validate
generate signals
send Telegram
update positions
resolve outcomes
```

## Weekly

```text
performance review
data quality review
model drift review
regime analysis
```

## Monthly

```text
champion/challenger review
retraining if enough data
TP/SL analysis
portfolio analytics
```

---

# 58. Model Drift Detection

Monitor rolling windows:

```text
last 50 signals
last 100
last 200
last 500
```

Compare against historical baseline.

Alert examples:

```text
Win Rate significantly below baseline
Brier Score deteriorating
Probability calibration degrading
Profit Factor collapsing
```

Do not automatically retrain solely because of one bad week.

---

# 59. Regime Analysis

Every outcome must be joinable with:

```text
market regime
sector
volatility regime
probability bucket
score bucket
```

Then generate:

```text
Bull:
win rate 68%

Sideways:
win rate 55%

Bear:
win rate 42%
```

This lets us determine where the model actually works.

---

# 60. MFE/MAE Research

After enough data:

```text
probability bucket
→ average MFE
→ average MAE
→ best TP
→ best SL
→ best holding period
```

This can drive future dynamic TP/SL research.

Do not automatically deploy optimized thresholds from the same test period used to discover them.

---

# 61. Dynamic TP/SL Roadmap

V1:

```text
fixed 5% / 2%
```

Research:

```text
ATR-based
```

Then:

```text
regime-aware
```

Then:

```text
ML-estimated favorable excursion
ML-estimated adverse excursion
```

Potential output:

```text
High confidence + low volatility
→ TP 3.8%
→ SL 1.6%

High confidence + strong trend
→ TP 6.2%
→ trailing exit
```

These are examples only. The system must learn them from historical data.

---

# 62. Future Fundamental Model

Add features:

```text
PER
PBV
ROE
ROA
DER
EPS growth
Revenue growth
Net income growth
cash flow
dividend yield
```

Fundamental data requires **availability timestamps**.

Do not use current fundamentals to backtest old dates unless historical availability is accurately reconstructed.

---

# 63. Future News / LLM Layer

Architecture:

```text
News
 ↓
timestamp filtering
 ↓
NLP / LLM
 ↓
structured sentiment/event features
 ↓
ML model
```

Possible events:

```text
earnings surprise
contract win
regulatory issue
corporate action
management change
```

The LLM output must become structured data with clear provenance.

---

# 64. Future Ensemble

Later:

```text
Logistic Regression
LightGBM
XGBoost
```

Then:

```text
ensemble probability
```

But benchmark each individual model first.

Do not add ensemble complexity before single-model baselines are understood.

---

# 65. Suggested Implementation Phases

## PHASE 0 — Repository Bootstrap

Agent tasks:

- initialize repo;
- create structure;
- create Python environment;
- create `.env.example`;
- configure lint/test;
- create README;
- create config system.

Acceptance:

```text
pytest passes
lint passes
project starts locally
```

---

## PHASE 1 — Data Layer

Implement:

```text
provider interface
CSV provider
database models
data validation
ingestion CLI
```

Commands:

```text
python -m scripts.ingest_daily
python -m scripts.validate_data
```

Acceptance:

- no duplicate ticker/date;
- schema valid;
- sample data queryable;
- tests pass.

---

## PHASE 2 — Feature Engine

Implement:

```text
momentum
trend
RSI
ATR
volume
market regime
sector strength
```

Acceptance:

- deterministic output;
- no future data usage;
- feature tests pass;
- feature snapshot reproducible.

---

## PHASE 3 — Label Engine

Implement:

```text
TP/SL label
max holding
ambiguity handling
```

Acceptance:

- exact edge cases tested;
- labels reproducible;
- daily OHLC ambiguity documented.

---

## PHASE 4 — Baseline Models

Implement:

```text
Logistic Regression
LightGBM
```

Acceptance:

- time-series split;
- metrics report;
- saved artifact;
- prediction schema.

---

## PHASE 5 — Backtesting

Implement:

```text
entry
TP
SL
expiry
fees
slippage
metrics
```

Acceptance:

- backtest has no lookahead;
- results reproducible;
- unit/integration tests pass.

---

## PHASE 6 — Signal Engine

Implement:

```text
probability
expected return
score
ranking
entry
TP
SL
max hold
```

Acceptance:

- Top-N signal list generated;
- full signal record saved;
- model version persisted.

---

## PHASE 7 — Telegram

Implement:

```text
/daily
/signals
/positions
/performance
/model
/compare
```

Acceptance:

- Telegram receives daily signal;
- failed API call logs correctly;
- message formatting deterministic.

---

## PHASE 8 — Manual Position Journal

Implement:

```text
/enter
/exit
```

Acceptance:

- signal without position remains distinct;
- actual fill price is stored;
- fees supported.

---

## PHASE 9 — Outcome Engine

Implement:

```text
daily snapshots
MFE
MAE
TP
SL
expiry
```

Acceptance:

- positions resolve correctly;
- matured outcomes available to training dataset;
- ambiguous cases follow policy.

---

## PHASE 10 — Model Evaluation

Implement dashboard/report for:

```text
win rate
profit factor
expectancy
drawdown
Brier score
calibration
```

Acceptance:

- champion/challenger comparison available;
- out-of-sample period clear;
- report reproducible.

---

## PHASE 11 — Retraining

Implement:

```text
dataset builder
candidate trainer
evaluation
promotion gate
registry
rollback
```

Acceptance:

- challenger never auto-promoted without gate;
- old model remains available;
- version metadata complete.

---

## PHASE 12 — AWS Deployment

Deploy:

```text
EventBridge
Lambda
database
S3
secret storage
CloudWatch
```

Acceptance:

- scheduled job works;
- data validation works;
- daily Telegram arrives;
- outcome update works;
- logs accessible;
- failure alert works.

---

## PHASE 13 — Next.js Dashboard

Only after V1 is stable.

Implement:

```text
Signals
Positions
Performance
Models
Backtests
Research
```

---

# 66. Agent Task Execution Rules

When implementing a phase, the coding agent must:

1. inspect the existing repository first;
2. identify affected modules;
3. make the smallest coherent change;
4. write/update tests;
5. run tests;
6. run lint/type checks;
7. update docs;
8. report changed files;
9. report remaining risks;
10. only then move to the next phase.

Do not implement all phases in one giant commit.

---

# 67. Definition of Done

A task is DONE only when:

```text
Code exists
AND
tests exist
AND
tests pass
AND
lint/type checks pass
AND
docs are updated
AND
configuration is documented
AND
no known future-data leakage is introduced
```

---

# 68. Git Strategy

Recommended:

```text
main
develop

feature/data-layer
feature/features
feature/ml
feature/backtest
feature/telegram
feature/positions
feature/retraining
feature/aws
```

Commit messages:

```text
feat: add daily market data ingestion
feat: add ATR and RSI features
feat: implement TP/SL label engine
test: add ambiguity cases
fix: prevent future leakage in feature window
```

Never commit:

```text
.env
API keys
private credentials
large raw datasets
model secrets
```

---

# 69. Documentation Agent Must Maintain

Required:

```text
README.md
docs/architecture.md
docs/data-contract.md
docs/ml.md
docs/backtesting.md
docs/retraining.md
docs/telegram.md
docs/deployment.md
docs/model-registry.md
```

---

# 70. Research Notebook Policy

Notebooks are allowed for exploration.

But production logic must eventually move to:

```text
python/
```

Do not leave critical business logic only inside notebooks.

Every notebook that influences a production feature must state:

```text
dataset version
date
experiment objective
result
next action
```

---

# 71. Experiment Tracking

Each experiment should store:

```text
experiment_id
date
features
model
hyperparameters
train period
validation period
test period
metrics
notes
```

Example:

```text
exp_042

Model:
LightGBM

Feature set:
features_05

Label:
TP +5% before SL -2%, max 10D

Result:
PF 1.62
Expectancy +0.71%
```

---

# 72. Avoid Overfitting

Agent must not optimize:

```text
TP
SL
feature weights
probability threshold
holding period
```

against the final test set repeatedly.

Use:

```text
training
validation
test
```

with test treated as a final holdout.

---

# 73. Probability Threshold Research

Do not assume:

```text
probability >= 70% = BUY
```

automatically.

Research:

```text
50%
55%
60%
65%
70%
75%
```

on validation only.

Select threshold based on objective criteria.

Then evaluate once on test.

---

# 74. Ranking Research

Eventually compare:

```text
Top 3
Top 5
Top 10
```

and assess:

```text
average return
win rate
drawdown
turnover
```

---

# 75. Data Frequency Roadmap

V1:

```text
Daily
```

V2:

```text
15m / 30m
```

V3:

```text
5m
```

Only move to finer frequency after the daily system has a measurable edge and reliable data source.

---

# 76. Security

Production secrets:

```text
AWS Secrets Manager
or
SSM Parameter Store
```

IAM:

```text
least privilege
```

Telegram token must never appear in logs.

Database should not be publicly exposed.

---

# 77. Monitoring and Alerts

Alert when:

```text
data ingestion fails
feature build fails
model loading fails
signal count abnormal
Telegram fails
database unavailable
model drift detected
```

An abnormal signal count example:

```text
normal = 5–30 signals
today = 0
```

should trigger investigation rather than silently being treated as "no opportunity".

---

# 78. Operational Safety

Because this is a financial decision-support system:

- signal must be labeled as model-generated;
- no guarantee of profitability;
- all performance reports must show methodology;
- backtest results must identify assumptions;
- live results must be separated from simulated results.

---

# 79. Final V1 Deliverable

The agent is finished with V1 when the following works end-to-end:

```text
Historical data
      ↓
Features
      ↓
Champion model
      ↓
Daily top 5–10 signals
      ↓
Telegram
      ↓
User manually records entry
      ↓
Daily position tracking
      ↓
TP/SL/expiry outcome
      ↓
Matured training data
      ↓
Evaluation report
      ↓
Challenger model
      ↓
Champion vs Challenger
```

---

# 80. Final Research Goal

The system should eventually answer these questions automatically:

### Q1
Which stocks have the best expected risk-adjusted opportunity today?

### Q2
What TP/SL/horizon is historically sensible for this type of signal?

### Q3
Where does the model work best?

```text
bull / sideways / bear
sector
volatility
probability bucket
score bucket
```

### Q4
Does the model remain calibrated?

### Q5
Does performance survive realistic fees and slippage?

### Q6
After 500–1,000+ matured signals:

> **Is there evidence that the model has a stable edge?**

### Q7
Is model v18 objectively better than model v17?

### Q8
If the model gets worse:

> Can we detect drift, understand why, and roll back?

---

# 81. Future Architecture

```text
                         ┌──────────────────┐
                         │   BEI DATA       │
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │ FEATURE STORE    │
                         └────────┬─────────┘
                                  ▼
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
             CLASSIFICATION               REGRESSION
             P(TP before SL)              Expected Return
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                            RISK ENGINE
                                  ▼
                           SIGNAL RANKING
                              │      │
                              ▼      ▼
                          TELEGRAM  WEB
                              │
                         MANUAL TRADE
                              │
                              ▼
                        POSITION TRACKER
                              │
                              ▼
                         OUTCOME ENGINE
                              │
                              ▼
                        MODEL EVALUATION
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
              CHAMPION               CHALLENGER
                  │                       │
                  └───────────┬───────────┘
                              ▼
                         PROMOTION GATE
                              │
                              ▼
                         NEW CHAMPION
```

Optional later:

```text
News → LLM/NLP → structured event features
```

Optional later:

```text
Next.js dashboard
```

Optional much later:

```text
broker API execution
```

---

# 82. Non-Negotiable Principles

## Principle 1
**Prediction history is immutable.**

## Principle 2
**Actual positions are separate from signals.**

## Principle 3
**Outcome calculation is deterministic.**

## Principle 4
**Time-series evaluation is chronological.**

## Principle 5
**No future data leakage.**

## Principle 6
**Backtests include realistic costs.**

## Principle 7
**New models are challengers first.**

## Principle 8
**Model promotion requires evidence.**

## Principle 9
**LLM is optional and secondary.**

## Principle 10
**500–1,000+ signals are a milestone for research, not a promise of statistical certainty.**

---

# 83. Agent Instruction — Start Here

When this repository is first opened, the agent should NOT immediately start coding the whole system.

First:

```text
1. Read this document.
2. Inspect repository state.
3. Produce implementation plan.
4. Identify data provider assumptions.
5. Identify missing credentials/config.
6. Bootstrap Phase 0.
7. Stop and report.
```

Then continue phase-by-phase.

For each phase, output:

```text
PHASE:
Goal:
Files changed:
Tests added:
Commands run:
Result:
Known limitations:
Next phase:
```

Do not silently skip acceptance criteria.

---

# 84. Recommended Initial Commands

After repository creation:

```bash
git init
```

Python environment:

```bash
python -m venv .venv
```

Install project dependencies using the project's package manager and lockfile.

Run:

```bash
pytest
```

Lint:

```bash
ruff check .
```

Format:

```bash
ruff format .
```

Node setup:

```bash
npm install
```

Type check:

```bash
npm run typecheck
```

Exact commands may change according to the final chosen package manager, but they must be documented in `README.md`.

---

# 85. Official Documentation Starting Points

AWS Lambda runtimes:

https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html

AWS Lambda Python:

https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html

Node.js releases:

https://nodejs.org/en/about/previous-releases/

Python:

https://www.python.org/

scikit-learn:

https://scikit-learn.org/stable/

LightGBM:

https://lightgbm.readthedocs.io/

XGBoost:

https://xgboost.readthedocs.io/

pandas:

https://pandas.pydata.org/docs/

PostgreSQL:

https://www.postgresql.org/docs/

Telegram Bot API:

https://core.telegram.org/bots/api

Next.js:

https://nextjs.org/docs

---

# 86. Final Instruction to Coding Agent

Build the simplest correct version first.

The project must evolve in this order:

```text
DATA
→ FEATURES
→ LABELS
→ BASELINE MODEL
→ BACKTEST
→ SIGNALS
→ TELEGRAM
→ POSITION JOURNAL
→ OUTCOMES
→ EVALUATION
→ CHALLENGER
→ AWS
→ DASHBOARD
→ ADVANCED ML
→ OPTIONAL LLM
```

Do not reverse this order merely because a more sophisticated feature looks attractive.

The system's long-term value comes from **clean historical records and honest evaluation**, not from complexity.

The most important dataset in this project is not just OHLCV.

It is:

```text
WHAT DID THE MODEL BELIEVE?
+
WHAT ACTUALLY HAPPENED?
+
UNDER WHICH MARKET CONDITIONS?
+
WHICH MODEL VERSION MADE THE PREDICTION?
```

That dataset is what allows the system to answer the central research question:

> **"Setelah 500 atau 1.000 signal, apakah model benar-benar makin baik?"**
