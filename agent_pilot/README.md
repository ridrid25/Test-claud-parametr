# agent_pilot — merchant-agent на выгрузках WB/Ozon (только чтение)

Пилот интерфейса `MerchantBackend` из [anthropics/commerce-agents](https://github.com/anthropics/commerce-agents)
поверх данных, которые уже есть у продавца: отчёт о реализации, себестоимость,
остатки, выгрузки рекламных кабинетов. Подробности и результаты — `../ОТЧЁТ_ПИЛОТ_ТОРГАГЕНТА.md`.

```bash
python3 agent_pilot/generate_periods.py            # перегенерировать data/ (детерминированно)
export COMMERCE_AGENTS_DIR=/path/commerce-agents    # клон репозитория с установленным .venv
$COMMERCE_AGENTS_DIR/.venv/bin/python -m agent_pilot.run_agent --period 3 --dump      # выходы 8 чтений
$COMMERCE_AGENTS_DIR/.venv/bin/python -m agent_pilot.run_agent --period 3 --dry-run   # через рантайм, без модели
ANTHROPIC_API_KEY=... $COMMERCE_AGENTS_DIR/.venv/bin/python -m agent_pilot.run_agent --period 3 --digest
```

Файлы `data/sales_p*.csv` грузятся в дашборд как обычные отчёты; `costs.csv` и
`stocks_p*.csv` — в загрузчики себестоимости и остатков.
