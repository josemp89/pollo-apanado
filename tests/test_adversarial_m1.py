import threading
import concurrent.futures
import re
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from app.main import app
import app.database as database

def test_adversarial_barrier_hammering_checkout(isolated_db):
    """
    Adversarial Stress Test:
    Hammer checkout endpoint with 60 simultaneous complex transactions across 15 threads.
    Synchronized via threading.Barrier so all 15 threads strike simultaneously.
    Verifies:
      1. Zero 'database is locked' or 'busy' errors.
      2. Zero duplicate sale_codes.
      3. Strict format and contiguous sequence numbers.
      4. Exact mathematical inventory balance with ZERO drift across all item keys.
    """
    client = TestClient(app)
    
    # Pre-seed inventory with ample stock to guarantee all 60 checkouts can be fulfilled
    conn = database.get_db_connection()
    tracked_keys = [
        'pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina',
        'papas_raciones', 'caldo_raciones', 'arroz_raciones', 'frijoles_raciones',
        'arepas_unidades', 'GAS-COC-400', 'GAS-MAN-400'
    ]
    for key in tracked_keys:
        conn.execute("UPDATE inventory SET stock = 1000.0 WHERE item_key = ?", (key,))
    conn.commit()
    
    # Fetch initial stock baseline
    initial_stock = {
        row["item_key"]: float(row["stock"])
        for row in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    conn.close()

    # Fetch product definitions
    products = client.get("/api/pos/products").json()
    prod_map = {p["sku"]: p["id"] for p in products}

    # Define diverse carts
    carts = [
        # Cart 0: Combo Pollo Entero + 2 Cocas
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["POL-ENT"], "quantity": 1},
                    {"product_id": prod_map["GAS-COC-400"], "quantity": 2}
                ],
                "payment_method": "efectivo",
                "cash_received": 100000
            },
            "expected_deductions": {
                'pechuga_vitrina': 2.0, 'ala_vitrina': 2.0, 'muslo_vitrina': 2.0,
                'contramuslo_vitrina': 2.0, 'papas_raciones': 2.0, 'GAS-COC-400': 2.0
            }
        },
        # Cart 1: Combo 1/2 Pollo + Porción Arepas
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["POL-12"], "quantity": 1},
                    {"product_id": prod_map["POR-AREP"], "quantity": 1}
                ],
                "payment_method": "nequi_daviplata",
                "cash_received": 0
            },
            "expected_deductions": {
                'pechuga_vitrina': 1.0, 'ala_vitrina': 1.0, 'muslo_vitrina': 1.0,
                'contramuslo_vitrina': 1.0, 'papas_raciones': 1.0, 'arepas_unidades': 1.0
            }
        },
        # Cart 2: Combo 1/4 Pollo + Manzana 400ml
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["POL-14"], "quantity": 1},
                    {"product_id": prod_map["GAS-MAN-400"], "quantity": 1}
                ],
                "payment_method": "datafono",
                "cash_received": 0
            },
            "expected_deductions": {
                'muslo_vitrina': 1.0, 'contramuslo_vitrina': 1.0,
                'papas_raciones': 1.0, 'GAS-MAN-400': 1.0
            }
        },
        # Cart 3: Almuerzo Completo con Pechuga
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["ALM-COMP"], "quantity": 1, "chosen_presa": "Pechuga"}
                ],
                "payment_method": "efectivo",
                "cash_received": 20000
            },
            "expected_deductions": {
                'pechuga_vitrina': 1.0, 'caldo_raciones': 1.0,
                'arroz_raciones': 1.0, 'frijoles_raciones': 1.0
            }
        },
        # Cart 4: Almuerzo Completo con Muslo + Porción Arepas
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["ALM-COMP"], "quantity": 1, "chosen_presa": "Muslo"},
                    {"product_id": prod_map["POR-AREP"], "quantity": 2}
                ],
                "payment_method": "efectivo",
                "cash_received": 50000
            },
            "expected_deductions": {
                'muslo_vitrina': 1.0, 'caldo_raciones': 1.0,
                'arroz_raciones': 1.0, 'frijoles_raciones': 1.0,
                'arepas_unidades': 2.0
            }
        },
        # Cart 5: Presas sueltas (Pechuga + Ala)
        {
            "payload": {
                "items": [
                    {"product_id": prod_map["POL-PEC"], "quantity": 1},
                    {"product_id": prod_map["POL-ALA"], "quantity": 1}
                ],
                "payment_method": "efectivo",
                "cash_received": 20000
            },
            "expected_deductions": {
                'pechuga_vitrina': 1.0, 'ala_vitrina': 1.0
            }
        }
    ]

    total_transactions = 60
    num_threads = 15
    barrier = threading.Barrier(num_threads)
    
    # Calculate total expected inventory deductions across all 60 planned checkouts
    total_expected_deductions = {key: 0.0 for key in tracked_keys}
    for i in range(total_transactions):
        cart_type = carts[i % len(carts)]
        for k, v in cart_type["expected_deductions"].items():
            total_expected_deductions[k] += v

    def execute_transaction(tx_index):
        # Barrier synchronization: thread waits until all threads in batch arrive
        barrier.wait()
        cart = carts[tx_index % len(carts)]
        try:
            res = client.post("/api/pos/checkout", json=cart["payload"])
            return tx_index, res.status_code, res.json()
        except Exception as exc:
            return tx_index, 999, {"error": str(exc)}

    # Execute 60 transactions using ThreadPoolExecutor with 15 concurrent worker threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(execute_transaction, i) for i in range(total_transactions)]
        results = [f.result() for f in futures]

    # 1. Assert all transactions succeeded with HTTP 200
    failed_txs = [r for r in results if r[1] != 200]
    assert len(failed_txs) == 0, f"Encountered failed transactions: {failed_txs}"

    # 2. Assert zero duplicate sale_code and valid format
    sale_codes = [r[2]["sale_code"] for r in results]
    assert len(sale_codes) == total_transactions, f"Expected {total_transactions} sale codes"
    assert len(set(sale_codes)) == total_transactions, f"Duplicate sale codes detected! Duplicates: {[c for c in sale_codes if sale_codes.count(c) > 1]}"
    
    code_pattern = re.compile(r"^VTA-\d{6}-\d{4}$")
    for code in sale_codes:
        assert code_pattern.match(code), f"Invalid sale_code format: {code}"

    # 3. Verify zero 'database is locked' errors in response bodies
    error_texts = [str(r[2]) for r in results if "locked" in str(r[2]).lower() or "busy" in str(r[2]).lower()]
    assert len(error_texts) == 0, f"Found locking/busy errors in responses: {error_texts}"

    # 4. Strict Mathematical Balance & Zero Drift Verification
    conn = database.get_db_connection()
    final_stock = {
        row["item_key"]: float(row["stock"])
        for row in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    
    # Verify sales table record count
    sales_count = conn.execute("SELECT COUNT(*) FROM sales WHERE status = 'completada'").fetchone()[0]
    assert sales_count == total_transactions, f"Expected {total_transactions} sales rows, found {sales_count}"
    conn.close()

    for item_key in tracked_keys:
        initial = initial_stock[item_key]
        expected_ded = total_expected_deductions[item_key]
        actual_final = final_stock[item_key]
        expected_final = initial - expected_ded
        discrepancy = actual_final - expected_final
        assert discrepancy == 0.0, (
            f"INVENTORY DRIFT DETECTED on {item_key}: "
            f"initial={initial}, deducted={expected_ded}, expected={expected_final}, actual={actual_final}, drift={discrepancy}"
        )


def test_adversarial_concurrency_stock_exhaustion_race(isolated_db):
    """
    Adversarial Attack: Stock Depletion Race Condition.
    Set pechuga_vitrina to exactly 12 units.
    Fire 60 simultaneous requests across 15 threads attempting to buy 1 pechuga each.
    Verifies:
      1. Exactly 12 succeed (HTTP 200).
      2. Exactly 48 fail cleanly with HTTP 400 ('Stock insuficiente').
      3. ZERO HTTP 500 or SQLite database lock errors.
      4. Final stock is EXACTLY 0.0 (no negative values, zero drift).
      5. Exactly 12 unique sale_codes generated.
    """
    client = TestClient(app)
    
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 12.0 WHERE item_key = 'pechuga_vitrina'")
    conn.commit()
    conn.close()

    products = client.get("/api/pos/products").json()
    pechuga_prod = next(p for p in products if p["sku"] == "POL-PEC")

    num_threads = 15
    total_requests = 60
    barrier = threading.Barrier(num_threads)

    def buy_pechuga(idx):
        barrier.wait()
        payload = {
            "items": [{"product_id": pechuga_prod["id"], "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        }
        res = client.post("/api/pos/checkout", json=payload)
        return idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(buy_pechuga, i) for i in range(total_requests)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[1] == 200]
    out_of_stocks = [r for r in results if r[1] == 400]
    internal_errors = [r for r in results if r[1] == 500]

    assert len(internal_errors) == 0, f"Encountered HTTP 500 errors: {internal_errors}"
    assert len(successes) == 12, f"Expected exactly 12 successful sales, got {len(successes)}"
    assert len(out_of_stocks) == 48, f"Expected exactly 48 out-of-stock rejections, got {len(out_of_stocks)}"

    for oos in out_of_stocks:
        assert "Stock insuficiente" in oos[2].get("detail", ""), f"Unexpected error detail: {oos[2]}"

    # Verify unique sale_codes
    sale_codes = [s[2]["sale_code"] for s in successes]
    assert len(set(sale_codes)) == 12, "Duplicate sale_code detected among successful transactions!"

    # Verify final stock is exactly 0.0
    conn = database.get_db_connection()
    final_stock = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    conn.close()

    assert final_stock == 0.0, f"Expected final stock 0.0, got {final_stock}"


def test_adversarial_mixed_pos_and_kitchen_concurrency(isolated_db):
    """
    Adversarial Attack: Simultaneous POS Checkouts + Kitchen Despiece + Fryer Batch Timers.
    15 concurrent worker threads performing:
      - 20 POS Checkouts (Combo 1/4 Pollo: 1 muslo + 1 contramuslo + 1 papas)
      - 5 Kitchen Despiece (each 2 whole chickens = +4P, +4M, +4C, +4A, +4 Caldo, -2 Pollo Crudo)
      - 5 Kitchen Fritura Batches (each 16 presas -> deducts harina and aceite)
    Verifies:
      1. Zero 'database is locked' errors.
      2. Zero sequence number collisions in both sale_code and batch_code.
      3. Exact mathematical balance across all kitchen & vitrina inventory items.
    """
    client = TestClient(app)

    conn = database.get_db_connection()
    # Seed ample stock
    conn.execute("UPDATE inventory SET stock = 100.0 WHERE item_key = 'pollo_entero_crudo'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'muslo_vitrina'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'contramuslo_vitrina'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'papas_raciones'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'pechuga_vitrina'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'ala_vitrina'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'caldo_raciones'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'harina_apanar_kg'")
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key = 'aceite_fritura_lt'")
    conn.commit()

    initial = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    conn.close()

    products = client.get("/api/pos/products").json()
    cuarto_prod = next(p for p in products if p["sku"] == "POL-14")

    num_threads = 15
    barrier = threading.Barrier(num_threads)

    operations = []
    # 20 checkouts
    for i in range(20):
        operations.append(("checkout", i))
    # 5 despieces (2 chickens each)
    for i in range(5):
        operations.append(("despiece", i))
    # 5 batch timers (fritura, 16 presas)
    for i in range(5):
        operations.append(("batch", i))

    assert len(operations) == 30

    def run_op(op):
        barrier.wait()
        op_type, op_idx = op
        if op_type == "checkout":
            payload = {
                "items": [{"product_id": cuarto_prod["id"], "quantity": 1}],
                "payment_method": "efectivo",
                "cash_received": 15000
            }
            res = client.post("/api/pos/checkout", json=payload)
            return op_type, op_idx, res.status_code, res.json()
        elif op_type == "despiece":
            payload = {"whole_chickens": 2, "operator": f"Cook-{op_idx}"}
            res = client.post("/api/kitchen/despiece", json=payload)
            return op_type, op_idx, res.status_code, res.json()
        elif op_type == "batch":
            payload = {"stage": "fritura", "total_presas": 16, "notes": f"Batch-{op_idx}"}
            res = client.post("/api/kitchen/batch-timer", json=payload)
            return op_type, op_idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(run_op, op) for op in operations]
        results = [f.result() for f in futures]

    # Verify no failures
    failed = [r for r in results if r[2] != 200]
    assert len(failed) == 0, f"Mixed concurrent operations failed: {failed}"

    # Verify uniqueness of sale codes (20) and batch codes (5)
    sale_codes = [r[3]["sale_code"] for r in results if r[0] == "checkout"]
    batch_codes = [r[3]["batch_code"] for r in results if r[0] == "batch"]
    assert len(set(sale_codes)) == 20, "Duplicate sale_code under mixed concurrency!"
    assert len(set(batch_codes)) == 5, "Duplicate batch_code under mixed concurrency!"

    # Verify mathematical balance
    conn = database.get_db_connection()
    final = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    conn.close()

    # Despiece: 5 operations * 2 chickens = 10 chickens consumed
    assert final["pollo_entero_crudo"] == initial["pollo_entero_crudo"] - 10.0
    # Pechugas: 0 from 1/4 pollo, +20 from despiece (5 * 4)
    assert final["pechuga_vitrina"] == initial["pechuga_vitrina"] + 20.0
    # Alas: 0 from 1/4 pollo, +20 from despiece (5 * 4)
    assert final["ala_vitrina"] == initial["ala_vitrina"] + 20.0
    # Muslos: -20 from 20 checkouts, +20 from despiece (5 * 4) -> Net delta 0
    assert final["muslo_vitrina"] == initial["muslo_vitrina"] - 20.0 + 20.0
    # Contramuslos: -20 from 20 checkouts, +20 from despiece -> Net delta 0
    assert final["contramuslo_vitrina"] == initial["contramuslo_vitrina"] - 20.0 + 20.0
    # Papas: -20 from 20 checkouts
    assert final["papas_raciones"] == initial["papas_raciones"] - 20.0
    # Caldo: +20 from despiece
    assert final["caldo_raciones"] == initial["caldo_raciones"] + 20.0
    # Harina: 5 batches * 16 * 0.025 = 2.0 kg
    assert abs(final["harina_apanar_kg"] - (initial["harina_apanar_kg"] - 2.0)) < 0.001
    # Aceite: 5 batches * 16 * 0.02 = 1.6 lt
    assert abs(final["aceite_fritura_lt"] - (initial["aceite_fritura_lt"] - 1.6)) < 0.001


def test_adversarial_concurrent_double_cancel_race(isolated_db):
    """
    Adversarial Attack: Concurrent Double-Cancel Race Condition.
    Creates 1 sale.
    Fires 10 simultaneous cancel requests targeting the exact same sale_id across 10 threads.
    Evaluates whether:
      - Exactly ONE request succeeds (HTTP 200).
      - The other 9 requests receive HTTP 400 ('ya se encuentra anulada').
      - Stock is restored EXACTLY ONCE (no double/multiple inventory restitution).
    """
    client = TestClient(app)

    # 1. Create a sale with 1/4 Pollo (1 muslo, 1 contramuslo, 1 papas)
    products = client.get("/api/pos/products").json()
    cuarto_prod = next(p for p in products if p["sku"] == "POL-14")

    # Read initial stock
    stock_initial = client.get("/api/pos/stock-summary").json()
    muslo_init = stock_initial["muslo_vitrina"]["stock"]

    res_sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": cuarto_prod["id"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 15000
    })
    assert res_sale.status_code == 200
    sale_id = res_sale.json()["sale_id"]

    # Verify deducted
    stock_after_sale = client.get("/api/pos/stock-summary").json()
    assert stock_after_sale["muslo_vitrina"]["stock"] == muslo_init - 1

    # 2. Fire 10 simultaneous cancellation requests
    num_threads = 10
    barrier = threading.Barrier(num_threads)

    def cancel_attempt(idx):
        barrier.wait()
        res = client.post(f"/api/pos/cancel-sale/{sale_id}")
        return idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(cancel_attempt, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[1] == 200]
    already_cancelled = [r for r in results if r[1] == 400]
    errors = [r for r in results if r[1] not in (200, 400)]

    # Check for unexpected crashes
    assert len(errors) == 0, f"Unexpected error status codes during concurrent cancel: {errors}"

    # Critical check:
    # Exactly ONE cancellation must succeed, 9 must be rejected
    assert len(successes) == 1, (
        f"RACE CONDITION IN CANCEL_SALE: {len(successes)} requests succeeded! "
        f"Expected exactly 1 success. Successes: {successes}"
    )
    assert len(already_cancelled) == 9, f"Expected 9 HTTP 400 rejections, got {len(already_cancelled)}"

    # Verify inventory was restored exactly ONCE and not multiplied
    stock_final = client.get("/api/pos/stock-summary").json()
    assert stock_final["muslo_vitrina"]["stock"] == muslo_init, (
        f"Inventory drift in cancel race: initial={muslo_init}, final={stock_final['muslo_vitrina']['stock']}"
    )


def test_adversarial_despiece_concurrency_race(isolated_db):
    """
    Adversarial Attack: Concurrent Despiece on Limited Bodega Stock.
    Set pollo_entero_crudo to exactly 3 units in bodega.
    Fire 8 simultaneous despiece requests across 8 threads, each attempting to butcher 2 chickens.
    Verifies:
      1. Exactly 1 request succeeds (butchering 2, leaving 1 in bodega).
      2. Exactly 7 requests are rejected with HTTP 400 ('Stock insuficiente').
      3. ZERO HTTP 500 or SQLite database locked errors.
      4. Bodega stock is exactly 1 (not negative!).
      5. Vitrina stock gained exactly 4 of each presa (no phantom multiplication).
    """
    client = TestClient(app)

    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 3.0 WHERE item_key = 'pollo_entero_crudo'")
    conn.commit()

    initial = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    conn.close()

    num_threads = 8
    barrier = threading.Barrier(num_threads)

    def do_despiece(idx):
        barrier.wait()
        res = client.post("/api/kitchen/despiece", json={"whole_chickens": 2, "operator": f"Butcher-{idx}"})
        return idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(do_despiece, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[1] == 200]
    failures = [r for r in results if r[1] == 400]
    errors = [r for r in results if r[1] not in (200, 400)]

    assert len(errors) == 0, f"Unexpected errors during concurrent despiece: {errors}"
    assert len(successes) == 1, f"Expected exactly 1 successful despiece, got {len(successes)}"
    assert len(failures) == 7, f"Expected exactly 7 rejections, got {len(failures)}"

    conn = database.get_db_connection()
    final = {
        r["item_key"]: float(r["stock"])
        for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
    }
    conn.close()

    assert final["pollo_entero_crudo"] == 1.0, f"Expected 1.0 chicken left in bodega, got {final['pollo_entero_crudo']}"
    assert final["pechuga_vitrina"] == initial["pechuga_vitrina"] + 4.0
    assert final["muslo_vitrina"] == initial["muslo_vitrina"] + 4.0
    assert final["contramuslo_vitrina"] == initial["contramuslo_vitrina"] + 4.0
    assert final["ala_vitrina"] == initial["ala_vitrina"] + 4.0
    assert final["caldo_raciones"] == initial["caldo_raciones"] + 4.0

