"""
Aprendizaje del tacto: el servidor se adapta a como usas el puntero.

No hace falta un modelo grande: con unas pocas medias exponenciales basta. La
idea es reconocer dos cosas al vuelo, mientras mueves el dedo:

  - que te has **pasado**: despues de un movimiento largo haces uno corto en
    sentido contrario (una correccion);
  - que te has **quedado corto**: encadenas movimientos largos en el mismo
    sentido sin corregir.

Con el equilibrio entre las dos se calcula una **ganancia** (0,6x a 1,9x) que se
aplica al movimiento del puntero. Se aprende **por aplicacion**, de modo que en
el navegador puede ir fina y en un juego mas rapida.

Dos reglas de sentido comun:

  - El ajuste manual del usuario manda: la ganancia es un multiplicador sobre lo
    que elija el, nunca lo sustituye.
  - El aprendizaje es lento y acotado: preferimos quedarnos cortos que dar un
    salto raro en mitad de un movimiento.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("remotepad")

# Archivo donde se recuerda lo aprendido (no se versiona).
LEARNING_FILE = Path(
    os.environ.get("REMOTEPAD_LEARNING")
    or (Path(__file__).resolve().parent / "learning.json")
)

# Una "rafaga" de movimiento termina tras este tiempo sin moverse.
BURST_GAP = 0.12
# Movimiento (px) a partir del cual una rafaga se considera "larga".
LARGA = 26.0
# Movimiento (px) por debajo del cual una rafaga cuenta como "correccion".
CORTA = 14.0
# Cuanto se recuerda: las cuentas se desvanecen un poco en cada rafaga.
MEMORIA = 0.97
# Limites de la ganancia aprendida.
MIN_GANANCIA = 0.6
MAX_GANANCIA = 1.9
# Cuanto pesa el desequilibrio en la ganancia (1.0 = todo el rango).
FUERZA = 0.9
# Rafagas evaluadas antes de fiarse de lo aprendido.
MIN_MUESTRAS = 6
# Tope de aplicaciones recordadas (las sobrantes se olvidan).
MAX_APPS = 40


class PerfilTacto:
    """Lo aprendido para una aplicacion (o para el uso en general)."""

    __slots__ = ("excesos", "defectos", "muestras")

    def __init__(self) -> None:
        self.excesos = 0.0     # correcciones por pasarse
        self.defectos = 0.0    # continuaciones por quedarse corto
        self.muestras = 0      # rafagas evaluadas (para no fiarse al principio)

    def ganancia(self) -> float:
        if self.muestras < MIN_MUESTRAS:
            return 1.0
        total = self.excesos + self.defectos
        if total <= 0:
            return 1.0
        # -1 = solo se pasa, +1 = solo se queda corto.
        equilibrio = (self.defectos - self.excesos) / total
        return max(MIN_GANANCIA, min(MAX_GANANCIA, 1.0 + equilibrio * FUERZA))

    def como_dict(self) -> dict:
        return {
            "excesos": round(self.excesos, 2),
            "defectos": round(self.defectos, 2),
            "muestras": self.muestras,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "PerfilTacto":
        perfil = cls()
        try:
            perfil.excesos = max(0.0, float(datos.get("excesos", 0.0)))
            perfil.defectos = max(0.0, float(datos.get("defectos", 0.0)))
            perfil.muestras = max(0, int(datos.get("muestras", 0)))
        except (TypeError, ValueError):
            pass
        return perfil


class AprendizTacto:
    """Analiza el flujo de movimientos y deduce la ganancia que te va bien."""

    def __init__(self) -> None:
        self.activo = True
        self._perfiles: dict[str, PerfilTacto] = {}
        self._app = ""
        self._burst = [0.0, 0.0]
        self._ultimo = 0.0
        self._anterior: Optional[tuple[float, float]] = None
        self.cargar()

    # ------------------------------------------------------------- perfiles
    def ubicar(self, app: str) -> None:
        """Le dice en que aplicacion estas (para los perfiles por aplicacion)."""
        self._app = app or ""

    def perfil(self, app: Optional[str] = None) -> PerfilTacto:
        clave = (app if app is not None else self._app) or "general"
        perfil = self._perfiles.get(clave)
        if perfil is None:
            perfil = PerfilTacto()
            self._perfiles[clave] = perfil
            self._recortar()
        return perfil

    def _recortar(self) -> None:
        """Si hay demasiadas aplicaciones, se olvidan las menos usadas."""
        if len(self._perfiles) <= MAX_APPS:
            return
        ordenadas = sorted(
            self._perfiles.items(), key=lambda par: par[1].muestras, reverse=True
        )
        self._perfiles = dict(ordenadas[:MAX_APPS])

    # ------------------------------------------------------------- ganancia
    def ganancia(self) -> float:
        if not self.activo:
            return 1.0
        return self.perfil().ganancia()

    # ------------------------------------------------------------ aprender
    def alimentar(self, dx: float, dy: float, ahora: Optional[float] = None) -> None:
        """Le da un movimiento ya aplicado, en pixeles."""
        if not self.activo:
            return
        momento = time.monotonic() if ahora is None else ahora
        if momento - self._ultimo > BURST_GAP:
            self._cerrar_rafaga()
        self._burst[0] += dx
        self._burst[1] += dy
        self._ultimo = momento

    def _cerrar_rafaga(self) -> None:
        bx, by = self._burst
        self._burst = [0.0, 0.0]
        distancia = math.hypot(bx, by)
        if distancia < 1.0:
            return
        anterior = self._anterior
        self._anterior = (bx, by)
        if anterior is None:
            return
        ax, ay = anterior
        larga_antes = math.hypot(ax, ay)
        if larga_antes < 1.0:
            return
        # Coseno entre las dos rafagas: -1 = sentido contrario, +1 = el mismo.
        coseno = (ax * bx + ay * by) / (larga_antes * distancia)

        perfil = self.perfil()
        if larga_antes >= LARGA and distancia <= CORTA and coseno < -0.4:
            # Se paso y lo corrigio.
            perfil.excesos = perfil.excesos * MEMORIA + 1.0
            perfil.defectos *= MEMORIA
            perfil.muestras += 1
        elif larga_antes >= LARGA and distancia >= LARGA and coseno > 0.4:
            # Siguio empujando en el mismo sentido: se quedo corto.
            perfil.defectos = perfil.defectos * MEMORIA + 1.0
            perfil.excesos *= MEMORIA
            perfil.muestras += 1

    # -------------------------------------------------------------- estado
    def estado(self) -> dict:
        perfil = self.perfil()
        return {
            "activo": self.activo,
            "app": self._app,
            "ganancia": round(self.ganancia(), 2),
            "excesos": round(perfil.excesos, 1),
            "defectos": round(perfil.defectos, 1),
            "muestras": perfil.muestras,
            "apps": {
                nombre: round(p.ganancia(), 2)
                for nombre, p in sorted(self._perfiles.items())
            },
        }

    def activar(self, activo: bool) -> None:
        self.activo = bool(activo)

    def reiniciar(self) -> None:
        self._perfiles.clear()
        self._burst = [0.0, 0.0]
        self._anterior = None
        self._ultimo = 0.0
        self.guardar()

    # ------------------------------------------------------------ persistir
    def cargar(self) -> None:
        try:
            datos = json.loads(LEARNING_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            log.warning("No se pudo leer %s (%s): se aprende de cero",
                        LEARNING_FILE.name, exc)
            return
        if not isinstance(datos, dict):
            return
        self.activo = bool(datos.get("activo", True))
        perfiles = datos.get("perfiles")
        if isinstance(perfiles, dict):
            for nombre, valores in perfiles.items():
                if isinstance(valores, dict):
                    self._perfiles[str(nombre)] = PerfilTacto.desde_dict(valores)

    def guardar(self) -> None:
        datos = {
            "activo": self.activo,
            "perfiles": {
                nombre: perfil.como_dict()
                for nombre, perfil in self._perfiles.items()
            },
        }
        try:
            LEARNING_FILE.write_text(json.dumps(datos, indent=2) + "\n",
                                     encoding="utf-8")
        except Exception as exc:
            log.debug("No se pudo guardar el aprendizaje: %s", exc)
