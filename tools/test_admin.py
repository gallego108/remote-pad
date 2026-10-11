"""
Pruebas de la app de escritorio y de su API de administracion.

  A) La API /api/admin/* responde a la PC y rechaza lo que no es de la app:
     una cabecera Origin (navegador) o un cuerpo que no sea JSON.
  B) Los cambios desde la app se aplican: PIN nuevo, codigo de acceso,
     QR (sin cambiarlo al consultarlo), revocar un dispositivo, historial.
  C) El registro sale en el archivo de log del servidor.
  D) control.py arranca el servidor sin ventana y lo para por la API.
  E) El registro se lee bien (trazas incluidas) y los ajustes se validan.

Todo usa archivos temporales: nunca toca accesos, ajustes ni registros reales.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "server"
ESCRITORIO = RAIZ / "escritorio"
PUERTO = 8797
PUERTO_ARRANQUE = 8798

failures = 0
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


# ----------------------------------------------- entorno aislado (antes de importar)
CARPETA = Path(tempfile.mkdtemp(prefix="remotepad_admin_"))
ARCHIVO_LOG = CARPETA / "servidor.log"
os.environ.update({
    "REMOTEPAD_TOKENS": str(CARPETA / "tokens.json"),
    "REMOTEPAD_PROFILES": str(CARPETA / "profiles.json"),
    "REMOTEPAD_LEARNING": str(CARPETA / "learning.json"),
    "REMOTEPAD_HISTORY": str(CARPETA / "history.json"),
    "REMOTEPAD_CONFIG": str(CARPETA / "config.json"),
    "REMOTEPAD_HTTPS_DIR": str(CARPETA / "https"),
    "REMOTEPAD_LOG": str(ARCHIVO_LOG),
    "REMOTEPAD_CONSOLA": str(CARPETA / "consola.log"),
    "REMOTEPAD_ESCRITORIO": str(CARPETA / "escritorio.json"),
    "REMOTEPAD_SIN_VENTANAS": "1",
    "PYTHONUTF8": "1",
})
sys.path.insert(0, str(SERVIDOR))
sys.path.insert(0, str(ESCRITORIO))

import auth  # noqa: E402
import control  # noqa: E402


def llamar(metodo: str, ruta: str, datos=None, cabeceras=None, puerto: int = PUERTO):
    """Devuelve (codigo, cuerpo_json_o_None)."""
    cuerpo = None
    cab = dict(cabeceras or {})
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        cab.setdefault("Content-Type", "application/json")
    peticion = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=cuerpo,
                                      method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(peticion, timeout=5) as respuesta:
            return respuesta.status, json.loads(respuesta.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def esperar_servidor(puerto: int, segundos: float = 25.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if control.servidor_en_marcha(puerto):
            return True
        time.sleep(0.2)
    return False


def pruebas_api(proceso: subprocess.Popen) -> None:
    print("\n[A] API de administracion: quien puede llamarla")
    codigo, datos = llamar("GET", "/api/admin/estado")
    check("GET /api/admin/estado desde la PC responde 200", codigo == 200, f"codigo={codigo}")
    check("el estado trae PIN, acceso y dispositivos",
          bool(datos) and "pin" in datos and "auth_required" in datos and "dispositivos" in datos)
    check("el estado trae el aviso de ventana con permisos de administrador",
          bool(datos) and datos.get("aviso_elevado") is False)

    codigo, _ = llamar("GET", "/api/admin/estado", cabeceras={"Origin": "http://evil.example"})
    check("una web (cabecera Origin) no puede leer el estado", codigo == 403, f"codigo={codigo}")

    codigo, _ = llamar("POST", "/api/admin/pin", datos={}, cabeceras={"Content-Type": "text/plain"})
    check("un POST que no es JSON se rechaza", codigo == 415, f"codigo={codigo}")

    codigo, _ = llamar("POST", "/api/admin/parar", datos={},
                       cabeceras={"Origin": "http://evil.example"})
    check("un POST con Origin no puede parar el servidor", codigo == 403, f"codigo={codigo}")
    check("el servidor sigue en marcha tras los rechazos", control.servidor_en_marcha(PUERTO))

    print("\n[B] Cambios desde la app")
    _, antes = llamar("GET", "/api/admin/estado")
    codigo, nuevo = llamar("POST", "/api/admin/pin", datos={})
    check("pedir PIN nuevo responde ok", codigo == 200 and bool(nuevo and nuevo.get("ok")))
    check("el PIN nuevo tiene 6 digitos y es distinto",
          bool(nuevo) and len(nuevo["pin"]) == 6 and nuevo["pin"].isdigit()
          and nuevo["pin"] != antes["pin"])

    codigo, consulta = llamar("GET", "/api/admin/qr")
    _, consulta2 = llamar("GET", "/api/admin/qr")
    check("consultar el QR devuelve la matriz", bool(consulta) and len(consulta["matrix"]) > 20)
    check("consultar el QR no lo cambia", bool(consulta) and consulta["url"] == consulta2["url"])
    codigo, renovado = llamar("POST", "/api/admin/qr", datos={})
    check("pedir QR nuevo cambia la direccion", bool(renovado) and renovado["url"] != consulta["url"])

    codigo, _ = llamar("POST", "/api/admin/ajustes", datos={"auth_required": False})
    _, despues = llamar("GET", "/api/admin/estado")
    check("desactivar el codigo de acceso se aplica", despues and despues["auth_required"] is False)
    llamar("POST", "/api/admin/ajustes", datos={"auth_required": True})
    _, despues = llamar("GET", "/api/admin/estado")
    check("volver a activarlo se aplica", despues and despues["auth_required"] is True)

    _, historial = llamar("GET", "/api/admin/historial")
    check("el historial responde con su lista", historial is not None and "programas" in historial)

    print("\n[C] Registro")
    check("el cambio de PIN queda en el archivo de registro",
          ARCHIVO_LOG.exists() and "Nuevo PIN de seguridad" in ARCHIVO_LOG.read_text(encoding="utf-8"))


def pruebas_dispositivos() -> None:
    print("\n[B2] Revocar un dispositivo desde la app")
    # El dispositivo se crea antes de que arranque el servidor, para que lo cargue.
    auth.Dispositivos().emitir("Movil de prueba", "192.168.1.50")
    identificador = auth.Dispositivos().listar()[0]["id"]
    proceso = arrancar_servidor_con_dispositivo()
    try:
        _, estado = llamar("GET", "/api/admin/estado", puerto=PUERTO_DISPOSITIVO)
        check("el dispositivo aparece en el estado",
              bool(estado) and any(d["id"] == identificador for d in estado["dispositivos"]))
        codigo, respuesta = llamar("POST", "/api/admin/revocar", datos={"id": identificador},
                                   puerto=PUERTO_DISPOSITIVO)
        check("revocarlo responde ok", bool(respuesta) and respuesta["ok"] is True,
              f"codigo={codigo}")
        _, estado = llamar("GET", "/api/admin/estado", puerto=PUERTO_DISPOSITIVO)
        check("ya no aparece con acceso",
              bool(estado) and not any(d["id"] == identificador for d in estado["dispositivos"]))
    finally:
        llamar("POST", "/api/admin/parar", datos={}, puerto=PUERTO_DISPOSITIVO)
        proceso.wait(timeout=20)


PUERTO_DISPOSITIVO = 8799


def arrancar_servidor_con_dispositivo() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-u", "app.py", "--port", str(PUERTO_DISPOSITIVO), "--no-browser"],
        cwd=str(SERVIDOR), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT, env=os.environ.copy(),
    )


def pruebas_arranque() -> None:
    print("\n[D] Arranque y parada desde la app (sin ventana)")
    ajustes = {"puerto": PUERTO_ARRANQUE, "red": "127.0.0.1", "https": False}
    proceso = control.arrancar(ajustes)
    try:
        check("arrancado en segundo plano responde", esperar_servidor(PUERTO_ARRANQUE))
        check("la API de administracion responde al arrancar",
              control.estado_servidor(PUERTO_ARRANQUE) is not None)
    finally:
        respuesta = control.accion_servidor(PUERTO_ARRANQUE, False, "/api/admin/parar")
        check("parar por la API responde ok", respuesta is not None and respuesta.get("ok"))
        check("el servidor se apaga", control.esperar_apagado(PUERTO_ARRANQUE, segundos=15))
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()
    check("el proceso ha terminado", proceso.poll() is not None)


def pruebas_registro_y_ajustes() -> None:
    print("\n[E] Registro y ajustes")
    ARCHIVO_LOG.write_text(
        "15:00:01  INFO    Primera linea\n"
        "15:00:02  WARNING Aviso\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1\n"
        "15:00:03  ERROR   Algo falla\n",
        encoding="utf-8")
    entradas = control.leer_registro()
    check("el registro separa las entradas por nivel",
          [e["nivel"] for e in entradas] == ["INFO", "WARNING", "ERROR"], str(entradas))
    check("la traza se pega a la entrada anterior",
          "Traceback" in entradas[1]["texto"] and "File" in entradas[1]["texto"])

    check("sin archivo de ajustes, sale el puerto 8765",
          control.ajustes_lanzamiento()["puerto"] == 8765)
    control.guardar_ajustes_lanzamiento({"puerto": 99999, "red": "otra", "https": "si"})
    limpios = control.ajustes_lanzamiento()
    check("un puerto fuera de rango vuelve al valor por defecto", limpios["puerto"] == 8765)
    check("una red no valida vuelve a 0.0.0.0", limpios["red"] == "0.0.0.0")
    check("un valor que no es booleano vuelve al valor por defecto", limpios["https"] is False)
    control.guardar_ajustes_lanzamiento({"puerto": 9100, "red": "127.0.0.1"})
    check("un ajuste valido se guarda", control.ajustes_lanzamiento()["puerto"] == 9100)


def main() -> int:
    print("Pruebas de la app de escritorio y de la API de administracion")
    proceso = subprocess.Popen(
        [sys.executable, "-u", "app.py", "--port", str(PUERTO), "--no-browser"],
        cwd=str(SERVIDOR), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT, env=os.environ.copy(),
    )
    try:
        if not esperar_servidor(PUERTO):
            print("  [FALLO] el servidor de pruebas no ha arrancado")
            return 1
        pruebas_api(proceso)
    finally:
        llamar("POST", "/api/admin/parar", datos={})
        try:
            proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proceso.kill()

    pruebas_dispositivos()
    pruebas_arranque()
    pruebas_registro_y_ajustes()

    print(f"\n{checks - failures} de {checks} comprobaciones correctas.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
