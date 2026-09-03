"""Merchant/product discovery: search across all merchants, filter & rank (see §5)."""
import re

from sqlalchemy.orm import Session

from models import Product


def _tokens(query: str) -> list[str]:
    """Content tokens from a free-text query, crudely singularised, so a natural
    phrase like 'ergonomic chairs' matches 'Ergonomic Office Chair'."""
    toks = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) >= 3]
    return [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in toks]


def search_products(db: Session, query: str) -> list[Product]:
    """Search product names first, using descriptions only as a fallback.

    This prevents an accessory such as ``Desk Chair Mat`` from crowding out
    actual chairs when the buyer asks specifically for chairs.
    """
    tokens = _tokens(query)
    if not tokens:
        return []
    name_matches = []
    description_matches = []
    for p in db.query(Product).all():
        name_tokens = _tokens(p.name)
        if all(token in name_tokens for token in tokens):
            # A chair search means the item itself should be a chair, not a
            # chair-related accessory whose name ends in mat, cushion, or pad.
            if "chair" in tokens and any(token in name_tokens for token in
                                         ("mat", "cushion", "pad")):
                continue
            name_matches.append(p)
            continue
        hay = (p.name + " " + (p.description or "")).lower()
        if any(token in hay for token in tokens):
            description_matches.append(p)
    return name_matches or description_matches


def filter_and_rank(products: list[Product], quantity: int, max_delivery_days: int | None) -> list[Product]:
    """Eliminate hard-constraint failures early, then rank by list price.

    A candidate survives only if it is ATOAC-enabled, has enough stock, and can
    deliver within the buyer's window. Ranking by list price is a cheap proxy;
    the real ordering happens after negotiation on negotiated total.
    """
    candidates = [
        p for p in products
        if p.atoac_enabled
        and p.stock >= quantity
        and (max_delivery_days is None or p.delivery_days <= max_delivery_days)
    ]
    return sorted(candidates, key=lambda p: p.list_price)


def top_n(products: list[Product], n: int = 5) -> list[Product]:
    return products[:n]
