"""
Pruebas del despertador (server/despertador.py).

Usa su propio puerto (8796), archivos temporales y un lanzador falso: no
arranca ningun servidor de verdad.

  - Con el puerto libre, lo ocupa y sirve la pagina "Encender" (y el
    manifest y los iconos para el icono del celular); nada mas.
  - Nadie mas puede abrir el mismo puerto mientras lo tiene.
  - Encender: sin acceso o con un acceso falso se rechaza; desde otro
    origen tambien; tras varios fallos bloquea; con un acceso valido (o con
    el acceso libre) arranca el servidor y suelta el puerto.
  - Soltar solo desde la propia PC; pedir_puerto() (lo que usa el servidor
    al arrancar a mano) lo libera.
  - Vigilancia: no vuelve a ocupar el puerto si alguien lo usa.

Uso:
    python tools/test_despertador.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="remotepad_despertador_"))
os.environ["REMOTEPAD_TOKENS"] = str(_TMP / "tokens.json")
os.environ["REMOTEPAD_CONFIG"] = str(_TMP / "config.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import auth  # noqa: E402
import despertador as modulo  # noqa: E402

PUERTO = 8796
BASE = f"http://127.0.0.1:{PUERTO}"
failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def pedir(ruta: str, datos: dict | None = None, origen: str | None = None):
    cabeceras = {"Content-Type": "application/json"}
    if origen:
        cabeceras["Origin"] = origen
    peticion = urllib.request.Request(
        BASE + ruta, data=None if datos is None else json.dumps(datos).encode(),
        headers=cabeceras, method="GET" if datos is None else "POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=3) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def esperar(condicion, segundos: float = 3.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return condicion()


def main() -> int:
    lanzados = []
    d = modulo.Despertador(PUERTO, "127.0.0.1", lanzar=lambda: lanzados.append(time.time()))

    print("\n== Ocupar el puerto ==")
    check("El puerto empieza libre", not modulo.puerto_ocupado(PUERTO))
    check("Lo ocupa", d.ocupar() and modulo.puerto_ocupado(PUERTO))
    estado, cabeceras, cuerpo = pedir("/")
    check("Sirve la pagina de Encender", estado == 200 and b"Encender RemotePad" in cuerpo)
    check("Con la cabecera del despertador", cabeceras.get(modulo.CABECERA) == "1")
    estado, _, cuerpo = pedir(modulo.RUTA_ESTADO)
    check("Estado en JSON", estado == 200 and json.loads(cuerpo).get("despertador") is True)
    check("Manifest e icono (para el icono del celular)",
          pedir("/manifest.webmanifest")[0] == 200 and pedir("/icon-192.png")[0] == 200)
    check("Nada mas: app.js no se sirve", pedir("/app.js")[0] == 404)
    check("Ni rutas raras", pedir("/../server/tokens.json")[0] == 404)
    otro = socket.socket()
    try:
        otro.bind(("127.0.0.1", PUERTO))
        pudo = True
    except OSError:
        pudo = False
    finally:
        otro.close()
    check("Nadie mas puede abrir el mismo puerto", not pudo)

    print("\n== Encender ==")
    estado, _, cuerpo = pedir(modulo.RUTA_ENCENDER, {})
    check("Sin acceso se rechaza", estado == 403 and not lanzados, cuerpo[:80])
    estado, _, _ = pedir(modulo.RUTA_ENCENDER, {"token": "inventado"})
    check("Con un acceso falso se rechaza", estado == 403 and not lanzados)
    token, _ = auth.Dispositivos().emitir("Celular de prueba", "127.0.0.1")
    estado, _, _ = pedir(modulo.RUTA_ENCENDER, {"token": token}, origen="http://malo.example")
    check("Desde otro origen se rechaza", estado == 403 and not lanzados)
    estado, _, cuerpo = pedir(modulo.RUTA_ENCENDER, {"token": token},
                              origen=f"http://127.0.0.1:{PUERTO}")
    check("Con un acceso valido responde ok", estado == 200 and json.loads(cuerpo).get("ok"))
    check("Arranca el servidor", esperar(lambda: len(lanzados) == 1))
    check("Y suelta el puerto", esperar(lambda: not modulo.puerto_ocupado(PUERTO)))
    d.vigilar_una_vez()
    check("No lo vuelve a ocupar mientras el servidor arranca", not d.escuchando)

    print("\n== Bloqueo por fallos ==")
    d._cedido_en = 0.0
    d.ocupar()
    for _ in range(modulo.MAX_FALLOS):
        pedir(modulo.RUTA_ENCENDER, {"token": "x"})
    estado, _, _ = pedir(modulo.RUTA_ENCENDER, {"token": token})
    check(f"Tras {modulo.MAX_FALLOS} fallos, bloquea aunque el acceso sea bueno",
          estado == 429 and len(lanzados) == 1)
    d._fallos.clear()

    print("\n== Acceso libre ==")
    auth.save_config({"auth_required": False})
    estado, _, _ = pedir(modulo.RUTA_ENCENDER, {})
    check("Con el acceso libre no hace falta acceso", estado == 200)
    check("Y arranca", esperar(lambda: len(lanzados) == 2))
    auth.save_config({"auth_required": True})
    esperar(lambda: not modulo.puerto_ocupado(PUERTO))

    print("\n== Soltar y vigilar ==")
    d._cedido_en = 0.0
    d.vigilar_una_vez()
    check("Vigilancia: con el puerto libre lo vuelve a ocupar", d.escuchando)
    check("pedir_puerto() lo libera (servidor arrancado a mano)",
          modulo.pedir_puerto(PUERTO, False) and not modulo.puerto_ocupado(PUERTO))
    check("pedir_puerto() sin despertador devuelve False",
          modulo.pedir_puerto(PUERTO, False, espera=0.5) is False)
    ocupante = socket.socket()
    ocupante.bind(("127.0.0.1", PUERTO))
    ocupante.listen(1)
    try:
        d._cedido_en = 0.0
        d.vigilar_una_vez()
        check("Si alguien usa el puerto (el servidor), no lo toca", not d.escuchando)
    finally:
        ocupante.close()
    check("Soltar solo se acepta desde la PC", modulo.es_local("127.0.0.1")
          and not modulo.es_local("192.168.1.20"))

    d.parar()
    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
