# Reporte de Investigación Técnica: Requerimientos R1 y R2
**Sistema:** Restaurante "Pollo Apanado"  
**Agente Investigador:** `explorer_cash_1` (teamwork_preview_explorer)  
**Fecha:** 2026-10-21  
**Directorio de Trabajo:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_cash_1\`  
**Estado:** Certificado para Implementación  

---

## 1. Resumen Ejecutivo

Este documento presenta la investigación arquitectónica, análisis de esquemas SQLite, derivación matemática de fórmulas de arqueo y diseño de endpoints para dar cumplimiento a los requerimientos **R1** (Ciclo de Caja con Base Inicial y Arqueo Cierre Explícito) y **R2** (Desglose Exhaustivo de Presas, Combos y Dinero Recaudado), establecidos en `ORIGINAL_REQUEST.md` (versión `2026-10-21T04:39:26Z`).

### Hallazgos Principales:
1. **Ausencia de Entidad de Turno de Caja:** Actualmente, `app/database.py` y `app/routers/cash.py` no tienen un ciclo de vida para turnos o sesiones de caja (`cash_shifts`). El endpoint actual `/api/cash/daily-summary` agrega transacciones de la tabla `sales` filtrando únicamente por la fecha (`date_str`), sin registrar cuándo se abrió la caja, quién la operó, con qué base inicial arrancó, ni si el turno fue cerrado.
2. **Inexistencia de Registro de Base Inicial y Gastos Menores:** No existe en SQLite una columna ni tabla para almacenar la `base_inicial` (fondo de cambio, ej. $100.000 COP) ni para registrar salidas de efectivo de caja menor (`cash_expenses` / `gastos_menores_autorizados`).
3. **Fórmula de Arqueo Incompleta en Producción:** La tarjeta de "Efectivo en Cajón" en `cash.html` muestra únicamente las ventas facturadas en efectivo (`data.cash_summary.efectivo`), ignorando por completo la base inicial y los gastos menores, lo que genera confusión financiera para el dueño y los empleados.
4. **Desglose de Ventas Incompleto para R2:** El resumen actual en `cash.py` cuenta presas físicas globales de forma aproximada, pero **no** desglosa los combos (`POL-14`, `POL-12`, `POL-ENT`), ni las porciones individuales (`POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`, `POR-AREP`), ni separa las bebidas por marca (Postobón vs Coca-Cola) con sus cantidades y subtotales en pesos colombianos (COP).
5. **Descubrimiento Crítico de Infraestructura de Pruebas:** Se detectó un error `AttributeError: module 'app.database' has no attribute 'DB_PATH'` en `tests/conftest.py:22` que bloquea la ejecución de pytest. `app/database.py` utiliza la función `get_db_path()` pero no define la variable de módulo `DB_PATH = None`. Resolver este detalle permite a la suite de pruebas aislar la base de datos sin errores de setup.

---

## 2. Auditoría del Código Fuente Actual

### 2.1. Base de Datos (`app/database.py`)
- **Líneas 27-139:** Se crean 8 tablas: `products`, `inventory`, `sales`, `sale_items`, `butchering_logs`, `cooking_batches`, `system_settings`, `order_counters`.
- **Tabla `sales` (Líneas 58-74):**
  - Campos: `id`, `sale_code`, `timestamp`, `date_str`, `time_str`, `hour_of_day`, `day_of_week`, `total_amount`, `payment_method`, `cash_received`, `change_returned`, `notes`, `status`.
  - No contiene referencia a `shift_id` ni a la sesión de caja.
  - Métodos de pago permitidos en la práctica: `'efectivo'`, `'nequi_daviplata'`, `'datafono'`.
- **Tabla `sale_items` (Líneas 77-90):**
  - Campos: `id`, `sale_id`, `product_id`, `product_name`, `quantity`, `unit_price`, `subtotal`, `chosen_presa`.
  - Excelente diseño relacional: almacena `subtotal = quantity * unit_price` y la presa elegida en almuerzos (`chosen_presa`).
  - La sumatoria de `sale_items.subtotal` para una venta dada coincide exactamente con `sales.total_amount` (garantía de cero derivas).
- **Inexistencia de Tablas para Caja:** No existen tablas `cash_shifts` ni `cash_expenses`.

### 2.2. Router de Caja (`app/routers/cash.py`)
- **Líneas 14-139 (`get_daily_summary`):**
  - Consulta `sales` agrupando por `payment_method` para `status = 'completada'`.
  - Calcula el margen bruto restando costos de productos (`p.price - p.cost`).
  - Compara contra el punto de equilibrio diario ($258.462 COP).
  - Calcula el reparto de socios según el Cap Table (40% Socio 1, 40% Socio 2, 20% Santiago, 5% Reserva).
  - Líneas 73-116: Consulta presas vendidas sumando presas solas y coeficientes de combos, pero **omite** los valores monetarios recaudados por ítem, el desglose de combos, porciones y gaseosas.
- **Líneas 141-160:** Endpoints de inventario (`/inventory-all`, `/adjust-stock`).

### 2.3. Plantilla Frontend (`app/templates/cash.html`)
- **Líneas 44-90:** Tarjetas de totales (Ingresos Brutos, Margen Bruto, Efectivo en Cajón, Nequi/Daviplata, Datáfono).
  - La tarjeta de "Efectivo en Cajón" actualmente toma `data.cash_summary.efectivo` sin sumar la base inicial ni restar gastos.
- **Líneas 166-202:** Muestra contadores planos de presas (`statPresasPechugas`, `statPresasMuslos`, etc.), pero sin tabla exhaustiva de productos, ni montos en COP, ni separación de marcas de bebidas.
- **Falta de Controles:** No hay interfaz para registrar apertura de turno con base inicial, ni modal para registrar gastos menores de caja menor, ni formulario para ingresar el conteo físico de billetes y contrastar sobrante/faltante al cierre.

---

## 3. Requerimiento R1: Ciclo de Vida de Caja y Fórmula de Arqueo

### 3.1. Máquina de Estados del Turno de Caja
Para una operación limpia con múltiples turnos (matutino 7:00 a.m. a 3:30 p.m. y tarde/cierre 1:30 p.m. a 10:00 p.m.), el ciclo debe modelarse con dos estados estrictos:

```
[ Sin Turno Activo ]
        │
        ▼  POST /api/cash/open-shift (Cajero declara 'base_inicial' ej. $100.000 COP)
[ Estado: 'abierto' ]
        │
        ├─► Ventas Mostrador (POST /api/pos/checkout) -> Suma a 'cash_sales'
        ├─► Gastos Menores (POST /api/cash/expense)   -> Suma a 'total_expenses'
        │
        ▼  POST /api/cash/close-shift (Cajero ingresa 'actual_cash' físico contado)
[ Estado: 'cerrado' ]
        │
        └─► Generación de Planilla de Arqueo Definitiva (Diferencia = Real - Esperado)
```

### 3.2. Esquema Relacional Propuesto en SQLite

#### Tabla 1: `cash_shifts` (Sesiones / Turnos de Caja)
```sql
CREATE TABLE IF NOT EXISTS cash_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_code TEXT UNIQUE NOT NULL,       -- ej. 'TURNO-261021-0001'
    date_str TEXT NOT NULL,                -- 'YYYY-MM-DD'
    opened_at TEXT NOT NULL,               -- ISO 8601 timestamp
    closed_at TEXT,                        -- ISO 8601 timestamp (NULL mientras esté abierto)
    cashier_name TEXT NOT NULL,            -- Nombre del cajero (ej. 'Santiago')
    base_inicial INTEGER NOT NULL DEFAULT 0 CHECK (base_inicial >= 0), -- Base inicial en COP
    
    -- Totales financieros congelados al cierre
    cash_sales INTEGER NOT NULL DEFAULT 0,              -- Ventas en efectivo físico
    digital_sales INTEGER NOT NULL DEFAULT 0,           -- Ventas Nequi / Daviplata
    datafono_sales INTEGER NOT NULL DEFAULT 0,          -- Ventas Datáfono / Tarjetas
    total_sales INTEGER NOT NULL DEFAULT 0,             -- Total ventas brutas (completadas)
    total_expenses INTEGER NOT NULL DEFAULT 0,          -- Total gastos menores autorizados
    
    -- Cuadre de efectivo físico
    expected_cash INTEGER NOT NULL DEFAULT 0,           -- base_inicial + cash_sales - total_expenses
    actual_cash INTEGER,                                -- Conteo físico de dinero en cajón
    difference INTEGER,                                 -- actual_cash - expected_cash (negativo=faltante, positivo=sobrante)
    
    closing_notes TEXT,                                 -- Observaciones de cierre
    status TEXT NOT NULL DEFAULT 'abierto' CHECK (status IN ('abierto', 'cerrado'))
);
```

#### Tabla 2: `cash_expenses` (Gastos Menores Autorizados / Caja Menor)
```sql
CREATE TABLE IF NOT EXISTS cash_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER,                                  -- Llave foránea a cash_shifts(id)
    timestamp TEXT NOT NULL,                           -- ISO 8601 timestamp
    date_str TEXT NOT NULL,                            -- 'YYYY-MM-DD'
    amount INTEGER NOT NULL CHECK (amount > 0),        -- Monto pagado en COP
    category TEXT NOT NULL,                            -- 'insumos', 'servicios', 'transporte', 'mantenimiento', 'otro'
    concept TEXT NOT NULL,                             -- Descripción (ej. 'Compra 2 bolsas de hielo')
    authorized_by TEXT NOT NULL,                       -- Quién autorizó (ej. 'Santiago')
    recipient TEXT,                                    -- A quién se pagó (opcional)
    receipt_number TEXT,                               -- Comprobante o factura (opcional)
    FOREIGN KEY (shift_id) REFERENCES cash_shifts (id) ON DELETE SET NULL
);
```

#### Actualización de compatibilidad en tabla `sales`:
Se recomienda incorporar la columna `shift_id INTEGER REFERENCES cash_shifts(id)` de forma idempotente en `init_db()`:
```python
sales_cols = [r["name"] for r in cursor.execute("PRAGMA table_info(sales);").fetchall()]
if "shift_id" not in sales_cols:
    cursor.execute("ALTER TABLE sales ADD COLUMN shift_id INTEGER REFERENCES cash_shifts(id);")
```

### 3.3. Derivación Matemática y Segregación de Canales de Pago

#### A. Efectivo Físico en Cajón (Cash Drawer):
$$\text{Efectivo Final Esperado en Cajón} = \text{Base Inicial} + \text{Ventas en Efectivo} - \text{Gastos Menores Autorizados}$$

- **Base Inicial:** Monto en billetes y monedas declarado en la apertura del turno para dar cambio al cliente.
- **Ventas en Efectivo:** Suma de `total_amount` para todas las ventas con `payment_method = 'efectivo'` y `status = 'completada'`.
  *Demostración de Invariante de Vueltas:*
  En cada venta en efectivo:
  $$\text{Dinero Entregado por Cliente} - \text{Vueltas Devueltas} = \text{cash\_received} - \text{change\_returned} \equiv \text{total\_amount}$$
  Por tanto, el incremento neto de dinero físico dentro del cajón por cada venta es exactamente el `total_amount` facturado.
- **Gastos Menores Autorizados:** Salidas físicas de efectivo retiradas del cajón para compras urgentes o pagos inmediatos:
  $$\text{Gastos Menores Autorizados} = \sum_{\text{turno}} \text{amount}$$
- **Conteo Físico y Descuadre (Diferencia):**
  $$\text{Diferencia} = \text{Efectivo Físico Real (Contado por Cajero)} - \text{Efectivo Final Esperado}$$
  - $\text{Diferencia} = 0$: **Caja Cuadrada Exacta** (cero descuadre).
  - $\text{Diferencia} < 0$: **Faltante de Efectivo** (resaltado en rojo con alerta de descuadre).
  - $\text{Diferencia} > 0$: **Sobrante de Efectivo** (resaltado en azul/verde con advertencia).

#### B. Canales Digitales y Electrónicos (Separación Estricta):
1. **Nequi / Daviplata:**
   $$\text{Total Nequi/Daviplata} = \sum_{\text{payment\_method = 'nequi\_daviplata'}} \text{total\_amount}$$
   - Los fondos ingresan directamente a la cuenta bancaria de la empresa.
   - **No tocan el cajón físico de efectivo.**
   - No generan vueltas (`change_returned = 0`).
2. **Datáfono (Vouchers de Tarjeta Débito / Crédito):**
   $$\text{Total Datáfono} = \sum_{\text{payment\_method = 'datafono'}} \text{total\_amount}$$
   - Los fondos son retenidos y liquidados por la pasarela de adquirencia (Redeban / Credibanco / Bold).
   - Se concilian mediante los vouchers físicos impresos por el terminal POS.
   - **No tocan el cajón físico de efectivo.**

#### C. Matriz de Cuadre Consolidado para la Planilla de Cierre:
| Canal Financiero | Ubicación de los Fondos | Saldo Inicial | Entradas (Ventas) | Salidas (Gastos) | Saldo Final Esperado | Soporte de Verificación |
|---|---|---|---|---|---|---|
| **Efectivo Físico** | Cajón metálico POS | Base Inicial ($B) | + Ventas Efectivo ($VE) | - Gastos Menores ($G) | **$B + $VE - $G** | Conteo físico de billetes y monedas |
| **Nequi / Daviplata** | Cuenta bancaria | $0 | + Ventas Nequi ($VN) | $0 | **$VN** | Extracto / App Nequi-Daviplata |
| **Datáfono** | Adquirente / Banco | $0 | + Ventas Tarjetas ($VT) | $0 | **$VT** | Total de lote en voucher impreso |
| **Gran Total** | Consolidado del Negocio | **$B** | **$VE + $VN + $VT** | **$G** | **$B + Total Ventas - $G** | Auditoría integral con 0 deriva |

---

## 4. Requerimiento R2: Desglose Exhaustivo de Presas, Combos y Dinero Recaudado

### 4.1. Mapeo Catálogo y Estructura de Ítems
El catálogo de productos de Pollo Apanado (`products`) se clasifica en 5 familias comerciales:

1. **Presas Solas (`category = 'pollo'`, SKU `POL-PEC`, `POL-MUS`, `POL-CON`, `POL-ALA`):**
   - Venta individual a $9.000 COP cada una.
   - Consume 1 unidad de vitrina de la presa correspondiente.
2. **Combos de Pollo (`category = 'pollo'`, SKU `POL-14`, `POL-12`, `POL-ENT`):**
   - `POL-14` (1/4 Pollo + Papas): $13.000 COP (1 Muslo + 1 Contramuslo + 1 ración papas).
   - `POL-12` (1/2 Pollo + Papas): $20.000 COP (1 Pechuga + 1 Ala + 1 Muslo + 1 Contramuslo + 1 ración papas).
   - `POL-ENT` (Pollo Entero + Papas): $36.000 COP (2 Pechugas + 2 Alas + 2 Muslos + 2 Contramuslos + 2 raciones papas).
3. **Almuerzos Ejecutivos (`category = 'almuerzos'`, SKU `ALM-COMP`):**
   - `ALM-COMP` (Almuerzo Completo): $16.000 COP.
   - Consume 1 presa seleccionada (`chosen_presa` ∈ {Pechuga, Muslo, Contramuslo, Ala}) + 1 caldo + 1 arroz + 1 frijoles.
4. **Porciones Sueltas (`category = 'porciones'`, SKU `POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`, `POR-AREP`):**
   - Caldo ($6.000), Frijoles ($6.000), Arroz ($4.000), Papas ($5.000), Arepas ($2.000).
5. **Gaseosas (`category = 'gaseosas'`):**
   - **Postobón:** Colombiana 400ml ($3.500), Manzana 400ml ($3.500), Colombiana 1.5L ($7.000), Manzana 1.5L ($7.000).
   - **Coca-Cola:** Coca-Cola 400ml ($4.000), Coca-Cola Zero 400ml ($4.000), Quatro Toronja 400ml ($4.000), Coca-Cola 1.5L ($8.500).

### 4.2. Algoritmo de Conciliación Matemática al 100% (Cero Derivas)

Para garantizar que la suma de todos los subtotales coincida con el 100% del dinero recaudado:
```python
def compute_exhaustive_sales_breakdown(conn, date_str: str, shift_id: Optional[int] = None):
    # Consulta de detalle por producto vendido en ventas completadas
    query = """
        SELECT 
            p.category,
            p.sku,
            p.name as product_name,
            p.price as unit_price,
            p.cost as unit_cost,
            SUM(si.quantity) as total_quantity,
            SUM(si.subtotal) as total_revenue,
            SUM(si.quantity * (p.price - p.cost)) as total_margin
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        JOIN products p ON si.product_id = p.id
        WHERE s.date_str = ? AND s.status = 'completada'
    """
    params = [date_str]
    if shift_id is not None:
        query += " AND s.shift_id = ?"
        params.append(shift_id)
        
    query += " GROUP BY p.category, p.sku, p.name, p.price, p.cost ORDER BY p.category, total_revenue DESC"
    
    rows = conn.execute(query, tuple(params)).fetchall()
    
    # Categorización explícita
    breakdown = {
        "presas_solas": {"items": [], "total_qty": 0, "subtotal_cop": 0},
        "combos": {"items": [], "total_qty": 0, "subtotal_cop": 0},
        "almuerzos": {"items": [], "total_qty": 0, "subtotal_cop": 0, "by_presa": {}},
        "porciones": {"items": [], "total_qty": 0, "subtotal_cop": 0},
        "gaseosas_postobon": {"items": [], "total_qty": 0, "subtotal_cop": 0},
        "gaseosas_cocacola": {"items": [], "total_qty": 0, "subtotal_cop": 0},
        "total_revenue_sum": 0
    }
    
    for r in rows:
        item_dict = dict(r)
        sku = item_dict["sku"]
        cat = item_dict["category"]
        qty = item_dict["total_quantity"]
        sub = item_dict["total_revenue"]
        
        breakdown["total_revenue_sum"] += sub
        
        if sku in ('POL-PEC', 'POL-MUS', 'POL-CON', 'POL-ALA'):
            breakdown["presas_solas"]["items"].append(item_dict)
            breakdown["presas_solas"]["total_qty"] += qty
            breakdown["presas_solas"]["subtotal_cop"] += sub
        elif sku in ('POL-14', 'POL-12', 'POL-ENT'):
            breakdown["combos"]["items"].append(item_dict)
            breakdown["combos"]["total_qty"] += qty
            breakdown["combos"]["subtotal_cop"] += sub
        elif sku == 'ALM-COMP':
            breakdown["almuerzos"]["items"].append(item_dict)
            breakdown["almuerzos"]["total_qty"] += qty
            breakdown["almuerzos"]["subtotal_cop"] += sub
        elif cat == 'porciones':
            breakdown["porciones"]["items"].append(item_dict)
            breakdown["porciones"]["total_qty"] += qty
            breakdown["porciones"]["subtotal_cop"] += sub
        elif cat == 'gaseosas':
            if 'Postob' in item_dict["product_name"] or sku.startswith('GAS-COL') or sku.startswith('GAS-MAN'):
                breakdown["gaseosas_postobon"]["items"].append(item_dict)
                breakdown["gaseosas_postobon"]["total_qty"] += qty
                breakdown["gaseosas_postobon"]["subtotal_cop"] += sub
            else:
                breakdown["gaseosas_cocacola"]["items"].append(item_dict)
                breakdown["gaseosas_cocacola"]["total_qty"] += qty
                breakdown["gaseosas_cocacola"]["subtotal_cop"] += sub
```

### 4.3. Desglose Específico de Presas de Almuerzos Ejecutivos
Para conocer qué presa prefirieron los clientes en el Almuerzo Completo:
```sql
SELECT 
    COALESCE(si.chosen_presa, 'Sin Especificar') as chosen_presa,
    SUM(si.quantity) as quantity,
    SUM(si.subtotal) as subtotal_cop
FROM sales s
JOIN sale_items si ON s.id = si.sale_id
JOIN products p ON si.product_id = p.id
WHERE s.date_str = ? AND s.status = 'completada' AND p.sku = 'ALM-COMP'
GROUP BY si.chosen_presa;
```

### 4.4. Trazabilidad Física de Presas Despachadas de Vitrina
El reporte debe cruzar la salida física de presas con su valorización comercial:
- **Pechugas Despachadas:**
  $$\text{Pechugas Totales} = \text{Pechugas Solas} + (1 \times \text{Medios Pollos}) + (2 \times \text{Pollos Enteros}) + \text{Almuerzos con Pechuga}$$
- **Muslos Despachados:**
  $$\text{Muslos Totales} = \text{Muslos Solos} + (1 \times \text{Cuartos Pollo}) + (1 \times \text{Medios Pollos}) + (2 \times \text{Pollos Enteros}) + \text{Almuerzos con Muslo}$$
- **Contramuslos Despachados:**
  $$\text{Contramuslos Totales} = \text{Contramuslos Solos} + (1 \times \text{Cuartos Pollo}) + (1 \times \text{Medios Pollos}) + (2 \times \text{Pollos Enteros}) + \text{Almuerzos con Contramuslo}$$
- **Alas Despachadas:**
  $$\text{Alas Totales} = \text{Alas Solas} + (1 \times \text{Medios Pollos}) + (2 \times \text{Pollos Enteros}) + \text{Almuerzos con Ala}$$
- **Total Presas Despachadas:**
  $$\text{Total Presas} = \text{Pechugas} + \text{Muslos} + \text{Contramuslos} + \text{Alas}$$
- **Pollos Enteros Equivalentes Consumidos:**
  $$\text{Pollos Equivalentes} = \frac{\text{Total Presas}}{8}$$

---

## 5. Endpoints a Agregar y Modificar en `app/routers/cash.py`

### 5.1. Modelos Pydantic para Entradas y Salidas
```python
class OpenShiftRequest(BaseModel):
    cashier_name: str = Field(..., min_length=2, description="Nombre del cajero responsable")
    base_inicial: int = Field(..., ge=0, description="Base inicial de efectivo en pesos COP")
    notes: Optional[str] = None

class CloseShiftRequest(BaseModel):
    shift_id: Optional[int] = None
    actual_cash: int = Field(..., ge=0, description="Conteo físico real de efectivo en el cajón")
    notes: Optional[str] = None

class CreateExpenseRequest(BaseModel):
    shift_id: Optional[int] = None
    amount: int = Field(..., gt=0, description="Monto del gasto menor en pesos COP")
    category: str = Field(..., description="insumos, servicios, transporte, mantenimiento, otro")
    concept: str = Field(..., min_length=3, description="Detalle del gasto")
    authorized_by: str = Field(..., min_length=2, description="Nombre de quien autoriza")
    recipient: Optional[str] = None
    receipt_number: Optional[str] = None
```

### 5.2. Especificación de Endpoints

| Método | Ruta | Descripción | Parámetros / Payload | Respuestas |
|---|---|---|---|---|
| `GET` | `/api/cash/current-shift` | Consulta el turno actualmente abierto | Ninguno | `200 OK` (objeto turno o `{active_shift: null}`) |
| `POST` | `/api/cash/open-shift` | Abre un nuevo turno registrando base inicial | `OpenShiftRequest` | `200 OK` (turno creado), `400 Bad Request` si ya hay turno abierto |
| `POST` | `/api/cash/close-shift` | Cierra el turno activo, registra conteo físico y calcula diferencia | `CloseShiftRequest` | `200 OK` (resumen completo de arqueo), `400/404` si no hay turno abierto |
| `POST` | `/api/cash/expense` | Registra una salida de efectivo de caja menor | `CreateExpenseRequest` | `200 OK` (gasto registrado con ID y fecha) |
| `GET` | `/api/cash/expenses` | Lista los gastos menores del día o turno | `date_str`, `shift_id` (opcionales) | `200 OK` (lista de gastos y suma total) |
| `GET` | `/api/cash/daily-summary` | Resumen financiero integral (actualizado para R1 y R2) | `date_str`, `shift_id` (opcionales) | `200 OK` (objeto con arqueo, desglose exhaustivo y métricas) |

### 5.3. Payload de Respuesta de `/api/cash/daily-summary` (Enriquecido)
```json
{
  "date": "2026-10-21",
  "shift_info": {
    "shift_id": 1,
    "shift_code": "TURNO-261021-0001",
    "status": "abierto",
    "opened_at": "2026-10-21T07:05:00",
    "cashier_name": "Santiago",
    "base_inicial": 100000
  },
  "cash_reconciliation": {
    "base_inicial": 100000,
    "cash_sales": 320000,
    "total_expenses": 25000,
    "expected_cash": 395000,
    "actual_cash": null,
    "difference": null,
    "digital_transfers": 150000,
    "card_vouchers": 90000,
    "gran_total_sales": 560000,
    "total_liquidity": 635000
  },
  "expenses_list": [
    {
      "id": 1,
      "timestamp": "2026-10-21T09:30:00",
      "amount": 25000,
      "category": "insumos",
      "concept": "Compra 2 bolsas de hielo y cilantro",
      "authorized_by": "Santiago"
    }
  ],
  "product_breakdown": {
    "presas_solas": {
      "items": [{"sku": "POL-PEC", "name": "Pechuga Sola", "quantity": 4, "unit_price": 9000, "subtotal": 36000}],
      "total_qty": 4,
      "subtotal_cop": 36000
    },
    "combos": {
      "items": [{"sku": "POL-14", "name": "1/4 Pollo + Papas", "quantity": 6, "unit_price": 13000, "subtotal": 78000}],
      "total_qty": 6,
      "subtotal_cop": 78000
    },
    "almuerzos": {
      "items": [{"sku": "ALM-COMP", "name": "Almuerzo Completo", "quantity": 10, "unit_price": 16000, "subtotal": 160000}],
      "total_qty": 10,
      "subtotal_cop": 160000,
      "by_presa": {"Pechuga": 4, "Muslo": 3, "Contramuslo": 2, "Ala": 1}
    },
    "porciones": {
      "items": [{"sku": "POR-CALD", "name": "Porción de Caldo", "quantity": 5, "unit_price": 6000, "subtotal": 30000}],
      "total_qty": 5,
      "subtotal_cop": 30000
    },
    "gaseosas_postobon": {
      "items": [{"sku": "GAS-COL-400", "name": "Postobón Colombiana 400ml", "quantity": 8, "unit_price": 3500, "subtotal": 28000}],
      "total_qty": 8,
      "subtotal_cop": 28000
    },
    "gaseosas_cocacola": {
      "items": [{"sku": "GAS-COC-400", "name": "Coca-Cola 400ml", "quantity": 7, "unit_price": 4000, "subtotal": 28000}],
      "total_qty": 7,
      "subtotal_cop": 28000
    },
    "total_revenue_sum": 560000,
    "zero_drift_verified": true
  },
  "physical_presas_summary": {
    "pechugas": 10,
    "muslos": 9,
    "contramuslos": 8,
    "alas": 7,
    "total_presas": 34,
    "pollos_equivalentes": 4.25
  },
  "estimated_margin": 285000,
  "daily_breakeven_target": 258462,
  "breakeven_percentage": 216.7,
  "is_profitable_today": true,
  "partner_distribution": { ... }
}
```

---

## 6. Actualización de Interfaz de Usuario (`app/templates/cash.html`)

### 6.1. Barra de Control de Turno de Caja (Superior)
- Componente dinámico de estado:
  - Si el turno está **ABIERTO**: Muestra banner verde esmeralda con código de turno, nombre del cajero, hora de inicio y Base Inicial declarada (`$100.000 COP`).
  - Si el turno está **CERRADO**: Muestra banner ámbar alertando "Caja no abierta", con botón táctil destacado `[ Abrir Turno de Caja ]`.
- Botones de acción rápida:
  - 🟢 `Abrir Turno` (abre modal de cajero + base inicial).
  - 🔴 `Registrar Gasto Menor` (abre modal para deducir dinero de caja menor con concepto y autorización).
  - 🏁 `Cerrar Turno & Arqueo` (abre modal para ingresar dinero físico contado y generar acta de cierre).

### 6.2. Panel Central de Arqueo Explícito (Fórmula R1)
Un recuadro de alta visibilidad para que tanto el dueño como el empleado entiendan la matemática sin ambigüedades:
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  💵 PLANILLA DE ARQUEO DE EFECTIVO EN CAJÓN                                           │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  (+) Base Inicial de Apertura:                $ 100.000 COP                           │
│  (+) Ventas en Efectivo Físico:               $ 320.000 COP (15 tickets)              │
│  (-) Gastos Menores Autorizados de Caja:     -$  25.000 COP (2 comprobantes)          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  (=) EFECTIVO FINAL ESPERADO EN CAJÓN:        $ 395.000 COP                           │
│      Efectivo Físico Real Contado:            $ 395.000 COP                           │
│      Diferencia / Cuadre:                     $       0 COP  [✅ CAJA CUADRADA EXACTA]│
└────────────────────────────────────────────────────────────────────────────────────────┘
```
Junto a dos paneles adyacentes independientes:
- 📲 **Transferencias Digitales (Nequi / Daviplata):** `$150.000 COP` (Cuenta bancaria, no toca cajón).
- 💳 **Datáfono / Vouchers de Tarjeta:** `$90.000 COP` (Conciliar con rollo de datáfono).

### 6.3. Tabla Desplegable Exhaustiva de Productos (R2)
Tablas estilizadas con Tailwind CSS organizadas por categoría:
1. **Presas Solas:** Pechuga, Muslo, Contramuslo, Ala (Cant, Subtotal).
2. **Combos de Pollo:** 1/4 Pollo, 1/2 Pollo, Pollo Entero (Cant, Subtotal).
3. **Almuerzos Ejecutivos:** Almuerzo Completo (Cant, Subtotal) con desglose de presas.
4. **Porciones Sueltas:** Caldo, Frijoles, Arroz, Papas, Arepas (Cant, Subtotal).
5. **Gaseosas y Bebidas:**
   - Postobón: Colombiana 400ml/1.5L, Manzana 400ml/1.5L.
   - Coca-Cola: Tradicional 400ml/1.5L, Zero 400ml, Quatro 400ml.
6. **Fila de Cierre de Tabla:** Suma 100% de Ventas Facturadas = `$560.000 COP` (con insignia verde `Deriva Cero: $0`).

### 6.4. Bitácora de Gastos Menores
Tabla con timestamp, concepto, categoría, autorizador y monto retirado del cajón.

---

## 7. Plan de Acción para Implementación

### Paso 1: Corrección de Infraestructura de Pruebas
- En `app/database.py`, declarar en el ámbito del módulo:
  ```python
  DB_PATH = None
  
  def get_db_path():
      if DB_PATH is not None:
          return DB_PATH
      return os.environ.get(
          "DATABASE_PATH",
          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "asadero.db")
      )
  ```
- Esto restaura de inmediato la ejecución de `pytest` permitiendo que `tests/conftest.py` asigne la ruta de base de datos aislada sin lanzar `AttributeError`.

### Paso 2: Creación de Tablas en `app/database.py`
- Agregar `CREATE TABLE IF NOT EXISTS cash_shifts (...)` y `CREATE TABLE IF NOT EXISTS cash_expenses (...)` en `init_db()`.
- Agregar migración idempotente para la columna `shift_id` en `sales`.

### Paso 3: Implementación de Lógica en `app/routers/cash.py`
- Crear funciones auxiliares:
  - `get_active_shift(conn)`: recupera el turno en estado `'abierto'`.
  - `calculate_expected_cash(base, sales, expenses)`: fórmula matemática.
  - `get_sales_exhaustive_breakdown(conn, date_str, shift_id)`: consulta agrupada con 100% de conciliación.
- Implementar los endpoints:
  - `GET /api/cash/current-shift`
  - `POST /api/cash/open-shift`
  - `POST /api/cash/expense`
  - `GET /api/cash/expenses`
  - `POST /api/cash/close-shift`
  - Enriquecer `GET /api/cash/daily-summary`

### Paso 4: Actualización en `app/routers/pos.py`
- En `process_checkout()`, si existe un turno activo en `cash_shifts`, asociar el `shift_id` en la inserción de `sales`. Si no hay turno abierto, mantener compatibilidad hacia atrás permitiendo la venta.

### Paso 5: Actualización Visual en `app/templates/cash.html`
- Agregar barra de estado de turno y botones modales.
- Agregar panel de arqueo de caja explícito (Fórmula R1).
- Agregar tabla de desglose exhaustivo de productos (R2).
- Agregar tabla de gastos menores.
- Actualizar script JS (`loadDailySummary()`) para renderizar todos los nuevos datos y controlar modales.

### Paso 6: Suite de Pruebas Automatizadas
- Crear `tests/test_cash_register_lifecycle.py` con pruebas unitarias y de integración que verifiquen:
  1. Apertura de turno con `base_inicial` y rechazo de duplicados.
  2. Registro de gastos menores y validación de montos positivos.
  3. Cálculo exacto de `expected_cash = base_inicial + cash_sales - expenses`.
  4. Cuadre de cierre con sobrante, faltante y exacto.
  5. Desglose exhaustivo de ventas con 100% de suma y cero deriva.
  6. Aislamiento total entre efectivo físico, transferencias Nequi/Daviplata y vouchers de datáfono.

---

## 8. Conclusión

La arquitectura actual de Pollo Apanado cuenta con un esquema relacional muy sólido en `sales` y `sale_items`. La implementación de **R1** y **R2** no requiere cambios disruptivos, sino la incorporación de dos tablas complementarias (`cash_shifts` y `cash_expenses`), la adición de 5 endpoints en `app/routers/cash.py` y el enriquecimiento visual de `app/templates/cash.html`.

Esta especificación garantiza transparencia contable absoluta, erradicación de confusiones entre dinero físico y digital, y control riguroso de cada presa de pollo y producto vendido en el asadero.
