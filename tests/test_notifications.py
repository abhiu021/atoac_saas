"""Account-level merchant notifications over WebSocket."""
from helpers import product_id, set_stock, start_negotiation


def _token(headers):
    return headers["Authorization"].split(" ", 1)[1]


def test_merchant_notified_of_new_negotiation(client, buyer, merchant_b):
    pid = product_id(client, merchant_b)
    set_stock(client, merchant_b, pid, 200)

    with client.websocket_connect(f"/ws/merchant?token={_token(merchant_b)}") as mws:
        uid = start_negotiation(client, buyer, pid, 30, pause=True).json()["negotiation_uid"]
        # Buyer opens the negotiation socket and pokes it — this broadcasts, which
        # triggers the merchant notification deterministically (no sleep needed).
        with client.websocket_connect(f"/ws/negotiations/{uid}?token={_token(buyer)}") as bws:
            bws.receive_json()  # initial state
            bws.send_json({"type": "say", "message": "hello there"})
            note = mws.receive_json()
            assert note["type"] == "notification"
            assert note["negotiation_uid"] == uid
            assert note["kind"] in ("new", "turn")


def test_ws_merchant_rejects_buyer(client, buyer):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/merchant?token={_token(buyer)}") as ws:
            ws.receive_json()
