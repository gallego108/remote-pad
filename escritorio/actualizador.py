"""
Actualizacion de RemotePad desde las releases de GitHub.

Solo se confia en el repositorio oficial: la version se lee de la ultima
release, el instalador se descarga de esa misma release (y solo desde ese
prefijo de URL) y su huella SHA-256 tiene que coincidir con la publicada en
SHA256SUMS.txt antes de ejecutarlo.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

REPO = "gallego108/remote-pad"
API_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"
PREFIJO_DESCARGA = f"https://github.com/{REPO}/releases/download/"
NOMBRE_INSTALADOR = "RemotePad-Instalador-{version}.exe"
NOMBRE_SUMAS = "SHA256SUMS.txt"
CABECERAS = {"Accept": "application/vnd.github+json", "User-Agent": "RemotePad"}


def a_tupla(version: str) -> tuple[int, ...]:
    """'1.16.0' o 'v1.16.0' -> (1, 16, 0). Lo que no sea numeros se ignora."""
    partes = re.findall(r"\d+", str(version))
    return tuple(int(p) for p in partes[:3]) or (0,)


def hay_version_nueva(instalada: str, publicada: str) -> bool:
    return a_tupla(publicada) > a_tupla(instalada)


def leer_sumas(texto: str) -> dict[str, str]:
    """Lee un SHA256SUMS.txt ('<hash>  <nombre>' por linea) -> {nombre: hash}."""
    sumas: dict[str, str] = {}
    for linea in texto.splitlines():
        partes = linea.strip().split(maxsplit=1)
        if len(partes) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", partes[0]):
            sumas[partes[1].strip().lstrip("*")] = partes[0].lower()
    return sumas


def url_permitida(url: str) -> bool:
    return url.startswith(PREFIJO_DESCARGA) and "/../" not in url


def _leer_json(url: str, timeout: float = 10.0) -> Any:
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _leer_texto(url: str, timeout: float = 10.0) -> str:
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def buscar(instalada: str) -> dict[str, Any]:
    """
    Mira la ultima release. Devuelve {disponible, version, url, sha256, notas}
    o {disponible: False, error: '...'} si no se puede comprobar.
    """
    try:
        release = _leer_json(API_ULTIMA)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"disponible": False, "error": "Aún no hay versiones publicadas en GitHub"}
        return {"disponible": False, "error": f"GitHub respondió con error ({error.code})"}
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"disponible": False, "error": f"No se pudo consultar GitHub ({error})"}

    version = str(release.get("tag_name", "")).lstrip("v")
    if not version:
        return {"disponible": False, "error": "Aún no hay versiones publicadas en GitHub"}
    if not hay_version_nueva(instalada, version):
        return {"disponible": False, "version": version}

    nombre = NOMBRE_INSTALADOR.format(version=version)
    activos = {a.get("name"): a for a in release.get("assets", [])}
    if nombre not in activos or NOMBRE_SUMAS not in activos:
        return {"disponible": False, "version": version,
                "error": "La release no trae el instalador o su huella"}
    url = activos[nombre].get("browser_download_url", "")
    if not url_permitida(url):
        return {"disponible": False, "version": version, "error": "Descarga no oficial"}
    try:
        sumas = leer_sumas(_leer_texto(activos[NOMBRE_SUMAS]["browser_download_url"]))
    except (urllib.error.URLError, OSError) as error:
        return {"disponible": False, "version": version,
                "error": f"No se pudo leer la huella ({error})"}
    if nombre not in sumas:
        return {"disponible": False, "version": version, "error": "Falta la huella del instalador"}
    return {
        "disponible": True,
        "version": version,
        "url": url,
        "sha256": sumas[nombre],
        "notas": str(release.get("body") or "")[:1500],
    }


def verificar(archivo: Path, sha256_esperado: str) -> bool:
    digest = hashlib.sha256()
    with open(archivo, "rb") as fichero:
        for bloque in iter(lambda: fichero.read(1 << 20), b""):
            digest.update(bloque)
    return digest.hexdigest() == sha256_esperado.lower()


def descargar(url: str, sha256: str, carpeta: Optional[Path] = None) -> Path:
    """Descarga el instalador y comprueba su huella. Lanza ValueError si no coincide."""
    if not url_permitida(url):
        raise ValueError("Descarga no oficial")
    carpeta = carpeta or Path(tempfile.gettempdir()) / "RemotePad-actualizacion"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / Path(url).name
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=60) as respuesta, open(destino, "wb") as fichero:
        for bloque in iter(lambda: respuesta.read(1 << 20), b""):
            fichero.write(bloque)
    if not verificar(destino, sha256):
        destino.unlink(missing_ok=True)
        raise ValueError("La huella del instalador no coincide: no se ejecuta")
    return destino
