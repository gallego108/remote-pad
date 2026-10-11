"""
Genera el instalador de RemotePad (dist/RemotePad-Instalador-<version>.exe).

Requiere PyInstaller (python -m pip install pyinstaller) e Inno Setup 6.
Uso (desde la raiz del proyecto):

    python empaquetado/empaquetar.py

Pasos: PyInstaller hace dos carpetas (el panel y el servidor) en build/ y
Inno Setup las mete en un unico instalador con el asistente de siempre.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
AQUI = RAIZ / "empaquetado"
BUILD = RAIZ / "build"
DIST = RAIZ / "dist"
ICONO = RAIZ / "remotepad.ico"
SEP = ";"   # separador de --add-data en Windows
# numpy (~40 MB) entra por una dependencia opcional de PIL; RemotePad no la usa.
# El plugin AVIF de PIL tampoco (solo usamos ICO y PNG).
EXCLUIR = ["numpy", "PIL.AvifImagePlugin"]
# El panel y el despertador no usan HTTPS: no necesitan cryptography (~15 MB).
EXCLUIR_SIN_HTTPS = EXCLUIR + ["cryptography"]


def version() -> str:
    texto = (RAIZ / "server" / "app.py").read_text(encoding="utf-8")
    encontrado = re.search(r'^APP_VERSION = "([^"]+)"', texto, re.MULTILINE)
    if not encontrado:
        raise SystemExit("No encuentro APP_VERSION en server/app.py")
    return encontrado.group(1)


def buscar_iscc() -> Path:
    for candidato in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]:
        if candidato.is_file():
            return candidato
    raise SystemExit("No encuentro Inno Setup 6 (ISCC.exe). Instalalo desde https://jrsoftware.org/isinfo.php")


def pyinstaller(nombre: str, entrada: Path, datos: list[tuple[str, str]],
                ventana: bool, ocultos: list[str],
                excluir: list[str] = EXCLUIR) -> None:
    comando = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", nombre,
        "--icon", str(ICONO),
        "--distpath", str(BUILD / nombre.lower()),
        "--workpath", str(BUILD / "trabajo"),
        "--specpath", str(BUILD / "especificaciones"),
        "--paths", str(RAIZ / "server"),
        "--paths", str(RAIZ / "escritorio"),
        "--paths", str(AQUI),
    ]
    if ventana:
        comando.append("--windowed")
    for origen, destino in datos:
        comando += ["--add-data", f"{origen}{SEP}{destino}"]
    for modulo in ocultos:
        comando += ["--hidden-import", modulo]
    # Lo que se incluye por error de dependencias y no usamos (pesa decenas de MB).
    for modulo in excluir:
        comando += ["--exclude-module", modulo]
    comando.append(str(entrada))
    print(f"\n== PyInstaller: {nombre} ==")
    subprocess.run(comando, cwd=str(RAIZ), check=True)


def main() -> int:
    version_actual = version()
    print(f"RemotePad {version_actual}: empaquetando")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    DIST.mkdir(exist_ok=True)

    # Servidor: sin ventana; lleva la web dentro.
    pyinstaller(
        "RemotePadServidor", AQUI / "entrada_servidor.py",
        datos=[(str(RAIZ / "web"), "web")],
        ventana=True, ocultos=[],
    )
    # Panel: ventana + bandeja; lleva la interfaz, el icono y app.py (para leer la version).
    pyinstaller(
        "RemotePad", AQUI / "entrada_panel.py",
        datos=[
            (str(RAIZ / "escritorio" / "ui"), "escritorio/ui"),
            (str(ICONO), "."),
            (str(RAIZ / "server" / "app.py"), "server"),
        ],
        ventana=True, ocultos=["pystray._win32"], excluir=EXCLUIR_SIN_HTTPS,
    )

    # Despertador: sin ventana; lleva la pagina de "Encender" dentro.
    pyinstaller(
        "RemotePadDespertador", AQUI / "entrada_despertador.py",
        datos=[(str(RAIZ / "web"), "web")],
        ventana=True, ocultos=[], excluir=EXCLUIR_SIN_HTTPS,
    )

    iscc = buscar_iscc()
    print("\n== Inno Setup ==")
    subprocess.run([str(iscc), f"/DMyAppVersion={version_actual}",
                    str(AQUI / "instalador.iss")], cwd=str(AQUI), check=True)
    instalador = DIST / f"RemotePad-Instalador-{version_actual}.exe"
    print(f"\nListo: {instalador}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
