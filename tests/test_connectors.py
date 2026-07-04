"""Verify connector pagination and rate-limit retry logic against a mocked
transport — no real WB/Ozon credentials are available in this environment,
so this is the closest thing to an integration test we can run.
"""
import json

import httpx

import connectors.wb as wb_module
import connectors.ozon as ozon_module
from connectors.ozon import OzonClient
from connectors.wb import WildberriesClient


def test_wb_paginates_via_rrd_id(monkeypatch):
    monkeypatch.setattr(wb_module, "PAGE_LIMIT", 2)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        rrdid = int(request.url.params["rrdid"])
        calls.append(rrdid)
        if rrdid == 0:
            return httpx.Response(200, json=[{"rrd_id": 1}, {"rrd_id": 2}])
        if rrdid == 2:
            return httpx.Response(200, json=[{"rrd_id": 3}])
        raise AssertionError(f"unexpected rrdid={rrdid}")

    transport = httpx.MockTransport(handler)
    client = WildberriesClient("token", transport=transport)
    rows = list(client.fetch_report_detail_by_period("2023-10-01", "2023-10-31"))

    assert [r["rrd_id"] for r in rows] == [1, 2, 3]
    assert calls == [0, 2]


def test_wb_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(wb_module, "PAGE_LIMIT", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = WildberriesClient("token", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_report_detail_by_period("2023-10-01", "2023-10-31"))
    assert rows == []


def test_wb_retries_after_429(monkeypatch):
    monkeypatch.setattr(wb_module.time, "sleep", lambda seconds: None)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[])

    client = WildberriesClient("token", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_report_detail_by_period("2023-10-01", "2023-10-31"))
    assert rows == []
    assert attempts["count"] == 2


def test_ozon_paginates_via_page_count():
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        if page == 1:
            return httpx.Response(200, json={"result": {"operations": [{"operation_id": 1}], "page_count": 2}})
        if page == 2:
            return httpx.Response(200, json={"result": {"operations": [{"operation_id": 2}], "page_count": 2}})
        raise AssertionError(f"unexpected page={page}")

    client = OzonClient("cid", "key", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_transactions("2023-10-01", "2023-10-31"))
    assert [r["operation_id"] for r in rows] == [1, 2]


def test_ozon_stops_when_no_operations():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"operations": [], "page_count": 1}})

    client = OzonClient("cid", "key", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_transactions("2023-10-01", "2023-10-31"))
    assert rows == []


def test_ozon_keeps_paginating_when_page_count_missing():
    """A response missing page_count must not be treated as the last page —
    only an empty operations list may terminate pagination in that case."""
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        if page == 1:
            return httpx.Response(200, json={"result": {"operations": [{"operation_id": 1}]}})
        if page == 2:
            return httpx.Response(200, json={"result": {"operations": [{"operation_id": 2}]}})
        if page == 3:
            return httpx.Response(200, json={"result": {"operations": []}})
        raise AssertionError(f"unexpected page={page}")

    client = OzonClient("cid", "key", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_transactions("2023-10-01", "2023-10-31"))
    assert [r["operation_id"] for r in rows] == [1, 2]


def test_ozon_retries_after_429(monkeypatch):
    monkeypatch.setattr(ozon_module.time, "sleep", lambda seconds: None)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"result": {"operations": [], "page_count": 1}})

    client = OzonClient("cid", "key", transport=httpx.MockTransport(handler))
    rows = list(client.fetch_transactions("2023-10-01", "2023-10-31"))
    assert rows == []
    assert attempts["count"] == 2
