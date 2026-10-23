"""
Tier 1: Feature Coverage Test Suite
Covers R1-R5 with >= 5 tests per feature across:
1. Despiece mathematical integrity (R2)
2. Single presas sales & inventory (R1, R2)
3. Combos sales & multi-component deductions (R1, R2)
4. Almuerzo completo with mandatory presa selection (R1, R2)
5. Cash change exact calculation (R1)
6. Digital payment methods (R1, R4)
7. Symmetrical sale cancellation (R1, R2)
8. Kitchen batch timers (R3)
9. Cash balance & financial summary (R4)
10. Supplier low-stock alerts (R4)
"""

import pytest
from datetime import datetime

# ==============================================================================
# 1. Despiece Mathematical Integrity (R2) — >= 5 tests
# ==============================================================================

def test_despiece_single_chicken_yield(client, helpers):
    """1 whole chicken must yield exactly 2 pechugas, 2 muslos, 2 contramuslos, 2 alas, 2 caldo raciones."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    init_raw = helpers.get_stock("pollo_entero_crudo")

    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 1, "operator": "Santiago"})
    assert res.status_code == 200
    data = res.json()
    assert data["yields"]["pechugas"] == 2
    assert data["yields"]["muslos"] == 2
    assert data["yields"]["contramuslos"] == 2
    assert data["yields"]["alas"] == 2
    assert data["yields"]["total_presas"] == 8
    assert data["yields"]["caldo_raciones"] == 2

    assert helpers.get_stock("pechuga_vitrina") == init_p + 2
    assert helpers.get_stock("muslo_vitrina") == init_m + 2
    assert helpers.get_stock("contramuslo_vitrina") == init_c + 2
    assert helpers.get_stock("ala_vitrina") == init_a + 2
    assert helpers.get_stock("caldo_raciones") == init_caldo + 2
    assert helpers.get_stock("pollo_entero_crudo") == init_raw - 1


def test_despiece_multiple_chickens_yield(client, helpers):
    """5 whole chickens must yield 10 pechugas, 10 muslos, 10 contramuslos, 10 alas, 10 caldo raciones."""
    init_raw = helpers.get_stock("pollo_entero_crudo")
    init_p = helpers.get_stock("pechuga_vitrina")

    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 5, "operator": "Santiago"})
    assert res.status_code == 200
    data = res.json()
    assert data["yields"]["pechugas"] == 10
    assert data["yields"]["muslos"] == 10
    assert data["yields"]["contramuslos"] == 10
    assert data["yields"]["alas"] == 10
    assert data["yields"]["total_presas"] == 40
    assert data["yields"]["caldo_raciones"] == 10
    assert helpers.get_stock("pechuga_vitrina") == init_p + 10
    assert helpers.get_stock("pollo_entero_crudo") == init_raw - 5


def test_despiece_large_batch_yield(client, helpers):
    """10 whole chickens must yield 20P, 20M, 20C, 20A, 20 Caldo."""
    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 10, "operator": "Carlos"})
    assert res.status_code == 200
    data = res.json()
    assert data["yields"]["total_presas"] == 80
    assert data["yields"]["caldo_raciones"] == 20


def test_despiece_deducts_bodega_stock_atomically(client, helpers):
    """Verifies that bodega stock of raw chickens decreases by exactly the butchered amount."""
    helpers.set_stock("pollo_entero_crudo", 15.0)
    res = client.post("/api/kitchen/despiece", json={"whole_chickens": 4})
    assert res.status_code == 200
    assert helpers.get_stock("pollo_entero_crudo") == 11.0


def test_despiece_creates_butchering_log_record(client, helpers, db_conn):
    """Verifies audit log creation in butchering_logs table with operator attribution and yield counts."""
    res = client.post("/api/kitchen/despiece", json={
        "whole_chickens": 3,
        "operator": "Santiago Posada",
        "notes": "Lote manana temprano"
    })
    assert res.status_code == 200

    row = db_conn.execute(
        "SELECT * FROM butchering_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["whole_chickens"] == 3
    assert row["operator"] == "Santiago Posada"
    assert row["pechugas_yield"] == 6
    assert row["muslos_yield"] == 6
    assert row["contramuslos_yield"] == 6
    assert row["alas_yield"] == 6
    assert row["caldo_bases_yield"] == 6
    assert row["notes"] == "Lote manana temprano"


def test_despiece_audit_formula_conservation(client, helpers):
    """Checks the invariant: total_presas_yield == whole_chickens * 8."""
    for n in [1, 2, 6]:
        helpers.set_stock("pollo_entero_crudo", 50.0)
        res = client.post("/api/kitchen/despiece", json={"whole_chickens": n})
        assert res.status_code == 200
        yields = res.json()["yields"]
        assert yields["total_presas"] == n * 8
        assert yields["pechugas"] + yields["muslos"] + yields["contramuslos"] + yields["alas"] == n * 8


# ==============================================================================
# 2. Single Presas Sales & Stock Deduction (R1, R2) — >= 5 tests
# ==============================================================================

def test_single_presa_pechuga_sale(client, helpers):
    """Pechuga Sola (POL-PEC, $9,000) deducts 1 from pechuga_vitrina."""
    init_stock = helpers.get_stock("pechuga_vitrina")
    prod_id = helpers.get_product_id("POL-PEC")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_amount"] == 9000
    assert data["change_returned"] == 1000
    assert helpers.get_stock("pechuga_vitrina") == init_stock - 1


def test_single_presa_muslo_sale(client, helpers):
    """Muslo Solo (POL-MUS, $9,000) deducts 1 from muslo_vitrina."""
    init_stock = helpers.get_stock("muslo_vitrina")
    prod_id = helpers.get_product_id("POL-MUS")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 9000
    })
    assert res.status_code == 200
    assert helpers.get_stock("muslo_vitrina") == init_stock - 1


def test_single_presa_contramuslo_sale(client, helpers):
    """Contramuslo Solo (POL-CON, $9,000) deducts 1 from contramuslo_vitrina."""
    init_stock = helpers.get_stock("contramuslo_vitrina")
    prod_id = helpers.get_product_id("POL-CON")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "nequi_daviplata"
    })
    assert res.status_code == 200
    assert helpers.get_stock("contramuslo_vitrina") == init_stock - 1


def test_single_presa_ala_sale(client, helpers):
    """Ala Sola (POL-ALA, $9,000) deducts 1 from ala_vitrina."""
    init_stock = helpers.get_stock("ala_vitrina")
    prod_id = helpers.get_product_id("POL-ALA")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "datafono"
    })
    assert res.status_code == 200
    assert helpers.get_stock("ala_vitrina") == init_stock - 1


def test_single_presas_multiple_quantities_in_cart(client, helpers):
    """Purchasing 2 Pechugas and 3 Alas in one order."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    p_id = helpers.get_product_id("POL-PEC")
    a_id = helpers.get_product_id("POL-ALA")

    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_id, "quantity": 2},
            {"product_id": a_id, "quantity": 3}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_amount"] == (2 * 9000 + 3 * 9000)
    assert helpers.get_stock("pechuga_vitrina") == init_p - 2
    assert helpers.get_stock("ala_vitrina") == init_a - 3


def test_single_presas_all_four_types_cart(client, helpers):
    """Purchasing 1 Pechuga, 1 Muslo, 1 Contramuslo, 1 Ala together."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_a = helpers.get_stock("ala_vitrina")

    items = [
        {"product_id": helpers.get_product_id("POL-PEC"), "quantity": 1},
        {"product_id": helpers.get_product_id("POL-MUS"), "quantity": 1},
        {"product_id": helpers.get_product_id("POL-CON"), "quantity": 1},
        {"product_id": helpers.get_product_id("POL-ALA"), "quantity": 1},
    ]
    res = client.post("/api/pos/checkout", json={
        "items": items,
        "payment_method": "efectivo",
        "cash_received": 40000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 36000
    assert helpers.get_stock("pechuga_vitrina") == init_p - 1
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 1
    assert helpers.get_stock("ala_vitrina") == init_a - 1


# ==============================================================================
# 3. Combos Sales & Multi-Component Deductions (R1, R2) — >= 5 tests
# ==============================================================================

def test_combo_cuarto_pollo_deduction(client, helpers):
    """POL-14 (1/4 Pollo + Papas, $13,000) deducts 1 muslo + 1 contramuslo + 1 papas."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-14")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 13000
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 1
    assert helpers.get_stock("papas_raciones") == init_papas - 1


def test_combo_medio_pollo_deduction(client, helpers):
    """POL-12 (1/2 Pollo + Papas, $20,000) deducts 1P + 1A + 1M + 1C + 1 papas."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-12")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 20000
    assert helpers.get_stock("pechuga_vitrina") == init_p - 1
    assert helpers.get_stock("ala_vitrina") == init_a - 1
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 1
    assert helpers.get_stock("papas_raciones") == init_papas - 1


def test_combo_pollo_entero_deduction(client, helpers):
    """POL-ENT (Pollo Entero + Papas, $36,000) deducts 2P + 2A + 2M + 2C + 2 papas."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-ENT")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 36000
    assert helpers.get_stock("pechuga_vitrina") == init_p - 2
    assert helpers.get_stock("ala_vitrina") == init_a - 2
    assert helpers.get_stock("muslo_vitrina") == init_m - 2
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 2
    assert helpers.get_stock("papas_raciones") == init_papas - 2


def test_combo_multiple_quantities_deduction(client, helpers):
    """Purchasing 2 units of POL-14 (1/4 Pollo) deducts 2 muslos, 2 contramuslos, 2 papas."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-14")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 2}],
        "payment_method": "nequi_daviplata"
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 26000
    assert helpers.get_stock("muslo_vitrina") == init_m - 2
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 2
    assert helpers.get_stock("papas_raciones") == init_papas - 2


def test_combo_with_drink_and_side_deductions(client, helpers):
    """Combo POL-14 plus Coca-Cola and Arepas in a single checkout."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_soda = helpers.get_stock("GAS-COC-400")
    init_arep = helpers.get_stock("arepas_unidades")

    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": helpers.get_product_id("POL-14"), "quantity": 1},
            {"product_id": helpers.get_product_id("GAS-COC-400"), "quantity": 1},
            {"product_id": helpers.get_product_id("POR-AREP"), "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 13000 + 4000 + 2000
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("GAS-COC-400") == init_soda - 1
    assert helpers.get_stock("arepas_unidades") == init_arep - 1


# ==============================================================================
# 4. Almuerzo Completo with Mandatory Presa Selection (R1, R2) — >= 5 tests
# ==============================================================================

def test_almuerzo_completo_with_pechuga(client, helpers):
    """ALM-COMP ($16,000) with Pechuga deducts 1 pechuga, 1 caldo, 1 arroz, 1 frijoles."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    init_arroz = helpers.get_stock("arroz_raciones")
    init_frij = helpers.get_stock("frijoles_raciones")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 16000
    assert helpers.get_stock("pechuga_vitrina") == init_p - 1
    assert helpers.get_stock("caldo_raciones") == init_caldo - 1
    assert helpers.get_stock("arroz_raciones") == init_arroz - 1
    assert helpers.get_stock("frijoles_raciones") == init_frij - 1


def test_almuerzo_completo_with_muslo(client, helpers):
    """ALM-COMP with Muslo deducts 1 muslo, 1 caldo, 1 arroz, 1 frijoles."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Muslo"}],
        "payment_method": "nequi_daviplata"
    })
    assert res.status_code == 200
    assert helpers.get_stock("muslo_vitrina") == init_m - 1
    assert helpers.get_stock("caldo_raciones") == init_caldo - 1


def test_almuerzo_completo_with_contramuslo(client, helpers):
    """ALM-COMP with Contramuslo deducts 1 contramuslo, 1 caldo, 1 arroz, 1 frijoles."""
    init_c = helpers.get_stock("contramuslo_vitrina")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Contramuslo"}],
        "payment_method": "datafono"
    })
    assert res.status_code == 200
    assert helpers.get_stock("contramuslo_vitrina") == init_c - 1


def test_almuerzo_completo_with_ala(client, helpers):
    """ALM-COMP with Ala deducts 1 ala, 1 caldo, 1 arroz, 1 frijoles."""
    init_a = helpers.get_stock("ala_vitrina")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Ala"}],
        "payment_method": "efectivo",
        "cash_received": 16000
    })
    assert res.status_code == 200
    assert helpers.get_stock("ala_vitrina") == init_a - 1


def test_almuerzo_completo_missing_presa_rejected(client, helpers):
    """ALM-COMP without chosen_presa must be rejected with HTTP 400."""
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 400
    assert "requiere elegir la presa exacta" in res.json()["detail"]


def test_almuerzo_multiple_with_distinct_presas(client, helpers):
    """Cart with two Almuerzos: 1 with Pechuga, 1 with Ala."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"},
            {"product_id": prod_id, "quantity": 1, "chosen_presa": "Ala"}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    assert res.json()["total_amount"] == 32000
    assert helpers.get_stock("pechuga_vitrina") == init_p - 1
    assert helpers.get_stock("ala_vitrina") == init_a - 1
    assert helpers.get_stock("caldo_raciones") == init_caldo - 2


# ==============================================================================
# 5. Cash Change Exact Calculation (R1) — >= 5 tests
# ==============================================================================

def test_cash_change_exact_payment(client, helpers):
    """Total 16,000, cash 16,000 -> change_returned == 0."""
    prod_id = helpers.get_product_id("ALM-COMP")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 16000
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 0


def test_cash_change_standard_round_bill(client, helpers):
    """Total 16,000, cash 20,000 -> change_returned == 4,000."""
    prod_id = helpers.get_product_id("ALM-COMP")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Muslo"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 4000


def test_cash_change_fifty_thousand_bill(client, helpers):
    """Total 13,000 (1/4 Pollo), cash 50,000 -> change_returned == 37,000."""
    prod_id = helpers.get_product_id("POL-14")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 37000


def test_cash_change_one_hundred_thousand_bill(client, helpers):
    """Total 36,000 (Pollo Entero), cash 100,000 -> change_returned == 64,000."""
    prod_id = helpers.get_product_id("POL-ENT")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 100000
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 64000


def test_cash_change_persisted_in_database(client, helpers, db_conn):
    """Verifies that cash_received and change_returned are stored correctly in sales row."""
    prod_id = helpers.get_product_id("POL-PEC")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res.status_code == 200
    sale_id = res.json()["sale_id"]

    row = db_conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    assert row["total_amount"] == 9000
    assert row["cash_received"] == 50000
    assert row["change_returned"] == 41000


# ==============================================================================
# 6. Digital Payment Methods (R1, R4) — >= 5 tests
# ==============================================================================

def test_payment_nequi_daviplata_success(client, helpers):
    """Checkout with payment_method='nequi_daviplata' sets change_returned=0 and completes."""
    prod_id = helpers.get_product_id("ALM-COMP")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "nequi_daviplata"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["payment_method"] == "nequi_daviplata"
    assert data["change_returned"] == 0


def test_payment_datafono_success(client, helpers):
    """Checkout with payment_method='datafono' sets change_returned=0 and completes."""
    prod_id = helpers.get_product_id("POL-12")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "datafono"
    })
    assert res.status_code == 200
    assert res.json()["payment_method"] == "datafono"
    assert res.json()["change_returned"] == 0


def test_digital_payment_notes_reference_stored(client, helpers, db_conn):
    """Verification that digital voucher/approval code is recorded in notes."""
    prod_id = helpers.get_product_id("POL-ENT")
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "nequi_daviplata",
        "notes": "Comprobante Nequi #M984723"
    })
    assert res.status_code == 200
    sale_id = res.json()["sale_id"]

    row = db_conn.execute("SELECT notes FROM sales WHERE id = ?", (sale_id,)).fetchone()
    assert row["notes"] == "Comprobante Nequi #M984723"


def test_digital_payments_isolated_in_cash_summary(client, helpers):
    """Digital payments are correctly counted under nequi_daviplata and datafono."""
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-14"), "quantity": 1}],
        "payment_method": "nequi_daviplata"
    })
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-12"), "quantity": 1}],
        "payment_method": "datafono"
    })

    summary = client.get("/api/cash/daily-summary").json()["cash_summary"]
    assert summary["nequi_daviplata"] == 13000
    assert summary["datafono"] == 20000
    assert summary["efectivo"] == 0


def test_digital_payment_zero_cash_received_handled(client, helpers, db_conn):
    """Digital payment with cash_received=0 does not corrupt balance or change."""
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-PEC"), "quantity": 1}],
        "payment_method": "datafono",
        "cash_received": 0
    })
    assert res.status_code == 200
    assert res.json()["change_returned"] == 0


# ==============================================================================
# 7. Symmetrical Sale Cancellation (R1, R2) — >= 5 tests
# ==============================================================================

def test_cancel_sale_single_presa_restores_stock(client, helpers):
    """Cancelling a sale of single presas restores vitrina stock exactly."""
    init_p = helpers.get_stock("pechuga_vitrina")
    prod_id = helpers.get_product_id("POL-PEC")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    sale_id = res.json()["sale_id"]
    assert helpers.get_stock("pechuga_vitrina") == init_p - 2

    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("pechuga_vitrina") == init_p


def test_cancel_sale_almuerzo_restores_chosen_presa_and_sides(client, helpers):
    """Cancelling an Almuerzo Completo restores chosen presa, caldo, arroz, frijoles."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_caldo = helpers.get_stock("caldo_raciones")
    init_arroz = helpers.get_stock("arroz_raciones")
    init_frij = helpers.get_stock("frijoles_raciones")
    prod_id = helpers.get_product_id("ALM-COMP")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Muslo"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    sale_id = res.json()["sale_id"]

    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("muslo_vitrina") == init_m
    assert helpers.get_stock("caldo_raciones") == init_caldo
    assert helpers.get_stock("arroz_raciones") == init_arroz
    assert helpers.get_stock("frijoles_raciones") == init_frij


def test_cancel_sale_combo_cuarto_restores_components(client, helpers):
    """Cancelling POL-14 (1/4 Pollo) restores 1 muslo, 1 contramuslo, 1 papas."""
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-14")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 15000
    })
    sale_id = res.json()["sale_id"]

    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("muslo_vitrina") == init_m
    assert helpers.get_stock("contramuslo_vitrina") == init_c
    assert helpers.get_stock("papas_raciones") == init_papas


def test_cancel_sale_combo_medio_restores_components(client, helpers):
    """Cancelling POL-12 (1/2 Pollo) restores 1P + 1A + 1M + 1C + 1 papas."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-12")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "datafono"
    })
    sale_id = res.json()["sale_id"]

    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("pechuga_vitrina") == init_p
    assert helpers.get_stock("ala_vitrina") == init_a
    assert helpers.get_stock("muslo_vitrina") == init_m
    assert helpers.get_stock("contramuslo_vitrina") == init_c
    assert helpers.get_stock("papas_raciones") == init_papas


def test_cancel_sale_combo_entero_restores_components(client, helpers):
    """Cancelling POL-ENT restores 2P + 2A + 2M + 2C + 2 papas."""
    init_p = helpers.get_stock("pechuga_vitrina")
    init_a = helpers.get_stock("ala_vitrina")
    init_m = helpers.get_stock("muslo_vitrina")
    init_c = helpers.get_stock("contramuslo_vitrina")
    init_papas = helpers.get_stock("papas_raciones")
    prod_id = helpers.get_product_id("POL-ENT")

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 40000
    })
    sale_id = res.json()["sale_id"]

    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert cancel_res.status_code == 200
    assert helpers.get_stock("pechuga_vitrina") == init_p
    assert helpers.get_stock("ala_vitrina") == init_a
    assert helpers.get_stock("muslo_vitrina") == init_m
    assert helpers.get_stock("contramuslo_vitrina") == init_c
    assert helpers.get_stock("papas_raciones") == init_papas


def test_cancel_sale_updates_status_to_anulada(client, helpers, db_conn):
    """Sale status is updated to 'anulada' in the database."""
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-PEC"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    })
    sale_id = res.json()["sale_id"]
    client.post(f"/api/pos/cancel-sale/{sale_id}")

    row = db_conn.execute("SELECT status FROM sales WHERE id = ?", (sale_id,)).fetchone()
    assert row["status"] == "anulada"


# ==============================================================================
# 8. Kitchen Batch Timers (R3) — >= 5 tests
# ==============================================================================

def test_kitchen_timer_salmuera_default_duration(client):
    """Salmuera batch timer defaults to 6 hours."""
    res = client.post("/api/kitchen/batch-timer", json={
        "stage": "salmuera",
        "total_presas": 40
    })
    assert res.status_code == 200
    data = res.json()
    assert data["stage"] == "salmuera"
    assert data["duration_hours"] == 6.0
    assert "LOTE-SAL-" in data["batch_code"]


def test_kitchen_timer_adobo_default_duration(client):
    """Adobo batch timer defaults to 4 hours."""
    res = client.post("/api/kitchen/batch-timer", json={
        "stage": "adobo",
        "total_presas": 32
    })
    assert res.status_code == 200
    data = res.json()
    assert data["stage"] == "adobo"
    assert data["duration_hours"] == 4.0
    assert "LOTE-ADO-" in data["batch_code"]


def test_kitchen_timer_custom_duration(client):
    """Starting a batch timer with explicit custom duration."""
    res = client.post("/api/kitchen/batch-timer", json={
        "stage": "salmuera",
        "total_presas": 24,
        "duration_hours": 7.5
    })
    assert res.status_code == 200
    assert res.json()["duration_hours"] == 7.5


def test_kitchen_get_active_timers(client):
    """Listing active batch timers returns non-terminated batches."""
    client.post("/api/kitchen/batch-timer", json={"stage": "salmuera", "total_presas": 16})
    client.post("/api/kitchen/batch-timer", json={"stage": "adobo", "total_presas": 16})

    res = client.get("/api/kitchen/batch-timers")
    assert res.status_code == 200
    batches = res.json()
    assert len(batches) >= 2


def test_kitchen_system_settings_retrieval(client):
    """GET /api/kitchen/settings returns standard system settings."""
    res = client.get("/api/kitchen/settings")
    assert res.status_code == 200
    settings = {s["key"]: s["value"] for s in res.json()}
    assert "salmuera_hours" in settings
    assert "adobo_hours" in settings
    assert "daily_breakeven_cop" in settings


def test_kitchen_update_setting(client):
    """PUT /api/kitchen/settings updates a configuration value."""
    res = client.put("/api/kitchen/settings", json={"key": "salmuera_hours", "value": "7"})
    assert res.status_code == 200

    settings_res = client.get("/api/kitchen/settings")
    settings = {s["key"]: s["value"] for s in settings_res.json()}
    assert settings["salmuera_hours"] == "7"


# ==============================================================================
# 9. Cash Balance & Financial Summary (R4) — >= 5 tests
# ==============================================================================

def test_cash_daily_summary_empty_day(client):
    """Daily summary on fresh database starts with zero totals."""
    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    data = res.json()
    assert data["cash_summary"]["gran_total"] == 0
    assert data["cash_summary"]["total_tickets"] == 0
    assert data["estimated_margin"] == 0


def test_cash_daily_summary_multiple_payment_methods(client, helpers):
    """Daily summary accurately aggregates cash, digital, and card sales."""
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-14"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-12"), "quantity": 1}],
        "payment_method": "nequi_daviplata"
    })
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-ENT"), "quantity": 1}],
        "payment_method": "datafono"
    })

    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    summary = res.json()["cash_summary"]
    assert summary["efectivo"] == 13000
    assert summary["nequi_daviplata"] == 20000
    assert summary["datafono"] == 36000
    assert summary["gran_total"] == 69000
    assert summary["total_tickets"] == 3


def test_cash_estimated_margin_calculation(client, helpers):
    """Estimated gross margin is calculated as SUM(qty * (price - cost))."""
    # POL-PEC: price 9000, cost 4500 -> margin = 4500
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-PEC"), "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    assert res.json()["estimated_margin"] == 9000


def test_cash_daily_breakeven_target_value(client):
    """Target daily breakeven is $258,462 COP."""
    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    assert res.json()["daily_breakeven_target"] == 258462


def test_cash_summary_excludes_cancelled_sales(client, helpers):
    """Cancelled sales are not counted in revenue, margin, or tickets."""
    res1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-ENT"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 40000
    })
    sale_id = res1.json()["sale_id"]

    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-14"), "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })

    # Cancel first sale
    client.post(f"/api/pos/cancel-sale/{sale_id}")

    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    summary = res.json()["cash_summary"]
    assert summary["gran_total"] == 13000
    assert summary["total_tickets"] == 1


def test_cash_breakeven_percentage_calculation(client, helpers):
    """Breakeven percentage reflects progress towards daily break-even."""
    client.post("/api/pos/checkout", json={
        "items": [{"product_id": helpers.get_product_id("POL-ENT"), "quantity": 2}],
        "payment_method": "efectivo",
        "cash_received": 80000
    })
    res = client.get("/api/cash/daily-summary")
    data = res.json()
    expected_pct = round((72000 / 258462) * 100, 1)
    assert data["breakeven_percentage"] == expected_pct


# ==============================================================================
# 10. Supplier Low-Stock Alerts (R4) — >= 5 tests
# ==============================================================================

def test_supplier_alert_when_stock_at_threshold(client, helpers):
    """Item with stock == min_threshold appears in low_stock_alerts."""
    helpers.set_stock("pollo_entero_crudo", 8.0) # min_threshold = 8
    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    alerts = res.json()["low_stock_alerts"]
    assert any(a["item_key"] == "pollo_entero_crudo" for a in alerts)


def test_supplier_alert_when_stock_below_threshold(client, helpers):
    """Item with stock < min_threshold appears in low_stock_alerts."""
    helpers.set_stock("pechuga_vitrina", 2.0) # min_threshold = 4
    res = client.get("/api/cash/daily-summary")
    alerts = res.json()["low_stock_alerts"]
    alert = next((a for a in alerts if a["item_key"] == "pechuga_vitrina"), None)
    assert alert is not None
    assert alert["stock"] == 2.0


def test_no_supplier_alert_when_stock_above_threshold(client, helpers):
    """Item with stock > min_threshold does not trigger an alert."""
    helpers.set_stock("pollo_entero_crudo", 25.0) # min_threshold = 8
    res = client.get("/api/cash/daily-summary")
    alerts = res.json()["low_stock_alerts"]
    assert not any(a["item_key"] == "pollo_entero_crudo" for a in alerts)


def test_supplier_alert_critical_sodas(client, helpers):
    """Sodas in nevera drop below min_threshold and trigger low stock alerts."""
    helpers.set_stock("GAS-COL-400", 2.0) # min_threshold = 6
    res = client.get("/api/cash/daily-summary")
    alerts = res.json()["low_stock_alerts"]
    assert any(a["item_key"] == "GAS-COL-400" for a in alerts)


def test_supplier_alert_dry_goods_harina_aceite(client, helpers):
    """Harina and aceite dropping below threshold appear in supplier alerts."""
    helpers.set_stock("harina_apanar_kg", 5.0) # min_threshold = 10
    helpers.set_stock("aceite_fritura_lt", 10.0) # min_threshold = 15
    res = client.get("/api/cash/daily-summary")
    alerts = res.json()["low_stock_alerts"]
    keys = [a["item_key"] for a in alerts]
    assert "harina_apanar_kg" in keys
    assert "aceite_fritura_lt" in keys


def test_supplier_adjust_stock_clears_alert(client, helpers):
    """Using POST /api/cash/adjust-stock to replenish stock clears the alert."""
    helpers.set_stock("pollo_entero_crudo", 2.0)
    # Confirm alert is active
    alerts = client.get("/api/cash/daily-summary").json()["low_stock_alerts"]
    assert any(a["item_key"] == "pollo_entero_crudo" for a in alerts)

    # Replenish stock
    adj_res = client.post("/api/cash/adjust-stock", json={
        "item_key": "pollo_entero_crudo",
        "new_stock": 20.0,
        "reason": "Entrega de proveedor Avidesa"
    })
    assert adj_res.status_code == 200

    # Confirm alert is cleared
    alerts_after = client.get("/api/cash/daily-summary").json()["low_stock_alerts"]
    assert not any(a["item_key"] == "pollo_entero_crudo" for a in alerts_after)
