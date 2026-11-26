"""Escenario controlado de saturacion (SOLO contra el laboratorio local).

Fases: baseline -> carga -> recuperacion. Durante todo el tiempo sondea
/health, /citas (no depende de llm) y /consulta (depende de llm) cada segundo.

Uso: python scenario.py --label antes [--baseline 10 --attack 40 --recovery 30 --workers 40]
"""
import argparse
import csv
import os
import threading
import time

import requests

p = argparse.ArgumentParser()
p.add_argument("--label", required=True, help="antes | despues")
p.add_argument("--target", default=os.getenv("TARGET", "http://gateway:8080"))
p.add_argument("--baseline", type=int, default=10)
p.add_argument("--attack", type=int, default=40)
p.add_argument("--recovery", type=int, default=30)
p.add_argument("--workers", type=int, default=40)
a = p.parse_args()

# Salvaguarda: este script solo debe apuntar al laboratorio.
if not a.target.startswith(("http://gateway", "http://localhost", "http://127.0.0.1")):
    raise SystemExit("Objetivo no permitido: solo el laboratorio local.")

out_dir = f"/evidencias/{a.label}"
os.makedirs(out_dir, exist_ok=True)
rows, lock = [], threading.Lock()
stop = threading.Event()
t0 = time.time()
attack_start = a.baseline
attack_end = a.baseline + a.attack
total = a.baseline + a.attack + a.recovery


def phase(t):
    if t < attack_start:
        return "baseline"
    return "carga" if t < attack_end else "recuperacion"


def record(endpoint, status, latency_ms, kind):
    t = time.time() - t0
    with lock:
        rows.append((round(t, 2), phase(t), kind, endpoint, status, round(latency_ms, 1)))


def request(endpoint, timeout):
    s = time.time()
    try:
        r = requests.get(a.target + endpoint, timeout=timeout)
        return r.status_code, (time.time() - s) * 1000
    except requests.RequestException:
        return 0, (time.time() - s) * 1000  # 0 = timeout / error de conexion


def probe(endpoint):
    while not stop.is_set():
        status, ms = request(endpoint, timeout=5)
        record(endpoint, status, ms, "sonda")
        time.sleep(1)


def load_worker():
    while not stop.is_set() and (time.time() - t0) < attack_end:
        if (time.time() - t0) >= attack_start:
            status, ms = request("/consulta", timeout=30)
            record("/consulta", status, ms, "carga")
        else:
            time.sleep(0.2)


threads = [threading.Thread(target=probe, args=(e,), daemon=True)
           for e in ("/health", "/citas", "/consulta")]
threads += [threading.Thread(target=load_worker, daemon=True) for _ in range(a.workers)]
for t in threads:
    t.start()

print(f"[{a.label}] baseline {a.baseline}s, carga {a.attack}s ({a.workers} hilos), recuperacion {a.recovery}s")
while time.time() - t0 < total:
    time.sleep(1)
stop.set()
time.sleep(1)

path = f"{out_dir}/mediciones.csv"
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t_seg", "fase", "tipo", "endpoint", "status", "latencia_ms"])
    w.writerows(sorted(rows))
print("Guardado:", path)

import analyze  # noqa: E402
analyze.run(a.label, attack_end)
