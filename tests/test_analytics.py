"""Merchant analytics dashboard (§16, §18)."""
from helpers import negotiate, product_id, result_for, set_stock


def _confirmed_order_with_upsell(client, buyer, merchant_b):
    set_stock(client, merchant_b, product_id(client, merchant_b), 200)
    data = negotiate(client, buyer, 50)
    uid = result_for(data, "WorkSpace Direct")["negotiation_uid"]
    agr = client.post("/api/buyer/agreement", headers=buyer,
                      json={"negotiation_uid": uid, "accept_upsell": True}).json()
    client.post("/api/buyer/checkout", headers=buyer,
                json={"agreement_uid": agr["agreement_uid"]})
    return agr


def test_analytics_structure_and_values(client, buyer, merchant_b):
    agr = _confirmed_order_with_upsell(client, buyer, merchant_b)
    a = client.get("/api/merchant/analytics", headers=merchant_b).json()

    for section in ("overview", "negotiation_intelligence", "upsell_intelligence",
                    "payment_health", "recommendations", "policy_actions",
                    "price_trend", "recent_negotiations"):
        assert section in a, section

    o = a["overview"]
    assert o["confirmed_orders"] >= 1
    assert o["gmv"] >= agr["total"] > 0
    assert o["aov"] > 0
    assert 0 <= o["success_rate_pct"] <= 100

    ni = a["negotiation_intelligence"]
    assert ni["closing_by_product"], "should have at least one closed product"
    assert ni["avg_discount_pct"] >= 0

    ui = a["upsell_intelligence"]
    assert ui["rules"], "merchant B has an upsell rule"
    desk = next(r for r in ui["rules"] if r["upsell_product"] == "Desk Mat")
    assert desk["accepted"] >= 1
    assert desk["revenue"] > 0
    assert ui["total_cross_sell_revenue"] > 0

    assert a["payment_health"]["confirmed"] >= 1
    assert len(a["recommendations"]) >= 1
    assert a["recent_negotiations"], "recent feed populated"


def test_analytics_isolated_per_merchant(client, merchant_a):
    """Merchant A (no orders in this flow) sees its own numbers, not merchant B's."""
    a = client.get("/api/merchant/analytics", headers=merchant_a).json()
    # Merchant A has no confirmed orders from the upsell flow above.
    assert a["overview"]["gmv"] == 0 or a["overview"]["confirmed_orders"] == 0 \
        or a["upsell_intelligence"]["total_cross_sell_revenue"] == 0
