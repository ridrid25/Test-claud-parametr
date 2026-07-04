"""Ozon Seller API client.

Docs: https://api-seller.ozon.ru (Client-Id + Api-Key from the seller cabinet).
Pulls finance transactions ("начисления") — one row per operation (sale,
return, marketplace service/commission, logistics, ...).

As with the WB client, field names follow the documented Ozon schema at
time of writing; re-verify against a live response before trusting the
mapping in normalize_ozon.py for a new client.
"""
import time
from typing import Iterator

import httpx

BASE_URL = "https://api-seller.ozon.ru"
TRANSACTIONS_PATH = "/v3/finance/transaction/list"
PAGE_SIZE = 1000
MAX_RETRIES = 5


class OzonClient:
    def __init__(self, client_id: str, api_key: str, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Client-Id": client_id, "Api-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OzonClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_transactions(self, date_from: str, date_to: str) -> Iterator[dict]:
        """Yield raw finance transaction rows for [date_from, date_to] (ISO dates)."""
        page = 1
        while True:
            body = {
                "filter": {
                    "date": {"from": f"{date_from}T00:00:00.000Z", "to": f"{date_to}T23:59:59.000Z"},
                    "transaction_type": "all",
                },
                "page": page,
                "page_size": PAGE_SIZE,
            }
            result = self._post(body)
            operations = result.get("operations", [])
            if not operations:
                return
            yield from operations
            # Only stop early if the API actually told us the total page
            # count — defaulting to the current page here would make
            # `page >= page` true on page 1 and silently drop every
            # remaining page whenever page_count is absent from a response.
            page_count = result.get("page_count")
            if page_count is not None and page >= page_count:
                return
            page += 1

    def _post(self, body: dict) -> dict:
        for attempt in range(MAX_RETRIES):
            response = self._client.post(TRANSACTIONS_PATH, json=body)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json().get("result", {})
        raise RuntimeError(f"Ozon API rate limit exceeded after {MAX_RETRIES} retries")
