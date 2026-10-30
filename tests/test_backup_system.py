# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import sqlite3
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection, get_db_path, init_db
from app.services.backup import (
    create_live_backup,
    create_timestamped_snapshot,
    rotate_snapshots,
    verify_and_auto_recover,
    restore_from_snapshot,
    get_backup_status,
    list_snapshots,
    is_sqlite_file_valid
)

@pytest.fixture
def backup_env(tmp_path):
    test_db = str(tmp_path / "asadero.db")
    backup_db = str(tmp_path / "asadero.backup.db")
    backups_dir = str(tmp_path / "backups")
    os.makedirs(backups_dir, exist_ok=True)
    
    import app.database
    original_path = app.database.DB_PATH
    app.database.DB_PATH = test_db
    
    init_db()
    create_live_backup()
    
    yield {
        "db": test_db,
        "backup": backup_db,
        "backups_dir": backups_dir,
        "tmp_path": tmp_path
    }
    
    app.database.DB_PATH = original_path

def test_live_backup_creation_and_integrity(backup_env):
    conn = get_db_connection()
    now_iso = datetime.now().isoformat()
    conn.execute("INSERT INTO cash_expenses (timestamp, date_str, amount, category, concept, payment_source, authorized_by) VALUES (?, '2026-10-30', 50000, 'insumos', 'Test Gasto', 'caja_efectivo', 'Alejandro');", (now_iso,))
    conn.commit()
    conn.close()

    backup_path = create_live_backup()
    assert backup_path is not None
    assert os.path.exists(backup_path)
    assert is_sqlite_file_valid(backup_path)

    # Verify expense exists in backup
    b_conn = sqlite3.connect(backup_path)
    cur = b_conn.cursor()
    cur.execute("SELECT amount, concept FROM cash_expenses WHERE concept = 'Test Gasto';")
    row = cur.fetchone()
    b_conn.close()
    assert row is not None
    assert row[0] == 50000

def test_timestamped_snapshot_and_rotation(backup_env):
    for i in range(5):
        create_timestamped_snapshot(label=f"test_snap_{i}")
    
    snaps = list_snapshots()
    # At least 5 snapshots plus live mirror
    assert len(snaps) >= 5

    # Test rotation
    rotate_snapshots(max_keep=2)
    backups_dir = backup_env["backups_dir"]
    files = [f for f in os.listdir(backups_dir) if f.startswith("asadero_") and f.endswith(".db")]
    assert len(files) <= 2

def test_auto_recovery_from_live_mirror(backup_env):
    test_db = backup_env["db"]
    
    # 1. Add unique record
    conn = get_db_connection()
    now_iso = datetime.now().isoformat()
    conn.execute("INSERT INTO cash_expenses (timestamp, date_str, amount, category, concept, payment_source, authorized_by) VALUES (?, '2026-10-30', 99999, 'insumos', 'Recuperacion Magica', 'caja_efectivo', 'Alejandro');", (now_iso,))
    conn.commit()
    conn.close()

    # 2. Sync live mirror
    create_live_backup()

    # 3. Simulate disaster: delete main asadero.db
    if os.path.exists(test_db):
        os.remove(test_db)
    assert not os.path.exists(test_db)

    # 4. Trigger auto-recovery
    recovery_result = verify_and_auto_recover()
    assert recovery_result["status"] == "recovered"
    assert os.path.exists(test_db)
    assert is_sqlite_file_valid(test_db)

    # 5. Verify the recovered record exists in the restored main DB
    recovered_conn = get_db_connection()
    cur = recovered_conn.cursor()
    cur.execute("SELECT amount FROM cash_expenses WHERE concept = 'Recuperacion Magica';")
    row = cur.fetchone()
    recovered_conn.close()
    assert row is not None
    assert row[0] == 99999

def test_backup_api_endpoints():
    create_live_backup()
    client = TestClient(app)

    # Status
    res = client.get("/api/backup/status")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "data" in data
    assert data["data"]["live_mirror_valid"] is True

    # Create snapshot via API
    res_create = client.post("/api/backup/create", json={"label": "pytest_api"})
    assert res_create.status_code == 200
    assert res_create.json()["success"] is True
    created_file = res_create.json()["filename"]

    # List
    res_list = client.get("/api/backup/list")
    assert res_list.status_code == 200
    files = [s["filename"] for s in res_list.json()["snapshots"]]
    assert created_file in files

    # Download
    res_down = client.get(f"/api/backup/download/{created_file}")
    assert res_down.status_code == 200
    assert len(res_down.content) > 0

    # Restore requires PIN
    res_bad_pin = client.post(f"/api/backup/restore/{created_file}", json={"pin": "0000"})
    assert res_bad_pin.status_code == 403

    # Restore with correct PIN (1780)
    res_restore = client.post(f"/api/backup/restore/{created_file}", json={"pin": "1780"})
    assert res_restore.status_code == 200
    assert res_restore.json()["success"] is True
