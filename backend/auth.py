"""Login, tokens and the per-customer permission check.

Rules (docs/architecture/auth-and-customer-directory.md §4):
  * every /api/customers/{id}/… call checks the customer is in the user's list (admin: all);
  * the Hindsight bank id comes from MongoDB, never from the browser.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from fastapi import Depends, Header, HTTPException

from contracts import CustomerContext, UserOut
from db import database

TOKEN_HOURS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(503, {"error": "config_missing", "message": "JWT_SECRET is not set on the server"})
    return secret


def issue_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=TOKEN_HOURS)}, _secret(),
                      algorithm="HS256")


def user_out(u: dict) -> UserOut:
    return UserOut(id=str(u["_id"]), email=u["email"], name=u["name"], role=u.get("role", "sales_exec"),
                   customer_ids=u.get("customer_ids", []))


async def current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, {"error": "unauthenticated", "message": "Log in first"})
    try:
        claims = jwt.decode(authorization[7:], _secret(), algorithms=["HS256"])
        user = await database().users.find_one({"_id": ObjectId(claims["sub"]), "active": True})
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user:
        raise HTTPException(401, {"error": "unauthenticated", "message": "Session expired, log in again"})
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, {"error": "forbidden", "message": "Admins only"})
    return user


def can_see(user: dict, customer_id: str) -> bool:
    return user.get("role") == "admin" or customer_id in user.get("customer_ids", [])


async def customer_context(customer_id: str, user: dict = Depends(current_user)) -> CustomerContext:
    """Permission check + directory lookup for every customer route. The agent only ever gets this."""
    if not can_see(user, customer_id):
        raise HTTPException(403, {"error": "forbidden", "message": "This customer is not assigned to you"})
    c = await database().customers.find_one({"_id": customer_id})
    if not c:
        raise HTTPException(404, {"error": "unknown_customer", "message": f"No customer '{customer_id}'"})
    return CustomerContext(customer_id=c["_id"], bank_id=c["bank_id"], name=c["name"], industry=c["industry"],
                           exec_name=user["name"])
