"""Calcula metricas del escenario: disponibilidad, p50/p95, 429, 5xx/timeout y recuperacion."""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def pct(values, q):
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def run(label, attack_end):
    base = f"/evidencias/{label}"
    with open(f"{base}/mediciones.csv") as f:
        data = list(csv.DictReader(f))
    probes = [r for r in data if r["tipo"] == "sonda"]

    lines = [
        f"# Resumen del escenario: {label}",
        "",
        "| Fase | Endpoint | Peticiones | Disp. (200) | 429 (rate limit) | 5xx / timeout | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for fase in ("baseline", "carga", "recuperacion"):
        for ep in ("/health", "/citas", "/consulta"):
            sel = [r for r in probes if r["fase"] == fase and r["endpoint"] == ep]
            if not sel:
                continue
            ok = [r for r in sel if r["status"] == "200"]
            rl = [r for r in sel if r["status"] == "429"]
            bad = [r for r in sel if r["status"] == "0" or r["status"].startswith("5")]
            lat = [float(r["latencia_ms"]) for r in sel]
            lines.append(
                f"| {fase} | {ep} | {len(sel)} | {100 * len(ok) / len(sel):.0f} % | "
                f"{len(rl)} | {len(bad)} | {pct(lat, 0.5):.0f} | {pct(lat, 0.95):.0f} |"
            )

    # Tiempo de recuperacion: primeros 3 OK seguidos de /citas tras terminar la carga
    after = sorted(
        (r for r in probes if r["endpoint"] == "/citas" and float(r["t_seg"]) >= attack_end),
        key=lambda r: float(r["t_seg"]),
    )
    rec, streak = None, 0
    for r in after:
        streak = streak + 1 if r["status"] == "200" else 0
        if streak == 3:
            rec = float(r["t_seg"]) - attack_end
            break
    lines += [
        "",
        "**Tiempo de recuperacion de /citas tras la carga:** "
        + (f"{rec:.0f} s" if rec is not None else "no se recupero en la ventana medida"),
    ]

    with open(f"{base}/resumen.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    plt.figure(figsize=(9, 4))
    for ep, color in (("/citas", "tab:blue"), ("/consulta", "tab:red")):
        pts = [(float(r["t_seg"]), float(r["latencia_ms"])) for r in probes if r["endpoint"] == ep]
        if pts:
            plt.plot(*zip(*pts), label=f"{ep} (latencia)", color=color, marker=".")
    plt.axvline(attack_end, color="gray", linestyle="--", label="fin de la carga")
    plt.xlabel("tiempo (s)")
    plt.ylabel("latencia (ms)")
    plt.title(f"Latencia de sondas: {label}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{base}/latencia.png", dpi=120)


if __name__ == "__main__":
    run(sys.argv[1], float(sys.argv[2]))
