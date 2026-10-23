import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from app.database import init_db
from app.routers import pos, kitchen, cash, inventory

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

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/healthz")
@app.get("/health")
def health_check():
    return {"status": "ok", "app": "Pollo Apanado"}

@app.get("/", response_class=HTMLResponse)
def get_pos_view(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"view": "pos"})

@app.get("/cocina", response_class=HTMLResponse)
def get_kitchen_view(request: Request):
    return templates.TemplateResponse(request=request, name="kitchen.html", context={"view": "kitchen"})

@app.get("/caja", response_class=HTMLResponse)
def get_cash_view(request: Request):
    return templates.TemplateResponse(request=request, name="cash.html", context={"view": "cash"})

@app.get("/tutorial", response_class=HTMLResponse)
def get_tutorial_view(request: Request):
    return templates.TemplateResponse(request=request, name="tutorial.html", context={"view": "tutorial"})

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(STATIC_DIR, "manifest.json")
    return FileResponse(manifest_path, media_type="application/manifest+json")
