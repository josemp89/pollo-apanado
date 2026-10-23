# Reporte de Investigación Técnica: Requerimientos R4 y R5
## Arqueo Físico de Vitrina, Detección de Mermas/Sustracción y Suite de Pruebas Automatizadas

**Fecha:** 2026-10-21T04:47:00Z  
**Autor:** `explorer_vitrina_3` (Role: `teamwork_preview_explorer`)  
**Proyecto:** Pollo Apanado — Sistema POS, Cocina, Vitrina & Auditoría de Caja  
**Archivos Inspeccionados:**
- `app/database.py`
- `app/routers/kitchen.py`
- `app/routers/pos.py`
- `app/routers/cash.py`
- `app/templates/cash.html`
- `tests/conftest.py`, `pytest.ini`, y suite existente en `tests/`

---

## 1. Resumen Ejecutivo

Este documento detalla los hallazgos técnicos, el diseño arquitectónico y la hoja de ruta para la implementación de:
1. **Requerimiento R4:** Arqueo Físico de Vitrina, cálculo automático de discrepancias/mermas ($\text{Conteo Físico Real} - \text{Stock Teórico}$) y correlación antifraude contra presas devueltas por ventas anuladas.
2. **Requerimiento R5:** Diagnóstico exhaustivo de la infraestructura de pruebas `pytest`, identificación de la falla de aislamiento de base de datos (`AttributeError: DB_PATH`), y diseño de la suite de pruebas unitarias/integración para R1 a R4.

---

## 2. Trazabilidad del Inventario de Vitrina (Inspección de Código)

### 2.1. Nombres y Claves de Presas en Base de Datos (`app/database.py`)
En la tabla `inventory` (líneas 45-56 y 239-244 de `app/database.py`), las presas listas para despacho en la vitrina térmica están identificadas con las siguientes claves únicas (`item_key`):

| `item_key` | Nombre Descriptivo | Categoría | Unidad | Stock Inicial Seed | Umbral Mínimo |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `pechuga_vitrina` | Pechugas en Vitrina | `vitrina` | `unidad` | 12 | 4 |
| `muslo_vitrina` | Muslos en Vitrina | `vitrina` | `unidad` | 14 | 4 |
| `contramuslo_vitrina` | Contramuslos en Vitrina | `vitrina` | `unidad` | 14 | 4 |
| `ala_vitrina` | Alas en Vitrina | `vitrina` | `unidad` | 10 | 4 |

### 2.2. Flujo de Entrada de Presas a Vitrina (`app/routers/kitchen.py`)
Existen dos vías de incremento de presas en vitrina:
1. **Despiece de Pollos Crudos (`POST /api/kitchen/despiece`, líneas 50-134):**
   - Por cada pollo crudo despiezado ($n$), se generan exactamente 8 presas:
     $$\Delta \text{pechugas} = 2n, \quad \Delta \text{muslos} = 2n, \quad \Delta \text{contramuslos} = 2n, \quad \Delta \text{alas} = 2n$$
   - Se incrementa el stock de cada `item_key` en vitrina y se descuentan $n$ unidades de `pollo_entero_crudo` de bodega.
2. **Finalización de Tanda de Fritura (`POST /api/kitchen/advance-batch/{id}`, líneas 341-395):**
   - Cuando un lote de cocina pasa de `fritura` a `terminado`, se distribuyen equitativamente las presas fritas:
     $$\text{per\_type} = \text{total\_presas} // 4$$
     Sumando `per_type` a cada una de las 4 presas de vitrina.

### 2.3. Flujo de Salida de Presas desde Vitrina (`app/routers/pos.py`)
En el checkout (`POST /api/pos/checkout`, líneas 135-297), la función `calculate_order_inventory_requirements` (líneas 59-133) descompone los productos vendidos en deducciones directas de vitrina:
- **Presas Solas:**
  - `POL-PEC` (Pechuga Sola): Descuenta 1 `pechuga_vitrina`.
  - `POL-MUS` (Muslo Solo): Descuenta 1 `muslo_vitrina`.
  - `POL-CON` (Contramuslo Solo): Descuenta 1 `contramuslo_vitrina`.
  - `POL-ALA` (Ala Sola): Descuenta 1 `ala_vitrina`.
- **Combos de Pollo:**
  - `POL-14` (1/4 Pollo): Descuenta 1 `muslo_vitrina` + 1 `contramuslo_vitrina` (+ 1 `papas_raciones`).
  - `POL-12` (1/2 Pollo): Descuenta 1 `pechuga_vitrina` + 1 `ala_vitrina` + 1 `muslo_vitrina` + 1 `contramuslo_vitrina` (+ 1 `papas_raciones`).
  - `POL-ENT` (Pollo Entero): Descuenta 2 `pechuga_vitrina` + 2 `ala_vitrina` + 2 `muslo_vitrina` + 2 `contramuslo_vitrina` (+ 2 `papas_raciones`).
- **Almuerzo Completo (`ALM-COMP`):**
  - Requiere selección obligatoria `chosen_presa` $\in \{\text{'Pechuga'}, \text{'Muslo'}, \text{'Contramuslo'}, \text{'Ala'}\}$.
  - Descuenta 1 unidad de `f"{chosen_presa.lower()}_vitrina"` (+ 1 caldo, 1 arroz, 1 frijoles).

### 2.4. Flujo de Retorno por Anulación (`app/routers/pos.py:322-380`)
En `cancel_sale`, al anular una venta previa, el sistema ejecuta una restauración simétrica:
- Reconstruye los ítems asociados a la venta y llama a `calculate_order_inventory_requirements`.
- Incrementa `inventory.stock` para cada presa (`UPDATE inventory SET stock = stock + ? WHERE item_key = ?`).
- Cambia `sales.status` a `'anulada'`.

---

## 3. Arqueo Físico de Vitrina: Conteo Real vs Stock Teórico (R4)

### 3.1. Fórmula Matemática
Al cierre de turno, el cajero o administrador cuenta físicamente las presas que quedan en la vitrina caliente. Para cada presa $p \in \{\text{pechuga}, \text{muslo}, \text{contramuslo}, \text{ala}\}$:
$$\text{Discrepancia}_p = \text{Conteo Físico Real}_p - \text{Stock Teórico del Sistema}_p$$
$$\text{Discrepancia Total} = \sum_{p} \text{Conteo Físico Real}_p - \sum_{p} \text{Stock Teórico del Sistema}_p$$

**Interpretación de Resultados:**
1. **$\text{Discrepancia}_p = 0$ (Cuadre Exacto):** El stock teórico coincide exactamente con la vitrina.
2. **$\text{Discrepancia}_p < 0$ (Faltante / Merma / Sustracción):** Faltan presas en vitrina. El sistema esperaba tener más de las que realmente hay.
3. **$\text{Discrepancia}_p > 0$ (Sobrante / Excedente):** Hay más presas físicas que en el sistema (por ejemplo, piezas de mayor rendimiento en el despiece o registros omitidos).

### 3.2. Modelo de Base de Datos para Auditorías Físicas (`vitrina_audits`)
Para garantizar trazabilidad inmutable y auditoría histórica, se propone crear la siguiente tabla en `app/database.py`:

```sql
CREATE TABLE IF NOT EXISTS vitrina_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,                  -- ISO timestamp (YYYY-MM-DDTHH:MM:SS)
    date_str TEXT NOT NULL,                   -- YYYY-MM-DD
    time_str TEXT NOT NULL,                   -- HH:MM:SS
    auditor TEXT NOT NULL,                    -- Nombre del cajero/administrador
    pechugas_teorico REAL NOT NULL,
    pechugas_fisico REAL NOT NULL,
    pechugas_diff REAL NOT NULL,
    muslos_teorico REAL NOT NULL,
    muslos_fisico REAL NOT NULL,
    muslos_diff REAL NOT NULL,
    contramuslos_teorico REAL NOT NULL,
    contramuslos_fisico REAL NOT NULL,
    contramuslos_diff REAL NOT NULL,
    alas_teorico REAL NOT NULL,
    alas_fisico REAL NOT NULL,
    alas_diff REAL NOT NULL,
    total_teorico REAL NOT NULL,
    total_fisico REAL NOT NULL,
    total_diff REAL NOT NULL,
    has_discrepancy BOOLEAN NOT NULL DEFAULT 0,
    has_theft_alert BOOLEAN NOT NULL DEFAULT 0,
    theft_alert_detail TEXT,                  -- Detalle forense si faltan presas de ventas anuladas
    notes TEXT,
    inventory_adjusted BOOLEAN DEFAULT 0      -- Indica si el stock de inventory fue actualizado al conteo físico
);
```

### 3.3. Endpoints de la API Propuestos (`app/routers/cash.py`)
1. **`GET /api/cash/vitrina-status`**:
   - Devuelve el stock teórico en vivo de las 4 presas de vitrina.
   - Devuelve el consolidado de presas que fueron devueltas hoy por ventas anuladas.
   - Payload de respuesta:
     ```json
     {
       "theoretical": {
         "pechuga": 12.0,
         "muslo": 14.0,
         "contramuslo": 14.0,
         "ala": 10.0,
         "total": 50.0
       },
       "today_cancelled_presas": {
         "pechuga": 2.0,
         "muslo": 1.0,
         "contramuslo": 1.0,
         "ala": 0.0,
         "total": 4.0,
         "cancelled_sales_count": 2,
         "cancelled_amount_cop": 33000
       }
     }
     ```

2. **`POST /api/cash/vitrina-audit`**:
   - Recibe el conteo físico del empleado y procesa la discrepancia.
   - Pydantic Model:
     ```python
     class VitrinaAuditRequest(BaseModel):
         auditor: str = "Santiago"
         pechugas_fisico: float
         muslos_fisico: float
         contramuslos_fisico: float
         alas_fisico: float
         adjust_inventory: bool = True  # Opcional: sincroniza inventory.stock con el físico
         notes: Optional[str] = None
     ```
   - Calcula las discrepancias, ejecuta el algoritmo de correlación antifraude contra ventas anuladas, guarda el registro en `vitrina_audits` y opcionalmente actualiza `inventory.stock` al conteo real.

3. **`GET /api/cash/vitrina-audits`**:
   - Devuelve el historial de auditorías de vitrina para revisión administrativa.

---

## 4. Correlación Antifraude: Ventas Anuladas vs Faltante Físico

### 4.1. El Vector de Fraude
Un cajero deshonesto realiza la siguiente maniobra:
1. Cobra un pedido en efectivo (ej. 1/2 Pollo + Papas por $20.000 COP).
2. Entrega el pollo frito al cliente.
3. El cliente se retira con su comida.
4. El cajero anula la venta en el sistema (fingiendo "error" o "cliente se fue sin pagar") y se embolsilla los $20.000 COP en efectivo.
5. El sistema, al anular la venta, **reingresa simétricamente las presas al inventario teórico** (+1 Pechuga, +1 Ala, +1 Muslo, +1 Contramuslo).
6. **Resultado en el sistema:** El cajón de efectivo no tiene descuadre aparente (la venta no figura como activa), pero en el inventario teórico hay 4 presas "fantasmas" que no existen en la vitrina física.

### 4.2. Algoritmo de Detección Forense
Al realizar el arqueo físico de vitrina:
1. **Identificar presas reingresadas por anulación:**
   Consultar todas las ventas con `status = 'anulada'` en la fecha actual (`date_str`), y reconstruir la cantidad total de presas devueltas por tipo:
   $$R_{\text{anulada}}(p) \quad \text{para cada presa } p \in \{\text{pechuga}, \text{muslo}, \text{contramuslo}, \text{ala}\}$$
2. **Evaluar el déficit físico:**
   Para cada presa con déficit ($\text{Discrepancia}_p < 0$):
   $$\text{PresasSospechosas}_p = \min(|\text{Discrepancia}_p|, R_{\text{anulada}}(p))$$
3. **Disparo de Alerta Roja:**
   Si $\sum_p \text{PresasSospechosas}_p > 0$:
   - Se marca `has_theft_alert = 1`.
   - Se genera una alerta de alta severidad:
     > 🚨 **ALERTA ROJA DE SUSTRACCIÓN NO AUTORIZADA:**
     > Se detectó un faltante físico de {Total} presas en vitrina ({P} pechugas, {M} muslos, {C} contramuslos, {A} alas) que coincide con presas reingresadas por ventas anuladas hoy.
     > Monto total de ventas anuladas sospechosas: ${Monto} COP.

---

## 5. Diagnóstico de Infraestructura Pytest (R5)

### 5.1. Causa Raíz de Falla en Suite de Pruebas
Al ejecutar cualquier prueba con `pytest`, todas las pruebas fallan en la etapa de `setup` con el siguiente error:
```
E   AttributeError: <module 'app.database' from 'C:\Users\Alejandro\Desktop\POLLO APANADO\app\database.py'> has no attribute 'DB_PATH'
```

**Inspección del Código:**
- En `tests/conftest.py` (línea 22):
  ```python
  monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
  ```
- En `app/database.py` (líneas 5-14):
  ```python
  def get_db_path():
      return os.environ.get(
          "DATABASE_PATH",
          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "asadero.db")
      )

  def get_db_connection():
      db_path = get_db_path()
  ```
- **Problema:** En `app/database.py` **no existe** la variable a nivel de módulo `DB_PATH`. Por defecto, `monkeypatch.setattr(target, name, value, raising=True)` lanza `AttributeError` si el atributo no existe previamente en el módulo.

### 5.2. Solución Requerida (Patch Propuesto)
Para restaurar la funcionalidad completa de la infraestructura de pruebas con aislamiento estricto de base de datos en SQLite:

**En `app/database.py`:**
```python
# Definición de ruta base predeterminada
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "asadero.db")

def get_db_path():
    # Prioridad: variable de entorno -> variable de módulo DB_PATH
    if "DATABASE_PATH" in os.environ:
        return os.environ["DATABASE_PATH"]
    return DB_PATH
```

**En `tests/conftest.py`:**
```python
@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    test_db_file = tmp_path / "test_asadero.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
    monkeypatch.setenv("DATABASE_PATH", str(test_db_file))
    
    # Initialize fresh schema and seed data
    database.init_db()
    
    yield str(test_db_file)
```
Con esta corrección simétrica:
1. `hasattr(database, "DB_PATH")` es `True`.
2. Las pruebas de estrés multihilo y los clientes de prueba apuntan inequívocamente al archivo temporal en `tmp_path`.
3. La base de datos de producción `data/asadero.db` permanece 100% protegida contra mutaciones.

---

## 6. Especificación de Casos de Prueba para R1-R4 (Cumplimiento R5)

Se define la creación de un nuevo módulo de pruebas exhaustivo: `tests/test_audit_r1_to_r5.py`:

### Grupo 1: Módulo Antifraude con PIN de Administrador (R3)
- `test_cancel_sale_without_pin_rejected_403`: Petición de anulación sin PIN recibe HTTP 403 Forbidden.
- `test_cancel_sale_with_wrong_pin_rejected_403`: Petición con PIN incorrecto (ej. `"0000"`) recibe HTTP 403.
- `test_cancel_sale_with_valid_pin_succeeds`: Petición con PIN válido (ej. `"1234"`) anula la venta exitosamente.
- `test_cancel_sale_forensic_log_entry`: Verifica que la anulación inserte un registro inmutable en `cancellation_audit_log` con timestamp, autorizador, motivo y presas restauradas.

### Grupo 2: Ciclo de Caja y Base Inicial (R1)
- `test_open_shift_records_base_inicial`: Apertura de turno registra base inicial en BD (ej. $100.000 COP).
- `test_expected_cash_drawer_formula`: Verifica la igualdad matemática:
  $$\text{Esperado} = \text{Base Inicial} + \text{Ventas Efectivo} - \text{Gastos Menores}$$
- `test_close_shift_cash_difference`: Conteo de efectivo mayor o menor calcula con exactitud la diferencia.
- `test_payment_separation_buckets`: Aísla efectivo en cajón vs transferencias Nequi vs vouchers de datáfono.

### Grupo 3: Desglose Exhaustivo de Ventas (R2)
- `test_shift_breakdown_combo_presas_decomposition`: Verifica que combos (1/4, 1/2, entero) sumen al desglose de presas vendidas.
- `test_shift_breakdown_100pct_cop_reconciliation`: La suma de subtotales de presas, combos, porciones y bebidas coincide exactamente con el 100% del ingreso total.

### Grupo 4: Arqueo Físico de Vitrina y Discrepancias (R4)
- `test_vitrina_audit_zero_discrepancy`: Conteo físico idéntico al teórico resulta en discrepancia 0 y sin alertas.
- `test_vitrina_audit_deficit_detection`: Conteo físico menor detecta faltante numérico exacto.
- `test_vitrina_audit_surplus_detection`: Conteo físico mayor detecta excedente numérico.
- `test_vitrina_audit_fraud_correlation_with_cancelled_sales`:
  1. Realizar venta de 1/2 Pollo (1P, 1M, 1C, 1A).
  2. Anular venta con PIN de Administrador -> presas reingresan a vitrina.
  3. Ejecutar arqueo físico reportando 0 presas en vitrina.
  4. Assert que `has_theft_alert == True` y `theft_alert_detail` reporte faltante de presas devueltas por venta anulada.

---

## 7. Plan de Acción y Recomendaciones para Implementadores

1. **Paso 1 (Inmediato):** Aplicar el fix de `DB_PATH` en `app/database.py` y `tests/conftest.py` para reactivar la ejecución de la suite de pruebas.
2. **Paso 2:** Crear las tablas `vitrina_audits` y `cancellation_audit_log` en `app/database.py` dentro de `init_db()`.
3. **Paso 3:** Implementar los endpoints de arqueo físico en `app/routers/cash.py` (`/api/cash/vitrina-status`, `/api/cash/vitrina-audit`).
4. **Paso 4:** Actualizar `app/templates/cash.html` incorporando el formulario interactivo de conteo físico de vitrina, el semáforo de discrepancias y la alerta roja de ventas anuladas sospechosas.
5. **Paso 5:** Implementar la suite `tests/test_audit_r1_to_r5.py` y validar la ejecución limpia de todos los tests.
