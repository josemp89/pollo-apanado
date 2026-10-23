# Forensic Audit Report & Handoff: Milestone M1 Iteration 2

**Agent**: Forensic Integrity Auditor (`auditor_m1_r2_1`)  
**Role**: critic, specialist, auditor  
**Date**: 2026-10-21T02:40:00Z  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Milestone**: M1 Iteration 2 (Core Data Integrity & Concurrency Hardening)  
**Integrity Mode**: Development (per `ORIGINAL_REQUEST.md` line 8)  
**Profile**: General Project  

---

## Forensic Audit Summary

**Work Product**: `app/main.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, `app/database.py`, `tests/`  
**Verdict**: **CLEAN**

### Phase Results
- **Hardcoded Output Detection**: **PASS** — Zero mock constants, fake assertion bypasses, or hardcoded expected outputs in production code or tests.
- **Facade Detection**: **PASS** — Genuine business logic across all routers interacting directly with SQLite engine.
- **Pre-populated Artifact Detection**: **PASS** — Zero pre-existing `.log`, `*result*`, or `*output*` files in workspace.
- **Dependency Audit**: **PASS** — No external library delegation; native SQLite WAL, FastAPI, Pydantic, and Python standard libraries used authentically.
- **Behavioral Verification (Test Suite Execution)**: **PASS** — 112 passed tests across all test suites (`test_milestone_m1.py`, `test_adversarial_m1.py`, `test_challenger_m1_2.py`, `test_concurrency_stress.py`, `test_tier1_features.py`, `test_tier2_boundaries.py`, `test_tier3_cross_features.py`, `test_tier4_lunch_rush.py`).
- **Atomic Conditional SQLite Writes in `cancel_sale`**: **PASS** — Direct query of SQLite database confirms genuine row transition (`status = 'anulada'`) and single atomic inventory restoration; 20-thread concurrency test yielded exactly 1 success (HTTP 200) and 19 rejections (HTTP 400).
- **Validation Handlers & Pydantic Boundary Enforcement**: **PASS** — Negative/zero quantities, negative/zero product IDs, invalid kitchen stages, non-positive presas, and non-positive durations are strictly intercepted and returned as HTTP 400.
- **SQLite Engine `CHECK (stock >= 0)` Declaration & Enforcement**: **PASS** — Direct query of `sqlite_master` confirms table definition constraint; raw DML updates and inserts violating the condition trigger native `sqlite3.IntegrityError: CHECK constraint failed: stock >= 0`.

---

## 1. Observation

### 1.1 Source Code Inspection
1. **`app/main.py` (lines 16-25)**:
   ```python
   @app.exception_handler(RequestValidationError)
   async def validation_exception_handler(request: Request, exc: RequestValidationError):
       errors = exc.errors()
       first_err = errors[0] if errors else {}
       field = " -> ".join(str(loc) for loc in first_err.get("loc", []))
       msg = first_err.get("msg", "Dato inválido")
       return JSONResponse(
           status_code=400,
           content={"detail": f"Error de validación en campo '{field}': {msg}", "errors": errors}
       )
   ```
   *Finding*: Genuinely intercepts Pydantic `RequestValidationError` and formats response with HTTP status code 400 and diagnostic detail.

2. **`app/routers/pos.py` (lines 10-14, 138-144, 305-349)**:
   - Line 11-12: `CartItem` declares `product_id: int = Field(..., gt=0)` and `quantity: int = Field(..., gt=0)`.
   - Line 138-144: Defensive endpoint check `if item.quantity <= 0: raise HTTPException(status_code=400, ...)`
   - Line 307-311: Atomic conditional update in `cancel_sale`:
     ```python
     cursor.execute("""
         UPDATE sales 
         SET status = 'anulada' 
         WHERE id = ? AND status != 'anulada'
     """, (sale_id,))
     if cursor.rowcount == 0:
         sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()
         if not sale:
             raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
         raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")
     ```
   *Finding*: Replaces vulnerable check-then-act with single serialized atomic conditional statement.

3. **`app/routers/kitchen.py` (lines 24, 160-183)**:
   ```python
   VALID_BATCH_STAGES = ("salmuera", "adobo", "fritura")
   ...
   stage_norm = (payload.stage or "").strip().lower()
   if stage_norm not in VALID_BATCH_STAGES:
       raise HTTPException(status_code=400, detail=f"Etapa inválida '{payload.stage}'...")
   if payload.total_presas <= 0:
       raise HTTPException(status_code=400, detail="El total de presas debe ser mayor a 0.")
   if payload.duration_hours is not None and payload.duration_hours <= 0:
       raise HTTPException(status_code=400, detail="La duración debe ser mayor a 0 horas.")
   ```
   *Finding*: Input guards execute before database connection acquisition.

4. **`app/database.py` (lines 45, 136-161)**:
   - `inventory` table definition: `stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0)`
   - Idempotent migration in `init_db()` checks `sqlite_master` for `inventory` table SQL, sanitizes negative values if any, and migrates to the schema containing the `CHECK` constraint.

### 1.2 Independent Empirical Test Execution Outputs

1. **Full Pytest Suite**:
   ```powershell
   pytest -v
   ```
   *Verbatim Result*:
   ```
   ====================== 112 passed, 3 warnings in 16.38s =======================
   ```

2. **Targeted Milestone M1 Suites**:
   ```powershell
   pytest tests/test_milestone_m1.py tests/test_adversarial_m1.py tests/test_challenger_m1_2.py -v -s
   ```
   *Verbatim Result*:
   ```
   ======================= 24 passed, 3 warnings in 6.51s ========================
   ```

3. **SQLite Schema & Engine CHECK Constraint Verification**:
   ```powershell
   python -c "import app.database as d; d.init_db(); c=d.get_db_connection(); s=c.execute('SELECT sql FROM sqlite_master WHERE name=?', ('inventory',)).fetchone()[0]; print(s); c.close()"
   ```
   *Verbatim Result*:
   ```sql
   CREATE TABLE inventory (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               item_key TEXT UNIQUE NOT NULL,
               name TEXT NOT NULL,
               category TEXT NOT NULL,
               stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
               unit TEXT NOT NULL,
               min_threshold REAL DEFAULT 5,
               updated_at TEXT
           )
   ```
   Testing negative update against engine:
   ```powershell
   python -c "import app.database as d, sqlite3; d.init_db(); c=d.get_db_connection();
   try:
       c.execute('UPDATE inventory SET stock = -1.0 WHERE item_key = ?', ('pechuga_vitrina',))
       print('FAILED_CHECK')
   except sqlite3.IntegrityError as e:
       print('SUCCESS_INTEGRITY_ERROR:', e)
   finally:
       c.close()"
   ```
   *Verbatim Result*:
   ```
   SUCCESS_INTEGRITY_ERROR: CHECK constraint failed: stock >= 0
   ```

4. **Verification of Genuine SQLite Writes in `cancel_sale`**:
   - Initial SQLite status: `'completada'`, stock in SQLite: `10.0`
   - Cancel API call: returned HTTP 200 `{'success': True, 'message': 'Venta VTA-261020-0001 anulada y stock devuelto a vitrina/nevera.'}`
   - Post-cancel SQLite direct row read: `status = 'anulada'`, stock in SQLite: `12.0` (genuinely restored)
   - Repeat cancel API call: returned HTTP 400 `{'detail': 'La venta VTA-261020-0001 ya se encuentra anulada.'}`
   - Post-repeat SQLite direct row read: stock remains `12.0` (zero duplicate restoration)

5. **Runtime Validation & Pydantic Constraint Interception**:
   - `POST /api/pos/checkout` (`quantity = -1`): status = 400, detail = `Error de validación en campo 'body -> items -> 0 -> quantity': Input should be greater than 0`
   - `POST /api/pos/checkout` (`quantity = 0`): status = 400, detail = `Error de validación en campo 'body -> items -> 0 -> quantity': Input should be greater than 0`
   - `POST /api/pos/checkout` (`product_id = 0`): status = 400, detail = `Error de validación en campo 'body -> items -> 0 -> product_id': Input should be greater than 0`
   - `POST /api/kitchen/batch-timer` (`stage = 'horno'`): status = 400, detail = `Etapa inválida 'horno'. Debe ser una de: ['salmuera', 'adobo', 'fritura']`
   - `POST /api/kitchen/batch-timer` (`total_presas = 0`): status = 400, detail = `El total de presas debe ser mayor a 0.`
   - `POST /api/kitchen/batch-timer` (`duration_hours = -0.5`): status = 400, detail = `La duración debe ser mayor a 0 horas.`

6. **Concurrent Cancellation Race Stress Test**:
   - 10-thread and 20-thread simultaneous strikes targeting a single sale ID yielded exactly 1 HTTP 200 response and 9 / 19 HTTP 400 responses.
   - Final SQLite stock verified equal to pre-sale stock with 0.0 drift.

---

## 2. Logic Chain

1. **Premise**: In Milestone M1 Iteration 1, three adversarial challenger tests failed due to a TOCTOU race in `cancel_sale`, missing negative/zero quantity validation in POS checkout, and unvalidated kitchen batch parameters. Additionally, database integrity was not enforced at the storage engine level.
2. **Analysis of Iteration 2 Hardening**:
   - By transitioning `cancel_sale` to use `UPDATE sales SET status = 'anulada' WHERE id = ? AND status != 'anulada'`, SQLite's engine-level write serialization ensures that only the single transaction updating the row receives `cursor.rowcount == 1`. All concurrent competitors receive `cursor.rowcount == 0` and are rejected before executing any inventory restoration logic.
   - By configuring `Field(..., gt=0)` on `CartItem` and attaching the custom `RequestValidationError` handler in `app/main.py`, FastAPI translates schema validation failures from HTTP 422 to the project standard HTTP 400. Defensive runtime checks in `process_checkout` provide defense-in-depth against payload manipulation.
   - By introducing `VALID_BATCH_STAGES` and explicit bounds checking in `start_batch_timer`, arbitrary stages and non-positive presas are rejected deterministically with HTTP 400.
   - By embedding `CHECK (stock >= 0)` into the table DDL and executing an idempotent migration on legacy databases, SQLite itself guarantees that negative inventory cannot be persisted by any SQL path.
3. **Forensic Verification**:
   - Independent inspection of `sqlite_master` confirms the table schema holds `CHECK (stock >= 0)`.
   - Direct execution of invalid DML against SQLite raised `sqlite3.IntegrityError: CHECK constraint failed: stock >= 0`.
   - Inspection of raw SQLite table records before and after `cancel_sale` empirically confirmed genuine database writes.
   - Concurrency stress tests with thread pools and barriers confirmed zero race conditions, zero database lock exceptions (`WAL` mode active), and zero inventory drift.
4. **Conclusion**: The implementation is completely genuine, authentic, and free of mocks or bypass facades.

---

## 3. Caveats

- **No Caveats**: All 4 areas specified in the audit dispatch were investigated directly through static code analysis, raw SQLite inspection, and empirical runtime execution. No unverified assumptions remain.

---

## 4. Conclusion

The work product for Milestone M1 Iteration 2 is certified as **CLEAN**.  
All adversarial vulnerabilities identified in Iteration 1 have been resolved with genuine, production-grade architectural defenses:
1. `cancel_sale` race condition eliminated via atomic conditional status transitions with genuine SQLite persistence.
2. POS cart items bounded to `> 0` with Pydantic and exception mapping to HTTP 400.
3. Kitchen batch timer input boundaries (`stage in ('salmuera', 'adobo', 'fritura')`, `total_presas > 0`, `duration_hours > 0`) enforced.
4. SQLite engine-level `CHECK (stock >= 0)` declared in schema and verified active.
5. All 112 tests across unit, boundary, cross-feature, adversarial, and stress suites pass with 100% success rate.

---

## 5. Verification Method

To independently reproduce this forensic audit:

1. **Verify Full Pytest Suite**:
   ```powershell
   pytest -v
   ```
   *Expected*: `112 passed, 3 warnings in ~16s`

2. **Verify SQLite Engine CHECK Constraint**:
   ```powershell
   python -c "import app.database as d, sqlite3; d.init_db(); c=d.get_db_connection();
   try:
       c.execute('UPDATE inventory SET stock = -1.0 WHERE item_key = ?', ('pechuga_vitrina',))
       print('FAILED_CHECK')
   except sqlite3.IntegrityError as e:
       print('SUCCESS_INTEGRITY_ERROR:', e)
   finally:
       c.close()"
   ```
   *Expected*: `SUCCESS_INTEGRITY_ERROR: CHECK constraint failed: stock >= 0`

3. **Verify SQLite Master DDL**:
   ```powershell
   python -c "import app.database as d; d.init_db(); c=d.get_db_connection(); s=c.execute('SELECT sql FROM sqlite_master WHERE name=?', ('inventory',)).fetchone()[0]; print(s); c.close()"
   ```
   *Expected*: Contains `stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0)`

4. **Verify Validation Exception Handler**:
   ```powershell
   python -c "from fastapi.testclient import TestClient; from app.main import app; c = TestClient(app); r = c.post('/api/pos/checkout', json={'items': [{'product_id': 1, 'quantity': -5}], 'payment_method': 'efectivo'}); assert r.status_code == 400; print('VALIDATION HANDLER PASS:', r.json())"
   ```
   *Expected*: `VALIDATION HANDLER PASS: {'detail': \"Error de validación en campo 'body -> items -> 0 -> quantity': Input should be greater than 0\", ...}`

5. **Invalidation Conditions**:
   The verdict is invalidated if:
   - Any test in `tests/` fails.
   - Any update with `stock < 0` succeeds without raising `sqlite3.IntegrityError`.
   - `cancel_sale` allows two concurrent callers to both receive HTTP 200.
   - Any negative or zero quantity checkout returns HTTP 200 or HTTP 422.
