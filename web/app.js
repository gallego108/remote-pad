/* =====================================================================
   RemotePad - cliente (celular)
   ---------------------------------------------------------------------
   Traduce gestos de la pantalla tactil en ordenes para el servidor.

   Gestos:
     1 dedo deslizando .......... mover el puntero
     1 toque corto .............. clic izquierdo (dos seguidos = doble clic)
     2 toques con 2 dedos ....... clic derecho
     2 dedos deslizando ......... scroll
     3 dedos tocando ............ clic central
     pulsacion larga ............ arrastrar mientras se mantiene el dedo
     doble toque y deslizar ..... arrastre fijo hasta volver a tocar
   ===================================================================== */
'use strict';

/* ------------------------------------------------------------ elementos */
const $ = (id) => document.getElementById(id);

const el = {
  auth: $('auth'),
  authCard: $('auth-card'),
  pinInput: $('pin-input'),
  authBtn: $('auth-btn'),
  authError: $('auth-error'),
  app: $('app'),
  statusDot: $('status-dot'),
  statusText: $('status-text'),
  statusLatency: $('status-latency'),
  pinBtn: $('pin-btn'),
  pinChip: $('pin-chip'),
  modeBtn: $('mode-btn'),
  pad: $('pad'),
  padHint: $('pad-hint'),
  cursor: $('cursor'),
  dragRing: $('drag-ring'),
  backdrop: $('sheet-backdrop'),
  toast: $('toast'),
};

const sheets = {
  keyboard: $('sheet-keyboard'),
  shortcuts: $('sheet-shortcuts'),
  media: $('sheet-media'),
  presentation: $('sheet-presentation'),
  settings: $('sheet-settings'),
};

/* -------------------------------------------------------------- ajustes */
const DEFAULTS = {
  sensitivity: 1.6,
  scrollSpeed: 1.0,
  accel: true,
  naturalScroll: true,
  tapClick: true,
  dragLock: true,
  haptics: true,
  edgeZones: true,
};

const SETTINGS_KEY = 'remotepad.settings';
const TOKEN_KEY = 'remotepad.token';

let settings = { ...DEFAULTS };
try {
  settings = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
} catch (_) { /* ajustes corruptos: usamos los de fabrica */ }

function saveSettings() {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (_) {}
}

/* --------------------------------------------------------------- estado */
const state = {
  ws: null,
  authorized: false,
  screen: { w: 1920, h: 1200 },
  serverPin: '',
  mode: 'pointer',          // pointer | dragging | locked
  retry: 0,
  retryTimer: null,
  pingTimer: null,
  latency: 0,
  outbox: [],
  wakeLock: null,
};

/* ------------------------------------------------------------ utilidades */
function toast(message, ms = 1600) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.toast.hidden = true; }, ms);
}

function buzz(pattern) {
  if (!settings.haptics || !navigator.vibrate) return;
  try { navigator.vibrate(pattern); } catch (_) {}
}

function setStatus(text, kind) {
  el.statusText.textContent = text;
  el.statusDot.className = 'dot ' + (kind || 'offline');
}

function setMode(mode) {
  if (state.mode === mode) return;
  const previous = state.mode;
  state.mode = mode;

  el.modeBtn.textContent = mode === 'dragging' ? 'Arrastrando'
    : mode === 'locked' ? 'Arrastre fijo' : 'Puntero';
  el.modeBtn.classList.toggle('armed', mode !== 'pointer');
  el.dragRing.hidden = mode === 'pointer';
  el.cursor.classList.toggle('pressed', mode !== 'pointer');

  if (previous === 'pointer' && mode !== 'pointer') {
    buzz(18);
    toast(mode === 'locked' ? 'Arrastre fijo: toca para soltar' : 'Arrastrando…');
  } else if (mode === 'pointer' && previous !== 'pointer') {
    toast('Soltado', 900);
  }
}

function hideHint() {
  el.padHint.classList.add('hidden');
}

/* --------------------------------------------------------- comunicación */
let sequence = 0;

function send(action, data) {
  const frame = JSON.stringify({ a: action, d: data || {}, n: ++sequence });
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(frame);
    return true;
  }
  if (action === 'mouse_click' || action === 'key' || action === 'media') {
    state.outbox.push(frame);
    if (state.outbox.length > 20) state.outbox.shift();
  }
  return false;
}

/* Coordenadas relativas a la ALTURA de la pantalla: la sensibilidad se
   siente igual en cualquier resolucion y el servidor no necesita escalar. */
function deltaUnits(pixels) {
  return (pixels / state.screen.h) * settings.sensitivity;
}

function sendMove(dx, dy) {
  send('mouse_rel_move', { dx: deltaUnits(dx), dy: deltaUnits(dy) });
}

function sendScroll(dx, dy) {
  const natural = settings.naturalScroll ? -1 : 1;
  const factor = 0.02 * settings.scrollSpeed;
  send('mouse_scroll', { dx: dx * factor * natural, dy: dy * factor * natural });
}

function wsUrl() {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
}

function connect() {
  clearTimeout(state.retryTimer);

  let socket;
  try {
    socket = new WebSocket(wsUrl());
  } catch (_) {
    scheduleReconnect();
    return;
  }
  state.ws = socket;

  socket.onopen = () => {
    state.retry = 0;
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      send('auth', { token });
      setStatus('Verificando…', 'pending');
    } else {
      send('auth', { pin: '' });
      setStatus('Sin autorizar', 'pending');
    }
    startPing();
  };

  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (_) { return; }
    handleMessage(message);
  };

  socket.onclose = () => {
    state.authorized = false;
    stopPing();
    setStatus('Desconectado', 'offline');
    setMode('pointer');
    scheduleReconnect();
  };

  socket.onerror = () => { /* onclose se encarga de reconectar */ };
}

function scheduleReconnect() {
  state.retryTimer = setTimeout(connect, Math.min(6000, 700 * ++state.retry));
}

function startPing() {
  stopPing();
  state.pingTimer = setInterval(() => send('ping', { ts: Date.now() }), 5000);
}

function stopPing() {
  clearInterval(state.pingTimer);
  state.pingTimer = null;
}

function handleMessage(message) {
  switch (message.t) {
    case 'ok':
      state.serverPin = message.pin || state.serverPin;
      if (message.status === 'auth') {
        state.authorized = true;
        if (message.token) {
          try { localStorage.setItem(TOKEN_KEY, message.token); } catch (_) {}
        }
        if (Array.isArray(message.screen) && message.screen.length === 2) {
          state.screen = { w: message.screen[0], h: message.screen[1] };
        }
        el.auth.hidden = true;
        el.app.hidden = false;
        el.authError.hidden = true;
        el.authBtn.disabled = false;
        el.pinInput.value = '';
        setStatus('Conectado', 'online');
        hideHint();
        flushOutbox();
        requestWakeLock();
      }
      break;

    case 'auth_required':
      state.authorized = false;
      el.auth.hidden = false;
      el.app.hidden = true;
      setStatus('Esperando PIN', 'pending');
      el.pinInput.focus();
      break;

    case 'auth_fail':
      state.authorized = false;
      try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
      el.auth.hidden = false;
      el.app.hidden = true;
      el.authError.textContent = message.reason || 'PIN incorrecto';
      el.authError.hidden = false;
      el.authBtn.disabled = false;
      el.pinInput.value = '';
      el.pinInput.focus();
      setStatus('PIN incorrecto', 'offline');
      buzz([40, 60, 40]);
      break;

    case 'pin':
      state.serverPin = message.pin;
      el.pinChip.textContent = message.pin;
      break;

    case 'pong':
      if (message.ts) {
        state.latency = Date.now() - message.ts;
        el.statusLatency.textContent = state.latency + ' ms';
      }
      break;

    case 'response':
      if (message.a === 'get_state' && message.d && message.d.pin) {
        state.serverPin = message.d.pin;
        el.pinChip.textContent = message.d.pin;
        toast('PIN actual en la PC: ' + message.d.pin, 2600);
      } else if (message.d && message.d.error) {
        toast('No se pudo: ' + message.d.error);
      }
      break;

    case 'denied':
      toast(message.reason || 'Acción no permitida');
      break;
  }
}

function flushOutbox() {
  if (!state.outbox.length) return;
  const pending = state.outbox;
  state.outbox = [];
  pending.forEach((frame) => {
    try { state.ws.send(frame); } catch (_) {}
  });
}

/* ---------------------------------------------------------------- gestos */
const TAP_MAX_MS = 260;
const TAP_SLOP = 12;
const LONG_PRESS_MS = 380;
const DOUBLE_TAP_MS = 300;
const DOUBLE_TAP_SLOP = 30;
const SCROLL_SLOP = 16;

const gesture = {
  pointers: new Map(),
  startPos: { x: 0, y: 0 },
  startTime: 0,
  startCount: 0,
  moved: 0,
  longPressTimer: null,
  lastTapTime: 0,
  lastTapPos: { x: 0, y: 0 },
  scrollMode: false,
  acc: { x: 0, y: 0 },
  streamTimer: null,
  twoFinger: { start: 0, moved: 0, active: false },
};

function padPoint(event) {
  const rect = el.pad.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function averagePointer() {
  let x = 0, y = 0, n = 0;
  gesture.pointers.forEach((p) => { x += p.x; y += p.y; n++; });
  return n ? { x: x / n, y: y / n } : { x: 0, y: 0 };
}

function moveCursorDot(point) {
  el.cursor.style.left = point.x + 'px';
  el.cursor.style.top = point.y + 'px';
}

function onPointerDown(event) {
  if (event.pointerType === 'mouse' && event.button !== 0) return;
  try { el.pad.setPointerCapture(event.pointerId); } catch (_) {}

  const point = padPoint(event);
  gesture.pointers.set(event.pointerId, { x: point.x, y: point.y });
  hideHint();
  moveCursorDot(point);
  el.cursor.classList.add('visible');

  const count = gesture.pointers.size;

  if (count === 1) {
    gesture.startPos = { x: point.x, y: point.y };
    gesture.startTime = performance.now();
    gesture.startCount = 1;
    gesture.moved = 0;
    gesture.scrollMode = false;
    gesture.acc.x = 0;
    gesture.acc.y = 0;
    startStreaming();
    if (state.mode === 'pointer') armLongPress();
  } else {
    cancelLongPress();
    if (count === 2) {
      gesture.startCount = Math.max(gesture.startCount, 2);
      stopStreaming();
      gesture.scrollMode = false;
      gesture.acc.x = 0;
      gesture.acc.y = 0;
      gesture.twoFinger = { start: performance.now(), moved: 0, active: true };
    } else {
      gesture.startCount = Math.max(gesture.startCount, count);
      stopStreaming();
      gesture.twoFinger.active = false;
      gesture.scrollMode = false;
    }
  }
}

function armLongPress() {
  cancelLongPress();
  gesture.longPressTimer = setTimeout(() => {
    if (gesture.pointers.size !== 1) return;
    if (gesture.moved > TAP_SLOP) return;
    startLeftDrag();
    setMode('dragging');
  }, LONG_PRESS_MS);
}

function cancelLongPress() {
  clearTimeout(gesture.longPressTimer);
  gesture.longPressTimer = null;
}

/* --------------------------------------------------------- botón izquierdo */
function startLeftDrag() {
  send('mouse_down', { button: 'left' });
}

function releaseLeft() {
  send('mouse_up', { button: 'left' });
}

/* --------------------------------------------------------------- mover */
function onPointerMove(event) {
  const tracked = gesture.pointers.get(event.pointerId);
  if (!tracked) return;

  const point = padPoint(event);
  const dx = point.x - tracked.x;
  const dy = point.y - tracked.y;
  tracked.x = point.x;
  tracked.y = point.y;
  moveCursorDot(point);

  const count = gesture.pointers.size;

  if (count === 1) {
    const dist = Math.hypot(point.x - gesture.startPos.x, point.y - gesture.startPos.y);
    gesture.moved = Math.max(gesture.moved, dist);
    if (gesture.moved > TAP_SLOP) cancelLongPress();

    let factor = 1;
    if (settings.edgeZones) {
      const w = el.pad.clientWidth, h = el.pad.clientHeight;
      const edge = Math.min(w, h) * 0.16;
      const near = Math.min(point.x, w - point.x, point.y, h - point.y);
      if (near < edge && near > 0) factor = 1 + (1 - near / edge) * 0.9;
    }

    gesture.acc.x += dx * factor;
    gesture.acc.y += dy * factor;
    return;
  }

  // --- dos o mas dedos
  if (!gesture.scrollMode) {
    gesture.twoFinger.moved += Math.hypot(dx, dy);
    if (gesture.twoFinger.moved > SCROLL_SLOP) {
      gesture.scrollMode = true;
      gesture.acc.x = 0;
      gesture.acc.y = 0;
      if (state.mode !== 'pointer') {   // arrastrando + scroll = soltar
        releaseLeft();
        setMode('pointer');
      }
    }
  }
  if (gesture.scrollMode) {
    gesture.acc.x += dx;
    gesture.acc.y += dy;
    startStreaming();
  }
}

function onPointerUp(event) {
  const tracked = gesture.pointers.get(event.pointerId);
  if (!tracked) return;

  const point = padPoint(event);
  gesture.pointers.delete(event.pointerId);
  cancelLongPress();
  el.cursor.classList.remove('visible');

  const heldMs = performance.now() - gesture.startTime;
  const totalMoved = Math.max(
    gesture.moved,
    Math.hypot(point.x - gesture.startPos.x, point.y - gesture.startPos.y)
  );
  const wasScroll = gesture.scrollMode;
  const wasTap = !wasScroll && totalMoved <= TAP_SLOP && heldMs <= TAP_MAX_MS;
  const remaining = gesture.pointers.size;

  if (remaining === 0) {
    pump();                 // vaciamos lo que quede pendiente
    stopStreaming();
  }

  // ------------------------------------------------ soltar arrastre activo
  if (state.mode === 'dragging') {
    if (remaining === 0 || wasScroll) {
      releaseLeft();
      setMode('pointer');
    }
    gesture.scrollMode = false;
    return;
  }

  // ------------------------------------------- toque para salir del arrastre fijo
  if (state.mode === 'locked') {
    if (remaining === 0 && wasTap) {
      releaseLeft();
      setMode('pointer');
    }
    gesture.scrollMode = false;
    return;
  }

  // ------------------------------------------------------- gestos con 2 dedos
  if (gesture.twoFinger.active && remaining <= 1) {
    const twoMs = performance.now() - gesture.twoFinger.start;
    const twoTap = !wasScroll && twoMs < 320 && gesture.twoFinger.moved <= SCROLL_SLOP;
    gesture.twoFinger.active = false;
    gesture.scrollMode = false;
    if (twoTap && remaining === 0) {
      send('mouse_click', { button: 'right', clicks: 1 });
      buzz(14);
      return;
    }
  }

  if (remaining > 0) {
    gesture.scrollMode = false;
    return;
  }

  gesture.scrollMode = false;

  // --------------------------------------------------------- gesto de 3 dedos
  if (gesture.startCount >= 3 && wasTap) {
    send('mouse_click', { button: 'middle', clicks: 1 });
    buzz(14);
    return;
  }

  // ------------------------------------------------------------ toque simple
  if (!wasTap || !settings.tapClick) return;

  const now = performance.now();
  const isDouble = settings.dragLock
    && now - gesture.lastTapTime < DOUBLE_TAP_MS
    && Math.hypot(point.x - gesture.lastTapPos.x, point.y - gesture.lastTapPos.y) < DOUBLE_TAP_SLOP;

  if (isDouble) {
    // No esperamos los 300 ms del doble clic: enviamos ya el segundo clic
    // (Windows lo interpreta como doble) y dejamos el arrastre fijo armado.
    send('mouse_click', { button: 'left', clicks: 1 });
    buzz([12, 40, 12]);
    gesture.lastTapTime = 0;
    state.mode = 'locked';
    setMode('locked');
    return;
  }

  send('mouse_click', { button: 'left', clicks: 1 });
  buzz(10);
  gesture.lastTapTime = now;
  gesture.lastTapPos = { x: point.x, y: point.y };
}

function onPointerCancel(event) {
  gesture.pointers.delete(event.pointerId);
  cancelLongPress();
  stopStreaming();
  gesture.scrollMode = false;
  gesture.twoFinger.active = false;
  if (state.mode !== 'pointer') { releaseLeft(); setMode('pointer'); }
  el.cursor.classList.remove('visible');
}

/* --------------------------------------------- envío a ritmo constante */
function startStreaming() {
  if (gesture.streamTimer) return;
  gesture.streamTimer = setInterval(pump, 16);
}

function stopStreaming() {
  clearInterval(gesture.streamTimer);
  gesture.streamTimer = null;
}

function pump() {
  const { x, y } = gesture.acc;
  if (!x && !y) return;
  gesture.acc.x = 0;
  gesture.acc.y = 0;

  if (gesture.scrollMode) {
    sendScroll(x, y);
    return;
  }

  let dx = x, dy = y;
  if (settings.accel) {
    const speed = Math.hypot(x, y);
    const boost = 1 + Math.min(1.1, speed / 34);
    dx *= boost;
    dy *= boost;
  }
  sendMove(dx, dy);
}
/* ------------------------------------------------------------------- UI */
function openSheet(name) {
  closeSheets();
  const sheet = sheets[name];
  if (!sheet) return;
  sheet.hidden = false;
  el.backdrop.hidden = false;
  if (name === 'keyboard') {
    const area = $('kb-text');
    area.value = '';
    area.focus();
  }
  if (name === 'settings') refreshSettingsUI();
}

function closeSheets() {
  Object.values(sheets).forEach((sheet) => { sheet.hidden = true; });
  el.backdrop.hidden = true;
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
}

function refreshSettingsUI() {
  $('s-speed').value = settings.sensitivity;
  $('v-speed').textContent = settings.sensitivity.toFixed(1) + '×';
  $('s-scroll').value = settings.scrollSpeed;
  $('v-scroll').textContent = settings.scrollSpeed.toFixed(1) + '×';
  $('s-accel').checked = settings.accel;
  $('s-natural').checked = settings.naturalScroll;
  $('s-tap').checked = settings.tapClick;
  $('s-draglock').checked = settings.dragLock;
  $('s-haptics').checked = settings.haptics;
  $('s-edges').checked = settings.edgeZones;
  $('about').textContent =
    `Pantalla: ${state.screen.w}×${state.screen.h} px · latencia ${state.latency} ms`;
}

/* ------------------------------------------------------ teclado remoto */
function bindTyping() {
  const area = $('kb-text');
  let previous = '';

  area.addEventListener('input', () => {
    const value = area.value;
    if (value.length >= previous.length && value.startsWith(previous)) {
      send('key_type', { text: value.slice(previous.length) });
    } else if (value.length < previous.length && previous.startsWith(value)) {
      const removed = Math.min(previous.length - value.length, 40);
      send('key_type', { text: '\b'.repeat(removed) });
    } else {
      let shared = 0;
      while (shared < value.length && shared < previous.length
             && value[shared] === previous[shared]) shared++;
      const tail = Math.min(previous.length - shared, 40);
      send('key_type', { text: '\b'.repeat(tail) + value.slice(shared) });
    }
    previous = value;
  });

  area.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send('key', { key: 'enter', mods: [] });
      previous = area.value;
    }
  });
}

/* --------------------------------------------------------------- hotkeys */
/* Los atajos se definen en el HTML con data-hotkey / data-mods / data-combo. */

/* -------------------------------------------------------------- eventos */
function bindUI() {
  // --- autorización
  el.authCard.addEventListener('submit', (event) => {
    event.preventDefault();
    const pin = el.pinInput.value.replace(/\D/g, '');
    if (pin.length !== 6) {
      el.authError.textContent = 'El PIN tiene 6 dígitos';
      el.authError.hidden = false;
      return;
    }
    el.authBtn.disabled = true;
    el.authError.hidden = true;
    el.pinInput.blur();
    send('auth', { pin });
    setStatus('Verificando…', 'pending');
  });

  el.pinInput.addEventListener('input', () => {
    el.pinInput.value = el.pinInput.value.replace(/\D/g, '').slice(0, 6);
    if (el.pinInput.value.length === 6) el.authBtn.click();
  });

  el.pinBtn.addEventListener('click', () => { send('get_state', {}); });

  el.modeBtn.addEventListener('click', () => {
    if (state.mode === 'pointer') {
      startLeftDrag();
      setMode('locked');
    } else {
      releaseLeft();
      setMode('pointer');
    }
  });

  // --- touchpad
  el.pad.addEventListener('pointerdown', onPointerDown);
  el.pad.addEventListener('pointermove', onPointerMove);
  el.pad.addEventListener('pointerup', onPointerUp);
  el.pad.addEventListener('pointercancel', onPointerCancel);
  el.pad.addEventListener('contextmenu', (event) => event.preventDefault());
  el.pad.addEventListener('gesturestart', (event) => event.preventDefault());

  // --- botones rápidos
  document.querySelectorAll('[data-quick]').forEach((button) => {
    button.addEventListener('click', () => {
      const action = button.dataset.quick;
      if (action === 'click') { send('mouse_click', { button: 'left', clicks: 1 }); buzz(12); }
      if (action === 'right') { send('mouse_click', { button: 'right', clicks: 1 }); buzz(12); }
      if (action === 'dump') {
        releaseLeft();
        setMode('pointer');
        send('mouse_release_all', {});
        toast('Botones liberados');
      }
      if (action === 'reset') {
        toast('Reconectando…');
        try { state.ws.close(); } catch (_) {}
        connect();
      }
    });
  });

  // --- paneles
  document.querySelectorAll('[data-panel]').forEach((button) => {
    button.addEventListener('click', () => openSheet(button.dataset.panel));
  });
  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', closeSheets);
  });
  el.backdrop.addEventListener('click', closeSheets);

  // --- teclas sueltas
  document.querySelectorAll('[data-key]').forEach((button) => {
    button.addEventListener('click', () => {
      send('key', { key: button.dataset.key, mods: [] });
      buzz(10);
    });
  });

  // --- atajos
  document.querySelectorAll('[data-hotkey]').forEach((button) => {
    button.addEventListener('click', () => {
      const base = button.dataset.hotkey;
      const extras = (button.dataset.mods || '').split(' ').filter(Boolean);
      const combo = button.dataset.combo || '';
      const main = base === 'win' ? 'cmd' : base;

      if (main === 'ctrl' && extras.includes('alt') && combo === 'delete') {
        toast('Windows bloquea Ctrl+Alt+Supr por seguridad', 2600);
        return;
      }

      if (combo) {
        send('key', { key: combo, mods: [main, ...extras] });
      } else {
        send('key', { key: main, mods: extras });
      }
      buzz(10);
    });
  });

  // --- multimedia
  document.querySelectorAll('[data-media]').forEach((button) => {
    button.addEventListener('click', () => {
      send('media', { action: button.dataset.media });
      buzz(10);
    });
  });
  document.querySelectorAll('[data-volume]').forEach((button) => {
    button.addEventListener('click', () => {
      send('media_volume', { steps: Number(button.dataset.volume) });
      buzz(10);
    });
  });

  // --- presentaciones
  document.querySelectorAll('[data-pres]').forEach((button) => {
    button.addEventListener('click', () => {
      send('presentation', { action: button.dataset.pres });
      buzz(10);
    });
  });

  // --- ajustes
  const bindRange = (id, labelId, key) => {
    const input = $(id);
    input.addEventListener('input', () => {
      settings[key] = Number(input.value);
      $(labelId).textContent = Number(input.value).toFixed(1) + '×';
      saveSettings();
    });
  };
  bindRange('s-speed', 'v-speed', 'sensitivity');
  bindRange('s-scroll', 'v-scroll', 'scrollSpeed');

  const bindSwitch = (id, key) => {
    const input = $(id);
    input.addEventListener('change', () => {
      settings[key] = input.checked;
      saveSettings();
    });
  };
  bindSwitch('s-accel', 'accel');
  bindSwitch('s-natural', 'naturalScroll');
  bindSwitch('s-tap', 'tapClick');
  bindSwitch('s-draglock', 'dragLock');
  bindSwitch('s-haptics', 'haptics');
  bindSwitch('s-edges', 'edgeZones');

  $('btn-fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) { toast('Tu navegador no permite pantalla completa'); }
  });

  $('btn-logout').addEventListener('click', () => {
    try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
    state.authorized = false;
    closeSheets();
    toast('Dispositivo olvidado: pide el PIN de nuevo', 2400);
    try { state.ws.close(); } catch (_) {}
  });

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSheets();
  });

  // Si el navegador pasa a segundo plano con un arrastre activo, soltamos.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (state.mode !== 'pointer') { releaseLeft(); setMode('pointer'); }
      if (state.authorized) requestWakeLock();
    }
  });

  window.addEventListener('pagehide', () => {
    if (state.mode !== 'pointer') releaseLeft();
  });
}

/* ------------------------------------------------------------ wake lock */
async function requestWakeLock() {
  if (!('wakeLock' in navigator) || state.wakeLock) return;
  try {
    state.wakeLock = await navigator.wakeLock.request('screen');
    state.wakeLock.addEventListener('release', () => { state.wakeLock = null; });
  } catch (_) { /* el navegador puede denegarlo: no es critico */ }
}

/* ---------------------------------------------------------- acceso por QR */
/**
 * Si se llega desde el codigo QR, la direccion trae una clave de un solo uso.
 * Se canjea por un token y se limpia la barra de direcciones, para que el
 * enlace no quede en el historial ni se pueda reutilizar.
 */
async function qrLogin() {
  const params = new URLSearchParams(location.search);
  const key = params.get('k');
  if (!key) return false;

  try {
    history.replaceState(null, '', location.pathname);
  } catch (_) { /* algunos navegadores no lo permiten */ }

  try {
    const response = await fetch('api/qr-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const data = await response.json();
    if (data && data.ok && data.token) {
      try { localStorage.setItem(TOKEN_KEY, data.token); } catch (_) {}
      return true;
    }
    el.authError.textContent =
      'El código QR ya se usó o caducó. Escanea el que muestra la PC ahora.';
    el.authError.hidden = false;
  } catch (_) {
    el.authError.textContent =
      'No se pudo usar el código QR. Escribe el PIN que muestra la PC.';
    el.authError.hidden = false;
  }
  return false;
}

/* ------------------------------------------------------------- arranque */
async function init() {
  bindUI();
  bindTyping();
  await qrLogin();
  connect();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

init();
