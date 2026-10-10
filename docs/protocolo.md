# Protocolo de comunicación

Todo va por un único **WebSocket** en `/ws` (y dos llamadas HTTP sueltas para
el acceso por QR). Los mensajes son objetos JSON compactos.

## Formato

```jsonc
// del celular a la PC
{ "a": "mouse_rel_move", "d": { "dx": 0.4, "dy": -1.2 }, "n": 17 }

// de la PC al celular
{ "t": "response", "a": "key_type", "d": { "ok": true } }
```

- `a`: acción (cliente → servidor).
- `d`: datos de la acción.
- `n`: número de secuencia del cliente (informativo).
- `t`: tipo de mensaje (servidor → cliente).

## Acciones del celular

### Autenticación

| Acción | Datos | Respuesta |
|---|---|---|
| `auth` | `{ token }`, `{ pin }` o `{ sinCodigo: true }` | `{ t: "ok", status: "auth", token?, device, screen, settings? }` |
| `auth_query` | — | `{ t: "auth_state", required }` — la pantalla de acceso pregunta si hace falta código. **Nunca incluye el PIN** |
| `viewer` | — | `{ t: "ok", status: "viewer", pin }` (modo espectador). **Solo desde la propia PC**; desde la red responde `denied` |

`token` solo viaja en la respuesta que crea el acceso: el servidor guarda
únicamente su huella SHA-256. `device` son los 8 primeros caracteres de esa
huella: identifica al dispositivo en la lista y para retirarle el acceso.

Si está activada la **confirmación de dispositivos nuevos**, la respuesta a un
`auth` con PIN (o al canje del QR) espera a que se permita en la PC, como
mucho 60 s; si se rechaza, llega `auth_fail`.

Si falta autenticación, el servidor responde `{ t: "auth_required" }` y, si
falla, `{ t: "auth_fail", reason }`.

Con el control de acceso desactivado, `auth` autoriza sin PIN (y reutiliza el
token si ya tenía uno válido, sin crear otro acceso), y `auth_query` responde
`required: false`.

### Puntero

| Acción | Datos | Notas |
|---|---|---|
| `mouse_rel_move` | `{ dx, dy }` | Desplazamiento relativo en unidades normalizadas |
| `mouse_move` | `{ x, y }` | Posición absoluta en píxeles del escritorio (negativos si hay un monitor a la izquierda o encima del principal) |
| `mouse_hover` | `{ dx, dy }` | Alias de `mouse_rel_move` (compatibilidad) |
| `mouse_click` | `{ button, clicks }` | `button`: `left` \| `right` \| `middle`; `clicks`: 1-3 |
| `mouse_down` | `{ button }` | Empieza un arrastre |
| `mouse_up` | `{ button }` | Termina un arrastre |
| `mouse_drag_start` | `{ x, y }` | Coloca el puntero y presiona (arrastre iniciado con el botón de la app) |
| `mouse_release_all` | — | Suelta botones y modificadores (botón **Soltar**) |
| `mouse_scroll` | `{ dx, dy }` | Unidades de deslizamiento; se convierten a rueda |
| `zoom` | `{ steps }` | Ctrl + rueda (pinza de 2 dedos). `steps > 0` acerca |
| `laser` | `{ on, x, y }` | Puntero láser. `x`, `y` normalizados (0..1); `on: false` lo apaga |

### Varios monitores

| Acción | Datos | Notas |
|---|---|---|
| `monitor_list` | — | `{ monitores: [{ x, y, w, h, primary }], actual }`. El principal va primero; `actual` es el índice del que tiene el puntero |
| `monitor_goto` | `{ index }` | Lleva el puntero al centro de ese monitor. `{ error }` si no existe |

### Portapapeles

| Acción | Datos | Notas |
|---|---|---|
| `clipboard_get` | — | Devuelve `{ ok, text }` con el texto copiado en la PC |
| `clipboard_set` | `{ text }` | Deja `text` en el portapapeles de la PC (máx. 100 000 caracteres) |

### Sistema

| Acción | Datos | Notas |
|---|---|---|
| `windows_list` | `{}` | Programas abiertos, como en la barra de tareas y del más reciente al más antiguo: `{ windows: [{ id, title, app, min, active }] }` |
| `window_focus` | `{ id }` | Trae al frente (y restaura si está minimizado) un programa de esa lista. Solo acepta ventanas que saldrían en la barra de tareas. Responde `{ ok, title, front }` o `{ error }` |
| `window` | `{ op }` | Ventana activa de la PC: `minimize`, `maximize` (si ya está maximizada, la restaura) o `close` (como su botón ✕: la aplicación puede preguntar si guardar). Responde `{ ok, title, done }` o `{ error }`. No toca el escritorio ni la barra de tareas y no cierra la consola de RemotePad |
| `keep_awake` | `{ minutes }` | Anti-apagado: mueve el ratón 1 px cada 40 s (sin desplazarlo) durante `minutes`; `on: false` lo detiene |
| `save_settings` | `{ settings }` | Guarda las preferencias del dispositivo en la PC (`server/profiles.json`). Se devuelven en el mensaje `ok` del siguiente acceso |
| `learning` | `{ on?, reset? }` | Aprendizaje del tacto: sin datos consulta el estado; `on` lo enciende/apaga; `reset` lo reinicia. Devuelve la ganancia aprendida y el estado |

### Teclado

| Acción | Datos | Notas |
|---|---|---|
| `key_type` | `{ text }` | Texto literal. `\n` = Enter, `\b` = Retroceso. Máximo 4000 caracteres |
| `key` | `{ key, mods }` | Tecla o combinación; `mods` es una lista (`["ctrl"]`) |

| `key_down` | `{ key }` | Modo mando: mantiene la tecla pulsada. Sin respuesta si va bien |
| `key_up` | `{ key }` | Suelta una tecla mantenida |
| `macro` | `{ pasos }` | Atajo personalizado (ver abajo) |

`key_down` y `key_up` se ejecutan **en orden** (por la misma cola que los
clics): un toque rápido no puede soltar la tecla antes de pulsarla. Como mucho
8 teclas mantenidas a la vez; al desconectarse el celular se sueltan todas.

Los pasos de `macro` son de tres tipos y se ejecutan en orden en la PC:

```jsonc
{ "tipo": "combo",  "tecla": "t", "mods": ["ctrl", "shift"] }
{ "tipo": "texto",  "texto": "Un saludo," }
{ "tipo": "espera", "ms": 500 }
```

Como mucho 30 pasos, 1000 caracteres por texto, 3 s por espera y 10 s de
espera en total. Las teclas y modificadores (`ctrl`, `alt`, `shift`, `win`)
deben ser conocidos; si algo no vale, la respuesta es `{ error }` con el motivo
y no se ejecuta nada.

`key` admite nombres (`left`, `f5`, `page_up`, `enter`, `esc`…) o un carácter
suelto (`"a"`, `"5"`). El texto se escribe con `KEYEVENTF_UNICODE`, así que los
acentos y símbolos funcionan con cualquier distribución de teclado.

### Multimedia y presentaciones

| Acción | Datos | Notas |
|---|---|---|
| `media` | `{ action }` | `play_pause`, `next`, `prev`, `stop`, `volume_up`, `volume_down`, `mute` |
| `media_volume` | `{ steps }` | Positivo sube, negativo baja (repite la tecla) |
| `presentation` | `{ action }` | `next`, `prev`, `start` (F5), `end` (Esc), `black`, `white`, `blank` |

### Utilidades

| Acción | Datos | Respuesta |
|---|---|---|
| `ping` | `{ ts }` | `{ t: "pong", ts }` — mide la latencia |
| `get_state` | — | Resolución de pantalla, PIN actual y segundos restantes |
| `get_driver` | — | Diagnóstico: botón y teclas que el servidor tiene presionados |
| `refresh_pin` | — | PIN y segundos restantes |
| `comando_detener` | — | Detiene el servidor. **Requiere estar ya autorizado.** Su respuesta se envía antes que el aviso `shutdown` |
| `set_auth` | `{ required }` | Quita o vuelve a pedir el código de acceso. **Requiere estar ya autorizado** |
| `devices_list` | — | `{ dispositivos: [{ id, nombre, addr, creado, visto, caduca, actual, conectado }], confirmar }` |
| `device_revoke` | `{ id }` | Retira el acceso del dispositivo cuyo `id` empieza así (mínimo 6 caracteres, coincidencia única) y lo desconecta |
| `set_confirm` | `{ on }` | Pedir (o no) permiso en la PC a cada dispositivo nuevo |

## Mensajes del servidor

| Tipo | Datos | Cuándo |
|---|---|---|
| `ok` | `status`, `token?`, `device`, `screen`, `settings?` | Autenticación correcta |
| `auth_required` | — | Hace falta autenticarse |
| `auth_fail` | `reason` | PIN incorrecto o bloqueado |
| `response` | `a`, `d` | Resultado de una acción (incluye `{ error }` si falló) |
| `pin` | `pin` | El PIN se ha renovado |
| `qr_key` | `key` | La clave del QR se ha renovado (para el panel de la PC) |
| `pong` | `ts` | Respuesta al `ping` |
| `denied` | `reason` | Acción no permitida (por ejemplo, un espectador) |
| `shutdown` | `reason` | El servidor se está deteniendo: el cliente no debe reconectar |
| `pad_input` | `from`, `d` | Retransmisión a los espectadores |
| `auth_state` | `required` | Respuesta a `auth_query` |
| `auth_mode` | `required`, `pin?` | Alguien quitó o volvió a pedir el código |
| `device_new` | `nombre`, `addr` | Ha entrado un dispositivo nuevo (a los demás autorizados) |
| `revoked` | — | Se ha retirado el acceso de este dispositivo; después se cierra la conexión |
| `keep_awake` | `active`, `remaining` | Terminó el anti-apagado |

## Reglas del servidor

- **Límite de caudal**: 450 acciones por segundo y cliente. Al superarlo se
  avisa una vez y se descartan los mensajes siguientes de ese segundo.
- **Cola de envío**: 80 mensajes por cliente; si se llena, se descarta el
  `cursor` más antiguo para no quedarse sin espacio.
- **Tamaño máximo de mensaje**: 2 MB.
- **Heartbeat**: 25 s a nivel de WebSocket, más el `ping` de la aplicación cada
  5 s para medir latencia.
- **Origen**: el WebSocket rechaza (403) las conexiones cuyo `Origin` no es
  el propio servidor. Un navegador siempre lo envía, así que otra página web
  no puede abrir una conexión con RemotePad. Los clientes que no son
  navegadores (pruebas, scripts) no lo envían y se aceptan.
- Los mensajes con JSON inválido o que no son un objeto se **ignoran** sin
  cerrar la conexión.

## Extremos HTTP

| Ruta | Método | Acceso | Descripción |
|---|---|---|---|
| `/` | GET | red local | Aplicación del celular |
| `/ws` | GET | red local | WebSocket |
| `/qr` | GET | **solo la PC** | Panel con el QR en grande y el PIN |
| `/qr/stream` | GET | **solo la PC** | Server-sent events: avisa cuando cambia la clave |
| `/qr/new` | POST | **solo la PC** | Genera un QR nuevo |
| `/api/qr-login` | POST | red local | Canjea la clave del QR por un token |
| `/api/qr-refresh` | POST | red local (exige token) | Da un QR nuevo a un dispositivo ya autorizado, para recuperarse si el código caducó al escanearlo |
| `/api/stop` | POST | **solo la PC** | Detiene el servidor |
| `/api/auth` | POST | **solo la PC** | Quita o vuelve a pedir el código de acceso |
| `/ca.crt` | GET | red local (solo con `--https`) | Autoridad local de HTTPS, para instalarla en el celular. Es la parte pública |
| `/healthz` | GET | red local | `{ "ok": true, "version": "...", "auth_required": ... }` |
| `/{archivo}` | GET | red local | Recursos estáticos (lista blanca de extensiones) |

Los recursos estáticos se sirven con lista blanca de extensiones y
comprobación de ruta, para que no se pueda salir del directorio `web/`.
