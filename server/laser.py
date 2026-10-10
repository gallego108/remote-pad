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


def _capa(ventana: "tk.Tk") -> int:
    """
    Hace que la ventana no capture los clics ni el foco del teclado (antes se
    quedaba con el foco: lo que se escribia desde el celular no llegaba al
    programa que tenias delante). Devuelve su hwnd de nivel superior.
    """
    try:
        import native_input
        return native_input.make_overlay(ventana.winfo_id())
    except Exception:
        return 0


def main() -> int:
    if tk is None:
        print("tkinter no esta disponible", file=sys.stderr)
        return 1

    try:
        import native_input
        anterior = native_input.foreground_window()
    except Exception:
        native_input = None
        anterior = 0

    raiz = tk.Tk()
    # Oculta mientras se prepara: los estilos de capa se ponen antes de que
    # Windows la muestre (y la active).
    raiz.withdraw()
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
    capa = _capa(raiz)
    raiz.deiconify()
    raiz.update()
    if native_input is not None:
        # Red de seguridad: si aun asi se quedo con el foco, se devuelve.
        native_input.give_back_focus(anterior, capa)
        raiz.after(300, lambda: native_input.give_back_focus(anterior, capa))

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
