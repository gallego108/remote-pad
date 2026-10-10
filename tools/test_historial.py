"""
Pruebas de server/historial.py (programas usados, para abrirlos desde el
celular). No abre ningun programa: solo prueba la lista y el archivo.

  - Anota programas, los ordena del mas reciente al mas antiguo y los sube
    al principio al volver a usarlos.
  - Ignora Python, la consola y los anfitriones de ventanas.
  - Como mucho MAX_PROGRAMAS: se olvidan los mas antiguos.
  - Lo que ve el celular no lleva rutas; quitar funciona por id.
  - Se guarda y se vuelve a cargar igual; un AUMID o icono raro del
    archivo se descarta.
  - Nombre para mostrar: descripcion, si no titulo corto, si no el archivo.

Uso:
    python tools/test_historial.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="remotepad_historial_"))
os.environ["REMOTEPAD_HISTORY"] = str(_TMP / "history.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import historial  # noqa: E402

failures = 0
checks = 0
PNG = "data:image/png;base64,iVBORw0KGgo="
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CODE = r"C:\Users\x\AppData\Local\Programs\Microsoft VS Code\Code.exe"
WHATSAPP = r"C:\Program Files\WindowsApps\5319275A.WhatsAppDesktop_2.1\WhatsApp.Root.exe"


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures, checks
    checks += 1
    print(f"  [{'OK   ' if condition else 'FALLO'}] {name}"
          + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures += 1


def main() -> int:
    archivo = _TMP / "history.json"
    print("\n== Anotar y ordenar ==")
    h = historial.Historial(archivo)
    check("Empieza vacio", h.lista() == {"programs": [], "icons": {}})
    id_chrome = h.anotar(CHROME, "", "Google Chrome", PNG, ahora=100)
    id_code = h.anotar(CODE, "", "Visual Studio Code", ahora=200)
    id_wa = h.anotar(WHATSAPP, "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "WhatsApp", ahora=300)
    nombres = [p["name"] for p in h.lista()["programs"]]
    check("Del mas reciente al mas antiguo",
          nombres == ["WhatsApp", "Visual Studio Code", "Google Chrome"], str(nombres))
    h.anotar(CHROME, "", "Google Chrome", ahora=400)
    check("Volver a usarlo lo sube al principio", h.lista()["programs"][0]["id"] == id_chrome)
    check("Mantiene el icono que ya tenia", h.lista()["icons"].get(id_chrome) == PNG)
    check("El id es estable", id_chrome == historial.id_de(CHROME))
    check("Las apps de la Store se identifican por su AUMID",
          id_wa == historial.id_de(WHATSAPP, "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"))

    print("\n== Lo que no se apunta ==")
    for ruta in (r"C:\Python312\python.exe", r"C:\Windows\System32\conhost.exe",
                 r"C:\Windows\System32\ApplicationFrameHost.exe", ""):
        check(f"Ignora {Path(ruta).name or '(sin ruta)'}", h.anotar(ruta) is None)
    raro = h.anotar(r"C:\x\app.exe", "esto no es un aumid", ahora=1)
    check("Un AUMID raro se descarta", h.buscar(raro)["aumid"] == "")

    print("\n== Lo que ve el celular ==")
    texto = json.dumps(h.lista())
    check("No lleva rutas", "Program Files" not in texto and "path" not in texto)
    check("Cada programa trae id, nombre, app y fecha",
          all({"id", "name", "app", "last"} <= set(p) for p in h.lista()["programs"]))
    check("buscar devuelve la ruta (solo para el servidor)", h.buscar(id_code)["path"] == CODE)
    check("buscar un id desconocido da None", h.buscar("noexiste") is None)

    print("\n== Quitar y limite ==")
    check("Quitar por id", h.quitar(id_code) and h.buscar(id_code) is None)
    check("Quitar dos veces no falla", h.quitar(id_code) is False)
    for i in range(historial.MAX_PROGRAMAS + 5):
        h.anotar(rf"C:\apps\programa{i}.exe", ahora=1000 + i)
    ids = [p["id"] for p in h.lista()["programs"]]
    check(f"Como mucho {historial.MAX_PROGRAMAS}", len(ids) == historial.MAX_PROGRAMAS, str(len(ids)))
    check("Se olvidan los mas antiguos", id_chrome not in ids)

    print("\n== Disco ==")
    h.guardar()
    otro = historial.Historial(archivo)
    check("Se vuelve a cargar igual", otro.lista() == h.lista())
    datos = {"programas": [
        {"path": CHROME, "aumid": "x; calc.exe", "name": "Chrome", "last": 5, "icon": "javascript:alert(1)"},
        {"name": "sin ruta"}, "basura",
    ]}
    archivo.write_text(json.dumps(datos), encoding="utf-8")
    cargado = historial.Historial(archivo)
    entrada = cargado.buscar(historial.id_de(CHROME))
    check("Del archivo se descartan AUMID e icono raros",
          entrada and entrada["aumid"] == "" and entrada["icon"] == "", str(entrada))
    check("Y las entradas sin ruta", len(cargado.lista()["programs"]) == 1)
    archivo.write_text("{roto", encoding="utf-8")
    check("Un archivo roto no impide arrancar", historial.Historial(archivo).lista()["programs"] == [])

    print("\n== Nombre para mostrar ==")
    check("La descripcion del ejecutable",
          historial.nombre_de(CODE, "Visual Studio Code", "main.py - x") == "Visual Studio Code")
    check("Si la descripcion es el archivo, el titulo corto",
          historial.nombre_de(WHATSAPP, "WhatsApp.Root", "WhatsApp") == "WhatsApp")
    check("Si el titulo es largo, el archivo",
          historial.nombre_de(r"C:\a\Herramienta.exe", "", "x" * 60) == "Herramienta")

    print(f"\n{checks - failures}/{checks} comprobaciones correctas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
