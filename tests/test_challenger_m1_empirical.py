import re
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection, init_db

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

class TestChallengerMilestone1:
    """
    Adversarial & Empirical verification suite for Milestone 1:
    Cocina Decoupling & Navbar Normalization.
    """

    def test_cocina_redirect_without_following(self, client):
        """1. GET /cocina with follow_redirects=False must return 307 and Location '/'"""
        response = client.get("/cocina", follow_redirects=False)
        assert response.status_code == 307, f"Expected 307, got {response.status_code}"
        assert response.headers.get("location") == "/", f"Expected location '/', got {response.headers.get('location')}"

    def test_cocina_redirect_with_following(self, client):
        """2. GET /cocina with follow_redirects=True must return 200 and render Mostrador"""
        response = client.get("/cocina", follow_redirects=True)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        text = response.text
        # Verify it renders Mostrador (index.html), not kitchen.html
        assert "Punto de Venta Mostrador" in text, "Missing Mostrador marker in redirected response"
        assert "POLLO APANADO" in text
        assert "COCINA & PRODUCCIÓN" not in text, "Kitchen header leaked into redirected page"
        assert "Cronómetros de Cocina" not in text

    def test_cocina_with_query_params_redirect(self, client):
        """Adversarial: GET /cocina?param=123 should still redirect safely"""
        response = client.get("/cocina?source=legacy_bookmark", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers.get("location") == "/"

        followed = client.get("/cocina?source=legacy_bookmark", follow_redirects=True)
        assert followed.status_code == 200
        assert "Punto de Venta Mostrador" in followed.text

    def test_cocina_disallowed_methods(self, client):
        """Adversarial: POST /cocina should not be accepted (405 Method Not Allowed)"""
        res_post = client.post("/cocina", json={"test": 1})
        assert res_post.status_code == 405

        res_delete = client.delete("/cocina")
        assert res_delete.status_code == 405

    def _extract_nav_html(self, html_content: str) -> str:
        match = re.search(r"<nav[^>]*>(.*?)</nav>", html_content, re.DOTALL | re.IGNORECASE)
        assert match is not None, "Could not find <nav> section in HTML"
        return match.group(1)

    def test_navbar_normalization_index_html(self, client):
        """
        Verify index.html has strictly the 6 normalized navigation items:
        1. Mostrador (href="/")
        2. Caja (href="/caja")
        3. Stock Inicial (openSetInitialStockModal)
        4. Precios Menú (openPriceEditorModal)
        5. + Proveedores (btnOpenSupplierEntry)
        6. Instalar App (btnInstallPwa)
        """
        response = client.get("/")
        assert response.status_code == 200
        nav_html = self._extract_nav_html(response.text)

        # Count interactive elements: <a ...> and <button ...>
        interactive_tags = re.findall(r"<(?:a|button)\b[^>]*>", nav_html, re.IGNORECASE)
        assert len(interactive_tags) == 6, f"Expected exactly 6 navbar items in index.html, found {len(interactive_tags)}: {interactive_tags}"

        # Check links
        assert 'href="/"' in nav_html, "Missing Mostrador link '/'"
        assert 'href="/caja"' in nav_html, "Missing Caja link '/caja'"
        assert 'href="/cocina"' not in nav_html, "Forbidden link '/cocina' found in index navbar"
        assert 'href="/tutorial"' not in nav_html, "Forbidden link '/tutorial' found in index navbar"

        # Check buttons
        assert "openSetInitialStockModal()" in nav_html, "Missing openSetInitialStockModal() handler"
        assert "openPriceEditorModal()" in nav_html, "Missing openPriceEditorModal() handler"
        assert "openSupplierEntryModal()" in nav_html, "Missing openSupplierEntryModal() handler"
        assert "triggerPwaInstall()" in nav_html, "Missing triggerPwaInstall() handler"

        # Check required IDs
        assert 'id="btnOpenSupplierEntry"' in nav_html, "Missing id='btnOpenSupplierEntry' in index navbar"
        assert 'id="btnInstallPwa"' in nav_html, "Missing id='btnInstallPwa' in index navbar"

    def test_navbar_normalization_cash_html(self, client):
        """
        Verify cash.html has strictly the exact same 6 normalized navigation items.
        """
        response = client.get("/caja")
        assert response.status_code == 200
        nav_html = self._extract_nav_html(response.text)

        interactive_tags = re.findall(r"<(?:a|button)\b[^>]*>", nav_html, re.IGNORECASE)
        assert len(interactive_tags) == 6, f"Expected exactly 6 navbar items in cash.html, found {len(interactive_tags)}: {interactive_tags}"

        assert 'href="/"' in nav_html, "Missing Mostrador link '/'"
        assert 'href="/caja"' in nav_html, "Missing Caja link '/caja'"
        assert 'href="/cocina"' not in nav_html, "Forbidden link '/cocina' found in cash navbar"
        assert 'href="/tutorial"' not in nav_html, "Forbidden link '/tutorial' found in cash navbar"

        assert "openSetInitialStockModal()" in nav_html
        assert "openPriceEditorModal()" in nav_html
        assert "openSupplierEntryModal()" in nav_html
        assert "triggerPwaInstall()" in nav_html

        assert 'id="btnOpenSupplierEntry"' in nav_html
        assert 'id="btnInstallPwa"' in nav_html

    def test_pos_checkout_stock_and_cash_integrity(self, client):
        """
        Verify end-to-end POS checkout operates seamlessly:
        1. Supplier adds stock directly to vitrina without kitchen intervention.
        2. Read initial stock and current cash sales.
        3. Perform cash checkout for Pechuga Sola (product_id corresponding to POL-PEC).
        4. Verify stock decreases accurately in Vitrina.
        5. Verify sale is recorded and cash sales in daily summary incremented.
        """
        # 1. Direct Supplier Entry for Pechuga Vitrina
        supplier_payload = {
            "supplier_name": "Avícola El Madrugador",
            "invoice_number": "INV-EMP-TEST-001",
            "item_name": "Pechuga Fresca Vitrina",
            "location": "Vitrina",
            "quantity": 5.0,
            "unit_cost": 4500.0,
            "total_cost": 22500.0,
            "notes": "Direct supplier restock empirical test"
        }
        res_supp = client.post("/api/inventory/supplier-entry", json=supplier_payload)
        assert res_supp.status_code == 200, f"Supplier entry failed: {res_supp.text}"
        data_supp = res_supp.json()
        assert data_supp["success"] is True

        conn = get_db_connection()
        try:
            prod_row = conn.execute("SELECT id, price FROM products WHERE sku = 'POL-PEC'").fetchone()
            assert prod_row is not None, "Product POL-PEC not found"
            prod_id = prod_row["id"]
            prod_price = prod_row["price"]

            stock_before_pechuga = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
            cash_sales_before = conn.execute("""
                SELECT COALESCE(SUM(total_amount), 0) as total_cash
                FROM sales
                WHERE payment_method = 'efectivo' AND status = 'completada'
            """).fetchone()["total_cash"]
        finally:
            conn.close()

        # 2. Perform POS Checkout with cash
        checkout_payload = {
            "items": [
                {
                    "product_id": prod_id,
                    "quantity": 1
                }
            ],
            "payment_method": "efectivo",
            "cash_received": prod_price + 1000,
            "notes": "Empirical challenger test sale"
        }
        res_checkout = client.post("/api/pos/checkout", json=checkout_payload)
        assert res_checkout.status_code == 200, f"Checkout failed: {res_checkout.text}"
        checkout_data = res_checkout.json()
        assert checkout_data["success"] is True
        sale_id = checkout_data["sale_id"]
        assert sale_id > 0
        assert checkout_data["total_amount"] == prod_price
        assert checkout_data["change_returned"] == 1000

        # 3. Verify stock deduction
        conn = get_db_connection()
        try:
            stock_after_pechuga = conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
            cash_sales_after = conn.execute("""
                SELECT COALESCE(SUM(total_amount), 0) as total_cash
                FROM sales
                WHERE payment_method = 'efectivo' AND status = 'completada'
            """).fetchone()["total_cash"]
        finally:
            conn.close()

        assert stock_after_pechuga == stock_before_pechuga - 1, (
            f"Pechuga stock didn't decrease by 1! Before: {stock_before_pechuga}, After: {stock_after_pechuga}"
        )
        assert cash_sales_after == cash_sales_before + prod_price, (
            f"Cash sales did not increase by {prod_price}! Before: {cash_sales_before}, After: {cash_sales_after}"
        )

        # 4. Check Daily Cash Summary API
        res_summary = client.get("/api/cash/daily-summary")
        assert res_summary.status_code == 200
        summary_data = res_summary.json()
        assert summary_data["cash_summary"]["efectivo"] >= prod_price
        assert summary_data["cash_reconciliation"]["cash_sales"] >= prod_price

    def test_kitchen_api_backend_preservation(self, client):
        """
        Verify app.include_router(kitchen.router) is still functional for backend tests
        and internal algorithms (despiece, timers) without breaking.
        """
        res_timers = client.get("/api/kitchen/batch-timers")
        assert res_timers.status_code == 200
        data = res_timers.json()
        assert isinstance(data, list)
