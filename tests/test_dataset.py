import pandas as pd

from backend.app.config import DATA_PATH
from ml import generate_dataset, validate_dataset


def test_csv_has_exactly_15000_data_rows():
    with open(DATA_PATH) as f:
        lines = f.read().splitlines()
    assert len(lines) - 1 == 15000  # excluding header


def test_validation_passes_on_saved_dataset():
    assert validate_dataset.validate(pd.read_csv(DATA_PATH)) == []


def test_generator_is_reproducible():
    a, b = generate_dataset.generate(), generate_dataset.generate()
    pd.testing.assert_frame_equal(a, b)
    saved = pd.read_csv(DATA_PATH)
    assert a.shape == saved.shape and (a["target_passenger_demand"].values == saved["target_passenger_demand"].values).all()


def test_validator_detects_problems():
    df = pd.read_csv(DATA_PATH)
    assert any("row count" in e for e in validate_dataset.validate(df.iloc[:-1]))
    bad = df.copy(); bad.loc[0, "target_passenger_demand"] = -5
    assert any("target_passenger_demand" in e for e in validate_dataset.validate(bad))
    dup = df.copy(); dup.iloc[5] = dup.iloc[0]
    assert any("duplicate" in e for e in validate_dataset.validate(dup))
    nan = df.copy(); nan.loc[3, "temperature"] = None
    assert any("missing values" in e for e in validate_dataset.validate(nan))
    assert any("missing columns" in e for e in validate_dataset.validate(df.drop(columns=["rainfall"])))


def test_data_is_meaningful_not_independent_noise():
    df = pd.read_csv(DATA_PATH)
    peak = df[df.event_phase.isin(["arrival", "dispersal"])].target_passenger_demand.mean()
    quiet = df[df.event_phase.isin(["pre_event", "wind_down"])].target_passenger_demand.mean()
    assert peak > 2 * quiet                       # temporal structure
    s01 = df[(df.stop_id == "S01") & (df.event_phase == "dispersal")].target_passenger_demand.mean()
    s04 = df[(df.stop_id == "S04") & (df.event_phase == "dispersal")].target_passenger_demand.mean()
    assert s01 > 3 * s04                           # venue stops spike on dispersal, hubs do not
    assert df.groupby("stop_id").average_bus_capacity.nunique().max() <= 3   # coherent fleet capacity
    assert (df.data_source == "synthetic").all()


def test_timestamps_valid_and_unique_keys():
    df = pd.read_csv(DATA_PATH)
    ts = pd.to_datetime(df.timestamp)
    assert ts.notna().all()
    assert not df.duplicated(["timestamp", "festival_id", "stop_id"]).any()
