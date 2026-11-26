"""API de Consultia (laboratorio).

Por defecto es VULNERABLE a fallos en cascada:
  - sin timeout hacia llm/stt
  - reintentos inmediatos
  - sin bulkhead ni circuit breaker

Las mitigaciones (P3) se activan por variables de entorno (ver resilience.py):
  HTTP_CONNECT_TIMEOUT=1.0   segundos de timeout de conexion (vacio = sin limite)
  STT_TIMEOUT=1.0            segundos de timeout de lectura hacia stt
  LLM_TIMEOUT=2.5            segundos de timeout de lectura hacia llm
  RETRIES=1                  reintentos maximos (con backoff si BACKOFF=1)
  BACKOFF=1                  espera exponencial con jitter entre reintentos
  LLM_BULKHEAD=4             maximo de llamadas simultaneas a /consulta -> llm (0 = sin limite)
  BULKHEAD_RETRY_AFTER=2     segundos sugeridos en Retry-After cuando el bulkhead se llena
  CB_ENABLED=1               circuit breaker con pybreaker
  CB_FAILURES=3              fallos seguidos para abrir el circuito (CLOSED -> OPEN)
  CB_RESET_SECONDS=10        tiempo hasta pasar a semiabierto (OPEN -> HALF_OPEN)
"""
import os

import psycopg2
import pybreaker
import requests
from flask import Flask, jsonify

from resilience import (
    Bulkhead,
    BulkheadFullError,
    LLMCircuitBreaker,
    ResilienceConfig,
    build_timeout,
    call_with_retries,
    log_resilience_config,
)

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


config = ResilienceConfig.from_env()
STT_HTTP_TIMEOUT = build_timeout(config.http_connect_timeout, config.stt_timeout)
LLM_HTTP_TIMEOUT = build_timeout(config.http_connect_timeout, config.llm_timeout)
llm_bulkhead = Bulkhead(config.llm_bulkhead, name="llm")
llm_breaker = LLMCircuitBreaker(
    enabled=config.cb_enabled,
    fail_max=config.cb_failures,
    reset_timeout=config.cb_reset_seconds,
    name="llm",
)
log_resilience_config(config)


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=_read_password(), connect_timeout=3,
    )


def _degraded_response(reason, error, retry_after, stt_data=None):
    payload = {
        "status": "degraded",
        "degraded": True,
        "reason": reason,
        "error": error,
        "retry_after_seconds": retry_after,
    }
    if stt_data is not None:
        payload["stt"] = stt_data
        payload["llm"] = None
    return jsonify(payload), 503, {"Retry-After": str(retry_after)}


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
    # 1. Fail-fast si el circuit breaker esta OPEN dentro de su ventana de enfriamiento
    if llm_breaker.is_blocking():
        return _degraded_response(
            reason="circuit_breaker_open",
            error="Servicio de analisis temporalmente no disponible (circuit breaker abierto)",
            retry_after=llm_breaker.retry_after_seconds(),
        )

    # 2. Bulkhead: limita concurrencia de /consulta para dejar hilos libres a /citas y /health
    try:
        with llm_bulkhead.slot():
            try:
                texto = call_with_retries(
                    url=STT_URL,
                    timeout=STT_HTTP_TIMEOUT,
                    config=config,
                    breaker=None,
                    service_name="stt",
                )
            except requests.RequestException:
                return _degraded_response(
                    reason="stt_unavailable",
                    error="Servicio de transcripcion (stt) no disponible",
                    retry_after=config.bulkhead_retry_after,
                )

            try:
                analisis = call_with_retries(
                    url=LLM_URL,
                    timeout=LLM_HTTP_TIMEOUT,
                    config=config,
                    breaker=llm_breaker if config.cb_enabled else None,
                    service_name="llm",
                )
            except pybreaker.CircuitBreakerError:
                return _degraded_response(
                    reason="circuit_breaker_open",
                    error="Servicio de analisis temporalmente no disponible (circuit breaker abierto)",
                    retry_after=llm_breaker.retry_after_seconds(),
                    stt_data=texto,
                )
            except requests.RequestException:
                return _degraded_response(
                    reason="llm_unavailable",
                    error="Analisis IA (llm) no disponible; transcripcion entregada en modo degradado",
                    retry_after=config.bulkhead_retry_after,
                    stt_data=texto,
                )

            return jsonify(stt=texto, llm=analisis)
    except BulkheadFullError:
        return _degraded_response(
            reason="bulkhead_full",
            error="Capacidad de analisis temporalmente agotada; intente nuevamente",
            retry_after=config.bulkhead_retry_after,
        )
