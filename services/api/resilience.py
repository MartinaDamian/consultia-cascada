"""Patrones de resiliencia (Bloque P3) para la API de Consultia.

Implementa:
  1. Timeouts diferenciados de conexion y lectura para llamadas HTTP a stt y llm.
  2. Reintentos acotados con backoff exponencial y jitter, cancelados si el
     circuit breaker esta abierto (OPEN).
  3. Circuit Breaker basado en pybreaker con registro explicito de transiciones
     de estado: CLOSED, OPEN y HALF_OPEN.
  4. Bulkhead basado en semaforo no bloqueante para aislar llamadas a llm y
     proteger el pool de hilos de Gunicorn (preservando /citas y /health).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import math
import os
import random
import sys
import threading
import time
from typing import Any, Callable

import pybreaker
import requests


def configure_logger(name: str = "consultia.resilience") -> logging.Logger:
    """Configura un logger que escribe a stderr para visibilidad en Docker/Gunicorn."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = configure_logger()


def _float_env(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ResilienceConfig:
    """Parametros de resiliencia cargados por variables de entorno.

    Cuando las variables quedan en sus valores por defecto (escenario vulnerable),
    todos los mecanismos de proteccion permanecen desactivados.
    """

    http_connect_timeout: float | None = None
    stt_timeout: float | None = None
    llm_timeout: float | None = None
    retries: int = 2
    backoff_enabled: bool = False
    backoff_base: float = 0.2
    backoff_max: float = 2.0
    backoff_jitter: float = 0.2
    llm_bulkhead: int = 0
    bulkhead_retry_after: int = 2
    cb_enabled: bool = False
    cb_failures: int = 3
    cb_reset_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "ResilienceConfig":
        llm_timeout = _float_env("LLM_TIMEOUT")
        stt_timeout = _float_env("STT_TIMEOUT", default=llm_timeout)
        return cls(
            http_connect_timeout=_float_env("HTTP_CONNECT_TIMEOUT"),
            stt_timeout=stt_timeout,
            llm_timeout=llm_timeout,
            retries=max(0, _int_env("RETRIES", 2)),
            backoff_enabled=_bool_env("BACKOFF", False),
            backoff_base=max(0.0, _float_env("BACKOFF_BASE_SECONDS", 0.2) or 0.2),
            backoff_max=max(0.0, _float_env("BACKOFF_MAX_SECONDS", 2.0) or 2.0),
            backoff_jitter=max(0.0, _float_env("BACKOFF_JITTER_SECONDS", 0.2) or 0.2),
            llm_bulkhead=max(0, _int_env("LLM_BULKHEAD", 0)),
            bulkhead_retry_after=max(1, _int_env("BULKHEAD_RETRY_AFTER", 2)),
            cb_enabled=_bool_env("CB_ENABLED", False),
            cb_failures=max(1, _int_env("CB_FAILURES", 3)),
            cb_reset_seconds=max(1.0, _float_env("CB_RESET_SECONDS", 10.0) or 10.0),
        )


def build_timeout(
    connect_timeout: float | None,
    read_timeout: float | None,
) -> float | tuple[float, float | None] | None:
    """Construye el argumento timeout para requests: (connect, read) o None."""
    if connect_timeout is None and read_timeout is None:
        return None
    if connect_timeout is not None and read_timeout is not None:
        return (connect_timeout, read_timeout)
    if read_timeout is not None:
        return (read_timeout, read_timeout)
    return (connect_timeout, None)


def compute_backoff(
    attempt: int,
    base: float = 0.2,
    max_delay: float = 2.0,
    jitter: float = 0.2,
) -> float:
    """Calcula espera exponencial acotada con jitter uniforme."""
    exp_delay = min((2 ** attempt) * base, max_delay)
    return exp_delay + random.uniform(0.0, jitter)


class BulkheadFullError(Exception):
    """Se lanza cuando no quedan permisos disponibles en el bulkhead."""


class Bulkhead:
    """Aislamiento de concurrencia no bloqueante mediante BoundedSemaphore."""

    def __init__(self, max_concurrent: int, name: str = "llm") -> None:
        self.max_concurrent = max_concurrent
        self.name = name
        self._sem = threading.BoundedSemaphore(max_concurrent) if max_concurrent > 0 else None

    @property
    def enabled(self) -> bool:
        return self._sem is not None

    @contextmanager
    def slot(self):
        if self._sem is None:
            yield
            return
        if not self._sem.acquire(blocking=False):
            logger.warning(
                "[bulkhead:%s] capacidad agotada (limite=%d); rechazando solicitud rapido",
                self.name,
                self.max_concurrent,
            )
            raise BulkheadFullError(f"Bulkhead '{self.name}' saturado")
        try:
            yield
        finally:
            self._sem.release()


def _normalize_state(state_name: str) -> str:
    mapping = {
        pybreaker.STATE_CLOSED: "CLOSED",
        pybreaker.STATE_OPEN: "OPEN",
        pybreaker.STATE_HALF_OPEN: "HALF_OPEN",
    }
    return mapping.get(state_name, state_name.upper().replace("-", "_"))


class ResilienceBreakerListener(pybreaker.CircuitBreakerListener):
    """Registra transiciones de estado del circuit breaker con formato claro."""

    def __init__(self, log: logging.Logger) -> None:
        self._log = log
        self._lock = threading.Lock()
        self._last_opened_at: float | None = None

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: Any, new_state: Any) -> None:
        old_name = _normalize_state(old_state.name)
        new_name = _normalize_state(new_state.name)
        with self._lock:
            if new_name == "OPEN":
                self._last_opened_at = time.monotonic()
            elif new_name in {"CLOSED", "HALF_OPEN"}:
                self._last_opened_at = None

        self._log.warning(
            "[circuit_breaker:%s] transicion %s -> %s (fallos=%d/%d, reset_timeout=%ss)",
            cb.name,
            old_name,
            new_name,
            cb.fail_counter,
            cb.fail_max,
            cb.reset_timeout,
        )

    def last_opened_at(self) -> float | None:
        with self._lock:
            return self._last_opened_at


class LLMCircuitBreaker:
    """Envoltorio thread-safe sobre pybreaker para proteger llamadas a llm."""

    def __init__(
        self,
        enabled: bool,
        fail_max: int,
        reset_timeout: float,
        name: str = "llm",
    ) -> None:
        self.enabled = enabled
        self.reset_timeout = reset_timeout
        self.name = name
        self._listener = ResilienceBreakerListener(logger)
        self._breaker = (
            pybreaker.CircuitBreaker(
                fail_max=fail_max,
                reset_timeout=reset_timeout,
                listeners=[self._listener],
                name=name,
            )
            if enabled
            else None
        )

    @property
    def state_name(self) -> str:
        if self._breaker is None:
            return "DISABLED"
        return _normalize_state(self._breaker.current_state)

    def is_open(self) -> bool:
        return self._breaker is not None and self._breaker.current_state == pybreaker.STATE_OPEN

    def is_blocking(self) -> bool:
        """Indica si el circuito esta OPEN y aun dentro de la ventana de enfriamiento.

        Cuando expira reset_timeout devuelve False para permitir que pybreaker
        ejecute la transicion OPEN -> HALF_OPEN en la siguiente llamada.
        """
        if not self.is_open():
            return False
        opened_at = self._listener.last_opened_at()
        if opened_at is None:
            return False
        return (time.monotonic() - opened_at) < self.reset_timeout

    def retry_after_seconds(self) -> int:
        opened_at = self._listener.last_opened_at()
        if opened_at is None:
            return max(1, int(math.ceil(self.reset_timeout)))
        remaining = self.reset_timeout - (time.monotonic() - opened_at)
        return max(1, int(math.ceil(remaining)))

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._breaker is None:
            return func(*args, **kwargs)
        # Se usa calling() (context manager) en lugar de call() porque pybreaker.call()
        # retiene su RLock interno durante toda la llamada de red, serializando los hilos.
        # Con calling() la verificacion/transicion de estado es segura sin bloquear I/O concurrente.
        with self._breaker.calling():
            return func(*args, **kwargs)


def _http_get_json(
    url: str,
    timeout: float | tuple[float, float | None] | None,
    verify: str | bool | None,
    cert: tuple[str, str] | None,
) -> Any:
    request_kwargs: dict[str, Any] = {"timeout": timeout}
    if verify is not None:
        request_kwargs["verify"] = verify
    if cert is not None:
        request_kwargs["cert"] = cert
    response = requests.get(url, **request_kwargs)
    response.raise_for_status()
    return response.json()


def call_with_retries(
    url: str,
    timeout: float | tuple[float, float | None] | None,
    config: ResilienceConfig,
    breaker: LLMCircuitBreaker | None = None,
    service_name: str = "upstream",
    verify: str | bool | None = None,
    cert: tuple[str, str] | None = None,
) -> Any:
    """Invoca un servicio HTTP con reintentos, backoff+jitter y circuit breaker.

    Garantia P3: nunca reintenta si el circuit breaker esta OPEN o si la
    invocacion dispara la transicion hacia OPEN.
    """
    last_exc: Exception | None = None
    for attempt in range(config.retries + 1):
        if breaker is not None and breaker.is_blocking():
            raise pybreaker.CircuitBreakerError(
                f"Circuit breaker '{breaker.name}' OPEN; reintento cancelado"
            )

        try:
            if breaker is not None and breaker.enabled:
                return breaker.call(_http_get_json, url, timeout, verify, cert)
            return _http_get_json(url, timeout, verify, cert)
        except pybreaker.CircuitBreakerError:
            # El circuito ya estaba OPEN o se acaba de abrir (CLOSED/HALF_OPEN -> OPEN):
            # abortar inmediatamente sin reintentar.
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if breaker is not None and breaker.is_open():
                raise pybreaker.CircuitBreakerError(
                    f"Circuit breaker '{breaker.name}' paso a OPEN; abortando reintentos"
                ) from exc

            if attempt < config.retries:
                if config.backoff_enabled:
                    delay = compute_backoff(
                        attempt=attempt,
                        base=config.backoff_base,
                        max_delay=config.backoff_max,
                        jitter=config.backoff_jitter,
                    )
                    logger.warning(
                        "[retry:%s] fallo intento %d/%d (%s); reintentando en %.2fs",
                        service_name,
                        attempt + 1,
                        config.retries + 1,
                        type(exc).__name__,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.debug(
                        "[retry:%s] fallo intento %d/%d (%s); reintento inmediato",
                        service_name,
                        attempt + 1,
                        config.retries + 1,
                        type(exc).__name__,
                    )

    assert last_exc is not None
    raise last_exc


def log_resilience_config(config: ResilienceConfig) -> None:
    """Imprime la configuracion activa al arrancar para auditoria en logs."""
    mode = "HARDENED" if (config.cb_enabled or config.llm_bulkhead > 0 or config.backoff_enabled) else "VULNERABLE"
    logger.info(
        "[startup] modo=%s connect_timeout=%s stt_timeout=%s llm_timeout=%s "
        "retries=%d backoff=%s bulkhead=%d cb_enabled=%s cb_failures=%d cb_reset=%ss",
        mode,
        config.http_connect_timeout,
        config.stt_timeout,
        config.llm_timeout,
        config.retries,
        config.backoff_enabled,
        config.llm_bulkhead,
        config.cb_enabled,
        config.cb_failures,
        config.cb_reset_seconds,
    )
