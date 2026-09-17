import math
import os
import sqlite3
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from database import (
    DB_PATH,
    TIER_MULTIPLIERS,
    compute_member_balance,
    get_db_connection,
    hash_password,
    init_db,
    member_payload,
    normalize_phone,
    update_member_tier,
    utc_now,
    verify_password,
)

app = FastAPI(title="Auriga Cafe Rewards", version="1.0.0")
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory="templates")

ACTIVE_TOKENS: dict[str, dict] = {}


def require_auth(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token = authorization.split(" ", 1)[1].strip()
    if token not in ACTIVE_TOKENS:
        raise HTTPException(status_code=401, detail="Token expired or invalid.")
    return ACTIVE_TOKENS[token]


def fetch_member_by_id(member_id: int) -> sqlite3.Row | None:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM members WHERE id = ?",
            (member_id,),
        ).fetchone()


def fetch_member_by_phone(phone: str) -> sqlite3.Row | None:
    normalized_phone = normalize_phone(phone)
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM members WHERE phone = ?",
            (normalized_phone,),
        ).fetchone()


class RegistrationRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=6, max_length=128)


class MemberRegistrationRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=80)
    last_name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field(..., min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=120)


class PurchaseRequest(BaseModel):
    member_id: int | None = None
    phone: str | None = None
    amount: float = Field(..., gt=0)
    notes: str | None = None


class RedemptionRequest(BaseModel):
    member_id: int | None = None
    phone: str | None = None
    item_name: str = Field(..., min_length=2, max_length=120)
    points: float = Field(..., gt=0)
    notes: str | None = None


class MemberListResponse(BaseModel):
    items: list[dict]
    page: int
    page_size: int
    total: int
    pages: int


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "database": DB_PATH}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/auth/register", status_code=201)
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
        conn.commit()
        user_id = cursor.lastrowid
    token = os.urandom(16).hex()
    ACTIVE_TOKENS[token] = {"id": user_id, "username": username}
    return {"id": user_id, "username": username, "token": token}


@app.post("/api/auth/login")
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
    ACTIVE_TOKENS[token] = {"id": user["id"], "username": user["username"]}
    return {"token": token, "user": {"id": user["id"], "username": user["username"]}}


@app.post("/api/members/register", status_code=201)
def register_member(payload: MemberRegistrationRequest, auth: dict = Depends(require_auth)):
    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()
    email = payload.email.strip() if payload.email else None
    phone = normalize_phone(payload.phone)
    if not first_name or not last_name:
        raise HTTPException(status_code=400, detail="First and last name are required.")

    with get_db_connection() as conn:
        existing = conn.execute("SELECT id FROM members WHERE phone = ?", (phone,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Member already exists for this phone number.")
        cursor = conn.execute(
            "INSERT INTO members (first_name, last_name, phone, email, tier, created_at, updated_at) VALUES (?, ?, ?, ?, 'Regular', ?, ?)",
            (first_name, last_name, phone, email, utc_now(), utc_now()),
        )
        member_id = cursor.lastrowid
        conn.commit()
        member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    return {"message": "Member registered successfully.", "member": member_payload(member)}


@app.get("/api/members/search")
def search_member_by_phone(
    phone: str = Query(..., min_length=7),
    auth: dict = Depends(require_auth),
):
    with get_db_connection() as conn:
        member = conn.execute("SELECT * FROM members WHERE phone = ?", (normalize_phone(phone),)).fetchone()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {"member": member_payload(member)}


@app.get("/api/members")
def list_members(
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Literal["first_name", "last_name", "phone", "tier", "created_at"] = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    auth: dict = Depends(require_auth),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be 1 or greater.")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Page size must be between 1 and 100.")

    search_term = (search or "").strip()
    query = "SELECT * FROM members"
    params: list[str] = []
    if search_term:
        query += " WHERE lower(first_name) LIKE ? OR lower(last_name) LIKE ? OR phone LIKE ?"
        term = f"%{search_term.lower()}%"
        params.extend([term, term, term])
    order = "ORDER BY " + sort_by + " " + sort_dir.upper()
    count_query = "SELECT COUNT(*) AS total FROM (" + query + ")"
    with get_db_connection() as conn:
        total_row = conn.execute(count_query, params).fetchone()
        total = int(total_row["total"] if total_row else 0)
        query_sql = query + " " + order + " LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(query_sql, params).fetchall()

    items = [member_payload(row) for row in rows]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@app.get("/api/members/{member_id}")
def get_member(member_id: int, auth: dict = Depends(require_auth)):
    member = fetch_member_by_id(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {"member": member_payload(member)}


@app.get("/api/members/{member_id}/balance")
def get_live_balance(member_id: int, auth: dict = Depends(require_auth)):
    member = fetch_member_by_id(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    current_balance = compute_member_balance(member_id)
    current_tier = update_member_tier(member_id)
    return {
        "member_id": member_id,
        "first_name": member["first_name"],
        "last_name": member["last_name"],
        "phone": member["phone"],
        "tier": current_tier,
        "points_balance": round(current_balance, 2),
        "points_multiplier": TIER_MULTIPLIERS.get(current_tier, 1.0),
    }


@app.post("/api/purchases", status_code=201)
def record_purchase(payload: PurchaseRequest, auth: dict = Depends(require_auth)):
    member_row = None
    if payload.member_id is not None:
        member_row = fetch_member_by_id(payload.member_id)
    elif payload.phone:
        member_row = fetch_member_by_phone(payload.phone)
    if not member_row:
        raise HTTPException(status_code=404, detail="Member not found.")

    points_earned = round(float(payload.amount) * TIER_MULTIPLIERS.get(member_row["tier"], 1.0), 2)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO purchases (member_id, amount, points_earned, tier_at_purchase, purchased_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (
                member_row["id"],
                float(payload.amount),
                points_earned,
                member_row["tier"],
                utc_now(),
                payload.notes,
            ),
        )
        conn.commit()
    current_tier = update_member_tier(member_row["id"])
    return {
        "message": "Purchase recorded successfully.",
        "member_id": member_row["id"],
        "member_name": f"{member_row['first_name']} {member_row['last_name']}",
        "tier_at_purchase": member_row["tier"],
        "amount": float(payload.amount),
        "points_earned": points_earned,
        "current_tier": current_tier,
    }


@app.post("/api/redemptions", status_code=201)
def redeem_points(payload: RedemptionRequest, auth: dict = Depends(require_auth)):
    member_row = None
    if payload.member_id is not None:
        member_row = fetch_member_by_id(payload.member_id)
    elif payload.phone:
        member_row = fetch_member_by_phone(payload.phone)
    if not member_row:
        raise HTTPException(status_code=404, detail="Member not found.")

    current_balance = compute_member_balance(member_row["id"])
    if float(payload.points) > current_balance:
        raise HTTPException(status_code=400, detail="Insufficient points balance.")

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO redemptions (member_id, item_name, points_redeemed, redeemed_at, notes) VALUES (?, ?, ?, ?, ?)",
            (
                member_row["id"],
                payload.item_name.strip(),
                float(payload.points),
                utc_now(),
                payload.notes,
            ),
        )
        conn.commit()
    remaining = compute_member_balance(member_row["id"])
    return {
        "message": "Redemption recorded successfully.",
        "member_id": member_row["id"],
        "item_name": payload.item_name.strip(),
        "points_redeemed": float(payload.points),
        "remaining_balance": round(remaining, 2),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
