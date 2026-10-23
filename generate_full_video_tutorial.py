"""
Script integral para generar el VIDEO TUTORIAL OFICIAL HD con NARRACIÓN DE VOZ EN ESPAÑOL,
ANIMACIONES DINÁMICAS, CURSOR ILUSTRATIVO, SPOTS DE LUZ Y EXPLICACIONES DIDÁCTICAS PASO A PASO.
"""

import os
import sys
import time
import shutil
import asyncio
import subprocess
import threading
import imageio_ffmpeg
import edge_tts
from playwright.sync_api import sync_playwright

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
PORT = 8995
BASE_URL = f"http://127.0.0.1:{PORT}"

NARRATIONS = [
    {
        "id": "01_intro",
        "chapter": "🍗 BIENVENIDO A POLLO APANADO",
        "title": "Sistema Fácil de Inventarios y Ventas",
        "desc": "Aprenderás paso a paso cómo registrar proveedores, hacer ventas, controlar la cocina y cuadrar la caja sin pérdidas ni equivocaciones.",
        "text": "¡Hola! Bienvenidos al sistema de inventario y punto de venta de Pollo Apanado. En este tutorial aprenderás de forma súper fácil y paso a paso cómo registrar proveedores, hacer ventas en mostrador, controlar la cocina y cuadrar la caja al final del día sin errores ni pérdidas."
    },
    {
        "id": "02_proveedores",
        "chapter": "🚚 PASO 1: LLEGADA DE PROVEEDORES",
        "title": "¿Dónde ponemos los pollos y gaseosas que llegan?",
        "desc": "En el botón azul '+ Proveedores' arriba. Ingresamos cantidades y sube el inventario de bodega sin tocar el dinero de la caja.",
        "text": "Paso 1: ¿Dónde ingresamos los pollos y gaseosas que llegan de los proveedores? Muy fácil. En la barra superior, hacemos clic en el botón azul: Más Proveedores. Seleccionamos el proveedor, por ejemplo Pollos El Galpón, y escribimos las cantidades que llegaron: 20 pollos enteros y 24 gaseosas. Hacemos clic en Guardar Entrada. ¡Listo! El inventario de bodega sube automáticamente sin alterar el dinero de la caja."
    },
    {
        "id": "03_cocina",
        "chapter": "🍳 PASO 2: COCINA Y DESPIECE",
        "title": "Conversión de Pollos Enteros a Presas",
        "desc": "Don Santiago registra los pollos despresados. El sistema calcula 2 pechugas, 2 muslos y 2 alas por pollo + caldo para sancocho.",
        "text": "Paso 2: Cocina y Despiece. Hacemos clic en Cocina. Por la mañana, Don Santiago registra cuántos pollos va a despresar, por ejemplo diez pollos. El sistema calcula inmediatamente que saldrán 20 pechugas, 20 muslos, 20 alas y el caldo del día. Al confirmar, los pollos crudos pasan a estar listos para adobar y freír con sus tiempos exactos."
    },
    {
        "id": "04_mostrador",
        "chapter": "🛒 PASO 3: VENTAS EN MOSTRADOR",
        "title": "Tomar el Pedido del Cliente y Elegir Presa",
        "desc": "Tocamos Almuerzo Completo y elegimos la presa deseada. En el ticket vemos cómo se suma todo y podemos modificarlo con + y -.",
        "text": "Paso 3: Ventas en Mostrador. En la pestaña Mostrador, atender a un cliente es muy fácil. Tocamos un Almuerzo Completo. Se abre la ventana para elegir la presa, y seleccionamos Pechuga. En el ticket de la derecha aparece de inmediato el pedido. Si el cliente quiere agregar otra presa o cambiar de opinión, usamos los botones más y menos para ajustar la comanda en tiempo real."
    },
    {
        "id": "05_cobro",
        "chapter": "💵 PASO 4: COBRO EN EFECTIVO Y NEQUI",
        "title": "Cálculo Automático de Devuelta y Bancos",
        "desc": "Con billete de $50.000 el sistema muestra en grande la devuelta exacta de $34.000. Si paga por Nequi, el dinero va a bancos sin enredos.",
        "text": "Paso 4: Cobro y Cambio Exacto. Si el cliente paga en efectivo con un billete de 50.000 pesos, la pantalla muestra en verde gigante la devuelta exacta: 34.000 pesos, para que el cajero nunca se equivoque. Si el cliente paga por Nequi o Daviplata, tocamos Transferencia y anotamos el número de comprobante para que el dinero del banco no se mezcle con el efectivo."
    },
    {
        "id": "06_antifraude",
        "chapter": "🛡️ PASO 5: SEGURIDAD ANTIFRAUDE",
        "title": "Protección Contra Ventas Borradas o Anuladas",
        "desc": "Si alguien intenta borrar una venta para quedarse la plata, el sistema exige PIN del Dueño y guarda registro en auditoría.",
        "text": "Paso 5: Bloqueo Antifraude. Si alguien intenta anular una venta a escondidas para sacar el dinero y quedárselo, el sistema lo detiene pidiendo el PIN Secreto del Administrador. Si no tienen el PIN del dueño, la venta no se puede borrar y todo queda registrado en la auditoría con hora y fecha."
    },
    {
        "id": "07_caja",
        "chapter": "💰 PASO 6: CUADRE DE CAJA AL FINAL DEL DÍA",
        "title": "Fórmula Clara: Base + Efectivo - Gastos = En Cajón",
        "desc": "Verificación transparente: dinero físico contado, arqueo de transferencias y conteo de vitrina sin descuadres.",
        "text": "Paso 6: Cuadre de Caja al Final del Día. Al terminar el turno, vamos a la pestaña Caja. La cuenta es muy simple: Base con la que empezó el día, más el dinero en efectivo que entró por ventas, menos los gastos del día. El sistema nos dice exactamente cuántos billetes debe haber en el cajón. Contamos el dinero físico, las presas de la vitrina, ¡y la caja queda 100% cuadrada!"
    }
]

def get_audio_duration(filepath):
    cmd = [FFMPEG_EXE, "-i", filepath]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stderr.split("\n"):
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = parts.split(":")
            return float(h)*3600 + float(m)*60 + float(s)
    return 20.0

async def generate_all_narrations():
    print("[1/5] Generando pistas de narracion en espanol colombiano...")
    os.makedirs("tutorial_audio_temp", exist_ok=True)
    for item in NARRATIONS:
        path = os.path.join("tutorial_audio_temp", f"{item['id']}.mp3")
        if not os.path.exists(path) or os.path.getsize(path) < 1000:
            tts = edge_tts.Communicate(item["text"], "es-CO-GonzaloNeural")
            await tts.save(path)
        item["audio_path"] = path
        item["duration"] = get_audio_duration(path)
        print(f"  -> {item['id']}: {item['duration']:.2f}s")

def build_combined_soundtrack():
    print("[2/5] Concatenando banda sonora completa con pausas...")
    silence_path = os.path.join("tutorial_audio_temp", "pause.mp3")
    subprocess.run([FFMPEG_EXE, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.8", "-q:a", "9", silence_path], capture_output=True)

    concat_file = os.path.join("tutorial_audio_temp", "concat.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for item in NARRATIONS:
            clean_audio = os.path.abspath(item["audio_path"]).replace("\\", "/")
            clean_silence = os.path.abspath(silence_path).replace("\\", "/")
            f.write(f"file '{clean_audio}'\n")
            f.write(f"file '{clean_silence}'\n")

    full_audio = "full_tutorial_soundtrack.mp3"
    subprocess.run([FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c:a", "libmp3lame", "-b:a", "192k", full_audio], capture_output=True)
    total_audio_dur = get_audio_duration(full_audio)
    print(f"  -> Audio total generado: {total_audio_dur:.2f}s")
    return total_audio_dur

def start_temp_server():
    import uvicorn
    from app.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(2.0)
    return server

JS_TUTORIAL_HELPERS = """
window.__initTutorialOverlay = function() {
    if (document.getElementById('tutorialOverlayStyles')) return;
    const style = document.createElement('style');
    style.id = 'tutorialOverlayStyles';
    style.innerHTML = `
        #tutCursor {
            position: fixed;
            z-index: 1000000;
            pointer-events: none;
            transition: all 0.45s cubic-bezier(0.25, 1, 0.5, 1);
            font-size: 42px;
            filter: drop-shadow(0 6px 12px rgba(0,0,0,0.8));
            transform: translate(-10px, -10px);
            display: block;
        }
        #tutSpotlight {
            position: fixed;
            z-index: 999998;
            pointer-events: none;
            border: 4px solid #f59e0b;
            border-radius: 16px;
            box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.5), 0 0 35px #f59e0b;
            transition: all 0.4s cubic-bezier(0.25, 1, 0.5, 1);
            opacity: 0;
        }
        #tutCard {
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 999999;
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.98), rgba(30, 41, 59, 0.98));
            border: 2px solid #f59e0b;
            border-radius: 20px;
            padding: 14px 24px;
            max-width: 820px;
            width: 88%;
            box-shadow: 0 20px 45px rgba(0,0,0,0.9), 0 0 20px rgba(245, 158, 11, 0.25);
            color: white;
            font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            text-align: center;
            transition: all 0.3s ease;
        }
        #tutCard .chapter-badge {
            display: inline-block;
            font-size: 11px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid rgba(245, 158, 11, 0.4);
            color: #fbbf24;
            padding: 3px 12px;
            border-radius: 9999px;
            margin-bottom: 4px;
        }
        #tutCard .tut-title {
            font-size: 17px;
            font-weight: 800;
            color: #ffffff;
            margin-bottom: 4px;
        }
        #tutCard .tut-desc {
            font-size: 13px;
            color: #cbd5e1;
            line-height: 1.35;
        }
        .tut-ripple {
            position: fixed;
            z-index: 1000001;
            pointer-events: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            border: 3px solid #38bdf8;
            transform: translate(-50%, -50%);
            animation: tutRippleAnim 0.6s ease-out forwards;
        }
        @keyframes tutRippleAnim {
            0% { width: 10px; height: 10px; opacity: 1; }
            100% { width: 70px; height: 70px; opacity: 0; }
        }
    `;
    document.head.appendChild(style);

    const cur = document.createElement('div');
    cur.id = 'tutCursor';
    cur.innerHTML = '👆';
    document.body.appendChild(cur);

    const spot = document.createElement('div');
    spot.id = 'tutSpotlight';
    document.body.appendChild(spot);

    const card = document.createElement('div');
    card.id = 'tutCard';
    card.innerHTML = `
        <div class="chapter-badge" id="tutCardBadge">POLLO APANADO</div>
        <div class="tut-title" id="tutCardTitle">Bienvenido</div>
        <div class="tut-desc" id="tutCardDesc">Cargando guia interactiva...</div>
    `;
    document.body.appendChild(card);
};

window.__findElem = function(selector) {
    if (!selector) return null;
    if (typeof selector !== 'string') return selector;
    try {
        if (selector.includes(':has-text(')) {
            const parts = selector.split(':has-text(');
            const tag = parts[0] || '*';
            const txt = parts[1].replace(/["')]/g, '').trim();
            const elems = Array.from(document.querySelectorAll(tag));
            return elems.find(el => el.textContent && el.textContent.includes(txt)) || null;
        }
        return document.querySelector(selector);
    } catch(e) {
        console.warn('Selector warning:', selector, e);
        return null;
    }
};

window.__showChapter = function(chapter, title, desc) {
    window.__initTutorialOverlay();
    document.getElementById('tutCardBadge').innerText = chapter;
    document.getElementById('tutCardTitle').innerText = title;
    document.getElementById('tutCardDesc').innerText = desc;
};

window.__pointTo = function(selector) {
    window.__initTutorialOverlay();
    const el = window.__findElem(selector);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cur = document.getElementById('tutCursor');
    const spot = document.getElementById('tutSpotlight');

    const pad = 8;
    spot.style.left = (rect.left - pad) + 'px';
    spot.style.top = (rect.top - pad) + 'px';
    spot.style.width = (rect.width + pad * 2) + 'px';
    spot.style.height = (rect.height + pad * 2) + 'px';
    spot.style.opacity = '1';

    cur.style.left = (rect.left + rect.width / 2) + 'px';
    cur.style.top = (rect.top + rect.height / 2 + 10) + 'px';
};

window.__hideSpotlight = function() {
    const spot = document.getElementById('tutSpotlight');
    if (spot) spot.style.opacity = '0';
};

window.__simulateClick = function(selector) {
    const el = window.__findElem(selector);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;

    const rip = document.createElement('div');
    rip.className = 'tut-ripple';
    rip.style.left = x + 'px';
    rip.style.top = y + 'px';
    document.body.appendChild(rip);
    setTimeout(() => rip.remove(), 700);

    el.click();
};
"""

def record_visual_browser_walkthrough(output_raw_webm):
    print("[3/5] Grabando recorrido visual explicativo con Playwright (1280x720 HD)...")
    temp_dir = "temp_recording_dir"
    os.makedirs(temp_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=temp_dir,
            record_video_size={"width": 1280, "height": 720}
        )
        page = context.new_page()

        # ----------------------------------------------------
        # CAPÍTULO 1: INTRODUCCIÓN
        # ----------------------------------------------------
        item = NARRATIONS[0]
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.evaluate(JS_TUTORIAL_HELPERS)
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(2.0)
        page.evaluate("window.__pointTo('header')")
        time.sleep(max(1.0, item["duration"] - 2.5))

        # ----------------------------------------------------
        # CAPÍTULO 2: LLEGADA DE PROVEEDORES
        # ----------------------------------------------------
        item = NARRATIONS[1]
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(1.0)
        page.evaluate("window.__pointTo('#btnOpenSupplierEntry')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('#btnOpenSupplierEntry')")
        time.sleep(1.5)

        # Llenar datos proveedor
        page.evaluate("window.__pointTo('#supplierNameInput')")
        page.fill("#supplierNameInput", "Pollos Bucanero")
        time.sleep(1.5)

        page.evaluate("window.__pointTo('#supplierInvoiceInput')")
        page.fill("#supplierInvoiceInput", "REM-9412")
        time.sleep(1.5)

        page.evaluate("window.__pointTo('#supplierItemSelect')")
        page.select_option("#supplierItemSelect", "pollo_entero_crudo")
        time.sleep(1.5)

        page.evaluate("window.__pointTo('#supplierQuantityInput')")
        page.fill("#supplierQuantityInput", "20")
        time.sleep(1.5)

        page.evaluate("window.__pointTo('#supplierTotalCostInput')")
        page.fill("#supplierTotalCostInput", "240000")
        time.sleep(1.5)

        page.evaluate("window.__pointTo('#btnSubmitSupplierEntry')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('#btnSubmitSupplierEntry')")
        time.sleep(2.5)
        page.evaluate("window.closeSupplierEntryModal()")
        page.evaluate("window.__hideSpotlight()")
        time.sleep(max(1.0, item["duration"] - 18.0))

        # ----------------------------------------------------
        # CAPÍTULO 3: COCINA Y DESPIECE
        # ----------------------------------------------------
        item = NARRATIONS[2]
        page.goto(f"{BASE_URL}/cocina", wait_until="networkidle")
        page.evaluate(JS_TUTORIAL_HELPERS)
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(2.0)

        page.evaluate("window.__pointTo('#inputWholeChickens')")
        time.sleep(2.0)
        page.fill("#inputWholeChickens", "10")
        time.sleep(2.0)

        page.evaluate("window.__pointTo('#prevPechugas')")
        time.sleep(2.5)

        page.evaluate("window.__pointTo('#btnSubmitDespiece')")
        time.sleep(2.5)
        page.evaluate("window.__simulateClick('#btnSubmitDespiece')")
        time.sleep(2.0)

        page.evaluate("window.__pointTo('#btnStartFrituraBatch')")
        time.sleep(2.5)
        page.evaluate("window.__simulateClick('#btnStartFrituraBatch')")
        time.sleep(max(1.5, item["duration"] - 16.5))

        # ----------------------------------------------------
        # CAPÍTULO 4: VENTAS EN MOSTRADOR
        # ----------------------------------------------------
        item = NARRATIONS[3]
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.wait_for_selector("#productsGrid button", timeout=10000)
        page.evaluate(JS_TUTORIAL_HELPERS)
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(2.0)

        # Seleccionar Almuerzo Completo
        page.evaluate("window.__pointTo('[data-sku=\"ALM-COM\"]')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('[data-sku=\"ALM-COM\"]')")
        time.sleep(2.0)

        # Seleccionar Pechuga en el modal
        page.evaluate("window.__pointTo('#btn-presa-pechuga')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('#btn-presa-pechuga')")
        time.sleep(2.0)

        # Mostrar Ticket
        page.evaluate("window.__pointTo('#orderItemsList')")
        time.sleep(2.5)

        # Agregar presa sola
        page.evaluate("window.__pointTo('[data-sku=\"POL-CON\"]')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('[data-sku=\"POL-CON\"]')")
        time.sleep(2.0)

        # Usar steppers en ticket
        page.evaluate("window.__pointTo('.btn-cart-inc')")
        time.sleep(1.5)
        page.evaluate("window.__simulateClick('.btn-cart-inc')")
        time.sleep(max(1.0, item["duration"] - 17.0))

        # ----------------------------------------------------
        # CAPÍTULO 5: COBRO EFECTIVO Y NEQUI
        # ----------------------------------------------------
        item = NARRATIONS[4]
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(1.5)

        # Click Efectivo
        page.evaluate("window.__pointTo('#btnPayCash')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('#btnPayCash')")
        time.sleep(2.0)

        # Llenar billete de 50.000
        page.evaluate("window.__pointTo('#cashReceivedInput')")
        page.fill("#cashReceivedInput", "50000")
        page.evaluate("updateChangeCalculation()")
        time.sleep(2.5)

        # Destacar cambio en verde gigante
        page.evaluate("window.__pointTo('#cashChangeDisplay')")
        time.sleep(3.0)

        # Confirmar cobro
        page.evaluate("window.__pointTo('#btnConfirmCashPayment')")
        time.sleep(2.0)
        page.evaluate("window.__simulateClick('#btnConfirmCashPayment')")
        time.sleep(2.5)
        page.evaluate("window.__hideSpotlight()")
        time.sleep(max(1.0, item["duration"] - 17.0))

        # ----------------------------------------------------
        # CAPÍTULO 6: SEGURIDAD ANTIFRAUDE
        # ----------------------------------------------------
        item = NARRATIONS[5]
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(1.5)

        # Intentar anular última venta
        page.evaluate("window.__pointTo('#btnUndoLastSale')")
        time.sleep(2.5)
        page.evaluate("window.__simulateClick('#btnUndoLastSale')")
        time.sleep(2.5)

        # Destacar el PIN de Administrador de bloqueo
        page.evaluate("window.__pointTo('#adminPinModal .bg-slate-900')")
        time.sleep(4.5)

        # Cerrar modal
        page.evaluate("window.closeAdminPinModal()")
        time.sleep(max(1.0, item["duration"] - 12.0))

        # ----------------------------------------------------
        # CAPÍTULO 7: CUADRE DE CAJA AL FINAL DEL DÍA
        # ----------------------------------------------------
        item = NARRATIONS[6]
        page.goto(f"{BASE_URL}/caja", wait_until="networkidle")
        page.evaluate(JS_TUTORIAL_HELPERS)
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", item)
        time.sleep(2.0)

        # Destacar la barra de estado de caja
        page.evaluate("window.__pointTo('#shiftStatusBar')")
        time.sleep(3.5)

        # Abrir modal de arqueo o conteo
        page.evaluate("window.__pointTo('#btnCloseShift')")
        time.sleep(2.5)
        page.evaluate("window.__simulateClick('#btnCloseShift')")
        time.sleep(2.0)

        # Destacar la fórmula matemática de cuadre
        page.evaluate("window.__pointTo('#closeModalExpectedCash')")
        time.sleep(4.0)

        # Cerrar modal
        page.evaluate("window.closeModal('closeShiftModal')")
        time.sleep(max(1.5, item["duration"] - 16.0))

        # Outro final
        page.evaluate("(args) => window.__showChapter(args.chapter, args.title, args.desc)", {"chapter": "🎉 ¡SISTEMA OPERATIVO Y SEGURO!", "title": "Pollo Apanado - Todo Cuadrado", "desc": "Tu dinero y tu inventario protegidos al 100% cada día."})
        page.evaluate("window.__hideSpotlight()")
        time.sleep(3.5)

        # Guardar video
        video_path = page.video.path()
        context.close()
        browser.close()
        shutil.move(video_path, output_raw_webm)
        print(f"  -> Video raw guardado en: {output_raw_webm}")

def multiplex_audio_and_video(raw_webm, full_audio, output_mp4, output_static_mp4, output_static_webm):
    print("[4/5] Ensamblando video HD final con audio y subtitulos codificados...")
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", raw_webm,
        "-i", full_audio,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_mp4
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Error al codificar MP4:", res.stderr)
    else:
        print(f"  -> MP4 Principal generado: {output_mp4} ({os.path.getsize(output_mp4)/1024/1024:.2f} MB)")

    os.makedirs(os.path.dirname(output_static_mp4), exist_ok=True)
    shutil.copy2(output_mp4, output_static_mp4)

    print("[5/5] Generando version webm optimizada para streaming movil...")
    cmd_webm = [
        FFMPEG_EXE, "-y",
        "-i", output_mp4,
        "-c:v", "libvpx-vp9",
        "-b:v", "1200k",
        "-c:a", "libvorbis",
        "-b:a", "128k",
        output_static_webm
    ]
    subprocess.run(cmd_webm, capture_output=True, text=True)
    print(f"  -> WebM Estatico generado: {output_static_webm} ({os.path.getsize(output_static_webm)/1024/1024:.2f} MB)")

def main():
    print("==========================================================")
    print("   GENERADOR OFICIAL DE VIDEO TUTORIAL POLLO APANADO HD   ")
    print("==========================================================")
    asyncio.run(generate_all_narrations())
    build_combined_soundtrack()

    server = start_temp_server()
    raw_video = "temp_walkthrough.webm"
    record_visual_browser_walkthrough(raw_video)

    out_mp4 = "TUTORIAL_SISTEMA_POLLO_APANADO.mp4"
    static_mp4 = os.path.join("app", "static", "videos", "tutorial_pollo_apanado.mp4")
    static_webm = os.path.join("app", "static", "videos", "tutorial_pollo_apanado.webm")

    multiplex_audio_and_video(raw_video, "full_tutorial_soundtrack.mp3", out_mp4, static_mp4, static_webm)

    # Limpieza temporal
    if os.path.exists("temp_recording_dir"):
        shutil.rmtree("temp_recording_dir", ignore_errors=True)
    if os.path.exists("tutorial_audio_temp"):
        shutil.rmtree("tutorial_audio_temp", ignore_errors=True)
    if os.path.exists("full_tutorial_soundtrack.mp3"):
        os.remove("full_tutorial_soundtrack.mp3")
    if os.path.exists(raw_video):
        os.remove(raw_video)

    print("\n[OK] TUTORIAL GENERADO EXITOSAMENTE CON NARRACION COMPLETA!")

if __name__ == "__main__":
    main()
