"""Phase 2 negotiation fidelity: concurrency, persisted per-round offers,
reason codes, and the standalone negotiation lookup endpoint (§5, §10, §21)."""
import json

from helpers import negotiate, result_for, set_stock, product_id


def test_parallel_flag_and_both_merchants_agree(client, buyer, merchant_b):
    set_stock(client, merchant_b, product_id(client, merchant_b), 200)
    data = negotiate(client, buyer, 50)
    assert data["concurrency"] == "parallel"
    names = {r["merchant_name"]: r for r in data["results"]}
    assert names["WorkSpace Direct"]["status"] == "AGREED"
    assert names["Comfort Seating"]["status"] == "AGREED"
    # Cheapest total is recommended (Comfort at floor 4400 beats WorkSpace 4466.67).
    rec = data["recommended_negotiation_uid"]
    assert rec == names["Comfort Seating"]["negotiation_uid"]


def test_reason_codes(client, buyer):
    # Target 4300: both merchants' final price lands within 5% -> WITHIN_TARGET.
    data = negotiate(client, buyer, 50)
    assert result_for(data, "WorkSpace Direct")["reason_code"] == "AGREED_WITHIN_TARGET"
    assert result_for(data, "Comfort Seating")["reason_code"] == "AGREED_WITHIN_TARGET"

    # Target 4100: Comfort's floor (4400) sits in the 5-10% stretch band -> FINAL_ROUND.
    stretch = negotiate(client, buyer, 50, target=4100)
    assert result_for(stretch, "Comfort Seating")["reason_code"] == "AGREED_FINAL_ROUND"

    # Impossibly low target: walk away before any counter.
    denied = negotiate(client, buyer, 10, target=1000)
    assert all(r["reason_code"] == "WALKAWAY_EXCEEDED" for r in denied["results"])


def test_offers_persisted_and_lookup(client, buyer):
    data = negotiate(client, buyer, 50)
    cs = result_for(data, "Comfort Seating")
    uid = cs["negotiation_uid"]

    got = client.get(f"/api/negotiations/{uid}", headers=buyer)
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "AGREED"
    assert len(body["offers"]) == cs["rounds"] >= 1
    # Every round is a first-class record with a reason code, ordered by round.
    rounds = [o["round"] for o in body["offers"]]
    assert rounds == sorted(rounds)
    assert all(o["reason_code"] for o in body["offers"])
    assert body["offers"][-1]["accepted"] is True
    # Private policy never leaks through the lookup either.
    assert "floor_price" not in json.dumps(body)


def test_lookup_visible_to_merchant_party(client, buyer, merchant_b):
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    r = client.get(f"/api/negotiations/{uid}", headers=merchant_b)
    assert r.status_code == 200
    assert r.json()["negotiation_uid"] == uid


def test_lookup_forbidden_for_non_party(client, buyer, merchant_a):
    # Merchant A is not a party to a WorkSpace Direct (merchant B) negotiation.
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    r = client.get(f"/api/negotiations/{uid}", headers=merchant_a)
    assert r.status_code == 403
