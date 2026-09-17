# Reasoning and architecture

## Design principles

The system follows a simple production-oriented full-stack pattern with clear boundaries:

- A FastAPI app provides the API layer and serves the staff dashboard.
- SQLite stores users, sessions, members, purchases, redemptions, allocations, and notifications.
- A modular package structure separates routes, schemas, and rewards logic for easier maintenance.
- A Tailwind-based HTML dashboard keeps the user experience fast and focused without a separate frontend framework.

This keeps the codebase readable, testable, and easy to stand up in a single workspace while still behaving like a real café loyalty backend.

## Why the project is structured this way

The refactor separated concerns into explicit domains:

- `api/` contains route-level concerns for auth, members, and transactions
- `schemas/` defines all request payload contracts
- `models/` owns the shared member and reward calculations
- `database.py` owns connectivity, schema setup, and runtime state

This reduces route sprawl and makes it easier to reason about how a form submission flows from the browser to the database and back into the UI.

## SQLite and session persistence

The application relies heavily on member phone lookups, which are indexed and resolved directly against the `members.phone` column. This keeps lookups fast even as the table grows.

Sessions are stored in a dedicated `sessions` table with a `token` primary key and `user_id`. This is more robust than the earlier in-memory dictionary because the auth token remains valid across server restarts as long as the SQLite database remains intact.

## Reward and tier model

The rewards system is driven by member lifetime metrics and current tier state. Purchases update the member’s lifetime spend and earned points, and the system recalculates the tier using those values.

The current tier logic is:

- Regular: 1.0x multiplier
- Silver: 1.2x multiplier
- Gold: 1.5x multiplier
- Platinum: 2.0x multiplier when thresholds are met

This means the code supports dynamic tier upgrades without rewriting prior transaction history. It preserves historical records while making new purchases respond to the member’s current status.

## 90-day expiration behavior

The app tracks each point allocation with an explicit creation timestamp and expiry timestamp. A simulated runtime clock is advanced via `POST /clock`, and any allocation older than the configured 90-day policy is expired and removed from the active balance.

Redemptions consume the oldest active allocations first, so the live balance reflects real-world FIFO redemption behavior.

## Outbox notifications

Tier transitions and operational status changes are emitted into `notifications_outbox`. The API reads these records from `GET /outbox`, making them available to the dashboard and any downstream notification processor.

This keeps the tier-change workflow observable and separates the state change from the user interface rendering.

## Verification approach

The implementation is verified with a FastAPI `TestClient` against a temporary SQLite database. The regression suite checks:

- staff auth and login
- member registration and phone lookup
- rewards accrual and upgrade behavior
- point redemption and balance correctness
- 90-day expiry simulation with the runtime clock
- notification generation in the outbox
- pagination and sort ordering in the member directory

The project uses:

```bash
pytest -q
```

as the main verification command.
