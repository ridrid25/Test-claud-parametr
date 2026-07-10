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
        # WB's "subject" is the предмет (category-like); brand_name may be absent
        # in older report versions, hence the tolerant .get with a blank default.
        "category": row.get("subject_name") or "",
        "brand": row.get("brand_name") or row.get("brand") or "",
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


# --- New Finance API schema (from 2026-07-15) -------------------------------
#
# POST https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed
# returns camelCase rows (SalesReportsDetailedRes). Field mapping vs the old
# Statistics schema (see normalize_wb_row): sa_name→vendorCode,
# subject_name→subjectName, ppvz_for_pay→forPay, delivery_rub→deliveryService,
# storage_fee→paidStorage, ppvz_sales_commission→ppvzSalesCommission,
# acquiring_fee→acquiringFee, deduction→deduction, penalty→penalty,
# rrd_id→rrdId, and amounts arrive as strings.
#
# Note: the old `supplier_promo` (продвижение в рублях) has no direct rubles
# equivalent in this report — the Finance schema only exposes promo as
# percentages (sellerPromo). Promotion is therefore left at 0 here; ДРР should
# come from the ads API or the CSV import, not this report.


def _fnum(row: dict, *keys: str) -> float:
    """Finance amounts come as strings ("183.79"); tolerate that and blanks."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def normalize_wb_finance_row(client_id: str, row: dict) -> dict:
    doc_type = (row.get("docTypeName") or "").strip()
    retail_amount = _fnum(row, "retailAmount")
    date = row.get("saleDt") or row.get("rrDate") or row.get("orderDt") or ""

    return {
        "client_id": client_id,
        "marketplace": "wb",
        "period_date": str(date)[:10],
        "sku": row.get("vendorCode") or str(row.get("nmId", "")),
        # title = "Название товара" (new field); fall back to subjectName (предмет).
        "product_name": row.get("title") or row.get("subjectName") or "",
        "category": row.get("subjectName") or "",
        "brand": row.get("brandName") or "",
        "quantity": int(float(row.get("quantity") or 0)),
        "realization": retail_amount if doc_type != "Возврат" else 0.0,
        "returns": retail_amount if doc_type == "Возврат" else 0.0,
        "commission": _fnum(row, "ppvzSalesCommission"),
        "logistics": _fnum(row, "deliveryService"),
        "storage": _fnum(row, "paidStorage"),
        "promotion": 0.0,  # not available as rubles in this report — see module note
        "penalty": _fnum(row, "penalty"),
        "other_deduction": _fnum(row, "deduction") + _fnum(row, "acquiringFee"),
        "payout": _fnum(row, "forPay"),
        "source_report": "wb_finance_sales_reports_detailed",
        "raw_ref": str(row.get("rrdId")),
    }


def normalize_wb_finance_rows(client_id: str, rows: list[dict]) -> list[dict]:
    return [normalize_wb_finance_row(client_id, row) for row in rows]
