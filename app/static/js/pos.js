// Estado Global del Punto de Venta
let allProducts = [];
let stockSummary = {};
let currentCategory = 'todos';
let cart = []; // { product, quantity, chosen_presa } - Para Llevar
let selectedTable = null; // null = Para Llevar; 1..5 = Mesas 1 a 5
let tablesState = []; // [{table_number: 1, status: 'libre', order: null}, ...]
let tableDraftCart = []; // Ítems nuevos para la mesa activa antes de enviar
let activeTableOrder = null; // Comanda guardada en backend de la mesa activa
let pendingPresaProduct = null;
let comboSelectedPresas = []; // Presas seleccionadas para combo dinámico (estilo Frisby)
let comboPersonalDrink = null; // Gaseosa seleccionada para Combo Personal (250ml)
let pendingDigitalMethod = null;
let lastSaleId = null;
let undoBannerTimeout = null;

const PRESA_MAP = [
  { name: 'Pechuga', key: 'pechuga_vitrina', btnId: 'btn-presa-pechuga', badgeId: 'stock-pechuga-badge', colorClass: 'text-blue-400' },
  { name: 'Muslo', key: 'muslo_vitrina', btnId: 'btn-presa-muslo', badgeId: 'stock-muslo-badge', colorClass: 'text-orange-400' },
  { name: 'Contramuslo', key: 'contramuslo_vitrina', btnId: 'btn-presa-contramuslo', badgeId: 'stock-contramuslo-badge', colorClass: 'text-amber-400' },
  { name: 'Ala', key: 'ala_vitrina', btnId: 'btn-presa-ala', badgeId: 'stock-ala-badge', colorClass: 'text-yellow-400' }
];

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function getActiveWorkingCart() {
  return selectedTable === null ? cart : tableDraftCart;
}

function getCartOrTableTotal() {
  if (selectedTable === null) {
    return cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
  } else {
    const savedTotal = (activeTableOrder && activeTableOrder.status === 'abierta') ? (activeTableOrder.total_amount || 0) : 0;
    const draftTotal = tableDraftCart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
    return savedTotal + draftTotal;
  }
}

// Inicialización al cargar la página
document.addEventListener('DOMContentLoaded', async () => {
  initClock();
  await Promise.all([loadProducts(), loadStockSummary(), loadTablesStatus()]);
  setInterval(() => {
    loadStockSummary();
    loadTablesStatus();
  }, 10000); // Refrescar stock y mesas cada 10s
});

// Reloj en tiempo real
function initClock() {
  const clockEl = document.getElementById('liveClock');
  const dateEl = document.getElementById('liveDate');
  const update = () => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString('es-CO', { hour12: true });
    dateEl.textContent = now.toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short' }).toUpperCase();
  };
  update();
  setInterval(update, 1000);
}

// Cargar catálogo de productos
async function loadProducts() {
  try {
    const res = await fetch('/api/pos/products');
    allProducts = await res.json();
    renderProducts();
  } catch (err) {
    console.error("Error al cargar productos:", err);
  }
}

// Cargar resumen de existencias en vitrina y nevera
async function loadStockSummary() {
  try {
    const res = await fetch('/api/pos/stock-summary');
    stockSummary = await res.json();
    const rawP = stockSummary['pechuga_nevera'] ? stockSummary['pechuga_nevera'].stock : 0;
    const rawC = stockSummary['contramuslo_nevera'] ? stockSummary['contramuslo_nevera'].stock : 0;
    const rawM = stockSummary['muslo_nevera'] ? stockSummary['muslo_nevera'].stock : 0;
    const rawA = stockSummary['ala_nevera'] ? stockSummary['ala_nevera'].stock : 0;
    const totalNeveraPresas = rawP + rawC + rawM + rawA;

    const bodegaEl = document.getElementById('bodegaRawChickensDisplay');
    if (bodegaEl) {
      if (totalNeveraPresas > 0) {
        bodegaEl.textContent = Math.floor(totalNeveraPresas);
      } else {
        const rawCount = stockSummary['pollo_entero_crudo'] ? stockSummary['pollo_entero_crudo'].stock : 0;
        bodegaEl.textContent = Math.floor(rawCount);
      }
    }
    const equivEl = document.getElementById('bodegaRawChickensEquivDisplay');
    if (equivEl) {
      const equivPollos = totalNeveraPresas > 0 ? (totalNeveraPresas / 8) : ((stockSummary['pollo_entero_crudo'] && stockSummary['pollo_entero_crudo'].stock) || 0);
      equivEl.textContent = Number.isInteger(equivPollos) ? equivPollos : equivPollos.toFixed(1);
    }
    const breakdownEl = document.getElementById('neveraPresasBreakdown');
    if (breakdownEl) {
      breakdownEl.textContent = `(${Math.floor(rawP)} P · ${Math.floor(rawC)} C · ${Math.floor(rawM)} M · ${Math.floor(rawA)} A)`;
    }
    updateStockBadgesInModal();
    renderProducts(); // Re-renderizar para actualizar badges de stock
  } catch (err) {
    console.error("Error al cargar stock:", err);
  }
}

// Filtrar por categorías
function filterCategory(eventOrCat, maybeCat = null) {
  let cat;
  let activeBtn = null;

  if (typeof eventOrCat === 'string') {
    cat = eventOrCat;
    if (maybeCat && (maybeCat.currentTarget || maybeCat.target)) {
      activeBtn = maybeCat.currentTarget || (maybeCat.target && maybeCat.target.closest ? maybeCat.target.closest('.cat-btn') : null);
    } else if (typeof window !== 'undefined' && window.event && window.event.currentTarget) {
      activeBtn = window.event.currentTarget;
    }
  } else if (eventOrCat && (eventOrCat.currentTarget || eventOrCat.target)) {
    cat = maybeCat;
    activeBtn = eventOrCat.currentTarget || (eventOrCat.target && eventOrCat.target.closest ? eventOrCat.target.closest('.cat-btn') : null);
  } else {
    cat = maybeCat || eventOrCat || 'todos';
  }

  currentCategory = cat || 'todos';

  document.querySelectorAll('.cat-btn').forEach(btn => {
    btn.classList.remove('bg-amber-500', 'text-slate-950', 'active');
    btn.classList.add('bg-slate-800', 'text-slate-300');
  });

  if (!activeBtn && typeof document !== 'undefined') {
    activeBtn = document.querySelector(`.cat-btn[data-category="${currentCategory}"]`) ||
                document.querySelector(`.cat-btn[onclick*="'${currentCategory}'"]`);
  }

  if (activeBtn && activeBtn.classList) {
    activeBtn.classList.remove('bg-slate-800', 'text-slate-300');
    activeBtn.classList.add('bg-amber-500', 'text-slate-950', 'active');
  }

  renderProducts();
}

// Formateador de moneda colombiana
function formatCOP(num) {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0
  }).format(num);
}

// Calculador universal de disponibilidad de stock
function getProductStockInfo(product, summary) {
  if (!summary || Object.keys(summary).length === 0) {
    return { availableStock: 999, isAvailable: true, badgeText: '', badgeClass: '' };
  }

  const getStock = (key) => (summary[key] && typeof summary[key].stock === 'number') ? summary[key].stock : 0;

  let stock = null;
  let label = '';
  let color = 'slate';

  // 1. Presas solas de vitrina
  if (product.sku === 'POL-PEC') {
    stock = getStock('pechuga_vitrina');
    label = 'Vitrina';
    color = 'blue';
  } else if (product.sku === 'POL-MUS') {
    stock = getStock('muslo_vitrina');
    label = 'Vitrina';
    color = 'orange';
  } else if (product.sku === 'POL-CON') {
    stock = getStock('contramuslo_vitrina');
    label = 'Vitrina';
    color = 'amber';
  } else if (product.sku === 'POL-ALA') {
    stock = getStock('ala_vitrina');
    label = 'Vitrina';
    color = 'yellow';
  }

  // 2. Combos de pollo (selección a la carta: 1/4 = 2 presas, 1/2 = 4 presas, Entero = 8 presas)
  else if (product.sku === 'POL-14') {
    const totalPresas = getStock('pechuga_vitrina') + getStock('muslo_vitrina') + getStock('contramuslo_vitrina') + getStock('ala_vitrina');
    const papas = getStock('papas_raciones');
    stock = Math.min(Math.floor(totalPresas / 2), papas);
    label = 'Combos';
    color = 'indigo';
  } else if (product.sku === 'POL-12') {
    const totalPresas = getStock('pechuga_vitrina') + getStock('muslo_vitrina') + getStock('contramuslo_vitrina') + getStock('ala_vitrina');
    const papas = getStock('papas_raciones');
    stock = Math.min(Math.floor(totalPresas / 4), papas);
    label = 'Combos';
    color = 'purple';
  } else if (product.sku === 'POL-ENT') {
    const totalPresas = getStock('pechuga_vitrina') + getStock('muslo_vitrina') + getStock('contramuslo_vitrina') + getStock('ala_vitrina');
    const papas = Math.floor(getStock('papas_raciones') / 2);
    stock = Math.min(Math.floor(totalPresas / 8), papas);
    label = 'Enteros';
    color = 'rose';
  } else if (product.sku === 'POL-PER') {
    const totalPresas = getStock('pechuga_vitrina') + getStock('muslo_vitrina') + getStock('contramuslo_vitrina') + getStock('ala_vitrina');
    const papas = getStock('papas_raciones');
    const sodas = getStock('GAS-MAN-250') + getStock('GAS-COL-250');
    stock = Math.min(totalPresas, papas, sodas);
    label = 'Combos';
    color = 'teal';
  }

  // 3. Almuerzo Completo
  else if (product.sku === 'ALM-COMP') {
    const totalPresas = getStock('pechuga_vitrina') + getStock('muslo_vitrina') + getStock('contramuslo_vitrina') + getStock('ala_vitrina');
    const caldo = getStock('caldo_raciones');
    const arroz = getStock('arroz_raciones');
    const frijol = getStock('frijoles_raciones');
    stock = Math.min(totalPresas, caldo, arroz, frijol);
    label = 'Almuerzos';
    color = 'emerald';
  }

  // 4. Porciones sueltas de cocina
  else if (product.sku === 'POR-CALD') {
    stock = getStock('caldo_raciones');
    label = 'Cocina';
    color = 'teal';
  } else if (product.sku === 'POR-FRIJ') {
    stock = getStock('frijoles_raciones');
    label = 'Cocina';
    color = 'amber';
  } else if (product.sku === 'POR-ARROZ') {
    stock = getStock('arroz_raciones');
    label = 'Cocina';
    color = 'cyan';
  } else if (product.sku === 'POR-PAPAS') {
    stock = getStock('papas_raciones');
    label = 'Cocina';
    color = 'yellow';
  } else if (product.sku === 'POR-AREP') {
    stock = getStock('arepas_unidades');
    label = 'Cocina';
    color = 'stone';
  }

  // 5. Gaseosas de nevera
  else if (product.category === 'gaseosas') {
    stock = getStock(product.sku);
    label = 'Nevera';
    color = 'sky';
  }

  if (stock === null) {
    return { availableStock: 999, isAvailable: true, badgeText: '', badgeClass: '' };
  }

  if (stock <= 0) {
    return {
      availableStock: 0,
      isAvailable: false,
      badgeText: '🚫 Agotado',
      badgeClass: 'bg-red-500/20 text-red-400 border border-red-500/40 font-bold'
    };
  }

  if (stock <= 2) {
    return {
      availableStock: stock,
      isAvailable: true,
      badgeText: `${label}: ${stock} (Bajo)`,
      badgeClass: 'bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold'
    };
  }

  return {
    availableStock: stock,
    isAvailable: true,
    badgeText: `${label}: ${stock}`,
    badgeClass: `bg-${color}-500/20 text-${color}-300 font-bold`
  };
}

// Selector visual de ícono de alto impacto por SKU
function getProductIcon(product) {
  switch (product.sku) {
    case 'POL-ENT': return '🍗👑';
    case 'POL-12': return '🍗🍗';
    case 'POL-14': return '🍗🍟';
    case 'POL-PEC': return '🍗';
    case 'POL-MUS': return '🍗';
    case 'POL-CON': return '🍗';
    case 'POL-ALA': return '🍗';
    case 'ALM-COMP': return '🍽️';
    case 'POR-PAPAS': return '🍟';
    case 'POR-AREP': return '🫓';
    case 'POR-FRIJ': return '🫘';
    case 'POR-CALD': return '🥣';
    case 'POR-ARROZ': return '🍚';
    // Bebidas Postobón Oficiales
    case 'GAS-TEA-DUR-500':
    case 'GAS-TEA-LIM-500':
    case 'GAS-HIT-TRO-500':
    case 'GAS-HIT-MAN-500':
    case 'GAS-HIT-MOR-500':
    case 'GAS-HIT-NP-500':
    case 'GAS-HIT-MAN-1L':
    case 'GAS-HIT-NP-1L': return '🧃';
    case 'GAS-H2O-LIM-600':
    case 'GAS-H2O-LTA-600':
    case 'GAS-H2O-MAR-600':
    case 'GAS-COL-250':
    case 'GAS-MAN-250':
    case 'GAS-COC-400':
    case 'GAS-ZER-400':
    case 'GAS-COL-400':
    case 'GAS-MAN-400':
    case 'GAS-QUA-400': return '🥤';
    case 'GAS-MAN-175L':
    case 'GAS-PEP-175L':
    case 'GAS-COL-15L':
    case 'GAS-MAN-15L':
    case 'GAS-COC-15L': return '🍾';
    default: return product.icon || '🍗';
  }
}

function getCategoryBadgeLabel(category) {
  switch (category) {
    case 'pollo': return 'Pollo';
    case 'almuerzos': return 'Almuerzo';
    case 'porciones': return 'Porción';
    case 'gaseosas': return 'Bebida';
    default: return category;
  }
}

// Renderizado de las tarjetas de productos
function renderProducts() {
  const grid = document.getElementById('productsGrid');
  if (!grid) return;
  grid.innerHTML = '';

  const filtered = currentCategory === 'todos' 
    ? allProducts 
    : allProducts.filter(p => p.category === currentCategory);

  filtered.forEach(p => {
    const stockInfo = getProductStockInfo(p, stockSummary);
    const card = document.createElement('button');
    card.dataset.sku = p.sku;
    const baseClasses = "touch-card p-3 sm:p-4 rounded-2xl border text-center flex flex-col items-center justify-between shadow-lg transition-all relative group overflow-hidden min-h-[195px] sm:min-h-[220px]";

    if (!stockInfo.isAvailable) {
      card.className = `${baseClasses} bg-slate-900/60 border-slate-800 opacity-50 cursor-not-allowed`;
      card.disabled = true;
      card.setAttribute('aria-disabled', 'true');
      card.onclick = (e) => {
        e.preventDefault();
        if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
        alert(`El producto "${p.name}" está agotado en inventario.`);
      };
    } else {
      card.className = `${baseClasses} bg-slate-800/85 hover:bg-slate-750 hover:border-amber-500/60 border-slate-700/80 active:border-amber-500 active:scale-98`;
      card.disabled = false;
      card.removeAttribute('aria-disabled');
      card.onclick = () => onProductClick(p);
    }

    let stockBadgeHtml = '';
    if (stockInfo.badgeText) {
      stockBadgeHtml = `<span class="text-[10px] px-2 py-0.5 rounded-full ${stockInfo.badgeClass} shadow-sm backdrop-blur-sm">${stockInfo.badgeText}</span>`;
    }

    const icon = getProductIcon(p);
    const catLabel = getCategoryBadgeLabel(p.category);

    card.innerHTML = `
      <div class="absolute top-2 left-2 text-[10px] uppercase font-bold tracking-wider text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded-md border border-slate-800">
        ${catLabel}
      </div>
      <div class="absolute top-2 right-2">
        ${stockBadgeHtml}
      </div>

      <div class="my-1.5 mt-3 flex items-center justify-center w-20 h-20 sm:w-24 sm:h-24 rounded-2xl bg-gradient-to-b from-slate-900/90 to-slate-950/90 border border-slate-700/60 shadow-inner group-hover:border-amber-500/50 group-hover:bg-amber-500/10 transition-all duration-200">
        <span class="text-5xl sm:text-6xl drop-shadow select-none transform group-hover:scale-110 transition-transform duration-200 ${!stockInfo.isAvailable ? 'grayscale opacity-60' : ''}">
          ${icon}
        </span>
      </div>

      <div class="w-full">
        <h4 class="font-black text-sm sm:text-base ${stockInfo.isAvailable ? 'text-slate-100 group-hover:text-amber-300' : 'text-slate-400 line-through'} transition-colors leading-tight line-clamp-2 min-h-[2.2rem] flex items-center justify-center px-1">
          ${p.name}
        </h4>
        <div class="mt-2 w-full py-1.5 px-2 rounded-xl bg-amber-500/15 border border-amber-500/40 text-amber-300 group-hover:bg-amber-500 group-hover:text-slate-950 font-black text-base sm:text-lg tabular-nums shadow-sm transition-all text-center">
          ${formatCOP(p.price)}
        </div>
      </div>
    `;

    grid.appendChild(card);
  });
}

// Helper: Determina cuántas presas requiere un producto (Almuerzo = 1, Combo Personal = 1, 1/4 Pollo = 2, 1/2 Pollo = 4, Entero = 8)
function getRequiredPresasCount(product) {
  if (!product) return 0;
  if (product.sku === 'ALM-COMP' || product.requires_presa_selection == 1) return 1;
  if (product.sku === 'POL-PER') return 1;
  if (product.sku === 'POL-14') return 2;
  if (product.sku === 'POL-12') return 4;
  if (product.sku === 'POL-ENT') return 8;
  return 0;
}

// Helper: Cuenta cuántas unidades de una presa específica están comprometidas en la comanda actual
function getReservedPresaCountInCart(presaName) {
  if (!presaName) return 0;
  const currentWorking = getActiveWorkingCart();
  if (!currentWorking || currentWorking.length === 0) return 0;
  const targetLower = presaName.toLowerCase();
  let count = 0;
  currentWorking.forEach(it => {
    // 1. Presa sola directa
    if (it.product && it.product.sku === getSkuForPresa(presaName)) {
      count += it.quantity;
      return;
    }
    // 2. Presa elegida en almuerzo o combo
    if (it.chosen_presa) {
      const tokens = String(it.chosen_presa).split(',');
      tokens.forEach(tok => {
        const m = tok.trim().match(/^(\d+)\s*x?\s*(.+)$/i);
        let multiplier = 1;
        let name = tok.trim().toLowerCase();
        if (m) {
          multiplier = parseInt(m[1], 10) || 1;
          name = m[2].trim().toLowerCase();
        }
        if (name.includes(targetLower)) {
          count += multiplier * it.quantity;
        }
      });
    }
  });
  return count;
}

// Clic en producto
function onProductClick(product) {
  const stockInfo = getProductStockInfo(product, stockSummary);
  if (!stockInfo.isAvailable || stockInfo.availableStock <= 0) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`El producto "${product.name}" está agotado en inventario.`);
    return;
  }

  // Vibración táctil si el dispositivo la soporta
  if (navigator.vibrate) navigator.vibrate(25);

  const requiredCount = getRequiredPresasCount(product);
  if (requiredCount > 0) {
    // Abrir modal de selección de presas (Almuerzo o Combos a la carta estilo Frisby)
    pendingPresaProduct = product;
    openPresaModal(product);
  } else {
    addToCart(product);
  }
}

// Modal de Selección de Presas
function openPresaModal(product = null) {
  if (product) pendingPresaProduct = product;
  if (!pendingPresaProduct) return;

  comboSelectedPresas = [];
  comboPersonalDrink = null;
  const reqCount = getRequiredPresasCount(pendingPresaProduct);

  const titleEl = document.getElementById('presaModalTitle');
  const subtitleEl = document.getElementById('presaModalSubtitle');
  const comboBarEl = document.getElementById('comboSelectionBar');
  const comboActionsEl = document.getElementById('comboActions');
  const drinkSectionEl = document.getElementById('comboPersonalDrinkSection');
  const choicesLabelEl = document.getElementById('presaChoicesLabel');

  if (pendingPresaProduct.sku === 'POL-PER') {
    if (titleEl) titleEl.textContent = '🍱 Combo Personal con Papas ($9.000)';
    if (subtitleEl) subtitleEl.textContent = '1 Presa de Pollo + Papas Francesa + Gaseosa 250ml';
    if (choicesLabelEl) choicesLabelEl.classList.remove('hidden');
    if (drinkSectionEl) drinkSectionEl.classList.remove('hidden');
    if (comboBarEl) comboBarEl.classList.add('hidden');
    if (comboActionsEl) comboActionsEl.classList.remove('hidden');

    updateDrinkBadgesInModal();
    const selDrinkBadge = document.getElementById('selectedDrinkBadge');
    if (selDrinkBadge) {
      selDrinkBadge.textContent = 'Sin seleccionar';
      selDrinkBadge.className = 'text-xs font-bold text-amber-400';
    }
    const confirmBtn = document.getElementById('btnConfirmComboSelection');
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-slate-800 text-slate-500 font-black text-sm border border-slate-700 cursor-not-allowed transition';
      confirmBtn.innerHTML = '<span>Elige 1 presa y 1 gaseosa</span>';
    }
  } else if (reqCount === 1) {
    if (titleEl) titleEl.textContent = '¿Qué Presa Lleva el Almuerzo?';
    if (subtitleEl) subtitleEl.textContent = 'Selecciona la presa para descontar exactamente del inventario';
    if (choicesLabelEl) choicesLabelEl.classList.add('hidden');
    if (drinkSectionEl) drinkSectionEl.classList.add('hidden');
    if (comboBarEl) comboBarEl.classList.add('hidden');
    if (comboActionsEl) comboActionsEl.classList.add('hidden');
  } else {
    if (titleEl) titleEl.textContent = `Elige las ${reqCount} Presas del Combo`;
    if (subtitleEl) subtitleEl.textContent = `${pendingPresaProduct.name} - Puedes combinar las presas a tu gusto`;
    if (choicesLabelEl) choicesLabelEl.classList.add('hidden');
    if (drinkSectionEl) drinkSectionEl.classList.add('hidden');
    if (comboBarEl) comboBarEl.classList.remove('hidden');
    if (comboActionsEl) comboActionsEl.classList.remove('hidden');
    renderComboSelectionUI();
  }

  updateStockBadgesInModal();

  const totalPresas = PRESA_MAP.reduce((sum, item) => {
    const s = stockSummary[item.key];
    const live = s ? Number(s.stock) : 0;
    const reserved = getReservedPresaCountInCart(item.name);
    return sum + Math.max(0, live - reserved);
  }, 0);

  if (totalPresas < reqCount) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`No hay suficientes presas en vitrina térmica (se requieren ${reqCount}, disponibles: ${totalPresas}).`);
    pendingPresaProduct = null;
    return;
  }

  document.getElementById('presaModal').classList.remove('hidden');
}

function updateDrinkBadgesInModal() {
  const drinks = [
    { sku: 'GAS-MAN-250', badgeId: 'stock-manzana250-badge', btnId: 'btn-drink-manzana', color: 'pink' },
    { sku: 'GAS-COL-250', badgeId: 'stock-colombiana250-badge', btnId: 'btn-drink-colombiana', color: 'red' }
  ];

  drinks.forEach(d => {
    const badgeEl = document.getElementById(d.badgeId);
    const btnEl = document.getElementById(d.btnId);
    if (!badgeEl || !btnEl) return;

    btnEl.classList.remove('border-pink-500', 'border-red-500', 'border-emerald-500', 'ring-2', 'ring-emerald-500');
    btnEl.classList.add('border-slate-700');

    const stockItem = stockSummary[d.sku];
    const liveStock = stockItem ? Number(stockItem.stock) : 0;
    const reservedInCart = cart.reduce((sum, it) => (it.product && it.product.sku === d.sku ? sum + it.quantity : sum), 0);
    const net = Math.max(0, liveStock - reservedInCart);

    if (net <= 0) {
      btnEl.disabled = true;
      btnEl.classList.add('opacity-50', 'cursor-not-allowed');
      badgeEl.textContent = '❌ Agotada';
      badgeEl.className = 'text-[10px] text-red-400 font-bold';
    } else {
      btnEl.disabled = false;
      btnEl.classList.remove('opacity-50', 'cursor-not-allowed');
      badgeEl.textContent = `Quedan ${net} frías`;
      badgeEl.className = `text-[10px] text-${d.color}-400 font-bold`;
    }
  });
}

function selectPersonalDrink(sku, name) {
  const stockItem = stockSummary[sku];
  const liveStock = stockItem ? Number(stockItem.stock) : 0;
  const reservedInCart = cart.reduce((sum, it) => (it.product && it.product.sku === sku ? sum + it.quantity : sum), 0);
  if (liveStock - reservedInCart <= 0) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`La gaseosa ${name} está agotada en la nevera.`);
    return;
  }

  if (navigator.vibrate) navigator.vibrate(25);
  comboPersonalDrink = { sku, name };

  const btnMan = document.getElementById('btn-drink-manzana');
  const btnCol = document.getElementById('btn-drink-colombiana');
  if (btnMan) {
    btnMan.classList.remove('ring-2', 'ring-emerald-500', 'border-pink-500');
    if (sku === 'GAS-MAN-250') btnMan.classList.add('ring-2', 'ring-emerald-500', 'border-pink-500');
  }
  if (btnCol) {
    btnCol.classList.remove('ring-2', 'ring-emerald-500', 'border-red-500');
    if (sku === 'GAS-COL-250') btnCol.classList.add('ring-2', 'ring-emerald-500', 'border-red-500');
  }

  const selDrinkBadge = document.getElementById('selectedDrinkBadge');
  if (selDrinkBadge) {
    selDrinkBadge.textContent = `✅ ${name}`;
    selDrinkBadge.className = 'text-xs font-black text-emerald-400';
  }

  checkPersonalComboReady();
}

function checkPersonalComboReady() {
  const confirmBtn = document.getElementById('btnConfirmComboSelection');
  if (!confirmBtn) return;

  const hasPresa = comboSelectedPresas.length > 0;
  const hasDrink = comboPersonalDrink !== null;

  if (hasPresa && hasDrink) {
    confirmBtn.disabled = false;
    confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-black text-sm shadow-lg shadow-emerald-600/30 active:scale-95 transition cursor-pointer flex items-center justify-center gap-1.5';
    confirmBtn.innerHTML = `<span>✅ Agregar Combo Personal al Pedido</span>`;
  } else if (!hasPresa) {
    confirmBtn.disabled = true;
    confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-slate-800 text-slate-500 font-black text-sm border border-slate-700 cursor-not-allowed transition';
    confirmBtn.innerHTML = '<span>Falta elegir la Presa</span>';
  } else {
    confirmBtn.disabled = true;
    confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-slate-800 text-slate-500 font-black text-sm border border-slate-700 cursor-not-allowed transition';
    confirmBtn.innerHTML = '<span>Falta elegir la Gaseosa 250ml</span>';
  }
}

function closePresaModal() {
  document.getElementById('presaModal').classList.add('hidden');
  pendingPresaProduct = null;
  comboSelectedPresas = [];
  comboPersonalDrink = null;
  ['pechuga', 'muslo', 'contramuslo', 'ala'].forEach(k => {
    const b = document.getElementById(`badge-count-${k}`);
    if (b) {
      b.classList.add('hidden');
      b.textContent = '0';
    }
    const btn = document.getElementById(`btn-presa-${k}`);
    if (btn) {
      btn.classList.remove('ring-2', 'ring-emerald-500', 'border-emerald-500');
    }
  });

  const btnMan = document.getElementById('btn-drink-manzana');
  const btnCol = document.getElementById('btn-drink-colombiana');
  if (btnMan) btnMan.classList.remove('ring-2', 'ring-emerald-500', 'border-pink-500');
  if (btnCol) btnCol.classList.remove('ring-2', 'ring-emerald-500', 'border-red-500');
}

function updateStockBadgesInModal() {
  PRESA_MAP.forEach(item => {
    const badgeEl = document.getElementById(item.badgeId);
    const btnEl = document.getElementById(item.btnId) || badgeEl?.closest('button');
    if (!badgeEl || !btnEl) return;

    btnEl.classList.remove('ring-2', 'ring-emerald-500', 'border-emerald-500');

    const stockItem = stockSummary[item.key];
    const liveStock = stockItem ? Number(stockItem.stock) : 0;
    const reserved = getReservedPresaCountInCart(item.name);
    const netAvailable = Math.max(0, liveStock - reserved);

    if (netAvailable <= 0) {
      btnEl.disabled = true;
      btnEl.setAttribute('aria-disabled', 'true');
      btnEl.classList.add('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
      btnEl.classList.remove('active:scale-95');

      badgeEl.textContent = '❌ Agotado (0 listas)';
      badgeEl.className = 'text-[11px] text-red-400 font-bold';
    } else {
      btnEl.disabled = false;
      btnEl.removeAttribute('aria-disabled');
      btnEl.classList.remove('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
      btnEl.classList.add('active:scale-95');

      badgeEl.textContent = `Quedan ${netAvailable} listas`;
      badgeEl.className = `text-[11px] ${item.colorClass} font-bold`;
    }
  });
}

function getSkuForPresa(presa) {
  const map = { 'Pechuga': 'POL-PEC', 'Muslo': 'POL-MUS', 'Contramuslo': 'POL-CON', 'Ala': 'POL-ALA' };
  return map[presa] || null;
}

// Clic en presa (compatible para Almuerzo Completo, Combo Personal y Combos estilo Frisby)
function handlePresaClick(presa) {
  if (!presa || !pendingPresaProduct) {
    closePresaModal();
    return;
  }

  // 1. Caso Combo Personal (1 presa + 1 gaseosa 250ml)
  if (pendingPresaProduct.sku === 'POL-PER') {
    const presaKey = `${presa.trim().toLowerCase()}_vitrina`;
    const currentStock = (stockSummary[presaKey] && typeof stockSummary[presaKey].stock === 'number')
      ? stockSummary[presaKey].stock
      : 0;
    const reservedInCart = getReservedPresaCountInCart(presa);
    if (reservedInCart >= currentStock) {
      if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
      alert(`Solo quedan ${currentStock} unidad(es) de ${presa} disponibles en vitrina.`);
      return;
    }

    if (navigator.vibrate) navigator.vibrate(25);
    comboSelectedPresas = [presa];

    PRESA_MAP.forEach(item => {
      const btn = document.getElementById(item.btnId);
      if (btn) {
        btn.classList.remove('ring-2', 'ring-emerald-500', 'border-emerald-500');
        if (item.name === presa) {
          btn.classList.add('ring-2', 'ring-emerald-500', 'border-emerald-500');
        }
      }
    });

    checkPersonalComboReady();
    return;
  }

  const reqCount = getRequiredPresasCount(pendingPresaProduct);
  if (reqCount <= 1) {
    confirmPresaChoice(presa);
    return;
  }

  // Combos de múltiples presas (1/4, 1/2, Entero)
  if (comboSelectedPresas.length >= reqCount) {
    if (navigator.vibrate) navigator.vibrate([80, 40, 80]);
    alert(`Ya has seleccionado las ${reqCount} presas requeridas. Presiona "Agregar al Pedido" o toca una presa arriba para quitarla.`);
    return;
  }

  const presaKey = `${presa.trim().toLowerCase()}_vitrina`;
  const currentStock = (stockSummary[presaKey] && typeof stockSummary[presaKey].stock === 'number')
    ? stockSummary[presaKey].stock
    : 0;

  const reservedInCart = getReservedPresaCountInCart(presa);
  const currentlySelectedInModal = comboSelectedPresas.filter(p => p.toLowerCase() === presa.toLowerCase()).length;

  if (reservedInCart + currentlySelectedInModal >= currentStock) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`Solo quedan ${currentStock} unidad(es) de ${presa} disponibles en vitrina.`);
    return;
  }

  if (navigator.vibrate) navigator.vibrate(25);
  comboSelectedPresas.push(presa);
  renderComboSelectionUI();
}

function renderComboSelectionUI() {
  if (!pendingPresaProduct) return;
  const reqCount = getRequiredPresasCount(pendingPresaProduct);

  // 1. Contador badge
  const counterEl = document.getElementById('comboCounterBadge');
  if (counterEl) {
    counterEl.textContent = `${comboSelectedPresas.length} / ${reqCount} presas`;
    if (comboSelectedPresas.length === reqCount) {
      counterEl.className = 'text-xs font-black px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 animate-pulse';
    } else {
      counterEl.className = 'text-xs font-black px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/40';
    }
  }

  // 2. Badges numéricos sobre botones de presa
  const counts = { pechuga: 0, muslo: 0, contramuslo: 0, ala: 0 };
  comboSelectedPresas.forEach(p => {
    const k = p.toLowerCase();
    if (counts[k] !== undefined) counts[k]++;
  });

  ['pechuga', 'muslo', 'contramuslo', 'ala'].forEach(k => {
    const badge = document.getElementById(`badge-count-${k}`);
    if (badge) {
      if (counts[k] > 0) {
        badge.textContent = counts[k];
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
        badge.textContent = '0';
      }
    }
  });

  // 3. Chips interactivos de presas seleccionadas
  const chipsContainer = document.getElementById('comboChipsContainer');
  if (chipsContainer) {
    if (comboSelectedPresas.length === 0) {
      chipsContainer.innerHTML = '<span class="text-[11px] text-slate-500 italic">Toca las presas abajo para agregarlas...</span>';
    } else {
      chipsContainer.innerHTML = comboSelectedPresas.map((presa, idx) => `
        <button type="button" onclick="removeComboPresaAtIndex(${idx})" class="group inline-flex items-center gap-1.5 bg-amber-500/20 hover:bg-red-500/25 border border-amber-500/40 hover:border-red-500/50 text-amber-300 hover:text-red-300 px-2.5 py-1 rounded-lg text-xs font-bold transition-all shadow-sm active:scale-95" title="Toca para quitar esta presa">
          <span>🍗 ${presa}</span>
          <span class="text-xs group-hover:rotate-90 transition-transform">&times;</span>
        </button>
      `).join('');
    }
  }

  // 4. Botón de confirmación
  const confirmBtn = document.getElementById('btnConfirmComboSelection');
  if (confirmBtn) {
    if (comboSelectedPresas.length === reqCount) {
      confirmBtn.disabled = false;
      confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-black text-sm shadow-lg shadow-emerald-600/30 active:scale-95 transition cursor-pointer flex items-center justify-center gap-1.5';
      confirmBtn.innerHTML = `<span>✅ Agregar Combo al Pedido</span>`;
    } else {
      confirmBtn.disabled = true;
      confirmBtn.className = 'flex-[2] py-2.5 rounded-xl bg-slate-800 text-slate-500 font-black text-sm border border-slate-700 cursor-not-allowed transition';
      const remaining = reqCount - comboSelectedPresas.length;
      confirmBtn.innerHTML = `<span>Falta${remaining > 1 ? 'n' : ''} ${remaining} presa${remaining > 1 ? 's' : ''}</span>`;
    }
  }
}

function removeComboPresaAtIndex(idx) {
  if (idx >= 0 && idx < comboSelectedPresas.length) {
    if (navigator.vibrate) navigator.vibrate(20);
    comboSelectedPresas.splice(idx, 1);
    renderComboSelectionUI();
  }
}

function resetComboSelection() {
  if (navigator.vibrate) navigator.vibrate(25);
  comboSelectedPresas = [];
  comboPersonalDrink = null;

  if (pendingPresaProduct && pendingPresaProduct.sku === 'POL-PER') {
    PRESA_MAP.forEach(item => {
      const btn = document.getElementById(item.btnId);
      if (btn) btn.classList.remove('ring-2', 'ring-emerald-500', 'border-emerald-500');
    });
    const btnMan = document.getElementById('btn-drink-manzana');
    const btnCol = document.getElementById('btn-drink-colombiana');
    if (btnMan) btnMan.classList.remove('ring-2', 'ring-emerald-500', 'border-pink-500');
    if (btnCol) btnCol.classList.remove('ring-2', 'ring-emerald-500', 'border-red-500');
    const selDrinkBadge = document.getElementById('selectedDrinkBadge');
    if (selDrinkBadge) {
      selDrinkBadge.textContent = 'Sin seleccionar';
      selDrinkBadge.className = 'text-xs font-bold text-amber-400';
    }
    checkPersonalComboReady();
  } else {
    renderComboSelectionUI();
  }
}

function formatPresasSummary(presasList) {
  if (!presasList || presasList.length === 0) return '';
  const counts = {};
  presasList.forEach(p => {
    counts[p] = (counts[p] || 0) + 1;
  });

  const parts = [];
  const order = ['Pechuga', 'Muslo', 'Contramuslo', 'Ala'];
  order.forEach(p => {
    if (counts[p]) {
      const c = counts[p];
      if (c === 1) {
        parts.push(`1 ${p}`);
      } else {
        const plural = p === 'Contramuslo' ? 'Contramuslos' : `${p}s`;
        parts.push(`${c} ${plural}`);
      }
    }
  });
  return parts.join(', ');
}

function confirmComboSelection() {
  if (!pendingPresaProduct) return;

  // Manejo de Combo Personal (1 presa + 1 gaseosa 250ml)
  if (pendingPresaProduct.sku === 'POL-PER') {
    if (comboSelectedPresas.length === 0) {
      alert("Por favor selecciona la presa de pollo.");
      return;
    }
    if (!comboPersonalDrink) {
      alert("Por favor selecciona la gaseosa de 250ml (Manzana o Colombiana).");
      return;
    }
    const formattedStr = `${comboSelectedPresas[0]} | ${comboPersonalDrink.name}`;
    if (navigator.vibrate) navigator.vibrate(30);
    addToCart(pendingPresaProduct, formattedStr);
    closePresaModal();
    return;
  }

  const reqCount = getRequiredPresasCount(pendingPresaProduct);
  if (comboSelectedPresas.length !== reqCount) {
    alert(`Debes seleccionar exactamente ${reqCount} presas.`);
    return;
  }

  const formattedStr = formatPresasSummary(comboSelectedPresas);
  if (navigator.vibrate) navigator.vibrate(30);
  addToCart(pendingPresaProduct, formattedStr);
  closePresaModal();
}

// Confirmación para productos de 1 presa directa (Almuerzo Completo)
function confirmPresaChoice(presa) {
  if (!presa || !pendingPresaProduct) {
    closePresaModal();
    return;
  }

  const presaKey = `${presa.trim().toLowerCase()}_vitrina`;
  const currentStock = (stockSummary[presaKey] && typeof stockSummary[presaKey].stock === 'number')
    ? stockSummary[presaKey].stock
    : 0;

  // Guard defensivo: rechazar presa agotada
  if (currentStock <= 0) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`La presa seleccionada (${presa}) se encuentra agotada en vitrina térmica. Por favor seleccione otra presa.`);
    updateStockBadgesInModal();
    return;
  }

  // Comprobar si ya se agregaron a la comanda todas las presas disponibles
  const reservedInCart = getReservedPresaCountInCart(presa);
  if (reservedInCart >= currentStock) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`Solo quedan ${currentStock} unidad(es) de ${presa} en vitrina, y ya están agregadas a la comanda.`);
    return;
  }

  if (navigator.vibrate) navigator.vibrate(30);
  addToCart(pendingPresaProduct, presa);
  closePresaModal();
}

// ==================== GESTIÓN DE MESAS Y COMANDAS ====================

// Cargar estado de las 5 mesas desde el servidor
async function loadTablesStatus() {
  try {
    const res = await fetch('/api/pos/tables');
    if (!res.ok) return;
    tablesState = await res.json();

    tablesState.forEach(t => {
      const badge = document.getElementById(`tab-badge-${t.table_number}`);
      const tab = document.getElementById(`tab-table-${t.table_number}`);
      if (!badge) return;

      if (t.status === 'ocupada' && t.order) {
        const kValue = Math.round(t.order.total_amount / 1000);
        badge.textContent = `$${kValue}K`;
        badge.className = 'text-[8px] text-amber-300 font-black leading-tight mt-0.5';
        if (tab && selectedTable !== t.table_number) {
          tab.classList.add('border-amber-500/60');
        }
      } else {
        badge.textContent = 'Libre';
        badge.className = 'text-[8px] text-emerald-400 font-bold leading-tight mt-0.5';
        if (tab && selectedTable !== t.table_number) {
          tab.classList.remove('border-amber-500/60');
        }
      }
    });

    if (selectedTable !== null) {
      const curr = tablesState.find(t => t.table_number === selectedTable);
      activeTableOrder = curr ? curr.order : null;
    }
  } catch (err) {
    console.error("Error al cargar estado de mesas:", err);
  }
}

// Cambiar destino de pedido (Llevar o Mesas 1 a 5)
async function selectTableDestination(tableNum) {
  selectedTable = tableNum;

  // Actualizar estilos de las pestañas
  const tabs = document.querySelectorAll('.table-tab');
  tabs.forEach(tab => {
    tab.classList.remove('bg-amber-500', 'text-slate-950', 'border-amber-400', 'shadow');
    tab.classList.add('bg-slate-800', 'text-slate-300', 'border-slate-700');
  });

  const activeTab = tableNum === null ? document.getElementById('tab-takeout') : document.getElementById(`tab-table-${tableNum}`);
  if (activeTab) {
    activeTab.classList.remove('bg-slate-800', 'text-slate-300', 'border-slate-700');
    activeTab.classList.add('bg-amber-500', 'text-slate-950', 'border-amber-400', 'shadow');
  }

  const labelEl = document.getElementById('activeDestinationLabel');
  if (labelEl) {
    if (tableNum === null) {
      labelEl.textContent = '🛍️ Para Llevar';
      labelEl.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30';
    } else {
      labelEl.textContent = `🪑 Mesa ${tableNum}`;
      labelEl.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30';
    }
  }

  if (tableNum !== null) {
    try {
      const res = await fetch(`/api/pos/tables/${tableNum}`);
      if (res.ok) {
        const data = await res.json();
        activeTableOrder = data.order || null;
      }
    } catch (err) {
      console.error("Error al obtener detalle de mesa:", err);
    }
  } else {
    activeTableOrder = null;
  }

  renderCart();
}

// Guardar y enviar adiciones a la comanda abierta de la mesa activa
async function saveItemsToActiveTable(showAlert = true) {
  if (selectedTable === null) return false;
  if (tableDraftCart.length === 0) {
    if (showAlert) alert("No hay productos nuevos para enviar a la mesa.");
    return false;
  }

  const payload = {
    items: tableDraftCart.map(it => ({
      product_id: it.product.id,
      quantity: it.quantity,
      chosen_presa: it.chosen_presa
    }))
  };

  try {
    const res = await fetch(`/api/pos/tables/${selectedTable}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error al adicionar productos a la mesa");

    if (navigator.vibrate) navigator.vibrate([30, 40, 30]);
    tableDraftCart = [];
    activeTableOrder = data.order;
    await Promise.all([loadTablesStatus(), loadStockSummary()]);
    renderCart();

    const btn = document.getElementById('btnSaveToTable');
    if (btn && showAlert) {
      const originalText = btn.innerHTML;
      btn.innerHTML = '<span>✅ ¡Enviado a Mesa con Éxito!</span>';
      btn.classList.add('bg-emerald-600', 'text-white');
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.classList.remove('bg-emerald-600', 'text-white');
      }, 1400);
    }
    return true;
  } catch (err) {
    alert("Error al enviar a mesa: " + err.message);
    return false;
  }
}

// Cancelar comanda activa de la mesa activa y restaurar inventario
async function cancelActiveTable() {
  if (selectedTable === null) return;
  if (!activeTableOrder) {
    tableDraftCart = [];
    renderCart();
    return;
  }

  const ok = confirm(`¿Estás seguro de cancelar la comanda de la Mesa ${selectedTable}?\n\nSe restaurarán ${activeTableOrder.items_count} productos a vitrina/nevera y la mesa quedará Libre.`);
  if (!ok) return;

  try {
    const res = await fetch(`/api/pos/tables/${selectedTable}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: "Cancelación manual desde mostrador" })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error al cancelar la mesa");

    if (navigator.vibrate) navigator.vibrate(50);
    tableDraftCart = [];
    activeTableOrder = null;
    await Promise.all([loadTablesStatus(), loadStockSummary()]);
    renderCart();
    alert(`Mesa ${selectedTable} cancelada con éxito. Stock restaurado a vitrina y nevera.`);
  } catch (err) {
    alert("Error al cancelar orden de mesa: " + err.message);
  }
}

function handleClearOrCancel() {
  if (selectedTable === null) {
    clearCart();
  } else {
    if (tableDraftCart.length > 0) {
      tableDraftCart = [];
      renderCart();
    } else if (activeTableOrder) {
      cancelActiveTable();
    }
  }
}

// Exponer funciones en window para invocación desde HTML onclick
window.handlePresaClick = handlePresaClick;
window.selectPersonalDrink = selectPersonalDrink;
window.removeComboPresaAtIndex = removeComboPresaAtIndex;
window.resetComboSelection = resetComboSelection;
window.confirmComboSelection = confirmComboSelection;
window.confirmPresaChoice = confirmPresaChoice;
window.closePresaModal = closePresaModal;
window.selectTableDestination = selectTableDestination;
window.saveItemsToActiveTable = saveItemsToActiveTable;
window.cancelActiveTable = cancelActiveTable;
window.handleClearOrCancel = handleClearOrCancel;
window.loadTablesStatus = loadTablesStatus;

// Agregar al carrito / comanda
function addToCart(product, chosen_presa = null) {
  const targetCart = getActiveWorkingCart();
  const existing = targetCart.find(it => it.product.id === product.id && it.chosen_presa === chosen_presa);
  if (existing) {
    existing.quantity++;
  } else {
    targetCart.push({
      product: product,
      quantity: 1,
      chosen_presa: chosen_presa
    });
  }
  renderCart();

  // Pulso de confirmación visual en la barra móvil
  const mobileBar = document.getElementById('mobileCartBar');
  if (mobileBar) {
    mobileBar.classList.add('bg-slate-800', 'border-amber-500');
    setTimeout(() => {
      mobileBar.classList.remove('bg-slate-800', 'border-amber-500');
    }, 250);
  }
}

// Control del cajón / ticket en dispositivos móviles
function toggleMobileCart(open) {
  const aside = document.getElementById('cartAside');
  if (!aside) return;
  if (open) {
    aside.classList.remove('translate-y-full');
    aside.classList.add('translate-y-0');
  } else {
    aside.classList.add('translate-y-full');
    aside.classList.remove('translate-y-0');
  }
}
window.toggleMobileCart = toggleMobileCart;

// Modificar cantidades en comanda
function updateQuantity(idx, newQty) {
  const targetCart = getActiveWorkingCart();
  if (idx < 0 || idx >= targetCart.length || !targetCart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  const qty = Number(newQty);
  if (isNaN(qty) || qty <= 0) {
    targetCart.splice(idx, 1);
  } else {
    targetCart[idx].quantity = Math.floor(qty);
  }
  renderCart();
}

function incrementItem(idx) {
  const targetCart = getActiveWorkingCart();
  if (idx < 0 || idx >= targetCart.length || !targetCart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  targetCart[idx].quantity++;
  renderCart();
}

function decrementItem(idx) {
  const targetCart = getActiveWorkingCart();
  if (idx < 0 || idx >= targetCart.length || !targetCart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  if (targetCart[idx].quantity > 1) {
    targetCart[idx].quantity--;
  } else {
    targetCart.splice(idx, 1);
  }
  renderCart();
}

function removeItem(idx) {
  const targetCart = getActiveWorkingCart();
  if (idx < 0 || idx >= targetCart.length || !targetCart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(35);
  targetCart.splice(idx, 1);
  renderCart();
}

// Alias para compatibilidad de interfaz
function removeFromCart(idx) {
  removeItem(idx);
}

function clearCart() {
  if (navigator.vibrate) navigator.vibrate(50);
  if (selectedTable === null) {
    cart = [];
  } else {
    tableDraftCart = [];
  }
  renderCart();
}

// Renderizado reactivo de la comanda
function renderCart() {
  const listEl = document.getElementById('cartItemsList');
  const emptyEl = document.getElementById('cartEmptyState');
  const totalDisplay = document.getElementById('cartTotalDisplay');
  const headerTitle = document.getElementById('cartHeaderTitle');
  const clearBtnText = document.getElementById('clearCartBtnText');
  const saveBtn = document.getElementById('btnSaveToTable');
  const saveBtnText = document.getElementById('btnSaveToTableText');
  const totalLabel = document.getElementById('cartTotalLabel');
  const tableStatusDetail = document.getElementById('tableStatusDetail');

  const mobileCount = document.getElementById('mobileCartItemCount');
  const mobileTotal = document.getElementById('mobileCartTotalDisplay');
  const mobileBadge = document.getElementById('mobileCartBadge');

  if (!listEl || !totalDisplay) return;

  // ==================== MODO 1: PARA LLEVAR (TRADICIONAL) ====================
  if (selectedTable === null) {
    if (headerTitle) headerTitle.textContent = "Ticket en Curso";
    if (clearBtnText) clearBtnText.textContent = "Vaciar";
    if (saveBtn) saveBtn.classList.add('hidden');
    if (totalLabel) totalLabel.textContent = "Total a Cobrar";
    if (tableStatusDetail) tableStatusDetail.classList.add('hidden');

    const totalUnits = cart.reduce((sum, it) => sum + it.quantity, 0);
    if (mobileCount) mobileCount.textContent = totalUnits === 1 ? '1 producto' : `${totalUnits} productos`;
    if (mobileBadge) {
      mobileBadge.textContent = totalUnits;
      mobileBadge.classList.toggle('hidden', totalUnits === 0);
    }

    if (cart.length === 0) {
      listEl.innerHTML = '';
      listEl.classList.add('hidden');
      listEl.style.display = 'none';
      if (emptyEl) {
        emptyEl.classList.remove('hidden');
        emptyEl.style.display = 'flex';
        const eTitle = document.getElementById('emptyStateTitle');
        const eSub = document.getElementById('emptyStateSubtitle');
        if (eTitle) eTitle.textContent = "Toca una presa o producto";
        if (eSub) eSub.textContent = "El pedido aparecerá aquí";
      }
      totalDisplay.textContent = formatCOP(0);
      if (mobileTotal) mobileTotal.textContent = formatCOP(0);
      return;
    }

    if (emptyEl) {
      emptyEl.classList.add('hidden');
      emptyEl.style.display = 'none';
    }
    listEl.classList.remove('hidden');
    listEl.style.display = 'block';
    listEl.innerHTML = '';

    let total = 0;
    cart.forEach((it, idx) => {
      const subtotal = it.product.price * it.quantity;
      total += subtotal;

      const row = document.createElement('div');
      row.className = "cart-item-row bg-slate-800/80 border border-slate-700/80 rounded-xl p-2.5 flex items-center justify-between shadow-sm transition-all";
      row.setAttribute('data-index', idx);
      row.setAttribute('data-product-id', it.product.id);
      if (it.product.sku) row.setAttribute('data-sku', it.product.sku);
      if (it.chosen_presa) row.setAttribute('data-chosen-presa', it.chosen_presa);

      const presaSubtitle = it.chosen_presa 
        ? `<span class="inline-block mt-0.5 text-[11px] font-bold text-amber-300 bg-amber-500/20 px-2 py-0.5 rounded-md">Presa: ${it.chosen_presa}</span>` 
        : '';

      row.innerHTML = `
        <div class="flex-1 pr-2">
          <div class="font-bold text-xs text-slate-100">${it.product.name}</div>
          ${presaSubtitle}
          <div class="cart-item-subtotal text-xs font-black text-amber-400 mt-0.5 tabular-nums" data-subtotal="${subtotal}">${formatCOP(subtotal)}</div>
        </div>

        <div class="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-700/80 shadow-inner">
          <button type="button" data-action="decrement" data-index="${idx}" onclick="decrementItem(${idx})" class="w-11 h-11 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Disminuir">-</button>
          <span class="cart-item-qty w-8 text-center font-black text-sm text-slate-100 tabular-nums select-none" data-quantity="${it.quantity}">${it.quantity}</span>
          <button type="button" data-action="increment" data-index="${idx}" onclick="incrementItem(${idx})" class="w-11 h-11 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Aumentar">+</button>
        </div>

        <button type="button" data-action="remove" data-index="${idx}" onclick="removeItem(${idx})" class="w-11 h-11 ml-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 font-bold text-base flex items-center justify-center active:scale-90 transition select-none touch-manipulation" title="Eliminar ítem">🗑️</button>
      `;
      listEl.appendChild(row);
    });

    totalDisplay.textContent = formatCOP(total);
    if (mobileTotal) mobileTotal.textContent = formatCOP(total);
    return;
  }

  // ==================== MODO 2: GESTIÓN DE MESAS (1 A 5) ====================
  const isOccupied = activeTableOrder && activeTableOrder.status === 'abierta';
  if (headerTitle) headerTitle.textContent = `Mesa ${selectedTable} - ${isOccupied ? 'Ocupada' : 'Libre'}`;
  if (totalLabel) totalLabel.textContent = `Total Mesa ${selectedTable}`;

  if (tableStatusDetail) {
    tableStatusDetail.classList.remove('hidden');
    tableStatusDetail.textContent = isOccupied ? `(${activeTableOrder.items_count} consumos guardados)` : "(Mesa libre sin consumos)";
  }

  // Botón superior de limpiar o cancelar comanda
  if (clearBtnText) {
    if (tableDraftCart.length > 0) {
      clearBtnText.textContent = "Limpiar Adición";
    } else if (isOccupied) {
      clearBtnText.textContent = "Cancelar Mesa";
    } else {
      clearBtnText.textContent = "Vaciar";
    }
  }

  const savedItems = (isOccupied && activeTableOrder.items) ? activeTableOrder.items : [];
  const draftItems = tableDraftCart;
  const totalUnits = savedItems.reduce((s, it) => s + it.quantity, 0) + draftItems.reduce((s, it) => s + it.quantity, 0);

  if (mobileCount) mobileCount.textContent = totalUnits === 1 ? '1 producto' : `${totalUnits} productos`;
  if (mobileBadge) {
    mobileBadge.textContent = totalUnits;
    mobileBadge.classList.toggle('hidden', totalUnits === 0);
  }

  // Estado totalmente vacío en la mesa
  if (savedItems.length === 0 && draftItems.length === 0) {
    listEl.innerHTML = '';
    listEl.classList.add('hidden');
    listEl.style.display = 'none';
    if (emptyEl) {
      emptyEl.classList.remove('hidden');
      emptyEl.style.display = 'flex';
      const eTitle = document.getElementById('emptyStateTitle');
      const eSub = document.getElementById('emptyStateSubtitle');
      if (eTitle) eTitle.textContent = `Mesa ${selectedTable} Libre`;
      if (eSub) eSub.textContent = "Toca productos del menú para sentar comensales";
    }
    if (saveBtn) saveBtn.classList.add('hidden');
    totalDisplay.textContent = formatCOP(0);
    if (mobileTotal) mobileTotal.textContent = formatCOP(0);
    return;
  }

  if (emptyEl) {
    emptyEl.classList.add('hidden');
    emptyEl.style.display = 'none';
  }
  listEl.classList.remove('hidden');
  listEl.style.display = 'block';
  listEl.innerHTML = '';

  let calculatedTotal = 0;

  // 1. Renderizar ítems ya guardados/consumidos en la mesa (stock ya descontado)
  if (savedItems.length > 0) {
    const savedHeader = document.createElement('div');
    savedHeader.className = "flex items-center justify-between text-[11px] font-black uppercase tracking-wider text-slate-400 bg-slate-950/80 px-2.5 py-1.5 rounded-lg border border-slate-800 mb-1.5";
    savedHeader.innerHTML = `<span>🍽️ Consumiendo en Mesa ${selectedTable}</span><span class="text-emerald-400 font-bold">Servido</span>`;
    listEl.appendChild(savedHeader);

    savedItems.forEach(it => {
      calculatedTotal += it.subtotal;
      const row = document.createElement('div');
      row.className = "bg-slate-850 border border-slate-700/60 rounded-xl p-2.5 flex items-center justify-between shadow-sm opacity-95 mb-1.5";
      const presaSub = it.chosen_presa ? `<span class="inline-block mt-0.5 text-[10px] font-bold text-amber-300 bg-amber-500/20 px-1.5 py-0.5 rounded">Presa: ${it.chosen_presa}</span>` : '';
      row.innerHTML = `
        <div class="flex-1 pr-2">
          <div class="font-bold text-xs text-slate-200 flex items-center gap-1.5">
            <span>${it.product_name}</span>
            <span class="text-[10px] font-black text-amber-400 bg-amber-500/10 px-1.5 py-0.2 rounded border border-amber-500/30">x${it.quantity}</span>
          </div>
          ${presaSub}
          <div class="text-xs font-black text-amber-300 mt-0.5 tabular-nums">${formatCOP(it.subtotal)}</div>
        </div>
        <div class="text-[10px] text-slate-400 font-bold px-2 py-1 rounded bg-slate-800 border border-slate-700 flex items-center gap-1">
          <span>✓</span>
          <span>En Mesa</span>
        </div>
      `;
      listEl.appendChild(row);
    });
  }

  // 2. Renderizar ítems nuevos por enviar a la mesa
  if (draftItems.length > 0) {
    const draftHeader = document.createElement('div');
    draftHeader.className = "mt-2.5 mb-1.5 flex items-center justify-between text-[11px] font-black uppercase tracking-wider text-amber-400 bg-amber-500/10 px-2.5 py-1.5 rounded-lg border border-amber-500/30";
    draftHeader.innerHTML = `<span>➕ Nueva Adición a Mesa</span><span class="text-amber-300 font-bold">Por Enviar</span>`;
    listEl.appendChild(draftHeader);

    draftItems.forEach((it, idx) => {
      const subtotal = it.product.price * it.quantity;
      calculatedTotal += subtotal;

      const row = document.createElement('div');
      row.className = "cart-item-row bg-slate-800/90 border border-amber-500/50 rounded-xl p-2.5 flex items-center justify-between shadow-sm transition-all mb-1.5";
      const presaSubtitle = it.chosen_presa 
        ? `<span class="inline-block mt-0.5 text-[11px] font-bold text-amber-300 bg-amber-500/20 px-2 py-0.5 rounded-md">Presa: ${it.chosen_presa}</span>` 
        : '';

      row.innerHTML = `
        <div class="flex-1 pr-2">
          <div class="font-bold text-xs text-slate-100">${it.product.name}</div>
          ${presaSubtitle}
          <div class="cart-item-subtotal text-xs font-black text-amber-400 mt-0.5 tabular-nums">${formatCOP(subtotal)}</div>
        </div>

        <div class="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-700/80 shadow-inner">
          <button type="button" onclick="decrementItem(${idx})" class="w-11 h-11 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Disminuir">-</button>
          <span class="cart-item-qty w-8 text-center font-black text-sm text-slate-100 tabular-nums select-none">${it.quantity}</span>
          <button type="button" onclick="incrementItem(${idx})" class="w-11 h-11 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Aumentar">+</button>
        </div>

        <button type="button" onclick="removeItem(${idx})" class="w-11 h-11 ml-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 font-bold text-base flex items-center justify-center active:scale-90 transition select-none touch-manipulation" title="Eliminar">🗑️</button>
      `;
      listEl.appendChild(row);
    });

    if (saveBtn) {
      saveBtn.classList.remove('hidden');
      if (saveBtnText) {
        saveBtnText.textContent = isOccupied ? `Enviar Adición a Mesa ${selectedTable}` : `Enviar Pedido a Mesa ${selectedTable}`;
      }
    }
  } else {
    if (saveBtn) saveBtn.classList.add('hidden');
  }

  totalDisplay.textContent = formatCOP(calculatedTotal);
  if (mobileTotal) mobileTotal.textContent = formatCOP(calculatedTotal);
}

// Manejo de Pagos en barra de comanda
async function handlePayment(method) {
  const total = getCartOrTableTotal();
  if (total <= 0) {
    alert("Agrega al menos un producto a la comanda antes de cobrar.");
    return;
  }

  // Si estamos en una mesa y hay ítems sin guardar, enviarlos primero automáticamente
  if (selectedTable !== null && tableDraftCart.length > 0) {
    const saved = await saveItemsToActiveTable(false);
    if (!saved) return;
  }

  const finalTotal = getCartOrTableTotal();
  if (method === 'efectivo') {
    openCashModal(finalTotal);
  } else if (method === 'nequi_daviplata' || method === 'datafono') {
    openDigitalModal(method, finalTotal);
  } else {
    processCheckout(method, finalTotal);
  }
}

// Modal de Efectivo
function openCashModal(total) {
  document.getElementById('cashModalTotal').textContent = formatCOP(total);
  const input = document.getElementById('cashReceivedInput');
  input.value = '';
  const changeEl = document.getElementById('cashChangeDisplay');
  changeEl.textContent = formatCOP(0);
  changeEl.classList.remove('text-amber-400');
  changeEl.classList.add('text-emerald-400');
  document.getElementById('cashModal').classList.remove('hidden');
  setTimeout(() => input.focus(), 100);
}

function closeCashModal() {
  document.getElementById('cashModal').classList.add('hidden');
}

// Acumulación de billetes en efectivo
function addCashAmount(val) {
  if (navigator.vibrate) navigator.vibrate(20);
  const input = document.getElementById('cashReceivedInput');
  const current = parseInt(input.value, 10) || 0;
  input.value = current + val;
  updateChangeCalculation();
}

function setCashAmount(val) {
  addCashAmount(val);
}

function clearCashAmount() {
  if (navigator.vibrate) navigator.vibrate(25);
  const input = document.getElementById('cashReceivedInput');
  input.value = '';
  updateChangeCalculation();
  input.focus();
}

// Pago Exacto
function setExactCash() {
  if (navigator.vibrate) navigator.vibrate(20);
  const total = getCartOrTableTotal();
  document.getElementById('cashReceivedInput').value = total;
  updateChangeCalculation();
}

// Cálculo en vivo de cambio y alerta de faltante
function updateChangeCalculation() {
  const total = getCartOrTableTotal();
  const rawVal = document.getElementById('cashReceivedInput').value;
  const received = parseFloat(rawVal) || 0;
  const changeEl = document.getElementById('cashChangeDisplay');

  if (rawVal !== '' && received < total) {
    changeEl.classList.remove('text-emerald-400');
    changeEl.classList.add('text-amber-400');
    changeEl.textContent = `Faltan ${formatCOP(total - received)}`;
  } else {
    changeEl.classList.remove('text-amber-400');
    changeEl.classList.add('text-emerald-400');
    const change = Math.max(0, received - total);
    changeEl.textContent = formatCOP(change);
  }
}

// Confirmar Pago en Efectivo con Validación Estricta
function submitCashPayment() {
  const total = getCartOrTableTotal();
  const input = document.getElementById('cashReceivedInput');
  const rawVal = input.value.trim();

  if (rawVal === '') {
    alert("Por favor ingresa el monto recibido en efectivo o presiona 'Pago Exacto'.");
    input.focus();
    return;
  }

  const received = parseFloat(rawVal) || 0;
  if (received < total) {
    alert(`Monto recibido insuficiente. Total: ${formatCOP(total)}, Recibido: ${formatCOP(received)}.`);
    input.focus();
    return;
  }

  closeCashModal();
  processCheckout('efectivo', received);
}

// Apertura de modal digital interactivo
function openDigitalModal(method, total) {
  pendingDigitalMethod = method;
  const isNequi = method === 'nequi_daviplata';

  const modal = document.getElementById('digitalModal');
  const titleEl = document.getElementById('digitalModalTitle');
  const iconEl = document.getElementById('digitalModalIcon');
  const textEl = document.getElementById('digitalModalTitleText');
  const badgeEl = document.getElementById('digitalModalBadge');
  const totalEl = document.getElementById('digitalModalTotal');
  const voucherInput = document.getElementById('digitalVoucherInput');
  const confirmBtn = document.getElementById('btnConfirmDigital');

  totalEl.textContent = formatCOP(total);
  voucherInput.value = '';

  if (isNequi) {
    iconEl.textContent = '📲';
    textEl.textContent = 'Cobro Nequi / Daviplata';
    titleEl.className = 'font-black text-base text-purple-400 flex items-center space-x-2';
    badgeEl.textContent = 'Nequi / Daviplata';
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 font-bold border border-purple-500/30';
    voucherInput.className = 'w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm font-bold text-slate-100 placeholder-slate-600 focus:outline-none focus:border-purple-500 tracking-wider';
    confirmBtn.className = 'flex-1 h-12 rounded-xl bg-purple-600 hover:bg-purple-500 active:scale-95 text-white font-black text-xs shadow-xl transition flex items-center justify-center select-none';
    confirmBtn.textContent = 'CONFIRMAR TRANSACCIÓN';
  } else {
    iconEl.textContent = '💳';
    textEl.textContent = 'Cobro con Datáfono';
    titleEl.className = 'font-black text-base text-sky-400 flex items-center space-x-2';
    badgeEl.textContent = 'Datáfono (Tarjeta)';
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 font-bold border border-sky-500/30';
    voucherInput.className = 'w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm font-bold text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500 tracking-wider';
    confirmBtn.className = 'flex-1 h-12 rounded-xl bg-sky-600 hover:bg-sky-500 active:scale-95 text-white font-black text-xs shadow-xl transition flex items-center justify-center select-none';
    confirmBtn.textContent = 'CONFIRMAR VOUCHER';
  }

  modal.classList.remove('hidden');
  setTimeout(() => voucherInput.focus(), 100);
}

function closeDigitalModal() {
  document.getElementById('digitalModal').classList.add('hidden');
  pendingDigitalMethod = null;
}

function confirmDigitalPayment() {
  if (!pendingDigitalMethod) return;
  const method = pendingDigitalMethod;
  const voucher = document.getElementById('digitalVoucherInput').value.trim();
  const notes = voucher ? `Comprobante: ${voucher}` : null;

  closeDigitalModal();
  processCheckout(method, 0, notes);
}

// Enviar Venta al Servidor (Mostrador o Mesa)
async function processCheckout(paymentMethod, cashReceived = 0, notes = null) {
  // CASO A: Cobro de Mesa en Sala (1 a 5)
  if (selectedTable !== null) {
    const payload = {
      payment_method: paymentMethod,
      cash_received: paymentMethod === 'efectivo' ? cashReceived : 0,
      notes: notes
    };

    try {
      const res = await fetch(`/api/pos/tables/${selectedTable}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al cobrar la mesa");

      if (navigator.vibrate) navigator.vibrate([40, 60, 40]);
      lastSaleId = data.sale_id;

      showLastSaleBanner(data);
      if (typeof showSaleSuccessModal === 'function') {
        showSaleSuccessModal(data);
      }

      tableDraftCart = [];
      activeTableOrder = null;
      await Promise.all([loadTablesStatus(), loadStockSummary()]);
      renderCart();
      toggleMobileCart(false);
    } catch (err) {
      alert("Error al procesar cobro de mesa: " + err.message);
    }
    return;
  }

  // CASO B: Cobro de Pedido Para Llevar (Mostrador Directo)
  const payload = {
    items: cart.map(it => ({
      product_id: it.product.id,
      quantity: it.quantity,
      chosen_presa: it.chosen_presa
    })),
    payment_method: paymentMethod,
    cash_received: paymentMethod === 'efectivo' ? cashReceived : 0,
    notes: notes
  };

  try {
    const res = await fetch('/api/pos/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error al procesar venta");

    // Éxito
    if (navigator.vibrate) navigator.vibrate([40, 60, 40]);
    lastSaleId = data.sale_id;

    // Mostrar banner de última venta con opción de deshacer
    showLastSaleBanner(data);

    // Abrir modal de venta exitosa con preview de ticket y devuelta
    if (typeof showSaleSuccessModal === 'function') {
      showSaleSuccessModal(data);
    }

    // Vaciar comanda
    cart = [];
    renderCart();
    toggleMobileCart(false);

    // Actualizar inventario en pantalla
    loadStockSummary();

  } catch (err) {
    alert("Error al procesar venta: " + err.message);
  }
}

// Banner de deshacer venta
function showLastSaleBanner(saleData) {
  const banner = document.getElementById('lastSaleBanner');
  const text = document.getElementById('lastSaleText');
  text.textContent = `Venta ${saleData.sale_code} (${formatCOP(saleData.total_amount)} - ${saleData.payment_method.toUpperCase()}) registrada exitosamente a las ${saleData.time_str}.`;

  banner.classList.remove('hidden');

  if (undoBannerTimeout) clearTimeout(undoBannerTimeout);
  undoBannerTimeout = setTimeout(() => {
    banner.classList.add('hidden');
  }, 20000); // 20 segundos para deshacer
}

// ==================== MÓDULO ANTIFRAUDE: ANULACIÓN CON PIN (R3) ====================

function cancelLastSale() {
  if (!lastSaleId) return;
  const modal = document.getElementById('adminPinModal');
  const pinInput = document.getElementById('adminPinInput');
  const errorBox = document.getElementById('pinErrorAlert');
  if (pinInput) pinInput.value = '';
  if (errorBox) errorBox.classList.add('hidden');
  if (modal) modal.classList.remove('hidden');
}

function closeAdminPinModal() {
  const modal = document.getElementById('adminPinModal');
  if (modal) modal.classList.add('hidden');
}

function pinKeyPress(digit) {
  const pinInput = document.getElementById('adminPinInput');
  if (!pinInput) return;
  if (pinInput.value.length < 8) {
    pinInput.value += digit;
  }
}

function pinKeyClear() {
  const pinInput = document.getElementById('adminPinInput');
  if (pinInput) pinInput.value = '';
}

function pinKeyBackspace() {
  const pinInput = document.getElementById('adminPinInput');
  if (pinInput && pinInput.value.length > 0) {
    pinInput.value = pinInput.value.slice(0, -1);
  }
}

async function submitCancelWithPin() {
  if (!lastSaleId) return;
  const pinInput = document.getElementById('adminPinInput');
  const reasonSelect = document.getElementById('cancelReasonSelect');
  const authSelect = document.getElementById('cancelAuthorizedByInput');
  const errorBox = document.getElementById('pinErrorAlert');
  const errorText = document.getElementById('pinErrorText');

  const pin = pinInput ? pinInput.value.trim() : '';
  const reason = reasonSelect ? reasonSelect.value : 'Error de digitación del cajero';
  const authorized_by = authSelect ? authSelect.value : 'Administrador';

  if (!pin) {
    if (errorBox && errorText) {
      errorText.textContent = 'Ingresa el PIN de seguridad de Administrador/Socio.';
      errorBox.classList.remove('hidden');
    }
    return;
  }

  try {
    const res = await fetch(`/api/pos/cancel-sale/${lastSaleId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-PIN': pin
      },
      body: JSON.stringify({
        pin: pin,
        reason: reason,
        authorized_by: authorized_by
      })
    });

    const data = await res.json();
    if (!res.ok) {
      if (res.status === 403) {
        if (navigator.vibrate) navigator.vibrate([100, 50, 100, 50, 100]);
        if (errorBox && errorText) {
          errorText.textContent = data.detail || '⛔ Acceso denegado: PIN de Administrador inválido.';
          errorBox.classList.remove('hidden');
        }
        return;
      }
      throw new Error(data.detail || 'No se pudo anular la venta.');
    }

    closeAdminPinModal();
    const banner = document.getElementById('lastSaleBanner');
    if (banner) banner.classList.add('hidden');
    lastSaleId = null;
    loadStockSummary();

    alert('✅ ' + data.message + ' (Registrado en bitácora forense)');
  } catch (err) {
    alert('Error al anular venta: ' + err.message);
  }
}

// ==================== EDITOR DE PRECIOS DEL MENÚ ====================
async function openPriceEditorModal() {
  const modal = document.getElementById('priceEditorModal');
  const container = document.getElementById('priceEditorItemsContainer');
  const fb = document.getElementById('priceEditorFeedback');
  if (fb) {
    fb.className = 'hidden';
    fb.textContent = '';
  }
  if (modal) modal.classList.remove('hidden');

  try {
    const res = await fetch('/api/pos/products');
    const products = await res.json();
    if (!container) return;
    container.innerHTML = '';

    if (!products || products.length === 0) {
      container.innerHTML = '<div class="p-4 text-center text-slate-400">No hay productos disponibles.</div>';
      return;
    }

    products.forEach((p, idx) => {
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between p-2.5 rounded-xl bg-slate-950/70 border border-slate-800 gap-3 hover:border-slate-700 transition';
      row.innerHTML = `
        <div class="flex items-center space-x-3 min-w-0 flex-1">
          <span class="text-2xl">${p.icon || '🍗'}</span>
          <div class="truncate">
            <div class="font-bold text-slate-100 truncate">${p.name}</div>
            <div class="text-[10px] text-slate-400 uppercase tracking-wider">${p.category} | SKU: ${p.sku}</div>
          </div>
        </div>
        <div class="flex items-center space-x-1.5 flex-shrink-0">
          <span class="text-xs text-amber-400 font-bold">$</span>
          <input type="number" step="500" min="0" 
            id="priceInput_${idx}"
            data-sku="${p.sku}"
            value="${p.price}"
            class="w-28 bg-slate-900 border border-slate-700 focus:border-amber-400 rounded-lg px-2 py-1.5 text-right font-black text-amber-400 text-sm tabular-nums focus:outline-none">
        </div>
      `;
      container.appendChild(row);
    });
  } catch (err) {
    if (container) {
      container.innerHTML = `<div class="p-4 text-center text-red-400">Error al cargar productos: ${err.message}</div>`;
    }
  }
}

async function submitPriceUpdates() {
  const container = document.getElementById('priceEditorItemsContainer');
  const pinInput = document.getElementById('priceAdminPinInput');
  const fb = document.getElementById('priceEditorFeedback');
  if (!container) return;

  const pin = (pinInput && pinInput.value.trim()) ? pinInput.value.trim() : '4321';

  const inputs = container.querySelectorAll('input[data-sku]');
  const prices = [];
  inputs.forEach(inp => {
    const sku = inp.dataset.sku;
    const priceVal = parseInt(inp.value, 10);
    prices.push({ sku: sku, price: isNaN(priceVal) ? 0 : Math.max(0, priceVal) });
  });

  try {
    const res = await fetch('/api/pos/update-prices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pin, prices: prices })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Error al actualizar precios');
    }

    if (fb) {
      fb.className = 'p-2.5 rounded-xl text-xs font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700 block';
      fb.textContent = `✅ Precios actualizados exitosamente (${prices.length} productos).`;
    }

    setTimeout(() => {
      closeModal('priceEditorModal');
      loadProducts();
    }, 1000);
  } catch (err) {
    if (fb) {
      fb.className = 'p-2.5 rounded-xl text-xs font-bold bg-red-950/80 text-red-300 border border-red-700 block';
      fb.textContent = `❌ ${err.message}`;
    }
  }
}

// ==================== INVENTARIO INICIAL ====================
async function openSetInitialStockModal() {
  const modal = document.getElementById('setInitialStockModal');
  const container = document.getElementById('initialStockItemsContainer');
  const fb = document.getElementById('setInitialStockFeedback');

  if (fb) {
    fb.className = 'hidden';
    fb.textContent = '';
  }

  if (container) {
    container.innerHTML = `<div class="p-4 text-center text-slate-400">Cargando insumos disponibles...</div>`;
  }

  if (modal) modal.classList.remove('hidden');

  try {
    const res = await fetch('/api/inventory/daily-reconciliation');
    const data = await res.json();

    if (!container) return;
    container.innerHTML = '';

    if (!data.items || data.items.length === 0) {
      container.innerHTML = `<div class="p-4 text-center text-slate-400">No se encontraron insumos en inventario.</div>`;
      return;
    }

    const locOrder = { 'Vitrina': 1, 'Bodega': 2, 'Nevera': 3, 'Cocina': 4 };
    data.items.sort((a, b) => (locOrder[a.location] || 99) - (locOrder[b.location] || 99));

    data.items.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between p-2 rounded-xl bg-slate-950/70 border border-slate-800 gap-2 hover:border-slate-700 transition';
      
      let locEmoji = '📦';
      if (it.location === 'Vitrina') locEmoji = '🍗';
      else if (it.location === 'Nevera') locEmoji = '🥤';
      else if (it.location === 'Cocina') locEmoji = '🍳';

      row.innerHTML = `
        <div class="flex items-center space-x-2 flex-1 min-w-0">
          <span class="text-xl">${locEmoji}</span>
          <div class="truncate">
            <div class="font-bold text-slate-100 truncate text-xs sm:text-sm">${it.item_name}</div>
            <div class="text-[10px] text-slate-400">${it.location} • Unidad: ${it.unit || 'uds'} (Actual: ${it.current_stock || 0})</div>
          </div>
        </div>
        <div class="w-28 flex items-center space-x-1">
          <input type="number" step="any" min="0" 
            id="initStockInput_${idx}"
            data-item-name="${it.item_name}"
            data-location="${it.location}"
            value="${it.initial_stock}"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-right font-black text-amber-400 text-xs focus:outline-none focus:border-blue-500 tabular-nums">
        </div>
      `;
      container.appendChild(row);
    });

  } catch (e) {
    if (container) {
      container.innerHTML = `<div class="p-4 text-center text-red-400">Error al cargar insumos: ${e.message}</div>`;
    }
  }
}

async function submitInitialStock() {
  const container = document.getElementById('initialStockItemsContainer');
  const fb = document.getElementById('setInitialStockFeedback');
  const updateLiveCheckbox = document.getElementById('updateLiveStockCheckbox');
  const updateLive = updateLiveCheckbox ? updateLiveCheckbox.checked : true;
  if (!container) return;

  const inputs = container.querySelectorAll('input[data-item-name]');
  const items = [];

  inputs.forEach(inp => {
    const itemName = inp.dataset.itemName;
    const location = inp.dataset.location;
    const val = parseFloat(inp.value);
    items.push({
      item_name: itemName,
      location: location,
      quantity: isNaN(val) ? 0.0 : Math.max(0, val)
    });
  });

  try {
    const res = await fetch('/api/inventory/set-initial-stock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: items, update_live_stock: updateLive })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Error al guardar inventario inicial');
    }

    if (fb) {
      fb.className = 'p-2 rounded-xl text-xs font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700 block';
      fb.textContent = `✅ Inventario inicial registrado exitosamente (${data.recorded_count} insumos).`;
    }

    setTimeout(() => {
      closeModal('setInitialStockModal');
      if (typeof loadStockSummary === 'function') loadStockSummary();
      if (typeof loadDailyReconciliation === 'function') loadDailyReconciliation();
    }, 1000);

  } catch (e) {
    if (fb) {
      fb.className = 'p-2 rounded-xl text-xs font-bold bg-red-950/80 text-red-300 border border-red-700 block';
      fb.textContent = `❌ ${e.message}`;
    }
  }
}

// ==================== PWA & INSTALACIÓN EN PANTALLA PRINCIPAL ====================
if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.log('SW registration note:', err);
    });
  });
}

let deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  const btn = document.getElementById('btnInstallPwa');
  if (btn) btn.classList.remove('hidden');
});

function triggerPwaInstall() {
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then((choiceResult) => {
      if (choiceResult.outcome === 'accepted') {
        const btn = document.getElementById('btnInstallPwa');
        if (btn) btn.classList.add('hidden');
      }
      deferredInstallPrompt = null;
    });
  } else {
    const modal = document.getElementById('pwaInstructionsModal');
    if (modal) modal.classList.remove('hidden');
  }
}

// ==================== TRASLADO DE POLLO: NEVERA (CANECAS) A VITRINA ====================
function openSacarPolloModal() {
  const modal = document.getElementById('modalSacarPolloVitrina');
  if (!modal) return;
  
  // Actualizar badges de disponibilidad en las 4 canecas de nevera
  const rawP = stockSummary['pechuga_nevera'] ? stockSummary['pechuga_nevera'].stock : 0;
  const rawC = stockSummary['contramuslo_nevera'] ? stockSummary['contramuslo_nevera'].stock : 0;
  const rawM = stockSummary['muslo_nevera'] ? stockSummary['muslo_nevera'].stock : 0;
  const rawA = stockSummary['ala_nevera'] ? stockSummary['ala_nevera'].stock : 0;

  const elP = document.getElementById('stockNeveraPechuga');
  const elC = document.getElementById('stockNeveraContramuslo');
  const elM = document.getElementById('stockNeveraMuslo');
  const elA = document.getElementById('stockNeveraAla');

  if (elP) elP.textContent = Math.floor(rawP);
  if (elC) elC.textContent = Math.floor(rawC);
  if (elM) elM.textContent = Math.floor(rawM);
  if (elA) elA.textContent = Math.floor(rawA);

  const totalModalNevera = rawP + rawC + rawM + rawA;
  const modalPresasEl = document.getElementById('modalNeveraPresasTotal');
  const modalEquivEl = document.getElementById('modalNeveraPollosEquiv');
  if (modalPresasEl) modalPresasEl.textContent = Math.floor(totalModalNevera);
  if (modalEquivEl) {
    const equiv = totalModalNevera / 8;
    modalEquivEl.textContent = Number.isInteger(equiv) ? equiv : equiv.toFixed(1);
  }

  updateSurtirPresasPreview();
  modal.classList.remove('hidden');
}

function closeSacarPolloModal() {
  const modal = document.getElementById('modalSacarPolloVitrina');
  if (modal) modal.classList.add('hidden');
}

function setTandaPreset(n) {
  setSurtirPresaQty('pechuga', n);
  setSurtirPresaQty('contramuslo', n);
  setSurtirPresaQty('muslo', n);
  setSurtirPresaQty('ala', n);
}

function clearSurtirPresas() {
  setSurtirPresaQty('pechuga', 0);
  setSurtirPresaQty('contramuslo', 0);
  setSurtirPresaQty('muslo', 0);
  setSurtirPresaQty('ala', 0);
}

function setSacarPolloQty(n) {
  setTandaPreset(2 * n);
}

function adjustSacarPolloQty(delta) {
  adjustSurtirPresaQty('pechuga', 2 * delta);
  adjustSurtirPresaQty('contramuslo', 2 * delta);
  adjustSurtirPresaQty('muslo', 2 * delta);
  adjustSurtirPresaQty('ala', 2 * delta);
}

function updateSacarPolloPreview() {
  updateSurtirPresasPreview();
}

async function confirmSacarPollo() {
  await confirmSurtirPresas();
}

// ==================== SURTIDO DE PRESAS SUELTAS (REFUERZO TARDE) ====================
function switchSurtirTab(mode) {
  const panelPollos = document.getElementById('panelSurtirPollos');
  const panelPresas = document.getElementById('panelSurtirPresas');
  const tabPollos = document.getElementById('tabBtnSurtirPollos');
  const tabPresas = document.getElementById('tabBtnSurtirPresas');

  if (mode === 'pollos') {
    if (panelPollos) panelPollos.classList.remove('hidden');
    if (panelPresas) panelPresas.classList.add('hidden');
    if (tabPollos) tabPollos.className = 'py-2 px-3 rounded-lg text-xs font-black transition border bg-amber-500 text-slate-950 border-amber-400 shadow-sm flex items-center justify-center space-x-1.5';
    if (tabPresas) tabPresas.className = 'py-2 px-3 rounded-lg text-xs font-bold transition border bg-slate-800 text-slate-300 border-slate-700 hover:text-white flex items-center justify-center space-x-1.5';
  } else {
    if (panelPollos) panelPollos.classList.add('hidden');
    if (panelPresas) panelPresas.classList.remove('hidden');
    if (tabPollos) tabPollos.className = 'py-2 px-3 rounded-lg text-xs font-bold transition border bg-slate-800 text-slate-300 border-slate-700 hover:text-white flex items-center justify-center space-x-1.5';
    if (tabPresas) tabPresas.className = 'py-2 px-3 rounded-lg text-xs font-black transition border bg-amber-500 text-slate-950 border-amber-400 shadow-sm flex items-center justify-center space-x-1.5';
    updateSurtirPresasPreview();
  }
}

function adjustSurtirPresaQty(presa, delta) {
  const inp = document.getElementById(`surtir_${presa}`);
  if (!inp) return;
  let val = parseInt(inp.value || '0', 10) + delta;
  if (val < 0) val = 0;
  inp.value = val;
  updateSurtirPresasPreview();
}

function setSurtirPresaQty(presa, val) {
  const inp = document.getElementById(`surtir_${presa}`);
  if (!inp) return;
  inp.value = val;
  updateSurtirPresasPreview();
}

function updateSurtirPresasPreview() {
  const p = parseInt(document.getElementById('surtir_pechuga')?.value || '0', 10);
  const c = parseInt(document.getElementById('surtir_contramuslo')?.value || '0', 10);
  const m = parseInt(document.getElementById('surtir_muslo')?.value || '0', 10);
  const a = parseInt(document.getElementById('surtir_ala')?.value || '0', 10);
  const total = p + c + m + a;

  const parts = [];
  if (p > 0) parts.push(`${p} Pechugas`);
  if (c > 0) parts.push(`${c} Contramuslos`);
  if (m > 0) parts.push(`${m} Muslos`);
  if (a > 0) parts.push(`${a} Alas`);

  const summaryEl = document.getElementById('previewSurtirPresasSummary');
  const totalEl = document.getElementById('previewSurtirPresasTotal');

  if (summaryEl) summaryEl.textContent = parts.length > 0 ? parts.join(', ') : 'Ninguna seleccionada';
  if (totalEl) totalEl.textContent = `+${total} presas`;
}

async function confirmSurtirPresas() {
  const p = parseInt(document.getElementById('surtir_pechuga')?.value || '0', 10);
  const c = parseInt(document.getElementById('surtir_contramuslo')?.value || '0', 10);
  const m = parseInt(document.getElementById('surtir_muslo')?.value || '0', 10);
  const a = parseInt(document.getElementById('surtir_ala')?.value || '0', 10);
  const total = p + c + m + a;

  if (total <= 0) {
    alert("Por favor ingresa al menos una presa para surtir a la vitrina caliente.");
    return;
  }

  const btn = document.getElementById('btnConfirmSurtirPresas');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span><span>Surtir presas...</span>';
  }

  try {
    const res = await fetch('/api/kitchen/surtir-presas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pechugas: p,
        contramuslos: c,
        muslos: m,
        alas: a,
        operator: 'Mostrador',
        notes: 'Refuerzo presas tarde'
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error al surtir presas a vitrina');

    closeSacarPolloModal();
    await loadStockSummary();

    // Mostrar banner de confirmación en pantalla
    const banner = document.getElementById('lastSaleBanner');
    const textEl = document.getElementById('lastSaleText');
    const undoBtn = document.getElementById('btnUndoSale');
    if (banner && textEl) {
      textEl.textContent = `¡${total} presas surtidas a vitrina exitosamente!`;
      if (undoBtn) undoBtn.classList.add('hidden');
      banner.classList.remove('hidden');
      setTimeout(() => {
        banner.classList.add('hidden');
        if (undoBtn) undoBtn.classList.remove('hidden');
      }, 6000);
    }
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>✅</span><span>Surtir Presas a Vitrina</span>';
    }
  }
}
