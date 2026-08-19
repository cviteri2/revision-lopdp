#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_render.py
=============
Convierte el HTML del informe (report_html.render_report_html) en un PDF real
usando el navegador headless de Playwright (page.pdf()). Reemplaza al paso de
LibreOffice/Abiword, que no está disponible en PythonAnywhere.

Uso:
    from pdf_render import render_pdf
    render_pdf(html, "/ruta/informe.pdf", browser=browser)   # reutiliza un browser
    render_pdf(html, "/ruta/informe.pdf", executable_path="/usr/bin/chromium")  # standalone
"""

from report_html import render_pdf_header, render_pdf_footer


def render_pdf(html, output_path, browser=None, executable_path=None):
    """Genera el PDF a partir del HTML del informe.

    `browser`: instancia ya lanzada de playwright.sync_api Browser, para reutilizarla
    (recomendado en el worker: el mismo browser sirve para el chequeo de rastreadores
    Y para renderizar el PDF, evitando lanzar Chromium dos veces por job).
    `executable_path`: ruta al binario de Chromium (en PythonAnywhere: /usr/bin/chromium).
    Se ignora si se pasa `browser`.
    """
    header_html = render_pdf_header()
    footer_html = render_pdf_footer()

    def _run(active_browser):
        page = active_browser.new_page()
        try:
            page.set_content(html, wait_until="load")
            page.pdf(
                path=output_path,
                format="Letter",
                print_background=True,
                display_header_footer=True,
                header_template=header_html,
                footer_template=footer_html,
                margin={"top": "2.6cm", "bottom": "2.2cm", "left": "3cm", "right": "3cm"},
            )
        finally:
            page.close()

    if browser is not None:
        _run(browser)
        return output_path

    from playwright.sync_api import sync_playwright

    launch_kwargs = {"headless": True}
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
        launch_kwargs["args"] = ["--no-sandbox", "--disable-gpu"]

    with sync_playwright() as p:
        b = p.chromium.launch(**launch_kwargs)
        try:
            _run(b)
        finally:
            b.close()

    return output_path
