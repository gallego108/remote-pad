"""
Crea el acceso directo "RemotePad" en el Escritorio y en el menu Inicio.

Por que: en algunos equipos, al hacer doble clic en iniciar.bat dentro de la
carpeta del proyecto, Windows muestra "Advertencia de seguridad de Abrir
archivo - No se pudo comprobar el editor" y hay que pulsar Ejecutar cada vez
(los .bat no llevan firma digital). El acceso directo abre cmd.exe, que si
esta firmado por Microsoft, y este lanza iniciar.bat: el aviso ya no sale.

El icono (remotepad.ico) se genera a partir de web/icon-192.png.

Uso:
    python tools/crear_acceso_directo.py            # crea o actualiza
    python tools/crear_acceso_directo.py --quitar   # los borra
    python tools/crear_acceso_directo.py --args "--no-browser"
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LANZADOR = RAIZ / "iniciar.bat"
ICONO_PNG = RAIZ / "web" / "icon-192.png"
ICONO = RAIZ / "remotepad.ico"
NOMBRE = "RemotePad.lnk"


def ico_desde_png(png: bytes) -> bytes:
    """Un .ico con una sola imagen PNG dentro (valido desde Windows Vista)."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("no es un PNG")
    ancho, alto = struct.unpack(">II", png[16:24])
    lado = lambda n: 0 if n >= 256 else n   # 0 significa 256 en un .ico
    cabecera = struct.pack("<HHH", 0, 1, 1)
    entrada = struct.pack("<BBBBHHII", lado(ancho), lado(alto), 0, 0, 1, 32,
                          len(png), 6 + 16)
    return cabecera + entrada + png


def carpetas() -> list[Path]:
    """Escritorio (aunque este redirigido, p. ej. a OneDrive) y menu Inicio."""
    escritorio = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True,
    ).stdout.strip()
    inicio = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [Path(escritorio), inicio] if escritorio else [inicio]


def crear_enlace(destino: Path, objetivo: Path, argumentos: str, carpeta: Path,
                 descripcion: str, ventana: int = 1) -> None:
    """Crea (o actualiza) un acceso directo .lnk. ventana: 1 normal, 7 minimizada."""
    if not ICONO.exists():
        ICONO.write_bytes(ico_desde_png(ICONO_PNG.read_bytes()))
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RP_LNK);"
        "$s.TargetPath = $env:RP_CMD;"
        "$s.Arguments = $env:RP_ARGS;"
        "$s.WorkingDirectory = $env:RP_DIR;"
        "$s.IconLocation = $env:RP_ICO + ',0';"
        "$s.Description = $env:RP_DESC;"
        "$s.WindowStyle = [int]$env:RP_WIN;"
        "$s.Save()"
    )
    entorno = dict(
        os.environ, RP_LNK=str(destino), RP_CMD=str(objetivo), RP_ARGS=argumentos,
        RP_DIR=str(carpeta), RP_ICO=str(ICONO), RP_DESC=descripcion, RP_WIN=str(ventana),
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=entorno, check=True)


def crear(destino: Path, argumentos: str) -> None:
    comando = f'/c ""{LANZADOR}"{(" " + argumentos) if argumentos else ""}"'
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    crear_enlace(destino, cmd, comando, RAIZ, "Iniciar RemotePad (touchpad del celular)")


def main() -> int:
    if sys.platform != "win32":
        print("Solo para Windows.")
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--quitar", action="store_true", help="borra los accesos directos")
    parser.add_argument("--args", default="", help="opciones para app.py (p. ej. --https)")
    args = parser.parse_args()

    if args.quitar:
        for carpeta in carpetas():
            enlace = carpeta / NOMBRE
            if enlace.exists():
                enlace.unlink()
                print(f"Borrado: {enlace}")
        return 0

    ICONO.write_bytes(ico_desde_png(ICONO_PNG.read_bytes()))
    for carpeta in carpetas():
        destino = carpeta / NOMBRE
        crear(destino, args.args.strip())
        print(f"Acceso directo listo: {destino}")
    print("Abre RemotePad desde ahi: ya no saldra la advertencia de seguridad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
