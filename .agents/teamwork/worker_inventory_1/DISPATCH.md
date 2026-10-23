## 2026-10-22T01:50:10Z
You are worker_inventory_1.
Your working directory: c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_inventory_1
Project root: c:\Users\Alejandro\Desktop\POLLO APANADO
Authoritative requirement document: c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md (specifically section ## 2026-10-22T01:24:23Z, requirements R2 and R3 and acceptance criteria).
Project Scope & Contracts: c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\orchestrator_m3_1\PROJECT.md
Survey Analysis & Blueprint: c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_inventory_backend_1\analysis.md and handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- app/database.py
- app/routers/inventory.py (create this router)
- app/main.py (register inventory router)
- app/templates/index.html (add accessible Supplier Entry modal/button)
- app/templates/cash.html (add Initial Inventory & Reconciliation panel)
- app/static/js/cash.js (add reconciliation logic/functions)

Your Task:
1. Read ORIGINAL_REQUEST.md, PROJECT.md, and explorer_inventory_backend_1's analysis.md.
2. Database Schema (app/database.py):
   - Add table `merchandise_entries`:
     - id INTEGER PRIMARY KEY AUTOINCREMENT
     - entry_code TEXT UNIQUE NOT NULL (e.g. REC-YYMMDD-XXXX)
     - date TEXT NOT NULL
     - supplier_name TEXT NOT NULL
     - invoice_number TEXT NOT NULL
     - item_name TEXT NOT NULL
     - location TEXT NOT NULL (Bodega, Nevera, Cocina, Vitrina)
     - quantity REAL NOT NULL
     - unit_cost REAL DEFAULT 0.0
     - total_cost REAL DEFAULT 0.0
     - notes TEXT
     - created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   - Add table `daily_initial_inventory`:
     - id INTEGER PRIMARY KEY AUTOINCREMENT
     - date TEXT NOT NULL
     - item_name TEXT NOT NULL
     - location TEXT NOT NULL
     - quantity REAL NOT NULL
     - recorded_by TEXT DEFAULT 'admin'
     - recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
     - UNIQUE(date, item_name, location)
   - Ensure tables are created cleanly in `init_db()` and when `app` starts up.
3. Inventory Router (app/routers/inventory.py):
   - `POST /api/inventory/supplier-entry`:
     - Body: {supplier_name, invoice_number, item_name, location, quantity, unit_cost, total_cost, notes}
     - Atomic transaction: Insert into `merchandise_entries` and increment existing inventory stock:
       `UPDATE inventory SET stock = stock + ? WHERE item_name = ? AND location = ?` (or create if not present).
     - Return: {success: True, entry_code: ..., new_stock: ..., item_name: ..., location: ...}
   - `GET /api/inventory/supplier-entries`:
     - Query params: optional date or limit.
     - Return: {entries: [...], total_count: int, total_value_cop: float}
   - `POST /api/inventory/set-initial-stock`:
     - Body: {date: optional, items: [{item_name, location, quantity}]}
     - Store/replace initial stock snapshot for the day in `daily_initial_inventory`.
     - Return: {success: True, recorded_count: int}
   - `GET /api/inventory/daily-reconciliation`:
     - Calculate real-time mathematical reconciliation:
       For each tracked item (raw chicken, pieces, drinks, sides):
       - Initial Stock (from `daily_initial_inventory` for today, or fallback to current stock if not yet set)
       - Supplier Entries (SUM quantity from `merchandise_entries` for today)
       - Sales/Dispatches (SUM quantity consumed from sales and combo items today)
       - Expected Stock = Initial + Entries - Sales
       - Current Physical/System Stock = from `inventory`
       - Drift = Current Stock - Expected Stock (should be 0.0 under normal operation)
     - Return: {date: ..., items: [...], is_balanced: bool}
   - Register this router in `app/main.py`: `app.include_router(inventory.router)`.
4. Frontend Integration:
   - In `app/templates/index.html`:
     - Add an accessible touch button "📦 Entrada Proveedor" (e.g. in the top header or quick actions bar) that opens a modal `#supplierEntryModal`.
     - The modal contains fields: Proveedor, Factura/Remisión, Insumo/Producto (dropdown or autocomplete with existing inventory items), Ubicación (Bodega/Nevera), Cantidad, Costo Total.
     - Submitting sends `POST /api/inventory/supplier-entry`, shows success feedback (e.g. toast notification), and clears the modal.
   - In `app/templates/cash.html` & `app/static/js/cash.js`:
     - Add a section/card for "Conciliación Diaria de Inventario (Stock Inicial + Entradas - Ventas)".
     - Allow viewing the initial stock, cumulative supplier entries today, sales, and expected stock with a clean table and zero-drift badge.
5. Verification:
   - Run `python -m pytest` from project root to ensure all 188 existing tests continue passing without regression.
   - Test the new endpoints using python/pytest or direct requests.
6. Write detailed handoff report in `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_inventory_1\handoff.md`.
7. Send a message to orchestrator with summary and verification output.
