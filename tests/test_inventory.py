"""Phase 1.5: reservation lifecycle, graceful inventory shortfall (§19.1),
payment failure + retry (§19.2)."""
import inventory
from database import SessionLocal
from models import Agreement, Payment, Reservation
from helpers import clear_holds, negotiate, product_id, result_for, send_webhook, set_stock


def _avail(pid):
    db = SessionLocal()
    try:
        return inventory.available_stock(db, pid)
    finally:
        db.close()


def test_reservation_reduces_availability(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    before = _avail(pid)
    data = negotiate(client, buyer, 10)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    assert "agreement_uid" in agr
    assert _avail(pid) == before - 10


def test_shortfall_offers_alternatives(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    data = negotiate(client, buyer, 50, deliv=7)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    clear_holds(pid)
    set_stock(client, merchant_b, pid, 20)  # stock drops mid-flow, below requested
    res = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    assert "inventory_shortfall" in res
    assert 0 < res["inventory_shortfall"]["available"] < 50
    types = {a["type"] for a in res["alternatives"]}
    assert "partial" in types
    # Comfort Seating has full stock and 5-day delivery <= 7 -> offered as alternative
    assert "alternative_merchant" in types


def test_accept_partial(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    data = negotiate(client, buyer, 40, deliv=7)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    clear_holds(pid)
    set_stock(client, merchant_b, pid, 15)
    res = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    avail = res["inventory_shortfall"]["available"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "partial_quantity": avail}).json()
    assert agr["items"][0]["quantity"] == avail
    co = client.post("/api/buyer/checkout", headers=buyer,
                     json={"agreement_uid": agr["agreement_uid"]}).json()
    assert co["status"] == "CONFIRMED"


def test_backorder_when_no_delivery_cap(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    data = negotiate(client, buyer, 50, deliv=None)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    clear_holds(pid)
    set_stock(client, merchant_b, pid, 5)
    res = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    assert "backorder" in {a["type"] for a in res["alternatives"]}
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "backorder": True}).json()
    assert agr["backorder"] is True
    assert agr["items"][0]["quantity"] == 50
    assert agr["delivery_days"] > 7  # extended by restock lead time


def test_payment_failure_releases_and_retry_confirms(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    data = negotiate(client, buyer, 30, deliv=7)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    ref = agr["agreement_uid"]

    # Move to PAYMENT_PENDING and attach a pending payment (simulating live checkout).
    db = SessionLocal()
    a = db.query(Agreement).filter(Agreement.uid == ref).first()
    a.status = "PAYMENT_PENDING"
    db.add(Payment(agreement_id=a.id, amount=a.total, status="PENDING", razorpay_id="plink_x"))
    agr_id = a.id
    db.commit()
    db.close()

    r = send_webhook(client, "payment.failed", ref, "evt_fail")
    assert r.json()["status"] == "processed"

    db = SessionLocal()
    a = db.query(Agreement).filter(Agreement.uid == ref).first()
    released = db.query(Reservation).filter(Reservation.agreement_id == agr_id,
                                            Reservation.status == "RELEASED").count()
    status = a.status
    db.close()
    assert status == "FAILED"
    assert released >= 1

    # Retry checkout re-reserves and confirms via mock.
    co = client.post("/api/buyer/checkout", headers=buyer, json={"agreement_uid": ref}).json()
    assert co["status"] == "CONFIRMED"
