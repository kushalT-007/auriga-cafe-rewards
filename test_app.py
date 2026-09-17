import os
import tempfile

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["CAFE_DB_PATH"] = db_path

from fastapi.testclient import TestClient

from app import app, init_db


def setup_function():
    init_db()


def test_member_registration_and_purchase_flow():
    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"username": "manager", "password": "secret123"},
    )
    assert register.status_code == 201, register.text

    login = client.post(
        "/api/auth/login",
        json={"username": "manager", "password": "secret123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    member = client.post(
        "/api/members/register",
        json={"first_name": "Amelia", "last_name": "Stone", "phone": "+1-415-555-0147"},
        headers=headers,
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["member"]["id"]

    search = client.get("/api/members/search", params={"phone": "+1-415-555-0147"}, headers=headers)
    assert search.status_code == 200, search.text
    assert search.json()["member"]["first_name"] == "Amelia"

    purchase = client.post(
        "/api/purchases",
        json={"member_id": member_id, "amount": 100.0},
        headers=headers,
    )
    assert purchase.status_code == 201, purchase.text
    assert purchase.json()["points_earned"] == 100.0

    balance = client.get(f"/api/members/{member_id}/balance", headers=headers)
    assert balance.status_code == 200, balance.text
    assert balance.json()["points_balance"] == 100.0

    redemption = client.post(
        "/api/redemptions",
        json={"member_id": member_id, "item_name": "Latte", "points": 50},
        headers=headers,
    )
    assert redemption.status_code == 201, redemption.text
    assert redemption.json()["remaining_balance"] == 50.0


def test_member_listing_supports_pagination_and_sorting():
    client = TestClient(app)
    register = client.post(
        "/api/auth/register",
        json={"username": "ops", "password": "secret123"},
    )
    token = register.json()["token"] if register.status_code == 201 else None
    headers = {"Authorization": f"Bearer {token}"}

    for idx in range(1, 25):
        client.post(
            "/api/members/register",
            json={"first_name": f"Member{idx}", "last_name": f"Last{idx}", "phone": f"+1-415-555-00{idx:02d}"},
            headers=headers,
        )

    members = client.get(
        "/api/members",
        params={"page": 1, "page_size": 10, "sort_by": "created_at", "sort_dir": "desc"},
        headers=headers,
    )
    assert members.status_code == 200, members.text
    payload = members.json()
    assert payload["page"] == 1
    assert len(payload["items"]) == 10
    assert payload["total"] >= 24
