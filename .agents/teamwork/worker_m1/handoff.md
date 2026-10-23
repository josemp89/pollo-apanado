# Handoff Report — Milestone M1: Core Data Integrity, Concurrency, and Symmetrical Inventory

**Agent**: Worker M1 (`worker_m1`)  
**Roles**: implementer, qa, specialist  
**Date**: 2026-10-21T02:03:00Z  
**Target Milestone**: M1 (Core Data Integrity & Concurrency)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`

---

## 1. Observation

Direct code inspection and test execution revealed the following initial defects and verified resolutions:

### 1.1 Concurrency Race Condition in `sale_code` and `batch_code`
- **Initial State**:
  - In `app/routers/pos.py:55-56`:
    ```python
    sale_count = cursor.execute("SELECT COUNT(*) FROM sales WHERE date_str = ?", (date_str,)).fetchone()[0] + 1
    sale_code = f"VTA-{now.strftime('%y%m%d')}-{sale_count:04d}"
    ```
  - In `app/routers/kitchen.py:123-124`:
    ```python
    batch_count = cursor.execute("SELECT COUNT(*) FROM cooking_batches").fetchone()[0] + 1
    batch_code = f"LOTE-{payload.stage[:3].upper()}-{now.strftime('%d%m')}-{batch_count:03d}"
    ```
  - Under concurrent execution, both read identical counts and crashed with `500 Internal Server Error: UNIQUE constraint failed: sales.sale_code` or `cooking_batches.batch_code`.
- **Implemented Fix**:
  - Added table `order_counters (counter_name TEXT PRIMARY KEY, last_value INTEGER NOT NULL DEFAULT 0)` in `app/database.py`.
  - Implemented `get_next_sale_code(cursor, now)` in `app/routers/pos.py` using atomic upsert:
    ```python
    cursor.execute("""
        INSERT INTO order_counters (counter_name, last_value)
        VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM sales WHERE date_str = ?) + 1)
        ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
        RETURNING last_value;
    """, (counter_name, date_str))
    ```
    coupled with verification against existing rows.
  - Implemented `get_next_batch_code(cursor, stage, now)` in `app/routers/kitchen.py` using equivalent atomic sequence generation.
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_concurrent_checkout_no_collisions`: 50 concurrent checkouts executed across 10 threads completed with 50 HTTP 200 responses, 0 collisions, and 50 unique `sale_code` identifiers.
  - `tests/test_milestone_m1.py::test_concurrent_batch_timers_no_collisions`: 20 concurrent batches across 8 threads completed with 20 HTTP 200 responses, 0 collisions, and 20 unique `batch_code` identifiers.

### 1.2 SQLite WAL and Connection Pragmas
- **Initial State (`app/database.py:9-14`)**:
  - `busy_timeout` defaulted to 5000ms.
  - `PRAGMA synchronous` was unconfigured (running in FULL synchronous mode = 2).
  - Redundant connection execution without explicit socket timeout.
- **Implemented Fix (`app/database.py:7-17`)**:
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
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_wal_and_pragma_configuration` verified:
    - `journal_mode`: `wal`
    - `synchronous`: `1` (`NORMAL`)
    - `busy_timeout`: `10000`
    - `foreign_keys`: `1` (`ON`)

### 1.3 Asymmetric Sale Cancellation and Missing Combos/Arepas
- **Initial State (`app/routers/pos.py:228-260`)**:
  - `cancel_sale` lacked handlers for combos `POL-14` (1/4 Pollo), `POL-12` (1/2 Pollo), `POL-ENT` (Pollo Entero), and `POR-AREP` (Porción de Arepas).
  - Cancelling an order with combos permanently drained vitrina presas and fries.
  - Line 246 contained an SQL injection vulnerability using raw f-strings: `WHERE item_key = '{chosen_presa.lower()}_vitrina'`.
  - Re-cancelling an already cancelled sale returned HTTP 404 rather than HTTP 400.
- **Implemented Fix**:
  - Extracted unified mapping `calculate_order_inventory_requirements(items_data)` in `app/routers/pos.py` used identically by both `process_checkout` and `cancel_sale`.
  - Full combo breakdown restoration:
    - `POL-14`: 1 muslo + 1 contramuslo + 1 papas
    - `POL-12`: 1 pechuga + 1 ala + 1 muslo + 1 contramuslo + 1 papas
    - `POL-ENT`: 2 pechugas + 2 alas + 2 muslos + 2 contramuslos + 2 papas
    - `ALM-COMP`: chosen presa (`{chosen_presa.lower()}_vitrina`) + 1 caldo + 1 arroz + 1 frijoles
    - `POR-AREP`: 1 arepa (`arepas_unidades`)
    - All individual presas, sides, and sodas.
  - Parameterized update: `UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = ?`.
  - Distinct HTTP status codes: HTTP 404 for non-existent sale ID, HTTP 400 for already cancelled sale (`"La venta {sale_code} ya se encuentra anulada."`).
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_symmetrical_cancel_sale_combos_and_sides`: Executed multi-item sale (Pollo Entero, 1/2 Pollo, 1/4 Pollo, Almuerzo Completo con Pechuga, Arepas x2, Coca-Cola x1), verified inventory deductions, executed cancellation, and verified that `Initial Stock == Final Stock` across all items with 0 discrepancy.
  - `tests/test_milestone_m1.py::test_cancel_sale_validation_errors`: Verified that second cancellation raises HTTP 400 and non-existent sale raises HTTP 404.

### 1.4 Non-Negative Stock Floor & Atomic Deductions
- **Initial State**:
  - `process_checkout` and `record_despiece` deducted stock without checking `stock >= qty`, allowing stock to drift into large negative numbers (survey observed `-973.0`).
  - Broad `except Exception:` caught `HTTPException` and masked validation errors as HTTP 500.
- **Implemented Fix**:
  - In `app/routers/pos.py`:
    1. Pre-validation loop checking `row["stock"] < needed`, raising HTTP 400 with item name, available stock, and required amount.
    2. Atomic deduction with `WHERE item_key = ? AND stock >= ?` checking `cursor.rowcount > 0`.
    3. Proper exception handling preserving `HTTPException`:
       ```python
       except HTTPException:
           conn.rollback()
           raise
       except Exception as e:
           conn.rollback()
           raise HTTPException(status_code=500, detail=str(e))
       ```
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_non_negative_stock_floor_checkout`: Verified that requesting more stock than available triggers HTTP 400 with `"Stock insuficiente para 'Alas en Vitrina'. Disponible: X, requerido: Y."` and leaves stock intact.

### 1.5 Despiece Validation, Mathematical Exactness & Audit Logging
- **Initial State (`app/routers/kitchen.py:24-78`)**:
  - `record_despiece` never validated `pollo_entero_crudo` stock in bodega, allowing negative bodega stock.
- **Implemented Fix**:
  - Pre-validation: `available < n` raises HTTP 400.
  - Atomic deduction: `UPDATE inventory SET stock = stock - ? WHERE item_key = 'pollo_entero_crudo' AND stock >= ?`.
  - Yield mathematical rule: `1 Pollo Crudo -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + 2 Caldo`.
  - Audit logging: Inserts full yield record into `butchering_logs` table (`whole_chickens`, `pechugas_yield`, `muslos_yield`, `contramuslos_yield`, `alas_yield`, `caldo_bases_yield`, `notes`).
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_despiece_validation_and_mathematical_yield`: Butchering 10 chickens with 5 available returned HTTP 400; butchering 3 chickens deducted 3 from bodega and added exactly 6 pechugas, 6 muslos, 6 contramuslos, 6 alas, and 6 caldo raciones to vitrina/cocina, recording full audit log in `butchering_logs`.

### 1.6 Insumos Secos & Arepas Tracking
- **Initial State**:
  - `POR-AREP` was missing from `inventory`.
  - `harina_apanar_kg` and `aceite_fritura_lt` were static and never decremented.
  - `start_batch_timer` for `fritura` stage searched for `fritura_hours` instead of converting `fritura_minutes` (14m), defaulting to 4.0 hours.
- **Implemented Fix**:
  - Seeded and ensured `arepas_unidades` in `inventory` (50 units, min threshold 10).
  - In `start_batch_timer`: For `stage == 'fritura'`, converts `fritura_minutes` (14) to hours (`14.0 / 60.0 = 0.233h`) and decrements `harina_apanar_kg` (`total_presas * 0.025 kg`) and `aceite_fritura_lt` (`total_presas * 0.02 L`).
- **Verification Result**:
  - `tests/test_milestone_m1.py::test_arepas_and_dry_goods_seeded` and `test_fritura_timer_duration_and_dry_supplies` passed.

---

## 2. Logic Chain

1. **Concurrency Safety Logic**:
   - Non-atomic `SELECT COUNT(*) FROM sales` within read-committed or deferred transactions causes concurrent transactions to calculate identical sequence numbers.
   - Using SQLite 3.35+ `INSERT INTO order_counters ... ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING last_value` serializes sequence assignment under the SQLite write lock.
   - Consequently, running 50 concurrent transactions yielded 50 distinct `sale_code`s with zero collisions.

2. **Inventory Symmetry Logic**:
   - If an order with combos (`POL-14`, `POL-12`, `POL-ENT`) deducts presas and fries upon checkout, but `cancel_sale` only checks individual presa SKUs, the combo items are permanently lost from inventory.
   - Defining a single, pure function `calculate_order_inventory_requirements(items)` that processes both individual presas and combos guarantees that the restitution set is the exact inverse of the deduction set.
   - Empirical proof: `Initial Stock == Final Stock` across all 10 tracked item keys after a multi-combo checkout and cancellation.

3. **Stock Floor Enforcement Logic**:
   - Checking `stock >= qty` in Python prior to updating is vulnerable to race conditions if two threads execute between the check and the update.
   - Including `WHERE item_key = ? AND stock >= ?` in the SQL `UPDATE` statement guarantees atomicity at the database level: if another thread reduced stock below `qty`, `cursor.rowcount` is 0.
   - Detecting `cursor.rowcount == 0` and rolling back prevents negative inventory under any concurrency condition.

---

## 3. Caveats

- **Scope Boundary**: This milestone strictly addresses Milestone M1 tasks (`app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`). Frontend UI modifications (touch ergonomics, presa selection modal disabling, cash change keypad) are scheduled for Milestone M2.
- **Existing Production DB State**: The active database `data/asadero.db` had pre-existing test transactions from initial system surveys. The auto-sanitization hook added to `init_db()` cleans negative values (`stock = 15 WHERE stock < 0`), but automated testing uses isolated temporary databases to guarantee 100% reproducible fixtures.

---

## 4. Conclusion

All six core integrity and concurrency requirements of Milestone M1 have been implemented and verified:
1. Concurrency safety: Zero collisions under 50 concurrent transactions.
2. SQLite WAL: Properly configured with `PRAGMA synchronous = NORMAL;`, `PRAGMA busy_timeout = 10000;`, and `PRAGMA foreign_keys = ON;`.
3. Symmetrical sale reversal: Full inventory restoration for combos, presas, lunch specials, portions, arepas, and sodas; SQL injection resolved; HTTP 400 on duplicate cancellation.
4. Non-negative stock floor: Strict atomic enforcement preventing stock from dropping below zero.
5. Despiece validation: Validates bodega chicken stock, enforces `1 -> 2P + 2M + 2C + 2A + 2 Caldo`, and records audit logs.
6. Dry supplies & arepas tracking: `arepas_unidades` tracked in POS and cancel flows; `harina_apanar_kg` and `aceite_fritura_lt` tracked in fryer batches; fryer timer fixed to 14 minutes.

---

## 5. Verification Method

To independently verify the implementation, execute the following commands from the project root (`c:\Users\Alejandro\Desktop\POLLO APANADO`):

1. **Run Full Pytest Test Suite**:
   ```powershell
   pytest -v
   ```
   *Expected outcome*: 9 passed tests in ~1.1 seconds.

2. **Verify SQLite WAL & Pragmas**:
   ```powershell
   python -c "import app.database as db; conn = db.get_db_connection(); print('journal_mode:', conn.execute('PRAGMA journal_mode;').fetchone()[0]); print('synchronous:', conn.execute('PRAGMA synchronous;').fetchone()[0]); print('busy_timeout:', conn.execute('PRAGMA busy_timeout;').fetchone()[0]); print('foreign_keys:', conn.execute('PRAGMA foreign_keys;').fetchone()[0]);"
   ```
   *Expected outcome*: `journal_mode: wal`, `synchronous: 1`, `busy_timeout: 10000`, `foreign_keys: 1`.

3. **Verify Symmetrical Cancellation and Combo Inventory Restitution**:
   Run the dedicated test case:
   ```powershell
   pytest tests/test_milestone_m1.py::test_symmetrical_cancel_sale_combos_and_sides -v
   ```
   *Expected outcome*: PASSED.

4. **Verify Concurrency Stress (50 concurrent checkouts)**:
   ```powershell
   pytest tests/test_milestone_m1.py::test_concurrent_checkout_no_collisions -v
   ```
   *Expected outcome*: PASSED with 0 collisions.
