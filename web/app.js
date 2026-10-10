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
  authOpen: $('auth-open'),
  authHint: $('auth-hint'),
  pinLive: $('pin-live'),
  pinLiveValue: $('pin-live-value'),
  app: $('app'),
  statusDot: $('status-dot'),
  statusText: $('status-text'),
  statusLatency: $('status-latency'),
  pinBtn: $('pin-btn'),
  pinChip: $('pin-chip'),
  modeBtn: $('mode-btn'),
  fastBtn: $('fast-btn'),
  laserBtn: $('laser-btn'),
  stripsBtn: $('strips-btn'),
  scrollV: $('scroll-v'),
  scrollH: $('scroll-h'),
  pad: $('pad'),
  padHint: $('pad-hint'),
  cursor: $('cursor'),
  dragRing: $('drag-ring'),
  backdrop: $('sheet-backdrop'),
  toast: $('toast'),
  tutorial: $('tutorial'),
  tutIcon: $('tut-icon'),
  tutStep: $('tut-step'),
  tutTitle: $('tut-title'),
  tutBody: $('tut-body'),
  tutNext: $('tut-next'),
  tutPrev: $('tut-prev'),
  tutSkip: $('tut-skip'),
  awake: $('awake'),
  awakeState: $('awake-state'),
};

const sheets = {
  keyboard: $('sheet-keyboard'),
  shortcuts: $('sheet-shortcuts'),
  media: $('sheet-media'),
  presentation: $('sheet-presentation'),
  gamepad: $('sheet-gamepad'),
  settings: $('sheet-settings'),
  help: $('sheet-help'),
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
  inertia: true,
  threeFinger: true,
  edgeBack: true,
  pinchZoom: true,
  scrollStrips: false,      // franjas para hacer scroll con un dedo
  learnAdaptive: true,      // el servidor aprende tu sensibilidad
  learnTap: true,           // filtro que aprende a exigir mas en el toque de 2
  learnThreshold: true,     // umbral pinza/scroll aprendido de tus gestos
  // Atajos propios, como texto JSON: asi viajan al perfil de la PC (que solo
  // guarda valores simples) y no se pierden al borrar los datos del navegador.
  atajos: '[]',
  mando: '{}',              // teclas del modo mando (JSON, como los atajos)
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

/* Perfil del usuario ------------------------------------------------
   Las preferencias se guardan tambien en la PC (ligadas a este dispositivo),
   asi que no hay que reajustarlas aunque el navegador borre sus datos. */
let perfilTimer = null;

function guardarPerfil() {
  clearTimeout(perfilTimer);
  perfilTimer = setTimeout(() => {
    try { send('save_settings', { settings }); } catch (_) {}
  }, 700);
}

function aplicarPerfil(guardado) {
  if (!guardado || typeof guardado !== 'object') return;
  const limpio = {};
  Object.keys(DEFAULTS).forEach((clave) => {
    if (Object.prototype.hasOwnProperty.call(guardado, clave)) {
      limpio[clave] = guardado[clave];
    }
  });
  if (!Object.keys(limpio).length) return;
  settings = { ...settings, ...limpio };
  saveSettings();
  refreshSettingsUI();
  pintarAtajos();
  pintarMando();
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
  qrDescartado: false,      // el usuario ha decidido escribir el PIN
  tokenDescartado: false,   // ya se reintento sin el token guardado
  detenido: false,          // el servicio se ha detenido (no reconectar)
  authRequired: true,       // la PC pide PIN/QR (lo dice el servidor)
  fast: false,              // modo rapido: el puntero va FAST_FACTOR veces mas
  laser: false,             // puntero laser: la pantalla solo senala
  deviceId: '',             // codigo corto de este dispositivo en la PC
  olvidando: false,         // el usuario pidio "Olvidar este dispositivo"
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

/* El servidor aplica estos valores como PIXELES del PC (los suma a la
   posicion del puntero). Antes se dividian por la altura de la pantalla y
   quedaban en ~0,1, asi que al redondear el puntero no se movia nunca:
   hay que enviar la distancia real recorrida por el dedo, multiplicada por
   la sensibilidad elegida. */
const FAST_FACTOR = 3;   // multiplicador del "modo rapido"

/* El servidor convierte las "unidades" de scroll a clics de rueda con
   UNITS_PER_SCROLL_CLICK = 22. Con el valor antiguo (0,02) hacian falta 1.100
   px de dedo para UN clic: el scroll era practicamente imperceptible. Con 0,45
   una pasada de dedo por el panel mueve varias lineas, y se afina con el
   ajuste "velocidad del scroll". */
const SCROLL_UNITS_PER_PIXEL = 0.45;

function deltaUnits(pixels) {
  const boost = state.fast ? FAST_FACTOR : 1;
  return pixels * settings.sensitivity * boost;
}

function sendMove(dx, dy) {
  send('mouse_rel_move', { dx: deltaUnits(dx), dy: deltaUnits(dy) });
}

function sendScroll(dx, dy) {
  const natural = settings.naturalScroll ? -1 : 1;
  const factor = SCROLL_UNITS_PER_PIXEL * settings.scrollSpeed;
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
      // Sin token guardado: se pregunta a la PC si hace falta codigo de
      // acceso. Si esta desactivado, el servidor autoriza al instante.
      send('auth_query', {});
      setStatus('Conectando…', 'pending');
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
    // La PC ya suelta las teclas al perder la conexion; aqui solo se limpia
    // el estado de los botones para que no se queden marcados.
    mando.dedos.clear();
    mando.cuentas.clear();
    document.querySelectorAll('.mbtn.pulsado').forEach((b) => b.classList.remove('pulsado'));
    stopPing();
    setMode('pointer');
    if (state.detenido) {
      // El servidor avisó de que se detenía: no se reintenta.
      setStatus('Servicio detenido', 'offline');
      return;
    }
    setStatus('Desconectado', 'offline');
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
        if (message.device) state.deviceId = message.device;
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
        // Preferencias guardadas en la PC: se aplican solas al entrar.
        if (message.settings) aplicarPerfil(message.settings);
        // La primera vez, se muestra el tutorial paso a paso.
        try {
          if (!localStorage.getItem(TUTORIAL_KEY)) setTimeout(openTutorial, 800);
        } catch (_) {}
      }
      break;

    case 'auth_required':
      state.authorized = false;
      el.auth.hidden = false;
      el.app.hidden = true;
      setStatus('Esperando PIN', 'pending');
      el.pinInput.focus();
      break;

    case 'auth_state':
      // La PC nos dice si hace falta codigo de acceso.
      state.authRequired = message.required !== false;
      applyAuthMode(message.required !== false, message.pin);
      break;

    case 'auth_mode':
      // Alguien cambio el modo (desde el celular o desde la consola de la PC).
      state.authRequired = message.required !== false;
      applyAuthMode(state.authRequired, message.pin);
      if (state.authRequired) {
        toast('Se ha activado el código de acceso', 3000);
      } else {
        toast('Acceso libre: ya no hace falta código', 3000);
      }
      break;

    case 'auth_fail':
      state.authorized = false;
      const teniaToken = Boolean(localStorage.getItem(TOKEN_KEY));
      try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
      el.auth.hidden = false;
      el.app.hidden = true;
      el.authBtn.disabled = false;
      el.pinInput.value = '';
      setStatus('Sin autorizar', 'pending');

      if (teniaToken && !state.tokenDescartado && qrKeyVigente()) {
        // El token guardado ya no vale, pero la pagina trae un QR vigente:
        // se usa ese en lugar de molestar al usuario.
        state.tokenDescartado = true;
        usarQrDeLaPagina();
        break;
      }
      if (teniaToken && !state.tokenDescartado) {
        // El token guardado ya no vale (el servidor se reinicio o se olvido el
        // dispositivo). Se reintenta sin el para que el servidor pida el PIN
        // en vez de dejarnos en un bucle de "PIN incorrecto".
        state.tokenDescartado = true;
        el.authError.textContent = 'Había un acceso guardado que ya no vale. '
          + 'Se pide de nuevo: escanea el QR o escribe el PIN.';
        el.authError.hidden = false;
        el.pinInput.focus();
        try { state.ws.close(); } catch (_) {}
        connect();
        break;
      }

      el.authError.textContent = message.reason || 'PIN incorrecto';
      el.authError.hidden = false;
      el.pinInput.focus();
      buzz([40, 60, 40]);
      break;

    case 'revoked':
      // La PC ha retirado el acceso de este dispositivo (desde Ajustes de
      // otro celular, desde la consola o con "Olvidar este dispositivo").
      try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
      state.authorized = false;
      closeSheets();
      el.app.hidden = true;
      el.auth.hidden = false;
      el.authError.textContent = state.olvidando
        ? 'Dispositivo olvidado: escanea el QR o escribe el PIN para volver.'
        : 'Se ha retirado el acceso de este dispositivo. Para volver, escanea '
          + 'el QR o escribe el PIN.';
      el.authError.hidden = false;
      state.olvidando = false;
      break;

    case 'device_new':
      // Ha entrado otro dispositivo: si no lo esperabas, puedes quitarlo en
      // Ajustes.
      toast('Nuevo dispositivo con acceso: ' + (message.nombre || '¿?'), 3200);
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
      } else if (message.a === 'set_auth' && message.d) {
        applyAuthMode(message.d.required !== false, message.d.pin);
      } else if (message.a === 'clipboard_get' && message.d) {
        ponerTextoTeclado(message.d.text || '');
        toast((message.d.text || '')
          ? 'Texto traído del PC'
          : 'El PC no tenía nada copiado');
      } else if (message.a === 'learning' && message.d) {
        pintarAprendizaje(message.d);
      } else if ((message.a === 'monitor_list' || message.a === 'monitor_goto')
                 && message.d && !message.d.error) {
        pintarMonitores(message.d);
      } else if ((message.a === 'devices_list' || message.a === 'device_revoke'
                  || message.a === 'set_confirm') && message.d && !message.d.error) {
        pintarDispositivos(message.d);
      } else if (message.d && message.d.error) {
        toast('No se pudo: ' + message.d.error);
      }
      break;

    case 'denied':
      toast(message.reason || 'Acción no permitida');
      break;

    case 'keep_awake':
      // El servidor avisa cuando se cumple el tiempo pedido.
      if (!message.active) {
        awakeHasta = 0;
        if (awakeTimer) { clearInterval(awakeTimer); awakeTimer = null; }
        pintarAwake();
        toast('Anti-apagado terminado (se cumplió el tiempo)', 2600);
      }
      break;

    case 'shutdown':
      // El servidor se está deteniendo: no tiene sentido reconectar.
      state.detenido = true;
      clearTimeout(state.retryTimer);
      stopPing();
      setStatus('Servicio detenido', 'offline');
      closeSheets();
      el.app.hidden = true;
      el.auth.hidden = false;
      el.authError.textContent = 'RemotePad se ha detenido en la PC. '
        + 'Vuelve a iniciarlo con iniciar.bat y escanea el código QR.';
      el.authError.hidden = false;
      el.authBtn.disabled = false;
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
const EDGE_ZONE = 28;        // ancho de la zona de borde (atras/adelante)
const EDGE_TRIGGER = 48;     // recorrido horizontal para dispararlo
const THREE_SLOP = 46;       // recorrido del gesto con 3 dedos
const INERTIA_MIN = 0.35;    // velocidad minima (px/ms) para que haya inercia
const INERTIA_DECAY = 0.9;   // cuanto se frena cada 16 ms

/* Toque con dos dedos = clic derecho. Para que NO salga solo (por rozar la
   pantalla con dos dedos, o por un pulgar apoyado) se exige que los dos dedos:
     - bajen casi a la vez (si uno llevaba rato apoyado, no cuenta),
     - esten separados (un roce del pulgar junto al dedo no cuenta),
     - no muevan el puntero y duren poco,
     - y se levanten tambien casi a la vez.
   Ademas el resultado se decide cuando se levantan AMBOS, asi no depende de
   cual se suelta primero (que era lo que hacia que saliera "a veces".). */
const TWO_FINGER_JOIN_MS = 200;    // maxima diferencia al apoyar los dos dedos
const TWO_FINGER_LIFT_MS = 220;    // maxima diferencia al levantarlos
const TWO_FINGER_MIN_DIST = 35;    // separacion minima entre los dos dedos

/* ------------------------------------------------- aprendizaje en el movil
   Dos cosas que se ajustan solas mirando como usas el movil:

   1) El umbral que separa "scroll" de "pinza". Se guarda la proporcion de cada
      gesto (cuanto se separan los dedos frente a cuanto avanza su punto medio)
      y se buscan los dos grupos con un k-means de 1 dimension. Si los grupos
      estan claros, el umbral se coloca entre ellos.

   2) Lo estricto que hay que ser con el toque de dos dedos. Si un clic derecho
      va seguido de un movimiento, es que ha salido solo: se sube la exigencia.
      Si no mueves nada despues, era lo que querias: se baja poco a poco. */
const RATIOS_KEY = 'remotepad.ratios';
const FIRMEZA_KEY = 'remotepad.firmeza';
const MAX_RATIOS = 40;

let ratios = [];
try {
  const guardados = JSON.parse(localStorage.getItem(RATIOS_KEY) || '[]');
  if (Array.isArray(guardados)) {
    ratios = guardados.filter((valor) => typeof valor === 'number');
  }
} catch (_) { ratios = []; }

let firmeza = 0.5;   // 0 = permisivo, 1 = estricto
try {
  const valor = parseFloat(localStorage.getItem(FIRMEZA_KEY));
  if (!Number.isNaN(valor)) firmeza = Math.max(0, Math.min(1, valor));
} catch (_) { /* se queda en el valor por defecto */ }

const postClic = { movido: 0, timer: null };

function guardarRatios() {
  try { localStorage.setItem(RATIOS_KEY, JSON.stringify(ratios.slice(-MAX_RATIOS))); } catch (_) {}
}

function guardarFirmeza() {
  try { localStorage.setItem(FIRMEZA_KEY, String(firmeza)); } catch (_) {}
}

/** Umbral aprendido entre scroll y pinza (dos grupos, k-means de 1 dimension). */
function umbralPinza() {
  if (!settings.learnThreshold || ratios.length < 12) return 1.0;
  let c1 = 0.15, c2 = 1.4;
  for (let vuelta = 0; vuelta < 8; vuelta++) {
    let suma1 = 0, n1 = 0, suma2 = 0, n2 = 0;
    ratios.forEach((r) => {
      if (Math.abs(r - c1) <= Math.abs(r - c2)) { suma1 += r; n1++; }
      else { suma2 += r; n2++; }
    });
    if (n1) c1 = suma1 / n1;
    if (n2) c2 = suma2 / n2;
  }
  // Si los dos grupos no se separan, mejor no tocar nada.
  if (c2 - c1 < 0.4) return 1.0;
  return Math.max(0.5, Math.min(1.6, (c1 + c2) / 2));
}

/** Umbrales del toque con dos dedos, segun lo estricto que haga falta. */
function umbralesToque() {
  const uso = settings.learnTap ? firmeza : 0.5;
  return {
    join: Math.round(TWO_FINGER_JOIN_MS - 80 * uso),
    lift: Math.round(TWO_FINGER_LIFT_MS - 90 * uso),
    dist: Math.round(TWO_FINGER_MIN_DIST + 30 * uso),
  };
}

/** Acaba de salir un clic derecho: ya se vera si era lo que querias. */
function anotarClicDerecho() {
  if (!settings.learnTap) return;
  clearTimeout(postClic.timer);
  postClic.movido = 0;
  postClic.timer = setTimeout(() => {
    // Paso el tiempo sin mover el puntero: el clic era intencionado.
    firmeza = Math.max(0, firmeza - 0.04);
    guardarFirmeza();
    postClic.movido = 0;
    postClic.timer = null;
  }, 1200);
}

/** Movimiento del puntero: si sigue a un clic derecho, ese clic sobraba. */
function anotarMovimiento(distancia) {
  if (!settings.learnTap || !postClic.timer) return;
  postClic.movido += distancia;
  if (postClic.movido > 30) {
    clearTimeout(postClic.timer);
    postClic.timer = null;
    postClic.movido = 0;
    firmeza = Math.min(1, firmeza + 0.15);
    guardarFirmeza();
    toast('Ajustando el toque con dos dedos…', 1600);
  }
}

function reiniciarAprendizajeLocal() {
  ratios = [];
  firmeza = 0.5;
  guardarRatios();
  guardarFirmeza();
  clearTimeout(postClic.timer);
  postClic.timer = null;
  postClic.movido = 0;
}

function estadoAprendizajeLocal() {
  return {
    gestos: ratios.length,
    umbral: umbralPinza(),
    firmeza,
    umbrales: umbralesToque(),
  };
}

/* Lo que ha aprendido la PC (llega del servidor cuando se le pregunta). */
let aprendizajeServidor = null;

function pintarAprendizaje(datos) {
  if (datos) aprendizajeServidor = datos;
  const caja = $('learning-state');
  if (!caja) return;
  const local = estadoAprendizajeLocal();
  const partes = [];
  const datosPC = aprendizajeServidor;
  if (datosPC && datosPC.activo) {
    const ganancia = Number(datosPC.ganancia || 1).toFixed(2);
    const app = datosPC.app ? ` en ${datosPC.app}` : '';
    partes.push(`PC: ganancia ${ganancia}×${app}`);
    partes.push(`se pasa ${datosPC.excesos || 0} / se queda corto ${datosPC.defectos || 0}`);
  } else if (datosPC) {
    partes.push('PC: aprendizaje desactivado');
  }
  partes.push(`móvil: umbral ${local.umbral.toFixed(2)} (${local.gestos} gestos)`);
  partes.push(`firmeza ${local.firmeza.toFixed(2)}`);
  caja.textContent = partes.join(' · ');
}

const gesture = {
  pointers: new Map(),
  startPos: { x: 0, y: 0 },
  startTime: 0,
  startCount: 0,
  moved: 0,
  longPressTimer: null,
  lastTapTime: 0,
  lastTapPos: { x: 0, y: 0 },
  acc: { x: 0, y: 0 },
  streamTimer: null,
  twoFinger: { start: 0, moved: 0, active: false, mode: '', lastDist: 0 },
  firstDownAt: 0,           // cuando bajo el primer dedo (para el toque de 2)
  pinchAcc: 0,
  edge: '',                 // '', 'left' o 'right'
  edgeFired: false,
  three: { active: false, fired: false, x: 0, y: 0, moved: 0 },
  velocity: { x: 0, y: 0 },
  lastMoveTime: 0,
  inertiaTimer: null,
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

/* Puntero laser: manda la posicion tocada, normalizada (0..1). */
function enviarLaser(point) {
  const rect = el.pad.getBoundingClientRect();
  send('laser', {
    on: true,
    x: point.x / Math.max(1, rect.width),
    y: point.y / Math.max(1, rect.height),
  });
}

function onPointerDown(event) {
  if (event.pointerType === 'mouse' && event.button !== 0) return;
  try { el.pad.setPointerCapture(event.pointerId); } catch (_) {}
  stopInertia();

  const point = padPoint(event);
  gesture.pointers.set(event.pointerId, { x: point.x, y: point.y });
  hideHint();
  moveCursorDot(point);
  el.cursor.classList.add('visible');

  const count = gesture.pointers.size;

  // En modo laser el panel solo senala: no mueve el puntero ni hace clics.
  if (state.laser && count === 1) {
    enviarLaser(point);
    return;
  }

  if (count === 1) {
    gesture.startPos = { x: point.x, y: point.y };
    gesture.startTime = performance.now();
    gesture.firstDownAt = gesture.startTime;
    gesture.startCount = 1;
    gesture.moved = 0;
    gesture.acc.x = 0;
    gesture.acc.y = 0;
    gesture.velocity.x = 0;
    gesture.velocity.y = 0;
    gesture.lastMoveTime = performance.now();
    gesture.edgeFired = false;
    // Zona de borde: deslizar hacia dentro = Atras / Adelante.
    gesture.edge = '';
    if (settings.edgeBack) {
      const ancho = el.pad.clientWidth;
      if (point.x <= EDGE_ZONE) gesture.edge = 'left';
      else if (point.x >= ancho - EDGE_ZONE) gesture.edge = 'right';
    }
    startStreaming();
    if (state.mode === 'pointer' && !gesture.edge) armLongPress();
  } else {
    cancelLongPress();
    if (count === 2) {
      gesture.startCount = Math.max(gesture.startCount, 2);
      stopStreaming();
      gesture.acc.x = 0;
      gesture.acc.y = 0;
      const pts = [...gesture.pointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const ahora = performance.now();
      gesture.twoFinger = {
        start: ahora, moved: 0, stretch: 0, active: true,
        mode: '', lastDist: dist, startDist: dist,
        lastCenter: averagePointer(),
        // Datos para decidir si fue un toque intencionado:
        joined: ahora - gesture.firstDownAt,   // cuanto tardo el 2.o dedo
        dist,                                   // separacion entre los dedos
        liftAt: 0,                              // cuando se levanto el 1.o
        sampled: false,                         // si ya se guardo su "firma"
      };
      gesture.pinchAcc = 0;
    } else {
      gesture.startCount = Math.max(gesture.startCount, count);
      stopStreaming();
      gesture.twoFinger.active = false;
      gesture.twoFinger.mode = '';
      if (count === 3 && settings.threeFinger) {
        const centro = averagePointer();
        gesture.three = {
          active: true, fired: false, x: centro.x, y: centro.y, moved: 0,
        };
      }
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

  if (state.laser && count === 1) {
    enviarLaser(point);
    return;
  }

  if (count === 1) {
    const dist = Math.hypot(point.x - gesture.startPos.x, point.y - gesture.startPos.y);
    gesture.moved = Math.max(gesture.moved, dist);
    if (gesture.moved > TAP_SLOP) cancelLongPress();

    // Gesto de borde: Atras (borde izquierdo) / Adelante (borde derecho).
    if (gesture.edge && !gesture.edgeFired) {
      const avance = point.x - gesture.startPos.x;
      const haciaDentro = gesture.edge === 'left' ? avance : -avance;
      if (haciaDentro > EDGE_TRIGGER) {
        gesture.edgeFired = true;
        gesture.acc.x = 0;
        gesture.acc.y = 0;
        send('key', {
          key: gesture.edge === 'left' ? 'left' : 'right',
          mods: ['alt'],
        });
        toast(gesture.edge === 'left' ? 'Atrás' : 'Adelante');
        buzz(16);
      }
      if (gesture.edgeFired) return;
    }

    // Velocidad reciente, para la inercia al levantar el dedo.
    const ahora = performance.now();
    const dt = Math.max(1, ahora - gesture.lastMoveTime);
    gesture.velocity.x = gesture.velocity.x * 0.6 + (dx / dt) * 0.4;
    gesture.velocity.y = gesture.velocity.y * 0.6 + (dy / dt) * 0.4;
    gesture.lastMoveTime = ahora;

    let factor = 1;
    if (settings.edgeZones) {
      const w = el.pad.clientWidth, h = el.pad.clientHeight;
      const edge = Math.min(w, h) * 0.16;
      const near = Math.min(point.x, w - point.x, point.y, h - point.y);
      if (near < edge && near > 0) factor = 1 + (1 - near / edge) * 0.9;
    }

    gesture.acc.x += dx * factor;
    gesture.acc.y += dy * factor;
    anotarMovimiento(Math.hypot(dx, dy));
    return;
  }

  // --- 3 dedos: arriba/abajo = volumen, izquierda/derecha = cambiar pestana
  if (count >= 3) {
    if (gesture.three.active && !gesture.three.fired) {
      const centro = averagePointer();
      const avanceX = centro.x - gesture.three.x;
      const avanceY = centro.y - gesture.three.y;
      gesture.three.moved += Math.hypot(dx, dy);
      if (Math.abs(avanceY) > THREE_SLOP || Math.abs(avanceX) > THREE_SLOP) {
        gesture.three.fired = true;
        if (Math.abs(avanceY) >= Math.abs(avanceX)) {
          send('media_volume', { steps: avanceY < 0 ? 4 : -4 });
          toast(avanceY < 0 ? 'Volumen +' : 'Volumen −');
        } else {
          send('key', { key: 'tab', mods: avanceX > 0 ? ['ctrl'] : ['ctrl', 'shift'] });
          toast(avanceX > 0 ? 'Pestaña siguiente' : 'Pestaña anterior');
        }
        buzz(18);
      }
    }
    return;
  }

  // --- dos dedos: scroll o zoom (pinza)
  const pts = [...gesture.pointers.values()];
  const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  const distDelta = dist - gesture.twoFinger.lastDist;
  gesture.twoFinger.lastDist = dist;

  if (!gesture.twoFinger.mode) {
    // "moved" es lo que se ha desplazado el PUNTO MEDIO entre los dedos, no la
    // suma del movimiento de cada uno. Ese detalle es la clave: al mover los
    // dedos juntos (scroll) el punto medio avanza y la distancia no cambia,
    // mientras que al separarlos (pinza) la distancia crece el DOBLE de lo que
    // avanza el punto medio. Comparando las dos cifras se distinguen bien.
    const centro = averagePointer();
    gesture.twoFinger.moved += Math.hypot(
      centro.x - gesture.twoFinger.lastCenter.x,
      centro.y - gesture.twoFinger.lastCenter.y,
    );
    gesture.twoFinger.lastCenter = centro;
    gesture.twoFinger.stretch += Math.abs(distDelta);
    // Se decide UNA sola vez, en cuanto hay movimiento suficiente:
    // si los dedos se han separado mas de lo que ha avanzado su punto medio,
    // es una pinza (zoom); si no, es scroll. El umbral lo afina el aprendizaje.
    const total = gesture.twoFinger.moved + gesture.twoFinger.stretch;
    if (total > SCROLL_SLOP) {
      if (settings.pinchZoom
          && gesture.twoFinger.stretch > gesture.twoFinger.moved * umbralPinza()) {
        gesture.twoFinger.mode = 'pinch';
        toast('Zoom');
      } else {
        gesture.twoFinger.mode = 'scroll';
        gesture.acc.x = 0;
        gesture.acc.y = 0;
        if (state.mode !== 'pointer') {   // arrastrando + scroll = soltar
          releaseLeft();
          setMode('pointer');
        }
      }
    }
    // Se guarda la "firma" del gesto (ya con recorrido de sobra) para que el
    // umbral se vaya ajustando a como los haces tu.
    if (!gesture.twoFinger.sampled && total >= 40 && gesture.twoFinger.moved > 1) {
      gesture.twoFinger.sampled = true;
      ratios.push(gesture.twoFinger.stretch / gesture.twoFinger.moved);
      if (ratios.length > MAX_RATIOS) ratios.shift();
      guardarRatios();
    }
  }

  if (gesture.twoFinger.mode === 'pinch') {
    gesture.pinchAcc += distDelta;
    const pasos = Math.trunc(gesture.pinchAcc / 40);
    if (pasos) {
      gesture.pinchAcc -= pasos * 40;
      send('zoom', { steps: pasos });
      buzz(10);
    }
    return;
  }

  if (gesture.twoFinger.mode === 'scroll') {
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
  const wasScroll = gesture.twoFinger.mode === 'scroll'
    || gesture.twoFinger.mode === 'pinch';
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
    resetGesture(remaining);
    return;
  }

  // ------------------------------------------- toque para salir del arrastre fijo
  if (state.mode === 'locked') {
    if (remaining === 0 && wasTap) {
      releaseLeft();
      setMode('pointer');
    }
    resetGesture(remaining);
    return;
  }

  // ------------------------------------------------------- gestos con 2 dedos
  // El clic derecho se decide cuando se han levantado AMBOS dedos: asi el
  // resultado no depende de cual se suelta primero (que era lo que hacia que
  // "a veces" saliera un clic derecho sin motivo).
  if (gesture.twoFinger.active && remaining <= 1) {
    const ahora = performance.now();
    if (!gesture.twoFinger.liftAt) gesture.twoFinger.liftAt = ahora;
    const juntos = ahora - gesture.twoFinger.liftAt;
    const dosMs = ahora - gesture.twoFinger.start;
    // Los umbrales los afina el aprendizaje del toque (filtro de accidentes).
    const u = umbralesToque();
    const intencionado = !wasScroll
      && dosMs < 320
      && gesture.twoFinger.moved <= SCROLL_SLOP
      && gesture.twoFinger.joined <= u.join
      && gesture.twoFinger.dist >= u.dist;
    if (remaining === 0) {
      gesture.twoFinger.active = false;
      if (intencionado && juntos <= u.lift) {
        resetGesture(0);
        send('mouse_click', { button: 'right', clicks: 1 });
        anotarClicDerecho();
        buzz(14);
        return;
      }
    }
    resetGesture(remaining);
    return;
  }

  if (remaining > 0) {
    resetGesture(remaining);
    return;
  }

  resetGesture(0);

  // --------------------------------------------------------- gesto de 3 dedos
  if (gesture.startCount >= 3 && wasTap) {
    send('mouse_click', { button: 'middle', clicks: 1 });
    buzz(14);
    return;
  }

  // Un toque con dos dedos ya se ha resuelto arriba (clic derecho o nada):
  // nunca debe acabar en un clic izquierdo, que es lo que lo hacia imprevisible.
  if (gesture.startCount >= 2) return;

  // ------------------------------------------------------------ toque simple
  if (!wasTap || !settings.tapClick) {
    // El dedo se movio (no fue un toque): si venia rapido, inercia.
    startInertia();
    return;
  }

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
  gesture.twoFinger.active = false;
  gesture.twoFinger.mode = '';
  gesture.three.active = false;
  if (state.mode !== 'pointer') { releaseLeft(); setMode('pointer'); }
  el.cursor.classList.remove('visible');
}

/* ------------------------------------------- fin de gesto, inercia y modos */
function resetGesture(remaining) {
  if (remaining === 0) {
    gesture.twoFinger.active = false;
    gesture.twoFinger.mode = '';
    gesture.three.active = false;
    gesture.three.fired = false;
    gesture.edge = '';
    gesture.pinchAcc = 0;
  }
}

/* Inercia: al levantar el dedo tras un deslizamiento rapido el puntero sigue
   un poco, frenandose, como en un touchpad real. */
function startInertia() {
  if (!settings.inertia) return;
  const velocidad = Math.hypot(gesture.velocity.x, gesture.velocity.y);
  if (velocidad < INERTIA_MIN) return;
  let vx = gesture.velocity.x * 16;
  let vy = gesture.velocity.y * 16;
  gesture.inertiaTimer = setInterval(() => {
    vx *= INERTIA_DECAY;
    vy *= INERTIA_DECAY;
    if (Math.hypot(vx, vy) < 0.6) { stopInertia(); return; }
    send('mouse_rel_move', { dx: deltaUnits(vx), dy: deltaUnits(vy) });
  }, 16);
}

function stopInertia() {
  if (gesture.inertiaTimer) {
    clearInterval(gesture.inertiaTimer);
    gesture.inertiaTimer = null;
  }
}

/* ------------------------------------------------- franjas de scroll */
/* Con dos dedos el scroll y la pinza se distinguen por como se mueven los
   dedos, y a veces se confunden. En las franjas basta UN dedo y solo cuenta
   su eje: la vertical hace scroll arriba/abajo y la horizontal a los lados.
   Sus eventos no llegan al panel, asi que no mueven el puntero ni hacen clic.

   Scroll continuo: si el dedo se queda apoyado despues de haberse alejado del
   punto donde se puso, el scroll sigue solo hacia ese lado, como un joystick.
   Cuanto mas lejos esta el dedo de su punto de partida, mas rapido va. */
const STRIP_DEAD = 24;          // px que hay que alejarse para que siga solo
const STRIP_LINEAL = 3;         // px de scroll por segundo, por px de distancia
const STRIP_CUADRATICO = 0.012; // y la parte que crece con el cuadrado
const strip = {
  id: null, eje: '', inicio: 0, last: 0, acc: 0, offset: 0,
  tick: 0, timer: null, elemento: null,
};

function pintarRayas(delta) {
  // Las rayas de la franja se desplazan con el scroll, como una rueda.
  strip.offset += delta;
  strip.elemento.style.backgroundPosition = strip.eje === 'y'
    ? `0 ${strip.offset}px` : `${strip.offset}px 0`;
}

function vaciarFranja() {
  const ahora = performance.now();
  const dt = Math.min(0.1, (ahora - strip.tick) / 1000);
  strip.tick = ahora;

  // Parte continua: depende de lo lejos que siga el dedo de donde empezo.
  const distancia = strip.last - strip.inicio;
  const exceso = Math.abs(distancia) - STRIP_DEAD;
  if (exceso > 0) {
    const rapidez = exceso * STRIP_LINEAL + exceso * exceso * STRIP_CUADRATICO;
    const extra = Math.sign(distancia) * rapidez * dt;
    strip.acc += extra;
    pintarRayas(extra);
  }

  const valor = strip.acc;
  if (!valor) return;
  strip.acc = 0;
  if (strip.eje === 'y') sendScroll(0, valor);
  else sendScroll(valor, 0);
}

function terminarFranja() {
  if (strip.id === null) return;
  vaciarFranja();
  clearInterval(strip.timer);
  strip.timer = null;
  strip.elemento.classList.remove('active');
  strip.id = null;
  strip.elemento = null;
}

function bindScrollStrip(elemento, eje) {
  const posicion = (event) => (eje === 'y' ? event.clientY : event.clientX);

  elemento.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
    event.preventDefault();
    if (strip.id !== null) return;          // un solo dedo manda en las franjas
    stopInertia();
    try { elemento.setPointerCapture(event.pointerId); } catch (_) {}
    strip.id = event.pointerId;
    strip.eje = eje;
    strip.elemento = elemento;
    strip.last = posicion(event);
    strip.inicio = strip.last;
    strip.acc = 0;
    strip.tick = performance.now();
    strip.timer = setInterval(vaciarFranja, 16);
    elemento.classList.add('active');
    hideHint();
    buzz(8);
  });

  elemento.addEventListener('pointermove', (event) => {
    event.stopPropagation();
    if (event.pointerId !== strip.id) return;
    const ahora = posicion(event);
    const delta = ahora - strip.last;
    strip.last = ahora;
    strip.acc += delta;
    pintarRayas(delta);
  });

  const soltar = (event) => {
    event.stopPropagation();
    if (event.pointerId === strip.id) terminarFranja();
  };
  elemento.addEventListener('pointerup', soltar);
  elemento.addEventListener('pointercancel', soltar);
}

function aplicarFranjas() {
  const visibles = !!settings.scrollStrips;
  if (!visibles) terminarFranja();
  el.scrollV.hidden = !visibles;
  el.scrollH.hidden = !visibles;
  el.stripsBtn.classList.toggle('armed', visibles);
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

  // El scroll se decide en onPointerMove: si el gesto de dos dedos acabo en
  // modo "scroll", lo acumulado se manda como rueda; si no, como movimiento.
  if (gesture.twoFinger.mode === 'scroll') {
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
    ponerTextoTeclado('');
    const area = $('kb-text');
    if (area) area.focus();
    const hint = $('dict-hint');
    if (hint) hint.hidden = true;
  }
  if (name === 'settings') {
    refreshSettingsUI();
    send('devices_list', {});
  }
  if (name === 'shortcuts') send('monitor_list', {});
  if (name === 'help') {
    const acerca = $('help-about');
    if (acerca) {
      acerca.textContent = (appVersion() ? `RemotePad ${appVersion()} · ` : '')
        + `pantalla ${state.screen.w}×${state.screen.h} px · latencia ${state.latency} ms`;
    }
  }
}

function closeSheets() {
  soltarTodoMando();
  Object.values(sheets).forEach((sheet) => { sheet.hidden = true; });
  el.backdrop.hidden = true;
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
}

/* ------------------------------------------------------- atajos propios
   Cada atajo es { nombre, pasos } y cada paso uno de:
     { tipo: 'combo', tecla: 't', mods: ['ctrl', 'shift'] }
     { tipo: 'texto', texto: 'Un saludo,' }
     { tipo: 'espera', ms: 500 }
   El servidor los vuelve a validar y los ejecuta en orden (accion "macro"). */
const MAX_ATAJOS = 24;
const MAX_PASOS = 30;

/* Las mismas teclas que acepta el servidor (controller.SPECIAL_KEYS), mas
   algunos nombres en castellano para escribirlas comodamente. */
const TECLAS_ESPECIALES = new Set([
  'alt', 'backspace', 'caps_lock', 'cmd', 'ctrl', 'delete', 'down', 'end',
  'enter', 'esc', 'home', 'insert', 'left', 'menu', 'num_lock', 'page_down',
  'page_up', 'pause', 'print_screen', 'right', 'scroll_lock', 'shift', 'space',
  'tab', 'up', 'win',
  'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
]);
const ALIAS_TECLAS = {
  control: 'ctrl', ctl: 'ctrl', mayus: 'shift', 'mayús': 'shift', windows: 'win',
  super: 'win', supr: 'delete', suprimir: 'delete', del: 'delete', intro: 'enter',
  return: 'enter', escape: 'esc', espacio: 'space', tabulador: 'tab',
  arriba: 'up', abajo: 'down', izquierda: 'left', derecha: 'right',
  inicio: 'home', fin: 'end', repag: 'page_up', avpag: 'page_down',
  retroceso: 'backspace', borrar: 'backspace', imppnt: 'print_screen',
};
const MODIFICADORES = new Set(['ctrl', 'alt', 'shift', 'win']);

function leerAtajos() {
  try {
    const lista = JSON.parse(settings.atajos || '[]');
    return Array.isArray(lista) ? lista.filter((a) => a && Array.isArray(a.pasos)) : [];
  } catch (_) {
    return [];
  }
}

function guardarAtajos(lista) {
  const texto = JSON.stringify(lista);
  // El perfil de la PC acepta textos de hasta 8000 caracteres por ajuste.
  if (texto.length > 7800) return 'Hay demasiados atajos o son muy largos.';
  settings.atajos = texto;
  saveSettings();
  guardarPerfil();
  return '';
}

/** "ctrl+shift+t" -> { tecla: 't', mods: ['ctrl', 'shift'] }, o un texto de error. */
function parsearCombo(texto) {
  const partes = String(texto || '').toLowerCase().split('+')
    .map((p) => p.trim()).filter(Boolean)
    .map((p) => ALIAS_TECLAS[p] || p);
  if (!partes.length) return 'Escribe una combinación, por ejemplo ctrl+c';
  const tecla = partes[partes.length - 1];
  const mods = partes.slice(0, -1);
  const malo = mods.find((m) => !MODIFICADORES.has(m));
  if (malo) return `«${malo}» no es un modificador (usa ctrl, alt, shift o win)`;
  if (tecla.length !== 1 && !TECLAS_ESPECIALES.has(tecla)) {
    return `No conozco la tecla «${tecla}»`;
  }
  return { tecla, mods };
}

function describirCombo(paso) {
  return [...(paso.mods || []), paso.tecla].join('+');
}

function ejecutarAtajo(atajo) {
  send('macro', { pasos: atajo.pasos });
  buzz(10);
}

const editorAtajos = { indice: -1, editando: false };

function pintarAtajos() {
  const contenedor = $('custom-shortcuts');
  if (!contenedor) return;
  const lista = leerAtajos();
  contenedor.replaceChildren();
  contenedor.classList.toggle('editando', editorAtajos.editando);
  lista.forEach((atajo, indice) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'key';
    boton.textContent = (editorAtajos.editando ? '✎ ' : '') + (atajo.nombre || 'Atajo');
    boton.addEventListener('click', () => {
      if (editorAtajos.editando) abrirEditorAtajo(indice);
      else ejecutarAtajo(atajo);
    });
    contenedor.append(boton);
  });
  $('custom-empty').hidden = lista.length > 0;
  $('btn-shortcut-edit').hidden = lista.length === 0;
  $('btn-shortcut-edit').textContent = editorAtajos.editando ? '✓ Hecho' : '✎ Editar';
  $('btn-shortcut-new').disabled = lista.length >= MAX_ATAJOS;
}

function filaPaso(paso) {
  const fila = document.createElement('li');
  fila.dataset.tipo = paso.tipo;
  const tipo = document.createElement('span');
  tipo.className = 'tipo-paso';
  tipo.textContent = { combo: 'Teclas', texto: 'Texto', espera: 'Espera' }[paso.tipo];
  const campo = document.createElement('input');
  campo.type = paso.tipo === 'espera' ? 'number' : 'text';
  campo.autocomplete = 'off';
  if (paso.tipo === 'combo') {
    campo.placeholder = 'ctrl+shift+t';
    campo.value = paso.tecla ? describirCombo(paso) : '';
    campo.autocapitalize = 'off';
  } else if (paso.tipo === 'texto') {
    campo.placeholder = 'Texto que se escribirá';
    campo.maxLength = 1000;
    campo.value = paso.texto || '';
  } else {
    campo.min = '0';
    campo.max = '3000';
    campo.step = '100';
    campo.value = String(paso.ms ?? 500);
  }
  const quitar = document.createElement('button');
  quitar.type = 'button';
  quitar.className = 'key';
  quitar.textContent = '✕';
  quitar.setAttribute('aria-label', 'Quitar este paso');
  quitar.addEventListener('click', () => fila.remove());
  fila.append(tipo, campo, quitar);
  return fila;
}

function anadirPaso(paso) {
  const lista = $('sc-steps');
  if (lista.children.length >= MAX_PASOS) {
    mostrarErrorAtajo(`Como mucho ${MAX_PASOS} pasos.`);
    return;
  }
  const fila = filaPaso(paso);
  lista.append(fila);
  fila.querySelector('input').focus();
}

function mostrarErrorAtajo(texto) {
  const error = $('sc-error');
  error.textContent = texto;
  error.hidden = !texto;
}

function abrirEditorAtajo(indice) {
  const atajo = indice >= 0 ? leerAtajos()[indice] : { nombre: '', pasos: [{ tipo: 'combo' }] };
  if (!atajo) return;
  editorAtajos.indice = indice;
  $('sc-name').value = atajo.nombre || '';
  $('sc-steps').replaceChildren(...atajo.pasos.map(filaPaso));
  $('sc-delete').hidden = indice < 0;
  mostrarErrorAtajo('');
  $('shortcut-editor').hidden = false;
  $('shortcut-editor').scrollIntoView({ block: 'nearest' });
}

function cerrarEditorAtajo() {
  $('shortcut-editor').hidden = true;
  editorAtajos.indice = -1;
}

/** Lee el editor y devuelve { nombre, pasos } o un texto de error. */
function leerEditorAtajo() {
  const nombre = $('sc-name').value.trim();
  if (!nombre) return 'Ponle un nombre al botón.';
  const pasos = [];
  let espera = 0;
  for (const [numero, fila] of [...$('sc-steps').children].entries()) {
    const valor = fila.querySelector('input').value;
    if (fila.dataset.tipo === 'combo') {
      const combo = parsearCombo(valor);
      if (typeof combo === 'string') return `Paso ${numero + 1}: ${combo}`;
      pasos.push({ tipo: 'combo', ...combo });
    } else if (fila.dataset.tipo === 'texto') {
      if (!valor) return `Paso ${numero + 1}: el texto está vacío.`;
      pasos.push({ tipo: 'texto', texto: valor });
    } else {
      const ms = Math.round(Number(valor));
      if (!Number.isFinite(ms) || ms < 0 || ms > 3000) {
        return `Paso ${numero + 1}: la espera va de 0 a 3000 ms.`;
      }
      espera += ms;
      pasos.push({ tipo: 'espera', ms });
    }
  }
  if (!pasos.length) return 'Añade al menos un paso.';
  if (espera > 10000) return 'Las esperas suman más de 10 segundos.';
  return { nombre: nombre.slice(0, 30), pasos };
}

function bindAtajos() {
  $('btn-shortcut-new').addEventListener('click', () => {
    editorAtajos.editando = false;
    pintarAtajos();
    abrirEditorAtajo(-1);
  });
  $('btn-shortcut-edit').addEventListener('click', () => {
    editorAtajos.editando = !editorAtajos.editando;
    if (!editorAtajos.editando) cerrarEditorAtajo();
    pintarAtajos();
    if (editorAtajos.editando) toast('Toca el atajo que quieras cambiar');
  });
  $('sc-add-combo').addEventListener('click', () => anadirPaso({ tipo: 'combo' }));
  $('sc-add-text').addEventListener('click', () => anadirPaso({ tipo: 'texto' }));
  $('sc-add-wait').addEventListener('click', () => anadirPaso({ tipo: 'espera', ms: 500 }));
  $('sc-cancel').addEventListener('click', cerrarEditorAtajo);
  $('sc-delete').addEventListener('click', () => {
    const lista = leerAtajos();
    const atajo = lista[editorAtajos.indice];
    if (!atajo || !window.confirm(`¿Borrar el atajo «${atajo.nombre}»?`)) return;
    lista.splice(editorAtajos.indice, 1);
    guardarAtajos(lista);
    cerrarEditorAtajo();
    pintarAtajos();
  });
  $('shortcut-editor').addEventListener('submit', (event) => {
    event.preventDefault();
    const atajo = leerEditorAtajo();
    if (typeof atajo === 'string') {
      mostrarErrorAtajo(atajo);
      return;
    }
    const lista = leerAtajos();
    if (editorAtajos.indice >= 0) lista[editorAtajos.indice] = atajo;
    else lista.push(atajo);
    const error = guardarAtajos(lista);
    if (error) {
      mostrarErrorAtajo(error);
      return;
    }
    cerrarEditorAtajo();
    pintarAtajos();
    toast(`Atajo «${atajo.nombre}» guardado`);
  });
  pintarAtajos();
}

/* ----------------------------------------------------------- modo mando
   Cada boton mantiene su tecla pulsada en la PC (key_down) mientras el dedo
   esta encima y la suelta al levantarlo (key_up). Varios a la vez: cruceta
   en diagonal + saltar + correr. */
const BOTONES_MANDO = ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'y', 'select', 'start'];
const NOMBRES_MANDO = {
  up: '▲', down: '▼', left: '◀', right: '▶', a: 'A', b: 'B', x: 'X', y: 'Y',
  select: 'Select', start: 'Start',
};
const PRESETS_MANDO = {
  flechas: { up: 'up', down: 'down', left: 'left', right: 'right',
    a: 'space', b: 'esc', x: 'z', y: 'x', select: 'tab', start: 'enter' },
  wasd: { up: 'w', down: 's', left: 'a', right: 'd',
    a: 'space', b: 'e', x: 'q', y: 'r', select: 'tab', start: 'esc' },
};

const mando = {
  dedos: new Map(),      // pointerId -> tecla
  cuentas: new Map(),    // tecla -> cuantos dedos la mantienen
};

function configMando() {
  let config = {};
  try { config = JSON.parse(settings.mando || '{}') || {}; } catch (_) { config = {}; }
  const preset = PRESETS_MANDO[config.preset] ? config.preset
    : (config.preset === 'propio' ? 'propio' : 'flechas');
  const propio = { ...PRESETS_MANDO.flechas, ...(config.mapa || {}) };
  return { preset, mapa: preset === 'propio' ? propio : PRESETS_MANDO[preset], propio };
}

function guardarConfigMando(preset, propio) {
  settings.mando = JSON.stringify({ preset, mapa: propio });
  saveSettings();
  guardarPerfil();
}

function teclaMandoValida(tecla) {
  return tecla.length === 1 ? /^[a-z0-9]$/.test(tecla) : TECLAS_ESPECIALES.has(tecla);
}

function pulsarMando(boton, pointerId) {
  const tecla = configMando().mapa[boton.dataset.pad];
  if (!tecla || mando.dedos.has(pointerId)) return;
  mando.dedos.set(pointerId, { tecla, boton });
  const cuenta = (mando.cuentas.get(tecla) || 0) + 1;
  mando.cuentas.set(tecla, cuenta);
  if (cuenta === 1) send('key_down', { key: tecla });
  boton.classList.add('pulsado');
  buzz(8);
}

function soltarMando(pointerId) {
  const dedo = mando.dedos.get(pointerId);
  if (!dedo) return;
  mando.dedos.delete(pointerId);
  const cuenta = (mando.cuentas.get(dedo.tecla) || 1) - 1;
  if (cuenta <= 0) {
    mando.cuentas.delete(dedo.tecla);
    send('key_up', { key: dedo.tecla });
  } else {
    mando.cuentas.set(dedo.tecla, cuenta);
  }
  if (![...mando.dedos.values()].some((d) => d.boton === dedo.boton)) {
    dedo.boton.classList.remove('pulsado');
  }
}

/* Al cerrar el panel, cambiar de app o perder la conexion no puede quedar
   ninguna tecla pulsada en la PC. */
function soltarTodoMando() {
  [...mando.dedos.keys()].forEach(soltarMando);
}

function pintarMando() {
  const { preset, mapa, propio } = configMando();
  $('mando-preset').value = preset;
  $('mando-resumen').textContent = BOTONES_MANDO
    .map((b) => `${NOMBRES_MANDO[b]} ${mapa[b]}`).join(' · ');
  const editor = $('mando-mapa');
  editor.hidden = preset !== 'propio';
  if (preset !== 'propio') return;
  editor.replaceChildren(...BOTONES_MANDO.map((boton) => {
    const etiqueta = document.createElement('label');
    const nombre = document.createElement('span');
    nombre.textContent = NOMBRES_MANDO[boton];
    const campo = document.createElement('input');
    campo.type = 'text';
    campo.autocapitalize = 'off';
    campo.autocomplete = 'off';
    campo.value = propio[boton];
    campo.addEventListener('change', () => {
      const valor = ALIAS_TECLAS[campo.value.trim().toLowerCase()] || campo.value.trim().toLowerCase();
      const valida = teclaMandoValida(valor);
      campo.classList.toggle('invalida', !valida);
      if (!valida) {
        toast(`No conozco la tecla «${campo.value}»`);
        return;
      }
      campo.value = valor;
      guardarConfigMando('propio', { ...configMando().propio, [boton]: valor });
      pintarMando();
    });
    etiqueta.append(nombre, campo);
    return etiqueta;
  }));
}

function bindMando() {
  document.querySelectorAll('[data-pad]').forEach((boton) => {
    boton.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      pulsarMando(boton, event.pointerId);
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((tipo) => {
      boton.addEventListener(tipo, (event) => soltarMando(event.pointerId));
    });
    boton.addEventListener('contextmenu', (event) => event.preventDefault());
  });
  $('mando-preset').addEventListener('change', (event) => {
    soltarTodoMando();
    guardarConfigMando(event.target.value, configMando().propio);
    pintarMando();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) soltarTodoMando();
  });
  pintarMando();
}

/* ------------------------------------------------------ varios monitores */
let monitoresConocidos = [];

/* Con una sola pantalla el bloque no aparece: no aporta nada. */
function pintarMonitores(datos) {
  if (Array.isArray(datos.monitores)) monitoresConocidos = datos.monitores;
  const actual = typeof datos.index === 'number' ? datos.index : datos.actual;
  if (datos.ok) toast(`Puntero en la pantalla ${actual + 1}`);

  const bloque = $('monitor-block');
  const botones = $('monitor-buttons');
  if (!bloque || !botones) return;
  bloque.hidden = monitoresConocidos.length < 2;
  botones.replaceChildren();
  monitoresConocidos.forEach((monitor, indice) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'key' + (indice === actual ? ' actual' : '');
    boton.textContent = `🖥 Pantalla ${indice + 1}`;
    const detalle = document.createElement('small');
    detalle.textContent = `${monitor.w}×${monitor.h}` + (monitor.primary ? ' · principal' : '');
    boton.append(detalle);
    boton.addEventListener('click', () => {
      send('monitor_goto', { index: indice });
      buzz(10);
    });
    botones.append(boton);
  });
}

/* ------------------------------------------------- dispositivos con acceso */
function haceCuanto(segundosEpoch) {
  const diferencia = Math.max(0, Date.now() / 1000 - Number(segundosEpoch || 0));
  if (diferencia < 90) return 'ahora';
  if (diferencia < 3600) return `hace ${Math.round(diferencia / 60)} min`;
  if (diferencia < 86400) return `hace ${Math.round(diferencia / 3600)} h`;
  const dias = Math.round(diferencia / 86400);
  return dias === 1 ? 'hace 1 día' : `hace ${dias} días`;
}

/* Los nombres vienen del User-Agent de cada navegador: se pintan siempre con
   textContent, nunca como HTML. */
function pintarDispositivos(datos) {
  const casilla = $('s-confirm');
  if (casilla && typeof datos.confirmar === 'boolean') casilla.checked = datos.confirmar;
  if (datos.ok && datos.nombre) toast('Acceso retirado: ' + datos.nombre, 2400);

  const lista = $('devices-list');
  const filas = Array.isArray(datos.dispositivos) ? datos.dispositivos : null;
  if (!lista || !filas) return;
  lista.replaceChildren();
  if (!filas.length) {
    const vacio = document.createElement('li');
    vacio.className = 'devices-empty';
    vacio.textContent = 'Ningún dispositivo tiene acceso.';
    lista.append(vacio);
    return;
  }
  filas.forEach((fila) => {
    const item = document.createElement('li');
    const info = document.createElement('div');
    info.className = 'device-info';

    const nombre = document.createElement('span');
    nombre.className = 'device-name';
    nombre.textContent = fila.nombre || 'Dispositivo';
    const etiqueta = fila.actual ? 'este' : (fila.conectado ? 'conectado' : '');
    if (etiqueta) {
      const marca = document.createElement('span');
      marca.className = 'device-tag';
      marca.textContent = etiqueta;
      nombre.append(marca);
    }
    const detalle = document.createElement('span');
    detalle.className = 'device-meta';
    detalle.textContent = `${fila.addr || 'sin dirección'} · ${haceCuanto(fila.visto)}`;
    info.append(nombre, detalle);

    const quitar = document.createElement('button');
    quitar.className = 'key danger';
    quitar.type = 'button';
    quitar.textContent = 'Quitar';
    quitar.addEventListener('click', () => {
      if (fila.actual) {
        olvidarEsteDispositivo();
        return;
      }
      if (!window.confirm(`¿Quitar el acceso a «${fila.nombre}»?\n\n`
          + 'Se desconectará y tendrá que volver a escanear el QR o escribir el PIN.')) {
        return;
      }
      send('device_revoke', { id: fila.id });
    });
    item.append(info, quitar);
    lista.append(item);
  });
}

/* "Olvidar este dispositivo": se retira tambien el acceso en la PC (no solo
   en el celular), para que el token no quede valido en ningun sitio. */
function olvidarEsteDispositivo() {
  if (!window.confirm('¿Olvidar este dispositivo?\n\nPara volver a entrar habrá '
      + 'que escanear el QR o escribir el PIN.')) {
    return;
  }
  state.olvidando = true;
  if (state.deviceId && send('device_revoke', { id: state.deviceId })) {
    return;   // el servidor responde con "revoked" y cierra la conexion
  }
  try { localStorage.removeItem(TOKEN_KEY); } catch (_) {}
  state.authorized = false;
  closeSheets();
  toast('Dispositivo olvidado: pide el PIN de nuevo', 2400);
  try { state.ws.close(); } catch (_) {}
}

/* ------------------------------------------------------------ tutorial */
const TUTORIAL_STEPS = [
  { icon: '👋', title: 'Bienvenido a RemotePad',
    body: 'Tu celular es ahora el touchpad de la PC. Te enseño los gestos en unos pasos rápidos.' },
  { icon: '👆', title: 'Mover el puntero',
    body: 'Desliza un dedo por el panel grande. Es como mover el ratón.' },
  { icon: '👊', title: 'Hacer clic',
    body: 'Tocar = clic izquierdo · 2 dedos = clic derecho · 3 dedos = botón central.' },
  { icon: '✌️', title: 'Scroll y zoom',
    body: 'Desliza con 2 dedos para hacer scroll. Pellizca con 2 dedos para acercar o alejar (zoom). '
      + 'Si se confunden, pulsa ↕ arriba: aparecen dos franjas para hacer scroll con un solo dedo. '
      + 'Si dejas el dedo apoyado, sigue solo: más lejos de donde empezaste, más rápido.' },
  { icon: '✊', title: 'Arrastrar',
    body: 'Mantén pulsado 0,4 s y desliza sin soltar para arrastrar. O toca dos veces y desliza '
      + '(arrastre fijo: toca otra vez para soltar).' },
  { icon: '⚡', title: 'Modo rápido',
    body: 'El botón ⚡ de la barra superior multiplica por 3 la velocidad del puntero, '
      + 'para cruzar la pantalla de una pasada.' },
  { icon: '⌨️', title: 'Teclado y dictado',
    body: 'En Teclado escribes y el texto aparece en la PC. Con 🎤 Dictar puedes hablar y que '
      + 'se escriba solo.' },
  { icon: '🎵', title: 'Atajos, volumen y láser',
    body: 'En los paneles de abajo tienes atajos, multimedia y presentaciones. Con 3 dedos ↑↓ '
      + 'cambias el volumen, y con 🔴 señalas con el puntero láser.' },
  { icon: '🎮', title: 'Mando y tus atajos',
    body: 'En 🎮 Mando tienes cruceta y botones para jugar. En ⚡ Atajos puedes crear tus '
      + 'propios botones: combinaciones de teclas, textos o varios pasos seguidos.' },
  { icon: '✅', title: '¡Todo listo!',
    body: 'Puedes volver a ver este tutorial desde ❓ Ayuda. Si algo se queda pegado, pulsa Soltar.' },
];

const TUTORIAL_KEY = 'remotepad.tutorial-visto';
let tutIndex = 0;

function openTutorial() {
  tutIndex = 0;
  renderTutorial();
  el.tutorial.hidden = false;
}

function renderTutorial() {
  const paso = TUTORIAL_STEPS[tutIndex];
  el.tutIcon.textContent = paso.icon;
  el.tutStep.textContent = `Paso ${tutIndex + 1} de ${TUTORIAL_STEPS.length}`;
  el.tutTitle.textContent = paso.title;
  el.tutBody.textContent = paso.body;
  el.tutPrev.disabled = tutIndex === 0;
  el.tutNext.textContent = tutIndex === TUTORIAL_STEPS.length - 1
    ? 'Empezar ✔' : 'Siguiente ▶';
}

function closeTutorial() {
  el.tutorial.hidden = true;
  try { localStorage.setItem(TUTORIAL_KEY, '1'); } catch (_) {}
}

function tutorialPaso(delta) {
  const siguiente = tutIndex + delta;
  if (siguiente < 0) return;
  if (siguiente >= TUTORIAL_STEPS.length) { closeTutorial(); return; }
  tutIndex = siguiente;
  renderTutorial();
}

/* ------------------------------------------------------- anti-apagado */
let awakeHasta = 0;
let awakeTimer = null;

function abrirAwake() {
  if (el.awake) el.awake.hidden = false;
  pintarAwake();
}

function pintarAwake() {
  if (!el.awakeState) return;
  const restante = Math.max(0, Math.round((awakeHasta - Date.now()) / 1000));
  if (!restante) {
    el.awakeState.textContent = 'Apagado: la PC puede apagarse como siempre.';
    return;
  }
  const min = Math.floor(restante / 60);
  const seg = restante % 60;
  el.awakeState.textContent =
    `Activo: quedan ${min} min ${String(seg).padStart(2, '0')} s.`;
}

function activarAwake(minutos) {
  send('keep_awake', { minutes: minutos });
  awakeHasta = Date.now() + minutos * 60000;
  if (awakeTimer) clearInterval(awakeTimer);
  awakeTimer = setInterval(pintarAwake, 1000);
  pintarAwake();
  toast(`Pantalla encendida durante ${minutos} minutos`, 2600);
  buzz(14);
}

function pararAwake() {
  send('keep_awake', { on: false });
  awakeHasta = 0;
  if (awakeTimer) { clearInterval(awakeTimer); awakeTimer = null; }
  pintarAwake();
  toast('Anti-apagado detenido');
}

/* ------------------------------------------------------------- dictado */
let dictado = null;

/*
 * Dictado por voz.
 *
 * Los navegadores solo dejan usar el microfono en paginas "seguras" (HTTPS o
 * localhost). RemotePad va por HTTP en la red local, asi que casi siempre la
 * via que funciona es el microfono del PROPIO TECLADO del celular (Gboard):
 * se enfoca el campo de texto y el sistema dicta ahi; el texto se envia a la
 * PC como si lo hubieras escrito. Si la pagina SI es segura y el navegador
 * trae reconocimiento de voz, se usa directamente.
 */
function iniciarDictado() {
  const area = $('kb-text');
  const hint = $('dict-hint');
  const Reconocimiento = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (Reconocimiento && window.isSecureContext) {
    try {
      if (dictado) {
        dictado.stop();
        dictado = null;
        if (hint) hint.hidden = true;
        return;
      }
      dictado = new Reconocimiento();
      dictado.lang = 'es-ES';
      dictado.continuous = true;
      dictado.interimResults = true;
      dictado.onresult = (evento) => {
        let texto = '';
        for (let i = evento.resultIndex; i < evento.results.length; i++) {
          if (evento.results[i].isFinal) texto += evento.results[i][0].transcript;
        }
        if (texto) {
          send('key_type', { text: texto + ' ' });
          if (area) { area.value += texto + ' '; tecladoPrevious = area.value; }
        }
      };
      dictado.onerror = () => {
        if (hint) {
          hint.hidden = false;
          hint.textContent = 'No se pudo usar el micrófono del navegador. '
            + 'Usa el 🎤 del teclado del celular.';
        }
      };
      dictado.onend = () => { dictado = null; };
      dictado.start();
      if (hint) {
        hint.hidden = false;
        hint.textContent = '🔴 Dictando… habla normal. Pulsa 🎤 otra vez para parar.';
      }
      buzz(14);
      return;
    } catch (_) { /* se intenta el plan B */ }
  }

  if (area) area.focus();
  if (hint) {
    hint.hidden = false;
    hint.textContent = 'Toca el 🎤 del teclado del celular y habla: el texto se '
      + 'escribirá en el campo y aparecerá en la PC.';
  }
  toast('Usa el micrófono del teclado del celular', 3200);
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
  $('s-inertia').checked = settings.inertia;
  $('s-three').checked = settings.threeFinger;
  $('s-edgeback').checked = settings.edgeBack;
  $('s-pinch').checked = settings.pinchZoom;
  aplicarFranjas();
  $('s-learn').checked = settings.learnAdaptive;
  $('s-learntap').checked = settings.learnTap;
  $('s-learnumbral').checked = settings.learnThreshold;
  pintarAprendizaje(aprendizajeServidor);
  // Se pide al servidor que cuente lo que ha aprendido de ti.
  send('learning', {});
  $('about').textContent =
    `Pantalla: ${state.screen.w}×${state.screen.h} px · latencia ${state.latency} ms`
    + (appVersion() ? ` · versión ${appVersion()}` : ' · versión desconocida');
}

/* ------------------------------------------------------ teclado remoto */
let tecladoPrevious = '';

/** Coloca texto en el campo del teclado SIN enviarlo a la PC. */
function ponerTextoTeclado(texto) {
  const area = $('kb-text');
  if (!area) return;
  area.value = texto;
  tecladoPrevious = texto;
}

function bindTyping() {
  const area = $('kb-text');

  area.addEventListener('input', () => {
    const value = area.value;
    if (value.length >= tecladoPrevious.length && value.startsWith(tecladoPrevious)) {
      send('key_type', { text: value.slice(tecladoPrevious.length) });
    } else if (value.length < tecladoPrevious.length && tecladoPrevious.startsWith(value)) {
      const removed = Math.min(tecladoPrevious.length - value.length, 40);
      send('key_type', { text: '\b'.repeat(removed) });
    } else {
      let shared = 0;
      while (shared < value.length && shared < tecladoPrevious.length
             && value[shared] === tecladoPrevious[shared]) shared++;
      const tail = Math.min(tecladoPrevious.length - shared, 40);
      send('key_type', { text: '\b'.repeat(tail) + value.slice(shared) });
    }
    tecladoPrevious = value;
  });

  // El Enter del teclado del movil NO se intercepta: escribe un salto de linea
  // normal, para poder escribir varias lineas. Ese salto se envia a la PC como
  // una linea nueva (en la PC un salto de linea ES un Enter). Para pulsar un
  // Enter suelto en la PC, sin escribir nada, esta el boton "Enter".
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
    const escrito = el.pinInput.value;
    // Si el campo estaba vacio y el usuario empieza a escribir, en realidad
    // quiere el PIN: se descarta la clave del QR y no se le toca el texto.
    if (escrito.length > 0 && qrKeyVigente()) {
      state.qrDescartado = true;
    }
    if (escrito.length === 0 && qrKeyVigente()) {
      // Tocar el campo vacio con un QR vigente en la pagina: se usa ese.
      usarQrDeLaPagina();
      return;
    }
    const limpio = escrito.replace(/\D/g, '').slice(0, 6);
    el.pinInput.value = limpio;
    if (limpio.length === 6) el.authBtn.click();
  });

  el.pinBtn.addEventListener('click', () => { send('get_state', {}); });

  // --- entrar sin codigo (cuando la PC tiene el acceso desactivado) -------
  el.authOpen.addEventListener('click', entrarSinCodigo);

  // --- activar o quitar el codigo de acceso ------------------------------
  $('btn-authmode').addEventListener('click', async () => {
    const quitar = state.authRequired;
    const mensaje = quitar
      ? '¿Quitar el código de acceso?\n\nMientras esté quitado, cualquiera '
        + 'conectado a tu misma WiFi podrá mover el puntero, hacer clic y '
        + 'escribir en la PC, sin PIN ni código QR.'
      : '¿Volver a pedir el código de acceso?\n\nSe generará un PIN nuevo y '
        + 'habrá que escanear el QR o escribirlo para conectarse.';
    if (!window.confirm(mensaje)) return;
    // Si estamos en la propia PC, la via directa es el endpoint local.
    try {
      const respuesta = await fetch('api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ required: !quitar }),
      });
      if (respuesta.ok) {
        toast(quitar ? 'Código de acceso desactivado' : 'Código activado', 3000);
        return;
      }
    } catch (_) { /* no somos la PC: se pide por el WebSocket */ }
    send('set_auth', { required: !quitar });
    toast(quitar ? 'Quitando el código…' : 'Activando el código…', 3000);
  });

  el.modeBtn.addEventListener('click', () => {
    if (state.mode === 'pointer') {
      startLeftDrag();
      setMode('locked');
    } else {
      releaseLeft();
      setMode('pointer');
    }
  });

  el.fastBtn.addEventListener('click', () => {
    state.fast = !state.fast;
    el.fastBtn.classList.toggle('armed', state.fast);
    el.fastBtn.textContent = state.fast ? `⚡ ${FAST_FACTOR}×` : '⚡ 1×';
    toast(state.fast
      ? `Modo rápido: el puntero va ${FAST_FACTOR}×`
      : 'Velocidad normal');
    buzz(14);
  });

  el.stripsBtn.addEventListener('click', () => {
    settings.scrollStrips = !settings.scrollStrips;
    saveSettings();
    guardarPerfil();
    aplicarFranjas();
    toast(settings.scrollStrips
      ? 'Franjas de scroll: desliza 1 dedo por ellas'
      : 'Franjas de scroll ocultas');
    buzz(14);
  });
  bindScrollStrip(el.scrollV, 'y');
  bindScrollStrip(el.scrollH, 'x');
  aplicarFranjas();

  el.laserBtn.addEventListener('click', () => {
    state.laser = !state.laser;
    el.laserBtn.classList.toggle('armed', state.laser);
    if (!state.laser) send('laser', { on: false });
    toast(state.laser ? 'Láser: toca el panel para señalar' : 'Láser apagado');
    buzz(14);
  });

  const kbGet = $('kb-get');
  if (kbGet) {
    kbGet.addEventListener('click', () => {
      send('clipboard_get', {});
      toast('Trayendo del PC…');
    });
  }
  const kbSend = $('kb-send');
  if (kbSend) {
    kbSend.addEventListener('click', () => {
      const area = $('kb-text');
      const texto = area ? area.value : '';
      if (!texto) { toast('No hay texto que enviar'); return; }
      send('clipboard_set', { text: texto });
      toast('Copiado en el PC: pégalo con Ctrl+V', 2600);
    });
  }

  const kbDict = $('kb-dict');
  if (kbDict) kbDict.addEventListener('click', iniciarDictado);

  if (el.tutNext) {
    el.tutNext.addEventListener('click', () => tutorialPaso(1));
    el.tutPrev.addEventListener('click', () => tutorialPaso(-1));
    el.tutSkip.addEventListener('click', closeTutorial);
  }
  const btnTutorial = $('btn-tutorial');
  if (btnTutorial) {
    btnTutorial.addEventListener('click', () => { closeSheets(); openTutorial(); });
  }

  const btnAwake = $('btn-awake');
  if (btnAwake) {
    btnAwake.addEventListener('click', () => { closeSheets(); abrirAwake(); });
  }
  document.querySelectorAll('[data-awake]').forEach((button) => {
    button.addEventListener('click', () => activarAwake(Number(button.dataset.awake)));
  });
  const awakeStop = $('awake-stop');
  if (awakeStop) awakeStop.addEventListener('click', pararAwake);
  const awakeClose = $('awake-close');
  if (awakeClose) {
    awakeClose.addEventListener('click', () => { if (el.awake) el.awake.hidden = true; });
  }

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
      guardarPerfil();
    });
  };
  bindRange('s-speed', 'v-speed', 'sensitivity');
  bindRange('s-scroll', 'v-scroll', 'scrollSpeed');

  const bindSwitch = (id, key) => {
    const input = $(id);
    input.addEventListener('change', () => {
      settings[key] = input.checked;
      saveSettings();
      guardarPerfil();
    });
  };
  bindSwitch('s-accel', 'accel');
  bindSwitch('s-natural', 'naturalScroll');
  bindSwitch('s-tap', 'tapClick');
  bindSwitch('s-draglock', 'dragLock');
  bindSwitch('s-haptics', 'haptics');
  bindSwitch('s-edges', 'edgeZones');
  bindSwitch('s-inertia', 'inertia');
  bindSwitch('s-three', 'threeFinger');
  bindSwitch('s-edgeback', 'edgeBack');
  bindSwitch('s-pinch', 'pinchZoom');
  bindSwitch('s-learn', 'learnAdaptive');
  bindSwitch('s-learntap', 'learnTap');
  bindSwitch('s-learnumbral', 'learnThreshold');

  const sLearn = $('s-learn');
  if (sLearn) {
    sLearn.addEventListener('change', () => send('learning', { on: sLearn.checked }));
  }
  const btnLearnReset = $('btn-learning-reset');
  if (btnLearnReset) {
    btnLearnReset.addEventListener('click', () => {
      send('learning', { reset: true });
      reiniciarAprendizajeLocal();
      toast('Lo aprendido se ha reiniciado');
    });
  }

  $('btn-fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) { toast('Tu navegador no permite pantalla completa'); }
  });

  $('btn-logout').addEventListener('click', olvidarEsteDispositivo);

  $('s-confirm').addEventListener('change', (event) => {
    send('set_confirm', { on: event.target.checked });
  });

  // --- detener el servicio en la PC -------------------------------------
  $('btn-stop').addEventListener('click', async () => {
    if (!window.confirm('¿Detener RemotePad en la PC?\n\n'
        + 'Se cerrará el servidor y habrá que volver a iniciarlo con '
        + 'iniciar.bat.')) {
      return;
    }
    closeSheets();
    // Si estamos en la propia PC, la via directa es el endpoint local; si no,
    // se pide por el WebSocket (que exige estar ya autorizado).
    try {
      const response = await fetch('api/stop', { method: 'POST' });
      if (response.ok) {
        toast('Deteniendo RemotePad…', 3000);
        return;
      }
    } catch (_) { /* no somos la PC: se pide por el WebSocket */ }
    send('comando_detener', {});
    toast('Pidiendo detener RemotePad…', 3000);
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
 * La clave del QR puede llegar de dos formas:
 *   1) en la direccion, como ?k=...  (cuando el navegador la conserva)
 *   2) inyectada por el servidor en una etiqueta meta (mas fiable: algunos
 *      visores de camara recortan la direccion al redirigir)
 *
 * Se acepta cualquiera de las dos. Ademas el servidor avisa, en otra etiqueta,
 * de si la clave seguia vigente cuando se sirvio la pagina.
 */
function qrKey() {
  const meta = document.querySelector('meta[name="remotepad-qr-key"]');
  if (meta && meta.content) return meta.content;
  const params = new URLSearchParams(location.search);
  return params.get('k') || '';
}

function appVersion() {
  const meta = document.querySelector('meta[name="remotepad-version"]');
  return meta ? meta.content : '';
}

/** True si el servidor dejo en la pagina una clave de QR aun vigente. */
function qrKeyVigente() {
  if (state.qrDescartado) return false;   // el usuario prefiere el PIN
  const estado = document.querySelector('meta[name="remotepad-qr-estado"]');
  return Boolean(estado && estado.content === 'ok' && qrKey());
}

/**
 * Usa la clave que el servidor puso en la pagina.
 *
 * Es el camino de respaldo: si el navegador perdio el parametro ?k= de la
 * direccion (algunos visores de camara lo recortan), la clave sigue estando
 * en el HTML y basta con pulsar el campo del PIN para entrar.
 */
async function usarQrDeLaPagina() {
  el.authError.textContent = 'Usando el código de la página…';
  el.authError.hidden = false;
  const ok = await qrLogin();
  if (!ok) return;
  // El token ya esta guardado: se reconecta para que el servidor lo acepte.
  try { state.ws.close(); } catch (_) {}
  connect();
}

async function qrLogin() {
  const key = qrKey();
  if (!key) return false;

  // Se limpia la direccion para que el enlace no quede en el historial.
  try {
    history.replaceState(null, '', location.pathname);
  } catch (_) { /* algunos navegadores no lo permiten */ }

  const resultado = await canjear(key);
  if (resultado.ok) return true;

  // El codigo pudo renovarse en el servidor justo mientras se escaneaba: el
  // panel los cambia cada 3 minutos. Si este celular ya estaba autorizado se
  // pide uno nuevo y se reintenta, sin volver a apuntar con la camara.
  if (resultado.status === 403 && await recuperarConToken()) {
    return true;
  }

  showAuthError(resultado.mensaje);
  return false;
}

/** Canjea una clave del QR. Devuelve {ok} o {ok:false, status, mensaje}. */
async function canjear(key) {
  let response;
  try {
    response = await fetch('api/qr-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
  } catch (_) {
    return {
      ok: false,
      status: 0,
      mensaje: 'No se pudo conectar con la PC para validar el código. '
        + (appVersion() ? '(versión ' + appVersion() + ') ' : '')
        + 'Comprueba que el servidor siga encendido.',
    };
  }

  if (response.status === 403) {
    return {
      ok: false,
      status: 403,
      mensaje: 'El código caducó o ya se usó (duran 3 minutos). Mira la PC: '
        + 'aparece uno nuevo cada 3 minutos. Escanea ese.',
    };
  }
  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      mensaje: 'La PC rechazó el código (error ' + response.status + '). '
        + 'Escanea el código que muestra ahora mismo.',
    };
  }

  try {
    const data = await response.json();
    if (data && data.ok && data.token) {
      try { localStorage.setItem(TOKEN_KEY, data.token); } catch (_) {}
      return { ok: true };
    }
    return {
      ok: false,
      status: response.status,
      mensaje: 'La PC no devolvió un acceso válido. Vuelve a escanear el código.',
    };
  } catch (_) {
    return {
      ok: false,
      status: response.status,
      mensaje: 'Respuesta inesperada de la PC. Vuelve a escanear el código.',
    };
  }
}

/**
 * Pide un QR nuevo con el token guardado y lo canjea al instante.
 *
 * Red de seguridad contra la carrera de la rotacion: el codigo que el usuario
 * escaneo cambio mientras lo leia, pero como este celular ya tenia acceso se
 * le entrega uno nuevo sin que tenga que volver a apuntar con la camara.
 */
async function recuperarConToken() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return false;
  try {
    const respuesta = await fetch('api/qr-refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    if (!respuesta.ok) return false;
    const datos = await respuesta.json();
    if (!datos || !datos.key) return false;
    return (await canjear(datos.key)).ok;
  } catch (_) {
    return false;
  }
}

/** Muestra el error de acceso y deja a mano la entrada del PIN. */
function showAuthError(message) {
  el.pinLive.hidden = false;
  el.pinLiveValue.textContent = '········';
  el.authError.textContent = message;
  el.authError.hidden = false;
  el.pinInput.focus();
}

/**
 * Pinta la pantalla de acceso segun si la PC pide codigo o no.
 *
 * Con el control de acceso desactivado, el servidor autoriza al instante, asi
 * que normalmente ni se llega a ver esta pantalla; pero si se llega (por
 * ejemplo al activarlo de nuevo), aqui se ofrece la opcion de entrar directo.
 */
function applyAuthMode(required, pin) {
  state.authRequired = required;
  if (typeof pin === 'string' && pin) state.serverPin = pin;

  el.pinInput.hidden = !required;
  el.pinChip.textContent = required && state.serverPin
    ? state.serverPin : (required ? '······' : 'sin código');
  el.pinBtn.classList.toggle('armed', !required);
  el.authOpen.hidden = required;
  el.authHint.textContent = required
    ? 'Escribe el PIN que muestra la consola de la PC, o escanea el código QR.'
    : 'La PC tiene el código de acceso desactivado: puedes entrar directamente.';

  const boton = $('btn-authmode');
  if (boton) {
    boton.textContent = required
      ? 'Quitar el código de acceso'
      : 'Volver a pedir el código de acceso';
  }
  const info = $('auth-mode-info');
  if (info) {
    info.textContent = required
      ? 'Ahora mismo la PC pide PIN o código QR para conectarse.'
      : 'AVISO: con el código desactivado, cualquiera en tu misma WiFi puede '
        + 'manejar la PC.';
  }
}

/** Autoriza este celular cuando la PC tiene el acceso libre. */
function entrarSinCodigo() {
  send('auth', { sinCodigo: true });
  setStatus('Entrando…', 'pending');
}

/* ------------------------------------------------------------- arranque */
async function init() {
  bindUI();
  bindTyping();
  bindAtajos();
  bindMando();
  await qrLogin();
  connect();

  if ('serviceWorker' in navigator) {
    // Si hay una version nueva del service worker, se recarga la pagina: es lo
    // que evita que el celular siga con un app.js antiguo guardado.
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data && event.data.tipo === 'version-nueva') {
        window.location.reload();
      }
    });
    navigator.serviceWorker.register('sw.js', { updateViaCache: 'none' })
      .then((registration) => registration.update().catch(() => {}))
      .catch(() => {});
    // Al volver a primer plano se busca una version nueva.
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        navigator.serviceWorker.getRegistration()
          .then((registration) => registration && registration.update())
          .catch(() => {});
      }
    });
  }
}

init();
