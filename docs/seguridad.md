# Seguridad

RemotePad controla el mouse y el teclado de tu PC. Estas son las medidas que
tiene y, sobre todo, las que **no** tiene.

## En resumen

| Medida | Estado |
|---|---|
| PIN de 6 dígitos rotativo | Sí |
| Código QR de un solo uso | Sí |
| Token por dispositivo (guardado solo como huella) | Sí |
| Lista de dispositivos y retirada de accesos | Sí |
| Permiso en la PC para cada dispositivo nuevo | Opcional (`--confirmar`) |
| Límite de intentos fallidos | Sí |
| Límite de caudal de órdenes | Sí |
| Rechazo de conexiones desde otras páginas web (`Origin`) | Sí |
| Solo red local (sin exponer a internet) | Sí |
| Cifrado del tráfico | Opcional (`--https`) |

## Cómo se protege el acceso

### PIN de 6 dígitos

Se muestra **solo en la consola de la PC** y se genera con
`secrets.randbelow` (generador criptográfico, no `random`). Se renueva:

- al arrancar el servidor;
- cada **5 minutos**;
- antes de cada acción sensible, por si el celular llevaba rato inactivo.

La comprobación es en tiempo constante y **no distingue** un PIN de seis ceros
de uno correcto por el tiempo que tarda en responder.

### Código QR de un solo uso

Ver [qr.md](qr.md). Su clave **vale 3 minutos**, se invalida al primer canje y se
compara también en tiempo constante. El panel de la PC muestra siempre uno
vigente, pero una foto del código deja de servir a los pocos minutos.

Durante **20 segundos adicionales** (`QR_GRACE_SECONDS`) se sigue aceptando el
código anterior, para que la renovación no haga fallar un escaneo que llegó un
instante tarde. Es una ventana pequeña y acotada, y cada código sigue sirviendo
**una sola vez**.

### Detener el servicio

- **Desde el celular**: el botón de *Ajustes* pide la parada por el WebSocket, y
  solo funciona si el dispositivo **ya está autorizado**. Cualquiera que haya
  entrado puede apagar el servidor, del mismo modo que puede mover tu puntero.
- **Desde la PC**: `/api/stop` (el panel o una consola). **Solo responde a la
  propia PC**, para que nadie de la red pueda apagarlo por esa vía.
- **Desde la consola**: escribir `q` y pulsar ENTER.

Apagar el servidor no borra los tokens: se guardan en `server/tokens.json` y, al
volver a arrancarlo, los celulares que ya estaban autorizados entran sin pedir
nada (hasta 30 días). El archivo guarda solo la **huella SHA-256** de cada
token, nunca el token: quien lo copie no obtiene un acceso válido. Aun así está
en `.gitignore` y no se comparte.

### Quitar el código de acceso

Se puede desactivar por completo (PIN y QR) de cuatro formas:
`quitar-codigo.bat` (doble clic), `--no-auth` al arrancar, el botón
*Ajustes → Quitar el código de acceso* en el celular, o el comando `auth off` en
la consola de la PC.

**Es la opción menos segura de todas**: mientras está quitado, cualquier
dispositivo de tu red puede conectarse y manejar el ratón y el teclado sin
ninguna credencial. Por eso:

- la consola muestra un **recuadro de aviso** mientras dure;
- la pantalla de acceso de la app lo indica;
- el panel del QR avisa y deja de mostrar códigos;
- solo un dispositivo **ya autorizado** (o la propia PC) puede cambiarlo, así
  que nadie de la red puede quitarse la protección por su cuenta.

Al volver a activarlo se genera un **PIN nuevo** y los accesos anteriores
siguen valiendo (no se expulsa a quien ya estaba dentro). Está pensado para
pruebas o para una red de total confianza; vuelve a activarlo después.

### Token de dispositivo

Tras acertar el PIN o el QR, el celular recibe un token de 24 bytes
(`secrets.token_urlsafe`) que guarda en `localStorage` y dura 30 días. Así no
hay que teclear el PIN cada vez.

- En la PC solo se guarda su huella SHA-256, junto con el nombre del
  dispositivo (sacado del navegador), su dirección y la última conexión.
- Se comparan las huellas con `hmac.compare_digest`, recorriendo la lista.
- Los caducados se purgan solos.
- *Ajustes → Olvidar este dispositivo* lo retira también en la PC: el token
  deja de valer en todas partes.

### Dispositivos con acceso

En *Ajustes → Dispositivos con acceso* (o con `dispositivos` en la consola)
se ve qué equipos pueden entrar, desde dónde y cuándo se conectaron por última
vez. Cualquiera se puede quitar (*Quitar*, o `revocar <código>` en la consola):
si está conectado se le desconecta al momento y tendrá que volver a escanear
el QR o escribir el PIN.

Cada vez que entra un dispositivo nuevo, la consola lo anuncia (con el comando
para quitarlo) y los demás celulares conectados reciben un aviso.

### Permiso en la PC para los dispositivos nuevos (opcional)

Con `--confirmar`, `confirmar on` en la consola o el interruptor de *Ajustes*,
acertar el PIN o escanear el QR ya no basta: la PC pregunta en una ventana (o
en la consola, escribiendo `si` / `no`) si deja entrar a ese dispositivo. Sin
respuesta en 60 segundos, se rechaza. Funciona como un segundo factor: hace
falta ver la pantalla **y** estar delante de la PC.

### Origen del WebSocket

El servidor rechaza las conexiones WebSocket cuya cabecera `Origin` no es la
suya. Sin esto, cualquier página web abierta en un navegador de tu red podía
conectarse a RemotePad (y, con el código de acceso quitado, manejar la PC).

### El PIN no sale de la PC

El PIN solo se muestra en la consola, en el panel `/qr` (que solo responde a
la propia PC) y a los dispositivos **ya autorizados** (para que puedan dejar
entrar a otro). Hasta la versión 1.7 la pantalla de acceso del celular
recibía el PIN antes de autenticarse, así que cualquiera de la red podía
leerlo; desde la 1.8 no se envía nunca a quien no ha entrado, y el registro
tampoco lo escribe al fallar un intento.

### Límite de intentos

- **8 fallos de PIN** desde una misma dirección → bloqueo de 5 minutos.
- **10 fallos de clave QR** desde una misma dirección → bloqueo de 5 minutos.

Es defensa contra la fuerza bruta desde la red. No protege contra alguien que
pueda leer la pantalla de la PC: en ese caso el PIN y el QR son, por diseño,
la llave.

### Límite de caudal

450 acciones por segundo y cliente. Evita que un celular descontrolado (o un
script) sature la cola de entrada del sistema operativo.

## Qué NO está protegido

### Sin `--https`, el tráfico no va cifrado

Por defecto, HTTP y WebSocket van en claro. En una red WiFi doméstica con
WPA2/WPA3 esto es equivalente a la protección del propio WiFi, pero
**cualquiera que pueda escuchar el tráfico de tu red podría leer el PIN y el
token**.

Si eso te preocupa, hay dos caminos:

1. **HTTPS** (`iniciar.bat --https`): RemotePad crea una autoridad local y un
   certificado para la IP de tu PC (en `server/https/`, que no se versiona).
   La primera vez el celular avisa de que la conexión no es privada; para que
   confíe sin avisos, instala la autoridad desde `https://<ip-de-la-pc>:8765/ca.crt`
   (Android: *Ajustes → Seguridad → Cifrado y credenciales → Instalar un
   certificado → Certificado de CA*) y comprueba que su huella empieza como
   indica la consola. Necesita el paquete `cryptography`, que `iniciar.bat`
   instala si hace falta. Si cambia la IP de la PC se vuelve a firmar el
   certificado con la misma autoridad: no hay que reinstalar nada.
2. **Túnel**: usa la app solo a través de una VPN (Tailscale, WireGuard…) y
   escucha en la interfaz de la VPN.

### Un dispositivo autorizado tiene control total

No hay permisos por acción ni modo "solo lectura" para quien ya entró, salvo el
modo espectador (solo desde la propia PC), que solo puede mirar. Quien tenga el
token puede mover el puntero, escribir, pulsar teclas multimedia y ejecutar sus
atajos propios. Los atajos solo pueden hacer lo que haría el teclado
(combinaciones, texto y esperas, con límites): no hay pasos para lanzar
programas ni ejecutar órdenes.

### El QR es tan sensible como el PIN

Quien vea la pantalla de la PC puede hacer una foto al QR y entrar mientras
siga vigente. Es inherente al diseño "sin escribir nada"; si no lo quieres,
arranca con `--no-qr` y usa solo el PIN.

## Superficie de red

- El servidor escucha en `0.0.0.0`, es decir **en todas las interfaces**. Si tu
  PC tiene una interfaz expuesta a internet, el servidor también lo está.
  Para limitarlo: `python app.py --host 192.168.1.9`.
- Los recursos estáticos usan **lista blanca de extensiones** y comprobación de
  ruta resuelta, así que no se puede pedir `../server/app.py`.
- `/qr`, `/qr/stream` y `/qr/new` **solo responden a la propia PC**.
- No hay redirecciones ni inclusión de contenido externo: la aplicación es
  completamente local (el service worker solo cachea sus propios archivos).

## Recomendaciones prácticas

1. **No lo expongas a internet** tal cual. Si necesitas acceso desde fuera,
   usa una VPN.
2. Si usas el QR a diario, ten en cuenta que cualquiera que vea tu pantalla
   puede entrar durante esos 5 minutos. El PIN tiene el mismo problema.
3. Revisa los avisos de la consola: cada acceso se registra con la dirección de
   origen.
4. Si sospechas, revisa *Ajustes → Dispositivos con acceso* (o escribe
   `dispositivos` en la consola) y quita los que no reconozcas. Para cortar
   todos los accesos de golpe: para el servidor y **borra
   `server/tokens.json`**. Si quieres que nadie nuevo entre sin tu permiso,
   activa la confirmación (`--confirmar`).
5. **El panel `/qr` debe quedarse en la PC.** No lo abras desde otro equipo: no
   funcionará (por diseño) y, si lo hiciera, estarías regalando el acceso.

## Registro

El servidor anota en la consola:

- cada conexión y desconexión, con la dirección de origen;
- cada autorización correcta (por token, por PIN o por QR);
- cada intento fallido;
- cada renovación de PIN y de clave QR.

No se guarda nada en disco: todo vive en memoria y desaparece al cerrar.
