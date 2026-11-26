# Bitácora de Validación Cruzada (Uso Crítico de IA) — Persona 1
**Integrante:** Martina Damián  
**Rol:** Persona 1 — Arquitecta del entorno base, topología de red y contrato técnico  
**Materia:** Sistemas Distribuidos — Universidad de Las Américas  

---

### Concepto Nro. 1
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 1 |
| **Tema** | Diseño de una arquitectura reproducible para provocar fallos en cascada por agotamiento de hilos |
| **Idea inicial del equipo** | Inicialmente pensábamos simular la caída apagando un contenedor (`docker stop llm`) o introduciendo un retardo aleatorio en un solo endpoint para observar errores en la API, sin diferenciar rutas con dependencias independientes. |
| **Prompt utilizado en la IA** | "Diseña la lógica técnica, contrato de endpoints y esqueleto Docker Compose de un laboratorio aislado para demostrar fallos en cascada en Consultia (`gateway`, `api`, `stt`, `llm`, `db`), donde la saturación de un servicio dependiente arrastre a funciones que no dependen de él." (Antigravity — Claude Sonnet / Gemini) |
| **Aporte generado por la IA** | "Para evidenciar una cascada real y no solo una caída aislada, `api` debe exponer dos rutas con dependencias separadas: `/citas` (que solo consulta PostgreSQL `db`) y `/consulta` (que invoca síncronamente a `stt` y `llm`). El cuello de botella se modela en `llm` mediante un `threading.BoundedSemaphore(MAX_CONCURRENCY=2)` y una latencia controlada (`LATENCY_MS=2000`), mientras `api` ejecuta Gunicorn con un pool finito de hilos (`-w 1 --threads 8`), sin timeouts y con reintentos inmediatos en su estado vulnerable. Bajo carga sostenida en `/consulta`, los 8 hilos quedan bloqueados esperando a `llm` y terminan indisponiendo también `/citas` y `/health`." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se acepta e implementa en `services/api/app.py`, `services/llm/app.py`, `services/stt/app.py` y `services/db/init.sql`. La propuesta fue contrastada con Beyer et al. (2016, cap. 22 "Addressing Cascading Failures") y Nygard (2018), quienes establecen que un fallo en cascada ocurre cuando el agotamiento de un recurso compartido (como el pool de hilos de un servidor de aplicaciones) propaga la falla de un servicio dependiente hacia operaciones no relacionadas. Este diseño permitió que P2 demostrara posteriormente la caída de `/citas` del 100 % al 0 % de disponibilidad durante la sobrecarga de `llm`. |
| **Referencias** | • Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site Reliability Engineering: How Google Runs Production Systems*. O'Reilly Media.<br>• Nygard, M. T. (2018). *Release It!: Design and Deploy Production-Ready Software* (2.ª ed.). Pragmatic Bookshelf.<br>• Newman, S. (2021). *Building Microservices: Designing Fine-Grained Systems* (2.ª ed.). O'Reilly Media. |

---

### Concepto Nro. 2
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 2 |
| **Tema** | Condición de carrera en el arranque de PostgreSQL (`depends_on` simple vs. `healthcheck` con `pg_isready`) |
| **Idea inicial del equipo** | Al generar el `docker-compose.yml` inicial, asumimos que declarar `depends_on: [db, llm, stt]` en el servicio `api` garantizaba que PostgreSQL ya estuviera listo y con el esquema `init.sql` cargado antes de recibir las primeras peticiones en `/citas`. |
| **Prompt utilizado en la IA** | "Genera el `docker-compose.yml` del entorno base vulnerable conectando `gateway`, `api`, `llm`, `stt` y `db` (PostgreSQL 16 con `init.sql`) sobre redes separadas `frontend` y `backend`." (Antigravity — Claude Sonnet / Gemini) |
| **Aporte generado por la IA** | En la primera generación del archivo `docker-compose.yml`, la IA definió únicamente `depends_on: [db, llm, stt]` en `api` y omitió por completo un `healthcheck` para el contenedor `db`. Al revisar críticamente el despliegue, se detectó que en Docker Compose una lista simple en `depends_on` únicamente espera a que el contenedor arranque, no a que el motor de base de datos finalice la inicialización del clúster ni ejecute `/docker-entrypoint-initdb.d/init.sql`, dejando expuesta una condición de carrera (*race condition*) en los primeros segundos tras `docker compose up -d`. |
| **Decisión** | Aceptado con correcciones (defecto detectado y corregido) |
| **Justificación crítica vs. Bibliografía** | Se corrigió `docker-compose.yml` tras contrastar con la documentación oficial de Docker Compose (*Control startup and shutdown order in Compose*) y la utilidad oficial `pg_isready` de PostgreSQL 16. Se agregó un `healthcheck` en `db` (`pg_isready -U consultia -d consultia`, intervalo de 3 s, 15 reintentos) y se reescribió `api.depends_on.db` con `condition: service_healthy`. La validez del manifiesto se comprobó con `docker compose config --quiet` antes del commit inicial (`77d241d`), garantizando un despliegue reproducible sin fallos de arranque para el resto del equipo. |
| **Referencias** | • Docker Documentation. (2024). *Control startup and shutdown order in Compose*. Docker Inc. https://docs.docker.com/compose/how-tos/startup-order/<br>• PostgreSQL Global Development Group. (2024). *PostgreSQL 16 Documentation: pg_isready*. https://www.postgresql.org/docs/16/app-pg-isready.html |

---

### Concepto Nro. 3
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 3 |
| **Tema** | Inconsistencia de perfiles y archivos *override* en los scripts automatizados de despliegue (`up.ps1` / `up.sh`) |
| **Idea inicial del equipo** | Queríamos automatizar el cambio entre modo `vulnerable` y modo `hardened` en un solo comando multiplataforma (PowerShell y Bash) para que cualquier compañero o evaluador pudiera reproducir el laboratorio sin escribir comandos largos de Compose. |
| **Prompt utilizado en la IA** | "Crea scripts `scripts/up.ps1` y `scripts/up.sh` que limpien el entorno previo y levanten tanto los microservicios en modo `vulnerable` o `hardened` como el contenedor auxiliar `tester` (definido en el perfil `tools`)." (Antigravity — Claude Sonnet / Gemini) |
| **Aporte generado por la IA** | En la primera versión generada por la IA, el script levantaba el modo endurecido mediante `docker compose -f docker-compose.yml -f docker-compose.hardened.yml up -d --build` y, en una segunda línea separada, ejecutaba `docker compose --profile tools up -d --build tester` **sin pasar** `-f docker-compose.hardened.yml`. Durante la revisión técnica se identificó que invocar Compose en el segundo paso únicamente con el archivo base genera una vista inconsistente del proyecto (descartando redes, secretos u *overrides* definidos en el archivo endurecido, como los que luego añadiría P4). |
| **Decisión** | Rechazado y corregido |
| **Justificación crítica vs. Bibliografía** | Se rechazó la ejecución dividida propuesta por la IA y se refactorizaron `scripts/up.ps1` y `scripts/up.sh` para usar una única invocación consistente con `--profile tools` junto a los archivos `-f` correspondientes (tanto en `down -v` como en `up -d --build`). Se contrastó con la documentación oficial de Docker Compose sobre combinación de archivos (*Merge Compose files*) y perfiles (*Using profiles with Compose*), y se verificó sintácticamente con el parser de PowerShell (`0 errors`) y `docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml config --quiet`. |
| **Referencias** | • Docker Documentation. (2024). *Merge Compose files*. Docker Inc. https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/<br>• Docker Documentation. (2024). *Using profiles with Compose*. Docker Inc. https://docs.docker.com/compose/how-tos/profiles/ |

---

### Concepto Nro. 4
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 4 |
| **Tema** | Segmentación base de red (`internal: true`), contrato de observabilidad en Nginx y extensibilidad por *override* para integración en paralelo |
| **Idea inicial del equipo** | Al principio valoramos crear dos carpetas separadas (`escenario-vulnerable/` y `escenario-mitigado/`) duplicando el código de los servicios y dejar el formato de logs por defecto de Nginx. |
| **Prompt utilizado en la IA** | "¿Cómo estructurar el repositorio `consultia-cascada` y la configuración de Nginx para aislar la red de backend, facilitar la integración sin conflictos entre P1, P2, P3 y P4, y registrar latencias del gateway frente al upstream?" (Antigravity — Gemini / Claude Sonnet) |
| **Aporte generado por la IA** | "Duplicar el código rompe la comparabilidad entre el 'antes' y el 'después'. Debe usarse un único conjunto de servicios parametrizado por variables de entorno (incluyendo soporte preventivo para `DB_PASSWORD_FILE` y banderas de resiliencia) junto con un archivo *override* (`docker-compose.hardened.yml`). En redes, definir `frontend` (solo para `tester` y `gateway`, único servicio con puerto `8080` publicado al host) y `backend` con `internal: true`. En `services/gateway/default.conf`, definir un `log_format` personalizado con `$request_time` (`rt`) y `$upstream_response_time` (`urt`) para distinguir demoras del cliente frente al bloqueo en `api`." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se aprueba e integra en `docker-compose.yml`, `docker-compose.hardened.yml`, `services/gateway/default.conf`, `services/api/app.py` y `README.md`. Esta decisión se sustenta en la documentación oficial del módulo `ngx_http_log_module` de Nginx, el principio de microsegmentación del estándar NIST SP 800-207 (*Zero Trust Architecture*) y las buenas prácticas de infraestructura reproducible. Su eficacia quedó validada en la práctica al permitir que P2 (PR #1), P3 (PR #2) y P4 (PR #3) integraran sus bloques sobre la misma base manteniendo total compatibilidad. |
| **Referencias** | • National Institute of Standards and Technology. (2020). *Zero Trust Architecture* (NIST Special Publication 800-207). U.S. Department of Commerce. https://doi.org/10.6028/NIST.SP.800-207<br>• Nginx Documentation. (2024). *Module ngx_http_log_module*. F5, Inc. https://nginx.org/en/docs/http/ngx_http_log_module.html<br>• Docker Documentation. (2024). *Networking in Compose: Internal networks*. Docker Inc. https://docs.docker.com/compose/networking/ |
