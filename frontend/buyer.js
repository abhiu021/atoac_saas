// Buyer portal — a single conversational surface. You describe what you want in
// natural language; the concierge parses it (NLP), finds merchants, and you
// negotiate with them right here in the thread, also in natural language.
const user = requireRole("buyer");
if (user) {
  document.getElementById("who").textContent = user.email;
  const av = document.getElementById("bavatar");
  if (av) av.textContent = (user.email[0] || "B").toUpperCase();
}

const $ = (id) => document.getElementById(id);
const inr = (n) => n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN");
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// A generated product thumbnail (we don't store images): a keyword icon on a
// deterministic soft tint, so each product gets a stable, distinct "photo".
const PROD_ICONS = [
  [/chair|seat|stool|sofa/, "🪑"], [/mat|rug|carpet/, "🟫"], [/desk|desh|table/, "🖥️"],
  [/lamp|light|bulb/, "💡"], [/monitor|screen|display/, "🖥️"], [/cable|charger|wire|adapter/, "🔌"],
  [/bottle|flask|mug|cup/, "🍶"], [/pipe|tube|pvc/, "🧵"], [/paper|notebook|pad|book/, "📒"],
  [/pen|marker|pencil/, "🖊️"], [/bag|pack|pouch/, "🎒"], [/shoe|boot|sneaker/, "👟"],
  [/phone|mobile|tablet/, "📱"], [/box|carton|crate/, "📦"], [/keyboard|mouse/, "⌨️"],
];
const THUMB_TINTS = ["#fff0e2", "#eef4ff", "#eafaf1", "#fdf0f4", "#f3f0ff", "#fff7e6"];
function prodIcon(name) {
  const s = (name || "").toLowerCase();
  for (const [re, ic] of PROD_ICONS) if (re.test(s)) return ic;
  return "📦";
}
function prodThumb(product) {
  // product can be either a string (name) or an object with image_url
  const isObject = typeof product === 'object';
  const name = isObject ? product.name : product;
  const imageUrl = isObject ? product.image_url : null;
  
  if (imageUrl) {
    return `<div class="cand-thumb" style="border: 1px solid var(--line2);"><img src="${imageUrl}" alt="" data-product-name="${esc(name)}" onerror="this.onerror=null;this.style.display='none';this.parentElement.classList.add('image-missing');this.parentElement.textContent=prodIcon(this.dataset.productName);" style="width: 100%; height: 100%; object-fit: cover; border-radius: 8px;"></div>`;
  }
  
  let h = 0; for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `<div class="cand-thumb" style="background:${THUMB_TINTS[h % THUMB_TINTS.length]}">${prodIcon(name)}</div>`;
}

const S = {
  phase: "idle",            // idle | clarify | merchants | negotiating | upsell | checkout | done
  rfq: { query: null, quantity: null, target_price: null, max_delivery_days: null },
  candidates: [], usedMerchants: [],
  activeNeg: null, activeMerchant: null, lastSeq: 0, ws: null,
  selectedNeg: null, agreement: null, upsell: null, multi: null, basket: null, orders: [],
  // Persistence / chat history
  convUid: null, items: [], chatList: [], currentTitle: "New chat", saveTimer: null, replaying: false,
};

function negWsUrl(uid) {
  const p = location.protocol === "https:" ? "wss" : "ws";
  return `${p}://${location.host}/ws/negotiations/${uid}?token=${encodeURIComponent(getToken())}`;
}

const thread = $("threadInner");
const scroll = () => { const t = $("thread"); t.scrollTop = t.scrollHeight; };

// `storeHtml` is the version persisted to history (buttons stripped for replay).
function row(kind, avatar, name, html, storeHtml) {
  const r = document.createElement("div");
  r.className = "msg " + kind;
  r.innerHTML = `<div class="av">${avatar}</div><div class="body">
    ${name ? `<div class="name">${name}</div>` : ""}<div class="bubble2">${html}</div></div>`;
  thread.appendChild(r); scroll();
  if (!S.replaying) { S.items.push({ t: "row", kind, avatar, name, html: storeHtml != null ? storeHtml : html }); scheduleSave(); }
  return r.querySelector(".bubble2");
}
const assistant = (html, storeHtml) => row("assistant", "A", "ATOAC", html, storeHtml);
const buyerMsg = (html) => row("user", "You", "", html);
const merchantMsg = (name, html) => row("merchant", "M", esc(name), html);
function systemChip(text) {
  const d = document.createElement("div"); d.className = "sys-chip"; d.textContent = text;
  thread.appendChild(d); scroll();
  if (!S.replaying) { S.items.push({ t: "sys", text }); scheduleSave(); }
}
let typingEl = null;
function typing(on) {
  if (on && !typingEl) {
    typingEl = document.createElement("div");
    typingEl.className = "msg assistant";
    typingEl.innerHTML = `<div class="av">A</div><div class="body"><div class="name">ATOAC</div>
      <div class="bubble2"><span class="typing-dots"><span></span><span></span><span></span></span></div></div>`;
    thread.appendChild(typingEl); scroll();
  } else if (!on && typingEl) { typingEl.remove(); typingEl = null; }
}
function hint(t) { $("turnHint").textContent = t || ""; }

// ---- Persistence + chat history ----
function scheduleSave() { if (S.saveTimer) clearTimeout(S.saveTimer); S.saveTimer = setTimeout(saveNow, 450); }
function deriveTitle() {
  const firstUser = S.items.find(i => i.t === "row" && i.kind === "user");
  return firstUser ? (firstUser.html.replace(/<[^>]+>/g, "").trim().slice(0, 60) || "New chat") : "New chat";
}
async function saveNow() {
  if (!S.convUid) return;
  const title = deriveTitle();
  const changed = title !== S.currentTitle;
  S.currentTitle = title;
  try { await api(`/api/buyer/conversations/${S.convUid}`, { method: "PUT", body: { title, items: S.items } }); } catch (e) {}
  if (changed) refreshChatList();
}
function clearThread() { thread.innerHTML = ""; typingEl = null; }
function resetConvState() {
  if (S.ws) { S.ws.close(); S.ws = null; }
  if (S.multi) { (S.multi.ws || []).forEach(w => { try { w.close(); } catch (e) {} }); S.multi = null; }
  if (S.basket) { S.basket.lines.forEach(L => L.ws.forEach(w => { try { w.close(); } catch (e) {} })); S.basket = null; }
  S.phase = "idle"; S.rfq = { query: null, quantity: null, target_price: null, max_delivery_days: null };
  S.candidates = []; S.usedMerchants = []; S.activeNeg = null; S.activeMerchant = null; S.lastSeq = 0;
  S.selectedNeg = null; S.agreement = null; S.upsell = null; hint("");
  const b = $("assistToggle"); if (b) b.style.display = "none";
}
async function refreshChatList() {
  try { S.chatList = await api("/api/buyer/conversations"); } catch (e) { S.chatList = []; }
  renderChatList();
}
function renderChatList() {
  const host = $("chatList"); if (!host) return;
  host.innerHTML = S.chatList.map(c => `
    <div class="chat-item ${c.uid === S.convUid ? "active" : ""}" onclick="openChatItem('${c.uid}')">
      <span class="title">${esc(c.title || "New chat")}</span>
      <span class="del" onclick="deleteChat(event,'${c.uid}')" title="Delete">✕</span>
    </div>`).join("") || `<div class="faint small" style="padding:8px 10px">No chats yet</div>`;
}
window.openChatItem = (uid) => { if (uid !== S.convUid) loadConversation(uid); };
window.deleteChat = async (ev, uid) => {
  ev.stopPropagation();
  try { await api(`/api/buyer/conversations/${uid}`, { method: "DELETE" }); } catch (e) {}
  if (uid === S.convUid) await startFresh(); else await refreshChatList();
};
async function newChat() {
  const c = await api("/api/buyer/conversations", { method: "POST" });
  S.convUid = c.uid; S.items = []; S.currentTitle = "New chat";
  resetConvState(); clearThread(); greeting();
  await refreshChatList();
}
async function loadConversation(uid) {
  const c = await api(`/api/buyer/conversations/${uid}`);
  S.convUid = c.uid; S.items = c.items || []; S.currentTitle = c.title || "New chat";
  resetConvState(); clearThread(); replay(S.items); renderChatList(); scroll();
}
function replay(items) {
  S.replaying = true;
  for (const it of items) {
    if (it.t === "sys") systemChip(it.text);
    else row(it.kind, it.avatar, it.name, it.html);
  }
  S.replaying = false;
}
async function startFresh() {
  await refreshChatList();
  if (S.chatList.length) await loadConversation(S.chatList[0].uid);
  else await newChat();
}
function greeting() {
  const chips = [
    "I need 50 ergonomic chairs under ₹4,300 each, within a week",
    "30 desk mats under ₹220 each",
    "40 chairs at ₹4,300 and 30 desk mats at ₹220",
    "Show my orders",
  ];
  const chipHtml = chips.map(c => `<button class="sugg-chip" onclick="quickPrompt(this)">${esc(c)}</button>`).join("");
  assistant(
    `What do you need? Describe it in plain English, or try one:
     <div class="sugg-row">${chipHtml}</div>`,
    `What do you need? Describe it in plain English.`);
}
window.quickPrompt = (btn) => { input.value = btn.textContent; onSend(); };
if ($("newChat")) $("newChat").onclick = () => newChat();

// ---- Composer ----
const input = $("composer");
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } });
$("send").onclick = onSend;

async function onSend() {
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; autosize();
  if (S.phase === "negotiating") { await negotiationSay(text); return; }
  buyerMsg(esc(text));
  await concierge(text);
}

// Is this a general/off-topic question rather than a buying request?
function looksLikeQuestion(low) {
  const s = (low || "").trim();
  if (/\?\s*$/.test(s)) return true;
  return /^(what|whats|how|why|who|when|where|which|can you (tell|explain|help)|could you|tell me|explain|do you|does|is |are |should|help\b|hi\b|hello|hey|thanks|thank you)/.test(s);
}
function hasBuyingSignal(low) {
  return /\d/.test(low) || /\b(buy|need|want|order|source|purchase|procure|find me|looking for|get me|rfq|quote|reorder)\b/.test(low);
}

// Free-form Q&A — the assistant answers general questions conversationally.
async function askAssistant(text) {
  typing(true);
  let res;
  try { res = await api("/api/buyer/ask", { method: "POST", body: { message: text } }); }
  catch (e) { typing(false); assistant("Sorry, I couldn't answer that just now — but tell me what you'd like to buy and I'll get to work."); return; }
  typing(false);
  assistant(esc(res.answer || "").replace(/\n/g, "<br>"), res.answer || "");
}

// ---- Concierge (discovery + orchestration) ----
async function concierge(text) {
  const low = text.toLowerCase();

  if (/\b(my )?orders?\b|order history|past (orders|purchases)|my purchases/.test(low)) {
    return showOrders();
  }

  if (S.phase === "upsell") {
    if (/\b(yes|yeah|sure|ok|okay|add|please|do it|go ahead)\b/.test(low)) return finalizeAgreement(true);
    if (/\b(no|nope|skip|without|don'?t|not)\b/.test(low)) return finalizeAgreement(false);
    assistant(`Shall I add the <strong>${esc(S.upsell.name)}</strong>? (yes / no)`); return;
  }
  if (S.phase === "checkout") {
    if (/\b(pay|checkout|proceed|confirm|yes|go)\b/.test(low)) return runCheckout();
    assistant(`Say <strong>“checkout”</strong> to pay now, or ask me anything.`); return;
  }
  if (S.phase === "compared") {
    if (/\b(yes|go|proceed|ok|okay|lock|do it|sure|best)\b/.test(low)) return proceedWithWinner();
    // otherwise fall through to treat as a new request
  }
  if (S.phase === "merchants") {
    if (/\b(all|everyone|compare|both|cheapest|best|lowest)\b/.test(low) || /negotiate all/.test(low))
      return negotiateAll(S.candidates);
    const pick = matchCandidate(low);
    if (pick) return startNeg(pick);
    if (!/\d/.test(low) && !/(chair|mat|desk|product|item)/.test(low) && !looksLikeQuestion(low)) {
      assistant(`Say “negotiate all” to compare them, name a merchant, or describe a new request.`); return;
    }
    // otherwise fall through and re-parse as a fresh/updated request
  }
  if (S.phase === "done") S.rfq = { query: null, quantity: null, target_price: null, max_delivery_days: null };

  // General/off-topic question (not a buying request)? Answer it conversationally.
  if (looksLikeQuestion(low) && !hasBuyingSignal(low)) return askAssistant(text);

  // Multi-item? If the message names ≥2 distinct line items, negotiate each line
  // in parallel and check them out as one basket. Single-item falls through below.
  if (S.phase !== "clarify") {
    try {
      const bk = await api("/api/buyer/basket-intent", { method: "POST", body: { message: text } });
      if (bk.lines && bk.lines.length >= 2) return startBasket(bk.lines);
    } catch (e) { /* fall through to single-item parsing */ }
  }

  S._t0 = Date.now();
  typing(true);
  let res;
  try { res = await api("/api/buyer/intent", { method: "POST", body: { message: text } }); }
  catch (e) { typing(false); assistant("Sorry, I couldn't parse that — try again?"); return; }
  typing(false);
  for (const k of Object.keys(S.rfq)) if (res.rfq[k] != null) S.rfq[k] = res.rfq[k];

  // We understood the request — present AI-Mode next actions (Alibaba style).
  showAiActions();
}

// ---- AI Mode: an agent header with an expandable "Worked for Ns" trace, then a
// menu of next actions the buyer can pick (auto-run, clarify, or just find). ----
function aiTraceHtml(steps) {
  const elapsed = Math.max(1, Math.round((Date.now() - (S._t0 || Date.now())) / 1000));
  const rows = steps.map(s => `<div class="ai-step"><span class="ai-step-ic">${s.ic || "›_"}</span>
      <span class="ai-step-l">${esc(s.label)}</span>${s.detail ? `<span class="ai-step-d">${esc(s.detail)}</span>` : ""}</div>`).join("");
  return `<div class="ai-worked" onclick="this.classList.toggle('open')">
      <span class="ai-chev">›</span> Worked for ${elapsed}s
      <div class="ai-steps" onclick="event.stopPropagation()">${rows}</div>
    </div>`;
}

function showAiActions() {
  const q = S.rfq;
  if (!q.query) { S.phase = "idle"; assistant(`What would you like to source? Just name the product — e.g. “ergonomic chairs” or “desk mats”.`); return; }
  const steps = [{ ic: "✦", label: "Understood your request" }, { ic: "›_", label: "Detected product", detail: q.query }];
  if (q.quantity) steps.push({ ic: "›_", label: "Quantity", detail: `${q.quantity} units` });
  if (q.target_price) steps.push({ ic: "›_", label: "Target price", detail: `${inr(q.target_price)}/unit` });
  if (q.max_delivery_days) steps.push({ ic: "›_", label: "Delivery window", detail: `${q.max_delivery_days} days` });
  steps.push({ ic: "✓", label: "Ready to source" });

  const actions = [
    { icon: "→", title: "Auto-run sourcing", sub: "Find merchants, negotiate all, and recommend the best", fn: "aiAuto" },
    { icon: "→", title: "Clarify requirements", sub: "Answer a few quick questions — quantity, budget, delivery", fn: "aiGuided" },
    { icon: "→", title: "Just find merchants", sub: "See who's available and negotiate them yourself", fn: "aiFind" },
  ].map(r => `<button class="ai-action" onclick="${r.fn}()">
      <span class="ai-a-ic">${r.icon}</span>
      <span class="ai-a-txt"><span class="ai-a-t">${r.title}</span><span class="ai-a-s">${r.sub}</span></span>
      <span class="ai-a-arrow">→</span></button>`).join("");

  S.phase = "actions";
  assistant(
    `<div class="ai-head"><span class="ai-spark">✦</span> Next Steps</div>
     ${aiTraceHtml(steps)}
     <div class="ai-lead">For <strong>${esc(q.query)}</strong>${q.quantity ? ` × ${q.quantity}` : ""} — choose an option:</div>
     <div class="ai-actions">${actions}</div>`,
    `Ready to source "${esc(q.query)}". Choose: auto-run sourcing, clarify requirements, or find merchants.`);
}

// Quantity is essential for search/negotiation; target is optional (defaults to ~10% off cheapest list).
function needClarify() { return S.rfq.quantity == null; }
window.aiAuto = () => { if (needClarify()) return startGuided("auto"); buyerMsg("Starting auto-run sourcing..."); doSearch(true); };
window.aiFind = () => { if (needClarify()) return startGuided("find"); buyerMsg("Finding merchants..."); doSearch(false); };
window.aiGuided = () => startGuided(null);

// ---- Guided requirement collection: one stepped question card at a time. ----
function startGuided(after) {
  S.phase = "guided";
  const steps = [
    { key: "quantity", tag: "Quantity", q: "How many units do you need?", type: "chips",
      options: [{ l: "25", v: 25 }, { l: "50", v: 50 }, { l: "100", v: 100 }, { l: "250", v: 250 }], custom: "number", ph: "e.g. 80" },
    { key: "target_price", tag: "Budget", q: "What's your target price per unit? (optional)", type: "number", ph: "e.g. 4300", skip: true },
    { key: "max_delivery_days", tag: "Delivery", q: "How soon do you need it?", type: "chips",
      options: [{ l: "3 days", v: 3 }, { l: "1 week", v: 7 }, { l: "2 weeks", v: 14 }, { l: "Any", v: null }], skip: true },
  ];
  if (!after) steps.push({ key: "method", tag: "Method", q: "How should I proceed?", type: "choice",
    options: [
      { l: "Negotiate & compare", d: "Negotiate with every merchant in parallel, then recommend the best deal", v: "auto" },
      { l: "Just find merchants", d: "Show who's available and let me choose who to negotiate", v: "find" }] });
  S.guided = { steps, i: 0, ans: {}, after, el: rawBubble("") };
  renderGuided();
}

function renderGuided() {
  const G = S.guided, s = G.steps[G.i], total = G.steps.length;
  const dots = G.steps.map((_, k) => `<span class="gq-dot${k === G.i ? " on" : ""}${k < G.i ? " done" : ""}"></span>`).join("");
  let body = "";
  if (s.type === "chips") {
    body = `<div class="gq-chips">${s.options.map(o => `<button class="gq-chip" onclick='guidedPick("${s.key}", ${JSON.stringify(o.v)})'>${esc(o.l)}</button>`).join("")}</div>`;
    if (s.custom === "number") body += `<div class="gq-custom"><input type="number" min="1" class="gq-input" placeholder="${s.ph || "Custom"}"><button class="ok sm" onclick='guidedCustom("${s.key}")'>Set</button></div>`;
  } else if (s.type === "number") {
    body = `<div class="gq-custom"><input type="number" min="1" class="gq-input" placeholder="${s.ph || ""}" value="${G.ans[s.key] != null ? G.ans[s.key] : ""}"><button class="ok sm" onclick='guidedCustom("${s.key}")'>Continue</button></div>`;
  } else if (s.type === "choice") {
    body = `<div class="gq-choices">${s.options.map(o => `<button class="gq-choice" onclick='guidedPick("${s.key}", ${JSON.stringify(o.v)})'><span class="gq-c-t">${esc(o.l)}</span><span class="gq-c-d">${esc(o.d)}</span></button>`).join("")}</div>`;
  }
  G.el.innerHTML = `<div class="guided-card">
    <div class="gq-top"><span class="gq-title">A few quick questions</span>
      <span class="gq-prog">${dots}<span class="gq-num">${G.i + 1}/${total}</span></span></div>
    <div class="gq-tag">${esc(s.tag)}</div>
    <div class="gq-q">${esc(s.q)}</div>
    ${body}
    <div class="gq-foot">
      ${G.i > 0 ? `<button class="ghost sm" onclick="guidedPrev()">‹ Previous</button>` : `<span></span>`}
      ${s.skip ? `<button class="ghost sm" onclick="guidedSkip()">Skip ›</button>` : `<span></span>`}
    </div></div>`;
  scroll();
}

function guidedAdvance() {
  const G = S.guided;
  if (G.i < G.steps.length - 1) { G.i++; renderGuided(); } else finishGuided();
}
window.guidedPick = (key, val) => { S.guided.ans[key] = val; guidedAdvance(); };
window.guidedSkip = () => guidedAdvance();
window.guidedPrev = () => { if (S.guided.i > 0) { S.guided.i--; renderGuided(); } };
window.guidedCustom = (key) => {
  const inp = S.guided.el.querySelector(".gq-input");
  const v = parseFloat(inp.value);
  if (!(v > 0)) return toast("Enter a number.", "err");
  S.guided.ans[key] = key === "quantity" ? Math.round(v) : v;
  guidedAdvance();
};

function finishGuided() {
  const G = S.guided, a = G.ans;
  if (a.quantity != null) S.rfq.quantity = a.quantity;
  if (a.target_price != null) S.rfq.target_price = a.target_price;
  if ("max_delivery_days" in a) S.rfq.max_delivery_days = a.max_delivery_days;  // null = any
  if (S.rfq.quantity == null) { toast("I still need a quantity.", "err"); G.i = 0; return renderGuided(); }
  const method = G.after || a.method || "auto";
  const summary = `${S.rfq.quantity} × ${S.rfq.query}${S.rfq.target_price ? ` at ${inr(S.rfq.target_price)}/unit` : ""}${S.rfq.max_delivery_days ? `, within ${S.rfq.max_delivery_days}d` : ""}`;
  buyerMsg(esc((method === "find" ? "Find merchants — " : "Auto-run sourcing — ") + summary));
  doSearch(method !== "find");
}

async function doSearch(auto) {
  const q = S.rfq;
  const p = new URLSearchParams({ query: q.query, quantity: q.quantity });
  if (q.max_delivery_days != null) p.set("max_delivery_days", q.max_delivery_days);
  typing(true);
  let data;
  try { data = await api("/api/buyer/search?" + p.toString()); }
  catch (e) { typing(false); assistant(e.message); return; }
  typing(false);
  S.candidates = data.candidates;
  if (!data.candidates.length) {
    S.phase = "idle";
    assistant(`I couldn't find any ATOAC-enabled merchant for that. Try a different item, a higher
      target price, or a longer delivery window.`);
    return;
  }
  // No target given? Aim ~10% under the cheapest list so the agent has room to negotiate.
  if (S.rfq.target_price == null) S.rfq.target_price = Math.round(Math.min(...data.candidates.map(c => c.list_price)) * 0.9);
  // Auto-run: skip the candidate picker and negotiate everyone in parallel.
  if (auto) return negotiateAll(data.candidates);
  const many = data.candidates.length > 1;
  const qty = S.rfq.quantity || 1;
  const cards = data.candidates.map((c, i) => {
    const inStock = c.stock >= qty;
    const cardId = `candidate-${i}`;
    return `
    <div class="cand" id="${cardId}">
      ${many ? `<input type="checkbox" class="cand-check" data-i="${i}" checked onchange="updateSelCount()" title="Include in comparison">` : ""}
      ${prodThumb(c)}
      <div class="cand-info">
        <div class="cand-prod" onclick="viewProductDetail('${c.id || i}', ${i})" style="cursor: pointer; color: var(--accent);">
          ${esc(c.name)} →
        </div>
        <div class="cand-merch" onclick="viewMerchantDetail('${c.merchant_id || c.merchant_name}', ${i})" style="cursor: pointer; color: var(--accent);">
          ${esc(c.merchant_name)} <span class="cand-verified">✓ Verified</span>
        </div>
        ${c.description ? `<div class="cand-desc">${esc(c.description)}</div>` : ""}
        <div class="cand-meta">
          <span class="cm"><b>${inr(c.list_price)}</b> list</span>
          <span class="cm">Delivery: ${c.delivery_days}d</span>
          <span class="cm">MOQ ${c.min_order_qty}</span>
          <span class="cm stock ${inStock ? "ok" : "low"}">${inStock ? "In stock" : `${c.stock} left`}</span>
        </div>
      </div>
      <div class="cand-actions">
        <button class="ghost sm" onclick="pickCandidate(${i})" title="You make the offers">My Offer</button>
        <button class="ok sm" onclick="agentOne(${i})" title="Let your agent negotiate this one">Agent Negotiate</button>
      </div>
    </div>`;
  }).join("");
  S.phase = "merchants";
  const selBtn = many
    ? `<button class="ok sm" id="negSelBtn" style="margin:0 0 10px" onclick="negotiateSelected()">Compare Selected Merchants (${data.candidates.length})</button>`
    : "";
  assistant(`I found <strong>${data.candidates.length}</strong> merchant(s) with matching products:<div class="rich">${selBtn}${cards}</div>
    <div class="faint small" style="margin-top:6px">Per merchant: <strong>My Offer</strong> = you negotiate directly · <strong>Agent Negotiate</strong> = AI agent handles it.${many ? " Or select several and tap <strong>Compare</strong> above." : " Click product/merchant name to see full details."}</div>`,
    `Found ${data.candidates.length} merchant(s): ${data.candidates.map(c => esc(c.merchant_name)).join(", ")}.`);
}

window.updateSelCount = () => {
  const n = document.querySelectorAll(".cand-check:checked").length;
  const b = $("negSelBtn"); if (b) b.textContent = `Compare Selected Merchants (${n})`;
};
window.negotiateSelected = () => {
  const sel = [...document.querySelectorAll(".cand-check:checked")].map(c => S.candidates[+c.dataset.i]);
  if (!sel.length) return toast("Tick at least one merchant.", "err");
  if (sel.length === 1) return startNeg(sel[0]);
  negotiateAll(sel);
};

// Navigate to product detail page
window.viewProductDetail = (productId, index) => {
  const product = S.candidates[index];
  if (!product) return toast("Product not found", "err");
  window.location.href = `/product-detail.html?id=${encodeURIComponent(product.id || productId)}`;
};

// Navigate to merchant detail page
window.viewMerchantDetail = (merchantId, index) => {
  const product = S.candidates[index];
  if (!product) return toast("Merchant not found", "err");
  window.location.href = `/merchant-detail.html?id=${encodeURIComponent(merchantId)}`;
};

function matchCandidate(low) {
  if (!S.candidates.length) return null;
  if (/\b(cheap|cheapest|best|lowest|first|recommend|any)\b/.test(low)) return S.candidates[0];
  for (const c of S.candidates) {
    const w = c.merchant_name.toLowerCase().split(/\s+/)[0];
    if (low.includes(w)) return c;
  }
  const n = low.match(/\b([1-9])\b/);
  if (n && S.candidates[+n[1] - 1]) return S.candidates[+n[1] - 1];
  return null;
}
window.pickCandidate = (i) => startNeg(S.candidates[i]);
window.agentOne = (i) => negotiateAll([S.candidates[i]]);  // let the agent negotiate one merchant
window.negotiateAllNow = () => negotiateAll(S.candidates);

// ---- Multi-merchant: negotiate all in parallel, compare, recommend ----
function rawBubble(html) {
  const r = document.createElement("div");
  r.className = "msg assistant";
  r.innerHTML = `<div class="av">A</div><div class="body"><div class="name">ATOAC</div><div class="bubble2">${html}</div></div>`;
  thread.appendChild(r); scroll();
  return r.querySelector(".bubble2");
}

function lastMerchantOffer(st) {
  for (let i = st.messages.length - 1; i >= 0; i--)
    if (st.messages[i].role === "merchant" && st.messages[i].unit_price != null) return st.messages[i].unit_price;
  return null;
}

// How much this negotiated price saves — total vs the merchant's list price, and
// per-unit vs the buyer's own target. Buyers judge outcomes by savings, not just totals.
function savingsChip(listPrice, unitPrice, qty, target) {
  if (listPrice == null || unitPrice == null) return "";
  const parts = [];
  const vsList = Math.round((listPrice - unitPrice) * (qty || 1));
  if (vsList > 0) parts.push(`${inr(vsList)} under list`);
  if (target != null && target - unitPrice >= 1) parts.push(`${inr(Math.round(target - unitPrice))}/u under target`);
  return parts.length ? `<div class="sb-save">↓ ${parts.join(" · ")}</div>` : "";
}

function renderBoard(M) {
  const rows = M.order.map(uid => {
    const x = M.states[uid], c = x.cand, st = x.st;
    let right, cls = "";
    if (!st) right = `<span class="muted small">starting…</span>`;
    else if (st.status === "NEGOTIATING") {
      const off = lastMerchantOffer(st);
      right = `<span class="live-dot"></span><span class="small muted">${off ? inr(off) + "/u" : "negotiating…"}</span>`;
    } else if (st.status === "AGREED") {
      right = `<div class="sb-price">${inr(st.total)}</div><div class="faint small">${inr(st.final_unit_price)}/u · ${st.rounds || 0} rnd</div>${savingsChip(c.list_price, st.final_unit_price, S.rfq.quantity, S.rfq.target_price)}`;
    } else { right = `<span class="pill denied">no deal</span>`; cls = "lost"; }
    const best = uid === M.winner ? " best" : "";
    const viewing = uid === M.viewing ? " viewing" : "";
    const canView = !!(st && st.messages && st.messages.length);
    return `<div class="sb-row${best} ${cls}${viewing}" ${canView ? `onclick="viewNegChat('${uid}')"` : ""}>
        <div class="sb-m"><strong>${esc(c.merchant_name)}</strong><div class="faint small">${c.delivery_days}d delivery</div></div>
        <div class="sb-r">${right}</div>
        ${uid === M.winner ? '<span class="sb-badge">best</span>' : ""}
        ${canView ? `<span class="sb-chev">${uid === M.viewing ? "⌄" : "›"}</span>` : ""}
      </div>${uid === M.viewing && canView ? sbTranscript(x) : ""}`;
  }).join("");
  const cta = M.winner
    ? `<div class="sb-cta"><button class="ok sm" onclick="proceedWithWinner()">Go with ${esc(M.states[M.winner].cand.merchant_name)} · ${inr(M.states[M.winner].st.total)}</button></div>`
    : "";
  return `<div class="scoreboard"><div class="sb-head">Negotiating with ${M.total} merchant(s) in parallel · tap a row to see the chat</div>${rows}${cta}</div>`;
}

function sbTranscript(x) {
  const st = x.st, mname = x.cand.merchant_name;
  const msgs = st.messages.filter(m => m.role !== "system");
  return `<div class="sb-transcript"><div class="sbt-title">${esc(mname)} — full negotiation</div>` +
    msgs.map(m => {
      const side = m.role === "buyer" ? "right" : "left";
      const price = m.unit_price != null ? ` <span class="price-chip">${inr(m.unit_price)}/u</span>` : "";
      const who = m.role === "buyer" ? "Buyer" : esc(mname);
      return `<div class="sbt-row ${side}"><div class="sbt-b ${m.role}"><div class="sbt-who">${who}</div><div>${esc(m.text)}${price}</div></div></div>`;
    }).join("") + `</div>`;
}

window.viewNegChat = (uid) => {
  const M = S.multi; if (!M) return;
  M.viewing = M.viewing === uid ? null : uid;
  M.board.innerHTML = renderBoard(M);
};

async function negotiateAll(cands) {
  if (!cands || !cands.length) return;
  if (S.ws) { S.ws.close(); S.ws = null; }
  S.phase = "comparing"; setStep(2);
  systemChip(`Negotiating with ${cands.length} merchants at once…`);
  const board = rawBubble("");
  const M = { order: [], states: {}, done: 0, total: cands.length, ws: [], winner: null, board };
  S.multi = M;
  board.innerHTML = renderBoard(M);

  for (const c of cands) {
    let uid;
    try {
      const st = await api("/api/negotiations/start", { method: "POST", body: {
        product_id: c.id, quantity: S.rfq.quantity, target_price: S.rfq.target_price,
        max_delivery_days: S.rfq.max_delivery_days, pause_agent: false } });
      uid = st.negotiation_uid;
    } catch (e) { M.total--; continue; }
    M.order.push(uid); M.states[uid] = { cand: c, st: null };
    const ws = new WebSocket(negWsUrl(uid)); M.ws.push(ws);
    ws.onmessage = (e) => {
      const st = JSON.parse(e.data);
      if (st.type) return;
      M.states[uid].st = st;
      board.innerHTML = renderBoard(M);
      if (st.status !== "NEGOTIATING") {
        ws.close(); M.done++;
        if (M.done >= M.total) finishCompare();
      }
    };
  }
  board.innerHTML = renderBoard(M);
}

function finishCompare() {
  const M = S.multi;
  const agreed = M.order.map(u => [u, M.states[u].st]).filter(([u, st]) => st && st.status === "AGREED");
  if (agreed.length) { agreed.sort((a, b) => a[1].total - b[1].total); M.winner = agreed[0][0]; }
  M.board.innerHTML = renderBoard(M);
  if (agreed.length) {
    const w = M.states[M.winner];
    S.phase = "compared";
    const sv = w.cand.list_price != null ? Math.round((w.cand.list_price - w.st.final_unit_price) * S.rfq.quantity) : 0;
    assistant(`Done — I negotiated all ${M.total} in parallel. <strong>${esc(w.cand.merchant_name)}</strong>
      gives the best total at <strong>${inr(w.st.total)}</strong> (${inr(w.st.final_unit_price)}/unit)${sv > 0 ? ` — <strong>${inr(sv)}</strong> below list` : ""}.
      Tap “Go with…” above, or say “yes” to lock it in.`,
      `Compared ${M.total} merchants — best: ${esc(w.cand.merchant_name)} at ${inr(w.st.total)}.`);
  } else {
    S.phase = "idle";
    assistant(`None of the ${M.total} merchants could close within your target. Try a higher target or a longer delivery window.`);
  }
}

window.proceedWithWinner = () => {
  const M = S.multi;
  if (!M || !M.winner) return;
  proceedToAgreement(M.winner, M.states[M.winner].cand.merchant_name);
};

// ---- Multi-item basket: negotiate every line item in parallel, one checkout ----
// Each line runs its own mini-scoreboard (all merchants at once); the cheapest
// AGREED negotiation per line wins, and every winner is paid in a single basket.
async function startBasket(lines) {
  if (S.ws) { S.ws.close(); S.ws = null; }
  if (S.multi) { (S.multi.ws || []).forEach(w => { try { w.close(); } catch (e) {} }); S.multi = null; }
  if (S.basket) { S.basket.lines.forEach(L => L.ws.forEach(w => { try { w.close(); } catch (e) {} })); }
  S.phase = "basket"; setStep(2);
  systemChip(`Basket — ${lines.length} items. Finding merchants and negotiating each line in parallel…`);
  const board = rawBubble("");
  const B = { board, settled: false, lines: lines.map(rfq => ({
    rfq, cands: [], order: [], states: {}, winner: null, done: 0, total: 0, ws: [], searchDone: false, note: "",
  })) };
  S.basket = B;
  renderBasket(B);

  for (const L of B.lines) {
    const q = L.rfq;
    const p = new URLSearchParams({ query: q.query, quantity: q.quantity });
    if (q.max_delivery_days != null) p.set("max_delivery_days", q.max_delivery_days);
    let data;
    try { data = await api("/api/buyer/search?" + p.toString()); }
    catch (e) { L.searchDone = true; L.note = "no merchant"; renderBasket(B); maybeFinishBasket(B); continue; }
    L.cands = data.candidates || [];
    L.searchDone = true;
    if (!L.cands.length) { L.note = "no merchant"; renderBasket(B); maybeFinishBasket(B); continue; }
    // Missing per-line target defaults to the cheapest candidate's list price.
    const target = q.target_price != null ? q.target_price : Math.min(...L.cands.map(c => c.list_price));
    for (const c of L.cands) {
      let uid;
      try {
        const st = await api("/api/negotiations/start", { method: "POST", body: {
          product_id: c.id, quantity: q.quantity, target_price: target,
          max_delivery_days: q.max_delivery_days, pause_agent: false } });
        uid = st.negotiation_uid;
      } catch (e) { continue; }
      L.order.push(uid); L.states[uid] = { cand: c, st: null }; L.total++;
      const ws = new WebSocket(negWsUrl(uid)); L.ws.push(ws);
      ws.onmessage = (e) => {
        const st = JSON.parse(e.data);
        if (st.type) return;
        L.states[uid].st = st;
        renderBasket(B);
        if (st.status !== "NEGOTIATING") {
          ws.close(); L.done++;
          if (L.done >= L.total) finishLine(L, B);
        }
      };
    }
    renderBasket(B);
  }
  renderBasket(B);
}

function finishLine(L, B) {
  const agreed = L.order.map(u => [u, L.states[u].st]).filter(([u, st]) => st && st.status === "AGREED");
  if (agreed.length) { agreed.sort((a, b) => a[1].total - b[1].total); L.winner = agreed[0][0]; }
  else if (!L.note) L.note = "no deal";
  renderBasket(B);
  maybeFinishBasket(B);
}

function maybeFinishBasket(B) {
  const allDone = B.lines.every(L => L.searchDone && (L.total === 0 || L.done >= L.total));
  if (!allDone || B.settled) return;
  B.settled = true;
  const winners = B.lines.filter(L => L.winner);
  renderBasket(B);
  if (!winners.length) {
    S.phase = "idle";
    assistant(`None of your basket items could close within target. Try higher targets or a longer delivery window.`);
    return;
  }
  S.phase = "basketReady";
  const grand = winners.reduce((s, L) => s + L.states[L.winner].st.total, 0);
  const missed = B.lines.length - winners.length;
  assistant(`Basket ready — <strong>${winners.length}</strong> item(s) negotiated${missed ? `, ${missed} couldn't close` : ""}.
    Grand total <strong>${inr(grand)}</strong>. Tap <strong>Confirm &amp; pay basket</strong> to lock every line in one go.`,
    `Basket ready: ${winners.length} item(s), total ${inr(grand)}.`);
}

function renderBasket(B) {
  const rows = B.lines.map(L => {
    const q = L.rfq;
    let right;
    if (!L.searchDone) right = `<span class="muted small">searching…</span>`;
    else if (!L.cands.length) right = `<span class="pill denied">no merchant</span>`;
    else if (L.winner) {
      const w = L.states[L.winner].st, c = L.states[L.winner].cand;
      right = `<div class="sb-price">${inr(w.total)}</div><div class="faint small">${esc(c.merchant_name)} · ${inr(w.final_unit_price)}/u</div>${savingsChip(c.list_price, w.final_unit_price, q.quantity, q.target_price)}`;
    } else if (L.total > 0 && L.done >= L.total) right = `<span class="pill denied">no deal</span>`;
    else {
      const agreed = L.order.map(u => L.states[u].st).filter(s => s && s.status === "AGREED").sort((a, b) => a.total - b.total);
      right = agreed.length
        ? `<span class="live-dot"></span><span class="small muted">best ${inr(agreed[0].total)}…</span>`
        : `<span class="live-dot"></span><span class="small muted">negotiating ${L.total || "…"}</span>`;
    }
    const chips = L.order.map(u => {
      const x = L.states[u], st = x.st;
      let s, extra = "";
      if (!st) s = "…";
      else if (st.status === "NEGOTIATING") { const o = lastMerchantOffer(st); s = o ? inr(o) : "…"; }
      else if (st.status === "AGREED") { s = inr(st.total); if (u === L.winner) extra = " win"; }
      else { s = "—"; extra = " lost"; }
      return `<span class="bk-chip${extra}">${esc(x.cand.merchant_name.split(/\s+/)[0])} · ${s}</span>`;
    }).join("");
    return `<div class="bk-line">
      <div class="bk-l"><strong>${q.quantity} × ${esc(q.query)}</strong>
        <div class="bk-chips">${chips || `<span class="faint small">${esc(L.note || "…")}</span>`}</div></div>
      <div class="bk-r">${right}</div></div>`;
  }).join("");
  const winners = B.lines.filter(L => L.winner);
  const grand = winners.reduce((s, L) => s + L.states[L.winner].st.total, 0);
  const cta = (B.settled && winners.length)
    ? `<div class="bk-cta"><button class="ok" onclick="confirmBasket()">Confirm &amp; pay basket · ${inr(grand)}</button></div>`
    : "";
  B.board.innerHTML = `<div class="basket">
    <div class="bk-head">🧺 Basket — ${B.lines.length} item(s), negotiated in parallel</div>
    ${rows}
    <div class="bk-total"><span>Grand total</span><strong>${inr(grand)}</strong></div>
    ${cta}</div>`;
}

window.confirmBasket = async () => {
  const B = S.basket; if (!B) return;
  const uids = B.lines.filter(L => L.winner).map(L => L.winner);
  if (!uids.length) return toast("Nothing to confirm.", "err");
  const btn = document.querySelector(".bk-cta button");
  if (btn) { btn.disabled = true; btn.textContent = "Processing…"; }
  try {
    const res = await api("/api/buyer/basket/checkout", { method: "POST", body: { negotiation_uids: uids } });
    setStep(4); S.phase = "done";
    renderBasketReceipt(res);
  } catch (e) { if (btn) { btn.disabled = false; btn.textContent = "Confirm & pay basket"; } assistant(e.message); }
};

function renderBasketReceipt(res) {
  const rows = res.lines.map(l => {
    const cls = l.status === "CONFIRMED" ? "CONFIRMED" : l.status === "UNAVAILABLE" ? "FAILED" : "AGREED";
    const link = l.payment_link ? ` · <a href="${l.payment_link}" target="_blank">pay</a>` : "";
    return `<tr><td>${esc(l.product_name || "")}<div class="faint small">${esc(l.merchant_name || "")}</div></td>
      <td>${l.quantity ?? "—"}</td><td>${inr(l.unit_price)}</td><td>${inr(l.total)}</td>
      <td><span class="pill ${cls}">${l.status}</span>${link}</td></tr>`;
  }).join("");
  const table = `<div class="rich"><table style="margin:8px 0"><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Subtotal</th><th>Status</th></tr>${rows}
    <tr><td colspan="3"><strong>Basket ${esc(res.basket_uid)} · ${res.mode} mode</strong></td><td colspan="2"><strong>${inr(res.total)}</strong></td></tr></table></div>`;
  assistant(`Basket <strong>${res.status}</strong> 🎉 ${table} Anything else you'd like to buy?`,
    `Basket ${res.basket_uid} ${res.status} — total ${inr(res.total)}.`);
  systemChip("Basket confirmed");
}

// ---- Negotiation (in-thread, natural language) ----
async function startNeg(cand) {
  if (S.ws) { S.ws.close(); S.ws = null; }
  S.activeNeg = null; S.lastSeq = 0; S.activeMerchant = cand.merchant_name;
  if (!S.usedMerchants.includes(cand.merchant_name)) S.usedMerchants.push(cand.merchant_name);
  setStep(2);
  systemChip(`Negotiation opened with ${cand.merchant_name}`);
  let st;
  try {
    st = await api("/api/negotiations/start", { method: "POST", body: {
      product_id: cand.id, quantity: S.rfq.quantity, target_price: S.rfq.target_price,
      max_delivery_days: S.rfq.max_delivery_days, pause_agent: true } });
  } catch (e) { assistant(e.message); return; }
  S.activeNeg = st.negotiation_uid; S.phase = "negotiating";
  applyNeg(st);
  assistant(`You're at the table with <strong>${esc(cand.merchant_name)}</strong>. Reply naturally —
    e.g. <em>“offer ₹4300”</em>, <em>“that's too high”</em>, or <em>“accept”</em>. I keep you within your limits.`);
  openNegWS(S.activeNeg);
}

function openNegWS(uid) {
  if (S.ws) S.ws.close();
  const ws = new WebSocket(negWsUrl(uid));
  S.ws = ws;
  ws.onmessage = (e) => {
    const st = JSON.parse(e.data);
    if (st.type === "error") { toast(st.message, "err"); return; }
    if (st.type === "gone") return;
    applyNeg(st);
  };
  ws.onclose = () => {
    if (S.phase === "negotiating" && S.activeNeg === uid)
      setTimeout(() => { if (S.phase === "negotiating" && S.activeNeg === uid) openNegWS(uid); }, 1000);
  };
}

function bubbleFor(m) {
  const price = m.unit_price != null ? ` <span class="price-chip">${inr(m.unit_price)}/unit</span>` : "";
  const kt = ["accept", "reject"].includes(m.kind) ? ` <span class="kind-tag ${m.kind}">${m.kind}</span>` : "";
  const html = `${esc(m.text)}${price}${kt}`;
  if (m.role === "system") return void systemChip(m.text);
  if (m.role === "merchant") merchantMsg(S.activeMerchant, html);
  else buyerMsg(html);
}

function applyNeg(st) {
  for (const m of st.messages) if (m.seq > S.lastSeq) { S.lastSeq = m.seq; bubbleFor(m); }
  if (st.status !== "NEGOTIATING") { hint(""); updateAssist(null); handleClosed(st); return; }
  const agentDriving = st.buyer_control === "AGENT";
  hint(st.turn === "merchant" ? `${S.activeMerchant} is considering…`
       : agentDriving ? "Your agent is negotiating for you…" : "Your move — type a reply below.");
  updateAssist(st);
}

function updateAssist(st) {
  const btn = $("assistToggle");
  if (!st || st.status !== "NEGOTIATING") { btn.style.display = "none"; return; }
  const agentDriving = st.buyer_control === "AGENT";
  btn.style.display = "";
  btn.textContent = agentDriving ? "Take Over" : "Agent Negotiate";
  btn.onclick = () => {
    if (S.ws && S.ws.readyState === 1)
      S.ws.send(JSON.stringify({ type: "control", mode: agentDriving ? "HUMAN" : "AGENT" }));
  };
}

function negotiationSay(text) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ type: "say", message: text }));
  else toast("Reconnecting to the negotiation…", "err");
}

async function handleClosed(st) {
  if (S.phase !== "negotiating") return;  // guard: WS can deliver terminal state more than once
  if (S.ws) { S.ws.close(); S.ws = null; }
  S.phase = "closing";
  if (st.status === "AGREED") {
    const cand = S.candidates.find(c => c.merchant_name === S.activeMerchant);
    const sv = cand && cand.list_price != null ? Math.round((cand.list_price - st.final_unit_price) * S.rfq.quantity) : 0;
    assistant(`Deal reached with <strong>${esc(S.activeMerchant)}</strong> at
      <strong>${inr(st.final_unit_price)}/unit</strong> (${inr(st.total)} total)${sv > 0 ? ` — you saved <strong>${inr(sv)}</strong> vs list` : ""}. Locking it in…`);
    await proceedToAgreement(st.negotiation_uid, S.activeMerchant);
  } else {
    const left = S.candidates.filter(c => !S.usedMerchants.includes(c.merchant_name));
    S.phase = left.length ? "merchants" : "idle";
    const more = left.length
      ? `Want me to try <strong>${esc(left[0].merchant_name)}</strong> instead? Say “yes” or pick another.`
      : `No other merchants to try. Start a new request whenever you like.`;
    assistant(`No deal with ${esc(S.activeMerchant)} (${reasonLabel(st.reason_code).toLowerCase()}). ${more}`);
  }
}

// Shared by single-merchant and multi-merchant paths: turn an AGREED negotiation
// into an upsell prompt / agreement.
async function proceedToAgreement(uid, merchantName) {
  setStep(3); S.activeMerchant = merchantName; S.selectedNeg = uid; S.phase = "closing";
  let sel;
  try { sel = await api("/api/buyer/select", { method: "POST", body: { negotiation_uid: uid } }); }
  catch (e) { assistant(e.message); return; }
  if (sel.upsell) {
    S.upsell = sel.upsell; S.phase = "upsell";
    assistant(`One more thing — buyers like you often add <strong>${esc(sel.upsell.name)}</strong>
      × ${sel.upsell.quantity} at ${inr(sel.upsell.unit_price)} (${inr(sel.upsell.total)}). ${esc(sel.upsell.reason)}
      <div class="rich" style="display:flex;gap:8px;margin-top:8px">
        <button class="ok sm" onclick="finalizeAgreement(true)">Add it</button>
        <button class="ghost sm" onclick="finalizeAgreement(false)">No thanks</button></div>
      Or just tell me “yes” / “no”.`,
      `Suggested add-on: ${esc(sel.upsell.name)} × ${sel.upsell.quantity} (${inr(sel.upsell.total)}).`);
  } else finalizeAgreement(false);
}

window.finalizeAgreement = async function (acceptUpsell) {
  try {
    const resp = await api("/api/buyer/agreement", { method: "POST",
      body: { negotiation_uid: S.selectedNeg, accept_upsell: acceptUpsell } });
    if (resp.inventory_shortfall) return renderShortfall(resp);
    S.agreement = resp; renderAgreement(resp);
  } catch (e) { assistant(e.message); }
};

function renderShortfall(resp) {
  const s = resp.inventory_shortfall;
  const btns = resp.alternatives.map(a => {
    if (a.type === "partial") return `<button class="ok sm" onclick='finalizePartial(${a.quantity})'>Take ${a.quantity} now · ${inr(a.total)}</button>`;
    if (a.type === "backorder") return `<button class="ok sm" onclick='finalizeBackorder()'>Backorder full in ${a.delivery_days}d · ${inr(a.total)}</button>`;
    if (a.type === "alternative_merchant") return `<span class="tag">${esc(a.label)}</span>`;
    return "";
  }).join(" ");
  assistant(`Stock just dropped — only <strong>${s.available}</strong> of ${s.requested} ${esc(s.product_name)} left.
    <div class="rich" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">${btns}</div>`,
    `Stock dropped on ${esc(s.product_name)} — only ${s.available} of ${s.requested} left; alternatives offered.`);
}
window.finalizePartial = async (qty) => finalizeWith({ partial_quantity: qty });
window.finalizeBackorder = async () => finalizeWith({ backorder: true });
async function finalizeWith(extra) {
  try {
    const resp = await api("/api/buyer/agreement", { method: "POST",
      body: { negotiation_uid: S.selectedNeg, accept_upsell: false, ...extra } });
    if (resp.inventory_shortfall) return renderShortfall(resp);
    S.agreement = resp; renderAgreement(resp);
  } catch (e) { assistant(e.message); }
}

function renderAgreement(agr) {
  setStep(3); S.phase = "checkout";
  const items = agr.items.map(i => `<tr><td>${esc(i.name)}</td><td>${i.quantity}</td><td>${inr(i.unit_price)}</td><td>${inr(i.unit_price * i.quantity)}</td></tr>`).join("");
  const bo = agr.backorder ? ' <span class="tag">backorder</span>' : "";
  const table = `<div class="rich"><table style="margin:8px 0"><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Subtotal</th></tr>${items}
      <tr><td colspan="3"><strong>Total · ${agr.delivery_days}d delivery</strong></td><td><strong>${inr(agr.total)}</strong></td></tr></table>`;
  assistant(`Here's your agreement <span class="muted small">${agr.agreement_uid}</span>${bo}:
    ${table}<button class="ok sm" onclick="runCheckout()">Proceed to payment</button></div>
    Or say <strong>“checkout”</strong>.`,
    `Agreement ${agr.agreement_uid}${bo}:${table}</div>`);
}

window.runCheckout = async function () {
  try {
    const res = await api("/api/buyer/checkout", { method: "POST", body: { agreement_uid: S.agreement.agreement_uid } });
    if (res.inventory_shortfall) return renderShortfall(res);
    setStep(4); S.phase = "done";
    const link = res.mode === "live" ? ` · <a href="${res.payment_link}" target="_blank">open payment link</a>` : "";
    assistant(`Payment <strong>${res.status}</strong> — ${inr(res.amount)} (${res.mode} mode)${link}. 🎉
      Anything else you'd like to buy?`);
    systemChip("Order confirmed");
  } catch (e) { assistant(e.message); }
};

window.showOrders = async function () {
  try {
    const orders = await api("/api/buyer/orders");
    S.orders = orders;
    if (!orders.length) { assistant("You don't have any orders yet — tell me what you'd like to buy."); return; }
    const rows = orders.map((o, i) => {
      const items = o.items.map(x => `${x.quantity}× ${esc(x.name)}`).join(", ");
      const cls = o.status === "CONFIRMED" ? "CONFIRMED" : o.status === "FAILED" ? "FAILED" : "AGREED";
      return `<div class="order-row">
        <div style="flex:1;min-width:0"><strong>${esc(o.counterparty)}</strong> <span class="pill ${cls}">${o.status}</span>
          <div class="muted small">${items} · ${o.delivery_days}d${o.backorder ? " · backorder" : ""}</div></div>
        <div class="order-actions">
          <span class="price" style="font-size:15px">${inr(o.total)}</span>
          <button class="ghost sm" onclick="invoiceOrder(${i})">Invoice</button>
          <button class="ok sm" onclick="reorderOrder(${i})">Reorder</button>
        </div></div>`;
    }).join("");
    assistant(`Here are your orders:<div class="rich">${rows}</div>`,
      `Your orders: ${orders.map(o => `${esc(o.counterparty)} ${inr(o.total)}`).join("; ")}.`);
  } catch (e) { assistant(e.message); }
};

window.invoiceOrder = (i) => { const o = S.orders[i]; if (o) printInvoice(o); };
window.reorderOrder = (i) => {
  const o = S.orders[i]; if (!o || !o.items.length) return;
  const base = o.items[0];
  S.rfq = { query: base.name, quantity: base.quantity, target_price: base.unit_price, max_delivery_days: o.delivery_days };
  buyerMsg(esc(`Reorder ${base.quantity}× ${base.name}`));
  assistant(`Reordering <strong>${base.quantity} × ${esc(base.name)}</strong> at your last price of
    ${inr(base.unit_price)}/unit. Finding merchants…`);
  doSearch();
};

function setStep(n) {
  document.querySelectorAll("#steps .step").forEach(s => {
    const i = parseInt(s.dataset.step, 10);
    s.classList.toggle("done", i < n); s.classList.toggle("active", i === n);
  });
}

// ---- Boot: restore the most recent chat, or start a new one ----
async function init() {
  await refreshChatList();
  if (S.chatList.length) await loadConversation(S.chatList[0].uid);
  else await newChat();
}
init();
