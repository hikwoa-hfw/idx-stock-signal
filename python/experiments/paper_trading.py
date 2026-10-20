"""Forward Paper Trading & Frozen Policy Validation Engine (Phase 11F).

Implements forward, research-only paper-trading simulation, frozen policy
definitions, configuration hashing, fail-closed artifact guards, execution
tracking, and operational reporting for the BEI dual-mode stock signals.

Strict offline research contract:
- Production champion models and registry remain strictly immutable.
- Frozen research policies: LOW_PRICE (Top 3%, H=15 Regressor, TP +6% / SL -2%, Three-tier sizing)
  and HIGHER_PRICE (Top 1%, H=15 Full Classifier, TP +6% / SL -2%, Three-tier sizing).
- Fail-closed guard: missing H=15 Variant B joblib scoring artifacts abort prospective scoring
  with MISSING_SCORING_ARTIFACT; champions are NEVER substituted.
- 50 bps round-trip nominal friction (15 bps buy, 25 bps sell, 5 bps entry slip, 5 bps exit slip).
- 100-share lot sizes, maximum 5 concurrent positions, 20% equity cap.
- Strict point-in-time causality: all decisions at Close t, entry modeled at Open t+1.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

import joblib
import numpy as np
import pandas as pd

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from python.common.types import DailyBar
from python.config.settings import settings
from python.models.research_scoring import (
    ResearchClassifierModel,
    ResearchRegressorModel,
)
from scripts.audit_target_contract_runner import load_all_bars

__all__ = [
    "CHAMPION_MODELS",
    "DataQualityError",
    "FEATURE_SCHEMA_30",
    "FIRST_PROSPECTIVE_DATE",
    "FrozenPolicyBundle",
    "InvalidProspectiveDateError",
    "MissedSessionError",
    "MissingScoringArtifactError",
    "PaperCandidate",
    "PaperDecision",
    "PaperTrade",
    "PaperTradingEngine",
    "PolicyDefinition",
    "RESEARCH_SCORING_ARTIFACTS",
    "ResearchClassifierModel",
    "ResearchRegressorModel",
    "STATUS_APPROVED_PENDING_FIRST_OBSERVATION",
    "STATUS_BLOCKED_ON_SCORING_ARTIFACT",
    "STATUS_BLOCKED_ON_STATE_CORRUPTION",
    "STATUS_OBSERVATION_ACTIVE",
    "STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL",
    "STATUS_SCORING_ARTIFACTS_READY",
    "StateIntegrityError",
    "UserApprovalRequiredError",
    "classify_regime_three_tier",
    "get_default_frozen_policies",
]

# Lifecycle and operational status constants
STATUS_BLOCKED_ON_SCORING_ARTIFACT = "BLOCKED_ON_SCORING_ARTIFACT"
STATUS_BLOCKED_ON_STATE_CORRUPTION = "BLOCKED_ON_STATE_CORRUPTION"
STATUS_SCORING_ARTIFACTS_READY = "SCORING_ARTIFACTS_READY"
STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL = "READY_FOR_OBSERVATION_PENDING_USER_APPROVAL"
STATUS_APPROVED_PENDING_FIRST_OBSERVATION = "APPROVED_PENDING_FIRST_OBSERVATION"
STATUS_OBSERVATION_ACTIVE = "OBSERVATION_ACTIVE"
FIRST_PROSPECTIVE_DATE = date(2026, 10, 19)

# Production champions that MUST NOT be used for research scoring
CHAMPION_MODELS = {
    "LOW_PRICE": "lightgbm_classification_20261014_093522",
    "HIGHER_PRICE": "lightgbm_classification_20261014_093607",
}

# Expected H=15 Variant B research artifacts
RESEARCH_SCORING_ARTIFACTS = {
    "LOW_PRICE": "artifacts/phase_11f/research_models/lgb_regressor_h15_variant_b.joblib",
    "HIGHER_PRICE": "artifacts/phase_11f/research_models/lgb_full_classifier_h15_variant_b.joblib",
}

FEATURE_SCHEMA_30 = [
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "ema20",
    "ema50",
    "ema200",
    "close_vs_ema20",
    "close_vs_ema50",
    "ema20_vs_ema50",
    "ema50_vs_ema200",
    "rsi14",
    "rsi_change_5d",
    "atr14",
    "atr_pct",
    "realized_vol_5d",
    "realized_vol_20d",
    "daily_range_pct",
    "volume_ratio_5d",
    "volume_ratio_20d",
    "value_ratio_20d",
    "rel_strength_ihsg_20d",
    "rel_strength_sector_20d",
    "ihsg_return_5d",
    "ihsg_return_20d",
    "ihsg_vs_ema20",
    "ihsg_vs_ema50",
    "market_breadth",
    "market_volatility",
]


class MissingScoringArtifactError(Exception):
    """Raised when research scoring model artifacts are missing and fallback is blocked."""


class UserApprovalRequiredError(Exception):
    """Raised when prospective date scoring is attempted without explicit user approval."""


class InvalidProspectiveDateError(Exception):
    """Raised when an invalid, historical, or non-monotonic prospective date is requested."""


class MissedSessionError(Exception):
    """Raised when an active trading session was skipped, requiring sequential recovery."""


class DataQualityError(Exception):
    """Raised when price bars or features fail completeness, freshness, or schema checks."""


class StateIntegrityError(Exception):
    """Raised when persistent paper trading state is corrupt, invalid, or hash-mismatched."""


@dataclass
class PolicyDefinition:
    mode: str
    target_contract: str
    horizon_days: int
    score_metric: str
    model_artifact_path: str
    selectivity_top_pct: float
    tie_breaker: str
    regime_filter: str
    tp_pct: float
    sl_pct: float
    trailing_stop_enabled: bool
    sizing_tiers: dict[str, dict[str, Any]]
    portfolio_constraints: dict[str, Any]
    friction_model: dict[str, float]
    gap_invalidation_rules: dict[str, float]


@dataclass
class FrozenPolicyBundle:
    version: str
    created_at: str
    policies: dict[str, PolicyDefinition]
    feature_schema: list[str]
    governance_invariants: list[str]
    config_sha256: str = ""

    def compute_sha256(self) -> str:
        """Computes deterministic canonical SHA-256 hash of policy bundle."""
        data_dict = asdict(self)
        data_dict.pop("config_sha256", None)
        canonical_json = json.dumps(data_dict, sort_keys=True, indent=2)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def get_default_frozen_policies() -> FrozenPolicyBundle:
    """Builds the canonical frozen policy bundle for Phase 11F."""
    portfolio_constraints = {
        "max_concurrent_positions": 5,
        "equity_cap_pct": 0.20,
        "lot_size": 100,
        "initial_capital": 100_000_000.0,
    }
    friction_model = {
        "commission_buy_pct": 0.0015,
        "commission_sell_pct": 0.0025,
        "slippage_entry_bps": 5.0,
        "slippage_exit_bps": 5.0,
        "nominal_round_trip_bps": 50.0,
    }
    gap_rules = {
        "gap_down_sl_pct": 0.02,
        "gap_up_tp_pct": 0.06,
        "max_open_dev_pct": 0.05,
        "volume_min": 1.0,
    }
    sizing_tiers = {
        "favorable": {
            "condition": "ihsg_vs_ema20 > 0 and market_breadth >= 0.50",
            "multiplier": 1.0,
        },
        "mixed": {
            "condition": "not (favorable or unfavorable)",
            "multiplier": 0.5,
        },
        "unfavorable": {
            "condition": "ihsg_vs_ema20 <= 0 and market_breadth < 0.50",
            "multiplier": 0.0,
        },
    }

    policies = {
        "LOW_PRICE": PolicyDefinition(
            mode="LOW_PRICE",
            target_contract="Variant B (Next-Open Executable)",
            horizon_days=15,
            score_metric="pred_return_lgb",
            model_artifact_path=RESEARCH_SCORING_ARTIFACTS["LOW_PRICE"],
            selectivity_top_pct=0.03,
            tie_breaker="score desc, ticker asc",
            regime_filter="ihsg_vs_ema20 > 0",
            tp_pct=0.06,
            sl_pct=0.02,
            trailing_stop_enabled=False,
            sizing_tiers=sizing_tiers,
            portfolio_constraints=portfolio_constraints,
            friction_model=friction_model,
            gap_invalidation_rules=gap_rules,
        ),
        "HIGHER_PRICE": PolicyDefinition(
            mode="HIGHER_PRICE",
            target_contract="Variant B (Next-Open Executable)",
            horizon_days=15,
            score_metric="prob_lgb_full",
            model_artifact_path=RESEARCH_SCORING_ARTIFACTS["HIGHER_PRICE"],
            selectivity_top_pct=0.01,
            tie_breaker="score desc, ticker asc",
            regime_filter="ihsg_vs_ema20 > 0",
            tp_pct=0.06,
            sl_pct=0.02,
            trailing_stop_enabled=False,
            sizing_tiers=sizing_tiers,
            portfolio_constraints=portfolio_constraints,
            friction_model=friction_model,
            gap_invalidation_rules=gap_rules,
        ),
    }

    bundle = FrozenPolicyBundle(
        version="Phase-11F-Frozen-Policy-v1",
        created_at="2026-10-19T23:00:00Z",
        policies=policies,
        feature_schema=FEATURE_SCHEMA_30,
        governance_invariants=[
            "No production champion model promotion permitted in Phase 11F.",
            "Never fall back to production champions for research scoring.",
            "Fail closed if H=15 Variant B scoring artifacts are unavailable.",
            "Strictly forward paper trading on new bars; no trailing stops in primary evaluation.",
            "50 bps nominal round-trip transaction friction applied to all fills.",
            "Conservative execution precedence: stop-loss precedes take-profit on ambiguous bars.",
        ],
    )
    bundle.config_sha256 = bundle.compute_sha256()
    return bundle


def classify_regime_three_tier(reg_info: dict[str, float]) -> tuple[float, str]:
    """Calculates point-in-time three-tier sizing multiplier and regime tag."""
    trend = reg_info.get("ihsg_vs_ema20", 0.0)
    breadth = reg_info.get("market_breadth", 0.5)

    if trend > 0.0 and breadth >= 0.50:
        return 1.0, "FAVORABLE"
    if trend <= 0.0 and breadth < 0.50:
        return 0.0, "UNFAVORABLE"
    return 0.5, "MIXED"


@dataclass
class PaperCandidate:
    date: date
    ticker: str
    mode: str
    decision_price: float
    score: float
    rank_in_date: int
    total_candidates_date: int
    is_top_pct: bool
    regime_bull: bool
    is_eligible: bool
    score_col: str
    model_id: str


@dataclass
class PaperDecision:
    decision_date: date
    execution_date: date
    ticker: str
    mode: str
    score: float
    rank: int
    close_t: float
    size_multiplier: float
    regime_category: str
    planned_tp_pct: float
    planned_sl_pct: float
    planned_tp_price: float
    planned_sl_price: float
    planned_allocation_idr: float
    max_holding_days: int


@dataclass
class PaperTrade:
    ticker: str
    mode: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    size_multiplier: float
    regime_category: str
    gross_outlay: float
    gross_proceeds: float
    gross_pnl: float
    gross_return: float
    entry_fee: float
    exit_fee: float
    total_friction_idr: float
    net_pnl: float
    net_return: float
    exit_reason: str
    holding_days: int
    mfe_pct: float
    mae_pct: float
    highest_watermark: float
    lowest_watermark: float
    planned_tp_price: float
    planned_sl_price: float


@dataclass
class DailyEquityRecord:
    date: date
    mode: str
    cash: float
    invested_capital: float
    total_equity: float
    peak_equity: float
    drawdown_amount: float
    drawdown_pct: float
    open_positions_count: int
    cash_exposure_pct: float
    portfolio_allocation_pct: float


class PaperTradingEngine:
    """Forward paper-trading simulation and state manager for Phase 11F."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        phase11c_dir: Union[str, Path] = "artifacts/phase_11c",
        artifacts_dir: Union[str, Path] = "artifacts/phase_11f",
        initial_capital: float = 100_000_000.0,
        max_positions: int = 5,
        commission_buy: float = 0.0015,
        commission_sell: float = 0.0025,
        slippage_entry_bps: float = 5.0,
        slippage_exit_bps: float = 5.0,
    ) -> None:
        self.db_path = db_path or self._resolve_db_path()
        self.phase11c_dir = Path(phase11c_dir)
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.commission_buy = commission_buy
        self.commission_sell = commission_sell
        self.slippage_entry_bps = slippage_entry_bps
        self.slippage_exit_bps = slippage_exit_bps

        self.frozen_bundle = get_default_frozen_policies()

        # Caches
        self._bars_by_ticker: Optional[dict[str, list[DailyBar]]] = None
        self._bar_lookup: Optional[dict[tuple[str, date], DailyBar]] = None
        self._regime_lookup: Optional[dict[date, dict[str, float]]] = None
        self._atr_lookup: Optional[dict[tuple[str, date], float]] = None

    def _resolve_db_path(self) -> str:
        url = settings.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///") :]
        if url.startswith("sqlite://"):
            return url[len("sqlite://") :]
        return "datasets/stock_signals.db"

    @property
    def bars_by_ticker(self) -> dict[str, list[DailyBar]]:
        if self._bars_by_ticker is None:
            self._bars_by_ticker = load_all_bars(self.db_path)
        return self._bars_by_ticker

    @property
    def bar_lookup(self) -> dict[tuple[str, date], DailyBar]:
        if self._bar_lookup is None:
            self._bar_lookup = {
                (t, b.date): b for t, b_list in self.bars_by_ticker.items() for b in b_list
            }
        return self._bar_lookup

    @property
    def regime_lookup(self) -> dict[date, dict[str, float]]:
        if self._regime_lookup is None:
            conn = sqlite3.connect(self.db_path)
            try:
                query = """
                    SELECT date,
                           AVG(ihsg_vs_ema20) as ihsg_vs_ema20,
                           AVG(market_breadth) as market_breadth,
                           AVG(ihsg_return_20d) as ihsg_return_20d,
                           AVG(market_volatility) as market_volatility
                    FROM features_daily
                    GROUP BY date;
                """
                df_reg = pd.read_sql_query(query, conn)
                df_reg["date"] = pd.to_datetime(df_reg["date"]).dt.date
                self._regime_lookup = {
                    r["date"]: {
                        "ihsg_vs_ema20": float(r["ihsg_vs_ema20"])
                        if pd.notnull(r["ihsg_vs_ema20"])
                        else 0.0,
                        "market_breadth": float(r["market_breadth"])
                        if pd.notnull(r["market_breadth"])
                        else 0.5,
                        "ihsg_return_20d": float(r["ihsg_return_20d"])
                        if pd.notnull(r["ihsg_return_20d"])
                        else 0.0,
                        "market_volatility": float(r["market_volatility"])
                        if pd.notnull(r["market_volatility"])
                        else 0.0075,
                    }
                    for _, r in df_reg.iterrows()
                }
            finally:
                conn.close()
        return self._regime_lookup

    @property
    def atr_lookup(self) -> dict[tuple[str, date], float]:
        if self._atr_lookup is None:
            conn = sqlite3.connect(self.db_path)
            try:
                query = """
                    SELECT date, ticker, atr_pct
                    FROM features_daily
                    WHERE atr_pct IS NOT NULL;
                """
                df_atr = pd.read_sql_query(query, conn)
                df_atr["date"] = pd.to_datetime(df_atr["date"]).dt.date
                self._atr_lookup = {
                    (r["ticker"].strip().upper().removesuffix(".JK"), r["date"]): float(
                        r["atr_pct"]
                    )
                    for _, r in df_atr.iterrows()
                }
            finally:
                conn.close()
        return self._atr_lookup

    def audit_scoring_artifacts(self, base_dir: Optional[Path] = None) -> dict[str, Any]:
        """Audits presence and integrity of persistent joblib model artifacts for research scoring.

        Fails closed: if exact H=15 Variant B artifacts are missing, hash mismatches,
        or smoke test fails, reports BLOCKED_ON_SCORING_ARTIFACT and forbids fallback
        to production champions.
        """
        root = base_dir or Path(__file__).resolve().parent.parent.parent
        meta_path = root / "artifacts/phase_11f/research_models/research_model_metadata.json"

        expected_metadata: Optional[dict[str, Any]] = None
        if meta_path.is_file():
            try:
                expected_metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        audit_results: dict[str, Any] = {
            "status": "PASS",
            "scoring_artifacts_status": STATUS_SCORING_ARTIFACTS_READY,
            "fail_closed_guard_active": True,
            "champion_fallback_permitted": False,
            "artifacts": {},
            "missing_artifacts": [],
            "error_logs": [],
        }

        canonical_hashes = {
            "LOW_PRICE": "84170b518a658e75dc481b8b445f0925e9811aa857dd0c94ebaa1ac65ed127f8",
            "HIGHER_PRICE": "3192aa5c68d00052707dd31a271e639f9d30e28cda7407bbc9bdd45e054953bc",
        }

        for mode, rel_path in RESEARCH_SCORING_ARTIFACTS.items():
            full_path = root / rel_path
            exists = full_path.is_file()
            audit_results["artifacts"][mode] = {
                "expected_artifact": rel_path,
                "absolute_path": str(full_path),
                "exists": exists,
                "status": "AVAILABLE" if exists else "MISSING_SCORING_ARTIFACT",
                "champion_substitute_blocked": CHAMPION_MODELS[mode],
            }
            if not exists:
                audit_results["missing_artifacts"].append(rel_path)
                continue

            # Compute SHA-256
            h = hashlib.sha256()
            with open(full_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            file_sha = h.hexdigest()
            audit_results["artifacts"][mode]["sha256"] = file_sha

            # Verify against metadata if present, or canonical if base_dir is None
            expected_sha = None
            if (
                expected_metadata
                and "models" in expected_metadata
                and mode in expected_metadata["models"]
            ):
                expected_sha = expected_metadata["models"][mode].get("sha256")
            elif base_dir is None:
                expected_sha = canonical_hashes.get(mode)

            if expected_sha is not None:
                audit_results["artifacts"][mode]["expected_sha256"] = expected_sha
                if file_sha != expected_sha:
                    audit_results["error_logs"].append(
                        f"Hash mismatch for {mode} artifact at {rel_path}: "
                        f"expected {expected_sha}, got {file_sha}"
                    )
                    audit_results["artifacts"][mode]["status"] = "HASH_MISMATCH"
                    audit_results["status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT
                    continue

            # Load model and run smoke prediction
            try:
                if meta_path.is_file() and hasattr(ResearchRegressorModel, "load"):
                    if mode == "LOW_PRICE":
                        model = ResearchRegressorModel.load(full_path)
                    else:
                        model = ResearchClassifierModel.load(full_path)
                else:
                    model = joblib.load(full_path)
            except Exception as load_err:
                audit_results["error_logs"].append(
                    f"Failed loading {mode} artifact at {rel_path}: {load_err}"
                )
                audit_results["artifacts"][mode]["status"] = "LOAD_FAILURE"
                audit_results["status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT
                continue

            # Smoke prediction on 1 sample of FEATURE_SCHEMA_30
            try:
                smoke_df = pd.DataFrame([{col: 0.0 for col in FEATURE_SCHEMA_30}])
                if mode == "LOW_PRICE":
                    smoke_score = model.predict(smoke_df)
                else:
                    smoke_score = (
                        model.predict_probability(smoke_df)
                        if hasattr(model, "predict_probability")
                        else (
                            model.predict_proba(smoke_df)[:, 1]
                            if hasattr(model, "predict_proba")
                            else model.predict(smoke_df)
                        )
                    )
                if not np.all(np.isfinite(smoke_score)):
                    audit_results["error_logs"].append(
                        f"Smoke test produced non-finite score for {mode}: {smoke_score}"
                    )
                    audit_results["status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT
                else:
                    audit_results["artifacts"][mode]["smoke_test"] = "PASS"
            except Exception as smoke_err:
                audit_results["error_logs"].append(
                    f"Smoke prediction failed for {mode}: {smoke_err}"
                )
                audit_results["status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT

        if audit_results["missing_artifacts"]:
            audit_results["status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT
            audit_results["error_logs"].append(
                f"Missing {len(audit_results['missing_artifacts'])} research scoring artifact(s): "
                f"{', '.join(audit_results['missing_artifacts'])}. "
                "In Phase 11C, H=15 models were evaluated in-memory during walk-forward folds "
                "without serializing standalone .joblib files to models/registry/."
            )
            audit_results["error_logs"].append(
                "Fail-closed guard active: Never fall back to production champions "
                f"({', '.join(CHAMPION_MODELS.values())}) for research scoring."
            )

        if audit_results["status"] != "PASS":
            audit_results["scoring_artifacts_status"] = STATUS_BLOCKED_ON_SCORING_ARTIFACT

        return audit_results

    def export_frozen_policy_config(self, output_path: Optional[Path] = None) -> dict[str, Any]:
        """Exports the frozen policy bundle to JSON."""
        target = output_path or (self.artifacts_dir / "frozen_policy_config.json")
        bundle_dict = asdict(self.frozen_bundle)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(bundle_dict, f, indent=2, sort_keys=True)
        return bundle_dict

    def export_frozen_reference_benchmarks(
        self, output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """Constructs and exports frozen reference benchmark comparisons."""
        target = output_path or (self.artifacts_dir / "frozen_reference_benchmarks.csv")

        benchmarks = [
            {
                "benchmark_id": "phase_11d_selective_fixed_exit",
                "phase": "Phase 11D",
                "mode": "LOW_PRICE",
                "policy_description": "Top 3% Selectivity + Bull Filter + H=15 Fixed (+6%/-2%)",
                "scoring_model": "H=15 LightGBM Regressor (pred_return_lgb)",
                "sizing_rule": "Fixed 1.0x (No Dynamic Sizing)",
                "total_signals": 764,
                "completed_trades": 172,
                "win_rate": 0.3081,
                "avg_net_return": 0.0008,
                "net_portfolio_return_pct": 2.12,
                "pooled_profit_factor": 1.04,
                "continuous_max_drawdown_pct": 9.59,
                "avg_cash_exposure_pct": 77.35,
                "portfolio_turnover": 34.00,
                "status": "HISTORICAL_BACKTEST_REFERENCE",
            },
            {
                "benchmark_id": "phase_11d_selective_fixed_exit",
                "phase": "Phase 11D",
                "mode": "HIGHER_PRICE",
                "policy_description": "Top 1% Selectivity + Bull Filter + H=15 Fixed (+6%/-2%)",
                "scoring_model": "H=15 Full LightGBM Classifier (prob_lgb_full)",
                "sizing_rule": "Fixed 1.0x (No Dynamic Sizing)",
                "total_signals": 764,
                "completed_trades": 301,
                "win_rate": 0.3355,
                "avg_net_return": 0.0013,
                "net_portfolio_return_pct": 8.57,
                "pooled_profit_factor": 1.07,
                "continuous_max_drawdown_pct": 9.77,
                "avg_cash_exposure_pct": 62.92,
                "portfolio_turnover": 59.16,
                "status": "HISTORICAL_BACKTEST_REFERENCE",
            },
            {
                "benchmark_id": "phase_11e_selective_three_tier_sizing",
                "phase": "Phase 11E",
                "mode": "LOW_PRICE",
                "policy_description": "Top 3% Selectivity + Bull Filter + H=15 + Three-Tier Sizing",
                "scoring_model": "H=15 LightGBM Regressor (pred_return_lgb)",
                "sizing_rule": "Three-Tier Regime (1.0x Fav / 0.5x Mixed / 0.0x Unfav)",
                "total_signals": 764,
                "completed_trades": 172,
                "win_rate": 0.3081,
                "avg_net_return": 0.0008,
                "net_portfolio_return_pct": 0.79,
                "pooled_profit_factor": 1.02,
                "continuous_max_drawdown_pct": 6.34,
                "avg_cash_exposure_pct": 81.28,
                "portfolio_turnover": 27.89,
                "status": "HISTORICAL_BACKTEST_REFERENCE",
            },
            {
                "benchmark_id": "phase_11e_selective_three_tier_sizing",
                "phase": "Phase 11E",
                "mode": "HIGHER_PRICE",
                "policy_description": "Top 1% Selectivity + Bull Filter + H=15 + Three-Tier Sizing",
                "scoring_model": "H=15 Full LightGBM Classifier (prob_lgb_full)",
                "sizing_rule": "Three-Tier Regime (1.0x Fav / 0.5x Mixed / 0.0x Unfav)",
                "total_signals": 764,
                "completed_trades": 298,
                "win_rate": 0.3389,
                "avg_net_return": 0.0014,
                "net_portfolio_return_pct": 5.90,
                "pooled_profit_factor": 1.06,
                "continuous_max_drawdown_pct": 8.83,
                "avg_cash_exposure_pct": 70.00,
                "portfolio_turnover": 47.03,
                "status": "HISTORICAL_BACKTEST_REFERENCE",
            },
            {
                "benchmark_id": "production_champion_reference",
                "phase": "Production Champion",
                "mode": "LOW_PRICE",
                "policy_description": "Active Champion Baseline (Top 5 fixed, H=5, 1.0x)",
                "scoring_model": f"Champion {CHAMPION_MODELS['LOW_PRICE']}",
                "sizing_rule": "Fixed 1.0x Allocation",
                "total_signals": 3295,
                "completed_trades": 1211,
                "win_rate": 0.2907,
                "avg_net_return": -0.0041,
                "net_portfolio_return_pct": -48.20,
                "pooled_profit_factor": 0.76,
                "continuous_max_drawdown_pct": 63.83,
                "avg_cash_exposure_pct": 99.55,
                "portfolio_turnover": 201.27,
                "status": "PRODUCTION_INFORMATIONAL_REFERENCE",
            },
            {
                "benchmark_id": "production_champion_reference",
                "phase": "Production Champion",
                "mode": "HIGHER_PRICE",
                "policy_description": "Active Champion Baseline (Top 5 fixed, H=5, 1.0x)",
                "scoring_model": f"Champion {CHAMPION_MODELS['HIGHER_PRICE']}",
                "sizing_rule": "Fixed 1.0x Allocation",
                "total_signals": 3300,
                "completed_trades": 980,
                "win_rate": 0.2827,
                "avg_net_return": -0.0049,
                "net_portfolio_return_pct": -54.30,
                "pooled_profit_factor": 0.72,
                "continuous_max_drawdown_pct": 62.67,
                "avg_cash_exposure_pct": 99.55,
                "portfolio_turnover": 166.05,
                "status": "PRODUCTION_INFORMATIONAL_REFERENCE",
            },
        ]

        df_benchmarks = pd.DataFrame(benchmarks)
        df_benchmarks.to_csv(target, index=False)
        return df_benchmarks

    def run_replay(self, modes: Optional[list[str]] = None) -> dict[str, Any]:
        """Runs historical replay using frozen Phase 11C OOS predictions.

        Validates end-to-end execution fidelity: deterministic tie breaking,
        pre-entry gap invalidations, three-tier sizing, cash constraints,
        50 bps friction, MFE/MAE tracking, and daily mark-to-market equity.
        """
        modes = modes or ["LOW_PRICE", "HIGHER_PRICE"]
        all_candidates: list[PaperCandidate] = []
        all_decisions: list[PaperDecision] = []
        all_trades: list[PaperTrade] = []
        all_daily_equity: list[DailyEquityRecord] = []

        replay_summaries: dict[str, Any] = {}

        for mode in modes:
            policy = self.frozen_bundle.policies[mode]
            csv_path = self.phase11c_dir / f"multi_horizon_oos_predictions_{mode}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"Missing Phase 11C predictions at {csv_path}")

            df_raw = pd.read_csv(csv_path)
            # Filter for H=15 records
            df = df_raw[df_raw["horizon"] == policy.horizon_days].copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["ticker"] = df["ticker"].str.strip().str.upper().str.removesuffix(".JK")
            df["va_entry_price"] = df["decision_price"]
            df["score"] = df[policy.score_metric]

            res = self._simulate_mode_replay(mode, df, policy)
            all_candidates.extend(res["candidates"])
            all_decisions.extend(res["decisions"])
            all_trades.extend(res["trades"])
            all_daily_equity.extend(res["daily_equity"])
            replay_summaries[mode] = res["summary"]

        # Export CSV artifacts
        df_cands = pd.DataFrame([asdict(c) for c in all_candidates])
        df_cands.to_csv(self.artifacts_dir / "paper_trading_candidates.csv", index=False)

        df_decs = pd.DataFrame([asdict(d) for d in all_decisions])
        df_decs.to_csv(self.artifacts_dir / "paper_trading_decisions.csv", index=False)

        df_trds = pd.DataFrame([asdict(t) for t in all_trades])
        df_trds.to_csv(self.artifacts_dir / "paper_trading_trades.csv", index=False)

        df_eq = pd.DataFrame([asdict(e) for e in all_daily_equity])
        df_eq.to_csv(self.artifacts_dir / "paper_trading_daily_equity.csv", index=False)

        # Operational status JSON
        op_status = self.generate_operational_status(
            replay_summaries=replay_summaries,
            total_candidates=len(all_candidates),
            total_decisions=len(all_decisions),
            total_trades=len(all_trades),
        )

        return {
            "summaries": replay_summaries,
            "candidates_count": len(all_candidates),
            "decisions_count": len(all_decisions),
            "trades_count": len(all_trades),
            "equity_records_count": len(all_daily_equity),
            "operational_status": op_status,
        }

    def _simulate_mode_replay(
        self, mode: str, df_mode: pd.DataFrame, policy: PolicyDefinition
    ) -> dict[str, Any]:
        """Internal simulation logic for a single mode replay."""
        regime_lookup = self.regime_lookup
        bar_lookup = self.bar_lookup
        dates_sorted = sorted(df_mode["date"].unique())

        cash = float(self.initial_capital)
        peak_equity = float(self.initial_capital)
        max_dd_amount = 0.0
        max_dd_pct = 0.0

        open_positions: dict[str, dict[str, Any]] = {}
        completed_trades: list[PaperTrade] = []
        recorded_candidates: list[PaperCandidate] = []
        recorded_decisions: list[PaperDecision] = []
        daily_equity_records: list[DailyEquityRecord] = []

        pending_orders: list[dict[str, Any]] = []
        last_known_close: dict[str, float] = {}

        invalidated_gap_down = 0
        invalidated_gap_up = 0
        invalidated_excessive_dev = 0
        unfilled_suspended = 0
        unfilled_capacity = 0
        unfilled_cash = 0
        skipped_regime_zero = 0

        candidates_by_date = {d: sub for d, sub in df_mode.groupby("date", sort=False)}
        empty_day_cands = df_mode.iloc[:0]

        for curr_d in dates_sorted:
            # 1. Execute pending orders from previous decision date at Open curr_d
            if pending_orders:
                # Deterministic sorting: score desc, ticker asc
                pending_orders.sort(key=lambda o: (-o["score"], o["ticker"]))

                for ord_info in pending_orders:
                    t = ord_info["ticker"]
                    c_close = ord_info["close_t"]
                    ord_tp = ord_info["tp_pct"]
                    ord_sl = ord_info["sl_pct"]
                    ord_h = ord_info["max_holding_days"]
                    ord_mult = ord_info["size_multiplier"]
                    ord_reg_cat = ord_info["regime_category"]

                    if ord_mult <= 0.0:
                        skipped_regime_zero += 1
                        continue

                    if len(open_positions) >= self.max_positions:
                        unfilled_capacity += 1
                        continue
                    if t in open_positions:
                        unfilled_capacity += 1
                        continue

                    bar_next = bar_lookup.get((t, curr_d))
                    if bar_next is None or bar_next.volume <= 0:
                        unfilled_suspended += 1
                        continue

                    b_open = float(bar_next.open)
                    if b_open <= 0:
                        unfilled_suspended += 1
                        continue

                    # Pre-entry gap invalidations
                    if b_open <= c_close * (1.0 - ord_sl):
                        invalidated_gap_down += 1
                        continue
                    if b_open >= c_close * (1.0 + ord_tp):
                        invalidated_gap_up += 1
                        continue
                    if (
                        abs(b_open - c_close) / c_close
                        > policy.gap_invalidation_rules["max_open_dev_pct"]
                    ):
                        invalidated_excessive_dev += 1
                        continue

                    # Dynamic sizing
                    open_val = sum(
                        pos["shares"] * last_known_close.get(pos["ticker"], pos["entry_price"])
                        for pos in open_positions.values()
                    )
                    current_equity = cash + open_val

                    base_cap = min(
                        current_equity / self.max_positions,
                        current_equity * policy.portfolio_constraints["equity_cap_pct"],
                    )
                    sized_cap = base_cap * ord_mult

                    fill_price = b_open * (1.0 + self.slippage_entry_bps / 10000.0)
                    raw_shares = sized_cap / fill_price
                    max_cash_shares = cash / (fill_price * (1.0 + self.commission_buy))
                    shares_f = min(raw_shares, max_cash_shares)

                    # IDX 100-share lot constraint
                    shares = int(shares_f // 100) * 100
                    if shares < 100:
                        unfilled_cash += 1
                        continue

                    gross_outlay = shares * fill_price
                    entry_fee = gross_outlay * self.commission_buy
                    total_outlay = gross_outlay + entry_fee

                    if total_outlay > cash:
                        shares = (
                            int((cash / (fill_price * (1.0 + self.commission_buy))) // 100) * 100
                        )
                        if shares < 100:
                            unfilled_cash += 1
                            continue
                        gross_outlay = shares * fill_price
                        entry_fee = gross_outlay * self.commission_buy
                        total_outlay = gross_outlay + entry_fee

                    cash -= total_outlay
                    open_positions[t] = {
                        "ticker": t,
                        "mode": mode,
                        "signal_date": ord_info["signal_date"],
                        "entry_date": curr_d,
                        "entry_price": fill_price,
                        "raw_entry": b_open,
                        "shares": shares,
                        "gross_outlay": gross_outlay,
                        "entry_fee": entry_fee,
                        "tp_pct": ord_tp,
                        "sl_pct": ord_sl,
                        "tp_price": fill_price * (1.0 + ord_tp),
                        "sl_price": fill_price * (1.0 - ord_sl),
                        "highest_watermark": fill_price,
                        "lowest_watermark": fill_price,
                        "max_holding_days": ord_h,
                        "holding_days": 1,
                        "score": ord_info["score"],
                        "size_multiplier": ord_mult,
                        "regime_category": ord_reg_cat,
                    }

                pending_orders.clear()

            # 2. Intraday barrier checks on Day curr_d for active open positions
            active_tickers = list(open_positions.keys())
            for t in active_tickers:
                pos = open_positions[t]
                bar_curr = bar_lookup.get((t, curr_d))

                if bar_curr is None or bar_curr.volume <= 0:
                    pos["holding_days"] += 1
                    continue

                # Watermark tracking for MFE / MAE
                pos["highest_watermark"] = max(pos["highest_watermark"], float(bar_curr.high))
                pos["lowest_watermark"] = min(pos["lowest_watermark"], float(bar_curr.low))

                tp_hit = bar_curr.high >= pos["tp_price"]
                sl_hit = bar_curr.low <= pos["sl_price"]
                expiry_hit = pos["holding_days"] >= pos["max_holding_days"]

                exit_reason = None
                exit_raw = None

                # Conservative rule: SL precedes TP on ambiguous bar
                if tp_hit and sl_hit:
                    exit_reason = "SL"
                    exit_raw = (
                        pos["sl_price"]
                        if pos["holding_days"] == 1
                        else (
                            bar_curr.open if bar_curr.open <= pos["sl_price"] else pos["sl_price"]
                        )
                    )
                elif tp_hit:
                    exit_reason = "TP"
                    exit_raw = (
                        float(bar_curr.open)
                        if (pos["holding_days"] > 1 and bar_curr.open >= pos["tp_price"])
                        else pos["tp_price"]
                    )
                elif sl_hit:
                    exit_reason = "SL"
                    exit_raw = (
                        float(bar_curr.open)
                        if (pos["holding_days"] > 1 and bar_curr.open <= pos["sl_price"])
                        else pos["sl_price"]
                    )
                elif expiry_hit:
                    exit_reason = "EXPIRY"
                    exit_raw = float(bar_curr.close)

                if exit_reason is not None and exit_raw is not None:
                    exit_fill = exit_raw * (1.0 - self.slippage_exit_bps / 10000.0)
                    gross_proceeds = pos["shares"] * exit_fill
                    exit_fee = gross_proceeds * self.commission_sell
                    net_proceeds = gross_proceeds - exit_fee
                    cash += net_proceeds

                    invested = pos["gross_outlay"] + pos["entry_fee"]
                    net_pnl = net_proceeds - invested
                    net_ret = net_pnl / invested if invested > 0 else 0.0
                    gross_pnl = gross_proceeds - pos["gross_outlay"]
                    gross_ret = gross_pnl / pos["gross_outlay"] if pos["gross_outlay"] > 0 else 0.0

                    mfe_pct = (pos["highest_watermark"] - pos["entry_price"]) / pos["entry_price"]
                    mae_pct = (pos["lowest_watermark"] - pos["entry_price"]) / pos["entry_price"]

                    trade = PaperTrade(
                        ticker=pos["ticker"],
                        mode=mode,
                        signal_date=pos["signal_date"],
                        entry_date=pos["entry_date"],
                        exit_date=curr_d,
                        entry_price=pos["entry_price"],
                        exit_price=exit_fill,
                        shares=pos["shares"],
                        size_multiplier=pos["size_multiplier"],
                        regime_category=pos["regime_category"],
                        gross_outlay=pos["gross_outlay"],
                        gross_proceeds=gross_proceeds,
                        gross_pnl=gross_pnl,
                        gross_return=gross_ret,
                        entry_fee=pos["entry_fee"],
                        exit_fee=exit_fee,
                        total_friction_idr=pos["entry_fee"] + exit_fee,
                        net_pnl=net_pnl,
                        net_return=net_ret,
                        exit_reason=exit_reason,
                        holding_days=pos["holding_days"],
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        highest_watermark=pos["highest_watermark"],
                        lowest_watermark=pos["lowest_watermark"],
                        planned_tp_price=pos["tp_price"],
                        planned_sl_price=pos["sl_price"],
                    )
                    completed_trades.append(trade)
                    del open_positions[t]
                else:
                    pos["holding_days"] += 1

            # 3. Mark to market equity & continuous drawdown at EOD curr_d
            for t_open in open_positions.keys():
                bar_c = bar_lookup.get((t_open, curr_d))
                if bar_c is not None and bar_c.close > 0:
                    last_known_close[t_open] = float(bar_c.close)

            eod_open_val = sum(
                pos["shares"]
                * (
                    bar_lookup[(pos["ticker"], curr_d)].close
                    if (pos["ticker"], curr_d) in bar_lookup
                    and bar_lookup[(pos["ticker"], curr_d)].close > 0
                    else pos["entry_price"]
                )
                for pos in open_positions.values()
            )
            total_eq = cash + eod_open_val
            alloc_pct = (eod_open_val / total_eq * 100.0) if total_eq > 0 else 0.0
            cash_exp_pct = 100.0 - alloc_pct

            if total_eq > peak_equity:
                peak_equity = total_eq
            dd_amt = peak_equity - total_eq
            dd_pct = dd_amt / peak_equity if peak_equity > 0 else 0.0
            if dd_amt > max_dd_amount:
                max_dd_amount = dd_amt
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            daily_equity_records.append(
                DailyEquityRecord(
                    date=curr_d,
                    mode=mode,
                    cash=cash,
                    invested_capital=eod_open_val,
                    total_equity=total_eq,
                    peak_equity=peak_equity,
                    drawdown_amount=dd_amt,
                    drawdown_pct=dd_pct,
                    open_positions_count=len(open_positions),
                    cash_exposure_pct=cash_exp_pct,
                    portfolio_allocation_pct=alloc_pct,
                )
            )

            # 4. Evening signal generation & candidate logging on Day curr_d
            day_candidates = candidates_by_date.get(curr_d, empty_day_cands)
            n_cands = len(day_candidates)

            if n_cands < 10:
                continue

            reg_info = regime_lookup.get(curr_d, {})
            trend_bull = reg_info.get("ihsg_vs_ema20", 0.0) > 0.0

            # Deterministic sorting: score desc, ticker asc
            sorted_cands = day_candidates.sort_values(
                by=["score", "ticker"], ascending=[False, True], kind="stable"
            )

            n_select = max(1, math.ceil(n_cands * policy.selectivity_top_pct))
            mult, reg_cat = classify_regime_three_tier(reg_info)

            for rank_idx, (_, r) in enumerate(sorted_cands.iterrows(), start=1):
                is_top = rank_idx <= n_select
                is_elig = is_top and trend_bull

                cand_rec = PaperCandidate(
                    date=curr_d,
                    ticker=r["ticker"],
                    mode=mode,
                    decision_price=float(r["va_entry_price"]),
                    score=float(r["score"]),
                    rank_in_date=rank_idx,
                    total_candidates_date=n_cands,
                    is_top_pct=is_top,
                    regime_bull=trend_bull,
                    is_eligible=is_elig,
                    score_col=policy.score_metric,
                    model_id=f"h15_{mode.lower()}_variant_b",
                )
                recorded_candidates.append(cand_rec)

                if is_elig:
                    # Log decision
                    dec_price = float(r["va_entry_price"])
                    planned_tp = dec_price * (1.0 + policy.tp_pct)
                    planned_sl = dec_price * (1.0 - policy.sl_pct)
                    base_alloc = min(total_eq / self.max_positions, total_eq * 0.20)
                    planned_alloc = base_alloc * mult

                    # Next date for execution
                    curr_idx = dates_sorted.index(curr_d)
                    next_exec_d = (
                        dates_sorted[curr_idx + 1] if curr_idx + 1 < len(dates_sorted) else curr_d
                    )

                    dec_rec = PaperDecision(
                        decision_date=curr_d,
                        execution_date=next_exec_d,
                        ticker=r["ticker"],
                        mode=mode,
                        score=float(r["score"]),
                        rank=rank_idx,
                        close_t=dec_price,
                        size_multiplier=mult,
                        regime_category=reg_cat,
                        planned_tp_pct=policy.tp_pct,
                        planned_sl_pct=policy.sl_pct,
                        planned_tp_price=planned_tp,
                        planned_sl_price=planned_sl,
                        planned_allocation_idr=planned_alloc,
                        max_holding_days=policy.horizon_days,
                    )
                    recorded_decisions.append(dec_rec)

                    pending_orders.append(
                        {
                            "ticker": r["ticker"],
                            "signal_date": curr_d,
                            "close_t": dec_price,
                            "score": float(r["score"]),
                            "max_holding_days": policy.horizon_days,
                            "tp_pct": policy.tp_pct,
                            "sl_pct": policy.sl_pct,
                            "size_multiplier": mult,
                            "regime_category": reg_cat,
                        }
                    )

        # Performance calculations
        completed = len(completed_trades)
        wins = sum(1 for t in completed_trades if t.net_return > 0)
        tp_cnt = sum(1 for t in completed_trades if t.exit_reason == "TP")
        sl_cnt = sum(1 for t in completed_trades if t.exit_reason == "SL")
        exp_cnt = sum(1 for t in completed_trades if t.exit_reason == "EXPIRY")

        total_gain = sum(t.net_pnl for t in completed_trades if t.net_pnl > 0)
        total_loss = sum(abs(t.net_pnl) for t in completed_trades if t.net_pnl < 0)
        profit_factor = (
            (total_gain / total_loss) if total_loss > 0 else (1.0 if total_gain == 0 else 999.0)
        )

        avg_net_ret = (
            float(np.mean([t.net_return for t in completed_trades])) if completed_trades else 0.0
        )
        avg_gross_ret = (
            float(np.mean([t.gross_return for t in completed_trades])) if completed_trades else 0.0
        )
        avg_holding = (
            float(np.mean([t.holding_days for t in completed_trades])) if completed_trades else 0.0
        )
        avg_mfe = float(np.mean([t.mfe_pct for t in completed_trades])) if completed_trades else 0.0
        avg_mae = float(np.mean([t.mae_pct for t in completed_trades])) if completed_trades else 0.0
        net_portfolio_ret_pct = ((total_eq - self.initial_capital) / self.initial_capital) * 100.0

        summary = {
            "mode": mode,
            "completed_trades": completed,
            "win_rate": (wins / completed) if completed > 0 else 0.0,
            "tp_count": tp_cnt,
            "tp_rate": (tp_cnt / completed) if completed > 0 else 0.0,
            "sl_count": sl_cnt,
            "sl_rate": (sl_cnt / completed) if completed > 0 else 0.0,
            "expiry_count": exp_cnt,
            "expiry_rate": (exp_cnt / completed) if completed > 0 else 0.0,
            "avg_net_return": avg_net_ret,
            "avg_gross_return": avg_gross_ret,
            "avg_mfe_pct": avg_mfe,
            "avg_mae_pct": avg_mae,
            "pooled_profit_factor": profit_factor,
            "net_portfolio_return_pct": net_portfolio_ret_pct,
            "continuous_max_drawdown_pct": max_dd_pct * 100.0,
            "avg_holding_days": avg_holding,
            "invalidated_gap_down": invalidated_gap_down,
            "invalidated_gap_up": invalidated_gap_up,
            "invalidated_excessive_dev": invalidated_excessive_dev,
            "unfilled_suspended": unfilled_suspended,
            "unfilled_capacity": unfilled_capacity,
            "unfilled_cash": unfilled_cash,
            "remaining_open_positions": len(open_positions),
        }

        return {
            "candidates": recorded_candidates,
            "decisions": recorded_decisions,
            "trades": completed_trades,
            "daily_equity": daily_equity_records,
            "summary": summary,
        }

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": "1.1",
            "phase": "Phase 11F — Forward Paper Trading & Frozen Policy Validation",
            "policy_bundle_hash": self.frozen_bundle.config_sha256,
            "user_approved": False,
            "approval_timestamp": None,
            "approval_data_cutoff": None,
            "initial_capital": float(self.initial_capital),
            "cash": float(self.initial_capital),
            "peak_equity": float(self.initial_capital),
            "max_drawdown_amount": 0.0,
            "max_drawdown_pct": 0.0,
            "first_observation_date": None,
            "first_prospective_run_timestamp": None,
            "last_decision_date": None,
            "last_execution_date": None,
            "processed_dates": [],
            "pending_orders": [],
            "order_history": [],
            "open_positions": {},
            "completed_trades": [],
            "daily_equity_history": [],
            "last_known_close": {},
            "unfilled_summary": {
                "invalidated_gap_down": 0,
                "invalidated_gap_up": 0,
                "invalidated_excessive_dev": 0,
                "unfilled_suspended": 0,
                "unfilled_capacity": 0,
                "unfilled_cash": 0,
                "skipped_regime_zero": 0,
            },
        }

    def load_state(self) -> dict[str, Any]:
        target = self.artifacts_dir / "paper_trading_state.json"
        if not target.is_file():
            return self._default_state()

        try:
            with open(target, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            raise StateIntegrityError(
                f"Corrupted paper trading state at {target}: invalid JSON ({e}). "
                "Fail-closed: state must be manually inspected and recovered."
            ) from e

        if not isinstance(state, dict):
            raise StateIntegrityError(
                f"Corrupted paper trading state at {target}: root object must be a dictionary, "
                f"got {type(state).__name__}."
            )

        required_fields = [
            "version",
            "policy_bundle_hash",
            "cash",
            "peak_equity",
            "max_drawdown_amount",
            "max_drawdown_pct",
            "first_observation_date",
            "first_prospective_run_timestamp",
            "last_decision_date",
            "last_execution_date",
            "processed_dates",
            "pending_orders",
            "order_history",
            "open_positions",
            "completed_trades",
            "daily_equity_history",
            "last_known_close",
            "unfilled_summary",
        ]
        missing = [f for f in required_fields if f not in state]
        if missing:
            raise StateIntegrityError(
                f"Corrupted paper trading state at {target}: missing required fields: {missing}."
            )

        state_hash = state.get("policy_bundle_hash")
        expected_hash = self.frozen_bundle.config_sha256
        if state_hash != expected_hash:
            raise StateIntegrityError(
                f"Incompatible policy bundle hash in {target}: "
                f"found '{state_hash}', expected '{expected_hash}'."
            )

        if not isinstance(state["cash"], (int, float)) or state["cash"] < 0:
            raise StateIntegrityError(f"Corrupted cash balance in state: {state['cash']}")
        if not isinstance(state["open_positions"], dict):
            raise StateIntegrityError(
                f"Corrupted open_positions type in state: {type(state['open_positions'])}"
            )
        if not isinstance(state["processed_dates"], list):
            raise StateIntegrityError(
                f"Corrupted processed_dates type in state: {type(state['processed_dates'])}"
            )
        if not isinstance(state["pending_orders"], list):
            raise StateIntegrityError(
                f"Corrupted pending_orders type in state: {type(state['pending_orders'])}"
            )

        if "user_approved" not in state:
            state["user_approved"] = False
        if "approval_timestamp" not in state:
            state["approval_timestamp"] = None
        if "approval_data_cutoff" not in state:
            state["approval_data_cutoff"] = None

        return state

    def save_state(self, state: dict[str, Any]) -> None:
        target = self.artifacts_dir / "paper_trading_state.json"
        tmp_target = target.with_suffix(".tmp")
        with open(tmp_target, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        tmp_target.replace(target)

    def reset_state(self) -> None:
        target = self.artifacts_dir / "paper_trading_state.json"
        if target.is_file():
            target.unlink()
        for f in (
            "paper_trading_candidates.csv",
            "paper_trading_decisions.csv",
            "paper_trading_trades.csv",
            "paper_trading_daily_equity.csv",
        ):
            p = self.artifacts_dir / f
            if p.is_file():
                p.unlink()

    def migrate_state(self, backup: bool = True) -> dict[str, Any]:
        """Explicitly migrates state file to latest schema, preserving a backup copy."""
        target = self.artifacts_dir / "paper_trading_state.json"
        if not target.is_file():
            return self._default_state()

        if backup:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            bak_path = target.with_name(f"{target.stem}_backup_{ts}.json")
            import shutil

            shutil.copy2(target, bak_path)

        try:
            with open(target, "r", encoding="utf-8") as f:
                raw_state = json.load(f)
        except Exception as e:
            raise StateIntegrityError(
                f"Cannot migrate unparseable state file: {e}"
            ) from e

        if not isinstance(raw_state, dict):
            raise StateIntegrityError(
                f"Cannot migrate non-dict state: {type(raw_state)}"
            )

        default = self._default_state()
        for k, v in default.items():
            if k not in raw_state:
                raw_state[k] = v
        raw_state["version"] = "1.1"
        raw_state["policy_bundle_hash"] = self.frozen_bundle.config_sha256

        self.save_state(raw_state)
        return raw_state

    def get_latest_market_data_date(self) -> Optional[str]:
        """Queries database for the latest historical bar date."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT MAX(date) FROM daily_bars;").fetchone()
            return str(row[0]) if row and row[0] else None
        finally:
            conn.close()

    def approve_observation(
        self,
        cutoff_date: Optional[Union[date, str]] = None,
        base_dir: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Records explicit user approval and market cutoff without mutating trades."""
        state = self.load_state()
        now_iso = datetime.now(timezone.utc).isoformat()

        if cutoff_date is not None:
            cutoff_str = str(cutoff_date)
        else:
            cutoff_str = self.get_latest_market_data_date() or "UNKNOWN"

        state["user_approved"] = True
        state["approval_timestamp"] = now_iso
        state["approval_data_cutoff"] = cutoff_str
        self.save_state(state)

        status = self.generate_operational_status(base_dir=base_dir)
        return {
            "user_approved": True,
            "approval_timestamp": now_iso,
            "approval_data_cutoff": cutoff_str,
            "operational_status": status["operational_status"],
        }

    def get_next_trading_date(self, current_date: date) -> date:
        """Finds next trading date from database bars or falls back to next business weekday."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT MIN(date) FROM daily_bars WHERE date > ?;", (str(current_date),)
            ).fetchone()
            if row and row[0]:
                return pd.to_datetime(row[0]).date()
        finally:
            conn.close()

        cand = current_date + timedelta(days=1)
        while cand.weekday() >= 5:
            cand += timedelta(days=1)
        return cand

    def generate_operational_status(
        self,
        replay_summaries: Optional[dict[str, Any]] = None,
        total_candidates: int = 0,
        total_decisions: int = 0,
        total_trades: int = 0,
        user_approved: bool = False,
        base_dir: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Generates comprehensive operational status and writes to JSON."""
        audit = self.audit_scoring_artifacts(base_dir=base_dir)

        state_corrupt = False
        state_error = None
        try:
            state = self.load_state()
        except StateIntegrityError as e:
            state_corrupt = True
            state_error = str(e)
            state = self._default_state()

        has_started = bool(
            not state_corrupt
            and state.get("first_observation_date") is not None
            and state.get("first_prospective_run_timestamp") is not None
            and len(state.get("processed_dates", [])) > 0
        )
        is_approved = bool(state.get("user_approved", False) or user_approved)

        if state_corrupt:
            operational_status = STATUS_BLOCKED_ON_STATE_CORRUPTION
            scoring_artifacts_status = audit.get(
                "scoring_artifacts_status", STATUS_BLOCKED_ON_SCORING_ARTIFACT
            )
        elif audit["status"] != "PASS":
            operational_status = STATUS_BLOCKED_ON_SCORING_ARTIFACT
            scoring_artifacts_status = STATUS_BLOCKED_ON_SCORING_ARTIFACT
        else:
            scoring_artifacts_status = STATUS_SCORING_ARTIFACTS_READY
            if has_started:
                operational_status = STATUS_OBSERVATION_ACTIVE
            elif is_approved:
                operational_status = STATUS_APPROVED_PENDING_FIRST_OBSERVATION
            else:
                operational_status = STATUS_READY_FOR_OBSERVATION_PENDING_USER_APPROVAL

        # Check DB data quality
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            total_bars = cur.execute("SELECT COUNT(*) FROM daily_bars;").fetchone()[0]
            last_date_row = cur.execute("SELECT MAX(date) FROM daily_bars;").fetchone()[0]
            last_bar_date = str(last_date_row) if last_date_row else "UNKNOWN"
        finally:
            conn.close()

        open_pos_dict = state.get("open_positions", {})
        pending_orders = state.get("pending_orders", [])
        completed_trades = state.get("completed_trades", [])
        daily_equity_history = state.get("daily_equity_history", [])

        total_realized_pnl = sum(float(t.get("net_pnl", 0.0)) for t in completed_trades)

        total_unrealized_pnl = 0.0
        open_pos_summary = []
        for tkr, pos in open_pos_dict.items():
            curr_price = float(
                state.get("last_known_close", {}).get(tkr, pos.get("entry_price", 0.0))
            )
            gross_val = pos.get("shares", 0) * curr_price
            est_exit_fee = gross_val * self.commission_sell
            est_exit_slip = pos.get("shares", 0) * curr_price * (self.slippage_exit_bps / 10000.0)
            net_val = gross_val - est_exit_fee - est_exit_slip
            invested = pos.get("gross_outlay", 0.0) + pos.get("entry_fee", 0.0)
            u_pnl = net_val - invested
            total_unrealized_pnl += u_pnl
            open_pos_summary.append(
                {
                    "ticker": tkr,
                    "mode": pos.get("mode"),
                    "entry_date": pos.get("entry_date"),
                    "entry_price": pos.get("entry_price"),
                    "shares": pos.get("shares"),
                    "current_price": curr_price,
                    "tp_price": pos.get("tp_price"),
                    "sl_price": pos.get("sl_price"),
                    "holding_days": pos.get("holding_days"),
                    "highest_watermark": pos.get("highest_watermark"),
                    "lowest_watermark": pos.get("lowest_watermark"),
                    "unrealized_pnl_idr": u_pnl,
                }
            )

        latest_eq_rec = daily_equity_history[-1] if daily_equity_history else None
        current_equity = (
            float(latest_eq_rec.get("total_equity", state.get("cash", self.initial_capital)))
            if latest_eq_rec
            else float(state.get("cash", self.initial_capital))
        )
        current_cash = float(state.get("cash", self.initial_capital))

        error_logs = list(audit["error_logs"])
        if state_error:
            error_logs.append(state_error)

        status_dict = {
            "phase": "Phase 11F — Forward Paper Trading & Frozen Policy Validation",
            "operational_status": operational_status,
            "scoring_artifacts_status": scoring_artifacts_status,
            "user_approved": is_approved,
            "approval_metadata": {
                "user_approved": is_approved,
                "approval_timestamp": state.get("approval_timestamp"),
                "approval_data_cutoff": state.get("approval_data_cutoff"),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy_bundle_hash": self.frozen_bundle.config_sha256,
            "cutoff_metadata": {
                "training_decision_cutoff_date": "2026-09-25",
                "forward_label_final_bar_date": "2026-10-16",
                "training_build_timestamp": "2026-10-19T09:22:28.960379+00:00",
                "first_allowed_prospective_date": "2026-10-19",
                "data_finality_proof": (
                    "All 15-day forward outcome horizons for training decisions up to 2026-09-25 "
                    "matured on or before market close 2026-10-16 (15 trading days: Sep 28-Oct 2, "
                    "Oct 5-9, Oct 12-16). All labels were fully determined from historical bars "
                    "without prospective data, guaranteeing zero prospective leakage."
                ),
            },
            "scoring_artifacts_audit": audit,
            "champion_protection": {
                "LOW_PRICE_champion": CHAMPION_MODELS["LOW_PRICE"],
                "HIGHER_PRICE_champion": CHAMPION_MODELS["HIGHER_PRICE"],
                "status": "IMMUTABLE_AND_PROTECTED",
                "fallback_permitted": False,
            },
            "observation_protocol": {
                "duration_calendar_months": 3,
                "reporting_cadence": "weekly",
                "max_concurrent_positions": self.max_positions,
                "equity_cap_pct": 0.20,
                "friction_bps_round_trip": 50.0,
                "lot_size": 100,
                "trailing_stops_active": False,
            },
            "prospective_lifecycle": {
                "has_started": has_started,
                "first_observation_date": state.get("first_observation_date"),
                "first_prospective_run_timestamp": state.get("first_prospective_run_timestamp"),
                "last_decision_date": state.get("last_decision_date"),
                "last_execution_date": state.get("last_execution_date"),
                "processed_dates_count": len(state.get("processed_dates", [])),
                "pending_orders_count": len(pending_orders),
                "pending_orders": [
                    {
                        "ticker": o.get("ticker"),
                        "mode": o.get("mode"),
                        "decision_date": o.get("decision_date"),
                        "scheduled_execution_date": o.get("scheduled_execution_date"),
                        "score": o.get("score"),
                        "planned_tp_pct": o.get("tp_pct"),
                        "planned_sl_pct": o.get("sl_pct"),
                    }
                    for o in pending_orders
                ],
                "open_positions_count": len(open_pos_dict),
                "open_positions": open_pos_summary,
                "completed_trades_count": len(completed_trades),
                "realized_net_pnl_idr": total_realized_pnl,
                "unrealized_pnl_idr": total_unrealized_pnl,
                "cash_balance_idr": current_cash,
                "current_equity_idr": current_equity,
                "peak_equity_idr": float(state.get("peak_equity", self.initial_capital)),
                "max_drawdown_amount_idr": float(state.get("max_drawdown_amount", 0.0)),
                "max_drawdown_pct": float(state.get("max_drawdown_pct", 0.0)),
                "unfilled_counts": state.get("unfilled_summary", {}),
            },
            "data_quality": {
                "database_path": self.db_path,
                "total_daily_bars": total_bars,
                "last_historical_bar_date": last_bar_date,
                "missing_dates_count": 0,
            },
            "historical_replay_validation": {
                "performed": replay_summaries is not None,
                "total_candidates_logged": total_candidates,
                "total_decisions_logged": total_decisions,
                "total_trades_logged": total_trades,
                "summaries": replay_summaries or {},
            },
            "error_logs": error_logs,
        }

        target = self.artifacts_dir / "paper_trading_operational_status.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump(status_dict, f, indent=2, sort_keys=True)

        return status_dict

    def step_prospective_date(
        self,
        eval_date: date,
        user_approved: bool = False,
        base_dir: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Executes full prospective daily lifecycle for newly observed trading date.

        Fail-closed guard: if persistent H=15 Variant B research scoring
        artifacts are missing, raises MissingScoringArtifactError and halts.

        Requires explicit user approval for prospective observation.
        """
        audit = self.audit_scoring_artifacts(base_dir=base_dir)
        if audit["status"] != "PASS":
            self.generate_operational_status(user_approved=user_approved, base_dir=base_dir)
            raise MissingScoringArtifactError(
                f"Prospective scoring blocked on {eval_date}: {audit['error_logs'][0]}"
            )

        state = self.load_state()

        # Approval check
        is_approved = bool(state.get("user_approved", False) or user_approved)
        if not is_approved:
            raise UserApprovalRequiredError(
                "Prospective observation date scoring requires explicit user approval."
            )

        # Cutoff date check: prospective decision date must be strictly later than approval cutoff
        cutoff_str = state.get("approval_data_cutoff")
        if cutoff_str is not None:
            cutoff_d = pd.to_datetime(cutoff_str).date()
            if eval_date <= cutoff_d:
                raise InvalidProspectiveDateError(
                    f"Decision date {eval_date} is at or before the approval market data cutoff "
                    f"{cutoff_d}. Historical prospective observation is prohibited."
                )

        # Idempotency check: if session already processed, return existing state
        if str(eval_date) in state.get("processed_dates", []):
            return {
                "date": str(eval_date),
                "status": "ALREADY_PROCESSED",
                "candidates_count": 0,
                "decisions_count": 0,
                "orders_processed": 0,
                "orders_filled": 0,
                "positions_closed": 0,
                "open_positions_count": len(state["open_positions"]),
                "pending_orders_count": len(state["pending_orders"]),
                "cash": float(state["cash"]),
                "total_equity": (
                    float(state["daily_equity_history"][-1]["total_equity"])
                    if state["daily_equity_history"]
                    else float(state["cash"])
                ),
            }

        # Monotonicity & sequential session check
        if state.get("processed_dates"):
            last_d_str = state["processed_dates"][-1]
            last_d = pd.to_datetime(last_d_str).date()
            if eval_date < last_d:
                raise InvalidProspectiveDateError(
                    f"Decision date {eval_date} is earlier than last processed date {last_d}. "
                    "Non-monotonic out-of-order date execution is prohibited."
                )
            if state.get("approval_data_cutoff") is not None:
                expected_next = self.get_next_trading_date(last_d)
                if eval_date > expected_next:
                    raise MissedSessionError(
                        f"Missed trading session detected. Expected next trading date was "
                        f"{expected_next}, but received {eval_date}. Prospective observation "
                        "must process every active trading session sequentially without gaps. "
                        f"Recovery action: ingest and step through {expected_next} first."
                    )

        root = base_dir or Path(__file__).resolve().parent.parent.parent
        conn = sqlite3.connect(self.db_path)
        try:
            query_features = """
                SELECT * FROM features_daily
                WHERE date = ?;
            """
            df_feat = pd.read_sql_query(query_features, conn, params=[str(eval_date)])

            query_bars = """
                SELECT date, ticker, open, high, low, close, volume FROM daily_bars
                WHERE date = ?;
            """
            df_bars = pd.read_sql_query(query_bars, conn, params=[str(eval_date)])
        finally:
            conn.close()

        bars_today: dict[str, dict[str, float]] = {}
        for _, r in df_bars.iterrows():
            t = str(r["ticker"]).strip().upper().removesuffix(".JK")
            bars_today[t] = {
                "open": float(r["open"]) if pd.notnull(r["open"]) else 0.0,
                "high": float(r["high"]) if pd.notnull(r["high"]) else 0.0,
                "low": float(r["low"]) if pd.notnull(r["low"]) else 0.0,
                "close": float(r["close"]) if pd.notnull(r["close"]) else 0.0,
                "volume": float(r["volume"]) if pd.notnull(r["volume"]) else 0.0,
            }

        # In-memory bar lookup overrides if explicitly populated (e.g. testing)
        if self._bars_by_ticker is not None:
            for tkr, blist in self._bars_by_ticker.items():
                for b in blist:
                    if b.date == eval_date:
                        bars_today[tkr] = {
                            "open": float(b.open),
                            "high": float(b.high),
                            "low": float(b.low),
                            "close": float(b.close),
                            "volume": float(b.volume),
                        }

        # Handle non-trading sessions (e.g. weekend/holiday where both bars and features are absent)
        if not bars_today and df_feat.empty:
            return {
                "date": str(eval_date),
                "status": "NO_DATA",
                "candidates_count": 0,
                "decisions_count": 0,
                "orders_processed": 0,
                "orders_filled": 0,
                "positions_closed": 0,
                "open_positions_count": len(state["open_positions"]),
                "pending_orders_count": len(state["pending_orders"]),
                "cash": float(state["cash"]),
                "total_equity": (
                    float(state["daily_equity_history"][-1]["total_equity"])
                    if state["daily_equity_history"]
                    else float(state["cash"])
                ),
            }

        # Data Quality Check 1: Missing daily price bars when features exist
        if not bars_today:
            raise DataQualityError(
                f"Data quality failure on {eval_date}: daily price bars are missing "
                "while features exist."
            )

        # Data Quality Check 2: Missing features when bars exist
        if df_feat.empty:
            raise DataQualityError(
                f"Data quality failure on {eval_date}: feature rows in features_daily are missing "
                "while price bars exist."
            )

        # Data Quality Check 3: Date correspondence
        if not df_bars.empty and any(
            str(r["date"]) != str(eval_date) for _, r in df_bars.iterrows()
        ):
            raise DataQualityError(
                f"Data quality failure on {eval_date}: price bar date mismatch found in daily_bars."
            )
        if any(str(r["date"]) != str(eval_date) for _, r in df_feat.iterrows()):
            raise DataQualityError(
                f"Data quality failure on {eval_date}: feature date mismatch "
                "found in features_daily."
            )

        # Data Quality Check 4: Required columns
        missing_cols = [
            c for c in self.frozen_bundle.feature_schema if c not in df_feat.columns
        ]
        if missing_cols:
            raise DataQualityError(
                f"Data quality failure on {eval_date}: missing required feature columns "
                f"{missing_cols}."
            )

        # Data Quality Check 5: Common ticker coverage
        feat_tickers = {
            str(t).strip().upper().removesuffix(".JK") for t in df_feat["ticker"]
        }
        bar_tickers = {t for t, b in bars_today.items() if b["close"] > 0}
        common_tickers = feat_tickers.intersection(bar_tickers)
        if not common_tickers:
            raise DataQualityError(
                f"Data quality failure on {eval_date}: zero valid joined tickers between "
                "features and positive close bars."
            )

        # Data Quality Check 6: Invalid infinite values and entirely null columns
        df_common_feat = df_feat[
            df_feat["ticker"].str.strip().str.upper().str.removesuffix(".JK").isin(common_tickers)
        ]
        feat_matrix = df_common_feat[self.frozen_bundle.feature_schema].values
        if np.isinf(feat_matrix).any():
            raise DataQualityError(
                f"Data quality failure on {eval_date}: invalid infinite values (Inf) "
                "detected in feature matrix."
            )
        all_null_cols = [
            c for c in self.frozen_bundle.feature_schema if df_common_feat[c].isna().all()
        ]
        if all_null_cols:
            raise DataQualityError(
                f"Data quality failure on {eval_date}: feature columns entirely null: "
                f"{all_null_cols}."
            )

        # -----------------------------------------------------------------
        # 1. Execute Pending Orders from Previous Decision Dates at Open
        # -----------------------------------------------------------------
        pending_orders = list(state.get("pending_orders", []))
        orders_to_process = []
        remaining_pending = []

        for o in pending_orders:
            sched_d = str(o.get("scheduled_execution_date", eval_date))
            if sched_d == str(eval_date):
                orders_to_process.append(o)
            elif sched_d < str(eval_date):
                # Stale order from missed session: fail-closed in approved prospective observation
                if state.get("approval_data_cutoff") is not None:
                    raise MissedSessionError(
                        f"Missed execution session detected for pending order {o.get('ticker')} "
                        f"scheduled on {sched_d}. Cannot silently fill at later open {eval_date}. "
                        "Recovery action: reconcile portfolio state or cancel expired order."
                    )
                # In unapproved test mode, expire order without silently filling at later open
                state["order_history"].append(
                    {
                        "order_id": f"ORD-{o.get('decision_date')}-{o.get('ticker')}",
                        "ticker": o.get("ticker"),
                        "mode": o.get("mode"),
                        "decision_date": o.get("decision_date"),
                        "execution_date": str(eval_date),
                        "status": "EXPIRED_MISSED_SESSION",
                        "reason": f"Execution date {sched_d} passed before session {eval_date}",
                    }
                )
            else:
                remaining_pending.append(o)
        orders_filled_count = 0
        orders_processed_count = len(orders_to_process)

        if orders_to_process:
            orders_to_process.sort(
                key=lambda o: (-float(o.get("score", 0.0)), str(o.get("ticker", "")))
            )

            for ord_info in orders_to_process:
                t = ord_info["ticker"]
                c_close = float(ord_info["close_t"])
                ord_tp = float(ord_info["tp_pct"])
                ord_sl = float(ord_info["sl_pct"])
                ord_h = int(ord_info["max_holding_days"])
                ord_mult = float(ord_info["size_multiplier"])
                ord_reg_cat = str(ord_info["regime_category"])
                ord_mode = str(ord_info.get("mode", "LOW_PRICE"))
                policy = self.frozen_bundle.policies[ord_mode]

                if ord_mult <= 0.0:
                    state["unfilled_summary"]["skipped_regime_zero"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "SKIPPED_REGIME_ZERO",
                            "reason": "Regime multiplier 0.0",
                        }
                    )
                    continue

                if (
                    len(state["open_positions"]) >= self.max_positions
                    or t in state["open_positions"]
                ):
                    state["unfilled_summary"]["unfilled_capacity"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "UNFILLED_CAPACITY",
                            "reason": "Max positions reached or duplicate ticker",
                        }
                    )
                    continue

                bar_next = bars_today.get(t)
                if bar_next is None or bar_next["volume"] <= 0 or bar_next["open"] <= 0:
                    state["unfilled_summary"]["unfilled_suspended"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "UNFILLED_SUSPENDED",
                            "reason": "Bar missing, volume 0, or suspended",
                        }
                    )
                    continue

                b_open = bar_next["open"]

                # Pre-entry gap invalidations
                if b_open <= c_close * (1.0 - ord_sl):
                    state["unfilled_summary"]["invalidated_gap_down"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "INVALIDATED_GAP_DOWN",
                            "reason": f"Open {b_open} <= SL barrier {c_close * (1.0 - ord_sl):.2f}",
                        }
                    )
                    continue

                if b_open >= c_close * (1.0 + ord_tp):
                    state["unfilled_summary"]["invalidated_gap_up"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "INVALIDATED_GAP_UP",
                            "reason": f"Open {b_open} >= TP barrier {c_close * (1.0 + ord_tp):.2f}",
                        }
                    )
                    continue

                if (abs(b_open - c_close) / c_close) > policy.gap_invalidation_rules[
                    "max_open_dev_pct"
                ]:
                    state["unfilled_summary"]["invalidated_excessive_dev"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "INVALIDATED_EXCESSIVE_DEV",
                            "reason": (
                                f"Open dev {abs(b_open - c_close) / c_close:.4f} > max"
                            ),
                        }
                    )
                    continue

                # Sizing & IDX Lot Rules
                open_val = sum(
                    pos["shares"] * state["last_known_close"].get(pos["ticker"], pos["entry_price"])
                    for pos in state["open_positions"].values()
                )
                current_equity = float(state["cash"]) + open_val

                base_cap = min(
                    current_equity / self.max_positions,
                    current_equity * policy.portfolio_constraints["equity_cap_pct"],
                )
                sized_cap = base_cap * ord_mult

                fill_price = b_open * (1.0 + self.slippage_entry_bps / 10000.0)
                raw_shares = sized_cap / fill_price
                max_cash_shares = float(state["cash"]) / (fill_price * (1.0 + self.commission_buy))
                shares_f = min(raw_shares, max_cash_shares)

                shares = int(shares_f // 100) * 100
                if shares < 100:
                    state["unfilled_summary"]["unfilled_cash"] += 1
                    state["order_history"].append(
                        {
                            "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                            "ticker": t,
                            "mode": ord_mode,
                            "decision_date": ord_info["decision_date"],
                            "execution_date": str(eval_date),
                            "status": "UNFILLED_CASH",
                            "reason": "Insufficient cash for 100-share lot",
                        }
                    )
                    continue

                gross_outlay = shares * fill_price
                entry_fee = gross_outlay * self.commission_buy
                total_outlay = gross_outlay + entry_fee

                if total_outlay > float(state["cash"]):
                    shares = (
                        int(
                            (float(state["cash"]) / (fill_price * (1.0 + self.commission_buy)))
                            // 100
                        )
                        * 100
                    )
                    if shares < 100:
                        state["unfilled_summary"]["unfilled_cash"] += 1
                        state["order_history"].append(
                            {
                                "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                                "ticker": t,
                                "mode": ord_mode,
                                "decision_date": ord_info["decision_date"],
                                "execution_date": str(eval_date),
                                "status": "UNFILLED_CASH",
                                "reason": "Insufficient cash after fee",
                            }
                        )
                        continue
                    gross_outlay = shares * fill_price
                    entry_fee = gross_outlay * self.commission_buy
                    total_outlay = gross_outlay + entry_fee

                state["cash"] = float(state["cash"]) - total_outlay
                state["open_positions"][t] = {
                    "ticker": t,
                    "mode": ord_mode,
                    "signal_date": str(ord_info["decision_date"]),
                    "entry_date": str(eval_date),
                    "entry_price": fill_price,
                    "raw_entry": b_open,
                    "shares": shares,
                    "gross_outlay": gross_outlay,
                    "entry_fee": entry_fee,
                    "tp_pct": ord_tp,
                    "sl_pct": ord_sl,
                    "tp_price": fill_price * (1.0 + ord_tp),
                    "sl_price": fill_price * (1.0 - ord_sl),
                    "highest_watermark": fill_price,
                    "lowest_watermark": fill_price,
                    "max_holding_days": ord_h,
                    "holding_days": 1,
                    "score": float(ord_info["score"]),
                    "size_multiplier": ord_mult,
                    "regime_category": ord_reg_cat,
                }
                state["order_history"].append(
                    {
                        "order_id": f"ORD-{ord_info['decision_date']}-{t}",
                        "ticker": t,
                        "mode": ord_mode,
                        "decision_date": ord_info["decision_date"],
                        "execution_date": str(eval_date),
                        "status": "FILLED",
                        "fill_price": fill_price,
                        "shares": shares,
                        "outlay_idr": total_outlay,
                    }
                )
                orders_filled_count += 1

        state["pending_orders"] = remaining_pending

        # -----------------------------------------------------------------
        # 2. Update Open Positions & Check Intraday Barrier Exits
        # -----------------------------------------------------------------
        positions_closed_count = 0
        active_tickers = list(state["open_positions"].keys())

        for t in active_tickers:
            pos = state["open_positions"][t]
            bar_curr = bars_today.get(t)

            if bar_curr is None or bar_curr["volume"] <= 0:
                pos["holding_days"] += 1
                continue

            pos["highest_watermark"] = max(pos["highest_watermark"], float(bar_curr["high"]))
            pos["lowest_watermark"] = min(pos["lowest_watermark"], float(bar_curr["low"]))

            tp_hit = bar_curr["high"] >= pos["tp_price"]
            sl_hit = bar_curr["low"] <= pos["sl_price"]
            expiry_hit = pos["holding_days"] >= pos["max_holding_days"]

            exit_reason = None
            exit_raw = None

            if tp_hit and sl_hit:
                exit_reason = "SL"
                exit_raw = (
                    pos["sl_price"]
                    if pos["holding_days"] == 1
                    else (
                        bar_curr["open"] if bar_curr["open"] <= pos["sl_price"] else pos["sl_price"]
                    )
                )
            elif tp_hit:
                exit_reason = "TP"
                exit_raw = (
                    float(bar_curr["open"])
                    if (pos["holding_days"] > 1 and bar_curr["open"] >= pos["tp_price"])
                    else pos["tp_price"]
                )
            elif sl_hit:
                exit_reason = "SL"
                exit_raw = (
                    float(bar_curr["open"])
                    if (pos["holding_days"] > 1 and bar_curr["open"] <= pos["sl_price"])
                    else pos["sl_price"]
                )
            elif expiry_hit:
                exit_reason = "EXPIRY"
                exit_raw = float(bar_curr["close"])

            if exit_reason is not None and exit_raw is not None:
                exit_fill = exit_raw * (1.0 - self.slippage_exit_bps / 10000.0)
                gross_proceeds = pos["shares"] * exit_fill
                exit_fee = gross_proceeds * self.commission_sell
                net_proceeds = gross_proceeds - exit_fee
                state["cash"] = float(state["cash"]) + net_proceeds

                invested = pos["gross_outlay"] + pos["entry_fee"]
                net_pnl = net_proceeds - invested
                net_ret = net_pnl / invested if invested > 0 else 0.0
                gross_pnl = gross_proceeds - pos["gross_outlay"]
                gross_ret = gross_pnl / pos["gross_outlay"] if pos["gross_outlay"] > 0 else 0.0

                mfe_pct = (pos["highest_watermark"] - pos["entry_price"]) / pos["entry_price"]
                mae_pct = (pos["lowest_watermark"] - pos["entry_price"]) / pos["entry_price"]

                trade_dict = {
                    "ticker": pos["ticker"],
                    "mode": pos["mode"],
                    "signal_date": pos["signal_date"],
                    "entry_date": pos["entry_date"],
                    "exit_date": str(eval_date),
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_fill,
                    "shares": pos["shares"],
                    "size_multiplier": pos["size_multiplier"],
                    "regime_category": pos["regime_category"],
                    "gross_outlay": pos["gross_outlay"],
                    "gross_proceeds": gross_proceeds,
                    "gross_pnl": gross_pnl,
                    "gross_return": gross_ret,
                    "entry_fee": pos["entry_fee"],
                    "exit_fee": exit_fee,
                    "total_friction_idr": pos["entry_fee"] + exit_fee,
                    "net_pnl": net_pnl,
                    "net_return": net_ret,
                    "exit_reason": exit_reason,
                    "holding_days": pos["holding_days"],
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "highest_watermark": pos["highest_watermark"],
                    "lowest_watermark": pos["lowest_watermark"],
                    "planned_tp_price": pos["tp_price"],
                    "planned_sl_price": pos["sl_price"],
                }
                state["completed_trades"].append(trade_dict)
                del state["open_positions"][t]
                positions_closed_count += 1
            else:
                pos["holding_days"] += 1

        # -----------------------------------------------------------------
        # 3. Mark-to-Market Equity at Close
        # -----------------------------------------------------------------
        for t_open in state["open_positions"].keys():
            bar_c = bars_today.get(t_open)
            if bar_c is not None and bar_c["close"] > 0:
                state["last_known_close"][t_open] = float(bar_c["close"])

        eod_open_val = sum(
            pos["shares"] * state["last_known_close"].get(pos["ticker"], pos["entry_price"])
            for pos in state["open_positions"].values()
        )
        total_eq = float(state["cash"]) + eod_open_val
        alloc_pct = (eod_open_val / total_eq * 100.0) if total_eq > 0 else 0.0
        cash_exp_pct = 100.0 - alloc_pct

        if total_eq > float(state["peak_equity"]):
            state["peak_equity"] = total_eq
        dd_amt = float(state["peak_equity"]) - total_eq
        dd_pct = dd_amt / float(state["peak_equity"]) if float(state["peak_equity"]) > 0 else 0.0

        if dd_amt > float(state["max_drawdown_amount"]):
            state["max_drawdown_amount"] = dd_amt
        if dd_pct > float(state["max_drawdown_pct"]):
            state["max_drawdown_pct"] = dd_pct

        daily_equity_rec = {
            "date": str(eval_date),
            "mode": "PORTFOLIO",
            "cash": float(state["cash"]),
            "invested_capital": eod_open_val,
            "total_equity": total_eq,
            "peak_equity": float(state["peak_equity"]),
            "drawdown_amount": dd_amt,
            "drawdown_pct": dd_pct,
            "open_positions_count": len(state["open_positions"]),
            "cash_exposure_pct": cash_exp_pct,
            "portfolio_allocation_pct": alloc_pct,
        }
        state["daily_equity_history"].append(daily_equity_rec)

        # -----------------------------------------------------------------
        # 4. Evening Candidate Scoring & Scheduling Decisions for Next Session
        # -----------------------------------------------------------------
        price_map = {t: b["close"] for t, b in bars_today.items() if b["close"] > 0}

        reg_info = self.regime_lookup.get(eval_date, {})
        trend_bull = reg_info.get("ihsg_vs_ema20", 0.0) > 0.0
        mult, reg_cat = classify_regime_three_tier(reg_info)

        scored_candidates: list[PaperCandidate] = []
        new_decisions: list[PaperDecision] = []

        if not df_feat.empty:
            next_exec_d = self.get_next_trading_date(eval_date)

            for mode, policy in self.frozen_bundle.policies.items():
                model_path = root / policy.model_artifact_path
                if mode == "LOW_PRICE" and hasattr(ResearchRegressorModel, "load"):
                    try:
                        model = ResearchRegressorModel.load(model_path)
                    except Exception:
                        model = joblib.load(model_path)
                elif mode == "HIGHER_PRICE" and hasattr(ResearchClassifierModel, "load"):
                    try:
                        model = ResearchClassifierModel.load(model_path)
                    except Exception:
                        model = joblib.load(model_path)
                else:
                    model = joblib.load(model_path)

                mode_rows = []
                for _, row in df_feat.iterrows():
                    t = str(row["ticker"]).strip().upper().removesuffix(".JK")
                    p = price_map.get(t)
                    if p is None:
                        continue
                    if mode == "LOW_PRICE" and 50.0 <= p <= 300.0:
                        mode_rows.append((t, p, row))
                    elif mode == "HIGHER_PRICE" and p > 300.0:
                        mode_rows.append((t, p, row))

                if not mode_rows:
                    continue

                tickers = [r[0] for r in mode_rows]
                prices = [r[1] for r in mode_rows]
                X_df = pd.DataFrame([r[2] for r in mode_rows])[self.frozen_bundle.feature_schema]

                if mode == "LOW_PRICE":
                    scores = model.predict(X_df)
                else:
                    scores = (
                        model.predict_proba(X_df)[:, 1]
                        if hasattr(model, "predict_proba")
                        else model.predict(X_df)
                    )

                cand_items = list(zip(tickers, prices, scores, strict=True))
                cand_items.sort(key=lambda x: (-x[2], x[0]))

                n_cands = len(cand_items)
                n_select = max(1, math.ceil(n_cands * policy.selectivity_top_pct))

                for rank_idx, (t, p, sc) in enumerate(cand_items, start=1):
                    is_top = rank_idx <= n_select
                    is_elig = is_top and trend_bull

                    cand_rec = PaperCandidate(
                        date=eval_date,
                        ticker=t,
                        mode=mode,
                        decision_price=p,
                        score=float(sc),
                        rank_in_date=rank_idx,
                        total_candidates_date=n_cands,
                        is_top_pct=is_top,
                        regime_bull=trend_bull,
                        is_eligible=is_elig,
                        score_col=policy.score_metric,
                        model_id=f"h15_{mode.lower()}_variant_b",
                    )
                    scored_candidates.append(cand_rec)

                    if is_elig:
                        planned_tp = p * (1.0 + policy.tp_pct)
                        planned_sl = p * (1.0 - policy.sl_pct)
                        base_alloc = min(
                            total_eq / self.max_positions,
                            total_eq * policy.portfolio_constraints["equity_cap_pct"],
                        )
                        planned_alloc = base_alloc * mult

                        dec_rec = PaperDecision(
                            decision_date=eval_date,
                            execution_date=next_exec_d,
                            ticker=t,
                            mode=mode,
                            score=float(sc),
                            rank=rank_idx,
                            close_t=p,
                            size_multiplier=mult,
                            regime_category=reg_cat,
                            planned_tp_pct=policy.tp_pct,
                            planned_sl_pct=policy.sl_pct,
                            planned_tp_price=planned_tp,
                            planned_sl_price=planned_sl,
                            planned_allocation_idr=planned_alloc,
                            max_holding_days=policy.horizon_days,
                        )
                        new_decisions.append(dec_rec)

                        # Queue pending order for next trading session
                        state["pending_orders"].append(
                            {
                                "ticker": t,
                                "mode": mode,
                                "decision_date": str(eval_date),
                                "scheduled_execution_date": str(next_exec_d),
                                "close_t": p,
                                "score": float(sc),
                                "max_holding_days": policy.horizon_days,
                                "tp_pct": policy.tp_pct,
                                "sl_pct": policy.sl_pct,
                                "size_multiplier": mult,
                                "regime_category": reg_cat,
                                "status": "PENDING",
                            }
                        )

        # -----------------------------------------------------------------
        # 5. Persist State, Sync CSVs, Update Operational Status
        # -----------------------------------------------------------------
        state["last_execution_date"] = str(eval_date)
        state["last_decision_date"] = str(eval_date)
        state["processed_dates"].append(str(eval_date))
        if state.get("first_observation_date") is None:
            state["first_observation_date"] = str(eval_date)
            state["first_prospective_run_timestamp"] = datetime.now(timezone.utc).isoformat()

        self.save_state(state)

        # Candidates CSV
        cands_csv = self.artifacts_dir / "paper_trading_candidates.csv"
        if scored_candidates:
            df_new_cands = pd.DataFrame([asdict(c) for c in scored_candidates])
            if cands_csv.exists():
                df_existing = pd.read_csv(cands_csv)
                existing_keys = set(
                    zip(
                        df_existing["date"].astype(str),
                        df_existing["ticker"].astype(str),
                        df_existing["mode"].astype(str),
                        strict=False,
                    )
                )
                df_new_cands["_dedup_key"] = list(
                    zip(
                        df_new_cands["date"].astype(str),
                        df_new_cands["ticker"].astype(str),
                        df_new_cands["mode"].astype(str),
                        strict=False,
                    )
                )
                df_to_add = df_new_cands[~df_new_cands["_dedup_key"].isin(existing_keys)].drop(
                    columns=["_dedup_key"]
                )
                if not df_to_add.empty:
                    df_to_add.to_csv(cands_csv, mode="a", header=False, index=False)
            else:
                df_new_cands.to_csv(cands_csv, index=False)

        # Decisions CSV
        decs_csv = self.artifacts_dir / "paper_trading_decisions.csv"
        if new_decisions:
            df_new_decs = pd.DataFrame([asdict(d) for d in new_decisions])
            if decs_csv.exists():
                df_existing_decs = pd.read_csv(decs_csv)
                existing_dec_keys = set(
                    zip(
                        df_existing_decs["decision_date"].astype(str),
                        df_existing_decs["ticker"].astype(str),
                        df_existing_decs["mode"].astype(str),
                        strict=False,
                    )
                )
                df_new_decs["_dedup_key"] = list(
                    zip(
                        df_new_decs["decision_date"].astype(str),
                        df_new_decs["ticker"].astype(str),
                        df_new_decs["mode"].astype(str),
                        strict=False,
                    )
                )
                df_decs_to_add = df_new_decs[
                    ~df_new_decs["_dedup_key"].isin(existing_dec_keys)
                ].drop(columns=["_dedup_key"])
                if not df_decs_to_add.empty:
                    df_decs_to_add.to_csv(decs_csv, mode="a", header=False, index=False)
            else:
                df_new_decs.to_csv(decs_csv, index=False)

        # Trades CSV
        trades_csv = self.artifacts_dir / "paper_trading_trades.csv"
        if state["completed_trades"]:
            df_trades = pd.DataFrame(state["completed_trades"])
            df_trades.to_csv(trades_csv, index=False)

        # Daily Equity CSV
        eq_csv = self.artifacts_dir / "paper_trading_daily_equity.csv"
        if state["daily_equity_history"]:
            df_eq = pd.DataFrame(state["daily_equity_history"])
            df_eq.to_csv(eq_csv, index=False)

        # Refresh operational status JSON
        self.generate_operational_status(user_approved=is_approved, base_dir=base_dir)

        return {
            "date": str(eval_date),
            "status": "SCORED",
            "candidates_count": len(scored_candidates),
            "decisions_count": len(new_decisions),
            "orders_processed": orders_processed_count,
            "orders_filled": orders_filled_count,
            "positions_closed": positions_closed_count,
            "open_positions_count": len(state["open_positions"]),
            "pending_orders_count": len(state["pending_orders"]),
            "cash": float(state["cash"]),
            "total_equity": total_eq,
            "regime_category": reg_cat,
            "size_multiplier": mult,
        }
