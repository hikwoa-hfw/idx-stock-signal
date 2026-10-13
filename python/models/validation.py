from datetime import date
from typing import Generator, Optional, Sequence, Union

import numpy as np


def _to_date_array(dates: Sequence[Union[date, str]]) -> np.ndarray:
    if len(dates) == 0:
        return np.array([], dtype="object")
    converted = []
    for d in dates:
        if isinstance(d, str):
            converted.append(date.fromisoformat(d.strip()))
        elif isinstance(d, date):
            converted.append(d)
        else:
            raise TypeError(f"Expected date or ISO date string, got {type(d)}: {d}")
    return np.array(converted, dtype="object")


def split_chronological(
    dates: Sequence[Union[date, str]],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    purge_days: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split row indices into strictly chronological train, val, and test partitions.

    Guarantees:
    - Train dates strictly precede validation dates.
    - Validation dates strictly precede test dates.
    - No future data leakage into training/validation.
    - Optional purge window between partitions to eliminate target overlap.

    Parameters
    ----------
    dates: Sequence of date instances or ISO string dates corresponding to each sample row.
    train_ratio: Fraction of unique calendar/trading dates allocated to training.
    val_ratio: Fraction of unique calendar/trading dates allocated to validation.
    test_ratio: Fraction of unique calendar/trading dates allocated to testing.
    purge_days: Number of unique trading dates to discard at the boundary of train (and val) sets.

    Returns
    -------
    (train_indices, val_indices, test_indices) as 1D numpy arrays of integer row indices.
    """
    total_ratio = train_ratio + val_ratio + test_ratio
    if total_ratio > 1.0 + 1e-6:
        raise ValueError(
            f"Sum of ratios ({train_ratio}+{val_ratio}+{test_ratio}={total_ratio}) exceeds 1.0"
        )
    if train_ratio <= 0:
        raise ValueError(f"train_ratio must be positive, got {train_ratio}")
    if val_ratio < 0:
        raise ValueError(f"val_ratio must be non-negative, got {val_ratio}")
    if test_ratio < 0:
        raise ValueError(f"test_ratio must be non-negative, got {test_ratio}")
    if purge_days < 0:
        raise ValueError(f"purge_days must be non-negative, got {purge_days}")

    dates_arr = _to_date_array(dates)
    if len(dates_arr) == 0:
        empty = np.array([], dtype=np.int64)
        return empty, empty, empty

    unique_dates = np.unique(dates_arr)
    unique_dates = np.sort(unique_dates)
    n_unique = len(unique_dates)

    if n_unique < 2:
        raise ValueError(f"Need at least 2 distinct dates for chronological split, got {n_unique}")

    n_train = max(1, int(round(n_unique * train_ratio)))
    n_val = int(round(n_unique * val_ratio))
    n_test = n_unique - n_train - n_val

    if n_test <= 0:
        if n_val > 0:
            n_val -= 1
            n_test = 1
        elif n_train > 1:
            n_train -= 1
            n_test = 1

    train_dates_raw = unique_dates[:n_train]
    val_dates_raw = unique_dates[n_train : n_train + n_val] if n_val > 0 else np.array([])
    test_dates_raw = unique_dates[n_train + n_val :]

    if purge_days > 0:
        if len(train_dates_raw) > purge_days:
            train_dates = train_dates_raw[:-purge_days]
        else:
            raise ValueError(
                f"purge_days={purge_days} exceeds train date count={len(train_dates_raw)}"
            )

        if len(val_dates_raw) > purge_days:
            val_dates = val_dates_raw[:-purge_days]
        elif len(val_dates_raw) > 0:
            val_dates = np.array([])
        else:
            val_dates = val_dates_raw
    else:
        train_dates = train_dates_raw
        val_dates = val_dates_raw

    test_dates = test_dates_raw

    # Strict chronological assertions
    if len(train_dates) > 0 and len(val_dates) > 0:
        assert max(train_dates) < min(val_dates), "Leakage detected: train overlaps validation"
    if len(val_dates) > 0 and len(test_dates) > 0:
        assert max(val_dates) < min(test_dates), "Leakage detected: validation overlaps test"
    if len(train_dates) > 0 and len(test_dates) > 0:
        assert max(train_dates) < min(test_dates), "Leakage detected: train overlaps test"

    train_idx = np.where(np.isin(dates_arr, train_dates))[0]
    val_idx = np.where(np.isin(dates_arr, val_dates))[0]
    test_idx = np.where(np.isin(dates_arr, test_dates))[0]

    return train_idx, val_idx, test_idx


def split_by_dates(
    dates: Sequence[Union[date, str]],
    train_end: Union[date, str],
    val_end: Optional[Union[date, str]] = None,
    purge_days: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split indices by explicit cutoff dates with purge window.

    Train: date <= train_end (excluding trailing purge_days dates)
    Val (if val_end): train_end < date <= val_end (excluding trailing purge_days dates)
    Test: date > val_end (or date > train_end if val_end is None)
    """
    dates_arr = _to_date_array(dates)
    if len(dates_arr) == 0:
        empty = np.array([], dtype=np.int64)
        return empty, empty, empty

    t_end = date.fromisoformat(train_end) if isinstance(train_end, str) else train_end
    v_end = date.fromisoformat(val_end) if isinstance(val_end, str) else val_end

    unique_dates = np.sort(np.unique(dates_arr))
    train_dates_raw = unique_dates[unique_dates <= t_end]

    if purge_days > 0 and len(train_dates_raw) > purge_days:
        train_dates = train_dates_raw[:-purge_days]
    elif purge_days > 0 and len(train_dates_raw) <= purge_days:
        raise ValueError(
            f"purge_days={purge_days} eliminates all train dates (count={len(train_dates_raw)})"
        )
    else:
        train_dates = train_dates_raw

    if v_end is not None:
        if v_end <= t_end:
            raise ValueError(f"val_end ({v_end}) must be strictly after train_end ({t_end})")
        val_dates_raw = unique_dates[(unique_dates > t_end) & (unique_dates <= v_end)]
        if purge_days > 0 and len(val_dates_raw) > purge_days:
            val_dates = val_dates_raw[:-purge_days]
        elif purge_days > 0 and len(val_dates_raw) <= purge_days:
            val_dates = np.array([])
        else:
            val_dates = val_dates_raw
        test_dates = unique_dates[unique_dates > v_end]
    else:
        val_dates = np.array([])
        test_dates = unique_dates[unique_dates > t_end]

    # Chronological safety checks
    if len(train_dates) > 0 and len(val_dates) > 0:
        assert max(train_dates) < min(val_dates), "Train dates must strictly precede validation"
    if len(val_dates) > 0 and len(test_dates) > 0:
        assert max(val_dates) < min(test_dates), "Validation dates must strictly precede test"
    if len(train_dates) > 0 and len(test_dates) > 0:
        assert max(train_dates) < min(test_dates), "Train dates must strictly precede test"

    train_idx = np.where(np.isin(dates_arr, train_dates))[0]
    val_idx = np.where(np.isin(dates_arr, val_dates))[0]
    test_idx = np.where(np.isin(dates_arr, test_dates))[0]

    return train_idx, val_idx, test_idx


class WalkForwardSplitter:
    """Walk-forward rolling or expanding time-series split generator with purge window."""

    def __init__(
        self,
        n_splits: int = 3,
        train_days: Optional[int] = None,
        test_days: Optional[int] = None,
        purge_days: int = 10,
        expanding: bool = False,
    ) -> None:
        if n_splits < 1:
            raise ValueError(f"n_splits must be at least 1, got {n_splits}")
        if purge_days < 0:
            raise ValueError(f"purge_days must be non-negative, got {purge_days}")
        self.n_splits = n_splits
        self.train_days = train_days
        self.test_days = test_days
        self.purge_days = purge_days
        self.expanding = expanding

    def split(
        self, dates: Sequence[Union[date, str]]
    ) -> Generator[tuple[np.ndarray, np.ndarray], None, None]:
        dates_arr = _to_date_array(dates)
        if len(dates_arr) == 0:
            return

        unique_dates = np.sort(np.unique(dates_arr))
        n_unique = len(unique_dates)

        test_span = self.test_days
        if test_span is None:
            # allocate equal test slices
            test_span = max(1, (n_unique - self.purge_days) // (self.n_splits + 1))

        min_train = self.train_days if (self.train_days is not None and not self.expanding) else 2
        min_required = test_span * self.n_splits + self.purge_days + min_train
        if n_unique < min_required:
            raise ValueError(
                f"Need at least {min_required} unique dates for {self.n_splits} splits, "
                f"but only found {n_unique}"
            )

        for i in range(self.n_splits):
            test_start_idx = n_unique - (self.n_splits - i) * test_span
            test_end_idx = test_start_idx + test_span

            purged_train_end_idx = test_start_idx - self.purge_days
            if purged_train_end_idx <= 0:
                raise ValueError(
                    f"Purge window {self.purge_days} eliminated all training dates for fold {i + 1}"
                )

            if self.expanding:
                train_start_idx = 0
            else:
                window_size = self.train_days if self.train_days is not None else test_span * 2
                train_start_idx = max(0, purged_train_end_idx - window_size)

            if purged_train_end_idx <= train_start_idx:
                raise ValueError(
                    f"Purge window {self.purge_days} eliminated all training dates for fold {i + 1}"
                )

            fold_train_dates = unique_dates[train_start_idx:purged_train_end_idx]
            fold_test_dates = unique_dates[test_start_idx:test_end_idx]

            assert max(fold_train_dates) < min(fold_test_dates), (
                f"Train dates overlap test in fold {i + 1}"
            )

            train_idx = np.where(np.isin(dates_arr, fold_train_dates))[0]
            test_idx = np.where(np.isin(dates_arr, fold_test_dates))[0]

            yield train_idx, test_idx
