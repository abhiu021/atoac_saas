"""Merchant 'manual' mode: with auto_negotiate off, the agent does NOT auto-respond —
new negotiations open with the merchant in HUMAN control and wait for their reply."""
from helpers import product_id

_FULL = ("name", "description", "list_price", "floor_price", "max_discount_pct",
         "min_order_qty", "max_negotiation_rounds", "stock", "delivery_days",
         "strategy", "atoac_enabled")


def _set_auto_negotiate(client, merchant, pid, value):
    p = next(x for x in client.get("/api/merchant/products", headers=merchant).json() if x["id"] == pid)
    body = {k: p[k] for k in _FULL}
    body["auto_negotiate"] = value
    r = client.put(f"/api/merchant/products/{pid}", headers=merchant, json=body)
    assert r.status_code == 200, r.text


def test_manual_merchant_starts_in_human_control(client, buyer, merchant_b):
    pid = product_id(client, merchant_b, "Ergonomic Office Chair")
    _set_auto_negotiate(client, merchant_b, pid, False)
    try:
        st = client.post("/api/negotiations/start", headers=buyer, json={
            "product_id": pid, "quantity": 40, "target_price": 4300, "pause_agent": False}).json()
        assert st["merchant_control"] == "HUMAN"
        assert st["status"] == "NEGOTIATING"       # not auto-closed by an agent
        assert st["waiting_for"] == "merchant"      # it's the merchant's (human) turn
    finally:
        _set_auto_negotiate(client, merchant_b, pid, True)  # restore for other tests


def test_auto_merchant_agent_drives(client, buyer, merchant_b):
    # Default (auto_negotiate on): the merchant side runs on its agent, not waiting on a human.
    pid = product_id(client, merchant_b, "Ergonomic Office Chair")
    st = client.post("/api/negotiations/start", headers=buyer, json={
        "product_id": pid, "quantity": 40, "target_price": 4300, "pause_agent": False}).json()
    assert st["merchant_control"] == "AGENT"
    assert st["waiting_for"] is None
