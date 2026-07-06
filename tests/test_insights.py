"""analytics/insights.py turns raw aggregates into the analysis the
dashboard's «Анализ» tab shows: loss-makers, dead stock, ABC classes,
channel comparison, promo share, concentration, MoM dynamics."""
import pytest

import storage.db as db
from analytics.insights import assign_abc, compute_insights


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()

    def row(**kwargs):
        base = {
            "client_id": "acme", "marketplace": "wb", "period_date": "2023-10-05",
            "sku": "SKU", "product_name": "Товар", "quantity": 1,
            "realization": 0.0, "returns": 0.0, "commission": 0.0, "logistics": 0.0,
            "storage": 0.0, "promotion": 0.0, "penalty": 0.0, "other_deduction": 0.0,
            "payout": 0.0, "source_report": "test", "raw_ref": kwargs.pop("ref"),
        }
        return {**base, **kwargs}

    db.upsert_transactions([
        # hero product: big positive payout (class A)
        row(ref="1", sku="HERO", realization=100000, commission=10000, payout=85000),
        # solid product (class B territory)
        row(ref="2", sku="GOOD", realization=20000, commission=2000, payout=15000),
        # small product (class C tail)
        row(ref="3", sku="SMALL", realization=2000, commission=200, payout=1500),
        # loss-maker: expenses above payout
        row(ref="4", sku="LOSER", realization=1000, commission=300, logistics=900, payout=-200),
        # dead stock: no sales, storage cost only
        row(ref="5", sku="DEAD", storage=500, payout=-500),
        # ozon row for channel comparison + promo for ДРР
        row(ref="6", marketplace="ozon", sku="OZ", realization=50000, promotion=9000, commission=5000, payout=30000),
        # November rows for MoM
        row(ref="7", period_date="2023-11-05", sku="HERO", realization=50000, payout=40000),
    ])
    return "acme"


def test_losers_and_loss_sum(seeded_db):
    result = compute_insights(seeded_db)
    losers = {p["sku"] for p in result["losers"]}
    assert "LOSER" in losers and "DEAD" in losers
    assert result["loss_sum"] == pytest.approx(-700)
    assert result["losers_count"] == 2


def test_dead_stock_detected_separately(seeded_db):
    result = compute_insights(seeded_db)
    assert result["dead_stock_count"] == 1
    assert result["dead_stock_cost"] == 500


def test_abc_classes(seeded_db):
    result = compute_insights(seeded_db)
    abc = result["abc"]
    assert abc["A"]["count"] >= 1          # HERO carries most of the payout
    assert abc["L"]["count"] == 2          # both negative-payout SKUs
    assert abc["L"]["payout"] == pytest.approx(-700)
    total = sum(cls["count"] for cls in abc.values())
    assert total == 6                       # every SKU classified exactly once


def test_channels_compare_wb_and_ozon(seeded_db):
    result = compute_insights(seeded_db)
    assert set(result["channels"]) == {"wb", "ozon"}
    assert result["channels"]["ozon"]["realization"] == 50000
    # channel breakdown must include deduction categories for unit economics
    assert result["channels"]["ozon"]["promotion"] == 9000


def test_channels_empty_when_marketplace_filter_active(seeded_db):
    result = compute_insights(seeded_db, marketplace="wb")
    assert result["channels"] == {}


def test_drr_and_expense_share(seeded_db):
    result = compute_insights(seeded_db)
    realization = result["totals"]["realization"]
    assert result["drr"] == pytest.approx(9000 / realization)
    assert 0 < result["expense_share"] < 1


def test_mom_dynamics(seeded_db):
    result = compute_insights(seeded_db)
    assert result["mom"]["prev_month"] == "2023-10"
    assert result["mom"]["last_month"] == "2023-11"


def test_assign_abc_margin_field():
    products = [
        {"payout": 80.0, "realization": 100.0, "returns": 0, "mp_expenses": 20},
        {"payout": -5.0, "realization": 0.0, "returns": 0, "mp_expenses": 5},
    ]
    assign_abc(products)
    assert products[0]["margin"] == pytest.approx(0.8)
    assert products[1]["margin"] == -1.0
    assert products[1]["abc"] == "L"
