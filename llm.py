"""Optional LLM layer — makes the agents *talk* naturally.

STRICT BOUNDARY: the LLM only turns already-decided facts into prose. It never
returns a number used for pricing, acceptance, or payment — those come from the
deterministic engine and pass the guardrail before any LLM text is generated. If
no GEMINI_API_KEY is set (or any call fails), deterministic templates are used, so
the product behaves identically with the LLM off.

Uses Google's Gemini API (free tier) over plain REST — no SDK needed. Enable by
setting GEMINI_API_KEY; optionally set GEMINI_MODEL (defaults to gemini-2.0-flash).
Get a free key at https://aistudio.google.com/app/apikey.
"""
import time

import httpx

from config import settings

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_TRANSIENT = {429, 500, 502, 503, 504}  # rate-limit / "high demand" — worth one retry


def _complete(system: str, user: str, max_tokens: int = 160) -> str | None:
    """One short, low-latency completion. Returns text, or None on any failure.
    The free tier occasionally returns 503 ('high demand'), so retry once."""
    if not settings.llm_enabled:
        return None
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens, "temperature": 0.7,
            "thinkingConfig": {"thinkingBudget": 0},  # short prose — don't spend tokens "thinking"
        },
    }
    for attempt in (0, 1):
        try:
            resp = httpx.post(_GEMINI_URL.format(model=settings.GEMINI_MODEL),
                              params={"key": settings.GEMINI_API_KEY}, json=body, timeout=15.0)
            if resp.status_code == 200:
                cand = (resp.json().get("candidates") or [{}])[0]
                parts = (cand.get("content") or {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return text
            elif resp.status_code not in _TRANSIENT:
                return None  # non-transient (e.g. 400/401) — no point retrying
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.7)
    return None


def complete(system: str, user: str, max_tokens: int = 200) -> str | None:
    """Public one-shot completion for other modules (e.g. intent parsing)."""
    return _complete(system, user, max_tokens)


# --- Free-form buyer assistant (off-topic / general questions) ----------------

_ASSISTANT_FALLBACK = ("I'm your ATOAC buying assistant. Tell me what you'd like to buy — "
                       "e.g. “50 ergonomic chairs under ₹4,300 each” — and I'll find "
                       "merchants and negotiate for you. You can also ask me how ATOAC works.")


def assistant_answer(message: str) -> str:
    """Answer a general/off-topic buyer question. Guardrail-safe: the assistant may
    discuss products and how things work, but never quotes a specific merchant price,
    stock level, or deal — those only come from real negotiation."""
    if not settings.llm_enabled:
        return _ASSISTANT_FALLBACK
    text = _complete(
        system=("You are ATOAC's friendly buying assistant for a B2B negotiation marketplace where an "
                "AI agent finds merchants and negotiates on the buyer's behalf within their target. "
                "Answer the user's question helpfully in 2-4 short sentences. You may discuss products, "
                "sourcing, negotiation and how ATOAC works. NEVER invent specific merchant prices, stock, "
                "or deals — those come only from live negotiation. If they seem ready to buy, invite them to "
                "describe what they need (product, quantity, target price)."),
        user=message,
        max_tokens=220,
    )
    return text or _ASSISTANT_FALLBACK


# --- Negotiation narration (auto path, completed deals) ----------------------

def _narrate_template(merchant_name, product_name, status, unit_price, quantity, target, reason) -> str:
    if status == "AGREED":
        return (f"{merchant_name} agreed to supply {quantity}× {product_name} at "
                f"₹{unit_price:,.0f}/unit (your target was ₹{target:,.0f}). {reason}")
    return f"{merchant_name} could not close a deal on {product_name}: {reason}"


def narrate_negotiation(merchant_name, product_name, status, unit_price, quantity,
                        target, transcript, reason) -> str:
    fallback = _narrate_template(merchant_name, product_name, status, unit_price, quantity, target, reason)
    rounds = "; ".join(f"round {t['round']}: ₹{t['merchant_offer']:,.0f}" for t in transcript
                       if t.get("merchant_offer") is not None)
    text = _complete(
        system=("You summarise a completed B2B price negotiation for the buyer in 1-2 friendly "
                "sentences. Use ONLY the facts given; never invent numbers, discounts, or promises."),
        user=(f"Merchant: {merchant_name}\nProduct: {product_name}\nQuantity: {quantity}\n"
              f"Buyer target: ₹{target:,.0f}/unit\nOutcome: {status}\nFinal unit price: {unit_price}\n"
              f"Rounds: {rounds}\nReason: {reason}"),
    )
    return text or fallback


# --- Per-turn negotiation lines (live chat) ----------------------------------

_TONE = {
    "merchant": "You are a merchant's confident but fair AI sales agent.",
    "buyer": "You are a buyer's pragmatic AI procurement agent.",
}


def negotiation_line(role: str, kind: str, *, merchant_name: str, product_name: str,
                     quantity: int, target: float, price: float | None,
                     round_no: int, final: bool, fallback: str) -> str:
    """Generate the natural-language line for one negotiation turn. `price` (when
    given) MUST appear verbatim; the LLM only phrases the message. Falls back to
    the deterministic template when the LLM is off or errors."""
    if not settings.llm_enabled:
        return fallback
    intent_desc = {
        "counter": f"You are countering at ₹{price:,.0f}/unit.",
        "accept": f"You accept the deal at ₹{price:,.0f}/unit.",
        "reject": "You are walking away — no deal.",
        "hold": f"The merchant's ₹{price:,.0f}/unit is above the ₹{target:,.0f} target; "
                f"you push back and ask for a better price (do NOT state a new number).",
    }.get(kind, "")
    text = _complete(
        system=(f"{_TONE.get(role, '')} Write ONE short, natural chat message (max 25 words) for this "
                f"negotiation turn. If a price is given you MUST state it exactly as ₹{price:,.0f}/unit "
                "and invent no other numbers, discounts, or commitments. No greetings, no quotes."),
        user=(f"Product: {product_name} (qty {quantity}). Round {round_no}"
              f"{' (final round)' if final else ''}. {intent_desc}"),
        max_tokens=90,
    )
    return text or fallback
