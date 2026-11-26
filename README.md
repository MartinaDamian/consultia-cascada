# Consultia — Laboratorio de Fallos en Cascada

Simulación controlada y reproducible de **fallos en cascada por saturación de dependencias** en un sistema distribuido de microservicios (proyecto integrador **Consultia**), diseñada para ejecutarse exclusivamente en un entorno Docker local y aislado.

## Arquitectura del laboratorio

```text
tester (red: frontend)
   │
   ▼
gateway (nginx :8080)  [redes: frontend, backend]
   │
   ▼
api (flask/gunicorn :5000, 8 hilos)  [red: backend (internal)]
   ├──► stt (:5001)  /transcribe   (latencia baja fija ~100 ms)
   ├──► llm (:5002)  /analyze      (punto de fallo: LATENCY_MS=2000, MAX_CONCURRENCY=2)
   └──► db  (:5432)  PostgreSQL    (tabla citas; usado por /citas)
```

### Contrato técnico de endpoints

| Servicio | Puerto interno | Endpoints | Dependencias |
|---|---|---|---|
| `gateway` | `8080` (expuesto en host) | Proxy hacia `api` | `api` |
| `api` | `5000` | `/health`, `/citas`, `/consulta` | `/citas` solo usa `db`; `/consulta` llama a `stt` y `llm` |
| `stt` | `5001` | `/health`, `/transcribe` | Ninguna |
| `llm` | `5002` | `/health`, `/analyze` | Ninguna |
| `db` | `5432` | PostgreSQL (`consultia`) | Ninguna |

## Requisitos

- Docker Desktop (Docker Compose v2)
- PowerShell (Windows) o Bash (Linux/macOS)

## Uso rápido

### 1. Desplegar el escenario base (vulnerable)

En Windows (PowerShell):
```powershell
.\scripts\up.ps1 vulnerable
```

En Linux / macOS:
```bash
bash scripts/up.sh vulnerable
```

Verificar servicios activos:
```powershell
docker compose ps
curl http://localhost:8080/health
curl http://localhost:8080/citas
curl http://localhost:8080/consulta
```

### 2. Reconocimiento (P2)

Ejecutar `nmap` desde el contenedor `tester` dentro de la red `frontend`:
```powershell
docker compose --profile tools exec tester nmap -sV -p 8080,5000,5001,5002,5432 gateway api llm stt db
```
*(Solo `gateway:8080` es alcanzable desde `frontend`; la red `backend` está aislada con `internal: true`.)*

### 3. Ejecutar el escenario de saturación (antes de mitigar)

```powershell
.\scripts\run_scenario.ps1 antes
```
Genera automáticamente en `evidencias/antes/`:
- `mediciones.csv` (sondas y carga segundo a segundo)
- `resumen.md` (tabla de disponibilidad, 429, 5xx/timeout, p50, p95 y tiempo de recuperación)
- `latencia.png` (gráfico comparativo de `/citas` vs `/consulta`)

### 4. Desplegar el escenario endurecido y reejecutar (después)

```powershell
.\scripts\up.ps1 hardened
.\scripts\run_scenario.ps1 despues
```
Genera las evidencias comparables en `evidencias/despues/` usando exactamente los mismos parámetros (`baseline=10s`, `attack=40s`, `recovery=30s`, `workers=40`).

### 5. Ver logs y limpiar el entorno

```powershell
docker compose logs --tail=50 gateway api
docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml down -v
```

## Estructura del repositorio

```text
consultia-cascada/
├── docker-compose.yml            # Escenario base vulnerable (P1)
├── docker-compose.hardened.yml   # Override con mitigaciones (P3 + P4)
├── services/
│   ├── api/                      # Backend vulnerable / mitigaciones por env (P1, P3)
│   ├── db/                       # Script init.sql de PostgreSQL (P1)
│   ├── gateway/                  # Config Nginx base y endurecida con rate limit (P1, P3, P4)
│   ├── llm/                      # Servicio simulado con cuello de botella (P1)
│   └── stt/                      # Servicio simulado de transcripción (P1)
├── tester/                       # Contenedor con nmap, scenario.py y analyze.py (P2)
├── security/                     # Espacio reservado para CA, mTLS y rotación de secretos (P4)
├── evidencias/
│   ├── antes/                    # CSV, resumen y gráfico del sistema vulnerable
│   └── despues/                  # CSV, resumen y gráfico del sistema endurecido
└── scripts/                      # Automatización de despliegue y pruebas (PS1 / SH)
```

## Pendiente por integrar (bloques de P3 y P4)

- **P3 (Resiliencia):** Ya están preparados los ganchos en `services/api/app.py` y `docker-compose.hardened.yml` (timeout, backoff, bulkhead, circuit breaker y `limit_req` en Nginx) para ajustar umbrales y documentar logs de transición del breaker.
- **P4 (Zero Trust y secretos):** Implementar en `security/` la CA propia con `openssl`, mTLS (`gateway → api → llm/stt`), TLS en Postgres, `docker secrets` con script de rotación y endurecimiento de contenedores (`user`, `read_only`, `cap_drop: ALL`) en `docker-compose.hardened.yml`.
