# Dual-Mode BEI Stock Signal — AI Coding Agent Guide

**Document:** `06_dual_mode_BEI_stock_signal_agent_guide.md`  
**Use with:** `04_ai_agent_coding_development_guide_BEI_stock_signal.md` and `05_dataset_and_market_data_agent_guide.md`  
**Project status:** Phase 12 reported PASS; Phase 13 dashboard is optional. This is an enhancement, not a rebuild.

> Goal: ingest all verifiable BEI tickers available from the chosen provider, screen two price ranges, train independent ML models, and release only validated daily signals. Preserve existing working code and audit before changing it.

---

## 1. Confirmed product decision

| Mode | Price at the decision/signal time | Model |
|---|---:|---|
| `LOW_PRICE` | IDR 50–300, inclusive | Independent classifier and model lifecycle |
| `HIGHER_PRICE` | Strictly above IDR 300 | Independent classifier and model lifecycle |
| Excluded from signals | Below IDR 50 | Keep data where available; no signal in either mode |

Price bucket is not market capitalization. A low nominal price does not automatically mean a small market cap or a good opportunity.

Fetch and store all verifiable tickers, not just today's low-price list. Assign each historical sample to a mode based on the price available at that sample's decision time—not today's price. A previously created signal keeps its original mode and model version, even if the stock later crosses a boundary.

Use the validated current provider adapter and canonical market-data schema. `yfinance.download()` supports bulk daily downloads and start/end date ranges, but coverage varies by ticker and intraday history is limited. Verify provider results, do not invent missing tickers/bars, and review usage rights before production or redistribution.

References:
- https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- https://github.com/ranaroussi/yfinance
- https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

---

## 2. Historical training and forward test

### Recommended path

- **1 year:** useful to validate ingestion, feature/label generation, model training, and end-to-end pipeline. Treat resulting model as experimental/paper-only, not as proof of trading edge.
- **3–5 years:** preferred minimum starting point for meaningful initial historical backtests, if coverage and price adjustments are adequate.
- **5–10 years:** target where available and useful for covering more market regimes; do not force the same history length for every ticker.
- **Daily forward test:** start saving immutable predictions from the next valid trading date after candidate validation.

Why not train and fully retrain every day? Daily should mean update data, generate signals, store predictions, resolve outcomes that have matured, and monitor. Retraining every day can overreact to noise. Retrain on a schedule or when enough new mature observations exist, then evaluate the new model as a challenger.

Example configuration (experiment defaults, not guarantees):

```yaml
history:
  preferred_years: 5
  minimum_years_for_candidate_research: 3
  one_year_is_pipeline_test_only: true

labels:
  tp_pct: 0.05
  sl_pct: 0.02
  max_holding_trading_days: 10

retraining:
  schedule: monthly
  min_new_matured_samples_per_mode: 200
  auto_promote: false

forward_test:
  enabled: true
  keep_predictions_immutable: true
```

The threshold of 200 new matured rows per mode is a configurable trigger for considering retraining, not proof of statistical sufficiency. Account for correlated stocks and overlapping 10-day outcome windows.

### Backtest and forward-test separation

```text
3–5+ years historical data
          ↓
chronological walk-forward backtest
          ↓
candidate model evaluation
          ↓
promotion gate
          ↓
daily forward predictions on unseen dates
          ↓
freeze prediction + model/config version
          ↓
resolve TP/SL/expiry when known
          ↓
evaluate actual forward performance
          ↓
periodic challenger retraining
```

Never random-split stock-day rows. Split chronologically by decision date and apply an appropriate purge/embargo for labels whose outcome windows overlap across train/test. Keep backtest, forward signals, and actual manual positions reported separately.

---

## 3. Data ingestion rules

### Initial backfill

1. Load a versioned, verified ticker universe.
2. Fetch daily (`1d`) bars for 3–5 years where available.
3. Use conservative batches, bounded retries, and provider error logging.
4. Normalize responses to the existing canonical schema.
5. Validate OHLCV, duplicates, missing coverage, price conventions, and corporate actions.
6. Upsert idempotently; record per-ticker fetch status.
7. Produce a coverage report before training.

Do not claim all BEI stocks were fetched if some ticker symbols failed or lack history. Report requested/succeeded/partial/failed tickers and observed date ranges.

### Daily update

Do not redownload the full history each day.

```text
after EOD data is available
  → fetch recent overlap window
  → validate
  → upsert by ticker/date/interval/provider
  → verify latest completed trading date
  → update features
  → generate signals only if core data quality passes
```

Use the overlap/retry values already configured in the repository. A missing bar does not prove suspension; classify missing data cautiously. Invalid or incomplete critical data must block signal generation. A correction to historical market data must not silently rewrite already-sent signals or prediction snapshots.

### Raw versus adjusted prices

- Preserve provider raw observations and corporate-action fields.
- Do not combine raw Close with adjusted High/Low in one TP/SL label path.
- Handle splits explicitly; handle dividends consistently and separately where appropriate.
- Record the price-adjustment and label-policy versions.
- If data quality prevents credible corporate-action handling, document it and do not claim realistic performance.

---

## 4. Historical mode assignment

At each decision date, use the most recent *completed* close known at that time:

```python
if 50 <= decision_close <= 300:
    mode_id = "LOW_PRICE"
elif decision_close > 300:
    mode_id = "HIGHER_PRICE"
else:
    mode_id = "EXCLUDED_BELOW_50"
```

Boundary tests are mandatory:

```text
49.99  → excluded from signals
50.00  → LOW_PRICE
300.00 → LOW_PRICE
300.01 → HIGHER_PRICE
NaN    → invalid, no signal
```

Use the application's appropriate numeric/decimal representation. If a stock crosses the boundary later, that changes mode eligibility for a future signal only. It must not change an old signal's stored mode or reset its outcome tracking.

Mode filtering is separate from liquidity and tradeability checks. Do not send a BUY just because a stock is inside a price range.

---

## 5. Independent models and registry

Use independent model identities:

```text
LOW_PRICE
  dataset/version
  feature schema/version
  label policy/version
  classifier and optional return regressor
  calibration
  champion + challengers
  evaluation metrics
  promotion/rollback history

HIGHER_PRICE
  dataset/version
  feature schema/version
  label policy/version
  classifier and optional return regressor
  calibration
  champion + challengers
  evaluation metrics
  promotion/rollback history
```

Shared infrastructure is encouraged: same provider adapter, canonical schema, feature functions, label engine, backtest engine, database, Telegram integration, scheduler and logging. The **trained artifacts, dataset assignment, calibration, metrics, champion state, and promotion decisions must be separate**.

Do not copy one model artifact and call it two models. Train each independently on its own eligible historical samples. If either mode has too few samples or poor class balance, mark that model `EXPERIMENTAL`/`PAPER_ONLY`; do not silently borrow the other mode's training rows.

Persist at least:

```text
model_id, mode_id, model_version
dataset_version, feature_version, label_policy_version
train/validation/OOS date ranges
sample counts and class distribution
metrics and artifact checksum
model status, promotion decision, rollback target
```

---

## 6. Keep the initial trading objective stable

To limit simultaneous changes, both models should initially target the existing swing setup:

```text
TP = +5%
SL = -2%
maximum holding = 10 trading days
```

Classification target:

```text
1 = TP touched before SL within the horizon
0 = SL first or expiry, according to documented label policy
```

Store outcome states separately:

```text
TP / SL / EXPIRY / AMBIGUOUS / INVALID_DATA
```

Daily OHLC cannot tell which threshold happened first if TP and SL are both touched in one candle. Use the established conservative policy or mark it ambiguous. Do not assume TP happened first. Use verified, versioned exchange tick-size rules when rounding entry/TP/SL; do not hardcode potentially outdated rules.

Mode-specific TP/SL or holding periods can be researched later as separate experiments. Do not repeatedly optimize those values on the final test set.

---

## 7. Investigate the current 0% probability / N/A issue first

The recent Telegram output showed `P(TP before SL) = 0%`, `Expected Return = N/A`, and a composite score of 8/100 while the active model reportedly used only about 10 trading days of mock data. Do not assume retraining alone fixes this.

The coding agent must audit:

1. Which model artifact is active and whether it is production-eligible.
2. Whether the positive `predict_proba()` class really maps to `TP before SL`.
3. Whether training data has sufficient real, validated rows and appropriate class balance.
4. Whether inference feature names/order/dtypes/transforms match training exactly.
5. Whether a 0 probability is a real model output versus a mapping/serialization error.
6. Why expected return is N/A and whether a required regressor is missing or failed.
7. Whether mock data can reach production training or model promotion.
8. Whether model validity/status is enforced by the Signal Engine.

### Fail-closed BUY policy

No BUY if any required condition fails:

```text
model is not production-eligible
OR probability missing/non-finite/invalid
OR expected return is required but unavailable
OR feature schema mismatch
OR core data quality fails
OR price is outside the mode
OR required liquidity/risk gate fails
  → NO BUY / WATCH / MODEL INVALID
```

Never allow a liquidity-only composite score to turn an invalid model prediction into a BUY. If expected return is optional for a specific strategy, that must be explicit in configuration and the message must clearly show the field is unavailable—not invent a number.

---

## 8. Mode-specific dataset builder

Build datasets separately, using a shared implementation:

```text
build_dataset(mode="LOW_PRICE")
build_dataset(mode="HIGHER_PRICE")
```

Each sample should be traceable to:

```text
ticker
decision_date
mode_id
decision_price
feature_snapshot
label
label_start_date
label_end_date
outcome_status
universe_version
market_data_version
feature_version
label_policy_version
```

Requirements:

- assign mode from the historical decision price;
- only use labels that have matured for supervised retraining;
- exclude or explicitly handle ambiguous/invalid labels;
- never pad missing history with fake bars;
- report sample count, class balance, dates, missingness, and ticker coverage per mode;
- block training if configurable minimum sample/class criteria fail;
- use chronological validation/OOS splits and purge overlapping outcomes;
- keep immature forward signals out of the labeled training set.

---

## 9. Evaluation criteria

Evaluate each mode independently. At minimum report:

**Data/model**
- sample count and class balance;
- AUC where meaningful, log loss, Brier score, calibration;
- training/validation/OOS dates;
- missing-data and excluded-label counts.

**Trading**
- win rate;
- average win/loss;
- expectancy;
- profit factor;
- maximum drawdown;
- TP/SL/expiry/ambiguous rates;
- fees and slippage;
- breakdown by year and market regime.

A 500–1,000-signal milestone is useful for long-term research, not a guarantee of significance. Stocks can be correlated and label horizons overlap. Do not claim profitability because tests pass or because a single backtest looks good.

---

## 10. Champion/challenger and promotion

Maintain separate promotion tracks:

```text
LOW_PRICE: champion A → challenger A → gate A
HIGHER_PRICE: champion B → challenger B → gate B
```

Promotion in one mode must never replace the other mode's champion.

Default:

```yaml
auto_promote: false
```

Promotion requires real validated data, chronological OOS testing, acceptable calibration and trading-cost metrics, a persisted comparison report, and a passing promotion gate. Preserve the previous champion and test rollback. Never use `--force --auto-promote` as a shortcut.

---

## 11. Telegram design

Report the two modes separately:

```text
DAILY STOCK SIGNAL

MODE A — LOW_PRICE (IDR 50–300)
1. TICKER
   Status: BUY / WATCH
   Probability: ...
   Expected return: ...
   Entry / TP / SL: ...
   Horizon: ...
   Model: low_price_vX
   Reasons: ...

MODE B — HIGHER_PRICE (> IDR 300)
1. TICKER
   Status: BUY / WATCH
   Probability: ...
   Expected return: ...
   Entry / TP / SL: ...
   Horizon: ...
   Model: higher_price_vX
   Reasons: ...
```

Rules:
- Include mode ID and model version.
- Return `NO SIGNAL` when no candidate passes hard gates; do not force a fixed number of BUY signals.
- Show a clear reason when output is `WATCH`, `MODEL INVALID`, or `N/A`.
- Do not show invalid model output as a normal BUY candidate.
- A score is not a probability. Label them separately.
- Keep old signals immutable if provider data is corrected later.

---

## 12. Implementation workflow for the agent

This is a post-Phase-12 enhancement, not a request to repeat the whole roadmap.

### Step 1 — Audit current code first

Report:
- current commit/deployed version;
- active model ID and data source;
- whether mock data can reach production;
- current universe and actual data coverage;
- price filtering implementation;
- scoring formula;
- exact cause of `0%` probability / `N/A` return;
- registry, promotion-gate and rollback behavior;
- current tests for relevant areas.

### Step 2 — Fix correctness defects

Resolve model-class mapping, feature schema, expected-return availability, mock-data contamination, and fail-closed BUY guardrails. Add regression tests.

### Step 3 — Expand and validate data

Bulk-fetch historical daily data for all verifiable tickers. Prefer 3–5 years for initial backtests where available; document ticker-level coverage and failures. Continue daily incremental upserts.

### Step 4 — Mode assignment + datasets

Add boundary and historical-mode tests. Produce separate dataset reports and confirm sample counts/class balance.

### Step 5 — Candidate training + OOS evaluation

Train one candidate per mode, independently. Store artifacts and reports. No automatic promotion.

### Step 6 — Staging/canary

Send dual-mode outputs in staging or explicitly labeled paper mode. Verify price mode, model version, probability, expected return, tick rounding, risk filters, and outcome tracking.

### Step 7 — Promote only after gate passes

Keep prior champions available. Promote each mode independently. Monitor daily forward predictions and resolve outcome only after TP/SL/expiry is known.

---

## 13. Required tests / release acceptance

### Mode assignment
- 50 and 300 inclusive map to `LOW_PRICE`.
- >300 maps to `HIGHER_PRICE`.
- below 50 excluded from both signal modes.
- invalid prices rejected.
- old signal's mode never changes after later price movement.

### Training/data
- real-data-only promotion rule works;
- positive-class mapping is correct;
- immature labels are excluded from training;
- ambiguous candles follow configured policy;
- chronology and purge prevent overlapping-label leakage under the implementation;
- mode datasets and class distributions are reported.

### Lifecycle
- each model has independent identity/artifact/metrics;
- promotion or rollback in one mode does not affect the other;
- failed challenger cannot replace champion;
- invalid probability, required missing return, schema mismatch, or bad data blocks BUY.

### Integration
- incremental upsert is idempotent;
- invalid core data prevents signal generation;
- corrected bars do not rewrite historical predictions;
- Telegram shows separate mode groups or `NO SIGNAL`;
- backtest and forward-test metrics are reported separately.

**Mark the enhancement PASS only when tests, lint and type checks actually run and acceptance evidence is reported.** Do not claim a model has a trading edge just because the software tests pass.

---

## 14. What not to build now

Do not add these without a measured need:
- LLM-based BUY/SELL decisions;
- broker auto-trading;
- intraday 1m/5m pipeline;
- neural networks or complicated ensembles;
- duplicate infrastructure for each mode;
- mandatory Next.js dashboard before daily signals are stable;
- automatic replacement of models every day;
- an artificial requirement to always return BUY candidates.

## Final definition of done

```text
all verifiable tickers ingested and quality-checked
  → recent bars updated idempotently each trading day
  → historical samples assigned to correct mode
  → separate LOW_PRICE and HIGHER_PRICE datasets
  → independent candidate models trained on real data
  → walk-forward backtests and reports per mode
  → separate champion/challenger gates and rollback
  → invalid models/data cannot create BUY signals
  → Telegram shows accurate dual-mode results
  → forward predictions are immutable
  → matured outcomes are tracked and evaluated
```

The long-term question remains: **does each mode's model show a stable out-of-sample edge, and does its challenger genuinely beat its own champion?**
