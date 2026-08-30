"""Free-form buyer Q&A endpoint. With the LLM off (test default) it returns the
safe fallback; it must never error and never leak a fabricated price."""


def test_ask_returns_answer(client, buyer):
    r = client.post("/api/buyer/ask", headers=buyer, json={"message": "what is ATOAC and how does it work?"})
    assert r.status_code == 200
    ans = r.json()["answer"]
    assert isinstance(ans, str) and len(ans) > 20


def test_ask_requires_auth(client):
    assert client.post("/api/buyer/ask", json={"message": "hi"}).status_code in (401, 403)
