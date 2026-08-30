"""Inventory reservation lifecycle + graceful shortfall alternatives (§6.1, §19.1).

Stock is never "held" during negotiation — only once the buyer moves to commit an
agreement. If the held quantity can't be met (stock dropped since negotiation), we
don't hard-fail: we compute buyer-respecting alternatives (partial / backorder /
another merchant) so the flow degrades gracefully.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import discovery
from audit import log_event
from config import settings
from models import Negotiation, Product, Reservation, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def release_expired(db: Session) -> None:
    """Flip any HELD reservation past its TTL to EXPIRED. Called before every
    availability check so stale holds free up automatically."""
    now = _now()
    expired = (db.query(Reservation)
               .filter(Reservation.status == "HELD", Reservation.expires_at < now)
               .all())
    for r in expired:
        r.status = "EXPIRED"
    if expired:
        db.commit()


def available_stock(db: Session, product_id: int) -> int:
    """Physical stock minus everything currently held by unexpired reservations."""
    release_expired(db)
    product = db.get(Product, product_id)
    if not product:
        return 0
    held = (db.query(func.coalesce(func.sum(Reservation.quantity), 0))
            .filter(Reservation.product_id == product_id, Reservation.status == "HELD")
            .scalar())
    return max(0, product.stock - int(held))


def reserve(db: Session, product_id: int, quantity: int,
            negotiation_id: int | None = None) -> Reservation | None:
    """Create a HELD reservation if enough is available, else return None."""
    if available_stock(db, product_id) < quantity:
        return None
    r = Reservation(
        product_id=product_id, negotiation_id=negotiation_id, quantity=quantity,
        status="HELD", expires_at=_now() + timedelta(minutes=settings.RESERVATION_TTL_MINUTES),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def consume_for_agreement(db: Session, agreement_id: int) -> None:
    """Payment confirmed: turn holds into real stock decrements."""
    holds = (db.query(Reservation)
             .filter(Reservation.agreement_id == agreement_id, Reservation.status == "HELD")
             .all())
    for r in holds:
        product = db.get(Product, r.product_id)
        if product:
            product.stock = max(0, product.stock - r.quantity)
        r.status = "CONSUMED"
    db.commit()


def release_for_agreement(db: Session, agreement_id: int) -> None:
    """Payment failed/expired or agreement abandoned: free the held stock."""
    holds = (db.query(Reservation)
             .filter(Reservation.agreement_id == agreement_id, Reservation.status == "HELD")
             .all())
    for r in holds:
        r.status = "RELEASED"
    if holds:
        db.commit()


def build_alternatives(db: Session, neg: Negotiation, requested_qty: int) -> list[dict]:
    """When the base product can't be fully reserved, offer buyer-respecting options,
    each honouring the buyer's max delivery window where one was given (§19.1)."""
    base = db.get(Product, neg.product_id)
    avail = available_stock(db, base.id)
    max_deliv = neg.max_delivery_days
    unit_price = neg.final_unit_price
    alts: list[dict] = []

    # A — Partial now: ship what's in stock at the agreed price, same delivery.
    if 0 < avail < requested_qty:
        alts.append({
            "type": "partial", "label": f"Take {avail} now at the agreed price",
            "product_id": base.id, "quantity": avail, "unit_price": unit_price,
            "delivery_days": base.delivery_days, "total": round(unit_price * avail, 2),
        })

    # B — Backorder full quantity with extended delivery, only if within the window.
    extended = base.delivery_days + settings.RESTOCK_LEAD_DAYS
    if max_deliv is None or extended <= max_deliv:
        alts.append({
            "type": "backorder", "label": f"Full {requested_qty} in {extended} days (backorder)",
            "product_id": base.id, "quantity": requested_qty, "unit_price": unit_price,
            "delivery_days": extended, "total": round(unit_price * requested_qty, 2),
        })

    # C — Another merchant who can fulfil the full quantity within the window.
    others = discovery.search_products(db, base.name)
    for p in discovery.filter_and_rank(others, requested_qty, max_deliv):
        if p.merchant_id == base.merchant_id:
            continue
        if available_stock(db, p.id) >= requested_qty:
            merchant = db.get(User, p.merchant_id)
            alts.append({
                "type": "alternative_merchant",
                "label": f"{merchant.business_name} can supply {requested_qty} in {p.delivery_days} days",
                "product_id": p.id, "merchant_name": merchant.business_name,
                "list_price": p.list_price, "delivery_days": p.delivery_days,
                "quantity": requested_qty,
            })
        if len([a for a in alts if a["type"] == "alternative_merchant"]) >= 2:
            break

    log_event(db, actor="inventory", action="inventory.shortfall",
              details={"product": base.name, "requested": requested_qty, "available": avail,
                       "alternatives": [a["type"] for a in alts]},
              merchant_id=base.merchant_id)
    return alts
