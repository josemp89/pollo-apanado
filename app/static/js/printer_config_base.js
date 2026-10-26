/**
 * printer_config_base.js - Respaldo permanente y oficial de la configuración base de impresora
 * Configuración:
 *   - Nombre del Negocio: YO SOY DON POLLO
 *   - Centrado: Hardware ESC/POS nativo (\x1b\x61\x01) - 100% simétrico y sin cortes
 *   - Ancho: 58mm (32 col estándar) con protección CRLF (\r\n)
 *   - Apertura de cajón monedero: Inmediata en cobros en efectivo (\x1b\x70\x00\x19\x32\x1b\x70\x01\x19\x32)
 *   - Impresión automática: Activa (autoPrint: true)
 */

const BASE_OFFICIAL_PRINTER_SETTINGS = {
  mode: 'auto',
  paperWidth: '58mm',
  headerOffset: 'escpos',
  autoPrint: true,
  openDrawer: true,
  storeName: 'YO SOY DON POLLO',
  storeNit: 'NIT: 901.458.789-1',
  storePhone: 'Tel: 310 123 4567',
  storeAddress: 'Calle Principal # 10-20',
  footerMsg: '¡Gracias por su compra!'
};
