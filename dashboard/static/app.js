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

function fmtMoney(value) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";
}

function fmtPercent(value) {
  return (value * 100).toFixed(1) + "%";
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
    { label: "К выплате", value: summary.payout, signed: true },
  ];
  const el = document.getElementById("stat-row");
  el.innerHTML = tiles.map(t => `
    <div class="stat-tile">
      <div class="label">${t.label}</div>
      <div class="value ${t.signed ? (t.value >= 0 ? "positive" : "negative") : ""}">${fmtMoney(t.value)}</div>
    </div>
  `).join("");
}

function renderDeductions(breakdown) {
  const max = Math.max(...DEDUCTION_LABELS.map(([key]) => breakdown[key] || 0), 1);
  const el = document.getElementById("chart-deductions");
  const rows = DEDUCTION_LABELS
    .map(([key, label, color]) => ({ key, label, color, value: breakdown[key] || 0 }))
    .sort((a, b) => b.value - a.value);

  el.innerHTML = rows.map(r => `
    <div class="bar-row">
      <span class="bar-label">${r.label}</span>
      <div class="bar-track">
        <div class="bar-fill" style="width:${(r.value / max * 100).toFixed(1)}%; background:${r.color}"></div>
      </div>
      <span class="bar-value">${fmtMoney(r.value)}</span>
    </div>
  `).join("");
}

function renderDynamics(months) {
  const el = document.getElementById("chart-dynamics");
  if (!months.length) {
    el.innerHTML = `<p class="muted">Нет данных за выбранный период.</p>`;
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

  const chart = `
    <div class="col-chart">
      ${months.map(m => `
        <div class="col-group" title="${m.month}">
          <div class="col-bar" style="height:${Math.max(m.net_revenue / max * 100, 0)}%; background:${SERIES.netRevenue.color}"></div>
          <div class="col-bar" style="height:${Math.max(m.mp_expenses / max * 100, 0)}%; background:${SERIES.mpExpenses.color}"></div>
          <div class="col-bar" style="height:${Math.max(m.payout / max * 100, 0)}%; background:${SERIES.payout.color}"></div>
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
  el.querySelector(".data-table-toggle").addEventListener("click", (e) => {
    const target = document.getElementById(e.target.dataset.target);
    target.hidden = !target.hidden;
    e.target.textContent = target.hidden ? "Показать таблицу" : "Скрыть таблицу";
  });
}

function productRowHtml(p) {
  const flags = p.red_flags.map(f => `<span class="flag">${f}</span>`).join("");
  return `
    <tr>
      <td>${p.product_name || "—"}<br /><span class="muted">${p.sku}</span></td>
      <td class="num">${fmtMoney(p.realization)}</td>
      <td class="num">${fmtMoney(p.returns)}</td>
      <td class="num">${fmtPercent(p.return_rate)}</td>
      <td class="num">${fmtMoney(p.mp_expenses)}</td>
      <td class="num">${fmtMoney(p.net_revenue)}</td>
      <td class="num">${fmtMoney(p.payout)}</td>
      <td>${flags}</td>
    </tr>
  `;
}

function renderProductsTable(products) {
  const el = document.getElementById("table-products");
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Товар</th><th class="num">Реализация</th><th class="num">Возврат</th>
          <th class="num">% возврата</th><th class="num">Расходы МП</th>
          <th class="num">Чистая выручка</th><th class="num">К выплате</th><th>Флаги</th>
        </tr>
      </thead>
      <tbody>${products.map(productRowHtml).join("")}</tbody>
    </table>
  `;
}

function renderReturnsTable(products) {
  const risky = products.filter(p => p.return_rate >= RETURN_RATE_RED_ZONE);
  const el = document.getElementById("table-returns");
  if (!risky.length) {
    el.innerHTML = `<p class="muted">Товаров с возвратностью ≥ 30% не найдено.</p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead>
        <tr><th>Товар</th><th class="num">% возврата</th><th class="num">Реализация</th><th class="num">Возврат</th></tr>
      </thead>
      <tbody>
        ${risky.map(p => `
          <tr>
            <td>${p.product_name || "—"}<br /><span class="muted">${p.sku}</span></td>
            <td class="num">${fmtPercent(p.return_rate)}</td>
            <td class="num">${fmtMoney(p.realization)}</td>
            <td class="num">${fmtMoney(p.returns)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function renderPlanFact() {
  const el = document.getElementById("table-plan-fact");
  const period = document.getElementById("plan-period").value.trim();
  if (!period) {
    el.innerHTML = `<p class="muted">Укажите месяц (YYYY-MM) слева, чтобы увидеть план-факт.</p>`;
    return;
  }
  const filters = currentFilters();
  const rows = await fetchJSON("/api/plan-fact", {
    client_id: filters.client_id,
    period,
    ...(filters.marketplace ? { marketplace: filters.marketplace } : {}),
  });
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

async function refresh() {
  const filters = currentFilters();
  const [summary, deductions, dynamics, products] = await Promise.all([
    fetchJSON("/api/summary", filters),
    fetchJSON("/api/deductions", filters),
    fetchJSON("/api/dynamics", filters),
    fetchJSON("/api/products", filters),
  ]);

  renderStatRow(summary);
  renderDeductions(deductions);
  renderDynamics(dynamics);
  renderProductsTable(products);
  renderReturnsTable(products);
  await renderPlanFact();

  document.getElementById("export-csv").href = `/api/export/products.csv?${toQuery(filters)}`;
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => (p.hidden = true));
      tab.classList.add("active");
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
    if (!period) return;
    const netRevenue = document.getElementById("plan-net-revenue").value;
    const payout = document.getElementById("plan-payout").value;
    const calls = [];
    if (netRevenue) calls.push(postPlan(client_id, period, "net_revenue", netRevenue));
    if (payout) calls.push(postPlan(client_id, period, "payout", payout));
    await Promise.all(calls);
    await renderPlanFact();
  });
}

async function postPlan(client_id, period, metric, plan_value) {
  await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id, period, metric, plan_value: Number(plan_value) }),
  });
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

setupTabs();
setupFilters();
setupPlanSave();
refresh().catch(err => {
  document.getElementById("stat-row").innerHTML = `<p class="muted">Не удалось загрузить данные: ${err.message}</p>`;
});
