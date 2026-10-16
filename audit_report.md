# Project Audit Reports Index — BEI Dual-Mode Stock Signal System

This document serves as the top-level index for technical audit reports, system validation records, and experimental evaluations conducted across the `hikwoa-hfw/idx-stock-signal` platform.

---

## 1. System Status & Active Model Gates

- **Platform Status:** Operational / Research Evaluation (Phase 11A.1 Completed)
- **Active Model Champions (Untouched & Protected):**
  * `LOW_PRICE` ($\le 300$): `lightgbm_classification_20261014_093522` (Active Champion)
  * `HIGHER_PRICE` ($> 300$): `lightgbm_classification_20261014_093607` (Active Champion)
- **Database Status:** `datasets/stock_signals.db` verified with 186,291 daily bars, 186,291 feature records, and 185,515 label records across 208 tickers.

---

## 2. Chronological Audit & Research Reports

| Phase / Date | Report Document | Scope / Objective | Status | Key Verdict / Artifacts |
|---|---|---|---|---|
| **Phase 11A.1**<br>`2026-10-16` | [docs/11_feature_ablation_metric_validation_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/11_feature_ablation_metric_validation_report.md) | **Validate Fold Aggregation & Daily Ranking Metrics:** Replaced pooled cross-fold rankings with per-fold evaluations, macro-averages (mean/std/min/max), and daily cross-sectional Top-10% precision ($N \ge 10$, deterministic tie-breaking). | `PASS`<br>(Ready for Phase 11B) | Confirmed: Pruning `trend` from `LOW_PRICE` uniformly improves all metrics (+2.04% daily precision); `market_regime` indispensable for `LOW_PRICE`; `HIGHER_PRICE` market regime shows fold divergence.<br>Artifacts in `artifacts/ablation/`. |
| **Phase 11A**<br>`2026-10-16` | [docs/10_controlled_feature_ablation_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/10_controlled_feature_ablation_report.md) | **Controlled Feature Ablation for BEI Dual-Mode Stock Signals:** 30-feature, 7-family inventory with 3-fold expanding walk-forward splits, 10-day purge, and leave-one-group-out benchmarking. | `PASS` | Identified dual-mode regime asymmetry; created ablation engine in `python/experiments/ablation.py`. |
| **Phase 10**<br>`2026-10-15` | [docs/09_outcome_tracking_backfill_and_integrity_audit_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/09_outcome_tracking_backfill_and_integrity_audit_report.md) | **Outcome Tracking Backfill & Integrity Audit:** Backfilled historical signal outcomes, resolved maturity status, validated TP/SL barrier logic. | `PASS` | 31 historical signals evaluated; outcome tracking pipeline validated. |
| **Phase 8**<br>`2026-10-14` | [docs/08_daily_production_signal_engine_deployment_audit_report.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/08_daily_production_signal_engine_deployment_audit_report.md) | **Daily Production Signal Engine Deployment:** Deployment of end-to-end signal generation pipeline, EV hurdle gate, and composite scoring. | `PASS` | Production engine active in `python/signals/engine.py`. |
| **Phase 6**<br>`2026-10-13` | [docs/06_dual_mode_BEI_stock_signal_agent_guide.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/06_dual_mode_BEI_stock_signal_agent_guide.md) | **Dual-Mode BEI Stock Signal System Architecture:** System design for bifurcated price regimes ($\le 300$ vs $> 300$). | `REFERENCE` | Core architectural blueprint for dual-mode models and fractional tick sizes. |
| **Phase 4**<br>`2026-10-12` | [docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md](file:///C:/Users/DROSE250122/Documents/Personal/indonesian-stock-ai/docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md) | **Platform Development Guide:** Developer reference for schema, test standards, and causal walk-forward guidelines. | `REFERENCE` | Foundational engineering guidelines. |

---

## 3. Key Repositories & Verification Commands

- **Unit Test Suite:**
  ```powershell
  & ".venv\Scripts\python.exe" -m pytest tests/unit/test_ablation.py
  ```
- **Code Linter:**
  ```powershell
  & ".venv\Scripts\python.exe" -m ruff check python/ experiments/ scripts/ tests/
  ```
- **Rerun Metric Validation & Feature Ablation:**
  ```powershell
  $env:PYTHONPATH="."
  & ".venv\Scripts\python.exe" -m scripts.run_feature_ablation --mode BOTH
  ```
