# Walkthrough — Phase 11E: Dynamic Conviction Sizing & Volatility Trailing Protection Research

## Overview

In Phase 11E, we investigated whether point-in-time regime conviction position sizing and volatility-based trailing protection can improve portfolio risk-adjusted performance without relying on fragile pooled profitability:
1. **Dynamic Position Sizing (Experiment A):** Conditioning trade allocation on point-in-time regime indicators (Fixed control, Conservative binary, Three-tier regime sizing, and Smooth conviction scaling).
2. **Volatility-Based Trailing Protection (Experiment B):** Evaluating ratcheting and volatility trailing stops (Breakeven ratchets at +2.5% and +3.0%, causal ATR $1.0\times$ and $1.5\times$ trailing stops, and Stepped profit locks).
3. **Combined Policy Matrix (Experiment C):** Testing whether sizing and trailing protection have complementary or overlapping effects when combined with Phase 11D selective policies.
4. **Walk-Forward Dispersion & Regime Allocation:** Measuring continuous compounding portfolio returns, continuous maximum drawdown, capital concentration, and fold-level stability across expanding test folds under the mandatory 50 bps round-trip friction model.

All experiments were executed strictly offline without retraining production champion models, modifying champion registry artifacts, or altering live BUY thresholds.

---

## Detailed Task Breakdown & Code Modifications

### 1. Research Engine: `python/experiments/sizing_trailing_eval.py`
- **Engine Architecture & Discrete-Event Simulation (`SizingTrailingEvaluationEngine`, lines 77–690):**
  - Integrated 50 bps round-trip friction model (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip).
  - Enforced 100-share IDX lot sizing, maximum 5 concurrent positions, and 20% equity cap per position.
  - Implemented dynamic sizing multiplier $w_t \in [0.0, 1.0]$: $\text{cap\_per\_pos} = \min(\text{equity} / 5, \text{equity} \times 0.20) \times w_t$.
  - Added tracking for `skipped_regime_sizing` when $w_t \le 0.0$ and explicit allocation metrics by regime (`FAVORABLE`, `MIXED`, `UNFAVORABLE`).
  - Implemented tightening-only trailing stops: evaluated on day $d$ using stop known at start of day; watermark and stop tighten at EOD based on observed High for subsequent day's Open/Low; stops strictly tighten and never loosen.
  - Handled opening gaps down below trailing stops: fill at Open (Variant B execution contract).
  - Conservative same-day exit resolution: SL takes precedence over TP on ambiguous wide-range bars.
- **Predeclared Sizing Rules (lines 740–795):**
  - `sizing_fixed_control`: $1.0\times$ allocation (20% cap) across all market conditions.
  - `sizing_conservative_binary`: $1.0\times$ when `ihsg_vs_ema20 > 0`, $0.0\times$ when `ihsg_vs_ema20 <= 0`.
  - `sizing_three_tier_regime`: $1.0\times$ Favorable (`ihsg_vs_ema20 > 0` & `breadth >= 0.50`), $0.5\times$ Mixed, $0.0\times$ Unfavorable (`ihsg_vs_ema20 <= 0` & `breadth < 0.50`).
  - `sizing_smooth_conviction`: $w_t = \text{clip}\left(\frac{\text{ihsg\_vs\_ema20} + 0.02}{0.04}, 0.0, 1.0\right)$.
- **Predeclared Trailing Stop Rules (lines 800–850):**
  - `make_breakeven_ratchet_rule(0.025, 0.0050)`: Moves stop to $+0.50\%$ (breakeven net of friction) after $+2.5\%$ watermark.
  - `make_breakeven_ratchet_rule(0.030, 0.0050)`: Moves stop to $+0.50\%$ after $+3.0\%$ watermark.
  - `make_atr_trailing_rule(1.0, 0.025)` & `make_atr_trailing_rule(1.5, 0.025)`: Causal ATR trailing stop with distance $k \times \text{ATR}$, activated after $+2.5\%$ move.
  - `make_stepped_profit_lock_rule`: $+2.5\%$ move locks $+0.50\%$; $+4.0\%$ move locks $+2.0\%$.
- **Continuous Compounding Equity & Aggregation (lines 855–1045):**
  - Compounded daily equity across chained test folds (Folds 1 $\rightarrow$ 2 $\rightarrow$ 3).
  - Computed continuous portfolio maximum drawdown, worst-fold maximum drawdown, trade expectancy, pooled profit factor, and turnover.

### 2. CLI Evaluation Runner: `scripts/run_sizing_trailing_evaluation.py`
- Built reproducible CLI runner generating aligned ASCII summary tables:
  - Table 1: Baseline Reference Baselines (Phase 11D Replication).
  - Table 2: Experiment A: Dynamic Position Sizing.
  - Table 3: Experiment B: Volatility Trailing Protection.
  - Table 4: Experiment C: Combined Policies.
  - Table 5: Regime Sizing & Capital Allocation Breakdown.
- Completed full multi-mode evaluation in 68.4 seconds.

### 3. Comprehensive Unit Tests: `tests/unit/test_sizing_trailing_evaluation.py`
- Implemented 13 targeted unit tests:
  - `test_engine_initialization`: Initialization, parameters, and friction contracts.
  - `test_sizing_rules_logic`: Mathematical verification of all 4 sizing rules across regime cases.
  - `test_sizing_zero_allocation_skips_orders`: Zero-multiplier orders skipped, recorded, no cash consumed.
  - `test_sizing_multiplier_scales_capital_allocation`: Capital scaling and lot rounding verification.
  - `test_trailing_stop_tightens_and_never_loosens`: Ratchet tightening behavior and pullback resistance.
  - `test_atr_trailing_and_stepped_lock_rules`: ATR distance scaling and stepped profit lock mechanics.
  - `test_trailing_stop_exit_execution`: Trailing stop trigger, exit reason `TRAILING_SL`, net profit protection.
  - `test_trailing_gap_down_execution`: Variant B gap-down fill at Open price rather than stop price.
  - `test_simultaneous_tp_and_trailing_sl_precedence`: Conservative precedence on ambiguous wide-range bars.
  - `test_continuous_equity_chaining_math`: Compounding scale and continuous drawdown math across folds.
  - `test_capital_competition_ranking`: Priority queue tie-breaking (score desc, ticker asc) with capacity caps.
  - `test_remaining_open_positions_tracking`: Tracking of positions remaining open at end of evaluation period.
  - `test_compute_fold_training_stats_causality`: Purge window and causal training stats computation.

### 4. Documentation & Governance
- `docs/16_phase_11e_sizing_trailing_protection_report.md`:
  - Formal audit report matching `docs/AGENT_REPORT_TEMPLATE.md`.
  - Executive decision: `DO_NOT_PROMOTE`.
  - Comprehensive empirical evidence tables across all experiments and folds (reconciled TP/SL rates in Section 5.3 and remaining open positions).
- `audit_report.md`:
  - Updated current operational state to Phase 11E with 503 passed tests.
  - Added entry 8 to index.
- `summary.md`:
  - Appended entry 60 preserving cumulative historical log integrity.

---

## Key Empirical Findings

1. **Replication of Frozen Baselines:**
   - Baseline numbers match Phase 11D exactly: `LOW_PRICE` H=15 regressor (856 trades, $-0.33\%$ net return, PF $0.80$, continuous DD $46.01\%$), `HIGHER_PRICE` H=15 full classifier (980 trades, $-0.49\%$ net return, PF $0.72$, continuous DD $62.67\%$).
2. **Experiment A (Dynamic Sizing):**
   - Three-Tier Regime Sizing cuts continuous portfolio drawdown from $46.01\% \rightarrow 14.74\%$ in `LOW_PRICE` and from $62.67\% \rightarrow 24.23\%$ in `HIGHER_PRICE`.
   - Sizing cuts portfolio turnover by more than half while maintaining $>61\%$ cash reserves.
   - However, sizing does not improve per-trade net expectancy ($-0.14\%$ in `LOW_PRICE`, $-0.26\%$ in `HIGHER_PRICE`). It is purely a capital preservation tool.
3. **Experiment B (Trailing Protection & The Payoff Truncation Paradox):**
   - Trailing stops increase win rate by $+5.4\%$ to $+10.9\%$ (surging up to $44.5\%$ in `HIGHER_PRICE`).
   - However, net trade expectancy and profit factor uniformly deteriorate: in `HIGHER_PRICE` selective, expectancy drops from $+0.13\% \rightarrow -0.06\%$ to $-0.14\%$, and profit factor falls from $1.07 \rightarrow 0.88$–$0.93$.
   - Normal daily volatility retracements trigger trailing stops prematurely, exchanging $+5.5\%$ target winners for marginal $+0.5\%$ or $+2.0\%$ exits while leaving full $-2.0\%$ initial stop losses intact.
4. **Experiment C (Combined Sizing & Selective Entry):**
   - Combining Three-Tier Sizing with Phase 11D Selective Entry (`comb_selective_sizing_alone`) achieves the lowest continuous portfolio drawdown in the history of the project:
     - `LOW_PRICE`: Continuous DD **$6.34\%$**, worst fold DD $5.86\%$, trade net return **$+0.08\%$**, PF $1.02$, turnover $27.9\text{x}$, cash exposure $81.3\%$.
     - `HIGHER_PRICE`: Continuous DD **$8.83\%$**, worst fold DD $8.83\%$, trade net return **$+0.14\%$**, PF $1.06$, turnover $47.0\text{x}$, cash exposure $70.0\%$.
   - Adding trailing stops degrades performance, confirming that Sizing and Trailing Protection do not have positive synergy.
5. **Cross-Fold Forward Inconsistency:**
   - In `comb_selective_sizing_alone`, positive returns are driven by single favorable folds (Fold 1 in `LOW_PRICE`, Fold 2 in `HIGHER_PRICE`). Forward test folds remain negative (Folds 2 & 3 in `LOW_PRICE`; Folds 1 & 3 in `HIGHER_PRICE`).
   - Governance Decision: `DO_NOT_PROMOTE`. Production champions remain unchanged.

---

## Testing Checklist

After checking out the working tree or reviewing Phase 11E artifacts, verify the following:

- [ ] **Unit Tests:** Run `pytest tests/unit/test_sizing_trailing_evaluation.py` and verify all 13 tests pass.
- [ ] **Full Regression Suite:** Run `pytest` and verify all 503 tests pass with 0 failures.
- [ ] **Code Linter:** Run `ruff check .` and confirm 0 errors.
- [ ] **CLI Execution:** Run `python scripts/run_sizing_trailing_evaluation.py` and verify execution completes in under 90 seconds.
- [ ] **Artifact Presence:** Verify that 10 files exist in `artifacts/phase_11e/`:
  - [ ] `artifacts/phase_11e/policy_metrics_LOW_PRICE.json`
  - [ ] `artifacts/phase_11e/policy_metrics_HIGHER_PRICE.json`
  - [ ] `artifacts/phase_11e/policy_summary_all.csv`
  - [ ] `artifacts/phase_11e/policy_summary_by_fold.csv`
  - [ ] `artifacts/phase_11e/baseline_reference_summary.csv`
  - [ ] `artifacts/phase_11e/experiment_a_sizing_summary.csv`
  - [ ] `artifacts/phase_11e/experiment_b_trailing_summary.csv`
  - [ ] `artifacts/phase_11e/experiment_c_combined_summary.csv`
  - [ ] `artifacts/phase_11e/regime_allocation_breakdown.csv`
  - [ ] `artifacts/phase_11e/phase_11e_selected_trades_sample.csv`
- [ ] **Champion Immutability:** Verify active production champions remain `lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`.
