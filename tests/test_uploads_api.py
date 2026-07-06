"""End-to-end lifecycle of the CSV upload feature through the HTTP API:
upload -> list -> inspect rows -> fix an error row manually -> import ->
verify it lands in the dashboard metrics -> delete with rollback."""
import pytest
from fastapi.testclient import TestClient

import storage.db as db
from dashboard.server import app

CSV_WITH_ERROR = (
    "Дата;Артикул;Товар;Реализация;Комиссия;К выплате\n"
    "05.10.2023;SKU-A;Платье;1 000,00;100;900\n"
    "нет даты;SKU-B;Рубашка;2000;200;1800\n"
).encode("cp1251")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    with TestClient(app) as test_client:
        yield test_client


def _upload(client, content=CSV_WITH_ERROR, filename="wb_report.csv"):
    return client.post(
        "/api/uploads",
        data={"client_id": "demo", "marketplace": "wb"},
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_parses_and_reports_counts(client):
    res = _upload(client)
    assert res.status_code == 200
    body = res.json()
    assert body["rows_fixed"] == 1   # date + number format fixes
    assert body["rows_error"] == 1   # unparseable date
    assert body["status"] == "staged"


def test_upload_rejects_file_without_date_column(client):
    res = _upload(client, content="Артикул,Реализация\nSKU-1,100\n".encode())
    assert res.status_code == 422
    assert "колонка с датой" in res.json()["detail"]


def test_rows_endpoint_exposes_fixes_and_errors(client):
    upload_id = _upload(client).json()["id"]
    rows = client.get(f"/api/uploads/{upload_id}/rows").json()
    assert len(rows) == 2
    fixed_row = next(r for r in rows if r["status"] == "fixed")
    assert any("дата" in f for f in fixed_row["fixes"])
    error_row = next(r for r in rows if r["status"] == "error")
    assert "дат" in error_row["error"].lower()


def test_manual_row_fix_revalidates(client):
    upload_id = _upload(client).json()["id"]
    error_row = next(
        r for r in client.get(f"/api/uploads/{upload_id}/rows").json()
        if r["status"] == "error"
    )
    res = client.patch(
        f"/api/uploads/{upload_id}/rows/{error_row['id']}",
        json={**{k: str(v) for k, v in error_row["data"].items()
              if k in ("sku", "product_name", "realization", "commission", "payout")},
              "period_date": "2023-10-06", "realization": "2000", "payout": "1800"},
    )
    assert res.status_code == 200
    assert res.json()["status"] in ("ok", "fixed")
    assert res.json()["error"] is None


def test_import_moves_good_rows_into_dashboard(client):
    upload_id = _upload(client).json()["id"]
    res = client.post(f"/api/uploads/{upload_id}/import")
    assert res.status_code == 200
    assert res.json() == {"imported": 1, "errors_left": 1}

    summary = client.get("/api/summary", params={"client_id": "demo"}).json()
    assert summary["realization"] == 1000
    assert summary["payout"] == 900


def test_import_is_idempotent(client):
    upload_id = _upload(client).json()["id"]
    client.post(f"/api/uploads/{upload_id}/import")
    client.post(f"/api/uploads/{upload_id}/import")  # second click, same rows
    summary = client.get("/api/summary", params={"client_id": "demo"}).json()
    assert summary["realization"] == 1000  # not doubled


def test_fixing_row_after_import_updates_dashboard(client):
    upload_id = _upload(client).json()["id"]
    client.post(f"/api/uploads/{upload_id}/import")
    error_row = next(
        r for r in client.get(f"/api/uploads/{upload_id}/rows").json()
        if r["status"] == "error"
    )
    client.patch(
        f"/api/uploads/{upload_id}/rows/{error_row['id']}",
        json={"period_date": "2023-10-06", "sku": "SKU-B", "product_name": "Рубашка",
              "realization": "2000", "commission": "200", "payout": "1800"},
    )
    summary = client.get("/api/summary", params={"client_id": "demo"}).json()
    assert summary["realization"] == 3000  # both rows now counted


def test_delete_rolls_back_imported_transactions(client):
    upload_id = _upload(client).json()["id"]
    client.post(f"/api/uploads/{upload_id}/import")
    res = client.delete(f"/api/uploads/{upload_id}")
    assert res.status_code == 200
    assert res.json()["rolled_back_transactions"] == 1

    summary = client.get("/api/summary", params={"client_id": "demo"}).json()
    assert summary["realization"] == 0
    assert client.get("/api/uploads", params={"client_id": "demo"}).json() == []


def test_errors_csv_download(client):
    upload_id = _upload(client).json()["id"]
    res = client.get(f"/api/uploads/{upload_id}/errors.csv")
    assert res.status_code == 200
    text = res.content.decode("utf-8-sig")
    assert "нет даты" in text or "дат" in text
