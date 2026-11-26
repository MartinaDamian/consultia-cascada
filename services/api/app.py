"""API de Consultia (laboratorio).

Por defecto es VULNERABLE a fallos en cascada:
  - sin timeout hacia llm/stt
  - reintentos inmediatos
  - sin bulkhead ni circuit breaker

Las mitigaciones (P3) se activan por variables de entorno:
  LLM_TIMEOUT=2        segundos de timeout (vacio = sin timeout)
  RETRIES=2            reintentos inmediatos (con backoff si BACKOFF=1)
  BACKOFF=1            espera exponencial con jitter entre reintentos
  LLM_BULKHEAD=4       maximo de llamadas simultaneas a llm (0 = sin limite)
  CB_ENABLED=1         circuit breaker
  CB_FAILURES=3        fallos seguidos para abrir el circuito
  CB_RESET_SECONDS=10  tiempo hasta pasar a semiabierto
"""
import os
import random
import threading
import time

import psycopg2
import requests
from flask import Flask, jsonify

app = Flask(__name__)

LLM_URL = os.getenv("LLM_URL", "http://llm:5002/analyze")
STT_URL = os.getenv("STT_URL", "http://stt:5001/transcribe")
DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("DB_NAME", "consultia")
DB_USER = os.getenv("DB_USER", "consultia")


def _read_password():
    path = os.getenv("DB_PASSWORD_FILE")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return os.getenv("DB_PASSWORD", "cambiame")


def _float_env(name):
    value = os.getenv(name, "")
    return float(value) if value else None


LLM_TIMEOUT = _float_env("LLM_TIMEOUT")
RETRIES = int(os.getenv("RETRIES", "2"))
BACKOFF = os.getenv("BACKOFF", "0") == "1"
BULKHEAD = int(os.getenv("LLM_BULKHEAD", "0"))
CB_ENABLED = os.getenv("CB_ENABLED", "0") == "1"
CB_FAILURES = int(os.getenv("CB_FAILURES", "3"))
CB_RESET = float(os.getenv("CB_RESET_SECONDS", "10"))

bulkhead = threading.BoundedSemaphore(BULKHEAD) if BULKHEAD > 0 else None


class CircuitBreaker:
    def __init__(self):
        self.failures = 0
        self.opened_at = None
        self.lock = threading.Lock()

    def allow(self):
        with self.lock:
            if self.opened_at is None:
                return True
            if time.time() - self.opened_at >= CB_RESET:
                return True  # semiabierto: deja pasar un intento
            return False

    def success(self):
        with self.lock:
            if self.opened_at is not None:
                app.logger.warning("circuit breaker: CERRADO")
            self.failures = 0
            self.opened_at = None

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.failures >= CB_FAILURES and self.opened_at is None:
                self.opened_at = time.time()
                app.logger.warning("circuit breaker: ABIERTO")
            elif self.opened_at is not None:
                self.opened_at = time.time()


breaker = CircuitBreaker()


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=_read_password(), connect_timeout=3,
    )


def call_with_retries(url):
    last = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(url, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last = exc
            if attempt < RETRIES and BACKOFF:
                time.sleep(min(2 ** attempt * 0.2, 2) + random.uniform(0, 0.2))
    raise last


@app.get("/health")
def health():
    return jsonify(status="ok", service="api")


@app.get("/citas")
def citas():
    """Solo usa la base de datos: NO depende de llm ni de stt."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, paciente, motivo FROM citas ORDER BY id")
        rows = cur.fetchall()
    return jsonify(citas=[{"id": r[0], "paciente": r[1], "motivo": r[2]} for r in rows])


@app.get("/consulta")
def consulta():
    """Depende de stt y llm (el punto de fallo del laboratorio)."""
    if CB_ENABLED and not breaker.allow():
        return jsonify(error="servicio de analisis no disponible",
                       degraded=True), 503, {"Retry-After": "10"}

    if bulkhead is not None and not bulkhead.acquire(blocking=False):
        return jsonify(error="capacidad de analisis agotada",
                       degraded=True), 503, {"Retry-After": "2"}
    try:
        texto = call_with_retries(STT_URL)
        analisis = call_with_retries(LLM_URL)
        if CB_ENABLED:
            breaker.success()
        return jsonify(stt=texto, llm=analisis)
    except requests.RequestException:
        if CB_ENABLED:
            breaker.failure()
        return jsonify(error="dependencia no disponible", degraded=True), 503
    finally:
        if bulkhead is not None:
            bulkhead.release()
