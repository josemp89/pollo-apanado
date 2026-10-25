"""
Test Suite: Verificación Oficial de Bebidas Postobón e Inventario Inicial
Valida:
1. Las 15 referencias exactas de bebidas Postobón extraídas de 'PRODUCTOS POSTOBON.txt'.
2. Costos unitarios exactos y cantidades iniciales por paquete (X12 = 12 uds, X15 = 15 uds).
3. Suma total de inventario inicial en nevera de 189 unidades.
4. Descuento atómico 1 a 1 de stock en nevera tras ventas por mostrador (POS).
5. Integración con la planilla interactiva de arqueo físico al cierre (/api/cash/closing-inventory-sheet).
6. Integración con la conciliación diaria de inventario inicial (/api/inventory/daily-reconciliation).
"""

import pytest

EXPECTED_POSTOBON_PRODUCTS = {
    "GAS-TEA-DUR-500": {"name": "Mr Tea Durazno 500ml", "stock": 12, "cost": 1125, "price": 3500},
    "GAS-TEA-LIM-500": {"name": "Mr Tea Limón 500ml", "stock": 12, "cost": 1125, "price": 3500},
    "GAS-HIT-TRO-500": {"name": "Hit Frutas Tropicales 500ml", "stock": 12, "cost": 1250, "price": 3500},
    "GAS-HIT-MAN-500": {"name": "Hit Mango 500ml", "stock": 12, "cost": 1250, "price": 3500},
    "GAS-HIT-MOR-500": {"name": "Hit Mora 500ml", "stock": 12, "cost": 1250, "price": 3500},
    "GAS-HIT-NP-500": {"name": "Hit Naranja Piña 500ml", "stock": 12, "cost": 1250, "price": 3500},
    "GAS-H2O-LIM-600": {"name": "H2OH! Lima Limón 600ml", "stock": 15, "cost": 722, "price": 3500},
    "GAS-H2O-LTA-600": {"name": "H2OH! Limonata 600ml", "stock": 15, "cost": 722, "price": 3500},
    "GAS-H2O-MAR-600": {"name": "H2OH! Maracuyá 600ml", "stock": 15, "cost": 722, "price": 3500},
    "GAS-COL-250": {"name": "Colombiana 250ml", "stock": 12, "cost": 1250, "price": 2500},
    "GAS-MAN-250": {"name": "Manzana Postobón 250ml", "stock": 12, "cost": 1250, "price": 2500},
    "GAS-HIT-MAN-1L": {"name": "Hit Mango 1L Tetra", "stock": 12, "cost": 1908, "price": 6000},
    "GAS-HIT-NP-1L": {"name": "Hit Naranja Piña 1L Tetra", "stock": 12, "cost": 1908, "price": 6000},
    "GAS-MAN-175L": {"name": "Manzana Postobón 1.75L", "stock": 12, "cost": 1875, "price": 7500},
    "GAS-PEP-175L": {"name": "Pepsi 1.75L", "stock": 12, "cost": 1875, "price": 7500},
}

def test_postobon_products_and_inventory_specs(client, db_conn):
    """
    Verifica que las 15 bebidas estén registradas con sus especificaciones exactas.
    """
    for sku, spec in EXPECTED_POSTOBON_PRODUCTS.items():
        # Verificar en products
        p_row = db_conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        assert p_row is not None, f"Producto {sku} debe existir en tabla products"
        assert p_row["price"] == spec["price"], f"Precio de {sku} debe ser {spec['price']}"
        assert p_row["cost"] == spec["cost"], f"Costo de {sku} debe ser {spec['cost']}"
        assert p_row["active"] == 1, f"Producto {sku} debe estar activo"

        # Verificar en inventory
        inv_row = db_conn.execute("SELECT * FROM inventory WHERE item_key = ?", (sku,)).fetchone()
        assert inv_row is not None, f"Item {sku} debe existir en tabla inventory"
        assert inv_row["category"] == "nevera"
        assert inv_row["location"] == "Nevera"
        assert inv_row["stock"] == spec["stock"], f"Stock inicial de {sku} debe ser {spec['stock']}"

def test_postobon_total_units_is_189(db_conn):
    """
    Verifica que la sumatoria total del inventario inicial de bebidas sea exactamente 189 unidades:
    - 2x Mr Tea 500ml x 12 = 24
    - 4x Hit 500ml x 12 = 48
    - 3x H2OH! 600ml x 15 = 45
    - 2x 250ml x 12 = 24
    - 2x Hit 1L Tetra x 12 = 24
    - 2x 1.75L x 12 = 24
    Total = 189 unidades.
    """
    skus = list(EXPECTED_POSTOBON_PRODUCTS.keys())
    placeholders = ','.join(['?'] * len(skus))
    total_qty = db_conn.execute(
        f"SELECT SUM(stock) FROM inventory WHERE item_key IN ({placeholders})", skus
    ).fetchone()[0]
    assert total_qty == 189.0, f"Total de unidades debe ser 189, obtenido: {total_qty}"

def test_postobon_closing_inventory_sheet_tracking(client):
    """
    Verifica que la planilla de arqueo físico al cierre (/api/cash/closing-inventory-sheet)
    rastree las 15 referencias en la zona Nevera con su stock y costos.
    """
    res = client.get("/api/cash/closing-inventory-sheet")
    assert res.status_code == 200
    data = res.json()
    assert "zones" in data
    assert "nevera" in data["zones"]

    nevera_items = {it["item_key"]: it for it in data["zones"]["nevera"]}
    for sku, spec in EXPECTED_POSTOBON_PRODUCTS.items():
        assert sku in nevera_items, f"{sku} debe estar listado en la zona Nevera del cierre"
        item = nevera_items[sku]
        assert item["unit_cost"] == spec["cost"]
        assert item["unit_price"] == spec["price"]

def test_postobon_pos_checkout_stock_depletion(client, db_conn):
    """
    Verifica la venta en mostrador de una gaseosa Postobón y el descuento inmediato de stock.
    """
    sku = "GAS-HIT-MAN-500"
    p_row = db_conn.execute("SELECT id, price FROM products WHERE sku = ?", (sku,)).fetchone()
    prod_id = p_row["id"]
    price = p_row["price"]

    initial_stock = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (sku,)).fetchone()["stock"]
    assert initial_stock == 12.0

    # Venta de 3 unidades en efectivo
    order_payload = {
        "items": [{"product_id": prod_id, "quantity": 3}],
        "payment_method": "efectivo",
        "cash_received": price * 3,
        "cashier_name": "Santiago"
    }
    res = client.post("/api/pos/checkout", json=order_payload)
    assert res.status_code == 200, res.text

    # Verificar que el stock en nevera se redujo a 9.0
    updated_stock = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (sku,)).fetchone()["stock"]
    assert updated_stock == 9.0

def test_postobon_daily_reconciliation_initial_stock(client):
    """
    Verifica que /api/inventory/daily-reconciliation exponga las 15 referencias de nevera.
    """
    res = client.get("/api/inventory/daily-reconciliation")
    assert res.status_code == 200
    data = res.json()
    items = {it["item_name"]: it for it in data["items"]}

    for sku, spec in EXPECTED_POSTOBON_PRODUCTS.items():
        name = spec["name"]
        assert name in items, f"Insumo '{name}' debe aparecer en daily-reconciliation"
        assert items[name]["location"] == "Nevera"
