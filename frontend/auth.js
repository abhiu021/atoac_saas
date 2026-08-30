// Shared auth helpers + landing-page login/signup.
const API = "";
const TOKEN_KEY = "atoac_token";
const USER_KEY = "atoac_user";

function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function getToken() { return localStorage.getItem(TOKEN_KEY); }
function getUser() { try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; } }
function logout() { localStorage.clear(); location.href = "/"; }

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail
      : Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(", ")
      : "Request failed";
    throw new Error(detail);
  }
  return data;
}

// --- Human-readable labels for machine reason codes ---
const REASON_LABEL = {
  AGREED_WITHIN_TARGET: "Closed within target",
  AGREED_FINAL_ROUND: "Closed on final round",
  MERCHANT_ACCEPTED: "Merchant accepted",
  BUYER_ACCEPTED: "Buyer accepted",
  COUNTER_OFFERED: "Counter-offered",
  WALKAWAY_EXCEEDED: "Past buyer's walk-away",
  NO_AGREEMENT_IN_ROUNDS: "No deal in rounds",
  BELOW_FLOOR: "Below floor price",
  OVER_DISCOUNT_CAP: "Over discount cap",
  BELOW_MIN_QTY: "Below minimum order",
  INSUFFICIENT_STOCK: "Not enough stock",
  HUMAN_COUNTER: "Merchant countered",
  HUMAN_REJECTED: "Ended by merchant",
};
// Fall back to Title Case for anything not mapped (e.g. FOO_BAR → "Foo bar").
function reasonLabel(code) {
  if (!code) return "";
  if (REASON_LABEL[code]) return REASON_LABEL[code];
  const s = String(code).replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}


function toast(msg, cls = "") {
  let host = document.getElementById("toasts");
  if (!host) { host = document.createElement("div"); host.id = "toasts"; host.className = "toasts"; document.body.appendChild(host); }
  const t = document.createElement("div");
  t.className = "toast " + cls;
  t.textContent = msg;
  host.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, 3200);
}

// Build a printable commercial agreement / invoice for an order and open the
// browser print dialog (Save as PDF). Works from both portals.
function printInvoice(order) {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const rupee = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
  const rows = (order.items || []).map(i =>
    `<tr><td>${esc(i.name)}</td><td class="c">${i.quantity}</td><td class="r">${rupee(i.unit_price)}</td><td class="r">${rupee(i.unit_price * i.quantity)}</td></tr>`).join("");
  const date = order.created_at ? new Date(order.created_at).toLocaleString() : new Date().toLocaleString();
  const paid = order.payment_status === "CONFIRMED";
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Invoice ${esc(order.agreement_uid)}</title>
    <style>
      *{box-sizing:border-box} body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1a2230;margin:0;padding:40px;background:#fff}
      .doc{max-width:720px;margin:0 auto}
      .hd{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #eef;padding-bottom:16px;margin-bottom:22px}
      .brand{font-weight:800;font-size:22px;letter-spacing:.5px} .brand span{color:#4f6dff}
      .sub{color:#8a94a4;font-size:12px;margin-top:2px}
      .status{font-size:12px;font-weight:700;padding:4px 12px;border-radius:999px;background:${paid ? "#e6f7ef;color:#1fa971" : "#fff5e6;color:#c58612"}}
      .meta{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px;font-size:12.5px}
      .meta b{color:#8a94a4;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}
      table{width:100%;border-collapse:collapse;font-size:13.5px} th,td{padding:10px 8px;border-bottom:1px solid #eef;text-align:left}
      th{color:#8a94a4;font-size:11px;text-transform:uppercase;letter-spacing:.4px} .c{text-align:center} .r{text-align:right}
      tfoot td{border-bottom:0;padding-top:14px;font-size:15px}
      .foot{margin-top:28px;color:#8a94a4;font-size:11.5px;border-top:1px solid #eef;padding-top:14px}
      @media print{body{padding:0}}
    </style></head><body><div class="doc">
      <div class="hd"><div><div class="brand">ATO<span>AC</span></div><div class="sub">Commercial Agreement &amp; Invoice</div></div>
        <div class="status">${esc(order.status)}${paid ? " · PAID" : ""}</div></div>
      <div class="meta">
        <div><b>Agreement</b><br>${esc(order.agreement_uid)}</div>
        <div><b>Date</b><br>${esc(date)}</div>
        <div><b>Counterparty</b><br>${esc(order.counterparty || "—")}</div>
        <div><b>Delivery</b><br>${order.delivery_days} days${order.backorder ? " (backorder)" : ""}</div>
      </div>
      <table><thead><tr><th>Item</th><th class="c">Qty</th><th class="r">Unit price</th><th class="r">Amount</th></tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr><td colspan="3" class="r"><strong>Total</strong></td><td class="r"><strong>${rupee(order.total)}</strong></td></tr></tfoot></table>
      <div class="foot">Negotiated and frozen through ATOAC${paid ? " · Settled via Razorpay" : ""}. This is a system-generated agreement — no signature required.</div>
    </div><script>window.onload=function(){setTimeout(function(){window.print()},150)}</script></body></html>`;
  const w = window.open("", "_blank", "width=820,height=920");
  if (!w) { toast("Allow pop-ups to download the invoice.", "err"); return; }
  w.document.write(html); w.document.close();
}

function requireRole(role) {
  const user = getUser();
  if (!getToken() || !user) { location.href = "/login.html"; return null; }
  if (user.role !== role) { location.href = user.role === "merchant" ? "/merchant.html" : "/buyer.html"; }
  return user;
}

// --- Landing page only ---
if (document.getElementById("submitBtn")) {
  let mode = "login";
  const el = (id) => document.getElementById(id);
  const msg = (t, cls = "err") => { el("msg").innerHTML = `<div class="notice ${cls}">${t}</div>`; };

  // If already logged in, jump to the right portal.
  if (getToken() && getUser()) {
    location.href = getUser().role === "merchant" ? "/merchant.html" : "/buyer.html";
  }

  el("toggleBtn").onclick = () => {
    mode = mode === "login" ? "signup" : "login";
    el("formTitle").textContent = mode === "login" ? "Log in" : "Sign up";
    el("submitBtn").textContent = mode === "login" ? "Log in" : "Create account";
    el("toggleBtn").textContent = mode === "login" ? "Need an account? Sign up" : "Have an account? Log in";
    el("roleWrap").classList.toggle("hidden", mode === "login");
    el("bizWrap").classList.toggle("hidden", mode === "login" || el("role").value !== "merchant");
    el("msg").innerHTML = "";
  };
  el("role").onchange = () => el("bizWrap").classList.toggle("hidden", el("role").value !== "merchant");

  // Deep-link: /login.html#signup opens the page in sign-up mode.
  if (location.hash === "#signup") el("toggleBtn").click();

  el("submitBtn").onclick = async () => {
    try {
      const email = el("email").value.trim();
      const password = el("password").value;
      let data;
      if (mode === "login") {
        data = await api("/api/auth/login", { method: "POST", body: { email, password } });
      } else {
        const role = el("role").value;
        const body = { email, password, role };
        if (role === "merchant") body.business_name = el("business_name").value.trim();
        data = await api("/api/auth/signup", { method: "POST", body });
      }
      saveSession(data.token, data.user);
      location.href = data.user.role === "merchant" ? "/merchant.html" : "/buyer.html";
    } catch (e) { msg(e.message); }
  };

  el("password").addEventListener("keydown", (e) => { if (e.key === "Enter") el("submitBtn").click(); });
}
