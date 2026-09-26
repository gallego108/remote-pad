# Historial de cambios

## 1.4.0

Imposible quedarse con una versión antigua de la aplicación en el celular.

Síntoma reportado: en el celular aparecía «no se pudo conectar: acción
desconocida auth». Ese texto lo genera el servidor cuando recibe una acción que
no reconoce, y el código actual **no puede** responder eso a una acción `auth`:
lo que ocurría es que el celular ejecutaba un **`app.js` guardado de una versión
anterior** (de antes de que existiera el acceso por QR), que no tenía el manejo
de `auth` y enviaba esa acción suelta. La página cargaba, pedía el PIN y el
servidor no registraba nada de QR: todo encaja.

### Corregido

- **Detector de versión en la propia página**: el servidor inyecta siempre su
  versión en el HTML, y un pequeño script del `<head>` compara con la constante
  `REMOTEPAD_WEB`. Si no cuadran (o si la página es tan antigua que no trae la
  etiqueta), **recarga con `?v=<versión>`**, que además salta la caché. Si ya lo
  intentó y sigue el desajuste, avisa en pantalla con la instrucción de vaciar
  la caché, sin entrar en bucle.
- La página principal se sirve **siempre sin caché** (`no-store`, `no-cache`,
  `Pragma` y `Expires`), con o sin QR.
- El *service worker* pide **siempre a la red** el código de la aplicación
  (`app.js`, `styles.css`, documentos) con `cache: 'no-store'`, usando la caché
  solo como respaldo sin conexión. Sube a `remotepad-v4`.
- La versión de la parte web y la del servidor deben coincidir; hay una prueba
  que lo comprueba, porque un desajuste haría recargar la página en bucle.

### Añadido

- El servidor avisa al arrancar de su versión y recuerda comprobarla en
  Ajustes del celular: en el registro se lee
  «Comprueba en el celular que la app muestre la versión 1.4.0».
- `tools/test_version_cache.py`: 16 comprobaciones de coherencia de versiones,
  cabeceras sin caché y estrategia del *service worker*.

### Nota de diagnóstico

Se descartó primero la hipótesis de que hubiera **otro servidor** en la red:
se listaron todos los servicios escuchando y se envió a cada uno la acción
`auth` para ver cuál producía el mensaje. Ninguno lo producía, y el servidor del
puerto 8765 era la versión correcta (1.3.1) con `/api/qr-login` respondiendo.
Eso dejó el cliente cacheado como única explicación posible.

## 1.3.1

Arregla que el código QR dejara de valer justo al escanearlo.

Síntoma reportado: al escanear el QR, el código cambiaba en ese instante y el
acceso fallaba («no se pudo conectar»), sin ninguna pista en la consola.

Causa: el código visible se renueva cada 3 minutos, y si el canje llegaba
después de la renovación, la clave ya no existía. Estaba reproducido: escanear
y renovar en el mismo instante daba 403.

### Corregido

- **Margen de gracia** (`QR_GRACE_SECONDS = 20`): al renovar, el código anterior
  sigue siendo válido 20 segundos más, que es lo que puede tardar el canje por
  la red. Cada código se sigue usando una sola vez.
- **Renovación anticipada**: el panel pide el siguiente código 20 segundos antes
  de que caduque el actual (`QR_PRE_REFRESH_SECONDS`), para que el cambio no
  coincida con el último segundo de vida del código.
- **Recuperación automática**: si el canje llega igualmente con un código
  caducado, el celular pide uno nuevo con `POST /api/qr-refresh` y lo canjea
  solo, sin que el usuario tenga que volver a apuntar con la cámara. Ese
  endpoint exige el token de un dispositivo ya autorizado.
- La consola **ya no redibuja el QR** cuando hay un panel abierto: mostrarlo en
  los dos sitios a la vez llenaba la ventana de códigos y confundía sobre cuál
  estaba vigente.
- Un fallo propio detectado al probarlo: la recuperación entregaba una clave ya
  consumida, así que el reintento volvía a fallar. Ahora entrega una clave
  nueva, que solo conoce ese cliente.

### Añadido

- `tools/test_qr_rotacion.py`: comprueba el margen de gracia, el uso único, la
  recuperación con token y que la recuperación exige estar autorizado.

## 1.3.0

El código QR dura 3 minutos y se puede detener el servicio.

### Cambiado

- El código QR pasa de 30 segundos a **3 minutos** (`QR_VALID_SECONDS`): da
  margen para apuntar con la cámara sin prisas. Sigue siendo de un solo uso y se
  renueva solo al agotarse la ventana (en el panel y en la consola).

### Añadido

- **Detener el servicio**, por tres vías:
  - *Ajustes → Detener RemotePad en la PC* en el celular (pide confirmación y
    solo funciona si el dispositivo **ya está autorizado**);
  - escribir **`q` + ENTER** en la consola del servidor (también acepta
    `salir`, `exit`, `quit`);
  - `POST /api/stop`, que **solo responde a la propia PC**.
- Al detenerse, los celulares conectados reciben el aviso `shutdown` y muestran
  «Servicio detenido» en lugar de «Desconectado», sin intentar reconectar.
- La consola indica ahora cómo parar (`ENTER = nuevo código QR · q = detener`) y
  despide con un mensaje claro al cerrarse.
- `/healthz` informa también de la versión del servidor.
- `tools/test_stop.py`: comprueba las tres vías de parada de extremo a extremo.

### Corregido

- **El proceso no terminaba al detener el servicio.** La parada se completaba
  (se cerraba el servidor y se soltaban los botones), pero el proceso se quedaba
  vivo: el hilo que lee la consola quedaba bloqueado en `input()` y asyncio
  espera a sus hilos antes de salir. Ahora la lectura se hace en un hilo
  demonio, y el proceso termina en menos de un segundo.
- La confirmación de `comando_detener` se envía **antes** del aviso de cierre,
  para que el celular sepa que la petición se aceptó y no solo que se ha
  desconectado.

## 1.2.0

Arregla el caso real de "el QR no entra": el celular ejecutaba una copia vieja.

Síntoma: al escanear, la página cargaba bien, **pedía el PIN** y al escribir el
código salía un error. Significa que el celular llega a la PC (red y Firewall
correctos) pero no ejecuta el canje del QR.

### Corregido

- **La clave del QR viaja ahora dentro del HTML**, en etiquetas meta, además de
  en la dirección. Algunos visores de cámara recortan el `?k=` al redirigir, y
  entonces la página cargaba y pedía el PIN sin intentar el canje: exactamente
  el síntoma reportado.
- La página del QR se sirve con `Cache-Control: no-store` y el *service worker*
  ignora las peticiones con `?k=`, así que nunca se reutiliza una copia guardada
  del enlace de acceso.
- **Un token guardado que ya no vale ya no bloquea la app.** Antes el servidor
  lo rechazaba y la pantalla se quedaba sin salida. Ahora se descarta y se
  vuelve a pedir el acceso, usando el QR de la página si lo hay.
- Si hay un QR vigente en la página y el usuario **no escribe nada**, al tocar
  el campo del PIN se usa ese código. Si empieza a escribir, se respeta el PIN.
- El service worker anterior podía dejar el `app.js` viejo en el teléfono
  (cargaba la página pero pedía el PIN). Ahora, al activarse una versión nueva,
  **avisa a las pestañas y la aplicación se recarga sola**; además busca
  actualización al volver a primer plano.

### Añadido

- La versión del servidor se muestra en *Ajustes* («versión 1.2.0»), para
  comprobar de un vistazo si el celular usa la copia nueva.
- `tools/diagnostico_qr.py`: recorre el QR como el navegador del celular (con su
  User-Agent), desde la página hasta la autenticación del WebSocket.
- `test_qr_login.py` comprueba la inyección de la clave, el estado y la versión
  en el HTML, y que esa respuesta no se cachea.

## 1.1.2

El QR de la consola ya no caduca sin remedio, y errores claros.

### Añadido

- La consola **redibuja el QR** cada vez que la clave se renueva (cada 30 s),
  para que el código a la vista no esté caducado.
- **Pulsar ENTER** en la consola imprime un QR nuevo al instante: respaldo
  cuando la consola no admite colores.
- `tools/diagnostico_qr.py` y el aviso de arranque con las instrucciones del
  Firewall.

### Cambiado

- Los mensajes del celular distinguen tres fallos: no llegar al servidor, que el
  código haya caducado (403) u otro error. Antes todos decían lo mismo.
- El servidor registra con claridad qué ha pasado: «Autorizado por token»,
  «Autorizado con el PIN», «Autorizado con el QR», «PIN incorrecto desde X (el
  PIN vigente es Y)», «Petición de acceso sin PIN ni token» y «QR rechazado: el
  código ya no vale».

## 1.1.1

Ventana del QR más corta y solución al bloqueo del Firewall.

### Cambiado

- El código QR ahora **vale 30 segundos** (antes 5 minutos) y sigue siendo de un
  solo uso. El panel de la PC genera uno nuevo automáticamente al agotarse la
  ventana, pidiéndolo **5 segundos antes** para no mostrar nunca uno caducado.
- La renovación del panel ya no necesita recargar la página: `/qr/new` devuelve
  la matriz y los datos del código nuevo.
- El flujo de eventos del panel se reconecta solo si se cae (cada 3 segundos).
- Los mensajes de la app al caducar el QR explican que hay que escanear el que
  muestra la PC en ese momento, en lugar de remitir al PIN.

### Añadido

- **`abrir-firewall.bat`**: abre el puerto del servidor en el Firewall de
  Windows pidiendo permisos de administrador. Resuelve el caso, muy habitual, de
  que el celular no pueda conectarse porque Windows no tiene ninguna regla de
  entrada **TCP** para Python (solo UDP).
- **`tools/diagnostico_red.py`**: comprueba en qué dirección escucha el
  servidor, si responde por la IP de la red local, cómo está clasificada la red
  WiFi y qué reglas del Firewall afectan al puerto.
- **`tools/test_qr_window.py`**: verifica la ventana de 30 segundos con un reloj
  falseado (rotación automática, caducidad, uso único y que el PIN no cambia
  cada 30 segundos).
- **`tools/ver_firewall.py`**: muestra las reglas de entrada de Python para
  diagnosticar el bloqueo.

### Corregido

- La prueba del panel comprobaba que `/qr/new` devolvía `ok`; ahora comprueba
  que devuelve un QR utilizable, que apunta a la IP de la red y que su clave
  sirve para entrar.

## 1.1.0

Acceso con código QR.

### Añadido

- **Acceso por código QR**: la consola dibuja un QR que, al escanearlo con la
  cámara, abre la app en el celular y entra directamente, sin escribir el PIN.
- **Panel `/qr`** en la PC con el código en grande, cuenta atrás y botón para
  generar uno nuevo. Se actualiza solo por *server-sent events*.
- **`server/qr.py`**: codificador de QR completo (versiones 1-10, cuatro
  niveles de corrección, máscara óptima, dibujo en consola con color ANSI), sin
  dependencias externas.
- Opción `--no-qr` para desactivarlo.
- Documentación en `docs/` y este historial.

### Seguridad

- La clave que viaja en el QR es de **un solo uso** y caduca a los 5 minutos,
  así que el enlace guardado en el historial deja de servir.
- El panel `/qr` **solo responde a la propia PC** porque contiene el PIN y la
  clave.
- Límite de 10 intentos fallidos de clave QR por dirección.

### Corregido

- La dirección del QR usaba `127.0.0.1` (la del panel), que en el celular no
  significa nada: ahora apunta a la IP de la red local.
- La limpieza de botones y teclas se ejecutaba en cada ciclo del bucle cuando no
  había clientes conectados; ahora solo en la transición.

## 1.0.0

Primera versión funcional.

### Añadido

- Touchpad con deslizamiento de un dedo, sensibilidad ajustable, aceleración y
  zonas de borde aceleradas.
- Clic izquierdo, derecho y central (uno, dos y tres dedos), doble clic.
- Scroll con dos dedos, con desplazamiento natural opcional.
- Arrastrar y soltar con pulsación larga y con arrastre fijo (doble toque).
- Teclado remoto con acentos y símbolos, teclas especiales y 21 atajos.
- Panel de multimedia (reproducir, pistas, volumen, silencio) y de
  presentaciones (avanzar, retroceder, iniciar, pantalla en negro o blanco).
- Acceso con PIN de 6 dígitos rotativo cada 5 minutos y token por dispositivo.
- Servidor `aiohttp` con bucle de animación que consolida movimientos.
- Capa nativa de Windows (`native_input.py`) con `SendInput`, sin `pynput`.
- Aplicación web instalable como PWA, con funcionamiento sin conexión.
- Pruebas: protocolo completo, arrastre real, coherencia de la interfaz.

### Notas de desarrollo

- **`pynput` 1.8.2 está roto con Python 3.12 en Windows**: su llamada a
  `SendInput` lanza `ArgumentError: expected LP__INPUT instance`, de modo que el
  puntero y todas las teclas fallaban en silencio. Se sustituyó por una capa
  nativa.
- **`GetAsyncKeyState` no refleja los botones inyectados** con `SendInput`, así
  que la detección de arrastre se apoya en el estado propio del controlador.
