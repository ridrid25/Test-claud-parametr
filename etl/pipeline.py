"""Fetch -> normalize -> store for one client, both marketplaces.

Run as a scheduled job (cron) per client to keep the dashboard fresh, or
invoke directly for a one-off backfill:

    python -m etl.pipeline --client acme --date-from 2023-10-01 --date-to 2023-12-31
"""
import argparse

from config import get_client
from connectors.ozon import OzonClient
from connectors.wb import WildberriesClient
from etl.normalize_ozon import normalize_ozon_rows
from etl.normalize_wb import normalize_wb_rows
from storage.db import init_db, upsert_transactions


def sync_wb(client_id: str, wb_api_key: str, date_from: str, date_to: str) -> int:
    with WildberriesClient(wb_api_key) as client:
        raw_rows = list(client.fetch_report_detail_by_period(date_from, date_to))
    return upsert_transactions(normalize_wb_rows(client_id, raw_rows))


def sync_ozon(
    client_id: str, ozon_client_id: str, ozon_api_key: str, date_from: str, date_to: str
) -> int:
    with OzonClient(ozon_client_id, ozon_api_key) as client:
        raw_rows = list(client.fetch_transactions(date_from, date_to))
    return upsert_transactions(normalize_ozon_rows(client_id, raw_rows))


def sync_client(client_id: str, date_from: str, date_to: str) -> dict:
    """Pull both marketplaces for one client; skip a marketplace with no credentials."""
    creds = get_client(client_id)
    init_db()
    result = {"wb_rows": 0, "ozon_rows": 0}
    if creds.wb_api_key:
        result["wb_rows"] = sync_wb(client_id, creds.wb_api_key, date_from, date_to)
    if creds.ozon_client_id and creds.ozon_api_key:
        result["ozon_rows"] = sync_ozon(
            client_id, creds.ozon_client_id, creds.ozon_api_key, date_from, date_to
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, help="client_id from clients.json")
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    result = sync_client(args.client, args.date_from, args.date_to)
    print(f"WB rows synced: {result['wb_rows']}")
    print(f"Ozon rows synced: {result['ozon_rows']}")


if __name__ == "__main__":
    main()
