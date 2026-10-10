"""
Historial de programas usados en la PC, para volver a abrirlos desde el
celular (panel "Programas" -> "Abrir programa").

El servidor anota el programa que tienes delante cada vez que cambias de
ventana: su ejecutable, su nombre ("Visual Studio Code"), su icono y, si es una
app de la Microsoft Store, su AUMID (con el que se abre). El celular solo ve
un identificador corto de cada programa: para abrir uno manda ese id y el
servidor busca la ruta en SU historial, asi que desde el celular no se puede
ejecutar nada que no estuviera ya en la PC.

Sin Win32: los datos llegan ya leidos desde app.py, asi que se prueba solo.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from auth import read_json, write_json_atomic

log = logging.getLogger("remotepad")

HISTORY_FILE = Path(
    os.environ.get("REMOTEPAD_HISTORY")
    or (Path(__file__).resolve().parent / "history.json")
)
MAX_PROGRAMAS = 30
# Ejecutables que no son "programas" para el usuario: anfitriones de otras
# ventanas y el propio Python (la consola o el laser de RemotePad).
EXCLUIDOS = {"applicationframehost", "python", "pythonw", "py", "conhost", "openconsole"}
# Un AUMID valido: letras, numeros y . _ - ! (p. ej. "Claude_pzs8sxrjxfjjc!Claude").
_AUMID = re.compile(r"^[A-Za-z0-9._\-]+![A-Za-z0-9._\-]+$")


def id_de(ruta: str, aumid: str = "") -> str:
    """Identificador corto y estable de un programa."""
    clave = (aumid or ruta).lower()
    return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:12]


def nombre_de(ruta: str, descripcion: str, titulo: str) -> str:
    """
    Nombre para mostrar: la descripcion del ejecutable ("Google Chrome"). Si no
    hay, o es igual al nombre del archivo ("WhatsApp.Root"), el titulo de la
    ventana cuando es corto ("WhatsApp"); y si no, el nombre del archivo.
    """
    exe = Path(ruta).stem
    descripcion = (descripcion or "").strip()
    if descripcion and descripcion.lower() != exe.lower():
        return descripcion
    titulo = (titulo or "").strip()
    if titulo and len(titulo) <= 40:
        return titulo
    return descripcion or exe


class Historial:
    def __init__(self, archivo: Path = HISTORY_FILE) -> None:
        self.archivo = Path(archivo)
        self._programas: dict[str, dict] = {}
        self._cambios = False
        self.cargar()

    # ------------------------------------------------------------ disco
    def cargar(self) -> None:
        datos = read_json(self.archivo, "historial de programas")
        programas = datos.get("programas") if isinstance(datos, dict) else None
        self._programas = {}
        for entrada in programas or []:
            if not isinstance(entrada, dict) or not entrada.get("path"):
                continue
            aumid = str(entrada.get("aumid") or "")
            if aumid and not _AUMID.match(aumid):
                aumid = ""
            limpio = {
                "path": str(entrada["path"]),
                "aumid": aumid,
                "name": str(entrada.get("name") or Path(str(entrada["path"])).stem)[:80],
                "last": float(entrada.get("last") or 0),
                "count": int(entrada.get("count") or 1),
                "icon": str(entrada.get("icon") or ""),
            }
            if limpio["icon"] and not limpio["icon"].startswith("data:image/png;base64,"):
                limpio["icon"] = ""
            self._programas[id_de(limpio["path"], aumid)] = limpio

    def guardar(self) -> None:
        """Escribe en disco solo si algo cambio."""
        if not self._cambios:
            return
        if write_json_atomic(self.archivo, {"programas": list(self._programas.values())}):
            self._cambios = False

    # ----------------------------------------------------------- cambios
    def anotar(self, ruta: str, aumid: str = "", nombre: str = "",
               icono: Optional[str] = None, ahora: Optional[float] = None) -> Optional[str]:
        """
        Apunta que se ha usado un programa (o lo sube al principio si ya
        estaba). Devuelve su id, o None si no se guarda (excluido o sin ruta).
        """
        if not ruta or Path(ruta).stem.lower() in EXCLUIDOS:
            return None
        if aumid and not _AUMID.match(aumid):
            aumid = ""
        clave = id_de(ruta, aumid)
        ahora = time.time() if ahora is None else ahora
        entrada = self._programas.get(clave)
        if entrada is None:
            entrada = {"path": ruta, "aumid": aumid, "name": nombre or Path(ruta).stem,
                       "last": ahora, "count": 0, "icon": ""}
            self._programas[clave] = entrada
        entrada["path"] = ruta              # una actualizacion cambia la carpeta
        entrada["last"] = ahora
        entrada["count"] += 1
        if nombre:
            entrada["name"] = nombre[:80]
        if icono and icono.startswith("data:image/png;base64,"):
            entrada["icon"] = icono
        self._recortar()
        self._cambios = True
        return clave

    def quitar(self, clave: str) -> bool:
        if self._programas.pop(str(clave), None) is None:
            return False
        self._cambios = True
        return True

    def _recortar(self) -> None:
        if len(self._programas) <= MAX_PROGRAMAS:
            return
        sobran = sorted(self._programas.items(), key=lambda par: par[1]["last"])
        for clave, _ in sobran[: len(self._programas) - MAX_PROGRAMAS]:
            del self._programas[clave]

    # ----------------------------------------------------------- consultas
    def necesita_icono(self, clave: str) -> bool:
        entrada = self._programas.get(clave)
        return bool(entrada) and not entrada["icon"]

    def buscar(self, clave: str) -> Optional[dict]:
        entrada = self._programas.get(str(clave))
        return dict(entrada) if entrada else None

    def lista(self) -> dict:
        """
        Lo que ve el celular: sin rutas. {"programs": [{id, name, app, last,
        icon?}], "icons": {id: data_url}}, del usado mas recientemente al mas
        antiguo.
        """
        ordenados = sorted(self._programas.items(), key=lambda par: -par[1]["last"])
        programas, iconos = [], {}
        for clave, entrada in ordenados:
            fila = {"id": clave, "name": entrada["name"], "app": Path(entrada["path"]).stem,
                    "last": int(entrada["last"])}
            if entrada["icon"]:
                iconos[clave] = entrada["icon"]
                fila["icon"] = clave
            programas.append(fila)
        return {"programs": programas, "icons": iconos}
