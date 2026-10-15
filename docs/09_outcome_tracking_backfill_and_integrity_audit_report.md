# Phase 9 — Outcome Tracking Historical Backfill & Integrity Audit Report

**Date**: 2026-10-15  
**Scope**: Historical Outcome Tracking Pipeline Validation, Extended Metrics Persistence, and Breakout Signal Expiry Separation  
**Environment**: Python 3.12 (venv), SQLite Database (`datasets/stock_signals.db`)

---

## 1. Executive Summary & Safeguards Preservation

A comprehensive audit and backfill integrity verification was performed on the historical outcome tracking pipeline. All required operational safeguards remain intact:

- **Champion Safeguards**: Neither champion model was promoted, modified, or replaced.
  - `LOW_PRICE` Champion: `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` Champion: `lightgbm_classification_20261014_093607` (Active)
- **Execution & BUY Threshold Safeguards**: Production BUY thresholds remain unchanged; live order routing remains disabled.
- **EV Gate Fail-Closed Integrity**: The mathematical expected value gate and fail-closed mechanisms operate strictly as designed.
- **Historical Source Data**: No historical prices or bars were modified or altered.
- **Signal vs Position Expiry Decoupling**: Breakout signals expiring without reaching their entry trigger level are now explicitly classified as `UNFILLED_EXPIRED`. They have zero holding days, null realized return, null net return, and are excluded from completed trade metrics (win-rate, expectancy, profit factor).

---

## 2. Actual SQLite Schema Fields and Definitions

The outcome tracking pipeline stores evaluations in `outcomes_daily` with daily trajectory tracking in `signal_snapshots_daily`.

### Schema Definition (`outcomes_daily`)

```sql
CREATE TABLE IF NOT EXISTS outcomes_daily (
    outcome_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_status TEXT NOT NULL DEFAULT 'FILLED',
    outcome_status TEXT NOT NULL,
    realized_return REAL,
    holding_days INTEGER NOT NULL DEFAULT 0,
    mfe REAL NOT NULL DEFAULT 0.0,
    mae REAL NOT NULL DEFAULT 0.0,
    mfe_price REAL DEFAULT 0.0,
    mae_price REAL DEFAULT 0.0,
    time_to_peak INTEGER,
    time_to_tp INTEGER,
    time_to_sl INTEGER,
    net_return REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    resolved_at TEXT,
    notes TEXT,
    mode TEXT,
    UNIQUE (signal_id)
);
```

### Field Definitions

| Column Name | SQLite Type | Python Type | Description |
| :--- | :--- | :--- | :--- |
| `outcome_id` | `TEXT` | `str` (UUID4) | Unique identifier for the outcome record |
| `signal_id` | `TEXT` | `str` | Foreign key referencing the signal in `signals_daily` (UNIQUE) |
| `ticker` | `TEXT` | `str` | Normalized IDX ticker symbol without suffix (e.g., `BBCA`) |
| `signal_date` | `TEXT` | `datetime.date` | Trading date the signal was emitted (`YYYY-MM-DD`) |
| `entry_date` | `TEXT` | `datetime.date` | Date of actual execution fill, or planned date for unfilled signals |
| `entry_price` | `REAL` | `float` | Actual fill price (or breakout trigger level for unfilled signals) |
| `entry_status` | `TEXT` | `str` | Entry execution status: `FILLED` (for actual trades) or `UNFILLED` (for untriggered breakout signals) |
| `outcome_status` | `TEXT` | `str` | Classification: `OPEN`, `TP`, `SL`, `EXPIRY`, `AMBIGUOUS`, `UNFILLED_EXPIRED` |
| `realized_return` | `REAL` | `Optional[float]` | Gross realized return: `(exit_price - entry_price) / entry_price`. `NULL` for `UNFILLED_EXPIRED` |
| `holding_days` | `INTEGER` | `int` | Trading days position was open. Exactly `0` for `UNFILLED_EXPIRED` |
| `mfe` | `REAL` | `float` | Maximum Favorable Excursion percentage, clamped `[0.0, inf)` |
| `mae` | `REAL` | `float` | Maximum Adverse Excursion percentage, clamped `(-inf, 0.0]` |
| `mfe_price` | `REAL` | `float` | Maximum Favorable Excursion in price points: `max(0.0, max(High) - P_entry)` |
| `mae_price` | `REAL` | `float` | Maximum Adverse Excursion in price points: `min(0.0, min(Low) - P_entry)` |
| `time_to_peak` | `INTEGER` | `Optional[int]` | 1-based holding day index where the highest high occurred |
| `time_to_tp` | `INTEGER` | `Optional[int]` | Holding day index where Take Profit was hit (`NULL` if not `TP`) |
| `time_to_sl` | `INTEGER` | `Optional[int]` | Holding day index where Stop Loss was hit (`NULL` if not `SL`) |
| `net_return` | `REAL` | `Optional[float]` | Net return after standard IDX brokerage commissions (buy 0.15%, sell 0.25%) |
| `exit_date` | `TEXT` | `Optional[datetime.date]`| Date on which barrier was touched or horizon ended |
| `exit_price` | `REAL` | `Optional[float]` | Actual exit execution price (`NULL` for `UNFILLED_EXPIRED`) |
| `exit_reason` | `TEXT` | `Optional[str]` | Trigger reason (`TP`, `SL`, `EXPIRY`, `AMBIGUOUS`, `UNFILLED_EXPIRED`) |
| `resolved_at` | `TEXT` | `Optional[datetime]` | UTC timestamp of outcome resolution |
| `notes` | `TEXT` | `Optional[str]` | Detailed operational context or ambiguity collision metadata |
| `mode` | `TEXT` | `Optional[str]` | Decision price regime: `LOW_PRICE` (50–300) or `HIGHER_PRICE` (>300) |

---

## 3. Mathematical Formulas & Calculation Logic

1. **Maximum Favorable Excursion (MFE)**:
   $$\text{MFE}_{\%} = \max\left(0.0, \frac{\max_{k \in \{1,\dots,N\}} High_k - P_{\text{entry}}}{P_{\text{entry}}}\right)$$
   $$\text{MFE}_{\$} = \max\left(0.0, \max_{k \in \{1,\dots,N\}} High_k - P_{\text{entry}}\right)$$
   *Clamping Guarantee*: MFE is never negative. If high never exceeds entry price, MFE is 0.0.

2. **Maximum Adverse Excursion (MAE)**:
   $$\text{MAE}_{\%} = \min\left(0.0, \frac{\min_{k \in \{1,\dots,N\}} Low_k - P_{\text{entry}}}{P_{\text{entry}}}\right)$$
   $$\text{MAE}_{\$} = \min\left(0.0, \min_{k \in \{1,\dots,N\}} Low_k - P_{\text{entry}}\right)$$
   *Clamping Guarantee*: MAE is never positive. If low never drops below entry price, MAE is 0.0.

3. **Time-to-Peak**:
   $$t_{\text{peak}} = \min \{ k \in \{1,\dots,N\} \mid High_k = \max_{j} High_j \}$$

4. **Time-to-TP / Time-to-SL**:
   $$t_{\text{TP}} = k_{\text{exit}} \quad \text{if } \text{status} = \text{TP}, \quad \text{else NULL}$$
   $$t_{\text{SL}} = k_{\text{exit}} \quad \text{if } \text{status} = \text{SL}, \quad \text{else NULL}$$

5. **Net Realized Return**:
   Indonesian stock exchange (BEI / IDX) standard transaction fees:
   - Buy brokerage commission: $c_{\text{buy}} = 0.0015$ ($0.15\%$)
   - Sell brokerage commission: $c_{\text{sell}} = 0.0025$ ($0.25\%$)
   $$R_{\text{net}} = \frac{P_{\text{exit}} \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + c_{\text{buy}})} - 1.0$$
   For `UNFILLED_EXPIRED` and `OPEN`, $R_{\text{net}} = \text{NULL}$.

---

## 4. Outcome Coverage, Missing-Value, and Status Counts

### Overall Dataset Counts (`datasets/stock_signals.db`)

- **Total Signals Emitted**: 41 signals (across historical dates 2026-07-06, 2026-08-03, 2026-08-18, 2026-09-01, 2026-09-15, 2026-10-09, 2026-10-14)
- **Matured & Resolved Outcomes**: 31 records
- **Open / In-Flight Signals**: 10 signals (emitted on 2026-10-14, zero forward bars elapsed)

### Status Distribution

| Outcome Status | Count | Percentage | Realized Return Assigned? | Counted in Trade PnL? |
| :--- | :---: | :---: | :---: | :---: |
| `SL` (Stop Loss Hit) | 20 | 64.5% | Yes (negative/zero) | Yes |
| `TP` (Take Profit Hit) | 8 | 25.8% | Yes (positive) | Yes |
| `EXPIRY` (Holding Horizon End) | 2 | 6.5% | Yes (terminal close) | Yes |
| `UNFILLED_EXPIRED` (Untriggered Breakout) | 1 | 3.2% | **No (`NULL`)** | **No (Excluded)** |
| `AMBIGUOUS` (Same-Candle Collision) | 0 | 0.0% | N/A (absent in sample) | N/A |
| **Total Resolved** | **31** | **100.0%** | — | — |

### Trade Distinction Summary

- **Filled Trades**: 30 (TP: 8, SL: 20, EXPIRY: 2). All 30 trades entered the market, have valid holding days ($\ge 1$), and realized/net returns.
- **Unfilled Breakout Signals**: 1. Signal never triggered entry; preserved as signal-level statistic without polluting trade win rate or expectancy.
- **Missing Values**:
  - In filled trades (30): 0 missing values across all required metrics.
  - In unfilled signal (1): `realized_return`, `net_return`, `exit_price`, `time_to_peak`, `time_to_tp`, `time_to_sl` are strictly `NULL` by specification.

---

## 5. Idempotency & Mathematical Verification (31-Record Audit)

### Idempotency Check

The CLI command `python scripts/resolve_outcomes.py --save-db` was executed twice consecutively against the active SQLite database:
- **Run 1**: Processed un-evaluated signals and persisted 28 new matured outcomes into `outcomes_daily`.
- **Run 2**: Re-evaluated the database. Output: `[INFO] No outcomes resolved.` Exactly 0 records were modified or duplicated; the database table count remained identical at 31 records.

### Representative Sample Inspection (31 Matured Records)

Every record below was independently reconciled against raw price bars in `daily_bars`. All calculations agree with zero discrepancies:

| Ticker | Signal Dt | Entry Dt | Entry Px | Status | Exit Dt | Exit Px | Return | Net Ret | Hold | MFE | MAE | Peak | Mode |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GIAA` | 2026-07-06 | 2026-07-07 | 53.0 | `EXPIRY` | 2026-07-20 | 54.0 | +1.89% | +1.48% | 10d | +5.7% | -3.8% | 10 | LOW |
| `WIRG` | 2026-07-06 | 2026-07-07 | 53.0 | `SL` | 2026-07-13 | 50.0 | -5.66% | -6.04% | 5d | +3.8% | -5.7% | 1 | LOW |
| `BBCA` | 2026-08-03 | 2026-08-04 | 12,000.0 | `UNFILLED_EXPIRED` | 2026-08-18 | *None* | *None* | *None* | 0d | +0.0% | +0.0% | *None* | HIGHER |
| `BMTR` | 2026-08-03 | 2026-08-04 | 114.0 | `EXPIRY` | 2026-08-18 | 116.0 | +1.75% | +1.35% | 10d | +3.5% | -1.8% | 4 | LOW |
| `GIAA` | 2026-08-03 | 2026-08-04 | 54.0 | `TP` | 2026-08-10 | 58.0 | +7.41% | +6.98% | 5d | +33.3% | -1.9% | 5 | LOW |
| `LPKR` | 2026-08-03 | 2026-08-04 | 61.0 | `TP` | 2026-08-07 | 65.0 | +6.56% | +6.13% | 4d | +21.3% | -1.6% | 4 | LOW |
| `PNLF` | 2026-08-03 | 2026-08-04 | 224.0 | `TP` | 2026-08-13 | 236.4 | +5.53% | +5.11% | 8d | +6.2% | +0.0% | 8 | LOW |
| `WIRG` | 2026-08-03 | 2026-08-04 | 59.0 | `TP` | 2026-08-07 | 62.0 | +5.08% | +4.67% | 4d | +13.6% | -1.7% | 4 | LOW |
| `ADHI` | 2026-08-18 | 2026-08-19 | 140.0 | `SL` | 2026-08-19 | 137.5 | -1.80% | -2.19% | 1d | +1.4% | -2.9% | 1 | LOW |
| `BMTR` | 2026-08-18 | 2026-08-19 | 116.0 | `SL` | 2026-08-26 | 113.1 | -2.49% | -2.88% | 5d | +1.7% | -3.4% | 3 | LOW |
| `BYAN` | 2026-08-18 | 2026-08-19 | 14,700.0 | `SL` | 2026-08-19 | 14,700.0 | +0.00% | -0.40% | 1d | +26.9% | +0.0% | 1 | HIGHER |
| `GIAA` | 2026-08-18 | 2026-08-19 | 75.0 | `SL` | 2026-08-19 | 72.0 | -4.00% | -4.38% | 1d | +1.3% | -4.0% | 1 | LOW |
| `KRAS` | 2026-08-18 | 2026-08-19 | 226.0 | `SL` | 2026-08-19 | 220.4 | -2.49% | -2.88% | 1d | +0.9% | -2.7% | 1 | LOW |
| `WIRG` | 2026-08-18 | 2026-08-19 | 69.0 | `TP` | 2026-08-20 | 74.0 | +7.25% | +6.82% | 2d | +15.9% | -2.9% | 2 | LOW |
| `BKSL` | 2026-09-01 | 2026-09-02 | 77.0 | `SL` | 2026-09-09 | 73.0 | -5.19% | -5.57% | 6d | +0.0% | -5.2% | 1 | LOW |
| `BMTR` | 2026-09-01 | 2026-09-02 | 113.0 | `TP` | 2026-09-10 | 120.3 | +6.46% | +6.03% | 7d | +7.1% | -0.8% | 7 | LOW |
| `GIAA` | 2026-09-01 | 2026-09-02 | 66.0 | `TP` | 2026-09-03 | 71.0 | +7.58% | +7.15% | 2d | +7.6% | -1.5% | 2 | LOW |
| `LPKR` | 2026-09-01 | 2026-09-02 | 63.0 | `SL` | 2026-09-11 | 60.0 | -4.76% | -5.14% | 8d | +1.6% | -4.8% | 1 | LOW |
| `WIRG` | 2026-09-01 | 2026-09-02 | 75.0 | `SL` | 2026-09-09 | 72.0 | -4.00% | -4.38% | 6d | +5.3% | -5.3% | 3 | LOW |
| `BKSL` | 2026-09-15 | 2026-09-16 | 69.0 | `SL` | 2026-09-18 | 66.0 | -4.35% | -4.73% | 3d | +2.9% | -4.3% | 1 | LOW |
| `BMTR` | 2026-09-15 | 2026-09-16 | 117.0 | `SL` | 2026-09-16 | 114.1 | -2.49% | -2.88% | 1d | +0.9% | -2.6% | 1 | LOW |
| `DEWA` | 2026-09-15 | 2026-09-16 | 394.0 | `SL` | 2026-09-16 | 386.1 | -1.99% | -2.39% | 1d | +1.5% | -6.1% | 1 | HIGHER |
| `EMTK` | 2026-09-15 | 2026-09-16 | 492.0 | `SL` | 2026-09-18 | 479.8 | -2.49% | -2.88% | 3d | +0.8% | -4.9% | 1 | HIGHER |
| `LPKR` | 2026-09-15 | 2026-09-16 | 60.0 | `SL` | 2026-09-18 | 56.0 | -6.67% | -7.04% | 3d | +1.7% | -11.7% | 1 | LOW |
| `MAPA` | 2026-09-15 | 2026-09-16 | 645.0 | `TP` | 2026-09-18 | 680.6 | +5.52% | +5.10% | 3d | +7.0% | +0.0% | 3 | HIGHER |
| `NCKL` | 2026-09-15 | 2026-09-16 | 915.0 | `SL` | 2026-09-28 | 892.2 | -2.49% | -2.88% | 9d | +4.4% | -3.8% | 6 | HIGHER |
| `SCMA` | 2026-09-15 | 2026-09-16 | 195.0 | `SL` | 2026-09-18 | 190.2 | -2.49% | -2.88% | 3d | +1.5% | -5.6% | 1 | LOW |
| `SMGR` | 2026-09-15 | 2026-09-16 | 1,585.0 | `SL` | 2026-09-28 | 1,545.5 | -2.49% | -2.88% | 9d | +3.2% | -4.4% | 3 | HIGHER |
| `WIRG` | 2026-09-15 | 2026-09-16 | 79.0 | `SL` | 2026-09-16 | 76.0 | -3.80% | -4.18% | 1d | +5.1% | -3.8% | 1 | LOW |
| `ASII` | 2026-10-09 | 2026-10-12 | 4,850.0 | `SL` | 2026-10-12 | 4,850.0 | +0.00% | -0.40% | 1d | +1.4% | -0.8% | 1 | HIGHER |
| `BBCA` | 2026-10-09 | 2026-10-12 | 6,050.0 | `SL` | 2026-10-12 | 6,050.0 | +0.00% | -0.40% | 1d | +0.8% | -1.7% | 1 | HIGHER |

---

## 6. Known Assumptions & Unresolved Edge Cases

1. **Daily Candle Intraday Sequence Ambiguity**:
   Daily OHLC bars do not encode intraday event ordering. If both TP and SL are touched within the same candle, the configured policy handles resolution:
   - `conservative`: Defaults to Stop Loss (SL).
   - `optimistic`: Defaults to Take Profit (TP).
   - `ambiguous`: Explicitly records `outcome_status="AMBIGUOUS"` and exits at the bar close.
   In this historical audit dataset, 0 same-candle collisions occurred. The behavior is rigorously protected by unit tests.

2. **Corporate Action Split & Dividend Adjustments**:
   Execution entries and exits occur on actual exchange prices (`raw_close`, `open`). Signals enforce consistency against adjusted prices using `raw_adjusted_tolerance_pct` (5%) to prevent dividend distortion.

3. **Liquidity Suspensions & Trading Halts**:
   Days where volume is zero or trading was halted do not advance trading session holding counters if bars are missing. When bars are present with volume=0, prices are unchanged.

4. **Breakout Trigger Validity Horizon & Boundary Conditions**:
   A breakout signal remains valid for entry strictly within `signal.max_holding_days`.
   - If the price touches `entry_low` on or before the final candle of the horizon (`k <= max_holding_days`), the order is filled and begins its holding period from that entry date.
   - If the trigger level is never reached within `max_holding_days`, the signal immediately expires as `UNFILLED_EXPIRED` (`entry_status='UNFILLED'`). Future bars after the expiry window are ignored, preventing post-horizon entry resurrection.
   - The maximum high observed across the untriggered observation window is recorded in `notes`.

5. **Intraday Breakout Snapshot MAE Trajectory Alignment**:
   On intraday breakout entries (`open < trigger_level`), morning pre-breakout lows prior to the trigger level are excluded from `SignalDailySnapshot.mae_so_far` (using `min(entry_price, close)` when SL is not hit), maintaining exact mathematical equivalence between daily trajectory snapshots and terminal outcome records.

---

## 7. Verification Record & Test Suite Results

- **Linter (`ruff check .`)**: 100% clean, 0 errors, all lines under 100 characters.
- **Pytest Suite**: Complete test suite passed (413 passing tests, 100% success rate).
- **Audit Verification (`scripts/audit_historical_outcomes.py`)**: 31 records independently recomputed and verified against underlying price bars. 0 violations.
- **CLI Replay Idempotency**: `scripts/resolve_outcomes.py --save-db` executed repeatedly yields identical DB state without duplicates or modifications.

---

## 8. Files Changed & Schema Migrations

1. `python/common/types.py`:
   - Added `UNFILLED_EXPIRED` to valid statuses in `SignalOutcomeRecord`.
   - Added `entry_status` (`FILLED` vs `UNFILLED`) to `SignalOutcomeRecord` with validation.
   - Added extended metrics: `mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl`, `net_return`.
   - Updated `validate_outcome_lifecycle` to mandate `holding_days == 0`, `realized_return is None`, `net_return is None`, and `entry_status == "UNFILLED"` for `UNFILLED_EXPIRED`.
2. `python/outcomes/engine.py`:
   - Confined breakout trigger search to `deduped_bars[: signal.max_holding_days]` to prevent post-expiry fill resurrection.
   - Updated untriggered breakout expiry to emit `UNFILLED_EXPIRED` with `entry_status="UNFILLED"`, null returns, 0 holding days, and max observed high in notes.
   - Added non-negative MFE clamping and non-positive MAE clamping.
   - Synchronized snapshot daily `mae_so_far` with outcome MAE for intraday breakout entries.
   - Added computation for `mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl`, and `net_return`.
3. `python/outcomes/repository.py`:
   - Added automated idempotent schema migration adding `entry_status`, `mfe_price`, `mae_price`, `time_to_peak`, `time_to_tp`, `time_to_sl`, `net_return` to `outcomes_daily`.
   - Updated upsert and row extraction logic for extended metrics and `entry_status`.
4. `python/models/evaluation.py`:
   - Updated `compute_trading_metrics`, `evaluate_dataset`, and `evaluate_from_outcomes` to exclude `UNFILLED_EXPIRED` and `OPEN` outcomes from trade win-rate and expectancy calculations.
5. `python/outcomes/dataset.py`:
   - Added `exclude_unfilled` parameter to `build_matured_outcomes_dataset` and exported `entry_status` and extended metric columns.
6. `scripts/resolve_outcomes.py`:
   - Added project root `sys.path` configuration for direct CLI invocation.
   - Adjusted outcome table formatting and summary counts to display `UNFILLED_EXPIRED`.
   - Added `--exclude-unfilled` CLI argument.
7. `scripts/audit_historical_outcomes.py`:
   - Validated `entry_status` and independent OHLC bar re-computations for 31 historical records.
8. `tests/unit/test_outcomes.py` & `tests/unit/test_evaluation.py`:
   - Added tests for boundary breakout triggering, post-horizon breakout expiration, snapshot MAE consistency, `entry_status` validation, and exclusion of `UNFILLED_EXPIRED` from trading metrics.
