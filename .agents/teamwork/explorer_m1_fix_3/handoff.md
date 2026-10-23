# Explorer 3 Analysis & Strategy Report — Milestone M1 Iteration 2
**Target Areas**: Kitchen Batch Timer Input Validation (`app/routers/kitchen.py`) & SQLite Database Engine-Level Constraints (`app/database.py`)  
**Agent**: Explorer 3 (`explorer_m1_fix_3`)  
**Role**: explorer, investigator, synthesizer  
**Parent Agent**: `e0991dd2-14f6-466f-a2b3-71ee70d307fd`  
**Status**: COMPLETE  

---

## Executive Summary
This investigation analyzed two identified data integrity gaps blocking the Milestone M1 certification gate:
1. **Kitchen Batch Timer Input Boundary**: Missing validation on `stage`, `total_presas`, and `duration_hours` in `POST /api/kitchen/batch-timer` allows arbitrary invalid stage strings and negative presas into `cooking_batches`.
2. **Database Engine-Level Floor**: The `inventory` table definition lacks a native `CHECK (stock >= 0)` constraint, leaving domain integrity dependent solely on application-level checks. Furthermore, editing `CREATE TABLE IF NOT EXISTS` is a no-op on existing databases (`data/asadero.db`), requiring an idempotent migration step in `init_db()`.

A clean, non-disruptive fix strategy is formulated below with drop-in code snippets and migration instructions for the implementing worker.

---

## 1. Observation

### 1.1 Kitchen Batch Timer Input Validation Defect
- **Target File**: `app/routers/kitchen.py`
- **Lines 14–19**:
  ```python
  class BatchTimerRequest(BaseModel):
      stage: str  # 'salmuera', 'adobo', 'fritura'
      total_presas: int
      duration_hours: Optional[float] = None
      notes: Optional[str] = None
  ```
- **Lines 156–220**:
  In `start_batch_timer`:
  ```python
  @router.post("/batch-timer")
  def start_batch_timer(payload: BatchTimerRequest):
      conn = get_db_connection()
      cursor = conn.cursor()
      try:
          now = datetime.now()

          # Si no se envía duración, tomar la configuración estándar
          duration = payload.duration_hours
          if duration is None:
              if payload.stage == "fritura":
                  row = cursor.execute("SELECT value FROM system_settings WHERE key = 'fritura_minutes'").fetchone()
                  minutes = float(row["value"]) if row else 14.0
                  duration = minutes / 60.0
              else:
                  setting_key = f"{payload.stage}_hours"
                  row = cursor.execute("SELECT value FROM system_settings WHERE key = ?", (setting_key,)).fetchone()
                  duration = float(row["value"]) if row else (6.0 if payload.stage == "salmuera" else 4.0)

          target_time = now + timedelta(hours=duration)
          batch_code = get_next_batch_code(cursor, payload.stage, now)

          cursor.execute("""
              INSERT INTO cooking_batches (
                  batch_code, stage, total_presas, started_at, target_finished_at, notes
              ) VALUES (?, ?, ?, ?, ?, ?)
          """, (
              batch_code, payload.stage, payload.total_presas, now.isoformat(), target_time.isoformat(), payload.notes
          ))
  ```
- **Empirical Defect Confirmation**:
  Executing `POST /api/kitchen/batch-timer` with payload `{"stage": "nonexistent_stage", "total_presas": -10}` succeeds with HTTP 200:
  ```json
  {
    "success": true,
    "batch_code": "LOTE-NON-2010-001",
    "stage": "nonexistent_stage",
    "duration_hours": 4.0
  }
  ```
  This creates corrupted batch records in `cooking_batches` with invalid stages and negative presa counts.
- **Related Counter Defect (Lines 24–35)**:
  `get_next_batch_code` formats `counter_name = f"batch_{now.strftime('%Y-%m-%d')}"`, but computes the fallback initial counter value using `(SELECT COALESCE(COUNT(*), 0) FROM cooking_batches) + 1` across all lifetime batches instead of filtering by today's date (`WHERE started_at LIKE ?`).

### 1.2 SQLite Inventory Schema and Missing CHECK Constraint
- **Target File**: `app/database.py`
- **Lines 39–50**:
  ```sql
  CREATE TABLE IF NOT EXISTS inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_key TEXT UNIQUE NOT NULL, -- e.g. 'pechuga_vitrina', 'pollo_crudo', 'coca_cola_400'
      name TEXT NOT NULL,
      category TEXT NOT NULL, -- 'vitrina', 'nevera', 'bodega', 'cocina'
      stock REAL DEFAULT 0,
      unit TEXT NOT NULL, -- 'unidad', 'porcion', 'kg', 'bolsa'
      min_threshold REAL DEFAULT 5,
      updated_at TEXT
  );
  ```
- **Line 155**:
  ```python
  # Saneamiento preventivo de inventario: restablecer cualquier stock negativo residual
  cursor.execute("UPDATE inventory SET stock = 15 WHERE stock < 0;")
  ```
- **Inspection of Existing Database (`data/asadero.db`)**:
  Executing direct schema inspection on the existing SQLite file:
  ```python
  cursor.execute("SELECT sql FROM sqlite_master WHERE name='inventory'").fetchone()[0]
  ```
  Returned:
  ```sql
  CREATE TABLE inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_key TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      category TEXT NOT NULL,
      stock REAL DEFAULT 0,
      unit TEXT NOT NULL,
      min_threshold REAL DEFAULT 5,
      updated_at TEXT
  )
  ```
- **Constraint Absence Impact**:
  Because SQLite does not enforce column domain bounds unless explicitly declared via `CHECK`, direct updates or inserts that produce negative values (e.g. `UPDATE inventory SET stock = -5.0 WHERE item_key = 'pechuga_vitrina'`) are permitted by the engine.
- **Idempotency Caveat for Existing Databases**:
  Modifying `CREATE TABLE IF NOT EXISTS` in `app/database.py` will protect fresh test databases (`tests/conftest.py` creates a new database per test), but is a complete **no-op** on existing databases (`data/asadero.db`). Because SQLite does not support `ALTER TABLE ... ADD CONSTRAINT`, table migration logic is mandatory in `init_db()`.
- **Foreign Key Safety**:
  Inspected all tables in `app/database.py`. Only `sale_items` has foreign keys (`sales(id)` and `products(id)`). Zero tables have foreign keys pointing to `inventory`. Thus, renaming and recreating `inventory` during migration is 100% safe and causes no foreign key constraint violations.

---

## 2. Logic Chain

1. **Defense-in-Depth Principle**:
   - Application-level guards (`WHERE stock >= ?` in SQL updates) provide user-friendly HTTP 400 responses.
   - However, without an engine-level `CHECK (stock >= 0)` constraint, any defect, rogue script, unvalidated endpoint (`adjust-stock`), or concurrency anomaly can bypass application logic and store negative stock (as evidenced by the preventive `UPDATE inventory SET stock = 15 WHERE stock < 0` at `database.py:155`).
   - Adding `CHECK (stock >= 0)` provides an un-bypassable guarantee at the storage layer.

2. **Non-Disruptive Constraint Verification**:
   - All standard business operations maintain non-negative stock:
     - Checkouts: pre-checked and atomically deducted `WHERE stock >= ?`.
     - Despiece: validates `pollo_entero_crudo >= n`.
     - Fritura batch timers: deducts using `SET stock = MAX(0.0, stock - ?)`.
     - Cancellations: `SET stock = stock + ?`.
     - Seeded stock: all initial inventory values are positive (10 to 50).
   - Therefore, valid workflows will never violate `CHECK (stock >= 0)`.

3. **HTTP 400 vs HTTP 422 Contract Alignment**:
   - In FastAPI, Pydantic field validators (`Field(gt=0)`) return HTTP 422 (Unprocessable Entity) on malformed requests.
   - However, existing tests, reviewer audits (`reviewer_m1_2/handoff.md`), and adversarial tests (`test_adversarial.py`) specifically assert HTTP 400 for business validation errors (e.g., negative despiece chickens, empty carts, exhausted stock).
   - Validating `stage in ('salmuera', 'adobo', 'fritura')` and `total_presas > 0` via explicit `HTTPException(status_code=400, ...)` inside `start_batch_timer` ensures complete compatibility with the project's error contract.
   - Performing this validation before `get_db_connection()` eliminates unnecessary database connections and transaction rollback overhead for invalid payloads.

---

## 3. Recommended Fix Strategy

### 3.1 Fix Strategy for `app/routers/kitchen.py`

#### A. Define Valid Stages Whitelist & Boundary Validations
In `app/routers/kitchen.py`:
1. Add constant `VALID_BATCH_STAGES`:
   ```python
   VALID_BATCH_STAGES = ("salmuera", "adobo", "fritura")
   ```
2. Place boundary validation at the very top of `start_batch_timer`:
   ```python
   @router.post("/batch-timer")
   def start_batch_timer(payload: BatchTimerRequest):
       # 1. Validar etapa permitida (insensible a mayúsculas/espacios)
       stage_norm = (payload.stage or "").strip().lower()
       if stage_norm not in VALID_BATCH_STAGES:
           raise HTTPException(
               status_code=400,
               detail=f"Etapa inválida '{payload.stage}'. Debe ser una de: {list(VALID_BATCH_STAGES)}"
           )

       # 2. Validar que la cantidad de presas sea estrictamente mayor a 0
       if payload.total_presas <= 0:
           raise HTTPException(
               status_code=400,
               detail="El total de presas debe ser mayor a 0."
           )

       # 3. Validar duración si se proporciona explícitamente
       if payload.duration_hours is not None and payload.duration_hours <= 0:
           raise HTTPException(
               status_code=400,
               detail="La duración debe ser mayor a 0 horas."
           )

       payload.stage = stage_norm
       conn = get_db_connection()
       cursor = conn.cursor()
       ...
   ```

#### B. Fix Daily Batch Counter Sequence (Robustness Improvement)
In `app/routers/kitchen.py:27-35`, update `get_next_batch_code`:
```python
def get_next_batch_code(cursor, stage: str, now: datetime) -> str:
    stage_prefix = stage[:3].upper()
    date_code = now.strftime('%d%m')
    counter_name = f"batch_{now.strftime('%Y-%m-%d')}"
    today_prefix = f"{now.strftime('%Y-%m-%d')}%"
    
    while True:
        cursor.execute("""
            INSERT INTO order_counters (counter_name, last_value)
            VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM cooking_batches WHERE started_at LIKE ?) + 1)
            ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
            RETURNING last_value;
        """, (counter_name, today_prefix))
        seq = cursor.fetchone()[0]
        code = f"LOTE-{stage_prefix}-{date_code}-{seq:03d}"
        exists = cursor.execute("SELECT 1 FROM cooking_batches WHERE batch_code = ?", (code,)).fetchone()
        if not exists:
            return code
```

---

### 3.2 Fix Strategy for `app/database.py`

#### A. Update Schema Definition with Column Constraint
In `app/database.py:39-50`:
```sql
    # 2. Tabla de Inventario Multinivel
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_key TEXT UNIQUE NOT NULL, -- e.g. 'pechuga_vitrina', 'pollo_crudo', 'coca_cola_400'
        name TEXT NOT NULL,
        category TEXT NOT NULL, -- 'vitrina', 'nevera', 'bodega', 'cocina'
        stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
        unit TEXT NOT NULL, -- 'unidad', 'porcion', 'kg', 'bolsa'
        min_threshold REAL DEFAULT 5,
        updated_at TEXT
    );
    """)
```

#### B. Add Idempotent Zero-Downtime Migration in `init_db()`
Immediately after the `CREATE TABLE IF NOT EXISTS` statements in `init_db()` (around line 135):
```python
    # 9. Migración idempotente: asegurar restricción CHECK (stock >= 0) en bases existentes
    inv_schema = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='inventory'"
    ).fetchone()
    if inv_schema and "CHECK" not in inv_schema[0]:
        cursor.execute("UPDATE inventory SET stock = 0 WHERE stock < 0;")
        cursor.execute("ALTER TABLE inventory RENAME TO _inventory_old;")
        cursor.execute("""
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
            unit TEXT NOT NULL,
            min_threshold REAL DEFAULT 5,
            updated_at TEXT
        );
        """)
        cursor.execute("""
        INSERT INTO inventory (id, item_key, name, category, stock, unit, min_threshold, updated_at)
        SELECT id, item_key, name, category, stock, unit, min_threshold, updated_at 
        FROM _inventory_old;
        """)
        cursor.execute("DROP TABLE _inventory_old;")
```
This guarantees that:
- Any existing database file (`data/asadero.db`) is automatically upgraded on application startup without data loss.
- In-memory and isolated test databases created fresh by pytest will natively possess the constraint.
- The migration is 100% idempotent: subsequent runs detect `"CHECK" in inv_schema[0]` and immediately skip the block.

---

### 3.3 New Unit & Adversarial Tests for Worker M1

Worker M1 should add the following targeted tests to `tests/test_milestone_m1.py`:

```python
import sqlite3

def test_kitchen_batch_timer_input_validation(client):
    """Verify that start_batch_timer rejects invalid stages and non-positive presas with HTTP 400."""
    # 1. Invalid stage string
    res_bad_stage = client.post("/api/kitchen/batch-timer", json={
        "stage": "horno",
        "total_presas": 16
    })
    assert res_bad_stage.status_code == 400
    assert "Etapa inválida" in res_bad_stage.json()["detail"]

    # 2. Zero presas
    res_zero_presas = client.post("/api/kitchen/batch-timer", json={
        "stage": "fritura",
        "total_presas": 0
    })
    assert res_zero_presas.status_code == 400
    assert "total de presas debe ser mayor a 0" in res_zero_presas.json()["detail"]

    # 3. Negative presas
    res_neg_presas = client.post("/api/kitchen/batch-timer", json={
        "stage": "salmuera",
        "total_presas": -10
    })
    assert res_neg_presas.status_code == 400

    # 4. Non-positive duration_hours
    res_bad_dur = client.post("/api/kitchen/batch-timer", json={
        "stage": "adobo",
        "total_presas": 12,
        "duration_hours": 0.0
    })
    assert res_bad_dur.status_code == 400

    # 5. Valid stage case-insensitivity
    res_valid = client.post("/api/kitchen/batch-timer", json={
        "stage": "FRITURA",
        "total_presas": 8
    })
    assert res_valid.status_code == 200
    assert res_valid.json()["stage"] == "fritura"


def test_sqlite_engine_check_constraint_rejects_negative_stock(isolated_test_db):
    """Verify that the SQLite engine enforces CHECK (stock >= 0) at the database layer."""
    conn = database.get_db_connection()
    try:
        # Direct attempt to set negative stock must trigger IntegrityError
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            conn.execute("UPDATE inventory SET stock = -1.0 WHERE item_key = 'pechuga_vitrina'")
        assert "CHECK constraint failed" in str(exc_info.value)
    finally:
        conn.close()
```

---

## 4. Caveats
1. **Scope Boundary**: As Explorer 3, I perform read-only architectural analysis and produce actionable proposals; I do not directly modify application source code in `app/` or test suites in `tests/`.
2. **FastAPI Default Validation (422 vs 400)**: Using Pydantic `Field(..., gt=0)` on `total_presas` causes FastAPI to return HTTP 422 instead of HTTP 400. Because existing project conventions and tests expect HTTP 400 for business validation errors, the recommended approach is explicit validation inside `start_batch_timer` raising `HTTPException(status_code=400)`.
3. **Other Milestones**: Milestone M3 introduces stage transitions (`salmuera -> adobo -> fritura -> terminado`) and active timer cleanup. The proposed `VALID_BATCH_STAGES` whitelist is strictly scoped to batch creation (`salmuera`, `adobo`, `fritura`), which directly aligns with M3 design.

---

## 5. Conclusion
- The input validation vulnerabilities in `app/routers/kitchen.py:start_batch_timer` and the missing database engine constraint in `app/database.py` have been diagnosed and verified with complete root-cause tracing.
- The proposed fix strategy:
  1. Enforces strict input validation on `stage`, `total_presas`, and `duration_hours` returning HTTP 400 before opening database connections.
  2. Embeds `CHECK (stock >= 0)` into the `inventory` schema and provides an idempotent SQLite migration for existing database files.
  3. Fixes daily batch counter sequence numbering across days.
- Implementing these changes will resolve Finding 2 from Reviewer 2, unblock gate certification, and ensure permanent defense-in-depth data integrity.

---

## 6. Verification Method

To independently verify this analysis:

1. **Verify Existing Tests Pass**:
   ```powershell
   pytest tests/test_milestone_m1.py tests/test_tier1_features.py tests/test_tier2_boundaries.py -v
   ```
   *Expected*: All 82 tests pass cleanly.

2. **Verify SQLite CHECK Constraint & Migration Logic**:
   ```powershell
   python .agents\teamwork\explorer_m1_fix_3\scratch_test.py
   ```
   *Expected*: Outputs `Verified: SQLite engine CHECK constraint raised IntegrityError as expected: CHECK constraint failed: stock >= 0`.

3. **Invalidation Conditions**:
   Once Worker M1 implements the fixes:
   - `client.post("/api/kitchen/batch-timer", json={"stage": "invalid", "total_presas": 10})` must return HTTP 400.
   - `client.post("/api/kitchen/batch-timer", json={"stage": "fritura", "total_presas": -5})` must return HTTP 400.
   - Direct SQL execution `UPDATE inventory SET stock = -1` must fail with `sqlite3.IntegrityError: CHECK constraint failed: stock >= 0`.
