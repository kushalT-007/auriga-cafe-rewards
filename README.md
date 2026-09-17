# Auriga Cafe Rewards

Auriga Cafe Rewards is a full-stack café loyalty programme built for member signup, purchase tracking, point redemption, and staff operations. The project adopts a clean Python web architecture with a SQLite data layer and a Tailwind-powered frontend interface.

## Project structure

- `app.py` — application entry point and routing logic
- `database.py` — SQLite setup and rewards logic
- `templates/` — HTML views for the landing page and dashboard
- `static/` — static assets and frontend styling support
- `cafe_rewards.db` — generated SQLite database file

## Installation and setup

Create and activate a Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the required packages:

```bash
pip install flask
pip install -r requirements.txt
```

Run the app in debug mode:

```bash
export FLASK_APP=app.py
export FLASK_DEBUG=1
flask run --debug
```

Or run directly with Python:

```bash
python app.py
```

Open the app in a browser:

```text
http://localhost:8000/
```

## Default staff credentials

- Username: admin
- Password: admin123

## Active REST API endpoints

### Authentication

- POST /api/auth/register
  - Body: {"username": "manager", "password": "secret123"}
- POST /api/auth/login
  - Body: {"username": "manager", "password": "secret123"}

### Member management

- POST /api/members/register
  - Body: {"first_name": "Amelia", "last_name": "Stone", "phone": "+1-415-555-0147", "email": "amelia@example.com"}
- GET /api/members/search?phone=+1-415-555-0147
- GET /api/members/{member_id}
- GET /api/members/{member_id}/balance

### Listing, sorting, and pagination

- GET /api/members?page=1&page_size=20
- GET /api/members?page=1&page_size=20&search=amelia&sort_by=created_at&sort_dir=desc
- GET /api/members?page=2&page_size=10&sort_by=first_name&sort_dir=asc

### Purchases and redemptions

- POST /api/purchases
  - Body: {"member_id": 1, "amount": 42.50, "notes": "Mocha and pastry"}
- POST /api/redemptions
  - Body: {"member_id": 1, "item_name": "Latte", "points": 50, "notes": "Free drink"}

### Site routes

- GET /
- GET /health

## Debugging notes

Use Flask debug mode while developing to reload the application automatically after source changes. If you encounter a runtime issue, check the terminal output for database initialization errors, missing template paths, or invalid route definitions.

## Verification

Run all checks with:

```bash
pytest -q
```

The verification suite covers user creation, custom member registration, phone-based lookups, tier multipliers, purchase accrual, redemptions, pagination, sorting, and common edge cases.

