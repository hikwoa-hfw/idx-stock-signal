from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SignalAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class OutcomeStatus(str, Enum):
    PENDING = "PENDING"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"


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


class Prediction(BaseModel):
    ticker: str
    prediction_date: date
    model_version: str
    probability: float
    expected_return: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
