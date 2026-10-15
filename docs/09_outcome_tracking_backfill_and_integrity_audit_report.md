# Phase 9 — Outcome Tracking Historical Backfill & Integrity Audit Report

**Date**: 2026-10-15  
**Scope**: Outcome Metric Semantics Remediation, In-Trade vs Opportunity Metric Decoupling, Execution Cost & Slippage Reconciliation, and Historical Backfill Audit  
**Environment**: Python 3.12 (venv), SQLite Database (`datasets/stock_signals.db`)

---

## 1. Executive Summary & Safeguards Preservation

A comprehensive audit and backfill integrity verification was performed on the historical outcome tracking pipeline. Two distinct metric scopes were formally established to eliminate post-exit price leakage and cleanly distinguish actual trading results from theoretical opportunity analysis:

1. **Scope A — Actual Trade Performance (In-Trade Bounded)**:
   - Tracks actual filled trade execution from entry to exit.
   - For gap-through exits at the open, in-trade high/low is strictly bounded by the opening exit price (`open`), eliminating subsequent post-exit rally/drop leakage.
   - For intraday barrier touches, in-trade high on TP exit is bounded by `tp_price`; in-trade low on SL exit is bounded by `sl_price`.
   - Metrics include: `holding_days`, `entry_date`, `entry_price`, `exit_date`, `exit_price`, `mfe`, `mae`, `mfe_price`, `mae_price`, `time_to_peak`, `realized_return` (gross return), `return_after_fees` (IDX commissions: buy 0.15%, sell 0.25%), and `return_after_fees_and_slippage` / `net_return` (commissions plus 10 bps round-trip slippage).
   - For `UNFILLED_EXPIRED` signals (untriggered breakouts), all Scope A fields are strictly `NULL` and `holding_days = 0`.

2. **Scope B — Full-Horizon Opportunity Analysis (Counterfactual Observation)**:
   - Evaluates the counterfactual price trajectory over the full planned observation window (`signal.max_holding_days`).
   - Evaluated regardless of whether the trade exited early via TP/SL or never triggered entry.
   - Metrics include: `full_horizon_mfe`, `full_horizon_mae`, `full_horizon_mfe_price`, `full_horizon_mae_price`, `full_horizon_time_to_peak`, `horizon_end_date`, `horizon_end_price`, `horizon_end_return`, and `is_full_horizon_complete`.

### Operational Safeguards Preservation

- **Champion Safeguards**: Neither champion model was promoted, modified, or replaced.
  - `LOW_PRICE` Champion: `lightgbm_classification_20261014_093522` (Active)
  - `HIGHER_PRICE` Champion: `lightgbm_classification_20261014_093607` (Active)
- **Execution & BUY Threshold Safeguards**: Production BUY thresholds remain unchanged; live order routing remains disabled.
- **EV Gate Fail-Closed Integrity**: The mathematical expected value hurdle gate operates strictly as designed with unified 50 bps execution friction (`0.0015 buy fee + 0.0025 sell fee + 0.0010 slippage = 0.0050`).
- **Historical Source Data**: No raw price bars in `daily_bars` were modified or altered.

---

## 2. Actual SQLite Schema Fields and Definitions

The outcome tracking pipeline persists evaluated outcomes in `outcomes_daily` and daily progression in `signal_snapshots_daily`.

### Schema Definition (`outcomes_daily`)

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
    UNIQUE (signal_id)
);
```

### Field Definitions

| Column Name | SQLite Type | Python Type | Scope | Description |
| :--- | :--- | :--- | :---: | :--- |
| `outcome_id` | `TEXT` | `str` (UUID4) | Common | Unique identifier for outcome record |
| `signal_id` | `TEXT` | `str` | Common | Foreign key referencing `signals_daily` (UNIQUE) |
| `ticker` | `TEXT` | `str` | Common | Normalized IDX ticker symbol without suffix (`BBCA`) |
| `signal_date` | `TEXT` | `date` | Common | Trading date signal was generated (`YYYY-MM-DD`) |
| `entry_date` | `TEXT` | `Optional[date]` | Scope A | Date position entered; `NULL` for `UNFILLED_EXPIRED` |
| `entry_price` | `REAL` | `Optional[float]` | Scope A | Fill price; `NULL` for `UNFILLED_EXPIRED` |
| `entry_status` | `TEXT` | `str` | Common | Execution status: `FILLED` or `UNFILLED` |
| `outcome_status` | `TEXT` | `str` | Common | Status: `TP`, `SL`, `EXPIRY`, `AMBIGUOUS`, `UNFILLED_EXPIRED`, `OPEN` |
| `realized_return` | `REAL` | `Optional[float]` | Scope A | Gross realized return: `(exit_price - entry_price) / entry_price` |
| `gross_return` | `REAL` | `Optional[float]` | Scope A | Synonymous with `realized_return` |
| `holding_days` | `INTEGER` | `int` | Scope A | Trading days held; strictly `0` for `UNFILLED_EXPIRED` |
| `mfe` | `REAL` | `Optional[float]` | Scope A | In-trade MFE clamped `[0.0, inf)`; `NULL` for `UNFILLED_EXPIRED` |
| `mae` | `REAL` | `Optional[float]` | Scope A | In-trade MAE clamped `(-inf, 0.0]`; `NULL` for `UNFILLED_EXPIRED` |
| `mfe_price` | `REAL` | `Optional[float]` | Scope A | In-trade MFE in points: `max(0.0, max(High) - P_entry)` |
| `mae_price` | `REAL` | `Optional[float]` | Scope A | In-trade MAE in points: `min(0.0, min(Low) - P_entry)` |
| `time_to_peak` | `INTEGER` | `Optional[int]` | Scope A | Holding day index of in-trade peak high |
| `time_to_tp` | `INTEGER` | `Optional[int]` | Scope A | Holding day TP was touched (`NULL` if not `TP`) |
| `time_to_sl` | `INTEGER` | `Optional[int]` | Scope A | Holding day SL was touched (`NULL` if not `SL`) |
| `return_after_fees` | `REAL` | `Optional[float]` | Scope A | Realized return after brokerage fees (buy 0.15%, sell 0.25%) |
| `return_after_fees_and_slippage` | `REAL` | `Optional[float]` | Scope A | Realized return after fees + 10 bps slippage |
| `net_return` | `REAL` | `Optional[float]` | Scope A | Synonymous with `return_after_fees_and_slippage` |
| `exit_date` | `TEXT` | `Optional[date]` | Scope A | Exit execution date; `NULL` for `UNFILLED_EXPIRED` |
| `exit_price` | `REAL` | `Optional[float]` | Scope A | Exit execution fill price; `NULL` for `UNFILLED_EXPIRED` |
| `exit_reason` | `TEXT` | `Optional[str]` | Scope A | Exit reason (`TP`, `SL`, `EXPIRY`, `UNFILLED_EXPIRED`) |
| `trigger_price` | `REAL` | `Optional[float]` | Scope B | Planned breakout trigger price |
| `observation_end_date` | `TEXT` | `Optional[date]` | Scope B | Expiry date of observation window |
| `full_horizon_mfe` | `REAL` | `Optional[float]` | Scope B | Counterfactual MFE across full observation horizon |
| `full_horizon_mae` | `REAL` | `Optional[float]` | Scope B | Counterfactual MAE across full observation horizon |
| `full_horizon_mfe_price` | `REAL` | `Optional[float]` | Scope B | Counterfactual MFE points across full horizon |
| `full_horizon_mae_price` | `REAL` | `Optional[float]` | Scope B | Counterfactual MAE points across full horizon |
| `full_horizon_time_to_peak` | `INTEGER` | `Optional[int]` | Scope B | Horizon day index of highest high |
| `horizon_end_date` | `TEXT` | `Optional[date]` | Scope B | Date of final candle in observation horizon |
| `horizon_end_price` | `REAL` | `Optional[float]` | Scope B | Closing price of final candle in observation horizon |
| `horizon_end_return` | `REAL` | `Optional[float]` | Scope B | Return from reference/entry to horizon end |
| `is_full_horizon_complete` | `INTEGER` | `bool` | Scope B | `1` if all `max_holding_days` elapsed, `0` if ongoing |
| `resolved_at` | `TEXT` | `datetime` | Common | UTC timestamp of outcome evaluation |
| `notes` | `TEXT` | `Optional[str]` | Common | Operational metadata and collision details |
| `mode` | `TEXT` | `Optional[str]` | Common | Decision regime: `LOW_PRICE` or `HIGHER_PRICE` |

---

## 3. Mathematical Formulas & Calculation Logic

### Scope A: Actual Trade Excursions and Returns

1. **In-Trade Maximum Favorable Excursion (MFE)**:
   $$\text{MFE}_{\text{trade}} = \max\left(0.0, \frac{\max_{k \in \{1,\dots,N\}} \widetilde{High}_k - P_{\text{entry}}}{P_{\text{entry}}}\right)$$
   Where on the exit candle $k = N$:
   - If gap exit at open ($Open \le SL$ or $Open \ge TP$): $\widetilde{High}_N = Open_N$
   - If intraday TP exit: $\widetilde{High}_N = P_{\text{TP}}$
   - If intraday SL exit (single barrier touch): $\widetilde{High}_N = High_N$ (bounded by $< P_{\text{TP}}$)
   - If same-candle collision ($High \ge TP$ and $Low \le SL$):
     - `conservative`: $\widetilde{High}_N = Open_N$ (or $P_{\text{entry}}$ if breakout entry bar; $SL$ assumed first so rally to $TP$ is post-exit)
     - `optimistic`: $\widetilde{High}_N = P_{\text{TP}}$ ($TP$ assumed first)
     - `ambiguous`: $\widetilde{High}_N = \min(High_N, P_{\text{TP}})$ (simulated exit at $Close_N$)

2. **In-Trade Maximum Adverse Excursion (MAE)**:
   $$\text{MAE}_{\text{trade}} = \min\left(0.0, \frac{\min_{k \in \{1,\dots,N\}} \widetilde{Low}_k - P_{\text{entry}}}{P_{\text{entry}}}\right)$$
   Where on the exit candle $k = N$:
   - If gap exit at open: $\widetilde{Low}_N = Open_N$
   - If intraday SL exit: $\widetilde{Low}_N = P_{\text{SL}}$
   - If intraday TP exit (single barrier touch): $\widetilde{Low}_N = Low_N$ for normal entries, or $P_{\text{entry}}$ for breakout entry day (preventing post-exit afternoon close selloff leakage)
   - If same-candle collision ($High \ge TP$ and $Low \le SL$):
     - `conservative`: $\widetilde{Low}_N = P_{\text{SL}}$ ($SL$ assumed first)
     - `optimistic`: $\widetilde{Low}_N = Open_N$ (or $P_{\text{entry}}$ if breakout entry bar; $TP$ assumed first so drop to $SL$ is post-exit)
     - `ambiguous`: $\widetilde{Low}_N = \max(Low_N, P_{\text{SL}})$ (simulated exit at $Close_N$)

3. **Trade Returns & Execution Friction Reconciliation**:
   Indonesian stock exchange (BEI / IDX) standard fees:
   - Buy brokerage fee: $c_{\text{buy}} = 0.0015$ (15 bps)
   - Sell brokerage fee: $c_{\text{sell}} = 0.0025$ (25 bps)
   - Slippage per side: $s_{\text{half}} = 0.0005$ (5 bps each leg = 10 bps round-trip)

   $$\text{Gross Return} = \frac{P_{\text{exit}} - P_{\text{entry}}}{P_{\text{entry}}}$$
   $$\text{Return After Fees} = \frac{P_{\text{exit}} \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + c_{\text{buy}})} - 1.0$$
   $$\text{Net Return (Fees + Slippage)} = \frac{P_{\text{exit}} \cdot (1 - s_{\text{half}}) \cdot (1 - c_{\text{sell}})}{P_{\text{entry}} \cdot (1 + s_{\text{half}}) \cdot (1 + c_{\text{buy}})} - 1.0$$

   *EV Gate Reconciliation*: At break-even ($P_{\text{exit}} = P_{\text{entry}}$), $\text{Net Return} = -0.499\% \approx -50\text{ bps}$, exactly matching the EV Hurdle friction budget (`15 bps + 25 bps + 10 bps = 50 bps`).

### Scope B: Full-Horizon Opportunity Trajectory

Evaluated across $H = \min(\text{len}(bars), \text{max\_holding\_days})$ candles:
$$\text{MFE}_{\text{horizon}} = \max\left(0.0, \frac{\max_{j \in \{1,\dots,H\}} High_j - P_{\text{ref}}}{P_{\text{ref}}}\right)$$
$$\text{MAE}_{\text{horizon}} = \min\left(0.0, \frac{\min_{j \in \{1,\dots,H\}} Low_j - P_{\text{ref}}}{P_{\text{ref}}}\right)$$
$$\text{Horizon End Return} = \frac{Close_H - P_{\text{ref}}}{P_{\text{ref}}}$$
Where $P_{\text{ref}} = P_{\text{entry}}$ for filled trades, and $P_{\text{ref}} = P_{\text{trigger}}$ for unfilled breakouts.

---

## 4. Defect Reconciliation & Audit Verification

Prior to remediation, the pipeline suffered from post-exit price extreme leakage on the exit bar. Below are verified before-and-after audit calculations on historical trades:

### Defect 1: Gap-Through Exits at the Open
When a position stopped out immediately at the open of a candle, the old engine evaluated the entire daily bar's high and low as part of the trade.

- **`BYAN` (Signal Date: 2026-08-18)**:
  - *Context*: Entered 2026-08-19 at Open = 14,700.0 with SL = 16,844.85. Because $Open \le SL$, stopped out immediately at 14,700.0 at the market open. Later that day, BYAN rallied to a high of 18,650.0.
  - *Old In-Trade MFE*: **+26.87%** (erroneously credited the rally to a stopped-out position).
  - *Remediated In-Trade MFE*: **+0.00%** (strictly bounded by exit at open).
  - *Scope B Horizon MFE*: **+26.87%** (correctly captured under counterfactual opportunity).
- **`ASII` (Signal Date: 2026-10-09)**:
  - *Context*: Entered 2026-10-12 at Open = 4,850.0 with SL = 4,948.33. Stopped out at open (4,850.0); intraday high reached 4,920.0.
  - *Old In-Trade MFE*: **+1.44%** $\rightarrow$ *Remediated In-Trade MFE*: **+0.00%** $\rightarrow$ *Scope B Horizon MFE*: **+1.44%**.
- **`BBCA` (Signal Date: 2026-10-09)**:
  - *Context*: Entered 2026-10-12 at Open = 6,050.0 with SL = 6,172.93. Stopped out at open (6,050.0); intraday high reached 6,100.0.
  - *Old In-Trade MFE*: **+0.83%** $\rightarrow$ *Remediated In-Trade MFE*: **+0.00%** $\rightarrow$ *Scope B Horizon MFE*: **+0.83%**.

### Defect 2: Intraday Barrier Touch Leakage
When a position hit Take Profit or Stop Loss intraday, the candle continued trading and established extremes beyond the exit barrier that leaked into in-trade metrics.

- **`GIAA` (Signal Date: 2026-08-03)**:
  - *Context*: Entered 2026-08-04 at 54.0, TP = 58.0. On Day 5 (2026-08-10), price touched TP at 58.0 (+7.41%). The day's high continued surging to 72.0 (+33.33%).
  - *Old In-Trade MFE*: **+33.33%** (distorted trade performance beyond the sold barrier).
  - *Remediated In-Trade MFE*: **+7.41%** (strictly bounded by TP exit).
  - *Scope B Horizon MFE*: **+55.56%** (captured subsequent rally to 84.0 on day 6).
- **`LPKR` (Signal Date: 2026-08-03)**:
  - *Context*: Entered 2026-08-04 at 61.0, TP = 65.0. On Day 4 (2026-08-07), price touched TP at 65.0 (+6.56%); candle high reached 74.0 (+21.31%).
  - *Old In-Trade MFE*: **+21.31%** $\rightarrow$ *Remediated In-Trade MFE*: **+6.56%** $\rightarrow$ *Scope B Horizon MFE*: **+21.31%**.
- **`LPKR` (Signal Date: 2026-09-15)**:
  - *Context*: Entered 2026-09-16 at 60.0, SL = 56.0. On Day 3 (2026-09-18), price touched SL at 56.0 (-6.67%); candle low plunged to 53.0 (-11.67%).
  - *Old In-Trade MAE*: **-11.67%** (erroneously recorded losses after the position was closed).
  - *Remediated In-Trade MAE*: **-6.67%** (strictly bounded by SL exit).
  - *Scope B Horizon MAE*: **-35.00%** (captured post-exit collapse across full horizon).

### Defect 3: Unfilled Breakout Signal Semantics
- **`BBCA` (Signal Date: 2026-08-03)**:
  - *Context*: Breakout BUY signal with trigger `entry_low = 12,000.0`. Over the 10-day holding horizon, BBCA traded between 6,000 and 6,250 and never triggered entry.
  - *Old Representation*: Stored as `UNFILLED_EXPIRED` but with planned trigger stored in `entry_price` (12,000.0) and entry date (2026-08-04), causing ambiguity as to whether an order was executed.
  - *Remediated Representation*: Trade fields are strictly `NULL`: `entry_date=None`, `entry_price=None`, `exit_date=None`, `exit_price=None`, `mfe=None`, `mae=None`, `realized_return=None`, `net_return=None`, `holding_days=0`. Trigger level is cleanly preserved in `trigger_price=12,000.0` and observation end in `observation_end_date=2026-08-18`. Scope B opportunity metrics are computed relative to trigger price: `full_horizon_mfe=0.0%`, `full_horizon_mae=-48.3%` (low 6,200 vs 12,000).

---

## 5. Complete Representative Sample Inspection (31 Matured Records)

Every record below has been recomputed and verified against underlying price bars in `daily_bars` via `scripts/audit_historical_outcomes.py`:

| Ticker | Signal Dt | Entry Dt | Entry Px | Status | Exit Dt | Exit Px | Return | Fee Ret | Net Ret | Hold | MFE | MAE | Horiz MFE | Horiz MAE | Mode |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GIAA` | 2026-07-06 | 2026-07-07 | 53.0 | `EXPIRY` | 2026-07-20 | 54.0 | +1.89% | +1.48% | +1.38% | 10d | +5.7% | -3.8% | +5.7% | -3.8% | LOW |
| `WIRG` | 2026-07-06 | 2026-07-07 | 53.0 | `SL` | 2026-07-13 | 50.0 | -5.66% | -6.04% | -6.13% | 5d | +3.8% | -5.7% | +3.8% | -5.7% | LOW |
| `BBCA` | 2026-08-03 | *None* | *None* | `UNFILLED_EXPIRED` | *None* | *None* | *None* | *None* | *None* | 0d | *None* | *None* | +0.0% | -48.3% | HIGHER |
| `BMTR` | 2026-08-03 | 2026-08-04 | 114.0 | `EXPIRY` | 2026-08-18 | 116.0 | +1.75% | +1.35% | +1.25% | 10d | +3.5% | -1.8% | +3.5% | -1.8% | LOW |
| `GIAA` | 2026-08-03 | 2026-08-04 | 54.0 | `TP` | 2026-08-10 | 58.0 | +7.41% | +6.98% | +6.87% | 5d | +7.4% | -1.9% | +55.6% | -1.9% | LOW |
| `LPKR` | 2026-08-03 | 2026-08-04 | 61.0 | `TP` | 2026-08-07 | 65.0 | +6.56% | +6.13% | +6.03% | 4d | +6.6% | -1.6% | +21.3% | -1.6% | LOW |
| `PNLF` | 2026-08-03 | 2026-08-04 | 224.0 | `TP` | 2026-08-13 | 236.4 | +5.53% | +5.11% | +5.00% | 8d | +5.5% | +0.0% | +8.9% | +0.0% | LOW |
| `WIRG` | 2026-08-03 | 2026-08-04 | 59.0 | `TP` | 2026-08-07 | 62.0 | +5.08% | +4.67% | +4.56% | 4d | +5.1% | -1.7% | +20.3% | -1.7% | LOW |
| `ADHI` | 2026-08-18 | 2026-08-19 | 140.0 | `SL` | 2026-08-19 | 137.5 | -1.80% | -2.19% | -2.29% | 1d | +1.4% | -1.8% | +1.4% | -5.7% | LOW |
| `BMTR` | 2026-08-18 | 2026-08-19 | 116.0 | `SL` | 2026-08-26 | 113.1 | -2.49% | -2.88% | -2.98% | 5d | +1.7% | -2.5% | +1.7% | -4.3% | LOW |
| `BYAN` | 2026-08-18 | 2026-08-19 | 14,700.0 | `SL` | 2026-08-19 | 14,700.0 | +0.00% | -0.40% | -0.50% | 1d | +0.0% | +0.0% | +26.9% | -8.7% | HIGHER |
| `GIAA` | 2026-08-18 | 2026-08-19 | 75.0 | `SL` | 2026-08-19 | 72.0 | -4.00% | -4.38% | -4.48% | 1d | +1.3% | -4.0% | +1.3% | -18.7% | LOW |
| `KRAS` | 2026-08-18 | 2026-08-19 | 226.0 | `SL` | 2026-08-19 | 220.4 | -2.49% | -2.88% | -2.98% | 1d | +0.9% | -2.5% | +9.7% | -3.5% | LOW |
| `WIRG` | 2026-08-18 | 2026-08-19 | 69.0 | `TP` | 2026-08-20 | 74.0 | +7.25% | +6.82% | +6.71% | 2d | +7.2% | -2.9% | +17.4% | -2.9% | LOW |
| `BKSL` | 2026-09-01 | 2026-09-02 | 77.0 | `SL` | 2026-09-09 | 73.0 | -5.19% | -5.57% | -5.67% | 6d | +0.0% | -5.2% | +0.0% | -14.3% | LOW |
| `BMTR` | 2026-09-01 | 2026-09-02 | 113.0 | `TP` | 2026-09-10 | 120.3 | +6.46% | +6.03% | +5.93% | 7d | +6.5% | -0.9% | +7.1% | -0.9% | LOW |
| `GIAA` | 2026-09-01 | 2026-09-02 | 66.0 | `TP` | 2026-09-03 | 71.0 | +7.58% | +7.15% | +7.04% | 2d | +7.6% | -1.5% | +7.6% | -6.1% | LOW |
| `LPKR` | 2026-09-01 | 2026-09-02 | 63.0 | `SL` | 2026-09-11 | 60.0 | -4.76% | -5.14% | -5.24% | 8d | +1.6% | -4.8% | +1.6% | -6.3% | LOW |
| `WIRG` | 2026-09-01 | 2026-09-02 | 75.0 | `SL` | 2026-09-09 | 72.0 | -4.00% | -4.38% | -4.48% | 6d | +5.3% | -4.0% | +14.7% | -5.3% | LOW |
| `BKSL` | 2026-09-15 | 2026-09-16 | 69.0 | `SL` | 2026-09-18 | 66.0 | -4.35% | -4.73% | -4.83% | 3d | +2.9% | -4.3% | +2.9% | -26.1% | LOW |
| `BMTR` | 2026-09-15 | 2026-09-16 | 117.0 | `SL` | 2026-09-16 | 114.1 | -2.49% | -2.88% | -2.97% | 1d | +0.9% | -2.5% | +0.9% | -41.0% | LOW |
| `DEWA` | 2026-09-15 | 2026-09-16 | 394.0 | `SL` | 2026-09-16 | 386.1 | -1.99% | -2.39% | -2.48% | 1d | +1.5% | -2.0% | +1.5% | -16.2% | HIGHER |
| `EMTK` | 2026-09-15 | 2026-09-16 | 492.0 | `SL` | 2026-09-18 | 479.8 | -2.49% | -2.88% | -2.98% | 3d | +0.8% | -2.5% | +0.8% | -19.5% | HIGHER |
| `LPKR` | 2026-09-15 | 2026-09-16 | 60.0 | `SL` | 2026-09-18 | 56.0 | -6.67% | -7.04% | -7.13% | 3d | +1.7% | -6.7% | +1.7% | -35.0% | LOW |
| `MAPA` | 2026-09-15 | 2026-09-16 | 645.0 | `TP` | 2026-09-18 | 680.6 | +5.52% | +5.10% | +5.00% | 3d | +5.5% | +0.0% | +8.5% | -2.3% | HIGHER |
| `NCKL` | 2026-09-15 | 2026-09-16 | 915.0 | `SL` | 2026-09-28 | 892.2 | -2.49% | -2.88% | -2.98% | 9d | +4.4% | -2.5% | +4.4% | -6.0% | HIGHER |
| `SCMA` | 2026-09-15 | 2026-09-16 | 195.0 | `SL` | 2026-09-18 | 190.2 | -2.49% | -2.88% | -2.97% | 3d | +1.5% | -2.5% | +1.5% | -17.4% | LOW |
| `SMGR` | 2026-09-15 | 2026-09-16 | 1,585.0 | `SL` | 2026-09-28 | 1,545.5 | -2.49% | -2.88% | -2.98% | 9d | +3.2% | -2.5% | +3.2% | -6.9% | HIGHER |
| `WIRG` | 2026-09-15 | 2026-09-16 | 79.0 | `SL` | 2026-09-16 | 76.0 | -3.80% | -4.18% | -4.28% | 1d | +5.1% | -3.8% | +5.1% | -32.9% | LOW |
| `ASII` | 2026-10-09 | 2026-10-12 | 4,850.0 | `SL` | 2026-10-12 | 4,850.0 | +0.00% | -0.40% | -0.50% | 1d | +0.0% | +0.0% | +1.4% | -3.5% | HIGHER |
| `BBCA` | 2026-10-09 | 2026-10-12 | 6,050.0 | `SL` | 2026-10-12 | 6,050.0 | +0.00% | -0.40% | -0.50% | 1d | +0.0% | +0.0% | +0.8% | -3.3% | HIGHER |

---

## 6. Known Assumptions & Unresolved Edge Cases

1. **Daily Candle Intraday Sequence Ambiguity**:
   Daily OHLC bars do not encode intraday tick ordering. If both TP and SL are touched within the same candle, the configured policy handles resolution:
   - `conservative`: Defaults to Stop Loss (SL).
   - `optimistic`: Defaults to Take Profit (TP).
   - `ambiguous`: Explicitly records `outcome_status="AMBIGUOUS"` and exits at the bar close.
   In this historical audit dataset, 0 same-candle collisions occurred. The behavior is protected by comprehensive unit tests.

2. **Corporate Action Split & Dividend Adjustments**:
   Execution entries and exits occur on actual exchange prices (`raw_close`, `open`). Signals enforce consistency against adjusted prices using `raw_adjusted_tolerance_pct` (5%) to prevent dividend distortion.

3. **Liquidity Suspensions & Trading Halts**:
   Days where volume is zero or trading was halted do not advance trading session holding counters if bars are missing. When bars are present with volume=0, prices are unchanged.

4. **Breakout Trigger Validity Horizon & Boundary Conditions**:
   A breakout signal remains valid for entry strictly within `signal.max_holding_days`.
   - If the price touches `entry_low` on or before the final candle of the horizon (`k <= max_holding_days`), the order is filled and begins its holding period from that entry date.
   - If the trigger level is never reached within `max_holding_days`, the signal immediately expires as `UNFILLED_EXPIRED` (`entry_status='UNFILLED'`). Future bars after the expiry window are ignored, preventing post-horizon entry resurrection.
   - The planned trigger is recorded in `trigger_price`, expiry in `observation_end_date`, and counterfactual opportunity metrics are tracked across the window.

---

## 7. Verification Record & Test Suite Results

- **Linter (`ruff check .`)**: 100% clean, 0 errors, all lines under 100 characters.
- **Pytest Suite**: Complete test suite passed (420 passing tests, 100% success rate).
- **Audit Verification (`scripts/audit_historical_outcomes.py`)**: 31 records independently recomputed and verified against underlying price bars. 0 violations.
- **Replay Idempotency**: `scripts/resolve_outcomes.py --save-db` executed repeatedly yields identical DB state without duplicates or unexpected mutations.

---

## 8. Summary of Files Changed & Schema Migrations

1. `python/common/types.py`:
   - Added fields: `gross_return`, `return_after_fees`, `return_after_fees_and_slippage`, `trigger_price`, `observation_end_date`, `full_horizon_mfe`, `full_horizon_mae`, `full_horizon_mfe_price`, `full_horizon_mae_price`, `full_horizon_time_to_peak`, `horizon_end_date`, `horizon_end_price`, `horizon_end_return`, `is_full_horizon_complete`.
   - Made `entry_date`, `entry_price`, `mfe`, `mae` Optional (strictly nullable for `UNFILLED_EXPIRED`).
   - Updated lifecycle validators to enforce `NULL` trade performance metrics for `UNFILLED_EXPIRED` while allowing populated trigger and opportunity metrics.
2. `python/outcomes/repository.py`:
   - Implemented automated SQLite table migration recreating table if legacy columns had `NOT NULL` on `entry_date`, `entry_price`, `mfe`, or `mae`, and added all 14 new columns.
   - Updated `_outcome_to_db_params` and `_row_to_outcome` for full 38-column SQLite mapping.
3. `python/outcomes/engine.py`:
   - Decoupled Scope A (in-trade bounded) from Scope B (full horizon opportunity).
   - Bounded gap exits at open to `bar.open` and intraday TP/SL to barriers, eliminating post-exit price extreme leakage.
   - Handled unfilled breakout signals by nulling trade fields and storing trigger + opportunity fields.
   - Reconciled execution fees (0.15% buy, 0.25% sell) and 10 bps round-trip slippage (5 bps per side), unifying friction with EV Gate (50 bps).
   - Added `force_recompute` option to `resolve_all_signals`.
4. `python/outcomes/dataset.py`:
   - Guarded date formatting on `entry_date` and exported all new opportunity and cost fields.
5. `scripts/resolve_outcomes.py`:
   - Added `--force-recompute` option and guarded string formatting for nullable trade metrics.
6. `scripts/audit_historical_outcomes.py`:
   - Comprehensive audit script validating bounded in-trade excursions, gap open exits, NULL unfilled trade metrics, and fee/slippage alignment across all 31 historical records.
7. `tests/unit/test_outcomes.py` & `tests/integration/test_outcome_pipeline.py`:
   - Updated existing tests to reflect bounded in-trade excursions.
   - Added comprehensive regression tests for gap exits, collision policies, fee/slippage alignment, and unfilled breakout repository persistence.
