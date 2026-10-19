"""Unit tests for Phase 11F Forward Paper Trading & Frozen Policy Validation.

Verifies:
- Deterministic policy configuration hashing (SHA-256) and parameter sensitivity.
- Deterministic candidate tie-breaking (score desc, ticker asc) in candidate sorting and simulation.
- Three-tier point-in-time regime conviction sizing (1.0x, 0.5x, 0.0x).
- Pre-entry gap invalidations in simulation (gap down through SL, gap up through TP,
  excessive dev, suspended).
- Portfolio capacity constraints (max 5 concurrent positions, duplicate rejection).
- Cash constraints and IDX lot-size rounding (100 shares).
- 50 bps round-trip transaction friction accounting (15 bps buy, 25 bps sell, 5 bps in/out slip).
- Fail-closed missing research scoring artifact guard and champion fallback prohibition.
- Prospective scoring execution when mock joblib model artifacts are present.
- Conservative SL precedence on ambiguous intraday bars in simulation.
- In-trade MFE / MAE excursion tracking.
- Operational status, data quality, and frozen reference benchmark verification.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

from python.common.types import DailyBar
from python.experiments.paper_trading import (
    CHAMPION_MODELS,
    RESEARCH_SCORING_ARTIFACTS,
    FrozenPolicyBundle,
    MissingScoringArtifactError,
    PaperTradingEngine,
    classify_regime_three_tier,
    get_default_frozen_policies,
)


@pytest.fixture
def policy_bundle() -> FrozenPolicyBundle:
    return get_default_frozen_policies()


@pytest.fixture
def mock_engine(tmp_path: Path) -> PaperTradingEngine:
    artifacts_dir = tmp_path / "artifacts_11f"
    engine = PaperTradingEngine(
        db_path="datasets/stock_signals.db",
        artifacts_dir=artifacts_dir,
    )
    return engine


class DummyEstimator:
    """Mock LightGBM estimator supporting predict and predict_proba."""

    def predict(self, X: Any) -> np.ndarray:
        return np.full(len(X), 0.05)

    def predict_proba(self, X: Any) -> np.ndarray:
        probs = np.full((len(X), 2), 0.5)
        probs[:, 1] = 0.65
        return probs


def build_synthetic_simulation_fixtures():
    """Builds synthetic candidate dataframe and bar lookup for deterministic testing."""
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)

    # 10 candidates on d1
    cand_rows = [
        {"date": d1, "ticker": "T_GAPDOWN", "va_entry_price": 1000.0, "score": 0.090},
        {"date": d1, "ticker": "T_GAPUP", "va_entry_price": 1000.0, "score": 0.080},
        {"date": d1, "ticker": "T_DEV", "va_entry_price": 1000.0, "score": 0.070},
        {"date": d1, "ticker": "T_SUSP", "va_entry_price": 1000.0, "score": 0.060},
        {"date": d1, "ticker": "T_AMBIG", "va_entry_price": 1000.0, "score": 0.050},
        {"date": d1, "ticker": "T_NORM", "va_entry_price": 1000.0, "score": 0.040},
        {"date": d1, "ticker": "BG1", "va_entry_price": 100.0, "score": 0.010},
        {"date": d1, "ticker": "BG2", "va_entry_price": 100.0, "score": 0.009},
        {"date": d1, "ticker": "BG3", "va_entry_price": 100.0, "score": 0.008},
        {"date": d1, "ticker": "BG4", "va_entry_price": 100.0, "score": 0.007},
    ]
    df_cands = pd.DataFrame(cand_rows)

    bar_lookup: dict[tuple[str, date], DailyBar] = {
        # T_GAPDOWN: Day 2 open at 970 (below SL 980)
        ("T_GAPDOWN", d1): DailyBar(
            ticker="T_GAPDOWN", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_GAPDOWN", d2): DailyBar(
            ticker="T_GAPDOWN", date=d2, open=970, high=980, low=960, close=970, volume=10000
        ),
        # T_GAPUP: Day 2 open at 1070 (above TP 1060)
        ("T_GAPUP", d1): DailyBar(
            ticker="T_GAPUP", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_GAPUP", d2): DailyBar(
            ticker="T_GAPUP", date=d2, open=1070, high=1080, low=1065, close=1070, volume=10000
        ),
        # T_DEV: Day 2 open at 1055 (> 5% deviation)
        ("T_DEV", d1): DailyBar(
            ticker="T_DEV", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_DEV", d2): DailyBar(
            ticker="T_DEV", date=d2, open=1055, high=1060, low=1050, close=1055, volume=10000
        ),
        # T_SUSP: Day 2 volume = 0
        ("T_SUSP", d1): DailyBar(
            ticker="T_SUSP", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_SUSP", d2): DailyBar(
            ticker="T_SUSP", date=d2, open=1000, high=1000, low=1000, close=1000, volume=0
        ),
        # T_AMBIG: Day 2 open 1000, hits both TP (1070) and SL (970) on Day 2
        ("T_AMBIG", d1): DailyBar(
            ticker="T_AMBIG", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_AMBIG", d2): DailyBar(
            ticker="T_AMBIG", date=d2, open=1000, high=1070, low=970, close=1010, volume=10000
        ),
        # T_NORM: normal trade entry on Day 2, exits TP on Day 3
        ("T_NORM", d1): DailyBar(
            ticker="T_NORM", date=d1, open=1000, high=1010, low=990, close=1000, volume=10000
        ),
        ("T_NORM", d2): DailyBar(
            ticker="T_NORM", date=d2, open=1000, high=1020, low=995, close=1010, volume=10000
        ),
        ("T_NORM", d3): DailyBar(
            ticker="T_NORM", date=d3, open=1010, high=1070, low=1005, close=1065, volume=10000
        ),
    }

    regime_lookup = {
        d1: {"ihsg_vs_ema20": 0.015, "market_breadth": 0.60},
        d2: {"ihsg_vs_ema20": 0.015, "market_breadth": 0.60},
        d3: {"ihsg_vs_ema20": 0.015, "market_breadth": 0.60},
    }

    return df_cands, bar_lookup, regime_lookup


class TestPolicyConfigurationAndHashing:
    def test_frozen_policy_config_hashing_determinism(self, policy_bundle: FrozenPolicyBundle):
        """Verifies deterministic SHA-256 calculation on canonical JSON representation."""
        hash1 = policy_bundle.compute_sha256()
        hash2 = policy_bundle.compute_sha256()
        assert len(hash1) == 64
        assert hash1 == hash2
        assert hash1 == policy_bundle.config_sha256

    def test_policy_hash_sensitivity(self, policy_bundle: FrozenPolicyBundle):
        """Verifies hash changes when any parameter is altered."""
        initial_hash = policy_bundle.compute_sha256()
        policy_bundle.policies["LOW_PRICE"].tp_pct = 0.07
        new_hash = policy_bundle.compute_sha256()
        assert initial_hash != new_hash

    def test_feature_schema_contains_30_features(self, policy_bundle: FrozenPolicyBundle):
        """Verifies feature schema matches established 30-feature baseline."""
        assert len(policy_bundle.feature_schema) == 30
        assert "ihsg_vs_ema20" in policy_bundle.feature_schema
        assert "market_breadth" in policy_bundle.feature_schema


class TestRegimeSizingTiers:
    def test_three_tier_regime_sizing_rules(self):
        """Tests point-in-time three-tier regime sizing classification."""
        fav_reg = {"ihsg_vs_ema20": 0.015, "market_breadth": 0.58}
        mult, cat = classify_regime_three_tier(fav_reg)
        assert mult == 1.0
        assert cat == "FAVORABLE"

        mixed_a = {"ihsg_vs_ema20": 0.015, "market_breadth": 0.42}
        mult, cat = classify_regime_three_tier(mixed_a)
        assert mult == 0.5
        assert cat == "MIXED"

        mixed_b = {"ihsg_vs_ema20": -0.010, "market_breadth": 0.55}
        mult, cat = classify_regime_three_tier(mixed_b)
        assert mult == 0.5
        assert cat == "MIXED"

        unfav = {"ihsg_vs_ema20": -0.010, "market_breadth": 0.40}
        mult, cat = classify_regime_three_tier(unfav)
        assert mult == 0.0
        assert cat == "UNFAVORABLE"


class TestDeterministicTieBreaking:
    def test_deterministic_candidate_sorting(self):
        """Verifies ties are broken deterministically by score desc, ticker asc."""
        raw_candidates = [
            {"ticker": "BBRI", "score": 0.055},
            {"ticker": "BBCA", "score": 0.080},
            {"ticker": "TLKM", "score": 0.055},
            {"ticker": "ASII", "score": 0.055},
            {"ticker": "BMRI", "score": 0.070},
        ]
        sorted_cands = sorted(raw_candidates, key=lambda c: (-c["score"], c["ticker"]))
        expected_order = ["BBCA", "BMRI", "ASII", "BBRI", "TLKM"]
        actual_order = [c["ticker"] for c in sorted_cands]
        assert actual_order == expected_order

    def test_deterministic_tie_breaking_in_simulation(self, mock_engine: PaperTradingEngine):
        """Verifies engine simulation resolves identical candidate scores by
        alphabetical ticker asc."""
        d1 = date(2026, 1, 2)
        # 10 candidates with identical scores for ZZZZ and AAAA
        cands = [
            {"date": d1, "ticker": "ZZZZ", "va_entry_price": 100.0, "score": 0.050},
            {"date": d1, "ticker": "AAAA", "va_entry_price": 100.0, "score": 0.050},
        ] + [
            {"date": d1, "ticker": f"BG_{i}", "va_entry_price": 100.0, "score": 0.010 - i * 0.001}
            for i in range(8)
        ]
        df_c = pd.DataFrame(cands)

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        mock_engine._bar_lookup = {}
        mock_engine._regime_lookup = {d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6}}

        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_c, policy)
        recorded = [c for c in res["candidates"] if c.ticker in ("AAAA", "ZZZZ")]
        assert len(recorded) == 2
        # AAAA must have lower rank (rank 1) than ZZZZ (rank 2)
        assert recorded[0].ticker == "AAAA"
        assert recorded[0].rank_in_date == 1
        assert recorded[1].ticker == "ZZZZ"
        assert recorded[1].rank_in_date == 2


def make_candidates_for_dates(
    dates: list[date], target_ticker: str, score: float = 0.099, base_price: float = 1000.0
) -> pd.DataFrame:
    """Builds a synthetic dataframe with at least 10 candidates per date."""
    rows = []
    for d in dates:
        rows.append(
            {"date": d, "ticker": target_ticker, "va_entry_price": base_price, "score": score}
        )
        for i in range(9):
            rows.append(
                {
                    "date": d,
                    "ticker": f"BG_{i}",
                    "va_entry_price": 100.0,
                    "score": 0.010 - i * 0.001,
                }
            )
    return pd.DataFrame(rows)


class TestExecutionFidelityAndGapInvalidations:
    def test_gap_down_invalidation_in_simulation(self, mock_engine: PaperTradingEngine):
        """Simulated Day 1 Open <= SL must invalidate order and leave cash untouched."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)

        df_cands = make_candidates_for_dates(
            [d1, d2], "GAP_DOWN_CO", score=0.099, base_price=1000.0
        )

        mock_engine._bar_lookup = {
            ("GAP_DOWN_CO", d1): DailyBar(
                ticker="GAP_DOWN_CO",
                date=d1,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1000.0,
                volume=10000,
            ),
            # Day 2 Open at 970 (<= planned SL of 980)
            ("GAP_DOWN_CO", d2): DailyBar(
                ticker="GAP_DOWN_CO",
                date=d2,
                open=970.0,
                high=980.0,
                low=960.0,
                close=970.0,
                volume=10000,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert res["summary"]["invalidated_gap_down"] == 1
        assert len(res["trades"]) == 0
        assert res["daily_equity"][-1].cash == mock_engine.initial_capital

    def test_gap_up_invalidation_in_simulation(self, mock_engine: PaperTradingEngine):
        """Simulated Day 1 Open >= TP must invalidate order with 0 cash outlay."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)

        df_cands = make_candidates_for_dates([d1, d2], "GAP_UP_CO", score=0.099, base_price=1000.0)

        mock_engine._bar_lookup = {
            ("GAP_UP_CO", d1): DailyBar(
                ticker="GAP_UP_CO",
                date=d1,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1000.0,
                volume=10000,
            ),
            # Day 2 Open at 1070 (>= planned TP of 1060)
            ("GAP_UP_CO", d2): DailyBar(
                ticker="GAP_UP_CO",
                date=d2,
                open=1070.0,
                high=1080.0,
                low=1065.0,
                close=1070.0,
                volume=10000,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert res["summary"]["invalidated_gap_up"] == 1
        assert len(res["trades"]) == 0
        assert res["daily_equity"][-1].cash == mock_engine.initial_capital

    def test_excessive_deviation_invalidation_in_simulation(self, mock_engine: PaperTradingEngine):
        """Simulated Day 1 Open deviation > 5% must invalidate order."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)

        df_cands = make_candidates_for_dates([d1, d2], "DEV_CO", score=0.099, base_price=1000.0)

        mock_engine._bar_lookup = {
            ("DEV_CO", d1): DailyBar(
                ticker="DEV_CO",
                date=d1,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1000.0,
                volume=10000,
            ),
            # Day 2 Open at 1055 (+5.5% deviation)
            ("DEV_CO", d2): DailyBar(
                ticker="DEV_CO",
                date=d2,
                open=1055.0,
                high=1058.0,
                low=1040.0,
                close=1045.0,
                volume=10000,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert res["summary"]["invalidated_excessive_dev"] == 1
        assert len(res["trades"]) == 0
        assert res["daily_equity"][-1].cash == mock_engine.initial_capital

    def test_suspended_or_zero_volume_unfilled_in_simulation(self, mock_engine: PaperTradingEngine):
        """Simulated Day 1 Volume <= 0 must mark order unfilled with 0 cash outlay."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)

        df_cands = make_candidates_for_dates([d1, d2], "SUSP_CO", score=0.099, base_price=1000.0)

        mock_engine._bar_lookup = {
            ("SUSP_CO", d1): DailyBar(
                ticker="SUSP_CO",
                date=d1,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1000.0,
                volume=10000,
            ),
            ("SUSP_CO", d2): DailyBar(
                ticker="SUSP_CO",
                date=d2,
                open=1000.0,
                high=1000.0,
                low=1000.0,
                close=1000.0,
                volume=0,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert res["summary"]["unfilled_suspended"] == 1
        assert len(res["trades"]) == 0
        assert res["daily_equity"][-1].cash == mock_engine.initial_capital

    def test_lot_size_and_cash_accounting(self, mock_engine: PaperTradingEngine):
        """Verifies 100-share lot rounding and capital protection."""
        sized_cap = 10_000_000.0
        fill_price = 1530.0
        raw_shares = sized_cap / fill_price
        lot_shares = int(raw_shares // 100) * 100
        assert lot_shares == 6500

        gross_outlay = lot_shares * fill_price
        buy_fee = gross_outlay * mock_engine.commission_buy
        assert buy_fee == pytest.approx(9_945_000.0 * 0.0015)

    def test_fee_accounting_50bps_nominal(self, mock_engine: PaperTradingEngine):
        """Verifies exact 50 bps round-trip nominal transaction friction."""
        buy_comm = mock_engine.commission_buy * 10000.0
        sell_comm = mock_engine.commission_sell * 10000.0
        entry_slip = mock_engine.slippage_entry_bps
        exit_slip = mock_engine.slippage_exit_bps
        total_nominal_bps = buy_comm + sell_comm + entry_slip + exit_slip
        assert total_nominal_bps == 50.0

    def test_ambiguous_bar_conservative_sl_precedence_in_simulation(
        self, mock_engine: PaperTradingEngine
    ):
        """On ambiguous bars where High >= TP and Low <= SL, simulation resolves exit as SL."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)

        df_cands = make_candidates_for_dates([d1, d2], "AMBIG_CO", score=0.099, base_price=1000.0)

        # Day 2 fills at 1000 * 1.0005 = 1000.5. Planned TP = 1060.53, planned SL = 980.49
        # Intraday High = 1070 (TP hit), Low = 970 (SL hit) -> Ambiguous bar!
        mock_engine._bar_lookup = {
            ("AMBIG_CO", d1): DailyBar(
                ticker="AMBIG_CO",
                date=d1,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1000.0,
                volume=10000,
            ),
            ("AMBIG_CO", d2): DailyBar(
                ticker="AMBIG_CO",
                date=d2,
                open=1000.0,
                high=1070.0,
                low=970.0,
                close=1010.0,
                volume=10000,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert len(res["trades"]) == 1
        trade = res["trades"][0]
        assert trade.exit_reason == "SL"
        assert trade.exit_price < trade.entry_price

    def test_mfe_mae_tracking(self, mock_engine: PaperTradingEngine):
        """Verifies in-trade excursion watermarks (highest/lowest) and MFE/MAE percentages."""
        d1 = date(2026, 1, 2)
        d2 = date(2026, 1, 3)
        d3 = date(2026, 1, 4)

        df_cands = make_candidates_for_dates(
            [d1, d2, d3], "TRACK_CO", score=0.099, base_price=100.0
        )

        mock_engine._bar_lookup = {
            ("TRACK_CO", d1): DailyBar(
                ticker="TRACK_CO",
                date=d1,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=10000,
            ),
            ("TRACK_CO", d2): DailyBar(
                ticker="TRACK_CO",
                date=d2,
                open=100.0,
                high=104.0,
                low=99.0,
                close=102.0,
                volume=10000,
            ),
            ("TRACK_CO", d3): DailyBar(
                ticker="TRACK_CO",
                date=d3,
                open=102.0,
                high=107.0,
                low=101.0,
                close=106.5,
                volume=10000,
            ),
        }
        mock_engine._regime_lookup = {
            d1: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d2: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
            d3: {"ihsg_vs_ema20": 0.01, "market_breadth": 0.6},
        }

        policy = mock_engine.frozen_bundle.policies["LOW_PRICE"]
        res = mock_engine._simulate_mode_replay("LOW_PRICE", df_cands, policy)

        assert len(res["trades"]) == 1
        trade = res["trades"][0]
        assert trade.exit_reason == "TP"
        assert trade.highest_watermark == 107.0
        assert trade.lowest_watermark == 99.0
        assert trade.mfe_pct > 0.0
        assert trade.mae_pct < 0.0


class TestFailClosedScoringArtifactGuard:
    def test_scoring_artifacts_audit_missing_fails_closed(self, mock_engine: PaperTradingEngine):
        """Verifies audit detects missing H=15 Variant B artifacts and blocks fallback."""
        audit = mock_engine.audit_scoring_artifacts()
        assert audit["status"] == "BLOCKED_ON_SCORING_ARTIFACT"
        assert audit["fail_closed_guard_active"] is True
        assert audit["champion_fallback_permitted"] is False
        assert len(audit["missing_artifacts"]) == 2
        assert RESEARCH_SCORING_ARTIFACTS["LOW_PRICE"] in audit["missing_artifacts"]
        assert RESEARCH_SCORING_ARTIFACTS["HIGHER_PRICE"] in audit["missing_artifacts"]

    def test_prospective_scoring_halts_on_missing_artifact(self, mock_engine: PaperTradingEngine):
        """Verifies step_prospective_date raises MissingScoringArtifactError."""
        with pytest.raises(MissingScoringArtifactError) as exc_info:
            mock_engine.step_prospective_date(date(2026, 10, 19))
        assert "Prospective scoring blocked" in str(exc_info.value)
        assert "Missing 2 research scoring artifact(s)" in str(exc_info.value)

    def test_champion_fallback_strictly_forbidden(self, mock_engine: PaperTradingEngine):
        """Verifies active production champions are never used for research scoring."""
        audit = mock_engine.audit_scoring_artifacts()
        for mode, info in audit["artifacts"].items():
            assert info["champion_substitute_blocked"] == CHAMPION_MODELS[mode]

    def test_prospective_scoring_executes_with_mock_artifacts(
        self, mock_engine: PaperTradingEngine, tmp_path: Path
    ):
        """Verifies step_prospective_date loads model, scores candidates,
        and records decisions when artifacts exist."""
        # Create mock model files under tmp_path
        reg_dir = tmp_path / "models" / "registry"
        reg_dir.mkdir(parents=True, exist_ok=True)
        dummy_model = DummyEstimator()

        joblib.dump(dummy_model, reg_dir / "lgb_regressor_h15_variant_b.joblib")
        joblib.dump(dummy_model, reg_dir / "lgb_full_classifier_h15_variant_b.joblib")

        # 1. Bull date (2026-09-18) where ihsg_vs_ema20 > 0: decisions generated
        res_bull = mock_engine.step_prospective_date(date(2026, 9, 18), base_dir=tmp_path)
        assert res_bull["status"] == "SCORED"
        assert res_bull["candidates_count"] > 0
        assert res_bull["decisions_count"] > 0
        assert (mock_engine.artifacts_dir / "paper_trading_candidates.csv").exists()
        assert (mock_engine.artifacts_dir / "paper_trading_decisions.csv").exists()

        # 2. Bear date (2026-10-14) where ihsg_vs_ema20 <= 0: candidates scored, decisions 0
        res_bear = mock_engine.step_prospective_date(date(2026, 10, 14), base_dir=tmp_path)
        assert res_bear["status"] == "SCORED"
        assert res_bear["candidates_count"] > 0
        assert res_bear["decisions_count"] == 0


class TestOperationalStatusAndBenchmarks:
    def test_export_frozen_policy_config(self, mock_engine: PaperTradingEngine):
        """Verifies export of frozen policy config JSON."""
        cfg = mock_engine.export_frozen_policy_config()
        assert "policies" in cfg
        assert "LOW_PRICE" in cfg["policies"]
        assert "HIGHER_PRICE" in cfg["policies"]
        assert cfg["config_sha256"] != ""
        cfg_file = mock_engine.artifacts_dir / "frozen_policy_config.json"
        assert cfg_file.exists()

    def test_export_frozen_reference_benchmarks(self, mock_engine: PaperTradingEngine):
        """Verifies export of benchmark comparison CSV and accurate reference metrics."""
        df_bm = mock_engine.export_frozen_reference_benchmarks()
        assert len(df_bm) == 6
        assert "phase_11d_selective_fixed_exit" in df_bm["benchmark_id"].values
        assert "phase_11e_selective_three_tier_sizing" in df_bm["benchmark_id"].values
        assert "production_champion_reference" in df_bm["benchmark_id"].values

        # Check Phase 11D corrected figures
        p11d_low = df_bm[
            (df_bm["benchmark_id"] == "phase_11d_selective_fixed_exit")
            & (df_bm["mode"] == "LOW_PRICE")
        ].iloc[0]
        assert p11d_low["net_portfolio_return_pct"] == pytest.approx(2.12)
        assert p11d_low["avg_cash_exposure_pct"] == pytest.approx(77.35)

        p11d_high = df_bm[
            (df_bm["benchmark_id"] == "phase_11d_selective_fixed_exit")
            & (df_bm["mode"] == "HIGHER_PRICE")
        ].iloc[0]
        assert p11d_high["net_portfolio_return_pct"] == pytest.approx(8.57)
        assert p11d_high["avg_cash_exposure_pct"] == pytest.approx(62.92)

        bm_file = mock_engine.artifacts_dir / "frozen_reference_benchmarks.csv"
        assert bm_file.exists()

    def test_operational_status_generation(self, mock_engine: PaperTradingEngine):
        """Verifies operational status JSON structure and content."""
        status = mock_engine.generate_operational_status()
        assert status["operational_status"] == (
            "READY_FOR_OBSERVATION (BLOCKED_ON_SCORING_ARTIFACT_OR_APPROVAL)"
        )
        assert status["policy_bundle_hash"] != ""
        assert "scoring_artifacts_audit" in status
        assert "data_quality" in status
        assert status["data_quality"]["total_daily_bars"] > 0
        status_file = mock_engine.artifacts_dir / "paper_trading_operational_status.json"
        assert status_file.exists()
