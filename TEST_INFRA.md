# E2E Testing Infrastructure — Pollo Apanado

## 1. Architectural Overview

The testing infrastructure for "Pollo Apanado" is engineered for high-concurrency, requirement-driven, opaque-box testing. It guarantees complete test isolation, mathematical inventory auditability, and safety against production database mutation.

- **Test Framework**: `pytest` (v9.1.1) with Python 3.12.
- **HTTP Client**: `fastapi.testclient.TestClient` powered by Starlette / AnyIO.
- **Database Engine**: Isolated SQLite database per test run utilizing Write-Ahead Logging (`WAL`), `synchronous=NORMAL`, `busy_timeout=10000`, and `foreign_keys=ON`.
- **Database Isolation Strategy**: Every test session and test case dynamically creates a temporary SQLite file in a fresh `tmp_path` directory. The module-level `app.database.DB_PATH` is monkeypatched to point exclusively to the isolated temporary file, and `init_db()` is invoked to bootstrap fresh tables and initial seed data. Under no circumstances is `data/asadero.db` touched or mutated.
- **Cross-Platform Console Compatibility**: Clean UTF-8 formatting and standard Spanish/English status messages without unhandled Unicode emojis that cause charmap decoding exceptions (`charmap codec can't encode character`) on default Windows CP1252 consoles.

---

## 2. Test Suite Architecture (4 Tiers + Concurrency Stress)

The test suite consists of 81 tests structured into 5 dedicated modules:

```
tests/
├── conftest.py                   # Global fixtures, DB isolation, TestClient, and DB helpers
├── test_tier1_features.py        # Tier 1: Feature Coverage (57 tests)
├── test_tier2_boundaries.py      # Tier 2: Boundary & Corner Cases (16 tests)
├── test_tier3_cross_features.py  # Tier 3: Cross-Feature Combinations (5 tests)
├── test_tier4_lunch_rush.py      # Tier 4: Real-World High-Volume Lunch Rush (1 test / 55 txs)
└── test_concurrency_stress.py    # Concurrency Stress Tests (2 tests / 50+ concurrent checkouts)
```

### Tier 1: Feature Coverage (`tests/test_tier1_features.py`) — 57 Tests
Guarantees at least 5 tests per feature across requirements R1 through R5:
1. **Despiece Mathematical Integrity (R2)**: 6 tests
   - 1 chicken -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + 2 Caldo raciones.
   - Batch yield multipliers for 5 and 10 whole chickens.
   - Exact deduction of `pollo_entero_crudo` from bodega.
   - Audit logging in `butchering_logs` table with operator and yield columns.
   - Conservation invariant: `total_presas == whole_chickens * 8`.
2. **Single Presas Sales & Stock Deduction (R1, R2)**: 6 tests
   - Dedicated deductions for Pechuga Sola, Muslo Solo, Contramuslo Solo, and Ala Sola.
   - Multiple quantities and cart containing all 4 varieties.
3. **Combos Sales & Multi-Component Deductions (R1, R2)**: 5 tests
   - 1/4 Pollo (POL-14): deducts 1 muslo + 1 contramuslo + 1 papas.
   - 1/2 Pollo (POL-12): deducts 1 pechuga + 1 ala + 1 muslo + 1 contramuslo + 1 papas.
   - Pollo Entero (POL-ENT): deducts 2 pechugas + 2 alas + 2 muslos + 2 contramuslos + 2 papas.
   - Multiple combo quantities and combos paired with sodas and sides.
4. **Almuerzo Completo with Mandatory Presa Selection (R1, R2)**: 6 tests
   - Selection with Pechuga, Muslo, Contramuslo, and Ala.
   - Strict server-side rejection (HTTP 400) when `chosen_presa` is missing.
   - Multiple almuerzos with distinct presas in a single order.
5. **Cash Change Exact Calculation (R1)**: 5 tests
   - Exact cash (change == 0).
   - Standard rounding ($20,000 COP bill).
   - Large bills ($50,000 and $100,000 COP).
   - Persistence of `cash_received` and `change_returned` in `sales` table.
6. **Digital Payment Methods (R1, R4)**: 5 tests
   - Nequi/Daviplata checkout setting change to 0 and preserving voucher notes.
   - Datáfono checkout setting change to 0.
   - Correct aggregation in daily summary under specific payment buckets.
7. **Symmetrical Sale Cancellation (R1, R2)**: 6 tests
   - Cancellation of single presas restores vitrina stock.
   - Cancellation of Almuerzo Completo restores chosen presa and side raciones.
   - Cancellation of combos (POL-14, POL-12, POL-ENT) restores all component presas and papas.
   - Status updated to `'anulada'` in database.
8. **Kitchen Batch Timers (R3)**: 6 tests
   - Salmuera default (6 hours).
   - Adobo default (4 hours).
   - Custom duration parameters and active batch listing.
   - System settings retrieval and updates.
9. **Cash Balance & Financial Summary (R4)**: 6 tests
   - Daily totals by payment method.
   - Gross contribution margin calculation: `SUM(qty * (price - cost))`.
   - Daily break-even comparison against $258,462 COP target.
   - Strict exclusion of cancelled sales from revenue and ticket counts.
10. **Supplier Low-Stock Alerts (R4)**: 6 tests
    - Low-stock alerts triggered when `stock <= min_threshold`.
    - No alert when stock is above threshold.
    - Alerts for raw chicken, beverages, and dry goods (harina/aceite).
    - Immediate clearing of alerts upon inventory replenishment.

### Tier 2: Boundary & Corner Cases (`tests/test_tier2_boundaries.py`) — 16 Tests
- 0 stock purchase rejection with HTTP 400.
- Negative stock rejection floor: orders requesting more than available stock return HTTP 400 and preserve stock without partial deductions or negative drift.
- Exact stock depletion to 0.0 succeeds; subsequent attempt fails with HTTP 400.
- Combo component exhaustion (e.g. papas exhausted) blocks combo checkout without partial chicken deduction.
- Exact cash payment returns change 0; non-negative change floor.
- Daily break-even exact boundary condition ($258,462 COP).
- Double cancellation rejection (cancelling an already cancelled sale returns HTTP 400).
- Non-existent sale ID cancellation returns HTTP 404.
- Empty cart checkout returns HTTP 400.
- Non-existent product ID returns HTTP 404.
- Almuerzo with blank/whitespace-only presa selection rejected.
- Despiece with 0 or negative chickens rejected with HTTP 400.
- Despiece exceeding raw chicken stock in bodega rejected with HTTP 400.

### Tier 3: Cross-Feature Combinations (`tests/test_tier3_cross_features.py`) — 5 Tests
- **Full Operational Lifecycle**: Despiece 6 chickens -> start timers -> 3 POS sales -> cancel 1 sale -> audit inventory and cash drawer reconciliation.
- **Cash Drawer Mixed Payment Reconciliation**: 4 sales across Cash, Nequi, and Datáfono; 1 cash sale cancelled; verify cash drawer reflects active sales only.
- **Multi-Item Order Multi-Level Inventory Atomic Deduction**: Single cart spanning Combos, Almuerzos, Drinks, and Sides; simultaneous deduction of 10 distinct inventory rows.
- **Atomic Rollback on Partial Inventory Failure**: If any single item in a multi-item cart lacks stock, entire transaction aborts with HTTP 400 and zero partial deduction occurs.
- **Sequential Depletion & Boundary Reversal Cascade**: Sequential purchases down to 0, failure on depleted stock, cancellation to restore stock, and subsequent purchase.

### Tier 4: Real-World Lunch Rush Scenario (`tests/test_tier4_lunch_rush.py`) — 1 Test
- Morning prep: Despiece of 15 whole chickens (yields 120 presas: 30P, 30M, 30C, 30A, 30 caldo raciones).
- 55 diverse customer transactions executed across combos, almuerzos, single presas, sodas, and sides.
- Payments across Cash, Nequi/Daviplata, and Datáfono.
- 3 customer order reversals processed.
- **Closed Inventory Conservation Formula**:
  $$\text{Initial Stock} + \text{Despiece Entradas} - \text{Net Sales Consumption} = \text{Final Physical Stock}$$
  Asserted across all 15 tracked inventory items with **EXACT 0 discrepancy**.
- Cash closing reconciliation: 52 active tickets, gross revenue matched against payment buckets, and break-even verified against $258,462 COP.

### Concurrency Stress Suite (`tests/test_concurrency_stress.py`) — 2 Tests
- **50 Rapid Concurrent Checkouts**: 50 simultaneous checkouts across 10 threads using `concurrent.futures.ThreadPoolExecutor`.
  - 0 database locks (`database is locked`).
  - 0 UNIQUE constraint collisions (`UNIQUE constraint failed: sales.sale_code`).
  - 50 unique sale codes generated sequentially.
  - Zero inventory drift: exactly 50 units deducted from vitrina and nevera.
- **30 Concurrent Mixed Combos**: 30 simultaneous multi-item combo purchases across 8 threads verifying multi-table atomic locks and zero component inventory drift.

---

## 3. How to Run the Tests

### Execute the Complete E2E Suite
```powershell
pytest tests/test_tier1_features.py tests/test_tier2_boundaries.py tests/test_tier3_cross_features.py tests/test_tier4_lunch_rush.py tests/test_concurrency_stress.py
```

### Execute by Individual Tiers
```powershell
# Tier 1: Feature Coverage
pytest tests/test_tier1_features.py

# Tier 2: Boundary & Corner Cases
pytest tests/test_tier2_boundaries.py

# Tier 3: Cross-Feature Combinations
pytest tests/test_tier3_cross_features.py

# Tier 4: Lunch Rush Real-World Simulation
pytest tests/test_tier4_lunch_rush.py

# Concurrency Stress Tests
pytest tests/test_concurrency_stress.py
```

---

## 4. Discovered Implementation Defects Escalated for Hardening

During comprehensive testing and adversarial execution against the codebase, 2 implementation bugs were discovered in `app/routers/pos.py`:

1. **Concurrent Double-Cancel Race Condition (`pos.py:286-332`)**:
   - *Observation*: Multiple concurrent requests to `/api/pos/cancel-sale/{sale_id}` can pass the check `if sale["status"] == "anulada"` before the write lock updates the status.
   - *Recommendation*: Enforce atomic status transition using `UPDATE sales SET status = 'anulada' WHERE id = ? AND status = 'completada'` and check `cursor.rowcount > 0` within an immediate write transaction.
2. **Negative Quantity Vulnerability (`pos.py:10-20` / `pos.py:153-176`)**:
   - *Observation*: `CartItem.quantity` accepts negative numbers (e.g. `quantity = -5`), resulting in negative sale totals and negative inventory deductions.
   - *Recommendation*: Add Pydantic validation `quantity: int = Field(gt=0)` or a server-side check `if item.quantity <= 0: raise HTTPException(400)`.
