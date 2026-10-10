"""
Pruebas de la gestion de dispositivos, con un servidor de verdad.

  A) Con --confirmar, un dispositivo nuevo espera permiso: "no" lo rechaza
     y "si" lo deja entrar. Un acceso ya guardado no vuelve a preguntar.
  B) Los demas dispositivos reciben el aviso de que ha entrado uno nuevo.
  C) La lista de dispositivos marca el propio y los conectados.
  D) Revocar un dispositivo lo desconecta y su token deja de valer.
  E) Con el codigo quitado, reconectar no crea accesos nuevos.
  F) La consola: "dispositivos" lista y "revocar" retira.

Las ventanas de confirmacion se desactivan (REMOTEPAD_SIN_VENTANAS) y se
responde por la consola.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import aiohttp

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


class Servidor:
    """Servidor de pruebas con la salida leida en segundo plano."""

    def __init__(self, puerto: int, extra: list[str] | None = None) -> None:
        self.puerto = puerto
        carpeta = Path(tempfile.mkdtemp(prefix="remotepad_disp_"))
        self.tokens = carpeta / "tokens.json"
        entorno = dict(os.environ)
        entorno.update({
            "REMOTEPAD_TOKENS": str(self.tokens),
            "REMOTEPAD_PROFILES": str(carpeta / "profiles.json"),
            "REMOTEPAD_LEARNING": str(carpeta / "learning.json"),
            "REMOTEPAD_CONFIG": str(carpeta / "config.json"),
            "REMOTEPAD_SIN_VENTANAS": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        self.proceso = subprocess.Popen(
            [sys.executable, "-u", "app.py", "--port", str(puerto), "--no-browser"]
            + (extra or []),
            cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            env=entorno,
        )
        self.lineas: list[str] = []
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self) -> None:
        for linea in self.proceso.stdout:
            self.lineas.append(linea)

    def esperar(self, patron: str, segundos: float = 20.0, desde: int = 0) -> str:
        limite = time.time() + segundos
        while time.time() < limite:
            for linea in self.lineas[desde:]:
                if re.search(patron, linea):
                    return linea
            time.sleep(0.05)
        return ""

    def pin(self) -> str:
        linea = self.esperar(r"PIN DE ACCESO\s*->")
        encontrado = re.search(r"(\d{3})\s*(\d{3})", linea)
        return encontrado.group(1) + encontrado.group(2) if encontrado else ""

    def escribir(self, texto: str) -> None:
        self.proceso.stdin.write(texto + "\n")
        self.proceso.stdin.flush()

    def parar(self) -> None:
        try:
            self.escribir("q")
            self.proceso.wait(timeout=10)
        except Exception:
            self.proceso.kill()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}/ws"


async def recibir(ws, tipo: str, limite: float = 8.0) -> dict:
    """Siguiente mensaje de ese tipo (o de respuesta a esa accion)."""
    fin = asyncio.get_running_loop().time() + limite
    while True:
        resto = fin - asyncio.get_running_loop().time()
        if resto <= 0:
            return {}
        try:
            mensaje = await ws.receive(timeout=resto)
        except asyncio.TimeoutError:
            return {}
        if mensaje.type != aiohttp.WSMsgType.TEXT:
            return {"cerrado": True}
        datos = json.loads(mensaje.data)
        if datos.get("t") == tipo or (datos.get("t") == "response" and datos.get("a") == tipo):
            return datos


async def entrar_con_pin(sesion, servidor: Servidor, pin: str, responder: str | None):
    ws = await sesion.ws_connect(servidor.url)
    marca = len(servidor.lineas)
    await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
    if responder is not None:
        check("La consola pregunta por el dispositivo nuevo",
              bool(servidor.esperar(r"quiere manejar esta PC", 10, marca)))
        servidor.escribir(responder)
    respuesta = await recibir(ws, "ok") if responder != "no" else await recibir(ws, "auth_fail")
    return ws, respuesta


async def prueba_confirmacion(servidor: Servidor) -> None:
    pin = servidor.pin()
    check("El servidor arranco", bool(pin))
    async with aiohttp.ClientSession() as sesion:
        print("\n== A) Confirmacion en la PC ==")
        ws, rechazo = await entrar_con_pin(sesion, servidor, pin, "no")
        check("Con 'no' se rechaza", rechazo.get("t") == "auth_fail", str(rechazo))
        check("Y no se crea ningun acceso",
              not servidor.tokens.exists() or "dispositivos\": {}" in servidor.tokens.read_text())
        await ws.close()

        ws1, ok = await entrar_con_pin(sesion, servidor, pin, "si")
        check("Con 'si' entra", ok.get("status") == "auth", str(ok))
        token1 = ok.get("token", "")
        check("Y recibe su token", bool(token1))

        # Un acceso guardado no pregunta otra vez.
        ws_otra = await sesion.ws_connect(servidor.url)
        marca = len(servidor.lineas)
        await ws_otra.send_str(json.dumps({"a": "auth", "d": {"token": token1}}))
        vuelta = await recibir(ws_otra, "ok")
        check("Con el token guardado entra sin preguntar",
              vuelta.get("status") == "auth"
              and not servidor.esperar(r"quiere manejar", 0.5, marca))
        await ws_otra.close()

        print("\n== B) Aviso a los demas ==")
        ws2, ok2 = await entrar_con_pin(sesion, servidor, pin, "si")
        aviso = await recibir(ws1, "device_new")
        check("El primer dispositivo recibe el aviso", bool(aviso), str(aviso))

        print("\n== C) Lista de dispositivos ==")
        await ws1.send_str(json.dumps({"a": "devices_list", "d": {}}))
        lista = (await recibir(ws1, "devices_list")).get("d", {})
        filas = lista.get("dispositivos", [])
        check("Hay dos dispositivos", len(filas) == 2, str(filas))
        check("Uno esta marcado como el propio", sum(f.get("actual") for f in filas) == 1)
        check("Los dos aparecen conectados", all(f.get("conectado") for f in filas))
        check("La lista no expone huellas completas",
              all(len(f.get("id", "")) == 8 and "huella" not in f for f in filas))
        check("Indica si se pide confirmacion", lista.get("confirmar") is True)

        print("\n== D) Revocar ==")
        otro = next(f for f in filas if not f.get("actual"))
        await ws1.send_str(json.dumps({"a": "device_revoke", "d": {"id": otro["id"]}}))
        confirmado = (await recibir(ws1, "device_revoke")).get("d", {})
        check("La revocacion se confirma con el nombre",
              confirmado.get("ok") and confirmado.get("nombre"), str(confirmado))
        check("Y devuelve la lista actualizada",
              len(confirmado.get("dispositivos", [])) == 1)
        revocado = await recibir(ws2, "revoked")
        check("El dispositivo revocado recibe el aviso", bool(revocado))
        cierre = await recibir(ws2, "nada", 4)
        check("Y se le desconecta", cierre.get("cerrado") is True, str(cierre))
        ws3 = await sesion.ws_connect(servidor.url)
        await ws3.send_str(json.dumps({"a": "auth", "d": {"token": ok2.get("token")}}))
        check("Su token ya no vale",
              (await recibir(ws3, "auth_fail")).get("t") == "auth_fail")
        await ws3.close()
        check("Un id inexistente da error",
              await _revocar_inexistente(ws1))

        print("\n== F) Consola ==")
        marca = len(servidor.lineas)
        servidor.escribir("dispositivos")
        check("'dispositivos' lista el que queda",
              bool(servidor.esperar(r"\(conectado\)", 5, marca)))
        propio = next(f for f in filas if f.get("actual"))
        servidor.escribir(f"revocar {propio['id']}")
        check("'revocar' lo retira", bool(servidor.esperar(r"Acceso retirado", 5, marca)))
        await ws1.close()


async def _revocar_inexistente(ws) -> bool:
    await ws.send_str(json.dumps({"a": "device_revoke", "d": {"id": "zzzzzzzz"}}))
    respuesta = (await recibir(ws, "device_revoke")).get("d", {})
    return "error" in respuesta


async def prueba_sin_codigo(servidor: Servidor) -> None:
    print("\n== E) Codigo quitado: reconectar no crea accesos ==")
    servidor.esperar(r"en marcha")
    async with aiohttp.ClientSession() as sesion:
        ws = await sesion.ws_connect(servidor.url)
        await ws.send_str(json.dumps({"a": "auth", "d": {}}))
        ok = await recibir(ws, "ok")
        token = ok.get("token", "")
        check("Entra sin codigo y recibe token", bool(token))
        await ws.close()
        for _ in range(3):
            ws = await sesion.ws_connect(servidor.url)
            await ws.send_str(json.dumps({"a": "auth", "d": {"token": token}}))
            vuelta = await recibir(ws, "ok")
            await ws.close()
        check("Al reconectar no recibe otro token", "token" not in vuelta, str(vuelta))
        datos = json.loads(servidor.tokens.read_text(encoding="utf-8"))
        check("Sigue habiendo un solo acceso", len(datos["dispositivos"]) == 1,
              f"hay {len(datos['dispositivos'])}")


def main() -> int:
    print("Gestion de dispositivos")
    servidor = Servidor(8797, ["--confirmar"])
    try:
        asyncio.run(prueba_confirmacion(servidor))
    finally:
        servidor.parar()

    servidor = Servidor(8798, ["--no-auth"])
    try:
        asyncio.run(prueba_sin_codigo(servidor))
    finally:
        servidor.parar()

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
