"""storage/db.py's upsert idempotency and per-client isolation were only
asserted by comments (README, module docstrings) — nothing failed if a
future change broke either guarantee. Both matter a lot for a financial
pipeline: idempotency is what makes it safe to re-run a sync, and isolation
is what keeps one client's numbers from ever leaking into another's."""
import json
from pathlib import Path

import pytest

import storage.db as db
from etl.normalize_ozon import normalize_ozon_rows
from etl.normalize_wb import normalize_wb_rows

FIXTURES = Path(__file__).parent.parent / "fixtures"
WB_ROWS = json.loads((FIXTURES / "wb_report_sample.json").read_text())
OZON_ROWS = json.loads((FIXTURES / "ozon_transactions_sample.json").read_text())


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()


def _row_count(client_id: str | None = None) -> int:
    with db.connect() as conn:
        if client_id is None:
            return conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        return conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE client_id = ?", (client_id,)
        ).fetchone()["n"]


def test_upsert_is_idempotent_on_identical_rows():
    rows = normalize_wb_rows("acme", WB_ROWS)
    db.upsert_transactions(rows)
    db.upsert_transactions(rows)  # re-running the same sync must not duplicate
    assert _row_count("acme") == len(WB_ROWS)


def test_upsert_updates_in_place_when_amounts_change():
    rows = normalize_wb_rows("acme", WB_ROWS)
    db.upsert_transactions(rows)

    updated_rows = [dict(r) for r in rows]
    updated_rows[0]["payout"] = 999999.0
    db.upsert_transactions(updated_rows)

    assert _row_count("acme") == len(WB_ROWS)  # still no duplicates
    with db.connect() as conn:
        payout = conn.execute(
            "SELECT payout FROM transactions WHERE client_id = ? AND raw_ref = ?",
            ("acme", updated_rows[0]["raw_ref"]),
        ).fetchone()["payout"]
    assert payout == 999999.0


def test_same_raw_ref_does_not_collide_across_clients():
    """Two different clients happening to share a raw_ref (e.g. both using
    small WB rrd_id values from independent accounts) must stay separate —
    the uniqueness key includes client_id specifically to guard this."""
    rows_a = normalize_wb_rows("client-a", WB_ROWS)
    rows_b = normalize_wb_rows("client-b", WB_ROWS)  # identical raw_ref values
    db.upsert_transactions(rows_a)
    db.upsert_transactions(rows_b)

    assert _row_count("client-a") == len(WB_ROWS)
    assert _row_count("client-b") == len(WB_ROWS)
    assert _row_count() == len(WB_ROWS) * 2


def test_client_isolation_across_both_marketplaces():
    db.upsert_transactions(normalize_wb_rows("client-a", WB_ROWS))
    db.upsert_transactions(normalize_ozon_rows("client-a", OZON_ROWS))
    db.upsert_transactions(normalize_wb_rows("client-b", WB_ROWS))

    with db.connect() as conn:
        client_a_skus = {
            r["client_id"]
            for r in conn.execute("SELECT DISTINCT client_id FROM transactions WHERE client_id = 'client-a'")
        }
        leaked = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE client_id = 'client-b' AND marketplace = 'ozon'"
        ).fetchone()["n"]
    assert client_a_skus == {"client-a"}
    assert leaked == 0  # client-b never synced Ozon data
