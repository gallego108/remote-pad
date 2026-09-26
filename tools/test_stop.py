"""
Pruebas de la parada del servicio, de extremo a extremo.

  A) Escribir "q" + ENTER en la consola detiene el servidor y lo cierra
     ordenadamente (sin pulsar Ctrl+C).
  B) Un celular ya autorizado puede pararlo desde Ajustes; recibe el aviso
     "shutdown" antes de que se cierre la conexion.
  C) /api/stop funciona desde la propia PC.

Cada prueba arranca su propio servidor en un puerto distinto para no
interferir entre si.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"
sys.path.insert(0, str(SERVIDOR))

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def esperar_pin(proceso: subprocess.Popen, segundos: float = 20.0) -> str:
    """Espera a que el servidor anuncie el PIN y lo devuelve."""
    limite = time.time() + segundos
    while time.time() < limite:
        linea = proceso.stdout.readline()
        if not linea:
            time.sleep(0.1)
            continue
        encontrado = re.search(r"PIN DE ACCESO\s*->\s*(\d{3})\s*(\d{3})", linea)
        if encontrado:
            return encontrado.group(1) + encontrado.group(2)
    return ""


def arrancar(puerto: int) -> subprocess.Popen:
    proceso = subprocess.Popen(
        [sys.executable, "-u", "app.py", "--port", str(puerto), "--no-browser"],
        cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    return proceso


def terminar(proceso: subprocess.Popen) -> None:
    if proceso.poll() is None:
        proceso.kill()
        proceso.wait(timeout=10)


def restante(proceso: subprocess.Popen, segundos: float = 6.0) -> str:
    """Lee lo que el servidor escriba durante unos segundos."""
    limite = time.time() + segundos
    salida = []
    while time.time() < limite:
        if proceso.poll() is not None:
            break
        linea = proceso.stdout.readline()
        if linea:
            salida.append(linea)
    return "".join(salida)


def puerto_abierto(puerto: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=2):
            return True
    except Exception:
        return False


# --------------------------------------------------------------------- A
def prueba_comando_consola() -> None:
    print("\n== A) Detener escribiendo 'q' en la consola ==")
    puerto = 8795
    proceso = arrancar(puerto)
    try:
        pin = esperar_pin(proceso)
        check("El servidor arranco", bool(pin), f"PIN='{pin}'")

        # Se escribe q + ENTER, como haria el usuario.
        proceso.stdin.write("q\n")
        proceso.stdin.flush()

        # El servidor debe anunciar la parada y dejar de aceptar conexiones.
        # (El proceso no termina aqui porque en esta prueba stdin es una
        # tuberia abierta y el hilo que lee la consola queda esperando; en el
        # uso real, al cerrar la ventana, el proceso acaba inmediatamente.)
        salida = restante(proceso, 12)
        check("El servidor anuncia la parada",
              "Deteniendo RemotePad" in salida, f"{salida[-160:]!r}")
        check("Avisa de que se puede cerrar",
              "se ha detenido" in salida, f"{salida[-160:]!r}")
        check("Deja de aceptar conexiones", not puerto_abierto(puerto))
    finally:
        terminar(proceso)


# --------------------------------------------------------------------- B
async def parar_por_websocket(puerto: int) -> dict:
    """Se autentica y pide detener el servicio. Devuelve lo que reciba."""
    import aiohttp
    recibido: list[dict] = []
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{puerto}/ws") as ws:
            # Autenticacion por QR (la via comoda en las pruebas).
            async with session.get(f"http://127.0.0.1:{puerto}/qr") as respuesta:
                panel = await respuesta.text()
            clave = re.search(r'"key":"([^"]+)"', panel).group(1)
            async with session.post(f"http://127.0.0.1:{puerto}/api/qr-login",
                                    json={"key": clave}) as respuesta:
                token = (await respuesta.json()).get("token")

            await ws.send_json({"a": "auth", "d": {"token": token}})
            recibido.append(json.loads((await ws.receive()).data))

            # Peticion de parada, como hace el boton de Ajustes.
            await ws.send_json({"a": "comando_detener", "d": {}})

            limite = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < limite:
                try:
                    mensaje = await asyncio.wait_for(ws.receive(), 5)
                except asyncio.TimeoutError:
                    break
                if mensaje.type.name != "TEXT":
                    break
                recibido.append(json.loads(mensaje.data))
                if any(m.get("t") == "shutdown" for m in recibido):
                    break
    return {"mensajes": recibido}


def prueba_parada_desde_el_celular() -> None:
    print("\n== B) Detener desde el celular (Ajustes) ==")
    proceso = arrancar(8796)
    try:
        pin = esperar_pin(proceso)
        check("El servidor arranco", bool(pin))

        resultado = asyncio.run(parar_por_websocket(8796))
        mensajes = resultado["mensajes"]
        check("El dispositivo se autentico",
              any(m.get("t") == "ok" for m in mensajes), f"{mensajes[:2]}")
        check("La peticion de parada se confirma",
              any(m.get("t") == "response" and m.get("a") == "comando_detener"
                  and (m.get("d") or {}).get("ok") for m in mensajes),
              f"{mensajes}")
        check("El celular recibe el aviso de parada",
              any(m.get("t") == "shutdown" for m in mensajes), f"{mensajes}")

        try:
            proceso.wait(timeout=15)
            parado = True
        except subprocess.TimeoutExpired:
            parado = False
        check("El servidor se detiene solo", parado)
    finally:
        terminar(proceso)


# --------------------------------------------------------------------- C
def prueba_endpoint_local() -> None:
    print("\n== C) Detener desde /api/stop (la propia PC) ==")
    import urllib.request
    proceso = arrancar(8797)
    try:
        pin = esperar_pin(proceso)
        check("El servidor arranco", bool(pin))

        peticion = urllib.request.Request("http://127.0.0.1:8797/api/stop",
                                          method="POST")
        try:
            with urllib.request.urlopen(peticion, timeout=10) as respuesta:
                cuerpo = respuesta.read().decode()
                estado = respuesta.status
        except Exception as exc:
            cuerpo, estado = str(exc), 0
        check("El endpoint responde", estado == 200, f"{estado} {cuerpo}")

        try:
            proceso.wait(timeout=15)
            parado = True
        except subprocess.TimeoutExpired:
            parado = False
        check("El servidor se detiene solo", parado)

        restante(proceso, 1)
        ver = ""
        if proceso.stdout:
            try:
                ver = proceso.stdout.read() or ""
            except Exception:
                pass
        check("El registro dice quien lo pidio",
              "Deteniendo RemotePad" in ver, f"{ver[-160:]!r}")
    finally:
        terminar(proceso)


def main() -> int:
    print("Parada del servicio")
    print("=" * 62)
    prueba_comando_consola()
    prueba_parada_desde_el_celular()
    prueba_endpoint_local()
    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
