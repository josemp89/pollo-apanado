# Handoff Report — Explorer Survey 3: Kitchen Timers, Peak-Hour Fryer Algorithm, Financial Cash Balance, and Deployment

**Author:** Explorer Survey 3  
**Date:** 2026-10-21T01:48:00Z  
**Target Audience:** Orchestrator, Test Writer, and Implementation Agents  
**Scope:** R3 (Kitchen Timers & Frying Recommendations), R4 (Cash Balance, Margins, Break-even & Supplier Alerts), R5 (Test Suite & Docker Deployment)

---

## 1. Observation

Direct code inspections, runtime executions, and database queries yielded the following verified evidence:

### 1.1 Kitchen Timers (Salmuera & Adobo)
* **Configuration Parameters (`app/database.py:214-225`)**:
  ```python
  settings = [
      ('salmuera_hours', '6', 'Tiempo estándar de permanencia en salmuera (horas)'),
      ('adobo_hours', '4', 'Tiempo estándar de permanencia en adobo (horas)'),
      ('fritura_minutes', '14', 'Tiempo estándar de freído de pollo en freidora (minutos)'),
      ('holding_vitrina_minutes', '45', 'Vida útil máxima recomendada en vitrina térmica (minutos)'),
      ('daily_breakeven_cop', '258462', 'Punto de equilibrio diario en pesos colombianos'),
      ('presas_per_chicken', '8', 'Número estándar de presas por pollo (8 = 2P, 2M, 2C, 2A)'),
  ]
  ```
* **Timer Duration Lookup Bug (`app/routers/kitchen.py:116-121`)**:
  ```python
  duration = payload.duration_hours
  if duration is None:
      setting_key = f"{payload.stage}_hours"
      row = cursor.execute("SELECT value FROM system_settings WHERE key = ?", (setting_key,)).fetchone()
      duration = float(row["value"]) if row else (6.0 if payload.stage == "salmuera" else 4.0)
  ```
  *Observed:* If `payload.stage == 'fritura'` and `duration_hours` is omitted, the code searches for `fritura_hours`. But `system_settings` contains `fritura_minutes = '14'`. Because `fritura_hours` does not exist, it falls back to `(6.0 if payload.stage == "salmuera" else 4.0)`, assigning a duration of **4.0 hours** instead of 14 minutes.
* **Batch Lifecycle & Termination (`app/routers/kitchen.py:145-154`)**:
  ```python
  @router.get("/batch-timers")
  def get_batch_timers():
      conn = get_db_connection()
      rows = conn.execute("""
          SELECT * FROM cooking_batches 
          WHERE stage != 'terminado' 
          ORDER BY id DESC LIMIT 10
      """).fetchall()
      conn.close()
      return [dict(r) for r in rows]
  ```
  *Observed:* There is no API endpoint to complete, cancel, or transition a batch (e.g., from `salmuera` to `adobo`, or marking `completed_at` with `stage = 'terminado'`). Batches persist in the active list forever until 10 newer batches displace them.
* **Frontend Timer Rendering & Alerts (`app/templates/kitchen.html:84-104`, `196-207`)**:
  * The UI only displays two buttons: `INICIAR SALMUERA` and `INICIAR ADOBO`. There is no button for `fritura`.
  * The timer display only slices the static target time string: `b.target_finished_at.slice(11, 16)`.
  * There is no countdown interval, no audio tone, no browser notification, and no visual state change (e.g., color shift or "Listo para retirar" banner) when the timer expires.
  * There is no UI to inspect or adjust `system_settings` (hours/minutes), even though `PUT /api/kitchen/settings` exists in the backend.

### 1.2 Peak-Hour Frying Recommendation Algorithm
* **Demand Query (`app/routers/kitchen.py:80-98`)**:
  ```python
  @router.get("/hourly-demand")
  def get_hourly_demand():
      """Analiza la demanda de presas por hora para saber a qué horas freír."""
      conn = get_db_connection()
      rows = conn.execute("""
          SELECT 
              s.hour_of_day,
              COUNT(DISTINCT s.id) as total_tickets,
              SUM(si.quantity) as total_items,
              SUM(CASE WHEN si.product_name LIKE '%Pechuga%' OR si.chosen_presa = 'Pechuga' THEN si.quantity ELSE 0 END) as pechugas_count,
              SUM(CASE WHEN si.product_name LIKE '%Muslo%' OR si.chosen_presa = 'Muslo' THEN si.quantity ELSE 0 END) as muslos_count,
              SUM(CASE WHEN si.product_name LIKE '%Contramuslo%' OR si.chosen_presa = 'Contramuslo' THEN si.quantity ELSE 0 END) as contramuslos_count,
              SUM(CASE WHEN si.product_name LIKE '%Ala%' OR si.chosen_presa = 'Ala' THEN si.quantity ELSE 0 END) as alas_count
          FROM sales s
          JOIN sale_items si ON s.id = si.sale_id
          WHERE s.status = 'completada'
          GROUP BY s.hour_of_day
          ORDER BY s.hour_of_day ASC
      """).fetchall()
  ```
  *Observed:*
  1. **Absence of Algorithm:** Neither `app/routers/kitchen.py` nor `app/templates/kitchen.html` contains an algorithm to calculate recommended frying batches. The system only executes a retrospective SQL aggregation of past completed sales.
  2. **Combo Presas Undercounting:** The query filters presas via `LIKE '%Pechuga%'`, etc. Sales of chicken combos (`POL-14` [1/4 pollo], `POL-12` [1/2 pollo], `POL-ENT` [Pollo Entero]) do NOT contain the words Pechuga/Muslo in `product_name` and have `chosen_presa = NULL`. Therefore, all presas sold inside combos are completely excluded from `pechugas_count`, `muslos_count`, `contramuslos_count`, and `alas_count`.
  3. **No Anticipation Logic:** In `app/templates/kitchen.html:123-125`, the text states:
     > *"Freír toma 14 minutos y la vitrina mantiene la crocancia ideal durante 45 minutos. El sistema te muestra abajo los picos de venta para freír con 15 minutos de anticipación."*
     The application delegates all calculation to human mental arithmetic. There is no automated recommendation suggesting when or how many batches to drop into the fryer based on lead times or upcoming peak hours.

### 1.3 Daily Cash Balance, Margins, Break-even & Supplier Alerts
* **Break-Even Calculation Fallacy (`app/routers/cash.py:50-53`, `85`)**:
  ```python
  setting_row = conn.execute("SELECT value FROM system_settings WHERE key = 'daily_breakeven_cop'").fetchone()
  daily_breakeven = int(setting_row["value"]) if setting_row else 258462
  breakeven_percentage = round((totals_dict["gran_total"] / daily_breakeven) * 100, 1) if daily_breakeven > 0 else 0
  ...
  "is_profitable_today": totals_dict["gran_total"] >= daily_breakeven,
  ```
  *Observed:*
  * As defined in `MASTER_CONTEXT.md:79-84` and `107-118`, the daily break-even of **$258,462 COP/day** is the fixed operational overhead cost ($6,720,000 COP / 26 days).
  * Fixed costs are covered by the **Gross Margin (Margen de Contribución)**, NOT by Gross Revenue (`gran_total`).
  * In `cash.py` and `cash.html:183-190`, `breakeven_percentage` compares `gran_total` against `daily_breakeven`. If a cashier sells $260,000 COP in revenue (with COGS of ~$140,000 COP, producing only ~$120,000 COP in margin), the system marks the day as `100.6%` and displays `¡DÍA RENTABLE!`, even though the business suffered a net operational loss of -$138,462 COP.
* **Unused Gross Margin (`app/routers/cash.py:40-47`, `app/templates/cash.html`)**:
  * `cash.py` computes `estimated_margin` accurately using `SUM(si.quantity * (p.price - p.cost))`.
  * However, `app/templates/cash.html` **completely ignores `data.estimated_margin`**. There is no element, card, or metric in the UI displaying the daily margin.
* **Missing Partner Distribution Metrics (R4 / `MASTER_CONTEXT.md:24-41`, `120-140`)**:
  * Neither `cash.py` nor `cash.html` calculates or displays the Cap Table distribution:
    * Capital Partner 1 (40%)
    * Capital Partner 2 (40%)
    * Operating Partner Santiago (20%)
    * Legal / Operating Reserve (5% or 7%)
* **Presas Sold Undercounting in Cash Dashboard (`app/routers/cash.py:55-67`)**:
  * The query for `units_sold` uses `LIKE '%Pechuga%' OR chosen_presa = 'Pechuga'`.
  * Just like the kitchen demand query, selling whole chickens (`POL-ENT`), half chickens (`POL-12`), or quarter chickens (`POL-14`) displays `0` presas sold in the `Balance de Presas Vendidas Hoy` cards.
* **Supplier Alerts & Dead Stock Tracking (`app/routers/cash.py:70-76`, `app/database.py:192-193`, `app/routers/pos.py`, `app/routers/kitchen.py`)**:
  * In `inventory`, initial items include `harina_apanar_kg` (25 kg, threshold 10) and `aceite_fritura_lt` (40 L, threshold 15).
  * A search across the entire project for `harina_apanar_kg` and `aceite_fritura_lt` confirms they are **NEVER decremented** anywhere during despiece, batch cooking, or POS sales.
  * Their stock remains static forever; therefore, low-stock alerts for flour and fryer oil will **never trigger**.
  * Arepas (`POR-AREP` in `products`) are missing from `inventory` entirely and are never decremented or tracked.

### 1.4 Test Suite & Concurrency Resiliency
* **Pytest Incompatibility (`test_system.py:6-79`)**:
  * `test_system.py` defines `def run_tests():` rather than standard pytest test functions (`def test_*`).
  * Running `pytest` outputs:
    ```
    collected 0 items
    ============================= 3 warnings in 0.46s =============================
    Process exited with code 1.
    ```
* **Windows Unicode Crash (`test_system.py:15`)**:
  * Running `python test_system.py` directly under Windows powershell failed with:
    ```
    UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' in position 0: character maps to <undefined>
    ```
    Standard Windows console defaults to cp1252; emojis in `print()` cause immediate process termination unless `PYTHONIOENCODING=utf-8` is forced or standard logging/ASCII formatting is used.
* **Destructive Test Execution (Lack of Database Isolation)**:
  * Running `test_system.py` directly mutates `data/asadero.db`.
  * Running it once inserted a sale `VTA-261020-0001` and added 5 butchered chickens (+40 presas) directly into the production database.
* **Missing Acceptance Criteria Test Scenarios (ORIGINAL_REQUEST.md:29-33)**:
  * Reversal of sales (`/api/pos/cancel-sale/{sale_id}`): Not tested.
  * Concurrency stress test (50+ rapid concurrent transactions under WAL mode): Zero tests written.
  * Closed inventory balance check (`Initial + Cuts - Sales = Final`): Zero tests written.
  * Batch timers and system settings: Zero tests written.

### 1.5 Critical Cross-Cutting Bug: Sale Reversal Inventory Corruption (`app/routers/pos.py:218-266`)
* In `cancel_sale`, the restoration logic explicitly checks:
  ```python
  if sku == 'POL-PEC': ...
  elif sku == 'POL-MUS': ...
  elif sku == 'POL-CON': ...
  elif sku == 'POL-ALA': ...
  elif sku == 'ALM-COMP' and chosen_presa: ...
  elif cat == 'gaseosas': ...
  elif sku == 'POR-CALD': ...
  elif sku == 'POR-FRIJ': ...
  elif sku == 'POR-ARROZ': ...
  elif sku == 'POR-PAPAS': ...
  ```
* **Omission:** `POL-14`, `POL-12`, `POL-ENT`, and `POR-AREP` are **completely absent** from `cancel_sale`.
* When a sale containing whole chicken or combos is cancelled, the inventory is **never restored**, permanently draining vitrina stock.

### 1.6 Docker Setup & Packaging (`Dockerfile`, `docker-compose.yml`, `requirements.txt`)
* **Missing `.dockerignore`**:
  * Root directory has no `.dockerignore`. `COPY . .` packages `.agents/` (entire multi-agent scratchpads, briefing logs), `__pycache__`, `.pytest_cache`, and `data/asadero.db` into the container image.
* **Missing Requirements (`requirements.txt:1-6`)**:
  * Only contains `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `pydantic`.
  * `pytest` and `httpx` (required for FastAPI TestClient) are absent. Automated tests cannot run inside a clean Docker container or CI.
* **Docker Environment**:
  * `docker-compose.yml` mounts `./data:/app/data` with `TZ=America/Bogota`.
  * The local Windows host environment does not have the `docker` binary installed in PATH (`CommandNotFoundException`).

---

## 2. Logic Chain

1. **R3 Logic (Timers & Fryer):**
   * *Premise:* R3 mandates kitchen timers with configurable parameters and an algorithm that anticipates fried chicken batches based on the hourly demand curve.
   * *Step 1:* `system_settings` defines parameters, but `kitchen.py:118` looks up `fritura_hours` instead of converting `fritura_minutes`, defaulting to 4 hours.
   * *Step 2:* `kitchen.html` has no inputs to change parameters, no button to start a frying batch, no live countdowns, no expiration alerts, and no way to mark batches as finished.
   * *Step 3:* `kitchen.py:80-98` only runs a backward-looking SQL query of past sales, completely omitting chicken sold in combos (`POL-14`, `POL-12`, `POL-ENT`).
   * *Conclusion 1:* R3 is currently failing: kitchen timers lack lifecycle management and alerting, and the peak-hour frying recommendation algorithm does not exist.

2. **R4 Logic (Financial Integrity, Cuadre de Caja & Stock Alerts):**
   * *Premise:* R4 requires daily cash balancing by payment method, gross margin computation, automatic comparison against daily break-even ($258,462 COP/day), partner metrics, and critical stock alerts for suppliers.
   * *Step 1:* In `cash.py:52` and `cash.html:183`, `breakeven_percentage` is calculated using gross sales revenue (`gran_total / daily_breakeven`).
   * *Step 2:* According to `MASTER_CONTEXT.md:79-118`, the $258,462 COP/day is fixed overhead that must be absorbed by the gross margin (`estimated_margin = revenue - COGS`). Using revenue flags unprofitable days as profitable.
   * *Step 3:* `estimated_margin` is computed in `cash.py` but is never rendered in `cash.html`.
   * *Step 4:* Partner profit splits (40/40/20) and reserves are nowhere in the code.
   * *Step 5:* Key inventory items (`harina_apanar_kg`, `aceite_fritura_lt`, `POR-AREP`) are never decremented in code, so supplier low-stock alerts never trigger for dry ingredients.
   * *Step 6:* `presas_sold` query omits combos, creating false audit reports of presas sold.
   * *Conclusion 2:* R4 has significant accounting and inventory bugs that would mislead the restaurant owners regarding profitability and stock reordering.

3. **R5 Logic (Automated Tests & Deployment):**
   * *Premise:* R5 mandates an automated pytest suite covering 100% of critical flows, 50+ concurrency stress test without WAL locks, closed inventory math, and clean Docker persistence.
   * *Step 1:* `test_system.py` is an ad-hoc script that pytest cannot discover (0 tests collected).
   * *Step 2:* The script crashes on Windows without UTF-8 console encoding and alters the live production database (`data/asadero.db`).
   * *Step 3:* Critical flows (sale reversal, combo restoration, concurrency stress, closed inventory formula) are completely untested.
   * *Step 4:* `cancel_sale` contains an inventory corruption bug because combo cancellation was never tested.
   * *Step 5:* Docker lacks `.dockerignore` and `requirements.txt` lacks `pytest` and `httpx`.
   * *Conclusion 3:* R5 acceptance criteria are unmet and require complete overhaul of the test harness and Docker configuration.

---

## 3. Caveats

* **No Docker Daemon on Host:** The host operating system does not have the `docker` CLI in PATH. Verification of Docker builds must be confirmed via Dockerfile/compose file structural audits and standard syntax/volume checks unless Docker is configured in a subshell or WSL.
* **Scope Boundary:** This survey was strictly read-only per the Explorer role. No application or database files were modified during this investigation.

---

## 4. Conclusion

The current codebase establishes a solid foundational skeleton (FastAPI, SQLite WAL, Jinja2/Tailwind UI), but possesses critical functional, financial, and testing deficiencies:
1. **Kitchen Timers:** Missing frying timer UI, bug in frying duration lookup (defaults to 4 hours), no audio/visual expiration alerts, and no batch completion/transition endpoint.
2. **Frying Recommendation Algorithm:** Missing entirely. Needs a forward-looking predictive engine that calculates required frying batches based on operational hourly curves (e.g., anticipating lunch rush 11:30–13:30 and evening peak 18:00–20:00) minus current vitrina stock.
3. **Cash Balancing & Margins:** Must fix break-even calculation to compare against Gross Margin (`estimated_margin >= daily_breakeven`) instead of gross sales, display Gross Margin in the UI, incorporate the 40/40/20 Cap Table breakdown, fix the presas sold aggregation to include combos, and implement inventory deduction for flour, oil, and arepas.
4. **Reversal Bug:** `cancel_sale` in `app/routers/pos.py` must restore presas and papas for `POL-14`, `POL-12`, `POL-ENT`, and `POR-AREP`.
5. **Testing Suite:** Replace `test_system.py` with a true `pytest` suite using an isolated SQLite test database (in-memory or temp file), test all critical paths (including sale reversal and invalid presa choice), execute a 50+ concurrent transaction stress test, and add `.dockerignore` and test dependencies.

---

## 5. Verification Method

To independently reproduce and verify every finding in this report:

1. **Verify Pytest Incompatibility:**
   ```powershell
   pytest -v
   ```
   *Expected Result:* Exits with code 1, `collected 0 items`.

2. **Verify Windows Console Crash on `test_system.py`:**
   ```powershell
   python test_system.py
   ```
   *Expected Result:* Terminates with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'`.

3. **Verify Fryer Duration Bug in `kitchen.py`:**
   Inspect `app/routers/kitchen.py:118-121`:
   Note that setting `fritura_hours` does not exist in `system_settings` (`database.py:217` defines `fritura_minutes`). Thus, `start_batch_timer` with `stage='fritura'` defaults to `4.0` hours.

4. **Verify Missing Combo Handling in Demand & Sales Queries:**
   Inspect `app/routers/kitchen.py:89-92` and `app/routers/cash.py:57-60`. Check that `POL-ENT`, `POL-12`, and `POL-14` are never matched by `LIKE '%Pechuga%'` or `chosen_presa`.

5. **Verify Break-Even Calculation Discrepancy:**
   Inspect `app/routers/cash.py:52` and `app/templates/cash.html:183-190`. Confirm comparison is against `cash_summary.gran_total` instead of `estimated_margin`.

6. **Verify Omission in `cancel_sale`:**
   Inspect `app/routers/pos.py:237-260`. Confirm `POL-14`, `POL-12`, `POL-ENT`, and `POR-AREP` are completely absent from the `if/elif` chain.

7. **Verify Unused Stock Items:**
   Search for `harina_apanar_kg` and `aceite_fritura_lt` across the workspace. Verify that only definition lines in `database.py` exist, with zero deduction queries in `pos.py` or `kitchen.py`.
