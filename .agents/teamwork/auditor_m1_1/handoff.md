# Forensic Audit Report — Milestone M1: Core Data Integrity & Concurrency

**Work Product**: Milestone M1 changes (`app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, `tests/test_milestone_m1.py`)  
**Profile**: General Project  
**Integrity Mode**: Development (defined in `ORIGINAL_REQUEST.md:8`)  
**Auditor**: Forensic Integrity Auditor (`auditor_m1_1`)  
**Verdict**: **CLEAN** (Zero Integrity Violations / Authentically Implemented)  
**Robustness Notice**: 2 Quality & Concurrency Hardening Items Identified from Adversarial Testing  

---

## Forensic Audit Summary

### Phase Results
- **Hardcoded Output Detection**: **PASS** — Zero hardcoded test return strings or static bypasses in production code or test suite.
- **Facade Implementation Detection**: **PASS** — Real SQLite transactional operations, genuine schema tables (`order_counters`, `sales`, `sale_items`, `inventory`, `butchering_logs`, `cooking_batches`), parameterized statements, and real rollback handlers.
- **Fabricated Verification Outputs**: **PASS** — No pre-populated logs, result dumps, or fake attestation files exist in the repository.
- **Self-Certifying Tests**: **PASS** — `tests/test_milestone_m1.py` uses independent, isolated SQLite database fixtures created per test and asserts real state transitions via `TestClient`.
- **Database Sequence Persistence (`order_counters`)**: **PASS** — Empirical trace confirms `order_counters` table records and persists sequence rows (`last_value`) using atomic upsert `ON CONFLICT DO UPDATE ... RETURNING last_value`.
- **Symmetrical Sale Cancellation (`cancel_sale`)**: **PASS** — Empirical trace confirms full SQL updates restoring every combo item (`POL-14`, `POL-12`, `POL-ENT`), lunch specials (`ALM-COMP`), sides, arepas, and sodas with 0 inventory drift.
- **Non-Negative Stock Floor**: **PASS** — Verified both pre-check and atomic database-level check (`WHERE stock >= ?`). Concurrent depletion of 30 threads competing for 15 units resulted in exactly 15 successes and 15 rejections with 0.0 ending stock.
- **Despiece Traceability (`despiece`)**: **PASS** — Verified atomic deduction from bodega `pollo_entero_crudo`, exact mathematical yield allocation (`2P + 2M + 2C + 2A + 2 Caldo`), and real insertion into `butchering_logs`.

---

## 1. Observation

Direct code examination and independent runtime execution yielded the following concrete evidence:

### 1.1 Prohibited Patterns Search
- **Grep for Mocks**: Executed recursive case-insensitive search for `mock` across `app/` and `tests/`. Result: **0 matches**. No `unittest.mock`, `pytest-mock`, or fake stubs exist.
- **Artifact Search**: Searched workspace for pre-populated `*.log`, `*result*`, and `*output*` files. Result: **0 matches**.

### 1.2 Inspection of `order_counters` Implementation
- In `app/database.py:127-132`:
  ```sql
  CREATE TABLE IF NOT EXISTS order_counters (
      counter_name TEXT PRIMARY KEY,
      last_value INTEGER NOT NULL DEFAULT 0
  );
  ```
- In `app/routers/pos.py:39-56` and `app/routers/kitchen.py:24-41`:
  ```python
  cursor.execute("""
      INSERT INTO order_counters (counter_name, last_value)
      VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM sales WHERE date_str = ?) + 1)
      ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
      RETURNING last_value;
  """, (counter_name, date_str))
  seq = cursor.fetchone()[0]
  ```
- **Empirical Trace**: Ran independent script generating 4 sequence numbers. Queried SQLite table `order_counters` directly:
  `[{'counter_name': 'sale_2026-10-20', 'last_value': 2}, {'counter_name': 'batch_2026-10-20', 'last_value': 2}]`.
  Sequence numbers generated: `VTA-261020-0001`, `VTA-261020-0002`, `LOTE-SAL-2010-001`, `LOTE-FRI-2010-002`. Real database writes confirmed.

### 1.3 Inspection of `cancel_sale` and Combo Inventory Restitution
- In `app/routers/pos.py:57-129`, pure function `calculate_order_inventory_requirements` maps every combo and product to constituent parts:
  - `POL-14` (1/4 Pollo) ➔ 1 muslo + 1 contramuslo + 1 papas
  - `POL-12` (1/2 Pollo) ➔ 1 pechuga + 1 ala + 1 muslo + 1 contramuslo + 1 papas
  - `POL-ENT` (Pollo Entero) ➔ 2 pechugas + 2 alas + 2 muslos + 2 contramuslos + 2 papas
  - `ALM-COMP` (Almuerzo Completo) ➔ chosen presa (`pechuga_vitrina`, `muslo_vitrina`, etc.) + 1 caldo + 1 arroz + 1 frijoles
  - `POR-AREP` (Porción Arepas) ➔ 1 arepas_unidades
- In `app/routers/pos.py:315-322`:
  ```python
  for item_key, qty in restorations.items():
      cursor.execute("""
          UPDATE inventory 
          SET stock = stock + ?, updated_at = ?
          WHERE item_key = ?
      """, (qty, now_str, item_key))
  cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ?", (sale_id,))
  conn.commit()
  ```
- **Empirical Trace**: Executed multi-item combo sale (`POL-ENT`, `POL-12`, `POL-14`, `ALM-COMP` con Pechuga, `POR-AREP` x2, `GAS-COC-400` x1). Checked DB row in `sales` (`status: completada`, `items: 6`). Executed `/api/pos/cancel-sale/{sale_id}`. Inspected DB directly: `sales.status` updated to `'anulada'`, and all 10 tracked inventory keys returned to exact initial levels (`discrepancy = 0.0`). Re-attempted cancellation: returned HTTP 400 (`detail: La venta ... ya se encuentra anulada`) and stock remained unchanged.

### 1.4 Inspection of Non-Negative Stock Floor
- In `app/routers/pos.py:182-211`:
  - Pre-check loop checks `if row["stock"] < needed: raise HTTPException(status_code=400, ...)`
  - SQL atomic execution: `UPDATE inventory SET stock = stock - ?, updated_at = ? WHERE item_key = ? AND stock >= ?`
  - Guard: `if cursor.rowcount == 0:` raises HTTP 400 with current available stock.
- **Empirical Concurrency Depletion Test**: Executed 30 concurrent threads competing for 15 units of `caldo_raciones`:
  - HTTP 200 successes: exactly 15.
  - HTTP 400 rejections: exactly 15.
  - Ending stock in SQLite: exactly `0.0`. No negative values occurred.

### 1.5 Inspection of `despiece` and `butchering_logs`
- In `app/routers/kitchen.py:42-125`:
  - Enforces `payload.whole_chickens > 0` (raises HTTP 400 otherwise).
  - Checks bodega availability: `available < n` raises HTTP 400.
  - Atomic deduction: `UPDATE inventory ... WHERE item_key = 'pollo_entero_crudo' AND stock >= ?`.
  - Math formula: `pechugas = 2*n`, `muslos = 2*n`, `contramuslos = 2*n`, `alas = 2*n`, `caldo_raciones = 2*n`.
  - SQL audit log:
    ```python
    cursor.execute("""
        INSERT INTO butchering_logs (
            timestamp, operator, whole_chickens, pechugas_yield, muslos_yield, 
            contramuslos_yield, alas_yield, caldo_bases_yield, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now_str, payload.operator, n, pechugas, muslos, contramuslos, alas, caldo_raciones, payload.notes))
    ```
- **Empirical Trace**: Butchered 4 chickens when 10 were in bodega. Checked DB directly: bodega stock dropped from 10 to 6; vitrina pechugas increased from 12 to 20; `butchering_logs` row inserted with `operator: 'AuditorTest'`, `whole_chickens: 4`, `pechugas_yield: 8`, `caldo_bases_yield: 8`.

### 1.6 High-Concurrency Stress Test (100 Threads)
- Executed 100 concurrent checkout requests across 16 worker threads:
  - Total requests: 100
  - HTTP 200 responses: 100
  - Unique `sale_code` values generated: 100
  - Initial stock: 1000.0
  - Final stock: 900.0 (exact deduction of 100 units). Zero collisions, zero SQLite database lock errors.

### 1.7 Adversarial Vulnerabilities Discovered (Stress-Testing Phase)
During adversarial review and execution of cross-test suites (`tests/test_adversarial_m1.py` and `tests/test_challenger_m1_2.py`), 2 robustness defects were surfaced:
1. **Race Condition in `cancel_sale`**:
   - `tests/test_adversarial_m1.py::test_adversarial_concurrent_double_cancel_race`:
   - When 10 concurrent requests hit `POST /api/pos/cancel-sale/{id}` for the same sale ID, all 10 threads execute `SELECT * FROM sales WHERE id = ?` before any thread commits the `UPDATE`. Consequently, multiple threads observe `status == 'completada'`, and multiple threads execute the stock restitution updates, duplicating restored inventory!
2. **Missing Validation for Negative Quantities in Checkout**:
   - `tests/test_challenger_m1_2.py::test_break_system_checkout_validation_defects`:
   - `CartItem.quantity` accepts negative numbers (e.g., `-5`). A checkout with `quantity: -5` succeeded with HTTP 200, creating negative totals and artificially adding stock to the database.

---

## 2. Logic Chain

1. **Integrity Evaluation**:
   - The project's declared integrity mode in `ORIGINAL_REQUEST.md` is `development`.
   - In Development mode, prohibited patterns are: hardcoded test results, facade implementations that return fixed placeholders without computation, and fabricated verification outputs.
   - Observations 1.1 through 1.6 confirm that the implementation contains genuine SQLite queries, atomic SQL locks, dynamic ID sequences, real multi-level inventory calculations, and real transaction rollback.
   - No mock libraries or artificial shortcuts exist in `app/` or `tests/`.
   - Therefore, the work product passes all forensic integrity checks. The verdict is **CLEAN**.

2. **Quality and Concurrency Hardening Evaluation**:
   - While the code is free of fraudulent shortcuts, Observation 1.7 highlights two functional vulnerabilities that should be hardened:
     a) `cancel_sale` needs an atomic state transition before inventory updates (`UPDATE sales SET status = 'anulada' WHERE id = ? AND status != 'anulada'`) so that concurrent duplicate cancellation requests are immediately rejected by `cursor.rowcount == 0`.
     b) `process_checkout` needs `quantity > 0` validation on each cart item.
   - These are standard software engineering defect corrections, not integrity violations.

---

## 3. Caveats

- **Scope Boundary**: As a Forensic Auditor, I strictly observe, audit, and trace; I do NOT modify application source code.
- **Windows Environment**: All stress tests were run on Python 3.12 under Windows. SQLite concurrency was evaluated using `ThreadPoolExecutor` and isolated SQLite WAL files.

---

## 4. Conclusion

The Milestone M1 work product genuinely and authentically implements all core data integrity and concurrency specifications. No mock facades, hardcoded bypasses, or fabricated outputs were detected.

**Integrity Verdict**: **CLEAN**

**Recommended Hardening Actions for Worker M1**:
1. In `app/routers/pos.py` (`cancel_sale`), execute `UPDATE sales SET status = 'anulada' WHERE id = ? AND status != 'anulada'` as the first operation and check `cursor.rowcount == 0` to prevent race-condition stock multiplication.
2. In `app/routers/pos.py` (`process_checkout`), validate that `item.quantity > 0` (or add `Field(..., gt=0)` to Pydantic model `CartItem`).

---

## 5. Verification Method

To independently reproduce the forensic audit results from the project root (`c:\Users\Alejandro\Desktop\POLLO APANADO`):

1. **Run Full Test Suite**:
   ```powershell
   pytest tests/test_milestone_m1.py -v
   ```
   *Expected outcome*: 9 passed in ~1.0s.

2. **Verify Database Sequences and Pragma Configuration**:
   ```powershell
   python -c "import app.database as db; conn = db.get_db_connection(); print('journal_mode:', conn.execute('PRAGMA journal_mode;').fetchone()[0]); print('synchronous:', conn.execute('PRAGMA synchronous;').fetchone()[0]); print('busy_timeout:', conn.execute('PRAGMA busy_timeout;').fetchone()[0]); print('foreign_keys:', conn.execute('PRAGMA foreign_keys;').fetchone()[0]);"
   ```

3. **Verify Symmetrical Cancellation & Invariance**:
   ```powershell
   pytest tests/test_milestone_m1.py::test_symmetrical_cancel_sale_combos_and_sides -v
   ```

4. **Verify Concurrency Stress (50 threads)**:
   ```powershell
   pytest tests/test_milestone_m1.py::test_concurrent_checkout_no_collisions -v
   ```
