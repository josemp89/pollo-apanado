import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from app.main import app
from app.database import get_db_connection, init_db

@pytest.fixture(autouse=True)
def setup_santiago_audit_db(monkeypatch, tmp_path):
    test_db = str(tmp_path / "test_santiago_audit.db")
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("ADMIN_PIN", "4321")
    init_db()

    # Pre-cargar inventario y stock de prueba para vitrina, bodega y bebidas
    conn = get_db_connection()
    with conn:
        conn.execute("UPDATE inventory SET stock = 20 WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')")
        conn.execute("UPDATE inventory SET stock = 50 WHERE item_key IN ('papas_raciones', 'caldo_raciones', 'arroz_raciones', 'frijoles_raciones', 'arepas_unidades')")
        conn.execute("UPDATE inventory SET stock = 30 WHERE item_key IN ('GAS-HIT-MAN-500', 'GAS-COL-250', 'GAS-MAN-250', 'GAS-TEA-DUR-500')")
        conn.execute("UPDATE inventory SET stock = 40 WHERE item_key IN ('pechuga_nevera', 'contramuslo_nevera', 'muslo_nevera', 'ala_nevera')")
        conn.execute("UPDATE inventory SET stock = 10 WHERE item_key = 'pollo_entero_crudo'")
    conn.close()
    return test_db

@pytest.fixture
def client():
    return TestClient(app)

# ==============================================================================
# 1. AUDITORÍA: SISTEMA DE 5 MESAS CON TICKETS PENDIENTES
# ==============================================================================

def test_audit_tables_initial_and_bounds_validation(client):
    """Verifica que existen exactamente las 5 mesas (1 a 5) y rechaza números fuera de rango."""
    res = client.get("/api/pos/tables")
    assert res.status_code == 200
    tables = res.json()
    assert len(tables) == 5
    for i in range(1, 6):
        t = next(tab for tab in tables if tab["table_number"] == i)
        assert t["status"] == "libre"
        assert t["order"] is None

    # Límites inválidos
    assert client.get("/api/pos/tables/0").status_code == 400
    assert client.get("/api/pos/tables/6").status_code == 400
    assert client.get("/api/pos/tables/-1").status_code == 400

def test_audit_open_table_and_add_items_realtime_inventory(client):
    """
    Verifica apertura de comanda en Mesa 1 con presas sueltas, combos y bebidas.
    Verifica que el inventario se descuenta en tiempo real de forma inmediata.
    """
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")
    p_14 = next(p for p in products if p["sku"] == "POL-14")
    p_hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    stock_init = client.get("/api/pos/stock-summary").json()
    pec_init = stock_init["pechuga_vitrina"]["stock"]
    mus_init = stock_init["muslo_vitrina"]["stock"]
    con_init = stock_init["contramuslo_vitrina"]["stock"]
    papas_init = stock_init["papas_raciones"]["stock"]
    hit_init = stock_init["GAS-HIT-MAN-500"]["stock"]

    # Agregar productos a Mesa 1: 1 Pechuga, 1 Combo 1/4 Pollo, 1 Gaseosa Hit
    payload = {
        "items": [
            {"product_id": p_pec["id"], "quantity": 1},
            {"product_id": p_14["id"], "quantity": 1},
            {"product_id": p_hit["id"], "quantity": 1}
        ]
    }
    res = client.post("/api/pos/tables/1/items", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["table_number"] == 1
    assert data["order"]["status"] == "abierta"
    assert data["order"]["items_count"] == 3
    expected_total = p_pec["price"] + p_14["price"] + p_hit["price"]
    assert data["order"]["total_amount"] == expected_total

    # Verificar descuento de inventario en tiempo real
    stock_after = client.get("/api/pos/stock-summary").json()
    assert stock_after["pechuga_vitrina"]["stock"] == pec_init - 1
    assert stock_after["muslo_vitrina"]["stock"] == mus_init - 1  # 1/4 pollo descuenta 1 muslo
    assert stock_after["contramuslo_vitrina"]["stock"] == con_init - 1  # 1/4 pollo descuenta 1 contramuslo
    assert stock_after["papas_raciones"]["stock"] == papas_init - 1  # 1/4 pollo descuenta 1 porcion papas
    assert stock_after["GAS-HIT-MAN-500"]["stock"] == hit_init - 1

def test_audit_prevent_overselling_on_table(client):
    """Verifica que el sistema rechaza pedidos a mesa si no hay suficiente stock en vitrina/nevera."""
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")

    # Hay 20 pechugas; intentar pedir 25
    res = client.post("/api/pos/tables/2/items", json={
        "items": [{"product_id": p_pec["id"], "quantity": 25}]
    })
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]

    # La mesa 2 debe permanecer libre y el inventario intacto
    t2 = client.get("/api/pos/tables/2").json()
    assert t2["status"] == "libre"

def test_audit_table_checkout_efectivo_change_and_shift(client):
    """
    Verifica cobro en efectivo en Mesa 3:
    - Validación de monto suficiente vs insuficiente.
    - Cambio exacto devuelto.
    - Generación de venta completada con código 'VTA-'.
    - Vinculación al turno activo de Santiago para cuadre de caja.
    - NO descuenta inventario por segunda vez.
    - Cierre del ticket de la mesa y retorno a estado libre.
    """
    # 1. Abrir turno de Santiago
    shift_res = client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 70000})
    assert shift_res.status_code == 200

    # 2. Asignar orden a Mesa 3
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")
    client.post("/api/pos/tables/3/items", json={"items": [{"product_id": p_pec["id"], "quantity": 2}]})

    total_order = p_pec["price"] * 2
    stock_before_pay = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]

    # 3. Rechazar pago insuficiente en efectivo
    insufficient = client.post("/api/pos/tables/3/checkout", json={
        "payment_method": "efectivo",
        "cash_received": total_order - 2000
    })
    assert insufficient.status_code == 400
    assert "insuficiente" in insufficient.json()["detail"].lower()

    # 4. Pago exitoso con billete mayor
    cash_received = total_order + 10000
    pay_res = client.post("/api/pos/tables/3/checkout", json={
        "payment_method": "efectivo",
        "cash_received": cash_received,
        "notes": "Cliente paga en caja central"
    })
    assert pay_res.status_code == 200
    data = pay_res.json()
    assert data["success"] is True
    assert data["table_number"] == 3
    assert data["total_amount"] == total_order
    assert data["cash_received"] == cash_received
    assert data["change_returned"] == 10000
    assert data["payment_method"] == "efectivo"
    assert data["sale_code"].startswith("VTA-")

    # 5. Inventario NO se vuelve a descontar tras pagar
    stock_after_pay = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    assert stock_after_pay == stock_before_pay

    # 6. Mesa 3 pasa a estar libre
    t3 = client.get("/api/pos/tables/3").json()
    assert t3["status"] == "libre"
    assert t3["order"] is None

    # 7. El turno activo refleja el ingreso de efectivo
    shift_cur = client.get("/api/cash/current-shift").json()["active_shift"]
    assert shift_cur["current_cash_sales"] == total_order
    assert shift_cur["current_expected_cash"] == 70000 + total_order

def test_audit_table_checkout_digital_and_datafono(client):
    """Verifica cobro en Mesa 4 con Nequi y Mesa 5 con Datáfono."""
    client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 50000})
    products = client.get("/api/pos/products").json()
    p_hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    # Mesa 4 -> Nequi
    client.post("/api/pos/tables/4/items", json={"items": [{"product_id": p_hit["id"], "quantity": 2}]})
    res4 = client.post("/api/pos/tables/4/checkout", json={"payment_method": "nequi_daviplata"})
    assert res4.status_code == 200
    assert res4.json()["payment_method"] == "nequi_daviplata"
    assert res4.json()["change_returned"] == 0

    # Mesa 5 -> Datáfono
    client.post("/api/pos/tables/5/items", json={"items": [{"product_id": p_hit["id"], "quantity": 1}]})
    res5 = client.post("/api/pos/tables/5/checkout", json={"payment_method": "datafono"})
    assert res5.status_code == 200
    assert res5.json()["payment_method"] == "datafono"
    assert res5.json()["change_returned"] == 0

    # Ambas mesas liberadas
    assert client.get("/api/pos/tables/4").json()["status"] == "libre"
    assert client.get("/api/pos/tables/5").json()["status"] == "libre"

def test_audit_table_cancellation_restores_stock(client):
    """Verifica que cancelar comanda en mesa devuelve íntegramente las existencias."""
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")
    stock_init = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]

    client.post("/api/pos/tables/1/items", json={"items": [{"product_id": p_pec["id"], "quantity": 4}]})
    assert client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"] == stock_init - 4

    cancel_res = client.post("/api/pos/tables/1/cancel", json={"reason": "Comensales decidieron retirarse"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["success"] is True

    # Stock restaurado
    assert client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"] == stock_init
    assert client.get("/api/pos/tables/1").json()["status"] == "libre"

# ==============================================================================
# 2. AUDITORÍA: HISTORIAL DE VENTAS POR HORAS Y ROTACIÓN DE PRESAS
# ==============================================================================

def test_audit_hourly_sales_metrics_and_modal_data(client):
    """
    Verifica /api/cash/hourly-sales con presas, combos, bebidas, tickets por hora,
    horas pico, ticket promedio y compatibilidad con modal de inspección.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")
    p_14 = next(p for p in products if p["sku"] == "POL-14")
    p_hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    # Insertar ventas simuladas en DB
    conn = get_db_connection()
    with conn:
        # Venta Hora 12: Mesa 1 (1 Pechuga sola)
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, notes, status)
            VALUES ('VTA-AUDIT-1201', ?, ?, '12:15:00', 12, 1, ?, 'efectivo', 'Consumo en Mesa 1', 'completada')
        """, (f"{today}T12:15:00", today, p_pec["price"]))
        s1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal, chosen_presa)
            VALUES (?, ?, ?, 1, ?, ?, 'Pechuga')
        """, (s1, p_pec["id"], p_pec["name"], p_pec["price"], p_pec["price"]))

        # Venta Hora 13: Mesa 2 (Combo 1/4 Pollo + Gaseosa)
        sub_14 = p_14["price"]
        sub_hit = p_hit["price"]
        tot_13 = sub_14 + sub_hit
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, notes, status)
            VALUES ('VTA-AUDIT-1301', ?, ?, '13:30:00', 13, 1, ?, 'nequi_daviplata', 'Consumo en Mesa 2', 'completada')
        """, (f"{today}T13:30:00", today, tot_13))
        s2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
            VALUES (?, ?, ?, 1, ?, ?)
        """, (s2, p_14["id"], p_14["name"], sub_14, sub_14))
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
            VALUES (?, ?, ?, 1, ?, ?)
        """, (s2, p_hit["id"], p_hit["name"], sub_hit, sub_hit))
    conn.close()

    # Consultar endpoint
    res = client.get(f"/api/cash/hourly-sales?date_str={today}")
    assert res.status_code == 200
    data = res.json()

    # Métricas globales
    assert data["total_tickets"] == 2
    assert data["total_sales"] == p_pec["price"] + tot_13
    assert data["total_gross_sales"] == data["total_sales"]
    assert data["average_ticket"] == int(data["total_sales"] / 2)
    assert data["date"] == today

    # Rotación de presas del día: 1 pechuga (s1) + 1 muslo + 1 contramuslo (combo 1/4) = 3 presas
    assert data["presas_breakdown"]["pechugas"] == 1
    assert data["presas_breakdown"]["muslos"] == 1
    assert data["presas_breakdown"]["contramuslos"] == 1
    assert data["presas_breakdown"]["alas"] == 0
    assert data["total_presas"] == 3
    assert data["total_presas_sold"]["total_presas"] == 3

    # Franja Hora 12
    h12 = next(h for h in data["hourly_sales"] if h["hour"] == 12)
    assert h12["tickets_count"] == 1
    assert h12["pechugas"] == 1
    assert h12["presas"]["pechugas"] == 1
    assert len(h12["tickets"]) == 1
    t12 = h12["tickets"][0]
    assert t12["ticket_code"] == "VTA-AUDIT-1201"
    assert t12["table_number"] == 1
    assert t12["payment_method"] == "efectivo"

    # Franja Hora 13 (Pico por mayor venta)
    h13 = next(h for h in data["hourly_sales"] if h["hour"] == 13)
    assert h13["tickets_count"] == 1
    assert h13["muslos"] == 1
    assert h13["contramuslos"] == 1
    assert h13["gaseosas_count"] == 1
    t13 = h13["tickets"][0]
    assert t13["ticket_code"] == "VTA-AUDIT-1301"
    assert t13["table_number"] == 2
    assert t13["payment_method"] == "nequi_daviplata"

    # Hora pico
    assert data["peak_hour"]["hour_label"] == "13:00 - 14:00"
    assert data["peak_hour"]["total_sales"] == tot_13

def test_audit_hourly_sales_and_detail_csv_exports(client):
    """
    Verifica exportación CSV de ventas por hora y detalle de tickets:
    - Presencia de UTF-8 BOM (\ufeff).
    - Delimitador punto y coma (;).
    - Encabezados correctos para abrir directamente en Microsoft Excel.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Exportación horaria agrupada
    res_h = client.get(f"/api/cash/hourly-sales/export?date_str={today}")
    assert res_h.status_code == 200
    assert res_h.headers["content-type"].startswith("text/csv")
    assert res_h.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    csv_h_text = res_h.content.decode("utf-8-sig")
    assert "Franja Horaria;Hora;Tickets Emitidos" in csv_h_text
    assert "Pechugas;Muslos;Contramuslos;Alas;Total Presas Pollo" in csv_h_text

    # 2. Exportación detalle granular
    res_d = client.get(f"/api/cash/sales-detail/export?date_str={today}")
    assert res_d.status_code == 200
    assert res_d.headers["content-type"].startswith("text/csv")
    assert res_d.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    csv_d_text = res_d.content.decode("utf-8-sig")
    assert "Codigo Venta;Metodo Pago;Producto;SKU;Categoria;Presa Elegida;Cantidad" in csv_d_text

# ==============================================================================
# 3. AUDITORÍA: FLUJO DE TURNO Y CAJA DIARIA (PERFIL SANTIAGO)
# ==============================================================================

def test_audit_open_shift_and_duplicate_prevention(client):
    """Verifica apertura de turno con base inicial y rechazo de apertura concurrente duplicada."""
    res1 = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 80000,
        "notes": "Apertura turno mañana"
    })
    assert res1.status_code == 200
    assert res1.json()["shift"]["status"] == "abierto"
    assert res1.json()["shift"]["base_inicial"] == 80000

    # Intentar abrir un segundo turno sin cerrar el primero
    res2 = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 50000
    })
    assert res2.status_code == 400
    assert "Ya existe un turno de caja abierto" in res2.json()["detail"]

def test_audit_cash_expenses_and_payment_source(client):
    """
    Verifica registro de gastos menores en efectivo (caja_efectivo) vs transferencias.
    Solo 'caja_efectivo' descuenta el efectivo esperado en el cajón físico.
    """
    shift = client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 100000}).json()["shift"]

    # Gasto 1: Insumos de emergencia pagados de la caja ($15.000)
    exp1 = client.post("/api/cash/expense", json={
        "amount": 15000,
        "category": "insumos",
        "concept": "Compra de bolsas y servilletas",
        "authorized_by": "Santiago",
        "payment_source": "caja_efectivo"
    })
    assert exp1.status_code == 200
    assert exp1.json()["expense"]["payment_source"] == "caja_efectivo"

    # Gasto 2: Pago a proveedor por transferencia bancaria ($40.000)
    exp2 = client.post("/api/cash/expense", json={
        "amount": 40000,
        "category": "servicios",
        "concept": "Pago transferencia internet",
        "authorized_by": "Alejandro",
        "payment_source": "banco_transferencia"
    })
    assert exp2.status_code == 200

    # Verificar que el cajón físico solo descuenta los $15.000 de caja
    status = client.get("/api/cash/current-shift").json()["active_shift"]
    assert status["current_expenses"] == 15000
    assert status["current_expected_cash"] == 100000 - 15000

def test_audit_3_step_closing_and_receipt_generation(client):
    """
    Verifica el Cierre de Turno de 3 Pasos:
    Paso 1: Conteo de efectivo en cajón (esperado vs real).
    Paso 2: Conteo físico de inventario (Santiago: vitrina, canecas de bodega, bebidas).
    Paso 3: Arqueo cruzado, emisión de comprobante REC-CIERRE-yymmdd-xxxx y cierre oficial.
    """
    # 1. Abrir turno con base $60.000
    client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 60000})

    # Venta de mostrador: 1 Pechuga $9.000 efectivo
    products = client.get("/api/pos/products").json()
    p_pec = next(p for p in products if p["sku"] == "POL-PEC")
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_pec["id"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })

    # Gasto menor en efectivo: $5.000
    client.post("/api/cash/expense", json={
        "amount": 5000,
        "category": "insumos",
        "concept": "Limones",
        "authorized_by": "Santiago",
        "payment_source": "caja_efectivo"
    })

    # Efectivo esperado = 60.000 + 9.000 - 5.000 = 64.000 COP
    sheet = client.get("/api/cash/closing-inventory-sheet").json()
    assert len(sheet["items"]) > 0

    # Simular conteos físicos idénticos al teórico (Cuadre perfecto)
    physical_counts = []
    for it in sheet["items"]:
        physical_counts.append({
            "item_key": it["item_key"],
            "physical_count": it["expected_stock"],
            "item_name": it["name"],
            "zone": it["zone"],
            "unit": it["unit"]
        })

    # Ejecutar cierre de turno
    close_res = client.post("/api/cash/close-shift", json={
        "actual_cash": 64000,
        "inventory_counts": physical_counts,
        "adjust_inventory_to_physical": True,
        "notes": "Cierre perfecto turno Santiago sin novedad"
    })
    assert close_res.status_code == 200
    cdata = close_res.json()
    assert cdata["success"] is True
    assert cdata["receipt_code"].startswith("REC-CIERRE-")
    assert cdata["cross_reconciliation_status"] == "cuadrada_total"
    assert cdata["cash_reconciliation"]["difference"] == 0
    assert cdata["inventory_reconciliation"]["total_missing_units"] == 0

    # Comprobante generado
    receipt_code = cdata["receipt_code"]

    # 4. Verificar consulta de comprobante individual
    rec_res = client.get(f"/api/cash/closing-receipt/{receipt_code}")
    assert rec_res.status_code == 200
    rec = rec_res.json()["receipt"]
    assert rec["receipt_code"] == receipt_code
    assert rec["cashier_name"] == "Santiago"
    assert rec["actual_cash"] == 64000
    assert rec["expected_cash"] == 64000

    # 5. Verificar Historial de Cierres (Endpoint para el botón 'HISTORIAL CIERRES')
    hist_res = client.get("/api/cash/closing-receipts")
    assert hist_res.status_code == 200
    receipts = hist_res.json()["receipts"]
    assert any(r["receipt_code"] == receipt_code for r in receipts)
