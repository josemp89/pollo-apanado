import sqlite3
from datetime import datetime

def update_inventory():
    conn = sqlite3.connect('data/asadero.db')
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Asegurar la creación de nuevos productos en tabla products
    new_products = [
        ('GAS-AGU-CRI-600', 'Agua Cristal 600ml', 'gaseosas', 3000, 1200, 0, '💧', 'sky', 1),
        ('GAS-COL-175L', 'Postobón Colombiana 1.75L', 'gaseosas', 6500, 3750, 0, '🍾', 'rose', 1),
        ('GAS-HIT-TRO-1L', 'Hit Frutas Tropicales 1L Tetra', 'gaseosas', 6500, 2500, 0, '🧃', 'orange', 1)
    ]
    for p in new_products:
        cursor.execute("""
            INSERT INTO products (sku, name, category, price, cost, requires_presa_selection, icon, badge_color, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                price = excluded.price,
                cost = excluded.cost,
                icon = excluded.icon,
                badge_color = excluded.badge_color,
                active = excluded.active;
        """, p)

    # 2. Asegurar que existan en la tabla inventory
    new_inventory_items = [
        ('GAS-AGU-CRI-600', 'Agua Cristal 600ml', 'nevera', 17.0, 'unidad', 5.0, 'Nevera', 'Agua Cristal 600ml'),
        ('GAS-COL-175L', 'Postobón Colombiana 1.75L', 'nevera', 2.0, 'unidad', 4.0, 'Nevera', 'Postobón Colombiana 1.75L'),
        ('GAS-HIT-TRO-1L', 'Hit Frutas Tropicales 1L Tetra', 'nevera', 1.0, 'unidad', 4.0, 'Nevera', 'Hit Frutas Tropicales 1L Tetra')
    ]
    for it in new_inventory_items:
        cursor.execute("""
            INSERT INTO inventory (item_key, name, category, stock, unit, min_threshold, updated_at, location, item_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                name = excluded.name,
                location = excluded.location,
                item_name = excluded.item_name;
        """, (it[0], it[1], it[2], it[3], it[4], it[5], now_iso, it[6], it[7]))

    # 3. Eliminar harina y aceite del inventario activo
    cursor.execute('DELETE FROM inventory WHERE item_key IN ("harina_apanar_kg", "aceite_fritura_lt")')
    cursor.execute('DELETE FROM daily_initial_inventory WHERE item_name IN ("harina_apanar_kg", "aceite_fritura_lt", "Harina Apanador", "Aceite para Freidoras")')

    # 4. Actualizar las existencias exactas del conteo físico (Arqueo real)
    exact_stocks = {
        # Presas en canecas de bodega
        'pechuga_nevera': 40.0,
        'muslo_nevera': 50.0,
        'contramuslo_nevera': 45.0,
        'ala_nevera': 34.0,
        'pollo_entero_crudo': 0.0,

        # Vitrina térmica (al cierre de la jornada)
        'pechuga_vitrina': 0.0,
        'muslo_vitrina': 0.0,
        'contramuslo_vitrina': 0.0,
        'ala_vitrina': 0.0,

        # Acompañamientos / Cocina
        'arepas_unidades': 50.0,
        'papas_raciones': 0.0,
        'caldo_raciones': 0.0,
        'arroz_raciones': 0.0,
        'frijoles_raciones': 0.0,

        # Bebidas en Nevera
        'GAS-HIT-MAN-500': 9.0,
        'GAS-HIT-NP-500': 5.0,
        'GAS-HIT-TRO-500': 4.0,
        'GAS-HIT-MOR-500': 0.0,
        'GAS-HIT-NP-1L': 5.0,
        'GAS-HIT-MAN-1L': 4.0,   # 3 + 1 = 4
        'GAS-HIT-TRO-1L': 1.0,
        'GAS-TEA-DUR-500': 6.0,
        'GAS-TEA-LIM-500': 4.0,
        'GAS-H2O-LTA-600': 5.0,
        'GAS-H2O-MAR-600': 5.0,
        'GAS-H2O-LIM-600': 3.0,
        'GAS-AGU-CRI-600': 17.0,  # 7 + 10 = 17
        'GAS-MAN-175L': 6.0,
        'GAS-PEP-175L': 5.0,
        'GAS-COL-175L': 2.0,
        'GAS-COL-250': 11.0,
        'GAS-MAN-250': 13.0,

        # Bebidas inactivas legacy en 0.0
        'GAS-COL-400': 0.0,
        'GAS-MAN-400': 0.0,
        'GAS-COL-15L': 0.0,
        'GAS-MAN-15L': 0.0,
        'GAS-COC-400': 0.0,
        'GAS-ZER-400': 0.0,
        'GAS-QUA-400': 0.0,
        'GAS-COC-15L': 0.0,
    }

    for key, qty in exact_stocks.items():
        cursor.execute("UPDATE inventory SET stock = ?, updated_at = ? WHERE item_key = ?", (qty, now_iso, key))

    # 5. Sincronizar daily_initial_inventory para mantener conciliación perfecta
    cursor.execute('DELETE FROM daily_initial_inventory WHERE date = ?', (today_str,))
    all_inv = cursor.execute('SELECT item_name, location, stock FROM inventory').fetchall()
    for row in all_inv:
        cursor.execute("""
            INSERT INTO daily_initial_inventory (date, item_name, location, quantity, recorded_by, recorded_at)
            VALUES (?, ?, ?, ?, 'Arqueo Real Usuario', ?)
        """, (today_str, row[0], row[1], row[2], now_iso))

    conn.commit()
    conn.close()
    print("Inventario actualizado con total éxito según arqueo del usuario.")

if __name__ == '__main__':
    update_inventory()
