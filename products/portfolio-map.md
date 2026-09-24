# Карта цифровых продуктов ridrid25 (инвентаризация 42 репо, 24.09.2026)

## Фундамент 1 — ФИНАНСЫ (основной, самый глубокий)
ГОТОВО / PRODUCTION:
- Test-claud-parametr: дашборд-витрина mp.ridfinance.ru; серверный
  мультиклиентский пайплайн WB/Ozon (API, ETL, SQLite, FastAPI);
  лендинг услуги «Экспресс-диагностика» (форма в бота, ниша m);
  «Советник» — AI-торговый агент (commerce-agents) с пилотом.
- data-smeta-audit — PRODUCTION (smeta.ridfinance.ru, реальный
  пользователь): выгодность тендера по смете ГРАНД-Смета. Тиражируем.
- taxwise-calculator — готовый интерактивный калькулятор
  УСН/АУСН/ОСНО с НДС, PDF-отчёт. Прямо в тему воронки.
- cfo-agent — бот-«финдиректор» по Google-таблице клиента, ~190
  тестов. Ядро идеи «цифры без посредника».
БЛИЗКО: mirage (прогнозный дашборд, 8 итераций), financial-command-
center (канонический из трёх дашбордов), happy-sales-trail,
vibefin-ai (концепт-витрина), stage-analytics-suite.
КОНФЛИКТ С ПРАВИЛОМ «сервис, не персона» (11.09): cfo-outsourcing-
landing, rid-visit-site (+ частично Motivation-offer).
МЕРТВО: Ozon-wild-fintablo (пустой), DebtControl (дамп).

## Фундамент 2 — СТРОЙКА/ПРОИЗВОДСТВО B2B (недооценённый high-ticket)
- data-smeta-audit (production, см. выше);
- asphalt-profit-master (актуальная итерация) + uds-asphalt-calc
  (прошлая; asphalt-margin-calculator — пустой);
- Parametric-transport-budget — готовая финмодель транспортного
  бюджета (Sheets + HTML-дашборд);
- SprayCheck (= spraycheck-vision-pro, дубль) — агро-прототип.
ЦА: подрядчики, АБЗ, транспортные компании. Естественный чек
50–300 тыс. за внедрение/настройку.

## Фундамент 3 — ИГРЫ
Chroma Loop (dream/adventures) — активная; island-hop, jumpbot,
cyber-blue — витрины/игрушки.

## Инфраструктура и личное (не продукты)
rid-finance (контент-система: автопостинг, бот заявок), vibepost /
content-factory-personal, telegram-bots (реестр 20 ботов),
pomoshchnik-naznacheniya-vstrech («Calendly в Telegram», продвинут),
ai-planner-balance (личный).

## Решения
1. В воронку линии А добавить taxwise-calculator (апселл/вторая
   ступень к налоговому гайду, письмо 4–5).
2. Линия Б строится на готовом: экспресс-диагностика (лендинг есть,
   перевести с персоны на сервис) → сопровождение на серверном
   пайплайне → cfo-agent/Советник как подписка.
3. Стройка-B2B — отдельная линия высокого чека: тираж data-smeta-
   audit + пакет АБЗ/транспорт. Не смешивать с селлерской.
4. Гигиена: выбрать канонический CFO-дашборд (кандидат mirage или
   financial-command-center), заархивировать дубли (spraycheck-
   vision-pro, старые asphalt, пустые), лендинги персоны — переделать
   или закрыть.
