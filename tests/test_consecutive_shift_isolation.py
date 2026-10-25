import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_consecutive_shift_isolation_resets_cash_and_sales_to_zero(helpers):
    """
    Verifica que al cerrar Turno 1 y abrir Turno 2 (incluso en la misma fecha):
    1. Turno 1 acumula sus ventas y gastos normalmente.
    2. Turno 1 se cierra satisfactoriamente.
    3. Al abrir Turno 2, los ingresos brutos, ventas en efectivo y gastos menores
       comienzan estrictamente en CEROS ($0).
    4. El efectivo esperado en Turno 2 es exactamente igual a la nueva base inicial.
    """
    # 1. Apertura Turno 1 con base $100.000
    r_open1 = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 100000,
        "notes": "Turno 1 Mañana"
    })
    assert r_open1.status_code == 200
    shift1_id = r_open1.json()["shift"]["id"]

    # 2. Venta en Turno 1: 1 Combo 1/2 Pollo ($20.000) en efectivo
    prod_id = helpers.get_product_id("POL-12")
    r_sale1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert r_sale1.status_code == 200

    # 3. Consultar daily-summary en Turno 1
    sum1 = client.get("/api/cash/daily-summary").json()
    assert sum1["cash_summary"]["gran_total"] == 20000
    assert sum1["cash_summary"]["efectivo"] == 20000
    assert sum1["cash_summary"]["total_tickets"] == 1
    assert sum1["cash_reconciliation"]["expected_cash"] == 120000

    # 4. Cerrar Turno 1 con conteo de $120.000 (Cuadre perfecto)
    r_close1 = client.post("/api/cash/close-shift", json={
        "shift_id": shift1_id,
        "actual_cash": 120000,
        "notes": "Cierre Turno 1 sin diferencias"
    })
    assert r_close1.status_code == 200
    assert r_close1.json()["reconciliation"]["difference"] == 0

    # 5. Apertura Turno 2 con base $150.000
    r_open2 = client.post("/api/cash/open-shift", json={
        "cashier_name": "Alejandro",
        "base_inicial": 150000,
        "notes": "Turno 2 Tarde"
    })
    assert r_open2.status_code == 200
    shift2_id = r_open2.json()["shift"]["id"]
    assert shift2_id != shift1_id

    # 6. Consultar daily-summary inmediatamente después de abrir Turno 2
    sum2 = client.get("/api/cash/daily-summary").json()
    
    # ¡DEBE ESTAR COMPLETAMENTE EN CEROS!
    assert sum2["cash_summary"]["gran_total"] == 0, f"Turno 2 debe tener $0 de ingresos brutos, pero tiene {sum2['cash_summary']['gran_total']}"
    assert sum2["cash_summary"]["efectivo"] == 0, f"Turno 2 debe tener $0 de ventas en efectivo, pero tiene {sum2['cash_summary']['efectivo']}"
    assert sum2["cash_summary"]["nequi_daviplata"] == 0
    assert sum2["cash_summary"]["datafono"] == 0
    assert sum2["cash_summary"]["total_tickets"] == 0, f"Turno 2 debe tener 0 tickets, pero tiene {sum2['cash_summary']['total_tickets']}"
    
    # Conciliación de Turno 2
    rec2 = sum2["cash_reconciliation"]
    assert rec2["base_inicial"] == 150000
    assert rec2["cash_sales"] == 0
    assert rec2["total_expenses"] == 0
    assert rec2["expected_cash"] == 150000
    assert rec2["actual_cash"] is None
    assert rec2["difference"] is None

    # Current shift endpoint también debe reportar $0 de ventas
    r_cur = client.get("/api/cash/current-shift").json()
    assert r_cur["active_shift"]["current_cash_sales"] == 0
    assert r_cur["active_shift"]["current_expenses"] == 0
    assert r_cur["active_shift"]["current_expected_cash"] == 150000
