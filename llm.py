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
import httpx

from config import settings

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _complete(system: str, user: str, max_tokens: int = 160) -> str | None:
    """One short, low-latency completion. Returns text, or None on any failure."""
    if not settings.llm_enabled:
        return None
    try:
        resp = httpx.post(
            _GEMINI_URL.format(model=settings.GEMINI_MODEL),
            params={"key": settings.GEMINI_API_KEY},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens, "temperature": 0.7,
                    "thinkingConfig": {"thinkingBudget": 0},  # short prose — don't spend tokens "thinking"
                },
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        data = resp.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception:
        return None


def complete(system: str, user: str, max_tokens: int = 200) -> str | None:
    """Public one-shot completion for other modules (e.g. intent parsing)."""
    return _complete(system, user, max_tokens)


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
