"""Desactiva el codigo de acceso en el servidor que ya esta en marcha."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

PUERTO = 8765


def estado() -> dict:
    return json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{PUERTO}/healthz", timeout=5).read().decode())


print("Estado antes:")
try:
    print("  ", estado())
except Exception as exc:
    print("   no responde:", exc)
    raise SystemExit(1)

peticion = urllib.request.Request(
    f"http://127.0.0.1:{PUERTO}/api/auth",
    data=json.dumps({"required": False}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
try:
    respuesta = json.loads(urllib.request.urlopen(peticion, timeout=5).read().decode())
    print("Respuesta:", respuesta)
except urllib.error.HTTPError as exc:
    print("Fallo:", exc.code, exc.read().decode()[:120])
    raise SystemExit(1)

print("Estado despues:")
print("  ", estado())
