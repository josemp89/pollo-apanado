/**
 * printer.js - Módulo de Impresión Térmica para Tablet Android (POS)
 * Soporta Doble Vía de Impresión:
 *   Vía 1: RawBT Print Service (ESC/POS directo vía localhost:40213 o intent rawbt:)
 *   Vía 2: Impresión Nativa del Navegador (window.print() con CSS térmico 58mm/80mm)
 * Incluye apertura automática de cajón monedero por pulso ESC/POS (\x1b\x70\x00\x19\xfa)
 */

const DEFAULT_PRINTER_SETTINGS = {
  mode: 'auto',          // 'auto' (intenta RawBT y si falla usa navegador), 'rawbt', 'browser'
  paperWidth: '58mm',    // '58mm' (32 col) o '80mm' (42 col)
  autoPrint: false,      // Imprimir automáticamente al cobrar
  openDrawer: true,      // Abrir cajón monedero al cobrar en efectivo
  storeName: 'ASADERO POLLO APANADO',
  storeNit: 'NIT: 901.458.789-1',
  storePhone: 'Tel: 310 123 4567',
  storeAddress: 'Calle Principal # 10-20',
  footerMsg: '¡Gracias por su compra! Vuelva pronto.'
};

function getPrinterSettings() {
  try {
    const raw = localStorage.getItem('pos_printer_settings');
    if (raw) return { ...DEFAULT_PRINTER_SETTINGS, ...JSON.parse(raw) };
  } catch (e) {
    console.warn("Error leyendo printer settings:", e);
  }
  return { ...DEFAULT_PRINTER_SETTINGS };
}

function savePrinterSettings(newSettings) {
  try {
    const current = getPrinterSettings();
    const updated = { ...current, ...newSettings };
    localStorage.setItem('pos_printer_settings', JSON.stringify(updated));
    return updated;
  } catch (e) {
    console.error("Error guardando printer settings:", e);
    return null;
  }
}

// ==================== FORMATEADOR DE TICKET DE TEXTO ====================

function padLine(left, right, width) {
  const l = String(left || '');
  const r = String(right || '');
  const spaceNeeded = width - l.length - r.length;
  if (spaceNeeded <= 0) {
    return l.substring(0, width - r.length - 1) + ' ' + r;
  }
  return l + ' '.repeat(spaceNeeded) + r;
}

function centerText(text, width) {
  const t = String(text || '').trim();
  if (t.length >= width) return t;
  const leftPad = Math.floor((width - t.length) / 2);
  return ' '.repeat(leftPad) + t;
}

function formatCOPLocal(amount) {
  return '$ ' + Math.round(amount || 0).toLocaleString('es-CO');
}

/**
 * Genera el texto formateado plano para el rollo térmico
 */
function generateReceiptPlainText(saleData) {
  const settings = getPrinterSettings();
  const width = settings.paperWidth === '80mm' ? 42 : 32;
  const sep = '-'.repeat(width);
  const dblSep = '='.repeat(width);

  const lines = [];

  // Encabezado
  lines.push(centerText(settings.storeName, width));
  lines.push(centerText(settings.storeNit, width));
  if (settings.storeAddress) lines.push(centerText(settings.storeAddress, width));
  if (settings.storePhone) lines.push(centerText(settings.storePhone, width));
  lines.push(dblSep);

  // Datos de Factura
  const code = saleData.sale_code || ('VTA-' + (saleData.sale_id || '0000'));
  const fecha = saleData.time_str ? `${saleData.time_str}` : new Date().toLocaleTimeString();
  const fechaCompleta = new Date().toLocaleDateString('es-CO');

  lines.push(padLine(`Factura: ${code}`, fecha, width));
  lines.push(padLine(`Fecha: ${fechaCompleta}`, `Caja: Principal`, width));
  lines.push(sep);

  // Detalle de Ítems
  lines.push(padLine("CANT DESCRIPCION", "TOTAL", width));
  lines.push(sep);

  const items = saleData.items || [];
  items.forEach(it => {
    const qty = it.quantity || 1;
    const name = it.product_name || it.name || 'Producto';
    const subtotal = formatCOPLocal(it.subtotal || (it.unit_price * qty));
    
    // Línea principal
    const desc = `${qty}x ${name}`;
    lines.push(padLine(desc, subtotal, width));

    // Si tiene presa elegida (ej. Almuerzo Completo)
    if (it.chosen_presa) {
      const presaDesc = `  Presa: ${it.chosen_presa.toUpperCase()}`;
      lines.push(presaDesc);
    }
  });

  lines.push(sep);

  // Totales
  const totalStr = formatCOPLocal(saleData.total_amount);
  lines.push(padLine("TOTAL A PAGAR:", totalStr, width));

  // Forma de pago y cambio
  const method = (saleData.payment_method || 'efectivo').toUpperCase();
  lines.push(padLine("FORMA DE PAGO:", method, width));

  if ((saleData.payment_method || '').toLowerCase() === 'efectivo') {
    const recibido = formatCOPLocal(saleData.cash_received || saleData.total_amount);
    const cambio = formatCOPLocal(saleData.change_returned || 0);
    lines.push(padLine("EFECTIVO RECIBIDO:", recibido, width));
    lines.push(padLine("CAMBIO / DEVUELTA:", cambio, width));
  }

  lines.push(dblSep);
  lines.push(centerText(settings.footerMsg, width));
  lines.push(centerText("*** COPIA CLIENTE ***", width));
  lines.push("\n\n\n"); // Espacio para corte

  return lines.join("\n");
}

/**
 * Genera el HTML formateado para la previsualización y para window.print()
 */
function generateReceiptHTML(saleData) {
  const settings = getPrinterSettings();
  const code = saleData.sale_code || ('VTA-' + (saleData.sale_id || '0000'));
  const fecha = saleData.time_str || new Date().toLocaleTimeString();
  const fechaCompleta = new Date().toLocaleDateString('es-CO');
  const items = saleData.items || [];

  let itemsHtml = '';
  items.forEach(it => {
    const qty = it.quantity || 1;
    const name = it.product_name || it.name || 'Producto';
    const subtotal = formatCOPLocal(it.subtotal || (it.unit_price * qty));
    const presa = it.chosen_presa ? `<div style="font-size: 10px; color: #555; padding-left: 10px;">Presa: ${it.chosen_presa.toUpperCase()}</div>` : '';

    itemsHtml += `
      <div style="display: flex; justify-content: space-between; margin: 3px 0; font-size: 11px;">
        <span>${qty}x ${name}</span>
        <span style="font-weight: bold;">${subtotal}</span>
      </div>
      ${presa}
    `;
  });

  let cashDetailHtml = '';
  if ((saleData.payment_method || '').toLowerCase() === 'efectivo') {
    cashDetailHtml = `
      <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 2px;">
        <span>Recibido:</span>
        <span>${formatCOPLocal(saleData.cash_received || saleData.total_amount)}</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: bold; margin-top: 2px; border-top: 1px dashed #000; padding-top: 3px;">
        <span>CAMBIO:</span>
        <span style="font-size: 14px;">${formatCOPLocal(saleData.change_returned || 0)}</span>
      </div>
    `;
  }

  const paperWidth = settings.paperWidth === '80mm' ? '72mm' : '48mm';

  return `
    <div style="width: ${paperWidth}; margin: 0 auto; font-family: 'Courier New', Courier, monospace; color: #000; line-height: 1.25; padding: 4px;">
      <div style="text-align: center; font-weight: 900; font-size: 14px; margin-bottom: 2px;">${settings.storeName}</div>
      <div style="text-align: center; font-size: 10px;">${settings.storeNit}</div>
      ${settings.storeAddress ? `<div style="text-align: center; font-size: 10px;">${settings.storeAddress}</div>` : ''}
      ${settings.storePhone ? `<div style="text-align: center; font-size: 10px;">${settings.storePhone}</div>` : ''}
      
      <div style="border-top: 1px dashed #000; margin: 6px 0;"></div>

      <div style="display: flex; justify-content: space-between; font-size: 10px;">
        <span>Fac: <strong>${code}</strong></span>
        <span>${fecha}</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 10px;">
        <span>Fecha: ${fechaCompleta}</span>
        <span>Caja: 1</span>
      </div>

      <div style="border-top: 1px dashed #000; margin: 6px 0;"></div>

      <div style="display: flex; justify-content: space-between; font-size: 10px; font-weight: bold; border-bottom: 1px solid #000; padding-bottom: 2px;">
        <span>CANT PRODUCTO</span>
        <span>TOTAL</span>
      </div>

      <div style="margin: 4px 0;">
        ${itemsHtml}
      </div>

      <div style="border-top: 1px dashed #000; margin: 6px 0;"></div>

      <div style="display: flex; justify-content: space-between; font-size: 14px; font-weight: 900; margin: 4px 0;">
        <span>TOTAL:</span>
        <span>${formatCOPLocal(saleData.total_amount)}</span>
      </div>

      <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 2px;">
        <span>Método:</span>
        <span style="font-weight: bold;">${(saleData.payment_method || 'efectivo').toUpperCase()}</span>
      </div>

      ${cashDetailHtml}

      <div style="border-top: 1px dashed #000; margin: 8px 0 4px 0;"></div>
      <div style="text-align: center; font-size: 10px; font-style: italic;">${settings.footerMsg}</div>
      <div style="text-align: center; font-size: 9px; margin-top: 2px;">*** COMPROBANTE DE PAGO ***</div>
    </div>
  `;
}

// ==================== MÉTODOS DE IMPRESIÓN ====================

/**
 * Vía 1: Envío directo a RawBT en Android (Abre RawBT e imprime al instante)
 */
function printReceiptViaRawBT(saleData) {
  const plainText = generateReceiptPlainText(saleData);
  const settings = getPrinterSettings();

  const isCash = (saleData.payment_method || '').toLowerCase() === 'efectivo';
  const shouldKickDrawer = settings.openDrawer && isCash;
  const kickDrawerCmd = shouldKickDrawer ? "\x1b\x70\x00\x19\xfa" : "";
  const fullContent = kickDrawerCmd + plainText;

  try {
    // Protocolo oficial RawBT para Android:
    // rawbt:base64,<contenido_en_base64>
    const b64 = btoa(unescape(encodeURIComponent(fullContent)));
    window.location.href = "rawbt:base64," + b64;
    return true;
  } catch (err) {
    console.warn("Fallo al codificar en base64, usando URI encode:", err);
    window.location.href = "rawbt:data:text/plain;charset=utf-8," + encodeURIComponent(fullContent);
    return true;
  }
}

/**
 * Vía 2: Impresión Nativa del Navegador con CSS Térmico
 */
function printReceiptViaBrowser(saleData) {
  const printArea = document.getElementById('thermalReceiptPrintArea');
  if (printArea) {
    printArea.classList.remove('hidden');
    printArea.innerHTML = generateReceiptHTML(saleData);
  }

  // Intentar abrir ventana limpia dedicada (sin Tailwind ni layouts oscuros)
  try {
    const printWin = window.open('', '_blank', 'width=450,height=650');
    if (printWin) {
      printWin.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Ticket - ${saleData.sale_code || 'Venta'}</title>
          <style>
            @page { size: auto; margin: 0; }
            body { 
              margin: 0; 
              padding: 4px; 
              font-family: 'Courier New', Courier, monospace; 
              background: #fff; 
              color: #000; 
              -webkit-print-color-adjust: exact;
              print-color-adjust: exact;
            }
          </style>
        </head>
        <body>
          ${generateReceiptHTML(saleData)}
        </body>
        </html>
      `);
      printWin.document.close();
      printWin.focus();
      setTimeout(() => {
        printWin.print();
        setTimeout(() => { try { printWin.close(); } catch(e){} }, 2500);
      }, 400);
      return true;
    }
  } catch (e) {
    console.warn("window.open no disponible, usando window.print() en ventana principal:", e);
  }

  // Si window.open fue bloqueado, imprimir en la ventana actual
  window.print();
  setTimeout(() => {
    if (printArea) printArea.classList.add('hidden');
  }, 2000);
  return true;
}

/**
 * Ejecutor Principal: Doble Vía con Respaldo Automático
 */
function printReceipt(saleData, preferredMethod = null) {
  if (!saleData) return;
  const settings = getPrinterSettings();
  const method = preferredMethod || settings.mode;

  if (method === 'browser') {
    return printReceiptViaBrowser(saleData);
  }

  if (method === 'rawbt') {
    return printReceiptViaRawBT(saleData);
  }

  // En modo 'auto': dispara RawBT (el intent de Android lo captura de inmediato si RawBT está instalado)
  return printReceiptViaRawBT(saleData);
}

/**
 * Impresión de prueba desde ajustes
 */
async function printTestTicket() {
  const testSale = {
    sale_id: 9999,
    sale_code: 'TEST-0001',
    timestamp: new Date().toISOString(),
    time_str: new Date().toLocaleTimeString(),
    payment_method: 'efectivo',
    total_amount: 16000,
    cash_received: 20000,
    change_returned: 4000,
    items: [
      { product_name: 'Almuerzo Completo', quantity: 1, unit_price: 16000, subtotal: 16000, chosen_presa: 'pechuga' }
    ]
  };

  await printReceipt(testSale);
}

// ==================== MODAL DE VENTA EXITOSA Y TICKET ====================

let currentSuccessSaleData = null;

function showSaleSuccessModal(saleData) {
  currentSuccessSaleData = saleData;

  const modal = document.getElementById('modalSaleSuccess');
  if (!modal) return;

  // 1. Mostrar cambio / devuelta
  const isCash = (saleData.payment_method || '').toLowerCase() === 'efectivo';
  const cashBox = document.getElementById('modalSuccessCashBox');
  const nonCashBox = document.getElementById('modalSuccessNonCashBox');
  const changeEl = document.getElementById('modalSuccessChangeAmount');
  const receivedEl = document.getElementById('modalSuccessReceivedAmount');
  const totalEl = document.getElementById('modalSuccessTotalAmount');
  const methodBadge = document.getElementById('modalSuccessPaymentBadge');

  if (totalEl) totalEl.textContent = formatCOPLocal(saleData.total_amount);
  if (methodBadge) methodBadge.textContent = (saleData.payment_method || 'efectivo').toUpperCase();

  if (isCash) {
    if (cashBox) cashBox.classList.remove('hidden');
    if (nonCashBox) nonCashBox.classList.add('hidden');
    if (receivedEl) receivedEl.textContent = formatCOPLocal(saleData.cash_received || saleData.total_amount);
    if (changeEl) changeEl.textContent = formatCOPLocal(saleData.change_returned || 0);
  } else {
    if (cashBox) cashBox.classList.add('hidden');
    if (nonCashBox) nonCashBox.classList.remove('hidden');
    const nonCashText = document.getElementById('modalSuccessNonCashText');
    if (nonCashText) nonCashText.textContent = `Pago confirmado vía ${(saleData.payment_method || '').toUpperCase()}`;
  }

  // 2. Previsualizar el ticket térmico
  const preview = document.getElementById('modalSuccessReceiptPreview');
  if (preview) {
    preview.innerHTML = generateReceiptHTML(saleData);
  }

  modal.classList.remove('hidden');

  // 3. Auto-imprimir si está habilitado en ajustes
  const settings = getPrinterSettings();
  if (settings.autoPrint) {
    printReceipt(saleData);
  }
}

function closeSaleSuccessModal() {
  const modal = document.getElementById('modalSaleSuccess');
  if (modal) modal.classList.add('hidden');
  currentSuccessSaleData = null;
}

function printCurrentSuccessTicket(method = null) {
  if (currentSuccessSaleData) {
    if (method === 'rawbt') {
      printReceiptViaRawBT(currentSuccessSaleData);
    } else if (method === 'browser') {
      printReceiptViaBrowser(currentSuccessSaleData);
    } else {
      printReceipt(currentSuccessSaleData);
    }
  }
}

// ==================== MODAL DE AJUSTES DE IMPRESORA ====================

function openPrinterSettingsModal() {
  const modal = document.getElementById('modalPrinterSettings');
  if (!modal) return;

  const settings = getPrinterSettings();
  const modeSel = document.getElementById('printerSettingMode');
  const widthSel = document.getElementById('printerSettingWidth');
  const autoPrintChk = document.getElementById('printerSettingAutoPrint');
  const drawerChk = document.getElementById('printerSettingOpenDrawer');
  const nameInp = document.getElementById('printerSettingStoreName');
  const nitInp = document.getElementById('printerSettingStoreNit');
  const phoneInp = document.getElementById('printerSettingStorePhone');

  if (modeSel) modeSel.value = settings.mode;
  if (widthSel) widthSel.value = settings.paperWidth;
  if (autoPrintChk) autoPrintChk.checked = !!settings.autoPrint;
  if (drawerChk) drawerChk.checked = !!settings.openDrawer;
  if (nameInp) nameInp.value = settings.storeName;
  if (nitInp) nitInp.value = settings.storeNit;
  if (phoneInp) phoneInp.value = settings.storePhone;

  modal.classList.remove('hidden');
}

function closePrinterSettingsModal() {
  const modal = document.getElementById('modalPrinterSettings');
  if (modal) modal.classList.add('hidden');
}

function savePrinterSettingsFromForm(e) {
  if (e) e.preventDefault();

  const modeSel = document.getElementById('printerSettingMode');
  const widthSel = document.getElementById('printerSettingWidth');
  const autoPrintChk = document.getElementById('printerSettingAutoPrint');
  const drawerChk = document.getElementById('printerSettingOpenDrawer');
  const nameInp = document.getElementById('printerSettingStoreName');
  const nitInp = document.getElementById('printerSettingStoreNit');
  const phoneInp = document.getElementById('printerSettingStorePhone');

  const newSettings = {
    mode: modeSel ? modeSel.value : 'auto',
    paperWidth: widthSel ? widthSel.value : '58mm',
    autoPrint: autoPrintChk ? autoPrintChk.checked : false,
    openDrawer: drawerChk ? drawerChk.checked : true,
    storeName: nameInp ? nameInp.value.trim() : DEFAULT_PRINTER_SETTINGS.storeName,
    storeNit: nitInp ? nitInp.value.trim() : DEFAULT_PRINTER_SETTINGS.storeNit,
    storePhone: phoneInp ? phoneInp.value.trim() : DEFAULT_PRINTER_SETTINGS.storePhone
  };

  savePrinterSettings(newSettings);

  // Actualizar previsualización si el modal de éxito está abierto
  if (currentSuccessSaleData) {
    const preview = document.getElementById('modalSuccessReceiptPreview');
    if (preview) preview.innerHTML = generateReceiptHTML(currentSuccessSaleData);
  }

  closePrinterSettingsModal();
  alert("✅ Configuración de impresora guardada con éxito.");
}

// Atajos de teclado para agilidad en caja
document.addEventListener('keydown', (e) => {
  const successModal = document.getElementById('modalSaleSuccess');
  if (successModal && !successModal.classList.contains('hidden')) {
    if (e.key === 'Enter') {
      e.preventDefault();
      printCurrentSuccessTicket();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeSaleSuccessModal();
    }
  }
});
