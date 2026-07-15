"""FastAPI backend for the marketplace financial dashboard.

Run with: uvicorn dashboard.server:app --port 8765

Serves the aggregated metrics as JSON to the static frontend in
dashboard/static/, plus a CSV export endpoint. One process can serve
several clients — every query is scoped by the client_id query param, so
each client only ever sees rows tagged with their own client_id.
"""
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analytics.insights import assign_abc, compute_insights
from analytics.metrics import by_product, deductions_breakdown, funnel, monthly_dynamics, plan_vs_fact
from etl.import_csv import normalize_row, parse_cost_upload, parse_csv_upload
from storage import db as storage
from storage.db import init_db, set_plan_target, upsert_transactions


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Marketplace Financial Dashboard", lifespan=_lifespan)

STATIC_DIR = Path(__file__).parent / "static"


MarketplaceQuery = Query(None, pattern="^(wb|ozon)$")
PeriodQuery = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")


@app.get("/api/summary")
def api_summary(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None):
    return funnel(client_id, marketplace, date_from, date_to)


@app.get("/api/deductions")
def api_deductions(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None):
    return deductions_breakdown(client_id, marketplace, date_from, date_to)


@app.get("/api/products")
def api_products(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None, search: str | None = None):
    # ABC classes are assigned over the full (unsearched) assortment, so a
    # search result still shows each product's true class. When себестоимость
    # is loaded, the result/margin/ABC become net-profit-based.
    costs = storage.get_product_costs(client_id)
    rows = assign_abc(by_product(client_id, marketplace, date_from, date_to, costs))
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in (r["product_name"] or "").lower() or needle in (r["sku"] or "").lower()]
    return rows


@app.get("/api/dynamics")
def api_dynamics(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None):
    return monthly_dynamics(client_id, marketplace, date_from, date_to)


@app.get("/api/plan-fact")
def api_plan_fact(client_id: str, period: str = PeriodQuery, marketplace: str | None = MarketplaceQuery):
    return plan_vs_fact(client_id, period, marketplace)


@app.get("/api/insights")
def api_insights(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None):
    return compute_insights(client_id, marketplace, date_from, date_to, storage.get_product_costs(client_id))


class PlanTargetIn(BaseModel):
    client_id: str
    period: str  # "YYYY-MM"
    metric: Literal["net_revenue", "payout"]
    plan_value: float


@app.post("/api/plan")
def api_set_plan(target: PlanTargetIn):
    set_plan_target(target.client_id, target.period, target.metric, target.plan_value)
    return {"status": "ok"}


# --- Себестоимость (unit cost) ----------------------------------------------


@app.get("/api/costs")
def api_costs_status(client_id: str):
    meta = storage.product_costs_meta(client_id)
    return {"loaded": meta["count"] > 0, "count": meta["count"], "source_file": meta["source_file"]}


@app.post("/api/costs")
async def api_upload_costs(client_id: str = Form(...), file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 20 МБ — проверьте, что это файл себестоимости.")
    if not raw:
        raise HTTPException(422, "Файл пустой.")
    try:
        parsed = parse_cost_upload(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    # Merge into any previously loaded costs (upsert per SKU), so several files
    # — e.g. WB and Ozon separately — build up one cost table. A repeated SKU
    # takes the newest value, which also covers uploading a corrected file. Use
    # «Убрать себестоимость» to wipe and start over.
    added = storage.set_product_costs(client_id, parsed["costs"], file.filename or "costs.csv")
    total = storage.product_costs_meta(client_id)["count"]
    return {
        "loaded": True,
        "count": total,        # всего SKU с себестоимостью после слияния
        "added": added,        # сколько принёс этот файл
        "skipped": parsed["skipped"],
        "cost_column": parsed["cost_column"],
        "file_fixes": parsed["file_fixes"],
        "source_file": file.filename or "costs.csv",
    }


@app.delete("/api/costs")
def api_delete_costs(client_id: str):
    removed = storage.clear_product_costs(client_id)
    return {"removed": removed}


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralize CSV formula injection: Excel/Sheets evaluate a cell as a
    formula if it starts with =, +, -, or @ — guard it so a marketplace-
    supplied product name can't run a formula when the export is opened."""
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


@app.get("/api/export/products.csv")
def export_products_csv(client_id: str, marketplace: str | None = MarketplaceQuery, date_from: str | None = None, date_to: str | None = None):
    rows = by_product(client_id, marketplace, date_from, date_to)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sku", "product_name", "realization", "returns", "return_rate", "mp_expenses", "net_revenue", "payout", "red_flags"])
    for row in rows:
        writer.writerow([
            _csv_safe(row["sku"]), _csv_safe(row["product_name"]), row["realization"], row["returns"],
            f"{row['return_rate']:.2%}", row["mp_expenses"], row["net_revenue"], row["payout"],
            _csv_safe("; ".join(row["red_flags"])),
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


# --- CSV upload lifecycle ---------------------------------------------------

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB is far beyond any cabinet export


@app.post("/api/uploads")
async def api_create_upload(
    client_id: str = Form(...),
    marketplace: Literal["wb", "ozon"] = Form(...),
    file: UploadFile = File(...),
):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 20 МБ — выгрузки кабинетов таких размеров не бывают, проверьте файл.")
    if not raw:
        raise HTTPException(422, "Файл пустой.")

    # upload_id участвует в raw_ref строк, поэтому парсим в два прохода:
    # сначала с placeholder, после создания записи знаем настоящий id.
    try:
        parsed = parse_csv_upload(client_id, marketplace, 0, raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    upload_id = storage.create_upload(
        client_id, marketplace, file.filename or "upload.csv",
        json.dumps(parsed["file_fixes"], ensure_ascii=False),
        json.dumps(parsed["columns"], ensure_ascii=False),
        [
            {
                "row_index": r["row_index"],
                "status": r["status"],
                "fixes": json.dumps(r["fixes"], ensure_ascii=False),
                "error": r["error"],
                "data": json.dumps(r["data"], ensure_ascii=False),
                "raw": r["raw"],
            }
            for r in parsed["rows"]
        ],
    )
    # Re-stamp source_report/raw_ref with the real upload_id.
    for row in storage.get_upload_rows(upload_id):
        data = json.loads(row["data"])
        data["source_report"] = f"csv_upload:{upload_id}"
        data["raw_ref"] = f"csv:{upload_id}:{row['row_index']}"
        storage.update_upload_row(row["id"], row["status"], row["fixes"], row["error"], json.dumps(data, ensure_ascii=False))

    uploads = {u["id"]: u for u in storage.list_uploads(client_id)}
    return uploads[upload_id]


@app.get("/api/uploads")
def api_list_uploads(client_id: str):
    return storage.list_uploads(client_id)


@app.get("/api/uploads/{upload_id}/rows")
def api_upload_rows(upload_id: int, status: Literal["ok", "fixed", "error"] | None = None):
    if not storage.get_upload(upload_id):
        raise HTTPException(404, "Загрузка не найдена.")
    rows = storage.get_upload_rows(upload_id, status)
    return [
        {
            "id": r["id"],
            "row_index": r["row_index"],
            "status": r["status"],
            "fixes": json.loads(r["fixes"]),
            "error": r["error"],
            "data": json.loads(r["data"]),
            "raw": json.loads(r["raw"]),
        }
        for r in rows
    ]


class RowEditIn(BaseModel):
    period_date: str
    sku: str = ""
    product_name: str = ""
    quantity: str = "0"
    realization: str = "0"
    returns: str = "0"
    commission: str = "0"
    logistics: str = "0"
    storage: str = "0"
    promotion: str = "0"
    penalty: str = "0"
    other_deduction: str = "0"
    payout: str = "0"


@app.patch("/api/uploads/{upload_id}/rows/{row_id}")
def api_edit_upload_row(upload_id: int, row_id: int, edit: RowEditIn):
    upload = storage.get_upload(upload_id)
    row = storage.get_upload_row(row_id)
    if not upload or not row or row["upload_id"] != upload_id:
        raise HTTPException(404, "Строка не найдена.")

    # Re-run the same validation/auto-fix pipeline on the edited values, so
    # a manual fix can't sneak in data the automatic path would reject.
    result = normalize_row(
        upload["client_id"], upload["marketplace"], upload_id, row["row_index"],
        edit.model_dump(),
    )
    storage.update_upload_row(
        row_id, result["status"],
        json.dumps(result["fixes"], ensure_ascii=False),
        result["error"],
        json.dumps(result["data"], ensure_ascii=False),
    )
    # If the upload was already imported, propagate the corrected row too.
    if upload["status"] == "imported" and result["status"] in ("ok", "fixed"):
        upsert_transactions([result["data"]])
    return {
        "status": result["status"],
        "fixes": result["fixes"],
        "error": result["error"],
        "data": result["data"],
    }


@app.post("/api/uploads/{upload_id}/import")
def api_import_upload(upload_id: int):
    upload = storage.get_upload(upload_id)
    if not upload:
        raise HTTPException(404, "Загрузка не найдена.")
    importable = [
        json.loads(r["data"])
        for r in storage.get_upload_rows(upload_id)
        if r["status"] in ("ok", "fixed")
    ]
    if not importable:
        raise HTTPException(422, "Нет ни одной строки, готовой к импорту — исправьте ошибки в строках.")
    upsert_transactions(importable)
    storage.mark_upload_imported(upload_id)
    errors_left = len(storage.get_upload_rows(upload_id, "error"))
    return {"imported": len(importable), "errors_left": errors_left}


@app.delete("/api/uploads/{upload_id}")
def api_delete_upload(upload_id: int):
    if not storage.get_upload(upload_id):
        raise HTTPException(404, "Загрузка не найдена.")
    removed = storage.delete_upload(upload_id)
    return {"rolled_back_transactions": removed}


@app.get("/api/uploads/{upload_id}/errors.csv")
def api_upload_errors_csv(upload_id: int):
    if not storage.get_upload(upload_id):
        raise HTTPException(404, "Загрузка не найдена.")
    error_rows = storage.get_upload_rows(upload_id, "error")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["строка_в_файле", "ошибка", "исходные_данные"])
    for row in error_rows:
        writer.writerow([row["row_index"] + 2, _csv_safe(row["error"] or ""), _csv_safe(row["raw"])])
    buffer.seek(0)
    return StreamingResponse(
        io.StringIO("﻿" + buffer.read()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=upload_{upload_id}_errors.csv"},
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
