#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
worker.py
=========
Worker en segundo plano que procesa la cola de jobs (SQLite). Está pensado
para correr como "Always-on task" de PythonAnywhere (Web tab > Tasks), que lo
mantiene vivo indefinidamente y lo reinicia solo si se cae.

Por cada job pendiente:
    1. Corre la auditoría (audit_engine.run_audit)
    2. Genera el HTML con la marca de Protego (report_html.render_report_html)
    3. Lo imprime a PDF con el mismo navegador headless (pdf_render.render_pdf)
    4. Envía una copia por correo a Protego (email_resend.send_report_email)
    5. Marca el job como 'done' (o 'error' si algo falló)

Uso local (fuera de PythonAnywhere, para probar):
    python3 worker.py

Variables de entorno relevantes (ver .env.example):
    CHROMIUM_PATH     - ruta al binario de Chromium (en PythonAnywhere: /usr/bin/chromium)
    REPORTS_DIR       - carpeta donde se guardan los PDF generados
    MAX_PAGES         - páginas a rastrear por sitio (default 12)
    TRACKER_WAIT      - segundos de observación de red del chequeo de cookies (default 6)
    POLL_INTERVAL     - segundos entre revisiones de la cola cuando está vacía (default 3)
"""

import os
import sys
import time
import traceback
from datetime import datetime, timedelta

import db
from audit_engine import run_audit
from report_html import render_report_html
from pdf_render import render_pdf
from email_resend import send_report_email

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get("REPORTS_DIR", os.path.join(BASE_DIR, "reports"))
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH") or None
MAX_PAGES = int(os.environ.get("MAX_PAGES", "12"))
TRACKER_WAIT = int(os.environ.get("TRACKER_WAIT", "6"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "3"))
CLEANUP_AFTER_DAYS = int(os.environ.get("CLEANUP_AFTER_DAYS", "7"))

os.makedirs(REPORTS_DIR, exist_ok=True)
db.init_db()


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def launch_browser(playwright):
    launch_kwargs = {"headless": True}
    if CHROMIUM_PATH:
        launch_kwargs["executable_path"] = CHROMIUM_PATH
        launch_kwargs["args"] = ["--no-sandbox", "--disable-gpu"]
    return playwright.chromium.launch(**launch_kwargs)


def process_job(job, browser):
    job_id = job["id"]
    url = job["url"]
    log(f"Procesando job {job_id}: {url}")

    report = run_audit(url, max_pages=MAX_PAGES, use_browser=True, tracker_wait=TRACKER_WAIT, browser=browser)
    html = render_report_html(report)

    pdf_path = os.path.join(REPORTS_DIR, f"{job_id}.pdf")
    render_pdf(html, pdf_path, browser=browser)

    sent_ok, sent_err = send_report_email(pdf_path, report["cliente"], report["url_final"], report["resumen"])
    if not sent_ok:
        log(f"  [!] No se pudo enviar el correo de notificación: {sent_err}")

    db.mark_job_done(job_id, pdf_path, report["cliente"])
    log(f"  OK -> cliente={report['cliente']} resumen={report['resumen']}")


def main():
    from playwright.sync_api import sync_playwright

    log("Worker LOPDP iniciando...")
    last_cleanup = datetime.min

    with sync_playwright() as p:
        browser = launch_browser(p)
        log("Navegador headless listo.")

        while True:
            try:
                if datetime.now() - last_cleanup > timedelta(days=1):
                    removed = db.cleanup_old_jobs(days=CLEANUP_AFTER_DAYS)
                    if removed:
                        log(f"Limpieza: {removed} job(s)/PDF(s) viejos eliminados.")
                    last_cleanup = datetime.now()

                job = db.claim_next_pending_job()
                if not job:
                    time.sleep(POLL_INTERVAL)
                    continue

                try:
                    process_job(job, browser)
                except Exception as e:
                    log(f"  [ERROR] job {job['id']} falló: {e}")
                    traceback.print_exc()
                    db.mark_job_error(job["id"], str(e))

            except KeyboardInterrupt:
                log("Worker detenido manualmente.")
                break
            except Exception as loop_err:
                # Un error inesperado en el loop (ej. el browser se cayó) no debe
                # matar la tarea always-on: lo registramos, reintentamos lanzar el
                # navegador si hace falta, y seguimos.
                log(f"[ERROR] Fallo inesperado en el loop del worker: {loop_err}")
                traceback.print_exc()
                try:
                    browser.close()
                except Exception:
                    pass
                time.sleep(5)
                browser = launch_browser(p)
                log("Navegador headless relanzado tras error.")

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
