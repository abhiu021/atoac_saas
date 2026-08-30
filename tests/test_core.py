"""Phase 1 guarantees: negotiation, privacy, guardrail, ownership, upsell, webhook."""
import json

from helpers import negotiate, product_id, result_for, send_webhook


def test_negotiation_agrees_within_policy(client, buyer):
    data = negotiate(client, buyer, 50)
    ws = result_for(data, "WorkSpace Direct")
    assert ws["status"] == "AGREED"
    assert ws["unit_price"] >= 4200  # never below floor
    assert data["recommended_negotiation_uid"] is not None


def test_floor_price_never_leaks(client, buyer):
    data = negotiate(client, buyer, 50)
    assert "floor_price" not in json.dumps(data)


def test_low_target_denied(client, buyer):
    data = negotiate(client, buyer, 10, target=1000)
    assert all(r["status"] == "DENIED" for r in data["results"])
    assert all("floor" in r["reason"].lower() or "exceeds" in r["reason"].lower()
               for r in data["results"])


def test_cross_merchant_edit_forbidden(client, merchant_a, merchant_b):
    pid = product_id(client, merchant_a)
    r = client.put(f"/api/merchant/products/{pid}", headers=merchant_b,
                   json={"name": "hijack", "list_price": 1, "floor_price": 1})
    assert r.status_code == 403


def test_upsell_triggers_and_agreement(client, buyer):
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    sel = client.post("/api/buyer/select", headers=buyer, json={"negotiation_uid": uid}).json()
    assert sel["upsell"] and sel["upsell"]["name"] == "Desk Mat"
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": True}).json()
    assert len(agr["items"]) == 2
    co = client.post("/api/buyer/checkout", headers=buyer,
                     json={"agreement_uid": agr["agreement_uid"]}).json()
    assert co["status"] == "CONFIRMED"


def test_webhook_signature_and_idempotency(client, buyer):
    data = negotiate(client, buyer, 15)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    ref = agr["agreement_uid"]

    # tampered -> 400
    r = client.post("/api/webhooks/razorpay", content=b'{"event":"payment_link.paid"}',
                    headers={"x-razorpay-signature": "bad", "x-razorpay-event-id": "e1"})
    assert r.status_code == 400

    # valid -> processed
    r = send_webhook(client, "payment_link.paid", ref, "evt_ok")
    assert r.json()["status"] == "processed"

    # replay -> duplicate ignored
    r = send_webhook(client, "payment_link.paid", ref, "evt_ok")
    assert r.json()["status"] == "duplicate_ignored"


def test_payment_amount_is_server_computed(client, buyer):
    """Buyer cannot influence the charged amount — it comes from Agreement.total."""
    data = negotiate(client, buyer, 12)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": False}).json()
    co = client.post("/api/buyer/checkout", headers=buyer,
                     json={"agreement_uid": agr["agreement_uid"]}).json()
    assert co["amount"] == agr["total"]
