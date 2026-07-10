"""Fetch -> normalize -> store for one client, both marketplaces.

Run as a scheduled job (cron) per client to keep the dashboard fresh, or
invoke directly for a one-off backfill:

    python -m etl.pipeline --client acme --date-from 2023-10-01 --date-to 2023-12-31
"""
import argparse

import httpx

from analytics.metrics import monthly_dynamics
from config import get_client
from connectors.ozon import OzonClient
from connectors.wb import WildberriesClient, WildberriesFinanceClient
from etl.normalize_ozon import normalize_ozon_rows
from etl.normalize_wb import normalize_wb_finance_rows, normalize_wb_rows
from storage.db import init_db, upsert_transactions


def sync_wb(client_id: str, wb_api_key: str, date_from: str, date_to: str, wb_api: str = "finance") -> int:
    """Pull WB financial detail. Defaults to the new Finance API
    (finance-api.wildberries.ru); pass wb_api='statistics' for the legacy
    endpoint, which WB switches off on 2026-07-15."""
    if wb_api == "statistics":
        with WildberriesClient(wb_api_key) as client:
            raw_rows = list(client.fetch_report_detail_by_period(date_from, date_to))
        return upsert_transactions(normalize_wb_rows(client_id, raw_rows))
    with WildberriesFinanceClient(wb_api_key) as client:
        raw_rows = list(client.fetch_sales_reports_detailed(date_from, date_to))
    return upsert_transactions(normalize_wb_finance_rows(client_id, raw_rows))


def sync_ozon(
    client_id: str, ozon_client_id: str, ozon_api_key: str, date_from: str, date_to: str
) -> int:
    with OzonClient(ozon_client_id, ozon_api_key) as client:
        raw_rows = list(client.fetch_transactions(date_from, date_to))
    return upsert_transactions(normalize_ozon_rows(client_id, raw_rows))


def sync_client(client_id: str, date_from: str, date_to: str, wb_api: str = "finance") -> dict:
    """Pull both marketplaces for one client; skip a marketplace with no credentials."""
    creds = get_client(client_id)
    init_db()
    result = {"wb_rows": 0, "ozon_rows": 0}
    if creds.wb_api_key:
        result["wb_rows"] = sync_wb(client_id, creds.wb_api_key, date_from, date_to, wb_api)
    if creds.ozon_client_id and creds.ozon_api_key:
        result["ozon_rows"] = sync_ozon(
            client_id, creds.ozon_client_id, creds.ozon_api_key, date_from, date_to
        )
    return result


def reconciliation_lines(client_id: str, date_from: str, date_to: str) -> list[str]:
    """Помесячные итоги по каждому каналу для сверки с кабинетом ВБ/Ozon.

    Печатается сразу после синка: «Реализация» и «К выплате» должны сойтись
    с отчётом реализации в кабинете за тот же месяц. Если не сходятся —
    маппинг полей в etl/normalize_*.py надо сверить с сырым ответом API.
    """
    names = {"wb": "Wildberries", "ozon": "Ozon"}
    lines = []
    for marketplace, name in names.items():
        months = monthly_dynamics(client_id, marketplace, date_from, date_to)
        if not months:
            continue
        lines.append(f"— {name}: сверьте с кабинетом —")
        lines.append(f"{'месяц':<9} {'реализация':>14} {'возвраты':>12} {'расходы МП':>12} {'к выплате':>14}")
        for m in months:
            lines.append(
                f"{m['month']:<9} {m['realization']:>14,.2f} {m['returns']:>12,.2f} "
                f"{m['mp_expenses']:>12,.2f} {m['payout']:>14,.2f}".replace(",", " ")
            )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, help="client_id from clients.json")
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--wb-api", choices=("finance", "statistics"), default="finance",
        help="WB endpoint: 'finance' (new, default) or 'statistics' (legacy, off 2026-07-15)",
    )
    args = parser.parse_args()

    # The two most common first-run failures (no clients.json entry, API
    # unreachable / key rejected) get a readable message instead of a raw
    # traceback — the CLI is run by non-developers following the README.
    try:
        result = sync_client(args.client, args.date_from, args.date_to, args.wb_api)
    except KeyError:
        raise SystemExit(
            f"Клиент {args.client!r} не найден в clients.json.\n"
            "Скопируйте clients.example.json в clients.json и впишите ключи клиента "
            "(см. раздел 'Онбординг клиента' в README.md)."
        )
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"Не удалось получить данные из API маркетплейса: {exc}\n"
            "Проверьте, что API-ключи в clients.json действительны и есть доступ в интернет."
        )
    print(f"WB rows synced: {result['wb_rows']}")
    print(f"Ozon rows synced: {result['ozon_rows']}")
    for line in reconciliation_lines(args.client, args.date_from, args.date_to):
        print(line)


if __name__ == "__main__":
    main()
