from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_auth
from database import (
    TIER_MULTIPLIERS,
    compute_member_balance,
    expire_old_point_allocations,
    get_db_connection,
    get_runtime_clock,
    isoformat_utc,
    set_runtime_clock,
    sync_member_tier,
    utc_now,
)
from models.rewards import determine_member_tier, resolve_member_reference
from schemas.api_models import ClockRequest, PurchaseRequest, RedemptionRequest

router = APIRouter(tags=["transactions"])


@router.post("/api/purchases")
def record_purchase(payload: PurchaseRequest, auth: dict = Depends(require_auth)):
    member_id_value = payload.member_id if payload.member_id not in (None, "") else None
    member_row = resolve_member_reference(member_id_value, payload.phone)
    if not member_row:
        raise HTTPException(status_code=404, detail="Member not found.")

    amount = float(payload.amount)
    projected_spend = float(member_row["lifetime_spend"] or 0) + amount
    projected_points = float(member_row["lifetime_points_earned"] or 0) + amount
    current_tier = determine_member_tier(projected_points, projected_spend)
    multiplier = TIER_MULTIPLIERS.get(current_tier, 1.0)
    points_earned = round(amount * multiplier, 2)
    now_value = utc_now()
    expires_at = (get_runtime_clock() + timedelta(days=90)).replace(microsecond=0).isoformat()

    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO purchases (member_id, amount, points_earned, tier_at_purchase, purchased_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (member_row["id"], amount, points_earned, current_tier, now_value, payload.notes),
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


@router.post("/api/redemptions")
def redeem_points(payload: RedemptionRequest, auth: dict = Depends(require_auth)):
    member_id_value = payload.member_id if payload.member_id not in (None, "") else None
    member_row = resolve_member_reference(member_id_value, payload.phone)
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


@router.post("/clock")
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


@router.get("/outbox")
def read_outbox(auth: dict = Depends(require_auth)):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications_outbox WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
    items = [dict(row) for row in rows]
    return {"items": items, "count": len(items)}
