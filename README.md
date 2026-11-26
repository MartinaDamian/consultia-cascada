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

## Mitigaciones de resiliencia (P3)

Implementadas de forma modular en `services/api/resilience.py`, `services/api/app.py`, `services/gateway/default.hardened.conf` y activables por variables de entorno en `docker-compose.hardened.yml`:

- **Timeouts diferenciados (conexión y lectura):** llamadas HTTP a `stt` (`1.0s` / `1.0s`) y `llm` (`1.0s` / `2.5s`) para que las solicitudes encoladas fallen rápido sin romper el baseline sano (~2.1 s).
- **Reintentos con backoff exponencial y jitter:** máximo 1 reintento con espera exponencial más jitter aleatorio; los reintentos se cancelan automáticamente si el circuit breaker está en `OPEN`.
- **Circuit Breaker (`pybreaker`):** protege las llamadas a `llm` usando `calling()` (sin serializar concurrencia por lock) y registra en logs de `api` las transiciones `CLOSED -> OPEN`, `OPEN -> HALF_OPEN`, `HALF_OPEN -> OPEN` y `HALF_OPEN -> CLOSED`.
- **Bulkhead:** semáforo no bloqueante (`LLM_BULKHEAD=4`) sobre el pool de 8 hilos de Gunicorn, asegurando al menos 4 hilos siempre disponibles para `/citas` y `/health`.
- **Degradación elegante en `/consulta`:** responde `503 Service Unavailable` con cabecera `Retry-After` y cuerpo JSON estructurado (`degraded: true`, `reason`, y transcripción parcial `stt` cuando falla `llm`).
- **Load shedding en Nginx (`default.hardened.conf`):** aplica `limit_req` (`5r/s`, `burst=6 nodelay`) y `limit_conn` (`6` conexiones simultáneas por IP) exclusivamente sobre `/consulta`, devolviendo `429 Too Many Requests` + `Retry-After: 2` sin limitar `/citas` ni `/health`.

| Variable de entorno (`api`) | Modo vulnerable (`docker-compose.yml`) | Modo endurecido (`docker-compose.hardened.yml`) |
|---|---|---|
| `HTTP_CONNECT_TIMEOUT` | *(sin límite)* | `1.0` |
| `STT_TIMEOUT` / `LLM_TIMEOUT` | `""` *(sin límite)* | `1.0` / `2.5` |
| `RETRIES` / `BACKOFF` | `2` / `0` *(inmediatos)* | `1` / `1` *(exponencial + jitter)* |
| `LLM_BULKHEAD` / `BULKHEAD_RETRY_AFTER` | `0` *(desactivado)* | `4` / `2` |
| `CB_ENABLED` / `CB_FAILURES` / `CB_RESET_SECONDS` | `0` *(desactivado)* | `1` / `3` / `10` |

## Estructura del repositorio

```text
consultia-cascada/
├── docker-compose.yml            # Escenario base vulnerable (P1)
├── docker-compose.hardened.yml   # Override con mitigaciones (P3 + P4)
├── services/
│   ├── api/                      # Backend + módulo de resiliencia resilience.py (P1, P3)
│   ├── db/                       # Script init.sql de PostgreSQL (P1)
│   ├── gateway/                  # Config Nginx base y endurecida con limit_req + limit_conn (P1, P3, P4)
│   ├── llm/                      # Servicio simulado con cuello de botella (P1)
│   └── stt/                      # Servicio simulado de transcripción (P1)
├── tester/                       # Contenedor con nmap, scenario.py y analyze.py (P2)
├── security/                     # Espacio reservado para CA, mTLS y rotación de secretos (P4)
├── evidencias/
│   ├── antes/                    # CSV, resumen y gráfico del sistema vulnerable
│   └── despues/                  # CSV, resumen y gráfico del sistema endurecido
└── scripts/                      # Automatización de despliegue y pruebas (PS1 / SH)
```

## Estado de integración (P3 y P4)

- **P3 (Resiliencia — integrado):** Timeouts de conexión/lectura, reintentos con backoff exponencial y jitter, circuit breaker con `pybreaker` y logs de transición (`CLOSED`/`OPEN`/`HALF_OPEN`), bulkhead en `api`, degradación elegante (`503` + `Retry-After`) y load shedding en Nginx (`limit_req` + `limit_conn` → `429`).
- **P4 (Zero Trust y secretos — pendiente):** Implementar en `security/` la CA propia con `openssl`, mTLS (`gateway → api → llm/stt`), TLS en Postgres, `docker secrets` con script de rotación y endurecimiento de contenedores (`user`, `read_only`, `cap_drop: ALL`) en `docker-compose.hardened.yml`.

