#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db.py
=====
Cola de trabajos (jobs) y límite de uso por IP, en SQLite. La app Flask (que
recibe la URL del formulario) y el worker always-on (que procesa la cola)
son dos procesos separados en PythonAnywhere, así que usamos WAL mode para
que ambos puedan leer/escribir sin bloquearse entre sí.

Estados de un job: pending -> running -> done | error
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta

DB_PATH = os.environ.get("LOPDP_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    ip TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    client_name TEXT,
    pdf_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_ip_created ON jobs(ip, created_at);
"""


def _connect(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=None):
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now():
    return datetime.utcnow().isoformat()


def create_job(url, ip, db_path=None):
    job_id = uuid.uuid4().hex[:12]
    conn = _connect(db_path)
    try:
        now = _now()
        conn.execute(
            "INSERT INTO jobs (id, url, ip, status, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?)",
            (job_id, url, ip, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def get_job(job_id, db_path=None):
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def count_recent_jobs_by_ip(ip, hours=24, db_path=None):
    conn = _connect(db_path)
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE ip = ? AND created_at > ?", (ip, cutoff)
        ).fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


def claim_next_pending_job(db_path=None):
    """Toma el job pendiente más antiguo y lo marca como 'running'. Devuelve el
    job (dict) o None si no hay nada pendiente. Pensado para que lo llame el
    worker en su loop."""
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?", (_now(), row["id"])
        )
        conn.execute("COMMIT")
        return dict(row)
    except sqlite3.OperationalError:
        conn.execute("ROLLBACK")
        return None
    finally:
        conn.close()


def mark_job_done(job_id, pdf_path, client_name, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE jobs SET status = 'done', pdf_path = ?, client_name = ?, updated_at = ? WHERE id = ?",
            (pdf_path, client_name, _now(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_job_error(job_id, error_message, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE jobs SET status = 'error', error = ?, updated_at = ? WHERE id = ?",
            (error_message[:500], _now(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_old_jobs(days=7, db_path=None):
    """Borra (de la base y del disco) los jobs/PDFs más viejos que `days`. Pensado
    para correrlo como tarea programada periódica (ver README_DEPLOY.md)."""
    conn = _connect(db_path)
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute("SELECT id, pdf_path FROM jobs WHERE created_at < ?", (cutoff,)).fetchall()
        for row in rows:
            if row["pdf_path"] and os.path.exists(row["pdf_path"]):
                try:
                    os.remove(row["pdf_path"])
                except OSError:
                    pass
        conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Base de datos inicializada en: {DB_PATH}")
