# Síntesis Arquitectónica y Especificación de Implementación: Requerimientos R1 a R5

## 1. Alcance y Objetivos
Implementación completa, auditoría y certificación de:
- **R1: Ciclo de Caja con Base Inicial y Arqueo Cierre Explícito**:
  - `Efectivo Esperado = Base Inicial + Ventas en Efectivo - Gastos Menores Autorizados`.
  - Segregación estricta de efectivo físico, transferencias Nequi/Daviplata y vouchers de datáfono.
- **R2: Desglose Exhaustivo de Presas, Combos y Dinero Recaudado**:
  - Desglose por presas solas, combos (1/4, 1/2, entero), almuerzos (con desglose de presas elegidas), porciones y gaseosas (Postobón vs Coca-Cola).
  - Suma 100% en COP con cero derivas matemáticas.
- **R3: Módulo Antifraude con PIN de Administrador y Bitácora Forense**:
  - Reversión/anulación estrictamente protegida con PIN de Administrador (HTTP 403 en falta o error).
  - Bitácora inmutable en SQLite con triggers `BEFORE UPDATE` y `BEFORE DELETE` con `RAISE(ABORT)`.
  - Recuadro en rojo de alerta en reporte de cierre de caja.
- **R4: Arqueo Físico de Vitrina y Reporte de Discrepancias**:
  - `Discrepancia = Conteo Físico Real - Stock Teórico`.
  - Correlación con ventas anuladas: si se anularon ventas y faltan esas presas en vitrina, detonar `🚨 ALERTA ROJA DE SUSTRACCIÓN NO AUTORIZADA`.
- **R5: Suite de Pruebas Automatizadas (pytest) y Certificación de Seguridad**:
  - Solución del error de setup en `tests/conftest.py` y `app/database.py` (`DB_PATH = None`).
  - Suite `tests/test_audit_r1_to_r5.py` validando los 4 requerimientos con 100% de éxito.

## 2. Componentes y Modificaciones Exactas

### 2.1. `app/database.py`
1. Declarar `DB_PATH = None` en el ámbito global del módulo y soportarlo en `get_db_path()`.
2. Crear tabla `cash_shifts` (id, shift_code, date_str, opened_at, closed_at, cashier_name, base_inicial, cash_sales, digital_sales, datafono_sales, total_sales, total_expenses, expected_cash, actual_cash, difference, closing_notes, status).
3. Crear tabla `cash_expenses` (id, shift_id, timestamp, date_str, amount, category, concept, authorized_by, recipient, receipt_number).
4. Crear tabla `sale_cancellation_audit` (id, sale_id, sale_code, cancelled_at, date_str, time_str, total_amount, payment_method, reason, authorized_by, pin_used_masked, restored_items_json, restored_presas_summary, restored_inventory_json).
5. Crear triggers `trg_prevent_cancellation_audit_update` y `trg_prevent_cancellation_audit_delete` impidiendo cualquier mutación sobre `sale_cancellation_audit`.
6. Crear tabla `vitrina_audits` (id, timestamp, date_str, time_str, auditor, pechugas_teorico, pechugas_fisico, pechugas_diff, muslos_teorico, muslos_fisico, muslos_diff, contramuslos_teorico, contramuslos_fisico, contramuslos_diff, alas_teorico, alas_fisico, alas_diff, total_teorico, total_fisico, total_diff, has_discrepancy, has_theft_alert, theft_alert_detail, notes, inventory_adjusted).
7. Añadir columna `shift_id` a `sales` si no existe.
8. Seed de `admin_pin = '4321'` en `system_settings` si no existe.

### 2.2. `app/routers/pos.py`
1. Pydantic model `CancelSaleRequest(pin: str, reason: Optional[str] = "Error de digitación", authorized_by: Optional[str] = "Administrador")`.
2. Proteger `POST /api/pos/cancel-sale/{sale_id}` y alias `POST /api/pos/cancel/{sale_id}`:
   - Validar PIN recibido (body, header `X-Admin-PIN`, o query `?pin=`) contra `os.environ.get("ADMIN_PIN")` o `system_settings('admin_pin')` usando `secrets.compare_digest`.
   - Si no coincide o falta: `raise HTTPException(status_code=403, detail="Acceso denegado: Se requiere PIN de Administrador/Socio válido.")`.
   - Al anular: actualizar estado a `'anulada'`, devolver stock simétrico, desglosar presas retornadas e insertar en `sale_cancellation_audit`.
3. En `process_checkout()`: si hay un turno abierto en `cash_shifts`, registrar `shift_id`.

### 2.3. `app/routers/cash.py`
1. Endpoints de turno y gastos:
   - `GET /api/cash/current-shift`
   - `POST /api/cash/open-shift` (cashier_name, base_inicial)
   - `POST /api/cash/close-shift` (actual_cash, notes) -> computa `expected_cash` y `difference`
   - `POST /api/cash/expense` (amount, category, concept, authorized_by)
   - `GET /api/cash/expenses`
2. Endpoints de vitrina:
   - `GET /api/cash/vitrina-status`
   - `POST /api/cash/vitrina-audit` -> calcula discrepancia y correlación con ventas anuladas
   - `GET /api/cash/vitrina-audits`
3. Enriquecer `GET /api/cash/daily-summary`:
   - `cash_reconciliation` (Base Inicial, Ventas Efectivo, Gastos Menores, Efectivo Esperado, Real, Diferencia, Digital, Datáfono).
   - `product_breakdown` (Presas solas, Combos, Almuerzos con chosen_presa, Porciones, Gaseosas Postobón, Gaseosas Coca-Cola, suma 100% y 0 deriva).
   - `cancellations_audit` (total devuelto, desglose por método, presas devueltas, registros forenses con segundo exacto).

### 2.4. Frontend: `app/templates/index.html` & `app/static/js/pos.js`
- Modal táctil para anular venta solicitando PIN numérico de 4 dígitos, motivo y nombre del autorizador.
- Manejo de HTTP 403 con alerta clara y vibración/estilo de error.

### 2.5. Frontend: `app/templates/cash.html`
- Barra superior de estado de turno con botones interactivos para abrir turno, registrar gasto menor y cerrar turno.
- Planilla central de arqueo de caja explícito: `(+) Base Inicial (+) Ventas Efectivo (-) Gastos Menores (=) Efectivo Esperado`.
- Paneles independientes para Nequi/Daviplata y Datáfono.
- Recuadro rojo `#cancellationsAlertCard` para auditoría de ventas anuladas y presas reingresadas.
- Formulario de Arqueo Físico de Vitrina con cálculo de discrepancia y alertas de sustracción sospechosa.
- Tabla detallada de ventas con el 100% de conciliación.

### 2.6. Pruebas: `tests/test_audit_r1_to_r5.py`
- Pruebas automatizadas con pytest para R1, R2, R3, R4 y R5.
