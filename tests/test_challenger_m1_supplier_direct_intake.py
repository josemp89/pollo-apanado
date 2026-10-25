import os
import tempfile
import pytest
from fastapi.testclient import TestClient
import app.database as database
from app.main import app

@pytest.fixture(autouse=True)
def isolated_test_db(monkeypatch):
    """Isolated SQLite WAL database for test idempotency."""
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

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

class TestChallengerSupplierDirectIntake:
    """
    Milestone 1 Empirical Challenge:
    Verifies direct supply intake to Vitrina, Bodega, and Nevera,
    instant live initial stock adjustments, and zero UI links to /cocina.
    """

    def test_templates_have_no_cocina_links(self, client):
        """Verify active UI views (index, cash, tutorial) have zero links to /cocina."""
        for path in ["/", "/caja", "/tutorial"]:
            res = client.get(path)
            assert res.status_code == 200
            assert 'href="/cocina"' not in res.text, f"Active view '{path}' contains orphaned link href='/cocina'"

    def test_cocina_endpoint_redirects_cleanly(self, client):
        """GET /cocina must return 307 redirecting to '/'."""
        res_no_follow = client.get("/cocina", follow_redirects=False)
        assert res_no_follow.status_code == 307
        assert res_no_follow.headers.get("location") == "/"

        res_followed = client.get("/cocina", follow_redirects=True)
        assert res_followed.status_code == 200
        assert "Punto de Venta Mostrador" in res_followed.text

    def test_supplier_entry_direct_intake_vitrina_bodega_nevera(self, client):
        """
        Supplier intake to Vitrina, Bodega, and Nevera directly increments inventory
        without requiring any kitchen butchering (despiece) or timer action.
        """
        conn = database.get_db_connection()
        initial_stocks = {
            r["item_key"]: float(r["stock"])
            for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
        }
        conn.close()

        # 1. Supplier entry to Vitrina: Pechugas
        res_vit = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "Avícola Santa Rita",
            "invoice_number": "FAC-VIT-001",
            "item_name": "Pechugas en Vitrina",
            "location": "Vitrina",
            "quantity": 20.0,
            "unit_cost": 4800.0,
            "notes": "Direct intake to vitrina"
        })
        assert res_vit.status_code == 200
        data_vit = res_vit.json()
        assert data_vit["success"] is True
        assert data_vit["new_stock"] == initial_stocks["pechuga_vitrina"] + 20.0

        # 2. Supplier entry to Bodega: Pollos Enteros Crudos
        res_bod = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "Avícola Central",
            "invoice_number": "FAC-BOD-002",
            "item_name": "Pollos Enteros Crudos (Bodega)",
            "location": "Bodega",
            "quantity": 30.0,
            "unit_cost": 17500.0,
            "notes": "Direct intake to bodega"
        })
        assert res_bod.status_code == 200
        data_bod = res_bod.json()
        assert data_bod["success"] is True
        assert data_bod["new_stock"] == initial_stocks["pollo_entero_crudo"] + 30.0

        # 3. Supplier entry to Nevera: Coca-Cola 400ml
        res_nev = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "FEMSA Coca-Cola",
            "invoice_number": "FAC-NEV-003",
            "item_name": "Coca-Cola 400ml (Nevera)",
            "location": "Nevera",
            "quantity": 48.0,
            "unit_cost": 2100.0,
            "notes": "Direct intake to nevera"
        })
        assert res_nev.status_code == 200
        data_nev = res_nev.json()
        assert data_nev["success"] is True
        assert data_nev["new_stock"] == initial_stocks["GAS-COC-400"] + 48.0

        # 4. Check DB directly for verified persistence
        conn = database.get_db_connection()
        updated_stocks = {
            r["item_key"]: float(r["stock"])
            for r in conn.execute("SELECT item_key, stock FROM inventory").fetchall()
        }
        receptions = conn.execute("SELECT entry_code, item_name, quantity FROM merchandise_entries").fetchall()
        conn.close()

        assert updated_stocks["pechuga_vitrina"] == initial_stocks["pechuga_vitrina"] + 20.0
        assert updated_stocks["pollo_entero_crudo"] == initial_stocks["pollo_entero_crudo"] + 30.0
        assert updated_stocks["GAS-COC-400"] == initial_stocks["GAS-COC-400"] + 48.0
        assert len(receptions) == 3

    def test_direct_pos_sale_using_supplier_stock(self, client):
        """Verify POS checkout immediately sells the fresh supplier stock with zero kitchen action."""
        # Add stock to Vitrina directly
        client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "Avícola Santa Rita",
            "invoice_number": "FAC-VIT-002",
            "item_name": "Pechugas en Vitrina",
            "location": "Vitrina",
            "quantity": 10.0,
            "unit_cost": 4800.0
        })

        prods = {p["sku"]: p["id"] for p in client.get("/api/pos/products").json()}

        conn = database.get_db_connection()
        stock_before = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
        conn.close()

        # Buy 5 Pechugas
        res_sale = client.post("/api/pos/checkout", json={
            "items": [
                {"product_id": prods["POL-PEC"], "quantity": 5}
            ],
            "payment_method": "efectivo",
            "cash_received": 50000
        })
        assert res_sale.status_code == 200
        sale_data = res_sale.json()
        assert sale_data["success"] is True

        conn = database.get_db_connection()
        stock_after = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
        conn.close()

        assert stock_after == stock_before - 5.0

    def test_set_initial_stock_snapshot_only(self, client):
        """
        Verify /api/inventory/set-initial-stock with update_live_stock=False:
        updates daily snapshot without altering live stock.
        """
        res_snap = client.post("/api/inventory/set-initial-stock", json={
            "date": "2026-10-25",
            "recorded_by": "test_supervisor",
            "update_live_stock": False,
            "items": [
                {"item_name": "Pechugas en Vitrina", "location": "Vitrina", "initial_stock": 33.0}
            ]
        })
        assert res_snap.status_code == 200
        assert res_snap.json()["recorded_count"] == 1

        conn = database.get_db_connection()
        stock_pechuga_live = conn.execute(
            "SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'"
        ).fetchone()["stock"]
        snap_pechuga = conn.execute(
            "SELECT quantity FROM daily_initial_inventory WHERE date = '2026-10-25' AND item_name = 'Pechugas en Vitrina'"
        ).fetchone()["quantity"]
        conn.close()

        # Initial seed for pechuga_vitrina is 12.0
        assert stock_pechuga_live == 12.0, "Live stock was altered even though update_live_stock=False"
        assert snap_pechuga == 33.0, "Snapshot in daily_initial_inventory was not updated to 33.0"

    def test_set_initial_stock_live_update_bug_reproduction(self, client):
        """
        EMPIRICAL BUG FIX VERIFICATION:
        When update_live_stock=True, /api/inventory/set-initial-stock executes
        `UPDATE inventory SET stock = ? WHERE id = ?;` using `inv_match['id']`.
        With 'id' in the SELECT projection, this returns 200 and updates live stock.
        """
        res_live = client.post("/api/inventory/set-initial-stock", json={
            "date": "2026-10-25",
            "recorded_by": "test_supervisor",
            "update_live_stock": True,
            "items": [
                {"item_name": "Pechugas en Vitrina", "location": "Vitrina", "initial_stock": 75.0}
            ]
        })
        assert res_live.status_code == 200, f"Expected 200 after fix, got {res_live.status_code}: {res_live.text}"
        assert res_live.json().get("success") is True
        assert res_live.json().get("recorded_count") == 1

        conn = database.get_db_connection()
        updated_stock = conn.execute(
            "SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'"
        ).fetchone()["stock"]
        conn.close()
        assert updated_stock == 75.0, f"Live stock expected 75.0, got {updated_stock}"

    def test_supplier_entry_validation_adversarial(self, client):
        """Adversarial stress test on supplier entry constraints."""
        # Non-positive quantities rejected (validation handler in main.py converts RequestValidationError to 400)
        res_neg = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "Proveedor Malicioso",
            "invoice_number": "INV-ERR-1",
            "item_name": "Pechugas en Vitrina",
            "location": "Vitrina",
            "quantity": -10.0
        })
        assert res_neg.status_code == 400

        res_zero = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "Proveedor Malicioso",
            "invoice_number": "INV-ERR-2",
            "item_name": "Pechugas en Vitrina",
            "location": "Vitrina",
            "quantity": 0.0
        })
        assert res_zero.status_code == 400

        # Empty required strings rejected
        res_empty = client.post("/api/inventory/supplier-entry", json={
            "supplier_name": "",
            "invoice_number": "INV-ERR-3",
            "item_name": "Pechugas en Vitrina",
            "location": "Vitrina",
            "quantity": 5.0
        })
        assert res_empty.status_code == 400
