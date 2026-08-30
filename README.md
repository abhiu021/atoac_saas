# ATOAC SaaS — Agent-to-Agent Commerce

Merchant-side AI sales platform: a buyer request negotiates against multiple
merchants' deterministic sales agents, upsells, freezes a bounded agreement, and
settles through Razorpay with verified, idempotent webhooks.

Built to `ATOAC_ARCHITECTURE.md` v3.0. This is the **Phase 1 vertical slice**.

## Run

```bash
cd atoac_saas
python -m pip install -r requirements.txt
python seed.py                       # demo merchants/buyer/products (once)
python -m uvicorn main:app --reload  # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and log in (all passwords `password123`):

| Role       | Email                    |
|------------|--------------------------|
| Buyer      | buyer@test.com           |
| Merchant A | a@comfortseating.com     |
| Merchant B | b@workspacedirect.com    |

**Demo path:** buyer searches `chair`, qty `50`, target `₹4300`, delivery `7d` →
two merchants negotiate → pick a deal → accept the desk-mat upsell → agreement →
checkout (mock mode auto-confirms).

## Configuration (`.env`, see `.env.example`)

- `DATABASE_URL` — SQLite by default; point at Postgres with no code change.
- `RAZORPAY_*` — leave blank for **mock mode**; set keys + webhook secret for live.
- `GEMINI_API_KEY` — optional (Google Gemini free tier). When set, the agents write
  natural-language negotiation lines/summaries. **The LLM never decides price or touches
  the guardrail** — with it off, the product behaves identically using templated messages.

## What's enforced (tested)

- **Guardrail is LLM-free** — all pricing/accept/reject is pure arithmetic in
  `negotiation.py`; below-floor / over-discount prices are rejected.
- **Merchant privacy** — `floor_price` and policy fields never appear in any
  buyer-facing response.
- **Ownership** — a merchant editing another merchant's product gets `403`.
- **Payment amount** is computed from `Agreement.total`, never from the client.
- **Webhooks** are HMAC-SHA256 verified and idempotent (tampered→400, replay→ignored).
- **Login rate limiting** — 5 attempts / 5-minute lockout.
- **Policy-change approval** — material pricing/policy edits are queued for explicit merchant
  approval; negotiations keep using the approved policy until then (§28).
- **Inventory reservation** — stock is held (with a TTL) only when a buyer commits an
  agreement; availability = physical stock − active holds; holds are consumed on
  payment, released on failure/expiry.
- **Graceful inventory shortfall (§19.1)** — if stock drops after negotiation, the
  agent offers buyer-respecting alternatives instead of failing: take a partial
  quantity now, backorder the full quantity within the delivery window, or switch to
  another merchant who can fulfil it.
- **Payment failure + retry (§19.2)** — a failed/cancelled/expired payment webhook
  marks the agreement `FAILED` and releases the hold; the buyer can re-checkout, which
  re-reserves and confirms.

## Tests

```bash
python -m pip install pytest
python -m pytest tests/ -q     # 12 tests: core guarantees + inventory/payment failure
```

## Layout

```
atoac_saas/
├── main.py            FastAPI app + all routes
├── models.py          SQLAlchemy models (§22)
├── database.py        engine/session
├── config.py          env-driven settings
├── auth.py            bcrypt + JWT + rate limiting
├── audit.py           DB-backed audit trail
├── discovery.py       cross-merchant search + filter/rank
├── negotiation.py     turn-based chat engine + guardrail  ← money path, no LLM
├── inventory.py       reservation lifecycle + shortfall alternatives (§19.1)
├── analytics.py       merchant analytics & revenue intelligence (§16/§18)
├── llm.py             optional narration layer (safe fallback)
├── razorpay_client.py payment link + webhook signature
├── seed.py            demo data (reference scenario §25)
├── tests/             pytest suite (isolated temp DB, 32 tests)
└── frontend/          vanilla HTML/JS, no build step
    ├── chat.js        reusable live negotiation chat panel (both portals)
    ├── buyer.*        search → live chat → upsell → agreement → checkout
    └── merchant.*     dashboard: analytics, live negotiations, policies, audit
```

## Roadmap

**Phase 1.5 — DONE** ✅
- §19.1 graceful inventory-failure flow (partial / backorder / alternative merchant)
- Payment `FAILED` handling + retry
- Inventory reservation with expiry
- Automated test suite

**Phase 2 — in progress**
- ✅ Concurrent negotiation — merchant sessions run in parallel threads (`asyncio.gather`
  + `asyncio.to_thread`), each with its own DB session (SQLite in WAL mode). Verified
  parallel by timing.
- ✅ Per-round `Offer` persistence + negotiation state machine (`NEGOTIATING → AGREED |
  DENIED`) — rounds are first-class queryable records, not just audit-log text.
- ✅ Structured reason codes (`AGREED_WITHIN_TARGET`, `WALKAWAY_EXCEEDED`, …) on every
  negotiation and offer, alongside the human-readable string.
- ✅ `GET /api/negotiations/{uid}` — standalone lookup with the full offer trail, visible
  to the buyer or merchant party only (floor price never included).
- ✅ Merchant analytics dashboard (`analytics.py`, §16/§18) — overview (GMV, AOV, success
  rate, avg rounds), negotiation intelligence (closing prices per product, discount spread,
  objection/denial breakdown by reason code), upsell intelligence (attach rate + cross-sell
  revenue), payment health, data-driven revenue recommendations with impact estimates, and a
  recent-negotiations feed.
- ✅ Merchant-approval workflow (§28) — edits to **material** policy fields (list/floor price,
  discount cap, min qty, max rounds) are queued as a `PolicyChangeRequest` and take effect only
  on approval; non-material edits (name, stock, delivery) apply immediately. Live negotiations
  keep using the current approved policy until a change is approved.
- ✅ **Persistent chat history** (`Conversation` model) — buyer conversations are saved
  server-side and restored on reload; a sidebar lists recent chats with a "New chat" button,
  and reopening a chat replays its full transcript (as static history). Endpoints under
  `/api/buyer/conversations`.
- ✅ **Conversational buyer (Claude-style) + NLP** (`intent.py`, §7) — the buyer portal is a
  single chat thread. You describe your request in plain English ("50 ergonomic chairs under
  ₹4300 each within a week"); an NLP parser extracts product/quantity/target/delivery (LLM when
  a key is set, deterministic regex otherwise). Merchants appear inline, and you negotiate with
  them right there in natural language ("that's too high", "offer 4300", "accept") — parsed into
  guardrail-checked actions. Endpoints: `POST /api/buyer/intent`, `POST /api/negotiations/{uid}/say`.
- ✅ **Live LLM agents** (optional) — set `GEMINI_API_KEY` and negotiation lines + intent
  parsing are authored by Google Gemini over REST (free tier; default `gemini-2.0-flash`, set
  `GEMINI_MODEL=gemini-2.5-flash` to change). The LLM only *phrases* messages — the price on
  every turn is still the deterministic engine value, guardrail-checked. Without a key,
  deterministic templates are used (identical behavior).
- ✅ **Order history** — `GET /api/buyer/orders` and `GET /api/merchant/orders`; a merchant Orders
  view and a buyer "Orders" button / "show my orders" chat command.
- ✅ **Live merchant notifications** — account-level `WS /ws/merchant` pushes a toast when a
  negotiation of theirs starts, needs a human takeover, or closes; the live table refreshes with it.
- ✅ **Live over WebSockets** (`ws_hub.py`) — negotiations stream over `WS /ws/negotiations/{uid}`
  (auth via `?token=`). A single server-side driver auto-advances AGENT turns and broadcasts state
  to everyone watching, so a negotiation progresses even with no buyer tab open. Clients send
  `{type: say|act|control}`.
- ✅ **Light / dark theme** — toggle in the header, persisted per browser; no-flash init in each
  page head. All colors are CSS-variable tokens with a `[data-theme="light"]` override.
- ✅ **Merchant analytics visuals** — close-rate donut, outcome bars, per-product closing-price
  bars, objection bars, and upsell attach-rate progress bars (hand-rolled inline SVG, theme-aware).
- ✅ **Interactive negotiation chat + human takeover** — a negotiation is a live turn-based
  chat (`NegotiationMessage` log). Each side is driven by its AGENT or, once paused, by its
  HUMAN. Either party can pause its agent and respond (counter / accept / reject / free text);
  a human **merchant is still bounded by the guardrail** (can't breach floor/discount cap), a
  human **buyer is unconstrained**. Both portals show the conversation live (polling); the buyer
  watches its agent negotiate and can jump in, the merchant watches/takes over from the dashboard.
  Endpoints: `POST /api/negotiations/start`, `/{uid}/step`, `/{uid}/control`, `/{uid}/act`,
  `GET /api/negotiations/{uid}` (chat state), `GET /api/merchant/negotiations`.
- ⬜ Capability registry (§9).
