import os
import time
import shutil
import threading
import sqlite3
import cv2
import numpy as np
import uvicorn
from playwright.sync_api import sync_playwright

TEST_PORT = 8877
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
RAW_DIR = "temp_raw_video"
OUTPUT_MP4 = "TUTORIAL_SISTEMA_POLLO_APANADO.mp4"
STATIC_MP4 = os.path.join("app", "static", "videos", "tutorial_pollo_apanado.mp4")
STATIC_WEBM = os.path.join("app", "static", "videos", "tutorial_pollo_apanado.webm")

def run_server():
    uvicorn.run("app.main:app", host="127.0.0.1", port=TEST_PORT, log_level="warning")

def record_browser_actions():
    if os.path.exists(RAW_DIR):
        shutil.rmtree(RAW_DIR, ignore_errors=True)
    os.makedirs(RAW_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )
        context = browser.new_context(
            record_video_dir=RAW_DIR,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        # ----------------------------------------------------
        # CAPÍTULO 1: PORTADA Y APERTURA DEL MOSTRADOR
        # ----------------------------------------------------
        page.goto(f"{BASE_URL}/")
        page.wait_for_selector("#productsGrid button")
        time.sleep(2.0)

        # ----------------------------------------------------
        # CAPÍTULO 2: ENTRADA DE PROVEEDORES (COMPRAS)
        # ----------------------------------------------------
        # Click en el botón único superior de Proveedores
        prov_btn = page.locator("#btnOpenSupplierEntry").first
        prov_btn.hover()
        time.sleep(0.8)
        prov_btn.click()
        time.sleep(1.2)

        # Llenar formulario de proveedor
        page.fill("#supplierNameInput", "Avícola Los Pollos")
        time.sleep(0.5)
        page.fill("#supplierInvoiceInput", "REM-40892")
        time.sleep(0.5)
        page.select_option("#supplierLocationSelect", "Bodega")
        time.sleep(0.5)
        page.select_option("#supplierItemSelect", "pollo_entero_crudo")
        time.sleep(0.5)
        page.fill("#supplierQuantityInput", "20")
        time.sleep(0.5)
        page.fill("#supplierTotalCostInput", "180000")
        time.sleep(0.5)
        page.fill("#supplierNotesInput", "Lote fresco 1.8 kg - Conservar congelador")
        time.sleep(1.0)

        # Confirmar entrada
        page.click("#btnSubmitSupplierEntry")
        time.sleep(2.5)

        # ----------------------------------------------------
        # CAPÍTULO 3: VENTAS EN MOSTRADOR (POS TÁCTIL)
        # ----------------------------------------------------
        # Agregar Contramuslo Solo
        contra_btn = page.locator("button:has-text('Contramuslo Solo')").first
        contra_btn.click()
        time.sleep(0.8)

        # Incrementar cantidad a 2 con el botón + del ticket
        plus_btn = page.locator("button[data-action='increment']").first
        plus_btn.click()
        time.sleep(0.8)

        # Agregar Pechuga Sola
        pec_btn = page.locator("button:has-text('Pechuga Sola')").first
        pec_btn.click()
        time.sleep(0.8)

        # Agregar Almuerzo Completo (con selección obligatoria de presa)
        alm_btn = page.locator("button:has-text('Almuerzo Completo')").first
        alm_btn.click()
        time.sleep(1.0)

        # En el modal de presas, seleccionar Pechuga
        page.click("#btn-presa-pechuga")
        time.sleep(1.0)

        # Filtrar categoría Gaseosas y agregar Colombiana
        page.click("button[data-category='gaseosas']")
        time.sleep(0.8)
        page.locator("button:has-text('Colombiana 400ml')").first.click()
        time.sleep(1.2)

        # Volver a categoría TODOS
        page.click("button[data-category='todos']")
        time.sleep(1.0)

        # Cobrar en EFECTIVO
        page.locator("button:has-text('EFECTIVO')").first.click()
        time.sleep(1.0)

        # Calculadora de efectivo: seleccionar billete +$50.000
        page.click("button:has-text('+$50.000')")
        time.sleep(0.8)
        # Y billete +$10.000 (total recibido $60.000)
        page.click("button:has-text('+$10.000')")
        time.sleep(1.2)

        # Confirmar cobro
        page.click("#btnConfirmCashPayment")
        time.sleep(2.5)

        # ----------------------------------------------------
        # CAPÍTULO 4: COCINA & TIEMPOS (DESPIECE Y PRODUCCIÓN)
        # ----------------------------------------------------
        page.click("a[href='/cocina']")
        page.wait_for_selector("#inputWholeChickens")
        time.sleep(1.5)

        # Ingresar despiece de 5 pollos
        page.fill("#inputWholeChickens", "5")
        time.sleep(1.0)
        page.click("button:has-text('CONFIRMAR ENTRADA DE DESPIECE')")
        time.sleep(2.0)

        # Iniciar cronómetro de fritura rápida
        page.locator("button:has-text('FRITURA')").first.click()
        time.sleep(2.0)

        # ----------------------------------------------------
        # CAPÍTULO 5: CAJA & SOCIOS (CUADRE Y ARQUEO DIARIO)
        # ----------------------------------------------------
        page.click("a[href='/caja']")
        page.wait_for_selector("#reconciliationTableBody")
        time.sleep(1.5)

        # Scroll suave para ver desglose de ventas y presas
        page.mouse.wheel(0, 300)
        time.sleep(1.5)

        # Scroll para ver la Conciliación de Inventario (Cero Deriva)
        page.mouse.wheel(0, 400)
        time.sleep(2.0)

        # Scroll para ver el Candado Antifraude y el Arqueo de Vitrina
        page.mouse.wheel(0, 400)
        time.sleep(2.5)

        # Volver al inicio de Caja
        page.mouse.wheel(0, -1100)
        time.sleep(1.5)

        # Cerrar contexto y guardar video
        context.close()
        browser.close()

def annotate_and_convert_video():
    files = [f for f in os.listdir(RAW_DIR) if f.endswith(".webm")]
    if not files:
        raise RuntimeError("No se generó el video raw de Playwright")

    raw_path = os.path.join(RAW_DIR, files[0])
    print(f"Video raw capturado: {raw_path}")

    # Guardar copia webm para streaming web nativo
    os.makedirs(os.path.dirname(STATIC_WEBM), exist_ok=True)
    shutil.copyfile(raw_path, STATIC_WEBM)

    cap = cv2.VideoCapture(raw_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)

    print(f"Procesando {total_frames} fotogramas a {fps:.1f} fps ({width}x{height})...")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_MP4, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_sec = frame_idx / fps

        # Determinar capítulo y subtítulo según el tiempo
        if timestamp_sec < 4.0:
            badge = "BIENVENIDA"
            title = "SISTEMA DE GESTION POLLO APANADO - TUTORIAL OPERATIVO"
            sub = "Punto de Venta Mostrador, Proveedores, Despiece de Cocina y Arqueo de Caja"
            color_badge = (30, 160, 245)
        elif timestamp_sec < 14.0:
            badge = "PASO 1: ENTRADA PROVEEDORES"
            title = "RECEPCION DE INSUMOS (Pollos Crudos, Harina, Aceite, Gaseosas)"
            sub = "Boton azul superior: Se digita Factura/Remision y se suma atomicamente al stock"
            color_badge = (240, 120, 20)
        elif timestamp_sec < 28.0:
            badge = "PASO 2: VENTA EN MOSTRADOR"
            title = "DESPACHO EN VIVO, SELECCION DE PRESA Y CALCULADORA DE CAMBIO"
            sub = "Ticket reactivo a la derecha (+ / -), seleccion de presa en almuerzos y cobro en 1 toque"
            color_badge = (30, 200, 80)
        elif timestamp_sec < 39.0:
            badge = "PASO 3: COCINA & TIEMPOS"
            title = "REGISTRO DE DESPIECE MATUTINO (Regla 1 Pollo = 8 Presas + Caldo)"
            sub = "Control de stock de congelador a vitrina caliente y cronometros de freidoras"
            color_badge = (20, 150, 230)
        else:
            badge = "PASO 4: CUADRE DE CAJA DIARIO"
            title = "ARQUEO EXPLÍCITO, FORMULA DE EFECTIVO Y CANDADO ANTIFRAUDE"
            sub = "Efectivo en Cajon = Base Inicial + Ventas Efectivo. Nequi y Datafono separados"
            color_badge = (200, 60, 60)

        # Dibujar banner inferior elegante semi-transparente
        banner_h = 75
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, height - banner_h), (width, height), (15, 23, 42), -1)
        # Línea de acento superior
        cv2.rectangle(overlay, (0, height - banner_h), (width, height - banner_h + 3), color_badge, -1)
        cv2.addWeighted(overlay, 0.88, frame, 0.12, 0, frame)

        # Dibujar Badge
        cv2.rectangle(frame, (20, height - banner_h + 12), (20 + len(badge)*9 + 20, height - banner_h + 34), color_badge, -1)
        cv2.putText(frame, badge, (30, height - banner_h + 28), cv2.FONT_HERSHEY_DUPLEX, 0.45, (10, 10, 10), 1, cv2.LINE_AA)

        # Dibujar Título
        cv2.putText(frame, title, (20 + len(badge)*9 + 32, height - banner_h + 28), cv2.FONT_HERSHEY_DUPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

        # Dibujar Subtítulo explicativo
        cv2.putText(frame, sub, (25, height - 16), cv2.FONT_HERSHEY_DUPLEX, 0.42, (200, 210, 225), 1, cv2.LINE_AA)

        # Barra de progreso del video
        progress_w = int((frame_idx / total_frames) * width)
        cv2.rectangle(frame, (0, height - 4), (progress_w, height), color_badge, -1)

        out.write(frame)
        frame_idx += 1

    cap.release()
    out.release()
    print("Video renderizado y guardado exitosamente en:", OUTPUT_MP4)

    # Copiar a carpeta estática de la app web
    shutil.copyfile(OUTPUT_MP4, STATIC_MP4)
    print("Copia estática generada en:", STATIC_MP4)

if __name__ == "__main__":
    print("Iniciando servidor temporal en segundo plano...")
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2.0)

    print("Grabando recorrido completo del sistema con Playwright...")
    record_browser_actions()

    print("Añadiendo subtítulos dinámicos y convirtiendo a MP4...")
    annotate_and_convert_video()

    print("\n[OK] VIDEO TUTORIAL COMPLETO GENERADO CON EXITO!")
