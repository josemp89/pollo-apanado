import os
import sys
import tempfile
import concurrent.futures
from fastapi.testclient import TestClient

sys.path.insert(0, r"c:\Users\Alejandro\Desktop\POLLO APANADO")

import app.database as database
from app.main import app

def test_concurrent_rollback():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        temp_db = tmp.name
    
    database.DB_PATH = temp_db
    database.init_db()
    client = TestClient(app)

    # Set stock of pechugas to exactly 10
    conn = database.get_db_connection()
    conn.execute("UPDATE inventory SET stock = 10 WHERE item_key = 'pechuga_vitrina'")
    conn.commit()
    conn.close()

    pechuga = next(p for p in client.get("/api/pos/products").json() if p["sku"] == "POL-PEC")

    def buy_one(i):
        payload = {
            "items": [{"product_id": pechuga["id"], "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        }
        res = client.post("/api/pos/checkout", json=payload)
        return res.status_code, res.json()

    print("Launching 50 concurrent checkouts for 10 available pechugas...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(buy_one, range(50)))

    status_200 = [r for r in results if r[0] == 200]
    status_400 = [r for r in results if r[0] == 400]
    status_other = [r for r in results if r[0] not in (200, 400)]

    print(f"Successes (HTTP 200): {len(status_200)}")
    print(f"Rejected (HTTP 400): {len(status_400)}")
    print(f"Other statuses: {len(status_other)} -> {status_other}")

    stock_final = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    print(f"Final stock in vitrina: {stock_final} (expected: 0)")

    # Check sale_codes
    sale_codes = [r[1]["sale_code"] for r in status_200]
    print(f"Unique sale codes count: {len(set(sale_codes))} out of {len(sale_codes)}")

    # Check database sales count
    conn = database.get_db_connection()
    db_sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    print(f"Sales recorded in DB: {db_sales} (expected: 10)")
    conn.close()

    # Cleanup
    try:
        os.remove(temp_db)
        if os.path.exists(f"{temp_db}-wal"): os.remove(f"{temp_db}-wal")
        if os.path.exists(f"{temp_db}-shm"): os.remove(f"{temp_db}-shm")
    except Exception:
        pass

if __name__ == "__main__":
    test_concurrent_rollback()
