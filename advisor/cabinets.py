"""Рекламные кабинеты WB и Ozon → строки статистики кампаний для советника.

Только стандартная библиотека. Ключи живут в окружении процесса сервера и никуда,
кроме API самих маркетплейсов, не уходят:

  WB_API_TOKEN              токен WB: кабинет → Настройки → Доступ к API → Создать токен.
                            Категории: «Продвижение» (обязательно) и «Контент» (чтобы
                            сопоставить nmId с артикулом продавца). Тип — «только чтение».
  OZON_PERF_CLIENT_ID       Ozon Performance API: performance.ozon.ru → Настройки →
  OZON_PERF_CLIENT_SECRET   API-ключи → Создать. Это НЕ ключ Seller API.
  OZON_CLIENT_ID            (необязательно) Seller API: seller.ozon.ru → Настройки →
  OZON_API_KEY              API-ключи. Нужны, чтобы сопоставить SKU Ozon с артикулом
                            продавца. Без них артикулом остаётся числовой SKU, а дашборд
                            пробует сопоставить по названию товара.

Только чтение: ни одна функция здесь ничего не меняет в кабинетах.

Проверка из командной строки:
  python -m advisor.cabinets --from 2026-07-27 --to 2026-08-23 --csv реклама.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable

WB_ADV_API = os.environ.get("WB_ADV_API", "https://advert-api.wildberries.ru")
WB_CONTENT_API = os.environ.get("WB_CONTENT_API", "https://content-api.wildberries.ru")
OZON_PERF_API = os.environ.get("OZON_PERF_API", "https://api-performance.ozon.ru")
OZON_SELLER_API = os.environ.get("OZON_SELLER_API", "https://api-seller.ozon.ru")

WB_TYPES = {4: "Каталог", 5: "Карточка товара", 6: "Поиск", 7: "Главная страница",
            8: "Автоматическая", 9: "Аукцион"}
WB_STATUSES = {-1: "удаляется", 4: "готова к запуску", 7: "завершена", 8: "отказ",
               9: "активна", 11: "пауза"}
WB_FULLSTATS_MAX_IDS = 100     # кампаний в одном запросе fullstats
WB_FULLSTATS_MAX_DAYS = 31     # дней в интервале одного запроса
OZON_STATS_MAX_IDS = 10        # кампаний в одном отчёте Performance API
OZON_STATS_MAX_DAYS = 62       # дней в одном отчёте
HTTP_TIMEOUT = 90
WB_MIN_INTERVAL = float(os.environ.get("WB_MIN_INTERVAL", "61"))  # пауза между запросами fullstats, с


class CabinetError(RuntimeError):
    """Ошибка кабинета, понятная пользователю (какой кабинет, что не так)."""


# ---------- HTTP ----------

def _http(method: str, url: str, headers: dict[str, str] | None = None, body: Any = None,
          retries: int = 3, retry_wait: float = 61.0) -> tuple[int, Any]:
    """Запрос с разбором JSON. 429 и 5xx — подождать и повторить (WB: 1 запрос/мин)."""
    data = None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    last: tuple[int, Any] = (0, "")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            if status == 429 or status >= 500:
                wait = float(e.headers.get("Retry-After") or retry_wait)
                last = (status, _decode(raw))
                if attempt < retries:
                    time.sleep(min(wait, 120))
                    continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = (0, str(e))
            if attempt < retries:
                time.sleep(3)
                continue
            return last
        return status, _decode(raw)
    return last


def _decode(raw: bytes) -> Any:
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        return text


def _num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "").replace(" ", "").replace("%", "").replace("₽", "")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _day_ranges(d_from: str, d_to: str, max_days: int):
    a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
    if b < a:
        raise CabinetError(f"Период задан наоборот: {d_from} > {d_to}")
    while a <= b:
        end = min(b, a + timedelta(days=max_days - 1))
        yield a.isoformat(), end.isoformat()
        a = end + timedelta(days=1)


def _pick(r: dict[str, Any], *names: str) -> Any:
    """Значение первой колонки, чьё имя содержит одну из подстрок (без регистра)."""
    for k, v in r.items():
        kl = str(k).lower()
        if any(n in kl for n in names):
            return v
    return None


def _row(mp: str, cid: Any, name: str, ctype: str, day: str, sku: Any, sku_mp: Any, product_name: str,
         views: Any, clicks: Any, spend: Any, orders: Any, order_sum: Any) -> dict[str, Any]:
    """sku — артикул продавца (если сопоставлен), sku_mp — номер товара в кабинете (nmId / SKU Ozon)."""
    return {"id": str(cid), "name": name or f"Кампания {cid}", "type": ctype, "mp": mp,
            "date": str(day or "")[:10], "sku": str(sku or ""), "sku_mp": str(sku_mp or ""),
            "product_name": str(product_name or ""), "impressions": _num(views),
            "clicks": _num(clicks), "spend": round(_num(spend), 2), "orders": _num(orders),
            "order_sum": round(_num(order_sum), 2)}


# ---------- ключи ----------

def wb_token() -> str:
    return os.environ.get("WB_API_TOKEN", "").strip()


def ozon_perf_keys() -> tuple[str, str]:
    return os.environ.get("OZON_PERF_CLIENT_ID", "").strip(), os.environ.get("OZON_PERF_CLIENT_SECRET", "").strip()


def ozon_seller_keys() -> tuple[str, str]:
    return os.environ.get("OZON_CLIENT_ID", "").strip(), os.environ.get("OZON_API_KEY", "").strip()


def cabinet_status() -> dict[str, Any]:
    cid, secret = ozon_perf_keys()
    scid, skey = ozon_seller_keys()
    return {"wb": {"configured": bool(wb_token())},
            "ozon": {"configured": bool(cid and secret), "seller_keys": bool(scid and skey)}}


# ---------- Wildberries ----------

def wb_campaigns(token: str, log: Callable[[str], None] = print) -> dict[int, dict[str, Any]]:
    """Все кампании кабинета: id → {name, type, status}."""
    status, body = _http("GET", f"{WB_ADV_API}/adv/v1/promotion/count", {"Authorization": token})
    if status == 401:
        raise CabinetError("WB: токен не принят (401). Проверьте WB_API_TOKEN и категорию «Продвижение».")
    if status != 200 or not isinstance(body, dict):
        raise CabinetError(f"WB: список кампаний не получен (HTTP {status}): {str(body)[:200]}")
    camps: dict[int, dict[str, Any]] = {}
    for grp in body.get("adverts") or []:
        for a in grp.get("advert_list") or []:
            cid = int(a.get("advertId"))
            camps[cid] = {"name": "", "type": WB_TYPES.get(grp.get("type"), str(grp.get("type") or "")),
                          "status": WB_STATUSES.get(grp.get("status"), str(grp.get("status") or ""))}
    log(f"WB: кампаний в кабинете {len(camps)}")
    # Названия — отдельным запросом; если он не удался, останутся «Кампания N».
    for ids in _chunks(sorted(camps), 50):
        st, det = _http("POST", f"{WB_ADV_API}/adv/v1/promotion/adverts?order=change&direction=desc",
                        {"Authorization": token}, ids, retries=1, retry_wait=5)
        if st == 200 and isinstance(det, list):
            for d in det:
                c = camps.get(int(d.get("advertId", 0)))
                if c is not None:
                    c["name"] = d.get("name") or c["name"]
                    if d.get("type") in WB_TYPES:
                        c["type"] = WB_TYPES[d["type"]]
        else:
            log(f"WB: названия кампаний не получены (HTTP {st}); оставляю номера")
            break
    return camps


def wb_fullstats(token: str, ids: list[int], d_from: str, d_to: str,
                 log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """/adv/v2/fullstats: по дням и артикулам (nmId). До 100 кампаний и 31 дня в запросе,
    не чаще 1 запроса в минуту."""
    out: list[dict[str, Any]] = []
    first = True
    for a, b in _day_ranges(d_from, d_to, WB_FULLSTATS_MAX_DAYS):
        for chunk in _chunks(ids, WB_FULLSTATS_MAX_IDS):
            if not first:
                time.sleep(WB_MIN_INTERVAL)  # лимит WB: 1 запрос в минуту
            first = False
            payload = [{"id": i, "interval": {"begin": a, "end": b}} for i in chunk]
            st, body = _http("POST", f"{WB_ADV_API}/adv/v2/fullstats", {"Authorization": token}, payload)
            if st == 200 and isinstance(body, list):
                out += body
                log(f"WB: статистика {a}…{b}, кампаний {len(chunk)}, ответов {len(body)}")
            elif st in (200, 204, 400) and (body is None or body == "" or isinstance(body, str)):
                log(f"WB: за {a}…{b} для {len(chunk)} кампаний данных нет (HTTP {st})")
            else:
                raise CabinetError(f"WB: статистика не получена (HTTP {st}): {str(body)[:200]}")
    return out


def wb_vendor_codes(token: str, log: Callable[[str], None] = print) -> dict[str, str]:
    """Content API: nmID → артикул продавца (vendorCode). Нужна категория «Контент»."""
    result: dict[str, str] = {}
    cursor: dict[str, Any] = {"limit": 100}
    for _ in range(300):  # до 30 000 карточек
        body = {"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}}
        st, resp = _http("POST", f"{WB_CONTENT_API}/content/v2/get/cards/list", {"Authorization": token}, body,
                         retries=2, retry_wait=5)
        if st in (401, 403):
            log("WB: в токене нет категории «Контент» — артикулы останутся номерами nmId")
            return {}
        if st != 200 or not isinstance(resp, dict):
            log(f"WB: карточки не получены (HTTP {st}); артикулы останутся nmId")
            return result
        cards = resp.get("cards") or []
        for c in cards:
            if c.get("nmID") is not None and c.get("vendorCode"):
                result[str(c["nmID"])] = str(c["vendorCode"])
        cur = resp.get("cursor") or {}
        if len(cards) < cursor["limit"] or not cur.get("nmID"):
            break
        cursor = {"limit": 100, "updatedAt": cur.get("updatedAt"), "nmID": cur.get("nmID")}
    log(f"WB: сопоставлено карточек {len(result)}")
    return result


def fetch_wb_ads(d_from: str, d_to: str, log: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], list[str]]:
    token = wb_token()
    if not token:
        raise CabinetError("WB: не задан WB_API_TOKEN.")
    warnings: list[str] = []
    camps = wb_campaigns(token, log)
    if not camps:
        return [], ["WB: в кабинете нет кампаний."]
    stats = wb_fullstats(token, sorted(camps), d_from, d_to, log)
    vendor = wb_vendor_codes(token, log)
    if not vendor:
        warnings.append("WB: артикулы продавца не сопоставлены (нужна категория «Контент» в токене); в строках nmId и название товара.")
    rows: list[dict[str, Any]] = []
    no_nm = 0
    for s in stats:
        cid = s.get("advertId")
        c = camps.get(int(cid or 0), {})
        for day in s.get("days") or []:
            d = str(day.get("date") or "")[:10]
            nm_rows = [n for app in (day.get("apps") or []) for n in (app.get("nm") or [])]
            if not nm_rows:
                if _num(day.get("sum")) > 0:
                    no_nm += 1
                continue
            for n in nm_rows:
                nm = str(n.get("nmId") or "")
                rows.append(_row("wb", cid, c.get("name"), c.get("type", ""), d, vendor.get(nm, nm), nm, n.get("name"),
                                 n.get("views"), n.get("clicks"), n.get("sum"), n.get("orders"), n.get("sum_price")))
    if no_nm:
        warnings.append(f"WB: {no_nm} дневных строк с затратами без разбивки по артикулам пропущено.")
    return rows, warnings


# ---------- Ozon ----------

def ozon_token() -> str:
    cid, secret = ozon_perf_keys()
    if not (cid and secret):
        raise CabinetError("Ozon: не заданы OZON_PERF_CLIENT_ID и OZON_PERF_CLIENT_SECRET.")
    st, body = _http("POST", f"{OZON_PERF_API}/api/client/token", None,
                     {"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"}, retries=1, retry_wait=5)
    if st != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise CabinetError(f"Ozon: Performance API не выдал токен (HTTP {st}): {str(body)[:200]}. "
                           "Проверьте ключи performance.ozon.ru (не Seller API).")
    return str(body["access_token"])


def ozon_campaigns(bearer: str, log: Callable[[str], None] = print) -> dict[str, dict[str, Any]]:
    st, body = _http("GET", f"{OZON_PERF_API}/api/client/campaign", {"Authorization": f"Bearer {bearer}"})
    if st != 200 or not isinstance(body, dict):
        raise CabinetError(f"Ozon: список кампаний не получен (HTTP {st}): {str(body)[:200]}")
    camps = {str(c.get("id")): {"name": c.get("title") or "", "type": str(c.get("advObjectType") or ""),
                                "status": str(c.get("state") or "")}
             for c in (body.get("list") or []) if c.get("id") is not None}
    log(f"Ozon: кампаний в кабинете {len(camps)}")
    return camps


def ozon_report(bearer: str, ids: list[str], d_from: str, d_to: str,
                log: Callable[[str], None] = print) -> Any:
    """Отчёт по кампаниям в JSON: заказ → ожидание → скачивание. Ozon держит один отчёт за раз."""
    hdr = {"Authorization": f"Bearer {bearer}"}
    body = {"campaigns": ids, "dateFrom": d_from, "dateTo": d_to, "groupBy": "DATE"}
    st, resp = _http("POST", f"{OZON_PERF_API}/api/client/statistics/json", hdr, body, retries=4, retry_wait=15)
    if st != 200 or not isinstance(resp, dict) or not resp.get("UUID"):
        raise CabinetError(f"Ozon: отчёт не заказан (HTTP {st}): {str(resp)[:200]}")
    uuid = resp["UUID"]
    deadline = time.monotonic() + 300
    while True:
        time.sleep(2)
        st, s = _http("GET", f"{OZON_PERF_API}/api/client/statistics/{uuid}", hdr, retries=2, retry_wait=5)
        state = (s or {}).get("state") if isinstance(s, dict) else None
        if state == "OK":
            break
        if state == "ERROR":
            raise CabinetError(f"Ozon: отчёт {uuid} завершился ошибкой: {str((s or {}).get('error'))[:200]}")
        if time.monotonic() > deadline:
            raise CabinetError(f"Ozon: отчёт {uuid} не готов за 5 минут (состояние {state}).")
    st, data = _http("GET", f"{OZON_PERF_API}/api/client/statistics/report?UUID={uuid}", hdr, retries=2, retry_wait=5)
    if st != 200:
        raise CabinetError(f"Ozon: отчёт не скачан (HTTP {st}): {str(data)[:200]}")
    log(f"Ozon: отчёт {d_from}…{d_to}, кампаний {len(ids)}")
    return data


def _ozon_report_rows(data: Any, ids: list[str]) -> list[tuple[str, str, dict[str, Any]]]:
    """Разные формы ответа → (id кампании, название, строка)."""
    out = []
    if isinstance(data, dict) and "report" in data and len(ids) == 1:
        data = {ids[0]: data}
    if isinstance(data, dict):
        for cid, block in data.items():
            if not isinstance(block, dict):
                continue
            rep = block.get("report") if isinstance(block.get("report"), dict) else block
            for r in rep.get("rows") or []:
                out.append((str(cid), str(block.get("title") or ""), r))
    elif isinstance(data, list):
        for r in data:
            if isinstance(r, dict):
                out.append((str(_pick(r, "campaign", "id") or ""), "", r))
    return out


def ozon_offer_ids(skus: list[str], log: Callable[[str], None] = print) -> dict[str, str]:
    """Seller API: SKU Ozon → артикул продавца (offer_id). Без ключей — пусто."""
    cid, key = ozon_seller_keys()
    if not (cid and key) or not skus:
        return {}
    hdr = {"Client-Id": cid, "Api-Key": key}
    result: dict[str, str] = {}
    nums = [int(s) for s in skus if str(s).isdigit()]
    for chunk in _chunks(nums, 1000):
        st, body = _http("POST", f"{OZON_SELLER_API}/v3/product/info/list", hdr, {"sku": chunk}, retries=2, retry_wait=5)
        if st != 200 or not isinstance(body, dict):
            log(f"Ozon: Seller API не ответил (HTTP {st}); артикулы останутся SKU")
            return result
        items = body.get("items") or (body.get("result") or {}).get("items") or []
        for it in items:
            offer = str(it.get("offer_id") or "")
            if not offer:
                continue
            for s in [it.get("sku"), it.get("fbo_sku"), it.get("fbs_sku")] + [src.get("sku") for src in (it.get("sources") or [])]:
                if s:
                    result[str(s)] = offer
    log(f"Ozon: сопоставлено артикулов {len(result)} из {len(nums)}")
    return result


def fetch_ozon_ads(d_from: str, d_to: str, log: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], list[str]]:
    bearer = ozon_token()
    camps = ozon_campaigns(bearer, log)
    if not camps:
        return [], ["Ozon: в кабинете нет кампаний."]
    warnings: list[str] = []
    raw: list[tuple[str, str, dict[str, Any]]] = []
    for a, b in _day_ranges(d_from, d_to, OZON_STATS_MAX_DAYS):
        for ids in _chunks(sorted(camps), OZON_STATS_MAX_IDS):
            raw += _ozon_report_rows(ozon_report(bearer, ids, a, b, log), ids)
    rows: list[dict[str, Any]] = []
    no_sku = 0
    for cid, title, r in raw:
        sku = _pick(r, "sku")
        if not sku:
            no_sku += 1
            continue
        c = camps.get(cid, {})
        rows.append(_row("ozon", cid, c.get("name") or title, c.get("type", ""), _pick(r, "date", "day", "день") or "",
                         sku, sku, _pick(r, "title", "название", "name"), _pick(r, "views", "показ"), _pick(r, "clicks", "клик"),
                         _pick(r, "moneyspent", "расход", "spent", "expense"), _pick(r, "orders", "заказ"),
                         _pick(r, "ordersmoney", "выручк", "revenue")))
    if no_sku:
        warnings.append(f"Ozon: {no_sku} строк без SKU (кампании не по товарам) пропущено.")
    offers = ozon_offer_ids(sorted({r["sku_mp"] for r in rows}), log)
    if offers:
        for r in rows:
            r["sku"] = offers.get(r["sku_mp"], r["sku"])
    elif rows:
        warnings.append("Ozon: артикулы продавца не сопоставлены (нет OZON_CLIENT_ID/OZON_API_KEY); в строках SKU Ozon и название товара.")
    return rows, warnings


# ---------- общее ----------

def fetch_ads(d_from: str, d_to: str, marketplaces: list[str] | None = None,
              log: Callable[[str], None] = print) -> dict[str, Any]:
    """Строки по всем настроенным кабинетам. Возвращает rows, warnings, by_mp, errors."""
    date.fromisoformat(d_from), date.fromisoformat(d_to)
    want = [m for m in (marketplaces or ["wb", "ozon"]) if m in ("wb", "ozon")]
    status = cabinet_status()
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: dict[str, str] = {}
    by_mp: dict[str, int] = {}
    for mp in want:
        if not status[mp]["configured"]:
            continue
        try:
            got, warn = (fetch_wb_ads if mp == "wb" else fetch_ozon_ads)(d_from, d_to, log)
            got = [r for r in got if r["spend"] > 0 or r["orders"] > 0]
            rows += got
            warnings += warn
            by_mp[mp] = len(got)
        except CabinetError as e:
            errors[mp] = str(e)
    return {"rows": rows, "warnings": warnings, "errors": errors, "by_mp": by_mp, "from": d_from, "to": d_to,
            "cabinets": status}


CSV_HEADERS = ["ID кампании", "Кампания", "Тип", "Дата", "Артикул", "Артикул в кабинете", "Товар", "Показы",
               "Клики", "Затраты, ₽", "Заказы", "Сумма заказов, ₽", "Маркетплейс"]


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    """CSV, который понимает загрузчик рекламы в дашборде (разделитель «;»)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(CSV_HEADERS)
    for r in rows:
        w.writerow([r["id"], r["name"], r["type"], r["date"], r["sku"], r["sku_mp"], r["product_name"],
                    int(r["impressions"]), int(r["clicks"]), f"{r['spend']:.2f}".replace(".", ","), int(r["orders"]),
                    f"{r['order_sum']:.2f}".replace(".", ","), "Wildberries" if r["mp"] == "wb" else "Ozon"])
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Статистика кампаний из кабинетов WB/Ozon (только чтение).")
    p.add_argument("--from", dest="d_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="d_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--wb", action="store_true", help="только Wildberries")
    p.add_argument("--ozon", action="store_true", help="только Ozon")
    p.add_argument("--out", help="сохранить строки в JSON")
    p.add_argument("--csv", help="сохранить CSV для загрузки в дашборд (вкладка «Загрузка» → Рекламный кабинет)")
    a = p.parse_args(argv)
    mps = [m for m, f in (("wb", a.wb), ("ozon", a.ozon)) if f] or None
    st = cabinet_status()
    print(f"Ключи: WB {'есть' if st['wb']['configured'] else 'нет'}, Ozon Performance "
          f"{'есть' if st['ozon']['configured'] else 'нет'}, Ozon Seller {'есть' if st['ozon']['seller_keys'] else 'нет'}")
    res = fetch_ads(a.d_from, a.d_to, mps)
    for mp, n in res["by_mp"].items():
        print(f"{mp}: строк {n}, затраты {sum(r['spend'] for r in res['rows'] if r['mp'] == mp):,.0f} ₽".replace(",", " "))
    for w in res["warnings"]:
        print("Предупреждение:", w)
    for mp, e in res["errors"].items():
        print(f"Ошибка {mp}:", e)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("JSON:", a.out)
    if a.csv:
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write(rows_to_csv(res["rows"]))
        print("CSV:", a.csv)
    return 1 if res["errors"] and not res["rows"] else 0


if __name__ == "__main__":
    sys.exit(main())
