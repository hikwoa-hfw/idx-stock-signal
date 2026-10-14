import hashlib
import math
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
except ImportError:
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_dump(self, **kwargs):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

        def dict(self, **kwargs):
            return self.model_dump(**kwargs)

    def Field(default=None, default_factory=None, **kwargs):  # type: ignore[no-redef]
        if default_factory is not None:
            return default_factory()
        return default

    def field_validator(*args, **kwargs):  # type: ignore[no-redef]
        def dec(fn):
            return fn

        return dec

    def model_validator(*args, **kwargs):  # type: ignore[no-redef]
        def dec(fn):
            return fn

        return dec


class DailyBar(BaseModel):
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: Optional[float] = None
    adj_close: Optional[float] = None
    dividends: Optional[float] = 0.0
    stock_splits: Optional[float] = 0.0
    provider: Optional[str] = None
    provider_symbol: Optional[str] = None
    ingestion_run_id: Optional[str] = None
    interval: str = "1d"
    row_hash: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_raw_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "trading_date" in data and "date" not in data:
                data["date"] = data["trading_date"]
            if "open_raw" in data and "open" not in data:
                data["open"] = data["open_raw"]
            if "high_raw" in data and "high" not in data:
                data["high"] = data["high_raw"]
            if "low_raw" in data and "low" not in data:
                data["low"] = data["low_raw"]
            if "close_raw" in data and "close" not in data:
                data["close"] = data["close_raw"]
            if "volume_raw" in data and "volume" not in data:
                data["volume"] = data["volume_raw"]
            if "adj_close_provider" in data and "adj_close" not in data:
                data["adj_close"] = data["adj_close_provider"]
        return data

    @property
    def trading_date(self) -> date:
        return self.date

    @property
    def open_raw(self) -> float:
        return self.open

    @property
    def high_raw(self) -> float:
        return self.high

    @property
    def low_raw(self) -> float:
        return self.low

    @property
    def close_raw(self) -> float:
        return self.close

    @property
    def volume_raw(self) -> float:
        return self.volume

    @property
    def adj_close_provider(self) -> Optional[float]:
        return self.adj_close

    def compute_row_hash(self) -> str:
        clean_t = self.ticker.strip().upper().removesuffix(".JK")
        parts = [
            clean_t,
            str(self.date),
            self.interval or "1d",
            f"{self.open:.4f}",
            f"{self.high:.4f}",
            f"{self.low:.4f}",
            f"{self.close:.4f}",
            f"{self.volume:.2f}",
            f"{self.adj_close:.4f}" if self.adj_close is not None else "",
            f"{(self.dividends or 0.0):.4f}",
            f"{(self.stock_splits or 0.0):.4f}",
            self.provider or "",
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    @model_validator(mode="after")
    def _ensure_row_hash(self) -> "DailyBar":
        if not self.row_hash:
            self.row_hash = self.compute_row_hash()
        return self


class IngestionRun(BaseModel):
    id: str
    provider: str
    job_type: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    tickers_requested: int = 0
    tickers_succeeded: int = 0
    tickers_partial: int = 0
    tickers_failed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_rejected: int = 0
    error_summary: Optional[str] = None
    config_version: Optional[str] = None


class IngestionTickerStatus(BaseModel):
    id: str
    ingestion_run_id: str
    ticker: str
    status: str
    rows_received: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    first_date_received: Optional[date] = None
    last_date_received: Optional[date] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempt_count: int = 1


class PriceMode(str, Enum):
    LOW_PRICE = "LOW_PRICE"
    HIGHER_PRICE = "HIGHER_PRICE"
    EXCLUDED_BELOW_50 = "EXCLUDED_BELOW_50"
    INVALID = "INVALID"


def classify_price_mode(price: Optional[float]) -> str:
    """Classifies a decision/close price into dual modes or exclusion.

    IDR 50 to 300 (inclusive) -> LOW_PRICE
    Strictly > 300 -> HIGHER_PRICE
    < 50 -> EXCLUDED_BELOW_50
    NaN / non-positive / non-finite -> INVALID
    """
    if price is None:
        return PriceMode.INVALID.value
    try:
        p = float(price)
    except (ValueError, TypeError):
        return PriceMode.INVALID.value
    if not math.isfinite(p) or p <= 0:
        return PriceMode.INVALID.value
    if p < 50.0:
        return PriceMode.EXCLUDED_BELOW_50.value
    if 50.0 <= p <= 300.0:
        return PriceMode.LOW_PRICE.value
    return PriceMode.HIGHER_PRICE.value


def get_bei_tick_size(price: float) -> int:
    """Returns official IDX / BEI tick size (fraksi harga) for a given price.

    Price range (IDR):
    < 200          : Rp 1
    200 to < 500   : Rp 2
    500 to < 2000  : Rp 5
    2000 to < 5000 : Rp 10
    >= 5000        : Rp 25
    """
    p = float(price)
    if p < 200.0:
        return 1
    elif p < 500.0:
        return 2
    elif p < 2000.0:
        return 5
    elif p < 5000.0:
        return 10
    else:
        return 25


def round_down_to_tick(price: float, tick: Optional[int] = None) -> float:
    """Rounds down to nearest valid BEI tick boundary."""
    t = float(tick if tick is not None else get_bei_tick_size(price))
    cand = float(math.floor(price / t) * t)
    cand_tick = float(get_bei_tick_size(cand))
    if cand % cand_tick != 0:
        cand = float(math.floor(cand / cand_tick) * cand_tick)
    return cand


def round_up_to_tick(price: float, tick: Optional[int] = None) -> float:
    """Rounds up to nearest valid BEI tick boundary."""
    t = float(tick if tick is not None else get_bei_tick_size(price))
    cand = float(math.ceil(price / t) * t)
    cand_tick = float(get_bei_tick_size(cand))
    if cand % cand_tick != 0:
        cand = float(math.ceil(cand / cand_tick) * cand_tick)
    return cand


def round_to_nearest_tick(price: float, tick: Optional[int] = None) -> float:
    """Rounds to nearest valid BEI tick boundary."""
    t = float(tick if tick is not None else get_bei_tick_size(price))
    cand = float(round(price / t) * t)
    cand_tick = float(get_bei_tick_size(cand))
    if cand % cand_tick != 0:
        cand = float(round(cand / cand_tick) * cand_tick)
    return cand



class SignalAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class OutcomeStatus(str, Enum):
    PENDING = "PENDING"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    AMBIGUOUS = "AMBIGUOUS"


class Signal(BaseModel):
    ticker: str
    signal_date: date
    action: SignalAction = SignalAction.BUY
    entry_price: float
    target_price: float
    stop_loss: float
    max_holding_days: int = 10
    probability: float
    model_version: str
    score: Optional[float] = None
    mode: Optional[str] = None

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode


class Position(BaseModel):
    position_id: str
    ticker: str
    entry_date: date
    entry_price: float
    quantity: int
    target_price: float
    stop_loss: float
    max_holding_days: int = 10
    is_open: bool = True
    close_date: Optional[date] = None
    close_price: Optional[float] = None
    mode: Optional[str] = None

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode


class Prediction(BaseModel):
    ticker: str
    prediction_date: date
    model_version: str
    probability: float
    expected_return: Optional[float] = None
    mode: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode


class Outcome(BaseModel):
    ticker: str
    signal_date: date
    status: OutcomeStatus
    realized_return: Optional[float] = None
    holding_days: int
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelVersion(BaseModel):
    version: str
    model_type: str
    trained_at: datetime
    metrics: dict[str, float] = Field(default_factory=dict)
    is_champion: bool = False


class FeatureRecord(BaseModel):
    ticker: str
    date: date
    feature_version: str = "v1.0.0"
    breakout_price: Optional[float] = None
    entry_price: Optional[float] = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper().removesuffix(".JK")

    # Momentum
    return_1d: Optional[float] = None
    return_3d: Optional[float] = None
    return_5d: Optional[float] = None
    return_10d: Optional[float] = None
    return_20d: Optional[float] = None

    # Trend
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None
    close_vs_ema20: Optional[float] = None
    close_vs_ema50: Optional[float] = None
    ema20_vs_ema50: Optional[float] = None
    ema50_vs_ema200: Optional[float] = None

    # RSI
    rsi14: Optional[float] = None
    rsi_change_5d: Optional[float] = None

    # Volatility
    atr14: Optional[float] = None
    atr_pct: Optional[float] = None
    realized_vol_5d: Optional[float] = None
    realized_vol_20d: Optional[float] = None
    daily_range_pct: Optional[float] = None

    # Volume
    volume_ratio_5d: Optional[float] = None
    volume_ratio_20d: Optional[float] = None
    value_ratio_20d: Optional[float] = None

    # Relative Strength
    rel_strength_ihsg_20d: Optional[float] = None
    rel_strength_sector_20d: Optional[float] = None

    # Market Regime
    ihsg_return_5d: Optional[float] = None
    ihsg_return_20d: Optional[float] = None
    ihsg_vs_ema20: Optional[float] = None
    ihsg_vs_ema50: Optional[float] = None
    market_breadth: Optional[float] = None
    market_volatility: Optional[float] = None


class LabelOutcome(str, Enum):
    TP = "TP"
    SL = "SL"
    EXPIRY = "EXPIRY"
    AMBIGUOUS = "AMBIGUOUS"


class AmbiguityPolicy(str, Enum):
    CONSERVATIVE = "conservative"
    OPTIMISTIC = "optimistic"
    AMBIGUOUS = "ambiguous"


class LabelRecord(BaseModel):
    ticker: str
    date: date
    label_version: str = "v1.0.0"
    entry_price: float
    tp_price: float
    sl_price: float
    tp_pct: float
    sl_pct: float
    max_holding_days: int = 10
    outcome: str = "EXPIRY"
    binary_target: int = 0
    mfe: float = 0.0
    mae: float = 0.0
    holding_days: int = 0
    realized_return: float = 0.0
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    ambiguity_policy: str = "conservative"
    mode: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
        return data

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper().removesuffix(".JK")

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, v: str) -> str:
        val = v.value if isinstance(v, LabelOutcome) else str(v)
        clean = val.strip().upper()
        if clean not in ("TP", "SL", "EXPIRY", "AMBIGUOUS"):
            raise ValueError(f"Invalid outcome: '{v}'. Expected TP, SL, EXPIRY, or AMBIGUOUS.")
        return clean

    @field_validator("ambiguity_policy")
    @classmethod
    def validate_policy(cls, v: str) -> str:
        val = v.value if isinstance(v, AmbiguityPolicy) else str(v)
        clean = val.strip().lower()
        if clean not in ("conservative", "optimistic", "ambiguous"):
            raise ValueError(
                f"Invalid ambiguity_policy: '{v}'. Expected conservative, optimistic, or ambiguous."
            )
        return clean

    @field_validator("binary_target")
    @classmethod
    def validate_binary_target(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError(f"binary_target must be 0 or 1, got {v}")
        return v

    @field_validator("entry_price", "tp_price", "sl_price")
    @classmethod
    def validate_positive_prices(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Price must be a positive finite number, got {v}")
        return v

    @field_validator("tp_pct", "sl_pct")
    @classmethod
    def validate_positive_pct(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Percentage barrier must be a positive finite number, got {v}")
        return v

    @field_validator("mfe", "mae", "realized_return")
    @classmethod
    def validate_finite_floats(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Metric must be a finite float, got {v}")
        return v

    @field_validator("max_holding_days", "holding_days")
    @classmethod
    def validate_holding_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"Holding days must be non-negative, got {v}")
        return v

    @property
    def target(self) -> int:
        return self.binary_target


class PositionSizingMethod(str, Enum):
    RISK_BASED = "risk_based"
    FIXED_FRACTIONAL = "fixed_fractional"
    EQUAL_WEIGHT = "equal_weight"


class BacktestConfig(BaseModel):
    initial_capital: float = 100_000_000.0
    commission_buy: float = 0.0015
    commission_sell: float = 0.0025
    slippage_bps: float = 10.0
    max_concurrent_positions: int = 5
    risk_per_trade_pct: float = 0.005
    max_position_pct: float = 0.20
    lot_size: int = 100
    position_sizing_method: str = "risk_based"
    tp_pct: float = 0.05
    sl_pct: float = 0.02
    max_holding_days: int = 10
    entry_execution: str = "next_open"
    probability_threshold: float = 0.50
    ambiguity_policy: str = "conservative"

    @field_validator("initial_capital")
    @classmethod
    def validate_initial_capital(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"initial_capital must be a positive finite number, got {v}")
        return v

    @field_validator("commission_buy", "commission_sell")
    @classmethod
    def validate_commissions(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"Commission must be a non-negative finite number, got {v}")
        return v

    @field_validator("slippage_bps")
    @classmethod
    def validate_slippage(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"slippage_bps must be a non-negative finite number, got {v}")
        return v

    @field_validator("max_concurrent_positions")
    @classmethod
    def validate_max_positions(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_concurrent_positions must be at least 1, got {v}")
        return v

    @field_validator("lot_size")
    @classmethod
    def validate_lot_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"lot_size must be at least 1, got {v}")
        return v

    @field_validator("risk_per_trade_pct", "max_position_pct", "tp_pct", "sl_pct")
    @classmethod
    def validate_positive_pct(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Percentage parameter must be a positive finite number, got {v}")
        return v

    @field_validator("max_holding_days")
    @classmethod
    def validate_max_holding_days(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_holding_days must be at least 1, got {v}")
        return v

    @field_validator("probability_threshold")
    @classmethod
    def validate_probability_threshold(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 1.0:
            raise ValueError(f"probability_threshold must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("position_sizing_method")
    @classmethod
    def validate_sizing_method(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("risk_based", "fixed_fractional", "equal_weight"):
            raise ValueError(
                f"Invalid position_sizing_method: '{v}'. "
                "Expected 'risk_based', 'fixed_fractional', or 'equal_weight'."
            )
        return s

    @field_validator("ambiguity_policy")
    @classmethod
    def validate_policy(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("conservative", "optimistic", "ambiguous"):
            raise ValueError(
                f"Invalid ambiguity_policy: '{v}'. "
                "Expected 'conservative', 'optimistic', or 'ambiguous'."
            )
        return s

    @field_validator("entry_execution")
    @classmethod
    def validate_entry_execution(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("next_open", "next_close"):
            raise ValueError(
                f"Invalid entry_execution: '{v}'. Expected 'next_open' or 'next_close'."
            )
        return s


class TradeRecord(BaseModel):
    trade_id: str
    ticker: str
    signal_date: date
    entry_date: date
    exit_date: date
    shares: int
    entry_price: float
    exit_price: float
    position_value: float
    entry_fee: float
    exit_fee: float
    slippage_cost: float
    gross_pnl: float
    net_pnl: float
    net_return: float
    exit_reason: str
    holding_days: int
    mfe: float = 0.0
    mae: float = 0.0
    signal_probability: Optional[float] = None
    mode: Optional[str] = None

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
        return data

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper().removesuffix(".JK")

    @field_validator("shares")
    @classmethod
    def validate_shares(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"shares must be non-negative, got {v}")
        return v

    @field_validator("entry_price", "exit_price")
    @classmethod
    def validate_positive_prices(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Price must be a positive finite number, got {v}")
        return v

    @field_validator(
        "position_value",
        "entry_fee",
        "exit_fee",
        "slippage_cost",
        "gross_pnl",
        "net_pnl",
        "net_return",
        "mfe",
        "mae",
    )
    @classmethod
    def validate_finite_floats(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Value must be a finite float, got {v}")
        return v

    @field_validator("holding_days")
    @classmethod
    def validate_holding_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"holding_days must be non-negative, got {v}")
        return v

    @field_validator("signal_probability")
    @classmethod
    def validate_prob(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if not math.isfinite(v) or v < 0.0 or v > 1.0:
                raise ValueError(f"signal_probability must be in [0.0, 1.0], got {v}")
        return v


class EquityPoint(BaseModel):
    date: date
    cash: float
    positions_value: float
    total_equity: float
    drawdown_pct: float = 0.0
    open_positions_count: int = 0

    @field_validator("cash", "positions_value", "total_equity")
    @classmethod
    def validate_finite_floats(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Equity values must be finite floats, got {v}")
        return v

    @field_validator("drawdown_pct")
    @classmethod
    def validate_dd_pct(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 1.0:
            raise ValueError(f"drawdown_pct must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("open_positions_count")
    @classmethod
    def validate_pos_count(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"open_positions_count must be non-negative, got {v}")
        return v


class BacktestReport(BaseModel):
    config: BacktestConfig
    start_date: date
    end_date: date
    initial_capital: float
    final_equity: float
    total_net_pnl: float
    total_return_pct: float
    cagr_pct: Optional[float] = None
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win_pct: float
    average_loss_pct: float
    win_loss_ratio: float
    profit_factor: float
    expectancy_pct: float
    max_drawdown_pct: float
    max_drawdown_amount: float
    average_holding_days: float
    tp_rate: float
    sl_rate: float
    expiry_rate: float
    trades: list[TradeRecord] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)


class SignalConfig(BaseModel):
    min_probability: float = 0.55
    min_expected_return: Optional[float] = None
    min_volume_20d: Optional[float] = None
    min_value_20d: Optional[float] = None
    tp_pct: float = 0.05
    sl_pct: float = 0.02
    max_holding_days: int = 10
    entry_band_pct: float = 0.01
    top_n: int = 5
    signal_config_version: str = "v1.0.0"
    mode: Optional[str] = None
    require_expected_return: bool = False
    max_entry_deviation_pct: float = 0.05
    min_range_ticks: int = 1
    enforce_bei_ticks: bool = False
    allow_breakout: bool = True
    raw_adjusted_tolerance_pct: float = 0.05
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "probability": 0.40,
            "return": 0.20,
            "risk": 0.10,
            "liquidity": 0.15,
            "regime": 0.15,
        }
    )

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @field_validator("min_probability")
    @classmethod
    def validate_min_probability(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 1.0:
            raise ValueError(f"min_probability must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("tp_pct", "sl_pct")
    @classmethod
    def validate_positive_percentages(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"Percentage parameter must be a positive finite float, got {v}")
        return v

    @field_validator("entry_band_pct", "max_entry_deviation_pct", "raw_adjusted_tolerance_pct")
    @classmethod
    def validate_non_negative_percentages(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0:
            raise ValueError(f"Percentage parameter must be a non-negative finite float, got {v}")
        return v

    @field_validator("max_holding_days", "top_n", "min_range_ticks")
    @classmethod
    def validate_positive_integers(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"Value must be >= 1, got {v}")
        return v

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("weights dict cannot be empty")
        for k, w in v.items():
            if not math.isfinite(w) or w < 0.0:
                raise ValueError(f"Weight '{k}' must be a non-negative finite float, got {w}")
        if sum(v.values()) <= 0:
            raise ValueError("At least one weight must be greater than 0")
        return v


class SignalRecord(BaseModel):
    signal_id: str
    ticker: str
    signal_date: date
    signal: str = "BUY"
    status: str = "BUY"
    entry_low: float
    entry_high: float
    tp_price: float
    sl_price: float
    max_holding_days: int = 10
    predicted_probability: float
    expected_return: Optional[float] = None
    score: float
    model_version: str
    feature_version: str = "v1.0.0"
    signal_config_version: str = "v1.0.0"
    feature_snapshot: dict[str, Any] = Field(default_factory=dict)
    mode: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    market_data_as_of: Optional[datetime] = None
    latest_completed_bar_date: Optional[date] = None
    reference_price: Optional[float] = None
    entry_policy: str = "IMMEDIATE"
    max_entry_deviation_pct: float = 0.05

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
            if "signal_generated_at" not in data and "created_at" in data:
                data["signal_generated_at"] = data["created_at"]
            if "latest_completed_bar_date" not in data and "signal_date" in data:
                data["latest_completed_bar_date"] = data["signal_date"]
            if "status" in data and "signal" not in data:
                data["signal"] = data["status"]
            elif "signal" in data and "status" not in data:
                data["status"] = data["signal"]
            if "entry_policy" not in data:
                data["entry_policy"] = "IMMEDIATE"
        return data

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper().removesuffix(".JK")

    @field_validator("signal", "status")
    @classmethod
    def validate_signal(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("signal action cannot be empty")
        return s

    @field_validator("entry_low", "entry_high", "tp_price", "sl_price")
    @classmethod
    def validate_prices(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Price must be a positive finite float, got {v}")
        return v

    @field_validator("reference_price")
    @classmethod
    def validate_reference_price(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if not math.isfinite(v) or v <= 0:
                raise ValueError(f"reference_price must be a positive finite float, got {v}")
        return v

    @field_validator("predicted_probability")
    @classmethod
    def validate_probability(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 1.0:
            raise ValueError(f"predicted_probability must be in [0.0, 1.0], got {v}")
        return v

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 100.0:
            raise ValueError(f"score must be between 0.0 and 100.0, got {v}")
        return v

    @field_validator("max_holding_days")
    @classmethod
    def validate_holding_days(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_holding_days must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def validate_barriers(self) -> "SignalRecord":
        if self.entry_low > self.entry_high:
            raise ValueError(
                f"entry_low ({self.entry_low}) cannot exceed entry_high ({self.entry_high})"
            )
        if self.tp_price < self.entry_high:
            raise ValueError(
                f"tp_price ({self.tp_price}) must be >= entry_high ({self.entry_high})"
            )
        if self.sl_price > self.entry_low:
            raise ValueError(f"sl_price ({self.sl_price}) must be <= entry_low ({self.entry_low})")

        # Price integrity validation against reference_price if provided
        if self.reference_price is not None:
            eff_status = (self.status or self.signal or "").strip().upper()
            max_dev = getattr(self, "max_entry_deviation_pct", 0.05) or 0.05
            dev_high = (self.entry_high - self.reference_price) / self.reference_price
            dev_low = (self.reference_price - self.entry_low) / self.reference_price

            if self.entry_policy == "BREAKOUT":
                if eff_status == "BUY":
                    raise ValueError(
                        "Signal with BREAKOUT policy cannot have BUY status; "
                        "must use conditional status such as WAIT_FOR_BREAKOUT."
                    )
                if eff_status == "WAIT_FOR_BREAKOUT" and self.entry_low < self.reference_price:
                    raise ValueError(
                        f"Breakout trigger entry_low ({self.entry_low}) cannot be below "
                        f"reference price ({self.reference_price})."
                    )

            if eff_status == "BUY":
                if self.entry_policy != "IMMEDIATE":
                    raise ValueError(
                        f"BUY status requires IMMEDIATE entry policy, got '{self.entry_policy}'."
                    )
                if dev_high > max_dev or dev_low > max_dev:
                    raise ValueError(
                        f"Immediate BUY entry price [{self.entry_low}, {self.entry_high}] deviates "
                        f"excessively from reference price {self.reference_price} (max deviation: "
                        f"{max_dev * 100:.1f}%). Must fail closed or use WAIT_FOR_BREAKOUT status."
                    )
            elif eff_status == "WAIT_FOR_BREAKOUT":
                if self.entry_low < self.reference_price:
                    raise ValueError(
                        f"Breakout trigger entry_low ({self.entry_low}) cannot be below "
                        f"reference price ({self.reference_price})."
                    )

        return self


class PositionRecord(BaseModel):
    position_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: Optional[str] = None
    ticker: str
    actual_entry_date: date
    actual_entry_price: float
    quantity: int
    actual_exit_date: Optional[date] = None
    actual_exit_price: Optional[float] = None
    status: str = "OPEN"
    exit_reason: Optional[str] = None
    realized_return: Optional[float] = None
    fees: float = 0.0
    holding_days: Optional[int] = None
    notes: Optional[str] = None
    mode: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
        return data

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        clean = v.strip().upper().removesuffix(".JK")
        if not clean:
            raise ValueError("ticker cannot be empty")
        return clean

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        s = v.strip().upper()
        if s not in {"OPEN", "CLOSED", "CANCELLED"}:
            raise ValueError(f"status must be one of 'OPEN', 'CLOSED', 'CANCELLED', got '{v}'")
        return s

    @field_validator("exit_reason")
    @classmethod
    def validate_exit_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        r = v.strip().upper()
        if r not in {"TP", "SL", "EXPIRY", "MANUAL", "OTHER"}:
            raise ValueError(
                f"exit_reason must be one of 'TP', 'SL', 'EXPIRY', 'MANUAL', 'OTHER', got '{v}'"
            )
        return r

    @field_validator("actual_entry_price")
    @classmethod
    def validate_entry_price(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"actual_entry_price must be positive and finite, got {v}")
        return v

    @field_validator("actual_exit_price")
    @classmethod
    def validate_exit_price(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"actual_exit_price must be positive and finite, got {v}")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantity must be > 0, got {v}")
        return v

    @field_validator("fees")
    @classmethod
    def validate_fees(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"fees must be non-negative and finite, got {v}")
        return v

    @field_validator("holding_days")
    @classmethod
    def validate_holding_days(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError(f"holding_days cannot be negative, got {v}")
        return v

    @field_validator("realized_return")
    @classmethod
    def validate_realized_return(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError(f"realized_return must be a finite float, got {v}")
        return v

    @model_validator(mode="after")
    def validate_position_lifecycle(self) -> "PositionRecord":
        if self.actual_exit_date is not None and self.actual_entry_date is not None:
            if self.actual_exit_date < self.actual_entry_date:
                raise ValueError(
                    f"actual_exit_date ({self.actual_exit_date}) cannot precede "
                    f"actual_entry_date ({self.actual_entry_date})"
                )
        if self.status == "CLOSED":
            if self.actual_exit_price is None:
                raise ValueError("Closed position must specify actual_exit_price")
            if self.actual_exit_date is None:
                raise ValueError("Closed position must specify actual_exit_date")
            if self.holding_days is None and self.actual_exit_date is not None:
                self.holding_days = (self.actual_exit_date - self.actual_entry_date).days
            if self.realized_return is None:
                cost_basis = self.actual_entry_price * self.quantity
                net_pnl = (
                    self.actual_exit_price - self.actual_entry_price
                ) * self.quantity - self.fees
                self.realized_return = net_pnl / cost_basis
            if self.exit_reason is None:
                self.exit_reason = "MANUAL"
        elif self.status == "OPEN":
            if self.actual_exit_price is not None:
                raise ValueError("Open position cannot have actual_exit_price")
            if self.actual_exit_date is not None:
                raise ValueError("Open position cannot have actual_exit_date")
        elif self.status == "CANCELLED":
            if self.actual_exit_price is not None:
                raise ValueError("Cancelled position cannot have actual_exit_price")
            if self.actual_exit_date is not None:
                raise ValueError("Cancelled position cannot have actual_exit_date")
            if self.realized_return is not None:
                raise ValueError("Cancelled position cannot have realized_return")
        return self


class SignalOutcomeRecord(BaseModel):
    outcome_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    ticker: str
    signal_date: date
    entry_date: date
    entry_price: float
    outcome_status: str = "OPEN"
    realized_return: Optional[float] = None
    holding_days: int = 0
    mfe: float = 0.0
    mae: float = 0.0
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None
    mode: Optional[str] = None

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
        return data

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        clean = v.strip().upper().removesuffix(".JK")
        if not clean:
            raise ValueError("ticker cannot be empty")
        return clean

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("signal_id cannot be empty")
        return clean

    @field_validator("outcome_status")
    @classmethod
    def validate_outcome_status(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in {"OPEN", "TP", "SL", "EXPIRY", "AMBIGUOUS"}:
            raise ValueError(
                f"outcome_status must be in OPEN, TP, SL, EXPIRY, AMBIGUOUS, got '{v}'"
            )
        return clean

    @field_validator("entry_price")
    @classmethod
    def validate_entry_price(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"entry_price must be positive and finite, got {v}")
        return v

    @field_validator("exit_price")
    @classmethod
    def validate_exit_price(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"exit_price must be positive and finite, got {v}")
        return v

    @field_validator("realized_return", "mfe", "mae")
    @classmethod
    def validate_finite_return_metrics(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError(f"Metric must be a finite float, got {v}")
        return v

    @field_validator("holding_days")
    @classmethod
    def validate_holding_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"holding_days cannot be negative, got {v}")
        return v

    @field_validator("exit_reason")
    @classmethod
    def validate_exit_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip().upper()
        return clean if clean else None

    @model_validator(mode="after")
    def validate_outcome_lifecycle(self) -> "SignalOutcomeRecord":
        if self.entry_date < self.signal_date:
            raise ValueError(
                f"entry_date ({self.entry_date}) cannot precede signal_date ({self.signal_date})"
            )
        if self.outcome_status == "OPEN":
            if self.exit_price is not None:
                raise ValueError("Open outcome cannot have exit_price")
            if self.exit_date is not None:
                raise ValueError("Open outcome cannot have exit_date")
            if self.exit_reason is not None:
                raise ValueError("Open outcome cannot have exit_reason")
            if self.realized_return is not None:
                raise ValueError("Open outcome cannot have realized_return")
            if self.resolved_at is not None:
                raise ValueError("Open outcome cannot have resolved_at")
        else:
            if self.exit_price is None:
                raise ValueError(
                    f"Resolved outcome ({self.outcome_status}) must specify exit_price"
                )
            if self.exit_date is None:
                raise ValueError(
                    f"Resolved outcome ({self.outcome_status}) must specify exit_date"
                )
            if self.exit_date < self.entry_date:
                raise ValueError(
                    f"exit_date ({self.exit_date}) cannot precede entry_date ({self.entry_date})"
                )
            if self.realized_return is None:
                self.realized_return = (self.exit_price - self.entry_price) / self.entry_price
            if self.exit_reason is None:
                self.exit_reason = self.outcome_status
            if self.resolved_at is None:
                self.resolved_at = datetime.now(timezone.utc)
        return self


OutcomeRecord = SignalOutcomeRecord


class SignalDailySnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    snapshot_date: date
    holding_day: int
    close_price: float
    return_from_entry: float
    high_price: float
    low_price: float
    mfe_so_far: float
    mae_so_far: float

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("signal_id cannot be empty")
        return clean

    @field_validator("holding_day")
    @classmethod
    def validate_holding_day(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"holding_day cannot be negative, got {v}")
        return v

    @field_validator("close_price", "high_price", "low_price")
    @classmethod
    def validate_prices(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"Price must be positive and finite, got {v}")
        return v

    @field_validator("return_from_entry", "mfe_so_far", "mae_so_far")
    @classmethod
    def validate_finite_metrics(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Metric must be a finite float, got {v}")
        return v

    @model_validator(mode="after")
    def validate_candle_bounds(self) -> "SignalDailySnapshot":
        if self.high_price < self.low_price:
            raise ValueError(
                f"high_price ({self.high_price}) cannot be less than low_price ({self.low_price})"
            )
        return self


class TradingMetrics(BaseModel):
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_trades: int = 0
    tp_rate: float = 0.0
    sl_rate: float = 0.0
    expiry_rate: float = 0.0


class PredictionMetrics(BaseModel):
    brier_score: float = 0.0
    log_loss: float = 0.0
    roc_auc: float = 0.5
    ece: float = 0.0
    accuracy: float = 0.0


class CalibrationBin(BaseModel):
    bin_index: int
    lower_bound: float
    upper_bound: float
    sample_count: int
    mean_predicted: float
    observed_frequency: float
    gap: float


class EvaluationReport(BaseModel):
    model_version: str
    evaluation_date: date = Field(default_factory=date.today)
    dataset_version: str = "v1.0.0"
    sample_size: int = 0
    trading_metrics: TradingMetrics = Field(default_factory=TradingMetrics)
    prediction_metrics: PredictionMetrics = Field(default_factory=PredictionMetrics)
    calibration_bins: list[CalibrationBin] = Field(default_factory=list)
    status: str = "evaluated"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ComparisonRecommendation(str, Enum):
    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ComparisonReport(BaseModel):
    champion_version: str
    challenger_version: str
    test_window: Union[str, dict[str, Optional[str]]] = ""
    champion_metrics: EvaluationReport
    challenger_metrics: EvaluationReport
    delta_metrics: dict[str, float] = Field(default_factory=dict)
    recommendation: str = "INCONCLUSIVE"
    rationale: list[str] = Field(default_factory=list)

    @field_validator("recommendation")
    @classmethod
    def validate_recommendation(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ("PROMOTE", "REJECT", "INCONCLUSIVE"):
            raise ValueError(
                f"recommendation must be 'PROMOTE', 'REJECT', or 'INCONCLUSIVE', got '{v}'"
            )
        return clean

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


