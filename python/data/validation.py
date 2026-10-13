import math
from typing import Optional

from pydantic import BaseModel

from python.common.types import DailyBar


class DataValidationError(ValueError):
    pass


class ValidationReport(BaseModel):
    is_valid: bool
    total_bars: int
    error_count: int
    errors: list[str]


def _is_finite_number(val: Optional[float]) -> bool:
    if val is None:
        return False
    try:
        return not (math.isnan(val) or math.isinf(val))
    except (TypeError, ValueError):
        return False


def validate_bar(bar: DailyBar) -> list[str]:
    errors: list[str] = []
    ticker = (bar.ticker or "").strip()
    if not ticker:
        errors.append("ticker must not be empty")

    date_str = str(bar.date) if bar.date is not None else "null"
    if bar.date is None:
        errors.append(f"{ticker or 'unknown'}: date must not be null")

    prefix = f"{ticker or 'unknown'} on {date_str}"

    if not _is_finite_number(bar.open) or bar.open <= 0:
        errors.append(f"{prefix}: open must be > 0 (got {bar.open})")

    if not _is_finite_number(bar.close) or bar.close <= 0:
        errors.append(f"{prefix}: close must be > 0 (got {bar.close})")

    if not _is_finite_number(bar.high) or bar.high <= 0:
        errors.append(f"{prefix}: high must be > 0 (got {bar.high})")

    if not _is_finite_number(bar.low) or bar.low <= 0:
        errors.append(f"{prefix}: low must be <= min(open, close) and > 0 (got {bar.low})")

    has_valid_ohlc = (
        _is_finite_number(bar.open)
        and _is_finite_number(bar.high)
        and _is_finite_number(bar.low)
        and _is_finite_number(bar.close)
    )
    if has_valid_ohlc:
        expected_max = max(bar.open, bar.close)
        expected_min = min(bar.open, bar.close)
        if bar.high < expected_max:
            errors.append(
                f"{prefix}: high must be >= max(open, close) (high={bar.high}, max={expected_max})"
            )
        if bar.low > expected_min:
            errors.append(
                f"{prefix}: low must be <= min(open, close) and > 0 "
                f"(low={bar.low}, min={expected_min})"
            )
        if bar.high < bar.low:
            errors.append(f"{prefix}: high must be >= low (high={bar.high}, low={bar.low})")

    if not _is_finite_number(bar.volume) or bar.volume < 0:
        errors.append(f"{prefix}: volume must be >= 0 (got {bar.volume})")

    if bar.value is not None:
        if not _is_finite_number(bar.value) or bar.value < 0:
            errors.append(f"{prefix}: value must be >= 0 (got {bar.value})")

    if getattr(bar, "adj_close", None) is not None:
        if not _is_finite_number(bar.adj_close) or bar.adj_close <= 0:
            errors.append(f"{prefix}: adj_close must be > 0 and finite (got {bar.adj_close})")

    if getattr(bar, "dividends", None) is not None:
        if not _is_finite_number(bar.dividends) or bar.dividends < 0:
            errors.append(f"{prefix}: dividends must be >= 0 and finite (got {bar.dividends})")

    if getattr(bar, "stock_splits", None) is not None:
        if not _is_finite_number(bar.stock_splits) or bar.stock_splits < 0:
            errors.append(
                f"{prefix}: stock_splits must be >= 0 and finite (got {bar.stock_splits})"
            )

    return errors


def validate_daily_bars(
    bars: list[DailyBar],
    raise_on_error: bool = False,
) -> ValidationReport:
    errors: list[str] = []
    seen_ticker_dates: set[tuple[str, str]] = set()

    for bar in bars:
        if bar is None:
            errors.append("null bar encountered in dataset")
            continue

        bar_errors = validate_bar(bar)
        errors.extend(bar_errors)

        if bar.ticker and bar.date:
            canonical_ticker = bar.ticker.strip().upper().removesuffix(".JK")
            key = (canonical_ticker, str(bar.date))
            if key in seen_ticker_dates:
                errors.append(
                    f"duplicate date for ticker {bar.ticker}: {bar.date} appears multiple times"
                )
            else:
                seen_ticker_dates.add(key)

    is_valid = len(errors) == 0
    report = ValidationReport(
        is_valid=is_valid,
        total_bars=len(bars),
        error_count=len(errors),
        errors=errors,
    )

    if raise_on_error and not is_valid:
        preview = "; ".join(errors[:3])
        if len(errors) > 3:
            preview += f" ... ({len(errors) - 3} more)"
        raise DataValidationError(f"Data validation failed ({len(errors)} error(s)): {preview}")

    return report
