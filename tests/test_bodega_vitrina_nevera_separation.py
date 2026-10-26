import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

client = TestClient(app)

def test_complete_bodega_to_vitrina_and_isolated_nevera_flow():
    """
    Test E2E de separación estricta:
    1. Pollo crudo se recibe en Bodega y se despresa en las 4 canecas de Bodega.
    2. Vitrina recibe presas fritas transferidas desde Bodega.
    3. Nevera contiene única y exclusivamente bebidas (gaseosas).
    4. Entrada de proveedor de 20 pollos enteros a Bodega incrementa instantáneamente el stock en 160 presas.
    """
    conn = get_db_connection()
    # Capturar stock previo en Bodega
    stocks_before = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    # 1. Entrada de 20 pollos enteros a Bodega
    res_sup = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola La Campiña S.A.S.",
        "invoice_number": "FAC-BOD-20-POLLOS",
        "item_name": "pollos_enteros_bodega",
        "location": "Bodega",
        "quantity": 20.0,
        "total_cost": 360000.0,
        "notes": "20 pollos enteros recibidos y despresados a las 4 canecas de Bodega"
    })
    assert res_sup.status_code == 200, res_sup.text
    data_sup = res_sup.json()
    assert data_sup["success"] is True
    assert data_sup["whole_chickens"] == 20.0
    assert data_sup["presas_added_each"] == 40.0
    assert data_sup["total_presas_added"] == 160.0
    assert data_sup["location"] == "Bodega"
    assert "recibidos y despresados en Bodega" in data_sup["message"]

    # 2. Verificar que las 4 canecas en Bodega aumentaron en 40 presas c/u
    conn = get_db_connection()
    stocks_after = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key LIKE '%nevera'").fetchall()
    }
    conn.close()

    for k in ["pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera"]:
        assert stocks_after[k] == stocks_before[k] + 40.0, f"Fallo en {k}: esperado {stocks_before[k] + 40}, actual {stocks_after[k]}"

    # 3. Trasladar 10 presas de cada tipo desde Bodega a Vitrina Caliente
    res_surtir = client.post("/api/kitchen/surtir-presas", json={
        "pechugas": 10,
        "muslos": 10,
        "contramuslos": 10,
        "alas": 10,
        "operator": "Santiago",
        "notes": "Pase de canecas en bodega a vitrina para almuerzo"
    })
    assert res_surtir.status_code == 200, res_surtir.text
    data_surtir = res_surtir.json()
    assert data_surtir["success"] is True

    # 4. Verificar hoja de arqueo / cierre físico:
    # - Bodega contiene las 4 canecas de pollo crudo
    # - Vitrina contiene las presas calientes
    # - Nevera contiene EXCLUSIVAMENTE bebidas/gaseosas (ninguna presa de pollo)
    res_sheet = client.get("/api/cash/closing-inventory-sheet")
    assert res_sheet.status_code == 200
    sheet = res_sheet.json()

    bodega_keys = [it["item_key"] for it in sheet.get("items", []) if it.get("zone") == "bodega"]
    nevera_keys = [it["item_key"] for it in sheet.get("items", []) if it.get("zone") == "nevera"]
    vitrina_keys = [it["item_key"] for it in sheet.get("items", []) if it.get("zone") == "vitrina"]

    # Las 4 canecas deben estar en bodega
    for k in ["pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera"]:
        assert k in bodega_keys, f"{k} debe estar categorizado en la zona Bodega"
        assert k not in nevera_keys, f"{k} NO debe estar en Nevera (separación de gaseosas)"

    # Nevera debe tener única y exclusivamente bebidas (inician con GAS-)
    assert len(nevera_keys) > 0
    for k in nevera_keys:
        assert k.startswith("GAS-"), f"Ítem {k} en Nevera no es una gaseosa/bebida!"

    # Vitrina debe tener las 4 presas de pollo frito
    for k in ["pechuga_vitrina", "contramuslo_vitrina", "muslo_vitrina", "ala_vitrina"]:
        assert k in vitrina_keys, f"{k} debe estar en Vitrina"
