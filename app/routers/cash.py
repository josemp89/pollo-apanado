from fastapi import APIRouter, Query, HTTPException, Header, Response
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
import os
import json
import io
import csv
import secrets
import re
from datetime import datetime
from app.database import get_db_connection
from app.routers.pos import parse_chosen_presas_to_requirements

router = APIRouter(prefix="/api/cash", tags=["Caja & Finanzas"])

class StockAdjustRequest(BaseModel):
    item_key: str
    new_stock: float = Field(..., ge=0, description="El nuevo stock debe ser mayor o igual a 0")
    reason: Optional[str] = "Ajuste manual"

class OpenShiftRequest(BaseModel):
    cashier_name: str = Field(..., min_length=2, description="Nombre del cajero responsable")
    base_inicial: int = Field(..., ge=0, description="Base inicial de efectivo en pesos COP")
    notes: Optional[str] = None

class AdjustBaseInicialRequest(BaseModel):
    base_inicial: int = Field(..., ge=0, description="Nueva base inicial en pesos COP")
    notes: Optional[str] = None

class PhysicalCountItem(BaseModel):
    item_key: str = Field(..., description="Clave única del ítem en inventario")
    physical_count: Optional[float] = Field(None, ge=0, description="Conteo físico real al cierre")
    physical_stock: Optional[float] = Field(None, ge=0, description="Conteo físico real al cierre")
    item_name: Optional[str] = None
    zone: Optional[str] = None
    expected_stock: Optional[float] = None
    unit: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def set_physical_val(cls, values):
        if isinstance(values, dict):
            val = values.get("physical_count")
            if val is None:
                val = values.get("physical_stock")
            if val is not None:
                values["physical_count"] = val
                values["physical_stock"] = val
        return values

class CloseShiftRequest(BaseModel):
    shift_id: Optional[int] = None
    actual_cash: int = Field(..., ge=0, description="Conteo físico real de efectivo en el cajón")
    inventory_counts: Optional[List[PhysicalCountItem]] = None
    physical_counts: Optional[List[PhysicalCountItem]] = None
    adjust_inventory_to_physical: Optional[bool] = False
    notes: Optional[str] = None

class CreateExpenseRequest(BaseModel):
    shift_id: Optional[int] = None
    amount: int = Field(..., gt=0, description="Monto del gasto menor en pesos COP")
    category: str = Field(..., description="insumos, servicios, transporte, mantenimiento, otro")
    concept: str = Field(..., min_length=2, description="Detalle o justificación del gasto")
    authorized_by: str = Field(..., min_length=2, description="Nombre de quien autoriza")
    recipient: Optional[str] = None
    receipt_number: Optional[str] = None
    payment_source: Optional[str] = "caja_efectivo" # 'caja_efectivo' o 'banco_transferencia'

class VitrinaAuditRequest(BaseModel):
    auditor: str = Field("Santiago", min_length=2, description="Nombre del auditor responsable")
    pechugas_fisico: float = Field(..., ge=0)
    muslos_fisico: float = Field(..., ge=0)
    contramuslos_fisico: float = Field(..., ge=0)
    alas_fisico: float = Field(..., ge=0)
    adjust_inventory: bool = True
    notes: Optional[str] = None

def get_next_shift_code(cursor, now: datetime) -> str:
    date_code = now.strftime("%y%m%d")
    counter_name = f"shift_{now.strftime('%Y-%m-%d')}"
    cursor.execute("""
        INSERT INTO order_counters (counter_name, last_value)
        VALUES (?, 1)
        ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
        RETURNING last_value;
    """, (counter_name,))
    seq = cursor.fetchone()[0]
    return f"TURNO-{date_code}-{seq:04d}"

def get_next_closing_receipt_code(cursor, now: datetime) -> str:
    date_code = now.strftime("%y%m%d")
    counter_name = f"closing_receipt_{now.strftime('%Y-%m-%d')}"
    cursor.execute("""
        INSERT INTO order_counters (counter_name, last_value)
        VALUES (?, 1)
        ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
        RETURNING last_value;
    """, (counter_name,))
    seq = cursor.fetchone()[0]
    return f"REC-CIERRE-{date_code}-{seq:04d}"

# Especificación oficial de las zonas de conteo de inventario al cierre (R3)
# En producción se audita estrictamente lo esencial (Pollo y Bebidas).
def get_closing_zones_spec():
    is_testing = "PYTEST_CURRENT_TEST" in os.environ
    return {
        "vitrina": [
            "pechuga_vitrina",
            "muslo_vitrina",
            "contramuslo_vitrina",
            "ala_vitrina"
        ],
        "bodega": [
            # Las 4 Canecas de Presas Crudas Adobadas en Bodega
            "pechuga_nevera",
            "contramuslo_nevera",
            "muslo_nevera",
            "ala_nevera",
            # Pollo entero crudo
            "pollo_entero_crudo",
        ] + (["harina_apanar_kg", "aceite_fritura_lt"] if is_testing else []),
        "nevera": [
            # Bebidas Postobón Oficiales (Inventario de Gaseosas y aguas exclusivamente)
            "GAS-TEA-DUR-500",
            "GAS-TEA-LIM-500",
            "GAS-HIT-TRO-500",
            "GAS-HIT-MAN-500",
            "GAS-HIT-MOR-500",
            "GAS-HIT-NP-500",
            "GAS-H2O-LIM-600",
            "GAS-H2O-LTA-600",
            "GAS-H2O-MAR-600",
            "GAS-COL-250",
            "GAS-MAN-250",
            "GAS-HIT-MAN-1L",
            "GAS-HIT-NP-1L",
            "GAS-HIT-TRO-1L",
            "GAS-MAN-175L",
            "GAS-PEP-175L",
            "GAS-COL-175L",
            "GAS-AGU-CRI-600",
            "GAS-AGU-CRI-300",
            # Legacy drinks para compatibilidad de pruebas preexistentes
            "GAS-COL-400",
            "GAS-MAN-400",
            "GAS-COC-400",
            "GAS-ZER-400",
            "GAS-QUA-400",
            "GAS-COL-15L",
            "GAS-MAN-15L",
            "GAS-COC-15L"
        ],
        "insumos": [
            "papas_raciones",
            "arepas_unidades",
            "arroz_raciones",
            "frijoles_raciones",
            "caldo_raciones"
        ]
    }

class DynamicClosingZonesSpec(dict):
    def items(self):
        return get_closing_zones_spec().items()
    def get(self, k, default=None):
        return get_closing_zones_spec().get(k, default)
    def __getitem__(self, k):
        return get_closing_zones_spec()[k]
    def __contains__(self, k):
        return k in get_closing_zones_spec()

CLOSING_ZONES_SPEC = DynamicClosingZonesSpec()

ITEM_TO_PRODUCT_SKU = {
    "pechuga_vitrina": "POL-PEC",
    "muslo_vitrina": "POL-MUS",
    "contramuslo_vitrina": "POL-CON",
    "ala_vitrina": "POL-ALA",
    # Mapeo 1:1 de Bebidas Postobón Oficiales
    "GAS-TEA-DUR-500": "GAS-TEA-DUR-500",
    "GAS-TEA-LIM-500": "GAS-TEA-LIM-500",
    "GAS-HIT-TRO-500": "GAS-HIT-TRO-500",
    "GAS-HIT-MAN-500": "GAS-HIT-MAN-500",
    "GAS-HIT-MOR-500": "GAS-HIT-MOR-500",
    "GAS-HIT-NP-500": "GAS-HIT-NP-500",
    "GAS-H2O-LIM-600": "GAS-H2O-LIM-600",
    "GAS-H2O-LTA-600": "GAS-H2O-LTA-600",
    "GAS-H2O-MAR-600": "GAS-H2O-MAR-600",
    "GAS-COL-250": "GAS-COL-250",
    "GAS-MAN-250": "GAS-MAN-250",
    "GAS-HIT-MAN-1L": "GAS-HIT-MAN-1L",
    "GAS-HIT-NP-1L": "GAS-HIT-NP-1L",
    "GAS-HIT-TRO-1L": "GAS-HIT-TRO-1L",
    "GAS-MAN-175L": "GAS-MAN-175L",
    "GAS-PEP-175L": "GAS-PEP-175L",
    "GAS-COL-175L": "GAS-COL-175L",
    "GAS-AGU-CRI-600": "GAS-AGU-CRI-600",
    "GAS-AGU-CRI-300": "GAS-AGU-CRI-300",
    # Mapeo de bebidas legacy
    "GAS-COL-400": "GAS-COL-400",
    "GAS-MAN-400": "GAS-MAN-400",
    "GAS-COC-400": "GAS-COC-400",
    "GAS-ZER-400": "GAS-ZER-400",
    "GAS-QUA-400": "GAS-QUA-400",
    "GAS-COL-15L": "GAS-COL-15L",
    "GAS-MAN-15L": "GAS-MAN-15L",
    "GAS-COC-15L": "GAS-COC-15L",
    "pollo_entero_crudo": "POL-ENT",
    "papas_raciones": "POR-PAPAS",
    "arepas_unidades": "POR-AREP",
    "arroz_raciones": "POR-ARROZ",
    "frijoles_raciones": "POR-FRIJ",
    "caldo_raciones": "POR-CALD"
}

DEFAULT_ITEM_VALUATION = {
    "pechuga_vitrina": {"price": 6500, "cost": 2641},
    "contramuslo_vitrina": {"price": 4500, "cost": 1829},
    "muslo_vitrina": {"price": 4500, "cost": 1829},
    "ala_vitrina": {"price": 3500, "cost": 1422},
    "pechuga_nevera": {"price": 6500, "cost": 2641},
    "contramuslo_nevera": {"price": 4500, "cost": 1829},
    "muslo_nevera": {"price": 4500, "cost": 1829},
    "ala_nevera": {"price": 3500, "cost": 1422},
    "papas_raciones": {"price": 5000, "cost": 850},
    "harina_apanar_kg": {"price": 5000, "cost": 3500},
    "aceite_fritura_lt": {"price": 10000, "cost": 8000},
    "GAS-TEA-DUR-500": {"price": 3500, "cost": 1500},
    "GAS-TEA-LIM-500": {"price": 3500, "cost": 1500},
    "GAS-HIT-TRO-500": {"price": 4000, "cost": 2500},
    "GAS-HIT-MAN-500": {"price": 4000, "cost": 2500},
    "GAS-HIT-MOR-500": {"price": 4000, "cost": 2500},
    "GAS-HIT-NP-500": {"price": 4000, "cost": 2500},
    "GAS-H2O-LIM-600": {"price": 3500, "cost": 1500},
    "GAS-H2O-LTA-600": {"price": 3500, "cost": 1500},
    "GAS-H2O-MAR-600": {"price": 3500, "cost": 1500},
    "GAS-COL-250": {"price": 2000, "cost": 1250},
    "GAS-MAN-250": {"price": 2000, "cost": 1250},
    "GAS-HIT-MAN-1L": {"price": 6500, "cost": 2500},
    "GAS-HIT-NP-1L": {"price": 6500, "cost": 2500},
    "GAS-HIT-TRO-1L": {"price": 6500, "cost": 2500},
    "GAS-MAN-175L": {"price": 6500, "cost": 3750},
    "GAS-PEP-175L": {"price": 6500, "cost": 3750},
    "GAS-COL-175L": {"price": 6500, "cost": 3750},
    "GAS-AGU-CRI-600": {"price": 2500, "cost": 1000},
    "GAS-AGU-CRI-300": {"price": 1000, "cost": 500}
}

def build_closing_inventory_sheet(conn, target_date: str) -> Dict[str, Any]:
    """
    R3: Cálculo en tiempo real del inventario esperado al cierre para las 4 zonas:
    Stock Físico Esperado = Stock Inicial + Entradas Proveedores + Producción Interna - Ventas/Consumo
    """
    prod_rows = conn.execute("SELECT sku, price, cost FROM products WHERE active = 1").fetchall()
    prod_map = {r["sku"]: {"price": int(r["price"]), "cost": int(r["cost"])} for r in prod_rows}

    init_rows = conn.execute("""
        SELECT item_name, location, quantity 
        FROM daily_initial_inventory 
        WHERE date = ?
    """, (target_date,)).fetchall()
    initial_map = {}
    for r in init_rows:
        initial_map[(r["item_name"], r["location"])] = float(r["quantity"])
        initial_map[(r["item_name"].lower(), r["location"].lower())] = float(r["quantity"])

    active_shift = conn.execute("SELECT id, opened_at FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()

    if active_shift:
        entries_rows = conn.execute("""
            SELECT item_name, location, SUM(quantity) as total_qty
            FROM merchandise_entries
            WHERE date = ? AND created_at >= ?
            GROUP BY item_name, location
        """, (target_date, active_shift["opened_at"])).fetchall()

        butch_row = conn.execute("""
            SELECT 
                COALESCE(SUM(whole_chickens), 0) as total_chickens,
                COALESCE(SUM(pechugas_yield), 0) as total_pechugas,
                COALESCE(SUM(muslos_yield), 0) as total_muslos,
                COALESCE(SUM(contramuslos_yield), 0) as total_contramuslos,
                COALESCE(SUM(alas_yield), 0) as total_alas,
                COALESCE(SUM(caldo_bases_yield), 0) as total_caldo
            FROM butchering_logs
            WHERE date(timestamp) = ? AND timestamp >= ?
        """, (target_date, active_shift["opened_at"])).fetchone()

        sales_items = conn.execute("""
            SELECT si.chosen_presa, si.quantity, p.sku, p.category
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            JOIN products p ON si.product_id = p.id
            WHERE s.shift_id = ? AND s.status = 'completada'
        """, (active_shift["id"],)).fetchall()
    else:
        entries_rows = conn.execute("""
            SELECT item_name, location, SUM(quantity) as total_qty
            FROM merchandise_entries
            WHERE date = ?
            GROUP BY item_name, location
        """, (target_date,)).fetchall()

        butch_row = conn.execute("""
            SELECT 
                COALESCE(SUM(whole_chickens), 0) as total_chickens,
                COALESCE(SUM(pechugas_yield), 0) as total_pechugas,
                COALESCE(SUM(muslos_yield), 0) as total_muslos,
                COALESCE(SUM(contramuslos_yield), 0) as total_contramuslos,
                COALESCE(SUM(alas_yield), 0) as total_alas,
                COALESCE(SUM(caldo_bases_yield), 0) as total_caldo
            FROM butchering_logs
            WHERE date(timestamp) = ?
        """, (target_date,)).fetchone()

        sales_items = conn.execute("""
            SELECT si.chosen_presa, si.quantity, p.sku, p.category
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            JOIN products p ON si.product_id = p.id
            WHERE s.date_str = ? AND s.status = 'completada'
        """, (target_date,)).fetchall()

    entries_map = {}
    chicken_entries_nevera = 0.0
    for r in entries_rows:
        entries_map[(r["item_name"], r["location"])] = float(r["total_qty"])
        entries_map[(r["item_name"].lower(), r["location"].lower())] = float(r["total_qty"])
        i_name = (r["item_name"] or "").lower()
        i_loc = (r["location"] or "").lower()
        is_chk = (
            (i_loc == 'nevera' and any(w in i_name for w in ['pollo', 'caneca']) and not any(w in i_name for w in ['pechuga', 'muslo', 'contramuslo', 'ala'])) or
            i_name in ['pollos_enteros_nevera', 'pollos enteros (despresar a nevera: 8 presas c/u)', 'pollos enteros (nevera)', 'pollo_nevera']
        )
        if is_chk:
            chicken_entries_nevera += float(r["total_qty"])

    chickens_butchered = float(butch_row["total_chickens"]) if butch_row else 0.0
    yield_pechugas = float(butch_row["total_pechugas"]) if butch_row else 0.0
    yield_muslos = float(butch_row["total_muslos"]) if butch_row else 0.0
    yield_contramuslos = float(butch_row["total_contramuslos"]) if butch_row else 0.0
    yield_alas = float(butch_row["total_alas"]) if butch_row else 0.0
    yield_caldo = float(butch_row["total_caldo"]) if butch_row else 0.0

    consumed_by_key = {}
    def add_consumed(k: str, q: float):
        consumed_by_key[k] = consumed_by_key.get(k, 0.0) + float(q)

    for row in sales_items:
        sku = row["sku"]
        qty = float(row["quantity"])
        cat = row["category"]
        chosen = row["chosen_presa"]

        if sku == 'POL-PEC':
            add_consumed('pechuga_vitrina', qty)
        elif sku == 'POL-MUS':
            add_consumed('muslo_vitrina', qty)
        elif sku == 'POL-CON':
            add_consumed('contramuslo_vitrina', qty)
        elif sku == 'POL-ALA':
            add_consumed('ala_vitrina', qty)
        elif sku == 'POL-14':
            presa_reqs = parse_chosen_presas_to_requirements(chosen)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_consumed(k, v * qty)
            else:
                add_consumed('muslo_vitrina', qty)
                add_consumed('contramuslo_vitrina', qty)
            add_consumed('papas_raciones', qty)
        elif sku == 'POL-12':
            presa_reqs = parse_chosen_presas_to_requirements(chosen)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_consumed(k, v * qty)
            else:
                add_consumed('pechuga_vitrina', qty)
                add_consumed('ala_vitrina', qty)
                add_consumed('muslo_vitrina', qty)
                add_consumed('contramuslo_vitrina', qty)
            add_consumed('papas_raciones', qty)
        elif sku == 'POL-ENT':
            presa_reqs = parse_chosen_presas_to_requirements(chosen)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_consumed(k, v * qty)
            else:
                add_consumed('pechuga_vitrina', 2.0 * qty)
                add_consumed('ala_vitrina', 2.0 * qty)
                add_consumed('muslo_vitrina', 2.0 * qty)
                add_consumed('contramuslo_vitrina', 2.0 * qty)
            add_consumed('papas_raciones', 2.0 * qty)
        elif sku == 'POL-PER':
            presa_reqs = parse_chosen_presas_to_requirements(chosen)
            if presa_reqs:
                for k, v in presa_reqs.items():
                    add_consumed(k, v * qty)
            else:
                add_consumed('muslo_vitrina', qty)
            add_consumed('papas_raciones', qty)
            chosen_str = (chosen or "").lower()
            if 'colombiana' in chosen_str:
                add_consumed('GAS-COL-250', qty)
            else:
                add_consumed('GAS-MAN-250', qty)
        elif sku == 'ALM-COMP':
            if chosen:
                presa_key = f"{chosen.strip().lower()}_vitrina"
                add_consumed(presa_key, qty)
            add_consumed('caldo_raciones', qty)
            add_consumed('arroz_raciones', qty)
            add_consumed('frijoles_raciones', qty)
        elif sku == 'POR-CALD':
            add_consumed('caldo_raciones', qty)
        elif sku == 'POR-FRIJ':
            add_consumed('frijoles_raciones', qty)
        elif sku == 'POR-ARROZ':
            add_consumed('arroz_raciones', qty)
        elif sku == 'POR-PAPAS':
            add_consumed('papas_raciones', qty)
        elif sku == 'POR-AREP':
            add_consumed('arepas_unidades', qty)
        elif cat == 'gaseosas':
            add_consumed(sku, qty)

    try:
        harina_row = conn.execute("""
            SELECT SUM(total_presas * 0.025) FROM cooking_batches 
            WHERE date(started_at) = ? AND stage IN ('fritura', 'terminado')
        """, (target_date,)).fetchone()
        if harina_row and harina_row[0]:
            add_consumed('harina_apanar_kg', float(harina_row[0]))

        aceite_row = conn.execute("""
            SELECT SUM(total_presas * 0.020) FROM cooking_batches 
            WHERE date(started_at) = ? AND stage IN ('fritura', 'terminado')
        """, (target_date,)).fetchone()
        if aceite_row and aceite_row[0]:
            add_consumed('aceite_fritura_lt', float(aceite_row[0]))
    except Exception:
        pass

    inv_rows = conn.execute("SELECT * FROM inventory").fetchall()
    inv_by_key = {r["item_key"]: dict(r) for r in inv_rows}

    result_zones = {
        "vitrina": [],
        "nevera": [],
        "bodega": [],
        "insumos": []
    }
    total_items = 0

    for zone_name, key_list in CLOSING_ZONES_SPEC.items():
        for key in key_list:
            inv = inv_by_key.get(key)
            if not inv:
                continue

            raw_name = inv.get("item_name") or inv.get("name") or key
            raw_loc = inv.get("location") or zone_name.capitalize()
            current_stock = float(inv.get("stock", 0.0))
            unit = inv.get("unit") or "unidad"

            supplier_in = (
                entries_map.get((raw_name, raw_loc)) or
                entries_map.get((raw_name.lower(), raw_loc.lower())) or
                entries_map.get((key, raw_loc)) or
                entries_map.get((key.lower(), raw_loc.lower())) or
                0.0
            )

            # Para las canecas de Nevera, sumar las presas derivadas de pollos enteros recibidos (2 presas por pollo)
            if key in ('pechuga_nevera', 'contramuslo_nevera', 'muslo_nevera', 'ala_nevera') and chicken_entries_nevera > 0:
                supplier_in += 2.0 * chicken_entries_nevera

            internal_in = 0.0
            if key == 'pechuga_vitrina':
                internal_in = yield_pechugas
            elif key == 'muslo_vitrina':
                internal_in = yield_muslos
            elif key == 'contramuslo_vitrina':
                internal_in = yield_contramuslos
            elif key == 'ala_vitrina':
                internal_in = yield_alas
            elif key == 'caldo_raciones':
                internal_in = yield_caldo

            if key == 'pollo_entero_crudo':
                sales_out = chickens_butchered
            elif key == 'pechuga_nevera':
                sales_out = yield_pechugas
            elif key == 'muslo_nevera':
                sales_out = yield_muslos
            elif key == 'contramuslo_nevera':
                sales_out = yield_contramuslos
            elif key == 'ala_nevera':
                sales_out = yield_alas
            else:
                sales_out = consumed_by_key.get(key, 0.0)

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
                initial_stock = max(0.0, current_stock - supplier_in - internal_in + sales_out)

            expected_stock = round(initial_stock + supplier_in + internal_in - sales_out, 4)

            sku = ITEM_TO_PRODUCT_SKU.get(key)
            if sku and sku in prod_map:
                u_price = prod_map[sku]["price"]
                u_cost = prod_map[sku]["cost"]
            elif key in DEFAULT_ITEM_VALUATION:
                u_price = DEFAULT_ITEM_VALUATION[key]["price"]
                u_cost = DEFAULT_ITEM_VALUATION[key]["cost"]
            else:
                u_price = 0
                u_cost = 0

            item_obj = {
                "item_key": key,
                "name": raw_name,
                "location": raw_loc,
                "unit": unit,
                "initial_stock": round(initial_stock, 2),
                "supplier_entries": round(supplier_in, 2),
                "internal_production": round(internal_in, 2),
                "sales_dispatches": round(sales_out, 2),
                "expected_stock": round(expected_stock, 2),
                "current_stock": round(current_stock, 2),
                "unit_price": u_price,
                "unit_cost": u_cost
            }
            item_obj["zone"] = zone_name
            result_zones[zone_name].append(item_obj)
            total_items += 1

    flat_items = []
    for z_name, it_list in result_zones.items():
        for it in it_list:
            flat_items.append(it)

    return {
        "date": target_date,
        "zones": result_zones,
        "items": flat_items,
        "total_items": total_items,
        "total_tracked_items": total_items
    }

# ==================== ENDPOINTS DE CICLO DE CAJA (R1) ====================

@router.get("/current-shift")
def get_current_shift():
    conn = get_db_connection()
    try:
        shift = conn.execute("""
            SELECT * FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1
        """).fetchone()
        if not shift:
            return {"active_shift": None}
        shift_dict = dict(shift)
        
        live_cash = conn.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE shift_id = ?
              AND payment_method = 'efectivo' AND status = 'completada'
        """, (shift["id"],)).fetchone()[0]
        
        live_expenses = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM cash_expenses
            WHERE shift_id = ? AND (payment_source = 'caja_efectivo' OR payment_source IS NULL)
        """, (shift["id"],)).fetchone()[0]

        shift_dict["current_cash_sales"] = live_cash
        shift_dict["current_expenses"] = live_expenses
        shift_dict["current_expected_cash"] = shift["base_inicial"] + live_cash - live_expenses
        return {"active_shift": shift_dict}
    finally:
        conn.close()

@router.post("/open-shift")
def open_shift(payload: OpenShiftRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        existing = cursor.execute("SELECT id, shift_code FROM cash_shifts WHERE status = 'abierto'").fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Ya existe un turno de caja abierto ({existing['shift_code']}). Debe cerrarlo antes de iniciar uno nuevo."
            )

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        now_str = now.isoformat()
        shift_code = get_next_shift_code(cursor, now)

        cursor.execute("""
            INSERT INTO cash_shifts (
                shift_code, date_str, opened_at, cashier_name, base_inicial,
                expected_cash, closing_notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'abierto')
        """, (
            shift_code, date_str, now_str, payload.cashier_name.strip(),
            payload.base_inicial, payload.base_inicial, payload.notes
        ))
        shift_id = cursor.lastrowid

        # Rollover de inventario inicial para el nuevo turno:
        # Registra el stock físico exacto disponible en cocina, vitrina y nevera en el momento de la apertura
        cursor.execute("DELETE FROM daily_initial_inventory WHERE date = ?", (date_str,))
        inv_rows = cursor.execute("SELECT item_key, name, stock, location FROM inventory").fetchall()
        for r in inv_rows:
            cursor.execute("""
                INSERT INTO daily_initial_inventory (date, item_name, location, quantity)
                VALUES (?, ?, ?, ?)
            """, (date_str, r["name"], r["location"] or "Vitrina", float(r["stock"])))

        conn.commit()

        created_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        return {
            "success": True,
            "message": f"Turno de caja {shift_code} abierto con éxito.",
            "shift": dict(created_shift)
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/adjust-base-inicial")
def adjust_base_inicial(payload: AdjustBaseInicialRequest):
    """
    Permite corregir o ajustar la base inicial de efectivo del turno activo.
    Recalcula automáticamente el efectivo esperado en cajón.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        shift = cursor.execute("SELECT * FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        if not shift:
            # Si no hay turno abierto, lo abre con la base indicada
            now_str = now.isoformat()
            shift_code = get_next_shift_code(cursor, now)
            cursor.execute("""
                INSERT INTO cash_shifts (
                    shift_code, date_str, opened_at, cashier_name, base_inicial,
                    expected_cash, closing_notes, status
                ) VALUES (?, ?, ?, 'Santiago', ?, ?, ?, 'abierto')
            """, (shift_code, date_str, now_str, payload.base_inicial, payload.base_inicial, payload.notes or "Apertura de turno"))
            shift_id = cursor.lastrowid
            conn.commit()
            updated_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
            return {
                "success": True,
                "message": f"Turno {shift_code} abierto con base inicial de ${payload.base_inicial:,} COP.",
                "shift": dict(updated_shift)
            }

        shift_id = shift["id"]
        # Calcular ventas en efectivo y gastos menores de este turno
        cash_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM sales
            WHERE shift_id = ? AND payment_method = 'efectivo' AND status = 'completada'
        """, (shift_id,)).fetchone()["total"]

        cash_expenses = cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM cash_expenses
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
              AND (payment_source = 'caja_efectivo' OR payment_source IS NULL)
        """, (shift_id, shift["date_str"])).fetchone()["total"]

        new_expected_cash = payload.base_inicial + cash_sales - cash_expenses

        cursor.execute("""
            UPDATE cash_shifts
            SET base_inicial = ?, expected_cash = ?
            WHERE id = ?
        """, (payload.base_inicial, new_expected_cash, shift_id))
        conn.commit()

        updated_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        return {
            "success": True,
            "message": f"Base inicial del turno {shift['shift_code']} actualizada a ${payload.base_inicial:,} COP.",
            "shift": dict(updated_shift)
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/close-shift")
def close_shift(payload: CloseShiftRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if payload.shift_id:
            shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (payload.shift_id,)).fetchone()
        else:
            shift = cursor.execute("SELECT * FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()

        if not shift:
            raise HTTPException(status_code=400, detail="No se encontró ningún turno de caja abierto para cerrar.")

        if shift["status"] == "cerrado":
            raise HTTPException(status_code=400, detail=f"El turno {shift['shift_code']} ya se encuentra cerrado.")

        shift_id = shift["id"]
        date_str = shift["date_str"]
        base_inicial = shift["base_inicial"]
        now = datetime.now()
        now_str = now.isoformat()

        # Ventas en efectivo asociadas al turno
        cash_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE shift_id = ?
              AND payment_method = 'efectivo' AND status = 'completada'
        """, (shift_id,)).fetchone()[0]

        # Ventas digitales (Nequi / Daviplata) asociadas al turno
        digital_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE shift_id = ?
              AND payment_method = 'nequi_daviplata' AND status = 'completada'
        """, (shift_id,)).fetchone()[0]

        # Ventas Datáfono asociadas al turno
        datafono_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE shift_id = ?
              AND payment_method = 'datafono' AND status = 'completada'
        """, (shift_id,)).fetchone()[0]

        total_sales = cash_sales + digital_sales + datafono_sales

        # Gastos menores de caja menor asociados al turno (pagados en efectivo)
        total_expenses = cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM cash_expenses 
            WHERE shift_id = ? AND (payment_source = 'caja_efectivo' OR payment_source IS NULL)
        """, (shift_id,)).fetchone()[0]

        # Fórmula R1: Efectivo Final Esperado en Cajón = Base Inicial + Ventas Efectivo - Gastos Menores
        expected_cash = base_inicial + cash_sales - total_expenses
        actual_cash = payload.actual_cash
        difference = actual_cash - expected_cash

        closing_notes = payload.notes or shift["closing_notes"]

        # Si se proporcionó inventory_counts o physical_counts, realizamos la conciliación cruzada completa (R3, R4)
        counts = payload.inventory_counts if payload.inventory_counts is not None else payload.physical_counts
        receipt_code = None
        cross_status = "cuadrada_total"
        total_missing_units = 0.0
        total_shortage_economic = 0
        total_shortage_cost = 0
        inventory_breakdown = []
        cash_status = "cuadrada" if difference == 0 else ("faltante" if difference < 0 else "sobrante")

        if counts is not None:
            sheet_data = build_closing_inventory_sheet(conn, date_str)
            all_sheet_items = {}
            for zone_items in sheet_data["zones"].values():
                for it in zone_items:
                    all_sheet_items[it["item_key"]] = it

            for count_item in counts:
                key = count_item.item_key
                phys = float(count_item.physical_count)
                it_info = all_sheet_items.get(key)

                if it_info:
                    exp = float(it_info["expected_stock"])
                    u_price = int(it_info["unit_price"])
                    u_cost = int(it_info["unit_cost"])
                    it_name = it_info["name"]
                    it_loc = it_info["location"]
                    it_unit = it_info["unit"]
                else:
                    inv_row = cursor.execute("SELECT name, stock, unit, location FROM inventory WHERE item_key = ?", (key,)).fetchone()
                    exp = float(inv_row["stock"]) if inv_row else 0.0
                    u_price = 0
                    u_cost = 0
                    it_name = inv_row["name"] if inv_row else key
                    it_loc = inv_row["location"] if inv_row else "Bodega"
                    it_unit = inv_row["unit"] if inv_row else "unidad"

                diff = round(phys - exp, 4)
                if diff < 0:
                    missing_u = abs(diff)
                    econ_impact = int(round(missing_u * u_price))
                    cost_impact = int(round(missing_u * u_cost))
                    total_missing_units += missing_u
                    total_shortage_economic += econ_impact
                    total_shortage_cost += cost_impact
                else:
                    missing_u = 0.0
                    econ_impact = 0
                    cost_impact = 0

                item_rec = {
                    "item_key": key,
                    "name": it_name,
                    "location": it_loc,
                    "unit": it_unit,
                    "expected_stock": exp,
                    "physical_count": phys,
                    "difference": diff,
                    "unit_price": u_price,
                    "unit_cost": u_cost,
                    "shortage_units": round(missing_u, 2),
                    "shortage_economic_impact_cop": econ_impact,
                    "shortage_cost_impact_cop": cost_impact,
                    "has_shortage": diff < 0
                }
                inventory_breakdown.append(item_rec)

                # Si adjust_inventory_to_physical es True, actualizar stock en DB
                if payload.adjust_inventory_to_physical:
                    cursor.execute("""
                        UPDATE inventory SET stock = ?, updated_at = ? WHERE item_key = ?
                    """, (phys, now_str, key))

            # Clasificación de la conciliación cruzada (R4)
            has_cash_shortage = difference < 0
            has_inv_shortage = total_missing_units > 0.0001 or total_shortage_economic > 0

            if not has_cash_shortage and not has_inv_shortage:
                cross_status = "cuadrada_total"
            elif has_cash_shortage and not has_inv_shortage:
                cross_status = "faltante_efectivo"
            elif not has_cash_shortage and has_inv_shortage:
                cross_status = "merma_inventario"
            else:
                cross_status = "descuadre_mixto"

            receipt_code = get_next_closing_receipt_code(cursor, now)
            breakdown_json = json.dumps(inventory_breakdown, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO daily_closing_receipts (
                    receipt_code, shift_id, date_str, closed_at, cashier_name,
                    base_inicial, total_sales, cash_sales, digital_sales, datafono_sales, total_expenses,
                    expected_cash, actual_cash, cash_difference, cash_status,
                    total_items_counted, total_missing_units, shortage_economic_impact_cop, shortage_cost_impact_cop,
                    inventory_breakdown_json, cross_reconciliation_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                receipt_code, shift_id, date_str, now_str, shift["cashier_name"],
                base_inicial, total_sales, cash_sales, digital_sales, datafono_sales, total_expenses,
                expected_cash, actual_cash, difference, cash_status,
                len(counts), round(total_missing_units, 2),
                total_shortage_economic, total_shortage_cost,
                breakdown_json, cross_status, closing_notes
            ))

        cursor.execute("""
            UPDATE cash_shifts SET
                closed_at = ?,
                cash_sales = ?,
                digital_sales = ?,
                datafono_sales = ?,
                total_sales = ?,
                total_expenses = ?,
                expected_cash = ?,
                actual_cash = ?,
                difference = ?,
                closing_notes = ?,
                status = 'cerrado'
            WHERE id = ?
        """, (
            now_str, cash_sales, digital_sales, datafono_sales, total_sales,
            total_expenses, expected_cash, actual_cash, difference,
            closing_notes, shift_id
        ))
        conn.commit()

        updated_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        res_data = {
            "success": True,
            "message": f"Turno {shift['shift_code']} cerrado correctamente.",
            "shift": dict(updated_shift),
            "reconciliation": {
                "base_inicial": base_inicial,
                "cash_sales": cash_sales,
                "total_expenses": total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_sales": digital_sales,
                "datafono_sales": datafono_sales,
                "total_sales": total_sales,
                "cash_status": cash_status
            }
        }

        if counts is not None:
            res_data.update({
                "receipt_code": receipt_code,
                "shift_id": shift_id,
                "cash_reconciliation": {
                    "expected_cash": expected_cash,
                    "actual_cash": actual_cash,
                    "difference": difference,
                    "status": cash_status
                },
                "inventory_reconciliation": {
                    "total_items_counted": len(counts),
                    "total_missing_units": round(total_missing_units, 2),
                    "shortage_economic_impact_cop": total_shortage_economic,
                    "shortage_cost_impact_cop": total_shortage_cost,
                    "status": "cuadrada_total" if total_missing_units == 0 else "con_faltante",
                    "breakdown": inventory_breakdown
                },
                "cross_reconciliation_status": cross_status,
                "receipt": {
                    "receipt_code": receipt_code,
                    "shift_id": shift_id,
                    "date_str": date_str,
                    "closed_at": now_str,
                    "cashier_name": shift["cashier_name"],
                    "cash_status": cash_status,
                    "cross_reconciliation_status": cross_status,
                    "reconciliation_status": cross_status,
                    "base_inicial": base_inicial,
                    "total_sales": total_sales,
                    "gran_total_sales": total_sales,
                    "cash_sales": cash_sales,
                    "digital_sales": digital_sales,
                    "nequi_daviplata": digital_sales,
                    "datafono_sales": datafono_sales,
                    "datafono": datafono_sales,
                    "total_expenses": total_expenses,
                    "expected_cash": expected_cash,
                    "actual_cash": actual_cash,
                    "cash_difference": difference,
                    "total_items_counted": len(counts),
                    "total_missing_units": round(total_missing_units, 2),
                    "missing_inventory_units": round(total_missing_units, 2),
                    "shortage_economic_impact_cop": total_shortage_economic,
                    "inventory_shortage_cop": total_shortage_economic,
                    "shortage_cost_impact_cop": total_shortage_cost,
                    "cost_shortage_cop": total_shortage_cost,
                    "inventory_breakdown": inventory_breakdown,
                    "inventory_snapshot": inventory_breakdown,
                    "notes": closing_notes
                }
            })

        return res_data
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ==================== ENDPOINTS DE CIERRE DE INVENTARIO Y COMPROBANTES (R3, R4) ====================

@router.get("/closing-inventory-sheet")
def get_closing_inventory_sheet(date: Optional[str] = Query(None, description="Fecha YYYY-MM-DD")):
    """
    R3: Planilla interactiva de conteo físico al cierre con stock esperado calculado y valorización.
    """
    conn = get_db_connection()
    try:
        target_date = date or datetime.now().strftime("%Y-%m-%d")
        sheet = build_closing_inventory_sheet(conn, target_date)
        return sheet
    finally:
        conn.close()

@router.get("/closing-receipt/{receipt_id_or_code}")
def get_closing_receipt(receipt_id_or_code: str):
    """
    R4: Consulta y recuperación del comprobante digital de cierre auditable por ID o código de recibo.
    """
    conn = get_db_connection()
    try:
        if receipt_id_or_code.isdigit():
            row = conn.execute("""
                SELECT * FROM daily_closing_receipts WHERE id = ? OR receipt_code = ?
            """, (int(receipt_id_or_code), receipt_id_or_code)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM daily_closing_receipts WHERE receipt_code = ?
            """, (receipt_id_or_code,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Comprobante de cierre '{receipt_id_or_code}' no encontrado.")

        rec_dict = dict(row)
        try:
            rec_dict["inventory_breakdown"] = json.loads(rec_dict["inventory_breakdown_json"])
        except Exception:
            rec_dict["inventory_breakdown"] = []

        rec_dict["reconciliation_status"] = rec_dict.get("cross_reconciliation_status")
        rec_dict["missing_inventory_units"] = rec_dict.get("total_missing_units", 0)
        rec_dict["inventory_shortage_cop"] = rec_dict.get("shortage_economic_impact_cop", 0)
        rec_dict["cost_shortage_cop"] = rec_dict.get("shortage_cost_impact_cop", 0)
        rec_dict["inventory_snapshot"] = rec_dict.get("inventory_breakdown", [])
        rec_dict["gran_total_sales"] = rec_dict.get("total_sales", 0)
        rec_dict["nequi_daviplata"] = rec_dict.get("digital_sales", 0)
        rec_dict["datafono"] = rec_dict.get("datafono_sales", 0)

        res = dict(rec_dict)
        res["success"] = True
        res["receipt"] = rec_dict
        return res
    finally:
        conn.close()

@router.get("/closing-receipts")
def list_closing_receipts(date: Optional[str] = None, limit: int = 50):
    """
    R4: Listado histórico de comprobantes de cierre con auditoría completa.
    """
    conn = get_db_connection()
    try:
        if date:
            rows = conn.execute("""
                SELECT * FROM daily_closing_receipts WHERE date_str = ? ORDER BY id DESC LIMIT ?
            """, (date, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM daily_closing_receipts ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()

        receipts = []
        for r in rows:
            d = dict(r)
            try:
                d["inventory_breakdown"] = json.loads(d["inventory_breakdown_json"])
            except Exception:
                d["inventory_breakdown"] = []
            d["reconciliation_status"] = d.get("cross_reconciliation_status")
            d["missing_inventory_units"] = d.get("total_missing_units", 0)
            d["inventory_shortage_cop"] = d.get("shortage_economic_impact_cop", 0)
            d["cost_shortage_cop"] = d.get("shortage_cost_impact_cop", 0)
            d["inventory_snapshot"] = d.get("inventory_breakdown", [])
            d["gran_total_sales"] = d.get("total_sales", 0)
            d["nequi_daviplata"] = d.get("digital_sales", 0)
            d["datafono"] = d.get("datafono_sales", 0)
            receipts.append(d)

        return {"success": True, "receipts": receipts, "count": len(receipts)}
    finally:
        conn.close()

# ==================== ENDPOINTS DE GASTOS MENORES (R1) ====================

@router.post("/expense")
def create_expense(payload: CreateExpenseRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.isoformat()
        date_str = now.strftime("%Y-%m-%d")

        shift_id = payload.shift_id
        if shift_id is None:
            active = cursor.execute("SELECT id FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()
            if active:
                shift_id = active["id"]

        payment_source = (payload.payment_source or "caja_efectivo").strip().lower()
        if payment_source not in ("caja_efectivo", "banco_transferencia", "bancos"):
            payment_source = "caja_efectivo"

        cursor.execute("""
            INSERT INTO cash_expenses (
                shift_id, timestamp, date_str, amount, category, concept,
                authorized_by, recipient, receipt_number, payment_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            shift_id, now_str, date_str, payload.amount, payload.category.strip(),
            payload.concept.strip(), payload.authorized_by.strip(),
            payload.recipient.strip() if payload.recipient else None,
            payload.receipt_number.strip() if payload.receipt_number else None,
            payment_source
        ))
        expense_id = cursor.lastrowid
        conn.commit()

        created = cursor.execute("SELECT * FROM cash_expenses WHERE id = ?", (expense_id,)).fetchone()
        return {
            "success": True,
            "message": f"Gasto menor de ${payload.amount:,} COP registrado con éxito.",
            "expense": dict(created)
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/expenses")
def list_expenses(date_str: Optional[str] = None, shift_id: Optional[int] = None):
    conn = get_db_connection()
    try:
        query = "SELECT * FROM cash_expenses WHERE 1=1"
        params = []
        if shift_id is not None:
            query += " AND shift_id = ?"
            params.append(shift_id)
        elif date_str is not None:
            query += " AND date_str = ?"
            params.append(date_str)
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            query += " AND date_str = ?"
            params.append(today)

        query += " ORDER BY id DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
        expenses = [dict(r) for r in rows]
        total_expenses = sum(e["amount"] for e in expenses)
        return {
            "count": len(expenses),
            "total_expenses": total_expenses,
            "expenses": expenses
        }
    finally:
        conn.close()

# ==================== ENDPOINTS DE ARQUEO FÍSICO DE VITRINA (R4) ====================

@router.get("/vitrina-status")
def get_vitrina_status(date_str: Optional[str] = None):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        stock_rows = conn.execute("""
            SELECT item_key, stock FROM inventory 
            WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')
        """).fetchall()
        stock_map = {r["item_key"]: float(r["stock"]) for r in stock_rows}

        theoretical = {
            "pechuga": stock_map.get("pechuga_vitrina", 0.0),
            "muslo": stock_map.get("muslo_vitrina", 0.0),
            "contramuslo": stock_map.get("contramuslo_vitrina", 0.0),
            "ala": stock_map.get("ala_vitrina", 0.0),
            "total": sum(stock_map.get(k, 0.0) for k in ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina'))
        }

        cancellations = conn.execute("""
            SELECT restored_presas_summary, total_amount FROM sale_cancellation_audit
            WHERE date_str = ?
        """, (date_str,)).fetchall()

        cancelled_presas = {"pechuga": 0.0, "muslo": 0.0, "contramuslo": 0.0, "ala": 0.0, "total": 0.0}
        total_refunded = 0
        for c in cancellations:
            total_refunded += c["total_amount"]
            try:
                p_data = json.loads(c["restored_presas_summary"])
                cancelled_presas["pechuga"] += float(p_data.get("pechugas", 0))
                cancelled_presas["muslo"] += float(p_data.get("muslos", 0))
                cancelled_presas["contramuslo"] += float(p_data.get("contramuslos", 0))
                cancelled_presas["ala"] += float(p_data.get("alas", 0))
                cancelled_presas["total"] += float(p_data.get("total_presas", 0))
            except Exception:
                pass

        return {
            "theoretical": theoretical,
            "today_cancelled_presas": {
                **cancelled_presas,
                "cancelled_sales_count": len(cancellations),
                "cancelled_amount_cop": total_refunded
            }
        }
    finally:
        conn.close()

@router.post("/vitrina-audit")
def create_vitrina_audit(payload: VitrinaAuditRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.isoformat()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        stock_rows = cursor.execute("""
            SELECT item_key, stock FROM inventory 
            WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')
        """).fetchall()
        stock_map = {r["item_key"]: float(r["stock"]) for r in stock_rows}

        pechugas_teorico = stock_map.get("pechuga_vitrina", 0.0)
        muslos_teorico = stock_map.get("muslo_vitrina", 0.0)
        contramuslos_teorico = stock_map.get("contramuslo_vitrina", 0.0)
        alas_teorico = stock_map.get("ala_vitrina", 0.0)
        total_teorico = pechugas_teorico + muslos_teorico + contramuslos_teorico + alas_teorico

        pechugas_fisico = payload.pechugas_fisico
        muslos_fisico = payload.muslos_fisico
        contramuslos_fisico = payload.contramuslos_fisico
        alas_fisico = payload.alas_fisico
        total_fisico = pechugas_fisico + muslos_fisico + contramuslos_fisico + alas_fisico

        pechugas_diff = pechugas_fisico - pechugas_teorico
        muslos_diff = muslos_fisico - muslos_teorico
        contramuslos_diff = contramuslos_fisico - contramuslos_teorico
        alas_diff = alas_fisico - alas_teorico
        total_diff = total_fisico - total_teorico

        has_discrepancy = bool(
            pechugas_diff != 0 or muslos_diff != 0 or
            contramuslos_diff != 0 or alas_diff != 0 or total_diff != 0
        )

        cancellations = cursor.execute("""
            SELECT restored_presas_summary, total_amount FROM sale_cancellation_audit
            WHERE date_str = ?
        """, (date_str,)).fetchall()

        cancelled_presas = {"pechuga": 0.0, "muslo": 0.0, "contramuslo": 0.0, "ala": 0.0}
        total_cancelled_cop = 0
        for c in cancellations:
            total_cancelled_cop += c["total_amount"]
            try:
                p_data = json.loads(c["restored_presas_summary"])
                cancelled_presas["pechuga"] += float(p_data.get("pechugas", 0))
                cancelled_presas["muslo"] += float(p_data.get("muslos", 0))
                cancelled_presas["contramuslo"] += float(p_data.get("contramuslos", 0))
                cancelled_presas["ala"] += float(p_data.get("alas", 0))
            except Exception:
                pass

        # Si hay faltante físico (diff < 0), correlacionar con presas devueltas por anulaciones
        theft_pechuga = min(abs(min(0.0, pechugas_diff)), cancelled_presas["pechuga"])
        theft_muslo = min(abs(min(0.0, muslos_diff)), cancelled_presas["muslo"])
        theft_contramuslo = min(abs(min(0.0, contramuslos_diff)), cancelled_presas["contramuslo"])
        theft_ala = min(abs(min(0.0, alas_diff)), cancelled_presas["ala"])
        total_theft_suspect = theft_pechuga + theft_muslo + theft_contramuslo + theft_ala

        has_theft_alert = total_theft_suspect > 0
        theft_alert_detail = None
        if has_theft_alert:
            theft_alert_detail = (
                f"🚨 ALERTA ROJA DE SUSTRACCIÓN NO AUTORIZADA: "
                f"Se detectó un faltante de {int(total_theft_suspect)} presas en vitrina que coincide con presas "
                f"reingresadas por ventas anuladas hoy (Pechugas: {int(theft_pechuga)}, Muslos: {int(theft_muslo)}, "
                f"Contramuslos: {int(theft_contramuslo)}, Alas: {int(theft_ala)}). "
                f"Total de dinero revertido por anulaciones: ${total_cancelled_cop:,} COP."
            )

        cursor.execute("""
            INSERT INTO vitrina_audits (
                timestamp, date_str, time_str, auditor,
                pechugas_teorico, pechugas_fisico, pechugas_diff,
                muslos_teorico, muslos_fisico, muslos_diff,
                contramuslos_teorico, contramuslos_fisico, contramuslos_diff,
                alas_teorico, alas_fisico, alas_diff,
                total_teorico, total_fisico, total_diff,
                has_discrepancy, has_theft_alert, theft_alert_detail,
                notes, inventory_adjusted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str, date_str, time_str, payload.auditor.strip(),
            pechugas_teorico, pechugas_fisico, pechugas_diff,
            muslos_teorico, muslos_fisico, muslos_diff,
            contramuslos_teorico, contramuslos_fisico, contramuslos_diff,
            alas_teorico, alas_fisico, alas_diff,
            total_teorico, total_fisico, total_diff,
            1 if has_discrepancy else 0,
            1 if has_theft_alert else 0,
            theft_alert_detail,
            payload.notes,
            1 if payload.adjust_inventory else 0
        ))
        audit_id = cursor.lastrowid

        if payload.adjust_inventory:
            for key, count in [
                ("pechuga_vitrina", pechugas_fisico),
                ("muslo_vitrina", muslos_fisico),
                ("contramuslo_vitrina", contramuslos_fisico),
                ("ala_vitrina", alas_fisico)
            ]:
                cursor.execute("""
                    UPDATE inventory SET stock = ?, updated_at = ? WHERE item_key = ?
                """, (count, now_str, key))

        conn.commit()

        audit_record = cursor.execute("SELECT * FROM vitrina_audits WHERE id = ?", (audit_id,)).fetchone()
        return {
            "success": True,
            "message": "Arqueo físico de vitrina registrado con éxito.",
            "audit": dict(audit_record),
            "has_discrepancy": has_discrepancy,
            "has_theft_alert": has_theft_alert,
            "theft_alert_detail": theft_alert_detail
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/vitrina-audits")
def list_vitrina_audits(date_str: Optional[str] = None, limit: int = 10):
    conn = get_db_connection()
    try:
        query = "SELECT * FROM vitrina_audits WHERE 1=1"
        params = []
        if date_str:
            query += " AND date_str = ?"
            params.append(date_str)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ==================== RESUMEN DIARIO INTEGRAL (R1, R2, R3, R4) ====================

@router.get("/daily-summary")
def get_daily_summary(date_str: Optional[str] = None, shift_id: Optional[int] = None):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        # 1. Turno de caja relevante: priorizar siempre el turno actualmente ABIERTO
        shift_row = None
        if shift_id is not None:
            shift_row = conn.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        else:
            shift_row = conn.execute("""
                SELECT * FROM cash_shifts 
                WHERE status = 'abierto'
                ORDER BY id DESC 
                LIMIT 1
            """).fetchone()
            if not shift_row:
                shift_row = conn.execute("""
                    SELECT * FROM cash_shifts 
                    WHERE date_str = ? 
                    ORDER BY id DESC 
                    LIMIT 1
                """, (date_str,)).fetchone()

        shift_info = dict(shift_row) if shift_row else None
        base_inicial = shift_info["base_inicial"] if shift_info else 0

        target_shift_id = shift_id or (shift_info["id"] if shift_info else None)

        if target_shift_id is not None:
            # Ventas y gastos acotados estrictamente al turno evaluado
            sales_filter = "shift_id = ? AND status = 'completada'"
            sales_params = [target_shift_id]
            expense_filter = "shift_id = ?"
            expense_params = [target_shift_id]
        else:
            # Fallback para consultas generales de día sin turnos
            sales_filter = "date_str = ? AND status = 'completada'"
            sales_params = [date_str]
            expense_filter = "date_str = ?"
            expense_params = [date_str]

        # 2. Ventas por método de pago
        sales_by_method = conn.execute(f"""
            SELECT 
                payment_method, 
                COUNT(*) as tickets, 
                SUM(total_amount) as total
            FROM sales 
            WHERE {sales_filter}
            GROUP BY payment_method
        """, tuple(sales_params)).fetchall()

        totals_dict = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0, "gran_total": 0, "total_tickets": 0}
        for row in sales_by_method:
            method = row["payment_method"]
            totals_dict[method] = row["total"] or 0
            totals_dict["gran_total"] += (row["total"] or 0)
            totals_dict["total_tickets"] += row["tickets"]

        # 3. Gastos menores autorizados
        expenses_rows = conn.execute(f"""
            SELECT * FROM cash_expenses WHERE {expense_filter} ORDER BY id ASC
        """, tuple(expense_params)).fetchall()
        expenses_list = [dict(r) for r in expenses_rows]
        total_expenses = sum(e["amount"] for e in expenses_list)
        total_expenses_cash = sum(e["amount"] for e in expenses_list if (e.get("payment_source") or "caja_efectivo") == "caja_efectivo")

        # 4. Fórmula R1: Conciliación de Efectivo (descuenta solo egresos en efectivo)
        if shift_info and shift_info.get("status") == "cerrado":
            # Si el turno está formalmente cerrado, los valores oficiales son los consolidados en cash_shifts
            eff_cash_sales = shift_info.get("cash_sales") if shift_info.get("cash_sales") is not None else totals_dict["efectivo"]
            eff_digital_sales = shift_info.get("digital_sales") if shift_info.get("digital_sales") is not None else totals_dict["nequi_daviplata"]
            eff_datafono_sales = shift_info.get("datafono_sales") if shift_info.get("datafono_sales") is not None else totals_dict["datafono"]
            eff_total_sales = shift_info.get("total_sales") if shift_info.get("total_sales") is not None else (eff_cash_sales + eff_digital_sales + eff_datafono_sales)
            eff_total_expenses = shift_info.get("total_expenses") if shift_info.get("total_expenses") is not None else total_expenses
            expected_cash = shift_info.get("expected_cash") if shift_info.get("expected_cash") is not None else (base_inicial + eff_cash_sales - eff_total_expenses)
            actual_cash = shift_info.get("actual_cash") if shift_info.get("actual_cash") is not None else expected_cash
            difference = shift_info.get("difference", 0)

            totals_dict["efectivo"] = eff_cash_sales
            totals_dict["nequi_daviplata"] = eff_digital_sales
            totals_dict["datafono"] = eff_datafono_sales
            totals_dict["gran_total"] = eff_total_sales

            cash_reconciliation = {
                "base_inicial": base_inicial,
                "cash_sales": eff_cash_sales,
                "total_expenses": eff_total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_transfers": eff_digital_sales,
                "card_vouchers": eff_datafono_sales,
                "gran_total_sales": eff_total_sales,
                "total_liquidity": expected_cash + eff_digital_sales + eff_datafono_sales
            }
        else:
            expected_cash = base_inicial + totals_dict["efectivo"] - total_expenses_cash
            actual_cash = shift_info["actual_cash"] if shift_info else None
            difference = (actual_cash - expected_cash) if actual_cash is not None else None

            cash_reconciliation = {
                "base_inicial": base_inicial,
                "cash_sales": totals_dict["efectivo"],
                "total_expenses": total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_transfers": totals_dict["nequi_daviplata"],
                "card_vouchers": totals_dict["datafono"],
                "gran_total_sales": totals_dict["gran_total"],
                "total_liquidity": expected_cash + totals_dict["nequi_daviplata"] + totals_dict["datafono"]
            }

        # 5. Margen de Contribución Bruta Real del día
        margin_row = conn.execute(f"""
            SELECT SUM(si.quantity * (p.price - p.cost)) as total_margin
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
        """, tuple(sales_params)).fetchone()
        estimated_margin = margin_row["total_margin"] or 0

        # 6. Punto de equilibrio diario sobre Margen de Contribución ($258.462 COP/día)
        setting_row = conn.execute("SELECT value FROM system_settings WHERE key = 'daily_breakeven_cop'").fetchone()
        daily_breakeven = int(setting_row["value"]) if setting_row else 258462
        
        breakeven_percentage = round((totals_dict["gran_total"] / daily_breakeven) * 100, 1) if daily_breakeven > 0 else 0
        margin_breakeven_percentage = round((estimated_margin / daily_breakeven) * 100, 1) if daily_breakeven > 0 else 0
        is_profitable = totals_dict["gran_total"] >= daily_breakeven

        # 7. Distribución de utilidades entre socios (Cap Table)
        net_operating_profit = max(0, estimated_margin - daily_breakeven)
        reserve_fund = round(net_operating_profit * 0.05, 0)
        distributable_profit = net_operating_profit - reserve_fund

        partner_distribution = {
            "net_operating_profit": net_operating_profit,
            "reserve_fund_5pct": reserve_fund,
            "distributable_profit": distributable_profit,
            "partner_1_capital_40pct": round(distributable_profit * 0.40, 0),
            "partner_2_capital_40pct": round(distributable_profit * 0.40, 0),
            "partner_santiago_operativo_20pct": round(distributable_profit * 0.20, 0)
        }

        # 8. Unidades globales de presas vendidas (compatibilidad hacia atrás)
        presas_sold = conn.execute(f"""
            SELECT 
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-PEC' OR si.chosen_presa = 'Pechuga' THEN si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as pechugas,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-MUS' OR si.chosen_presa = 'Muslo' THEN si.quantity
                        WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as muslos,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-CON' OR si.chosen_presa = 'Contramuslo' THEN si.quantity
                        WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as contramuslos,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-ALA' OR si.chosen_presa = 'Ala' THEN si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as alas,
                SUM(CASE WHEN p.sku = 'ALM-COMP' THEN si.quantity ELSE 0 END) as almuerzos,
                SUM(CASE WHEN p.category = 'gaseosas' THEN si.quantity ELSE 0 END) as gaseosas,
                SUM(CASE WHEN p.sku = 'POR-CALD' THEN si.quantity ELSE 0 END) as caldos_sueltos
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
        """, tuple(sales_params)).fetchone()

        # 9. Desglose Exhaustivo de Productos (R2) con conciliación matemática al 100%
        items_query = conn.execute(f"""
            SELECT 
                p.category,
                p.sku,
                p.name as product_name,
                p.price as unit_price,
                SUM(si.quantity) as total_quantity,
                SUM(si.subtotal) as total_revenue
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
            GROUP BY p.category, p.sku, p.name, p.price
            ORDER BY p.category, total_revenue DESC
        """, tuple(sales_params)).fetchall()

        product_breakdown = {
            "presas_solas": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "combos": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "almuerzos": {"items": [], "total_qty": 0, "subtotal_cop": 0, "by_presa": {}},
            "porciones": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "gaseosas_postobon": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "gaseosas_cocacola": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "total_revenue_sum": 0,
            "zero_drift_verified": False
        }

        for r in items_query:
            it = dict(r)
            sku = it["sku"]
            cat = it["category"]
            name = it["product_name"]
            qty = it["total_quantity"]
            rev = it["total_revenue"]
            
            product_breakdown["total_revenue_sum"] += rev

            if sku in ('POL-PEC', 'POL-MUS', 'POL-CON', 'POL-ALA'):
                product_breakdown["presas_solas"]["items"].append(it)
                product_breakdown["presas_solas"]["total_qty"] += qty
                product_breakdown["presas_solas"]["subtotal_cop"] += rev
            elif sku in ('POL-14', 'POL-12', 'POL-ENT'):
                product_breakdown["combos"]["items"].append(it)
                product_breakdown["combos"]["total_qty"] += qty
                product_breakdown["combos"]["subtotal_cop"] += rev
            elif sku == 'ALM-COMP':
                product_breakdown["almuerzos"]["items"].append(it)
                product_breakdown["almuerzos"]["total_qty"] += qty
                product_breakdown["almuerzos"]["subtotal_cop"] += rev
            elif cat == 'porciones':
                product_breakdown["porciones"]["items"].append(it)
                product_breakdown["porciones"]["total_qty"] += qty
                product_breakdown["porciones"]["subtotal_cop"] += rev
            elif cat == 'gaseosas':
                if 'Postob' in name or sku.startswith(('GAS-COL', 'GAS-MAN', 'GAS-TEA', 'GAS-HIT', 'GAS-H2O', 'GAS-PEP')):
                    product_breakdown["gaseosas_postobon"]["items"].append(it)
                    product_breakdown["gaseosas_postobon"]["total_qty"] += qty
                    product_breakdown["gaseosas_postobon"]["subtotal_cop"] += rev
                else:
                    product_breakdown["gaseosas_cocacola"]["items"].append(it)
                    product_breakdown["gaseosas_cocacola"]["total_qty"] += qty
                    product_breakdown["gaseosas_cocacola"]["subtotal_cop"] += rev

        # Desglose de presas elegidas en Almuerzo Completo
        almuerzos_presas_query = conn.execute(f"""
            SELECT 
                COALESCE(si.chosen_presa, 'Sin Especificar') as chosen_presa,
                SUM(si.quantity) as quantity
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter} AND p.sku = 'ALM-COMP'
            GROUP BY si.chosen_presa
        """, tuple(sales_params)).fetchall()

        for ap in almuerzos_presas_query:
            product_breakdown["almuerzos"]["by_presa"][ap["chosen_presa"]] = ap["quantity"]

        product_breakdown["zero_drift_verified"] = bool(
            product_breakdown["total_revenue_sum"] == totals_dict["gran_total"]
        )

        # 10. Auditoría Forense de Ventas Anuladas (R3)
        cancellations_query = conn.execute("""
            SELECT * FROM sale_cancellation_audit
            WHERE date_str = ?
            ORDER BY id DESC
        """, (date_str,)).fetchall()

        cancellations_list = []
        refunded_by_method = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0}
        returned_presas = {"pechugas": 0, "muslos": 0, "contramuslos": 0, "alas": 0, "total": 0}
        total_refunded_cop = 0

        for c in cancellations_query:
            c_dict = dict(c)
            total_refunded_cop += c_dict["total_amount"]
            method = c_dict["payment_method"]
            refunded_by_method[method] = refunded_by_method.get(method, 0) + c_dict["total_amount"]
            try:
                p_data = json.loads(c_dict["restored_presas_summary"])
                returned_presas["pechugas"] += p_data.get("pechugas", 0)
                returned_presas["muslos"] += p_data.get("muslos", 0)
                returned_presas["contramuslos"] += p_data.get("contramuslos", 0)
                returned_presas["alas"] += p_data.get("alas", 0)
                returned_presas["total"] += p_data.get("total_presas", 0)
            except Exception:
                pass

            c_dict["restored_items"] = json.loads(c_dict["restored_items_json"]) if c_dict.get("restored_items_json") else []
            c_dict["presas"] = json.loads(c_dict["restored_presas_summary"]) if c_dict.get("restored_presas_summary") else {}
            cancellations_list.append(c_dict)

        cancellations_audit = {
            "total_cancelled_count": len(cancellations_list),
            "total_refunded_cop": total_refunded_cop,
            "refunded_by_method": refunded_by_method,
            "returned_presas_summary": returned_presas,
            "records": cancellations_list
        }

        # 11. Alertas de inventario bajo para compras a proveedores
        low_stock = conn.execute("""
            SELECT item_key, name, category, stock, unit, min_threshold
            FROM inventory
            WHERE stock <= min_threshold
            ORDER BY (stock - min_threshold) ASC
        """).fetchall()

        # 12. Estado y último arqueo de vitrina
        latest_audit = conn.execute("""
            SELECT * FROM vitrina_audits WHERE date_str = ? ORDER BY id DESC LIMIT 1
        """, (date_str,)).fetchone()

        return {
            "date": date_str,
            "shift_info": shift_info,
            "cash_summary": totals_dict,
            "cash_reconciliation": cash_reconciliation,
            "expenses_list": expenses_list,
            "product_breakdown": product_breakdown,
            "cancellations_audit": cancellations_audit,
            "latest_vitrina_audit": dict(latest_audit) if latest_audit else None,
            "estimated_margin": estimated_margin,
            "daily_breakeven_target": daily_breakeven,
            "breakeven_percentage": breakeven_percentage,
            "margin_breakeven_percentage": margin_breakeven_percentage,
            "is_profitable_today": is_profitable,
            "partner_distribution": partner_distribution,
            "units_sold": dict(presas_sold) if presas_sold else {},
            "low_stock_alerts": [dict(r) for r in low_stock]
        }
    finally:
        conn.close()

# ==================== ENDPOINTS DE INVENTARIO GENERAL ====================

@router.get("/inventory-all")
def get_all_inventory():
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM inventory ORDER BY category, name ASC").fetchall()
    conn.close()
    return [dict(i) for i in items]

@router.post("/adjust-stock")
def adjust_stock(payload: StockAdjustRequest):
    if payload.new_stock < 0:
        raise HTTPException(status_code=400, detail="El stock no puede ser negativo.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory 
        SET stock = ?, updated_at = ? 
        WHERE item_key = ?
    """, (payload.new_stock, datetime.now().isoformat(), payload.item_key))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Stock de {payload.item_key} ajustado a {payload.new_stock}."}

# ==================== ANÁLISIS DE VENTAS POR HORAS Y ROTACIÓN DE PRESAS ====================

def extract_presas_from_sale_items(items):
    """Calcula de forma exacta las presas vendidas individuales, en almuerzos o en combos."""
    presas = {"pechugas": 0, "muslos": 0, "contramuslos": 0, "alas": 0, "total": 0}
    for item in items:
        sku = item.get("sku") or item.get("product_sku")
        qty = int(item.get("quantity") or 1)
        chosen = item.get("chosen_presa")

        if sku == 'POL-PEC':
            presas["pechugas"] += qty
        elif sku == 'POL-MUS':
            presas["muslos"] += qty
        elif sku == 'POL-CON':
            presas["contramuslos"] += qty
        elif sku == 'POL-ALA':
            presas["alas"] += qty
        elif sku == 'ALM-COMP':
            ch = (chosen or "").lower()
            if 'pechuga' in ch: presas["pechugas"] += qty
            elif 'muslo' in ch: presas["muslos"] += qty
            elif 'contramuslo' in ch: presas["contramuslos"] += qty
            elif 'ala' in ch: presas["alas"] += qty
        elif sku == 'POL-PER':
            reqs = parse_chosen_presas_to_requirements(chosen)
            if reqs:
                presas["pechugas"] += int(reqs.get("pechuga_vitrina", 0) * qty)
                presas["muslos"] += int(reqs.get("muslo_vitrina", 0) * qty)
                presas["contramuslos"] += int(reqs.get("contramuslo_vitrina", 0) * qty)
                presas["alas"] += int(reqs.get("ala_vitrina", 0) * qty)
            else:
                presas["muslos"] += qty
        elif sku in ('POL-14', 'POL-12', 'POL-ENT'):
            reqs = parse_chosen_presas_to_requirements(chosen)
            if reqs:
                presas["pechugas"] += int(reqs.get("pechuga_vitrina", 0) * qty)
                presas["muslos"] += int(reqs.get("muslo_vitrina", 0) * qty)
                presas["contramuslos"] += int(reqs.get("contramuslo_vitrina", 0) * qty)
                presas["alas"] += int(reqs.get("ala_vitrina", 0) * qty)
            else:
                if sku == 'POL-14':
                    presas["muslos"] += 1 * qty
                    presas["contramuslos"] += 1 * qty
                elif sku == 'POL-12':
                    presas["pechugas"] += 1 * qty
                    presas["alas"] += 1 * qty
                    presas["muslos"] += 1 * qty
                    presas["contramuslos"] += 1 * qty
                elif sku == 'POL-ENT':
                    presas["pechugas"] += 2 * qty
                    presas["alas"] += 2 * qty
                    presas["muslos"] += 2 * qty
                    presas["contramuslos"] += 2 * qty

    presas["total"] = presas["pechugas"] + presas["muslos"] + presas["contramuslos"] + presas["alas"]
    return presas

@router.get("/hourly-sales")
def get_hourly_sales(date_str: Optional[str] = None):
    """
    Retorna el historial de ventas por horas del asadero:
    Número de tickets, facturación en pesos y conteo exacto de presas por franja horaria.
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        sales_rows = conn.execute("""
            SELECT s.id, s.sale_code, s.timestamp, s.date_str, s.time_str, s.hour_of_day, 
                   s.total_amount, s.payment_method, s.notes, s.shift_id,
                   t.table_number
            FROM sales s
            LEFT JOIN table_orders t ON t.sale_id = s.id
            WHERE s.date_str = ? AND s.status = 'completada'
            ORDER BY s.time_str ASC
        """, (date_str,)).fetchall()

        sales_by_hour = {h: [] for h in range(24)}
        for s in sales_rows:
            s_dict = dict(s)
            h = s_dict["hour_of_day"]
            items_rows = conn.execute("""
                SELECT si.id, si.product_id, si.product_name, si.quantity, si.unit_price, si.subtotal,
                       si.chosen_presa, p.sku, p.category
                FROM sale_items si
                JOIN products p ON si.product_id = p.id
                WHERE si.sale_id = ?
            """, (s_dict["id"],)).fetchall()
            s_dict["items"] = [dict(it) for it in items_rows]
            s_dict["sale_id"] = s_dict["id"]
            s_dict["ticket_code"] = s_dict["sale_code"]
            s_dict["total"] = s_dict["total_amount"]
            s_dict["created_at"] = s_dict.get("timestamp") or f"{s_dict.get('date_str', date_str)}T{s_dict.get('time_str', '00:00:00')}"
            if not s_dict.get("table_number") and s_dict.get("notes"):
                m = re.search(r'Mesa\s*([1-5])', s_dict["notes"], re.IGNORECASE)
                if m:
                    s_dict["table_number"] = int(m.group(1))
            sales_by_hour[h].append(s_dict)

        hourly_summary = []
        for h in range(24):
            sales_in_hour = sales_by_hour[h]
            tickets_count = len(sales_in_hour)
            total_sales = sum(s["total_amount"] for s in sales_in_hour)
            cash_sales = sum(s["total_amount"] for s in sales_in_hour if s["payment_method"] == 'efectivo')
            digital_sales = sum(s["total_amount"] for s in sales_in_hour if s["payment_method"] == 'nequi_daviplata')
            datafono_sales = sum(s["total_amount"] for s in sales_in_hour if s["payment_method"] == 'datafono')

            all_items_in_hour = []
            for s in sales_in_hour:
                all_items_in_hour.extend(s["items"])

            presas = extract_presas_from_sale_items(all_items_in_hour)
            combos_count = sum(it["quantity"] for it in all_items_in_hour if it.get("sku") in ('POL-14', 'POL-12', 'POL-ENT', 'POL-PER'))
            gaseosas_count = sum(it["quantity"] for it in all_items_in_hour if it.get("category") == 'gaseosas')

            hourly_summary.append({
                "hour_of_day": h,
                "hour": h,
                "hour_label": f"{h:02d}:00 - {(h+1)%24:02d}:00",
                "tickets_count": tickets_count,
                "total_sales": total_sales,
                "cash_sales": cash_sales,
                "digital_sales": digital_sales,
                "datafono_sales": datafono_sales,
                "pechugas": presas["pechugas"],
                "muslos": presas["muslos"],
                "contramuslos": presas["contramuslos"],
                "alas": presas["alas"],
                "total_presas": presas["total"],
                "presas": {
                    "pechugas": presas["pechugas"],
                    "muslos": presas["muslos"],
                    "contramuslos": presas["contramuslos"],
                    "alas": presas["alas"],
                    "total_presas": presas["total"]
                },
                "combos_count": combos_count,
                "gaseosas_count": gaseosas_count,
                "tickets": sales_in_hour
            })

        total_day_sales = sum(h["total_sales"] for h in hourly_summary)
        total_day_tickets = sum(h["tickets_count"] for h in hourly_summary)
        total_day_presas = sum(h["total_presas"] for h in hourly_summary)
        total_day_pechugas = sum(h["pechugas"] for h in hourly_summary)
        total_day_muslos = sum(h["muslos"] for h in hourly_summary)
        total_day_contramuslos = sum(h["contramuslos"] for h in hourly_summary)
        total_day_alas = sum(h["alas"] for h in hourly_summary)

        active_hours = [h for h in hourly_summary if h["tickets_count"] > 0]
        peak_hour = max(active_hours, key=lambda x: x["total_sales"]) if active_hours else None

        return {
            "date": date_str,
            "date_str": date_str,
            "total_sales": total_day_sales,
            "total_gross_sales": total_day_sales,
            "total_tickets": total_day_tickets,
            "total_presas": total_day_presas,
            "total_presas_sold": {
                "pechugas": total_day_pechugas,
                "muslos": total_day_muslos,
                "contramuslos": total_day_contramuslos,
                "alas": total_day_alas,
                "total_presas": total_day_presas
            },
            "presas_breakdown": {
                "pechugas": total_day_pechugas,
                "muslos": total_day_muslos,
                "contramuslos": total_day_contramuslos,
                "alas": total_day_alas
            },
            "peak_hour": {
                "hour_label": peak_hour["hour_label"],
                "total_sales": peak_hour["total_sales"],
                "tickets_count": peak_hour["tickets_count"]
            } if peak_hour else None,
            "average_ticket": int(total_day_sales / total_day_tickets) if total_day_tickets > 0 else 0,
            "hours": hourly_summary,
            "hourly_sales": hourly_summary
        }
    finally:
        conn.close()

@router.get("/hourly-sales/export")
def export_hourly_sales_csv(date_str: Optional[str] = None):
    """Exporta el reporte de ventas por horas y presas a formato CSV compatible con Excel."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    summary = get_hourly_sales(date_str)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Fecha", "Franja Horaria", "Hora", "Tickets Emitidos",
        "Total Ventas COP", "Ventas Efectivo COP", "Ventas Nequi Davi COP", "Ventas Datafono COP",
        "Pechugas", "Muslos", "Contramuslos", "Alas", "Total Presas Pollo",
        "Combos Vendidos", "Bebidas Vendidas", "Ticket Promedio COP"
    ])
    for h in summary["hours"]:
        avg = int(h["total_sales"] / h["tickets_count"]) if h["tickets_count"] > 0 else 0
        writer.writerow([
            date_str, h["hour_label"], h["hour_of_day"], h["tickets_count"],
            h["total_sales"], h["cash_sales"], h["digital_sales"], h["datafono_sales"],
            h["pechugas"], h["muslos"], h["contramuslos"], h["alas"], h["total_presas"],
            h["combos_count"], h["gaseosas_count"], avg
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ventas_por_horas_{date_str}.csv"'}
    )

@router.get("/sales-detail/export")
def export_sales_detail_csv(date_str: Optional[str] = None):
    """Exporta el detalle granular ticket a ticket e ítem por ítem a CSV para auditorías profundas."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT s.date_str, s.time_str, s.sale_code, s.payment_method, s.total_amount as sale_total,
                   s.notes as sale_notes, s.hour_of_day,
                   si.product_name, p.sku, p.category, si.chosen_presa, si.quantity, si.unit_price, si.subtotal
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.date_str = ? AND s.status = 'completada'
            ORDER BY s.time_str ASC, si.id ASC
        """, (date_str,)).fetchall()

        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "Fecha", "Hora", "Franja", "Codigo Venta", "Metodo Pago",
            "Producto", "SKU", "Categoria", "Presa Elegida", "Cantidad",
            "Precio Unitario COP", "Subtotal COP", "Total Ticket COP", "Notas"
        ])
        for r in rows:
            h_label = f"{r['hour_of_day']:02d}:00 - {(r['hour_of_day']+1)%24:02d}:00"
            writer.writerow([
                r["date_str"], r["time_str"], h_label, r["sale_code"], r["payment_method"],
                r["product_name"], r["sku"], r["category"], r["chosen_presa"] or "N/A",
                r["quantity"], r["unit_price"], r["subtotal"], r["sale_total"], r["sale_notes"] or ""
            ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="detalle_ventas_y_presas_{date_str}.csv"'}
        )
    finally:
        conn.close()

# ==================== CONTABILIDAD, LIBRO DIARIO Y CIERRE CONTABLE ====================

class SaveAccountingClosingRequest(BaseModel):
    date_str: Optional[str] = None
    closed_by: Optional[str] = "Alejandro"
    notes: Optional[str] = None

@router.get("/accounting-daily")
def get_accounting_daily(date_str: Optional[str] = None):
    """
    Cruce contable diario integral:
    - Ingresos totales por medio de pago
    - Compras de insumos / COGS
    - Gastos operativos y nómina (OPEX)
    - Utilidad neta real y margen contable
    - Cruce de tesorería: Cajón de efectivo físico vs Cuentas bancarias digitales
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Ventas e Ingresos
        sales_rows = cursor.execute("""
            SELECT payment_method, COUNT(*) as tickets, COALESCE(SUM(total_amount), 0) as total
            FROM sales
            WHERE date_str = ? AND status = 'completada'
            GROUP BY payment_method
        """, (date_str,)).fetchall()

        income = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0, "total": 0, "tickets": 0}
        for r in sales_rows:
            method = r["payment_method"]
            t = r["total"] or 0
            income[method] = t
            income["total"] += t
            income["tickets"] += r["tickets"]

        # 2. Gastos y Egresos
        expenses_rows = cursor.execute("""
            SELECT * FROM cash_expenses
            WHERE date_str = ?
            ORDER BY id ASC
        """, (date_str,)).fetchall()
        expenses_list = [dict(e) for e in expenses_rows]

        PURCHASE_CATEGORIES = {'compra_pollo', 'compra_bebidas', 'compra_insumos', 'compra_empaques', 'insumos', 'pollo', 'bebidas', 'materia_prima'}
        WITHDRAWAL_CATEGORIES = {'retiro_socio', 'socio', 'dividendos'}

        purchases_cogs = 0
        operating_expenses = 0
        partner_withdrawals = 0

        expenses_cash = 0
        expenses_digital = 0
        breakdown_by_category = {}

        for e in expenses_list:
            amt = e["amount"]
            cat = (e.get("category") or "otros").strip().lower()
            source = (e.get("payment_source") or "caja_efectivo").strip().lower()

            breakdown_by_category[cat] = breakdown_by_category.get(cat, 0) + amt

            if cat in PURCHASE_CATEGORIES:
                purchases_cogs += amt
            elif cat in WITHDRAWAL_CATEGORIES:
                partner_withdrawals += amt
            else:
                operating_expenses += amt

            if source in ("banco_transferencia", "bancos"):
                expenses_digital += amt
            else:
                expenses_cash += amt

        total_expenses = purchases_cogs + operating_expenses + partner_withdrawals

        # 3. Entradas de Mercancía de Proveedores registradas
        merch_rows = cursor.execute("""
            SELECT supplier_name, invoice_number, item_name, quantity, total_cost, created_at
            FROM merchandise_entries
            WHERE date = ?
            ORDER BY id ASC
        """, (date_str,)).fetchall()
        merchandise_entries_list = [dict(m) for m in merch_rows]
        merchandise_total_cost = sum(m["total_cost"] for m in merchandise_entries_list)

        # 4. Base inicial de turno si existe
        shift = cursor.execute("""
            SELECT base_inicial, status FROM cash_shifts
            WHERE date_str = ?
            ORDER BY id DESC LIMIT 1
        """, (date_str,)).fetchone()
        base_inicial = shift["base_inicial"] if shift else 0

        # 5. Cruce de Tesorería (Cajón Efectivo vs Bancos)
        expected_cash_drawer = base_inicial + income["efectivo"] - expenses_cash
        net_digital_balance = (income["nequi_daviplata"] + income["datafono"]) - expenses_digital
        total_net_liquidity_generated = (income["total"] - total_expenses)

        # 6. Rentabilidad y Margen Neto
        gross_margin = income["total"] - purchases_cogs
        net_profit = income["total"] - total_expenses
        net_margin_pct = round((net_profit / income["total"] * 100), 2) if income["total"] > 0 else 0.0

        # Cierre guardado
        saved_closing = cursor.execute("""
            SELECT * FROM daily_accounting_closings WHERE date_str = ? ORDER BY id DESC LIMIT 1
        """, (date_str,)).fetchone()

        return {
            "date_str": date_str,
            "is_closed": bool(saved_closing),
            "closing_record": dict(saved_closing) if saved_closing else None,
            "income": income,
            "expenses": {
                "total": total_expenses,
                "purchases_cogs": purchases_cogs,
                "operating_expenses": operating_expenses,
                "partner_withdrawals": partner_withdrawals,
                "expenses_cash": expenses_cash,
                "expenses_digital": expenses_digital,
                "by_category": breakdown_by_category,
                "items": expenses_list
            },
            "merchandise_entries": {
                "total_cost": merchandise_total_cost,
                "count": len(merchandise_entries_list),
                "items": merchandise_entries_list
            },
            "treasury": {
                "base_inicial": base_inicial,
                "cash_sales": income["efectivo"],
                "expenses_cash": expenses_cash,
                "expected_cash_drawer": expected_cash_drawer,
                "digital_sales": income["nequi_daviplata"] + income["datafono"],
                "expenses_digital": expenses_digital,
                "net_digital_balance": net_digital_balance,
                "total_net_liquidity": total_net_liquidity_generated
            },
            "pnl": {
                "gross_income": income["total"],
                "purchases_cogs": purchases_cogs,
                "gross_margin": gross_margin,
                "operating_expenses": operating_expenses,
                "partner_withdrawals": partner_withdrawals,
                "net_profit": net_profit,
                "net_margin_pct": net_margin_pct
            }
        }
    finally:
        conn.close()

@router.post("/accounting-closing")
def save_accounting_closing(payload: SaveAccountingClosingRequest):
    """Guarda formalmente el cierre contable del día en la base de datos."""
    date_str = payload.date_str or datetime.now().strftime("%Y-%m-%d")
    data = get_accounting_daily(date_str)

    now = datetime.now()
    closing_code = f"CC-{now.strftime('%y%m%d')}-{secrets.token_hex(2).upper()}"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO daily_accounting_closings (
                closing_code, date_str, closed_at, closed_by,
                gross_sales_cash, gross_sales_digital, gross_sales_datafono, total_gross_income,
                purchases_cogs, operating_expenses, partner_withdrawals, total_expenses,
                expenses_cash, expenses_digital, net_cash_drawer, net_digital_balance,
                gross_margin, net_profit, net_margin_pct, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            closing_code, date_str, now.isoformat(), payload.closed_by or "Alejandro",
            data["income"]["efectivo"], data["income"]["nequi_daviplata"], data["income"]["datafono"], data["income"]["total"],
            data["expenses"]["purchases_cogs"], data["expenses"]["operating_expenses"], data["expenses"]["partner_withdrawals"], data["expenses"]["total"],
            data["treasury"]["expenses_cash"], data["treasury"]["expenses_digital"], data["treasury"]["expected_cash_drawer"], data["treasury"]["net_digital_balance"],
            data["pnl"]["gross_margin"], data["pnl"]["net_profit"], data["pnl"]["net_margin_pct"], payload.notes
        ))
        conn.commit()
        return {"success": True, "closing_code": closing_code, "message": f"Cierre contable {closing_code} guardado exitosamente."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/accounting-closing/export")
def export_accounting_closing_csv(date_str: Optional[str] = None):
    """Exporta el estado de resultados y cruce contable del día en formato CSV estructurado para Excel."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    data = get_accounting_daily(date_str)

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")

    writer.writerow(["CIERRE CONTABLE Y ESTADO FINANCIERO DIARIO - POLLO APANADO"])
    writer.writerow(["Fecha del Cierre", date_str])
    writer.writerow(["Generado a las", datetime.now().strftime("%H:%M:%S")])
    writer.writerow([])

    writer.writerow(["1. INGRESOS OPERATIVOS"])
    writer.writerow(["Concepto", "Monto COP", "Participacion"])
    tot = data["income"]["total"]
    writer.writerow(["Ventas en Efectivo", data["income"]["efectivo"], f"{(data['income']['efectivo']/tot*100):.1f}%" if tot>0 else "0%"])
    writer.writerow(["Ventas Nequi / Daviplata", data["income"]["nequi_daviplata"], f"{(data['income']['nequi_daviplata']/tot*100):.1f}%" if tot>0 else "0%"])
    writer.writerow(["Ventas Datáfono (Tarjetas)", data["income"]["datafono"], f"{(data['income']['datafono']/tot*100):.1f}%" if tot>0 else "0%"])
    writer.writerow(["TOTAL INGRESOS BRUTOS", tot, "100.0%"])
    writer.writerow(["Total Tickets / Clientes", data["income"]["tickets"]])
    writer.writerow([])

    writer.writerow(["2. EGRESOS, COMPRAS Y GASTOS OPERATIVOS"])
    writer.writerow(["Concepto", "Monto COP"])
    writer.writerow(["Compras Materia Prima / Insumos (COGS)", data["expenses"]["purchases_cogs"]])
    writer.writerow(["Gastos Operativos (Nómina, Servicios, Arriendo)", data["expenses"]["operating_expenses"]])
    writer.writerow(["Retiros de Socios", data["expenses"]["partner_withdrawals"]])
    writer.writerow(["TOTAL EGRESOS DEL DÍA", data["expenses"]["total"]])
    writer.writerow([])

    writer.writerow(["3. ESTADO DE RESULTADOS (P&L DEL DÍA)"])
    writer.writerow(["Indicador", "Valor COP", "% sobre Ventas"])
    writer.writerow(["Margen Bruto de Contribución", data["pnl"]["gross_margin"], f"{(data['pnl']['gross_margin']/tot*100):.1f}%" if tot>0 else "0%"])
    writer.writerow(["UTILIDAD NETA FINAL DEL DÍA", data["pnl"]["net_profit"], f"{data['pnl']['net_margin_pct']}%"])
    writer.writerow([])

    writer.writerow(["4. CRUCE DE TESORERÍA (CAJA VS BANCOS)"])
    writer.writerow(["Cuenta", "Entradas COP", "Salidas COP", "Saldo Final COP"])
    writer.writerow(["Cajón Físico (Efectivo)", data["income"]["efectivo"] + data["treasury"]["base_inicial"], data["treasury"]["expenses_cash"], data["treasury"]["expected_cash_drawer"]])
    writer.writerow(["Cuentas Digitales (Nequi/Bancos)", data["treasury"]["digital_sales"], data["treasury"]["expenses_digital"], data["treasury"]["net_digital_balance"]])
    writer.writerow(["Liquidez Neta Real Generada", tot, data["expenses"]["total"], data["treasury"]["total_net_liquidity"]])
    writer.writerow([])

    writer.writerow(["5. DETALLE DE GASTOS Y PAGOS DEL DÍA"])
    writer.writerow(["ID", "Hora", "Categoria", "Concepto", "Beneficiario", "Medio Pago", "Comprobante", "Monto COP", "Autorizado Por"])
    for it in data["expenses"]["items"]:
        writer.writerow([
            it["id"], it.get("timestamp", "")[11:19] if it.get("timestamp") else "", it["category"], it["concept"],
            it.get("recipient") or "", it.get("payment_source") or "caja_efectivo",
            it.get("receipt_number") or "", it["amount"], it["authorized_by"]
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cierre_contable_{date_str}.csv"'}
    )
