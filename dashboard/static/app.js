const SERIES = {
  netRevenue: { color: "var(--series-1)", label: "Чистая выручка" },
  mpExpenses: { color: "var(--series-2)", label: "Расходы МП" },
  payout: { color: "var(--series-3)", label: "К выплате" },
};

const DEDUCTION_LABELS = [
  ["commission", "Комиссия МП", "var(--series-1)"],
  ["logistics", "Логистика МП", "var(--series-2)"],
  ["storage", "Хранение", "var(--series-3)"],
  ["promotion", "Продвижение", "var(--series-5)"],
  ["penalty", "Штрафы", "var(--series-6)"],
  ["other_deduction", "Прочие удержания", "var(--series-8)"],
];

// Keep in sync with RETURN_RATE_RED_ZONE in analytics/metrics.py — duplicated
// here only to filter the already-fetched product list, not to recompute it.
const RETURN_RATE_RED_ZONE = 0.30;

const PERIOD_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;
const GENERIC_ERROR_MESSAGE = "Не удалось загрузить данные. Проверьте соединение с сервером и попробуйте ещё раз.";

function fmtMoney(value) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";
}

// Compact ruble for the KPI hero tiles ("107,1 млн ₽"); exact value stays in the tooltip.
function fmtMoneyCompact(value) {
  const a = Math.abs(value), sign = value < 0 ? "−" : "";
  if (a >= 1e6) return sign + (a / 1e6).toFixed(1).replace(".", ",") + " млн ₽";
  if (a >= 1e4) return sign + Math.round(a / 1e3) + " тыс ₽";
  return fmtMoney(value);
}

function fmtPercent(value) {
  return (value * 100).toFixed(1) + "%";
}

// product_name/sku come from marketplace-supplied catalog data (seller listing
// titles), not something we control — escape before templating into innerHTML.
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}

function currentFilters() {
  const params = {
    client_id: document.getElementById("f-client").value.trim() || "demo",
  };
  const marketplace = document.getElementById("f-marketplace").value;
  const dateFrom = document.getElementById("f-date-from").value;
  const dateTo = document.getElementById("f-date-to").value;
  const search = document.getElementById("f-search").value.trim();
  if (marketplace) params.marketplace = marketplace;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  if (search) params.search = search;
  return params;
}

function toQuery(params) {
  return new URLSearchParams(params).toString();
}

async function fetchJSON(path, params) {
  const res = await fetch(`${path}?${toQuery(params)}`);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

function renderStatRow(summary) {
  const tiles = [
    { label: "Реализация", value: summary.realization },
    { label: "Возвраты", value: summary.returns },
    { label: "Чистая выручка", value: summary.net_revenue, signed: true },
    { label: "Расходы МП", value: summary.mp_expenses },
    { label: "К выплате", value: summary.payout, signed: true, hero: true },
  ];
  const el = document.getElementById("stat-row");
  el.innerHTML = tiles.map(t => `
    <div class="stat-tile ${t.hero ? "stat-tile-hero" : ""}" title="${t.label}: ${fmtMoney(t.value)}">
      <div class="label">${t.label}</div>
      <div class="value ${t.signed ? (t.value >= 0 ? "positive" : "negative") : ""}">${fmtMoneyCompact(t.value)}</div>
    </div>
  `).join("");
}

function renderDeductions(breakdown) {
  const max = Math.max(...DEDUCTION_LABELS.map(([key]) => breakdown[key] || 0), 1);
  const el = document.getElementById("chart-deductions");
  const rows = DEDUCTION_LABELS
    .map(([key, label, color]) => ({ key, label, color, value: breakdown[key] || 0 }))
    .sort((a, b) => b.value - a.value);

  const chart = rows.map(r => `
    <div class="bar-row">
      <span class="bar-label">${r.label}</span>
      <div class="bar-track">
        <div class="bar-fill" title="${escapeHtml(r.label)}: ${fmtMoney(r.value)}" style="width:${(r.value / max * 100).toFixed(1)}%; background:${r.color}"></div>
      </div>
      <span class="bar-value">${fmtMoney(r.value)}</span>
    </div>
  `).join("");

  const table = `
    <button class="data-table-toggle" data-target="deductions-table">Показать таблицу</button>
    <table id="deductions-table" hidden>
      <thead><tr><th>Статья</th><th class="num">Сумма</th></tr></thead>
      <tbody>
        ${rows.map(r => `<tr><td>${escapeHtml(r.label)}</td><td class="num">${fmtMoney(r.value)}</td></tr>`).join("")}
      </tbody>
    </table>
  `;

  el.innerHTML = chart + table;
  wireTableToggle(el);
}

function wireTableToggle(container) {
  const toggle = container.querySelector(".data-table-toggle");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const target = document.getElementById(toggle.dataset.target);
    target.hidden = !target.hidden;
    toggle.textContent = target.hidden ? "Показать таблицу" : "Скрыть таблицу";
  });
}

function renderDynamics(months) {
  const el = document.getElementById("chart-dynamics");
  if (!months.length) {
    el.innerHTML = `<p class="hint">Нет данных за выбранный период.</p>`;
    return;
  }
  const max = Math.max(
    ...months.flatMap(m => [m.net_revenue, m.mp_expenses, m.payout]),
    1
  );

  const legend = `
    <div class="legend">
      ${Object.values(SERIES).map(s => `
        <span class="legend-item">
          <span class="legend-swatch" style="background:${s.color}"></span>${s.label}
        </span>
      `).join("")}
    </div>
  `;

  const bar = (value, color, label, month) =>
    `<div class="col-bar" title="${month} — ${escapeHtml(label)}: ${fmtMoney(value)}" style="height:${Math.max(value / max * 100, 0)}%; background:${color}"></div>`;

  const chart = `
    <div class="col-chart">
      ${months.map(m => `
        <div class="col-group">
          ${bar(m.net_revenue, SERIES.netRevenue.color, SERIES.netRevenue.label, m.month)}
          ${bar(m.mp_expenses, SERIES.mpExpenses.color, SERIES.mpExpenses.label, m.month)}
          ${bar(m.payout, SERIES.payout.color, SERIES.payout.label, m.month)}
        </div>
      `).join("")}
    </div>
    <div class="col-labels">
      ${months.map(m => `<span>${m.month}</span>`).join("")}
    </div>
  `;

  const table = `
    <button class="data-table-toggle" data-target="dynamics-table">Показать таблицу</button>
    <table id="dynamics-table" hidden>
      <thead><tr><th>Месяц</th><th class="num">Чистая выручка</th><th class="num">Расходы МП</th><th class="num">К выплате</th></tr></thead>
      <tbody>
        ${months.map(m => `
          <tr>
            <td>${m.month}</td>
            <td class="num">${fmtMoney(m.net_revenue)}</td>
            <td class="num">${fmtMoney(m.mp_expenses)}</td>
            <td class="num">${fmtMoney(m.payout)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;

  el.innerHTML = legend + chart + table;
  wireTableToggle(el);
}

function productRowHtml(p) {
  const flags = p.red_flags.map(f => `<span class="flag">${f}</span>`).join("");
  const abcChip = p.abc ? `<span class="abc-chip abc-${p.abc}">${p.abc === "L" ? "−" : p.abc}</span>` : "";
  return `
    <tr>
      <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
      <td>${abcChip}</td>
      <td class="num">${fmtMoney(p.realization)}</td>
      <td class="num">${fmtMoney(p.returns)}</td>
      <td class="num">${fmtPercent(p.return_rate)}</td>
      <td class="num">${fmtMoney(p.mp_expenses)}</td>
      <td class="num ${p.margin < 0 ? "delta-down" : ""}">${p.margin != null ? fmtPercent(p.margin) : "—"}</td>
      <td class="num ${p.payout < 0 ? "delta-down" : ""}">${fmtMoney(p.payout)}</td>
      <td>${flags}</td>
    </tr>
  `;
}

function renderProductsTable(products) {
  const el = document.getElementById("table-products");
  if (!products.length) {
    el.innerHTML = `<p class="hint">Ничего не найдено по текущим фильтрам.</p>`;
    return;
  }
  const search = document.getElementById("f-search").value.trim();
  const count = `<p class="result-count">${search ? `Найдено по запросу «${escapeHtml(search)}»: ` : "Всего товаров: "}<strong>${products.length}</strong>. Сортировка — худшие по выплате первыми.</p>`;
  el.innerHTML = count + `
    <table>
      <thead>
        <tr>
          <th>Товар</th><th>ABC</th><th class="num">Реализация</th><th class="num">Возврат</th>
          <th class="num">% возврата</th><th class="num">Расходы МП</th>
          <th class="num">Маржа</th><th class="num">К выплате</th><th>Флаги</th>
        </tr>
      </thead>
      <tbody>${products.map(productRowHtml).join("")}</tbody>
    </table>
  `;
}

function renderReturnsTable(products) {
  const el = document.getElementById("table-returns");
  const withReturns = products.filter(p => p.returns > 0).sort((a, b) => b.returns - a.returns);
  if (!withReturns.length) {
    el.innerHTML = `<p class="hint">Возвратов нет.</p>`;
    return;
  }
  const totalReturns = withReturns.reduce((s, p) => s + p.returns, 0);
  const totalReal = products.reduce((s, p) => s + p.realization, 0);
  const top10 = withReturns.slice(0, 10).reduce((s, p) => s + p.returns, 0);
  const summary = `<p class="result-count">Возвраты съели <strong>${fmtMoney(totalReturns)}</strong>${totalReal ? ` (${(totalReturns / totalReal * 100).toFixed(1)}% реализации)` : ""}. Топ-10 товаров дают ${totalReturns ? (top10 / totalReturns * 100).toFixed(0) : 0}% потерь — сортировка по рублям, сначала самое дорогое.</p>`;
  el.innerHTML = summary + `
    <table>
      <thead>
        <tr><th>Товар</th><th class="num">Потери, ₽</th><th class="num">% возврата</th><th class="num">Реализация</th><th>Сигнал</th></tr>
      </thead>
      <tbody>
        ${withReturns.map(p => `
          <tr>
            <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
            <td class="num delta-down">${fmtMoney(p.returns)}</td>
            <td class="num">${fmtPercent(p.return_rate)}</td>
            <td class="num">${fmtMoney(p.realization)}</td>
            <td>${p.return_rate >= RETURN_RATE_RED_ZONE ? `<span class="flag">возвратность ≥ 30%</span>` : ""}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

/* ==== Вкладка «Анализ» ==== */

function renderInsightsCards(a) {
  const el = document.getElementById("insights");
  const pct = v => (v * 100).toFixed(1) + "%";
  const cards = [];

  if (a.losers_count) {
    cards.push({ severity: "critical",
      title: `Убыточные товары: ${a.losers_count} шт., минус ${fmtMoney(Math.abs(a.loss_sum))}`,
      body: `Эти позиции после удержаний МП приносят убыток.${a.losers[0] ? ` Худший: «${escapeHtml(a.losers[0].product_name)}» (${fmtMoney(a.losers[0].payout)}).` : ""}`,
      action: `Если убрать или переоценить их, выплата вырастет на ${fmtMoney(Math.abs(a.loss_sum))}.` });
  } else {
    cards.push({ severity: "good", title: "Убыточных товаров нет", body: "Все позиции с продажами дают положительную выплату." });
  }

  if (a.dead_stock_count) {
    cards.push({ severity: "warning",
      title: `Расходы без продаж: ${a.dead_stock_count} товаров, ${fmtMoney(a.dead_stock_cost)}`,
      body: "Ни одной продажи за период, но начислены хранение/логистика/прочие удержания.",
      action: "Проверьте остатки: вывезти со склада, снизить цену или закрыть карточку." });
  }

  cards.push({ severity: a.returns_share > 0.1 ? "warning" : "neutral",
    title: `Возвраты: ${fmtMoney(a.totals.returns)} (${pct(a.returns_share)} реализации)`,
    body: `Топ-10 товаров дают ${pct(a.top10_returns_share)} всех возвратов в рублях.`,
    action: a.top_returns[0] ? `Главный источник: «${escapeHtml(a.top_returns[0].product_name)}» — ${fmtMoney(a.top_returns[0].returns)}.` : "" });

  cards.push({ severity: a.drr > 0.1 ? "warning" : "neutral",
    title: `ДРР (продвижение): ${pct(a.drr)} от реализации`,
    body: `Потрачено ${fmtMoney(a.promotion_total)}.` + (a.drr > 0.1 ? " Выше типичного порога 10% — проверьте отдачу кампаний." : " В пределах нормы (до 10%).") });

  cards.push({ severity: a.top10_payout_share > 0.5 ? "warning" : "good",
    title: `Концентрация: топ-10 товаров дают ${pct(a.top10_payout_share)} выплаты`,
    body: a.top10_payout_share > 0.5
      ? "Больше половины денег приносит узкая группа товаров — падение любого сильно ударит по выручке."
      : "Выручка распределена по ассортименту — зависимость от отдельных хитов умеренная." });

  if (a.mom) {
    cards.push({ severity: a.mom.delta < -0.05 ? "warning" : a.mom.delta > 0.05 ? "good" : "neutral",
      title: `Динамика выплаты: ${a.mom.delta >= 0 ? "+" : ""}${pct(a.mom.delta)} (${a.mom.prev_month} → ${a.mom.last_month})`,
      body: `${fmtMoney(a.mom.prev_payout)} → ${fmtMoney(a.mom.last_payout)}.` });
  }

  cards.push({ severity: a.expense_share > 0.35 ? "warning" : "neutral",
    title: `Маркетплейсы забирают ${pct(a.expense_share)} реализации`,
    body: `Все удержания за период: ${fmtMoney(a.totals.mp_expenses)}. Средняя маржа к выплате: ${pct(a.avg_margin)}.` });

  el.innerHTML = cards.map(c => `
    <div class="insight ${c.severity}">
      <div class="insight-title"><span class="insight-dot"></span>${c.title}</div>
      <div>${c.body}</div>
      ${c.action ? `<div class="insight-action">→ ${c.action}</div>` : ""}
    </div>`).join("");
}

function renderAbcSummary(a) {
  const el = document.getElementById("abc-summary");
  const classes = [
    ["A", "Приносят 80% выплаты", "abc-A"],
    ["B", "Ещё 15% выплаты", "abc-B"],
    ["C", "Хвост: последние 5%", "abc-C"],
    ["L", "Убыточные", "abc-L"],
  ];
  el.innerHTML = `
    <table>
      <thead><tr><th>Класс</th><th>Что означает</th><th class="num">Товаров</th><th class="num">Доля SKU</th><th class="num">Сумма выплаты</th></tr></thead>
      <tbody>${classes.map(([cls, label, chip]) => {
        const item = a.abc[cls] || { count: 0, payout: 0, share_sku: 0 };
        return `<tr>
          <td><span class="abc-chip ${chip}">${cls === "L" ? "−" : cls}</span></td>
          <td>${label}</td>
          <td class="num">${item.count}</td>
          <td class="num">${(item.share_sku * 100).toFixed(1)}%</td>
          <td class="num">${fmtMoney(item.payout)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>
    <p class="hint" style="margin-bottom:0">A — беречь и не допускать out-of-stock, B — растить, C — проверить целесообразность, «−» — убирать или переоценивать.</p>`;
}

function renderChannelCompare(a) {
  const el = document.getElementById("channel-compare");
  const names = { wb: "Wildberries", ozon: "Ozon" };
  const keys = Object.keys(a.channels);
  if (keys.length < 2) {
    el.innerHTML = `<p class="hint">Сравнение доступно при фильтре «Все маркетплейсы» и данных обоих каналов.</p>`;
    return;
  }
  const pctOf = (v, base) => base ? (v / base * 100).toFixed(1) + "%" : "—";
  const rows = [
    ["Реализация", c => fmtMoney(c.realization)],
    ["Возвратность", c => pctOf(c.returns, c.realization)],
    ["Комиссия", c => pctOf(c.commission, c.realization)],
    ["Логистика", c => pctOf(c.logistics, c.realization)],
    ["Хранение", c => pctOf(c.storage, c.realization)],
    ["Продвижение (ДРР)", c => pctOf(c.promotion, c.realization)],
    ["Штрафы и прочее", c => pctOf(c.penalty + c.other_deduction, c.realization)],
    ["К выплате с рубля", c => c.realization ? (c.payout / c.realization).toFixed(2) + " ₽" : "—"],
  ];
  const better = keys.reduce((best, k) =>
    (a.channels[k].payout / (a.channels[k].realization || 1)) > (a.channels[best].payout / (a.channels[best].realization || 1)) ? k : best, keys[0]);
  el.innerHTML = `
    <table>
      <thead><tr><th>Показатель</th>${keys.map(k => `<th class="num">${names[k] || k}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(([label, fn]) => `
        <tr><td>${label}</td>${keys.map(k => `<td class="num">${fn(a.channels[k])}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>
    <p class="hint" style="margin-bottom:0">Эффективнее сейчас: <strong>${names[better] || better}</strong> — больше остаётся с каждого рубля реализации. Наращивать канал стоит по выплате, а не по обороту.</p>`;
}

function renderLossTable(a) {
  const el = document.getElementById("loss-table");
  if (!a.losers.length) {
    el.innerHTML = `<p class="hint">Убыточных товаров нет — отлично.</p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr><th>Товар</th><th class="num">Реализация</th><th class="num">Расходы МП</th><th class="num">% возврата</th><th class="num">Убыток</th><th>Что делать</th></tr></thead>
      <tbody>${a.losers.map(p => {
        const advice = !p.realization ? "нет продаж — вывезти остатки или закрыть карточку"
          : p.return_rate >= RETURN_RATE_RED_ZONE ? "высокие возвраты — проверить качество/размерную сетку/фото"
          : p.mp_expenses > p.realization ? "расходы выше выручки — поднять цену или сменить схему поставки"
          : "пересчитать юнит-экономику";
        return `<tr>
          <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
          <td class="num">${fmtMoney(p.realization)}</td>
          <td class="num">${fmtMoney(p.mp_expenses)}</td>
          <td class="num">${fmtPercent(p.return_rate)}</td>
          <td class="num delta-down">${fmtMoney(p.payout)}</td>
          <td class="hint">${advice}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function renderAnalysis(insights) {
  renderInsightsCards(insights);
  renderAbcSummary(insights);
  renderChannelCompare(insights);
  renderLossTable(insights);
}

async function renderPlanFact() {
  const el = document.getElementById("table-plan-fact");
  const period = document.getElementById("plan-period").value.trim();
  if (!period) {
    el.innerHTML = `<p class="hint">Укажите месяц (YYYY-MM) слева, чтобы увидеть план-факт.</p>`;
    return;
  }
  if (!PERIOD_PATTERN.test(period)) {
    el.innerHTML = `<p class="hint">Месяц должен быть в формате YYYY-MM, например 2023-12.</p>`;
    return;
  }
  const filters = currentFilters();
  let rows;
  try {
    rows = await fetchJSON("/api/plan-fact", {
      client_id: filters.client_id,
      period,
      ...(filters.marketplace ? { marketplace: filters.marketplace } : {}),
    });
  } catch (err) {
    console.error(err);
    el.innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr><th>Метрика</th><th class="num">План</th><th class="num">Факт</th><th class="num">Отклонение</th></tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${r.metric === "net_revenue" ? "Чистая выручка" : "К выплате"}</td>
            <td class="num">${r.plan != null ? fmtMoney(r.plan) : "—"}</td>
            <td class="num">${fmtMoney(r.fact)}</td>
            <td class="num ${r.delta != null && r.delta < 0 ? "negative" : ""}">${r.delta != null ? fmtMoney(r.delta) : "—"}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

let refreshGeneration = 0;

async function refresh() {
  const filters = currentFilters();
  // Set synchronously, before any await, so the export link always matches
  // the filters that were active when this refresh started — even if the
  // fetches below fail or a newer refresh supersedes this one.
  document.getElementById("export-csv").href = `/api/export/products.csv?${toQuery(filters)}`;

  const generation = ++refreshGeneration;

  let summary, deductions, dynamics, products, insights;
  try {
    [summary, deductions, dynamics, products, insights] = await Promise.all([
      fetchJSON("/api/summary", filters),
      fetchJSON("/api/deductions", filters),
      fetchJSON("/api/dynamics", filters),
      fetchJSON("/api/products", filters),
      fetchJSON("/api/insights", filters),
    ]);
  } catch (err) {
    if (generation !== refreshGeneration) return; // superseded by a newer refresh
    console.error(err);
    document.getElementById("stat-row").innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
    return;
  }

  // A newer refresh() started (and may already have rendered) while this one
  // was in flight — drop this now-stale response instead of overwriting.
  if (generation !== refreshGeneration) return;

  renderStatRow(summary);
  renderDeductions(deductions);
  renderDynamics(dynamics);
  renderProductsTable(products);
  renderReturnsTable(products);
  renderAnalysis(insights);
  await renderPlanFact();
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".tab-panel").forEach(p => (p.hidden = true));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      document.querySelector(`.tab-panel[data-panel="${tab.dataset.tab}"]`).hidden = false;
    });
  });
}

function setupFilters() {
  ["f-client", "f-marketplace", "f-date-from", "f-date-to"].forEach(id => {
    document.getElementById(id).addEventListener("change", refresh);
  });
  document.getElementById("f-search").addEventListener("input", debounce(refresh, 300));
  document.getElementById("plan-period").addEventListener("change", renderPlanFact);
}

function setupPlanSave() {
  document.getElementById("save-plan").addEventListener("click", async () => {
    const client_id = currentFilters().client_id;
    const period = document.getElementById("plan-period").value.trim();
    if (!period || !PERIOD_PATTERN.test(period)) {
      alert("Укажите месяц в формате YYYY-MM, например 2023-12.");
      return;
    }
    const netRevenue = document.getElementById("plan-net-revenue").value;
    const payout = document.getElementById("plan-payout").value;
    const calls = [];
    if (netRevenue) calls.push(postPlan(client_id, period, "net_revenue", netRevenue));
    if (payout) calls.push(postPlan(client_id, period, "payout", payout));
    try {
      await Promise.all(calls);
    } catch (err) {
      console.error(err);
      alert("Не удалось сохранить план. Проверьте значения и попробуйте ещё раз.");
      return;
    }
    await renderPlanFact();
  });
}

async function postPlan(client_id, period, metric, plan_value) {
  const res = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id, period, metric, plan_value: Number(plan_value) }),
  });
  if (!res.ok) throw new Error(`/api/plan failed: ${res.status}`);
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// --- Загрузка CSV-файлов ---------------------------------------------------

const ROW_EDIT_FIELDS = [
  ["period_date", "Дата"], ["sku", "Артикул"], ["product_name", "Товар"],
  ["quantity", "Кол-во"], ["realization", "Реализация"], ["returns", "Возврат"],
  ["commission", "Комиссия"], ["logistics", "Логистика"], ["storage", "Хранение"],
  ["promotion", "Продвижение"], ["penalty", "Штраф"], ["other_deduction", "Прочее"],
  ["payout", "К выплате"],
];

let openRowsUploadId = null;

function uploadStatusEl() { return document.getElementById("upload-status"); }

function showUploadStatus(text, isError = false) {
  const el = uploadStatusEl();
  el.hidden = false;
  el.textContent = text;
  el.classList.toggle("row-error-text", isError);
}

async function refreshUploads() {
  const client_id = currentFilters().client_id;
  const el = document.getElementById("uploads-list");
  let uploads;
  try {
    uploads = await fetchJSON("/api/uploads", { client_id });
  } catch (err) {
    console.error(err);
    el.innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
    return;
  }
  if (!uploads.length) {
    el.innerHTML = `<p class="hint">Файлы ещё не загружались. Загрузите первый отчёт выше.</p>`;
    return;
  }
  el.innerHTML = `
    <div class="table-wrap"><table>
      <thead>
        <tr>
          <th>Файл</th><th>Маркетплейс</th><th>Загружен</th>
          <th class="num">Строк ОК</th><th class="num">Исправлено</th><th class="num">Ошибок</th>
          <th>Статус</th><th>Действия</th>
        </tr>
      </thead>
      <tbody>
        ${uploads.map(u => `
          <tr>
            <td>${escapeHtml(u.filename)}${JSON.parse(u.file_fixes).length ? `<br /><span class="row-fixes-text">автоисправления файла: ${escapeHtml(JSON.parse(u.file_fixes).join(", "))}</span>` : ""}</td>
            <td>${u.marketplace === "wb" ? "Wildberries" : "Ozon"}</td>
            <td>${escapeHtml((u.uploaded_at || "").slice(0, 16).replace("T", " "))}</td>
            <td class="num">${u.rows_ok}</td>
            <td class="num">${u.rows_fixed ? `<span class="chip chip-fixed">${u.rows_fixed}</span>` : 0}</td>
            <td class="num">${u.rows_error ? `<span class="chip chip-error">${u.rows_error}</span>` : 0}</td>
            <td>${u.status === "imported" ? `<span class="chip chip-imported">импортирован</span>` : `<span class="chip chip-ok">готов к импорту</span>`}</td>
            <td>
              <button class="btn-small" data-action="rows" data-id="${u.id}" type="button">Строки</button>
              ${u.status !== "imported" ? `<button class="btn-small" data-action="import" data-id="${u.id}" type="button">Импортировать</button>` : ""}
              ${u.rows_error ? `<button class="btn-small" data-action="errors-csv" data-id="${u.id}" type="button">Ошибки CSV</button>` : ""}
              <button class="btn-small danger" data-action="delete" data-id="${u.id}" type="button">Удалить</button>
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table></div>`;

  el.querySelectorAll("button[data-action]").forEach(btn => {
    btn.addEventListener("click", () => handleUploadAction(btn.dataset.action, Number(btn.dataset.id)));
  });
}

async function handleUploadAction(action, uploadId) {
  if (action === "rows") {
    openRowsUploadId = uploadId;
    await renderUploadRows(uploadId);
    return;
  }
  if (action === "errors-csv") {
    window.location.href = `/api/uploads/${uploadId}/errors.csv`;
    return;
  }
  if (action === "import") {
    try {
      const res = await fetch(`/api/uploads/${uploadId}/import`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.status);
      showUploadStatus(
        `Импортировано строк: ${body.imported}.` +
        (body.errors_left ? ` Осталось ошибок: ${body.errors_left} — их можно исправить в «Строках» и импортировать повторно.` : " Все строки загружены в дашборд.")
      );
    } catch (err) {
      console.error(err);
      showUploadStatus(`Не удалось импортировать: ${err.message}`, true);
    }
    await refreshUploads();
    refresh();
    return;
  }
  if (action === "delete") {
    if (!confirm("Удалить файл? Если он был импортирован, его данные будут убраны из дашборда.")) return;
    try {
      const res = await fetch(`/api/uploads/${uploadId}`, { method: "DELETE" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.status);
      showUploadStatus(body.rolled_back_transactions
        ? `Файл удалён, из дашборда убрано строк: ${body.rolled_back_transactions}.`
        : "Файл удалён.");
    } catch (err) {
      console.error(err);
      showUploadStatus(`Не удалось удалить: ${err.message}`, true);
    }
    if (openRowsUploadId === uploadId) {
      openRowsUploadId = null;
      document.getElementById("rows-card").hidden = true;
    }
    await refreshUploads();
    refresh();
  }
}

async function renderUploadRows(uploadId) {
  const card = document.getElementById("rows-card");
  const container = document.getElementById("upload-rows");
  card.hidden = false;
  document.getElementById("rows-title").textContent = `Строки файла №${uploadId}`;
  let rows;
  try {
    rows = await fetchJSON(`/api/uploads/${uploadId}/rows`, {});
  } catch (err) {
    console.error(err);
    container.innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
    return;
  }

  const chip = (r) => r.status === "ok"
    ? `<span class="chip chip-ok">ок</span>`
    : r.status === "fixed"
      ? `<span class="chip chip-fixed">исправлено</span>`
      : `<span class="chip chip-error">ошибка</span>`;

  container.innerHTML = `
    <table>
      <thead>
        <tr><th>№</th><th>Статус</th>${ROW_EDIT_FIELDS.map(([, label]) => `<th>${label}</th>`).join("")}<th></th></tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr class="row-editor" data-row-id="${r.id}">
            <td>${r.row_index + 2}</td>
            <td>${chip(r)}${r.error ? `<div class="row-error-text">${escapeHtml(r.error)}</div>` : ""}${r.fixes.length ? `<div class="row-fixes-text">${escapeHtml(r.fixes.join("; "))}</div>` : ""}</td>
            ${ROW_EDIT_FIELDS.map(([field]) => `
              <td><input data-field="${field}" value="${escapeHtml(r.data[field] ?? "")}" ${r.status === "error" ? "" : "readonly"} /></td>
            `).join("")}
            <td>${r.status === "error"
              ? `<button class="btn-small" data-save-row="${r.id}" type="button">Сохранить</button>`
              : `<button class="btn-small" data-unlock-row="${r.id}" type="button">Править</button>`}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;

  container.querySelectorAll("button[data-unlock-row]").forEach(btn => {
    btn.addEventListener("click", () => {
      const tr = btn.closest("tr");
      tr.querySelectorAll("input").forEach(i => i.removeAttribute("readonly"));
      btn.textContent = "Сохранить";
      btn.removeAttribute("data-unlock-row");
      btn.setAttribute("data-save-row", tr.dataset.rowId);
      btn.addEventListener("click", () => saveRow(uploadId, Number(tr.dataset.rowId), tr), { once: true });
    }, { once: true });
  });
  container.querySelectorAll("button[data-save-row]").forEach(btn => {
    btn.addEventListener("click", () => {
      const tr = btn.closest("tr");
      saveRow(uploadId, Number(tr.dataset.rowId), tr);
    });
  });
}

async function saveRow(uploadId, rowId, tr) {
  const payload = {};
  tr.querySelectorAll("input[data-field]").forEach(input => {
    payload[input.dataset.field] = input.value;
  });
  try {
    const res = await fetch(`/api/uploads/${uploadId}/rows/${rowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.status);
    showUploadStatus(body.status === "error"
      ? `Строка всё ещё с ошибкой: ${body.error}`
      : "Строка исправлена и проверена.", body.status === "error");
  } catch (err) {
    console.error(err);
    showUploadStatus(`Не удалось сохранить строку: ${err.message}`, true);
  }
  await renderUploadRows(uploadId);
  await refreshUploads();
  refresh();
}

function setupUploads() {
  document.getElementById("upload-submit").addEventListener("click", async () => {
    const fileInput = document.getElementById("upload-file");
    const file = fileInput.files[0];
    if (!file) {
      showUploadStatus("Сначала выберите файл CSV.", true);
      return;
    }
    const formData = new FormData();
    formData.append("client_id", currentFilters().client_id);
    formData.append("marketplace", document.getElementById("upload-marketplace").value);
    formData.append("file", file);
    const button = document.getElementById("upload-submit");
    button.disabled = true;
    showUploadStatus("Загружаю и проверяю файл…");
    try {
      const res = await fetch("/api/uploads", { method: "POST", body: formData });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.status);
      const parts = [`Файл разобран: строк ОК — ${body.rows_ok}, исправлено автоматически — ${body.rows_fixed}, с ошибками — ${body.rows_error}.`];
      parts.push(body.rows_error
        ? "Ошибки можно поправить в «Строках», затем нажать «Импортировать»."
        : "Нажмите «Импортировать», чтобы данные попали в дашборд.");
      showUploadStatus(parts.join(" "));
      fileInput.value = "";
    } catch (err) {
      console.error(err);
      showUploadStatus(`Не удалось загрузить: ${err.message}`, true);
    }
    button.disabled = false;
    await refreshUploads();
  });

  // Подгружаем список при первом открытии вкладки.
  document.getElementById("tab-uploads").addEventListener("click", refreshUploads, { once: true });
  document.getElementById("f-client").addEventListener("change", () => {
    if (!document.getElementById("panel-uploads").hidden) refreshUploads();
  });
}

setupTabs();
setupFilters();
setupPlanSave();
setupUploads();
// refresh() catches its own fetch errors; this is a last-resort net for a
// synchronous bug before that point (e.g. a missing DOM element).
refresh().catch(err => {
  console.error(err);
  document.getElementById("stat-row").innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
});
