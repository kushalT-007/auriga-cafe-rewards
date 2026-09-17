import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_auth
from database import TIER_MULTIPLIERS, get_db_connection, normalize_phone, sync_member_tier, utc_now
from models.rewards import fetch_member_by_id, member_payload, resolve_member_reference
from schemas.api_models import MemberRegistrationRequest

router = APIRouter(prefix="/api/members", tags=["members"])


@router.post("/register", status_code=201)
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


@router.get("/search")
def search_member_by_phone(phone: str = Query(..., min_length=7), auth: dict = Depends(require_auth)):
    try:
        normalized_phone = normalize_phone(phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid phone number.") from exc

    with get_db_connection() as conn:
        member = conn.execute("SELECT * FROM members WHERE phone = ?", (normalized_phone,)).fetchone()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {"member": member_payload(member)}


@router.get("")
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


@router.get("/{member_id}")
def get_member(member_id: int, auth: dict = Depends(require_auth)):
    member = fetch_member_by_id(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {"member": member_payload(member)}


@router.get("/{member_id}/balance")
def get_live_balance(member_id: int, auth: dict = Depends(require_auth)):
    member = fetch_member_by_id(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    current_tier = sync_member_tier(member_id)
    current_balance = member_payload(member)["points_balance"]
    return {
        "member_id": member_id,
        "first_name": member["first_name"],
        "last_name": member["last_name"],
        "phone": member["phone"],
        "tier": current_tier,
        "points_balance": round(current_balance, 2),
        "points_multiplier": TIER_MULTIPLIERS.get(current_tier, 1.0),
    }
