import os
import sqlite3
import threading
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.database import get_db_path

logger = logging.getLogger("backup_service")
_backup_lock = threading.Lock()
_last_backup_time: Optional[datetime] = None

def get_backup_dir() -> str:
    db_path = get_db_path()
    if db_path == ":memory:":
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    else:
        base_dir = os.path.dirname(os.path.abspath(db_path))
    backup_dir = os.path.join(base_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def get_live_backup_path() -> str:
    db_path = get_db_path()
    if db_path == ":memory:":
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    else:
        base_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "asadero.backup.db")

def is_sqlite_file_valid(file_path: str) -> bool:
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        if os.path.getsize(file_path) == 0:
            return False
        conn = sqlite3.connect(file_path, timeout=5.0)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchall()
        cur.execute("SELECT count(*) FROM sqlite_master;")
        count = cur.fetchone()[0]
        conn.close()
        return len(res) > 0 and res[0][0] == "ok" and count > 0
    except Exception as e:
        logger.warning(f"Error checking database integrity for {file_path}: {e}")
        return False

def create_live_backup() -> Optional[str]:
    """Crea o actualiza la copia espejo en tiempo real (asadero.backup.db) usando la API nativa de SQLite."""
    global _last_backup_time
    db_path = get_db_path()
    if db_path == ":memory:" or not os.path.exists(db_path):
        return None

    backup_path = get_live_backup_path()
    with _backup_lock:
        src = None
        dst = None
        try:
            src = sqlite3.connect(db_path, timeout=10.0)
            dst = sqlite3.connect(backup_path, timeout=10.0)
            src.backup(dst)
            _last_backup_time = datetime.now()
            logger.info(f"Live backup sincronizado con éxito en {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Fallo al crear live backup: {e}")
            return None
        finally:
            if dst:
                try:
                    dst.close()
                except Exception:
                    pass
            if src:
                try:
                    src.close()
                except Exception:
                    pass

def create_timestamped_snapshot(label: str = "auto") -> Optional[str]:
    """Crea un punto de restauración con marca de tiempo en data/backups/asadero_YYYYMMDD_HHMMSS_{label}.db"""
    global _last_backup_time
    db_path = get_db_path()
    if db_path == ":memory:" or not os.path.exists(db_path):
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
    filename = f"asadero_{timestamp}_{safe_label}.db"
    backup_dir = get_backup_dir()
    snapshot_path = os.path.join(backup_dir, filename)

    with _backup_lock:
        src = None
        dst = None
        try:
            src = sqlite3.connect(db_path, timeout=10.0)
            dst = sqlite3.connect(snapshot_path, timeout=10.0)
            src.backup(dst)
            _last_backup_time = datetime.now()
            logger.info(f"Snapshot guardado exitosamente: {snapshot_path}")
        except Exception as e:
            logger.error(f"Fallo al crear snapshot {snapshot_path}: {e}")
            return None
        finally:
            if dst:
                try:
                    dst.close()
                except Exception:
                    pass
            if src:
                try:
                    src.close()
                except Exception:
                    pass

    # Mantener el espejo en vivo actualizado y rotar
    create_live_backup()
    rotate_snapshots()
    return snapshot_path

def rotate_snapshots(max_keep: int = 30):
    """Elimina snapshots antiguos dejando los más recientes."""
    backup_dir = get_backup_dir()
    try:
        files = [
            os.path.join(backup_dir, f)
            for f in os.listdir(backup_dir)
            if f.startswith("asadero_") and f.endswith(".db")
        ]
        if len(files) <= max_keep:
            return
        files.sort(key=lambda x: os.path.getmtime(x))
        to_delete = files[:-max_keep]
        for f in to_delete:
            try:
                os.remove(f)
                logger.info(f"Snapshot antiguo purgado: {f}")
            except Exception as e:
                logger.warning(f"No se pudo purgar snapshot {f}: {e}")
    except Exception as e:
        logger.warning(f"Error durante rotación de snapshots: {e}")

def trigger_live_backup(label: Optional[str] = None, in_background: bool = True):
    """Dispara respaldo en segundo plano o síncrono."""
    def _run():
        if label:
            create_timestamped_snapshot(label)
        else:
            create_live_backup()

    if in_background:
        t = threading.Thread(target=_run, daemon=True)
        t.start()
    else:
        _run()

def restore_from_snapshot(filename_or_path: str) -> Dict[str, Any]:
    """Restaura la base de datos principal desde un snapshot o archivo .db especificado."""
    db_path = get_db_path()
    backup_dir = get_backup_dir()

    if os.path.isabs(filename_or_path):
        target_path = filename_or_path
    else:
        clean_name = os.path.basename(filename_or_path)
        target_path = os.path.join(backup_dir, clean_name)
        if not os.path.exists(target_path) and clean_name == "asadero.backup.db":
            target_path = get_live_backup_path()

    if not os.path.exists(target_path):
        return {"success": False, "error": f"Archivo de respaldo no encontrado: {target_path}"}

    if not is_sqlite_file_valid(target_path):
        return {"success": False, "error": f"El archivo de respaldo está corrupto o es inválido: {target_path}"}

    with _backup_lock:
        # 1. Guardar snapshot de emergencia del estado actual si existe
        if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
            pre_restore_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_file = os.path.join(backup_dir, f"asadero_{pre_restore_ts}_pre_restore.db")
            try:
                s_cur = sqlite3.connect(db_path, timeout=10.0)
                d_cur = sqlite3.connect(pre_restore_file, timeout=10.0)
                s_cur.backup(d_cur)
                d_cur.close()
                s_cur.close()
            except Exception as e:
                logger.warning(f"No se pudo crear copia previa a la restauración: {e}")

        # 2. Restaurar usando SQLite backup API hacia db_path
        src = None
        dst = None
        try:
            src = sqlite3.connect(target_path, timeout=10.0)
            dst = sqlite3.connect(db_path, timeout=10.0)
            src.backup(dst)
            logger.info(f"Base de datos principal restaurada con éxito desde {target_path}")
        except Exception as e:
            logger.error(f"Error restaurando base de datos: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if dst:
                try:
                    dst.close()
                except Exception:
                    pass
            if src:
                try:
                    src.close()
                except Exception:
                    pass

    # Actualizar copia espejo en vivo
    create_live_backup()
    return {"success": True, "restored_from": target_path, "timestamp": datetime.now().isoformat()}

def verify_and_auto_recover() -> Dict[str, Any]:
    """
    Verifica la base de datos principal al arrancar el sistema.
    Si está ausente, vacía o corrupta, recupera automáticamente desde el espejo en vivo
    o el snapshot válido más reciente.
    Si está sana, genera un snapshot de arranque y actualiza el espejo.
    """
    db_path = get_db_path()
    if db_path == ":memory:":
        return {"status": "memory_mode", "recovered": False}

    is_healthy = is_sqlite_file_valid(db_path)

    if not is_healthy:
        logger.warning(f"Base de datos {db_path} no válida o ausente. Iniciando recuperación automática...")
        live_backup = get_live_backup_path()
        if is_sqlite_file_valid(live_backup):
            res = restore_from_snapshot(live_backup)
            if res.get("success"):
                logger.info(f"Recuperación exitosa desde espejo en vivo: {live_backup}")
                return {"status": "recovered", "source": "live_backup", "path": live_backup}

        # Buscar en snapshots históricos (más reciente primero)
        backup_dir = get_backup_dir()
        if os.path.exists(backup_dir):
            snapshots = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.startswith("asadero_") and f.endswith(".db")
            ]
            snapshots.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            for snap in snapshots:
                if is_sqlite_file_valid(snap):
                    res = restore_from_snapshot(snap)
                    if res.get("success"):
                        logger.info(f"Recuperación exitosa desde snapshot histórico: {snap}")
                        return {"status": "recovered", "source": "snapshot", "path": snap}

        logger.info("No se encontraron copias de seguridad previas válidas. Se creará base de datos limpia.")
        return {"status": "clean_init", "recovered": False}

    # Base de datos sana: generar snapshot de inicio seguro y refrescar espejo
    snap = create_timestamped_snapshot(label="startup")
    return {"status": "healthy", "recovered": False, "startup_snapshot": snap}

def list_snapshots() -> List[Dict[str, Any]]:
    """Lista todos los snapshots disponibles ordenados del más reciente al más antiguo."""
    backup_dir = get_backup_dir()
    result = []
    
    # 1. Espejo en vivo
    live_backup = get_live_backup_path()
    if os.path.exists(live_backup):
        size = os.path.getsize(live_backup)
        mtime = datetime.fromtimestamp(os.path.getmtime(live_backup))
        result.append({
            "filename": os.path.basename(live_backup),
            "full_path": live_backup,
            "size_bytes": size,
            "size_formatted": f"{size / 1024:.1f} KB",
            "modified_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
            "iso_time": mtime.isoformat(),
            "type": "live_mirror",
            "is_valid": is_sqlite_file_valid(live_backup),
            "label": "Espejo en Tiempo Real"
        })

    # 2. Snapshots
    if os.path.exists(backup_dir):
        files = [
            f for f in os.listdir(backup_dir)
            if f.startswith("asadero_") and f.endswith(".db")
        ]
        for f in files:
            fp = os.path.join(backup_dir, f)
            size = os.path.getsize(fp)
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            parts = f.replace(".db", "").split("_")
            label = "_".join(parts[3:]) if len(parts) >= 4 else "auto"
            result.append({
                "filename": f,
                "full_path": fp,
                "size_bytes": size,
                "size_formatted": f"{size / 1024:.1f} KB",
                "modified_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "iso_time": mtime.isoformat(),
                "type": "snapshot",
                "is_valid": is_sqlite_file_valid(fp),
                "label": label
            })

    result.sort(key=lambda x: x["iso_time"], reverse=True)
    return result

def get_backup_status() -> Dict[str, Any]:
    """Retorna el estado general del sistema de respaldos."""
    db_path = get_db_path()
    live_backup = get_live_backup_path()
    snapshots = list_snapshots()
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    return {
        "status": "active",
        "database_path": db_path,
        "database_size_bytes": db_size,
        "database_size_formatted": f"{db_size / 1024:.1f} KB",
        "live_mirror_exists": os.path.exists(live_backup),
        "live_mirror_valid": is_sqlite_file_valid(live_backup) if os.path.exists(live_backup) else False,
        "last_backup_time": _last_backup_time.strftime("%Y-%m-%d %H:%M:%S") if _last_backup_time else "Al inicio",
        "snapshots_count": len([s for s in snapshots if s["type"] == "snapshot"]),
        "snapshots": snapshots
    }
