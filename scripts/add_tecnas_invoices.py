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
    print(f"Registrando facturas TECNAS y Flete en: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 1. Registrar Compras en merchandise_entries
    c.execute("""
        INSERT OR IGNORE INTO merchandise_entries 
        (entry_code, date, supplier_name, invoice_number, item_name, location, quantity, unit_cost, total_cost, notes, created_at)
        VALUES 
        ('REC-261030-0004', '2026-10-30', 'TECNAS S.A. BIC.', 'CADO212362', 'adobo_tecnas_20kg', 'Bodega', 20.0, 16944.9, 338898.0, 'Compra fábrica 20 kg Adobo Pollo Frito TECNAS (4 bolsas x 5kg). Lote 271627 Vence 2027/08/30. Pagado con dinero de realiso acumulado (Caja General).', '2026-10-30T13:26:33'),
        ('REC-261030-0005', '2026-10-30', 'Transportadora La Prensa del Valle S.A.S', 'CE11511536', 'flete_adobo_tecnas', 'Bodega', 1.0, 31898.0, 31898.0, 'Flete transporte y manejo 20kg adobo TECNAS Cali a La Unión. Remesa CE11511536. Pagado con dinero de realiso acumulado (Caja General).', '2026-10-30T13:31:31')
    """)

    # 2. Registrar en cash_expenses clasificado como pago de Caja General / Fondo Realiso (no afecta arqueo de mostrador)
    c.execute("""
        INSERT OR IGNORE INTO cash_expenses 
        (shift_id, timestamp, date_str, amount, category, concept, authorized_by, recipient, receipt_number, payment_source)
        VALUES 
        (NULL, '2026-10-30T13:26:33', '2026-10-30', 338898, 'compra_insumos', 'Compra fábrica 20 kg Adobo Pollo Frito TECNAS (4x5kg) Lote 271627', 'Alejandro', 'TECNAS S.A. BIC. (NIT 800011002)', 'CADO212362', 'fondo_realiso_socio'),
        (NULL, '2026-10-30T13:31:31', '2026-10-30', 31898, 'flete_transporte', 'Flete transporte La Unión 20kg Adobo TECNAS (Remesa CE11511536)', 'Alejandro', 'Transportadora La Prensa del Valle (NIT 890301067)', 'CE11511536', 'fondo_realiso_socio')
    """)

    # 3. Actualizar el inventario de bodega de Adobo a 20 kilos
    c.execute("""
        UPDATE inventory 
        SET stock = 20.0, updated_at = datetime('now', 'localtime') 
        WHERE item_key = 'adobo_tecnas_kg'
    """)

    conn.commit()
    conn.close()
    print(f"Registros completados exitosamente en: {db_path}")
