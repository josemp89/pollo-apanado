/**
 * auth.js - Control de Acceso y Gestión de Usuarios
 * Roles:
 * - 'admin': Dueño / Gerencia (Alejandro) -> Acceso a libro contable, utilidades, compras
 * - 'cajero': Vendedor / Asadero (Santiago) -> Mostrador POS, caja diaria, arqueo de turno
 */

let activeAppUser = null;

function getActiveUser() {
  if (activeAppUser) return activeAppUser;
  try {
    const raw = localStorage.getItem('don_pollo_user');
    if (raw) {
      activeAppUser = JSON.parse(raw);
      return activeAppUser;
    }
  } catch (e) {
    console.warn("Error leyendo don_pollo_user de localStorage", e);
  }
  // Default to Santiago (Vendedor) if not logged in
  activeAppUser = {
    id: 1,
    username: 'santiago',
    display_name: 'Santiago (Vendedor)',
    role: 'cajero'
  };
  localStorage.setItem('don_pollo_user', JSON.stringify(activeAppUser));
  return activeAppUser;
}

function setActiveUser(user) {
  activeAppUser = user;
  localStorage.setItem('don_pollo_user', JSON.stringify(user));
  updateUserUI();
}

function updateUserUI() {
  const user = getActiveUser();
  const labelEl = document.getElementById('navUserLabel');
  const iconEl = document.getElementById('navUserIcon');
  const gerenciaTab = document.getElementById('navGerenciaTab');
  const gerenciaNavBtn = document.getElementById('btnOpenGerencia');

  if (labelEl) {
    labelEl.textContent = user.display_name;
  }
  if (iconEl) {
    iconEl.textContent = user.role === 'admin' ? '👑' : '👤';
  }

  // Si es Admin, mostrar el botón de Gerencia
  const isAdmin = (user.role === 'admin');
  if (gerenciaTab) {
    if (isAdmin) {
      gerenciaTab.classList.remove('hidden');
    } else {
      gerenciaTab.classList.add('hidden');
    }
  }
  if (gerenciaNavBtn) {
    if (isAdmin) {
      gerenciaNavBtn.classList.remove('hidden');
    } else {
      gerenciaNavBtn.classList.add('hidden');
    }
  }
}

async function openUserSwitchModal() {
  let modal = document.getElementById('userSwitchModal');
  if (!modal) {
    createUserSwitchModalDOM();
    modal = document.getElementById('userSwitchModal');
  }

  const listEl = document.getElementById('userSwitchList');
  if (listEl) {
    listEl.innerHTML = '<div class="p-3 text-center text-slate-400">Cargando usuarios...</div>';
  }

  if (modal) modal.classList.remove('hidden');

  try {
    const res = await fetch('/api/auth/users');
    const data = await res.json();
    if (!data.success) throw new Error("Error cargando usuarios");

    const users = data.users || [];
    const current = getActiveUser();

    if (listEl) {
      listEl.innerHTML = users.map(u => {
        const isCurrent = u.username === current.username;
        const borderClass = isCurrent ? "border-amber-500 bg-amber-500/10" : "border-slate-800 bg-slate-950 hover:border-slate-700";
        const icon = u.role === 'admin' ? '👑' : '👤';
        const roleLabel = u.role === 'admin' ? 'Dueño / Gerencia' : 'Vendedor / Asadero';

        return `
          <button type="button" onclick="selectUserToSwitch('${u.username}', '${u.display_name}', '${u.role}')" class="w-full text-left p-3 rounded-xl border ${borderClass} transition flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <span class="text-2xl">${icon}</span>
              <div>
                <div class="font-bold text-white text-xs">${u.display_name}</div>
                <div class="text-[10px] text-slate-400">${roleLabel}</div>
              </div>
            </div>
            ${isCurrent ? '<span class="text-xs font-black text-amber-400">ACTIVO</span>' : '<span class="text-xs text-slate-500">Seleccionar ▶</span>'}
          </button>
        `;
      }).join('');
    }
  } catch (err) {
    if (listEl) listEl.innerHTML = `<div class="p-3 text-center text-red-400">${err.message}</div>`;
  }
}

let pendingSwitchUser = null;

function selectUserToSwitch(username, display_name, role) {
  pendingSwitchUser = { username, display_name, role };
  document.getElementById('switchStep1').classList.add('hidden');
  document.getElementById('switchStep2').classList.remove('hidden');
  document.getElementById('switchPinTargetName').textContent = display_name;
  document.getElementById('switchPinInput').value = '';
  document.getElementById('switchPinError').classList.add('hidden');
}

function cancelSwitchPin() {
  pendingSwitchUser = null;
  document.getElementById('switchStep2').classList.add('hidden');
  document.getElementById('switchStep1').classList.remove('hidden');
}

async function confirmUserSwitch() {
  if (!pendingSwitchUser) return;
  const pin = document.getElementById('switchPinInput').value.trim();
  const errEl = document.getElementById('switchPinError');

  if (!pin) {
    if (errEl) { errEl.textContent = "Ingresa el PIN."; errEl.classList.remove('hidden'); }
    return;
  }

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ username: pendingSwitchUser.username, pin })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "PIN incorrecto");

    setActiveUser(data.user);
    closeUserSwitchModal();
    alert(`✅ Sesión cambiada a: ${data.user.display_name}`);

    // Si cambió a admin y está en una pantalla donde quiera ir a gerencia
    if (data.user.role === 'admin' && window.location.pathname === '/caja') {
      const goToGerencia = confirm("¿Deseas abrir el Libro Contable y Gerencia Financiera ahora?");
      if (goToGerencia) {
        window.location.href = '/gerencia';
      }
    }
  } catch (e) {
    if (errEl) {
      errEl.textContent = e.message || "PIN incorrecto";
      errEl.classList.remove('hidden');
    }
  }
}

function closeUserSwitchModal() {
  const modal = document.getElementById('userSwitchModal');
  if (modal) modal.classList.add('hidden');
  cancelSwitchPin();
}

function createUserSwitchModalDOM() {
  const div = document.createElement('div');
  div.id = 'userSwitchModal';
  div.className = 'fixed inset-0 bg-slate-950/85 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4';
  div.innerHTML = `
    <div class="bg-slate-900 border-2 border-slate-700 rounded-3xl max-w-sm w-full p-5 shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-2.5">
        <h3 class="font-black text-sm text-amber-400 flex items-center space-x-2">
          <span>👥</span>
          <span>Perfiles de Usuario</span>
        </h3>
        <button type="button" onclick="closeUserSwitchModal()" class="text-slate-400 hover:text-white font-bold text-xl select-none">&times;</button>
      </div>

      <!-- Paso 1: Lista de Usuarios -->
      <div id="switchStep1" class="space-y-3">
        <p class="text-xs text-slate-400">Selecciona el perfil que va a operar el sistema:</p>
        <div id="userSwitchList" class="space-y-2"></div>
      </div>

      <!-- Paso 2: PIN de Seguridad -->
      <div id="switchStep2" class="space-y-3 hidden text-center">
        <p class="text-xs text-slate-300">Ingresa el PIN de acceso para:</p>
        <div id="switchPinTargetName" class="font-black text-amber-400 text-sm">Usuario</div>
        <input type="password" id="switchPinInput" maxlength="6" inputmode="numeric" placeholder="••••" class="w-36 mx-auto text-center tracking-widest text-2xl font-black bg-slate-950 border-2 border-amber-500 rounded-xl py-1.5 text-amber-300 focus:outline-none">
        <p id="switchPinError" class="text-xs font-bold text-red-400 hidden"></p>
        <div class="flex space-x-2 pt-2">
          <button type="button" onclick="cancelSwitchPin()" class="w-1/2 h-10 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs">Volver</button>
          <button type="button" onclick="confirmUserSwitch()" class="w-1/2 h-10 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-black text-xs">Confirmar</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(div);
}

document.addEventListener('DOMContentLoaded', () => {
  getActiveUser();
  updateUserUI();
});
