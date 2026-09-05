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
from datetime import date, datetime, timedelta, timezone
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

    @property
    def expenses(self) -> float:
        return self.comm + self.logi + self.stor + self.promo + self.pen + self.other


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


class MarketplaceCsvBackend(MerchantBackend):
    """Бэкенд над CSV; ``period`` — номер текущего периода (1..3)."""

    def __init__(self, data_dir: Path = DATA_DIR, period: int = 3,
                 config: MerchantAgentConfig | None = None, store_name: str = "Финсрез / МП",
                 tax_mode: str = "usn_income", tax_rate: float = 6.0, money_rate: float = 24.0):
        self.data_dir = Path(data_dir)
        self.period = period
        self.config = config or MerchantAgentConfig()
        self.store_name = store_name
        self.tax_mode, self.tax_rate, self.money_rate = tax_mode, tax_rate, money_rate
        self.sales: dict[int, list[Row]] = {}
        for p in (1, 2, 3):
            f = self.data_dir / f"sales_p{p}.csv"
            if f.exists():
                self.sales[p] = [Row(r) for r in _read(f)]
        self.costs = {r["SKU"]: _num(r["Полная себестоимость за шт"]) for r in _read(self.data_dir / "costs.csv")}
        sf = self.data_dir / f"stocks_p{period}.csv"
        self.stocks = {r["SKU"]: int(_num(r["Остаток, шт"])) for r in _read(sf)} if sf.exists() else {}
        self.ads: list[dict[str, Any]] = []
        wb = self.data_dir / f"wb_ads_p{period}.csv"
        if wb.exists():
            for r in _read(wb):
                self.ads.append({"id": r["ID кампании"], "name": r["Кампания"], "type": r["Тип кампании"], "mp": "wb",
                                 "date": r["Дата"], "sku": r["Артикул WB"], "impressions": _num(r["Показы"]),
                                 "clicks": _num(r["Клики"]), "spend": _num(r["Затраты, ₽"]), "orders": _num(r["Заказы"]),
                                 "order_sum": _num(r["Сумма заказов, ₽"])})
        oz = self.data_dir / f"ozon_ads_p{period}.csv"
        if oz.exists():
            for r in _read(oz):
                self.ads.append({"id": r["ID кампании"], "name": r["Кампания"], "type": r["Тип"], "mp": "ozon",
                                 "date": r["Дата"], "sku": r["Артикул"], "impressions": _num(r["Показы"]),
                                 "clicks": _num(r["Клики"]), "spend": _num(r["Расход, ₽"]), "orders": _num(r["Заказы"]),
                                 "order_sum": _num(r["Выручка с заказов, ₽"])})

    # ------------------------------------------------------------------ helpers
    def _rows(self, period: str | None = None) -> tuple[list[Row], str]:
        """Строки за период и его подпись. period: None|current, prior|previous,
        p1..p3, ISO 'YYYY-MM-DD/YYYY-MM-DD'."""
        p = self.period
        if period:
            t = period.strip().lower()
            if t in ("prior", "previous", "last", "прошлый", "предыдущий"):
                p = self.period - 1
            elif t.startswith("p") and t[1:].isdigit():
                p = int(t[1:])
            elif "/" in t:
                a, b = (x.strip() for x in t.split("/", 1))
                rows = [r for rows in self.sales.values() for r in rows if a <= r.date <= b]
                return rows, f"{a}/{b}"
        rows = self.sales.get(p, [])
        return rows, self._label(p)

    def _label(self, p: int) -> str:
        rows = self.sales.get(p)
        if not rows:
            return f"p{p}"
        first = min(r.date for r in rows)
        last = (date.fromisoformat(max(r.date for r in rows)) + timedelta(days=6)).isoformat()
        return f"{first}/{last}"

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

    def _period_days(self, rows: list[Row]) -> int:
        if not rows:
            return 0
        first, last = min(r.date for r in rows), max(r.date for r in rows)
        return (date.fromisoformat(last) - date.fromisoformat(first)).days + 7

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
        prev = self._by_sku(self._rows("prior")[0]) if self.period > 1 else {}
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
        out = []
        for cid, c in sorted(by.items()):
            out.append(Campaign(
                campaign_id=cid, name=c["name"], status="active",
                objective=f"{c['type']} — продажи {', '.join(sorted(c['skus']))} (по данным кабинета)",
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
            prior_rows, prior_label = self._rows("prior") if self.period > 1 else ([], None)
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
        prev = self._by_sku(self._rows("prior")[0]).get(listing_id) if self.period > 1 else None
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
        return {
            "store": self.store_name, "operator": session.operator, "currency": "RUB",
            "current_period": label, "prior_period": self._label(self.period - 1) if self.period > 1 else None,
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
