import math
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

import numpy as np

from python.common.types import (
    DailyBar,
    FeatureRecord,
    SignalConfig,
    SignalRecord,
    classify_price_mode,
    get_bei_tick_size,
    round_down_to_tick,
    round_to_nearest_tick,
    round_up_to_tick,
)
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
        mode: Optional[str] = None,
        bars_by_ticker: Optional[dict[str, list[DailyBar]]] = None,
        features_by_ticker: Optional[dict[str, list[FeatureRecord]]] = None,
        config: Optional[SignalConfig] = None,
        min_history_bars: int = 20,
    ) -> list[SignalRecord]:
        """Generate ranked signals for a given trading date and optional price mode."""
        cfg = config or self.config
        eff_mode = mode or cfg.mode
        if eff_mode:
            eff_mode = eff_mode.strip().upper()

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
                if (
                    eff_mode
                    and eff_mode not in ("ALL", "*")
                    and meta.mode
                    and meta.mode.strip().upper() != eff_mode
                ):
                    raise ValueError(
                        f"Model version '{model_version}' is tagged for mode '{meta.mode}', "
                        f"incompatible with requested mode '{eff_mode}'."
                    )
                model_version_str = meta.model_version
                feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
            elif use_champion:
                champ = None
                if eff_mode and eff_mode not in ("ALL", "*"):
                    champ = self.model_registry.get_champion(task="classification", mode=eff_mode)
                else:
                    champ = self.model_registry.get_champion(task="classification")
                if champ is None and eff_mode and eff_mode not in ("ALL", "*"):
                    legacy_champs = [
                        m
                        for m in self.model_registry.list_models(task="classification")
                        if m.mode is None and m.status.lower() == "champion"
                    ]
                    if legacy_champs:
                        champ = self.model_registry.load_model(legacy_champs[0].model_version)
                if champ is None:
                    mode_detail = f" for mode '{eff_mode}'" if eff_mode else ""
                    raise ValueError(
                        f"No champion classification model registered in model registry"
                        f"{mode_detail}."
                    )
                classifier, meta = champ
                model_version_str = meta.model_version
                feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
            else:
                champ = None
                if eff_mode and eff_mode not in ("ALL", "*"):
                    champ = self.model_registry.get_champion(task="classification", mode=eff_mode)
                else:
                    champ = self.model_registry.get_champion(task="classification")
                if champ is None and eff_mode and eff_mode not in ("ALL", "*"):
                    legacy_champs = [
                        m
                        for m in self.model_registry.list_models(task="classification")
                        if m.mode is None and m.status.lower() == "champion"
                    ]
                    if legacy_champs:
                        champ = self.model_registry.load_model(legacy_champs[0].model_version)
                if champ is not None:
                    classifier, meta = champ
                    model_version_str = meta.model_version
                    feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
                else:
                    candidates = self.model_registry.list_models(
                        task="classification",
                        mode=eff_mode if eff_mode not in ("ALL", "*") else None,
                    )
                    if not candidates and eff_mode and eff_mode not in ("ALL", "*"):
                        candidates = [
                            m
                            for m in self.model_registry.list_models(task="classification")
                            if m.mode is None
                        ]
                    if candidates:
                        v = candidates[0].model_version
                        classifier, meta = self.model_registry.load_model(v)
                        model_version_str = meta.model_version
                        feature_names = meta.feature_names or DEFAULT_FEATURE_COLUMNS
                    else:
                        mode_detail = f" for mode '{eff_mode}'" if eff_mode else ""
                        raise ValueError(
                            f"No classifier model available in registry{mode_detail} "
                            "and none provided."
                        )
        else:
            if not model_version_str:
                model_version_str = getattr(classifier, "model_version", "custom_classifier")
            feature_names = getattr(classifier, "feature_names_", DEFAULT_FEATURE_COLUMNS)

        if regressor is None:
            champ_reg = None
            if eff_mode and eff_mode not in ("ALL", "*"):
                champ_reg = self.model_registry.get_champion(task="regression", mode=eff_mode)
            else:
                champ_reg = self.model_registry.get_champion(task="regression")
            if champ_reg is None and eff_mode and eff_mode not in ("ALL", "*"):
                legacy_regs = [
                    m
                    for m in self.model_registry.list_models(task="regression")
                    if m.mode is None and m.status.lower() == "champion"
                ]
                if legacy_regs:
                    champ_reg = self.model_registry.load_model(legacy_regs[0].model_version)
            if champ_reg is not None:
                regressor, _ = champ_reg

        # 6. Predict probabilities and expected returns
        candidate_rows: list[dict[str, Any]] = []

        for ticker in eligible_tickers:
            feat_rec = date_features.get(ticker)
            if feat_rec is None:
                continue

            last_bar = filtered_bars[ticker][-1]
            cand_price = float(last_bar.close)
            cand_mode = classify_price_mode(cand_price)

            # Strict price integrity & ticker/date matching validation
            clean_t = ticker.strip().upper().removesuffix(".JK")
            bar_t = last_bar.ticker.strip().upper().removesuffix(".JK")
            feat_t = feat_rec.ticker.strip().upper().removesuffix(".JK")
            if bar_t != clean_t or feat_t != clean_t:
                continue

            # Stale data check: bar and feature must match target trading date
            if last_bar.date != target_date or feat_rec.date != target_date:
                continue

            # Raw-versus-adjusted price inconsistency check (fail-closed)
            adj_close = getattr(last_bar, "adj_close", None)
            if adj_close is not None and math.isfinite(adj_close) and adj_close > 0:
                divs = getattr(last_bar, "dividends", 0.0) or 0.0
                splits = getattr(last_bar, "stock_splits", 0.0) or 0.0
                if divs == 0.0 and splits == 0.0:
                    raw_adj_dev = abs(cand_price - adj_close) / cand_price
                    if raw_adj_dev > getattr(cfg, "raw_adjusted_tolerance_pct", 0.05):
                        continue

            # Strict exclusion: Sub-50 IDR or invalid prices excluded from signals
            if cand_mode in ("EXCLUDED_BELOW_50", "INVALID"):
                continue

            # If mode filter is active, only include matching price mode
            if eff_mode and eff_mode not in ("ALL", "*") and cand_mode != eff_mode:
                continue

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

            # Fail-closed BUY policy: Non-finite or non-positive probability blocks BUY
            if not math.isfinite(prob) or prob <= 0.0:
                continue

            prob = float(np.clip(prob, 0.0, 1.0))

            # 7. Apply risk & liquidity filters
            if prob < cfg.min_probability:
                continue

            # Calculate mathematical Expected Value (EV) components
            comm_buy = getattr(cfg, "commission_buy", 0.0015)
            comm_sell = getattr(cfg, "commission_sell", 0.0025)
            slippage = getattr(cfg, "slippage_bps", 10.0) / 10000.0
            friction = comm_buy + comm_sell + slippage

            exp_ratio = getattr(cfg, "expiry_given_negative_ratio", 0.1414)
            empirical_expiry_ret = getattr(cfg, "empirical_expiry_return", 0.0069)

            p_tp = prob
            p_sl = (1.0 - p_tp) * (1.0 - exp_ratio)
            p_exp = (1.0 - p_tp) * exp_ratio

            tp_net = cfg.tp_pct - friction
            sl_net = -cfg.sl_pct - friction
            exp_net = empirical_expiry_ret - friction

            ev_net_discrete = p_tp * tp_net + p_sl * sl_net + p_exp * exp_net
            ev_gross_discrete = (
                p_tp * cfg.tp_pct + p_sl * (-cfg.sl_pct) + p_exp * empirical_expiry_ret
            )

            exp_ret: Optional[float] = None
            if regressor is not None:
                try:
                    pred_val = float(self._predict_reg(regressor, [x_row])[0])
                    if math.isfinite(pred_val):
                        exp_ret = pred_val
                except Exception:
                    exp_ret = None

            # Fail-closed if expected return is explicitly required but missing or non-finite
            if getattr(cfg, "require_expected_return", False) and exp_ret is None:
                continue

            if exp_ret is not None:
                effective_exp_ret = exp_ret
                effective_net_ev = min(ev_net_discrete, exp_ret - friction)
            else:
                effective_exp_ret = ev_gross_discrete
                effective_net_ev = ev_net_discrete

            # Fail-closed if calculated values are non-finite
            if not math.isfinite(effective_net_ev) or not math.isfinite(effective_exp_ret):
                continue

            # Mathematical EV Hurdle Check (fail-closed)
            enforce_ev = getattr(cfg, "enforce_positive_ev", True)
            min_hurdle = getattr(cfg, "min_net_ev", 0.0)
            if enforce_ev and (
                effective_net_ev <= min_hurdle or abs(effective_net_ev - min_hurdle) < 1e-9
            ):
                continue

            if cfg.min_expected_return is not None and effective_exp_ret is not None:
                if effective_exp_ret < cfg.min_expected_return:
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
                expected_return=effective_exp_ret,
                feat_rec=feat_rec,
                config=cfg,
            )

            candidate_rows.append(
                {
                    "ticker": ticker,
                    "prob": prob,
                    "expected_return": effective_exp_ret,
                    "net_ev": effective_net_ev,
                    "score": score,
                    "feat_rec": feat_rec,
                    "last_bar": last_bar,
                    "mode": cand_mode,
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
            ref_price = c_close
            half_band = cfg.entry_band_pct / 2.0

            target_entry = float(
                cand.get("breakout_price")
                or cand.get("entry_price")
                or getattr(feat_rec, "breakout_price", None)
                or getattr(feat_rec, "entry_price", None)
                or ref_price
            )
            raw_low = target_entry * (1.0 - half_band)
            raw_high = target_entry * (1.0 + half_band)

            enforce_ticks = getattr(cfg, "enforce_bei_ticks", False)
            min_ticks = max(1, getattr(cfg, "min_range_ticks", 1))

            if enforce_ticks:
                entry_low = round_down_to_tick(raw_low)
                entry_high = round_up_to_tick(raw_high)
                tick_low = get_bei_tick_size(entry_low)
                tick_high = get_bei_tick_size(entry_high)
                if (entry_high - entry_low) < min_ticks * min(tick_low, tick_high):
                    entry_low = max(1.0, round_down_to_tick(entry_low - tick_low))
                    entry_high = round_up_to_tick(entry_high + tick_high)
                tp_price = round_up_to_tick(entry_high * (1.0 + cfg.tp_pct))
                sl_price = round_down_to_tick(entry_low * (1.0 - cfg.sl_pct))
                if tp_price <= entry_high:
                    tp_price = round_up_to_tick(entry_high + get_bei_tick_size(entry_high))
                if sl_price >= entry_low:
                    tick_down = get_bei_tick_size(entry_low)
                    sl_price = max(1.0, round_down_to_tick(entry_low - tick_down))
            else:
                cand_low = round(raw_low, 2)
                cand_high = round(raw_high, 2)
                rounded_low_tick = round_to_nearest_tick(cand_low)
                rounded_high_tick = round_to_nearest_tick(cand_high)
                # Check whether entry zone collapses when rounded to nearest tick
                if rounded_low_tick >= rounded_high_tick or cand_low >= cand_high:
                    entry_low = round_down_to_tick(raw_low)
                    entry_high = round_up_to_tick(raw_high)
                    tick_low = get_bei_tick_size(entry_low)
                    tick_high = get_bei_tick_size(entry_high)
                    if (entry_high - entry_low) < min_ticks * min(tick_low, tick_high):
                        entry_low = max(
                            1.0, round_down_to_tick(target_entry - tick_low * min_ticks)
                        )
                        entry_high = round_up_to_tick(target_entry + tick_high * min_ticks)
                    tp_price = round_up_to_tick(entry_high * (1.0 + cfg.tp_pct))
                    sl_price = round_down_to_tick(entry_low * (1.0 - cfg.sl_pct))
                    if tp_price <= entry_high:
                        tp_price = round_up_to_tick(entry_high + get_bei_tick_size(entry_high))
                    if sl_price >= entry_low:
                        tick_down = get_bei_tick_size(entry_low)
                        sl_price = max(1.0, round_down_to_tick(entry_low - tick_down))
                else:
                    entry_low = cand_low
                    entry_high = cand_high
                    tp_price = round(entry_high * (1.0 + cfg.tp_pct), 2)
                    sl_price = round(entry_low * (1.0 - cfg.sl_pct), 2)
                    if tp_price <= entry_high:
                        tp_price = round(entry_high + 1.0, 2)
                    if sl_price >= entry_low:
                        sl_price = round(max(1.0, entry_low - 1.0), 2)
            sl_price = max(1.0, sl_price)

            # 11. Entry policy and reference price consistency checks
            max_dev = getattr(cfg, "max_entry_deviation_pct", 0.05)
            dev_above = (entry_low - ref_price) / ref_price
            dev_below = (ref_price - entry_high) / ref_price

            if dev_above > max_dev:
                # Entry zone is above reference price beyond max_dev -> breakout trigger
                if getattr(cfg, "allow_breakout", True):
                    entry_policy = "BREAKOUT"
                    sig_status = "WAIT_FOR_BREAKOUT"
                else:
                    # Breakout not allowed: fail-closed
                    continue
            elif dev_below > max_dev:
                # Downward entry zone beyond max_dev fails closed
                continue
            elif (
                abs(entry_high - ref_price) / ref_price > max_dev
                or abs(ref_price - entry_low) / ref_price > max_dev
            ):
                # Entry zone straddles beyond allowable deviation (fail-closed)
                continue
            else:
                entry_policy = "IMMEDIATE"
                sig_status = "BUY"

            # Fail-closed safeguard: BUY cannot be emitted if net EV fails hurdle or inputs invalid
            enforce_ev = getattr(cfg, "enforce_positive_ev", True)
            min_hurdle = getattr(cfg, "min_net_ev", 0.0)
            if sig_status in ("BUY", "WAIT_FOR_BREAKOUT"):
                if getattr(cfg, "require_expected_return", False):
                    c_exp = cand.get("expected_return")
                    if c_exp is None or not math.isfinite(c_exp):
                        continue
                if enforce_ev:
                    cand_net_ev = cand.get("net_ev")
                    if (
                        cand_net_ev is None
                        or not math.isfinite(cand_net_ev)
                        or cand_net_ev <= min_hurdle
                        or abs(cand_net_ev - min_hurdle) < 1e-9
                    ):
                        continue

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

            now_utc = datetime.now(timezone.utc)
            market_as_of = datetime.combine(
                last_bar.date,
                datetime.min.time(),
                tzinfo=timezone.utc,
            )

            record = SignalRecord(
                signal_id=signal_id,
                ticker=ticker,
                signal_date=target_date,
                signal=sig_status,
                status=sig_status,
                entry_low=entry_low,
                entry_high=entry_high,
                tp_price=tp_price,
                sl_price=sl_price,
                max_holding_days=cfg.max_holding_days,
                predicted_probability=round(prob, 4),
                expected_return=(
                    round(exp_ret, 4) if (exp_ret is not None and math.isfinite(exp_ret)) else None
                ),
                net_ev=(
                    round(cand["net_ev"], 4)
                    if (cand.get("net_ev") is not None and math.isfinite(cand["net_ev"]))
                    else None
                ),
                score=score,
                model_version=str(model_version_str),
                feature_version=feat_rec.feature_version,
                signal_config_version=cfg.signal_config_version,
                feature_snapshot=snapshot,
                mode=cand.get("mode"),
                signal_generated_at=now_utc,
                market_data_as_of=market_as_of,
                latest_completed_bar_date=last_bar.date,
                reference_price=ref_price,
                entry_policy=entry_policy,
                max_entry_deviation_pct=max_dev,
            )
            results.append(record)

        return results

    def generate_dual_mode_signals(
        self,
        signal_date: Optional[date] = None,
        universe: Optional[list[str]] = None,
        bars_by_ticker: Optional[dict[str, list[DailyBar]]] = None,
        features_by_ticker: Optional[dict[str, list[FeatureRecord]]] = None,
        config: Optional[SignalConfig] = None,
        config_low: Optional[SignalConfig] = None,
        config_higher: Optional[SignalConfig] = None,
        use_champion: bool = False,
        min_history_bars: int = 20,
        **kwargs: Any,
    ) -> dict[str, list[SignalRecord]]:
        """Generate separate ranked signals for LOW_PRICE and HIGHER_PRICE modes."""
        base_cfg = config or self.config
        cfg_low = config_low or base_cfg.model_copy(update={"mode": "LOW_PRICE"})
        cfg_high = config_higher or base_cfg.model_copy(update={"mode": "HIGHER_PRICE"})

        try:
            low_signals = self.generate_signals(
                signal_date=signal_date,
                universe=universe,
                mode="LOW_PRICE",
                bars_by_ticker=bars_by_ticker,
                features_by_ticker=features_by_ticker,
                config=cfg_low,
                use_champion=use_champion,
                min_history_bars=min_history_bars,
                **kwargs,
            )
        except ValueError:
            low_signals = []

        try:
            higher_signals = self.generate_signals(
                signal_date=signal_date,
                universe=universe,
                mode="HIGHER_PRICE",
                bars_by_ticker=bars_by_ticker,
                features_by_ticker=features_by_ticker,
                config=cfg_high,
                use_champion=use_champion,
                min_history_bars=min_history_bars,
                **kwargs,
            )
        except ValueError:
            higher_signals = []

        return {
            "LOW_PRICE": low_signals,
            "HIGHER_PRICE": higher_signals,
        }
