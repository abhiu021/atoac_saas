"""Interactive negotiation: chat log, stepping, and human takeover on both sides."""
from helpers import (negotiate, product_id, result_for, run_to_end, set_stock,
                     start_negotiation)


def test_auto_negotiation_produces_chat_log(client, buyer):
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "Comfort Seating")["negotiation_uid"]
    state = client.get(f"/api/negotiations/{uid}", headers=buyer).json()
    kinds = [(m["role"], m["kind"]) for m in state["messages"]]
    assert ("buyer", "offer") == kinds[0]                 # buyer opens
    assert any(r == "merchant" and k == "counter" for r, k in kinds)
    assert any(k == "accept" for _, k in kinds)           # someone closes it
    assert state["status"] == "AGREED"
    assert state["your_role"] == "buyer"


def test_start_and_step_to_agreement(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    st = start_negotiation(client, buyer, pid, 50).json()
    assert st["status"] == "NEGOTIATING" and st["turn"] == "merchant"
    assert st["messages"][0]["kind"] == "offer"
    uid = st["negotiation_uid"]
    final = run_to_end(client, buyer, uid)
    assert final["status"] == "AGREED"
    assert final["final_unit_price"] is not None


def test_buyer_human_takeover_accept(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 50).json()["negotiation_uid"]
    # One step -> merchant counters, now buyer's turn.
    st = client.post(f"/api/negotiations/{uid}/step", headers=buyer).json()
    assert st["turn"] == "buyer"
    # Buyer pauses their agent and accepts the standing merchant offer.
    client.post(f"/api/negotiations/{uid}/control", headers=buyer, json={"mode": "HUMAN"})
    st = client.post(f"/api/negotiations/{uid}/act", headers=buyer,
                     json={"action": "accept"}).json()
    assert st["status"] == "AGREED"
    assert st["reason_code"] == "BUYER_ACCEPTED"
    assert any(m["type"] == "human" and m["kind"] == "accept" for m in st["messages"])


def test_act_requires_pause_first(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 50).json()["negotiation_uid"]
    client.post(f"/api/negotiations/{uid}/step", headers=buyer)  # -> buyer's turn, agent still on
    r = client.post(f"/api/negotiations/{uid}/act", headers=buyer, json={"action": "accept"})
    assert r.status_code == 400
    assert "pause" in r.json()["detail"].lower()


def test_merchant_human_guardrail_blocks_below_floor(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 50).json()["negotiation_uid"]
    # Merchant pauses at the very start (it's the merchant's turn) and tries to
    # counter below the floor — must be rejected by the guardrail.
    client.post(f"/api/negotiations/{uid}/control", headers=merchant_b, json={"mode": "HUMAN"})
    bad = client.post(f"/api/negotiations/{uid}/act", headers=merchant_b,
                      json={"action": "counter", "price": 1000})
    assert bad.status_code == 400 and "floor" in bad.json()["detail"].lower()
    # A within-policy counter above the buyer's target: the buyer agent holds and
    # hands the turn back to the (paused) merchant, who is now waiting to respond.
    ok = client.post(f"/api/negotiations/{uid}/act", headers=merchant_b,
                     json={"action": "counter", "price": 4600}).json()
    assert ok["turn"] == "merchant" and ok["waiting_for"] == "merchant"
    assert any(m["role"] == "merchant" and m["type"] == "human" for m in ok["messages"])


def test_non_party_cannot_control(client, buyer, merchant_a, merchant_b):
    pid = product_id(client, merchant_b)
    uid = start_negotiation(client, buyer, pid, 50).json()["negotiation_uid"]
    r = client.post(f"/api/negotiations/{uid}/control", headers=merchant_a, json={"mode": "HUMAN"})
    assert r.status_code == 403


def test_merchant_sees_its_negotiations(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    uid = start_negotiation(client, buyer, pid, 50).json()["negotiation_uid"]
    rows = client.get("/api/merchant/negotiations", headers=merchant_b).json()
    assert any(r["negotiation_uid"] == uid for r in rows)
