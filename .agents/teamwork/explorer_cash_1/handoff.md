# Handoff Report: Auditoría e Investigación R1 & R2 (Caja y Desglose Exhaustivo)

**De:** `explorer_cash_1` (teamwork_preview_explorer)  
**Para:** `orchestrator_gen3` e Implementadores de Backend/Frontend  
**Fecha:** 2026-10-21  
**Directorio de Trabajo:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_cash_1\`  
**Documento Técnico Completo:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_cash_1\analysis.md`

---

## 1. Observation (Observaciones Directas)

1. **Ausencia de Entidades de Turno y Caja Menor en SQLite:**
   - En `app/database.py` (líneas 27-139), se crean 8 tablas: `products`, `inventory`, `sales`, `sale_items`, `butchering_logs`, `cooking_batches`, `system_settings`, `order_counters`.
   - **No existe** tabla `cash_shifts` (ni `cash_register_sessions`). No hay registro de apertura de turno, fecha/hora de inicio, nombre del cajero ni `base_inicial`.
   - **No existe** tabla `cash_expenses` (ni `gastos_menores_autorizados`) para registrar desembolsos de efectivo desde el cajón metálico.
   - En la tabla `sales` (líneas 58-74), no existe columna `shift_id` para relacionar una venta con una sesión de caja específica.

2. **Cálculo de Efectivo Actual en `cash.py`:**
   - En `app/routers/cash.py` (líneas 21-38), el endpoint `/api/cash/daily-summary` computa:
     ```python
     sales_by_method = conn.execute("""
         SELECT payment_method, COUNT(*) as tickets, SUM(total_amount) as total
         FROM sales 
         WHERE date_str = ? AND status = 'completada'
         GROUP BY payment_method
     """, (date_str,)).fetchall()
     ```
   - Retorna `cash_summary["efectivo"]` como la suma simple de ventas en efectivo completadas en la fecha.
   - **No suma** ninguna base inicial ni **resta** gastos menores, violando la fórmula requerida de arqueo:
     `Efectivo Final Esperado en Cajón = Base Inicial + Ventas en Efectivo - Gastos Menores Autorizados`.

3. **Presentación Visual en `cash.html`:**
   - En `app/templates/cash.html` (líneas 61-69 y 225), la tarjeta "Efectivo en Cajón" muestra directamente `data.cash_summary.efectivo`.
   - No hay panel de arqueo de caja con desglose de la fórmula.
   - No hay botones ni modales para "Abrir Turno" con base inicial, "Registrar Gasto Menor", ni "Cerrar Turno" con conteo físico real y cálculo de sobrante/faltante.

4. **Desglose de Productos y Presas en `cash.py` y `cash.html`:**
   - En `app/routers/cash.py` (líneas 73-116), la consulta de presas suma coeficientes de pechugas, muslos, contramuslos y alas, pero:
     - No reporta el valor equivalente en dinero ($ COP) de las presas.
     - No reporta la cantidad ni el dinero recaudado de combos individuales (`POL-14`, `POL-12`, `POL-ENT`).
     - No reporta la cantidad ni el dinero recaudado de porciones sueltas (`POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`, `POR-AREP`).
     - No separa las gaseosas por marca (Postobón vs Coca-Cola) ni por presentación (400ml vs 1.5L) con sus ingresos asociados.
     - No presenta una tabla de ventas que concilie al 100% el dinero recaudado con cero deriva.

5. **Infraestructura de Pruebas Pytest:**
   - Al ejecutar `pytest tests/test_milestone_m1.py`, se observó el siguiente error verbatim en todas las pruebas:
     ```
     tests\conftest.py:22: in isolated_db
         monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
     E   AttributeError: <module 'app.database' from 'C:\\Users\\Alejandro\\Desktop\\POLLO APANADO\\app\\database.py'> has no attribute 'DB_PATH'
     ```
   - En `app/database.py` (líneas 5-9), la función `get_db_path()` consulta `os.environ.get("DATABASE_PATH")`, pero no define la variable a nivel de módulo `DB_PATH = None`.

---

## 2. Logic Chain (Cadena Lógica)

1. *Premisa A (de Obs. 1 y 2):* La fórmula `Efectivo Final Esperado en Cajón = Base Inicial + Ventas en Efectivo - Gastos Menores Autorizados` requiere como insumos obligatorios:
   - `Base Inicial`: valor inicial declarado al abrir la caja.
   - `Ventas en Efectivo`: sumatoria de `total_amount` de ventas en efectivo completadas.
   - `Gastos Menores`: sumatoria de salidas autorizadas de efectivo.
   Dado que actualmente ni la base inicial ni los gastos menores se guardan en la base de datos, el sistema no puede evaluar esta fórmula sin agregar las tablas `cash_shifts` y `cash_expenses` en SQLite.

2. *Premisa B (de Obs. 1, 2 y 3):* En un restaurante con servicio continuo (7am a 10pm) y turnos diferenciados (mañana y tarde), un arqueo no puede basarse únicamente en la fecha calendario `date_str`, sino en una sesión de turno acotada con estado (`abierto` -> `cerrado`), lo que permite saber con exactitud qué cajero responde por el dinero y cuánto efectivo físico contó al momento del cierre (`actual_cash`).

3. *Premisa C (de Obs. 2 y 3):* En cada venta en efectivo, el dinero físico recibido menos las vueltas entregadas es idéntico al monto facturado:
   $$\text{cash\_received} - \text{change\_returned} \equiv \text{total\_amount}$$
   Por lo tanto, la sumatoria de `total_amount` de las ventas en efectivo representa exactamente el dinero neto ingresado al cajón por concepto de ventas. Los pagos digitales (Nequi/Daviplata) van a la cuenta bancaria y los de Datáfono se liquidan por vouchers; ninguno entra al cajón físico. Separarlos en tarjetas y columnas independientes en `cash.html` resuelve la confusión contable.

4. *Premisa D (de Obs. 4):* En `sale_items`, cada fila registra `quantity`, `unit_price`, `subtotal` y `chosen_presa`. Debido a que cada ticket de `sales` tiene `total_amount = sum(si.subtotal)`, una consulta que agrupe por producto y categoría en `sale_items` suma exactamente el 100% de los ingresos con cero deriva matemática ($0 COP de descuadre).

5. *Premisa E (de Obs. 5):* Para que la suite de pruebas automatizadas y los nuevos tests de caja se ejecuten con éxito, `app/database.py` debe declarar `DB_PATH = None` y permitir que `get_db_path()` use `DB_PATH` si está definido.

---

## 3. Caveats (Salvedades y Supuestos)

1. **Permiso de Escritura:** Como agente explorador (read-only), este reporte no modifica los archivos fuente `app/database.py`, `app/routers/cash.py` ni `app/templates/cash.html`. Los cambios propuestos se detallan con precisión en `analysis.md` para ser aplicados por el implementador.
2. **Turnos sin Cerrar:** Si un cajero olvida cerrar el turno anterior e intenta abrir uno nuevo, el sistema debe rechazarlo con código HTTP 400 exigiendo el arqueo del turno previo.
3. **Compatibilidad con Ventas Anteriores:** Las ventas existentes en la base de datos no tienen `shift_id` asociado. El endpoint `/api/cash/daily-summary` debe ser tolerante a `shift_id NULL` agrupando por `date_str` para no romper la visualización de días históricos.
4. **Reversiones y Ventas Anuladas:** Todas las consultas financieras deben mantener el filtro `status = 'completada'`. Las ventas con `status = 'anulada'` deben exponerse en una sección separada de auditoría forense (Requerimiento R3).

---

## 4. Conclusion (Conclusiones y Recomendaciones de Acción)

1. **Diseño de Base de Datos:**
   - Crear tabla `cash_shifts` con campos: `id`, `shift_code`, `date_str`, `opened_at`, `closed_at`, `cashier_name`, `base_inicial`, `cash_sales`, `digital_sales`, `datafono_sales`, `total_sales`, `total_expenses`, `expected_cash`, `actual_cash`, `difference`, `closing_notes`, `status`.
   - Crear tabla `cash_expenses` con campos: `id`, `shift_id`, `timestamp`, `date_str`, `amount`, `category`, `concept`, `authorized_by`, `recipient`, `receipt_number`.
   - Agregar columna opcional `shift_id` en `sales`.
   - Definir `DB_PATH = None` en `app/database.py` para solventar el AttributeError en pruebas.

2. **Diseño de Endpoints (`app/routers/cash.py`):**
   - `GET /api/cash/current-shift`: Retorna el estado del turno actual.
   - `POST /api/cash/open-shift`: Apertura de turno con `base_inicial` y nombre de cajero.
   - `POST /api/cash/expense`: Registro de gasto menor autorizado deducido de caja.
   - `GET /api/cash/expenses`: Lista de gastos menores del día/turno.
   - `POST /api/cash/close-shift`: Cierre de turno, ingreso de dinero físico y cálculo de diferencia.
   - Enriquecer `GET /api/cash/daily-summary` con:
     - `cash_reconciliation` (Fórmula R1 completa).
     - `product_breakdown` (Desglose exhaustivo R2: presas solas, combos, almuerzos, porciones, gaseosas Postobón y Coca-Cola con 100% de suma y 0 deriva).
     - `physical_presas_summary` (Pechugas, muslos, contramuslos, alas totales y pollos equivalentes).

3. **Diseño de Frontend (`app/templates/cash.html`):**
   - Incorporar banner superior de turno activo con botón de apertura/cierre.
   - Añadir recuadro visual de Arqueo Explícito: `Base Inicial + Ventas Efectivo - Gastos Menores = Efectivo Esperado`.
   - Incorporar tablas desglosadas por categoría de producto y tabla de gastos menores.
   - Incluir modales interactivos para apertura, registro de gasto y cierre de caja.

---

## 5. Verification Method (Método de Verificación Independiente)

Para verificar independientemente los hallazgos de este reporte:

1. **Verificar Ausencia de Esquema Actual:**
   ```powershell
   python -c "import sqlite3; conn=sqlite3.connect('data/asadero.db'); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
   ```
   *Condición:* Las tablas `cash_shifts` y `cash_expenses` no existen actualmente.

2. **Verificar el Error de Setup en Pytest:**
   ```powershell
   pytest tests/test_milestone_m1.py -k test_sqlite_engine_check_constraint_rejects_negative_stock
   ```
   *Condición de fallo:* Lanza `AttributeError: module 'app.database' has no attribute 'DB_PATH'`.
   *Solución de prueba rápida:* Agregar `DB_PATH = None` en `app/database.py` y volver a correr el comando; la prueba pasará a verde.

3. **Verificar la Conciliación Matemática al 100% de `sale_items`:**
   ```powershell
   python -c "import sqlite3; conn=sqlite3.connect('data/asadero.db'); vtas = conn.execute(\"SELECT SUM(total_amount) FROM sales WHERE status='completada'\").fetchone()[0]; items = conn.execute(\"SELECT SUM(si.subtotal) FROM sales s JOIN sale_items si ON s.id=si.sale_id WHERE s.status='completada'\").fetchone()[0]; print(f'Ventas: {vtas}, Items: {items}, Diferencia: {abs(vtas - items)} COP')"
   ```
   *Condición de éxito:* `Diferencia: 0 COP` certifica que el desglose de ítems suma exactamente el 100% de las ventas.
