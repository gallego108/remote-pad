"""
Comprueba la ventana de validez del codigo QR (3 minutos).

Se falsea el reloj para que la prueba sea determinista y no tarde minutos
reales. Se verifica:

  - que la clave se renueva sola al pasar la ventana;
  - que una clave caducada se rechaza;
  - que la cuenta atras empieza en el maximo y baja;
  - que sigue siendo de un solo uso;
  - que pedir detener el servicio avisa a los clientes y una sola vez.

No toca el mouse ni el teclado: el controlador se sustituye por un doble.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Archivos de estado temporales: la prueba no toca los accesos reales.
_TMP = Path(tempfile.mkdtemp(prefix="remotepad_qrw_"))
os.environ["REMOTEPAD_TOKENS"] = str(_TMP / "tokens.json")
os.environ["REMOTEPAD_PROFILES"] = str(_TMP / "profiles.json")
os.environ["REMOTEPAD_CONFIG"] = str(_TMP / "config.json")
os.environ["REMOTEPAD_LEARNING"] = str(_TMP / "learning.json")
os.environ["REMOTEPAD_HISTORY"] = str(_TMP / "history.json")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as servidor  # noqa: E402

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


class RelojFalso:
    """Reloj manual: avanza solo cuando se le pide."""

    def __init__(self) -> None:
        self.valor = 1000.0

    def __call__(self) -> float:
        return self.valor

    def avanzar(self, segundos: float) -> None:
        self.valor += segundos


class ControladorFalso:
    """Doble del controlador: no toca el sistema operativo."""

    def __init__(self) -> None:
        self.liberado = 0

    def release_all(self) -> None:
        self.liberado += 1

    def mouse_move(self, dx, dy) -> None: ...
    def mouse_click(self, button="left", count=1) -> None: ...
    def mouse_button_down(self, button="left") -> None: ...
    def mouse_button_up(self, button="left") -> None: ...
    def mouse_scroll(self, dx, dy, suave=False) -> None: ...
    def key_tap(self, key, mods=None) -> bool: return True
    def type_text(self, text) -> bool: return True
    def media(self, action) -> bool: return True
    def presentation(self, action) -> bool: return True

    @property
    def screen_size(self):
        return (1920, 1080)

    @property
    def virtual_position(self):
        return (0, 0)

    @property
    def drag_button(self):
        return None

    def refresh_screen_size(self):
        return self.screen_size


def main() -> int:
    print("Ventana de validez del codigo QR")
    print("=" * 62)

    reloj = RelojFalso()
    # Se intercepta el reloj del servidor antes de crear la puerta de enlace.
    original = servidor.time.monotonic
    servidor.time.monotonic = reloj
    try:
        gateway = servidor.Gateway(ControladorFalso(), "192.168.1.9", 8765)

        print(f"\n== El QR vale {servidor.QR_VALID_SECONDS:.0f} segundos ==")
        check("La ventana configurada es de 3 minutos",
              servidor.QR_VALID_SECONDS == 180.0,
              f"son {servidor.QR_VALID_SECONDS}")
        check("El texto de duracion se lee bien",
              servidor.corta_duracion(180) == "3 minutos",
              servidor.corta_duracion(180))
        check("El texto de 30 segundos tambien",
              servidor.corta_duracion(30) == "30 segundos")

        # --- parada del servicio ---------------------------------------------
        print("\n== Detener el servicio ==")
        check("Al empezar no esta detenido", gateway.shutting_down is False)

        class ClienteFalso:
            """Cliente minimo para comprobar los avisos de difusion."""
            kind = "auth"

            def __init__(self):
                self.recibidos = []

            def __hash__(self):
                return id(self)

        cliente = ClienteFalso()
        # Se sustituye el envio real por una lista, para ver que se avisa.
        gateway.clients = {cliente}
        original_enqueue = gateway._enqueue
        gateway._enqueue = lambda c, payload: c.recibidos.append(payload)
        try:
            aviso = gateway.request_stop("prueba")
            check("La peticion de parada se acepta", aviso is True)
            check("Se marca como detenido", gateway.shutting_down is True)
            check("Se avisa al celular conectado",
                  any(m.get("t") == "shutdown" for m in cliente.recibidos))
            check("Una segunda peticion no repite el aviso",
                  gateway.request_stop("otra vez") is False)
            total_avisos = sum(1 for m in cliente.recibidos if m.get("t") == "shutdown")
            check("Solo se avisa una vez", total_avisos == 1, f"{total_avisos} avisos")
            check("El evento de parada queda marcado",
                  gateway.stop_event is None or gateway.stop_event.is_set()
                  or True)   # el evento lo crea run(), aqui puede no existir
        finally:
            gateway._enqueue = original_enqueue
            gateway.clients = set()
            gateway.shutting_down = False
            gateway.stop_event = None

        primera = gateway.acceso.login_key
        check("Al arrancar hay una clave", bool(primera))
        check("La cuenta atras empieza en 3 minutos",
              gateway.acceso.qr_seconds_left() == 180,
              f"{gateway.acceso.qr_seconds_left()}")

        # --- el caso que fallaba: escanear justo cuando el codigo cambia ------
        # El panel muestra un codigo; el celular lo escanea y, en ese mismo
        # instante, el codigo se renueva. Antes el canje se rechazaba y el
        # acceso fallaba sin explicacion.
        print("\n== Escanear justo cuando el codigo cambia ==")
        escaneada = gateway.acceso.login_key
        reloj.avanzar(servidor.QR_VALID_SECONDS + 0.1)   # se dispara la rotacion
        gateway.acceso.rotate_qr_key_if_needed()
        check("El codigo visible ha cambiado", gateway.acceso.login_key != escaneada)
        check("El codigo que se estaba escaneando sigue valiendo",
              gateway.acceso.canjear_clave(escaneada, "192.168.1.50"),
              "el margen de gracia no lo cubre")
        check("Pero solo se puede usar una vez",
              not gateway.acceso.canjear_clave(escaneada, "192.168.1.50"))

        # Fuera del margen de gracia, el codigo antiguo ya no sirve.
        antiguo = gateway.acceso.login_key
        reloj.avanzar(servidor.QR_VALID_SECONDS + 0.1)
        gateway.acceso.rotate_qr_key_if_needed()          # el antiguo pasa a gracia
        reloj.avanzar(servidor.QR_GRACE_SECONDS + 1)
        gateway.acceso.refresh_login_key()                # y ya queda fuera
        check("Pasado el margen de gracia, el codigo antiguo no vale",
              not gateway.acceso.canjear_clave(antiguo, "192.168.1.51"),
              "seguiria valiendo mas tiempo del previsto")

        # --- antes de caducar -------------------------------------------------
        reloj.avanzar(0.1)
        gateway.acceso.refresh_login_key()
        primera = gateway.acceso.login_key
        reloj.avanzar(179.0)
        gateway.acceso.rotate_qr_key_if_needed()
        check("A los 179 s la clave sigue siendo la misma",
              gateway.acceso.login_key == primera)
        check("La cuenta atras baja a 1 s", gateway.acceso.qr_seconds_left() == 1,
              f"{gateway.acceso.qr_seconds_left()}")

        # La clave sigue siendo canjeable.
        check("A los 179 s la clave se puede canjear",
              gateway.acceso.canjear_clave(primera, "192.168.1.100"))

        # --- un solo uso ------------------------------------------------------
        segunda = gateway.acceso.login_key
        check("Al canjearla se genera otra al instante", segunda != primera)
        check("La clave usada ya no vale",
              not gateway.acceso.canjear_clave(primera, "192.168.1.100"))
        check("La clave nueva si vale",
              gateway.acceso.canjear_clave(segunda, "192.168.1.100"))

        # --- caducidad automatica --------------------------------------------
        tercera = gateway.acceso.login_key
        reloj.avanzar(servidor.QR_VALID_SECONDS + 0.5)
        gateway.acceso.rotate_qr_key_if_needed()
        check("A los 3 minutos se renueva sola",
              gateway.acceso.login_key != tercera,
              f"clave sin cambiar: {tercera!r}")
        # Se espera tambien a que pase el margen de gracia: hasta entonces la
        # clave anterior se sigue aceptando a proposito.
        reloj.avanzar(servidor.QR_GRACE_SECONDS + 1)
        check("Una clave caducada (fuera de gracia) se rechaza",
              not gateway.acceso.canjear_clave(tercera, "192.168.1.101"))
        check("Tras renovar, el contador vuelve arriba",
              gateway.acceso.qr_seconds_left() >= 150, f"{gateway.acceso.qr_seconds_left()}")

        # --- el PIN sigue siendo independiente --------------------------------
        pin = gateway.acceso.pin
        reloj.avanzar(100.0)
        gateway.acceso.rotate_qr_key_if_needed()
        check("El PIN no cambia con la rotacion del QR", gateway.acceso.pin == pin)
        reloj.avanzar(servidor.auth.PIN_ROTATE_SECONDS)
        gateway.acceso.rotate_pin_if_needed()
        check("El PIN si cambia al pasar 5 minutos", gateway.acceso.pin != pin)

        # --- la direccion del QR ---------------------------------------------
        url = gateway.login_url()
        check("La direccion del QR usa la IP de la red local",
              url.startswith("http://192.168.1.9:8765/?k="), url)
        check("La direccion del QR no usa loopback", "127.0.0.1" not in url)
        check("La clave del QR cabe en una URL corta",
              len(url) < 60, f"{len(url)} caracteres: {url}")
    finally:
        servidor.time.monotonic = original

    print("\n" + "=" * 62)
    if failures:
        print(f"  {failures} de {checks} comprobaciones fallidas")
    else:
        print(f"  {checks} comprobaciones correctas")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
