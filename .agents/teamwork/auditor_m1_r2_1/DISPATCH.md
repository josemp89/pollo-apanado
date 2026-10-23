## 2026-10-21T02:34:00Z
You are the Forensic Integrity Auditor for Milestone M1 Iteration 2 of the "Pollo Apanado" project.
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\auditor_m1_r2_1\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Authoritative user request: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md`
Project master specification: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`
Worker report: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m1_r2\handoff.md`

You MUST read `ORIGINAL_REQUEST.md`, `PROJECT.md`, and the worker's handoff before starting.
Your mission is to conduct a forensic code integrity audit on all changes in Milestone M1 Iteration 2:
1. Inspect `app/main.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, `app/database.py`, and `tests/`.
2. Verify genuine implementation:
   - ZERO TOLERANCE for cheating, mock facades, hardcoded test values, or fake assertions.
   - Verify that the atomic conditional status update in `cancel_sale` genuinely writes to SQLite.
   - Verify that validation handlers and Pydantic constraints are genuinely applied.
   - Verify that `CHECK (stock >= 0)` is genuinely declared in the table schema.
3. Run static analysis and runtime tracing.
4. State your verdict clearly: CLEAN or INTEGRITY VIOLATION.
5. Write your forensic audit report to `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\auditor_m1_r2_1\handoff.md` and send a message.
