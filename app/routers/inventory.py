import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.database import get_db_connection

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

# ==================== PYDANTIC MODELS ====================

class SupplierEntryRequest(BaseModel):
    supplier_name: str = Field(..., min_length=1, description="Nombre del proveedor")
    invoice_number: str = Field(..., min_length=1, description="Número de factura o remisión")
    item_name: str = Field(..., min_length=1, description="Nombre o clave del insumo")
    location: str = Field(..., min_length=1, description="Ubicación: Bodega, Nevera, Cocina, Vitrina")
    quantity: float = Field(..., gt=0, description="Cantidad recibida mayor a cero")
    unit_cost: Optional[float] = Field(0.0, ge=0)
    total_cost: Optional[float] = Field(0.0, ge=0)
    notes: Optional[str] = None

class InitialStockItem(BaseModel):
    item_name: Optional[str] = None
    item_key: Optional[str] = None
    location: Optional[str] = None
    quantity: Optional[float] = None
    initial_stock: Optional[float] = None

class SetInitialStockRequest(BaseModel):
    date: Optional[str] = None
    items: List[InitialStockItem]
    recorded_by: Optional[str] = "admin"

# ==================== HELPER FUNCTIONS ====================

def slugify(text: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '_', text.strip().lower())
    return cleaned.strip('_') or "item"

def get_next_reception_code(cursor, now: datetime) -> str:
    date_code = now.strftime("%y%m%d")
    date_str = now.strftime("%Y-%m-%d")
    counter_name = f"reception_{date_str}"
    cursor.execute("""
        INSERT INTO order_counters (counter_name, last_value)
        VALUES (?, 1)
        ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
        RETURNING last_value;
    """, (counter_name,))
    seq = cursor.fetchone()[0]
    return f"REC-{date_code}-{seq:04d}"

# ==================== ENDPOINTS (R2 & R3) ====================

@router.post("/supplier-entry")
def register_supplier_entry(payload: SupplierEntryRequest):
    """
    R2: Registra la llegada de insumos de proveedores de manera atómica,
    genera código de recepción auditable e incrementa el stock en inventario.
    """
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0.")

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    now_iso = now.isoformat()

    unit_cost = float(payload.unit_cost or 0.0)
    total_cost = float(payload.total_cost or 0.0)

    if total_cost == 0.0 and unit_cost > 0.0:
        total_cost = unit_cost * float(payload.quantity)
    elif unit_cost == 0.0 and total_cost > 0.0 and payload.quantity > 0:
        unit_cost = total_cost / float(payload.quantity)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE;")
        entry_code = get_next_reception_code(cursor, now)

        # 1. Insertar en bitácora de recepciones de mercancía
        cursor.execute("""
            INSERT INTO merchandise_entries (
                entry_code, date, supplier_name, invoice_number,
                item_name, location, quantity, unit_cost, total_cost, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry_code, date_str, payload.supplier_name.strip(), payload.invoice_number.strip(),
            payload.item_name.strip(), payload.location.strip(), payload.quantity,
            unit_cost, total_cost, payload.notes, now_iso
        ))

        # 2. Buscar insumo correspondiente en la tabla de inventario
        target_name = payload.item_name.strip()
        target_loc = payload.location.strip()

        row = cursor.execute("""
            SELECT id, item_key, name, item_name, category, location, stock, unit
            FROM inventory
            WHERE (
                item_name = ? OR name = ? OR item_key = ? 
                OR LOWER(item_name) = LOWER(?) OR LOWER(name) = LOWER(?) OR LOWER(item_key) = LOWER(?)
            ) AND (
                LOWER(location) = LOWER(?) OR LOWER(category) = LOWER(?)
            )
            LIMIT 1;
        """, (
            target_name, target_name, target_name,
            target_name, target_name, target_name,
            target_loc, target_loc
        )).fetchone()

        if not row:
            # Búsqueda secundaria relajada solo por nombre/clave si la ubicación es compatible
            row = cursor.execute("""
                SELECT id, item_key, name, item_name, category, location, stock, unit
                FROM inventory
                WHERE (
                    item_name = ? OR name = ? OR item_key = ? 
                    OR LOWER(item_name) = LOWER(?) OR LOWER(name) = LOWER(?) OR LOWER(item_key) = LOWER(?)
                )
                LIMIT 1;
            """, (target_name, target_name, target_name, target_name, target_name, target_name)).fetchone()

        if row:
            inv_id = row["id"]
            current_stock = float(row["stock"])
            new_stock = current_stock + float(payload.quantity)

            cursor.execute("""
                UPDATE inventory 
                SET stock = stock + ?, updated_at = ?,
                    item_name = COALESCE(item_name, ?),
                    location = COALESCE(location, ?)
                WHERE id = ?;
            """, (payload.quantity, now_iso, target_name, target_loc, inv_id))
        else:
            # Crear ítem en inventario si no existía
            item_key = f"{slugify(target_name)}_{slugify(target_loc)}"
            cursor.execute("""
                INSERT INTO inventory (
                    item_key, name, category, stock, unit, min_threshold, updated_at, location, item_name
                ) VALUES (?, ?, ?, ?, 'unidad', 5, ?, ?, ?);
            """, (
                item_key, target_name, target_loc.lower(),
                payload.quantity, now_iso, target_loc, target_name
            ))
            new_stock = float(payload.quantity)

        # Si el producto tiene SKU idéntico en products (ej. gaseosas), actualizar costo unitario
        cursor.execute("""
            UPDATE products 
            SET cost = ? 
            WHERE (sku = ? OR name = ?) AND ? > 0;
        """, (int(round(unit_cost)), target_name, target_name, unit_cost))

        conn.commit()

        return {
            "success": True,
            "entry_code": entry_code,
            "new_stock": new_stock,
            "item_name": payload.item_name,
            "location": payload.location
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al registrar entrada de proveedor: {str(e)}")
    finally:
        conn.close()

@router.get("/supplier-entries")
def get_supplier_entries(date: Optional[str] = None, limit: Optional[int] = None):
    """
    R2: Consulta la bitácora auditable de recepciones de proveedores con filtro opcional por fecha.
    """
    conn = get_db_connection()
    try:
        query = "SELECT * FROM merchandise_entries"
        params = []
        if date:
            query += " WHERE date = ?"
            params.append(date)
        query += " ORDER BY id DESC"
        if limit and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()
        entries = [dict(r) for r in rows]
        total_count = len(entries)
        total_value_cop = sum(float(e.get("total_cost") or 0.0) for e in entries)

        return {
            "entries": entries,
            "total_count": total_count,
            "total_value_cop": round(total_value_cop, 2)
        }
    finally:
        conn.close()

@router.post("/set-initial-stock")
def set_initial_stock(payload: SetInitialStockRequest):
    """
    R3: Establece o reemplaza la fotografía de stock de inventario inicial para la fecha dada.
    """
    target_date = payload.date or datetime.now().strftime("%Y-%m-%d")
    recorded_by = payload.recorded_by or "admin"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE;")
        recorded_count = 0

        for item in payload.items:
            name = item.item_name or item.item_key
            if not name:
                continue

            qty = item.quantity if item.quantity is not None else item.initial_stock
            if qty is None:
                qty = 0.0

            loc = item.location
            inv_match = cursor.execute("""
                SELECT item_key, name, item_name, location, category FROM inventory 
                WHERE (
                    item_name = ? OR name = ? OR item_key = ? 
                    OR LOWER(item_name) = LOWER(?) OR LOWER(name) = LOWER(?) OR LOWER(item_key) = LOWER(?)
                ) LIMIT 1;
            """, (name, name, name, name, name, name)).fetchone()

            if inv_match:
                stored_name = inv_match["item_name"] or inv_match["name"]
                if not loc:
                    loc = inv_match["location"] or inv_match["category"].capitalize()
            else:
                stored_name = name.strip()
                if not loc:
                    loc = "Bodega"

            cursor.execute("""
                INSERT INTO daily_initial_inventory (
                    date, item_name, location, quantity, recorded_by, recorded_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date, item_name, location) DO UPDATE SET
                    quantity = excluded.quantity,
                    recorded_by = excluded.recorded_by,
                    recorded_at = CURRENT_TIMESTAMP;
            """, (target_date, stored_name, loc.strip(), float(qty), recorded_by))
            recorded_count += 1

        conn.commit()
        return {"success": True, "recorded_count": recorded_count}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al establecer inventario inicial: {str(e)}")
    finally:
        conn.close()

@router.get("/daily-reconciliation")
def get_daily_reconciliation(date: Optional[str] = None):
    """
    R3: Cálculo en tiempo real de la conciliación diaria de inventario:
    Stock Físico Esperado = Stock Inicial + Entradas Proveedores - Consumo/Ventas
    Discrepancia / Deriva = Stock Actual - Stock Esperado (0.0 en operación normal)
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        # 1. Obtener todos los ítems de inventario del sistema
        inv_rows = conn.execute("""
            SELECT id, item_key, name, item_name, category, location, stock, unit
            FROM inventory
            ORDER BY category, name ASC;
        """).fetchall()

        # 2. Consultar inventario inicial registrado para la fecha
        initial_rows = conn.execute("""
            SELECT item_name, location, quantity 
            FROM daily_initial_inventory 
            WHERE date = ?;
        """, (target_date,)).fetchall()

        initial_map = {}
        for r in initial_rows:
            initial_map[(r["item_name"], r["location"])] = float(r["quantity"])
            initial_map[(r["item_name"].lower(), r["location"].lower())] = float(r["quantity"])

        # 3. Consultar entradas de proveedores para la fecha
        entries_rows = conn.execute("""
            SELECT item_name, location, SUM(quantity) as total_qty
            FROM merchandise_entries
            WHERE date = ?
            GROUP BY item_name, location;
        """, (target_date,)).fetchall()

        entries_map = {}
        for r in entries_rows:
            entries_map[(r["item_name"], r["location"])] = float(r["total_qty"])
            entries_map[(r["item_name"].lower(), r["location"].lower())] = float(r["total_qty"])

        # 4. Consultar despiece realizado hoy (transformación de pollo crudo en presas y caldo)
        butchering_row = conn.execute("""
            SELECT SUM(whole_chickens) as total_chickens
            FROM butchering_logs
            WHERE date(timestamp) = ?;
        """, (target_date,)).fetchone()
        chickens_butchered = float(butchering_row["total_chickens"] or 0) if butchering_row else 0.0

        # 5. Consultar consumo de ventas completadas hoy
        sales_items = conn.execute("""
            SELECT si.chosen_presa, si.quantity, p.sku, p.category
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            JOIN products p ON si.product_id = p.id
            WHERE s.date_str = ? AND s.status = 'completada';
        """, (target_date,)).fetchall()

        consumed_by_key = {}
        def add_consumption(key: str, qty: float):
            consumed_by_key[key] = consumed_by_key.get(key, 0.0) + float(qty)

        for row in sales_items:
            sku = row["sku"]
            qty = float(row["quantity"])
            cat = row["category"]
            chosen = row["chosen_presa"]

            if sku == 'POL-PEC':
                add_consumption('pechuga_vitrina', qty)
            elif sku == 'POL-MUS':
                add_consumption('muslo_vitrina', qty)
            elif sku == 'POL-CON':
                add_consumption('contramuslo_vitrina', qty)
            elif sku == 'POL-ALA':
                add_consumption('ala_vitrina', qty)
            elif sku == 'POL-14':
                add_consumption('muslo_vitrina', qty)
                add_consumption('contramuslo_vitrina', qty)
                add_consumption('papas_raciones', qty)
            elif sku == 'POL-12':
                add_consumption('pechuga_vitrina', qty)
                add_consumption('ala_vitrina', qty)
                add_consumption('muslo_vitrina', qty)
                add_consumption('contramuslo_vitrina', qty)
                add_consumption('papas_raciones', qty)
            elif sku == 'POL-ENT':
                add_consumption('pechuga_vitrina', 2.0 * qty)
                add_consumption('ala_vitrina', 2.0 * qty)
                add_consumption('muslo_vitrina', 2.0 * qty)
                add_consumption('contramuslo_vitrina', 2.0 * qty)
                add_consumption('papas_raciones', 2.0 * qty)
            elif sku == 'ALM-COMP':
                if chosen:
                    presa_key = f"{chosen.strip().lower()}_vitrina"
                    add_consumption(presa_key, qty)
                add_consumption('caldo_raciones', qty)
                add_consumption('arroz_raciones', qty)
                add_consumption('frijoles_raciones', qty)
            elif sku == 'POR-CALD':
                add_consumption('caldo_raciones', qty)
            elif sku == 'POR-FRIJ':
                add_consumption('frijoles_raciones', qty)
            elif sku == 'POR-ARROZ':
                add_consumption('arroz_raciones', qty)
            elif sku == 'POR-PAPAS':
                add_consumption('papas_raciones', qty)
            elif sku == 'POR-AREP':
                add_consumption('arepas_unidades', qty)
            elif cat == 'gaseosas':
                add_consumption(sku, qty)

        # 6. Construir lista de reconciliación por cada ítem
        reconciliation_items = []

        for inv in inv_rows:
            raw_name = inv["item_name"] or inv["name"]
            raw_loc = inv["location"] or inv["category"].capitalize()
            key = inv["item_key"]
            current_stock = float(inv["stock"])

            # Entradas de proveedores acumuladas hoy
            supplier_in = (
                entries_map.get((raw_name, raw_loc)) or
                entries_map.get((raw_name.lower(), raw_loc.lower())) or
                entries_map.get((key, raw_loc)) or
                entries_map.get((key.lower(), raw_loc.lower())) or
                0.0
            )

            # Entradas internas / producción por despiece
            internal_in = 0.0
            if key == 'pechuga_vitrina':
                internal_in = 2.0 * chickens_butchered
            elif key == 'muslo_vitrina':
                internal_in = 2.0 * chickens_butchered
            elif key == 'contramuslo_vitrina':
                internal_in = 2.0 * chickens_butchered
            elif key == 'ala_vitrina':
                internal_in = 2.0 * chickens_butchered
            elif key == 'caldo_raciones':
                internal_in = 2.0 * chickens_butchered

            # Consumo / Despachos
            if key == 'pollo_entero_crudo':
                sales_out = chickens_butchered
            else:
                sales_out = consumed_by_key.get(key, 0.0)

            # Stock inicial (registrado o fallback al inicio del día)
            initial_val = (
                initial_map.get((raw_name, raw_loc)) or
                initial_map.get((raw_name.lower(), raw_loc.lower())) or
                initial_map.get((key, raw_loc)) or
                initial_map.get((key.lower(), raw_loc.lower())) or
                initial_map.get((inv["name"], raw_loc)) or
                initial_map.get((inv["name"].lower(), raw_loc.lower()))
            )

            if initial_val is not None:
                initial_stock = initial_val
            else:
                # Fallback: estado teórico inicial antes de las operaciones de hoy
                initial_stock = max(0.0, current_stock - supplier_in - internal_in + sales_out)

            expected_stock = round(initial_stock + supplier_in + internal_in - sales_out, 4)
            drift = round(current_stock - expected_stock, 4)
            is_item_balanced = abs(drift) < 0.001

            reconciliation_items.append({
                "item_name": raw_name,
                "item_key": key,
                "location": raw_loc,
                "initial_stock": round(initial_stock, 2),
                "supplier_entries": round(supplier_in, 2),
                "sales_dispatches": round(sales_out, 2),
                "expected_stock": round(expected_stock, 2),
                "current_stock": round(current_stock, 2),
                "drift": round(drift, 2),
                "unit": inv["unit"],
                "category": inv["category"],
                "is_balanced": is_item_balanced
            })

        overall_balanced = all(it["is_balanced"] for it in reconciliation_items)

        return {
            "date": target_date,
            "items": reconciliation_items,
            "is_balanced": overall_balanced
        }

    finally:
        conn.close()
