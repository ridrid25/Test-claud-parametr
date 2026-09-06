#!/usr/bin/env python3
"""Прогон merchant-agent (anthropics/commerce-agents) на выгрузках WB/Ozon.

Режимы:
  --dry-run           штатный FakeClient репозитория вместо модели: сценарий вызовов
                      инструментов проходит через настоящий MerchantToolExecutor и наш
                      бэкенд; печатает, что именно увидела бы модель. Ключ не нужен.
  --ask "вопрос"      живой ход агента (нужен ANTHROPIC_API_KEY).
  --digest            живой утренний дайджест (нужен ключ).
  --dump              без агента: выдать выходы всех восьми чтений в JSON.

Пример:
  COMMERCE_AGENTS_DIR=/path/to/commerce-agents python3 -m agent_pilot.run_agent --period 3 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from agent_pilot.backend import MarketplaceCsvBackend  # noqa: E402

DEFAULT_REPO = os.environ.get("COMMERCE_AGENTS_DIR", str(HERE.parent.parent / "commerce-agents"))


def make_session(backend):
    from merchant_agent import MerchantSessionContext, MerchantSessionState
    session = MerchantSessionContext(session_id="pilot", merchant_id="seller-demo", operator="финансист",
                                     now=datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc), timezone="Europe/Moscow")
    return session, MerchantSessionState()


def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [dump(x) for x in obj]
    return obj


async def dump_reads(backend):
    session, _ = make_session(backend)
    out = {
        "merchant_context": await backend.get_merchant_context(session),
        "business_snapshot": dump(await backend.get_business_snapshot(session)),
        "business_snapshot_prior": dump(await backend.get_business_snapshot(session, "prior")) if backend.period > 1 else None,
        "inventory_alerts": dump(await backend.get_inventory_alerts(session)),
        "order_issues": dump(await backend.get_order_issues(session)),
        "campaigns": dump(await backend.get_campaign_performance(session)),
        "listings_loss_candidates": dump(await backend.search_listings(session, "", limit=30)),
        "metrics_payout_by_week": dump(await backend.query_metrics(session, "payout", granularity="week")),
        "metrics_sales_posuda": dump(await backend.query_metrics(session, "sales", segment="category:посуда")),
        "metrics_logistics_oz012": dump(await backend.query_metrics(session, "logistics", segment="sku:OZ-012")),
        "metrics_return_rate_wb023": dump(await backend.query_metrics(session, "return_rate", segment="sku:WB-023")),
        "pricing_WB-019": dump(await backend.get_pricing_context(session, "WB-019")),
        "pricing_OZ-013": dump(await backend.get_pricing_context(session, "OZ-013")),
        "pricing_OZ-012": dump(await backend.get_pricing_context(session, "OZ-012")),
        "listing_WB-018": dump(await backend.get_listing(session, "WB-018")),
    }
    return out


async def dry_run(backend, skills_dir: Path):
    from commerce_common.skills import SkillRegistry
    from commerce_common.testing import FakeClient, text_message, tool_use_message
    from merchant_agent import MerchantAgentConfig
    from merchant_agent_runtime import MerchantAgent

    session, state = make_session(backend)
    config = MerchantAgentConfig(brand_name="Финсрез / МП", max_context_chars=8000)
    script = [
        tool_use_message("get_business_snapshot", {}),
        tool_use_message("get_inventory_alerts", {}),
        tool_use_message("get_order_issues", {}),
        tool_use_message("get_campaign_performance", {}),
        tool_use_message("get_pending_changes", {}),
        tool_use_message("query_metrics", {"metric": "payout", "granularity": "week"}),
        tool_use_message("search_listings", {"query": "наушники"}),
        tool_use_message("get_pricing_context", {"listing_id": "WB-019"}),
        tool_use_message("stage_price_update", {"items": [{"listing_id": "WB-019", "new_price": 950}], "note": "проверка отказа"}),
        text_message("Сухой прогон завершён: инструменты отвечают, запись отклонена."),
    ]
    client = FakeClient(script)
    agent = MerchantAgent(backend=backend, skills=SkillRegistry.from_dir(skills_dir), config=config, client=client)
    messages = [{"role": "user", "content": "Как прошёл период? Что требует внимания и почему?"}]
    events = []
    async for ev in agent.stream_turn(messages, session, state):
        events.append(ev)
    # Что увидела модель: содержимое tool_result из истории сообщений.
    seen = []
    for m in messages:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for block in m["content"]:
            if block.get("type") == "tool_result":
                content = block.get("content")
                text = content if isinstance(content, str) else "".join(c.get("text", "") for c in content if isinstance(c, dict))
                seen.append({"tool_use_id": block.get("tool_use_id"), "is_error": block.get("is_error", False), "text": text})
    calls = [e.data for e in events if e.type == "tool_call"]
    results = [e.data for e in events if e.type == "tool_result"]
    system_blocks = client.calls[0].get("system") if client.calls else None
    system_text = json.dumps(system_blocks, ensure_ascii=False) if system_blocks else ""
    context_included = "loss_making_skus" in system_text and "merchant context omitted" not in system_text
    return {"model_calls": len(client.calls), "merchant_context_included": context_included,
            "tool_calls": calls, "tool_results": results,
            "tool_result_texts": seen, "system_prompt": system_blocks,
            "tools_offered": [t["name"] for t in client.calls[0].get("tools", [])] if client.calls else []}


async def live(backend, skills_dir: Path, text: str):
    from commerce_common.skills import SkillRegistry
    from merchant_agent import MerchantAgentConfig
    from merchant_agent_runtime import MerchantAgent

    session, state = make_session(backend)
    agent = MerchantAgent(backend=backend, skills=SkillRegistry.from_dir(skills_dir),
                          config=MerchantAgentConfig(brand_name="Финсрез / МП", max_context_chars=8000))
    messages = [{"role": "user", "content": text}]
    reply, ui = [], []
    async for ev in agent.stream_turn(messages, session, state):
        if ev.type == "text_delta":
            reply.append(ev.data["text"])
        elif ev.type == "tool_call":
            print(f"→ {ev.data['tool']} {json.dumps(ev.data['input'], ensure_ascii=False)}", file=sys.stderr)
        elif ev.type == "ui":
            ui.append(ev.data)
    return {"reply": "".join(reply), "ui": ui}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", type=int, default=3)
    ap.add_argument("--repo", default=DEFAULT_REPO, help="путь к клону anthropics/commerce-agents")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--ask")
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--tax-mode", default="usn_income", choices=["none", "usn_income", "usn_profit"])
    ap.add_argument("--tax-rate", type=float, default=6.0)
    ap.add_argument("--out", help="записать результат в файл (UTF-8) вместо вывода на экран")
    a = ap.parse_args()
    def emit(obj):
        text = json.dumps(obj, ensure_ascii=False, indent=2)
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"записано: {a.out}")
        else:
            print(text)
    backend = MarketplaceCsvBackend(period=a.period, tax_mode=a.tax_mode, tax_rate=a.tax_rate)
    skills_dir = Path(a.repo) / "merchant-agent" / "skills"
    if a.dump:
        emit(asyncio.run(dump_reads(backend)))
    elif a.dry_run:
        emit(asyncio.run(dry_run(backend, skills_dir)))
    elif a.ask or a.digest:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            sys.exit("Нужен ANTHROPIC_API_KEY (или ANTHROPIC_AUTH_TOKEN) в окружении.")
        text = a.ask or "Produce the morning digest: what needs attention today and why. Answer in Russian."
        emit(asyncio.run(live(backend, skills_dir, text)))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
