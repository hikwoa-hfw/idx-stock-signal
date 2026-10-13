import math
import uuid
from datetime import date
from typing import Any, Optional, Sequence

import numpy as np

from python.common.types import DailyBar, FeatureRecord, SignalConfig, SignalRecord
from python.config.settings import settings
from python.data.provider import load_universe
from python.data.repository import DailyBarRepository
from python.features.engine import FeatureEngine
from python.models.dataset import DEFAULT_FEATURE_COLUMNS
from python.models.registry import ModelRegistry


class SignalEngine:
    """Production daily signal generation engine for BEI stocks."""

    def __init__(
        self,
        config: Optional[SignalConfig] = None,
        feature_engine: Optional[FeatureEngine] = None,
        model_registry: Optional[ModelRegistry] = None,
        bar_repo: Optional[DailyBarRepository] = None,
    ) -> None:
        self.config = config or SignalConfig()
        self.feature_engine = feature_engine or FeatureEngine()
        self.model_registry = model_registry or ModelRegistry()
        self.bar_repo = bar_repo

    def _get_bar_repo(self) -> DailyBarRepository:
        if self.bar_repo is None:
            self.bar_repo = DailyBarRepository(settings.database_url)
        return self.bar_repo

    def _predict_prob(self, classifier: Any, X: Sequence[Sequence[Any]]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if hasattr(classifier, "predict_probability"):
            return np.asarray(classifier.predict_probability(X_arr), dtype=np.float64)
        if hasattr(classifier, "predict_proba"):
            proba = classifier.predict_proba(X_arr)
            if proba.ndim == 2 and proba.shape[1] >= 2:
                return np.asarray(proba[:, 1], dtype=np.float64)
            return np.asarray(proba.ravel(), dtype=np.float64)
        if hasattr(classifier, "predict"):
            preds = classifier.predict(X_arr)
            return np.asarray(preds, dtype=np.float64)
        raise AttributeError(
            "Classifier has no predict_probability, predict_proba, or predict method"
        )

    def _predict_reg(self, regressor: Any, X: Sequence[Sequence[Any]]) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if hasattr(regressor, "predict_expected_return"):
            return np.asarray(regressor.predict_expected_return(X_arr), dtype=np.float64)
        if hasattr(regressor, "predict"):
            preds = regressor.predict(X_arr)
            return np.asarray(preds, dtype=np.float64)
        raise AttributeError("Regressor has no predict_expected_return or predict method")

    def calculate_composite_score(
        self,
        prob: float,
        expected_return: Optional[float],
        feat_rec: FeatureRecord,
        config: SignalConfig,
    ) -> float:
        """Calculate weighted composite score in range [0.0, 100.0]."""
        prob_score = float(np.clip(prob * 100.0, 0.0, 100.0))

        if expected_return is not None and math.isfinite(expected_return):
            # Scale expected return: -5% -> 0.0, +15% -> 100.0
            return_score = float(np.clip(((expected_return + 0.05) / 0.20) * 100.0, 0.0, 100.0))
        else:
            return_score = prob_score

        if feat_rec.volume_ratio_20d is not None and math.isfinite(feat_rec.volume_ratio_20d):
            # 1.0 ratio -> 50.0, 2.0 ratio -> 100.0
            liquidity_score = float(np.clip(feat_rec.volume_ratio_20d * 50.0, 0.0, 100.0))
        else:
            liquidity_score = 50.0

        if feat_rec.market_breadth is not None and math.isfinite(feat_rec.market_breadth):
            regime_score = float(np.clip(feat_rec.market_breadth * 100.0, 0.0, 100.0))
        else:
            regime_score = 50.0

        if feat_rec.atr_pct is not None and math.isfinite(feat_rec.atr_pct):
            # Lower volatility -> higher risk-adjusted score (0% ATR -> 100, 10% ATR -> 0)
            risk_score = float(np.clip((1.0 - (feat_rec.atr_pct / 0.10)) * 100.0, 0.0, 100.0))
        else:
            risk_score = 50.0

        comp_map = {
            "probability": prob_score,
            "return": return_score,
            "liquidity": liquidity_score,
            "regime": regime_score,
            "risk": risk_score,
        }

        weights = config.weights
        active_weights = {k: float(w) for k, w in weights.items() if k in comp_map and w > 0}
        total_w = sum(active_weights.values())

        if total_w > 0:
            raw_score = sum(w * comp_map[k] for k, w in active_weights.items()) / total_w
        else:
            raw_score = prob_score

        return round(float(np.clip(raw_score, 0.0, 100.0)), 2)

    def generate_signals(
        self,
        signal_date: Optional[date] = None,
        universe: Optional[list[str]] = None,
        classifier: Optional[Any] = None,
        regressor: Optional[Any] = None,
        model_version: Optional[str] = None,
        use_champion: bool = False,
        bars_by_ticker: Optional[dict[str, list[DailyBar]]] = None,
        features_by_ticker: Optional[dict[str, list[FeatureRecord]]] = None,
        config: Optional[SignalConfig] = None,
        min_history_bars: int = 20,
    ) -> list[SignalRecord]:
        """Generate ranked signals for a given trading date."""
        cfg = config or self.config

        # 1. Gather bars
        raw_bars_map: dict[str, list[DailyBar]] = {}
        if bars_by_ticker is not None:
            raw_bars_map = {
                t.strip().upper().removesuffix(".JK"): list(b_list)
                for t, b_list in bars_by_ticker.items()
            }
        else:
            repo = self._get_bar_repo()
            target_universe = universe or repo.get_universe() or load_universe()
            for t in target_universe:
                clean = t.strip().upper().removesuffix(".JK")
                bars = repo.get_daily_bars(clean)
                if bars:
                    raw_bars_map[clean] = bars

        if not raw_bars_map:
            raise ValueError("No market data bars available to generate signals.")

        # 2. Determine target trading date & check validity
        all_dates = {b.date for bars in raw_bars_map.values() for b in bars}
        if not all_dates:
            raise ValueError("No valid bar dates found in market data.")

        if signal_date is not None and signal_date not in all_dates:
            raise ValueError(
                f"Signal date {signal_date} is not a completed trading date in market data."
            )

        target_date = signal_date or max(all_dates)

        # 3. Filter bars strictly up to target_date (Strictly Causal / No Lookahead)
        filtered_bars: dict[str, list[DailyBar]] = {}
        eligible_tickers: list[str] = []

        for ticker, bars in raw_bars_map.items():
            past_bars = [b for b in bars if b.date <= target_date]
            past_bars.sort(key=lambda x: x.date)

            # Check eligibility:
            # - has bar on target_date
            # - has at least min_history_bars
            # - target_date bar has valid prices
            if not past_bars or past_bars[-1].date != target_date:
                continue
            if len(past_bars) < min_history_bars:
                continue

            last_bar = past_bars[-1]
            if last_bar.close <= 0 or last_bar.high < last_bar.low or last_bar.volume < 0:
                continue

            filtered_bars[ticker] = past_bars
            eligible_tickers.append(ticker)

        if not eligible_tickers:
            # Abort/block if entire universe has insufficient bars
            has_sufficient = any(
                len([b for b in bars if b.date <= target_date]) >= min_history_bars
                for bars in raw_bars_map.values()
            )
            if not has_sufficient:
                raise ValueError(
                    f"Insufficient historical bars up to {target_date} "
                    f"(minimum {min_history_bars} required)."
                )
            return []

        # 4. Compute features up to target_date
        if features_by_ticker is not None:
            feature_matrix = {
                t.strip().upper().removesuffix(".JK"): [f for f in f_list if f.date <= target_date]
                for t, f_list in features_by_ticker.items()
            }
        else:
            feature_matrix = self.feature_engine.compute_universe_features(filtered_bars)

        # Extract latest FeatureRecord on target_date
        date_features: dict[str, FeatureRecord] = {}
        for ticker in eligible_tickers:
            f_list = feature_matrix.get(ticker, [])
            for f in reversed(f_list):
                if f.date == target_date:
                    date_features[ticker] = f
                    break

        # 5. Resolve models and feature column contract
        model_version_str = model_version
        feature_names = DEFAULT_FEATURE_COLUMNS

        if classifier is None:
            if model_version:
                classifier, meta = self.model_registry.load_model(model_version)
                model_version_str = meta.model_version
                feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
            elif use_champion:
                champ = self.model_registry.get_champion(task="classification")
                if champ is None:
                    raise ValueError(
                        "No champion classification model registered in model registry."
                    )
                classifier, meta = champ
                model_version_str = meta.model_version
                feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
            else:
                champ = self.model_registry.get_champion(task="classification")
                if champ is not None:
                    classifier, meta = champ
                    model_version_str = meta.model_version
                    feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
                else:
                    candidates = self.model_registry.list_models(task="classification")
                    if candidates:
                        v = candidates[0].model_version
                        classifier, meta = self.model_registry.load_model(v)
                        model_version_str = meta.model_version
                        feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
                    else:
                        raise ValueError(
                            "No classifier model available in registry and none provided."
                        )
        else:
            if not model_version_str:
                model_version_str = getattr(classifier, "model_version", "custom_classifier")
            feature_names = getattr(classifier, "feature_names_", DEFAULT_FEATURE_COLUMNS)

        if regressor is None:
            champ_reg = self.model_registry.get_champion(task="regression")
            if champ_reg is not None:
                regressor, _ = champ_reg

        # 6. Predict probabilities and expected returns
        candidate_rows: list[dict[str, Any]] = []

        for ticker in eligible_tickers:
            feat_rec = date_features.get(ticker)
            if feat_rec is None:
                continue

            last_bar = filtered_bars[ticker][-1]

            # Vector representation for prediction (sanitized finite floats)
            x_row = []
            for col in feature_names:
                v = getattr(feat_rec, col, None)
                if v is not None:
                    try:
                        fv = float(v)
                        x_row.append(fv if math.isfinite(fv) else np.nan)
                    except (ValueError, TypeError):
                        x_row.append(np.nan)
                else:
                    x_row.append(np.nan)

            try:
                prob = float(self._predict_prob(classifier, [x_row])[0])
            except Exception:
                continue

            prob = float(np.clip(prob, 0.0, 1.0))

            exp_ret: Optional[float] = None
            if regressor is not None:
                try:
                    exp_ret = float(self._predict_reg(regressor, [x_row])[0])
                except Exception:
                    exp_ret = None

            # 7. Apply risk & liquidity filters
            if prob < cfg.min_probability:
                continue

            if cfg.min_expected_return is not None and exp_ret is not None:
                if exp_ret < cfg.min_expected_return:
                    continue

            if cfg.min_volume_20d is not None:
                recent_vols = [b.volume for b in filtered_bars[ticker][-20:]]
                avg_vol = sum(recent_vols) / len(recent_vols)
                if avg_vol < cfg.min_volume_20d:
                    continue

            if cfg.min_value_20d is not None:
                recent_vals = [
                    float(b.value) if b.value is not None else float(b.close * b.volume)
                    for b in filtered_bars[ticker][-20:]
                ]
                avg_val = sum(recent_vals) / len(recent_vals)
                if avg_val < cfg.min_value_20d:
                    continue

            # 8. Calculate composite score
            score = self.calculate_composite_score(
                prob=prob,
                expected_return=exp_ret,
                feat_rec=feat_rec,
                config=cfg,
            )

            candidate_rows.append(
                {
                    "ticker": ticker,
                    "prob": prob,
                    "expected_return": exp_ret,
                    "score": score,
                    "feat_rec": feat_rec,
                    "last_bar": last_bar,
                }
            )

        # 9. Rank candidates: score DESC, prob DESC, ticker ASC
        candidate_rows.sort(key=lambda x: (-x["score"], -x["prob"], x["ticker"]))

        top_candidates = candidate_rows[: cfg.top_n]

        # 10. Generate SignalRecord for Top-N
        results: list[SignalRecord] = []
        for cand in top_candidates:
            ticker = cand["ticker"]
            prob = cand["prob"]
            exp_ret = cand["expected_return"]
            score = cand["score"]
            feat_rec: FeatureRecord = cand["feat_rec"]
            last_bar: DailyBar = cand["last_bar"]

            c_close = float(last_bar.close)

            # Entry band around close
            half_band = cfg.entry_band_pct / 2.0
            entry_low = round(c_close * (1.0 - half_band), 2)
            entry_high = round(c_close * (1.0 + half_band), 2)

            if entry_low > entry_high:
                entry_low = entry_high

            # TP and SL prices
            tp_price = round(entry_high * (1.0 + cfg.tp_pct), 2)
            sl_price = round(entry_low * (1.0 - cfg.sl_pct), 2)

            # Safety guards for barrier relationships
            if tp_price <= entry_high:
                tp_price = round(entry_high + 1.0, 2)
            if sl_price >= entry_low:
                sl_price = round(max(1.0, entry_low - 1.0), 2)
            sl_price = max(1.0, sl_price)

            # Feature snapshot (all default columns + model feature names)
            cols_to_capture = list(
                dict.fromkeys(list(DEFAULT_FEATURE_COLUMNS) + list(feature_names))
            )
            snapshot = {}
            for col in cols_to_capture:
                v = getattr(feat_rec, col, None)
                if v is not None:
                    try:
                        fv = float(v)
                        if math.isfinite(fv):
                            snapshot[col] = round(fv, 6)
                    except (ValueError, TypeError):
                        pass

            # Deterministic canonical signal UUID
            canonical_key = f"{ticker}_{target_date.isoformat()}_{model_version_str}"
            signal_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, canonical_key))

            record = SignalRecord(
                signal_id=signal_id,
                ticker=ticker,
                signal_date=target_date,
                signal="BUY",
                entry_low=entry_low,
                entry_high=entry_high,
                tp_price=tp_price,
                sl_price=sl_price,
                max_holding_days=cfg.max_holding_days,
                predicted_probability=round(prob, 4),
                expected_return=round(exp_ret, 4) if exp_ret is not None else None,
                score=score,
                model_version=str(model_version_str),
                feature_version=feat_rec.feature_version,
                signal_config_version=cfg.signal_config_version,
                feature_snapshot=snapshot,
            )
            results.append(record)

        return results
