import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

client = TestClient(app)

def test_ui_contains_sacar_pollo_elements():
    """Verifica que Mostrador y Caja contengan los botones y modales para sacar pollo."""
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "btnSacarPolloVitrina" in r_index.text
    assert "modalSacarPolloVitrina" in r_index.text
    assert "bodegaRawChickensDisplay" in r_index.text
    assert "bodegaRawChickensEquivDisplay" in r_index.text
    assert "pollos enteros" in r_index.text

    r_cash = client.get("/caja")
    assert r_cash.status_code == 200
    assert "btnSacarPolloCash" in r_cash.text
    assert "modalSacarPolloCash" in r_cash.text

def test_stock_summary_includes_bodega_chicken():
    """Verifica que /api/pos/stock-summary reporte el stock de bodega para pollos crudos."""
    res = client.get("/api/pos/stock-summary")
    assert res.status_code == 200
    data = res.json()
    assert "pollo_entero_crudo" in data
    assert data["pollo_entero_crudo"]["category"] == "bodega"
    assert "pechuga_vitrina" in data
    assert "muslo_vitrina" in data

def test_despiece_workflow_end_to_end():
    """Verifica la deducción atómica de bodega, adición a vitrina y conciliación en el cierre."""
    # 1. Ajustar bodega a 30 y vitrina a 0 para una prueba aislada
    conn = get_db_connection()
    conn.execute("UPDATE inventory SET stock = 30 WHERE item_key = 'pollo_entero_crudo'")
    conn.execute("UPDATE inventory SET stock = 0 WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')")
    conn.commit()
    conn.close()

    # 2. Sacar 5 pollos en la mañana
    res_batch1 = client.post("/api/kitchen/despiece", json={
        "whole_chickens": 5,
        "operator": "Turno Mañana",
        "notes": "Tanda mañana 5 pollos"
    })
    assert res_batch1.status_code == 200
    body1 = res_batch1.json()
    assert body1["success"] is True
    assert body1["yields"]["pechugas"] == 10
    assert body1["yields"]["total_presas"] == 40

    # Stock intermedio
    s1 = client.get("/api/pos/stock-summary").json()
    assert s1["pollo_entero_crudo"]["stock"] == 25.0
    assert s1["pechuga_vitrina"]["stock"] == 10.0
    assert s1["muslo_vitrina"]["stock"] == 10.0

    # 3. Sacar 1 pollo de refuerzo en la tarde
    res_batch2 = client.post("/api/kitchen/despiece", json={
        "whole_chickens": 1,
        "operator": "Turno Tarde",
        "notes": "Refuerzo tarde 1 pollo"
    })
    assert res_batch2.status_code == 200
    body2 = res_batch2.json()
    assert body2["yields"]["pechugas"] == 2
    assert body2["yields"]["total_presas"] == 8

    # Stock final
    s2 = client.get("/api/pos/stock-summary").json()
    assert s2["pollo_entero_crudo"]["stock"] == 24.0
    assert s2["pechuga_vitrina"]["stock"] == 12.0
    assert s2["muslo_vitrina"]["stock"] == 12.0
