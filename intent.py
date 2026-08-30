"""Natural-language understanding for the buyer (§7 Intent Parser).

`parse_rfq` turns a free-text buying request into a structured RFQ; `parse_action`
turns a free-text negotiation reply into a bounded action. If GEMINI_API_KEY is
set, the RFQ parse uses the LLM (with a deterministic fallback); action parsing is
always deterministic so it stays fast and predictable.

NOTE: parsing only *reads* intent. Every number it produces still flows through the
same deterministic guardrail before it can affect a price or a payment.
"""
import json
import re

import llm
from config import settings

_STOP = {
    "i", "we", "want", "need", "looking", "look", "buy", "buying", "purchase", "order",
    "get", "for", "of", "the", "a", "an", "to", "some", "please", "can", "you", "help",
    "find", "me", "with", "and", "that", "this", "like", "would", "around", "about",
    "approx", "budget", "under", "below", "max", "maximum", "upto", "up", "at", "per",
    "unit", "units", "each", "piece", "pieces", "pcs", "price", "priced", "delivery",
    "deliver", "delivered", "within", "days", "day", "week", "weeks", "month", "months",
    "quantity", "qty", "nos", "no", "in", "by", "my", "our", "is", "are", "it", "them",
    "hi", "hello", "hey", "there", "quote", "rate", "rates", "cost", "total", "roughly",
    "target", "want", "need", "ideally", "prefer", "preferably", "about",
}


def parse_rfq(message: str) -> dict:
    if settings.llm_enabled:
        llm = _parse_rfq_llm(message)
        if llm is not None:
            return llm
    return _parse_rfq_rule(message)


def parse_basket(message: str) -> list[dict]:
    """Split a multi-item request into line items. Each clause is parsed as its own
    RFQ; a delivery window stated once applies to the whole basket."""
    clauses = re.split(r"\s*(?:,|;|&|\band\b|\bplus\b|\balso\b)\s*", message, flags=re.I)
    lines, shared_delivery = [], None
    for c in clauses:
        if not c.strip():
            continue
        r = parse_rfq(c)
        if r.get("max_delivery_days"):
            shared_delivery = r["max_delivery_days"]
        if r.get("query") and r.get("quantity"):
            lines.append(r)
    for ln in lines:
        if ln.get("max_delivery_days") is None:
            ln["max_delivery_days"] = shared_delivery
    return lines


# --- Deterministic RFQ parser ------------------------------------------------

def _parse_rfq_rule(message: str) -> dict:
    low = (message or "").lower()
    used: list[tuple[int, int]] = []
    r = {"query": None, "quantity": None, "target_price": None, "max_delivery_days": None}

    # Delivery window
    m = re.search(r"(\d+)\s*(day|days|week|weeks|month|months)", low)
    if m:
        n = int(m.group(1))
        mult = 7 if "week" in m.group(2) else 30 if "month" in m.group(2) else 1
        r["max_delivery_days"] = n * mult
        used.append(m.span())
    elif re.search(r"\b(a|one|next)\s+week\b", low):
        r["max_delivery_days"] = 7
    elif re.search(r"\btomorrow\b", low):
        r["max_delivery_days"] = 1

    # Price cues
    price = None
    for pat in (
        r"(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?)",
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:each|apiece|per\s*unit|/\s*unit|a\s*unit|per\s*piece)",
        r"(?:around|about|approx\.?|budget(?:\s*of)?|under|below|max(?:imum)?|upto|up\s*to|at|for)\s*₹?\s*(\d[\d,]*(?:\.\d+)?)",
    ):
        mm = re.search(pat, low)
        if mm:
            price = float(mm.group(1).replace(",", ""))
            used.append(mm.span())
            break

    # Quantity cues
    qty = None
    mq = re.search(r"(\d[\d,]*)\s*(?:units?|pcs?|pieces?|nos?\.?|qty|quantity)\b", low)
    if mq:
        qty = int(mq.group(1).replace(",", ""))
        used.append(mq.span())

    # Assign leftover bare integers
    def in_used(pos: int) -> bool:
        return any(s <= pos < e for s, e in used)

    leftover = [int(x.group().replace(",", "")) for x in re.finditer(r"\d[\d,]*", low)
                if not in_used(x.start())]
    if qty is None and price is None and len(leftover) >= 2:
        s = sorted(leftover)
        qty, price = s[0], float(s[-1])
    elif qty is None and leftover:
        rem = [v for v in leftover if float(v) != price]
        if rem:
            qty = min(rem)
    elif price is None and leftover:
        rem = [v for v in leftover if v != qty]
        if rem:
            price = float(max(rem))

    r["quantity"] = qty
    r["target_price"] = price
    r["query"] = _extract_product(low)
    return r


def _extract_product(low: str) -> str | None:
    tmp = re.sub(r"(?:₹|rs\.?|inr)\s*\d[\d,]*(?:\.\d+)?", " ", low)
    tmp = re.sub(r"\d[\d,]*(?:\.\d+)?", " ", tmp)
    tmp = re.sub(r"[^a-z\s]", " ", tmp)
    words = [w for w in tmp.split() if w not in _STOP and len(w) > 2]
    return " ".join(words) if words else None


# --- LLM RFQ parser (optional) -----------------------------------------------

def _parse_rfq_llm(message: str) -> dict | None:
    text = llm.complete(
        system=("Extract a purchase request. Respond with ONLY a JSON object, no prose, with keys: "
                "product (string|null — the item), quantity (integer|null), target_price (number|null — "
                "price PER UNIT), max_delivery_days (integer|null — convert weeks/months). Use null for "
                "anything not stated; never invent values."),
        user=message,
    )
    if not text:
        return None
    try:
        data = json.loads(re.search(r"\{.*\}", text, re.S).group())
        return {
            "query": data.get("product"),
            "quantity": int(data["quantity"]) if data.get("quantity") is not None else None,
            "target_price": float(data["target_price"]) if data.get("target_price") is not None else None,
            "max_delivery_days": int(data["max_delivery_days"]) if data.get("max_delivery_days") is not None else None,
        }
    except Exception:
        return None


# --- Negotiation action parser (always deterministic) ------------------------

def parse_action(message: str) -> dict:
    low = (message or "").lower().strip()
    # Reject is checked first so "no deal" isn't caught by "deal".
    if re.search(r"\b(reject|pass|no deal|walk away|cancel|forget it|not interested|"
                 r"decline|too expensive|nevermind|never mind)\b", low):
        return {"action": "reject", "price": None, "text": message}
    if re.search(r"\b(accept|deal|agreed?|take it|sounds good|works for me|go ahead|"
                 r"confirm|i'?ll take|lets do it|let'?s do it)\b", low):
        return {"action": "accept", "price": None, "text": message}
    pm = re.search(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)", low)
    if pm and re.search(r"(offer|counter|do|how about|can you|make it|match|₹|rs|at|price|per|each|\d)", low):
        return {"action": "counter", "price": float(pm.group(1).replace(",", "")), "text": message}
    return {"action": "message", "price": None, "text": message}
