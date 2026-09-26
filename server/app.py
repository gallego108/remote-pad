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
import ipaddress
import json
import logging
import math
import mimetypes
import os
import queue
import secrets
import socket
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

# --------------------------------------------------------------------- ajustes
WEB_ROOT = (Path(__file__).resolve().parent.parent / "web").resolve()
DEFAULT_PORT = 8765

PIN_ROTATE_SECONDS = 300.0   # cada cuanto cambia el PIN de seguridad
QR_VALID_SECONDS = 30.0      # cuanto vale cada codigo QR (de un solo uso)
TOKEN_TTL_SECONDS = 30 * 24 * 3600
ANSWER_TIMEOUT = 2.0
MAX_ACTIONS_PER_SECOND = 450
SCROLL_QUEUE_DELAY_MS = 40

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
    print(f"   Vale {int(QR_VALID_SECONDS)} segundos: si tardas, se muestra uno")
    print("   nuevo aqui solo. Tambien puedes pulsar ENTER para otro ahora.")
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
        print("   MODO SIN CONTRASENA (--no-auth): cualquiera en tu WiFi entra")
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

        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        self.login_key = new_login_key()      # clave del enlace del codigo QR
        self.login_key_generated = self._pin_generated
        self._key_failures: dict[str, list[float]] = {}
        self._tokens: dict[str, float] = {}
        self._pin_failures: dict[str, list[float]] = {}
        self.clients: set[Client] = set()

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
    def rotate_pin_if_needed(self) -> None:
        if time.monotonic() - self._pin_generated < PIN_ROTATE_SECONDS:
            return
        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        log.info("Nuevo PIN de seguridad: %s", self.pin)
        self.broadcast({"t": "pin", "pin": self.pin})

    def rotate_qr_key_if_needed(self) -> None:
        """
        El codigo QR vale 30 segundos.

        Pasado ese tiempo se genera otro automaticamente, de modo que el panel
        de la PC siempre muestra un codigo vigente. Es de un solo uso: al
        canjearlo tambien se renueva aqui.
        """
        if time.monotonic() - self.login_key_generated < QR_VALID_SECONDS:
            return
        self.refresh_login_key()

    def refresh_login_key(self) -> str:
        """Genera un QR nuevo (lo usa el panel de la PC y la rotacion)."""
        self.login_key = new_login_key()
        self.login_key_generated = time.monotonic()
        self.broadcast({"t": "qr_key", "key": self.login_key})
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

        La clave caduca con el PIN (5 minutos) y solo sirve una vez, para que
        el enlace que queda en el historial del navegador no valga siempre.
        """
        attempts = [t for t in self._key_failures.get(addr, []) if time.time() - t < 300]
        self._key_failures[addr] = attempts
        if len(attempts) >= 10:
            return None
        if not key or not hmac.compare_digest(str(key), self.login_key):
            attempts.append(time.time())
            return None

        self._key_failures.pop(addr, None)
        # Un solo uso: se renueva la clave al instante.
        self.refresh_login_key()
        return self.issue_token()

    def pin_seconds_left(self) -> int:
        remaining = PIN_ROTATE_SECONDS - (time.monotonic() - self._pin_generated)
        return max(0, int(remaining))

    def _prune_tokens(self) -> None:
        cutoff = time.time() - TOKEN_TTL_SECONDS
        for token in [t for t, created in self._tokens.items() if created < cutoff]:
            self._tokens.pop(token, None)

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
        return token

    def _too_many_failures(self, addr: str) -> bool:
        attempts = [t for t in self._pin_failures.get(addr, []) if time.time() - t < 300]
        self._pin_failures[addr] = attempts
        return len(attempts) >= 8

    def _register_failure(self, addr: str) -> None:
        self._pin_failures.setdefault(addr, []).append(time.time())

    def check_pin(self, pin: Any, addr: str = "?") -> bool:
        if self._too_many_failures(addr):
            return False
        if hmac.compare_digest(str(pin or ""), self.pin):
            self._pin_failures.pop(addr, None)
            return True
        self._register_failure(addr)
        return False

    def keep_pin_fresh(self) -> None:
        self.rotate_pin_if_needed()
        self.rotate_qr_key_if_needed()
        self._discard_stale()

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

            # Si la clave del QR cambio, se vuelve a dibujar en la consola:
            # asi el codigo que hay en pantalla nunca esta caducado.
            if self.show_qr_console and self.login_key != last_shown_key:
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
                try:
                    await loop.run_in_executor(
                        self.executor, self.controller.mouse_move, dx, dy
                    )
                except Exception:
                    log.debug("mouse_move fallo", exc_info=True)

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
            }

        if action == "get_driver":
            # Diagnostico: que boton tiene presionado el servidor ahora mismo.
            return {
                "button_held": c.drag_button,
                "position": list(c.virtual_position),
            }

        if action == "refresh_pin":
            return {"pin": self.pin, "pin_seconds": self.pin_seconds_left()}

        return {"error": f"accion desconocida: {action}"}

    # ----------------------------------------------------------- autenticacion
    def handle_auth(self, client: Client, data: dict) -> Optional[dict]:
        token = data.get("token")
        if self.token_is_valid(token):
            client.token = str(token)
            client.kind = "auth"
            log.info("Autorizado por token: %s", client.addr)
            return {"t": "ok", "status": "auth", "id": client.client_id, "screen": list(self.controller.screen_size)}

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
            return {
                "t": "ok",
                "status": "auth",
                "id": client.client_id,
                "token": client.token,
                "screen": list(self.controller.screen_size),
            }

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
            if action == "auth":
                response = self.handle_auth(client, data)
                assert response is not None
                if response.get("status") == "auth":
                    self.clients.add(client)
                self._enqueue(client, response)
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
        try:
            response = await self.handle_action(client, action, data)
        except Exception:
            log.exception("Error ejecutando %s", action)
            response = {"error": "fallo interno"}
        if response is not None:
            self._enqueue(client, {"t": "response", "a": action, "d": response})

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
        return web.FileResponse(WEB_ROOT / "index.html")

    async def static_file(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        candidate = (WEB_ROOT / name).resolve()
        if (
            candidate.suffix.lower() not in STATIC_EXTENSIONS
            or not candidate.is_file()
            or WEB_ROOT not in candidate.parents
        ):
            raise web.HTTPNotFound()
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
            # vale (pasaron los 30 segundos o ya se uso).
            log.warning(
                "QR rechazado desde %s: el codigo ya no vale. Los codigos duran "
                "%d segundos y sirven una sola vez; en la consola se muestra uno "
                "nuevo automaticamente.",
                addr, int(QR_VALID_SECONDS),
            )
            return web.json_response(
                {"ok": False, "error": "El codigo QR caduco"}, status=403
            )
        log.info("Autorizado con el QR: %s", addr)
        return web.json_response({"ok": True, "token": token})

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
        cada 30 segundos. Devolver los datos evita tener que recargar.
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
            "matrix": qr.encode(url, "M"),
        })

    app.router.add_get("/", index)
    app.router.add_get("/ws", gateway.ws_handler)
    app.router.add_get("/qr", qr_page)
    app.router.add_get("/qr/stream", qr_stream)
    app.router.add_post("/qr/new", qr_new)
    app.router.add_post("/api/qr-login", qr_login)
    app.router.add_get("/{name}", static_file)
    app.router.add_get("/healthz", lambda _r: web.json_response({"ok": True}))
    return app


async def run(args: argparse.Namespace) -> None:
    gateway: Gateway  # se crea abajo; el controlador necesita su callback de PIN

    # Sin esto, si el usuario deja el celular inactivo el PIN no se renovaria
    # hasta la siguiente orden: lo comprobamos antes de cada accion sensible.
    controller = DesktopController(pin_verifier=lambda: gateway.keep_pin_fresh())
    gateway = Gateway(controller, host=args.host, port=args.port)

    if args.no_auth:
        async def _always_ok(pin: Any = None, addr: str = "?") -> bool:
            return True

        gateway.check_pin = _always_ok  # type: ignore[assignment]

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

    shown_host = args.host
    if shown_host in ("0.0.0.0", "::"):
        shown_host = local_ip()
    gateway.lan_host = shown_host
    gateway.console_host = shown_host
    # La consola redibuja el QR cada vez que cambia, para que el que esta a la
    # vista nunca este caducado (vale 30 segundos).
    gateway.show_qr_console = (
        not args.no_qr and not args.no_auth and qr.supports_color()
    )
    print_banner(
        shown_host, args.port, gateway.pin, not args.no_auth,
        login_key=gateway.login_key, show_qr=not args.no_qr,
    )

    if not args.no_browser and shown_host not in ("127.0.0.1", "localhost"):
        webbrowser.open(f"http://127.0.0.1:{args.port}/qr")

    loop = asyncio.get_running_loop()
    animations = loop.create_task(gateway.animation_loop())
    keyboard = loop.create_task(watch_enter_key(gateway))
    try:
        await asyncio.Event().wait()          # corre hasta Ctrl+C
    except asyncio.CancelledError:
        pass
    finally:
        for task in (animations, keyboard):
            task.cancel()
        await gateway.shutdown()
        await runner.cleanup()


async def watch_enter_key(gateway: Gateway) -> None:
    """
    Pulsar ENTER en la consola imprime un QR nuevo al instante.

    Es el respaldo del redibujado automatico: si la consola no admite colores o
    el codigo ya ha caducado, el usuario tiene una forma directa de pedir otro.
    """
    if not gateway.show_qr_console:
        return

    loop = asyncio.get_running_loop()

    def read_line() -> str:
        try:
            return input()
        except (EOFError, KeyboardInterrupt, OSError):
            return "\x00"          # senal para terminar

    try:
        while True:
            line = await loop.run_in_executor(None, read_line)
            if line == "\x00":
                return
            gateway.refresh_login_key()
            print_qr_block(gateway.console_host, gateway.port,
                           gateway.login_key, when="codigo nuevo")
    except asyncio.CancelledError:
        pass
    except Exception:
        log.debug("lectura de ENTER terminada", exc_info=True)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RemotePad: usa tu celular como touchpad del PC."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="puerto (def. 8765)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="interfaz de escucha (def. 0.0.0.0)"
    )
    parser.add_argument("--no-auth", action="store_true", help="desactivar el PIN")
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
