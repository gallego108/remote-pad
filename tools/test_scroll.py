"""
Pruebas del scroll (rueda del raton) del controlador.

Usa una capa nativa simulada: no mueve la rueda de verdad.

  A) Scroll clasico: solo clicks enteros, y el resto se conserva.
  B) Scroll suave: fracciones de click (alta resolucion), sin perder nada.
  C) Los signos se invierten igual en los dos modos.

Uso:
    python tools/test_scroll.py
"""

from __future__ import annotations

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


class RuedaFalsa:
    """Sustituye las llamadas de rueda de native_input y apunta lo enviado."""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []
        self.deltas: list[tuple[int, int]] = []

    def instalar(self) -> None:
        native_input.scroll = lambda v, h=0: self.clicks.append((v, h)) or True
        native_input.scroll_delta = lambda v, h=0: self.deltas.append((v, h)) or True
        native_input.monitors = lambda: [
            {"left": 0, "top": 0, "right": 1920, "bottom": 1080}]
        native_input.cursor_position = lambda: (100, 100)
        native_input.screen_size = lambda: (1920, 1080)

    def total_delta(self) -> tuple[int, int]:
        return (sum(d[0] for d in self.deltas), sum(d[1] for d in self.deltas))


def main() -> int:
    print("Scroll del controlador")
    print("=" * 64)
    unidades = modulo_controlador.UNITS_PER_SCROLL_CLICK
    rueda = RuedaFalsa()
    rueda.instalar()

    print("\n== A) Clicks enteros ==")
    c = modulo_controlador.DesktopController()
    c.mouse_scroll(0, unidades * 0.5)
    check("Medio click no se envia", rueda.clicks == [])
    c.mouse_scroll(0, unidades * 0.6)
    check("Al completar uno, sale un click", rueda.clicks == [(-1, 0)],
          str(rueda.clicks))
    check("No usa la rueda fina", rueda.deltas == [])

    print("\n== B) Scroll suave ==")
    rueda = RuedaFalsa()
    rueda.instalar()
    c = modulo_controlador.DesktopController()
    c.mouse_scroll(0, unidades * 0.25, suave=True)
    check("Un cuarto de click ya mueve algo", rueda.deltas != [], str(rueda.deltas))
    check("Y es una fraccion de click",
          bool(rueda.deltas) and 0 < abs(rueda.deltas[0][0]) < native_input.WHEEL_DELTA,
          str(rueda.deltas))
    for _ in range(200):                     # muchos pasos diminutos
        c.mouse_scroll(0, 0.37, suave=True)
    esperado = round((unidades * 0.25 + 200 * 0.37)
                     * native_input.WHEEL_DELTA / unidades)
    check("Los pasos pequenos no se pierden",
          abs(-rueda.total_delta()[0] - esperado) <= 1,
          f"enviado={-rueda.total_delta()[0]} esperado={esperado}")
    check("No usa clicks enteros", rueda.clicks == [])

    print("\n== C) Signos ==")
    rueda = RuedaFalsa()
    rueda.instalar()
    c = modulo_controlador.DesktopController()
    c.mouse_scroll(unidades, unidades, suave=True)
    v, h = rueda.total_delta()
    check("Vertical invertido como en clicks", v == -native_input.WHEEL_DELTA, str(v))
    check("Horizontal invertido como en clicks", h == -native_input.WHEEL_DELTA, str(h))

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
