"""LLM simulado: tarda LATENCY_MS por peticion y solo atiende MAX_CONCURRENCY a la vez.
Las demas esperan en cola, que es lo que provoca la saturacion."""
import os
import threading
import time

from flask import Flask, jsonify

app = Flask(__name__)
LATENCY_MS = int(os.getenv("LATENCY_MS", "2000"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "2"))
slots = threading.BoundedSemaphore(MAX_CONCURRENCY)


@app.get("/health")
def health():
    return jsonify(status="ok", service="llm")


@app.post("/analyze")
@app.get("/analyze")
def analyze():
    with slots:
        time.sleep(LATENCY_MS / 1000)
    return jsonify(service="llm", intent="agendar_cita", latency_ms=LATENCY_MS)
