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

# The pipeline defaults to the new WB Finance API, so its rows are camelCase.
WB_FINANCE_ROWS = [
    {"rrdId": 1, "saleDt": "2026-07-16", "vendorCode": "WB-1", "docTypeName": "Продажа",
     "retailAmount": "4000", "ppvzSalesCommission": "680", "forPay": "3110"},
    {"rrdId": 2, "saleDt": "2026-07-16", "vendorCode": "WB-2", "docTypeName": "Возврат",
     "retailAmount": "2000", "forPay": "-2000"},
]


class _FakeWBClient:
    """Legacy Statistics client (used only via --wb-api statistics)."""

    def __init__(self, api_key):
        self.api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_report_detail_by_period(self, date_from, date_to):
        return iter(WB_ROWS)


class _FakeWBFinanceClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_sales_reports_detailed(self, date_from, date_to, period="weekly"):
        return iter(WB_FINANCE_ROWS)


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
    monkeypatch.setattr(pipeline, "WildberriesFinanceClient", _FakeWBFinanceClient)
    monkeypatch.setattr(pipeline, "OzonClient", _FakeOzonClient)


def test_sync_client_pulls_both_marketplaces(monkeypatch):
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", "ozon-cid", "ozon-key"),
    )
    result = pipeline.sync_client("acme", "2023-10-01", "2023-12-31")
    assert result == {"wb_rows": len(WB_FINANCE_ROWS), "ozon_rows": len(OZON_ROWS)}

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE client_id = ?", ("acme",)
        ).fetchone()["n"]
    assert count == len(WB_FINANCE_ROWS) + len(OZON_ROWS)


def test_sync_client_statistics_flag_uses_legacy_client(monkeypatch):
    """--wb-api statistics must route to the old Statistics endpoint (snake_case
    rows) instead of the new Finance default."""
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", None, None),
    )
    result = pipeline.sync_client("acme", "2023-10-01", "2023-12-31", wb_api="statistics")
    assert result["wb_rows"] == len(WB_ROWS)  # legacy fixture, not WB_FINANCE_ROWS


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
    assert result["wb_rows"] == len(WB_FINANCE_ROWS)
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
    assert count == len(WB_FINANCE_ROWS)


def test_reconciliation_lines_show_monthly_totals_per_channel(monkeypatch):
    """После синка CLI печатает помесячные итоги для сверки с кабинетом —
    суммы должны совпадать с тем, что реально легло в базу."""
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", "ozon-cid", "ozon-key"),
    )
    pipeline.sync_client("acme", "2023-10-01", "2026-12-31")
    lines = pipeline.reconciliation_lines("acme", "2023-10-01", "2026-12-31")

    text = "\n".join(lines)
    assert "Wildberries" in text and "Ozon" in text
    # WB_FINANCE_ROWS: sale 4000 + return 2000, both 2026-07.
    wb_month = next(line for line in lines if line.startswith("2026-07"))
    assert "4 000.00" in wb_month  # реализация
    assert "2 000.00" in wb_month  # возвраты


def test_reconciliation_lines_empty_without_data(tmp_path, monkeypatch):
    db.init_db()
    assert pipeline.reconciliation_lines("ghost", "2023-01-01", "2023-12-31") == []


def test_cli_unknown_client_exits_with_readable_message(monkeypatch, capsys):
    """The CLI is run by non-developers — a missing clients.json entry must
    produce a plain instruction, not a KeyError traceback."""
    monkeypatch.setattr("sys.argv", ["etl.pipeline", "--client", "ghost", "--date-from", "2023-10-01", "--date-to", "2023-10-07"])

    def _raise(client_id):
        raise KeyError(client_id)

    monkeypatch.setattr(pipeline, "get_client", _raise)
    with pytest.raises(SystemExit) as excinfo:
        pipeline.main()
    assert "clients.json" in str(excinfo.value)
    assert "ghost" in str(excinfo.value)


def test_cli_network_failure_exits_with_readable_message(monkeypatch):
    import httpx

    monkeypatch.setattr("sys.argv", ["etl.pipeline", "--client", "acme", "--date-from", "2023-10-01", "--date-to", "2023-10-07"])
    monkeypatch.setattr(
        pipeline, "get_client",
        lambda client_id: ClientCredentials(client_id, "wb-key", None, None),
    )

    class _NetworkFailWB(_FakeWBFinanceClient):
        def fetch_sales_reports_detailed(self, date_from, date_to, period="weekly"):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(pipeline, "WildberriesFinanceClient", _NetworkFailWB)
    with pytest.raises(SystemExit) as excinfo:
        pipeline.main()
    assert "API-ключи" in str(excinfo.value)
