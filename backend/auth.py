"""Auth utilities: password hashing, JWT issue/verify, FastAPI deps.

A user signs up with their email + password and a company name. We create a
new Company row and the owner User in one transaction. Login returns a JWT
that encodes the user id and the company id. Every protected endpoint uses
`current_company` to filter data by tenant.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
import bcrypt

from . import config
from .db import db_session, User, Company

_bearer = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ---------------- password ----------------
# Use bcrypt directly — passlib 1.7 + bcrypt 5.x break verify/hash on Windows.
def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return digest.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------------- JWT --------------------
def issue_token(user_id: str, company_id: str, email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=config.JWT_EXPIRE_MIN)
    payload = {
        "sub": user_id, "cid": company_id, "email": email,
        "iat": datetime.utcnow(), "exp": expire,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])


# ---------------- FastAPI dependencies ---
def _unauth(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                          headers={"WWW-Authenticate": "Bearer"})


def get_current_user(token: Optional[str] = Depends(_bearer)) -> User:
    if not token:
        raise _unauth()
    try:
        payload = decode_token(token)
        user_id = payload.get("sub"); cid = payload.get("cid")
    except JWTError:
        raise _unauth("Invalid token")
    if not user_id or not cid:
        raise _unauth("Invalid token payload")
    with db_session() as s:
        u = s.get(User, user_id)
        if not u or not u.is_active or u.company_id != cid:
            raise _unauth("User no longer valid")
        # Detach a lightweight copy so callers can use it after session closes
        s.expunge(u)
        return u


def get_current_company(user: User = Depends(get_current_user)) -> Company:
    with db_session() as s:
        c = s.get(Company, user.company_id)
        if not c:
            raise _unauth("Company missing")
        s.expunge(c)
        return c
