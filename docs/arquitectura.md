# Arquitectura

## Vista general

RemotePad tiene dos piezas: un **servidor** que corre en la PC (Python) y una
**aplicación web** que abre el celular en su navegador. No hay app que instalar
en el teléfono.

```
   CELULAR (Chrome)                          PC (Windows)
 ┌────────────────────┐                  ┌──────────────────────────────┐
 │  index.html        │                  │  app.py  (aiohttp)           │
 │  styles.css        │   WebSocket      │   ├─ autenticación (PIN/QR)  │
 │  app.js            │ ◄──────────────► │   ├─ cola de eventos         │
 │   ├─ gestos        │      JSON        │   ├─ bucle de animación      │
 │   └─ interfaz      │                  │   └─ /qr (panel de la PC)    │
 └────────────────────┘                  │            │                 │
                                         │            ▼                 │
                                         │  controller.py               │
                                         │   ├─ puntero y clics         │
                                         │   ├─ teclado                 │
                                         │   └─ multimedia              │
                                         │            │                 │
                                         │            ▼                 │
                                         │  native_input.py             │
                                         │   └─ SendInput / SetCursorPos│
                                         └──────────────────────────────┘
```

## Por qué así

### Un servidor web en vez de una app nativa

Servir una PWA desde la propia PC evita compilar y distribuir un APK, funciona
igual en Android que en iPhone y no necesita certificados ni tienda de
aplicaciones. El coste es que el celular y la PC deben estar en la misma red,
que es exactamente el caso de uso.

### Coordenadas relativas, no absolutas

El celular manda **desplazamientos** (`mouse_rel_move`), no posiciones. Con
posiciones absolutas habría que conocer la resolución y el puntero "saltaría"
al tocar la pantalla, además de depender de la orientación del teléfono.

La distancia recorrida por el dedo se multiplica por la sensibilidad:

```python
dx_enviado = pixeles_del_dedo * sensibilidad
```

El servidor aplica cada unidad como **1 píxel** del PC, así que el cliente
manda la distancia real recorrida. (Ojo: normalizar dividiendo por la altura
de la pantalla deja valores de ~0,1 que al redondear no mueven el puntero; fue
justo el fallo por el que el touchpad "no respondía".)

### El servidor acumula y aplica a ritmo constante

El hilo de red puede recibir ráfagas (WiFi irregular) y el sistema operativo no
necesita 500 eventos por segundo. El bucle de animación:

1. vacía la cola de movimientos y **suma** todos los desplazamientos pendientes;
2. aplica el total de una vez;
3. duerme ~8-16 ms.

Si el celular va por delante, no se pierde distancia: se consolida. Los **clics
van en su propia cola y se ejecutan sin esperar**, para que pulsar un botón
pequeño sea fiable.

### El scroll se convierte a "clics" de rueda

Windows entiende la rueda en unidades de 120. El cliente envía píxeles de
deslizamiento y el controlador los acumula, guardando la parte fraccionaria,
para que un deslizamiento lento también acabe moviendo la página.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `server/app.py` | Servidor HTTP/WebSocket, autenticación, difusión, bucle de animación |
| `server/controller.py` | Traduce acciones en llamadas a la capa nativa; mantiene el estado del puntero y del arrastre |
| `server/native_input.py` | Única dependencia del sistema operativo: `SendInput`, `SetCursorPos`, `GetAsyncKeyState` |
| `server/qr.py` | Codificador de QR completo (rejilla, Reed-Solomon, máscaras) y dibujo en consola |
| `server/laser.py` | Proceso aparte que dibuja el puntero láser: ventana `tkinter` transparente y "click-through" |
| `server/learning.py` | Aprendizaje del tacto: deduce la ganancia del puntero a partir de cómo corriges, por aplicación |
| `web/app.js` | Motor de gestos y comunicación del cliente |
| `web/qr.html` | Panel local de la PC con el QR en grande |

### Estado que se guarda en disco

Todo vive en la carpeta `server/` y **no se versiona** (ver `.gitignore`):

| Archivo | Contenido | Por qué |
|---|---|---|
| `config.json` | Si se pide código de acceso | Que `quitar-codigo.bat` sobreviva al reinicio |
| `tokens.json` | Accesos de los dispositivos autorizados | Que reiniciar el servidor no obligue a escribir el PIN otra vez |
| `profiles.json` | Preferencias de cada dispositivo (por token) | Que no haya que reajustar velocidad, gestos, etc. |
| `learning.json` | Ganancia aprendida por aplicación | Que la adaptación sobreviva al reinicio |

Las pruebas **no tocan** esos archivos: `probar.bat` redirige los tres últimos
con `REMOTEPAD_TOKENS`, `REMOTEPAD_PROFILES` y `REMOTEPAD_LEARNING` a archivos
temporales.

### Cómo aprende la ganancia

`learning.py` parte el movimiento en **rafagas** (una rafaga termina tras 120 ms
sin moverse) y compara cada una con la anterior:

| Patrón | Lectura | Efecto |
|---|---|---|
| Rafaga larga + rafaga corta en sentido contrario | se pasó y corrigió | cuenta como **exceso** |
| Rafagas largas encadenadas en el mismo sentido | se quedó corto | cuenta como **defecto** |

Las dos cuentas se desvanecen un 3 % por rafaga (media exponencial), así que
manda lo reciente, y de su desequilibrio sale la ganancia:

```
equilibrio = (defectos - excesos) / (defectos + excesos)     # -1 .. +1
ganancia   = 1 + equilibrio * 0.9                            # 0,6 .. 1,9
```

Con menos de 6 rafagas evaluadas la ganancia es 1,0: preferimos no tocar nada
hasta tener datos.

## Estados del controlador

El puntero se sigue con una posición "virtual" propia porque `pynput` y
`SendInput` no informan de dónde está el cursor:

- **Arrastre por el celular**: mientras `_drag_button` no sea `None`, manda el
  celular y no se resincroniza nada.
- **Sin arrastre**: si la posición real difiere de la virtual, se adopta la
  real. Así, si mueves el mouse físico, la app no "pelea" contigo.
- **Borde de pantalla**: al llegar al límite se descarta el desplazamiento
  sobrante y se resincroniza, para que al cambiar de dirección el puntero
  responda al instante.

### Estados de la interfaz del celular

```
        (toque corto)
   ┌────────────────────► clic izquierdo
   │
pointer ──(pulsación larga)──► dragging ──(levantar)──► pointer
   │                              ▲
   └──(doble toque)──► locked ────┘
                        │
                        └──(toque)──► suelta y vuelve a pointer
```

- **dragging**: se mantiene el botón mientras el dedo no se levante.
- **locked**: se mantiene el botón entre gestos (arrastre cómodo para
  seleccionar texto o mover ventanas largas); se sale con un toque o pulsando
  **Soltar**.

En ambos casos, si el celular se desconecta o pasa a segundo plano, el servidor
**suelta** botones y teclas automáticamente para no dejar la PC bloqueada.

## Concurrencia

- Un único bucle de eventos de asyncio para la red.
- Un `ThreadPoolExecutor` de 3 hilos para las llamadas al sistema operativo,
  porque `SendInput` es bloqueante.
- Los eventos de puntero **no** pasan por el ejecutor: los aplica el bucle de
  animación, ya consolidados.
- Los valores que van a un hilo se pasan **como argumentos por defecto** en el
  `run_in_executor`; de lo contrario el hilo leería variables ya reasignadas por
  el siguiente mensaje.

## Limitaciones conocidas

- Solo funciona en **Windows** (la capa nativa usa la API Win32).
- **Ctrl+Alt+Supr** no se puede simular: Windows lo reserva al sistema. La app
  lo avisa en lugar de fallar en silencio.
- El **nivel de volumen** no se puede leer ni fijar desde una aplicación
  normal: se sube o baja a pasos de tecla multimedia.
- Sin cifrado: el tráfico va en claro por la red local. Ver
  [seguridad.md](seguridad.md).
