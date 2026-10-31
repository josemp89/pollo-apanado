# -*- coding: utf-8 -*-
"""
DonPolloPOS - Lanzador de Escritorio Autónomo
Pollo Apanado - Sistema POS, Inventario & Contabilidad
"""
import multiprocessing
multiprocessing.freeze_support()

import os
import sys
import time
import socket
import threading
import webbrowser
import subprocess
import traceback

# 1. Configurar directorio base del ejecutable
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

# 2. Configurar la ruta de la base de datos local permanente
DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "asadero.db")
os.environ["DATABASE_PATH"] = DB_PATH

LOG_FILE = os.path.join(APP_DIR, "don_pollo.log")

class SafeLogWriter:
    def __init__(self, filepath):
        self.filepath = filepath
    def write(self, s):
        if not s or s.isspace():
            return
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {s.strip()}\n")
        except Exception:
            pass
    def flush(self):
        pass
    def isatty(self):
        return False

# Redirigir stdout y stderr en modo sin consola (--noconsole) para evitar NoneType errors
if sys.stdout is None:
    sys.stdout = SafeLogWriter(LOG_FILE)
if sys.stderr is None:
    sys.stderr = SafeLogWriter(LOG_FILE)

def log_msg(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def is_already_running(port: int = 8000) -> bool:
    import urllib.request
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.8)
        return req.getcode() == 200
    except Exception:
        return False

def launch_browser(url: str, delay: float = 1.8):
    if delay > 0:
        time.sleep(delay)
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe")
    ]
    for ep in edge_paths:
        if os.path.exists(ep):
            try:
                subprocess.Popen([ep, f"--app={url}"])
                return
            except Exception:
                pass
    webbrowser.open(url)

def main():
    try:
        local_ip = get_local_ip()
        port = int(os.environ.get("PORT", 8000))
        url = f"http://localhost:{port}"
        remote_url = f"http://{local_ip}:{port}"

        # Si ya se encuentra activo en segundo plano, sólo abrimos la ventana y salimos cleanly
        if is_already_running(port):
            log_msg(f"DonPolloPOS ya activo en puerto {port}. Abriendo ventana de app...")
            launch_browser(url, delay=0.1)
            sys.exit(0)

        log_msg("Iniciando aplicación DonPolloPOS (Modo Visual Limpio sin consola)...")
        from app.main import app
        from app.database import init_db
        from app.services.backup import verify_and_auto_recover
        import uvicorn

        # Inicializar base de datos y respaldos
        verify_and_auto_recover()
        init_db()
        log_msg("Base de datos inicializada correctamente")

        # Abrir navegador en ventana de aplicación
        t = threading.Thread(target=launch_browser, args=(url, 1.8), daemon=True)
        t.start()

        # Correr servidor uvicorn silencioso (sin configuración de consola)
        log_msg(f"Arrancando uvicorn en 0.0.0.0:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port, log_config=None)
    except Exception as e:
        err = traceback.format_exc()
        log_msg(f"ERROR CRÍTICO: {err}")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Error iniciando Don Pollo POS:\n{e}", "Don Pollo POS Error", 0x10)
        except Exception:
            pass

if __name__ == "__main__":
    main()
