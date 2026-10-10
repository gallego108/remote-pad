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
# Cada cuanto se vuelve a mirar que monitores hay (se pueden conectar o
# desconectar con la app en marcha). Consultarlo en cada movimiento seria caro.
MONITOR_REFRESH_SECONDS = 3.0
# Modo mando: teclas que se pueden tener pulsadas a la vez (cruceta en
# diagonal + varios botones). Limita el dano de un cliente que no las suelte.
MAX_HELD_KEYS = 8


class DesktopController:
    """Controla el mouse y el teclado del equipo donde corre el servidor."""

    def __init__(self, pin_verifier=None) -> None:
        # Se llama antes de cada accion sensible para que el servidor pueda
        # mantener el PIN al dia aunque el celular este inactivo.
        self._pin_verifier = pin_verifier

        self._screen_w, self._screen_h = native_input.screen_size()
        self._monitors: list[dict] = native_input.monitors()
        self._monitors_at = time.monotonic()
        real = native_input.cursor_position() or (0, 0)
        self._virt_x, self._virt_y = real
        self._lock = threading.RLock()

        self._drag_button: Optional[str] = None
        self._scroll_remainder = [0.0, 0.0]
        # Teclas mantenidas por el modo mando (virtual-key codes).
        self._held_keys: set[int] = set()

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
        self.refresh_monitors(force=True)
        return self.screen_size

    # ------------------------------------------------------------- monitores
    def refresh_monitors(self, force: bool = False) -> list[dict]:
        ahora = time.monotonic()
        if force or ahora - self._monitors_at >= MONITOR_REFRESH_SECONDS:
            self._monitors = native_input.monitors()
            self._monitors_at = ahora
        return self._monitors

    @property
    def monitors(self) -> list[dict]:
        """Monitores conectados (el principal primero)."""
        return list(self.refresh_monitors())

    def _rects(self) -> list[tuple[int, int, int, int]]:
        return [(m["x"], m["y"], m["w"], m["h"]) for m in self.refresh_monitors()]

    def move_to_monitor(self, index: int) -> Optional[dict]:
        """
        Lleva el puntero al centro del monitor `index` (0 = el principal).

        Devuelve el monitor, o None si no existe. Sirve para cruzar de una
        pantalla a otra sin arrastrar el dedo varias veces.
        """
        self._check_pin()
        lista = self.refresh_monitors(force=True)
        if not 0 <= index < len(lista):
            return None
        monitor = lista[index]
        with self._lock:
            x = monitor["x"] + monitor["w"] // 2
            y = monitor["y"] + monitor["h"] // 2
            if native_input.move_absolute(x, y, self._rects()):
                self._virt_x, self._virt_y = x, y
        return monitor

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
            # Se limita a la zona que cubren los monitores (todos, no solo el
            # principal: antes el puntero no podia pasar a un segundo monitor).
            rects = self._rects()
            clamped_x, clamped_y = native_input.clamp_to_rects(target_x, target_y, rects)

            if clamped_x == self._virt_x and clamped_y == self._virt_y:
                # Ya estamos en el borde: si el cursor real sigue pegado ahi,
                # el desfase acumulado solo sirve para que al cambiar de
                # direccion el puntero tarde en responder. Lo descartamos.
                self._sync_pointer()
                return

            if native_input.move_absolute(clamped_x, clamped_y, rects):
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
            for vk in list(self._held_keys):
                native_input.release_key(vk)
            self._held_keys.clear()
            for key in ("shift", "ctrl", "alt", "cmd"):
                vk = native_input.resolve_key(key)
                if vk is not None:
                    native_input.release_key(vk)

    # ------------------------------------------------------- modo mando
    @property
    def held_keys(self) -> list[int]:
        return sorted(self._held_keys)

    def key_down(self, key: str) -> bool:
        """
        Mantiene pulsada una tecla (modo mando) hasta key_up o release_all.

        Pulsar otra vez una tecla ya mantenida no envia nada: asi un mensaje
        repetido no deja una pulsacion "de mas" que el juego leeria como doble.
        """
        self._check_pin()
        vk = native_input.resolve_key(key)
        if vk is None:
            return False
        with self._lock:
            if vk in self._held_keys:
                return True
            if len(self._held_keys) >= MAX_HELD_KEYS:
                return False
            if native_input.press_key(vk):
                self._held_keys.add(vk)
                return True
            return False

    def key_up(self, key: str) -> bool:
        """Suelta una tecla mantenida (o cualquier tecla, por si acaso)."""
        vk = native_input.resolve_key(key)
        if vk is None:
            return False
        with self._lock:
            self._held_keys.discard(vk)
            return native_input.release_key(vk)

    def mouse_scroll(self, dx: float, dy: float, suave: bool = False) -> None:
        """
        Rueda del raton.

        El cliente envia 'unidades' (1 unidad = 1 pixel de deslizamiento).
        Se convierten a clicks de rueda y se conserva el resto para que un
        deslizamiento lento tambien acabe produciendo movimiento.

        Con 'suave' se mandan fracciones de click (rueda de alta resolucion):
        el desplazamiento es continuo en lugar de saltar de 3 en 3 lineas.
        """
        self._check_pin()
        with self._lock:
            self._scroll_remainder[0] += dx
            self._scroll_remainder[1] += dy

            if suave:
                por_unidad = native_input.WHEEL_DELTA / UNITS_PER_SCROLL_CLICK
                # round(.., 6) antes de truncar: 22 * (120 / 22) da 119,999...
                horizontal = int(round(self._scroll_remainder[0] * por_unidad, 6))
                vertical = int(round(self._scroll_remainder[1] * por_unidad, 6))
                self._scroll_remainder[0] -= horizontal / por_unidad
                self._scroll_remainder[1] -= vertical / por_unidad
                if horizontal or vertical:
                    # Mismo cambio de signo que en el caso de clicks enteros.
                    native_input.scroll_delta(-vertical, -horizontal)
                return

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

    def zoom(self, steps: int) -> bool:
        """Zoom con Ctrl + rueda (pinza de dos dedos). >0 acerca, <0 aleja."""
        self._check_pin()
        with self._lock:
            return native_input.zoom(steps)

    def clipboard_text(self) -> str:
        """Texto del portapapeles de la PC (para enviarlo al celular)."""
        self._check_pin()
        with self._lock:
            return native_input.get_clipboard() or ""

    def clipboard_set(self, text: str) -> bool:
        """Deja texto en el portapapeles de la PC (para pegarlo alli)."""
        self._check_pin()
        with self._lock:
            return native_input.set_clipboard(text)

    # ------------------------------------------------------- anti-apagado
    def jiggle(self) -> None:
        """Mueve el raton 1 px y lo devuelve: actividad sin mover el puntero."""
        with self._lock:
            native_input.jiggle(1)

    def keep_display_awake(self, on: bool) -> bool:
        """Pide a Windows que no apague la pantalla mientras este activo."""
        return native_input.keep_display_awake(on)

    # ---------------------------------------------------- perfiles por app
    def foreground_app(self) -> str:
        """Nombre del ejecutable en primer plano (para los perfiles por app)."""
        return native_input.foreground_app()

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

    # ------------------------------------------------------- atajos propios
    def run_macro(self, pasos: list[dict]) -> bool:
        """
        Ejecuta un atajo personalizado: combinaciones, texto y esperas, en orden.

        Los pasos llegan ya validados (ver `validate_macro` en app.py). Si uno
        falla se sigue con el resto, y se devuelve False al final; las teclas
        no quedan pulsadas porque cada combinacion se suelta en el mismo envio.
        """
        todo_bien = True
        for paso in pasos:
            tipo = paso.get("tipo")
            if tipo == "combo":
                todo_bien = self.key_tap(paso["tecla"], paso.get("mods") or []) and todo_bien
            elif tipo == "texto":
                todo_bien = self.type_text(paso["texto"]) and todo_bien
            elif tipo == "espera":
                time.sleep(paso["ms"] / 1000.0)
        return todo_bien

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
