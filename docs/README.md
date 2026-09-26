# Documentación de RemotePad

RemotePad convierte tu celular en un touchpad inalámbrico para la PC: mueve el
puntero, haz clic, arrastra, escribe texto y controla multimedia y
presentaciones, desde el navegador del teléfono y por tu propia red WiFi.

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
| **Acceso** | PIN de 6 dígitos rotativo o código QR de un solo uso |
| **Funciones** | Puntero, clics, doble clic, scroll, arrastre, teclado, atajos, multimedia, presentaciones |
| **Pruebas** | `probar.bat`: 35 de control + arrastre + 19 de QR + 14 de acceso por QR |

## Recorrido recomendado

1. **[instalacion.md](instalacion.md)** — para tenerlo funcionando en 2 minutos.
2. **[qr.md](qr.md)** — para entender el acceso sin escribir nada.
3. **[protocolo.md](protocolo.md)** — si vas a tocar el código o hacer un
   cliente distinto.
4. **[arquitectura.md](arquitectura.md)** y
   **[desarrollo.md](desarrollo.md)** — antes de modificar algo.
