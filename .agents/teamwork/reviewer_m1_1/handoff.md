# Review & Adversarial Challenge Report — Milestone M1

**Verdict**: **REQUEST_CHANGES**  
**Reviewer**: Reviewer 1 (`reviewer_m1_1`)  
**Roles**: Reviewer, Adversarial Critic  
**Date**: 2026-10-21T02:12:00Z  
**Reviewed Artifacts**:
- `app/database.py`
- `app/routers/pos.py`
- `app/routers/kitchen.py`
- `tests/test_milestone_m1.py`
- Worker Handoff: `.agents/teamwork/worker_m1/handoff.md`

---

## Executive Summary

While Worker M1 successfully implemented core concurrency mechanisms for sequence numbers, WAL mode, despiece tracking, and mathematical decomposition of combos, adversarial stress-testing identified **two critical integrity and race-condition vulnerabilities** that violate system invariants:

1. **[CRITICAL] Race Condition in `cancel_sale`**: Concurrent requests to cancel the same sale bypass the status check and multiply returned inventory. In empirical testing, 10 concurrent cancellation requests for a single sale of 1 Pollo Entero restored **+20 pechugas instead of +2**, corrupting physical inventory counts.
2. **[CRITICAL] Negative Cart Quantities Exploit**: `CartItem.quantity` is unvalidated. Submitting negative quantities (e.g., `quantity: -5`) succeeds with HTTP 200, artificially generates stock (`stock = stock - (-5)`), produces a negative bill, and triggers fraudulent cash return payouts (`change_returned`).

Until these two vulnerabilities are remediated, Milestone M1 **CANNOT** be approved for production.

---

## 1. Observation

Direct code analysis, test execution, and adversarial attack scripts produced the following empirical observations:

### 1.1 Test Suite Baseline
- Command: `pytest -v`
- Result: 9 passed, 3 deprecation warnings in 0.85s.
- Existing tests cover nominal workflows for WAL pragmas, seeded goods, concurrent checkouts, concurrent batch timers, single-threaded cancellation symmetry, despiece yields, and fryer timer duration.

### 1.2 Inspection of Concurrency & `order_counters` (`app/routers/pos.py:39-56`, `app/routers/kitchen.py:24-41`)
- **Observation**:
  `get_next_sale_code` uses SQLite UPSERT (`INSERT ... ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING last_value`).
  Under an adversarial test of 100 rapid concurrent checkouts across 20 worker threads, all 100 checkouts succeeded with HTTP 200 in 1.13s, producing 100 unique, strictly monotonic `sale_code` values without database lock timeouts (`busy_timeout=10000`).
  When a transaction aborts (e.g., validation failure), SQLite rolls back the counter increment atomically, preventing sequence number leaks.

### 1.3 Inspection of WAL Pragmas (`app/database.py:7-16`)
- **Observation**:
  `conn.execute("PRAGMA journal_mode=WAL;")`, `conn.execute("PRAGMA synchronous=NORMAL;")`, `conn.execute("PRAGMA busy_timeout=10000;")`, and `conn.execute("PRAGMA foreign_keys=ON;")` are executed on every connection.
  Empirical inspection confirmed active WAL and SHM files (`asadero.db-wal`, `asadero.db-shm`) and correct PRAGMA query returns (`wal`, `1`, `10000`, `1`).

### 1.4 Inspection of `cancel_sale` (`app/routers/pos.py:286-324`)
- **Observation (Vulnerability Found)**:
  `cancel_sale` reads sale status at line 290:
  ```python
  sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
  if sale["status"] == "anulada":
      raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")
  ```
  And updates sales status to `'anulada'` at line 321:
  ```python
  cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ?", (sale_id,))
  ```
  AFTER iterating through `restorations.items()` and incrementing inventory.
- **Empirical Stress Test**:
  Executed 10 concurrent requests to cancel the exact same completed sale (`POL-ENT`, 1 unit = 2 pechugas, 2 alas, 2 muslos, 2 contramuslos, 2 papas).
  - *Expected*: Exactly 1 request returns HTTP 200; 9 requests return HTTP 400. Final pechuga stock increases by +2.
  - *Actual*: **ALL 10 requests returned HTTP 200!** Pechuga stock increased from 10.0 to 30.0 (**+20 pechugas**).

### 1.5 Inspection of Cart Item Validation (`app/routers/pos.py:10-14, 153-176`)
- **Observation (Vulnerability Found)**:
  `CartItem` defines `quantity: int` with no minimum bound.
  Neither `CartItem` nor `process_checkout` checks `item.quantity > 0`.
- **Empirical Attack Test**:
  Sent `POST /api/pos/checkout` with `items: [{"product_id": ala_id, "quantity": -5}]`, `payment_method: "efectivo"`, `cash_received: 10000`.
  - *Result*: HTTP 200 OK.
  - *Total amount*: `-$45,000` COP.
  - *Change returned*: `+$55,000` COP (`max(0, 10000 - (-45000))`).
  - *Inventory*: Ala stock increased by **+5 units** (`stock = stock - (-5)`).

### 1.6 Inspection of Despiece & Mathematical Yields (`app/routers/kitchen.py:42-126`)
- **Observation**:
  `record_despiece` validates `whole_chickens > 0`, checks available bodega stock, performs atomic deduction with `WHERE stock >= n`, calculates exact yields (`2P, 2M, 2C, 2A, 2 Caldo` per chicken), updates kitchen/vitrina stock, and records complete audit logs in `butchering_logs`.
  Adversarial test with 2 concurrent requests butchering 3 chickens each when only 5 existed resulted in 1 success (stock 5 -> 2) and 1 rejection (HTTP 400), with exactly 1 audit log created.

---

## 2. Logic Chain

1. **`cancel_sale` Concurrency Vulnerability**:
   - In SQLite/Python with default transaction handling, `SELECT` executes in shared read mode.
   - Multiple concurrent threads calling `POST /api/pos/cancel-sale/{sale_id}` execute `SELECT * FROM sales WHERE id = ?` before any write lock is acquired.
   - At the time of reading, `sale["status"]` is still `'completada'` in all threads.
   - Each thread then executes `UPDATE inventory SET stock = stock + ?`, which SQLite serializes.
   - Each thread then unconditionally runs `UPDATE sales SET status = 'anulada' WHERE id = ?` without verifying whether `status` was already updated by a preceding thread.
   - Consequently, all threads commit, multiplying the restored stock by the number of concurrent requests.

2. **Negative Quantity Exploit Logic**:
   - In `process_checkout`, inventory requirements are computed as `needed = qty`.
   - If `quantity` is negative (e.g. `-5`), `needed = -5.0`.
   - The query `UPDATE inventory SET stock = stock - (-5) WHERE item_key = ? AND stock >= -5` mathematically evaluates to `stock = stock + 5`.
   - The predicate `stock >= -5` evaluates to true for any non-negative stock.
   - Therefore, negative quantities bypass stock floors, inflate inventory without butchering, and allow fraudulent cash register drainage via negative billing.

---

## 3. Findings & Required Remediation

### [Critical] Finding 1: Race Condition in `cancel_sale` Causing Inventory Duplication
- **File**: `app/routers/pos.py`, lines 286–324
- **Problem**: Double/concurrent cancellation requests duplicate restored stock.
- **Remediation**:
  Make the status transition atomic and conditional before or during inventory restoration. Use `rowcount` validation:
  ```python
  cursor.execute(
      "UPDATE sales SET status = 'anulada' WHERE id = ? AND status != 'anulada'",
      (sale_id,)
  )
  if cursor.rowcount == 0:
      # If the sale was already cancelled or doesn't exist
      sale = cursor.execute("SELECT status FROM sales WHERE id = ?", (sale_id,)).fetchone()
      if not sale:
          raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
      raise HTTPException(status_code=400, detail=f"La venta con ID {sale_id} ya se encuentra anulada.")
  ```
  Only if `cursor.rowcount == 1` should the loop execute `UPDATE inventory SET stock = stock + ?`.

### [Critical] Finding 2: Missing `quantity > 0` Validation Allows Inventory Inflation & Cash Drainage
- **File**: `app/routers/pos.py`, lines 10–14 and 153–177
- **Problem**: Negative or zero item quantities are accepted, creating phantom stock and draining money.
- **Remediation**:
  Enforce positive integer quantities in Pydantic schema and in `process_checkout`:
  ```python
  from pydantic import Field

  class CartItem(BaseModel):
      product_id: int
      quantity: int = Field(gt=0, description="La cantidad debe ser mayor a 0.")
      chosen_presa: Optional[str] = None
  ```
  Additionally, add defensive check inside the item loop:
  ```python
  if item.quantity <= 0:
      raise HTTPException(status_code=400, detail="La cantidad de cada ítem debe ser mayor a 0.")
  ```

### [Major] Finding 3: Absence of Engine-Level `CHECK (stock >= 0)` in SQLite DDL
- **File**: `app/database.py`, lines 40–50
- **Problem**: The `inventory` table definition lacks `CHECK (stock >= 0)`.
- **Remediation**:
  Update table DDL to enforce non-negative stock at the database engine level:
  ```sql
  CREATE TABLE IF NOT EXISTS inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_key TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      category TEXT NOT NULL,
      stock REAL DEFAULT 0 CHECK (stock >= 0),
      unit TEXT NOT NULL,
      min_threshold REAL DEFAULT 5,
      updated_at TEXT
  );
  ```

### [Minor] Finding 4: Unvalidated Stage and Presa Count in `start_batch_timer`
- **File**: `app/routers/kitchen.py`, lines 14–19, 157–185
- **Problem**: `BatchTimerRequest.stage` is not restricted to `('salmuera', 'adobo', 'fritura')`, and `total_presas` is not validated to be `> 0`.
- **Remediation**:
  Validate `stage in ('salmuera', 'adobo', 'fritura')` and `total_presas > 0`.

---

## 4. Caveats

- **Scope Adherence**: In accordance with the Reviewer Protocol, no implementation files (`app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`) were modified by this reviewer. Remediation must be executed by Worker M1.
- **Automated Tests**: Worker M1 must add dedicated test cases for concurrent `cancel_sale` and negative quantity checkout in `tests/test_milestone_m1.py` to prevent regression.

---

## 5. Conclusion

**Verdict: REQUEST_CHANGES**

Worker M1 implemented solid foundations for `order_counters` atomicity, WAL connection pragmas, symmetrical combo breakdown mapping, and despiece audit logging. However, the discovery of the **`cancel_sale` concurrent duplication vulnerability** and the **negative quantity inventory exploit** compromises system integrity.

Worker M1 must address Findings 1, 2, and 3, add corresponding automated regression tests, and resubmit for certification.

---

## 6. Verification Method

To reproduce the findings and verify future fixes:

1. **Reproduce Concurrent `cancel_sale` Duplication**:
   Run the following test script:
   ```python
   # Run 10 concurrent cancellations on the same sale
   # If more than one request returns 200, or if inventory is restored > 1x, the bug persists.
   ```
2. **Reproduce Negative Quantity Checkout Exploit**:
   ```powershell
   # Send POST /api/pos/checkout with quantity = -5
   # Expected: HTTP 422 or HTTP 400.
   # Bug confirmed if: HTTP 200 is returned.
   ```
3. **Verify Standard Test Suite**:
   ```powershell
   pytest -v
   ```
