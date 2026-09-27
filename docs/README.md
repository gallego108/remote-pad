# Documentación de RemotePad

RemotePad convierte tu celular en un touchpad inalámbrico para la PC: mueve el
puntero, haz clic, arrastra, escribe o dicta, controla multimedia y
presentaciones, comparte el portapapeles y evita que la pantalla se apague,
desde el navegador del teléfono y por tu propia red WiFi.

Si es la primera vez, empieza por el [README](../README.md).

## Guías

| Documento | Para qué sirve |
|---|---|
| [instalacion.md](instalacion.md) | Requisitos, puesta en marcha, Firewall, icono en el celular, arranque automático |
| [arquitectura.md](arquitectura.md) | Cómo está construido y por qué: decisiones, módulos, concurrencia, limitaciones |
| [protocolo.md](protocolo.md) | Mensajes del WebSocket y extremos HTTP (referencia completa) |
| [qr.md](qr.md) | El generador de códigos QR y el acceso sin escribir nada |
| [seguridad.md](seguridad.md) | Qué protege y qué no, con recomendaciones prácticas |
| [solucion-de-problemas.md](solucion-de-problemas.md) | Qué hacer cuando algo no funciona |
| [desarrollo.md](desarrollo.md) | Entorno, pruebas, estilo y cómo añadir funciones |

## Resumen en una tabla

| | |
|---|---|
| **Plataforma de la PC** | Windows 10+ |
| **Cliente** | Navegador del celular (PWA, sin instalar nada) |
| **Requisito** | Python 3.9+ con `aiohttp` |
| **Red** | WiFi local; no necesita internet |
| **Acceso** | Código QR de un solo uso (vale 3 minutos) o PIN de 6 dígitos. El dispositivo **recuerda el acceso** (30 días, sobrevive a reinicios) |
| **Funciones** | Puntero, clics, scroll, zoom, arrastre, inercia, gestos de 2 y 3 dedos, bordes, atrás/adelante, teclado, **dictado**, atajos, multimedia, presentaciones, **portapapeles compartido**, **puntero láser** y **anti-apagado** |
| **Perfil** | Las preferencias de cada dispositivo se guardan en la PC y se aplican solas |
| **Ayuda** | Tutorial paso a paso y guía de uso dentro de la propia app (panel *Ayuda*) |
| **Detenerlo** | Botón en *Ajustes* del celular, `q` + ENTER en la consola, o `Ctrl+C` |
| **Si no conecta** | `abrir-firewall.bat` (el Firewall de Windows no abre TCP para Python) |
| **Pruebas** | `probar.bat`: control, arrastre, QR, ventana, parada y acceso |

## Recorrido recomendado

1. **[instalacion.md](instalacion.md)** — para tenerlo funcionando en 2 minutos.
2. **[qr.md](qr.md)** — para entender el acceso sin escribir nada.
3. **[protocolo.md](protocolo.md)** — si vas a tocar el código o hacer un
   cliente distinto.
4. **[arquitectura.md](arquitectura.md)** y
   **[desarrollo.md](desarrollo.md)** — antes de modificar algo.
