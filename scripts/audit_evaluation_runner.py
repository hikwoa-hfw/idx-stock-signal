import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from python.backtest.engine import BacktestEngine
from python.common.types import (
    BacktestConfig,
    DailyBar,
    FeatureRecord,
    SignalConfig,
)
from python.config.settings import settings
from python.data.repository import DailyBarRepository
from python.features.repository import FeatureRepository
from python.labels.repository import LabelRepository
from python.models.baseline import RidgeRegressionBaseline
from python.models.dataset import DatasetBuilder
from python.models.metrics import (
    evaluate_classification,
    evaluate_regression,
)
from python.models.registry import ModelRegistry
from python.models.validation import split_chronological
from python.signals.engine import SignalEngine


def run_evaluation() -> dict[str, Any]:
    print("=" * 80)
    print("       AUDIT REMEDIATION EVALUATION & WALK-FORWARD BACKTEST RUNNER")
    print("=" * 80)

    db_url = settings.database_url
    feat_repo = FeatureRepository(db_url)
    lbl_repo = LabelRepository(db_url)
    bar_repo = DailyBarRepository(db_url)
    registry = ModelRegistry()

    # Champions
    champ_low_ver = "lightgbm_classification_20261014_093522"
    champ_high_ver = "lightgbm_classification_20261014_093607"

    # Candidates (latest challenger in registry)
    low_challengers = [
        m for m in registry.list_models(task="classification", mode="LOW_PRICE")
        if m.status.lower() == "challenger"
    ]
    high_challengers = [
        m for m in registry.list_models(task="classification", mode="HIGHER_PRICE")
        if m.status.lower() == "challenger"
    ]
    low_regs = [
        m for m in registry.list_models(task="regression", mode="LOW_PRICE")
        if m.status.lower() == "challenger"
    ]
    high_regs = [
        m for m in registry.list_models(task="regression", mode="HIGHER_PRICE")
        if m.status.lower() == "challenger"
    ]

    cand_low_clf_ver = low_challengers[0].model_version if low_challengers else None
    cand_high_clf_ver = high_challengers[0].model_version if high_challengers else None
    cand_low_reg_ver = low_regs[0].model_version if low_regs else None
    cand_high_reg_ver = high_regs[0].model_version if high_regs else None

    print(f"LOW_PRICE Champion:     {champ_low_ver}")
    print(f"LOW_PRICE Candidate:    {cand_low_clf_ver}")
    print(f"LOW_PRICE Regressor:    {cand_low_reg_ver}")
    print(f"HIGHER_PRICE Champion:  {champ_high_ver}")
    print(f"HIGHER_PRICE Candidate: {cand_high_clf_ver}")
    print(f"HIGHER_PRICE Regressor: {cand_high_reg_ver}")
    print()

    results: dict[str, Any] = {
        "evaluation_date": str(date.today()),
        "test_period": {"start": "2026-03-26", "end": "2026-10-13"},
        "modes": {},
    }

    # Gather test bars for backtesting
    all_universe = bar_repo.get_universe()
    all_bars_map: dict[str, list[DailyBar]] = {}
    for t in all_universe:
        bars = bar_repo.get_daily_bars(t)
        if bars:
            all_bars_map[t] = bars

    for mode in ["LOW_PRICE", "HIGHER_PRICE"]:
        print(f"\n{'='*35} MODE: {mode} {'='*35}")
        builder = DatasetBuilder(mode=mode)
        ds = builder.build_from_db(feat_repo, lbl_repo, mode=mode)
        train_idx, val_idx, test_idx = split_chronological(
            ds.dates, 0.70, 0.15, 0.15, purge_days=10
        )
        train_ds = ds.select_indices(train_idx)
        val_ds = ds.select_indices(val_idx)
        test_ds = ds.select_indices(test_idx)

        print(
            f"Total rows: {len(ds)} | Train: {len(train_ds)} | "
            f"Val: {len(val_ds)} | Test: {len(test_ds)}"
        )
        print(f"Test dates: {min(test_ds.dates)} to {max(test_ds.dates)}")

        y_train_clf = train_ds.y
        y_test_clf = test_ds.y
        y_train_reg = train_ds.y_return
        y_test_reg = test_ds.y_return

        # -------------------------------------------------------------
        # 1. Classification Metrics
        # -------------------------------------------------------------
        # Prevalence Baseline
        base_rate = float(np.mean(y_train_clf))
        prob_prev = np.full_like(y_test_clf, base_rate, dtype=np.float64)
        m_prev = evaluate_classification(y_test_clf, prob_prev)

        # Champion
        champ_ver = champ_low_ver if mode == "LOW_PRICE" else champ_high_ver
        champ_clf, champ_meta = registry.load_model(champ_ver)
        prob_champ = champ_clf.predict_probability(test_ds.X)
        m_champ = evaluate_classification(y_test_clf, prob_champ)

        # Candidate
        cand_clf_ver = cand_low_clf_ver if mode == "LOW_PRICE" else cand_high_clf_ver
        cand_clf, cand_meta = registry.load_model(cand_clf_ver)
        prob_cand = cand_clf.predict_probability(test_ds.X)
        m_cand = evaluate_classification(y_test_clf, prob_cand)

        print(f"\n--- Classification Metrics ({mode} Test Set: {len(test_ds)} rows) ---")
        row_clf = "{:<18} {:<8.4f} {:<9.4f} {:<9.4f} {:<6.1f}% {:<8.4f}"
        p_br, p_ll = m_prev["brier_score"], m_prev["log_loss"]
        p_auc, p_acc = m_prev["roc_auc"], m_prev["accuracy"] * 100
        p_ece = m_prev["calibration_error"]
        print(row_clf.format("Prevalence Base", p_br, p_ll, p_auc, p_acc, p_ece))
        c_br, c_ll = m_champ["brier_score"], m_champ["log_loss"]
        c_auc, c_acc = m_champ["roc_auc"], m_champ["accuracy"] * 100
        c_ece = m_champ["calibration_error"]
        print(row_clf.format("Champion", c_br, c_ll, c_auc, c_acc, c_ece))
        k_br, k_ll = m_cand["brier_score"], m_cand["log_loss"]
        k_auc, k_acc = m_cand["roc_auc"], m_cand["accuracy"] * 100
        k_ece = m_cand["calibration_error"]
        print(row_clf.format("Candidate", k_br, k_ll, k_auc, k_acc, k_ece))

        # -------------------------------------------------------------
        # 2. Regression Metrics & Baseline Comparisons
        # -------------------------------------------------------------
        # Zero Baseline
        pred_zero = np.zeros_like(y_test_reg)
        m_zero = evaluate_regression(y_test_reg, pred_zero)

        # Mean Baseline
        pred_mean = np.full_like(y_test_reg, np.mean(y_train_reg))
        m_mean = evaluate_regression(y_test_reg, pred_mean)

        # Ridge Regression Baseline
        ridge = RidgeRegressionBaseline(alpha=1.0)
        ridge.fit(train_ds.X, y_train_reg, feature_names=ds.feature_names)
        pred_ridge = ridge.predict(test_ds.X)
        m_ridge = evaluate_regression(y_test_reg, pred_ridge)

        # LightGBM Regressor Candidate
        cand_reg_ver = cand_low_reg_ver if mode == "LOW_PRICE" else cand_high_reg_ver
        cand_reg, _ = registry.load_model(cand_reg_ver)
        pred_cand_reg = cand_reg.predict(test_ds.X)
        m_cand_reg = evaluate_regression(y_test_reg, pred_cand_reg)

        print(f"\n--- Regression Metrics ({mode} Test Set: {len(test_ds)} rows) ---")
        print(f"{'Model':<20} {'MSE':<10} {'RMSE':<10} {'MAE':<10} {'R2':<8}")
        z_mse, z_rmse, z_mae, z_r2 = m_zero['mse'], m_zero['rmse'], m_zero['mae'], m_zero['r2']
        print(f"{'Zero Baseline':<20} {z_mse:.6f}   {z_rmse:.6f}   {z_mae:.6f}   {z_r2:.4f}")
        mn_mse, mn_rmse = m_mean['mse'], m_mean['rmse']
        mn_mae, mn_r2 = m_mean['mae'], m_mean['r2']
        print(f"{'Mean Baseline':<20} {mn_mse:.6f}   {mn_rmse:.6f}   {mn_mae:.6f}   {mn_r2:.4f}")
        rg_mse, rg_rmse = m_ridge['mse'], m_ridge['rmse']
        rg_mae, rg_r2 = m_ridge['mae'], m_ridge['r2']
        print(f"{'Ridge Baseline':<20} {rg_mse:.6f}   {rg_rmse:.6f}   {rg_mae:.6f}   {rg_r2:.4f}")
        lg_mse, lg_rmse = m_cand_reg['mse'], m_cand_reg['rmse']
        lg_mae, lg_r2 = m_cand_reg['mae'], m_cand_reg['r2']
        print(f"{'LightGBM Reg':<20} {lg_mse:.6f}   {lg_rmse:.6f}   {lg_mae:.6f}   {lg_r2:.4f}")

        # -------------------------------------------------------------
        # 3. Walk-Forward Backtests on Test Period (2026-03-26 to 2026-10-13)
        # -------------------------------------------------------------
        # Gather all test bars
        test_dates_set = set(test_ds.dates)
        test_bars = [b for bars in all_bars_map.values() for b in bars if b.date in test_dates_set]

        # Preload features for test period to ensure instant execution and accurate feature values
        all_test_features = feat_repo.get_feature_matrix(
            start_date=min(test_dates_set),
            end_date=max(test_dates_set),
        )
        from collections import defaultdict
        feats_by_ticker: dict[str, list[FeatureRecord]] = defaultdict(list)
        for f in all_test_features:
            clean_t = f.ticker.strip().upper().removesuffix(".JK")
            feats_by_ticker[clean_t].append(f)

        backtest_cfg = BacktestConfig(
            initial_capital=100_000_000.0,
            commission_buy=0.0015,
            commission_sell=0.0025,
            slippage_bps=10.0,
            max_concurrent_positions=5,
            risk_per_trade_pct=0.02,  # 2% risk budget as tested in audit report
            lot_size=100,
            tp_pct=0.05,
            sl_pct=0.02,
            max_holding_days=10,
            entry_execution="next_open",
            ambiguity_policy="conservative",
        )
        engine_bt = BacktestEngine(config=backtest_cfg)

        # Backtest 1: Champion at threshold 0.25 (audit baseline replicate)
        cfg_champ_bt = backtest_cfg.model_copy(update={"probability_threshold": 0.25})
        rep_champ = BacktestEngine(config=cfg_champ_bt).run(
            bars=test_bars,
            model=champ_clf,
            universe_features=all_test_features,
            feature_names=ds.feature_names,
            mode=mode,
        )

        # Backtest 2: Candidate at threshold 0.25 unhurdled
        cfg_cand_unhurdled = backtest_cfg.model_copy(update={"probability_threshold": 0.25})
        rep_cand_unhurdled = BacktestEngine(config=cfg_cand_unhurdled).run(
            bars=test_bars,
            model=cand_clf,
            universe_features=all_test_features,
            feature_names=ds.feature_names,
            mode=mode,
        )

        # Backtest 3: Candidate with Mathematical EV Hurdle check (fail-closed)
        sig_cfg_ev = SignalConfig(
            min_probability=0.25,
            enforce_positive_ev=True,
            top_n=5,
            mode=mode,
        )
        sig_engine_ev = SignalEngine(config=sig_cfg_ev, model_registry=registry)

        ev_signals = []
        sorted_test_dates = sorted(list(test_dates_set))
        for d in sorted_test_dates:
            try:
                sigs = sig_engine_ev.generate_signals(
                    signal_date=d,
                    classifier=cand_clf,
                    regressor=cand_reg,
                    model_version=cand_clf_ver,
                    bars_by_ticker=all_bars_map,
                    features_by_ticker=feats_by_ticker,
                    mode=mode,
                    config=sig_cfg_ev,
                )
                from python.common.types import Signal, SignalAction
                for s in sigs:
                    ev_signals.append(
                        Signal(
                            ticker=s.ticker,
                            signal_date=s.signal_date,
                            action=SignalAction.BUY,
                            target_price=s.tp_price,
                            stop_loss=s.sl_price,
                            max_holding_days=s.max_holding_days,
                            probability=s.predicted_probability,
                            model_version=s.model_version,
                            score=s.score,
                            mode=s.mode,
                        )
                    )
            except Exception:
                pass

        rep_cand_ev = engine_bt.run(
            bars=test_bars,
            signals=ev_signals,
            mode=mode,
        )

        print(f"\n--- Walk-Forward Results ({mode} Period: 2026-03-26 to 2026-10-13) ---")
        row_fmt = "{:<20} {:<24} {:<24} {:<24}"
        print(row_fmt.format("Metric", "Champion(0.25)", "Cand-Unhurdled", "Cand-EV-Gate"))
        print("-" * 92)
        print(row_fmt.format(
            "Trades",
            rep_champ.total_trades,
            rep_cand_unhurdled.total_trades,
            rep_cand_ev.total_trades,
        ))
        print(row_fmt.format(
            "Win Rate",
            f"{rep_champ.win_rate*100:.2f}%",
            f"{rep_cand_unhurdled.win_rate*100:.2f}%",
            f"{rep_cand_ev.win_rate*100:.2f}%",
        ))
        print(row_fmt.format(
            "Profit Factor",
            f"{rep_champ.profit_factor:.2f}",
            f"{rep_cand_unhurdled.profit_factor:.2f}",
            f"{rep_cand_ev.profit_factor:.2f}",
        ))
        print(row_fmt.format(
            "Net Return",
            f"{rep_champ.total_return_pct*100:+.2f}%",
            f"{rep_cand_unhurdled.total_return_pct*100:+.2f}%",
            f"{rep_cand_ev.total_return_pct*100:+.2f}%",
        ))
        print(row_fmt.format(
            "Max Drawdown",
            f"{rep_champ.max_drawdown_pct*100:.2f}%",
            f"{rep_cand_unhurdled.max_drawdown_pct*100:.2f}%",
            f"{rep_cand_ev.max_drawdown_pct*100:.2f}%",
        ))
        print(row_fmt.format(
            "Expectancy",
            f"{rep_champ.expectancy_pct*100:+.2f}%",
            f"{rep_cand_unhurdled.expectancy_pct*100:+.2f}%",
            f"{rep_cand_ev.expectancy_pct*100:+.2f}%",
        ))
        print(row_fmt.format(
            "TP Rate",
            f"{rep_champ.tp_rate*100:.1f}%",
            f"{rep_cand_unhurdled.tp_rate*100:.1f}%",
            f"{rep_cand_ev.tp_rate*100:.1f}%",
        ))
        print(row_fmt.format(
            "SL Rate",
            f"{rep_champ.sl_rate*100:.1f}%",
            f"{rep_cand_unhurdled.sl_rate*100:.1f}%",
            f"{rep_cand_ev.sl_rate*100:.1f}%",
        ))
        print(row_fmt.format(
            "Expiry Rate",
            f"{rep_champ.expiry_rate*100:.1f}%",
            f"{rep_cand_unhurdled.expiry_rate*100:.1f}%",
            f"{rep_cand_ev.expiry_rate*100:.1f}%",
        ))

        # Store mode summary
        results["modes"][mode] = {
            "sample_counts": {
                "total": len(ds),
                "train": len(train_ds),
                "val": len(val_ds),
                "test": len(test_ds),
            },
            "champion": {
                "version": champ_ver,
                "classification": m_champ,
                "backtest": rep_champ.model_dump(exclude={"trades", "equity_curve"}),
            },
            "candidate_classifier": {
                "version": cand_clf_ver,
                "classification": m_cand,
                "backtest_unhurdled": rep_cand_unhurdled.model_dump(
                    exclude={"trades", "equity_curve"}
                ),
                "backtest_ev_hurdle": rep_cand_ev.model_dump(
                    exclude={"trades", "equity_curve"}
                ),
            },
            "candidate_regressor": {
                "version": cand_reg_ver,
                "regression": m_cand_reg,
            },
            "baselines": {
                "classification_prevalence": m_prev,
                "regression_zero": m_zero,
                "regression_mean": m_mean,
                "regression_ridge": m_ridge,
            },
        }

    # Save to JSON artifact
    out_path = Path("docs/audit_remediation_evaluation_results.json")
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved reproducible evaluation results to: {out_path}")
    return results


if __name__ == "__main__":
    run_evaluation()
