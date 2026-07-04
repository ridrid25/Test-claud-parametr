"""dashboard/server.py's HTTP routes were previously untested — only the
underlying analytics.metrics functions were. This covers behavior that
lives in the route layer itself: query-param validation, the products
search filter, and the CSV export's encoding/injection guard.

Note: FastAPI's TestClient (via starlette.testclient) currently emits a
StarletteDeprecationWarning nudging towards an `httpx2` package in place
of `httpx` — harmless for now (TestClient still works correctly against
the pinned httpx version), and not worth chasing here since connectors/
wb.py and connectors/ozon.py both depend on httpx directly for their real
HTTP client behavior.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import storage.db as db
from dashboard.server import app
from etl.normalize_ozon import normalize_ozon_rows
from etl.normalize_wb import normalize_wb_rows

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    with TestClient(app) as test_client:
        wb_rows = json.loads((FIXTURES / "wb_report_sample.json").read_text())
        ozon_rows = json.loads((FIXTURES / "ozon_transactions_sample.json").read_text())
        db.upsert_transactions(normalize_wb_rows("demo", wb_rows))
        db.upsert_transactions(normalize_ozon_rows("demo", ozon_rows))
        yield test_client


def test_summary_endpoint_returns_funnel(client):
    res = client.get("/api/summary", params={"client_id": "demo"})
    assert res.status_code == 200
    assert res.json()["realization"] == 17500


def test_products_search_filters_by_name(client):
    res = client.get("/api/products", params={"client_id": "demo", "search": "кроссов"})
    assert res.status_code == 200
    assert {row["sku"] for row in res.json()} == {"12345"}


def test_products_search_filters_by_sku(client):
    res = client.get("/api/products", params={"client_id": "demo", "search": "SKU-BLUE"})
    assert {row["sku"] for row in res.json()} == {"SKU-BLUE-SHIRT-L"}


def test_marketplace_pattern_rejects_garbage(client):
    res = client.get("/api/summary", params={"client_id": "demo", "marketplace": "bogus"})
    assert res.status_code == 422


def test_period_pattern_rejects_malformed_value(client):
    res = client.get("/api/plan-fact", params={"client_id": "demo", "period": "abc"})
    assert res.status_code == 422


def test_plan_endpoint_rejects_invalid_metric(client):
    res = client.post(
        "/api/plan",
        json={"client_id": "demo", "period": "2023-10", "metric": "bogus", "plan_value": 100},
    )
    assert res.status_code == 422


def test_plan_endpoint_roundtrips_a_valid_metric(client):
    res = client.post(
        "/api/plan",
        json={"client_id": "demo", "period": "2023-10", "metric": "net_revenue", "plan_value": 1000},
    )
    assert res.status_code == 200

    plan_fact = client.get("/api/plan-fact", params={"client_id": "demo", "period": "2023-10"}).json()
    row = next(r for r in plan_fact if r["metric"] == "net_revenue")
    assert row["plan"] == 1000


def test_export_csv_has_bom_and_formula_guard(client, monkeypatch):
    monkeypatch.setattr(
        "dashboard.server.by_product",
        lambda *a, **k: [{
            "sku": "=cmd", "product_name": "+HYPERLINK(1)", "realization": 0, "returns": 0,
            "mp_expenses": 0, "net_revenue": 0, "payout": 0, "return_rate": 0, "red_flags": [],
        }],
    )
    res = client.get("/api/export/products.csv", params={"client_id": "demo"})
    assert res.status_code == 200
    assert res.content.startswith("﻿".encode("utf-8"))
    text = res.content.decode("utf-8-sig")
    assert "'=cmd" in text
    assert "'+HYPERLINK(1)" in text
