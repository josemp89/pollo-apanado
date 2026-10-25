/**
 * cash.js - Lógica de Conciliación Diaria de Inventario (R3)
 * Pollo Apanado
 */

let dailyReconciliationData = null;

async function loadDailyReconciliation() {
  const tbody = document.getElementById('reconciliationTableBody');
  const badge = document.getElementById('reconciliationBalanceBadge');

  try {
    const res = await fetch('/api/inventory/daily-reconciliation');
    if (!res.ok) {
      throw new Error(`Error HTTP: ${res.status}`);
    }
    const data = await res.json();
    dailyReconciliationData = data;

    renderReconciliationTable(data);

    if (badge) {
      if (data.is_balanced) {
        badge.className = 'px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/40';
        badge.innerHTML = '✅ Cero Deriva (100% Cuadrado)';
      } else {
        badge.className = 'px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse';
        badge.innerHTML = '⚠️ Discrepancia Detectada';
      }
    }
  } catch (err) {
    console.error('Error cargando conciliación de inventario:', err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" class="py-4 text-center text-red-400 font-bold">Error al cargar la conciliación de inventario.</td></tr>`;
    }
  }
}

function renderReconciliationTable(data) {
  const tbody = document.getElementById('reconciliationTableBody');
  if (!tbody) return;

  if (!data.items || data.items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="py-4 text-center text-slate-400">No hay insumos registrados para conciliar.</td></tr>`;
    return;
  }

  tbody.innerHTML = '';

  data.items.forEach(item => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-slate-800/40 transition';

    const driftVal = parseFloat(item.drift || 0);
    const hasDrift = Math.abs(driftVal) >= 0.001;

    let driftBadge = '';
    if (!hasDrift) {
      driftBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-black bg-emerald-950/80 text-emerald-400 border border-emerald-700/60">✅ 0.0</span>`;
    } else if (driftVal > 0) {
      driftBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-black bg-amber-950/80 text-amber-400 border border-amber-700/60" title="Sobrante físico">🚨 +${driftVal}</span>`;
    } else {
      driftBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-black bg-red-950/80 text-red-400 border border-red-700/60" title="Faltante / Merma no registrada">🚨 ${driftVal}</span>`;
    }

    let locBadgeColor = 'bg-slate-800 text-slate-300';
    const locLower = (item.location || '').toLowerCase();
    if (locLower.includes('bodega')) locBadgeColor = 'bg-blue-950/80 text-blue-300 border border-blue-800/60';
    else if (locLower.includes('nevera')) locBadgeColor = 'bg-cyan-950/80 text-cyan-300 border border-cyan-800/60';
    else if (locLower.includes('cocina')) locBadgeColor = 'bg-amber-950/80 text-amber-300 border border-amber-800/60';
    else if (locLower.includes('vitrina')) locBadgeColor = 'bg-rose-950/80 text-rose-300 border border-rose-800/60';

    tr.innerHTML = `
      <td class="py-2.5 px-3">
        <span class="font-bold text-slate-100">${item.item_name}</span>
        <span class="text-[10px] text-slate-400 block">${item.unit || 'unidad'}</span>
      </td>
      <td class="py-2.5 px-3">
        <span class="px-2 py-0.5 rounded-md text-[10px] font-bold ${locBadgeColor}">${item.location}</span>
      </td>
      <td class="py-2.5 px-3 text-right font-bold text-slate-300 tabular-nums">${item.initial_stock}</td>
      <td class="py-2.5 px-3 text-right font-bold text-blue-400 tabular-nums">+${item.supplier_entries}</td>
      <td class="py-2.5 px-3 text-right font-bold text-amber-400 tabular-nums">-${item.sales_dispatches}</td>
      <td class="py-2.5 px-3 text-right font-black text-slate-200 tabular-nums">${item.expected_stock}</td>
      <td class="py-2.5 px-3 text-right font-black text-emerald-400 tabular-nums">${item.current_stock}</td>
      <td class="py-2.5 px-3 text-center">${driftBadge}</td>
    `;

    tbody.appendChild(tr);
  });
}

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
      loadDailyReconciliation();
      if (typeof loadDailySummary === 'function') loadDailySummary();
    }, 1000);

  } catch (e) {
    if (fb) {
      fb.className = 'p-2 rounded-xl text-xs font-bold bg-red-950/80 text-red-300 border border-red-700 block';
      fb.textContent = `❌ ${e.message}`;
    }
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
      if (typeof loadDailySummary === 'function') loadDailySummary();
    }, 1000);
  } catch (err) {
    if (fb) {
      fb.className = 'p-2.5 rounded-xl text-xs font-bold bg-red-950/80 text-red-300 border border-red-700 block';
      fb.textContent = `❌ ${err.message}`;
    }
  }
}

// Inicialización automática
document.addEventListener('DOMContentLoaded', () => {
  loadDailyReconciliation();
});

// ==================== PWA & INSTALACIÓN EN PANTALLA PRINCIPAL ====================
if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.log('SW registration note:', err);
    });
  });
}

let deferredCashInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredCashInstallPrompt = e;
  const btn = document.getElementById('btnInstallPwa');
  if (btn) btn.classList.remove('hidden');
});

function triggerPwaInstall() {
  if (deferredCashInstallPrompt) {
    deferredCashInstallPrompt.prompt();
    deferredCashInstallPrompt.userChoice.then((choiceResult) => {
      if (choiceResult.outcome === 'accepted') {
        const btn = document.getElementById('btnInstallPwa');
        if (btn) btn.classList.add('hidden');
      }
      deferredCashInstallPrompt = null;
    });
  } else {
    const modal = document.getElementById('pwaInstructionsModal');
    if (modal) modal.classList.remove('hidden');
  }
}

// ==================== TRASLADO DE POLLO: NEVERA (CANECAS) A VITRINA (DESDE CAJA) ====================
let cashBodegaChickenStock = 30;

async function openSacarPolloCashModal() {
  const modal = document.getElementById('modalSacarPolloCash');
  if (!modal) return;
  try {
    const res = await fetch('/api/pos/stock-summary');
    if (res.ok) {
      const data = await res.json();
      cashBodegaChickenStock = (data['pollo_entero_crudo'] && data['pollo_entero_crudo'].stock) || 0;
      
      const rawP = data['pechuga_nevera'] ? data['pechuga_nevera'].stock : 0;
      const rawC = data['contramuslo_nevera'] ? data['contramuslo_nevera'].stock : 0;
      const rawM = data['muslo_nevera'] ? data['muslo_nevera'].stock : 0;
      const rawA = data['ala_nevera'] ? data['ala_nevera'].stock : 0;

      const elP = document.getElementById('stockNeveraCashPechuga');
      const elC = document.getElementById('stockNeveraCashContramuslo');
      const elM = document.getElementById('stockNeveraCashMuslo');
      const elA = document.getElementById('stockNeveraCashAla');

      if (elP) elP.textContent = Math.floor(rawP);
      if (elC) elC.textContent = Math.floor(rawC);
      if (elM) elM.textContent = Math.floor(rawM);
      if (elA) elA.textContent = Math.floor(rawA);
    }
  } catch (e) {
    console.warn("Could not fetch stock-summary:", e);
  }
  
  updateSurtirCashPresasPreview();
  modal.classList.remove('hidden');
}

function closeSacarPolloCashModal() {
  const modal = document.getElementById('modalSacarPolloCash');
  if (modal) modal.classList.add('hidden');
}

function setTandaCashPreset(n) {
  setSurtirCashPresaQty('pechuga', n);
  setSurtirCashPresaQty('contramuslo', n);
  setSurtirCashPresaQty('muslo', n);
  setSurtirCashPresaQty('ala', n);
}

function clearSurtirCashPresas() {
  setSurtirCashPresaQty('pechuga', 0);
  setSurtirCashPresaQty('contramuslo', 0);
  setSurtirCashPresaQty('muslo', 0);
  setSurtirCashPresaQty('ala', 0);
}

function setSacarPolloCashQty(n) {
  setTandaCashPreset(2 * n);
}

function adjustSacarPolloCashQty(delta) {
  adjustSurtirCashPresaQty('pechuga', 2 * delta);
  adjustSurtirCashPresaQty('contramuslo', 2 * delta);
  adjustSurtirCashPresaQty('muslo', 2 * delta);
  adjustSurtirCashPresaQty('ala', 2 * delta);
}

function updateSacarPolloCashPreview() {
  updateSurtirCashPresasPreview();
}

async function confirmSacarPolloCash() {
  await confirmSurtirCashPresas();
}

function switchSurtirCashTab(mode) {
  // Ya no se requieren pestañas: vista directa de presas
  updateSurtirCashPresasPreview();
}

function adjustSurtirCashPresaQty(presa, delta) {
  const inp = document.getElementById(`surtir_cash_${presa}`);
  if (!inp) return;
  let val = parseInt(inp.value || '0', 10) + delta;
  if (val < 0) val = 0;
  inp.value = val;
  updateSurtirCashPresasPreview();
}

function setSurtirCashPresaQty(presa, val) {
  const inp = document.getElementById(`surtir_cash_${presa}`);
  if (!inp) return;
  inp.value = val;
  updateSurtirCashPresasPreview();
}

function updateSurtirCashPresasPreview() {
  const p = parseInt(document.getElementById('surtir_cash_pechuga')?.value || '0', 10);
  const c = parseInt(document.getElementById('surtir_cash_contramuslo')?.value || '0', 10);
  const m = parseInt(document.getElementById('surtir_cash_muslo')?.value || '0', 10);
  const a = parseInt(document.getElementById('surtir_cash_ala')?.value || '0', 10);
  const total = p + c + m + a;

  const parts = [];
  if (p > 0) parts.push(`${p} Pechugas`);
  if (c > 0) parts.push(`${c} Contramuslos`);
  if (m > 0) parts.push(`${m} Muslos`);
  if (a > 0) parts.push(`${a} Alas`);

  const summaryEl = document.getElementById('previewSurtirCashPresasSummary');
  const totalEl = document.getElementById('previewSurtirCashPresasTotal');

  if (summaryEl) summaryEl.textContent = parts.length > 0 ? parts.join(', ') : 'Ninguna seleccionada';
  if (totalEl) totalEl.textContent = `+${total} presas`;
}

async function confirmSurtirCashPresas() {
  const p = parseInt(document.getElementById('surtir_cash_pechuga')?.value || '0', 10);
  const c = parseInt(document.getElementById('surtir_cash_contramuslo')?.value || '0', 10);
  const m = parseInt(document.getElementById('surtir_cash_muslo')?.value || '0', 10);
  const a = parseInt(document.getElementById('surtir_cash_ala')?.value || '0', 10);
  const total = p + c + m + a;

  if (total <= 0) {
    alert("Por favor ingresa al menos una presa para surtir a la vitrina caliente.");
    return;
  }

  const btn = document.getElementById('btnConfirmSurtirCashPresas');
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
        operator: 'Caja',
        notes: 'Refuerzo presas tarde'
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error al surtir presas a vitrina');

    closeSacarPolloCashModal();
    if (typeof loadDailySummary === 'function') await loadDailySummary();
    if (typeof loadDailyReconciliation === 'function') await loadDailyReconciliation();
    if (typeof loadClosingInventorySheet === 'function') await loadClosingInventorySheet(true);
    alert(`¡${total} presas surtidas a vitrina exitosamente!`);
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>✅</span><span>Surtir Presas a Vitrina</span>';
    }
  }
}
