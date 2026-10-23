# Reviewer 2 & Adversarial Critic Report — Milestone M1

**Agent**: Reviewer 2 (`reviewer_m1_2`)  
**Roles**: reviewer, critic  
**Target**: Milestone M1 (Core Data Integrity & Concurrency)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Verdict**: **REQUEST_CHANGES**  
**Overall Risk Assessment**: **HIGH**  

---

## 1. Observation

Direct code examination and empirical stress testing revealed the following concrete findings:

### 1.1 Verified Strengths & Integrity Conformance
1. **No Integrity Violations Detected**:
   - Source code in `app/database.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, and `tests/test_milestone_m1.py` contains genuine operational logic.
   - No hardcoded test responses, fake assertions, facade bypasses, or self-certifying shortcuts were found.
2. **SQLite WAL & Pragma Configuration**:
   - `app/database.py:12-15` properly sets `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=10000`, and `foreign_keys=ON`.
   - Verified via `PRAGMA` inspection: `journal_mode = 'wal'`, `synchronous = 1`, `busy_timeout = 10000`, `foreign_keys = 1`.
3. **Concurrency-Safe Sequence Generation**:
   - `order_counters` table with atomic `INSERT INTO ... ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING last_value` serializes `sale_code` and `batch_code` creation.
   - 50 concurrent checkout operations across 10 worker threads completed with 50 distinct codes and 0 collisions.
4. **High-Contention Rollback Handling**:
   - In a stress test allocating 10 items among 50 competing threads, exactly 10 transactions succeeded (HTTP 200) and 40 transactions cleanly failed (HTTP 400 with `Stock insuficiente...`) without any `database is locked` errors or transaction leaks. Final inventory reached exactly `0.0`.
5. **Symmetrical Sale Reversal**:
   - `calculate_order_inventory_requirements()` in `app/routers/pos.py:57-129` properly maps combos (`POL-14`, `POL-12`, `POL-ENT`), lunch specials (`ALM-COMP`), portions (`POR-AREP`, sides), and sodas.
   - Symmetrical cancellation restores 100% of deducted inventory with 0 drift.
   - Duplicate cancellation raises HTTP 400; non-existent sale ID raises HTTP 404.
6. **Despiece Mathematical Exactness**:
   - `app/routers/kitchen.py:42-126` verifies bodega chicken availability, deducts whole chickens, awards `2P + 2M + 2C + 2A + 2 Caldo`, and records full audit logs in `butchering_logs`. Non-positive input (`whole_chickens <= 0`) is rejected with HTTP 400.

---

### 1.2 Critical Adversarial Vulnerabilities & Defects

#### [Critical] Finding 1: Zero and Negative Quantities Allowed in Checkout (Inventory Inflation & Cash Leakage)
- **Where**: `app/routers/pos.py:10-13`, `app/routers/pos.py:153-176`, `app/routers/pos.py:198-211`.
- **What**:
  `CartItem` in `app/routers/pos.py:10-13` defines:
  ```python
  class CartItem(BaseModel):
      product_id: int
      quantity: int
      chosen_presa: Optional[str] = None
  ```
  Neither Pydantic validation (`Field(..., gt=0)`) nor endpoint logic validates that `item.quantity > 0`.
- **Why**:
  Empirical execution of:
  ```json
  {
    "items": [{"product_id": 1, "quantity": -5}],
    "payment_method": "efectivo",
    "cash_received": 10000
  }
  ```
  returned HTTP 200:
  ```json
  {
    "success": true,
    "sale_id": 2,
    "sale_code": "VTA-261020-0002",
    "total_amount": -45000,
    "cash_received": 10000,
    "change_returned": 55000,
    "payment_method": "efectivo"
  }
  ```
  **Direct Business & Data Impact**:
  1. **Stock Inflation / Phantom Inventory**:
     - `calculate_order_inventory_requirements()` yields `{'pechuga_vitrina': -5.0}`.
     - The database executes `UPDATE inventory SET stock = stock - (-5) WHERE item_key = 'pechuga_vitrina' AND stock >= -5`.
     - `pechuga_vitrina` stock jumped from `12.0` to `17.0` without any butchering or supplier input!
  2. **Cash Extraction & Negative Ledger**:
     - The sale was recorded with `total_amount = -45000`.
     - Cash change was calculated as `cash_received - (-45000) = 10000 + 45000 = 55000 COP`.
     - A rogue cashier or corrupted client can drain cash from the register and create fake inventory.
  3. **Zero Quantity Transactions**:
     - When `quantity = 0`, the endpoint returns HTTP 200, creates a 0 COP sale, and pollutes `sale_items` with useless 0-quantity rows.
- **Suggested Fix**:
  In `app/routers/pos.py`:
  ```python
  from pydantic import BaseModel, Field

  class CartItem(BaseModel):
      product_id: int
      quantity: int = Field(..., gt=0, description="La cantidad debe ser mayor a 0")
      chosen_presa: Optional[str] = None
  ```
  And in `process_checkout`:
  ```python
  for item in payload.items:
      if item.quantity <= 0:
          raise HTTPException(status_code=400, detail="La cantidad de cada producto debe ser mayor a 0.")
  ```

---

#### [Major] Finding 2: Unvalidated Stage and Negative Presas in Kitchen Batch Timer
- **Where**: `app/routers/kitchen.py:14-19`, `app/routers/kitchen.py:157-220`.
- **What**:
  `BatchTimerRequest` has no validation constraints on `stage` or `total_presas`.
- **Why**:
  Empirical execution of:
  ```json
  {"stage": "invalid_nonexistent_stage", "total_presas": -10}
  ```
  returned HTTP 200, creating batch code `LOTE-INV-2010-001` with `-10` presas and a default duration of 4.0 hours in `cooking_batches`.
- **Suggested Fix**:
  In `app/routers/kitchen.py`:
  ```python
  VALID_STAGES = {"salmuera", "adobo", "fritura"}
  if payload.stage not in VALID_STAGES:
      raise HTTPException(status_code=400, detail=f"Etapa inválida '{payload.stage}'. Debe ser una de: {list(VALID_STAGES)}")
  if payload.total_presas <= 0:
      raise HTTPException(status_code=400, detail="El total de presas debe ser mayor a 0.")
  if payload.duration_hours is not None and payload.duration_hours <= 0:
      raise HTTPException(status_code=400, detail="La duración debe ser mayor a 0 horas.")
  ```

---

#### [Minor] Finding 3: Daily Batch Counter Initialized from Lifetime Cooking Batches
- **Where**: `app/routers/kitchen.py:27-35`.
- **What**:
  `get_next_batch_code` formats `counter_name = f"batch_{now.strftime('%Y-%m-%d')}"`, but initializes `last_value` using `(SELECT COALESCE(COUNT(*), 0) FROM cooking_batches) + 1`.
- **Why**:
  Because `cooking_batches` stores all lifetime batches and does not have a separate `date_str` column, a new day will not start at sequence `001`. Rather, it starts at `(total_lifetime_batches + 1)`.
- **Suggested Fix**:
  Either use a unified global counter name `batch_sequence` or filter `cooking_batches` by current date `started_at LIKE ?` when computing the initial count.

---

## 2. Logic Chain

1. **Integrity Chain**:
   - We inspected all lines of `app/database.py`, `app/routers/pos.py`, and `app/routers/kitchen.py`.
   - All tests in `tests/test_milestone_m1.py` dynamically exercise database transactions in temporary SQLite instances. No mocked or hardcoded test returns were found. Therefore, no integrity violation exists.
2. **Adversarial Input Chain**:
   - The system contract requires a "Non-Negative Stock Floor" and "Core Data Integrity".
   - The formula `stock = stock - needed` with condition `stock >= needed` is mathematically inverted when `needed < 0`: subtracting a negative number adds to the stock (`stock - (-5) = stock + 5`), and `stock >= -5` is trivially satisfied for any non-negative stock.
   - Consequently, sending negative quantities bypasses the non-negative stock floor, generates negative ticket totals, extracts cash change, and creates phantom inventory.
3. **Verdict Deduction**:
   - A system cannot be certified for Milestone M1 (Core Data Integrity & Concurrency) while allowing negative item quantities that corrupt inventory and cash balances.
   - Therefore, the verdict must be **REQUEST_CHANGES** until input bounds are enforced.

---

## 3. Caveats

- **Scope Boundary**: Frontend UI elements (disabling zero-stock buttons, touch keypad layout) are designated for Milestone M2. This review evaluated backend data integrity, concurrency, and validation rules.
- **Cash Underpayment**: In `pos.py:212`, `change_returned` computes `max(0, payload.cash_received - total_amount)`. While strict underpayment rejection (`cash_received >= total_amount`) is planned for M2 (Feature 9), allowing negative `total_amount` due to negative item quantities is an immediate M1 data integrity defect.

---

## 4. Conclusion

Milestone M1 represents high quality in its SQLite WAL configuration, atomic sequence generation under concurrency, and symmetrical inventory restoration for complex combos.

However, adversarial stress testing revealed a **Critical data integrity vulnerability**:
- Unchecked negative item quantities in `/api/pos/checkout` inflate vitrina inventory without butchering and yield negative order totals with positive change payouts.
- Unchecked kitchen batch stages and presas in `/api/kitchen/batch-timer` allow garbage data into `cooking_batches`.

**Verdict**: **REQUEST_CHANGES**.

---

## 5. Verification Method

To independently reproduce and verify both the passing behaviors and the identified defects:

1. **Run Base Test Suite**:
   ```powershell
   pytest -v
   ```
   *Result*: 9 passed in ~0.9s.

2. **Run Adversarial Input Test**:
   ```powershell
   python .agents\teamwork\reviewer_m1_2\test_adversarial.py
   ```
   *Expected defect confirmation*:
   - Section 2: Returns HTTP 200 for quantity `-5`, increases `pechuga_vitrina` from `12.0` to `17.0`, and outputs `total_amount: -45000, change_returned: 55000`.
   - Section 6 & 7: Returns HTTP 200 for negative presas and invalid stage.

3. **Run Concurrent Rollback Stress Test**:
   ```powershell
   python .agents\teamwork\reviewer_m1_2\test_concurrent_rollback.py
   ```
   *Expected outcome*: 10 successes, 40 clean rollbacks, 0 locks, 0 inventory drift.

4. **Invalidation Condition**:
   Once input validation (`quantity > 0`, `stage in (...)`, `total_presas > 0`) is implemented by the worker, `test_adversarial.py` must reject negative/zero items and invalid batches with HTTP 400.
