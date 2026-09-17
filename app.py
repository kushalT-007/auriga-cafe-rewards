import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
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
    determine_member_tier,
    expire_old_point_allocations,
    get_db_connection,
    get_runtime_clock,
    hash_password,
    init_db,
    isoformat_utc,
    member_payload,
    normalize_phone,
    set_runtime_clock,
    sync_member_tier,
    utc_now,
    verify_password,
)

app = FastAPI(title="Auriga Cafe Rewards", version="1.1.0")
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory="templates")

ACTIVE_TOKENS: dict[str, dict] = {}


class UserAuthRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=6, max_length=128)


class MemberRegistrationRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=80)
    last_name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field(..., min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=120)


class PurchaseRequest(BaseModel):
    member_id: int | str | None = None
    phone: str | None = None
    amount: float = Field(..., gt=0)
    notes: str | None = None


class RedemptionRequest(BaseModel):
    member_id: int | str | None = None
    phone: str | None = None
    item_name: str = Field(..., min_length=2, max_length=120)
    points: float = Field(..., gt=0)
    notes: str | None = None


class ClockRequest(BaseModel):
    days: int | None = None
    timestamp: str | None = None


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


def fetch_member_by_id(member_id: int) -> sqlite3.Row | None:
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()


def fetch_member_by_phone(phone: str) -> sqlite3.Row | None:
    normalized_phone = normalize_phone(phone)
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM members WHERE phone = ?", (normalized_phone,)).fetchone()


def resolve_member_reference(member_id: int | str | None, phone: str | None) -> sqlite3.Row | None:
    if member_id is not None:
        if isinstance(member_id, str) and member_id.strip():
            value = member_id.strip()
            if value.isdigit():
                return fetch_member_by_id(int(value))
        elif isinstance(member_id, int):
            return fetch_member_by_id(member_id)

    if phone is not None:
        trimmed = str(phone).strip()
        if trimmed:
            return fetch_member_by_phone(trimmed)

    return None


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
def register_user(payload: UserAuthRequest):
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
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, utc_now()),
        )
        conn.commit()
    return {"id": user_id, "username": username, "token": token}


@app.post("/api/auth/login")
def login_user(payload: UserAuthRequest):
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
            "INSERT INTO members (first_name, last_name, phone, email, tier, lifetime_spend, lifetime_points_earned, created_at, updated_at) VALUES (?, ?, ?, ?, 'Regular', 0, 0, ?, ?)",
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
    try:
        normalized_phone = normalize_phone(phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid phone number.") from exc

    with get_db_connection() as conn:
        member = conn.execute("SELECT * FROM members WHERE phone = ?", (normalized_phone,)).fetchone()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {"member": member_payload(member)}


@app.get("/api/members")
def list_members(
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Literal["first_name", "last_name", "phone", "tier", "created_at", "lifetime_spend", "lifetime_points_earned"] = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    auth: dict = Depends(require_auth),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be 1 or greater.")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Page size must be between 1 and 100.")
    allowed_sort = {"first_name", "last_name", "phone", "tier", "created_at", "lifetime_spend", "lifetime_points_earned"}
    if sort_by not in allowed_sort:
        raise HTTPException(status_code=400, detail="Unsupported sort field.")

    search_term = (search or "").strip()
    query = "SELECT * FROM members"
    params: list[str] = []
    if search_term:
        query += " WHERE lower(first_name) LIKE ? OR lower(last_name) LIKE ? OR phone LIKE ?"
        term = f"%{search_term.lower()}%"
        params.extend([term, term, term])

    count_query = "SELECT COUNT(*) AS total FROM (" + query + ")"
    with get_db_connection() as conn:
        total_row = conn.execute(count_query, params).fetchone()
        total = int(total_row["total"] if total_row else 0)
        order_clause = f"ORDER BY {sort_by} {sort_dir.upper()}"
        query_sql = query + " " + order_clause + " LIMIT ? OFFSET ?"
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
    current_tier = sync_member_tier(member_id)
    current_balance = compute_member_balance(member_id)
    return {
        "member_id": member_id,
        "first_name": member["first_name"],
        "last_name": member["last_name"],
        "phone": member["phone"],
        "tier": current_tier,
        "points_balance": round(current_balance, 2),
        "points_multiplier": TIER_MULTIPLIERS.get(current_tier, 1.0),
    }


@app.post("/api/purchases")
def record_purchase(payload: PurchaseRequest, auth: dict = Depends(require_auth)):
    member_row = resolve_member_reference(payload.member_id, payload.phone)
    if not member_row:
        raise HTTPException(status_code=404, detail="Member not found.")

    amount = float(payload.amount)
    current_lifetime_spend = float(member_row["lifetime_spend"] or 0)
    current_lifetime_points = float(member_row["lifetime_points_earned"] or 0)
    projected_spend = current_lifetime_spend + amount
    projected_points = current_lifetime_points + amount
    current_tier = determine_member_tier(projected_points, projected_spend)
    multiplier = TIER_MULTIPLIERS.get(current_tier, 1.0)
    points_earned = round(amount * multiplier, 2)
    now_value = utc_now()
    expires_at = (get_runtime_clock() + timedelta(days=90)).replace(microsecond=0).isoformat()

    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO purchases (member_id, amount, points_earned, tier_at_purchase, purchased_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (
                member_row["id"],
                amount,
                points_earned,
                current_tier,
                now_value,
                payload.notes,
            ),
        )
        purchase_id = cursor.lastrowid
        conn.execute(
            "UPDATE members SET lifetime_spend = lifetime_spend + ?, lifetime_points_earned = lifetime_points_earned + ?, updated_at = ? WHERE id = ?",
            (amount, points_earned, now_value, member_row["id"]),
        )
        conn.execute(
            "INSERT INTO point_allocations (member_id, purchase_id, points, created_at, expires_at, redeemed_points, status) VALUES (?, ?, ?, ?, ?, 0, 'active')",
            (member_row["id"], purchase_id, points_earned, now_value, expires_at),
        )
        conn.commit()

    final_tier = sync_member_tier(member_row["id"])
    return {
        "status": "success",
        "message": "Purchase recorded successfully.",
        "member_id": member_row["id"],
        "member_name": f"{member_row['first_name']} {member_row['last_name']}",
        "tier_at_purchase": current_tier,
        "amount": amount,
        "points_earned": points_earned,
        "current_tier": final_tier,
    }


@app.post("/api/redemptions")
def redeem_points(payload: RedemptionRequest, auth: dict = Depends(require_auth)):
    member_row = resolve_member_reference(payload.member_id, payload.phone)
    if not member_row:
        raise HTTPException(status_code=404, detail="Member not found.")

    points_to_redeem = float(payload.points)
    member_id = member_row["id"]
    current_balance = compute_member_balance(member_id)
    if points_to_redeem > current_balance:
        raise HTTPException(status_code=400, detail="Insufficient points balance.")

    item_name = payload.item_name.strip()
    with get_db_connection() as conn:
        allocations = conn.execute(
            "SELECT id, points, redeemed_points FROM point_allocations WHERE member_id = ? AND status = 'active' ORDER BY created_at ASC",
            (member_id,),
        ).fetchall()
        remaining_to_redeem = points_to_redeem
        for allocation in allocations:
            if remaining_to_redeem <= 0:
                break
            available = float(allocation["points"]) - float(allocation["redeemed_points"])
            if available <= 0:
                continue
            consumed = min(available, remaining_to_redeem)
            remaining_to_redeem -= consumed
            conn.execute(
                "UPDATE point_allocations SET redeemed_points = redeemed_points + ? WHERE id = ?",
                (consumed, allocation["id"]),
            )
        conn.execute(
            "INSERT INTO redemptions (member_id, item_name, points_redeemed, redeemed_at, notes) VALUES (?, ?, ?, ?, ?)",
            (member_id, item_name, points_to_redeem, utc_now(), payload.notes),
        )
        conn.commit()

    remaining = compute_member_balance(member_id)
    sync_member_tier(member_id)
    return {
        "status": "success",
        "message": "Redemption recorded successfully.",
        "member_id": member_id,
        "item_name": item_name,
        "points_redeemed": points_to_redeem,
        "remaining_balance": round(remaining, 2),
    }


@app.post("/clock")
def advance_clock(payload: ClockRequest, auth: dict = Depends(require_auth)):
    try:
        if payload.timestamp:
            target_time = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
        elif payload.days is not None:
            target_time = get_runtime_clock() + timedelta(days=int(payload.days))
        else:
            target_time = get_runtime_clock()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid timestamp format.") from exc

    set_runtime_clock(target_time)
    expired_count = expire_old_point_allocations(target_time)
    with get_db_connection() as conn:
        member_ids = [row["id"] for row in conn.execute("SELECT id FROM members").fetchall()]
    for member_id in member_ids:
        sync_member_tier(member_id)

    return {
        "status": "success",
        "current_time": isoformat_utc(target_time),
        "expired_allocations": expired_count,
    }


@app.get("/outbox")
def read_outbox(auth: dict = Depends(require_auth)):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications_outbox WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
    items = [dict(row) for row in rows]
    return {"items": items, "count": len(items)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8001)
