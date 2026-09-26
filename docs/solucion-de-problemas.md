# Solución de problemas

Antes de nada, si el celular no conecta ejecuta:

```bash
python tools/diagnostico_red.py 8765
```

Comprueba en qué dirección escucha el servidor, si responde por la IP de la red
local, cómo está clasificada la red WiFi y qué reglas del Firewall afectan al
puerto.

## El celular dice "no se puede conectar"

**Es el Firewall de Windows, casi siempre.** Motivo comprobado: Windows tiene
reglas de entrada para `python.exe` **solo de tipo UDP** (mDNS y similares), y
el servidor usa **TCP**. Sin una regla TCP de entrada, el celular no puede
llegar a la PC aunque la aplicación funcione perfectamente en local.

### Solución

Doble clic en **`abrir-firewall.bat`** y acepta el aviso de administrador.
Crea la regla para el puerto 8765 (y un rango pequeño por si usas `--port`) y
muestra la dirección que debe abrir el celular.

Hacerlo a mano, desde una consola **como administrador**:

```bat
netsh advfirewall firewall add rule name="RemotePad TCP 8765" dir=in action=allow protocol=TCP localport=8765
```

Para quitarlo después:

```bat
netsh advfirewall firewall delete rule name="RemotePad TCP 8765"
```

### Alternativa sin tocar el Firewall

Cambiar la red WiFi a **Privada**, que es lo que Windows espera para una red de
casa:

*Configuración → Red e Internet → WiFi → Propiedades → Perfil de red: Privada*

O por consola (como administrador):

```powershell
Set-NetConnectionProfile -NetworkCategory Private
```

### Comprobar si ya está resuelto

Con el servidor en marcha:

```bash
python tools/diagnostico_red.py 8765
```

Debe aparecer `[OK] red local: 192.168.1.9:8765 responde` y una regla de
entrada que permite el puerto.

### Si aun así no conecta

1. **Misma red**: el celular no debe estar en datos móviles ni en otra WiFi.
2. **Red de invitados**: muchas aíslan los equipos entre sí. Prueba con el punto
   de acceso del celular: conecta la PC a él y usa la IP que muestre la consola.
3. **Antivirus de terceros**: algunos (Kaspersky, ESET, Bitdefender) tienen su
   propio cortafuegos y bloquean las conexiones entrantes. Autoriza Python ahí.
4. **Red equivocada**: si la PC tiene varias interfaces (WiFi y Ethernet),
   comprueba que la IP del QR es la de la interfaz que usa el celular. Puedes
   forzarla con `--host`. 

### Verificar que el servidor escucha bien

```
netstat -ano | findstr :8765
```

Debe aparecer `0.0.0.0:8765 ... LISTENING`. Si aparece `127.0.0.1:8765`, se
arrancó con `--host 127.0.0.1` y el celular nunca podrá entrar.

### "No se pudo abrir el puerto 8765"

Otro programa lo ocupa. Usa otro puerto:

```
iniciar.bat --port 8899
```

Recuerda que **cambiar de puerto requiere volver a abrir el Firewall** para ese
puerto (`abrir-firewall.bat 8899`); el rango que abre el script cubre de 8765 a
8799, así que cualquier puerto de ese rango ya queda permitido.

## Problemas de acceso

### "PIN incorrecto" siempre

- El PIN **caduca cada 5 minutos**. Mira el valor actual en la consola.
- En la app, el botón **PIN** de la barra superior muestra el vigente.
- Se bloquea tras 8 fallos seguidos desde el mismo celular: espera 5 minutos.
- Si tienes varios servidores abiertos, asegúrate de estar mirando la consola
  del que escucha en el puerto que abriste.

### El celular pide el PIN en vez de entrar con el QR

Este síntoma significa que el celular llega a la PC (red y Firewall correctos)
pero **no está ejecutando el canje del QR**: casi siempre es una **copia antigua
de la aplicación guardada en el propio teléfono**.

Un caso real y muy confuso: en el celular aparecía
**«acción desconocida: auth»**. Ese mensaje lo genera el servidor cuando recibe
una acción que no reconoce, y el código actual **no puede** responder eso a una
acción `auth`. Lo que pasaba es que el teléfono ejecutaba un `app.js` de una
versión anterior (de antes de que existiera el QR), que enviaba `auth` sin el
manejo correspondiente. Es decir: **el mensaje no venía de la versión instalada,
sino de la copia vieja del navegador**.

Desde la versión 1.4.0 esto se detecta y se corrige solo:

- el servidor inyecta su versión en el HTML y la página, si no coincide con la
  suya, **se recarga con `?v=<versión>`** saltando la caché;
- si aun así no cuadra (porque el HTML viejo tampoco trae la etiqueta), muestra
  un aviso pidiendo vaciar la caché, sin entrar en bucle;
- el *service worker* pide el código de la app **siempre a la red**;
- en *Ajustes* de la app se ve la **versión** que está ejecutando el celular.

Si te ocurre en un teléfono que ya tenía la app instalada:

1. Recarga la página (el propio aviso te lo pedirá).
2. Si sigue igual: Chrome → menú ⋮ → *Configuración del sitio* → **Borrar
   datos**, y recarga.
3. Comprueba en *Ajustes* que dice **«versión 1.4.0»**. Si no aparece, sigues
   con la copia antigua.

### Al escanear el QR, la página carga pero pide el PIN

Este síntoma —**la página abre bien, pero pide el código**— significa que el
celular llega a la PC (red y Firewall correctos) pero **no está ejecutando el
canje del QR**. Casi siempre es una **copia antigua de la aplicación guardada en
el propio teléfono** (la caché del navegador o del *service worker*), de una
versión anterior a que existiera el acceso por QR.

Desde la versión 1.2.0 esto ya no debería ocurrir:

- el servidor **inyecta la clave del QR dentro del HTML**, así que no depende de
  que el navegador conserve el `?k=` de la dirección (algunos visores de cámara
  lo recortan al redirigir);
- esa página se sirve con `Cache-Control: no-store`;
- el *service worker* pide la versión del servidor y, si detecta una nueva,
  **recarga la pestaña sola**.

Si te encuentras con esta situación en un celular que ya tenía la app instalada:

1. En Chrome, abre el menú ⋮ → *Configuración del sitio* (o el candado de la
   barra de direcciones) → **Borrar datos**.
2. Recarga la página.
3. Para confirmar que ya tienes la versión nueva: *Ajustes* dentro de la app
   muestra **«versión 1.2.0»** al final. Si no aparece, sigues con la copia
   antigua.

Y un aviso: si tocas el campo del PIN y empiezas a escribir, la app entiende que
prefieres el PIN y **no** usa el QR. Deja el campo vacío y toca *Conectar* para
que use el código de la página.

### "Ese código ya se usó o pasó su tiempo"

Cada QR **vale 3 minutos** y sirve **una sola vez**. Escanea el que muestra la
PC en ese momento: el panel `/qr` y la consola generan uno nuevo
automáticamente, así que siempre hay uno vigente.

### El servicio no se detiene

- Escribe **`q` + ENTER** en la consola del servidor, o **`Ctrl+C`**.
- Desde el celular: *Ajustes → Detener RemotePad en la PC* (solo funciona si ya
  entraste antes).
- Si el botón del celular no hace nada, puede que la app del teléfono siga con
  una copia antigua: borra los datos del sitio y recarga.
- Comprueba que no haya **otro servidor** escuchando en otro puerto: cada
  `iniciar.bat` abre un proceso. Se ven con
  `netstat -ano | findstr LISTENING | findstr :87`.

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
