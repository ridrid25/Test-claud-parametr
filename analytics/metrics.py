"""Aggregate the unified transactions table into the numbers the dashboard shows.

All functions take the same filter set (client_id required; marketplace,
date_from, date_to optional) so the UI's filter panel maps 1:1 onto these
calls.
"""
from storage.db import connect

RETURN_RATE_RED_ZONE = 0.30  # 30%+ returns on a SKU is worth a human look
# Also duplicated as RETURN_RATE_RED_ZONE in dashboard/static/app.js (the
# returns tab filters client-side) — keep both in sync if this changes.
EXPENSE_SHARE_RED_ZONE = 0.50  # MP fees eating 50%+ of revenue on a SKU


def _where(client_id: str, marketplace: str | None, date_from: str | None, date_to: str | None):
    clauses = ["client_id = ?"]
    params: list = [client_id]
    if marketplace:
        clauses.append("marketplace = ?")
        params.append(marketplace)
    if date_from:
        clauses.append("period_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("period_date <= ?")
        params.append(date_to)
    return " AND ".join(clauses), params


def funnel(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None) -> dict:
    where, params = _where(client_id, marketplace, date_from, date_to)
    query = f"""
        SELECT
            COALESCE(SUM(realization), 0) AS realization,
            COALESCE(SUM(returns), 0) AS returns,
            COALESCE(SUM(commission + logistics + storage + promotion + penalty + other_deduction), 0) AS mp_expenses,
            COALESCE(SUM(payout), 0) AS payout
        FROM transactions
        WHERE {where}
    """
    with connect() as conn:
        row = conn.execute(query, params).fetchone()
    realization = row["realization"]
    returns = row["returns"]
    net_revenue = realization - returns
    return {
        "realization": realization,
        "returns": returns,
        "net_revenue": net_revenue,
        "mp_expenses": row["mp_expenses"],
        "payout": row["payout"],
    }


def deductions_breakdown(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None) -> dict:
    where, params = _where(client_id, marketplace, date_from, date_to)
    query = f"""
        SELECT
            COALESCE(SUM(commission), 0) AS commission,
            COALESCE(SUM(logistics), 0) AS logistics,
            COALESCE(SUM(storage), 0) AS storage,
            COALESCE(SUM(promotion), 0) AS promotion,
            COALESCE(SUM(penalty), 0) AS penalty,
            COALESCE(SUM(other_deduction), 0) AS other_deduction
        FROM transactions
        WHERE {where}
    """
    with connect() as conn:
        row = conn.execute(query, params).fetchone()
    return dict(row)


def by_product(client_id: str, marketplace: str | None = None, date_from: str | None = None,
               date_to: str | None = None, costs: dict[str, float] | None = None) -> list[dict]:
    """Per-SKU aggregates. When `costs` (sku -> unit cost) is given, each row
    also carries себестоимость fields (unit_cost, cogs, profit) and the
    "result"/"margin" metric switches from payout to net profit — this is
    what drives the cost-aware analysis, ABC and product cards."""
    where, params = _where(client_id, marketplace, date_from, date_to)
    query = f"""
        SELECT
            sku,
            MAX(product_name) AS product_name,
            MAX(COALESCE(category, '')) AS category,
            MAX(COALESCE(brand, '')) AS brand,
            MAX(marketplace) AS marketplace,
            COALESCE(SUM(quantity), 0) AS quantity,
            COALESCE(SUM(realization), 0) AS realization,
            COALESCE(SUM(returns), 0) AS returns,
            COALESCE(SUM(commission), 0) AS commission,
            COALESCE(SUM(logistics), 0) AS logistics,
            COALESCE(SUM(storage), 0) AS storage,
            COALESCE(SUM(promotion), 0) AS promotion,
            COALESCE(SUM(penalty), 0) AS penalty,
            COALESCE(SUM(other_deduction), 0) AS other_deduction,
            COALESCE(SUM(commission + logistics + storage + promotion + penalty + other_deduction), 0) AS mp_expenses,
            COALESCE(SUM(payout), 0) AS payout
        FROM transactions
        WHERE {where}
        GROUP BY sku
        ORDER BY payout ASC
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    costs = costs or {}
    costs_loaded = bool(costs)
    for row in rows:
        gross = row["realization"] + row["returns"]
        row["return_rate"] = (row["returns"] / gross) if gross else 0.0
        row["net_revenue"] = row["realization"] - row["returns"]
        row["payout_margin"] = (row["payout"] / row["realization"]) if row["realization"] else (-1.0 if row["payout"] < 0 else 0.0)

        # Себестоимость: COGS = закупочная цена за шт × продано шт; прибыль = к выплате − COGS.
        unit_cost = costs.get(row["sku"])
        row["unit_cost"] = unit_cost
        row["cogs"] = unit_cost * (row["quantity"] or 0) if unit_cost is not None else 0.0
        row["profit"] = row["payout"] - row["cogs"]
        row["profit_margin"] = (row["profit"] / row["realization"]) if row["realization"] else (-1.0 if row["profit"] < 0 else 0.0)

        # The "result"/"margin" the UI ranks and colours by: net profit when
        # costs are loaded, otherwise к выплате.
        row["result"] = row["profit"] if costs_loaded else row["payout"]
        row["margin"] = row["profit_margin"] if costs_loaded else row["payout_margin"]

        red_flags = []
        if row["result"] < 0:
            red_flags.append("убыток с уч. себестоимости" if costs_loaded else "убыток")
        if row["return_rate"] >= RETURN_RATE_RED_ZONE:
            red_flags.append("высокая возвратность")
        if row["net_revenue"] < 0:
            red_flags.append("отрицательная чистая выручка")
        elif row["realization"] and (row["mp_expenses"] / row["realization"]) >= EXPENSE_SHARE_RED_ZONE:
            red_flags.append("высокая доля расходов МП")
        row["red_flags"] = red_flags
    rows.sort(key=lambda r: r["result"])
    return rows


def monthly_dynamics(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    where, params = _where(client_id, marketplace, date_from, date_to)
    query = f"""
        SELECT
            substr(period_date, 1, 7) AS month,
            COALESCE(SUM(realization), 0) AS realization,
            COALESCE(SUM(returns), 0) AS returns,
            COALESCE(SUM(commission + logistics + storage + promotion + penalty + other_deduction), 0) AS mp_expenses,
            COALESCE(SUM(payout), 0) AS payout
        FROM transactions
        WHERE {where}
        GROUP BY month
        ORDER BY month
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    for row in rows:
        row["net_revenue"] = row["realization"] - row["returns"]
    return rows


def plan_vs_fact(client_id: str, period: str, marketplace: str | None = None) -> list[dict]:
    """period is a 'YYYY-MM' month; compares plan_targets against that month's actuals."""
    actual = funnel(client_id, marketplace, date_from=f"{period}-01", date_to=f"{period}-31")
    with connect() as conn:
        plans = {
            r["metric"]: r["plan_value"]
            for r in conn.execute(
                "SELECT metric, plan_value FROM plan_targets WHERE client_id = ? AND period = ?",
                (client_id, period),
            ).fetchall()
        }
    results = []
    for metric in ("net_revenue", "payout"):
        plan_value = plans.get(metric)
        fact_value = actual[metric]
        results.append({
            "metric": metric,
            "plan": plan_value,
            "fact": fact_value,
            "delta": (fact_value - plan_value) if plan_value is not None else None,
        })
    return results
