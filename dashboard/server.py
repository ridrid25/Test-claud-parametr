"""FastAPI backend for the marketplace financial dashboard.

Run with: uvicorn dashboard.server:app --port 8765

Serves the aggregated metrics as JSON to the static frontend in
dashboard/static/, plus a CSV export endpoint. One process can serve
several clients — every query is scoped by the client_id query param, so
each client only ever sees rows tagged with their own client_id.
"""
import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analytics.metrics import by_product, deductions_breakdown, funnel, monthly_dynamics, plan_vs_fact
from storage.db import init_db, set_plan_target


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Marketplace Financial Dashboard", lifespan=_lifespan)

STATIC_DIR = Path(__file__).parent / "static"


def _filters(
    client_id: str = Query(...),
    marketplace: str | None = Query(None, pattern="^(wb|ozon)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> dict:
    return {
        "client_id": client_id,
        "marketplace": marketplace,
        "date_from": date_from,
        "date_to": date_to,
    }


@app.get("/api/summary")
def api_summary(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None):
    return funnel(client_id, marketplace, date_from, date_to)


@app.get("/api/deductions")
def api_deductions(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None):
    return deductions_breakdown(client_id, marketplace, date_from, date_to)


@app.get("/api/products")
def api_products(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None, search: str | None = None):
    rows = by_product(client_id, marketplace, date_from, date_to)
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in (r["product_name"] or "").lower() or needle in (r["sku"] or "").lower()]
    return rows


@app.get("/api/dynamics")
def api_dynamics(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None):
    return monthly_dynamics(client_id, marketplace, date_from, date_to)


@app.get("/api/plan-fact")
def api_plan_fact(client_id: str, period: str, marketplace: str | None = None):
    return plan_vs_fact(client_id, period, marketplace)


class PlanTargetIn(BaseModel):
    client_id: str
    period: str  # "YYYY-MM"
    metric: str  # "net_revenue" | "payout"
    plan_value: float


@app.post("/api/plan")
def api_set_plan(target: PlanTargetIn):
    set_plan_target(target.client_id, target.period, target.metric, target.plan_value)
    return {"status": "ok"}


@app.get("/api/export/products.csv")
def export_products_csv(client_id: str, marketplace: str | None = None, date_from: str | None = None, date_to: str | None = None):
    rows = by_product(client_id, marketplace, date_from, date_to)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sku", "product_name", "realization", "returns", "return_rate", "mp_expenses", "net_revenue", "payout", "red_flags"])
    for row in rows:
        writer.writerow([
            row["sku"], row["product_name"], row["realization"], row["returns"],
            f"{row['return_rate']:.2%}", row["mp_expenses"], row["net_revenue"], row["payout"],
            "; ".join(row["red_flags"]),
        ])
    # BOM so Excel (esp. ru-RU Windows locale) reads the Cyrillic columns as
    # UTF-8 instead of guessing cp1251 and mangling them.
    buffer.seek(0)
    content = "﻿" + buffer.read()
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products.csv"},
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
