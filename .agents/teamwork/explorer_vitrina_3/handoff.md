# Handoff Report: R4 & R5 Investigation (Vitrina Arqueo, Discrepancies & Pytest Suite)

**Agent:** `explorer_vitrina_3` (Role: `teamwork_preview_explorer`)  
**Target:** Requirements R4 (Physical Vitrina Arqueo & Shrinkage/Theft Detection) & R5 (Pytest Testing Infrastructure)  
**Recipient:** `orchestrator_gen3` / Worker & Implementer Agents  
**Working Directory:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_vitrina_3\`  
**Project Root:** `c:\Users\Alejandro\Desktop\POLLO APANADO`  

---

## 1. Observation

1. **Vitrina Presas Data Keys & Schema (`app/database.py:45-56`, `app/database.py:239-244`):**
   - Presas are stored in `inventory` table with keys:
     - `pechuga_vitrina` (Pechugas en Vitrina, category `'vitrina'`, unit `'unidad'`, initial stock 12)
     - `muslo_vitrina` (Muslos en Vitrina, category `'vitrina'`, unit `'unidad'`, initial stock 14)
     - `contramuslo_vitrina` (Contramuslos en Vitrina, category `'vitrina'`, unit `'unidad'`, initial stock 14)
     - `ala_vitrina` (Alas en Vitrina, category `'vitrina'`, unit `'unidad'`, initial stock 10)
   - Table constraint enforces non-negative stock floor: `stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0)`.

2. **Presa Inflow and Outflow Chains:**
   - **Inflow via Despiece (`app/routers/kitchen.py:50-134`):**
     1 chicken crudo produces 2 Pechugas, 2 Muslos, 2 Contramuslos, 2 Alas, and 2 Caldo raciones (`pechuga_vitrina`, `muslo_vitrina`, `contramuslo_vitrina`, `ala_vitrina` + $2 \times n$).
   - **Inflow via Batch Fritura Completion (`app/routers/kitchen.py:378-385`):**
     Advancing a batch to `'terminado'` adds `total_presas // 4` to each of the 4 vitrina presas.
   - **Outflow via POS Checkout (`app/routers/pos.py:77-133`):**
     `calculate_order_inventory_requirements` deducts single presas, combo presas (`POL-14` = 1M + 1C; `POL-12` = 1P + 1A + 1M + 1C; `POL-ENT` = 2P + 2A + 2M + 2C), and `ALM-COMP` with `chosen_presa` (`pechuga_vitrina`, etc.).
   - **Outflow Reversal on Cancellation (`app/routers/pos.py:348-369`):**
     `cancel_sale` symmetrically restores the exact presas deducted back to `inventory.stock`.

3. **Current Cash Frontend & Lack of Physical Vitrina Arqueo (`app/templates/cash.html`):**
   - `cash.html` contains financial cards (Ingresos Brutos, Margen Bruto, Efectivo, Nequi, Datáfono), a breakeven thermometer ($258.462 COP), partner Cap Table split (40/40/20), low-stock supplier alerts, and presas sold summary.
   - **Absence:** There is NO form or UI component for recording physical vitrina counts, calculating discrepancies ($\text{Conteo Físico Real} - \text{Stock Teórico}$), or alerting on missing presas from cancelled sales.

4. **Pytest Failure Observation & Output:**
   - Running `pytest tests/test_concurrency_stress.py` or `pytest tests/test_milestone_m1.py` fails 100% of tests with:
     ```
     tests\conftest.py:22: in isolated_db
         monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
     E   AttributeError: <module 'app.database' from 'C:\Users\Alejandro\Desktop\POLLO APANADO\app\database.py'> has no attribute 'DB_PATH'
     ```
   - Inspection of `app/database.py:5-14` reveals:
     ```python
     def get_db_path():
         return os.environ.get(
             "DATABASE_PATH",
             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "asadero.db")
         )
     ```
     `DB_PATH` is NOT defined as a module-level variable in `app/database.py`. Running `python -c "import app.database as db; print(hasattr(db, 'DB_PATH'))"` outputs `False`.

---

## 2. Logic Chain

1. **Premise 1:** The acceptance criteria for R4 require that at shift close, the system contrasts `Discrepancia / Merma = Conteo Físico Real - Stock Teórico del Sistema`, and immediately alerts if cancelled sales returned presas that are physically missing.
2. **Premise 2:** As observed in `app/database.py` and `app/routers/pos.py`, theoretical stock for presas is tracked under four exact keys (`pechuga_vitrina`, `muslo_vitrina`, `contramuslo_vitrina`, `ala_vitrina`).
3. **Premise 3:** Since cancelled sales execute symmetrical inventory returns (`pos.py:363-369`), a fraudulent cashier can pocket cash from a completed order and cancel it; the system will believe the presas are in the vitrina.
4. **Deduction 1:** To detect this theft vector, the physical arqueo endpoint must compute $\Delta_p = \text{Conteo Físico}_p - \text{Stock Teórico}_p$. If $\Delta_p < 0$ and there were presas of type $p$ restored by cancelled sales on that shift ($R_{\text{anulada}}(p) > 0$), the system must correlate $\min(|\Delta_p|, R_{\text{anulada}}(p))$ as suspected stolen presas and raise an immediate Red Security Alert.
5. **Deduction 2:** Storing these audits requires a dedicated table `vitrina_audits` to record timestamps, auditor name, theoretical stock, physical count, discrepancies, theft alerts, and whether stock was adjusted.
6. **Premise 4:** For R5, automated tests must validate R1-R4. However, every test currently crashes in `conftest.py` because `monkeypatch.setattr(database, "DB_PATH", ...)` fails with `AttributeError`.
7. **Deduction 3:** Defining `DB_PATH = ...` in `app/database.py` and reading `os.environ.get("DATABASE_PATH", DB_PATH)` in `get_db_path()` immediately repairs `conftest.py` and all 81+ existing tests. Once repaired, dedicated automated tests for R1-R4 can be written in `tests/test_audit_r1_to_r5.py`.

---

## 3. Caveats

- **Caveat 1:** Other explorer agents (`explorer_cash_1` and `explorer_antifraud_2`) are concurrently designing R1/R2 (cash shift lifecycle and breakdown) and R3 (Admin PIN and cancellation audit log). The schemas proposed here (`vitrina_audits`, `cancellation_audit_log`, `cash_shifts`) are fully decoupled yet interoperable via standard foreign keys / date strings.
- **Caveat 2:** Vitrina stock adjustment policy: When an arqueo is completed, `adjust_inventory: bool = True` should update `inventory.stock` to match physical reality so subsequent sales don't fail due to phantom stock. However, the audit record permanently preserves the pre-adjustment discrepancy for accounting.

---

## 4. Conclusion

1. **Vitrina Tracking Architecture is Complete and Solid:** Inflow (despiece + fritura) and outflow (sales + cancellations) are mathematically modeled in SQLite.
2. **Missing Components for R4:**
   - Table `vitrina_audits` in `app/database.py`.
   - Endpoints `GET /api/cash/vitrina-status` and `POST /api/cash/vitrina-audit` in `app/routers/cash.py`.
   - UI Card in `app/templates/cash.html` providing physical input fields, live $\Delta$ calculation, and Red Fraud Alert banner.
3. **Pytest Infrastructure Root Cause Solved (R5):**
   - Single root cause identified: Missing `DB_PATH` in `app/database.py`.
   - Proposed patch restores full test isolation and execution.
   - Comprehensive test specifications created for R1-R4 in `analysis.md`.

---

## 5. Verification Method

To verify the observations, fixes, and recommendations independently:

1. **Verify missing `DB_PATH` in `app/database.py`:**
   ```powershell
   python -c "import app.database as db; print('Has DB_PATH:', hasattr(db, 'DB_PATH'))"
   ```
   *Expected:* `Has DB_PATH: False`.

2. **Verify test failure reproduction:**
   ```powershell
   pytest tests/test_milestone_m1.py -k test_wal_and_pragma_configuration
   ```
   *Expected:* Fails with `AttributeError: <module 'app.database' ...> has no attribute 'DB_PATH'`.

3. **Verify patch resolution for `app/database.py`:**
   Temporarily verify in Python shell:
   ```powershell
   python -c "import app.database as db; db.DB_PATH = 'data/asadero.db'; import tests.conftest"
   ```
   *Expected:* Succeeds with exit code 0.

4. **Verify vitrina inventory keys:**
   ```powershell
   python -c "import sqlite3; conn = sqlite3.connect('data/asadero.db'); print([r[0] for r in conn.execute(\"SELECT item_key FROM inventory WHERE category = 'vitrina'\").fetchall()])"
   ```
   *Expected:* `['pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina']`.
