# Reasoning and Architecture

## Architecture decisions

This project follows a clean full-stack pattern with a lightweight backend, a SQLite data layer, and a Jinja-rendered frontend using Tailwind CSS through the CDN. The separation keeps the application easy to reason about while still being compact enough for a single-developer café rewards system.

- Backend: Python service with a REST-style interface and request validation
- Database: SQLite for transactional storage of users, members, purchases, and redemptions
- Frontend: HTML templates and JavaScript, styled with Tailwind CDN for a polished dashboard UI
- Layout: separate `templates/` and `static/` directories to match a professional app structure

## Scaling strategy

For a long member list, the most important optimization is a database index on the member phone column. The table uses a dedicated index on `members.phone`, which means lookups by phone number do not require scanning the entire table. In practical terms, this reduces the query from a full-table pass to an indexed lookup pattern, which is near-constant time for typical customer datasets and dramatically faster than a linear scan as membership grows.

Additional scaling controls include:

- pagination on the members listing endpoint
- sorting by fields such as `created_at`, `first_name`, and `tier`
- filtered queries for search values and a capped page size
- transactional writes for purchases and redemptions so balance calculations remain consistent

## Tier algorithm

The business rule uses tier-based multipliers for points accrual:

- Regular: 1.0x per $1 spent
- Silver: 1.2x per $1 spent
- Gold: 1.5x per $1 spent

Each purchase is stored with the tier in effect at purchase time, and the member's live tier is recalculated from aggregate lifetime spend. This ensures future purchases reflect the correct reward rate based on the member's current status.

## System verification checklist

The project was verified using a real API workflow rather than mock-only behavior. The checklist below reflects the actual validation we performed:

- user creation and login
- member registration by phone number
- member lookup and live balance retrieval
- purchase recording and points accrual
- Silver and Gold tier upgrades based on cumulative spend thresholds
- redemption with remaining balance validation
- edge-case checks for invalid tokens, missing members, and insufficient points
- pagination and sorting on the member directory

The verification command used was:

```bash
pytest -q
```

This passed successfully after the full workflow was implemented and validated.
