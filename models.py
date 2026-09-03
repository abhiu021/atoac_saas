"""Core database model (see ATOAC_ARCHITECTURE.md §22).

Deliberate simplifications vs. the v2.0 spec:
  - `User` combines the spec's `merchants` + `agents`.
  - `Product` inlines the policy fields the spec keeps in `merchant_policies`.
Both are reasonable for current scale; revisit if multi-policy/multi-agent is needed.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'buyer' | 'merchant'
    business_name = Column(String, nullable=True)  # merchants only
    created_at = Column(DateTime, default=_now)

    products = relationship("Product", back_populates="merchant", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")

    # Pricing / policy (private to the merchant — never leaves merchant context)
    list_price = Column(Float, nullable=False)
    floor_price = Column(Float, nullable=False)
    max_discount_pct = Column(Float, default=10.0)
    min_order_qty = Column(Integer, default=1)
    max_negotiation_rounds = Column(Integer, default=3)

    # Negotiation strategy — tunes how fast the agent concedes toward the floor.
    # balanced | aggressive (win the deal) | firm (hold margin) | clear_stock (move inventory)
    strategy = Column(String, default="balanced")

    # Fulfilment
    stock = Column(Integer, default=0)
    delivery_days = Column(Integer, default=7)
    atoac_enabled = Column(Boolean, default=True)   # discoverable by AI buyers
    # When False, the AI sales agent does NOT auto-respond — new negotiations open
    # with the merchant in HUMAN control, so the merchant negotiates each one itself.
    auto_negotiate = Column(Boolean, default=True)
    
    # Product image
    image_url = Column(String, nullable=True)  # URL to product image

    created_at = Column(DateTime, default=_now)

    merchant = relationship("User", back_populates="products")


class UpsellRule(Base):
    __tablename__ = "upsell_rules"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    base_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    upsell_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    trigger_min_qty = Column(Integer, default=1)
    created_at = Column(DateTime, default=_now)


class Negotiation(Base):
    __tablename__ = "negotiations"

    id = Column(Integer, primary_key=True)
    uid = Column(String, unique=True, nullable=False, index=True)  # neg_xxxx
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    quantity = Column(Integer, nullable=False)
    target_price = Column(Float, nullable=False)
    max_delivery_days = Column(Integer, nullable=True)  # buyer's delivery constraint, for alternatives
    final_unit_price = Column(Float, nullable=True)
    total = Column(Float, nullable=True)
    rounds = Column(Integer, default=0)
    status = Column(String, nullable=False)  # NEGOTIATING | AGREED | DENIED
    reason = Column(Text, default="")
    reason_code = Column(String, default="")  # machine-readable, see negotiation.ReasonCode
    created_at = Column(DateTime, default=_now)

    # Interactive session state (chat + human takeover)
    buyer_control = Column(String, default="AGENT")     # AGENT | HUMAN
    merchant_control = Column(String, default="AGENT")  # AGENT | HUMAN
    turn = Column(String, nullable=True)                # 'buyer' | 'merchant' | None (terminal)
    round_no = Column(Integer, default=0)
    buyer_offer = Column(Float, nullable=True)
    merchant_offer = Column(Float, nullable=True)

    offers = relationship("Offer", back_populates="negotiation",
                          cascade="all, delete-orphan", order_by="Offer.round")
    messages = relationship("NegotiationMessage", back_populates="negotiation",
                            cascade="all, delete-orphan", order_by="NegotiationMessage.seq")


class NegotiationMessage(Base):
    """One chat message in a negotiation — from either party's agent or its human.
    The full to-and-fro is replayable from these rows."""
    __tablename__ = "negotiation_messages"

    id = Column(Integer, primary_key=True)
    negotiation_id = Column(Integer, ForeignKey("negotiations.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    sender_role = Column(String, nullable=False)  # 'buyer' | 'merchant' | 'system'
    sender_type = Column(String, nullable=False)  # 'agent' | 'human' | 'system'
    kind = Column(String, nullable=False)         # offer | counter | accept | reject | message | system
    unit_price = Column(Float, nullable=True)
    text = Column(Text, default="")
    created_at = Column(DateTime, default=_now)

    negotiation = relationship("Negotiation", back_populates="messages")


class Offer(Base):
    """One round of a negotiation, persisted as a first-class auditable record
    (spec §10/§22 — previously only in the free-text audit log)."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True)
    negotiation_id = Column(Integer, ForeignKey("negotiations.id"), nullable=False, index=True)
    round = Column(Integer, nullable=False)
    actor = Column(String, nullable=False)  # 'merchant' (counter) | 'buyer' (accept/reject)
    unit_price = Column(Float, nullable=True)
    accepted = Column(Boolean, default=False)
    reason_code = Column(String, default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=_now)

    negotiation = relationship("Negotiation", back_populates="offers")


class Agreement(Base):
    __tablename__ = "agreements"

    id = Column(Integer, primary_key=True)
    uid = Column(String, unique=True, nullable=False, index=True)  # agr_xxxx
    negotiation_id = Column(Integer, ForeignKey("negotiations.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    items_json = Column(Text, nullable=False)  # [{product_id, name, quantity, unit_price}]
    delivery_days = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)
    backorder = Column(Boolean, default=False)  # fulfilled from future restock, not held now
    basket_id = Column(Integer, ForeignKey("baskets.id"), nullable=True, index=True)  # multi-item basket
    status = Column(String, default="AGREED")  # AGREED | PAYMENT_PENDING | CONFIRMED | FAILED
    created_at = Column(DateTime, default=_now)


class Basket(Base):
    """Groups several per-line Agreements into one multi-item order + checkout."""
    __tablename__ = "baskets"

    id = Column(Integer, primary_key=True)
    uid = Column(String, unique=True, nullable=False, index=True)  # bsk_xxxx
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default="AGREED")  # AGREED | PAYMENT_PENDING | CONFIRMED | PARTIAL
    total = Column(Float, default=0)
    created_at = Column(DateTime, default=_now)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    agreement_id = Column(Integer, ForeignKey("agreements.id"), nullable=False)
    razorpay_id = Column(String, nullable=True)  # payment link / order id
    amount = Column(Float, nullable=False)  # authoritative, computed server-side
    status = Column(String, default="PENDING")  # PENDING | CONFIRMED | FAILED
    payment_link = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    details_json = Column(Text, default="{}")
    merchant_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=_now)


class Reservation(Base):
    """A time-boxed hold on stock while a buyer commits an agreement (§6.1, §28).

    Availability = Product.stock - sum(quantity of HELD, unexpired reservations).
    Lifecycle: HELD -> CONSUMED (paid, stock decremented) | RELEASED | EXPIRED.
    """
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    negotiation_id = Column(Integer, ForeignKey("negotiations.id"), nullable=True)
    agreement_id = Column(Integer, ForeignKey("agreements.id"), nullable=True, index=True)
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="HELD")  # HELD | CONSUMED | RELEASED | EXPIRED
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_now)


class Conversation(Base):
    """A buyer's saved chat thread — the rendered transcript is stored as JSON so
    it can be reopened later (chat history / new chat, like a normal chat app)."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    uid = Column(String, unique=True, nullable=False, index=True)  # conv_xxxx
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, default="New chat")
    items_json = Column(Text, default="[]")  # [{t, role, name, html} | {t:'sys', text}]
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class PolicyChangeRequest(Base):
    """A proposed change to a product's material pricing/policy fields, held for
    explicit merchant approval before it takes effect (§28). Non-material edits
    (name, stock, delivery) apply immediately and never create one of these.
    """
    __tablename__ = "policy_change_requests"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    changes_json = Column(Text, nullable=False)  # {field: {"old": x, "new": y}}
    status = Column(String, default="PENDING")  # PENDING | APPROVED | REJECTED
    created_at = Column(DateTime, default=_now)
    resolved_at = Column(DateTime, nullable=True)


class ProcessedWebhookEvent(Base):
    __tablename__ = "processed_webhook_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True, nullable=False, index=True)
    processed_at = Column(DateTime, default=_now)
