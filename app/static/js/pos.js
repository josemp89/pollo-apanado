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
    const baseClasses = "touch-card p-3 rounded-2xl border text-left flex flex-col justify-between shadow-md transition-all relative group";

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
      card.className = `${baseClasses} bg-slate-800/80 hover:bg-slate-750 border-slate-700/80 active:border-amber-500 active:scale-98`;
      card.disabled = false;
      card.removeAttribute('aria-disabled');
      card.onclick = () => onProductClick(p);
    }

    let stockBadgeHtml = '';
    if (stockInfo.badgeText) {
      stockBadgeHtml = `<span class="text-[10px] px-2 py-0.5 rounded-full ${stockInfo.badgeClass}">${stockInfo.badgeText}</span>`;
    }

    card.innerHTML = `
      <div class="flex items-start justify-between w-full mb-2">
        <span class="text-3xl ${!stockInfo.isAvailable ? 'grayscale opacity-75' : ''}">${p.icon || '🍗'}</span>
        ${stockBadgeHtml}
      </div>
      <div>
        <h4 class="font-black text-sm ${stockInfo.isAvailable ? 'text-slate-100 group-hover:text-amber-400' : 'text-slate-400 line-through'} transition leading-snug mb-1">${p.name}</h4>
        <div class="text-base font-black ${stockInfo.isAvailable ? 'text-amber-400' : 'text-slate-500'} tabular-nums">${formatCOP(p.price)}</div>
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
