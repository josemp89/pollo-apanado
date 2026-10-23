import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, get_db_connection

def run_tests():
    print("Iniciando pruebas del sistema...")
    init_db()
    client = TestClient(app)

    # 1. Probar carga de productos
    res = client.get("/api/pos/products")
    assert res.status_code == 200, f"Error en products: {res.text}"
    products = res.json()
    print(f"✅ Productos cargados: {len(products)} productos en catálogo.")

    # 2. Verificar que existe Almuerzo Completo y Caldo
    almuerzo = next((p for p in products if p["sku"] == "ALM-COMP"), None)
    assert almuerzo is not None, "No se encontró Almuerzo Completo"
    assert almuerzo["price"] == 16000, "Precio incorrecto de almuerzo"
    assert almuerzo["requires_presa_selection"] == 1, "Debe requerir selección de presa"

    caldo = next((p for p in products if p["sku"] == "POR-CALD"), None)
    assert caldo is not None, "No se encontró Porción de Caldo"
    assert caldo["price"] == 6000, "Precio incorrecto de caldo"
    print("✅ Almuerzo ($16.000) y Caldo ($6.000) verificados con éxito.")

    # 3. Leer stock inicial
    stock_res = client.get("/api/pos/stock-summary").json()
    pechuga_init = stock_res["pechuga_vitrina"]["stock"]
    caldo_init = stock_res["caldo_raciones"]["stock"]
    colombiana_init = stock_res["GAS-COL-400"]["stock"]
    print(f"📊 Stock inicial - Pechuga: {pechuga_init}, Caldo: {caldo_init}, Colombiana: {colombiana_init}")

    # 4. Simular Venta en POS:
    # 1 Almuerzo Completo (con Pechuga) + 1 Caldo Solo + 1 Colombiana 400ml
    checkout_payload = {
        "items": [
            {"product_id": almuerzo["id"], "quantity": 1, "chosen_presa": "Pechuga"},
            {"product_id": caldo["id"], "quantity": 1},
            {"product_id": next(p for p in products if p["sku"] == "GAS-COL-400")["id"], "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 50000
    }

    checkout_res = client.post("/api/pos/checkout", json=checkout_payload)
    assert checkout_res.status_code == 200, f"Error en checkout: {checkout_res.text}"
    sale_data = checkout_res.json()
    print(f"✅ Venta registrada: {sale_data['sale_code']} por {sale_data['total_amount']} COP a las {sale_data['time_str']}")
    assert sale_data["total_amount"] == (16000 + 6000 + 3500), "Total de venta incorrecto"
    assert sale_data["change_returned"] == (50000 - 25500), "Cambio devuelto incorrecto"

    # 5. Verificar que el inventario se descontó exactamente
    stock_after = client.get("/api/pos/stock-summary").json()
    assert stock_after["pechuga_vitrina"]["stock"] == pechuga_init - 1, "Pechuga no se descontó"
    assert stock_after["caldo_raciones"]["stock"] == caldo_init - 2, "Caldo no se descontó correctamente (-2 raciones)"
    assert stock_after["GAS-COL-400"]["stock"] == colombiana_init - 1, "Gaseosa no se descontó"
    print("✅ Descuento de inventario verificado a la perfección:")
    print(f"   • Pechugas vitrina: {stock_after['pechuga_vitrina']['stock']}")
    print(f"   • Caldo disponible: {stock_after['caldo_raciones']['stock']}")
    print(f"   • Colombiana nevera: {stock_after['GAS-COL-400']['stock']}")

    # 6. Probar Cuadre de Caja
    cash_res = client.get("/api/cash/daily-summary").json()
    print(f"✅ Resumen de caja: Total hoy = {cash_res['cash_summary']['gran_total']} COP (Efectivo: {cash_res['cash_summary']['efectivo']} COP)")
    assert cash_res["cash_summary"]["gran_total"] >= 25500, "Total de caja no coincide"

    # 7. Probar Entrada de Proveedores y Despiece Matutino
    supplier_res = client.post("/api/inventory/supplier-entry", json={
        "supplier_name": "Avícola Bucanero",
        "invoice_number": f"REM-{int(datetime.now().timestamp())}",
        "item_name": "pollo_entero_crudo",
        "location": "bodega",
        "quantity": 10,
        "unit_cost": 15000
    })
    assert supplier_res.status_code == 200, f"Error en entrada proveedor: {supplier_res.text}"
    print("✅ Entrada de proveedor registrada: +10 pollos crudos en bodega.")
    despiece_res = client.post("/api/kitchen/despiece", json={"whole_chickens": 5, "operator": "Santiago"})
    assert despiece_res.status_code == 200, "Error en despiece"
    despiece_data = despiece_res.json()
    print(f"✅ Despiece de 5 pollos completado: +{despiece_data['yields']['total_presas']} presas generadas.")

    print("\n🎉 ¡TODAS LAS PRUEBAS PASARON AL 100%! El sistema está completamente funcional.")

if __name__ == "__main__":
    run_tests()
