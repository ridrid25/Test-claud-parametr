#!/usr/bin/env python3
"""Самопроверка сервера-советника без браузера: собирает пакет в схеме дашборда из
agent_pilot/data (период 3), шлёт на /advise и сохраняет ответ.

  python advisor/selfcheck.py [--url http://127.0.0.1:8010] [--mode digest] [--out файл.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "agent_pilot" / "data"


def read(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def payload(mode: str, question: str | None) -> dict:
    rows = []
    for p in (2, 3):
        for r in read(D / f"sales_p{p}.csv"):
            rows.append({"marketplace": "wb" if r["Маркетплейс"] == "Wildberries" else "ozon", "period_date": r["Дата"],
                         "sku": r["Артикул"], "product_name": r["Товар"], "category": r["Категория"], "brand": r["Бренд"],
                         "quantity": r["Продано, шт"], "realization": r["Реализация, ₽"], "returns": r["Возвраты, ₽"],
                         "commission": r["Комиссия МП, ₽"], "logistics": r["Логистика, ₽"], "storage": r["Хранение, ₽"],
                         "promotion": r["Продвижение, ₽"], "penalty": r["Штрафы, ₽"], "other_deduction": r["Прочие удержания, ₽"],
                         "payout": r["К выплате, ₽"]})
    costs = {r["SKU"]: float(r["Полная себестоимость за шт"]) for r in read(D / "costs.csv")}
    stocks = {r["SKU"]: int(r["Остаток, шт"]) for r in read(D / "stocks_p3.csv")}
    ads_raw = [dict(r, _mp="wb") for r in read(D / "wb_ads_p3.csv")] + [dict(r, _mp="ozon") for r in read(D / "ozon_ads_p3.csv")]
    return {"mode": mode if not question else None, "question": question, "rows": rows, "costs": costs, "stocks": stocks,
            "ads_raw": ads_raw, "period": {"from": "2026-07-27", "to": "2026-08-23"},
            "settings": {"taxMode": "usn_income", "taxRate": 6, "moneyRate": 24}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--mode", default="digest")
    ap.add_argument("--question")
    ap.add_argument("--out")
    a = ap.parse_args()
    health = json.loads(urllib.request.urlopen(a.url + "/health", timeout=30).read())
    print("health:", health)
    body = json.dumps(payload(a.mode, a.question), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(a.url + "/advise", data=body, headers={"Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:500]); return 1
    print({k: d.get(k) for k in ("dry_run", "elapsed_s", "period", "prior", "sent")})
    print("tools:", [c["tool"] for c in d.get("tool_calls", [])], "errors:", d.get("tool_errors"))
    print("reply:", (d.get("reply") or "")[:400])
    for u in d.get("ui", []):
        print("ui:", u.get("component"), json.dumps(u.get("payload", {}), ensure_ascii=False)[:300])
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("записано:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
