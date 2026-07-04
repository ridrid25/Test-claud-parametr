"""Map raw Wildberries reportDetailByPeriod rows to the unified transactions schema.

WB's own field names for this report have shifted between API versions in
the past — if a client's numbers look off after a live pull, diff a sample
raw row against this mapping before assuming a logic bug.
"""


def _num(row: dict, *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value:
            return float(value)
    return 0.0


def normalize_wb_row(client_id: str, row: dict) -> dict:
    # .strip() guards against a stray trailing/leading space in WB's export
    # silently misclassifying a return as a sale (they'd otherwise compare
    # unequal to the exact literal "Возврат").
    doc_type = (row.get("doc_type_name") or "").strip()
    retail_amount = _num(row, "retail_amount")
    date = row.get("sale_dt") or row.get("rr_dt") or row.get("order_dt") or ""

    return {
        "client_id": client_id,
        "marketplace": "wb",
        "period_date": date[:10],
        "sku": row.get("sa_name") or str(row.get("nm_id", "")),
        "product_name": row.get("subject_name") or "",
        # int() rejects a decimal-string quantity like "2.0" outright — go
        # through float() first so one such row doesn't crash the whole batch.
        "quantity": int(float(row.get("quantity") or 0)),
        "realization": retail_amount if doc_type != "Возврат" else 0.0,
        "returns": retail_amount if doc_type == "Возврат" else 0.0,
        "commission": _num(row, "ppvz_sales_commission", "ppvz_vw"),
        "logistics": _num(row, "delivery_rub", "delivery_amount"),
        "storage": _num(row, "storage_fee"),
        "promotion": _num(row, "supplier_promo"),
        "penalty": _num(row, "penalty"),
        "other_deduction": _num(row, "deduction") + _num(row, "acquiring_fee"),
        "payout": _num(row, "ppvz_for_pay"),
        "source_report": "wb_report_detail_by_period",
        "raw_ref": str(row.get("rrd_id")),
    }


def normalize_wb_rows(client_id: str, rows: list[dict]) -> list[dict]:
    return [normalize_wb_row(client_id, row) for row in rows]
