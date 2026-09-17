# AI logs

This log was initialized for the Auriga Cafe Rewards rebuild.

- Date: 2026-09-17
- Project: Auriga Cafe Rewards
- Stack: FastAPI + SQLite + Tailwind dashboard
- Status: full rebuild and verification complete

Session summary:
- Rebuilt the backend, database, and UI around the requested reward rules.
- Added indexed phone lookup, point expiry simulation, and tier-outbox handling.
- Verified the implementation with pytest.

- Verified the implementation with pytest.
@agent Reset, restructure, and completely build a robust full-stack Cafe Rewards application in Python (FastAPI + SQLite + Tailwind UI) matching the updated specs and advanced level twists. 

Execute these setup and structure actions natively:
1. Run bash commands to create the directories: 'templates/', 'static/', and '.github/reference/'.
2. Place a clean, modular 'index.html' dashboard in the 'templates/' folder.
3. Completely overwrite 'app.py' and 'database.py' to handle the full app lifecycle.

Implement these strict operational mechanics and twist parameters:
1. Core Rewards & Lifetime Tier Rules:
   - Regular Tier: 1.0x points per ₹1 spent.
   - Silver Tier: 1.2x points per ₹1 spent.
   - Gold Tier: 1.5x points per ₹1 spent.
   - Twist L1 (Platinum): Lifetime points >= 5000 earns 2.0x points (0.3 points per ₹1 spent -> 30% earning rate). Upgrade members dynamically without modifying stable balances unless they qualify.
2. Lookup Optimization: Fast indexed SQLite lookups on the 'phone' column for long member directories.
3. Twist L2 (90-Day Points Expiration & /clock):
   - Track points with explicit ingestion timestamps. 
   - Implement a 'POST /clock' endpoint that simulates time moving forward. When called with a payload containing days/timestamps, expire any point allocations older than 90 days that have not been deducted by redemptions, and adjust the live balance.
4. Twist L3 (Tier Transition Notifications & /outbox):
   - When a member upgrades their tier, append a dispatch entry to a local 'notifications_outbox' database table.
   - Implement a 'GET /outbox' endpoint that reads and lists these unsent status notifications for graders to check integration.
5. Mandatory Standard Features:
   - Full REST API endpoints supporting user registration, staff login sessions, searching members, recording purchases (POST /api/purchases), and processing redemptions (POST /api/redemptions).
   - Server-side sorting and pagination on the list members view.
   - Generate root files: 'README.md' (with exact API endpoints), 'REASONING.md' (architecture choices), and an initialized 'AI_LOGS.md'.

Ensure all path lookups, template directories, and model logic are functional with zero placeholder comments. Run pytest or syntax checks to confirm health.
