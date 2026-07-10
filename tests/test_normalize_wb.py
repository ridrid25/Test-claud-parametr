import json
from pathlib import Path

from etl.normalize_wb import normalize_wb_finance_rows, normalize_wb_rows

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


def test_commission_falls_back_to_ppvz_vw_when_primary_field_absent():
    """None of the fixtures exercise the fallback key in _num(row,
    "ppvz_sales_commission", "ppvz_vw") — every sample row happens to have
    the primary key. WB has renamed report fields before (see the README's
    2026-07-15 migration note), so this fallback needs its own coverage."""
    row = {**FIXTURE[0]}
    del row["ppvz_sales_commission"]
    row["ppvz_vw"] = 555
    normalized = normalize_wb_rows("acme", [row])[0]
    assert normalized["commission"] == 555


def test_logistics_falls_back_to_delivery_amount_when_primary_field_absent():
    row = {**FIXTURE[0]}
    del row["delivery_rub"]
    row["delivery_amount"] = 222
    normalized = normalize_wb_rows("acme", [row])[0]
    assert normalized["logistics"] == 222


# --- New Finance API schema (camelCase, from 2026-07-15) --------------------

def _finance_sale_row(**overrides):
    """A representative row from POST /api/finance/v1/sales-reports/detailed
    (SalesReportsDetailedRes): camelCase keys, string amounts."""
    row = {
        "rrdId": 2001,
        "saleDt": "2026-07-16T12:00:00",
        "vendorCode": "SKU-RED-DRESS-M",
        "title": "Платье красное",
        "subjectName": "Платья",
        "brandName": "AceBrand",
        "docTypeName": "Продажа",
        "quantity": 2,
        "retailAmount": "4000.00",
        "ppvzSalesCommission": "680.50",
        "deliveryService": "150.00",
        "paidStorage": "20.00",
        "penalty": "0",
        "deduction": "10.00",
        "acquiringFee": "5.00",
        "forPay": "3110.00",
    }
    row.update(overrides)
    return row


def test_finance_sale_row_maps_fields_and_string_amounts():
    row = normalize_wb_finance_rows("acme", [_finance_sale_row()])[0]
    assert row["marketplace"] == "wb"
    assert row["sku"] == "SKU-RED-DRESS-M"
    assert row["product_name"] == "Платье красное"
    assert row["category"] == "Платья"
    assert row["brand"] == "AceBrand"
    assert row["realization"] == 4000
    assert row["returns"] == 0
    assert row["commission"] == 680.50
    assert row["logistics"] == 150
    assert row["storage"] == 20
    assert row["other_deduction"] == 15  # deduction + acquiringFee
    assert row["payout"] == 3110
    assert row["period_date"] == "2026-07-16"
    assert row["raw_ref"] == "2001"
    assert row["source_report"] == "wb_finance_sales_reports_detailed"


def test_finance_return_row_maps_to_returns():
    row = normalize_wb_finance_rows("acme", [
        _finance_sale_row(docTypeName="Возврат", retailAmount="2000.00", forPay="-2000.00"),
    ])[0]
    assert row["realization"] == 0
    assert row["returns"] == 2000
    assert row["payout"] == -2000


def test_finance_missing_fields_default_to_zero():
    row = normalize_wb_finance_rows("acme", [
        {"rrdId": 9, "saleDt": "2026-07-16", "vendorCode": "X", "docTypeName": "Продажа"},
    ])[0]
    assert row["realization"] == 0
    assert row["commission"] == 0
    assert row["payout"] == 0
    assert row["quantity"] == 0


def test_finance_sku_falls_back_to_nm_id():
    row = normalize_wb_finance_rows("acme", [
        _finance_sale_row(vendorCode="", nmId=123456),
    ])[0]
    assert row["sku"] == "123456"
