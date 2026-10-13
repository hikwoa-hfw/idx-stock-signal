import math
from typing import Optional


def compute_returns(closes: list[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    for i in range(period, n):
        prev = closes[i - period]
        cur = closes[i]
        if prev > 0 and math.isfinite(prev) and math.isfinite(cur):
            result[i] = (cur - prev) / prev
    return result


def compute_ema(values: list[float], span: int) -> list[Optional[float]]:
    if span <= 0:
        raise ValueError(f"span must be positive, got {span}")
    n = len(values)
    result: list[Optional[float]] = [None] * n
    if n < span:
        return result

    alpha = 2.0 / (span + 1.0)
    sma_seed = sum(values[:span]) / float(span)
    result[span - 1] = sma_seed
    current_ema = sma_seed

    for i in range(span, n):
        current_ema = alpha * values[i] + (1.0 - alpha) * current_ema
        result[i] = current_ema

    return result


def compute_relative_distance(
    numerator: Optional[float], denominator: Optional[float]
) -> Optional[float]:
    if (
        numerator is None
        or denominator is None
        or denominator == 0
        or not math.isfinite(numerator)
        or not math.isfinite(denominator)
    ):
        return None
    return (numerator - denominator) / denominator


def compute_rsi(closes: list[float], period: int = 14) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)

    if avg_loss == 0.0:
        result[period] = 100.0 if avg_gain > 0.0 else 50.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)
        bar_idx = i + 1
        if avg_loss == 0.0:
            result[bar_idx] = 100.0 if avg_gain > 0.0 else 50.0
        else:
            rs = avg_gain / avg_loss
            result[bar_idx] = 100.0 - (100.0 / (1.0 + rs))

    return result


def compute_rsi_change(rsi_values: list[Optional[float]], period: int = 5) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    n = len(rsi_values)
    result: list[Optional[float]] = [None] * n
    for i in range(period, n):
        cur = rsi_values[i]
        prev = rsi_values[i - period]
        if cur is not None and prev is not None:
            result[i] = cur - prev
    return result


def compute_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs, lows, and closes must have identical length")
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result

    tr_list: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

    atr = sum(tr_list[:period]) / float(period)
    result[period - 1] = atr

    for i in range(period, n):
        atr = (atr * (period - 1) + tr_list[i]) / float(period)
        result[i] = atr

    return result


def compute_realized_vol(returns: list[Optional[float]], period: int) -> list[Optional[float]]:
    if period <= 1:
        raise ValueError(f"period must be at least 2 for sample stdev, got {period}")
    n = len(returns)
    result: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        window = returns[i - period + 1 : i + 1]
        if any(r is None for r in window):
            continue
        valid_vals = [float(r) for r in window if r is not None]
        mean = sum(valid_vals) / float(period)
        variance = sum((x - mean) ** 2 for x in valid_vals) / float(period - 1)
        result[i] = math.sqrt(variance)
    return result


def compute_rolling_mean_ratio(values: list[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    n = len(values)
    result: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        avg = sum(window) / float(period)
        if avg > 0:
            result[i] = values[i] / avg
        elif values[i] == 0:
            result[i] = 1.0
        else:
            result[i] = None
    return result


def compute_daily_range_pct(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[Optional[float]]:
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    for i in range(n):
        c = closes[i]
        h = highs[i]
        low_val = lows[i]
        if c > 0 and math.isfinite(c) and math.isfinite(h) and math.isfinite(low_val):
            result[i] = (h - low_val) / c
    return result
