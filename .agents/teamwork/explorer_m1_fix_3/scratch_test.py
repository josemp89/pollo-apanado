import sqlite3
import pytest

def test_full_validation_and_check():
    conn = sqlite3.connect(':memory:')
    conn.execute('''
    CREATE TABLE inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_key TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        stock REAL NOT NULL DEFAULT 0 CHECK (stock >= 0),
        unit TEXT NOT NULL,
        min_threshold REAL DEFAULT 5,
        updated_at TEXT
    );
    ''')
    conn.execute("INSERT INTO inventory (item_key, name, category, stock, unit) VALUES ('pechuga_vitrina', 'Pechuga', 'vitrina', 10.0, 'unidad')")

    # 1. Decrement down to 0
    conn.execute("UPDATE inventory SET stock = stock - 10.0 WHERE item_key = 'pechuga_vitrina' AND stock >= 10.0")
    assert conn.execute("SELECT stock FROM inventory WHERE item_key = 'pechuga_vitrina'").fetchone()[0] == 0.0

    # 2. Atomic check prevents decrement below 0
    cursor = conn.cursor()
    cursor.execute("UPDATE inventory SET stock = stock - 1.0 WHERE item_key = 'pechuga_vitrina' AND stock >= 1.0")
    assert cursor.rowcount == 0  # Application level guard catches it

    # 3. Direct update attempting negative stock triggers engine-level CHECK constraint
    try:
        conn.execute("UPDATE inventory SET stock = -0.5 WHERE item_key = 'pechuga_vitrina'")
        assert False, "Should have raised IntegrityError"
    except sqlite3.IntegrityError as e:
        assert "CHECK constraint failed" in str(e)
        print("Verified: SQLite engine CHECK constraint raised IntegrityError as expected:", e)

if __name__ == "__main__":
    test_full_validation_and_check()
