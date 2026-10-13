from python.common.types import FeatureRecord
from python.features.repository import FeatureRepository

try:
    from python.features.engine import FEATURE_VERSION, FeatureEngine
    from python.features.indicators import (
        compute_atr,
        compute_daily_range_pct,
        compute_ema,
        compute_realized_vol,
        compute_relative_distance,
        compute_returns,
        compute_rolling_mean_ratio,
        compute_rsi,
        compute_rsi_change,
    )
except ImportError:
    FEATURE_VERSION = "v1"  # type: ignore[assignment]
    FeatureEngine = None  # type: ignore[assignment]
    compute_atr = None  # type: ignore[assignment]
    compute_daily_range_pct = None  # type: ignore[assignment]
    compute_ema = None  # type: ignore[assignment]
    compute_realized_vol = None  # type: ignore[assignment]
    compute_relative_distance = None  # type: ignore[assignment]
    compute_returns = None  # type: ignore[assignment]
    compute_rolling_mean_ratio = None  # type: ignore[assignment]
    compute_rsi = None  # type: ignore[assignment]
    compute_rsi_change = None  # type: ignore[assignment]

__all__ = [
    "FEATURE_VERSION",
    "FeatureEngine",
    "FeatureRecord",
    "FeatureRepository",
    "compute_atr",
    "compute_daily_range_pct",
    "compute_ema",
    "compute_realized_vol",
    "compute_relative_distance",
    "compute_returns",
    "compute_rolling_mean_ratio",
    "compute_rsi",
    "compute_rsi_change",
]
