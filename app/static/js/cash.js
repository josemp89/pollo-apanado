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

    data.items.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between p-2 rounded-xl bg-slate-950/70 border border-slate-800 gap-2';
      row.innerHTML = `
        <div class="flex-1 min-w-0">
          <div class="font-bold text-slate-100 truncate">${it.item_name}</div>
          <div class="text-[10px] text-slate-400">${it.location} (${it.unit || 'uds'})</div>
        </div>
        <div class="w-32 flex items-center space-x-1">
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
      body: JSON.stringify({ items: items })
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
    }, 1000);

  } catch (e) {
    if (fb) {
      fb.className = 'p-2 rounded-xl text-xs font-bold bg-red-950/80 text-red-300 border border-red-700 block';
      fb.textContent = `❌ ${e.message}`;
    }
  }
}

// Inicialización automática
document.addEventListener('DOMContentLoaded', () => {
  loadDailyReconciliation();
});
