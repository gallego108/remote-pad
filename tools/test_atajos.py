"""
Pruebas de los atajos personalizados (accion "macro").

  A) Validacion: tipos, teclas, modificadores y limites.
  B) El controlador ejecuta los pasos en orden y respeta las esperas (con
     teclado simulado: no escribe nada en la PC).
  C) El servidor rechaza un atajo invalido y acepta uno valido (con pasos
     inofensivos: solo esperas).

Uso:
    python tools/test_atajos.py                      # A y B
    python tools/test_atajos.py --port 8791 --pin 123456
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="remotepad_atajos_"))
for variable, archivo in (("REMOTEPAD_TOKENS", "tokens.json"),
                          ("REMOTEPAD_PROFILES", "profiles.json"),
                          ("REMOTEPAD_CONFIG", "config.json"),
                          ("REMOTEPAD_LEARNING", "learning.json"),
                          ("REMOTEPAD_HISTORY", "history.json")):
    os.environ.setdefault(variable, str(_TMP / archivo))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import app as servidor  # noqa: E402
import controller as modulo_controlador  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def prueba_validacion() -> None:
    print("\n== A) Validacion ==")
    validar = servidor.validate_macro
    pasos, motivo = validar([
        {"tipo": "combo", "tecla": "T", "mods": ["ctrl", "shift"]},
        {"tipo": "espera", "ms": 250},
        {"tipo": "texto", "texto": "Hola, ¿qué tal? 👋"},
        {"tipo": "combo", "tecla": "d", "mods": ["win"]},
    ])
    check("Un atajo correcto se acepta", pasos is not None, motivo)
    if pasos:
        check("La tecla se normaliza a minusculas", pasos[0]["tecla"] == "t")
        check("'win' se traduce a la tecla del sistema", pasos[3]["mods"] == ["cmd"])
        check("El texto conserva acentos y emoji", pasos[2]["texto"] == "Hola, ¿qué tal? 👋")
    casos = [
        ("Sin pasos", []),
        ("No es una lista", {"tipo": "texto"}),
        ("Tipo desconocido", [{"tipo": "lanzar", "programa": "cmd.exe"}]),
        ("Tecla desconocida", [{"tipo": "combo", "tecla": "rm -rf"}]),
        ("Modificador desconocido", [{"tipo": "combo", "tecla": "a", "mods": ["hyper"]}]),
        ("Texto vacio", [{"tipo": "texto", "texto": ""}]),
        ("Texto demasiado largo", [{"tipo": "texto", "texto": "x" * 5000}]),
        ("Demasiados pasos", [{"tipo": "espera", "ms": 1}] * 31),
        ("Demasiada espera en total", [{"tipo": "espera", "ms": 3000}] * 4),
    ]
    for nombre, pasos_malos in casos:
        resultado, motivo = validar(pasos_malos)
        check(f"Se rechaza: {nombre}", resultado is None and bool(motivo))
    espera, _ = validar([{"tipo": "espera", "ms": 999_999}])
    check("Una espera enorme se recorta a 3 s", espera == [{"tipo": "espera", "ms": 3000}])


def prueba_ejecucion() -> None:
    print("\n== B) Ejecucion en orden ==")
    c = modulo_controlador.DesktopController.__new__(modulo_controlador.DesktopController)
    registro: list = []
    c.key_tap = lambda tecla, mods=None: registro.append(("combo", tecla, list(mods or []))) or True
    c.type_text = lambda texto: registro.append(("texto", texto)) or True
    inicio = time.monotonic()
    ok = c.run_macro([
        {"tipo": "combo", "tecla": "l", "mods": ["ctrl"]},
        {"tipo": "espera", "ms": 300},
        {"tipo": "texto", "texto": "remotepad"},
        {"tipo": "combo", "tecla": "enter", "mods": []},
    ])
    transcurrido = time.monotonic() - inicio
    check("Devuelve correcto", ok is True)
    check("Los pasos van en orden", registro == [
        ("combo", "l", ["ctrl"]), ("texto", "remotepad"), ("combo", "enter", []),
    ], str(registro))
    check("Respeta la espera", 0.28 <= transcurrido < 1.0, f"{transcurrido:.2f} s")

    registro.clear()
    c.key_tap = lambda tecla, mods=None: registro.append(tecla) or tecla != "x"
    ok = c.run_macro([{"tipo": "combo", "tecla": "x", "mods": []},
                      {"tipo": "combo", "tecla": "y", "mods": []}])
    check("Si un paso falla se sigue con el resto", registro == ["x", "y"])
    check("Y se informa del fallo", ok is False)


async def prueba_protocolo(puerto: int, pin: str) -> None:
    import aiohttp

    print("\n== C) Protocolo ==")

    async def pedir(ws, datos: dict) -> dict:
        await ws.send_str(json.dumps({"a": "macro", "d": datos}))
        while True:
            mensaje = json.loads((await ws.receive(timeout=10)).data)
            if mensaje.get("t") == "response" and mensaje.get("a") == "macro":
                return mensaje.get("d", {})

    async with aiohttp.ClientSession() as sesion:
        async with sesion.ws_connect(f"http://127.0.0.1:{puerto}/ws") as ws:
            await ws.send_str(json.dumps({"a": "auth", "d": {"pin": pin}}))
            check("Entra con el PIN",
                  json.loads((await ws.receive(timeout=5)).data).get("status") == "auth")
            malo = await pedir(ws, {"pasos": [{"tipo": "lanzar", "programa": "cmd"}]})
            check("Un atajo invalido devuelve el motivo", "error" in malo, str(malo))
            inicio = time.monotonic()
            bueno = await pedir(ws, {"pasos": [{"tipo": "espera", "ms": 200},
                                               {"tipo": "espera", "ms": 200}]})
            check("Un atajo valido se ejecuta", bueno.get("ok") is True, str(bueno))
            check("Con sus esperas", time.monotonic() - inicio >= 0.38)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--pin")
    args = parser.parse_args()
    print("Atajos personalizados")
    prueba_validacion()
    prueba_ejecucion()
    if args.port and args.pin:
        asyncio.run(prueba_protocolo(args.port, args.pin))
    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
