"""
Control de acceso de RemotePad.

Reune todo lo que decide QUIEN puede manejar la PC:

- el PIN de 6 digitos que rota cada 5 minutos;
- las claves de un solo uso del codigo QR (con margen de gracia);
- los limites de intentos fallidos;
- los dispositivos autorizados (`Dispositivos`), que se guardan en disco.

No sabe nada de WebSocket ni del mouse: `app.py` le pregunta y actua. Asi se
puede probar sin servidor ni sistema operativo.

Los tokens NO se guardan en claro: en `tokens.json` solo esta su huella
SHA-256. Quien copie el archivo no obtiene un acceso valido.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("remotepad")

SERVER_DIR = Path(__file__).resolve().parent

# Ajustes que se recuerdan entre arranques (codigo de acceso, confirmacion).
# Las pruebas usan REMOTEPAD_CONFIG para no tocar el archivo real.
CONFIG_FILE = Path(os.environ.get("REMOTEPAD_CONFIG") or (SERVER_DIR / "config.json"))
# Dispositivos autorizados. Las pruebas usan REMOTEPAD_TOKENS.
TOKENS_FILE = Path(os.environ.get("REMOTEPAD_TOKENS") or (SERVER_DIR / "tokens.json"))

PIN_ROTATE_SECONDS = 300.0   # cada cuanto cambia el PIN de seguridad
QR_VALID_SECONDS = 180.0     # cuanto vale cada codigo QR (3 minutos, un solo uso)

# Margen de gracia de los codigos QR.
#
# Por que existe: el codigo visible cambia cada QR_VALID_SECONDS, y si alguien
# esta escaneando justo en ese momento, el codigo que acaba de leer dejaria de
# valer y el acceso fallaria. Con este margen se sigue aceptando el codigo
# anterior unos segundos despues de rotar, que es justo el tiempo que el canje
# puede llegar tarde por el retardo de la red o del navegador.
QR_GRACE_SECONDS = 20.0

TOKEN_TTL_SECONDS = 30 * 24 * 3600
FAILURE_WINDOW_SECONDS = 300.0
MAX_PIN_FAILURES = 8
MAX_QR_FAILURES = 10


# ------------------------------------------------------------------ archivos
def write_json_atomic(path: Path, data: Any) -> bool:
    """
    Escribe JSON sin dejar nunca el archivo a medias.

    Se escribe en un temporal de la misma carpeta y se sustituye de golpe con
    os.replace: si el proceso muere en mitad de la escritura, el archivo
    anterior sigue intacto. Con write_text directo, un corte dejaba un JSON
    roto y todos los dispositivos perdian el acceso.
    """
    path = Path(path)
    temporal = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporal.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        # En Windows, un antivirus o un indexador puede tener el destino
        # abierto un instante: se reintenta antes de rendirse.
        for intento in range(5):
            try:
                os.replace(temporal, path)
                return True
            except PermissionError:
                if intento == 4:
                    raise
                time.sleep(0.05 * (intento + 1))
    except Exception as exc:
        log.warning("No se pudo guardar %s: %s", path.name, exc)
        try:
            temporal.unlink()
        except OSError:
            pass
    return False


def read_json(path: Path, descripcion: str = "") -> Any:
    """Lee JSON; None si no existe o esta roto (se avisa en el registro)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("No se pudo leer %s (%s)%s", Path(path).name, exc,
                    f": {descripcion}" if descripcion else "")
        return None


def load_config() -> dict:
    """
    Lee los ajustes guardados entre arranques.

    Si el archivo no existe o esta mal, se usan los valores por defecto: es
    preferible arrancar siempre que quedarse sin servidor por un JSON roto.
    """
    datos = read_json(CONFIG_FILE, "se usan los valores por defecto")
    return datos if isinstance(datos, dict) else {}


def save_config(cambios: dict) -> None:
    """Guarda ajustes sin perder los que ya hubiera."""
    datos = load_config()
    datos.update(cambios)
    write_json_atomic(CONFIG_FILE, datos)


# ------------------------------------------------------------------- claves
def new_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_login_key() -> str:
    """Clave corta y aleatoria que viaja dentro del enlace del codigo QR."""
    return secrets.token_urlsafe(9)


def token_hash(token: str) -> str:
    """Huella del token: es lo unico que se guarda y lo que identifica al equipo."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


_HUELLA = re.compile(r"^[0-9a-f]{64}$")


def is_hash(valor: str) -> bool:
    return bool(_HUELLA.match(str(valor)))


def device_name(user_agent: str) -> str:
    """
    Nombre legible del dispositivo a partir del User-Agent del navegador.

    Chrome recorta el modelo en Android modernos ("Android 10; K"), asi que si
    no hay modelo util se queda en el sistema. Nunca falla: como mucho devuelve
    "Dispositivo".
    """
    agente = str(user_agent or "")
    android = re.search(r"Android\s+([\d.]+);\s*([^;)]+)", agente)
    if android:
        modelo = android.group(2).strip()
        if modelo and modelo != "K" and "Build" not in modelo:
            return f"{modelo} (Android {android.group(1)})"
        return f"Android {android.group(1)}"
    if "iPhone" in agente:
        return "iPhone"
    if "iPad" in agente:
        return "iPad"
    if "Windows" in agente:
        return "Navegador en Windows"
    if "Mac OS" in agente:
        return "Navegador en Mac"
    if "Linux" in agente:
        return "Navegador en Linux"
    if agente:
        return agente[:40]
    return "Dispositivo"


# ------------------------------------------------------------- dispositivos
class Dispositivos:
    """
    Dispositivos autorizados, guardados en disco.

    Formato de `tokens.json` (version 2):

        {"version": 2, "dispositivos": {
            "<sha256 del token>": {"creado": ..., "visto": ..., "nombre": "...",
                                   "addr": "..."}}}

    La version 1 guardaba {token_en_claro: creado}; al leerla se convierte y
    se reescribe ya con huellas, sin que nadie tenga que volver a entrar.
    """

    def __init__(self, archivo: Optional[Path] = None) -> None:
        self.archivo = Path(archivo or TOKENS_FILE)
        self._datos: dict[str, dict] = {}
        self._cargar()

    # ---------------------------------------------------------------- disco
    def _cargar(self) -> None:
        crudo = read_json(self.archivo, "se pedira el PIN de nuevo")
        if not isinstance(crudo, dict):
            return
        migrado = False
        if "dispositivos" in crudo and isinstance(crudo["dispositivos"], dict):
            origen = crudo["dispositivos"]
        else:
            # Version 1: {token: creado}. Se pasa a huellas.
            origen = {}
            for token, creado in crudo.items():
                origen[token_hash(token)] = {"creado": creado}
            migrado = bool(origen)

        for huella, info in origen.items():
            if not is_hash(huella) or not isinstance(info, dict):
                continue
            try:
                creado = float(info.get("creado", 0))
            except (TypeError, ValueError):
                continue
            try:
                visto = float(info.get("visto", creado))
            except (TypeError, ValueError):
                visto = creado
            self._datos[huella] = {
                "creado": creado,
                "visto": visto,
                "nombre": str(info.get("nombre") or "Dispositivo")[:60],
                "addr": str(info.get("addr") or "")[:60],
            }
        quitados = self.podar(guardar=False)
        if migrado:
            log.info("Accesos convertidos al formato nuevo (solo huellas, sin "
                     "tokens en claro)")
        if migrado or quitados:
            self.guardar()

    def guardar(self) -> None:
        write_json_atomic(self.archivo, {"version": 2, "dispositivos": self._datos})

    # ------------------------------------------------------------- consultas
    def __len__(self) -> int:
        return len(self._datos)

    def __contains__(self, huella: str) -> bool:
        return huella in self._datos

    def podar(self, guardar: bool = True) -> list[str]:
        """Quita los accesos caducados. Devuelve sus huellas."""
        corte = time.time() - TOKEN_TTL_SECONDS
        caducados = [h for h, info in self._datos.items() if info["creado"] < corte]
        for huella in caducados:
            del self._datos[huella]
        if caducados and guardar:
            self.guardar()
        return caducados

    def validar(self, token: Any) -> Optional[str]:
        """Huella del dispositivo si el token vale; None si no."""
        if not token or not isinstance(token, str) or len(token) > 200:
            return None
        self.podar()
        huella = token_hash(token)
        # La busqueda es por huella: comparar con compare_digest contra cada
        # huella guardada evita depender del tiempo que tarda el diccionario.
        for conocida in self._datos:
            if hmac.compare_digest(conocida, huella):
                return conocida
        return None

    def emitir(self, nombre: str = "", addr: str = "") -> tuple[str, str]:
        """Crea un acceso nuevo. Devuelve (token, huella)."""
        token = secrets.token_urlsafe(24)
        huella = token_hash(token)
        ahora = time.time()
        self._datos[huella] = {
            "creado": ahora,
            "visto": ahora,
            "nombre": (nombre or "Dispositivo")[:60],
            "addr": (addr or "")[:60],
        }
        self.podar(guardar=False)
        # Se guarda en disco: el dispositivo no tendra que volver a pedir el PIN
        # aunque el servidor se reinicie (hasta que caduque, 30 dias).
        self.guardar()
        return token, huella

    def visto(self, huella: str, addr: str = "", nombre: str = "") -> None:
        """Anota la ultima conexion (para la lista de dispositivos)."""
        info = self._datos.get(huella)
        if info is None:
            return
        info["visto"] = time.time()
        if addr:
            info["addr"] = addr[:60]
        if nombre and info.get("nombre") in ("", "Dispositivo"):
            info["nombre"] = nombre[:60]
        self.guardar()

    def revocar(self, prefijo: str) -> list[str]:
        """
        Retira el acceso de los dispositivos cuya huella empieza por `prefijo`.

        Se exige un prefijo de al menos 6 caracteres y que identifique a UN
        solo dispositivo: asi un error al teclear no borra varios a la vez.
        Devuelve las huellas retiradas (vacia si no hay coincidencia unica).
        """
        prefijo = str(prefijo or "").strip().lower()
        if len(prefijo) < 6:
            return []
        coincidencias = [h for h in self._datos if h.startswith(prefijo)]
        if len(coincidencias) != 1:
            return []
        del self._datos[coincidencias[0]]
        self.guardar()
        return coincidencias

    def listar(self) -> list[dict]:
        """Dispositivos ordenados por ultima conexion (el mas reciente primero)."""
        filas = [
            {
                "id": huella[:8],
                "huella": huella,
                "nombre": info["nombre"],
                "addr": info["addr"],
                "creado": info["creado"],
                "visto": info["visto"],
                "caduca": info["creado"] + TOKEN_TTL_SECONDS,
            }
            for huella, info in self._datos.items()
        ]
        filas.sort(key=lambda fila: fila["visto"], reverse=True)
        return filas


# ------------------------------------------------------------ control acceso
class ControlAcceso:
    """
    PIN, codigos QR e intentos fallidos.

    `avisar` recibe los mensajes que deben llegar a los clientes conectados
    (PIN nuevo, clave nueva, cambio de modo); lo pone `Gateway`.
    """

    def __init__(self, avisar: Optional[Callable[[dict], None]] = None,
                 dispositivos: Optional[Dispositivos] = None) -> None:
        self._avisar = avisar or (lambda payload: None)
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
        self._pin_failures: dict[str, list[float]] = {}
        self.dispositivos = dispositivos if dispositivos is not None else Dispositivos()

    # ------------------------------------------------------------------- PIN
    def rotate_pin_if_needed(self) -> None:
        if time.monotonic() - self._pin_generated < PIN_ROTATE_SECONDS:
            return
        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        log.info("Nuevo PIN de seguridad: %s", self.pin)
        self._avisar({"t": "pin", "pin": self.pin})

    def regenerar_pin(self, motivo: str = "") -> str:
        """Genera un PIN nuevo ahora mismo (pedido desde la app de escritorio)."""
        self.pin = new_pin()
        self._pin_generated = time.monotonic()
        log.info("Nuevo PIN de seguridad%s: %s", f" {motivo}".rstrip(), self.pin)
        self._avisar({"t": "pin", "pin": self.pin})
        return self.pin

    def pin_seconds_left(self) -> int:
        remaining = PIN_ROTATE_SECONDS - (time.monotonic() - self._pin_generated)
        return max(0, int(remaining))

    def check_pin(self, pin: Any, addr: str = "?") -> bool:
        # Con el control de acceso desactivado entra cualquiera de la red: es
        # comodo para probar, pero cualquiera en tu WiFi puede manejar la PC.
        if not self.auth_required:
            return True
        if self._bloqueado(self._pin_failures, addr, MAX_PIN_FAILURES):
            return False
        if hmac.compare_digest(str(pin or ""), self.pin):
            self._pin_failures.pop(addr, None)
            return True
        self._pin_failures.setdefault(addr, []).append(time.time())
        return False

    # ----------------------------------------------------------- fallos
    @staticmethod
    def _bloqueado(registro: dict[str, list[float]], addr: str, maximo: int) -> bool:
        recientes = [t for t in registro.get(addr, [])
                     if time.time() - t < FAILURE_WINDOW_SECONDS]
        if recientes:
            registro[addr] = recientes
        else:
            registro.pop(addr, None)
        return len(recientes) >= maximo

    def prune_failures(self) -> None:
        """
        Olvida las direcciones sin fallos recientes.

        Sin esto los diccionarios de fallos crecian con cada direccion que
        alguna vez se equivoco, y nunca se vaciaban.
        """
        ahora = time.time()
        for registro in (self._pin_failures, self._key_failures):
            for addr in list(registro):
                recientes = [t for t in registro[addr]
                             if ahora - t < FAILURE_WINDOW_SECONDS]
                if recientes:
                    registro[addr] = recientes
                else:
                    del registro[addr]

    # ------------------------------------------------------------- codigo QR
    def rotate_qr_key_if_needed(self) -> None:
        """
        El codigo QR vale 3 minutos.

        Pasado ese tiempo se genera otro automaticamente, de modo que el panel
        de la PC siempre muestra un codigo vigente. El anterior NO se invalida
        de golpe: queda unos segundos en el margen de gracia por si el celular
        estaba escaneandolo justo en ese momento.
        """
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
        self._avisar({"t": "qr_key", "key": self.login_key})
        return self.login_key

    def _podar_historial(self, ahora: Optional[float] = None) -> None:
        """Descarta las claves antiguas que ya pasaron el margen de gracia."""
        if ahora is None:
            ahora = time.monotonic()
        while self._key_history:
            _clave, nacida, usada = self._key_history[0]
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

    def canjear_clave(self, key: Any, addr: str = "?") -> bool:
        """
        Comprueba y consume la clave del QR.

        Acepta la clave vigente y tambien las anteriores mientras esten dentro
        del margen de gracia: asi, si el codigo se renovo mientras el celular
        lo escaneaba, el acceso no falla. Cada clave sirve una sola vez.

        Con el control de acceso desactivado se acepta sin mirar la clave: el
        QR no es necesario.
        """
        if not self.auth_required:
            return True
        if not key:
            return False
        if self._bloqueado(self._key_failures, addr, MAX_QR_FAILURES):
            return False

        candidata = str(key)
        if self.login_key and hmac.compare_digest(candidata, self.login_key):
            self._key_failures.pop(addr, None)
            self._marcar_clave_usada(candidata)
            return True

        # Margen de gracia: claves recien rotadas, aun sin usar.
        self._podar_historial()
        for anterior, _nacida, ya_usada in self._key_history:
            if hmac.compare_digest(candidata, anterior):
                if ya_usada:
                    break
                self._key_failures.pop(addr, None)
                self._marcar_clave_usada(candidata)
                return True
        self._key_failures.setdefault(addr, []).append(time.time())
        return False

    # ------------------------------------------------------------- modo libre
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
            self._avisar({"t": "auth_mode", "required": True, "pin": self.pin})
        else:
            log.warning("Control de acceso DESACTIVADO%s: cualquiera en tu "
                        "WiFi puede manejar la PC", f" {motivo}".rstrip())
            self._avisar({"t": "auth_mode", "required": False})
        return True
