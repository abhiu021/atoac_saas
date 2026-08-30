"""Live-LLM layer: when enabled it authors the prose, but never the numbers.
The SDK call is stubbed so no network/key is needed."""
import config
import llm
from helpers import negotiate, result_for


def test_llm_authors_prose_not_prices(client, buyer, monkeypatch):
    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", "test-key")  # enable
    monkeypatch.setattr(llm, "_complete",
                        lambda system, user, max_tokens=160: "STUB agent line")

    data = negotiate(client, buyer, 50)
    ws = result_for(data, "WorkSpace Direct")
    neg = client.get(f"/api/negotiations/{ws['negotiation_uid']}", headers=buyer).json()

    # Agent-authored lines use the (stubbed) LLM text...
    assert any(m["text"] == "STUB agent line" for m in neg["messages"] if m["type"] == "agent")
    # ...but the negotiated price is exactly the deterministic engine value.
    assert ws["unit_price"] == 4466.67
    assert ws["status"] == "AGREED"


def test_llm_intent_path(client, buyer, monkeypatch):
    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_complete", lambda system, user, max_tokens=200:
                        '{"product":"chair","quantity":75,"target_price":4100,"max_delivery_days":14}')
    r = client.post("/api/buyer/intent", headers=buyer, json={"message": "anything"}).json()
    assert r["rfq"]["quantity"] == 75 and r["rfq"]["target_price"] == 4100
    assert r["rfq"]["max_delivery_days"] == 14


def test_llm_off_uses_templates(client, buyer):
    # With no key (default), messages are the deterministic templates.
    data = negotiate(client, buyer, 50)
    ws = result_for(data, "WorkSpace Direct")
    neg = client.get(f"/api/negotiations/{ws['negotiation_uid']}", headers=buyer).json()
    assert any("Best we can do this round" in m["text"] for m in neg["messages"])
