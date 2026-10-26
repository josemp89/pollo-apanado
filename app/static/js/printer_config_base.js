/**
 * printer_config_base.js - Respaldo permanente y oficial de la configuración base de impresora
 * Configuración:
 *   - Nombre del Negocio: YO SOY DON POLLO
 *   - Centrado: Espaciado simétrico puro (offset: 0) probado y validado
 *   - Ancho: 58mm (32 col estándar) con delimitadores limpios
 *   - Apertura de cajón monedero: Inmediata en cobros en efectivo con disparo cuádruple universal (Pin 2 y Pin 5 a 24V 500ms)
 *   - Impresión automática: Activa (autoPrint: true)
 */

const BASE_OFFICIAL_PRINTER_SETTINGS = {
  mode: 'auto',
  paperWidth: '58mm',
  headerOffset: 0,
  autoPrint: true,
  openDrawer: true,
  storeName: 'YO SOY DON POLLO',
  storeNit: 'NIT: 901.458.789-1',
  storePhone: 'Tel: 310 123 4567',
  storeAddress: 'Calle Principal # 10-20',
  footerMsg: '¡Gracias por su compra!'
};
