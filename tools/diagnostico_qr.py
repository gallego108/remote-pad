"""
Reproduce exactamente lo que hace el navegador del celular al escanear el QR.

Usa peticiones HTTP identicas a las del telefono y tambien las cabeceras y el
User-Agent de un Chrome movil, para detectar diferencias que no aparecen con un
cliente simple (por ejemplo, que el navegador pida otra ruta o que falle el
reparto de la peticion).

Se comprueba ademas que el servidor responde a TODAS las rutas que el cliente
puede pedir, incluida la del panel, y que el POST del canje llega.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import re
import sys
import urllib.parse

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# Cabeceras tipicas de Chrome en Android.
MOBILE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}

SUCCESS = 0
PROBLEMS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    global SUCCESS
    print(f"  [{'OK   ' if ok else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not ok else ""))
    if ok:
        SUCCESS += 1
    else:
        PROBLEMS.append(name)


def request(method: str, path: str, body: bytes | None = None,
            headers: dict | None = None) -> tuple[int, str, dict]:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=10)
    all_headers = dict(MOBILE_HEADERS)
    if headers:
        all_headers.update(headers)
    connection.request(method, path, body=body, headers=all_headers)
    response = connection.getresponse()
    data = response.read().decode("utf-8", "replace")
    head = dict(response.getheaders())
    connection.close()
    return response.status, data, head


def main() -> int:
    print(f"Simulando el navegador del celular contra {HOST}:{PORT}")
    print("=" * 66)

    print("\n== 1. La pagina principal ==")
    status, body, headers = request("GET", "/")
    report("GET / responde 200", status == 200, f"codigo {status}")
    report("El HTML trae la app", "RemotePad" in body)
    report("El HTML carga app.js", "app.js" in body)

    print("\n== 2. La app pide sus recursos ==")
    for asset in ("app.js", "styles.css", "manifest.webmanifest",
                  "icon-192.png", "sw.js"):
        status, _, _ = request("GET", "/" + asset)
        report(f"GET /{asset}", status == 200, f"codigo {status}")

    print("\n== 3. La ruta del canje del QR ==")
    # Esta es la que usa el cliente con fetch('api/qr-login').
    status, body, _ = request(
        "POST", "/api/qr-login",
        body=json.dumps({"key": "clave-inventada"}).encode(),
        headers={"Content-Type": "application/json", "Origin": f"http://{HOST}:{PORT}"},
    )
    report("POST /api/qr-login existe (no da 404/405)",
           status not in (404, 405), f"codigo {status}")
    report("Rechaza una clave invalida sin romperse",
           status == 403 and "ok" in body, f"codigo {status} cuerpo={body[:80]}")
    report("La respuesta es JSON valido", isinstance(json.loads(body), dict))

    print("\n== 4. Recorrido completo como el del telefono ==")
    # 1) Se pide el panel local para obtener la clave vigente.
    status, panel, _ = request("GET", "/qr")
    report("GET /qr responde", status == 200, f"codigo {status}")
    match = re.search(r'"key":"([^"]+)"', panel)
    report("El panel trae la clave", match is not None)
    if not match:
        return 1
    key = match.group(1)
    url = re.search(r'"url":"([^"]+)"', panel).group(1)
    print(f"       clave: {key}")
    print(f"       url:   {url}")

    # 2) El telefono abre esa url (path con ?k=...). Se comprueba que la
    #    pagina se sirve igual y que el parametro llega.
    path = urllib.parse.urlparse(url).path + "?" + urllib.parse.urlparse(url).query
    status, body, _ = request("GET", path)
    report("GET /?k=... sirve la app", status == 200, f"codigo {status}")

    # 3) El cliente hace fetch('api/qr-login') con esa clave.
    status, body, _ = request(
        "POST", "/api/qr-login",
        body=json.dumps({"key": key}).encode(),
        headers={"Content-Type": "application/json", "Origin": f"http://{HOST}:{PORT}"},
    )
    ok = status == 200
    report("El canje devuelve 200", ok, f"codigo {status} cuerpo={body[:120]}")
    token = None
    if ok:
        data = json.loads(body)
        token = data.get("token")
        report("El canje devuelve token", bool(token))

    # 4) Con ese token, el WebSocket debe aceptar la conexion.
    if token:
        asyncio.run(check_websocket(token))

    print("\n" + "=" * 66)
    if PROBLEMS:
        print("  Problemas encontrados:")
        for item in PROBLEMS:
            print("   -", item)
    else:
        print(f"  {SUCCESS} comprobaciones correctas: el recorrido del QR funciona")
    print("=" * 66)
    return 1 if PROBLEMS else 0


async def check_websocket(token: str) -> None:
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"http://{HOST}:{PORT}/ws") as ws:
            await ws.send_json({"a": "auth", "d": {"token": token}})
            message = json.loads((await ws.receive()).data)
            report("El token del QR autentica el WebSocket",
                   message.get("t") == "ok", f"{message}")
            # Y una accion real para confirmar que el control funciona.
            await ws.send_json({"a": "ping", "d": {"ts": 1}})
            pong = json.loads((await ws.receive()).data)
            report("El servidor responde a una accion tras el acceso",
                   pong.get("t") == "pong", f"{pong}")


if __name__ == "__main__":
    sys.exit(main())
