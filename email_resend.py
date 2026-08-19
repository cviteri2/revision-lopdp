#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
email_resend.py
================
Envía por correo (vía Resend, https://resend.com) una copia del informe en
PDF a la casilla interna de Protego Consulting, cada vez que el worker
termina un análisis.

Variables de entorno requeridas (ver .env.example / README_DEPLOY.md):
    RESEND_API_KEY     - API key de tu cuenta de Resend
    RESEND_FROM_EMAIL   - remitente verificado en Resend, ej. "Auditor LOPDP <auditor@protego-consulting.com>"
    NOTIFY_TO_EMAIL     - a qué correo interno de Protego llega la copia
"""

import base64
import os

import requests

RESEND_API_URL = "https://api.resend.com/emails"
TIMEOUT = 20


def send_report_email(pdf_path, client_name, site_url, summary):
    """Envía el PDF adjunto por correo. Devuelve (True, None) si se envió, o
    (False, motivo) si falló -- sin lanzar excepción, para que un error de
    correo no tumbe el procesamiento del job."""
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    to_email = os.environ.get("NOTIFY_TO_EMAIL")

    if not api_key or not from_email or not to_email:
        return False, "Faltan variables de entorno RESEND_API_KEY / RESEND_FROM_EMAIL / NOTIFY_TO_EMAIL."

    try:
        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        return False, f"No se pudo leer el PDF para adjuntarlo: {e}"

    subject = f"Nuevo análisis LOPDP: {client_name} ({site_url})"
    resumen_txt = ", ".join(f"{k}: {v}" for k, v in summary.items())
    html_body = (
        f"<p>Se generó un nuevo informe LOPDP desde el widget del sitio.</p>"
        f"<p><strong>Cliente:</strong> {client_name}<br>"
        f"<strong>Sitio analizado:</strong> {site_url}<br>"
        f"<strong>Resumen:</strong> {resumen_txt}</p>"
        f"<p>El informe completo va adjunto en PDF.</p>"
    )

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "attachments": [
            {
                "filename": os.path.basename(pdf_path),
                "content": pdf_b64,
            }
        ],
    }

    try:
        r = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f"Error de red al llamar a Resend: {e}"

    if r.status_code >= 300:
        return False, f"Resend devolvió un error ({r.status_code}): {r.text[:300]}"

    return True, None
