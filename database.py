import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("CAFE_DB_PATH", str(BASE_DIR / "cafe_rewards.db"))
TIER_MULTIPLIERS = {
    "Regular": 1.0,
    "Silver": 1.2,
    "Gold": 1.5,
}


def normalize_phone(phone: str) -> str:
    if not phone:
        raise ValueError("Phone number is required.")
    cleaned = re.sub(r"[^0-9+]", "", phone.strip())
    if not cleaned:
        raise ValueError("Phone number is required.")
    return cleaned


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def determine_member_tier(total_spend: float) -> str:
    if total_spend >= 1500:
        return "Gold"
    if total_spend >= 500:
        return "Silver"
    return "Regular"


def compute_member_balance(member_id: int) -> float:
    with get_db_connection() as conn:
        points_earned = conn.execute(
            "SELECT COALESCE(SUM(points_earned), 0) AS total_earned FROM purchases WHERE member_id = ?",
            (member_id,),
        ).fetchone()
        points_redeemed = conn.execute(
            "SELECT COALESCE(SUM(points_redeemed), 0) AS total_redeemed FROM redemptions WHERE member_id = ?",
            (member_id,),
        ).fetchone()
    earned = float(points_earned["total_earned"] or 0)
    redeemed = float(points_redeemed["total_redeemed"] or 0)
    return round(earned - redeemed, 2)


def update_member_tier(member_id: int) -> str:
    with get_db_connection() as conn:
        lifetime_spend = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spend FROM purchases WHERE member_id = ?",
            (member_id,),
        ).fetchone()["total_spend"]
        tier = determine_member_tier(float(lifetime_spend or 0))
        conn.execute("UPDATE members SET tier = ?, updated_at = ? WHERE id = ?", (tier, utc_now(), member_id))
        conn.commit()
    return tier


def member_payload(member_row: sqlite3.Row) -> dict:
    member_id = member_row["id"]
    lifetime_spend = 0.0
    with get_db_connection() as conn:
        lifetime_spend_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spend FROM purchases WHERE member_id = ?",
            (member_id,),
        ).fetchone()
        lifetime_spend = float(lifetime_spend_row["total_spend"] or 0)
    tier = update_member_tier(member_id)
    balance = compute_member_balance(member_id)
    return {
        "id": member_id,
        "first_name": member_row["first_name"],
        "last_name": member_row["last_name"],
        "phone": member_row["phone"],
        "email": member_row["email"],
        "tier": tier,
        "lifetime_spend": round(lifetime_spend, 2),
        "points_balance": round(balance, 2),
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

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            email TEXT,
            tier TEXT NOT NULL DEFAULT 'Regular',
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
