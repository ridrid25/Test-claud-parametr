"""Себестоимость (unit-cost) pipeline: cost-file parsing, cost-aware
by_product/insights (net profit instead of payout), and the /api/costs
endpoints that store and clear a client's costs."""
import pytest
from fastapi.testclient import TestClient

import storage.db as db
from analytics.insights import compute_insights
from analytics.metrics import by_product
from etl.import_csv import parse_cost_upload


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()

    def row(**kwargs):
        base = {
            "client_id": "acme", "marketplace": "wb", "period_date": "2023-10-05",
            "sku": "SKU", "product_name": "Товар", "category": "", "brand": "",
            "quantity": 1, "realization": 0.0, "returns": 0.0, "commission": 0.0,
            "logistics": 0.0, "storage": 0.0, "promotion": 0.0, "penalty": 0.0,
            "other_deduction": 0.0, "payout": 0.0, "source_report": "test",
            "raw_ref": kwargs.pop("ref"),
        }
        return {**base, **kwargs}

    db.upsert_transactions([
        # 10 units sold, к выплате 8500 — cost 600/шт → COGS 6000 → profit 2500
        row(ref="1", sku="A", category="Одежда/Худи", brand="Nike", quantity=10,
            realization=10000, commission=1000, logistics=500, payout=8500),
        # 5 units, к выплате 800 — cost 300/шт → COGS 1500 → profit −700 (loss under costs)
        row(ref="2", marketplace="ozon", sku="B", category="Посуда/Кружки", brand="IKEA",
            quantity=5, realization=2000, returns=500, commission=300, logistics=400, payout=800),
    ])
    return db


# --- parse_cost_upload ------------------------------------------------------

def test_parse_cost_basic():
    raw = "SKU;Полная себестоимость за шт\nA;600\nB;300\n".encode("utf-8")
    result = parse_cost_upload(raw)
    assert result["costs"] == {"A": 600.0, "B": 300.0}
    assert result["skipped"] == 0


def test_parse_cost_ru_numbers_and_cp1251():
    # cp1251, ';' delimiter, "1 200,50 ₽"-style numbers, bare "Себестоимость".
    raw = "Артикул;Себестоимость\nA;1 200,50\nB;300 руб\n".encode("cp1251")
    result = parse_cost_upload(raw)
    assert result["costs"] == {"A": 1200.5, "B": 300.0}
    assert "кодировка cp1251 → UTF-8" in result["file_fixes"]


def test_parse_cost_skips_bad_rows():
    raw = "SKU;Себестоимость\nA;600\n;500\nC;0\nD;abc\n".encode("utf-8")
    result = parse_cost_upload(raw)
    assert result["costs"] == {"A": 600.0}
    assert result["skipped"] == 3  # blank sku, zero cost, non-numeric


def test_parse_cost_missing_column_raises():
    with pytest.raises(ValueError, match="себестоимости"):
        parse_cost_upload("SKU;Цена\nA;600\n".encode("utf-8"))
    with pytest.raises(ValueError, match="артикул"):
        parse_cost_upload("Название;Себестоимость\nX;600\n".encode("utf-8"))


# --- cost-aware analytics ---------------------------------------------------

def test_by_product_profit_with_costs(seeded_db):
    rows = {p["sku"]: p for p in by_product("acme", costs={"A": 600, "B": 300})}
    assert rows["A"]["cogs"] == 6000
    assert rows["A"]["profit"] == 2500
    assert rows["A"]["result"] == 2500  # result switches to profit
    assert rows["B"]["profit"] == -700
    assert "убыток с уч. себестоимости" in rows["B"]["red_flags"]


def test_by_product_without_costs_uses_payout(seeded_db):
    rows = {p["sku"]: p for p in by_product("acme")}
    assert rows["A"]["result"] == rows["A"]["payout"] == 8500
    assert rows["A"]["unit_cost"] is None


def test_insights_profit_totals(seeded_db):
    ins = compute_insights("acme", costs={"A": 600, "B": 300})
    assert ins["costs_loaded"] is True
    assert ins["cogs_total"] == 7500
    assert ins["profit_total"] == 8500 + 800 - 7500  # payout total − COGS
    assert ins["cost_coverage"] == 1.0
    # B is now a loss-maker under costs even though its payout was positive.
    assert any(p["sku"] == "B" for p in ins["losers"])


def test_insights_partial_cost_coverage(seeded_db):
    ins = compute_insights("acme", costs={"A": 600})
    assert ins["cost_coverage"] == 0.5


# --- /api/costs endpoints ---------------------------------------------------

@pytest.fixture
def client(seeded_db):
    # seeded_db already patched db.DB_PATH (the same module the server uses)
    # and initialized/seeded the schema, so a plain TestClient is enough.
    from dashboard.server import app
    return TestClient(app)


def test_costs_endpoints_roundtrip(client):
    assert client.get("/api/costs", params={"client_id": "acme"}).json()["loaded"] is False

    files = {"file": ("costs.csv", "SKU;Себестоимость\nA;600\nB;300\n", "text/csv")}
    res = client.post("/api/costs", params={"client_id": "acme"}, data={"client_id": "acme"}, files=files)
    assert res.status_code == 200
    assert res.json()["count"] == 2

    status = client.get("/api/costs", params={"client_id": "acme"}).json()
    assert status["loaded"] is True and status["count"] == 2

    # Products now expose profit-based result.
    products = {p["sku"]: p for p in client.get("/api/products", params={"client_id": "acme"}).json()}
    assert products["A"]["profit"] == 2500
    assert products["B"]["unit_cost"] == 300

    assert client.delete("/api/costs", params={"client_id": "acme"}).json()["removed"] == 2
    assert client.get("/api/costs", params={"client_id": "acme"}).json()["loaded"] is False


def test_costs_multiple_files_merge(client):
    """Several cost files build up one table (e.g. WB then Ozon); a repeated
    SKU takes the newest value, so a correction file still works."""
    def upload(body):
        return client.post("/api/costs", params={"client_id": "acme"},
                           data={"client_id": "acme"},
                           files={"file": ("c.csv", body, "text/csv")}).json()

    first = upload("SKU;Себестоимость\nA;600\nB;300\n")
    assert first["added"] == 2 and first["count"] == 2

    # A second file adds a new SKU and corrects an existing one.
    second = upload("SKU;Себестоимость\nA;700\nC;900\n")
    assert second["added"] == 2      # A (updated) + C (new)
    assert second["count"] == 3      # A, B, C — B kept, not wiped

    costs = client.get("/api/products", params={"client_id": "acme"}).json()
    by_sku = {p["sku"]: p for p in costs}
    assert by_sku["A"]["unit_cost"] == 700  # newest value wins
    assert by_sku["B"]["unit_cost"] == 300  # earlier file preserved
