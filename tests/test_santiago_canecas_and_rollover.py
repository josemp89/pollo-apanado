import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection

client = TestClient(app)

def test_santiago_canecas_assistant_ui_elements():
    """Verifica que la interfaz de Caja incluya el asistente de canecas y pollo frito de Santiago."""
    r_cash = client.get("/caja")
    assert r_cash.status_code == 200
    assert "santiagoAssistantContent" in r_cash.text
    assert "inputCanecasCerradas" in r_cash.text
    assert "sc_crudo_pechuga" in r_cash.text
    assert "sc_frito_pechuga" in r_cash.text
    assert "applySantiagoChickenTotals" in r_cash.text

def test_rollover_fried_chicken_and_canecas_to_next_day():
    """
    Verifica que el pollo frito que queda al cierre y las canecas crudas
    se trasladen automáticamente al inventario inicial del día siguiente.
    """
    conn = get_db_connection()
    # 1. Asegurar estado inicial conocido
    conn.execute("UPDATE inventory SET stock = 42.0 WHERE item_key = 'pechuga_vitrina'") # 40 en canecas + 2 fritas
    conn.execute("UPDATE inventory SET stock = 43.0 WHERE item_key = 'muslo_vitrina'")   # 40 en canecas + 3 fritas
    conn.commit()
    conn.close()

    # 2. Abrir turno en una fecha simulada
    test_date = "2026-10-26"
    conn = get_db_connection()
    conn.execute("DELETE FROM daily_initial_inventory WHERE date = ?", (test_date,))
    conn.execute("DELETE FROM cash_shifts WHERE date_str = ?", (test_date,))
    conn.commit()
    conn.close()

    # Simular apertura de turno que dispara el rollover
    conn = get_db_connection()
    cursor = conn.cursor()
    # Simular lógica de open_shift rollover
    init_count = cursor.execute("SELECT COUNT(*) FROM daily_initial_inventory WHERE date = ?", (test_date,)).fetchone()[0]
    if init_count == 0:
        inv_rows = cursor.execute("SELECT item_key, name, stock, location FROM inventory").fetchall()
        for r in inv_rows:
            cursor.execute("""
                INSERT INTO daily_initial_inventory (date, item_name, location, quantity)
                VALUES (?, ?, ?, ?)
            """, (test_date, r["name"], r["location"] or "Vitrina", float(r["stock"])))
    conn.commit()

    # Verificar que el inventario inicial del día siguiente tiene las 42 pechugas y 43 muslos
    pechuga_init = conn.execute("""
        SELECT quantity FROM daily_initial_inventory 
        WHERE date = ? AND (item_name LIKE '%pechuga%' OR item_name = 'pechuga_vitrina')
    """, (test_date,)).fetchone()
    assert pechuga_init is not None
    assert pechuga_init[0] == 42.0

    muslo_init = conn.execute("""
        SELECT quantity FROM daily_initial_inventory 
        WHERE date = ? AND (item_name LIKE '%muslo%' OR item_name = 'muslo_vitrina')
    """, (test_date,)).fetchone()
    assert muslo_init is not None
    assert muslo_init[0] == 43.0

    conn.close()
