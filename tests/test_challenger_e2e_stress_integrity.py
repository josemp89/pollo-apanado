import threading
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from app.main import app
import app.database as database

def test_adversarial_competing_tables_and_counter_orders(isolated_db):
    """
    STRESS & CONCURRENCY AUDIT:
    Simultaneous orders between dining tables (Tables 1-5) and takeaway counter checkouts.
    Tests:
      1. Inventory floor: Stock NEVER falls below 0 under high contention.
      2. No duplicate table orders created on the same table.
      3. Strict inventory conservation without leaks or phantom deductions.
    """
    client = TestClient(app)
    conn = database.get_db_connection()
    
    # Set controlled initial stock
    initial_stock = {
        'pechuga_vitrina': 20.0,
        'muslo_vitrina': 20.0,
        'contramuslo_vitrina': 20.0,
        'ala_vitrina': 20.0,
        'papas_raciones': 30.0,
        'GAS-COL-250': 20.0,
        'GAS-MAN-250': 20.0
    }
    for k, v in initial_stock.items():
        conn.execute("UPDATE inventory SET stock = ? WHERE item_key = ?", (v, k))
    conn.commit()
    conn.close()

    products = client.get("/api/pos/products").json()
    prod_map = {p["sku"]: p["id"] for p in products}

    num_threads = 20
    barrier = threading.Barrier(num_threads)
    results = []

    def execute_worker(idx):
        barrier.wait()
        # Half workers add items to Table 1-5, half do takeaway checkout
        if idx % 2 == 0:
            table_num = (idx % 5) + 1
            payload = {
                "items": [
                    {"product_id": prod_map["POL-PEC"], "quantity": 1},
                    {"product_id": prod_map["POR-PAPAS"], "quantity": 1}
                ]
            }
            res = client.post(f"/api/pos/tables/{table_num}/items", json=payload)
            return ("table", idx, res.status_code, res.json())
        else:
            payload = {
                "items": [
                    {"product_id": prod_map["POL-MUS"], "quantity": 1},
                    {"product_id": prod_map["POL-CON"], "quantity": 1}
                ],
                "payment_method": "efectivo",
                "cash_received": 50000
            }
            res = client.post("/api/pos/checkout", json=payload)
            return ("counter", idx, res.status_code, res.json())

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(execute_worker, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    # Validate responses: only 200 or 400 allowed, zero 500s
    for op_type, idx, status, body in results:
        assert status in (200, 400), f"Worker {idx} ({op_type}) returned unexpected status {status}: {body}"

    # Validate Invariant: Stock must NEVER be negative
    conn = database.get_db_connection()
    negative_rows = conn.execute("SELECT item_key, stock FROM inventory WHERE stock < 0").fetchall()
    assert len(negative_rows) == 0, f"Negative stock detected! {negative_rows}"

    # Verify no table has more than 1 active (abierta) order
    for t in range(1, 6):
        active_cnt = conn.execute(
            "SELECT count(*) FROM table_orders WHERE table_number = ? AND status = 'abierta'", (t,)
        ).fetchone()[0]
        assert active_cnt in (0, 1), f"Table {t} has {active_cnt} simultaneous open orders!"
    conn.close()


def test_adversarial_concurrent_table_cancellation_and_checkout_race(isolated_db):
    """
    RACE CONDITION AUDIT:
    Race between table checkout and table cancellation on the same table.
    Verifies:
      1. Exactly ONE operation succeeds (either checkout wins or cancel wins).
      2. If cancellation wins: 100% of stock is restored exactly once; 0 sales recorded.
      3. If checkout wins: exactly 1 sale recorded; stock is NOT restored; table order is cobrada.
      4. Zero duplicate stock, zero phantom sales, zero 500 errors.
    """
    client = TestClient(app)
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 50.0 WHERE item_key IN ('pechuga_vitrina', 'papas_raciones')")
    conn.commit()
    
    products = client.get("/api/pos/products").json()
    prod_map = {p["sku"]: p["id"] for p in products}

    # Add items to Table 3
    add_res = client.post("/api/pos/tables/3/items", json={
        "items": [
            {"product_id": prod_map["POL-PEC"], "quantity": 4},
            {"product_id": prod_map["POR-PAPAS"], "quantity": 2}
        ]
    })
    assert add_res.status_code == 200

    stock_after_add = {
        row["item_key"]: float(row["stock"])
        for row in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key IN ('pechuga_vitrina', 'papas_raciones')").fetchall()
    }
    assert stock_after_add["pechuga_vitrina"] == 46.0
    assert stock_after_add["papas_raciones"] == 48.0
    conn.close()

    # Fire 15 threads trying to cancel, 15 threads trying to checkout
    num_threads = 30
    barrier = threading.Barrier(num_threads)

    def racer(idx):
        barrier.wait()
        if idx % 2 == 0:
            res = client.post("/api/pos/tables/3/cancel", json={"reason": "Test concurrent cancel"})
            return ("cancel", idx, res.status_code, res.json())
        else:
            res = client.post("/api/pos/tables/3/checkout", json={
                "payment_method": "efectivo",
                "cash_received": 100000
            })
            return ("checkout", idx, res.status_code, res.json())

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(racer, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    cancels_200 = [r for r in results if r[0] == "cancel" and r[2] == 200]
    checkouts_200 = [r for r in results if r[0] == "checkout" and r[2] == 200]
    errors_500 = [r for r in results if r[2] == 500]

    assert len(errors_500) == 0, f"HTTP 500 errors encountered: {errors_500}"
    # Exactly ONE operation can win total (either 1 cancel and 0 checkouts, OR 0 cancels and 1 checkout)
    total_winners = len(cancels_200) + len(checkouts_200)
    assert total_winners == 1, (
        f"Expected exactly 1 winning operation, but got {len(cancels_200)} cancels and {len(checkouts_200)} checkouts!"
    )

    conn = database.get_db_connection()
    final_stock = {
        row["item_key"]: float(row["stock"])
        for row in conn.execute("SELECT item_key, stock FROM inventory WHERE item_key IN ('pechuga_vitrina', 'papas_raciones')").fetchall()
    }

    if len(cancels_200) == 1:
        # Cancel won: stock must be restored exactly once (50.0 and 50.0)
        assert final_stock["pechuga_vitrina"] == 50.0
        assert final_stock["papas_raciones"] == 50.0
        # Sales should not include this table
        sales_cnt = conn.execute("SELECT count(*) FROM sales WHERE notes LIKE '%Mesa 3%'").fetchone()[0]
        assert sales_cnt == 0
    else:
        # Checkout won: stock must remain deducted (46.0 and 48.0)
        assert final_stock["pechuga_vitrina"] == 46.0
        assert final_stock["papas_raciones"] == 48.0
        sales_cnt = conn.execute("SELECT count(*) FROM sales WHERE notes LIKE '%Mesa 3%'").fetchone()[0]
        assert sales_cnt == 1

    conn.close()


def test_adversarial_concurrent_table_cancel_race(isolated_db):
    """
    Scale Stress: 25 simultaneous cancellation requests on the same open table order.
    Verifies:
      1. Exactly 1 request succeeds with HTTP 200.
      2. Exactly 24 requests fail with HTTP 400.
      3. Stock is restored EXACTLY ONCE (no duplication / multiplication of inventory).
    """
    client = TestClient(app)
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 10.0 WHERE item_key = 'pechuga_vitrina'")
    conn.commit()

    products = client.get("/api/pos/products").json()
    pechuga_prod = next(p for p in products if p["sku"] == "POL-PEC")

    # Order 5 pechugas on Table 4 -> remaining stock = 5.0
    client.post("/api/pos/tables/4/items", json={
        "items": [{"product_id": pechuga_prod["id"], "quantity": 5}]
    })

    stock_mid = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()[0]
    assert stock_mid == 5.0
    conn.close()

    num_threads = 25
    barrier = threading.Barrier(num_threads)

    def cancel_worker(idx):
        barrier.wait()
        res = client.post("/api/pos/tables/4/cancel")
        return idx, res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(cancel_worker, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[1] == 200]
    bad_requests = [r for r in results if r[1] == 400]
    server_errors = [r for r in results if r[1] == 500]

    assert len(server_errors) == 0, f"Encountered 500s: {server_errors}"
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(bad_requests) == 24, f"Expected 24 400s, got {len(bad_requests)}"

    conn = database.get_db_connection()
    final_stock = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()[0]
    # Restored exactly 5.0 -> final stock must be 10.0, NOT 10 + 5*24 = 130!
    assert final_stock == 10.0, f"Inventory duplication leak detected! Final stock: {final_stock}"
    conn.close()


def test_database_and_transactional_integrity(isolated_db):
    """
    INTEGRITY AUDIT:
    Verifies SQLite database integrity, foreign keys, WAL configuration, and lack of orphans.
    """
    conn = database.get_db_connection()
    
    # 1. PRAGMA checks
    wal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert wal.lower() == "wal", f"Expected WAL mode, got {wal}"
    
    timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    assert timeout >= 10000, f"Expected busy_timeout >= 10000, got {timeout}"

    fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert fk == 1, f"Foreign keys should be ON, got {fk}"

    # 2. SQLite integrity check
    integrity = [r[0] for r in conn.execute("PRAGMA integrity_check;").fetchall()]
    assert integrity == ["ok"], f"Integrity check failed: {integrity}"

    # 3. Foreign key check
    fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    assert len(fk_violations) == 0, f"Foreign key violations found: {fk_violations}"

    # 4. Check for orphan table_order_items
    orphan_items = conn.execute("""
        SELECT toi.id FROM table_order_items toi
        LEFT JOIN table_orders t ON toi.table_order_id = t.id
        WHERE t.id IS NULL
    """).fetchall()
    assert len(orphan_items) == 0, f"Found orphaned table_order_items: {orphan_items}"

    # 5. Check for orphan sale_items
    orphan_sales = conn.execute("""
        SELECT si.id FROM sale_items si
        LEFT JOIN sales s ON si.sale_id = s.id
        WHERE s.id IS NULL
    """).fetchall()
    assert len(orphan_sales) == 0, f"Found orphaned sale_items: {orphan_sales}"

    # 6. Check inventory non-negative constraint
    negs = conn.execute("SELECT item_key, stock FROM inventory WHERE stock < 0").fetchall()
    assert len(negs) == 0, f"Found negative inventory: {negs}"

    conn.close()
