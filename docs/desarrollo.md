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
├── probar.bat           Verificación completa
├── server/
│   ├── app.py           HTTP/WebSocket, autenticación, bucle de animación
│   ├── controller.py    Control del escritorio (estado del puntero)
│   ├── native_input.py  API nativa de Windows (SendInput, cursor, rueda)
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

```bash
python tools/check_ui.py                 # HTML/CSS/JS coherentes, sin servidor
python tools/test_qr.py                  # generador de QR (no necesita servidor)
python tools/test_qr_capacity.py         # QR llenos al máximo (necesita zxing-cpp)
python tools/verify_rs.py                # Reed-Solomon (no necesita servidor)

# Las siguientes necesitan un servidor en marcha:
python app.py --port 8791 --no-browser &
python tools/test_client.py --port 8791 --pin <PIN> --cursor
python tools/test_drag.py   --port 8791 --pin <PIN>
python tools/test_qr_login.py 8791
```

O todo de una vez con `probar.bat`, que arranca su propio servidor, comprueba y
lo detiene.

### Qué cubre cada prueba

| Prueba | Cubre |
|---|---|
| `check_ui.py` | Que cada `id` y `data-*` que usa el JS exista, que las clases tengan estilo, que las acciones enviadas existan en el servidor, y que los archivos del service worker y del manifiesto existan |
| `test_client.py` | Protocolo completo, autenticación, clics, teclado, multimedia, robustez ante datos inválidos y reconexión con token |
| `test_drag.py` | Arrastre real: el puntero se mueve con el botón pulsado y se suelta al final |
| `test_qr.py` | Aritmética de QR contra la tabla oficial, estructura, ida y vuelta y lectura con zxing |
| `test_qr_capacity.py` | Que la capacidad calculada sea la real, llenando al byte exacto |
| `test_qr_login.py` | Canje de la clave, token, un solo uso, rechazo de claves falsas |

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

1. **Servidor**: añade la rama en `Gateway.handle_action()`. Si es rápida y
   ligera, ejecútala directamente; si toca el sistema operativo, mándala al
   ejecutor.
2. **Controlador**: implementa el método en `DesktopController` usando
   `native_input`.
3. **Cliente**: llama a `send('nombre_accion', { ... })`.
4. **Prueba**: añade la comprobación en `tools/test_client.py`.

## Registro y depuración

- El servidor registra en la consola conexiones, autorizaciones y fallos.
- Los errores de las acciones se registran con traza completa
  (`log.exception`) y se devuelven al cliente como `{ error }`.
- Los fallos de `mouse_move` y de las teclas se registran a nivel `debug`: casi
  siempre significan que la entrada no llegó al sistema operativo.
- El servidor se prueba con `--port` distinto para no chocar con una instancia
  ya en marcha; hay una prueba que usa el 8791.
