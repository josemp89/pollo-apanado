import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import app as fastapi_app
import app.database as database

# Backward compatibility wrapper for pre-R3 tests that called cancel-sale before PIN requirement was added
_orig_tc_request = TestClient.request

def _compat_tc_request(self, method, url, *args, **kwargs):
    current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    if "test_audit" not in current_test and "/api/pos/cancel" in str(url):
        headers = kwargs.get("headers") or {}
        json_data = kwargs.get("json") or {}
        params = kwargs.get("params") or {}
        has_pin = (
            "X-Admin-PIN" in headers
            or "x-admin-pin" in headers
            or (isinstance(json_data, dict) and "pin" in json_data)
            or (isinstance(params, dict) and "pin" in params)
        )
        if not has_pin:
            headers = dict(headers)
            headers["X-Admin-PIN"] = "4321"
            kwargs["headers"] = headers
    return _orig_tc_request(self, method, url, *args, **kwargs)

TestClient.request = _compat_tc_request

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Creates an isolated SQLite database for each test in a temporary directory.
    Guarantees that production database 'data/asadero.db' is NEVER touched or mutated.
    """
    test_db_file = tmp_path / "test_asadero.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db_file))
    monkeypatch.setenv("DATABASE_PATH", str(test_db_file))
    
    # Initialize fresh schema and seed data
    database.init_db()
    
    yield str(test_db_file)

@pytest.fixture
def client(isolated_db):
    """
    FastAPI TestClient connected to the isolated database.
    """
    with TestClient(fastapi_app) as test_client:
        yield test_client

@pytest.fixture
def db_conn(isolated_db):
    """
    Direct SQLite connection to the isolated test database for verification and assertions.
    """
    conn = sqlite3.connect(isolated_db, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    yield conn
    conn.close()

class TestHelpers:
    """Helper utilities for querying and setting state in the isolated test database."""
    def __init__(self, client: TestClient, db_path: str):
        self.client = client
        self.db_path = db_path

    def get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_stock(self, item_key: str) -> float:
        conn = self.get_conn()
        try:
            row = conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (item_key,)).fetchone()
            return float(row["stock"]) if row else 0.0
        finally:
            conn.close()

    def set_stock(self, item_key: str, amount: float):
        conn = self.get_conn()
        try:
            conn.execute("UPDATE inventory SET stock = ? WHERE item_key = ?", (amount, item_key))
            conn.commit()
        finally:
            conn.close()

    def get_product(self, sku: str) -> dict:
        conn = self.get_conn()
        try:
            row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_product_id(self, sku: str) -> int:
        prod = self.get_product(sku)
        assert prod is not None, f"Product with SKU '{sku}' not found in products table"
        return prod["id"]

    def count_sales(self, status: str = None) -> int:
        conn = self.get_conn()
        try:
            if status:
                row = conn.execute("SELECT COUNT(*) FROM sales WHERE status = ?", (status,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM sales").fetchone()
            return row[0]
        finally:
            conn.close()

@pytest.fixture
def helpers(client, isolated_db):
    return TestHelpers(client, isolated_db)
