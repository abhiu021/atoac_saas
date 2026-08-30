"""DB-backed audit trail. Every material action lands here (see §20)."""
import json

from sqlalchemy.orm import Session

from models import AuditEvent


def log_event(db: Session, actor: str, action: str, details: dict | None = None,
              merchant_id: int | None = None) -> None:
    event = AuditEvent(
        actor=actor,
        action=action,
        details_json=json.dumps(details or {}, default=str),
        merchant_id=merchant_id,
    )
    db.add(event)
    db.commit()


def query_events(db: Session, merchant_id: int | None = None, limit: int = 100) -> list[dict]:
    q = db.query(AuditEvent)
    if merchant_id is not None:
        q = q.filter(AuditEvent.merchant_id == merchant_id)
    rows = q.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "timestamp": r.created_at.isoformat() if r.created_at else None,
            "actor": r.actor,
            "action": r.action,
            "details": json.loads(r.details_json or "{}"),
        }
        for r in rows
    ]
