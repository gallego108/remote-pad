"""
Pruebas del modo mando (teclas mantenidas: key_down / key_up).

  A) El controlador mantiene la tecla, no la repite y la suelta; tiene un
     limite de teclas a la vez y release_all lo suelta todo (capa nativa
     simulada: no pulsa nada en la PC).
  B) Protocolo con la tecla Mayus (inofensiva sola):
     - se mantiene y se suelta;
     - 30 toques muy rapidos no dejan ninguna tecla pegada (orden garantizado);
     - si el celular se desconecta con la tecla pulsada, la PC la suelta;
     - una tecla no valida se rechaza.

Uso:
    python tools/test_mando.py                      # A
    python tools/test_mando.py --port 8791 --pin 123456
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import controller as modulo_controlador  # noqa: E402
import native_input  # noqa: E402

failures = 0
checks = 0
VK_SHIFT = 0x10


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def prueba_controlador() -> None:
    print("\n== A) Controlador (capa nativa simulada) ==")
    registro: list[tuple[str, int]] = []
    originales = {n: getattr(native_input, n) for n in ("press_key", "release_key", "button_up")}
    native_input.press_key = lambda vk, extended=None: registro.append(("down", vk)) or True
    native_input.release_key = lambda vk, extended=None: registro.append(("up", vk)) or True
    native_input.button_up = lambda button="left": True
    try:
        c = modulo_controlador.DesktopController()
        check("key_down de una tecla conocida", c.key_down("w"))
        check("Repetirlo no envia otra pulsacion",
              c.key_down("w") and registro.count(("down", ord("W"))) == 1)
        check("La tecla consta como mantenida", c.held_keys == [ord("W")])
        check("key_up la suelta", c.key_up("w") and ("up", ord("W")) in registro)
        check("Y ya no consta", c.held_keys == [])
        check("Una tecla desconocida se rechaza", c.key_down("tecla-inventada") is False)

        for tecla in "abcdefghij":
            c.key_down(tecla)
        check(f"Como mucho {modulo_controlador.MAX_HELD_KEYS} a la vez",
              len(c.held_keys) == modulo_controlador.MAX_HELD_KEYS, str(len(c.held_keys)))
        retenidas = list(c.held_keys)
        registro.clear()
        c.release_all()
        check("release_all las suelta todas",
              all(("up", vk) in registro for vk in retenidas) and c.held_keys == [])
    finally:
        for nombre, funcion in originales.items():
            setattr(native_input, nombre, funcion)


async def prueba_protocolo(puerto: int, pin: str) -> None:
    import aiohttp

    print("\n== B) Protocolo (tecla Mayus) ==")
    url = f"http://127.0.0.1:{puerto}/ws"

    async def entrar(sesion):
        ws = await sesion.ws_connect(url)
        await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
        respuesta = json.loads((await ws.receive(timeout=5)).data)
        return ws, respuesta.get("token")

    async def mantenidas(ws) -> list:
        # Un instante para que el bucle del servidor procese la cola.
        await asyncio.sleep(0.25)
        await ws.send_str(json.dumps({"a": "get_driver", "d": {}}))
        while True:
            mensaje = json.loads((await ws.receive(timeout=5)).data)
            if mensaje.get("t") == "response" and mensaje.get("a") == "get_driver":
                return mensaje["d"].get("keys_held", [])

    async def respuesta_a(ws, accion: str) -> dict:
        while True:
            mensaje = json.loads((await ws.receive(timeout=5)).data)
            if mensaje.get("t") == "response" and mensaje.get("a") == accion:
                return mensaje.get("d", {})

    async with aiohttp.ClientSession() as sesion:
        ws, token = await entrar(sesion)
        check("Entra con el PIN", bool(token))
        await ws.send_str(json.dumps({"a": "key_down", "d": {"key": "shift"}}))
        check("key_down mantiene Mayus", VK_SHIFT in await mantenidas(ws))
        await ws.send_str(json.dumps({"a": "key_up", "d": {"key": "shift"}}))
        check("key_up la suelta", VK_SHIFT not in await mantenidas(ws))

        for _ in range(30):
            await ws.send_str(json.dumps({"a": "key_down", "d": {"key": "shift"}}))
            await ws.send_str(json.dumps({"a": "key_up", "d": {"key": "shift"}}))
        check("30 toques rapidos no dejan la tecla pegada",
              VK_SHIFT not in await mantenidas(ws))

        await ws.send_str(json.dumps({"a": "key_down", "d": {"key": "rm -rf"}}))
        check("Una tecla no valida se rechaza",
              "error" in await respuesta_a(ws, "key_down"))

        await ws.send_str(json.dumps({"a": "key_down", "d": {"key": "shift"}}))
        check("Mayus pulsada antes de desconectar", VK_SHIFT in await mantenidas(ws))
        await ws.close()
        await asyncio.sleep(0.5)

        ws2 = await sesion.ws_connect(url)
        await ws2.send_str(json.dumps({"a": "auth", "d": {"token": token}}))
        await ws2.receive(timeout=5)
        check("Al desconectarse, la PC la ha soltado", VK_SHIFT not in await mantenidas(ws2))
        await ws2.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--pin")
    args = parser.parse_args()
    print("Modo mando")
    prueba_controlador()
    if args.port and args.pin:
        asyncio.run(prueba_protocolo(args.port, args.pin))
    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
