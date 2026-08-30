"""Multi-item basket: parse several line items, then check them out as one order."""
from helpers import negotiate, product_id, result_for, set_stock


def test_basket_intent_parses_multiple_lines(client, buyer):
    r = client.post("/api/buyer/basket-intent", headers=buyer,
                    json={"message": "50 chairs at 4300 and 30 desk mats at 220 within a week"})
    lines = r.json()["lines"]
    assert len(lines) == 2
    assert {ln["quantity"] for ln in lines} == {50, 30}
    # delivery stated once applies to both lines
    assert all(ln["max_delivery_days"] == 7 for ln in lines)


def test_basket_checkout_across_lines(client, buyer, merchant_b):
    set_stock(client, merchant_b, product_id(client, merchant_b, "Ergonomic Office Chair"), 200)
    set_stock(client, merchant_b, product_id(client, merchant_b, "Desk Mat"), 200)

    d1 = negotiate(client, buyer, 40, target=4300, query="chair")
    uid1 = result_for(d1, "WorkSpace Direct")["negotiation_uid"]
    d2 = negotiate(client, buyer, 30, target=220, query="desk mat")
    uid2 = result_for(d2, "WorkSpace Direct")["negotiation_uid"]

    r = client.post("/api/buyer/basket/checkout", headers=buyer,
                    json={"negotiation_uids": [uid1, uid2]})
    body = r.json()
    assert body["status"] == "CONFIRMED"
    assert len(body["lines"]) == 2
    assert all(ln["status"] == "CONFIRMED" for ln in body["lines"])
    assert body["total"] == round(sum(ln["total"] for ln in body["lines"]), 2)

    # Both lines became confirmed orders.
    orders = client.get("/api/buyer/orders", headers=buyer).json()
    uids = {ln["agreement_uid"] for ln in body["lines"]}
    assert uids.issubset({o["agreement_uid"] for o in orders})
    for o in orders:
        if o["agreement_uid"] in uids:
            assert o["status"] == "CONFIRMED"


def test_basket_rejects_empty(client, buyer):
    assert client.post("/api/buyer/basket/checkout", headers=buyer,
                       json={"negotiation_uids": []}).status_code == 400
