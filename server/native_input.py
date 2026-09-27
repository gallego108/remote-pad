"""
Capa de entrada nativa de Windows (sin pynput).

pynput 1.8.2 esta roto con Python 3.12 en Windows: su llamada a SendInput
lanza `ArgumentError: expected LP__INPUT instance`. Aqui hablamos
directamente con la API de Windows, que es ademas mas rapida y mas precisa.

Todo pasa por SendInput con:
  - MOUSEEVENTF_ABSOLUTE ... el puntero va exactamente donde se le dice
  - KEYEVENTF_SCANCODE ..... teclas fisicas (independiente del layout)
  - KEYEVENTF_UNICODE ...... texto literal (acentos, simbolos, emoji)
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

# ------------------------------------------------------------------ constantes
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

SM_CXSCREEN = 0
SM_CYSCREEN = 1
VK_LBUTTON = 0x01

# Teclas "extendidas": necesitan el flag EXTENDEDKEY o no funcionan.
EXTENDED_VK = {
    0x21, 0x22, 0x23, 0x24,          # prior, next, end, home
    0x25, 0x26, 0x27, 0x28,          # flechas
    0x2D, 0x2E,                      # insert, delete
    0x5B, 0x5C,                      # teclas Windows
    0x6F,                            # dividir del teclado numerico
    0x90,                            # bloq num
    0xA3, 0xA5,                      # ctrl derecho, alt derecho
}

# Nombres logico -> virtual-key code
VIRTUAL_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "shift_l": 0xA0, "shift_r": 0xA1,
    "ctrl": 0x11, "control": 0x11, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt": 0x12, "alt_l": 0xA4, "alt_r": 0xA5, "menu": 0x5D,
    "caps_lock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "select": 0x29, "print": 0x2A, "print_screen": 0x2C, "insert": 0x2D,
    "delete": 0x2E, "del": 0x2E, "pause": 0x13, "num_lock": 0x90,
    "scroll_lock": 0x91, "win": 0x5B, "cmd": 0x5B, "super": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
}

# Volumen y multimedia (estas son Virtual-Key especiales)
MEDIA_KEYS = {
    "volume_mute": 0xAD,
    "mute": 0xAD,            # alias que envia la aplicacion del celular
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "next": 0xB0,
    "prev": 0xB1,
    "stop": 0xB2,
    "play_pause": 0xB3,
}

# ------------------------------------------------------------------- ctypes
if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
else:  # pragma: no cover
    _user32 = None
    _kernel32 = None


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def _configure() -> None:
    """Declara los prototipos: sin esto ctypes trunca punteros de 64 bits."""
    if not IS_WINDOWS:
        return
    _user32.SendInput.argtypes = (
        ctypes.c_uint,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    )
    _user32.SendInput.restype = ctypes.c_uint

    _user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    _user32.SetCursorPos.restype = wintypes.BOOL

    _user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    _user32.GetCursorPos.restype = wintypes.BOOL

    _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _user32.GetSystemMetrics.restype = ctypes.c_int

    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short

    _user32.MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
    _user32.MapVirtualKeyW.restype = ctypes.c_uint

    # Portapapeles (para compartir texto entre la PC y el celular).
    _user32.OpenClipboard.argtypes = (wintypes.HWND,)
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = (ctypes.c_uint,)
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.CloseClipboard.argtypes = ()
    _user32.CloseClipboard.restype = wintypes.BOOL

    _kernel32.GlobalLock.argtypes = (wintypes.HANDLE,)
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = (wintypes.HANDLE,)
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalFree.argtypes = (wintypes.HANDLE,)
    _kernel32.GlobalFree.restype = wintypes.HANDLE

    _user32.EmptyClipboard.argtypes = ()
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = (ctypes.c_uint, wintypes.HANDLE)
    _user32.SetClipboardData.restype = wintypes.HANDLE

    # Aplicacion en primer plano (para los perfiles por aplicacion).
    _user32.GetForegroundWindow.argtypes = ()
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    )
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


_configure()


# ------------------------------------------------------------------ utilidades
def available() -> bool:
    return bool(IS_WINDOWS and _user32 is not None)


def screen_size() -> tuple[int, int]:
    if not available():
        return (1920, 1080)
    return (
        int(_user32.GetSystemMetrics(SM_CXSCREEN)) or 1920,
        int(_user32.GetSystemMetrics(SM_CYSCREEN)) or 1080,
    )


def cursor_position() -> Optional[tuple[int, int]]:
    if not available():
        return None
    point = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        return None
    return (int(point.x), int(point.y))


def set_cursor_position(x: int, y: int) -> bool:
    if not available():
        return False
    return bool(_user32.SetCursorPos(int(x), int(y)))


def foreground_app() -> str:
    """
    Nombre del ejecutable en primer plano (sin ruta ni extension).

    Se usa para los perfiles por aplicacion: "chrome", "firefox", "winword"...
    Devuelve "" si no se puede saber. Conviene no llamarlo en bucle: cambia
    poco y cada llamada abre un proceso del sistema.
    """
    if not available():
        return ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(512)
            tamano = wintypes.DWORD(len(buffer))
            if not _kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(tamano)
            ):
                return ""
            return os.path.splitext(os.path.basename(buffer.value))[0]
        finally:
            _kernel32.CloseHandle(handle)
    except Exception:
        return ""


def left_button_is_down() -> bool:
    if not available():
        return False
    return bool(_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def _send(items: list[INPUT]) -> bool:
    """Envia una lista de eventos. Devuelve True si se enviaron todos."""
    if not available() or not items:
        return False
    array = (INPUT * len(items))(*items)
    try:
        sent = _user32.SendInput(len(items), array, ctypes.sizeof(INPUT))
    except Exception:
        return False
    return sent == len(items)


def _mouse_input(dx: int, dy: int, flags: int, data: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_MOUSE
    item.u.mi.dx = dx
    item.u.mi.dy = dy
    item.u.mi.mouseData = data
    item.u.mi.dwFlags = flags
    item.u.mi.time = 0
    item.u.mi.dwExtraInfo = None
    return item


def _key_input(vk: int, scan: int, flags: int) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki.wVk = vk
    item.u.ki.wScan = scan
    item.u.ki.dwFlags = flags
    item.u.ki.time = 0
    item.u.ki.dwExtraInfo = None
    return item


# --------------------------------------------------------------------- mouse
def move_absolute(x: int, y: int) -> bool:
    """
    Coloca el puntero en coordenadas de pantalla exactas.

    SendInput trabaja en un sistema normalizado de 0..65535 sobre el
    escritorio virtual, asi que hay que convertir. Se usa SetCursorPos
    (que acepta pixeles) y SendInput como respaldo.
    """
    if not available():
        return False
    width, height = screen_size()
    x = max(0, min(width - 1, int(x)))
    y = max(0, min(height - 1, int(y)))
    if set_cursor_position(x, y):
        return True
    nx = int(x * 65535 / max(1, width - 1))
    ny = int(y * 65535 / max(1, height - 1))
    return _send([_mouse_input(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)])


def move_relative(dx: float, dy: float) -> bool:
    if not available():
        return False
    return _send([_mouse_input(int(round(dx)), int(round(dy)), MOUSEEVENTF_MOVE)])


def jiggle(offset: int = 1) -> bool:
    """
    Genera actividad SIN mover el puntero de sitio: lo desplaza 'offset' px y
    lo devuelve en el mismo envio. Windows lo cuenta como actividad, asi que la
    pantalla no se apaga ni el equipo se suspende, y el usuario no lo nota.
    """
    if not available():
        return False
    paso = max(1, min(4, int(offset)))
    return _send(
        [
            _mouse_input(paso, 0, MOUSEEVENTF_MOVE),
            _mouse_input(-paso, 0, MOUSEEVENTF_MOVE),
        ]
    )


# SetThreadExecutionState: la via "oficial" de Windows para no apagarse.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def keep_display_awake(on: bool) -> bool:
    """
    Pide a Windows que no apague la pantalla ni suspenda el equipo.

    Se aplica al HILO que la llama, asi que hay que invocarla desde el bucle
    principal (el mismo que se mantiene vivo). Con on=False se desactiva.
    """
    if not available():
        return False
    flags = ES_CONTINUOUS
    if on:
        flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    try:
        _kernel32.SetThreadExecutionState.argtypes = (ctypes.c_uint,)
        _kernel32.SetThreadExecutionState.restype = ctypes.c_uint
        _kernel32.SetThreadExecutionState(flags)
        return True
    except Exception:
        return False


BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def button_down(button: str = "left") -> bool:
    flags = BUTTON_FLAGS.get(button)
    if flags is None:
        return False
    return _send([_mouse_input(0, 0, flags[0])])


def button_up(button: str = "left") -> bool:
    flags = BUTTON_FLAGS.get(button)
    if flags is None:
        return False
    return _send([_mouse_input(0, 0, flags[1])])


def click(button: str = "left", count: int = 1) -> bool:
    flags = BUTTON_FLAGS.get(button)
    if flags is None:
        return False
    items: list[INPUT] = []
    for _ in range(max(1, min(3, int(count)))):
        items.append(_mouse_input(0, 0, flags[0]))
        items.append(_mouse_input(0, 0, flags[1]))
    return _send(items)


def scroll(vertical: int, horizontal: int = 0) -> bool:
    """Rueda del raton. Unidades: 120 = un 'click' de rueda."""
    if not available():
        return False
    items: list[INPUT] = []
    if vertical:
        steps = max(-50, min(50, int(round(vertical))))
        if steps:
            items.append(_mouse_input(0, 0, MOUSEEVENTF_WHEEL, steps * WHEEL_DELTA))
    if horizontal:
        steps = max(-50, min(50, int(round(horizontal))))
        if steps:
            items.append(_mouse_input(0, 0, MOUSEEVENTF_HWHEEL, steps * WHEEL_DELTA))
    return _send(items) if items else True


def zoom(steps: int) -> bool:
    """
    Zoom con Ctrl + rueda (lo que hace la pinza de dos dedos).

    steps > 0 acerca, steps < 0 aleja. Todo va en un solo SendInput para que
    el Ctrl se suelte siempre, aunque el gesto sea muy corto.
    """
    if not available() or not steps:
        return False
    clicks = max(-50, min(50, int(round(steps))))
    if not clicks:
        return False
    ctrl = VIRTUAL_KEYS["ctrl"]
    scan = int(_user32.MapVirtualKeyW(ctrl, MAPVK_VK_TO_VSC)) or ctrl
    items = [
        _key_input(0, scan, KEYEVENTF_SCANCODE),
        _mouse_input(0, 0, MOUSEEVENTF_WHEEL, clicks * WHEEL_DELTA),
        _key_input(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP),
    ]
    return _send(items)


# -------------------------------------------------------------- portapapeles
CF_UNICODETEXT = 13


def get_clipboard() -> Optional[str]:
    """Texto que hay ahora mismo en el portapapeles de Windows (None si no hay)."""
    if not available():
        return None
    if not _user32.OpenClipboard(None):
        return None
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    except Exception:
        return None
    finally:
        _user32.CloseClipboard()


def set_clipboard(text: str) -> bool:
    """Deja 'text' en el portapapeles de Windows (para pegarlo en la PC)."""
    if not available():
        return False
    GMEM_MOVEABLE = 0x0002
    datos = str(text)
    tamano = (len(datos) + 1) * ctypes.sizeof(ctypes.c_wchar)
    bloque = _kernel32.GlobalAlloc(GMEM_MOVEABLE, tamano)
    if not bloque:
        return False
    puntero = _kernel32.GlobalLock(bloque)
    if not puntero:
        _kernel32.GlobalFree(bloque)
        return False
    try:
        ctypes.memmove(puntero, ctypes.create_unicode_buffer(datos), tamano)
    finally:
        _kernel32.GlobalUnlock(bloque)

    if not _user32.OpenClipboard(None):
        _kernel32.GlobalFree(bloque)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_UNICODETEXT, bloque):
            _kernel32.GlobalFree(bloque)
            return False
        # A partir de aqui el bloque es del sistema: no hay que liberarlo.
        return True
    except Exception:
        _kernel32.GlobalFree(bloque)
        return False
    finally:
        _user32.CloseClipboard()


# ------------------------------------------------------------------- teclado
def resolve_key(name: str) -> Optional[int]:
    """Nombre logico o caracter suelto -> virtual-key code."""
    if not name:
        return None
    key = VIRTUAL_KEYS.get(name.lower())
    if key is not None:
        return key
    upper = name.upper()
    if len(upper) == 1 and ("A" <= upper <= "Z" or "0" <= upper <= "9"):
        return ord(upper)
    return None


def tap_key(vk: int, extended: Optional[bool] = None) -> bool:
    """Pulsa y suelta una tecla por su virtual-key (usa scancode fisico)."""
    if not available():
        return False
    if extended is None:
        extended = vk in EXTENDED_VK
    flag = KEYEVENTF_EXTENDEDKEY if extended else 0
    scan = int(_user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) or vk
    return _send(
        [
            _key_input(0, scan, KEYEVENTF_SCANCODE | flag),
            _key_input(0, scan, KEYEVENTF_SCANCODE | flag | KEYEVENTF_KEYUP),
        ]
    )


def press_key(vk: int, extended: Optional[bool] = None) -> bool:
    if extended is None:
        extended = vk in EXTENDED_VK
    flag = KEYEVENTF_EXTENDEDKEY if extended else 0
    scan = int(_user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) or vk
    return _send([_key_input(0, scan, KEYEVENTF_SCANCODE | flag)])


def release_key(vk: int, extended: Optional[bool] = None) -> bool:
    if extended is None:
        extended = vk in EXTENDED_VK
    flag = KEYEVENTF_EXTENDEDKEY if extended else 0
    scan = int(_user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) or vk
    return _send([_key_input(0, scan, KEYEVENTF_SCANCODE | flag | KEYEVENTF_KEYUP)])


def combo(vk: int, modifiers: list[int]) -> bool:
    """Pulsa modificadores + tecla y lo suelta todo en orden inverso."""
    if not available():
        return False
    items: list[INPUT] = []
    for mod in modifiers:
        scan = int(_user32.MapVirtualKeyW(mod, MAPVK_VK_TO_VSC)) or mod
        flag = KEYEVENTF_EXTENDEDKEY if mod in EXTENDED_VK else 0
        items.append(_key_input(0, scan, KEYEVENTF_SCANCODE | flag))

    scan = int(_user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) or vk
    flag = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VK else 0
    items.append(_key_input(0, scan, KEYEVENTF_SCANCODE | flag))
    items.append(_key_input(0, scan, KEYEVENTF_SCANCODE | flag | KEYEVENTF_KEYUP))

    for mod in reversed(modifiers):
        scan = int(_user32.MapVirtualKeyW(mod, MAPVK_VK_TO_VSC)) or mod
        flag = KEYEVENTF_EXTENDEDKEY if mod in EXTENDED_VK else 0
        items.append(_key_input(0, scan, KEYEVENTF_SCANCODE | flag | KEYEVENTF_KEYUP))

    return _send(items)


def type_text(text: str) -> bool:
    """
    Escribe texto literal con KEYEVENTF_UNICODE: funciona con acentos,
    simbolos raros y emoji, sin depender de la distribucion del teclado.

    Convenciones: '\\n' = Enter, '\\b' = Retroceso.
    """
    if not available():
        return False
    if not text:
        return True

    items: list[INPUT] = []
    for index, line in enumerate(text.split("\n")):
        if index:
            items.append(_key_input(0x0D, 0, 0))
            items.append(_key_input(0x0D, 0, KEYEVENTF_KEYUP))
        for char in line:
            if char == "\b":
                items.append(_key_input(0x08, 0, 0))
                items.append(_key_input(0x08, 0, KEYEVENTF_KEYUP))
            elif char == "\t":
                items.append(_key_input(0x09, 0, 0))
                items.append(_key_input(0x09, 0, KEYEVENTF_KEYUP))
            else:
                code = ord(char)
                items.append(_key_input(0, code, KEYEVENTF_UNICODE))
                items.append(_key_input(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

    if not items:
        return True
    # En lotes: SendInput tiene un limite practico de eventos por llamada.
    ok = True
    for start in range(0, len(items), 256):
        ok = _send(items[start:start + 256]) and ok
    return ok


def press_media(name: str) -> bool:
    """Teclas multimedia y de volumen."""
    vk = MEDIA_KEYS.get(name)
    if vk is None:
        return False
    return tap_key(vk, extended=True)
