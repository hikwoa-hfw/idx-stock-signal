from datetime import date, timedelta
from pathlib import Path

from python.backtest.engine import BacktestEngine
from python.common.types import (
    BacktestConfig,
    DailyBar,
    SignalConfig,
)
from python.journal.repository import PositionJournalRepository
from python.journal.service import PositionJournalService
from python.models.baseline import LogisticRegressionBaseline
from python.models.registry import ModelMetadata, ModelRegistry
from python.outcomes.engine import OutcomeEngine
from python.outcomes.repository import OutcomeRepository
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository


def test_dual_mode_pipeline_end_to_end(tmp_path: Path):
    db_file = tmp_path / "dual_mode_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    sig_repo = SignalRepository(db_url)
    out_repo = OutcomeRepository(db_url)
    pos_repo = PositionJournalRepository(db_url)

    # 1. Prepare registry with separate champions
    reg_dir = tmp_path / "models"
    registry = ModelRegistry(registry_dir=reg_dir)

    clf_low = LogisticRegressionBaseline()
    clf_low.fit([[0.01], [-0.01]], [1, 0], feature_names=["return_1d"])
    meta_low = ModelMetadata(
        model_version="champ_low_v1",
        algorithm="logistic",
        task="classification",
        mode="LOW_PRICE",
        status="champion",
        training_start="2026-08-01",
        training_end="2026-08-15",
        feature_names=["return_1d"],
    )
    registry.save_model(clf_low, meta_low)

    clf_high = LogisticRegressionBaseline()
    clf_high.fit([[0.02], [-0.02]], [1, 0], feature_names=["return_1d"])
    meta_high = ModelMetadata(
        model_version="champ_high_v1",
        algorithm="logistic",
        task="classification",
        mode="HIGHER_PRICE",
        status="champion",
        training_start="2026-08-01",
        training_end="2026-08-15",
        feature_names=["return_1d"],
    )
    registry.save_model(clf_high, meta_high)

    # 2. Build bars for a LOW_PRICE stock (GOTO: ~80 IDR) and HIGHER_PRICE stock (BBCA: ~10,000 IDR)
    start_d = date(2026, 8, 1)
    bars_by_ticker = {"GOTO": [], "BBCA": []}

    for i in range(30):
        d = start_d + timedelta(days=i)
        # GOTO: 80 + slight upward drift
        p_goto = 80.0 + i * 0.5
        bars_by_ticker["GOTO"].append(
            DailyBar(
                ticker="GOTO",
                date=d,
                open=p_goto,
                high=p_goto + 2.0,
                low=p_goto - 1.0,
                close=p_goto + 1.0,
                volume=10_000_000.0,
                provider="test",
            )
        )
        # BBCA: 10000 + upward drift
        p_bbca = 10000.0 + i * 50.0
        bars_by_ticker["BBCA"].append(
            DailyBar(
                ticker="BBCA",
                date=d,
                open=p_bbca,
                high=p_bbca + 100.0,
                low=p_bbca - 50.0,
                close=p_bbca + 50.0,
                volume=5_000_000.0,
                provider="test",
            )
        )

    # 3. Generate Dual-Mode Signals
    sig_engine = SignalEngine(
        model_registry=registry,
        config=SignalConfig(min_probability=0.40, top_n=5),
    )

    dual_signals = sig_engine.generate_dual_mode_signals(
        signal_date=bars_by_ticker["GOTO"][-1].date,
        universe=["GOTO", "BBCA"],
        bars_by_ticker=bars_by_ticker,
        use_champion=True,
    )

    assert "LOW_PRICE" in dual_signals
    assert "HIGHER_PRICE" in dual_signals

    low_sigs = dual_signals["LOW_PRICE"]
    high_sigs = dual_signals["HIGHER_PRICE"]

    assert any(s.ticker == "GOTO" and s.mode_id == "LOW_PRICE" for s in low_sigs)
    assert any(s.ticker == "BBCA" and s.mode_id == "HIGHER_PRICE" for s in high_sigs)

    # Save to SQLite SignalRepository
    all_sigs = low_sigs + high_sigs
    saved_cnt = sig_repo.save_signals(all_sigs)
    assert saved_cnt == len(all_sigs)

    # Verify query by mode from DB
    db_low_sigs = sig_repo.get_signals(mode="LOW_PRICE")
    db_high_sigs = sig_repo.get_signals(mode="HIGHER_PRICE")
    assert all(s.mode_id == "LOW_PRICE" for s in db_low_sigs)
    assert all(s.mode_id == "HIGHER_PRICE" for s in db_high_sigs)

    # 4. Evaluate Outcomes with OutcomeEngine
    out_engine = OutcomeEngine(outcome_repo=out_repo, signal_repo=sig_repo)
    for sig in all_sigs:
        # Create mock forward bars
        forward_bars = [
            DailyBar(
                ticker=sig.ticker,
                date=sig.signal_date + timedelta(days=1),
                open=sig.entry_high,
                high=sig.tp_price + 1.0,
                low=sig.entry_low - 1.0,
                close=sig.tp_price,
                volume=1_000_000.0,
                provider="test",
            )
        ]
        outcome_rec, _ = out_engine.evaluate_signal(sig, forward_bars)
        assert outcome_rec is not None
        assert outcome_rec.mode_id == sig.mode_id
        out_repo.save_outcome(outcome_rec)

    # Verify querying matured outcomes by mode from DB
    low_outcomes = out_repo.get_matured_outcomes(mode="LOW_PRICE")
    high_outcomes = out_repo.get_matured_outcomes(mode="HIGHER_PRICE")
    assert all(o.mode_id == "LOW_PRICE" for o in low_outcomes)
    assert all(o.mode_id == "HIGHER_PRICE" for o in high_outcomes)

    # 5. Position Journal: open position inherits mode
    journal = PositionJournalService(repo=pos_repo)
    pos_low = journal.open_position(
        ticker="GOTO",
        entry_price=85.0,
        quantity=5000,
        signal_id=low_sigs[0].signal_id,
    )
    assert pos_low.mode_id == "LOW_PRICE"

    pos_high = journal.open_position(
        ticker="BBCA",
        entry_price=10200.0,
        quantity=100,
        signal_id=high_sigs[0].signal_id,
    )
    assert pos_high.mode_id == "HIGHER_PRICE"

    # Verify loaded from repo
    loaded_low = pos_repo.get_position_by_id(pos_low.position_id)
    assert loaded_low is not None and loaded_low.mode_id == "LOW_PRICE"

    # 6. Backtest Simulation with mode filtering
    bt_engine = BacktestEngine(BacktestConfig(initial_capital=50_000_000.0))
    all_bars = bars_by_ticker["GOTO"] + bars_by_ticker["BBCA"]

    # Run backtest only for LOW_PRICE mode
    report_low = bt_engine.run(bars=all_bars, model=clf_low, mode="LOW_PRICE")
    assert all(t.mode_id == "LOW_PRICE" for t in report_low.trades)

    # Run backtest only for HIGHER_PRICE mode
    report_high = bt_engine.run(bars=all_bars, model=clf_high, mode="HIGHER_PRICE")
    assert all(t.mode_id == "HIGHER_PRICE" for t in report_high.trades)
