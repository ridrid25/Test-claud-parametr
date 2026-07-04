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


def test_multi_item_operation_keeps_every_sku():
    """Ozon only reports operation-level totals, not a per-item split — a
    2-item shipment must not silently drop the second SKU's share."""
    multi_item_op = {
        "operation_id": 900004,
        "operation_type": "OperationAgentDeliveredToCustomer",
        "operation_date": "2023-10-20T00:00:00Z",
        "type": "orders",
        "items": [
            {"sku": 111, "name": "Товар А"},
            {"sku": 222, "name": "Товар Б"},
        ],
        "accruals_for_sale": 10000,
        "sale_commission": 1000,
        "services": [{"name": "MarketplaceServiceItemDeliveryToCustomer", "price": -400}],
        "amount": 8600,
    }
    rows = normalize_ozon_rows("acme", [multi_item_op])
    assert len(rows) == 2
    assert {r["sku"] for r in rows} == {"111", "222"}
    assert {r["raw_ref"] for r in rows} == {"900004:0", "900004:1"}
    # Totals split evenly across items rather than one item getting everything.
    assert sum(r["realization"] for r in rows) == 10000
    assert sum(r["commission"] for r in rows) == 1000
    assert sum(r["logistics"] for r in rows) == 400
    assert sum(r["payout"] for r in rows) == 8600
    for row in rows:
        assert row["realization"] == 5000
        assert row["payout"] == 4300


def test_single_item_operation_keeps_plain_raw_ref():
    """Existing single-item rows must keep their un-suffixed raw_ref so a
    re-sync of already-stored data doesn't create duplicate rows."""
    row = normalize_ozon_rows("acme", [FIXTURE[0]])[0]
    assert row["raw_ref"] == "900001"
