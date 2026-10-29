import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection, init_db

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    test_db = str(tmp_path / "test_asadero_tables.db")
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("ADMIN_PIN", "4321")
    init_db()
    
    # Pre-cargar productos e inventario base para pruebas
    conn = get_db_connection()
    with conn:
        conn.execute("UPDATE inventory SET stock = 10 WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'papas_raciones')")
        conn.execute("UPDATE inventory SET stock = 10 WHERE item_key = 'GAS-HIT-MAN-500'")
        conn.execute("UPDATE inventory SET stock = 10 WHERE item_key = 'GAS-MAN-250'")
    conn.close()
    return test_db

@pytest.fixture
def client():
    return TestClient(app)

def test_tables_initial_status_all_libre(client):
    res = client.get("/api/pos/tables")
    assert res.status_code == 200
    tables = res.json()
    assert len(tables) == 5
    for idx, t in enumerate(tables, 1):
        assert t["table_number"] == idx
        assert t["status"] == "libre"
        assert t["order"] is None

def test_invalid_table_number_rejected(client):
    res_zero = client.get("/api/pos/tables/0")
    assert res_zero.status_code == 400
    assert "Número de mesa inválido" in res_zero.json()["detail"]

    res_six = client.get("/api/pos/tables/6")
    assert res_six.status_code == 400
    assert "Número de mesa inválido" in res_six.json()["detail"]

def test_add_items_to_table_deducts_stock_and_opens_table(client):
    # Buscar producto Pechuga y Gaseosa
    products = client.get("/api/pos/products").json()
    pec = next(p for p in products if p["sku"] == "POL-PEC")
    hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    # Stock inicial
    init_stock = client.get("/api/pos/stock-summary").json()
    init_pec = init_stock["pechuga_vitrina"]["stock"]
    init_hit = init_stock["GAS-HIT-MAN-500"]["stock"]

    # Adicionar a Mesa 2
    payload = {
        "items": [
            {"product_id": pec["id"], "quantity": 2},
            {"product_id": hit["id"], "quantity": 1}
        ]
    }
    res = client.post("/api/pos/tables/2/items", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["table_number"] == 2
    assert data["order"]["items_count"] == 2
    assert data["order"]["status"] == "abierta"
    expected_total = (pec["price"] * 2) + hit["price"]
    assert data["order"]["total_amount"] == expected_total

    # Verificar descuento inmediato en stock
    stock_after = client.get("/api/pos/stock-summary").json()
    assert stock_after["pechuga_vitrina"]["stock"] == init_pec - 2
    assert stock_after["GAS-HIT-MAN-500"]["stock"] == init_hit - 1

    # Verificar que GET /tables/2 reporta ocupada
    table2 = client.get("/api/pos/tables/2").json()
    assert table2["status"] == "ocupada"
    assert table2["order"]["total_amount"] == expected_total

def test_add_subsequent_items_to_open_table(client):
    products = client.get("/api/pos/products").json()
    pec = next(p for p in products if p["sku"] == "POL-PEC")
    hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    # Primera ronda: 1 pechuga
    client.post("/api/pos/tables/3/items", json={"items": [{"product_id": pec["id"], "quantity": 1}]})
    
    # Segunda ronda: 1 gaseosa adicional
    res2 = client.post("/api/pos/tables/3/items", json={"items": [{"product_id": hit["id"], "quantity": 1}]})
    assert res2.status_code == 200
    data = res2.json()
    assert data["order"]["items_count"] == 2
    assert data["order"]["total_amount"] == pec["price"] + hit["price"]

def test_add_items_insufficient_stock_fails_atomically(client):
    prod_pec = client.get("/api/pos/products").json()
    pec_id = next(p["id"] for p in prod_pec if p["sku"] == "POL-PEC")

    # Intentar pedir 99 pechugas (hay 10)
    res = client.post("/api/pos/tables/1/items", json={"items": [{"product_id": pec_id, "quantity": 99}]})
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]

    # Mesa 1 sigue libre
    t1 = client.get("/api/pos/tables/1").json()
    assert t1["status"] == "libre"

def test_cancel_table_order_restores_inventory(client):
    prod_pec = client.get("/api/pos/products").json()
    pec_id = next(p["id"] for p in prod_pec if p["sku"] == "POL-PEC")

    init_stock = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]

    # Poner 3 pechugas en Mesa 4
    client.post("/api/pos/tables/4/items", json={"items": [{"product_id": pec_id, "quantity": 3}]})
    assert client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"] == init_stock - 3

    # Cancelar Mesa 4
    cancel_res = client.post("/api/pos/tables/4/cancel", json={"reason": "Cliente se retiró"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["success"] is True

    # Stock restaurado al 100%
    assert client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"] == init_stock

    # Mesa 4 vuelve a estar libre
    t4 = client.get("/api/pos/tables/4").json()
    assert t4["status"] == "libre"

def test_checkout_table_cash_success_and_shift_reconciliation(client):
    # 1. Abrir turno de caja
    shift_res = client.post("/api/cash/open-shift", json={"cashier_name": "Santiago", "base_inicial": 50000})
    assert shift_res.status_code == 200
    shift_id = shift_res.json()["shift"]["id"]

    # 2. Agregar ítem a Mesa 5
    products = client.get("/api/pos/products").json()
    pec = next(p for p in products if p["sku"] == "POL-PEC")
    client.post("/api/pos/tables/5/items", json={"items": [{"product_id": pec["id"], "quantity": 2}]})

    stock_after_items = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    expected_total = pec["price"] * 2

    # 3. Cobrar Mesa 5 con $50.000 en efectivo
    cash_given = 50000
    checkout_res = client.post("/api/pos/tables/5/checkout", json={
        "payment_method": "efectivo",
        "cash_received": cash_given,
        "notes": "Comensales mesa 5"
    })
    assert checkout_res.status_code == 200
    data = checkout_res.json()
    assert data["success"] is True
    assert data["total_amount"] == expected_total
    assert data["cash_received"] == cash_given
    assert data["change_returned"] == cash_given - expected_total
    assert data["table_number"] == 5
    assert "VTA-" in data["sale_code"]

    # 4. Stock NO debe descontarse de nuevo (permanece intacto tras el checkout)
    stock_after_checkout = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    assert stock_after_checkout == stock_after_items

    # 5. Mesa 5 queda libre
    t5 = client.get("/api/pos/tables/5").json()
    assert t5["status"] == "libre"

    # 6. Cuadre de caja: el turno debe registrar exactamente el valor de la venta
    shift_info = client.get("/api/cash/current-shift").json()["active_shift"]
    assert shift_info["current_cash_sales"] == expected_total
    assert shift_info["current_expected_cash"] == 50000 + expected_total

def test_checkout_table_insufficient_cash_rejected(client):
    products = client.get("/api/pos/products").json()
    pec = next(p for p in products if p["sku"] == "POL-PEC")
    client.post("/api/pos/tables/1/items", json={"items": [{"product_id": pec["id"], "quantity": 1}]})

    # Total: pec["price"]. Se envía menos efectivo
    res = client.post("/api/pos/tables/1/checkout", json={"payment_method": "efectivo", "cash_received": pec["price"] - 1000})
    assert res.status_code == 400
    assert "insuficiente" in res.json()["detail"].lower()

def test_multiple_tables_simultaneously_active_and_independent(client):
    products = client.get("/api/pos/products").json()
    pec = next(p for p in products if p["sku"] == "POL-PEC")
    hit = next(p for p in products if p["sku"] == "GAS-HIT-MAN-500")

    # Mesa 1: 1 pechuga
    client.post("/api/pos/tables/1/items", json={"items": [{"product_id": pec["id"], "quantity": 1}]})
    # Mesa 2: 2 gaseosas Hit
    client.post("/api/pos/tables/2/items", json={"items": [{"product_id": hit["id"], "quantity": 2}]})

    tables = client.get("/api/pos/tables").json()
    t1 = next(t for t in tables if t["table_number"] == 1)
    t2 = next(t for t in tables if t["table_number"] == 2)
    t3 = next(t for t in tables if t["table_number"] == 3)

    assert t1["status"] == "ocupada"
    assert t1["order"]["total_amount"] == pec["price"]
    assert t2["status"] == "ocupada"
    assert t2["order"]["total_amount"] == hit["price"] * 2
    assert t3["status"] == "libre"

    # Cobrar Mesa 2 por Nequi
    res_nequi = client.post("/api/pos/tables/2/checkout", json={"payment_method": "nequi_daviplata", "notes": "Pago Nequi"})
    assert res_nequi.status_code == 200
    assert res_nequi.json()["payment_method"] == "nequi_daviplata"

    # Ahora Mesa 2 debe estar libre, y Mesa 1 seguir ocupada intacta
    tables_after = client.get("/api/pos/tables").json()
    t1_after = next(t for t in tables_after if t["table_number"] == 1)
    t2_after = next(t for t in tables_after if t["table_number"] == 2)
    assert t1_after["status"] == "ocupada"
    assert t2_after["status"] == "libre"

def test_cancel_nonexistent_table_order_rejected(client):
    res = client.post("/api/pos/tables/5/cancel")
    assert res.status_code == 400
    assert "No hay una orden abierta" in res.json()["detail"]

