"""Map raw Ozon /v3/finance/transaction/list operations to the unified schema.

Ozon reports individual named "services" per operation (delivery, storage,
promotion, ...) rather than fixed columns like WB does, so this classifies
each service by keywords in its name. Re-check these keyword buckets
against a live client's actual service names before trusting the output —
Ozon adds/renames service codes over time.
"""

_LOGISTICS_KEYWORDS = ("Deliv", "Trans", "Logistic", "Return")
_STORAGE_KEYWORDS = ("Storage", "Store")
_PROMOTION_KEYWORDS = ("Promo", "Advert", "Premium")


def _classify_services(services: list[dict]) -> dict:
    buckets = {"logistics": 0.0, "storage": 0.0, "promotion": 0.0, "other_deduction": 0.0}
    for service in services or []:
        name = service.get("name", "")
        price = abs(float(service.get("price") or 0))
        if any(kw in name for kw in _LOGISTICS_KEYWORDS):
            buckets["logistics"] += price
        elif any(kw in name for kw in _STORAGE_KEYWORDS):
            buckets["storage"] += price
        elif any(kw in name for kw in _PROMOTION_KEYWORDS):
            buckets["promotion"] += price
        else:
            buckets["other_deduction"] += price
    return buckets


def normalize_ozon_row(client_id: str, operation: dict) -> dict:
    items = operation.get("items") or [{}]
    first_item = items[0]
    op_type = operation.get("type", "")
    accruals_for_sale = float(operation.get("accruals_for_sale") or 0)
    service_buckets = _classify_services(operation.get("services"))
    is_penalty = op_type == "penalty" or "penalty" in operation.get("operation_type", "").lower()

    return {
        "client_id": client_id,
        "marketplace": "ozon",
        "period_date": (operation.get("operation_date") or "")[:10],
        "sku": str(first_item.get("sku", "")),
        "product_name": first_item.get("name") or "",
        "quantity": 1,
        "realization": accruals_for_sale if op_type == "orders" else 0.0,
        "returns": abs(accruals_for_sale) if op_type == "returns" else 0.0,
        "commission": abs(float(operation.get("sale_commission") or 0)),
        "logistics": service_buckets["logistics"],
        "storage": service_buckets["storage"],
        "promotion": service_buckets["promotion"],
        "penalty": abs(float(operation.get("amount") or 0)) if is_penalty else 0.0,
        "other_deduction": service_buckets["other_deduction"],
        "payout": float(operation.get("amount") or 0),
        "source_report": "ozon_finance_transaction_list",
        "raw_ref": str(operation.get("operation_id")),
    }


def normalize_ozon_rows(client_id: str, operations: list[dict]) -> list[dict]:
    return [normalize_ozon_row(client_id, operation) for operation in operations]
