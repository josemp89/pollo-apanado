import os
import uvicorn
import socket
import sys

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

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = int(os.environ.get("PORT", 8000))
    reload_opt = os.environ.get("ENV", "development") == "development"
    
    print("\n" + "="*65)
    print("   [+] SISTEMA POLLO APANADO - SERVIDOR ACTIVO")
    print("="*65)
    print(f" * Desde este Computador:")
    print(f"   -> http://localhost:{port}")
    print(f" * Desde tu Tablet o Celular en red local:")
    print(f"   -> http://{local_ip}:{port}")
    print("="*65)
    print(" Presiona Ctrl + C en esta ventana para detener el servidor.\n")
    
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload_opt)
