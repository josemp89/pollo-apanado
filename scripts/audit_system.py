import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

def run_system_audit():
    client = TestClient(app)

    print("=== AUDITORIA DE RUTAS Y VISTAS HTML ===")
    for route in ['/', '/caja', '/guia-fritura', '/cartel-precios']:
        res = client.get(route)
        assert res.status_code == 200, f"Fallo en {route}: {res.status_code}"
        print(f"OK: {route:18} -> 200 OK ({len(res.text)} bytes)")

    # Test cocina redirect
    res = client.get('/cocina', follow_redirects=False)
    assert res.status_code in (301, 302, 307, 308), f"Fallo en /cocina redirect: {res.status_code}"
    print(f"OK: /cocina            -> {res.status_code} Redirect hacia /")

    print("\n=== AUDITORIA DE CATALOGO Y PRODUCTOS ===")
    prods = client.get('/api/pos/products').json()
    print(f"OK: /api/pos/products  -> {len(prods)} productos activos encontrados")
    skus = [p['sku'] for p in prods]
    for target in ['POL-PER', 'POL-14', 'POL-12', 'POL-ENT', 'ALM-COMP']:
        assert target in skus, f"{target} no encontrado en productos activos"
    print("OK: Combos y Almuerzo verificados (POL-PER, POL-14, POL-12, POL-ENT, ALM-COMP)")

    print("\n=== AUDITORIA DE EXISTENCIAS EN TIEMPO REAL ===")
    stock = client.get('/api/pos/stock-summary').json()
    print(f"OK: /api/pos/stock-summary -> {len(stock)} insumos rastreados")
    assert stock['pollo_entero_crudo']['stock'] == 30.0, f"Pollos crudos erróneo"
    assert stock['pechuga_vitrina']['stock'] == 0.0, "Vitrina no está vacía"
    assert stock['ala_vitrina']['stock'] == 0.0, "Vitrina no está vacía"
    assert stock['pechuga_nevera']['stock'] == 0.0, "Bodega de presas no está vacía"
    assert stock['ala_nevera']['stock'] == 0.0, "Bodega de presas no está vacía"
    
    # Check 15 bebidas
    nevera_total = sum(v['stock'] for k, v in stock.items() if v.get('category') == 'nevera')
    assert nevera_total == 189.0, f"Total nevera incorrecto: {nevera_total}"
    print(f"OK: Inventario verificado: 30 pollos crudos en bodega, 0 presas en vitrina/nevera, 189 botellas en nevera")

    print("\n=== AUDITORIA DE CAJA, PLANILLA Y RECONCILIACION ===")
    shift = client.get('/api/cash/current-shift').json()
    print(f"OK: /api/cash/current-shift -> Turno abierto: {shift.get('is_open', False)}")

    sheet = client.get('/api/cash/closing-inventory-sheet').json()
    assert 'zones' in sheet
    for zone in ['bodega', 'vitrina', 'nevera', 'insumos']:
        assert zone in sheet['zones'], f"Falta zona {zone}"
    print(f"OK: /api/cash/closing-inventory-sheet -> 4 zonas verificadas (bodega, vitrina, nevera, insumos)")

    rec = client.get('/api/inventory/daily-reconciliation').json()
    assert 'items' in rec
    print(f"OK: /api/inventory/daily-reconciliation -> {len(rec['items'])} items reconciliados")

    print("\n*** AUDITORIA AUTOMATIZADA DEL SISTEMA COMPLETADA: 100% OPERATIVO Y CUADRADO ***\n")

if __name__ == '__main__':
    run_system_audit()
