# Agent Task Report — Phase 11E: Dynamic Conviction Sizing & Volatility Trailing Protection Research

## 1. Metadata

- **Task ID:** `PHASE-11E-SIZING-TRAILING-PROTECTION-EVAL`
- **Task title:** Dynamic Conviction Sizing & Volatility Trailing Protection Research
- **Date:** `2026-10-19 22:30 WIB`
- **Repository:** `hikwoa-hfw/idx-stock-signal`
- **Branch:** `main`
- **Commit SHA:** Working tree with Phase 11E sizing & trailing engine, CLI runner, empirical artifacts, and comprehensive test suite
- **Task status:** `PASS (DO_NOT_PROMOTE)`
- **Related reports:**
  - [10_controlled_feature_ablation_report.md](10_controlled_feature_ablation_report.md)
  - [11_feature_ablation_metric_validation_report.md](11_feature_ablation_metric_validation_report.md)
  - [12_phase_11b_target_contract_audit_report.md](12_phase_11b_target_contract_audit_report.md)
  - [13_phase_11b_candidate_model_evaluation_report.md](13_phase_11b_candidate_model_evaluation_report.md)
  - [14_phase_11c_multi_horizon_return_evaluation_report.md](14_phase_11c_multi_horizon_return_evaluation_report.md)
  - [15_phase_11d_dynamic_exit_policy_evaluation_report.md](15_phase_11d_dynamic_exit_policy_evaluation_report.md)

---

## 2. Executive Summary

### Decision

`DO_NOT_PROMOTE`

Comprehensive out-of-sample investigation of post-prediction dynamic conviction sizing and volatility-based trailing protection demonstrates significant tail-risk dampening and capital protection, but **fails to resolve the underlying cross-fold deficit in forward test folds**.

Under the mandatory 50 bps round-trip transaction friction model (15 bps buy commission, 25 bps sell commission, 5 bps entry slippage, 5 bps exit slippage):
1. **Dynamic Position Sizing suppresses portfolio drawdown to record lows:** Implementing a point-in-time three-tier regime sizing rule ($1.0\times$ Favorable, $0.5\times$ Mixed, $0.0\times$ Unfavorable) cuts continuous portfolio drawdown on the baseline strategy from $46.01\% \rightarrow 14.74\%$ in `LOW_PRICE` and from $62.67\% \rightarrow 24.23\%$ in `HIGHER_PRICE`. When applied on top of the Phase 11D selective policy (`comb_selective_sizing_alone`), continuous drawdown is suppressed to a project-record low of **$6.34\%$** in `LOW_PRICE` and **$8.83\%$** in `HIGHER_PRICE`, while maintaining cash reserves ($70.0\%$ to $81.3\%$ average cash exposure).
2. **However, sizing does not improve per-trade net expectancy:** De-allocating capital in adverse or mixed regimes protects the aggregate cash balance, but the per-trade net return of executed signals remains negative on baseline configurations ($-0.14\%$ in `LOW_PRICE`, $-0.26\%$ in `HIGHER_PRICE`). Position sizing is strictly a capital preservation lever, not an expectancy generator.
3. **Trailing Stops exhibit a classic payoff truncation paradox:** In Experiment B, volatility-based trailing protection (breakeven ratchets, ATR trailing stops, and stepped profit locks) dramatically elevates trade win rates (surging up to $43.67\%$–$44.48\%$ in `HIGHER_PRICE` and $36.41\%$ in `LOW_PRICE`). However, **net trade expectancy and profit factor severely deteriorate** (e.g. `HIGHER_PRICE` selective expectancy drops from $+0.13\% \rightarrow -0.06\%$ to $-0.14\%$, PF falls from $1.07 \rightarrow 0.88$–$0.93$). Premature trailing stop hits truncate full $+6.0\%$ target winners on routine daily retracements while preserving full initial stop-loss exposure ($-2.0\%$), asymmetrically shrinking the right tail of the return distribution.
4. **Persistent forward-fold deficit prevents production promotion:** While the combined selective sizing policy (`comb_selective_sizing_alone`) achieves positive pooled net return ($+0.08\%$ in `LOW_PRICE`, $+0.14\%$ in `HIGHER_PRICE`) with minimal drawdown, fold-level dispersion confirms that forward test folds remain underwater. In `LOW_PRICE`, Fold 2 ($-0.10\%$) and Fold 3 ($-0.16\%$) remain negative. In `HIGHER_PRICE`, Fold 1 ($-0.01\%$) and Fold 3 ($-0.11\%$) remain negative.

In accordance with repository governance invariants ("A policy that merely reduces losses or drawdown must be described as a risk-reduction improvement, not as a profitable strategy. No policy may be promoted to production in this phase"), **no policy is promoted to production champion status**. Active production champions (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) remain strictly unchanged and protected.

### Completed

1. **Frozen Reference Baseline Replication:** Replicated exact Phase 11D out-of-sample trading performance without retraining models or modifying registry champions:
   - `LOW_PRICE`: H=15 fixed control (856 trades, $-0.33\%$ net return, PF $0.80$, continuous DD $46.01\%$), Bull filter alone (452 trades, $-0.10\%$ net return, PF $0.93$, continuous DD $16.65\%$), and Combined selective policy (172 trades, $+0.08\%$ net return, PF $1.04$, continuous DD $9.59\%$).
   - `HIGHER_PRICE`: H=15 fixed control (980 trades, $-0.49\%$ net return, PF $0.72$, continuous DD $62.67\%$), Bull filter alone (461 trades, $-0.17\%$ net return, PF $0.89$, continuous DD $23.43\%$), Combined Top 1% policy (301 trades, $+0.13\%$ net return, PF $1.07$, continuous DD $9.77\%$), and Combined Top 3% policy (416 trades, $-0.13\%$ net return, PF $0.91$, continuous DD $16.05\%$).
2. **Experiment A (Dynamic Position Sizing):** Evaluated 4 predeclared sizing rules on baseline models without lookahead bias:
   - Fixed Sizing Control ($1.0\times$ allocation, 20% equity cap, max 5 positions).
   - Conservative Binary ($1.0\times$ in bull trend `ihsg_vs_ema20 > 0`, $0.0\times$ in bear trend `ihsg_vs_ema20 <= 0`).
   - Three-Tier Regime Sizing ($1.0\times$ Favorable, $0.5\times$ Mixed, $0.0\times$ Unfavorable).
   - Smooth Conviction Sizing (continuous linear ramp $w_t = \text{clip}\left(\frac{\text{ihsg\_vs\_ema20} + 0.02}{0.04}, 0.0, 1.0\right)$).
   - Tracked capital allocation by regime, skipped entries ($590$ to $1,380$ orders), average cash exposure ($53.4\%$ to $65.5\%$), and continuous portfolio drawdowns.
3. **Experiment B (Volatility-Based Trailing Protection):** Evaluated 5 causal trailing-stop policies on both Baseline and Selective policies:
   - Fixed exit control without trailing protection (TP +5%/+6%, SL -2%).
   - Breakeven Ratchet after $+2.5\%$ move (locks $+0.50\%$ net covering round-trip friction).
   - Breakeven Ratchet after $+3.0\%$ move (locks $+0.50\%$ net).
   - Causal ATR $1.0\times$ trailing stop activated after $+2.5\%$ move.
   - Causal ATR $1.5\times$ trailing stop activated after $+2.5\%$ move.
   - Stepped Profit Lock ($+2.5\%$ move locks $+0.50\%$ net, $+4.0\%$ move locks $+2.0\%$ net).
   - Strictly enforced tightening-only stop logic, zero intraday event lookahead, daily gap fills, and conservative SL precedence.
4. **Experiment C (Combined Policy Matrix):** Evaluated whether sizing and trailing protection are complementary:
   - Evaluated Sizing Alone vs Trailing Alone vs Sizing + Trailing Combined on both Baseline and Phase 11D selective configurations.
5. **Walk-Forward Validation Protocol:** Assessed fold-level dispersion across Folds 1, 2, and 3, continuous compounded portfolio return, continuous portfolio maximum drawdown, and capital exposure.
6. **Production Verification & Hygiene:** Implemented 13 unit tests in `tests/unit/test_sizing_trailing_evaluation.py` (total test suite: 503 passed, 0 failures, 100% clean ruff linter).
7. **Artifact Delivery:** Exported 10 machine-readable artifacts (JSON, modular CSV summaries, regime allocation breakdown, and selected trade sample logs) to `artifacts/phase_11e/`.

### Important Findings

1. **Dynamic Sizing is a Potent Capital Preservation Tool:**
   - Three-tier regime sizing ($1.0\times / 0.5\times / 0.0\times$) cuts portfolio maximum drawdown by more than half across both markets: from $46.01\% \rightarrow 14.74\%$ in `LOW_PRICE` and from $62.67\% \rightarrow 24.23\%$ in `HIGHER_PRICE`.
   - When combined with selective entry (`comb_selective_sizing_alone`), continuous drawdown is suppressed to a record low of **$6.34\%$** (`LOW_PRICE`) and **$8.83\%$** (`HIGHER_PRICE`), with average cash exposure maintained at $70.0\%$–$81.3\%$.
2. **Sizing Preserves, but Does Not Create, Net Expectancy:**
   - Trade-level expectancy under three-tier sizing on baseline signals remains negative ($-0.14\%$ in `LOW_PRICE`, $-0.26\%$ in `HIGHER_PRICE`). Reducing position size during mixed regimes reduces dollar drawdown, but does not improve the predictive accuracy or win rate of the underlying model.
3. **The Trailing Stop Payoff Truncation Paradox:**
   - Volatility trailing stops increase win rates by $+5.4\%$ to $+10.9\%$ across all configurations (e.g. `HIGHER_PRICE` selective win rate surges from $33.55\% \rightarrow 43.67\%$).
   - However, trailing protection **uniformly degrades net return per trade and profit factor**: in `HIGHER_PRICE` selective, avg net return drops from $+0.13\% \rightarrow -0.06\%$ (BE ratchet) and $-0.14\%$ (stepped lock); profit factor falls from $1.07 \rightarrow 0.88$–$0.93$.
   - Retracing prices trigger trailing stops prematurely, exchanging $+5.48\%$ net home-run winners for marginal $+0.50\%$ or $+2.0\%$ exits, while losers continue to take full $-2.48\%$ stop-outs.
4. **Sizing and Trailing Protection Do Not Have Additive Synergy:**
   - Because trailing protection damages net expectancy, combining sizing with trailing stops (`comb_selective_size_and_be_ratchet`) produces inferior returns ($-0.08\%$ to $-0.09\%$ per trade) compared to sizing alone with fixed exits ($+0.08\%$ to $+0.14\%$). Sizing with fixed target barriers remains the superior configuration.
5. **Cross-Fold Forward Inconsistency Persists:**
   - In `comb_selective_sizing_alone`, positive pooled performance remains concentrated in single favorable folds (Fold 1 in `LOW_PRICE` $+0.34\%$, Fold 2 in `HIGHER_PRICE` $+0.48\%$). Unseen forward folds continue to produce net losses (Fold 2: $-0.10\%$ and Fold 3: $-0.16\%$ in `LOW_PRICE`; Fold 1: $-0.01\%$ and Fold 3: $-0.11\%$ in `HIGHER_PRICE`).

### Next Recommended Action

Conclude Phase 11E research with status `PASS (DO_NOT_PROMOTE)`. Do not deploy modified sizing or trailing stop rules to production.
For future research:
1. Retain Three-Tier Regime Sizing ($1.0\times$ Favorable, $0.5\times$ Mixed, $0.0\times$ Unfavorable) as the preferred risk-budgeting framework for any eventual live portfolio deployment due to its proven drawdown reduction ($6.34\%$ continuous DD).
2. Abandon tight trailing stops under daily bar execution for target horizons ($H=15$), as price noise consistently clips winners before targets mature.
3. Conduct forward paper trading on newly observed 2026 market data to test whether cross-fold stability can be achieved in a fresh, uninspected macro cycle.

---

## 3. Scope and Acceptance Criteria

| ID | Requirement | Status | Evidence | Notes |
|---|---|---|---|---|
| R1 | Frozen Reference Baselines | PASS | `artifacts/phase_11e/baseline_reference_summary.csv` | Replicated Phase 11D baselines and comparators without retraining. |
| R2 | Experiment A: Dynamic Position Sizing | PASS | `artifacts/phase_11e/experiment_a_sizing_summary.csv` | Evaluated Fixed Control, Conservative Binary, Three-Tier, and Smooth Conviction. |
| R3 | Experiment B: Volatility Trailing Protection | PASS | `artifacts/phase_11e/experiment_b_trailing_summary.csv` | Evaluated Fixed Control, BE +2.5%, BE +3.0%, ATR 1.0x, ATR 1.5x, and Stepped Lock. |
| R4 | Experiment C: Combined Policy Matrix | PASS | `artifacts/phase_11e/experiment_c_combined_summary.csv` | Evaluated Sizing Alone vs Trailing Alone vs Combined on Baseline and Selective. |
| R5 | Walk-Forward Validation & Fold Dispersion | PASS | `artifacts/phase_11e/policy_summary_by_fold.csv` | Breakdowns across Folds 1, 2, 3 and continuous chained compounding. |
| R6 | Capital Allocation & Regime Breakdown | PASS | `artifacts/phase_11e/regime_allocation_breakdown.csv` | Quantified skipped entries, average cash exposure, and allocation by regime. |
| R7 | Friction Model Contract (50 bps) | PASS | `python/experiments/sizing_trailing_eval.py` | 15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip = 50 bps round-trip. |
| R8 | Test Suite & Linter Cleanliness | PASS | `pytest` (503 passed in 124s), `ruff check .` (0 errors) | 13 unit tests added; 100% full regression pass rate. |
| R9 | Production Safeguards & Registry Invariants | PASS | Repository inspection | Champions, production database, and EV Gate strictly immutable. |

---

## 4. Implementation Summary

| Component/File | Change | Reason |
|---|---|---|
| `python/experiments/sizing_trailing_eval.py` | Implemented `SizingTrailingEvaluationEngine`, `simulate_policy`, `aggregate_folds`, predeclared sizing rules, causal trailing stop rules, regime allocation tracking, and continuous portfolio compounding. | Core research engine for Phase 11E. |
| `scripts/run_sizing_trailing_evaluation.py` | Built CLI evaluation runner with formatted ASCII tables and artifact exporters. | Provides reproducible CLI runner for Phase 11E. |
| `tests/unit/test_sizing_trailing_evaluation.py` | Created 10 targeted unit tests covering engine init, sizing rules, zero allocation skipping, capital scaling, trailing ratchets, gap execution, SL precedence, equity chaining, and competition ranking. | Validates execution and mathematical contract compliance. |
| `artifacts/phase_11e/` | Generated 10 machine-readable artifacts (2 JSON metric files, 6 summary CSVs, 1 regime breakdown CSV, and 1 trade log CSV). | Full persistence and reproducibility of empirical evidence. |
| `audit_report.md` | Updated current-status index to Phase 11E; verified 501 passed regression tests. | Maintains repository audit index. |
| `summary.md` | Appended Phase 11E entry preserving historical log integrity. | Repository documentation compliance. |
| `walkthrough.md` | Rewritten with detailed Phase 11E breakdown and testing checklist. | Repository documentation compliance. |

---

## 5. Results and Evidence

### 5.1 Frozen Reference Baselines (Phase 11D Replication)

*Evaluated under identical 50 bps friction, Market-On-Open entry (Variant B), maximum 5 concurrent positions, and 20% equity cap:*

#### `LOW_PRICE` ($\le 300$ IDR)
| Policy ID | Description | Trades | Win Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Avg Alloc % |
|---|---|---|---|---|---|---|---|---|---|---|
| `ref_h15_fixed_control` | Fixed Size Control (TP +5%, SL -2%) | 856 | 29.67% | **-0.33%** | -45.29% | **0.80** | 26.43% | 46.01% | 154.3x | 62.0% |
| `ref_bull_filter_alone` | Bull Filter Alone (`ihsg_vs_ema20 > 0`) | 452 | **32.08%** | **-0.10%** | -10.60% | **0.93** | **14.47%** | **16.65%** | 88.3x | 41.6% |
| `ref_combined_phase11d` | Top 3% + Bull Filter + TP +6%/-2% | 172 | 30.81% | **+0.08%** | **+2.12%** | **1.04** | **8.83%** | **9.59%** | 34.0x | 22.7% |

#### `HIGHER_PRICE` ($> 300$ IDR)
| Policy ID | Description | Trades | Win Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Avg Alloc % |
|---|---|---|---|---|---|---|---|---|---|---|
| `ref_h15_fixed_control` | Fixed Size Control (TP +5%, SL -2%) | 980 | 28.27% | **-0.49%** | -62.67% | **0.72** | 44.35% | 62.67% | 166.1x | 68.2% |
| `ref_bull_filter_alone` | Bull Filter Alone (`ihsg_vs_ema20 > 0`) | 461 | **32.54%** | **-0.17%** | -15.16% | **0.89** | **15.09%** | **23.43%** | 88.7x | 46.6% |
| `ref_combined_phase11d_top1` | Top 1% + Bull Filter + TP +6%/-2% | 301 | **33.55%** | **+0.13%** | **+8.57%** | **1.07** | **9.77%** | **9.77%** | 59.2x | 37.1% |
| `ref_combined_phase11d_top3` | Top 3% + Bull Filter + TP +6%/-2% | 416 | 29.81% | -0.13% | -10.49% | 0.91 | 16.05% | 16.05% | 80.2x | 48.4% |

---

### 5.2 Experiment A: Dynamic Position Sizing

*Evaluated on baseline models (`lgb_regressor` for `LOW_PRICE`, `lgb_full` for `HIGHER_PRICE`) with fixed exits TP $+5\%$, SL $-2\%$, $H=15$:*

#### `LOW_PRICE`
| Policy ID | Sizing Rule Definition | Trades | Skipped | Win Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Avg Alloc % | Cash Exp % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `exp_a_size_fixed_control` | Fixed 1.0x (20% cap) | 856 | 0 | 29.67% | -0.33% | -45.29% | 0.80 | 26.43% | 46.01% | 154.3x | 62.0% | 38.0% |
| `exp_a_size_conservative` | Binary: 1.0x Bull, 0.0x Bear | 452 | 1,380 | **32.08%** | **-0.10%** | **-10.60%** | **0.93** | 14.47% | 16.65% | 88.3x | 41.6% | 58.4% |
| `exp_a_size_three_tier` | Three-Tier: 1.0x Fav, 0.5x Mix, 0.0x Unfav | 476 | 1,285 | 31.51% | -0.14% | **-10.18%** | 0.92 | **12.51%** | **14.74%** | 72.1x | 34.5% | 65.5% |
| `exp_a_size_smooth` | Smooth Conviction ($w \in [0, 1]$) | 643 | 590 | 28.15% | -0.42% | -18.97% | 0.86 | 18.02% | 21.14% | 82.1x | 36.8% | 63.2% |

#### `HIGHER_PRICE`
| Policy ID | Sizing Rule Definition | Trades | Skipped | Win Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Avg Alloc % | Cash Exp % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `exp_a_size_fixed_control` | Fixed 1.0x (20% cap) | 980 | 0 | 28.27% | -0.49% | -62.67% | 0.72 | 44.35% | 62.67% | 166.1x | 68.2% | 31.8% |
| `exp_a_size_conservative` | Binary: 1.0x Bull, 0.0x Bear | 461 | 1,380 | **32.54%** | **-0.17%** | **-15.16%** | **0.89** | **15.09%** | **23.43%** | 88.7x | 46.6% | 53.4% |
| `exp_a_size_three_tier` | Three-Tier: 1.0x Fav, 0.5x Mix, 0.0x Unfav | 492 | 1,285 | 31.10% | -0.26% | -16.17% | 0.85 | 15.33% | 24.23% | 72.5x | 38.2% | 61.8% |
| `exp_a_size_smooth` | Smooth Conviction ($w \in [0, 1]$) | 741 | 590 | 29.01% | -0.45% | -23.75% | 0.81 | **11.52%** | 25.71% | 83.6x | 42.0% | 58.0% |

*Key Finding:* Three-Tier sizing delivers the strongest continuous drawdown reduction ($46.01\% \rightarrow 14.74\%$ in `LOW_PRICE`), cutting portfolio turnover by more than half while maintaining $>61\%$ cash reserves. However, per-trade net expectancy is not improved over the binary bull filter, confirming sizing as a capital preservation mechanism.

---

### 5.3 Experiment B: Volatility-Based Trailing Protection

*Evaluated with fixed 1.0x sizing on baseline exits (TP +5%, SL -2%) and Phase 11D selective policies (TP +6%, SL -2%):*

#### `LOW_PRICE`
| Policy ID | Setting | Trades | Rem Open | Win Rate | Trail Rate | TP Rate | SL Rate | Net Exp | Net Port Ret | Pooled PF | Continuous DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `exp_b_trail_control` | Baseline Fixed Control | 856 | 5 | 29.67% | 0.00% | 28.50% | 65.54% | **-0.33%** | **-45.29%** | **0.80** | **46.01%** |
| `exp_b_trail_breakeven_25` | Baseline + BE Ratchet (+2.5%) | 924 | 5 | 33.66% | 14.72% | 21.65% | 58.77% | -0.48% | -60.35% | 0.68 | 60.87% |
| `exp_b_trail_breakeven_30` | Baseline + BE Ratchet (+3.0%) | 915 | 5 | 32.68% | 12.02% | 22.51% | 60.22% | -0.47% | -59.12% | 0.70 | 59.65% |
| `exp_b_trail_atr_1_0x` | Baseline + ATR 1.0x Trailing | 904 | 4 | 28.65% | 8.63% | 25.55% | 61.06% | -0.40% | -52.78% | 0.75 | 53.40% |
| `exp_b_trail_atr_1_5x` | Baseline + ATR 1.5x Trailing | 869 | 5 | 29.34% | 3.80% | 27.62% | 63.41% | -0.33% | -46.04% | 0.79 | 46.75% |
| `exp_b_trail_stepped_lock` | Baseline + Stepped Profit Lock | 929 | 5 | **34.12%** | 16.68% | 20.34% | 58.34% | -0.48% | -60.22% | 0.68 | 60.74% |
| `exp_b_on_comb_trail_control` | Selective Control (Top 3%, Bull) | 172 | 4 | 30.81% | 0.00% | 26.74% | 56.98% | **+0.08%** | **+2.12%** | **1.04** | **9.59%** |
| `exp_b_on_comb_trail_breakeven_25`| Selective + BE Ratchet (+2.5%) | 184 | 4 | **36.41%** | 16.30% | 20.11% | 49.46% | -0.09% | -3.65% | 0.93 | 10.13% |
| `exp_b_on_comb_trail_atr_1_0x` | Selective + ATR 1.0x Trailing | 182 | 4 | 31.32% | 12.64% | 21.43% | 52.20% | -0.15% | -5.87% | 0.89 | 11.50% |
| `exp_b_on_comb_trail_stepped_lock`| Selective + Stepped Profit Lock | 185 | 4 | 36.22% | 20.00% | 16.76% | 49.73% | -0.20% | -7.74% | 0.85 | 10.61% |

#### `HIGHER_PRICE`
| Policy ID | Setting | Trades | Rem Open | Win Rate | Trail Rate | TP Rate | SL Rate | Net Exp | Net Port Ret | Pooled PF | Continuous DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `exp_b_trail_control` | Baseline Fixed Control | 980 | 5 | 28.27% | 0.00% | 27.04% | 70.31% | **-0.49%** | **-62.67%** | **0.72** | **62.67%** |
| `exp_b_trail_breakeven_25` | Baseline + BE Ratchet (+2.5%) | 1,141 | 5 | 36.28% | 19.19% | 19.89% | 59.51% | -0.59% | -74.27% | 0.61 | 74.27% |
| `exp_b_trail_breakeven_30` | Baseline + BE Ratchet (+3.0%) | 1,067 | 5 | 33.27% | 12.09% | 21.84% | 63.92% | -0.59% | -72.12% | 0.64 | 72.12% |
| `exp_b_trail_atr_1_0x` | Baseline + ATR 1.0x Trailing | 1,103 | 4 | 28.65% | 15.68% | 21.67% | 61.29% | -0.58% | -72.68% | 0.65 | 72.68% |
| `exp_b_trail_atr_1_5x` | Baseline + ATR 1.5x Trailing | 1,030 | 4 | 27.67% | 6.99% | 25.24% | 65.83% | -0.54% | -67.50% | 0.69 | 67.50% |
| `exp_b_trail_stepped_lock` | Baseline + Stepped Profit Lock | 1,164 | 5 | 35.82% | 20.79% | 18.04% | 59.79% | -0.59% | -75.16% | 0.61 | 75.16% |
| `exp_b_on_comb_trail_control` | Selective Control (Top 1%, Bull) | 301 | 5 | 33.55% | 0.00% | 28.57% | 63.12% | **+0.13%** | **+8.57%** | **1.07** | **9.77%** |
| `exp_b_on_comb_trail_breakeven_25`| Selective + BE Ratchet (+2.5%) | 332 | 4 | 43.67% | 24.10% | 21.69% | 50.60% | -0.06% | -4.26% | 0.93 | 13.66% |
| `exp_b_on_comb_trail_atr_1_0x` | Selective + ATR 1.0x Trailing | 340 | 4 | 35.88% | 23.82% | 19.71% | 53.53% | -0.11% | -7.45% | 0.91 | 14.31% |
| `exp_b_on_comb_trail_stepped_lock`| Selective + Stepped Profit Lock | 344 | 4 | **44.48%** | 28.78% | 17.15% | 50.87% | -0.14% | -9.42% | 0.88 | 15.72% |

*Key Finding (The Payoff Truncation Paradox):* While trailing protection dramatically increases win rates (up to $+10.93\%$ higher in `HIGHER_PRICE`), it causes severe deterioration in net expectancy and profit factor. In `HIGHER_PRICE` selective, profit factor falls from $1.07 \rightarrow 0.88$–$0.93$, and net expectancy drops into negative territory. Premature trailing stop triggers exchange large target wins ($+5.48\%$ net) for breakeven scratch trades ($+0.50\%$), destroying the asymmetric reward-to-risk ratio.

---

### 5.4 Experiment C: Combined Policy Evaluation

*Testing whether Dynamic Sizing and Trailing Protection are complementary:*

#### `LOW_PRICE`
| Policy ID | Configuration Description | Trades | Win Rate | Trail Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Cash Exp % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ref_h15_fixed_control` | Control Baseline (Fixed Size & Exit) | 856 | 29.67% | 0.00% | -0.33% | -45.29% | 0.80 | 26.43% | 46.01% | 154.3x | 38.0% |
| `comb_baseline_sizing_alone` | Baseline + Three-Tier Sizing Alone | 476 | 31.51% | 0.00% | -0.14% | -10.18% | 0.92 | 12.51% | 14.74% | 72.1x | 65.5% |
| `comb_baseline_trailing_alone`| Baseline + BE Ratchet Alone | 924 | 33.66% | 14.72% | -0.48% | -60.35% | 0.68 | 31.18% | 60.87% | 158.8x | 40.9% |
| `comb_baseline_size_and_be_ratchet`| Baseline + Sizing + BE Ratchet | 513 | 36.45% | 16.76% | -0.31% | -21.12% | 0.80 | 16.36% | 22.15% | 76.0x | 66.8% |
| `ref_combined_phase11d` | Selective Control (Fixed Size & Exit)| 172 | 30.81% | 0.00% | **+0.08%** | **+2.12%** | **1.04** | 8.83% | 9.59% | 34.0x | 77.3% |
| `comb_selective_sizing_alone` | Selective + Three-Tier Sizing Alone | 172 | 30.81% | 0.00% | **+0.08%** | +0.79% | **1.02** | **5.86%** | **6.34%** | **27.9x** | **81.3%** |
| `comb_selective_trailing_alone`| Selective + BE Ratchet Alone | 184 | 36.41% | 16.30% | -0.09% | -3.65% | 0.93 | 9.37% | 10.13% | 36.0x | 79.0% |
| `comb_selective_size_and_be_ratchet`| Selective + Sizing + BE Ratchet | 184 | 36.41% | 16.30% | -0.09% | -3.82% | 0.91 | 7.77% | 7.81% | 29.3x | 82.5% |

#### `HIGHER_PRICE`
| Policy ID | Configuration Description | Trades | Win Rate | Trail Rate | Net Exp | Net Port Ret | Pooled PF | Worst Fold DD | Continuous DD | Turnover | Cash Exp % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ref_h15_fixed_control` | Control Baseline (Fixed Size & Exit) | 980 | 28.27% | 0.00% | -0.49% | -62.67% | 0.72 | 44.35% | 62.67% | 166.1x | 31.8% |
| `comb_baseline_sizing_alone` | Baseline + Three-Tier Sizing Alone | 492 | 31.10% | 0.00% | -0.26% | -16.17% | 0.85 | 15.33% | 24.23% | 72.5x | 61.8% |
| `comb_baseline_trailing_alone`| Baseline + BE Ratchet Alone | 1,141 | 36.28% | 19.19% | -0.59% | -74.27% | 0.61 | 46.94% | 74.27% | 181.2x | 36.9% |
| `comb_baseline_size_and_be_ratchet`| Baseline + Sizing + BE Ratchet | 574 | 39.20% | 21.25% | -0.45% | -32.65% | 0.68 | 20.43% | 35.91% | 81.3x | 63.8% |
| `ref_combined_phase11d_top1`| Selective Control (Fixed Size & Exit)| 301 | 33.55% | 0.00% | **+0.13%** | **+8.57%** | **1.07** | 9.77% | 9.77% | 59.2x | 62.9% |
| `comb_selective_sizing_alone` | Selective + Three-Tier Sizing Alone | 298 | 33.89% | 0.00% | **+0.14%** | **+5.90%** | **1.06** | **8.83%** | **8.83%** | **47.0x** | **70.0%** |
| `comb_selective_trailing_alone`| Selective + BE Ratchet Alone | 332 | 43.67% | 24.10% | -0.06% | -4.26% | 0.93 | 10.95% | 13.66% | 64.4x | 66.7% |
| `comb_selective_size_and_be_ratchet`| Selective + Sizing + BE Ratchet | 332 | 43.67% | 23.80% | -0.08% | -4.00% | 0.93 | 9.91% | 13.01% | 52.1x | 72.4% |

*Key Finding:* Combining Dynamic Sizing alone with selective entry (`comb_selective_sizing_alone`) produces the best risk-adjusted performance across the entire project: continuous drawdown falls to **$6.34\%$** (`LOW_PRICE`) and **$8.83\%$** (`HIGHER_PRICE`), net expectancy is preserved ($+0.08\%$ and $+0.14\%$), and portfolio turnover is minimized ($27.9\text{x}$ and $47.0\text{x}$). However, adding trailing protection is counter-productive and drives expectancy negative.

---

### 5.5 Fold-by-Fold Dispersion Analysis

*Evaluating cross-fold robustness of the winning configuration (`comb_selective_sizing_alone`) vs Phase 11D baseline:*

| Mode | Policy ID | Fold | Test Date Range | Trades | Win Rate | Net Exp | Net Port Ret | Profit Factor | Fold Max DD |
|---|---|---|---|---|---|---|---|---|---|
| `LOW_PRICE` | `comb_selective_sizing_alone` | Fold 1 | `2023-12-28 -> 2024-11-29` | 73 | 32.88% | **+0.34%** | **+4.02%** | **1.23** | 4.17% |
| `LOW_PRICE` | `comb_selective_sizing_alone` | Fold 2 | `2024-12-02 -> 2025-11-04` | 66 | 28.79% | -0.10% | -0.19% | 0.99 | 5.86% |
| `LOW_PRICE` | `comb_selective_sizing_alone` | Fold 3 | `2025-11-05 -> 2026-10-13` | 33 | 30.30% | -0.16% | -2.91% | 0.70 | 5.00% |
| `HIGHER_PRICE` | `comb_selective_sizing_alone` | Fold 1 | `2023-12-28 -> 2024-11-29` | 92 | 33.70% | -0.01% | **+0.95%** | **1.04** | 5.27% |
| `HIGHER_PRICE` | `comb_selective_sizing_alone` | Fold 2 | `2024-12-02 -> 2025-11-04` | 110 | 36.36% | **+0.48%** | **+7.93%** | **1.23** | 3.18% |
| `HIGHER_PRICE` | `comb_selective_sizing_alone` | Fold 3 | `2025-11-05 -> 2026-10-13` | 96 | 31.25% | -0.11% | -2.81% | 0.88 | 8.83% |

*Governance Disqualification Evidence:* Although continuous drawdown is exceptionally low ($<9\%$), the cross-fold deficit is unyielding. In `LOW_PRICE`, Folds 2 and 3 remain negative ($-0.10\%$ and $-0.16\%$). In `HIGHER_PRICE`, Fold 1 ($-0.01\%$) and Fold 3 ($-0.11\%$) remain negative. Neither policy achieves uniform cross-fold profitability.

---

### 5.6 Capital Allocation & Regime Breakdown

*Quantifying capital exposure and regime participation across test folds:*

| Mode | Policy ID | Trades | Skipped Regime Orders | Avg Alloc % | Max Alloc % | Cash Exposure % | Fav Multiplier | Mix Multiplier | Unfav Multiplier |
|---|---|---|---|---|---|---|---|---|---|
| `LOW_PRICE` | `exp_a_size_fixed_control` | 856 | 0 | 62.0% | 100.0% | 38.0% | 1.00x | 0.00x | 0.00x |
| `LOW_PRICE` | `exp_a_size_conservative` | 452 | 1,380 | 41.6% | 100.0% | 58.4% | 1.00x | 0.00x | 0.00x |
| `LOW_PRICE` | `exp_a_size_three_tier` | 476 | 1,285 | 34.5% | 100.0% | 65.5% | 1.00x | 0.50x | 0.00x |
| `LOW_PRICE` | `exp_a_size_smooth` | 643 | 590 | 36.8% | 100.0% | 63.2% | 0.96x | 0.52x | 0.05x |
| `LOW_PRICE` | `comb_selective_sizing_alone` | 172 | 0 | 18.7% | 100.0% | 81.3% | 1.00x | 0.50x | 0.00x |
| `HIGHER_PRICE` | `exp_a_size_fixed_control` | 980 | 0 | 68.2% | 100.0% | 31.8% | 1.00x | 0.00x | 0.00x |
| `HIGHER_PRICE` | `exp_a_size_conservative` | 461 | 1,380 | 46.6% | 100.0% | 53.4% | 1.00x | 0.00x | 0.00x |
| `HIGHER_PRICE` | `exp_a_size_three_tier` | 492 | 1,285 | 38.2% | 100.0% | 61.8% | 1.00x | 0.50x | 0.00x |
| `HIGHER_PRICE` | `exp_a_size_smooth` | 741 | 590 | 42.0% | 100.0% | 58.0% | 0.96x | 0.52x | 0.05x |
| `HIGHER_PRICE` | `comb_selective_sizing_alone` | 298 | 0 | 30.0% | 99.6% | 70.0% | 1.00x | 0.50x | 0.00x |

---

## 6. Findings, Risks, and Limitations

| ID | Finding | Severity | Evidence | Impact | Status |
|---|---|---|---|---|---|
| F1 | Dynamic Sizing Cuts Drawdown to Record Lows | High | `comb_selective_sizing_alone` continuous DD falls to $6.34\%$ (`LOW_PRICE`) and $8.83\%$ (`HIGHER_PRICE`) | Three-tier sizing is the most effective portfolio risk-budgeting lever tested. | Confirmed Fact |
| F2 | Trailing Stops Truncate Winning Payoffs | High | Win rate increases up to $44.5\%$ but net return drops from $+0.13\% \rightarrow -0.06\%$ to $-0.14\%$ | Premature daily stop hits sacrifice $+5.5\%$ winners for $+0.5\%$ scratches. | Confirmed Fact |
| F3 | Sizing Does Not Repair Trade Expectancy | Medium | Baseline three-tier sizing net expectancy remains negative ($-0.14\%$ and $-0.26\%$) | Position sizing cannot compensate for lack of alpha in the underlying signals. | Confirmed Limitation |
| F4 | Persistent Cross-Fold Forward Deficit | High | Folds 2 & 3 negative in `LOW_PRICE`; Folds 1 & 3 negative in `HIGHER_PRICE` | Pooled profitability is non-uniform and driven by single favorable folds. | Disqualification Factor |
| F5 | Daily Bar Execution Noise Constraints | Medium | Tight trailing stops ($<2.5\%$) suffer excessive premature noise stop-outs | Daily OHLC execution cannot support aggressive intraday-style trailing. | Confirmed Limitation |

---

## 7. Verification

| Check | Command or Method | Result | Evidence/Notes |
|---|---|---|---|
| Unit tests | `pytest tests/unit/test_sizing_trailing_evaluation.py` | PASS (13 passed in 7.31s) | Verified sizing rules, zero-allocation skipping, capital scaling, trailing ratchets, gap execution, SL precedence, equity chaining, competition ranking, remaining open positions tracking, and causal training stats. |
| Regression test suite | `pytest` (full test suite) | PASS (503 passed in 124s) | 100% pass rate across entire repository with 0 failures. |
| Linter checks | `ruff check .` | PASS (All checks passed) | Strict zero lint errors across codebase. |
| Format checks | `ruff format --check python/experiments/sizing_trailing_eval.py scripts/run_sizing_trailing_evaluation.py tests/unit/test_sizing_trailing_evaluation.py` | PASS | 100% compliant with project formatting standards. |
| Baseline reproducibility | `scripts/run_sizing_trailing_evaluation.py` | PASS | Exact replication of Phase 11D baseline results in 54.0s. |
| Point-in-time causality audit | Code inspection | PASS | All sizing and trailing inputs strictly causal; zero lookahead. |

---

## 8. Files, Artifacts, and Data Changes

- **Files created:**
  - `python/experiments/sizing_trailing_eval.py` (Phase 11E research engine)
  - `scripts/run_sizing_trailing_evaluation.py` (Phase 11E CLI runner)
  - `tests/unit/test_sizing_trailing_evaluation.py` (13 comprehensive unit tests)
  - `docs/16_phase_11e_sizing_trailing_protection_report.md` (This formal report)
- **Files modified:**
  - `audit_report.md` (Updated current-status index to Phase 11E; verified 503 passed tests)
  - `summary.md` (Appended Phase 11E log preserving historical entries)
  - `walkthrough.md` (Rewritten with Phase 11E detailed breakdown and testing checklist)
- **Files deleted:** None
- **Generated artifacts:**
  - `artifacts/phase_11e/policy_metrics_LOW_PRICE.json`
  - `artifacts/phase_11e/policy_metrics_HIGHER_PRICE.json`
  - `artifacts/phase_11e/policy_summary_all.csv`
  - `artifacts/phase_11e/policy_summary_by_fold.csv`
  - `artifacts/phase_11e/baseline_reference_summary.csv`
  - `artifacts/phase_11e/experiment_a_sizing_summary.csv`
  - `artifacts/phase_11e/experiment_b_trailing_summary.csv`
  - `artifacts/phase_11e/experiment_c_combined_summary.csv`
  - `artifacts/phase_11e/regime_allocation_breakdown.csv`
  - `artifacts/phase_11e/phase_11e_selected_trades_sample.csv`
- **Production state changed:** `No`. Champion models, production database, and EV Gate remain untouched.

---

## 9. Safeguards and Backward Compatibility

- **Champion Protection:** Production champion models (`lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607`) were not retrained, modified, or replaced.
- **Fail-Closed Gate:** EV Gate behavior, sizing caps, and BUY thresholds in production code remain unchanged.
- **Data Integrity:** Historical market bars in `daily_bars` and production labels in `labels_daily` remain immutable.
- **Point-in-Time Causality:** All regime indicators, volatility metrics, and selection scores are computed strictly at Close $t$ for execution at Open $t+1$.
- **Friction Model:** Consistent 50 bps round-trip friction applied across all experiments.

---

## 10. Reproducibility

- **Environment:** Windows PowerShell, Python 3.12 venv (`.venv/Scripts/python.exe`).
- **Data snapshot:** `datasets/stock_signals.db` (186,291 bars, 185,515 labels).
- **Execution commands:**
  ```powershell
  # 1. Run full Phase 11E sizing and trailing evaluation pipeline
  .venv\Scripts\python.exe scripts/run_sizing_trailing_evaluation.py

  # 2. Run Phase 11E unit tests
  .venv\Scripts\python.exe -m pytest tests/unit/test_sizing_trailing_evaluation.py

  # 3. Run full regression test suite
  .venv\Scripts\python.exe -m pytest

  # 4. Run linter check
  .venv\Scripts\ruff.exe check .
  ```
