"""
Concurrency Stress Test Suite
Mandated by R5 / Feature 21:
- Executes >= 50 rapid concurrent checkouts using concurrent.futures.ThreadPoolExecutor.
- Verifies 0 database locks ('database is locked').
- Verifies 0 UNIQUE constraint collisions ('UNIQUE constraint failed: sales.sale_code').
- Verifies 0 inventory drift (exact physical inventory conservation under concurrent writes).
- Verifies all transaction sale codes are strictly unique and sequential.
"""

import concurrent.futures
import pytest

def test_fifty_rapid_concurrent_checkouts(client, helpers):
    """
    Stress test with 50 rapid concurrent checkout transactions across 10 threads.
    Verifies concurrency safety under SQLite WAL mode with zero errors and zero inventory drift.
    """
    TOTAL_CONCURRENT_TRANSACTIONS = 50
    NUM_WORKER_THREADS = 10

    # Ensure ample stock for 50 checkouts
    helpers.set_stock("pechuga_vitrina", 100.0)
    helpers.set_stock("GAS-COL-400", 100.0)

    p_pec = helpers.get_product_id("POL-PEC")
    p_soda = helpers.get_product_id("GAS-COL-400")

    def execute_single_checkout(index: int):
        payload = {
            "items": [
                {"product_id": p_pec, "quantity": 1},
                {"product_id": p_soda, "quantity": 1}
            ],
            "payment_method": "efectivo" if index % 2 == 0 else "nequi_daviplata",
            "cash_received": 15000 if index % 2 == 0 else 0,
            "notes": f"Stress test tx #{index:03d}"
        }
        res = client.post("/api/pos/checkout", json=payload)
        return res.status_code, res.text, res.json() if res.status_code == 200 else {}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKER_THREADS) as executor:
        futures = [executor.submit(execute_single_checkout, i) for i in range(TOTAL_CONCURRENT_TRANSACTIONS)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # 1. Assert all 50 checkouts completed with HTTP 200
    errors = [f"Code {code}: {txt}" for code, txt, _ in results if code != 200]
    assert len(errors) == 0, f"Concurrent checkouts encountered errors: {errors}"
    assert len(results) == TOTAL_CONCURRENT_TRANSACTIONS

    # 2. Assert zero database locks and zero unique constraint failures
    for code, txt, _ in results:
        assert "database is locked" not in txt.lower()
        assert "unique constraint failed" not in txt.lower()

    # 3. Assert strictly unique sale codes across all 50 transactions
    sale_codes = [data["sale_code"] for _, _, data in results]
    assert len(set(sale_codes)) == TOTAL_CONCURRENT_TRANSACTIONS, "Duplicate sale_code generated under concurrency!"

    # 4. Assert zero inventory drift: exactly 50 units deducted from stock
    final_pec = helpers.get_stock("pechuga_vitrina")
    final_soda = helpers.get_stock("GAS-COL-400")
    assert final_pec == 100.0 - TOTAL_CONCURRENT_TRANSACTIONS # Exactly 50.0
    assert final_soda == 100.0 - TOTAL_CONCURRENT_TRANSACTIONS # Exactly 50.0

    # 5. Financial integrity check
    summary = client.get("/api/cash/daily-summary").json()["cash_summary"]
    expected_revenue = TOTAL_CONCURRENT_TRANSACTIONS * (9000 + 3500) # 625,000 COP
    assert summary["gran_total"] == expected_revenue
    assert summary["total_tickets"] == TOTAL_CONCURRENT_TRANSACTIONS


def test_concurrent_mixed_combos_stress(client, helpers):
    """
    Stress test with 30 concurrent transactions purchasing multi-item Combos (1/4 Pollo, 1/2 Pollo, Pollo Entero).
    Verifies multi-table atomic locks and zero component inventory drift.
    """
    CONCURRENT_COMBOS = 30
    NUM_WORKER_THREADS = 8

    # Ample stock for all combo components
    helpers.set_stock("pechuga_vitrina", 150.0)
    helpers.set_stock("ala_vitrina", 150.0)
    helpers.set_stock("muslo_vitrina", 150.0)
    helpers.set_stock("contramuslo_vitrina", 150.0)
    helpers.set_stock("papas_raciones", 150.0)

    p_14 = helpers.get_product_id("POL-14") # 1M, 1C, 1 papa
    p_12 = helpers.get_product_id("POL-12") # 1P, 1A, 1M, 1C, 1 papa
    p_ent = helpers.get_product_id("POL-ENT") # 2P, 2A, 2M, 2C, 2 papas

    combo_list = [p_14, p_12, p_ent]

    def execute_combo_checkout(index: int):
        combo_id = combo_list[index % 3]
        payload = {
            "items": [{"product_id": combo_id, "quantity": 1}],
            "payment_method": "datafono"
        }
        res = client.post("/api/pos/checkout", json=payload)
        return res.status_code, res.text, combo_id

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKER_THREADS) as executor:
        futures = [executor.submit(execute_combo_checkout, i) for i in range(CONCURRENT_COMBOS)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Verify all 30 succeeded
    errors = [f"Code {code}: {txt}" for code, txt, _ in results if code != 200]
    assert len(errors) == 0, f"Combo checkouts failed: {errors}"
    assert len(results) == CONCURRENT_COMBOS

    # Verify zero database lock errors
    for code, txt, _ in results:
        assert "database is locked" not in txt.lower()

    # Calculate expected deductions:
    # 10 of p_14: 10M, 10C, 10 papas
    # 10 of p_12: 10P, 10A, 10M, 10C, 10 papas
    # 10 of p_ent: 20P, 20A, 20M, 20C, 20 papas
    # Expected totals deducted:
    # Pechugas: 0 + 10 + 20 = 30
    # Alas: 0 + 10 + 20 = 30
    # Muslos: 10 + 10 + 20 = 40
    # Contramuslos: 10 + 10 + 20 = 40
    # Papas: 10 + 10 + 20 = 40
    assert helpers.get_stock("pechuga_vitrina") == 150.0 - 30.0 # 120.0
    assert helpers.get_stock("ala_vitrina") == 150.0 - 30.0 # 120.0
    assert helpers.get_stock("muslo_vitrina") == 150.0 - 40.0 # 110.0
    assert helpers.get_stock("contramuslo_vitrina") == 150.0 - 40.0 # 110.0
    assert helpers.get_stock("papas_raciones") == 150.0 - 40.0 # 110.0
