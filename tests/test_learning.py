"""Learning loop (§17): analytics suggests a floor change; applying it creates a
PENDING policy change that the merchant approves — feeding back into policy."""
from helpers import negotiate, product_id, set_stock


def test_walkaway_produces_actionable_suggestion_and_approval_loop(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    # Create history: some agreed deals + walk-aways (target far below floor).
    for _ in range(2):
        negotiate(client, buyer, 20, target=4300)
    for _ in range(2):
        negotiate(client, buyer, 10, target=1200)  # WALKAWAY_EXCEEDED for WorkSpace

    a = client.get("/api/merchant/analytics", headers=merchant_b).json()
    assert "policy_actions" in a
    act = next((x for x in a["policy_actions"] if x["product_id"] == pid), None)
    assert act is not None
    assert act["field"] == "floor_price" and act["suggested"] < act["current"]

    # Apply -> creates a PENDING policy change (not yet in effect).
    before = client.get("/api/merchant/products", headers=merchant_b).json()
    floor_before = next(p for p in before if p["id"] == pid)["floor_price"]
    r = client.post("/api/merchant/policy-suggestion", headers=merchant_b,
                    json={"product_id": pid, "floor_price": act["suggested"]})
    assert r.status_code == 200
    req_id = r.json()["request_id"]
    # Still not applied.
    mid = client.get("/api/merchant/products", headers=merchant_b).json()
    assert next(p for p in mid if p["id"] == pid)["floor_price"] == floor_before

    # Approve -> new policy takes effect.
    client.post(f"/api/merchant/policy-changes/{req_id}/approve", headers=merchant_b)
    after = client.get("/api/merchant/products", headers=merchant_b).json()
    assert next(p for p in after if p["id"] == pid)["floor_price"] == act["suggested"]

    # Restore shared state so later tests keep the seeded floor.
    from database import SessionLocal
    from models import PolicyChangeRequest, Product
    db = SessionLocal()
    db.get(Product, pid).floor_price = floor_before
    for pc in (db.query(PolicyChangeRequest)
               .filter(PolicyChangeRequest.product_id == pid, PolicyChangeRequest.status == "PENDING").all()):
        pc.status = "REJECTED"
    db.commit()
    db.close()


def test_suggestion_ownership(client, merchant_a, merchant_b):
    pid = product_id(client, merchant_b)
    r = client.post("/api/merchant/policy-suggestion", headers=merchant_a,
                    json={"product_id": pid, "floor_price": 4000})
    assert r.status_code == 403
