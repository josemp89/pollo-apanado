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
    print(f"Asentando contabilidad del 30 de Octubre en: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 1. Compras / Entradas de Mercancía
    c.execute("""
        INSERT OR IGNORE INTO merchandise_entries 
        (entry_code, date, supplier_name, invoice_number, item_name, location, quantity, unit_cost, total_cost, notes, created_at)
        VALUES 
        ('REC-261030-0002', '2026-10-30', 'Distribuidor Urbano La Unión', 'FJSI-47315', 'gaseosas_reposicion_postobon', 'Nevera', 66.0, 1455.3, 96050.0, 'Compra reposición Postobón: 3 Hit Litro, 7 Hit 500, 19 Postobon 250, 6 Agua 600, 6 Agua 300, 15 Pony Malta. Pagado de caja.', datetime('now', 'localtime')),
        ('REC-261030-0003', '2026-10-30', 'TECNAS S.A.', 'REM-TECNAS-3010', 'adobo_tecnas_kg', 'Bodega', 2.0, 17000.0, 34000.0, 'Compra de 2 kg de Adobo TECNAS para condimento de pollo. Pagado de caja.', datetime('now', 'localtime'))
    """)

    # 2. Gastos de Caja Menor (cash_expenses)
    c.execute("""
        DELETE FROM cash_expenses WHERE date_str = '2026-10-30' AND category != 'compra_pollo'
    """)
    c.execute("""
        INSERT INTO cash_expenses 
        (shift_id, timestamp, date_str, amount, category, concept, authorized_by, recipient, receipt_number, payment_source)
        VALUES 
        (1, '2026-10-30T17:30:00', '2026-10-30', 96050, 'proveedor_gaseosas', 'Factura Postobón reposición bebidas', 'Alejandro', 'Distribuidor Urbano La Unión', 'FJSI-47315', 'caja_efectivo'),
        (1, '2026-10-30T18:00:00', '2026-10-30', 34000, 'insumos_adobo', 'Compra 2 kg Adobo TECNAS ($17.000/kg)', 'Alejandro', 'TECNAS', 'REM-TECNAS-3010', 'caja_efectivo'),
        (1, '2026-10-30T19:30:00', '2026-10-30', 11500, 'alimentacion_personal', 'Alimentación empleados (desayuno, almuerzo, cena)', 'Santiago', 'Personal Asadero', 'VALE-ALIM-3010', 'caja_efectivo')
    """)

    # 3. Libro de Ingresos Diarios (daily_income_ledger)
    c.execute("""
        INSERT INTO daily_income_ledger (date_str, income_cash, income_digital, income_datafono, income_total, source, notes, updated_at)
        VALUES ('2026-10-30', 501550, 51000, 0, 552550, 'pos_reconciliation', 'Ventas brutas 30 de Octubre ($552.550 COP) - Egresos de caja ($141.550 COP: Postobón $96.050 + Adobo $34.000 + Alimentación $11.500) = $411.000 COP libres del día', datetime('now', 'localtime'))
        ON CONFLICT(date_str) DO UPDATE SET
            income_cash = 501550,
            income_digital = 51000,
            income_datafono = 0,
            income_total = 552550,
            source = 'pos_reconciliation',
            notes = 'Ventas brutas 30 de Octubre ($552.550 COP) - Egresos de caja ($141.550 COP: Postobón $96.050 + Adobo $34.000 + Alimentación $11.500) = $411.000 COP libres del día',
            updated_at = datetime('now', 'localtime')
    """)

    # 4. Turno de Caja Cerrado (cash_shifts)
    c.execute("""
        INSERT INTO cash_shifts 
        (id, shift_code, date_str, opened_at, closed_at, cashier_name, base_inicial, cash_sales, digital_sales, datafono_sales, total_sales, total_expenses, expected_cash, actual_cash, difference, closing_notes, status)
        VALUES 
        (2, 'TURNO-20261030-01', '2026-10-30', '2026-10-30T09:00:00', '2026-10-30T22:00:00', 'Santiago', 150000, 501550, 51000, 0, 552550, 141550, 510000, 510000, 0, 'Cierre de turno 30 de Octubre. Cuadre perfecto. Retiro efectivo socio $310.000 + Nequi $51.000. Quedan en cajón $150.000 base + $50.000 remanente.', 'cerrado')
        ON CONFLICT(id) DO UPDATE SET
            shift_code = 'TURNO-20261030-01',
            date_str = '2026-10-30',
            opened_at = '2026-10-30T09:00:00',
            closed_at = '2026-10-30T22:00:00',
            cashier_name = 'Santiago',
            base_inicial = 150000,
            cash_sales = 501550,
            digital_sales = 51000,
            datafono_sales = 0,
            total_sales = 552550,
            total_expenses = 141550,
            expected_cash = 510000,
            actual_cash = 510000,
            difference = 0,
            closing_notes = 'Cierre de turno 30 de Octubre. Cuadre perfecto. Retiro efectivo socio $310.000 + Nequi $51.000. Quedan en cajón $150.000 base + $50.000 remanente.',
            status = 'cerrado'
    """)

    conn.commit()
    conn.close()
    print(f"Contabilidad asentada con éxito en {db_path}.")
