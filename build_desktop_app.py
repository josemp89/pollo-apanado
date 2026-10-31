import os
import subprocess
import sys
import shutil

print("=== INICIANDO COMPILACIÓN DE DON POLLO POS (SIN CONSOLA / GUI PURA) ===")

sep = ";" if os.name == "nt" else ":"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--name", "DonPolloPOS",
    "--onedir",
    "--clean",
    "--noconfirm",
    "--noconsole",  # <--- MODO VENTANA VISUAL PURA (CERO CONSOLA NEGRA)
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

# 1. Script de arranque rápido por BAT
bat_content = """@echo off
cd /d "%~dp0"
start "" "DonPolloPOS.exe"
exit
"""
with open(os.path.join("dist", "DonPolloPOS", "INICIAR_DON_POLLO.bat"), "w", encoding="utf-8") as f:
    f.write(bat_content)

# 2. Script de arranque 100% invisible VBS (ni un milisegundo de ventana)
vbs_content = """Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "DonPolloPOS.exe" & chr(34), 0
Set WshShell = Nothing
"""
with open(os.path.join("dist", "DonPolloPOS", "INICIAR_DON_POLLO.vbs"), "w", encoding="utf-8") as f:
    f.write(vbs_content)

# 3. Script para cerrar el sistema completamente cuando se desee
close_bat_content = """@echo off
taskkill /F /IM DonPolloPOS.exe /T 2>nul
echo Sistema Don Pollo POS cerrado con éxito.
ping 127.0.0.1 -n 2 >nul
"""
with open(os.path.join("dist", "DonPolloPOS", "CERRAR_DON_POLLO.bat"), "w", encoding="utf-8") as f:
    f.write(close_bat_content)

# 4. Crear archivo ZIP para transporte en memoria USB
print("Creando archivo comprimido ZIP para transportar en memoria USB...")
zip_target = os.path.join("dist", "DonPollo_POS_Portable")
shutil.make_archive(zip_target, "zip", os.path.join("dist", "DonPolloPOS"))
print(f"ARCHIVO ZIP LISTO EN: {zip_target}.zip")

# Copiar también directamente al Escritorio de Alejandro
desktop_zip = os.path.expanduser(r"~\Desktop\DonPollo_POS_Portable.zip")
try:
    shutil.copy2(f"{zip_target}.zip", desktop_zip)
    print(f"COPIA DIRECTA AL ESCRITORIO LISTA EN: {desktop_zip}")
except Exception as e:
    print(f"Nota copia escritorio: {e}")

print("=== COMPILACIÓN COMPLETADA CON ÉXITO ===")
