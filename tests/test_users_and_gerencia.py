# -*- coding: utf-8 -*-
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from app.main import app
from app.database import get_db_connection, init_db

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    test_db = str(tmp_path / "test_gerencia.db")
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("ADMIN_PIN", "4321")
    init_db()
    return test_db

@pytest.fixture
def client():
    return TestClient(app)

def test_auth_users_and_login_validation(client):
    # 1. Listar usuarios activos
    res = client.get("/api/auth/users")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    usernames = [u["username"] for u in data["users"]]
    assert "santiago" in usernames
    assert "alejandro" in usernames

    # 2. Login Santiago con PIN correcto
    res_sant = client.post("/api/auth/login", json={"username": "santiago", "pin": "1234"})
    assert res_sant.status_code == 200
    assert res_sant.json()["user"]["role"] == "cajero"

    # 3. Login Alejandro con PIN correcto (1780)
    res_alejo = client.post("/api/auth/login", json={"username": "alejandro", "pin": "1780"})
    assert res_alejo.status_code == 200
    assert res_alejo.json()["user"]["role"] == "admin"

    # 4. Login rechazado con PIN incorrecto
    res_fail = client.post("/api/auth/login", json={"username": "alejandro", "pin": "9999"})
    assert res_fail.status_code == 401

def test_gerencia_html_view_accessible(client):
    res = client.get("/gerencia")
    assert res.status_code == 200
    assert "GERENCIA & LIBRO CONTABLE" in res.text
    assert "pinGateModal" in res.text

    res2 = client.get("/contabilidad")
    assert res2.status_code == 200

def test_accounting_ledger_and_expenses_lifecycle(client):
    today = datetime.now().strftime("%Y-%m-%d")
    month = today[:7]

    # 1. Registrar compra a proveedor pagada por Transferencia Bancaria (Nequi)
    res_exp1 = client.post("/api/accounting/expense", json={
        "date_str": today,
        "amount": 200000,
        "category": "compra_pollo",
        "concept": "35 pollos frescos MacPollo",
        "payment_source": "banco_transferencia",
        "recipient": "MacPollo",
        "receipt_number": "FAC-1001",
        "authorized_by": "Alejandro"
    })
    assert res_exp1.status_code == 200
    exp1_id = res_exp1.json()["expense_id"]

    # 2. Registrar gasto menor pagado en Efectivo de Caja
    res_exp2 = client.post("/api/accounting/expense", json={
        "date_str": today,
        "amount": 15000,
        "category": "insumos",
        "concept": "Hielo y condimentos urgentes",
        "payment_source": "caja_efectivo",
        "authorized_by": "Santiago"
    })
    assert res_exp2.status_code == 200
    exp2_id = res_exp2.json()["expense_id"]

    # 3. Registrar ingresos brutos manuales para el día
    res_inc = client.post("/api/accounting/daily-income", json={
        "date_str": today,
        "income_cash": 300000,
        "income_digital": 150000,
        "income_datafono": 50000,
        "notes": "Ventas del día con cierre cuadrado"
    })
    assert res_inc.status_code == 200

    # 4. Consultar libro contable (Ledger) del mes
    res_led = client.get(f"/api/accounting/ledger?month={month}")
    assert res_led.status_code == 200
    led_data = res_led.json()
    assert led_data["success"] is True

    # Buscar el día de hoy en el ledger
    day_entry = next((d for d in led_data["ledger"] if d["date_str"] == today), None)
    assert day_entry is not None
    assert day_entry["income_total"] == 500000
    assert day_entry["purchases_cogs"] == 200000
    assert day_entry["operating_expenses"] == 15000
    assert day_entry["total_expenses"] == 215000
    # Utilidad Neta = 500000 - 215000 = 285000
    assert day_entry["net_profit"] == 285000
    assert day_entry["net_margin_pct"] == round(285000 / 500000 * 100, 1)

    # Cruce de tesorería del día:
    # Efectivo: 300.000 ingresos - 15.000 egresos = 285.000
    assert day_entry["net_cash_drawer"] == 285000
    # Bancos/Nequi: (150.000 digital + 50.000 datafono) - 200.000 transferencia = 0
    assert day_entry["net_digital_balance"] == 0

    # 5. Probar eliminación de un gasto
    res_del = client.delete(f"/api/accounting/expense/{exp2_id}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Verificar que el gasto fue eliminado
    res_led_after = client.get(f"/api/accounting/ledger?month={month}")
    day_after = next((d for d in res_led_after.json()["ledger"] if d["date_str"] == today), None)
    assert day_after["operating_expenses"] == 0
    assert day_after["total_expenses"] == 200000
    assert day_after["net_profit"] == 300000

def test_sync_pos_day_into_accounting(client):
    today = datetime.now().strftime("%Y-%m-%d")

    # Insertar ventas simuladas en POS
    conn = get_db_connection()
    with conn:
        conn.execute("""
            INSERT INTO sales (sale_code, timestamp, date_str, time_str, hour_of_day, day_of_week, total_amount, payment_method, status)
            VALUES 
            ('VTA-SYNC-01', ?, ?, '12:00:00', 12, 3, 45000, 'efectivo', 'completada'),
            ('VTA-SYNC-02', ?, ?, '13:00:00', 13, 3, 35000, 'nequi_daviplata', 'completada'),
            ('VTA-SYNC-03', ?, ?, '14:00:00', 14, 3, 20000, 'datafono', 'completada')
        """, (f"{today}T12:00:00", today, f"{today}T13:00:00", today, f"{today}T14:00:00", today))

    # Ejecutar sincronización de ventas POS hacia contabilidad
    res_sync = client.post("/api/accounting/sync-pos-day", json={"date_str": today})
    assert res_sync.status_code == 200
    data = res_sync.json()
    assert data["success"] is True
    assert data["income"]["cash"] == 45000
    assert data["income"]["digital"] == 35000
    assert data["income"]["datafono"] == 20000
    assert data["income"]["total"] == 100000

def test_export_ledger_csv(client):
    month = datetime.now().strftime("%Y-%m")
    res = client.get(f"/api/accounting/export-ledger?month={month}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    content = res.text
    # Debe tener BOM UTF-8
    assert content.startswith("\ufeff")
    # Debe tener delimitador punto y coma
    assert ";" in content
    assert "LIBRO CONTABLE Y CRUCE FINANCIERO" in content
    assert "Total Ingresos Brutos" in content
    assert "Compras Mercancía (COGS)" in content

def test_accounting_detailed_categories_classification(client):
    test_date = "2026-10-28"
    month = "2026-10"

    # 1. Registrar egresos de cada una de las categorías de Materia Prima / Producción (COGS)
    cogs_categories = [
        ("compra_pollo", 120000, "15 pollos enteros"),
        ("compra_papas", 45000, "2 bultos de papas francesa"),
        ("compra_arepas", 20000, "Paquetes de arepas"),
        ("compra_gaseosas", 60000, "Pacas de gaseosas Postobón"),
        ("compra_aceite_harina", 50000, "Aceite y harina apanado"),
        ("compra_dotacion_empaques", 25000, "Guantes desechables y cajas para llevar"),
    ]
    expected_cogs_total = sum(item[1] for item in cogs_categories)

    for cat, amt, concept in cogs_categories:
        res = client.post("/api/accounting/expense", json={
            "date_str": test_date,
            "amount": amt,
            "category": cat,
            "concept": concept,
            "payment_source": "banco_transferencia",
            "authorized_by": "Alejandro"
        })
        assert res.status_code == 200

    # 2. Registrar egresos de Gastos Fijos / Operativos (OPEX)
    opex_categories = [
        ("nomina_turnos", 60000, "Jornal turno cocina"),
        ("arriendo", 50000, "Fracción arriendo local"),
        ("servicios_publicos", 30000, "Recibo energía"),
        ("fletes_transporte", 15000, "Flete transporte insumos"),
        ("aseo_mantenimiento", 10000, "Jabón y desinfectante"),
        ("otros_gastos", 5000, "Gasto vario menor"),
    ]
    expected_opex_total = sum(item[1] for item in opex_categories)

    for cat, amt, concept in opex_categories:
        res = client.post("/api/accounting/expense", json={
            "date_str": test_date,
            "amount": amt,
            "category": cat,
            "concept": concept,
            "payment_source": "caja_efectivo",
            "authorized_by": "Alejandro"
        })
        assert res.status_code == 200

    # 3. Registrar Retiro de Socios
    res_ret = client.post("/api/accounting/expense", json={
        "date_str": test_date,
        "amount": 40000,
        "category": "retiro_socio",
        "concept": "Adelanto utilidades socio",
        "payment_source": "banco_transferencia",
        "authorized_by": "Alejandro"
    })
    assert res_ret.status_code == 200

    # 4. Registrar los ingresos brutos del día (340.000 COP)
    res_inc = client.post("/api/accounting/daily-income", json={
        "date_str": test_date,
        "income_cash": 340000,
        "income_digital": 0,
        "income_datafono": 0,
        "notes": "Ventas reportadas 340.000 COP"
    })
    assert res_inc.status_code == 200

    # 5. Obtener ledger y verificar la segregación matemática exacta
    res_led = client.get(f"/api/accounting/ledger?month={month}")
    assert res_led.status_code == 200
    ledger_day = next((d for d in res_led.json()["ledger"] if d["date_str"] == test_date), None)
    assert ledger_day is not None

    assert ledger_day["income_total"] == 340000
    assert ledger_day["purchases_cogs"] == expected_cogs_total
    assert ledger_day["operating_expenses"] == expected_opex_total
    assert ledger_day["partner_withdrawals"] == 40000
    expected_total_exp = expected_cogs_total + expected_opex_total + 40000
    assert ledger_day["total_expenses"] == expected_total_exp
    assert ledger_day["net_profit"] == 340000 - expected_total_exp

def test_october_28_startup_audit_scenario(client):
    """
    Auditoría Certificada del 28 de Octubre (Arranque Don Pollo):
    1. 8 egresos iniciales ($1.569.505 COP)
    2. Ingresos brutos en efectivo ($340.000 COP)
    3. Utilidad neta resultante: -$1.229.505 COP
    4. Cruce de tesorería: Saldo en caja en mano +$340.000 COP intactos, Bancos -$1.569.505 COP
    5. Seguridad y no persistencia de PIN en gerencia
    6. Restricciones de costos para el perfil cajero (Santiago)
    """
    test_date = "2026-10-28"
    month = "2026-10"

    # Los 8 egresos de arranque exactamente descritos
    startup_expenses = [
        (463250, "compra_pollo", "30 unidades de pollo entero (MacPollo / arranque)", "MacPollo"),
        (280000, "compra_aceite_harina", "2 bidones de aceite de palma x 20L c/u", "Distribuidora Aceites"),
        (240300, "compra_gaseosas", "Compra de gaseosas Postobon", "Postobon"),
        (242000, "servicios_publicos", "Pipa de gas propano para freidoras (Pago hoy, entrega mañana)", "Distribuidora de Gas"),
        (121905, "compra_aceite_harina", "Bulto de harina As de Oros", "Molino / Distribuidora"),
        (105900, "compra_dotacion_empaques", "Factura salsas (sachet tomate, miel, rosada), servilletas Popular, vasos 7oz y 2 bolsas papas 2.5kg", "Distribuidora Desechables"),
        (99150, "compra_aceite_harina", "Maizena x 50 libras para apanado", "Distribuidora"),
        (17000, "compra_aceite_harina", "1 kilo de adobo Tecnas", "Tecnas")
    ]

    total_expected_expenses = sum(item[0] for item in startup_expenses)
    assert total_expected_expenses == 1569505

    for amt, cat, concept, recip in startup_expenses:
        res = client.post("/api/accounting/expense", json={
            "date_str": test_date,
            "amount": amt,
            "category": cat,
            "concept": concept,
            "payment_source": "banco_transferencia",
            "recipient": recip,
            "authorized_by": "Alejandro"
        })
        assert res.status_code == 200

    # Registrar ingreso bruto del 28 de Octubre ($340.000 COP en efectivo)
    res_inc = client.post("/api/accounting/daily-income", json={
        "date_str": test_date,
        "income_cash": 340000,
        "income_digital": 0,
        "income_datafono": 0,
        "notes": "Ingresos brutos del día (Arqueo real reportado)"
    })
    assert res_inc.status_code == 200

    # Consultar libro contable del mes
    res_led = client.get(f"/api/accounting/ledger?month={month}")
    assert res_led.status_code == 200
    day_28 = next((d for d in res_led.json()["ledger"] if d["date_str"] == test_date), None)
    assert day_28 is not None

    # Verificaciones Contables Exactas:
    assert day_28["income_total"] == 340000
    assert day_28["income_cash"] == 340000
    assert day_28["income_digital"] == 0
    assert day_28["purchases_cogs"] == 1327505
    assert day_28["operating_expenses"] == 242000
    assert day_28["total_expenses"] == 1569505
    assert day_28["net_profit"] == -1229505
    assert day_28["net_cash_drawer"] == 340000  # Efectivo en caja intacto
    assert day_28["net_digital_balance"] == -1569505  # Bancos / transferencias
    assert day_28["expenses_count"] == 8

    # Seguridad: Verificación de acceso y PIN
    # 1. Alejandro con 1780 -> Exitoso
    res_alejo = client.post("/api/auth/login", json={"username": "alejandro", "pin": "1780"})
    assert res_alejo.status_code == 200
    assert res_alejo.json()["user"]["role"] == "admin"

    # 2. PIN erróneo -> Rechazado
    res_wrong = client.post("/api/auth/login", json={"username": "alejandro", "pin": "0000"})
    assert res_wrong.status_code == 401

    # 3. Santiago con 1234 -> Rol cajero (no admin)
    res_sant = client.post("/api/auth/login", json={"username": "santiago", "pin": "1234"})
    assert res_sant.status_code == 200
    assert res_sant.json()["user"]["role"] == "cajero"

    # 4. Vista /gerencia exige pinGateModal y no guarda en storage
    res_gerencia = client.get("/gerencia")
    assert res_gerencia.status_code == 200
    assert "pinGateModal" in res_gerencia.text
    assert "localStorage" not in res_gerencia.text
    assert "sessionStorage" not in res_gerencia.text

