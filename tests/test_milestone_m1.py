import os
import tempfile
import concurrent.futures
import sqlite3
import pytest
from fastapi.testclient import TestClient
import app.database as database
from app.main import app

@pytest.fixture(autouse=True)
def isolated_test_db(monkeypatch):
    """
    Creates an isolated temporary SQLite database for each test
    to guarantee test idempotency and prevent test pollution.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        temp_db_path = tmp.name

    monkeypatch.setattr(database, "DB_PATH", temp_db_path)
    database.init_db()

    yield temp_db_path

    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
        wal_path = f"{temp_db_path}-wal"
        shm_path = f"{temp_db_path}-shm"
        if os.path.exists(wal_path):
            os.remove(wal_path)
        if os.path.exists(shm_path):
            os.remove(shm_path)
    except Exception:
        pass


def test_wal_and_pragma_configuration():
    """Verify WAL mode, synchronous=NORMAL, busy_timeout=10000, and foreign_keys=ON."""
    conn = database.get_db_connection()
    try:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal", f"Expected WAL mode, got {journal_mode}"

        synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
        # In SQLite: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
        assert synchronous == 1, f"Expected synchronous=NORMAL (1), got {synchronous}"

        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert busy_timeout == 10000, f"Expected busy_timeout=10000, got {busy_timeout}"

        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert foreign_keys == 1, f"Expected foreign_keys=ON (1), got {foreign_keys}"
    finally:
        conn.close()


def test_arepas_and_dry_goods_seeded():
    """Verify arepas_unidades, harina_apanar_kg, and aceite_fritura_lt are tracked in inventory."""
    conn = database.get_db_connection()
    try:
        arepa = conn.execute("SELECT * FROM inventory WHERE item_key = 'arepas_unidades'").fetchone()
        assert arepa is not None, "arepas_unidades must exist in inventory"
        assert arepa["stock"] >= 10, "arepas stock should be initialized"

        harina = conn.execute("SELECT * FROM inventory WHERE item_key = 'harina_apanar_kg'").fetchone()
        assert harina is not None, "harina_apanar_kg must exist in inventory"

        aceite = conn.execute("SELECT * FROM inventory WHERE item_key = 'aceite_fritura_lt'").fetchone()
        assert aceite is not None, "aceite_fritura_lt must exist in inventory"
    finally:
        conn.close()


def test_concurrent_checkout_no_collisions():
    """Verify that 50 concurrent checkout requests succeed with 0 UNIQUE constraint collisions."""
    client = TestClient(app)
    # Ensure ample stock of a simple item
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 1000 WHERE item_key = 'caldo_raciones'")
    conn.commit()
    conn.close()

    caldo = next(p for p in client.get("/api/pos/products").json() if p["sku"] == "POR-CALD")

    def make_sale(i):
        payload = {
            "items": [{"product_id": caldo["id"], "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        }
        res = client.post("/api/pos/checkout", json=payload)
        return res.status_code, res.json()

    # Execute 50 concurrent checkout requests across 10 threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(make_sale, range(50)))

    status_codes = [r[0] for r in results]
    assert all(code == 200 for code in status_codes), f"Some checkouts failed: {status_codes}"

    sale_codes = [r[1]["sale_code"] for r in results]
    assert len(sale_codes) == len(set(sale_codes)), "Duplicate sale_code detected under concurrency!"
    assert len(sale_codes) == 50


def test_concurrent_batch_timers_no_collisions():
    """Verify that 20 concurrent batch timer creations succeed with 0 UNIQUE constraint collisions."""
    client = TestClient(app)

    def start_batch(i):
        payload = {
            "stage": "salmuera",
            "total_presas": 16,
            "duration_hours": 6.0,
            "notes": f"Batch {i}"
        }
        res = client.post("/api/kitchen/batch-timer", json=payload)
        return res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(start_batch, range(20)))

    status_codes = [r[0] for r in results]
    assert all(code == 200 for code in status_codes), f"Some batch creations failed: {status_codes}"

    batch_codes = [r[1]["batch_code"] for r in results]
    assert len(batch_codes) == len(set(batch_codes)), "Duplicate batch_code detected under concurrency!"
    assert len(batch_codes) == 20


def test_non_negative_stock_floor_checkout():
    """Verify that sales with insufficient stock are rejected with HTTP 400 and stock remains non-negative."""
    client = TestClient(app)
    stock_before = client.get("/api/pos/stock-summary").json()
    ala_stock = stock_before["ala_vitrina"]["stock"]

    ala_prod = next(p for p in client.get("/api/pos/products").json() if p["sku"] == "POL-ALA")

    # Request more than available
    payload = {
        "items": [{"product_id": ala_prod["id"], "quantity": int(ala_stock) + 50}],
        "payment_method": "efectivo",
        "cash_received": 1000000
    }
    res = client.post("/api/pos/checkout", json=payload)
    assert res.status_code == 400, f"Expected HTTP 400, got {res.status_code}: {res.text}"
    assert "Stock insuficiente" in res.json()["detail"]

    # Verify stock did not drop
    stock_after = client.get("/api/pos/stock-summary").json()
    assert stock_after["ala_vitrina"]["stock"] == ala_stock


def test_symmetrical_cancel_sale_combos_and_sides():
    """
    Verify complete mathematical symmetry between checkout and cancel_sale
    for individual presas, combos (POL-14, POL-12, POL-ENT), almuerzos, and sides (including arepas).
    Initial Stock == Final Stock with 0 drift!
    """
    client = TestClient(app)
    products = client.get("/api/pos/products").json()

    # Find target products
    entero = next(p for p in products if p["sku"] == "POL-ENT")
    medio = next(p for p in products if p["sku"] == "POL-12")
    cuarto = next(p for p in products if p["sku"] == "POL-14")
    almuerzo = next(p for p in products if p["sku"] == "ALM-COMP")
    arepa = next(p for p in products if p["sku"] == "POR-AREP")
    coca = next(p for p in products if p["sku"] == "GAS-COC-400")

    # Ensure sufficient stock for all
    conn = database.get_db_connection()
    conn.execute("""
        UPDATE inventory SET stock = 100 
        WHERE item_key IN (
            'pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina',
            'papas_raciones', 'caldo_raciones', 'arroz_raciones', 'frijoles_raciones',
            'arepas_unidades', 'GAS-COC-400'
        )
    """)
    conn.commit()
    conn.close()

    stock_initial = client.get("/api/pos/stock-summary").json()

    # Create checkout with combos, lunch, arepas, soda
    checkout_payload = {
        "items": [
            {"product_id": entero["id"], "quantity": 1},
            {"product_id": medio["id"], "quantity": 1},
            {"product_id": cuarto["id"], "quantity": 1},
            {"product_id": almuerzo["id"], "quantity": 1, "chosen_presa": "Pechuga"},
            {"product_id": arepa["id"], "quantity": 2},
            {"product_id": coca["id"], "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 150000
    }

    res_checkout = client.post("/api/pos/checkout", json=checkout_payload)
    assert res_checkout.status_code == 200, f"Checkout failed: {res_checkout.text}"
    sale_data = res_checkout.json()
    sale_id = sale_data["sale_id"]

    # Verify inventory was decremented
    stock_during = client.get("/api/pos/stock-summary").json()
    # Pechuga: 2 (entero) + 1 (medio) + 0 (cuarto) + 1 (almuerzo) = 4
    assert stock_during["pechuga_vitrina"]["stock"] == stock_initial["pechuga_vitrina"]["stock"] - 4
    # Ala: 2 (entero) + 1 (medio) + 0 (cuarto) = 3
    assert stock_during["ala_vitrina"]["stock"] == stock_initial["ala_vitrina"]["stock"] - 3
    # Muslo: 2 (entero) + 1 (medio) + 1 (cuarto) = 4
    assert stock_during["muslo_vitrina"]["stock"] == stock_initial["muslo_vitrina"]["stock"] - 4
    # Contramuslo: 2 (entero) + 1 (medio) + 1 (cuarto) = 4
    assert stock_during["contramuslo_vitrina"]["stock"] == stock_initial["contramuslo_vitrina"]["stock"] - 4
    # Papas: 2 (entero) + 1 (medio) + 1 (cuarto) = 4
    assert stock_during["papas_raciones"]["stock"] == stock_initial["papas_raciones"]["stock"] - 4
    # Arepas: 2
    assert stock_during["arepas_unidades"]["stock"] == stock_initial["arepas_unidades"]["stock"] - 2
    # Soda: 1
    assert stock_during["GAS-COC-400"]["stock"] == stock_initial["GAS-COC-400"]["stock"] - 1

    # Cancel sale
    res_cancel = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res_cancel.status_code == 200, f"Cancel failed: {res_cancel.text}"

    # Verify inventory is 100% restored with ZERO discrepancy!
    stock_final = client.get("/api/pos/stock-summary").json()
    for item_key in stock_initial:
        assert stock_final[item_key]["stock"] == stock_initial[item_key]["stock"], (
            f"Discrepancy for {item_key}: initial={stock_initial[item_key]['stock']}, final={stock_final[item_key]['stock']}"
        )


def test_cancel_sale_validation_errors():
    """Verify that re-cancelling returns HTTP 400 and cancelling non-existent sale returns HTTP 404."""
    client = TestClient(app)
    caldo = next(p for p in client.get("/api/pos/products").json() if p["sku"] == "POR-CALD")

    # Make sale
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": caldo["id"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    sale_id = res.json()["sale_id"]

    # First cancel -> 200
    assert client.post(f"/api/pos/cancel-sale/{sale_id}").status_code == 200

    # Second cancel -> 400
    res_repeat = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res_repeat.status_code == 400
    assert "ya se encuentra anulada" in res_repeat.json()["detail"]

    # Non-existent sale -> 404
    res_404 = client.post("/api/pos/cancel-sale/999999")
    assert res_404.status_code == 404


def test_despiece_validation_and_mathematical_yield():
    """Verify that despiece validates bodega stock and yields exact 1->(2P, 2M, 2C, 2A, 2 Caldo)."""
    client = TestClient(app)

    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 5 WHERE item_key = 'pollo_entero_crudo'")
    conn.commit()
    conn.close()

    # Attempt to butcher 10 when only 5 exist
    res_fail = client.post("/api/kitchen/despiece", json={"whole_chickens": 10, "operator": "Santiago"})
    assert res_fail.status_code == 400
    assert "Stock insuficiente" in res_fail.json()["detail"]

    # Read vitrina stock before valid despiece
    stock_before = client.get("/api/pos/stock-summary").json()
    pechuga_before = stock_before["pechuga_vitrina"]["stock"]
    caldo_before = stock_before["caldo_raciones"]["stock"]

    # Butcher 3 chickens
    res_ok = client.post("/api/kitchen/despiece", json={"whole_chickens": 3, "operator": "Santiago"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["yields"]["pechugas"] == 6
    assert data["yields"]["muslos"] == 6
    assert data["yields"]["contramuslos"] == 6
    assert data["yields"]["alas"] == 6
    assert data["yields"]["caldo_raciones"] == 6

    # Verify bodega stock is 2
    conn = database.get_db_connection()
    bodega_stock = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()["stock"]
    assert bodega_stock == 2

    # Verify audit log in butchering_logs
    log = conn.execute("SELECT * FROM butchering_logs ORDER BY id DESC LIMIT 1").fetchone()
    assert log is not None
    assert log["whole_chickens"] == 3
    assert log["pechugas_yield"] == 6
    assert log["caldo_bases_yield"] == 6
    conn.close()

    # Verify vitrina stock increased
    stock_after = client.get("/api/pos/stock-summary").json()
    assert stock_after["pechuga_vitrina"]["stock"] == pechuga_before + 6
    assert stock_after["caldo_raciones"]["stock"] == caldo_before + 6


def test_fritura_timer_duration_and_dry_supplies():
    """Verify fritura stage looks up fritura_minutes (14m) and deducts harina and aceite."""
    client = TestClient(app)

    conn = database.get_db_connection()
    harina_before = conn.execute("SELECT stock FROM inventory WHERE item_key = 'harina_apanar_kg'").fetchone()["stock"]
    aceite_before = conn.execute("SELECT stock FROM inventory WHERE item_key = 'aceite_fritura_lt'").fetchone()["stock"]
    conn.close()

    res = client.post("/api/kitchen/batch-timer", json={"stage": "fritura", "total_presas": 16})
    assert res.status_code == 200
    data = res.json()

    # 14 minutes = ~0.2333 hours
    assert abs(data["duration_hours"] - (14.0 / 60.0)) < 0.001

    # Check that dry supplies were deducted
    conn = database.get_db_connection()
    harina_after = conn.execute("SELECT stock FROM inventory WHERE item_key = 'harina_apanar_kg'").fetchone()["stock"]
    aceite_after = conn.execute("SELECT stock FROM inventory WHERE item_key = 'aceite_fritura_lt'").fetchone()["stock"]
    conn.close()

    assert harina_after < harina_before
    assert aceite_after < aceite_before


def test_kitchen_batch_timer_input_validation():
    """Verify that start_batch_timer rejects invalid stages and non-positive presas with HTTP 400."""
    client = TestClient(app)

    # 1. Invalid stage string
    res_bad_stage = client.post("/api/kitchen/batch-timer", json={
        "stage": "horno",
        "total_presas": 16
    })
    assert res_bad_stage.status_code == 400
    assert "Etapa inválida" in res_bad_stage.json()["detail"]

    # 2. Zero presas
    res_zero_presas = client.post("/api/kitchen/batch-timer", json={
        "stage": "fritura",
        "total_presas": 0
    })
    assert res_zero_presas.status_code == 400
    assert "total de presas debe ser mayor a 0" in res_zero_presas.json()["detail"]

    # 3. Negative presas
    res_neg_presas = client.post("/api/kitchen/batch-timer", json={
        "stage": "salmuera",
        "total_presas": -10
    })
    assert res_neg_presas.status_code == 400

    # 4. Non-positive duration_hours
    res_bad_dur = client.post("/api/kitchen/batch-timer", json={
        "stage": "adobo",
        "total_presas": 12,
        "duration_hours": 0.0
    })
    assert res_bad_dur.status_code == 400

    # 5. Valid stage case-insensitivity
    res_valid = client.post("/api/kitchen/batch-timer", json={
        "stage": "FRITURA",
        "total_presas": 8
    })
    assert res_valid.status_code == 200
    assert res_valid.json()["stage"] == "fritura"


def test_sqlite_engine_check_constraint_rejects_negative_stock():
    """Verify that the SQLite engine enforces CHECK (stock >= 0) at the database layer."""
    conn = database.get_db_connection()
    try:
        # Direct attempt to set negative stock must trigger IntegrityError
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            conn.execute("UPDATE inventory SET stock = -1.0 WHERE item_key = 'pechuga_vitrina'")
        assert "CHECK constraint failed" in str(exc_info.value)
    finally:
        conn.close()

