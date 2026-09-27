"""
Prueba de arrastre real: comprueba con las API de Windows que el boton
izquierdo queda realmente pulsado mientras se mueve (drag & drop).

Uso:
    python tools/test_drag.py --port 8768 --pin 123456
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

SERVER = str(Path(__file__).resolve().parent.parent / "server")
sys.path.insert(0, SERVER)

import native_input  # noqa: E402
from aiohttp import ClientSession  # noqa: E402


async def run(port: int, pin: str) -> int:
    failures = 0
    url = f"http://127.0.0.1:{port}"

    async with ClientSession() as session:
        async with session.ws_connect(f"{url}/ws") as ws:
            await ws.send_json({"a": "auth", "d": {"pin": pin}})
            hello = json.loads((await ws.receive()).data)
            if hello.get("t") != "ok":
                print("No se pudo autenticar:", hello)
                return 1

            async def settle(seconds: float = 0.30) -> None:
                await asyncio.sleep(seconds)

            async def driver_state() -> dict:
                """Pregunta al servidor que boton tiene presionado."""
                await ws.send_json({"a": "get_driver", "d": {}})
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 3.0
                while loop.time() < deadline:
                    try:
                        message = json.loads(
                            (await asyncio.wait_for(ws.receive(), deadline - loop.time())).data
                        )
                    except asyncio.TimeoutError:
                        return {}
                    if message.get("t") == "response" and message.get("a") == "get_driver":
                        return message.get("d") or {}
                return {}

            # Se coloca el puntero en el centro POR LA VIA DEL SERVIDOR, para
            # que tambien quede centrada su posicion interna: si estuviera
            # pegado a un borde, el desplazamiento se recortaria y la prueba
            # fallaria sin motivo (o si el celular esta moviendo el raton).
            ancho, alto = native_input.screen_size()
            await ws.send_json({"a": "mouse_move", "d": {"x": ancho // 2, "y": alto // 2}})
            await settle(0.4)

            start = native_input.cursor_position()
            print(f"Posicion inicial: {start}")

            # GetAsyncKeyState NO refleja los botones inyectados con SendInput,
            # asi que el estado se consulta al propio servidor.
            await ws.send_json({"a": "mouse_down", "d": {"button": "left"}})
            await settle(0.2)
            held = (await driver_state()).get("button_held")
            print(f"Tras mouse_down, boton que el servidor tiene presionado: {held}")
            if held != "left":
                failures += 1
                print("  [FALLO] el servidor no registro el boton pulsado")

            for _ in range(25):
                await ws.send_json({"a": "mouse_rel_move", "d": {"dx": 4.0, "dy": 2.0}})
                await asyncio.sleep(0.012)
            await settle(0.5)
            middle = native_input.cursor_position()
            travelled = abs(middle[0] - start[0]) + abs(middle[1] - start[1])
            still_held = (await driver_state()).get("button_held")
            print(f"Tras arrastrar: {middle} (recorrido {travelled} px), boton={still_held}")
            if travelled < 20:
                failures += 1
                print("  [FALLO] el puntero no se movio mientras arrastraba")
            if still_held != "left":
                failures += 1
                print("  [FALLO] el boton se solto durante el arrastre")

            await ws.send_json({"a": "mouse_up", "d": {"button": "left"}})
            await settle(0.25)
            released = (await driver_state()).get("button_held")
            print(f"Tras mouse_up, boton presionado: {released}")
            if released is not None:
                failures += 1
                print("  [FALLO] el boton siguio pulsado")

            # --- limpieza por desconexion ----------------------------------
            await ws.send_json({"a": "mouse_down", "d": {"button": "left"}})
            await settle(0.2)
            print(f"Boton pulsado antes de desconectar: {(await driver_state()).get('button_held')}")

        # La conexion se ha cerrado: el servidor debe soltar todo solo.
        await asyncio.sleep(0.6)
        after_close = native_input.cursor_position()
        print(f"Servidor sigue vivo tras la desconexion: {after_close is not None}")

    print("\n" + "=" * 58)
    print("  Arrastre OK" if not failures else f"  {failures} fallo(s) en el arrastre")
    print("=" * 58)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pin", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.port, args.pin))


if __name__ == "__main__":
    sys.exit(main())
