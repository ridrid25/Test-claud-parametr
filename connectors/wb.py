"""Wildberries financial detail report clients.

WB is retiring the old Statistics endpoint
(GET https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod)
on 2026-07-15 in favour of the new Finance category endpoint
(POST https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed).

Both return one row per operation (sale, return, logistics, storage, penalty,
...). The schemas differ:
  - Statistics: snake_case fields (rrd_id, sa_name, ppvz_for_pay, ...)
    → normalize_wb_row in etl/normalize_wb.py
  - Finance:    camelCase fields (rrdId, vendorCode, forPay, ...)
    → normalize_wb_finance_row in etl/normalize_wb.py

The Finance schema here was taken from Wildberries' published OpenAPI
specification (mirrored in the `wildberries-sdk` package, model
SalesReportsDetailedRes). Still worth a diff against a live token on the
first real sync — WB has renamed report fields before.

`WildberriesFinanceClient` is the forward-looking default; `WildberriesClient`
is kept for pre-cutover data / fallback.
"""
import time
from typing import Iterator

import httpx

BASE_URL = "https://statistics-api.wildberries.ru"
REPORT_PATH = "/api/v5/supplier/reportDetailByPeriod"
FINANCE_BASE_URL = "https://finance-api.wildberries.ru"
FINANCE_DETAIL_PATH = "/api/finance/v1/sales-reports/detailed"
PAGE_LIMIT = 100_000
# WB rate-limits these endpoints aggressively; back off and honor Retry-After.
MAX_RETRIES = 5


class WildberriesClient:
    """Legacy Statistics API (reportDetailByPeriod). Off from 2026-07-15."""

    def __init__(self, api_key: str, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WildberriesClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_report_detail_by_period(
        self, date_from: str, date_to: str
    ) -> Iterator[dict]:
        """Yield raw report rows for [date_from, date_to] (YYYY-MM-DD).

        Paginates via rrd_id: each page's last row's rrd_id seeds the next
        request until WB returns an empty page.
        """
        rrd_id = 0
        while True:
            page = self._get_page(date_from, date_to, rrd_id)
            if not page:
                return
            yield from page
            rrd_id = page[-1]["rrd_id"]
            if len(page) < PAGE_LIMIT:
                return

    def _get_page(self, date_from: str, date_to: str, rrd_id: int) -> list[dict]:
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "rrdid": rrd_id,
            "limit": PAGE_LIMIT,
        }
        for attempt in range(MAX_RETRIES):
            response = self._client.get(REPORT_PATH, params=params)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json() or []
        raise RuntimeError(
            f"WB API rate limit exceeded after {MAX_RETRIES} retries "
            f"(dateFrom={date_from}, dateTo={date_to}, rrdid={rrd_id})"
        )


class WildberriesFinanceClient:
    """New Finance API (sales-reports/detailed). Replaces WildberriesClient
    from 2026-07-15. Same per-operation granularity, camelCase schema."""

    def __init__(self, api_key: str, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=FINANCE_BASE_URL,
            headers={"Authorization": api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WildberriesFinanceClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_sales_reports_detailed(
        self, date_from: str, date_to: str, period: str = "weekly"
    ) -> Iterator[dict]:
        """Yield raw report rows for [date_from, date_to] (RFC3339 date/datetime,
        Moscow UTC+3).

        Paginates via rrdId: start at 0, seed each request with the previous
        page's last rrdId, and stop when WB answers 204 No Content (or an
        empty body). `period` is 'weekly' or 'daily'.
        """
        rrd_id = 0
        while True:
            page = self._get_page(date_from, date_to, rrd_id, period)
            if not page:
                return
            yield from page
            rrd_id = page[-1]["rrdId"]
            if len(page) < PAGE_LIMIT:
                return

    def _get_page(self, date_from: str, date_to: str, rrd_id: int, period: str) -> list[dict]:
        body = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "rrdId": rrd_id,
            "limit": PAGE_LIMIT,
            "period": period,
        }
        for attempt in range(MAX_RETRIES):
            response = self._client.post(FINANCE_DETAIL_PATH, json=body)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                time.sleep(retry_after)
                continue
            # 204 = no more rows for this window: the documented end-of-report signal.
            if response.status_code == 204:
                return []
            response.raise_for_status()
            return response.json() or []
        raise RuntimeError(
            f"WB Finance API rate limit exceeded after {MAX_RETRIES} retries "
            f"(dateFrom={date_from}, dateTo={date_to}, rrdId={rrd_id})"
        )
