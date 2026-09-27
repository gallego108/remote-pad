"""Muestra los servidores de RemotePad en marcha y su estado de acceso."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request

salida = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                        timeout=30).stdout
puertos = {}
for linea in salida.splitlines():
    if "LISTENING" not in linea:
        continue
    coincide = re.search(r":(\d{4})\s", linea)
    if not coincide:
        continue
    puerto = int(coincide.group(1))
    if 8700 <= puerto <= 8899:
        puertos[puerto] = linea.split()[-1]

if not puertos:
    print("  No hay ningun servidor entre los puertos 8700 y 8899.")
    print("  Eso significa que RemotePad NO esta en marcha ahora mismo:")
    print("  el celular no puede conectar con nada.")
else:
    for puerto, pid in sorted(puertos.items()):
        print(f"  Puerto {puerto} (pid {pid}):")
        try:
            datos = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/healthz", timeout=4).read().decode())
            version = datos.get("version", "?")
            print(f"     version: {version}")
            print(f"     control de acceso: "
                  f"{'DESACTIVADO' if datos.get('auth_required') is False else 'activado'}")
        except Exception as exc:
            print(f"     no es RemotePad o no responde ({type(exc).__name__})")
