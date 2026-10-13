from datetime import date
from typing import Optional, Union

import numpy as np
import pandas as pd

from python.data.repository import DailyBarRepository
from python.features.repository import FeatureRepository
from python.labels.repository import LabelRepository
from python.models.dataset import DEFAULT_FEATURE_COLUMNS, Dataset, DatasetBuilder
from python.models.validation import split_chronological
from python.outcomes.dataset import build_matured_outcomes_dataset
from python.outcomes.repository import OutcomeRepository
from python.signals.repository import SignalRepository


class RetrainingDatasetAssembler:
    """Assembles unified retraining datasets from historical features/labels and matured outcomes,

    enforcing strict chronological walk-forward purge windows to eliminate data leakage.
    """

    def __init__(
        self,
        feature_cols: Optional[list[str]] = None,
        exclude_ambiguous: bool = True,
        purge_days: int = 10,
        outcome_repo: Optional[OutcomeRepository] = None,
        signal_repo: Optional[SignalRepository] = None,
        feature_repo: Optional[FeatureRepository] = None,
        label_repo: Optional[LabelRepository] = None,
        bar_repo: Optional[DailyBarRepository] = None,
    ) -> None:
        self.feature_cols = list(feature_cols or DEFAULT_FEATURE_COLUMNS)
        self.exclude_ambiguous = exclude_ambiguous
        self.purge_days = purge_days
        self.outcome_repo = outcome_repo or OutcomeRepository()
        self.signal_repo = signal_repo or SignalRepository()
        self.feature_repo = feature_repo or FeatureRepository()
        self.label_repo = label_repo or LabelRepository()
        self.bar_repo = bar_repo or DailyBarRepository()
        self.builder = DatasetBuilder(
            feature_cols=self.feature_cols,
            exclude_ambiguous=self.exclude_ambiguous,
            drop_na=False,
            impute_strategy="median",
        )

    def assemble_from_dfs(
        self,
        historical_df: pd.DataFrame,
        outcomes_df: pd.DataFrame,
        feature_cols: Optional[list[str]] = None,
    ) -> Dataset:
        """Merge historical training records and matured outcomes dataframes."""
        cols = list(feature_cols or self.feature_cols)
        builder = DatasetBuilder(
            feature_cols=cols,
            exclude_ambiguous=self.exclude_ambiguous,
            impute_strategy="median",
        )

        h_df = historical_df.copy() if not historical_df.empty else pd.DataFrame()
        o_df = outcomes_df.copy() if not outcomes_df.empty else pd.DataFrame()

        if h_df.empty and o_df.empty:
            return builder._empty_dataset()

        # Standardize historical columns
        if not h_df.empty:
            h_df["ticker"] = (
                h_df["ticker"].astype(str).str.strip().str.upper().str.removesuffix(".JK")
            )
            h_df["date"] = pd.to_datetime(h_df["date"]).dt.date
            if self.exclude_ambiguous and "outcome_status" in h_df.columns:
                h_df = h_df[h_df["outcome_status"].str.upper() != "AMBIGUOUS"]
            elif self.exclude_ambiguous and "outcome" in h_df.columns:
                h_df = h_df[h_df["outcome"].str.upper() != "AMBIGUOUS"]

        # Standardize outcome columns
        if not o_df.empty:
            o_df["ticker"] = (
                o_df["ticker"].astype(str).str.strip().str.upper().str.removesuffix(".JK")
            )
            # Map signal_date to date
            date_col = "signal_date" if "signal_date" in o_df.columns else "date"
            o_df["date"] = pd.to_datetime(o_df[date_col]).dt.date
            if self.exclude_ambiguous and "outcome_status" in o_df.columns:
                o_df = o_df[o_df["outcome_status"].str.upper() != "AMBIGUOUS"]

        # If one is empty, return the other directly formatted
        if h_df.empty:
            merged = o_df.copy()
        elif o_df.empty:
            merged = h_df.copy()
        else:
            # Combine: outcomes take precedence over historical labels for identical (ticker, date)
            # Put outcomes at end, then drop duplicates keep='last'
            combined = pd.concat([h_df, o_df], ignore_index=True)
            merged = combined.drop_duplicates(subset=["ticker", "date"], keep="last")

        # Sort chronologically strictly by date, then ticker
        merged = merged.sort_values(by=["date", "ticker"]).reset_index(drop=True)

        # Target filtering
        valid_targets = merged["binary_target"].notna() & merged["realized_return"].notna()
        merged = merged[valid_targets].reset_index(drop=True)
        if merged.empty:
            return builder._empty_dataset()

        # Impute missing feature columns
        for c in cols:
            if c not in merged.columns:
                merged[c] = np.nan
            med = merged[c].median()
            merged[c] = merged[c].fillna(0.0 if pd.isna(med) else float(med))

        X = merged[cols].to_numpy(dtype=np.float64)
        y = merged["binary_target"].to_numpy(dtype=np.int64)
        y_return = merged["realized_return"].to_numpy(dtype=np.float64)
        dates = merged["date"].to_numpy(dtype="object")
        tickers = merged["ticker"].to_numpy(dtype="object")

        return Dataset(
            X=X,
            y=y,
            y_return=y_return,
            dates=dates,
            tickers=tickers,
            feature_names=cols,
            metadata=merged,
        )

    def assemble_dataset(
        self,
        base_dataset: Optional[Dataset] = None,
        since_date: Optional[Union[date, str]] = None,
        tickers: Optional[list[str]] = None,
    ) -> Dataset:
        """Assembles dataset from database repositories and latest matured outcomes."""
        # 1. Base dataset from DB or provided
        hist_df = pd.DataFrame()
        if base_dataset is not None:
            hist_df = base_dataset.metadata.copy()
        else:
            try:
                base_ds = self.builder.build_from_db(
                    feature_repo=self.feature_repo,
                    label_repo=self.label_repo,
                    tickers=tickers,
                )
                if len(base_ds) > 0:
                    hist_df = base_ds.metadata.copy()
            except Exception:
                hist_df = pd.DataFrame()

        # 2. Matured outcomes from repository
        s_date = (
            date.fromisoformat(since_date)
            if isinstance(since_date, str)
            else since_date
        )
        outcomes_df = build_matured_outcomes_dataset(
            outcome_repo=self.outcome_repo,
            signal_repo=self.signal_repo,
            start_date=s_date,
            exclude_ambiguous=self.exclude_ambiguous,
        )

        return self.assemble_from_dfs(hist_df, outcomes_df)

    def split_walk_forward(
        self,
        dataset: Dataset,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        purge_days: Optional[int] = None,
    ) -> tuple[Dataset, Optional[Dataset], Dataset]:
        """Chronologically split dataset with purge window to prevent label lookahead leakage."""
        p_days = purge_days if purge_days is not None else self.purge_days
        train_idx, val_idx, test_idx = split_chronological(
            dates=dataset.dates,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            purge_days=p_days,
        )

        train_ds = dataset.select_indices(train_idx)
        val_ds = dataset.select_indices(val_idx) if len(val_idx) > 0 else None
        test_ds = dataset.select_indices(test_idx)

        return train_ds, val_ds, test_ds
