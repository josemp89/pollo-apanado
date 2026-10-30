# -*- coding: utf-8 -*-
import os
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from app.database import get_db_connection, get_db_path
from app.services.backup import (
    get_backup_status,
    list_snapshots,
    create_timestamped_snapshot,
    create_live_backup,
    restore_from_snapshot,
    get_backup_dir,
    get_live_backup_path,
    is_sqlite_file_valid
)

router = APIRouter(prefix="/api/backup", tags=["Respaldos & Seguridad"])

class CreateBackupRequest(BaseModel):
    label: Optional[str] = Field("manual", description="Etiqueta descriptiva para el snapshot")

class RestoreBackupRequest(BaseModel):
    pin: Optional[str] = Field(None, description="PIN de administrador requerido para restaurar")

def verify_admin_pin(pin: Optional[str]):
    if not pin:
        raise HTTPException(status_code=403, detail="Se requiere PIN de administración para restaurar el sistema")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = 'admin_pin';")
        row = cur.fetchone()
        expected_pin = row[0] if row else "1780"
        if pin.strip() != expected_pin.strip():
            # También comprobar si coincide con algún admin en app_users
            cur.execute("SELECT count(*) FROM app_users WHERE role = 'admin' AND pin = ?;", (pin.strip(),))
            match_admin = cur.fetchone()[0] > 0
            if not match_admin:
                raise HTTPException(status_code=403, detail="PIN de seguridad inválido")
    finally:
        conn.close()

@router.get("/status")
def backup_status():
    """Retorna el estado de las copias de seguridad en tiempo real y snapshots."""
    return {"success": True, "data": get_backup_status()}

@router.get("/list")
def backup_list():
    """Lista todos los snapshots y respaldos disponibles."""
    snapshots = list_snapshots()
    return {"success": True, "snapshots": snapshots, "total": len(snapshots)}

@router.post("/create")
def trigger_backup(payload: Optional[CreateBackupRequest] = None):
    """Genera un snapshot inmediato con marca de tiempo."""
    label = payload.label if payload and payload.label else "manual"
    snapshot_path = create_timestamped_snapshot(label=label)
    if not snapshot_path:
        raise HTTPException(status_code=500, detail="Error creando la copia de seguridad")
    return {
        "success": True,
        "message": "Copia de seguridad generada con éxito",
        "snapshot_path": snapshot_path,
        "filename": os.path.basename(snapshot_path)
    }

@router.post("/sync-live")
def sync_live():
    """Sincroniza forzosamente el espejo en vivo asadero.backup.db."""
    path = create_live_backup()
    if not path:
        raise HTTPException(status_code=500, detail="Error sincronizando la copia espejo")
    return {"success": True, "message": "Copia espejo sincronizada", "path": path}

@router.get("/download/{filename}")
def download_backup(filename: str):
    """Descarga un archivo .db específico (snapshot, espejo o base activa)."""
    clean_name = os.path.basename(filename)
    backup_dir = get_backup_dir()
    live_backup = get_live_backup_path()
    current_db = get_db_path()

    if clean_name == "asadero.db" or clean_name == "current":
        target_path = current_db
        download_name = f"asadero_actual_{os.path.basename(current_db)}"
    elif clean_name == "asadero.backup.db" or clean_name == "live":
        target_path = live_backup
        download_name = "asadero.backup.db"
    else:
        target_path = os.path.join(backup_dir, clean_name)
        download_name = clean_name

    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {clean_name}")

    return FileResponse(
        target_path,
        media_type="application/x-sqlite3",
        filename=download_name
    )

@router.post("/restore/{filename}")
def restore_backup(filename: str, payload: Optional[RestoreBackupRequest] = None):
    """Restaura el sistema a partir de un snapshot seleccionado."""
    pin = payload.pin if payload else None
    verify_admin_pin(pin)

    clean_name = os.path.basename(filename)
    res = restore_from_snapshot(clean_name)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error", "Error al restaurar"))

    return {
        "success": True,
        "message": f"Base de datos restaurada exitosamente desde {clean_name}",
        "details": res
    }
