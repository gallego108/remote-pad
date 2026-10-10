"""
Pruebas de varios monitores.

  A) Limite del puntero con distribuciones simuladas: dos monitores en
     paralelo, uno a la izquierda (coordenadas negativas) y alturas distintas.
  B) El controlador cruza de un monitor a otro y centra el puntero en el
     elegido (con una capa nativa simulada: no toca el raton).
  C) Lectura real de los monitores de esta PC.
  D) Protocolo: monitor_list y monitor_goto (con --cursor mueve el puntero de
     verdad y lo devuelve a su sitio).

Uso:
    python tools/test_monitores.py                      # A, B y C
    python tools/test_monitores.py --port 8791 --pin 123456 [--cursor]
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


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


UNO = [(0, 0, 1920, 1080)]
PARALELO = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
IZQUIERDA_BAJO = [(0, 0, 1920, 1080), (-1280, 0, 1280, 1024)]


def prueba_limites() -> None:
    print("\n== A) Limite del puntero ==")
    clamp = native_input.clamp_to_rects
    check("Un monitor: se queda dentro", clamp(5000, -50, UNO) == (1919, 0))
    check("Dos en paralelo: el segundo monitor es alcanzable",
          clamp(2500, 500, PARALELO) == (2500, 500),
          "antes se cortaba en x=1919 (solo el principal)")
    check("Dos en paralelo: el borde derecho es el del segundo",
          clamp(9999, 500, PARALELO) == (3839, 500))
    check("Monitor a la izquierda: coordenadas negativas validas",
          clamp(-100, 500, IZQUIERDA_BAJO) == (-100, 500))
    check("Hueco bajo el monitor mas bajo: se pega a su borde",
          clamp(-100, 1050, IZQUIERDA_BAJO) == (-100, 1023),
          str(clamp(-100, 1050, IZQUIERDA_BAJO)))
    check("Sin monitores: no falla", clamp(10.4, 20.6, []) == (10, 21))


class NativaFalsa:
    """Sustituye a native_input dentro del controlador: dos monitores."""

    def __init__(self, monitores: list[dict]) -> None:
        self.monitores = monitores
        self.posicion = (100, 100)

    def instalar(self) -> dict:
        originales = {}
        for nombre in ("monitors", "cursor_position", "move_absolute", "screen_size"):
            originales[nombre] = getattr(native_input, nombre)
        native_input.monitors = lambda: [dict(m) for m in self.monitores]
        native_input.cursor_position = lambda: self.posicion
        native_input.screen_size = lambda: (1920, 1080)

        def mover(x, y, rects=None):
            self.posicion = native_input.clamp_to_rects(
                x, y, rects or [(m["x"], m["y"], m["w"], m["h"]) for m in self.monitores])
            return True

        native_input.move_absolute = mover
        return originales

    @staticmethod
    def restaurar(originales: dict) -> None:
        for nombre, funcion in originales.items():
            setattr(native_input, nombre, funcion)


def prueba_controlador() -> None:
    print("\n== B) Controlador con dos monitores (simulados) ==")
    falsa = NativaFalsa([
        {"x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True},
        {"x": 1920, "y": 0, "w": 2560, "h": 1440, "primary": False},
    ])
    originales = falsa.instalar()
    try:
        c = modulo_controlador.DesktopController()
        c.mouse_move(1900, 0)          # de x=100 a x=2000: cruza al segundo
        check("El puntero cruza al segundo monitor",
              c.virtual_position == (2000, 100), str(c.virtual_position))
        c.mouse_move(10_000, 0)
        check("Y se detiene en su borde derecho",
              c.virtual_position == (4479, 100), str(c.virtual_position))
        c.mouse_move(0, 2000)
        check("Abajo se detiene en el borde del monitor alto (1440)",
              c.virtual_position == (4479, 1439), str(c.virtual_position))
        elegido = c.move_to_monitor(1)
        check("move_to_monitor(1) lo centra en el segundo",
              elegido is not None and c.virtual_position == (1920 + 1280, 720),
              str(c.virtual_position))
        c.move_to_monitor(0)
        check("move_to_monitor(0) vuelve al principal",
              c.virtual_position == (960, 540), str(c.virtual_position))
        check("Una pantalla que no existe devuelve None", c.move_to_monitor(5) is None)
        check("monitors lista los dos", len(c.monitors) == 2)
    finally:
        NativaFalsa.restaurar(originales)


def prueba_real() -> None:
    print("\n== C) Monitores de esta PC ==")
    lista = native_input.monitors()
    check("Hay al menos un monitor", len(lista) >= 1, str(lista))
    check("Exactamente uno es el principal", sum(m["primary"] for m in lista) == 1)
    check("El principal va primero", lista and lista[0]["primary"])
    if native_input.available():
        izquierda, arriba, ancho, alto = native_input.virtual_screen()
        check("Todos caben en el escritorio virtual",
              all(m["x"] >= izquierda and m["y"] >= arriba
                  and m["x"] + m["w"] <= izquierda + ancho
                  and m["y"] + m["h"] <= arriba + alto for m in lista))
    print(f"  ({len(lista)} monitor(es): "
          + ", ".join(f"{m['w']}x{m['h']} en ({m['x']},{m['y']})" for m in lista) + ")")


async def prueba_protocolo(puerto: int, pin: str, cursor: bool) -> None:
    import aiohttp

    print("\n== D) Protocolo ==")

    async def pedir(ws, accion: str, datos: dict) -> dict:
        await ws.send_str(json.dumps({"a": accion, "d": datos}))
        while True:
            mensaje = json.loads((await ws.receive(timeout=5)).data)
            if mensaje.get("t") == "response" and mensaje.get("a") == accion:
                return mensaje.get("d", {})

    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://127.0.0.1:{puerto}/ws") as ws:
            await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
            entrada = json.loads((await ws.receive(timeout=5)).data)
            check("Entra con el PIN", entrada.get("status") == "auth")
            lista = await pedir(ws, "monitor_list", {})
            check("monitor_list devuelve los monitores",
                  isinstance(lista.get("monitores"), list) and lista["monitores"])
            check("E indica en cual esta el puntero",
                  isinstance(lista.get("actual"), int))
            check("Una pantalla que no existe da error",
                  "error" in await pedir(ws, "monitor_goto", {"index": 31}))
            if cursor:
                antes = native_input.cursor_position()
                ida = await pedir(ws, "monitor_goto", {"index": 0})
                monitor = lista["monitores"][0]
                centro = (monitor["x"] + monitor["w"] // 2, monitor["y"] + monitor["h"] // 2)
                check("monitor_goto 0 centra el puntero de verdad",
                      ida.get("ok") and native_input.cursor_position() == centro,
                      f"{native_input.cursor_position()} != {centro}")
                if antes:
                    native_input.set_cursor_position(*antes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--pin")
    parser.add_argument("--cursor", action="store_true")
    args = parser.parse_args()

    print("Varios monitores")
    prueba_limites()
    prueba_controlador()
    prueba_real()
    if args.port and args.pin:
        asyncio.run(prueba_protocolo(args.port, args.pin, args.cursor))
    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
