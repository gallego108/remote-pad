"""
Pruebas de server/rdp.py (estado del escritorio remoto de Windows).

No toca el registro ni la red: las lecturas se sustituyen por valores fijos.

  - Cada combinacion (activado / escucha) da el mensaje correcto.
  - Los datos (IP, puerto, nombre de la PC) llegan tal cual.
  - Sin registro (Windows Home o no Windows) no revienta: dice que no puede
    comprobarlo.

Uso:
    python tools/test_rdp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import rdp  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    if condition:
        print(f"[OK]    {name}")
    else:
        failures += 1
        print(f"[FALLO] {name} {detail}")


def estado(activado, escucha):
    return rdp.estado(
        "192.168.1.20", "MI-PC",
        leer=lambda: activado,
        escuchar=lambda: escucha,
    )


# ---------------------------------------------------------- combinaciones
activo = estado(True, True)
check("activado y escuchando: listo",
      activo["mensaje"].startswith("Listo"), activo["mensaje"])

sin_servicio = estado(True, False)
check("activado sin servicio: avisa de reiniciar",
      "reiniciar" in sin_servicio["mensaje"], sin_servicio["mensaje"])

desactivado = estado(False, False)
check("desactivado: indica la ruta de Configuracion",
      "Escritorio remoto" in desactivado["mensaje"], desactivado["mensaje"])

desconocido = estado(None, False)
check("sin registro: dice que no puede comprobarlo",
      "No se puede comprobar" in desconocido["mensaje"], desconocido["mensaje"])

# --------------------------------------------------------------- datos
check("la IP llega tal cual", activo["ip"] == "192.168.1.20", str(activo))
check("el puerto es el 3389 de RDP", activo["puerto"] == 3389, str(activo))
check("el nombre de la PC llega tal cual", activo["pc"] == "MI-PC", str(activo))
check("activado y escucha se devuelven como booleanos",
      activo["activado"] is True and activo["escucha"] is True, str(activo))
check("activado desconocido se devuelve como None",
      desconocido["activado"] is None, str(desconocido))

# ------------------------------------------------ lecturas reales (no fallan)
real = rdp.estado("10.0.0.1", "PRUEBA")
check("las lecturas reales devuelven un estado completo",
      set(real) == {"activado", "escucha", "ip", "puerto", "pc", "mensaje"},
      str(real))

print()
print(f"{checks - failures}/{checks} comprobaciones correctas")
sys.exit(1 if failures else 0)
