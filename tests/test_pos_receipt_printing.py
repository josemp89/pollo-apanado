import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_checkout_returns_items_and_receipt_endpoint():
    """
    Verifica que al procesar una venta:
    1. El checkout retorne la lista de ítems detallados para impresión del ticket.
    2. El endpoint /api/pos/sale/{sale_id}/receipt devuelva la información completa de la factura y del negocio.
    """
    # 1. Realizar una venta de prueba
    res = client.post("/api/pos/checkout", json={
        "payment_method": "efectivo",
        "cash_received": 50000.0,
        "items": [
            {
                "product_id": 1,
                "quantity": 1,
                "chosen_presa": "pechuga"
            }
        ]
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["chosen_presa"] == "pechuga"
    sale_id = data["sale_id"]

    # 2. Consultar comprobante térmico por endpoint
    res_rec = client.get(f"/api/pos/sale/{sale_id}/receipt")
    assert res_rec.status_code == 200, res_rec.text
    receipt = res_rec.json()
    assert receipt["id"] == sale_id
    assert receipt["sale_code"] == data["sale_code"]
    assert receipt["total_amount"] == data["total_amount"]
    assert len(receipt["items"]) == 1
    assert receipt["items"][0]["chosen_presa"] == "pechuga"
    assert "store" in receipt
    assert "ASADERO" in receipt["store"]["name"]
