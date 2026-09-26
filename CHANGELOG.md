# Historial de cambios

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
