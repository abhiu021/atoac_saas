"""Auth: bcrypt passwords, JWT sessions, login rate limiting, FastAPI deps."""
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User

# In-memory login attempt tracker: email -> (fail_count, first_fail_ts)
_login_attempts: dict[str, tuple[int, float]] = {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# --- Rate limiting -----------------------------------------------------------

def check_login_allowed(email: str) -> None:
    entry = _login_attempts.get(email)
    if not entry:
        return
    count, first_ts = entry
    window = settings.LOGIN_LOCKOUT_MINUTES * 60
    if time.time() - first_ts > window:
        _login_attempts.pop(email, None)  # window elapsed, reset
        return
    if count >= settings.LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429,
                            detail=f"Too many attempts. Locked for {settings.LOGIN_LOCKOUT_MINUTES} min.")


def record_login_failure(email: str) -> None:
    entry = _login_attempts.get(email)
    now = time.time()
    if not entry or now - entry[1] > settings.LOGIN_LOCKOUT_MINUTES * 60:
        _login_attempts[email] = (1, now)
    else:
        _login_attempts[email] = (entry[0] + 1, entry[1])


def record_login_success(email: str) -> None:
    _login_attempts.pop(email, None)


# --- FastAPI dependencies ----------------------------------------------------

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = decode_token(authorization.split(" ", 1)[1])
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_merchant(user: User = Depends(get_current_user)) -> User:
    if user.role != "merchant":
        raise HTTPException(status_code=403, detail="Merchant account required")
    return user


def require_buyer(user: User = Depends(get_current_user)) -> User:
    if user.role != "buyer":
        raise HTTPException(status_code=403, detail="Buyer account required")
    return user
