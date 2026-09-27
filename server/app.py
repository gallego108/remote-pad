"""
RemotePad - Servidor de la PC
=============================

Convierte tu celular en un touchpad remoto por WiFi local.

- Sirve la aplicacion web (PWA) que abre el celular.
- Recibe ordenes por WebSocket y controla el mouse/teclado del sistema.
- Protege el acceso con un PIN de 6 digitos que se muestra en esta consola y
  con un codigo QR que entra directo, sin escribir nada.

Ambos se regeneran automaticamente cada 5 minutos.

Uso:
    python app.py                 # puerto 8765
    python app.py --port 9000     # otro puerto
    python app.py --no-auth       # sin PIN (solo para pruebas)
    python app.py --no-qr         # sin codigo QR
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import html as html_lib
import ipaddress
import json
import logging
import math
import mimetypes
import os
import queue
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from aiohttp import WSMsgType, web

try:
    from controller import DesktopController
except ImportError as exc:  # pragma: no cover
    print("Falta el controlador del escritorio:", exc)
    print("Instala las dependencias con:  python -m pip install -r requirements.txt")
    raise SystemExit(1)

import qr
import learning

# --------------------------------------------------------------------- ajustes
WEB_ROOT = (Path(__file__).resolve().parent.parent / "web").resolve()
# Ajustes que se recuerdan entre arranques (por ahora, solo el codigo de acceso).
CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
# Accesos de los dispositivos ya autorizados: se guardan en disco para no tener
# que volver a pedir el PIN (ni el QR) cada vez que se reinicia el servidor.
# Las pruebas usan REMOTEPAD_TOKENS para no tocar el archivo real.
TOKENS_FILE = Path(
    os.environ.get("REMOTEPAD_TOKENS")
    or (Path(__file__).resolve().parent / "tokens.json")
)
# Preferencias de cada dispositivo (velocidad, gestos, etc.), para no tener que
# volver a ajustarlas: se guardan en el servidor, ligadas al acceso del celular.
PROFILES_FILE = Path(
    os.environ.get("REMOTEPAD_PROFILES")
    or (Path(__file__).resolve().parent / "profiles.json")
)
DEFAULT_PORT = 8765

PIN_ROTATE_SECONDS = 300.0   # cada cuanto cambia el PIN de seguridad
QR_VALID_SECONDS = 180.0     # cuanto vale cada codigo QR (3 minutos, un solo uso)

# Margen de gracia y renovacion de los codigos QR.
#
# Por que existe: el codigo visible cambia cada QR_VALID_SECONDS, y si alguien
# esta escaneando justo en ese momento, el codigo que acaba de leer dejaria de
# valer y el acceso fallaria. Con este margen se sigue aceptando el codigo
# anterior unos segundos despues de rotar, que es justo el tiempo que el canje
# puede llegar tarde por el retardo de la red o del navegador.
QR_GRACE_SECONDS = 20.0
QR_PRE_REFRESH_SECONDS = 20.0   # antelacion con que el panel pide el siguiente

# Sube al cambiar la parte web: sirve para comprobar en el celular que se esta
# ejecutando la version nueva y no una copia guardada. Debe coincidir con la
# constante REMOTEPAD_WEB de web/index.html: si no, la propia pagina fuerza una
# recarga (y avisa) para que el celular no se quede con JavaScript viejo.
APP_VERSION = "1.7.0"
TOKEN_TTL_SECONDS = 30 * 24 * 3600
ANSWER_TIMEOUT = 2.0
MAX_ACTIONS_PER_SECOND = 450
SCROLL_QUEUE_DELAY_MS = 40
# Anti-apagado: cada cuanto se mueve el raton 1 px para simular actividad.
KEEP_AWAKE_INTERVAL = 40.0

STATIC_EXTENSIONS = {
    ".html", ".css", ".js", ".json", ".webmanifest",
    ".png", ".jpg", ".svg", ".ico", ".txt",
}

# Subconjunto de acciones que pueden usar los "espectadores" (solo mirar).
VIEWER_ACTIONS = {"client_hello", "get_state", "refresh_pin", "ping", "pad_input"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("remotepad")


def now_ms() -> int:
    return int(time.time() * 1000)


def loop_time_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)


def new_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_login_key() -> str:
    """Clave corta y aleatoria que viaja dentro del enlace del codigo QR."""
    return secrets.token_urlsafe(9)


def clamp_number(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return max(low, min(high, number))


def load_config() -> dict:
    """
    Lee los ajustes guardados entre arranques.

    Si el archivo no existe o esta mal, se usan los valores por defecto: es
    preferible arrancar siempre que quedarse sin servidor por un JSON roto.
    """
    try:
        datos = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("No se pudo leer %s (%s): se usan los valores por defecto",
                    CONFIG_FILE.name, exc)
        return {}
    return datos if isinstance(datos, dict) else {}


def save_config(cambios: dict) -> None:
    """Guarda ajustes sin perder los que ya hubiera."""
    datos = load_config()
    datos.update(cambios)
    try:
        CONFIG_FILE.write_text(json.dumps(datos, indent=2) + "\n",
                               encoding="utf-8")
    except Exception as exc:
        log.warning("No se pudo guardar %s: %s", CONFIG_FILE.name, exc)


def load_tokens() -> dict:
    """
    Accesos de dispositivos que siguen valiendo, leidos de disco.

    Existen para que reiniciar el servidor NO obligue a todos los celulares a
    volver a escribir el PIN: el dispositivo guarda su token y entra solo. Si el
    archivo no esta o esta mal, se empieza de cero (solo se pedira el PIN).
    """
    try:
        datos = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("No se pudo leer %s (%s): se pedira el PIN de nuevo",
                    TOKENS_FILE.name, exc)
        return {}
    if not isinstance(datos, dict):
        return {}
    corte = time.time() - TOKEN_TTL_SECONDS
    vivos: dict = {}
    for token, creado in datos.items():
        try:
            cuando = float(creado)
        except (TypeError, ValueError):
            continue
        if cuando >= corte:
            vivos[str(token)] = cuando
    return vivos


def save_tokens(tokens: dict) -> None:
    """Guarda los accesos vigentes. Si falla, se sigue funcionando igual."""
    try:
        TOKENS_FILE.write_text(json.dumps(tokens, indent=2) + "\n",
                               encoding="utf-8")
    except Exception as exc:
        log.warning("No se pudieron guardar los accesos: %s", exc)


def load_profiles() -> dict:
    """Preferencias guardadas de cada dispositivo (por token)."""
    try:
        datos = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("No se pudo leer %s (%s): se usan los ajustes del celular",
                    PROFILES_FILE.name, exc)
        return {}
    return datos if isinstance(datos, dict) else {}


def save_profiles(perfiles: dict) -> None:
    """Guarda las preferencias de los dispositivos (best effort)."""
    try:
        PROFILES_FILE.write_text(json.dumps(perfiles, indent=2) + "\n",
                                 encoding="utf-8")
    except Exception as exc:
        log.warning("No se pudieron guardar los perfiles: %s", exc)


def local_ip() -> str:
    """IP de la PC dentro de la red local (la que debe abrir el celular)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except Exception:
        try:
            return str(socket.gethostbyname(socket.gethostname()))
        except Exception:
            return "127.0.0.1"


def is_private(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_private
    except ValueError:
        return False


# ------------------------------------------------------------------- una linea
BANNER = r"""
   ___                     _   ___         _
  | _ \ ___ _ __  ___ _ _ | |_| _ \__ _ __| |
  |   /| -_) '  \/ _ \ ' \|  _|  _/ _` / _` |
  |_|_\___|_|_|_\___/_||_|\__|_| \__,_\__,_|
"""

AVISO_SIN_ACCESO = r"""
  ####################################################################
  #  CONTROL DE ACCESO DESACTIVADO                                   #
  #  Cualquiera conectado a tu misma red WiFi puede mover el puntero, #
  #  hacer clic y escribir en esta PC, sin PIN ni codigo QR.          #
  #  Para volver a pedirlo: escribe  "auth on"  aqui y pulsa ENTER.   #
  #  (o pulsa el boton de Ajustes en el celular)                      #
  ####################################################################
"""


def corta_duracion(segundos: float) -> str:
    """Texto legible de una duracion: '30 segundos', '3 minutos'..."""
    if segundos < 60:
        return f"{int(segundos)} segundos"
    minutos = segundos / 60
    if minutos == int(minutos):
        return f"{int(minutos)} minutos"
    return f"{minutos:.1f} minutos"


def print_qr_block(host: str, port: int, login_key: str, when: str = "") -> None:
    """
    Dibuja el QR en la consola con su pie de informacion.

    Se usa tanto al arrancar como cada vez que la clave se renueva, para que
    el codigo que hay en pantalla nunca este caducado.
    """
    url = f"http://{host}:{port}/?k={login_key}"
    etiqueta = f"   ({when})" if when else ""
    print("=" * 58)
    print(f"   Escanea este QR y entra sin escribir nada:{etiqueta}")
    print()
    if qr.supports_color():
        try:
            print(qr.render_terminal(qr.encode(url, "M")))
        except Exception as exc:
            print(f"   (no se pudo dibujar el QR: {exc})")
    else:
        print("   (esta consola no admite color: usa el panel del navegador)")
    print()
    print(f"   Vale {corta_duracion(QR_VALID_SECONDS)} y se renueva solo: si tardas,")
    print("   aqui abajo aparece uno nuevo.")
    print("   ENTER = otro codigo ahora   ·   escribe q + ENTER = detener")
    print(f"   Panel siempre vigente:  http://127.0.0.1:{port}/qr")


def print_banner(host: str, port: int, pin: str, auth: bool,
                 login_key: str = "", show_qr: bool = True) -> None:
    line = "=" * 58
    print(BANNER)
    print(line)
    if auth:
        print(f"   PIN DE ACCESO  ->  {pin[:3]} {pin[3:]}")
        print("   (cambia automaticamente cada 5 minutos)")
    else:
        print("   CONTROL DE ACCESO DESACTIVADO")
        print("   El celular entra directo, sin PIN ni codigo QR.")
        print("   AVISO: cualquiera en tu misma WiFi puede manejar la PC.")
        print("   Para volver a pedirlo: escribe  auth on  y pulsa ENTER.")
    print(line)
    print("   Abre esta direccion en el navegador del celular:")
    print(f"       http://{host}:{port}")
    if host != "127.0.0.1":
        print(f"   Desde esta misma PC:  http://127.0.0.1:{port}")
    print("   (el celular debe estar en la MISMA red WiFi)")
    print()
    print("   SI EL CELULAR DICE 'no se puede conectar':")
    print("   es el Firewall de Windows. Ejecuta abrir-firewall.bat")
    print("   (una sola vez, pide permisos de administrador).")

    if show_qr and auth and login_key:
        print()
        print_qr_block(host, port, login_key)
    print(line)
    print("   Ctrl+C para detener el servidor.\n")


# ------------------------------------------------------------------- clientes
# eq=False: un dataclass normal genera __eq__, y entonces la clase deja de ser
# "hasheable". Aqui cada cliente se identifica por su objeto (se guardan en un
# set), asi que la identidad es justo lo que queremos.
@dataclass(eq=False)
class Client:
    ws: web.WebSocketResponse
    client_id: str
    kind: str = "auth"          # auth | viewer
    token: Optional[str] = None
    addr: str = "?"
    rate_used: int = 0
    rate_window: int = 0
    last_seen: float = field(default_factory=time.monotonic)
    send_queue: "deque[dict]" = field(default_factory=deque)
    send_task: Optional[asyncio.Task] = None


class LaserPointer:
    """
    Controla el proceso del puntero laser (`laser.py`).

    Se lanza solo la primera vez que se usa y se le manda la posicion por la
    entrada estandar. Si el sistema no puede abrirlo (por ejemplo, sin tkinter)
    la funcion simplemente no hace nada: el resto de la app sigue igual.
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    def _ensure(self) -> bool:
        if self._process is not None and self._process.poll() is None:
            return True
        script = Path(__file__).resolve().parent / "laser.py"
        try:
            self._process = subprocess.Popen(
                [sys.executable, str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as exc:
            log.warning("No se pudo abrir el puntero laser: %s", exc)
            self._process = None
            return False
        return True

    def point(self, x: float, y: float) -> bool:
        if not self._ensure() or self._process is None or self._process.stdin is None:
            return False
        try:
            self._process.stdin.write(f"{int(x)} {int(y)}\n")
            self._process.stdin.flush()
            return True
        except Exception:
            self._process = None
            return False

    def hide(self) -> None:
        if self._process is None or self._process.stdin is None:
            return
        try:
            self._process.stdin.write("off\n")
            self._process.stdin.flush()
        except Exception:
            self._process = None

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        except Exception:
            pass
        try:
            self._process.wait(timeout=2)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None


class Gateway:
    """Une el WebSocket con el control del escritorio."""

    def __init__(self, controller: DesktopController, host: str, port: int) -> None:
        self.controller = controller
        self.host = host
        self.port = port
        # IP que debe usar el celular (se ajusta al arrancar el servidor).
        self.lan_host = host if host not in ("0.0.0.0", "::") else local_ip()
        # Redibujo del QR en la consola (lo activa run() segun los argumentos).
        self.show_qr_console = False
        self.console_host = self.lan_host
        # Parada ordenada: la marca el boton del celular (o el comando de la
        # consola) y la espera run() para cerrar todo limpiamente.
        self.stop_event: Optional[asyncio.Event] = None
        self.shutting_down = False
        self._parada_pedida: Optional[str] = None

        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        # Con False, cualquiera de la red entra sin PIN ni QR: lo activan
        # --no-auth, el comando "auth off" de la consola o el boton de Ajustes.
        self.auth_required = True
        self.login_key = new_login_key()      # clave del enlace del codigo QR
        self.login_key_generated = self._pin_generated
        # Claves anteriores que se siguen aceptando unos segundos (margen de
        # gracia): (clave, momento de la rotacion, ya_usada).
        self._key_history: "deque[tuple[str, float, bool]]" = deque()
        self._key_failures: dict[str, list[float]] = {}
        # Accesos de dispositivos ya autorizados. Se leen de disco para que
        # reiniciar el servidor no obligue a volver a escribir el PIN.
        self._tokens: dict[str, float] = load_tokens()
        if self._tokens:
            log.info("Accesos recordados de %d dispositivo(s)", len(self._tokens))
        # Preferencias de cada dispositivo (por token).
        self._profiles: dict[str, dict] = load_profiles()
        self._pin_failures: dict[str, list[float]] = {}
        self.clients: set[Client] = set()
        # Puntero laser para presentaciones (se abre bajo demanda).
        self.laser = LaserPointer()
        # Anti-apagado: momento (monotonic) en que termina, y ultimo movimiento.
        self.keep_awake_until: Optional[float] = None
        self.keep_awake_last = 0.0
        # Aprendizaje del tacto: se adapta a como mueves el puntero, por app.
        self.learning = learning.AprendizTacto()
        self._app = ""
        self._app_check = 0.0
        self._learn_saved = 0.0

        self.executor = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="input"
        )
        # Colas de entrada: el bucle de animacion las consume a ritmo fijo.
        self._move_q: "queue.Queue[tuple[float, float]]" = queue.Queue()
        self._click_q: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._scroll_q: "deque[tuple[float, float]]" = deque()
        self._move_accum = [0.0, 0.0]
        self._scroll_accum = [0.0, 0.0]
        self._scroll_sent_at = 0.0
        self._idle_cleanup_done = False

    # -------------------------------------------------------------- PIN/token
    def request_stop(self, motivo: str = "") -> bool:
        """
        Pide detener el servidor.

        Solo la primera peticion hace efecto; las siguientes se ignoran (el
        cierre tarda un instante y pueden llegar varias). Devuelve True si esta
        peticion es la que inicia la parada.
        """
        if self.shutting_down:
            return False
        self.shutting_down = True
        log.info("Deteniendo RemotePad%s", f": {motivo}" if motivo else "")
        # Se avisa a los celulares conectados antes de cortar.
        self.broadcast({"t": "shutdown", "reason": motivo or "El servidor se ha detenido"})
        if self.stop_event is not None:
            self.stop_event.set()
        return True

    def rotate_pin_if_needed(self) -> None:
        if time.monotonic() - self._pin_generated < PIN_ROTATE_SECONDS:
            return
        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        log.info("Nuevo PIN de seguridad: %s", self.pin)
        self.broadcast({"t": "pin", "pin": self.pin})

    def rotate_qr_key_if_needed(self) -> None:
        """
        El codigo QR vale 3 minutos.

        Pasado ese tiempo se genera otro automaticamente, de modo que el panel
        de la PC siempre muestra un codigo vigente. El anterior NO se invalida
        de golpe: queda unos segundos en el margen de gracia por si el celular
        estaba escaneandolo justo en ese momento.
        """
        if self.shutting_down:
            return
        if not self.auth_required:
            return          # sin control de acceso el QR no hace falta
        if time.monotonic() - self.login_key_generated < QR_VALID_SECONDS:
            return
        self.refresh_login_key()

    def refresh_login_key(self, internal: bool = False) -> str:
        """
        Genera un QR nuevo.

        Si `internal` es False (rotacion automatica, boton del panel), la clave
        anterior pasa al margen de gracia: asi no falla un canje que llego
        tarde por unos segundos. Si es True, la rotacion viene de haber canjeado
        o reservado una clave, y entonces la anterior se descarta directamente
        (guardarla en el historial solo serviria para reutilizarla).
        """
        ahora = time.monotonic()
        if self.login_key and not internal:
            self._key_history.append((self.login_key, ahora, False))
        self._podar_historial(ahora)
        self.login_key = new_login_key()
        self.login_key_generated = ahora
        self.broadcast({"t": "qr_key", "key": self.login_key})
        return self.login_key

    def _podar_historial(self, ahora: Optional[float] = None) -> None:
        """Descarta las claves antiguas que ya pasaron el margen de gracia."""
        if ahora is None:
            ahora = time.monotonic()
        while self._key_history:
            clave, nacida, usada = self._key_history[0]
            if usada or (ahora - nacida) > QR_GRACE_SECONDS:
                self._key_history.popleft()
            else:
                break

    def _marcar_clave_usada(self, clave: str) -> None:
        """
        Invalida una clave ya canjeada, este en el historial o sea la vigente.

        Una clave usada no se conserva en el margen de gracia: si se guardara,
        un segundo intento con el mismo enlace volveria a encontrar la clave y
        habria que rechazarlo expresamente. Se descarta y punto.
        """
        self._key_history = deque(
            (c, t, u) for c, t, u in self._key_history if c != clave
        )
        if self.login_key == clave:
            self.refresh_login_key(internal=True)

    def reservar_clave_actual(self) -> str:
        """
        Entrega una clave nueva para un cliente ya autorizado (recuperacion).

        La clave vigente se marca como usada (para que el enlace que ya circulo
        no sirva) y se devuelve una NUEVA, que solo conoce este cliente: como
        no se muestra en ningun panel hasta que este la canjee, no hay carrera
        posible y el canje funciona siempre.
        """
        self._podar_historial()
        if self.login_key:
            self._marcar_clave_usada(self.login_key)
        else:
            self.refresh_login_key(internal=True)
        return self.login_key

    def qr_seconds_left(self) -> int:
        remaining = QR_VALID_SECONDS - (time.monotonic() - self.login_key_generated)
        return max(0, int(round(remaining)))

    def login_url(self) -> str:
        """
        Direccion que debe contener el QR.

        Tiene que ser la IP de la red local: 127.0.0.1 funcionaria solo en la
        propia PC, pero en el celular apuntaria a si mismo y no abriria nada.
        """
        return f"http://{self.lan_host}:{self.port}/?k={self.login_key}"

    def use_login_key(self, key: Any, addr: str = "?") -> Optional[str]:
        """
        Canjea la clave del QR por un token.

        Acepta la clave vigente y tambien las anteriores mientras esten dentro
        del margen de gracia: asi, si el codigo se renovo mientras el celular
        lo escaneaba, el acceso no falla. Cada clave sirve una sola vez.

        Con el control de acceso desactivado se entrega token sin mirar la
        clave: el QR no es necesario.
        """
        if not self.auth_required:
            return self.issue_token()
        if not key:
            return None

        attempts = [t for t in self._key_failures.get(addr, []) if time.time() - t < 300]
        self._key_failures[addr] = attempts
        if len(attempts) >= 10:
            return None

        candidata = str(key)
        usada = False

        if self.login_key and hmac.compare_digest(candidata, self.login_key):
            self._key_failures.pop(addr, None)
            self._marcar_clave_usada(candidata)
            return self.issue_token()

        # Margen de gracia: claves recien rotadas, aun sin usar.
        self._podar_historial()
        for anterior, _nacida, ya_usada in self._key_history:
            if hmac.compare_digest(candidata, anterior):
                usada = ya_usada
                break
        else:
            attempts.append(time.time())
            return None

        if usada:
            attempts.append(time.time())
            return None

        self._key_failures.pop(addr, None)
        self._marcar_clave_usada(candidata)
        return self.issue_token()

    def pin_seconds_left(self) -> int:
        remaining = PIN_ROTATE_SECONDS - (time.monotonic() - self._pin_generated)
        return max(0, int(remaining))

    def _prune_tokens(self) -> None:
        cutoff = time.time() - TOKEN_TTL_SECONDS
        vivos = {t: c for t, c in self._tokens.items() if c >= cutoff}
        if len(vivos) != len(self._tokens):
            self._tokens = vivos
            save_tokens(self._tokens)

    def token_is_valid(self, token: Optional[str]) -> bool:
        if not token:
            return False
        self._prune_tokens()
        for known in self._tokens:
            if hmac.compare_digest(known, token):
                return True
        return False

    def issue_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = time.time()
        self._prune_tokens()
        # Se guarda en disco: el dispositivo no tendra que volver a pedir el PIN
        # aunque el servidor se reinicie (hasta que caduque, 30 dias).
        save_tokens(self._tokens)
        return token

    def _too_many_failures(self, addr: str) -> bool:
        attempts = [t for t in self._pin_failures.get(addr, []) if time.time() - t < 300]
        self._pin_failures[addr] = attempts
        return len(attempts) >= 8

    def _register_failure(self, addr: str) -> None:
        self._pin_failures.setdefault(addr, []).append(time.time())

    def check_pin(self, pin: Any, addr: str = "?") -> bool:
        # Con el control de acceso desactivado entra cualquiera de la red: es
        # comodo para probar, pero cualquiera en tu WiFi puede manejar la PC.
        if not self.auth_required:
            return True
        if self._too_many_failures(addr):
            return False
        if hmac.compare_digest(str(pin or ""), self.pin):
            self._pin_failures.pop(addr, None)
            return True
        self._register_failure(addr)
        return False

    def set_auth_required(self, activo: bool, motivo: str = "") -> bool:
        """
        Activa o desactiva el codigo de acceso (PIN y QR) en caliente.

        Devuelve True si el estado ha cambiado. Al desactivarlo se avisa a los
        celulares conectados para que lo sepan, y al activarlo se avisa tambien
        para que no se queden creyendo que sigue libre.
        """
        if self.auth_required == activo:
            return False
        self.auth_required = activo
        # Se recuerda entre arranques: si lo quitas, sigue quitado al reiniciar.
        save_config({"auth_required": activo})
        if activo:
            # Se genera un PIN nuevo, para que no valga uno visto antes.
            self.pin = new_pin()
            self._pin_generated = time.monotonic()
            log.info("Control de acceso ACTIVADO%s (PIN %s)",
                     f" {motivo}".rstrip(), self.pin)
            self.broadcast({"t": "auth_mode", "required": True, "pin": self.pin})
        else:
            log.warning("Control de acceso DESACTIVADO%s: cualquiera en tu "
                        "WiFi puede manejar la PC", f" {motivo}".rstrip())
            self.broadcast({"t": "auth_mode", "required": False})
        return True

    def keep_pin_fresh(self) -> None:
        self.rotate_pin_if_needed()
        self.rotate_qr_key_if_needed()
        self._discard_stale()

    def keep_awake_tick(self) -> None:
        """
        Anti-apagado: mueve el raton 1 px cada KEEP_AWAKE_INTERVAL segundos
        (sin desplazarlo) para que Windows no apague la pantalla ni suspenda.
        """
        hasta = self.keep_awake_until
        if hasta is None:
            return
        ahora = time.monotonic()
        if ahora >= hasta:
            self.keep_awake_until = None
            self.controller.keep_display_awake(False)
            log.info("Anti-apagado terminado")
            self.broadcast({"t": "keep_awake", "active": False, "remaining": 0})
            return
        if ahora - self.keep_awake_last < KEEP_AWAKE_INTERVAL:
            return
        self.keep_awake_last = ahora
        self.controller.keep_display_awake(True)
        try:
            self.controller.jiggle()
        except Exception:
            log.debug("jiggle fallo", exc_info=True)

    def aprender_tick(self) -> None:
        """
        Mantiene al dia el aprendizaje del tacto.

        Mira cada ~1,5 s que aplicacion tienes delante (para los perfiles por
        aplicacion) y guarda lo aprendido de vez en cuando, para no escribir en
        disco en cada movimiento.
        """
        ahora = time.monotonic()
        if ahora - self._app_check >= 1.5:
            self._app_check = ahora
            try:
                app_actual = self.controller.foreground_app()
            except Exception:
                app_actual = ""
            if app_actual != self._app:
                self._app = app_actual
                self.learning.ubicar(app_actual)
        if ahora - self._learn_saved >= 60.0:
            self._learn_saved = ahora
            self.learning.guardar()

    def _discard_stale(self) -> None:
        """
        Cuando ya no queda ningun celular conectado soltamos botones y teclas
        una sola vez, para no dejar la PC con el boton izquierdo presionado.
        Se hace en la transicion, no en cada ciclo, para no interferir con el
        mouse fisico del usuario.
        """
        if self.clients:
            self._idle_cleanup_done = False
            return
        if self._idle_cleanup_done:
            return
        self._idle_cleanup_done = True
        self.controller.release_all()

    # ---------------------------------------------------------------- difusion
    def _enqueue(self, client: Client, payload: dict) -> None:
        q = client.send_queue
        if len(q) >= 80:
            drop_cursor = next(
                (i for i, item in enumerate(q) if item.get("t") == "cursor"), 0
            )
            try:
                del q[drop_cursor]
            except IndexError:
                pass
        q.append(payload)

    def broadcast(self, payload: dict, only_kind: Optional[str] = None) -> None:
        for client in list(self.clients):
            if only_kind and client.kind != only_kind:
                continue
            self._enqueue(client, payload)

    async def _sender(self, client: Client) -> None:
        try:
            while True:
                if not client.send_queue:
                    await asyncio.sleep(0.008)
                    continue
                payload = client.send_queue.popleft()
                await client.ws.send_str(json.dumps(payload, separators=(",", ":")))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            pass

    def start_sender(self, client: Client) -> None:
        client.send_task = asyncio.create_task(self._sender(client))

    async def stop_sender(self, client: Client) -> None:
        if client.send_task is not None:
            client.send_task.cancel()
            try:
                await client.send_task
            except (asyncio.CancelledError, Exception):
                pass
            client.send_task = None

    # ------------------------------------------------------------ bucle de salida
    async def animation_loop(self) -> None:
        """
        Consume los eventos de entrada a ~60-125 Hz.

        Los movimientos se acumulan y se aplican en el ultimo momento: si el
        celular envia mas rapido de lo que se puede procesar, no se pierde
        distancia. Los clics se ejecutan de inmediato para no perder
        precision, y el scroll se consolida para que las ruedas se sientan
        suaves en lugar de a saltos.
        """
        loop = asyncio.get_running_loop()
        last_shown_key = self.login_key
        while True:
            self.keep_pin_fresh()
            self.keep_awake_tick()
            self.aprender_tick()

            # Si la clave del QR cambio, se vuelve a dibujar en la consola:
            # asi el codigo que hay en pantalla nunca esta caducado. Se omite
            # si hay algun navegador conectado (el panel ya lo muestra y
            # redibujar no haria mas que llenar la consola de codigos).
            if (self.show_qr_console and not self.clients
                    and self.login_key != last_shown_key):
                last_shown_key = self.login_key
                print_qr_block(self.console_host, self.port, last_shown_key,
                               when="codigo nuevo")

            dx = dy = 0.0
            try:
                while True:
                    mx, my = self._move_q.get_nowait()
                    dx += mx
                    dy += my
            except queue.Empty:
                pass

            if dx or dy:
                # Aprendizaje del tacto: multiplica el movimiento por la
                # ganancia aprendida (1,0 si esta desactivado o aun no sabe).
                ganancia = self.learning.ganancia()
                aplicado_x = dx * ganancia
                aplicado_y = dy * ganancia
                try:
                    await loop.run_in_executor(
                        self.executor, self.controller.mouse_move,
                        aplicado_x, aplicado_y,
                    )
                except Exception:
                    log.debug("mouse_move fallo", exc_info=True)
                # Se aprende de lo que de verdad ha pasado en pantalla.
                self.learning.alimentar(aplicado_x, aplicado_y)

            while True:
                try:
                    action = self._click_q.get_nowait()
                except queue.Empty:
                    break
                try:
                    await loop.run_in_executor(self.executor, action)
                except Exception:
                    log.debug("accion de clic fallo", exc_info=True)

            now = loop.time() * 1000.0
            if self._scroll_q and (now - self._scroll_sent_at) >= SCROLL_QUEUE_DELAY_MS:
                sdx = sdy = 0.0
                while self._scroll_q:
                    sx, sy = self._scroll_q.popleft()
                    sdx += sx
                    sdy += sy
                if sdx or sdy:
                    try:
                        await loop.run_in_executor(
                            self.executor, self.controller.mouse_scroll, sdx, sdy
                        )
                    except Exception:
                        log.debug("scroll fallo", exc_info=True)
                self._scroll_sent_at = now

            wait = 0.008 if (self._move_q.qsize() or self._click_q.qsize()) else 0.016
            await asyncio.sleep(wait)

    # -------------------------------------------------------------- acciones
    def _queue_move(self, dx: float, dy: float) -> None:
        q = self._move_q
        if q.qsize() >= 240:          # el celular va muy por delante: consolidamos
            while not q.empty():
                mx, my = q.get_nowait()
                dx += mx
                dy += my
        q.put_nowait((dx, dy))

    def _queue_click(self, action: Callable[[], None]) -> None:
        self._click_q.put_nowait(action)

    async def handle_action(
        self, client: Client, action: str, data: dict
    ) -> Optional[dict]:
        c = self.controller

        if action == "mouse_rel_move":
            self._queue_move(
                clamp_number(data.get("dx"), -4000, 4000),
                clamp_number(data.get("dy"), -4000, 4000),
            )
            return None

        if action == "mouse_move":
            # Movimiento absoluto: se convierte a relativo para respetar el
            # mismo limite de pantalla y la misma consolidacion de eventos.
            x = clamp_number(data.get("x"), 0, 100_000)
            y = clamp_number(data.get("y"), 0, 100_000)
            target_x, target_y = c.virtual_position
            self._queue_move(x - target_x, y - target_y)
            return None

        if action == "mouse_hover":
            # Compatibilidad: el cliente antiguo pedia "pasar por encima". El
            # puntero normal ya genera hover, asi que lo tratamos como mover.
            self._queue_move(
                clamp_number(data.get("dx"), -4000, 4000),
                clamp_number(data.get("dy"), -4000, 4000),
            )
            return None

        if action == "mouse_click":
            button = str(data.get("button", "left"))
            count = int(clamp_number(data.get("clicks"), 1, 3, 1)) or 1
            self._queue_click(lambda: c.mouse_click(button, count))
            return None

        if action == "mouse_down":
            button = str(data.get("button", "left"))
            self._queue_click(lambda: c.mouse_button_down(button))
            return None

        if action == "mouse_up":
            button = str(data.get("button", "left"))
            self._queue_click(lambda: c.mouse_button_up(button))
            return None

        if action == "mouse_drag_start":
            # Coloca el puntero sobre el objetivo y presiona: asi el arrastre
            # empieza justo donde el usuario toco la pantalla.
            x = clamp_number(data.get("x"), 0, 100_000)
            y = clamp_number(data.get("y"), 0, 100_000)

            def _start(x=x, y=y):
                c.mouse_move_to(x, y)
                c.mouse_button_down("left")

            self._queue_click(_start)
            return None

        if action == "mouse_release_all":
            self._queue_click(c.release_all)
            return None

        if action == "mouse_scroll":
            self._scroll_q.append(
                (
                    clamp_number(data.get("dx"), -2000, 2000),
                    clamp_number(data.get("dy"), -2000, 2000),
                )
            )
            return None

        if action == "zoom":
            # Pinza de dos dedos: Ctrl + rueda. >0 acerca, <0 aleja.
            steps = int(clamp_number(data.get("steps"), -50, 50, 0))
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.zoom, steps
            )
            return {"ok": bool(ok)}

        if action == "clipboard_get":
            # Texto que hay ahora en el portapapeles de la PC.
            texto = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.clipboard_text
            )
            return {"ok": True, "text": texto}

        if action == "clipboard_set":
            # Deja en el portapapeles de la PC el texto que manda el celular.
            texto = str(data.get("text", ""))
            if len(texto) > 100_000:
                return {"error": "texto demasiado largo"}
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.clipboard_set, texto
            )
            return {"ok": bool(ok)}

        if action == "laser":
            # Puntero laser: x, y llegan normalizados (0..1) desde el touchpad.
            activo = bool(data.get("on", True))
            if not activo:
                self.laser.hide()
                return {"ok": True, "on": False}
            ancho, alto = c.screen_size
            x = clamp_number(data.get("x"), 0.0, 1.0, 0.0) * max(1, ancho - 1)
            y = clamp_number(data.get("y"), 0.0, 1.0, 0.0) * max(1, alto - 1)
            self.laser.point(x, y)
            return {"ok": True, "on": True}

        if action == "keep_awake":
            # Anti-apagado: mueve el raton 1 px cada 40 s para que Windows no
            # apague la pantalla. `minutes` es la duracion pedida por el usuario.
            activo = bool(data.get("on", True))
            minutos = clamp_number(data.get("minutes"), 0, 24 * 60, 0)
            if not activo or minutos <= 0:
                if self.keep_awake_until is not None:
                    self.keep_awake_until = None
                    self.controller.keep_display_awake(False)
                    log.info("Anti-apagado detenido")
                return {"ok": True, "active": False, "remaining": 0}
            self.keep_awake_until = time.monotonic() + minutos * 60
            self.keep_awake_last = 0.0     # que haga el primer movimiento ya
            log.info("Anti-apagado activo %d minutos", int(minutos))
            return {
                "ok": True,
                "active": True,
                "remaining": int(self.keep_awake_until - time.monotonic()),
            }

        if action == "save_settings":
            # Preferencias del dispositivo (velocidad, gestos...). Se guardan en
            # el servidor para no tener que reajustarlas si el navegador borra
            # sus datos, o si se entra desde el mismo celular otra vez.
            ajustes = data.get("settings")
            if not isinstance(ajustes, dict) or not client.token:
                return {"error": "ajustes invalidos"}
            limpio = {
                str(clave): valor
                for clave, valor in ajustes.items()
                if isinstance(clave, str)
                and isinstance(valor, (bool, int, float, str))
            }
            self._profiles[client.token] = limpio
            save_profiles(self._profiles)
            return {"ok": True}

        if action == "learning":
            # Aprendizaje del tacto: consultar, encender/apagar o reiniciar.
            if "on" in data:
                self.learning.activar(bool(data.get("on")))
                self.learning.guardar()
            if data.get("reset"):
                self.learning.reiniciar()
                log.info("Aprendizaje del tacto reiniciado")
            return {"ok": True, **self.learning.estado()}

        if action == "key_type":
            text = str(data.get("text", ""))
            if len(text) > 4000:
                return {"error": "texto demasiado largo"}
            # Los valores van como argumentos por defecto: esta funcion corre
            # en otro hilo y sin esto leeria variables ya reasignadas.
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.type_text, text
            )
            return {"ok": bool(ok)}

        if action == "key":
            key = str(data.get("key", ""))
            modifiers = data.get("mods") or []
            if not isinstance(modifiers, (list, tuple)):
                modifiers = []
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.key_tap, key, list(modifiers)
            )
            return {"ok": bool(ok)}

        if action == "media":
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.media, str(data.get("action", ""))
            )
            return {"ok": bool(ok), "media": data.get("action")}

        if action == "media_volume":
            # Volumen "inteligente": pynput no sabe el volumen actual, asi que
            # se mueve a pasos de ~2% repitiendo la tecla.
            steps = int(clamp_number(data.get("steps"), -50, 50, 0))
            direction = "volume_up" if steps > 0 else "volume_down"
            for _ in range(abs(steps)):
                await asyncio.get_running_loop().run_in_executor(
                    self.executor, c.media, direction
                )
                await asyncio.sleep(0.012)
            return {"ok": True}

        if action == "media_mute":
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.media, "mute"
            )
            return {"ok": bool(ok)}

        if action == "presentation":
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.presentation, str(data.get("action", ""))
            )
            return {"ok": bool(ok), "presentation": data.get("action")}

        if action == "get_state":
            return {
                "screen": list(c.refresh_screen_size()),
                "pin": self.pin,
                "pin_seconds": self.pin_seconds_left(),
                "auth_required": self.auth_required,
            }

        if action == "set_auth":
            # Solo un dispositivo ya autorizado puede quitar el codigo de
            # acceso (la comprobacion previa a este bloque lo garantiza).
            activo = bool(data.get("required", True))
            cambiado = self.set_auth_required(activo, f"peticion de {client.addr}")
            return {"ok": True, "required": self.auth_required, "cambiado": cambiado}

        if action == "get_driver":
            # Diagnostico: que boton tiene presionado el servidor ahora mismo.
            return {
                "button_held": c.drag_button,
                "position": list(c.virtual_position),
            }

        if action == "refresh_pin":
            return {"pin": self.pin, "pin_seconds": self.pin_seconds_left()}

        if action == "comando_detener":
            # Solo un dispositivo ya autorizado puede parar el servicio: la
            # comprobacion de antes de este bloque lo garantiza.
            #
            # La parada se pide DESPUES de responder, al salir de esta funcion:
            # esta respuesta se encola antes que el aviso de parada, y asi el
            # celular recibe la confirmacion y no solo un "desconectado".
            self._parada_pedida = f"peticion de {client.addr}"
            return {"ok": True, "detenido": True}

        return {"error": f"accion desconocida: {action}"}

    # ----------------------------------------------------------- autenticacion
    def auth_payload(self, client: Client, con_token: bool = False) -> dict:
        """
        Respuesta de acceso correcto.

        Incluye las preferencias guardadas del dispositivo (si las tiene) para
        que no haya que volver a ajustarlas tras limpiar los datos del navegador.
        """
        payload: dict = {
            "t": "ok",
            "status": "auth",
            "id": client.client_id,
            "screen": list(self.controller.screen_size),
        }
        if con_token and client.token:
            payload["token"] = client.token
        perfil = self._profiles.get(client.token or "")
        if isinstance(perfil, dict) and perfil:
            payload["settings"] = perfil
        return payload

    def handle_auth(self, client: Client, data: dict) -> Optional[dict]:
        token = data.get("token")
        if self.token_is_valid(token):
            client.token = str(token)
            client.kind = "auth"
            log.info("Autorizado por token: %s", client.addr)
            return self.auth_payload(client)

        if data.get("token"):
            # Hay un token guardado en el celular pero ya no vale: es una
            # situacion normal tras reiniciar el servidor con otra version, o
            # si se pulso "Olvidar este dispositivo" en otro momento.
            log.warning("Token desconocido desde %s: se pedira el PIN o el QR",
                        client.addr)

        pin = data.get("pin")
        if pin and self.check_pin(pin, client.addr):
            client.token = self.issue_token()
            client.kind = "auth"
            log.info("Autorizado con el PIN: %s", client.addr)
            return self.auth_payload(client, con_token=True)

        if pin:
            log.warning("PIN incorrecto desde %s (el PIN vigente es %s; "
                        "caduca cada 5 minutos)", client.addr, self.pin)
        else:
            log.warning("Peticion de acceso sin PIN ni token desde %s", client.addr)
        return {"t": "auth_fail", "reason": "PIN incorrecto"}

    # -------------------------------------------------------------- WebSocket
    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=2 * 1024 * 1024)
        await ws.prepare(request)

        addr = request.remote or "?"
        client = Client(ws=ws, client_id=secrets.token_hex(4), addr=addr)
        self.start_sender(client)
        log.info("Conexion desde %s", addr)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    client.last_seen = time.monotonic()
                    await self._handle_message(client, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            await self.stop_sender(client)
            self.clients.discard(client)
            if client.kind == "auth":
                # Al irse el celular soltamos botones/teclas para no dejar la
                # PC con el boton izquierdo presionado.
                await asyncio.get_running_loop().run_in_executor(
                    self.executor, self.controller.release_all
                )
            log.info("Desconectado: %s", addr)
        return ws

    async def _handle_message(self, client: Client, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return

        action = str(message.get("a", ""))
        data = message.get("d")
        if not isinstance(data, dict):
            data = {}

        # --- todavia sin autenticar -----------------------------------------
        if client.kind == "auth" and client.token is None:
            if action == "viewer":
                client.kind = "viewer"
                client.token = ""
                self.clients.add(client)
                self._enqueue(
                    client,
                    {"t": "ok", "status": "viewer", "id": client.client_id, "pin": self.pin},
                )
                return

            # Con el control de acceso desactivado se autoriza al instante: el
            # celular entra sin PIN ni QR.
            if action == "auth" and not self.auth_required:
                client.token = self.issue_token()
                client.kind = "auth"
                self.clients.add(client)
                log.info("Autorizado sin codigo (control de acceso "
                         "desactivado): %s", client.addr)
                self._enqueue(client, self.auth_payload(client, con_token=True))
                return

            if action == "auth":
                response = self.handle_auth(client, data)
                assert response is not None
                if response.get("status") == "auth":
                    self.clients.add(client)
                self._enqueue(client, response)
                return

            if action == "auth_query":
                # Pregunta de la pantalla de acceso: asi sabe si debe pedir
                # codigo o si puede entrar directamente.
                self._enqueue(client, {
                    "t": "auth_state",
                    "required": self.auth_required,
                    "pin": self.pin if self.auth_required else "",
                })
                return

            self._enqueue(client, {"t": "auth_required"})
            return

        # --- autenticado ----------------------------------------------------
        if client.kind == "viewer" and action not in VIEWER_ACTIONS:
            self._enqueue(client, {"t": "denied", "reason": "modo espectador"})
            return
        if client.kind == "auth" and not self._within_rate(client):
            return

        if action == "pad_input":
            self.broadcast(
                {"t": "pad_input", "from": client.client_id, "d": data},
                only_kind="viewer",
            )
            return
        if action == "ping":
            self._enqueue(client, {"t": "pong", "ts": data.get("ts")})
            return
        if action == "auth":
            # Un dispositivo ya autorizado puede volver a presentar sus
            # credenciales (por ejemplo, una copia antigua de la app que repite
            # la autenticacion al reconectar). Se trata como un reintento
            # idempotente en lugar de devolver "accion desconocida: auth".
            response = self.handle_auth(client, data)
            if response.get("status") == "auth":
                self.clients.add(client)
            self._enqueue(client, response)
            return
        try:
            response = await self.handle_action(client, action, data)
        except Exception:
            log.exception("Error ejecutando %s", action)
            response = {"error": "fallo interno"}
        if response is not None:
            self._enqueue(client, {"t": "response", "a": action, "d": response})

        # La parada se ejecuta despues de encolar la respuesta, para que el
        # cliente reciba la confirmacion y despues el aviso de cierre.
        if self._parada_pedida:
            motivo, self._parada_pedida = self._parada_pedida, None
            self.request_stop(motivo)

    def _within_rate(self, client: Client) -> bool:
        window = int(time.monotonic())
        if client.rate_window != window:
            client.rate_window = window
            client.rate_used = 0
        client.rate_used += 1
        if client.rate_used <= MAX_ACTIONS_PER_SECOND:
            return True
        if client.rate_used == MAX_ACTIONS_PER_SECOND + 1:
            self._enqueue(
                client,
                {"t": "denied", "reason": "demasiadas ordenes por segundo"},
            )
        return False

    # ------------------------------------------------------------------ cierre
    async def shutdown(self) -> None:
        self.laser.stop()
        self.learning.guardar()
        self.controller.release_all()
        for client in list(self.clients):
            await self.stop_sender(client)
        self.executor.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ servidor
def dashboard_html(gateway: Gateway, url: str) -> str:
    """Panel que se abre en la PC: muestra el QR y el PIN en grande."""
    template = (WEB_ROOT / "qr.html").read_text(encoding="utf-8")
    data = {
        "url": url,
        "key": gateway.login_key,
        "pin": gateway.pin,
        "seconds": gateway.qr_seconds_left(),
        "auth_required": gateway.auth_required,
        "matrix": qr.encode(url, "M"),
    }
    # La matriz y los datos van como JSON incrustado: la pagina se dibuja en
    # el navegador con canvas y se refresca sola cuando la clave cambia.
    return template.replace(
        "/*__DATA__*/null",
        json.dumps(data, separators=(",", ":")),
    )


def build_app(gateway: Gateway) -> web.Application:
    app = web.Application()

    async def index(request: web.Request) -> web.StreamResponse:
        """
        Sirve la aplicacion del celular.

        Si la peticion trae la clave del QR (?k=...), se inyecta en el propio
        HTML como etiqueta meta. Asi el acceso no depende de que el navegador
        conserve el parametro en la direccion: algunos visores de camara lo
        recortan al redirigir.

        Esta respuesta se sirve SIEMPRE sin cache. Es la unica forma segura de
        que el celular no se quede ejecutando un app.js antiguo guardado: con
        una copia vieja, la pagina carga, pide el PIN y el servidor recibe
        acciones que ya no existen («accion desconocida»).
        """
        log.info("HTTP %s  <- %s", request.path_qs, request.remote)
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        key = request.query.get("k", "")

        if key:
            # Comprobacion previa: si la clave ya no vale se avisa en la propia
            # pantalla, sin necesidad de que el cliente haga la peticion.
            if hmac.compare_digest(str(key), gateway.login_key):
                estado = "ok"
            else:
                estado = "caducado"
            meta = (
                f'<meta name="remotepad-qr-key" content="{html_lib.escape(key, quote=True)}">\n'
                f'<meta name="remotepad-qr-estado" content="{estado}">\n'
                f'<meta name="remotepad-version" content="{APP_VERSION}">'
            )
            html = html.replace("<!-- remoto -->", meta)
        else:
            html = html.replace(
                "<!-- remoto -->",
                f'<meta name="remotepad-version" content="{APP_VERSION}">',
            )

        return web.Response(
            text=html, content_type="text/html", charset="utf-8",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    async def static_file(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        candidate = (WEB_ROOT / name).resolve()
        if (
            candidate.suffix.lower() not in STATIC_EXTENSIONS
            or not candidate.is_file()
            or WEB_ROOT not in candidate.parents
        ):
            raise web.HTTPNotFound()
        # El codigo de la aplicacion se sirve SIN cache: si el celular guardara
        # una copia antigua de app.js, la pagina cargaria y el servidor recibiria
        # acciones que ya no existen ("accion desconocida: auth"). Las imagenes
        # (iconos) si pueden cachearse: no cambian entre versiones.
        if candidate.suffix.lower() in (".js", ".css", ".html", ".webmanifest"):
            log.info("HTTP %s  <- %s", request.path_qs, request.remote)
            return web.FileResponse(
                candidate,
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                },
            )
        return web.FileResponse(candidate)

    def is_local(request: web.Request) -> bool:
        addr = request.remote or ""
        return addr in ("127.0.0.1", "::1", "localhost")

    async def qr_page(request: web.Request) -> web.StreamResponse:
        # Solo desde la propia PC: la pagina contiene el PIN y la clave que
        # permite entrar sin autenticarse, asi que no debe salir a la red.
        if not is_local(request):
            raise web.HTTPForbidden(text="Este panel solo se abre en la PC")
        return web.Response(text=dashboard_html(gateway, gateway.login_url()),
                            content_type="text/html", charset="utf-8")

    async def qr_login(request: web.Request) -> web.StreamResponse:
        """Canjea la clave del QR por un token de dispositivo."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        key = (payload or {}).get("key", "")
        addr = request.remote or "?"
        token = gateway.use_login_key(key, addr)
        if token is None:
            # Nota: si el celular ha podido llegar hasta aqui, la red y el
            # firewall funcionan. Lo unico que falla es que ese codigo ya no
            # vale (pasaron los 3 minutos o ya se uso).
            log.warning(
                "QR rechazado desde %s: el codigo ya no vale. Los codigos duran "
                "%d segundos y sirven una sola vez; en la consola se muestra uno "
                "nuevo automaticamente.",
                addr, int(QR_VALID_SECONDS),
            )
            return web.json_response(
                {"ok": False, "error": "El codigo QR caduco"}, status=403
            )
        log.info("Autorizado con el QR: %s", addr) if gateway.auth_required else \
            log.info("Autorizado sin codigo (control de acceso desactivado): %s", addr)
        return web.json_response({"ok": True, "token": token})

    async def qr_refresh(request: web.Request) -> web.StreamResponse:
        """
        Da un QR nuevo a un cliente que ya esta autorizado.

        Lo usa la aplicacion del celular para recuperarse sola: si el codigo se
        renovo justo mientras lo escaneaba, pide uno nuevo y reintenta, sin que
        el usuario tenga que volver a apuntar con la camara.

        Exige el token de un dispositivo ya autorizado: no sirve para entrar
        desde cero, solo para renovar un acceso que ya existe. El enlace se
        consume al usarlo.
        """
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        token = str((payload or {}).get("token", ""))
        if not gateway.token_is_valid(token):
            log.warning("Recuperacion de QR rechazada desde %s: token no valido",
                        request.remote)
            return web.json_response({"ok": False, "error": "no autorizado"},
                                     status=403)

        clave = gateway.reservar_clave_actual()
        url = f"http://{gateway.lan_host}:{gateway.port}/?k={clave}"
        return web.json_response({
            "ok": True,
            "key": clave,
            "url": url,
            "seconds": gateway.qr_seconds_left(),
            "matrix": qr.encode(url, "M"),
        })

    async def qr_stream(request: web.Request) -> web.StreamResponse:
        """Avisa al panel de la PC cuando cambia la clave (server-sent events)."""
        if not is_local(request):
            raise web.HTTPForbidden(text="Solo en la PC")
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
        })
        await response.prepare(request)
        last_key = None
        try:
            while True:
                await asyncio.sleep(1.0)
                gateway.keep_pin_fresh()
                if gateway.login_key != last_key:
                    last_key = gateway.login_key
                    data = {
                        "url": gateway.login_url(),
                        "key": last_key,
                        "pin": gateway.pin,
                        "seconds": gateway.qr_seconds_left(),
                        "auth_required": gateway.auth_required,
                        "matrix": qr.encode(gateway.login_url(), "M"),
                    }
                    await response.write(
                        b"data: " + json.dumps(data, separators=(",", ":")).encode() + b"\n\n"
                    )
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            log.debug("stream del panel terminado", exc_info=True)
        return response

    async def qr_new(request: web.Request) -> web.StreamResponse:
        """
        Genera un QR nuevo y devuelve sus datos.

        Lo usa el panel de la PC: tanto el boton como la renovacion automatica
        cada 3 minutos. Devolver los datos evita tener que recargar.
        """
        if not is_local(request):
            raise web.HTTPForbidden(text="Solo en la PC")
        gateway.refresh_login_key()
        url = gateway.login_url()
        return web.json_response({
            "url": url,
            "key": gateway.login_key,
            "pin": gateway.pin,
            "seconds": gateway.qr_seconds_left(),
            "auth_required": gateway.auth_required,
            "matrix": qr.encode(url, "M"),
        })

    async def health(request: web.Request) -> web.StreamResponse:
        return web.json_response({
            "ok": True,
            "version": APP_VERSION,
            "auth_required": gateway.auth_required,
        })

    async def api_stop(request: web.Request) -> web.StreamResponse:
        """
        Detiene el servidor. Solo desde la propia PC: cualquiera de la red
        podria apagarlo, y para eso esta el boton de la app (que exige estar
        ya autenticado).
        """
        if not is_local(request):
            raise web.HTTPForbidden(text="Solo se puede detener desde la PC")
        gateway.request_stop("desde el navegador de la PC")
        return web.json_response({"ok": True})

    async def api_auth(request: web.Request) -> web.StreamResponse:
        """
        Activa o desactiva el codigo de acceso desde la propia PC.

        Solo responde a la PC: si lo aceptara desde la red, cualquiera podria
        quitar la proteccion.
        """
        if not is_local(request):
            raise web.HTTPForbidden(text="Solo se puede cambiar desde la PC")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        activo = bool((payload or {}).get("required", True))
        gateway.set_auth_required(activo, "desde el navegador de la PC")
        return web.json_response({"ok": True, "required": gateway.auth_required})

    app.router.add_get("/", index)
    app.router.add_get("/ws", gateway.ws_handler)
    app.router.add_get("/qr", qr_page)
    app.router.add_get("/qr/stream", qr_stream)
    app.router.add_post("/qr/new", qr_new)
    app.router.add_post("/api/qr-login", qr_login)
    app.router.add_post("/api/qr-refresh", qr_refresh)
    app.router.add_post("/api/stop", api_stop)
    app.router.add_post("/api/auth", api_auth)
    app.router.add_get("/{name}", static_file)
    app.router.add_get("/healthz", health)
    return app


async def run(args: argparse.Namespace) -> None:
    gateway: Gateway  # se crea abajo; el controlador necesita su callback de PIN

    # Sin esto, si el usuario deja el celular inactivo el PIN no se renovaria
    # hasta la siguiente orden: lo comprobamos antes de cada accion sensible.
    controller = DesktopController(pin_verifier=lambda: gateway.keep_pin_fresh())
    gateway = Gateway(controller, host=args.host, port=args.port)

    if args.no_auth:
        # Arrancar sin codigo de acceso: comodo para probar, pero cualquiera en
        # la misma WiFi puede manejar la PC. Se guarda la eleccion para que
        # siga quitado en los proximos arranques (se cambia con "auth on" o
        # desde Ajustes en el celular).
        gateway.auth_required = False
        save_config({"auth_required": False})
        log.warning("Arrancando SIN codigo de acceso (--no-auth): la eleccion "
                    "queda guardada; para volver a pedirlo, escribe 'auth on'")
    else:
        # Se respeta lo que se eligio la ultima vez.
        guardado = load_config()
        if guardado.get("auth_required") is False:
            gateway.auth_required = False
            log.warning("El codigo de acceso esta desactivado (se quito antes "
                        "con quitar-codigo.bat o desde la app): el celular "
                        "entra directamente")

    app = build_app(gateway)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    try:
        await site.start()
    except OSError as exc:
        print(f"\n[ERROR] No se pudo abrir el puerto {args.port}: {exc}")
        print("Prueba con otro puerto:  python app.py --port 8899\n")
        await runner.cleanup()
        return

    log.info("RemotePad %s en marcha (puerto %d)", APP_VERSION, args.port)
    if gateway.auth_required and not args.no_qr:
        log.info("Comprueba en el celular que la app muestre la version %s "
                 "(Ajustes); si muestra otra, borra los datos del sitio.",
                 APP_VERSION)

    shown_host = args.host
    if shown_host in ("0.0.0.0", "::"):
        shown_host = local_ip()
    gateway.lan_host = shown_host
    gateway.console_host = shown_host
    # La consola redibuja el QR cada vez que cambia, para que el que esta a la
    # vista nunca este caducado. Solo tiene sentido si se pide codigo.
    gateway.show_qr_console = (
        not args.no_qr and gateway.auth_required and qr.supports_color()
    )
    # Ojo: se pasa el estado REAL (gateway.auth_required), no solo el argumento
    # --no-auth, porque el codigo puede estar desactivado desde config.json.
    print_banner(
        shown_host, args.port, gateway.pin, gateway.auth_required,
        login_key=gateway.login_key, show_qr=not args.no_qr,
    )
    if not gateway.auth_required:
        # El recuadro va despues del banner para que no corte el logo.
        print(AVISO_SIN_ACCESO)

    if not args.no_browser and shown_host not in ("127.0.0.1", "localhost"):
        webbrowser.open(f"http://127.0.0.1:{args.port}/qr")

    loop = asyncio.get_running_loop()
    gateway.stop_event = asyncio.Event()
    animations = loop.create_task(gateway.animation_loop())
    console = loop.create_task(console_commands(gateway))
    try:
        await gateway.stop_event.wait()      # hasta Ctrl+C o peticion de parada
    except asyncio.CancelledError:
        pass
    finally:
        gateway.shutting_down = True         # evita mas avisos durante el cierre
        # Un instante para que el aviso "shutdown" llegue a los celulares antes
        # de cerrar las conexiones: asi muestran "servicio detenido" y no un
        # simple "desconectado".
        await asyncio.sleep(0.4)
        for task in (animations, console):
            task.cancel()
        await gateway.shutdown()
        await runner.cleanup()
        print("\n" + "=" * 58)
        print("   RemotePad se ha detenido. Puedes cerrar esta ventana.")
        print("=" * 58 + "\n")


async def console_commands(gateway: Gateway) -> None:
    """
    Lee lo que se escribe en la consola.

    - ENTER (linea vacia): imprime un QR nuevo al instante.
    - q / Q / salir / exit: detiene el servidor.
    - cualquier otra cosa: muestra la ayuda.

    La lectura se hace en un hilo *demonio* y no con run_in_executor: el hilo
    que espera en input() no se puede interrumpir, y si no es demonio impide
    que el proceso termine al detener el servicio (asyncio espera a sus hilos
    antes de salir). Siendo demonio, cuando la tarea se cancela el proceso
    puede cerrarse igualmente.
    """
    import threading

    loop = asyncio.get_running_loop()
    cola: asyncio.Queue = asyncio.Queue()

    def leer_consola() -> None:
        while True:
            try:
                linea = input()
            except (EOFError, KeyboardInterrupt, OSError, ValueError):
                # Sin entrada disponible (por ejemplo si stdin esta cerrado):
                # no hay nada mas que hacer, el hilo termina.
                return
            try:
                loop.call_soon_threadsafe(cola.put_nowait, linea)
            except RuntimeError:
                return          # el bucle ya se ha cerrado

    threading.Thread(target=leer_consola, daemon=True, name="consola").start()

    parar = {"q", "quit", "salir", "exit", "s"}
    encender = {"auth on", "autenticacion on", "codigo on", "pin on"}
    apagar = {"auth off", "autenticacion off", "codigo off", "pin off"}
    try:
        while True:
            linea = await cola.get()
            comando = linea.strip().lower()
            if comando in parar:
                gateway.request_stop("desde la consola")
                return
            if comando in encender:
                gateway.set_auth_required(True, "desde la consola")
                print("   Control de acceso ACTIVADO. El PIN actual es "
                      f"{gateway.pin}")
                continue
            if comando in apagar:
                gateway.set_auth_required(False, "desde la consola")
                print(AVISO_SIN_ACCESO)
                continue
            if comando in ("", "qr"):
                if gateway.show_qr_console:
                    gateway.refresh_login_key()
                    print_qr_block(gateway.console_host, gateway.port,
                                   gateway.login_key, when="codigo nuevo")
                else:
                    print("   Este terminal no admite el QR en color; "
                          "usa el panel del navegador.")
                continue
            print("   ENTER = nuevo codigo QR   ·   q = detener   ·   "
                  "auth off / auth on = codigo de acceso")
    except asyncio.CancelledError:
        pass
    except Exception:
        log.debug("lectura de consola terminada", exc_info=True)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RemotePad: usa tu celular como touchpad del PC."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="puerto (def. 8765)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="interfaz de escucha (def. 0.0.0.0)"
    )
    parser.add_argument("--no-auth", action="store_true",
                        help="quitar el codigo de acceso (PIN y QR)")
    parser.add_argument(
        "--no-qr", action="store_true", help="no generar el codigo QR de acceso"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="no abrir el navegador al iniciar"
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main() -> int:
    args = parse_args()
    if not (WEB_ROOT / "index.html").is_file():
        print(f"[ERROR] No encuentro la interfaz web en {WEB_ROOT}")
        return 1
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
