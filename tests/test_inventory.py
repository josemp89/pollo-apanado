import pytest
from datetime import datetime
import concurrent.futures
from app.database import get_db_connection

# ==================== TESTS: R2 ENTRADA DE PROVEEDORES ====================

def test_supplier_entry_atomic_stock_increment(client):
    """
    R2: Registra una entrada de proveedor e incrementa atómicamente el stock en bodega.
    """
    # Stock previo de pollos crudos en bodega
    conn = get_db_connection()
    prev_stock = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()["stock"]
    conn.close()

    res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola Los Pollos S.A.S.",
        "invoice_number": "FAC-2026-001",
        "item_name": "pollo_entero_crudo",
        "location": "Bodega",
        "quantity": 25.0,
        "unit_cost": 12000.0,
        "total_cost": 300000.0,
        "notes": "Lote fresco con cadena de frío certificada"
    })

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["entry_code"].startswith("REC-")
    assert data["new_stock"] == prev_stock + 25.0
    assert data["item_name"] == "pollo_entero_crudo"
    assert data["location"] == "Bodega"

    # Verificar persistencia en base de datos
    conn = get_db_connection()
    new_db_stock = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()["stock"]
    assert new_db_stock == prev_stock + 25.0

    entry = conn.execute("SELECT * FROM merchandise_entries WHERE entry_code = ?", (data["entry_code"],)).fetchone()
    assert entry is not None
    assert entry["supplier_name"] == "Avícola Los Pollos S.A.S."
    assert entry["invoice_number"] == "FAC-2026-001"
    assert entry["quantity"] == 25.0
    assert entry["unit_cost"] == 12000.0
    assert entry["total_cost"] == 300000.0
    conn.close()

def test_supplier_entry_auto_cost_calculation(client):
    """
    R2: Calcula total_cost automáticamente si se provee unit_cost, o viceversa.
    """
    res1 = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Postobón S.A.",
        "invoice_number": "REM-9988",
        "item_name": "GAS-COL-400",
        "location": "Nevera",
        "quantity": 24.0,
        "unit_cost": 2100.0,
        "total_cost": 0.0
    })
    assert res1.status_code == 200
    conn = get_db_connection()
    entry1 = conn.execute("SELECT * FROM merchandise_entries WHERE invoice_number = 'REM-9988'").fetchone()
    assert entry1["total_cost"] == 24.0 * 2100.0
    conn.close()

    res2 = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Postobón S.A.",
        "invoice_number": "REM-9989",
        "item_name": "GAS-MAN-400",
        "location": "Nevera",
        "quantity": 10.0,
        "unit_cost": 0.0,
        "total_cost": 22000.0
    })
    assert res2.status_code == 200
    conn = get_db_connection()
    entry2 = conn.execute("SELECT * FROM merchandise_entries WHERE invoice_number = 'REM-9989'").fetchone()
    assert entry2["unit_cost"] == 2200.0
    conn.close()

def test_supplier_entry_creates_new_item_if_not_present(client):
    """
    R2: Si el proveedor entrega un insumo que no existía previamente en inventario,
    se inserta una nueva fila en inventory sin error.
    """
    res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Distribuidora El Grano",
        "invoice_number": "FAC-5544",
        "item_name": "Salsa Tártara Especial 1L",
        "location": "Cocina",
        "quantity": 12.0,
        "unit_cost": 8500.0,
        "total_cost": 102000.0
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["new_stock"] == 12.0

    conn = get_db_connection()
    row = conn.execute("SELECT * FROM inventory WHERE name = 'Salsa Tártara Especial 1L'").fetchone()
    assert row is not None
    assert row["stock"] == 12.0
    assert row["category"] == "cocina"
    conn.close()

def test_supplier_entry_validations(client):
    """
    R2: Validación estricta de parámetros obligatorios y cantidades positivas.
    """
    # Cantidad <= 0 rechazada
    res_zero = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola",
        "invoice_number": "F1",
        "item_name": "pollo_entero_crudo",
        "location": "Bodega",
        "quantity": 0.0
    })
    assert res_zero.status_code in [400, 422]

    res_neg = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola",
        "invoice_number": "F1",
        "item_name": "pollo_entero_crudo",
        "location": "Bodega",
        "quantity": -5.0
    })
    assert res_neg.status_code in [400, 422]

    # Campos vacíos
    res_empty_sup = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "",
        "invoice_number": "F1",
        "item_name": "pollo_entero_crudo",
        "location": "Bodega",
        "quantity": 10.0
    })
    assert res_empty_sup.status_code in [400, 422]

def test_get_supplier_entries_history(client):
    """
    R2: Consulta de historial con conteo total y suma de inversión en compras.
    """
    # Registrar dos recepciones
    client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Molino Central",
        "invoice_number": "HAR-101",
        "item_name": "harina_apanar_kg",
        "location": "Bodega",
        "quantity": 50.0,
        "unit_cost": 3000.0,
        "total_cost": 150000.0
    })
    client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Aceites del Llano",
        "invoice_number": "ACE-202",
        "item_name": "aceite_fritura_lt",
        "location": "Bodega",
        "quantity": 60.0,
        "unit_cost": 7000.0,
        "total_cost": 420000.0
    })

    today = datetime.now().strftime("%Y-%m-%d")
    res = client.get(f"/api/inventory/supplier-entries?date={today}")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] >= 2
    assert data["total_value_cop"] >= 570000.0

    invoices = [e["invoice_number"] for e in data["entries"]]
    assert "HAR-101" in invoices
    assert "ACE-202" in invoices

# ==================== TESTS: R3 CONCILIACIÓN DE INVENTARIO ====================

def test_set_and_get_initial_stock(client):
    """
    R3: Declaración del inventario matutino de apertura y consulta de conciliación.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    res = client.post("/api/inventory/set-initial-stock", json={
        "date": today,
        "items": [
            {"item_name": "Pollos Enteros Crudos (Bodega)", "location": "Bodega", "quantity": 20.0},
            {"item_name": "Pechugas en Vitrina", "location": "Vitrina", "quantity": 15.0},
            {"item_name": "Postobón Colombiana 400ml (Nevera)", "location": "Nevera", "quantity": 30.0}
        ],
        "recorded_by": "Santiago"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["recorded_count"] == 3

    # Reemplazo idempotente sin error de duplicación
    res2 = client.post("/api/inventory/set-initial-stock", json={
        "date": today,
        "items": [
            {"item_name": "Pollos Enteros Crudos (Bodega)", "location": "Bodega", "quantity": 22.0}
        ]
    })
    assert res2.status_code == 200
    conn = get_db_connection()
    row = conn.execute("""
        SELECT quantity FROM daily_initial_inventory 
        WHERE date = ? AND item_name = 'Pollos Enteros Crudos (Bodega)' AND location = 'Bodega'
    """, (today,)).fetchone()
    assert row["quantity"] == 22.0
    conn.close()

def test_daily_reconciliation_zero_drift_clean_day(client):
    """
    R3: Al inicio de la jornada, el inventario reconciliado reporta CERO DERIVA (is_balanced: True).
    """
    res = client.get("/api/inventory/daily-reconciliation")
    assert res.status_code == 200
    data = res.json()
    assert data["is_balanced"] is True
    assert len(data["items"]) > 0

    for item in data["items"]:
        assert item["drift"] == 0.0
        assert item["is_balanced"] is True
        assert item["expected_stock"] == item["current_stock"]

def test_daily_reconciliation_mathematical_conservation_with_entries_and_sales(client):
    """
    R3: Verifica la ley de conservación matemática:
    Stock Físico Esperado = Stock Inicial + Entradas Proveedor - Ventas
    Con drift = 0.0 al ocurrir recepciones y ventas.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Fijar stock inicial de gaseosas en 24
    client.post("/api/inventory/set-initial-stock", json={
        "date": today,
        "items": [
            {"item_name": "Postobón Colombiana 400ml (Nevera)", "location": "Nevera", "quantity": 24.0}
        ]
    })

    # Asegurar que el stock live coincida con el stock inicial fijado
    conn = get_db_connection()
    conn.execute("UPDATE inventory SET stock = 24.0 WHERE item_key = 'GAS-COL-400'")
    conn.commit()
    conn.close()

    # 2. Entrada de proveedor: +12 unidades
    entry_res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Postobón S.A.",
        "invoice_number": "FAC-TEST-CONSERVE",
        "item_name": "Postobón Colombiana 400ml (Nevera)",
        "location": "Nevera",
        "quantity": 12.0,
        "unit_cost": 2200.0,
        "total_cost": 26400.0
    })
    assert entry_res.status_code == 200
    assert entry_res.json()["new_stock"] == 36.0

    # 3. Venta POS: venta de 6 unidades
    sale_res = client.post("/api/pos/checkout", json={
        "payment_method": "efectivo",
        "cash_received": 50000,
        "items": [
            {"product_id": 14, "quantity": 6} # GAS-COL-400
        ]
    })
    assert sale_res.status_code == 200

    # 4. Consultar conciliación diaria
    rec_res = client.get(f"/api/inventory/daily-reconciliation?date={today}")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()

    col_item = next(it for it in rec_data["items"] if it.get("item_key") == "GAS-COL-400" or ("Colombiana" in it["item_name"] and "400ml" in it["item_name"]))
    assert col_item["initial_stock"] == 24.0
    assert col_item["supplier_entries"] == 12.0
    assert col_item["sales_dispatches"] == 6.0
    # Expected: 24 + 12 - 6 = 30.0
    assert col_item["expected_stock"] == 30.0
    assert col_item["current_stock"] == 30.0
    assert col_item["drift"] == 0.0
    assert col_item["is_balanced"] is True

def test_daily_reconciliation_detects_unrecorded_drift(client):
    """
    R3: Detecta inmediatamente discrepancias o mermas si el stock físico no cuadra con la fórmula.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # Fijar stock inicial
    client.post("/api/inventory/set-initial-stock", json={
        "date": today,
        "items": [
            {"item_name": "Coca-Cola 400ml (Nevera)", "location": "Nevera", "quantity": 20.0}
        ]
    })

    conn = get_db_connection()
    # Simular sustracción/pérdida no registrada: en vez de 20 hay 16 físicamente
    conn.execute("UPDATE inventory SET stock = 16.0 WHERE item_key = 'GAS-COC-400'")
    conn.commit()
    conn.close()

    rec_res = client.get(f"/api/inventory/daily-reconciliation?date={today}")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()

    coc_item = next(it for it in rec_data["items"] if "GAS-COC-400" in it["item_name"] or "Coca-Cola 400ml" in it["item_name"])
    assert coc_item["initial_stock"] == 20.0
    assert coc_item["expected_stock"] == 20.0
    assert coc_item["current_stock"] == 16.0
    assert coc_item["drift"] == -4.0 # Faltante de 4 unidades
    assert coc_item["is_balanced"] is False
    assert rec_data["is_balanced"] is False

# ==================== TESTS: CONCURRENCIA BAJO SQLITE WAL ====================

def test_supplier_entries_high_concurrency(client):
    """
    R2/R5: Comprueba que múltiples recepciones concurrentes no generan bloqueos ni colisiones
    en los identificadores únicos 'entry_code' bajo SQLite WAL.
    """
    def make_entry(idx):
        return client.post("/api/inventory/supplier-entry", json={
            "supplier_name": f"Proveedor Concurrente {idx}",
            "invoice_number": f"INV-CONC-{idx}",
            "item_name": "harina_apanar_kg",
            "location": "Bodega",
            "quantity": 1.0,
            "unit_cost": 3000.0,
            "total_cost": 3000.0
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(make_entry, range(20)))

    for res in results:
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True

    # Validar que todos los entry_codes son distintos
    entry_codes = [r.json()["entry_code"] for r in results]
    assert len(entry_codes) == len(set(entry_codes))
