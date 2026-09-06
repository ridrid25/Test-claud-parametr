"""Сервер-советник: принимает агрегаты из дашборда, прогоняет merchant-agent, отвечает.

Ничего не хранит: бэкенд строится в памяти на время одного запроса. Сырые файлы
кабинетов на сервер не приходят — только нормализованные строки отчёта (те же, что
считает дашборд), себестоимость, остатки, рекламные строки и настройки налога.

Запуск:  python -m advisor.server            (порт 8010; ADVISOR_PORT — изменить)
Ключ:    PILOT_ANTHROPIC_KEY или ANTHROPIC_API_KEY в окружении процесса.
Скиллы:  COMMERCE_AGENTS_DIR — путь к клону anthropics/commerce-agents.
Кабинеты: WB_API_TOKEN, OZON_PERF_CLIENT_ID/OZON_PERF_CLIENT_SECRET (см. advisor/cabinets.py) —
         тогда «Подтянуть из кабинетов» в дашборде забирает статистику кампаний без файлов.
Без ключа сервер отвечает сухим прогоном (инструменты работают, текста модели нет).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_pilot.backend import MarketplaceBackend, parse_ads_rows  # noqa: E402
from agent_pilot.runner import STANDARD_QUESTIONS, api_key_present, build_agent, run_question, skills_dir  # noqa: E402
from advisor.cabinets import CabinetError, cabinet_status, fetch_ads  # noqa: E402

app = FastAPI(title="Финсрез / МП — советник", version="1.2")
# Сайт открыт по HTTPS с github.io, а сервер — локальный (127.0.0.1). Chrome считает
# это обращением из публичной сети в приватную и на preflight требует
# Access-Control-Allow-Private-Network: true; Starlette 1.x без allow_private_network
# отвечает «Disallowed CORS private-network», и вкладка «Советник» не работает.
_cors = {"allow_origins": ["*"], "allow_methods": ["*"], "allow_headers": ["*"]}
try:
    app.add_middleware(CORSMiddleware, **_cors, allow_private_network=True)
except TypeError:  # Starlette старше 1.0: параметра нет, заголовок добавим сами
    app.add_middleware(CORSMiddleware, **_cors)

    @app.middleware("http")
    async def _private_network(request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

MAX_ROWS = 50_000


class AdviseRequest(BaseModel):
    mode: str | None = Field(default=None, description="digest | payout | losers | ads | stock")
    question: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    costs: dict[str, float] = Field(default_factory=dict)
    stocks: dict[str, int] = Field(default_factory=dict)
    ads: list[dict[str, Any]] = Field(default_factory=list)
    ads_raw: list[dict[str, Any]] = Field(default_factory=list, description="сырые строки рекламной выгрузки с полем _mp")
    period: dict[str, str | None] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    operator: str = "финансист"
    dry_run: bool = False


class CabinetsRequest(BaseModel):
    date_from: str = Field(alias="from")
    date_to: str = Field(alias="to")
    marketplaces: list[str] = Field(default_factory=lambda: ["wb", "ozon"])
    model_config = {"populate_by_name": True}


@app.get("/health")
def health() -> dict[str, Any]:
    sd = skills_dir()
    return {"ok": True, "key_present": api_key_present(), "skills_dir": str(sd), "skills_found": sd.exists(),
            "questions": list(STANDARD_QUESTIONS), "cabinets": cabinet_status(), "version": app.version}


@app.post("/cabinets/ads")
def cabinets_ads(req: CabinetsRequest) -> dict[str, Any]:
    """Статистика кампаний из рекламных кабинетов по ключам на сервере. Только чтение.
    Долгий запрос: WB отдаёт статистику не чаще раза в минуту, Ozon строит отчёт до минуты."""
    st = cabinet_status()
    if not any(st[m]["configured"] for m in ("wb", "ozon") if m in req.marketplaces):
        raise HTTPException(400, "На сервере нет ключей кабинетов: задайте WB_API_TOKEN и/или "
                                 "OZON_PERF_CLIENT_ID + OZON_PERF_CLIENT_SECRET (см. advisor/README.md).")
    started = time.monotonic()
    try:
        res = fetch_ads(req.date_from, req.date_to, req.marketplaces, log=lambda m: print("кабинеты:", m))
    except (CabinetError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    res["elapsed_s"] = round(time.monotonic() - started, 1)
    return res


@app.post("/advise")
async def advise(req: AdviseRequest) -> dict[str, Any]:
    if not req.rows:
        raise HTTPException(400, "Нет строк отчёта: загрузите отчёт о реализации в дашборд.")
    if len(req.rows) > MAX_ROWS:
        raise HTTPException(413, f"Слишком много строк ({len(req.rows)}); сузьте период фильтром.")
    text = req.question or STANDARD_QUESTIONS.get(req.mode or "", "")
    if not text:
        raise HTTPException(400, "Нужен question или mode из списка: " + ", ".join(STANDARD_QUESTIONS))
    ads = list(req.ads)
    if req.ads_raw:
        for mp in ("wb", "ozon"):
            ads += parse_ads_rows([r for r in req.ads_raw if r.get("_mp") == mp], mp)
    payload = req.model_dump()
    payload["ads"] = ads
    try:
        backend = MarketplaceBackend.from_payload(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось собрать данные: {e}") from e
    dry = req.dry_run or not api_key_present()
    if not skills_dir().exists():
        raise HTTPException(500, f"Не найдены скиллы merchant-agent: {skills_dir()}. Задайте COMMERCE_AGENTS_DIR.")
    started = time.monotonic()
    try:
        agent = build_agent(backend, dry_run=dry)
        result = await run_question(agent, text, operator=req.operator)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Ошибка агента: {type(e).__name__}: {str(e)[:300]}") from e
    result.update({
        "dry_run": dry, "elapsed_s": round(time.monotonic() - started, 1),
        "period": {"from": backend.cur[0], "to": backend.cur[1]},
        "prior": {"from": backend.prev[0], "to": backend.prev[1]} if backend.prev else None,
        "sent": {"rows": len(req.rows), "costs": len(req.costs), "stocks": len(req.stocks), "ads": len(ads)},
    })
    return result


def main() -> None:
    import uvicorn
    port = int(os.environ.get("ADVISOR_PORT", "8010"))
    print(f"Советник: http://127.0.0.1:{port}  ключ: {'есть' if api_key_present() else 'НЕТ (сухой прогон)'}  скиллы: {skills_dir()}")
    uvicorn.run(app, host=os.environ.get("ADVISOR_HOST", "127.0.0.1"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
