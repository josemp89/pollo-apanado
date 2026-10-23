# Handoff Report — Explorer M2.1: Frontend Live Stock Checking & Presa Locking

**Author**: Explorer 1 (`explorer_m2_1`)  
**Mission**: Milestone M2 — Analyze frontend live stock checking and presa selection locking in `app/templates/index.html` and `app/static/js/pos.js`.  
**Target Files Analyzed**:
- `app/templates/index.html` (specifically lines 172–209 `#presaModal` and lines 112–116 `#productsGrid`)
- `app/static/js/pos.js` (`updateStockBadgesInModal`, `confirmPresaChoice`, `renderProducts`, `loadStockSummary`, `onProductClick`, `addToCart`)
- `app/routers/pos.py` (lines 21–37 `/api/pos/stock-summary`, lines 57–131 inventory requirements)
- `app/database.py` (lines 191–266 product catalog and inventory definitions)

---

## 1. Observation

### 1.1. State of `#presaModal` in `app/templates/index.html:172-209`
In `app/templates/index.html`:
```html
172:   <!-- MODAL RÁPIDO DE SELECCIÓN DE PRESA PARA ALMUERZO -->
173:   <div id="presaModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
174:     <div class="bg-slate-850 bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4 animate-scale-up">
175:       <div class="text-center space-y-1">
176:         <span class="text-3xl">🍽️</span>
177:         <h3 class="text-lg font-black text-amber-400">¿Qué Presa Lleva el Almuerzo?</h3>
178:         <p class="text-xs text-slate-400">Selecciona la presa para descontar exactamente del inventario</p>
179:       </div>
180: 
181:       <div class="grid grid-cols-2 gap-3" id="presaChoices">
182:         <button onclick="confirmPresaChoice('Pechuga')" class="p-4 rounded-xl bg-slate-800 hover:bg-blue-600/30 border border-slate-700 hover:border-blue-500 active:scale-95 text-center transition space-y-1">
183:           <div class="text-2xl">🍗</div>
184:           <div class="font-black text-sm text-slate-100">Pechuga</div>
185:           <div id="stock-pechuga-badge" class="text-[11px] text-blue-400 font-bold">Cargando...</div>
186:         </button>
187:         <button onclick="confirmPresaChoice('Muslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-orange-600/30 border border-slate-700 hover:border-orange-500 active:scale-95 text-center transition space-y-1">
188:           <div class="text-2xl">🍗</div>
189:           <div class="font-black text-sm text-slate-100">Muslo</div>
190:           <div id="stock-muslo-badge" class="text-[11px] text-orange-400 font-bold">Cargando...</div>
191:         </button>
192:         <button onclick="confirmPresaChoice('Contramuslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-amber-600/30 border border-slate-700 hover:border-amber-500 active:scale-95 text-center transition space-y-1">
193:           <div class="text-2xl">🍗</div>
194:           <div class="font-black text-sm text-slate-100">Contramuslo</div>
195:           <div id="stock-contramuslo-badge" class="text-[11px] text-amber-400 font-bold">Cargando...</div>
196:         </button>
197:         <button onclick="confirmPresaChoice('Ala')" class="p-4 rounded-xl bg-slate-800 hover:bg-yellow-600/30 border border-slate-700 hover:border-yellow-500 active:scale-95 text-center transition space-y-1">
198:           <div class="text-2xl">🍗</div>
199:           <div class="font-black text-sm text-slate-100">Ala</div>
200:           <div id="stock-ala-badge" class="text-[11px] text-yellow-400 font-bold">Cargando...</div>
201:         </button>
202:       </div>
```
- **Direct observation**:
  - The `<button>` tags lack distinct `id` attributes (e.g. `id="btn-presa-pechuga"`) or `data-presa` attributes. Only the child badges have IDs (`id="stock-pechuga-badge"`, etc.).
  - The buttons have active scaling (`active:scale-95`) and hover background styles regardless of inventory stock status.

### 1.2. State of `updateStockBadgesInModal()` in `app/static/js/pos.js:146-159`
```javascript
146: function updateStockBadgesInModal() {
147:   if (stockSummary['pechuga_vitrina']) {
148:     document.getElementById('stock-pechuga-badge').textContent = `Quedan ${stockSummary['pechuga_vitrina'].stock} listas`;
149:   }
150:   if (stockSummary['muslo_vitrina']) {
151:     document.getElementById('stock-muslo-badge').textContent = `Quedan ${stockSummary['muslo_vitrina'].stock} listas`;
152:   }
153:   if (stockSummary['contramuslo_vitrina']) {
154:     document.getElementById('stock-contramuslo-badge').textContent = `Quedan ${stockSummary['contramuslo_vitrina'].stock} listas`;
155:   }
156:   if (stockSummary['ala_vitrina']) {
157:     document.getElementById('stock-ala-badge').textContent = `Quedan ${stockSummary['ala_vitrina'].stock} listas`;
158:   }
159: }
```
- **Direct observation**:
  - The function only updates `textContent` to `"Quedan X listas"`.
  - When `stockSummary[key].stock === 0`, it displays `"Quedan 0 listas"`.
  - It NEVER disables the button element (`disabled` attribute is never set).
  - It NEVER applies visual disabled styling (`opacity-50`, `cursor-not-allowed`, etc.).
  - It NEVER displays explicit exhaustion text such as `(Agotado)`.
  - If a key is missing or undefined, it remains as `"Cargando..."` without error handling.

### 1.3. State of `confirmPresaChoice()` in `app/static/js/pos.js:161-167`
```javascript
161: function confirmPresaChoice(presa) {
162:   if (navigator.vibrate) navigator.vibrate(30);
163:   if (pendingPresaProduct) {
164:     addToCart(pendingPresaProduct, presa);
165:   }
166:   closePresaModal();
167: }
```
- **Direct observation**:
  - Zero stock checking is performed.
  - If the user clicks or programmatically calls `confirmPresaChoice('Pechuga')` when `stockSummary['pechuga_vitrina'].stock <= 0`, it unconditionally calls `addToCart(...)` and adds the item to the order.
  - If `pendingPresaProduct` is null, it still vibrates and closes the modal silently.

### 1.4. State of `renderProducts()` in `app/static/js/pos.js:79-119`
```javascript
79: function renderProducts() {
80:   const grid = document.getElementById('productsGrid');
81:   grid.innerHTML = '';
82: 
83:   const filtered = currentCategory === 'todos' 
84:     ? allProducts 
85:     : allProducts.filter(p => p.category === currentCategory);
86: 
87:   filtered.forEach(p => {
88:     const card = document.createElement('button');
89:     card.className = "touch-card p-3 rounded-2xl bg-slate-800/80 hover:bg-slate-750 border border-slate-700/80 text-left flex flex-col justify-between shadow-md active:border-amber-500 group relative";
90:     card.onclick = () => onProductClick(p);
91: 
92:     // Obtener stock relevante si aplica
93:     let stockBadge = '';
94:     if (p.sku === 'POL-PEC' && stockSummary['pechuga_vitrina']) {
95:       stockBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-bold">Vitrina: ${stockSummary['pechuga_vitrina'].stock}</span>`;
96:     } else if (p.sku === 'POL-MUS' && stockSummary['muslo_vitrina']) {
97:       stockBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-300 font-bold">Vitrina: ${stockSummary['muslo_vitrina'].stock}</span>`;
98:     } else if (p.sku === 'POL-CON' && stockSummary['contramuslo_vitrina']) {
99:       stockBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-bold">Vitrina: ${stockSummary['contramuslo_vitrina'].stock}</span>`;
100:     } else if (p.sku === 'POL-ALA' && stockSummary['ala_vitrina']) {
101:       stockBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-300 font-bold">Vitrina: ${stockSummary['ala_vitrina'].stock}</span>`;
102:     } else if (p.category === 'gaseosas' && stockSummary[p.sku]) {
103:       stockBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-700 text-slate-300 font-bold">Nevera: ${stockSummary[p.sku].stock}</span>`;
104:     }
105: 
106:     card.innerHTML = `
107:       <div class="flex items-start justify-between w-full mb-2">
108:         <span class="text-3xl">${p.icon || '🍗'}</span>
109:         ${stockBadge}
110:       </div>
111:       <div>
112:         <h4 class="font-black text-sm text-slate-100 group-hover:text-amber-400 transition leading-snug mb-1">${p.name}</h4>
113:         <div class="text-base font-black text-amber-400 tabular-nums">${formatCOP(p.price)}</div>
114:       </div>
115:     `;
116: 
117:     grid.appendChild(card);
118:   });
119: }
```
- **Direct observation**:
  - `card.disabled` is NEVER set, even when stock is 0.
  - `card.onclick` is ALWAYS attached (`() => onProductClick(p)`).
  - If `stock === 0`, the badge displays `Vitrina: 0` or `Nevera: 0`, but the card still has full opacity, hover styles, and active scale animations.
  - No stock badges exist for:
    - Combos (`POL-14`, `POL-12`, `POL-ENT`).
    - Almuerzo Completo (`ALM-COMP`).
    - Porciones (`POR-CALD`, `POR-FRIJ`, `POR-ARROZ`, `POR-PAPAS`, `POR-AREP`), even though their stocks are returned in `/api/pos/stock-summary` under `caldo_raciones`, `frijoles_raciones`, `arroz_raciones`, `papas_raciones`, `arepas_unidades`.

### 1.5. State of `loadStockSummary()` and Startup Lifecycle in `pos.js:10-16, 43-52`
```javascript
10: document.addEventListener('DOMContentLoaded', () => {
11:   initClock();
12:   loadProducts();
13:   loadStockSummary();
14:   setInterval(loadStockSummary, 15000); // Refrescar stock cada 15s
15: });
...
43: async function loadStockSummary() {
44:   try {
45:     const res = await fetch('/api/pos/stock-summary');
46:     stockSummary = await res.json();
47:     updateStockBadgesInModal();
48:     renderProducts(); // Re-renderizar para actualizar badges de stock
49:   } catch (err) {
50:     console.error("Error al cargar stock:", err);
51:   }
52: }
```
- **Direct observation**:
  - `loadProducts()` and `loadStockSummary()` are executed concurrently without synchronization. If `loadStockSummary()` finishes before `loadProducts()`, `allProducts` is `[]`, so `renderProducts()` does nothing until `loadProducts()` completes.
  - `loadStockSummary()` is called at line 367 after checkout (`processCheckout`) and at line 401 after cancel sale (`cancelLastSale`).
  - Polling interval is 15 seconds.

### 1.6. Pytest Execution Baseline
- Command: `pytest`
- Result: **112 passed, 0 failed in 18.11s**. All existing backend invariants, boundary tests, and concurrency suites pass.

---

## 2. Logic Chain

1. **Premise**: In POS tablet operation, if a physical item (e.g., Pechuga) is depleted in vitrina (`stock <= 0`), allowing the cashier to select it creates operational friction, cashier error, and runtime 400 rejection during checkout (as observed in `app/routers/pos.py:204-210`).
2. **From Observation 1.1 & 1.2**: In `#presaModal`, the buttons for each presa have no disabled logic. `updateStockBadgesInModal()` only sets `textContent = "Quedan 0 listas"`. Without the HTML `disabled` attribute, `pointer-events-none`, and `opacity-50 cursor-not-allowed`, touchscreen taps will trigger `confirmPresaChoice()`.
3. **From Observation 1.3**: `confirmPresaChoice(presa)` does not check `stockSummary`. Even if a user bypasses UI disabling or taps before styling takes effect, the item is pushed into `cart`. Therefore, `confirmPresaChoice()` must be guarded with a strict inventory floor check (`stockSummary[presa_key].stock <= 0`).
4. **From Observation 1.4**: `renderProducts()` fails to disable 0-stock products on the main grid. When any product's inventory reaches 0, its card remains clickable, with full hover effects and standard borders. Furthermore, combos (`POL-14`, `POL-12`, `POL-ENT`), portions (`POR-*`), and almuerzos (`ALM-COMP`) completely lack stock calculations, even though their constituent ingredients are available in `stockSummary`.
5. **Conclusion & Remediation Path**:
   - Add explicit button IDs (`btn-presa-pechuga`, etc.) in `index.html:180-201`.
   - Rewrite `updateStockBadgesInModal()` to set `disabled = true`, visual styling (`opacity-50 cursor-not-allowed pointer-events-none`), remove active transitions, and display explicit text `"❌ Agotado (0 listas)"` (or restore active state when stock > 0).
   - Harden `confirmPresaChoice(presa)` with a defensive check against `stockSummary`, vibrating with error haptics and aborting if stock <= 0.
   - Implement `getProductStockInfo(product, stockSummary)` in `pos.js` to compute stock for presas, combos, almuerzos, portions, and sodas, and update `renderProducts()` to disable 0-stock cards with `opacity-50 cursor-not-allowed`, strikethrough/dimmed styling, and `🚫 Agotado` badges.
   - Guard `onProductClick(product)` against 0-stock items.
   - Ensure `loadStockSummary()` immediately propagates updates to both the grid and the modal during polling, checkout, and sale reversal.

---

## 3. Caveats

1. **Client-Side Cart Concurrency**: The frontend checks `stockSummary`, which represents the snapshot on the server at the moment of fetching. If two tablets simultaneously attempt to add the final Pechuga, the frontend will allow adding it to cart on both, but the SQLite atomic deduction in `app/routers/pos.py:214-220` with `WHERE item_key = ? AND stock >= ?` and `WAL` mode ensures only one checkout succeeds, and the other receives HTTP 400. This is the intended architecture.
2. **Cart Increment Guard**: In addition to modal and grid locking, the comanda stepper `incrementItem(idx)` should check available stock so cashiers cannot click `+` beyond available vitrina stock.
3. **No Direct Code Modifications**: Per Explorer rules, this report provides exact, verified, copy-pasteable proposals without modifying the code files directly.

---

## 4. Conclusion & Concrete Implementation Recommendations

### Component A: `app/templates/index.html` (Modal Enhancement)

In `app/templates/index.html:180-201`, assign explicit IDs, data attributes, and semantic labels to the presa buttons:

#### Proposed Changes in `app/templates/index.html`:
```html
      <!-- BEFORE -->
      <div class="grid grid-cols-2 gap-3" id="presaChoices">
        <button onclick="confirmPresaChoice('Pechuga')" class="p-4 rounded-xl bg-slate-800 hover:bg-blue-600/30 border border-slate-700 hover:border-blue-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Pechuga</div>
          <div id="stock-pechuga-badge" class="text-[11px] text-blue-400 font-bold">Cargando...</div>
        </button>
        <button onclick="confirmPresaChoice('Muslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-orange-600/30 border border-slate-700 hover:border-orange-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Muslo</div>
          <div id="stock-muslo-badge" class="text-[11px] text-orange-400 font-bold">Cargando...</div>
        </button>
        <button onclick="confirmPresaChoice('Contramuslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-amber-600/30 border border-slate-700 hover:border-amber-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Contramuslo</div>
          <div id="stock-contramuslo-badge" class="text-[11px] text-amber-400 font-bold">Cargando...</div>
        </button>
        <button onclick="confirmPresaChoice('Ala')" class="p-4 rounded-xl bg-slate-800 hover:bg-yellow-600/30 border border-slate-700 hover:border-yellow-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Ala</div>
          <div id="stock-ala-badge" class="text-[11px] text-yellow-400 font-bold">Cargando...</div>
        </button>
      </div>

      <!-- AFTER -->
      <div class="grid grid-cols-2 gap-3" id="presaChoices">
        <button type="button" id="btn-presa-pechuga" data-presa="Pechuga" onclick="confirmPresaChoice('Pechuga')" class="p-4 rounded-xl bg-slate-800 hover:bg-blue-600/30 border border-slate-700 hover:border-blue-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Pechuga</div>
          <div id="stock-pechuga-badge" class="text-[11px] text-blue-400 font-bold">Cargando...</div>
        </button>
        <button type="button" id="btn-presa-muslo" data-presa="Muslo" onclick="confirmPresaChoice('Muslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-orange-600/30 border border-slate-700 hover:border-orange-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Muslo</div>
          <div id="stock-muslo-badge" class="text-[11px] text-orange-400 font-bold">Cargando...</div>
        </button>
        <button type="button" id="btn-presa-contramuslo" data-presa="Contramuslo" onclick="confirmPresaChoice('Contramuslo')" class="p-4 rounded-xl bg-slate-800 hover:bg-amber-600/30 border border-slate-700 hover:border-amber-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Contramuslo</div>
          <div id="stock-contramuslo-badge" class="text-[11px] text-amber-400 font-bold">Cargando...</div>
        </button>
        <button type="button" id="btn-presa-ala" data-presa="Ala" onclick="confirmPresaChoice('Ala')" class="p-4 rounded-xl bg-slate-800 hover:bg-yellow-600/30 border border-slate-700 hover:border-yellow-500 active:scale-95 text-center transition space-y-1">
          <div class="text-2xl">🍗</div>
          <div class="font-black text-sm text-slate-100">Ala</div>
          <div id="stock-ala-badge" class="text-[11px] text-yellow-400 font-bold">Cargando...</div>
        </button>
      </div>
```

---

### Component B: `app/static/js/pos.js` (Modal & Presa Locking Logic)

#### 1. Constant Mapping Definition
Add a reusable structure to map each presa to its inventory key, element IDs, and default colors:
```javascript
const PRESA_MAP = [
  { name: 'Pechuga', key: 'pechuga_vitrina', btnId: 'btn-presa-pechuga', badgeId: 'stock-pechuga-badge', colorClass: 'text-blue-400' },
  { name: 'Muslo', key: 'muslo_vitrina', btnId: 'btn-presa-muslo', badgeId: 'stock-muslo-badge', colorClass: 'text-orange-400' },
  { name: 'Contramuslo', key: 'contramuslo_vitrina', btnId: 'btn-presa-contramuslo', badgeId: 'stock-contramuslo-badge', colorClass: 'text-amber-400' },
  { name: 'Ala', key: 'ala_vitrina', btnId: 'btn-presa-ala', badgeId: 'stock-ala-badge', colorClass: 'text-yellow-400' }
];
```

#### 2. Robust `updateStockBadgesInModal()`
```javascript
function updateStockBadgesInModal() {
  PRESA_MAP.forEach(item => {
    const badgeEl = document.getElementById(item.badgeId);
    const btnEl = document.getElementById(item.btnId) || badgeEl?.closest('button');
    if (!badgeEl || !btnEl) return;

    const stockItem = stockSummary[item.key];
    const stock = stockItem ? Number(stockItem.stock) : 0;

    if (stock <= 0) {
      // 1. Set HTML disabled attribute and ARIA state
      btnEl.disabled = true;
      btnEl.setAttribute('aria-disabled', 'true');

      // 2. Visual disabled styling
      btnEl.classList.add('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
      btnEl.classList.remove('active:scale-95');

      // 3. Explicit exhaustion text
      badgeEl.textContent = '❌ Agotado (0 listas)';
      badgeEl.className = 'text-[11px] text-red-400 font-bold';
    } else {
      // Re-enable when stock is replenished
      btnEl.disabled = false;
      btnEl.removeAttribute('aria-disabled');

      btnEl.classList.remove('opacity-50', 'cursor-not-allowed', 'pointer-events-none');
      btnEl.classList.add('active:scale-95');

      badgeEl.textContent = `Quedan ${stock} listas`;
      badgeEl.className = `text-[11px] ${item.colorClass} font-bold`;
    }
  });
}
```

#### 3. Strict Guard in `confirmPresaChoice(presa)`
```javascript
function confirmPresaChoice(presa) {
  if (!presa || !pendingPresaProduct) {
    closePresaModal();
    return;
  }

  const presaKey = `${presa.trim().toLowerCase()}_vitrina`;
  const currentStock = (stockSummary[presaKey] && typeof stockSummary[presaKey].stock === 'number')
    ? stockSummary[presaKey].stock
    : 0;

  // STRICT GUARD: Refuse to select an exhausted presa under any circumstance
  if (currentStock <= 0) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]); // Haptic alert
    alert(`La presa seleccionada (${presa}) se encuentra agotada en vitrina térmica. Por favor seleccione otra presa.`);
    updateStockBadgesInModal();
    return; // Abort: do NOT add to cart; do NOT close modal
  }

  // Secondary Guard: check whether cart already contains all available units
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

function getSkuForPresa(presa) {
  const map = { 'Pechuga': 'POL-PEC', 'Muslo': 'POL-MUS', 'Contramuslo': 'POL-CON', 'Ala': 'POL-ALA' };
  return map[presa] || null;
}
```

#### 4. Defensive Guard in `openPresaModal()`
If all 4 presas are exhausted, inform cashier immediately rather than showing a dead modal:
```javascript
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
```

---

### Component C: `renderProducts()` Architecture and Product Disabling

#### 1. Universal Stock Calculator Helper
```javascript
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
```

#### 2. Enhanced `renderProducts()` Implementation
```javascript
function renderProducts() {
  const grid = document.getElementById('productsGrid');
  grid.innerHTML = '';

  const filtered = currentCategory === 'todos' 
    ? allProducts 
    : allProducts.filter(p => p.category === currentCategory);

  filtered.forEach(p => {
    const stockInfo = getProductStockInfo(p, stockSummary);
    const card = document.createElement('button');
    const baseClasses = "touch-card p-3 rounded-2xl border text-left flex flex-col justify-between shadow-md transition-all relative group";

    if (!stockInfo.isAvailable) {
      // Disabled button styling
      card.className = `${baseClasses} bg-slate-900/60 border-slate-800 opacity-50 cursor-not-allowed`;
      card.disabled = true;
      card.setAttribute('aria-disabled', 'true');
      card.onclick = (e) => {
        e.preventDefault();
        if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
        alert(`El producto "${p.name}" está agotado en inventario.`);
      };
    } else {
      // Active interactive styling
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
```

#### 3. Defensive Guard on `onProductClick()`
```javascript
function onProductClick(product) {
  const stockInfo = getProductStockInfo(product, stockSummary);
  if (!stockInfo.isAvailable || stockInfo.availableStock <= 0) {
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    alert(`El producto "${product.name}" está agotado en inventario.`);
    return;
  }

  if (navigator.vibrate) navigator.vibrate(25);

  if (product.requires_presa_selection) {
    pendingPresaProduct = product;
    openPresaModal();
  } else {
    addToCart(product);
  }
}
```

---

### Component D: Immediate UI Synchronization Lifecycle

1. **Synchronized Initialization**:
   Change `DOMContentLoaded` to await both products and stock before initial render:
   ```javascript
   document.addEventListener('DOMContentLoaded', async () => {
     initClock();
     await Promise.all([loadProducts(), loadStockSummary()]);
     setInterval(loadStockSummary, 15000); // Polling every 15s
   });
   ```
2. **Immediate Post-Checkout Update**:
   Lines 367 in `processCheckout` already invokes `loadStockSummary()`. With the new `renderProducts()` and `updateStockBadgesInModal()` implementations, any product depleted to 0 during that sale immediately disables on the grid and within the modal.
3. **Immediate Post-Cancellation Update**:
   Line 401 in `cancelLastSale` invokes `loadStockSummary()`, immediately un-disabling any previously exhausted products.

---

## 5. Verification Method

To verify these implementation recommendations:
1. **Static Analysis of Template & JS**:
   - Verify all buttons in `#presaChoices` have IDs `btn-presa-pechuga`, `btn-presa-muslo`, `btn-presa-contramuslo`, `btn-presa-ala`.
   - Verify `updateStockBadgesInModal` sets `btnEl.disabled = true`, adds `opacity-50 cursor-not-allowed pointer-events-none`, and sets `badgeEl.textContent = '❌ Agotado (0 listas)'`.
   - Verify `confirmPresaChoice(presa)` contains `if (currentStock <= 0) return;`.
2. **Interactive UI Verification (Browser / DevTools)**:
   - In browser console on `http://127.0.0.1:8000/`:
     ```javascript
     stockSummary['pechuga_vitrina'].stock = 0;
     updateStockBadgesInModal();
     ```
     Inspect `#btn-presa-pechuga`: confirm attribute `disabled` is present, classes `opacity-50 cursor-not-allowed` are present, and text is `❌ Agotado`.
   - Test clicking:
     ```javascript
     confirmPresaChoice('Pechuga');
     ```
     Confirm `cart` does NOT receive any item and modal remains intact with error alert.
   - Test grid cards:
     ```javascript
     renderProducts();
     ```
     Inspect cards with 0 stock (e.g. `POL-PEC`): confirm `disabled` attribute is true, click does not add to cart, and badge displays `🚫 Agotado`.
3. **Test Suite Verification**:
   Execute:
   ```powershell
   pytest
   ```
   Ensure all 112+ backend tests pass with zero regressions.
