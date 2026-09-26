# Instalación

## Requisitos

| Elemento | Mínimo | Notas |
|---|---|---|
| Sistema | Windows 10 o superior | La capa de entrada usa la API Win32 |
| Python | 3.9 o superior | Solo se probó a fondo en 3.12 |
| `aiohttp` | 3.9 o superior | Única dependencia; la instala `iniciar.bat` |
| Celular | Cualquier Android con Chrome | También funciona en iPhone (Safari) |
| Red | WiFi común (misma subred) | No hace falta internet |

**No hacen falta permisos de administrador.** La dependencia se instala en el
site-packages del usuario (`pip install --user`).

### Comprobar la versión de Python

```bash
python --version
```

Si no lo tienes, instálalo desde [python.org](https://www.python.org/downloads/)
marcando **Add python.exe to PATH**.

## Instalación

### Opción 1: el lanzador (recomendado)

Doble clic en `iniciar.bat`. Si falta `aiohttp`, lo instala solo la primera vez
y arranca el servidor.

### Opción 2: a mano

```bash
cd server
python -m pip install --user -r requirements.txt
python app.py
```

## Primer arranque

```
==========================================================
   PIN DE ACCESO  ->  482 913
   (cambia automáticamente cada 5 minutos)
==========================================================
   Abre esta direccion en el navegador del celular:
       http://192.168.1.9:8765
   Desde esta misma PC:  http://127.0.0.1:8765
   (el celular debe estar en la MISMA red WiFi)
==========================================================
   O escanea este QR y entra sin escribir nada:
   ...
```

1. Conecta el celular a la **misma WiFi**.
2. Escanea el QR con la cámara, o abre la dirección y escribe el PIN.
3. Listo.

### Aviso del Firewall de Windows

La primera vez, Windows preguntará si permites el tráfico de red para Python.
**Marca "Redes privadas" y acepta.** Si lo cancelas, el celular no podrá
conectarse: para arreglarlo, busca "Permitir una aplicación a través del
Firewall de Windows" y habilita Python (o el `python.exe` que uses).

## Instalarlo como app en el celular

1. Abre la dirección en Chrome.
2. Menú ⋮ → **Añadir a pantalla de inicio**.
3. Aparecerá un icono como el de cualquier app, a pantalla completa y sin barra
   de direcciones.

El dispositivo recuerda el acceso con un token, así que las próximas veces
entra directamente. Si quieres que pida el PIN otra vez:
*Ajustes → Olvidar este dispositivo*.

## Arrancar automáticamente con Windows (opcional)

1. Pulsa `Win + R`, escribe `shell:startup` y acepta.
2. Crea ahí un **acceso directo** a `iniciar.bat`.

Si te molesta que abra el panel del QR cada vez, añade `--no-browser`:

```
"RUTA\remote-pad\iniciar.bat" --no-browser
```

## Desinstalar

1. Borra la carpeta del proyecto.
2. Quita el acceso directo de `shell:startup`, si lo creaste.
3. Opcional: `python -m pip uninstall aiohttp` (solo si no lo usa otra cosa).
4. En el celular, quita el icono de la pantalla de inicio.

No se escribe nada en el registro ni se instalan servicios.
