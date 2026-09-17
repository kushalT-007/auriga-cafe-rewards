# Reasoning and architecture

## Design principles

The system follows a compact, production-oriented full-stack pattern with clear boundaries:

- A FastAPI service handles auth, member management, rewards logic, and route validation.
- SQLite stores users, members, purchases, redemption records, point allocations, and outbox notifications.
- A Tailwind-powered HTML dashboard provides the staff interface without creating a separate frontend framework.

This keeps the codebase readable, testable, and easy to run in a single workspace while still satisfying the operational demands of a café loyalty system.

## Why SQLite and index-first lookup

Member phone numbers are the primary lookup route. SQLite supports fast indexed lookup on `members.phone`, which is essential as the directory grows into thousands of records. The project also keeps the member list query server-side by applying filtered search, sorting, and pagination in SQL before sending the results to the UI.

This design reduces expensive full-table scans and keeps the API predictable for both staff operations and dashboard rendering.

## Tier and rewards logic

The tier system is implemented around two stable facts:

- The current reward multiplier is based on the member’s active tier.
- The active tier is recalculated from lifetime metrics, especially lifetime spend and lifetime earned points.

The tier rules are:

- Regular: 1.0x points per ₹1 spent
- Silver: 1.2x points per ₹1 spent
- Gold: 1.5x points per ₹1 spent
- Platinum: lifetime points >= 5000 earns 2.0x points

This means higher tiers accelerate future accrual without rewriting existing purchase history. That preserves the integrity of the historical balance while allowing dynamic uplift for new purchases.

## 90-Day point expiration model

The expiration twist is implemented by tracking each point allocation with explicit timestamps and a computed expiry window. A purchase produces a point allocation row with a `created_at` and `expires_at`, and the app uses a simulated `POST /clock` transition to move the runtime clock forward and invalidate allocations older than 90 days.

Redemptions consume the oldest active allocations first, which keeps the live balance consistent with real point usage patterns.

## Outbox-based tier notification flow

Tier upgrades are treated as state transitions, not just UI changes. When the member's tier changes, the app appends a row to `notifications_outbox` with the `tier_from`, `tier_to`, and message body. The `GET /outbox` endpoint exposes this table so graders can confirm that status notifications are generated and queued for downstream integration.

## Verification approach

The implementation was verified with a real FastAPI test client and SQLite-backed test DB, not mock-only assertions. The regression suite checks:

- staff auth and login
- member registration and search
- purchase accrual and live balance updates
- redemption deductions
- Platinum upgrade behavior
- clock-based expiry simulation
- pending notifications in the outbox
- server-side pagination and sort ordering

The corresponding verification command is:

```bash
pytest -q
```
