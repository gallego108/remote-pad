"""
Pruebas del boton "Ventana" (minimizar, maximizar/restaurar, cerrar).

  A) native_input.window_action con la API de Windows simulada: no toca
     ninguna ventana de verdad.
     - minimizar, maximizar, restaurar (si ya esta maximizada) y cerrar
       mandan el WM_SYSCOMMAND correcto a la ventana activa;
     - si el mensaje falla, minimizar/maximizar recurren a ShowWindow;
     - el escritorio, la barra de tareas y la consola de RemotePad no se
       cierran;
     - una operacion desconocida se rechaza.
  B) Protocolo: una operacion no valida devuelve error (no mueve nada).

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
        await ws.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--pin")
    args = parser.parse_args()

    prueba_nativa()
    if args.port and args.pin:
        asyncio.run(prueba_protocolo(args.port, args.pin))

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
