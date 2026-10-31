import sqlite3
import os

db_paths = [
    os.path.join("data", "asadero.db"),
    os.path.join("dist", "DonPolloPOS", "data", "asadero.db"),
    os.path.expanduser(r"~\Desktop\DonPollo_POS_Portable\data\asadero.db")
]

for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    print(f"Actualizando base de datos en: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 1. Nuevos productos
    c.execute("""
        INSERT OR IGNORE INTO products (sku, name, price, category, icon, active)
        VALUES ('GAS-PON-330', 'Pony Malta 330ml', 3500, 'gaseosas', '🍺', 1)
    """)
    c.execute("""
        UPDATE products SET price = 3500, active = 1 WHERE sku = 'GAS-PON-330'
    """)

    c.execute("""
        INSERT OR IGNORE INTO products (sku, name, price, category, icon, active)
        VALUES ('GAS-TOR-250', 'Postobón Toronja 250ml', 2000, 'gaseosas', '🥤', 1)
    """)
    c.execute("""
        UPDATE products SET price = 2000, active = 1 WHERE sku = 'GAS-TOR-250'
    """)

    # 2. Actualizar inventario de presas de pollo
    chicken_counts = {
        'pechuga_nevera': (179.0, 'Caneca Pechugas Crudas', 'unidad', 'bodega'),
        'contramuslo_nevera': (175.0, 'Caneca Contramuslos Crudos', 'unidad', 'bodega'),
        'muslo_nevera': (160.0, 'Caneca Muslos Crudos', 'unidad', 'bodega'),
        'ala_nevera': (165.0, 'Caneca Alas Crudas', 'unidad', 'bodega'),
        'pechuga_vitrina': (0.0, 'Pechugas en Vitrina', 'unidad', 'vitrina'),
        'contramuslo_vitrina': (0.0, 'Contramuslos en Vitrina', 'unidad', 'vitrina'),
        'muslo_vitrina': (0.0, 'Muslos en Vitrina', 'unidad', 'vitrina'),
        'ala_vitrina': (0.0, 'Alas en Vitrina', 'unidad', 'vitrina'),
    }

    for key, (stock, name, unit, cat) in chicken_counts.items():
        c.execute("""
            INSERT INTO inventory (item_key, name, stock, unit, min_threshold, category, updated_at)
            VALUES (?, ?, ?, ?, 10, ?, datetime('now', 'localtime'))
            ON CONFLICT(item_key) DO UPDATE SET stock = ?, updated_at = datetime('now', 'localtime')
        """, (key, name, stock, unit, cat, stock))

    # 3. Bebidas
    drinks = {
        'GAS-HIT-MAN-500': ('Hit Mango 500ml', 9.0),
        'GAS-HIT-TRO-500': ('Hit Frutas Tropicales 500ml', 2.0),
        'GAS-H2O-MAR-600': ('H2OH! Maracuyá 600ml', 5.0),
        'GAS-H2O-LTA-600': ('H2OH! Limonata 600ml', 3.0),
        'GAS-H2O-LIM-600': ('H2OH! Lima Limón 600ml', 3.0),
        'GAS-AGU-CRI-300': ('Agua Cristal 300ml', 11.0),
        'GAS-AGU-CRI-600': ('Agua Cristal 600ml', 15.0),
        'GAS-TEA-DUR-500': ('Mr Tea Durazno 500ml', 5.0),
        'GAS-TEA-LIM-500': ('Mr Tea Limón 500ml', 2.0),
        'GAS-PON-330': ('Pony Malta 330ml', 14.0),
        'GAS-MAN-400': ('Postobón Manzana 400ml (Nevera)', 1.0),
        'GAS-COL-400': ('Postobón Colombiana 400ml (Nevera)', 1.0),
        'GAS-TOR-250': ('Postobón Toronja 250ml', 10.0),
        'GAS-COL-250': ('Colombiana 250ml', 9.0),
        'GAS-MAN-250': ('Manzana Postobón 250ml', 8.0),
        'GAS-PEP-175L': ('Pepsi 1.75L', 5.0),
        'GAS-MAN-175L': ('Manzana Postobón 1.75L', 5.0),
        'GAS-HIT-TRO-1L': ('Hit Frutas Tropicales 1L Tetra', 4.0),
        'GAS-HIT-NP-1L': ('Hit Naranja Piña 1L Tetra', 4.0),
        'GAS-HIT-MAN-1L': ('Hit Mango 1L Tetra', 4.0),
    }

    for key, (name, stock) in drinks.items():
        c.execute("""
            INSERT INTO inventory (item_key, name, stock, unit, min_threshold, category, updated_at)
            VALUES (?, ?, ?, 'unidad', 2, 'nevera', datetime('now', 'localtime'))
            ON CONFLICT(item_key) DO UPDATE SET stock = ?, updated_at = datetime('now', 'localtime')
        """, (key, name, stock, stock))

    # 4. Adobo TECNAS
    c.execute("""
        INSERT INTO inventory (item_key, name, stock, unit, min_threshold, category, updated_at)
        VALUES ('adobo_tecnas_kg', 'Adobo TECNAS (Condimento Pollo)', 1.0, 'kg', 0.5, 'bodega', datetime('now', 'localtime'))
        ON CONFLICT(item_key) DO UPDATE SET stock = 1.0, updated_at = datetime('now', 'localtime')
    """)

    conn.commit()
    conn.close()
    print(f"Base de datos {db_path} actualizada con éxito.")
