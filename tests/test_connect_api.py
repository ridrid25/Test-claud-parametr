"""«Подключение» tab: storing per-client marketplace API keys and running an
API sync from the browser. Keys are never returned to the client; the sync
endpoint aggregates both marketplaces and reports per-channel errors."""
import pytest
from fastapi.testclient import TestClient

import dashboard.server as server
import storage.db as db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()
    return TestClient(server.app)


# --- credentials ------------------------------------------------------------

def test_credentials_start_disconnected(client):
    status = client.get("/api/credentials", params={"client_id": "acme"}).json()
    assert status == {"wb_connected": False, "ozon_connected": False}


def test_save_and_status_never_leaks_keys(client):
    res = client.post("/api/credentials", json={"client_id": "acme", "wb_api_key": "secret-wb"})
    body = res.json()
    assert body["wb_connected"] is True and body["ozon_connected"] is False
    # The key must never come back over the wire.
    assert "secret-wb" not in res.text


def test_partial_save_does_not_wipe_other_marketplace(client):
    client.post("/api/credentials", json={"client_id": "acme", "wb_api_key": "wb1"})
    client.post("/api/credentials", json={
        "client_id": "acme", "ozon_client_id": "cid", "ozon_api_key": "oz1",
    })
    status = client.get("/api/credentials", params={"client_id": "acme"}).json()
    assert status == {"wb_connected": True, "ozon_connected": True}


def test_disconnect_one_marketplace(client):
    client.post("/api/credentials", json={
        "client_id": "acme", "wb_api_key": "wb1", "ozon_client_id": "cid", "ozon_api_key": "oz1",
    })
    client.delete("/api/credentials", params={"client_id": "acme", "marketplace": "wb"})
    status = client.get("/api/credentials", params={"client_id": "acme"}).json()
    assert status == {"wb_connected": False, "ozon_connected": True}


# --- sync -------------------------------------------------------------------

def test_sync_requires_saved_keys(client):
    res = client.post("/api/sync", json={"client_id": "acme", "date_from": "2026-06-01", "date_to": "2026-06-30"})
    assert res.status_code == 422


def test_sync_rejects_bad_dates(client):
    client.post("/api/credentials", json={"client_id": "acme", "wb_api_key": "wb1"})
    res = client.post("/api/sync", json={"client_id": "acme", "date_from": "01.06.2026", "date_to": "2026-06-30"})
    assert res.status_code == 422


def test_sync_aggregates_both_marketplaces(client, monkeypatch):
    client.post("/api/credentials", json={
        "client_id": "acme", "wb_api_key": "wb1", "ozon_client_id": "cid", "ozon_api_key": "oz1",
    })
    monkeypatch.setattr(server, "sync_wb", lambda *a, **k: 12)
    monkeypatch.setattr(server, "sync_ozon", lambda *a, **k: 7)
    monkeypatch.setattr(server, "reconciliation_lines", lambda *a, **k: ["— Wildberries —"])

    body = client.post("/api/sync", json={
        "client_id": "acme", "date_from": "2026-06-01", "date_to": "2026-06-30",
    }).json()
    assert body["wb"] == 12 and body["ozon"] == 7
    assert body["errors"] == {}
    assert body["reconciliation"] == ["— Wildberries —"]


def test_sync_reports_one_channel_error_without_failing_the_other(client, monkeypatch):
    import httpx

    client.post("/api/credentials", json={
        "client_id": "acme", "wb_api_key": "wb1", "ozon_client_id": "cid", "ozon_api_key": "oz1",
    })

    def _wb_401(*a, **k):
        raise httpx.HTTPStatusError(
            "unauthorized", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(server, "sync_wb", _wb_401)
    monkeypatch.setattr(server, "sync_ozon", lambda *a, **k: 5)
    monkeypatch.setattr(server, "reconciliation_lines", lambda *a, **k: [])

    body = client.post("/api/sync", json={
        "client_id": "acme", "date_from": "2026-06-01", "date_to": "2026-06-30",
    }).json()
    assert body["ozon"] == 5           # Ozon still ran
    assert body["wb"] is None
    assert "отклонён" in body["errors"]["wb"]  # friendly 401 message
