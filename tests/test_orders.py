"""Order history for buyer and merchant."""
from helpers import negotiate, product_id, result_for, set_stock


def _place_confirmed_order(client, buyer, merchant_b):
    set_stock(client, merchant_b, product_id(client, merchant_b), 200)
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": True}).json()
    client.post("/api/buyer/checkout", headers=buyer,
                json={"agreement_uid": agr["agreement_uid"]})
    return agr["agreement_uid"]


def test_buyer_and_merchant_see_the_order(client, buyer, merchant_b):
    agr_uid = _place_confirmed_order(client, buyer, merchant_b)

    b_orders = client.get("/api/buyer/orders", headers=buyer).json()
    mine = next(o for o in b_orders if o["agreement_uid"] == agr_uid)
    assert mine["status"] == "CONFIRMED"
    assert mine["payment_status"] == "CONFIRMED"
    assert mine["counterparty"] == "WorkSpace Direct"
    assert len(mine["items"]) == 2  # chairs + desk mats

    m_orders = client.get("/api/merchant/orders", headers=merchant_b).json()
    same = next(o for o in m_orders if o["agreement_uid"] == agr_uid)
    assert same["counterparty"] == "buyer@test.com"
    assert same["status"] == "CONFIRMED"


def test_orders_scoped_per_user(client, merchant_a):
    # Merchant A had no orders in this flow.
    a_orders = client.get("/api/merchant/orders", headers=merchant_a).json()
    assert all(o["counterparty"] != "buyer@test.com" or o["status"] != "CONFIRMED"
               for o in a_orders) or a_orders == []
