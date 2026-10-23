# Handoff Report: Tablet Touch Ergonomics, Cumulative Fast Cash & Digital Payment Modal (Milestone M2)

**Agent**: Explorer M2-3  
**Working Directory**: `c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_m2_3\`  
**Target Files**: `app/templates/index.html`, `app/static/js/pos.js`, `app/static/css/style.css`  
**Related Endpoints**: `app/routers/pos.py` (`POST /api/pos/checkout`, `sales.notes`)  
**Status**: Investigation Complete — Read-Only Architecture & Implementation Strategy  

---

## 1. Observation

Direct forensic inspection of the codebase revealed three primary usability, operational, and financial risks in the Point of Sale interface:

### 1.1 Stepper Buttons & Comanda Touch Targets
- **Location**: `app/static/js/pos.js:251-265` within `renderCart()`:
  ```javascript
  <!-- Controles Stepper Grande Táctil -->
  <div class="flex items-center space-x-1.5 bg-slate-900 p-1 rounded-xl border border-slate-700">
    <button onclick="decrementItem(${idx})" class="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-black text-sm flex items-center justify-center active:scale-90 transition">
      -
    </button>
    <span class="w-6 text-center font-black text-xs text-slate-100 tabular-nums">${it.quantity}</span>
    <button onclick="incrementItem(${idx})" class="w-8 h-8 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-sm flex items-center justify-center active:scale-90 transition">
      +
    </button>
  </div>

  <button onclick="removeItem(${idx})" class="ml-2 text-slate-500 hover:text-red-400 p-1.5 rounded-lg active:scale-90 transition" title="Eliminar">
    🗑️
  </button>
  ```
- **Observed Metrics**:
  - `w-8 h-8` in Tailwind CSS resolves to `2rem` = `32px × 32px`.
  - The item quantity `<span>` is `w-6` (`24px`), styled with `text-xs` (`12px`).
  - The delete button `removeItem` has only `p-1.5` padding around an emoji icon, resulting in a touch target of approximately `28px × 28px`.
  - Both stepper buttons and the delete button fall far short of standard tablet ergonomics (`>= 44px × 44px` / Apple HIG 44pt, Google Material 48dp, WCAG 2.1 AAA 2.5.5). In a fast-paced fried chicken restaurant environment where cashiers operate touchscreens with greasy fingers or under rapid queue throughput, 32px targets cause high mis-tap frequency.

### 1.2 Fast Cash Buttons in `#cashModal`
- **Location**: `app/templates/index.html:233-240`:
  ```html
  <!-- Botones de billetes comunes -->
  <div class="grid grid-cols-3 gap-2">
    <button onclick="setCashAmount(10000)" class="py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 border border-slate-700">$10.000</button>
    <button onclick="setCashAmount(20000)" class="py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 border border-slate-700">$20.000</button>
    <button onclick="setCashAmount(50000)" class="py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 border border-slate-700">$50.000</button>
    <button onclick="setCashAmount(100000)" class="py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 border border-slate-700">$100.000</button>
    <button onclick="setExactCash()" class="col-span-2 py-2 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-xs font-black border border-amber-500/40">Pago Exacto</button>
  </div>
  ```
- **Location**: `app/static/js/pos.js:304-313`:
  ```javascript
  function setCashAmount(val) {
    document.getElementById('cashReceivedInput').value = val;
    updateChangeCalculation();
  }

  function setExactCash() {
    const total = cart.reduce((sum, it) => sum + (it.product.price * it.quantity), 0);
    document.getElementById('cashReceivedInput').value = total;
    updateChangeCalculation();
  }
  ```
- **Observed Deficiencies**:
  - `setCashAmount(val)` performs a destructive overwrite (`input.value = val`). If a customer pays with a $50,000 bill and a $10,000 bill, tapping `$50.000` then `$10.000` resets the input to `10000` instead of accumulating to `60000`.
  - There is NO "Limpiar" / reset button. If the cashier taps an incorrect button, they must manually select the input and backspace digits.
  - Buttons have `py-2` padding (~32px height), violating the 44px minimum target.
  - Button labels (`$10.000`) lack a cumulative indicator (`+`), creating ambiguity about button behavior.

### 1.3 Digital Payment Trigger Flow
- **Location**: `app/static/js/pos.js:284-288`:
  ```javascript
    if (method === 'efectivo') {
      openCashModal(total);
    } else {
      // Pago digital directo (Nequi, Daviplata, Datáfono)
      processCheckout(method, total);
    }
  ```
- **Observed Deficiencies**:
  - Tapping `NEQUI/DAVI` or `DATÁFONO` on the sidebar initiates immediate checkout with 1 touch.
  - No confirmation dialog is presented. If the cashier brushes the button unintentionally or taps it while aiming for another control, the sale is finalized immediately in the database, reducing stock and issuing a sale code.
  - The cashier cannot verify receipt of transfer or electronic voucher confirmation before committing inventory.
  - The voucher / authorization code input is completely absent from the UI, even though `app/routers/pos.py:19,233-238` accepts `notes: Optional[str]` and records it in `sales.notes` (verified by `test_digital_payment_notes_reference_stored` in `tests/test_tier1_features.py:537-549`).
  - In line 286, `processCheckout(method, total)` passes `total` as `cash_received`, which is semantically inconsistent for digital payments (should be 0 cash received).

---

## 2. Logic Chain

1. **Touch Ergonomics**:
   - The comanda sidebar has a fixed width of `w-96` (`384px`).
   - The inner list area has 340px usable width per row.
   - Increasing stepper buttons from `w-8 h-8` (32px) to `w-11 h-11` (44px) increases touch area by +89% (`1936 px²` vs `1024 px²`).
   - Expanding the stepper container width to ~135px and the delete button to `w-11 h-11` (44px) leaves ~160px for product name, presa subtitle, and subtotal. This fits without wrapping or breaking the 384px aside column.
   - Setting `user-select: none` (`select-none`) and `touch-action: manipulation` prevents accidental text selection or double-tap zoom delay on tablet touch events.

2. **Cumulative Cash Register Model**:
   - In Colombian fast-food operations, transactions are dominated by cash combinations (e.g. $50k + $20k, $50k + $10k, $20k + $20k).
   - A cumulative function `addCashAmount(val)` that reads `parseInt(input.value) || 0` and adds `val` allows natural sequential entry: tapping `$50.000` then `$10.000` evaluates to `60000`.
   - Prefixing button labels with `+` (`+$10.000`, `+$20.000`, `+$50.000`, `+$100.000`) provides clear visual affordance.
   - Adding a dedicated `Limpiar` button (`clearCashAmount()`) provides instant 1-touch error recovery.
   - Retaining `setExactCash()` guarantees zero change calculation for exact tender.
   - Arranging 6 buttons in a 3-column × 2-row grid with `h-11` (`44px`) maintains perfect rectangular symmetry and satisfies `>= 44px` touch ergonomics.

3. **Digital Payment Confirmation Flow**:
   - Accidental clicks on digital payment triggers create phantom sales and deplete inventory.
   - Introducing an intermediate modal (`#digitalModal`) enforces a two-step confirmation pattern:
     1. Modal opens displaying the exact order total and dynamic method badge (`Nequi/Daviplata` or `Datáfono`).
     2. An explicit reminder instructs the cashier to verify the phone notification or card slip.
     3. An optional voucher input (`#digitalVoucherInput`) allows capturing reference numbers (e.g., `M984723` or voucher authorization numbers).
     4. Two distinct touch buttons (`>= 44px` height): "Cancelar" (dismisses without action) and "Confirmar" (submits checkout with `notes`).
   - For digital checkouts, `cash_received` is passed as `0`, and the voucher reference is sent as `notes: "Comprobante: " + voucher` (or plain voucher), matching backend expectations in `test_digital_payment_notes_reference_stored`.

---

## 3. Implementation Recommendations (Ready for Implementer)

### Recommendation 1: Stepper and Cart Touch Target Resizing

**File**: `app/static/js/pos.js` (lines 251-265)

Replace the stepper HTML inside `renderCart()` with:
```javascript
      <!-- Controles Stepper Grande Táctil (>= 44x44px) -->
      <div class="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-700/80 shadow-inner">
        <button type="button" onclick="decrementItem(${idx})" class="w-11 h-11 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Disminuir">
          -
        </button>
        <span class="w-8 text-center font-black text-sm text-slate-100 tabular-nums select-none">${it.quantity}</span>
        <button type="button" onclick="incrementItem(${idx})" class="w-11 h-11 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-lg flex items-center justify-center active:scale-90 transition select-none shadow-sm touch-manipulation" title="Aumentar">
          +
        </button>
      </div>

      <!-- Botón Eliminar Ítem Grande Táctil (>= 44x44px) -->
      <button type="button" onclick="removeItem(${idx})" class="w-11 h-11 ml-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 font-bold text-base flex items-center justify-center active:scale-90 transition select-none touch-manipulation" title="Eliminar ítem">
        🗑️
      </button>
```

**File**: `app/static/css/style.css`

Add utility classes for tablet touch targets and manipulation:
```css
/* Ergonomía táctil para tablet */
.touch-target-44 {
  min-width: 44px;
  min-height: 44px;
}

.touch-manipulation {
  touch-action: manipulation;
  user-select: none;
  -webkit-user-select: none;
}
```

---

### Recommendation 2: Cumulative Fast Cash Buttons & Limpiar

**File**: `app/templates/index.html` (replace lines 233-241):
```html
        <!-- Botones de billetes acumulativos y utilidades (Grid 3x2, h-11 >= 44px) -->
        <div class="grid grid-cols-3 gap-2">
          <button type="button" onclick="addCashAmount(10000)" class="h-11 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-xs font-bold text-slate-100 border border-slate-700 transition flex items-center justify-center select-none shadow-sm">
            +$10.000
          </button>
          <button type="button" onclick="addCashAmount(20000)" class="h-11 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-xs font-bold text-slate-100 border border-slate-700 transition flex items-center justify-center select-none shadow-sm">
            +$20.000
          </button>
          <button type="button" onclick="addCashAmount(50000)" class="h-11 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-xs font-bold text-slate-100 border border-slate-700 transition flex items-center justify-center select-none shadow-sm">
            +$50.000
          </button>
          <button type="button" onclick="addCashAmount(100000)" class="h-11 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-xs font-bold text-slate-100 border border-slate-700 transition flex items-center justify-center select-none shadow-sm">
            +$100.000
          </button>
          <button type="button" onclick="setExactCash()" class="h-11 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 active:scale-95 text-xs font-black transition flex items-center justify-center select-none shadow-sm">
            🎯 Pago Exacto
          </button>
          <button type="button" onclick="clearCashAmount()" class="h-11 rounded-xl bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/40 active:scale-95 text-xs font-bold transition flex items-center justify-center space-x-1 select-none shadow-sm">
            <span>🗑️</span>
            <span>Limpiar</span>
          </button>
        </div>
```

**File**: `app/static/js/pos.js` (replace lines 304-331):
```javascript
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
```

---

### Recommendation 3: Digital Payment Confirmation Modal (`#digitalModal`)

**File**: `app/templates/index.html` (add around line 252, immediately after `#cashModal`):
```html
  <!-- MODAL DE CONFIRMACIÓN DE PAGO DIGITAL (NEQUI/DAVIPLATA / DATÁFONO) -->
  <div id="digitalModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl max-w-sm w-full p-5 shadow-2xl space-y-4 animate-scale-up">
      <!-- Encabezado con método dinámico -->
      <div class="flex items-center justify-between border-b border-slate-800 pb-2">
        <h3 id="digitalModalTitle" class="font-black text-base text-purple-400 flex items-center space-x-2">
          <span id="digitalModalIcon">📲</span>
          <span id="digitalModalTitleText">Confirmar Pago Digital</span>
        </h3>
        <button type="button" onclick="closeDigitalModal()" class="text-slate-400 hover:text-white font-bold text-lg w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-800 select-none">&times;</button>
      </div>

      <div class="space-y-3">
        <!-- Indicador de Método y Monto -->
        <div class="bg-slate-800 p-3 rounded-xl border border-slate-700 space-y-1">
          <div class="flex justify-between items-center">
            <span class="text-xs text-slate-400 font-bold">Método:</span>
            <span id="digitalModalBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 font-bold border border-purple-500/30">Nequi / Daviplata</span>
          </div>
          <div class="flex justify-between items-center pt-1 border-t border-slate-700/60">
            <span class="text-xs text-slate-400 font-bold">Total a Cobrar:</span>
            <span id="digitalModalTotal" class="text-xl font-black text-amber-400 tabular-nums">$ 0</span>
          </div>
        </div>

        <!-- Alerta de verificación obligatoria para el cajero -->
        <div class="bg-slate-950/70 border border-slate-800 rounded-xl p-3 flex items-start space-x-2.5">
          <span class="text-base text-amber-400 mt-0.5">⚠️</span>
          <p class="text-xs text-slate-300 leading-relaxed font-medium">
            Verifica la notificación en tu teléfono o el comprobante aprobado del datáfono antes de registrar la venta.
          </p>
        </div>

        <!-- Input de comprobante o referencia (Opcional) -->
        <div>
          <label class="block text-xs font-bold text-slate-300 mb-1">
            N° Comprobante / Voucher <span class="text-slate-500 font-normal">(Opcional)</span>:
          </label>
          <input type="text" id="digitalVoucherInput" placeholder="Ej. M123456 o número de aprobación" onkeydown="if(event.key==='Enter') confirmDigitalPayment()" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm font-bold text-slate-100 placeholder-slate-600 focus:outline-none focus:border-purple-500 tracking-wider">
        </div>

        <!-- Botones de Acción (>= 44px altura) -->
        <div class="flex space-x-2 pt-1">
          <button type="button" onclick="closeDigitalModal()" class="w-1/3 h-12 rounded-xl bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 font-bold text-xs border border-slate-700 transition flex items-center justify-center select-none">
            Cancelar
          </button>
          <button type="button" id="btnConfirmDigital" onclick="confirmDigitalPayment()" class="flex-1 h-12 rounded-xl bg-purple-600 hover:bg-purple-500 active:scale-95 text-white font-black text-xs shadow-xl transition flex items-center justify-center select-none">
            CONFIRMAR PAGO
          </button>
        </div>
      </div>
    </div>
  </div>
```

**File**: `app/static/js/pos.js`:
Add state variable and update payment triggers:
```javascript
let pendingDigitalMethod = null;

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
```

Update `processCheckout` signature and payload (replace lines 334-345 in `pos.js`):
```javascript
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
...
```

---

## 4. Caveats

1. **Read-Only Investigation**:
   - In accordance with instruction 4, no code modifications were applied to `app/templates/index.html`, `app/static/js/pos.js`, or `app/static/css/style.css`. All code blocks above are ready drop-in implementations for the Worker agent.
2. **CDN Tailwind vs Local Tailwind Build**:
   - `index.html` loads Tailwind via CDN script (`<script src="https://cdn.tailwindcss.com"></script>`). Tailwind classes such as `w-11`, `h-11`, `h-12`, `active:scale-90`, `tabular-nums` are supported by the runtime script.
3. **Cross-Explorer Integration**:
   - Explorer 1 is designing the disabled states for stock badges in `renderProducts()` and `#presaModal`. Our changes in `pos.js` (`renderCart()`, `handlePayment()`, `openDigitalModal()`, `submitCashPayment()`, `processCheckout()`) do NOT conflict with `renderProducts()` or `updateStockBadgesInModal()`.
   - Explorer 2 is enforcing backend underpayment rejection in `app/routers/pos.py`. Our client-side validations (`rawVal === ''`, `received < total`, and passing `cash_received = 0` for digital) align with Explorer 2's backend `CHECK` and `HTTPException(400)`.

---

## 5. Conclusion

- **Ergonomics**: Increasing stepper and cart item delete buttons to `w-11 h-11` (`44px × 44px`) brings the entire comanda interface into full compliance with tablet touch guidelines without breaking the 384px sidebar layout.
- **Cash Speed & Precision**: Converting fast cash buttons to cumulative addition (`addCashAmount`), adding a "Limpiar" button, and maintaining "Pago Exacto" reflects physical retail payment workflows and eliminates manual digit erasing.
- **Loss Prevention**: The `#digitalModal` eliminates 1-touch accidental checkouts, allows electronic payment verification, and captures optional voucher reference numbers into `sales.notes` for accounting auditability.

---

## 6. Verification Method

To independently verify the implementation after the Worker applies the changes:

1. **Test Suite Execution**:
   ```bash
   pytest
   ```
   Must pass all tests (112+ tests), including `test_payment_nequi_daviplata_success`, `test_payment_datafono_success`, and `test_digital_payment_notes_reference_stored`.

2. **Touch Target Dimensions Verification (DevTools / Headless DOM)**:
   In Chrome DevTools or via JavaScript console on `http://127.0.0.1:8000`:
   ```javascript
   // Add sample product to cart
   addToCart(allProducts[0]);
   const decBtn = document.querySelector('#cartItemsList button');
   const rect = decBtn.getBoundingClientRect();
   console.assert(rect.width >= 44 && rect.height >= 44, `Stepper button target too small: ${rect.width}x${rect.height}`);
   ```

3. **Cumulative Cash Calculation Verification**:
   ```javascript
   openCashModal(30000);
   addCashAmount(50000);
   addCashAmount(10000);
   console.assert(document.getElementById('cashReceivedInput').value === '60000', "Cash did not accumulate to 60000");
   clearCashAmount();
   console.assert(document.getElementById('cashReceivedInput').value === '', "Clear cash failed");
   setExactCash();
   console.assert(document.getElementById('cashReceivedInput').value === '30000', "Exact cash failed");
   ```

4. **Digital Payment Dialog Verification**:
   - Add items to cart.
   - Click `NEQUI/DAVI`: verify `#digitalModal` is visible and `#btnConfirmDigital` has purple styling.
   - Click `Cancelar`: verify `#digitalModal` is hidden and cart is intact.
   - Click `DATÁFONO`: verify `#digitalModal` is visible and `#btnConfirmDigital` has sky-blue styling.
   - Enter voucher `"VOUCHER-TEST-999"` and click `CONFIRMAR VOUCHER`.
   - Verify sale is created and `sales.notes` contains `"Comprobante: VOUCHER-TEST-999"`.
