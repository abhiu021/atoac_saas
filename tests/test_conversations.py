"""Persistent buyer chat history (create / list / save / load / delete)."""


def test_conversation_lifecycle(client, buyer):
    created = client.post("/api/buyer/conversations", headers=buyer).json()
    uid = created["uid"]
    assert created["title"] == "New chat" and created["items"] == []

    items = [{"t": "row", "kind": "user", "avatar": "You", "name": "", "html": "50 chairs"},
             {"t": "sys", "text": "Negotiation opened"}]
    client.put(f"/api/buyer/conversations/{uid}", headers=buyer,
               json={"title": "50 chairs", "items": items})

    got = client.get(f"/api/buyer/conversations/{uid}", headers=buyer).json()
    assert got["title"] == "50 chairs"
    assert len(got["items"]) == 2 and got["items"][1]["text"] == "Negotiation opened"

    listed = client.get("/api/buyer/conversations", headers=buyer).json()
    assert any(c["uid"] == uid and c["title"] == "50 chairs" for c in listed)

    assert client.delete(f"/api/buyer/conversations/{uid}", headers=buyer).status_code == 200
    assert client.get(f"/api/buyer/conversations/{uid}", headers=buyer).status_code == 404


def test_conversation_requires_buyer(client, merchant_b):
    # Merchant token can't create buyer conversations.
    assert client.post("/api/buyer/conversations", headers=merchant_b).status_code == 403
