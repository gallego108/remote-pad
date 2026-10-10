"""
Ejecuta todas las pruebas de RemotePad.

Es lo que usan probar.bat (doble clic) y la integracion continua de GitHub,
para que la lista de pruebas este en un solo sitio.

    python tools/run_tests.py            # todo, moviendo el puntero de verdad
    python tools/run_tests.py --ci       # sin tocar el escritorio (servidores
                                         # de integracion sin sesion grafica)
    python tools/run_tests.py test_qr    # solo las que contengan ese texto

Todas las pruebas usan archivos de estado temporales: nunca tocan los
accesos, perfiles ni ajustes reales de server/.
"""

from __future__ import annotations

import argparse
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"
HERRAMIENTAS = RAIZ / "tools"
PUERTO = 8791


@dataclass
class Prueba:
    script: str
    args: list[str] = field(default_factory=list)
    servidor: bool = False       # necesita el servidor compartido de pruebas
    escritorio: bool = False     # mueve el puntero de verdad (no en --ci)
    cursor: bool = False         # anade --cursor salvo en --ci (solo esa parte
                                 # de la prueba mueve el puntero)


# Orden: primero las rapidas y sin servidor; despues las de extremo a extremo.
PRUEBAS = [
    Prueba("check_ui.py"),
    Prueba("test_qr.py"),
    Prueba("verify_rs.py"),
    Prueba("test_qr_window.py"),
    Prueba("test_auth.py"),
    Prueba("test_aprendizaje.py"),
    Prueba("test_stop.py"),
    Prueba("test_scroll.py"),
    Prueba("test_client.py", ["--port", "{puerto}", "--pin", "{pin}", "--cursor"],
           servidor=True, escritorio=True),
    Prueba("test_drag.py", ["--port", "{puerto}", "--pin", "{pin}"],
           servidor=True, escritorio=True),
    Prueba("test_monitores.py", ["--port", "{puerto}", "--pin", "{pin}"],
           servidor=True, cursor=True),
    Prueba("test_atajos.py", ["--port", "{puerto}", "--pin", "{pin}"], servidor=True),
    Prueba("test_mando.py", ["--port", "{puerto}", "--pin", "{pin}"], servidor=True),
    Prueba("test_qr_login.py", ["{puerto}"], servidor=True),
    Prueba("test_qr_rotacion.py", ["{puerto}"], servidor=True),
    Prueba("test_version_cache.py", ["{puerto}"], servidor=True),
    Prueba("test_acceso_libre.py"),
    Prueba("test_seguridad.py"),
    Prueba("test_dispositivos.py"),
    Prueba("test_https.py"),
]


def entorno_aislado() -> dict:
    carpeta = Path(tempfile.mkdtemp(prefix="remotepad_pruebas_"))
    entorno = dict(os.environ)
    entorno.update({
        "REMOTEPAD_TOKENS": str(carpeta / "tokens.json"),
        "REMOTEPAD_PROFILES": str(carpeta / "profiles.json"),
        "REMOTEPAD_LEARNING": str(carpeta / "learning.json"),
        "REMOTEPAD_CONFIG": str(carpeta / "config.json"),
        "REMOTEPAD_HTTPS_DIR": str(carpeta / "https"),
        "REMOTEPAD_SIN_VENTANAS": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return entorno


class ServidorDePruebas:
    def __init__(self, entorno: dict) -> None:
        self.lineas: list[str] = []
        self.proceso = subprocess.Popen(
            [sys.executable, "-u", "app.py", "--port", str(PUERTO), "--no-browser"],
            cwd=str(SERVIDOR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            env=entorno,
        )
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self) -> None:
        for linea in self.proceso.stdout:
            self.lineas.append(linea)

    def pin(self, segundos: float = 30.0) -> str:
        limite = time.time() + segundos
        while time.time() < limite:
            for linea in list(self.lineas):
                encontrado = re.search(r"PIN DE ACCESO\s*->\s*(\d{3})\s*(\d{3})", linea)
                if encontrado:
                    return encontrado.group(1) + encontrado.group(2)
            if self.proceso.poll() is not None:
                break
            time.sleep(0.1)
        return ""

    def parar(self) -> None:
        try:
            self.proceso.stdin.write("q\n")
            self.proceso.stdin.flush()
            self.proceso.wait(timeout=10)
        except Exception:
            self.proceso.kill()


def compilar() -> bool:
    bien = True
    for archivo in sorted(SERVIDOR.glob("*.py")) + sorted(HERRAMIENTAS.glob("*.py")):
        try:
            py_compile.compile(str(archivo), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"  [FALLO] {archivo.name}: {exc.msg}")
            bien = False
    return bien


def main() -> int:
    parser = argparse.ArgumentParser(description="Pruebas de RemotePad")
    parser.add_argument("--ci", action="store_true",
                        help="omitir las pruebas que mueven el puntero de verdad")
    parser.add_argument("filtro", nargs="*", help="solo las pruebas que contengan esto")
    args = parser.parse_args()

    elegidas = [p for p in PRUEBAS
                if not (args.ci and p.escritorio)
                and (not args.filtro or any(f in p.script for f in args.filtro))]
    omitidas = [p.script for p in PRUEBAS if args.ci and p.escritorio]

    print("=" * 62)
    print("  RemotePad - comprobando el proyecto")
    print("=" * 62)
    print("\n[1] Sintaxis de Python")
    if not compilar():
        return 1
    print("  correcta")

    entorno = entorno_aislado()
    servidor = None
    pin = ""
    if any(p.servidor for p in elegidas):
        print(f"\n[2] Servidor de pruebas en el puerto {PUERTO}")
        servidor = ServidorDePruebas(entorno)
        pin = servidor.pin()
        if not pin:
            print("  [FALLO] el servidor no arranco:")
            print("".join(servidor.lineas[-30:]))
            servidor.parar()
            return 1
        print(f"  listo (PIN {pin})")

    fallidas: list[str] = []
    try:
        for prueba in elegidas:
            orden = [sys.executable, str(HERRAMIENTAS / prueba.script)]
            orden += [a.format(puerto=PUERTO, pin=pin) for a in prueba.args]
            if prueba.cursor and not args.ci:
                orden.append("--cursor")
            print(f"\n----- {prueba.script} " + "-" * max(0, 48 - len(prueba.script)))
            sys.stdout.flush()
            resultado = subprocess.run(orden, cwd=str(RAIZ), env=entorno)
            if resultado.returncode != 0:
                fallidas.append(prueba.script)
    finally:
        if servidor is not None:
            servidor.parar()

    print("\n" + "=" * 62)
    if omitidas:
        print(f"  Omitidas (--ci, mueven el puntero): {', '.join(omitidas)}")
    if fallidas:
        print(f"  HAY FALLOS en: {', '.join(fallidas)}")
    else:
        print(f"  TODO CORRECTO ({len(elegidas)} pruebas)")
    print("=" * 62)
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
