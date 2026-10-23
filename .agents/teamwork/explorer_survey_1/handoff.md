# Handoff Report: Backend Architecture, Database Schema, and Transaction Integrity Survey

**Agent**: Explorer Survey 1  
**Working Directory**: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_survey_1\`  
**Target Milestone**: Survey of Backend, Database, Concurrency, Despiece & Inventory  
**Date**: 2026-10-21  

---

## 1. Observation

### 1.1 Codebase & Architectural Overview
- **Entry Points & Server Bootstrap**:
  - `run_server.py:31`: Runs `uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)`. Dynamically discovers local LAN IP via UDP socket probe to `8.8.8.8` (lines 5-15).
  - `requirements.txt`: Specifies `fastapi>=0.115.0`, `uvicorn>=0.30.0`, `jinja2>=3.1.4`, `python-multipart>=0.0.9`, `pydantic>=2.8.0`. Missing `pytest` and `httpx` declarations.
  - `Dockerfile` & `docker-compose.yml`: Uses `python:3.12-slim`, exposes port 8000, maps volume `./data:/app/data`. There is **no `.dockerignore` file**, resulting in `.agents/`, `data/asadero.db`, and `__pycache__` being sent into the build context. Docker CLI is not installed in the Windows environment (`docker : El término 'docker' no se reconoce`).
  - `app/main.py:28-30`: Uses `@app.on_event("startup")` to invoke `init_db()`. Mounts `/static` and serves HTML templates (`/`, `/cocina`, `/caja`).

### 1.2 SQLite Connection Settings & Concurrency
- **File**: `app/database.py:7-14`:
  ```python
  def get_db_connection():
      os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
      conn = sqlite3.connect(DB_PATH)
      conn.row_factory = sqlite3.Row
      # Enable WAL mode for high concurrency
      conn.execute("PRAGMA journal_mode=WAL;")
      conn.execute("PRAGMA foreign_keys=ON;")
      return conn
  ```
- **PRAGMA inspection via Python**:
  - `journal_mode`: `wal`
  - `synchronous`: `2` (FULL synchronous mode; NOT `NORMAL`)
  - `busy_timeout`: `5000` (Default 5.0 seconds)
  - `foreign_keys`: `0` by default on new connections until line 13 runs.
- **Empirical Concurrency Test**:
  Executed 10 concurrent checkout requests across 5 threads using `ThreadPoolExecutor`:
  ```
  (200, '{"success":true,"sale_id":12,"sale_code":"VTA-261020-0011",...}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (200, '{"success":true,"sale_id":13,"sale_code":"VTA-261020-0012",...}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (200, '{"success":true,"sale_id":14,"sale_code":"VTA-261020-0013",...}')
  (500, '{"detail":"UNIQUE constraint failed: sales.sale_code"}')
  (200, '{"success":true,"sale_id":15,"sale_code":"VTA-261020-0014",...}')
  ```
  **6 out of 10 requests crashed with HTTP 500 (`UNIQUE constraint failed: sales.sale_code`)**.
  Caused by `app/routers/pos.py:55-56`:
  ```python
  sale_count = cursor.execute("SELECT COUNT(*) FROM sales WHERE date_str = ?", (date_str,)).fetchone()[0] + 1
  sale_code = f"VTA-{now.strftime('%y%m%d')}-{sale_count:04d}"
  ```
- Similar race condition in `app/routers/kitchen.py:123-124`:
  ```python
  batch_count = cursor.execute("SELECT COUNT(*) FROM cooking_batches").fetchone()[0] + 1
  batch_code = f"LOTE-{payload.stage[:3].upper()}-{now.strftime('%d%m')}-{batch_count:03d}"
  ```
  `cooking_batches.batch_code` is `UNIQUE NOT NULL` (`app/database.py:105`), creating identical collisions.

### 1.3 Despiece Logic & Mathematical Exactness
- **File**: `app/routers/kitchen.py:24-78` (`POST /api/kitchen/despiece`):
  ```python
  n = payload.whole_chickens
  pechugas = 2 * n
  muslos = 2 * n
  contramuslos = 2 * n
  alas = 2 * n
  caldo_bases = n

  # 1. Descontar pollos crudos de bodega
  cursor.execute("UPDATE inventory SET stock = stock - ? WHERE item_key = 'pollo_entero_crudo'", (n,))

  # 2. Sumar presas listas y raciones de caldo a cocina/vitrina
  cursor.execute("UPDATE inventory SET stock = stock + ? WHERE item_key = 'pechuga_vitrina'", (pechugas,))
  cursor.execute("UPDATE inventory SET stock = stock + ? WHERE item_key = 'muslo_vitrina'", (muslos,))
  cursor.execute("UPDATE inventory SET stock = stock + ? WHERE item_key = 'contramuslo_vitrina'", (contramuslos,))
  cursor.execute("UPDATE inventory SET stock = stock + ? WHERE item_key = 'ala_vitrina'", (alas,))
  cursor.execute("UPDATE inventory SET stock = stock + ? WHERE item_key = 'caldo_raciones'", (caldo_bases * 2,))
  ```
- **Formula Verification**: Enforces `1 Pollo Crudo -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + 2 Caldo raciones`. Logs exact values to `butchering_logs` table (`app/database.py:87-98`).
- **Deficiencies Observed**:
  - **Stage bypass**: Despiece immediately increments `_vitrina` (fried chicken ready for sale), skipping intermediate states (`pechuga_cruda`, `muslo_crudo`, salmuera/adobo containers).
  - **No stock sufficiency check**: If `pollo_entero_crudo` stock in bodega is 2 and 10 are requested, stock updates to `-8.0`.
  - **No exception handling or rollback**: No `try ... except ... conn.rollback()`.
  - **No entrada/purchase flow**: No endpoint to record supplier delivery of raw chickens into bodega.

### 1.4 Multi-Level Inventory Tracking & Sale Deduction Flows
- **Checkout Deductions (`app/routers/pos.py:121-173`)**:
  - Presas solas: Deducts 1 unit from `_vitrina`.
  - Combos:
    - `POL-14` (1/4 Pollo): Deducts 1 `muslo_vitrina`, 1 `contramuslo_vitrina`, 1 `papas_raciones`.
    - `POL-12` (1/2 Pollo): Deducts 1 `pechuga_vitrina`, 1 `ala_vitrina`, 1 `muslo_vitrina`, 1 `contramuslo_vitrina`, 1 `papas_raciones`.
    - `POL-ENT` (Pollo Entero): Deducts 2 `pechuga_vitrina`, 2 `ala_vitrina`, 2 `muslo_vitrina`, 2 `contramuslo_vitrina`, 2 `papas_raciones`.
  - Almuerzo Completo (`ALM-COMP`): Deducts chosen presa + 1 `caldo_raciones`, 1 `arroz_raciones`, 1 `frijoles_raciones`.
  - Sides (`POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`): Deducts 1 from corresponding `_raciones`.
  - Gaseosas: Deducts 1 from `nevera` by SKU.
- **Critical Inventory Defects Observed**:
  - **Asymmetric Sale Reversal (`app/routers/pos.py:228-260`)**:
    In `cancel_sale(sale_id: int)`, there are cases for `POL-PEC`, `POL-MUS`, `POL-CON`, `POL-ALA`, `ALM-COMP`, `gaseosas`, and porciones.
    **COMBOS (`POL-14`, `POL-12`, `POL-ENT`) ARE COMPLETELY MISSING FROM `cancel_sale`!**
    Cancelling a sale containing combos leaves items deducted permanently, causing severe inventory drift.
  - **SQL Injection Risk in `cancel_sale` (`app/routers/pos.py:246`)**:
    `cursor.execute(f"UPDATE inventory SET stock = stock + ? WHERE item_key = '{chosen_presa.lower()}_vitrina'", (qty,))` uses f-string interpolation instead of parameterized placeholders.
  - **Negative Stock Allowed**:
    Neither checkout nor despiece checks `stock >= qty`.
    Direct database inspection revealed `ala_vitrina` had a stock of **`-973.0`**.
  - **Orphaned Insumos Secos**:
    `harina_apanar_kg` and `aceite_fritura_lt` are seeded in `app/database.py:192-193`, but are never updated or consumed anywhere in the codebase.
  - **Missing Arepas**:
    `POR-AREP` exists in `products` (`app/database.py:153`), but does not exist in `inventory` table, and is never deducted in `checkout` or restored in `cancel_sale`.
  - **Combos Omitted in Reporting & Kitchen Demand**:
    In `app/routers/cash.py:56-67` and `app/routers/kitchen.py:89-92`, presas are counted with:
    `SUM(CASE WHEN si.product_name LIKE '%Pechuga%' OR si.chosen_presa = 'Pechuga' THEN si.quantity ELSE 0 END)`.
    Combos (`1/4 Pollo`, `1/2 Pollo`, `Pollo Entero`) do not match the `LIKE` clause and have `chosen_presa = NULL`, so presas sold through combos are completely absent from the sales summary and hourly kitchen demand curve.

### 1.5 Timers & Kitchen Logic
- **Fritura Duration Setting Bug (`app/routers/kitchen.py:118-121`)**:
  ```python
  setting_key = f"{payload.stage}_hours"
  row = cursor.execute("SELECT value FROM system_settings WHERE key = ?", (setting_key,)).fetchone()
  duration = float(row["value"]) if row else (6.0 if payload.stage == "salmuera" else 4.0)
  ```
  In `system_settings` (`app/database.py:217`), fritura is stored as `'fritura_minutes'`, not `'fritura_hours'`.
  When starting a `'fritura'` batch timer without explicitly providing `duration_hours`, the query for `'fritura_hours'` returns `None`, and the code defaults to **`4.0` hours** instead of 14 minutes.
- **Batches Never Complete**:
  `cooking_batches` table has `stage` and `completed_at`, but there is no endpoint or UI action to mark a batch as completed or advance it (`salmuera` -> `adobo` -> `fritura` -> `vitrina`).

### 1.6 Financial & Cash Summary
- **Breakeven Comparison Discrepancy (`app/routers/cash.py:51-52`)**:
  ```python
  daily_breakeven = int(setting_row["value"]) if setting_row else 258462
  breakeven_percentage = round((totals_dict["gran_total"] / daily_breakeven) * 100, 1)
  ```
  Compares gross revenue (`gran_total`) directly against fixed costs ($258.462 COP/day) rather than gross contribution margin (`estimated_margin`).
- **Hidden Margin Metric**:
  `estimated_margin` is calculated at line 47, but is not rendered in `app/templates/cash.html`.

### 1.7 Test Suite Status
- Running `python test_system.py` fails on Windows due to unhandled Unicode character `✅` with default codepage `cp1252` (`UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'`).
- Running with UTF-8 encoding fails because it asserts `cash_res["cash_summary"]["gran_total"] == 25500` against the live production database (`data/asadero.db`), which already contains previous sales.
- Pytest is available (`pytest 9.1.1`), but no pytest suite or test database fixtures currently exist in the repository.

---

## 2. Logic Chain

1. **Premise**: Concurrency requirement R5 mandates handling rapid consecutive transactions without database locks or integrity crashes.
   - *Observation*: `pos.py:55-56` computes `sale_code` using `SELECT COUNT(*) FROM sales` within deferred transactions.
   - *Deduction*: Multiple concurrent threads read the same count and generate identical `sale_code`.
   - *Proof*: Running 10 concurrent checkouts resulted in 6 requests failing with `500 UNIQUE constraint failed: sales.sale_code`.

2. **Premise**: Inventory integrity R2 mandates mathematical exactness: `Stock Inicial + Entradas por Despiece - Ventas Registradas = Stock Final Físico`.
   - *Observation*: `cancel_sale` in `pos.py:228-260` only restores single presas, lunch specials, sodas, and sides. It omits combos (`POL-14`, `POL-12`, `POL-ENT`).
   - *Deduction*: When any combo sale is cancelled, inventory deducted at checkout is permanently omitted from restitution.
   - *Observation*: No stock floor exists; `ala_vitrina` was observed at `-973.0`.
   - *Deduction*: Discrepancy zero cannot be achieved without bidirectional symmetry and non-negative constraints.

3. **Premise**: Kitchen timing and peak demand R3 requires accurate timers and hourly fry recommendations.
   - *Observation*: `kitchen.py:118` queries `{payload.stage}_hours`. In `database.py:217`, the key is `fritura_minutes`.
   - *Deduction*: Fritura batch timers default to 4.0 hours instead of 14 minutes.
   - *Observation*: Presa demand query in `kitchen.py:89-92` relies on `LIKE '%Presa%'` and `chosen_presa`.
   - *Deduction*: Demand curves completely omit presas consumed via combos (`POL-14`, `POL-12`, `POL-ENT`), distorting frying projections.

4. **Premise**: SQLite in WAL mode must support concurrent read/write operations without locking.
   - *Observation*: `database.py:9` opens connections with default timeout (5.0s), omits `PRAGMA synchronous = NORMAL`, and executes `PRAGMA journal_mode=WAL` redundantly on every connection.
   - *Deduction*: High write concurrency risks lock contention and unnecessary filesystem overhead.

---

## 3. Caveats

- **Docker runtime**: The Docker CLI is not installed on the host machine; docker container build was inspected statically via `Dockerfile` and `docker-compose.yml`, but could not be launched locally.
- **Frontend live browser test**: The frontend templates and scripts were analyzed via source code inspection; Chrome browser automation was not executed during this survey turn.
- **Production database state**: The active database `data/asadero.db` contains test transactions and negative stock values from earlier manual or scripted runs.

---

## 4. Conclusion

The current codebase establishes a clean foundational architecture with FastAPI, SQLite WAL, and Tailwind-based responsive templates. However, it currently contains **critical architectural, concurrency, and mathematical integrity flaws** that violate requirements R1, R2, R3, R4, and R5:

1. **Concurrency Blocker (R5)**: `sale_code` and `batch_code` generation are subject to deterministic race conditions, causing 60% failure rates under concurrent checkout loads.
2. **Inventory Leakage & Asymmetry (R2)**: `cancel_sale` permanently loses presas and sides on cancelled combo orders; negative inventory is unconstrained (observed at `-973.0`); insumos secos (harina, aceite, arepas) are not tracked.
3. **Despiece Workflow Disconnect (R2)**: Yield formula ($1 \rightarrow 8$ presas + $2$ caldo) is mathematically compliant, but despiece immediately teleports raw chickens from bodega into hot vitrina without checking bodega stock or passing through kitchen production stages.
4. **Kitchen Timer Bug (R3)**: Fritura timers fall back to 4 hours due to setting key mismatch (`fritura_hours` vs `fritura_minutes`); batches cannot be completed or transitioned; combo presas are invisible in demand curves.
5. **Financial & Test Fragility (R4, R5)**: Daily breakeven gauge compares gross revenue instead of gross margin; existing `test_system.py` fails on Windows CP1252 encoding and mutates live production data.

---

## 5. Verification Method

To independently verify all observations and conclusions:

1. **Verify Concurrency Race Condition**:
   Execute the following command from project root:
   ```powershell
   python -c "import concurrent.futures; from fastapi.testclient import TestClient; from app.main import app; c = TestClient(app); f = lambda i: c.post('/api/pos/checkout', json={'items': [{'product_id': 1, 'quantity': 1}], 'payment_method': 'efectivo', 'cash_received': 10000}).status_code; p = list(concurrent.futures.ThreadPoolExecutor(max_workers=5).map(f, range(10))); print('Status codes:', p)"
   ```
   *Expected outcome*: Appearance of status code `500` due to `UNIQUE constraint failed: sales.sale_code`.

2. **Verify Negative Inventory**:
   Execute:
   ```powershell
   python -c "import sqlite3; conn = sqlite3.connect('data/asadero.db'); print(conn.execute(\"SELECT item_key, stock FROM inventory WHERE item_key = 'ala_vitrina';\").fetchone())"
   ```
   *Expected outcome*: Stock value is negative (observed `-973.0`).

3. **Verify Combo Voiding Asymmetry**:
   Inspect `app/routers/pos.py` lines 228 to 260. Note the complete absence of `elif sku in ('POL-14', 'POL-12', 'POL-ENT')`.

4. **Verify Fritura Timer Key Mismatch**:
   Inspect `app/database.py` line 217 (`'fritura_minutes', '14'`) versus `app/routers/kitchen.py` line 118 (`setting_key = f"{payload.stage}_hours"`).

5. **Verify Windows Test Script Encoding Failure**:
   Execute:
   ```powershell
   python test_system.py
   ```
   *Expected outcome*: `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'`.
