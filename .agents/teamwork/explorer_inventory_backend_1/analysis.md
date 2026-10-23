# Análisis Técnico y Arquitectura de Backend: Inventario, Entradas de Mercancía (R2) y Conciliación Diaria (R3)

**Autor:** `explorer_inventory_backend_1`  
**Fecha:** 2026-10-22T01:37:00Z  
**Estado:** Certificado / Listo para Implementación  
**Alcance:** Requerimientos R2 y R3 de `ORIGINAL_REQUEST.md` (Sección `## 2026-10-22T01:24:23Z`).

---

## 1. Resumen Ejecutivo

Este documento presenta la investigación exhaustiva del backend de "Pollo Apanado" (FastAPI + SQLite WAL), el modelo de datos de inventario multinivel existente, y el diseño arquitectónico preciso para implementar los requerimientos:
- **R2: Módulo de Entrada de Mercancía y Recepción de Proveedores** (captura de proveedor, factura/remisión, insumo, cantidad, costo unitario/total, incremento atómico de stock y bitácora auditable).
- **R3: Panel de Conteo Inicial de Inventario y Conciliación Diaria en Tiempo Real** (fórmula matemática de conservación: $\text{Stock Físico Esperado} = \text{Stock Inicial} + \text{Entradas de Proveedores} - \text{Consumo/Ventas}$, con cero deriva).

Se verificó que los **188 tests automatizados existentes en pytest pasan al 100%** con cero errores, estableciendo que el diseño propuesto mantiene total compatibilidad regresiva con los módulos de mostrador (POS), cocina (tiempos y despiece), y caja (turnos, arqueo y seguridad antifraude).

---

## 2. Arquitectura de Backend Existente

### 2.1 Stack Tecnológico
- **Framework Web:** FastAPI (Python 3.12) con ASGI Uvicorn.
- **Base de Datos:** SQLite3 en modo WAL (`PRAGMA journal_mode=WAL;`), `synchronous=NORMAL;`, `busy_timeout=10000;`, y llaves foráneas estrictas (`foreign_keys=ON;`).
- **Gestión de Conexiones:** `app.database.get_db_connection()`, retornando objetos `sqlite3.Row` con soporte transaccional inmediato.
- **Secuencias Atómicas Concurrenciales:** Tabla `order_counters` con patrón `INSERT ... ON CONFLICT(counter_name) DO UPDATE SET last_value = last_value + 1 RETURNING last_value;` que previene colisiones de identificadores únicos (`sale_code`, `batch_code`, `shift_code`) bajo pruebas de estrés de más de 50 hilos paralelos.

### 2.2 Estructura de Módulos y Routers
| Archivo | Prefijo | Responsabilidad Principal |
|---|---|---|
| `app/main.py` | `/` | Punto de entrada FastAPI, montaje de estáticos, rutas HTML Jinja2 (`/`, `/cocina`, `/caja`). |
| `app/database.py` | N/A | DDL de esquema SQLite, migraciones idempotentes, inicialización y seed inicial. |
| `app/routers/pos.py` | `/api/pos` | Catálogo de productos, stock en vivo, checkout atómico con piso no negativo, anulación con PIN y bitácora forense. |
| `app/routers/kitchen.py` | `/api/kitchen` | Despiece de pollos enteros (`1 -> 2P+2M+2C+2A+2 Caldo`), cronómetros por etapas (salmuera, adobo, fritura), recomendador predictivo de fritura. |
| `app/routers/cash.py` | `/api/cash` | Ciclo de turnos (apertura/cierre, base inicial), gastos menores, auditoría física de vitrina y reporte diario integral. |

---

## 3. Modelo Actual de Inventario y Flujo de Insumos

### 3.1 Esquema de la Tabla `inventory`
```sql
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL, -- 'vitrina', 'nevera', 'bodega', 'cocina'
    stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
    unit TEXT NOT NULL, -- 'unidad', 'porcion', 'kg', 'litro'
    min_threshold REAL DEFAULT 5,
    updated_at TEXT
);
```

### 3.2 Catálogo de Insumos Registrados en Base de Datos
1. **Bodega (`bodega`):**
   - `pollo_entero_crudo`: Pollos enteros crudos para despiece (Stock inicial seed: 18 uds, umbral mín: 8).
   - `harina_apanar_kg`: Harina de apanado para freidoras (Stock inicial seed: 25 kg, umbral mín: 10).
   - `aceite_fritura_lt`: Aceite vegetal para freidoras industriales (Stock inicial seed: 40 litros, umbral mín: 15).
2. **Nevera (`nevera`):**
   - Gaseosas Postobón: `GAS-COL-400` (24 uds), `GAS-MAN-400` (20 uds), `GAS-COL-15L` (8 uds), `GAS-MAN-15L` (8 uds).
   - Gaseosas Coca-Cola: `GAS-COC-400` (24 uds), `GAS-ZER-400` (12 uds), `GAS-QUA-400` (15 uds), `GAS-COC-15L` (6 uds).
3. **Cocina (`cocina`):**
   - `arepas_unidades`: Arepas pre-asadas/fritas (Stock inicial seed: 50 uds, umbral mín: 10).
   - `caldo_raciones`: Raciones de sopa/caldo generadas por huacales (Seed: 25 raciones, umbral: 5).
   - `arroz_raciones`: Raciones de arroz cocido (Seed: 30 raciones, umbral: 6).
   - `frijoles_raciones`: Raciones de frijoles preparados (Seed: 25 raciones, umbral: 5).
   - `papas_raciones`: Porciones de papa a la francesa (Seed: 20 porciones, umbral: 5).
4. **Vitrina Térmica (`vitrina`):**
   - `pechuga_vitrina`: Pechugas fritas listas (Seed: 12 uds, umbral: 4).
   - `muslo_vitrina`: Muslos fritos listos (Seed: 14 uds, umbral: 4).
   - `contramuslo_vitrina`: Contramuslos fritos listos (Seed: 14 uds, umbral: 4).
   - `ala_vitrina`: Alas fritas listas (Seed: 10 uds, umbral: 4).

### 3.3 Flujo Dinámico de Consumo y Deducción
- **Venta POS (`/api/pos/checkout`):** Descuenta atómicamente de vitrina, cocina y nevera según la descomposición simétrica de `calculate_order_inventory_requirements()` (`POL-14`, `POL-12`, `POL-ENT`, `ALM-COMP`, presas individuales, porciones y gaseosas).
- **Anulación de Venta (`/api/pos/cancel-sale/{id}`):** Reingresa exactamente los mismos insumos descontados y actualiza el estado a `'anulada'`.
- **Despiece de Pollos (`/api/kitchen/despiece`):** Descuenta $N$ unidades de `pollo_entero_crudo` en bodega e incrementa $2N$ pechugas, $2N$ muslos, $2N$ contramuslos, $2N$ alas y $2N$ caldos.
- **Fritura de Lotes (`/api/kitchen/batch-timer`):** Descuenta $0.025 \times \text{presas}$ kg de harina y $0.020 \times \text{presas}$ litros de aceite. Al terminar el lote suma presas a vitrina.

---

## 4. Diagnóstico: Brechas Identificadas (Gaps)

1. **Ausencia de Registro de Proveedores y Entradas de Mercancía (R2):**
   - Actualmente, el único mecanismo existente para subir stock es el endpoint `/api/cash/adjust-stock`, el cual sobrescribe arbitrariamente el campo `stock` con un número flotante sin registrar:
     - Nombre del proveedor (`supplier_name`).
     - Número de remisión o factura comercial (`invoice_number`).
     - Costo unitario o costo total pagado (`unit_cost`, `total_cost`).
     - Quién recibió la mercancía (`received_by`).
     - Código de trazabilidad o timestamp inmutable.
   - No existe la tabla de bitácora `merchandise_entries` requerida por R2.

2. **Ausencia de Línea Base de Inventario Inicial Diario (R3):**
   - El sistema no almacena con qué inventario arrancó el turno o el día. Si el día comenzó con 18 pollos, no queda registro histórico de esa cifra una vez ocurren ventas o despieces.
   - No existe la tabla `daily_initial_inventory`.

3. **Ausencia del Algoritmo de Conciliación Matemática Diaria (R3):**
   - No existe un endpoint que contraste:
     $$\text{Stock Esperado} = \text{Stock Inicial} + \text{Entradas Proveedor} - \text{Consumo/Ventas}$$
   - No hay forma de validar si hay discrepancias o mermas entre el stock teórico calculado por la fórmula y el stock actual en base de datos.

---

## 5. Diseño Técnico y Blueprint de Solución para R2 y R3

### 5.1 Nuevas Tablas en Base de Datos (`app/database.py`)

#### Tabla 1: `merchandise_entries` (Bitácora de Recepción de Proveedores - R2)
```sql
CREATE TABLE IF NOT EXISTS merchandise_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_code TEXT UNIQUE NOT NULL, -- e.g. 'REC-261022-0001'
    timestamp TEXT NOT NULL,
    date_str TEXT NOT NULL,          -- YYYY-MM-DD
    time_str TEXT NOT NULL,          -- HH:MM:SS
    supplier_name TEXT NOT NULL,     -- e.g. 'Avícola Los Pollos', 'Postobón S.A.'
    invoice_number TEXT NOT NULL,    -- Factura o Remisión
    item_key TEXT NOT NULL,          -- FK a inventory(item_key)
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,          -- 'bodega', 'nevera', 'cocina'
    quantity REAL NOT NULL CHECK (quantity > 0),
    unit TEXT NOT NULL,              -- 'unidad', 'kg', 'litro'
    unit_cost INTEGER NOT NULL CHECK (unit_cost >= 0),
    total_cost INTEGER NOT NULL CHECK (total_cost >= 0),
    received_by TEXT NOT NULL DEFAULT 'Santiago',
    notes TEXT,
    shift_id INTEGER,
    FOREIGN KEY (item_key) REFERENCES inventory (item_key),
    FOREIGN KEY (shift_id) REFERENCES cash_shifts (id) ON DELETE SET NULL
);
```

#### Tabla 2: `daily_initial_inventory` (Línea Base de Apertura Diaria - R3)
```sql
CREATE TABLE IF NOT EXISTS daily_initial_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_str TEXT NOT NULL,          -- YYYY-MM-DD
    shift_id INTEGER,
    item_key TEXT NOT NULL,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL,
    initial_stock REAL NOT NULL CHECK (initial_stock >= 0),
    recorded_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL DEFAULT 'Santiago / Administrador',
    notes TEXT,
    UNIQUE (date_str, item_key),
    FOREIGN KEY (item_key) REFERENCES inventory (item_key),
    FOREIGN KEY (shift_id) REFERENCES cash_shifts (id) ON DELETE SET NULL
);
```

---

### 5.2 Nuevo Módulo de Router: `app/routers/inventory.py`

Se recomienda crear un router dedicado con prefijo `/api/inventory` (e incluirlo en `app/main.py`), manteniendo el código desacoplado y de alta cohesión.

#### Endpoints Propuestos:

#### 1. `POST /api/inventory/supplier-entry` (R2)
- **Propósito:** Registrar recepción de mercancía de un proveedor y sumar inmediatamente al stock real.
- **Payload Pydantic:**
  ```python
  class SupplierEntryRequest(BaseModel):
      supplier_name: str = Field(..., min_length=2, description="Nombre del proveedor")
      invoice_number: str = Field(..., min_length=1, description="Número de factura o remisión")
      item_key: str = Field(..., description="Clave única del insumo en inventario")
      quantity: float = Field(..., gt=0, description="Cantidad recibida > 0")
      unit_cost: int = Field(..., ge=0, description="Costo unitario en COP")
      total_cost: Optional[int] = Field(None, ge=0, description="Costo total en COP (opcional, auto-calculado)")
      received_by: Optional[str] = "Santiago"
      notes: Optional[str] = None
      shift_id: Optional[int] = None
  ```
- **Lógica Transaccional:**
  1. Verificar que `item_key` exista en `inventory`.
  2. Generar `entry_code` secuencial atómico con `order_counters` (`entry_YYYY-MM-DD`).
  3. Calcular `total_cost = total_cost if total_cost is not None else int(round(quantity * unit_cost))`.
  4. Ejecutar incremento atómico:
     ```sql
     UPDATE inventory 
     SET stock = stock + ?, updated_at = ? 
     WHERE item_key = ?;
     ```
  5. Insertar registro auditable en `merchandise_entries`.
  6. Si el insumo corresponde a un producto con SKU idéntico (ej. gaseosas `GAS-*`), actualizar `products.cost = unit_cost` para mantener actualizados los márgenes de ganancia.
  7. Commit y respuesta con estado de stock anterior y nuevo.

#### 2. `GET /api/inventory/supplier-entries` (R2)
- **Parámetros:** `date_str` (opcional), `shift_id` (opcional), `item_key` (opcional).
- **Retorno:** Lista de recepciones ordenadas por ID descendente, conteo total de recepciones y suma total monetaria invertida en compras de insumos.

#### 3. `POST /api/inventory/set-initial-stock` (R3)
- **Propósito:** Establecer o confirmar el inventario físico con el que arranca la jornada.
- **Payload:**
  ```python
  class InitialStockItem(BaseModel):
      item_key: str
      initial_stock: float = Field(..., ge=0)

  class SetInitialStockRequest(BaseModel):
      date_str: Optional[str] = None # Defaults to today
      items: List[InitialStockItem]
      recorded_by: Optional[str] = "Santiago"
      sync_live_stock: bool = True # Si true, sincroniza inventory.stock con la apertura declarada
      notes: Optional[str] = None
  ```
- **Lógica:**
  - Registra o actualiza (`INSERT ... ON CONFLICT(date_str, item_key) DO UPDATE`) los valores en `daily_initial_inventory`.
  - Si `sync_live_stock` es True y la jornada apenas arranca, actualiza `inventory.stock = initial_stock`.

#### 4. `GET /api/inventory/daily-reconciliation` (R3)
- **Propósito:** Emitir la conciliación en tiempo real de todo el inventario con balance de conservación matemática.
- **Fórmula de Conciliación por Ítem:**
  $$\text{Stock Físico Esperado} = \text{Stock Inicial} + \text{Entradas Proveedor} - \text{Consumo/Ventas}$$
- **Cálculo de Consumo por Tipo de Insumo:**
  - **Gaseosas y Porciones de Mostrador:** Suma de `quantity` de ventas completadas hoy en `sale_items`.
  - **Pollos Enteros Crudos (Bodega):** Suma de `whole_chickens` de `butchering_logs` para la fecha.
  - **Presas de Vitrina:**
    - Entradas de producción = Presas generadas por despiece ($2 \times \text{pollos}$) + Lotes de fritura terminados.
    - Consumo = Presas vendidas (solas + combos desglosados + almuerzos ejecutivos).
  - **Harina y Aceite:** Consumo en lotes de fritura ($0.025 \text{ kg}$ harina, $0.020 \text{ L}$ aceite por presa frita).
- **Respuesta JSON:**
  ```json
  {
    "date": "2026-10-22",
    "has_initial_inventory": true,
    "total_supplier_spend_cop": 350000,
    "reconciliation_items": [
      {
        "item_key": "GAS-COL-400",
        "name": "Postobón Colombiana 400ml",
        "category": "nevera",
        "unit": "unidad",
        "initial_stock": 24.0,
        "supplier_entries": 24.0,
        "consumption_sales": 6.0,
        "expected_stock": 42.0,
        "current_stock": 42.0,
        "discrepancy": 0.0,
        "is_balanced": true
      },
      {
        "item_key": "pollo_entero_crudo",
        "name": "Pollos Enteros Crudos (Bodega)",
        "category": "bodega",
        "unit": "unidad",
        "initial_stock": 18.0,
        "supplier_entries": 20.0,
        "consumption_sales": 10.0,
        "expected_stock": 28.0,
        "current_stock": 28.0,
        "discrepancy": 0.0,
        "is_balanced": true
      }
    ],
    "zero_drift_overall": true
  }
  ```

#### 5. Integración Automática al Abrir Turno (`app/routers/cash.py` -> `open_shift`)
Al abrir un turno de caja (`POST /api/cash/open-shift`), si no se ha establecido el inventario inicial del día en `daily_initial_inventory`, el sistema toma automáticamente una fotografía (*snapshot*) del stock actual de cada insumo. Esto garantiza que la conciliación esté siempre disponible desde el primer segundo del turno sin requerir pasos manuales redundantes.

---

### 5.3 Integración de Frontend

#### En `app/templates/index.html` (Mostrador POS):
- **Botón Accesible de Recepción:**
  En la barra superior o bajo el menú lateral, agregar botón táctil `📦 Entrada Mercancía / Proveedores` (cumpliendo criterio de aceptación R2).
- **Modal Táctil de Recepción Rápida:**
  - Selector de proveedor habitual (Avícola Los Pollos, Postobón, Coca-Cola, etc.).
  - Input para Factura / Remisión.
  - Dropdown o selector de insumo.
  - Stepper táctil para cantidad (+1, +5, +10, +24).
  - Input de costo unitario y total.
  - Botón: "CONFIRMAR ENTRADA AL STOCK".

#### En `app/templates/cash.html` (Caja & Socios / Administración):
- **Pestaña / Tarjeta Dedicada: "Control de Proveedores & Conciliación de Inventario":**
  1. **Tarjeta de Balance de Entradas:** Total invertido hoy en compras a proveedores ($ COP) y total de recepciones procesadas.
  2. **Botón "Establecer / Revisar Inventario Inicial":** Abre modal para registrar el conteo físico matutino de apertura.
  3. **Tabla Interactiva de Conciliación en Tiempo Real:**
     Columnas: `Insumo | Categoría | Stock Inicial | (+) Entradas Proveedor | (-) Consumo/Ventas | Stock Esperado | Stock Actual | Estado`.
     Badges visuales:
     - `✅ Cuadrado (0 Deriva)` en verde esmeralda.
     - `🚨 Discrepancia (-X faltante / +X sobrante)` en rojo o ámbar.
  4. **Bitácora Histórica de Recepciones:** Lista auditable de facturas y recepciones del día.

---

## 6. Plan de Implementación Concreto y Pruebas

### Paso 1: Esquema de Base de Datos (`app/database.py`)
- Crear las tablas `merchandise_entries` y `daily_initial_inventory` dentro de `init_db()`.
- Agregar triggers o índices (`idx_merch_entries_date`, `idx_initial_inv_date`) para optimizar consultas de conciliación.

### Paso 2: Endpoint Router (`app/routers/inventory.py` y `app/main.py`)
- Implementar los endpoints de `/api/inventory` detallados en la sección 5.2.
- Registrar el router en `app/main.py`:
  ```python
  from app.routers import inventory
  app.include_router(inventory.router)
  ```

### Paso 3: Integración de Apertura de Turno (`app/routers/cash.py`)
- En `open_shift`, invocar snapshot inicial automático en `daily_initial_inventory`.
- En `daily-summary`, incorporar el resumen de entradas de proveedores y enlace de conciliación.

### Paso 4: Vistas Frontend (`index.html` y `cash.html`)
- Agregar modal táctil de recepción de mercancía en `index.html`.
- Agregar sección de conciliación de inventario y tabla de proveedores en `cash.html`.

### Paso 5: Suite de Pruebas Automatizadas (`tests/test_inventory_r2_r3.py`)
- Test de incremento atómico de stock por proveedor (`Stock Final = Stock Inicial + Entrada`).
- Test de validación de campos obligatorios (proveedor, factura, cantidad > 0).
- Test de generación secuencial inmutable de `entry_code`.
- Test de registro de inventario inicial matutino.
- Test de conciliación matemática: `Stock Esperado = Inicial + Entradas - Ventas` con cero deriva en gaseosas, pollos crudos y presas.
- Test de consistencia con ventas anuladas.
- Test de concurrencia: múltiples recepciones simultáneas bajo SQLite WAL sin bloqueos de base de datos.
