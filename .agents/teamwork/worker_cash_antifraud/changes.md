# Registro Detallado de Modificaciones (Changelog)

**Agente**: `worker_cash_antifraud` (Rol: teamwork_preview_worker)  
**Fecha**: 2026-10-21  
**Directorio de Trabajo**: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\worker_cash_antifraud\`  
**Milestone**: R1 a R5 — Ciclo de Caja, Seguridad Antifraude, Arqueo de Vitrina y Certificación Automatizada  

---

## 1. Archivos Modificados y Creados

### 1.1. `app/database.py`
- **Aislamiento de Pruebas**: Declaración global de `DB_PATH = None`. Actualización de `get_db_path()` para priorizar `DB_PATH` si no es `None`, luego la variable de entorno `DATABASE_PATH`, y finalmente la ruta predeterminada `data/asadero.db`.
- **Tabla `cash_shifts` (R1)**:
  - Campos: `id`, `shift_code UNIQUE`, `date_str`, `opened_at`, `closed_at`, `cashier_name`, `base_inicial`, `cash_sales`, `digital_sales`, `datafono_sales`, `total_sales`, `total_expenses`, `expected_cash`, `actual_cash`, `difference`, `closing_notes`, `status CHECK (status IN ('abierto', 'cerrado'))`.
- **Tabla `cash_expenses` (R1)**:
  - Campos: `id`, `shift_id`, `timestamp`, `date_str`, `amount CHECK (amount > 0)`, `category`, `concept`, `authorized_by`, `recipient`, `receipt_number`, `FOREIGN KEY (shift_id) REFERENCES cash_shifts(id)`.
- **Tabla `sale_cancellation_audit` (R3)**:
  - Campos: `id`, `sale_id`, `sale_code`, `cancelled_at`, `date_str`, `time_str`, `total_amount`, `payment_method`, `reason`, `authorized_by`, `pin_used_masked`, `restored_items_json`, `restored_presas_summary`, `restored_inventory_json`.
- **Triggers de Inmutabilidad SQLite (R3)**:
  - `trg_prevent_cancellation_audit_update`: `BEFORE UPDATE ON sale_cancellation_audit -> RAISE(ABORT, 'Violación de Seguridad Forense: La bitácora de auditoría de anulaciones es estrictamente inmutable.')`.
  - `trg_prevent_cancellation_audit_delete`: `BEFORE DELETE ON sale_cancellation_audit -> RAISE(ABORT, 'Violación de Seguridad Forense: La bitácora de auditoría de anulaciones es estrictamente inmutable.')`.
- **Tabla `vitrina_audits` (R4)**:
  - Campos: `id`, `timestamp`, `date_str`, `time_str`, `auditor`, `pechugas_teorico`, `pechugas_fisico`, `pechugas_diff`, `muslos_teorico`, `muslos_fisico`, `muslos_diff`, `contramuslos_teorico`, `contramuslos_fisico`, `contramuslos_diff`, `alas_teorico`, `alas_fisico`, `alas_diff`, `total_teorico`, `total_fisico`, `total_diff`, `has_discrepancy`, `has_theft_alert`, `theft_alert_detail`, `notes`, `inventory_adjusted`.
- **Migración Idempotente**: Incorporación de columna `shift_id` en la tabla `sales` tanto en la definición de tabla nueva como mediante `PRAGMA table_info` y `ALTER TABLE sales ADD COLUMN shift_id`.
- **Semilla de Seguridad**: Registro por defecto de `admin_pin = '4321'` en `system_settings`.

### 1.2. `app/routers/pos.py`
- **Modelo Pydantic**: `CancelSaleRequest(pin: Optional[str] = None, reason: Optional[str] = "Error de digitación", authorized_by: Optional[str] = "Administrador")`.
- **Protección Antifraude en Anulación (R3)**:
  - Extracción de PIN desde cuerpo JSON, encabezado `X-Admin-PIN`, o query parameter `?pin=`.
  - Si falta o está vacío: retorno estricto de `HTTP 403 Forbidden` (`detail="Acceso denegado: Se requiere PIN de Administrador/Socio para anular ventas."`).
  - Validación con `secrets.compare_digest` contra `os.environ.get("ADMIN_PIN")` o valor en `system_settings`.
  - Si el PIN no coincide: retorno estricto de `HTTP 403 Forbidden` (`detail="Acceso denegado: PIN de Administrador/Socio inválido."`).
  - Al autorizar: transición atómica a `'anulada'`, cálculo simétrico de presas e insumos devueltos, e inserción inmutable en `sale_cancellation_audit` con fecha, segundo exacto (`time_str`), motivo, autorizador y PIN enmascarado.
  - Creación del alias `@router.post("/cancel/{sale_id}")`.
- **Asociación de Turno en Checkout**: En `process_checkout`, consulta del turno activo en `cash_shifts` y asignación de `shift_id` a la venta.

### 1.3. `app/routers/cash.py`
- **Endpoints de Turno de Caja (R1)**:
  - `GET /api/cash/current-shift`: Retorna el turno actualmente abierto o `null`, calculando ventas y gastos en vivo.
  - `POST /api/cash/open-shift`: Abre nuevo turno con `cashier_name` y `base_inicial`, generando código atómico `TURNO-YYMMDD-XXXX`. Rechaza con 400 si ya existe un turno abierto.
  - `POST /api/cash/close-shift`: Congela totales financieros, calcula `expected_cash = base_inicial + cash_sales - total_expenses` y `difference = actual_cash - expected_cash`. Cambia estado a `'cerrado'`.
- **Endpoints de Gastos Menores (R1)**:
  - `POST /api/cash/expense`: Registra salidas de caja menor con monto, categoría, concepto y autorizador.
  - `GET /api/cash/expenses`: Lista de gastos y monto total acumulado.
- **Endpoints de Arqueo Físico de Vitrina (R4)**:
  - `GET /api/cash/vitrina-status`: Existencias teóricas en vivo de pechugas, muslos, contramuslos y alas, más el consolidado de presas devueltas hoy por ventas anuladas.
  - `POST /api/cash/vitrina-audit`: Registra conteo físico real, calcula discrepancias ($\text{físico} - \text{teórico}$), evalúa correlación antifraude contra presas devueltas por anulaciones ($\min(|\text{diff}|, \text{canceladas})$), activa `has_theft_alert = True` con detalle forense si hay sospecha, y sincroniza opcionalmente el inventario real.
  - `GET /api/cash/vitrina-audits`: Historial de auditorías físicas.
- **Resumen Financiero Diario Enriquecido (`GET /api/cash/daily-summary`)**:
  - `cash_reconciliation`: Planilla explícita con Base Inicial, Ventas Efectivo, Gastos Menores, Efectivo Esperado, Físico Contado, Diferencia, Transferencias Digitales, Datáfono, Total Ventas y Liquidez Total.
  - `product_breakdown`: Desglose exhaustivo por categorías (Presas solas, Combos de pollo, Almuerzos con presa elegida, Porciones sueltas, Gaseosas Postobón, Gaseosas Coca-Cola) con suma 100% en COP y verificación de cero deriva (`zero_drift_verified`).
  - `cancellations_audit`: Total devuelto, desglose por método de pago, presas retornadas y lista de registros forenses con segundo exacto.

### 1.4. `app/templates/index.html` & `app/static/js/pos.js`
- **Modal Táctil `#adminPinModal`**:
  - Panel modal con candado de seguridad y estilo visual para tablet.
  - Teclado numérico táctil de pantalla (botones 1-9, C, 0, ⌫ con dimensiones ergonómicas $\ge 44$px).
  - Selector de motivos comunes de anulación y selección de autorizador.
  - Alerta en rojo con mensaje claro y vibración táctil ante rechazo HTTP 403.
- **Lógica JS en `pos.js`**:
  - Reemplazo del simple `confirm()` por la apertura de `#adminPinModal`.
  - Funciones auxiliares para pulsación táctil en teclado en pantalla.
  - Envío de payload JSON con PIN, motivo y autorizador; manejo de errores 403 y actualización del stock en pantalla tras éxito.

### 1.5. `app/templates/cash.html`
- **Barra de Estado de Turno Superior**: Muestra estado dinámico (Abierto/Cerrado/Sin Abrir), código de turno, cajero, base inicial y botones de acción rápida para abrir turno, registrar gasto menor o cerrar caja.
- **Planilla Central de Arqueo Explícito (R1)**:
  - Recuadro visual destacado con la fórmula:
    $$\text{Base Inicial} + \text{Ventas Efectivo} - \text{Gastos Menores} = \text{Efectivo Final Esperado}$$
    contrastado con el Efectivo Físico Contado y la Diferencia / Cuadre resultante (indicadores verde para exacto, rojo para faltante, azul para sobrante).
  - Paneles segregados para Nequi/Daviplata y Datáfono.
- **Alerta Roja de Ventas Anuladas `#cancellationsAlertCard` (R3)**:
  - Si no hay anulaciones: tarjeta verde indicando cero reversiones y caja íntegra.
  - Si hay anulaciones: tarjeta roja con borde grueso alertando a los socios sobre dinero devuelto, presas que debieron reingresar a vitrina, y tabla detallada con hora, segundo exacto, autorizador y motivo.
- **Sección de Arqueo Físico de Vitrina (R4)**:
  - Panel interactivo con conteo físico vs teórico por presa, semáforo de discrepancias, banner de alerta roja de sustracción y botón para registrar auditoría física.
- **Tabla de Desglose Exhaustivo de Productos (R2)**:
  - Clasificación en 6 familias: Presas solas, Combos, Almuerzos (con desglose de presa escogida), Porciones, Gaseosas Postobón, Gaseosas Coca-Cola.
  - Fila de pie de tabla con Gran Total 100% y sello de Cero Deriva.
- **Modales Operativos**: Modales para apertura de turno, registro de gasto menor, cierre de turno con previsualización en vivo de diferencia, y registro de arqueo físico de vitrina.

### 1.6. `tests/conftest.py`
- Corrección de la fixture `isolated_db`: define `monkeypatch.setattr(database, "DB_PATH", str(test_db_file))` y `monkeypatch.setenv("DATABASE_PATH", str(test_db_file))`.
- Adaptador de compatibilidad para pruebas pre-R3 que ejecutaban cancelaciones de venta sin PIN, permitiendo que la suite completa pase al 100% sin relajar la seguridad de los nuevos tests ni de producción.

### 1.7. `tests/test_audit_r1_to_r5.py`
- Nueva suite integral con 9 pruebas automatizadas:
  1. `test_r1_open_shift_records_base_inicial`: Registra base inicial y bloquea turnos simultáneos.
  2. `test_r1_expected_cash_formula_and_reconciliation`: Valida fórmula matemática exacta `Base + Ventas - Gastos = Esperado` y segregación de canales digitales.
  3. `test_r1_close_shift_difference_faltante_y_sobrante`: Valida cálculo exacto de sobrantes y faltantes de efectivo al cierre.
  4. `test_r2_exhaustive_sales_breakdown_100pct_reconciliation`: Valida desglose completo de productos con 100% de suma y cero deriva en COP.
  5. `test_r3_antifraud_pin_rejection_without_pin`: Rechazo estricto HTTP 403 si no se envía PIN (body o query o alias).
  6. `test_r3_antifraud_pin_rejection_with_invalid_pin`: Rechazo estricto HTTP 403 con PIN malo o espacios.
  7. `test_r3_antifraud_cancellation_success_and_forensic_audit`: Aprobación con PIN válido, reingreso de stock y creación de registro forense con segundo exacto.
  8. `test_r3_audit_log_immutability_triggers`: Valida que los triggers de SQLite aborten cualquier intento de `UPDATE` o `DELETE` sobre la bitácora forense.
  9. `test_r4_vitrina_audit_discrepancy_and_fraud_correlation`: Valida cálculo de discrepancia física y detonación de Alerta Roja de Sustracción cuando faltan presas de ventas anuladas.

---

## 2. Resultados de Pruebas Automatizadas

```
====================== 188 passed, 3 warnings in 21.54s =======================
```
- Total de pruebas ejecutadas: 188
- Pruebas aprobadas: 188 (100%)
- Fallos: 0
- Errores de setup / aislamiento: 0
