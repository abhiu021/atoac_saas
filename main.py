"""ATOAC SaaS API — FastAPI app wiring the full vertical slice (see §30)."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

import analytics
import discovery
import intent
import inventory
import llm
import negotiation as neg_engine
import razorpay_client
from audit import log_event, query_events
from auth import (
    check_login_allowed,
    create_token,
    decode_token,
    get_current_user,
    hash_password,
    record_login_failure,
    record_login_success,
    require_buyer,
    require_merchant,
    verify_password,
)
from ws_hub import hub, is_merchant, merchant_hub, party_role
from config import settings
from database import get_db, init_db
from models import (
    Agreement,
    Basket,
    Conversation,
    Negotiation,
    Payment,
    PolicyChangeRequest,
    ProcessedWebhookEvent,
    Product,
    Reservation,
    UpsellRule,
    User,
)

# Editing any of these requires explicit merchant approval before it takes effect (§28).
MATERIAL_POLICY_FIELDS = ("list_price", "floor_price", "max_discount_pct",
                          "min_order_qty", "max_negotiation_rounds")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Populate demo accounts/products on a fresh deploy (idempotent — skips if present).
    if os.getenv("SEED_ON_START", "1") == "1":
        try:
            import seed
            seed.seed()
        except Exception as e:  # never let seeding block startup
            print("Seed skipped:", e)
    yield


app = FastAPI(title="ATOAC", version="3.0", lifespan=lifespan)


@app.middleware("http")
async def _no_cache_assets(request: Request, call_next):
    """Serve the frontend without caching so edits show up on a normal reload
    (no more stale JS/CSS/HTML)."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# --- Schemas -----------------------------------------------------------------

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    role: str  # buyer | merchant
    business_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


STRATEGIES = {"balanced", "aggressive", "firm", "clear_stock"}


class ProductIn(BaseModel):
    name: str
    description: str = ""
    list_price: float = Field(gt=0)
    floor_price: float = Field(gt=0)
    max_discount_pct: float = Field(default=10.0, ge=0, le=100)
    min_order_qty: int = Field(default=1, ge=1)
    max_negotiation_rounds: int = Field(default=3, ge=1, le=10)
    stock: int = Field(default=0, ge=0)
    delivery_days: int = Field(default=7, ge=0)
    strategy: str = "balanced"
    atoac_enabled: bool = True
    auto_negotiate: bool = True

    @field_validator("strategy")
    @classmethod
    def _valid_strategy(cls, v: str) -> str:
        return v if v in STRATEGIES else "balanced"


class UpsellRuleIn(BaseModel):
    base_product_id: int
    upsell_product_id: int
    trigger_min_qty: int = 1


class NegotiateIn(BaseModel):
    query: str
    quantity: int = Field(gt=0)
    target_price: float = Field(gt=0)
    max_delivery_days: int | None = None


class SelectIn(BaseModel):
    negotiation_uid: str


class AgreementIn(BaseModel):
    negotiation_uid: str
    accept_upsell: bool = False
    # Inventory-shortfall responses (§19.1): buyer may take fewer units now, or
    # accept a backordered full quantity with extended delivery.
    partial_quantity: int | None = None
    backorder: bool = False


class CheckoutIn(BaseModel):
    agreement_uid: str


# --- Auth --------------------------------------------------------------------

@app.post("/api/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if body.role not in ("buyer", "merchant"):
        raise HTTPException(400, "role must be 'buyer' or 'merchant'")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password),
                role=body.role, business_name=body.business_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, actor=body.email, action="auth.signup", details={"role": body.role})
    return {"token": create_token(user), "user": _user_dto(user)}


@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    check_login_allowed(body.email)
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_login_failure(body.email)
        raise HTTPException(401, "Invalid credentials")
    record_login_success(body.email)
    return {"token": create_token(user), "user": _user_dto(user)}


def _user_dto(u: User) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role, "business_name": u.business_name}


# --- Merchant: products ------------------------------------------------------

@app.post("/api/merchant/products")
def create_product(body: ProductIn, db: Session = Depends(get_db),
                   merchant: User = Depends(require_merchant)):
    if body.floor_price > body.list_price:
        raise HTTPException(400, "floor_price cannot exceed list_price")
    p = Product(merchant_id=merchant.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    log_event(db, actor=merchant.business_name or merchant.email, action="product.create",
              details={"product_id": p.id, "name": p.name}, merchant_id=merchant.id)
    return _product_dto(p, owner=True)


@app.get("/api/merchant/products")
def list_products(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    rows = db.query(Product).filter(Product.merchant_id == merchant.id).all()
    return [_product_dto(p, owner=True) for p in rows]


@app.put("/api/merchant/products/{product_id}")
def update_product(product_id: int, body: ProductIn, db: Session = Depends(get_db),
                   merchant: User = Depends(require_merchant)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if p.merchant_id != merchant.id:  # ownership enforcement — §0
        raise HTTPException(403, "Not your product")
    if body.floor_price > body.list_price:
        raise HTTPException(400, "floor_price cannot exceed list_price")

    payload = body.model_dump()
    # Material policy changes are queued for approval; everything else applies now (§28).
    material_diff = {f: {"old": getattr(p, f), "new": payload[f]}
                     for f in MATERIAL_POLICY_FIELDS if getattr(p, f) != payload[f]}
    for k, v in payload.items():
        if k not in MATERIAL_POLICY_FIELDS:
            setattr(p, k, v)
    db.commit()

    pending = None
    if material_diff:
        existing = (db.query(PolicyChangeRequest)
                    .filter(PolicyChangeRequest.product_id == p.id,
                            PolicyChangeRequest.status == "PENDING").first())
        if existing:
            raise HTTPException(409, "A pending policy change already exists for this product; "
                                     "approve or reject it first.")
        req = PolicyChangeRequest(merchant_id=merchant.id, product_id=p.id,
                                  changes_json=json.dumps(material_diff), status="PENDING")
        db.add(req)
        db.commit()
        db.refresh(req)
        pending = _policy_change_dto(req, p.name)
        log_event(db, actor=merchant.business_name or merchant.email,
                  action="policy_change.proposed",
                  details={"product_id": p.id, "request_id": req.id, "changes": material_diff},
                  merchant_id=merchant.id)

    log_event(db, actor=merchant.business_name or merchant.email, action="product.update",
              details={"product_id": p.id, "name": p.name,
                       "queued_policy_change": bool(material_diff)}, merchant_id=merchant.id)
    dto = _product_dto(p, owner=True)
    dto["pending_policy_change"] = pending
    return dto


@app.post("/api/merchant/products/{product_id}/image")
async def upload_product_image(product_id: int, file: UploadFile = File(...), 
                               db: Session = Depends(get_db),
                               merchant: User = Depends(require_merchant)):
    """Upload an image for a product. Stores as base64 data URL or file path."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if p.merchant_id != merchant.id:
        raise HTTPException(403, "Not your product")
    
    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"File type not allowed. Allowed: {', '.join(allowed_types)}")
    
    # Validate file size (max 5MB)
    file_size = (await file.read()).__sizeof__()
    await file.seek(0)
    if file_size > 5 * 1024 * 1024:
        raise HTTPException(400, "File size exceeds 5MB limit")
    
    # Store as base64 data URL (simple approach, suitable for prototyping)
    import base64
    file_content = await file.read()
    base64_content = base64.b64encode(file_content).decode('utf-8')
    image_url = f"data:{file.content_type};base64,{base64_content}"
    
    # Alternative: store in /uploads directory and use URL path
    # (uncomment to use file-based storage instead)
    # os.makedirs("frontend/uploads", exist_ok=True)
    # filename = f"{product_id}_{int(datetime.now(timezone.utc).timestamp())}.{file.filename.split('.')[-1]}"
    # filepath = f"frontend/uploads/{filename}"
    # with open(filepath, "wb") as f:
    #     f.write(file_content)
    # image_url = f"/uploads/{filename}"
    
    p.image_url = image_url
    db.commit()
    
    log_event(db, actor=merchant.business_name or merchant.email, action="product.image_upload",
              details={"product_id": p.id, "product_name": p.name}, merchant_id=merchant.id)
    
    return {"success": True, "image_url": image_url}


@app.get("/api/merchant/policy-changes")
def list_policy_changes(status: str = "PENDING", db: Session = Depends(get_db),
                        merchant: User = Depends(require_merchant)):
    q = db.query(PolicyChangeRequest).filter(PolicyChangeRequest.merchant_id == merchant.id)
    if status:
        q = q.filter(PolicyChangeRequest.status == status.upper())
    rows = q.order_by(PolicyChangeRequest.created_at.desc()).all()
    names = {p.id: p.name for p in db.query(Product).filter(Product.merchant_id == merchant.id)}
    return [_policy_change_dto(r, names.get(r.product_id)) for r in rows]


@app.post("/api/merchant/policy-changes/{request_id}/approve")
def approve_policy_change(request_id: int, db: Session = Depends(get_db),
                          merchant: User = Depends(require_merchant)):
    req = _get_pending_change(db, request_id, merchant)
    product = db.get(Product, req.product_id)
    changes = json.loads(req.changes_json)
    for field, delta in changes.items():
        setattr(product, field, delta["new"])
    if product.floor_price > product.list_price:  # revalidate against current state
        raise HTTPException(400, "Applying this change would put floor_price above list_price")
    req.status = "APPROVED"
    req.resolved_at = datetime.now(timezone.utc)
    db.commit()
    log_event(db, actor=merchant.business_name or merchant.email, action="policy_change.approved",
              details={"request_id": req.id, "product_id": product.id, "changes": changes},
              merchant_id=merchant.id)
    return {"request_id": req.id, "status": "APPROVED",
            "product": _product_dto(product, owner=True)}


@app.post("/api/merchant/policy-changes/{request_id}/reject")
def reject_policy_change(request_id: int, db: Session = Depends(get_db),
                         merchant: User = Depends(require_merchant)):
    req = _get_pending_change(db, request_id, merchant)
    req.status = "REJECTED"
    req.resolved_at = datetime.now(timezone.utc)
    db.commit()
    log_event(db, actor=merchant.business_name or merchant.email, action="policy_change.rejected",
              details={"request_id": req.id, "product_id": req.product_id}, merchant_id=merchant.id)
    return {"request_id": req.id, "status": "REJECTED"}


@app.delete("/api/merchant/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db),
                   merchant: User = Depends(require_merchant)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if p.merchant_id != merchant.id:
        raise HTTPException(403, "Not your product")
    db.delete(p)
    db.commit()
    log_event(db, actor=merchant.business_name or merchant.email, action="product.delete",
              details={"product_id": product_id}, merchant_id=merchant.id)
    return {"deleted": product_id}


@app.post("/api/merchant/upsell-rules")
def create_upsell_rule(body: UpsellRuleIn, db: Session = Depends(get_db),
                       merchant: User = Depends(require_merchant)):
    for pid in (body.base_product_id, body.upsell_product_id):
        p = db.get(Product, pid)
        if not p or p.merchant_id != merchant.id:
            raise HTTPException(403, f"Product {pid} is not yours")
    rule = UpsellRule(merchant_id=merchant.id, **body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    log_event(db, actor=merchant.business_name or merchant.email, action="upsell_rule.create",
              details={"rule_id": rule.id}, merchant_id=merchant.id)
    return {"id": rule.id, "base_product_id": rule.base_product_id,
            "upsell_product_id": rule.upsell_product_id, "trigger_min_qty": rule.trigger_min_qty}


@app.get("/api/merchant/upsell-rules")
def list_upsell_rules(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    rows = db.query(UpsellRule).filter(UpsellRule.merchant_id == merchant.id).all()
    return [{"id": r.id, "base_product_id": r.base_product_id,
             "upsell_product_id": r.upsell_product_id, "trigger_min_qty": r.trigger_min_qty}
            for r in rows]


@app.delete("/api/merchant/upsell-rules/{rule_id}")
def delete_upsell_rule(rule_id: int, db: Session = Depends(get_db),
                       merchant: User = Depends(require_merchant)):
    rule = db.get(UpsellRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    if rule.merchant_id != merchant.id:
        raise HTTPException(403, "Not your rule")
    db.delete(rule)
    db.commit()
    log_event(db, actor=merchant.business_name or merchant.email, action="upsell_rule.delete",
              details={"rule_id": rule_id}, merchant_id=merchant.id)
    return {"deleted": rule_id}


# --- Merchant: analytics + audit ---------------------------------------------

@app.get("/api/merchant/analytics")
def merchant_analytics(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    return analytics.compute(db, merchant.id)


class PolicySuggestionIn(BaseModel):
    product_id: int
    floor_price: float


@app.post("/api/merchant/policy-suggestion")
def apply_policy_suggestion(body: PolicySuggestionIn, db: Session = Depends(get_db),
                            merchant: User = Depends(require_merchant)):
    """Apply an analytics-suggested floor as a PENDING policy change (§17). The
    merchant still approves it in the normal workflow before it takes effect."""
    p = db.get(Product, body.product_id)
    if not p or p.merchant_id != merchant.id:
        raise HTTPException(403, "Not your product")
    new_floor = round(body.floor_price, 2)
    if new_floor > p.list_price:
        raise HTTPException(400, "floor_price cannot exceed list_price")
    if new_floor == p.floor_price:
        raise HTTPException(400, "Floor is already at that value")
    if (db.query(PolicyChangeRequest)
            .filter(PolicyChangeRequest.product_id == p.id, PolicyChangeRequest.status == "PENDING").first()):
        raise HTTPException(409, "A pending policy change already exists for this product.")
    diff = {"floor_price": {"old": p.floor_price, "new": new_floor}}
    req = PolicyChangeRequest(merchant_id=merchant.id, product_id=p.id,
                              changes_json=json.dumps(diff), status="PENDING")
    db.add(req)
    db.commit()
    db.refresh(req)
    log_event(db, actor=merchant.business_name or merchant.email, action="policy_change.proposed",
              details={"product_id": p.id, "request_id": req.id, "changes": diff, "source": "analytics"},
              merchant_id=merchant.id)
    return _policy_change_dto(req, p.name)


@app.get("/api/merchant/audit")
def merchant_audit(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    return query_events(db, merchant_id=merchant.id, limit=100)


# --- Buyer flow --------------------------------------------------------------

@app.post("/api/buyer/negotiate")
async def buyer_negotiate(body: NegotiateIn, db: Session = Depends(get_db),
                          buyer: User = Depends(require_buyer)):
    products = discovery.search_products(db, body.query)
    ranked = discovery.top_n(discovery.filter_and_rank(products, body.quantity, body.max_delivery_days))
    if not ranked:
        return {"query": body.query, "results": [], "message": "No ATOAC-enabled merchant can fulfil this."}

    # Concurrent gateway (§5): each merchant negotiation runs in its own thread with
    # its own DB session. gather preserves order, so results stay in ranked order.
    product_ids = [p.id for p in ranked]
    buyer_id = buyer.id
    results = await asyncio.gather(*[
        asyncio.to_thread(neg_engine.negotiate_new_session, pid, buyer_id,
                          body.quantity, body.target_price, body.max_delivery_days)
        for pid in product_ids
    ])
    results = list(results)
    agreed = [r for r in results if r["status"] == "AGREED"]
    best = min(agreed, key=lambda r: r["total"]) if agreed else None
    return {
        "query": body.query,
        "results": results,
        "concurrency": "parallel",
        "recommended_negotiation_uid": best["negotiation_uid"] if best else None,
    }


def _party_negotiation(db: Session, uid: str, user: User) -> Negotiation:
    neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
    if not neg:
        raise HTTPException(404, "Negotiation not found")
    if user.id not in (neg.buyer_id, neg.merchant_id):
        raise HTTPException(403, "Not a party to this negotiation")
    return neg


def _party_role(neg: Negotiation, user: User) -> str:
    return "buyer" if user.id == neg.buyer_id else "merchant"


@app.get("/api/negotiations/{uid}")
def get_negotiation(uid: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Standalone negotiation lookup / chat state (§21). Visible to the buyer or the
    merchant party. Returns the full message log + offer trail. No floor price."""
    neg = _party_negotiation(db, uid, user)
    state = neg_engine.state_dict(db, neg)
    state["your_role"] = _party_role(neg, user)
    state["reason"] = neg.reason
    state["rounds"] = neg.rounds
    state["offers"] = [
        {"round": o.round, "actor": o.actor, "unit_price": o.unit_price,
         "accepted": o.accepted, "reason_code": o.reason_code, "note": o.note}
        for o in neg.offers
    ]
    return state


class StartNegotiationIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    target_price: float = Field(gt=0)
    max_delivery_days: int | None = None
    pause_agent: bool = False  # buyer starts with their agent paused (drives manually)


class ControlIn(BaseModel):
    mode: str  # AGENT | HUMAN


class ActIn(BaseModel):
    action: str  # offer | counter | accept | reject | message
    price: float | None = None
    text: str | None = None


class IntentIn(BaseModel):
    message: str


class SayIn(BaseModel):
    message: str


class ConversationSaveIn(BaseModel):
    title: str | None = None
    items: list | None = None


def _conv_dto(c: Conversation, full: bool = False) -> dict:
    dto = {"uid": c.uid, "title": c.title,
           "updated_at": c.updated_at.isoformat() if c.updated_at else None}
    if full:
        dto["items"] = json.loads(c.items_json or "[]")
    return dto


def _get_buyer_conversation(db: Session, uid: str, buyer: User) -> Conversation:
    c = db.query(Conversation).filter(Conversation.uid == uid).first()
    if not c:
        raise HTTPException(404, "Conversation not found")
    if c.buyer_id != buyer.id:
        raise HTTPException(403, "Not your conversation")
    return c


@app.get("/api/buyer/conversations")
def list_conversations(db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    rows = (db.query(Conversation).filter(Conversation.buyer_id == buyer.id)
            .order_by(Conversation.updated_at.desc()).all())
    return [_conv_dto(c) for c in rows]


@app.post("/api/buyer/conversations")
def create_conversation(db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    import uuid
    c = Conversation(uid=f"conv_{uuid.uuid4().hex[:8]}", buyer_id=buyer.id, title="New chat")
    db.add(c)
    db.commit()
    db.refresh(c)
    return _conv_dto(c, full=True)


@app.get("/api/buyer/conversations/{uid}")
def get_conversation(uid: str, db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    return _conv_dto(_get_buyer_conversation(db, uid, buyer), full=True)


@app.put("/api/buyer/conversations/{uid}")
def save_conversation(uid: str, body: ConversationSaveIn, db: Session = Depends(get_db),
                      buyer: User = Depends(require_buyer)):
    c = _get_buyer_conversation(db, uid, buyer)
    if body.title is not None:
        c.title = body.title[:80]
    if body.items is not None:
        c.items_json = json.dumps(body.items)
    db.commit()
    return _conv_dto(c)


@app.delete("/api/buyer/conversations/{uid}")
def delete_conversation(uid: str, db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    c = _get_buyer_conversation(db, uid, buyer)
    db.delete(c)
    db.commit()
    return {"deleted": uid}


@app.post("/api/buyer/intent")
def buyer_intent(body: IntentIn, buyer: User = Depends(require_buyer)):
    """Parse a natural-language buying request into a structured RFQ (§7)."""
    rfq = intent.parse_rfq(body.message)
    missing = [f for f in ("query", "quantity", "target_price") if rfq.get(f) in (None, "")]
    return {"rfq": rfq, "missing": missing}


@app.post("/api/buyer/basket-intent")
def buyer_basket_intent(body: IntentIn, buyer: User = Depends(require_buyer)):
    """Parse a multi-item request into line items for a basket negotiation."""
    return {"lines": intent.parse_basket(body.message)}


@app.post("/api/buyer/ask")
def buyer_ask(body: IntentIn, buyer: User = Depends(require_buyer)):
    """Free-form Q&A: answer general/off-topic questions conversationally (LLM when
    enabled, safe template otherwise). Never quotes live prices/stock — those come
    from real negotiation, so the guardrail is untouched."""
    return {"answer": llm.assistant_answer(body.message)}


class BasketCheckoutIn(BaseModel):
    negotiation_uids: list[str]


@app.post("/api/buyer/basket/checkout")
def buyer_basket_checkout(body: BasketCheckoutIn, db: Session = Depends(get_db),
                          buyer: User = Depends(require_buyer)):
    """Turn a set of AGREED negotiations (one per basket line, possibly across
    merchants) into per-line agreements grouped under one Basket, and check them
    all out. Lines that lost stock are reported as unavailable, not charged."""
    if not body.negotiation_uids:
        raise HTTPException(400, "No lines to check out")
    import uuid
    basket = Basket(uid=f"bsk_{uuid.uuid4().hex[:8]}", buyer_id=buyer.id, status="AGREED", total=0)
    db.add(basket)
    db.commit()
    db.refresh(basket)

    lines, total, mode, any_pending = [], 0.0, "mock", False
    for uid in dict.fromkeys(body.negotiation_uids):  # dedupe, keep order
        neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
        if not neg or neg.buyer_id != buyer.id or neg.status != "AGREED":
            lines.append({"negotiation_uid": uid, "status": "INVALID"})
            continue
        product, merchant = db.get(Product, neg.product_id), db.get(User, neg.merchant_id)
        mname = (merchant.business_name or "Merchant") if merchant else "—"
        base_line = {"negotiation_uid": uid, "merchant_name": mname,
                     "product_name": product.name if product else "—", "quantity": neg.quantity,
                     "unit_price": neg.final_unit_price}

        agr = db.query(Agreement).filter(Agreement.negotiation_id == neg.id).first()
        if agr:
            agr.basket_id = basket.id
            db.commit()
        else:
            built = _build_agreement(db, buyer, neg, basket_id=basket.id)
            if isinstance(built, dict):  # stock dropped
                lines.append({**base_line, "status": "UNAVAILABLE"})
                continue
            agr = built

        res = _do_checkout(db, buyer, agr)
        if res.get("inventory_shortfall"):
            lines.append({**base_line, "status": "UNAVAILABLE"})
            continue
        mode = res.get("mode", mode)
        if res["status"] == "PAYMENT_PENDING":
            any_pending = True
        total += agr.total
        lines.append({**base_line, "agreement_uid": agr.uid, "total": agr.total,
                      "status": res["status"], "payment_link": res.get("payment_link")})

    basket.total = round(total, 2)
    ok = [l for l in lines if l.get("status") in ("CONFIRMED", "PAYMENT_PENDING")]
    basket.status = ("CONFIRMED" if ok and len(ok) == len(lines) and not any_pending
                     else "PAYMENT_PENDING" if any_pending
                     else "PARTIAL" if ok else "AGREED")
    db.commit()
    log_event(db, actor=buyer.email, action="basket.checkout",
              details={"basket_uid": basket.uid, "lines": len(lines), "total": basket.total})
    return {"basket_uid": basket.uid, "status": basket.status, "total": basket.total,
            "mode": mode, "lines": lines}


@app.post("/api/negotiations/{uid}/say")
def say_negotiation(uid: str, body: SayIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Natural-language negotiation turn: interpret the message and apply it. The
    guardrail still authorizes any resulting price (a human merchant can't breach
    the floor)."""
    neg = _party_negotiation(db, uid, user)
    product = db.get(Product, neg.product_id)
    role = _party_role(neg, user)
    act = intent.parse_action(body.message)
    try:
        if act["action"] == "message":
            neg_engine.human_act(db, neg, product, role, "message", text=act["text"])
        else:
            control = neg.buyer_control if role == "buyer" else neg.merchant_control
            if control != "HUMAN":  # auto-pause this side so its human can act
                neg_engine.set_control(db, neg, role, "HUMAN")
            neg_engine.human_act(db, neg, product, role, act["action"],
                                 price=act.get("price"), text=act["text"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_negotiation(uid, db, user)


@app.get("/api/buyer/search")
def buyer_search(query: str, quantity: int = 1, max_delivery_days: int | None = None,
                 db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    """Discovery only — return ATOAC-enabled candidates for the buyer to negotiate with."""
    products = discovery.search_products(db, query)
    ranked = discovery.top_n(discovery.filter_and_rank(products, quantity, max_delivery_days))
    out = []
    for p in ranked:
        merchant = db.get(User, p.merchant_id)
        dto = _product_dto(p, owner=False)
        dto["merchant_name"] = merchant.business_name or "Merchant"
        out.append(dto)
    return {"query": query, "candidates": out}


@app.post("/api/negotiations/start")
def start_negotiation(body: StartNegotiationIn, db: Session = Depends(get_db),
                      buyer: User = Depends(require_buyer)):
    product = db.get(Product, body.product_id)
    if not product or not product.atoac_enabled:
        raise HTTPException(404, "Product not available for negotiation")
    neg = neg_engine.start(db, buyer, product, body.quantity, body.target_price,
                           body.max_delivery_days,
                           buyer_control="HUMAN" if body.pause_agent else "AGENT",
                           # Respect the merchant's per-product setting: manual sellers
                           # negotiate every deal themselves (agent won't auto-respond).
                           merchant_control="AGENT" if product.auto_negotiate else "HUMAN")
    return neg_engine.state_dict(db, neg) | {"your_role": "buyer"}


@app.post("/api/negotiations/{uid}/step")
def step_negotiation(uid: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    neg = _party_negotiation(db, uid, user)
    product = db.get(Product, neg.product_id)
    neg_engine.step_once(db, neg, product)
    return get_negotiation(uid, db, user)


@app.post("/api/negotiations/{uid}/control")
def control_negotiation(uid: str, body: ControlIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    if body.mode not in ("AGENT", "HUMAN"):
        raise HTTPException(400, "mode must be AGENT or HUMAN")
    neg = _party_negotiation(db, uid, user)
    role = _party_role(neg, user)
    neg_engine.set_control(db, neg, role, body.mode)
    return get_negotiation(uid, db, user)


@app.post("/api/negotiations/{uid}/act")
def act_negotiation(uid: str, body: ActIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    neg = _party_negotiation(db, uid, user)
    product = db.get(Product, neg.product_id)
    role = _party_role(neg, user)
    try:
        neg_engine.human_act(db, neg, product, role, body.action, body.price, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_negotiation(uid, db, user)


@app.get("/api/merchant/negotiations")
def merchant_negotiations(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    """Threads the merchant is a party to — for the live-negotiations view."""
    rows = (db.query(Negotiation).filter(Negotiation.merchant_id == merchant.id)
            .order_by(Negotiation.created_at.desc()).limit(30).all())
    out = []
    for n in rows:
        product = db.get(Product, n.product_id)
        out.append({
            "negotiation_uid": n.uid, "product_name": product.name if product else None,
            "quantity": n.quantity, "status": n.status, "reason_code": n.reason_code,
            "turn": n.turn, "merchant_control": n.merchant_control,
            "final_unit_price": n.final_unit_price, "total": n.total,
            "waiting_for_merchant": n.turn == "merchant" and n.merchant_control == "HUMAN",
            "created_at": n.created_at.isoformat() if n.created_at else None,
        })
    return out


@app.post("/api/buyer/select")
def buyer_select(body: SelectIn, db: Session = Depends(get_db),
                 buyer: User = Depends(require_buyer)):
    neg = _get_buyer_negotiation(db, body.negotiation_uid, buyer)
    if neg.status != "AGREED":
        raise HTTPException(400, "Cannot select a negotiation that did not agree")
    upsell = _find_upsell(db, neg)
    return {"negotiation_uid": neg.uid, "upsell": upsell}


@app.post("/api/buyer/agreement")
def buyer_agreement(body: AgreementIn, db: Session = Depends(get_db),
                    buyer: User = Depends(require_buyer)):
    neg = _get_buyer_negotiation(db, body.negotiation_uid, buyer)
    if neg.status != "AGREED":
        raise HTTPException(400, "Negotiation is not in AGREED state")
    if db.query(Agreement).filter(Agreement.negotiation_id == neg.id).first():
        raise HTTPException(409, "Agreement already exists for this negotiation")
    if body.partial_quantity is not None and not (0 < body.partial_quantity <= neg.quantity):
        raise HTTPException(400, "partial_quantity out of range")
    result = _build_agreement(db, buyer, neg, accept_upsell=body.accept_upsell,
                              backorder=body.backorder, partial_quantity=body.partial_quantity)
    return result if isinstance(result, dict) else _agreement_dto(result)


def _build_agreement(db, buyer, neg, accept_upsell=False, backorder=False,
                     partial_quantity=None, basket_id=None):
    """Create an Agreement for an AGREED negotiation (reserving stock). Returns the
    Agreement, or an {inventory_shortfall, alternatives} dict if stock dropped."""
    base = db.get(Product, neg.product_id)
    base_qty = partial_quantity if partial_quantity is not None else neg.quantity
    delivery_days = base.delivery_days + (settings.RESTOCK_LEAD_DAYS if backorder else 0)

    base_reservation = None
    if not backorder:
        base_reservation = inventory.reserve(db, base.id, base_qty, negotiation_id=neg.id)
        if base_reservation is None:
            return {"inventory_shortfall": {
                        "product_id": base.id, "product_name": base.name, "requested": base_qty,
                        "available": inventory.available_stock(db, base.id)},
                    "alternatives": inventory.build_alternatives(db, neg, base_qty)}

    items = [{"product_id": base.id, "name": base.name, "quantity": base_qty, "unit_price": neg.final_unit_price}]
    total = round(neg.final_unit_price * base_qty, 2)

    upsell_reservation = None
    if accept_upsell:
        upsell = _find_upsell(db, neg)
        if upsell:
            upsell_reservation = inventory.reserve(db, upsell["product_id"], upsell["quantity"], negotiation_id=neg.id)
            if upsell_reservation is not None:
                items.append({"product_id": upsell["product_id"], "name": upsell["name"],
                              "quantity": upsell["quantity"], "unit_price": upsell["unit_price"]})
                total = round(total + upsell["total"], 2)

    import uuid
    agr = Agreement(uid=f"agr_{uuid.uuid4().hex[:8]}", negotiation_id=neg.id, buyer_id=buyer.id,
                    merchant_id=neg.merchant_id, items_json=json.dumps(items), delivery_days=delivery_days,
                    total=total, backorder=backorder, basket_id=basket_id, status="AGREED")
    db.add(agr)
    db.commit()
    db.refresh(agr)
    for r in (base_reservation, upsell_reservation):
        if r is not None:
            r.agreement_id = agr.id
    db.commit()
    log_event(db, actor=buyer.email, action="agreement.create",
              details={"agreement_uid": agr.uid, "total": total, "items": len(items),
                       "backorder": backorder, "basket": basket_id is not None},
              merchant_id=neg.merchant_id)
    return agr


@app.post("/api/buyer/checkout")
def buyer_checkout(body: CheckoutIn, db: Session = Depends(get_db),
                   buyer: User = Depends(require_buyer)):
    agr = db.query(Agreement).filter(Agreement.uid == body.agreement_uid).first()
    if not agr:
        raise HTTPException(404, "Agreement not found")
    if agr.buyer_id != buyer.id:
        raise HTTPException(403, "Not your agreement")
    if agr.status in ("PAYMENT_PENDING", "CONFIRMED"):
        raise HTTPException(409, f"Agreement already in {agr.status}")
    return _do_checkout(db, buyer, agr)


def _do_checkout(db, buyer, agr) -> dict:
    """Reserve → pay → confirm one agreement. Returns a result dict (or a shortfall)."""
    if not agr.backorder:
        shortfall = _ensure_reservations(db, agr)
        if shortfall is not None:
            return shortfall
    # Amount is computed from the agreement total — NEVER from the client (§14).
    link = razorpay_client.create_payment_link(agr.total, agr.uid, buyer.email)
    payment = Payment(agreement_id=agr.id, razorpay_id=link["razorpay_id"],
                      amount=agr.total, payment_link=link["payment_link"], status="PENDING")
    db.add(payment)
    db.commit()
    if link["mode"] == "mock":
        payment.status = "CONFIRMED"
        agr.status = "CONFIRMED"
        inventory.consume_for_agreement(db, agr.id)
        log_event(db, actor="razorpay(mock)", action="payment.confirmed",
                  details={"agreement_uid": agr.uid, "amount": agr.total}, merchant_id=agr.merchant_id)
    else:
        agr.status = "PAYMENT_PENDING"
    db.commit()
    return {"agreement_uid": agr.uid, "status": agr.status, "amount": agr.total,
            "payment_link": link["payment_link"], "mode": link["mode"]}


# --- Webhook -----------------------------------------------------------------

@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not razorpay_client.verify_webhook_signature(raw, signature):
        raise HTTPException(400, "Invalid webhook signature")

    payload = json.loads(raw)
    event_id = request.headers.get("x-razorpay-event-id") or payload.get("id") or signature
    if db.query(ProcessedWebhookEvent).filter(ProcessedWebhookEvent.event_id == event_id).first():
        return {"status": "duplicate_ignored"}  # idempotent (§14)
    db.add(ProcessedWebhookEvent(event_id=event_id))
    db.commit()

    event = payload.get("event", "")
    reference_id = _extract_reference_id(payload)
    agr = (db.query(Agreement).filter(Agreement.uid == reference_id).first()
           if reference_id else None)

    SUCCESS = ("payment_link.paid", "payment.captured")
    FAILURE = ("payment.failed", "payment_link.cancelled", "payment_link.expired")

    if agr and event in SUCCESS and agr.status != "CONFIRMED":
        agr.status = "CONFIRMED"
        pay = _latest_payment(db, agr.id)
        if pay:
            pay.status = "CONFIRMED"
        inventory.consume_for_agreement(db, agr.id)
        log_event(db, actor="razorpay", action="payment.confirmed",
                  details={"agreement_uid": agr.uid, "event": event}, merchant_id=agr.merchant_id)
        db.commit()

    elif agr and event in FAILURE and agr.status not in ("CONFIRMED", "FAILED"):
        # Free the held stock so it's available to others; buyer may retry checkout.
        agr.status = "FAILED"
        pay = _latest_payment(db, agr.id)
        if pay:
            pay.status = "FAILED"
        inventory.release_for_agreement(db, agr.id)
        log_event(db, actor="razorpay", action="payment.failed",
                  details={"agreement_uid": agr.uid, "event": event}, merchant_id=agr.merchant_id)
        db.commit()

    return {"status": "processed", "event": event}


# --- Helpers -----------------------------------------------------------------

def _get_buyer_negotiation(db: Session, uid: str, buyer: User) -> Negotiation:
    neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
    if not neg:
        raise HTTPException(404, "Negotiation not found")
    if neg.buyer_id != buyer.id:
        raise HTTPException(403, "Not your negotiation")
    return neg


def _find_upsell(db: Session, neg: Negotiation) -> dict | None:
    rule = (db.query(UpsellRule)
            .filter(UpsellRule.base_product_id == neg.product_id,
                    UpsellRule.merchant_id == neg.merchant_id,
                    UpsellRule.trigger_min_qty <= neg.quantity)
            .first())
    if not rule:
        return None
    up = db.get(Product, rule.upsell_product_id)
    if not up or up.stock < neg.quantity:
        return None
    return {
        "product_id": up.id, "name": up.name, "unit_price": up.list_price,
        "quantity": neg.quantity, "total": round(up.list_price * neg.quantity, 2),
        "reason": f"Buyers ordering {rule.trigger_min_qty}+ often add {up.name}.",
    }


def _get_pending_change(db: Session, request_id: int, merchant: User) -> PolicyChangeRequest:
    req = db.get(PolicyChangeRequest, request_id)
    if not req:
        raise HTTPException(404, "Policy change request not found")
    if req.merchant_id != merchant.id:
        raise HTTPException(403, "Not your policy change request")
    if req.status != "PENDING":
        raise HTTPException(409, f"Request already {req.status}")
    return req


def _policy_change_dto(req: PolicyChangeRequest, product_name: str | None) -> dict:
    return {
        "request_id": req.id,
        "product_id": req.product_id,
        "product_name": product_name,
        "changes": json.loads(req.changes_json),
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


def _latest_payment(db: Session, agreement_id: int) -> Payment | None:
    return (db.query(Payment).filter(Payment.agreement_id == agreement_id)
            .order_by(Payment.id.desc()).first())


def _held_qty(db: Session, agreement_id: int, product_id: int) -> int:
    from sqlalchemy import func
    return int(db.query(func.coalesce(func.sum(Reservation.quantity), 0))
              .filter(Reservation.agreement_id == agreement_id,
                      Reservation.product_id == product_id,
                      Reservation.status == "HELD").scalar())


def _ensure_reservations(db: Session, agr: Agreement) -> dict | None:
    """Make sure every line of an agreement is currently held. Reserves any missing
    quantity; on shortfall returns the alternatives payload instead of raising."""
    inventory.release_expired(db)
    neg = db.get(Negotiation, agr.negotiation_id)
    for item in json.loads(agr.items_json):
        need = item["quantity"] - _held_qty(db, agr.id, item["product_id"])
        if need <= 0:
            continue
        r = inventory.reserve(db, item["product_id"], need, negotiation_id=neg.id)
        if r is None:
            alts = (inventory.build_alternatives(db, neg, item["quantity"])
                    if item["product_id"] == neg.product_id else [])
            return {
                "inventory_shortfall": {
                    "product_id": item["product_id"], "product_name": item["name"],
                    "requested": item["quantity"],
                    "available": inventory.available_stock(db, item["product_id"]),
                },
                "alternatives": alts,
            }
        r.agreement_id = agr.id
        db.commit()
    return None


def _extract_reference_id(payload: dict) -> str | None:
    entities = payload.get("payload", {})
    for key in ("payment_link", "payment", "order"):
        entity = entities.get(key, {}).get("entity", {})
        ref = entity.get("reference_id") or entity.get("notes", {}).get("agreement_uid")
        if ref:
            return ref
    return None


def _product_dto(p: Product, owner: bool = False) -> dict:
    dto = {"id": p.id, "merchant_id": p.merchant_id, "name": p.name,
           "description": p.description, "list_price": p.list_price, "stock": p.stock,
           "delivery_days": p.delivery_days, "min_order_qty": p.min_order_qty,
           "atoac_enabled": p.atoac_enabled}
    if owner:  # private policy fields returned ONLY to the owning merchant (§6.1)
        dto.update({"floor_price": p.floor_price, "max_discount_pct": p.max_discount_pct,
                    "max_negotiation_rounds": p.max_negotiation_rounds,
                    "strategy": p.strategy or "balanced",
                    "auto_negotiate": bool(p.auto_negotiate)})
    return dto


def _agreement_dto(a: Agreement) -> dict:
    return {"agreement_uid": a.uid, "negotiation_id": a.negotiation_id, "buyer_id": a.buyer_id,
            "merchant_id": a.merchant_id, "items": json.loads(a.items_json),
            "delivery_days": a.delivery_days, "total": a.total, "backorder": a.backorder,
            "status": a.status}


# --- WebSocket: live negotiations --------------------------------------------

@app.websocket("/ws/negotiations/{uid}")
async def ws_negotiation(websocket: WebSocket, uid: str, token: str = ""):
    """Live negotiation stream. Auth via ?token= (browsers can't set WS headers).
    Server pushes full state on connect and after every change, and auto-advances
    agent turns. Clients send {type: say|act|control|step} to drive their side."""
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        await websocket.close(code=4401)
        return
    role = await asyncio.to_thread(party_role, uid, user_id)
    if not role:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await hub.register(uid, websocket)
    try:
        await hub.send_state(uid, websocket)
        await hub.ensure_driver(uid)
        while True:
            msg = await websocket.receive_json()
            await hub.handle(uid, role, msg, websocket)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.unregister(uid, websocket)


@app.websocket("/ws/merchant")
async def ws_merchant(websocket: WebSocket, token: str = ""):
    """Account-level notification stream for a merchant's dashboards."""
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        await websocket.close(code=4401)
        return
    if not await asyncio.to_thread(is_merchant, user_id):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    await merchant_hub.register(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive pings; content ignored
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        merchant_hub.unregister(user_id, websocket)


# --- Order history -----------------------------------------------------------

def _order_dto(db: Session, a: Agreement, counterparty: str) -> dict:
    pay = _latest_payment(db, a.id)
    return {
        "agreement_uid": a.uid, "items": json.loads(a.items_json), "total": a.total,
        "delivery_days": a.delivery_days, "backorder": a.backorder, "status": a.status,
        "payment_status": pay.status if pay else None,
        "counterparty": counterparty,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@app.get("/api/buyer/orders")
def buyer_orders(db: Session = Depends(get_db), buyer: User = Depends(require_buyer)):
    rows = (db.query(Agreement).filter(Agreement.buyer_id == buyer.id)
            .order_by(Agreement.created_at.desc()).all())
    out = []
    for a in rows:
        m = db.get(User, a.merchant_id)
        out.append(_order_dto(db, a, m.business_name or "Merchant" if m else "—"))
    return out


@app.get("/api/merchant/orders")
def merchant_orders(db: Session = Depends(get_db), merchant: User = Depends(require_merchant)):
    rows = (db.query(Agreement).filter(Agreement.merchant_id == merchant.id)
            .order_by(Agreement.created_at.desc()).all())
    out = []
    for a in rows:
        b = db.get(User, a.buyer_id)
        out.append(_order_dto(db, a, b.email if b else "—"))
    return out


# --- Static frontend (mounted last so /api/* routes win) ---------------------

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
