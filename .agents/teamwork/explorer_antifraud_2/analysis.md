# Reporte de Investigación: Módulo de Seguridad Antifraude y Auditoría Forense (Requerimiento R3)

**Agente Investigador**: `explorer_antifraud_2` (Teamwork Preview Explorer)  
**Fecha y Hora**: 2026-10-21T04:46:00Z  
**Proyecto**: Pollo Apanado — Sistema POS & Gestión Operativa  
**Ruta de Trabajo**: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_antifraud_2\`  
**Estado**: Finalizado (Read-Only Analysis)

---

## 1. Resumen Ejecutivo

El presente reporte entrega la investigación técnica, análisis de vulnerabilidades del flujo actual de ventas y propuesta exhaustiva de arquitectura para el **Requerimiento R3 (Módulo Antifraude con PIN de Administrador/Socio y Bitácora Forense Inmutable)**.

### Hallazgos Principales:
1. **Flujo Actual de Anulación Vulnerable**: Actualmente en `app/routers/pos.py:322-380`, el endpoint `POST /api/pos/cancel-sale/{sale_id}` **carece de cualquier verificación de permisos, autenticación o PIN**. En frontend (`app/static/js/pos.js:706-723`), la anulación se activa mediante un simple `confirm()` de navegador sin solicitar PIN ni motivo.
2. **Inexistencia de `/api/pos/cancel/{id}`**: Dicho endpoint no existe; la ruta vigente es `/api/pos/cancel-sale/{sale_id}`. Se propone implementar un alias para soportar ambas rutas.
3. **Ausencia Total de Registro Forense**: Cuando una venta es anulada, el estado pasa a `'anulada'` y el stock se suma al inventario, pero **no se almacena ningún registro** de quién autorizó, a qué segundo exacto ocurrió, qué presas específicas reingresaron, ni el motivo de la anulación.
4. **Vulnerabilidad de Robo por Anulación**: Un cajero infiel puede cobrar en efectivo (ej. $36.000 COP por un pollo entero), entregar el pedido, anular la venta inmediatamente en el banner superior, sustraer el dinero físico del cajón y crear un descuadre fantasma en vitrina.
5. **Reporte de Caja Huérfano de Alertas**: En `app/routers/cash.py` y `app/templates/cash.html`, las ventas anuladas simplemente se excluyen del resumen diario con `WHERE status = 'completada'`, sin generar alertas, sin indicar dinero devuelto y sin listar las presas que debieron reingresar a la vitrina térmica.
6. **Defecto de Infraestructura de Pruebas Descubierto**: En `tests/conftest.py:22`, la fixture `isolated_db` intenta hacer `monkeypatch.setattr(database, "DB_PATH", str(test_db_file))`, pero `app/database.py` no declara `DB_PATH = None` a nivel de módulo, causando `AttributeError` en todas las suites de pytest.

---

## 2. Inspección del Flujo Actual de Anulación

### 2.1 Archivos Involucrados
| Componente | Archivo | Líneas | Rol Actual |
|---|---|---|---|
| **Rutas Backend** | `app/routers/pos.py` | 322–380 | Función `cancel_sale(sale_id: int)` expuesta en `POST /api/pos/cancel-sale/{sale_id}`. |
| **Plantilla POS** | `app/templates/index.html` | 70–80 | Banner `#lastSaleBanner` con botón `#btnUndoSale` que invoca `cancelLastSale()`. *(Nota: `app/templates/pos.html` no existe; la vista POS es servida por `index.html`)*. |
| **Lógica Frontend** | `app/static/js/pos.js` | 692–723 | Funciones `showLastSaleBanner(saleData)` y `cancelLastSale()`. |
| **Base de Datos** | `app/database.py` | 58–74 | Tabla `sales` con columna `status TEXT DEFAULT 'completada'`. |

### 2.2 ¿Existe el endpoint `/api/pos/cancel/{id}`?
**No.** Tras ejecutar búsqueda exhaustiva por grep en todo el proyecto:
- El único endpoint de anulación registrado es: `POST /api/pos/cancel-sale/{sale_id}` (`pos.py:322`).
- No existe ningún endpoint `/api/pos/cancel/{id}`.
- **Recomendación arquitectónica**: Mantener la ruta original `POST /api/pos/cancel-sale/{sale_id}` (utilizada por frontend y tests existentes) y agregar el alias `POST /api/pos/cancel/{sale_id}` apuntando al mismo controlador.

### 2.3 Mecanismo Actual y Vulnerabilidades
En `app/static/js/pos.js`:
```javascript
// Líneas 706-723 de app/static/js/pos.js
async function cancelLastSale() {
  if (!lastSaleId) return;
  if (!confirm("¿Seguro que deseas anular la última venta y devolver los productos al inventario?")) return;

  try {
    const res = await fetch(`/api/pos/cancel-sale/${lastSaleId}`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "No se pudo anular");

    alert("✅ " + data.message);
    document.getElementById('lastSaleBanner').classList.add('hidden');
    lastSaleId = null;
    loadStockSummary();
  } catch (err) {
    alert("Error al anular: " + err.message);
  }
}
```

En `app/routers/pos.py`:
```python
# Líneas 322-380 de app/routers/pos.py
@router.post("/cancel-sale/{sale_id}")
def cancel_sale(sale_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Transición atómica de estado
        cursor.execute("""
            UPDATE sales 
            SET status = 'anulada' 
            WHERE id = ? AND status != 'anulada'
        """, (sale_id,))

        if cursor.rowcount == 0:
            sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

        # Reversión de inventario simétrica
        items = cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
        # ... cálculo y suma a inventory.stock ...
        conn.commit()
        return {"success": True, "message": f"Venta {sale_code} anulada y stock devuelto a vitrina/nevera."}
```

**Brecha de Seguridad**: Cualquier empleado con acceso a la pantalla táctil puede anular una venta sin requerir clave de supervisor. No se pide motivo, no se valida identidad y no se deja rastro de autorizador.

---

## 3. Especificación de Seguridad: PIN de Administrador / Socio

### 3.1 Jerarquía de Configuración del PIN
Para cumplir con estándares de producción de 12 factores y facilidad de despliegue en Docker:
1. **Variable de Entorno**: `os.environ.get("ADMIN_PIN")` (prioridad alta).
2. **Tabla de Base de Datos (`system_settings`)**: `SELECT value FROM system_settings WHERE key = 'admin_pin'`.
3. **Valor Predeterminado de Respaldo**: `'4321'` (o `'1234'`).

Asimismo, para soportar a los socios de la compraventa (Socio 1, Socio 2 y Socio Operativo Santiago):
- Se puede permitir una lista de PINs autorizados en `system_settings` o un PIN maestro.
- Ejemplo de configuración predeterminada:
  - `admin_pin`: `'4321'` (Administrador General)
  - `partner_1_pin`: `'1111'` (Socio Capital 1)
  - `partner_2_pin`: `'2222'` (Socio Capital 2)
  - `partner_santiago_pin`: `'3333'` (Socio Operativo Santiago)

### 3.2 Esquema del Payload de Solicitud (Pydantic)
```python
from pydantic import BaseModel, Field
from typing import Optional

class CancelSaleRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=10, description="PIN de seguridad de Administrador/Socio")
    reason: Optional[str] = Field("Error de digitación", description="Motivo declarado de la anulación")
    authorized_by: Optional[str] = Field("Administrador", description="Nombre o identificación del autorizador")
```

### 3.3 Rechazo Estricto HTTP 403 Forbidden
Para blindar el endpoint contra intentos no autorizados y ataques de fuerza bruta:
- **Protección contra Timing Attacks**: Utilizar `secrets.compare_digest(provided_pin, valid_pin)`.
- **Validación de Presencia**: Si el PIN no es enviado, es `None`, cadena vacía o espacio en blanco:
  ```python
  if not pin or not pin.strip():
      raise HTTPException(
          status_code=403,
          detail="Acceso denegado: Se requiere PIN de Administrador/Socio para anular ventas."
      )
  ```
- **Validación de Coincidencia**: Si el PIN no coincide con el configurado:
  ```python
  if not secrets.compare_digest(pin.strip(), configured_pin.strip()):
      raise HTTPException(
          status_code=403,
          detail="Acceso denegado: PIN de Administrador/Socio inválido."
      )
  ```
- **Soporte Híbrido de Envío de PIN**:
  Para máxima compatibilidad (frontend JSON, clientes REST, llamadas programáticas y tests), el PIN debe poder recibirse mediante:
  1. Cuerpo JSON: `payload.pin`
  2. Encabezado HTTP: `X-Admin-PIN: <pin>`
  3. Query param: `?pin=<pin>`
  Si no se proporciona en ninguna de estas fuentes o es inválido, se rechaza inmediatamente con **HTTP 403**.

---

## 4. Diseño de la Bitácora Forense Inmutable (`sale_cancellation_audit`)

### 4.1 Requerimientos Forenses
Según `ORIGINAL_REQUEST.md`:
> *"Toda anulación guarda permanentemente la fecha, hora, segundo exacto, motivo y usuario autorizador."*
> *"El informe de caja incluye un recuadro en rojo con la auditoría de ventas anuladas, el dinero que fue revertido y las presas exactas que debieron reingresar a la vitrina."*

### 4.2 Esquema DDL en SQLite
```sql
CREATE TABLE IF NOT EXISTS sale_cancellation_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    sale_code TEXT NOT NULL,
    cancelled_at TEXT NOT NULL,              -- ISO-8601 completo: '2026-10-21T14:35:22'
    date_str TEXT NOT NULL,                  -- 'YYYY-MM-DD' para consultas veloces indexadas
    time_str TEXT NOT NULL,                  -- 'HH:MM:SS' con segundo exacto
    total_amount INTEGER NOT NULL,           -- Monto en COP reintegrado
    payment_method TEXT NOT NULL,            -- 'efectivo', 'nequi_daviplata', 'datafono'
    reason TEXT NOT NULL,                    -- Motivo declarado
    authorized_by TEXT NOT NULL,             -- Quien autorizó ('Socio 1', 'Administrador', etc.)
    pin_used_masked TEXT NOT NULL,           -- '****' o 'PIN_ADMIN_VALIDADO' (no almacenar PIN en texto plano)
    restored_items_json TEXT NOT NULL,       -- JSON de ítems vendidos que fueron devueltos
    restored_presas_summary TEXT NOT NULL,   -- JSON de presas devueltas: {"pechugas": 2, "muslos": 2, ...}
    restored_inventory_json TEXT NOT NULL,   -- JSON de insumos devueltos a inventory
    FOREIGN KEY (sale_id) REFERENCES sales (id)
);

CREATE INDEX IF NOT EXISTS idx_cancellation_date ON sale_cancellation_audit (date_str);
CREATE INDEX IF NOT EXISTS idx_cancellation_sale ON sale_cancellation_audit (sale_id);
```

### 4.3 Inmutabilidad Real a Nivel de Motor (Triggers SQLite)
Para garantizar que **nadie** pueda modificar ni borrar registros de auditoría forense una vez creados:
```sql
CREATE TRIGGER IF NOT EXISTS trg_prevent_cancellation_audit_update
BEFORE UPDATE ON sale_cancellation_audit
BEGIN
    SELECT RAISE(ABORT, 'Violación de Seguridad Forense: La bitácora de anulaciones es estrictamente inmutable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_prevent_cancellation_audit_delete
BEFORE DELETE ON sale_cancellation_audit
BEGIN
    SELECT RAISE(ABORT, 'Violación de Seguridad Forense: La bitácora de anulaciones es estrictamente inmutable.');
END;
```
Estos disparadores garantizan inmutabilidad matemática: cualquier comando `UPDATE` o `DELETE` sobre la tabla arroja una excepción fatal de SQLite.

### 4.4 Cálculo de Presas Devueltas para la Bitácora
Al momento de anular la venta, se desglosa el impacto exacto en presas:
```python
def extract_presas_breakdown(items_data):
    """Calcula la cantidad exacta de presas que deben volver a la vitrina térmica."""
    presas = {"pechugas": 0, "muslos": 0, "contramuslos": 0, "alas": 0, "total_presas": 0}
    for item in items_data:
        sku = item.get("product_sku")
        qty = int(item.get("quantity", 0))
        presa = item.get("chosen_presa")

        if sku == 'POL-PEC' or presa == 'Pechuga':
            presas["pechugas"] += qty
        elif sku == 'POL-MUS' or presa == 'Muslo':
            presas["muslos"] += qty
        elif sku == 'POL-CON' or presa == 'Contramuslo':
            presas["contramuslos"] += qty
        elif sku == 'POL-ALA' or presa == 'Ala':
            presas["alas"] += qty
        elif sku == 'POL-14':
            presas["muslos"] += qty
            presas["contramuslos"] += qty
        elif sku == 'POL-12':
            presas["pechugas"] += qty
            presas["alas"] += qty
            presas["muslos"] += qty
            presas["contramuslos"] += qty
        elif sku == 'POL-ENT':
            presas["pechugas"] += 2 * qty
            presas["alas"] += 2 * qty
            presas["muslos"] += 2 * qty
            presas["contramuslos"] += 2 * qty

    presas["total_presas"] = (
        presas["pechugas"] + presas["muslos"] + presas["contramuslos"] + presas["alas"]
    )
    return presas
```

---

## 5. Reporte de Cierre de Caja: Alerta Roja Forense

### 5.1 Enriquecimiento del Endpoint `GET /api/cash/daily-summary`
En `app/routers/cash.py`, la función `get_daily_summary(date_str: Optional[str] = None)` debe consultar `sale_cancellation_audit`:

```python
# Consulta de anulaciones del día
cancellations = conn.execute("""
    SELECT 
        id, sale_id, sale_code, cancelled_at, date_str, time_str,
        total_amount, payment_method, reason, authorized_by,
        restored_items_json, restored_presas_summary
    FROM sale_cancellation_audit
    WHERE date_str = ?
    ORDER BY id DESC
""", (date_str,)).fetchall()

total_cancelled_amount = sum(c["total_amount"] for c in cancellations)
refunded_by_method = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0}
returned_presas = {"pechugas": 0, "muslos": 0, "contramuslos": 0, "alas": 0, "total": 0}

for c in cancellations:
    method = c["payment_method"]
    refunded_by_method[method] = refunded_by_method.get(method, 0) + c["total_amount"]
    try:
        p_data = json.loads(c["restored_presas_summary"])
        returned_presas["pechugas"] += p_data.get("pechugas", 0)
        returned_presas["muslos"] += p_data.get("muslos", 0)
        returned_presas["contramuslos"] += p_data.get("contramuslos", 0)
        returned_presas["alas"] += p_data.get("alas", 0)
        returned_presas["total"] += p_data.get("total_presas", 0)
    except Exception:
        pass

cancellations_audit = {
    "total_cancelled_count": len(cancellations),
    "total_refunded_cop": total_cancelled_amount,
    "refunded_by_method": refunded_by_method,
    "returned_presas_summary": returned_presas,
    "records": [
        {
            "id": c["id"],
            "sale_code": c["sale_code"],
            "time_str": c["time_str"],
            "total_amount": c["total_amount"],
            "payment_method": c["payment_method"],
            "reason": c["reason"],
            "authorized_by": c["authorized_by"],
            "restored_items": json.loads(c["restored_items_json"]) if c["restored_items_json"] else [],
            "presas": json.loads(c["restored_presas_summary"]) if c["restored_presas_summary"] else {}
        }
        for c in cancellations
    ]
}
```

### 5.2 Diseño Visual en `app/templates/cash.html`
En `cash.html`, justo debajo de las tarjetas de totales y antes del termómetro del punto de equilibrio, se ubicará el bloque `#cancelledSalesAlertSection`:

```html
<!-- SECCIÓN DE ALERTA ROJA DE VENTAS ANULADAS (MÓDULO ANTIFRAUDE) -->
<div id="cancellationsAlertCard" class="hidden rounded-2xl p-5 shadow-2xl transition-all duration-300">
  <!-- Render dinámico vía JS -->
</div>
```

#### Estado A: Cero Anulaciones (Día Limpio)
- Tarjeta verde/gris tenue:
  - Ícono: 🛡️
  - Título: **"Auditoría Forense: Cero Anulaciones Registradas Hoy"**
  - Mensaje: *"No se han efectuado reversiones de comanda ni devoluciones de dinero. El flujo de caja físico y vitrina térmica se mantiene íntegro."*

#### Estado B: Una o Más Anulaciones (Alerta Roja Destacada)
- Tarjeta con borde rojo grueso y fondo `bg-red-950/70 border-2 border-red-500`:
  - Cabecera: `🚨 ALERTA ROJA DE SEGURIDAD ANTIFRAUDE: [N] VENTA(S) ANULADA(S)`
  - Subtítulo de advertencia explícita:
    > *"⚠️ ATENCIÓN SOCIOS: Se devolvió un total de $[TOTAL_REFUNDED] COP. Verifiquen de inmediato que este dinero no haya sido sustraído del cajón y que las [TOTAL_PRESAS] presas reingresadas se encuentren físicamente en la vitrina térmica."*
  - **3 Tarjetas Resumen:**
    1. **Dinero Revertido en Efectivo**: `$[EFECTIVO_REFUNDED] COP` (Impacto directo en faltante de cajón físico).
    2. **Dinero Revertido en Medios Digitales**: `$[DIGITAL_REFUNDED] COP` (Nequi / Datáfono).
    3. **Presas que Debieron Reingresar**: `P: [x] | M: [y] | C: [z] | A: [w] (Total: [T] presas)`.
  - **Tabla de Bitácora Forense al Segundo Exacto**:
    | Hora | Código Venta | Total Anulado | Método | Presas Retornadas | Motivo Declarado | Autorizado Por |
    |---|---|---|---|---|---|---|
    | 13:42:18 | VTA-261021-0005 | $36.000 COP | Efectivo | 2P, 2M, 2C, 2A | Error en pedido | PIN Admin (Socio 1) |

---

## 6. Actualización del Flujo en Frontend Mostrador (`index.html` y `pos.js`)

### 6.1 Modal Táctil de PIN de Seguridad en Mostrador
En lugar de `window.confirm()`, al presionar `#btnUndoSale`:
1. Se despliega el modal `#adminPinModal`:
   - Título: `🔐 Autorización Requerida — Anular Venta [VTA-...]`
   - Campo 1: PIN de Seguridad (4 dígitos con teclado numérico táctil de pantalla para tablet).
   - Campo 2: Motivo de la anulación (Dropdown con opciones comunes: `"Error de digitación del cajero"`, `"Cliente desistió / no esperó"`, `"Producto devuelto / reclamo"`, `"Otro"`).
   - Campo 3: Nombre del Autorizador (`"Administrador"`, `"Socio Capital 1"`, `"Socio Operativo Santiago"`).
   - Botón: `"CONFIRMAR ANULACIÓN CON PIN"` (estilo rojo peligroso).
2. Si el cajero ingresa un PIN incorrecto:
   - El backend retorna **HTTP 403 Forbidden**.
   - El frontend vibra con patrón de error (`navigator.vibrate([100, 50, 100, 50, 100])`) y muestra mensaje en rojo: `"⛔ Acceso denegado: PIN de Administrador inválido. Intento registrado."`
3. Si el PIN es correcto:
   - El backend retorna **HTTP 200 OK**.
   - Se cierra el modal, se oculta el banner de deshacer, se refresca el stock de vitrina y se emite notificación de éxito.

---

## 7. Inventario de Archivos y Modificaciones Requeridas

| Archivo | Tipo de Cambio | Componente / Firma | Razón Técnica |
|---|---|---|---|
| `app/database.py` | Modificación | 1. Declarar `DB_PATH = None` a nivel módulo.<br>2. `CREATE TABLE sale_cancellation_audit`.<br>3. `CREATE TRIGGER trg_prevent_cancellation_audit_update`.<br>4. `CREATE TRIGGER trg_prevent_cancellation_audit_delete`.<br>5. Seed de `'admin_pin'` en `system_settings`. | Persistencia inmutable, prevención de manipulación y soporte de fixtures aisladas en tests. |
| `app/routers/pos.py` | Modificación | 1. `class CancelSaleRequest(BaseModel)` con `pin`, `reason`, `authorized_by`.<br>2. Actualizar `cancel_sale`: chequear PIN contra env/db, validar con `secrets.compare_digest`, retornar 403 si falla.<br>3. Insertar en `sale_cancellation_audit` dentro de la transacción atómica.<br>4. Registrar alias `@router.post("/cancel/{sale_id}")`. | Bloqueo por PIN, código HTTP 403 estricto y registro forense con segundo exacto. |
| `app/routers/cash.py` | Modificación | En `get_daily_summary`: consultar `sale_cancellation_audit`, calcular total devuelto, presas devueltas y adjuntar `cancellations_audit` al JSON de respuesta. | Alimentar la alerta roja del cuadre de caja con datos forenses reales. |
| `app/templates/index.html` | Modificación | Agregar `#adminPinModal` con interfaz táctil para ingreso de PIN, selector de motivo y campo autorizador. | Ergonomía táctil para tablet de mostrador y bloqueo de cajero común. |
| `app/static/js/pos.js` | Modificación | 1. Reemplazar `cancelLastSale()` para abrir modal de PIN.<br>2. Implementar `submitCancelWithPin()` enviando payload con `pin`, `reason`, `authorized_by`.<br>3. Manejo de error HTTP 403 con alerta visual roja. | Flujo de seguridad interactivo y feedback táctil. |
| `app/templates/cash.html` | Modificación | 1. Agregar contenedor HTML `#cancellationsAlertCard`.<br>2. Modificar script JS para renderizar la Alerta Roja con métricas y tabla de auditoría al segundo. | Visibilidad prioritaria para socios sobre dinero y presas devueltas. |
| `tests/conftest.py` | Modificación | Asegurar que `monkeypatch` apunte correctamente a `database.DB_PATH` sin generar `AttributeError`. | Reparar la infraestructura de testing del proyecto. |
| `tests/test_antifraud_forensic.py` | Archivo Nuevo | Suite de pruebas exhaustivas para R3 (rechazo 403 sin PIN, rechazo 403 con PIN malo, éxito 200 con PIN, inmutabilidad de triggers, reporte en caja). | Validación automatizada y certificación de seguridad. |

---

## 8. Hallazgo Adicional: Corrección de la Suite de Pruebas (`conftest.py` y `database.py`)

Durante la verificación del entorno de testing con `pytest`, se identificó que:
- `tests/conftest.py:22` ejecuta:
  ```python
  test_db_file = tmp_path / "test_asadero.db"
  monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
  ```
- Sin embargo, `app/database.py` no tenía definida la variable `DB_PATH = None` en el ámbito global del módulo, ocasionando:
  ```
  AttributeError: <module 'app.database' from '...'> has no attribute 'DB_PATH'
  ```
- **Solución recomendada para el agente constructor**:
  En `app/database.py`:
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
  Esta simple adición resuelve los 179 errores de setup de pytest y permite correr las pruebas de forma 100% aislada.

---

## 9. Matriz de Pruebas Automatizadas Recomendadas para R3

| Caso de Prueba | Endpoint / Método | Entrada | Resultado Esperado | Invariante Verificada |
|---|---|---|---|---|
| **Rechazo Sin PIN** | `POST /api/pos/cancel-sale/{id}` | `{}` o `None` | **HTTP 403 Forbidden** | Ninguna anulación puede ocurrir sin PIN. |
| **Rechazo PIN Incorrecto** | `POST /api/pos/cancel-sale/{id}` | `{"pin": "9999"}` | **HTTP 403 Forbidden** | PINs no autorizados son rechazados de inmediato. |
| **Rechazo PIN Espacios** | `POST /api/pos/cancel-sale/{id}` | `{"pin": "    "}` | **HTTP 403 Forbidden** | Se previene evasión por cadenas vacías. |
| **Aprobación PIN Válido** | `POST /api/pos/cancel-sale/{id}` | `{"pin": "4321", "reason": "Error comanda"}` | **HTTP 200 OK** | Venta pasa a 'anulada', stock reingresa. |
| **Registro en Bitácora** | DB Query | Tras anulación exitosa | `sale_cancellation_audit` contiene registro | Contiene fecha, hora, segundo, motivo, presas. |
| **Inmutabilidad Disparador UPDATE** | SQLite Query | `UPDATE sale_cancellation_audit SET total_amount = 0` | **SQLite Exception / Abort** | Triggers previenen alteración de la bitácora. |
| **Inmutabilidad Disparador DELETE** | SQLite Query | `DELETE FROM sale_cancellation_audit` | **SQLite Exception / Abort** | Triggers previenen borrado de la bitácora. |
| **Alerta en Cierre de Caja** | `GET /api/cash/daily-summary` | Parámetro `date_str` | Respuesta incluye `cancellations_audit` | Muestra conteo, dinero devuelto y presas reingresadas. |
| **Exclusión de Caja Activa** | `GET /api/cash/daily-summary` | Venta en efectivo cancelada | Dinero cancelado NO suma en `efectivo` | Caja física reporta solo dinero de ventas completadas. |
| **Re-anulación Doble** | `POST /api/pos/cancel-sale/{id}` | `{"pin": "4321"}` sobre venta ya anulada | **HTTP 400 Bad Request** | Previene doble devolución de stock o dinero. |
