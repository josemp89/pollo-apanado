import os
import sys
import tempfile
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, r"c:\Users\Alejandro\Desktop\POLLO APANADO")

import app.database as database
from app.main import app

def run_tests():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        temp_db = tmp.name
    
    database.DB_PATH = temp_db
    database.init_db()
    client = TestClient(app)
    
    print("--- 1. Testing Zero Quantity Checkout ---")
    prods = client.get("/api/pos/products").json()
    pechuga = next(p for p in prods if p["sku"] == "POL-PEC")
    
    res_zero = client.post("/api/pos/checkout", json={
        "items": [{"product_id": pechuga["id"], "quantity": 0}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    print(f"Zero quantity response: status={res_zero.status_code}, body={res_zero.json()}")
    
    print("\n--- 2. Testing Negative Quantity Checkout ---")
    stock_before = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    print(f"Stock before negative checkout: {stock_before}")
    
    res_neg = client.post("/api/pos/checkout", json={
        "items": [{"product_id": pechuga["id"], "quantity": -5}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    print(f"Negative quantity response: status={res_neg.status_code}, body={res_neg.json()}")
    stock_after = client.get("/api/pos/stock-summary").json()["pechuga_vitrina"]["stock"]
    print(f"Stock after negative checkout: {stock_after}")
    
    print("\n--- 3. Testing SQL Injection in chosen_presa ---")
    almuerzo = next(p for p in prods if p["sku"] == "ALM-COMP")
    res_sqli = client.post("/api/pos/checkout", json={
        "items": [{"product_id": almuerzo["id"], "quantity": 1, "chosen_presa": "'; DROP TABLE inventory; --"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    print(f"SQLi in chosen_presa: status={res_sqli.status_code}, body={res_sqli.json()}")
    
    print("\n--- 4. Testing Negative Cash Received ---")
    res_neg_cash = client.post("/api/pos/checkout", json={
        "items": [{"product_id": pechuga["id"], "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": -50000
    })
    print(f"Negative cash_received: status={res_neg_cash.status_code}, body={res_neg_cash.json()}")
    
    print("\n--- 5. Testing Zero / Negative Despiece ---")
    res_zero_desp = client.post("/api/kitchen/despiece", json={"whole_chickens": 0})
    print(f"Zero despiece: status={res_zero_desp.status_code}, body={res_zero_desp.json()}")
    res_neg_desp = client.post("/api/kitchen/despiece", json={"whole_chickens": -3})
    print(f"Negative despiece: status={res_neg_desp.status_code}, body={res_neg_desp.json()}")

    print("\n--- 6. Testing Negative Batch Presas in kitchen ---")
    res_neg_batch = client.post("/api/kitchen/batch-timer", json={
        "stage": "fritura",
        "total_presas": -10
    })
    print(f"Negative batch presas: status={res_neg_batch.status_code}, body={res_neg_batch.json()}")

    print("\n--- 7. Testing Invalid Stage in batch-timer ---")
    res_inv_stage = client.post("/api/kitchen/batch-timer", json={
        "stage": "nonexistent_stage",
        "total_presas": 10
    })
    print(f"Invalid stage: status={res_inv_stage.status_code}, body={res_inv_stage.json()}")

    # Cleanup
    try:
        os.remove(temp_db)
        if os.path.exists(f"{temp_db}-wal"): os.remove(f"{temp_db}-wal")
        if os.path.exists(f"{temp_db}-shm"): os.remove(f"{temp_db}-shm")
    except Exception:
        pass

if __name__ == "__main__":
    run_tests()
