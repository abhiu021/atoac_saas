"""Merchant-approval workflow for material policy changes (§28)."""
from helpers import clear_pending, get_product, product_id, put_product


def test_material_change_requires_approval_then_applies(client, merchant_b):
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    put_product(client, merchant_b, pid, floor_price=4200)  # normalise baseline

    r = put_product(client, merchant_b, pid, floor_price=4300)
    assert r.status_code == 200
    body = r.json()
    assert body["pending_policy_change"] is not None
    assert "floor_price" in body["pending_policy_change"]["changes"]
    # Not applied yet — product still shows the old floor.
    assert get_product(client, merchant_b, pid)["floor_price"] == 4200

    req_id = body["pending_policy_change"]["request_id"]
    ap = client.post(f"/api/merchant/policy-changes/{req_id}/approve", headers=merchant_b)
    assert ap.status_code == 200
    assert get_product(client, merchant_b, pid)["floor_price"] == 4300


def test_nonmaterial_change_applies_immediately(client, merchant_b):
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    r = put_product(client, merchant_b, pid, stock=321, delivery_days=6)
    assert r.json()["pending_policy_change"] is None
    p = get_product(client, merchant_b, pid)
    assert p["stock"] == 321 and p["delivery_days"] == 6


def test_reject_discards_change(client, merchant_b):
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    put_product(client, merchant_b, pid, max_discount_pct=10)
    before = get_product(client, merchant_b, pid)["max_discount_pct"]
    r = put_product(client, merchant_b, pid, max_discount_pct=25)
    req_id = r.json()["pending_policy_change"]["request_id"]
    client.post(f"/api/merchant/policy-changes/{req_id}/reject", headers=merchant_b)
    assert get_product(client, merchant_b, pid)["max_discount_pct"] == before


def test_duplicate_pending_blocked(client, merchant_b):
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    put_product(client, merchant_b, pid, floor_price=4250)
    r2 = put_product(client, merchant_b, pid, floor_price=4260)
    assert r2.status_code == 409
    clear_pending(client, merchant_b)


def test_other_merchant_cannot_approve(client, merchant_a, merchant_b):
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    r = put_product(client, merchant_b, pid, floor_price=4230)
    req_id = r.json()["pending_policy_change"]["request_id"]
    ap = client.post(f"/api/merchant/policy-changes/{req_id}/approve", headers=merchant_a)
    assert ap.status_code == 403
    clear_pending(client, merchant_b)


def test_negotiation_uses_approved_policy_only(client, buyer, merchant_b):
    """A queued floor increase must NOT affect live negotiations until approved."""
    from helpers import negotiate, result_for, set_stock
    pid = product_id(client, merchant_b)
    clear_pending(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    put_product(client, merchant_b, pid, floor_price=4200)

    # Queue a large floor increase but do NOT approve it.
    put_product(client, merchant_b, pid, floor_price=4550)
    data = negotiate(client, buyer, 20, target=4300)
    ws = result_for(data, "WorkSpace Direct")
    # Old floor 4200 still governs, so a sub-4550 close is still reachable.
    assert ws["status"] == "AGREED"
    assert ws["unit_price"] < 4550
    clear_pending(client, merchant_b)
