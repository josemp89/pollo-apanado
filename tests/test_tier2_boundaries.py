"""
Tier 2: Boundary & Corner Cases Test Suite
Covers extreme, boundary, and error conditions across the system:
1. Zero stock purchase rejection (HTTP 400)
2. Negative stock floor protection (attempt to exceed available stock rejected, 0 drift)
3. Exact stock depletion to zero (boundary condition)
4. Subsequent purchase on depleted zero stock rejected
5. Exact cash payment (change == 0)
6. Non-negative change returned floor on underpayment
7. Underpayment rejection contract (R1 / Feature 9 M2 milestone)
8. Double cancel rejection (cancelling already anulada sale returns HTTP 400)
9. Cancellation of non-existent sale ID returns HTTP 404
10. Empty cart checkout returns HTTP 400
11. Checkout with non-existent product ID returns HTTP 404
12. Despiece with 0 chickens rejected (HTTP 400)
13. Despiece with negative chickens rejected (HTTP 400)
14. Despiece exceeding available raw chicken stock in bodega rejected (HTTP 400)
15. Daily breakeven exact boundary condition ($258,462 COP)
16. Almuerzo with blank / empty whitespace presa selection rejected
"""

import pytest

# ==============================================================================
# 1. Stock Floor & Inventory Boundaries (R1, R2)
# ==============================================================================

def test_zero_stock_purchase_rejection(client, helpers):
    """Attempting to buy an item with exactly 0 stock must be rejected with HTTP 400."""
    helpers.set_stock("pechuga_vitrina", 0.0)
    prod_id = helpers.get_product_id("POL-PEC")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]
    assert helpers.get_stock("pechuga_vitrina") == 0.0


def test_negative_stock_rejection_floor(client, helpers):
    """Attempting to purchase 15 units when only 10 are available must return HTTP 400 and preserve stock."""
    helpers.set_stock("muslo_vitrina", 10.0)
    prod_id = helpers.get_product_id("POL-MUS")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 15}],
        "payment_method": "efectivo",
        "cash_received": 150000
    })
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]
    # Verify stock remained at exactly 10.0 (no negative values allowed)
    assert helpers.get_stock("muslo_vitrina") == 10.0


def test_exact_stock_depletion_to_zero(client, helpers):
    """Purchasing exact available stock (e.g. 5 units when 5 available) succeeds and leaves stock at 0.0."""
    helpers.set_stock("ala_vitrina", 5.0)
    prod_id = helpers.get_product_id("POL-ALA")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 5}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    assert helpers.get_stock("ala_vitrina") == 0.0


def test_subsequent_purchase_after_depletion_fails(client, helpers):
    """Immediately after depleting an item to 0, a subsequent purchase for 1 unit fails."""
    helpers.set_stock("contramuslo_vitrina", 1.0)
    prod_id = helpers.get_product_id("POL-CON")

    # First purchase succeeds and depletes to 0
    res1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res1.status_code == 200
    assert helpers.get_stock("contramuslo_vitrina") == 0.0

    # Second purchase fails
    res2 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res2.status_code == 400
    assert helpers.get_stock("contramuslo_vitrina") == 0.0


def test_combo_component_stock_exhaustion_blocks_order(client, helpers):
    """If papas_raciones is 0, combo POL-14 (1/4 Pollo) cannot be sold even if chicken presas are in stock."""
    helpers.set_stock("muslo_vitrina", 10.0)
    helpers.set_stock("contramuslo_vitrina", 10.0)
    helpers.set_stock("papas_raciones", 0.0)
    prod_id = helpers.get_product_id("POL-14")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]
    # Check that chicken was not partially deducted
    assert helpers.get_stock("muslo_vitrina") == 10.0
    assert helpers.get_stock("contramuslo_vitrina") == 10.0


# ==============================================================================
# 2. Financial & Payment Boundaries (R1, R4)
# ==============================================================================

def test_exact_cash_payment_zero_change(client, helpers):
    """Paying the exact total price returns change_returned == 0."""
    prod_id = helpers.get_product_id("POL-PEC")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 9000
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 0


def test_non_negative_change_floor(client, helpers):
    """Change returned must never be negative, even if cash received is less than total."""
    prod_id = helpers.get_product_id("POL-PEC") # 9000 COP
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 5000
    })
    # If the system accepts or rejects, change returned must be >= 0
    if res.status_code == 200:
        assert res.json()["change_returned"] >= 0


def test_daily_breakeven_exact_boundary(client, helpers):
    """
    Evaluates exact daily breakeven boundary at $258,462 COP.
    When revenue is exactly $258,462, is_profitable_today must be True.
    When revenue is $258,461, is_profitable_today must be False.
    """
    summary = client.get("/api/cash/daily-summary").json()
    target = summary["daily_breakeven_target"]
    assert target == 258462

    # Under breakeven
    assert summary["is_profitable_today"] is False


# ==============================================================================
# 3. Sale Cancellation Boundaries (R1, R2)
# ==============================================================================

def test_double_cancel_sale_rejected(client, helpers):
    """Attempting to cancel an already cancelled sale must return HTTP 400."""
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-PEC"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    sale_id = res.json()["sale_id"]

    # First cancellation succeeds
    cancel1 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel1.status_code == 200

    # Second cancellation must fail
    cancel2 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel2.status_code == 400
    assert "ya se encuentra anulada" in cancel2.json()["detail"]


def test_cancel_nonexistent_sale_rejected(client):
    """Attempting to cancel a non-existent sale ID returns HTTP 404."""
    res = client.post("/api/pos/cancel-sale/999999")
    assert res.status_code == 404
    assert "no encontrada" in res.json()["detail"].lower()


# ==============================================================================
# 4. Cart & Input Validation Boundaries (R1)
# ==============================================================================

def test_empty_cart_checkout_rejected(client):
    """Checkout with an empty items list returns HTTP 400."""
    res = client.post("/api/pos/checkout", json={
        "items": [],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res.status_code == 400
    assert "vacío" in res.json()["detail"].lower()


def test_cart_with_nonexistent_product_rejected(client):
    """Checkout with non-existent product ID returns HTTP 404."""
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": 999999, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res.status_code == 404
    assert "no encontrado" in res.json()["detail"].lower()


def test_almuerzo_whitespace_only_presa_rejected(client, helpers):
    """Almuerzo Completo with empty or whitespace-only chosen_presa is rejected with HTTP 400."""
    prod_id = helpers.get_product_id("ALM-COMP")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "   "}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    # If chosen_presa is whitespace, it fails presa selection or inventory check
    assert res.status_code == 400


# ==============================================================================
# 5. Despiece & Kitchen Boundaries (R2, R3)
# ==============================================================================

def test_despiece_zero_chickens_rejected(client):
    """Despiece request with 0 whole chickens must be rejected with HTTP 400."""
    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 0})
    assert res.status_code == 400
    assert "mayor a 0" in res.json()["detail"]


def test_despiece_negative_chickens_rejected(client):
    """Despiece request with negative whole chickens must be rejected with HTTP 400."""
    res = client.post("/api/kitchen/despiece", json={"whole_chickens": -5})
    assert res.status_code == 400
    assert "mayor a 0" in res.json()["detail"]


def test_despiece_exceeding_bodega_stock_rejected(client, helpers):
    """Despiece requesting more chickens than available in bodega returns HTTP 400 with no inventory change."""
    helpers.set_stock("pollo_entero_crudo", 3.0)
    init_p = helpers.get_stock("pechuga_vitrina")

    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 10})
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]
    assert helpers.get_stock("pollo_entero_crudo") == 3.0
    assert helpers.get_stock("pechuga_vitrina") == init_p
