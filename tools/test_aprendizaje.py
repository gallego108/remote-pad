"""
Pruebas del aprendizaje del tacto (sensibilidad adaptativa y perfiles por app).

  A) Si te pasas y corriges, la ganancia BAJA.
  B) Si te quedas corto, la ganancia SUBE.
  C) Con uso equilibrado se queda cerca de 1.
  D) Desactivado no cambia nada.
  E) Cada aplicacion tiene su propio perfil.
  F) Lo aprendido se guarda y se recupera del disco.

No hace falta servidor: se prueba el modulo `learning` directamente, con
movimientos simulados.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"

# Archivo aparte: las pruebas no tocan el aprendizaje real del usuario.
_TEMPORAL = Path(os.environ.get("TEMP", ".")) / "remotepad_learning_test.json"
os.environ["REMOTEPAD_LEARNING"] = str(_TEMPORAL)

sys.path.insert(0, str(SERVIDOR))

import learning  # noqa: E402

failures = 0
checks = 0


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condicion else 'FALLO'}] {nombre}"
          + (f"  {detalle}" if detalle and not condicion else ""))
    if not condicion:
        failures += 1


def rafaga(aprendiz, t: float, dx: float, dy: float, n: int = 3) -> float:
    """Simula una rafaga de n movimientos seguidos y su pausa posterior."""
    for _ in range(n):
        t += 0.016
        aprendiz.alimentar(dx, dy, t)
    t += 0.2
    aprendiz.alimentar(0.0, 0.0, t)      # la pausa cierra la rafaga
    return t


def nuevo(app: str = "") -> "learning.AprendizTacto":
    if _TEMPORAL.exists():
        _TEMPORAL.unlink()
    aprendiz = learning.AprendizTacto()
    aprendiz.activar(True)
    aprendiz.reiniciar()
    aprendiz.ubicar(app)
    return aprendiz


def main() -> int:
    print("Aprendizaje del tacto")
    print("=" * 62)

    print("\n== A) Te pasas y corriges -> la ganancia baja ==")
    aprendiz = nuevo()
    t = 0.0
    for _ in range(10):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)      # rafaga larga (+45 px)
        t = rafaga(aprendiz, t, -6.0, 0.0, 2)      # correccion corta (-12 px)
    ganancia = aprendiz.ganancia()
    check("Detecta las correcciones por exceso", aprendiz.perfil().excesos > 3,
          f"excesos={aprendiz.perfil().excesos:.1f}")
    check("Y baja la ganancia", ganancia < 0.9, f"ganancia={ganancia:.2f}")

    print("\n== B) Te quedas corto -> la ganancia sube ==")
    aprendiz = nuevo()
    t = 0.0
    for _ in range(20):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)      # rafagas seguidas iguales
    ganancia = aprendiz.ganancia()
    check("Detecta que te quedas corto", aprendiz.perfil().defectos > 3,
          f"defectos={aprendiz.perfil().defectos:.1f}")
    check("Y sube la ganancia", ganancia > 1.2, f"ganancia={ganancia:.2f}")

    print("\n== C) Uso equilibrado -> cerca de 1 ==")
    aprendiz = nuevo()
    t = 0.0
    for _ in range(8):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)
        t = rafaga(aprendiz, t, -6.0, 0.0, 2)
    for _ in range(8):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)
    ganancia = aprendiz.ganancia()
    check("Se queda en torno a 1", 0.85 <= ganancia <= 1.25, f"ganancia={ganancia:.2f}")

    print("\n== D) Desactivado no cambia nada ==")
    aprendiz = nuevo()
    aprendiz.activar(False)
    t = 0.0
    for _ in range(20):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)
    check("La ganancia es 1 con el aprendizaje apagado",
          aprendiz.ganancia() == 1.0, f"ganancia={aprendiz.ganancia():.2f}")

    print("\n== E) Los perfiles son por aplicacion ==")
    aprendiz = nuevo()
    aprendiz.ubicar("juego")
    t = 0.0
    for _ in range(20):
        t = rafaga(aprendiz, t, 15.0, 0.0, 3)      # en el juego te quedas corto
    en_juego = aprendiz.ganancia()
    aprendiz.ubicar("navegador")
    en_navegador = aprendiz.ganancia()
    check("La aplicacion activa es la que se le dice", aprendiz.estado()["app"] == "navegador")
    check("El juego tiene su ganancia aprendida", en_juego > 1.2, f"{en_juego:.2f}")
    check("Y el navegador empieza neutro (no se contagia)",
          abs(en_navegador - 1.0) < 0.01, f"{en_navegador:.2f}")
    check("El estado lista las aplicaciones", "juego" in aprendiz.estado()["apps"])

    print("\n== F) Se guarda y se recupera ==")
    aprendiz.guardar()
    check("El archivo se ha escrito", _TEMPORAL.exists())
    otro = learning.AprendizTacto()
    otro.ubicar("juego")
    check("La ganancia del juego se recupera",
          abs(otro.ganancia() - en_juego) < 0.01, f"{otro.ganancia():.2f} != {en_juego:.2f}")
    otro.reiniciar()
    otro.ubicar("juego")
    check("Reiniciar vuelve a dejarlo neutro",
          abs(otro.ganancia() - 1.0) < 0.01, f"{otro.ganancia():.2f}")

    if _TEMPORAL.exists():
        _TEMPORAL.unlink()

    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
