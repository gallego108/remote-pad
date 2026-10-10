# Desarrollo

## Poner en marcha el entorno

```bash
git clone <url-del-repo> remote-pad
cd remote-pad/server
python -m pip install --user -r requirements.txt
python app.py --no-browser
```

No hay que compilar nada: el cliente son tres archivos estáticos y el servidor
se ejecuta directamente.

Para las pruebas más completas (opcionales, solo para desarrollo):

```bash
python -m pip install --user zxing-cpp numpy segno opencv-python-headless
```

`zxing-cpp` y `segno` permiten verificar el generador de QR contra
implementaciones de referencia; `numpy` es necesario para construir las
imágenes; `opencv-python-headless` es una segunda opinión al leer QR.

## Estructura

```
remote-pad/
├── iniciar.bat          Lanzador para el usuario final
├── probar.bat           Verificación completa (llama a tools/run_tests.py)
├── .github/workflows/   Integración continua (pruebas en Windows)
├── server/
│   ├── app.py           HTTP/WebSocket, dispositivos, bucle de animación, consola
│   ├── auth.py          PIN, QR, intentos fallidos, dispositivos, guardado atómico
│   ├── certificado.py   Certificados para --https
│   ├── controller.py    Control del escritorio (puntero, monitores, teclas)
│   ├── native_input.py  API nativa de Windows (SendInput, cursor, monitores)
│   ├── learning.py      Aprendizaje del tacto
│   ├── laser.py         Puntero láser
│   └── qr.py            Codificador de QR y dibujo en consola
├── web/
│   ├── index.html       Interfaz del celular
│   ├── styles.css       Estilos
│   ├── app.js           Gestos y comunicación
│   ├── qr.html          Panel local de la PC con el QR
│   ├── sw.js            Service worker (caché)
│   └── manifest.webmanifest
├── tools/               Pruebas y utilidades
└── docs/                Esta documentación
```

## Ejecutar las pruebas

Todo de una vez (arranca su propio servidor en el 8791, ejecuta las pruebas y
lo detiene):

```bash
python tools/run_tests.py                # todo (mueve el puntero de verdad)
python tools/run_tests.py --ci           # sin tocar el escritorio
python tools/run_tests.py test_auth      # solo las que contengan ese texto
```

`probar.bat` hace lo mismo con doble clic (y admite los mismos argumentos). La
integración continua (`.github/workflows/pruebas.yml`) ejecuta
`run_tests.py --ci` en Windows en cada push y pull request.

La lista de pruebas vive **solo** en `tools/run_tests.py`: al añadir una, se
añade ahí. Cada prueba también se puede lanzar suelta:

```bash
python tools/check_ui.py                 # HTML/CSS/JS coherentes, sin servidor
python tools/test_auth.py                # modulo de acceso, sin servidor
python tools/test_qr_capacity.py         # QR llenos al máximo (necesita zxing-cpp)

# Las que reciben puerto y PIN necesitan un servidor en marcha:
python server/app.py --port 8791 --no-browser
python tools/test_client.py --port 8791 --pin <PIN> --cursor
python tools/test_monitores.py --port 8791 --pin <PIN> [--cursor]
```

### Diagnóstico de red

Cuando el celular no conecta, este es el primero que hay que ejecutar (con el
servidor en marcha):

```bash
python tools/diagnostico_red.py 8765
python tools/ver_firewall.py       # reglas de entrada de Python, en detalle
```

`diagnostico_red.py` comprueba la dirección de escucha, el alcance por la IP de
la red local, la clasificación de la red WiFi y las reglas del Firewall.
`ver_firewall.py` desglosa las reglas de entrada que mencionan Python: sirve
para confirmar el caso típico de que **solo hay reglas UDP**, que es lo que
bloquea al celular.

### Qué cubre cada prueba

| Prueba | Cubre |
|---|---|
| `check_ui.py` | Que cada `id` y `data-*` que usa el JS exista, que las clases tengan estilo, que las acciones enviadas existan en el servidor, y que los archivos del service worker y del manifiesto existan |
| `test_client.py` | Protocolo completo, autenticación, clics, teclado, multimedia, robustez ante datos inválidos y reconexión con token |
| `test_drag.py` | Arrastre real: el puntero se mueve con el botón pulsado y se suelta al final |
| `test_qr.py` | Aritmética de QR contra la tabla oficial, estructura, ida y vuelta y lectura con zxing |
| `test_qr_capacity.py` | Que la capacidad calculada sea la real, llenando al byte exacto |
| `test_qr_window.py` | Ventana del QR: rotación automática, caducidad, uso único y petición de parada, con reloj falseado |
| `test_stop.py` | Las tres vías de parada: comando de consola, botón del celular y `/api/stop` |
| `test_qr_login.py` | Canje de la clave, token, un solo uso, rechazo de claves falsas y que el QR apunte a la IP de red |
| `test_qr_rotacion.py` | Rotación del QR, margen de gracia, un solo uso y recuperación con token |
| `test_acceso_libre.py` | El código de acceso desactivable: arranque con `--no-auth`, cambio en caliente desde el celular y desde la consola, permisos y persistencia |
| `test_version_cache.py` | Anti-caché: versión inyectada en el HTML, `no-store`, coherencia entre HTML y servidor, y service worker "red primero" |
| `test_seguridad.py` | Que el PIN no llegue a quien no está autorizado, el modo espectador solo desde la PC, el rechazo de `Origin` ajenos, el bloqueo tras 8 fallos y que el registro no escriba el PIN |
| `test_auth.py` | `auth.py` sin servidor: tokens solo como huella, migración del formato antiguo, caducidad, revocación, escritura atómica, poda de fallos, validación y migración de preferencias, nombre del dispositivo |
| `test_dispositivos.py` | Confirmación en la PC (por consola), aviso a los demás, lista de dispositivos, revocación con desconexión y reconexión sin código |
| `test_https.py` | Certificados (IP, duración, refirmado con la misma autoridad), conexión HTTPS/WSS de confianza, direcciones `https://` y `/ca.crt`. Se omite sin `cryptography` |
| `test_monitores.py` | Límite del puntero con distribuciones de monitores simuladas, controlador con dos monitores falsos, lectura real y protocolo |
| `test_atajos.py` | Validación de los atajos, ejecución en orden con teclado simulado y protocolo con pasos inofensivos |
| `test_mando.py` | Teclas mantenidas: controlador simulado, protocolo con Mayús, 30 toques rápidos sin teclas pegadas y liberación al desconectar |
| `test_aprendizaje.py` | Aprendizaje del tacto, con movimientos simulados: que baje la ganancia al pasarse, que suba al quedarse corto, que se quede neutro con uso equilibrado, los perfiles por aplicación y el guardado en disco |

### Aislamiento de los archivos de estado

`tools/run_tests.py` define `REMOTEPAD_TOKENS`, `REMOTEPAD_PROFILES`,
`REMOTEPAD_LEARNING`, `REMOTEPAD_CONFIG` y `REMOTEPAD_HTTPS_DIR` apuntando a una
carpeta temporal, así que las pruebas **no escriben** en los archivos de
`server/` del usuario. También define `REMOTEPAD_SIN_VENTANAS=1`: la
confirmación de dispositivos nuevos se responde por la consola en lugar de
abrir una ventana. Si lanzas a mano una prueba que arranca un servidor sin esas
variables, usará los archivos reales (inofensivo, pero ensucia).

## Notas para tocar el código

### `native_input.py` es la única frontera con Windows

Todo lo específico del sistema está ahí. Si algún día se quiere soportar Linux
o macOS, es el único archivo que hay que duplicar: `controller.py` y `app.py`
no saben nada de Win32.

Los prototipos de ctypes (`argtypes` y `restype`) **son obligatorios**: sin
ellos ctypes trunca los punteros de 64 bits y las llamadas fallan de formas
difíciles de diagnosticar.

### El bucle de animación es el corazón

`Gateway.animation_loop()` consume las colas y aplica los eventos al sistema.
Si tocas algo del rendimiento, es ahí. Dos reglas:

- El puntero se **consolida** (sumar y aplicar una vez).
- Los clics **no** se consolidan: se ejecutan en cuanto llegan.

### Cuidado con los hilos

`run_in_executor` recibe los argumentos **por valor**. Si pasas una variable
que el bucle de mensajes va a reasignar, el hilo puede leer el valor nuevo:

```python
# MAL: `key` puede haber cambiado cuando el hilo se ejecute
run_in_executor(executor, c.key_tap, key, mods)

# Bien: el argumento se evalúa antes de despachar
run_in_executor(executor, c.key_tap, key, list(mods))
```

Y los `lambda` que van a un hilo deben capturar por argumento por defecto:

```python
self._queue_click(lambda x=x, y=y: c.mouse_move_to(x, y))
```

### Cliente

- `web/app.js` no usa frameworks ni módulos: es un solo archivo con `'use strict'`.
- El estado de los gestos vive en el objeto `gesture`; el de la aplicación, en
  `state`. Mantener esa separación ayuda.
- Los gestos se prueban mejor en un móvil real. En el escritorio, el pad
  responde al ratón, pero sin multitáctil no se pueden probar scroll ni los
  gestos de dos y tres dedos.

### Estilo

- Comentarios y mensajes **en español, sin acentos** en el código Python (para
  evitar problemas de codificación en consolas antiguas) y con acentos en la
  documentación y en los textos de la interfaz.
- Los nombres de variables y funciones, en inglés.
- Preferir `pathlib` y `dataclasses` a cadenas y tuplas.

## Añadir una acción nueva

1. **Servidor**: añade la rama en `Gateway.handle_action()` escrita como
   `if action == "nombre":` (así la encuentra `check_ui.py`). Si es rápida y
   ligera, ejecútala directamente; si toca el sistema operativo, mándala al
   ejecutor; si el **orden** importa respecto a otras órdenes, por la cola de
   clics (`_queue_click`).
2. **Controlador**: implementa el método en `DesktopController` usando
   `native_input`.
3. **Cliente**: llama a `send('nombre_accion', { ... })`.
4. **Prueba**: añade la comprobación en `tools/test_client.py` o en una prueba
   nueva registrada en `tools/run_tests.py`.
5. Si cambia algo de `web/`, **sube la versión** (`APP_VERSION` en `app.py`,
   `REMOTEPAD_WEB` y los `?v=` de `index.html`; `test_version_cache.py` lo
   comprueba) y el nombre de la caché de `web/sw.js`.

## Registro y depuración

- El servidor registra en la consola conexiones, autorizaciones y fallos.
- Los errores de las acciones se registran con traza completa
  (`log.exception`) y se devuelven al cliente como `{ error }`.
- Los fallos de `mouse_move` y de las teclas se registran a nivel `debug`: casi
  siempre significan que la entrada no llegó al sistema operativo.
- El servidor se prueba con `--port` distinto para no chocar con una instancia
  ya en marcha; hay una prueba que usa el 8791.
