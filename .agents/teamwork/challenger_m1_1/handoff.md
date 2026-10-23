# Adversarial Verification Report — Milestone M1: Concurrency & Database Locking Resilience

**Agent**: Challenger 1 (`challenger_m1_1`)  
**Roles**: critic, specialist (Empirical Challenger)  
**Date**: 2026-10-21T02:09:00Z  
**Target Milestone**: M1 (Core Data Integrity & Concurrency)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Verdict**: **REQUEST_CHANGES**  

---

## 1. Observation

Direct empirical execution of adversarial stress harnesses against the application and SQLite database revealed the following verified results:

### 1.1 Empirical Checkout Concurrency Stress Test (60 Transactions across 15 Threads)
- **Harness**: `tests/test_adversarial_m1.py::test_adversarial_barrier_hammering_checkout`
- **Execution Profile**:
  - 60 heterogeneous checkout transactions: combos (`POL-ENT`, `POL-12`, `POL-14`), lunch specials (`ALM-COMP` with varying presas), individual presas (`POL-PEC`, `POL-ALA`), sides (`POR-AREP`), and sodas (`GAS-COC-400`, `GAS-MAN-400`).
  - Executed across 15 concurrent worker threads synchronized using `threading.Barrier(15)` to force simultaneous contention at the exact same millisecond.
- **Results**:
  - HTTP 200 Success Rate: **60 / 60 (100%)**.
  - Duplicate `sale_code`s: **0** (`len(set(sale_codes)) == 60`). Format strictly verified as `^VTA-\d{6}-\d{4}$`.
  - SQLite Lock / Busy Errors: **0** (`"database is locked"` or `"busy"` occurrences: 0).
  - Mathematical Inventory Balance: **0.0 Drift**. For every tracked inventory item key (`pechuga_vitrina`, `muslo_vitrina`, `contramuslo_vitrina`, `ala_vitrina`, `papas_raciones`, `caldo_raciones`, `arroz_raciones`, `frijoles_raciones`, `arepas_unidades`, `GAS-COC-400`, `GAS-MAN-400`), `Initial Stock - Actual Final Stock == Total Expected Deductions` with exact mathematical precision.

### 1.2 Empirical Stock Exhaustion Race Condition Test (Non-Negative Floor)
- **Harness**: `tests/test_adversarial_m1.py::test_adversarial_concurrency_stock_exhaustion_race`
- **Execution Profile**:
  - `pechuga_vitrina` seeded to exactly 12.0 units.
  - 60 simultaneous checkout requests across 15 threads (barrier synchronized), each attempting to buy 1 Pechuga Sola (`POL-PEC`).
- **Results**:
  - Exactly **12** transactions succeeded with HTTP 200.
  - Exactly **48** transactions were cleanly rejected with HTTP 400 (`"Stock insuficiente para 'Pechugas en Vitrina'. Disponible: X, requerido: Y."`).
  - Final stock of `pechuga_vitrina`: **0.0** (strictly non-negative).
  - HTTP 500 / SQLite Lock Errors: **0**.

### 1.3 Mixed High-Contention POS + Kitchen Workload Test
- **Harness**: `tests/test_adversarial_m1.py::test_adversarial_mixed_pos_and_kitchen_concurrency` and `test_adversarial_despiece_concurrency_race`
- **Execution Profile**:
  - 30 concurrent mixed operations across 15 threads: 20 POS Checkouts (1/4 Pollo), 5 Kitchen Despieces (2 whole chickens each = 10 chickens consumed), 5 Fryer Batch Timers (16 presas each = harina & aceite deducted).
  - 8 concurrent despieces contending for 3 bodega chickens.
- **Results**:
  - Zero deadlocks, zero lock errors.
  - Despiece concurrency guarded cleanly by `UPDATE inventory ... WHERE item_key = 'pollo_entero_crudo' AND stock >= ?` and `cursor.rowcount == 0` (1 success, 7 rejected with HTTP 400).

### 1.4 Critical Vulnerability: Concurrent Double-Cancel Race Condition in `cancel_sale`
- **Harness**: `tests/test_adversarial_m1.py::test_adversarial_concurrent_double_cancel_race`
- **Execution Profile**:
  - 1 completed sale with 1/4 Pollo (`POL-14`).
  - 10 simultaneous cancellation requests fired against `/api/pos/cancel-sale/{sale_id}` across 10 threads synchronized via `threading.Barrier(10)`.
- **Observed Result**:
  - **10 out of 10 requests returned HTTP 200 OK**:
    ```json
    {"success": true, "message": "Venta VTA-261020-0001 anulada y stock devuelto a vitrina/nevera."}
    ```
  - **Assertion Failure**:
    ```
    FAILED tests/test_adversarial_m1.py::test_adversarial_concurrent_double_cancel_race - AssertionError: RACE CONDITION IN CANCEL_SALE: 10 requests succeeded! Expected exactly 1 success. Successes: [(0, 200, ...), (1, 200, ...), (2, 200, ...), (3, 200, ...), (4, 200, ...), (5, 200, ...), (6, 200, ...), (7, 200, ...), (8, 200, ...), (9, 200, ...)]
    assert 10 == 1
    ```
  - **Inventory Impact**:
    The sale items (muslo, contramuslo, papas) were restored **10 times** into inventory, causing massive phantom inventory inflation (e.g., +10 muslos instead of +1 muslo).
- **Vulnerable Code Location (`app/routers/pos.py:286-324`)**:
  ```python
  @router.post("/cancel-sale/{sale_id}")
  def cancel_sale(sale_id: int):
      conn = get_db_connection()
      cursor = conn.cursor()
      try:
          sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
          if not sale:
              raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")

          if sale["status"] == "anulada":
              raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

          # Revertir inventario de forma simétrica
          ...
          for item_key, qty in restorations.items():
              cursor.execute("""
                  UPDATE inventory 
                  SET stock = stock + ?, updated_at = ?
                  WHERE item_key = ?
              """, (qty, now_str, item_key))

          cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ?", (sale_id,))
          conn.commit()
  ```

---

## 2. Logic Chain

1. **Checkout Concurrency and Collision Resistance**:
   - `get_next_sale_code()` uses SQLite 3.35+ atomic upsert on `order_counters`:
     ```sql
     INSERT INTO order_counters (counter_name, last_value)
     VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM sales WHERE date_str = ?) + 1)
     ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
     RETURNING last_value;
     ```
   - Because `order_counters` is modified inside the same transaction as the sale, and SQLite serializes write locks, all 60 concurrent checkouts obtained strictly unique sequence numbers (`VTA-261020-0001` to `VTA-261020-0060`) with zero duplicate codes (Observation 1.1).
   - Under SQLite WAL mode (`PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=10000;`), no thread timed out waiting for the database write lock (Observation 1.1).

2. **Stock Floor Atomicity in Checkout & Despiece**:
   - Both `process_checkout` and `despiece` enforce the stock floor at the SQL level:
     ```sql
     UPDATE inventory SET stock = stock - ?, updated_at = ? WHERE item_key = ? AND stock >= ?
     ```
     followed by:
     ```python
     if cursor.rowcount == 0:
         conn.rollback()
         raise HTTPException(status_code=400, detail="Stock insuficiente...")
     ```
   - When 60 threads contended for 12 items, SQLite write transactions processed the deductions serially: the first 12 reduced stock to 0.0, and the remaining 48 matched `stock >= ?` with 0 rows updated, triggering immediate rollbacks and HTTP 400 responses without allowing negative stock or phantom drift (Observation 1.2).

3. **Defect in Symmetrical Cancellation (`cancel_sale`)**:
   - Unlike `process_checkout` and `despiece`, `cancel_sale` performs a non-atomic read-then-write (Time-of-Check to Time-of-Use / TOCTOU vulnerability):
     1. In Python `sqlite3`, transactions default to deferred mode. `SELECT * FROM sales WHERE id = ?` only acquires a shared read lock and does NOT serialize writes.
     2. In WAL mode, concurrent readers do not block readers. When 10 requests hit `/api/pos/cancel-sale/{sale_id}` concurrently, all 10 read `sale["status"] == "completada"`.
     3. All 10 pass the `if sale["status"] == "anulada":` guard in Python.
     4. Each thread serially enters write mode, executes `UPDATE inventory SET stock = stock + ?`, marks `status = 'anulada'`, and commits.
     5. The sale is marked anulada 10 times, and inventory is incremented 10 times for a single sale cancellation (Observation 1.4).
   - This directly breaks Feature 3 ("Symmetrical Sale Cancellation") and Acceptance Criteria 32 ("Verificación de inventario cerrado con discrepancia cero") under concurrency.

---

## 3. Caveats

- **Scope of Assessment**: This audit specifically stress-tested Milestone M1 core data integrity, concurrency, and locking resilience (`app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`). Frontend UI components (touch targets, modals, cash change keyboards) belong to Milestone M2 and were not evaluated in this stress audit.
- **Isolated Database Fixtures**: All stress tests were conducted using temporary SQLite database files via `isolated_db` to guarantee complete isolation without altering production data in `data/asadero.db`.

---

## 4. Conclusion

### Verdict: **REQUEST_CHANGES**

Milestone M1 has demonstrated outstanding resilience in checkout concurrency, sequence numbering, and non-negative stock floors:
- **Zero collisions** across 60 simultaneous checkouts on 15 threads.
- **Zero database locked or busy errors** under SQLite WAL mode.
- **Zero mathematical inventory drift** in standard checkout and kitchen despiece operations.

**HOWEVER, a Critical Data Integrity Vulnerability was discovered in `cancel_sale` (`app/routers/pos.py:286-324`)**:
Concurrent cancellation requests targeting the same sale ID bypass the non-atomic status check, all succeed with HTTP 200, and restore inventory multiple times, resulting in severe phantom stock inflation.

### Required Action for Worker M1:
Harden `cancel_sale` in `app/routers/pos.py` using atomic conditional updating:
```python
# Atomically transition status from completada to anulada
cursor.execute("""
    UPDATE sales 
    SET status = 'anulada' 
    WHERE id = ? AND status != 'anulada'
""", (sale_id,))

if cursor.rowcount == 0:
    sale = cursor.execute("SELECT status FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if not sale:
        raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
    raise HTTPException(status_code=400, detail=f"La venta ya se encuentra anulada.")

# Only the thread that succeeded in updating the status restores inventory
...
```

---

## 5. Verification Method

To independently reproduce and verify these findings:

1. **Execute Challenger Concurrency Test Suite**:
   ```powershell
   pytest -v tests/test_adversarial_m1.py
   ```
   *Observed outcome*:
   - `test_adversarial_barrier_hammering_checkout`: **PASSED** (60 transactions, 15 threads, 0 collisions, 0 locks, 0 drift).
   - `test_adversarial_concurrency_stock_exhaustion_race`: **PASSED** (Strict 0.0 non-negative floor).
   - `test_adversarial_mixed_pos_and_kitchen_concurrency`: **PASSED** (POS + Despiece + Batch Timers).
   - `test_adversarial_despiece_concurrency_race`: **PASSED** (Bodega stock floor).
   - `test_adversarial_concurrent_double_cancel_race`: **FAILED** (`AssertionError: RACE CONDITION IN CANCEL_SALE: 10 requests succeeded! Expected exactly 1 success.`).

2. **Condition for Invalidation**:
   The `REQUEST_CHANGES` verdict will be overturned to `APPROVE` once `cancel_sale` is updated with atomic conditional status transitions and all 5 tests in `tests/test_adversarial_m1.py` pass with 100% success.
