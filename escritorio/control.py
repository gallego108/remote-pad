"""
Control del servidor de RemotePad para la app de escritorio.

Sin ventana ni Win32: habla con el servidor por su API local (/api/admin/*),
arranca y para el proceso, y lee el registro y los ajustes de disco cuando el
servidor esta apagado. Asi se puede probar sin abrir ninguna ventana.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

RAIZ = Path(__file__).resolve().parent.parent
# Empaquetado (PyInstaller), los recursos (web, iconos, app.py para la version) van dentro del ejecutable.
ES_EJECUTABLE = bool(getattr(sys, "frozen", False))
RECURSOS = Path(getattr(sys, "_MEIPASS", RAIZ))
SERVIDOR = RECURSOS / "server" if ES_EJECUTABLE else RAIZ / "server"
if str(SERVIDOR) not in sys.path:
    sys.path.insert(0, str(SERVIDOR))

import auth  # noqa: E402  (despues de tocar sys.path)
import historial  # noqa: E402

# Las pruebas redirigen estos archivos con variables de entorno, igual que el servidor.
LOG_FILE = Path(os.environ.get("REMOTEPAD_LOG") or (SERVIDOR / "servidor.log"))
CONSOLA_FILE = Path(os.environ.get("REMOTEPAD_CONSOLA") or (SERVIDOR / "consola.log"))
AJUSTES_FILE = Path(os.environ.get("REMOTEPAD_ESCRITORIO") or (SERVIDOR / "escritorio.json"))

AJUSTES_POR_DEFECTO: dict[str, Any] = {
    "puerto": 8765,
    "red": "0.0.0.0",            # 0.0.0.0 = el celular puede entrar; 127.0.0.1 = solo esta PC
    "https": False,
    "arrancar_servidor": True,   # al abrir la app, enciende RemotePad si esta apagado
    "inicio_windows": True,      # la app se abre sola al encender el PC (en la bandeja)
}

CREATE_NO_WINDOW = 0x08000000
PATRON_LINEA = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*)$")


# ------------------------------------------------------------------ ajustes
def _validar(crudos: dict[str, Any]) -> dict[str, Any]:
    """Deja solo valores correctos; lo que no lo sea vuelve al valor por defecto."""
    limpios = dict(AJUSTES_POR_DEFECTO)
    try:
        puerto = int(crudos.get("puerto", limpios["puerto"]))
        if 1 <= puerto <= 65535:
            limpios["puerto"] = puerto
    except (TypeError, ValueError):
        pass
    if crudos.get("red") in ("0.0.0.0", "127.0.0.1"):
        limpios["red"] = crudos["red"]
    for clave in ("https", "arrancar_servidor", "inicio_windows"):
        if isinstance(crudos.get(clave), bool):
            limpios[clave] = crudos[clave]
    return limpios


def ajustes_lanzamiento() -> dict[str, Any]:
    """Ajustes de la propia app (puerto, red, arranque), ya validados."""
    try:
        crudos = json.loads(AJUSTES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        crudos = {}
    return _validar(crudos if isinstance(crudos, dict) else {})


def guardar_ajustes_lanzamiento(cambios: dict[str, Any]) -> dict[str, Any]:
    """Aplica los cambios a los ajustes actuales, los valida y los guarda."""
    datos = ajustes_lanzamiento()
    datos.update({k: v for k, v in cambios.items() if k in AJUSTES_POR_DEFECTO})
    limpios = _validar(datos)
    AJUSTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    auth.write_json_atomic(AJUSTES_FILE, limpios)
    return limpios


# --------------------------------------------------------------- API local
def _llamar(puerto: int, https: bool, metodo: str, ruta: str,
            datos: Optional[dict] = None, timeout: float = 2.0) -> Optional[dict]:
    """Llama a la API local del servidor. Devuelve None si no responde con JSON."""
    esquema = "https" if https else "http"
    cuerpo = None
    cabeceras = {}
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(
        f"{esquema}://127.0.0.1:{puerto}{ruta}", data=cuerpo, method=metodo, headers=cabeceras)
    contexto = None
    if https:
        # Certificado local autofirmado, y solo hablamos con 127.0.0.1.
        contexto = ssl.create_default_context()
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(peticion, timeout=timeout, context=contexto) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        # Tambien cubre el despertador: responde HTML en ese mismo puerto.
        return None


def servidor_en_marcha(puerto: int, https: bool = False) -> bool:
    return _llamar(puerto, https, "GET", "/healthz", timeout=1.0) is not None


def estado_servidor(puerto: int, https: bool = False) -> Optional[dict]:
    return _llamar(puerto, https, "GET", "/api/admin/estado")


def consultar_servidor(puerto: int, https: bool, ruta: str) -> Optional[dict]:
    return _llamar(puerto, https, "GET", ruta)


def accion_servidor(puerto: int, https: bool, ruta: str, datos: Optional[dict] = None) -> Optional[dict]:
    return _llamar(puerto, https, "POST", ruta, datos if datos is not None else {}, timeout=5.0)


# ---------------------------------------------------------- proceso servidor
def python_de_fondo() -> str:
    """pythonw.exe no abre consola; si no existe, se usa el que hay."""
    candidato = Path(sys.executable).with_name("pythonw.exe")
    return str(candidato if candidato.is_file() else sys.executable)


def ejecutable_servidor() -> Path:
    """Empaquetado, el servidor va en la subcarpeta 'servidor' de la instalacion."""
    return Path(sys.executable).parent / "servidor" / "RemotePadServidor.exe"


def arrancar(ajustes: dict[str, Any]) -> subprocess.Popen:
    """Arranca el servidor en segundo plano, sin ventana, y guarda su salida en consola.log."""
    if ES_EJECUTABLE:
        args = [str(ejecutable_servidor())]
    else:
        args = [python_de_fondo(), "app.py"]
    args += ["--no-browser", "--port", str(ajustes["puerto"]), "--host", ajustes["red"]]
    if ajustes["https"]:
        args.append("--https")
    entorno = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    CONSOLA_FILE.parent.mkdir(parents=True, exist_ok=True)
    salida = open(CONSOLA_FILE, "w", encoding="utf-8")
    try:
        return subprocess.Popen(
            args, cwd=str(SERVIDOR), stdin=subprocess.DEVNULL,
            stdout=salida, stderr=subprocess.STDOUT, env=entorno,
            creationflags=CREATE_NO_WINDOW,
        )
    finally:
        salida.close()    # el proceso hereda su propia copia del descriptor


def esperar_apagado(puerto: int, https: bool = False, segundos: float = 8.0) -> bool:
    """
    Espera a que el servidor deje de responder. Se mira la API y no el puerto:
    al apagarse, el despertador ocupa ese mismo puerto y el puerto nunca queda libre.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if not servidor_en_marcha(puerto, https):
            return True
        time.sleep(0.25)
    return False


# ------------------------------------------------------ arranque con Windows
RUTA_ACCESO = "RemotePad.lnk"


def carpeta_inicio() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup")


def crear_acceso(destino: Path, objetivo: Path, argumentos: str, carpeta: Path,
                 descripcion: str, icono: Path) -> None:
    """Crea (o actualiza) un acceso directo .lnk con PowerShell, sin depender de tools/."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RP_LNK);"
        "$s.TargetPath = $env:RP_CMD;"
        "$s.Arguments = $env:RP_ARGS;"
        "$s.WorkingDirectory = $env:RP_DIR;"
        "$s.IconLocation = $env:RP_ICO + ',0';"
        "$s.Description = $env:RP_DESC;"
        "$s.Save()"
    )
    entorno = dict(os.environ, RP_LNK=str(destino), RP_CMD=str(objetivo), RP_ARGS=argumentos,
                   RP_DIR=str(carpeta), RP_ICO=str(icono), RP_DESC=descripcion)
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=entorno, check=True)


def sincronizar_inicio(activo: bool) -> None:
    """Crea o quita el acceso directo que abre la app al iniciar sesion (en segundo plano)."""
    enlace = carpeta_inicio() / RUTA_ACCESO
    if not activo:
        if enlace.exists():
            enlace.unlink()
        return
    descripcion = "RemotePad: panel de escritorio (en segundo plano)"
    icono = RECURSOS / "remotepad.ico"
    if ES_EJECUTABLE:
        objetivo = Path(sys.executable)
        argumentos = "--en-segundo-plano"
        carpeta = objetivo.parent
    else:
        script = Path(__file__).resolve().parent / "remotepad_escritorio.py"
        objetivo = Path(python_de_fondo())
        argumentos = f'"{script}" --en-segundo-plano'
        carpeta = script.parent
    crear_acceso(enlace, objetivo, argumentos, carpeta, descripcion, icono)


# ------------------------------------------------------------------ registro
def leer_registro(maximo: int = 1500) -> list[dict]:
    """
    Ultimas lineas del registro como [{hora, nivel, texto}]. Las lineas sin
    marca de hora (trazas de error) se pegan a la entrada anterior.
    """
    try:
        lineas = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entradas: list[dict] = []
    for linea in lineas[-maximo * 2:]:
        encontrado = PATRON_LINEA.match(linea)
        if encontrado:
            entradas.append({"hora": encontrado.group(1), "nivel": encontrado.group(2),
                             "texto": encontrado.group(3)})
        elif entradas and linea.strip():
            entradas[-1]["texto"] += "\n" + linea
    return entradas[-maximo:]


# ---------------------------------------------- lectura sin servidor (disco)
def dispositivos_en_disco() -> list[dict]:
    filas = []
    for fila in auth.Dispositivos().listar():
        fila.pop("huella", None)
        fila["actual"] = False
        fila["conectado"] = False
        filas.append(fila)
    return filas


def revocar_en_disco(prefijo: str) -> Optional[str]:
    dispositivos = auth.Dispositivos()
    nombres = {f["id"]: f["nombre"] for f in dispositivos.listar()}
    retirados = dispositivos.revocar(prefijo)
    if not retirados:
        return None
    return nombres.get(retirados[0][:8], retirados[0][:8])


def programas_en_disco() -> list[dict]:
    return historial.Historial().lista()["programs"]


def quitar_programa_en_disco(clave: str) -> bool:
    anotado = historial.Historial()
    quitado = anotado.quitar(clave)
    anotado.guardar()
    return quitado
