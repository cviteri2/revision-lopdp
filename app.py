#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py
======
App Flask que expone la API que consume el widget del sitio (protego-consulting.com):

    POST /api/analyze          { "url": "https://cliente.com" }  -> { "job_id": "..." }
    GET  /api/status/<job_id>  -> { "status": "pending|running|done|error", ... }
    GET  /reports/<job_id>.pdf -> descarga el PDF ya generado

El análisis NO se ejecuta aquí (sería demasiado lento para una sola petición
HTTP: 20-90 segundos). Esta app solo encola el job en SQLite; el trabajo real
lo hace worker.py, corriendo como tarea "always-on" separada.

Variables de entorno relevantes (ver .env.example):
    ALLOWED_ORIGIN       - origen permitido para CORS, ej. https://protego-consulting.com
    RATE_LIMIT_PER_DAY   - máx. análisis por IP cada 24h (default 5)
    REPORTS_DIR          - carpeta donde el worker escribe los PDF (default ./reports)
"""

import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import db
from url_safety import is_safe_public_url

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get("REPORTS_DIR", os.path.join(BASE_DIR, "reports"))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://protego-consulting.com")
RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "5"))

os.makedirs(REPORTS_DIR, exist_ok=True)
db.init_db()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGIN}, r"/reports/*": {"origins": ALLOWED_ORIGIN}})


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    raw_url = (data.get("url") or "").strip()

    if not raw_url:
        return jsonify({"error": "Debes indicar una URL."}), 400

    ok, result = is_safe_public_url(raw_url)
    if not ok:
        return jsonify({"error": result}), 400
    safe_url = result

    ip = get_client_ip()
    recent = db.count_recent_jobs_by_ip(ip, hours=24)
    if recent >= RATE_LIMIT_PER_DAY:
        return jsonify({
            "error": f"Has alcanzado el límite de {RATE_LIMIT_PER_DAY} análisis gratuitos por día. Intenta de nuevo mañana."
        }), 429

    job_id = db.create_job(safe_url, ip)
    return jsonify({"job_id": job_id, "status": "pending"}), 202


@app.route("/api/status/<job_id>", methods=["GET"])
def status(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "No existe ese análisis."}), 404

    response = {
        "status": job["status"],
        "url": job["url"],
        "cliente": job.get("client_name"),
    }
    if job["status"] == "done":
        response["download_url"] = f"/reports/{job_id}.pdf"
    elif job["status"] == "error":
        response["error"] = job.get("error") or "Ocurrió un error al analizar el sitio."
    return jsonify(response)


@app.route("/reports/<job_id>.pdf", methods=["GET"])
def download_report(job_id):
    job = db.get_job(job_id)
    if not job or job["status"] != "done" or not job.get("pdf_path"):
        return jsonify({"error": "El informe no está disponible."}), 404

    directory = os.path.dirname(job["pdf_path"])
    filename = os.path.basename(job["pdf_path"])
    download_name = f"informe_lopdp_{(job.get('client_name') or 'informe').lower()}.pdf"
    return send_from_directory(directory, filename, as_attachment=True, download_name=download_name)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
