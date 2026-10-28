import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

client = TestClient(app)

def reset_inventory_for_test():
    conn = get_db_connection()
    conn.execute("""
        UPDATE inventory 
        SET stock = 20.0 
        WHERE item_key IN (
            'pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 
            'ala_vitrina', 'papas_raciones', 'GAS-MAN-250', 'GAS-COL-250'
        )
    """)
    conn.commit()
    conn.close()

def test_quarter_chicken_custom_presas_deduction():
    reset_inventory_for_test()
    r = client.get("/api/pos/products")
    prods = {p["sku"]: p["id"] for p in r.json()}
    pol14_id = prods["POL-14"]

    # Cliente pide 1/4 de pollo con 2 Muslos (estilo Frisby)
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": pol14_id, "quantity": 1, "chosen_presa": "2 Muslos"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200, res.text
    data = res.json()

    conn = get_db_connection()
    muslo = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    contra = conn.execute("SELECT stock FROM inventory WHERE item_key = 'contramuslo_vitrina'").fetchone()["stock"]
    papas = conn.execute("SELECT stock FROM inventory WHERE item_key = 'papas_raciones'").fetchone()["stock"]
    conn.close()

    assert muslo == 18.0, "Debe descontar exactamente 2 muslos"
    assert contra == 20.0, "No debe descontar contramuslos si se escogieron 2 muslos"
    assert papas == 19.0, "Debe descontar 1 porción de papas"

def test_half_chicken_custom_presas_deduction_and_cancel():
    reset_inventory_for_test()
    r = client.get("/api/pos/products")
    prods = {p["sku"]: p["id"] for p in r.json()}
    pol12_id = prods["POL-12"]

    # Cliente pide 1/2 pollo con 3 Alas y 1 Pechuga
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": pol12_id, "quantity": 1, "chosen_presa": "1 Pechuga, 3 Alas"}],
        "payment_method": "efectivo",
        "cash_received": 40000
    })
    assert res.status_code == 200, res.text
    sale_id = res.json()["sale_id"]

    conn = get_db_connection()
    pechuga = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    alas = conn.execute("SELECT stock FROM inventory WHERE item_key = 'ala_vitrina'").fetchone()["stock"]
    muslos = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    conn.close()

    assert pechuga == 19.0
    assert alas == 17.0
    assert muslos == 20.0

    # Anular la venta y verificar restauración exacta
    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}", json={
        "pin": "4321",
        "reason": "Cliente cambió de opinión"
    })
    assert cancel_res.status_code == 200, cancel_res.text

    conn = get_db_connection()
    pechuga_restored = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    alas_restored = conn.execute("SELECT stock FROM inventory WHERE item_key = 'ala_vitrina'").fetchone()["stock"]
    audit = conn.execute("SELECT restored_presas_summary FROM sale_cancellation_audit WHERE sale_id = ?", (sale_id,)).fetchone()
    conn.close()

    assert pechuga_restored == 20.0
    assert alas_restored == 20.0
    assert "pechugas" in audit["restored_presas_summary"]

def test_combo_personal_deduction_and_cancel():
    reset_inventory_for_test()
    r = client.get("/api/pos/products")
    prods = {p["sku"]: p["id"] for p in r.json()}
    polper_id = prods.get("POL-PER")
    assert polper_id is not None, "El producto POL-PER debe existir en el catálogo"

    # Cliente compra Combo Personal con Muslo y Gaseosa Manzana 250ml
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": polper_id, "quantity": 1, "chosen_presa": "Muslo | Manzana 250ml"}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res.status_code == 200, res.text
    sale_id = res.json()["sale_id"]

    conn = get_db_connection()
    muslo = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    papas = conn.execute("SELECT stock FROM inventory WHERE item_key = 'papas_raciones'").fetchone()["stock"]
    manzana = conn.execute("SELECT stock FROM inventory WHERE item_key = 'GAS-MAN-250'").fetchone()["stock"]
    colombiana = conn.execute("SELECT stock FROM inventory WHERE item_key = 'GAS-COL-250'").fetchone()["stock"]
    conn.close()

    assert muslo == 19.0, f"Debe descontar 1 muslo de vitrina, actual: {muslo}"
    assert papas == 19.0, f"Debe descontar 1 porción de papas, actual: {papas}"
    assert manzana == 19.0, f"Debe descontar 1 Manzana 250ml, actual: {manzana}"
    assert colombiana == 20.0, f"No debe alterar Colombiana 250ml, actual: {colombiana}"

    # Anular la venta y verificar restauración simétrica
    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}", json={
        "pin": "4321",
        "reason": "Anulación de prueba combo personal"
    })
    assert cancel_res.status_code == 200, cancel_res.text

    conn = get_db_connection()
    muslo_restored = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    papas_restored = conn.execute("SELECT stock FROM inventory WHERE item_key = 'papas_raciones'").fetchone()["stock"]
    manzana_restored = conn.execute("SELECT stock FROM inventory WHERE item_key = 'GAS-MAN-250'").fetchone()["stock"]
    conn.close()

    assert muslo_restored == 20.0, "Muslo debe restaurarse a 20.0"
    assert papas_restored == 20.0, "Papas deben restaurarse a 20.0"
    assert manzana_restored == 20.0, "Manzana 250ml debe restaurarse a 20.0"

