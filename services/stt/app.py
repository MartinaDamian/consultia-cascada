"""STT simulado: latencia baja y fija."""
import time

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", service="stt")


@app.post("/transcribe")
@app.get("/transcribe")
def transcribe():
    time.sleep(0.1)
    return jsonify(service="stt", text="quiero agendar una cita")
