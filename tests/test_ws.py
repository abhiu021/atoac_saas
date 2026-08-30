"""WebSocket live negotiation: server pushes state, auto-advances the merchant
agent, and applies a natural-language accept sent over the socket."""
from helpers import product_id, set_stock, start_negotiation


def _token(headers):
    return headers["Authorization"].split(" ", 1)[1]


def test_ws_autodrive_and_nl_accept(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)
    uid = start_negotiation(client, buyer, pid, 40, pause=True).json()["negotiation_uid"]

    with client.websocket_connect(f"/ws/negotiations/{uid}?token={_token(buyer)}") as ws:
        first = ws.receive_json()
        assert first["status"] == "NEGOTIATING"

        # Server auto-drives the merchant (agent) counter — no client stepping.
        countered = None
        for _ in range(8):
            st = ws.receive_json()
            if any(m["role"] == "merchant" for m in st["messages"]):
                countered = st
                break
        assert countered is not None and countered["turn"] == "buyer"

        # Natural-language accept over the socket closes the deal.
        ws.send_json({"type": "say", "message": "great, accept that deal"})
        final = None
        for _ in range(8):
            st = ws.receive_json()
            if st["status"] != "NEGOTIATING":
                final = st
                break
        assert final is not None
        assert final["status"] == "AGREED" and final["reason_code"] == "BUYER_ACCEPTED"


def test_ws_rejects_bad_token(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    uid = start_negotiation(client, buyer, pid, 10, pause=True).json()["negotiation_uid"]
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/negotiations/{uid}?token=bogus") as ws:
            ws.receive_json()
