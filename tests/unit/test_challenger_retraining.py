from datetime import date
from pathlib import Path

import numpy as np

from python.experiments.ablation import ALL_FEATURE_COLUMNS, FEATURE_FAMILIES
from python.experiments.challenger_retraining import (
    ChallengerRetrainingRunner,
    compute_file_sha256,
)
from python.models.registry import ModelRegistry


def test_challenger_model_specs():
    """Verify that candidate models adhere to predeclared feature and family specifications."""
    runner = ChallengerRetrainingRunner()

    # LOW_PRICE specs
    low_specs = runner.get_candidate_specs("LOW_PRICE")
    spec_map_low = {s.model_id: s for s in low_specs}

    assert "lgb_full" in spec_map_low
    assert len(spec_map_low["lgb_full"].features) == 30
    assert spec_map_low["lgb_full"].feature_group_excluded is None

    assert "lgb_minus_trend" in spec_map_low
    assert spec_map_low["lgb_minus_trend"].feature_group_excluded == "trend"
    expected_low_feats = [f for f in ALL_FEATURE_COLUMNS if f not in FEATURE_FAMILIES["trend"]]
    assert spec_map_low["lgb_minus_trend"].features == expected_low_feats
    assert len(spec_map_low["lgb_minus_trend"].features) == 23

    assert "logistic_baseline" in spec_map_low
    assert len(spec_map_low["logistic_baseline"].features) == 30

    assert "prevalence_baseline" in spec_map_low
    assert len(spec_map_low["prevalence_baseline"].features) == 0

    assert "production_champion" in spec_map_low
    assert len(spec_map_low["production_champion"].features) == 30

    # HIGHER_PRICE specs
    high_specs = runner.get_candidate_specs("HIGHER_PRICE")
    spec_map_high = {s.model_id: s for s in high_specs}

    assert "lgb_minus_market_regime" in spec_map_high
    assert spec_map_high["lgb_minus_market_regime"].feature_group_excluded == "market_regime"
    expected_high_feats = [
        f for f in ALL_FEATURE_COLUMNS if f not in FEATURE_FAMILIES["market_regime"]
    ]
    assert spec_map_high["lgb_minus_market_regime"].features == expected_high_feats
    assert len(spec_map_high["lgb_minus_market_regime"].features) == 24


def test_matured_data_cutoff_enforcement():
    """Verify that decisions are strictly truncated at the fully observable cutoff date."""
    runner = ChallengerRetrainingRunner(cutoff_date="2026-09-25")
    df_low, _ = runner.load_matured_data("LOW_PRICE")
    df_high, _ = runner.load_matured_data("HIGHER_PRICE")

    assert not df_low.empty
    assert df_low["date"].max() <= date(2026, 9, 25)

    assert not df_high.empty
    assert df_high["date"].max() <= date(2026, 9, 25)

    # Check that vb_status_15 has zero incomplete decisions on or before cutoff for LOW_PRICE
    assert len(df_low[df_low["vb_status_15"] == "INCOMPLETE"]) == 0

    # In HIGHER_PRICE, 2 decisions (MPMX on 2026-09-24 and 2026-09-25) lack 15 forward bars
    # due to missing bars. Verify that valid training mask strictly filters them out.
    mask_valid_high = (df_high["vb_status_15"] == "VALID") & (
        df_high["date"] <= date(2026, 9, 25)
    )
    df_valid_high = df_high[mask_valid_high]
    assert len(df_valid_high[df_valid_high["vb_status_15"] == "INCOMPLETE"]) == 0
    assert len(df_valid_high) == 131110


def test_inspect_dataset_splits():
    """Verify inspect_database_splits returns accurate contract and row metrics."""
    from scripts.inspect_dataset_splits import inspect_database_splits

    runner = ChallengerRetrainingRunner()
    stats = inspect_database_splits(db_path=runner.db_path, cutoff_date="2026-09-25")
    assert stats["max_bar_date"] == "2026-10-16"
    assert stats["cutoff_date"] == "2026-09-25"
    assert stats["champ_low"] == 31794
    assert stats["champ_high"] == 94821
    assert stats["champ_below50"] == 1452
    assert stats["chall_low_valid"] == 41848
    assert stats["chall_high_valid"] == 131110
    assert stats["tot_chall_valid"] == 172958
    assert stats["inc_tot"] == 46343



def test_walk_forward_fold_purge_window():
    """Verify that walk-forward splits enforce strict 15-day purge window."""
    runner = ChallengerRetrainingRunner(n_splits=3, purge_days=15, cutoff_date="2026-09-25")
    df_low, _ = runner.load_matured_data("LOW_PRICE")
    dates = df_low["date"].to_numpy()

    from python.models.validation import WalkForwardSplitter

    splitter = WalkForwardSplitter(n_splits=3, purge_days=15, expanding=True)
    for tr_idx, te_idx in splitter.split(dates):
        tr_max = dates[tr_idx].max()
        te_min = dates[te_idx].min()
        # Find number of trading dates strictly between tr_max and te_min
        unique_dates = np.sort(np.unique(dates))
        purge_gap = np.sum((unique_dates > tr_max) & (unique_dates < te_min))
        assert purge_gap >= 15


def test_compute_file_sha256(tmp_path: Path):
    """Verify SHA-256 calculation on known content."""
    f = tmp_path / "test.bin"
    f.write_bytes(b"HELLO_WORLD_CHALLENGER")
    # echo -n "HELLO_WORLD_CHALLENGER" | sha256sum
    # 732fe46d84f88e8f85f54316d8924b4ce88ec299e52516a7590554efc1743bb1
    digest = compute_file_sha256(f)
    import hashlib

    assert digest == hashlib.sha256(b"HELLO_WORLD_CHALLENGER").hexdigest()


def test_champion_immutability():
    """Verify that production champions in registry are untouched and preserved."""
    reg = ModelRegistry()
    champ_low = reg.get_champion(mode="LOW_PRICE")
    champ_high = reg.get_champion(mode="HIGHER_PRICE")

    assert champ_low is not None
    assert champ_low[1].model_version == "lightgbm_classification_20261014_093522"
    assert champ_low[1].status == "champion"

    assert champ_high is not None
    assert champ_high[1].model_version == "lightgbm_classification_20261014_093607"
    assert champ_high[1].status == "champion"
