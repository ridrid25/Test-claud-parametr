import json
from pathlib import Path

import pytest

import storage.db as db
from analytics.metrics import by_product, deductions_breakdown, funnel, monthly_dynamics, plan_vs_fact
from etl.normalize_ozon import normalize_ozon_rows
from etl.normalize_wb import normalize_wb_rows

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()

    wb_rows = json.loads((FIXTURES / "wb_report_sample.json").read_text())
    ozon_rows = json.loads((FIXTURES / "ozon_transactions_sample.json").read_text())
    db.upsert_transactions(normalize_wb_rows("acme", wb_rows))
    db.upsert_transactions(normalize_ozon_rows("acme", ozon_rows))
    return "acme"


def test_funnel_sums_across_both_marketplaces(seeded_db):
    result = funnel(seeded_db)
    # realization: 4000 (wb sale) + 7500 (wb sale) + 6000 (ozon order) = 17500
    assert result["realization"] == 17500
    # returns: 2000 (wb) + 3000 (ozon) = 5000
    assert result["returns"] == 5000
    assert result["net_revenue"] == 12500


def test_funnel_filters_by_marketplace(seeded_db):
    wb_only = funnel(seeded_db, marketplace="wb")
    assert wb_only["realization"] == 11500
    ozon_only = funnel(seeded_db, marketplace="ozon")
    assert ozon_only["realization"] == 6000


def test_deductions_breakdown_sums_categories(seeded_db):
    result = deductions_breakdown(seeded_db)
    assert result["commission"] == 680 + 1200 + 900
    assert result["promotion"] == 100 + 200


def test_by_product_flags_high_return_rate(seeded_db):
    products = by_product(seeded_db)
    dress = next(p for p in products if p["sku"] == "SKU-RED-DRESS-M")
    # 2000 returned out of 6000 gross = 33% -> above the 30% red-zone threshold
    assert dress["return_rate"] == pytest.approx(2000 / 6000)
    assert "высокая возвратность" in dress["red_flags"]


def test_monthly_dynamics_groups_by_month(seeded_db):
    months = monthly_dynamics(seeded_db)
    month_keys = [m["month"] for m in months]
    assert month_keys == ["2023-10", "2023-11"]


def test_plan_vs_fact_computes_delta(seeded_db):
    db.set_plan_target(seeded_db, "2023-10", "net_revenue", 1000)
    results = plan_vs_fact(seeded_db, "2023-10")
    net_revenue_row = next(r for r in results if r["metric"] == "net_revenue")
    assert net_revenue_row["plan"] == 1000
    assert net_revenue_row["delta"] == pytest.approx(net_revenue_row["fact"] - 1000)
