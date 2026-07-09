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


def normalize_ozon_operation(client_id: str, operation: dict) -> list[dict]:
    """One Ozon operation can list several items (a combined shipment), but
    Ozon only reports totals (accruals, commission, services, amount) for
    the operation as a whole — there's no per-item split in this API. Emit
    one row per item with the totals divided evenly, rather than crediting
    everything to items[0] and silently dropping the rest of the shipment.
    """
    items = operation.get("items") or [{}]
    item_count = len(items)
    op_type = operation.get("type", "")
    accruals_for_sale = float(operation.get("accruals_for_sale") or 0)
    service_buckets = _classify_services(operation.get("services"))
    is_penalty = op_type == "penalty" or "penalty" in operation.get("operation_type", "").lower()
    amount = float(operation.get("amount") or 0)
    # Unverified assumption: commission is always treated as a positive
    # expense, including on returns. If Ozon reports a negative
    # sale_commission on a return (i.e. a commission refund), forcing it
    # positive here would double-count it as an expense instead of netting
    # it out. None of the sample data includes a return with a non-zero
    # commission, so this hasn't been checked against a real example —
    # revisit if a client's Ozon returns show an unexplained expense bump.
    commission = abs(float(operation.get("sale_commission") or 0))
    operation_id = operation.get("operation_id")
    period_date = (operation.get("operation_date") or "")[:10]

    rows = []
    for index, item in enumerate(items):
        # raw_ref must stay unique per row for storage's upsert key — suffix
        # with the item index only when there's more than one, so the common
        # single-item case keeps the plain operation_id used by existing data.
        raw_ref = str(operation_id) if item_count == 1 else f"{operation_id}:{index}"
        rows.append({
            "client_id": client_id,
            "marketplace": "ozon",
            "period_date": period_date,
            "sku": str(item.get("sku", "")),
            "product_name": item.get("name") or "",
            # The finance transaction API carries no category/brand per item —
            # keep the keys present (blank) so the unified upsert stays uniform.
            "category": "",
            "brand": "",
            "quantity": 1,
            "realization": (accruals_for_sale / item_count) if op_type == "orders" else 0.0,
            "returns": (abs(accruals_for_sale) / item_count) if op_type == "returns" else 0.0,
            "commission": commission / item_count,
            "logistics": service_buckets["logistics"] / item_count,
            "storage": service_buckets["storage"] / item_count,
            "promotion": service_buckets["promotion"] / item_count,
            "penalty": (abs(amount) / item_count) if is_penalty else 0.0,
            "other_deduction": service_buckets["other_deduction"] / item_count,
            "payout": amount / item_count,
            "source_report": "ozon_finance_transaction_list",
            "raw_ref": raw_ref,
        })
    return rows


def normalize_ozon_rows(client_id: str, operations: list[dict]) -> list[dict]:
    rows = []
    for operation in operations:
        rows.extend(normalize_ozon_operation(client_id, operation))
    return rows
