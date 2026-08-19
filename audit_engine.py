#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_engine.py
================
Motor de auditoría LOPDP reutilizable (sin CLI, sin dependencias de Word/Node).
Es el mismo motor que lopdp_audit.py, pensado para ser importado por la app web
(Flask) y el worker en PythonAnywhere.

Uso típico:
    from audit_engine import run_audit
    report = run_audit("https://cliente.com", tracker_wait=8)
    # report es un dict con: url_analizada, url_final, cliente, fecha_analisis,
    # paginas_analizadas, resumen, items, conclusiones

LIMITACIONES: ver README_DEPLOY.md. Este motor solo verifica señales públicas
del sitio web; no sustituye asesoría legal.
"""

import re
import sys
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 LOPDPAuditBot/1.0 "
        "(+https://protego-consulting.com/auditor-lopdp)"
    )
}
TIMEOUT = 15

KEYWORD_LINKS = {
    "privacidad": ["privacidad", "protección de datos", "proteccion de datos", "privacy", "datos personales"],
    "cookies": ["cookies", "cookie"],
    "terminos": ["términos", "terminos", "aviso legal", "condiciones de uso", "terms", "legal"],
    "contacto": ["contacto", "contáctanos", "contact"],
}

TRACKER_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.com/tr",
    "connect.facebook.net",
    "hotjar.com",
    "clarity.ms",
    "analytics.tiktok.com",
    "ads.linkedin.com",
    "px.ads.linkedin.com",
    "snap.licdn.com",
    "bat.bing.com",
    "static.ads-twitter.com",
]

CMP_SIGNATURES = [
    "onetrust", "cookiebot", "iubenda", "cookieyes", "cookie-law-info",
    "complianz", "borlabs-cookie", "cookieconsent", "termly", "usercentrics",
    "axeptio", "didomi", "klaro", "tarteaucitron", "civicuk", "quantcast",
    "cookie-notice", "gdpr-cookie-consent", "cookiehub", "trustarc",
]

STATUS_CUMPLE = "CUMPLE"
STATUS_NO_CUMPLE = "NO_CUMPLE"
STATUS_REVISAR = "REVISAR_MANUAL"
STATUS_NO_DETECTADO = "NO_DETECTADO"

STATUS_PRIORITY = {STATUS_NO_CUMPLE: 0, STATUS_REVISAR: 1, STATUS_NO_DETECTADO: 1, STATUS_CUMPLE: 99}

CHECK_SEVERITY = {
    "3.3": 0, "4.3": 0, "1.1": 0, "3.1": 0, "2.1": 0,
    "3.2": 1, "2.8": 1, "2.9": 1, "4.2": 1, "5.1": 1, "1.2": 1,
    "2.2": 2, "2.3": 2, "2.4": 2, "2.5": 2, "2.6": 2, "2.7": 2, "3.4": 2, "4.4": 2, "6.1": 2,
    "2.10": 3, "4.1": 3,
}

SHORT_RECOMMENDATIONS = {
    "1.1": "Instalar un certificado SSL/TLS para que todo el sitio de {client} cargue por HTTPS.",
    "1.2": "Configurar la redirección automática de HTTP a HTTPS en el sitio de {client}.",
    "2.1": "Publicar la Política de Privacidad de {client} y enlazarla desde el pie de página.",
    "2.2": "Agregar en la política de privacidad el nombre, RUC y datos de contacto de {client}.",
    "2.3": "Detallar en la política de privacidad para qué usa {client} cada dato recolectado.",
    "2.4": "Especificar la base legal de cada tratamiento de datos que realiza {client}.",
    "2.5": "Indicar en la política de privacidad cuánto tiempo conserva {client} los datos personales.",
    "2.6": "Listar en la política de privacidad los proveedores con los que {client} comparte datos.",
    "2.7": "Declarar en la política de privacidad las transferencias internacionales de datos de {client}.",
    "2.8": "Detallar en la política de privacidad los derechos ARCO+ y de portabilidad de los titulares.",
    "2.9": "Indicar el plazo legal de 15 días para responder solicitudes de derechos.",
    "2.10": "Confirmar si {client} debe designar un Delegado de Protección de Datos y publicarlo.",
    "3.1": "Implementar un banner de cookies en el sitio de {client} antes de cargar rastreadores.",
    "3.2": "Agregar la opción de 'Rechazar' cookies en el banner de {client}, no solo 'Aceptar'.",
    "3.3": "Bloquear Google Analytics/Meta Pixel en el sitio de {client} hasta que el usuario consienta.",
    "3.4": "Publicar o completar la política de cookies de {client} con el detalle de cada cookie.",
    "4.1": "Revisar manualmente si {client} usa formularios cargados por JavaScript no detectados aquí.",
    "4.2": "Agregar una casilla de consentimiento (sin marcar) en los formularios de {client}.",
    "4.3": "Quitar la marca automática de las casillas de consentimiento en los formularios de {client}.",
    "4.4": "Enlazar la política de privacidad directamente desde los formularios de {client}.",
    "5.1": "Habilitar un correo o formulario dedicado para que los titulares ejerzan sus derechos ante {client}.",
    "6.1": "Publicar los Términos y Condiciones de uso del sitio de {client}.",
}


def client_name_from_domain(raw_domain):
    if not raw_domain:
        return "el cliente"
    first_label = raw_domain.split(".")[0]
    return first_label.upper() if first_label else "el cliente"


def build_conclusions(items, client_name):
    candidates = [it for it in items if it["status"] != STATUS_CUMPLE]
    candidates.sort(key=lambda it: (STATUS_PRIORITY.get(it["status"], 50), CHECK_SEVERITY.get(it["id"], 2)))
    chosen = candidates[:4]

    conclusions = []
    for it in chosen:
        template = SHORT_RECOMMENDATIONS.get(it["id"])
        if template:
            conclusions.append(template.format(client=client_name))
        else:
            conclusions.append(f"Revisar y corregir: {it['title']} en el sitio de {client_name}.")

    if not conclusions:
        conclusions.append(
            f"{client_name} cumple con los criterios técnicos evaluados en este análisis automatizado."
        )

    conclusions.append("Repetir este análisis después de aplicar los cambios para confirmar el cumplimiento.")
    return conclusions


# ---------------------------------------------------------------------------
# Utilidades de red / rastreo
# ---------------------------------------------------------------------------

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        content_type = r.headers.get("Content-Type", "")
        if "charset" not in content_type.lower() and r.apparent_encoding:
            r.encoding = r.apparent_encoding
        return r
    except requests.RequestException as e:
        print(f"  [!] No se pudo obtener {url}: {e}", file=sys.stderr)
        return None


def same_domain(url, base_netloc):
    try:
        return urlparse(url).netloc.replace("www.", "") == base_netloc.replace("www.", "")
    except Exception:
        return False


def find_candidate_links(base_url, soup, base_netloc):
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").strip().lower()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urljoin(base_url, href)
        if not same_domain(full, base_netloc):
            continue
        haystack = f"{href.lower()} {text}"
        for category, keywords in KEYWORD_LINKS.items():
            if category in found:
                continue
            if any(kw in haystack for kw in keywords):
                found[category] = full
    return found


def crawl(start_url, max_pages=15):
    pages = {}
    parsed = urlparse(start_url)
    if not parsed.scheme:
        start_url = "https://" + start_url
        parsed = urlparse(start_url)
    base_netloc = parsed.netloc

    resp = fetch(start_url)
    if resp is None or not resp.ok:
        raise RuntimeError(f"No se pudo acceder a {start_url} (¿URL correcta? ¿sitio en línea?)")

    soup = BeautifulSoup(resp.text, "html.parser")
    pages["homepage"] = {"url": resp.url, "html": resp.text, "soup": soup}

    candidates = find_candidate_links(resp.url, soup, base_netloc)

    visited_count = 1
    for category, link in candidates.items():
        if visited_count >= max_pages:
            break
        r2 = fetch(link)
        visited_count += 1
        if r2 is None or not r2.ok:
            continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        pages[category] = {"url": r2.url, "html": r2.text, "soup": s2}
        if visited_count < max_pages:
            extra = find_candidate_links(r2.url, s2, base_netloc)
            for cat2, link2 in extra.items():
                if cat2 not in pages and cat2 not in candidates and visited_count < max_pages:
                    r3 = fetch(link2)
                    visited_count += 1
                    if r3 is not None and r3.ok:
                        pages[cat2] = {"url": r3.url, "html": r3.text, "soup": BeautifulSoup(r3.text, "html.parser")}

    return pages


def combined_text(pages, keys=None):
    keys = keys or list(pages.keys())
    parts = []
    for k in keys:
        if k in pages:
            parts.append(pages[k]["soup"].get_text(" ", strip=True).lower())
    return " \n ".join(parts)


def combined_html(pages, keys=None):
    keys = keys or list(pages.keys())
    parts = []
    for k in keys:
        if k in pages:
            parts.append(pages[k]["html"].lower())
    return " \n ".join(parts)


def find_snippet(text, pattern, context=80):
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    start = max(0, m.start() - context)
    end = min(len(text), m.end() + context)
    snippet = text[start:end].replace("\n", " ").strip()
    return ("..." if start > 0 else "") + snippet + ("..." if end < len(text) else "")


class Results:
    def __init__(self):
        self.items = []

    def add(self, section, cid, title, status, evidence, recommendation):
        self.items.append({
            "id": cid,
            "section": section,
            "title": title,
            "status": status,
            "evidence": evidence or "No se encontró evidencia en las páginas analizadas.",
            "recommendation": recommendation,
        })

    def summary(self):
        s = {STATUS_CUMPLE: 0, STATUS_NO_CUMPLE: 0, STATUS_REVISAR: 0, STATUS_NO_DETECTADO: 0}
        for it in self.items:
            s[it["status"]] += 1
        return s


# ---------------------------------------------------------------------------
# Chequeos individuales (idénticos a lopdp_audit.py)
# ---------------------------------------------------------------------------

def check_https(results, start_url, pages):
    home = pages["homepage"]
    final_url = home["url"]
    is_https = urlparse(final_url).scheme == "https"
    results.add(
        "1. Aspectos técnicos", "1.1", "Conexión segura (HTTPS)",
        STATUS_CUMPLE if is_https else STATUS_NO_CUMPLE,
        f"URL final tras cargar el sitio: {final_url}",
        "Ninguna: el sitio ya usa HTTPS." if is_https else
        "Instalar un certificado SSL/TLS y servir todo el sitio por HTTPS. Sin cifrado en tránsito, "
        "cualquier dato personal enviado en formularios viaja expuesto, lo que es una falla grave de "
        "seguridad exigida por la LOPDP.",
    )

    parsed = urlparse(start_url if "://" in start_url else "https://" + start_url)
    http_url = f"http://{parsed.netloc}{parsed.path or '/'}"
    try:
        r = requests.get(http_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        redirected_to_https = urlparse(r.url).scheme == "https"
        status = STATUS_CUMPLE if redirected_to_https else STATUS_NO_CUMPLE
        evidence = f"http://{parsed.netloc} redirige a: {r.url}"
    except requests.RequestException as e:
        status = STATUS_REVISAR
        evidence = f"No se pudo probar la redirección HTTP->HTTPS automáticamente ({e})."
    results.add(
        "1. Aspectos técnicos", "1.2", "Redirección forzada de HTTP a HTTPS",
        status, evidence,
        "Ninguna." if status == STATUS_CUMPLE else
        "Configurar una redirección 301 permanente de todo el tráfico HTTP hacia HTTPS a nivel de "
        "servidor/CDN.",
    )


def check_privacy_policy(results, pages):
    home_html = pages["homepage"]["html"].lower()
    has_link = "privacidad" in home_html or "privacy" in home_html or "protecci" in home_html
    priv_page = pages.get("privacidad")

    results.add(
        "2. Política de Privacidad", "2.1", "Enlace visible a la Política de Privacidad",
        STATUS_CUMPLE if priv_page else (STATUS_REVISAR if has_link else STATUS_NO_CUMPLE),
        (f"Página encontrada en: {priv_page['url']}" if priv_page else
         "Se detectó texto relacionado en la portada, pero no se pudo confirmar un enlace directo a "
         "una página dedicada." if has_link else
         "No se encontró ningún enlace con texto/URL relacionado a 'privacidad' o 'protección de datos' "
         "en la portada (usualmente debería estar en el pie de página)."),
        "Ninguna." if priv_page else
        "Publicar una Política de Privacidad como página independiente y enlazarla claramente desde el "
        "pie de página de todo el sitio.",
    )

    if not priv_page:
        for cid, title in [
            ("2.2", "Identificación del responsable del tratamiento"),
            ("2.3", "Finalidades del tratamiento especificadas"),
            ("2.4", "Base legal del tratamiento"),
            ("2.5", "Plazo de conservación de los datos"),
            ("2.6", "Terceros/destinatarios de los datos"),
            ("2.7", "Transferencias internacionales de datos"),
            ("2.8", "Derechos ARCO+ y portabilidad"),
            ("2.9", "Plazo de respuesta a solicitudes (15 días)"),
            ("2.10", "Delegado de Protección de Datos (DPO) mencionado"),
        ]:
            results.add(
                "2. Política de Privacidad", cid, title, STATUS_NO_CUMPLE,
                "No se encontró una página de Política de Privacidad para evaluar este punto.",
                "Publicar primero la Política de Privacidad; luego re-ejecutar esta auditoría.",
            )
        return

    text = priv_page["soup"].get_text(" ", strip=True)

    checks = [
        ("2.2", "Identificación del responsable del tratamiento",
         r"responsable del tratamiento|razón social|R\.?U\.?C\.?\s*[:#]?\s*\d{10,13}",
         "Indicar claramente el nombre/razón social, RUC y datos de contacto de la empresa responsable "
         "del tratamiento de los datos."),
        ("2.3", "Finalidades del tratamiento especificadas",
         r"finalidad(es)?\s+del\s+tratamiento|para\s+qué\s+usamos|finalidad(es)?\s+específica",
         "Detallar de forma específica (no genérica) para qué se usará cada dato recolectado."),
        ("2.4", "Base legal del tratamiento",
         r"base\s+legal|fundamento\s+jurídico|consentimiento\s+del\s+titular\s+de\s+los\s+datos",
         "Especificar la base legal aplicable a cada tratamiento (consentimiento, ejecución de contrato, "
         "obligación legal, etc.), no solo mencionar 'consentimiento' de forma genérica."),
        ("2.5", "Plazo de conservación de los datos",
         r"plazo\s+de\s+conservaci|tiempo\s+de\s+conservaci|per[ií]odo\s+de\s+conservaci|"
         r"conservaci[oó]n\s+de\s+(los\s+)?datos|se\s+conservar[aá]n|mientras\s+dure\s+la\s+relaci[oó]n",
         "Indicar por cuánto tiempo se conservarán los datos personales, o el criterio para determinarlo."),
        ("2.6", "Terceros/destinatarios de los datos",
         r"terceros|destinatarios\s+de\s+(los\s+)?datos|compartimos.{0,30}(datos|información)",
         "Listar a qué terceros/proveedores se comparten los datos (ej. pasarela de pago, CRM, email "
         "marketing) y con qué propósito."),
        ("2.7", "Transferencias internacionales de datos",
         r"transferencia(s)?\s+internacional(es)?\s+de\s+datos|fuera\s+del\s+(país|ecuador)",
         "Si se usan servicios como Google Analytics, Meta, Mailchimp, hosting en el extranjero, etc., "
         "declarar explícitamente el destino de la transferencia y las salvaguardas aplicadas."),
        ("2.8", "Derechos ARCO+ y portabilidad",
         r"derechos?\s+arco|acceso,?\s+rectificación,?\s+cancelación|derecho\s+de\s+(acceso|rectificación|oposición|portabilidad)",
         "Detallar explícitamente los derechos ARCO+ (Acceso, Rectificación, Cancelación, Oposición) más "
         "Portabilidad y Limitación, y cómo se ejercen."),
        ("2.9", "Plazo de respuesta a solicitudes (15 días)",
         r"15\s+días|quince\s+días",
         "Indicar el plazo legal de 15 días (hábiles, prorrogables 10 días más) para responder solicitudes "
         "de derechos."),
        ("2.10", "Delegado de Protección de Datos (DPO) mencionado",
         r"delegado\s+de\s+protección\s+de\s+datos|\bdpo\b|oficial\s+de\s+protección\s+de\s+datos",
         "Si aplica (tratamiento a gran escala, datos sensibles o sector público), identificar al Delegado "
         "de Protección de Datos y su canal de contacto."),
    ]

    for cid, title, pattern, reco in checks:
        snippet = find_snippet(text, pattern)
        status = STATUS_CUMPLE if snippet else STATUS_NO_CUMPLE
        if cid == "2.10" and not snippet:
            status = STATUS_REVISAR
            reco = ("No se menciona un DPO. Confirmar con el cliente si su actividad exige uno (tratamiento "
                    "a gran escala, datos sensibles, o sector público); si no aplica, este punto se puede "
                    "descartar.")
        results.add("2. Política de Privacidad", cid, title, status,
                     snippet or f"No se encontró el texto esperado en: {priv_page['url']}", reco)


def check_cookies(results, pages):
    all_html = combined_html(pages)
    all_text = combined_text(pages)

    cmp_found = [sig for sig in CMP_SIGNATURES if sig in all_html]
    generic_banner = bool(re.search(r"(usamos|utilizamos)\s+cookies|aviso\s+de\s+cookies|banner\s+de\s+cookies", all_text))
    has_banner = bool(cmp_found) or generic_banner

    results.add(
        "3. Cookies y rastreo", "3.1", "Banner/aviso de cookies presente",
        STATUS_CUMPLE if has_banner else STATUS_NO_CUMPLE,
        (f"Se detectó la plataforma de gestión de consentimiento: {', '.join(cmp_found)}." if cmp_found else
         "Se detectó texto genérico relacionado a cookies." if generic_banner else
         "No se encontró ningún banner de cookies, ni texto ni scripts de plataformas de consentimiento "
         "conocidas (OneTrust, Cookiebot, Iubenda, CookieYes, etc.)."),
        "Ninguna." if has_banner else
        "Implementar un banner de consentimiento de cookies que se muestre antes de cargar cualquier "
        "script no esencial (analítica, publicidad).",
    )

    can_reject = bool(re.search(r"rechazar|no\s+acepto|solo\s+esenciales|gestionar\s+cookies|personalizar\s+cookies|configurar\s+cookies", all_text))
    results.add(
        "3. Cookies y rastreo", "3.2", "El banner permite RECHAZAR (no solo aceptar)",
        STATUS_CUMPLE if (has_banner and can_reject) else STATUS_NO_CUMPLE,
        ("Se encontró lenguaje de rechazo/configuración de cookies en el sitio." if can_reject else
         "No se encontró un botón o texto de 'rechazar'/'configurar' cookies; muchos banners solo ofrecen "
         "'Aceptar', lo cual no constituye consentimiento libre según la LOPDP."),
        "Ninguna." if can_reject else
        "El consentimiento debe ser una elección real: agregar opciones de 'Rechazar' y 'Configurar por "
        "categoría', no solo un botón de 'Aceptar'.",
    )

    cookie_policy_page = pages.get("cookies")
    results.add(
        "3. Cookies y rastreo", "3.4", "Política de cookies específica (propia o dentro de la política de privacidad)",
        STATUS_CUMPLE if cookie_policy_page else STATUS_REVISAR,
        (f"Página dedicada encontrada en: {cookie_policy_page['url']}" if cookie_policy_page else
         "No se encontró una página separada de política de cookies; puede estar integrada en la "
         "política de privacidad (revisar manualmente)."),
        "Ninguna." if cookie_policy_page else
        "Confirmar que la política de privacidad incluya el detalle de cookies (tipos, duración, "
        "finalidad, terceros), o publicar una política de cookies independiente.",
    )


def check_trackers_playwright(url, timeout_s=8, browser=None, executable_path=None):
    """Carga la portada con un navegador headless y observa si se hacen peticiones de red
    a dominios de analítica/publicidad conocidos ANTES de cualquier interacción del usuario.

    Si se pasa `browser` (una instancia ya lanzada de Playwright), la reutiliza en vez de
    lanzar un Chromium nuevo (útil en el worker web, donde el mismo browser se reutiliza
    también para renderizar el PDF del informe)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return STATUS_REVISAR, "Playwright no está instalado; no se pudo verificar de forma dinámica."

    contacted = set()

    def _run(active_browser):
        context = active_browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        def on_request(request):
            req_url = request.url.lower()
            for domain in TRACKER_DOMAINS:
                if domain in req_url:
                    contacted.add(domain)

        page.on("request", on_request)
        page.goto(url, wait_until="load", timeout=timeout_s * 1000)
        page.wait_for_timeout(timeout_s * 1000)
        context.close()

    try:
        if browser is not None:
            _run(browser)
        else:
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
    except Exception as e:
        return STATUS_REVISAR, f"No se pudo completar la verificación dinámica con navegador headless ({e})."

    if contacted:
        return STATUS_NO_CUMPLE, (
            "El navegador headless detectó peticiones a estos dominios de rastreo ANTES de cualquier "
            "interacción con el banner de cookies: " + ", ".join(sorted(contacted)) + ". Esto indica que "
            "los scripts de analítica/publicidad se cargan sin haber obtenido consentimiento previo."
        )
    return STATUS_CUMPLE, (
        "No se detectaron peticiones a dominios de rastreo conocidos durante la carga inicial de la "
        f"página (ventana de observación: {timeout_s}s, sin interactuar con el sitio)."
    )


def check_forms(results, pages):
    all_forms = []
    for key, page in pages.items():
        for form in page["soup"].find_all("form"):
            all_forms.append((key, form))

    if not all_forms:
        results.add(
            "4. Formularios y consentimiento", "4.1", "Formularios detectados que recolectan datos",
            STATUS_NO_DETECTADO,
            "No se encontraron elementos <form> en las páginas analizadas (puede que el sitio use "
            "formularios cargados dinámicamente vía JavaScript que este análisis estático no detecta).",
            "Revisar manualmente si existen formularios (contacto, newsletter, checkout, registro) "
            "cargados por JavaScript, y aplicarles los mismos criterios de consentimiento.",
        )
        results.add("4. Formularios y consentimiento", "4.2", "Casilla de consentimiento en formularios",
                     STATUS_NO_DETECTADO, "No aplica: no se detectaron formularios.", "Ver punto 4.1.")
        results.add("4. Formularios y consentimiento", "4.3", "Casillas de consentimiento NO premarcadas",
                     STATUS_NO_DETECTADO, "No aplica: no se detectaron formularios.", "Ver punto 4.1.")
        results.add("4. Formularios y consentimiento", "4.4", "Enlace a política de privacidad junto al formulario",
                     STATUS_NO_DETECTADO, "No aplica: no se detectaron formularios.", "Ver punto 4.1.")
        return

    forms_with_checkbox = 0
    forms_with_premarked = []
    forms_with_privacy_link = 0

    for key, form in all_forms:
        form_text = form.get_text(" ", strip=True).lower()
        checkboxes = form.find_all("input", attrs={"type": "checkbox"})
        if checkboxes:
            forms_with_checkbox += 1
            for cb in checkboxes:
                if cb.has_attr("checked"):
                    forms_with_premarked.append(key)
        if "privacidad" in form_text or "política" in str(form).lower() or form.find("a", href=re.compile("priva", re.I)):
            forms_with_privacy_link += 1

    results.add(
        "4. Formularios y consentimiento", "4.1", "Formularios detectados que recolectan datos",
        STATUS_CUMPLE,
        f"Se detectaron {len(all_forms)} formulario(s) en las páginas: {', '.join(sorted(set(k for k, _ in all_forms)))}.",
        "Ninguna (informativo).",
    )
    results.add(
        "4. Formularios y consentimiento", "4.2", "Casilla de consentimiento presente en formularios",
        STATUS_CUMPLE if forms_with_checkbox else STATUS_NO_CUMPLE,
        f"{forms_with_checkbox} de {len(all_forms)} formulario(s) tienen al menos un checkbox." if forms_with_checkbox
        else "Ningún formulario detectado tiene un checkbox de consentimiento explícito.",
        "Ninguna." if forms_with_checkbox else
        "Agregar una casilla de consentimiento explícita (sin premarcar) junto al texto 'He leído y "
        "acepto la Política de Privacidad' en cada formulario que recolecte datos.",
    )
    results.add(
        "4. Formularios y consentimiento", "4.3", "Casillas de consentimiento NO premarcadas",
        STATUS_NO_CUMPLE if forms_with_premarked else (STATUS_CUMPLE if forms_with_checkbox else STATUS_REVISAR),
        f"Se encontraron checkboxes premarcados (atributo 'checked') en: {', '.join(set(forms_with_premarked))}."
        if forms_with_premarked else
        ("Ningún checkbox de consentimiento aparece premarcado en el HTML analizado." if forms_with_checkbox else
         "No hay checkboxes de consentimiento que evaluar (ver punto 4.2)."),
        "Ninguna." if not forms_with_premarked else
        "Quitar el atributo 'checked' de las casillas de consentimiento: el consentimiento por omisión "
        "no es válido bajo la LOPDP.",
    )
    results.add(
        "4. Formularios y consentimiento", "4.4", "Enlace a política de privacidad junto al formulario",
        STATUS_CUMPLE if forms_with_privacy_link else STATUS_REVISAR,
        f"{forms_with_privacy_link} de {len(all_forms)} formulario(s) referencian la política de privacidad."
        if forms_with_privacy_link else
        "No se detectó texto o enlace a 'política de privacidad' dentro de los formularios analizados.",
        "Ninguna." if forms_with_privacy_link else
        "Enlazar la Política de Privacidad directamente desde cada formulario que recolecte datos "
        "personales.",
    )


def check_arco_channel(results, pages):
    text = combined_text(pages, ["privacidad", "contacto", "homepage", "cookies"])
    email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    emails = email_pattern.findall(text)
    priority_emails = [e for e in emails if any(w in e.lower() for w in ["privacidad", "datos", "dpo", "proteccion"])]
    has_arco_phrase = bool(re.search(r"ejercer\s+sus\s+derechos|formulario\s+de\s+derechos|solicitud\s+de\s+derechos", text))

    if priority_emails:
        status = STATUS_CUMPLE
        evidence = f"Correo(s) dedicado(s) encontrado(s): {', '.join(set(priority_emails))}."
    elif emails and has_arco_phrase:
        status = STATUS_CUMPLE
        evidence = f"Se menciona un canal para ejercer derechos y hay correo(s) de contacto disponible(s): {', '.join(set(emails[:3]))}."
    elif emails:
        status = STATUS_REVISAR
        evidence = f"Hay correo(s) de contacto general ({', '.join(set(emails[:3]))}) pero no está claro si son el canal designado para derechos ARCO+."
    else:
        status = STATUS_NO_CUMPLE
        evidence = "No se encontró ningún correo electrónico ni formulario dedicado para ejercer derechos ARCO+."

    results.add(
        "5. Derechos ARCO+ y canal de contacto", "5.1", "Canal específico para ejercer derechos (correo/formulario dedicado)",
        status, evidence,
        "Ninguna." if status == STATUS_CUMPLE else
        "Habilitar un correo dedicado (ej. privacidad@empresa.com o datos@empresa.com) o un formulario "
        "específico para que los titulares ejerzan sus derechos ARCO+, y mencionarlo explícitamente en "
        "la política de privacidad.",
    )


def check_terms(results, pages):
    terms_page = pages.get("terminos")
    results.add(
        "6. Otros documentos legales", "6.1", "Términos y condiciones / Aviso legal publicado",
        STATUS_CUMPLE if terms_page else STATUS_REVISAR,
        f"Página encontrada en: {terms_page['url']}" if terms_page else
        "No se encontró una página de Términos y Condiciones o Aviso Legal enlazada desde la portada.",
        "Ninguna." if terms_page else
        "Publicar Términos y Condiciones de uso del sitio, separados de la Política de Privacidad.",
    )


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def run_audit(start_url, max_pages=12, use_browser=True, tracker_wait=8, browser=None, executable_path=None):
    """Ejecuta la auditoría completa y devuelve el dict del informe.

    `browser`: instancia opcional de Playwright Browser ya lanzada, para reutilizarla
    (el worker web la reutiliza también para renderizar el PDF, evitando lanzar
    Chromium dos veces por job).
    `executable_path`: ruta al binario de Chromium (necesaria en PythonAnywhere:
    normalmente /usr/bin/chromium). Se ignora si se pasa `browser`.
    """
    results = Results()
    pages = crawl(start_url, max_pages=max_pages)

    check_https(results, start_url, pages)
    check_privacy_policy(results, pages)
    check_cookies(results, pages)

    if use_browser:
        status, evidence = check_trackers_playwright(
            pages["homepage"]["url"], timeout_s=tracker_wait, browser=browser, executable_path=executable_path
        )
    else:
        status, evidence = STATUS_REVISAR, "Verificación dinámica omitida."
    results.add(
        "3. Cookies y rastreo", "3.3",
        "Rastreadores (Google Analytics/Meta Pixel/etc.) cargan ANTES del consentimiento",
        status, evidence,
        "Ninguna." if status == STATUS_CUMPLE else
        "Configurar el gestor de consentimiento (CMP) para bloquear todo script de analítica/publicidad "
        "hasta que el usuario dé su consentimiento explícito (consent mode / bloqueo de tags).",
    )

    check_forms(results, pages)
    check_arco_channel(results, pages)
    check_terms(results, pages)

    results.items.sort(key=lambda it: [int(p) if p.isdigit() else p for p in it["id"].split(".")])

    raw_domain = urlparse(pages["homepage"]["url"]).netloc.replace("www.", "")
    client_name = client_name_from_domain(raw_domain)

    report = {
        "url_analizada": start_url,
        "url_final": pages["homepage"]["url"],
        "cliente": client_name,
        "fecha_analisis": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "paginas_analizadas": {k: v["url"] for k, v in pages.items()},
        "resumen": results.summary(),
        "items": results.items,
        "conclusiones": build_conclusions(results.items, client_name),
    }
    return report
