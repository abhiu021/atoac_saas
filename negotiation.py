"""Turn-based negotiation engine + guardrail (see §10, §12).

A negotiation is a stateful chat between the buyer's side and the merchant's
side. Each side is controlled by an AGENT (deterministic, this module) or a
HUMAN (who has paused their agent and types responses). The SAME engine powers
both the fully-automatic path (`negotiate`, both sides AGENT, run to completion)
and the interactive path (stepped turn by turn, humans can take over).

Design invariant: ALL pricing and accept/reject math is pure arithmetic. No LLM
ever decides a number. A human MERCHANT still cannot breach the floor/discount
cap (the guardrail authorizes every merchant price); a human BUYER is free to
offer anything (buyers carry no server-side floor).
"""
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

import inventory
import llm
from audit import log_event
from config import settings
from database import SessionLocal
from models import Negotiation, NegotiationMessage, Offer, Product, User

HAPPY_ACCEPT_TOLERANCE = 0.05   # accept immediately if counter <= target * 1.05
WALKAWAY_MARKUP = 0.10          # walk away if even the best offer > target * 1.10


class ReasonCode:
    BELOW_MIN_QTY = "BELOW_MIN_QTY"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    WALKAWAY_EXCEEDED = "WALKAWAY_EXCEEDED"
    NO_AGREEMENT_IN_ROUNDS = "NO_AGREEMENT_IN_ROUNDS"
    AGREED_WITHIN_TARGET = "AGREED_WITHIN_TARGET"
    AGREED_FINAL_ROUND = "AGREED_FINAL_ROUND"
    COUNTER_OFFERED = "COUNTER_OFFERED"
    BELOW_FLOOR = "BELOW_FLOOR"
    OVER_DISCOUNT_CAP = "OVER_DISCOUNT_CAP"
    MERCHANT_ACCEPTED = "MERCHANT_ACCEPTED"
    BUYER_ACCEPTED = "BUYER_ACCEPTED"
    HUMAN_COUNTER = "HUMAN_COUNTER"
    HUMAN_REJECTED = "HUMAN_REJECTED"


# --- Pure pricing primitives -------------------------------------------------

def effective_floor(product: Product) -> float:
    discount_limit = round(product.list_price * (1 - product.max_discount_pct / 100), 2)
    return max(product.floor_price, discount_limit)


def guardrail_check(product: Product, unit_price: float) -> tuple[bool, str, str]:
    """Independent authorize step — must stay LLM-free forever."""
    floor = effective_floor(product)
    if unit_price < floor - 1e-6:
        return False, f"₹{unit_price:.0f} below floor ₹{floor:.0f}. Rejected.", ReasonCode.BELOW_FLOOR
    discount_pct = (product.list_price - unit_price) / product.list_price * 100
    if discount_pct > product.max_discount_pct + 1e-6:
        return (False, f"Discount {discount_pct:.1f}% exceeds cap {product.max_discount_pct:.0f}%. Rejected.",
                ReasonCode.OVER_DISCOUNT_CAP)
    return True, "ok", "ok"


# Concession curve exponent per strategy: <1 concedes toward the floor faster
# (lower prices, more deals); >1 holds near list longer (higher prices, fewer deals).
# The final round always lands exactly on the floor regardless of strategy.
STRATEGY_EXP = {"aggressive": 0.55, "balanced": 1.0, "firm": 1.8, "clear_stock": 0.4}


def counter_offer(product: Product, target: float, round_num: int, total_rounds: int) -> float:
    floor = effective_floor(product)
    exp = STRATEGY_EXP.get(getattr(product, "strategy", "balanced") or "balanced", 1.0)
    frac = (round_num / total_rounds) ** exp
    price = product.list_price - (product.list_price - floor) * frac
    return round(max(price, floor), 2)


# --- Message / offer bookkeeping ---------------------------------------------

def _next_seq(db: Session, neg: Negotiation) -> int:
    return (db.query(func.max(NegotiationMessage.seq))
            .filter(NegotiationMessage.negotiation_id == neg.id).scalar() or 0) + 1


def _msg(db, neg, role, stype, kind, text, unit_price=None):
    db.add(NegotiationMessage(negotiation_id=neg.id, seq=_next_seq(db, neg), sender_role=role,
                              sender_type=stype, kind=kind, unit_price=unit_price, text=text))


def _stype(neg: Negotiation, role: str) -> str:
    control = neg.buyer_control if role == "buyer" else neg.merchant_control
    return "human" if control == "HUMAN" else "agent"


def _control_of(neg: Negotiation, side: str) -> str:
    return neg.buyer_control if side == "buyer" else neg.merchant_control


def _record_merchant_offer(db, neg, round_no, price, accepted, code, note):
    db.add(Offer(negotiation_id=neg.id, round=round_no, actor="merchant", unit_price=price,
                 accepted=accepted, reason_code=code, note=note))


def _offer_count(db, neg) -> int:
    return db.query(func.count(Offer.id)).filter(Offer.negotiation_id == neg.id).scalar() or 0


def _mark_last_merchant_offer_accepted(db, neg, code):
    last = (db.query(Offer).filter(Offer.negotiation_id == neg.id)
            .order_by(Offer.round.desc()).first())
    if last:
        last.accepted = True
        last.reason_code = code


# --- Terminal transitions ----------------------------------------------------

def _finalize_agree(db, neg, product, price, code):
    neg.status = "AGREED"
    neg.turn = None
    neg.final_unit_price = round(price, 2)
    neg.total = round(price * neg.quantity, 2)
    neg.reason = "Agreed within policy."
    neg.reason_code = code
    neg.rounds = _offer_count(db, neg)
    db.commit()
    merchant = db.get(User, product.merchant_id)
    log_event(db, actor=merchant.business_name or merchant.email, action="negotiation.agreed",
              details={"neg_uid": neg.uid, "product": product.name, "unit_price": neg.final_unit_price,
                       "quantity": neg.quantity, "total": neg.total, "reason_code": code},
              merchant_id=product.merchant_id)


def _finalize_deny(db, neg, product, code, reason):
    neg.status = "DENIED"
    neg.turn = None
    neg.reason = reason
    neg.reason_code = code
    neg.rounds = _offer_count(db, neg)
    _msg(db, neg, "system", "system", "system", reason)
    db.commit()
    merchant = db.get(User, product.merchant_id)
    log_event(db, actor=merchant.business_name or merchant.email, action="negotiation.denied",
              details={"neg_uid": neg.uid, "product": product.name, "reason_code": code, "reason": reason},
              merchant_id=product.merchant_id)


# --- Session lifecycle -------------------------------------------------------

def start(db, buyer, product, quantity, target_price, max_delivery_days=None,
          buyer_control="AGENT", merchant_control="AGENT") -> Negotiation:
    """Create a negotiation, run eligibility gates, post the buyer's opening offer."""
    uid = f"neg_{uuid.uuid4().hex[:8]}"
    neg = Negotiation(uid=uid, buyer_id=buyer.id, merchant_id=product.merchant_id,
                      product_id=product.id, quantity=quantity, target_price=target_price,
                      max_delivery_days=max_delivery_days, status="NEGOTIATING", reason="",
                      reason_code="", turn="merchant", round_no=0, buyer_offer=target_price,
                      merchant_offer=None, buyer_control=buyer_control,
                      merchant_control=merchant_control)
    db.add(neg)
    db.commit()
    db.refresh(neg)

    if quantity < product.min_order_qty:
        _finalize_deny(db, neg, product, ReasonCode.BELOW_MIN_QTY,
                       f"Quantity {quantity} below minimum order {product.min_order_qty}.")
        return neg
    available = inventory.available_stock(db, product.id)
    if quantity > available:
        _finalize_deny(db, neg, product, ReasonCode.INSUFFICIENT_STOCK,
                       f"Only {available} available; requested {quantity}.")
        return neg
    floor = effective_floor(product)
    if floor > target_price * (1 + WALKAWAY_MARKUP):
        _finalize_deny(db, neg, product, ReasonCode.WALKAWAY_EXCEEDED,
                       f"Best possible ₹{floor:.0f} exceeds buyer walk-away for target ₹{target_price:.0f}.")
        return neg

    _msg(db, neg, "buyer", _stype(neg, "buyer"), "offer",
         f"We'd like {quantity} × {product.name} at ₹{target_price:,.0f}/unit.", target_price)
    db.commit()
    return neg


def _phrase(db, neg, product, role, kind, price, final, fallback):
    """LLM-authored line for this turn (numbers stay engine-decided); template fallback."""
    if not settings.llm_enabled:
        return fallback
    merchant = db.get(User, product.merchant_id)
    return llm.negotiation_line(
        role, kind, merchant_name=merchant.business_name or "Merchant", product_name=product.name,
        quantity=neg.quantity, target=neg.target_price, price=price, round_no=neg.round_no,
        final=final, fallback=fallback)


def _agent_turn(db, neg, product):
    """Perform exactly one agent action for whichever side's turn it is."""
    total_rounds = max(1, product.max_negotiation_rounds)

    if neg.turn == "merchant":
        r = neg.round_no + 1
        counter = counter_offer(product, neg.target_price, r, total_rounds)
        if neg.buyer_offer is not None and neg.buyer_offer >= counter - 1e-6:
            price = round(neg.buyer_offer, 2)
            neg.round_no = r
            neg.merchant_offer = price
            _record_merchant_offer(db, neg, r, price, True, ReasonCode.MERCHANT_ACCEPTED, "accepts buyer offer")
            text = _phrase(db, neg, product, "merchant", "accept", price, False,
                           f"₹{price:,.0f}/unit works for us — deal.")
            _msg(db, neg, "merchant", "agent", "accept", text, price)
            _finalize_agree(db, neg, product, price, ReasonCode.MERCHANT_ACCEPTED)
            return
        neg.round_no = r
        neg.merchant_offer = counter
        _record_merchant_offer(db, neg, r, counter, False, ReasonCode.COUNTER_OFFERED, "counter")
        text = _phrase(db, neg, product, "merchant", "counter", counter, r == total_rounds,
                       f"Best we can do this round is ₹{counter:,.0f}/unit for {neg.quantity}.")
        _msg(db, neg, "merchant", "agent", "counter", text, counter)
        neg.turn = "buyer"
        db.commit()
        return

    # buyer turn — evaluate the merchant's standing offer
    mo = neg.merchant_offer
    happy = mo <= neg.target_price * (1 + HAPPY_ACCEPT_TOLERANCE)
    final = neg.round_no >= total_rounds
    stretch = mo <= neg.target_price * (1 + WALKAWAY_MARKUP)
    if happy:
        _mark_last_merchant_offer_accepted(db, neg, ReasonCode.AGREED_WITHIN_TARGET)
        text = _phrase(db, neg, product, "buyer", "accept", mo, False,
                       f"₹{mo:,.0f} is within our target — we'll take it.")
        _msg(db, neg, "buyer", "agent", "accept", text, mo)
        _finalize_agree(db, neg, product, mo, ReasonCode.AGREED_WITHIN_TARGET)
        return
    if final:
        if stretch:
            _mark_last_merchant_offer_accepted(db, neg, ReasonCode.AGREED_FINAL_ROUND)
            text = _phrase(db, neg, product, "buyer", "accept", mo, True,
                           f"Above target, but ₹{mo:,.0f} is acceptable. Deal.")
            _msg(db, neg, "buyer", "agent", "accept", text, mo)
            _finalize_agree(db, neg, product, mo, ReasonCode.AGREED_FINAL_ROUND)
        else:
            text = _phrase(db, neg, product, "buyer", "reject", mo, True,
                           f"₹{mo:,.0f} is above our walk-away — we'll pass.")
            _msg(db, neg, "buyer", "agent", "reject", text, mo)
            _finalize_deny(db, neg, product, ReasonCode.NO_AGREEMENT_IN_ROUNDS,
                           f"No agreement within {total_rounds} rounds for target ₹{neg.target_price:.0f}.")
        return
    text = _phrase(db, neg, product, "buyer", "hold", mo, False,
                   f"₹{mo:,.0f} is still above our ₹{neg.target_price:,.0f} target — can you improve?")
    _msg(db, neg, "buyer", "agent", "message", text)
    neg.turn = "merchant"
    db.commit()


def advance(db, neg, product):
    """Run agent turns until a human-controlled turn or a terminal state."""
    while neg.status == "NEGOTIATING" and neg.turn and _control_of(neg, neg.turn) == "AGENT":
        _agent_turn(db, neg, product)


def step_once(db, neg, product) -> bool:
    """Advance exactly one agent turn (for the live 'typing' effect). Returns True
    if it acted, False if it's a human's turn or the negotiation is over."""
    if neg.status == "NEGOTIATING" and neg.turn and _control_of(neg, neg.turn) == "AGENT":
        _agent_turn(db, neg, product)
        return True
    return False


def set_control(db, neg, role, mode):
    # Control changes are reflected in the UI (turn indicator / buttons), not as a
    # chat message — keep the transcript clean.
    if role == "buyer":
        neg.buyer_control = mode
    else:
        neg.merchant_control = mode
    db.commit()


def human_act(db, neg, product, role, action, price=None, text=None):
    """Apply a human action for `role`, then let any AGENT side respond."""
    if neg.status != "NEGOTIATING":
        raise ValueError("Negotiation is already closed.")

    if action == "message":
        _msg(db, neg, role, "human", "message", text or "")
        db.commit()
        return

    if _control_of(neg, role) != "HUMAN":
        raise ValueError("Pause your agent before acting for this side.")
    if neg.turn != role:
        raise ValueError(f"It is not the {role}'s turn.")

    if action in ("offer", "counter"):
        if price is None:
            raise ValueError("A price is required.")
        price = round(float(price), 2)
        if role == "merchant":
            ok, reason, _code = guardrail_check(product, price)
            if not ok:
                raise ValueError(reason)  # bounded: human merchant cannot breach the floor
            neg.round_no += 1
            neg.merchant_offer = price
            _record_merchant_offer(db, neg, neg.round_no, price, False, ReasonCode.HUMAN_COUNTER, "human counter")
            _msg(db, neg, "merchant", "human", "counter", text or f"Our offer: ₹{price:,.0f}/unit.", price)
            neg.turn = "buyer"
        else:
            neg.buyer_offer = price
            _msg(db, neg, "buyer", "human", "counter", text or f"We can do ₹{price:,.0f}/unit.", price)
            neg.turn = "merchant"
        db.commit()
        advance(db, neg, product)
        return

    if action == "accept":
        if role == "buyer":
            if neg.merchant_offer is None:
                raise ValueError("No merchant offer to accept yet.")
            price = neg.merchant_offer
            _mark_last_merchant_offer_accepted(db, neg, ReasonCode.BUYER_ACCEPTED)
            _msg(db, neg, "buyer", "human", "accept", text or f"We'll take it at ₹{price:,.0f}/unit.", price)
            _finalize_agree(db, neg, product, price, ReasonCode.BUYER_ACCEPTED)
        else:
            if neg.buyer_offer is None:
                raise ValueError("No buyer offer to accept yet.")
            price = neg.buyer_offer
            ok, reason, _code = guardrail_check(product, price)
            if not ok:
                raise ValueError(reason)
            neg.round_no += 1
            neg.merchant_offer = price
            _record_merchant_offer(db, neg, neg.round_no, price, True, ReasonCode.MERCHANT_ACCEPTED, "human accept")
            _msg(db, neg, "merchant", "human", "accept", text or f"Agreed at ₹{price:,.0f}/unit.", price)
            _finalize_agree(db, neg, product, price, ReasonCode.MERCHANT_ACCEPTED)
        return

    if action == "reject":
        _msg(db, neg, role, "human", "reject", text or "We'll pass on this one.")
        _finalize_deny(db, neg, product, ReasonCode.HUMAN_REJECTED, f"Negotiation ended by {role}.")
        return

    raise ValueError(f"Unknown action '{action}'.")


# --- Serialization -----------------------------------------------------------

def state_dict(db, neg) -> dict:
    """Full interactive state for a party (never leaks floor/policy)."""
    product = db.get(Product, neg.product_id)
    merchant = db.get(User, neg.merchant_id)
    waiting_for = neg.turn if (neg.turn and _control_of(neg, neg.turn) == "HUMAN") else None
    return {
        "negotiation_uid": neg.uid,
        "merchant_id": neg.merchant_id,
        "merchant_name": merchant.business_name or "Merchant",
        "buyer_id": neg.buyer_id,
        "product_id": neg.product_id,
        "product_name": product.name if product else None,
        "quantity": neg.quantity,
        "target_price": neg.target_price,
        "status": neg.status,
        "reason_code": neg.reason_code,
        "turn": neg.turn,
        "buyer_control": neg.buyer_control,
        "merchant_control": neg.merchant_control,
        "waiting_for": waiting_for,
        "final_unit_price": neg.final_unit_price,
        "total": neg.total,
        "rounds": neg.rounds,
        "delivery_days": product.delivery_days if product else None,
        "messages": [
            {"seq": m.seq, "role": m.sender_role, "type": m.sender_type, "kind": m.kind,
             "unit_price": m.unit_price, "text": m.text,
             "at": m.created_at.isoformat() if m.created_at else None}
            for m in neg.messages
        ],
    }


# --- Automatic (both-agent) path — used by the multi-merchant gateway --------

def negotiate(db, buyer, product, quantity, target_price, max_delivery_days=None) -> dict:
    neg = start(db, buyer, product, quantity, target_price, max_delivery_days, "AGENT", "AGENT")
    if neg.status == "NEGOTIATING":
        advance(db, neg, product)
    return _result(db, neg, product)


def negotiate_new_session(product_id, buyer_id, quantity, target_price, max_delivery_days) -> dict:
    db = SessionLocal()
    try:
        buyer = db.get(User, buyer_id)
        product = db.get(Product, product_id)
        return negotiate(db, buyer, product, quantity, target_price, max_delivery_days)
    finally:
        db.close()


def _result(db, neg, product) -> dict:
    """Buyer-facing result for the auto path — same shape the UI/analytics expect."""
    merchant = db.get(User, product.merchant_id)
    offers = (db.query(Offer).filter(Offer.negotiation_id == neg.id)
              .order_by(Offer.round).all())
    transcript = [{"round": o.round, "merchant_offer": o.unit_price, "buyer_target": neg.target_price,
                   "accepted": o.accepted, "reason_code": o.reason_code, "note": o.note} for o in offers]
    narration = llm.narrate_negotiation(
        merchant_name=merchant.business_name or "Merchant", product_name=product.name,
        status=neg.status, unit_price=neg.final_unit_price, quantity=neg.quantity,
        target=neg.target_price, transcript=transcript, reason=neg.reason)
    return {
        "negotiation_uid": neg.uid,
        "merchant_id": merchant.id,
        "merchant_name": merchant.business_name or "Merchant",
        "product_id": product.id,
        "product_name": product.name,
        "quantity": neg.quantity,
        "target_price": neg.target_price,
        "status": neg.status,
        "reason_code": neg.reason_code,
        "unit_price": neg.final_unit_price,
        "total": neg.total,
        "delivery_days": product.delivery_days,
        "rounds": neg.rounds,
        "transcript": transcript,
        "reason": neg.reason,
        "narration": narration,
    }
