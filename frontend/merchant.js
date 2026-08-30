// Merchant console: overview, live negotiations, catalog/policies, analytics, activity.
const user = requireRole("merchant");
const $ = (id) => document.getElementById(id);
const inr = (n) => n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN");
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let products = [];
let editId = null;

if (user) {
  const name = user.business_name || user.email;
  $("who").textContent = user.email;
  $("bizName").textContent = user.business_name || "Merchant";
  $("avatar").textContent = (name[0] || "M").toUpperCase();
}

// --- Sidebar navigation ---
const PAGE_META = {
  overview: ["Overview", "Your AI sales performance at a glance"],
  negotiations: ["Negotiations", "Watch your agent negotiate — or take over live"],
  catalog: ["Catalog & policies", "Products, pricing policy, and upsell rules"],
  orders: ["Orders", "Agreements and their payment status"],
  analytics: ["Analytics", "Closing prices, discounts, and cross-sell performance"],
  activity: ["Activity", "Audit trail of every material action"],
};
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.view === name));
  const [t, s] = PAGE_META[name] || ["", ""];
  $("pageTitle").textContent = t; $("pageSub").textContent = s;
}
document.querySelectorAll(".nav-item").forEach(n => n.onclick = () => showView(n.dataset.view));

function notice(el, text, cls = "err") {
  el.innerHTML = text ? `<div class="notice ${cls}">${text}</div>` : "";
}

let merchantChat = null;

async function refresh() {
  await Promise.all([loadProducts(), loadAnalytics(), loadRules(), loadAudit(),
                     loadPolicyChanges(), loadNegotiations(), loadOrders()]);
}

let merchantOrders = [];
window.mInvoice = (i) => { const o = merchantOrders[i]; if (o) printInvoice(o); };

async function loadOrders() {
  const rows = await api("/api/merchant/orders");
  merchantOrders = rows;
  $("orderTable").innerHTML =
    `<tr><th>Agreement</th><th>Buyer</th><th>Items</th><th>Total</th><th>Status</th><th>Payment</th><th>When</th><th></th></tr>` +
    (rows.length ? rows.map((o, i) => {
      const items = o.items.map(x => `${x.quantity}× ${esc(x.name)}`).join(", ");
      const cls = o.status === "CONFIRMED" ? "CONFIRMED" : o.status === "FAILED" ? "FAILED" : "AGREED";
      const when = o.created_at ? new Date(o.created_at).toLocaleString() : "—";
      return `<tr><td class="small muted">${o.agreement_uid}</td><td>${esc(o.counterparty)}</td>
        <td class="small">${items}${o.backorder ? ' <span class="tag">backorder</span>' : ""}</td>
        <td>${inr(o.total)}</td><td><span class="pill ${cls}">${o.status}</span></td>
        <td class="small muted">${o.payment_status || "—"}</td><td class="small muted">${when}</td>
        <td><button class="ghost sm" onclick="mInvoice(${i})">Invoice</button></td></tr>`;
    }).join("") : `<tr><td colspan="8" class="muted">No orders yet.</td></tr>`);
}

// --- Live notifications (account-level WebSocket) ---
function connectNotifications() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/merchant?token=${encodeURIComponent(getToken())}`);
  ws.onmessage = (e) => {
    let n; try { n = JSON.parse(e.data); } catch { return; }
    if (n.type !== "notification") return;
    toast("🔔 " + n.text, n.kind === "closed" ? "ok" : "");
    loadNegotiations();  // refresh table + live badge
    if (n.kind !== "new") loadOrders();
  };
  ws.onclose = () => setTimeout(connectNotifications, 2000);  // auto-reconnect
}

function downloadCsv(filename, rows) {
  const csv = rows.map(r => r.map(c => {
    const s = String(c == null ? "" : c);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

async function exportOrders() {
  try {
    const orders = await api("/api/merchant/orders");
    if (!orders.length) return toast("No orders to export yet.", "err");
    const rows = [["Agreement", "Buyer", "Items", "Total", "Status", "Payment", "Date"]];
    for (const o of orders) rows.push([o.agreement_uid, o.counterparty,
      o.items.map(i => `${i.quantity}x ${i.name}`).join("; "), o.total, o.status, o.payment_status || "", o.created_at || ""]);
    downloadCsv("atoac-orders.csv", rows);
    toast("Orders exported.", "ok");
  } catch (e) { toast(e.message, "err"); }
}

async function applySuggestion(pid, floor) {
  try {
    await api("/api/merchant/policy-suggestion", { method: "POST", body: { product_id: pid, floor_price: floor } });
    toast("Change queued — approve it under Catalog & policies.", "ok");
    await refresh();
  } catch (e) { toast(e.message, "err"); }
}

let activeNegUid = null;

async function loadNegotiations() {
  const rows = await api("/api/merchant/negotiations");
  const liveCount = rows.filter(n => n.status === "NEGOTIATING").length;
  const badge = $("navNegCount");
  if (badge) badge.textContent = liveCount || "";
  const list = $("negList");
  if (!list) return;
  if (!rows.length) { list.innerHTML = `<div class="faint small" style="padding:16px">No negotiations yet.</div>`; return; }
  list.innerHTML = rows.map(n => {
    const live = n.status === "NEGOTIATING";
    const cls = n.status === "AGREED" ? "agreed" : n.status === "DENIED" ? "denied" : "NEGOTIATING";
    const sub = live ? (n.waiting_for_merchant ? "Your turn to respond" : "Agent negotiating…")
      : n.status === "AGREED" ? `Agreed ${inr(n.final_unit_price)}/u` : (reasonLabel(n.reason_code) || n.status);
    const turn = n.waiting_for_merchant ? ` <span class="tag">your turn</span>` : "";
    return `<div class="neg-item ${n.negotiation_uid === activeNegUid ? "active" : ""}" data-uid="${n.negotiation_uid}" onclick="openMerchantChat('${n.negotiation_uid}')">
      <div class="ni-av">🧑</div>
      <div class="ni-main">
        <div class="ni-top"><strong>${esc(n.product_name || "—")}</strong><span class="ni-qty">${n.quantity}u</span></div>
        <div class="ni-sub">${live ? '<span class="live-dot"></span>' : ""}<span class="pill ${cls} ni-pill">${n.status}</span> ${esc(sub)}${turn}</div>
      </div></div>`;
  }).join("");
}

function openMerchantChat(uid) {
  activeNegUid = uid;
  const empty = $("negEmpty"); if (empty) empty.style.display = "none";
  document.querySelectorAll("#negList .neg-item").forEach(el => el.classList.toggle("active", el.dataset.uid === uid));
  if (merchantChat) merchantChat.stop();
  merchantChat = openChat($("merchantChatPanel"), uid, "merchant", {
    onClosed: () => loadNegotiations(),
    onState: (st) => renderAgentPanel(st),
  });
}
window.negAct = (a) => merchantChat && merchantChat.act(a);

// Right-hand "Deal Agent" panel: summarizes the buyer's requirements and the live
// state of this negotiation (merchant-side, so it may show the private floor).
function renderAgentPanel(st) {
  const host = $("negAgent"); if (!host) return;
  const prod = products.find(p => p.id === st.product_id) || {};
  const rev = [...st.messages].reverse();
  const lastMerch = rev.find(m => m.role === "merchant" && m.unit_price != null);
  const lastBuyer = rev.find(m => m.role === "buyer" && m.unit_price != null);
  const reqs = [
    ["Product", esc(st.product_name || "—")],
    ["Quantity", `${st.quantity} units`],
    ["Buyer's target", inr(st.target_price) + "/u"],
    ["Delivery", st.delivery_days ? `${st.delivery_days} days` : "—"],
  ];
  const pts = [["Rounds so far", st.rounds != null ? st.rounds : 0]];
  if (lastBuyer) pts.push(["Buyer's latest offer", inr(lastBuyer.unit_price) + "/u"]);
  if (lastMerch) pts.push(["Your agent's offer", inr(lastMerch.unit_price) + "/u"]);
  if (prod.floor_price != null) pts.push(["Your floor (private)", inr(prod.floor_price) + "/u"]);

  let pending;
  if (st.status === "AGREED") pending = `✅ Deal reached at <strong>${inr(st.final_unit_price)}/unit</strong> — ${inr(st.total)} total. The buyer will complete checkout.`;
  else if (st.status === "DENIED") pending = `❌ Closed with no deal — ${esc((reasonLabel(st.reason_code) || "").toLowerCase())}.`;
  else if (st.waiting_for === "merchant") pending = `⏳ Your turn — counter, accept, or reject in the chat.`;
  else if (st.merchant_control === "HUMAN") pending = `✋ You're at the table. Waiting for the buyer to respond.`;
  else pending = `🤖 Your sales agent is negotiating automatically — it will never breach your floor.`;

  const cta = st.status !== "NEGOTIATING" ? ""
    : st.merchant_control === "HUMAN"
      ? `<div class="ag-actions"><button class="ghost sm" onclick="negAct('resume')">🤖 Let agent handle</button></div>`
      : `<div class="ag-actions"><button class="warn-btn sm" onclick="negAct('pause')">✋ Take over</button></div>`;

  host.innerHTML = `
    <div class="ag-head"><span class="ag-spark">✦</span> Deal Agent</div>
    <div class="ag-summ">Summarizing this negotiation as it happens.<div class="ag-chip">🧾 ${esc(st.product_name || "Product")}</div></div>
    <div class="ag-sec">Buyer requirements</div>
    <ul class="ag-list">${reqs.map(([k, v]) => `<li><span>${k}</span><b>${v}</b></li>`).join("")}</ul>
    <div class="ag-sec">Key points</div>
    <ul class="ag-list">${pts.map(([k, v]) => `<li><span>${k}</span><b>${v}</b></li>`).join("")}</ul>
    <div class="ag-sec">What's pending</div>
    <div class="ag-pending">${pending}</div>
    ${cta}`;
}

const FIELD_LABELS = {
  list_price: "List price", floor_price: "Floor price", max_discount_pct: "Max discount %",
  min_order_qty: "Min order qty", max_negotiation_rounds: "Max rounds",
};

async function loadPolicyChanges() {
  const changes = await api("/api/merchant/policy-changes?status=PENDING");
  const card = $("policyCard");
  const pbadge = $("navPolicyCount");
  if (pbadge) pbadge.textContent = changes.length || "";
  if (!changes.length) { card.classList.add("hidden"); $("policyList").innerHTML = ""; return; }
  card.classList.remove("hidden");
  $("policyList").innerHTML = changes.map(c => {
    const diff = Object.entries(c.changes).map(([f, d]) =>
      `<div class="small">${FIELD_LABELS[f] || f}: <span class="muted">${d.old}</span> → <strong>${d.new}</strong></div>`
    ).join("");
    return `<div class="result-card">
      <strong>${c.product_name || ("Product #" + c.product_id)}</strong>
      <div style="margin:6px 0">${diff}</div>
      <div style="display:flex; gap:10px">
        <button class="ok" onclick="approvePolicy(${c.request_id})">Approve</button>
        <button class="danger" onclick="rejectPolicy(${c.request_id})">Reject</button>
      </div>
    </div>`;
  }).join("");
}

async function approvePolicy(id) {
  try { await api(`/api/merchant/policy-changes/${id}/approve`, { method: "POST" }); await refresh(); }
  catch (e) { toast(e.message, "err"); }
}
async function rejectPolicy(id) {
  try { await api(`/api/merchant/policy-changes/${id}/reject`, { method: "POST" }); await refresh(); }
  catch (e) { toast(e.message, "err"); }
}

const STRAT_LABEL = { balanced: "Balanced", aggressive: "Aggressive", firm: "Hold firm", clear_stock: "Clear stock" };

function prodCard(p) {
  const eff = Math.max(p.floor_price, p.list_price * (1 - p.max_discount_pct / 100));
  const floorPct = Math.max(4, Math.min(100, eff / p.list_price * 100));
  const low = p.stock < 20;
  return `<div class="prod-card">
    <div class="prod-head">
      <div style="min-width:0">
        <div class="prod-name">${esc(p.name)}</div>
        ${p.description ? `<div class="prod-desc">${esc(p.description)}</div>` : ""}
      </div>
      <label class="switch sm" title="Discoverable by AI buyers">
        <input type="checkbox" ${p.atoac_enabled ? "checked" : ""} onchange="quickToggleAtoac(${p.id}, this.checked)">
        <span class="slider"></span></label>
    </div>
    <div class="price-line">
      <div class="pl-track"><div class="pl-fill" style="width:${floorPct}%"></div>
        <div class="pl-band" style="left:${floorPct}%"></div></div>
      <div class="pl-labels"><span>Floor <strong>${inr(p.floor_price)}</strong></span>
        <span class="muted">negotiable</span><span>List <strong>${inr(p.list_price)}</strong></span></div>
    </div>
    <div class="chips">
      <span class="chip ${p.auto_negotiate === false ? "chip-manual" : "chip-ai"}">${p.auto_negotiate === false ? "✋ Manual" : "🤖 AI auto"}</span>
      <span class="chip strat strat-${p.strategy || "balanced"}">${STRAT_LABEL[p.strategy] || "Balanced"}</span>
      <span class="chip">≤ ${p.max_discount_pct}% off</span>
      <span class="chip">min ${p.min_order_qty}</span>
      <span class="chip">${p.max_negotiation_rounds} rounds</span>
    </div>
    <div class="prod-foot">
      <span class="stock-badge ${low ? "low" : ""}">${p.stock} in stock</span>
      <span class="muted small">${p.delivery_days}d delivery</span>
      <div class="prod-actions">
        <button class="ghost sm" onclick="editProduct(${p.id})">Edit</button>
        <button class="ghost sm danger-ghost" onclick="deleteProduct(${p.id})">Delete</button>
      </div>
    </div>
  </div>`;
}

async function loadProducts() {
  products = await api("/api/merchant/products");
  $("prodGrid").innerHTML = products.length
    ? products.map(prodCard).join("")
    : `<div class="empty">No products yet — add your first above.</div>`;
  const opts = products.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  $("u_base").innerHTML = opts; $("u_up").innerHTML = opts;
}

async function quickToggleAtoac(id, checked) {
  const p = products.find(x => x.id === id);
  if (!p) return;
  const body = { name: p.name, description: p.description || "", list_price: p.list_price,
    floor_price: p.floor_price, max_discount_pct: p.max_discount_pct, min_order_qty: p.min_order_qty,
    max_negotiation_rounds: p.max_negotiation_rounds, stock: p.stock, delivery_days: p.delivery_days,
    atoac_enabled: checked };
  try { await api(`/api/merchant/products/${id}`, { method: "PUT", body }); await loadProducts(); }
  catch (e) { toast(e.message, "err"); loadProducts(); }
}

const ICO = {
  chat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4 12 14.01l-3-3"/></svg>`,
  bag: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg>`,
  money: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`,
  cart: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>`,
  loop: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
  bulb: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z"/></svg>`,
};

function kpi(icClass, icon, label, value, sub, accent) {
  return `<div class="kpi" style="--kpi-accent:${accent}">
    <div class="top"><span class="ic ${icClass}">${icon}</span>${label}</div>
    <div class="val">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function donut(pct, color) {
  const r = 42, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(100, pct)) / 100);
  return `<svg viewBox="0 0 100 100" width="112" height="112" style="flex:0 0 auto">
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--panel3)" stroke-width="11"/>
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="${color}" stroke-width="11" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${off}" transform="rotate(-90 50 50)"
      style="transition:stroke-dashoffset .7s ease"/>
    <text x="50" y="50" text-anchor="middle" dominant-baseline="central" font-size="21"
      font-weight="800" fill="var(--text)">${pct}%</text></svg>`;
}

function hbar(label, pct, color, valText) {
  const w = Math.max(pct > 0 ? 3 : 0, Math.min(100, pct));
  return `<div class="bar-row"><div class="bar-label">${label}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${color}"></div></div>
    <div class="bar-val">${valText}</div></div>`;
}

function lineChart(vals, color) {
  if (!vals || vals.length < 2) return `<div class="empty small">Not enough closed deals yet for a trend.</div>`;
  const w = 600, h = 130, pad = 10;
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const X = (i) => pad + i * (w - 2 * pad) / (vals.length - 1);
  const Y = (v) => h - pad - (v - min) / span * (h - 2 * pad);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const area = `${d} L${X(vals.length - 1).toFixed(1)} ${h - pad} L${X(0).toFixed(1)} ${h - pad} Z`;
  return `<div class="linechart"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:${h}px">
    <path d="${area}" fill="${color}" opacity="0.12"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg></div>`;
}

async function loadAnalytics() {
  const a = await api("/api/merchant/analytics");
  const o = a.overview;
  $("stats").innerHTML =
    kpi("ic-indigo", ICO.chat, "Negotiations", o.negotiation_count, `${o.agreed_count} agreed`, "var(--accent)") +
    kpi("ic-green", ICO.check, "Success rate", o.success_rate_pct + "%", `${o.agreed_count} of ${o.negotiation_count} closed`, "var(--green)") +
    kpi("ic-violet", ICO.bag, "Confirmed orders", o.confirmed_orders, "paid &amp; fulfilled", "var(--violet)") +
    kpi("ic-cyan", ICO.money, "GMV", inr(o.gmv), "confirmed revenue", "var(--cyan)") +
    kpi("ic-amber", ICO.cart, "Avg order value", inr(o.aov), "per confirmed order", "var(--amber)");

  // Revenue opportunities — one-click policy actions first, then text insights
  const actions = (a.policy_actions || []).map(x => `
    <div class="reco action">
      <span class="dot">${ICO.bulb}</span>
      <div style="flex:1">
        <div style="display:flex; justify-content:space-between; gap:10px; align-items:center">
          <strong>${x.title}</strong>
          <button class="ok sm" onclick="applySuggestion(${x.product_id}, ${x.suggested})">Apply →</button>
        </div>
        <p class="small muted" style="margin:5px 0 0">${x.detail}
          <span class="tag">floor ${inr(x.current)} → ${inr(x.suggested)}</span></p>
      </div>
    </div>`).join("");
  const recos = a.recommendations.map(r => `
    <div class="reco">
      <span class="dot">${ICO.bulb}</span>
      <div style="flex:1">
        <div style="display:flex; justify-content:space-between; gap:10px; align-items:center">
          <strong>${r.title}</strong>
          ${r.expected_impact_inr ? `<span class="pill agreed">~${inr(r.expected_impact_inr)} impact</span>` : ""}
        </div>
        <p class="small muted" style="margin:5px 0 0">${r.detail}</p>
      </div>
    </div>`).join("");
  $("recos").innerHTML = actions + recos;

  // Closing price trend
  if ($("priceTrend")) {
    const prices = (a.price_trend || []).map(p => p.price);
    $("priceTrend").innerHTML = lineChart(prices, "var(--accent)") +
      (prices.length >= 2 ? `<div class="pl-labels" style="margin-top:8px">
        <span>${prices.length} recent deals</span><span>${inr(Math.min(...prices))} – ${inr(Math.max(...prices))}</span></div>` : "");
  }

  // Overview charts: close-rate donut + outcomes bars
  const ni = a.negotiation_intelligence;
  const denied = ni.objections.reduce((s, x) => s + x.count, 0);
  const negg = Math.max(0, o.negotiation_count - o.agreed_count - denied);
  if ($("donut")) $("donut").innerHTML = donut(o.success_rate_pct, "var(--green)") +
    `<div class="donut-legend">
      <div class="lg"><span class="sw" style="background:var(--green)"></span>${o.agreed_count} agreed</div>
      <div class="lg"><span class="sw" style="background:var(--panel3)"></span>${o.negotiation_count - o.agreed_count} not closed</div>
    </div>`;
  if ($("outcomes")) {
    const mx = o.negotiation_count || 1;
    $("outcomes").innerHTML =
      hbar("Agreed", o.agreed_count / mx * 100, "var(--green)", o.agreed_count) +
      hbar("Negotiating", negg / mx * 100, "var(--amber)", negg) +
      hbar("Denied", denied / mx * 100, "var(--red)", denied);
  }

  // Negotiation intelligence — closing prices + objections as bars
  const maxClose = Math.max(1, ...ni.closing_by_product.map(c => c.max_close_price));
  const closing = ni.closing_by_product.length
    ? ni.closing_by_product.map(c =>
        hbar(`${c.product} <span class="faint">(${c.deals})</span>`, c.avg_close_price / maxClose * 100,
             "var(--accent)", inr(c.avg_close_price))).join("")
    : `<p class="muted small">No closed deals yet.</p>`;
  const maxObj = Math.max(1, ...ni.objections.map(x => x.count));
  const objections = ni.objections.length
    ? ni.objections.map(x => hbar(reasonLabel(x.reason_code),
        x.count / maxObj * 100, "var(--red)", x.count)).join("")
    : `<span class="muted small">None — every negotiation closed.</span>`;
  $("negIntel").innerHTML = `
    <div class="small muted" style="margin-bottom:10px">Discount spread
      ${ni.min_discount_pct}%–${ni.max_discount_pct}% · avg <strong>${ni.avg_discount_pct}%</strong></div>
    <h3>Avg closing price by product</h3>${closing}
    <h3 style="margin-top:14px">Why deals didn't close</h3>${objections}`;

  // Upsell intelligence — attach-rate progress bars
  const ui = a.upsell_intelligence;
  $("upsellIntel").innerHTML = `
    <div class="small muted" style="margin-bottom:6px">Cross-sell revenue
      <strong>${inr(ui.total_cross_sell_revenue)}</strong></div>
    ${ui.rules.length ? ui.rules.map(r => `
      <div style="margin-top:14px">
        <div class="small" style="margin-bottom:5px">${r.base_product} → <strong>${r.upsell_product}</strong></div>
        ${hbar("attach rate", r.acceptance_rate_pct, "var(--violet)", r.acceptance_rate_pct + "%")}
        <div class="faint small" style="margin-top:3px">${r.accepted}/${r.offered} accepted · ${inr(r.revenue)}</div>
      </div>`).join("")
      : `<p class="muted small" style="margin-top:8px">No upsell rules configured.</p>`}`;

  // Recent negotiations
  $("recentNegs").innerHTML =
    `<tr><th>Product</th><th>Qty</th><th>Status</th><th>Reason</th><th>Unit</th><th>Total</th><th>Rounds</th></tr>` +
    (a.recent_negotiations.length ? a.recent_negotiations.map(n => `
      <tr>
        <td>${n.product || "—"}</td><td>${n.quantity}</td>
        <td><span class="pill ${n.status === "AGREED" ? "agreed" : "denied"}">${n.status}</span></td>
        <td class="small muted">${reasonLabel(n.reason_code)}</td>
        <td>${inr(n.final_unit_price)}</td><td>${inr(n.total)}</td><td>${n.rounds}</td>
      </tr>`).join("") : `<tr><td colspan="7" class="muted">No negotiations yet.</td></tr>`);
}

async function loadRules() {
  const rules = await api("/api/merchant/upsell-rules");
  const name = (id) => (products.find(p => p.id === id) || {}).name || `#${id}`;
  $("ruleList").innerHTML = rules.length
    ? rules.map(r => `
      <div class="rule-card">
        <div class="rule-flow">
          <span class="rf-base">${esc(name(r.base_product_id))}</span>
          <span class="rf-arrow"><span class="rf-qty">≥ ${r.trigger_min_qty}</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 12h14M13 6l6 6-6 6"/></svg></span>
          <span class="rf-up">${esc(name(r.upsell_product_id))}</span>
        </div>
        <button class="ghost sm danger-ghost" onclick="deleteRule(${r.id})">Remove</button>
      </div>`).join("")
    : `<div class="empty small">No upsell rules yet.</div>`;
}

async function deleteRule(id) {
  try { await api(`/api/merchant/upsell-rules/${id}`, { method: "DELETE" }); await loadRules(); }
  catch (e) { toast(e.message, "err"); }
}

function auditColor(a) {
  if (/agreed|confirmed|approved|create/.test(a)) return "ok";
  if (/denied|failed|rejected|delete/.test(a)) return "bad";
  if (/proposed|shortfall|update/.test(a)) return "warn";
  return "";
}
function auditDetail(d) {
  if (!d) return "";
  const parts = [];
  for (const [k, v] of Object.entries(d)) {
    if (v == null || typeof v === "object") continue;
    parts.push(`${k.replace(/_/g, " ")}: ${v}`);
    if (parts.length >= 3) break;
  }
  return parts.join(" · ");
}
async function loadAudit() {
  const events = await api("/api/merchant/audit");
  $("audit").innerHTML = events.length
    ? `<div class="timeline">` + events.map(e => {
        const t = new Date(e.timestamp).toLocaleString();
        const det = auditDetail(e.details);
        return `<div class="tl-item"><span class="tl-dot ${auditColor(e.action)}"></span>
          <div class="tl-body">
            <div class="tl-top"><span class="tl-action">${e.action}</span><span class="tl-time">${t}</span></div>
            <div class="tl-detail"><strong>${esc(e.actor)}</strong>${det ? " · " + esc(det) : ""}</div>
          </div></div>`;
      }).join("") + `</div>`
    : `<div class="empty small">No activity yet.</div>`;
}

function productBody() {
  return {
    name: $("p_name").value.trim(),
    description: $("p_desc").value.trim(),
    list_price: parseFloat($("p_list").value),
    floor_price: parseFloat($("p_floor").value),
    max_discount_pct: parseFloat($("p_disc").value),
    min_order_qty: parseInt($("p_minq").value, 10),
    max_negotiation_rounds: parseInt($("p_rounds").value, 10),
    stock: parseInt($("p_stock").value, 10),
    delivery_days: parseInt($("p_deliv").value, 10),
    strategy: $("p_strategy").value,
    atoac_enabled: $("p_atoac").checked,
    auto_negotiate: $("p_autoneg").checked,
  };
}

$("saveProd").onclick = async () => {
  notice($("prodMsg"), "");
  try {
    const body = productBody();
    let resp;
    if (editId) resp = await api(`/api/merchant/products/${editId}`, { method: "PUT", body });
    else resp = await api("/api/merchant/products", { method: "POST", body });
    const queued = resp && resp.pending_policy_change;
    resetForm();
    await refresh();
    if (queued) notice($("prodMsg"),
      "Material policy change queued — approve it below to take effect.", "ok");
  } catch (e) { notice($("prodMsg"), e.message); }
};

function editProduct(id) {
  const p = products.find(x => x.id === id);
  editId = id;
  $("p_name").value = p.name; $("p_desc").value = p.description || "";
  $("p_list").value = p.list_price; $("p_floor").value = p.floor_price;
  $("p_disc").value = p.max_discount_pct; $("p_minq").value = p.min_order_qty;
  $("p_rounds").value = p.max_negotiation_rounds; $("p_stock").value = p.stock;
  $("p_deliv").value = p.delivery_days; $("p_atoac").checked = p.atoac_enabled;
  $("p_autoneg").checked = p.auto_negotiate !== false;
  $("p_strategy").value = p.strategy || "balanced";
  $("prodFormTitle").textContent = "Edit " + p.name;
  $("cancelEdit").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("cancelEdit").onclick = resetForm;
function resetForm() {
  editId = null;
  ["p_name", "p_desc", "p_list", "p_floor"].forEach(id => $(id).value = "");
  $("p_atoac").checked = true; $("p_autoneg").checked = true; $("p_strategy").value = "balanced";
  $("prodFormTitle").textContent = "Add product";
  $("cancelEdit").classList.add("hidden");
  notice($("prodMsg"), "");
}

async function deleteProduct(id) {
  if (!confirm("Delete this product?")) return;
  try { await api(`/api/merchant/products/${id}`, { method: "DELETE" }); await refresh(); }
  catch (e) { toast(e.message, "err"); }
}

$("addRule").onclick = async () => {
  try {
    await api("/api/merchant/upsell-rules", {
      method: "POST",
      body: {
        base_product_id: parseInt($("u_base").value, 10),
        upsell_product_id: parseInt($("u_up").value, 10),
        trigger_min_qty: parseInt($("u_qty").value, 10),
      },
    });
    await loadRules();
  } catch (e) { toast(e.message, "err"); }
};

refresh();
connectNotifications();
