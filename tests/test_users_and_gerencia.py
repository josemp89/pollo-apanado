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

    # 3. Login Alejandro con PIN correcto
    res_alejo = client.post("/api/auth/login", json={"username": "alejandro", "pin": "4321"})
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
