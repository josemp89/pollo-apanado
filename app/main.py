import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from app.database import init_db
from app.routers import pos, kitchen, cash, inventory, auth, accounting, backup
from app.services.backup import verify_and_auto_recover, trigger_live_backup

app = FastAPI(
    title="Sistema de Gestión y POS - Pollo Apanado",
    description="Punto de Venta Táctil, Control de Tiempos de Cocina, Despiece e Inventario",
    version="1.0.0"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first_err = errors[0] if errors else {}
    field = " -> ".join(str(loc) for loc in first_err.get("loc", []))
    msg = first_err.get("msg", "Dato inválido")
    return JSONResponse(
        status_code=400,
        content={"detail": f"Error de validación en campo '{field}': {msg}", "errors": errors}
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Servir archivos estáticos (CSS, JS, iconos)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Evitar que navegadores (Chrome, Safari iOS) almacenen versiones viejas en caché
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Registrar Routers
app.include_router(pos.router)
app.include_router(kitchen.router)
app.include_router(cash.router)
app.include_router(inventory.router)
app.include_router(auth.router)
app.include_router(accounting.router)
app.include_router(backup.router)

@app.middleware("http")
async def auto_backup_middleware(request: Request, call_next):
    response = await call_next(request)
    # Sincronización continua en segundo plano ante cualquier mutación exitosa
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400:
        if "/api/backup/restore" not in request.url.path:
            trigger_live_backup(in_background=True)
    return response

@app.on_event("startup")
def on_startup():
    # 1. Verificar integridad y recuperar automáticamente si la base de datos se dañó o perdió
    recovery_result = verify_and_auto_recover()
    # 2. Inicializar esquemas y tablas
    init_db()

@app.get("/healthz")
@app.get("/health")
def health_check():
    return {"status": "ok", "app": "Pollo Apanado"}

@app.get("/", response_class=HTMLResponse)
def get_pos_view(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"view": "pos"})

@app.get("/cocina")
def get_kitchen_view(request: Request = None):
    return RedirectResponse(url="/", status_code=307)

@app.get("/caja", response_class=HTMLResponse)
def get_cash_view(request: Request):
    return templates.TemplateResponse(request=request, name="cash.html", context={"view": "cash"})

@app.get("/gerencia", response_class=HTMLResponse)
@app.get("/contabilidad", response_class=HTMLResponse)
def get_management_view(request: Request):
    return templates.TemplateResponse(request=request, name="gerencia.html", context={"view": "gerencia"})

@app.get("/tutorial", response_class=HTMLResponse)
def get_tutorial_view(request: Request):
    return templates.TemplateResponse(request=request, name="tutorial.html", context={"view": "tutorial"})

@app.get("/precios", response_class=HTMLResponse)
@app.get("/cartel-precios", response_class=HTMLResponse)
def get_precios_view(request: Request):
    return templates.TemplateResponse(request=request, name="cartel_precios.html", context={"view": "precios"})

@app.get("/guia-fritura", response_class=HTMLResponse)
@app.get("/fritura", response_class=HTMLResponse)
def get_guia_fritura_view(request: Request):
    return templates.TemplateResponse(request=request, name="guia_fritura.html", context={"view": "fritura"})

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(STATIC_DIR, "manifest.json")
    return FileResponse(manifest_path, media_type="application/manifest+json")

@app.get("/sw.js")
def get_service_worker():
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    return FileResponse(sw_path, media_type="application/javascript")
