# Reporte de Auditoría y Encuesta Detallada: Punto de Venta (POS) Mostrador

**Misión:** Encuesta detallada de la interfaz táctil del Punto de Venta (POS), mecánica de comanda y flujos de pago para el restaurante "Pollo Apanado" frente al Requisito R1.  
**Fecha:** 2026-10-21  
**Agente:** `explorer_survey_2`  
**Ruta de Trabajo:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_survey_2\`

---

## Resumen Ejecutivo

La interfaz del mostrador POS implementa una arquitectura moderna orientada a tablet (FastAPI + Jinja2 + Tailwind CSS + Vanilla JS con haptic feedback), pero **falla en el cumplimiento estricto del Requisito R1** debido a la ausencia de validación activa de existencias en vivo (permite vender presas agotadas con stock negativo), pérdida irrecuperable de inventario al anular ventas de combos (`POL-14`, `POL-12`, `POL-ENT`), colisiones de concurrencia en la generación del código de comanda `sale_code` que provocan errores HTTP 500 bajo carga, y aceptación en backend de pagos en efectivo incompletos sin validación de saldo.

---

## 1. Observation (Observaciones Directas y Evidencia)

### 1.1. Inspección de Archivos Frontend
- **Plantilla HTML principal:** `app/templates/index.html` (258 líneas).
  - Configuración viewport: `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">` (línea 5).
  - PWA Manifest: `<link rel="manifest" href="/manifest.json">` (línea 7).
  - Prevención de selección accidental en pantalla táctil: `<body class="... select-none overflow-hidden">` (línea 30).
  - Arquitectura de pantalla dividida:
    - 65% Izquierda: Menú táctil de productos (`#productsGrid`, línea 113) con selector por pestañas (`.cat-btn`, líneas 90-110).
    - 35% Derecha: Ticket / Comanda activa (`#cartItemsList`, línea 134), visualizador de total (`#cartTotalDisplay`, línea 149), y botones de cobro en 1 toque (Efectivo, Nequi/Daviplata, Datáfono, líneas 153-166).
    - Modales flotantes: `#presaModal` (líneas 172-209) para selección de presa en Almuerzo Completo, y `#cashModal` (líneas 212-252) para cobro en efectivo.
    - Banner de anulación temporal: `#lastSaleBanner` (líneas 71-80) con botón para deshacer venta.
- **Hoja de estilos táctiles:** `app/static/css/style.css` (47 líneas).
  - Desactivación de retraso de doble tap y resaltado azul: `* { touch-action: manipulation; -webkit-tap-highlight-color: transparent; }` (líneas 2-5).
  - Efecto tactile-feedback en tarjetas: `.touch-card:active { transform: scale(0.96); }` (líneas 32-37).
- **Lógica de interacción frontend:** `app/static/js/pos.js` (406 líneas).
  - Estado reactivo local: `cart = []`, `allProducts = []`, `stockSummary = {}`, `currentCategory = 'todos'`, `lastSaleId = null`.
  - Polling periódico de inventario: `setInterval(loadStockSummary, 15000);` (línea 15).
  - Haptic feedback mediante `navigator.vibrate` en botones: toques de producto (25ms), selección de presa (30ms), stepper +/- (20ms), eliminación (35ms), vaciado de comanda (50ms) y checkout exitoso ([40, 60, 40]ms).

---

### 1.2. Mecánica de Comanda y Gestión de Estado

#### Controles de Aumento (+), Disminución (-) y Eliminación
En `app/static/js/pos.js` (líneas 170-212):
```javascript
function addToCart(product, chosen_presa = null) {
  const existing = cart.find(it => it.product.id === product.id && it.chosen_presa === chosen_presa);
  if (existing) {
    existing.quantity++;
  } else {
    cart.push({ product: product, quantity: 1, chosen_presa: chosen_presa });
  }
  renderCart();
}

function incrementItem(idx) {
  if (navigator.vibrate) navigator.vibrate(20);
  cart[idx].quantity++;
  renderCart();
}

function decrementItem(idx) {
  if (navigator.vibrate) navigator.vibrate(20);
  if (cart[idx].quantity > 1) {
    cart[idx].quantity--;
  } else {
    cart.splice(idx, 1);
  }
  renderCart();
}

function removeItem(idx) {
  if (navigator.vibrate) navigator.vibrate(35);
  cart.splice(idx, 1);
  renderCart();
}
```
- **Observación comanda:**
  - El agrupamiento de ítems en el carrito considera adecuadamente `it.chosen_presa === chosen_presa`, permitiendo tener en la misma comanda un "Almuerzo Completo (Pechuga)" y un "Almuerzo Completo (Muslo)" como líneas independientes.
  - Al decrementar a 0 (`quantity <= 1`), se elimina el ítem automáticamente sin dejar filas vacías.
  - El botón `Vaciar` (`clearCart()`) limpia el arreglo y restablece el estado vacío `#cartEmptyState`.
- **Fricción identificada en controles:**
  - Los botones de incremento y decremento (`incrementItem`, `decrementItem`) tienen un tamaño de clase Tailwind `w-8 h-8` (32px × 32px, `app/templates/index.html:253,257`). Los estándares ergonómicos táctiles (WCAG / Android Material / Apple HIG) exigen un área táctil mínima de 44px × 44px o 48px × 48px para evitar pulsaciones erróneas en pantalla de mostrador.
  - Al presionar repetidamente `+` (`incrementItem`), **no existe límite superior ni verificación contra el stock físico**. El cajero puede incrementar la cantidad indefinidamente a 50 o 100 unidades de un producto con stock 1.

---

### 1.3. Flujo de Almuerzo Completo ($16.000 COP) y Selección de Presa

#### Obligatoriedad de Presa
- En base de datos (`app/database.py:146`):
  `('ALM-COMP', 'Almuerzo Completo', 'almuerzos', 16000, 8000, 1, '🍽️', 'emerald')`
  Tiene la bandera `requires_presa_selection = 1`.
- En frontend (`app/static/js/pos.js:126-133`):
  ```javascript
  if (product.requires_presa_selection) {
    pendingPresaProduct = product;
    openPresaModal();
  } else {
    addToCart(product);
  }
  ```
  Al tocar la tarjeta del Almuerzo Completo, se abre forzosamente el modal `#presaModal`.
- En backend (`app/routers/pos.py:67-71`):
  ```python
  if product["requires_presa_selection"] and not item.chosen_presa:
      raise HTTPException(
          status_code=400, 
          detail=f"El producto '{product['name']}' requiere elegir la presa exacta para no descuadrar el inventario."
      )
  ```
- **Conclusión de obligatoriedad:** La selección de presa es efectivamente obligatoria tanto a nivel visual como en el API.

#### Verificación de Existencias en Vivo (Falla Crítica de R1)
- En frontend (`app/static/js/pos.js:146-159`):
  ```javascript
  function updateStockBadgesInModal() {
    if (stockSummary['pechuga_vitrina']) {
      document.getElementById('stock-pechuga-badge').textContent = `Quedan ${stockSummary['pechuga_vitrina'].stock} listas`;
    }
    // ... muslo, contramuslo, ala
  }
  ```
- En `app/templates/index.html` (líneas 181-200), los botones del modal:
  `<button onclick="confirmPresaChoice('Pechuga')" class="...">`
  **No tienen propiedad `disabled`, ni clase visual de inhabilitación cuando el stock es 0**.
- En `pos.js:161-167`:
  ```javascript
  function confirmPresaChoice(presa) {
    if (navigator.vibrate) navigator.vibrate(30);
    if (pendingPresaProduct) {
      addToCart(pendingPresaProduct, presa);
    }
    closePresaModal();
  }
  ```
  **No evalúa si `stockSummary[presa_key].stock <= 0`**. Permite confirmar la presa sin importar si hay 0 disponibles.
- En backend (`app/routers/pos.py:152-159`):
  ```python
  elif sku == 'ALM-COMP':
      if chosen_presa:
          presa_key = f"{chosen_presa.lower()}_vitrina"
          cursor.execute("UPDATE inventory SET stock = stock - ? WHERE item_key = ?", (qty, presa_key))
      cursor.execute("UPDATE inventory SET stock = stock - ? WHERE item_key = 'caldo_raciones'", (qty,))
      cursor.execute("UPDATE inventory SET stock = stock - ? WHERE item_key = 'arroz_raciones'", (qty,))
      cursor.execute("UPDATE inventory SET stock = stock - ? WHERE item_key = 'frijoles_raciones'", (qty,))
  ```
  **No realiza validación previa de stock suficiente** (`SELECT stock FROM inventory ...` o `WHERE stock >= qty`).
- **Prueba empírica ejecutada:**
  ```python
  # Orden de 1000 alas con stock disponible = 29
  res = client.post('/api/pos/checkout', json={'items': [{'product_id': ala_prod['id'], 'quantity': 1000}], 'payment_method': 'efectivo', 'cash_received': 9000000})
  # Resultado: HTTP 200 OK
  # Stock final resultante en base de datos: -971.0 unidades
  ```
  **Resultado:** El sistema permite vender piezas no disponibles y deja el inventario en números negativos, violando directamente el Requisito R1 (*"verificación de existencias en vivo"*).

---

### 1.4. Flujos de Pago y Cálculo de Cambio

#### Cálculo de Cambio en Efectivo
- En frontend (`app/static/js/pos.js:315-331`):
  ```javascript
  function updateChangeCalculation() {
    const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
    const received = parseFloat(document.getElementById('cashReceivedInput').value) || 0;
    const change = Math.max(0, received - total);
    document.getElementById('cashChangeDisplay').textContent = formatCOP(change);
  }
  ```
- Botones de denominaciones rápidas en `app/templates/index.html:235-239`:
  `$10.000`, `$20.000`, `$50.000`, `$100.000`, y `Pago Exacto`.
- **Fricción ergonómica observada:**
  - Las funciones `setCashAmount(val)` asignan `input.value = val` directamente en lugar de sumar acumulativamente. Si el cliente paga con un billete de $50k y uno de $10k ($60k), presionar `$50.000` y luego `$10.000` reemplaza el valor a $10.000 en vez de sumar $60.000.
  - Al tocar el campo `cashReceivedInput` de tipo `<input type="number">`, se despliega el teclado numérico del sistema operativo de la tablet, el cual frecuentemente oculta el botón "CONFIRMAR PAGO EN EFECTIVO" en pantallas de 10 pulgadas.
- **Validación de monto recibido en backend:**
  - En frontend existe un control: `if (received < total) alert("El monto recibido no puede ser menor al total de la cuenta.");`
  - Sin embargo, en backend (`app/routers/pos.py:87`):
    `change_returned = max(0, payload.cash_received - total_amount) if payload.payment_method == "efectivo" else 0`
    **No valida que `cash_received >= total_amount`**.
  - **Prueba empírica ejecutada:**
    Se envió un pedido de $16.000 COP con `cash_received = 5000`.
    **Resultado:** Respuesta `HTTP 200 OK`, registrando la venta con `cash_received: 5000` y `change_returned: 0`, permitiendo registrar ventas con faltante de dinero en caja.

#### Pagos Digitales (Nequi, Daviplata, Datáfono)
- En frontend (`app/static/js/pos.js:284-287`):
  ```javascript
  } else {
    // Pago digital directo (Nequi, Daviplata, Datáfono)
    processCheckout(method, total);
  }
  ```
- **Riesgo operativo:** Al tocar el botón `NEQUI/DAVI` o `DATÁFONO`, se procesa la venta en un solo toque, sin solicitar confirmación ("¿Confirmar cobro de $X?"), sin campo para registrar número de comprobante/aprobación ni validar que la transacción en el datáfono físico fue exitosa. Un roce accidental en la pantalla táctil graba la transacción de inmediato.

---

### 1.5. Bugs Críticos y Riesgos de Discrepancia Identificados

#### Hallazgo 1: Pérdida Irrecuperable de Stock al Anular Ventas de Combos (`POL-14`, `POL-12`, `POL-ENT`)
- En `app/routers/pos.py`, el endpoint `cancel_sale` (líneas 218-265) desglosa y devuelve el stock de piezas individuales (`POL-PEC`, `POL-MUS`, etc.), almuerzos (`ALM-COMP`), gaseosas y porciones.
- **Sin embargo, omite por completo los combos de pollo:**
  `POL-14` (1/4 Pollo), `POL-12` (1/2 Pollo) y `POL-ENT` (Pollo Entero) **NO están contemplados en la reversión de inventario**.
- **Prueba empírica ejecutada:**
  1. Stock de Pechugas inicial: 30.0.
  2. Venta de 1 Pollo Entero (`POL-ENT`): stock bajó a 28.0 (descontó 2 pechugas).
  3. Ejecución de anulación vía `/api/pos/cancel-sale/{sale_id}`: Retornó `HTTP 200 OK` con mensaje *"Venta anulada y stock devuelto a vitrina/nevera"*.
  4. Stock de Pechugas verificado posterior a la anulación: **28.0**.
  - **Evidencia:** Las 2 pechugas, 2 alas, 2 muslos, 2 contramuslos y 2 porciones de papas nunca fueron restituidas al inventario, generando descuadre matemático permanente.

#### Hallazgo 2: Colisión de Concurrencia en `sales.sale_code`
- En `app/routers/pos.py` (líneas 55-56):
  ```python
  sale_count = cursor.execute("SELECT COUNT(*) FROM sales WHERE date_str = ?", (date_str,)).fetchone()[0] + 1
  sale_code = f"VTA-{now.strftime('%y%m%d')}-{sale_count:04d}"
  ```
  La tabla `sales` define `sale_code TEXT UNIQUE NOT NULL` (`app/database.py:54`).
- **Prueba empírica de concurrencia:**
  Se simularon 10 transacciones rápidas concurrentes con 5 workers en `ThreadPoolExecutor`.
  - **Resultado:**
    `Statuses: [200, 500, 500, 200, 500, 200, 500, 500, 200, 200]`
    **5 de las 10 transacciones (50% de fallo) colapsaron con error HTTP 500**:
    `{'detail': 'UNIQUE constraint failed: sales.sale_code'}`
  - Esto viola frontalmente el criterio de aceptación de estrés de concurrencia de R5 y genera congelamiento/error al cajero en horas pico.

#### Hallazgo 3: Enmascaramiento de Excepciones HTTP (`HTTPException` convertida en 500)
- En `app/routers/pos.py` (líneas 188-190):
  ```python
  except Exception as e:
      conn.rollback()
      raise HTTPException(status_code=500, detail=str(e))
  ```
  Dado que en FastAPI `HTTPException` hereda de `Exception`, cualquier validación que lance `raise HTTPException(status_code=400, ...)` (como la falta de presa en el Almuerzo) es capturada por el bloque genérico y re-lanzada como un error interno de servidor `HTTP 500`.
- **Prueba empírica ejecutada:**
  Un checkout sin presa devolvió:
  `HTTP 500 {'detail': "400: El producto 'Almuerzo Completo' requiere elegir la presa exacta para no descuadrar el inventario."}`

#### Hallazgo 4: Omisión de Inventario para "Porción de Arepas" (`POR-AREP`)
- El producto `POR-AREP` ("Porción de Arepas", $2.000 COP) existe en `products` (`app/database.py:153`).
- Sin embargo, no existe en la tabla `inventory` ni en la lógica de descuento de `process_checkout` ni en `cancel_sale`. Se vende sin control alguno de insumo.

#### Hallazgo 5: Riesgo de Alcance Global en `filterCategory`
- En `app/templates/index.html` (líneas 90-106): `onclick="filterCategory('todos')"`.
- En `app/static/js/pos.js` (línea 62): `const activeBtn = event.currentTarget;`.
- La variable `event` no se pasa como parámetro en la firma de la función, descansando en el objeto global no estándar `window.event`, lo que genera inconsistencias en navegadores que operan bajo estándares estrictos de eventos.

---

## 2. Logic Chain (Cadena Lógica de Deducción)

1. **Premisa R1:** El Requisito R1 exige un Punto de Venta táctil robusto con:
   - Comanda interactiva (+, -, eliminar ítem) sin retrasos.
   - Selección obligatoria de presa para el Almuerzo Completo ($16.000 COP) **con verificación de existencias en vivo**.
   - Cálculo exacto de cambio en efectivo y pagos digitales (Nequi/Daviplata y Datáfono).
2. **De la Observación 1.3:** Se constató que `openPresaModal()` y `updateStockBadgesInModal()` muestran la cantidad en texto pero no inhabilitan el botón de la presa cuando `stock <= 0`, y el backend decrementa `inventory` sin condición `WHERE stock >= qty`.
   - *Deducción:* Si la vitrina tiene 0 pechugas, un cliente o cajero puede pedir 5 almuerzos con pechuga y el sistema lo procesa exitosamente arrojando stock -5. Esto **invalida** la premisa de "verificación de existencias en vivo", generando faltantes físicos in situ.
3. **De la Observación 1.5 (Hallazgo 1):** `cancel_sale` contiene ramas `elif` específicas para `POL-PEC`, `POL-MUS`, `ALM-COMP`, etc., pero omitió completamente `POL-14`, `POL-12` y `POL-ENT`.
   - *Deducción:* Cada vez que un cajero anula una venta por error que contenga un pollo entero o combo, el dinero se anula en caja pero el pollo frito desaparece contablemente del sistema sin reingresar a vitrina, provocando mermas ficticias y descuadre entre cocina y mostrador.
4. **De la Observación 1.5 (Hallazgo 2):** El cálculo de `sale_code` lee `SELECT COUNT(*) FROM sales` antes de insertar. En presencia de solicitudes concurrentes (e.g. tablet de mostrador + pedidos entrantes simultáneos), ambas leen el mismo contador e intentan insertar con el mismo `sale_code`, violando la restricción `UNIQUE`.
   - *Deducción:* El sistema colapsa bajo estrés en horas pico con errores 500 en lugar de garantizar resiliencia transaccional.
5. **De la Observación 1.4:** El backend acepta cualquier valor en `cash_received` sin verificar si cubre el total de la orden.
   - *Deducción:* El control de caja depende 100% del cliente JavaScript. Cualquier fallo en el navegador o petición externa permite registrar ventas pagadas parcialmente como ventas completadas.

---

## 3. Caveats (Advertencias y Supuestos)

1. **Hardware físico táctil:** La auditoría se ejecutó en entorno emulado y análisis de código fuente; no se probó físicamente en la pantalla táctil de 10 pulgadas con guantes de cocina reales, aunque las dimensiones CSS (32px de botón stepper) se compararon directamente contra las pautas de accesibilidad estándar (44px-48px).
2. **Conectividad de datáfono:** El sistema actual modela los pagos digitales como transacciones offline/manuales (el cajero confirma en datáfono físico y registra el cobro en el sistema). No existe integración directa vía API bancaria ni webhook de Nequi/Daviplata; el riesgo radica en la ausencia de un diálogo de confirmación que evite pulsaciones involuntarias.

---

## 4. Conclusion (Conclusiones y Dictamen de Auditoría)

El Punto de Venta Mostrador presenta una base sólida en cuanto a diseño visual, catálogo de productos, unit economics y rapidez básica de interfaz, pero **NO CUMPLE los criterios de certificación de producción para R1** en su estado actual debido a cinco defectos críticos:

| Defecto | Gravedad | Impacto en R1 / Operación |
|---|---|---|
| **Ausencia de bloqueo de stock en vivo** | **Crítica** | Venta permitida de presas agotadas; deriva a stock negativo. |
| **Omisión de combos en `cancel_sale`** | **Crítica** | Descuadre de inventario al anular ventas de 1/4, 1/2 y Pollo Entero. |
| **Colisión de concurrencia en `sale_code`** | **Alta** | Caída del 50% de transacciones concurrentes con error HTTP 500. |
| **Aceptación de efectivo insuficiente en backend** | **Alta** | Riesgo de descuadre de caja por transacciones con faltante de pago. |
| **Captura indiscriminada de `HTTPException`** | **Media** | Enmascara errores 400 de validación convirtiéndolos en HTTP 500. |
| **Ergonomía táctil de stepper y teclado numérico** | **Media** | Botones de 32px difíciles de pulsar; teclado virtual cubre modal. |

---

## 5. Verification Method (Método de Verificación Independiente)

Para que cualquier agente auditor independiente o desarrollador verifique y reproduzca estos hallazgos, ejecute los siguientes comandos en PowerShell desde el directorio raíz del proyecto (`c:\Users\Alejandro\Desktop\POLLO APANADO`):

### Verificación 1: Reproducción de Stock Negativo (Falla de Validación en Vivo)
```powershell
python -c "
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db
init_db()
client = TestClient(app)
products = client.get('/api/pos/products').json()
ala = next(p for p in products if p['sku'] == 'POL-ALA')
res = client.post('/api/pos/checkout', json={
    'items': [{'product_id': ala['id'], 'quantity': 9999}],
    'payment_method': 'efectivo',
    'cash_received': 99990000
})
assert res.status_code == 200, 'Deberia haber rechazado pero aceptó'
stock = client.get('/api/pos/stock-summary').json()['ala_vitrina']['stock']
print(f'Falla confirmada: El sistema aceptó la venta y el stock quedó en {stock}')
"
```

### Verificación 2: Descuadre de Inventario al Cancelar Pollo Entero
```powershell
python -c "
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db
init_db()
client = TestClient(app)
products = client.get('/api/pos/products').json()
entero = next(p for p in products if p['sku'] == 'POL-ENT')
stock_ini = client.get('/api/pos/stock-summary').json()['pechuga_vitrina']['stock']
sale = client.post('/api/pos/checkout', json={
    'items': [{'product_id': entero['id'], 'quantity': 1}],
    'payment_method': 'efectivo',
    'cash_received': 36000
}).json()
client.post(f'/api/pos/cancel-sale/{sale[\"sale_id\"]}')
stock_fin = client.get('/api/pos/stock-summary').json()['pechuga_vitrina']['stock']
assert stock_fin != stock_ini, f'Error: El stock debio ser {stock_ini} pero quedo en {stock_fin}'
print(f'Falla confirmada: Stock no restituido. Inicial: {stock_ini}, Final: {stock_fin}')
"
```

### Verificación 3: Colisión de Concurrencia en `sale_code`
```powershell
python -c "
import concurrent.futures
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db
init_db()
client = TestClient(app)
caldo_id = next(p['id'] for p in client.get('/api/pos/products').json() if p['sku'] == 'POR-CALD')
def vta(i):
    return client.post('/api/pos/checkout', json={'items': [{'product_id': caldo_id, 'quantity': 1}], 'payment_method': 'efectivo', 'cash_received': 6000}).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    codes = list(ex.map(vta, range(10)))
print('Falla confirmada si hay codigos 500:', codes)
assert 500 in codes, 'Se esperaba colision de concurrencia'
"
```

---
*Fin del Reporte de Auditoría de `explorer_survey_2`.*
