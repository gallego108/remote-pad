"""
Pruebas del codigo de acceso desactivable.

  A) Arrancar con --no-auth: un celular entra sin PIN ni QR.
  B) Desactivarlo en caliente desde un dispositivo ya autorizado.
  C) Desactivarlo con el comando "auth off" de la consola.
  D) Volver a activarlo genera un PIN nuevo y vuelve a pedir codigo.
  E) Cambiar el modo exige estar autorizado (o ser la propia PC).

Cada prueba arranca su propio servidor en un puerto distinto.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def arrancar(puerto: int, extra: list[str] | None = None) -> subprocess.Popen:
    orden = [sys.executable, "-u", "app.py", "--port", str(puerto), "--no-browser"]
    if extra:
        orden += extra
    return subprocess.Popen(
        orden, cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )


def esperar_pin(proceso: subprocess.Popen, segundos: float = 20.0) -> str:
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


def esperar_texto(proceso: subprocess.Popen, texto: str,
                  segundos: float = 20.0) -> str:
    """Espera a que aparezca un texto en la salida y devuelve lo leido."""
    limite = time.time() + segundos
    leido = []
    while time.time() < limite:
        linea = proceso.stdout.readline()
        if not linea:
            time.sleep(0.1)
            continue
        leido.append(linea)
        if texto in linea:
            break
    return "".join(leido)


def terminar(proceso: subprocess.Popen) -> None:
    """Cierra el servidor de prueba sin dejar tuberias colgando."""
    if proceso.poll() is not None:
        return
    try:
        proceso.stdin.close()
    except Exception:
        pass
    try:
        proceso.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    proceso.kill()
    try:
        proceso.wait(timeout=5)
    except Exception:
        pass


async def esperar_respuesta(ws, accion: str, limite: float = 8.0) -> dict:
    """
    Espera el resultado de una accion, ignorando avisos previos.

    Dos detalles del protocolo que hay que respetar:
      - al cambiar el modo, el servidor manda el aviso 'auth_mode' antes de la
        respuesta, asi que no se puede asumir que el siguiente mensaje sea la
        respuesta;
      - la autenticacion no responde con 'response': contesta directamente con
        'ok' o 'auth_fail'.
    """
    loop = asyncio.get_running_loop()
    fin = loop.time() + limite
    while loop.time() < fin:
        recibido = await asyncio.wait_for(ws.receive(), fin - loop.time())
        if recibido.type.name != "TEXT":
            return {"t": f"<{recibido.type.name}>"}
        mensaje = json.loads(recibido.data)
        if accion == "auth":
            if mensaje.get("t") in ("ok", "auth_fail", "auth_required"):
                return mensaje
            continue
        if mensaje.get("t") == "response" and mensaje.get("a") == accion:
            return mensaje.get("d") or {}
        # Los avisos (auth_mode, pin, qr_key...) se ignoran.
    return {}


async def pedir(puerto: int, preparar, accion: str, datos: dict) -> dict:
    """
    Abre el WebSocket, ejecuta `preparar` (autenticarse y demas) y devuelve la
    respuesta de la ultima accion.
    """
    import aiohttp
    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://127.0.0.1:{puerto}/ws") as ws:
            for mensaje, esperada in preparar:
                await ws.send_json(mensaje)
                await esperar_respuesta(ws, esperada)
            await ws.send_json({"a": accion, "d": datos})
            return await esperar_respuesta(ws, accion)


async def conectar(puerto: int, mensaje: dict, accion: str = "") -> dict:
    """Abre el WebSocket, manda un mensaje y devuelve su respuesta."""
    import aiohttp
    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://127.0.0.1:{puerto}/ws") as ws:
            await ws.send_json(mensaje)
            if accion:
                return await esperar_respuesta(ws, accion)
            recibido = await asyncio.wait_for(ws.receive(), 8)
            if recibido.type.name != "TEXT":
                return {"t": f"<{recibido.type.name}>"}
            return json.loads(recibido.data)


def clave_del_panel(puerto: int) -> str:
    panel = urllib.request.urlopen(f"http://127.0.0.1:{puerto}/qr",
                                   timeout=5).read().decode()
    return re.search(r'"key":"([^"]+)"', panel).group(1)


# --------------------------------------------------------------------- A
def prueba_arranque_sin_codigo() -> None:
    print("\n== A) Arrancar con --no-auth ==")
    puerto = 8810
    proceso = arrancar(puerto, ["--no-auth"])
    try:
        # Se espera al aviso de riesgo completo (el recuadro), no solo al titulo.
        salida = esperar_texto(proceso, "puede manejar la PC", 20)
        check("El arranque avisa de que no hay codigo",
              "CONTROL DE ACCESO DESACTIVADO" in salida, salida[-300:])
        check("Y avisa del riesgo",
              "puede manejar la PC" in salida, salida[-300:])
        check("No muestra PIN", "PIN DE ACCESO" not in salida)

        # Un celular entra sin mandar nada.
        respuesta = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Un celular entra sin PIN ni QR",
              respuesta.get("t") == "ok" and respuesta.get("status") == "auth",
              f"{respuesta}")
        check("Y recibe un token", bool(respuesta.get("token")))

        # La consulta de estado tambien lo dice.
        estado = asyncio.run(conectar(puerto, {"a": "auth_query", "d": {}}))
        check("La consulta de estado dice que no hace falta codigo",
              estado.get("t") == "auth_state" and estado.get("required") is False,
              f"{estado}")

        # Y el canje del QR tambien funciona sin clave.
        try:
            datos = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{puerto}/api/qr-login",
                data=json.dumps({"key": "lo-que-sea"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST"),
                timeout=5).read().decode())
            check("El canje del QR no exige clave", datos.get("ok") is True)
        except Exception as exc:
            check("El canje del QR no exige clave", False, str(exc))
    finally:
        terminar(proceso)


# --------------------------------------------------------------------- B
def prueba_desactivar_en_caliente() -> None:
    print("\n== B) Desactivar desde el celular (ya autorizado) ==")
    puerto = 8811
    proceso = arrancar(puerto)
    try:
        check("El servidor arranco", bool(esperar_pin(proceso)))

        # 1) Un celular entra con el QR y quita el codigo.
        clave = clave_del_panel(puerto)
        datos = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{puerto}/api/qr-login",
            data=json.dumps({"key": clave}).encode(),
            headers={"Content-Type": "application/json"}, method="POST"),
            timeout=5).read().decode())
        token = datos.get("token")
        check("El primer celular entra con el QR", bool(token))

        respuestas = asyncio.run(pedir(
            puerto,
            [({"a": "auth", "d": {"token": token}}, "auth")],
            "set_auth", {"required": False},
        ))
        check("Se acepta quitar el codigo",
              respuestas.get("required") is False, f"{respuestas}")

        # 2) Ahora un celular NUEVO entra sin nada.
        nuevo = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Un celular nuevo entra sin codigo",
              nuevo.get("t") == "ok" and nuevo.get("status") == "auth",
              f"{nuevo}")

        # 3) Y se puede volver a activar: se pide codigo de nuevo.
        respuesta = asyncio.run(pedir(
            puerto,
            [({"a": "auth", "d": {"token": token}}, "auth")],
            "set_auth", {"required": True},
        ))
        check("Se vuelve a activar el codigo",
              respuesta.get("required") is True, f"{respuesta}")

        sin_codigo = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Con el codigo activo, ya no entra sin PIN",
              sin_codigo.get("t") == "auth_fail", f"{sin_codigo}")

        # El token anterior sigue valiendo (no se expulsa a nadie).
        sigue = asyncio.run(conectar(puerto, {"a": "auth", "d": {"token": token}}))
        check("El token anterior sigue siendo valido", sigue.get("t") == "ok")
    finally:
        terminar(proceso)


# --------------------------------------------------------------------- C
def prueba_desactivar_desde_consola() -> None:
    print("\n== C) Desactivar con 'auth off' en la consola ==")
    puerto = 8812
    proceso = arrancar(puerto)
    try:
        check("El servidor arranco", bool(esperar_pin(proceso)))
        proceso.stdin.write("auth off\n")
        proceso.stdin.flush()

        salida = esperar_texto(proceso, "CONTROL DE ACCESO DESACTIVADO", 15)
        check("La consola confirma que esta desactivado",
              "CONTROL DE ACCESO DESACTIVADO" in salida,
              salida[-300:])

        nuevo = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Un celular entra sin codigo",
              nuevo.get("t") == "ok" and nuevo.get("status") == "auth", f"{nuevo}")

        # Y se puede volver a activar desde la consola.
        proceso.stdin.write("auth on\n")
        proceso.stdin.flush()
        esperar_texto(proceso, "ACTIVADO", 15)
        sin_codigo = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Tras 'auth on' vuelve a pedir codigo",
              sin_codigo.get("t") == "auth_fail", f"{sin_codigo}")
    finally:
        terminar(proceso)


# --------------------------------------------------------------------- D
def prueba_permisos() -> None:
    print("\n== D) Quitar el codigo exige estar autorizado ==")
    puerto = 8813
    proceso = arrancar(puerto)
    try:
        check("El servidor arranco", bool(esperar_pin(proceso)))
        # Sin autenticarse no se puede cambiar el modo.
        respuesta = asyncio.run(conectar(puerto, {"a": "set_auth", "d": {"required": False}}))
        check("Sin autenticarse no se cambia el modo",
              respuesta.get("t") == "auth_required", f"{respuesta}")

        # El endpoint local existe y responde a la propia PC.
        datos = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{puerto}/api/auth",
            data=json.dumps({"required": False}).encode(),
            headers={"Content-Type": "application/json"}, method="POST"),
            timeout=5).read().decode())
        check("El endpoint local desactiva el codigo", datos.get("required") is False,
              f"{datos}")

        nuevo = asyncio.run(conectar(puerto, {"a": "auth", "d": {"sinCodigo": True}}))
        check("Y a partir de ahi entra cualquiera sin codigo",
              nuevo.get("t") == "ok", f"{nuevo}")
    finally:
        terminar(proceso)


def main() -> int:
    print("Codigo de acceso desactivable")
    print("=" * 62)
    prueba_arranque_sin_codigo()
    prueba_desactivar_en_caliente()
    prueba_desactivar_desde_consola()
    prueba_permisos()
    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
