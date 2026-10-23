'use strict';

// Panel de escritorio de RemotePad. La logica vive en remotepad_escritorio.py
// (window.pywebview.api); aqui solo se pinta y se llama. Todo texto que viene
// del servidor se pone con textContent, nunca con innerHTML.

const estado = {
  activo: false,
  servidor: null,
  ajustes: null,
  pagina: 'inicio',
  pinSegundos: 0,
  qrSegundos: 0,
  qrUrl: '',
  qrRenovando: false,
  registroTodas: [],
  registroMarca: 0,
  registroFirma: '',
  pausado: false,
  ajustesSeguridadPendientes: 0,
};

// ------------------------------------------------------------------ ayudas
const $ = (id) => document.getElementById(id);

function crear(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined && texto !== null) nodo.textContent = String(texto);
  return nodo;
}

function vaciar(nodo) {
  while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
}

function api() {
  return window.pywebview && window.pywebview.api;
}

async function llamar(metodo, ...args) {
  try {
    return await api()[metodo](...args);
  } catch (error) {
    return { ok: false, motivo: 'No se pudo hablar con la app (' + metodo + ')' };
  }
}

let temporizadorToast = null;
function avisar(texto, error = false) {
  const caja = $('toast');
  caja.textContent = texto;
  caja.classList.toggle('error', error);
  caja.classList.remove('oculto');
  clearTimeout(temporizadorToast);
  temporizadorToast = setTimeout(() => caja.classList.add('oculto'), 3200);
}

function formatoPin(pin) {
  const limpio = String(pin || '').replace(/\D/g, '');
  if (limpio.length !== 6) return '— —';
  return limpio.slice(0, 3) + ' ' + limpio.slice(3);
}

function formatoSegundos(segundos) {
  const s = Math.max(0, Math.floor(segundos));
  const min = Math.floor(s / 60);
  const resto = String(s % 60).padStart(2, '0');
  return min + ':' + resto;
}

function hacePoco(segundosUnix) {
  if (!segundosUnix) return 'nunca';
  const diff = Date.now() / 1000 - segundosUnix;
  if (diff < 60) return 'hace un momento';
  if (diff < 3600) return 'hace ' + Math.floor(diff / 60) + ' min';
  if (diff < 86400) return 'hace ' + Math.floor(diff / 3600) + ' h';
  const dias = Math.floor(diff / 86400);
  return 'hace ' + dias + (dias === 1 ? ' día' : ' días');
}

function fechaCorta(segundosUnix) {
  if (!segundosUnix) return '—';
  return new Date(segundosUnix * 1000).toLocaleDateString('es-ES', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

// ----------------------------------------------------------------- modal
function preguntar({ titulo, texto, acciones }) {
  return new Promise((resolver) => {
    $('modal-titulo').textContent = titulo;
    $('modal-texto').textContent = texto;
    const cont = $('modal-acciones');
    vaciar(cont);
    const cerrar = (valor) => {
      $('modal').classList.add('oculto');
      resolver(valor);
    };
    acciones.forEach((a) => {
      const boton = crear('button', 'boton ' + (a.clase || 'boton-suave'), a.texto);
      boton.addEventListener('click', () => cerrar(a.valor));
      cont.appendChild(boton);
    });
    $('modal').classList.remove('oculto');
  });
}

// ----------------------------------------------------------- navegacion
function irA(pagina) {
  estado.pagina = pagina;
  document.querySelectorAll('.menu-item').forEach((b) =>
    b.classList.toggle('activo', b.dataset.pagina === pagina));
  document.querySelectorAll('.pagina').forEach((s) =>
    s.classList.toggle('activa', s.dataset.pagina === pagina));
  if (pagina === 'registro') cargarRegistro();
  if (pagina === 'programas') cargarProgramas();
  if (pagina === 'dispositivos') pintarDispositivos();
  if (pagina === 'ajustes') cargarLanzamiento();
}

// --------------------------------------------------------------- estado
async function refrescarEstado() {
  const datos = await llamar('estado');
  if (!datos || !datos.servidor) return;
  estado.activo = !!datos.activo;
  estado.servidor = datos.servidor;
  estado.ajustes = datos.ajustes;
  pintarBarra();
  pintarInicio();
  pintarPendiente();
  $('aviso-elevado').classList.toggle('oculto', !hayAvisoElevado(datos.servidor));
  pintarAjustesSeguridad();
  pintarDispositivos();
}

function pintarBarra() {
  const on = estado.activo;
  $('estado-punto').classList.toggle('on', on);
  $('estado-texto').textContent = on ? 'Servidor encendido' : 'Servidor apagado';
  $('btn-encender').classList.toggle('oculto', on);
  $('btn-parar').classList.toggle('oculto', !on);
  const version = estado.servidor.version || '';
  $('version').textContent = version ? 'v' + version : '';
  $('acerca-version').textContent = version || '—';
}

function pintarInicio() {
  const s = estado.servidor;
  const on = estado.activo;
  $('inicio-apagado').classList.toggle('oculto', on);
  $('inicio-encendido').classList.toggle('oculto', !on);
  $('inicio-sub').textContent = on
    ? (s.clientes ? s.clientes + ' móvil(es) conectado(s) ahora' : 'Listo para recibir móviles')
    : 'Apagado';

  if (!on) {
    $('pin').textContent = '— —';
    return;
  }

  const url = (estado.ajustes.https ? 'https' : 'http') + '://' +
    (s.lan_host || '127.0.0.1') + ':' + s.port;
  $('url-lan').textContent = estado.ajustes.red === '127.0.0.1'
    ? 'Solo esta PC (127.0.0.1)' : url;
  $('clientes').textContent = String(s.clientes || 0);
  $('puerto').textContent = String(s.port);
  $('https').textContent = s.https ? 'Sí' : 'No';

  $('pin').textContent = formatoPin(s.pin);
  estado.pinSegundos = s.pin_seconds || 0;

  $('acceso-estado').textContent = s.auth_required ? 'Activado' : 'Desactivado';
  $('acceso-resumen').textContent = s.auth_required
    ? 'El móvil pide el PIN o el QR antes de entrar.'
    : 'Cualquier móvil de tu WiFi entra sin PIN.';
  $('acceso-numero').textContent = String((s.dispositivos || []).length);

  if (s.qr_url && s.qr_url !== estado.qrUrl) {
    estado.qrUrl = s.qr_url;
    estado.qrSegundos = s.qr_seconds || 0;
    cargarQrActual();
  } else if (typeof s.qr_seconds === 'number') {
    estado.qrSegundos = s.qr_seconds;     // el servidor manda la cuenta atras real
  }
}

// ------------------------------------------------------------ codigo QR
function dibujarQr(matriz) {
  const caja = $('qr-caja');
  vaciar(caja);
  if (!matriz || !matriz.length) {
    caja.appendChild(crear('div', 'vacio', 'Enciende el servidor para ver el código'));
    return;
  }
  const n = matriz.length;
  const margen = 4;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + (n + margen * 2) + ' ' + (n + margen * 2));
  svg.setAttribute('shape-rendering', 'crispEdges');
  svg.setAttribute('role', 'img');
  const titulo = document.createElementNS(ns, 'title');
  titulo.textContent = 'Código QR para conectar el móvil';
  svg.appendChild(titulo);
  let trazo = '';
  matriz.forEach((fila, y) => {
    fila.forEach((oscuro, x) => {
      if (oscuro) trazo += 'M' + (x + margen) + ' ' + (y + margen) + 'h1v1h-1z';
    });
  });
  const camino = document.createElementNS(ns, 'path');
  camino.setAttribute('d', trazo);
  camino.setAttribute('fill', '#000');
  svg.appendChild(camino);
  caja.appendChild(svg);
}

async function cargarQrActual() {
  const datos = await llamar('qr_actual');
  if (datos && datos.matrix) {
    dibujarQr(datos.matrix);
    estado.qrSegundos = datos.seconds || estado.qrSegundos;
  }
}

async function nuevoQr() {
  if (!estado.activo) return avisar('Enciende el servidor primero', true);
  estado.qrRenovando = true;
  const datos = await llamar('qr_nuevo');
  estado.qrRenovando = false;
  if (datos && datos.matrix) {
    estado.qrUrl = datos.url;
    estado.qrSegundos = datos.seconds || 0;
    dibujarQr(datos.matrix);
    avisar('Código QR nuevo');
  } else {
    avisar((datos && datos.motivo) || 'No se pudo generar el QR', true);
  }
}

async function nuevoPin() {
  if (!estado.activo) return avisar('Enciende el servidor primero', true);
  const datos = await llamar('pin_nuevo');
  if (datos && datos.pin) {
    $('pin').textContent = formatoPin(datos.pin);
    avisar('PIN nuevo');
    refrescarEstado();
  } else {
    avisar((datos && datos.motivo) || 'No se pudo generar el PIN', true);
  }
}

// --------------------------------------------------- temporizadores (1 s)
function tictac() {
  if (estado.activo) {
    estado.pinSegundos = Math.max(0, estado.pinSegundos - 1);
    $('pin-tiempo').textContent = estado.pinSegundos > 0
      ? 'Cambia en ' + formatoSegundos(estado.pinSegundos) : '';
    estado.qrSegundos = Math.max(0, estado.qrSegundos - 1);
    $('qr-tiempo').textContent = estado.qrSegundos > 0
      ? 'Vale ' + formatoSegundos(estado.qrSegundos) : 'Caducado';
    if (estado.qrSegundos === 0 && !estado.qrRenovando) nuevoQr();
  }
}

// ------------------------------------------------------- avisos y acceso
function hayAvisoElevado(servidor) {
  return !!(servidor && servidor.aviso_elevado);
}

function pintarPendiente() {
  const p = estado.servidor.pendiente;
  $('pendiente').classList.toggle('oculto', !p);
  if (!p) return;
  $('pendiente-nombre').textContent = p.nombre + ' (' + p.addr + ')';
  $('pendiente-texto').textContent = 'quiere manejar esta PC. ¿Lo permites?';
}

async function responderPendiente(permitir) {
  const datos = await llamar('responder_confirmacion', permitir);
  avisar(datos && datos.ok ? (permitir ? 'Acceso permitido' : 'Acceso rechazado')
    : 'Ya no hay nadie esperando', !(datos && datos.ok));
  refrescarEstado();
}

function pintarAjustesSeguridad() {
  if (estado.ajustesSeguridadPendientes > 0) return;   // no pisar lo que el usuario acaba de cambiar
  const s = estado.servidor;
  $('ajs-auth').checked = !!s.auth_required;
  $('ajs-confirmar').checked = !!s.confirmar_nuevos;
}

async function cambiarSeguridad(clave, valor) {
  estado.ajustesSeguridadPendientes += 1;
  const datos = await llamar('ajustes_seguridad', { [clave]: valor });
  estado.ajustesSeguridadPendientes -= 1;
  if (datos && datos.ok) {
    avisar(clave === 'auth_required'
      ? (valor ? 'Código de acceso activado' : 'Código de acceso desactivado')
      : (valor ? 'Los dispositivos nuevos pedirán permiso' : 'Los dispositivos nuevos entran con el PIN o el QR'));
  } else {
    avisar('No se pudo guardar el cambio', true);
  }
  refrescarEstado();
}

// ----------------------------------------------------------- dispositivos
function pintarDispositivos() {
  if (estado.pagina !== 'dispositivos' || !estado.servidor) return;
  const cont = $('lista-dispositivos');
  vaciar(cont);
  const filas = estado.servidor.dispositivos || [];
  if (!filas.length) {
    cont.appendChild(crear('div', 'vacio-lista', 'Ningún móvil tiene acceso todavía.'));
    return;
  }
  filas.forEach((d) => {
    const fila = crear('div', 'fila');
    const info = crear('div', 'fila-info');
    const titulo = crear('div', 'fila-titulo', d.nombre || 'Dispositivo');
    if (d.conectado) titulo.appendChild(crear('span', 'chip on', 'conectado'));
    info.appendChild(titulo);
    const detalle = [
      d.addr ? 'Dirección ' + d.addr : null,
      'Última vez ' + hacePoco(d.visto),
      'Caduca el ' + fechaCorta(d.caduca),
    ].filter(Boolean).join(' · ');
    info.appendChild(crear('div', 'sub', detalle));
    fila.appendChild(info);
    const revocar = crear('button', 'boton boton-peligro boton-pequeno', 'Revocar');
    revocar.addEventListener('click', () => revocarDispositivo(d));
    fila.appendChild(revocar);
    cont.appendChild(fila);
  });
}

async function revocarDispositivo(d) {
  const quiere = await preguntar({
    titulo: 'Revocar acceso',
    texto: '«' + (d.nombre || 'este dispositivo') + '» dejará de poder manejar esta PC. '
      + 'Para volver a entrar tendrá que usar el PIN o el QR.',
    acciones: [
      { texto: 'Cancelar', valor: false },
      { texto: 'Revocar', clase: 'boton-peligro', valor: true },
    ],
  });
  if (!quiere) return;
  const datos = await llamar('revocar', d.id);
  if (datos && datos.ok) avisar('Acceso retirado: ' + (datos.nombre || d.nombre));
  else avisar('No se pudo retirar el acceso', true);
  refrescarEstado();
}

// -------------------------------------------------------------- registro
const NIVELES = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 3 };

function filtrarRegistro(entradas) {
  const minimo = NIVELES[$('reg-nivel').value] || 0;
  const buscar = $('reg-buscar').value.trim().toLowerCase();
  return entradas.filter((e) =>
    (NIVELES[e.nivel] || 0) >= minimo &&
    (!buscar || (e.texto + ' ' + e.hora).toLowerCase().includes(buscar)));
}

function pintarRegistro() {
  const caja = $('registro');
  // Solo se sigue el final si ya estabas abajo: si estas leyendo mas arriba, no te mueve.
  const cerca = caja.scrollTop + caja.clientHeight >= caja.scrollHeight - 40;
  const visibles = filtrarRegistro(estado.registroTodas.slice(estado.registroMarca));
  const buscar = $('reg-buscar').value.trim();
  vaciar(caja);
  if (!visibles.length) {
    caja.appendChild(crear('div', 'vacio-lista', 'Sin entradas. Cuando el servidor haga algo, aparecerá aquí.'));
    return;
  }
  visibles.forEach((e) => {
    const linea = crear('div', 'linea nivel-' + e.nivel);
    linea.appendChild(crear('span', 'hora', e.hora));
    linea.appendChild(crear('span', 'nivel', e.nivel));
    if (buscar) resaltar(linea, e.texto, buscar);
    else linea.appendChild(document.createTextNode(e.texto));
    caja.appendChild(linea);
  });
  if (cerca) caja.scrollTop = caja.scrollHeight;
}

function resaltar(nodo, texto, buscar) {
  const bajo = texto.toLowerCase();
  const aguja = buscar.toLowerCase();
  let pos = 0;
  let idx = bajo.indexOf(aguja);
  while (idx !== -1) {
    nodo.appendChild(document.createTextNode(texto.slice(pos, idx)));
    nodo.appendChild(crear('mark', null, texto.slice(idx, idx + aguja.length)));
    pos = idx + aguja.length;
    idx = bajo.indexOf(aguja, pos);
  }
  nodo.appendChild(document.createTextNode(texto.slice(pos)));
}

async function cargarRegistro() {
  if (estado.pausado) return;
  const entradas = await llamar('registro');
  if (!Array.isArray(entradas)) return;
  const firma = entradas.length + '|' + (entradas.length ? entradas[entradas.length - 1].texto : '');
  if (firma === estado.registroFirma) return;
  estado.registroFirma = firma;
  estado.registroTodas = entradas;
  if (estado.registroMarca > entradas.length) estado.registroMarca = 0;   // el archivo se rotó
  pintarRegistro();
}

// ------------------------------------------------------------- programas
let ultimosProgramas = null;

async function cargarProgramas() {
  const lista = await llamar('programas');
  ultimosProgramas = Array.isArray(lista) ? lista : [];
  pintarProgramas();
}

function pintarProgramas() {
  const cont = $('lista-programas');
  vaciar(cont);
  const lista = ultimosProgramas || [];
  if (!lista.length) {
    cont.appendChild(crear('div', 'vacio-lista', 'Aún no hay programas. Se anotan cuando cambias de ventana.'));
    return;
  }
  lista.forEach((p) => {
    const fila = crear('div', 'fila');
    const info = crear('div', 'fila-info');
    info.appendChild(crear('div', 'fila-titulo', p.name || p.app || p.id));
    const detalle = [p.app, 'Usado ' + hacePoco(p.last)].filter(Boolean).join(' · ');
    info.appendChild(crear('div', 'sub', detalle));
    fila.appendChild(info);
    const quitar = crear('button', 'boton boton-peligro boton-pequeno', 'Quitar');
    quitar.addEventListener('click', () => quitarPrograma(p));
    fila.appendChild(quitar);
    cont.appendChild(fila);
  });
}

async function quitarPrograma(p) {
  const datos = await llamar('programa_quitar', p.id);
  if (datos && datos.ok) {
    ultimosProgramas = ultimosProgramas.filter((x) => x.id !== p.id);
    pintarProgramas();
    avisar('Quitado del historial');
  } else {
    avisar('No se pudo quitar', true);
  }
}

// ------------------------------------------------------------- lanzamiento
async function cargarLanzamiento() {
  const a = await llamar('lanzamiento_leer');
  if (!a || a.puerto === undefined) return;
  $('lan-puerto').value = a.puerto;
  $('lan-red').value = a.red;
  $('lan-https').checked = !!a.https;
  $('lan-auto').checked = !!a.arrancar_servidor;
  $('lan-inicio').checked = !!a.inicio_windows;
  $('lan-aviso').textContent = estado.activo
    ? 'Los cambios se aplican al encender el servidor de nuevo.' : '';
}

async function guardarLanzamiento() {
  const puerto = parseInt($('lan-puerto').value, 10);
  if (!(puerto >= 1 && puerto <= 65535)) {
    avisar('El puerto tiene que estar entre 1 y 65535', true);
    return;
  }
  const datos = await llamar('lanzamiento_guardar', {
    puerto,
    red: $('lan-red').value,
    https: $('lan-https').checked,
    arrancar_servidor: $('lan-auto').checked,
    inicio_windows: $('lan-inicio').checked,
  });
  if (datos && datos.ok) {
    avisar('Ajustes guardados');
    $('lan-aviso').textContent = estado.activo
      ? 'Reinicia el servidor para aplicar los cambios de red o puerto.' : '';
  } else {
    avisar('No se pudieron guardar', true);
  }
}

// ----------------------------------------------------------- encender/parar
async function encender() {
  const datos = await llamar('arrancar');
  avisar(datos && datos.ok ? 'Encendiendo RemotePad…' : 'No se pudo encender', !(datos && datos.ok));
  setTimeout(refrescarEstado, 1200);
  setTimeout(refrescarEstado, 3000);
}

async function parar() {
  const quiere = await preguntar({
    titulo: 'Parar RemotePad',
    texto: 'Los móviles conectados se desconectarán y no podrán manejar esta PC hasta que lo enciendas.',
    acciones: [
      { texto: 'Cancelar', valor: false },
      { texto: 'Parar', clase: 'boton-peligro', valor: true },
    ],
  });
  if (!quiere) return;
  const datos = await llamar('parar');
  avisar(datos && datos.ok ? 'Servidor parado' : (datos && datos.motivo) || 'No se pudo parar', !(datos && datos.ok));
  refrescarEstado();
}

// ------------------------------------------------------------ actualizar
let actualizacionLista = null;

async function buscarActualizacion() {
  $('act-estado').textContent = 'Buscando…';
  $('act-instalar').classList.add('oculto');
  const datos = await llamar('buscar_actualizacion');
  if (datos && datos.disponible) {
    actualizacionLista = datos;
    $('act-estado').textContent = 'Hay una versión nueva: ' + datos.version
      + ' (tienes la ' + (estado.servidor.version || '?') + ').';
    $('act-notas').textContent = datos.notas || '';
    $('act-instalar').classList.remove('oculto');
    $('act-instalar').disabled = false;
  } else {
    actualizacionLista = null;
    $('act-estado').textContent = datos && datos.error
      ? datos.error
      : 'Ya tienes la última versión (' + ((datos && datos.version) || estado.servidor.version || '?') + ').';
    $('act-notas').textContent = '';
  }
}

async function instalarActualizacion() {
  if (!actualizacionLista) return;
  const quiere = await preguntar({
    titulo: 'Actualizar RemotePad',
    texto: 'Se parará el servidor, se cerrará este panel y se abrirá el instalador de la versión '
      + actualizacionLista.version + '. Windows te pedirá confirmar el aviso de seguridad.',
    acciones: [
      { texto: 'Cancelar', valor: false },
      { texto: 'Actualizar', clase: 'boton-principal', valor: true },
    ],
  });
  if (!quiere) return;
  $('act-instalar').disabled = true;
  $('act-estado').textContent = 'Descargando y comprobando la huella…';
  const datos = await llamar('instalar_actualizacion', actualizacionLista.url, actualizacionLista.sha256);
  if (!datos || !datos.ok) {
    $('act-instalar').disabled = false;
    $('act-estado').textContent = 'No se pudo actualizar.';
    avisar((datos && datos.motivo) || 'No se pudo actualizar', true);
  }
}

async function salirDeLaApp() {
  const eleccion = await preguntar({
    titulo: 'Salir de RemotePad',
    texto: 'La app se cierra. ¿Quieres dejar el servidor encendido?',
    acciones: [
      { texto: 'Cancelar', valor: null },
      { texto: 'Salir y parar', clase: 'boton-peligro', valor: true },
      { texto: 'Salir y dejar encendido', clase: 'boton-principal', valor: false },
    ],
  });
  if (eleccion === null) return;
  api().salir(eleccion);
}

// Llamada desde Python (icono de la bandeja): no devuelve nada, para que evaluate_js no espere una promesa.
function pedirSalida() {
  salirDeLaApp();
}

// ----------------------------------------------------------------- inicio
function iniciar() {
  document.querySelectorAll('.menu-item').forEach((b) =>
    b.addEventListener('click', () => irA(b.dataset.pagina)));
  document.querySelectorAll('[data-ir]').forEach((b) =>
    b.addEventListener('click', () => irA(b.dataset.ir)));

  $('btn-encender').addEventListener('click', encender);
  $('inicio-encender').addEventListener('click', encender);
  $('btn-parar').addEventListener('click', parar);
  $('btn-salir-app').addEventListener('click', salirDeLaApp);
  $('act-buscar').addEventListener('click', buscarActualizacion);
  $('act-instalar').addEventListener('click', instalarActualizacion);
  $('btn-qr').addEventListener('click', nuevoQr);
  $('btn-pin').addEventListener('click', nuevoPin);

  $('pendiente-si').addEventListener('click', () => responderPendiente(true));
  $('pendiente-no').addEventListener('click', () => responderPendiente(false));

  $('ajs-auth').addEventListener('change', async (ev) => {
    const activar = ev.target.checked;
    if (!activar) {
      const ok = await preguntar({
        titulo: 'Quitar el código de acceso',
        texto: 'Cualquier móvil de tu WiFi podrá manejar esta PC sin PIN ni QR. ¿Seguro?',
        acciones: [
          { texto: 'Cancelar', valor: false },
          { texto: 'Quitar código', clase: 'boton-peligro', valor: true },
        ],
      });
      if (!ok) {
        ev.target.checked = true;
        return;
      }
    }
    cambiarSeguridad('auth_required', activar);
  });
  $('ajs-confirmar').addEventListener('change', (ev) =>
    cambiarSeguridad('confirmar_nuevos', ev.target.checked));

  $('lan-guardar').addEventListener('click', guardarLanzamiento);

  $('reg-buscar').addEventListener('input', pintarRegistro);
  $('reg-nivel').addEventListener('change', pintarRegistro);
  $('reg-pausa').addEventListener('click', () => {
    estado.pausado = !estado.pausado;
    $('reg-pausa').textContent = estado.pausado ? 'Reanudar' : 'Pausar';
    if (!estado.pausado) cargarRegistro();
  });
  $('reg-limpiar').addEventListener('click', () => {
    estado.registroMarca = estado.registroTodas.length;
    pintarRegistro();
  });
  $('reg-carpeta').addEventListener('click', () => llamar('abrir_carpeta_registro'));

  refrescarEstado();
  cargarLanzamiento();
  setInterval(refrescarEstado, 2000);
  setInterval(tictac, 1000);
  setInterval(() => { if (estado.pagina === 'registro') cargarRegistro(); }, 1500);
}

// pywebview avisa cuando su puente con Python esta listo.
if (window.pywebview && window.pywebview.api) {
  iniciar();
} else {
  window.addEventListener('pywebviewready', iniciar);
}
