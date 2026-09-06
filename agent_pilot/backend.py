"""Read-only MerchantBackend поверх выгрузок маркетплейсов (CSV из agent_pilot/data).

Реализует восемь методов чтения интерфейса ``merchant_agent.MerchantBackend`` из
anthropics/commerce-agents на данных, которые уже есть у продавца WB/Ozon:
отчёт о реализации (по неделям), себестоимость по SKU, остатки по SKU и
выгрузки рекламных кабинетов. Все методы записи отказывают исключением
``ChangeNotApplicable`` — это тот самый «пилот только для чтения» из README
репозитория: у агента нет никакого пути что-то изменить в кабинете площадки.

Что важно знать про сопоставление:
  * «продажи» (sales) = реализация − возвраты; «заказов» в отчёте нет — есть штуки;
  * трафика и конверсии нет → None + note, как требует докстринг BusinessSnapshot;
  * маржа в PricingContext — ПОСЛЕ удержаний площадки: (к выплате − себестоимость)/реализация,
    а не «цена − себестоимость», как в примере retail;
  * кампании — из рекламного кабинета; бюджет кабинет не отдаёт, поэтому budget = spend,
    об этом сказано в limitations;
  * период по умолчанию — выбранный при создании бэкенда (1..3), «prior» — предыдущий.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from merchant_agent import (
    ActorKind,
    AlertCounts,
    BusinessSnapshot,
    Campaign,
    CampaignDraft,
    ChangeNotApplicable,
    DataLimitation,
    InventoryActionItem,
    InventoryAlert,
    Listing,
    ListingDetails,
    ListingFilters,
    MerchantAgentConfig,
    MerchantBackend,
    MerchantSessionContext,
    MetricPoint,
    MetricSeries,
    OrderIssue,
    PriceUpdateItem,
    PricingContext,
    PromotionDraft,
    StagedChange,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
READ_ONLY_TEXT = (
    "Этот пилот работает только на чтение: изменения цен, остатков, карточек и кампаний "
    "в кабинетах Wildberries/Ozon отсюда не делаются. Предложите оператору, что изменить, "
    "и он сделает это в кабинете сам."
)

MP_LABEL = {"Wildberries": "wb", "Ozon": "ozon"}
METRICS = {
    "sales": ("реализация − возвраты", "RUB"),
    "revenue": ("реализация − возвраты", "RUB"),
    "realization": ("реализация", "RUB"),
    "returns": ("возвраты", "RUB"),
    "units": ("продано, шт", "шт"),
    "payout": ("к выплате", "RUB"),
    "commission": ("комиссия МП", "RUB"),
    "logistics": ("логистика", "RUB"),
    "storage": ("хранение", "RUB"),
    "promotion": ("продвижение (реклама)", "RUB"),
    "ad_spend": ("продвижение (реклама)", "RUB"),
    "penalties": ("штрафы", "RUB"),
    "other": ("прочие удержания", "RUB"),
    "expenses": ("все удержания площадки", "RUB"),
    "cogs": ("себестоимость проданного", "RUB"),
    "profit": ("к выплате − себестоимость", "RUB"),
    "return_rate": ("доля возвратов, %", "%"),
    "margin": ("(к выплате − себестоимость) / реализация, %", "%"),
}


def _num(v: str) -> float:
    return float(str(v).replace(",", ".").replace(" ", "") or 0)


class Row:
    __slots__ = ("mp", "date", "sku", "name", "category", "brand", "qty", "real", "ret",
                 "comm", "logi", "stor", "promo", "pen", "other", "payout", "service")

    def __init__(self, r: dict[str, str]):
        self.mp = MP_LABEL.get(r["Маркетплейс"], r["Маркетплейс"].lower())
        self.date = r["Дата"]
        self.sku = r["Артикул"]
        self.name = r["Товар"]
        self.category = r["Категория"]
        self.brand = r["Бренд"]
        self.qty = int(_num(r["Продано, шт"]))
        self.real = _num(r["Реализация, ₽"])
        self.ret = _num(r["Возвраты, ₽"])
        self.comm = _num(r["Комиссия МП, ₽"])
        self.logi = _num(r["Логистика, ₽"])
        self.stor = _num(r["Хранение, ₽"])
        self.promo = _num(r["Продвижение, ₽"])
        self.pen = _num(r["Штрафы, ₽"])
        self.other = _num(r["Прочие удержания, ₽"])
        self.payout = _num(r["К выплате, ₽"])
        self.service = self.category.startswith("Прочее/")

    @classmethod
    def from_norm(cls, r: dict[str, Any]) -> "Row":
        """Строка в схеме дашборда: marketplace, period_date, sku, product_name, category,
        brand, quantity, realization, returns, commission, logistics, storage, promotion,
        penalty, other_deduction, payout, service."""
        self = cls.__new__(cls)
        self.mp = "ozon" if "ozon" in str(r.get("marketplace", "")).lower() else "wb"
        self.date = str(r.get("period_date", ""))[:10]
        self.sku = str(r.get("sku", "")); self.name = str(r.get("product_name", ""))
        self.category = str(r.get("category", "")); self.brand = str(r.get("brand", ""))
        g = lambda k: float(r.get(k) or 0)  # noqa: E731
        self.qty = int(g("quantity")); self.real = g("realization"); self.ret = g("returns")
        self.comm = g("commission"); self.logi = g("logistics"); self.stor = g("storage")
        self.promo = g("promotion"); self.pen = g("penalty"); self.other = g("other_deduction")
        self.payout = g("payout"); self.service = bool(r.get("service")) or self.category.startswith("Прочее/")
        return self

    @property
    def expenses(self) -> float:
        return self.comm + self.logi + self.stor + self.promo + self.pen + self.other


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def parse_ads_rows(rows: list[dict[str, str]], marketplace: str) -> list[dict[str, Any]]:
    """Строки рекламной выгрузки WB/Ozon → единый вид. Колонки ищутся по подстрокам."""
    def col(r: dict[str, str], *names: str) -> str:
        for k, v in r.items():
            kl = str(k).lower()
            if any(n in kl for n in names):
                return v
        return ""
    out = []
    for r in rows:
        out.append({
            "id": col(r, "id кампании", "campaign id", "id"), "name": col(r, "кампания", "название кампании", "campaign"),
            "type": col(r, "тип"), "mp": marketplace, "date": col(r, "дата", "date"),
            "sku": col(r, "артикул", "sku", "nm"), "impressions": _num(col(r, "показ", "impress")),
            "clicks": _num(col(r, "клик", "click")), "spend": _num(col(r, "затрат", "расход", "spend", "cost")),
            "orders": _num(col(r, "заказ", "order")), "order_sum": _num(col(r, "сумма заказ", "выручк", "revenue")),
        })
    return [a for a in out if a["sku"] and a["spend"] > 0]


class MarketplaceBackend(MerchantBackend):
    """Бэкенд на данных в памяти: строки отчёта о реализации (все периоды), себестоимость,
    остатки, рекламные строки, границы текущего периода. Предыдущий период — такой же
    длины непосредственно перед текущим."""

    def __init__(self, sales: list[Row], costs: dict[str, float], stocks: dict[str, int],
                 ads: list[dict[str, Any]], current: tuple[str, str],
                 config: MerchantAgentConfig | None = None, store_name: str = "Финсрез / МП",
                 tax_mode: str = "usn_income", tax_rate: float = 6.0, money_rate: float = 24.0,
                 periods: dict[int, tuple[str, str]] | None = None):
        self.config = config or MerchantAgentConfig()
        self.store_name = store_name
        self.tax_mode, self.tax_rate, self.money_rate = tax_mode, tax_rate, money_rate
        self.all_sales = sales
        self.costs = costs
        self.stocks = stocks
        self.ads = ads
        self.periods = periods or {}
        self.cur = current
        length = (date.fromisoformat(current[1]) - date.fromisoformat(current[0])).days + 1
        prev_to = date.fromisoformat(current[0]) - timedelta(days=1)
        prev_from = prev_to - timedelta(days=length - 1)
        self.prev = (prev_from.isoformat(), prev_to.isoformat())
        if not any(prev_from.isoformat() <= r.date <= prev_to.isoformat() for r in sales):
            self.prev = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any], **kw) -> "MarketplaceBackend":
        """Пакет агрегатов из дашборда: rows (нормализованные строки), costs, stocks,
        ads (уже в едином виде), period {from,to}, settings {taxMode, taxRate, moneyRate}."""
        rows = [Row.from_norm(r) for r in payload.get("rows", [])]
        costs = {str(k): float(v) for k, v in (payload.get("costs") or {}).items()}
        stocks = {str(k): int(v) for k, v in (payload.get("stocks") or {}).items()}
        ads = payload.get("ads") or []
        per = payload.get("period") or {}
        dates = [r.date for r in rows if r.date]
        cur = (per.get("from") or min(dates), per.get("to") or max(dates))
        st = payload.get("settings") or {}
        mode = {"usn_income": "usn_income", "usn_profit": "usn_profit"}.get(st.get("taxMode"), "none")
        return cls(rows, costs, stocks, ads, cur, tax_mode=mode, tax_rate=float(st.get("taxRate") or 0),
                   money_rate=float(st.get("moneyRate") or 24), **kw)


    # ------------------------------------------------------------------ helpers
    def _rows(self, period: str | None = None) -> tuple[list[Row], str]:
        """Строки за период и его подпись. period: None|current, prior|previous,
        pN (только для CSV-набора), ISO 'YYYY-MM-DD/YYYY-MM-DD'."""
        a, b = self.cur
        if period:
            t = period.strip().lower()
            if t in ("prior", "previous", "last", "прошлый", "предыдущий"):
                if not self.prev:
                    return [], "нет данных за предыдущий период"
                a, b = self.prev
            elif t.startswith("p") and t[1:].isdigit() and int(t[1:]) in self.periods:
                a, b = self.periods[int(t[1:])]
            elif "/" in t:
                a, b = (x.strip() for x in t.split("/", 1))
        rows = [r for r in self.all_sales if a <= r.date <= b]
        return rows, f"{a}/{b}"

    def _label(self, which: str) -> str | None:
        if which == "prior":
            return f"{self.prev[0]}/{self.prev[1]}" if self.prev else None
        return f"{self.cur[0]}/{self.cur[1]}"

    @staticmethod
    def _sum(rows: list[Row], key: str) -> float:
        if key in ("sales", "revenue"):
            return sum(r.real - r.ret for r in rows)
        if key == "expenses":
            return sum(r.expenses for r in rows)
        attr = {"realization": "real", "returns": "ret", "units": "qty", "payout": "payout", "commission": "comm",
                "logistics": "logi", "storage": "stor", "promotion": "promo", "ad_spend": "promo",
                "penalties": "pen", "other": "other"}[key]
        return sum(getattr(r, attr) for r in rows)

    def _cogs(self, rows: list[Row]) -> float:
        return sum(self.costs.get(r.sku, 0) * r.qty for r in rows if r.sku in self.costs)

    def _by_sku(self, rows: list[Row]) -> dict[str, dict[str, Any]]:
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.service:
                continue
            a = agg.setdefault(r.sku, {"sku": r.sku, "name": r.name, "category": r.category, "brand": r.brand,
                                       "mp": r.mp, "qty": 0, "real": 0.0, "ret": 0.0, "payout": 0.0, "expenses": 0.0,
                                       "promo": 0.0, "logi": 0.0, "comm": 0.0})
            a["qty"] += r.qty; a["real"] += r.real; a["ret"] += r.ret; a["payout"] += r.payout
            a["expenses"] += r.expenses; a["promo"] += r.promo; a["logi"] += r.logi; a["comm"] += r.comm
        for a in agg.values():
            a["price"] = round(a["real"] / a["qty"], 2) if a["qty"] else 0.0
            a["unit_cost"] = self.costs.get(a["sku"])
            a["cogs"] = a["unit_cost"] * a["qty"] if a["unit_cost"] is not None else None
            a["profit"] = a["payout"] - a["cogs"] if a["cogs"] is not None else None
            gross = a["real"] + a["ret"]
            a["return_rate"] = round(a["ret"] / gross * 100, 1) if gross else 0.0
            a["stock"] = self.stocks.get(a["sku"])
        return agg

    def _period_days(self, rows: list[Row] | None = None) -> int:
        return (date.fromisoformat(self.cur[1]) - date.fromisoformat(self.cur[0])).days + 1

    def _segment_match(self, r: Row, segment: str | None) -> bool:
        if not segment:
            return True
        s = segment.strip().lower()
        key, _, val = s.partition(":")
        if val:
            val = val.strip()
            if key in ("category", "категория"):
                return val in r.category.lower()
            if key in ("brand", "бренд"):
                return val == r.brand.lower()
            if key in ("sku", "listing", "listing_id", "артикул"):
                return val == r.sku.lower()
            if key in ("marketplace", "mp", "маркетплейс", "channel"):
                return val in (r.mp, {"wb": "wildberries", "ozon": "ozon"}.get(r.mp, ""))
        return (s in r.category.lower() or s == r.brand.lower() or s == r.sku.lower()
                or s in (r.mp, "wildberries" if r.mp == "wb" else r.mp))

    def _alerts(self) -> list[InventoryAlert]:
        rows, _ = self._rows()
        days = self._period_days(rows) or 28
        alerts: list[InventoryAlert] = []
        by = self._by_sku(rows)
        for sku, stock in sorted(self.stocks.items()):
            a = by.get(sku)
            sold = a["qty"] if a else 0
            pace = sold / days if days else 0
            cover = round(stock / pace, 1) if pace else None
            threshold = int(round(pace * 14))  # две недели продаж
            title = a["name"] if a else sku
            if pace and stock <= threshold:
                alerts.append(InventoryAlert(listing_id=sku, title=title, kind="low_stock", stock=stock,
                                             threshold=threshold, days_of_cover=cover, sales_last_30d=sold,
                                             storefront_visible=stock > 0))
            elif stock > 0 and (not pace or cover is not None and cover > 180):
                alerts.append(InventoryAlert(listing_id=sku, title=title, kind="slow_mover", stock=stock,
                                             threshold=threshold or None, days_of_cover=cover, sales_last_30d=sold,
                                             storefront_visible=True))
        alerts.sort(key=lambda x: (x.kind != "low_stock", -(x.sales_last_30d or 0)))
        return alerts

    def _issues(self) -> list[OrderIssue]:
        cur = self._by_sku(self._rows()[0])
        prev = self._by_sku(self._rows("prior")[0]) if self.prev else {}
        issues = []
        for sku, a in cur.items():
            rate, before = a["return_rate"], prev.get(sku, {}).get("return_rate")
            if rate >= 30 and (before is None or rate >= before + 3):
                issues.append(OrderIssue(
                    issue_id=f"ret-{sku}", order_id=f"агрегат по {sku}", kind="return_spike", listing_id=sku,
                    summary=f"{a['name']}: возвраты {rate:.0f}% от валовой реализации"
                            + (f" (в прошлом периоде {before:.0f}%)" if before is not None else "")
                            + f", {a['ret']:,.0f} ₽ за период. Причины возвратов в отчёте не указаны.",
                ))
        return issues

    def _campaigns(self) -> list[Campaign]:
        by: dict[str, dict[str, Any]] = {}
        for r in self.ads:
            c = by.setdefault(r["id"], {"name": r["name"], "type": r["type"], "mp": r["mp"], "spend": 0.0,
                                        "orders": 0.0, "order_sum": 0.0, "dates": [], "skus": set()})
            c["spend"] += r["spend"]; c["orders"] += r["orders"]; c["order_sum"] += r["order_sum"]
            c["dates"].append(r["date"]); c["skus"].add(r["sku"])
        by_sku = self._by_sku(self._rows()[0])
        out = []
        for cid, c in sorted(by.items()):
            # Маржа SKU после удержаний и себестоимости — чтобы ROAS кабинета читался
            # вместе с фактической прибыльностью товара, а не отдельно от неё.
            margins = []
            for sku in sorted(c["skus"]):
                a = by_sku.get(sku)
                if a and a["profit"] is not None and a["real"]:
                    margins.append(f"{sku} маржа после удержаний {a['profit'] / a['real'] * 100:+.1f}%")
                elif a:
                    margins.append(f"{sku} маржа неизвестна (нет себестоимости)")
            objective = f"{c['type']} — продажи {', '.join(sorted(c['skus']))}. " + "; ".join(margins)
            out.append(Campaign(
                campaign_id=cid, name=c["name"], status="active",
                objective=objective[:200],
                channel=f"{'Wildberries' if c['mp'] == 'wb' else 'Ozon'} · {c['type']}",
                budget=round(c["spend"], 2), spend=round(c["spend"], 2), revenue=round(c["order_sum"], 2),
                currency="RUB", starts=min(c["dates"]),
                ends=(date.fromisoformat(max(c["dates"])) + timedelta(days=6)).isoformat(),
            ))
        return out

    def _listing(self, a: dict[str, Any]) -> Listing:
        stock = a["stock"]
        status = "out_of_stock" if stock == 0 else ("paused" if a["qty"] == 0 else "active")
        return Listing(listing_id=a["sku"], title=a["name"], status=status, price=a["price"] or 0.01, currency="RUB",
                       stock=stock or 0, category=a["category"],
                       attributes={"brand": a["brand"], "marketplace": "Wildberries" if a["mp"] == "wb" else "Ozon"})

    # ------------------------------------------------------------------ reads
    async def get_business_snapshot(self, session: MerchantSessionContext, period: str | None = None) -> BusinessSnapshot:
        rows, label = self._rows(period)
        prior_rows: list[Row] = []
        if not period or period.strip().lower() in ("current", "this", "текущий"):
            prior_rows, prior_label = self._rows("prior") if self.prev else ([], None)
        else:
            prior_label = None
        sales = self._sum(rows, "sales")
        units = self._sum(rows, "units")
        pct = lambda cur, prev: round((cur - prev) / prev * 100, 1) if prev else None  # noqa: E731
        alerts = self._alerts()
        note = "Заказов, трафика и конверсии в отчёте о реализации нет; orders = None, units см. query_metrics('units')."
        return BusinessSnapshot(
            period=label, compare_to=prior_label, sales=round(sales, 2), orders=0, traffic=None, conversion_rate=None,
            average_order_value=round(sales / units, 2) if units else None,
            sales_change_pct=pct(sales, self._sum(prior_rows, "sales")) if prior_rows else None,
            orders_change_pct=pct(units, self._sum(prior_rows, "units")) if prior_rows else None,
            traffic_change_pct=None, conversion_change_pct=None, currency="RUB",
            alerts=AlertCounts(low_stock=sum(a.kind == "low_stock" for a in alerts),
                               slow_movers=sum(a.kind == "slow_mover" for a in alerts),
                               order_issues=len(self._issues()), pending_changes=0),
            note=note[:140],
        )

    async def query_metrics(self, session: MerchantSessionContext, metric: str, period: str | None = None,
                            granularity: str = "day", segment: str | None = None) -> MetricSeries:
        key = metric.strip().lower().replace(" ", "_")
        rows, label = self._rows(period)
        if key not in METRICS:
            return MetricSeries(metric=metric, granularity="week", period=label, segment=segment, points=[],
                                note=f"Нет такой метрики. Доступны: {', '.join(sorted(METRICS))}."[:140])
        rows = [r for r in rows if self._segment_match(r, segment)]
        if granularity == "month":
            bucket = lambda d: d[:7]  # noqa: E731
        else:
            bucket = lambda d: d  # noqa: E731
        groups: dict[str, list[Row]] = defaultdict(list)
        for r in rows:
            groups[bucket(r.date)].append(r)
        points = []
        for d in sorted(groups):
            g = groups[d]
            if key in ("cogs", "profit", "margin"):
                cogs = self._cogs(g)
                val = cogs if key == "cogs" else (self._sum(g, "payout") - cogs if key == "profit"
                                                  else (self._sum(g, "payout") - cogs) / self._sum(g, "realization") * 100
                                                  if self._sum(g, "realization") else 0.0)
            elif key == "return_rate":
                gross = self._sum(g, "realization") + self._sum(g, "returns")
                val = self._sum(g, "returns") / gross * 100 if gross else 0.0
            else:
                val = self._sum(g, key)
            points.append(MetricPoint(date=d, value=round(val, 2)))
        desc, unit = METRICS[key]
        note = f"{desc}. Отчёт недельный: точка = неделя с понедельника" + ("; дневной разбивки нет." if granularity == "day" else ".")
        return MetricSeries(metric=key, unit=unit, granularity="month" if granularity == "month" else "week",
                            period=label, segment=segment, points=points, note=note[:140])

    async def get_campaign_performance(self, session: MerchantSessionContext, campaign_id: str | None = None) -> list[Campaign]:
        camps = self._campaigns()
        return [c for c in camps if c.campaign_id == campaign_id] if campaign_id else camps

    async def search_listings(self, session: MerchantSessionContext, query: str,
                              filters: ListingFilters | None = None, limit: int = 8) -> list[Listing]:
        by = self._by_sku(self._rows()[0])
        q = (query or "").strip().lower()
        items = [self._listing(a) for a in by.values()
                 if q in ("", "*", "all") or q in a["name"].lower() or q == a["sku"].lower()
                 or q in a["category"].lower() or q == a["brand"].lower()]
        if filters:
            if filters.status:
                items = [i for i in items if i.status == filters.status]
            if filters.category:
                items = [i for i in items if filters.category.lower() in (i.category or "").lower()]
            if filters.max_stock is not None:
                items = [i for i in items if i.stock <= filters.max_stock]
            sort = filters.sort or "relevance"
            if sort == "sales_desc":
                items.sort(key=lambda i: -by[i.listing_id]["qty"])
            elif sort == "stock_asc":
                items.sort(key=lambda i: i.stock)
            elif sort == "price_desc":
                items.sort(key=lambda i: -i.price)
            elif sort == "price_asc":
                items.sort(key=lambda i: i.price)
        return items[:limit]

    async def get_listing(self, session: MerchantSessionContext, listing_id: str) -> ListingDetails | None:
        by = self._by_sku(self._rows()[0])
        a = by.get(listing_id)
        if a is None:
            return None
        base = self._listing(a)
        return ListingDetails(**base.model_dump(), long_description=None, review_snippets=[],
                              sales_last_30d=a["qty"], return_rate_pct=a["return_rate"],
                              missing_attributes=["description", "images"], variants=[])

    async def get_inventory_alerts(self, session: MerchantSessionContext) -> list[InventoryAlert]:
        return self._alerts()

    async def get_order_issues(self, session: MerchantSessionContext) -> list[OrderIssue]:
        return self._issues()

    async def get_pricing_context(self, session: MerchantSessionContext, listing_id: str) -> PricingContext | None:
        cur = self._by_sku(self._rows()[0]).get(listing_id)
        if cur is None:
            return None
        prev = self._by_sku(self._rows("prior")[0]).get(listing_id) if self.prev else None
        unit_cost = cur["unit_cost"]
        real = cur["real"]
        # Маржа после удержаний площадки: (к выплате − себестоимость) / реализация.
        margin = round((cur["payout"] - unit_cost * cur["qty"]) / real * 100, 1) if (unit_cost is not None and real) else None
        # Минимальная цена = точка безубыточности: себестоимость / (доля выплаты в реализации).
        payout_share = cur["payout"] / real if real else 0
        min_price = round(unit_cost / payout_share, 2) if (unit_cost is not None and payout_share > 0) else None
        demand = None
        if prev and prev["qty"]:
            ch = (cur["qty"] - prev["qty"]) / prev["qty"]
            demand = "rising" if ch > 0.1 else "falling" if ch < -0.1 else "steady"
        return PricingContext(listing_id=listing_id, current_price=cur["price"] or 0.01, currency="RUB",
                              unit_cost=unit_cost, margin_pct=margin, min_price=min_price,
                              max_price=round((cur["price"] or 0) * 1.35, 2) or None,
                              max_price_delta_pct=self.config.max_price_delta_pct,
                              max_promotion_discount_pct=self.config.max_promotion_discount_pct,
                              min_price_basis="cost" if min_price else None, demand_signal=demand,
                              last_changed=None)

    # ------------------------------------------------------------------ writes: refuse
    async def stage_listing_update(self, session, listing_id, fields, note=None) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def stage_price_update(self, session, items: list[PriceUpdateItem], note=None) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def stage_inventory_action(self, session, items: list[InventoryActionItem], note=None) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def stage_promotion(self, session, promotion: PromotionDraft) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def stage_campaign(self, session, campaign: CampaignDraft) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def get_pending_changes(self, session) -> list[StagedChange]:
        return []

    async def apply_change(self, session, change_id: str) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    async def discard_change(self, session, change_id: str, actor_kind: ActorKind = ActorKind.OPERATOR) -> StagedChange:
        raise ChangeNotApplicable(READ_ONLY_TEXT)

    # ------------------------------------------------------------------ context
    async def get_merchant_context(self, session: MerchantSessionContext) -> dict[str, Any] | None:
        rows, label = self._rows()
        by = self._by_sku(rows)
        frozen = sum(self.stocks.get(s, 0) * c for s, c in self.costs.items())
        days = self._period_days(rows)
        income = self._sum(rows, "sales")
        cogs = self._cogs(rows)
        payout = self._sum(rows, "payout")
        tax = income * self.tax_rate / 100 if self.tax_mode == "usn_income" else max(0.0, payout - cogs) * self.tax_rate / 100 if self.tax_mode == "usn_profit" else 0.0
        no_cost = sorted(s for s, a in by.items() if a["unit_cost"] is None and a["qty"] > 0)
        alerts = self._alerts()
        losers = sorted((a for a in by.values() if a["profit"] is not None and a["profit"] < 0), key=lambda a: a["profit"])
        frozen_by_sku = sorted(((sku, self.stocks.get(sku, 0) * c) for sku, c in self.costs.items() if self.stocks.get(sku)),
                               key=lambda x: -x[1])
        return {
            "loss_making_skus": [
                {"sku": a["sku"], "title": a["name"], "profit_after_cogs": round(a["profit"], 2),
                 "margin_after_deductions_pct": round(a["profit"] / a["real"] * 100, 1) if a["real"] else None,
                 "ad_spend": round(a["promo"], 2), "stock": a["stock"],
                 "frozen_rub": round((a["stock"] or 0) * (a["unit_cost"] or 0), 2)}
                for a in losers[:8]
            ],
            "frozen_by_sku_top": [{"sku": sku, "frozen_rub": round(v, 2), "stock": self.stocks.get(sku)} for sku, v in frozen_by_sku[:8]],
            "frozen_note": "заморожено = остаток × себестоимость за шт (не × цена продажи)",
            "store": self.store_name, "operator": session.operator, "currency": "RUB",
            "current_period": label, "prior_period": self._label("prior"),
            "data_source": "отчёты о реализации Wildberries и Ozon по неделям + файл себестоимости + файл остатков + выгрузки рекламных кабинетов",
            "catalog_size": len(by),
            "finance": {
                "payout_total": round(payout, 2), "cogs_total": round(cogs, 2), "profit_total": round(payout - cogs, 2),
                "tax_mode": self.tax_mode, "tax_rate_pct": self.tax_rate, "tax_for_period": round(tax, 2),
                "tax_note": "налог считается со всей выручки периода, по SKU только распределяется пропорционально выручке",
                "frozen_in_stock": round(frozen, 2), "money_rate_pct": self.money_rate,
                "cost_of_frozen_money_for_period": round(frozen * self.money_rate / 100 * days / 365, 2),
                "period_days": days,
            },
            "limitations": [
                DataLimitation(source="orders", note="заказов нет — только штуки и суммы по SKU за неделю").model_dump(),
                DataLimitation(source="traffic", note="трафика и конверсии в отчёте о реализации нет").model_dump(),
                DataLimitation(source="campaigns", note="бюджет кабинет не отдаёт: budget = фактический расход; выручка = атрибуция кабинета").model_dump(),
                DataLimitation(source="returns", note="причины возвратов и номера заказов недоступны; всплеск — по доле возвратов SKU").model_dump(),
                DataLimitation(source="costs", note=f"нет себестоимости у {len(no_cost)} проданных SKU: {', '.join(no_cost) or '—'}"[:140]).model_dump(),
                DataLimitation(source="writes", note="пилот только на чтение: любое изменение оператор делает в кабинете сам").model_dump(),
            ],
            "alerts": {"low_stock": sum(a.kind == "low_stock" for a in alerts),
                       "slow_movers": sum(a.kind == "slow_mover" for a in alerts),
                       "order_issues": len(self._issues()), "pending_changes": 0},
        }


class MarketplaceCsvBackend(MarketplaceBackend):
    """Бэкенд над CSV из agent_pilot/data; ``period`` — номер текущего периода (1..3)."""

    def __init__(self, data_dir: Path = DATA_DIR, period: int = 3, **kw):
        self.data_dir = Path(data_dir)
        self.period = period
        sales: list[Row] = []
        periods: dict[int, tuple[str, str]] = {}
        for p in (1, 2, 3):
            f = self.data_dir / f"sales_p{p}.csv"
            if f.exists():
                rows = [Row(r) for r in _read(f)]
                sales += rows
                first = min(r.date for r in rows)
                last = (date.fromisoformat(max(r.date for r in rows)) + timedelta(days=6)).isoformat()
                periods[p] = (first, last)
        costs = {r["SKU"]: _num(r["Полная себестоимость за шт"]) for r in _read(self.data_dir / "costs.csv")}
        sf = self.data_dir / f"stocks_p{period}.csv"
        stocks = {r["SKU"]: int(_num(r["Остаток, шт"])) for r in _read(sf)} if sf.exists() else {}
        ads: list[dict[str, Any]] = []
        wb = self.data_dir / f"wb_ads_p{period}.csv"
        if wb.exists():
            ads += parse_ads_rows(_read(wb), "wb")
        oz = self.data_dir / f"ozon_ads_p{period}.csv"
        if oz.exists():
            ads += parse_ads_rows(_read(oz), "ozon")
        super().__init__(sales, costs, stocks, ads, periods[period], periods=periods, **kw)
