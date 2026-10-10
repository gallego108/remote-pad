"""
Pruebas de seguridad del acceso.

  A) La pantalla de acceso NO recibe el PIN (auth_query).
  B) El modo espectador solo se acepta desde la propia PC.
  C) Un WebSocket abierto desde otra pagina web (Origin ajeno) se rechaza.
  D) El registro no escribe el PIN vigente al fallar un intento.
  E) Tras 8 fallos, ni siquiera el PIN correcto entra (fuerza bruta).

Arranca su propio servidor, con archivos de estado temporales.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"
PUERTO = 8796

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def entorno_aislado() -> dict:
    """Las pruebas no tocan los accesos ni los perfiles reales."""
    carpeta = Path(tempfile.mkdtemp(prefix="remotepad_seg_"))
    entorno = dict(os.environ)
    entorno["REMOTEPAD_TOKENS"] = str(carpeta / "tokens.json")
    entorno["REMOTEPAD_PROFILES"] = str(carpeta / "profiles.json")
    entorno["REMOTEPAD_LEARNING"] = str(carpeta / "learning.json")
    entorno["REMOTEPAD_CONFIG"] = str(carpeta / "config.json")
    entorno["PYTHONIOENCODING"] = "utf-8"
    return entorno


def arrancar(puerto: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-u", "app.py", "--port", str(puerto), "--no-browser"],
        cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env=entorno_aislado(),
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


def terminar(proceso: subprocess.Popen) -> str:
    """Detiene el servidor y devuelve lo que quedaba en su salida."""
    try:
        proceso.stdin.write("q\n")
        proceso.stdin.flush()
    except Exception:
        pass
    try:
        salida, _ = proceso.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
        salida, _ = proceso.communicate()
    return salida or ""


def ip_de_red() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except Exception:
        return ""


async def primer_mensaje(host: str, mensaje: dict, headers: dict | None = None) -> dict:
    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://{host}:{PUERTO}/ws",
                                     headers=headers or {}) as ws:
            await ws.send_str(json.dumps(mensaje))
            respuesta = await ws.receive(timeout=5)
            return json.loads(respuesta.data)


async def abrir_con_origen(origen: str | None) -> int:
    """Devuelve 101 si el WebSocket se abrio, o el codigo HTTP del rechazo."""
    headers = {"Origin": origen} if origen else {}
    async with aiohttp.ClientSession() as sesion:
        try:
            async with sesion.ws_connect(f"http://127.0.0.1:{PUERTO}/ws",
                                         headers=headers):
                return 101
        except aiohttp.WSServerHandshakeError as exc:
            return exc.status


async def intentos(pin_malo: str, pin_bueno: str) -> dict:
    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://127.0.0.1:{PUERTO}/ws") as ws:
            for _ in range(8):
                await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin_malo}}))
                await ws.receive(timeout=5)
            await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin_bueno}}))
            return json.loads((await ws.receive(timeout=5)).data)


def main() -> int:
    print("Pruebas de seguridad del acceso")
    proceso = arrancar(PUERTO)
    salida = ""
    try:
        pin = esperar_pin(proceso)
        check("El servidor arranco", bool(pin))
        if not pin:
            return 1
        pin_malo = "000000" if pin != "000000" else "111111"

        print("\n== A) La pantalla de acceso no recibe el PIN ==")
        estado = asyncio.run(primer_mensaje("127.0.0.1", {"a": "auth_query", "d": {}}))
        check("auth_query responde con el estado", estado.get("t") == "auth_state")
        check("auth_query NO incluye el PIN", "pin" not in estado and pin not in json.dumps(estado))

        print("\n== B) Modo espectador solo desde la PC ==")
        local = asyncio.run(primer_mensaje("127.0.0.1", {"a": "viewer", "d": {}}))
        check("Desde la PC se acepta", local.get("status") == "viewer")
        ip = ip_de_red()
        if ip and not ip.startswith("127."):
            remoto = asyncio.run(primer_mensaje(ip, {"a": "viewer", "d": {}}))
            check("Desde la red se rechaza", remoto.get("t") == "denied", str(remoto))
            check("Desde la red no llega el PIN", pin not in json.dumps(remoto))
        else:
            print("  (sin IP de red: se omite la prueba desde otro equipo)")

        print("\n== C) Origen del WebSocket ==")
        check("Sin Origin (no es un navegador) se acepta",
              asyncio.run(abrir_con_origen(None)) == 101)
        check("Origin de la propia app se acepta",
              asyncio.run(abrir_con_origen(f"http://127.0.0.1:{PUERTO}")) == 101)
        check("Origin de otra pagina se rechaza (403)",
              asyncio.run(abrir_con_origen("http://pagina-ajena.example")) == 403)
        check("Origin con otro puerto se rechaza",
              asyncio.run(abrir_con_origen("http://127.0.0.1:1")) == 403)

        print("\n== E) Fuerza bruta ==")
        tras_fallos = asyncio.run(intentos(pin_malo, pin))
        check("Tras 8 fallos el PIN correcto no entra",
              tras_fallos.get("t") == "auth_fail", str(tras_fallos))
    finally:
        salida = terminar(proceso)

    print("\n== D) El registro no muestra el PIN al fallar ==")
    lineas = [l for l in salida.splitlines() if "PIN incorrecto" in l]
    check("Se registraron los intentos fallidos", bool(lineas))
    check("Ninguna linea de fallo contiene el PIN",
          all(pin not in linea for linea in lineas))

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
