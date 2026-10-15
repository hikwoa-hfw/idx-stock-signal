import math
from datetime import date, timedelta
from typing import Any

import pytest

from python.common.types import DailyBar, SignalConfig
from python.signals.engine import SignalEngine


class MockClassifier:
    """Mock classifier returning a constant probability."""

    def __init__(self, prob: float, model_version: str = "mock_clf_v1") -> None:
        self.prob = prob
        self.model_version = model_version
        self.feature_names_ = ["return_1d"]

    def predict_probability(self, X: Any) -> list[float]:
        return [self.prob] * len(X)


class MockRegressor:
    """Mock regressor returning a constant expected return."""

    def __init__(self, ret: float, model_version: str = "mock_reg_v1") -> None:
        self.ret = ret
        self.model_version = model_version

    def predict_expected_return(self, X: Any) -> list[float]:
        return [self.ret] * len(X)


def create_bars_fixture(
    ticker: str = "BBCA",
    start_date: date = date(2026, 1, 1),
    count: int = 25,
    base_price: float = 10000.0,
) -> list[DailyBar]:
    bars = []
    current_date = start_date
    for i in range(count):
        price = base_price + i * 10.0
        bars.append(
            DailyBar(
                ticker=ticker,
                date=current_date,
                open=price,
                high=price + 20.0,
                low=price - 20.0,
                close=price,
                volume=1_000_000.0,
                value=price * 1_000_000.0,
            )
        )
        current_date += timedelta(days=1)
    return bars


# -------------------------------------------------------------------------
# 1. Positive EV (> 0) and Negative EV (<= 0)
# -------------------------------------------------------------------------


def test_ev_gate_blocks_negative_ev():
    """Verify that bets with negative expected value are blocked even if probability is high."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    # Prob 0.25 is well below ~32.02% breakeven hurdle
    cfg = SignalConfig(min_probability=0.20, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.25),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 0


def test_ev_gate_passes_positive_ev():
    """Verify that bets with positive EV pass and have net_ev > 0."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    # Prob 0.40 has positive net EV with default TP 5%, SL 2%, friction 0.50%
    cfg = SignalConfig(min_probability=0.20, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)

    signals = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.40),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal == "BUY"
    assert sig.net_ev is not None
    assert sig.net_ev > 0.0


# -------------------------------------------------------------------------
# 2. Exact Breakeven Boundary (p ≈ 32.02% / 32.1%)
# -------------------------------------------------------------------------


def test_ev_gate_exact_breakeven_fail_closed():
    """Verify that exact breakeven (EV == 0.0) is blocked due to <= 0 fail-closed rule."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    cfg = SignalConfig(min_probability=0.20, enforce_positive_ev=True)
    friction = cfg.commission_buy + cfg.commission_sell + (cfg.slippage_bps / 10000.0)
    tp_net = cfg.tp_pct - friction
    sl_net = -cfg.sl_pct - friction
    exp_net = cfg.empirical_expiry_return - friction
    exp_ratio = cfg.expiry_given_negative_ratio

    # Solve p * tp_net + (1 - p) * ((1 - exp_ratio) * sl_net + exp_ratio * exp_net) = 0
    neg_bracket = (1.0 - exp_ratio) * sl_net + exp_ratio * exp_net
    breakeven_p = -neg_bracket / (tp_net - neg_bracket)

    # 1. At exact breakeven (or float precision equal), EV <= 0 must fail closed
    engine = SignalEngine(config=cfg)
    signals_exact = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(breakeven_p),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals_exact) == 0

    # 2. Just below breakeven (p - 0.001) is strictly negative EV -> blocked
    signals_below = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(breakeven_p - 0.001),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals_below) == 0

    # 3. Slightly above breakeven (e.g. p=32.1%, which is > 32.02%) -> positive EV -> emitted
    signals_above = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.321),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(signals_above) == 1
    assert signals_above[0].net_ev is not None
    assert signals_above[0].net_ev > 0.0


# -------------------------------------------------------------------------
# 3. Non-Finite NaN / Inf Handling (Fail-Closed)
# -------------------------------------------------------------------------


def test_ev_gate_regressor_nan_inf_fail_closed():
    """Verify non-finite return predictions from regressor fail closed properly."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    # 1. require_expected_return=True with NaN -> fail closed (0 signals)
    cfg_req = SignalConfig(
        min_probability=0.20,
        enforce_positive_ev=True,
        require_expected_return=True,
    )
    engine_req = SignalEngine(config=cfg_req)
    sigs_nan = engine_req.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=MockRegressor(float("nan")),
        bars_by_ticker={"BBCA": bars},
        config=cfg_req,
    )
    assert len(sigs_nan) == 0

    # 2. require_expected_return=True with Inf -> fail closed (0 signals)
    sigs_inf = engine_req.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=MockRegressor(float("inf")),
        bars_by_ticker={"BBCA": bars},
        config=cfg_req,
    )
    assert len(sigs_inf) == 0

    sigs_neginf = engine_req.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=MockRegressor(float("-inf")),
        bars_by_ticker={"BBCA": bars},
        config=cfg_req,
    )
    assert len(sigs_neginf) == 0

    # 3. require_expected_return=False with NaN -> safely falls back to discrete EV
    cfg_fallback = SignalConfig(
        min_probability=0.20,
        enforce_positive_ev=True,
        require_expected_return=False,
    )
    engine_fallback = SignalEngine(config=cfg_fallback)
    sigs_fallback = engine_fallback.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=MockRegressor(float("nan")),
        bars_by_ticker={"BBCA": bars},
        config=cfg_fallback,
    )
    assert len(sigs_fallback) == 1
    assert math.isfinite(sigs_fallback[0].net_ev)
    assert sigs_fallback[0].net_ev > 0.0


def test_ev_gate_classifier_non_finite_fail_closed():
    """Verify non-finite or non-positive probabilities from classifier fail closed."""
    bars = create_bars_fixture()
    target_date = bars[-1].date
    cfg = SignalConfig(min_probability=0.10, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)

    # NaN probability
    assert (
        len(
            engine.generate_signals(
                signal_date=target_date,
                classifier=MockClassifier(float("nan")),
                bars_by_ticker={"BBCA": bars},
                config=cfg,
            )
        )
        == 0
    )

    # Inf probability
    assert (
        len(
            engine.generate_signals(
                signal_date=target_date,
                classifier=MockClassifier(float("inf")),
                bars_by_ticker={"BBCA": bars},
                config=cfg,
            )
        )
        == 0
    )

    # Zero probability
    assert (
        len(
            engine.generate_signals(
                signal_date=target_date,
                classifier=MockClassifier(0.0),
                bars_by_ticker={"BBCA": bars},
                config=cfg,
            )
        )
        == 0
    )


# -------------------------------------------------------------------------
# 4. Missing Expected Return When Required
# -------------------------------------------------------------------------


def test_ev_gate_missing_expected_return_when_required():
    """Verify require_expected_return blocks when regressor is absent or fails."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    cfg = SignalConfig(
        min_probability=0.20,
        enforce_positive_ev=True,
        require_expected_return=True,
    )
    engine = SignalEngine(config=cfg)

    # 1. regressor is None
    sigs_none = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=None,
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(sigs_none) == 0

    # 2. regressor raises an exception during inference
    class ErrorRegressor:
        model_version = "err_reg"

        def predict_expected_return(self, X: Any) -> list[float]:
            raise RuntimeError("Model runtime inference failed")

    sigs_err = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=ErrorRegressor(),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(sigs_err) == 0


# -------------------------------------------------------------------------
# 5. Friction Deduction (Buy 0.15%, Sell 0.25%, Slippage 10 bps)
# -------------------------------------------------------------------------


def test_ev_gate_friction_deduction_and_cost_sensitivity():
    """Verify exact round-trip friction deduction and sensitivity to trading costs."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    # Default friction = 0.15% + 0.25% + (10 / 10000 = 0.10%) = 0.0050 (50 bps)
    cfg_default = SignalConfig(
        min_probability=0.20,
        commission_buy=0.0015,
        commission_sell=0.0025,
        slippage_bps=10.0,
        enforce_positive_ev=True,
    )
    engine = SignalEngine(config=cfg_default)

    # At prob = 0.35, default 50 bps friction yields positive EV:
    sigs_pass = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.35),
        bars_by_ticker={"BBCA": bars},
        config=cfg_default,
    )
    assert len(sigs_pass) == 1
    assert sigs_pass[0].net_ev > 0.0

    # Increase friction: buy 0.30%, sell 0.50%, slippage 30 bps -> total 0.0110 (110 bps)
    cfg_expensive = SignalConfig(
        min_probability=0.20,
        commission_buy=0.0030,
        commission_sell=0.0050,
        slippage_bps=30.0,
        enforce_positive_ev=True,
    )
    sigs_fail = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.35),
        bars_by_ticker={"BBCA": bars},
        config=cfg_expensive,
    )
    # The higher friction pushes EV <= 0 -> blocked
    assert len(sigs_fail) == 0


# -------------------------------------------------------------------------
# 6. Discrete vs Continuous Minimum EV
# -------------------------------------------------------------------------


def test_ev_gate_discrete_vs_continuous_hurdle():
    """Verify effective_net_ev takes min(discrete_ev, continuous_return - friction)."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    cfg = SignalConfig(min_probability=0.20, enforce_positive_ev=True)
    engine = SignalEngine(config=cfg)

    # Case A: Discrete EV > 0 (prob 0.80), but continuous predicted return is below friction
    # Continuous return = +0.003, friction = 0.005 -> continuous net = -0.002 <= 0
    sigs_cont_drag = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.80),
        regressor=MockRegressor(0.003),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(sigs_cont_drag) == 0

    # Case B: High continuous return (+10%), but low discrete win probability (0.25 -> EV <= 0)
    sigs_disc_drag = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.25),
        regressor=MockRegressor(0.10),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(sigs_disc_drag) == 0

    # Case C: Both clear positive hurdle
    # Discrete prob 0.70 (ev_net_discrete ≈ 0.0252), regressor exp_ret 0.06 (net = 0.055)
    sigs_both_clear = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.70),
        regressor=MockRegressor(0.06),
        bars_by_ticker={"BBCA": bars},
        config=cfg,
    )
    assert len(sigs_both_clear) == 1
    # net_ev should be min(discrete, continuous_net)
    expected_disc = 0.70 * (0.05 - 0.005) + (1 - 0.70) * (
        (1 - 0.1414) * (-0.02 - 0.005) + 0.1414 * (0.0069 - 0.005)
    )
    expected_cont = 0.06 - 0.005
    expected_effective = min(expected_disc, expected_cont)
    assert sigs_both_clear[0].net_ev == pytest.approx(round(expected_effective, 4), abs=1e-3)


def test_ev_gate_custom_min_net_ev_hurdle():
    """Verify customizable min_net_ev hurdle threshold."""
    bars = create_bars_fixture()
    target_date = bars[-1].date

    # Require at least 2% net EV (0.02)
    cfg_strict = SignalConfig(
        min_probability=0.20,
        enforce_positive_ev=True,
        min_net_ev=0.02,
    )
    engine = SignalEngine(config=cfg_strict)

    # Prob 0.45 has net EV around ~0.0086 (> 0, but < 0.02 hurdle) -> blocked
    sigs_blocked = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.45),
        bars_by_ticker={"BBCA": bars},
        config=cfg_strict,
    )
    assert len(sigs_blocked) == 0

    # Prob 0.75 has net EV around ~0.0285 (> 0.02 hurdle) -> emitted
    sigs_passed = engine.generate_signals(
        signal_date=target_date,
        classifier=MockClassifier(0.75),
        bars_by_ticker={"BBCA": bars},
        config=cfg_strict,
    )
    assert len(sigs_passed) == 1
    assert sigs_passed[0].net_ev > 0.02
