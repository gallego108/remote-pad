"""
Despertador de RemotePad: enciende el servidor desde el celular.

Arranca con Windows (sin ventana, con pythonw) y casi no gasta nada: no mueve
el puntero ni toca el teclado, solo vigila el puerto de RemotePad (8765).

  - Si el servidor esta apagado, el despertador ocupa ese puerto y responde
    con una pagina "RemotePad esta apagado - Encender". Asi el icono del
    celular siempre abre algo, tambien por HTTP normal.
  - Al pulsar "Encender" comprueba que el celular este autorizado (con el
    acceso que ya guarda de antes; tokens.json solo tiene huellas), suelta el
    puerto y arranca iniciar.bat en su consola. La pagina se recarga sola en
    cuanto el servidor responde.
  - Si arrancas el servidor a mano, este le pide (desde la propia PC) que
    suelte el puerto. Cuando el servidor se cierra, el despertador lo vuelve
    a ocupar.

Uso:
    pythonw server/despertador.py                  # lo normal (sin ventana)
    python server/despertador.py --port 8765 --https
Instalacion: python tools/instalar_despertador.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

SERVER_DIR = Path(__file__).resolve().parent
RAIZ = SERVER_DIR.parent
WEB = RAIZ / "web"
LANZADOR = RAIZ / "iniciar.bat"
sys.path.insert(0, str(SERVER_DIR))

import auth  # noqa: E402

log = logging.getLogger("despertador")

CABECERA = "X-RemotePad-Despertador"
RUTA_ESTADO = "/__despertador/estado"
RUTA_ENCENDER = "/__despertador/encender"
RUTA_SOLTAR = "/__despertador/soltar"
# Tras arrancar (o ceder el puerto a) el servidor, cuanto se espera antes de
# volver a ocupar el puerto si sigue libre (el servidor tarda en arrancar).
ESPERA_ARRANQUE = 40.0
VIGILANCIA = 2.0
# Fallos de token permitidos por direccion antes de bloquearla un rato.
MAX_FALLOS = 8
BLOQUEO = 300.0
ESTATICOS = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}


def puerto_ocupado(puerto: int) -> bool:
    """Hay algo escuchando en el puerto (normalmente, el servidor)."""
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.6):
            return True
    except OSError:
        return False


def es_local(addr: str) -> bool:
    return addr in ("127.0.0.1", "::1", "localhost") or addr.startswith("127.")


class _Servidor(ThreadingHTTPServer):
    # En Windows, SO_REUSEADDR deja que DOS programas abran el mismo puerto:
    # el despertador y el servidor se repartirian las conexiones. No.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Despertador:
    def __init__(self, puerto: int = 8765, host: str = "0.0.0.0",
                 args_servidor: Optional[list[str]] = None,
                 contexto_ssl: Optional[ssl.SSLContext] = None,
                 lanzar: Optional[Callable[[], None]] = None) -> None:
        self.puerto = puerto
        self.host = host
        self.args_servidor = list(args_servidor or [])
        self.contexto_ssl = contexto_ssl
        self._lanzar = lanzar or self._lanzar_servidor
        self._httpd: Optional[_Servidor] = None
        self._cerrojo = threading.RLock()
        self._cedido_en = 0.0            # ultima vez que se cedio el puerto
        self._fallos: dict[str, list[float]] = {}
        self._parar = threading.Event()

    # ------------------------------------------------------------ puerto
    @property
    def escuchando(self) -> bool:
        return self._httpd is not None

    def ocupar(self) -> bool:
        """Abre el puerto con la pagina de "Encender". False si esta en uso."""
        with self._cerrojo:
            if self._httpd is not None:
                return True
            try:
                httpd = _Servidor((self.host, self.puerto), _Manejador)
            except OSError:
                return False
            if self.contexto_ssl is not None:
                httpd.socket = self.contexto_ssl.wrap_socket(httpd.socket, server_side=True)
            httpd.despertador = self
            self._httpd = httpd
            threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.3},
                             name="despertador-http", daemon=True).start()
            log.info("Puerto %d ocupado: esperando a que el celular pida encender",
                     self.puerto)
            return True

    def soltar(self, motivo: str = "") -> None:
        """Cierra el puerto para que lo use el servidor."""
        with self._cerrojo:
            httpd, self._httpd = self._httpd, None
            self._cedido_en = time.monotonic()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            log.info("Puerto %d liberado (%s)", self.puerto, motivo or "sin motivo")

    def vigilar_una_vez(self) -> None:
        """Si el servidor no esta y ya paso la espera, vuelve a ocupar el puerto."""
        if self.escuchando:
            return
        if time.monotonic() - self._cedido_en < ESPERA_ARRANQUE:
            return
        if puerto_ocupado(self.puerto):
            return
        self.ocupar()

    def bucle(self) -> None:
        while not self._parar.is_set():
            try:
                self.vigilar_una_vez()
            except Exception:
                log.exception("Fallo vigilando el puerto")
            self._parar.wait(VIGILANCIA)

    def parar(self) -> None:
        self._parar.set()
        self.soltar("parada")

    # ------------------------------------------------------------ encender
    def bloqueado(self, addr: str) -> bool:
        ahora = time.monotonic()
        recientes = [t for t in self._fallos.get(addr, []) if ahora - t < BLOQUEO]
        self._fallos[addr] = recientes
        return len(recientes) >= MAX_FALLOS

    def anotar_fallo(self, addr: str) -> None:
        self._fallos.setdefault(addr, []).append(time.monotonic())

    def autorizado(self, token: str) -> bool:
        """Mismo criterio que el servidor: un dispositivo con acceso, o acceso libre."""
        if auth.load_config().get("auth_required") is False:
            return True
        if not token:
            return False
        return auth.Dispositivos().validar(token) is not None

    def encender(self, addr: str) -> None:
        log.info("Encendido pedido desde %s", addr)
        self.soltar(f"encender desde {addr}")
        try:
            self._lanzar()
        except Exception:
            log.exception("No se pudo arrancar el servidor")
            self._cedido_en = 0.0          # se vuelve a ocupar en la siguiente vuelta

    def _lanzar_servidor(self) -> None:
        """Abre iniciar.bat con su consola (via cmd.exe, firmado: sin aviso)."""
        cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
        extra = " ".join(self.args_servidor)
        linea = f'"{cmd}" /c ""{LANZADOR}" --no-browser {extra}"'
        subprocess.Popen(linea, cwd=str(RAIZ),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


class _Manejador(BaseHTTPRequestHandler):
    server_version = "RemotePad-Despertador"
    sys_version = ""

    @property
    def despertador(self) -> Despertador:
        return self.server.despertador  # type: ignore[attr-defined]

    def log_message(self, formato: str, *args) -> None:  # silencio en consola
        log.debug("%s - %s", self.client_address[0], formato % args)

    def _responder(self, estado: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(CABECERA, "1")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, estado: int, datos: dict) -> None:
        self._responder(estado, json.dumps(datos).encode("utf-8"), "application/json")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        ruta = urlsplit(self.path).path
        if ruta in ("/", "/index.html"):
            pagina = (WEB / "despertador.html").read_bytes()
            self._responder(HTTPStatus.OK, pagina, "text/html; charset=utf-8")
        elif ruta == RUTA_ESTADO:
            self._json(HTTPStatus.OK, {"despertador": True, "servidor": False})
        elif ruta in ESTATICOS:
            nombre, tipo = ESTATICOS[ruta]
            self._responder(HTTPStatus.OK, (WEB / nombre).read_bytes(), tipo)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "RemotePad esta apagado"})

    def _mismo_origen(self) -> bool:
        origen = self.headers.get("Origin")
        if not origen:
            return True        # peticiones sin Origin (p. ej. desde la PC)
        return urlsplit(origen).netloc == (self.headers.get("Host") or "")

    def do_POST(self) -> None:
        ruta = urlsplit(self.path).path
        addr = self.client_address[0]
        if ruta == RUTA_SOLTAR:
            # Solo la propia PC (el servidor al arrancar a mano).
            if not es_local(addr):
                self._json(HTTPStatus.FORBIDDEN, {"error": "solo desde la PC"})
                return
            self._json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=self.despertador.soltar, args=("servidor manual",),
                             daemon=True).start()
            return
        if ruta != RUTA_ENCENDER:
            self._json(HTTPStatus.NOT_FOUND, {"error": "no existe"})
            return
        if not self._mismo_origen():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origen no permitido"})
            return
        if self.despertador.bloqueado(addr):
            self._json(HTTPStatus.TOO_MANY_REQUESTS,
                       {"error": "Demasiados intentos. Espera unos minutos."})
            return
        try:
            largo = min(int(self.headers.get("Content-Length") or 0), 4096)
            datos = json.loads(self.rfile.read(largo) or b"{}")
            token = str(datos.get("token") or "")[:200]
        except (ValueError, AttributeError):
            token = ""
        if not self.despertador.autorizado(token):
            self.despertador.anotar_fallo(addr)
            log.warning("Encendido rechazado desde %s (sin acceso valido)", addr)
            self._json(HTTPStatus.FORBIDDEN, {
                "error": "Este celular no tiene acceso. Entra una vez con el QR o "
                         "el PIN mientras RemotePad está encendido en la PC.",
            })
            return
        self._json(HTTPStatus.OK, {"ok": True})
        # Se responde antes de soltar el puerto: si no, el celular no recibe nada.
        threading.Timer(0.3, self.despertador.encender, args=(addr,)).start()


def pedir_puerto(puerto: int, https: bool, espera: float = 6.0) -> bool:
    """
    Lo usa el servidor al arrancar: si el despertador tiene el puerto, le pide
    que lo suelte y espera a que quede libre. True si lo ha soltado.
    """
    import urllib.request

    esquema = "https" if https else "http"
    contexto = ssl._create_unverified_context() if https else None  # es la propia PC
    peticion = urllib.request.Request(
        f"{esquema}://127.0.0.1:{puerto}{RUTA_SOLTAR}", data=b"{}", method="POST"
    )
    try:
        with urllib.request.urlopen(peticion, timeout=1.5, context=contexto) as respuesta:
            if respuesta.headers.get(CABECERA) != "1":
                return False
    except Exception:
        return False
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if not puerto_ocupado(puerto):
            return True
        time.sleep(0.2)
    return False


def _instancia_unica(puerto: int):
    """Un solo despertador por puerto (cerrojo en un archivo temporal)."""
    import msvcrt
    import tempfile

    ruta = Path(tempfile.gettempdir()) / f"remotepad-despertador-{puerto}.lock"
    archivo = open(ruta, "w")
    try:
        msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return archivo


def _configurar_registro() -> None:
    manejador = RotatingFileHandler(SERVER_DIR / "despertador.log", maxBytes=200_000,
                                    backupCount=1, encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(manejador)
    if sys.stdout is not None:          # con python.exe tambien se ve en consola
        log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def main() -> int:
    parser = argparse.ArgumentParser(description="Despertador de RemotePad")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--https", action="store_true",
                        help="el servidor se usa con --https (mismo certificado)")
    args = parser.parse_args()
    _configurar_registro()

    cerrojo = _instancia_unica(args.port)
    if cerrojo is None:
        log.info("Ya hay un despertador vigilando el puerto %d", args.port)
        return 0

    contexto = None
    if args.https:
        try:
            import certificado
            from app import local_ip
            contexto = certificado.preparar(local_ip()).contexto_ssl()
        except Exception:
            log.exception("No se pudo preparar HTTPS; el despertador no arranca")
            return 1

    despertador = Despertador(args.port, args.host,
                              ["--https"] if args.https else [], contexto)
    log.info("Despertador de RemotePad en marcha (puerto %d)", args.port)
    try:
        despertador.bucle()
    except KeyboardInterrupt:
        pass
    finally:
        despertador.parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
