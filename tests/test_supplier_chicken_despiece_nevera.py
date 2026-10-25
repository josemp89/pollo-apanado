import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

client = TestClient(app)

def test_supplier_chicken_entry_automatically_despresas_into_nevera_canecas():
    """
    Verifica que al registrar una entrada de proveedor en cantidad de pollos enteros para Nevera:
    1. Se registre la factura en merchandise_entries.
    2. Se convierta automáticamente en 8 presas por pollo (2P, 2C, 2M, 2A).
    3. Se sumen a las 4 canecas de Nevera.
    4. Se refleje en la conciliación de cierre de caja (supplier_entries = 2 * pollos).
    """
    conn = get_db_connection()
    # Capturar stock previo
    stocks_before = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    # 1. Registrar entrada de 10 pollos enteros
    res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola La Campiña S.A.S.",
        "invoice_number": "FAC-POLLO-7788",
        "item_name": "pollos_enteros_nevera",
        "location": "Nevera",
        "quantity": 10.0,
        "total_cost": 180000.0,
        "notes": "10 pollos recibidos y despresados directamente a canecas"
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["whole_chickens"] == 10.0
    assert data["presas_added_each"] == 20.0
    assert data["total_presas_added"] == 80.0
    assert "10 pollos enteros recibidos y despresados en Nevera" in data["message"]

    # 2. Verificar que las 4 canecas aumentaron exactamente en 20 presas c/u
    conn = get_db_connection()
    stocks_after = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    for k in ["pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera"]:
        assert stocks_after[k] == stocks_before[k] + 20.0, f"Fallo en {k}: esperado {stocks_before[k] + 20}, actual {stocks_after[k]}"

    # 3. Verificar que la conciliación de cierre reporte las entradas de proveedores por presas
    r_sheet = client.get("/api/cash/closing-inventory-sheet")
    assert r_sheet.status_code == 200
    sheet = r_sheet.json()
    nevera_items = {item["item_key"]: item for item in sheet.get("items", []) if item.get("zone") == "nevera"}

    # Cada presa de nevera debe registrar al menos las 20 presas del proveedor
    for k in ["pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera"]:
        assert k in nevera_items, f"{k} no encontrado en la hoja de cierre"
        assert nevera_items[k]["supplier_entries"] >= 20.0


def test_supplier_chicken_with_emoji_or_bodega_location_still_despresas_to_nevera():
    """
    Verifica que si el usuario ingresa con nombre de emoji '🍗 Pollos Enteros' o deja ubicación 'Bodega',
    el sistema infaliblemente reconozca que es pollo y lo desprese a las canecas de Nevera (+2P, +2C, +2M, +2A).
    """
    conn = get_db_connection()
    stocks_before = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola Central",
        "invoice_number": "FAC-EMOJI-20",
        "item_name": "🍗 Pollos Enteros",
        "location": "Bodega",
        "quantity": 20.0,
        "total_cost": 300000.0,
        "notes": "Entrada con emoji y ubicación Bodega por omisión de usuario"
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["whole_chickens"] == 20.0
    assert data["presas_added_each"] == 40.0
    assert data["total_presas_added"] == 160.0

    conn = get_db_connection()
    stocks_after = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    for k in ["pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera"]:
        assert stocks_after[k] == stocks_before[k] + 40.0, f"Fallo en {k}: esperado {stocks_before[k] + 40}, actual {stocks_after[k]}"

