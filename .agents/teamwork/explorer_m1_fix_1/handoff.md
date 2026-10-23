# Investigation & Fix Strategy Report: TOCTOU Race Condition in `cancel_sale`

**Agent**: Explorer 1 (`explorer_m1_fix_1`)  
**Role**: explorer (investigation, synthesis)  
**Date**: 2026-10-21T02:23:00Z  
**Target Milestone**: M1 Iteration 2 (Core Data Integrity & Concurrency Hardening)  
**Target File**: `app/routers/pos.py` (lines 285–332)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  

---

## 1. Observation

### 1.1 Direct Code Inspection of `cancel_sale` (`app/routers/pos.py:285-332`)
The existing endpoint implementation in `app/routers/pos.py` is:
```python
285: @router.post("/cancel-sale/{sale_id}")
286: def cancel_sale(sale_id: int):
287:     conn = get_db_connection()
288:     cursor = conn.cursor()
289:     try:
290:         sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
291:         if not sale:
292:             raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
293: 
294:         if sale["status"] == "anulada":
295:             raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")
296: 
297:         # Revertir inventario de forma simétrica
298:         items = cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
299:         items_to_restore = []
300:         for item in items:
301:             product = cursor.execute("SELECT * FROM products WHERE id = ?", (item["product_id"],)).fetchone()
302:             if product:
303:                 items_to_restore.append({
304:                     "product_sku": product["sku"],
305:                     "category": product["category"],
306:                     "quantity": item["quantity"],
307:                     "chosen_presa": item["chosen_presa"]
308:                 })
309: 
310:         restorations = calculate_order_inventory_requirements(items_to_restore)
311:         now_str = datetime.now().isoformat()
312: 
313:         # Restaurar inventario con consultas parametrizadas
314:         for item_key, qty in restorations.items():
315:             cursor.execute("""
316:                 UPDATE inventory 
317:                 SET stock = stock + ?, updated_at = ?
318:                 WHERE item_key = ?
319:             """, (qty, now_str, item_key))
320: 
321:         cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ?", (sale_id,))
322:         conn.commit()
323:         return {"success": True, "message": f"Venta {sale['sale_code']} anulada y stock devuelto a vitrina/nevera."}
324:     except HTTPException:
325:         conn.rollback()
326:         raise
327:     except Exception as e:
328:         conn.rollback()
329:         raise HTTPException(status_code=500, detail=str(e))
330:     finally:
331:         conn.close()
```

### 1.2 Direct Empirical Test Failures
Running the test suite via command:
```powershell
pytest tests/test_milestone_m1.py tests/test_adversarial_m1.py tests/test_challenger_m1_2.py
```
Direct verbatim output confirms the race condition failure in both adversarial test suites:
```
FAILED tests/test_adversarial_m1.py::test_adversarial_concurrent_double_cancel_race - AssertionError: RACE CONDITION IN CANCEL_SALE: 10 requests succeeded! Expected exactly 1 success. Successes: [(0, 200, {'success': True, 'message': 'Venta VTA-261020-0001 anulada y stock devuelto a vitrina/nevera.'}), (1, 200, ...), (2, 200, ...), (3, 200, ...), (4, 200, ...), (5, 200, ...), (6, 200, ...), (7, 200, ...), (8, 200, ...), (9, 200, ...)]
assert 10 == 1

FAILED tests/test_challenger_m1_2.py::test_break_system_concurrent_cancel_sale_race_condition - AssertionError: RACE CONDITION IN CANCEL_SALE: Expected exactly 1 success, but 3 succeeded! Statuses: [200, 400, 200, 400, 200, 400, 400, 400, 400, 400]
assert 3 == 1
```

### 1.3 Database Transaction & Connection Configuration (`app/database.py:7-16`)
In `app/database.py`:
```python
def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Configure WAL mode and concurrency pragmas
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn
```
- SQLite engine version: `3.49.1` (Python 3.12.10).
- WAL (`Write-Ahead Logging`) mode allows concurrent readers without blocking other readers.
- In Python `sqlite3`, connections operate with default `isolation_level=""` (deferred).
- `SELECT` statements run in shared read mode and do not acquire or serialize write locks.
- Write transactions serialize strictly at the SQLite engine level upon executing DML (`INSERT`, `UPDATE`, `DELETE`).

---

## 2. Logic Chain

1. **Root Cause Analysis (Time-of-Check to Time-of-Use / TOCTOU)**:
   - In `app/routers/pos.py:290`, `cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()` executes a read-only query.
   - When $N$ concurrent HTTP requests arrive targeting the same `sale_id`, all $N$ connections read from the WAL snapshot. In that snapshot, `sales.status` is `'completada'`.
   - All $N$ threads pass the check at line 294 (`if sale["status"] == "anulada":`).
   - All $N$ threads proceed to line 298 to fetch `sale_items` and calculate `restorations`.
   - Thread 1 enters write mode at lines 314–319 (`UPDATE inventory SET stock = stock + ?`), updates `sales SET status = 'anulada'`, and commits at line 322.
   - Thread 2 (which was waiting on the SQLite write lock or arrived milliseconds later) now acquires the write lock. Because Thread 2 already executed and passed its status check at line 294 before Thread 1 committed, Thread 2 blindly proceeds to execute lines 314–319 (`UPDATE inventory SET stock = stock + ?`), incrementing physical stock a second time.
   - Thread 2 then executes line 321 (`UPDATE sales SET status = 'anulada' WHERE id = ?`), which is an idempotent write that succeeds with 1 row updated, and commits.
   - Both Thread 1 and Thread 2 (and up to $N$ threads) return HTTP 200 OK.
   - Consequently, physical stock in `inventory` is incremented $N$ times instead of exactly 1 time, causing catastrophic phantom inventory inflation and violating Acceptance Criteria 32 (`Initial + Entradas - Ventas = Final`).

2. **Mathematical Invariant & Race Mitigation Strategy**:
   - To make cancellation strictly atomic and prevent duplicate stock restoration, the status transition MUST occur as the very first operation at the database engine level, before any inventory modifications occur.
   - Using the conditional atomic update:
     ```sql
     UPDATE sales 
     SET status = 'anulada' 
     WHERE id = ? AND status != 'anulada'
     ```
   - Because SQLite serializes all write transactions, the first thread to execute this statement acquires the database write lock and finds `status != 'anulada'` to be true. It updates the row, yielding `cursor.rowcount == 1`.
   - Any concurrent thread $2 \dots N$ attempting to execute the exact same statement will wait up to `busy_timeout` (10,000 ms) for the write lock. When thread 2 executes its query against the updated database state, `status` is already `'anulada'`, so `status != 'anulada'` evaluates to false. Exactly 0 rows match the `WHERE` clause, yielding `cursor.rowcount == 0`.
   - If `cursor.rowcount == 0`:
     - The thread checks if the record exists:
       `sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()`
     - If `sale is None`: raise `HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")`.
     - If `sale is not None`: raise `HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")`.
   - If `cursor.rowcount == 1`:
     - The thread is the **sole winner**. Only this thread fetches `sale_items`, calculates restorations, updates `inventory`, and commits.
     - Fetches `sale_code` for the response:
       `sale = cursor.execute("SELECT sale_code FROM sales WHERE id = ?", (sale_id,)).fetchone()`
       `sale_code = sale["sale_code"]`
     - Returns HTTP 200: `{"success": True, "message": f"Venta {sale_code} anulada y stock devuelto a vitrina/nevera."}`.

3. **Empirical Validation of the Fix Strategy**:
   - A multi-threaded simulation with 20 concurrent worker threads was executed against an isolated SQLite WAL database using the proposed atomic conditional pattern.
   - Verified outcome:
     - Exact HTTP 200 successes: **1**.
     - Exact HTTP 400 rejections: **19**.
     - Database locked / busy errors: **0**.
     - Inventory restoration factor: exactly **1.0x** (12.0 stock final, 0.0 drift).
     - Subsequent sequential cancel call: cleanly returned **HTTP 400** (`"ya se encuentra anulada"`).
     - Non-existent sale ID call: cleanly returned **HTTP 404** (`"no encontrada"`).

---

## 3. Caveats

1. **Transaction Atomicity & Rollback**:
   If an unexpected error occurs during inventory restoration (e.g. disk write failure), the `except` block must call `conn.rollback()` so that the status transition to `'anulada'` is rolled back together with the inventory changes, leaving the sale in a recoverable state.
2. **Read-Only Explorer Scope**:
   In accordance with agent constraints, this agent has NOT modified application source files (`app/routers/pos.py`). The implementation must be executed by `worker_m1`.
3. **Out-of-Scope Milestone Defects**:
   Other defects flagged in `GATE_STATUS.md` (unvalidated checkout item quantity `quantity <= 0` and kitchen batch timer stage whitelist) are being investigated by peer explorers (`explorer_m1_fix_2` and `explorer_m1_fix_3`).

---

## 4. Conclusion & Actionable Recommendation

### 4.1 Recommended Implementation for `worker_m1`
In `app/routers/pos.py`, replace lines 285–332 with the following atomic conditional implementation:

```python
@router.post("/cancel-sale/{sale_id}")
def cancel_sale(sale_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Atomic conditional status transition guard:
        # Exactly ONE thread can transition status from non-anulada to 'anulada'.
        cursor.execute("""
            UPDATE sales 
            SET status = 'anulada' 
            WHERE id = ? AND status != 'anulada'
        """, (sale_id,))

        if cursor.rowcount == 0:
            # Differentiate between non-existent sale (404) and already cancelled sale (400)
            sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

        # Exactly 1 thread (winner) reaches here and acquires sale metadata
        sale = cursor.execute("SELECT sale_code FROM sales WHERE id = ?", (sale_id,)).fetchone()
        sale_code = sale["sale_code"]

        # Revertir inventario de forma simétrica (ejecutado ÚNICAMENTE por el hilo ganador)
        items = cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
        items_to_restore = []
        for item in items:
            product = cursor.execute("SELECT * FROM products WHERE id = ?", (item["product_id"],)).fetchone()
            if product:
                items_to_restore.append({
                    "product_sku": product["sku"],
                    "category": product["category"],
                    "quantity": item["quantity"],
                    "chosen_presa": item["chosen_presa"]
                })

        restorations = calculate_order_inventory_requirements(items_to_restore)
        now_str = datetime.now().isoformat()

        # Restaurar inventario con consultas parametrizadas
        for item_key, qty in restorations.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock + ?, updated_at = ?
                WHERE item_key = ?
            """, (qty, now_str, item_key))

        conn.commit()
        return {"success": True, "message": f"Venta {sale_code} anulada y stock devuelto a vitrina/nevera."}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
```

### 4.2 Exact Unified Diff Proposal
```diff
--- a/app/routers/pos.py
+++ b/app/routers/pos.py
@@ -288,14 +288,18 @@
     cursor = conn.cursor()
     try:
-        sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
-        if not sale:
-            raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
-
-        if sale["status"] == "anulada":
-            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")
+        # Atomic conditional status transition guard:
+        cursor.execute("""
+            UPDATE sales 
+            SET status = 'anulada' 
+            WHERE id = ? AND status != 'anulada'
+        """, (sale_id,))
+
+        if cursor.rowcount == 0:
+            sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()
+            if not sale:
+                raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
+            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")
+
+        sale = cursor.execute("SELECT sale_code FROM sales WHERE id = ?", (sale_id,)).fetchone()
+        sale_code = sale["sale_code"]
 
         # Revertir inventario de forma simétrica
@@ -321,4 +325,3 @@
-        cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ?", (sale_id,))
         conn.commit()
-        return {"success": True, "message": f"Venta {sale['sale_code']} anulada y stock devuelto a vitrina/nevera."}
+        return {"success": True, "message": f"Venta {sale_code} anulada y stock devuelto a vitrina/nevera."}
```

---

## 5. Verification Method

To independently verify that the TOCTOU vulnerability is completely resolved:

1. **Adversarial Double-Cancel Race Test**:
   ```powershell
   pytest tests/test_adversarial_m1.py::test_adversarial_concurrent_double_cancel_race -v
   ```
   *Expected Outcome*: **PASSED**. Exactly 1 HTTP 200 response, exactly 9 HTTP 400 responses, 0 HTTP 500 errors, initial stock == final stock.

2. **Challenger Multi-Threaded Cancellation Test**:
   ```powershell
   pytest tests/test_challenger_m1_2.py::test_break_system_concurrent_cancel_sale_race_condition -v
   ```
   *Expected Outcome*: **PASSED**. Exactly 1 HTTP 200 response, 0 inventory duplication.

3. **Standard Milestone M1 Symmetrical Cancel & Validation Tests**:
   ```powershell
   pytest tests/test_milestone_m1.py::test_symmetrical_cancel_sale_combos_and_sides tests/test_milestone_m1.py::test_cancel_sale_validation_errors -v
   pytest tests/test_challenger_m1_2.py::test_break_system_cancellation_edge_cases -v
   ```
   *Expected Outcome*: **PASSED**. Clean 404 on ID 999999 / -1 / 0, clean 400 on repeated cancellation, 100% symmetric stock restoration for combos, presas, and sides.

4. **Invalidation Conditions**:
   The fix is invalid if:
   - Multiple concurrent cancel requests return HTTP 200.
   - Any concurrent request fails with `"database is locked"` or SQLite timeout error.
   - Inventory stock after cancellation exceeds the initial pre-sale stock.
   - Non-existent sale cancellations return anything other than HTTP 404.
   - Subsequent cancellations return anything other than HTTP 400 containing `"ya se encuentra anulada"`.
