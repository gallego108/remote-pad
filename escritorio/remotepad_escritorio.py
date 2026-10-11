"""
RemotePad - panel de escritorio.

Ventana con la configuracion de RemotePad, el registro en vivo y los
dispositivos, y un icono junto al reloj para abrirla o encender/parar el
servidor sin tener la ventana abierta.

    python escritorio/remotepad_escritorio.py                 # abre la ventana
    pythonw escritorio/remotepad_escritorio.py --en-segundo-plano
                                                              # solo bandeja

Requiere: pip install -r escritorio/requirements.txt
"""

from __future__ import annotations

import argparse
import ctypes
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import webview

import control
import auth
import actualizador

UI = control.RECURSOS / "escritorio" / "ui" / "index.html"
ICONO = control.RECURSOS / "remotepad.ico"
NOMBRE_MUTEX = "RemotePadPanelEscritorio"


def version_instalada() -> str:
    """Version del servidor, leida del codigo (sin importar el servidor entero)."""
    try:
        texto = (control.SERVIDOR / "app.py").read_text(encoding="utf-8")
    except OSError:
        return "?"
    encontrado = re.search(r'^APP_VERSION = "([^"]+)"', texto, re.MULTILINE)
    return encontrado.group(1) if encontrado else "?"


def ya_hay_una_abierta() -> bool:
    """Un solo panel por usuario: el mutex con nombre lo garantiza mientras la app viva."""
    ctypes.windll.kernel32.CreateMutexW(None, False, NOMBRE_MUTEX)
    return ctypes.windll.kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS


class Api:
    """Lo que la interfaz llama (window.pywebview.api.*). Devuelve siempre dicts."""

    def __init__(self) -> None:
        self._ventana: Optional[webview.Window] = None
        self._bandeja: Optional["Bandeja"] = None
        self._proceso = None            # el servidor que esta app ha arrancado, si lo ha hecho ella

    # ------------------------------------------------------------- estado
    def _ajustes(self) -> dict[str, Any]:
        return control.ajustes_lanzamiento()

    def _en_marcha(self) -> bool:
        ajustes = self._ajustes()
        return control.servidor_en_marcha(ajustes["puerto"], ajustes["https"])

    def estado(self) -> dict[str, Any]:
        ajustes = self._ajustes()
        datos = control.estado_servidor(ajustes["puerto"], ajustes["https"])
        activo = datos is not None
        if activo:
            servidor = datos
        else:
            # Apagado: se muestra lo que queda guardado en disco.
            guardado = auth.load_config()
            servidor = {
                "auth_required": guardado.get("auth_required") is not False,
                "confirmar_nuevos": bool(guardado.get("confirm_new_devices", False)),
                "dispositivos": control.dispositivos_en_disco(),
                "pendiente": None,
                "clientes": 0,
                "version": version_instalada(),
            }
        return {"activo": activo, "ajustes": ajustes, "servidor": servidor,
                "version": servidor.get("version", version_instalada())}

    # ---------------------------------------------------- encender y parar
    def arrancar(self) -> dict[str, Any]:
        if self._en_marcha():
            return {"ok": True, "motivo": "Ya estaba encendido"}
        self._proceso = control.arrancar(self._ajustes())
        return {"ok": True}

    def parar(self) -> dict[str, Any]:
        ajustes = self._ajustes()
        respuesta = control.accion_servidor(ajustes["puerto"], ajustes["https"],
                                            "/api/admin/parar")
        if respuesta is None:
            return {"ok": False, "motivo": "El servidor ya estaba apagado"}
        control.esperar_apagado(ajustes["puerto"], ajustes["https"])
        self._cerrar_proceso_propio()
        return {"ok": True}

    def _cerrar_proceso_propio(self) -> None:
        if self._proceso is not None and self._proceso.poll() is None:
            self._proceso.terminate()
        self._proceso = None

    # ------------------------------------------------------------ seguridad
    def ajustes_seguridad(self, cambios: dict[str, Any]) -> dict[str, Any]:
        """Codigo de acceso y confirmacion de dispositivos nuevos. Funciona con el servidor apagado."""
        cambios = {k: bool(v) for k, v in cambios.items()
                   if k in ("auth_required", "confirmar_nuevos")}
        ajustes = self._ajustes()
        if control.servidor_en_marcha(ajustes["puerto"], ajustes["https"]):
            respuesta = control.accion_servidor(ajustes["puerto"], ajustes["https"],
                                                "/api/admin/ajustes", cambios)
            return {"ok": respuesta is not None}
        cambios_disco = {}
        if "auth_required" in cambios:
            cambios_disco["auth_required"] = cambios["auth_required"]
        if "confirmar_nuevos" in cambios:
            cambios_disco["confirm_new_devices"] = cambios["confirmar_nuevos"]
        auth.save_config(cambios_disco)
        return {"ok": True}

    def _accion_con_servidor(self, ruta: str, datos: Optional[dict] = None) -> dict[str, Any]:
        ajustes = self._ajustes()
        respuesta = control.accion_servidor(ajustes["puerto"], ajustes["https"], ruta, datos)
        if respuesta is None:
            return {"ok": False, "motivo": "Enciende el servidor para hacer esto"}
        return respuesta

    def pin_nuevo(self) -> dict[str, Any]:
        return self._accion_con_servidor("/api/admin/pin")

    def qr_nuevo(self) -> dict[str, Any]:
        return self._accion_con_servidor("/api/admin/qr")

    def qr_actual(self) -> dict[str, Any]:
        """El QR vigente, sin cambiarlo (lo que el movil ya puede tener escaneado)."""
        ajustes = self._ajustes()
        datos = control.consultar_servidor(ajustes["puerto"], ajustes["https"], "/api/admin/qr")
        return datos if datos is not None else {"matrix": None}

    def responder_confirmacion(self, permitir: bool) -> dict[str, Any]:
        return self._accion_con_servidor("/api/admin/confirmar", {"permitir": bool(permitir)})

    def revocar(self, identificador: str) -> dict[str, Any]:
        ajustes = self._ajustes()
        if control.servidor_en_marcha(ajustes["puerto"], ajustes["https"]):
            return self._accion_con_servidor("/api/admin/revocar", {"id": identificador})
        nombre = control.revocar_en_disco(identificador)
        return {"ok": nombre is not None, "nombre": nombre}

    # ------------------------------------------------------------- registro
    # ----------------------------------------------------------- actualizar
    def buscar_actualizacion(self) -> dict[str, Any]:
        return actualizador.buscar(version_instalada())

    def instalar_actualizacion(self, url: str, sha256: str) -> dict[str, Any]:
        """
        Descarga la version nueva, comprueba su huella y abre el instalador.
        El instalador reemplaza los archivos del programa, asi que antes se para
        el servidor y el panel se cierra.
        """
        try:
            instalador = actualizador.descargar(url, sha256)
        except (ValueError, OSError) as error:
            return {"ok": False, "motivo": str(error)}
        if self._en_marcha():
            self.parar()
        import os
        os.startfile(str(instalador))
        # Un instante para que la interfaz reciba la respuesta antes de cerrarse.
        threading.Timer(1.5, self.salir, args=(False,)).start()
        return {"ok": True}

    def registro(self) -> list[dict[str, Any]]:
        return control.leer_registro()

    def abrir_carpeta_registro(self) -> None:
        import os
        os.startfile(str(control.LOG_FILE.parent))

    # ------------------------------------------------------------ programas
    def programas(self) -> list[dict[str, Any]]:
        ajustes = self._ajustes()
        datos = control.consultar_servidor(ajustes["puerto"], ajustes["https"],
                                           "/api/admin/historial")
        if datos is not None:
            return datos.get("programas", [])
        return control.programas_en_disco()

    def programa_quitar(self, clave: str) -> dict[str, Any]:
        ajustes = self._ajustes()
        if control.servidor_en_marcha(ajustes["puerto"], ajustes["https"]):
            return self._accion_con_servidor("/api/admin/historial/quitar", {"id": clave})
        return {"ok": control.quitar_programa_en_disco(clave)}

    # ------------------------------------------------------------ lanzamiento
    def lanzamiento_leer(self) -> dict[str, Any]:
        return self._ajustes()

    def lanzamiento_guardar(self, cambios: dict[str, Any]) -> dict[str, Any]:
        guardados = control.guardar_ajustes_lanzamiento(cambios)
        if "inicio_windows" in cambios:
            control.sincronizar_inicio(guardados["inicio_windows"])
        return {"ok": True, "ajustes": guardados}

    # ------------------------------------------------------------- ventana
    def ocultar(self) -> None:
        if self._ventana is not None:
            self._ventana.hide()

    def mostrar(self) -> None:
        if self._ventana is not None:
            self._ventana.show()

    def salir(self, parar_servidor: bool) -> None:
        """Cierra la app. Con parar_servidor, tambien apaga RemotePad."""
        if parar_servidor and self._en_marcha():
            self.parar()
        self._cerrar_proceso_propio()
        if self._bandeja is not None:
            self._bandeja.detener()
        if self._ventana is not None:
            self._ventana.destroy()


class Bandeja:
    """Icono junto al reloj. Va en su propio hilo; pystray no comparte bucle con la ventana."""

    def __init__(self, api: Api) -> None:
        import pystray
        from PIL import Image

        self.api = api
        self.activo = False
        self.icono = pystray.Icon(
            "RemotePad", Image.open(ICONO), "RemotePad",
            menu=pystray.Menu(
                pystray.MenuItem("Abrir RemotePad", self._abrir, default=True),
                pystray.MenuItem(lambda _: "Parar servidor" if self.activo else "Encender servidor",
                                 self._alternar),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", self._salir),
            ),
        )
        self._parar = threading.Event()

    def iniciar(self) -> None:
        threading.Thread(target=self.icono.run, daemon=True, name="bandeja").start()
        threading.Thread(target=self._vigilar, daemon=True, name="bandeja-estado").start()

    def _vigilar(self) -> None:
        """Mantiene el texto del menu al dia y avisa si una ventana elevada bloquea el control."""
        elevado = False
        while not self._parar.is_set():
            ajustes = self.api._ajustes()
            nuevo = control.servidor_en_marcha(ajustes["puerto"], ajustes["https"])
            if nuevo != self.activo:
                self.activo = nuevo
                try:
                    self.icono.update_menu()
                except Exception:
                    pass
            if nuevo:
                datos = control.estado_servidor(ajustes["puerto"], ajustes["https"]) or {}
                ahora = bool(datos.get("aviso_elevado"))
                if ahora and not elevado:
                    try:
                        self.icono.notify(
                            "Hay una ventana con permisos de administrador delante. "
                            "Windows no deja que el móvil la mueva: haz clic en otra ventana.",
                            "RemotePad")
                    except Exception:
                        pass
                elevado = ahora
            self._parar.wait(2.0)

    def _abrir(self, icono, item) -> None:
        self.api.mostrar()

    def _alternar(self, icono, item) -> None:
        if self.activo:
            threading.Thread(target=self.api.parar, daemon=True).start()
        else:
            self.api.arrancar()

    def _salir(self, icono, item) -> None:
        respuesta = control.preguntar_parar_servidor()
        if respuesta is None:
            return
        self.api.salir(parar_servidor=respuesta)

    def detener(self) -> None:
        self._parar.set()
        try:
            self.icono.stop()
        except Exception:
            pass


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Panel de escritorio de RemotePad.")
    parser.add_argument("--en-segundo-plano", action="store_true",
                        help="arranca solo en la bandeja (lo usa el inicio de Windows)")
    args = parser.parse_args(argv)

    if ya_hay_una_abierta():
        ctypes.windll.user32.MessageBoxW(
            None, "RemotePad ya está abierto. Búscalo en la bandeja del reloj.",
            "RemotePad", 0x40)
        return 0

    api = Api()
    ajustes = control.ajustes_lanzamiento()

    ventana = webview.create_window(
        "RemotePad", url=str(UI), js_api=api,
        width=1080, height=700, min_size=(860, 560),
        background_color="#0e1116", hidden=args.en_segundo_plano,
    )
    api._ventana = ventana

    try:
        api._bandeja = Bandeja(api)
        api._bandeja.iniciar()
        con_bandeja = True
    except Exception as exc:
        # Sin bandeja, cerrar la ventana tiene que cerrar la app (si no, no habria forma de salir).
        print(f"[AVISO] Sin icono en la bandeja: {exc}")
        con_bandeja = False

    def al_cerrar() -> bool:
        if con_bandeja:
            ventana.hide()
            return False       # la app sigue en la bandeja, con el servidor como estaba
        return True

    ventana.events.closing += al_cerrar

    def al_arrancar() -> None:
        # Al abrir la app, enciende RemotePad si asi se eligio (en segundo plano tambien).
        if ajustes["arrancar_servidor"]:
            api.arrancar()

    control.sincronizar_inicio(ajustes["inicio_windows"])
    webview.start(al_arrancar, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
