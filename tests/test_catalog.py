"""Catalog: upsell-rule delete + ownership."""
from helpers import product_id


def test_create_and_delete_upsell_rule(client, merchant_b):
    base = product_id(client, merchant_b, "Ergonomic Office Chair")
    up = product_id(client, merchant_b, "Desk Mat")
    created = client.post("/api/merchant/upsell-rules", headers=merchant_b,
                          json={"base_product_id": base, "upsell_product_id": up,
                                "trigger_min_qty": 5}).json()
    rid = created["id"]
    assert any(r["id"] == rid for r in client.get("/api/merchant/upsell-rules", headers=merchant_b).json())

    assert client.delete(f"/api/merchant/upsell-rules/{rid}", headers=merchant_b).status_code == 200
    assert not any(r["id"] == rid for r in client.get("/api/merchant/upsell-rules", headers=merchant_b).json())


def test_cannot_delete_other_merchants_rule(client, merchant_a, merchant_b):
    base = product_id(client, merchant_b, "Ergonomic Office Chair")
    up = product_id(client, merchant_b, "Desk Mat")
    rid = client.post("/api/merchant/upsell-rules", headers=merchant_b,
                      json={"base_product_id": base, "upsell_product_id": up,
                            "trigger_min_qty": 7}).json()["id"]
    assert client.delete(f"/api/merchant/upsell-rules/{rid}", headers=merchant_a).status_code == 403
    client.delete(f"/api/merchant/upsell-rules/{rid}", headers=merchant_b)  # cleanup
