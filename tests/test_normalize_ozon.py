import json
from pathlib import Path

from etl.normalize_ozon import normalize_ozon_rows

FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "ozon_transactions_sample.json").read_text())


def test_order_row_maps_to_realization_and_services():
    row = normalize_ozon_rows("acme", [FIXTURE[0]])[0]
    assert row["marketplace"] == "ozon"
    assert row["sku"] == "12345"
    assert row["realization"] == 6000
    assert row["returns"] == 0
    assert row["commission"] == 900
    assert row["logistics"] == 250
    assert row["storage"] == 30
    assert row["payout"] == 4820
    assert row["raw_ref"] == "900001"


def test_return_row_maps_to_returns():
    row = normalize_ozon_rows("acme", [FIXTURE[1]])[0]
    assert row["realization"] == 0
    assert row["returns"] == 3000
    assert row["logistics"] == 120
    assert row["payout"] == -3120


def test_promotion_service_maps_to_promotion_bucket():
    row = normalize_ozon_rows("acme", [FIXTURE[2]])[0]
    assert row["promotion"] == 200
    assert row["realization"] == 0
    assert row["returns"] == 0
