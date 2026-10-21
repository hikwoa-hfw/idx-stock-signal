from datetime import date, datetime, timezone

import pytest

from python.common.types import (
    AmbiguityPolicy,
    CalibrationBin,
    ComparisonRecommendation,
    ComparisonReport,
    DailyBar,
    EvaluationReport,
    FeatureRecord,
    IngestionRun,
    IngestionTickerStatus,
    LabelOutcome,
    LabelRecord,
    ModelVersion,
    Outcome,
    OutcomeStatus,
    Position,
    Prediction,
    PredictionMetrics,
    Signal,
    SignalAction,
    SignalDailySnapshot,
    SignalOutcomeRecord,
    TradingMetrics,
)
from python.config.settings import settings


def test_settings_load_defaults():
    assert settings.app_env in ["development", "production", "test"]
    assert settings.market_data_provider != ""


def test_signal_model_validation():
    signal = Signal(
        ticker="BBCA.JK",
        signal_date=date(2026, 10, 12),
        action=SignalAction.BUY,
        entry_price=10000.0,
        target_price=10500.0,
        stop_loss=9800.0,
        probability=0.72,
        model_version="v1.0.0",
    )
    assert signal.ticker == "BBCA.JK"
    assert signal.action == SignalAction.BUY
    assert signal.target_price > signal.entry_price
    assert signal.max_holding_days == 10


def test_position_model_validation():
    pos = Position(
        position_id="pos-001",
        ticker="BBRI.JK",
        entry_date=date(2026, 10, 12),
        entry_price=5000.0,
        quantity=10,
        target_price=5300.0,
        stop_loss=4850.0,
        is_open=True,
    )
    assert pos.is_open is True
    assert pos.quantity == 10


def test_prediction_model_validation():
    pred = Prediction(
        ticker="TLKM.JK",
        prediction_date=date(2026, 10, 12),
        model_version="lgbm_v1.0",
        probability=0.68,
        expected_return=0.045,
    )
    assert pred.ticker == "TLKM.JK"
    assert pred.probability == 0.68
    assert pred.created_at is not None
    assert pred.created_at.tzinfo is not None


def test_outcome_model_validation():
    outcome = Outcome(
        ticker="BBCA.JK",
        signal_date=date(2026, 10, 1),
        status=OutcomeStatus.TP_HIT,
        realized_return=0.052,
        holding_days=4,
    )
    assert outcome.status == OutcomeStatus.TP_HIT
    assert outcome.realized_return == 0.052
    assert outcome.holding_days == 4
    assert outcome.evaluated_at.tzinfo is not None


def test_model_version_validation():
    mv = ModelVersion(
        version="v1.0.0",
        model_type="lightgbm_classifier",
        trained_at=datetime.now(timezone.utc),
        metrics={"roc_auc": 0.65, "precision_at_k": 0.70},
        is_champion=True,
    )
    assert mv.is_champion is True
    assert mv.metrics["roc_auc"] == 0.65


def test_daily_bar_model_validation():
    bar = DailyBar(
        ticker="BBCA.JK",
        date=date(2026, 10, 12),
        open=10200.0,
        high=10300.0,
        low=10150.0,
        close=10250.0,
        volume=1500000.0,
        value=15375000000.0,
    )
    assert bar.ticker == "BBCA.JK"
    assert bar.open == 10200.0
    assert bar.high >= bar.open
    assert bar.low <= bar.close
    assert bar.volume == 1500000.0


def test_feature_record_model_validation():
    rec = FeatureRecord(
        ticker="  bbca.jk  ",
        date=date(2026, 10, 12),
        feature_version="v1.0.0",
        return_1d=0.012,
        ema20=10200.0,
        rsi14=55.0,
        market_breadth=0.6,
    )
    assert rec.ticker == "BBCA"
    assert rec.feature_version == "v1.0.0"
    assert rec.return_1d == 0.012
    assert rec.ema20 == 10200.0
    assert rec.market_breadth == 0.6


def test_label_record_model_validation():
    rec = LabelRecord(
        ticker="  bbca.jk  ",
        date=date(2026, 10, 12),
        label_version="v1.0.0",
        entry_price=10000.0,
        tp_price=10500.0,
        sl_price=9800.0,
        tp_pct=0.05,
        sl_pct=0.02,
        max_holding_days=10,
        outcome=LabelOutcome.TP.value,
        binary_target=1,
        mfe=0.06,
        mae=-0.01,
        holding_days=3,
        realized_return=0.05,
        exit_date=date(2026, 10, 15),
        exit_price=10500.0,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE.value,
    )
    assert rec.ticker == "BBCA"
    assert rec.target == 1
    assert rec.binary_target == 1
    assert rec.outcome == "TP"
    assert rec.created_at is not None


def test_label_record_validation_errors():
    base_kwargs = dict(
        ticker="BBCA",
        date=date(2026, 10, 12),
        entry_price=10000.0,
        tp_price=10500.0,
        sl_price=9800.0,
        tp_pct=0.05,
        sl_pct=0.02,
        outcome="TP",
        binary_target=1,
    )

    # Invalid outcome
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "outcome": "INVALID"})

    # Invalid policy
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "ambiguity_policy": "invalid_policy"})

    # Invalid binary target
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "binary_target": 2})

    # Negative price
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "entry_price": -100.0})

    # Non-finite price
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "entry_price": float("nan")})

    # Non-finite metric
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "mfe": float("inf")})

    # Negative holding days
    with pytest.raises(ValueError):
        LabelRecord(**{**base_kwargs, "holding_days": -1})


def test_backtest_domain_types():
    from python.common.types import (
        BacktestConfig,
        BacktestReport,
        EquityPoint,
        TradeRecord,
    )

    cfg = BacktestConfig(
        initial_capital=50_000_000.0,
        commission_buy=0.0015,
        commission_sell=0.0025,
        slippage_bps=10.0,
        max_concurrent_positions=3,
    )
    assert cfg.initial_capital == 50_000_000.0
    assert cfg.max_concurrent_positions == 3

    trade = TradeRecord(
        trade_id="TR-001",
        ticker="BBCA.JK",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        exit_date=date(2026, 1, 5),
        shares=1000,
        entry_price=1000.0,
        exit_price=1050.0,
        position_value=1_000_000.0,
        entry_fee=1500.0,
        exit_fee=2625.0,
        slippage_cost=1000.0,
        gross_pnl=50_000.0,
        net_pnl=44_875.0,
        net_return=0.0448,
        exit_reason="TP",
        holding_days=3,
        mfe=0.06,
        mae=-0.01,
    )
    assert trade.ticker == "BBCA"
    assert trade.net_pnl == 44_875.0

    eq_pt = EquityPoint(
        date=date(2026, 1, 2),
        cash=49_000_000.0,
        positions_value=1_000_000.0,
        total_equity=50_000_000.0,
        drawdown_pct=0.0,
        open_positions_count=1,
    )
    assert eq_pt.total_equity == 50_000_000.0

    report = BacktestReport(
        config=cfg,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
        initial_capital=50_000_000.0,
        final_equity=50_044_875.0,
        total_net_pnl=44_875.0,
        total_return_pct=0.0008975,
        total_trades=1,
        winning_trades=1,
        losing_trades=0,
        win_rate=1.0,
        average_win_pct=0.0448,
        average_loss_pct=0.0,
        win_loss_ratio=float("inf"),
        profit_factor=float("inf"),
        expectancy_pct=0.0448,
        max_drawdown_pct=0.0,
        max_drawdown_amount=0.0,
        average_holding_days=3.0,
        tp_rate=1.0,
        sl_rate=0.0,
        expiry_rate=0.0,
        trades=[trade],
        equity_curve=[eq_pt],
    )
    assert report.total_trades == 1
    assert len(report.trades) == 1
    assert len(report.equity_curve) == 1


def test_backtest_domain_types_validation_errors():
    from python.common.types import BacktestConfig, EquityPoint, TradeRecord

    # Invalid entry_execution
    with pytest.raises(ValueError, match="entry_execution"):
        BacktestConfig(entry_execution="yolo")

    base_trade = dict(
        trade_id="TR-ERR",
        ticker="BBCA",
        signal_date=date(2026, 1, 1),
        entry_date=date(2026, 1, 2),
        exit_date=date(2026, 1, 5),
        shares=100,
        entry_price=1000.0,
        exit_price=1050.0,
        position_value=100_000.0,
        entry_fee=150.0,
        exit_fee=250.0,
        slippage_cost=10.0,
        gross_pnl=5000.0,
        net_pnl=4590.0,
        net_return=0.0459,
        exit_reason="TP",
        holding_days=3,
    )

    # Negative holding days
    with pytest.raises(ValueError, match="holding_days"):
        TradeRecord(**{**base_trade, "holding_days": -1})

    # Invalid signal probability
    with pytest.raises(ValueError, match="signal_probability"):
        TradeRecord(**{**base_trade, "signal_probability": 1.5})

    # Negative open_positions_count
    with pytest.raises(ValueError, match="open_positions_count"):
        EquityPoint(
            date=date(2026, 1, 2),
            cash=100.0,
            positions_value=0.0,
            total_equity=100.0,
            open_positions_count=-1,
        )

    # Negative drawdown_pct
    with pytest.raises(ValueError, match="drawdown_pct"):
        EquityPoint(
            date=date(2026, 1, 2),
            cash=100.0,
            positions_value=0.0,
            total_equity=100.0,
            drawdown_pct=-0.1,
        )


def test_daily_bar_corporate_actions_and_raw_aliases():
    # Instantiation using canonical raw field names
    bar = DailyBar(
        ticker="BBCA.JK",
        trading_date=date(2026, 10, 1),
        open_raw=10000.0,
        high_raw=10200.0,
        low_raw=9900.0,
        close_raw=10100.0,
        volume_raw=500000.0,
        adj_close_provider=9800.0,
        dividends=150.0,
        stock_splits=2.0,
        provider="yfinance",
    )
    assert bar.date == date(2026, 10, 1)
    assert bar.open == 10000.0
    assert bar.high == 10200.0
    assert bar.low == 9900.0
    assert bar.close == 10100.0
    assert bar.volume == 500000.0
    assert bar.adj_close == 9800.0
    assert bar.dividends == 150.0
    assert bar.stock_splits == 2.0
    assert bar.interval == "1d"
    assert bar.provider == "yfinance"

    # Properties
    assert bar.trading_date == date(2026, 10, 1)
    assert bar.open_raw == 10000.0
    assert bar.high_raw == 10200.0
    assert bar.low_raw == 9900.0
    assert bar.close_raw == 10100.0
    assert bar.volume_raw == 500000.0
    assert bar.adj_close_provider == 9800.0


def test_ingestion_audit_types():
    run = IngestionRun(
        id="run-123",
        provider="yfinance",
        job_type="incremental",
        started_at=datetime.now(timezone.utc),
        status="SUCCESS",
        tickers_requested=5,
        tickers_succeeded=5,
        rows_inserted=20,
    )
    assert run.id == "run-123"
    assert run.job_type == "incremental"
    assert run.tickers_requested == 5

    status = IngestionTickerStatus(
        id="run-123_BBCA",
        ingestion_run_id="run-123",
        ticker="BBCA",
        status="SUCCESS",
        rows_received=10,
        rows_inserted=10,
        first_date_received=date(2026, 10, 1),
        last_date_received=date(2026, 10, 10),
    )
    assert status.ticker == "BBCA"
    assert status.status == "SUCCESS"
    assert status.first_date_received == date(2026, 10, 1)


def test_daily_bar_row_hash():
    b1 = DailyBar(
        ticker="BBCA.JK",
        date=date(2026, 10, 1),
        open=10000.0,
        high=10200.0,
        low=9900.0,
        close=10100.0,
        volume=500000.0,
        dividends=0.0,
        stock_splits=0.0,
        provider="yfinance",
    )
    b2 = DailyBar(
        ticker="BBCA",
        date=date(2026, 10, 1),
        open=10000.0,
        high=10200.0,
        low=9900.0,
        close=10100.0,
        volume=500000.0,
        dividends=0.0,
        stock_splits=0.0,
        provider="yfinance",
    )
    assert b1.row_hash is not None
    assert b1.row_hash == b2.row_hash

    # Modify corporate action field -> row_hash must change
    b3 = DailyBar(
        ticker="BBCA",
        date=date(2026, 10, 1),
        open=10000.0,
        high=10200.0,
        low=9900.0,
        close=10100.0,
        volume=500000.0,
        dividends=150.0,
        stock_splits=0.0,
        provider="yfinance",
    )
    assert b3.row_hash != b1.row_hash


def test_signal_config_validation():
    from python.common.types import SignalConfig

    cfg = SignalConfig()
    assert cfg.min_probability == 0.55
    assert cfg.tp_pct == 0.05
    assert cfg.sl_pct == 0.02
    assert cfg.max_holding_days == 10
    assert cfg.top_n == 5
    assert "probability" in cfg.weights

    # Invalid probability
    with pytest.raises(ValueError, match="min_probability"):
        SignalConfig(min_probability=1.2)

    with pytest.raises(ValueError, match="min_probability"):
        SignalConfig(min_probability=-0.1)

    # Invalid tp_pct
    with pytest.raises(ValueError, match="Percentage parameter"):
        SignalConfig(tp_pct=0.0)

    # Invalid max_holding_days
    with pytest.raises(ValueError, match="Value must be >= 1"):
        SignalConfig(max_holding_days=0)

    # Empty weights
    with pytest.raises(ValueError, match="weights dict cannot be empty"):
        SignalConfig(weights={})

    # All zero weights
    with pytest.raises(ValueError, match="greater than 0"):
        SignalConfig(weights={"probability": 0.0, "return": 0.0})


def test_signal_record_validation():
    from python.common.types import SignalRecord

    sig = SignalRecord(
        signal_id="sig-uuid-123",
        ticker="  bbca.jk  ",
        signal_date=date(2026, 10, 12),
        signal="buy",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10605.0,
        sl_price=9800.0,
        max_holding_days=10,
        predicted_probability=0.75,
        expected_return=0.045,
        score=82.5,
        model_version="lgbm_champ_v1",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot={"rsi14": 55.0, "volume_ratio_20d": 1.2},
    )
    assert sig.ticker == "BBCA"
    assert sig.signal == "BUY"
    assert sig.entry_low == 10000.0
    assert sig.entry_high == 10100.0
    assert sig.tp_price == 10605.0
    assert sig.sl_price == 9800.0
    assert sig.predicted_probability == 0.75
    assert sig.score == 82.5
    assert sig.created_at is not None


def test_signal_record_validation_errors():
    from python.common.types import SignalRecord

    base_sig = dict(
        signal_id="sig-001",
        ticker="BBCA",
        signal_date=date(2026, 10, 12),
        signal="BUY",
        entry_low=10000.0,
        entry_high=10100.0,
        tp_price=10500.0,
        sl_price=9800.0,
        max_holding_days=10,
        predicted_probability=0.65,
        score=75.0,
        model_version="v1",
    )

    # Inverted entry band (entry_low > entry_high)
    with pytest.raises(ValueError, match="entry_low"):
        SignalRecord(**{**base_sig, "entry_low": 10200.0, "entry_high": 10100.0})

    # TP price below entry_high
    with pytest.raises(ValueError, match="tp_price"):
        SignalRecord(**{**base_sig, "tp_price": 10050.0})

    # SL price above entry_low
    with pytest.raises(ValueError, match="sl_price"):
        SignalRecord(**{**base_sig, "sl_price": 10050.0})

    # Invalid probability
    with pytest.raises(ValueError, match="predicted_probability"):
        SignalRecord(**{**base_sig, "predicted_probability": 1.5})

    # Invalid score
    with pytest.raises(ValueError, match="score"):
        SignalRecord(**{**base_sig, "score": 105.0})


def test_position_record_types():
    from python.common.types import PositionRecord

    pos = PositionRecord(
        ticker="bbri.jk",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=5100.0,
        quantity=500,
        signal_id="sig-ref-01",
        notes="Opening trade",
    )
    assert pos.ticker == "BBRI"
    assert pos.status == "OPEN"
    assert pos.actual_entry_price == 5100.0
    assert pos.quantity == 500
    assert pos.signal_id == "sig-ref-01"
    assert pos.notes == "Opening trade"
    assert pos.position_id is not None
    assert pos.created_at is not None
    assert pos.updated_at is not None

    # Empty signal_id stripped to None
    pos_no_sig = PositionRecord(
        ticker="BBCA",
        actual_entry_date=date(2026, 10, 1),
        actual_entry_price=10000.0,
        quantity=100,
        signal_id="  ",
    )
    assert pos_no_sig.signal_id is None

    # Invalid status on creation raises ValidationError
    with pytest.raises(ValueError, match="status must be one of"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="INVALID",
        )

    # CANCELLED position rejects exit_price
    with pytest.raises(ValueError, match="Cancelled position cannot have actual_exit_price"):
        PositionRecord(
            ticker="BBCA",
            actual_entry_date=date(2026, 10, 1),
            actual_entry_price=10000.0,
            quantity=100,
            status="CANCELLED",
            actual_exit_price=10500.0,
        )


def test_signal_outcome_record_validation():
    # Valid OPEN record
    rec = SignalOutcomeRecord(
        signal_id="sig_001",
        ticker="bbca.jk",
        signal_date=date(2026, 10, 1),
        entry_date=date(2026, 10, 2),
        entry_price=10000.0,
        outcome_status="OPEN",
        holding_days=2,
    )
    assert rec.ticker == "BBCA"
    assert rec.outcome_status == "OPEN"
    assert rec.exit_price is None
    assert rec.exit_date is None
    assert rec.realized_return is None

    # Valid TP resolved record
    resolved = SignalOutcomeRecord(
        signal_id="sig_002",
        ticker="BBRI",
        signal_date=date(2026, 10, 1),
        entry_date=date(2026, 10, 2),
        entry_price=5000.0,
        outcome_status="TP",
        exit_date=date(2026, 10, 5),
        exit_price=5250.0,
        holding_days=3,
    )
    assert resolved.outcome_status == "TP"
    assert resolved.exit_reason == "TP"
    assert resolved.realized_return == pytest.approx(0.05)
    assert resolved.resolved_at is not None

    # Invalid exit_price on OPEN record
    with pytest.raises(ValueError, match="Open outcome cannot have exit_price"):
        SignalOutcomeRecord(
            signal_id="sig_003",
            ticker="BBCA",
            signal_date=date(2026, 10, 1),
            entry_date=date(2026, 10, 2),
            entry_price=10000.0,
            outcome_status="OPEN",
            exit_price=10500.0,
        )

    # Missing exit_date on resolved record
    with pytest.raises(ValueError, match="must specify exit_date"):
        SignalOutcomeRecord(
            signal_id="sig_004",
            ticker="BBCA",
            signal_date=date(2026, 10, 1),
            entry_date=date(2026, 10, 2),
            entry_price=10000.0,
            outcome_status="TP",
            exit_price=10500.0,
        )

    # Exit date preceding entry date
    with pytest.raises(ValueError, match="cannot precede entry_date"):
        SignalOutcomeRecord(
            signal_id="sig_005",
            ticker="BBCA",
            signal_date=date(2026, 10, 5),
            entry_date=date(2026, 10, 6),
            entry_price=10000.0,
            outcome_status="SL",
            exit_date=date(2026, 10, 4),
            exit_price=9800.0,
        )

    # Entry date preceding signal date (causality violation)
    with pytest.raises(ValueError, match="cannot precede signal_date"):
        SignalOutcomeRecord(
            signal_id="sig_006",
            ticker="BBCA",
            signal_date=date(2026, 10, 5),
            entry_date=date(2026, 10, 4),
            entry_price=10000.0,
            outcome_status="OPEN",
        )

    # Open outcome cannot have realized_return
    with pytest.raises(ValueError, match="Open outcome cannot have realized_return"):
        SignalOutcomeRecord(
            signal_id="sig_007",
            ticker="BBCA",
            signal_date=date(2026, 10, 1),
            entry_date=date(2026, 10, 2),
            entry_price=10000.0,
            outcome_status="OPEN",
            realized_return=0.05,
        )


def test_signal_daily_snapshot_validation():
    snap = SignalDailySnapshot(
        signal_id="sig_001",
        snapshot_date=date(2026, 10, 2),
        holding_day=1,
        close_price=10100.0,
        return_from_entry=0.01,
        high_price=10200.0,
        low_price=9950.0,
        mfe_so_far=0.02,
        mae_so_far=-0.005,
    )
    assert snap.holding_day == 1
    assert snap.close_price == 10100.0
    assert snap.mfe_so_far == 0.02

    with pytest.raises(ValueError, match="Price must be positive"):
        SignalDailySnapshot(
            signal_id="sig_001",
            snapshot_date=date(2026, 10, 2),
            holding_day=1,
            close_price=-100.0,
            return_from_entry=0.0,
            high_price=100.0,
            low_price=90.0,
            mfe_so_far=0.0,
            mae_so_far=0.0,
        )

    with pytest.raises(ValueError, match="cannot be less than low_price"):
        SignalDailySnapshot(
            signal_id="sig_001",
            snapshot_date=date(2026, 10, 2),
            holding_day=1,
            close_price=100.0,
            return_from_entry=0.0,
            high_price=90.0,
            low_price=110.0,
            mfe_so_far=0.0,
            mae_so_far=0.0,
        )


def test_evaluation_report_validation():
    t_m = TradingMetrics(
        win_rate=0.60,
        profit_factor=1.85,
        expectancy=0.025,
        max_drawdown=0.08,
        sharpe=1.65,
        avg_win=0.05,
        avg_loss=-0.02,
        total_trades=100,
        tp_rate=0.55,
        sl_rate=0.35,
        expiry_rate=0.10,
    )
    p_m = PredictionMetrics(
        brier_score=0.175,
        log_loss=0.512,
        roc_auc=0.68,
        ece=0.032,
        accuracy=0.62,
    )
    c_bin = CalibrationBin(
        bin_index=1,
        lower_bound=0.0,
        upper_bound=0.1,
        sample_count=10,
        mean_predicted=0.05,
        observed_frequency=0.04,
        gap=0.01,
    )

    report = EvaluationReport(
        model_version="challenger_v2",
        sample_size=100,
        trading_metrics=t_m,
        prediction_metrics=p_m,
        calibration_bins=[c_bin],
        status="evaluated",
    )
    assert report.model_version == "challenger_v2"
    assert report.trading_metrics.profit_factor == 1.85
    assert report.prediction_metrics.brier_score == 0.175
    assert len(report.calibration_bins) == 1

    d = report.to_dict()
    assert d["model_version"] == "challenger_v2"
    assert d["trading_metrics"]["profit_factor"] == 1.85


def test_comparison_report_validation():
    champ = EvaluationReport(
        model_version="champ_v1",
        sample_size=100,
        trading_metrics=TradingMetrics(win_rate=0.55, profit_factor=1.50, max_drawdown=0.10),
        prediction_metrics=PredictionMetrics(brier_score=0.20, roc_auc=0.62),
    )
    chall = EvaluationReport(
        model_version="chall_v2",
        sample_size=100,
        trading_metrics=TradingMetrics(win_rate=0.60, profit_factor=1.75, max_drawdown=0.09),
        prediction_metrics=PredictionMetrics(brier_score=0.18, roc_auc=0.66),
    )

    comp = ComparisonReport(
        champion_version="champ_v1",
        challenger_version="chall_v2",
        champion_metrics=champ,
        challenger_metrics=chall,
        delta_metrics={"profit_factor_delta": 0.25, "brier_score_delta": -0.02},
        recommendation=ComparisonRecommendation.PROMOTE.value,
        rationale=["Challenger outperforms champion across all gates."],
    )
    assert comp.recommendation == "PROMOTE"
    assert comp.delta_metrics["profit_factor_delta"] == 0.25

    with pytest.raises(ValueError, match="recommendation must be"):
        ComparisonReport(
            champion_version="champ_v1",
            challenger_version="chall_v2",
            champion_metrics=champ,
            challenger_metrics=chall,
            recommendation="INVALID_DECISION",
        )
