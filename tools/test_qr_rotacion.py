"""
Comprueba que el codigo escaneado NO deja de valer por la rotacion.

Antes fallaba: si el panel renovaba el codigo justo mientras el celular lo
estaba escaneando, el canje llegaba con el codigo anterior y se rechazaba.

Ahora:
  - el codigo anterior sigue valiendo unos segundos (margen de gracia);
  - el celular autorizado puede pedir un codigo nuevo y reintentar solo;
  - cada codigo se sigue usando una sola vez.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import aiohttp

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


def clave(texto: str) -> str:
    return re.search(r'"key":"([^"]+)"', texto).group(1)


async def main() -> int:
    print("La rotacion del QR ya no invalida el codigo escaneado")
    print("=" * 64)
    async with aiohttp.ClientSession() as sesion:
        async with sesion.get(f"{BASE}/qr") as r:
            visible = clave(await r.text())

        print("\n== Margen de gracia ==")
        # El panel renueva (como cada 3 minutos) y el celular canjea el anterior.
        async with sesion.post(f"{BASE}/qr/new") as r:
            await r.json()
        async with sesion.post(f"{BASE}/api/qr-login",
                               json={"key": visible}) as r:
            dato = await r.json()
            check("El codigo escaneado sigue valiendo tras la rotacion",
                  r.status == 200 and dato.get("ok") is True,
                  f"{r.status} {dato}")

        print("\n== Un solo uso ==")
        async with sesion.post(f"{BASE}/api/qr-login",
                               json={"key": visible}) as r:
            check("Ese mismo codigo no se puede reutilizar", r.status == 403,
                  f"codigo {r.status}")

        async with sesion.get(f"{BASE}/qr") as r:
            otra = clave(await r.text())
        async with sesion.post(f"{BASE}/api/qr-login", json={"key": otra}) as r:
            token = (await r.json()).get("token")
        async with sesion.post(f"{BASE}/api/qr-login", json={"key": otra}) as r:
            check("El codigo vigente tampoco se reutiliza", r.status == 403,
                  f"codigo {r.status}")

        print("\n== Recuperacion del celular ya autorizado ==")
        check("Tenemos un token de la prueba", bool(token))
        async with sesion.post(f"{BASE}/api/qr-refresh",
                               json={"token": token}) as r:
            datos = await r.json()
            check("Un dispositivo autorizado obtiene un QR nuevo",
                  r.status == 200 and bool(datos.get("key")), f"{r.status} {datos}")
            nueva = datos.get("key")
            check("El QR nuevo trae su URL y su matriz",
                  bool(datos.get("url")) and bool(datos.get("matrix")))
            check("Apunta a la red local, no a loopback",
                  "127.0.0.1" not in (datos.get("url") or "127.0.0.1"))

        async with sesion.post(f"{BASE}/api/qr-login", json={"key": nueva}) as r:
            segundo = await r.json()
            check("Y ese QR nuevo permite entrar", r.status == 200
                  and segundo.get("ok") is True, f"{r.status} {segundo}")

        print("\n== La recuperacion exige estar autorizado ==")
        async with sesion.post(f"{BASE}/api/qr-refresh",
                               json={"token": "token-inventado"}) as r:
            check("Un token inventado no obtiene QR", r.status == 403,
                  f"codigo {r.status}")
        async with sesion.post(f"{BASE}/api/qr-refresh", json={}) as r:
            check("Sin token tampoco", r.status == 403, f"codigo {r.status}")

        print("\n== Un codigo inventado se sigue rechazando ==")
        async with sesion.post(f"{BASE}/api/qr-login",
                               json={"key": "no-existe"}) as r:
            check("Se rechaza", r.status == 403, f"codigo {r.status}")

    print("\n" + "=" * 64)
    print(f"  {checks - failures} de {checks} correctas" if failures
          else f"  {checks} comprobaciones correctas")
    print("=" * 64)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
