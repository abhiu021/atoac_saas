"""WebSocket hub for live negotiations.

Replaces client polling: each negotiation has a set of subscribed sockets and a
single server-side "driver" task that advances AGENT-controlled turns (with a
small delay for realism) and broadcasts the new state to everyone watching. This
also means a negotiation progresses even if no buyer tab is open to drive it.

DB work is synchronous (SQLAlchemy); it runs via asyncio.to_thread so the event
loop is never blocked. A per-negotiation asyncio.Lock serialises mutations.
"""
import asyncio
from collections import defaultdict

import intent
import negotiation as neg_engine
from database import SessionLocal
from models import Negotiation, Product, User

STEP_DELAY = 0.55  # seconds between automatic agent turns


# --- Synchronous DB operations (run in a worker thread) ----------------------

def party_role(uid: str, user_id: int) -> str | None:
    db = SessionLocal()
    try:
        neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
        if not neg:
            return None
        if user_id == neg.buyer_id:
            return "buyer"
        if user_id == neg.merchant_id:
            return "merchant"
        return None
    finally:
        db.close()


def is_merchant(user_id: int) -> bool:
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        return bool(u and u.role == "merchant")
    finally:
        db.close()


def get_state(uid: str) -> dict:
    db = SessionLocal()
    try:
        neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
        if not neg:
            return {"type": "gone"}
        return neg_engine.state_dict(db, neg)
    finally:
        db.close()


def _with_neg(uid: str, fn):
    db = SessionLocal()
    try:
        neg = db.query(Negotiation).filter(Negotiation.uid == uid).first()
        if not neg:
            raise ValueError("Negotiation not found")
        product = db.get(Product, neg.product_id)
        return fn(db, neg, product)
    finally:
        db.close()


def step(uid: str) -> None:
    _with_neg(uid, lambda db, neg, p: neg_engine.step_once(db, neg, p))


def apply_say(uid: str, role: str, message: str) -> None:
    def run(db, neg, product):
        act = intent.parse_action(message)
        if act["action"] == "message":
            neg_engine.human_act(db, neg, product, role, "message", text=act["text"])
        else:
            control = neg.buyer_control if role == "buyer" else neg.merchant_control
            if control != "HUMAN":
                neg_engine.set_control(db, neg, role, "HUMAN")
            neg_engine.human_act(db, neg, product, role, act["action"],
                                 price=act.get("price"), text=act["text"])
    _with_neg(uid, run)


def apply_act(uid: str, role: str, action: str, price, text) -> None:
    _with_neg(uid, lambda db, neg, p: neg_engine.human_act(db, neg, p, role, action, price=price, text=text))


def set_control(uid: str, role: str, mode: str) -> None:
    _with_neg(uid, lambda db, neg, p: neg_engine.set_control(db, neg, role, mode))


def _is_agent_turn(st: dict) -> bool:
    turn = st.get("turn")
    if not turn:
        return False
    ctrl = st["buyer_control"] if turn == "buyer" else st["merchant_control"]
    return ctrl == "AGENT"


# --- Async hub ---------------------------------------------------------------

class MerchantHub:
    """Account-level notification channel: pushes alerts to a merchant's open
    dashboards when a negotiation of theirs starts, needs them, or closes."""

    def __init__(self):
        self.subs: dict[int, set] = defaultdict(set)

    async def register(self, merchant_id: int, ws) -> None:
        self.subs[merchant_id].add(ws)

    def unregister(self, merchant_id: int, ws) -> None:
        self.subs[merchant_id].discard(ws)

    async def notify(self, merchant_id: int, payload: dict) -> None:
        for ws in list(self.subs.get(merchant_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.subs[merchant_id].discard(ws)


merchant_hub = MerchantHub()


class NegotiationHub:
    def __init__(self):
        self.subs: dict[str, set] = defaultdict(set)
        self.locks: dict[str, asyncio.Lock] = {}
        self.drivers: dict[str, asyncio.Task] = {}
        self._notif: dict[str, dict] = {}  # last-notified signature per uid (dedup)

    def _lock(self, uid: str) -> asyncio.Lock:
        return self.locks.setdefault(uid, asyncio.Lock())

    async def register(self, uid: str, ws) -> None:
        self.subs[uid].add(ws)

    def unregister(self, uid: str, ws) -> None:
        self.subs[uid].discard(ws)

    async def send_state(self, uid: str, ws) -> None:
        st = await asyncio.to_thread(get_state, uid)
        await ws.send_json(st)

    async def broadcast(self, uid: str) -> None:
        st = await asyncio.to_thread(get_state, uid)
        for ws in list(self.subs.get(uid, ())):
            try:
                await ws.send_json(st)
            except Exception:
                self.subs[uid].discard(ws)
        await self._maybe_notify(uid, st)

    async def _maybe_notify(self, uid: str, st: dict) -> None:
        mid = st.get("merchant_id")
        if mid is None or st.get("status") is None:
            return
        prev = self._notif.get(uid)
        needs_merchant = st.get("waiting_for") == "merchant"
        events = []
        if prev is None:
            events.append(("new", f"New negotiation · {st['quantity']}× {st['product_name']}"))
        if needs_merchant and (prev is None or not prev["needs"]):
            events.append(("turn", f"Your input needed · {st['product_name']}"))
        if st["status"] != "NEGOTIATING" and (prev is None or prev["status"] == "NEGOTIATING"):
            verb = "agreed" if st["status"] == "AGREED" else st["status"].lower()
            events.append(("closed", f"Negotiation {verb} · {st['product_name']}"))
        self._notif[uid] = {"status": st["status"], "needs": needs_merchant}
        for kind, text in events:
            await merchant_hub.notify(mid, {
                "type": "notification", "kind": kind, "negotiation_uid": uid,
                "product_name": st.get("product_name"), "status": st["status"], "text": text})

    async def ensure_driver(self, uid: str) -> None:
        t = self.drivers.get(uid)
        if t and not t.done():
            return
        self.drivers[uid] = asyncio.create_task(self._drive(uid))

    async def _drive(self, uid: str) -> None:
        """Advance agent turns until a human turn or a terminal state."""
        try:
            while True:
                await asyncio.sleep(STEP_DELAY)
                stop = False
                async with self._lock(uid):
                    st = await asyncio.to_thread(get_state, uid)
                    if st.get("status") != "NEGOTIATING" or not _is_agent_turn(st):
                        stop = True
                    else:
                        await asyncio.to_thread(step, uid)
                await self.broadcast(uid)
                if stop:
                    break
        finally:
            self.drivers.pop(uid, None)

    async def handle(self, uid: str, role: str, msg: dict, ws) -> None:
        kind = msg.get("type")
        try:
            async with self._lock(uid):
                if kind == "say":
                    await asyncio.to_thread(apply_say, uid, role, msg.get("message", ""))
                elif kind == "control":
                    await asyncio.to_thread(set_control, uid, role, msg.get("mode", "AGENT"))
                elif kind == "act":
                    await asyncio.to_thread(apply_act, uid, role, msg.get("action"),
                                            msg.get("price"), msg.get("text"))
                elif kind == "step":
                    await asyncio.to_thread(step, uid)
                else:
                    return
        except ValueError as e:
            await ws.send_json({"type": "error", "message": str(e)})
            return
        await self.broadcast(uid)
        await self.ensure_driver(uid)


hub = NegotiationHub()
