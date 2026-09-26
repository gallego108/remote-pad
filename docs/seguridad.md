# Seguridad

RemotePad controla el mouse y el teclado de tu PC. Estas son las medidas que
tiene y, sobre todo, las que **no** tiene.

## En resumen

| Medida | Estado |
|---|---|
| PIN de 6 dígitos rotativo | Sí |
| Código QR de un solo uso | Sí |
| Token por dispositivo | Sí |
| Límite de intentos fallidos | Sí |
| Límite de caudal de órdenes | Sí |
| Solo red local (sin exponer a internet) | Sí |
| Cifrado del tráfico | **No** |
| Autenticación de dos factores | **No** |

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

### Detener el servicio

- **Desde el celular**: el botón de *Ajustes* pide la parada por el WebSocket, y
  solo funciona si el dispositivo **ya está autorizado**. Cualquiera que haya
  entrado puede apagar el servidor, del mismo modo que puede mover tu puntero.
- **Desde la PC**: `/api/stop` (el panel o una consola). **Solo responde a la
  propia PC**, para que nadie de la red pueda apagarlo por esa vía.
- **Desde la consola**: escribir `q` y pulsar ENTER.

Apagar el servidor no borra los tokens: al volver a arrancarlo, los celulares
que ya estaban autorizados entran sin pedir nada (hasta 30 días).

### Token de dispositivo

Tras acertar el PIN o el QR, el celular recibe un token de 24 bytes
(`secrets.token_urlsafe`) que guarda en `localStorage` y dura 30 días. Así no
hay que teclear el PIN cada vez.

- Se comparan con `hmac.compare_digest`, recorriendo la lista completa.
- Los caducados se purgan al emitir uno nuevo.
- *Ajustes → Olvidar este dispositivo* lo borra del celular.

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

### El tráfico no va cifrado

HTTP y WebSocket en claro. En una red WiFi doméstica con WPA2/WPA3 esto es
equivalente a la protección del propio WiFi, pero **cualquiera que pueda
escuchar el tráfico de tu red podría leer el PIN y el token**.

Si eso te preocupa, hay dos caminos:

1. **Túnel**: usa la app solo a través de una VPN (Tailscale, WireGuard…) y
   escucha en la interfaz de la VPN.
2. **HTTPS**: haría falta un certificado y aceptar el aviso del navegador (o
   instalar el certificado en el celular). No está implementado.

### Un dispositivo autorizado tiene control total

No hay permisos por acción ni modo "solo lectura" para quien ya entró, salvo el
modo espectador, que se declara al conectar y solo puede mirar. Quien tenga el
token puede mover el puntero, escribir y pulsar teclas multimedia.

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
4. Si sospechas, reinicia el servidor: **todos los tokens siguen siendo
   válidos** (duran 30 días), así que además conviene usar *Olvidar este
   dispositivo* en cada celular, o borrar el token del `localStorage`.
5. **El panel `/qr` debe quedarse en la PC.** No lo abras desde otro equipo: no
   funcionará (por diseño) y, si lo hiciera, estarías regalando el acceso.

## Registro

El servidor anota en la consola:

- cada conexión y desconexión, con la dirección de origen;
- cada autorización correcta (por token, por PIN o por QR);
- cada intento fallido;
- cada renovación de PIN y de clave QR.

No se guarda nada en disco: todo vive en memoria y desaparece al cerrar.
