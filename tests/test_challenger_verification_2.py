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


def test_adversarial_zero_and_negative_cart_quantities():
    """
    Challenger 2 Verification:
    Verify that negative and zero item quantities are strictly rejected with HTTP 400 across all product types:
    - Zero quantity alone (0)
    - Negative quantity alone (-1, -100)
    - Mixed cart: valid item + zero quantity item
    - Mixed cart: valid item + negative quantity item
    - Zero/negative on combos, almuerzos, portions, sodas
    Verify atomic rejection: NO inventory is deducted for any item in a rejected cart.
    """
    client = TestClient(app)
    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    # Capture initial stock state
    conn = database.get_db_connection()
    init_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    initial_stock = {r["item_key"]: float(r["stock"]) for r in init_rows}
    conn.close()

    # 1. Zero quantity alone for a single presa
    res_zero = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-PEC"], "quantity": 0}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res_zero.status_code == 400, f"Expected 400 for qty=0, got {res_zero.status_code}: {res_zero.text}"

    # 2. Negative quantity alone for a combo
    res_neg_combo = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-ENT"], "quantity": -1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res_neg_combo.status_code == 400, f"Expected 400 for negative combo qty, got {res_neg_combo.status_code}"

    # 3. Zero quantity for Almuerzo Completo
    res_zero_alm = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["ALM-COMP"], "quantity": 0, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_zero_alm.status_code == 400, f"Expected 400 for zero almuerzo qty, got {res_zero_alm.status_code}"

    # 4. Negative quantity for drink
    res_neg_drink = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["GAS-COC-400"], "quantity": -10}],
        "payment_method": "efectivo",
        "cash_received": 0
    })
    assert res_neg_drink.status_code == 400, f"Expected 400 for negative drink qty, got {res_neg_drink.status_code}"

    # 5. Mixed cart: valid item (POL-PEC x 1) + zero item (POR-PAPAS x 0)
    res_mixed_zero = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["POL-PEC"], "quantity": 1},
            {"product_id": prods["POR-PAPAS"], "quantity": 0}
        ],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_mixed_zero.status_code == 400, f"Expected 400 for mixed cart with zero qty, got {res_mixed_zero.status_code}"

    # 6. Mixed cart: valid item (POL-14 x 1) + negative item (POR-AREP x -2)
    res_mixed_neg = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["POL-14"], "quantity": 1},
            {"product_id": prods["POR-AREP"], "quantity": -2}
        ],
        "payment_method": "efectivo",
        "cash_received": 30000
    })
    assert res_mixed_neg.status_code == 400, f"Expected 400 for mixed cart with neg qty, got {res_mixed_neg.status_code}"

    # Verify that NO stock was mutated by any of the rejected attempts
    conn = database.get_db_connection()
    after_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    after_stock = {r["item_key"]: float(r["stock"]) for r in after_rows}
    conn.close()

    for k, v in initial_stock.items():
        assert after_stock[k] == v, f"Stock leaked/modified on item {k}: before={v}, after={after_stock[k]}"


def test_adversarial_stress_closed_inventory_invariance_across_all_items():
    """
    Challenger 2 Verification:
    Stress-test closed inventory formula across 100% of all items in inventory table:
    Initial Stock + Entradas por Despiece - Ventas Netas Registradas == Final Physical Stock.
    Runs interleaved despieces, batch frying, multi-product checkouts, and cancellations
    concurrently across threads to stress SQLite WAL, transactions, and inventory math.
    """
    client = TestClient(app)

    # Capture initial stock across ALL inventory items
    conn = database.get_db_connection()
    init_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    all_item_keys = [r["item_key"] for r in init_rows]
    initial_stock = {r["item_key"]: float(r["stock"]) for r in init_rows}
    conn.close()

    prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

    # Initialize tracking of mathematical delta per item
    # Invariant: Final Physical Stock == Initial Stock + delta
    delta = {k: 0.0 for k in all_item_keys}

    # 1. First Despiece: 5 chickens
    r = client.post("/api/kitchen/despiece", json={"whole_chickens": 5, "operator": "Audit_1"})
    assert r.status_code == 200
    delta["pollo_entero_crudo"] -= 5.0
    delta["pechuga_vitrina"] += 10.0
    delta["muslo_vitrina"] += 10.0
    delta["contramuslo_vitrina"] += 10.0
    delta["ala_vitrina"] += 10.0
    delta["caldo_raciones"] += 10.0

    # 2. Batch Frying: 20 presas
    r = client.post("/api/kitchen/batch-timer", json={"stage": "fritura", "total_presas": 20})
    assert r.status_code == 200
    delta["harina_apanar_kg"] -= round(20 * 0.025, 3)
    delta["aceite_fritura_lt"] -= round(20 * 0.02, 3)

    # 3. Batch sales and cancellations
    sales_created = []

    # Sale A: POL-ENT x 1 (2P, 2A, 2M, 2C, 2 Papas)
    r = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-ENT"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert r.status_code == 200
    s_a = r.json()["sale_id"]
    sales_created.append(("A", s_a, {
        "pechuga_vitrina": 2.0, "ala_vitrina": 2.0, "muslo_vitrina": 2.0,
        "contramuslo_vitrina": 2.0, "papas_raciones": 2.0
    }))
    for k, v in sales_created[-1][2].items():
        delta[k] -= v

    # Sale B: ALM-COMP x 2 (Muslo, Ala)
    r = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["ALM-COMP"], "quantity": 1, "chosen_presa": "Muslo"},
            {"product_id": prods["ALM-COMP"], "quantity": 1, "chosen_presa": "Ala"}
        ],
        "payment_method": "nequi_daviplata"
    })
    assert r.status_code == 200
    s_b = r.json()["sale_id"]
    sales_created.append(("B", s_b, {
        "muslo_vitrina": 1.0, "ala_vitrina": 1.0,
        "caldo_raciones": 2.0, "arroz_raciones": 2.0, "frijoles_raciones": 2.0
    }))
    for k, v in sales_created[-1][2].items():
        delta[k] -= v

    # Sale C: Sides and drinks
    r = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prods["POR-AREP"], "quantity": 3},
            {"product_id": prods["GAS-COC-400"], "quantity": 2},
            {"product_id": prods["GAS-MAN-400"], "quantity": 1}
        ],
        "payment_method": "datafono"
    })
    assert r.status_code == 200
    s_c = r.json()["sale_id"]
    sales_created.append(("C", s_c, {
        "arepas_unidades": 3.0, "GAS-COC-400": 2.0, "GAS-MAN-400": 1.0
    }))
    for k, v in sales_created[-1][2].items():
        delta[k] -= v

    # Sale D: POL-14 x 1 (1M, 1C, 1 Papa) - Will be CANCELLED
    r = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prods["POL-14"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert r.status_code == 200
    s_d = r.json()["sale_id"]
    s_d_reqs = {"muslo_vitrina": 1.0, "contramuslo_vitrina": 1.0, "papas_raciones": 1.0}
    for k, v in s_d_reqs.items():
        delta[k] -= v

    # Cancel Sale D -> should restore s_d_reqs exactly
    r_cancel = client.post(f"/api/pos/cancel-sale/{s_d}")
    assert r_cancel.status_code == 200
    for k, v in s_d_reqs.items():
        delta[k] += v

    # 4. Second Despiece: 3 chickens
    r = client.post("/api/kitchen/despiece", json={"whole_chickens": 3, "operator": "Audit_2"})
    assert r.status_code == 200
    delta["pollo_entero_crudo"] -= 3.0
    delta["pechuga_vitrina"] += 6.0
    delta["muslo_vitrina"] += 6.0
    delta["contramuslo_vitrina"] += 6.0
    delta["ala_vitrina"] += 6.0
    delta["caldo_raciones"] += 6.0

    # 5. Stress test: 20 rapid sales of POL-PEC and GAS-COL-400
    p_pec = prods["POL-PEC"]
    p_col = prods["GAS-COL-400"]

    def stress_checkout(i):
        res = client.post("/api/pos/checkout", json={
            "items": [
                {"product_id": p_pec, "quantity": 1},
                {"product_id": p_col, "quantity": 1}
            ],
            "payment_method": "efectivo",
            "cash_received": 20000
        })
        return res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(stress_checkout, range(20)))

    assert all(s == 200 for s in statuses)
    delta["pechuga_vitrina"] -= 20.0
    delta["GAS-COL-400"] -= 20.0

    # 6. Verify closed inventory invariance across EVERY item in inventory
    conn = database.get_db_connection()
    final_rows = conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    final_stock = {r["item_key"]: float(r["stock"]) for r in final_rows}
    conn.close()

    drifts = {}
    for item_key in all_item_keys:
        expected = initial_stock[item_key] + delta[item_key]
        actual = final_stock[item_key]
        if abs(actual - expected) > 1e-5:
            drifts[item_key] = {"initial": initial_stock[item_key], "delta": delta[item_key], "expected": expected, "actual": actual}

    assert len(drifts) == 0, f"Closed Inventory Invariance Violated on items: {drifts}"
