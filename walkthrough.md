# Walkthrough — Phase 11B.1: Candidate Model Training & Evaluation

## 1. Work Session Summary

In this work session, we executed **Phase 11B.1: Candidate Model Training & Evaluation** for the BEI dual-mode stock signal system. Building on the Phase 11A feature ablation findings and Phase 11B.0 target contract audit, we implemented an offline candidate model evaluation pipeline (`python/experiments/candidate_eval.py` and `scripts/run_candidate_evaluation.py`) that evaluated 16 model configurations across 3 expanding walk-forward temporal folds with a 10-day purge window under dual target definitions (Variant A: Close-Anchor vs Variant B: Next-Session Open-Anchor).

We conducted predictive evaluation (ROC-AUC, PR-AUC, Brier score, ECE, daily cross-sectional Top-10% and Top-5 precision) and realistic discrete-event trading simulation (with 50 bps round-trip IDX friction, 100-share lots, and pre-entry gap protection). Based on the empirical finding that no candidate model achieved positive net trading returns after transaction costs, we established the governance decision `DO_NOT_PROMOTE`. Production champions remain 100% active and untouched.

---

## 2. Key Empirical Findings

1. **Operational Gap Invalidation Suppression in Variant B:**
   - Training on Variant B (Next-Open Anchor) eliminates pre-entry lookahead bias.
   - In `HIGHER_PRICE`, pre-entry invalidations drop from 157 to 79 (full model) and 167 to 109 (ablation model).
   - Win rate improves from $25.48\%$ to $28.07\%$, and maximum drawdown decreases from $60.23\%$ to $45.02\%$.
2. **Net Negative Trading Return Barrier Across All Candidates:**
   - With 15 bps buy fee, 25 bps sell fee, 20 bps slippage, and 100-share lotting, break-even requires $> 32\%$ win rate.
   - All candidate models achieve win rates of $21.57\%$ to $28.62\%$, yielding average net returns between $-0.49\%$ and $-1.01\%$ per trade and profit factors below 1.0 ($0.49$ to $0.71$).
3. **Ablation Models Show Predictive Discrimination but Fail to Improve Trading PnL:**
   - In `LOW_PRICE`, removing `trend` improves Variant A ROC-AUC ($0.5686 \rightarrow 0.5800$) and Daily Top-10% precision ($31.85\% \rightarrow 33.27\%$). However, simulated trading net return deteriorates from $-0.49\%$ to $-0.61\%$, and max drawdown deepens from $44.70\%$ to $53.82\%$.
   - In `HIGHER_PRICE`, removing `market_regime` improves Variant B ROC-AUC ($0.5483 \rightarrow 0.5686$), but simulated trading exhibits higher invalidations (109 vs 79) and deeper drawdown ($59.53\%$ vs $45.02\%$).
4. **Governance Decision:**
   - `DO_NOT_PROMOTE`: Production champions `lightgbm_classification_20261014_093522` and `lightgbm_classification_20261014_093607` remain active.

---

## 3. Detailed Task Breakdown & Code Modifications

### A. Candidate Evaluation Engine
- **File:** `python/experiments/candidate_eval.py`
  * Implemented `CandidateEvaluationRunner` class supporting 3-fold expanding walk-forward validation and 10-day purge.
  * Extracted features up to Close $t$, causal median imputation fit on training folds only.
  * Implemented dual-target datasets: Variant A (all eligible decision rows) vs Variant B (valid filled modeled entries, excluding pre-entry invalidations and unfilled bars).
  * Implemented `_simulate_fold_trading` simulating Next-Open execution, pre-entry gap protection ($\le -2\%$, $\ge +5\%$, $> 5\%$ dev), lot sizing (100 shares), concurrent position limits (max 5), and IDX fees (15 bps buy, 25 bps sell, 10 bps slippage each way).
  * Hardened simulation edge cases: initialized `total_eq` before loop to prevent `UnboundLocalError` on empty data, guarded positive closing prices in open position valuation, and added `default=str` serialization to `export_artifacts`.
  * Implemented `_compute_macro_summaries` and `_aggregate_trading_summaries` for macro fold aggregation.
  * Implemented `export_artifacts` generating 13 machine-readable JSON and CSV files.

### B. CLI Runner
- **File:** `scripts/run_candidate_evaluation.py`
  * Provides command-line interface with `--mode`, `--n-splits`, `--purge-days`, `--random-state`, and `--output-dir`.
  * Outputs formatted comparison tables for predictive performance and simulated trading.

### C. Targeted Unit Tests
- **File:** `tests/unit/test_candidate_evaluation.py`
  * Added 8 unit tests verifying candidate specification completeness, gap invalidation handling in trading simulation, excessive deviation and suspension rejection, max positions capacity limit, empty dataframe robustness, macro aggregation mathematics, trading summary aggregation, and artifact export completeness.

### D. Governance Documentation & Status Index
- **File:** `docs/13_phase_11b_candidate_model_evaluation_report.md`
  * Authored comprehensive 11-section formal report following `docs/AGENT_REPORT_TEMPLATE.md`.
- **File:** `audit_report.md`
  * Updated concise repository status index to Phase 11B.1 with relative Markdown links.
- **File:** `summary.md`
  * Appended cumulative Log Entry 56 preserving audit trail.

---

## 4. Testing Checklist

- [x] Implement candidate model evaluation engine (`python/experiments/candidate_eval.py`)
- [x] Implement CLI runner script (`scripts/run_candidate_evaluation.py`)
- [x] Run candidate evaluation across both modes (`python scripts/run_candidate_evaluation.py --mode BOTH`)
- [x] Export 13 machine-readable artifacts into `artifacts/candidate_eval/`
- [x] Add targeted unit tests (`tests/unit/test_candidate_evaluation.py`, 8 passed)
- [x] Verify production champions untouched (`models/registry/` checksums intact)
- [x] Verify database immutability (`daily_bars` and `labels_daily` unchanged)
- [x] Run full pytest suite (468 passed)
- [x] Run linter (`ruff check .`, 0 errors)
- [x] Create formal report `docs/13_phase_11b_candidate_model_evaluation_report.md`
- [x] Update `audit_report.md` status index
- [x] Append Log Entry 56 to `summary.md`
