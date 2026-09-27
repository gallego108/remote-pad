# RemotePad — tu celular como touchpad del PC

Convierte tu celular Android en un **touchpad inalámbrico** para tu PC con
Windows: mueve el puntero, haz clic, arrastra, escribe (o **dicta**), controla
el volumen, comparte el **portapapeles**, señala con un **puntero láser**,
evita que la pantalla se apague y **aprende de tu forma de moverte**. Todo desde
el navegador del teléfono y por tu propia red WiFi.

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
   entras directamente, sin escribir nada. El código vale **3 minutos** y se
   renueva solo, así que hay tiempo de sobra para escanear.
5. Si el QR no te resulta cómodo, abre `http://192.168.1.9:8765` y escribe el
   PIN de 6 dígitos.

### Para detenerlo

- **Desde el celular**: *Ajustes → Detener RemotePad en la PC* (pide
  confirmación y solo funciona si ya entraste).
- **Desde la consola de la PC**: escribe `q` y pulsa ENTER, o `Ctrl+C`.
- Al detenerse, los celulares conectados lo avisan en pantalla; los accesos
  guardados siguen valiendo para la próxima vez.

### Quitar el código de acceso (temporalmente)

Si quieres entrar sin PIN ni código QR, hay cuatro formas:

| Cómo | Qué hacer |
|---|---|
| **Doble clic** | `quitar-codigo.bat` (y `activar-codigo.bat` para volver a pedirlo) |
| **Al arrancar** | `iniciar.bat --no-auth` |
| **En caliente, desde el celular** | *Ajustes → Quitar el código de acceso* |
| **En caliente, desde la consola** | Escribe `auth off` y pulsa ENTER |

Para volver a pedirlo: `activar-codigo.bat`, *Ajustes → Volver a pedir el
código*, o `auth on` en la consola (genera un PIN nuevo). Quien ya estaba dentro
sigue dentro: no se expulsa a nadie, simplemente deja de pedirse el código a los
nuevos. La elección **se recuerda entre reinicios** (se guarda en
`server/config.json`).

> **Aviso**: mientras está quitado, **cualquiera conectado a tu misma WiFi puede
> mover el puntero, hacer clic y escribir en tu PC**. La consola lo recuerda con
> un recuadro de aviso mientras dure. Úsalo solo en una red de confianza y
> vuelve a activarlo cuando termines.

> ### Si el celular dice "no se puede conectar"
>
> Es el **Firewall de Windows**, no la aplicación: Windows no tiene ninguna
> regla de entrada para **TCP** en Python (solo UDP), así que bloquea al
> celular aunque la app funcione en la PC.
>
> **Solución:** haz doble clic en **`abrir-firewall.bat`** y acepta el aviso de
> administrador. Crea la regla y muestra la dirección que debe abrir el celular.
>
> Si no quieres tocar el Firewall, cambia la red WiFi a **Privada**
> (Configuración → Red e Internet → WiFi → Propiedades).
>
> Para saber qué está pasando, ejecuta:
> `python tools/diagnostico_red.py 8765`

> **Si el QR no cabe en la consola**, en la PC se abre automáticamente una
> página con el código en grande (`http://127.0.0.1:8765/qr`), que se
> **renueva sola cada 3 minutos** y tiene un botón para generar uno nuevo.

> **La primera vez**, Windows preguntará si quieres permitir el tráfico de red
> para Python. Marca **Redes privadas** y acepta; si lo cancelas, usa
> `abrir-firewall.bat`.

**Para no repetir el acceso:** en Chrome, menú ⋮ → *Añadir a pantalla de
inicio*. Así queda como una app con su icono, y el dispositivo recuerda el
acceso (guarda un token propio): las próximas veces entra directo, **incluso si
la PC o el servidor se reinician** (el acceso dura 30 días y se guarda en
`server/tokens.json`).

### Cómo funciona el código QR

El QR contiene una dirección con una **clave de un solo uso**
(`http://192.168.1.9:8765/?k=...`). Al escanearlo, el celular canjea esa clave
por un token de dispositivo y entra sin pedir el PIN.

- La clave vale **3 minutos** y **se invalida al primer uso**, así que el enlace
  que quede en el historial del navegador ya no sirve.
- El panel de la PC **genera un código nuevo cada 3 minutos**: siempre hay uno
  vigente en pantalla, sin que tengas que hacer nada. En la consola se muestra
  uno nuevo sola, y con ENTER pides otro al instante.
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
| **Pellizcar con 2 dedos (pinza)** | **Zoom** (Ctrl + rueda) |
| Tocar con 3 dedos | Clic central (abrir en pestaña nueva…) |
| **Deslizar con 3 dedos arriba/abajo** | **Subir / bajar volumen** |
| **Deslizar con 3 dedos izquierda/derecha** | **Pestaña siguiente / anterior** |
| **Deslizar desde el borde izquierdo/derecho** | **Atrás / Adelante** |
| Mantener pulsado (0,4 s) | Arrastrar mientras no levantes el dedo |
| Doble toque y deslizar sin levantar | Arrastre fijo, hasta que toques otra vez |

Además:

- **Modo rápido (⚡)** — en la barra superior. Mientras está activo el puntero se
  mueve **3× más rápido**: ideal para cruzar la pantalla de una pasada.
- **Puntero láser (🔴)** — para presentaciones. Mientras está activo, tocar el
  panel **solo señala** con un punto rojo sobre la pantalla, sin mover el ratón
  ni hacer clic.
- **Inercia** — al soltar el dedo tras un deslizamiento rápido el puntero sigue
  un poco, frenándose, como en un touchpad real (se desactiva en Ajustes).
- **Portapapeles compartido** — en el panel *Teclado*: **⬇ Traer del PC** pone en
  el campo el texto copiado en la PC, y **⬆ Copiar en el PC** deja el texto del
  campo en el portapapeles de la PC (para pegarlo con Ctrl+V).

Los botones **Clic izq. / Clic der. / Soltar / Reconectar** están siempre a la
vista. El botón de la barra superior (**Puntero**) hace de interruptor maestro
para el arrastre fijo: si algo se queda "pegado", pulsa **Soltar**.

### Paneles inferiores

- **Teclado** — escribe en el campo y el texto aparece en la PC tal cual
  (acentos, `@`, `¿`, emoji). Debajo tienes Enter, Tab, Esc, flechas, etc.
  El **Enter** de tu teclado hace un **salto de línea** (puedes escribir varias
  líneas); para pulsar un Enter suelto en la PC usa el botón **⏎ Enter en la PC**.
  - **🎤 Dictar** — dictado por voz. Enfoca el campo para que uses el
    **micrófono del teclado del celular** (Gboard): lo que digas se escribe en
    la PC. Si la página se sirve por HTTPS y el navegador trae reconocimiento de
    voz, se usa directamente, sin depender del teclado.
  - **⬇ Traer del PC / ⬆ Copiar en el PC** — portapapeles compartido.
- **Atajos** — copiar, pegar, deshacer, Alt+Tab, F11, bloquear la PC…
- **Multimedia** — ⏮ ⏯ ⏭, silencio y subir/bajar volumen.
- **Presentar** — anterior/siguiente diapositiva, iniciar (F5), salir, y
  pantalla en negro o blanco (PowerPoint, Impress y similares).
- **Ajustes** — velocidad del puntero y del scroll, aceleración, desplazamiento
  natural, inercia, gestos de 3 dedos, bordes, pinza, vibración y el desbloqueo.
  Incluye **💡 Mantener la pantalla encendida**: eliges cuánto tiempo (5 min a
  4 h) y la app mueve el ratón 1 píxel cada 40 s para que la PC no se apague
  ni se suspenda. Todo lo que ajustes se guarda **también en la PC**
  (`server/profiles.json`, ligado al dispositivo), así que no hay que volver a
  configurarlo al entrar de nuevo.
- **Ayuda** — la **guía de uso completa dentro de la app** y un botón para
  repetir el **tutorial paso a paso** (también aparece solo la primera vez).

---

## Seguridad

- **PIN de 6 dígitos** que se muestra **solo en la pantalla de la PC** y se
  renueva **cada 5 minutos** (o antes, si toca el botón PIN de la app).
- **Código QR de un solo uso**: su clave caduca en 5 minutos y se invalida al
  primer escaneo, así que el enlace del historial del navegador deja de servir.
- Tras acertar el PIN o el QR, el celular recibe un **token** y ya no lo vuelve
  a pedir: se guarda en `server/tokens.json` para que **sobreviva a los
  reinicios** (hasta 30 días).
- **8 intentos fallidos** de PIN (o 10 de QR) desde una misma dirección
  bloquean el acceso durante 5 minutos.
- El panel que muestra el QR en grande **solo responde a la propia PC**.
- **El código de acceso se puede quitar** temporalmente (`--no-auth` al
  arrancar, `auth off` en la consola, o el botón de *Ajustes*). Mientras está
  quitado, **cualquiera en tu red puede controlar la PC**: la consola lo avisa
  con un recuadro y la app lo indica en la pantalla de acceso.
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
├── abrir-firewall.bat       ← si el celular no conecta: abre el puerto
├── probar.bat               ← doble clic para comprobar que todo funciona
├── activar-codigo.bat       ← volver a pedir el PIN y el QR
├── quitar-codigo.bat        ← quitar el PIN y el QR temporalmente
├── server/
│   ├── app.py               Servidor HTTP + WebSocket, acceso por PIN/QR
│   ├── qr.py                Generador de códigos QR (sin dependencias)
│   ├── controller.py        Control del escritorio (puntero, clics, teclado)
│   ├── native_input.py      Capa nativa de Windows (SendInput, cursor, rueda)
│   ├── laser.py             Puntero láser (capa transparente sobre la pantalla)
│   ├── config.json          ¿Se pide código de acceso? — local, no se versiona
│   ├── tokens.json          Accesos de los dispositivos — local, no se versiona
│   ├── profiles.json        Preferencias de cada dispositivo — local, no se versiona
│   └── requirements.txt
├── web/                     Aplicación del celular (PWA)
│   ├── index.html           Interfaz + guía de uso + tutorial
│   ├── styles.css           Estilos
│   ├── app.js               Gestos, atajos y comunicación
│   ├── qr.html              Panel de la PC con el QR en grande
│   ├── sw.js                Service worker (funcionamiento sin conexión)
│   └── manifest.webmanifest
└── tools/
    ├── check_ui.py          Coherencia entre HTML, CSS y JS
    ├── diagnostico_red.py   Averigua por qué el celular no conecta
    ├── diagnostico_qr.py    Diagnóstico del acceso por código QR
    ├── ver_firewall.py      Estado del Firewall de Windows
    ├── estado_servidores.py Servidores en marcha y su estado de acceso
    ├── quitar_codigo_ahora.py  Quita el código en el servidor en marcha
    ├── make_icons.py        Genera los iconos de la app
    ├── test_client.py       Extremo a extremo: protocolo completo (35 pruebas)
    ├── test_drag.py         Arrastrar y soltar de verdad
    ├── test_stop.py         Parada del servicio (consola, celular, /api/stop)
    ├── test_qr.py           Verificación del generador de QR (19 pruebas)
    ├── test_qr_login.py     Acceso por QR de extremo a extremo
    ├── test_qr_rotacion.py  Rotación del QR y margen de gracia
    ├── test_qr_window.py    Ventana de validez del QR y del PIN
    ├── test_acceso_libre.py Código de acceso desactivable
    └── test_version_cache.py  Anti-caché y detector de versión
```

**Requisito único:** Python 3.9 o superior con `aiohttp`
(`iniciar.bat` lo instala solo si falta). No hacen falta permisos de
administrador. El puntero láser usa `tkinter`, que viene con Python en Windows.

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

### Aprendizaje (sin dependencias ni nube)

La app se adapta sola a cómo usas el puntero, con unas pocas medias
exponenciales: **nada sale de tu PC** y no hace falta ningún modelo grande.

| Qué aprende | Cómo | Dónde |
|---|---|---|
| **Sensibilidad** | Si te pasas y corriges (movimiento largo + uno corto al revés) baja la ganancia; si encadenas movimientos largos en el mismo sentido, la sube | PC (`server/learning.py`) |
| **Por aplicación** | La misma ganancia, aprendida por separado para cada programa en primer plano | PC |
| **Toque con dos dedos** | Si un clic derecho va seguido de un movimiento, salió solo: se exige más la próxima vez | Celular |
| **Umbral pinza/scroll** | Guarda la "firma" de tus gestos y coloca el umbral entre los dos grupos (k-means 1D) | Celular |

La ganancia se mueve entre 0,6× y 1,9×, despacio y acotada: mejor quedarse corto
que dar un salto raro a mitad de un movimiento. **Tu ajuste manual siempre
manda**: la ganancia multiplica lo que elijas, no lo sustituye. Todo se puede
apagar y reiniciar desde *Ajustes → Aprendizaje*.

---

## Si algo no funciona

| Síntoma | Solución |
|---|---|
| **El celular dice "no se puede conectar"** | Ejecuta **`abrir-firewall.bat`** (necesita permisos de administrador). Windows no tiene regla de entrada TCP para Python. |
| El celular no abre la dirección | Misma WiFi en ambos (y que no sea una red de invitados que aísle los equipos). |
| El QR no se ve en la consola | Abre `http://127.0.0.1:8765/qr` en la PC: ahí sale en grande y se renueva solo. |
| "Ese código ya se usó o pasó su tiempo" | Cada QR vale 3 minutos y sirve una sola vez. Escanea el que muestra la PC en ese momento. |
| "PIN incorrecto" siempre | El PIN caduca cada 5 minutos. Mira el valor actual en la consola de la PC o pulsa el botón **PIN** de la app. |
| El puntero va lento o rapidísimo | Ajustes → velocidad del puntero (1,6× es el valor por defecto). |
| El scroll va al revés | Ajustes → desactiva *Desplazamiento natural*. |
| Algo se quedó arrastrando | Pulsa **Soltar** (o el botón **Puntero** de la barra superior). |
| "No se pudo abrir el puerto 8765" | Otro programa lo ocupa: `iniciar.bat --port 8899`. |
| Quiero saber por qué no conecta | `python tools/diagnostico_red.py 8765` |
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

