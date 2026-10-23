## 2026-10-21T02:55:27Z
You are the Worker agent for Milestone M2 of the "Pollo Apanado" project.
Your working directory is: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m2\`
Project root: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Authoritative user request file: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\ORIGINAL_REQUEST.md`
Project master specification: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\PROJECT.md`

You MUST read `ORIGINAL_REQUEST.md` and `PROJECT.md` before starting work.
Also read the detailed Explorer handoffs:
- `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_m2_1\handoff.md` (Live stock & presa locking)
- `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_m2_2\handoff.md` (Server-side cash underpayment & validation)
- `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_m2_3\handoff.md` (Tablet ergonomics, cumulative fast cash, digital payment modal)

MANDATORY INTEGRITY WARNING — include this verbatim in your awareness:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your write ownership covers:
- `app/routers/pos.py`
- `app/templates/index.html`
- `app/static/js/pos.js`
- `app/static/css/style.css`
- `tests/test_milestone_m2.py`

Tasks to implement for Milestone M2:
1. Backend Checkout Validation & Exact Change (`app/routers/pos.py`):
   - Whitelist `payment_method` in `{'efectivo', 'nequi_daviplata', 'datafono'}`. Reject invalid with HTTP 400.
   - For cash (`efectivo`), strictly reject `cash_received is None or cash_received < total_amount` with `HTTPException(status_code=400, detail="Monto en efectivo insuficiente para cubrir el total de la orden.")`. Validate this before deducting stock.
   - Exact integer change: `change_returned = (payload.cash_received - total_amount) if payload.payment_method == "efectivo" else 0`.
2. Frontend Presa Modal & Live Stock Badges (`app/templates/index.html` & `app/static/js/pos.js`):
   - In `#presaModal`: Add explicit IDs for buttons (`btn-presa-pechuga`, etc.).
   - In `updateStockBadgesInModal()`: When `stockSummary[presa_key].stock <= 0`, set HTML `disabled=true`, `aria-disabled="true"`, visual styling `opacity-50 cursor-not-allowed pointer-events-none`, and badge `❌ Agotado (0 listas)`.
   - In `confirmPresaChoice(presa)`: Add defensive guard refusing selection if `stockSummary[key].stock <= 0`.
   - In `renderProducts()`: Show stock status badges on products and disable clicking on out-of-stock items (`opacity-50 cursor-not-allowed`).
3. Tablet Touch Ergonomics & Steppers:
   - In `app/static/js/pos.js:renderCart()` and `app/templates/index.html`:
     - Resize stepper buttons `+` and `-` to standard touch target >= 44x44px (`w-11 h-11`).
4. Cumulative Fast Cash Buttons & Digital Payment Modal:
   - In `#cashModal`: Make fast cash buttons cumulative (`addCashAmount(val)`), add a "Limpiar" button (`clearCashAmount()`), and keep "Pago Exacto".
   - In `app/templates/index.html`: Add `#digitalModal` confirmation modal for Nequi/Daviplata and Datáfono with total display, optional voucher reference input, "Confirmar" and "Cancelar" buttons.
   - In `app/static/js/pos.js`: Trigger `#digitalModal` when clicking digital payment buttons so checkout is not 1-touch accidental.
5. Create Test Suite (`tests/test_milestone_m2.py`):
   - Test cash underpayment rejected with HTTP 400.
   - Test exact cash payment accepted with change = 0.
   - Test overpayment accepted with exact change.
   - Test invalid payment methods rejected with HTTP 400.
   - Test digital payments accepted with change = 0.
   - Test presa selection stock boundaries.
6. Verify:
   - Run `pytest -v` across all test suites (including previous M1 and E2E suites). Ensure 100% tests pass.

Write your handoff report to `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_m2\handoff.md` and send a message when done.
