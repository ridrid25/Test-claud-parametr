"""etl/pipeline.py orchestrates fetch -> normalize -> store; this was
previously untested even though it's the only place that wires the pieces
together (each piece is otherwise only tested in isolation)."""
import json
from pathlib import Path

import pytest

import etl.pipeline as pipeline
import storage.db as db
from config import ClientCredentials

FIXTURES = Path(__file__).parent.parent / "fixtures"
WB_ROWS = json.loads((FIXTURES / "wb_report_sample.json").read_text())
OZON_ROWS = json.loads((FIXTURES / "ozon_transactions_sample.json").read_text())


class _FakeWBClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_report_detail_by_period(self, date_from, date_to):
        return iter(WB_ROWS)


class _FakeOzonClient:
    def __init__(self, client_id, api_key):
        self.client_id = client_id
        self.api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_transactions(self, date_from, date_to):
        return iter(OZON_ROWS)


class _FailingOzonClient(_FakeOzonClient):
    def fetch_transactions(self, date_from, date_to):
        raise RuntimeError("Ozon API unreachable")


@pytest.fixture(autouse=True)
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(pipeline, "WildberriesClient", _FakeWBClient)
    monkeypatch.setattr(pipeline, "OzonClient", _FakeOzonClient)


def test_sync_client_pulls_both_marketplaces(monkeypatch):
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", "ozon-cid", "ozon-key"),
    )
    result = pipeline.sync_client("acme", "2023-10-01", "2023-12-31")
    assert result == {"wb_rows": len(WB_ROWS), "ozon_rows": len(OZON_ROWS)}

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE client_id = ?", ("acme",)
        ).fetchone()["n"]
    assert count == len(WB_ROWS) + len(OZON_ROWS)


def test_sync_client_skips_wb_without_wb_key(monkeypatch):
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, None, "ozon-cid", "ozon-key"),
    )
    result = pipeline.sync_client("acme", "2023-10-01", "2023-12-31")
    assert result["wb_rows"] == 0
    assert result["ozon_rows"] == len(OZON_ROWS)


def test_sync_client_skips_ozon_with_partial_credentials(monkeypatch):
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", "ozon-cid", None),
    )
    result = pipeline.sync_client("acme", "2023-10-01", "2023-12-31")
    assert result["wb_rows"] == len(WB_ROWS)
    assert result["ozon_rows"] == 0


def test_wb_data_survives_a_later_ozon_failure(monkeypatch):
    """sync_wb runs and commits before sync_ozon is even attempted, so an
    Ozon-side failure must not lose the WB rows already persisted."""
    monkeypatch.setattr(pipeline, "OzonClient", _FailingOzonClient)
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", "ozon-cid", "ozon-key"),
    )
    with pytest.raises(RuntimeError, match="Ozon API unreachable"):
        pipeline.sync_client("acme", "2023-10-01", "2023-12-31")

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE client_id = ? AND marketplace = 'wb'",
            ("acme",),
        ).fetchone()["n"]
    assert count == len(WB_ROWS)
