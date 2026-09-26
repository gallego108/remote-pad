"""
Control del escritorio: puntero, clics, scroll, teclado, multimedia.

Todo pasa por `native_input` (API de Windows). En el diseno original se uso
pynput, pero su version 1.8.2 esta rota con Python 3.12 en Windows: su llamada
a SendInput lanza `ArgumentError: expected LP__INPUT instance`, asi que el
movimiento del puntero y todas las teclas fallaban en silencio.

Este modulo mantiene su propia idea de donde esta el puntero para poder
trabajar con desplazamientos relativos (asi el celular no necesita conocer
la resolucion) y se resincroniza cuando el usuario mueve el mouse fisico.
"""

from __future__ import annotations

import threading
import time
from typing import Iterable, Optional

import native_input

# Nombres de teclas aceptados (los que envia la aplicacion del celular).
SPECIAL_KEYS = {
    "alt", "alt_l", "alt_r", "alt_gr", "backspace", "caps_lock", "cmd",
    "ctrl", "ctrl_l", "ctrl_r", "delete", "down", "end", "enter", "esc",
    "home", "insert", "left", "menu", "num_lock", "page_down", "page_up",
    "pause", "print_screen", "right", "scroll_lock", "shift", "shift_l",
    "shift_r", "space", "tab", "up", "win",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}

# Vistas predeterminadas de PowerPoint / Impress / visores basados en teclado.
PRESENTATION_KEYS = {
    "next": "right",
    "prev": "left",
    "start": "f5",
    "end": "esc",
    "black": "b",
    "white": "w",
    "blank": "period",
}

UNITS_PER_SCROLL_CLICK = 22.0   # unidades del cliente por "click" de rueda


class DesktopController:
    """Controla el mouse y el teclado del equipo donde corre el servidor."""

    def __init__(self, pin_verifier=None) -> None:
        # Se llama antes de cada accion sensible para que el servidor pueda
        # mantener el PIN al dia aunque el celular este inactivo.
        self._pin_verifier = pin_verifier

        self._screen_w, self._screen_h = native_input.screen_size()
        real = native_input.cursor_position() or (0, 0)
        self._virt_x, self._virt_y = real
        self._lock = threading.RLock()

        self._drag_button: Optional[str] = None
        self._scroll_remainder = [0.0, 0.0]

    # ------------------------------------------------------------- utilidades
    @property
    def screen_size(self) -> tuple[int, int]:
        return (self._screen_w, self._screen_h)

    @property
    def virtual_position(self) -> tuple[int, int]:
        """Posicion que el servidor cree que tiene el puntero."""
        return (self._virt_x, self._virt_y)

    @property
    def drag_button(self) -> Optional[str]:
        """Boton que RemotePad tiene presionado ahora mismo (arrastre)."""
        return self._drag_button

    def refresh_screen_size(self) -> tuple[int, int]:
        self._screen_w, self._screen_h = native_input.screen_size()
        return self.screen_size

    def _check_pin(self) -> None:
        if self._pin_verifier is not None:
            try:
                self._pin_verifier()
            except Exception:
                pass

    def _sync_pointer(self) -> None:
        """Si el usuario movio el mouse fisico, adoptamos esa posicion."""
        if self._drag_button is not None:
            return          # en pleno arrastre manda el celular
        real = native_input.cursor_position()
        if real is None:
            return
        if abs(real[0] - self._virt_x) <= 2 and abs(real[1] - self._virt_y) <= 2:
            return
        self._virt_x, self._virt_y = real

    # ---------------------------------------------------------------- mouse
    def mouse_move(self, dx: float, dy: float) -> None:
        """
        Desplaza el puntero de forma relativa, sin salirse de la pantalla.

        Nota: la deteccion del arrastre se apoya en nuestro propio estado
        (`_drag_button`) y no en `GetAsyncKeyState`, porque esa API NO refleja
        los botones que inyectamos con SendInput: si dependieramos de ella, el
        arrastre iniciado desde el celular se soltaria solo.
        """
        self._check_pin()
        if not dx and not dy:
            return
        with self._lock:
            self._sync_pointer()

            target_x = self._virt_x + dx
            target_y = self._virt_y + dy
            clamped_x = max(0, min(self._screen_w - 1, int(round(target_x))))
            clamped_y = max(0, min(self._screen_h - 1, int(round(target_y))))

            if clamped_x == self._virt_x and clamped_y == self._virt_y:
                # Ya estamos en el borde: si el cursor real sigue pegado ahi,
                # el desfase acumulado solo sirve para que al cambiar de
                # direccion el puntero tarde en responder. Lo descartamos.
                self._sync_pointer()
                return

            if native_input.move_absolute(clamped_x, clamped_y):
                self._virt_x, self._virt_y = clamped_x, clamped_y
            else:
                self._sync_pointer()

    def mouse_move_to(self, x: float, y: float) -> None:
        self._check_pin()
        with self._lock:
            self._sync_pointer()
            self.mouse_move(x - self._virt_x, y - self._virt_y)

    def mouse_click(self, button: str = "left", count: int = 1) -> None:
        self._check_pin()
        with self._lock:
            native_input.click(button, count)

    def mouse_button_down(self, button: str = "left") -> None:
        self._check_pin()
        with self._lock:
            if self._drag_button is not None and self._drag_button != button:
                native_input.button_up(self._drag_button)
            native_input.button_down(button)
            self._drag_button = button

    def mouse_button_up(self, button: str = "left") -> None:
        self._check_pin()
        with self._lock:
            if self._drag_button is not None and self._drag_button != button:
                native_input.button_up(self._drag_button)
                self._drag_button = None
            native_input.button_up(button)
            if self._drag_button == button:
                self._drag_button = None

    def release_all(self) -> None:
        """Suelta botones y modificadores: se usa al desconectar el celular."""
        with self._lock:
            for button in ("left", "right", "middle"):
                native_input.button_up(button)
            self._drag_button = None
            for key in ("shift", "ctrl", "alt", "cmd"):
                vk = native_input.resolve_key(key)
                if vk is not None:
                    native_input.release_key(vk)

    def mouse_scroll(self, dx: float, dy: float) -> None:
        """
        Rueda del raton.

        El cliente envia 'unidades' (1 unidad = 1 pixel de deslizamiento).
        Se convierten a clicks de rueda y se conserva el resto para que un
        deslizamiento lento tambien acabe produciendo movimiento.
        """
        self._check_pin()
        with self._lock:
            self._scroll_remainder[0] += dx
            self._scroll_remainder[1] += dy

            horizontal = int(self._scroll_remainder[0] / UNITS_PER_SCROLL_CLICK)
            vertical = int(self._scroll_remainder[1] / UNITS_PER_SCROLL_CLICK)

            if horizontal:
                self._scroll_remainder[0] -= horizontal * UNITS_PER_SCROLL_CLICK
            if vertical:
                self._scroll_remainder[1] -= vertical * UNITS_PER_SCROLL_CLICK

            if horizontal or vertical:
                # En Windows la rueda horizontal crece hacia la derecha y la
                # vertical hacia arriba: los signos van invertidos respecto a
                # la pantalla, y el cliente ya aplica su propio "scroll
                # natural", asi que aqui se invierte una sola vez.
                native_input.scroll(-vertical, -horizontal)

    # -------------------------------------------------------------- teclado
    def key_tap(self, key: str, modifiers: Optional[Iterable[str]] = None) -> bool:
        """Pulsa una tecla o combinacion. True si se pudo enviar."""
        self._check_pin()
        if not key:
            return False

        vk = native_input.resolve_key(key)
        if vk is None:
            # Un caracter suelto ('a', '5', '@'...): se escribe como texto
            # para que funcione con cualquier distribucion de teclado.
            if len(key) == 1:
                mods = self._resolve_modifiers(modifiers)
                if mods:
                    return native_input.combo(ord(key.upper()), mods)
                return native_input.type_text(key)
            return False

        mods = self._resolve_modifiers(modifiers)
        with self._lock:
            if mods:
                return native_input.combo(vk, mods)
            return native_input.tap_key(vk)

    @staticmethod
    def _resolve_modifiers(modifiers: Optional[Iterable[str]]) -> list[int]:
        result: list[int] = []
        for name in modifiers or ():
            vk = native_input.resolve_key(str(name))
            if vk is not None and vk not in result:
                result.append(vk)
        return result

    def type_text(self, text: str) -> bool:
        """Escribe texto literal (y '\\n' / '\\b') en la ventana con foco."""
        self._check_pin()
        if not text:
            return True
        with self._lock:
            return native_input.type_text(text)

    # ------------------------------------------------------------ multimedia
    def media(self, action: str) -> bool:
        self._check_pin()
        return native_input.press_media((action or "").lower())

    # --------------------------------------------------------- presentaciones
    def presentation(self, action: str) -> bool:
        self._check_pin()
        key = PRESENTATION_KEYS.get((action or "").lower())
        if key is None:
            return False
        return self.key_tap(key)

    # -------------------------------------------------------------- utilidades
    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))
