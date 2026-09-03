"""Natural-language buyer flow: intent parsing, tokenized discovery, and
conversational negotiation via /say (§7)."""
from helpers import product_id, set_stock, start_negotiation


def test_intent_parses_full_request(client, buyer):
    r = client.post("/api/buyer/intent", headers=buyer,
                    json={"message": "I need 50 ergonomic chairs under 4300 each within a week"})
    rfq = r.json()["rfq"]
    assert rfq["quantity"] == 50
    assert rfq["target_price"] == 4300
    assert rfq["max_delivery_days"] == 7
    assert "chair" in (rfq["query"] or "")
    assert r.json()["missing"] == []


def test_intent_reports_missing(client, buyer):
    r = client.post("/api/buyer/intent", headers=buyer, json={"message": "I want some chairs"})
    body = r.json()
    assert "chair" in (body["rfq"]["query"] or "")
    assert "quantity" in body["missing"] and "target_price" in body["missing"]


def test_tokenized_search_matches_natural_phrase(client, buyer):
    r = client.get("/api/buyer/search?query=ergonomic%20office%20chairs&quantity=10&max_delivery_days=7",
                   headers=buyer)
    names = {c["merchant_name"] for c in r.json()["candidates"]}
    assert "WorkSpace Direct" in names and "Comfort Seating" in names


def test_chair_search_excludes_chair_accessories(client, buyer):
    r = client.get("/api/buyer/search?query=chairs&quantity=1&max_delivery_days=7",
                   headers=buyer)
    names = [c["name"].lower() for c in r.json()["candidates"]]
    assert names and all("mat" not in name and "cushion" not in name and "pad" not in name
                         for name in names)


def test_say_natural_language_accept_closes_deal(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 40, pause=True).json()["negotiation_uid"]
    # merchant (agent) counters
    st = client.post(f"/api/negotiations/{uid}/step", headers=buyer).json()
    assert st["turn"] == "buyer"
    # a chit-chat line stays the buyer's turn
    st = client.post(f"/api/negotiations/{uid}/say", headers=buyer,
                     json={"message": "hmm that's a bit high"}).json()
    assert st["status"] == "NEGOTIATING" and st["turn"] == "buyer"
    # natural-language accept closes it
    st = client.post(f"/api/negotiations/{uid}/say", headers=buyer,
                     json={"message": "alright, accept that deal"}).json()
    assert st["status"] == "AGREED" and st["reason_code"] == "BUYER_ACCEPTED"


def test_say_natural_language_counter(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 20, pause=True).json()["negotiation_uid"]
    client.post(f"/api/negotiations/{uid}/step", headers=buyer)  # merchant counters
    st = client.post(f"/api/negotiations/{uid}/say", headers=buyer,
                     json={"message": "can you do 4250?"}).json()
    # buyer's counter was recorded; merchant agent responded, so it's the buyer's turn again or closed
    assert any(m["type"] == "human" and m["role"] == "buyer" and m["unit_price"] == 4250
               for m in st["messages"])
