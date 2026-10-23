## 2026-10-21T02:04:04Z
You are the Forensic Integrity Auditor for Milestone M1 of the "Pollo Apanado" project.
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\auditor_m1_1\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Authoritative user request: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md`
Project master specification: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`
Worker report: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m1\handoff.md`

You MUST read `ORIGINAL_REQUEST.md`, `PROJECT.md`, and the worker's handoff before starting.
Your mission is to conduct a forensic code integrity audit on all changes made for Milestone M1:
1. Inspect `app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, and `tests/test_milestone_m1.py`.
2. Verify genuine implementation:
   - ZERO TOLERANCE for cheating, mock facades, hardcoded test values, fake pass returns, or bypasses.
   - Verify that `order_counters` truly writes to database and is not mocked.
   - Verify that `cancel_sale` actually executes SQL updates restoring every combo item.
   - Verify that stock deductions genuinely check `stock >= qty`.
   - Verify that `despiece` genuinely updates database inventory and writes to `butchering_logs`.
3. Run static analysis and runtime tracing to confirm that the real database tables and endpoints are exercised.
4. State your verdict clearly: CLEAN or INTEGRITY VIOLATION.
5. Write your forensic audit report to `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\auditor_m1_1\handoff.md` and send a message.
