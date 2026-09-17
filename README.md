# Auriga Cafe Rewards

Auriga Cafe Rewards is a modular FastAPI loyalty application for café operations. It combines SQLite persistence, a small staff dashboard, and rule-driven rewards logic for member registration, point accrual, tier progression, redemption handling, and notification tracking.

## Project structure

- `app.py` — application entrypoint, static mount, template configuration, router registration
- `database.py` — SQLite setup, schema creation, clock helpers, auth/session persistence, point logic
- `models/rewards.py` — reward/member-service helpers used by the API layer
- `schemas/api_models.py` — Pydantic request validation models
- `api/auth.py` — login/register and Bearer-token validation
- `api/members.py` — member routes and lookup logic
- `api/transactions.py` — purchase, redemption, clock, and outbox endpoints
- `templates/index.html` — FastAPI Jinja staff dashboard UI
- `static/` — static frontend assets directory
- `README.md` — setup and usage guide
- `REASONING.md` — architecture and design rationale
- `AI_LOGS.md` — session log
- `cafe_rewards.db` — generated SQLite database

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
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open the UI at:

```text
http://localhost:8000/
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
- Platinum: lifetime spend or lifetime points thresholds can move the member into Platinum with a 2.0x multiplier
- Point allocations are tracked with explicit timestamps and 90-day expiry windows
- Redemptions consume the oldest active allocations first
- Tier upgrades append notifications to `notifications_outbox`
- Session tokens are persisted in the SQLite `sessions` table instead of an in-memory dictionary

## Verification

Run:

```bash
cd /workspaces/auriga-cafe-rewards && pytest -q
```

This validates member registration, points, redemptions, tier upgrades, clock-driven expiry simulation, outbox notifications, and list sorting/pagination.

