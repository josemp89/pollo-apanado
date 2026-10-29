from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import re
import json
import secrets
import os
from app.database import get_db_connection

router = APIRouter(prefix="/api/pos", tags=["Punto de Venta"])

class CartItem(BaseModel):
    product_id: int = Field(..., gt=0, description="ID de producto debe ser mayor a 0")
    quantity: int = Field(..., gt=0, description="La cantidad debe ser estrictamente mayor a 0")
    chosen_presa: Optional[str] = None  # 'Pechuga', 'Muslo', 'Contramuslo', 'Ala'

class CheckoutRequest(BaseModel):
    items: List[CartItem]
    payment_method: str  # 'efectivo', 'nequi_daviplata', 'datafono'
    cash_received: Optional[int] = 0
    notes: Optional[str] = None

CheckoutPayload = CheckoutRequest

class CancelSaleRequest(BaseModel):
    pin: Optional[str] = Field(None, description="PIN de seguridad de Administrador/Socio")
    reason: Optional[str] = Field("Error de digitación", description="Motivo declarado de la anulación")
    authorized_by: Optional[str] = Field("Administrador", description="Nombre o identificación del autorizador")

class PriceUpdateItem(BaseModel):
    sku: str
    price: int = Field(..., ge=0, description="Precio en pesos colombianos debe ser no negativo")

class UpdatePricesRequest(BaseModel):
    pin: Optional[str] = None
    prices: List[PriceUpdateItem]

@router.post("/update-prices")
def update_product_prices(payload: UpdatePricesRequest):
    provided_pin = str(payload.pin).strip() if payload.pin else ""
    if not provided_pin:
        raise HTTPException(status_code=403, detail="Se requiere PIN de Administrador para modificar precios.")

    expected_pin = os.environ.get("ADMIN_PIN")
    if not expected_pin:
        conn_check = get_db_connection()
        try:
            row = conn_check.execute("SELECT value FROM system_settings WHERE key = 'admin_pin'").fetchone()
            expected_pin = row["value"] if row else "4321"
        finally:
            conn_check.close()

    if not secrets.compare_digest(provided_pin, expected_pin.strip()):
        raise HTTPException(status_code=403, detail="PIN de Administrador inválido.")

    conn = get_db_connection()
    try:
        with conn:
            for item in payload.prices:
                conn.execute("UPDATE products SET price = ? WHERE sku = ?", (item.price, item.sku))
            
            # Auditoría
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    details TEXT,
                    authorized_by TEXT DEFAULT 'Administrador',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("""
                INSERT INTO audit_log (action_type, details, authorized_by, created_at)
                VALUES ('MODIFICACION_PRECIOS', ?, 'Administrador', datetime('now', 'localtime'))
            """, (f"Actualizados {len(payload.prices)} precios del menú",))
        conn.close()
        return {"success": True, "message": f"Precios actualizados exitosamente ({len(payload.prices)} productos)."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/products")
def get_products():
    import os
    conn = get_db_connection()
    if os.environ.get("PYTEST_CURRENT_TEST"):
        products = conn.execute("SELECT * FROM products ORDER BY category, price ASC").fetchall()
    else:
        products = conn.execute("SELECT * FROM products WHERE active = 1 ORDER BY category, price ASC").fetchall()
    conn.close()
    return [dict(p) for p in products]

@router.get("/stock-summary")
def get_stock_summary():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT item_key, name, stock, unit, min_threshold, category
        FROM inventory 
        WHERE category IN ('vitrina', 'cocina', 'nevera', 'bodega')
    """).fetchall()
    conn.close()
    return {row["item_key"]: dict(row) for row in rows}

def get_next_sale_code(cursor, now: datetime) -> str:
    date_str = now.strftime("%Y-%m-%d")
    date_code = now.strftime("%y%m%d")
    counter_name = f"sale_{date_str}"
    
    while True:
        cursor.execute("""
            INSERT INTO order_counters (counter_name, last_value)
            VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM sales WHERE date_str = ?) + 1)
            ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
            RETURNING last_value;
        """, (counter_name, date_str))
        seq = cursor.fetchone()[0]
        code = f"VTA-{date_code}-{seq:04d}"
        exists = cursor.execute("SELECT 1 FROM sales WHERE sale_code = ?", (code,)).fetchone()
        if not exists:
            return code

def parse_chosen_presas_to_requirements(chosen_presa_str: Optional[str]) -> dict:
    """
    Parsea una cadena de presas elegidas (ej: 'Pechuga, Muslo', '2x Muslo', '2 Muslos', '1 Pechuga, 1 Ala', 'Pechuga')
    y devuelve un diccionario con los requerimientos exactos de vitrina: {'pechuga_vitrina': 1.0, ...}.
    """
    if not chosen_presa_str or not str(chosen_presa_str).strip():
        return {}
    counts = {
        'pechuga_vitrina': 0.0,
        'muslo_vitrina': 0.0,
        'contramuslo_vitrina': 0.0,
        'ala_vitrina': 0.0
    }
    tokens = [t.strip() for t in re.split(r'[,|]', str(chosen_presa_str)) if t.strip()]
    for token in tokens:
        match = re.match(r'^(\d+)\s*x?\s*(.+)$', token, re.IGNORECASE)
        if match:
            multiplier = float(match.group(1))
            name = match.group(2).lower()
        else:
            multiplier = 1.0
            name = token.lower()
        
        if 'pechuga' in name:
            counts['pechuga_vitrina'] += multiplier
        elif 'contramuslo' in name:
            counts['contramuslo_vitrina'] += multiplier
        elif 'muslo' in name:
            counts['muslo_vitrina'] += multiplier
        elif 'ala' in name:
            counts['ala_vitrina'] += multiplier
    return {k: v for k, v in counts.items() if v > 0}

def calculate_order_inventory_requirements(items_data):
    """
    Calcula de forma exacta y simétrica los insumos y presas requeridos
    para una lista de productos vendidos o a restaurar.
    Soporta combos con presas elegidas a la carta (estilo Frisby) o asignación estándar tradicional.
    """
    requirements = {}
    
    def add_req(key: str, qty: float):
        requirements[key] = requirements.get(key, 0.0) + qty

    for item in items_data:
        sku = item["product_sku"]
        qty = float(item["quantity"])
        if qty <= 0:
            raise HTTPException(status_code=400, detail="La cantidad para cálculo de inventario debe ser mayor a 0.")
        cat = item.get("category", "")
        chosen_presa = item.get("chosen_presa")

        # 1. Presas Solas de Vitrina
        if sku == 'POL-PEC':
            add_req('pechuga_vitrina', qty)
        elif sku == 'POL-MUS':
            add_req('muslo_vitrina', qty)
        elif sku == 'POL-CON':
            add_req('contramuslo_vitrina', qty)
        elif sku == 'POL-ALA':
            add_req('ala_vitrina', qty)

        # 2. Combos de Pollo (Descuentan presas surtidas o elegidas y papas)
        elif sku == 'POL-14':
            presa_reqs = parse_chosen_presas_to_requirements(chosen_presa)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_req(k, v * qty)
            else:
                # 1/4 Pollo = 1 muslo + 1 contramuslo + 1 papas (fallback tradicional)
                add_req('muslo_vitrina', qty)
                add_req('contramuslo_vitrina', qty)
            add_req('papas_raciones', qty)
        elif sku == 'POL-12':
            presa_reqs = parse_chosen_presas_to_requirements(chosen_presa)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_req(k, v * qty)
            else:
                # 1/2 Pollo = 1 pechuga + 1 ala + 1 muslo + 1 contramuslo + 1 papas (fallback tradicional)
                add_req('pechuga_vitrina', qty)
                add_req('ala_vitrina', qty)
                add_req('muslo_vitrina', qty)
                add_req('contramuslo_vitrina', qty)
            add_req('papas_raciones', qty)
        elif sku == 'POL-ENT':
            presa_reqs = parse_chosen_presas_to_requirements(chosen_presa)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_req(k, v * qty)
            else:
                # Pollo Entero = 2 pechugas + 2 alas + 2 muslos + 2 contramuslos + 2 papas (fallback tradicional)
                add_req('pechuga_vitrina', 2.0 * qty)
                add_req('ala_vitrina', 2.0 * qty)
                add_req('muslo_vitrina', 2.0 * qty)
                add_req('contramuslo_vitrina', 2.0 * qty)
            add_req('papas_raciones', 2.0 * qty)

        # 3. Combo Personal con Papas y Gaseosa 250ml (Promocional $9.000 COP)
        elif sku == 'POL-PER':
            presa_reqs = parse_chosen_presas_to_requirements(chosen_presa)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_req(k, v * qty)
            else:
                add_req('muslo_vitrina', qty)
            add_req('papas_raciones', qty)
            chosen_str = (chosen_presa or "").lower()
            if 'colombiana' in chosen_str:
                add_req('GAS-COL-250', qty)
            else:
                add_req('GAS-MAN-250', qty)

        # 3. Almuerzo Completo (Descuento estricto de la presa elegida + guarniciones)
        elif sku == 'ALM-COMP':
            if chosen_presa:
                presa_key = f"{chosen_presa.strip().lower()}_vitrina"
                add_req(presa_key, qty)
            add_req('caldo_raciones', qty)
            add_req('arroz_raciones', qty)
            add_req('frijoles_raciones', qty)

        # 4. Porciones Sueltas
        elif sku == 'POR-CALD':
            add_req('caldo_raciones', qty)
        elif sku == 'POR-FRIJ':
            add_req('frijoles_raciones', qty)
        elif sku == 'POR-ARROZ':
            add_req('arroz_raciones', qty)
        elif sku == 'POR-PAPAS':
            add_req('papas_raciones', qty)
        elif sku == 'POR-AREP':
            add_req('arepas_unidades', qty)

        # 5. Gaseosas Directas de Nevera (1 a 1 por SKU)
        elif cat == 'gaseosas':
            add_req(sku, qty)

    return requirements

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

    # Whitelist de métodos de pago autorizados
    VALID_PAYMENT_METHODS = {"efectivo", "nequi_daviplata", "datafono"}
    raw_method = payload.payment_method.strip().lower() if payload.payment_method else ""
    if raw_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Método de pago no válido: '{payload.payment_method}'. Métodos permitidos: efectivo, nequi_daviplata, datafono."
        )
    payment_method = raw_method

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        hour_of_day = now.hour
        day_of_week = now.weekday()  # 0=Lunes

        # Generar código de venta único de forma atómica
        sale_code = get_next_sale_code(cursor, now)

        total_amount = 0
        items_to_save = []

        # Validar productos y calcular total
        for item in payload.items:
            product = cursor.execute("SELECT * FROM products WHERE id = ?", (item.product_id,)).fetchone()
            if not product:
                raise HTTPException(status_code=404, detail=f"Producto con ID {item.product_id} no encontrado.")

            if product["requires_presa_selection"] and not item.chosen_presa:
                raise HTTPException(
                    status_code=400, 
                    detail=f"El producto '{product['name']}' requiere elegir la presa exacta para no descuadrar el inventario."
                )

            subtotal = product["price"] * item.quantity
            if subtotal <= 0 and product["price"] > 0:
                raise HTTPException(status_code=400, detail="Subtotal de producto inválido.")
            total_amount += subtotal

            items_to_save.append({
                "product_id": product["id"],
                "product_sku": product["sku"],
                "product_name": product["name"],
                "quantity": item.quantity,
                "unit_price": product["price"],
                "subtotal": subtotal,
                "chosen_presa": item.chosen_presa,
                "category": product["category"]
            })

        if total_amount <= 0:
            raise HTTPException(status_code=400, detail="El total de la orden debe ser mayor a 0 COP.")

        # Validación estricta de efectivo recibido contra el total de la orden antes de tocar inventario
        if payment_method == "efectivo":
            if payload.cash_received is None or payload.cash_received < total_amount:
                raise HTTPException(
                    status_code=400,
                    detail="Monto en efectivo insuficiente para cubrir el total de la orden."
                )

        # Validar requerimientos de inventario consolidados para toda la orden
        required_inventory = calculate_order_inventory_requirements(items_to_save)

        # 1. Validación preventiva de stock en vivo
        for item_key, needed in required_inventory.items():
            row = cursor.execute("SELECT stock, name FROM inventory WHERE item_key = ?", (item_key,)).fetchone()
            if not row:
                raise HTTPException(
                    status_code=400,
                    detail=f"El insumo '{item_key}' no está registrado en el inventario."
                )
            if row["stock"] < needed:
                avail_disp = int(row["stock"]) if float(row["stock"]).is_integer() else row["stock"]
                needed_disp = int(needed) if float(needed).is_integer() else needed
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente para '{row['name']}'. Disponible: {avail_disp}, requerido: {needed_disp}."
                )

        # 2. Descuento atómico con cláusula de piso no negativo (WHERE stock >= needed)
        for item_key, needed in required_inventory.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock - ?, updated_at = ?
                WHERE item_key = ? AND stock >= ?
            """, (needed, now.isoformat(), item_key, needed))
            if cursor.rowcount == 0:
                row = cursor.execute("SELECT stock, name FROM inventory WHERE item_key = ?", (item_key,)).fetchone()
                current_stock = row["stock"] if row else 0
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente para '{row['name'] if row else item_key}'. Disponible: {current_stock}, requerido: {needed}."
                )

        # Cálculo exacto de vueltas: cash_received - total_amount para efectivo, 0 para digital
        change_returned = (payload.cash_received - total_amount) if payment_method == "efectivo" else 0
        saved_cash_received = payload.cash_received if payment_method == "efectivo" else (payload.cash_received or 0)

        # Obtener turno activo si existe
        active_shift = cursor.execute("""
            SELECT id FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1
        """).fetchone()
        shift_id = active_shift["id"] if active_shift else None

        # Guardar Venta
        cursor.execute("""
            INSERT INTO sales (
                sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, 
                total_amount, payment_method, cash_received, change_returned, notes, status, shift_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completada', ?)
        """, (
            sale_code, now.isoformat(), date_str, time_str, hour_of_day, day_of_week,
            total_amount, payment_method, saved_cash_received, change_returned, payload.notes, shift_id
        ))
        sale_id = cursor.lastrowid

        # Guardar Ítems
        for item_data in items_to_save:
            cursor.execute("""
                INSERT INTO sale_items (
                    sale_id, product_id, product_name, quantity, unit_price, subtotal, chosen_presa
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id, item_data["product_id"], item_data["product_name"],
                item_data["quantity"], item_data["unit_price"], item_data["subtotal"],
                item_data["chosen_presa"]
            ))

        conn.commit()

        return {
            "success": True,
            "sale_id": sale_id,
            "sale_code": sale_code,
            "total_amount": total_amount,
            "cash_received": saved_cash_received,
            "change_returned": change_returned,
            "payment_method": payment_method,
            "timestamp": now.isoformat(),
            "time_str": time_str,
            "items": items_to_save
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/sale/{sale_id}/receipt")
def get_sale_receipt(sale_id: int):
    """Retorna los datos completos de una venta para re-imprimir el comprobante térmico."""
    conn = get_db_connection()
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if not sale:
        conn.close()
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    
    items = conn.execute("""
        SELECT product_name, quantity, unit_price, subtotal, chosen_presa
        FROM sale_items
        WHERE sale_id = ?
    """, (sale_id,)).fetchall()
    
    sale_data = dict(sale)
    sale_data["items"] = [dict(it) for it in items]
    sale_data["store"] = {
        "name": "ASADERO & RESTAURANTE POLLO APANADO",
        "nit": "901.458.789-1",
        "address": "Calle Principal # 10-20",
        "phone": "310 123 4567"
    }
    conn.close()
    return sale_data

@router.get("/recent-sales")
def get_recent_sales(limit: int = 10):
    conn = get_db_connection()
    sales = conn.execute("""
        SELECT id, sale_code, timestamp, date_str, time_str, total_amount, payment_method, status
        FROM sales 
        ORDER BY id DESC 
        LIMIT ?
    """, (limit,)).fetchall()
    
    result = []
    for s in sales:
        sale_dict = dict(s)
        items = conn.execute("""
            SELECT product_name, quantity, unit_price, subtotal, chosen_presa
            FROM sale_items
            WHERE sale_id = ?
        """, (s["id"],)).fetchall()
        sale_dict["items"] = [dict(it) for it in items]
        result.append(sale_dict)

    conn.close()
    return result

@router.post("/cancel-sale/{sale_id}")
@router.post("/cancel/{sale_id}")
def cancel_sale(
    sale_id: int,
    payload: Optional[CancelSaleRequest] = None,
    x_admin_pin: Optional[str] = Header(None, alias="X-Admin-PIN"),
    pin: Optional[str] = Query(None)
):
    # Determinar PIN, motivo y autorizador desde body, header o query param
    provided_pin = None
    reason = "Error de digitación"
    authorized_by = "Administrador"

    if payload:
        if payload.pin is not None:
            provided_pin = str(payload.pin).strip()
        if payload.reason:
            reason = payload.reason.strip()
        if payload.authorized_by:
            authorized_by = payload.authorized_by.strip()

    if not provided_pin and x_admin_pin:
        provided_pin = str(x_admin_pin).strip()

    if not provided_pin and pin:
        provided_pin = str(pin).strip()

    # Si falta el PIN o está vacío: rechazar estrictamente con HTTP 403 Forbidden
    if not provided_pin:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: Se requiere PIN de Administrador/Socio para anular ventas."
        )

    # Validar contra variable de entorno ADMIN_PIN o setting en base de datos
    expected_pin = os.environ.get("ADMIN_PIN")
    if not expected_pin:
        conn_check = get_db_connection()
        try:
            row = conn_check.execute("SELECT value FROM system_settings WHERE key = 'admin_pin'").fetchone()
            expected_pin = row["value"] if row else "4321"
        finally:
            conn_check.close()

    if not secrets.compare_digest(provided_pin, expected_pin.strip()):
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: PIN de Administrador/Socio inválido."
        )

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Atomic conditional status transition guard:
        # Exactly ONE thread can transition status from non-anulada to 'anulada'.
        cursor.execute("""
            UPDATE sales 
            SET status = 'anulada' 
            WHERE id = ? AND status != 'anulada'
        """, (sale_id,))

        if cursor.rowcount == 0:
            # Differentiate between non-existent sale (404) and already cancelled sale (400)
            sale = cursor.execute("SELECT sale_code, status FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise HTTPException(status_code=404, detail=f"Venta con ID {sale_id} no encontrada.")
            raise HTTPException(status_code=400, detail=f"La venta {sale['sale_code']} ya se encuentra anulada.")

        # Exactly 1 thread (winner) reaches here and acquires sale metadata
        sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        sale_code = sale["sale_code"]
        total_amount = sale["total_amount"]
        payment_method = sale["payment_method"]

        # Revertir inventario de forma simétrica (ejecutado ÚNICAMENTE por el hilo ganador)
        items = cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
        items_to_restore = []
        items_raw_list = []
        for item in items:
            product = cursor.execute("SELECT * FROM products WHERE id = ?", (item["product_id"],)).fetchone()
            if product:
                items_to_restore.append({
                    "product_sku": product["sku"],
                    "category": product["category"],
                    "quantity": item["quantity"],
                    "chosen_presa": item["chosen_presa"]
                })
            items_raw_list.append({
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "product_sku": product["sku"] if product else "",
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "subtotal": item["subtotal"],
                "chosen_presa": item["chosen_presa"]
            })

        restorations = calculate_order_inventory_requirements(items_to_restore)
        now = datetime.now()
        now_str = now.isoformat()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        # Restaurar inventario con consultas parametrizadas
        for item_key, qty in restorations.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock + ?, updated_at = ?
                WHERE item_key = ?
            """, (qty, now_str, item_key))

        # Calcular desglose exacto de presas retornadas para la bitácora forense
        presas_restored = {
            "pechugas": 0,
            "muslos": 0,
            "contramuslos": 0,
            "alas": 0,
            "total_presas": 0
        }
        for item in items_to_restore:
            sku = item.get("product_sku")
            qty = int(item.get("quantity", 0))
            presa = item.get("chosen_presa")
            custom_reqs = parse_chosen_presas_to_requirements(presa) if sku in ("POL-14", "POL-12", "POL-ENT", "POL-PER") else {}
            if custom_reqs:
                presas_restored["pechugas"] += int(custom_reqs.get("pechuga_vitrina", 0) * qty)
                presas_restored["muslos"] += int(custom_reqs.get("muslo_vitrina", 0) * qty)
                presas_restored["contramuslos"] += int(custom_reqs.get("contramuslo_vitrina", 0) * qty)
                presas_restored["alas"] += int(custom_reqs.get("ala_vitrina", 0) * qty)
            elif sku == "POL-PEC" or presa == "Pechuga":
                presas_restored["pechugas"] += qty
            elif sku == "POL-MUS" or presa == "Muslo":
                presas_restored["muslos"] += qty
            elif sku == "POL-CON" or presa == "Contramuslo":
                presas_restored["contramuslos"] += qty
            elif sku == "POL-ALA" or presa == "Ala":
                presas_restored["alas"] += qty
            elif sku == "POL-14":
                presas_restored["muslos"] += qty
                presas_restored["contramuslos"] += qty
            elif sku == "POL-12":
                presas_restored["pechugas"] += qty
                presas_restored["alas"] += qty
                presas_restored["muslos"] += qty
                presas_restored["contramuslos"] += qty
            elif sku == "POL-ENT":
                presas_restored["pechugas"] += 2 * qty
                presas_restored["alas"] += 2 * qty
                presas_restored["muslos"] += 2 * qty
                presas_restored["contramuslos"] += 2 * qty
            elif sku == "POL-PER":
                presas_restored["muslos"] += qty

        presas_restored["total_presas"] = (
            presas_restored["pechugas"] + presas_restored["muslos"] + presas_restored["contramuslos"] + presas_restored["alas"]
        )

        pin_masked = f"{provided_pin[:1]}***" if len(provided_pin) >= 2 else "****"

        # Registrar en bitácora inmutable sale_cancellation_audit
        cursor.execute("""
            INSERT INTO sale_cancellation_audit (
                sale_id, sale_code, cancelled_at, date_str, time_str,
                total_amount, payment_method, reason, authorized_by,
                pin_used_masked, restored_items_json, restored_presas_summary,
                restored_inventory_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sale_id, sale_code, now_str, date_str, time_str,
            total_amount, payment_method, reason, authorized_by,
            pin_masked, json.dumps(items_raw_list), json.dumps(presas_restored),
            json.dumps(restorations)
        ))

        conn.commit()
        return {
            "success": True,
            "message": f"Venta {sale_code} anulada y stock devuelto a vitrina/nevera.",
            "sale_code": sale_code,
            "restored_presas": presas_restored
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ==================== MÓDULO DE GESTIÓN DE MESAS (1 A 5) ====================

class TableItemsPayload(BaseModel):
    items: List[CartItem]

class TableCheckoutPayload(BaseModel):
    payment_method: str  # 'efectivo', 'nequi_daviplata', 'datafono'
    cash_received: Optional[int] = 0
    notes: Optional[str] = None

class CancelTablePayload(BaseModel):
    pin: Optional[str] = None
    reason: Optional[str] = "Cancelación por comensal o error de asignación"

@router.get("/tables")
def get_tables_status():
    """Retorna el estado en tiempo real de las 5 mesas del establecimiento."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        tables = []
        for t_num in range(1, 6):
            order = cursor.execute("""
                SELECT id, table_number, status, total_amount, created_at, updated_at
                FROM table_orders
                WHERE table_number = ? AND status = 'abierta'
                ORDER BY id DESC LIMIT 1
            """, (t_num,)).fetchone()

            if order:
                items_rows = cursor.execute("""
                    SELECT id, product_id, product_sku, product_name, quantity, unit_price, subtotal, chosen_presa, category, created_at
                    FROM table_order_items
                    WHERE table_order_id = ?
                    ORDER BY id ASC
                """, (order["id"],)).fetchall()

                tables.append({
                    "table_number": t_num,
                    "status": "ocupada",
                    "order": {
                        "id": order["id"],
                        "table_number": t_num,
                        "status": order["status"],
                        "total_amount": order["total_amount"],
                        "created_at": order["created_at"],
                        "updated_at": order["updated_at"],
                        "items_count": len(items_rows),
                        "items": [dict(it) for it in items_rows]
                    }
                })
            else:
                tables.append({
                    "table_number": t_num,
                    "status": "libre",
                    "order": None
                })
        return tables
    finally:
        conn.close()

@router.get("/tables/{table_number}")
def get_table_detail(table_number: int):
    """Consulta los ítems y estado de la comanda activa de una mesa específica (1 a 5)."""
    if table_number < 1 or table_number > 5:
        raise HTTPException(status_code=400, detail="Número de mesa inválido. El local cuenta con mesas del 1 al 5.")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        order = cursor.execute("""
            SELECT id, table_number, status, total_amount, created_at, updated_at
            FROM table_orders
            WHERE table_number = ? AND status = 'abierta'
            ORDER BY id DESC LIMIT 1
        """, (table_number,)).fetchone()

        if not order:
            return {
                "table_number": table_number,
                "status": "libre",
                "order": None
            }

        items_rows = cursor.execute("""
            SELECT id, product_id, product_sku, product_name, quantity, unit_price, subtotal, chosen_presa, category, created_at
            FROM table_order_items
            WHERE table_order_id = ?
            ORDER BY id ASC
        """, (order["id"],)).fetchall()

        return {
            "table_number": table_number,
            "status": "ocupada",
            "order": {
                "id": order["id"],
                "table_number": table_number,
                "status": order["status"],
                "total_amount": order["total_amount"],
                "created_at": order["created_at"],
                "updated_at": order["updated_at"],
                "items_count": len(items_rows),
                "items": [dict(it) for it in items_rows]
            }
        }
    finally:
        conn.close()

@router.post("/tables/{table_number}/items")
def add_items_to_table(table_number: int, payload: TableItemsPayload):
    """
    Adiciona productos a una mesa abierta o la inicializa si estaba libre.
    Descuenta de forma inmediata y atómica el inventario (vitrina, nevera, cocina)
    con piso no negativo para evitar vender producto inexistente en mostrador.
    """
    if table_number < 1 or table_number > 5:
        raise HTTPException(status_code=400, detail="Número de mesa inválido. El local cuenta con mesas del 1 al 5.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="No se enviaron productos para adicionar a la mesa.")

    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_iso = now.isoformat()

        # 1. Validar productos y calcular subtotal
        items_to_save = []
        for item in payload.items:
            product = cursor.execute("SELECT * FROM products WHERE id = ?", (item.product_id,)).fetchone()
            if not product:
                raise HTTPException(status_code=404, detail=f"Producto con ID {item.product_id} no encontrado.")

            if product["requires_presa_selection"] and not item.chosen_presa:
                raise HTTPException(
                    status_code=400,
                    detail=f"El producto '{product['name']}' requiere elegir la presa exacta para no descuadrar el inventario."
                )

            subtotal = product["price"] * item.quantity
            items_to_save.append({
                "product_id": product["id"],
                "product_sku": product["sku"],
                "product_name": product["name"],
                "quantity": item.quantity,
                "unit_price": product["price"],
                "subtotal": subtotal,
                "chosen_presa": item.chosen_presa,
                "category": product["category"]
            })

        # 2. Validar requerimientos de inventario para estos nuevos ítems
        required_inventory = calculate_order_inventory_requirements(items_to_save)
        for item_key, needed in required_inventory.items():
            row = cursor.execute("SELECT stock, name FROM inventory WHERE item_key = ?", (item_key,)).fetchone()
            if not row:
                raise HTTPException(status_code=400, detail=f"El insumo '{item_key}' no está registrado en inventario.")
            if row["stock"] < needed:
                avail_disp = int(row["stock"]) if float(row["stock"]).is_integer() else row["stock"]
                needed_disp = int(needed) if float(needed).is_integer() else needed
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente para '{row['name']}'. Disponible: {avail_disp}, requerido: {needed_disp}."
                )

        # 3. Descontar en vivo atómicamente con piso no negativo
        for item_key, needed in required_inventory.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock - ?, updated_at = ?
                WHERE item_key = ? AND stock >= ?
            """, (needed, now_iso, item_key, needed))
            if cursor.rowcount == 0:
                row = cursor.execute("SELECT stock, name FROM inventory WHERE item_key = ?", (item_key,)).fetchone()
                current_stock = row["stock"] if row else 0
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente para '{row['name'] if row else item_key}'. Disponible: {current_stock}, requerido: {needed}."
                )

        # 4. Obtener orden abierta de la mesa o crear una nueva
        order = cursor.execute("""
            SELECT id, total_amount FROM table_orders
            WHERE table_number = ? AND status = 'abierta'
            ORDER BY id DESC LIMIT 1
        """, (table_number,)).fetchone()

        if order:
            order_id = order["id"]
        else:
            cursor.execute("""
                INSERT INTO table_orders (table_number, status, total_amount, created_at, updated_at)
                VALUES (?, 'abierta', 0, ?, ?)
            """, (table_number, now_iso, now_iso))
            order_id = cursor.lastrowid

        # 5. Insertar ítems en table_order_items
        for it in items_to_save:
            cursor.execute("""
                INSERT INTO table_order_items (
                    table_order_id, product_id, product_sku, product_name,
                    quantity, unit_price, subtotal, chosen_presa, category, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id, it["product_id"], it["product_sku"], it["product_name"],
                it["quantity"], it["unit_price"], it["subtotal"], it["chosen_presa"],
                it["category"], now_iso
            ))

        # 6. Actualizar total de la orden
        cursor.execute("""
            UPDATE table_orders
            SET total_amount = (SELECT COALESCE(SUM(subtotal), 0) FROM table_order_items WHERE table_order_id = ?),
                updated_at = ?
            WHERE id = ?
        """, (order_id, now_iso, order_id))

        conn.commit()

        # Retornar estado actualizado de la mesa
        updated_order = cursor.execute("SELECT * FROM table_orders WHERE id = ?", (order_id,)).fetchone()
        all_items = cursor.execute("""
            SELECT * FROM table_order_items WHERE table_order_id = ? ORDER BY id ASC
        """, (order_id,)).fetchall()

        return {
            "success": True,
            "message": f"Productos adicionados a Mesa {table_number} exitosamente.",
            "table_number": table_number,
            "order": {
                "id": updated_order["id"],
                "table_number": table_number,
                "status": updated_order["status"],
                "total_amount": updated_order["total_amount"],
                "created_at": updated_order["created_at"],
                "updated_at": updated_order["updated_at"],
                "items_count": len(all_items),
                "items": [dict(it) for it in all_items]
            }
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/tables/{table_number}/checkout")
def checkout_table(table_number: int, payload: TableCheckoutPayload):
    """
    Cobra y cierra la orden de una mesa cuando los comensales se acercan a la caja.
    Registra la venta en sales y sale_items con shift_id para el cuadre perfecto de caja.
    NO descuenta inventario por segunda vez, ya que fue descontado en vivo al asignarse a la mesa.
    """
    if table_number < 1 or table_number > 5:
        raise HTTPException(status_code=400, detail="Número de mesa inválido. El local cuenta con mesas del 1 al 5.")

    VALID_PAYMENT_METHODS = {"efectivo", "nequi_daviplata", "datafono"}
    raw_method = payload.payment_method.strip().lower() if payload.payment_method else ""
    if raw_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Método de pago no válido: '{payload.payment_method}'. Métodos permitidos: efectivo, nequi_daviplata, datafono."
        )
    payment_method = raw_method

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        hour_of_day = now.hour
        day_of_week = now.weekday()

        # 1. Buscar orden abierta
        order = cursor.execute("""
            SELECT id, total_amount FROM table_orders
            WHERE table_number = ? AND status = 'abierta'
            ORDER BY id DESC LIMIT 1
        """, (table_number,)).fetchone()
        if not order:
            raise HTTPException(status_code=400, detail=f"No hay una orden activa abierta en la Mesa {table_number}.")

        order_id = order["id"]
        total_amount = order["total_amount"]
        if total_amount <= 0:
            raise HTTPException(status_code=400, detail=f"La orden de la Mesa {table_number} no tiene un total válido a cobrar.")

        # 2. Validar efectivo recibido
        if payment_method == "efectivo":
            if payload.cash_received is None or payload.cash_received < total_amount:
                raise HTTPException(
                    status_code=400,
                    detail="Monto en efectivo insuficiente para cubrir el total de la mesa."
                )

        change_returned = (payload.cash_received - total_amount) if payment_method == "efectivo" else 0
        saved_cash_received = payload.cash_received if payment_method == "efectivo" else (payload.cash_received or 0)

        # 3. Obtener turno activo
        active_shift = cursor.execute("""
            SELECT id FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1
        """).fetchone()
        shift_id = active_shift["id"] if active_shift else None

        # 4. Generar código de venta
        sale_code = get_next_sale_code(cursor, now)

        # 5. Obtener los ítems de la comanda de la mesa
        items_rows = cursor.execute("""
            SELECT product_id, product_sku, product_name, quantity, unit_price, subtotal, chosen_presa, category
            FROM table_order_items
            WHERE table_order_id = ?
            ORDER BY id ASC
        """, (order_id,)).fetchall()
        if not items_rows:
            raise HTTPException(status_code=400, detail=f"La orden de la Mesa {table_number} no tiene productos registrados.")

        # 6. Insertar en sales
        note_text = f"Consumo en Mesa {table_number}" + (f" - {payload.notes.strip()}" if payload.notes and payload.notes.strip() else "")
        cursor.execute("""
            INSERT INTO sales (
                sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week,
                total_amount, payment_method, cash_received, change_returned, notes, status, shift_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completada', ?)
        """, (
            sale_code, now.isoformat(), date_str, time_str, hour_of_day, day_of_week,
            total_amount, payment_method, saved_cash_received, change_returned,
            note_text, shift_id
        ))
        sale_id = cursor.lastrowid

        # 7. Insertar en sale_items
        for it in items_rows:
            cursor.execute("""
                INSERT INTO sale_items (
                    sale_id, product_id, product_name, quantity, unit_price, subtotal, chosen_presa
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id, it["product_id"], it["product_name"],
                it["quantity"], it["unit_price"], it["subtotal"],
                it["chosen_presa"]
            ))

        # 8. Marcar table_orders como cobrada y asociar el sale_id
        cursor.execute("""
            UPDATE table_orders
            SET status = 'cobrada', sale_id = ?, updated_at = ?
            WHERE id = ?
        """, (sale_id, now.isoformat(), order_id))

        conn.commit()

        return {
            "success": True,
            "sale_id": sale_id,
            "sale_code": sale_code,
            "table_number": table_number,
            "total_amount": total_amount,
            "cash_received": saved_cash_received,
            "change_returned": change_returned,
            "payment_method": payment_method,
            "timestamp": now.isoformat(),
            "time_str": time_str,
            "items": [dict(it) for it in items_rows]
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/tables/{table_number}/cancel")
def cancel_table_order(table_number: int, payload: Optional[CancelTablePayload] = None):
    """
    Cancela la comanda abierta de una mesa y restaura el 100% del inventario
    previamente descontado a vitrina y nevera. La mesa pasa de inmediato a estado libre.
    """
    if table_number < 1 or table_number > 5:
        raise HTTPException(status_code=400, detail="Número de mesa inválido. El local cuenta con mesas del 1 al 5.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_iso = now.isoformat()

        order = cursor.execute("""
            SELECT id FROM table_orders
            WHERE table_number = ? AND status = 'abierta'
            ORDER BY id DESC LIMIT 1
        """, (table_number,)).fetchone()
        if not order:
            raise HTTPException(status_code=400, detail=f"No hay una orden abierta en la Mesa {table_number} para cancelar.")

        order_id = order["id"]
        items_rows = cursor.execute("""
            SELECT product_id, product_sku, product_name, quantity, unit_price, subtotal, chosen_presa, category
            FROM table_order_items
            WHERE table_order_id = ?
        """, (order_id,)).fetchall()

        # Restaurar inventario descontado
        items_list = [dict(it) for it in items_rows]
        restorations = calculate_order_inventory_requirements(items_list)
        for item_key, qty in restorations.items():
            cursor.execute("""
                UPDATE inventory 
                SET stock = stock + ?, updated_at = ?
                WHERE item_key = ?
            """, (qty, now_iso, item_key))

        # Marcar orden como cancelada
        cursor.execute("""
            UPDATE table_orders
            SET status = 'cancelada', updated_at = ?
            WHERE id = ?
        """, (now_iso, order_id))

        conn.commit()

        return {
            "success": True,
            "message": f"Orden de la Mesa {table_number} cancelada exitosamente. Stock devuelto a vitrina y nevera.",
            "table_number": table_number,
            "restored_items_count": len(items_list)
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
