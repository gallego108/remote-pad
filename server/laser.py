"""
Puntero laser: capa transparente sobre toda la pantalla con un punto rojo.

Se ejecuta como proceso aparte (`python laser.py`) para no mezclar el bucle de
tkinter con el de asyncio del servidor. El servidor le escribe una linea por la
entrada estandar por cada posicion:

    "x y"   -> coloca el punto en esas coordenadas de pantalla (pixeles)
    "off"   -> oculta el punto
    (cerrar la entrada) -> termina

La ventana es transparente y "click-through" (no intercepta el raton), asi que
se puede seguir usando la PC con normalidad mientras se senala.
"""

from __future__ import annotations

import sys
import threading

try:
    import tkinter as tk
except Exception:  # pragma: no cover - sin tkinter no hay laser
    tk = None

TRANSPARENT_COLOR = "#010203"   # color clave que Windows vuelve transparente
DOT_RADIUS = 16
DOT_COLOR = "#ff2d55"
DOT_EDGE = "#ffffff"

# Estado compartido entre el hilo que lee la entrada y el bucle de dibujo.
_estado = {"x": None, "y": None, "vivo": True}


def _leer_entrada() -> None:
    try:
        for linea in sys.stdin:
            texto = linea.strip()
            if texto == "off":
                _estado["x"] = None
                continue
            partes = texto.split()
            if len(partes) != 2:
                continue
            try:
                _estado["x"] = float(partes[0])
                _estado["y"] = float(partes[1])
            except ValueError:
                continue
    except Exception:
        pass
    _estado["vivo"] = False


def _click_through(ventana: "tk.Tk") -> None:
    """Hace que la ventana no capture los clics (Windows)."""
    try:
        user32 = __import__("ctypes").windll.user32
        hwnd = user32.GetParent(ventana.winfo_id())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )
    except Exception:
        pass


def main() -> int:
    if tk is None:
        print("tkinter no esta disponible", file=sys.stderr)
        return 1

    raiz = tk.Tk()
    raiz.overrideredirect(True)
    try:
        raiz.attributes("-topmost", True)
    except Exception:
        pass
    try:
        raiz.attributes("-transparentcolor", TRANSPARENT_COLOR)
    except Exception:
        pass
    ancho = raiz.winfo_screenwidth()
    alto = raiz.winfo_screenheight()
    raiz.geometry(f"{ancho}x{alto}+0+0")
    raiz.configure(bg=TRANSPARENT_COLOR)

    lienzo = tk.Canvas(raiz, bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0)
    lienzo.pack(fill="both", expand=True)
    punto = lienzo.create_oval(
        0, 0, 0, 0, fill=DOT_COLOR, outline=DOT_EDGE, width=3, state="hidden"
    )
    raiz.update_idletasks()
    _click_through(raiz)

    threading.Thread(target=_leer_entrada, daemon=True, name="laser-stdin").start()

    def dibujar() -> None:
        if not _estado["vivo"]:
            try:
                raiz.destroy()
            except Exception:
                pass
            return
        x, y = _estado["x"], _estado["y"]
        if x is None:
            lienzo.itemconfigure(punto, state="hidden")
        else:
            r = DOT_RADIUS
            lienzo.coords(punto, x - r, y - r, x + r, y + r)
            lienzo.itemconfigure(punto, state="normal")
        raiz.after(16, dibujar)

    raiz.after(16, dibujar)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
