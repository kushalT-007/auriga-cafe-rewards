import os

from fastapi import APIRouter, Header, HTTPException

from database import get_db_connection, hash_password, utc_now, verify_password
from schemas.api_models import RegistrationRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def require_auth(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")

    token = authorization.split(" ", 1)[1].strip()
    with get_db_connection() as conn:
        session = conn.execute(
            "SELECT s.token, s.user_id, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()

    if not session:
        raise HTTPException(status_code=401, detail="Token expired or invalid.")

    return {"id": session["user_id"], "username": session["username"]}


@router.post("/register", status_code=201)
def register_user(payload: RegistrationRequest):
    username = payload.username.strip()
    password = payload.password.strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")

    with get_db_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already registered.")

        password_hash = hash_password(password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        user_id = cursor.lastrowid

    token = os.urandom(16).hex()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, utc_now()),
        )
        conn.commit()

    return {"id": user_id, "username": username, "token": token}


@router.post("/login")
def login_user(payload: RegistrationRequest):
    username = payload.username.strip()
    password = payload.password.strip()

    with get_db_connection() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = os.urandom(16).hex()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user["id"], utc_now()),
        )
        conn.commit()

    return {"token": token, "user": {"id": user["id"], "username": user["username"]}}
