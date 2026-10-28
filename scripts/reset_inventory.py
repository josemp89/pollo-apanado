import sqlite3
from datetime import datetime

def reset_inventory():
    conn = sqlite3.connect('data/asadero.db')
    cursor = conn.cursor()

    # 1. Limpiar ventas de prueba y transacciones
    cursor.execute('DELETE FROM sales')
    cursor.execute('DELETE FROM sale_items')
    
    # Desactivar temporalmente el trigger de inmutabilidad para limpiar registros de prueba
    cursor.execute('DROP TRIGGER IF EXISTS trg_prevent_cancellation_audit_delete')
    cursor.execute('DELETE FROM sale_cancellation_audit')
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_prevent_cancellation_audit_delete
        BEFORE DELETE ON sale_cancellation_audit
        BEGIN
            SELECT RAISE(ABORT, 'Violación de Seguridad Forense: La bitácora de auditoría de anulaciones es estrictamente inmutable.');
        END;
    """)
    cursor.execute('DELETE FROM butchering_logs')
    cursor.execute('DELETE FROM cooking_batches')
    cursor.execute('DELETE FROM cash_shifts')
    cursor.execute('DELETE FROM cash_expenses')
    cursor.execute('DELETE FROM vitrina_audits')
    cursor.execute('DELETE FROM merchandise_entries')
    cursor.execute('DELETE FROM daily_closing_receipts')
    cursor.execute('DELETE FROM order_counters')

    # Reiniciar secuencias autoincrementales
    cursor.execute("""
        DELETE FROM sqlite_sequence 
        WHERE name IN (
            'sales', 'sale_items', 'sale_cancellation_audit', 
            'butchering_logs', 'cooking_batches', 'cash_shifts', 'cash_expenses'
        )
    """)

    now_iso = datetime.now().isoformat()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 2. Reiniciar inventario en Bodega, Vitrina, Cocina y Nevera
    # Eliminar insumos de producción no rotativos (harina y aceite) del inventario activo
    cursor.execute('DELETE FROM inventory WHERE item_key IN ("harina_apanar_kg", "aceite_fritura_lt")')
    cursor.execute('DELETE FROM daily_initial_inventory WHERE item_name IN ("harina_apanar_kg", "aceite_fritura_lt", "Harina Apanador", "Aceite para Freidoras")')

    # Bodega (Estrictamente pollo: 30 pollos enteros crudos y 0 en canecas crudas)
    cursor.execute('UPDATE inventory SET stock = 30.0, updated_at = ? WHERE item_key = "pollo_entero_crudo"', (now_iso,))
    cursor.execute('UPDATE inventory SET stock = 0.0, updated_at = ? WHERE item_key IN ("pechuga_nevera", "contramuslo_nevera", "muslo_nevera", "ala_nevera")', (now_iso,))

    # Vitrina
    cursor.execute('UPDATE inventory SET stock = 0.0, updated_at = ? WHERE item_key IN ("pechuga_vitrina", "muslo_vitrina", "contramuslo_vitrina", "ala_vitrina")', (now_iso,))

    # Cocina
    cursor.execute('UPDATE inventory SET stock = 0.0, updated_at = ? WHERE item_key IN ("caldo_raciones", "arroz_raciones", "frijoles_raciones", "papas_raciones", "arepas_unidades")', (now_iso,))

    # Gaseosas antiguas inactivas en cero
    cursor.execute('UPDATE inventory SET stock = 0.0, updated_at = ? WHERE item_key IN ("GAS-COL-400", "GAS-MAN-400", "GAS-COL-15L", "GAS-MAN-15L", "GAS-COC-400", "GAS-ZER-400", "GAS-QUA-400", "GAS-COC-15L")', (now_iso,))

    # Las 15 Bebidas Postobón activas (Exactamente 189 unidades)
    postobon_stocks = {
        'GAS-TEA-DUR-500': 12.0,
        'GAS-TEA-LIM-500': 12.0,
        'GAS-HIT-TRO-500': 12.0,
        'GAS-HIT-MAN-500': 12.0,
        'GAS-HIT-MOR-500': 12.0,
        'GAS-HIT-NP-500': 12.0,
        'GAS-H2O-LIM-600': 15.0,
        'GAS-H2O-LTA-600': 15.0,
        'GAS-H2O-MAR-600': 15.0,
        'GAS-COL-250': 12.0,
        'GAS-MAN-250': 12.0,
        'GAS-HIT-MAN-1L': 12.0,
        'GAS-HIT-NP-1L': 12.0,
        'GAS-MAN-175L': 12.0,
        'GAS-PEP-175L': 12.0,
    }
    for sku, qty in postobon_stocks.items():
        cursor.execute('UPDATE inventory SET stock = ?, updated_at = ? WHERE item_key = ?', (qty, now_iso, sku))

    # 3. Registrar snapshot en daily_initial_inventory para que la conciliación diaria empiece perfecta
    cursor.execute('DELETE FROM daily_initial_inventory WHERE date = ?', (today_str,))
    all_inv = cursor.execute('SELECT item_name, location, stock FROM inventory').fetchall()
    for row in all_inv:
        cursor.execute("""
            INSERT INTO daily_initial_inventory (date, item_name, location, quantity, recorded_by, recorded_at)
            VALUES (?, ?, ?, ?, 'Sistema', ?)
        """, (today_str, row[0], row[1], row[2], now_iso))

    conn.commit()
    conn.close()
    print("Inventario reiniciado con total exactitud.")

def audit_inventory_state():
    conn = sqlite3.connect('data/asadero.db')
    cursor = conn.cursor()
    print("\n--- ESTADO COMPLETO DEL INVENTARIO REINICIADO ---")
    rows = cursor.execute("SELECT location, item_key, name, stock, unit FROM inventory ORDER BY location, name").fetchall()
    for loc, key, name, stock, unit in rows:
        print(f"[{loc:8}] {name:32} ({key:16}): {stock:5.1f} {unit}")
    
    total_nevera = cursor.execute("SELECT SUM(stock) FROM inventory WHERE location = 'Nevera'").fetchone()[0]
    total_bodega_pollos = cursor.execute("SELECT stock FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()[0]
    total_presas_bodega = cursor.execute("SELECT SUM(stock) FROM inventory WHERE item_key IN ('pechuga_nevera', 'muslo_nevera', 'contramuslo_nevera', 'ala_nevera')").fetchone()[0]
    total_vitrina = cursor.execute("SELECT SUM(stock) FROM inventory WHERE location = 'Vitrina'").fetchone()[0]
    total_cocina = cursor.execute("SELECT SUM(stock) FROM inventory WHERE location = 'Cocina'").fetchone()[0]

    print("\n--- RESUMEN AUDITADO ---")
    print(f"Pollos Enteros Crudos en Bodega: {total_bodega_pollos} unidades")
    print(f"Presas Crudas en Bodega/Nevera : {total_presas_bodega} unidades")
    print(f"Presas Listas en Vitrina Térmica: {total_vitrina} unidades")
    print(f"Guarniciones Listas en Cocina  : {total_cocina} raciones")
    print(f"Gaseosas Listas en Nevera      : {total_nevera} botellas")
    print(f"Ventas registradas en base     : {cursor.execute('SELECT COUNT(*) FROM sales').fetchone()[0]}")
    conn.close()

if __name__ == '__main__':
    reset_inventory()
    audit_inventory_state()
