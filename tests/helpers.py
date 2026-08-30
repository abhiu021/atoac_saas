"""Shared test helpers."""
import hashlib
import hmac
import json

WEBHOOK_SECRET = b"whsec_test_123"

_PRODUCT_FIELDS = ("name", "description", "list_price", "floor_price", "max_discount_pct",
                   "min_order_qty", "max_negotiation_rounds", "stock", "delivery_days", "atoac_enabled")


def negotiate(client, buyer, qty, target=4300, deliv=7, query="chair"):
    return client.post("/api/buyer/negotiate", headers=buyer,
                       json={"query": query, "quantity": qty, "target_price": target,
                             "max_delivery_days": deliv}).json()


def result_for(data, merchant_name):
    return next(x for x in data["results"] if x["merchant_name"] == merchant_name)


def product_id(client, merchant_headers, name="Ergonomic Office Chair"):
    prods = client.get("/api/merchant/products", headers=merchant_headers).json()
    return next(p["id"] for p in prods if p["name"] == name)


def set_stock(client, merchant_headers, pid, stock):
    prods = client.get("/api/merchant/products", headers=merchant_headers).json()
    p = next(x for x in prods if x["id"] == pid)
    body = {k: p[k] for k in _PRODUCT_FIELDS}
    body["stock"] = stock
    r = client.put(f"/api/merchant/products/{pid}", headers=merchant_headers, json=body)
    assert r.status_code == 200, r.text


def get_product(client, merchant_headers, pid):
    prods = client.get("/api/merchant/products", headers=merchant_headers).json()
    return next(p for p in prods if p["id"] == pid)


def put_product(client, merchant_headers, pid, **overrides):
    body = {k: get_product(client, merchant_headers, pid)[k] for k in _PRODUCT_FIELDS}
    body.update(overrides)
    return client.put(f"/api/merchant/products/{pid}", headers=merchant_headers, json=body)


def clear_pending(client, merchant_headers):
    for c in client.get("/api/merchant/policy-changes?status=PENDING", headers=merchant_headers).json():
        client.post(f"/api/merchant/policy-changes/{c['request_id']}/reject", headers=merchant_headers)


def start_negotiation(client, buyer, product_id, qty, target=4300, deliv=7, pause=False):
    return client.post("/api/negotiations/start", headers=buyer,
                       json={"product_id": product_id, "quantity": qty, "target_price": target,
                             "max_delivery_days": deliv, "pause_agent": pause})


def run_to_end(client, party, uid, max_steps=12):
    """Drive agent turns via /step until the negotiation closes."""
    state = client.get(f"/api/negotiations/{uid}", headers=party).json()
    steps = 0
    while state["status"] == "NEGOTIATING" and state["waiting_for"] is None and steps < max_steps:
        state = client.post(f"/api/negotiations/{uid}/step", headers=party).json()
        steps += 1
    return state


def clear_holds(pid):
    """Release any lingering HELD reservations so a test starts from known availability."""
    from database import SessionLocal
    from models import Reservation
    db = SessionLocal()
    for r in db.query(Reservation).filter(Reservation.product_id == pid,
                                          Reservation.status == "HELD").all():
        r.status = "RELEASED"
    db.commit()
    db.close()


def send_webhook(client, event, reference_id, event_id):
    payload = {"event": event, "payload": {"payment_link": {"entity": {"reference_id": reference_id}}}}
    raw = json.dumps(payload).encode()
    sig = hmac.new(WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/razorpay", content=raw,
                       headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id,
                                "content-type": "application/json"})
