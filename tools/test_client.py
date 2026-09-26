"""
Prueba de extremo a extremo: simula el celular hablando con el servidor.

Se conecta al WebSocket, se autentica con el PIN real, y envia una bateria de
ordenes comprobando que el servidor responde correctamente.

Uso:
    python tools/test_client.py --port 8765 --pin 123456 --cursor
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from aiohttp import ClientSession  # noqa: E402

PASS = "OK  "
FAIL = "FALLO"


class Checker:
    def __init__(self) -> None:
        self.ok = 0
        self.failed = 0

    def report(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.ok += 1
            print(f"  [{PASS}] {name}")
        else:
            self.failed += 1
            print(f"  [{FAIL}] {name} {detail}")


async def run(port: int, pin: str, move_cursor: bool) -> int:
    checks = Checker()
    url = f"http://127.0.0.1:{port}"

    async with ClientSession() as session:
        # ---------------------------------------------------- HTTP estatico
        print("\n== Servidor HTTP ==")
        async with session.get(f"{url}/") as response:
            body = await response.text()
            checks.report("GET / devuelve la app", response.status == 200 and "RemotePad" in body)

        for name in ("app.js", "styles.css", "manifest.webmanifest", "icon-192.png", "sw.js"):
            async with session.get(f"{url}/{name}") as response:
                checks.report(f"GET /{name}", response.status == 200)

        async with session.get(f"{url}/../server/app.py") as response:
            checks.report("Bloquea salir del directorio web", response.status in (400, 403, 404))

        # ------------------------------------------------------- WebSocket
        print("\n== Autenticacion ==")
        async with session.ws_connect(f"{url}/ws") as ws:
            await ws.send_json({"a": "auth", "d": {"pin": "000000"}})
            message = json.loads((await ws.receive()).data)
            checks.report("Rechaza un PIN incorrecto", message.get("t") == "auth_fail",
                          f"-> {message}")

            await ws.send_json({"a": "auth", "d": {"pin": pin}})
            message = json.loads((await ws.receive()).data)
            checks.report("Acepta el PIN correcto", message.get("t") == "ok", f"-> {message}")
            token = message.get("token")
            checks.report("Entrega un token al dispositivo", bool(token))
            checks.report("Informa la resolucion de pantalla",
                          isinstance(message.get("screen"), list), f"-> {message.get('screen')}")

            # ------------------------------------------------- ordenes
            print("\n== Control del puntero ==")

            before = None
            if move_cursor:
                import native_input
                before = native_input.cursor_position()

            for _ in range(20):
                await ws.send_json({"a": "mouse_rel_move", "d": {"dx": 1.0, "dy": 0.6}})
            await asyncio.sleep(0.45)

            if move_cursor:
                import native_input
                after = native_input.cursor_position()
                moved = abs(after[0] - before[0]) + abs(after[1] - before[1])
                checks.report("mouse_rel_move desplaza el puntero del sistema",
                              moved > 5, f"-> antes {before}, despues {after}")

            await ws.send_json({"a": "ping", "d": {"ts": 12345}})
            message = json.loads((await ws.receive()).data)
            checks.report("Responde al ping (latencia)", message.get("t") == "pong")

            async def expect_response(action: str, payload: dict, timeout: float = 3.0) -> dict:
                """Envia una orden y espera su confirmacion (ignora 'pong'/'pin')."""
                await ws.send_json({"a": action, "d": payload})
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout
                while loop.time() < deadline:
                    try:
                        message = json.loads(
                            (await asyncio.wait_for(ws.receive(), deadline - loop.time())).data
                        )
                    except asyncio.TimeoutError:
                        return {}
                    if message.get("t") == "response" and message.get("a") == action:
                        return message.get("d") or {}
                return {}

            print("\n== Clics y botones ==")
            result = await expect_response("mouse_click", {"button": "left", "clicks": 1})
            checks.report("Clic izquierdo", "error" not in result, f"-> {result}")

            result = await expect_response("mouse_click", {"button": "right", "clicks": 1})
            checks.report("Clic derecho", "error" not in result)

            result = await expect_response("mouse_click", {"button": "left", "clicks": 2})
            checks.report("Doble clic", "error" not in result)

            await ws.send_json({"a": "mouse_down", "d": {"button": "left"}})
            await asyncio.sleep(0.05)
            for _ in range(6):
                await ws.send_json({"a": "mouse_rel_move", "d": {"dx": 4.0, "dy": 0.5}})
            await ws.send_json({"a": "mouse_up", "d": {"button": "left"}})
            await asyncio.sleep(0.35)
            checks.report("Arrastrar y soltar (down + move + up) sin errores", True)

            result = await expect_response("mouse_release_all", {})
            checks.report("mouse_release_all", "error" not in result)

            print("\n== Scroll ==")
            for _ in range(3):
                await ws.send_json({"a": "mouse_scroll", "d": {"dx": 0.0, "dy": -2.0}})
            await asyncio.sleep(0.3)
            checks.report("Scroll vertical", True)

            print("\n== Teclado ==")
            result = await expect_response("key_type", {"text": "remotepad prueba"})
            checks.report("Escribe texto (acentos y simbolos)", result.get("ok") is True,
                          f"-> {result}")

            result = await expect_response("key", {"key": "left", "mods": []})
            checks.report("Tecla especial (flecha)", result.get("ok") is True, f"-> {result}")

            result = await expect_response("key", {"key": "c", "mods": ["ctrl"]})
            checks.report("Atajo Ctrl+C", result.get("ok") is True, f"-> {result}")

            result = await expect_response("key", {"key": "desconocida_larga", "mods": []})
            checks.report("Rechaza teclas invalidas sin romperse", result.get("ok") is False,
                          f"-> {result}")

            print("\n== Multimedia y presentaciones ==")
            for name in ("play_pause", "next", "prev", "mute"):
                result = await expect_response("media", {"action": name})
                checks.report(f"Tecla multimedia: {name}", result.get("ok") is True, f"-> {result}")

            result = await expect_response("media_volume", {"steps": 2})
            checks.report("Volumen +2", result.get("ok") is True)
            result = await expect_response("presentation", {"action": "next"})
            checks.report("Presentacion: siguiente", result.get("ok") is True, f"-> {result}")

            print("\n== Robustez ==")
            result = await expect_response("accion_inventada", {})
            checks.report("Accion desconocida devuelve error controlado",
                          "error" in result, f"-> {result}")

            result = await expect_response("mouse_rel_move", {"dx": "no-soy-un-numero", "dy": None})
            checks.report("Datos invalidos no tumban el servidor", True)

            result = await expect_response("key_type", {"text": "x" * 5000})
            checks.report("Rechaza texto desmesurado", "error" in result, f"-> {result}")

            await ws.send_str("{esto no es json}")
            await ws.send_str("[]")
            await asyncio.sleep(0.1)
            result = await expect_response("ping", {"ts": 1})
            checks.report("Sigue vivo tras mensajes corruptos", True)

        # ------------------------------------------------- token reutilizable
        print("\n== Reconexion con token ==")
        async with session.ws_connect(f"{url}/ws") as ws2:
            await ws2.send_json({"a": "auth", "d": {"token": token}})
            message = json.loads((await ws2.receive()).data)
            checks.report("El mismo celular reconecta sin PIN",
                          message.get("t") == "ok" and message.get("status") == "auth",
                          f"-> {message}")

        async with session.ws_connect(f"{url}/ws") as ws3:
            await ws3.send_json({"a": "auth", "d": {"token": "token-falso"}})
            message = json.loads((await ws3.receive()).data)
            checks.report("Rechaza un token inventado", message.get("t") != "ok", f"-> {message}")

    print("\n" + "=" * 58)
    print(f"  Resultado: {checks.ok} correctas, {checks.failed} fallidas")
    print("=" * 58)
    return 1 if checks.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pin", required=True)
    parser.add_argument("--cursor", action="store_true",
                        help="mueve el puntero real del sistema (prueba completa)")
    args = parser.parse_args()
    return asyncio.run(run(args.port, args.pin, args.cursor))


if __name__ == "__main__":
    sys.exit(main())
