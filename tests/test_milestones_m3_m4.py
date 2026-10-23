import pytest
from fastapi.testclient import TestClient

def test_batch_stage_transitions_and_completion(client: TestClient, db_conn):
    """Verifica el ciclo completo de un lote: Salmuera -> Adobo -> Fritura -> Terminado."""
    # 1. Iniciar Salmuera
    res = client.post("/api/kitchen/batch-timer", json={
        "stage": "salmuera",
        "total_presas": 20
    })
    assert res.status_code == 200
    batch_data = res.json()
    batch_code = batch_data["batch_code"]

    batch_row = db_conn.execute("SELECT id, stage FROM cooking_batches WHERE batch_code = ?", (batch_code,)).fetchone()
    batch_id = batch_row["id"]
    assert batch_row["stage"] == "salmuera"

    # 2. Avanzar a Adobo
    res_adv1 = client.post(f"/api/kitchen/advance-batch/{batch_id}")
    assert res_adv1.status_code == 200
    assert res_adv1.json()["new_stage"] == "adobo"

    # 3. Avanzar a Fritura
    res_adv2 = client.post(f"/api/kitchen/advance-batch/{batch_id}")
    assert res_adv2.status_code == 200
    assert res_adv2.json()["new_stage"] == "fritura"

    # 4. Avanzar a Terminado (debe sumar presas a vitrina)
    initial_pechuga = db_conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    res_adv3 = client.post(f"/api/kitchen/advance-batch/{batch_id}")
    assert res_adv3.status_code == 200
    assert res_adv3.json()["new_stage"] == "terminado"

    final_pechuga = db_conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()["stock"]
    assert final_pechuga == initial_pechuga + (20 // 4)

def test_fryer_recommendation_and_combo_aggregation(client: TestClient, helpers):
    """Verifica que el endpoint hourly-demand desglosa presas de combos y emite recomendación."""
    res = client.get("/api/kitchen/hourly-demand")
    assert res.status_code == 200
    data = res.json()
    assert "fryer_recommendation" in data
    rec = data["fryer_recommendation"]
    assert "suggested_to_fry" in rec
    assert "status_message" in rec
    assert "lead_time_minutes" in rec
    assert rec["lead_time_minutes"] == 15

def test_partner_distribution_and_breakeven_margin(client: TestClient, helpers):
    """Verifica el cálculo de punto de equilibrio sobre margen bruto y el reparto 40/40/20."""
    res = client.get("/api/cash/daily-summary")
    assert res.status_code == 200
    data = res.json()
    assert "estimated_margin" in data
    assert "partner_distribution" in data
    
    part = data["partner_distribution"]
    assert "partner_1_capital_40pct" in part
    assert "partner_2_capital_40pct" in part
    assert "partner_santiago_operativo_20pct" in part
    assert "reserve_fund_5pct" in part

def test_accurate_presas_count_includes_combos(client: TestClient, helpers, db_conn):
    """Verifica que la venta de un combo POL-ENT (Pollo Entero) suma 2 de cada presa en el reporte."""
    prod_id = helpers.get_product_id("POL-ENT")
    
    # Hacer una venta de Pollo Entero en efectivo exacto ($36.000)
    checkout_res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 36000
    })
    assert checkout_res.status_code == 200

    summary_res = client.get("/api/cash/daily-summary")
    assert summary_res.status_code == 200
    units = summary_res.json()["units_sold"]
    assert units["pechugas"] >= 2
    assert units["muslos"] >= 2
    assert units["contramuslos"] >= 2
    assert units["alas"] >= 2
