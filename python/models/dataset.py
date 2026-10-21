from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence, Union

import numpy as np
import pandas as pd

from python.common.types import FeatureRecord, LabelRecord, classify_price_mode
from python.features.repository import FeatureRepository
from python.labels.repository import LabelRepository

DEFAULT_FEATURE_COLUMNS: list[str] = [
    # Momentum
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    # Trend
    "ema20",
    "ema50",
    "ema200",
    "close_vs_ema20",
    "close_vs_ema50",
    "ema20_vs_ema50",
    "ema50_vs_ema200",
    # RSI
    "rsi14",
    "rsi_change_5d",
    # Volatility
    "atr14",
    "atr_pct",
    "realized_vol_5d",
    "realized_vol_20d",
    "daily_range_pct",
    # Volume
    "volume_ratio_5d",
    "volume_ratio_20d",
    "value_ratio_20d",
    # Relative Strength
    "rel_strength_ihsg_20d",
    "rel_strength_sector_20d",
    # Market Regime
    "ihsg_return_5d",
    "ihsg_return_20d",
    "ihsg_vs_ema20",
    "ihsg_vs_ema50",
    "market_breadth",
    "market_volatility",
]


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    y_return: np.ndarray
    dates: np.ndarray
    tickers: np.ndarray
    feature_names: list[str]
    metadata: pd.DataFrame
    mode_id: Optional[str] = None

    def __len__(self) -> int:
        return len(self.y)

    def select_indices(self, indices: Union[np.ndarray, Sequence[int]]) -> "Dataset":
        idx = np.asarray(indices, dtype=np.int64)
        if len(idx) == 0:
            return Dataset(
                X=np.empty((0, len(self.feature_names)), dtype=np.float64),
                y=np.empty((0,), dtype=np.int64),
                y_return=np.empty((0,), dtype=np.float64),
                dates=np.empty((0,), dtype="object"),
                tickers=np.empty((0,), dtype="object"),
                feature_names=list(self.feature_names),
                metadata=self.metadata.iloc[0:0].copy().reset_index(drop=True),
                mode_id=self.mode_id,
            )

        return Dataset(
            X=self.X[idx],
            y=self.y[idx],
            y_return=self.y_return[idx],
            dates=self.dates[idx],
            tickers=self.tickers[idx],
            feature_names=list(self.feature_names),
            metadata=self.metadata.iloc[idx].copy().reset_index(drop=True),
            mode_id=self.mode_id,
        )

    def filter_by_date_range(
        self,
        start_date: Optional[Union[date, str]] = None,
        end_date: Optional[Union[date, str]] = None,
    ) -> "Dataset":
        mask = np.ones(len(self), dtype=bool)
        if start_date is not None:
            s_d = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            mask &= self.dates >= s_d
        if end_date is not None:
            e_d = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            mask &= self.dates <= e_d
        indices = np.where(mask)[0]
        return self.select_indices(indices)

    def filter_by_mode(self, mode: str) -> "Dataset":
        """Filter dataset samples strictly to a specific price mode."""
        if self.metadata.empty or "mode" not in self.metadata.columns:
            return self
        target_mode = mode.strip().upper()
        mask = self.metadata["mode"].astype(str).str.upper() == target_mode
        indices = np.where(mask)[0]
        res = self.select_indices(indices)
        res.mode_id = target_mode
        return res

    def get_summary(self) -> dict[str, Any]:
        """Provides report on sample count, class balance, dates, and ticker coverage."""
        total = len(self)
        if total == 0:
            return {
                "total_samples": 0,
                "positive_samples": 0,
                "negative_samples": 0,
                "class_balance_ratio": 0.0,
                "unique_tickers": 0,
                "date_min": None,
                "date_max": None,
                "mode": self.mode_id,
            }
        pos = int(np.sum(self.y == 1))
        neg = int(np.sum(self.y == 0))
        ratio = float(pos / total) if total > 0 else 0.0
        mode_counts = {}
        if not self.metadata.empty and "mode" in self.metadata.columns:
            mode_counts = self.metadata["mode"].value_counts().to_dict()
        return {
            "total_samples": total,
            "positive_samples": pos,
            "negative_samples": neg,
            "class_balance_ratio": round(ratio, 4),
            "unique_tickers": len(set(self.tickers)),
            "date_min": str(min(self.dates)),
            "date_max": str(max(self.dates)),
            "mode": self.mode_id,
            "mode_counts": mode_counts,
        }


class DatasetBuilder:
    """Builds clean numerical feature and target matrices for model training."""

    def __init__(
        self,
        feature_cols: Optional[list[str]] = None,
        exclude_ambiguous: bool = True,
        drop_na: bool = False,
        impute_strategy: Optional[str] = "median",
        mode: Optional[str] = None,
    ) -> None:
        self.feature_cols = feature_cols or list(DEFAULT_FEATURE_COLUMNS)
        self.exclude_ambiguous = exclude_ambiguous
        self.drop_na = drop_na
        self.impute_strategy = impute_strategy
        self.mode = mode

    def build_from_records(
        self,
        features: list[FeatureRecord],
        labels: list[LabelRecord],
        mode: Optional[str] = None,
    ) -> Dataset:
        if not features or not labels:
            return self._empty_dataset(mode_id=mode or self.mode)

        feat_rows = []
        for f in features:
            d = f.model_dump()
            d["ticker"] = f.ticker.strip().upper().removesuffix(".JK")
            feat_rows.append(d)
        feat_df = pd.DataFrame(feat_rows)

        lbl_rows = []
        for lbl in labels:
            d = lbl.model_dump()
            d["ticker"] = lbl.ticker.strip().upper().removesuffix(".JK")
            lbl_rows.append(d)
        lbl_df = pd.DataFrame(lbl_rows)

        return self.build_from_dfs(feat_df, lbl_df, mode=mode)

    def build_from_dfs(
        self,
        features_df: pd.DataFrame,
        labels_df: pd.DataFrame,
        mode: Optional[str] = None,
    ) -> Dataset:
        eff_mode = mode or self.mode
        if eff_mode:
            eff_mode = eff_mode.strip().upper()

        if features_df.empty or labels_df.empty:
            return self._empty_dataset(mode_id=eff_mode)

        feat = features_df.copy()
        lbl = labels_df.copy()

        feat["ticker"] = feat["ticker"].astype(str).str.strip().str.upper().str.removesuffix(".JK")
        lbl["ticker"] = lbl["ticker"].astype(str).str.strip().str.upper().str.removesuffix(".JK")

        # Normalize date to string or date
        feat["date"] = pd.to_datetime(feat["date"]).dt.date
        lbl["date"] = pd.to_datetime(lbl["date"]).dt.date

        if self.exclude_ambiguous and "outcome" in lbl.columns:
            lbl = lbl[lbl["outcome"].str.upper() != "AMBIGUOUS"]

        # Drop duplicate keys keeping first
        feat = feat.drop_duplicates(subset=["ticker", "date"])
        lbl = lbl.drop_duplicates(subset=["ticker", "date"])

        merged = pd.merge(
            feat,
            lbl,
            on=["ticker", "date"],
            how="inner",
            suffixes=("", "_label"),
        )

        if merged.empty:
            return self._empty_dataset(mode_id=eff_mode)

        # Assign historical price mode based on decision entry price
        if "entry_price_label" in merged.columns and merged["entry_price_label"].notna().any():
            merged["entry_price"] = merged["entry_price_label"]

        if "entry_price" in merged.columns and merged["entry_price"].notna().any():
            merged["mode"] = merged["entry_price"].apply(classify_price_mode)
        elif "mode_label" in merged.columns and merged["mode_label"].notna().any():
            merged["mode"] = merged["mode_label"]
        elif "mode" not in merged.columns:
            merged["mode"] = "INVALID"

        # Filter by mode if requested
        if eff_mode and eff_mode not in ("ALL", "*"):
            merged = merged[merged["mode"] == eff_mode].reset_index(drop=True)

        if merged.empty:
            return self._empty_dataset(mode_id=eff_mode)

        # Sort chronologically by date, then ticker
        merged = merged.sort_values(by=["date", "ticker"]).reset_index(drop=True)

        # Target filtering
        valid_targets = merged["binary_target"].notna() & merged["realized_return"].notna()
        merged = merged[valid_targets].reset_index(drop=True)
        if merged.empty:
            return self._empty_dataset(mode_id=eff_mode)

        for col in self.feature_cols:
            if col not in merged.columns:
                merged[col] = np.nan

        if self.drop_na:
            valid_mask = merged[self.feature_cols].notna().all(axis=1)
            merged = merged[valid_mask].reset_index(drop=True)
            if merged.empty:
                return self._empty_dataset(mode_id=eff_mode)

        if self.impute_strategy == "median":
            for col in self.feature_cols:
                med = merged[col].median()
                merged[col] = merged[col].fillna(0.0 if pd.isna(med) else float(med))
        elif self.impute_strategy == "mean":
            for col in self.feature_cols:
                avg = merged[col].mean()
                merged[col] = merged[col].fillna(0.0 if pd.isna(avg) else float(avg))
        elif self.impute_strategy == "zero":
            merged[self.feature_cols] = merged[self.feature_cols].fillna(0.0)

        X = merged[self.feature_cols].to_numpy(dtype=np.float64)
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
            feature_names=list(self.feature_cols),
            metadata=merged,
            mode_id=eff_mode,
        )

    def build_from_db(
        self,
        feature_repo: FeatureRepository,
        label_repo: LabelRepository,
        tickers: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        feature_version: Optional[str] = None,
        label_version: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dataset:
        features = feature_repo.get_feature_matrix(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            feature_version=feature_version,
        )
        labels = label_repo.get_all_labels(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            label_version=label_version,
        )
        return self.build_from_records(features, labels, mode=mode)

    def build_dataset(
        self,
        mode: str,
        features: Optional[list[FeatureRecord]] = None,
        labels: Optional[list[LabelRecord]] = None,
        feature_repo: Optional[FeatureRepository] = None,
        label_repo: Optional[LabelRepository] = None,
        **kwargs: Any,
    ) -> Dataset:
        """Build mode-specific dataset ('LOW_PRICE' or 'HIGHER_PRICE')."""
        if features is not None and labels is not None:
            return self.build_from_records(features=features, labels=labels, mode=mode)
        if feature_repo is not None and label_repo is not None:
            return self.build_from_db(
                feature_repo=feature_repo, label_repo=label_repo, mode=mode, **kwargs
            )
        raise ValueError("Must provide either (features, labels) or (feature_repo, label_repo)")

    def _empty_dataset(self, mode_id: Optional[str] = None) -> Dataset:
        return Dataset(
            X=np.empty((0, len(self.feature_cols)), dtype=np.float64),
            y=np.empty((0,), dtype=np.int64),
            y_return=np.empty((0,), dtype=np.float64),
            dates=np.empty((0,), dtype="object"),
            tickers=np.empty((0,), dtype="object"),
            feature_names=list(self.feature_cols),
            metadata=pd.DataFrame(),
            mode_id=mode_id,
        )
