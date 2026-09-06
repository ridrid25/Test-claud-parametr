"""Общий запуск хода merchant-agent для CLI (run_agent.py) и сервера-советника (advisor/)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Стандартные вопросы советника: кнопки в дашборде → текст для модели.
STANDARD_QUESTIONS = {
    "digest": "Produce the morning digest: what needs attention today and why. Answer in Russian.",
    "payout": "Почему изменилась выплата к прошлому периоду и что делать первым? Разложи по товарам и категориям.",
    "losers": "Какие товары убыточны с учётом себестоимости и сколько денег в них заморожено? Что делать с каждым?",
    "ads": "Какие рекламные кампании остановить, какие усилить, при том же бюджете? Учитывай маржу товаров после удержаний.",
    "stock": "Какие товары заканчиваются и сколько нужно поставить, а какие лежат без движения и что с ними делать?",
}

DRY_SCRIPT = [
    ("get_business_snapshot", {}),
    ("get_inventory_alerts", {}),
    ("get_order_issues", {}),
    ("get_campaign_performance", {}),
    ("query_metrics", {"metric": "payout", "granularity": "week"}),
]


def skills_dir(repo: str | None = None) -> Path:
    base = repo or os.environ.get("COMMERCE_AGENTS_DIR") or str(Path(__file__).resolve().parent.parent.parent / "commerce-agents")
    return Path(base) / "merchant-agent" / "skills"


def make_session(operator: str = "финансист", now: datetime | None = None):
    from merchant_agent import MerchantSessionContext, MerchantSessionState
    session = MerchantSessionContext(session_id="advisor", merchant_id="seller", operator=operator,
                                     now=now or datetime.now(timezone.utc), timezone="Europe/Moscow")
    return session, MerchantSessionState()


def api_key_present() -> bool:
    return bool(os.environ.get("PILOT_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def build_agent(backend, dry_run: bool = False, repo: str | None = None):
    from commerce_common.skills import SkillRegistry
    from merchant_agent import MerchantAgentConfig
    from merchant_agent_runtime import MerchantAgent

    config = MerchantAgentConfig(brand_name="Финсрез / МП", max_context_chars=8000)
    if dry_run:
        from commerce_common.testing import FakeClient, text_message, tool_use_message
        script = [tool_use_message(n, i) for n, i in DRY_SCRIPT]
        script.append(text_message("Сухой прогон: модель не вызывалась, инструменты отработали. "
                                   "Задайте ключ Anthropic на сервере-советнике, чтобы получить настоящий ответ."))
        client = FakeClient(script)
    else:
        from anthropic import AsyncAnthropic
        # PILOT_ANTHROPIC_KEY — отдельный ключ пилота; base_url явно, чтобы не зависеть от
        # ANTHROPIC_BASE_URL облачных сессий Claude Code.
        client = AsyncAnthropic(api_key=os.environ.get("PILOT_ANTHROPIC_KEY") or None,
                                base_url="https://api.anthropic.com", timeout=120)
    return MerchantAgent(backend=backend, skills=SkillRegistry.from_dir(skills_dir(repo)), config=config, client=client)


async def run_question(agent, text: str, operator: str = "финансист", now: datetime | None = None) -> dict[str, Any]:
    session, state = make_session(operator, now)
    messages = [{"role": "user", "content": text}]
    reply, ui, calls, errors = [], [], [], []
    async for ev in agent.stream_turn(messages, session, state):
        if ev.type == "text_delta":
            reply.append(ev.data["text"])
        elif ev.type == "tool_call":
            calls.append({"tool": ev.data["tool"], "input": ev.data.get("input", {})})
        elif ev.type == "tool_result" and ev.data.get("is_error"):
            errors.append({"tool": ev.data.get("tool"), "text": ev.data.get("summary")})
        elif ev.type == "ui":
            ui.append(ev.data)
    return {"reply": "".join(reply), "ui": ui, "tool_calls": calls, "tool_errors": errors}
