# Solución de problemas

## No puedo conectar

### El celular no abre la dirección

1. **Misma red**: comprueba que el celular no esté en datos móviles ni en otra
   WiFi (ni en una red de invitados, que suele aislar los equipos).
2. **Firewall**: la primera vez Windows pregunta si permites el tráfico. Si lo
   cancelaste, abre *Permitir una aplicación a través del Firewall de Windows*
   y habilita Python en **Redes privadas**.
3. **La IP correcta**: la que muestra la consola es la de la PC ahora mismo. Si
   cambió de red, reinicia el servidor.
4. **Aislamiento de clientes**: algunas redes (hoteles, oficinas) impiden que
   dos dispositivos se hablen entre sí. Prueba con el punto de acceso del
   celular: conecta la PC a él y usa la IP que muestre la consola.

Comprobación rápida desde la PC:

```bash
python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8765/healthz').read())"
```

### "No se pudo abrir el puerto 8765"

Otro programa lo ocupa. Usa otro puerto:

```
iniciar.bat --port 8899
```

Para ver quién lo ocupa:

```bash
netstat -ano | findstr :8765
```

## Problemas de acceso

### "PIN incorrecto" siempre

- El PIN **caduca cada 5 minutos**. Mira el valor actual en la consola.
- En la app, el botón **PIN** de la barra superior muestra el vigente.
- Se bloquea tras 8 fallos seguidos desde el mismo celular: espera 5 minutos.
- Si tienes varios servidores abiertos, asegúrate de estar mirando la consola
  del que escucha en el puerto que abriste.

### "El código QR ya se usó o caducó"

Cada QR sirve **una sola vez** y dura 5 minutos. Escanea el que muestra la PC
en ese momento (el panel `/qr` se actualiza solo).

### El QR no se lee

- **Prueba el panel de la PC**: `http://127.0.0.1:8765/qr` lo muestra en 340 px
  sobre fondo blanco, que es lo más fácil de leer.
- Sube el brillo de la pantalla y evita reflejos.
- Aleja un poco el celular: el QR necesita su zona de silencio (el margen
  blanco) visible.
- Si escaneas desde la consola: la letra de la terminal debe estar a un tamaño
  normal y sin colores invertidos (tema oscuro con texto claro es lo correcto).
- El navegador puede abrir el enlace en lugar de la cámara: si al escanear se
  abre un navegador interno, usa la app de cámara del sistema.

### No quiero usar el QR

Arranca con `--no-qr` y usa solo el PIN.

## Problemas de control

### El puntero va lento o demasiado rápido

*Ajustes → Velocidad del puntero*. El valor por defecto es 1,6×. Si lo pones
muy alto, desactiva la **aceleración** para que sea predecible.

### El puntero no llega a las esquinas

Las **zonas de borde** aceleran al acercarse al límite. Si las has desactivado,
vuelve a activarlas en *Ajustes*.

### El scroll va al revés

*Ajustes → Desplazamiento natural*. Activado = como en el celular (deslizas
hacia arriba y el contenido sube).

### Algo se quedó arrastrando

1. Pulsa **Soltar** en la barra inferior.
2. O el botón **Puntero** de la barra superior (interruptor del arrastre fijo).
3. Si el celular se desconecta, el servidor suelta todo solo.

### Los clics no responden o se pierden

- Mira la latencia en la barra superior. Por encima de 150 ms la sensación es
  mala: acércate al router o usa la banda de 5 GHz.
- Si el celular está con la pantalla ahorrando energía, el navegador puede
  frenar los eventos. Mantén la pestaña en primer plano (la app pide el
  *wake lock*, pero el navegador puede denegarlo).

### El teclado escribe en otro sitio

El texto va a la **ventana que tenga el foco** en la PC en ese momento. Si
escribiste en el campo del celular y el foco estaba en otra ventana, el texto
aparece ahí. Comprueba el foco antes de escribir.

### El volumen no cambia

Las teclas multimedia se envían al sistema; si el reproductor no está en primer
plano, algunas aplicaciones las ignoran. Windows sí cambia el volumen general.

### Ctrl+Alt+Supr no hace nada

Windows reserva esa combinación al sistema y **no se puede simular** desde una
aplicación normal. La app lo avisa en lugar de fallar en silencio.

## Problemas de la aplicación

### La app se queda "Desconectado"

1. Reinicia el servidor.
2. En la app, pulsa **Reconectar**.
3. Comprueba que el celular no haya cambiado de red WiFi.

La reconexión es automática (con espera creciente hasta 6 segundos), así que
suele resolverse sola si el servidor vuelve.

### Tras cambiar de red, no entra

El token está ligado al dispositivo, no a la red, pero la **dirección cambió**.
Abre la nueva dirección que muestra la consola.

### Quiero empezar de cero con este celular

*Ajustes → Olvidar este dispositivo*, y escribe el PIN de nuevo.

### Aparece "demasiadas órdenes por segundo"

El servidor descarta lo que sobra para no saturar la entrada del sistema. Suele
pasar al apoyar la mano entera sobre la pantalla. Separa los dedos y sigue.

## Problemas al arrancar

### "No encuentro Python en el PATH"

Reinstala Python desde [python.org](https://www.python.org/downloads/) marcando
**Add python.exe to PATH**.

### "No se pudieron instalar las dependencias"

Instálalas a mano para ver el error real:

```bash
python -m pip install --user aiohttp
```

Si es un problema de permisos, evita `--user` y usa un entorno virtual:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### "Falta el controlador del escritorio"

Falta `aiohttp`. Ejecuta `iniciar.bat`, que lo instala.

### El servidor arranca pero no pasa nada al pulsar teclas

Comprueba que el servidor no esté ejecutándose **como administrador** mientras
la ventana de destino no lo está: Windows bloquea la inyección de entrada entre
niveles de integridad distintos (UIPI). Ejecuta ambos al mismo nivel.

## Comprobar que todo está bien

Doble clic en **`probar.bat`**. Arranca un servidor de pruebas, ejecuta las
suites y lo detiene. Si algo falla, la salida indica exactamente qué.
