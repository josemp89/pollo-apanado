import os
import tempfile
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
import app.database as database
from app.main import app

@pytest.fixture(autouse=True)
def isolated_test_db(monkeypatch):
    """
    Creates an isolated temporary SQLite database for each test.
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


def test_complex_workflow_and_closed_inventory_invariance():
    """
    Adversarial verification of closed inventory invariance across complex multi-step workflows:
    Despiece -> Frying batches -> Multiple sales (combos, individual presas, almuerzos, portions, sodas)
    -> Cancellations -> Re-orders.
    Invariant: Initial Stock + Entradas Despiece - Total Ventas Registradas + Ventas Anuladas == Final Physical Stock.
    """
    client = TestClient(app)

    # 1. Capture initial physical inventory
    conn = database.get_db_connection()
    initial_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    initial_stock = {r["item_key"]: float(r["stock"]) for r in initial_rows}
    conn.close()

    # Track inventory modifications according to mathematical formulas
    # delta[item_key] represents net change: + despiece - registered sales + cancelled sales
    expected_delta = {k: 0.0 for k in initial_stock}

    # Step 1: Despiece of 4 chickens
    despiece_chickens = 4
    res_despiece = client.post("/api/kitchen/despiece", json={
        "whole_chickens": despiece_chickens,
        "operator": "Santiago",
        "notes": "Lote inicial de la manana"
    })
    assert res_despiece.status_code == 200, f"Despiece failed: {res_despiece.text}"

    expected_delta["pollo_entero_crudo"] -= despiece_chickens
    expected_delta["pechuga_vitrina"] += 2.0 * despiece_chickens
    expected_delta["muslo_vitrina"] += 2.0 * despiece_chickens
    expected_delta["contramuslo_vitrina"] += 2.0 * despiece_chickens
    expected_delta["ala_vitrina"] += 2.0 * despiece_chickens
    expected_delta["caldo_raciones"] += 2.0 * despiece_chickens

    # Step 2: Frying batches (2 batches)
    # Batch 1: 16 presas
    res_batch1 = client.post("/api/kitchen/batch-timer", json={"stage": "fritura", "total_presas": 16})
    assert res_batch1.status_code == 200
    expected_delta["harina_apanar_kg"] -= round(16 * 0.025, 3)
    expected_delta["aceite_fritura_lt"] -= round(16 * 0.02, 3)

    # Batch 2: 8 presas
    res_batch2 = client.post("/api/kitchen/batch-timer", json={"stage": "fritura", "total_presas": 8})
    assert res_batch2.status_code == 200
    expected_delta["harina_apanar_kg"] -= round(8 * 0.025, 3)
    expected_delta["aceite_fritura_lt"] -= round(8 * 0.02, 3)

    # Get product IDs
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    # Helper function to place order and track required items
    def place_order(items_spec, pmethod="efectivo", cash=500000):
        payload_items = []
        for sku, qty, chosen in items_spec:
            item_obj = {"product_id": prods[sku], "quantity": qty}
            if chosen:
                item_obj["chosen_presa"] = chosen
            payload_items.append(item_obj)
        res = client.post("/api/pos/checkout", json={
            "items": payload_items,
            "payment_method": pmethod,
            "cash_received": cash
        })
        assert res.status_code == 200, f"Checkout failed: {res.text}"
        return res.json()["sale_id"]

    # Step 3: Diverse sales
    # Sale 1: Combos (POL-ENT x 1, POL-14 x 1) + Soda (GAS-COC-400 x 2)
    s1_id = place_order([
        ("POL-ENT", 1, None),
        ("POL-14", 1, None),
        ("GAS-COC-400", 2, None)
    ])
    # Expected deductions for S1:
    # POL-ENT: 2 pechugas, 2 alas, 2 muslos, 2 contramuslos, 2 papas
    # POL-14: 1 muslo, 1 contramuslo, 1 papas
    # GAS-COC-400: 2
    s1_deductions = {
        "pechuga_vitrina": 2.0, "ala_vitrina": 2.0, "muslo_vitrina": 3.0,
        "contramuslo_vitrina": 3.0, "papas_raciones": 3.0, "GAS-COC-400": 2.0
    }
    for k, v in s1_deductions.items():
        expected_delta[k] -= v

    # Sale 2: Combos to be cancelled later (POL-12 x 2)
    s2_id = place_order([("POL-12", 2, None)])
    # POL-12 x 2: 2 pechugas, 2 alas, 2 muslos, 2 contramuslos, 2 papas
    s2_deductions = {
        "pechuga_vitrina": 2.0, "ala_vitrina": 2.0, "muslo_vitrina": 2.0,
        "contramuslo_vitrina": 2.0, "papas_raciones": 2.0
    }
    for k, v in s2_deductions.items():
        expected_delta[k] -= v

    # Sale 3: Almuerzos Ejecutivos with distinct presas
    s3_id = place_order([
        ("ALM-COMP", 2, "Pechuga"),
        ("ALM-COMP", 1, "Muslo"),
        ("ALM-COMP", 1, "Ala"),
        ("ALM-COMP", 1, "Contramuslo")
    ])
    s3_deductions = {
        "pechuga_vitrina": 2.0, "muslo_vitrina": 1.0, "ala_vitrina": 1.0,
        "contramuslo_vitrina": 1.0, "caldo_raciones": 5.0, "arroz_raciones": 5.0,
        "frijoles_raciones": 5.0
    }
    for k, v in s3_deductions.items():
        expected_delta[k] -= v

    # Sale 4: Individual presas and Portions (to be cancelled later)
    s4_id = place_order([
        ("POL-PEC", 1, None),
        ("POL-ALA", 1, None),
        ("POR-AREP", 4, None),
        ("POR-PAPAS", 2, None),
        ("POR-CALD", 1, None)
    ])
    s4_deductions = {
        "pechuga_vitrina": 1.0, "ala_vitrina": 1.0, "arepas_unidades": 4.0,
        "papas_raciones": 2.0, "caldo_raciones": 1.0
    }
    for k, v in s4_deductions.items():
        expected_delta[k] -= v

    # Sale 5: Sodas
    s5_id = place_order([
        ("GAS-COL-400", 2, None),
        ("GAS-MAN-400", 1, None),
        ("GAS-ZER-400", 1, None)
    ])
    s5_deductions = {"GAS-COL-400": 2.0, "GAS-MAN-400": 1.0, "GAS-ZER-400": 1.0}
    for k, v in s5_deductions.items():
        expected_delta[k] -= v

    # Step 4: Cancellations of Sale 2 and Sale 4
    res_c2 = client.post(f"/api/pos/cancel-sale/{s2_id}")
    assert res_c2.status_code == 200, f"Cancel S2 failed: {res_c2.text}"
    # Restores s2_deductions
    for k, v in s2_deductions.items():
        expected_delta[k] += v

    res_c4 = client.post(f"/api/pos/cancel-sale/{s4_id}")
    assert res_c4.status_code == 200, f"Cancel S4 failed: {res_c4.text}"
    # Restores s4_deductions
    for k, v in s4_deductions.items():
        expected_delta[k] += v

    # Step 5: Re-orders
    s6_id = place_order([
        ("ALM-COMP", 1, "Pechuga"),
        ("POR-AREP", 2, None),
        ("GAS-COC-15L", 1, None)
    ])
    s6_deductions = {
        "pechuga_vitrina": 1.0, "caldo_raciones": 1.0, "arroz_raciones": 1.0,
        "frijoles_raciones": 1.0, "arepas_unidades": 2.0, "GAS-COC-15L": 1.0
    }
    for k, v in s6_deductions.items():
        expected_delta[k] -= v

    # Step 6: Verify Closed Inventory Invariance Formula
    # Final Stock == Initial Stock + expected_delta
    conn = database.get_db_connection()
    final_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    final_stock = {r["item_key"]: float(r["stock"]) for r in final_rows}
    conn.close()

    for item_key, init_val in initial_stock.items():
        expected_val = init_val + expected_delta[item_key]
        actual_val = final_stock[item_key]
        assert abs(actual_val - expected_val) < 1e-5, (
            f"Inventory Drift on '{item_key}': initial={init_val}, delta={expected_delta[item_key]}, "
            f"expected={expected_val}, actual={actual_val}"
        )


def test_break_system_checkout_greater_than_stock():
    """
    Attempt checkouts exceeding available stock under various permutations:
    1. Single item exceeding stock
    2. Multi-item cart where one item exceeds stock (asserts rollback)
    3. Combo exceeding stock of shared component (papas)
    4. Aggregated items of same product in cart exceeding stock
    """
    client = TestClient(app)
    stock = client.get("/api/pos/stock-summary").json()
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    # 1. Single item exceeding stock
    ala_stock = stock["ala_vitrina"]["stock"]
    res1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-ALA"], "quantity": int(ala_stock) + 1}],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert res1.status_code == 400
    assert "Stock insuficiente" in res1.json()["detail"]

    # 2. Multi-item cart where first is valid, second exceeds
    pec_stock = stock["pechuga_vitrina"]["stock"]
    res2 = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["POL-PEC"], "quantity": 1},
            {"product_id": prods["POL-ALA"], "quantity": int(ala_stock) + 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert res2.status_code == 400
    # Assert rollback: pechuga was NOT deducted
    stock_after2 = client.get("/api/pos/stock-summary").json()
    assert stock_after2["pechuga_vitrina"]["stock"] == pec_stock

    # 3. Combo exceeding component stock
    # Set papas to 1
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 1 WHERE item_key = 'papas_raciones'")
    conn.commit()
    conn.close()

    # POL-ENT requires 2 papas
    res3 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-ENT"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert res3.status_code == 400
    assert "Stock insuficiente para 'Papas a la Francesa Disponibles'" in res3.json()["detail"]

    # 4. Aggregated items of same product in cart exceeding stock
    # Set arepas to 3
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 3 WHERE item_key = 'arepas_unidades'")
    conn.commit()
    conn.close()

    res4 = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["POR-AREP"], "quantity": 2},
            {"product_id": prods["POR-AREP"], "quantity": 2}
        ],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert res4.status_code == 400
    assert "Stock insuficiente para 'Arepas Disponibles'" in res4.json()["detail"]


def test_break_system_cancellation_edge_cases():
    """
    Attempt adversarial sale cancellations:
    - Non-existent sale ID
    - Negative sale ID
    - Sale ID 0
    - Re-cancellation (double and triple cancel)
    """
    client = TestClient(app)
    caldo_prod = next(p for p in client.get("/api/pos/products").json() if p["sku"] == "POR-CALD")

    # Non-existent
    res_none = client.post("/api/pos/cancel-sale/999999")
    assert res_none.status_code == 404
    assert "no encontrada" in res_none.json()["detail"]

    # Negative ID
    res_neg = client.post("/api/pos/cancel-sale/-1")
    assert res_neg.status_code == 404

    # ID 0
    res_zero = client.post("/api/pos/cancel-sale/0")
    assert res_zero.status_code == 404

    # Create valid sale
    res_sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": caldo_prod["id"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    sale_id = res_sale.json()["sale_id"]

    # First cancel -> 200
    res_c1 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res_c1.status_code == 200

    # Second cancel -> 400
    res_c2 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res_c2.status_code == 400
    assert "ya se encuentra anulada" in res_c2.json()["detail"]

    # Third cancel -> 400
    res_c3 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res_c3.status_code == 400
    assert "ya se encuentra anulada" in res_c3.json()["detail"]


def test_break_system_despiece_edge_cases():
    """
    Attempt adversarial despiece inputs:
    - 0 chickens
    - Negative chickens
    - More chickens than available in bodega
    - Exact available stock
    - Subsequent despiece when stock is 0
    """
    client = TestClient(app)

    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 3 WHERE item_key = 'pollo_entero_crudo'")
    conn.commit()
    conn.close()

    # 0 chickens
    res0 = client.post("/api/kitchen/despiece", json={"whole_chickens": 0})
    assert res0.status_code == 400

    # Negative chickens
    res_neg = client.post("/api/kitchen/despiece", json={"whole_chickens": -3})
    assert res_neg.status_code == 400

    # More than available
    res_over = client.post("/api/kitchen/despiece", json={"whole_chickens": 4})
    assert res_over.status_code == 400
    assert "Stock insuficiente" in res_over.json()["detail"]

    # Exact stock (3 chickens)
    res_exact = client.post("/api/kitchen/despiece", json={"whole_chickens": 3})
    assert res_exact.status_code == 200

    conn = database.get_db_connection()
    stock_now = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()["stock"]
    conn.close()
    assert stock_now == 0

    # Subsequent despiece when stock is 0
    res_zero_stock = client.post("/api/kitchen/despiece", json={"whole_chickens": 1})
    assert res_zero_stock.status_code == 400
    assert "Stock insuficiente" in res_zero_stock.json()["detail"]


def test_break_system_checkout_validation_defects():
    """
    Adversarial test exploring cart item validation defects:
    1. Quantity <= 0 (negative or zero)
    2. Invalid chosen_presa for Almuerzo Completo
    3. Missing items list
    """
    client = TestClient(app)
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    # Missing items list
    res_empty = client.post("/api/pos/checkout", json={"items": [], "payment_method": "efectivo"})
    assert res_empty.status_code == 400

    # Invalid chosen_presa
    res_bad_presa = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["ALM-COMP"], "quantity": 1, "chosen_presa": "Pescuezo"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_bad_presa.status_code == 400
    assert "no está registrado en el inventario" in res_bad_presa.json()["detail"]

    # Negative quantity in checkout: does it reject with HTTP 400?
    res_neg_qty = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-PEC"], "quantity": -5}],
        "payment_method": "efectivo",
        "cash_received": 0
    })
    # If the system permits negative quantity, this assertion documents the vulnerability
    assert res_neg_qty.status_code == 400, (
        f"CRITICAL VULNERABILITY: Checkout accepted negative quantity (-5)! "
        f"Status: {res_neg_qty.status_code}, Response: {res_neg_qty.text}"
    )


def test_break_system_concurrent_cancel_sale_race_condition():
    """
    Adversarial test: Fire 10 concurrent cancel requests for the SAME sale.
    Expectation: Exactly 1 request succeeds (HTTP 200), remaining 9 get HTTP 400.
    Inventory must be restored EXACTLY once with 0 duplication!
    """
    client = TestClient(app)
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    stock_initial = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]

    # Make sale of 2 pechugas
    res_sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-PEC"], "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 30000
    })
    assert res_sale.status_code == 200
    sale_id = res_sale.json()["sale_id"]

    # 10 concurrent cancellations of the same sale_id
    def cancel_call(i):
        r = client.post(f"/api/pos/cancel-sale/{sale_id}")
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(cancel_call, range(10)))

    # Only 1 cancel must succeed!
    success_count = statuses.count(200)
    assert success_count == 1, (
        f"RACE CONDITION IN CANCEL_SALE: Expected exactly 1 success, but {success_count} succeeded! "
        f"Statuses: {statuses}"
    )

    stock_final = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    assert stock_final == stock_initial, (
        f"INVENTORY DUPLICATION DETECTED: Initial stock was {stock_initial}, but after concurrent cancels "
        f"stock is {stock_final} (discrepancy: +{stock_final - stock_initial})!"
    )


def test_break_system_concurrent_competing_checkout_stock_floor():
    """
    Adversarial test: 10 concurrent checkouts competing for 3 available pechugas (1 pechuga each).
    Expectation: Exactly 3 succeed (200), exactly 7 fail with HTTP 400.
    Final stock must be exactly 0.0, never negative.
    """
    client = TestClient(app)
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 3 WHERE item_key = 'pechuga_vitrina'")
    conn.commit()
    conn.close()

    def attempt_buy(i):
        r = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prods["POL-PEC"], "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 15000
        })
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(attempt_buy, range(10)))

    successes = statuses.count(200)
    failures = statuses.count(400)

    assert successes == 3, f"Expected 3 successes, got {successes}. Statuses: {statuses}"
    assert failures == 7, f"Expected 7 failures, got {failures}. Statuses: {statuses}"

    final_stock = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    assert final_stock == 0.0, f"Expected final stock 0.0, got {final_stock}"


def test_break_system_concurrent_competing_despiece_stock_floor():
    """
    Adversarial test: 10 concurrent despiece requests competing for 3 whole chickens in bodega (1 chicken each).
    Expectation: Exactly 3 succeed (200), exactly 7 fail with HTTP 400.
    Final bodega chicken stock must be exactly 0.0, never negative.
    Total pechugas yielded must be exactly 6.0.
    """
    client = TestClient(app)

    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 3 WHERE item_key = 'pollo_entero_crudo'")
    conn.execute("UPDATE inventory SET stock = 0 WHERE item_key = 'pechuga_vitrina'")
    conn.commit()
    conn.close()

    def attempt_despiece(i):
        r = client.post("/api/kitchen/despiece", json={
            "whole_chickens": 1,
            "operator": f"Santiago_{i}"
        })
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(attempt_despiece, range(10)))

    successes = statuses.count(200)
    failures = statuses.count(400)

    assert successes == 3, f"Expected 3 successes, got {successes}. Statuses: {statuses}"
    assert failures == 7, f"Expected 7 failures, got {failures}. Statuses: {statuses}"

    conn = database.get_db_connection()
    final_bodega = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()["stock"]
    final_pechugas = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    conn.close()

    assert final_bodega == 0.0, f"Expected final bodega stock 0.0, got {final_bodega}"
    assert final_pechugas == 6.0, f"Expected 6 pechugas yield, got {final_pechugas}"
