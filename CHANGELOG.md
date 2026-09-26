# Historial de cambios

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
