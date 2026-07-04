import json
from pathlib import Path

from etl.normalize_wb import normalize_wb_rows

FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "wb_report_sample.json").read_text())


def test_sale_row_maps_to_realization():
    rows = normalize_wb_rows("acme", [FIXTURE[0]])
    row = rows[0]
    assert row["marketplace"] == "wb"
    assert row["sku"] == "SKU-RED-DRESS-M"
    assert row["realization"] == 4000
    assert row["returns"] == 0
    assert row["commission"] == 680
    assert row["logistics"] == 150
    assert row["storage"] == 20
    assert row["payout"] == 3110
    assert row["raw_ref"] == "1001"


def test_return_row_maps_to_returns_not_realization():
    rows = normalize_wb_rows("acme", [FIXTURE[1]])
    row = rows[0]
    assert row["realization"] == 0
    assert row["returns"] == 2000
    assert row["payout"] == -2000


def test_period_date_is_truncated_to_day():
    rows = normalize_wb_rows("acme", [FIXTURE[0]])
    assert rows[0]["period_date"] == "2023-10-05"


def test_missing_fields_default_to_zero():
    sparse_row = {"rrd_id": 9999, "sale_dt": "2023-10-01", "sa_name": "X"}
    row = normalize_wb_rows("acme", [sparse_row])[0]
    assert row["realization"] == 0
    assert row["commission"] == 0
    assert row["payout"] == 0


def test_standalone_fee_row_does_not_inflate_realization():
    """A row with no sale (pure logistics/storage/penalty charge, empty
    doc_type_name, no retail_amount) must not be counted as a sale just
    because doc_type_name != 'Возврат'."""
    fee_only_row = {
        "rrd_id": 5000,
        "sale_dt": "2023-10-15",
        "sa_name": "SKU-X",
        "doc_type_name": "",
        "storage_fee": 45,
        "ppvz_for_pay": -45,
    }
    row = normalize_wb_rows("acme", [fee_only_row])[0]
    assert row["realization"] == 0
    assert row["returns"] == 0
    assert row["storage"] == 45
    assert row["payout"] == -45


def test_doc_type_with_stray_whitespace_still_classified_as_return():
    padded_return_row = dict(FIXTURE[1])
    padded_return_row["doc_type_name"] = " Возврат "
    row = normalize_wb_rows("acme", [padded_return_row])[0]
    assert row["realization"] == 0
    assert row["returns"] == 2000


def test_decimal_string_quantity_does_not_crash():
    row = {**FIXTURE[0], "quantity": "2.0"}
    normalized = normalize_wb_rows("acme", [row])[0]
    assert normalized["quantity"] == 2
