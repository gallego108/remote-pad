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
    _gdi32 = ctypes.windll.gdi32
    try:
        _dwmapi = ctypes.windll.dwmapi
    except OSError:  # pragma: no cover
        _dwmapi = None
else:  # pragma: no cover
    _user32 = None
    _kernel32 = None
    _gdi32 = None
    _dwmapi = None


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


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)
MONITORINFOF_PRIMARY = 0x1

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


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


    # Varios monitores.
    _user32.EnumDisplayMonitors.argtypes = (
        wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MONITORENUMPROC, wintypes.LPARAM
    )
    _user32.EnumDisplayMonitors.restype = wintypes.BOOL
    _user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO))
    _user32.GetMonitorInfoW.restype = wintypes.BOOL

    # Pregunta de confirmacion (dispositivos nuevos).
    _user32.MessageBoxTimeoutW.argtypes = (
        wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.UINT, wintypes.WORD, wintypes.DWORD,
    )
    _user32.MessageBoxTimeoutW.restype = ctypes.c_int
    _user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.PostMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    _user32.PostMessageW.restype = wintypes.BOOL

    # Minimizar, maximizar y cerrar la ventana activa.
    _user32.IsZoomed.argtypes = (wintypes.HWND,)
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.ShowWindowAsync.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    _user32.GetAncestor.restype = wintypes.HWND
    _kernel32.GetConsoleWindow.argtypes = ()
    _kernel32.GetConsoleWindow.restype = wintypes.HWND

    # Lista de programas abiertos y traer uno al frente.
    _user32.EnumWindows.argtypes = (_WNDENUMPROC, wintypes.LPARAM)
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = (wintypes.HWND,)
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    _user32.GetWindow.restype = wintypes.HWND
    _user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.argtypes = ()
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    # Iconos de los programas abiertos.
    _user32.PrivateExtractIconsW.argtypes = (
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT,
    )
    _user32.PrivateExtractIconsW.restype = wintypes.UINT
    _user32.SendMessageTimeoutW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    )
    _user32.SendMessageTimeoutW.restype = ctypes.c_size_t
    _user32.GetClassLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.GetClassLongPtrW.restype = ctypes.c_size_t
    _user32.DrawIconEx.argtypes = (
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
        ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
    )
    _user32.DrawIconEx.restype = wintypes.BOOL
    _user32.DestroyIcon.argtypes = (wintypes.HICON,)
    _user32.DestroyIcon.restype = wintypes.BOOL
    _gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateDIBSection.argtypes = (
        wintypes.HDC, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    )
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    _gdi32.DeleteDC.restype = wintypes.BOOL
    _gdi32.GdiFlush.argtypes = ()
    _gdi32.GdiFlush.restype = wintypes.BOOL

    if _dwmapi is not None:
        _dwmapi.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
        )
        _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


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


# Rectangulo de un monitor en coordenadas del escritorio: (x, y, ancho, alto).
# El principal empieza en (0, 0); los demas pueden tener coordenadas negativas
# (un monitor a la izquierda o encima del principal).
Rect = tuple[int, int, int, int]


def monitors() -> list[dict]:
    """
    Monitores conectados, el principal primero y el resto de izquierda a derecha.

    Cada uno: {"x", "y", "w", "h", "primary"}. Sin Windows (o si falla la
    consulta) se devuelve un unico monitor del tamano de la pantalla.
    """
    ancho, alto = screen_size()
    respaldo = [{"x": 0, "y": 0, "w": ancho, "h": alto, "primary": True}]
    if not available():
        return respaldo
    encontrados: list[dict] = []

    def _uno(hmonitor, _hdc, _rect, _datos):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            encontrados.append({
                "x": int(r.left), "y": int(r.top),
                "w": int(r.right - r.left), "h": int(r.bottom - r.top),
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            })
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_uno), 0)
    except Exception:
        return respaldo
    if not encontrados:
        return respaldo
    encontrados.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    return encontrados


def clamp_to_rects(x: float, y: float, rects: list[Rect]) -> tuple[int, int]:
    """
    Lleva (x, y) al punto mas cercano que este DENTRO de algun monitor.

    Es pura (no toca el sistema) para poder probarla con distribuciones de
    monitores simuladas. Con monitores de alturas distintas hay "huecos" en el
    escritorio virtual: un punto en el hueco se pega al borde del monitor mas
    cercano, igual que hace el raton fisico.
    """
    if not rects:
        return int(round(x)), int(round(y))
    mejor: Optional[tuple[int, int]] = None
    mejor_distancia = float("inf")
    for izquierda, arriba, ancho, alto in rects:
        if ancho <= 0 or alto <= 0:
            continue
        cx = min(max(int(round(x)), izquierda), izquierda + ancho - 1)
        cy = min(max(int(round(y)), arriba), arriba + alto - 1)
        distancia = (cx - x) ** 2 + (cy - y) ** 2
        if distancia < mejor_distancia:
            mejor, mejor_distancia = (cx, cy), distancia
    return mejor if mejor is not None else (int(round(x)), int(round(y)))


def monitor_rects() -> list[Rect]:
    return [(m["x"], m["y"], m["w"], m["h"]) for m in monitors()]


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
        return _exe_de_ventana(hwnd)
    except Exception:
        return ""


def _exe_de_ventana(hwnd) -> str:
    """Nombre del ejecutable (sin ruta ni extension) dueno de una ventana."""
    ruta = _ruta_exe(hwnd)
    return os.path.splitext(os.path.basename(ruta))[0] if ruta else ""


def _ruta_exe(hwnd) -> str:
    """Ruta completa del ejecutable dueno de una ventana ("" si no se sabe)."""
    try:
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
            return buffer.value
        finally:
            _kernel32.CloseHandle(handle)
    except Exception:
        return ""


# Ventanas que no se deben tocar: el escritorio y la barra de tareas (un
# "cerrar" sobre el escritorio abriria el dialogo de apagar Windows).
_VENTANAS_SISTEMA = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
}
_WM_SYSCOMMAND = 0x0112
_SC_MINIMIZE = 0xF020
_SC_MAXIMIZE = 0xF030
_SC_RESTORE = 0xF120
_SC_CLOSE = 0xF060
_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_SW_RESTORE = 9
_GA_ROOT = 2


def window_action(op: str) -> dict:
    """
    Minimiza, maximiza (o restaura si ya lo esta) o cierra la ventana activa.

    `op` es "minimize", "maximize" o "close". Devuelve {"ok", "title", "done"}
    o {"error"}. Se usa WM_SYSCOMMAND, igual que los botones de la barra de
    titulo: la aplicacion puede preguntar si guardar antes de cerrar.
    """
    if op not in ("minimize", "maximize", "close"):
        return {"error": "operacion desconocida"}
    if not available():
        return {"error": "no disponible"}
    hwnd = _user32.GetForegroundWindow()
    if hwnd:
        hwnd = _user32.GetAncestor(hwnd, _GA_ROOT) or hwnd
    if not hwnd:
        return {"error": "no hay ninguna ventana activa"}

    clase = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, clase, len(clase))
    if clase.value in _VENTANAS_SISTEMA:
        return {"error": "no hay ninguna ventana activa"}
    # La consola de RemotePad: cerrarla apagaria el servidor.
    if op == "close" and hwnd == _kernel32.GetConsoleWindow():
        return {"error": "es la consola de RemotePad"}

    titulo = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, titulo, len(titulo))

    if op == "minimize":
        comando, mostrar, hecho = _SC_MINIMIZE, _SW_MINIMIZE, "minimized"
    elif op == "maximize" and _user32.IsZoomed(hwnd):
        comando, mostrar, hecho = _SC_RESTORE, _SW_RESTORE, "restored"
    elif op == "maximize":
        comando, mostrar, hecho = _SC_MAXIMIZE, _SW_MAXIMIZE, "maximized"
    else:
        comando, mostrar, hecho = _SC_CLOSE, None, "closed"

    ok = bool(_user32.PostMessageW(hwnd, _WM_SYSCOMMAND, comando, 0))
    # Si el mensaje no llega (p. ej. ventana de un programa elevado), ShowWindow
    # sigue funcionando para minimizar y maximizar.
    if not ok and mostrar is not None:
        ok = bool(_user32.ShowWindowAsync(hwnd, mostrar))
    if not ok:
        return {"error": "Windows no dejo cambiar esa ventana"}
    return {"ok": True, "title": titulo.value, "done": hecho}


_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_NOACTIVATE = 0x08000000
_DWMWA_CLOAKED = 14
_VK_ALT = 0x12
MAX_VENTANAS = 60


def _en_barra_de_tareas(hwnd) -> bool:
    """
    Las mismas reglas que usa la barra de tareas (y Alt+Tab) para mostrar una
    ventana: visible, con titulo, sin dueno (o marcada como ventana de
    aplicacion), que no sea de herramientas y que no este "oculta" por DWM
    (apps de la tienda suspendidas o ventanas de otro escritorio virtual).
    """
    if not _user32.IsWindowVisible(hwnd):
        return False
    if _user32.GetWindowTextLengthW(hwnd) <= 0:
        return False
    estilo = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    if estilo & _WS_EX_TOOLWINDOW:
        return False
    if _user32.GetWindow(hwnd, _GW_OWNER) and not estilo & _WS_EX_APPWINDOW:
        return False
    if estilo & _WS_EX_NOACTIVATE and not estilo & _WS_EX_APPWINDOW:
        return False
    if _dwmapi is not None:
        oculta = wintypes.DWORD()
        if _dwmapi.DwmGetWindowAttribute(
            hwnd, _DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta)
        ) == 0 and oculta.value:
            return False
    clase = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, clase, len(clase))
    return clase.value not in _VENTANAS_SISTEMA


def _titulo(hwnd) -> str:
    longitud = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(min(max(longitud, 0), 300) + 1)
    _user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _raiz_activa() -> int:
    activa = _user32.GetForegroundWindow()
    if not activa:
        return 0
    return int(_user32.GetAncestor(activa, _GA_ROOT) or activa)


def list_windows() -> list[dict]:
    """
    Programas abiertos, como en la barra de tareas, del usado mas
    recientemente al mas antiguo (orden Z).
    Cada uno: {"id", "title", "app", "min", "active"}.
    """
    if not available():
        return []
    activa = _raiz_activa()
    encontradas: list[int] = []

    def _una(hwnd, _lparam):
        try:
            if _en_barra_de_tareas(hwnd):
                encontradas.append(int(hwnd))
        except Exception:
            pass
        return len(encontradas) < MAX_VENTANAS

    _user32.EnumWindows(_WNDENUMPROC(_una), 0)
    ventanas = []
    for hwnd in encontradas:
        ruta = _ruta_exe(hwnd)
        ventanas.append({
            "id": hwnd,
            "title": _titulo(hwnd),
            "app": os.path.splitext(os.path.basename(ruta))[0] if ruta else "",
            "path": ruta,
            "min": bool(_user32.IsIconic(hwnd)),
            "active": hwnd == activa,
        })
    return ventanas


_WM_GETICON = 0x007F
_ICON_SMALL2 = 2
_ICON_BIG = 1
_GCLP_HICON = -14
_SMTO_ABORTIFHUNG = 0x0002
_DI_NORMAL = 0x0003
# Programas que alojan ventanas de otros: el icono de su .exe no es el bueno.
_EXE_ANFITRIONES = {"applicationframehost"}


def _icono_de_ventana(hwnd) -> int:
    """El icono que la propia ventana muestra (no hay que destruirlo)."""
    for tipo in (_ICON_BIG, _ICON_SMALL2):
        resultado = ctypes.c_size_t(0)
        if _user32.SendMessageTimeoutW(
            hwnd, _WM_GETICON, tipo, 0, _SMTO_ABORTIFHUNG, 150,
            ctypes.byref(resultado),
        ) and resultado.value:
            return resultado.value
    return _user32.GetClassLongPtrW(hwnd, _GCLP_HICON) or 0


def window_icon(hwnd: int, ruta: str = "", tamano: int = 64):
    """
    Dibuja el icono de un programa abierto.

    Primero el del ejecutable a `tamano` px (nitido en la pantalla del
    celular); si no hay, el que muestra la ventana. Devuelve
    (ancho, alto, bgra_sobre_negro, bgra_sobre_blanco) o None; iconos.py lo
    convierte a PNG con transparencia.
    """
    if not available() or _gdi32 is None:
        return None
    icono = 0
    propio = False
    nombre = os.path.splitext(os.path.basename(ruta))[0].lower() if ruta else ""
    if ruta and nombre not in _EXE_ANFITRIONES:
        hicon = wintypes.HICON()
        ident = wintypes.UINT()
        if _user32.PrivateExtractIconsW(
            ruta, 0, tamano, tamano, ctypes.byref(hicon), ctypes.byref(ident), 1, 0
        ) == 1 and hicon:
            icono, propio = hicon.value, True
    if not icono:
        icono = _icono_de_ventana(hwnd)
    if not icono:
        return None

    dc = _gdi32.CreateCompatibleDC(None)
    cabecera = _BITMAPINFOHEADER(
        ctypes.sizeof(_BITMAPINFOHEADER), tamano, -tamano, 1, 32, 0, 0, 0, 0, 0, 0
    )
    bits = ctypes.c_void_p()
    mapa = _gdi32.CreateDIBSection(dc, ctypes.byref(cabecera), 0, ctypes.byref(bits), None, 0)
    anterior = _gdi32.SelectObject(dc, mapa) if mapa else None
    try:
        if not mapa or not bits.value:
            return None
        n = tamano * tamano * 4
        dibujos = []
        for fondo in (0x00, 0xFF):
            ctypes.memset(bits, fondo, n)
            if not _user32.DrawIconEx(dc, 0, 0, icono, tamano, tamano, 0, None, _DI_NORMAL):
                return None
            _gdi32.GdiFlush()
            dibujos.append(ctypes.string_at(bits, n))
        return tamano, tamano, dibujos[0], dibujos[1]
    finally:
        if anterior:
            _gdi32.SelectObject(dc, anterior)
        if mapa:
            _gdi32.DeleteObject(mapa)
        _gdi32.DeleteDC(dc)
        if propio:
            _user32.DestroyIcon(icono)


def focus_window(hwnd_id: int) -> dict:
    """
    Trae al frente una ventana de la lista (y la restaura si esta minimizada).

    Solo se aceptan ventanas que saldrian en la barra de tareas: el celular no
    puede activar ventanas ocultas ni del sistema. Windows impide que un
    proceso en segundo plano robe el foco, asi que se prueba primero de forma
    normal, despues uniendo la entrada con el hilo de la ventana activa y,
    como ultimo recurso, tras una pulsacion de Alt (que habilita el cambio).
    """
    if not available():
        return {"error": "no disponible"}
    if not hwnd_id or not _user32.IsWindow(hwnd_id) or not _en_barra_de_tareas(hwnd_id):
        return {"error": "esa ventana ya no esta abierta"}

    if _user32.IsIconic(hwnd_id):
        _user32.ShowWindowAsync(hwnd_id, _SW_RESTORE)

    def _al_frente() -> bool:
        return _raiz_activa() == hwnd_id

    _user32.SetForegroundWindow(hwnd_id)
    if not _al_frente():
        activa = _user32.GetForegroundWindow()
        hilo_activo = _user32.GetWindowThreadProcessId(activa, None) if activa else 0
        propio = _kernel32.GetCurrentThreadId()
        unido = bool(hilo_activo) and hilo_activo != propio and bool(
            _user32.AttachThreadInput(propio, hilo_activo, True)
        )
        try:
            _user32.BringWindowToTop(hwnd_id)
            _user32.SetForegroundWindow(hwnd_id)
        finally:
            if unido:
                _user32.AttachThreadInput(propio, hilo_activo, False)
    if not _al_frente():
        tap_key(_VK_ALT)
        _user32.SetForegroundWindow(hwnd_id)
    return {"ok": True, "title": _titulo(hwnd_id), "front": _al_frente()}


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
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MOUSEEVENTF_VIRTUALDESK = 0x4000


def virtual_screen() -> Rect:
    """Rectangulo que abarca todos los monitores: (x, y, ancho, alto)."""
    if not available():
        ancho, alto = screen_size()
        return (0, 0, ancho, alto)
    return (
        int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)) or 1920,
        int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)) or 1080,
    )


def move_absolute(x: int, y: int, rects: Optional[list[Rect]] = None) -> bool:
    """
    Coloca el puntero en coordenadas de escritorio exactas.

    Se limita a la zona cubierta por los monitores (`rects`; si no se pasan,
    se consultan). Antes se limitaba al monitor PRINCIPAL y el puntero no
    podia pasar a un segundo monitor.

    Se usa SetCursorPos (que acepta pixeles) y SendInput como respaldo: este
    trabaja en un sistema normalizado de 0..65535 sobre todo el escritorio
    virtual, asi que hay que convertir.
    """
    if not available():
        return False
    x, y = clamp_to_rects(x, y, rects if rects is not None else monitor_rects())
    if set_cursor_position(x, y):
        return True
    izquierda, arriba, ancho, alto = virtual_screen()
    nx = int((x - izquierda) * 65535 / max(1, ancho - 1))
    ny = int((y - arriba) * 65535 / max(1, alto - 1))
    return _send([_mouse_input(
        nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )])


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
    """Rueda del raton en 'clicks' enteros (cada uno = WHEEL_DELTA)."""
    v = max(-50, min(50, int(round(vertical))))
    h = max(-50, min(50, int(round(horizontal))))
    return scroll_delta(v * WHEEL_DELTA, h * WHEEL_DELTA)


MAX_WHEEL_DELTA = 50 * WHEEL_DELTA


def scroll_delta(vertical: int, horizontal: int = 0) -> bool:
    """
    Rueda en alta resolucion: unidades de rueda (120 = un 'click').

    Windows admite valores menores que WHEEL_DELTA (las ruedas y touchpads de
    precision los usan): las aplicaciones modernas desplazan solo esa
    fraccion, y el scroll se ve continuo en vez de a saltos de 3 lineas.
    """
    if not available():
        return False
    items: list[INPUT] = []
    v = max(-MAX_WHEEL_DELTA, min(MAX_WHEEL_DELTA, int(vertical)))
    h = max(-MAX_WHEEL_DELTA, min(MAX_WHEEL_DELTA, int(horizontal)))
    if v:
        items.append(_mouse_input(0, 0, MOUSEEVENTF_WHEEL, v))
    if h:
        items.append(_mouse_input(0, 0, MOUSEEVENTF_HWHEEL, h))
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


# ------------------------------------------------------------- confirmacion
MB_YESNO = 0x04
MB_ICONQUESTION = 0x20
MB_DEFBUTTON2 = 0x100
MB_SYSTEMMODAL = 0x1000
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDYES = 6
IDNO = 7
WM_COMMAND = 0x0111


def ask_yes_no(title: str, text: str, seconds: float) -> Optional[bool]:
    """
    Pregunta Si/No en una ventana encima de todo. Bloquea hasta la respuesta.

    Devuelve True (Si), False (No) o None si paso el tiempo o no se pudo
    mostrar. "No" es el boton por defecto: un ENTER despistado no deja entrar
    a nadie. MessageBoxTimeoutW no esta documentada, pero existe en user32
    desde Windows XP y es la unica forma de que la ventana se cierre sola.
    """
    if not available():
        return None
    flags = (MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2 | MB_SYSTEMMODAL
             | MB_SETFOREGROUND | MB_TOPMOST)
    try:
        resultado = _user32.MessageBoxTimeoutW(
            None, text, title, flags, 0, int(max(1.0, seconds) * 1000)
        )
    except Exception:
        return None
    if resultado == IDYES:
        return True
    if resultado == IDNO:
        return False
    return None


def dismiss_question(title: str) -> bool:
    """Cierra (respondiendo No) la pregunta abierta con ese titulo."""
    if not available():
        return False
    try:
        hwnd = _user32.FindWindowW("#32770", title)
        if not hwnd:
            return False
        return bool(_user32.PostMessageW(hwnd, WM_COMMAND, IDNO, 0))
    except Exception:
        return False
