"""
Test Suite E2E: Cierre de Caja, Cuadre de Inventario Físico y Comprobantes Digitales (R1 - R4)
Valida empíricamente:
1. Carga y estructura de la planilla interactiva en las 4 zonas oficiales: Vitrina, Nevera, Bodega, Insumos.
2. Fórmula aritmética del stock esperado al cierre (Inicial + Entradas + Producción - Salidas/Consumo).
3. Cierre de turno con caja cuadrada (diferencia 0).
4. Cierre de turno con faltante de efectivo (diferencia negativa) y con sobrante (diferencia positiva).
5. Cuadre de inventario físico: detección de mermas/faltantes y su valorización en pesos COP (precio de venta y costo).
6. Bandera de ajuste de inventario en base de datos (`adjust_inventory_to_physical`).
7. Creación, persistencia y recuperación del comprobante digital de cierre (`daily_closing_receipts`) por código e ID.
8. Matriz completa de clasificación de conciliación cruzada (cuadrada_total, faltante_efectivo, merma_inventario, descuadre_mixto).
9. Validaciones de frontera, robustez y manejo de errores (400, 404, 422).
"""

import pytest
from datetime import datetime
import json

def test_closing_inventory_sheet_four_zones_structure_and_valuation(client):
    """
    Verifica que la planilla de inventario al cierre cargue exactamente las 4 zonas oficiales
    (Vitrina, Nevera, Bodega, Insumos) con valorización económica (precio y costo unitario).
    """
    res = client.get("/api/cash/closing-inventory-sheet")
    assert res.status_code == 200
    data = res.json()

    assert "date" in data
    assert "zones" in data
    assert "total_tracked_items" in data
    assert data["total_tracked_items"] >= 20

    zones = data["zones"]
    assert "vitrina" in zones, "Debe existir la zona Vitrina"
    assert "nevera" in zones, "Debe existir la zona Nevera"
    assert "bodega" in zones, "Debe existir la zona Bodega"
    assert "insumos" in zones, "Debe existir la zona Insumos"

    # Verificar zona Vitrina
    vitrina_keys = [it["item_key"] for it in zones["vitrina"]]
    for expected_key in ["pechuga_vitrina", "muslo_vitrina", "contramuslo_vitrina", "ala_vitrina"]:
        assert expected_key in vitrina_keys

    # Verificar zona Nevera
    nevera_keys = [it["item_key"] for it in zones["nevera"]]
    assert "GAS-COL-400" in nevera_keys
    assert "GAS-COC-400" in nevera_keys
    assert "GAS-MAN-15L" in nevera_keys

    # Verificar zona Bodega
    bodega_keys = [it["item_key"] for it in zones["bodega"]]
    assert "pollo_entero_crudo" in bodega_keys
    assert "harina_apanar_kg" in bodega_keys
    assert "aceite_fritura_lt" in bodega_keys

    # Verificar zona Insumos
    insumos_keys = [it["item_key"] for it in zones["insumos"]]
    for expected_key in ["papas_raciones", "arepas_unidades", "arroz_raciones", "frijoles_raciones", "caldo_raciones"]:
        assert expected_key in insumos_keys

    # Validar que todos los ítems tengan los campos requeridos y valores económicos no nulos
    for zone_name, items in zones.items():
        for item in items:
            assert "item_key" in item
            assert "name" in item
            assert "location" in item
            assert "unit" in item
            assert "initial_stock" in item
            assert "supplier_entries" in item
            assert "internal_production" in item
            assert "sales_dispatches" in item
            assert "expected_stock" in item
            assert "current_stock" in item
            assert "unit_price" in item
            assert "unit_cost" in item
            assert item["unit_price"] >= 0
            assert item["unit_cost"] >= 0


def test_closing_inventory_sheet_formula_with_entries_and_sales(client, db_conn):
    """
    Verifica la fórmula: Stock Esperado = Stock Inicial + Entradas Proveedores + Producción Interna - Ventas/Consumo
    con entradas de proveedores y ventas reales registradas en el día.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Registrar entrada de mercancía (harina +10 kg, Postobón Manzana 400ml +24 unidades)
    db_conn.execute("""
        INSERT INTO merchandise_entries (entry_code, date, supplier_name, invoice_number, item_name, location, quantity, unit_cost, total_cost)
        VALUES ('ENT-TEST-001', ?, 'Distribuidora Harinas', 'FAC-991', 'harina_apanar_kg', 'Bodega', 10.0, 3500, 35000)
    """, (today_str,))
    db_conn.execute("""
        INSERT INTO merchandise_entries (entry_code, date, supplier_name, invoice_number, item_name, location, quantity, unit_cost, total_cost)
        VALUES ('ENT-TEST-002', ?, 'Postobón S.A.', 'FAC-992', 'GAS-MAN-400', 'Nevera', 24.0, 2200, 52800)
    """, (today_str,))

    # 2. Registrar despiece de 5 pollos (producción interna: +10 pechugas, +10 muslos, +10 contramuslos, +10 alas, +10 caldos)
    db_conn.execute("""
        INSERT INTO butchering_logs (timestamp, operator, whole_chickens, pechugas_yield, muslos_yield, contramuslos_yield, alas_yield, caldo_bases_yield)
        VALUES (?, 'Santiago', 5, 10, 10, 10, 10, 10)
    """, (datetime.now().isoformat(),))

    # 3. Registrar venta de 2 pechugas sueltas y 3 gaseosas Manzana
    now_str = datetime.now().isoformat()
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, cash_received, change_returned, status)
        VALUES ('VENTA-CIERRE-001', ?, ?, '12:00:00', 12, 1, 28500, 'efectivo', 30000, 1500, 'completada')
    """, (now_str, today_str))
    sale_id = cur.lastrowid

    # Obtener IDs de producto
    pec_id = db_conn.execute("SELECT id FROM products WHERE sku = 'POL-PEC'").fetchone()["id"]
    gas_id = db_conn.execute("SELECT id FROM products WHERE sku = 'GAS-MAN-400'").fetchone()["id"]

    cur.execute("""
        INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
        VALUES (?, ?, 'Pechuga Sola', 2, 9000, 18000)
    """, (sale_id, pec_id))
    cur.execute("""
        INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
        VALUES (?, ?, 'Postobón Manzana 400ml', 3, 3500, 10500)
    """, (sale_id, gas_id))
    db_conn.commit()

    # 4. Consultar planilla de cierre
    res = client.get(f"/api/cash/closing-inventory-sheet?date={today_str}")
    assert res.status_code == 200
    data = res.json()

    # Validar Pechuga en Vitrina
    pec_item = next(it for it in data["zones"]["vitrina"] if it["item_key"] == "pechuga_vitrina")
    assert pec_item["internal_production"] == 10.0  # 5 pollos * 2
    assert pec_item["sales_dispatches"] == 2.0      # 2 vendidas
    expected_pec = pec_item["initial_stock"] + pec_item["supplier_entries"] + pec_item["internal_production"] - pec_item["sales_dispatches"]
    assert pec_item["expected_stock"] == round(expected_pec, 2)

    # Validar Gaseosa Manzana en Nevera
    gas_item = next(it for it in data["zones"]["nevera"] if it["item_key"] == "GAS-MAN-400")
    assert gas_item["supplier_entries"] == 24.0
    assert gas_item["sales_dispatches"] == 3.0
    expected_gas = gas_item["initial_stock"] + gas_item["supplier_entries"] + gas_item["internal_production"] - gas_item["sales_dispatches"]
    assert gas_item["expected_stock"] == round(expected_gas, 2)


def test_close_shift_balanced_cash_zero_difference(client, helpers):
    """
    Verifica el cierre de caja perfectamente cuadrado (diferencia == 0 COP).
    Efectivo Esperado = Base Inicial + Ventas Efectivo - Gastos Menores.
    """
    # 1. Abrir turno con base inicial de 70,000 COP
    open_res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Valentina",
        "base_inicial": 70000,
        "notes": "Apertura turno mañana"
    })
    assert open_res.status_code == 200
    shift_id = open_res.json()["shift"]["id"]

    # 2. Registrar venta en efectivo por 25,000 COP
    sale_res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-12"), "quantity": 1},
            {"product_id": helpers.get_product_id("POR-PAPAS"), "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert sale_res.status_code == 200

    # 3. Registrar gasto menor por 12,000 COP (transporte insumos)
    exp_res = client.post("/api/cash/expense", json={
        "shift_id": shift_id,
        "amount": 12000,
        "category": "transporte",
        "concept": "Taxi compra de verduras urgentes",
        "authorized_by": "Santiago"
    })
    assert exp_res.status_code == 200

    # Efectivo esperado = 70,000 + 25,000 - 12,000 = 83,000 COP
    # 4. Cerrar turno con exactamente 83,000 COP en el cajón
    close_res = client.post("/api/cash/close-shift", json={
        "shift_id": shift_id,
        "actual_cash": 83000,
        "notes": "Cierre exacto sin novedad"
    })
    assert close_res.status_code == 200
    close_data = close_res.json()

    assert close_data["success"] is True
    rec = close_data["reconciliation"]
    assert rec["base_inicial"] == 70000
    assert rec["cash_sales"] == 25000
    assert rec["total_expenses"] == 12000
    assert rec["expected_cash"] == 83000
    assert rec["actual_cash"] == 83000
    assert rec["difference"] == 0
    assert rec["cash_status"] == "cuadrada"
    assert close_data["shift"]["status"] == "cerrado"


def test_close_shift_cash_shortage_and_surplus(client, helpers):
    """
    Verifica detección rigurosa de descuadres de efectivo:
    - Faltante (diferencia negativa)
    - Sobrante (diferencia positiva)
    """
    # CASO A: Faltante de efectivo
    open_res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Camilo",
        "base_inicial": 100000,
        "notes": "Turno con faltante intencional"
    })
    shift_a_id = open_res.json()["shift"]["id"]

    # Venta de 36,000 COP
    sale_a = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-ENT"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 40000
    })
    assert sale_a.status_code == 200

    # Esperado: 100,000 + 36,000 = 136,000. Cajero reporta 130,000 (Faltante 6,000)
    close_a = client.post("/api/cash/close-shift", json={
        "shift_id": shift_a_id,
        "actual_cash": 130000,
        "notes": "Faltante reportado por cajero"
    })
    assert close_a.status_code == 200
    rec_a = close_a.json()["reconciliation"]
    assert rec_a["expected_cash"] == 136000
    assert rec_a["actual_cash"] == 130000
    assert rec_a["difference"] == -6000
    assert rec_a["cash_status"] == "faltante"

    # CASO B: Sobrante de efectivo
    open_b = client.post("/api/cash/open-shift", json={
        "cashier_name": "Laura",
        "base_inicial": 50000,
        "notes": "Turno con sobrante intencional"
    })
    shift_b_id = open_b.json()["shift"]["id"]

    # Esperado: 50,000. Cajero cuenta 54,500 (Sobrante 4,500)
    close_b = client.post("/api/cash/close-shift", json={
        "shift_id": shift_b_id,
        "actual_cash": 54500,
        "notes": "Propina o vuelto no reclamado"
    })
    assert close_b.status_code == 200
    rec_b = close_b.json()["reconciliation"]
    assert rec_b["expected_cash"] == 50000
    assert rec_b["actual_cash"] == 54500
    assert rec_b["difference"] == 4500
    assert rec_b["cash_status"] == "sobrante"


def test_physical_inventory_reconciliation_shortage_detection_and_valuation(client):
    """
    Verifica el cuadre físico de inventario al cierre:
    - Conteo físico menor al esperado (merma/faltante).
    - Cuantificación de unidades faltantes.
    - Valorización en COP a precio de venta y a costo unitario.
    - Soporte para lista 'physical_counts' directa o 'inventory_counts'.
    """
    # 1. Abrir turno
    open_res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Andrés",
        "base_inicial": 80000
    })
    shift_id = open_res.json()["shift"]["id"]

    # 2. Consultar planilla de inventario para saber el stock inicial/esperado
    sheet_res = client.get("/api/cash/closing-inventory-sheet")
    sheet_data = sheet_res.json()

    vitrina_items = {it["item_key"]: it for it in sheet_data["zones"]["vitrina"]}
    nevera_items = {it["item_key"]: it for it in sheet_data["zones"]["nevera"]}

    exp_pechuga = vitrina_items["pechuga_vitrina"]["expected_stock"]
    exp_coca = nevera_items["GAS-COC-400"]["expected_stock"]

    # Precios y costos esperados de POL-PEC y GAS-COC-400
    price_pechuga = vitrina_items["pechuga_vitrina"]["unit_price"] # 9000
    cost_pechuga = vitrina_items["pechuga_vitrina"]["unit_cost"]   # 4500
    price_coca = nevera_items["GAS-COC-400"]["unit_price"]         # 4000
    cost_coca = nevera_items["GAS-COC-400"]["unit_cost"]           # 2500

    # Simulamos conteo físico con faltantes:
    # 2 pechugas faltantes
    # 3 gaseosas Coca-Cola faltantes
    phys_pechuga = exp_pechuga - 2.0
    phys_coca = exp_coca - 3.0

    expected_shortage_units = 5.0
    expected_econ_loss = (2 * price_pechuga) + (3 * price_coca)  # 2*9000 + 3*4000 = 18000 + 12000 = 30000
    expected_cost_loss = (2 * cost_pechuga) + (3 * cost_coca)    # 2*4500 + 3*2500 = 9000 + 7500 = 16500

    # 3. Cerrar turno enviando physical_counts
    close_res = client.post("/api/cash/close-shift", json={
        "shift_id": shift_id,
        "actual_cash": 80000,
        "physical_counts": [
            {"item_key": "pechuga_vitrina", "physical_count": phys_pechuga},
            {"item_key": "GAS-COC-400", "physical_count": phys_coca}
        ],
        "notes": "Cierre con faltante físico en vitrina y nevera"
    })
    assert close_res.status_code == 200
    data = close_res.json()

    assert "inventory_reconciliation" in data
    inv_rec = data["inventory_reconciliation"]
    assert inv_rec["total_items_counted"] == 2
    assert inv_rec["total_missing_units"] == expected_shortage_units
    assert inv_rec["shortage_economic_impact_cop"] == expected_econ_loss
    assert inv_rec["shortage_cost_impact_cop"] == expected_cost_loss
    assert inv_rec["status"] == "con_faltante"

    # Verificar el desglose de cada ítem
    breakdown = {it["item_key"]: it for it in inv_rec["breakdown"]}
    assert breakdown["pechuga_vitrina"]["shortage_units"] == 2.0
    assert breakdown["pechuga_vitrina"]["shortage_economic_impact_cop"] == 2 * price_pechuga
    assert breakdown["pechuga_vitrina"]["shortage_cost_impact_cop"] == 2 * cost_pechuga
    assert breakdown["pechuga_vitrina"]["has_shortage"] is True

    assert breakdown["GAS-COC-400"]["shortage_units"] == 3.0
    assert breakdown["GAS-COC-400"]["shortage_economic_impact_cop"] == 3 * price_coca
    assert breakdown["GAS-COC-400"]["shortage_cost_impact_cop"] == 3 * cost_coca
    assert breakdown["GAS-COC-400"]["has_shortage"] is True


def test_adjust_inventory_to_physical_flag_updates_db(client, db_conn):
    """
    Verifica que si `adjust_inventory_to_physical` es True, la tabla inventory
    se sincronice con el conteo físico real.
    """
    open_res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Admin",
        "base_inicial": 50000
    })
    shift_id = open_res.json()["shift"]["id"]

    target_key = "ala_vitrina"
    orig_stock = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (target_key,)).fetchone()["stock"]
    new_physical = 7.0

    close_res = client.post("/api/cash/close-shift", json={
        "shift_id": shift_id,
        "actual_cash": 50000,
        "inventory_counts": [
            {"item_key": target_key, "physical_count": new_physical}
        ],
        "adjust_inventory_to_physical": True,
        "notes": "Ajuste forzado de inventario a físico"
    })
    assert close_res.status_code == 200

    # Comprobar que en la base de datos el stock se actualizó
    updated_stock = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (target_key,)).fetchone()["stock"]
    assert updated_stock == new_physical


def test_closing_receipt_creation_persistence_and_retrieval(client, helpers):
    """
    Verifica la generación, persistencia en `daily_closing_receipts` y recuperación
    tanto por receipt_code como por ID numérico y a través del endpoint de listado histórico.
    """
    open_res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Marta",
        "base_inicial": 120000
    })
    shift_id = open_res.json()["shift"]["id"]

    # Venta de 9,000 COP
    sale_res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-PEC"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert sale_res.status_code == 200

    # Cierre con conteo de inventario (genera recibo digital)
    close_res = client.post("/api/cash/close-shift", json={
        "shift_id": shift_id,
        "actual_cash": 129000,
        "inventory_counts": [
            {"item_key": "pechuga_vitrina", "physical_count": 11.0}
        ],
        "notes": "Comprobante de cierre auditable"
    })
    assert close_res.status_code == 200
    close_data = close_res.json()

    receipt_code = close_data.get("receipt_code")
    assert receipt_code is not None
    assert receipt_code.startswith("REC-CIERRE-")

    # 1. Recuperar recibo por receipt_code
    get_res = client.get(f"/api/cash/closing-receipt/{receipt_code}")
    assert get_res.status_code == 200
    receipt_data = get_res.json()["receipt"]

    assert receipt_data["receipt_code"] == receipt_code
    assert receipt_data["shift_id"] == shift_id
    assert receipt_data["cashier_name"] == "Marta"
    assert receipt_data["base_inicial"] == 120000
    assert receipt_data["cash_sales"] == 9000
    assert receipt_data["expected_cash"] == 129000
    assert receipt_data["actual_cash"] == 129000
    assert receipt_data["cash_difference"] == 0
    assert receipt_data["cash_status"] == "cuadrada"
    assert "inventory_breakdown" in receipt_data
    assert len(receipt_data["inventory_breakdown"]) == 1

    # 2. Recuperar recibo por ID numérico
    receipt_id = receipt_data["id"]
    get_by_id = client.get(f"/api/cash/closing-receipt/{receipt_id}")
    assert get_by_id.status_code == 200
    assert get_by_id.json()["receipt"]["receipt_code"] == receipt_code

    # 3. Listado de recibos (/api/cash/closing-receipts)
    list_res = client.get("/api/cash/closing-receipts")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["count"] >= 1
    found = any(r["receipt_code"] == receipt_code for r in list_data["receipts"])
    assert found is True

    # 4. Filtrar por fecha
    today_str = datetime.now().strftime("%Y-%m-%d")
    filter_res = client.get(f"/api/cash/closing-receipts?date={today_str}")
    assert filter_res.status_code == 200
    assert any(r["receipt_code"] == receipt_code for r in filter_res.json()["receipts"])


def test_cross_reconciliation_status_classification_matrix(client):
    """
    Verifica las 4 clasificaciones oficiales de la matriz de conciliación cruzada (R4):
    1. cuadrada_total: Efectivo cuadrado (diff >= 0) y sin merma en inventario.
    2. faltante_efectivo: Efectivo con faltante (diff < 0) y sin merma en inventario.
    3. merma_inventario: Efectivo cuadrado (diff >= 0) pero con merma en inventario.
    4. descuadre_mixto: Efectivo con faltante (diff < 0) Y merma en inventario.
    """
    matrix_cases = [
        # (cash_delta, inv_delta, expected_status)
        (0, 0, "cuadrada_total"),
        (-5000, 0, "faltante_efectivo"),
        (0, -2, "merma_inventario"),
        (-5000, -2, "descuadre_mixto")
    ]

    for cash_delta, inv_delta, expected_status in matrix_cases:
        # Abrir turno
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": f"Tester-{expected_status}",
            "base_inicial": 50000
        })
        s_id = open_res.json()["shift"]["id"]

        sheet = client.get("/api/cash/closing-inventory-sheet").json()
        target_item = sheet["zones"]["vitrina"][0]
        exp_stock = target_item["expected_stock"]
        phys_stock = exp_stock + inv_delta  # if inv_delta < 0 => merma

        actual_cash = 50000 + cash_delta

        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": s_id,
            "actual_cash": actual_cash,
            "physical_counts": [
                {"item_key": target_item["item_key"], "physical_count": phys_stock}
            ]
        })
        assert close_res.status_code == 200
        res_data = close_res.json()
        assert res_data["cross_reconciliation_status"] == expected_status, (
            f"Esperado {expected_status} para cash_delta={cash_delta}, inv_delta={inv_delta}, pero obtuvo {res_data['cross_reconciliation_status']}"
        )


def test_closing_error_handling_and_validations(client):
    """
    Verifica validaciones de frontera y manejo de errores:
    - Intentar cerrar cuando no hay turno abierto -> 400.
    - Intentar re-cerrar un turno ya cerrado -> 400.
    - Buscar recibo inexistente -> 404.
    - Conteo de efectivo negativo -> 400 (Pydantic / RequestValidationError).
    - Conteo de inventario físico negativo -> 400 (Pydantic / RequestValidationError).
    """
    # 1. Cerrar sin turno abierto
    res_no_shift = client.post("/api/cash/close-shift", json={"actual_cash": 50000})
    assert res_no_shift.status_code == 400
    assert "No se encontró ningún turno" in res_no_shift.json()["detail"]

    # 2. Abrir y cerrar turno
    open_res = client.post("/api/cash/open-shift", json={"cashier_name": "Sara", "base_inicial": 20000})
    shift_id = open_res.json()["shift"]["id"]

    close_1 = client.post("/api/cash/close-shift", json={"shift_id": shift_id, "actual_cash": 20000})
    assert close_1.status_code == 200

    # Re-cerrar turno ya cerrado
    close_again = client.post("/api/cash/close-shift", json={"shift_id": shift_id, "actual_cash": 20000})
    assert close_again.status_code == 400
    assert "ya se encuentra cerrado" in close_again.json()["detail"]

    # 3. Buscar comprobante inexistente
    rec_not_found = client.get("/api/cash/closing-receipt/REC-INEXISTENTE-999")
    assert rec_not_found.status_code == 404

    # 4. Validaciones Pydantic de valores negativos (capturadas por validation_exception_handler como HTTP 400)
    neg_cash = client.post("/api/cash/close-shift", json={"actual_cash": -500})
    assert neg_cash.status_code == 400
    assert "actual_cash" in str(neg_cash.json())

    neg_inv = client.post("/api/cash/close-shift", json={
        "actual_cash": 50000,
        "physical_counts": [{"item_key": "pechuga_vitrina", "physical_count": -3}]
    })
    assert neg_inv.status_code == 400
    assert "physical_count" in str(neg_inv.json())
