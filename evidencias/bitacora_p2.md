# Bitácora de Validación Cruzada (Uso Crítico de IA) — Persona 2
**Integrante:** Sara Chiriboga  
**Rol:** Persona 2 — Simulación del fallo y métricas  
**Materia:** Sistemas Distribuidos — Universidad de Las Américas  

---

### Concepto Nro. 1
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 1 |
| **Tema** | Aislamiento perimetral y escaneo de redes internas en contenedores |
| **Idea inicial del equipo** | Creíamos que al ejecutar `nmap` desde un contenedor dentro del mismo host de Docker, este podría resolver y escanear todos los puertos de los servicios (`api`, `llm`, `stt`, `db`), ya que todos corren bajo el mismo daemon de Docker. |
| **Prompt utilizado en la IA** | "¿Cómo debe comportarse un escaneo con Nmap desde un contenedor auxiliar (`tester`) en la red `frontend` hacia servicios en una red `backend` configurada con `internal: true` en Docker Compose?" (Gemini) |
| **Aporte generado por la IA** | "Cuando una red en Docker Compose se define como `internal: true`, el daemon de Docker aísla completamente dicha red: restringe el tráfico de entrada/salida externo y no registra los nombres DNS de los contenedores internos en las redes adyacentes. Por tanto, el contenedor `tester` (ubicado únicamente en la red `frontend`) no puede resolver los hostnames de la red interna (`api`, `llm`, `stt`, `db`), resultando en 'Failed to resolve'. Únicamente puede resolver e interactuar con el `gateway`, el cual actúa como host puente (dual-homed) con interfaces en ambas redes. Hacia el gateway, los puertos directos de microservicios aparecen como cerrados o filtrados, y solo el puerto publicado (8080) se detecta como abierto." |
| **Decisión** | Aceptado |
| **Justificación crítica vs. Bibliografía** | Se acepta el aporte de la IA porque describe con exactitud el comportamiento observado empíricamente en la evidencia `antes_01_recon_nmap.png` y `nmap.txt`. Además, eleva técnicamente la justificación basándose en el principio de segmentación de red y arquitectura de confianza cero (Zero Trust Architecture) promovido por el estándar NIST SP 800-207, el cual establece que la visibilidad de la red debe estar compartimentada y ningún componente debe confiar ciegamente en el tráfico perimetral. La literatura de microservicios (Newman, 2021) corrobora que exponer interfaces internas directamente viola el principio de ocultamiento de información y amplía la superficie de ataque. |
| **Referencias** | • National Institute of Standards and Technology. (2020). *Zero Trust Architecture* (NIST Special Publication 800-207). U.S. Department of Commerce. https://doi.org/10.6028/NIST.SP.800-207<br>• Newman, S. (2021). *Building Microservices: Designing Fine-Grained Systems* (2.ª ed.). O'Reilly Media.<br>• Docker Documentation. (2024). *Networking in Compose: Internal networks*. Docker Inc. https://docs.docker.com/compose/networking/ |

---

### Concepto Nro. 2
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 2 |
| **Tema** | Agotamiento del pool de hilos (Thread Starvation) y fallo en cascada |
| **Idea inicial del equipo** | Pensábamos que al sobrecargar de peticiones el endpoint `/consulta` (que invoca al LLM simulado), únicamente ese endpoint fallaría con error o lentitud, mientras que `/citas` (que solo consulta a la base de datos PostgreSQL) y `/health` continuarían respondiendo rápido y sin interrupciones. |
| **Prompt utilizado en la IA** | "¿Por qué en una arquitectura de microservicios un cuello de botella en un servicio dependiente lento (`llm`) termina congelando y botando endpoints completamente independientes como `/citas` o `/health` en una API basada en Flask y Gunicorn?" (ChatGPT) |
| **Aporte generado por la IA** | "El fenómeno ocurre por 'thread starvation' (agotamiento de hilos de trabajo) en el servidor de aplicaciones. Gunicorn, configurado con un número finito de hilos (ej. `-w 1 --threads 8`), comparte ese pool global de 8 hilos para atender todas las solicitudes HTTP entrantes sin distinción de ruta. Si `/consulta` realiza llamadas síncronas hacia `llm` sin definir un timeout de conexión o lectura, cada solicitud concurrente a `/consulta` captura y retiene un hilo de ejecución durante todo el tiempo que `llm` tarde en responder o encolar. Cuando la tasa de peticiones supera la capacidad de atención, los 8 hilos quedan bloqueados simultáneamente. A partir de ese momento, cualquier petición nueva hacia `/citas` o `/health` se encola en el socket del sistema operativo y no es procesada, provocando que el proxy inverso (Nginx) corte la conexión por timeout o devuelva errores, arrastrando a todo el sistema a una indisponibilidad generalizada (fallo en cascada)." |
| **Decisión** | Aceptado |
| **Justificación crítica vs. Bibliografía** | El aporte se aprueba porque fundamenta con precisión la causa raíz del problema que observamos en `resumen.md` y `latencia.png`, donde la disponibilidad de `/citas` cayó del 100 % al 0 % durante la carga de 40 hilos. Esta dinámica se alinea con la literatura clásica de resiliencia en sistemas distribuidos, específicamente el capítulo 22 ("Addressing Cascading Failures") del libro *Site Reliability Engineering* de Google (Beyer et al., 2016), donde se explica que la falta de aislamiento de recursos compartidos (como pools de hilos) propaga fallas locales hacia dependencias no relacionadas. Asimismo, Nygard (2018) en *Release It!* subraya que las llamadas remotas bloqueantes y sin timeout son la causa número uno de colapsos sistémicos. |
| **Referencias** | • Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site Reliability Engineering: How Google Runs Production Systems*. O'Reilly Media.<br>• Nygard, M. T. (2018). *Release It!: Design and Deploy Production-Ready Software* (2.ª ed.). Pragmatic Bookshelf.<br>• Tanenbaum, A. S., & Van Steen, M. (2017). *Distributed Systems: Principles and Paradigms* (3.ª ed.). CreateSpace Independent Publishing Platform. |

---

### Concepto Nro. 3
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 3 |
| **Tema** | Metodología de medición de resiliencia y diseño de pruebas de carga empíricas |
| **Idea inicial del equipo** | Para demostrar la cascada, creíamos que bastaba con enviar muchas peticiones con un bucle simple en Python durante un tiempo indeterminado y verificar visualmente si aparecían errores en la terminal. |
| **Prompt utilizado en la IA** | "¿Cuáles son las etapas y métricas estadísticas indispensables que debe tener un script de prueba controlada para cuantificar formalmente un fallo en cascada y permitir una comparación válida antes y después de aplicar mitigaciones?" (Claude) |
| **Aporte generado por la IA** | "Para evaluar empíricamente la resiliencia en sistemas distribuidos se requiere un protocolo estructurado en tres fases temporales fijas: 1) Línea base (*baseline*): tráfico nominal para medir la latencia y disponibilidad normal en estado saludable; 2) Fase de estrés/carga: saturación controlada contra el endpoint crítico con concurrencia fija para forzar la contención de recursos; 3) Fase de recuperación (*recovery window*): cese de la carga agresiva manteniendo únicamente el sondeo para registrar el tiempo que tarda el sistema en estabilizarse (Time to Recovery o TTR). En cuanto a las métricas, nunca debe utilizarse el promedio de latencia debido a que las distribuciones en fallos en cascada presentan colas pesadas (*fat-tail*); deben calcularse percentiles no paramétricos como la mediana (p50) y el percentil 95 (p95), además del porcentaje de disponibilidad (códigos 200), tasa de rechazo preventivo (429) y tasa de fallos de servidor (5xx/timeouts)." |
| **Decisión** | Aceptado e integrado |
| **Justificación crítica vs. Bibliografía** | Se acepta el criterio de la IA y se utilizó directamente para estructurar `tester/scenario.py` y `tester/analyze.py`. La bibliografía especializada en ingeniería de rendimiento y fiabilidad de software respalda que evaluar la latencia por promedio oculta la degradación extrema que sufren los usuarios en el percentil 95 y 99 (Kleppmann, 2017; Beyer et al., 2016). Adicionalmente, el concepto de tiempo de recuperación es vital: en nuestra prueba (`evidencias/antes/resumen.md`), el sistema demostró un estado metaestable (*metastable failure state*) al no lograr recuperarse de forma autónoma durante los 30 segundos posteriores al cese de la carga, lo que confirma la necesidad de implementar circuit breakers y bulkheads en la fase de endurecimiento. |
| **Referencias** | • Kleppmann, M. (2017). *Designing Data-Intensive Applications: The Big Ideas Behind Reliable, Scalable, and Maintainable Systems*. O'Reilly Media.<br>• Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site Reliability Engineering: How Google Runs Production Systems*. O'Reilly Media.<br>• Coulouris, G., Dollimore, J., Kindberg, T., & Blair, G. (2012). *Distributed Systems: Concepts and Design* (5.ª ed.). Addison-Wesley. |

---

### Concepto Nro. 4
| Campo | Detalle |
|---|---|
| **Concepto Nro.** | 4 |
| **Tema** | Semántica de errores en Gateways y origen del código HTTP 499 |
| **Idea inicial del equipo** | Al revisar los logs del Gateway Nginx durante la falla, esperábamos ver exclusivamente códigos estándar HTTP 504 (*Gateway Timeout*) o HTTP 502 (*Bad Gateway*), pero observamos masivamente el código `499`. Inicialmente creímos que se trataba de un error de configuración de Nginx. |
| **Prompt utilizado en la IA** | "En los logs de acceso de un proxy Nginx que redirige tráfico hacia una API saturada, ¿qué significa exactamente el código HTTP 499 con tiempos `rt=5.008 urt=5.008` y cómo se diferencia de un 504 Gateway Timeout?" (Gemini) |
| **Aporte generado por la IA** | "El código HTTP 499 ('Client Closed Request') es un pseudocódigo de estado no estándar introducido por Nginx. No indica un error interno de Nginx, sino que el cliente cerró voluntariamente la conexión TCP antes de que Nginx pudiera entregarle la respuesta del upstream. La diferencia con el error 504 es quién toma la iniciativa de cortar la conexión: en un 504, es el propio Nginx quien alcanza su directiva `proxy_read_timeout` y decide abortar la espera al backend enviando un mensaje de error al cliente; en un 499, el cliente (en este caso el script de Python con `requests.get(..., timeout=5)`) alcanza su propio tiempo límite de 5 segundos y envía un paquete TCP FIN/RST para desconectarse mientras Nginx todavía aguardaba por la API. Los valores `rt=5.008` (tiempo total de la petición) y `urt=5.008` (tiempo esperando al upstream) demuestran que el cliente esperó exactamente sus 5 segundos de tolerancia antes de abandonar." |
| **Decisión** | Aceptado |
| **Justificación crítica vs. Bibliografía** | El aporte se acepta sin reservas porque clarifica un comportamiento técnico clave que se evidencia en la captura `antes_logs_cascada.png`. Tras contrastarlo con la documentación oficial del módulo HTTP Core de Nginx y la especificación de protocolos de transporte y aplicación (RFC 9110 / Fielding et al., 2022), se comprueba que cuando un cliente implementa timeouts más restrictivos que los del intermediario (proxy), la terminación anticipada de sockets TCP es la conducta esperada en redes distribuidas. Esto demuestra empíricamente la asincronía y el desacoplamiento de tiempos entre las capas cliente, gateway y servicio interno. |
| **Referencias** | • Nginx Documentation. (2024). *Module ngx_http_core_module: Embedded Variables and Status Codes*. F5, Inc. https://nginx.org/en/docs/http/ngx_http_core_module.html<br>• Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP Semantics* (RFC 9110). Internet Engineering Task Force (IETF). https://doi.org/10.17487/RFC9110<br>• Tanenbaum, A. S., & Wetherall, D. J. (2011). *Computer Networks* (5.ª ed.). Pearson. |
