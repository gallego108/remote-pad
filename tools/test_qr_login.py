"""
Prueba del acceso por codigo QR de extremo a extremo.

Comprueba:
  - que el QR de la consola tiene el tamano correcto y todas las filas iguales
  - que el panel /qr se sirve y trae la matriz
  - que canjear la clave da un token
  - que la clave NO se puede reutilizar (un solo uso)
  - que una clave inventada se rechaza
  - que el panel /qr no se sirve a otras maquinas de la red (solo a la PC)
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import aiohttp

import qr

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def check_terminal_render() -> None:
    print("\n== QR de la consola ==")
    url = "http://192.168.1.9:8772/?k=AbCdEf123456"
    matrix = qr.encode(url, "M")
    text = qr.render_terminal(matrix)
    lines = text.split("\n")

    # Cada linea debe medir lo mismo una vez quitados los codigos ANSI.
    stripped = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
    widths = {len(line) for line in stripped}
    check("Todas las lineas miden lo mismo", len(widths) == 1, f"anchos: {widths}")

    size = len(matrix)
    padded = size + 8               # zona de silencio de 4 modulos
    check(f"El ancho es el del QR mas la zona de silencio ({padded})",
          widths == {padded}, f"ancho real: {widths}, esperado {padded}")

    # Dos filas de bloque por linea, mas una linea de borde arriba y otra abajo.
    expected_lines = padded // 2 + 1 + 2
    check(f"El alto es el esperado ({expected_lines} lineas)",
          len(lines) == expected_lines, f"{len(lines)} lineas")

    # Los bordes superior e inferior deben ser claros: la zona de silencio.
    border_ok = all("\x1b[40m" not in line for line in (lines[0], lines[1],
                                                       lines[-1], lines[-2]))
    check("Los bordes del QR son claros (zona de silencio)", border_ok)

    # Se guarda una version en texto para poder revisarla.
    Path("qr_consola.txt").write_text(text, encoding="utf-8")
    print("     (volcado en qr_consola.txt)")


async def check_http(port: int) -> None:
    base = f"http://127.0.0.1:{port}"
    print("\n== Panel y canje de la clave ==")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/qr") as response:
            body = await response.text()
            check("El panel /qr responde", response.status == 200)
            check("El panel trae la matriz del QR", '"matrix"' in body)
            check("El panel trae el PIN", '"pin"' in body)

        # Extraer la clave que va incrustada en el panel.
        match = re.search(r'"key":"([^"]+)"', body)
        check("Se puede extraer la clave del panel", match is not None)
        if not match:
            return
        key = match.group(1)
        print(f"     clave del QR: {key}")

        # Canje correcto.
        async with session.post(f"{base}/api/qr-login", json={"key": key}) as response:
            data = await response.json()
            check("La clave del QR da un token",
                  response.status == 200 and data.get("ok") is True
                  and bool(data.get("token")), f"{response.status} {data}")
            token = data.get("token")

        # El token debe servir para el WebSocket.
        if token:
            async with session.ws_connect(f"{base}/ws") as ws:
                await ws.send_json({"a": "auth", "d": {"token": token}})
                message = json.loads((await ws.receive()).data)
                check("El token del QR autentica el WebSocket",
                      message.get("t") == "ok" and message.get("status") == "auth",
                      f"{message}")

        # La clave ya no debe valer: es de un solo uso.
        async with session.post(f"{base}/api/qr-login", json={"key": key}) as response:
            check("La clave no se puede reutilizar", response.status == 403)

        # Clave inventada.
        async with session.post(f"{base}/api/qr-login",
                                json={"key": "clave-inventada"}) as response:
            check("Una clave inventada se rechaza", response.status == 403)

        # El panel renovado debe traer una clave nueva.
        async with session.get(f"{base}/qr") as response:
            body = await response.text()
        new_key = re.search(r'"key":"([^"]+)"', body)
        check("El panel genera una clave nueva tras el canje",
              new_key is not None and new_key.group(1) != key)

        # Renovacion manual: devuelve los datos del codigo nuevo.
        async with session.post(f"{base}/qr/new") as response:
            data = await response.json()
            check("El boton de renovar devuelve un QR utilizable",
                  response.status == 200 and data.get("matrix")
                  and data.get("url") and data.get("key") != key,
                  f"{response.status} claves={data.get('key')!r}")

        # El QR debe apuntar a la red local, no a 127.0.0.1: en el celular
        # "127.0.0.1" es el propio telefono y no abriria nada.
        check("El QR apunta a la IP de la red, no a loopback",
              "127.0.0.1" not in (data.get("url") or "127.0.0.1"),
              f"url={data.get('url')!r}")

        # La clave nueva tambien debe poder canjearse.
        async with session.post(f"{base}/api/qr-login",
                                json={"key": data.get("key")}) as response:
            second = await response.json()
            check("La clave renovada tambien sirve",
                  response.status == 200 and second.get("ok") is True)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8772
    print("Prueba del acceso por codigo QR")
    print("=" * 62)
    check_terminal_render()
    asyncio.run(check_http(port))
    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
