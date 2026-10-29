import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection, init_db
from datetime import datetime

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    test_db = str(tmp_path / "test_accounting.db")
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("ADMIN_PIN", "4321")
    init_db()
    return test_db

@pytest.fixture
def client():
    return TestClient(app)

def test_hourly_sales_breakdown_and_presas_counts(client):
    # 1. Crear ventas directas en la base de datos simulando diferentes horas
    conn = get_db_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    with conn:
        # Venta a las 11:30 (Hora 11) - 2 pechugas
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, status)
            VALUES ('VTA-110001', ?, ?, '11:30:00', 11, 2, 18000, 'efectivo', 'completada')
        """, (f"{today}T11:30:00", today))
        sale1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Producto Pechuga
        p_pec = conn.execute("SELECT id FROM products WHERE sku = 'POL-PEC'").fetchone()[0]
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
            VALUES (?, ?, 'Pechuga Sola', 2, 9000, 18000)
        """, (sale1_id, p_pec))

        # Venta a las 12:15 (Hora 12) - 1/4 Pollo (1 muslo + 1 contramuslo) + 1 Gaseosa
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, status)
            VALUES ('VTA-120001', ?, ?, '12:15:00', 12, 2, 16500, 'nequi_daviplata', 'completada')
        """, (f"{today}T12:15:00", today))
        sale2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        p_14 = conn.execute("SELECT id FROM products WHERE sku = 'POL-14'").fetchone()[0]
        p_gas = conn.execute("SELECT id FROM products WHERE sku = 'GAS-COL-400'").fetchone()[0]
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
            VALUES (?, ?, '1/4 Pollo + Papas', 1, 13000, 13000)
        """, (sale2_id, p_14))
        conn.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal)
            VALUES (?, ?, 'Postobon Colombiana 400ml', 1, 3500, 3500)
        """, (sale2_id, p_gas))

    conn.close()

    # Consultar endpoint de ventas por horas
    res = client.get(f"/api/cash/hourly-sales?date_str={today}")
    assert res.status_code == 200
    data = res.json()

    assert data["date_str"] == today
    assert data["total_sales"] == 18000 + 16500
    assert data["total_tickets"] == 2

    # Verificar hora 11
    h11 = next(h for h in data["hours"] if h["hour_of_day"] == 11)
    assert h11["tickets_count"] == 1
    assert h11["total_sales"] == 18000
    assert h11["cash_sales"] == 18000
    assert h11["pechugas"] == 2
    assert h11["muslos"] == 0
    assert len(h11["tickets"]) == 1

    # Verificar hora 12
    h12 = next(h for h in data["hours"] if h["hour_of_day"] == 12)
    assert h12["tickets_count"] == 1
    assert h12["total_sales"] == 16500
    assert h12["digital_sales"] == 16500
    assert h12["muslos"] == 1
    assert h12["contramuslos"] == 1
    assert h12["gaseosas_count"] == 1

    # Presas totales del día
    assert data["presas_breakdown"]["pechugas"] == 2
    assert data["presas_breakdown"]["muslos"] == 1
    assert data["presas_breakdown"]["contramuslos"] == 1
    assert data["total_presas"] == 4

def test_hourly_sales_csv_export(client):
    today = datetime.now().strftime("%Y-%m-%d")
    res = client.get(f"/api/cash/hourly-sales/export?date_str={today}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in res.headers["content-disposition"]
    text = res.content.decode("utf-8-sig")
    assert "Franja Horaria" in text
    assert "Pechugas" in text
    assert "Total Presas Pollo" in text

def test_sales_detail_csv_export(client):
    today = datetime.now().strftime("%Y-%m-%d")
    res = client.get(f"/api/cash/sales-detail/export?date_str={today}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    text = res.content.decode("utf-8-sig")
    assert "Codigo Venta" in text
    assert "Presa Elegida" in text

def test_expense_payment_source_affects_cash_drawer_appropriately(client):
    # 1. Abrir turno con $50.000 base
    shift_res = client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 50000})
    assert shift_res.status_code == 200
    shift_id = shift_res.json()["shift"]["id"]

    # 2. Registrar gasto pagado en EFECTIVO de caja ($10.000)
    exp_cash_res = client.post("/api/cash/expense", json={
        "amount": 10000,
        "category": "compra_insumos",
        "concept": "Cilantro y limones",
        "authorized_by": "Santiago",
        "payment_source": "caja_efectivo"
    })
    assert exp_cash_res.status_code == 200
    assert exp_cash_res.json()["expense"]["payment_source"] == "caja_efectivo"

    # Verificar que el efectivo esperado en cajón baja a $40.000
    shift_info = client.get("/api/cash/current-shift").json()["active_shift"]
    assert shift_info["current_expected_cash"] == 50000 - 10000

    # 3. Registrar gasto pagado por TRANSFERENCIA BANCARIA / NEQUI ($50.000 de pollo)
    exp_bank_res = client.post("/api/cash/expense", json={
        "amount": 50000,
        "category": "compra_pollo",
        "concept": "Pollo crudo proveedor",
        "authorized_by": "Alejandro",
        "payment_source": "banco_transferencia"
    })
    assert exp_bank_res.status_code == 200

    # El cajón físico NO debe verse afectado por el pago de banco (sigue en $40.000)
    shift_info2 = client.get("/api/cash/current-shift").json()["active_shift"]
    assert shift_info2["current_expected_cash"] == 40000

def test_accounting_daily_and_closing_workflow(client):
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Crear venta en efectivo de $100.000 y digital de $50.000
    conn = get_db_connection()
    with conn:
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, status)
            VALUES ('VTA-ACC01', ?, ?, '12:00:00', 12, 2, 100000, 'efectivo', 'completada')
        """, (f"{today}T12:00:00", today))
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, status)
            VALUES ('VTA-ACC02', ?, ?, '13:00:00', 13, 2, 50000, 'nequi_daviplata', 'completada')
        """, (f"{today}T13:00:00", today))
    conn.close()

    # 2. Registrar egresos: $40.000 compra pollo (transferencia), $20.000 nómina (efectivo)
    client.post("/api/cash/expense", json={
        "amount": 40000, "category": "compra_pollo", "concept": "Pollo canal",
        "authorized_by": "Alejandro", "payment_source": "banco_transferencia"
    })
    client.post("/api/cash/expense", json={
        "amount": 20000, "category": "nomina_jornales", "concept": "Jornal Santiago",
        "authorized_by": "Alejandro", "payment_source": "caja_efectivo"
    })

    # 3. Consultar cruce contable
    acc_res = client.get(f"/api/cash/accounting-daily?date_str={today}")
    assert acc_res.status_code == 200
    data = acc_res.json()

    assert data["income"]["total"] == 150000
    assert data["income"]["efectivo"] == 100000
    assert data["income"]["nequi_daviplata"] == 50000

    assert data["expenses"]["total"] == 60000
    assert data["expenses"]["purchases_cogs"] == 40000
    assert data["expenses"]["operating_expenses"] == 20000
    assert data["expenses"]["expenses_cash"] == 20000
    assert data["expenses"]["expenses_digital"] == 40000

    # Utilidad neta: $150.000 - $60.000 = $90.000 COP
    assert data["pnl"]["gross_margin"] == 150000 - 40000 # $110.000
    assert data["pnl"]["net_profit"] == 90000
    assert data["pnl"]["net_margin_pct"] == 60.0

    # Cruce de tesorería
    assert data["treasury"]["cash_sales"] == 100000
    assert data["treasury"]["expenses_cash"] == 20000
    assert data["treasury"]["expected_cash_drawer"] == 100000 - 20000 # 80000
    assert data["treasury"]["digital_sales"] == 50000
    assert data["treasury"]["expenses_digital"] == 40000
    assert data["treasury"]["net_digital_balance"] == 10000

    # 4. Guardar Cierre Contable
    close_res = client.post("/api/cash/accounting-closing", json={
        "date_str": today,
        "closed_by": "Alejandro",
        "notes": "Cierre contable cuadrado perfecto"
    })
    assert close_res.status_code == 200
    assert close_res.json()["success"] is True
    assert "CC-" in close_res.json()["closing_code"]

    # 5. Exportar CSV del Cierre Contable
    csv_res = client.get(f"/api/cash/accounting-closing/export?date_str={today}")
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    csv_text = csv_res.content.decode("utf-8-sig")
    assert "CIERRE CONTABLE Y ESTADO FINANCIERO DIARIO" in csv_text
    assert "TOTAL INGRESOS BRUTOS" in csv_text
    assert "UTILIDAD NETA FINAL DEL DÍA" in csv_text
