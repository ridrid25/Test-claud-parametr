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


def test_deductions_breakdown_filters_by_marketplace(seeded_db):
    wb_only = deductions_breakdown(seeded_db, marketplace="wb")
    assert wb_only["commission"] == 680 + 1200
    ozon_only = deductions_breakdown(seeded_db, marketplace="ozon")
    assert ozon_only["commission"] == 900


def test_by_product_filters_by_marketplace(seeded_db):
    wb_only = by_product(seeded_db, marketplace="wb")
    assert {p["sku"] for p in wb_only} == {"SKU-RED-DRESS-M", "SKU-BLUE-SHIRT-L"}
    ozon_only = by_product(seeded_db, marketplace="ozon")
    assert {p["sku"] for p in ozon_only} == {"12345", "67890"}


def test_monthly_dynamics_filters_by_marketplace(seeded_db):
    wb_only = monthly_dynamics(seeded_db, marketplace="wb")
    # WB fixture rows only fall in Oct and Nov; Ozon's Oct order shouldn't
    # leak into a WB-filtered Oct total.
    october = next(m for m in wb_only if m["month"] == "2023-10")
    assert october["realization"] == 4000  # WB-only, not 4000+6000 with Ozon mixed in


def test_plan_vs_fact_filters_by_marketplace(seeded_db):
    results = plan_vs_fact(seeded_db, "2023-10", marketplace="ozon")
    net_revenue_row = next(r for r in results if r["metric"] == "net_revenue")
    assert net_revenue_row["fact"] == 6000  # Ozon-only Oct realization, no returns that month


def test_empty_client_returns_zeroed_funnel_not_an_error(seeded_db):
    result = funnel("no-such-client")
    assert result == {"realization": 0, "returns": 0, "net_revenue": 0, "mp_expenses": 0, "payout": 0}


def test_empty_client_returns_empty_lists_not_an_error(seeded_db):
    assert by_product("no-such-client") == []
    assert monthly_dynamics("no-such-client") == []


def test_empty_client_plan_vs_fact_has_no_plan_and_zero_fact(seeded_db):
    results = plan_vs_fact("no-such-client", "2023-10")
    for row in results:
        assert row["plan"] is None
        assert row["fact"] == 0
        assert row["delta"] is None
