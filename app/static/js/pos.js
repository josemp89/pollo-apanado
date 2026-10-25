// Estado Global del Punto de Venta
let allProducts = [];
let stockSummary = {};
let currentCategory = 'todos';
let cart = []; // { product, quantity, chosen_presa }
let pendingPresaProduct = null;
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

// Inicialización al cargar la página
document.addEventListener('DOMContentLoaded', async () => {
  initClock();
  await Promise.all([loadProducts(), loadStockSummary()]);
  setInterval(loadStockSummary, 15000); // Refrescar stock cada 15s
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

  // 2. Combos de pollo
  else if (product.sku === 'POL-14') {
    const muslo = getStock('muslo_vitrina');
    const contra = getStock('contramuslo_vitrina');
    const papas = getStock('papas_raciones');
    stock = Math.min(muslo, contra, papas);
    label = 'Combos';
    color = 'indigo';
  } else if (product.sku === 'POL-12') {
    const pec = getStock('pechuga_vitrina');
    const ala = getStock('ala_vitrina');
    const mus = getStock('muslo_vitrina');
    const con = getStock('contramuslo_vitrina');
    const papas = getStock('papas_raciones');
    stock = Math.min(pec, ala, mus, con, papas);
    label = 'Combos';
    color = 'purple';
  } else if (product.sku === 'POL-ENT') {
    const pec = Math.floor(getStock('pechuga_vitrina') / 2);
    const ala = Math.floor(getStock('ala_vitrina') / 2);
    const mus = Math.floor(getStock('muslo_vitrina') / 2);
    const con = Math.floor(getStock('contramuslo_vitrina') / 2);
    const papas = Math.floor(getStock('papas_raciones') / 2);
    stock = Math.min(pec, ala, mus, con, papas);
    label = 'Enteros';
    color = 'rose';
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

  if (product.requires_presa_selection) {
    // Abrir modal de selección de presa (Almuerzo Completo)
    pendingPresaProduct = product;
    openPresaModal();
  } else {
    addToCart(product);
  }
}

// Modal de Selección de Presa
function openPresaModal() {
  updateStockBadgesInModal();
  const hasAvailablePresas = PRESA_MAP.some(item => {
    const s = stockSummary[item.key];
    return s && Number(s.stock) > 0;
  });

  if (!hasAvailablePresas) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert("Todas las presas de pollo están agotadas en vitrina térmica. No es posible agregar Almuerzo Completo en este momento.");
    pendingPresaProduct = null;
    return;
  }

  document.getElementById('presaModal').classList.remove('hidden');
}

function closePresaModal() {
  document.getElementById('presaModal').classList.add('hidden');
  pendingPresaProduct = null;
}

function updateStockBadgesInModal() {
  PRESA_MAP.forEach(item => {
    const badgeEl = document.getElementById(item.badgeId);
    const btnEl = document.getElementById(item.btnId) || badgeEl?.closest('button');
    if (!badgeEl || !btnEl) return;

    const stockItem = stockSummary[item.key];
    const stock = stockItem ? Number(stockItem.stock) : 0;

    if (stock <= 0) {
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

      badgeEl.textContent = `Quedan ${stock} listas`;
      badgeEl.className = `text-[11px] ${item.colorClass} font-bold`;
    }
  });
}

function getSkuForPresa(presa) {
  const map = { 'Pechuga': 'POL-PEC', 'Muslo': 'POL-MUS', 'Contramuslo': 'POL-CON', 'Ala': 'POL-ALA' };
  return map[presa] || null;
}

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
  const cartPresaCount = cart.reduce((sum, it) => {
    if (it.chosen_presa === presa) return sum + it.quantity;
    if (it.product.sku === getSkuForPresa(presa)) return sum + it.quantity;
    return sum;
  }, 0);

  if (cartPresaCount >= currentStock) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`Solo quedan ${currentStock} unidad(es) de ${presa} en vitrina, y ya están agregadas a la comanda.`);
    return;
  }

  if (navigator.vibrate) navigator.vibrate(30);
  addToCart(pendingPresaProduct, presa);
  closePresaModal();
}

// Agregar al carrito / comanda
function addToCart(product, chosen_presa = null) {
  const existing = cart.find(it => it.product.id === product.id && it.chosen_presa === chosen_presa);
  if (existing) {
    existing.quantity++;
  } else {
    cart.push({
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
  if (idx < 0 || idx >= cart.length || !cart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  const qty = Number(newQty);
  if (isNaN(qty) || qty <= 0) {
    cart.splice(idx, 1);
  } else {
    cart[idx].quantity = Math.floor(qty);
  }
  renderCart();
}

function incrementItem(idx) {
  if (idx < 0 || idx >= cart.length || !cart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  cart[idx].quantity++;
  renderCart();
}

function decrementItem(idx) {
  if (idx < 0 || idx >= cart.length || !cart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(20);
  if (cart[idx].quantity > 1) {
    cart[idx].quantity--;
  } else {
    cart.splice(idx, 1);
  }
  renderCart();
}

function removeItem(idx) {
  if (idx < 0 || idx >= cart.length || !cart[idx]) return;
  if (navigator.vibrate) navigator.vibrate(35);
  cart.splice(idx, 1);
  renderCart();
}

// Alias para compatibilidad de interfaz
function removeFromCart(idx) {
  removeItem(idx);
}

function clearCart() {
  if (navigator.vibrate) navigator.vibrate(50);
  cart = [];
  renderCart();
}

// Renderizado reactivo de la comanda
function renderCart() {
  const listEl = document.getElementById('cartItemsList');
  const emptyEl = document.getElementById('cartEmptyState');
  const totalDisplay = document.getElementById('cartTotalDisplay');

  // Elementos de la barra flotante en móviles
  const mobileCount = document.getElementById('mobileCartItemCount');
  const mobileTotal = document.getElementById('mobileCartTotalDisplay');
  const mobileBadge = document.getElementById('mobileCartBadge');

  if (!listEl || !totalDisplay) return;

  const totalUnits = cart.reduce((sum, it) => sum + it.quantity, 0);

  // Sincronizar barra flotante en teléfonos
  if (mobileCount) {
    mobileCount.textContent = totalUnits === 1 ? '1 producto' : `${totalUnits} productos`;
  }
  if (mobileBadge) {
    mobileBadge.textContent = totalUnits;
    if (totalUnits > 0) {
      mobileBadge.classList.remove('hidden');
    } else {
      mobileBadge.classList.add('hidden');
    }
  }

  // Estado Vacío: Comanda sin ítems
  if (cart.length === 0) {
    listEl.innerHTML = '';
    listEl.classList.add('hidden');
    listEl.style.display = 'none';
    if (emptyEl) {
      emptyEl.classList.remove('hidden');
      emptyEl.style.display = 'flex';
    }
    totalDisplay.textContent = formatCOP(0);
    if (mobileTotal) mobileTotal.textContent = formatCOP(0);
    return;
  }

  // Estado Activo: Comanda con ítems
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

      <!-- Controles Stepper Grande Táctil (>= 44x44px) -->
      <div class="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-700/80 shadow-inner">
        <button type="button" data-action="decrement" data-index="${idx}" onclick="decrementItem(${idx})" class="w-11 h-11 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Disminuir">
          -
        </button>
        <span class="cart-item-qty w-8 text-center font-black text-sm text-slate-100 tabular-nums select-none" data-quantity="${it.quantity}">${it.quantity}</span>
        <button type="button" data-action="increment" data-index="${idx}" onclick="incrementItem(${idx})" class="w-11 h-11 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Aumentar">
          +
        </button>
      </div>

      <!-- Botón Eliminar Ítem Grande Táctil (>= 44x44px) -->
      <button type="button" data-action="remove" data-index="${idx}" onclick="removeItem(${idx})" class="w-11 h-11 ml-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 font-bold text-base flex items-center justify-center active:scale-90 transition select-none touch-manipulation" title="Eliminar ítem">
        🗑️
      </button>
    `;

    listEl.appendChild(row);
  });

  totalDisplay.textContent = formatCOP(total);
  if (mobileTotal) mobileTotal.textContent = formatCOP(total);
}

// Manejo de Pagos en barra de comanda
function handlePayment(method) {
  if (cart.length === 0) {
    alert("Agrega al menos un producto a la comanda antes de cobrar.");
    return;
  }

  const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);

  if (method === 'efectivo') {
    openCashModal(total);
  } else if (method === 'nequi_daviplata' || method === 'datafono') {
    openDigitalModal(method, total);
  } else {
    processCheckout(method, total);
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

// Compatibilidad por si se invoca con el nombre anterior
function setCashAmount(val) {
  addCashAmount(val);
}

// Limpiar valor recibido
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
  const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
  document.getElementById('cashReceivedInput').value = total;
  updateChangeCalculation();
}

// Cálculo en vivo de cambio y alerta de faltante
function updateChangeCalculation() {
  const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
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
  const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
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

// Enviar Venta al Servidor
async function processCheckout(paymentMethod, cashReceived = 0, notes = null) {
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
