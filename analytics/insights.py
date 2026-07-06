"""Automatic financial analysis on top of the unified transactions table.

Mirrors what paid seller-analytics tools (Sellerboard, MPStats, Moneyplace)
highlight: loss-making SKUs with the ruble cost of keeping them, dead stock
(expenses with zero sales), ABC classes by payout contribution, channel
unit economics per ruble of realization, promo share (ДРР), payout
concentration, and month-over-month payout dynamics. Everything is
computed from the same filter set the rest of the dashboard uses.
"""
from analytics.metrics import by_product, deductions_breakdown, funnel, monthly_dynamics

DRR_WARNING = 0.10           # promo above 10% of realization deserves a look
CONCENTRATION_WARNING = 0.5  # top-10 SKUs carrying >50% of payout is risky
EXPENSE_SHARE_WARNING = 0.35


def assign_abc(products: list[dict]) -> list[dict]:
    """A: first 80% of positive payout, B: next 15%, C: tail. Loss-makers
    get their own class 'L' — they are an action list, not a tail."""
    positive = sorted((p for p in products if p["payout"] > 0), key=lambda p: -p["payout"])
    total_positive = sum(p["payout"] for p in positive) or 1.0
    cumulative = 0.0
    for product in positive:
        cumulative += product["payout"]
        product["abc"] = "A" if cumulative <= total_positive * 0.8 else "B" if cumulative <= total_positive * 0.95 else "C"
    for product in products:
        if product["payout"] <= 0:
            product["abc"] = "L" if product["payout"] < 0 else "C"
        product["margin"] = (product["payout"] / product["realization"]) if product["realization"] else (-1.0 if product["payout"] < 0 else 0.0)
    return products


def compute_insights(client_id: str, marketplace: str | None = None,
                     date_from: str | None = None, date_to: str | None = None) -> dict:
    products = assign_abc(by_product(client_id, marketplace, date_from, date_to))
    totals = funnel(client_id, marketplace, date_from, date_to)
    deductions = deductions_breakdown(client_id, marketplace, date_from, date_to)
    months = monthly_dynamics(client_id, marketplace, date_from, date_to)

    losers = sorted((p for p in products if p["payout"] < 0), key=lambda p: p["payout"])
    loss_sum = sum(p["payout"] for p in losers)
    dead_stock = [p for p in products if not p["realization"] and not p["returns"] and p["mp_expenses"] > 0]
    dead_cost = sum(p["mp_expenses"] for p in dead_stock)

    by_returns_rub = sorted(products, key=lambda p: -p["returns"])
    top10_returns_share = (
        sum(p["returns"] for p in by_returns_rub[:10]) / totals["returns"]
        if totals["returns"] else 0.0
    )

    positive = sorted((p for p in products if p["payout"] > 0), key=lambda p: -p["payout"])
    positive_total = sum(p["payout"] for p in positive)
    top10_payout_share = (
        sum(p["payout"] for p in positive[:10]) / positive_total if positive_total else 0.0
    )

    channels = {}
    if marketplace is None:
        for channel in ("wb", "ozon"):
            channel_funnel = funnel(client_id, channel, date_from, date_to)
            if not channel_funnel["realization"] and not channel_funnel["payout"]:
                continue
            channel_deductions = deductions_breakdown(client_id, channel, date_from, date_to)
            channels[channel] = {**channel_funnel, **channel_deductions}

    abc_summary = {}
    for cls in ("A", "B", "C", "L"):
        items = [p for p in products if p.get("abc") == cls]
        abc_summary[cls] = {
            "count": len(items),
            "payout": sum(p["payout"] for p in items),
            "share_sku": len(items) / len(products) if products else 0.0,
        }

    mom = None
    if len(months) >= 2:
        prev, last = months[-2], months[-1]
        mom = {
            "prev_month": prev["month"], "last_month": last["month"],
            "prev_payout": prev["payout"], "last_payout": last["payout"],
            "delta": (last["payout"] - prev["payout"]) / abs(prev["payout"]) if prev["payout"] else 0.0,
        }

    realization = totals["realization"]
    return {
        "totals": totals,
        "drr": (deductions["promotion"] / realization) if realization else 0.0,
        "promotion_total": deductions["promotion"],
        "expense_share": (totals["mp_expenses"] / realization) if realization else 0.0,
        "avg_margin": (totals["payout"] / realization) if realization else 0.0,
        "returns_share": (totals["returns"] / realization) if realization else 0.0,
        "losers": losers[:15],
        "losers_count": len(losers),
        "loss_sum": loss_sum,
        "dead_stock_count": len(dead_stock),
        "dead_stock_cost": dead_cost,
        "top_returns": [p for p in by_returns_rub[:10] if p["returns"] > 0],
        "top10_returns_share": top10_returns_share,
        "top10_payout_share": top10_payout_share,
        "abc": abc_summary,
        "channels": channels,
        "mom": mom,
    }
