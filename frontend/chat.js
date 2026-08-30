// Reusable live negotiation chat panel (merchant portal), over WebSocket.
// The server pushes full state and auto-advances agent turns; this client renders
// and sends the viewer's actions. The merchant can take over from their agent.

function fmtINR(n) { return n == null ? "" : "₹" + Number(n).toLocaleString("en-IN"); }

const SENDER_LABEL = {
  "buyer:agent": "Buyer Agent", "buyer:human": "Buyer",
  "merchant:agent": "Your Agent", "merchant:human": "You",
  "system:system": "System",
};

function controlOf(st, side) { return side === "buyer" ? st.buyer_control : st.merchant_control; }

function wsUrl(uid) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/negotiations/${uid}?token=${encodeURIComponent(getToken())}`;
}

// mount: element. uid: negotiation id. role: 'buyer' | 'merchant'. opts: { onClosed }
function openChat(mount, uid, role, opts = {}) {
  let stopped = false, ws = null, lastStatus = "NEGOTIATING", reconnectT = null;

  mount.innerHTML = `
    <div class="chat-head">
      <div class="ch-head-info"><div id="ch-title" class="chat-title"></div><div id="ch-status" class="ch-status"></div></div>
      <div id="ch-toggle"></div>
    </div>
    <div id="ch-log" class="chat-log"></div>
    <div id="ch-controls" class="chat-controls"></div>`;
  const log = mount.querySelector("#ch-log");

  function av(m) {
    if (m.role === "merchant") return `<div class="bub-av merchant">🏬</div>`;
    return `<div class="bub-av buyer">🧑</div>`;
  }
  function bubble(m) {
    if (m.role === "system") return `<div class="bubble-system">${m.text}</div>`;
    const side = m.role === role ? "right" : "left";
    const who = SENDER_LABEL[`${m.role}:${m.type}`] || m.role;
    const human = m.type === "human" ? " human" : "";
    const price = m.unit_price != null ? `<span class="price-chip">${fmtINR(m.unit_price)}/unit</span>` : "";
    const kindTag = ["accept", "reject"].includes(m.kind) ? `<span class="kind-tag ${m.kind}">${m.kind}</span>` : "";
    const avatar = av(m);
    return `<div class="bubble-row ${side}">
      ${side === "left" ? avatar : ""}
      <div class="bubble ${m.role}${human}">
        <div class="bubble-meta">${who} ${kindTag}</div>
        <div class="bubble-text">${m.text || ""} ${price}</div>
      </div>
      ${side === "right" ? avatar : ""}
    </div>`;
  }

  function render(st) {
    mount.querySelector("#ch-title").innerHTML =
      `<strong>${st.product_name}</strong> <span class="muted">· ${st.quantity} units · target ${fmtINR(st.target_price)}</span>`;

    const statusEl = mount.querySelector("#ch-status");
    if (st.status === "NEGOTIATING") {
      const wf = st.waiting_for === role ? "your turn to respond"
        : st.waiting_for ? `waiting for ${st.waiting_for}`
        : st.turn === role ? "your turn" : `${st.turn}'s turn`;
      statusEl.innerHTML = `<span class="live-dot"></span><span class="muted">${wf}</span>`;
    } else if (st.status === "AGREED") {
      statusEl.innerHTML = `<span class="pill agreed">AGREED ${fmtINR(st.final_unit_price)}/unit</span>`;
    } else statusEl.innerHTML = `<span class="pill denied">${st.status}</span>`;

    const tg = mount.querySelector("#ch-toggle");
    if (st.status === "NEGOTIATING") {
      const paused = controlOf(st, role) === "HUMAN";
      tg.innerHTML = paused
        ? `<button class="ghost sm" data-act="resume">▶ Resume agent</button>`
        : `<button class="warn-btn sm" data-act="pause">⏸ Take over</button>`;
      tg.querySelector("[data-act]").onclick = (e) => action(e.currentTarget.dataset.act);
    } else tg.innerHTML = "";

    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
    log.innerHTML = inquiryCard(st) + st.messages.map(bubble).join("");
    if (atBottom) log.scrollTop = log.scrollHeight;
    renderControls(st);
    if (opts.onState) opts.onState(st);
  }

  // The buyer's structured request, pinned at the top of the thread.
  function inquiryCard(st) {
    return `<div class="inquiry-card">
      <div class="iq-title">📄 Inquiry · ${st.product_name || "Product"}</div>
      <div class="iq-grid">
        <div class="iq-f"><span>Quantity</span><b>${st.quantity} units</b></div>
        <div class="iq-f"><span>Buyer target</span><b>${fmtINR(st.target_price)}/unit</b></div>
        <div class="iq-f"><span>Delivery</span><b>${st.delivery_days ? st.delivery_days + " days" : "—"}</b></div>
        <div class="iq-f"><span>Status</span><b>${st.status}</b></div>
      </div></div>`;
  }

  function renderControls(st) {
    const el = mount.querySelector("#ch-controls");
    if (st.status !== "NEGOTIATING") { el.innerHTML = ""; return; }
    const paused = controlOf(st, role) === "HUMAN";
    if (!paused) {
      el.innerHTML = `<div class="agent-note">🤖 Your sales agent is handling this — your floor still applies.
        <button class="linklike" data-act="pause">Take over</button> to respond yourself.</div>`;
      el.querySelector("[data-act]").onclick = () => action("pause");
      return;
    }
    const myTurn = st.turn === role;
    el.innerHTML = `
      <div class="you-control">✋ You're responding as a human. Your floor price still applies.</div>
      <div class="mc-row">
        <input id="ch-price" type="number" placeholder="₹ / unit" ${myTurn ? "" : "disabled"} />
        <button class="ok sm" data-act="counter" ${myTurn ? "" : "disabled"}>Counter</button>
        <button class="ok sm" data-act="accept" ${myTurn ? "" : "disabled"}>Accept</button>
        <button class="danger sm" data-act="reject" ${myTurn ? "" : "disabled"}>Reject</button>
      </div>
      <div class="mc-row">
        <input id="ch-text" placeholder="Type a message to the buyer…" />
        <button class="ghost sm" data-act="message">Send</button>
      </div>
      ${myTurn ? "" : `<div class="faint small" style="margin-top:2px">Waiting for the buyer to respond…</div>`}`;
    el.querySelectorAll("[data-act]").forEach(b => b.onclick = () => action(b.dataset.act));
  }

  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  function action(act) {
    if (act === "pause") return send({ type: "control", mode: "HUMAN" });
    if (act === "resume") return send({ type: "control", mode: "AGENT" });
    const price = parseFloat((mount.querySelector("#ch-price") || {}).value);
    const text = (mount.querySelector("#ch-text") || {}).value || null;
    if (act === "counter") send({ type: "act", action: "counter", price, text });
    else if (act === "accept") send({ type: "act", action: "accept" });
    else if (act === "reject") send({ type: "act", action: "reject" });
    else if (act === "message") send({ type: "act", action: "message", text });
  }

  function connect() {
    ws = new WebSocket(wsUrl(uid));
    ws.onmessage = (e) => {
      const st = JSON.parse(e.data);
      if (st.type === "error") { toast(st.message, "err"); return; }
      if (st.type === "gone") return;
      render(st);
      if (st.status !== "NEGOTIATING" && lastStatus === "NEGOTIATING" && opts.onClosed) opts.onClosed(st);
      lastStatus = st.status;
    };
    ws.onclose = () => {
      if (stopped || lastStatus !== "NEGOTIATING") return;
      reconnectT = setTimeout(connect, 1000);
    };
  }
  connect();

  return {
    stop() { stopped = true; if (reconnectT) clearTimeout(reconnectT); if (ws) ws.close(); },
    act(a) { action(a); },  // let an external panel drive take-over / resume
  };
}
