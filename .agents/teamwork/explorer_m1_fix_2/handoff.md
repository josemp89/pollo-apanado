# Investigation & Watertight Fix Strategy Report — Cart Item Quantity Vulnerability

**Agent**: Explorer 2 (`explorer_m1_fix_2`)  
**Target**: Milestone M1 Iteration 2 (Punto de Venta Checkout Data Integrity)  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Date**: 2026-10-21T02:18:00Z  
**Target Code**: `app/routers/pos.py:10-14`, `app/routers/pos.py:131-260`, `app/main.py:1-48`  

---

## 1. Observation

Direct code inspection and test execution confirmed the existence of a high-severity data integrity and financial exploitation vulnerability in `/api/pos/checkout`.

### 1.1 Unbounded CartItem Schema (`app/routers/pos.py:10-14`)
```python
10: class CartItem(BaseModel):
11:     product_id: int
12:     quantity: int
13:     chosen_presa: Optional[str] = None  # 'Pechuga', 'Muslo', 'Contramuslo', 'Ala'
```
- `quantity` is typed as a bare `int` with no minimum boundary (`gt=0`), allowing negative values (e.g. `-5`) and zero (`0`).

### 1.2 Missing Endpoint-Level Input Guard (`app/routers/pos.py:131-167`)
```python
131: @router.post("/checkout")
132: def process_checkout(payload: CheckoutRequest):
133:     if not payload.items:
134:         raise HTTPException(status_code=400, detail="El pedido está vacío.")
...
153:         for item in payload.items:
154:             product = cursor.execute("SELECT * FROM products WHERE id = ?", (item.product_id,)).fetchone()
...
164:             subtotal = product["price"] * item.quantity
165:             total_amount += subtotal
```
- The only cart-level check is `if not payload.items:`. There is no check verifying `item.quantity > 0`.
- For `item.quantity = -5` and `product["price"] = 9000`, `subtotal` becomes `-45,000`, and `total_amount` becomes `-45,000`.

### 1.3 Inventory Mathematical Inversion (`app/routers/pos.py:179-211`)
```python
179:         required_inventory = calculate_order_inventory_requirements(items_to_save)
...
189:             if row["stock"] < needed:
...
199:             cursor.execute("""
200:                 UPDATE inventory 
201:                 SET stock = stock - ?, updated_at = ?
202:                 WHERE item_key = ? AND stock >= ?
203:             """, (needed, now.isoformat(), item_key, needed))
```
- For `quantity = -5`, `needed = -5.0`.
- The preventative check `if row["stock"] < needed` evaluates `12.0 < -5.0` (False).
- In the SQL query:
  `SET stock = stock - (-5.0)` mathematically evaluates to `stock = stock + 5.0`.
  `WHERE ... AND stock >= -5.0` evaluates to True for any non-negative stock.
- Physical inventory is incremented by 5 units without butchering or kitchen production.

### 1.4 Fraudulent Cash Register Drainage (`app/routers/pos.py:212-224`)
```python
212:         change_returned = max(0, payload.cash_received - total_amount) if payload.payment_method == "efectivo" else 0
```
- With `total_amount = -45,000` and `cash_received = 0`:
  `change_returned = max(0, 0 - (-45000)) = +45,000 COP`.
- With `cash_received = 10,000`:
  `change_returned = max(0, 10000 - (-45000)) = +55,000 COP`.
- The system returns HTTP 200, persists negative sales into `sales` and `sale_items`, and instructs the cashier to dispense positive cash change.

### 1.5 Empirical Test Failure Reproduction (`tests/test_challenger_m1_2.py`)
Executing `pytest -v tests/test_challenger_m1_2.py::test_break_system_checkout_validation_defects` produced:
```
FAILED tests/test_challenger_m1_2.py::test_break_system_checkout_validation_defects - 
AssertionError: CRITICAL VULNERABILITY: Checkout accepted negative quantity (-5)! 
Status: 200, Response: {"success":true,"sale_id":1,"sale_code":"VTA-261020-0001",
"total_amount":-45000,"cash_received":0,"change_returned":45000,"payment_method":"efectivo",
"timestamp":"2026-10-20T21:14:48.484605","time_str":"21:14:48"}
assert 200 == 400
 +  where 200 = <Response [200 OK]>.status_code
```

### 1.6 FastAPI Schema Validation Status Code Behavior
- By default, FastAPI's parameter validation raises `fastapi.exceptions.RequestValidationError`, which produces **HTTP 422 Unprocessable Entity**.
- In the project's specification and test suite (`test_challenger_m1_2.py:405`), input validation failures are strictly expected to return **HTTP 400 Bad Request**.
- If `Field(gt=0)` is added to `CartItem` without an exception handler mapping `RequestValidationError` to HTTP 400, requests with `quantity = -5` return HTTP 422, causing `assert res_neg_qty.status_code == 400` to fail with `assert 422 == 400`.

---

## 2. Logic Chain

1. **Root Cause**: `CartItem.quantity` accepts non-positive integers because `CartItem` lacks schema constraints and `process_checkout` lacks defensive runtime bounds checks (Observation 1.1, 1.2).
2. **Mechanism of Exploitation**:
   - Supplying `quantity <= 0` generates non-positive requirements (`needed <= 0`).
   - Subtracting a negative number in SQL is equivalent to addition (`stock - (-qty) = stock + qty`).
   - The condition `stock >= needed` is trivially satisfied when `needed < 0` for any non-negative stock.
   - Consequently, unvalidated negative quantities bypass the non-negative stock floor, generating phantom inventory (Observation 1.3).
3. **Financial Compromise**:
   - Negative subtotals produce negative order totals (`total_amount < 0`).
   - The change formula `cash_received - total_amount` subtracts a negative number, resulting in positive cash change (`change_returned > 0`), which drains physical cash from the register and records negative sales figures in the financial ledger (Observation 1.4).
4. **Resolution Architecture (Defense-in-Depth)**:
   - **Schema Layer**: Enforce `quantity: int = Field(..., gt=0)` on `CartItem` so OpenAPI/Swagger and client contracts explicitly demand strictly positive integers.
   - **Gateway Error Mapping Layer**: Register a global `RequestValidationError` exception handler in `app/main.py` that converts schema validation failures into HTTP 400 responses with descriptive Spanish messages, ensuring compatibility with all automated test assertions and client expectations (Observation 1.6).
   - **Endpoint Runtime Layer**: Add explicit defensive checks in `process_checkout` verifying `item.quantity > 0`, `subtotal > 0`, and `total_amount > 0` with HTTP 400, guaranteeing protection even if internal or direct function calls bypass Pydantic parsing.
   - **Mathematical Core Layer**: Guard `calculate_order_inventory_requirements` to reject `qty <= 0` with a `ValueError`.

---

## 3. Caveats

- **Scope Boundary**: This investigation focuses strictly on the cart item quantity vulnerability and checkout data integrity (`/api/pos/checkout`). The concurrent race condition in `cancel_sale` is handled by Explorer 1 (`explorer_m1_fix_1`), and kitchen batch validation/SQLite DDL `CHECK` constraints are handled by Explorer 3 (`explorer_m1_fix_3`).
- **Cash Underpayment Guard**: While `cash_received >= total_amount` validation is formally scheduled for Milestone M2 (Feature 9), preventing negative `total_amount` is an immediate Milestone M1 data integrity prerequisite.

---

## 4. Conclusion & Watertight Fix Strategy

### 4.1 Recommended Concrete Changes

#### Change 1: Add Global Validation Exception Handler in `app/main.py`
In `app/main.py`, register an exception handler for `RequestValidationError` to return HTTP 400:

```python
# In app/main.py
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Add after creating app:
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

#### Change 2: Enforce Pydantic Bounds on `CartItem` in `app/routers/pos.py`
```python
# In app/routers/pos.py (lines 10-14)
from pydantic import BaseModel, Field

class CartItem(BaseModel):
    product_id: int = Field(..., gt=0, description="ID de producto debe ser mayor a 0")
    quantity: int = Field(..., gt=0, description="La cantidad debe ser estrictamente mayor a 0")
    chosen_presa: Optional[str] = None  # 'Pechuga', 'Muslo', 'Contramuslo', 'Ala'
```

#### Change 3: Add Server-Side Defensive Checks in `process_checkout` (`app/routers/pos.py`)
```python
# In app/routers/pos.py inside process_checkout (lines 131-167)
@router.post("/checkout")
def process_checkout(payload: CheckoutRequest):
    if not payload.items:
        raise HTTPException(status_code=400, detail="El pedido está vacío.")

    # Guard defensivo: rechazar cantidades menores o iguales a cero
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"La cantidad de cada producto debe ser mayor a 0. Recibido: {item.quantity}."
            )

    conn = get_db_connection()
    cursor = conn.cursor()
    ...
    # Dentro del ciclo de cálculo de subtotales:
    for item in payload.items:
        ...
        subtotal = product["price"] * item.quantity
        if subtotal <= 0 and product["price"] > 0:
            raise HTTPException(status_code=400, detail="Subtotal de producto inválido.")
        total_amount += subtotal
    ...
    # Guard defensivo: total de venta debe ser positivo
    if total_amount <= 0:
        raise HTTPException(status_code=400, detail="El total de la orden debe ser mayor a 0 COP.")
```

#### Change 4: Guard `calculate_order_inventory_requirements` in `app/routers/pos.py`
```python
# In app/routers/pos.py inside calculate_order_inventory_requirements (line 69)
    for item in items_data:
        sku = item["product_sku"]
        qty = float(item["quantity"])
        if qty <= 0:
            raise HTTPException(status_code=400, detail="La cantidad para cálculo de inventario debe ser mayor a 0.")
```

---

## 5. Verification Method

### 5.1 Automated Adversarial Regression Test
Run the targeted challenger test:
```powershell
pytest -v tests/test_challenger_m1_2.py -k "test_break_system_checkout_validation_defects"
```
**Expected Outcome**: **PASS**. Returns HTTP 400 for `quantity = -5`, `quantity = 0`, and invalid presa.

### 5.2 Direct API Call Verification
Execute via Python TestClient or cURL:
```powershell
python -c "
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
prods = client.get('/api/pos/products').json()
pec = next(p for p in prods if p['sku'] == 'POL-PEC')

# Test negative quantity
res_neg = client.post('/api/pos/checkout', json={'items': [{'product_id': pec['id'], 'quantity': -5}], 'payment_method': 'efectivo', 'cash_received': 0})
assert res_neg.status_code == 400, f'Expected 400, got {res_neg.status_code}'

# Test zero quantity
res_zero = client.post('/api/pos/checkout', json={'items': [{'product_id': pec['id'], 'quantity': 0}], 'payment_method': 'efectivo', 'cash_received': 0})
assert res_zero.status_code == 400, f'Expected 400, got {res_zero.status_code}'

print('All quantity bounds verified successfully!')
"
```

### 5.3 Invalidation Condition
If `POST /api/pos/checkout` returns HTTP 200, HTTP 422, or modifies `inventory` for any payload containing `quantity <= 0`, the remediation is invalid.
