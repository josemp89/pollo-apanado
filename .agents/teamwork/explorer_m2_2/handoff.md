# Informe de Análisis e Investigación: Robustez de Pagos, Validación de Efectivo y Métodos en POS

**Investigador:** Explorer 2 (Milestone M2)  
**Fecha:** 2026-10-21  
**Módulo Objetivo:** `app/routers/pos.py`  
**Directorio de Trabajo:** `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_m2_2\`

---

## 1. Observation

### Obs 1.1: Esquema de Entrada en `app/routers/pos.py`
En `app/routers/pos.py` (líneas 15–19), el esquema del cuerpo de checkout está definido como:
```python
class CheckoutRequest(BaseModel):
    items: List[CartItem]
    payment_method: str  # 'efectivo', 'nequi_daviplata', 'datafono'
    cash_received: Optional[int] = 0
    notes: Optional[str] = None
```
- El campo `payment_method` está tipado como un simple `str` sin validadores de pertenencia ni restricciones de lista blanca (`whitelist`).
- El campo `cash_received` es `Optional[int] = 0`. No valida que el valor sea mayor o igual a cero ni comprueba suficiencia contra el total.
- La clase está nombrada `CheckoutRequest`, mientras que algunas especificaciones y llamados se refieren a ella conceptualmente como `CheckoutPayload`.

### Obs 1.2: Ausencia de Validación de `payment_method` en `process_checkout`
En `app/routers/pos.py` (líneas 134–146 y subsiguientes):
```python
@router.post("/checkout")
def process_checkout(payload: CheckoutRequest):
    if not payload.items:
        raise HTTPException(status_code=400, detail="El pedido está vacío.")

    # Guard defensivo: rechazar cantidades menores o iguales a cero
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"La cantidad de cada producto debe ser mayor a 0. Recibido: {item.quantity}."
            )
```
- No existe ninguna verificación de `payload.payment_method`. Métodos arbitrarios como `"bitcoin"`, `"cheque"`, `"fiado"` o cadenas vacías son aceptados sin error.
- En la base de datos (`app/database.py`, línea 63), la columna es `payment_method TEXT NOT NULL, -- 'efectivo', 'nequi_daviplata', 'datafono'`.
- En el módulo de caja (`app/routers/cash.py`, líneas 32–37), el arqueo diario asume claves estrictas:
  ```python
  totals_dict = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0, "gran_total": 0, "total_tickets": 0}
  for row in sales_by_method:
      method = row["payment_method"]
      totals_dict[method] = row["total"] or 0
  ```
  Permitir métodos no autorizados corrompe la estructura fija de `totals_dict` y el arqueo contable.

### Obs 1.3: Subpago en Efectivo Aceptado Silenciosamente
En `app/routers/pos.py` (línea 227):
```python
change_returned = max(0, payload.cash_received - total_amount) if payload.payment_method == "efectivo" else 0
```
- Si un cliente realiza un pago en `"efectivo"` donde `payload.cash_received < total_amount` (por ejemplo, cuenta de $16.000 COP entregando $5.000 COP o $0 COP):
  - `payload.cash_received - total_amount` es negativo (`-11000`).
  - `max(0, -11000)` resulta en `0`.
  - La venta se completa exitosamente (`status = 'completada'`), el inventario se descuenta atómicamente y se guarda en la base de datos una venta con monto total de $16.000 pero dinero en caja recibido de $5.000, generando descuadre de caja físico.
- No existe validación que lance `HTTPException(status_code=400, detail="Monto en efectivo insuficiente para cubrir el total de la orden.")`.

### Obs 1.4: Orden de Ejecución y Rol del Descuento de Inventario
En `app/routers/pos.py`:
- Líneas 163–191: Se calcula `total_amount`.
- Líneas 197–225: Se valida la disponibilidad de inventario y se descuentan atómicamente las existencias (`UPDATE inventory SET stock = stock - ? ...`).
- Línea 227: Se calcula `change_returned`.
- Si la verificación de pago se realiza en la línea 227, el sistema ya habría modificado el inventario y tomado locks en SQLite, requiriendo un `conn.rollback()` para deshacer la mutación innecesaria. Validar el efectivo recibido inmediatamente después de conocer `total_amount` (línea 192) evita cualquier interacción destructiva con el inventario.

### Obs 1.5: Manejo de Moneda Colombiana (COP) y Aritmética Entera
- En Colombia, el peso (COP) no maneja centavos en transacciones comerciales físicas ni retail. La denominación mínima es $50 o $100 COP; los billetes estándar son $2.000, $5.000, $10.000, $20.000, $50.000 y $100.000.
- Esquema de base de datos (`app/database.py`):
  - `products.price`: `INTEGER NOT NULL`
  - `products.cost`: `INTEGER DEFAULT 0`
  - `sales.total_amount`: `INTEGER NOT NULL`
  - `sales.cash_received`: `INTEGER DEFAULT 0`
  - `sales.change_returned`: `INTEGER DEFAULT 0`
  - `sale_items.unit_price`: `INTEGER NOT NULL`
  - `sale_items.subtotal`: `INTEGER NOT NULL`
- En Pydantic v2:
  - Un valor flotante como `50000.0` se coacciona limpiamente a entero `50000`.
  - Un valor con fracción decimal como `50000.5` es rechazado con error de validación de tipo `int_from_float` (HTTP 422).
  - Al utilizar enteros puros para precios, cantidades, totales y vueltas, no existen problemas de precisión de punto flotante IEEE 754 (ej. `0.1 + 0.2 != 0.3`).

### Obs 1.6: Estado de la Suite de Pruebas Actual
- Ejecución de `pytest` (Task id `task-64`):
  `112 passed, 3 warnings in 17.52s`.
- El test existente `tests/test_tier2_boundaries.py::test_non_negative_change_floor` (líneas 132–143) contiene:
  ```python
  res = client.post("/api/pos/checkout", json={
      "items": [{"product_id": prod_id, "quantity": 1}],
      "payment_method": "efectivo",
      "cash_received": 5000
  })
  if res.status_code == 200:
      assert res.json()["change_returned"] >= 0
  ```
  Este test fue diseñado de manera condicional (`if res.status_code == 200:`), por lo que al rechazar con HTTP 400 el test continúa pasando sin romperse.
- Todos los demás tests de checkout en la suite envían efectivo exacto o superior, o pagos digitales con `cash_received: 0`.

---

## 2. Logic Chain

### Paso 2.1: Validación Temprana de Métodos de Pago
- **De Obs 1.1 y 1.2:** Los únicos métodos de pago autorizados en el sistema son `'efectivo'`, `'nequi_daviplata'` y `'datafono'`.
- Si se valida `payment_method` al inicio de `process_checkout` (antes de llamar a `get_db_connection()`):
  1. Si `payment_method` no está en la lista blanca, se rechaza inmediatamente con `HTTPException(status_code=400, detail="Método de pago no válido: '...'. Métodos permitidos: efectivo, nequi_daviplata, datafono.")`.
  2. Se ahorran conexiones y transacciones en SQLite.
  3. Se garantiza que `sales.payment_method` nunca contenga valores que descompongan `totals_dict` en `app/routers/cash.py`.

### Paso 2.2: Rechazo Estricto de Subpago en Efectivo
- **De Obs 1.3:** La lógica actual en línea 227 (`max(0, cash_received - total_amount)`) permite que un usuario pague menos de la cuenta sin error.
- La regla de negocio estipula que en pagos en efectivo:
  `cash_received >= total_amount`.
- Si `payload.cash_received is None` o `payload.cash_received < total_amount`, la transacción debe fallar de inmediato con:
  `HTTPException(status_code=400, detail="Monto en efectivo insuficiente para cubrir el total de la orden.")`.
- **De Obs 1.4:** Esta validación debe ocurrir en la línea 192, justo después de calcular `total_amount` y validar `total_amount > 0`, **ANTES** de ejecutar cualquier query a `inventory` o aplicar descuentos con `UPDATE inventory`. De esta forma:
  - Si no hay efectivo suficiente, no se toca el inventario físico ni vitrina.
  - No se generan rollbacks de base de datos ni escrituras espurias.

### Paso 2.3: Cálculo Exacto de Vueltas / Cambio
- **De Obs 1.3 y Paso 2.2:** Una vez garantizado que `payload.cash_received >= total_amount` para pagos en efectivo:
  `change_returned = payload.cash_received - total_amount`
  Garantiza un resultado exacto, entero y siempre `>= 0`.
- Para pagos no en efectivo (`nequi_daviplata`, `datafono`):
  `change_returned = 0` (no se entrega dinero físico de la caja registradora en pagos electrónicos).
- Fórmula unificada:
  ```python
  change_returned = (payload.cash_received - total_amount) if payment_method == "efectivo" else 0
  ```

### Paso 2.4: Integridad de la Moneda COP (Aritmética Entera)
- **De Obs 1.5:** Todas las operaciones monetarias en el backend se realizan con `int`.
- `total_amount` es la sumatoria de enteros (`price * quantity`).
- `cash_received` es entero.
- `change_returned` es entero.
- No hay divisiones ni porcentajes en el cálculo de checkout, eliminando toda posibilidad de error de redondeo de coma flotante.
- En la base de datos, `sales.cash_received` y `sales.change_returned` se persisten como enteros.

### Paso 2.5: Compatibilidad de Alias
- **De Obs 1.1:** Establecer en `app/routers/pos.py`:
  ```python
  CheckoutPayload = CheckoutRequest
  ```
  Evita inconsistencias si otros módulos o pruebas importan `CheckoutPayload`.

---

## 3. Caveats

1. **Persistencia de `cash_received` en Pagos Digitales:**
   En el frontend (`pos.js`), cuando se envía `nequi_daviplata` o `datafono`, a veces se pasa `cash_received = total` o `0`. En la base de datos, se debe guardar `payload.cash_received if payment_method == 'efectivo' else (payload.cash_received or 0)` para no romper pruebas existentes que validan que `cash_received` sea 0 en digital o que refleje el valor enviado.
2. **Normalización de Cadenas en Métodos de Pago:**
   Si un cliente o tablet envía `"EFECTIVO"` o `" efectivo "`, aplicar `.strip().lower()` permite normalizar limpiamente a `"efectivo"`. Sin embargo, métodos desconocidos como `"tarjeta"` o `"fiado"` deben ser rechazados sin excepción con HTTP 400.
3. **Pydantic Validation vs HTTP 400:**
   Si la validación de `payment_method` se hiciera exclusivamente con `Literal['efectivo', 'nequi_daviplata', 'datafono']` en Pydantic, FastAPI devolvería **HTTP 422 (Unprocessable Entity)** en lugar de **HTTP 400 (Bad Request)**. Dado que los criterios de aceptación y las pruebas exigen **HTTP 400**, la validación explícita con `raise HTTPException(status_code=400, ...)` en la función del router es la solución técnica adecuada.

---

## 4. Conclusion

Se ha formulado la estrategia exacta para implementar la validación de pagos en `app/routers/pos.py`. Las modificaciones requeridas son localizadas, limpias y libres de efectos secundarios:

### Propuesta de Código Concreto para el Implementador

#### A. En `app/routers/pos.py` (Línea 15–20): Alias de esquema
```python
class CheckoutRequest(BaseModel):
    items: List[CartItem]
    payment_method: str  # 'efectivo', 'nequi_daviplata', 'datafono'
    cash_received: Optional[int] = 0
    notes: Optional[str] = None

CheckoutPayload = CheckoutRequest
```

#### B. En `process_checkout` (Línea 145): Validación estricta de `payment_method`
```python
    # Whitelist de métodos de pago autorizados
    VALID_PAYMENT_METHODS = {"efectivo", "nequi_daviplata", "datafono"}
    raw_method = payload.payment_method.strip().lower() if payload.payment_method else ""
    if raw_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Método de pago no válido: '{payload.payment_method}'. Métodos permitidos: efectivo, nequi_daviplata, datafono."
        )
    payment_method = raw_method
```

#### C. En `process_checkout` (Línea 192): Validación de subpago antes de tocar inventario
```python
        if total_amount <= 0:
            raise HTTPException(status_code=400, detail="El total de la orden debe ser mayor a 0 COP.")

        # Validación estricta de efectivo recibido contra el total de la orden
        if payment_method == "efectivo":
            if payload.cash_received is None or payload.cash_received < total_amount:
                raise HTTPException(
                    status_code=400,
                    detail="Monto en efectivo insuficiente para cubrir el total de la orden."
                )
```

#### D. En `process_checkout` (Líneas 227–238): Cálculo exacto de vueltas y persistencia
```python
        # Cálculo exacto de vueltas: cash_received - total_amount para efectivo, 0 para digital
        change_returned = (payload.cash_received - total_amount) if payment_method == "efectivo" else 0
        saved_cash_received = payload.cash_received if payment_method == "efectivo" else (payload.cash_received or 0)

        # Guardar Venta
        cursor.execute("""
            INSERT INTO sales (
                sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, 
                total_amount, payment_method, cash_received, change_returned, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completada')
        """, (
            sale_code, now.isoformat(), date_str, time_str, hour_of_day, day_of_week,
            total_amount, payment_method, saved_cash_received, change_returned, payload.notes
        ))
```

#### E. En `process_checkout` (Líneas 255–265): Retorno
```python
        return {
            "success": True,
            "sale_id": sale_id,
            "sale_code": sale_code,
            "total_amount": total_amount,
            "cash_received": saved_cash_received,
            "change_returned": change_returned,
            "payment_method": payment_method,
            "timestamp": now.isoformat(),
            "time_str": time_str
        }
```

---

## 5. Verification Method

Para verificar independientemente esta implementación una vez aplicada:

### 1. Ejecución de la Suite Completa
Verificar que ningún flujo existente se degrade:
```powershell
pytest
```
*Condición de éxito:* 112+ tests en estado `PASSED`, 0 errores.

### 2. Nuevos Casos de Prueba Unitarios y de Frontera recomendados para M2
Crear o añadir los siguientes tests en `tests/test_milestone_m2_payments.py`:
1. **Subpago en efectivo:**
   ```python
   def test_cash_underpayment_rejected(client, helpers):
       prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
       res = client.post("/api/pos/checkout", json={
           "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
           "payment_method": "efectivo",
           "cash_received": 10000
       })
       assert res.status_code == 400
       assert res.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."
   ```
2. **Efectivo cero o nulo:**
   ```python
   def test_cash_zero_or_null_rejected(client, helpers):
       prod_id = helpers.get_product_id("POL-PEC") # 9,000 COP
       res_zero = client.post("/api/pos/checkout", json={
           "items": [{"product_id": prod_id, "quantity": 1}],
           "payment_method": "efectivo",
           "cash_received": 0
       })
       assert res_zero.status_code == 400
       assert res_zero.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."
   ```
3. **Método de pago no autorizado:**
   ```python
   def test_unsupported_payment_method_rejected(client, helpers):
       prod_id = helpers.get_product_id("POL-PEC")
       res = client.post("/api/pos/checkout", json={
           "items": [{"product_id": prod_id, "quantity": 1}],
           "payment_method": "bitcoin",
           "cash_received": 50000
       })
       assert res.status_code == 400
       assert "no válido" in res.json()["detail"] or "no soportado" in res.json()["detail"]
   ```
4. **Cálculo exacto de vueltas:**
   ```python
   def test_exact_change_cash_and_digital(client, helpers):
       prod_id = helpers.get_product_id("POL-14") # 13,000 COP
       # Efectivo con billete de 20,000 -> 7,000 de cambio
       res_cash = client.post("/api/pos/checkout", json={
           "items": [{"product_id": prod_id, "quantity": 1}],
           "payment_method": "efectivo",
           "cash_received": 20000
       })
       assert res_cash.status_code == 200
       assert res_cash.json()["change_returned"] == 7000

       # Pago digital -> cambio siempre 0
       res_dig = client.post("/api/pos/checkout", json={
           "items": [{"product_id": prod_id, "quantity": 1}],
           "payment_method": "nequi_daviplata",
           "cash_received": 20000
       })
       assert res_dig.status_code == 200
       assert res_dig.json()["change_returned"] == 0
   ```

### 3. Condiciones de Invalidación
La implementación se considerará inválida si:
- Permite que una venta en efectivo se registre con `cash_received < total_amount`.
- El mensaje de error devuelto ante subpago difiere de `"Monto en efectivo insuficiente para cubrir el total de la orden."`.
- Acepta métodos de pago fuera de `'efectivo'`, `'nequi_daviplata'` o `'datafono'`.
- Devuelve cambio mayor a 0 en transacciones de Nequi/Daviplata o Datáfono.
- Se produce cualquier error por coerción de tipo de coma flotante en los totales de la orden.
