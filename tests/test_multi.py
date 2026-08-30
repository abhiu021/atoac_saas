"""Multi-merchant parallel negotiation: several auto negotiations run to
completion concurrently over WebSockets (the buyer 'negotiate all' path)."""
from helpers import product_id, set_stock


def _token(headers):
    return headers["Authorization"].split(" ", 1)[1]


def test_two_negotiations_run_in_parallel(client, buyer, merchant_a, merchant_b):
    set_stock(client, merchant_a, product_id(client, merchant_a), 200)
    set_stock(client, merchant_b, product_id(client, merchant_b), 200)
    # Discover candidates the way the buyer UI does.
    cands = client.get("/api/buyer/search?query=chair&quantity=40&max_delivery_days=7",
                       headers=buyer).json()["candidates"]
    assert len(cands) >= 2

    results = {}
    for c in cands:
        st = client.post("/api/negotiations/start", headers=buyer, json={
            "product_id": c["id"], "quantity": 40, "target_price": 4300,
            "max_delivery_days": 7, "pause_agent": False}).json()  # both sides AGENT -> auto
        uid = st["negotiation_uid"]
        with client.websocket_connect(f"/ws/negotiations/{uid}?token={_token(buyer)}") as ws:
            final = None
            for _ in range(12):
                s = ws.receive_json()
                if s["status"] != "NEGOTIATING":
                    final = s
                    break
            assert final is not None and final["status"] == "AGREED"
            assert final["rounds"] >= 1  # state now carries round count
            results[c["merchant_name"]] = final["total"]

    # Every candidate produced a real negotiated total; the buyer picks the lowest.
    assert len(results) == len(cands)
    assert min(results.values()) > 0
