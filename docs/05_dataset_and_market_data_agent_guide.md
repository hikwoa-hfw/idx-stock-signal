# Dataset & Market Data Ingestion Guide for AI Coding Agents
## AI Indonesian Stock Daily Signal Generator — BEI / IDX

**Document ID:** DATA-001  
**Related guide:** `04_ai_agent_coding_development_guide_BEI_stock_signal.md`  
**Project status:** Development is currently at Phase 6 (Signal Engine).  
**Prototype provider:** `yfinance`  
**Initial interval:** Daily OHLCV (`1d`)  
**Initial development universe:** Approximately 200 liquid BEI stocks  
**Initial history target:** Around 10 years, subject to ticker-level availability and data quality

> This is an addendum to the main coding guide, not a replacement. The coding agent must inspect the existing repository and reuse working components rather than rebuild completed phases unnecessarily.

---

# 1. Goal

Implement a repeatable market-data pipeline that:

1. bulk-fetches historical daily bars for an initial development universe;
2. validates and stores the results;
3. fetches new bars after each completed BEI session when the provider has published the data;
4. performs idempotent upserts, including a small overlap window to repair late or changed data;
5. records ticker-level success/failure and data-quality outcomes;
6. distinguishes raw provider values from adjusted research data;
7. makes validated data available to the existing Phase 6 Signal Engine;
8. allows the provider to be replaced later without rewriting ML/signal logic.

The pipeline must not assume `yfinance` provides complete, timely, correct data for every IDX symbol. Missing or suspicious data must be reported, never silently fabricated.

# 2. V1 Defaults

Use configuration, not hardcoded business logic:

```yaml
market_data:
  provider: yfinance
  exchange: IDX
  interval: 1d
  initial_history_start: "2016-01-01"
  universe_target: 200
  overlap_calendar_days: 10
  bulk_batch_size: 25
  max_workers: 4
  retry_attempts: 4
  retry_backoff_seconds: [2, 5, 10, 20]
  require_completed_daily_bar: true
```

These are starting values, not guarantees imposed by Yahoo. Adjust batch size and concurrency down if requests are throttled or unreliable. A target of 200 tickers is for initial engineering and research; it is not a claim that the universe is optimal or free of survivorship bias.

`2016-01-01` targets roughly ten years of history as of 2026. Each ticker may have a later first observation, and the pipeline must report actual coverage. In `yfinance`, `start` is inclusive and `end` is exclusive; calculate the effective date range explicitly.

# 3. Provider Caveats and References

- `yfinance.download()` API: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- `yfinance` repository: https://github.com/ranaroussi/yfinance
- Yahoo Developer Network legal guidance: https://legal.yahoo.com/us/en/yahoo/guidelines/ydn/index.html
- IDX market data services: https://www.idx.id/id/produk/layanan-data-bei/
- IDX daily stock summary: https://idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/

`yfinance` is a community-maintained wrapper around Yahoo Finance endpoints, not an official licensed IDX market-data feed with a service-level guarantee. Its documented intraday history is limited (the current documentation says intraday bars cannot extend beyond the most recent 60 days); do not rely on it to resolve TP/SL ordering across many years of history.

Before persistent cloud storage, redistribution, a public product, or commercial use, review applicable provider terms and usage rights. Do not assume publicly accessible means unrestricted storage/redistribution. Keep the provider behind an adapter so a properly licensed source can be substituted if required.

# 4. Initial Universe: ~200 Liquid Stocks

## 4.1 Source file

Use a versioned file such as:

```text
configs/universe/seed_universe.csv
```

Suggested fields:

```text
ticker,company_name,sector,exchange,selected_as_of,selection_source,selection_reason,active
```

Use valid Yahoo ticker symbols for IDX names (commonly with `.JK`, e.g. `BBCA.JK`), and validate every symbol with the provider. Do not invent symbols simply to reach 200. If there are not yet 200 verified tickers, use a smaller real universe for the first end-to-end run and report the shortfall.

## 4.2 Liquidity-selection policy

Prefer average daily trading **value** rather than volume alone. Define a reproducible selection process—for example, average trading value over the preceding 60 or 90 trading days, subject to data-quality and minimum-coverage filters. Save the source, measurement period, and `selected_as_of` date.

If only Yahoo `Close` and `Volume` are available, `close × volume` may be used as a clearly labelled *turnover proxy*, only after validating volume units. Do not silently equate this proxy with official IDX traded value.

## 4.3 Avoid survivorship bias

The 200 stocks liquid today are a valid **development universe**, but they must not be represented as the top 200 stocks at every date in the past. Historical backtests using today's universe can suffer survivorship bias.

For V1, document this limitation. Later, add point-in-time membership where reliable information exists:

```text
ticker,effective_from,effective_to,selected_as_of,selection_metric,selection_source
```

Historical evaluation should consider ticker changes, suspensions, delisted names, and stocks that were eligible at the time. Never claim a survivorship-free backtest unless the data actually supports it.

# 5. Initial Bulk Fetch

Run a historical backfill once to seed the dataset. Example provider request:

```python
import yfinance as yf

frame = yf.download(
    tickers=batch_tickers,
    start="2016-01-01",
    end=effective_end_exclusive,
    interval="1d",
    auto_adjust=False,
    actions=True,
    group_by="ticker",
    threads=False,
    progress=False,
    timeout=20,
)
```

Implementation requirements:

- Explicitly set `auto_adjust=False`; do not rely on changing library defaults.
- Request corporate-action fields when available.
- Normalize the provider's returned layout in one adapter function. Multi-ticker and single-ticker results may have different column layouts; cover both with tests.
- A successful HTTP/library call does not guarantee all requested tickers returned data.
- Process batches conservatively (start with 25 tickers, at most four concurrent batches) and adapt based on observed failures/throttling.
- Use bounded retries with backoff for transient errors.
- Report errors per ticker; one failed ticker must not hide successful results for the others.
- Do not report a partially failed run as full success.

Required command, adapting to existing CLI conventions:

```bash
python -m scripts.ingest_daily --mode backfill
```

Support configurable ticker source, date range, batch size, retries, a summary, and a nonzero/partial exit status when appropriate.

# 6. Daily Incremental Fetch and Upsert

After the initial fetch, **do not re-download ten years of history every day**.

## Daily flow

```text
After IDX market close / data publication window
        ↓
Determine latest expected trading date
        ↓
Fetch recent window (including overlap)
        ↓
Normalize + validate
        ↓
Upsert by unique key
        ↓
Check latest-date coverage and data quality
        ↓
Proceed to features/signals only when policy passes
```

Start with an overlap of 10 **calendar days**. This allows a missed run or recent provider correction to be repaired; it is not a requirement to fetch the complete historical dataset again. Schedule after the likely EOD publication window, but do not promise a fixed time at which Yahoo data must be available. Check the returned latest date and retry within a bounded window.

Required command:

```bash
python -m scripts.ingest_daily --mode incremental
```

## Upsert key

Use a unique constraint equivalent to:

```text
UNIQUE(ticker, trading_date, interval, provider)
```

For each refreshed row:

- insert if the key is new;
- update market-data fields if the same key is re-fetched;
- update fetch/ingestion metadata;
- count insert/update/unchanged rows;
- do not create duplicates;
- do not mutate prior signal/prediction records as a side effect.

Run the daily refresh for the configured universe. Weekends and exchange holidays should not be treated as missing sessions. A missing bar for a ticker that did not trade can be legitimate; do not forward-fill fake OHLCV bars. The pipeline should distinguish known holiday/weekend, no bar, possible suspension/illiquidity, provider omission, and unknown where evidence permits. Do not claim a suspension solely because Yahoo did not return a row.

If benchmark data or too many candidate tickers are missing/invalid, block signal generation or apply a documented and tested exclusion policy. Record the decision.

# 7. Canonical Daily-Bar Schema

Normalize all provider data to a stable internal schema before database writes:

```text
ticker
trading_date
interval
open_raw
high_raw
low_raw
close_raw
adj_close_provider
volume_raw
dividends
stock_splits
provider
provider_symbol
fetched_at
ingestion_run_id
```

Optional fields:

```text
currency,exchange,data_status,row_hash,created_at,updated_at
```

Rules:

- `trading_date` is a date in the exchange calendar, not an arbitrary host-local timestamp.
- Use `Asia/Jakarta` for exchange-local operations; the daily-bar domain field should be date-only.
- Use numeric storage with adequate precision. Do not use an imprecise binary float as the database's source of truth for financial values when decimal storage is appropriate.
- Null means missing, not zero price.
- Keep provider symbol (e.g. `BBCA.JK`) separate from canonical ticker (`BBCA`) if useful.
- Do not assume Yahoo volume is equivalent to official trading value.

# 8. Raw, Adjusted, and Corporate-Action Data

Do not mix raw and adjusted values without identifying each price view.

Persist raw provider observations, when returned:

```text
open_raw,high_raw,low_raw,close_raw,adj_close_provider,volume_raw,dividends,stock_splits
```

Build any adjusted research series as a separate, versioned transformation. The provider's adjusted close may incorporate distributions as well as splits. Such a series can be useful for total-return analysis, but it is not automatically the exact tradable price path for a TP/SL order.

For price-triggered TP/SL labels and execution simulation:

- handle stock splits so a split is not mistaken for a sudden loss/gain;
- represent dividend cash flows separately when computing total portfolio return;
- never mix raw `Close` with adjusted `High`/`Low` inside one label calculation;
- use one coherent price convention for entry, TP, SL, and the subsequent price path;
- document the adjustment logic and version it.

Add tests for an ordinary session, stock split, dividend ex-date, missing action record, and suspicious large price discontinuity. Do not automatically erase every extreme return; it could be a genuine move.

If split/dividend handling is not yet reliable, explicitly document the backtest limitation and do not claim realistic TP/SL performance. A future corporate-action-aware execution simulation is preferable to silently mixing adjusted and raw prices.

# 9. Data-Quality Validation

Run validations before committing or using the data.

## Structural checks

For a valid traded bar:

```text
open > 0
high > 0
low > 0
close > 0
high >= max(open, close)
low <= min(open, close)
high >= low
volume >= 0
```

Treat zero volume according to provider semantics and data-status policy; flag it for review rather than inventing a value.

## Uniqueness and coverage

```text
duplicate (ticker, trading_date, interval, provider) rows = 0
```

Record per ticker:

```text
requested_start,first_observed_date,last_observed_date,rows_received,
expected_recent_bar_date,latest_observed_date,missing_recent_bar,fetch_status
```

A ticker that listed later need not have ten years of history. Report its actual coverage rather than backfilling fake candles.

## Outliers

Flag for review:

- extreme daily returns;
- factor-of-10 or factor-of-100 price changes;
- unusual volume spikes;
- unexplained gaps;
- invalid OHLC relationships.

Check corporate actions and a second source where possible. Preserve flagged observations until validated; genuine market moves must not be silently deleted.

If critical checks fail, stop signal generation for affected data. Preserve the last known valid dataset and send an alert rather than using made-up prices.

# 10. Suggested Database Tables

Reuse the existing database/migrations where possible. Inspect the current schema before creating duplicates.

## `market_daily_bars`

```text
id,ticker,trading_date,interval,
open_raw,high_raw,low_raw,close_raw,adj_close_provider,volume_raw,
dividends,stock_splits,provider,provider_symbol,row_hash,
fetched_at,ingestion_run_id,created_at,updated_at
```

Unique key:

```text
(ticker, trading_date, interval, provider)
```

## `ingestion_runs`

```text
id,provider,job_type,started_at,finished_at,status,
tickers_requested,tickers_succeeded,tickers_partial,tickers_failed,
rows_inserted,rows_updated,rows_unchanged,rows_rejected,
error_summary,config_version
```

## `ingestion_ticker_status`

```text
id,ingestion_run_id,ticker,status,rows_received,rows_inserted,rows_updated,
first_date_received,last_date_received,error_code,error_message,attempt_count
```

## `universe_membership` (recommended)

```text
id,ticker,effective_from,effective_to,selected_as_of,
selection_source,selection_metric,selection_reason
```

## `corporate_actions` (if needed by existing schema)

```text
id,ticker,action_date,action_type,action_value,provider,fetched_at
```

Do not blindly create every suggested table. Add only missing capabilities through migrations.

# 11. Idempotency, Repair, and Versioning

All these actions must be safe to run more than once:

```text
initial backfill
incremental refresh
recent-window repair
validation
feature regeneration
```

A repeated backfill must not duplicate bars. An interrupted run must be resumable. A failed ticker must not make the overall run look successful. Use transactions at batch or reasonable unit-of-work granularity rather than one huge transaction for all symbols.

Add a repair command, adapting to the repo's conventions:

```bash
python -m scripts.ingest_daily --mode repair --lookback-days 30
```

Repair should re-fetch a recent period, detect changed values via field comparison/row hash, update bars, and report changed row counts. It must not rewrite historical production signals. Mark downstream research datasets/backtests as potentially stale when relevant and create a new dataset/experiment version for corrected research.

Track versions where available:

```text
provider/library version
universe version
ingestion run
price-adjustment version
feature version
label policy
signal configuration
model version
```

Each signal must keep its original feature snapshot and model version. If source data later changes, preserve the signal and record the correction separately.

# 12. Provider Abstraction

Keep provider-specific logic inside a single adapter. Conceptual interface:

```python
class MarketDataProvider:
    def get_daily_bars(self, tickers, start_date, end_date): ...
```

Implement `YFinanceProvider` and a `LocalCSVProvider` for deterministic tests. Adapt to existing project patterns rather than forcing this exact class signature.

The adapter must normalize all responses to the same canonical schema and explicit status/error format. Features, labels, model, signal engine, position tracker, and outcome engine must not call `yfinance` directly.

# 13. Integration with Current Phase 6

The main coding guide is already at Phase 6 (Signal Engine). First audit the existing implementation. Do not restart Phase 0–5 merely to match this document's naming.

Before changing code, report:

```text
1. Current market-data provider
2. Current universe source and size
3. Current history start date and interval
4. Raw/adjusted price semantics
5. Existing schema and unique key
6. Initial bulk-fetch capability
7. Daily incremental-upsert capability
8. Existing quality checks
9. Input expected by Phase 6
10. Concrete gaps and minimal safe fixes
```

The Signal Engine must consume validated data via a repository/service abstraction, not call `yfinance` directly. Before generating signals it must be able to determine:

```text
latest_completed_trading_date
data_quality_status
universe_version
feature_version
price_adjustment_version
```

If data quality is not sufficient, block signal generation according to configuration and log the reason.

# 14. Tests

Use provider fixtures/mocks; normal unit tests must not need live Yahoo requests.

Required unit tests:

- ticker normalization;
- single-ticker and multi-ticker response normalization;
- empty or failed provider response;
- duplicate handling;
- OHLC validation;
- date normalization and end-exclusive semantics;
- raw/adjusted field preservation;
- corporate-action parsing;
- row hash;
- upsert key and idempotency;
- retry/backoff;
- overlap-window calculation;
- latest-completed-bar detection.

Required integration tests:

- mock provider → normalization;
- normalization → validation;
- valid rows → database upsert;
- repeated fetch → no duplicates;
- changed recent bar → updated row and logged correction;
- provider failure → run marked partial/failed;
- missing required recent data → signal generation blocked;
- market-data upsert does not mutate historical signals.

# 15. Acceptance Criteria

Consider the pipeline ready for Phase 6 only when:

- [ ] seed universe is configurable and source-documented;
- [ ] actual verified ticker count is reported;
- [ ] initial historical backfill runs in batches;
- [ ] no fabricated tickers or bars are inserted;
- [ ] daily bars use a documented canonical schema;
- [ ] raw/adjusted/corporate-action semantics are explicit;
- [ ] unique key prevents duplicate rows;
- [ ] repeated backfills remain idempotent;
- [ ] daily incremental upsert works;
- [ ] recent overlap repair works;
- [ ] missing/incomplete critical data blocks signals by policy;
- [ ] ticker-level and run-level success/failure is reported;
- [ ] historical production signals remain immutable;
- [ ] tests, lint, and relevant type checks pass;
- [ ] README documents commands, configuration, data source, and limitations.

Do not claim acceptance criteria pass unless the agent actually executed the tests.

# 16. Required Agent Workflow

## Step A — Audit

Read the main guide and inspect source code, migrations, tests, config, and current Phase 6 behavior.

## Step B — Report gaps

Provide this table before large changes:

| Requirement | Existing implementation | Gap | Planned change |
|---|---|---|---|
| Seed universe | ... | ... | ... |
| Initial bulk fetch | ... | ... | ... |
| Daily upsert | ... | ... | ... |
| Data validation | ... | ... | ... |
| Corporate actions | ... | ... | ... |
| Phase 6 input contract | ... | ... | ... |

## Step C — Implement minimal safe changes

Preserve working modules/migrations. Avoid a broad refactor.

## Step D — Test

Run unit/integration tests plus the repository's lint/type checks.

## Step E — Report

```text
DATASET GUIDE IMPLEMENTATION REPORT
Audit:
Files changed:
Migrations:
Commands added:
Tests added:
Tests executed:
Results:
Known provider/data limitations:
Phase 6 integration result:
Manual action still required:
```

# 17. Suggested Roadmap

1. Audit current universe, provider, schema, and Phase 6 input contract.
2. Make the seed universe configurable and document its selection source.
3. Complete/repair the provider adapter and response normalization.
4. Implement historical bulk fetch with batches, retries, validation, and idempotent upsert.
5. Implement incremental refresh with recent overlap and daily coverage check.
6. Add ingestion reports and data-quality alerts.
7. Separate raw data from adjusted research data and document corporate-action limitations.
8. Integrate the validated data contract with Phase 6.
9. Schedule the daily process only after manual/local runs are reliable.

Do not move to later project phases just because the data pipeline was improved. Preserve the current roadmap unless the user changes scope.

# 18. Recommended Operating Pattern

Initial development:

```text
Seed universe (~200 liquid names)
        ↓
Bulk-fetch historical daily bars
        ↓
Validate and store
        ↓
Feature / signal development
```

Daily operation:

```text
After market close and provider publication
        ↓
Fetch latest bars + recent overlap
        ↓
Validate and upsert
        ↓
Verify required date/coverage
        ↓
Update features
        ↓
Phase 6 Signal Engine
```

Periodic maintenance:

```text
Review missing/corrected data
        ↓
Repair recent window
        ↓
Review ticker universe and provider coverage
        ↓
Create a new research dataset version when needed
```

# 19. Non-Negotiable Rules

1. Bulk-fetch historical data once; daily jobs must be incremental.
2. Upsert idempotently by ticker, trading date, interval, and provider.
3. Re-fetch a recent overlap window to repair missing or changed bars.
4. Never generate a signal from incomplete or critically invalid data.
5. Never invent prices, volumes, symbols, holidays, or missing bars.
6. Never mix raw and adjusted prices silently.
7. Handle splits/dividends explicitly or document the limitation.
8. Keep the current 200-stock development universe distinct from a point-in-time historical universe.
9. Never rewrite old production signals after data corrections.
10. Treat `yfinance` coverage, stability, and usage rights as limitations—not guarantees.
11. Audit the current repository because development is already at Phase 6.
12. Do not rebuild completed phases unless the audit identifies a concrete defect.

> **A model cannot be evaluated honestly unless we know which stocks were eligible, what data was available at signal time, how prices were adjusted, and whether the dataset changed later.**
