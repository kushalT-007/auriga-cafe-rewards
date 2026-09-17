import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("CAFE_DB_PATH", str(BASE_DIR / "cafe_rewards.db"))
POINTS_EXPIRY_DAYS = 90
TIER_MULTIPLIERS = {
    "Regular": 1.0,
    "Silver": 1.2,
    "Gold": 1.5,
    "Platinum": 2.0,
}

_RUNTIME_CLOCK = {"current": datetime.now(timezone.utc).replace(microsecond=0)}


def reset_runtime_clock(now: datetime | None = None) -> None:
    if now is None:
        _RUNTIME_CLOCK["current"] = datetime.now(timezone.utc).replace(microsecond=0)
        return
    _RUNTIME_CLOCK["current"] = now.astimezone(timezone.utc).replace(microsecond=0)


def get_runtime_clock() -> datetime:
    return _RUNTIME_CLOCK["current"]


def set_runtime_clock(now: datetime) -> None:
    reset_runtime_clock(now)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def utc_now() -> str:
    return isoformat_utc(get_runtime_clock())


def normalize_phone(phone: str | None) -> str:
    if phone is None:
        raise ValueError("Phone number is required.")
    cleaned = re.sub(r"[^0-9+]", "", str(phone).strip())
    if not cleaned or cleaned == "+":
        raise ValueError("Phone number is required.")
    if cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned[1:])
        return f"+{digits}"
    digits = re.sub(r"\D", "", cleaned)
    return digits


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + derived.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, derived_hex = stored_hash.split(":", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return secrets.compare_digest(derived.hex(), derived_hex)


def get_db_connection() -> sqlite3.Connection:
    db_target = DB_PATH
    if db_target == ":memory:":
        db_target = str(BASE_DIR / ".cafe_rewards_test.db")
    connection = sqlite3.connect(db_target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def determine_member_tier(lifetime_points_earned: float, lifetime_spend: float) -> str:
    if lifetime_points_earned >= 5000 or lifetime_spend >= 5000:
        return "Platinum"
    if lifetime_spend >= 1500 or lifetime_points_earned >= 2500:
        return "Gold"
    if lifetime_spend >= 500 or lifetime_points_earned >= 1000:
        return "Silver"
    return "Regular"


def sync_member_tier(member_id: int) -> str:
    with get_db_connection() as conn:
        member = conn.execute(
            "SELECT tier, lifetime_spend, lifetime_points_earned FROM members WHERE id = ?",
            (member_id,),
        ).fetchone()
        if member is None:
            return "Regular"

        new_tier = determine_member_tier(
            float(member["lifetime_points_earned"] or 0),
            float(member["lifetime_spend"] or 0),
        )
        if member["tier"] != new_tier:
            now_value = utc_now()
            conn.execute(
                "UPDATE members SET tier = ?, updated_at = ? WHERE id = ?",
                (new_tier, now_value, member_id),
            )
            conn.execute(
                "INSERT INTO notifications_outbox (member_id, title, body, status, tier_from, tier_to, created_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (
                    member_id,
                    f"Tier upgraded to {new_tier}",
                    f"Member moved from {member['tier']} to {new_tier}.",
                    member["tier"] or "Regular",
                    new_tier,
                    now_value,
                ),
            )
            conn.commit()
        return new_tier


def expire_old_point_allocations(reference_time: datetime | None = None) -> int:
    current_time = reference_time or get_runtime_clock()
    cutoff = current_time - timedelta(days=POINTS_EXPIRY_DAYS)
    cutoff_iso = isoformat_utc(cutoff)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, points, redeemed_points FROM point_allocations WHERE status = 'active' AND created_at <= ?",
            (cutoff_iso,),
        ).fetchall()
        expired_count = 0
        for row in rows:
            if float(row["redeemed_points"] or 0) < float(row["points"] or 0):
                conn.execute(
                    "UPDATE point_allocations SET status = 'expired', expired_at = ? WHERE id = ?",
                    (isoformat_utc(current_time), row["id"]),
                )
                expired_count += 1
        conn.commit()
    return expired_count


def compute_member_balance(member_id: int) -> float:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN status = 'active' THEN points - redeemed_points ELSE 0 END), 0) AS total_active FROM point_allocations WHERE member_id = ?",
            (member_id,),
        ).fetchone()
    balance = float(row["total_active"] or 0)
    return round(balance, 2)


def member_payload(member_row: sqlite3.Row) -> dict:
    member_id = member_row["id"]
    tier = sync_member_tier(member_id)
    balance = compute_member_balance(member_id)
    lifetime_spend = float(member_row["lifetime_spend"] or 0)
    lifetime_points = float(member_row["lifetime_points_earned"] or 0)
    return {
        "id": member_id,
        "first_name": member_row["first_name"],
        "last_name": member_row["last_name"],
        "phone": member_row["phone"],
        "email": member_row["email"],
        "tier": tier,
        "lifetime_spend": round(lifetime_spend, 2),
        "lifetime_points_earned": round(lifetime_points, 2),
        "points_balance": round(balance, 2),
        "points_multiplier": TIER_MULTIPLIERS.get(tier, 1.0),
        "created_at": member_row["created_at"],
        "updated_at": member_row["updated_at"],
    }


def init_db() -> None:
    connection = get_db_connection()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            email TEXT,
            tier TEXT NOT NULL DEFAULT 'Regular',
            lifetime_spend REAL NOT NULL DEFAULT 0,
            lifetime_points_earned REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone);
        CREATE INDEX IF NOT EXISTS idx_members_tier ON members(tier);

        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL CHECK(amount >= 0),
            points_earned REAL NOT NULL DEFAULT 0,
            tier_at_purchase TEXT NOT NULL,
            purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_purchases_member_id ON purchases(member_id);
        CREATE INDEX IF NOT EXISTS idx_purchases_purchased_at ON purchases(purchased_at);

        CREATE TABLE IF NOT EXISTS point_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            purchase_id INTEGER,
            points REAL NOT NULL CHECK(points >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            redeemed_points REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            expired_at TEXT,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE,
            FOREIGN KEY(purchase_id) REFERENCES purchases(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_point_allocations_member_id ON point_allocations(member_id);
        CREATE INDEX IF NOT EXISTS idx_point_allocations_status ON point_allocations(status);
        CREATE INDEX IF NOT EXISTS idx_point_allocations_expires_at ON point_allocations(expires_at);

        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            points_redeemed REAL NOT NULL CHECK(points_redeemed > 0),
            redeemed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_redemptions_member_id ON redemptions(member_id);
        CREATE INDEX IF NOT EXISTS idx_redemptions_redeemed_at ON redemptions(redeemed_at);

        CREATE TABLE IF NOT EXISTS notifications_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            tier_from TEXT,
            tier_to TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_notifications_member_id ON notifications_outbox(member_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications_outbox(status);
        """
    )
    connection.commit()

    admin_username = "admin"
    admin_password = "admin123"
    admin_row = connection.execute(
        "SELECT id FROM users WHERE username = ?",
        (admin_username,),
    ).fetchone()
    if admin_row is None:
        admin_hash = hash_password(admin_password)
        connection.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (admin_username, admin_hash),
        )
        connection.commit()
    connection.close()
