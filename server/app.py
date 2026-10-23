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
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

try:
    from controller import SPECIAL_KEYS, DesktopController
except ImportError as exc:  # pragma: no cover
    print("Falta el controlador del escritorio:", exc)
    print("Instala las dependencias con:  python -m pip install -r requirements.txt")
    raise SystemExit(1)

import auth
import certificado
import qr
import rdp
import despertador
import historial
import learning
import native_input
from auth import (QR_GRACE_SECONDS, QR_VALID_SECONDS, device_name, load_config,
                  save_config, read_json, write_json_atomic)

# --------------------------------------------------------------------- ajustes
# Empaquetado (PyInstaller) la web va dentro del ejecutable, junto a los datos.
WEB_ROOT = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "web").resolve()
# Preferencias de cada dispositivo (velocidad, gestos, etc.), para no tener que
# volver a ajustarlas: se guardan en el servidor, ligadas al acceso del celular.
PROFILES_FILE = Path(
    os.environ.get("REMOTEPAD_PROFILES")
    or (Path(__file__).resolve().parent / "profiles.json")
)
DEFAULT_PORT = 8765
# "https" con --https (ver certificado.py). Lo fija run() al arrancar y lo usan
# todas las direcciones que se muestran o van dentro del QR.
SCHEME = "http"

# Sube al cambiar la parte web: sirve para comprobar en el celular que se esta
# ejecutando la version nueva y no una copia guardada. Debe coincidir con la
# constante REMOTEPAD_WEB de web/index.html: si no, la propia pagina fuerza una
# recarga (y avisa) para que el celular no se quede con JavaScript viejo.
APP_VERSION = "1.17.0"
ANSWER_TIMEOUT = 2.0
MAX_ACTIONS_PER_SECOND = 450
SCROLL_QUEUE_DELAY_MS = 16
# Anti-apagado: cada cuanto se mueve el raton 1 px para simular actividad.
KEEP_AWAKE_INTERVAL = 40.0
# Confirmacion de dispositivos nuevos: titulo de la ventana y tiempo maximo.
CONFIRM_TITLE = "RemotePad - dispositivo nuevo"
CONFIRM_TIMEOUT = 60.0

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

# Registro en archivo: lo lee la app de escritorio, y sirve aunque el servidor
# se arranque sin consola (en segundo plano). Las pruebas lo redirigen con
# REMOTEPAD_LOG.
LOG_FILE = Path(os.environ.get("REMOTEPAD_LOG")
                or (Path(__file__).resolve().parent / "servidor.log"))
try:
    _registro_archivo = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _registro_archivo.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(_registro_archivo)
except OSError as exc:
    print(f"[AVISO] No se puede escribir el registro {LOG_FILE}: {exc}")


def now_ms() -> int:
    return int(time.time() * 1000)


def loop_time_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)


def clamp_number(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return max(low, min(high, number))


# Limites de las preferencias que guarda cada dispositivo: sin ellos un cliente
# podia llenar profiles.json con mensajes de 2 MB, uno detras de otro.
MAX_SETTINGS_KEYS = 60
MAX_SETTINGS_KEY_LEN = 40
MAX_SETTINGS_STR_LEN = 8000
MAX_SETTINGS_BYTES = 32_000


# Atajos personalizados: limites para que un atajo no pueda bloquear la PC
# (ni el hilo que lo ejecuta) mas de unos segundos.
MACRO_MAX_STEPS = 30
MACRO_MAX_TEXT = 1000
MACRO_MAX_WAIT_MS = 3000
MACRO_MAX_TOTAL_WAIT_MS = 10_000
MACRO_MODIFIERS = {"ctrl", "alt", "shift", "cmd", "win"}


def validate_macro(pasos: Any) -> tuple[Optional[list[dict]], str]:
    """
    Comprueba los pasos de un atajo personalizado.

    Devuelve (pasos_limpios, "") o (None, motivo). Solo se aceptan tres tipos:
    combinacion de teclas, texto y espera, con nombres de tecla conocidos.
    """
    if not isinstance(pasos, list) or not pasos:
        return None, "el atajo no tiene pasos"
    if len(pasos) > MACRO_MAX_STEPS:
        return None, f"como mucho {MACRO_MAX_STEPS} pasos"
    limpios: list[dict] = []
    espera_total = 0
    for numero, paso in enumerate(pasos, 1):
        if not isinstance(paso, dict):
            return None, f"paso {numero} no valido"
        tipo = paso.get("tipo")
        if tipo == "combo":
            tecla = str(paso.get("tecla", "")).strip().lower()
            mods = paso.get("mods") or []
            if not isinstance(mods, list) or len(mods) > 4:
                return None, f"paso {numero}: modificadores no validos"
            mods = [str(m).lower() for m in mods]
            if any(m not in MACRO_MODIFIERS for m in mods):
                return None, f"paso {numero}: modificador desconocido"
            if not (len(tecla) == 1 or tecla in SPECIAL_KEYS):
                return None, f"paso {numero}: tecla desconocida «{tecla[:20]}»"
            limpios.append({"tipo": "combo", "tecla": tecla,
                            "mods": ["cmd" if m == "win" else m for m in mods]})
        elif tipo == "texto":
            texto = str(paso.get("texto", ""))
            if not texto or len(texto) > MACRO_MAX_TEXT:
                return None, f"paso {numero}: texto vacio o demasiado largo"
            limpios.append({"tipo": "texto", "texto": texto})
        elif tipo == "espera":
            ms = int(clamp_number(paso.get("ms"), 0, MACRO_MAX_WAIT_MS, 0))
            espera_total += ms
            if espera_total > MACRO_MAX_TOTAL_WAIT_MS:
                return None, "demasiado tiempo de espera en total"
            limpios.append({"tipo": "espera", "ms": ms})
        else:
            return None, f"paso {numero}: tipo desconocido"
    return limpios, ""


def load_profiles() -> dict:
    """
    Preferencias guardadas de cada dispositivo, por huella de su acceso.

    Las versiones anteriores las guardaban con el token EN CLARO como clave:
    se convierten a la huella (la misma que usa tokens.json), asi el archivo
    deja de contener secretos.
    """
    datos = read_json(PROFILES_FILE, "se usan los ajustes del celular")
    if not isinstance(datos, dict):
        return {}
    perfiles: dict = {}
    migrado = False
    for clave, perfil in datos.items():
        if not isinstance(perfil, dict):
            continue
        if not auth.is_hash(clave):
            clave = auth.token_hash(clave)
            migrado = True
        perfiles[clave] = perfil
    if migrado:
        save_profiles(perfiles)
    return perfiles


def save_profiles(perfiles: dict) -> None:
    """Guarda las preferencias de los dispositivos (best effort)."""
    write_json_atomic(PROFILES_FILE, perfiles)


def clean_settings(ajustes: Any) -> Optional[dict]:
    """
    Valida las preferencias que manda el celular.

    Solo valores simples, con nombres y textos acotados. Devuelve None si el
    conjunto no es valido o es demasiado grande.
    """
    if not isinstance(ajustes, dict) or len(ajustes) > MAX_SETTINGS_KEYS:
        return None
    limpio: dict = {}
    for clave, valor in ajustes.items():
        if not isinstance(clave, str) or not clave or len(clave) > MAX_SETTINGS_KEY_LEN:
            continue
        if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
            continue
        if isinstance(valor, str) and len(valor) > MAX_SETTINGS_STR_LEN:
            continue
        if isinstance(valor, (bool, int, float, str)):
            limpio[clave] = valor
    if len(json.dumps(limpio)) > MAX_SETTINGS_BYTES:
        return None
    return limpio


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


def is_loopback(addr: str) -> bool:
    """La peticion viene de la propia PC."""
    if addr == "localhost":
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    """
    El WebSocket solo se acepta desde la propia aplicacion.

    Un navegador siempre manda la cabecera Origin. Si no coincide con la
    direccion del servidor, la conexion la ha abierto OTRA pagina web (por
    ejemplo, una que el usuario visita en un navegador de la misma red) y se
    rechaza. Los clientes que no son navegadores (pruebas, scripts) no mandan
    Origin: ahi no hay pagina ajena que proteger y se aceptan.
    """
    if not origin:
        return True
    if not host:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and parsed.netloc.lower() == host.lower()


def mostrar_ventanas() -> bool:
    """
    Se pueden abrir ventanas en la PC (la pregunta de confirmacion).

    Las pruebas lo desactivan con REMOTEPAD_SIN_VENTANAS=1 y responden por la
    consola, para no dejar ventanas abiertas ni depender de un escritorio.
    """
    return native_input.available() and not os.environ.get("REMOTEPAD_SIN_VENTANAS")


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
    url = f"{SCHEME}://{host}:{port}/?k={login_key}"
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
    print(f"   Panel siempre vigente:  {SCHEME}://127.0.0.1:{port}/qr")


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
    print(f"       {SCHEME}://{host}:{port}")
    if host != "127.0.0.1":
        print(f"   Desde esta misma PC:  {SCHEME}://127.0.0.1:{port}")
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


def print_https_info(host: str, port: int, certificados: "certificado.Certificados") -> None:
    """Como conseguir que el celular confie en el certificado (una sola vez)."""
    line = "=" * 58
    print(line)
    print("   HTTPS ACTIVO (trafico cifrado)")
    print("   La primera vez el celular avisara de que la conexion no es")
    print("   privada: el certificado es de esta PC, no de una empresa.")
    print("   Para que confie sin avisos, instala la autoridad local:")
    print(f"       {SCHEME}://{host}:{port}/ca.crt")
    print("   Android: Ajustes > Seguridad > Cifrado y credenciales >")
    print("            Instalar un certificado > Certificado de CA")
    print(f"   Comprueba que su huella empiece por: {certificados.huella_ca}")
    print(line + "\n")


# ------------------------------------------------------------------- clientes
# eq=False: un dataclass normal genera __eq__, y entonces la clase deja de ser
# "hasheable". Aqui cada cliente se identifica por su objeto (se guardan en un
# set), asi que la identidad es justo lo que queremos.
@dataclass(eq=False)
class Client:
    ws: web.WebSocketResponse
    client_id: str
    kind: str = "auth"          # auth | viewer
    # Huella del acceso del dispositivo (None = aun no autorizado; "" para el
    # espectador). El token en claro nunca se guarda en el servidor.
    device: Optional[str] = None
    addr: str = "?"
    nombre: str = "Dispositivo"   # sacado del User-Agent del navegador
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
        # Empaquetado, sys.executable es el propio servidor: se le pide que haga de laser.
        comando = ([sys.executable, "--laser"] if getattr(sys, "frozen", False)
                   else [sys.executable, str(script)])
        try:
            self._process = subprocess.Popen(
                comando,
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

        # PIN, codigos QR, intentos fallidos y dispositivos autorizados (estos
        # se leen de disco para que reiniciar no obligue a volver a entrar).
        # El aviso se resuelve al llamarlo: las pruebas sustituyen _enqueue.
        self.acceso = auth.ControlAcceso(avisar=lambda payload: self.broadcast(payload))
        if len(self.acceso.dispositivos):
            log.info("Accesos recordados de %d dispositivo(s)",
                     len(self.acceso.dispositivos))
        # Preferencias de cada dispositivo (por huella). Se descartan las de
        # accesos que ya no existen (caducados o retirados).
        self._profiles: dict[str, dict] = load_profiles()
        self._podar_perfiles()
        # Confirmacion en la PC de cada dispositivo NUEVO (opcional).
        self.confirmar_nuevos = bool(load_config().get("confirm_new_devices", False))
        self._confirmaciones: "deque[asyncio.Future]" = deque()
        # Dispositivo que espera tu permiso ahora mismo (lo muestra la app de escritorio).
        self.pendiente: Optional[dict] = None
        self._poda_fallos = 0.0
        # Certificados HTTPS (solo con --https): run() los prepara.
        self.certificados: Optional[certificado.Certificados] = None
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
        # Programas usados, para volver a abrirlos desde el celular.
        self.historial = historial.Historial()
        self._prog_hwnd = 0
        self._prog_check = 0.0
        # Ventana con permisos de administrador delante (Windows bloquea el control).
        self.aviso_elevado = False
        self._elev_check = 0.0

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
        self._scroll_suave = False   # rueda de alta resolucion (lo pide el cliente)
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

    def login_url(self) -> str:
        """
        Direccion que debe contener el QR.

        Tiene que ser la IP de la red local: 127.0.0.1 funcionaria solo en la
        propia PC, pero en el celular apuntaria a si mismo y no abriria nada.
        """
        return f"{SCHEME}://{self.lan_host}:{self.port}/?k={self.acceso.login_key}"

    def keep_pin_fresh(self) -> None:
        self.acceso.rotate_pin_if_needed()
        if not self.shutting_down:
            self.acceso.rotate_qr_key_if_needed()
        ahora = time.monotonic()
        if ahora - self._poda_fallos >= 60.0:
            self._poda_fallos = ahora
            self.acceso.prune_failures()
            if self.acceso.dispositivos.podar():
                self._podar_perfiles()
        self._discard_stale()

    # ------------------------------------------------------------ dispositivos
    def _podar_perfiles(self) -> None:
        """Olvida las preferencias de accesos que ya no existen."""
        huerfanos = [h for h in self._profiles if h not in self.acceso.dispositivos]
        for huella in huerfanos:
            del self._profiles[huella]
        if huerfanos:
            save_profiles(self._profiles)

    async def autorizar_dispositivo(self, nombre: str, addr: str) -> Optional[tuple[str, str]]:
        """
        Da acceso a un dispositivo NUEVO (tras acertar el PIN o el QR).

        Si esta activada la confirmacion, la PC pregunta antes. Devuelve
        (token, huella), o None si se rechaza. Siempre se avisa en la consola
        y a los demas dispositivos conectados: asi una entrada inesperada no
        pasa desapercibida.
        """
        if self.confirmar_nuevos and not await self.pedir_confirmacion(nombre, addr):
            log.warning("Acceso RECHAZADO en la PC: %s (%s)", nombre, addr)
            return None
        token, huella = self.acceso.dispositivos.emitir(nombre, addr)
        print("\n" + "-" * 58)
        print(f"   NUEVO DISPOSITIVO CON ACCESO: {nombre} ({addr})")
        print(f"   Si no lo reconoces:  revocar {huella[:8]}")
        print("-" * 58)
        self.broadcast({"t": "device_new", "nombre": nombre, "addr": addr},
                       only_kind="auth")
        return token, huella

    async def pedir_confirmacion(self, nombre: str, addr: str) -> bool:
        """
        Pregunta en la PC si se deja entrar a un dispositivo nuevo.

        Se puede responder en la ventana que aparece o escribiendo si / no en
        la consola; lo primero que llegue manda. Sin respuesta en
        CONFIRM_TIMEOUT segundos, se rechaza.
        """
        loop = asyncio.get_running_loop()
        futuro: asyncio.Future = loop.create_future()
        self._confirmaciones.append(futuro)
        self.pendiente = {"nombre": nombre, "addr": addr}
        log.info("Dispositivo NUEVO esperando permiso: %s (%s)", nombre, addr)
        print("\n" + "!" * 58)
        print(f"   {nombre} ({addr}) quiere manejar esta PC.")
        print("   Escribe  si  para permitirlo o  no  para rechazarlo.")
        print("!" * 58)

        ventana = None
        if mostrar_ventanas():
            texto = (f"{nombre} ({addr}) quiere manejar esta PC con RemotePad.\n\n"
                     "¿Permitir el acceso?")
            ventana = loop.run_in_executor(
                None, native_input.ask_yes_no, CONFIRM_TITLE, texto, CONFIRM_TIMEOUT
            )

            def _desde_ventana(tarea: asyncio.Future) -> None:
                if futuro.done() or tarea.cancelled() or tarea.exception():
                    return
                respuesta = tarea.result()
                if respuesta is not None:
                    futuro.set_result(bool(respuesta))

            ventana.add_done_callback(_desde_ventana)
        try:
            return await asyncio.wait_for(asyncio.shield(futuro), CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            print("   Sin respuesta: acceso rechazado.")
            return False
        finally:
            try:
                self._confirmaciones.remove(futuro)
            except ValueError:
                pass
            if not self._confirmaciones:
                self.pendiente = None
            if ventana is not None and not ventana.done():
                # Se respondio en la consola: se cierra la ventana pendiente.
                native_input.dismiss_question(CONFIRM_TITLE)

    def responder_confirmacion(self, permitir: bool) -> bool:
        """Respuesta desde la consola a la pregunta mas antigua pendiente."""
        for futuro in list(self._confirmaciones):
            if not futuro.done():
                futuro.set_result(permitir)
                return True
        return False

    def set_confirmar_nuevos(self, activo: bool, motivo: str = "") -> None:
        self.confirmar_nuevos = bool(activo)
        save_config({"confirm_new_devices": self.confirmar_nuevos})
        log.info("Confirmacion de dispositivos nuevos %s%s",
                 "ACTIVADA" if activo else "desactivada",
                 f" {motivo}".rstrip())

    def lista_dispositivos(self, actual: Optional[str] = None) -> list[dict]:
        """Dispositivos con acceso, marcando el que pregunta y los conectados."""
        conectados = {c.device for c in self.clients if c.kind == "auth" and c.device}
        filas = []
        for fila in self.acceso.dispositivos.listar():
            huella = fila.pop("huella")
            fila["actual"] = huella == actual
            fila["conectado"] = huella in conectados
            filas.append(fila)
        return filas

    async def revocar_dispositivo(self, prefijo: str, motivo: str = "") -> Optional[str]:
        """
        Retira el acceso de un dispositivo y lo desconecta si esta conectado.

        Devuelve el nombre del dispositivo retirado, o None si el identificador
        no corresponde a uno (y solo uno).
        """
        nombres = {f["huella"]: f["nombre"] for f in self.acceso.dispositivos.listar()}
        retirados = self.acceso.dispositivos.revocar(prefijo)
        if not retirados:
            return None
        huella = retirados[0]
        self._profiles.pop(huella, None)
        save_profiles(self._profiles)
        log.warning("Acceso RETIRADO a %s%s", nombres.get(huella, huella[:8]),
                    f" {motivo}".rstrip())
        for client in list(self.clients):
            if client.device == huella:
                self._enqueue(client, {"t": "revoked"})
                # Un instante para que el aviso salga antes de cortar.
                await asyncio.sleep(0.15)
                try:
                    await client.ws.close()
                except Exception:
                    pass
        return nombres.get(huella, huella[:8])

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
        if ahora - self._prog_check >= 1.5:
            self._prog_check = ahora
            self.historial_tick()
        if ahora - self._learn_saved >= 60.0:
            self._learn_saved = ahora
            self.learning.guardar()
            self.historial.guardar()

    def elevacion_tick(self) -> None:
        """
        Avisa a los moviles y a la app de escritorio cuando la ventana de delante
        tiene permisos de administrador: Windows no deja controlarla, y sin aviso
        parece que el touchpad se ha roto.
        """
        ahora = time.monotonic()
        if ahora - self._elev_check < 1.0:
            return
        self._elev_check = ahora
        try:
            elevada = native_input.foreground_elevated()
        except Exception:
            elevada = False
        if elevada == self.aviso_elevado:
            return
        self.aviso_elevado = elevada
        if elevada:
            log.warning("Ventana con permisos de administrador delante: Windows no deja "
                        "controlarla desde el movil (haz clic en otra ventana)")
        else:
            log.info("Ya no hay ventana con permisos de administrador delante")
        self.broadcast({"t": "aviso_elevado", "activo": elevada})

    def historial_tick(self) -> None:
        """
        Apunta en el historial el programa que tienes delante cuando cambias de
        ventana. El nombre y el icono solo se leen la primera vez.
        """
        try:
            actual = self.controller.foreground_program()
        except Exception:
            actual = None
        hwnd = actual["hwnd"] if actual else 0
        if not actual or hwnd == self._prog_hwnd:
            self._prog_hwnd = hwnd
            return
        self._prog_hwnd = hwnd
        try:
            ruta = actual["path"]
            nombre = historial.nombre_de(
                ruta, self.controller.program_name(ruta), actual.get("title", "")
            )
            clave = self.historial.anotar(ruta, actual.get("aumid", ""), nombre)
            if clave and self.historial.necesita_icono(clave):
                icono = self.controller.program_icon(ruta, hwnd)
                if icono:
                    self.historial.anotar(ruta, actual.get("aumid", ""), nombre, icono)
        except Exception:
            log.debug("historial: no se pudo anotar", exc_info=True)

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
        last_shown_key = self.acceso.login_key
        while True:
            self.keep_pin_fresh()
            self.keep_awake_tick()
            self.aprender_tick()
            self.elevacion_tick()

            # Si la clave del QR cambio, se vuelve a dibujar en la consola:
            # asi el codigo que hay en pantalla nunca esta caducado. Se omite
            # si hay algun navegador conectado (el panel ya lo muestra y
            # redibujar no haria mas que llenar la consola de codigos).
            if (self.show_qr_console and not self.clients
                    and self.acceso.login_key != last_shown_key):
                last_shown_key = self.acceso.login_key
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
                            self.executor, self.controller.mouse_scroll,
                            sdx, sdy, self._scroll_suave,
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
            # Coordenadas del escritorio: pueden ser negativas si hay un
            # monitor a la izquierda o encima del principal.
            x = clamp_number(data.get("x"), -100_000, 100_000)
            y = clamp_number(data.get("y"), -100_000, 100_000)
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
            # Coordenadas del escritorio: pueden ser negativas si hay un
            # monitor a la izquierda o encima del principal.
            x = clamp_number(data.get("x"), -100_000, 100_000)
            y = clamp_number(data.get("y"), -100_000, 100_000)

            def _start(x=x, y=y):
                c.mouse_move_to(x, y)
                c.mouse_button_down("left")

            self._queue_click(_start)
            return None

        if action == "mouse_release_all":
            self._queue_click(c.release_all)
            return None

        if action == "mouse_scroll":
            self._scroll_suave = bool(data.get("smooth"))
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
            limpio = clean_settings(data.get("settings"))
            if limpio is None or not client.device:
                return {"error": "ajustes invalidos"}
            # Solo se escribe en disco si algo cambia.
            if self._profiles.get(client.device) != limpio:
                self._profiles[client.device] = limpio
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

        if action == "key_down" or action == "key_up":
            # Modo mando: la tecla queda pulsada mientras el dedo esta en el
            # boton. Al desconectarse el celular, release_all las suelta.
            tecla = str(data.get("key", "")).strip().lower()
            if not (len(tecla) == 1 and tecla.isalnum()) and tecla not in SPECIAL_KEYS:
                return {"error": "tecla no valida"}
            # Por la cola de clics, que se ejecuta EN ORDEN: con el ejecutor
            # (3 hilos) un toque rapido podia soltar la tecla antes de pulsarla
            # y dejarla pegada. Sin respuesta: son mensajes muy seguidos.
            funcion = c.key_down if action == "key_down" else c.key_up
            self._queue_click(lambda funcion=funcion, tecla=tecla: funcion(tecla))
            return None

        if action == "macro":
            # Atajo personalizado del usuario: se ejecuta entero en un hilo,
            # en orden y con sus esperas.
            pasos, motivo = validate_macro(data.get("pasos"))
            if pasos is None:
                return {"error": motivo}
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.run_macro, pasos
            )
            return {"ok": bool(ok)}

        if action == "media":
            ok = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.media, str(data.get("action", ""))
            )
            return {"ok": bool(ok), "media": data.get("action")}

        if action == "window":
            # Botones de la barra de titulo de la ventana activa.
            op = str(data.get("op", ""))
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, c.window, op
            )

        if action == "windows_list":
            # Programas abiertos, para elegir cual ver desde el celular.
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, c.windows
            )

        if action == "rdp_info":
            # Estado del escritorio remoto de Windows. Solo se lee: activarlo
            # exige administrador y se hace en Configuracion de Windows.
            ip = local_ip()
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, lambda h=ip: rdp.estado(h, socket.gethostname())
            )

        if action == "programs_history":
            # Programas usados en la PC (sin rutas), para volver a abrirlos.
            return self.historial.lista()

        if action == "program_launch":
            # Solo se abre lo que ya esta en el historial: el celular manda un
            # id y la ruta la pone el servidor.
            entrada = self.historial.buscar(str(data.get("id", "")))
            if not entrada:
                return {"error": "ese programa ya no esta en el historial"}
            resultado = await asyncio.get_running_loop().run_in_executor(
                self.executor,
                lambda e=entrada: c.launch_program(e["path"], e.get("aumid", "")),
            )
            if resultado.get("ok"):
                resultado["name"] = entrada["name"]
                log.info("Abriendo %s desde %s", entrada["name"], client.addr)
            return resultado

        if action == "program_forget":
            borrado = self.historial.quitar(str(data.get("id", "")))
            self.historial.guardar()
            return {"ok": borrado}

        if action == "window_close":
            hwnd = int(clamp_number(data.get("id"), 0, 2**63 - 1))
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, lambda hwnd=hwnd: c.window_close(hwnd)
            )

        if action == "window_focus":
            hwnd = int(clamp_number(data.get("id"), 0, 2**63 - 1))
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, lambda hwnd=hwnd: c.window_focus(hwnd)
            )

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
                "pin": self.acceso.pin,
                "pin_seconds": self.acceso.pin_seconds_left(),
                "auth_required": self.acceso.auth_required,
            }

        if action == "set_auth":
            # Solo un dispositivo ya autorizado puede quitar el codigo de
            # acceso (la comprobacion previa a este bloque lo garantiza).
            activo = bool(data.get("required", True))
            cambiado = self.acceso.set_auth_required(activo, f"peticion de {client.addr}")
            return {"ok": True, "required": self.acceso.auth_required, "cambiado": cambiado}

        if action == "monitor_list":
            # Monitores conectados, para elegir a cual llevar el puntero.
            monitores = await asyncio.get_running_loop().run_in_executor(
                self.executor, lambda: c.monitors
            )
            x, y = c.virtual_position
            actual = next(
                (i for i, m in enumerate(monitores)
                 if m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"]),
                0,
            )
            return {"monitores": monitores, "actual": actual}

        if action == "monitor_goto":
            indice = int(clamp_number(data.get("index"), 0, 32, 0))
            monitor = await asyncio.get_running_loop().run_in_executor(
                self.executor, c.move_to_monitor, indice
            )
            if monitor is None:
                return {"error": "no existe esa pantalla"}
            return {"ok": True, "index": indice, "monitor": monitor}

        if action == "devices_list":
            # Dispositivos con acceso, para gestionarlos desde Ajustes.
            return {
                "dispositivos": self.lista_dispositivos(client.device),
                "confirmar": self.confirmar_nuevos,
            }

        if action == "device_revoke":
            prefijo = str(data.get("id", ""))[:64]
            nombre = await self.revocar_dispositivo(prefijo, f"desde {client.addr}")
            if nombre is None:
                return {"error": "no se encontro ese dispositivo"}
            return {"ok": True, "nombre": nombre,
                    "dispositivos": self.lista_dispositivos(client.device)}

        if action == "set_confirm":
            # Pedir (o no) confirmacion en la PC para cada dispositivo nuevo.
            self.set_confirmar_nuevos(bool(data.get("on")), f"desde {client.addr}")
            return {"ok": True, "confirmar": self.confirmar_nuevos}

        if action == "get_driver":
            # Diagnostico: que boton tiene presionado el servidor ahora mismo.
            return {
                "button_held": c.drag_button,
                "position": list(c.virtual_position),
                "keys_held": c.held_keys,
            }

        if action == "refresh_pin":
            return {"pin": self.acceso.pin, "pin_seconds": self.acceso.pin_seconds_left()}

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
    def auth_payload(self, client: Client, token: Optional[str] = None) -> dict:
        """
        Respuesta de acceso correcto.

        `token` solo va cuando se acaba de crear el acceso: es la unica vez que
        sale del servidor (despues solo se guarda su huella). Incluye las
        preferencias guardadas del dispositivo (si las tiene) para que no haya
        que volver a ajustarlas tras limpiar los datos del navegador.
        """
        payload: dict = {
            "t": "ok",
            "status": "auth",
            "id": client.client_id,
            "screen": list(self.controller.screen_size),
            "device": (client.device or "")[:8],
            "aviso_elevado": self.aviso_elevado,
        }
        if token:
            payload["token"] = token
        perfil = self._profiles.get(client.device or "")
        if isinstance(perfil, dict) and perfil:
            payload["settings"] = perfil
        return payload

    async def handle_auth(self, client: Client, data: dict) -> dict:
        huella = self.acceso.dispositivos.validar(data.get("token"))
        if huella:
            client.device = huella
            client.kind = "auth"
            self.acceso.dispositivos.visto(huella, client.addr, client.nombre)
            log.info("Autorizado por token: %s", client.addr)
            return self.auth_payload(client)

        if data.get("token"):
            # Hay un token guardado en el celular pero ya no vale: es una
            # situacion normal tras reiniciar el servidor con otra version, o
            # si se pulso "Olvidar este dispositivo" en otro momento.
            log.warning("Token desconocido desde %s: se pedira el PIN o el QR",
                        client.addr)

        pin = data.get("pin")
        if pin and self.acceso.check_pin(pin, client.addr):
            emitido = await self.autorizar_dispositivo(client.nombre, client.addr)
            if emitido is None:
                return {"t": "auth_fail", "reason": "La PC no ha permitido el acceso"}
            token, client.device = emitido
            client.kind = "auth"
            log.info("Autorizado con el PIN: %s", client.addr)
            return self.auth_payload(client, token=token)

        if pin:
            # El PIN vigente no se escribe aqui: el registro puede acabar en un
            # archivo (probar.bat lo guarda en %TEMP%) y ya se ve en el banner.
            log.warning("PIN incorrecto desde %s (caduca cada 5 minutos: "
                        "mira el vigente en la consola)", client.addr)
        else:
            log.warning("Peticion de acceso sin PIN ni token desde %s", client.addr)
        return {"t": "auth_fail", "reason": "PIN incorrecto"}

    # -------------------------------------------------------------- WebSocket
    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        if not origin_allowed(request.headers.get("Origin"), request.host):
            # Otra pagina web intenta hablar con RemotePad desde el navegador.
            log.warning("WebSocket rechazado desde %s: origen ajeno (%s)",
                        request.remote, request.headers.get("Origin"))
            raise web.HTTPForbidden(text="Origen no permitido")
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=2 * 1024 * 1024)
        await ws.prepare(request)

        addr = request.remote or "?"
        client = Client(ws=ws, client_id=secrets.token_hex(4), addr=addr,
                        nombre=device_name(request.headers.get("User-Agent", "")))
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
        if client.kind == "auth" and client.device is None:
            if action == "viewer":
                # El modo espectador ve el PIN: solo para la propia PC. Antes se
                # aceptaba desde cualquier equipo de la red, y bastaba un mensaje
                # para conocer el PIN y entrar.
                if not is_loopback(client.addr):
                    log.warning("Modo espectador rechazado desde %s", client.addr)
                    self._enqueue(client, {"t": "denied", "reason": "solo en la PC"})
                    return
                client.kind = "viewer"
                client.device = ""
                self.clients.add(client)
                self._enqueue(
                    client,
                    {"t": "ok", "status": "viewer", "id": client.client_id, "pin": self.acceso.pin},
                )
                return

            # Con el control de acceso desactivado se autoriza al instante: el
            # celular entra sin PIN ni QR. Si ya tiene un acceso valido se usa
            # ese (antes se creaba uno nuevo en cada reconexion y tokens.json
            # crecia sin parar).
            if (action == "auth" and not self.acceso.auth_required
                    and not self.acceso.dispositivos.validar(data.get("token"))):
                emitido = await self.autorizar_dispositivo(client.nombre, client.addr)
                if emitido is None:
                    self._enqueue(client, {"t": "auth_fail",
                                           "reason": "La PC no ha permitido el acceso"})
                    return
                token, client.device = emitido
                client.kind = "auth"
                self.clients.add(client)
                log.info("Autorizado sin codigo (control de acceso "
                         "desactivado): %s", client.addr)
                self._enqueue(client, self.auth_payload(client, token=token))
                return

            if action == "auth":
                response = await self.handle_auth(client, data)
                if response.get("status") == "auth":
                    self.clients.add(client)
                self._enqueue(client, response)
                return

            if action == "auth_query":
                # Pregunta de la pantalla de acceso: asi sabe si debe pedir
                # codigo o si puede entrar directamente.
                # NUNCA se incluye el PIN: quien pregunta aun no esta
                # autorizado, y con el PIN podria entrar sin estar delante de
                # la PC.
                self._enqueue(client, {
                    "t": "auth_state",
                    "required": self.acceso.auth_required,
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
            # idempotente en lugar de devolver "accion desconocida: auth". Ya
            # esta dentro: no se crea otro acceso, se le confirma el que tiene.
            if self.acceso.dispositivos.validar(data.get("token")):
                response = await self.handle_auth(client, data)
            else:
                response = self.auth_payload(client)
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
        self.historial.guardar()
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
        "key": gateway.acceso.login_key,
        "pin": gateway.acceso.pin,
        "seconds": gateway.acceso.qr_seconds_left(),
        "auth_required": gateway.acceso.auth_required,
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
            if hmac.compare_digest(str(key), gateway.acceso.login_key):
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
        return is_loopback(request.remote or "")

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
        if not gateway.acceso.canjear_clave(key, addr):
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
        nombre = device_name(request.headers.get("User-Agent", ""))
        emitido = await gateway.autorizar_dispositivo(nombre, addr)
        if emitido is None:
            return web.json_response(
                {"ok": False, "error": "La PC no ha permitido el acceso"}, status=403
            )
        if gateway.acceso.auth_required:
            log.info("Autorizado con el QR: %s", addr)
        else:
            log.info("Autorizado sin codigo (control de acceso desactivado): %s", addr)
        return web.json_response({"ok": True, "token": emitido[0]})

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
        if not gateway.acceso.dispositivos.validar(token):
            log.warning("Recuperacion de QR rechazada desde %s: token no valido",
                        request.remote)
            return web.json_response({"ok": False, "error": "no autorizado"},
                                     status=403)

        clave = gateway.acceso.reservar_clave_actual()
        url = f"{SCHEME}://{gateway.lan_host}:{gateway.port}/?k={clave}"
        return web.json_response({
            "ok": True,
            "key": clave,
            "url": url,
            "seconds": gateway.acceso.qr_seconds_left(),
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
                if gateway.acceso.login_key != last_key:
                    last_key = gateway.acceso.login_key
                    data = {
                        "url": gateway.login_url(),
                        "key": last_key,
                        "pin": gateway.acceso.pin,
                        "seconds": gateway.acceso.qr_seconds_left(),
                        "auth_required": gateway.acceso.auth_required,
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
        gateway.acceso.refresh_login_key()
        url = gateway.login_url()
        return web.json_response({
            "url": url,
            "key": gateway.acceso.login_key,
            "pin": gateway.acceso.pin,
            "seconds": gateway.acceso.qr_seconds_left(),
            "auth_required": gateway.acceso.auth_required,
            "matrix": qr.encode(url, "M"),
        })

    async def ca_cert(request: web.Request) -> web.StreamResponse:
        """
        Autoridad local de HTTPS, para instalarla en el celular.

        Es la parte PUBLICA (nunca la clave): darla a cualquiera no permite
        suplantar al servidor. Solo existe con --https.
        """
        if gateway.certificados is None:
            raise web.HTTPNotFound()
        return web.Response(
            body=gateway.certificados.ca.read_bytes(),
            content_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="remotepad-ca.crt"'},
        )

    async def health(request: web.Request) -> web.StreamResponse:
        return web.json_response({
            "ok": True,
            "version": APP_VERSION,
            "auth_required": gateway.acceso.auth_required,
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
        gateway.acceso.set_auth_required(activo, "desde el navegador de la PC")
        return web.json_response({"ok": True, "required": gateway.acceso.auth_required})

    # ------------------------------------------------- API de la app de escritorio
    # Lo usa la ventana de escritorio (escritorio/). Solo acepta peticiones de la
    # propia PC y sin cabecera Origin: asi una web abierta en el navegador no
    # puede tocarla. Los POST deben ser JSON, lo que obliga al navegador a pedir
    # permiso previo (CORS) y este servidor no lo concede.
    def admin_guard(request: web.Request, post: bool = False) -> None:
        if not is_local(request) or request.headers.get("Origin"):
            raise web.HTTPForbidden(text="Solo desde la app de escritorio de la PC")
        if post and request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(text="Se espera JSON")

    async def admin_datos(request: web.Request) -> dict:
        try:
            datos = await request.json()
        except Exception:
            datos = {}
        return datos if isinstance(datos, dict) else {}

    async def admin_estado(request: web.Request) -> web.StreamResponse:
        admin_guard(request)
        acceso = gateway.acceso
        return web.json_response({
            "version": APP_VERSION,
            "host": gateway.host,
            "port": gateway.port,
            "https": SCHEME == "https",
            "lan_host": gateway.lan_host,
            "auth_required": acceso.auth_required,
            "pin": acceso.pin,
            "pin_seconds": acceso.pin_seconds_left(),
            "qr_url": gateway.login_url(),
            "qr_seconds": acceso.qr_seconds_left(),
            "confirmar_nuevos": gateway.confirmar_nuevos,
            "clientes": len(gateway.clients),
            "pendiente": gateway.pendiente,
            "apagando": gateway.shutting_down,
            "aviso_elevado": gateway.aviso_elevado,
            "dispositivos": gateway.lista_dispositivos(),
        })

    async def admin_ajustes(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        datos = await admin_datos(request)
        if "auth_required" in datos:
            gateway.acceso.set_auth_required(bool(datos["auth_required"]),
                                             "desde la app de escritorio")
        if "confirmar_nuevos" in datos:
            gateway.set_confirmar_nuevos(bool(datos["confirmar_nuevos"]),
                                         "desde la app de escritorio")
        return web.json_response({"ok": True, "auth_required": gateway.acceso.auth_required,
                                  "confirmar_nuevos": gateway.confirmar_nuevos})

    async def admin_pin(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        pin = gateway.acceso.regenerar_pin("(desde la app de escritorio)")
        return web.json_response({"ok": True, "pin": pin})

    async def admin_qr_actual(request: web.Request) -> web.StreamResponse:
        # Solo mira el QR vigente (no lo cambia): la ventana lo pide sin parar.
        admin_guard(request)
        url = gateway.login_url()
        return web.json_response({
            "url": url, "seconds": gateway.acceso.qr_seconds_left(),
            "matrix": qr.encode(url, "M"),
        })

    async def admin_qr_nuevo(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        gateway.acceso.refresh_login_key()
        url = gateway.login_url()
        return web.json_response({
            "ok": True, "url": url, "seconds": gateway.acceso.qr_seconds_left(),
            "matrix": qr.encode(url, "M"),
        })

    async def admin_revocar(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        datos = await admin_datos(request)
        nombre = await gateway.revocar_dispositivo(str(datos.get("id", "")),
                                                   "(desde la app de escritorio)")
        return web.json_response({"ok": bool(nombre), "nombre": nombre})

    async def admin_confirmar(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        datos = await admin_datos(request)
        respondida = gateway.responder_confirmacion(bool(datos.get("permitir")))
        return web.json_response({"ok": respondida})

    async def admin_historial(request: web.Request) -> web.StreamResponse:
        admin_guard(request)
        # Sin iconos: pesan mucho y la ventana solo muestra nombres.
        return web.json_response({"programas": gateway.historial.lista()["programs"]})

    async def admin_historial_quitar(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        datos = await admin_datos(request)
        quitado = gateway.historial.quitar(str(datos.get("id", "")))
        gateway.historial.guardar()
        return web.json_response({"ok": quitado})

    async def admin_parar(request: web.Request) -> web.StreamResponse:
        admin_guard(request, post=True)
        gateway.request_stop("desde la app de escritorio")
        return web.json_response({"ok": True})

    app.router.add_get("/", index)
    app.router.add_get("/ws", gateway.ws_handler)
    app.router.add_get("/api/admin/estado", admin_estado)
    app.router.add_post("/api/admin/ajustes", admin_ajustes)
    app.router.add_post("/api/admin/pin", admin_pin)
    app.router.add_get("/api/admin/qr", admin_qr_actual)
    app.router.add_post("/api/admin/qr", admin_qr_nuevo)
    app.router.add_post("/api/admin/revocar", admin_revocar)
    app.router.add_post("/api/admin/confirmar", admin_confirmar)
    app.router.add_get("/api/admin/historial", admin_historial)
    app.router.add_post("/api/admin/historial/quitar", admin_historial_quitar)
    app.router.add_post("/api/admin/parar", admin_parar)
    app.router.add_get("/qr", qr_page)
    app.router.add_get("/qr/stream", qr_stream)
    app.router.add_post("/qr/new", qr_new)
    app.router.add_post("/api/qr-login", qr_login)
    app.router.add_post("/api/qr-refresh", qr_refresh)
    app.router.add_post("/api/stop", api_stop)
    app.router.add_post("/api/auth", api_auth)
    app.router.add_get("/ca.crt", ca_cert)
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
        gateway.acceso.auth_required = False
        save_config({"auth_required": False})
        log.warning("Arrancando SIN codigo de acceso (--no-auth): la eleccion "
                    "queda guardada; para volver a pedirlo, escribe 'auth on'")
    else:
        # Se respeta lo que se eligio la ultima vez.
        guardado = load_config()
        if guardado.get("auth_required") is False:
            gateway.acceso.auth_required = False
            log.warning("El codigo de acceso esta desactivado (se quito antes "
                        "con quitar-codigo.bat o desde la app): el celular "
                        "entra directamente")

    if args.confirmar and not gateway.confirmar_nuevos:
        gateway.set_confirmar_nuevos(True, "(--confirmar)")
    if gateway.confirmar_nuevos:
        log.info("Cada dispositivo NUEVO necesitara tu permiso en esta PC "
                 "(para quitarlo: escribe 'confirmar off')")

    contexto_ssl = None
    certificados = None
    if args.https:
        global SCHEME
        SCHEME = "https"
        try:
            certificados = certificado.preparar(gateway.lan_host)
            contexto_ssl = certificados.contexto_ssl()
        except certificado.FaltaCryptography as exc:
            print(f"\n[ERROR] {exc}\n")
            return
        except Exception as exc:
            print(f"\n[ERROR] No se pudo preparar el certificado HTTPS: {exc}\n")
            return
    gateway.certificados = certificados

    app = build_app(gateway)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port, ssl_context=contexto_ssl)
    # Si el despertador tiene el puerto (servidor apagado), se le pide que lo
    # suelte: asi se puede arrancar a mano aunque este instalado.
    if despertador.pedir_puerto(args.port, contexto_ssl is not None):
        log.info("El despertador ha cedido el puerto %d", args.port)
    try:
        await site.start()
    except OSError as exc:
        print(f"\n[ERROR] No se pudo abrir el puerto {args.port}: {exc}")
        print("Prueba con otro puerto:  python app.py --port 8899\n")
        await runner.cleanup()
        return

    log.info("RemotePad %s en marcha (puerto %d)", APP_VERSION, args.port)
    if gateway.acceso.auth_required and not args.no_qr:
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
        not args.no_qr and gateway.acceso.auth_required and qr.supports_color()
    )
    # Ojo: se pasa el estado REAL (gateway.acceso.auth_required), no solo el argumento
    # --no-auth, porque el codigo puede estar desactivado desde config.json.
    print_banner(
        shown_host, args.port, gateway.acceso.pin, gateway.acceso.auth_required,
        login_key=gateway.acceso.login_key, show_qr=not args.no_qr,
    )
    if certificados is not None:
        print_https_info(shown_host, args.port, certificados)
    if not gateway.acceso.auth_required:
        # El recuadro va despues del banner para que no corte el logo.
        print(AVISO_SIN_ACCESO)

    if not args.no_browser and shown_host not in ("127.0.0.1", "localhost"):
        webbrowser.open(f"{SCHEME}://127.0.0.1:{args.port}/qr")

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


def imprimir_dispositivos(gateway: Gateway) -> None:
    filas = gateway.lista_dispositivos()
    if not filas:
        print("   No hay ningun dispositivo con acceso.")
        return
    print(f"   {'codigo':<9}{'dispositivo':<30}{'direccion':<16}ultima vez")
    for fila in filas:
        visto = time.strftime("%d/%m %H:%M", time.localtime(fila["visto"]))
        marca = "  (conectado)" if fila["conectado"] else ""
        print(f"   {fila['id']:<9}{fila['nombre'][:29]:<30}{fila['addr'][:15]:<16}"
              f"{visto}{marca}")
    print("   Para quitar uno:  revocar <codigo>")


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
            except (EOFError, KeyboardInterrupt, OSError, ValueError, RuntimeError):
                # Sin entrada disponible (por ejemplo si stdin esta cerrado, o el
                # ejecutable empaquetado no tiene consola: RuntimeError):
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
                gateway.acceso.set_auth_required(True, "desde la consola")
                print("   Control de acceso ACTIVADO. El PIN actual es "
                      f"{gateway.acceso.pin}")
                continue
            if comando in apagar:
                gateway.acceso.set_auth_required(False, "desde la consola")
                print(AVISO_SIN_ACCESO)
                continue
            if comando in ("si", "sí", "permitir", "no", "rechazar"):
                permitir = comando not in ("no", "rechazar")
                if not gateway.responder_confirmacion(permitir):
                    print("   No hay ningun dispositivo esperando permiso.")
                continue
            if comando in ("dispositivos", "devices", "d"):
                imprimir_dispositivos(gateway)
                continue
            if comando.startswith("revocar ") or comando.startswith("revoke "):
                prefijo = comando.split(None, 1)[1]
                nombre = await gateway.revocar_dispositivo(prefijo, "desde la consola")
                if nombre:
                    print(f"   Acceso retirado: {nombre}")
                else:
                    print("   No hay un dispositivo (y solo uno) con ese codigo. "
                          "Escribe 'dispositivos' para ver la lista.")
                continue
            if comando in ("confirmar on", "confirmar off"):
                gateway.set_confirmar_nuevos(comando.endswith("on"), "desde la consola")
                print("   Los dispositivos nuevos "
                      + ("necesitaran tu permiso." if gateway.confirmar_nuevos
                         else "entraran solo con el PIN o el QR."))
                continue
            if comando in ("", "qr"):
                if gateway.show_qr_console:
                    gateway.acceso.refresh_login_key()
                    print_qr_block(gateway.console_host, gateway.port,
                                   gateway.acceso.login_key, when="codigo nuevo")
                else:
                    print("   Este terminal no admite el QR en color; "
                          "usa el panel del navegador.")
                continue
            print("   ENTER = nuevo codigo QR   ·   q = detener   ·   "
                  "auth off / auth on = codigo de acceso\n"
                  "   dispositivos = lista   ·   revocar <codigo> = quitar acceso   ·   "
                  "confirmar on / off = permiso para los nuevos")
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
    parser.add_argument(
        "--https", action="store_true",
        help="servir por HTTPS con un certificado local (necesita 'cryptography')"
    )
    parser.add_argument(
        "--confirmar", action="store_true",
        help="pedir confirmacion en la PC para cada dispositivo nuevo (se recuerda)"
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
