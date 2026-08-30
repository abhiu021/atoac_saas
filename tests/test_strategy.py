"""Merchant negotiation strategy presets + product input validation."""
import types

import negotiation as ne


def _p(strategy):
    return types.SimpleNamespace(list_price=4600, floor_price=4200, max_discount_pct=100, strategy=strategy)


def test_strategy_changes_concession_curve():
    r, R = 1, 3
    agg = ne.counter_offer(_p("aggressive"), 4300, r, R)
    bal = ne.counter_offer(_p("balanced"), 4300, r, R)
    firm = ne.counter_offer(_p("firm"), 4300, r, R)
    # Round 1: aggressive concedes lowest, firm holds highest.
    assert agg < bal < firm
    # Final round always lands exactly on the floor, regardless of strategy.
    assert ne.counter_offer(_p("aggressive"), 4300, R, R) == 4200
    assert ne.counter_offer(_p("firm"), 4300, R, R) == 4200


def test_product_input_validation(client, merchant_b):
    base = {"name": "Test", "list_price": 100, "floor_price": 50}
    assert client.post("/api/merchant/products", headers=merchant_b,
                       json={**base, "max_discount_pct": 500}).status_code == 422
    assert client.post("/api/merchant/products", headers=merchant_b,
                       json={**base, "list_price": -5}).status_code == 422
    assert client.post("/api/merchant/products", headers=merchant_b,
                       json={**base, "max_negotiation_rounds": 0}).status_code == 422


def test_invalid_strategy_normalised(client, merchant_b):
    r = client.post("/api/merchant/products", headers=merchant_b,
                    json={"name": "StratTest", "list_price": 100, "floor_price": 50, "strategy": "nonsense"})
    assert r.status_code == 200 and r.json()["strategy"] == "balanced"
    client.delete(f"/api/merchant/products/{r.json()['id']}", headers=merchant_b)  # cleanup
