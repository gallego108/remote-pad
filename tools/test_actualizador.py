"""
Pruebas del actualizador del panel (escritorio/actualizador.py).

Todo se prueba sin red: las llamadas a GitHub se sustituyen por datos de
ejemplo. Lo que se comprueba es que solo se acepta lo oficial y que una
huella que no coincide nunca llega a ejecutarse.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "escritorio"))

import actualizador  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def main() -> int:
    print("== Versiones ==")
    check("1.16.0 es mas nueva que 1.15.1", actualizador.hay_version_nueva("1.15.1", "1.16.0"))
    check("v1.16.0 (con v) tambien cuenta", actualizador.hay_version_nueva("1.15.1", "v1.16.0"))
    check("la misma version no es nueva", not actualizador.hay_version_nueva("1.16.0", "1.16.0"))
    check("una version antigua no es nueva", not actualizador.hay_version_nueva("1.16.0", "1.15.9"))
    check("1.10.0 es mas nueva que 1.9.0 (no es orden de texto)",
          actualizador.hay_version_nueva("1.9.0", "1.10.0"))

    print("\n== Huellas (SHA256SUMS.txt) ==")
    texto = ("A" * 64 + "  RemotePad-Instalador-1.16.0.exe\n"
             + "b" * 64 + " *otro.zip\n"
             + "linea rara sin huella\n")
    sumas = actualizador.leer_sumas(texto)
    check("lee la huella del instalador", sumas.get("RemotePad-Instalador-1.16.0.exe") == "a" * 64)
    check("acepta el formato con asterisco", sumas.get("otro.zip") == "b" * 64)
    check("ignora las lineas sin huella valida", len(sumas) == 2)

    print("\n== Origen ==")
    check("acepta descargas de la release oficial",
          actualizador.url_permitida("https://github.com/gallego108/remote-pad/releases/download/v1.16.0/x.exe"))
    check("rechaza otro repositorio",
          not actualizador.url_permitida("https://github.com/otro/remote-pad/releases/download/v1/x.exe"))
    check("rechaza una web cualquiera", not actualizador.url_permitida("https://evil.example/x.exe"))
    check("rechaza rutas con ../",
          not actualizador.url_permitida("https://github.com/gallego108/remote-pad/releases/download/../x.exe"))

    print("\n== Huella de un archivo ==")
    carpeta = Path(tempfile.mkdtemp(prefix="rp_act_"))
    archivo = carpeta / "instalador.exe"
    archivo.write_bytes(b"contenido de prueba")
    correcta = hashlib.sha256(b"contenido de prueba").hexdigest()
    check("una huella correcta se acepta", actualizador.verificar(archivo, correcta))
    check("una huella distinta se rechaza", not actualizador.verificar(archivo, "0" * 64))

    print("\n== Busqueda (red simulada) ==")
    base = "https://github.com/gallego108/remote-pad/releases/download/v1.16.0/"
    release = {
        "tag_name": "v1.16.0",
        "body": "Aviso de ventanas de administrador.",
        "assets": [
            {"name": "RemotePad-Instalador-1.16.0.exe", "browser_download_url": base + "RemotePad-Instalador-1.16.0.exe"},
            {"name": "SHA256SUMS.txt", "browser_download_url": base + "SHA256SUMS.txt"},
        ],
    }
    sumas_texto = ("c" * 64 + "  RemotePad-Instalador-1.16.0.exe\n")
    original_json, original_texto = actualizador._leer_json, actualizador._leer_texto
    try:
        actualizador._leer_json = lambda url, timeout=10.0: release
        actualizador._leer_texto = lambda url, timeout=10.0: sumas_texto
        resultado = actualizador.buscar("1.15.1")
        check("con una release nueva, la encuentra", resultado.get("disponible") is True,
              str(resultado))
        check("devuelve la huella del instalador", resultado.get("sha256") == "c" * 64)
        check("devuelve la URL oficial", resultado.get("url", "").startswith(base))

        actualizador._leer_json = lambda url, timeout=10.0: {**release, "tag_name": "v1.15.1"}
        check("sin release nueva no ofrece nada",
              actualizador.buscar("1.15.1").get("disponible") is False)

        def sin_red(url, timeout=10.0):
            raise OSError("sin conexion")
        actualizador._leer_json = sin_red
        error = actualizador.buscar("1.15.1")
        check("sin red devuelve un error claro", error.get("disponible") is False and "GitHub" in error.get("error", ""))
    finally:
        actualizador._leer_json, actualizador._leer_texto = original_json, original_texto

    print(f"\n{checks - failures} de {checks} comprobaciones correctas.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
