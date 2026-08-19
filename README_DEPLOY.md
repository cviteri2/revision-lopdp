# Despliegue en PythonAnywhere — Auditor LOPDP para protego-consulting.com

Esta guía asume que ya tienes:
- Una cuenta **PythonAnywhere Developer** (de pago) — necesaria para tener
  acceso completo a internet y para poder correr una tarea "always-on".
- Una cuenta **Resend** con tu dominio (protego-consulting.com) verificado.
- El código de este proyecto (`protego_web/`) en un repositorio Git al que
  puedas hacer `git clone` desde PythonAnywhere.

Todo lo que sigue se ejecuta en una **consola Bash de PythonAnywhere**
("Consoles" → "Bash"), no en tu computadora.

---

## 1. Clonar el proyecto y crear el entorno virtual

```bash
cd ~
git clone <URL-DE-TU-REPOSITORIO> protego_web
cd protego_web

mkvirtualenv protego-lopdp --python=python3.10
pip install -r requirements.txt
```

Espera unos minutos: Playwright y sus dependencias pesan un poco. No
ejecutes `playwright install` — PythonAnywhere no lo permite y no hace
falta, porque usamos el Chromium que ya viene preinstalado en
`/usr/bin/chromium`.

Crea la carpeta donde se guardarán los PDF generados:

```bash
mkdir -p ~/protego_web/reports
```

---

## 2. Configurar la app web (Flask)

1. Ve a la pestaña **Web** → **Add a new web app**.
2. Elige **Manual configuration** → **Python 3.10**.
3. En **Code**:
   - **Source code**: `/home/TUUSUARIO/protego_web`
   - **Working directory**: `/home/TUUSUARIO/protego_web`
4. En **Virtualenv**, indica la ruta del entorno que creaste:
   `/home/TUUSUARIO/.virtualenvs/protego-lopdp`
5. Abre el **archivo WSGI** (el enlace bajo "Code", algo como
   `/var/www/tuusuario_pythonanywhere_com_wsgi.py`) y reemplaza su
   contenido por esto (ajustando `TUUSUARIO` y las variables de la sección
   de Resend/CORS con tus datos reales):

```python
import sys
import os

project_home = '/home/TUUSUARIO/protego_web'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# ---- Variables de entorno (ver .env.example para la lista completa) ----
os.environ['ALLOWED_ORIGIN'] = 'https://protego-consulting.com'
os.environ['REPORTS_DIR'] = '/home/TUUSUARIO/protego_web/reports'
os.environ['LOPDP_DB_PATH'] = '/home/TUUSUARIO/protego_web/jobs.sqlite3'
os.environ['RATE_LIMIT_PER_DAY'] = '5'

from app import app as application
```

No pongas aquí las variables de Resend (`RESEND_API_KEY`, etc.) — esas solo
las necesita `worker.py`, no la app Flask. Mantener la superficie de
variables sensibles en un solo proceso reduce el riesgo si algo se filtra
por error en logs.

6. Guarda y dale **Reload** al web app (botón verde arriba de la página Web).
7. Prueba: abre `https://TUUSUARIO.pythonanywhere.com/api/health` en el
   navegador. Debe responder `{"ok": true}`.

---

## 3. Configurar la tarea always-on (el worker)

El worker es el proceso que realmente hace el análisis (rastrea el sitio,
genera el PDF, envía el correo). Es lento (20-90+ segundos por sitio), así
que **no** corre dentro de la app Flask — corre aparte, todo el tiempo,
como tarea "always-on".

1. Ve a la pestaña **Tasks** (o "Always-on tasks", según tu plan).
2. En **Command**, pon:

```bash
export CHROMIUM_PATH=/usr/bin/chromium
export REPORTS_DIR=/home/TUUSUARIO/protego_web/reports
export LOPDP_DB_PATH=/home/TUUSUARIO/protego_web/jobs.sqlite3
export MAX_PAGES=12
export TRACKER_WAIT=6
export POLL_INTERVAL=3
export CLEANUP_AFTER_DAYS=7
export RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx
export RESEND_FROM_EMAIL="Auditor LOPDP <auditor@protego-consulting.com>"
export NOTIFY_TO_EMAIL=contacto@protego-consulting.com
/home/TUUSUARIO/.virtualenvs/protego-lopdp/bin/python /home/TUUSUARIO/protego_web/worker.py
```

   Reemplaza `RESEND_API_KEY`, `RESEND_FROM_EMAIL` y `NOTIFY_TO_EMAIL` con
   tus datos reales de Resend. `RESEND_FROM_EMAIL` debe ser una dirección de
   tu dominio ya verificado en Resend.

3. Guarda. PythonAnywhere lo deja corriendo indefinidamente y lo reinicia
   solo si se cae. El plan Developer incluye 1 tarea always-on — esta es la
   que la usa.
4. Revisa el log de la tarea (en la misma página de Tasks) para confirmar
   que arrancó bien. Deberías ver algo como:

```
Worker LOPDP iniciando...
Navegador headless listo.
```

Si en cambio ves un error de import o de Chromium, revisa que el
virtualenv tenga instaladas las dependencias (`pip list` dentro de él) y
que `CHROMIUM_PATH` apunte a `/usr/bin/chromium` (puedes confirmar que
existe con `ls -la /usr/bin/chromium` en una consola Bash).

---

## 4. Instalar el widget en tu sitio

1. Abre `widget/lopdp-widget-snippet.html` (incluido en este proyecto).
2. Copia todo el bloque, desde `<section id="lopdp-widget">` hasta el
   `</script>` final.
3. Pégalo en tu `index.html`, en el lugar donde quieras que aparezca el
   formulario (por ejemplo, antes del footer o como sección propia).
4. Dentro del bloque `<script>` que pegaste, busca esta línea:

```js
const API_BASE = "https://TUUSUARIO.pythonanywhere.com";
```

   y cámbiala por el dominio real de tu app (el mismo de la pestaña Web,
   paso 2). Si más adelante apuntas un dominio propio tipo
   `api.protego-consulting.com` a tu app de PythonAnywhere, usa ese en su
   lugar.

5. Sube el `index.html` actualizado a tu hosting estático (el mismo
   proceso que ya usas — Git, FTP, lo que sea).

No hace falta ningún archivo `.css` ni `.js` adicional: todo el estilo y la
lógica van dentro de ese mismo bloque, autocontenidos.

---

## 5. Probar el flujo completo en producción

1. Entra a `https://protego-consulting.com/` y busca el widget.
2. Ingresa la URL de un sitio real (el tuyo mismo sirve para la primera
   prueba) y dale "Analizar mi sitio".
3. Deberías ver el mensaje de "Analizando tu sitio..." con el spinner, y en
   1-2 minutos el mensaje de "Tu informe está listo" con la descarga
   disparándose sola.
4. Revisa la bandeja de `NOTIFY_TO_EMAIL` — debería llegar un correo con el
   mismo PDF adjunto, enviado por Resend.
5. Si algo falla, revisa en este orden:
   - **Log de la tarea always-on** (pestaña Tasks) — ahí aparece cualquier
     error del análisis o del envío de correo.
   - **Error log de la app web** (pestaña Web, sección "Log files") — ahí
     aparece cualquier error de la API (`/api/analyze`, `/api/status`).
   - La consola del navegador (F12) en la página con el widget — ahí
     aparecería un error de CORS si `ALLOWED_ORIGIN` no coincide
     exactamente con el dominio desde el que se sirve el widget (con o sin
     `www.`, con `https://`, sin `/` al final).

---

## 6. Mantenimiento

- **Limpieza automática**: el worker borra por sí solo los jobs y PDF de
  más de `CLEANUP_AFTER_DAYS` días (7 por defecto) cada vez que arranca un
  nuevo día de operación. No hace falta ninguna tarea programada aparte
  para esto.
- **Límite de uso diario**: cada IP puede pedir como máximo
  `RATE_LIMIT_PER_DAY` análisis cada 24 horas (5 por defecto). Ajusta esta
  variable en el archivo WSGI si quieres cambiarlo.
- **Espacio en disco**: cada PDF pesa entre 150 y 250 KB aprox. Con la
  limpieza automática a 7 días y el límite diario por IP, el uso de disco
  debería mantenerse bien por debajo de los 5 GB del plan Developer. Puedes
  revisarlo con `du -sh ~/protego_web/reports` en una consola.
- **Cuota de Resend**: el plan gratuito de Resend permite 3,000
  correos/mes (100/día). Si vas a recibir más de 100 análisis por día en
  algún momento, considera pasar a un plan pago de Resend.
- **Actualizar el código**: `cd ~/protego_web && git pull`, y si cambiaron
  las dependencias, `pip install -r requirements.txt` dentro del
  virtualenv. Luego, dale **Reload** a la app web (para que tome cambios
  de `app.py`) y reinicia la tarea always-on desde la pestaña Tasks (para
  que tome cambios de `worker.py`).

---

## 7. Nota de seguridad

`url_safety.py` incluye una variable `ALLOW_PRIVATE_HOSTS` pensada
**solo** para pruebas locales fuera de PythonAnywhere (te permite apuntar a
`localhost` o IPs privadas para probar el pipeline sin salir a internet).
**No la definas en producción** (ni en el WSGI ni en la tarea always-on):
si `ALLOW_PRIVATE_HOSTS=1` queda activa en PythonAnywhere, se desactiva la
protección contra SSRF y el formulario público podría usarse para hacer
que tu servidor le pegue a direcciones internas. Por defecto está apagada
(`0`) — simplemente no la toques al desplegar.
