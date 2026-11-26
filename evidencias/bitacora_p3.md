# Bitácora de Validación Cruzada (Uso Crítico de IA) — Persona 3
**Integrante:** Johann Vásquez  
**Rol:** Persona 3 — Resiliencia, contención de fallos y degradación elegante  
**Materia:** Sistemas Distribuidos — Universidad de Las Américas  

---

### Concepto Nro. 1
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 1 |
| **Tema** | Descarte temprano de carga (*Load Shedding*) y limitación de tasa/conexiones en el API Gateway |
| **Idea inicial del equipo** | Pensábamos que aplicar un límite global de peticiones en Nginx sobre todo el dominio (`location /`) bastaría para frenar la saturación hacia el backend sin afectar las consultas médicas ni los chequeos de salud. |
| **Prompt utilizado en la IA** | "¿Cómo configurar `limit_req` y `limit_conn` en Nginx (`default.hardened.conf`) para proteger únicamente el endpoint crítico `/consulta` frente a ráfagas concurrentes sin penalizar `/citas` ni `/health`, y qué código y cabeceras HTTP estándar deben devolverse al cliente?" (Gemini) |
| **Aporte generado por la IA** | "Aplicar `limit_req` de forma indiscriminada en `location /` bloquea tráfico legítimo de endpoints livianos cuando un cliente o atacante satura una ruta pesada. En Nginx debe definirse un bloque específico `location = /consulta` con su propia zona compartida (`limit_req_zone ... zone=consulta_req:10m rate=5r/s` y `limit_conn_zone ... zone=consulta_conn:10m`), estableciendo `limit_req_status 429;` y `limit_conn_status 429;`, además de inyectar la cabecera `add_header Retry-After 2 always;` en la respuesta de error. De esta manera, el exceso de solicitudes se descarta en el borde en ~0 ms (`rt=0.000`) antes de consumir hilos en Gunicorn, mientras `/citas` y `/health` mantienen su flujo libre." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se acepta e integra en `services/gateway/default.hardened.conf`. En las evidencias `03_p3_rafaga_429_503.png` y `05_p3_recuperacion_y_logs.png` se verificó que ante una ráfaga de 20 hilos concurrentes, Nginx descartó el excedente (`excess: 6.935 by zone "consulta_req"`) devolviendo `HTTP 429` con `Retry-After: 2` en `0.000 s`, mientras `/citas` (`rt=0.007 s`) y `/health` (`rt=0.001 s`) mantuvieron disponibilidad del 100 %. Esta decisión se respalda en la literatura de ingeniería de fiabilidad (Beyer et al., 2016, cap. 21 "Handling Overload"), donde se establece que el *load shedding* perimetral con señalización explícita (`Retry-After`, RFC 9110) evita que la cola del servidor de aplicaciones se sature. |
| **Referencias** | • Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site Reliability Engineering: How Google Runs Production Systems*. O'Reilly Media.<br>• Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP Semantics* (RFC 9110, Sección 15.5.29 & 10.2.3). Internet Engineering Task Force (IETF). https://doi.org/10.17487/RFC9110<br>• Nginx Documentation. (2024). *Module ngx_http_limit_req_module*. F5, Inc. https://nginx.org/en/docs/http/ngx_http_limit_req_module.html |

---

### Concepto Nro. 2
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 2 |
| **Tema** | Aislamiento de recursos mediante patrón *Bulkhead* (mamparo) con `BoundedSemaphore` |
| **Idea inicial del equipo** | Creíamos que limitar las peticiones en Nginx era suficiente para evitar que los 8 hilos de Gunicorn se bloquearan, sin necesidad de restringir internamente cuántas llamadas simultáneas puede abrir `api` hacia el microservicio lento `llm`. |
| **Prompt utilizado en la IA** | "En una API Python/Flask servida con Gunicorn (`--threads 8`) donde un microservicio dependiente (`llm`) tiene `MAX_CONCURRENCY=2` y latencia de 2000 ms, ¿por qué sigue existiendo riesgo de agotamiento de hilos si no se implementa un *bulkhead* interno, y cómo dimensionarlo con `threading.BoundedSemaphore`?" (Gemini) |
| **Aporte generado por la IA** | "Incluso con rate limiting en el gateway, las peticiones que logran pasar la ráfaga inicial pueden acumularse esperando respuesta de `llm` si este tarda 2 segundos por solicitud. Si 8 peticiones entran casi simultáneamente, los 8 hilos de Gunicorn quedan retenidos en I/O bloqueante hacia `llm`, dejando cero hilos libres para `/citas` o `/health`. Un *bulkhead* mediante `threading.BoundedSemaphore(LLM_BULKHEAD)` (por ejemplo, `LLM_BULKHEAD=4`) acota el máximo de hilos de la API que pueden invocar a `llm` concurrentemente, reservando al menos la mitad del pool de Gunicorn para rutas independientes. Si el semáforo no se adquiere de inmediato (`acquire(blocking=False)`), la API rechaza rápido (*fail-fast*) devolviendo `HTTP 503` (`bulkhead_full`) con `Retry-After`." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se aprueba e implementa en `services/api/resilience.py` con `LLM_BULKHEAD=4`. Empíricamente, en `05_p3_recuperacion_y_logs.png` se registraron las trazas `[bulkhead:llm] capacidad agotada (limite=4); rechazando solicitud rapido`, demostrando que el excedente que supera el límite de 4 hilos concurrentes falla en milisegundos sin secuestrar los 4 hilos restantes de Gunicorn. Nygard (2018) en *Release It!* formaliza el patrón *Bulkhead* (inspirado en compartimentos estancos navales) como mecanismo esencial para contener daños y garantizar que la saturación de un componente no hunda toda la capacidad de cómputo del proceso anfitrión. |
| **Referencias** | • Nygard, M. T. (2018). *Release It!: Design and Deploy Production-Ready Software* (2.ª ed.). Pragmatic Bookshelf.<br>• Newman, S. (2021). *Building Microservices: Designing Fine-Grained Systems* (2.ª ed.). O'Reilly Media.<br>• Python Software Foundation. (2024). *threading — Thread-based parallelism: BoundedSemaphore*. https://docs.python.org/3/library/threading.html |

---

### Concepto Nro. 3
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 3 |
| **Tema** | Prevención de tormentas de reintentos mediante *Exponential Backoff* con *Jitter* y *Timeouts* acotados |
| **Idea inicial del equipo** | Al añadir tolerancia a fallos en las llamadas HTTP hacia `llm`, inicialmente pensamos en configurar 3 reintentos inmediatos cada vez que ocurriera un `ReadTimeout`, asumiendo que reintentar rápido aumentaría la tasa de éxito. |
| **Prompt utilizado en la IA** | "¿Qué riesgo introduce reintentar inmediatamente o con intervalos fijos cuando un servicio `llm` falla por `ReadTimeout` bajo alta concurrencia, y cómo deben calibrarse `LLM_TIMEOUT`, `LLM_MAX_RETRIES` y el *jitter* en `resilience.py`?" (Gemini) |
| **Aporte generado por la IA** | "Los reintentos inmediatos o deterministas bajo saturación producen una 'tormenta de reintentos' (*retry storm* o efecto *thundering herd*): múltiples hilos fallan al mismo instante por timeout y vuelven a golpear sincronizadamente al servicio ya colapsado, multiplicando la carga y prolongando la indisponibilidad. La práctica recomendada es: 1) fijar timeouts estrictos de conexión y lectura (`CONNECT_TIMEOUT=1.0`, `STT_TIMEOUT=1.0`, `LLM_TIMEOUT=2.5`, ligeramente por encima de los 2000 ms nominales de `llm`); 2) limitar el número de reintentos (`LLM_MAX_RETRIES=1`); y 3) aplicar *backoff* exponencial con *full jitter* aleatorio (`random.uniform(0, base * 2**attempt)`) para dispersar temporalmente las solicitudes." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se acepta e integra en `services/api/resilience.py`. En los logs de `api-1` (`05_p3_recuperacion_y_logs.png`) se observa cómo ante fallos simultáneos de lectura, los hilos aplican retardos desincronizados (`[retry:llm] fallo intento 1/2 (ReadTimeout); reintentando en 0.37s` y `en 0.28s`), evitando colisiones sincronizadas. Esta estrategia está fundamentada en el análisis matemático de Brooker (2015) en AWS Architecture ("Exponential Backoff And Jitter") y en Kleppmann (2017), quienes demuestran que los reintentos sin aleatorización (*jitter*) amplifican la congestión en sistemas distribuidos en lugar de aliviarla. |
| **Referencias** | • Brooker, M. (2015). *Exponential Backoff And Jitter*. Amazon Web Services Architecture Blog. https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/<br>• Kleppmann, M. (2017). *Designing Data-Intensive Applications: The Big Ideas Behind Reliable, Scalable, and Maintainable Systems*. O'Reilly Media.<br>• Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site Reliability Engineering: How Google Runs Production Systems*. O'Reilly Media. |

---

### Concepto Nro. 4
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 4 |
| **Tema** | Máquina de estados del *Circuit Breaker* (`pybreaker`) y degradación elegante (*Graceful Degradation*) |
| **Idea inicial del equipo** | Pensábamos que cuando `llm` fallara repetidamente, `/consulta` debía seguir intentando llamarlo en cada petición o devolver un error genérico `500 Internal Server Error` descartando también lo que ya había procesado el servicio `stt`. |
| **Prompt utilizado en la IA** | "¿Cómo integrar un *Circuit Breaker* (`pybreaker`) sobre el cliente `llm` en Flask para cortar llamadas a un downstream degradado, permitir su recuperación automática y devolver una respuesta parcialmente degradada aprovechando el resultado exitoso de `stt`?" (Gemini) |
| **Aporte generado por la IA** | "El patrón *Circuit Breaker* actúa como una máquina de estados finitos con tres estados: `CLOSED` (flujo normal), `OPEN` (tras alcanzar `CB_FAILURE_THRESHOLD=3` fallos consecutivos, rechaza instantáneamente sin invocar a `llm` durante `CB_RESET_SECONDS=10.0` para dejar que el servicio drene su cola) y `HALF_OPEN` (transcurridos los 10 s, deja pasar una petición de prueba; si tiene éxito cierra el circuito `CLOSED`, si falla vuelve a `OPEN`). Complementariamente, en `/consulta`, dado que `stt` responde en ~100 ms antes de invocar a `llm`, cuando el breaker está abierto o `llm` falla se debe aplicar degradación elegante: retornar `HTTP 503` con `Retry-After` incluyendo el objeto `stt` ya transcrito y `"llm": null` (`degraded: true`), preservando el valor parcial obtenido." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se aprueba e implementa en `services/api/resilience.py` y `services/api/app.py` con `pybreaker==1.4.0`. Las pruebas en `03_p3_rafaga_429_503.png` y `05_p3_recuperacion_y_logs.png` validaron el ciclo completo de estados: apertura tras `3/3` fallos (`CLOSED -> OPEN`), entrega de respuesta parcial con transcripción `stt` y `Retry-After`, transición a `HALF_OPEN` tras `10.0s` y retorno autónomo a `CLOSED` con `HTTP 200` (`rt=2.106 s`), eliminando el estado de fallo metaestable observado antes de mitigar. Tanto Fowler (2014) en su especificación del patrón *Circuit Breaker* como Nygard (2018) destacan que cortar el tráfico hacia un recurso saturado y degradar funcionalidades no esenciales es indispensable para la autorrecuperación del sistema. |
| **Referencias** | • Fowler, M. (2014). *CircuitBreaker*. martinfowler.com. https://martinfowler.com/bliki/CircuitBreaker.html<br>• Nygard, M. T. (2018). *Release It!: Design and Deploy Production-Ready Software* (2.ª ed.). Pragmatic Bookshelf.<br>• Tanenbaum, A. S., & Van Steen, M. (2017). *Distributed Systems: Principles and Paradigms* (3.ª ed.). CreateSpace Independent Publishing Platform. |
