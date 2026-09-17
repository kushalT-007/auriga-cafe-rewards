import sqlite3

from database import (
    TIER_MULTIPLIERS,
    compute_member_balance,
    determine_member_tier,
    expire_old_point_allocations,
    get_db_connection,
    member_payload,
    normalize_phone,
    sync_member_tier,
)


def fetch_member_by_id(member_id: int) -> sqlite3.Row | None:
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()


def fetch_member_by_phone(phone: str) -> sqlite3.Row | None:
    normalized_phone = normalize_phone(phone)
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM members WHERE phone = ?", (normalized_phone,)).fetchone()


def resolve_member_reference(member_id: int | str | None, phone: str | None) -> sqlite3.Row | None:
    if phone is not None:
        trimmed = str(phone).strip()
        if trimmed:
            member = fetch_member_by_phone(trimmed)
            if member is not None:
                return member

    if member_id is not None:
        if isinstance(member_id, int):
            return fetch_member_by_id(member_id)

        value = str(member_id).strip()
        if value:
            if value.isdigit():
                member = fetch_member_by_id(int(value))
                if member is not None:
                    return member
                return fetch_member_by_phone(value)
            return fetch_member_by_phone(value)

    return None
