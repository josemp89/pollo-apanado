import pytest
import sqlite3
import json
import os
from fastapi.testclient import TestClient
from app.main import app
import app.database as database

def test_r1_open_shift_records_base_inicial(client, db_conn):
    """R1: La apertura de caja registra la base inicial en base de datos."""
    res = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 100000,
        "notes": "Apertura turno matutino"
    })
    assert res.status_code == 200, f"Error opening shift: {res.text}"
    data = res.json()
    assert data["success"] is True
    assert data["shift"]["base_inicial"] == 100000
    assert data["shift"]["status"] == "abierto"
    assert data["shift"]["cashier_name"] == "Santiago"

    # Verificar en base de datos
    shift_db = db_conn.execute("SELECT * FROM cash_shifts WHERE id = ?", (data["shift"]["id"],)).fetchone()
    assert shift_db is not None
    assert shift_db["base_inicial"] == 100000
    assert shift_db["status"] == "abierto"

    # Verificar que no permite abrir un segundo turno simultáneo
    res_dup = client.post("/api/cash/open-shift", json={
        "cashier_name": "Cajero 2",
        "base_inicial": 50000
    })
    assert res_dup.status_code == 400
    assert "Ya existe un turno de caja abierto" in res_dup.json()["detail"]


def test_r1_expected_cash_formula_and_reconciliation(client, helpers):
    """
    R1: Efectivo Final Esperado en Cajón = Base Inicial + Ventas en Efectivo - Gastos Menores Autorizados.
    Verifica también separación estricta de pagos digitales (Nequi/Daviplata y Datáfono).
    """
    # 1. Abrir turno con base inicial de $100.000 COP
    res_open = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 100000
    })
    assert res_open.status_code == 200
    shift_id = res_open.json()["shift"]["id"]

    # 2. Venta 1 en Efectivo: 1/4 Pollo ($13.000 COP)
    prod_cuarto_id = helpers.get_product_id("POL-14")
    res_v1 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_cuarto_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_v1.status_code == 200
    assert res_v1.json()["total_amount"] == 13000

    # 3. Venta 2 en Efectivo: Pollo Entero ($36.000 COP)
    prod_entero_id = helpers.get_product_id("POL-ENT")
    res_v2 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_entero_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 50000
    })
    assert res_v2.status_code == 200
    assert res_v2.json()["total_amount"] == 36000

    # Total ventas efectivo = 13.000 + 36.000 = $49.000 COP

    # 4. Venta en Nequi/Daviplata (Digital): 1/2 Pollo ($20.000 COP) - No toca cajón
    prod_medio_id = helpers.get_product_id("POL-12")
    res_v3 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_medio_id, "quantity": 1}],
        "payment_method": "nequi_daviplata",
        "cash_received": 0
    })
    assert res_v3.status_code == 200

    # 5. Venta en Datáfono (Tarjeta): Almuerzo Completo ($16.000 COP) - No toca cajón
    prod_alm_id = helpers.get_product_id("ALM-COMP")
    res_v4 = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_alm_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "datafono",
        "cash_received": 0
    })
    assert res_v4.status_code == 200

    # 6. Registrar gasto menor de caja menor: $15.000 COP para compra de hielo
    res_exp = client.post("/api/cash/expense", json={
        "shift_id": shift_id,
        "amount": 15000,
        "category": "insumos",
        "concept": "Compra 2 bolsas de hielo y limones",
        "authorized_by": "Santiago"
    })
    assert res_exp.status_code == 200

    # 7. Consultar current-shift y daily-summary
    summary = client.get("/api/cash/daily-summary").json()
    reconcil = summary["cash_reconciliation"]

    # Matemática R1:
    # Base Inicial ($100.000) + Ventas Efectivo ($49.000) - Gastos ($15.000) = $134.000 COP
    assert reconcil["base_inicial"] == 100000
    assert reconcil["cash_sales"] == 49000
    assert reconcil["total_expenses"] == 15000
    assert reconcil["expected_cash"] == 134000
    assert reconcil["digital_transfers"] == 20000
    assert reconcil["card_vouchers"] == 16000
    assert reconcil["gran_total_sales"] == 85000  # 49k + 20k + 16k

    # 8. Cerrar turno con conteo físico exacto de $134.000 COP
    res_close = client.post("/api/cash/close-shift", json={
        "shift_id": shift_id,
        "actual_cash": 134000,
        "notes": "Cuadre de caja exacto verificado"
    })
    assert res_close.status_code == 200
    close_data = res_close.json()
    assert close_data["shift"]["status"] == "cerrado"
    assert close_data["reconciliation"]["expected_cash"] == 134000
    assert close_data["reconciliation"]["actual_cash"] == 134000
    assert close_data["reconciliation"]["difference"] == 0


def test_r1_close_shift_difference_faltante_y_sobrante(client):
    """R1: Validación de cálculo exacto de diferencia en cierre con faltante y sobrante."""
    # Turno 1: Faltante de $5.000 COP
    res_open = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 50000
    })
    shift1_id = res_open.json()["shift"]["id"]

    res_close = client.post("/api/cash/close-shift", json={
        "shift_id": shift1_id,
        "actual_cash": 45000  # Faltan 5.000
    })
    assert res_close.status_code == 200
    assert res_close.json()["reconciliation"]["difference"] == -5000

    # Turno 2: Sobrante de $3.000 COP
    res_open2 = client.post("/api/cash/open-shift", json={
        "cashier_name": "Santiago",
        "base_inicial": 50000
    })
    shift2_id = res_open2.json()["shift"]["id"]

    res_close2 = client.post("/api/cash/close-shift", json={
        "shift_id": shift2_id,
        "actual_cash": 53000  # Sobran 3.000
    })
    assert res_close2.status_code == 200
    assert res_close2.json()["reconciliation"]["difference"] == 3000


def test_r2_exhaustive_sales_breakdown_100pct_reconciliation(client, helpers):
    """
    R2: Desglose exhaustivo de presas solas, combos, almuerzos (por presa), porciones y gaseosas.
    Verifica que la suma total coincida al 100% en COP con cero derivas matemáticas.
    """
    # Realizar ventas en todas las categorías:
    # 1. Presas solas: Pechuga Sola ($9.000) + Ala Sola ($9.000) = $18.000
    p_pec = helpers.get_product_id("POL-PEC")
    p_ala = helpers.get_product_id("POL-ALA")
    client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_pec, "quantity": 1},
            {"product_id": p_ala, "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 20000
    })

    # 2. Combos: 1/4 Pollo ($13.000) + Pollo Entero ($36.000) = $49.000
    p_14 = helpers.get_product_id("POL-14")
    p_ent = helpers.get_product_id("POL-ENT")
    client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_14, "quantity": 1},
            {"product_id": p_ent, "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    })

    # 3. Almuerzo Completo con presa Muslo ($16.000) y con Contramuslo ($16.000) = $32.000
    p_alm = helpers.get_product_id("ALM-COMP")
    client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_alm, "quantity": 1, "chosen_presa": "Muslo"},
            {"product_id": p_alm, "quantity": 1, "chosen_presa": "Contramuslo"}
        ],
        "payment_method": "nequi_daviplata",
        "cash_received": 0
    })

    # 4. Porciones sueltas: Caldo ($6.000) + Papas ($5.000) + Arepas ($2.000) = $13.000
    p_cald = helpers.get_product_id("POR-CALD")
    p_papas = helpers.get_product_id("POR-PAPAS")
    p_arep = helpers.get_product_id("POR-AREP")
    client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_cald, "quantity": 1},
            {"product_id": p_papas, "quantity": 1},
            {"product_id": p_arep, "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 15000
    })

    # 5. Gaseosas Postobón: Colombiana 400ml ($3.500)
    p_post = helpers.get_product_id("GAS-COL-400")
    # Gaseosas Coca-Cola: Coca-Cola 400ml ($4.000)
    p_coca = helpers.get_product_id("GAS-COC-400")
    client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": p_post, "quantity": 1},
            {"product_id": p_coca, "quantity": 1}
        ],
        "payment_method": "datafono",
        "cash_received": 0
    })

    # Total esperado = 18.000 + 49.000 + 32.000 + 13.000 + 7.500 = $119.500 COP

    summary = client.get("/api/cash/daily-summary").json()
    bd = summary["product_breakdown"]

    assert bd["presas_solas"]["subtotal_cop"] == 18000
    assert bd["presas_solas"]["total_qty"] == 2
    assert bd["combos"]["subtotal_cop"] == 49000
    assert bd["combos"]["total_qty"] == 2
    assert bd["almuerzos"]["subtotal_cop"] == 32000
    assert bd["almuerzos"]["total_qty"] == 2
    assert bd["almuerzos"]["by_presa"]["Muslo"] == 1
    assert bd["almuerzos"]["by_presa"]["Contramuslo"] == 1
    assert bd["porciones"]["subtotal_cop"] == 13000
    assert bd["porciones"]["total_qty"] == 3
    assert bd["gaseosas_postobon"]["subtotal_cop"] == 3500
    assert bd["gaseosas_postobon"]["total_qty"] == 1
    assert bd["gaseosas_cocacola"]["subtotal_cop"] == 4000
    assert bd["gaseosas_cocacola"]["total_qty"] == 1

    # Verificación de suma 100% y deriva cero
    assert bd["total_revenue_sum"] == 119500
    assert summary["cash_summary"]["gran_total"] == 119500
    assert bd["zero_drift_verified"] is True


def test_r3_antifraud_pin_rejection_without_pin(client, helpers):
    """R3: Cualquier petición de anulación sin PIN es rechazada con HTTP 403 Forbidden."""
    caldo_id = helpers.get_product_id("POR-CALD")
    sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": caldo_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    }).json()
    sale_id = sale["sale_id"]

    # Intento 1: Sin cuerpo y sin header
    res1 = client.post(f"/api/pos/cancel-sale/{sale_id}")
    assert res1.status_code == 403, f"Expected 403, got {res1.status_code}: {res1.text}"
    assert "PIN de Administrador" in res1.json()["detail"]

    # Intento 2: Cuerpo vacío {}
    res2 = client.post(f"/api/pos/cancel-sale/{sale_id}", json={})
    assert res2.status_code == 403

    # Intento 3: Alias /cancel/{id} sin PIN
    res3 = client.post(f"/api/pos/cancel/{sale_id}")
    assert res3.status_code == 403


def test_r3_antifraud_pin_rejection_with_invalid_pin(client, helpers):
    """R3: Cualquier petición de anulación con PIN incorrecto o espacios es rechazada con HTTP 403."""
    caldo_id = helpers.get_product_id("POR-CALD")
    sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": caldo_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    }).json()
    sale_id = sale["sale_id"]

    # Intento PIN incorrecto
    res_bad = client.post(f"/api/pos/cancel-sale/{sale_id}", json={"pin": "9999"})
    assert res_bad.status_code == 403
    assert "PIN de Administrador/Socio inválido" in res_bad.json()["detail"]

    # Intento PIN vacío / espacios
    res_blank = client.post(f"/api/pos/cancel-sale/{sale_id}", json={"pin": "    "})
    assert res_blank.status_code == 403


def test_r3_antifraud_cancellation_success_and_forensic_audit(client, helpers, db_conn):
    """
    R3: Con PIN válido ('4321'), la anulación es aprobada (HTTP 200),
    el inventario reingresa, y se crea un registro forense inmutable en sale_cancellation_audit.
    """
    # 1. Registrar venta de 1/2 Pollo + Papas ($20.000 COP)
    p_medio = helpers.get_product_id("POL-12")
    stock_p_before = helpers.get_stock("pechuga_vitrina")
    stock_m_before = helpers.get_stock("muslo_vitrina")

    sale_res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_medio, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert sale_res.status_code == 200
    sale_id = sale_res.json()["sale_id"]
    sale_code = sale_res.json()["sale_code"]

    # Stock disminuyó
    assert helpers.get_stock("pechuga_vitrina") == stock_p_before - 1
    assert helpers.get_stock("muslo_vitrina") == stock_m_before - 1

    # 2. Anular venta con PIN de administrador
    cancel_res = client.post(f"/api/pos/cancel-sale/{sale_id}", json={
        "pin": "4321",
        "reason": "Error en digitación de mesa",
        "authorized_by": "Socio 1"
    })
    assert cancel_res.status_code == 200, f"Cancel with valid PIN failed: {cancel_res.text}"
    cancel_data = cancel_res.json()
    assert cancel_data["success"] is True

    # 3. Stock se restauró simétricamente
    assert helpers.get_stock("pechuga_vitrina") == stock_p_before
    assert helpers.get_stock("muslo_vitrina") == stock_m_before

    # 4. Bitácora forense registrada en sale_cancellation_audit
    audit_row = db_conn.execute("SELECT * FROM sale_cancellation_audit WHERE sale_id = ?", (sale_id,)).fetchone()
    assert audit_row is not None
    assert audit_row["sale_code"] == sale_code
    assert audit_row["total_amount"] == 20000
    assert audit_row["payment_method"] == "efectivo"
    assert audit_row["reason"] == "Error en digitación de mesa"
    assert audit_row["authorized_by"] == "Socio 1"
    assert audit_row["time_str"] is not None  # Segundo exacto registrado
    assert "4***" in audit_row["pin_used_masked"]

    presas_dict = json.loads(audit_row["restored_presas_summary"])
    assert presas_dict["pechugas"] == 1
    assert presas_dict["muslos"] == 1
    assert presas_dict["contramuslos"] == 1
    assert presas_dict["alas"] == 1
    assert presas_dict["total_presas"] == 4

    # 5. La anulación se expone en daily-summary bajo cancellations_audit
    summary = client.get("/api/cash/daily-summary").json()
    canc_audit = summary["cancellations_audit"]
    assert canc_audit["total_cancelled_count"] >= 1
    assert canc_audit["total_refunded_cop"] >= 20000
    assert canc_audit["refunded_by_method"]["efectivo"] >= 20000
    assert canc_audit["returned_presas_summary"]["pechugas"] >= 1


def test_r3_audit_log_immutability_triggers(client, helpers, db_conn):
    """R3: Inmutabilidad estricta: los triggers impiden UPDATE o DELETE sobre sale_cancellation_audit."""
    # Crear una venta y anularla con PIN
    caldo_id = helpers.get_product_id("POR-CALD")
    sale = client.post("/api/pos/checkout", json={
        "items": [{"product_id": caldo_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 10000
    }).json()

    client.post(f"/api/pos/cancel-sale/{sale['sale_id']}", json={"pin": "4321"}).json()

    # Intento malicioso de modificar la bitácora
    with pytest.raises(sqlite3.DatabaseError) as exc_update:
        db_conn.execute("UPDATE sale_cancellation_audit SET total_amount = 0 WHERE sale_id = ?", (sale["sale_id"],))
    assert "Seguridad Forense" in str(exc_update.value)

    # Intento malicioso de borrar registros de la bitácora
    with pytest.raises(sqlite3.DatabaseError) as exc_delete:
        db_conn.execute("DELETE FROM sale_cancellation_audit WHERE sale_id = ?", (sale["sale_id"],))
    assert "Seguridad Forense" in str(exc_delete.value)


def test_r4_vitrina_audit_discrepancy_and_fraud_correlation(client, helpers):
    """
    R4: Arqueo Físico de Vitrina:
    1. Calcula Discrepancia = Conteo Físico Real - Stock Teórico.
    2. Detona Alerta Roja de Sustracción No Autorizada cuando hay ventas anuladas
       cuyas presas devueltas no aparecen físicamente en vitrina.
    """
    # Establecer stock teórico conocido: 10 de cada una
    helpers.set_stock("pechuga_vitrina", 10)
    helpers.set_stock("muslo_vitrina", 10)
    helpers.set_stock("contramuslo_vitrina", 10)
    helpers.set_stock("ala_vitrina", 10)

    # Caso 1: Arqueo sin discrepancias
    res_audit_ok = client.post("/api/cash/vitrina-audit", json={
        "auditor": "Santiago",
        "pechugas_fisico": 10,
        "muslos_fisico": 10,
        "contramuslos_fisico": 10,
        "alas_fisico": 10,
        "adjust_inventory": False
    })
    assert res_audit_ok.status_code == 200
    data_ok = res_audit_ok.json()
    assert data_ok["has_discrepancy"] is False
    assert data_ok["has_theft_alert"] is False
    assert data_ok["audit"]["total_diff"] == 0

    # Caso 2: Simulación del vector de fraude
    # a) Cajero vende Pollo Entero ($36.000 COP) -> descuenta 2P, 2M, 2C, 2A
    p_entero = helpers.get_product_id("POL-ENT")
    sale_fraud = client.post("/api/pos/checkout", json={
        "items": [{"product_id": p_entero, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 36000
    }).json()

    # b) Cajero anula la venta con PIN fingiendo error -> reingresa 2P, 2M, 2C, 2A al stock teórico
    client.post(f"/api/pos/cancel-sale/{sale_fraud['sale_id']}", json={
        "pin": "4321",
        "reason": "Pedido equivocado"
    })

    # El stock teórico ahora es 10 de cada una
    vitrina_status = client.get("/api/cash/vitrina-status").json()
    assert vitrina_status["theoretical"]["pechuga"] == 10.0
    assert vitrina_status["today_cancelled_presas"]["pechuga"] >= 2.0

    # c) En la realidad física, el pollo se lo llevaron: en vitrina solo hay 8 de cada una
    res_audit_theft = client.post("/api/cash/vitrina-audit", json={
        "auditor": "Santiago",
        "pechugas_fisico": 8,
        "muslos_fisico": 8,
        "contramuslos_fisico": 8,
        "alas_fisico": 8,
        "adjust_inventory": True
    })
    assert res_audit_theft.status_code == 200
    data_theft = res_audit_theft.json()

    # Se detecta discrepancia: faltan 8 presas (diff = -2 en cada una)
    assert data_theft["has_discrepancy"] is True
    assert data_theft["audit"]["pechugas_diff"] == -2.0
    assert data_theft["audit"]["total_diff"] == -8.0

    # ¡Alerta roja de sustracción detonada!
    assert data_theft["has_theft_alert"] is True
    assert "ALERTA ROJA DE SUSTRACCIÓN NO AUTORIZADA" in data_theft["theft_alert_detail"]

    # El stock en inventory fue sincronizado con el conteo físico (adjust_inventory=True)
    assert helpers.get_stock("pechuga_vitrina") == 8
    assert helpers.get_stock("muslo_vitrina") == 8
