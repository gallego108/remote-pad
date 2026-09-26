# El código QR

## Qué contiene y por qué

El QR no es una imagen decorativa: codifica una dirección con una **clave de un
solo uso**.

```
http://192.168.1.9:8765/?k=XUZkWmnZ9RUT
```

Al escanearlo, el navegador del celular abre la aplicación y esta canjea la
clave por un token de dispositivo (`POST /api/qr-login`). A partir de ahí la
sesión funciona igual que si se hubiera escrito el PIN.

El objetivo es **quitar el paso de teclear** sin debilitar el acceso: la clave
la puede leer únicamente quien esté delante de la pantalla de la PC, igual que
el PIN.

### Por qué una clave en la URL y no el PIN

Poner el PIN en la URL sería más corto, pero quedaría en el historial del
navegador y en cualquier registro, y valdría hasta que caducara. Con una clave
de un solo uso:

- **vale 3 minutos** (`QR_VALID_SECONDS`), tiempo de sobra para apuntar con la
  cámara sin prisas;
- **se invalida al primer canje**, así que el enlace guardado ya no sirve;
- el PIN nunca viaja en una URL.

La comparación se hace en **tiempo constante** (`hmac.compare_digest`) y tras
10 fallos desde una misma dirección se bloquea el canje 5 minutos.

### Por qué 3 minutos

Es el equilibrio entre comodidad y exposición. Tres minutos dan margen para
escanear sin agobios, y el panel de la PC **genera un código nuevo
automáticamente** al agotarse la ventana, de modo que siempre hay uno vigente en
pantalla sin intervención. La consola también muestra uno nuevo sola, y
pulsando ENTER se pide otro al instante.

La rotación la hace `Gateway.rotate_qr_key_if_needed()`, que se ejecuta en cada
ciclo del bucle de animación y también desde el flujo de eventos del panel.

## Cómo llega la clave al celular

La clave viaja por **dos caminos a la vez**, para que el acceso no dependa del
navegador:

1. **En la dirección**: `http://192.168.1.9:8765/?k=<clave>`.
2. **Dentro del HTML**: cuando el servidor sirve la página y la petición trae
   `?k=`, escribe la clave en etiquetas meta:

   ```html
   <meta name="remotepad-qr-key" content="...">
   <meta name="remotepad-qr-estado" content="ok|caducado">
   <meta name="remotepad-version" content="1.2.0">
   ```

El segundo camino existe porque algunos **visores de cámara recortan la
dirección al redirigir**, y entonces el parámetro se pierde: la página cargaba y
pedía el PIN sin intentar el QR. Con la etiqueta meta la clave sobrevive a
cualquier redirección, y `remotepad-qr-estado` permite avisar en la propia
pantalla de que el código ya había caducado cuando se sirvió.

Esa respuesta se envía con `Cache-Control: no-store`, y el *service worker*
ignora cualquier petición con `?k=`, así que nunca se sirve una copia guardada
del enlace de acceso.

## La rotación no puede hacer fallar un escaneo

Un problema real: el código visible cambia cada 3 minutos, y si alguien está
apuntando con la cámara en ese preciso instante, **el código que acaba de leer
deja de valer y el acceso falla**. Pasó de verdad, con el mensaje «no se pudo
conectar» y sin ninguna pista en la consola de la PC.

Se resuelve con tres medidas que se complementan:

1. **Margen de gracia** (`QR_GRACE_SECONDS = 20`): al renovar, el código
   anterior **sigue siendo válido 20 segundos más**. Es justo el tiempo que
   tarda el canje en llegar por la red. Cada código se sigue usando una sola
   vez.
2. **Renovación anticipada**: el panel pide el código siguiente
   `QR_PRE_REFRESH_SECONDS` (20 s) antes de que caduque el actual, de modo que
   el cambio no coincide con el último segundo de vida del código.
3. **Recuperación automática**: si aun así el canje llega con un código
   caducado, el celular pide uno nuevo con `POST /api/qr-refresh` y lo canjea
   solo. Ese endpoint **exige el token de un dispositivo ya autorizado**: no
   sirve para entrar desde cero, solo para renovar un acceso que ya existe. Si
   el usuario no tenía acceso previo, se le muestra el aviso y el campo del
   PIN.

## El cliente y las versiones antiguas

Un problema real: el celular puede quedarse con una **copia antigua de
`app.js`** (de antes de que existiera el QR). Entonces la página carga, pide el
PIN y nunca intenta el canje, sin ningún error visible en la PC.

Medidas que lo evitan:

- El *service worker* usa estrategia **red primero**: si hay conexión manda
  siempre el servidor; la caché solo es respaldo sin conexión.
- Al activarse una versión nueva, el *service worker* avisa a las pestañas
  abiertas (`version-nueva`) y la aplicación **se recarga sola**.
- El registro se hace con `updateViaCache: 'none'` y se busca actualización al
  volver la app a primer plano.
- El nombre de la caché incluye versión (`remotepad-v3`) y el `activate` borra
  las anteriores.
- La versión del servidor se muestra en *Ajustes* dentro de la app, para poder
  comprobar de un vistazo qué copia se está ejecutando.

## El codificador

`server/qr.py` implementa el estándar ISO/IEC 18004 sin dependencias externas.
Cubre versiones 1 a 10 (hasta 57×57 módulos, suficiente para estas direcciones)
y los cuatro niveles de corrección.

### Cadena de codificación

```
texto
  │
  ├─ 1. Elección de versión: la más pequeña donde quepa
  │       cabecera (4 + 8/16 bits) + datos + terminador + relleno
  ├─ 2. Modo byte: 0100 + longitud + bytes UTF-8
  ├─ 3. Relleno: 0xEC / 0x11 alternos hasta llenar la capacidad
  ├─ 4. Reparto en bloques + Reed-Solomon sobre GF(256)
  ├─ 5. Entrelazado de datos y corrección
  ├─ 6. Colocación en zigzag desde la esquina inferior derecha
  ├─ 7. Patrones: posición, separadores, temporización, alineación,
  │       módulo oscuro, información de versión y de formato
  └─ 8. Elección de la máscara con menor penalización (8 candidatas)
```

### Piezas delicadas

Tres detalles que son invisibles a la vista y que hacen que un QR "se vea
perfecto" y no lo lea ningún móvil:

1. **Hay que reservar las 30 celdas del formato ANTES de colocar los datos.**
   Si no, esas celdas cuentan como libres, los datos se reparten por encima y
   todo el flujo de bits queda desplazado. El QR sigue pareciendo correcto.

2. **El orden de los bits de formato.** La primera celda de la secuencia lleva
   el bit más significativo, y la secuencia recorre la fila 8 y la columna 8
   alrededor del patrón de posición superior izquierdo:

   ```
   bit 14 → (8,0)   bit 13 → (8,1)   ...   bit 9 → (8,5)
   bit  8 → (8,7)   bit  7 → (7,8)   bit 6 → (8,8)
   bit  5 → (5,8)   bit  4 → (4,8)   ...   bit 0 → (0,8)
   ```

3. **El módulo oscuro de `(size-8, 8)` no es parte del formato.** Debe quedar
   siempre oscuro y fuera de la máscara. Al colocar la segunda copia del
   formato es fácil pisarlo.

4. **La temporización llega hasta el centro de los patrones de posición**
   (índice `size-9` incluido). Quedarse corto deja celdas sin reservar.

### Cómo se verifica

No basta con mirarlo. `tools/test_qr.py` comprueba cuatro niveles:

| Nivel | Qué comprueba |
|---|---|
| Aritmética | Las 32 palabras de formato y las 4 de versión contra la tabla oficial, y la distancia de Hamming (≥7 y ≥8) |
| Estructura | Patrones de posición, alineación, temporización, módulo oscuro y que la máscara no toque celdas reservadas |
| Ida y vuelta | Se quita la máscara, se leen los códigos, se deshace el entrelazado y se recupera el texto |
| Lectores reales | `zxing-cpp` descodifica los QR generados (es el motor de muchos lectores y móviles) |

Además:

- `tools/test_qr_capacity.py` llena cada versión y nivel **hasta el byte
  exacto** y comprueba que el lector los descodifica. Si la capacidad estimada
  fuese mayor que la real, esos códigos serían ilegibles.
- `tools/verify_rs.py` valida Reed-Solomon con un segundo método (división
  polinómica frente a multiplicación) y comprobando que el polinomio se anula
  en las raíces del generador.

## Dibujo en la consola

`qr.render_terminal()` usa el carácter de medio bloque `▀` con colores de fondo
ANSI: cada línea de texto pinta dos filas de módulos, así el código sale con la
proporción correcta (un módulo cuadrado) ocupando la mitad de alto.

- Zona de silencio de **4 módulos**, como exige el estándar.
- Módulos oscuros sobre fondo claro, que es lo que esperan las cámaras. La
  opción `invert` existe pero no se usa.
- `enable_ansi()` activa las secuencias de color en la consola de Windows
  (`ENABLE_VIRTUAL_TERMINAL_PROCESSING`). Si la consola no las admite,
  `supports_color()` devuelve `False` y el servidor remite al panel `/qr`.

## El panel de la PC

`/qr` sirve `web/qr.html`, que dibuja la matriz en un `<canvas>` a 340 px. Es
la alternativa cuando el QR no cabe o no se lee bien en la consola.

- **Solo responde a la propia PC** (`127.0.0.1` / `::1`): la página contiene el
  PIN y la clave, así que no se sirve al resto de la red.
- **Se renueva solo**: cada 3 minutos pide un código nuevo a `/qr/new` y lo
  redibuja, así que en pantalla siempre hay uno vigente. La renovación se pide
  **5 segundos antes** de que caduque, para no mostrar nunca uno vencido.
- Recibe además los cambios por **server-sent events** (`/qr/stream`), y si el
  flujo se cae lo reintenta a los 3 segundos: la renovación por reloj sigue
  funcionando igual.
- El botón **Generar uno nuevo** fuerza la renovación e invalida el anterior.
- `/qr/new` devuelve la matriz y los datos, de modo que el panel se actualiza
  **sin recargar la página**.

## Nota sobre el generador de referencia

Durante el desarrollo se comparó con `segno` y `zxing-cpp`. Conviene saber que
sus matrices **no coinciden celda a celda** y no es un error: `segno` usa modo
alfanumérico cuando el texto lo permite, así que las celdas de datos difieren
legítimamente. Lo que sí debe coincidir —y se comprueba— es el **formato**
(nivel y máscara) y todo el andamiaje de patrones.
