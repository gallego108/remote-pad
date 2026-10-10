"""
Pruebas del boton "Ventana" (minimizar, maximizar/restaurar, cerrar) y de
la lista de programas abiertos.

  A) native_input.window_action con la API de Windows simulada: no toca
     ninguna ventana de verdad.
     - minimizar, maximizar, restaurar (si ya esta maximizada) y cerrar
       mandan el WM_SYSCOMMAND correcto a la ventana activa;
     - si el mensaje falla, minimizar/maximizar recurren a ShowWindow;
     - el escritorio, la barra de tareas y la consola de RemotePad no se
       cierran;
     - una operacion desconocida se rechaza.
  C) Programas abiertos (API simulada): solo salen las ventanas que
     estarian en la barra de tareas, y solo esas se pueden traer al frente.
  B) Protocolo: una operacion no valida devuelve error (no mueve nada); la
     lista de programas llega con su formato; un id invalido se rechaza.

Uso:
    python tools/test_ventana.py                      # A
    python tools/test_ventana.py --port 8791 --pin 123456
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import native_input  # noqa: E402

failures = 0
checks = 0

HWND = 0x1234
CONSOLA = 0x9999
WM_SYSCOMMAND = 0x0112
SC_MINIMIZE, SC_MAXIMIZE, SC_RESTORE, SC_CLOSE = 0xF020, 0xF030, 0xF120, 0xF060


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


class User32Falso:
    def __init__(self, hwnd=HWND, clase="Notepad", titulo="Sin titulo - Bloc de notas",
                 maximizada=False, post_ok=True):
        self.hwnd = hwnd
        self.clase = clase
        self.titulo = titulo
        self.maximizada = maximizada
        self.post_ok = post_ok
        self.mensajes: list[tuple] = []
        self.mostrar: list[tuple] = []

    def GetForegroundWindow(self):
        return self.hwnd

    def GetAncestor(self, hwnd, flag):
        return hwnd

    def GetClassNameW(self, hwnd, buffer, n):
        buffer.value = self.clase
        return len(self.clase)

    def GetWindowTextW(self, hwnd, buffer, n):
        buffer.value = self.titulo
        return len(self.titulo)

    def IsZoomed(self, hwnd):
        return self.maximizada

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.mensajes.append((hwnd, msg, wparam))
        return self.post_ok

    def ShowWindowAsync(self, hwnd, cmd):
        self.mostrar.append((hwnd, cmd))
        return True


class Kernel32Falso:
    def GetCurrentThreadId(self):
        return 1

    def GetConsoleWindow(self):
        return CONSOLA


def con_falsos(user32: User32Falso, op: str) -> dict:
    originales = (native_input._user32, native_input._kernel32, native_input.IS_WINDOWS)
    native_input._user32 = user32
    native_input._kernel32 = Kernel32Falso()
    native_input.IS_WINDOWS = True
    try:
        return native_input.window_action(op)
    finally:
        native_input._user32, native_input._kernel32, native_input.IS_WINDOWS = originales


def prueba_nativa() -> None:
    print("\n== A) window_action (API de Windows simulada) ==")
    u = User32Falso()
    r = con_falsos(u, "minimize")
    check("Minimizar manda SC_MINIMIZE", u.mensajes == [(HWND, WM_SYSCOMMAND, SC_MINIMIZE)])
    check("Devuelve el titulo y lo hecho",
          r.get("ok") and r.get("done") == "minimized"
          and r.get("title") == "Sin titulo - Bloc de notas", str(r))

    u = User32Falso()
    r = con_falsos(u, "maximize")
    check("Maximizar manda SC_MAXIMIZE",
          u.mensajes == [(HWND, WM_SYSCOMMAND, SC_MAXIMIZE)] and r.get("done") == "maximized")

    u = User32Falso(maximizada=True)
    r = con_falsos(u, "maximize")
    check("Si ya esta maximizada, la restaura",
          u.mensajes == [(HWND, WM_SYSCOMMAND, SC_RESTORE)] and r.get("done") == "restored")

    u = User32Falso()
    r = con_falsos(u, "close")
    check("Cerrar manda SC_CLOSE",
          u.mensajes == [(HWND, WM_SYSCOMMAND, SC_CLOSE)] and r.get("done") == "closed")

    u = User32Falso(post_ok=False)
    r = con_falsos(u, "minimize")
    check("Si el mensaje falla, minimiza con ShowWindow",
          u.mostrar == [(HWND, 6)] and r.get("ok"), str(r))

    u = User32Falso(post_ok=False)
    r = con_falsos(u, "close")
    check("Si cerrar falla, avisa del error", "error" in r and not u.mostrar)

    for clase in ("Progman", "WorkerW", "Shell_TrayWnd"):
        u = User32Falso(clase=clase)
        r = con_falsos(u, "close")
        check(f"No toca el escritorio/barra ({clase})", "error" in r and not u.mensajes)

    u = User32Falso(hwnd=CONSOLA, clase="ConsoleWindowClass")
    r = con_falsos(u, "close")
    check("No cierra la consola de RemotePad", "error" in r and not u.mensajes)
    u = User32Falso(hwnd=CONSOLA, clase="ConsoleWindowClass")
    r = con_falsos(u, "minimize")
    check("Pero si puede minimizarla", r.get("ok") and u.mensajes)

    u = User32Falso(hwnd=0)
    check("Sin ventana activa, error", "error" in con_falsos(u, "minimize"))

    u = User32Falso()
    r = con_falsos(u, "destroy")
    check("Operacion desconocida se rechaza", "error" in r and not u.mensajes)


WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000


class EscritorioFalso(User32Falso):
    """Varias ventanas con distintas propiedades, para list_windows."""

    def __init__(self):
        super().__init__(hwnd=10)
        # hwnd: (visible, titulo, estilo_ex, dueno, clase)
        self.ventanas = {
            10: (True, "Documento - Word", 0, 0, "OpusApp"),
            11: (False, "Oculta", 0, 0, "X"),
            12: (True, "", 0, 0, "X"),
            13: (True, "Paleta", WS_EX_TOOLWINDOW, 0, "X"),
            14: (True, "Dialogo", 0, 10, "#32770"),
            15: (True, "Dialogo de app", WS_EX_APPWINDOW, 10, "#32770"),
            16: (True, "Program Manager", 0, 0, "Progman"),
            17: (True, "Chrome", 0, 0, "Chrome_WidgetWin_1"),
        }
        self.minimizadas = {17}
        self.al_frente: list[int] = []

    def EnumWindows(self, callback, lparam):
        for hwnd in self.ventanas:
            if not callback(hwnd, lparam):
                break
        return True

    def IsWindow(self, hwnd):
        return hwnd in self.ventanas

    def IsWindowVisible(self, hwnd):
        return self.ventanas[hwnd][0]

    def GetWindowTextLengthW(self, hwnd):
        return len(self.ventanas[hwnd][1])

    def GetWindowTextW(self, hwnd, buffer, n):
        buffer.value = self.ventanas[hwnd][1]
        return len(buffer.value)

    def GetWindowLongPtrW(self, hwnd, indice):
        return self.ventanas[hwnd][2]

    def GetWindow(self, hwnd, cmd):
        return self.ventanas[hwnd][3]

    def GetClassNameW(self, hwnd, buffer, n):
        buffer.value = self.ventanas[hwnd][4]
        return len(buffer.value)

    def IsIconic(self, hwnd):
        return hwnd in self.minimizadas

    def ShowWindowAsync(self, hwnd, cmd):
        self.minimizadas.discard(hwnd)
        return True

    def SetForegroundWindow(self, hwnd):
        self.al_frente.append(hwnd)
        self.hwnd = hwnd
        return True

    def GetWindowThreadProcessId(self, hwnd, pid):
        return 0


def con_escritorio(escritorio: EscritorioFalso, funcion, *args):
    originales = (native_input._user32, native_input._kernel32,
                  native_input._dwmapi, native_input.IS_WINDOWS,
                  native_input._ruta_exe)
    native_input._user32 = escritorio
    native_input._kernel32 = Kernel32Falso()
    native_input._dwmapi = None
    native_input.IS_WINDOWS = True
    native_input._ruta_exe = lambda hwnd: f"C:/Apps/app{hwnd}.exe"
    try:
        return funcion(*args)
    finally:
        (native_input._user32, native_input._kernel32, native_input._dwmapi,
         native_input.IS_WINDOWS, native_input._ruta_exe) = originales


def prueba_programas() -> None:
    print("\n== C) Programas abiertos (API de Windows simulada) ==")
    e = EscritorioFalso()
    lista = con_escritorio(e, native_input.list_windows)
    ids = [v["id"] for v in lista]
    check("Solo las ventanas de la barra de tareas", ids == [10, 15, 17], str(ids))
    check("Marca la activa", [v["active"] for v in lista] == [True, False, False])
    check("Marca la minimizada", [v["min"] for v in lista] == [False, False, True])
    check("Titulo y programa", lista[0]["title"] == "Documento - Word"
          and lista[0]["app"] == "app10", str(lista[0]))

    e = EscritorioFalso()
    r = con_escritorio(e, native_input.focus_window, 17)
    check("Trae al frente la elegida y la restaura",
          r.get("ok") and r.get("front") and e.al_frente == [17] and 17 not in e.minimizadas,
          str(r))
    for hwnd, motivo in ((11, "oculta"), (13, "de herramientas"), (16, "el escritorio"),
                         (99, "inexistente"), (0, "id 0")):
        e = EscritorioFalso()
        r = con_escritorio(e, native_input.focus_window, hwnd)
        check(f"No activa una ventana {motivo}", "error" in r and not e.al_frente)

    e = EscritorioFalso()
    r = con_escritorio(e, native_input.close_window, 17)
    check("Cerrar un programa de la lista manda SC_CLOSE a esa ventana",
          r.get("ok") and e.mensajes == [(17, WM_SYSCOMMAND, SC_CLOSE)], str(r))
    for hwnd, motivo in ((13, "de herramientas"), (16, "el escritorio"), (99, "inexistente")):
        e = EscritorioFalso()
        r = con_escritorio(e, native_input.close_window, hwnd)
        check(f"No cierra una ventana {motivo}", "error" in r and not e.mensajes)
    e = EscritorioFalso()
    e.ventanas[CONSOLA] = (True, "RemotePad", 0, 0, "ConsoleWindowClass")
    r = con_escritorio(e, native_input.close_window, CONSOLA)
    check("No cierra la consola de RemotePad desde la lista", "error" in r and not e.mensajes)


async def prueba_protocolo(puerto: int, pin: str) -> None:
    import aiohttp

    print("\n== B) Protocolo ==")
    url = f"http://127.0.0.1:{puerto}/ws"
    async with aiohttp.ClientSession() as sesion:
        ws = await sesion.ws_connect(url)
        await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
        respuesta = json.loads((await ws.receive(timeout=5)).data)
        check("Entra con el PIN", bool(respuesta.get("token")))
        await ws.send_str(json.dumps({"a": "window", "d": {"op": "formatear"}}))
        while True:
            mensaje = json.loads((await ws.receive(timeout=5)).data)
            if mensaje.get("t") == "response" and mensaje.get("a") == "window":
                break
        check("Una operacion no valida devuelve error", "error" in mensaje.get("d", {}),
              str(mensaje))

        async def respuesta(accion: str) -> dict:
            while True:
                m = json.loads((await ws.receive(timeout=5)).data)
                if m.get("t") == "response" and m.get("a") == accion:
                    return m.get("d", {})

        await ws.send_str(json.dumps({"a": "windows_list", "d": {}}))
        datos = await respuesta("windows_list")
        ventanas = datos.get("windows")
        check("windows_list devuelve una lista", isinstance(ventanas, list), str(datos)[:200])
        check("Cada programa trae id, titulo y app",
              all({"id", "title", "app", "min", "active"} <= set(v) for v in ventanas or []))
        check("La ruta del ejecutable no sale de la PC",
              all("path" not in v for v in ventanas or []))
        imagenes = datos.get("icons")
        check("Los iconos llegan aparte y cada clave existe",
              isinstance(imagenes, dict)
              and all(v["icon"] in imagenes for v in ventanas or [] if "icon" in v))
        check("Los iconos son PNG en data URL",
              all(str(u).startswith("data:image/png;base64,") for u in (imagenes or {}).values()))
        await ws.send_str(json.dumps({"a": "window_focus", "d": {"id": "nada"}}))
        check("window_focus con un id invalido se rechaza",
              "error" in await respuesta("window_focus"))
        await ws.send_str(json.dumps({"a": "window_close", "d": {"id": 0}}))
        check("window_close con un id invalido se rechaza",
              "error" in await respuesta("window_close"))
        await ws.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--pin")
    args = parser.parse_args()

    prueba_nativa()
    prueba_programas()
    if args.port and args.pin:
        asyncio.run(prueba_protocolo(args.port, args.pin))

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
