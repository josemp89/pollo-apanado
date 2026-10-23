## 2026-10-21T04:49:37Z
You are worker_cash_antifraud (role: teamwork_preview_worker).
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_cash_antifraud\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

CRITICAL: Before writing any code, thoroughly read:
1. `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md` (specifically section `## 2026-10-21T04:39:26Z`).
2. `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`.
3. `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\orchestrator_gen3\SYNTHESIS.md`.
4. Explorer reports:
   - `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_cash_1\analysis.md`
   - `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_antifraud_2\analysis.md`
   - `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_vitrina_3\analysis.md`

You have EXCLUSIVE write ownership of:
- `app/database.py`
- `app/routers/pos.py`
- `app/routers/cash.py`
- `app/templates/index.html`
- `app/static/js/pos.js`
- `app/templates/cash.html`
- `tests/conftest.py`
- `tests/test_audit_r1_to_r5.py`

Implementation Checklist:
1. Database & Pytest Isolation:
   - In `app/database.py`: define `DB_PATH = None` at module level, make `get_db_path()` prioritize `DB_PATH` if not None, then `DATABASE_PATH` env var, then default.
   - In `tests/conftest.py`: ensure isolated test DB fixture sets `database.DB_PATH` and initializes database properly.
   - In `app/database.py` `init_db()`:
     - Table `cash_shifts` (id, shift_code UNIQUE, date_str, opened_at, closed_at, cashier_name, base_inicial, cash_sales, digital_sales, datafono_sales, total_sales, total_expenses, expected_cash, actual_cash, difference, closing_notes, status CHECK ('abierto', 'cerrado')).
     - Table `cash_expenses` (id, shift_id, timestamp, date_str, amount, category, concept, authorized_by, recipient, receipt_number).
     - Table `sale_cancellation_audit` (id, sale_id, sale_code, cancelled_at, date_str, time_str, total_amount, payment_method, reason, authorized_by, pin_used_masked, restored_items_json, restored_presas_summary, restored_inventory_json).
     - Triggers `trg_prevent_cancellation_audit_update` and `trg_prevent_cancellation_audit_delete` on `sale_cancellation_audit` raising `ABORT`.
     - Table `vitrina_audits` (id, timestamp, date_str, time_str, auditor, pechugas_teorico, pechugas_fisico, pechugas_diff, muslos_teorico, muslos_fisico, muslos_diff, contramuslos_teorico, contramuslos_fisico, contramuslos_diff, alas_teorico, alas_fisico, alas_diff, total_teorico, total_fisico, total_diff, has_discrepancy, has_theft_alert, theft_alert_detail, notes, inventory_adjusted).
     - Idempotent addition of `shift_id` to `sales`.
     - Seed `admin_pin = '4321'` in `system_settings` if not exists.

2. POS Router & Antifraud PIN (R3):
   - Model `CancelSaleRequest(pin: str, reason: Optional[str] = "Error de digitación", authorized_by: Optional[str] = "Administrador")`.
   - Update `POST /api/pos/cancel-sale/{sale_id}` and add alias `POST /api/pos/cancel/{sale_id}`.
   - Enforce PIN validation against `os.environ.get("ADMIN_PIN")` or DB setting using `secrets.compare_digest`.
   - Return strict `HTTP 403 Forbidden` if PIN is missing, empty, or invalid.
   - Accept PIN from JSON body, header `X-Admin-PIN`, or query `?pin=`.
   - On valid PIN: set status `'anulada'`, restore inventory, calculate presas restored, insert full record into `sale_cancellation_audit`.
   - In `process_checkout`: if active shift exists in `cash_shifts`, associate `shift_id`.

3. Cash Router (R1, R2, R4):
   - `GET /api/cash/current-shift`: returns active shift or null.
   - `POST /api/cash/open-shift`: opens shift with `cashier_name` and `base_inicial`.
   - `POST /api/cash/close-shift`: calculates `expected_cash = base_inicial + cash_sales - total_expenses` and `difference = actual_cash - expected_cash`.
   - `POST /api/cash/expense`: records expense from cash drawer.
   - `GET /api/cash/expenses`: lists expenses.
   - `GET /api/cash/vitrina-status`: returns live vitrina stock and today's cancelled presas summary.
   - `POST /api/cash/vitrina-audit`: records physical counts, computes discrepancies (`fisico - teorico`), computes theft correlation if cancelled sale presas are missing from physical count (`min(|diff|, cancelled)`), sets `has_theft_alert = True`.
   - `GET /api/cash/vitrina-audits`: lists audit records.
   - Enriched `GET /api/cash/daily-summary`: returns `cash_reconciliation` (explicit formula), `product_breakdown` (exhaustive: presas solas, combos, almuerzos by chosen presa, portions, gaseosas Postobón vs Coca-Cola, with 100% sum and zero drift verification), and `cancellations_audit`.

4. Frontend POS (`app/templates/index.html` & `app/static/js/pos.js`):
   - Replace simple `confirm()` with `#adminPinModal` (PIN keypad, reason dropdown, authorizer name).
   - On 403, display prominent error feedback.

5. Frontend Cash (`app/templates/cash.html`):
   - Shift status bar with open/close/expense buttons and active shift info.
   - Explicit Arqueo Planilla: `Base Inicial + Ventas Efectivo - Gastos Menores = Efectivo Esperado` vs `Efectivo Físico Contado` -> `Diferencia / Cuadre`.
   - Independent panels for Nequi/Daviplata and Datáfono.
   - Red Alert Card `#cancellationsAlertCard` for cancelled sales with refunded money, returned presas, and discrepancy matching.
   - Vitrina Physical Arqueo Section: inputs for Pechuga, Muslo, Contramuslo, Ala, with live discrepancy indicators and theft alert.
   - Exhaustive product sales breakdown table summing to 100%.

6. Automated Tests (`tests/test_audit_r1_to_r5.py`):
   - Implement comprehensive pytest suite covering all 5 requirements:
     - Shift opening & expected cash formula.
     - 100% COP sales breakdown reconciliation.
     - HTTP 403 on cancellation without PIN or with wrong PIN.
     - Success with valid PIN & forensic log entry in `sale_cancellation_audit`.
     - Inmutability of audit table (triggers prevent update/delete).
     - Vitrina physical arqueo discrepancy calculation.
     - Fraud correlation alert when cancelled presas are missing from physical count.
   - Run pytest and ensure 100% passing tests!
