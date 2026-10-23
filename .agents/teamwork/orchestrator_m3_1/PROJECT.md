# Project: Pollo Apanado - POS Reactive Ticket, Supplier Entry & Inventory Reconciliation

## Architecture
- **Framework**: FastAPI / Python backend with SQLite in WAL mode.
- **Frontend**: Responsive HTML5 + Vanilla JS + Tailwind CSS (touch tablet-optimized).
- **Core State Flow**:
  - POS: `cart` in `pos.js` synced reactively to `#cartItemsList` DOM.
  - Inventory: `inventory` table (Bodega, Nevera, Cocina, Vitrina) updated atomically on sales and supplier deliveries.
  - Supplier Deliveries: `merchandise_entries` audit table tracking reception code, supplier, invoice, item, quantity, cost.
  - Daily Reconciliation: `daily_initial_inventory` snapshot table + real-time mathematical calculation:
    `Expected Stock = Initial Stock + Supplier Entries - Sales/Consumption`

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | POS Comanda DOM Separation | Move #cartEmptyState out of #cartItemsList into sibling element | M1 | Survey explorer_pos_ui_1 |
| 2 | POS Reactive renderCart() | Ensure item add, +, -, trash updates DOM immediately without JS error | M1 | R1 ORIGINAL_REQUEST |
| 3 | POS Clean Cart State | Correctly restore clean empty state on cart reset or checkout | M1 | R1 ORIGINAL_REQUEST |
| 4 | Database Table merchandise_entries | SQLite schema for supplier receptions with sequential code | M2 | R2 ORIGINAL_REQUEST |
| 5 | Supplier Entry API | POST /api/inventory/supplier-entry atomic stock increment + audit | M2 | R2 ORIGINAL_REQUEST |
| 6 | Supplier Entries History API | GET /api/inventory/supplier-entries list & total balance | M2 | R2 ORIGINAL_REQUEST |
| 7 | Supplier Entry UI Modal/Form | Accessible touch modal in index.html to register supplier arrivals | M2 | R2 ORIGINAL_REQUEST |
| 8 | Database Table daily_initial_inventory | SQLite schema for daily opening stock snapshot | M3 | R3 ORIGINAL_REQUEST |
| 9 | Set Opening Stock API | POST /api/inventory/set-initial-stock (or auto-snapshot on open-shift) | M3 | R3 ORIGINAL_REQUEST |
| 10 | Daily Reconciliation API | GET /api/inventory/daily-reconciliation (Expected = Initial + Supplier - Sales) | M3 | R3 ORIGINAL_REQUEST |
| 11 | Daily Reconciliation UI Panel | Real-time reconciliation panel in cash.html with zero-drift indicator | M3 | R3 ORIGINAL_REQUEST |
| 12 | POS Browser Reactivity Tests | Automated Playwright test for ticket addition, steppers, and zero JS console errors | M4 | R4 ORIGINAL_REQUEST |
| 13 | Supplier Entry Automated Tests | Pytest coverage for supplier entry endpoints, validation and DB state | M4 | R4 ORIGINAL_REQUEST |
| 14 | Zero-Drift Reconciliation Tests | Pytest coverage for mathematical reconciliation conservation law | M4 | R4 ORIGINAL_REQUEST |
| 15 | Adversarial & Forensic Verification | Independent review, stress verification, and forensic audit clean check | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | POS Reactive Ticket Bugfix | Fix index.html DOM hierarchy and pos.js renderCart reactivity | none | DONE |
| M2 | Merchandise Entry & Supplier Deliveries | DDL, API endpoints, and touch UI modal for supplier receptions | none | DONE |
| M3 | Initial Inventory & Reconciliation | DDL, API endpoints, and reconciliation panel in cash.html | M2 | DONE |
| M4 | Automated Test Suite (R4) | Implement test_pos_ticket_reactivity, test_merchandise_receptions, test_inventory_reconciliation | M1, M2, M3 | IN_PROGRESS |
| M5 | Adversarial Hardening & Forensic Audit | 2 Reviewers, 2 Challengers, and Forensic Auditor verification | M4 | PLANNED |

## Interface Contracts
### POS Comanda DOM Contract
- `#cartEmptyState`: Sibling to `#cartItemsList`, controlled via `.hidden` class.
- `#cartItemsList`: Container where item rows are dynamically rendered.
- `renderCart()`: Idempotent rendering function that nunca mutates `#cartEmptyState` DOM reference.

### Supplier Deliveries API Contract
- `POST /api/inventory/supplier-entry`:
  - Request JSON: `{"supplier_name": str, "invoice_number": str, "item_name": str, "location": str, "quantity": float, "unit_cost": float, "total_cost": float, "notes": Optional[str]}`
  - Response JSON: `{"success": true, "entry_code": str, "new_stock": float, "item_name": str, "location": str}`
- `GET /api/inventory/supplier-entries`:
  - Response JSON: `{"entries": [...], "total_count": int, "total_value_cop": float}`

### Inventory Reconciliation API Contract
- `POST /api/inventory/set-initial-stock`:
  - Request JSON: `{"date": "YYYY-MM-DD", "items": [{"item_name": str, "location": str, "quantity": float}]}`
  - Response JSON: `{"success": true, "recorded_count": int}`
- `GET /api/inventory/daily-reconciliation`:
  - Response JSON: `{"date": "YYYY-MM-DD", "items": [{"item_name": str, "initial_stock": float, "supplier_entries": float, "sales_dispatches": float, "expected_stock": float, "current_stock": float, "drift": float}], "is_balanced": bool}`

## Code Layout
- Frontend POS: `app/templates/index.html`, `app/static/js/pos.js`
- Frontend Cash/Reconciliation: `app/templates/cash.html`, `app/static/js/cash.js`
- Backend DB & Models: `app/database.py`, `app/models.py`
- Backend Router: `app/routers/inventory.py`, registered in `app/main.py`
- Tests: `tests/test_pos_ticket_reactivity.py`, `tests/test_merchandise_receptions.py`, `tests/test_inventory_reconciliation.py`, `tests/test_inventory.py`
