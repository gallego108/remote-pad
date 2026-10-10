"""
Comprueba el mecanismo anti-cache que evita que el celular se quede con un
JavaScript viejo (el origen del mensaje "accion desconocida auth").

Se verifica:
  - que el servidor inyecta SIEMPRE la version en el HTML, con o sin QR;
  - que esa respuesta no se cachea;
  - que la constante de version del HTML coincide con la del servidor (si no,
    la propia pagina recargaria en bucle);
  - que el service worker pide a la red el codigo de la aplicacion.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import aiohttp

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "server"))

import app as servidor  # noqa: E402

BASE = "http://127.0.0.1:" + (sys.argv[1] if len(sys.argv) > 1 else "8765")
failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


async def main() -> int:
    print("Version y cache de la parte web")
    print("=" * 64)

    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    sw = (RAIZ / "web" / "sw.js").read_text(encoding="utf-8")

    print("\n== Coherencia de versiones ==")
    en_html = re.search(r"REMOTEPAD_WEB\s*=\s*'([^']+)'", html)
    check("El HTML declara su version", en_html is not None)
    check("La version del HTML coincide con la del servidor",
          bool(en_html) and en_html.group(1) == servidor.APP_VERSION,
          f"html={en_html.group(1) if en_html else '?'} "
          f"servidor={servidor.APP_VERSION}")

    print("\n== Aviso de version en la pagina ==")
    check("El HTML trae el detector de version",
          "remotepad-version" in html and "REMOTEPAD_WEB" in html)
    check("Si no cuadra, recarga con ?v=", "?v=" in html)
    check("Y avisa en pantalla si ya lo intento",
          "Vaciar cache" in html or "Vaciar caché" in html,
          "no se encontro el aviso de vaciar cache")
    check("Si no hay meta (pagina vieja), tambien recarga",
          "servidor === REMOTEPAD_WEB" in html and "window.stop()" in html)

    print("\n== Service worker ==")
    check("Pide el codigo a la red sin cache",
          "cache: 'no-store'" in sw and "critico" in sw)
    # La v4 fue la primera con "red primero"; cada version posterior la sube.
    version_cache = re.search(r"const CACHE = 'remotepad-v(\d+)'", sw)
    check("La version de la cache ha cambiado",
          version_cache is not None and int(version_cache.group(1)) >= 4,
          version_cache.group(0) if version_cache else "sin nombre de cache")
    check("No cachea la recarga forzada", "?v=" in sw)

    print("\n== El servidor inyecta la version ==")
    async with aiohttp.ClientSession() as sesion:
        async with sesion.get(f"{BASE}/") as respuesta:
            cuerpo = await respuesta.text()
            check("Sin QR tambien se inyecta la version",
                  f'name="remotepad-version" content="{servidor.APP_VERSION}"' in cuerpo)
            cache = respuesta.headers.get("Cache-Control", "")
            check("La pagina no se cachea", "no-store" in cache, cache)
            check("Tampoco por Pragma", "no-cache" in respuesta.headers.get("Pragma", ""))

        async with sesion.get(f"{BASE}/qr") as respuesta:
            panel = await respuesta.text()
        clave = re.search(r'"key":"([^"]+)"', panel).group(1)

        async with sesion.get(f"{BASE}/?k={clave}") as respuesta:
            cuerpo = await respuesta.text()
            check("Con QR se inyectan clave, estado y version",
                  "remotepad-qr-key" in cuerpo
                  and "remotepad-qr-estado" in cuerpo
                  and "remotepad-version" in cuerpo)
            check("El estado de la clave es correcto",
                  'name="remotepad-qr-estado" content="ok"' in cuerpo)
            check("Y esa respuesta tampoco se cachea",
                  "no-store" in respuesta.headers.get("Cache-Control", ""))

        # app.js debe poder pedirse siempre fresco (sin cache intermedia).
        async with sesion.get(f"{BASE}/app.js") as respuesta:
            check("app.js se sirve", respuesta.status == 200)

    print("\n" + "=" * 64)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 64)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
