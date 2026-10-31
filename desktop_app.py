# -*- coding: utf-8 -*-
"""
DonPolloPOS - Lanzador de Escritorio Autónomo
Pollo Apanado - Sistema POS, Inventario & Contabilidad
"""
import os
import sys
import time
import socket
import threading
import webbrowser
import subprocess
import uvicorn

# 1. Configurar directorio base del ejecutable
if getattr(sys, 'frozen', False):
    # Ejecutándose como ejecutable compilado (PyInstaller)
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    # Ejecutándose como script python normal
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

# 2. Configurar la ruta de la base de datos local permanente
DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "asadero.db")
os.environ["DATABASE_PATH"] = DB_PATH

# 3. Importar app después de setear las variables de entorno
from app.main import app
from app.database import init_db
from app.services.backup import verify_and_auto_recover

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

def launch_browser(url: str):
    time.sleep(1.8)
    # Intentar abrir con Microsoft Edge en modo aplicación tipo app nativa
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
    local_ip = get_local_ip()
    port = int(os.environ.get("PORT", 8000))
    url = f"http://localhost:{port}"
    remote_url = f"http://local_ip:{port}".replace("local_ip", local_ip)

    print("\n" + "="*65)
    print("   [+] SISTEMA POLLO APANADO - PROGRAMA DE ESCRITORIO")
    print("   [+] BASE DE DATOS LOCAL Y SEGURA (OFFLINE)")
    print("="*65)
    print(f" * Computador Local:       {url}")
    print(f" * Celulares / Tablets:    {remote_url}")
    print("="*65)
    print(" La base de datos y los respaldos estan guardados permanentemente")
    print(f" en: {DATA_DIR}")
    print("="*65 + "\n")

    # Inicializar base de datos y respaldos
    verify_and_auto_recover()
    init_db()

    # Abrir navegador en ventana de aplicación
    t = threading.Thread(target=launch_browser, args=(url,), daemon=True)
    t.start()

    # Correr servidor uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

if __name__ == "__main__":
    main()
