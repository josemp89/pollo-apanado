# Handoff Report — Milestone M1 Adversarial Audit & Invariance Stress-Testing

**Agent**: Challenger 2 (`challenger_m1_2`)  
**Roles**: critic, specialist  
**Date**: 2026-10-21T02:10:00Z  
**Target Milestone**: M1 (Core Data Integrity & Concurrency)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Verdict**: **REQUEST_CHANGES**

---

## Challenge Summary

**Overall risk assessment**: **HIGH**

Empirical stress-testing of Milestone M1 confirmed that while sequential workflows and mathematical invariant calculations (`Initial + Entradas - Ventas + Anuladas = Final`) are implemented cleanly, adversarial stress tests uncovered two high-severity data integrity vulnerabilities:
1. **Race Condition in `cancel_sale` (Inventory Duplication)**: Concurrent cancellations of the same sale bypass the status check, executing multiple stock restorations and inflating physical inventory out of thin air.
2. **Unvalidated Cart Item Quantities (`quantity <= 0`)**: `process_checkout` accepts negative quantities (e.g. `quantity: -5`), creating negative sales totals, positive cash change, and injecting unverified stock directly into inventory.

---

## 1. Observation

All findings below were empirically reproduced using automated adversarial test harness `tests/test_challenger_m1_2.py`:

### 1.1 Race Condition in Sale Cancellation (`app/routers/pos.py:285-323`)
- **Direct Code Inspection (`app/routers/pos.py:289-322`)**:
  ```python
  sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
  if not sale:
      raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")

  if sale["status"] == "anulada":
      raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

  # Revertir inventario de forma simétrica
  items = cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
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
- **Empirical Execution**:
  Ran `pytest tests/test_challenger_m1_2.py -k "test_break_system_concurrent_cancel_sale_race_condition" -v`:
  ```
  FAILED tests/test_challenger_m1_2.py::test_break_system_concurrent_cancel_sale_race_condition - 
  AssertionError: RACE CONDITION IN CANCEL_SALE: Expected exactly 1 success, but 2 succeeded! 
  Statuses: [400, 400, 200, 400, 200, 400, 400, 400, 400, 400]
  assert 2 == 1
  ```
  - Initial `pechuga_vitrina` stock: 12.0
  - After selling 2 pechugas: 10.0
  - After 10 concurrent cancellation attempts of that single sale:
    - 2 (or more) requests returned HTTP 200.
    - Final stock: 14.0 (an unintended surplus of +2.0 units created out of nowhere).

### 1.2 Checkout Accepting Negative and Zero Quantities (`app/routers/pos.py:10-14, 153-210`)
- **Direct Code Inspection**:
  In `app/routers/pos.py:10-14`:
  ```python
  class CartItem(BaseModel):
      product_id: int
      quantity: int
      chosen_presa: Optional[str] = None
  ```
  In `app/routers/pos.py:153-210`, there is no validation that `item.quantity > 0`.
- **Empirical Execution**:
  Ran `pytest tests/test_challenger_m1_2.py -k "test_break_system_checkout_validation_defects" -v`:
  ```
  FAILED tests/test_challenger_m1_2.py::test_break_system_checkout_validation_defects - 
  AssertionError: CRITICAL VULNERABILITY: Checkout accepted negative quantity (-5)! 
  Status: 200, Response: {"success":true,"sale_id":1,"sale_code":"VTA-261020-0001",
  "total_amount":-45000,"cash_received":0,"change_returned":45000,"payment_method":"efectivo",...}
  ```
  - In `calculate_order_inventory_requirements`, `qty = -5.0` calculates `requirements['pechuga_vitrina'] = -5.0`.
  - `UPDATE inventory SET stock = stock - (-5)` executes `stock + 5`, artificially increasing physical inventory.
  - Generates negative transaction total (`-45000 COP`) and positive change returned (`45000 COP`).
  - If subsequent cancellation is triggered, `cancel_sale` executes `stock + (-5)`, which drains inventory without floor protection.

### 1.3 Verified Functionality (Passing Tests)
- `test_complex_workflow_and_closed_inventory_invariance`: **PASSED**
  - Workflow: Despiece (4 pollos) -> Fritura (2 lotes: 16 y 8 presas) -> Sales (Combos `POL-ENT`, `POL-14`, `POL-12`, Almuerzos con 4 tipos de presa, Porciones `POR-AREP`, `POR-PAPAS`, `POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, Gaseosas) -> Cancellations (Combos y Porciones) -> Re-orders.
  - Formula `Initial Stock + Entradas Despiece - Total Ventas Registradas + Ventas Anuladas == Final Physical Stock` verified across all 19 inventory keys with **0.00000 discrepancy**.
- `test_break_system_checkout_greater_than_stock`: **PASSED**
  - Blocked single-item over-requests with HTTP 400.
  - Multi-item carts where one item is deficient properly roll back without partial deductions.
  - Combos where a shared sub-component (papas) is depleted fail with HTTP 400.
- `test_break_system_cancellation_edge_cases`: **PASSED**
  - Non-existent sale ID (999999) -> HTTP 404.
  - Negative and zero sale IDs -> HTTP 404.
  - Sequential double and triple cancel -> HTTP 400 (`ya se encuentra anulada`).
- `test_break_system_despiece_edge_cases`: **PASSED**
  - `whole_chickens = 0` and `< 0` rejected with HTTP 400.
  - `whole_chickens > bodega stock` rejected with HTTP 400.
  - Despiece of exact available stock leaves bodega stock at 0.0.
  - Subsequent despiece with 0 bodega stock rejected with HTTP 400.
- `test_break_system_concurrent_competing_checkout_stock_floor`: **PASSED**
  - 10 threads competing for 3 pechugas: exactly 3 succeeded (200), exactly 7 failed (400), final stock exactly 0.0.
- `test_break_system_concurrent_competing_despiece_stock_floor`: **PASSED**
  - 10 threads competing for 3 bodega chickens: exactly 3 succeeded (200), exactly 7 failed (400), final bodega stock exactly 0.0, yields exactly 6 pechugas.

---

## 2. Logic Chain

1. **Inventory Invariance Breach via Cancellation Concurrency**:
   - Observations 1.1 show that `cancel_sale` performs a non-locking `SELECT * FROM sales WHERE id = ?`.
   - When multiple cancellation requests for the same sale execute concurrently (e.g., user double-clicks, network retry, client race), multiple transactions read `sale["status"] == "completada"`.
   - Each thread then proceeds to execute `UPDATE inventory SET stock = stock + ?` and finally sets `status = 'anulada'`.
   - Because `UPDATE sales SET status = 'anulada'` occurs after the inventory is updated rather than atomically guarding the entry, both threads commit, causing duplicate inventory restoration.
   - Consequently, physical inventory drifts higher than legitimate initial + despiece stock, violating the closed inventory invariant.

2. **Inventory and Financial Breach via Unvalidated Quantities**:
   - Observation 1.2 demonstrates that `CartItem.quantity` lacks a positive lower bound (`quantity > 0`).
   - Supplying negative integers generates negative requirements (`needed < 0`).
   - SQLite evaluates `stock - (-needed) = stock + needed` and satisfies `WHERE stock >= needed` unconditionally when `needed` is negative.
   - This allows an unauthorized client to manipulate stock levels and balance sheets.

3. **Conclusion Rationale**:
   - The system is architecturally solid in its mathematical modeling and sequential transaction flows, but cannot be approved for Milestone M1 completion while concurrent cancellation causes inventory duplication and negative quantities compromise stock integrity.
   - Therefore, the verdict is **REQUEST_CHANGES**.

---

## 3. Stress Test Results Summary

| Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|
| Closed Inventory Invariant (Multi-stage complex workflow) | 0.0 discrepancy across all 19 inventory keys | Exactly 0.0 discrepancy verified | **PASS** |
| Checkout with Qty > Available Stock | HTTP 400, atomic rollback | HTTP 400, 0 stock deducted | **PASS** |
| Multi-item Cart with Depleted Sub-item | HTTP 400, full rollback | HTTP 400, no partial deduction | **PASS** |
| Sequential Re-cancellation of Cancelled Sale | HTTP 400 "ya se encuentra anulada" | HTTP 400 "ya se encuentra anulada" | **PASS** |
| Cancellation of Non-Existent Sale ID | HTTP 404 | HTTP 404 | **PASS** |
| Despiece with whole_chickens <= 0 or > bodega stock | HTTP 400 | HTTP 400 | **PASS** |
| Competing Concurrent Checkouts for Limited Stock | Non-negative stock floor, exactly available count succeeds | 3 succeeded, 7 rejected, final stock 0.0 | **PASS** |
| Competing Concurrent Despiece for Limited Bodega Stock | Exactly bodega count succeeds | 3 succeeded, 7 rejected, final stock 0.0 | **PASS** |
| **Concurrent Cancellations of Same Sale** | **Exactly 1 success (200), 9 rejected (400)** | **2 succeeded (200), duplicate stock added** | **FAIL** |
| **Checkout with Negative Quantity (quantity = -5)** | **HTTP 400 rejection** | **HTTP 200, stock inflated, negative total** | **FAIL** |

---

## 4. Caveats

- **Scope Boundary**: Milestone M1 evaluation is strictly focused on backend data integrity, inventory invariance, concurrency, and validation. Frontend touch UI and cash change UI components are scheduled for Milestone M2.
- **No Production Code Modified**: As an adversarial reviewer, no implementation code in `app/` was altered. Only adversarial test fixtures in `tests/test_challenger_m1_2.py` were authored and executed.

---

## 5. Conclusion & Actionable Mitigations

**Verdict**: **REQUEST_CHANGES**

Worker M1 must address the following two concrete fixes:

### Action 1: Atomic Status Guard in `cancel_sale` (`app/routers/pos.py`)
Replace the deferred check in `cancel_sale` with an atomic conditioned status transition executed **before** restoring inventory:
```python
@router.post("/cancel-sale/{sale_id}")
def cancel_sale(sale_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Atomic transition guard: only transition if currently NOT 'anulada'
        cursor.execute("UPDATE sales SET status = 'anulada' WHERE id = ? AND status != 'anulada'", (sale_id,))
        if cursor.rowcount == 0:
            sale = cursor.execute("SELECT status, sale_code FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

        # Revertir inventario de forma simétrica (ejecutado únicamente por el hilo ganador)
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

        for item_key, qty in restorations.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock + ?, updated_at = ?
                WHERE item_key = ?
            """, (qty, now_str, item_key))

        conn.commit()
        return {"success": True, "message": f"Venta {sale_id} anulada y stock devuelto a vitrina/nevera."}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
```

### Action 2: Positive Quantity Validation in `process_checkout` (`app/routers/pos.py`)
In `app/routers/pos.py`, enforce that all cart items have `quantity > 0`:
```python
        for item in payload.items:
            if item.quantity <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="La cantidad de cada producto debe ser mayor a 0."
                )
```
Optionally also enforce `quantity: int = Field(..., gt=0)` in `CartItem`.

---

## 6. Verification Method

Once Worker M1 applies the two mitigations above, run the full test suite including the adversarial tests:

```powershell
pytest tests/test_milestone_m1.py tests/test_challenger_m1_2.py -v
```

**Passing Criteria**:
- All 17 tests (9 in `test_milestone_m1.py` and 8 in `test_challenger_m1_2.py`) pass with 0 failures and 0 errors.
- `test_break_system_concurrent_cancel_sale_race_condition` passes with exactly 1 success and 9 rejections.
- `test_break_system_checkout_validation_defects` passes with HTTP 400 on negative and zero quantities.
