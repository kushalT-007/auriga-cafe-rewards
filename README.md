# Auriga Cafe Rewards

Auriga Cafe Rewards is a full-stack loyalty application for café operations. It combines FastAPI, SQLite, and a Tailwind-based dashboard to manage staff authentication, member records, purchases, point balances, 90-day expiry, and tier notifications.

## Project structure

- `app.py` — FastAPI application and route configuration
- `database.py` — SQLite schema, business rules, point allocation, and tier logic
- `templates/index.html` — full staff dashboard UI
- `static/` — static assets and mount target
- `.github/reference/` — reference/spec directory
- `README.md` — project setup and API guide
- `REASONING.md` — architecture and design rationale
- `AI_LOGS.md` — session log initializer
- `cafe_rewards.db` — SQLite database generated at runtime

## Setup

```bash
cd /workspaces/auriga-cafe-rewards
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run the application

```bash
cd /workspaces/auriga-cafe-rewards
source .venv/bin/activate
python app.py
```

Open the UI at:

```text
http://localhost:8001/
```

## Default staff credentials

- Username: `admin`
- Password: `admin123`

## API endpoints

### Auth

- `POST /api/auth/register`
  - Body: `{ "username": "manager", "password": "secret123" }`
- `POST /api/auth/login`
  - Body: `{ "username": "manager", "password": "secret123" }`

### Members

- `POST /api/members/register`
  - Requires `Authorization: Bearer <token>`
  - Body: `{ "first_name": "Amelia", "last_name": "Stone", "phone": "+1-415-555-0147", "email": "amelia@example.com" }`
- `GET /api/members/search?phone=+1-415-555-0147`
- `GET /api/members`
  - Query params: `search`, `page`, `page_size`, `sort_by`, `sort_dir`
- `GET /api/members/{member_id}`
- `GET /api/members/{member_id}/balance`

### Transactions

- `POST /api/purchases`
  - Requires auth
  - Body: `{ "member_id": 1, "amount": 42.5, "notes": "Mocha and pastry" }`
  - Accepts either `member_id` or `phone`
- `POST /api/redemptions`
  - Requires auth
  - Body: `{ "member_id": 1, "item_name": "Latte", "points": 50, "notes": "Free drink" }`

### Time and notifications

- `POST /clock`
  - Requires auth
  - Body example: `{ "days": 90 }` or `{ "timestamp": "2026-09-17T12:00:00+00:00" }`
- `GET /outbox`
  - Requires auth
  - Lists pending tier/notification dispatch records

### Utility routes

- `GET /`
- `GET /health`

## Business rules

- Regular: 1.0x points per ₹1 spent
- Silver: 1.2x points per ₹1 spent
- Gold: 1.5x points per ₹1 spent
- Platinum: lifetime points >= 5000 triggers 2.0x points (0.3 points per ₹1 spent)
- Point allocations expire after 90 days unless the points were redeemed first
- Tier upgrades append notifications to `notifications_outbox`

## Verification

Run:

```bash
cd /workspaces/auriga-cafe-rewards && pytest -q
```

This validates member registration, point accrual, redemptions, tier upgrades, expiry simulation, and list pagination/sorting behavior.

