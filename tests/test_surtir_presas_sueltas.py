import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

@pytest.fixture
def client():
    return TestClient(app)

def test_surtir_presas_validation_rejects_zero(client):
    """Rechazar si no se envía al menos una presa."""
    res = client.post("/api/kitchen/surtir-presas", json={
        "pechugas": 0,
        "contramuslos": 0,
        "muslos": 0,
        "alas": 0
    })
    assert res.status_code == 400
    assert "al menos una presa" in res.json()["detail"].lower()

def test_surtir_presas_sueltas_success(client):
    """Surtir presas sueltas de la caneca abierta incrementa el stock de vitrina y registra en butchering_logs."""
    conn = get_db_connection()
    p_init = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    c_init = conn.execute("SELECT stock FROM inventory WHERE item_key = 'contramuslo_vitrina'").fetchone()["stock"]
    m_init = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    a_init = conn.execute("SELECT stock FROM inventory WHERE item_key = 'ala_vitrina'").fetchone()["stock"]
    conn.close()

    res = client.post("/api/kitchen/surtir-presas", json={
        "pechugas": 4,
        "contramuslos": 2,
        "muslos": 0,
        "alas": 0,
        "operator": "Santiago",
        "notes": "Refuerzo tarde pechugas y contramuslos"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["added"]["total"] == 6
    assert data["added"]["pechugas"] == 4
    assert data["added"]["contramuslos"] == 2

    # Verificar inventario actualizado
    conn = get_db_connection()
    p_now = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    c_now = conn.execute("SELECT stock FROM inventory WHERE item_key = 'contramuslo_vitrina'").fetchone()["stock"]
    m_now = conn.execute("SELECT stock FROM inventory WHERE item_key = 'muslo_vitrina'").fetchone()["stock"]
    a_now = conn.execute("SELECT stock FROM inventory WHERE item_key = 'ala_vitrina'").fetchone()["stock"]

    assert p_now == p_init + 4
    assert c_now == c_init + 2
    assert m_now == m_init
    assert a_now == a_init

    # Verificar butchering_logs
    log = conn.execute("SELECT * FROM butchering_logs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert log["whole_chickens"] == 0
    assert log["pechugas_yield"] == 4
    assert log["contramuslos_yield"] == 2
    assert log["notes"] == "Refuerzo tarde pechugas y contramuslos"

def test_surtir_presas_reflected_in_closing_sheet(client):
    """Verificar que la hoja de arqueo / concilación de cierre incluye las presas sueltas en internal_production."""
    # Surtir presas primero
    res_surtir = client.post("/api/kitchen/surtir-presas", json={
        "pechugas": 4,
        "contramuslos": 2,
        "muslos": 0,
        "alas": 0,
        "operator": "Santiago",
        "notes": "Refuerzo tarde pechugas y contramuslos"
    })
    assert res_surtir.status_code == 200

    res = client.get("/api/cash/closing-inventory-sheet")
    assert res.status_code == 200
    data = res.json()
    items = {item["item_key"]: item for item in data["items"]}
    
    assert "pechuga_vitrina" in items
    assert "contramuslo_vitrina" in items
    # internal_production debe ser >= a las presas surtidas
    assert items["pechuga_vitrina"]["internal_production"] >= 4
    assert items["contramuslo_vitrina"]["internal_production"] >= 2

def test_templates_contain_surtir_tabs_and_elements(client):
    """Verificar que ambas plantillas (index.html y cash.html) tienen los selectores de presas sueltas."""
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert 'tabBtnSurtirPresas' in res_index.text
    assert 'surtir_pechuga' in res_index.text
    assert 'panelSurtirPresas' in res_index.text

    res_cash = client.get("/caja")
    assert res_cash.status_code == 200
    assert 'tabBtnSurtirCashPresas' in res_cash.text
    assert 'surtir_cash_pechuga' in res_cash.text
    assert 'panelSurtirCashPresas' in res_cash.text
