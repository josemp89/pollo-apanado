"""
Tier 3: Cross-Feature Combinations Test Suite
Covers integration flows between modules:
1. End-to-end Operational Lifecycle:
   Despiece -> Batch Cooking -> Vitrina Stock -> POS Sales -> Sale Reversal -> Inventory & Financial Audit
2. Cash Drawer Mixed Payments Reconciliation & Reversal
3. Multi-Item Order Multi-Level Inventory Atomic Deduction
4. Atomic Transaction Rollback on Partial Inventory Failure
5. Sequential Depletion & Boundary Reversal Cascade
"""

import pytest

def test_end_to_end_operational_lifecycle(client, helpers):
    """
    Simulates a full cycle:
    1. Kitchen butcher 6 whole chickens.
    2. Start kitchen timers for preparation.
    3. POS sales across combos, almuerzo, and beverages.
    4. Customer cancels one sale.
    5. Audit inventory and financial reconciliation.
    """
    init_p = helpers.get_stock("pechuga_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    init_raw = helpers.get_stock("pollo_entero_crudo")

    # Step 1: Despiece 6 pollos
    despiece_res = client.post("/api/kitchen/despiece", json={
        "whole_chickens": 6,
        "operator": "Santiago",
        "notes": "Preparacion turno almuerzo"
    })
    assert despiece_res.status_code == 200
    assert helpers.get_stock("pechuga_vitrina") == init_p + 12
    assert helpers.get_stock("pollo_entero_crudo") == init_raw - 6

    # Step 2: Start cooking batch timers
    salmuera_res = client.post("/api/kitchen/batch-timer", json={"stage": "salmuera", "total_presas": 32})
    assert salmuera_res.status_code == 200
    adobo_res = client.post("/api/kitchen/batch-timer", json={"stage": "adobo", "total_presas": 24})
    assert adobo_res.status_code == 200

    # Step 3: POS Sales
    # Sale 1: 2 Combos 1/4 Pollo (POL-14) + 2 Colombiana 400ml -> Efectivo
    sale1_res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-14"), "quantity": 2},
            {"product_id": helpers.get_product_id("GAS-COL-400"), "quantity": 2}
        ],
        "payment_method": "efectivo",
        "cash_received": 35000
    })
    assert sale1_res.status_code == 200
    assert sale1_res.json()["total_amount"] == (2 * 13000 + 2 * 3500) # 33000
    assert sale1_res.json()["change_returned"] == 2000

    # Sale 2: 1 Almuerzo Completo (Pechuga) + 1 Caldo -> Nequi
    sale2_res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("ALM-COMP"), "quantity": 1, "chosen_presa": "Pechuga"},
            {"product_id": helpers.get_product_id("POR-CALD"), "quantity": 1}
        ],
        "payment_method": "nequi_daviplata",
        "notes": "Nequi ref #77283"
    })
    assert sale2_res.status_code == 200
    sale2_id = sale2_res.json()["sale_id"]
    assert sale2_res.json()["total_amount"] == 16000 + 6000 # 22000

    # Sale 3: 1 Pollo Entero (POL-ENT) + 2 Arepas -> Datáfono
    sale3_res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-ENT"), "quantity": 1},
            {"product_id": helpers.get_product_id("POR-AREP"), "quantity": 2}
        ],
        "payment_method": "datafono"
    })
    assert sale3_res.status_code == 200
    assert sale3_res.json()["total_amount"] == 36000 + 4000 # 40000

    # Step 4: Reversal of Sale 2
    cancel_res = client.post(f"/api/pos/cancel-sale/{sale2_id}")
    assert cancel_res.status_code == 200

    # Step 5: Verification of Inventory & Cash Audit
    # Sale 2 (Pechuga + Caldo) was reverted, so only Sale 1 and Sale 3 remain active
    # Active presas deducted:
    # Sale 1: 2 muslos, 2 contramuslos, 2 papas, 2 colombiana
    # Sale 3: 2 pechugas, 2 alas, 2 muslos, 2 contramuslos, 2 papas, 2 arepas
    # Net pechugas deducted = 2 (from Sale 3)
    assert helpers.get_stock("pechuga_vitrina") == init_p + 12 - 2
    # Net alas deducted = 2 (from Sale 3)
    assert helpers.get_stock("ala_vitrina") == init_a + 12 - 2
    # Net muslos deducted = 4 (2 from Sale 1 + 2 from Sale 3)
    assert helpers.get_stock("muslo_vitrina") == init_m + 12 - 4
    # Net contramuslos deducted = 4 (2 from Sale 1 + 2 from Sale 3)
    assert helpers.get_stock("contramuslo_vitrina") == init_c + 12 - 4
    # Net caldo deducted = 0 (Sale 2 caldo was cancelled)
    assert helpers.get_stock("caldo_raciones") == init_caldo + 12

    # Verify Cash Summary
    cash_summary = client.get("/api/cash/daily-summary").json()["cash_summary"]
    assert cash_summary["efectivo"] == 33000
    assert cash_summary["nequi_daviplata"] == 0 # Cancelled sale excluded
    assert cash_summary["datafono"] == 40000
    assert cash_summary["gran_total"] == 73000
    assert cash_summary["total_tickets"] == 2


def test_cash_drawer_mixed_payment_reconciliation(client, helpers):
    """
    Tests cash drawer reconciliation with mixed payments and a voided cash sale.
    """
    p_id = helpers.get_product_id("POL-PEC")

    # Sale 1: Efectivo 9000
    s1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    }).json()["sale_id"]

    # Sale 2: Efectivo 18000
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_id, "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })

    # Sale 3: Nequi 9000
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_id, "quantity": 1}],
        "payment_method": "nequi_daviplata"
    })

    # Sale 4: Datafono 9000
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_id, "quantity": 1}],
        "payment_method": "datafono"
    })

    # Reconcile before cancellation
    summary_before = client.get("/api/cash/daily-summary").json()["cash_summary"]
    assert summary_before["efectivo"] == 27000
    assert summary_before["nequi_daviplata"] == 9000
    assert summary_before["datafono"] == 9000
    assert summary_before["gran_total"] == 45000
    assert summary_before["total_tickets"] == 4

    # Cancel Sale 1 (Efectivo 9000)
    client.post(f"/api/pos/cancel-sale/{s1}")

    # Reconcile after cancellation
    summary_after = client.get("/api/cash/daily-summary").json()["cash_summary"]
    assert summary_after["efectivo"] == 18000
    assert summary_after["nequi_daviplata"] == 9000
    assert summary_after["datafono"] == 9000
    assert summary_after["gran_total"] == 36000
    assert summary_after["total_tickets"] == 3


def test_multi_item_order_atomic_deduction(client, helpers):
    """
    A single transaction with 4 distinct product categories:
    Combos, Almuerzo, Drinks, and Sides.
    Verifies that all 10 inventory line items are updated simultaneously.
    """
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    init_caldo = helpers.get_stock("caldo_raciones")
    init_arroz = helpers.get_stock("arroz_raciones")
    init_frij = helpers.get_stock("frijoles_raciones")
    init_soda = helpers.get_stock("GAS-COL-400")
    init_arep = helpers.get_stock("arepas_unidades")

    # Order contains:
    # 1 POL-12 (1/2 Pollo: 1P, 1A, 1M, 1C, 1 papas)
    # 1 ALM-COMP with Pechuga (1P, 1 caldo, 1 arroz, 1 frijoles)
    # 1 GAS-COL-400 (1 soda)
    # 2 POR-AREP (2 arepas)
    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-12"), "quantity": 1},
            {"product_id": helpers.get_product_id("ALM-COMP"), "quantity": 1, "chosen_presa": "Pechuga"},
            {"product_id": helpers.get_product_id("GAS-COL-400"), "quantity": 1},
            {"product_id": helpers.get_product_id("POR-AREP"), "quantity": 2}
        ],
        "payment_method": "datafono"
    })
    assert res.status_code == 200
    expected_total = 20000 + 16000 + 3500 + 2 * 2000
    assert res.json()["total_amount"] == expected_total

    # Assert all deductions
    assert helpers.get_stock("pechuga_vitrina") == init_p - 2 # 1 from combo + 1 from almuerzo
    assert helpers.get_stock("ala_vitrina") == init_a - 1
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 1
    assert helpers.get_stock("papas_raciones") == init_papas - 1
    assert helpers.get_stock("caldo_raciones") == init_caldo - 1
    assert helpers.get_stock("arroz_raciones") == init_arroz - 1
    assert helpers.get_stock("frijoles_raciones") == init_frij - 1
    assert helpers.get_stock("GAS-COL-400") == init_soda - 1
    assert helpers.get_stock("arepas_unidades") == init_arep - 2


def test_atomic_rollback_on_partial_inventory_failure(client, helpers, db_conn):
    """
    If any single item in a multi-item cart lacks sufficient stock,
    the ENTIRE transaction must be rejected with HTTP 400 and NO item stock may be deducted.
    """
    helpers.set_stock("pechuga_vitrina", 10.0)
    helpers.set_stock("arepas_unidades", 1.0)
    sales_count_before = helpers.count_sales()

    # Order requests 2 Pechugas (in stock) AND 5 Arepas (insufficient stock)
    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-PEC"), "quantity": 2},
            {"product_id": helpers.get_product_id("POR-AREP"), "quantity": 5}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 400
    assert "Stock insuficiente" in res.json()["detail"]

    # Verify atomic rollback: pechuga was NOT deducted
    assert helpers.get_stock("pechuga_vitrina") == 10.0
    assert helpers.get_stock("arepas_unidades") == 1.0
    # Verify no orphan sales row was inserted
    assert helpers.count_sales() == sales_count_before


def test_sequential_depletion_and_boundary_reversal(client, helpers):
    """
    Tests sequential checkouts down to depletion followed by cancellation and recovery:
    1. Stock starts at 3.
    2. Buy 2 -> stock = 1.
    3. Buy 2 -> rejected (insufficient), stock = 1.
    4. Buy 1 -> stock = 0.
    5. Buy 1 -> rejected (0 stock), stock = 0.
    6. Cancel Order 4 -> stock restored to 1!
    7. Buy 1 -> succeeds, stock = 0.
    """
    helpers.set_stock("GAS-ZER-400", 3.0)
    prod_id = helpers.get_product_id("GAS-ZER-400")

    # Step 1: Buy 2
    r1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert r1.status_code == 200
    assert helpers.get_stock("GAS-ZER-400") == 1.0

    # Step 2: Try to buy 2 (fails)
    r2 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert r2.status_code == 400
    assert helpers.get_stock("GAS-ZER-400") == 1.0

    # Step 3: Buy 1 (succeeds, depletes to 0)
    r3 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 5000
    })
    assert r3.status_code == 200
    sale3_id = r3.json()["sale_id"]
    assert helpers.get_stock("GAS-ZER-400") == 0.0

    # Step 4: Try to buy 1 on 0 stock (fails)
    r4 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 5000
    })
    assert r4.status_code == 400
    assert helpers.get_stock("GAS-ZER-400") == 0.0

    # Step 5: Cancel Step 3 sale -> stock restored to 1.0
    cancel_res = client.post(f"/api/pos/cancel-sale/{sale3_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("GAS-ZER-400") == 1.0

    # Step 6: Buy 1 again -> succeeds
    r6 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 5000
    })
    assert r6.status_code == 200
    assert helpers.get_stock("GAS-ZER-400") == 0.0
