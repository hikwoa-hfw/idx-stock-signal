from python.labels.repository import LabelRepository

try:
    from python.labels.engine import (
        DEFAULT_AMBIGUITY_POLICY,
        DEFAULT_MAX_HOLDING_DAYS,
        DEFAULT_SL_PCT,
        DEFAULT_TP_PCT,
        LABEL_VERSION,
        AmbiguityPolicy,
        LabelEngine,
        LabelOutcome,
    )
except ImportError:
    DEFAULT_AMBIGUITY_POLICY = None  # type: ignore[assignment]
    DEFAULT_MAX_HOLDING_DAYS = 10  # type: ignore[assignment]
    DEFAULT_SL_PCT = 0.05  # type: ignore[assignment]
    DEFAULT_TP_PCT = 0.05  # type: ignore[assignment]
    LABEL_VERSION = "v1"  # type: ignore[assignment]
    AmbiguityPolicy = None  # type: ignore[assignment]
    LabelEngine = None  # type: ignore[assignment]
    LabelOutcome = None  # type: ignore[assignment]

__all__ = [
    "DEFAULT_AMBIGUITY_POLICY",
    "DEFAULT_MAX_HOLDING_DAYS",
    "DEFAULT_SL_PCT",
    "DEFAULT_TP_PCT",
    "LABEL_VERSION",
    "AmbiguityPolicy",
    "LabelEngine",
    "LabelOutcome",
    "LabelRepository",
]
