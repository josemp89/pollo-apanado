# Handoff Report — explorer_antifraud_2

**Task**: Requirement R3: Antifraud Security Module & Forensic Audit  
**Type**: Hard Handoff (Investigation Complete)  
**Date**: 2026-10-21T04:47:00Z  
**Author**: `explorer_antifraud_2` (teamwork_preview_explorer)  
**Target Recipient**: `orchestrator_gen3` / builder agents

---

## 1. Observation

1. **Sale Cancellation Endpoint**:
   - In `app/routers/pos.py:322`, the endpoint is `@router.post("/cancel-sale/{sale_id}")`.
   - Function signature: `def cancel_sale(sale_id: int):`.
   - The path `/api/pos/cancel/{id}` does **NOT** exist anywhere in the codebase.
   - The endpoint accepts no payload, headers, or parameters for authentication. Any caller can cancel any sale with a simple POST request.

2. **Frontend POS Cancellation**:
   - `app/templates/pos.html` does **NOT** exist; the POS interface is rendered by `app/templates/index.html` at route `/`.
   - In `app/templates/index.html:71-80`, the banner `#lastSaleBanner` exposes button `#btnUndoSale` with `onclick="cancelLastSale()"`.
   - In `app/static/js/pos.js:706-723`:
     ```javascript
     async function cancelLastSale() {
       if (!lastSaleId) return;
       if (!confirm("¿Seguro que deseas anular la última venta y devolver los productos al inventario?")) return;
       try {
         const res = await fetch(`/api/pos/cancel-sale/${lastSaleId}`, { method: 'POST' });
     ```
     A standard browser `confirm()` dialog is used with zero PIN check, zero reason capture, and zero role validation.

3. **Database Audit & Immutability**:
   - In `app/database.py:27-140`, tables exist for `products`, `inventory`, `sales`, `sale_items`, `butchering_logs`, `cooking_batches`, `system_settings`, `order_counters`.
   - There is **no table** for cancellation audit or forensic logging.
   - When a sale is cancelled in `pos.py:330-333`, `sales.status` is set to `'anulada'`, but no entry is made recording the authorizer, reason, exact second, or presas restored.

4. **Cash Closing Report**:
   - In `app/routers/cash.py:22-30`, `sales` are queried with `WHERE date_str = ? AND status = 'completada'`.
   - Cancelled sales are silently excluded from totals without generating any audit metrics, alert flags, refunded money summaries, or restored presas counts.
   - In `app/templates/cash.html`, there is no visual alert or section dedicated to cancelled sales or fraud detection.

5. **Test Infrastructure Issue**:
   - Running `pytest` produces 179 errors due to `AttributeError: <module 'app.database' from '...'> has no attribute 'DB_PATH'` triggered at `tests/conftest.py:22` because `app/database.py` does not declare `DB_PATH = None` at module scope.

---

## 2. Logic Chain

1. **From Observation 1 & 2 to Fraud Vulnerability**:
   Because `cancel_sale` in `app/routers/pos.py` requires no credentials and `app/static/js/pos.js` only prompts with `confirm()`, a cashier can take cash from a customer, register the sale, undo it immediately, pocket the cash, and leave the cash drawer balanced with zero expected cash.
2. **From Observation 1 to Endpoint Compatibility**:
   Because existing M1 tests (`tests/test_milestone_m1.py`, etc.) and frontend invoke `/api/pos/cancel-sale/{sale_id}`, changing the route abruptly to `/api/pos/cancel/{id}` would break existing components. Therefore, `/api/pos/cancel-sale/{sale_id}` must remain the primary endpoint, with `/api/pos/cancel/{sale_id}` added as an alias.
3. **From Observation 3 to Forensic Audit Table & Engine Immutability**:
   Requirement R3 dictates that cancellations must be permanently recorded with exact second, authorizer, and reason. By creating table `sale_cancellation_audit` and attaching SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers that raise `RAISE(ABORT, ...)`, the log cannot be modified or deleted even if application code or an admin attempts to tamper with it.
4. **From Observation 2 & Requirement R3 to PIN Security & HTTP 403**:
   To enforce partner-level authorization, the endpoint must validate the supplied PIN against `os.environ.get("ADMIN_PIN")` or `system_settings` (default `'4321'`). Any request with a missing, empty, or wrong PIN must be rejected strictly with `HTTP 403 Forbidden` using constant-time comparison (`secrets.compare_digest`).
5. **From Observation 4 to Red Alert in Cash Report**:
   Because cash closing currently ignores cancellations, owners cannot see if cash was refunded. Incorporating `sale_cancellation_audit` data into `GET /api/cash/daily-summary` and rendering a prominent red banner in `cash.html` provides immediate visibility into refunded cash and presas that should be in the display case.
6. **From Observation 5 to Test Suite Fix**:
   Declaring `DB_PATH = None` in `app/database.py` and updating `get_db_path()` enables `tests/conftest.py`'s `monkeypatch.setattr(database, "DB_PATH", ...)` to work, unblocking all test suites.

---

## 3. Caveats

- **Scope Limitation**: As an explorer subagent, no application source code files were edited during this step; all concrete code changes are prepared as recommendations for the builder agent.
- **PIN Multi-tenancy**: The design supports a master PIN (default `'4321'`) with capability to expand to per-partner PINs (`partner_1_pin`, `partner_2_pin`, `partner_santiago_pin`).
- **Existing Tests Impact**: When the builder implements the strict HTTP 403 requirement for missing PINs, existing tests in `test_milestone_m1.py` and `test_tier1_features.py` that call `client.post(f"/api/pos/cancel-sale/{sale_id}")` without a body or header will receive HTTP 403. The builder will need to update them to supply `{"pin": "4321"}` (or header `X-Admin-PIN: 4321`) when testing successful cancellation.

---

## 4. Conclusion

Requirement R3 can be cleanly and robustly implemented by:
1. Adding `DB_PATH = None` to `app/database.py` to fix the test suite fixture.
2. Creating `sale_cancellation_audit` table with immutable SQLite triggers.
3. Hardening `cancel_sale` in `app/routers/pos.py` with `CancelSaleRequest` model, rejecting unauthorized calls with HTTP 403, and creating the alias `/api/pos/cancel/{sale_id}`.
4. Updating `app/routers/cash.py` and `app/templates/cash.html` to display the prominent red alert card showing refunded money and returned presas.
5. Updating `app/templates/index.html` and `app/static/js/pos.js` to replace `confirm()` with a touch-friendly Admin PIN modal.

All architectural specifications, DDL, Pydantic schemas, and endpoint designs are documented in `analysis.md`.

---

## 5. Verification Method

Once the builder implements these changes:
1. **Automated Pytest Suite**:
   Run: `pytest tests/test_antifraud_forensic.py -v`
   Verify:
   - Cancellation without PIN returns `403`.
   - Cancellation with invalid PIN returns `403`.
   - Cancellation with valid PIN returns `200` and creates audit record in `sale_cancellation_audit`.
   - Direct `UPDATE` or `DELETE` on `sale_cancellation_audit` raises SQLite abort error.
   - `GET /api/cash/daily-summary` reflects cancelled count, refunded amount, and returned presas.
2. **Template Inspection**:
   - Inspect `app/templates/index.html` to confirm `#adminPinModal` exists.
   - Inspect `app/templates/cash.html` to confirm `#cancellationsAlertCard` / red alert container exists.
3. **Manual Flow Verification**:
   - Start server: `python run_server.py`.
   - Perform checkout at `http://localhost:8000/`.
   - Click "Deshacer venta" -> Admin PIN modal must appear.
   - Enter invalid PIN -> Alert displays error (HTTP 403).
   - Enter valid PIN (`4321`) -> Sale is cancelled.
   - Visit `http://localhost:8000/caja` -> Red alert box displays the cancelled sale, amount refunded, and presas returned.
