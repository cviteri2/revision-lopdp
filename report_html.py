#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_html.py
==============
Convierte el dict que produce audit_engine.run_audit() en HTML autocontenido
(fuente, logo e íconos embebidos en base64) listo para imprimirse a PDF con
Playwright. Reemplaza al viejo generate_report.js + LibreOffice: no depende de
Word ni de un segundo programa externo, así que corre sin problema en
PythonAnywhere.

Nota sobre la tipografía: "Century Gothic" es una fuente comercial de
Monotype y no se puede embeber legalmente en un PDF servido públicamente
desde una web sin una licencia de uso web. Por eso este renderer usa
"TeX Gyre Adventor" (licencia SIL Open Font License, gratuita), una fuente
geométrica de la misma familia visual, como reemplazo. Si Protego Consulting
adquiere una licencia web de Century Gothic, basta con reemplazar los 4
archivos .otf en assets/fonts/ (mismo nombre) y ajustar FONT_FILES abajo.
"""

import base64
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

FONT_FILES = {
    "font_regular": "texgyreadventor-regular.otf",
    "font_bold": "texgyreadventor-bold.otf",
    "font_italic": "texgyreadventor-italic.otf",
    "font_bolditalic": "texgyreadventor-bolditalic.otf",
}

STATUS_ORDER = [
    ("CUMPLE", "CUMPLE"),
    ("NO_CUMPLE", "NO CUMPLE"),
    ("REVISAR_MANUAL", "REVISAR MANUAL"),
    ("NO_DETECTADO", "NO DETECTADO"),
]
STATUS_LABEL = {k: v for k, v in STATUS_ORDER}

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

_asset_cache = {}


def _b64_file(path):
    if path not in _asset_cache:
        with open(path, "rb") as f:
            _asset_cache[path] = base64.b64encode(f.read()).decode("ascii")
    return _asset_cache[path]


def _grouped_sections(items):
    """Agrupa los items por sección preservando el orden de aparición."""
    order = []
    grouped = {}
    for it in items:
        sec = it["section"]
        if sec not in grouped:
            grouped[sec] = []
            order.append(sec)
        grouped[sec].append(it)
    return [(sec, grouped[sec]) for sec in order]


def render_report_html(report):
    """Devuelve el HTML completo del informe (para pasar a page.set_content())."""
    template = _env.get_template("report.html")
    context = {
        "report": report,
        "sections": _grouped_sections(report["items"]),
        "status_order": STATUS_ORDER,
        "status_label": STATUS_LABEL,
        "banner_b64": _b64_file(os.path.join(ASSETS_DIR, "protego_banner.png")),
    }
    for key, filename in FONT_FILES.items():
        context[key] = _b64_file(os.path.join(FONTS_DIR, filename))
    return template.render(**context)


def render_pdf_header():
    template = _env.get_template("pdf_header.html")
    return template.render(icon_b64=_b64_file(os.path.join(ASSETS_DIR, "protego_icon.png")))


def render_pdf_footer():
    template = _env.get_template("pdf_footer.html")
    return template.render()
