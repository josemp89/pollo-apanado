# Handoff Report: Auditoría e Investigación Backend de Inventario, Entradas de Mercancía (R2) y Conciliación Diaria (R3)

**De:** `explorer_inventory_backend_1`  
**Para:** Orquestador (`bc8f4c39-fa47-48c2-a1a6-459dace9f969`)  
**Fecha:** 2026-10-22T01:38:00Z  
**Tipo de Handoff:** Hard (Investigación Completa)  
**Documento Técnico Detallado:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_inventory_backend_1\analysis.md`

---

## 1. Observation

1. **Estado Actual de la Suite de Pruebas:**
   - Comando ejecutado: `pytest`
   - Resultado observado:
     ```
     ====================== 188 passed, 3 warnings in 20.42s =======================
     ```
   - 100% de las pruebas unitarias, de integración, concurrencia y auditoría adversaria pasan sin errores sobre base de datos aislada temporal en WAL mode.

2. **Esquema de Inventario Actual (`app/database.py`, Líneas 49–59):**
   ```python
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
   ```

3. **Insumos Registrados en Inventario (`app/database.py`, Líneas 357–385 y 293–303):**
   - **Bodega:** `pollo_entero_crudo` (18 uds), `harina_apanar_kg` (25 kg), `aceite_fritura_lt` (40 L).
   - **Nevera:** `GAS-COL-400` (24), `GAS-MAN-400` (20), `GAS-COL-15L` (8), `GAS-MAN-15L` (8), `GAS-COC-400` (24), `GAS-ZER-400` (12), `GAS-QUA-400` (15), `GAS-COC-15L` (6).
   - **Cocina:** `arepas_unidades` (50), `caldo_raciones` (25), `arroz_raciones` (30), `frijoles_raciones` (25), `papas_raciones` (20).
   - **Vitrina:** `pechuga_vitrina` (12), `muslo_vitrina` (14), `contramuslo_vitrina` (14), `ala_vitrina` (10).

4. **Flujos de Mutación de Stock Existentes:**
   - **Checkout POS (`app/routers/pos.py`, Líneas 240–253):**
     Deduce stock atómicamente con cláusula de piso no negativo:
     ```python
     UPDATE inventory 
     SET stock = stock - ?, updated_at = ?
     WHERE item_key = ? AND stock >= ?
     ```
   - **Despiece en Cocina (`app/routers/kitchen.py`, Líneas 77–100):**
     Deduce `pollo_entero_crudo` de bodega e incrementa $2N$ pechugas, muslos, contramuslos, alas y caldos con auditoría en `butchering_logs`.
   - **Fritura en Cocina (`app/routers/kitchen.py`, Líneas 307–320 y 378–385):**
     Deduce $0.025 \times \text{presas}$ kg de harina y $0.020 \times \text{presas}$ litros de aceite. Al terminar suma presas a vitrina.
   - **Ajuste de Stock Manual (`app/routers/cash.py`, Líneas 828–839):**
     Endpoint `/api/cash/adjust-stock` sobrescribe el stock directamente sin trazabilidad de compras a proveedores ni auditoría de recepción.

5. **Ausencias en el Sistema Actual respecto a R2 y R3:**
   - No existe tabla para recepciones de compras a proveedores (`merchandise_entries`).
   - No existe tabla ni registro de la línea base del inventario inicial del día (`daily_initial_inventory`).
   - No existe endpoint que calcule la fórmula de conciliación en tiempo real:
     $\text{Stock Esperado} = \text{Stock Inicial} + \text{Entradas Proveedor} - \text{Consumo/Ventas}$.

---

## 2. Logic Chain

1. **Premisa R2:** El negocio recibe insumos periódicamente (pollos enteros de avícolas, gaseosas de Postobón/Coca-Cola, sacos de harina, canecas de aceite, arepas).
2. **De la Observación 4 y 5:** Actualmente solo existe un ajuste manual destructivo (`adjust-stock`) que borra el historial y no registra quién entregó, la factura, el costo ni la fecha.
3. **Inferencia R2:** Se requiere una tabla relacional inmutable `merchandise_entries` con clave foránea a `inventory(item_key)`, código secuencial atómico (`REC-YYMMDD-XXXX`), y un endpoint `POST /api/inventory/supplier-entry` que incremente atómicamente el stock en la misma transacción SQLite WAL.
4. **Premisa R3:** Para detectar pérdidas, robos de presas/gaseosas o errores operativos, el dueño necesita comparar el stock físico esperado contra el stock real en cualquier momento del día.
5. **De la Observación 2 y 4:** El stock live en `inventory.stock` cambia dinámicamente con cada venta, anulación y despiece. Sin embargo, no se preserva la fotografía de apertura matutina.
6. **Inferencia R3:** Almacenar en `daily_initial_inventory` la foto de apertura diaria (manualmente vía formulario o automáticamente al abrir turno con `open-shift`) permite reconstruir con precisión matemática la ecuación:
   $$\text{Stock Esperado} = \text{Stock Inicial} + \text{Entradas Proveedores} - \text{Consumo/Ventas}$$
7. **Consistencia:** Debido a que las ventas anuladas ya revierten el stock a vitrina/nevera de forma simétrica (`pos.py:cancel_sale`), filtrar únicamente ventas `completadas` para el consumo neto garantiza cero deriva matemática ($\text{discrepancia} = 0$).

---

## 3. Caveats

1. **Costeo de Inventario:** El modelo actual de `products` maneja `cost` fijo. Las entradas de proveedores pueden actualizar `products.cost = unit_cost` para productos directos (gaseosas), pero para productos compuestos (combos y almuerzos), el costo unitario depende de la receta de despiece y guarniciones.
2. **Turnos Múltiples:** La conciliación está diseñada principalmente por fecha (`date_str`), con soporte para filtrar por `shift_id` si se abren dos turnos en un mismo día.
3. **Insumos No Catalogados:** Todo insumo recibido debe tener un `item_key` registrado en la tabla `inventory`. Si un proveedor entrega un producto nuevo (ej. agua mineral), debe pre-registrarse en `inventory` antes de la recepción.

---

## 4. Conclusion

1. La arquitectura actual de SQLite en modo WAL y FastAPI es óptima y suficientemente robusta para soportar R2 y R3 sin degradación de concurrencia ni bloqueos.
2. La solución técnica más limpia y desacoplada consiste en:
   - Crear 2 tablas nuevas en `app/database.py`: `merchandise_entries` y `daily_initial_inventory`.
   - Implementar un router dedicado `app/routers/inventory.py` registrado en `app/main.py`.
   - Conectar la apertura de turno (`cash.py:open_shift`) para autogenerar el snapshot inicial de apertura si no existe.
   - Implementar los 3 endpoints nucleares:
     - `POST /api/inventory/supplier-entry` (R2: Entrada de mercancía con incremento atómico de stock).
     - `POST /api/inventory/set-initial-stock` (R3: Declaración del conteo de apertura del día).
     - `GET /api/inventory/daily-reconciliation` (R3: Conciliación en tiempo real con fórmula estricta de conservación).
   - Agregar integración frontend táctil: botón y modal de recepción de mercancía en `index.html` (POS) y panel de conciliación en `cash.html`.

---

## 5. Verification Method

Para verificar independientemente estos hallazgos y validar la implementación futura:
1. **Inspección de Archivos:**
   - Leer `app/database.py` líneas 48-110 para confirmar las tablas actuales de inventario y despiece.
   - Leer `app/routers/pos.py` líneas 66-140 para verificar la función de cálculo de requerimientos de inventario (`calculate_order_inventory_requirements`).
   - Leer `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_inventory_backend_1\analysis.md` para el diseño completo de endpoints y DDL.
2. **Ejecución de Pruebas:**
   - Ejecutar en PowerShell / terminal:
     ```powershell
     pytest -v
     ```
   - Debe pasar con 188 tests exitosos en menos de 25 segundos sin errores ni bloqueos.
3. **Condición de Invalidación:**
   - La propuesta quedaría invalidada si una entrada de proveedor produce inconsistencias en la restricción `CHECK (stock >= 0)` o si la fórmula $\text{Stock Inicial} + \text{Entradas} - \text{Ventas}$ presenta una desviación $> 0$ en condiciones sin mermas declaradas.
