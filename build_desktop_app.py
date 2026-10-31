import os
import subprocess
import sys
import shutil

print("=== INICIANDO COMPILACIÓN DE DON POLLO POS (PORTABLE WINDOWS EXE) ===")

sep = ";" if os.name == "nt" else ":"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--name", "DonPolloPOS",
    "--onedir",
    "--clean",
    "--noconfirm",
    "--add-data", f"app/static{sep}app/static",
    "--add-data", f"app/templates{sep}app/templates",
    "--hidden-import", "uvicorn",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols",
    "--hidden-import", "uvicorn.protocols.http",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespans",
    "--hidden-import", "uvicorn.lifespans.on",
    "desktop_app.py"
]

print("Ejecutando:", " ".join(cmd))
res = subprocess.run(cmd)
if res.returncode != 0:
    print("Error durante la compilación con PyInstaller!")
    sys.exit(res.returncode)

# Copiar la base de datos actual con los productos y saldo inicial a la carpeta dist/DonPolloPOS/data
dist_data_dir = os.path.join("dist", "DonPolloPOS", "data")
os.makedirs(dist_data_dir, exist_ok=True)

src_db = os.path.join("data", "asadero.db")
dst_db = os.path.join(dist_data_dir, "asadero.db")
if os.path.exists(src_db):
    shutil.copy2(src_db, dst_db)
    print(f"Base de datos copiada exitosamente a: {dst_db}")

# Crear acceso directo / script de arranque rápido
bat_content = """@echo off
title Don Pollo POS - Sistema de Ventas e Inventario
cd /d "%~dp0"
start "" "DonPolloPOS.exe"
exit
"""
with open(os.path.join("dist", "DonPolloPOS", "INICIAR_DON_POLLO.bat"), "w", encoding="utf-8") as f:
    f.write(bat_content)

# Crear archivo ZIP para transporte en memoria USB
print("Creando archivo comprimido ZIP para transportar en memoria USB...")
zip_target = os.path.join("dist", "DonPollo_POS_Portable")
shutil.make_archive(zip_target, "zip", os.path.join("dist", "DonPolloPOS"))
print(f"ARCHIVO ZIP LISTO EN: {zip_target}.zip")
print("=== COMPILACIÓN COMPLETADA CON ÉXITO ===")
