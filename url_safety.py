#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
url_safety.py
=============
Validación de la URL que manda el usuario en el widget público, para evitar
SSRF (Server-Side Request Forgery): que alguien use el formulario para hacer
que TU servidor le pegue a una IP interna, a localhost, o al endpoint de
metadata de la nube (169.254.169.254), en vez de a un sitio web real.

Uso:
    ok, reason_or_url = is_safe_public_url("https://cliente.com")
    if not ok:
        return error(reason_or_url)
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

MAX_URL_LENGTH = 300

# Escotilla SOLO para desarrollo local: permite apuntar a sitios de prueba en
# localhost/red privada para probar el pipeline completo sin salir a internet.
# NUNCA debe estar en "1" en producción -- ahí es donde vive la protección SSRF.
_ALLOW_PRIVATE_HOSTS = os.environ.get("ALLOW_PRIVATE_HOSTS", "0") == "1"

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _is_private_or_reserved(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # si no se puede parsear, más vale bloquear
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 6 and ip.is_site_local)
    )


def is_safe_public_url(raw_url):
    """Devuelve (True, url_normalizada) si la URL es segura de rastrear, o
    (False, mensaje_de_error) si no."""
    if not raw_url or not isinstance(raw_url, str):
        return False, "URL vacía."

    raw_url = raw_url.strip()
    if len(raw_url) > MAX_URL_LENGTH:
        return False, "La URL es demasiado larga."

    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)

    if parsed.scheme not in ("http", "https"):
        return False, "Solo se aceptan URLs http:// o https://."

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "No se pudo identificar el dominio en la URL."

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
        return False, "Ese dominio no está permitido."

    if _ALLOW_PRIVATE_HOSTS:
        return True, raw_url

    # Si el propio hostname ya es una IP literal, validar directo
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        if _is_private_or_reserved(hostname.strip("[]")):
            return False, "No se permite analizar direcciones IP privadas o internas."
    except ValueError:
        pass  # es un dominio normal, no una IP literal -> se resuelve abajo

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, "No se pudo resolver ese dominio. Verifica que la URL sea correcta."

    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        return False, "No se pudo resolver ese dominio."

    for ip_str in resolved_ips:
        if _is_private_or_reserved(ip_str):
            return False, "Ese dominio apunta a una dirección de red privada/interna, no está permitido."

    return True, raw_url
