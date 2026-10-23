"""
Empirical Challenger Test Suite: High-Scale Concurrency & Double-Cancel Stress
Milestone: M1 Iteration 2
Agent: Challenger 1 (challenger_m1_r2_1)

Stress tests:
1. Scale 20: 20 simultaneous cancel requests on a single sale (Combo 1/4 Pollo).
2. Scale 30: 30 simultaneous cancel requests on a single sale (Almuerzo Completo).
3. Scale 50: 50 simultaneous cancel requests on a single sale (Combo Pollo Entero).
4. Multi-Sale Race: 40 threads simultaneously cancelling two distinct sales (20 threads on Sale A, 20 on Sale B).
5. Zero Phantom Inventory Drift: Verification that stock before checkout exactly matches stock after cancellation.
"""

import threading
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from app.main import app
import app.database as database

@pytest.mark.parametrize("scale", [20, 30, 50])
def test_simultaneous_cancellation_scale_stress(client, helpers, scale):
    """
    Stress test with 20, 30, and 50 simultaneous cancellation requests against a single sale.
    All threads are synchronized with threading.Barrier to maximize instantaneous contention.
    
    Verifies:
      1. Exactly 1 request succeeds with HTTP 200.
      2. Exactly (scale - 1) requests fail with HTTP 400 and detail 'ya se encuentra anulada'.
      3. ZERO HTTP 500 or SQLite 'database is locked' errors.
      4. ZERO phantom inventory drift: post-cancellation stock == pre-checkout baseline.
      5. Sale status in database is strictly 'anulada'.
    """
    # 1. Reset and capture baseline stock
    tracked_items = [
        "pechuga_vitrina", "ala_vitrina", "muslo_vitrina",
        "contramuslo_vitrina", "papas_raciones", "GAS-COC-400"
    ]
    for item in tracked_items:
        helpers.set_stock(item, 100.0)

    initial_stocks = {item: helpers.get_stock(item) for item in tracked_items}

    # 2. Place an order (Combo Pollo Entero: 2P, 2A, 2M, 2C, 2 Papas + 1 Coca-Cola)
    p_ent = helpers.get_product_id("POL-ENT")
    p_coke = helpers.get_product_id("GAS-COC-400")

    checkout_res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_ent, "quantity": 1},
            {"product_id": p_coke, "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert checkout_res.status_code == 200, f"Checkout failed: {checkout_res.text}"
    sale_id = checkout_res.json()["sale_id"]

    # Verify inventory was deducted
    assert helpers.get_stock("pechuga_vitrina") == initial_stocks["pechuga_vitrina"] - 2.0
    assert helpers.get_stock("muslo_vitrina") == initial_stocks["muslo_vitrina"] - 2.0
    assert helpers.get_stock("papas_raciones") == initial_stocks["papas_raciones"] - 2.0
    assert helpers.get_stock("GAS-COC-400") == initial_stocks["GAS-COC-400"] - 1.0

    # 3. Synchronize `scale` threads at a barrier
    barrier = threading.Barrier(scale)

    def hammer_cancel(thread_idx):
        barrier.wait()
        res = client.post(f"/api/pos/cancel-sale/{sale_id}")
        return thread_idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=scale) as executor:
        futures = [executor.submit(hammer_cancel, i) for i in range(scale)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[1] == 200]
    bad_requests = [r for r in results if r[1] == 400]
    server_errors = [r for r in results if r[1] == 500]
    other_errors = [r for r in results if r[1] not in (200, 400)]

    # 4. Assert zero server errors or database lockouts
    assert len(server_errors) == 0, f"Scale {scale}: Encountered HTTP 500 errors: {server_errors}"
    assert len(other_errors) == 0, f"Scale {scale}: Unexpected status codes: {other_errors}"

    # 5. Assert EXACTLY 1 winner and (scale - 1) HTTP 400 rejections
    assert len(successes) == 1, (
        f"CRITICAL CONCURRENCY FAILURE at scale {scale}: "
        f"Expected exactly 1 success, but got {len(successes)} successes! Successes: {successes}"
    )
    assert len(bad_requests) == scale - 1, (
        f"Scale {scale}: Expected {scale - 1} HTTP 400 rejections, got {len(bad_requests)}"
    )

    for br in bad_requests:
        detail = br[2].get("detail", "")
        assert "ya se encuentra anulada" in detail, f"Unexpected 400 detail: {detail}"

    # 6. Verify ZERO phantom inventory drift
    final_stocks = {item: helpers.get_stock(item) for item in tracked_items}
    for item in tracked_items:
        init_val = initial_stocks[item]
        final_val = final_stocks[item]
        drift = final_val - init_val
        assert drift == 0.0, (
            f"PHANTOM INVENTORY DRIFT on '{item}' at scale {scale}: "
            f"initial={init_val}, final={final_val}, drift={drift}"
        )

    # 7. Check database record status
    conn = helpers.get_conn()
    sale_row = conn.execute("SELECT status FROM sales WHERE id = ?", (sale_id,)).fetchone()
    assert sale_row["status"] == "anulada"
    
    # 8. PRAGMA integrity check
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert integrity == "ok"
    conn.close()


def test_concurrent_multi_sale_cancellation_race(client, helpers):
    """
    Stress test with 2 distinct sales being cancelled concurrently by 20 threads each (40 total threads).
    Verifies that atomic row-level conditional updates do not cross-talk or lock out distinct sales.
    """
    helpers.set_stock("pechuga_vitrina", 100.0)
    helpers.set_stock("muslo_vitrina", 100.0)
    p_pec = helpers.get_product_id("POL-PEC")
    p_mus = helpers.get_product_id("POL-MUS")

    # Create Sale 1
    s1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_pec, "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 50000
    }).json()["sale_id"]

    # Create Sale 2
    s2 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_mus, "quantity": 3}],
        "payment_method": "nequi_daviplata",
        "cash_received": 0
    }).json()["sale_id"]

    total_threads = 40
    barrier = threading.Barrier(total_threads)

    def cancel_worker(sale_target):
        barrier.wait()
        res = client.post(f"/api/pos/cancel-sale/{sale_target}")
        return sale_target, res.status_code, res.json()

    tasks = [s1] * 20 + [s2] * 20

    with concurrent.futures.ThreadPoolExecutor(max_workers=total_threads) as executor:
        futures = [executor.submit(cancel_worker, target) for target in tasks]
        results = [f.result() for f in futures]

    # Analyze Sale 1
    s1_results = [r for r in results if r[0] == s1]
    s1_successes = [r for r in s1_results if r[1] == 200]
    s1_rejected = [r for r in s1_results if r[1] == 400]

    assert len(s1_successes) == 1, f"Sale 1 had {len(s1_successes)} successes, expected 1"
    assert len(s1_rejected) == 19, f"Sale 1 had {len(s1_rejected)} rejections, expected 19"

    # Analyze Sale 2
    s2_results = [r for r in results if r[0] == s2]
    s2_successes = [r for r in s2_results if r[1] == 200]
    s2_rejected = [r for r in s2_results if r[1] == 400]

    assert len(s2_successes) == 1, f"Sale 2 had {len(s2_successes)} successes, expected 1"
    assert len(s2_rejected) == 19, f"Sale 2 had {len(s2_rejected)} rejections, expected 19"

    # Verify inventory restitution
    assert helpers.get_stock("pechuga_vitrina") == 100.0
    assert helpers.get_stock("muslo_vitrina") == 100.0


def test_interleaved_concurrent_checkouts_and_cancellations(client, helpers):
    """
    Stress test with rapid interleaved checkouts and cancellations under high concurrency:
    - 20 sales created
    - 20 concurrent worker threads randomly checking out new sales or cancelling completed sales
    Verifies that simultaneous write transactions do not trigger lock timeouts or inventory corruption.
    """
    helpers.set_stock("pechuga_vitrina", 200.0)
    helpers.set_stock("muslo_vitrina", 200.0)
    p_pec = helpers.get_product_id("POL-PEC")

    # Pre-create 10 sales
    sales_to_cancel = []
    for _ in range(10):
        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": p_pec, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        })
        assert res.status_code == 200
        sales_to_cancel.append(res.json()["sale_id"])

    stock_midpoint = helpers.get_stock("pechuga_vitrina")
    assert stock_midpoint == 190.0 # 200 - 10

    # 10 workers cancel the 10 sales, while 10 workers checkout 10 new sales simultaneously
    barrier = threading.Barrier(20)

    def worker_action(idx):
        barrier.wait()
        if idx < 10:
            # Cancel sale
            s_id = sales_to_cancel[idx]
            r = client.post(f"/api/pos/cancel-sale/{s_id}")
            return "cancel", r.status_code
        else:
            # Checkout new sale
            r = client.post("/api/pos/checkout", json={
                "items": [{"product_id": p_pec, "quantity": 1}],
                "payment_method": "efectivo",
                "cash_received": 10000
            })
            return "checkout", r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker_action, i) for i in range(20)]
        results = [f.result() for f in futures]

    cancels = [r for r in results if r[0] == "cancel"]
    checkouts = [r for r in results if r[0] == "checkout"]

    assert all(c[1] == 200 for c in cancels), f"Some cancellations failed: {cancels}"
    assert all(co[1] == 200 for co in checkouts), f"Some checkouts failed: {checkouts}"

    # Invariant: 10 cancelled (+10 stock), 10 checked out (-10 stock) => Net delta = 0
    final_stock = helpers.get_stock("pechuga_vitrina")
    assert final_stock == 190.0, f"Expected final stock 190.0, got {final_stock}"
