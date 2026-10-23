"""
Tier 4: Real-World Application Scenario Test Suite
Simulates an entire high-volume lunch rush day:
- Morning Despiece of 15 whole chickens (yields 120 presas: 30P, 30M, 30C, 30A, 30 caldo raciones).
- 55 realistic customer transactions across all product lines (Combos, Almuerzos, Single presas, Drinks, Sides).
- Varied payment methods (Cash, Nequi/Daviplata, Datáfono).
- 3 customer order cancellations / refunds.
- Verification of the Closed Inventory Conservation Equation:
  Initial Physical Stock + Despiece Entradas - Net Completed Sales Consumption = Final Physical Stock
  Asserted item-by-item with EXACT 0 discrepancy!
- Daily Cash Closing Reconciliation: Gross total, payment breakdown, margin, and comparison vs daily breakeven ($258,462 COP).
"""

import pytest

def test_full_lunch_rush_scenario(client, helpers, db_conn):
    # --------------------------------------------------------------------------
    # 1. Morning Setup & Initial Stock Initialization
    # --------------------------------------------------------------------------
    # Initialize start-of-day stock
    helpers.set_stock("pechuga_vitrina", 20.0)
    helpers.set_stock("muslo_vitrina", 20.0)
    helpers.set_stock("contramuslo_vitrina", 20.0)
    helpers.set_stock("ala_vitrina", 20.0)
    helpers.set_stock("caldo_raciones", 30.0)
    helpers.set_stock("pollo_entero_crudo", 25.0)
    helpers.set_stock("arroz_raciones", 100.0)
    helpers.set_stock("frijoles_raciones", 100.0)
    helpers.set_stock("papas_raciones", 100.0)
    helpers.set_stock("arepas_unidades", 100.0)
    helpers.set_stock("GAS-COL-400", 50.0)
    helpers.set_stock("GAS-COC-400", 50.0)
    helpers.set_stock("GAS-MAN-400", 50.0)
    helpers.set_stock("GAS-ZER-400", 50.0)
    helpers.set_stock("GAS-QUA-400", 50.0)

    # Snapshot initial physical stock for all tracked items
    tracked_keys = [
        "pechuga_vitrina", "muslo_vitrina", "contramuslo_vitrina", "ala_vitrina",
        "caldo_raciones", "arroz_raciones", "frijoles_raciones", "papas_raciones",
        "arepas_unidades", "pollo_entero_crudo", "GAS-COL-400", "GAS-COC-400",
        "GAS-MAN-400", "GAS-ZER-400", "GAS-QUA-400"
    ]
    initial_stock = {k: helpers.get_stock(k) for k in tracked_keys}

    # --------------------------------------------------------------------------
    # 2. Morning Kitchen Despiece: 15 Whole Chickens
    # --------------------------------------------------------------------------
    despiece_res = client.post("/api/kitchen/despiece", json={
        "whole_chickens": 15,
        "operator": "Santiago",
        "notes": "Despiece matutino para turno pico"
    })
    assert despiece_res.status_code == 200
    yields = despiece_res.json()["yields"]
    assert yields["pechugas"] == 30
    assert yields["muslos"] == 30
    assert yields["contramuslos"] == 30
    assert yields["alas"] == 30
    assert yields["total_presas"] == 120
    assert yields["caldo_raciones"] == 30

    despiece_added = {k: 0.0 for k in tracked_keys}
    despiece_added["pollo_entero_crudo"] = -15.0
    despiece_added["pechuga_vitrina"] = 30.0
    despiece_added["muslo_vitrina"] = 30.0
    despiece_added["contramuslo_vitrina"] = 30.0
    despiece_added["ala_vitrina"] = 30.0
    despiece_added["caldo_raciones"] = 30.0

    # Start kitchen timers
    client.post("/api/kitchen/batch-timer", json={"stage": "salmuera", "total_presas": 60})
    client.post("/api/kitchen/batch-timer", json={"stage": "adobo", "total_presas": 60})

    # --------------------------------------------------------------------------
    # 3. Execution of 55 POS Transactions
    # --------------------------------------------------------------------------
    # Product ID mappings
    p_alm = helpers.get_product_id("ALM-COMP")
    p_14 = helpers.get_product_id("POL-14")
    p_12 = helpers.get_product_id("POL-12")
    p_ent = helpers.get_product_id("POL-ENT")
    p_pec = helpers.get_product_id("POL-PEC")
    p_mus = helpers.get_product_id("POL-MUS")
    p_con = helpers.get_product_id("POL-CON")
    p_ala = helpers.get_product_id("POL-ALA")
    p_cald = helpers.get_product_id("POR-CALD")
    p_papas = helpers.get_product_id("POR-PAPAS")
    p_arep = helpers.get_product_id("POR-AREP")
    p_col = helpers.get_product_id("GAS-COL-400")
    p_coc = helpers.get_product_id("GAS-COC-400")
    p_man = helpers.get_product_id("GAS-MAN-400")
    p_qua = helpers.get_product_id("GAS-QUA-400")

    # Build 55 structured orders
    orders_spec = []
    
    # 1-12: Almuerzos ejecutivos with varied presas
    for i in range(12):
        presa = ["Pechuga", "Muslo", "Contramuslo", "Ala"][i % 4]
        drink = [p_col, p_coc, p_man, p_qua][i % 4]
        method = ["efectivo", "nequi_daviplata", "datafono"][i % 3]
        cash = 25000 if method == "efectivo" else 0
        orders_spec.append({
            "items": [
                {"product_id": p_alm, "quantity": 1, "chosen_presa": presa},
                {"product_id": drink, "quantity": 1}
            ],
            "payment_method": method,
            "cash_received": cash
        })

    # 13-24: 1/4 Pollo Combos
    for i in range(12):
        method = ["efectivo", "nequi_daviplata", "datafono"][i % 3]
        cash = 20000 if method == "efectivo" else 0
        orders_spec.append({
            "items": [
                {"product_id": p_14, "quantity": 1},
                {"product_id": p_col, "quantity": 1}
            ],
            "payment_method": method,
            "cash_received": cash
        })

    # 25-34: 1/2 Pollo Combos
    for i in range(10):
        method = ["efectivo", "nequi_daviplata", "datafono"][i % 3]
        cash = 30000 if method == "efectivo" else 0
        orders_spec.append({
            "items": [
                {"product_id": p_12, "quantity": 1},
                {"product_id": p_arep, "quantity": 2}
            ],
            "payment_method": method,
            "cash_received": cash
        })

    # 35-42: Pollo Entero Combos
    for i in range(8):
        method = ["efectivo", "nequi_daviplata", "datafono"][i % 3]
        cash = 50000 if method == "efectivo" else 0
        orders_spec.append({
            "items": [
                {"product_id": p_ent, "quantity": 1},
                {"product_id": p_coc, "quantity": 2}
            ],
            "payment_method": method,
            "cash_received": cash
        })

    # 43-50: Individual presas and extra portions
    for i in range(8):
        presa_prod = [p_pec, p_mus, p_con, p_ala][i % 4]
        orders_spec.append({
            "items": [
                {"product_id": presa_prod, "quantity": 1},
                {"product_id": p_cald, "quantity": 1}
            ],
            "payment_method": "efectivo",
            "cash_received": 20000
        })

    # 51-55: Mixed large orders
    for i in range(5):
        orders_spec.append({
            "items": [
                {"product_id": p_14, "quantity": 1},
                {"product_id": p_alm, "quantity": 1, "chosen_presa": "Pechuga"},
                {"product_id": p_papas, "quantity": 1},
                {"product_id": p_arep, "quantity": 1}
            ],
            "payment_method": "datafono"
        })

    assert len(orders_spec) == 55

    # Execute all 55 checkouts
    completed_sales = []
    for spec in orders_spec:
        res = client.post("/api/pos/checkout", json=spec)
        assert res.status_code == 200, f"Checkout failed: {res.text}"
        completed_sales.append({
            "sale_id": res.json()["sale_id"],
            "sale_code": res.json()["sale_code"],
            "total_amount": res.json()["total_amount"],
            "payment_method": spec["payment_method"],
            "items": spec["items"]
        })

    assert len(completed_sales) == 55

    # --------------------------------------------------------------------------
    # 4. Cancellations / Customer Reversals (3 Sales Cancelled)
    # --------------------------------------------------------------------------
    # Pick sale 5 (Almuerzo), sale 20 (1/4 Pollo), and sale 35 (Pollo Entero)
    cancelled_indices = [4, 19, 34]
    cancelled_sale_ids = [completed_sales[idx]["sale_id"] for idx in cancelled_indices]

    for sid in cancelled_sale_ids:
        cancel_res = client.post(f"/api/pos/cancel-sale/{sid}")
        assert cancel_res.status_code == 200

    # --------------------------------------------------------------------------
    # 5. Inventory Math Verification: Closed Conservation Equation
    # --------------------------------------------------------------------------
    # Calculate exact net consumption across active (non-cancelled) sales
    net_consumed = {k: 0.0 for k in tracked_keys}

    active_sales = [s for idx, s in enumerate(completed_sales) if idx not in cancelled_indices]
    assert len(active_sales) == 52

    for s in active_sales:
        for it in s["items"]:
            pid = it["product_id"]
            qty = it["quantity"]
            chosen = it.get("chosen_presa")

            if pid == p_pec:
                net_consumed["pechuga_vitrina"] += qty
            elif pid == p_mus:
                net_consumed["muslo_vitrina"] += qty
            elif pid == p_con:
                net_consumed["contramuslo_vitrina"] += qty
            elif pid == p_ala:
                net_consumed["ala_vitrina"] += qty
            elif pid == p_14:
                net_consumed["muslo_vitrina"] += qty
                net_consumed["contramuslo_vitrina"] += qty
                net_consumed["papas_raciones"] += qty
            elif pid == p_12:
                net_consumed["pechuga_vitrina"] += qty
                net_consumed["ala_vitrina"] += qty
                net_consumed["muslo_vitrina"] += qty
                net_consumed["contramuslo_vitrina"] += qty
                net_consumed["papas_raciones"] += qty
            elif pid == p_ent:
                net_consumed["pechuga_vitrina"] += 2.0 * qty
                net_consumed["ala_vitrina"] += 2.0 * qty
                net_consumed["muslo_vitrina"] += 2.0 * qty
                net_consumed["contramuslo_vitrina"] += 2.0 * qty
                net_consumed["papas_raciones"] += 2.0 * qty
            elif pid == p_alm:
                presa_key = f"{chosen.lower()}_vitrina"
                net_consumed[presa_key] += qty
                net_consumed["caldo_raciones"] += qty
                net_consumed["arroz_raciones"] += qty
                net_consumed["frijoles_raciones"] += qty
            elif pid == p_cald:
                net_consumed["caldo_raciones"] += qty
            elif pid == p_papas:
                net_consumed["papas_raciones"] += qty
            elif pid == p_arep:
                net_consumed["arepas_unidades"] += qty
            elif pid == p_col:
                net_consumed["GAS-COL-400"] += qty
            elif pid == p_coc:
                net_consumed["GAS-COC-400"] += qty
            elif pid == p_man:
                net_consumed["GAS-MAN-400"] += qty
            elif pid == p_qua:
                net_consumed["GAS-QUA-400"] += qty

    # VERIFY THE CLOSED EQUATION FOR EVERY ITEM:
    # Final Stock == Initial Stock + Despiece Additions - Net Completed Sales Consumption
    drift_errors = []
    for k in tracked_keys:
        expected_final = initial_stock[k] + despiece_added[k] - net_consumed[k]
        actual_final = helpers.get_stock(k)
        if actual_final != expected_final:
            drift_errors.append(f"Drift in {k}: Expected {expected_final}, Actual {actual_final}")

    assert len(drift_errors) == 0, f"Inventory drift detected: {drift_errors}"

    # --------------------------------------------------------------------------
    # 6. Financial Reconcilation & Break-Even Audit
    # --------------------------------------------------------------------------
    cash_summary_res = client.get("/api/cash/daily-summary")
    assert cash_summary_res.status_code == 200
    summary_data = cash_summary_res.json()
    cash_totals = summary_data["cash_summary"]

    expected_efectivo = sum(s["total_amount"] for s in active_sales if s["payment_method"] == "efectivo")
    expected_nequi = sum(s["total_amount"] for s in active_sales if s["payment_method"] == "nequi_daviplata")
    expected_datafono = sum(s["total_amount"] for s in active_sales if s["payment_method"] == "datafono")
    expected_gran_total = expected_efectivo + expected_nequi + expected_datafono

    assert cash_totals["efectivo"] == expected_efectivo
    assert cash_totals["nequi_daviplata"] == expected_nequi
    assert cash_totals["datafono"] == expected_datafono
    assert cash_totals["gran_total"] == expected_gran_total
    assert cash_totals["total_tickets"] == len(active_sales) # 52 tickets

    # Break-even check ($258,462 COP)
    assert summary_data["daily_breakeven_target"] == 258462
    assert expected_gran_total > 258462
    assert summary_data["is_profitable_today"] is True
    assert summary_data["breakeven_percentage"] > 100.0
