"""
Instala el despertador de RemotePad para que arranque solo con Windows.

Pone un acceso directo en la carpeta Inicio de Windows (shell:startup) que
abre server/despertador.py con pythonw (sin ventana), y lo arranca ya. Con el
despertador en marcha, el icono de RemotePad del celular muestra "Encender
RemotePad" cuando el servidor esta apagado.

Uso:
    python tools/instalar_despertador.py            # instala y arranca
    python tools/instalar_despertador.py --https    # si usas RemotePad con --https
    python tools/instalar_despertador.py --quitar   # lo quita y lo detiene
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crear_acceso_directo import RAIZ, crear_enlace  # noqa: E402

SCRIPT = RAIZ / "server" / "despertador.py"
NOMBRE = "RemotePad despertador.lnk"


def carpeta_inicio() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup")


def pythonw() -> Path:
    candidato = Path(sys.executable).with_name("pythonw.exe")
    return candidato if candidato.is_file() else Path(sys.executable)


def detener() -> None:
    """Para los despertadores en marcha (solo los de este proyecto)."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Where-Object { $_.CommandLine -like '*server*despertador.py*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }"
    )
    salida = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True).stdout.split()
    for pid in salida:
        print(f"Despertador detenido (proceso {pid})")


def main() -> int:
    if sys.platform != "win32":
        print("Solo para Windows.")
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--quitar", action="store_true")
    parser.add_argument("--https", action="store_true")
    parser.add_argument("--no-iniciar", action="store_true",
                        help="solo instalar, sin arrancarlo ahora")
    args = parser.parse_args()

    enlace = carpeta_inicio() / NOMBRE
    if args.quitar:
        if enlace.exists():
            enlace.unlink()
            print(f"Quitado del inicio de Windows: {enlace}")
        detener()
        return 0

    argumentos = f'"{SCRIPT}"' + (" --https" if args.https else "")
    crear_enlace(enlace, pythonw(), argumentos, SCRIPT.parent,
                 "Despertador de RemotePad: enciende el servidor desde el celular")
    print(f"Arrancara solo con Windows: {enlace}")

    if not args.no_iniciar:
        detener()                      # por si habia uno con otras opciones
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(pythonw()), str(SCRIPT)] + (["--https"] if args.https else []),
                         cwd=str(SCRIPT.parent), creationflags=flags, close_fds=True)
        print("Despertador en marcha. Registro: server/despertador.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
