"""Wildberries Statistics API client.

Docs: https://statistics-api.wildberries.ru (personal-cabinet API key required).
Pulls the weekly financial detail report ("отчёт о реализации по неделям") —
one row per operation (sale, return, logistics, storage, penalty, ...).

Field names come from the documented Wildberries report schema. WB has
changed field names before, so if a client's data comes back with unexpected
gaps, re-check the row shape against the current WB API docs before assuming
a bug in normalize_wb.py.

DEADLINE: as of July 2026, WB has announced this exact endpoint
(GET /api/v5/supplier/reportDetailByPeriod) will be switched off on
2026-07-15, replaced by two new "Finance" category endpoints:
POST /api/finance/v1/sales-reports/list (list report IDs) and
POST /api/finance/v1/sales-reports/detailed/{reportId} (row detail per
report). Their exact request/response shape wasn't verifiable from this
environment (dev.wildberries.ru blocks automated fetches) — confirm the
new schema against a live token before the cutover and update this client
and normalize_wb.py together.
"""
import time
from typing import Iterator

import httpx

BASE_URL = "https://statistics-api.wildberries.ru"
REPORT_PATH = "/api/v5/supplier/reportDetailByPeriod"
PAGE_LIMIT = 100_000
# WB rate-limits this endpoint aggressively; back off and honor Retry-After.
MAX_RETRIES = 5


class WildberriesClient:
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
