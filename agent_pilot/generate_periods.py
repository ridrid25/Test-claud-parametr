#!/usr/bin/env python3
"""Генерация трёх отчётных периодов на основе демо-данных дашборда.

Берёт 24 товара из демо-выгрузки (те же SKU, категории, бренды, цены и
структура удержаний), раскладывает по 4 недели на период и накладывает
сценарий, в котором торговому агенту есть что находить:

  * WB-018 Наушники SonaX 18 — топ-продавец, в периоде 3 заканчивается остаток;
  * WB-023 Пледы CozyNest 23 — возвраты растут 31 % → 43 % → 50 % от валовой реализации;
  * OZ-012 Кружки LuceCasa 12 — логистика Ozon дорожает 12 % → 16 % → 20 % от реализации;
  * WB-019 Наушники SonaX 19 — реклама съедает маржу, в периоде 3 ДРР 25 % и цена −10 %;
  * OZ-013 Тарелки Keramo 13 — убыток с учётом себестоимости из-за рекламы (ДРР 14 %);
  * WB-002 Худи Aurelka 02 — почти не продаётся, остаток 340 шт (замороженные деньги);
  * WB-010 Кружки Keramo 10 — в периоде 2 две недели комиссия 17 % вместо 15 % (аудит);
  * общий сезон: период 2 +8 %, период 3 −5 %.

Выход (agent_pilot/data/, разделитель «;», UTF-8):
  sales_p1.csv, sales_p2.csv, sales_p3.csv   — отчёты о реализации в формате дашборда
  costs.csv                                  — себестоимость по SKU
  stocks_p1.csv .. stocks_p3.csv             — остатки на конец периода
  wb_ads_p1.csv .. / ozon_ads_p1.csv ..      — выгрузки рекламных кабинетов
  scenario.json                              — что заложено, для сверки

Детерминированно: random.seed(2026). Никаких зависимостей кроме stdlib.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"
SEED = 2026

# Строка = одна «типовая неделя» из демо-выгрузки (сборка v36).
DEMO = """Маркетплейс;Дата;Артикул;Товар;Категория;Бренд;Продано, шт;Реализация, ₽;Возвраты, ₽;Комиссия МП, ₽;Логистика, ₽;Хранение, ₽;Продвижение, ₽;Штрафы, ₽;Прочие удержания, ₽;К выплате, ₽
Wildberries;2026-06-05;WB-001;Худи Northmoor 01;Одежда/Худи;Northmoor;47;81122;0;12168;8451;346;3244;0;0;56913
Wildberries;2026-06-05;WB-002;Худи Aurelka 02;Одежда/Худи;Aurelka;2;1444;606;216;106;308;0;0;0;208
Wildberries;2026-06-05;WB-003;Худи Aurelka 03;Одежда/Худи;Aurelka;14;34146;0;5121;3603;81;1365;0;0;23976
Ozon;2026-06-05;OZ-004;Худи Aurelka 04;Одежда/Худи;Aurelka;17;21012;1050;3151;1389;194;0;0;0;15228
Ozon;2026-06-05;OZ-005;Футболки Basico 05;Одежда/Футболки;Basico;38;63954;7674;9593;5894;193;0;0;0;40600
Ozon;2026-06-05;OZ-006;Футболки Basico 06;Одежда/Футболки;Basico;36;49932;0;7489;4977;395;0;0;0;37071
Wildberries;2026-06-05;WB-007;Футболки Northmoor 07;Одежда/Футболки;Northmoor;55;55715;6685;8357;5467;186;0;0;0;35020
Ozon;2026-06-05;OZ-008;Футболки Basico 08;Одежда/Футболки;Basico;13;43485;0;6522;4198;87;1739;0;0;30939
Wildberries;2026-06-05;WB-009;Кружки Keramo 09;Посуда/Кружки;Keramo;29;62466;0;9369;6313;393;0;0;0;46391
Wildberries;2026-06-05;WB-010;Кружки Keramo 10;Посуда/Кружки;Keramo;51;96492;0;14473;7011;290;3859;0;0;70859
Ozon;2026-06-05;OZ-011;Кружки Keramo 11;Посуда/Кружки;Keramo;41;108404;13008;16260;7433;71;0;0;0;71632
Ozon;2026-06-05;OZ-012;Кружки LuceCasa 12;Посуда/Кружки;LuceCasa;57;170430;0;25564;20424;70;6817;0;0;117555
Ozon;2026-06-05;OZ-013;Тарелки Keramo 13;Посуда/Тарелки;Keramo;48;38016;0;5702;3712;348;5322;0;0;22932
Ozon;2026-06-05;OZ-014;Тарелки Keramo 14;Посуда/Тарелки;Keramo;24;51912;6229;7786;4762;283;0;0;0;32852
Wildberries;2026-06-05;WB-015;Тарелки LuceCasa 15;Посуда/Тарелки;LuceCasa;49;158025;7901;23703;13603;232;0;0;0;112586
Ozon;2026-06-05;OZ-016;Тарелки Keramo 16;Посуда/Тарелки;Keramo;32;33120;1656;4968;3659;259;4636;0;0;17942
Wildberries;2026-06-05;WB-017;Наушники Voltra 17;Электроника/Наушники;Voltra;23;85629;0;12844;8214;250;0;0;0;64321
Wildberries;2026-06-05;WB-018;Наушники SonaX 18;Электроника/Наушники;SonaX;56;224336;0;33650;14239;290;0;0;0;176157
Wildberries;2026-06-05;WB-019;Наушники SonaX 19;Электроника/Наушники;SonaX;52;45916;0;6887;3108;243;6428;0;0;29250
Wildberries;2026-06-05;WB-020;Наушники SonaX 20;Электроника/Наушники;SonaX;33;137709;0;20656;15937;386;5508;0;0;95222
Wildberries;2026-06-05;WB-021;Пледы Aurelka 21;Дом/Пледы;Aurelka;25;83775;10053;12566;9548;231;0;0;0;51377
Wildberries;2026-06-05;WB-022;Пледы CozyNest 22;Дом/Пледы;CozyNest;4;7936;3333;1190;739;301;0;0;0;2373
Wildberries;2026-06-05;WB-023;Пледы CozyNest 23;Дом/Пледы;CozyNest;45;143280;60177;21492;9176;16;0;0;0;52419
Wildberries;2026-06-05;WB-024;Пледы CozyNest 24;Дом/Пледы;CozyNest;17;56780;0;8517;5871;292;2271;0;0;39829"""

HEADER = DEMO.splitlines()[0].split(";")

# Себестоимость за шт (демо + добавлены OZ-012, WB-015, WB-017, WB-024; OZ-006 нарочно нет).
COSTS = {
    "WB-001": 1059, "WB-002": 271, "WB-003": 1152, "OZ-004": 601, "OZ-005": 958,
    "WB-007": 467, "OZ-008": 2156, "WB-009": 810, "WB-010": 886, "OZ-011": 1057,
    "OZ-012": 1980, "OZ-013": 510, "OZ-014": 692, "WB-015": 1650, "OZ-016": 711,
    "WB-017": 2100, "WB-018": 1468, "WB-019": 340, "WB-020": 1349, "WB-021": 2326,
    "WB-022": 1217, "WB-023": 1493, "WB-024": 1700,
}

# Периоды: по 4 недели, дата строки = понедельник недели.
PERIODS = {
    1: [date(2026, 6, 1) + timedelta(days=7 * i) for i in range(4)],
    2: [date(2026, 6, 29) + timedelta(days=7 * i) for i in range(4)],
    3: [date(2026, 7, 27) + timedelta(days=7 * i) for i in range(4)],
}
SEASON = {1: 1.00, 2: 1.08, 3: 0.95}

# Остатки. База — примерно 2,6 периода продаж, пополнение каждый период равно
# проданному (склад держится ровным). Исключения по сценарию: WB-018 не пополняется
# и заканчивается, WB-002 и WB-022 — неликвид без пополнения, OZ-013 — большой сток
# убыточного товара (замороженные деньги).
STOCK_FIXED_P1 = {"WB-002": 340, "WB-022": 75, "OZ-013": 1300}
NO_INBOUND = {"WB-018", "WB-002", "WB-022", "OZ-013"}
STOCK_COVER_PERIODS = 2.6

# Рекламные кампании: (id, название, тип, маркетплейс, SKU).
CAMPAIGNS = [
    ("WB-C-101", "Аукцион · Наушники SonaX", "Аукцион", "wb", ["WB-019", "WB-020"]),
    ("WB-C-102", "Авто · Худи Northmoor/Aurelka", "Автоматическая", "wb", ["WB-001", "WB-003"]),
    ("WB-C-103", "Авто · Кружки Keramo", "Автоматическая", "wb", ["WB-010"]),
    ("WB-C-104", "Аукцион · Пледы CozyNest 24", "Аукцион", "wb", ["WB-024"]),
    ("OZ-C-201", "Трафареты · Кружки LuceCasa", "Трафареты", "ozon", ["OZ-012"]),
    ("OZ-C-202", "Продвижение в поиске · Тарелки Keramo", "Продвижение в поиске", "ozon", ["OZ-013", "OZ-016"]),
    ("OZ-C-203", "Трафареты · Футболки Basico 08", "Трафареты", "ozon", ["OZ-008"]),
]


def parse_demo() -> list[dict]:
    rows = []
    for line in DEMO.splitlines()[1:]:
        c = line.split(";")
        rows.append({
            "mp": c[0], "sku": c[2], "name": c[3], "category": c[4], "brand": c[5],
            "qty": int(c[6]), "real": float(c[7]), "ret": float(c[8]), "comm": float(c[9]),
            "logi": float(c[10]), "stor": float(c[11]), "promo": float(c[12]),
        })
    return rows


def sku_scenario(p: int, sku: str, week: int) -> dict:
    """Множители сценария для SKU в периоде p, неделе week (0..3)."""
    s = {"qty": 1.0, "price": 1.0, "ret_share": None, "comm_share": None, "logi": 1.0, "promo_share": None}
    if sku == "WB-023":
        s["ret_share"] = {1: 0.45, 2: 0.75, 3: 1.0}[p]   # от реализации; от валовой 31 % → 43 % → 50 %
    if sku == "WB-018":
        if p == 2:
            s["qty"] = 1.15
        if p == 3:
            s["qty"] = {0: 1.0, 1: 0.7, 2: 0.15, 3: 0.0}[week]   # остаток кончился
    if sku == "OZ-012":
        s["logi"] = {1: 1.0, 2: 1.33, 3: 1.67}[p]              # 12 % → 16 % → 20 %
    if sku == "WB-019":
        s["promo_share"] = {1: 0.14, 2: 0.16, 3: 0.25}[p]
        if p == 3:
            s["price"] = 0.90
            s["qty"] = 1.10
    if sku == "OZ-013":
        s["promo_share"] = 0.14
    if sku == "WB-002":
        s["qty"] = 0.6
    if sku == "WB-010" and p == 2 and week in (1, 2):
        s["comm_share"] = 0.17                                  # аномалия комиссии
    if sku == "WB-021" and p == 3:
        s["qty"] = 0.75                                          # сезон пледов заканчивается
    if sku in ("WB-022",) and p >= 2:
        s["qty"] = 0.5
    return s


def gen_sales(rng: random.Random, base: list[dict]) -> dict[int, list[list]]:
    out: dict[int, list[list]] = {}
    for p, weeks in PERIODS.items():
        rows = []
        for w, monday in enumerate(weeks):
            for b in base:
                sc = sku_scenario(p, b["sku"], w)
                noise = rng.uniform(0.85, 1.15)
                qty = round(b["qty"] * SEASON[p] * sc["qty"] * noise)
                unit_price = (b["real"] / b["qty"]) * sc["price"] * rng.uniform(0.98, 1.02)
                real = round(qty * unit_price)
                ret_share = sc["ret_share"] if sc["ret_share"] is not None else (b["ret"] / b["real"] if b["real"] else 0)
                ret = round(real * ret_share * rng.uniform(0.9, 1.1))
                comm_share = sc["comm_share"] if sc["comm_share"] is not None else b["comm"] / b["real"]
                comm = round(real * comm_share)
                logi = round((b["logi"] / b["qty"]) * qty * sc["logi"] * rng.uniform(0.95, 1.05)) if qty else 0
                stor = round(b["stor"] * rng.uniform(0.8, 1.2))
                promo_share = sc["promo_share"] if sc["promo_share"] is not None else b["promo"] / b["real"]
                promo = round(real * promo_share) if promo_share else 0
                payout = real - ret - comm - logi - stor - promo
                rows.append([b["mp"], monday.isoformat(), b["sku"], b["name"], b["category"], b["brand"],
                             qty, real, ret, comm, logi, stor, promo, 0, 0, payout])
        # Служебные операции: штраф за маркировку и эквайринг Ozon (как в демо).
        rows.append(["Wildberries", weeks[2].isoformat(), "WB-050", "Штраф — маркировка", "Прочее/Корректировки", "—",
                     0, 0, 0, 0, 0, 0, 0, 620 if p != 3 else 1860, 0, -(620 if p != 3 else 1860)])
        for monday in weeks:
            rows.append(["Ozon", monday.isoformat(), "OZ-060", "Удержание — эквайринг", "Прочее/Корректировки", "—",
                         0, 0, 0, 0, 0, 0, 0, 0, 450, -450])
        out[p] = rows
    return out


def gen_stocks(sales: dict[int, list[list]]) -> dict[int, dict[str, int]]:
    sold = {p: {} for p in sales}
    for p, rows in sales.items():
        for r in rows:
            if r[2].startswith(("WB-050", "OZ-060")):
                continue
            sold[p][r[2]] = sold[p].get(r[2], 0) + r[6]
    skus = sorted(set(sold[1]))
    stocks: dict[int, dict[str, int]] = {}
    p1 = {}
    for sku in skus:
        if sku in STOCK_FIXED_P1:
            p1[sku] = STOCK_FIXED_P1[sku]
        elif sku == "WB-018":
            p1[sku] = sold[2][sku] + sold[3][sku] + 6      # ровно столько, чтобы в периоде 3 осталось 6 шт
        else:
            p1[sku] = round(sold[1][sku] * STOCK_COVER_PERIODS)
    stocks[1] = p1
    for p in (2, 3):
        prev = stocks[p - 1]
        stocks[p] = {sku: max(0, prev[sku] + (0 if sku in NO_INBOUND else sold[p].get(sku, 0)) - sold[p].get(sku, 0))
                     for sku in skus}
    stocks[3]["WB-018"] = 6
    return stocks


def gen_ads(rng: random.Random, sales: dict[int, list[list]]) -> dict[int, dict[str, list[list]]]:
    """Рекламные выгрузки. Затраты кампании по SKU-неделе = «Продвижение» из отчёта,
    поэтому сумма расходов кабинета сходится со столбцом продвижения."""
    out: dict[int, dict[str, list[list]]] = {}
    for p, rows in sales.items():
        wb, oz = [], []
        by_key = {(r[2], r[1]): r for r in rows}
        for cid, cname, ctype, mp, skus in CAMPAIGNS:
            for monday in PERIODS[p]:
                for sku in skus:
                    r = by_key.get((sku, monday.isoformat()))
                    if not r or r[12] <= 0:
                        continue
                    spend, qty, real = r[12], r[6], r[7]
                    price = real / qty if qty else 0
                    cpc = rng.uniform(9, 14) if mp == "wb" else rng.uniform(12, 18)
                    clicks = max(1, round(spend / cpc))
                    ctr = rng.uniform(0.02, 0.04)
                    impressions = round(clicks / ctr)
                    attribution = 0.3 if (sku == "WB-019" and p == 3) else rng.uniform(0.45, 0.7)
                    orders = round(qty * attribution)
                    order_sum = round(orders * price)
                    cr = orders / clicks if clicks else 0
                    if mp == "wb":
                        wb.append([cid, cname, ctype, monday.isoformat(), sku, impressions, clicks,
                                   f"{ctr * 100:.2f}", f"{spend / clicks:.2f}", spend, orders, order_sum, f"{cr * 100:.2f}"])
                    else:
                        drr = spend / order_sum * 100 if order_sum else 0
                        oz.append([cid, cname, ctype, monday.isoformat(), sku, impressions, clicks,
                                   spend, orders, order_sum, f"{drr:.1f}"])
        out[p] = {"wb": wb, "ozon": oz}
    return out


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    rng = random.Random(SEED)
    base = parse_demo()
    sales = gen_sales(rng, base)
    stocks = gen_stocks(sales)
    ads = gen_ads(rng, sales)
    OUT.mkdir(parents=True, exist_ok=True)
    for p, rows in sales.items():
        write_csv(OUT / f"sales_p{p}.csv", HEADER, rows)
    write_csv(OUT / "costs.csv", ["SKU", "Полная себестоимость за шт"], [[k, v] for k, v in COSTS.items()])
    for p, st in stocks.items():
        write_csv(OUT / f"stocks_p{p}.csv", ["SKU", "Остаток, шт"], [[k, v] for k, v in sorted(st.items())])
    wb_header = ["ID кампании", "Кампания", "Тип кампании", "Дата", "Артикул WB", "Показы", "Клики",
                 "CTR, %", "CPC, ₽", "Затраты, ₽", "Заказы", "Сумма заказов, ₽", "CR, %"]
    oz_header = ["ID кампании", "Кампания", "Тип", "Дата", "Артикул", "Показы", "Клики",
                 "Расход, ₽", "Заказы", "Выручка с заказов, ₽", "ДРР, %"]
    for p, a in ads.items():
        write_csv(OUT / f"wb_ads_p{p}.csv", wb_header, a["wb"])
        write_csv(OUT / f"ozon_ads_p{p}.csv", oz_header, a["ozon"])
    scenario = {
        "periods": {str(p): [d.isoformat() for d in w] + [(w[-1] + timedelta(days=6)).isoformat()] for p, w in PERIODS.items()},
        "season": SEASON,
        "events": [
            "WB-018: остаток кончается в периоде 3 (недели 2–4 почти без продаж), остаток 6 шт",
            "WB-023: доля возвратов от валовой реализации 31% → 43% → 50%",
            "OZ-012: логистика Ozon +33% и +67% к базе в периодах 2 и 3",
            "WB-019: ДРР 14% → 16% → 25%, в периоде 3 цена −10%, атрибуция рекламы 30%",
            "OZ-013: ДРР 14%, убыток с учётом себестоимости во всех периодах",
            "WB-002: продажи ×0.6, остаток 340 шт без пополнения — замороженные деньги",
            "OZ-013: остаток 1300 шт без пополнения — заморожено ~660 тыс. ₽ в убыточном товаре",
            "WB-010: комиссия 17% вместо 15% в неделях 2–3 периода 2",
            "WB-050 штраф маркировка: 620 → 620 → 1860; OZ-060 эквайринг 450/нед",
            "Себестоимости нет у OZ-006 (нарочно, проверка предупреждений)",
        ],
        "totals": {str(p): {"realization": sum(r[7] for r in rows), "returns": sum(r[8] for r in rows),
                            "promotion": sum(r[12] for r in rows), "payout": sum(r[15] for r in rows),
                            "units": sum(r[6] for r in rows)} for p, rows in sales.items()},
    }
    (OUT / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in sales:
        t = scenario["totals"][str(p)]
        print(f"P{p}: реализация {t['realization']:,} ₽, возвраты {t['returns']:,} ₽, продвижение {t['promotion']:,} ₽, к выплате {t['payout']:,} ₽, {t['units']} шт")


if __name__ == "__main__":
    main()
