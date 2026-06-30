from datetime import datetime, timedelta, timezone
import os

import bcrypt
import jwt
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("Missing required environment variable: JWT_SECRET")
    return secret


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "id": user["id"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
        "role": user.get("role", "student"),
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid token.") from exc
