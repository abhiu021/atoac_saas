"""Merchant analytics & revenue intelligence (§16, §18).

Everything here is computed on demand from the event tables (Negotiation, Offer,
Agreement, Payment). No numbers are invented; recommendations are rule-based with
data-derived impact estimates, not learned.
"""
import json
from collections import defaultdict

from sqlalchemy.orm import Session

from models import Agreement, Negotiation, Payment, Product, UpsellRule


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def compute(db: Session, merchant_id: int) -> dict:
    negs = db.query(Negotiation).filter(Negotiation.merchant_id == merchant_id).all()
    agreements = db.query(Agreement).filter(Agreement.merchant_id == merchant_id).all()
    products = {p.id: p for p in db.query(Product).filter(Product.merchant_id == merchant_id).all()}

    overview = _overview(db, negs, agreements)
    neg_intel = _negotiation_intelligence(negs, products)
    upsell_intel = _upsell_intelligence(db, merchant_id, negs, agreements, products)
    payments = _payment_health(db, agreements)
    recos = _recommendations(overview, neg_intel, upsell_intel, agreements)
    actions = _learning_actions(negs, products, overview["aov"])
    recent = _recent_negotiations(negs, products)

    return {
        "overview": overview,
        "negotiation_intelligence": neg_intel,
        "upsell_intelligence": upsell_intel,
        "payment_health": payments,
        "recommendations": recos,
        "policy_actions": actions,
        "price_trend": _price_trend(negs, products),
        "recent_negotiations": recent,
    }


def _price_trend(negs, products: dict) -> list[dict]:
    """Chronological closing unit-prices for the last agreed negotiations — a trend
    line that reads well even when all the data is from one day."""
    agreed = [n for n in negs if n.status == "AGREED" and n.final_unit_price]
    agreed = sorted(agreed, key=lambda n: (n.created_at, n.id))[-20:]
    return [{"price": n.final_unit_price,
             "product": products[n.product_id].name if n.product_id in products else "",
             "at": n.created_at.isoformat() if n.created_at else None} for n in agreed]


def _learning_actions(negs, products: dict, aov: float) -> list[dict]:
    """Turn negotiation history into concrete, one-click floor suggestions per
    product. Applying one creates a PENDING policy change (approval required),
    closing the analytics -> policy loop (§17). Never mutates anything itself."""
    from collections import defaultdict
    stats = defaultdict(lambda: {"total": 0, "agreed": 0, "walk": 0, "discs": []})
    for n in negs:
        s = stats[n.product_id]
        s["total"] += 1
        if n.status == "AGREED":
            s["agreed"] += 1
            p = products.get(n.product_id)
            if p and n.final_unit_price:
                s["discs"].append((p.list_price - n.final_unit_price) / p.list_price * 100)
        elif n.reason_code == "WALKAWAY_EXCEEDED":
            s["walk"] += 1

    actions = []
    for pid, s in stats.items():
        p = products.get(pid)
        if not p or s["total"] < 2:
            continue
        close = s["agreed"] / s["total"] * 100
        avgd = sum(s["discs"]) / len(s["discs"]) if s["discs"] else 0.0
        if s["walk"] >= 1:  # losing deals -> floor likely too high
            new_floor = round(p.floor_price * 0.97, 2)
            if new_floor < p.floor_price:
                actions.append({
                    "product_id": pid, "product_name": p.name, "field": "floor_price",
                    "current": p.floor_price, "suggested": new_floor, "direction": "lower",
                    "title": f"Recover walk-aways on {p.name}",
                    "detail": (f"{s['walk']} deal(s) were lost because your floor exceeded the buyer's "
                               f"walk-away price. Lowering the floor ~3% could recapture that demand."),
                    "expected_impact_inr": round(s["walk"] * (aov or 0), 0),
                })
        elif close >= 80 and avgd >= 3 and s["walk"] == 0:  # closing easily -> room to raise floor
            new_floor = min(p.list_price, round(p.floor_price * 1.02, 2))
            if new_floor > p.floor_price:
                actions.append({
                    "product_id": pid, "product_name": p.name, "field": "floor_price",
                    "current": p.floor_price, "suggested": new_floor, "direction": "raise",
                    "title": f"Capture margin on {p.name}",
                    "detail": (f"You close {close:.0f}% of {p.name} negotiations at {avgd:.1f}% average "
                               f"discount with no walk-aways. Raising the floor ~2% is unlikely to hurt conversion."),
                    "expected_impact_inr": 0,
                })
    return actions


def _overview(db, negs, agreements) -> dict:
    total = len(negs)
    agreed = [n for n in negs if n.status == "AGREED"]
    confirmed = [a for a in agreements if a.status == "CONFIRMED"]
    gmv = round(sum(a.total for a in confirmed), 2)
    return {
        "negotiation_count": total,
        "agreed_count": len(agreed),
        "success_rate_pct": round(len(agreed) / total * 100, 1) if total else 0.0,
        "confirmed_orders": len(confirmed),
        "gmv": gmv,
        "aov": round(gmv / len(confirmed), 2) if confirmed else 0.0,
        "avg_rounds": _avg([n.rounds for n in negs]),
    }


def _negotiation_intelligence(negs, products) -> dict:
    agreed = [n for n in negs if n.status == "AGREED" and n.final_unit_price]
    discounts = []
    per_product = defaultdict(lambda: {"count": 0, "prices": [], "discounts": []})
    for n in agreed:
        p = products.get(n.product_id)
        if not p:
            continue
        disc = (p.list_price - n.final_unit_price) / p.list_price * 100
        discounts.append(disc)
        row = per_product[p.name]
        row["count"] += 1
        row["prices"].append(n.final_unit_price)
        row["discounts"].append(disc)

    closing = [{
        "product": name, "deals": r["count"],
        "avg_close_price": _avg(r["prices"]),
        "min_close_price": round(min(r["prices"]), 2),
        "max_close_price": round(max(r["prices"]), 2),
        "avg_discount_pct": _avg(r["discounts"]),
    } for name, r in per_product.items()]

    # "Objections": why deals didn't close, bucketed by machine reason code.
    denials = defaultdict(int)
    for n in negs:
        if n.status == "DENIED":
            denials[n.reason_code or "UNKNOWN"] += 1

    return {
        "avg_discount_pct": _avg(discounts),
        "min_discount_pct": round(min(discounts), 2) if discounts else 0.0,
        "max_discount_pct": round(max(discounts), 2) if discounts else 0.0,
        "closing_by_product": sorted(closing, key=lambda x: -x["deals"]),
        "objections": [{"reason_code": k, "count": v}
                       for k, v in sorted(denials.items(), key=lambda x: -x[1])],
    }


def _upsell_intelligence(db, merchant_id, negs, agreements, products) -> dict:
    rules = db.query(UpsellRule).filter(UpsellRule.merchant_id == merchant_id).all()
    rows = []
    total_cross_sell_revenue = 0.0
    for rule in rules:
        base = products.get(rule.base_product_id)
        up = products.get(rule.upsell_product_id)
        if not base or not up:
            continue
        # Offered ≈ agreed negotiations on the base product at/above the trigger qty.
        offered = sum(1 for n in negs if n.product_id == base.id
                      and n.status == "AGREED" and n.quantity >= rule.trigger_min_qty)
        accepted = 0
        revenue = 0.0
        for a in agreements:
            for item in json.loads(a.items_json):
                if item["product_id"] == up.id:
                    accepted += 1
                    if a.status == "CONFIRMED":
                        revenue += item["unit_price"] * item["quantity"]
        total_cross_sell_revenue += revenue
        rows.append({
            "base_product": base.name, "upsell_product": up.name,
            "trigger_min_qty": rule.trigger_min_qty,
            "offered": offered, "accepted": accepted,
            "acceptance_rate_pct": round(accepted / offered * 100, 1) if offered else 0.0,
            "revenue": round(revenue, 2),
        })
    return {"rules": sorted(rows, key=lambda x: -x["revenue"]),
            "total_cross_sell_revenue": round(total_cross_sell_revenue, 2)}


def _payment_health(db, agreements) -> dict:
    agr_ids = [a.id for a in agreements]
    payments = (db.query(Payment).filter(Payment.agreement_id.in_(agr_ids)).all()
                if agr_ids else [])
    total = len(payments)
    confirmed = sum(1 for p in payments if p.status == "CONFIRMED")
    failed = sum(1 for p in payments if p.status == "FAILED")
    return {
        "payment_attempts": total,
        "confirmed": confirmed,
        "failed": failed,
        "success_rate_pct": round(confirmed / total * 100, 1) if total else 0.0,
    }


def _recommendations(overview, neg_intel, upsell_intel, agreements) -> list[dict]:
    recos = []

    # 1. Lost deals to walk-aways -> floors may be too high.
    walkaways = next((o["count"] for o in neg_intel["objections"]
                      if o["reason_code"] == "WALKAWAY_EXCEEDED"), 0)
    if walkaways:
        impact = round(walkaways * (overview["aov"] or 0), 0)
        recos.append({
            "title": "Recover walk-away losses",
            "detail": f"{walkaways} negotiation(s) ended because your floor exceeded the buyer's "
                      f"walk-away price. Lowering the floor 2–3% on those items could recapture demand.",
            "expected_impact_inr": impact,
        })

    # 2. Strong close rate + healthy discount -> room to tighten.
    if overview["success_rate_pct"] >= 70 and neg_intel["avg_discount_pct"] >= 3:
        gain = round(overview["gmv"] * 0.01, 0)
        recos.append({
            "title": "Tighten discounting",
            "detail": f"You close {overview['success_rate_pct']}% of negotiations at "
                      f"{neg_intel['avg_discount_pct']}% average discount. Raising floors ~1% is "
                      f"unlikely to hurt conversion at this close rate.",
            "expected_impact_inr": gain,
        })

    # 3. Upsell performing well -> extend to more products.
    for r in upsell_intel["rules"]:
        if r["offered"] >= 1 and r["acceptance_rate_pct"] >= 50:
            recos.append({
                "title": f"Scale the {r['upsell_product']} cross-sell",
                "detail": f"{r['upsell_product']} attaches to {r['acceptance_rate_pct']}% of qualifying "
                          f"{r['base_product']} orders (₹{r['revenue']:,.0f} so far). Add similar rules "
                          f"to other high-volume products.",
                "expected_impact_inr": round(r["revenue"], 0),
            })
            break

    if not recos:
        recos.append({
            "title": "Gathering data",
            "detail": "Not enough closed negotiations yet to make a confident recommendation. "
                      "Insights sharpen as more buyers negotiate.",
            "expected_impact_inr": 0,
        })
    return recos


def _recent_negotiations(negs, products) -> list[dict]:
    recent = sorted(negs, key=lambda n: n.created_at or 0, reverse=True)[:15]
    return [{
        "negotiation_uid": n.uid,
        "product": products[n.product_id].name if n.product_id in products else None,
        "quantity": n.quantity,
        "status": n.status,
        "reason_code": n.reason_code,
        "final_unit_price": n.final_unit_price,
        "total": n.total,
        "rounds": n.rounds,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in recent]
