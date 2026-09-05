# ATOAC — Agent-to-Agent Commerce

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Status: Active Development](https://img.shields.io/badge/Status-Active%20Development-green?style=flat-square)](#implementation-status)

> **A merchant-side AI sales platform for the agentic commerce era.** Give every merchant an autonomous sales agent that can receive buyer agent requests, negotiate within merchant-defined guardrails, identify upsell opportunities, freeze agreements, and hand off to payment—all without exposing private merchant strategy.

---

## Table of Contents

- [Quick Start](#quick-start)
- [What is ATOAC?](#what-is-atoac)
- [Key Features](#key-features)
- [Installation](#installation)
- [Usage & Demo](#usage--demo)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Implementation Status](#implementation-status)
- [API Overview](#api-overview)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---

## Quick Start

### 30 seconds to a running demo:

```bash
# 1. Clone and navigate
git clone https://github.com/your-username/atoac.git
cd atoac/atoac_saas

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Seed demo data (once)
python seed.py

# 4. Start the server
python -m uvicorn main:app --reload
```

**Open** http://127.0.0.1:8000 in your browser. Log in with any of these test accounts (all use password: `password123`):

| Role     | Email                  | Purpose |
|----------|------------------------|---------|
| Buyer    | buyer@test.com         | Search & negotiate with merchants |
| Merchant A | a@comfortseating.com | Sell chairs & desks |
| Merchant B | b@workspacedirect.com | Sell workspaces & ergonomics |

**Try this workflow:**
1. Log in as **buyer** → Search for `chair`, quantity `50`, target price `₹4300`, delivery `7d`
2. Two merchants will negotiate automatically
3. Accept a deal → See upsell options (e.g., desk mats for bulk quantities)
4. Review & sign the agreement → Proceed to checkout (mock mode auto-confirms)
5. Log in as a **merchant** → View your negotiation analytics & audit logs

---

## What is ATOAC?

Traditional e-commerce is buyer-focused: humans visit storefronts and checkout manually. **Agentic commerce changes this:**

```
┌─────────────┐
│ User        │
└──────┬──────┘
       │
┌──────▼──────────┐
│ Buyer Agent     │ ← AI agent discovers & buys on behalf of user
│ (ChatGPT, etc)  │
└──────┬──────────┘
       │ "Find 50 office chairs, ≤₹4300/unit, 7d delivery"
       │
       ├──────────────────────┬──────────────────────┐
       │                      │                      │
    ┌──▼─────┐           ┌────▼── ┐            ┌─────▼──┐
    │ ATOAC   │          │ATOAC   │            │ Other  │
    │Merchant │          │Merchant             │ Systems
    │Agent A  │          │Agent B │            │
    └──┬─────┘           └────┬── ┘            └─────┬──┘
       │ Counter: ₹3900 ×50  │ Counter: ₹4100        │
       │ (guardrail: floor   │ Accepted!             │
       │  price ₹2000,max15% │                       │
       │  discount)          │                       │
       └──────────┬──────────┘                       │
                  │ Winner: Merchant B @ ₹4100
                  │ + Upsell: Desk Mats
                  │ = Agreement
                  │
                  └──► Razorpay (payment + verification)
```

**In short:** ATOAC is your agent. You (the merchant) define your rules—floor price, max discount, who qualifies for bulk discounts—then ATOAC negotiates on your behalf, upsells smartly, and passes the deal to checkout.

---

## Key Features

### ✅ Fully Built & Tested

| Feature | What It Does |
|---------|-------------|
| **Autonomous Merchant Agent** | Negotiates buyer requests within guardrails (floor price, max discount %, max rounds) |
| **Deterministic Guardrail** | LLM-free price/accept/reject logic ensures guardrails are **never** bypassed |
| **Multi-Merchant Negotiation** | Coordinate negotiations across multiple competing merchants in a single buyer request |
| **Negotiation Engine** | Structured offer/counter/accept/reject lifecycle with full audit trail |
| **Upsell & Cross-Sell** | Quantity-triggered rules (e.g., 30+ chairs → suggest desk mats) |
| **Agreement Generation** | Freeze negotiated terms into a legally-auditable, JSON-formatted agreement |
| **Razorpay Integration** | Create real payment links, verify webhook signatures (HMAC-SHA256), handle idempotent payments |
| **Login Rate Limiting** | 5 attempts per 5 minutes; offenders locked out |
| **Audit Logging** | Every negotiation, offer, and policy change is logged & queryable per merchant |
| **Merchant Analytics** | Track negotiation count, success rate, upsell impact, and revenue insights |
| **Buyer & Merchant UI** | Vanilla HTML/JS (no build step required); product & merchant detail pages |



---

## Installation

### Prerequisites

- **Python 3.9+** ([download](https://www.python.org/downloads/))
- **pip** (comes with Python)
- **SQLite** (built-in) or **PostgreSQL** (optional, for production)

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/atoac.git
cd atoac
```

### Step 2: Create a Virtual Environment

**On macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

### Step 3: Install Dependencies

```bash
cd atoac_saas
pip install -r requirements.txt
```

### Step 4: Configure Environment

Copy `.env.example` to `.env` and update values:

```bash
cp .env.example .env
```

Then edit `.env`:

```ini
# Database (SQLite by default, or PostgreSQL)
DATABASE_URL=sqlite:///./atoac.db

# JWT Secret (generate a strong one for production)
JWT_SECRET=your-secret-key-change-this-in-production

# Razorpay (leave blank for mock mode; set for live payments)
# RAZORPAY_KEY_ID=rzp_xxx
# RAZORPAY_KEY_SECRET=yyy
# RAZORPAY_WEBHOOK_SECRET=zzz

# Google Gemini (optional; enables natural-language negotiation summaries)
# GEMINI_API_KEY=your-key
# GEMINI_MODEL=gemini-3.5-flash

# Seed data on startup (useful for development)
SEED_ON_START=1
```

### Step 5: Seed Demo Data

```bash
python seed.py
```

This creates:
- 2 test merchants with sample products (chairs, desks, ergonomic supplies)
- 1 test buyer account
- Predefined upsell rules (e.g., bulk quantity triggers)

### Step 6: Start the Development Server

```bash
python -m uvicorn main:app --reload
```

You should see:
```
INFO:     Application startup complete
Uvicorn running on http://127.0.0.1:8000
```

---

## Usage & Demo

### Web UI

Open http://127.0.0.1:8000 in your browser.

#### Buyer Workflow

1. **Login** as `buyer@test.com` (password: `password123`)
2. **Search** for products (e.g., "chair")
3. **Enter requirements:**
   - Quantity (e.g., 50)
   - Target price per unit
   - Desired delivery time
4. **View candidates** — ATOAC finds matching merchants
5. **Review & select** — Each merchant negotiates autonomously; pick the best offer
6. **Upsell** — Accept complementary suggestions (e.g., desk mats with your chairs)
7. **Review agreement** — See the frozen terms (pricing, quantities, delivery)
8. **Checkout** — Proceed to Razorpay payment (mock mode auto-confirms)

#### Merchant Workflow

1. **Login** as `a@comfortseating.com` or `b@workspacedirect.com` (password: `password123`)
2. **Manage products:**
   - Create a new product
   - Set floor price, max discount %, max negotiation rounds
   - Edit or delete existing products
3. **View negotiations:**
   - See all active and completed negotiation histories
   - Review per-offer counters & audit trail
4. **Check analytics:**
   - Negotiation count, success rate
   - Upsell frequency & impact
   - Revenue insights
5. **Export audit logs** for compliance

### API Endpoints (Key Routes)

**Merchant endpoints:**
- `POST /merchant/signup` — Create merchant account
- `POST /merchant/login` — Login & get JWT
- `GET /merchant/products` — List your products
- `POST /merchant/products` — Create product with guardrails
- `PUT /merchant/products/{id}` — Update product
- `DELETE /merchant/products/{id}` — Delete product
- `GET /merchant/analytics` — Your negotiation metrics

**Buyer endpoints:**
- `POST /buyer/signup` — Create buyer account
- `POST /buyer/login` — Login & get JWT
- `GET /search` — Search products across merchants
- `GET /merchants/{id}` — Merchant profile
- `POST /negotiate` — Start multi-merchant negotiation
- `GET /agreements/{id}` — View agreement
- `POST /agreements/{id}/confirm` — Sign agreement

**Negotiation endpoints:**
- `GET /negotiations` — List your negotiations
- `POST /negotiations/{id}/offer` — Send counter-offer (internal use)
- `POST /negotiations/{id}/accept` — Accept negotiated terms
- `GET /negotiations/{id}/audit` — Full audit trail

**Payment endpoints:**
- `POST /checkout` — Create Razorpay payment link
- `GET /webhooks/razorpay` — Webhook receiver (HMAC-verified)

**Analytics endpoints:**
- `GET /analytics/dashboard` — Your metrics
- `GET /audit/logs` — Queryable event logs

See `main.py` for complete route definitions.

---

## Configuration

### Environment Variables (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | `sqlite:///./atoac.db` | Database connection string; supports SQLite, PostgreSQL |
| `JWT_SECRET` | **Yes** | (generated) | Secret key for JWT tokens; **must be strong in production** |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `JWT_EXPIRATION_HOURS` | No | `24` | Token expiration time |
| `RAZORPAY_KEY_ID` | No | (unset) | Razorpay Key ID (leave blank for mock mode) |
| `RAZORPAY_KEY_SECRET` | No | (unset) | Razorpay Key Secret |
| `RAZORPAY_WEBHOOK_SECRET` | No | (unset) | Razorpay webhook secret for HMAC verification |
| `GEMINI_API_KEY` | No | (unset) | Google Gemini API key (optional; enables LLM summaries) |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Gemini model name |
| `SEED_ON_START` | No | `0` | Set to `1` to auto-seed demo data on startup |

### Database Configuration

**SQLite (default, great for development):**
```ini
DATABASE_URL=sqlite:///./atoac.db
```

**PostgreSQL (recommended for production):**
```ini
DATABASE_URL=postgresql://user:password@localhost:5432/atoac
```

Database will auto-initialize on first run (`init_db()` in `config.py`).

### Razorpay Configuration

**Mock Mode (development):**
Leave `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` blank. The system will use deterministic mock responses.

**Live Mode (production):**
1. Sign up at [Razorpay](https://razorpay.com)
2. Get your Key ID & Key Secret from the dashboard
3. Set up a webhook endpoint in Razorpay pointing to `https://your-domain.com/webhooks/razorpay`
4. Copy the webhook secret into `.env`
5. Set environment variables:
   ```ini
   RAZORPAY_KEY_ID=rzp_live_xxxxx
   RAZORPAY_KEY_SECRET=yyyyy
   RAZORPAY_WEBHOOK_SECRET=zzzzz
   ```

All webhook payloads are verified with HMAC-SHA256; tampered or replayed webhooks are rejected.

---

## Architecture

### System Overview

```
┌─────────────────┐
│   Frontend UI   │ (Buyer & Merchant dashboards)
│  (HTML/JS/CSS)  │
└────────┬────────┘
         │
    ┌────▼─────────────────────────────────┐
    │        FastAPI Application            │
    │  (main.py — route handlers)           │
    ├────────────────────────────────────┤
    │  ┌─────────────────────────────┐  │
    │  │ Auth Module                 │  │ (auth.py)
    │  │ • Login/signup              │  │
    │  │ • JWT generation & verify   │  │
    │  │ • Rate limiting             │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Discovery Module            │  │ (discovery.py)
    │  │ • Product search            │  │
    │  │ • Merchant lookup           │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Negotiation Engine          │  │ (negotiation.py)
    │  │ • Guardrail enforcement     │  │
    │  │ • Offer/counter logic       │  │
    │  │ • LLM-free safety layer     │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Upsell/Cross-Sell Engine    │  │ (intent.py)
    │  │ • Rule evaluation           │  │
    │  │ • Bundle recommendations    │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Agreement Engine            │  │ (inventory.py)
    │  │ • Freeze negotiated terms   │  │
    │  │ • Generate JSON schema      │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Payment Module              │  │ (razorpay_client.py)
    │  │ • Payment link creation     │  │
    │  │ • Webhook verification      │  │
    │  │ • Idempotent processing     │  │
    │  └─────────────────────────────┘  │
    │                                    │
    │  ┌─────────────────────────────┐  │
    │  │ Analytics & Audit           │  │ (analytics.py, audit.py)
    │  │ • Metrics & insights        │  │
    │  │ • Event logging             │  │
    │  └─────────────────────────────┘  │
    └────┬─────────────────────────────┘
         │
    ┌────▼──────────────┐
    │  SQLAlchemy ORM   │
    │  (models.py)      │
    └────┬──────────────┘
         │
    ┌────▼──────────────┐
    │  SQLite / PG DB   │
    │  (atoac.db)       │
    └───────────────────┘

    ┌──────────────────┐
    │  Razorpay API    │ (External payment processor)
    │  (when live)     │
    └──────────────────┘

    ┌──────────────────┐
    │  Google Gemini   │ (Optional LLM for summaries)
    │  (when set)      │
    └──────────────────┘
```

### Core Modules

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI route handlers & WebSocket hub |
| `auth.py` | JWT, bcrypt, rate limiting |
| `models.py` | SQLAlchemy ORM (User, Merchant, Product, Negotiation, Agreement, etc.) |
| `database.py` | SQLAlchemy engine & session management |
| `config.py` | Settings from environment & `.env` |
| `discovery.py` | Product search & merchant lookup |
| `negotiation.py` | Core negotiation logic & guardrail enforcement |
| `intent.py` | Upsell/cross-sell rule evaluation |
| `inventory.py` | Agreement generation & stock management |
| `analytics.py` | Negotiation metrics & insights |
| `audit.py` | Event logging & compliance queries |
| `razorpay_client.py` | Payment link creation & webhook handling |
| `llm.py` | Optional Google Gemini integration for summaries |
| `ws_hub.py` | WebSocket connection management |

---

## Implementation Status

### ✅ Fully Built & Tested End-to-End

- ✅ Merchant + buyer signup/login with bcrypt-hashed passwords, JWT sessions
- ✅ Merchant product CRUD with ownership enforcement (403 if you try to edit another merchant's product)
- ✅ Cross-merchant product search & negotiation
- ✅ Deterministic guardrail (floor price, max discount %, max rounds) — **never bypassed by LLM**
- ✅ Upsell/cross-sell engine (quantity-triggered rules)
- ✅ Agreement generation matching JSON schema
- ✅ Razorpay integration with real Payment Link creation (mock fallback with no keys)
- ✅ Webhook signature verification (HMAC-SHA256, tested with valid/tampered/replayed payloads)
- ✅ Login rate limiting (5 attempts / 5-min lockout)
- ✅ Audit logging (DB-backed, queryable per merchant)
- ✅ Merchant analytics (negotiation count, success rate, insights)
- ✅ Buyer + Merchant frontend (vanilla HTML/JS, no build step)




---

## API Overview

### Authentication

All requests requiring authentication use **Bearer JWT tokens**:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/merchant/products
```

Tokens are obtained via `/merchant/login` or `/buyer/login`.

### Request/Response Format

All endpoints use **JSON**:

**Request:**
```bash
curl -X POST http://127.0.0.1:8000/merchant/products \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Office Chair",
    "floor_price": 2000,
    "max_discount_pct": 15,
    "max_negotiation_rounds": 5
  }'
```

**Response:**
```json
{
  "id": "prod_123",
  "name": "Office Chair",
  "merchant_id": "merch_001",
  "floor_price": 2000,
  "max_discount_pct": 15,
  "created_at": "2025-01-15T10:00:00Z"
}
```

### Error Handling

Standard HTTP status codes:

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `400` | Bad request (validation error) |
| `401` | Unauthorized (missing/invalid token) |
| `403` | Forbidden (ownership check, rate limit) |
| `404` | Not found |
| `422` | Unprocessable entity (validation) |
| `500` | Server error |

---

## Testing

Run the full test suite:

```bash
# Install test dependencies (already in requirements.txt)
pytest tests/ -v

# Run a specific test file
pytest tests/test_negotiation.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

**Key test suites:**
- `test_auth.py` — Login, JWT, rate limiting
- `test_negotiation.py` — Guardrail enforcement, offer/counter logic
- `test_core.py` — Product CRUD, ownership checks
- `test_policy.py` — Policy change workflows
- `test_ws.py` — WebSocket negotiation flows
- `test_payments.py` — Razorpay integration & webhook verification
- `test_analytics.py` — Metrics & insights

---

## Deployment

### Option 1: Render (Recommended for Beginners)

[Render](https://render.com) provides free hosting with WebSocket support.

**Steps:**
1. Push this repository to GitHub
2. Sign in to Render → **New** → **Blueprint**
3. Select this repository
4. Click **Deploy** (Render reads `render.yaml` for configuration)
5. Set secrets in Render dashboard:
   - `GEMINI_API_KEY` (if using LLM features)
   - `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (for live payments)

**Your app will be live at** `https://atoac-xxx.onrender.com`

### Option 2: Docker (Local or Cloud)

```bash
# Build image
docker build -t atoac:latest .

# Run container
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL=sqlite:///./atoac.db \
  -e JWT_SECRET=your-secret \
  atoac:latest
```

### Option 3: Heroku (Legacy)

```bash
# Install Heroku CLI
brew tap heroku/brew && brew install heroku

# Login
heroku login

# Create app
heroku create atoac-demo

# Add Procfile (already included)
# Set config vars
heroku config:set JWT_SECRET=your-secret
heroku config:set GEMINI_API_KEY=your-key

# Deploy
git push heroku main
```

### Option 4: Manual VPS (AWS EC2, DigitalOcean, Linode)

```bash
# On your VPS:
ssh user@your-server

# Clone, install, run
git clone https://github.com/your-username/atoac.git
cd atoac/atoac_saas
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 80 &
```

### Production Checklist

Before deploying to production:

- [ ] Change `JWT_SECRET` to a strong random value
- [ ] Use PostgreSQL instead of SQLite (set `DATABASE_URL`)
- [ ] Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
- [ ] Enable HTTPS (use a reverse proxy like Nginx or Let's Encrypt)
- [ ] Set up monitoring & error logging (e.g., Sentry)
- [ ] Run database migrations (auto-applied on startup)
- [ ] Test webhook endpoint (Razorpay test mode)
- [ ] Set up backups for database
- [ ] Configure CORS for your domain
- [ ] Review security checklist in `config.py`

---

## Contributing

We welcome contributions! Please follow these steps:

### 1. Fork & Clone

```bash
git clone https://github.com/your-fork/atoac.git
cd atoac
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 3. Make Changes

- Follow PEP 8 (Python style guide)
- Add docstrings to functions
- Update tests for new functionality
- Update README if adding new features

### 4. Test Your Changes

```bash
pytest tests/ -v
python -m uvicorn main:app --reload
```

### 5. Commit & Push

```bash
git add .
git commit -m "feat: add your feature description"
git push origin feature/your-feature-name
```

### 6. Open a Pull Request

Go to GitHub and open a PR from your branch to `main`. Include:
- **Description** of what changed
- **Motivation** (why this change is needed)
- **Testing** (what you tested)
- **Screenshots/GIFs** if UI changes

### Development Guidelines

- **Code Style:** Use `black` for formatting
  ```bash
  pip install black
  black .
  ```
- **Type Hints:** Add type hints to all functions
- **Tests:** Aim for >80% coverage
  ```bash
  pytest tests/ --cov=. --cov-report=term-missing
  ```
- **Docstrings:** Use Google-style docstrings
  ```python
  def negotiate(buyer_request: BuyerRequest) -> NegotiationResult:
      """Orchestrate multi-merchant negotiation.
      
      Args:
          buyer_request: The buyer's search & offer parameters.
          
      Returns:
          NegotiationResult with accepted offers per merchant.
      """
  ```

### Reporting Issues

Found a bug? Please open a [GitHub Issue](../../issues) with:
- **Title:** Brief description
- **Description:** What happened & what you expected
- **Steps to Reproduce:** Exact steps to trigger the bug
- **Environment:** OS, Python version, branch/commit
- **Logs:** Error messages or stack traces

### Architecture & Design

Before implementing large changes, please:
1. Read [ATOAC_ARCHITECTURE.md](ATOAC_ARCHITECTURE.md) to understand the design
2. Discuss in an issue or PR to get feedback
3. Reference the [Implementation Status](#implementation-status) to see what's already built

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

**TL;DR:** You can use, modify, and distribute this code freely, including for commercial purposes, as long as you include the license and don't hold us liable.

---

## Support & Community

- **Questions?** Open a [GitHub Discussion](../../discussions)
- **Found a bug?** Open a [GitHub Issue](../../issues)
- **Want to contribute?** See [Contributing](#contributing) above
- **Architecture deep-dive?** Read [ATOAC_ARCHITECTURE.md](ATOAC_ARCHITECTURE.md)
- **Email:** maintainers@atoac.dev (replace with your contact)

---


---

## Acknowledgments

- **FastAPI** — Fast, modern web framework
- **SQLAlchemy** — Flexible ORM
- **Razorpay** — Payment infrastructure
- **Google Gemini** — LLM capabilities
- **Contributors** — Thanks to all who've helped shape ATOAC

---

**Last Updated:** January 2025  
**Version:** 3.0 (Phase 1 Vertical Slice)  
**Status:** Active Development ✅

