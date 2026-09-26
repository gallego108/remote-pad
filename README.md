# RemotePad — tu celular como touchpad del PC

Convierte tu celular Android en un **touchpad inalámbrico** para tu PC con
Windows: mueve el puntero, haz clic, arrastra, escribe y controla el volumen,
todo desde el navegador del teléfono y por tu propia red WiFi.

No hay que instalar nada en el celular: el servidor de la PC sirve la
aplicación web, y el teléfono solo tiene que abrir una dirección.

---

## Puesta en marcha (1 minuto)

1. **Conecta el celular a la misma red WiFi que la PC.**
2. En la PC, haz doble clic en **`iniciar.bat`**.
3. En la consola verás el PIN **y un código QR**:

   ```
   ==========================================================
      PIN DE ACCESO  ->  482 913
      (cambia automáticamente cada 5 minutos)
   ==========================================================
      Abre esta direccion en el navegador del celular:
          http://192.168.1.9:8765
   ==========================================================
      O escanea este QR y entra sin escribir nada:

        ▄▄▄▄▄▄▄ ▄ ▄▄▄▄▄ ▄▄▄▄▄▄▄
        █ ▄▄▄ █ ▀█▄▀ █ ▄▄▄ █
        █ ███ █ ▄▀▄▄ █ ███ █
        ...
   ```

4. **Apunta con la cámara del celular al código**: se abre el navegador solo y
   entras directamente, sin escribir nada.
5. Si el QR no te resulta cómodo, abre `http://192.168.1.9:8765` y escribe el
   PIN de 6 dígitos.

> **Si el QR no cabe en la consola**, en la PC se abre automáticamente una
> página con el código en grande (`http://127.0.0.1:8765/qr`), con un botón
> para generar uno nuevo cuando quieras.

> **La primera vez**, Windows preguntará si quieres permitir el tráfico de red
> para Python. Marca **Redes privadas** y acepta; si lo cancelas, el celular no
> podrá conectarse.

**Para no repetir el acceso:** en Chrome, menú ⋮ → *Añadir a pantalla de
inicio*. Así queda como una app con su icono, y el dispositivo recuerda el
acceso (guarda un token propio): las próximas veces entra directo.

### Cómo funciona el código QR

El QR contiene una dirección con una **clave de un solo uso**
(`http://192.168.1.9:8765/?k=...`). Al escanearlo, el celular canjea esa clave
por un token de dispositivo y entra sin pedir el PIN.

- La clave **caduca a los 5 minutos** y **se invalida al primer uso**, así que
  el enlace que quede en el historial del navegador ya no sirve.
- Solo lo puede leer quien esté delante de la pantalla de tu PC (o quien tú se
  lo muestres), igual que el PIN.
- La página que muestra el código en grande **solo responde a la propia PC**:
  contiene el PIN y la clave, así que no se sirve al resto de la red.
- Si lo prefieres, puedes desactivarlo con `--no-qr`.

---

## Gestos del touchpad

| Gesto | Acción |
|---|---|
| Deslizar 1 dedo | Mover el puntero |
| Tocar la pantalla | Clic izquierdo |
| Tocar dos veces seguidas | Doble clic |
| Tocar con 2 dedos a la vez | Clic derecho |
| Deslizar con 2 dedos | Scroll vertical y horizontal |
| Tocar con 3 dedos | Clic central (abrir en pestaña nueva…) |
| Mantener pulsado (0,4 s) | Arrastrar mientras no levantes el dedo |
| Doble toque y deslizar sin levantar | Arrastre fijo, hasta que toques otra vez |

Los botones **Clic izq. / Clic der. / Soltar / Reconectar** están siempre a la
vista. El botón de la barra superior (**Puntero**) hace de interruptor maestro
para el arrastre fijo: si algo se queda "pegado", pulsa **Soltar**.

### Paneles inferiores

- **Teclado** — escribe en el campo y el texto aparece en la PC tal cual
  (acentos, `@`, `¿`, emoji). Debajo tienes Enter, Tab, Esc, flechas, etc.
- **Atajos** — copiar, pegar, deshacer, Alt+Tab, F11, bloquear la PC…
- **Multimedia** — ⏮ ⏯ ⏭, silencio y subir/bajar volumen.
- **Presentar** — anterior/siguiente diapositiva, iniciar (F5), salir, y
  pantalla en negro o blanco (PowerPoint, Impress y similares).
- **Ajustes** — velocidad del puntero y del scroll, aceleración, desplazamiento
  natural, vibración y el desbloqueo del dispositivo.

---

## Seguridad

- **PIN de 6 dígitos** que se muestra **solo en la pantalla de la PC** y se
  renueva **cada 5 minutos** (o antes, si toca el botón PIN de la app).
- **Código QR de un solo uso**: su clave caduca en 5 minutos y se invalida al
  primer escaneo, así que el enlace del historial del navegador deja de servir.
- Tras acertar el PIN o el QR, el celular recibe un **token** y ya no lo vuelve
  a pedir.
- **8 intentos fallidos** de PIN (o 10 de QR) desde una misma dirección
  bloquean el acceso durante 5 minutos.
- El panel que muestra el QR en grande **solo responde a la propia PC**.
- Al desconectarse el celular, la PC **suelta** automáticamente botones y teclas.
- La aplicación solo escucha en tu **red local**; no se abre nada hacia internet.

Si quieres empezar de cero, pulsa *Ajustes → Olvidar este dispositivo*.

---

## Opciones de línea de comandos

Desde la carpeta `server/`:

```bash
python app.py                      # puerto 8765 (por defecto)
python app.py --port 9000          # usar otro puerto
python app.py --host 127.0.0.1     # solo esta PC (para pruebas)
python app.py --no-auth            # sin PIN ni QR (¡solo para pruebas!)
python app.py --no-qr              # con PIN, pero sin código QR
python app.py --no-browser         # no abrir el panel del QR al iniciar
```

También puedes pasar estos parámetros a `iniciar.bat`, por ejemplo:
`iniciar.bat --port 9000`

---

## Estructura del proyecto

```
remote-pad/
├── iniciar.bat              ← doble clic para usar la app
├── probar.bat               ← doble clic para comprobar que todo funciona
├── server/
│   ├── app.py               Servidor HTTP + WebSocket, acceso por PIN/QR
│   ├── qr.py                Generador de códigos QR (sin dependencias)
│   ├── controller.py        Control del escritorio (puntero, clics, teclado)
│   ├── native_input.py      Capa nativa de Windows (SendInput, cursor, rueda)
│   └── requirements.txt
├── web/                     Aplicación del celular (PWA)
│   ├── index.html           Interfaz
│   ├── styles.css           Estilos
│   ├── app.js               Gestos y comunicación
│   ├── qr.html              Panel de la PC con el QR en grande
│   ├── sw.js                Service worker (funcionamiento sin conexión)
│   └── manifest.webmanifest
└── tools/
    ├── test_client.py       Pruebas de extremo a extremo (protocolo completo)
    ├── test_drag.py         Prueba real de arrastrar y soltar
    ├── test_qr.py           Verificación del generador de QR
    ├── test_qr_login.py     Prueba del acceso por QR de extremo a extremo
    ├── check_ui.py          Coherencia entre HTML, CSS y JS
    └── make_icons.py        Genera los iconos de la app
```

**Requisito único:** Python 3.9 o superior con `aiohttp`
(`iniciar.bat` lo instala solo si falta). No hacen falta permisos de
administrador.

---

## Documentación

| Documento | Contenido |
|---|---|
| [docs/instalacion.md](docs/instalacion.md) | Requisitos, puesta en marcha, Firewall, icono en el celular, arranque automático |
| [docs/qr.md](docs/qr.md) | Cómo funciona el acceso por código QR |
| [docs/arquitectura.md](docs/arquitectura.md) | Decisiones de diseño, módulos, concurrencia y limitaciones |
| [docs/protocolo.md](docs/protocolo.md) | Referencia de los mensajes WebSocket y los extremos HTTP |
| [docs/seguridad.md](docs/seguridad.md) | Qué protege y qué no, con recomendaciones |
| [docs/solucion-de-problemas.md](docs/solucion-de-problemas.md) | Qué hacer cuando algo no funciona |
| [docs/desarrollo.md](docs/desarrollo.md) | Entorno, pruebas, estilo y cómo añadir funciones |
| [CHANGELOG.md](CHANGELOG.md) | Historial de versiones |

---

## Cómo funciona

```
 Celular (Chrome)                       PC (Windows)
 ┌──────────────────┐   WebSocket   ┌──────────────────────────┐
 │ touchpad + gestos│ ────────────► │ app.py (aiohttp)         │
 │   app.js         │   JSON        │   ↓ cola de eventos      │
 │                  │ ◄──────────── │   bucle a 60-125 Hz      │
 └──────────────────┘   estado      │   ↓                      │
                                    │ controller.py            │
                                    │   ↓                      │
                                    │ native_input.py          │
                                    │   ↓ SendInput            │
                                    │ puntero / teclado / vol. │
                                    └──────────────────────────┘
```

Detalles que marcan la diferencia:

- El celular envía **desplazamientos relativos normalizados por la altura de la
  pantalla**, así que la sensibilidad se siente igual en cualquier resolución.
- El servidor **acumula** los movimientos y los aplica a ritmo constante: si el
  WiFi sufre un tirón no se pierde distancia recorrida.
- Los **clics se ejecutan de inmediato** (no esperan a la cola de movimiento)
  para que pulsar un botón pequeño sea fiable.
- El **scroll** se consolida en "clics" de rueda, con la parte fraccionaria
  guardada para que un deslizamiento lento también responda.

---

## Si algo no funciona

| Síntoma | Solución |
|---|---|
| El celular no abre la dirección | Misma WiFi en ambos. Revisa el Firewall de Windows: permite Python en redes privadas. |
| El QR no se ve en la consola | Abre `http://127.0.0.1:8765/qr` en la PC: ahí sale en grande. |
| "El código QR ya se usó o caducó" | Cada QR sirve una sola vez y dura 5 minutos. Escanea el que muestra la PC ahora (se renueva solo). |
| "PIN incorrecto" siempre | El PIN caduca cada 5 minutos. Mira el valor actual en la consola de la PC o pulsa el botón **PIN** de la app. |
| El puntero va lento o rapidísimo | Ajustes → velocidad del puntero (1,6× es el valor por defecto). |
| El scroll va al revés | Ajustes → desactiva *Desplazamiento natural*. |
| Algo se quedó arrastrando | Pulsa **Soltar** (o el botón **Puntero** de la barra superior). |
| "No se pudo abrir el puerto 8765" | Otro programa lo ocupa: `iniciar.bat --port 8899`. |
| Quiero comprobar que todo está bien | Doble clic en **`probar.bat`** (35 pruebas de control + arrastre + QR). |

---

## Notas técnicas

Durante el desarrollo aparecieron varios problemas que conviene conocer:

1. **`pynput` 1.8.2 no funciona con Python 3.12 en Windows.** Su llamada a
   `SendInput` lanza `ArgumentError: expected LP__INPUT instance`, de modo que
   el movimiento del puntero y todas las teclas fallaban en silencio. Por eso
   `native_input.py` habla directamente con la API de Windows.
2. **`GetAsyncKeyState` no refleja los botones inyectados con `SendInput`.**
   La detección de arrastre se apoya en el estado propio del controlador y no
   en esa API; de lo contrario un arrastre iniciado desde el celular se
   soltaría solo a mitad del gesto.
3. **Los bits del código QR son traicioneros.** Un QR con los patrones bien
   dibujados puede ser ilegible si un solo bit está en la celda equivocada: se
   ve perfecto y ningún móvil lo lee. Por eso el generador se verifica contra
   la tabla oficial de información de formato y contra lectores reales
   (`test_qr.py`), y no solo "a ojo".

---

## Licencia

[MIT](LICENSE) — úsalo, modifícalo y compártelo libremente.

## Créditos

Escrito para un caso de uso doméstico: controlar el PC del salón desde el sofá,
sin instalar nada en el celular y sin depender de servicios en la nube.

