## 2026-10-21T01:52:52Z
You are the Worker agent for Milestone M1 of the "Pollo Apanado" project.
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m1\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Authoritative user request file: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md`
Project master specification: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`

You MUST read `ORIGINAL_REQUEST.md` and `PROJECT.md` before starting work. Also read the survey findings at:
- `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_survey_1\handoff.md`
- `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_survey_2\handoff.md`

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your write ownership covers:
- `app/database.py`
- `app/routers/pos.py` (specifically atomic `sale_code`, non-negative stock floor, and symmetrical `cancel_sale`)
- `app/routers/kitchen.py` (specifically atomic `batch_code` and despiece validation)

Scope of Milestone M1:
1. Concurrency Safety & Collision-Free Order/Batch IDs:
   - Fix `sale_code` generation in `app/routers/pos.py` and `batch_code` generation in `app/routers/kitchen.py`.
   - Must NOT use non-atomic `SELECT COUNT(*)`. Implement a collision-free mechanism (e.g., SQLite autoincrement sequence, or microsecond monotonic timestamp with UUID/random suffix, or atomic counter table) so that concurrent requests NEVER collide with `UNIQUE constraint failed`.
2. SQLite WAL & Connection Configuration (`app/database.py`):
   - Configure WAL mode properly with `PRAGMA synchronous = NORMAL;`, `PRAGMA busy_timeout = 10000;`, and `PRAGMA foreign_keys = ON;`.
3. Symmetrical Sale Reversal (`cancel_sale` in `app/routers/pos.py`):
   - Fix `cancel_sale` so that when cancelling a sale, it restores ALL items:
     - Individual presas (`POL-PEC`, `POL-MUS`, `POL-CON`, `POL-ALA`)
     - Almuerzo Completo (`ALM-COMP` with `chosen_presa`, caldo, arroz, frijoles)
     - Combos (`POL-14`: 1 muslo + 1 contramuslo + 1 papas; `POL-12`: 1 pechuga + 1 ala + 1 muslo + 1 contramuslo + 1 papas; `POL-ENT`: 2 pechugas + 2 alas + 2 muslos + 2 contramuslos + 2 papas)
     - Porciones (`POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`, `POR-AREP`)
     - Gaseosas
   - Fix SQL injection risk in line 246 (use parameterized queries).
   - Ensure an already cancelled sale cannot be cancelled again (HTTP 400).
4. Non-Negative Stock Floor & Atomic Deductions:
   - Enforce that stock cannot drop below 0. Check `stock >= qty` before deducting or use atomic `UPDATE inventory SET stock = stock - ? WHERE item_key = ? AND stock >= ?` and verify `rowcount > 0`. If insufficient stock, raise HTTP 400 with a clear message.
5. Despiece Validation & Stage Integrity (`app/routers/kitchen.py`):
   - Validate `inventory['pollo_entero_crudo'].stock >= whole_chickens` before butchering. Raise HTTP 400 if insufficient.
   - Enforce `1 Pollo Crudo -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + 2 Caldo` with audit logging.
6. Track Dry Supplies & Arepas:
   - Ensure `POR-AREP` has inventory tracking in `inventory` (`arepas_unidades`) and is deducted on sale and restored on cancel.
   - Ensure `harina_apanar_kg` and `aceite_fritura_lt` are properly tracked.

Verify your changes by running tests.
Write your handoff report to `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m1\handoff.md` and send a message.
