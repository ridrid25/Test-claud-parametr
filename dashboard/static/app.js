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

// Latest fetched data, cached so segment/grouping/sort/card clicks re-render
// without re-hitting the server; costsLoaded flips the whole UI to net-profit.
let lastProducts = [];
let lastInsights = null;
let lastDeductions = null;
let costsLoaded = false;

const trunc = (text, n = 26) => {
  const s = String(text || "—");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
};

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

// Цветной бейдж маркетплейса: фирменный цвет + короткий значок WB/OZ.
const MP_LABELS = { wb: "Wildberries", ozon: "Ozon" };
function mpBadge(mp, compact = false) {
  const cls = mp === "wb" ? "mp-wb" : "mp-ozon";
  const short = mp === "wb" ? "WB" : "OZ";
  return `<span class="mp-badge ${cls}${compact ? " mp-compact" : ""}"><span class="mp-dot">${short}</span><span class="mp-label">${MP_LABELS[mp] || escapeHtml(mp)}</span></span>`;
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

function renderStatRow(summary, insights) {
  // With себестоимость loaded, the bottom line is net profit (payout − COGS),
  // so the hero tile becomes «Чистая прибыль» and we surface COGS separately.
  const tiles = costsLoaded && insights
    ? [
        { label: "Реализация", value: summary.realization },
        { label: "Возвраты", value: summary.returns },
        { label: "Расходы МП", value: summary.mp_expenses },
        { label: "Себестоимость", value: insights.cogs_total },
        { label: "Чистая прибыль", value: insights.profit_total, signed: true, hero: true },
      ]
    : [
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

/* ==== Товары: сегменты, группировка, карточка ==== */

const MP_NAMES = { wb: "Wildberries", ozon: "Ozon" };
const ABC_NAMES = { A: "A — ядро (80% выплаты)", B: "B — середина", C: "C — хвост", L: "− Убыточные" };
const ABC_CHIP = { A: "abc-A", B: "abc-B", C: "abc-C", L: "abc-L" };

// Ранжирующая метрика: чистая прибыль, когда загружена себестоимость, иначе выплата.
const resultOf = p => (p.result != null ? p.result : p.payout);

const SEGMENTS = [
  ["all", "Все", () => true],
  ["loss", "Убыточные", p => resultOf(p) < 0],
  ["dead", "Мёртвый сток", p => !p.realization && !p.returns && p.mp_expenses > 0],
  ["returns", "Возвраты ≥ 30%", p => p.return_rate >= RETURN_RATE_RED_ZONE],
  ["A", "Класс A", p => p.abc === "A"],
  ["B", "Класс B", p => p.abc === "B"],
  ["C", "Класс C", p => p.abc === "C"],
];

const GROUP_DIMS = {
  section: p => (p.category || "").split("/")[0].trim() || "Без раздела",
  category: p => {
    const parts = (p.category || "").split("/");
    return (parts[1] || parts[0] || "").trim() || "Без подкатегории";
  },
  brand: p => p.brand || "Без бренда",
  marketplace: p => MP_NAMES[p.marketplace] || p.marketplace,
  abc: p => ABC_NAMES[p.abc] || p.abc,
};

let productSort = { key: "payout", dir: "asc" };
let productSegment = "all";
let expandedGroups = new Set();
let openProductSku = null;

function groupProducts(products, groupKey) {
  const keyFn = GROUP_DIMS[groupKey];
  const groups = new Map();
  for (const p of products) {
    const name = keyFn(p);
    if (!groups.has(name)) groups.set(name, { name, items: [], realization: 0, returns: 0, mp_expenses: 0, payout: 0 });
    const g = groups.get(name);
    g.items.push(p);
    g.realization += p.realization; g.returns += p.returns; g.mp_expenses += p.mp_expenses; g.payout += p.payout;
  }
  for (const g of groups.values()) {
    g.margin = g.realization ? g.payout / g.realization : (g.payout < 0 ? -1 : 0);
    g.return_rate = (g.realization + g.returns) ? g.returns / (g.realization + g.returns) : 0;
    g.items.sort((a, b) => resultOf(a) - resultOf(b)); // worst first inside the group
  }
  return [...groups.values()].sort((a, b) => b.payout - a.payout);
}

function renderSegments(products) {
  const el = document.getElementById("product-segments");
  el.innerHTML = SEGMENTS.map(([key, label, fn]) => {
    const count = products.filter(fn).length;
    return `<button class="segment ${productSegment === key ? "active" : ""}" data-segment="${key}" type="button">${label}<span class="seg-count">${count}</span></button>`;
  }).join("");
  el.querySelectorAll("button[data-segment]").forEach(btn => {
    btn.addEventListener("click", () => {
      productSegment = btn.dataset.segment;
      openProductSku = null;
      rerenderProducts();
    });
  });
}

function productCardRow(p, colspan) {
  const pct = v => p.realization ? (v / p.realization * 100).toFixed(1) + "%" : "—";
  const maxDeduction = Math.max(p.commission, p.logistics, p.storage, p.promotion, p.penalty, p.other_deduction, 1);
  const deductionRows = [
    ["Комиссия МП", p.commission], ["Логистика", p.logistics], ["Хранение", p.storage],
    ["Продвижение", p.promotion], ["Штрафы", p.penalty], ["Прочие удержания", p.other_deduction],
  ].map(([label, value]) => `
    <tr><td>${label}</td>
      <td><div class="share-track"><div class="share-fill" style="width:${((value || 0) / maxDeduction * 100).toFixed(0)}%"></div></div></td>
      <td class="num">${fmtMoney(value || 0)}</td><td class="num">${pct(value || 0)}</td></tr>`).join("");
  const hasCost = p.unit_cost != null;
  return `
    <tr class="product-card"><td colspan="${colspan}">
      <div class="pcard">
        <div>
          <h4>Деньги: от продажи до выплаты</h4>
          <table>
            <tr><td>Реализация</td><td></td><td class="num">${fmtMoney(p.realization)}</td><td class="num">100%</td></tr>
            <tr><td>− Возвраты</td><td></td><td class="num delta-down">${fmtMoney(p.returns)}</td><td class="num">${pct(p.returns)}</td></tr>
            ${deductionRows}
            <tr><td><strong>= К выплате</strong></td><td></td><td class="num ${p.payout < 0 ? "delta-down" : ""}"><strong>${fmtMoney(p.payout)}</strong></td><td class="num"><strong>${pct(p.payout)}</strong></td></tr>
            ${hasCost ? `
            <tr><td>− Себестоимость (${p.quantity || 0} шт × ${fmtMoney(p.unit_cost)})</td><td></td><td class="num delta-down">${fmtMoney(p.cogs)}</td><td class="num">${pct(p.cogs)}</td></tr>
            <tr><td><strong>= Чистая прибыль</strong></td><td></td><td class="num ${p.profit < 0 ? "delta-down" : ""}"><strong>${fmtMoney(p.profit)}</strong></td><td class="num"><strong>${pct(p.profit)}</strong></td></tr>` : (costsLoaded ? `
            <tr><td colspan="4" class="hint">Себестоимость для этого SKU не найдена в загруженном файле.</td></tr>` : "")}
          </table>
        </div>
        <div>
          <h4>Паспорт товара</h4>
          <dl class="kv">
            <dt>Маркетплейс</dt><dd>${mpBadge(p.marketplace)}</dd>
            <dt>Категория</dt><dd>${escapeHtml(p.category) || "—"}</dd>
            <dt>Бренд</dt><dd>${escapeHtml(p.brand) || "—"}</dd>
            <dt>Класс ABC</dt><dd><span class="abc-chip ${ABC_CHIP[p.abc] || ""}">${p.abc === "L" ? "−" : (p.abc || "")}</span></dd>
            <dt>Продано, шт</dt><dd>${p.quantity || "—"}</dd>
            <dt>Возвратность</dt><dd>${fmtPercent(p.return_rate)}</dd>
            ${hasCost ? `
            <dt>Себестоимость за шт</dt><dd>${fmtMoney(p.unit_cost)}</dd>
            <dt>Чистая прибыль</dt><dd class="${p.profit < 0 ? "delta-down" : ""}">${fmtMoney(p.profit)}</dd>
            <dt>Рентабельность</dt><dd class="${p.profit_margin < 0 ? "delta-down" : ""}">${fmtPercent(p.profit_margin)}</dd>` : `
            <dt>Маржа к выплате</dt><dd class="${p.payout_margin < 0 ? "delta-down" : ""}">${fmtPercent(p.payout_margin)}</dd>`}
            <dt>Сигналы</dt><dd>${p.red_flags.length ? p.red_flags.map(f => `<span class="flag">${escapeHtml(f)}</span>`).join(" ") : "нет"}</dd>
          </dl>
        </div>
      </div>
    </td></tr>`;
}

function productLineHtml(p, colspan, indent = 0) {
  const line = `
    <tr class="product-line" data-sku="${escapeHtml(p.sku)}">
      <td style="padding-left:${14 + indent}px">${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
      <td class="num">${p.quantity || ""}</td>
      <td class="num">${fmtMoney(p.realization)}</td>
      <td class="num">${fmtMoney(p.returns)}</td>
      <td class="num">${fmtPercent(p.return_rate)}</td>
      <td class="num">${fmtMoney(p.mp_expenses)}</td>
      <td class="num ${p.margin < 0 ? "delta-down" : ""}">${p.margin != null ? fmtPercent(p.margin) : "—"}</td>
      <td class="num ${p.payout < 0 ? "delta-down" : ""}">${fmtMoney(p.payout)}</td>
    </tr>`;
  return line + (openProductSku === p.sku ? productCardRow(p, colspan) : "");
}

const PRODUCT_COLUMNS = [
  ["product_name", "Товар", false],
  ["abc", "ABC", false],
  ["realization", "Реализация", true],
  ["returns", "Возврат", true],
  ["return_rate", "% возврата", true],
  ["mp_expenses", "Расходы МП", true],
  ["margin", "Маржа", true],
  ["payout", "К выплате", true],
];

function productRowHtml(p) {
  const flags = p.red_flags.map(f => `<span class="flag">${escapeHtml(f)}</span>`).join("");
  const row = `
    <tr class="product-line" data-sku="${escapeHtml(p.sku)}">
      <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}${p.category ? " · " + escapeHtml(p.category) : ""}</span></td>
      <td>${p.abc ? `<span class="abc-chip ${ABC_CHIP[p.abc] || ""}">${p.abc === "L" ? "−" : p.abc}</span>` : ""}</td>
      <td class="num">${fmtMoney(p.realization)}</td>
      <td class="num">${fmtMoney(p.returns)}</td>
      <td class="num">${fmtPercent(p.return_rate)}</td>
      <td class="num">${fmtMoney(p.mp_expenses)}</td>
      <td class="num ${p.margin < 0 ? "delta-down" : ""}">${p.margin != null ? fmtPercent(p.margin) : "—"}</td>
      <td class="num ${p.payout < 0 ? "delta-down" : ""}">${fmtMoney(p.payout)}</td>
      <td>${flags}</td>
    </tr>`;
  return row + (openProductSku === p.sku ? productCardRow(p, 9) : "");
}

const PRODUCT_HEAD = () => `<thead><tr>${PRODUCT_COLUMNS.map(([key, label, isNum]) => {
  const shown = key === "margin" && costsLoaded ? "Рентаб." : label;
  return `<th class="sortable ${isNum ? "num" : ""} ${productSort.key === key ? "sorted-" + productSort.dir : ""}" data-sort="${key}">${shown}</th>`;
}).join("")}<th>Флаги</th></tr></thead>`;

function renderProductsTable(products) {
  const el = document.getElementById("table-products");
  renderSegments(products);

  const segment = SEGMENTS.find(([key]) => key === productSegment) || SEGMENTS[0];
  const visible = products.filter(segment[2]);
  const search = document.getElementById("f-search").value.trim();

  if (!visible.length) {
    el.innerHTML = products.length
      ? `<p class="hint">В сегменте «${segment[1]}» ничего не найдено по текущим фильтрам.</p>`
      : `<p class="hint">Нет товаров — загрузите файл на вкладке «Загрузка».</p>`;
    return;
  }

  const segNote = productSegment !== "all" ? ` в сегменте «${segment[1]}»` : "";
  const searchNote = search ? ` по запросу «${escapeHtml(search)}»` : "";
  // While searching, force the flat list — otherwise a match hides inside a
  // collapsed group and the search looks like it did nothing.
  const grouping = search ? "" : document.getElementById("product-grouping").value;

  if (grouping) {
    const grouping2 = document.getElementById("product-grouping2").value;
    const sub = (grouping2 && grouping2 !== grouping) ? grouping2 : null;
    const COLSPAN = 8;

    const groupRowHtml = (g, key, level) => `
      <tr class="group-row ${level === 2 ? "level-2" : ""}" data-group="${escapeHtml(key)}">
        <td style="padding-left:${level === 2 ? 28 : 12}px"><span class="group-caret">${expandedGroups.has(key) ? "▾" : "▸"}</span>${escapeHtml(g.name)}</td>
        <td class="num">${g.items.length}</td>
        <td class="num">${fmtMoney(g.realization)}</td>
        <td class="num">${fmtMoney(g.returns)}</td>
        <td class="num">${fmtPercent(g.return_rate)}</td>
        <td class="num">${fmtMoney(g.mp_expenses)}</td>
        <td class="num ${g.margin < 0 ? "delta-down" : ""}">${fmtPercent(g.margin)}</td>
        <td class="num ${g.payout < 0 ? "delta-down" : ""}">${fmtMoney(g.payout)}</td>
      </tr>`;

    const productBlock = (items, indent) =>
      items.slice(0, 30).map(p => productLineHtml(p, COLSPAN, indent)).join("") +
      (items.length > 30 ? `<tr><td colspan="${COLSPAN}" class="hint" style="padding-left:${indent + 14}px">…и ещё ${items.length - 30} товаров — уточните сегмент или поиск.</td></tr>` : "");

    const groups = groupProducts(visible, grouping);
    const count = `<p class="result-count">Групп: <strong>${groups.length}</strong>, товаров${segNote}${searchNote}: <strong>${visible.length}</strong>.</p>`;
    el.innerHTML = count + `
      <table>
        <thead><tr><th>Группа / товар</th><th class="num">Шт</th><th class="num">Реализация</th><th class="num">Возвраты</th><th class="num">% возврата</th><th class="num">Расходы МП</th><th class="num">Маржа</th><th class="num">К выплате</th></tr></thead>
        <tbody>${groups.map(g => {
          const key1 = g.name;
          let html = groupRowHtml(g, key1, 1);
          if (expandedGroups.has(key1)) {
            if (sub) {
              html += groupProducts(g.items, sub).map(sg => {
                const key2 = `${key1}||${sg.name}`;
                let subHtml = groupRowHtml(sg, key2, 2);
                if (expandedGroups.has(key2)) subHtml += productBlock(sg.items, 42);
                return subHtml;
              }).join("");
            } else {
              html += productBlock(g.items, 28);
            }
          }
          return html;
        }).join("")}</tbody>
      </table>`;
    el.querySelectorAll(".group-row").forEach(tr => {
      tr.addEventListener("click", () => {
        const name = tr.dataset.group;
        if (expandedGroups.has(name)) expandedGroups.delete(name);
        else expandedGroups.add(name);
        rerenderProducts();
      });
    });
    wireProductCards(el);
    return;
  }

  const sorted = [...visible].sort((a, b) => {
    const va = a[productSort.key], vb = b[productSort.key];
    const cmp = typeof va === "string" ? String(va).localeCompare(String(vb), "ru") : ((va || 0) - (vb || 0));
    return productSort.dir === "asc" ? cmp : -cmp;
  });
  const LIMIT = 500;
  const count = `<p class="result-count">Товаров${segNote}${searchNote}: <strong>${visible.length}</strong>${visible.length > LIMIT ? `, показаны первые ${LIMIT}` : ""}. Сортировка — клик по заголовку; клик по строке — карточка товара.</p>`;
  el.innerHTML = count + `
    <table>
      ${PRODUCT_HEAD()}
      <tbody>${sorted.slice(0, LIMIT).map(productRowHtml).join("")}</tbody>
    </table>`;
  el.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (productSort.key === key) productSort.dir = productSort.dir === "asc" ? "desc" : "asc";
      else productSort = { key, dir: key === "product_name" || key === "abc" ? "asc" : "desc" };
      rerenderProducts();
    });
  });
  wireProductCards(el);
}

function wireProductCards(container) {
  container.querySelectorAll("tr.product-line").forEach(tr => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input")) return;
      const sku = tr.dataset.sku;
      openProductSku = openProductSku === sku ? null : sku;
      rerenderProducts();
    });
  });
}

function rerenderProducts() {
  renderProductsTable(lastProducts);
}

/* ==== Возвраты: группировка по разделам/категориям/брендам ==== */

let returnsGrouping = "section";
const returnsExpanded = new Set();

function returnRateOf(g) {
  const gross = g.realization + g.returns;
  return gross ? g.returns / gross : 0;
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
  const summary = `<p class="result-count">Возвраты съели <strong>${fmtMoney(totalReturns)}</strong>${totalReal ? ` (${(totalReturns / totalReal * 100).toFixed(1)}% реализации)` : ""}. Топ-10 товаров дают ${totalReturns ? (top10 / totalReturns * 100).toFixed(0) : 0}% потерь. Разверните группу, чтобы увидеть товары.</p>`;

  if (!returnsGrouping) {
    el.innerHTML = summary + `
      <table>
        <thead><tr><th>Товар</th><th class="num">Потери, ₽</th><th class="num">% возврата</th><th class="num">Реализация</th><th>Сигнал</th></tr></thead>
        <tbody>${withReturns.slice(0, 300).map(p => `
          <tr>
            <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
            <td class="num delta-down">${fmtMoney(p.returns)}</td>
            <td class="num">${fmtPercent(p.return_rate)}</td>
            <td class="num">${fmtMoney(p.realization)}</td>
            <td>${p.return_rate >= RETURN_RATE_RED_ZONE ? `<span class="flag">возвратность ≥ 30%</span>` : ""}</td>
          </tr>`).join("")}${withReturns.length > 300 ? `<tr><td colspan="5" class="hint">…показаны первые 300 — уточните фильтры или используйте экспорт CSV.</td></tr>` : ""}</tbody>
      </table>`;
    return;
  }

  const keyFn = GROUP_DIMS[returnsGrouping];
  const groups = new Map();
  for (const p of withReturns) {
    const name = keyFn(p);
    const g = groups.get(name) || { name, items: [], returns: 0, realization: 0 };
    g.items.push(p); g.returns += p.returns; g.realization += p.realization;
    groups.set(name, g);
  }
  const sorted = [...groups.values()].sort((a, b) => b.returns - a.returns);

  el.innerHTML = summary + `
    <table>
      <thead><tr><th>Группа / товар</th><th class="num">Товаров</th><th class="num">Потери, ₽</th><th class="num">% возврата</th><th class="num">Реализация</th></tr></thead>
      <tbody>${sorted.map(g => {
        const key = g.name;
        const isOpen = returnsExpanded.has(key);
        let html = `
          <tr class="group-row" data-ret-group="${escapeHtml(key)}">
            <td><span class="group-caret">${isOpen ? "▾" : "▸"}</span>${escapeHtml(g.name)}</td>
            <td class="num">${g.items.length}</td>
            <td class="num delta-down">${fmtMoney(g.returns)}</td>
            <td class="num">${fmtPercent(returnRateOf(g))}</td>
            <td class="num">${fmtMoney(g.realization)}</td>
          </tr>`;
        if (isOpen) {
          html += g.items.slice(0, 30).map(p => `
            <tr><td style="padding-left:28px">${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
              <td></td>
              <td class="num delta-down">${fmtMoney(p.returns)}</td>
              <td class="num">${fmtPercent(p.return_rate)}</td>
              <td class="num">${fmtMoney(p.realization)}</td></tr>`).join("");
          if (g.items.length > 30) html += `<tr><td colspan="5" class="hint" style="padding-left:28px">…и ещё ${g.items.length - 30} товаров.</td></tr>`;
        }
        return html;
      }).join("")}</tbody>
    </table>`;
  el.querySelectorAll(".group-row").forEach(tr => {
    tr.addEventListener("click", () => {
      const name = tr.dataset.retGroup;
      if (returnsExpanded.has(name)) returnsExpanded.delete(name);
      else returnsExpanded.add(name);
      renderReturnsTable(lastProducts);
    });
  });
}

/* ==== Вкладка «Анализ» ==== */

function renderInsightsCards(a) {
  const el = document.getElementById("insights");
  const pct = v => (v * 100).toFixed(1) + "%";
  const cards = [];

  if (a.costs_loaded) {
    cards.push({ severity: a.profit_total < 0 ? "critical" : "good",
      title: `Чистая прибыль: ${fmtMoney(a.profit_total)} (рентабельность ${pct(a.profit_margin)})`,
      body: `К выплате ${fmtMoney(a.totals.payout)} минус себестоимость проданного ${fmtMoney(a.cogs_total)}. Это настоящий результат бизнеса, а не оборот.`,
      action: a.cost_coverage < 0.95 ? `Внимание: себестоимость найдена только для ${pct(a.cost_coverage)} товаров — по остальным прибыль завышена.` : "" });
  }

  const lossWord = a.costs_loaded ? "с учётом себестоимости приносят убыток" : "после удержаний МП приносят убыток";
  const profitWord = a.costs_loaded ? "прибыль" : "выплата";
  if (a.losers_count) {
    cards.push({ severity: "critical",
      title: `Убыточные товары: ${a.losers_count} шт., минус ${fmtMoney(Math.abs(a.loss_sum))}`,
      body: `Эти позиции ${lossWord}.${a.losers[0] ? ` Худший: «${escapeHtml(a.losers[0].product_name)}» (${fmtMoney(resultOf(a.losers[0]))}).` : ""}`,
      action: `Если убрать или переоценить их, ${profitWord} за период вырастет на ${fmtMoney(Math.abs(a.loss_sum))}.` });
  } else {
    cards.push({ severity: "good", title: "Убыточных товаров нет",
      body: a.costs_loaded ? "Все позиции с продажами прибыльны с учётом себестоимости." : "Все позиции с продажами дают положительную выплату." });
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
  const metricWord = a.costs_loaded ? "прибыли" : "выплаты";
  const classes = [
    ["A", `Приносят 80% ${metricWord}`, "abc-A"],
    ["B", `Ещё 15% ${metricWord}`, "abc-B"],
    ["C", "Хвост: последние 5%", "abc-C"],
    ["L", "Убыточные", "abc-L"],
  ];
  el.innerHTML = `
    <table>
      <thead><tr><th>Класс</th><th>Что означает</th><th class="num">Товаров</th><th class="num">Доля SKU</th><th class="num">Сумма ${metricWord}</th></tr></thead>
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
      <thead><tr><th>Показатель</th>${keys.map(k => `<th class="mp-col">${mpBadge(k)}</th>`).join("")}</tr></thead>
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
          : (p.unit_cost != null && p.cogs > p.payout && p.payout > 0) ? "себестоимость съедает выплату — пересмотреть закупочную или продажную цену"
          : "пересчитать юнит-экономику";
        return `<tr>
          <td>${escapeHtml(p.product_name) || "—"}<br /><span class="muted">${escapeHtml(p.sku)}</span></td>
          <td class="num">${fmtMoney(p.realization)}</td>
          <td class="num">${fmtMoney(p.mp_expenses)}</td>
          <td class="num">${fmtPercent(p.return_rate)}</td>
          <td class="num delta-down">${fmtMoney(resultOf(p))}</td>
          <td class="hint">${advice}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function barRows(items, color, valueFn, labelFn, titleFn, valueLabelFn) {
  const max = Math.max(...items.map(valueFn), 1);
  return items.map(item => `
    <div class="bar-row">
      <span class="bar-label" title="${escapeHtml(titleFn ? titleFn(item) : labelFn(item))}">${escapeHtml(labelFn(item))}</span>
      <div class="bar-track"><div class="bar-fill" title="${escapeHtml(titleFn ? titleFn(item) : "")}" style="width:${(valueFn(item) / max * 100).toFixed(1)}%; background:${color}"></div></div>
      <span class="bar-value">${valueLabelFn ? valueLabelFn(item) : fmtMoney(valueFn(item))}</span>
    </div>`).join("");
}

function renderRubleFlow(insights, deductions) {
  const el = document.getElementById("ruble-flow");
  const t = insights.totals;
  if (!t.realization) { el.innerHTML = `<p class="hint">Нет реализации за период.</p>`; return; }
  const ownParts = costsLoaded
    ? [
        ["Чистая прибыль (вам)", Math.max(insights.profit_total, 0), "var(--series-2)"],
        ["Себестоимость проданного", insights.cogs_total, "var(--series-7)"],
      ]
    : [["К выплате (вам)", Math.max(t.payout, 0), "var(--series-2)"]];
  const segments = [
    ...ownParts,
    ["Возвраты", t.returns, "var(--series-6)"],
    ["Комиссия МП", deductions.commission, "var(--series-1)"],
    ["Логистика", deductions.logistics, "var(--series-3)"],
    ["Хранение", deductions.storage, "var(--series-5)"],
    ["Продвижение", deductions.promotion, "var(--series-8)"],
    ["Штрафы и прочее", (deductions.penalty || 0) + (deductions.other_deduction || 0), "var(--baseline)"],
  ].filter(([, v]) => v > 0);
  const total = segments.reduce((s, [, v]) => s + v, 0) || 1;
  el.innerHTML = `
    <div class="stack-bar">
      ${segments.map(([label, value, color]) =>
        `<div class="stack-seg" title="${escapeHtml(label)}: ${fmtMoney(value)} (${(value / total * 100).toFixed(1)}%)" style="flex:${(value / total).toFixed(4)}; background:${color}"></div>`).join("")}
    </div>
    <div class="stack-legend">
      ${segments.map(([label, value, color]) => `
        <span class="legend-item">
          <span class="legend-swatch" style="background:${color}"></span>
          <span class="legend-name">${label}</span>
          <span class="legend-pct">${(value / total * 100).toFixed(1)}%</span>
          <span class="legend-rub">${fmtMoney(value)}</span>
        </span>`).join("")}
    </div>`;
}

const MARGIN_BINS = [
  ["Убыточные (маржа < 0)", p => p.margin < 0, "var(--series-6)"],
  ["0–20%", p => p.margin >= 0 && p.margin < 0.2, "var(--series-8)"],
  ["20–40%", p => p.margin >= 0.2 && p.margin < 0.4, "var(--series-3)"],
  ["40–60%", p => p.margin >= 0.4 && p.margin < 0.6, "var(--series-1)"],
  ["60–80%", p => p.margin >= 0.6 && p.margin < 0.8, "var(--series-2)"],
  ["80%+", p => p.margin >= 0.8, "var(--series-5)"],
];

function renderMarginHistogram(products) {
  const el = document.getElementById("margin-histogram");
  if (!products.length) { el.innerHTML = `<p class="hint">Нет товаров.</p>`; return; }
  const bins = MARGIN_BINS.map(([label, fn, color]) => ({ label, color, count: products.filter(fn).length }));
  const max = Math.max(...bins.map(b => b.count), 1);
  el.innerHTML = bins.map(b => `
    <div class="bar-row">
      <span class="bar-label" style="width:150px">${b.label}</span>
      <div class="bar-track"><div class="bar-fill" title="${b.label}: ${b.count} товаров (${(b.count / products.length * 100).toFixed(1)}%)" style="width:${(b.count / max * 100).toFixed(1)}%; background:${b.color}"></div></div>
      <span class="bar-value">${b.count} тов. (${(b.count / products.length * 100).toFixed(0)}%)</span>
    </div>`).join("") +
    `<p class="hint" style="margin-bottom:0">${costsLoaded
      ? "Рентабельность = чистая прибыль (после себестоимости) / реализация. Здоровый профиль — горб справа; всё, что слева от 20%, — кандидаты на пересмотр цены или закупки."
      : "Маржа = «к выплате» / реализация (без себестоимости — загрузите файл себестоимости на вкладке «Загрузка», и здесь появится настоящая рентабельность). Здоровый профиль — горб справа."}</p>`;
}

function renderAnalysis(insights, deductions, products) {
  renderInsightsCards(insights);
  renderRubleFlow(insights, deductions);
  renderMarginHistogram(products);
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

  let summary, deductions, dynamics, products, insights, costStatus;
  try {
    [summary, deductions, dynamics, products, insights, costStatus] = await Promise.all([
      fetchJSON("/api/summary", filters),
      fetchJSON("/api/deductions", filters),
      fetchJSON("/api/dynamics", filters),
      fetchJSON("/api/products", filters),
      fetchJSON("/api/insights", filters),
      fetchJSON("/api/costs", { client_id: filters.client_id }),
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

  costsLoaded = !!costStatus.loaded;
  lastProducts = products;
  lastInsights = insights;
  lastDeductions = deductions;

  renderStatRow(summary, insights);
  renderDeductions(deductions);
  renderDynamics(dynamics);
  renderProductsTable(products);
  renderReturnsTable(products);
  renderAnalysis(insights, deductions, products);
  renderCostStatus(costStatus);
  await renderPlanFact();
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach(t => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach(p => {
    p.hidden = p.dataset.panel !== name;
  });
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
}

function setupFilters() {
  ["f-client", "f-marketplace", "f-date-from", "f-date-to"].forEach(id => {
    document.getElementById(id).addEventListener("change", refresh);
  });
  // Typing a query jumps to «Товары» so the search visibly does something —
  // the search filter only affects the products/returns lists, not «Анализ».
  document.getElementById("f-search").addEventListener("input", debounce(() => {
    if (document.getElementById("f-search").value.trim()) activateTab("products");
    refresh();
  }, 300));
  document.getElementById("plan-period").addEventListener("change", renderPlanFact);

  // Grouping selects re-render the cached product list — no server round-trip.
  ["product-grouping", "product-grouping2"].forEach(id => {
    document.getElementById(id).addEventListener("change", () => {
      expandedGroups = new Set();
      openProductSku = null;
      rerenderProducts();
    });
  });
  document.getElementById("returns-grouping").addEventListener("change", (e) => {
    returnsGrouping = e.target.value;
    returnsExpanded.clear();
    renderReturnsTable(lastProducts);
  });
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
            <td>${mpBadge(u.marketplace)}</td>
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

// --- Себестоимость (unit cost) ---------------------------------------------

function renderCostStatus(status) {
  const el = document.getElementById("cost-status");
  const removeBtn = document.getElementById("cost-remove");
  if (!el) return;
  if (status && status.loaded) {
    el.textContent = `Себестоимость загружена: ${status.count} SKU${status.source_file ? ` (${status.source_file})` : ""}. Анализ, ABC и карточки считают чистую прибыль (к выплате − себестоимость проданного).`;
    el.classList.remove("row-error-text");
    if (removeBtn) removeBtn.hidden = false;
  } else {
    el.textContent = "Понимает «Полная себестоимость за шт», «Себестоимость закупки за шт» или просто «Себестоимость». Пока файл не загружен, анализ идёт без неё — по метрике «к выплате».";
    el.classList.remove("row-error-text");
    if (removeBtn) removeBtn.hidden = true;
  }
}

function setupCosts() {
  document.getElementById("cost-submit").addEventListener("click", async () => {
    const fileInput = document.getElementById("cost-file");
    const file = fileInput.files[0];
    const statusEl = document.getElementById("cost-status");
    if (!file) {
      statusEl.textContent = "Сначала выберите файл CSV с себестоимостью.";
      statusEl.classList.add("row-error-text");
      return;
    }
    const formData = new FormData();
    formData.append("client_id", currentFilters().client_id);
    formData.append("file", file);
    const button = document.getElementById("cost-submit");
    button.disabled = true;
    statusEl.classList.remove("row-error-text");
    statusEl.textContent = "Загружаю и проверяю файл себестоимости…";
    try {
      const res = await fetch("/api/costs", { method: "POST", body: formData });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.status);
      const fixes = (body.file_fixes || []).length ? ` Автоисправления: ${body.file_fixes.join(", ")}.` : "";
      const skipped = body.skipped ? ` Пропущено строк без валидной себестоимости: ${body.skipped}.` : "";
      statusEl.textContent = `Из файла добавлено ${body.added} SKU (колонка «${body.cost_column}»). Всего товаров с себестоимостью: ${body.count}.${fixes}${skipped} Дашборд пересчитан по чистой прибыли.`;
      fileInput.value = "";
      await refresh();
    } catch (err) {
      console.error(err);
      statusEl.textContent = `Не удалось загрузить себестоимость: ${err.message}`;
      statusEl.classList.add("row-error-text");
    }
    button.disabled = false;
  });

  document.getElementById("cost-remove").addEventListener("click", async () => {
    if (!confirm("Убрать загруженную себестоимость? Анализ вернётся к метрике «к выплате».")) return;
    try {
      await fetch(`/api/costs?${toQuery({ client_id: currentFilters().client_id })}`, { method: "DELETE" });
    } catch (err) {
      console.error(err);
    }
    await refresh();
  });
}

// --- Подключение по API ----------------------------------------------------

function renderConnectionStatus(status) {
  const set = (id, connected) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = connected ? "подключено" : "не подключено";
    el.classList.toggle("conn-on", connected);
  };
  set("wb-conn-status", status.wb_connected);
  set("ozon-conn-status", status.ozon_connected);
  const anyConnected = status.wb_connected || status.ozon_connected;
  const disc = document.getElementById("disconnect-all");
  if (disc) disc.hidden = !anyConnected;
}

async function refreshConnectionStatus() {
  try {
    const status = await fetchJSON("/api/credentials", { client_id: currentFilters().client_id });
    renderConnectionStatus(status);
  } catch (err) {
    console.error(err);
  }
}

function setupApiConnect() {
  document.getElementById("save-credentials").addEventListener("click", async () => {
    const statusEl = document.getElementById("credentials-status");
    const payload = {
      client_id: currentFilters().client_id,
      wb_api_key: document.getElementById("wb-key").value.trim(),
      ozon_client_id: document.getElementById("ozon-client-id").value.trim(),
      ozon_api_key: document.getElementById("ozon-key").value.trim(),
    };
    if (!payload.wb_api_key && !payload.ozon_client_id && !payload.ozon_api_key) {
      statusEl.hidden = false;
      statusEl.classList.add("row-error-text");
      statusEl.textContent = "Введите хотя бы один ключ.";
      return;
    }
    try {
      const res = await fetch("/api/credentials", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const status = await res.json();
      if (!res.ok) throw new Error(status.detail || res.status);
      renderConnectionStatus(status);
      // Clear the inputs so keys aren't left on screen; presence shows in status.
      ["wb-key", "ozon-client-id", "ozon-key"].forEach(id => (document.getElementById(id).value = ""));
      statusEl.hidden = false;
      statusEl.classList.remove("row-error-text");
      statusEl.textContent = "Ключи сохранены. Теперь можно загрузить данные по API ниже.";
    } catch (err) {
      console.error(err);
      statusEl.hidden = false;
      statusEl.classList.add("row-error-text");
      statusEl.textContent = `Не удалось сохранить ключи: ${err.message}`;
    }
  });

  document.getElementById("disconnect-all").addEventListener("click", async () => {
    if (!confirm("Отключить все сохранённые ключи? Загруженные ранее данные останутся.")) return;
    try {
      await fetch(`/api/credentials?${toQuery({ client_id: currentFilters().client_id })}`, { method: "DELETE" });
    } catch (err) {
      console.error(err);
    }
    await refreshConnectionStatus();
  });

  document.getElementById("sync-submit").addEventListener("click", async () => {
    const statusEl = document.getElementById("sync-status");
    const reconEl = document.getElementById("sync-reconciliation");
    const dateFrom = document.getElementById("sync-date-from").value;
    const dateTo = document.getElementById("sync-date-to").value;
    reconEl.innerHTML = "";
    if (!dateFrom || !dateTo) {
      statusEl.hidden = false;
      statusEl.classList.add("row-error-text");
      statusEl.textContent = "Укажите период — с даты и по дату.";
      return;
    }
    const button = document.getElementById("sync-submit");
    button.disabled = true;
    statusEl.hidden = false;
    statusEl.classList.remove("row-error-text");
    statusEl.textContent = "Запрашиваю данные из кабинетов… это может занять до минуты.";
    try {
      const res = await fetch("/api/sync", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: currentFilters().client_id, date_from: dateFrom, date_to: dateTo }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.status);

      const parts = [];
      if (body.wb != null) parts.push(`Wildberries: загружено ${body.wb} строк`);
      if (body.errors && body.errors.wb) parts.push(`Wildberries: ${body.errors.wb}`);
      if (body.ozon != null) parts.push(`Ozon: загружено ${body.ozon} строк`);
      if (body.errors && body.errors.ozon) parts.push(`Ozon: ${body.errors.ozon}`);
      statusEl.textContent = parts.join(". ") + ". Дашборд обновлён.";
      statusEl.classList.toggle("row-error-text", !!(body.errors && Object.keys(body.errors).length));

      if (body.reconciliation && body.reconciliation.length) {
        reconEl.innerHTML = `<p class="hint" style="margin:14px 0 6px">Сверьте эти суммы с кабинетом за тот же период:</p>` +
          `<pre class="recon-block">${escapeHtml(body.reconciliation.join("\n"))}</pre>`;
      }
      await refresh();
    } catch (err) {
      console.error(err);
      statusEl.classList.add("row-error-text");
      statusEl.textContent = `Не удалось загрузить: ${err.message}`;
    }
    button.disabled = false;
  });

  // Load connection status when the tab is first opened, and on client change.
  document.getElementById("tab-connect").addEventListener("click", refreshConnectionStatus, { once: true });
  document.getElementById("f-client").addEventListener("change", () => {
    if (!document.getElementById("panel-connect").hidden) refreshConnectionStatus();
  });
}

function setupFiltersToggle() {
  // On phones the filter sidebar is collapsed behind this button (it's hidden
  // on desktop via CSS). Tap to reveal filters/period, tap again to hide.
  const toggle = document.getElementById("filters-toggle");
  const sidebar = document.getElementById("sidebar");
  toggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.classList.toggle("open", open);
  });
}

setupTabs();
setupFilters();
setupFiltersToggle();
setupPlanSave();
setupApiConnect();
setupUploads();
setupCosts();
// refresh() catches its own fetch errors; this is a last-resort net for a
// synchronous bug before that point (e.g. a missing DOM element).
refresh().catch(err => {
  console.error(err);
  document.getElementById("stat-row").innerHTML = `<p class="hint">${GENERIC_ERROR_MESSAGE}</p>`;
});
