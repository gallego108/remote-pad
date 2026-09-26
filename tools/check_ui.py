"""
Coherencia entre la interfaz (HTML/CSS) y su logica (JS).

Recorre los elementos que el JS busca por id y los atributos data-* que
dispara, y avisa si alguno no existe en el HTML (un fallo tipico que en el
celular se manifestaria como "el boton no hace nada").
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

html = (WEB / "index.html").read_text(encoding="utf-8")
js = (WEB / "app.js").read_text(encoding="utf-8")
css = (WEB / "styles.css").read_text(encoding="utf-8")

failures: list[str] = []

# ---------------------------------------------------------- ids del HTML
html_ids = set(re.findall(r'id="([^"]+)"', html))
css_classes = set(re.findall(r'class="([^"]+)"', html))

print(f"Elementos con id en el HTML: {len(html_ids)}")

# ------------------------------------------- ids que el JS pide con $('...')
js_ids = set(re.findall(r"\$\('([^']+)'\)", js))
missing = sorted(js_ids - html_ids)
print(f"\nids que el JS busca: {len(js_ids)}")
if missing:
    failures.append(f"ids que el JS usa y no existen en el HTML: {missing}")
    print("  [FALLO]", missing)
else:
    print("  [OK   ] todos existen en el HTML")

# ------------------------------- clases que el JS activa y no estan en el CSS
js_classes = set(re.findall(r"classList\.(?:add|toggle|remove)\('([^']+)'", js))
# setStatus monta la clase asi: 'dot ' + (kind || 'offline')
js_classes |= set(re.findall(r"kind \|\| '(\w+)'", js))
# Un selector puede encadenar clases (.dot.offline), asi que recogemos todos
# los nombres de clase de cada selector, no solo el primero.
css_rules: set[str] = set()
for selector in re.findall(r"([^{}]+)\{", css):
    for match in re.finditer(r"\.([a-zA-Z][\w-]*)", selector):
        css_rules.add(match.group(1))
unstyled = sorted(c for c in js_classes if c not in css_rules)
print(f"\nclases que el JS activa: {len(js_classes)} -> {sorted(js_classes)}")
if unstyled:
    failures.append(f"clases sin estilo definido: {unstyled}")
    print("  [FALLO]", unstyled)
else:
    print("  [OK   ] todas tienen estilo")

# --------------------------------------- atributos data-* del HTML <-> JS
data_attrs = {
    "data-panel": "openSheet(button.dataset.panel)",
    "data-close": "cerrar panel",
    "data-quick": "botones rapidos",
    "data-key": "teclas sueltas",
    "data-hotkey": "atajos",
    "data-media": "multimedia",
    "data-volume": "volumen",
    "data-pres": "presentaciones",
}
print("\nAtributos data-* declarados en el HTML:")
for attribute in data_attrs:
    count = len(re.findall(rf'{attribute}(?:="|\s|>)', html))
    # El JS los lee como button.dataset.panel -> dataset.panel
    property_name = attribute.replace("data-", "").replace("-", "")
    # El JS puede leerlo como dataset.panel o seleccionarlo como [data-close].
    used = (
        re.search(rf"dataset\.{property_name}\b", js) is not None
        or f"[{attribute}]" in js
    )
    status = "OK   " if (count and used) else "FALLO"
    if not count or not used:
        failures.append(f"{attribute}: declarado {count} veces, leido en JS: {used}")
    print(f"  [{status}] {attribute:<14} {count:>2} elementos  -> {data_attrs[attribute]}")

# ------------------------------------------ acciones que envia el JS al server
sent = sorted(set(re.findall(r"send\('([a-z_]+)'", js)))
print(f"\nAcciones que el JS envia al servidor: {len(sent)}")

server = (
    Path(__file__).resolve().parent.parent / "server" / "app.py"
).read_text(encoding="utf-8")
known = set(re.findall(r'action == "([a-z_]+)"', server))
known |= {"ping"}
unknown = [a for a in sent if a not in known]
if unknown:
    failures.append(f"acciones que el servidor no reconoce: {unknown}")
    print("  [FALLO]", unknown)
else:
    print("  [OK   ] todas las acciones existen en el servidor")

# ------------------------------------------- ficheros que pide el service worker
# Solo nos interesa la lista FILES; otras cadenas del archivo (nombre de la
# cache, eventos) no son rutas y no deben comprobarse.
sw = (WEB / "sw.js").read_text(encoding="utf-8")
files_block = re.search(r"const FILES = \[(.*?)\]", sw, re.S)
listed = re.findall(r"'([^']+)'", files_block.group(1)) if files_block else []
print("\nFicheros en la cache del service worker:")
for name in listed:
    if name == "./":
        continue
    exists = (WEB / name).is_file()
    if not exists:
        failures.append(f"el service worker lista {name}, que no existe")
    print(f"  [{'OK   ' if exists else 'FALLO'}] {name}")

# --------------------------------------------------- manifest
manifest = (WEB / "manifest.webmanifest").read_text(encoding="utf-8")
icons = re.findall(r'"src":\s*"([^"]+)"', manifest)
print("\nIconos del manifest:")
for icon in icons:
    exists = (WEB / icon).is_file()
    if not exists:
        failures.append(f"el manifest referencia {icon}, que no existe")
    print(f"  [{'OK   ' if exists else 'FALLO'}] {icon}")

print("\n" + "=" * 58)
if failures:
    print(f"  {len(failures)} problema(s) de coherencia:")
    for item in failures:
        print("   -", item)
else:
    print("  Interfaz coherente: HTML, CSS y JS encajan")
print("=" * 58)
sys.exit(1 if failures else 0)
