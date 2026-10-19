# Walkthrough — Phase 11B.1: Trading Metric Reconciliation

## 1. Work Session Summary

In this work session, we executed the **Phase 11B.1 Trading Metric Reconciliation** for the BEI dual-mode stock signal system. Without retraining any models, we resolved simulator friction discrepancies, established mathematically explicit metric definitions, reconciled reported test and return metrics, and validated reproducible recomputation directly from saved out-of-sample predictions.

The simulator was aligned with the production cost contract: 15 bps buy commission, 25 bps sell commission, and 10 bps total round-trip slippage allocated evenly as 5 bps on entry fill and 5 bps on exit fill (50 bps nominal round-trip friction). Using the existing saved out-of-sample predictions (`candidate_oos_predictions_{mode}.csv`), we recomputed trading performance across all 16 candidate configurations. We separated the true pooled profit factor from the mean fold profit factor, and distinguished the worst-fold maximum drawdown from the continuous portfolio maximum drawdown.

---

## 2. Key Empirical Findings & Reconciled Outcomes

1. **Reconciled Return Range Across All 16 Candidates:**
   - Under 50 bps round-trip friction, all candidate models produce negative average net returns, spanning **$-0.33\%$ to $-0.92\%$** per trade across the entire 16-candidate matrix.
   - Best candidate models: `VA_lgb_full` ($-0.33\%$) and `VB_lgb_full` ($-0.38\%$) in `LOW_PRICE`; `VB_lgb_full` ($-0.45\%$) in `HIGHER_PRICE`.
   - Linear baselines suffer severe negative expectancy: `VA_logistic_baseline` ($-0.70\%$ in LOW, $-0.92\%$ in HIGH).
2. **Profit Factor Distinction:**
   - Reconciled true pooled profit factor ($\sum \text{Gain} / \sum |\text{Loss}|$ across all trades) spans **$0.52$ to $0.80$**.
   - Arithmetic mean fold profit factor spans **$0.52$ to $0.79$**.
3. **Drawdown Definition Divergence:**
   - **Worst-Fold Max Drawdown:** Deepest single-fold decline within an independent 221-day period spans **$34.46\%$ to $83.24\%$**.
   - **Continuous Portfolio Max Drawdown:** Compounded continuous decline across all 663 walk-forward test days spans **$62.63\%$ to $98.54\%$**. Conflating worst-fold drawdown with continuous portfolio drawdown severely understates compounding risk.
4. **Variant B Execution Fidelity Confirmed:**
   - In `HIGHER_PRICE`, Variant B cuts pre-entry gap invalidations from 156 to 80 (full model) and from 165 to 107 (ablation model).
   - Variant B achieves superior win rate ($29.11\%$ vs $26.49\%$) and lower worst-fold max drawdown ($38.89\%$ vs $56.15\%$).
5. **Zero-Retraining Governance Preservation:**
   - 100% of candidate predictive models, out-of-sample probabilities, production champions, SQLite tables, and EV gate configs remained untouched.
   - Recomputation executed in ~92 seconds via `--recompute-trading-only`.

---

## 3. Detailed Task Breakdown & Code Modifications

### A. Candidate Evaluation Engine
- **File:** `python/experiments/candidate_eval.py`
  * **Lines 380–388:** Added `"va_entry_price": list(df_test["va_entry_price"])` to `fold_oos_dict` so exported OOS prediction artifacts are completely self-contained.
  * **Lines 530–545:** Configured `_simulate_fold_trading` call with `slippage_entry_bps=5.0` and `slippage_exit_bps=5.0`, and passed `all_model_trades` into `_aggregate_trading_summaries`.
  * **Lines 580–615:** Updated `_simulate_fold_trading` signature to accept `slippage_entry_bps: float = 5.0`, `slippage_exit_bps: float = 5.0`, and backward-compatible `slippage_bps: Optional[float] = None` (which splits total slippage equally). Documented exact 50 bps friction contract.
  * **Lines 695–702:** Applied `fill_price = b_open * (1.0 + slippage_entry_bps / 10000.0)`.
  * **Lines 775–782:** Applied `exit_fill = exit_raw * (1.0 - slippage_exit_bps / 10000.0)`.
  * **Lines 820–828 & 900–908:** Recorded `daily_equity` on each trading date and returned it in the simulation fold dictionary.
  * **Lines 975–1045:** Rewrote `_aggregate_trading_summaries` to compute true `pooled_profit_factor`, arithmetic `mean_profit_factor`, `worst_fold_max_drawdown_pct`, and continuous chained `continuous_max_drawdown_pct` (with backward-compatible alias `"max_drawdown_pct"`).
  * **Lines 1120–1150:** Added JSON artifact export for trading results (`candidate_trading_results_{mode}.json` and `candidate_trading_aggregate.json`).
  * **Lines 1165–1255:** Implemented `recompute_trading_from_saved_predictions(mode, artifacts_dir, ...)` to reload universe bars and saved OOS prediction CSVs and re-simulate trading without retraining any models.

### B. CLI Evaluation Runner
- **File:** `scripts/run_candidate_evaluation.py`
  * **Lines 56–61:** Added `--recompute-trading-only` CLI flag.
  * **Lines 80–95:** Updated console comparison table columns to explicitly display `pooled_profit_factor`, `mean_profit_factor`, `worst_fold_max_drawdown_pct`, and `continuous_max_drawdown_pct`.
  * **Lines 110–140:** Implemented execution branch in `main()` to invoke `recompute_trading_from_saved_predictions` and export updated artifacts when `--recompute-trading-only` is provided.

### C. Targeted Unit Tests
- **File:** `tests/unit/test_candidate_evaluation.py`
  * **Lines 390–460:** Added `test_slippage_friction_allocation()` verifying exact 5 bps entry fill ($100.05$) and 5 bps exit fill ($105.00$) accounting.
  * **Lines 462–558:** Added `test_pooled_vs_mean_profit_factor_and_drawdown_distinction()` verifying separate computation of pooled PF ($2.0$) vs mean PF ($1.25$) and worst-fold DD ($20.0\%$) vs continuous DD.
  * **Lines 560–578:** Added `test_recompute_trading_from_saved_predictions()` verifying idempotent trading recomputation directly from saved artifacts.
  * **Test Suite Status:** All 11 unit tests passed in 2.67s.

### D. Governance Documentation & Status Index
- **File:** `docs/13_phase_11b_candidate_model_evaluation_report.md`
  * Updated formal report with reconciled before-and-after tables, formal mathematical definitions, reconciled return range across all candidates ($-0.33\%$ to $-0.92\%$), reconciled test count (471 passed), and exact reproducible commands.
- **File:** `audit_report.md`
  * Updated concise repository status index to reflect reconciled Phase 11B.1 metrics.
- **File:** `summary.md`
  * Appended cumulative Log Entry 57 recording problems and solutions.

---

## 4. Testing Checklist

The user and reviewers should verify the following items:

- [ ] **Friction Model Verification:** Run `python -m pytest tests/unit/test_candidate_evaluation.py -k test_slippage_friction_allocation` and verify 5 bps entry + 5 bps exit slippage is enforced.
- [ ] **Metric Definition Math:** Run `python -m pytest tests/unit/test_candidate_evaluation.py -k test_pooled_vs_mean` and confirm pooled PF and worst-fold/continuous DD distinctions pass.
- [ ] **Retraining-Free Recompute Runner:** Run `python scripts/run_candidate_evaluation.py --mode BOTH --recompute-trading-only` and confirm completion in < 2 minutes with zero model training logs.
- [ ] **Artifact Integrity:** Check `artifacts/candidate_eval/candidate_trading_aggregate.csv` and verify columns `avg_net_return`, `pooled_profit_factor`, `mean_profit_factor`, `worst_fold_max_drawdown_pct`, and `continuous_max_drawdown_pct` exist and are populated.
- [ ] **Full Regression Suite:** Run `python -m pytest` and confirm 471 tests pass without errors.
- [ ] **Linter Hygiene:** Run `python -m ruff check .` and confirm 0 errors.
- [ ] **Champion Model State:** Verify `git status models/registry/` shows no untracked or modified files (champions remain untouched).
- [ ] **Database State:** Verify `datasets/stock_signals.db` has not been modified or migrated.
