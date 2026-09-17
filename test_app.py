import os
import tempfile
from datetime import datetime, timedelta, timezone

import database
import app as app_module
from fastapi.testclient import TestClient


def setup_function():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database.DB_PATH = db_path
    database.reset_runtime_clock()
    app_module.ACTIVE_TOKENS.clear()
    database.init_db()


def test_member_registration_purchase_redemption_and_platinum_tier():
    client = TestClient(app_module.app)

    register = client.post("/api/auth/register", json={"username": "manager", "password": "secret123"})
    assert register.status_code == 201, register.text
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    member = client.post(
        "/api/members/register",
        json={"first_name": "Amelia", "last_name": "Stone", "phone": "+1-415-555-0147"},
        headers=headers,
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["member"]["id"]

    purchase = client.post(
        "/api/purchases",
        json={"member_id": member_id, "amount": 5000.0, "notes": "bulk loyalty purchase"},
        headers=headers,
    )
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["points_earned"] == 10000.0
    assert purchase.json()["current_tier"] == "Platinum"

    balance = client.get(f"/api/members/{member_id}/balance", headers=headers)
    assert balance.status_code == 200, balance.text
    payload = balance.json()
    assert payload["tier"] == "Platinum"
    assert payload["points_multiplier"] == 2.0
    assert payload["points_balance"] == 10000.0

    redemption = client.post(
        "/api/redemptions",
        json={"member_id": member_id, "item_name": "Premium Latte", "points": 2500},
        headers=headers,
    )
    assert redemption.status_code == 200, redemption.text
    assert redemption.json()["remaining_balance"] == 7500.0


def test_clock_expiration_and_outbox_notifications():
    client = TestClient(app_module.app)

    register = client.post("/api/auth/register", json={"username": "ops", "password": "secret123"})
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    member = client.post(
        "/api/members/register",
        json={"first_name": "Derek", "last_name": "Ng", "phone": "+1-415-555-0999"},
        headers=headers,
    )
    member_id = member.json()["member"]["id"]

    purchase = client.post(
        "/api/purchases",
        json={"member_id": member_id, "amount": 6000.0},
        headers=headers,
    )
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["current_tier"] == "Platinum"

    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=200)).replace(microsecond=0).isoformat()
    with database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO point_allocations (member_id, purchase_id, points, created_at, expires_at, redeemed_points, status) VALUES (?, ?, ?, ?, ?, 0, 'active')",
            (member_id, None, 200.0, old_timestamp, (datetime.now(timezone.utc) - timedelta(days=110)).replace(microsecond=0).isoformat()),
        )
        conn.commit()

    clock = client.post(
        "/clock",
        json={"timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat()},
        headers=headers,
    )
    assert clock.status_code == 200, clock.text
    payload = clock.json()
    assert payload["expired_allocations"] >= 1

    outbox = client.get("/outbox", headers=headers)
    assert outbox.status_code == 200, outbox.text
    outbox_items = outbox.json()["items"]
    assert any(item["tier_to"] == "Platinum" for item in outbox_items)


def test_member_listing_supports_sorting_and_pagination():
    client = TestClient(app_module.app)

    register = client.post("/api/auth/register", json={"username": "audit", "password": "secret123"})
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    for idx in range(1, 25):
        client.post(
            "/api/members/register",
            json={"first_name": f"Member{idx}", "last_name": f"Last{idx}", "phone": f"+1-415-555-00{idx:02d}"},
            headers=headers,
        )

    page = client.get(
        "/api/members",
        params={"page": 1, "page_size": 10, "sort_by": "first_name", "sort_dir": "asc"},
        headers=headers,
    )
    assert page.status_code == 200, page.text
    data = page.json()
    assert data["page"] == 1
    assert len(data["items"]) == 10
    assert data["total"] >= 24
    assert data["items"][0]["first_name"] <= data["items"][-1]["first_name"]
